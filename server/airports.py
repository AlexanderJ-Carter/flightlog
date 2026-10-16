"""机场字典：OurAirports（IATA）+ 中文名覆盖 + 城市→机场（短信解析）。"""
from __future__ import annotations

import json
import os

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
_BUNDLE = os.path.join(BASE_DIR, "airports_iata.json")

# 枢纽中文名（覆盖 OurAirports 英文名，供界面与短信）
NAME_ZH = {
    "PEK": "北京首都", "PKX": "北京大兴", "SHA": "上海虹桥", "PVG": "上海浦东",
    "CAN": "广州白云", "SZX": "深圳宝安", "CTU": "成都双流", "TFU": "成都天府",
    "CKG": "重庆江北", "HGH": "杭州萧山", "NKG": "南京禄口", "WUH": "武汉天河",
    "XIY": "西安咸阳", "KMG": "昆明长水", "CSX": "长沙黄花", "XMN": "厦门高崎",
    "TAO": "青岛胶东", "DLC": "大连周水子", "URC": "乌鲁木齐地窝堡",
    "HAK": "海口美兰", "SYX": "三亚凤凰", "LJG": "丽江三义",
    "HKG": "香港国际", "MFM": "澳门国际", "TPE": "台北桃园",
    "ICN": "首尔仁川", "NRT": "东京成田", "HND": "东京羽田", "KIX": "大阪关西",
    "SIN": "新加坡樟宜", "BKK": "曼谷素万那普", "KUL": "吉隆坡", "DXB": "迪拜",
    "LHR": "伦敦希思罗", "CDG": "巴黎戴高乐", "FRA": "法兰克福", "AMS": "阿姆斯特丹",
    "SFO": "圣弗朗西斯科", "LAX": "洛杉矶", "JFK": "纽约肯尼迪",
    "SYD": "悉尼", "MEL": "墨尔本",
}

CITY_TO_AP = {
    "北京": "PEK", "首都": "PEK", "大兴": "PKX",
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

# code -> (display_name, lat, lon) —— 与旧接口兼容（db / 地图）
AIRPORTS: dict[str, tuple[str, float, float]] = {}
# code -> 完整元数据
_META: dict[str, dict] = {}


def _display_name(code: str, rec: dict) -> str:
    if code in NAME_ZH:
        return NAME_ZH[code]
    city = (rec.get("city") or "").strip()
    name = (rec.get("name") or "").strip()
    if city and city.lower() not in name.lower():
        return f"{city} · {name}"
    return name or code


def _load() -> None:
    global AIRPORTS, _META
    if AIRPORTS:
        return
    path = _BUNDLE
    if not os.path.isfile(path):
        raise FileNotFoundError(f"缺少机场库文件：{path}")
    with open(path, encoding="utf-8") as f:
        raw = json.load(f)
    meta: dict[str, dict] = {}
    ap: dict[str, tuple[str, float, float]] = {}
    for code, rec in raw.items():
        code = code.upper()
        lat = float(rec["lat"])
        lon = float(rec["lon"])
        name = _display_name(code, rec)
        ap[code] = (name, lat, lon)
        meta[code] = {
            "code": code,
            "icao": rec.get("icao") or "",
            "name": name,
            "name_en": rec.get("name") or "",
            "city": rec.get("city") or "",
            "country": rec.get("country") or "",
            "lat": lat,
            "lon": lon,
            "type": rec.get("type") or "",
        }
    # 保证中文覆盖坐标仍来自 OA；无 OA 条目时不造假坐标
    AIRPORTS = ap
    _META = meta


_load()


def known(code: str) -> bool:
    """三字码是否在机场库中。"""
    return (code or "").upper() in AIRPORTS


def get(code: str) -> dict | None:
    """单机场元数据。"""
    return _META.get((code or "").upper())


def search(q: str = "", limit: int = 20) -> list[dict]:
    """按三字码 / ICAO / 名称 / 城市模糊搜索。"""
    q_raw = (q or "").strip()
    q = q_raw.upper()
    q_lower = q_raw.lower()
    items = []
    for code, m in _META.items():
        if not q:
            hit = True
        else:
            hit = (
                q in code
                or q in (m.get("icao") or "")
                or q_lower in (m.get("name") or "").lower()
                or q_lower in (m.get("name_en") or "").lower()
                or q_lower in (m.get("city") or "").lower()
            )
        if not hit:
            continue
        items.append({
            "code": code,
            "name": m["name"],
            "lat": m["lat"],
            "lon": m["lon"],
            "icao": m.get("icao") or "",
            "city": m.get("city") or "",
            "country": m.get("country") or "",
            "known": True,
        })
    # 前缀/精确优先
    def rank(it: dict) -> tuple:
        c = it["code"]
        if c == q:
            return (0, c)
        if c.startswith(q):
            return (1, c)
        if (it.get("icao") or "") == q:
            return (2, c)
        return (3, c)

    items.sort(key=rank)
    return items[: max(1, min(limit, 500))]


def count() -> int:
    return len(AIRPORTS)
