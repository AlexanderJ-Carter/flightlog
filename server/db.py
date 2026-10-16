"""SQLite 访问层：表结构 + CRUD + 统计/地图数据。

只依赖标准库 sqlite3 / math / threading。
数据库文件默认在 server/data/flightlog.db（docker-compose 挂载 ./data 持久化），
可用环境变量 FLIGHTLOG_DB / FLIGHTLOG_DATA_DIR 覆盖。
"""
import math
import os
import sqlite3
import threading
from collections import Counter
from datetime import datetime, timezone

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.environ.get("FLIGHTLOG_DATA_DIR", os.path.join(BASE_DIR, "data"))
DB_PATH = os.environ.get("FLIGHTLOG_DB", os.path.join(DATA_DIR, "flightlog.db"))

_lock = threading.Lock()

# ------------------------------------------------------------------
# 内置机场字典：三字码 -> (中文名, 纬度, 经度)
# ------------------------------------------------------------------
AIRPORTS = {
    "PEK": ("北京首都", 40.080, 116.580),
    "SHA": ("上海虹桥", 31.197, 121.336),
    "PVG": ("上海浦东", 31.144, 121.808),
    "CAN": ("广州白云", 23.392, 113.299),
    "SZX": ("深圳宝安", 22.639, 113.811),
    "CTU": ("成都双流", 30.578, 103.947),
    "TFU": ("成都天府", 30.312, 104.441),
    "CKG": ("重庆江北", 29.719, 106.642),
    "HGH": ("杭州萧山", 30.229, 120.434),
    "NKG": ("南京禄口", 31.742, 118.862),
    "WUH": ("武汉天河", 30.784, 114.208),
    "XIY": ("西安咸阳", 34.447, 108.752),
    "KMG": ("昆明长水", 25.101, 102.929),
    "CSX": ("长沙黄花", 28.189, 113.220),
    "XMN": ("厦门高崎", 24.544, 118.128),
    "TAO": ("青岛胶东", 36.361, 120.088),
    "DLC": ("大连周水子", 38.966, 121.539),
    "URC": ("乌鲁木齐地窝堡", 43.907, 87.474),
    "HAK": ("海口美兰", 19.935, 110.459),
    "SYX": ("三亚凤凰", 18.303, 109.412),
    "LJG": ("丽江三义", 26.680, 100.320),
    "HKG": ("香港国际", 22.308, 113.918),
    "MFM": ("澳门国际", 22.150, 113.590),
    "TPE": ("台北桃园", 25.078, 121.233),
    "ICN": ("首尔仁川", 37.469, 126.451),
    "NRT": ("东京成田", 35.772, 140.393),
    "HND": ("东京羽田", 35.549, 139.780),
    "KIX": ("大阪关西", 34.427, 135.244),
    "SIN": ("新加坡樟宜", 1.364, 103.991),
    "BKK": ("曼谷素万那普", 13.690, 100.750),
    "KUL": ("吉隆坡", 2.746, 101.710),
    "DXB": ("迪拜", 25.253, 55.365),
    "LHR": ("伦敦希思罗", 51.470, -0.454),
    "CDG": ("巴黎戴高乐", 49.010, 2.548),
    "FRA": ("法兰克福", 50.033, 8.571),
    "AMS": ("阿姆斯特丹", 52.310, 4.768),
    "SFO": ("圣弗朗西斯科", 37.621, -122.379),
    "LAX": ("洛杉矶", 33.942, -118.408),
    "JFK": ("纽约肯尼迪", 40.641, -73.778),
    "SYD": ("悉尼", -33.947, 151.177),
    "MEL": ("墨尔本", -37.673, 144.843),
}

# 城市/机场名 -> 三字码（extract.py 也用；同名多机场取最常用）
CITY_TO_AP = {
    "北京": "PEK", "首都": "PEK",
    "上海虹桥": "SHA", "虹桥": "SHA", "上海浦东": "PVG", "浦东": "PVG", "上海": "SHA",
    "广州": "CAN", "白云": "CAN",
    "深圳": "SZX", "宝安": "SZX",
    "成都双流": "CTU", "成都天府": "TFU", "成都": "CTU",
    "重庆": "CKG", "江北": "CKG",
    "杭州": "HGH", "萧山": "HGH",
    "南京": "NKG", "禄口": "NKG",
    "武汉": "WUH", "天河": "WUH",
    "西安": "XIY", "咸阳": "XIY",
    "昆明": "KMG", "长水": "KMG",
    "长沙": "CSX", "黄花": "CSX",
    "厦门": "XMN", "高崎": "XMN",
    "青岛": "TAO", "胶东": "TAO",
    "大连": "DLC", "周水子": "DLC",
    "乌鲁木齐": "URC", "地窝堡": "URC",
    "海口": "HAK", "美兰": "HAK",
    "三亚": "SYX", "凤凰": "SYX",
    "丽江": "LJG", "三义": "LJG",
    "香港": "HKG", "澳门": "MFM", "台北": "TPE", "桃园": "TPE",
    "首尔": "ICN", "仁川": "ICN",
    "东京成田": "NRT", "成田": "NRT", "东京羽田": "HND", "羽田": "HND", "东京": "HND",
    "大阪": "KIX", "关西": "KIX",
    "新加坡": "SIN", "樟宜": "SIN",
    "曼谷": "BKK", "素万那普": "BKK",
    "吉隆坡": "KUL", "迪拜": "DXB",
    "伦敦": "LHR", "希思罗": "LHR",
    "巴黎": "CDG", "戴高乐": "CDG",
    "法兰克福": "FRA", "阿姆斯特丹": "AMS",
    "旧金山": "SFO", "洛杉矶": "LAX", "纽约": "JFK", "肯尼迪": "JFK",
    "悉尼": "SYD", "墨尔本": "MEL",
}


def _connect():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    """建库建表（幂等），FastAPI 启动时调用。"""
    with _lock:
        os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
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
            # 旧库迁移：无 aircraft 列则补上
            cols = [r[1] for r in conn.execute("PRAGMA table_info(flights)")]
            if "aircraft" not in cols:
                conn.execute("ALTER TABLE flights ADD COLUMN aircraft TEXT DEFAULT ''")


# ------------------------------------------------------------------
# CRUD
# ------------------------------------------------------------------
def add_flight(date, flight, from_ap, to_ap, seat="", note="", aircraft=""):
    """插入一条飞行记录，返回新 id。"""
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    with _lock:
        with _connect() as conn:
            cur = conn.execute(
                "INSERT INTO flights(date, flight, from_ap, to_ap, seat, note, aircraft, created_at) "
                "VALUES(?,?,?,?,?,?,?,?)",
                (date, flight, from_ap, to_ap, seat, note, aircraft, now),
            )
            return cur.lastrowid


def delete_flight(fid):
    """按 id 删除（幂等：删不存在的 id 也算成功）。"""
    with _lock:
        with _connect() as conn:
            conn.execute("DELETE FROM flights WHERE id=?", (fid,))


def list_flights():
    """全部记录，新→旧（date DESC, id DESC），键名与前端契约一致。"""
    with _connect() as conn:
        rows = conn.execute(
            "SELECT id, date, flight, from_ap, to_ap, seat, note, aircraft "
            "FROM flights ORDER BY date DESC, id DESC"
        ).fetchall()
    return [
        {
            "id": r["id"], "date": r["date"], "flight": r["flight"],
            "from": r["from_ap"], "to": r["to_ap"],
            "seat": r["seat"], "note": r["note"], "aircraft": r["aircraft"] or "",
        }
        for r in rows
    ]


# ------------------------------------------------------------------
# 地理计算
# ------------------------------------------------------------------
def haversine_km(code_a, code_b):
    """两个机场三字码间的大圆距离（公里）；任一机场不在字典里返回 0。"""
    if code_a not in AIRPORTS or code_b not in AIRPORTS:
        return 0.0
    _, lat1, lon1 = AIRPORTS[code_a]
    _, lat2, lon2 = AIRPORTS[code_b]
    r1, l1, r2, l2 = map(math.radians, (lat1, lon1, lat2, lon2))
    a = (math.sin((r2 - r1) / 2) ** 2
         + math.cos(r1) * math.cos(r2) * math.sin((l2 - l1) / 2) ** 2)
    return 2 * 6371.0 * math.asin(math.sqrt(a))


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
    return [round(math.degrees(pm), 4), round(math.degrees(lm) % 360 - 360
                                              if math.degrees(lm) % 360 > 180
                                              else math.degrees(lm) % 360, 4)]


# ------------------------------------------------------------------
# 统计与地图
# ------------------------------------------------------------------
def aircraft_stats():
    """机型统计（飞友专属）：机型→次数，总机型数。"""
    with _connect() as conn:
        rows = conn.execute(
            "SELECT aircraft, COUNT(*) n FROM flights "
            "WHERE aircraft != '' GROUP BY aircraft ORDER BY n DESC"
        ).fetchall()
    counts = {r["aircraft"]: r["n"] for r in rows}
    return {"aircraft": counts, "aircraft_types": len(counts)}


def stats():
    """GET /api/stats 的数据。"""
    with _connect() as conn:
        rows = conn.execute(
            "SELECT date, flight, from_ap, to_ap FROM flights"
        ).fetchall()

    total = len(rows)
    km = 0.0
    airports = set()
    airlines = Counter()
    years = Counter()
    routes = Counter()
    for r in rows:
        km += haversine_km(r["from_ap"], r["to_ap"])
        airports.update((r["from_ap"], r["to_ap"]))
        code = (r["flight"] or "")[:2]
        if code:
            airlines[code] += 1
        year = (r["date"] or "")[:4]
        if len(year) == 4 and year.isdigit():
            years[year] += 1
        routes[f"{r['from_ap']}-{r['to_ap']}"] += 1

    return {
        "total": total,
        "km": round(km, 1),
        "airports": len(airports),
        "airlines": dict(sorted(airlines.items(), key=lambda x: -x[1])),
        "years": dict(sorted(years.items())),
        "routes": dict(sorted(routes.items(), key=lambda x: -x[1])),
    }


def map_data():
    """GET /api/map 的数据：用到的机场 + 航线弧线（含权重）。

    routes 每项 = [路径, 权重]，路径为 [起点, 大圆中点, 终点] 三个 [lat, lon]，
    正反向航线合并为一条线，权重为次数。
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
            routes.append([path, weight])

    return {"airports": airports, "routes": routes}
