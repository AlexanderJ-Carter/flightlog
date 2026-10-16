"""构建/刷新自建参考库 catalog.db（地理 + 登记 + 词典）。

分层写入见 catalog_db.LAYERS。

用法::

    uv run python sync_catalog.py
    uv run python sync_catalog.py --skip-faa
    uv run python sync_catalog.py --only-geo
"""

from __future__ import annotations

import argparse
import csv
import io
import zipfile
from pathlib import Path

import httpx

import catalog_db

OA = "https://davidmegginson.github.io/ourairports-data"
FAA_URL = "https://registry.faa.gov/database/ReleasableAircraft.zip"
AS = "https://raw.githubusercontent.com/AviationShop"
OF_AIRPORTS = (
    "https://raw.githubusercontent.com/jpatokal/openflights/master/data/airports.dat"
)
IP2_IATA = (
    "https://raw.githubusercontent.com/ip2location/ip2location-iata-icao/"
    "master/iata-icao.csv"
)


def _get_text(url: str, timeout: float = 120.0) -> str:
    with httpx.Client(timeout=timeout, follow_redirects=True) as client:
        r = client.get(url, headers={"User-Agent": "FlightLogCatalog/2.0"})
        r.raise_for_status()
        return r.text


def _get_bytes(url: str, timeout: float = 300.0) -> bytes:
    with httpx.Client(timeout=timeout, follow_redirects=True) as client:
        r = client.get(url, headers={"User-Agent": "FlightLogCatalog/2.0"})
        r.raise_for_status()
        return r.content


def _i(v: str) -> int | None:
    v = (v or "").strip()
    if not v:
        return None
    try:
        return int(float(v))
    except ValueError:
        return None


def _f(v: str) -> float | None:
    v = (v or "").strip()
    if not v:
        return None
    try:
        return float(v)
    except ValueError:
        return None


def _norm_key(k: str) -> str:
    return (k or "").strip().lstrip("\ufeff").upper().replace(" ", "_").replace("-", "_")


def import_countries() -> int:
    text = _get_text(f"{OA}/countries.csv")
    rows = []
    for row in csv.DictReader(io.StringIO(text)):
        code = (row.get("code") or "").strip().upper()
        if not code:
            continue
        rows.append((
            code,
            (row.get("name") or "").strip()[:120],
            (row.get("continent") or "").strip().upper(),
            (row.get("wikipedia_link") or "").strip()[:240],
        ))
    n = catalog_db.replace_countries(rows)
    print(f"[geo] countries: {n}")
    return n


def import_regions() -> int:
    text = _get_text(f"{OA}/regions.csv")
    rows = []
    for row in csv.DictReader(io.StringIO(text)):
        code = (row.get("code") or "").strip().upper()
        if not code:
            continue
        rows.append((
            code,
            (row.get("name") or "").strip()[:120],
            (row.get("iso_country") or "").strip().upper(),
            (row.get("continent") or "").strip().upper(),
            (row.get("wikipedia_link") or "").strip()[:240],
        ))
    n = catalog_db.replace_regions(rows)
    print(f"[geo] regions: {n}")
    return n


def import_airports() -> int:
    text = _get_text(f"{OA}/airports.csv", timeout=180.0)
    rows: list[tuple] = []
    for row in csv.DictReader(io.StringIO(text)):
        ident = (row.get("ident") or "").strip().upper()
        icao = (row.get("icao_code") or row.get("gps_code") or ident).strip().upper()
        if not icao or len(icao) > 7:
            continue
        if (row.get("type") or "") == "closed":
            continue
        # 主档优先 4 字 ICAO；无 ICAO 时用 ident（仍可挂跑道）
        if len(icao) != 4 and len(ident) == 4:
            icao = ident
        if len(icao) < 3:
            continue
        rows.append((
            icao,
            (row.get("iata_code") or "").strip().upper(),
            ident,
            (row.get("name") or "").strip()[:160],
            "",  # name_zh later
            (row.get("type") or "").strip(),
            _f(row.get("latitude_deg") or ""),
            _f(row.get("longitude_deg") or ""),
            _i(row.get("elevation_ft") or ""),
            (row.get("continent") or "").strip().upper(),
            (row.get("iso_country") or "").strip().upper(),
            (row.get("iso_region") or "").strip().upper(),
            (row.get("municipality") or "").strip()[:80],
            "",  # timezone later
            1 if (row.get("scheduled_service") or "").strip().lower() == "yes" else 0,
            (row.get("gps_code") or "").strip().upper()[:8],
            (row.get("local_code") or "").strip().upper()[:12],
            (row.get("wikipedia_link") or "").strip()[:240],
            (row.get("home_link") or "").strip()[:240],
            (row.get("keywords") or "").strip()[:240],
        ))
    n = catalog_db.replace_airports(rows)
    print(f"[geo] airports: {n}")
    return n


def patch_timezones() -> int:
    """OpenFlights airports.dat → timezone。"""
    text = _get_text(OF_AIRPORTS, timeout=120.0)
    pairs: list[tuple[str, str]] = []
    for line in text.splitlines():
        parts = next(csv.reader([line]))
        if len(parts) < 12:
            continue
        icao = (parts[5] or "").strip().upper()
        tz = (parts[11] or "").strip()
        if icao == "\\N" or not icao or not tz or tz == "\\N":
            continue
        pairs.append((icao, tz[:64]))
    n = catalog_db.patch_airport_timezones(pairs)
    print(f"[geo] timezones patched (airports with tz): {n}")
    return n


def patch_name_zh() -> int:
    from airports import NAME_ZH

    # catalog_db.patch_airport_zh 期望 (iata, name_zh)
    pairs = [(code, zh) for code, zh in NAME_ZH.items()]
    n = catalog_db.patch_airport_zh(pairs)
    print(f"[geo] name_zh rows with zh: {n}")
    return n


def enrich_from_ip2location() -> int:
    """用 IP2Location IATA/ICAO 表补缺省 IATA（已有 icao 行）。"""
    text = _get_text(IP2_IATA, timeout=120.0)
    catalog_db.init()
    updated = 0
    with catalog_db._lock:
        with catalog_db._connect() as conn:
            for row in csv.DictReader(io.StringIO(text)):
                icao = (row.get("icao") or "").strip().upper()
                iata = (row.get("iata") or "").strip().upper()
                if len(icao) != 4 or len(iata) != 3:
                    continue
                cur = conn.execute(
                    "SELECT iata FROM geo_airports WHERE icao=?", (icao,)
                ).fetchone()
                if not cur:
                    continue
                if (cur["iata"] or "") == "":
                    conn.execute(
                        "UPDATE geo_airports SET iata=? WHERE icao=?", (iata, icao)
                    )
                    updated += 1
            n_iata = conn.execute(
                "SELECT COUNT(*) FROM geo_airports WHERE iata!=''"
            ).fetchone()[0]
    catalog_db.mark_source(
        "ip2location_iata", "geo", n_iata, note=f"filled_iata={updated}"
    )
    print(f"[geo] ip2location filled iata on {updated} rows (total with iata {n_iata})")
    return updated


def import_runways() -> int:
    text = _get_text(f"{OA}/runways.csv")
    rows = []
    for row in csv.DictReader(io.StringIO(text)):
        ident = (row.get("airport_ident") or "").strip().upper()
        if not ident:
            continue
        rows.append((
            ident,
            (row.get("le_ident") or "").strip().upper(),
            (row.get("he_ident") or "").strip().upper(),
            _i(row.get("length_ft") or ""),
            _i(row.get("width_ft") or ""),
            (row.get("surface") or "").strip(),
            1 if (row.get("lighted") or "0").strip() == "1" else 0,
            1 if (row.get("closed") or "0").strip() == "1" else 0,
        ))
    n = catalog_db.replace_runways(rows)
    print(f"[geo] runways: {n}")
    return n


def import_frequencies() -> int:
    text = _get_text(f"{OA}/airport-frequencies.csv")
    rows = []
    for row in csv.DictReader(io.StringIO(text)):
        ident = (row.get("airport_ident") or "").strip().upper()
        if not ident:
            continue
        rows.append((
            ident,
            (row.get("type") or "").strip(),
            (row.get("description") or "").strip()[:120],
            _f(row.get("frequency_mhz") or ""),
        ))
    n = catalog_db.replace_frequencies(rows)
    print(f"[geo] frequencies: {n}")
    return n


def import_navaids() -> int:
    text = _get_text(f"{OA}/navaids.csv")
    rows = []
    for row in csv.DictReader(io.StringIO(text)):
        ident = (row.get("ident") or "").strip().upper()
        if not ident:
            continue
        rows.append((
            ident,
            (row.get("name") or "").strip()[:120],
            (row.get("type") or "").strip(),
            _f(row.get("frequency_khz") or ""),
            _f(row.get("latitude_deg") or ""),
            _f(row.get("longitude_deg") or ""),
            (row.get("iso_country") or "").strip().upper(),
            (row.get("associated_airport") or "").strip().upper(),
        ))
    n = catalog_db.replace_navaids(rows)
    print(f"[geo] navaids: {n}")
    return n


def import_icao_types() -> int:
    text = _get_text(f"{AS}/aircraft-type-designators/main/aircraft_types.csv")
    rows = []
    for row in csv.DictReader(io.StringIO(text)):
        d = (row.get("icao_type_designator") or "").strip().upper()
        if d:
            rows.append((
                d,
                (row.get("aircraft") or "").strip()[:120],
                (row.get("manufacturer") or "").strip()[:80],
                (row.get("category") or "").strip()[:40],
            ))
    n = catalog_db.replace_icao_types(rows)
    print(f"[reg] icao_types: {n}")
    return n


def import_reg_prefixes() -> int:
    text = _get_text(
        f"{AS}/aircraft-registration-prefixes/main/aircraft-registration-prefixes.csv"
    )
    rows = [
        ((row.get("prefix") or "").strip().upper(),
         (row.get("country") or "").strip()[:80], "")
        for row in csv.DictReader(io.StringIO(text))
        if (row.get("prefix") or "").strip()
    ]
    n = catalog_db.replace_prefixes(rows)
    print(f"[reg] prefixes: {n}")
    return n


def import_metar_codes() -> int:
    text = _get_text(f"{AS}/metar-taf-abbreviations/main/metar-taf-codes.csv")
    rows = [
        ((row.get("code") or "").strip().upper(),
         (row.get("meaning") or "").strip()[:200])
        for row in csv.DictReader(io.StringIO(text))
        if (row.get("code") or "").strip()
    ]
    n = catalog_db.replace_metar(rows)
    print(f"[lex] metar: {n}")
    return n


def import_squawk_codes() -> int:
    text = _get_text(f"{AS}/transponder-squawk-codes/main/squawk-codes.csv")
    rows = [
        ((row.get("code") or "").strip(),
         (row.get("meaning") or "").strip()[:200])
        for row in csv.DictReader(io.StringIO(text))
        if (row.get("code") or "").strip()
    ]
    n = catalog_db.replace_squawk(rows)
    print(f"[lex] squawk: {n}")
    return n


def _parse_faa_master(master_text: str) -> list[tuple]:
    text = master_text.lstrip("\ufeff")
    if "N-NUMBER" not in text[:500].upper():
        return []
    reader = csv.DictReader(io.StringIO(text))
    if not reader.fieldnames:
        return []
    fieldmap = {_norm_key(k): k for k in reader.fieldnames}

    def g(row: dict, *names: str) -> str:
        for n in names:
            key = fieldmap.get(_norm_key(n))
            if key is not None:
                return str(row.get(key) or "").strip()
        return ""

    out: list[tuple] = []
    for row in reader:
        n = g(row, "N_NUMBER").lstrip("N").upper()
        if not n:
            continue
        mode_s = g(row, "MODE_S_CODE_HEX").upper().replace(" ", "")
        if mode_s and not all(c in "0123456789ABCDEF" for c in mode_s):
            mode_s = ""
        out.append((
            "N" + n,
            mode_s[-6:] if mode_s else "",
            g(row, "MFR_MDL_CODE")[:40],
            g(row, "YEAR_MFR")[:8],
            g(row, "NAME")[:120],
            g(row, "CITY")[:60],
            g(row, "STATE")[:8],
            g(row, "STATUS_CODE")[:8],
            g(row, "TYPE_AIRCRAFT")[:8],
        ))
    return out


def import_faa(*, cache_path: Path | None = None) -> int:
    try:
        if cache_path and cache_path.is_file() and cache_path.stat().st_size > 1_000_000:
            print(f"[reg] FAA cache {cache_path}")
            blob = cache_path.read_bytes()
        else:
            print(f"[reg] FAA download…")
            blob = _get_bytes(FAA_URL)
            if cache_path:
                cache_path.parent.mkdir(parents=True, exist_ok=True)
                cache_path.write_bytes(blob)
        with zipfile.ZipFile(io.BytesIO(blob)) as zf:
            master_name = next(
                (n for n in zf.namelist()
                 if n.upper().endswith("MASTER.TXT") or n.upper().endswith("MASTER.CSV")),
                None,
            )
            if not master_name:
                raise RuntimeError("zip 内无 MASTER")
            raw = zf.read(master_name)
        try:
            text = raw.decode("utf-8-sig")
        except UnicodeDecodeError:
            text = raw.decode("latin-1")
        rows = _parse_faa_master(text)
        if not rows:
            raise RuntimeError("MASTER 解析为空")
        n = catalog_db.replace_faa(rows)
        print(f"[reg] faa: {n}")
        return n
    except Exception as e:
        catalog_db.mark_source("faa_registry", "reg", 0, note=f"skip: {e}"[:200])
        print(f"[reg] FAA 跳过: {e}")
        return 0


def import_geo() -> dict:
    out = {
        "countries": import_countries(),
        "regions": import_regions(),
        "airports": import_airports(),
        "runways": import_runways(),
        "frequencies": import_frequencies(),
        "navaids": import_navaids(),
    }
    patch_timezones()
    patch_name_zh()
    enrich_from_ip2location()
    return out


def import_reg_lex(*, skip_faa: bool) -> dict:
    out = {
        "icao_types": import_icao_types(),
        "reg_prefixes": import_reg_prefixes(),
        "metar": import_metar_codes(),
        "squawk": import_squawk_codes(),
    }
    if not skip_faa:
        cache = Path(catalog_db.DATA_DIR) / "cache" / "ReleasableAircraft.zip"
        out["faa"] = import_faa(cache_path=cache)
    return out


def run_all(
    *,
    skip_faa: bool = False,
    only_geo: bool = False,
    only_reg: bool = False,
) -> dict:
    catalog_db.init()
    out: dict = {}
    if only_reg:
        out.update(import_reg_lex(skip_faa=skip_faa))
        return out
    if only_geo:
        out.update(import_geo())
        return out
    out.update(import_geo())
    out.update(import_reg_lex(skip_faa=skip_faa))
    return out


def main() -> None:
    p = argparse.ArgumentParser(description="刷新自建航空参考库 catalog.db")
    p.add_argument("--skip-faa", action="store_true")
    p.add_argument("--only-geo", action="store_true", help="只刷地理层")
    p.add_argument("--only-reg", action="store_true", help="只刷登记/词典层")
    args = p.parse_args()
    print("catalog:", Path(catalog_db.CATALOG_DB).resolve())
    print(run_all(
        skip_faa=args.skip_faa,
        only_geo=args.only_geo,
        only_reg=args.only_reg,
    ))
    st = catalog_db.stats()
    for layer, counts in st["counts"].items():
        print(f"  [{layer}] {counts}")


if __name__ == "__main__":
    main()
