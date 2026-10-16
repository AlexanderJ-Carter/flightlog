"""SQLite 访问层：表结构 + CRUD + 统计/地图数据。

只依赖标准库 sqlite3 / math / threading。
数据库文件默认在 server/data/flightlog.db（docker-compose 挂载 ./data 持久化），
可用环境变量 FLIGHTLOG_DB / FLIGHTLOG_DATA_DIR 覆盖。
"""
import math
import os
import re
import sqlite3
import threading
from collections import Counter
from datetime import datetime, timezone

from airports import AIRPORTS
import fleet_db

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.environ.get("FLIGHTLOG_DATA_DIR", os.path.join(BASE_DIR, "data"))
DB_PATH = os.environ.get("FLIGHTLOG_DB", os.path.join(DATA_DIR, "flightlog.db"))

_lock = threading.Lock()


def _connect():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db():
    """建库建表（幂等），FastAPI 启动时调用。"""
    with _lock:
        os.makedirs(os.path.dirname(DB_PATH) or ".", exist_ok=True)
        with _connect() as conn:
            conn.execute(
                """CREATE TABLE IF NOT EXISTS flights(
                       id INTEGER PRIMARY KEY,
                       date TEXT NOT NULL,
                       flight TEXT NOT NULL,
                       from_ap TEXT NOT NULL,
                       to_ap TEXT NOT NULL,
                       seat TEXT DEFAULT '',
                       note TEXT DEFAULT '',
                       aircraft TEXT DEFAULT '',
                       created_at TEXT NOT NULL
                   )"""
            )
            cols = {r[1] for r in conn.execute("PRAGMA table_info(flights)")}
            for col, ddl in (
                ("aircraft", "TEXT DEFAULT ''"),
                ("registration", "TEXT DEFAULT ''"),
                ("cabin_class", "TEXT DEFAULT ''"),
                ("seat_type", "TEXT DEFAULT ''"),
                ("flight_reason", "TEXT DEFAULT ''"),
                ("duration_min", "INTEGER"),
                ("airline_name", "TEXT DEFAULT ''"),
                ("dep_time", "TEXT DEFAULT ''"),
                ("arr_time", "TEXT DEFAULT ''"),
                ("dep_terminal", "TEXT DEFAULT ''"),
                ("arr_terminal", "TEXT DEFAULT ''"),
                ("dep_gate", "TEXT DEFAULT ''"),
                ("arr_gate", "TEXT DEFAULT ''"),
                ("trip_id", "TEXT DEFAULT ''"),
                ("distance_km", "REAL"),
            ):
                if col not in cols:
                    conn.execute(
                        f"ALTER TABLE flights ADD COLUMN {col} {ddl}"
                    )
            conn.execute(
                """CREATE TABLE IF NOT EXISTS flight_tracks(
                       flight_id INTEGER PRIMARY KEY,
                       track_json TEXT NOT NULL DEFAULT '[]',
                       source_format TEXT NOT NULL DEFAULT '',
                       source_name TEXT NOT NULL DEFAULT '',
                       point_count INTEGER NOT NULL DEFAULT 0,
                       updated_at TEXT NOT NULL,
                       FOREIGN KEY(flight_id) REFERENCES flights(id) ON DELETE CASCADE
                   )"""
            )


def find_duplicate(date, flight, from_ap, to_ap, exclude_id=None):
    """查找同日同航班同航线记录；exclude_id 用于更新时排除自身。"""
    sql = ("SELECT id FROM flights WHERE date=? AND UPPER(flight)=? "
           "AND UPPER(from_ap)=? AND UPPER(to_ap)=?")
    params = [date, flight.upper(), from_ap.upper(), to_ap.upper()]
    if exclude_id is not None:
        sql += " AND id!=?"
        params.append(exclude_id)
    with _connect() as conn:
        row = conn.execute(sql, params).fetchone()
    return row["id"] if row else None


def infer_seat_type(seat: str) -> str:
    """由座位号末字母粗推 window/aisle/middle（可被显式字段覆盖）。"""
    s = (seat or "").strip().upper()
    letter = next((c for c in reversed(s) if c.isalpha()), "")
    if letter in "AFHK":
        return "window"
    if letter in "CDGJ":
        return "aisle"
    if letter in "BE":
        return "middle"
    return ""


def _resolve_airline_name(flight: str, explicit: str = "") -> str:
    name = (explicit or "").strip()
    if name:
        return name
    code = re.sub(r"\s+", "", flight or "").upper()[:2]
    if len(code) != 2:
        return ""
    return fleet_db.airline_name(code)


def _norm_time(raw) -> str:
    """归一化为 HH:MM；空串表示未填。"""
    s = (str(raw) if raw is not None else "").strip()
    if not s:
        return ""
    m = re.search(r"(\d{1,2}):(\d{2})", s)
    if m:
        return f"{int(m.group(1)):02d}:{m.group(2)}"
    m = re.fullmatch(r"(\d{1,2})(\d{2})", s)
    if m:
        return f"{int(m.group(1)):02d}:{m.group(2)}"
    return ""


def add_flight(
    date,
    flight,
    from_ap,
    to_ap,
    seat="",
    note="",
    aircraft="",
    registration="",
    cabin_class="",
    seat_type="",
    flight_reason="",
    duration_min=None,
    airline_name="",
    dep_time="",
    arr_time="",
    dep_terminal="",
    arr_terminal="",
    dep_gate="",
    arr_gate="",
    trip_id="",
    distance_km=None,
):
    """插入一条飞行记录，返回新 id。"""
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    st = (seat_type or "").strip().lower() or infer_seat_type(seat)
    aln = _resolve_airline_name(flight, airline_name)
    dur = int(duration_min) if duration_min not in (None, "") else None
    dist = compute_distance_km(from_ap, to_ap, distance_km)
    with _lock:
        with _connect() as conn:
            cur = conn.execute(
                "INSERT INTO flights(date, flight, from_ap, to_ap, seat, note, "
                "aircraft, registration, cabin_class, seat_type, flight_reason, "
                "duration_min, airline_name, dep_time, arr_time, dep_terminal, "
                "arr_terminal, dep_gate, arr_gate, trip_id, distance_km, "
                "created_at) "
                "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    date, flight, from_ap, to_ap, seat, note, aircraft,
                    registration,
                    (cabin_class or "").strip().lower(),
                    st,
                    (flight_reason or "").strip().lower(),
                    dur,
                    aln,
                    _norm_time(dep_time),
                    _norm_time(arr_time),
                    (dep_terminal or "").strip(),
                    (arr_terminal or "").strip(),
                    (dep_gate or "").strip(),
                    (arr_gate or "").strip(),
                    (trip_id or "").strip(),
                    dist,
                    now,
                ),
            )
            fid = cur.lastrowid
    if aircraft or registration:
        fleet_db.remember_sighting(
            flight,
            aircraft=aircraft or "",
            registration=registration or "",
            source="user",
        )
    return fid


def delete_flight(fid):
    """按 id 删除（幂等：删不存在的 id 也算成功）。"""
    with _lock:
        with _connect() as conn:
            conn.execute("DELETE FROM flights WHERE id=?", (fid,))


UPDATE_FIELDS = {
    "date": "date", "flight": "flight", "from_ap": "from_ap", "to_ap": "to_ap",
    "seat": "seat", "note": "note", "aircraft": "aircraft",
    "registration": "registration",
    "cabin_class": "cabin_class", "seat_type": "seat_type",
    "flight_reason": "flight_reason", "duration_min": "duration_min",
    "airline_name": "airline_name",
    "dep_time": "dep_time", "arr_time": "arr_time",
    "dep_terminal": "dep_terminal", "arr_terminal": "arr_terminal",
    "dep_gate": "dep_gate", "arr_gate": "arr_gate",
    "trip_id": "trip_id", "distance_km": "distance_km",
}


def update_flight(fid, **fields):
    """按 id 部分更新：只改传入且非 None 的字段。

    返回 False 表示该 id 不存在（未做任何修改）。
    """
    if fields.get("seat") is not None and fields.get("seat_type") is None:
        fields["seat_type"] = infer_seat_type(fields["seat"])
    if fields.get("cabin_class") is not None:
        fields["cabin_class"] = (fields["cabin_class"] or "").strip().lower()
    if fields.get("flight_reason") is not None:
        fields["flight_reason"] = (fields["flight_reason"] or "").strip().lower()
    if fields.get("seat_type") is not None:
        fields["seat_type"] = (fields["seat_type"] or "").strip().lower()
    for tk in ("dep_time", "arr_time"):
        if fields.get(tk) is not None:
            fields[tk] = _norm_time(fields[tk])
    if fields.get("from_ap") is not None or fields.get("to_ap") is not None:
        existing = get_flight(fid)
        if existing:
            fa = fields.get("from_ap", existing["from"])
            ta = fields.get("to_ap", existing["to"])
            if fields.get("distance_km") is None:
                fields["distance_km"] = compute_distance_km(fa, ta)
    sets, vals = [], []
    for key, col in UPDATE_FIELDS.items():
        if fields.get(key) is not None:
            sets.append(f"{col}=?")
            vals.append(fields[key])
    if not sets:
        return True
    vals.append(fid)
    with _lock:
        with _connect() as conn:
            cur = conn.execute(
                f"UPDATE flights SET {', '.join(sets)} WHERE id=?", vals)
            return cur.rowcount > 0


def _row_flight(r) -> dict:
    keys = r.keys()
    return {
        "id": r["id"],
        "date": r["date"],
        "flight": r["flight"],
        "from": r["from_ap"],
        "to": r["to_ap"],
        "seat": r["seat"] or "",
        "note": r["note"] or "",
        "aircraft": r["aircraft"] or "",
        "registration": r["registration"] or "",
        "cabin_class": r["cabin_class"] or "",
        "seat_type": r["seat_type"] or "",
        "flight_reason": r["flight_reason"] or "",
        "duration_min": r["duration_min"],
        "airline_name": r["airline_name"] or "",
        "dep_time": r["dep_time"] if "dep_time" in keys else "",
        "arr_time": r["arr_time"] if "arr_time" in keys else "",
        "dep_terminal": r["dep_terminal"] if "dep_terminal" in keys else "",
        "arr_terminal": r["arr_terminal"] if "arr_terminal" in keys else "",
        "dep_gate": r["dep_gate"] if "dep_gate" in keys else "",
        "arr_gate": r["arr_gate"] if "arr_gate" in keys else "",
        "trip_id": r["trip_id"] if "trip_id" in keys else "",
        "distance_km": r["distance_km"] if "distance_km" in keys else None,
    }


_FLIGHT_COLS = (
    "id, date, flight, from_ap, to_ap, seat, note, aircraft, registration, "
    "cabin_class, seat_type, flight_reason, duration_min, airline_name, "
    "dep_time, arr_time, dep_terminal, arr_terminal, dep_gate, arr_gate, "
    "trip_id, distance_km"
)


def get_flight(fid):
    """按 id 取单条，不存在返回 None。"""
    with _connect() as conn:
        r = conn.execute(
            f"SELECT {_FLIGHT_COLS} FROM flights WHERE id=?",
            (fid,),
        ).fetchone()
    return _row_flight(r) if r else None


def list_flights(year=None, airline=None, airport=None, q=None,
                 limit=None, offset=0):
    """航班列表（新→旧），支持可选筛选。"""
    conds, params = [], []
    if year:
        conds.append("date LIKE ?")
        params.append(f"{year}%")
    if airline:
        conds.append("UPPER(flight) LIKE ?")
        params.append(airline.upper() + "%")
    if airport:
        conds.append("(UPPER(from_ap)=? OR UPPER(to_ap)=?)")
        params.extend([airport.upper(), airport.upper()])
    if q:
        like = f"%{q.upper()}%"
        conds.append(
            "(UPPER(flight) LIKE ? OR UPPER(from_ap) LIKE ? "
            "OR UPPER(to_ap) LIKE ? OR UPPER(IFNULL(note,'')) LIKE ? "
            "OR UPPER(IFNULL(aircraft,'')) LIKE ? "
            "OR UPPER(IFNULL(registration,'')) LIKE ?)"
        )
        params.extend([like, like, like, like, like, like])
    where = ("WHERE " + " AND ".join(conds)) if conds else ""
    lim = f" LIMIT {int(limit)} OFFSET {int(offset)}" if limit else ""

    with _connect() as conn:
        rows = conn.execute(
            f"SELECT {_FLIGHT_COLS} FROM flights {where} "
            f"ORDER BY date DESC, id DESC{lim}",
            params,
        ).fetchall()
    return [_row_flight(r) for r in rows]


_MERGE_TEXT = (
    "seat", "note", "aircraft", "registration", "cabin_class", "seat_type",
    "flight_reason", "airline_name", "dep_time", "arr_time",
    "dep_terminal", "arr_terminal", "dep_gate", "arr_gate", "trip_id",
)


def _row_payload(r: dict, flight: str) -> dict:
    seat = str(r.get("seat", "") or "")
    st = (
        str(r.get("seat_type", "") or "").strip().lower()
        or infer_seat_type(seat)
    )
    from_ap = str(r.get("from", "")).upper()
    to_ap = str(r.get("to", "")).upper()
    return {
        "seat": seat,
        "note": str(r.get("note", "") or ""),
        "aircraft": str(r.get("aircraft", "") or ""),
        "registration": str(r.get("registration", "") or "").upper(),
        "cabin_class": str(r.get("cabin_class", "") or "").strip().lower(),
        "seat_type": st,
        "flight_reason": str(r.get("flight_reason", "") or "").strip().lower(),
        "duration_min": (
            int(r["duration_min"])
            if r.get("duration_min") not in (None, "")
            else None
        ),
        "airline_name": _resolve_airline_name(
            flight, str(r.get("airline_name", "") or "")
        ),
        "dep_time": _norm_time(r.get("dep_time", "")),
        "arr_time": _norm_time(r.get("arr_time", "")),
        "dep_terminal": str(r.get("dep_terminal", "") or "").strip(),
        "arr_terminal": str(r.get("arr_terminal", "") or "").strip(),
        "dep_gate": str(r.get("dep_gate", "") or "").strip(),
        "arr_gate": str(r.get("arr_gate", "") or "").strip(),
        "trip_id": str(r.get("trip_id", "") or "").strip(),
        "distance_km": compute_distance_km(
            from_ap, to_ap, r.get("distance_km")
        ),
    }


def import_rows(rows, replace=False):
    """批量导入。重复记录补全空字段；replace=True 时先清空。"""
    added, updated, skipped = 0, 0, []
    with _lock:
        with _connect() as conn:
            if replace:
                conn.execute("DELETE FROM flights")
            now = datetime.now(timezone.utc).isoformat(timespec="seconds")
            for i, r in enumerate(rows):
                try:
                    date, flight = str(r["date"]), str(r["flight"]).upper()
                    from_ap = str(r.get("from", "")).upper()
                    to_ap = str(r.get("to", "")).upper()
                    if not (date and flight and from_ap and to_ap):
                        raise ValueError("缺少必填字段（date/flight/from/to）")
                    if len(from_ap) != 3 or len(to_ap) != 3:
                        raise ValueError("机场码不是三字码")
                    if not re.match(r"^\d{4}-\d{2}-\d{2}$", date):
                        raise ValueError(f"日期格式应为 YYYY-MM-DD：{date!r}")
                    import catalog_db
                    catalog_db.ensure_custom_airport(from_ap)
                    catalog_db.ensure_custom_airport(to_ap)
                    payload = _row_payload(r, flight)
                    dup = conn.execute(
                        f"SELECT {_FLIGHT_COLS} FROM flights WHERE date=? "
                        "AND UPPER(flight)=? AND UPPER(from_ap)=? "
                        "AND UPPER(to_ap)=?",
                        (date, flight, from_ap, to_ap),
                    ).fetchone()
                    if dup:
                        sets, vals = [], []
                        for col in _MERGE_TEXT:
                            new_v = payload.get(col) or ""
                            old_v = dup[col] if col in dup.keys() else ""
                            if new_v and not (old_v or "").strip():
                                sets.append(f"{col}=?")
                                vals.append(new_v)
                        if payload["duration_min"] is not None and dup["duration_min"] is None:
                            sets.append("duration_min=?")
                            vals.append(payload["duration_min"])
                        if (
                            payload["distance_km"] is not None
                            and dup["distance_km"] is None
                        ):
                            sets.append("distance_km=?")
                            vals.append(payload["distance_km"])
                        if sets:
                            vals.append(dup["id"])
                            conn.execute(
                                f"UPDATE flights SET {', '.join(sets)} WHERE id=?",
                                vals,
                            )
                            updated += 1
                        else:
                            skipped.append({
                                "row": i,
                                "reason": f"重复且无新字段 id={dup['id']}",
                            })
                        continue
                    conn.execute(
                        "INSERT INTO flights(date, flight, from_ap, to_ap, seat, "
                        "note, aircraft, registration, cabin_class, seat_type, "
                        "flight_reason, duration_min, airline_name, dep_time, "
                        "arr_time, dep_terminal, arr_terminal, dep_gate, "
                        "arr_gate, trip_id, distance_km, created_at) "
                        "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                        (
                            date, flight, from_ap, to_ap,
                            payload["seat"], payload["note"],
                            payload["aircraft"], payload["registration"],
                            payload["cabin_class"], payload["seat_type"],
                            payload["flight_reason"], payload["duration_min"],
                            payload["airline_name"], payload["dep_time"],
                            payload["arr_time"], payload["dep_terminal"],
                            payload["arr_terminal"], payload["dep_gate"],
                            payload["arr_gate"], payload["trip_id"],
                            payload["distance_km"], now,
                        ),
                    )
                    added += 1
                except (KeyError, ValueError) as e:
                    skipped.append({"row": i, "reason": str(e)})
    return {"added": added, "updated": updated, "skipped": skipped}


def _airport_latlon(code: str) -> tuple[float, float] | None:
    c = (code or "").upper()
    if c in AIRPORTS:
        _, lat, lon = AIRPORTS[c]
        return float(lat), float(lon)
    import catalog_db
    ap = catalog_db.get_airport(c)
    if ap and ap.get("lat") is not None and ap.get("lon") is not None:
        return float(ap["lat"]), float(ap["lon"])
    return None


def haversine_km(code_a, code_b):
    """两个机场三字码间的大圆距离（公里）；缺坐标返回 0。"""
    a = _airport_latlon(code_a)
    b = _airport_latlon(code_b)
    if not a or not b:
        return 0.0
    lat1, lon1 = a
    lat2, lon2 = b
    r1, l1, r2, l2 = map(math.radians, (lat1, lon1, lat2, lon2))
    x = (math.sin((r2 - r1) / 2) ** 2
         + math.cos(r1) * math.cos(r2) * math.sin((l2 - l1) / 2) ** 2)
    return 2 * 6371.0 * math.asin(math.sqrt(x))


def compute_distance_km(from_ap: str, to_ap: str, explicit=None) -> float | None:
    """优先显式值，否则大圆距离。"""
    if explicit not in (None, ""):
        return round(float(explicit), 1)
    km = haversine_km(from_ap, to_ap)
    return round(km, 1) if km else None


def _gc_midpoint(code_a, code_b):
    """大圆中点 (lat, lon)，给地图画弧线用。"""
    _, lat1, lon1 = AIRPORTS[code_a]
    _, lat2, lon2 = AIRPORTS[code_b]
    p1, l1, p2, l2 = map(math.radians, (lat1, lon1, lat2, lon2))
    bx = math.cos(p2) * math.cos(l2 - l1)
    by = math.cos(p2) * math.sin(l2 - l1)
    pm = math.atan2(math.sin(p1) + math.sin(p2),
                    math.sqrt((math.cos(p1) + bx) ** 2 + by ** 2))
    lm = l1 + math.atan2(by, math.cos(p1) + bx)
    deg_lm = math.degrees(lm) % 360
    if deg_lm > 180:
        deg_lm -= 360
    return [round(math.degrees(pm), 4), round(deg_lm, 4)]


def aircraft_stats():
    """机型统计：机型→次数，总机型数。"""
    with _connect() as conn:
        rows = conn.execute(
            "SELECT aircraft, COUNT(*) n FROM flights "
            "WHERE aircraft != '' GROUP BY aircraft ORDER BY n DESC"
        ).fetchall()
    counts = {r["aircraft"]: r["n"] for r in rows}
    return {"aircraft": counts, "aircraft_types": len(counts)}


def stats():
    """GET /api/stats：总量 + AirTrail 风格维度（舱位/座位/事由/大洲/月/周）。"""
    with _connect() as conn:
        rows = conn.execute(
            "SELECT date, flight, from_ap, to_ap, cabin_class, seat_type, "
            "flight_reason, duration_min, seat, distance_km FROM flights"
        ).fetchall()

    total = len(rows)
    km = 0.0
    duration = 0
    airports = set()
    airlines = Counter()
    years = Counter()
    routes = Counter()
    cabin = Counter()
    seat_pos = Counter()
    reasons = Counter()
    months = Counter()
    weekdays = Counter()
    for r in rows:
        if r["distance_km"] is not None:
            km += float(r["distance_km"])
        else:
            km += haversine_km(r["from_ap"], r["to_ap"])
        airports.update((r["from_ap"], r["to_ap"]))
        code = (r["flight"] or "")[:2]
        if code:
            airlines[code] += 1
        year = (r["date"] or "")[:4]
        if len(year) == 4 and year.isdigit():
            years[year] += 1
        routes[f"{r['from_ap']}-{r['to_ap']}"] += 1
        cc = (r["cabin_class"] or "").strip().lower()
        if cc:
            cabin[cc] += 1
        st = (r["seat_type"] or "").strip().lower() or infer_seat_type(r["seat"] or "")
        if st:
            seat_pos[st] += 1
        fr = (r["flight_reason"] or "").strip().lower()
        if fr:
            reasons[fr] += 1
        if r["duration_min"]:
            duration += int(r["duration_min"])
        d = r["date"] or ""
        if len(d) >= 7:
            months[d[:7]] += 1
        if len(d) >= 10:
            try:
                weekdays[datetime.strptime(d[:10], "%Y-%m-%d").strftime("%a")] += 1
            except ValueError:
                pass

    continents = Counter()
    import catalog_db
    catalog_db.init()
    for code in airports:
        ap = catalog_db.get_airport(code)
        cont = (ap or {}).get("continent") or ""
        if cont:
            continents[cont] += 1

    return {
        "total": total,
        "km": round(km, 1),
        "duration_min": duration,
        "airports": len(airports),
        "airlines": dict(sorted(airlines.items(), key=lambda x: -x[1])),
        "years": dict(sorted(years.items())),
        "routes": dict(sorted(routes.items(), key=lambda x: -x[1])),
        "cabin_class": dict(sorted(cabin.items(), key=lambda x: -x[1])),
        "seat_type": dict(sorted(seat_pos.items(), key=lambda x: -x[1])),
        "flight_reason": dict(sorted(reasons.items(), key=lambda x: -x[1])),
        "continents": dict(sorted(continents.items(), key=lambda x: -x[1])),
        "countries": visited_countries(),
        "months": dict(sorted(months.items())),
        "weekdays": dict(weekdays),
    }


def visited_countries() -> dict[str, dict]:
    """按起降机场国家统计（catalog.geo）。"""
    with _connect() as conn:
        rows = conn.execute("SELECT from_ap, to_ap FROM flights").fetchall()
    codes = set()
    for r in rows:
        codes.update((r["from_ap"], r["to_ap"]))
    import catalog_db
    catalog_db.init()
    counts: Counter = Counter()
    names: dict[str, str] = {}
    for code in codes:
        ap = catalog_db.get_airport(code)
        if not ap:
            continue
        cc = (ap.get("country") or "").upper()
        if not cc:
            continue
        counts[cc] += 1
        if cc not in names:
            names[cc] = ap.get("country_name") or cc
    # 补全国家正式名
    with catalog_db._lock:
        with catalog_db._connect() as conn:
            for cc in list(counts):
                row = conn.execute(
                    "SELECT name FROM geo_countries WHERE code=?", (cc,)
                ).fetchone()
                if row and row["name"]:
                    names[cc] = row["name"]
    return {
        cc: {"count": n, "name": names.get(cc, cc)}
        for cc, n in sorted(counts.items(), key=lambda x: -x[1])
    }


def set_flight_track(
    flight_id: int,
    points: list,
    *,
    source_format: str = "json",
    source_name: str = "",
) -> dict:
    """写入航迹：points 为 [[lat,lon], ...] 或 [{lat,lon}, ...]。"""
    import json as _json

    if get_flight(flight_id) is None:
        raise ValueError("航班不存在")
    norm: list[list[float]] = []
    for p in points or []:
        if isinstance(p, (list, tuple)) and len(p) >= 2:
            norm.append([float(p[0]), float(p[1])])
        elif isinstance(p, dict) and "lat" in p and "lon" in p:
            norm.append([float(p["lat"]), float(p["lon"])])
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    with _lock:
        with _connect() as conn:
            conn.execute(
                """INSERT INTO flight_tracks(
                       flight_id, track_json, source_format, source_name,
                       point_count, updated_at
                   ) VALUES(?,?,?,?,?,?)
                   ON CONFLICT(flight_id) DO UPDATE SET
                       track_json=excluded.track_json,
                       source_format=excluded.source_format,
                       source_name=excluded.source_name,
                       point_count=excluded.point_count,
                       updated_at=excluded.updated_at
                """,
                (
                    flight_id,
                    _json.dumps(norm, separators=(",", ":")),
                    (source_format or "json")[:32],
                    (source_name or "")[:120],
                    len(norm),
                    now,
                ),
            )
    return {"flight_id": flight_id, "point_count": len(norm)}


def get_flight_track(flight_id: int) -> dict | None:
    import json as _json

    with _connect() as conn:
        r = conn.execute(
            "SELECT * FROM flight_tracks WHERE flight_id=?", (flight_id,)
        ).fetchone()
    if not r:
        return None
    return {
        "flight_id": r["flight_id"],
        "path": _json.loads(r["track_json"] or "[]"),
        "source_format": r["source_format"] or "",
        "source_name": r["source_name"] or "",
        "point_count": r["point_count"],
        "updated_at": r["updated_at"],
    }


def delete_flight_track(flight_id: int) -> None:
    with _lock:
        with _connect() as conn:
            conn.execute("DELETE FROM flight_tracks WHERE flight_id=?", (flight_id,))


def map_data():
    """GET /api/map：机场点 + 航线弧线。

    routes 每项 = {"path": [[lat,lon],...], "weight": n}，正反向合并。
    """
    with _connect() as conn:
        rows = conn.execute(
            "SELECT from_ap, to_ap FROM flights"
        ).fetchall()

    used = set()
    pair = Counter()
    for r in rows:
        used.update((r["from_ap"], r["to_ap"]))
        key = "-".join(sorted((r["from_ap"], r["to_ap"])))
        pair[key] += 1

    airports = []
    for code in sorted(used):
        if code in AIRPORTS:
            name, lat, lon = AIRPORTS[code]
            airports.append([code, name, lat, lon])

    routes = []
    for key, weight in pair.items():
        a, b = key.split("-")
        if a in AIRPORTS and b in AIRPORTS:
            _, la1, lo1 = AIRPORTS[a]
            _, la2, lo2 = AIRPORTS[b]
            path = [[la1, lo1], _gc_midpoint(a, b), [la2, lo2]]
            routes.append({"path": path, "weight": weight})

    return {"airports": airports, "routes": routes}
