"""自建航空参考库（catalog.db）——分层、可全量刷新。

分层约定（表名前缀即层级）：

  geo_   地理：国家 / 行政区 / 机场 / 跑道 / 频率 / 导航台
  net_   网络：航司 / 航线 / 机型名录
  reg_   登记：FAA / 国籍前缀 / ICAO 机型代号
  lex_   词典：METAR 缩写 / 应答机代码
  meta_  元数据：各数据源导入记录

观测机尾与呼号沉淀仍在 fleet.db，不混入本库。
"""
from __future__ import annotations

import os
import sqlite3
import threading
import time

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.environ.get("FLIGHTLOG_DATA_DIR", os.path.join(BASE_DIR, "data"))
CATALOG_DB = os.path.join(DATA_DIR, "catalog.db")

_lock = threading.Lock()
_ready = False

# 层级说明（API / 文档共用）
LAYERS = {
    "geo": "地理：国家、行政区、机场及附属设施",
    "net": "网络：航司、航线、机型名录",
    "reg": "登记：FAA、国籍前缀、ICAO 机型代号",
    "lex": "词典：METAR / 应答机代码",
    "meta": "元数据：导入来源与时间",
}


def _connect():
    os.makedirs(os.path.dirname(CATALOG_DB) or ".", exist_ok=True)
    conn = sqlite3.connect(CATALOG_DB, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    return conn


def init() -> None:
    """建表（幂等）。"""
    global _ready
    with _lock:
        with _connect() as conn:
            if not _ready:
                conn.executescript(
                """
                -- ========== geo ==========
                CREATE TABLE IF NOT EXISTS geo_countries(
                    code TEXT PRIMARY KEY,
                    name TEXT NOT NULL DEFAULT '',
                    continent TEXT NOT NULL DEFAULT '',
                    wikipedia TEXT NOT NULL DEFAULT ''
                );
                CREATE TABLE IF NOT EXISTS geo_regions(
                    code TEXT PRIMARY KEY,
                    name TEXT NOT NULL DEFAULT '',
                    iso_country TEXT NOT NULL DEFAULT '',
                    continent TEXT NOT NULL DEFAULT '',
                    wikipedia TEXT NOT NULL DEFAULT ''
                );
                CREATE INDEX IF NOT EXISTS idx_geo_reg_country
                    ON geo_regions(iso_country);

                CREATE TABLE IF NOT EXISTS geo_airports(
                    icao TEXT PRIMARY KEY,
                    iata TEXT NOT NULL DEFAULT '',
                    ident TEXT NOT NULL DEFAULT '',
                    name TEXT NOT NULL DEFAULT '',
                    name_zh TEXT NOT NULL DEFAULT '',
                    type TEXT NOT NULL DEFAULT '',
                    lat REAL,
                    lon REAL,
                    elevation_ft INTEGER,
                    continent TEXT NOT NULL DEFAULT '',
                    iso_country TEXT NOT NULL DEFAULT '',
                    iso_region TEXT NOT NULL DEFAULT '',
                    municipality TEXT NOT NULL DEFAULT '',
                    timezone TEXT NOT NULL DEFAULT '',
                    scheduled INTEGER NOT NULL DEFAULT 0,
                    gps_code TEXT NOT NULL DEFAULT '',
                    local_code TEXT NOT NULL DEFAULT '',
                    wikipedia TEXT NOT NULL DEFAULT '',
                    home_link TEXT NOT NULL DEFAULT '',
                    keywords TEXT NOT NULL DEFAULT ''
                );
                CREATE INDEX IF NOT EXISTS idx_geo_ap_iata ON geo_airports(iata);
                CREATE INDEX IF NOT EXISTS idx_geo_ap_country ON geo_airports(iso_country);
                CREATE INDEX IF NOT EXISTS idx_geo_ap_type ON geo_airports(type);
                CREATE INDEX IF NOT EXISTS idx_geo_ap_city ON geo_airports(municipality);

                CREATE TABLE IF NOT EXISTS geo_runways(
                    airport_icao TEXT NOT NULL,
                    le_ident TEXT NOT NULL DEFAULT '',
                    he_ident TEXT NOT NULL DEFAULT '',
                    length_ft INTEGER,
                    width_ft INTEGER,
                    surface TEXT NOT NULL DEFAULT '',
                    lighted INTEGER NOT NULL DEFAULT 0,
                    closed INTEGER NOT NULL DEFAULT 0,
                    PRIMARY KEY (airport_icao, le_ident, he_ident)
                );
                CREATE INDEX IF NOT EXISTS idx_geo_rwy ON geo_runways(airport_icao);

                CREATE TABLE IF NOT EXISTS geo_frequencies(
                    airport_icao TEXT NOT NULL,
                    type TEXT NOT NULL DEFAULT '',
                    description TEXT NOT NULL DEFAULT '',
                    frequency_mhz REAL,
                    PRIMARY KEY (airport_icao, type, description, frequency_mhz)
                );
                CREATE INDEX IF NOT EXISTS idx_geo_freq ON geo_frequencies(airport_icao);

                CREATE TABLE IF NOT EXISTS geo_navaids(
                    ident TEXT NOT NULL,
                    name TEXT NOT NULL DEFAULT '',
                    type TEXT NOT NULL DEFAULT '',
                    frequency_khz REAL,
                    lat REAL,
                    lon REAL,
                    iso_country TEXT NOT NULL DEFAULT '',
                    associated_airport TEXT NOT NULL DEFAULT '',
                    PRIMARY KEY (ident, type, associated_airport)
                );
                CREATE INDEX IF NOT EXISTS idx_geo_nav_ap
                    ON geo_navaids(associated_airport);

                -- ========== net ==========
                CREATE TABLE IF NOT EXISTS net_airlines(
                    iata TEXT PRIMARY KEY,
                    icao TEXT NOT NULL DEFAULT '',
                    name TEXT NOT NULL DEFAULT '',
                    country TEXT NOT NULL DEFAULT '',
                    callsign TEXT NOT NULL DEFAULT '',
                    active INTEGER NOT NULL DEFAULT 1
                );
                CREATE TABLE IF NOT EXISTS net_routes(
                    airline TEXT NOT NULL,
                    from_ap TEXT NOT NULL,
                    to_ap TEXT NOT NULL,
                    equipment TEXT NOT NULL DEFAULT '',
                    equipment_all TEXT NOT NULL DEFAULT '',
                    PRIMARY KEY (airline, from_ap, to_ap)
                );
                CREATE INDEX IF NOT EXISTS idx_net_route_od
                    ON net_routes(from_ap, to_ap);
                CREATE TABLE IF NOT EXISTS net_plane_types(
                    iata TEXT PRIMARY KEY,
                    icao TEXT NOT NULL DEFAULT '',
                    name TEXT NOT NULL DEFAULT ''
                );

                -- ========== reg ==========
                CREATE TABLE IF NOT EXISTS reg_faa(
                    n_number TEXT PRIMARY KEY,
                    hex TEXT NOT NULL DEFAULT '',
                    mfr_mdl TEXT NOT NULL DEFAULT '',
                    year_mfr TEXT NOT NULL DEFAULT '',
                    registrant TEXT NOT NULL DEFAULT '',
                    city TEXT NOT NULL DEFAULT '',
                    state TEXT NOT NULL DEFAULT '',
                    status TEXT NOT NULL DEFAULT '',
                    type_aircraft TEXT NOT NULL DEFAULT '',
                    updated_at REAL NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_reg_faa_hex ON reg_faa(hex);
                CREATE TABLE IF NOT EXISTS reg_prefixes(
                    prefix TEXT PRIMARY KEY,
                    country TEXT NOT NULL DEFAULT '',
                    note TEXT NOT NULL DEFAULT ''
                );
                CREATE TABLE IF NOT EXISTS reg_icao_types(
                    designator TEXT PRIMARY KEY,
                    name TEXT NOT NULL DEFAULT '',
                    manufacturer TEXT NOT NULL DEFAULT '',
                    category TEXT NOT NULL DEFAULT ''
                );

                -- ========== lex ==========
                CREATE TABLE IF NOT EXISTS lex_metar(
                    code TEXT PRIMARY KEY,
                    meaning TEXT NOT NULL DEFAULT ''
                );
                CREATE TABLE IF NOT EXISTS lex_squawk(
                    code TEXT PRIMARY KEY,
                    meaning TEXT NOT NULL DEFAULT ''
                );

                -- ========== meta ==========
                CREATE TABLE IF NOT EXISTS meta_sources(
                    source TEXT PRIMARY KEY,
                    layer TEXT NOT NULL DEFAULT '',
                    rows INTEGER NOT NULL DEFAULT 0,
                    imported_at REAL NOT NULL,
                    note TEXT NOT NULL DEFAULT ''
                );
                CREATE TABLE IF NOT EXISTS meta_kv(
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL DEFAULT ''
                );
                """
                )
            cols = {r[1] for r in conn.execute("PRAGMA table_info(geo_airports)")}
            if "custom" not in cols:
                conn.execute(
                    "ALTER TABLE geo_airports ADD COLUMN custom "
                    "INTEGER NOT NULL DEFAULT 0"
                )
        _ready = True


def ensure_custom_airport(
    iata: str,
    *,
    name: str = "",
    icao: str = "",
) -> dict | None:
    """未知三字码写入自定义机场行（不覆盖官方数据）。"""
    code = (iata or "").strip().upper()
    if len(code) != 3 or not code.isalnum():
        return None
    existing = get_airport(code)
    if existing:
        return existing
    pk = (icao or f"X{code}").strip().upper()[:8]
    init()
    with _lock:
        with _connect() as conn:
            conn.execute(
                """INSERT OR IGNORE INTO geo_airports(
                       icao, iata, ident, name, type, custom
                   ) VALUES(?,?,?,?,?,1)""",
                (pk, code, code, name or code, "custom",),
            )
    return get_airport(code)


def mark_source(source: str, layer: str, rows: int, note: str = "") -> None:
    init()
    with _lock:
        with _connect() as conn:
            conn.execute(
                """INSERT INTO meta_sources(source, layer, rows, imported_at, note)
                   VALUES(?,?,?,?,?)
                   ON CONFLICT(source) DO UPDATE SET
                       layer=excluded.layer,
                       rows=excluded.rows,
                       imported_at=excluded.imported_at,
                       note=excluded.note
                """,
                (source, layer, int(rows), time.time(), note or ""),
            )


def _replace(table: str, columns: str, rows: list[tuple], source: str, layer: str) -> int:
    init()
    placeholders = ",".join("?" * len(columns.split(",")))
    with _lock:
        with _connect() as conn:
            conn.execute(f"DELETE FROM {table}")
            if rows:
                conn.executemany(
                    f"INSERT OR IGNORE INTO {table}({columns}) VALUES({placeholders})",
                    rows,
                )
            n = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
    mark_source(source, layer, n)
    return n


def replace_countries(rows: list[tuple]) -> int:
    return _replace(
        "geo_countries", "code,name,continent,wikipedia", rows,
        "ourairports_countries", "geo",
    )


def replace_regions(rows: list[tuple]) -> int:
    return _replace(
        "geo_regions", "code,name,iso_country,continent,wikipedia", rows,
        "ourairports_regions", "geo",
    )


def replace_airports(rows: list[tuple]) -> int:
    """行字段见 sync_catalog.import_airports。"""
    cols = (
        "icao,iata,ident,name,name_zh,type,lat,lon,elevation_ft,"
        "continent,iso_country,iso_region,municipality,timezone,"
        "scheduled,gps_code,local_code,wikipedia,home_link,keywords"
    )
    return _replace("geo_airports", cols, rows, "ourairports_airports", "geo")


def patch_airport_timezones(pairs: list[tuple[str, str]]) -> int:
    """按 ICAO 补时区：(icao, timezone)。"""
    if not pairs:
        return 0
    init()
    with _lock:
        with _connect() as conn:
            conn.executemany(
                "UPDATE geo_airports SET timezone=? WHERE icao=? AND timezone=''",
                [(tz, icao) for icao, tz in pairs],
            )
            n = conn.execute(
                "SELECT COUNT(*) FROM geo_airports WHERE timezone!=''"
            ).fetchone()[0]
    mark_source("openflights_timezone", "geo", n, note="timezone patch")
    return n


def patch_airport_zh(pairs: list[tuple[str, str]]) -> int:
    """按 IATA 写中文名：每项为 (iata, name_zh)。"""
    if not pairs:
        return 0
    init()
    with _lock:
        with _connect() as conn:
            conn.executemany(
                "UPDATE geo_airports SET name_zh=? WHERE iata=?",
                [(zh, iata) for iata, zh in pairs],
            )
            n = conn.execute(
                "SELECT COUNT(*) FROM geo_airports WHERE name_zh!=''"
            ).fetchone()[0]
    mark_source("name_zh", "geo", n, note="zh display names")
    return n


def replace_runways(rows: list[tuple]) -> int:
    return _replace(
        "geo_runways",
        "airport_icao,le_ident,he_ident,length_ft,width_ft,surface,lighted,closed",
        rows,
        "ourairports_runways",
        "geo",
    )


def replace_frequencies(rows: list[tuple]) -> int:
    return _replace(
        "geo_frequencies",
        "airport_icao,type,description,frequency_mhz",
        rows,
        "ourairports_frequencies",
        "geo",
    )


def replace_navaids(rows: list[tuple]) -> int:
    return _replace(
        "geo_navaids",
        "ident,name,type,frequency_khz,lat,lon,iso_country,associated_airport",
        rows,
        "ourairports_navaids",
        "geo",
    )


def replace_airlines(rows: list[tuple]) -> int:
    return _replace(
        "net_airlines",
        "iata,icao,name,country,callsign,active",
        rows,
        "openflights_airlines",
        "net",
    )


def replace_routes(rows: list[tuple]) -> int:
    return _replace(
        "net_routes",
        "airline,from_ap,to_ap,equipment,equipment_all",
        rows,
        "openflights_routes",
        "net",
    )


def replace_plane_types(rows: list[tuple]) -> int:
    return _replace(
        "net_plane_types", "iata,icao,name", rows,
        "openflights_planes", "net",
    )


def replace_faa(rows: list[tuple]) -> int:
    init()
    now = time.time()
    with _lock:
        with _connect() as conn:
            conn.execute("DELETE FROM reg_faa")
            conn.executemany(
                """INSERT OR REPLACE INTO reg_faa(
                       n_number, hex, mfr_mdl, year_mfr, registrant, city, state,
                       status, type_aircraft, updated_at
                   ) VALUES(?,?,?,?,?,?,?,?,?,?)""",
                [(*r, now) for r in rows],
            )
            n = conn.execute("SELECT COUNT(*) FROM reg_faa").fetchone()[0]
    mark_source("faa_registry", "reg", n)
    return n


def replace_prefixes(rows: list[tuple]) -> int:
    return _replace(
        "reg_prefixes", "prefix,country,note", rows,
        "reg_prefixes", "reg",
    )


def replace_icao_types(rows: list[tuple]) -> int:
    return _replace(
        "reg_icao_types", "designator,name,manufacturer,category", rows,
        "icao_types", "reg",
    )


def replace_metar(rows: list[tuple]) -> int:
    return _replace("lex_metar", "code,meaning", rows, "metar_codes", "lex")


def replace_squawk(rows: list[tuple]) -> int:
    return _replace("lex_squawk", "code,meaning", rows, "squawk_codes", "lex")


def get_airport(code: str) -> dict | None:
    """按 IATA 或 ICAO 取机场主档。"""
    code = (code or "").strip().upper()
    if not code:
        return None
    init()
    with _lock:
        with _connect() as conn:
            if len(code) == 3:
                row = conn.execute(
                    "SELECT * FROM geo_airports WHERE iata=? LIMIT 1", (code,)
                ).fetchone()
            else:
                row = conn.execute(
                    "SELECT * FROM geo_airports WHERE icao=? OR ident=?",
                    (code, code),
                ).fetchone()
    if not row:
        return None
    return _airport_dict(row)


def _airport_dict(row: sqlite3.Row) -> dict:
    return {
        "icao": row["icao"] or "",
        "iata": row["iata"] or "",
        "ident": row["ident"] or "",
        "name": row["name"] or "",
        "name_zh": row["name_zh"] or "",
        "display_name": (row["name_zh"] or row["name"] or row["icao"] or ""),
        "type": row["type"] or "",
        "lat": row["lat"],
        "lon": row["lon"],
        "elevation_ft": row["elevation_ft"],
        "continent": row["continent"] or "",
        "country": row["iso_country"] or "",
        "region": row["iso_region"] or "",
        "city": row["municipality"] or "",
        "timezone": row["timezone"] or "",
        "scheduled": bool(row["scheduled"]),
        "gps_code": row["gps_code"] or "",
        "local_code": row["local_code"] or "",
        "wikipedia": row["wikipedia"] or "",
        "home_link": row["home_link"] or "",
        "keywords": row["keywords"] or "",
        "custom": bool(row["custom"]) if "custom" in row.keys() else False,
    }


def airport_detail(code: str) -> dict | None:
    """机场主档 + 跑道 / 频率 / 导航台 + 国家地区名。"""
    ap = get_airport(code)
    if not ap:
        return None
    icao = ap["icao"]
    init()
    with _lock:
        with _connect() as conn:
            country = conn.execute(
                "SELECT * FROM geo_countries WHERE code=?", (ap["country"],)
            ).fetchone()
            region = conn.execute(
                "SELECT * FROM geo_regions WHERE code=?", (ap["region"],)
            ).fetchone()
            rwys = [
                {
                    "le": r["le_ident"],
                    "he": r["he_ident"],
                    "length_ft": r["length_ft"],
                    "width_ft": r["width_ft"],
                    "surface": r["surface"] or "",
                    "lighted": bool(r["lighted"]),
                    "closed": bool(r["closed"]),
                }
                for r in conn.execute(
                    """SELECT * FROM geo_runways WHERE airport_icao=?
                       ORDER BY length_ft DESC""",
                    (icao,),
                )
            ]
            freqs = [
                {
                    "type": r["type"] or "",
                    "description": r["description"] or "",
                    "mhz": r["frequency_mhz"],
                }
                for r in conn.execute(
                    "SELECT * FROM geo_frequencies WHERE airport_icao=? ORDER BY type",
                    (icao,),
                )
            ]
            navs = [
                {
                    "ident": r["ident"],
                    "name": r["name"] or "",
                    "type": r["type"] or "",
                    "khz": r["frequency_khz"],
                    "lat": r["lat"],
                    "lon": r["lon"],
                }
                for r in conn.execute(
                    """SELECT * FROM geo_navaids
                       WHERE associated_airport=? LIMIT 40""",
                    (icao,),
                )
            ]
    ap["country_name"] = (country["name"] if country else "") or ""
    ap["region_name"] = (region["name"] if region else "") or ""
    return {
        "airport": ap,
        "runways": rwys,
        "frequencies": freqs,
        "navaids": navs,
        "layer": "geo",
    }


def search_airports(q: str, limit: int = 20) -> list[dict]:
    """按 IATA / ICAO / 城市 / 名称模糊搜。"""
    q = (q or "").strip()
    if not q:
        return []
    init()
    like = f"%{q}%"
    qu = q.upper()
    with _lock:
        with _connect() as conn:
            rows = conn.execute(
                """SELECT * FROM geo_airports
                   WHERE iata=? OR icao=? OR iata LIKE ? OR icao LIKE ?
                      OR municipality LIKE ? OR name LIKE ? OR name_zh LIKE ?
                      OR keywords LIKE ?
                   ORDER BY
                     CASE WHEN iata=? THEN 0 WHEN icao=? THEN 1
                          WHEN type='large_airport' THEN 2
                          WHEN type='medium_airport' THEN 3 ELSE 4 END,
                     name
                   LIMIT ?""",
                (qu, qu, f"{qu}%", f"{qu}%", like, like, like, like, qu, qu, limit),
            ).fetchall()
    return [_airport_dict(r) for r in rows]


def network_routes(
    *,
    airports: list[str] | None = None,
    airline: str = "",
    limit: int = 180,
) -> list[dict]:
    """参考航线（供地图叠加）。"""
    init()
    airline = (airline or "").strip().upper()
    codes = {(a or "").strip().upper() for a in (airports or []) if a}
    with _lock:
        with _connect() as conn:
            sql = "SELECT * FROM net_routes WHERE 1=1"
            args: list = []
            if airline:
                sql += " AND airline=?"
                args.append(airline)
            if codes:
                placeholders = ",".join("?" * len(codes))
                sql += f" AND (from_ap IN ({placeholders}) OR to_ap IN ({placeholders}))"
                args.extend(sorted(codes))
                args.extend(sorted(codes))
            sql += " LIMIT ?"
            args.append(int(limit))
            rows = conn.execute(sql, args).fetchall()
            # 坐标
            need = {r["from_ap"] for r in rows} | {r["to_ap"] for r in rows}
            coords: dict[str, tuple[float, float]] = {}
            for code in need:
                ap = conn.execute(
                    "SELECT iata, lat, lon FROM geo_airports WHERE iata=? LIMIT 1",
                    (code,),
                ).fetchone()
                if ap and ap["lat"] is not None and ap["lon"] is not None:
                    coords[code] = (ap["lat"], ap["lon"])
    out = []
    for r in rows:
        a, b = r["from_ap"], r["to_ap"]
        if a not in coords or b not in coords:
            continue
        la1, lo1 = coords[a]
        la2, lo2 = coords[b]
        out.append({
            "airline": r["airline"],
            "from": a,
            "to": b,
            "equipment": r["equipment"] or "",
            "path": [[la1, lo1], [la2, lo2]],
        })
    return out


def airline_name(iata: str) -> str:
    code = (iata or "").strip().upper()[:2]
    if len(code) != 2:
        return ""
    init()
    with _lock:
        with _connect() as conn:
            row = conn.execute(
                "SELECT name FROM net_airlines WHERE iata=?", (code,)
            ).fetchone()
    return (row["name"] if row else "") or ""


def typical_equipment(airline: str, frm: str, to: str) -> str:
    init()
    with _lock:
        with _connect() as conn:
            row = conn.execute(
                """SELECT equipment FROM net_routes
                   WHERE airline=? AND from_ap=? AND to_ap=?""",
                (
                    (airline or "").strip().upper()[:2],
                    (frm or "").strip().upper(),
                    (to or "").strip().upper(),
                ),
            ).fetchone()
    return (row["equipment"] if row else "") or ""


def lookup_faa_hex(hex_code: str) -> dict | None:
    hx = "".join(c for c in (hex_code or "").upper() if c in "0123456789ABCDEF")
    if len(hx) < 6:
        return None
    hx = hx[-6:]
    init()
    with _lock:
        with _connect() as conn:
            row = conn.execute(
                "SELECT * FROM reg_faa WHERE hex=?", (hx,)
            ).fetchone()
    if not row:
        return None
    return {
        "hex": row["hex"] or hx,
        "registration": row["n_number"] or "",
        "aircraft_name": row["mfr_mdl"] or "",
        "operator": row["registrant"] or "",
        "country": "US",
        "source": "catalog:faa",
    }


def stats() -> dict:
    """按层汇总行数 + 来源列表。"""
    init()
    tables = {
        "geo": [
            "geo_countries", "geo_regions", "geo_airports",
            "geo_runways", "geo_frequencies", "geo_navaids",
        ],
        "net": ["net_airlines", "net_routes", "net_plane_types"],
        "reg": ["reg_faa", "reg_prefixes", "reg_icao_types"],
        "lex": ["lex_metar", "lex_squawk"],
    }
    with _lock:
        with _connect() as conn:
            layers = {}
            for layer, names in tables.items():
                layers[layer] = {
                    name: conn.execute(f"SELECT COUNT(*) FROM {name}").fetchone()[0]
                    for name in names
                }
            sources = [
                {
                    "source": r["source"],
                    "layer": r["layer"],
                    "rows": r["rows"],
                    "imported_at": r["imported_at"],
                    "note": r["note"] or "",
                }
                for r in conn.execute(
                    "SELECT * FROM meta_sources ORDER BY layer, source"
                )
            ]
    return {
        "db": CATALOG_DB,
        "layers": LAYERS,
        "counts": layers,
        "sources": sources,
    }
