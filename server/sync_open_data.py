#!/usr/bin/env python3
"""从公开开源源构建本地飞友库（不爬商业站）。

来源：
  1. OpenSky Aircraft Database（机尾 hex / 注册号 / 机型）~100MB
  2. OpenFlights airlines + routes（航司名、航线常用机型）

用法：
    cd server
    FLIGHTLOG_DATA_DIR=../data ../.venv/bin/python sync_open_data.py
    # 只要航司航线、不要百兆机尾：
    FLIGHTLOG_DATA_DIR=../data ../.venv/bin/python sync_open_data.py --skip-aircraft
"""
from __future__ import annotations

import argparse
import csv
import io
import os
import sys
import urllib.request

import catalog_db
import fleet_db

OPENSKY_URL = os.environ.get(
    "FLIGHTLOG_OPENSKY_URL",
    "https://s3.opensky-network.org/data-samples/metadata/"
    "aircraft-database-complete-2025-08.csv",
)
OF_AIRLINES = (
    "https://raw.githubusercontent.com/jpatokal/openflights/master/data/airlines.dat"
)
OF_ROUTES = (
    "https://raw.githubusercontent.com/jpatokal/openflights/master/data/routes.dat"
)
BATCH = 2000
UA = {"User-Agent": "flightlog-sync/1.0 (open-data import)"}


def _open(url: str, timeout: int = 600):
    req = urllib.request.Request(url, headers=UA)
    return urllib.request.urlopen(req, timeout=timeout)


def import_opensky() -> int:
    print(f"[OpenSky] 下载机尾库…\n  {OPENSKY_URL}")
    fleet_db.init()
    with _open(OPENSKY_URL) as resp:
        text = io.TextIOWrapper(resp, encoding="utf-8", errors="replace")
        reader = csv.DictReader(text, quotechar="'")
        batch: list[tuple] = []
        total = kept = 0
        for row in reader:
            total += 1
            hx = (row.get("icao24") or "").strip().upper()
            reg = (row.get("registration") or "").strip().upper()
            tc = (row.get("typecode") or "").strip().upper()
            model = (row.get("model") or "").strip()
            op = (row.get("operator") or row.get("operatorIcao") or "").strip()
            country = (row.get("country") or "").strip()
            if len(hx) < 6 or (not reg and not tc):
                continue
            batch.append((hx, reg, tc, model, op, country))
            if len(batch) >= BATCH:
                fleet_db.upsert_aircraft_rows(batch)
                kept += len(batch)
                batch.clear()
                if kept % 40000 == 0:
                    print(f"  已写入 {kept}（扫描 {total}）")
        if batch:
            fleet_db.upsert_aircraft_rows(batch)
            kept += len(batch)
    print(f"[OpenSky] 完成：扫描 {total}，有效 {kept}")
    return kept


def import_openflights() -> tuple[int, int]:
    """航司/航线写入 catalog.db 的 net_ 层。"""
    print("[OpenFlights] 下载 airlines.dat / routes.dat → catalog.net_*")
    catalog_db.init()

    airlines: list[tuple] = []
    with _open(OF_AIRLINES, timeout=120) as resp:
        text = io.TextIOWrapper(resp, encoding="utf-8", errors="replace")
        # Airline ID, Name, Alias, IATA, ICAO, Callsign, Country, Active
        for line in text:
            parts = next(csv.reader([line]))
            if len(parts) < 8:
                continue
            iata = (parts[3] or "").strip().upper()
            icao = (parts[4] or "").strip().upper()
            name = (parts[1] or "").strip()
            callsign = (parts[5] or "").strip()
            country = (parts[6] or "").strip()
            active = (parts[7] or "").strip().upper() == "Y"
            if len(iata) != 2 or iata == "\\N":
                continue
            if not active:
                continue
            airlines.append((
                iata,
                icao if icao != "\\N" else "",
                name,
                country,
                callsign if callsign != "\\N" else "",
                1,
            ))
    n_air = catalog_db.replace_airlines(airlines)
    print(f"  [net] airlines：{n_air}")

    routes: list[tuple] = []
    with _open(OF_ROUTES, timeout=120) as resp:
        text = io.TextIOWrapper(resp, encoding="utf-8", errors="replace")
        for line in text:
            parts = next(csv.reader([line]))
            if len(parts) < 9:
                continue
            airline = (parts[0] or "").strip().upper()
            frm = (parts[2] or "").strip().upper()
            to = (parts[4] or "").strip().upper()
            equip = (parts[8] or "").strip().upper().replace("\\N", "")
            if len(airline) != 2 or len(frm) != 3 or len(to) != 3:
                continue
            first = equip.split()[0] if equip else ""
            routes.append((airline, frm, to, first, equip))
    n_rt = catalog_db.replace_routes(routes)
    print(f"  [net] routes：{n_rt}")
    return n_air, n_rt


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="导入公开航空开放数据")
    p.add_argument(
        "--skip-aircraft",
        action="store_true",
        help="跳过 OpenSky 大文件，只导 OpenFlights",
    )
    p.add_argument(
        "--only-aircraft",
        action="store_true",
        help="只导 OpenSky 机尾",
    )
    args = p.parse_args(argv)

    print(f"数据目录：{fleet_db.DATA_DIR}")
    print(f"观测库：{fleet_db.FLEET_DB}")
    print(f"参考库：{catalog_db.CATALOG_DB}")
    fleet_db.init()
    catalog_db.init()

    if not args.skip_aircraft:
        import_opensky()
    if not args.only_aircraft:
        import_openflights()
        from harvest_live import import_planes_dat
        import_planes_dat()

    print("—— fleet（观测/机尾）——")
    for k, v in fleet_db.stats().items():
        print(f"  {k}: {v}")
    print("—— catalog.net ——")
    for k, v in catalog_db.stats()["counts"]["net"].items():
        print(f"  {k}: {v}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
