"""航班号查询：免费 adsbdb（默认）+ 可选 AviationStack / AI。

优先级：
1. AviationStack / 飞常准（有 key 时：当日时刻 + 机型）
2. adsbdb 公开 API（零配置：典型航线，非当日动态）
3. LLM 消歧（可选，标注 source=ai）

不再使用「常见航司瞎猜」列表；纯数字只返回真实命中。
"""
import json
import re
import urllib.error
import urllib.parse
import urllib.request

import ai_assist
import aircraft_meta
import airports as airports_mod
import config_store
import route_cache

TIMEOUT = 5
route_cache.init()

AIRLINE_NAMES = {
    "MU": "中国东方航空", "CA": "中国国际航空", "CZ": "中国南方航空",
    "HU": "海南航空", "HO": "吉祥航空", "GJ": "长龙航空", "KN": "中联航",
    "MF": "厦门航空", "ZH": "深圳航空", "SC": "山东航空", "3U": "四川航空",
    "EU": "成都航空", "9C": "春秋航空", "GS": "天津航空", "TV": "西藏航空",
    "DZ": "东海航空", "PN": "西部航空", "G5": "华夏航空", "JR": "幸福航空",
    "OQ": "重庆航空", "Y8": "圆通货运",
}

# IATA → ICAO（adsbdb callsign 常用 ICAO）
IATA_TO_ICAO = {
    "CA": "CCA", "MU": "CES", "CZ": "CSN", "HU": "CHH", "HO": "DKH",
    "3U": "CSC", "9C": "CQH", "ZH": "CSZ", "MF": "CXA", "SC": "CDG",
    "GJ": "CDC", "EU": "UEA", "GS": "GCR", "TV": "TBA", "KN": "CUA",
    "PN": "CHB", "G5": "HXA", "JR": "JOY", "OQ": "CQN", "DZ": "EPA",
}

CN_AIRLINE_PRIORITY = [
    "CA", "MU", "CZ", "HU", "HO", "3U", "9C", "ZH", "MF", "SC",
    "GJ", "EU", "GS", "TV", "KN", "PN", "G5",
]


def load_keys():
    return config_store.load_keys()


def _http_json(url, accept_404=False):
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "flightlog/1.0"})
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            return json.loads(resp.read().decode("utf-8", "replace"))
    except urllib.error.HTTPError as e:
        if accept_404 and e.code == 404:
            return None
        return None
    except Exception:
        return None


def _adsb_result(flight, frm, to, airline, date_str, cached=False):
    return {
        "found": True,
        "date": date_str,
        "flight": flight,
        "from": frm,
        "to": to,
        "dep_time": "",
        "arr_time": "",
        "airline": airline,
        "aircraft": "",
        "registration": "",
        "source": "adsbdb",
        "note": "典型航线（非当日动态时刻）"
        + (" · 缓存" if cached else ""),
    }


def _icao_callsign(flight_iata: str) -> str:
    m = re.fullmatch(r"([0-9A-Z]{2})(\d{3,4})", (flight_iata or "").upper())
    if not m:
        return ""
    icao = IATA_TO_ICAO.get(m.group(1))
    return (icao + m.group(2)) if icao else ""


def _attach_airport_labels(result: dict) -> dict:
    """附加机场显示名（OurAirports / 中文覆盖）。"""
    for key, label_key in (("from", "from_name"), ("to", "to_name")):
        code = result.get(key) or ""
        meta = airports_mod.get(code)
        if meta:
            result[label_key] = meta["name"]
    return result


def _attach_enthusiast(result: dict) -> dict:
    """本地观测库 / 实时 ADS-B / adsbdb：补机型、注册号、缩略图。"""
    if not result or not result.get("flight"):
        return result
    # 已有完整机尾（如 AviationStack）→ 沉淀进本地库后返回
    if result.get("aircraft") and result.get("registration"):
        import fleet_db
        fleet_db.remember_sighting(
            result["flight"],
            aircraft=result.get("aircraft") or "",
            registration=result.get("registration") or "",
            source=result.get("source") or "lookup",
        )
        return _attach_airport_labels(result)
    meta = aircraft_meta.enrich_callsign(
        result["flight"], _icao_callsign(result["flight"])
    )
    if meta.get("aircraft") and not result.get("aircraft"):
        result["aircraft"] = meta["aircraft"]
    if meta.get("aircraft_name") and not result.get("aircraft_name"):
        result["aircraft_name"] = meta["aircraft_name"]
    if meta.get("registration") and not result.get("registration"):
        result["registration"] = meta["registration"]
    if meta.get("photo") and not result.get("photo"):
        result["photo"] = meta["photo"]
    if meta.get("hex"):
        result["hex"] = meta["hex"]
    if meta.get("operator"):
        result["operator"] = meta["operator"]
    src = meta.get("source") or ""
    if src.startswith("fleet:") and meta.get("aircraft"):
        note = result.get("note") or ""
        if "本地机尾库" not in note:
            result["note"] = (note + " · 机型来自本地库").strip(" ·")

    # OpenFlights：航线常用机型（仅当仍无机型时作提示）
    if not result.get("aircraft"):
        import fleet_db
        tip = fleet_db.typical_equipment(
            result.get("from") or "",
            result.get("to") or "",
            result.get("flight") or "",
        )
        if tip and tip.get("aircraft"):
            result["aircraft"] = tip["aircraft"]
            result["aircraft_hint"] = True
            note = result.get("note") or ""
            result["note"] = (note + " · 航线常用机型（OpenFlights）").strip(" ·")

    if not result.get("airline"):
        import fleet_db
        name = fleet_db.airline_name((result.get("flight") or "")[:2])
        if name:
            result["airline"] = name

    # 自建 catalog：机型代号 → 可读名称
    code = (result.get("aircraft") or "").strip()
    if code:
        import fleet_db
        label = fleet_db.plane_type_name(code)
        if label:
            result["aircraft_name"] = result.get("aircraft_name") or label
            # 短代号（如 738 / B738）换成全名，便于档案展示
            if len(code) <= 4 and code.replace("-", "").isalnum():
                result["aircraft"] = label

    return _attach_airport_labels(result)


def _adsbdb_callsign(callsign: str, date_str: str) -> dict | None:
    """公开 API：按呼号查典型航线（零 key）。https://api.adsbdb.com"""
    cs = re.sub(r"\s+", "", (callsign or "")).upper()
    if not cs:
        return None
    cache_key = "cs:" + cs
    cached = route_cache.get(cache_key)
    if cached is not None:
        if cached.get("_miss"):
            return None
        return _adsb_result(
            cached["flight"], cached["from"], cached["to"],
            cached.get("airline", ""), date_str, cached=True,
        )

    data = _http_json(
        f"https://api.adsbdb.com/v0/callsign/{urllib.parse.quote(cs)}",
        accept_404=True,
    )
    if not isinstance(data, dict):
        # 网络失败不写负缓存，避免短暂故障被记住
        return None
    route = (data.get("response") or {}).get("flightroute")
    if not isinstance(route, dict):
        route_cache.set_miss(cache_key)
        return None
    origin = route.get("origin") or {}
    dest = route.get("destination") or {}
    frm, to = origin.get("iata_code"), dest.get("iata_code")
    if not frm or not to:
        route_cache.set_miss(cache_key)
        return None
    flight = (route.get("callsign_iata") or cs).upper()
    airline = (route.get("airline") or {}).get("name") or airline_name(flight)
    route_cache.set(cache_key, {
        "flight": flight, "from": frm, "to": to, "airline": airline,
    })
    return _adsb_result(flight, frm, to, airline, date_str)


def _adsbdb_by_iata(flight_iata: str, date_str: str) -> dict | None:
    """先试 IATA，再试 ICAO 呼号。"""
    hit = _adsbdb_callsign(flight_iata, date_str)
    if hit:
        return hit
    m = re.fullmatch(r"([0-9A-Z]{2})(\d{3,4})", flight_iata)
    if not m:
        return None
    icao = IATA_TO_ICAO.get(m.group(1))
    if not icao:
        return None
    return _adsbdb_callsign(icao + m.group(2), date_str)


def _adsbdb_number_candidates(number: str, date_str: str) -> list[dict]:
    """纯数字：缓存整表结果；未缓存则并行探测。"""
    from concurrent.futures import ThreadPoolExecutor, as_completed

    nkey = "num:" + number
    cached = route_cache.get(nkey)
    if cached is not None and not cached.get("_miss"):
        cands = cached.get("candidates") or []
        out = []
        for c in cands:
            out.append({
                **_adsb_result(
                    c["flight"], c["from"], c["to"],
                    c.get("airline", ""), date_str, cached=True,
                ),
                "suggested": False,
                "found": False,
            })
            out[-1].pop("found", None)
        return out

    out = []
    with ThreadPoolExecutor(max_workers=10) as pool:
        futs = [
            pool.submit(_adsbdb_by_iata, f"{iata}{number}", date_str)
            for iata in CN_AIRLINE_PRIORITY
        ]
        for fut in as_completed(futs):
            hit = fut.result()
            if not hit:
                continue
            cand = {**hit, "suggested": False}
            cand.pop("found", None)
            out.append(cand)
    out.sort(key=_rank_key)
    route_cache.set(nkey, {
        "candidates": [
            {
                "flight": c["flight"], "from": c["from"], "to": c["to"],
                "airline": c.get("airline", ""),
            }
            for c in out
        ]
    })
    return out


def airline_name(flight_no):
    m = re.match(r"^([0-9A-Z]{2})", flight_no or "")
    return AIRLINE_NAMES.get(m.group(1), "") if m else ""


def _norm_date(date_str):
    s = (date_str or "").strip()
    m = re.match(r"^(\d{4})[-/.]?(\d{1,2})[-/.]?(\d{1,2})$", s)
    if m:
        return f"{m.group(1)}-{int(m.group(2)):02d}-{int(m.group(3)):02d}"
    return s


def _parse_flight_input(raw):
    s = re.sub(r"\s+", "", (raw or "")).upper()
    if not s:
        return "", ""
    if re.fullmatch(r"\d{3,4}", s):
        return "", s
    m = re.fullmatch(r"([0-9][A-Z]|[A-Z][0-9]|[A-Z]{2})(\d{3,4})", s)
    if m:
        return m.group(1) + m.group(2), ""
    return s, ""


def _aircraft_code(hit):
    ac = hit.get("aircraft")
    if not ac:
        return ""
    if isinstance(ac, str):
        return ac.strip()
    if isinstance(ac, dict):
        return (ac.get("iata") or ac.get("icao") or "").strip()
    return ""


def _hit_to_result(hit, fallback_flight, date_str):
    dep, arr = hit.get("departure") or {}, hit.get("arrival") or {}
    flight_obj = hit.get("flight") or {}
    airline_obj = hit.get("airline") or {}
    flight = (
        hit.get("flight_iata")
        or flight_obj.get("iata")
        or fallback_flight
    )
    if not dep.get("iata") or not arr.get("iata"):
        return None
    return {
        "found": True,
        "date": hit.get("flight_date") or date_str,
        "flight": (flight or fallback_flight or "").upper(),
        "from": dep.get("iata"),
        "to": arr.get("iata"),
        "dep_time": dep.get("scheduled") or dep.get("estimated") or "",
        "arr_time": arr.get("scheduled") or arr.get("estimated") or "",
        "airline": airline_obj.get("name") or airline_name(flight),
        "aircraft": _aircraft_code(hit),
        "source": "aviationstack",
    }


def _rank_key(result):
    code = (result.get("flight") or "")[:2]
    try:
        return CN_AIRLINE_PRIORITY.index(code)
    except ValueError:
        return len(CN_AIRLINE_PRIORITY) + 1


def _aviationstack_iata(key, flight_no, date_str):
    params = urllib.parse.urlencode({
        "access_key": key,
        "flight_iata": flight_no,
        "limit": 20,
    })
    data = _http_json(f"http://api.aviationstack.com/v1/flights?{params}")
    if not isinstance(data, dict):
        return None, "aviationstack 请求失败"
    if data.get("error"):
        msg = data["error"].get("info") or data["error"].get("message") or "API 错误"
        return None, str(msg)
    if not data.get("data"):
        return None, None
    items = data["data"]
    hit = next(
        (it for it in items if (it.get("flight_date") or "") == date_str),
        items[0],
    )
    return _hit_to_result(hit, flight_no, date_str), None


def _aviationstack_number(key, number, date_str):
    params = urllib.parse.urlencode({
        "access_key": key,
        "flight_number": number,
        "limit": 30,
    })
    data = _http_json(f"http://api.aviationstack.com/v1/flights?{params}")
    if not isinstance(data, dict):
        return [], "aviationstack 请求失败"
    if data.get("error"):
        msg = data["error"].get("info") or data["error"].get("message") or "API 错误"
        return [], str(msg)
    if not data.get("data"):
        return [], None
    seen, out = set(), []
    for it in data["data"]:
        if date_str and it.get("flight_date") and it["flight_date"] != date_str:
            continue
        r = _hit_to_result(it, "", date_str)
        if not r:
            continue
        key_id = (r["flight"], r["from"], r["to"], r["date"])
        if key_id in seen:
            continue
        seen.add(key_id)
        cand = {**r, "suggested": False}
        cand.pop("found", None)
        out.append(cand)
    out.sort(key=_rank_key)
    return out, None


def _variflight(key, flight_no, date_str):
    params = urllib.parse.urlencode({
        "app_id": key.split(":")[0] if ":" in key else "",
        "app_key": key.split(":", 1)[1] if ":" in key else key,
        "fnum": flight_no,
        "date": date_str.replace("-", ""),
    })
    data = _http_json(f"https://open-api.variflight.com/api/flightstatus?{params}")
    if not isinstance(data, dict):
        return None
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
        "flight": (it.get("fNumber") or flight_no).upper(),
        "from": str(it.get("dep", "")).upper(),
        "to": str(it.get("arr", "")).upper(),
        "dep_time": it.get("planDepTime") or "",
        "arr_time": it.get("planArrTime") or "",
        "airline": it.get("airlineName") or airline_name(flight_no),
        "aircraft": (it.get("aircraftType") or it.get("aircraft") or "").strip(),
        "source": "variflight",
    }


def _verify_candidates_with_stack(key, candidates, date_str):
    """用完整航班号再查一遍，筛出真实命中。"""
    verified = []
    for c in candidates:
        hit, _err = _aviationstack_iata(key, c["flight"], date_str)
        if hit:
            verified.append({**hit, "found": False, "suggested": False})
            verified[-1].pop("found", None)
    return verified


def _pack_candidates(candidates, reason):
    if not candidates:
        return None
    if len(candidates) == 1:
        only = dict(candidates[0])
        only["found"] = True
        return only
    return {"found": False, "reason": reason, "candidates": candidates}


def lookup_flight(flight_no, date_str):
    """POST /api/lookup。永远返回 dict。"""
    flight_iata, number_only = _parse_flight_input(flight_no)
    date_str = _norm_date(date_str)
    if (not flight_iata and not number_only) or not date_str:
        return {"found": False, "reason": "航班号或日期为空"}

    keys = load_keys()
    stack_key = keys.get("aviationstack") or ""
    vari_key = keys.get("variflight") or ""
    has_llm = ai_assist.available()

    # —— 纯数字 ——
    if number_only:
        if stack_key:
            candidates, api_err = _aviationstack_number(
                stack_key, number_only, date_str)
            packed = _pack_candidates(candidates, "匹配到多个实时航班，请选择")
            if packed:
                return _attach_enthusiast(packed) if packed.get("found") else packed
            if api_err and not candidates:
                pass

        adsb_cands = _adsbdb_number_candidates(number_only, date_str)
        packed = _pack_candidates(
            adsb_cands, "免费航线库匹配到多个航班（典型航线），请选择")
        if packed:
            return _attach_enthusiast(packed) if packed.get("found") else packed

        if has_llm:
            ai_cands = ai_assist.resolve_flight_number(number_only, date_str)
            if ai_cands and stack_key:
                verified = _verify_candidates_with_stack(
                    stack_key, ai_cands, date_str)
                packed = _pack_candidates(
                    verified, "AI 候选已用实时数据核实，请选择")
                if packed:
                    return _attach_enthusiast(packed) if packed.get("found") else packed
            if ai_cands:
                return {
                    "found": False,
                    "reason": "AI 推断候选（请核对后入库）",
                    "candidates": ai_cands,
                    "needs_confirm": True,
                }

        return {"found": False, "reason": "未查到该数字对应的航班"}

    # —— 完整航班号：付费实时 → 免费航线库 → AI ——
    result = None
    err = None
    if vari_key:
        result = _variflight(vari_key, flight_iata, date_str)
    if result is None and stack_key:
        result, err = _aviationstack_iata(stack_key, flight_iata, date_str)
    if result is not None:
        return _attach_enthusiast(result)

    free = _adsbdb_by_iata(flight_iata, date_str)
    if free:
        return _attach_enthusiast(free)

    if has_llm:
        num = re.search(r"(\d{3,4})$", flight_iata)
        if num:
            ai_cands = [
                c for c in ai_assist.resolve_flight_number(num.group(1), date_str)
                if c["flight"] == flight_iata
            ]
            if ai_cands:
                return {
                    "found": False,
                    "reason": "以下为 AI 推断，请核对",
                    "candidates": ai_cands,
                    "needs_confirm": True,
                }

    if err:
        return {"found": False, "reason": err}
    return {
        "found": False,
        "reason": "未查到该航班。免费库无此呼号；配 AviationStack 可查当日时刻与机型",
    }
