"""航班号查询代理：AviationStack（主）+ 飞常准（预留）。

- key 配置在 server/api_keys.json，格式 {"aviationstack": "<key>", "variflight": "<key>"}
- 无 key 时返回 {"found": false, "reason": "未配置API key"}，绝不抛异常
- 只用标准库 urllib 发 HTTP，不引入额外第三方依赖
"""
import json
import os
import re
import urllib.parse
import urllib.request

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
# key 文件两个位置都找：server/api_keys.json（本地开发）或 data/api_keys.json
# （Docker：data 目录是挂载卷，改 key 不用重新 build 镜像）
KEYS_PATHS = [
    os.path.join(BASE_DIR, "api_keys.json"),
    os.path.join(os.environ.get("FLIGHTLOG_DATA_DIR", os.path.join(BASE_DIR, "data")),
                 "api_keys.json"),
]

TIMEOUT = 8  # 秒

# 航司二字码 -> 名称（取不到 API 航司名时的兜底，extract/展示也复用）
AIRLINE_NAMES = {
    "MU": "中国东方航空", "CA": "中国国际航空", "CZ": "中国南方航空",
    "HU": "海南航空", "HO": "吉祥航空", "GJ": "长龙航空", "KN": "中联航",
    "MF": "厦门航空", "ZH": "深圳航空", "SC": "山东航空", "3U": "四川航空",
    "EU": "成都航空", "9C": "春秋航空", "GS": "天津航空", "TV": "西藏航空",
    "DZ": "东海航空", "PN": "西部航空", "G5": "华夏航空", "JR": "幸福航空",
    "OQ": "重庆航空", "Y8": "圆通货运",
}


def load_keys():
    """读 api_keys.json；不存在/格式错/无 key 都安静地返回 {}。"""
    for path in KEYS_PATHS:
        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict) and data:
                return data
        except (OSError, ValueError):
            continue
    return {}


def _http_json(url):
    """GET 一个 JSON；任何失败返回 None（不向上抛异常）。"""
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "flightlog/1.0"})
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            return json.loads(resp.read().decode("utf-8", "replace"))
    except Exception:
        return None


def airline_name(flight_no):
    """由航班号前缀猜航司名（API 结果缺航司时兜底）。"""
    m = re.match(r"^([0-9A-Z]{2})", flight_no or "")
    return AIRLINE_NAMES.get(m.group(1), "") if m else ""


def _norm_date(date_str):
    """接受 YYYY-MM-DD / YYYYMMDD / YYYY/M/D，统一成 YYYY-MM-DD；无效返回原样。"""
    s = (date_str or "").strip()
    m = re.match(r"^(\d{4})[-/.]?(\d{1,2})[-/.]?(\d{1,2})$", s)
    if m:
        return f"{m.group(1)}-{int(m.group(2)):02d}-{int(m.group(3)):02d}"
    return s


def _aviationstack(key, flight_no, date_str):
    """AviationStack 查询；查到返回契约 dict，查不到返回 None。"""
    params = urllib.parse.urlencode({
        "access_key": key,
        "flight_iata": flight_no,
        "limit": 20,
    })
    data = _http_json(f"http://api.aviationstack.com/v1/flights?{params}")
    if not isinstance(data, dict) or not data.get("data"):
        return None
    items = data["data"]
    # 优先取日期匹配的那条，取不到就用第一条
    hit = next((it for it in items if (it.get("flight_date") or "") == date_str),
               items[0])
    dep, arr = hit.get("departure") or {}, hit.get("arrival") or {}
    if not dep.get("iata") or not arr.get("iata"):
        return None
    return {
        "found": True,
        "date": hit.get("flight_date") or date_str,
        "flight": hit.get("flight_iata") or flight_no,
        "from": dep.get("iata"),
        "to": arr.get("iata"),
        "dep_time": dep.get("scheduled") or dep.get("estimated") or "",
        "arr_time": arr.get("scheduled") or arr.get("estimated") or "",
        "airline": (hit.get("airline") or {}).get("name") or airline_name(flight_no),
    }


def _variflight(key, flight_no, date_str):
    """飞常准开放平台（预留实现，返回 None 表示不可用/未命中）。

    开放平台文档: https://developer.variflight.com ，接口以实际申请的
    product 为准；若字段名有出入，只需调整下面的解析段。
    """
    params = urllib.parse.urlencode({
        "app_id": key.split(":")[0] if ":" in key else "",
        "app_key": key.split(":", 1)[1] if ":" in key else key,
        "fnum": flight_no,
        "date": date_str.replace("-", ""),
    })
    data = _http_json(f"https://open-api.variflight.com/api/flightstatus?{params}")
    if not isinstance(data, dict):
        return None
    # 常见返回结构 {"errcode":0, "data":[{"fNumber":..., "dep":..., "arr":...}]}
    items = data.get("data") or []
    if isinstance(items, dict):
        items = [items]
    if not items:
        return None
    it = items[0]
    if not it.get("dep") or not it.get("arr"):
        return None
    return {
        "found": True,
        "date": date_str,
        "flight": it.get("fNumber") or flight_no,
        "from": str(it.get("dep", "")).upper(),
        "to": str(it.get("arr", "")).upper(),
        "dep_time": it.get("planDepTime") or "",
        "arr_time": it.get("planArrTime") or "",
        "airline": it.get("airlineName") or airline_name(flight_no),
    }


def lookup_flight(flight_no, date_str):
    """POST /api/lookup 的实现。永远返回 dict，绝不抛异常。"""
    flight_no = re.sub(r"\s+", "", (flight_no or "")).upper()
    date_str = _norm_date(date_str)
    if not flight_no or not date_str:
        return {"found": False, "reason": "航班号或日期为空"}

    keys = load_keys()
    if not any(keys.get(k) for k in ("aviationstack", "variflight")):
        return {"found": False, "reason": "未配置API key"}

    # 先试飞常准（国内数据全），失败自动落到 AviationStack
    result = None
    if keys.get("variflight"):
        result = _variflight(keys["variflight"], flight_no, date_str)
    if result is None and keys.get("aviationstack"):
        result = _aviationstack(keys["aviationstack"], flight_no, date_str)

    if result is not None:
        return result
    return {"found": False, "reason": "未查到该航班"}
