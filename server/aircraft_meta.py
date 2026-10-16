"""飞友侧机型/注册号：本地库 → adsb.fi 实时 → adsbdb 机尾（全程零 key）。"""
from __future__ import annotations

import json
import re
import urllib.error
import urllib.parse
import urllib.request

import fleet_db
import route_cache

TIMEOUT = 5
UA = "flightlog/1.0 (personal archive)"


def _http_json(url: str, accept_404: bool = False) -> dict | None:
    try:
        req = urllib.request.Request(url, headers={"User-Agent": UA})
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            return json.loads(resp.read().decode("utf-8", "replace"))
    except urllib.error.HTTPError as e:
        if accept_404 and e.code == 404:
            return None
        return None
    except Exception:
        return None


def lookup_aircraft_hex(hex_code: str) -> dict | None:
    """按 Mode-S hex：本地 fleet → 缓存 → adsbdb。"""
    hx = re.sub(r"[^0-9A-Fa-f]", "", hex_code or "").upper()
    if len(hx) < 6:
        return None

    local = fleet_db.lookup_hex(hx)
    if local and (local.get("aircraft") or local.get("registration")):
        return local

    cache_key = "ac:" + hx
    cached = route_cache.get(cache_key)
    if cached is not None:
        if cached.get("_miss"):
            return None
        return cached

    data = _http_json(
        f"https://api.adsbdb.com/v0/aircraft/{urllib.parse.quote(hx)}",
        accept_404=True,
    )
    ac = (data or {}).get("response", {}).get("aircraft") if data else None
    if not isinstance(ac, dict):
        route_cache.set_miss(cache_key)
        return None
    out = {
        "hex": hx,
        "aircraft": (ac.get("icao_type") or ac.get("type") or "").strip(),
        "aircraft_name": (ac.get("type") or "").strip(),
        "registration": (ac.get("registration") or "").strip().upper(),
        "operator": (ac.get("registered_owner") or "").strip(),
        "photo": (ac.get("url_photo_thumbnail") or ac.get("url_photo") or "").strip(),
        "source": "adsbdb",
    }
    route_cache.set(cache_key, out)
    fleet_db.upsert_aircraft_rows([(
        hx,
        out["registration"],
        out["aircraft"],
        out.get("aircraft_name") or "",
        out["operator"],
        "",
    )])
    return out


def _live_hex_for_callsign(callsign: str) -> str | None:
    """adsb.fi：当前空中该呼号的 Mode-S。"""
    cs = re.sub(r"\s+", "", callsign or "").upper()
    if not cs:
        return None
    data = _http_json(
        f"https://opendata.adsb.fi/api/v2/callsign/{urllib.parse.quote(cs)}",
        accept_404=True,
    )
    if not isinstance(data, dict):
        return None
    acs = data.get("ac") or []
    if not acs:
        return None
    hx = (acs[0].get("hex") or "").strip().upper()
    # 实时包里常自带机型/注册号
    if hx:
        t = (acs[0].get("t") or acs[0].get("type") or "").strip()
        r = (acs[0].get("r") or acs[0].get("reg") or "").strip().upper()
        if t or r:
            fleet_db.upsert_aircraft_rows([(hx, r, t, "", "", "")])
    return hx or None


def enrich_callsign(flight_iata: str, icao_callsign: str = "") -> dict:
    """补充机型/注册号：本地观测 → 实时空中 → adsbdb。"""
    flight = re.sub(r"\s+", "", flight_iata or "").upper()

    # 1) 自己攒的呼号库（哪怕飞机不在空中）
    if flight:
        seen = fleet_db.lookup_flight(flight)
        if seen and (seen.get("aircraft") or seen.get("registration")):
            return seen

    # 2) 实时 ADS-B
    tried = []
    for cs in (flight_iata, icao_callsign):
        cs = re.sub(r"\s+", "", cs or "").upper()
        if not cs or cs in tried:
            continue
        tried.append(cs)
        hx = _live_hex_for_callsign(cs)
        if not hx:
            continue
        meta = lookup_aircraft_hex(hx)
        if meta:
            if flight:
                fleet_db.remember_sighting(
                    flight,
                    aircraft=meta.get("aircraft") or "",
                    registration=meta.get("registration") or "",
                    hex_code=hx,
                    operator=meta.get("operator") or "",
                    photo=meta.get("photo") or "",
                    source="adsb.fi",
                )
            return meta
        bare = {"hex": hx, "source": "adsb.fi"}
        if flight:
            fleet_db.remember_sighting(flight, hex_code=hx, source="adsb.fi")
        return bare

    return {}
