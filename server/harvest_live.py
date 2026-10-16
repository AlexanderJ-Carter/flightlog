#!/usr/bin/env python3
"""合法采集：公开 ADS-B API → 写入本地 fleet.db（不爬商业站）。

来源：
  - adsb.fi opendata（枢纽周边，≤1 req/s）
  - OpenSky Network states（研究/非商用匿名接口）

用法：
    FLIGHTLOG_DATA_DIR=../data ../.venv/bin/python harvest_live.py
"""
from __future__ import annotations

import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

import fleet_db

UA = "flightlog-harvest/1.0 (personal open-data; respectful rate limit)"
TIMEOUT = 12

# 枢纽：名称, lat, lon, 半径海里
HUBS_FULL = [
    ("PEK", 40.08, 116.58, 80),
    ("PKX", 39.51, 116.41, 60),
    ("PVG", 31.14, 121.81, 80),
    ("SHA", 31.20, 121.34, 50),
    ("CAN", 23.39, 113.30, 70),
    ("SZX", 22.64, 113.81, 60),
    ("CTU", 30.58, 103.95, 60),
    ("TFU", 30.31, 104.44, 60),
    ("HKG", 22.31, 113.92, 60),
    ("ICN", 37.46, 126.44, 60),
    ("NRT", 35.77, 140.39, 70),
    ("HND", 35.55, 139.78, 50),
    ("SIN", 1.36, 103.99, 50),
    ("BKK", 13.69, 100.75, 60),
    ("LHR", 51.47, -0.46, 60),
    ("FRA", 50.03, 8.57, 60),
    ("LAX", 33.94, -118.41, 70),
    ("SFO", 37.62, -122.38, 60),
]

# 轻量：少量枢纽，降低请求与 CPU（容器默认）
HUBS_LIGHT = [
    ("PEK", 40.08, 116.58, 70),
    ("PVG", 31.14, 121.81, 70),
    ("CAN", 23.39, 113.30, 60),
    ("HKG", 22.31, 113.92, 50),
    ("ICN", 37.46, 126.44, 50),
]


def _light_mode() -> bool:
    return os.environ.get("FLIGHTLOG_HARVEST_LIGHT", "1").lower() not in (
        "0", "false", "no",
    )


def _hubs() -> list[tuple]:
    return HUBS_LIGHT if _light_mode() else HUBS_FULL


def _http_json(url: str) -> dict | None:
    try:
        req = urllib.request.Request(url, headers={"User-Agent": UA})
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            return json.loads(resp.read().decode("utf-8", "replace"))
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, ValueError):
        return None


def _norm_flight(raw: str) -> str:
    return re.sub(r"\s+", "", raw or "").upper()


def ingest_adsb_fi_ac(ac: dict) -> bool:
    """写入一条 adsb.fi 飞机。"""
    hx = (ac.get("hex") or "").strip().upper()
    fl = _norm_flight(ac.get("flight") or "")
    reg = (ac.get("r") or "").strip().upper()
    tc = (ac.get("t") or "").strip().upper()
    model = (ac.get("desc") or "").strip()
    if len(hx) < 6 and not fl:
        return False
    if hx and (reg or tc):
        fleet_db.upsert_aircraft_rows([(hx, reg, tc, model, "", "")])
    if fl and (reg or tc or hx):
        fleet_db.remember_sighting(
            fl,
            aircraft=tc,
            registration=reg,
            hex_code=hx,
            source="harvest:adsb.fi",
        )
        return True
    return bool(hx and (reg or tc))


def harvest_adsb_fi() -> tuple[int, int]:
    """按枢纽扫描；遵守约 1 req/s。"""
    seen_hex: set[str] = set()
    flights = 0
    for name, lat, lon, dist in _hubs():
        url = (
            f"https://opendata.adsb.fi/api/v3/lat/{lat}/lon/{lon}/dist/{dist}"
        )
        print(f"  adsb.fi {name} …", end=" ", flush=True)
        data = _http_json(url)
        time.sleep(1.05)
        if not data:
            print("失败")
            continue
        acs = data.get("ac") or []
        n = 0
        for ac in acs:
            hx = (ac.get("hex") or "").strip().upper()
            if hx and hx in seen_hex:
                continue
            if hx:
                seen_hex.add(hx)
            if ingest_adsb_fi_ac(ac):
                n += 1
                if _norm_flight(ac.get("flight") or ""):
                    flights += 1
        print(f"{len(acs)} 架 / 新记 {n}")
    return len(seen_hex), flights


def harvest_opensky() -> tuple[int, int]:
    """OpenSky 区域状态（匿名、低频率）。轻量模式仅中国框。"""
    if _light_mode():
        boxes = [("CN", 18, 73, 54, 135)]
    else:
        boxes = [
            ("CN", 18, 73, 54, 135),
            ("JP-KR", 30, 120, 46, 146),
            ("SEA", -10, 95, 20, 120),
            ("EU-W", 40, -10, 60, 15),
            ("US-W", 30, -125, 50, -110),
        ]
    seen_hex: set[str] = set()
    flights = 0
    for name, lamin, lomin, lamax, lomax in boxes:
        q = urllib.parse.urlencode({
            "lamin": lamin, "lomin": lomin, "lamax": lamax, "lomax": lomax,
        })
        url = f"https://opensky-network.org/api/states/all?{q}"
        print(f"  OpenSky {name} …", end=" ", flush=True)
        data = _http_json(url)
        time.sleep(1.2)
        if not data:
            print("失败/限流")
            continue
        states = data.get("states") or []
        n = 0
        rows = []
        for st in states:
            # icao24, callsign, origin_country, …, 注册号不在状态向量里
            if not st or len(st) < 2:
                continue
            hx = (st[0] or "").strip().upper()
            fl = _norm_flight(st[1] or "")
            if not hx or hx in seen_hex:
                continue
            seen_hex.add(hx)
            # 用已有机尾库补全
            meta = fleet_db.lookup_hex(hx)
            reg = (meta or {}).get("registration") or ""
            tc = (meta or {}).get("aircraft") or ""
            if meta:
                rows.append((
                    hx, reg, tc,
                    (meta.get("aircraft_name") or ""),
                    (meta.get("operator") or ""),
                    (meta.get("country") or ""),
                ))
            if fl:
                fleet_db.remember_sighting(
                    fl,
                    aircraft=tc,
                    registration=reg,
                    hex_code=hx,
                    source="harvest:opensky",
                )
                flights += 1
                n += 1
            elif hx:
                n += 1
        if rows:
            fleet_db.upsert_aircraft_rows(rows)
        print(f"{len(states)} 状态 / 呼号入库 {n}")
    return len(seen_hex), flights


def import_planes_dat() -> int:
    import csv

    url = (
        "https://raw.githubusercontent.com/jpatokal/openflights/"
        "master/data/planes.dat"
    )
    print("[OpenFlights] planes.dat …")
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=60) as resp:
        text = resp.read().decode("utf-8", "replace")
    rows = []
    for line in text.splitlines():
        parts = next(csv.reader([line]))
        if len(parts) < 3:
            continue
        name = parts[0].strip()
        iata = parts[1].strip().upper()
        icao = parts[2].strip().upper()
        if iata in ("", "\\N") and icao in ("", "\\N"):
            continue
        key = iata if iata not in ("", "\\N") else icao
        rows.append((key, "" if icao in ("", "\\N") else icao, name))
    n = fleet_db.replace_plane_types(rows)
    print(f"  plane_types: {n}")
    return n


def run_once(*, planes: bool | None = None, quiet: bool = False) -> dict:
    """执行一轮合法采集，返回统计字典。

    轻量模式（默认）：少枢纽、单 OpenSky 框、不每次拉 planes.dat。
    """
    def log(*args):
        if not quiet:
            print(*args)

    if planes is None:
        # 轻量默认不拉 planes；完整模式才拉
        planes = not _light_mode()
        env_p = os.environ.get("FLIGHTLOG_HARVEST_PLANES")
        if env_p is not None:
            planes = env_p.lower() not in ("0", "false", "no")

    log(f"数据目录：{fleet_db.DATA_DIR}")
    log(f"模式：{'light' if _light_mode() else 'full'}")
    fleet_db.init()
    before = fleet_db.stats()
    log("采集前：", before)

    plane_n = import_planes_dat() if planes else 0
    log("[adsb.fi] 枢纽空域扫描")
    h1, f1 = harvest_adsb_fi()
    log("[OpenSky] 区域状态扫描")
    h2, f2 = harvest_opensky()

    after = fleet_db.stats()
    delta_s = after["sightings"] - before["sightings"]
    delta_a = after["aircraft"] - before["aircraft"]
    log("—— 本轮 ——")
    log(f"  adsb.fi 唯一 hex≈{h1}，呼号写入相关 {f1}")
    log(f"  OpenSky 唯一 hex≈{h2}，呼号写入相关 {f2}")
    log("采集后：", after)
    log("增量 sightings：", delta_s, " aircraft：", delta_a)
    return {
        "before": before,
        "after": after,
        "delta_sightings": delta_s,
        "delta_aircraft": delta_a,
        "adsb_fi_hex": h1,
        "adsb_fi_flights": f1,
        "opensky_hex": h2,
        "opensky_flights": f2,
        "plane_types": plane_n,
    }


def main() -> int:
    run_once()
    return 0


if __name__ == "__main__":
    sys.exit(main())
