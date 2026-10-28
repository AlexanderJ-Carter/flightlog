"""本地观测库 fleet.db：呼号沉淀 + OpenSky 机尾。

参考数据（机场/航司/航线/FAA 等）在 catalog.db，见 catalog_db。
"""
from __future__ import annotations

import os
import re
import sqlite3
import threading
import time

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.environ.get("FLIGHTLOG_DATA_DIR", os.path.join(BASE_DIR, "data"))
FLEET_DB = os.path.join(DATA_DIR, "fleet.db")

_lock = threading.Lock()
_ready = False


def _connect():
    os.makedirs(os.path.dirname(FLEET_DB) or ".", exist_ok=True)
    conn = sqlite3.connect(FLEET_DB, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("PRAGMA temp_store=MEMORY")
    conn.execute("PRAGMA mmap_size=67108864")
    conn.execute("PRAGMA cache_size=-16384")
    conn.execute("PRAGMA busy_timeout=10000")
    return conn


def init():
    """建表（幂等）。"""
    global _ready
    with _lock:
        with _connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS sightings(
                    flight TEXT PRIMARY KEY,
                    aircraft TEXT NOT NULL DEFAULT '',
                    registration TEXT NOT NULL DEFAULT '',
                    hex TEXT NOT NULL DEFAULT '',
                    operator TEXT NOT NULL DEFAULT '',
                    photo TEXT NOT NULL DEFAULT '',
                    source TEXT NOT NULL DEFAULT '',
                    seen_at REAL NOT NULL
                );
                CREATE TABLE IF NOT EXISTS aircraft(
                    hex TEXT PRIMARY KEY,
                    registration TEXT NOT NULL DEFAULT '',
                    typecode TEXT NOT NULL DEFAULT '',
                    model TEXT NOT NULL DEFAULT '',
                    operator TEXT NOT NULL DEFAULT '',
                    country TEXT NOT NULL DEFAULT '',
                    updated_at REAL NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_ac_reg ON aircraft(registration);
                CREATE TABLE IF NOT EXISTS meta(
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL DEFAULT ''
                );
                """
            )
            # 旧版曾把 OpenFlights/OurAirports 放在 fleet；现已迁 catalog，清掉空壳表
            for _t in (
                "of_airlines", "of_routes", "plane_types",
                "oa_airports", "oa_runways", "oa_frequencies", "oa_navaids",
                "faa_registry", "data_sources", "icao_types", "reg_prefixes",
                "ref_airline_codes", "metar_codes", "squawk_codes",
            ):
                row = conn.execute(
                    "SELECT 1 FROM sqlite_master WHERE type=? AND name=?",
                    ("table", _t),
                ).fetchone()
                if not row:
                    continue
                n = conn.execute(f"SELECT COUNT(*) AS n FROM [{_t}]").fetchone()["n"]
                if int(n) == 0:
                    conn.execute(f"DROP TABLE IF EXISTS [{_t}]")
        _ready = True



def get_meta(key: str, default: str = "") -> str:
    _ensure()
    with _lock:
        with _connect() as conn:
            row = conn.execute(
                "SELECT value FROM meta WHERE key=?", (key,)
            ).fetchone()
    return row["value"] if row else default


def get_meta_float(key: str, default: float = 0.0) -> float:
    raw = get_meta(key, "")
    if not raw:
        return default
    return float(raw)


def set_meta(key: str, value: str) -> None:
    _ensure()
    with _lock:
        with _connect() as conn:
            conn.execute(
                "INSERT INTO meta(key, value) VALUES(?,?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (key, str(value)),
            )


def _ensure():
    if not _ready:
        init()


def remember_sighting(
    flight: str,
    *,
    aircraft: str = "",
    registration: str = "",
    hex_code: str = "",
    operator: str = "",
    photo: str = "",
    source: str = "live",
) -> None:
    """把「航班号 → 最近机尾」写入本地库（覆盖更新）。"""
    fl = re.sub(r"\s+", "", flight or "").upper()
    if not fl:
        return
    ac = (aircraft or "").strip()
    reg = (registration or "").strip().upper()
    hx = re.sub(r"[^0-9A-Fa-f]", "", hex_code or "").upper()
    if not ac and not reg and not hx:
        return
    _ensure()
    with _lock:
        with _connect() as conn:
            conn.execute(
                """INSERT INTO sightings(
                       flight, aircraft, registration, hex, operator, photo, source, seen_at
                   ) VALUES(?,?,?,?,?,?,?,?)
                   ON CONFLICT(flight) DO UPDATE SET
                       aircraft=excluded.aircraft,
                       registration=excluded.registration,
                       hex=excluded.hex,
                       operator=excluded.operator,
                       photo=CASE WHEN excluded.photo!='' THEN excluded.photo
                                  ELSE sightings.photo END,
                       source=excluded.source,
                       seen_at=excluded.seen_at
                """,
                (
                    fl, ac, reg, hx, (operator or "").strip(),
                    (photo or "").strip(), source, time.time(),
                ),
            )
            if hx and (ac or reg):
                conn.execute(
                    """INSERT INTO aircraft(
                           hex, registration, typecode, model, operator, country, updated_at
                       ) VALUES(?,?,?,?,?,?,?)
                       ON CONFLICT(hex) DO UPDATE SET
                           registration=CASE WHEN excluded.registration!=''
                               THEN excluded.registration ELSE aircraft.registration END,
                           typecode=CASE WHEN excluded.typecode!=''
                               THEN excluded.typecode ELSE aircraft.typecode END,
                           operator=CASE WHEN excluded.operator!=''
                               THEN excluded.operator ELSE aircraft.operator END,
                           updated_at=excluded.updated_at
                    """,
                    (hx, reg, ac, "", (operator or "").strip(), "", time.time()),
                )


def lookup_flight(flight: str) -> dict | None:
    """按航班号取最近观测到的机尾信息。"""
    fl = re.sub(r"\s+", "", flight or "").upper()
    if not fl:
        return None
    _ensure()
    with _lock:
        with _connect() as conn:
            row = conn.execute(
                "SELECT * FROM sightings WHERE flight=?", (fl,)
            ).fetchone()
    if not row:
        return None
    return {
        "flight": row["flight"],
        "aircraft": row["aircraft"] or "",
        "registration": row["registration"] or "",
        "hex": row["hex"] or "",
        "operator": row["operator"] or "",
        "photo": row["photo"] or "",
        "source": "fleet:" + (row["source"] or "local"),
        "seen_at": row["seen_at"],
    }


def lookup_hex(hex_code: str) -> dict | None:
    """按 Mode-S hex 查本地机尾库（观测 / OpenSky / FAA）。"""
    hx = re.sub(r"[^0-9A-Fa-f]", "", hex_code or "").upper()
    if len(hx) < 6:
        return None
    hx = hx[-6:]
    _ensure()
    with _lock:
        with _connect() as conn:
            row = conn.execute(
                "SELECT * FROM aircraft WHERE hex=?", (hx,)
            ).fetchone()
            if row:
                return {
                    "hex": row["hex"],
                    "aircraft": row["typecode"] or "",
                    "aircraft_name": row["model"] or "",
                    "registration": row["registration"] or "",
                    "operator": row["operator"] or "",
                    "country": row["country"] or "",
                    "source": "fleet:aircraft",
                }
    import catalog_db
    faa = catalog_db.lookup_faa_hex(hx)
    if not faa:
        return None
    return {
        "hex": faa["hex"],
        "aircraft": "",
        "aircraft_name": faa.get("aircraft_name") or "",
        "registration": faa.get("registration") or "",
        "operator": faa.get("operator") or "",
        "country": "US",
        "source": "catalog:faa",
    }


def stats() -> dict:
    """观测库规模；航司/航线见 catalog.stats()['counts']['net']。"""
    _ensure()
    with _lock:
        with _connect() as conn:
            sightings = conn.execute("SELECT COUNT(*) c FROM sightings").fetchone()["c"]
            aircraft = conn.execute("SELECT COUNT(*) c FROM aircraft").fetchone()["c"]
    import catalog_db
    net = catalog_db.stats()["counts"]["net"]
    return {
        "sightings": sightings,
        "aircraft": aircraft,
        "airlines": net.get("net_airlines", 0),
        "routes": net.get("net_routes", 0),
        "plane_types": net.get("net_plane_types", 0),
    }


def replace_airlines(rows: list[tuple]) -> int:
    """航司写入 catalog.net_airlines。"""
    import catalog_db
    return catalog_db.replace_airlines(rows)


def replace_routes(rows: list[tuple]) -> int:
    """航线写入 catalog.net_routes。"""
    import catalog_db
    return catalog_db.replace_routes(rows)


def airline_name(iata: str) -> str:
    import catalog_db
    return catalog_db.airline_name(iata)


def replace_plane_types(rows: list[tuple]) -> int:
    """机型名录写入 catalog.net_plane_types。"""
    import catalog_db
    return catalog_db.replace_plane_types(rows)


def plane_type_name(code: str) -> str:
    import catalog_db
    info = catalog_db.resolve_aircraft(code)
    return (info.get("name") or "").strip()


def typical_equipment(from_ap: str, to_ap: str, flight: str = "") -> dict | None:
    """航线常用机型（catalog.net_routes）。"""
    import catalog_db
    frm = (from_ap or "").strip().upper()
    to = (to_ap or "").strip().upper()
    if len(frm) != 3 or len(to) != 3:
        return None
    airline = re.sub(r"\s+", "", flight or "").upper()[:2]
    catalog_db.init()
    with catalog_db._lock:
        with catalog_db._connect() as conn:
            row = None
            if len(airline) == 2:
                row = conn.execute(
                    "SELECT equipment, equipment_all, airline FROM net_routes "
                    "WHERE airline=? AND from_ap=? AND to_ap=?",
                    (airline, frm, to),
                ).fetchone()
            if not row:
                row = conn.execute(
                    "SELECT equipment, equipment_all, airline FROM net_routes "
                    "WHERE from_ap=? AND to_ap=? AND equipment!='' LIMIT 1",
                    (frm, to),
                ).fetchone()
    if not row or not (row["equipment"] or "").strip():
        return None
    return {
        "aircraft": row["equipment"].strip(),
        "equipment_all": row["equipment_all"] or "",
        "airline": row["airline"],
        "source": "catalog:openflights",
    }


def network_routes(
    airports: list[str] | None = None,
    airline: str = "",
    limit: int = 200,
) -> list[dict]:
    """给地图用的参考航线（catalog.net_routes）。"""
    import catalog_db
    return catalog_db.network_routes(
        airports=airports, airline=airline, limit=limit,
    )


def upsert_aircraft_rows(rows: list[tuple]) -> int:
    """批量写入 OpenSky 导入行：(hex, reg, typecode, model, operator, country)。"""
    if not rows:
        return 0
    _ensure()
    now = time.time()
    with _lock:
        with _connect() as conn:
            conn.executemany(
                """INSERT INTO aircraft(
                       hex, registration, typecode, model, operator, country, updated_at
                   ) VALUES(?,?,?,?,?,?,?)
                   ON CONFLICT(hex) DO UPDATE SET
                       registration=excluded.registration,
                       typecode=excluded.typecode,
                       model=excluded.model,
                       operator=excluded.operator,
                       country=excluded.country,
                       updated_at=excluded.updated_at
                """,
                [(h, r, t, m, o, c, now) for h, r, t, m, o, c in rows],
            )
            return len(rows)



def airport_catalog(iata: str = "", icao: str = "") -> dict | None:
    """机场详情（委托 catalog.db）。"""
    import catalog_db
    code = (iata or icao or "").strip().upper()
    return catalog_db.airport_detail(code) if code else None


def catalog_stats() -> dict:
    """参考库分层统计（委托 catalog.db）。"""
    import catalog_db
    return catalog_db.stats()
