"""多源航班导入：OpenFlights / MyFlightradar24 风格 CSV / FlightLog JSON。"""

from __future__ import annotations

import csv
import io
import json
import re
from typing import Any


def _null(v: str | None) -> str:
    s = (v or "").strip().lstrip("\ufeff")
    if not s or s in ("\\N", "N/A", "-", "null", "None"):
        return ""
    return s


def _norm_date(raw: str) -> str:
    s = _null(raw).split()[0] if raw else ""
    if not s:
        raise ValueError("缺少日期")
    if re.fullmatch(r"\d{4}", s):
        return f"{s}-01-01"
    if re.fullmatch(r"\d{4}-\d{1,2}-\d{1,2}", s):
        y, m, d = s.split("-")
        return f"{int(y):04d}-{int(m):02d}-{int(d):02d}"
    if re.fullmatch(r"\d{1,2}/\d{1,2}/\d{4}", s):
        a, b, y = s.split("/")
        # 优先按 OpenFlights 常见 MM/DD/YYYY
        return f"{int(y):04d}-{int(a):02d}-{int(b):02d}"
    if re.fullmatch(r"\d{1,2}\.\d{1,2}\.\d{4}", s):
        d, m, y = s.split(".")
        return f"{int(y):04d}-{int(m):02d}-{int(d):02d}"
    raise ValueError(f"无法解析日期：{raw!r}")


def _duration_min(raw: str) -> int | None:
    s = _null(raw)
    if not s:
        return None
    m = re.fullmatch(r"(\d{1,3}):(\d{2})(?::\d{2})?", s)
    if m:
        return int(m.group(1)) * 60 + int(m.group(2))
    if s.isdigit():
        return int(s)
    return None


def _map_cabin(raw: str) -> str:
    s = _null(raw).upper()
    return {
        "F": "first", "FIRST": "first",
        "C": "business", "J": "business", "BUSINESS": "business", "B": "business",
        "P": "economy+", "W": "economy+", "PREMIUM": "economy+", "ECONOMY+": "economy+",
        "Y": "economy", "E": "economy", "ECONOMY": "economy",
    }.get(s, s.lower() if s.lower() in ("economy", "economy+", "business", "first") else "")


def _map_seat_type(raw: str) -> str:
    s = _null(raw).upper()
    return {
        "W": "window", "WINDOW": "window",
        "A": "aisle", "AISLE": "aisle",
        "M": "middle", "MIDDLE": "middle",
    }.get(s, s.lower() if s.lower() in ("window", "aisle", "middle") else "")


def _map_reason(raw: str) -> str:
    s = _null(raw).upper()
    return {
        "L": "leisure", "P": "leisure", "LEISURE": "leisure",
        "B": "business", "BUSINESS": "business",
        "C": "crew", "CREW": "crew",
        "O": "other", "OTHER": "other",
    }.get(s, s.lower() if s.lower() in ("leisure", "business", "crew", "other") else "")


def _airport(code: str) -> str:
    c = _null(code).upper()
    # "Beijing (PEK)" / "PEK - Beijing" 等
    m = re.search(r"\(([A-Z0-9]{3,4})\)", c)
    if m:
        c = m.group(1)
    else:
        m = re.match(r"^([A-Z0-9]{3,4})\b", c)
        if m:
            c = m.group(1)
    if len(c) == 4 and c.isalpha():
        import catalog_db
        ap = catalog_db.get_airport(c)
        if ap and ap.get("iata"):
            return ap["iata"]
        return ""
    if len(c) == 3 and c.isalnum():
        return c
    return ""


def _flight_no(airline: str, number: str) -> str:
    al = _null(airline).upper().replace(" ", "")
    num = _null(number).upper().replace(" ", "")
    if not num:
        return al[:8]
    if re.match(r"^[A-Z0-9]{2}\d", num):
        return num
    if len(al) == 2 and num.isdigit():
        return al + num
    return num


def _row(
    *,
    date: str,
    flight: str,
    frm: str,
    to: str,
    seat: str = "",
    note: str = "",
    aircraft: str = "",
    registration: str = "",
    cabin_class: str = "",
    seat_type: str = "",
    flight_reason: str = "",
    duration_min: int | None = None,
    airline_name: str = "",
    dep_time: str = "",
    arr_time: str = "",
    dep_terminal: str = "",
    arr_terminal: str = "",
    dep_gate: str = "",
    arr_gate: str = "",
    trip_id: str = "",
    distance_km: float | None = None,
) -> dict[str, Any]:
    return {
        "date": date,
        "flight": flight,
        "from": frm,
        "to": to,
        "seat": seat,
        "note": note,
        "aircraft": aircraft,
        "registration": registration,
        "cabin_class": cabin_class,
        "seat_type": seat_type,
        "flight_reason": flight_reason,
        "duration_min": duration_min,
        "airline_name": airline_name,
        "dep_time": dep_time,
        "arr_time": arr_time,
        "dep_terminal": dep_terminal,
        "arr_terminal": arr_terminal,
        "dep_gate": dep_gate,
        "arr_gate": arr_gate,
        "trip_id": trip_id,
        "distance_km": distance_km,
    }


def _time_part(raw: str) -> str:
    s = _null(raw)
    if not s:
        return ""
    m = re.search(r"(\d{1,2}):(\d{2})", s)
    if m:
        return f"{int(m.group(1)):02d}:{m.group(2)}"
    m = re.search(r"T(\d{2}):(\d{2})", s)
    if m:
        return f"{m.group(1)}:{m.group(2)}"
    return ""


# OpenFlights export 常见表头
_OF_HEADERS = {
    "date", "from", "to", "flight_number", "airline", "distance", "duration",
    "seat", "seat_type", "class", "reason", "plane", "registration", "note",
}


def parse_openflights_csv(text: str) -> list[dict]:
    f = io.StringIO(text.lstrip("\ufeff"))
    reader = csv.DictReader(f)
    if not reader.fieldnames:
        raise ValueError("CSV 无表头")
    headers = {h.strip().lstrip("\ufeff").lower() for h in reader.fieldnames}
    if "from" not in headers or "to" not in headers:
        raise ValueError("不像 OpenFlights CSV（需 from/to 列）")
    out: list[dict] = []
    for raw in reader:
        row = { (k or "").strip().lstrip("\ufeff").lower(): _null(v) for k, v in raw.items() }
        try:
            date = _norm_date(row.get("date", ""))
            frm = _airport(row.get("from", ""))
            to = _airport(row.get("to", ""))
            if not frm or not to:
                continue
            flight = _flight_no(row.get("airline", ""), row.get("flight_number", ""))
            if not flight:
                flight = "XX0000"
            note_parts = [row.get("note", "")]
            if row.get("trip"):
                note_parts.append(f"trip:{row['trip']}")
            dist = row.get("distance", "")
            distance_km = float(dist) if dist.replace(".", "", 1).isdigit() else None
            out.append(_row(
                date=date,
                flight=flight,
                frm=frm,
                to=to,
                seat=row.get("seat", ""),
                note=" · ".join(p for p in note_parts if p),
                aircraft=row.get("plane", ""),
                registration=row.get("registration", "").upper(),
                cabin_class=_map_cabin(row.get("class", "")),
                seat_type=_map_seat_type(row.get("seat_type", "")),
                flight_reason=_map_reason(row.get("reason", "")),
                duration_min=_duration_min(row.get("duration", "")),
                airline_name=row.get("airline", "") if len(row.get("airline", "")) > 2 else "",
                trip_id=row.get("trip", ""),
                distance_km=distance_km,
            ))
        except ValueError:
            continue
    return out


def parse_fr24_csv(text: str) -> list[dict]:
    """MyFlightradar24 导出：列名常含 Date / Flight number / From / To 等。"""
    f = io.StringIO(text.lstrip("\ufeff"))
    reader = csv.DictReader(f)
    if not reader.fieldnames:
        raise ValueError("CSV 无表头")

    def pick(row: dict, *names: str) -> str:
        lower = { (k or "").strip().lower(): v for k, v in row.items() }
        for n in names:
            if n.lower() in lower:
                return _null(lower[n.lower()])
        # 模糊包含
        for n in names:
            for k, v in lower.items():
                if n.lower() in k:
                    return _null(v)
        return ""

    out: list[dict] = []
    for raw in reader:
        try:
            date = _norm_date(pick(raw, "date", "flight date", "dep date"))
            frm = _airport(pick(raw, "from", "from code", "origin", "dep"))
            to = _airport(pick(raw, "to", "to code", "destination", "arr"))
            if not frm or not to:
                continue
            flight = pick(raw, "flight number", "flight", "flight no", "callsign").upper().replace(" ", "")
            if not flight:
                flight = "XX0000"
            out.append(_row(
                date=date,
                flight=flight,
                frm=frm,
                to=to,
                seat=pick(raw, "seat", "seat number"),
                note=pick(raw, "note", "notes", "comment"),
                aircraft=pick(raw, "aircraft", "plane", "type", "aircraft type"),
                registration=pick(raw, "registration", "reg", "tail").upper(),
                cabin_class=_map_cabin(pick(raw, "class", "cabin", "cabin class")),
                seat_type=_map_seat_type(pick(raw, "seat type", "seattype")),
                flight_reason=_map_reason(pick(raw, "reason", "flight reason")),
                duration_min=_duration_min(pick(raw, "duration", "flight time")),
                airline_name=pick(raw, "airline", "airline name"),
                dep_time=_time_part(pick(raw, "dep time", "departure", "departure time")),
                arr_time=_time_part(pick(raw, "arr time", "arrival", "arrival time")),
            ))
        except ValueError:
            continue
    return out


def parse_flighty_csv(text: str) -> list[dict]:
    """Flighty 导出 CSV（列名含 Airline / Flight / From / To / Gate 等）。"""
    f = io.StringIO(text.lstrip("\ufeff"))
    reader = csv.DictReader(f)
    if not reader.fieldnames:
        raise ValueError("CSV 无表头")

    def pick(row: dict, *names: str) -> str:
        lower = {(k or "").strip().lower(): v for k, v in row.items()}
        for n in names:
            if n.lower() in lower:
                return _null(lower[n.lower()])
        for n in names:
            for k, v in lower.items():
                if n.lower() in k:
                    return _null(v)
        return ""

    out: list[dict] = []
    for raw in reader:
        try:
            date_raw = pick(
                raw, "date", "departure date", "dep date", "flight date"
            )
            if not date_raw:
                dep = pick(raw, "departure", "takeoff", "dep")
                date_raw = dep.split("T")[0] if dep else ""
            date = _norm_date(date_raw)
            frm = _airport(pick(raw, "from", "from code", "origin", "departure airport"))
            to = _airport(pick(raw, "to", "to code", "destination", "arrival airport"))
            if not frm or not to:
                continue
            flight = pick(raw, "flight", "flight number", "flight no").upper().replace(" ", "")
            airline = pick(raw, "airline", "airline name")
            if not flight:
                flight = _flight_no(airline, pick(raw, "number", "flight number"))
            if not flight:
                flight = "XX0000"
            out.append(_row(
                date=date,
                flight=flight,
                frm=frm,
                to=to,
                seat=pick(raw, "seat", "seat number"),
                note=pick(raw, "notes", "note", "comment"),
                aircraft=pick(
                    raw, "aircraft type", "aircraft", "aircraft_type_name", "plane"
                ),
                registration=pick(
                    raw, "tail number", "registration", "aircraft registration"
                ).upper(),
                cabin_class=_map_cabin(pick(raw, "cabin", "cabin class", "class")),
                seat_type=_map_seat_type(pick(raw, "seat type", "seattype")),
                flight_reason=_map_reason(pick(raw, "flight reason", "reason", "purpose")),
                duration_min=_duration_min(pick(raw, "duration", "flight time")),
                airline_name=airline if len(airline) > 2 else "",
                dep_time=_time_part(
                    pick(raw, "departure time", "dep time", "departure", "takeoff")
                ),
                arr_time=_time_part(
                    pick(raw, "arrival time", "arr time", "arrival", "landing")
                ),
                dep_terminal=pick(raw, "dep terminal", "departure terminal", "from terminal"),
                arr_terminal=pick(raw, "arr terminal", "arrival terminal", "to terminal"),
                dep_gate=pick(raw, "dep gate", "departure gate", "gate"),
                arr_gate=pick(raw, "arr gate", "arrival gate"),
            ))
        except ValueError:
            continue
    return out


def parse_tripit_ics(text: str) -> list[dict]:
    """TripIt / 日历 ICS：从 VEVENT 提取航班号与机场。"""
    blocks = re.split(r"BEGIN:VEVENT", text, flags=re.I)
    out: list[dict] = []
    for block in blocks[1:]:
        body = block.split("END:VEVENT", 1)[0]
        fields: dict[str, str] = {}
        key = None
        for line in body.splitlines():
            if line.startswith(" ") and key:
                fields[key] += line[1:].strip()
                continue
            if ":" not in line:
                continue
            k, v = line.split(":", 1)
            key = k.split(";")[0].upper()
            fields[key] = v.strip()
        summary = fields.get("SUMMARY", "")
        desc = fields.get("DESCRIPTION", "")
        loc = fields.get("LOCATION", "")
        blob = " ".join((summary, desc, loc))
        flight_m = re.search(
            r"\b([A-Z]{2}|[A-Z]\d|\d[A-Z])\s?(\d{1,4}[A-Z]?)\b",
            blob.upper(),
        )
        flight = (
            (flight_m.group(1) + flight_m.group(2)).replace(" ", "")
            if flight_m
            else ""
        )
        codes = re.findall(
            r"\b([A-Z]{3})\b",
            re.sub(r"https?://\S+", "", blob.upper()),
        )
        # 过滤常见非机场词
        skip = {
            "UTC", "GMT", "MON", "TUE", "WED", "THU", "FRI", "SAT", "SUN",
            "JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP",
            "OCT", "NOV", "DEC", "FLIGHT", "AIR", "THE", "AND", "FOR",
        }
        aps = [c for c in codes if c not in skip]
        frm = _airport(aps[0]) if len(aps) >= 1 else ""
        to = _airport(aps[1]) if len(aps) >= 2 else ""
        if not frm or not to:
            continue
        dt = fields.get("DTSTART", "")
        date_m = re.search(r"(\d{4})(\d{2})(\d{2})", dt)
        if not date_m:
            continue
        date = f"{date_m.group(1)}-{date_m.group(2)}-{date_m.group(3)}"
        dep_time = ""
        tm = re.search(r"T(\d{2})(\d{2})", dt)
        if tm:
            dep_time = f"{tm.group(1)}:{tm.group(2)}"
        arr_time = ""
        dt_end = fields.get("DTEND", "")
        tm2 = re.search(r"T(\d{2})(\d{2})", dt_end)
        if tm2:
            arr_time = f"{tm2.group(1)}:{tm2.group(2)}"
        if not flight:
            flight = "XX0000"
        out.append(_row(
            date=date,
            flight=flight,
            frm=frm,
            to=to,
            note=summary[:200],
            dep_time=dep_time,
            arr_time=arr_time,
        ))
    return out


def parse_flightlog_json(text: str) -> list[dict]:
    data = json.loads(text)
    if isinstance(data, dict):
        rows = data.get("flights") or data.get("rows") or []
    elif isinstance(data, list):
        rows = data
    else:
        raise ValueError("JSON 格式无法识别")
    out = []
    for r in rows:
        if not isinstance(r, dict):
            continue
        frm = _airport(str(r.get("from") or r.get("from_ap") or ""))
        to = _airport(str(r.get("to") or r.get("to_ap") or ""))
        if not frm or not to:
            continue
        out.append(_row(
            date=_norm_date(str(r.get("date") or "")),
            flight=str(r.get("flight") or "XX0000").upper().replace(" ", ""),
            frm=frm,
            to=to,
            seat=str(r.get("seat") or ""),
            note=str(r.get("note") or ""),
            aircraft=str(r.get("aircraft") or ""),
            registration=str(r.get("registration") or "").upper(),
            cabin_class=_map_cabin(str(r.get("cabin_class") or "")),
            seat_type=_map_seat_type(str(r.get("seat_type") or "")),
            flight_reason=_map_reason(str(r.get("flight_reason") or "")),
            duration_min=int(r["duration_min"]) if r.get("duration_min") not in (None, "") else None,
            airline_name=str(r.get("airline_name") or ""),
            dep_time=_time_part(str(r.get("dep_time") or "")),
            arr_time=_time_part(str(r.get("arr_time") or "")),
            dep_terminal=str(r.get("dep_terminal") or ""),
            arr_terminal=str(r.get("arr_terminal") or ""),
            dep_gate=str(r.get("dep_gate") or ""),
            arr_gate=str(r.get("arr_gate") or ""),
            trip_id=str(r.get("trip_id") or ""),
            distance_km=(
                float(r["distance_km"])
                if r.get("distance_km") not in (None, "")
                else None
            ),
        ))
    return out


def detect_and_parse(text: str, source: str = "auto") -> tuple[str, list[dict]]:
    """返回 (识别到的来源, 标准化行列表)。"""
    src = (source or "auto").strip().lower()
    t = text.lstrip("\ufeff")
    if src in ("tripit", "ics") or (
        src == "auto" and "BEGIN:VEVENT" in t.upper()
    ):
        return "tripit", parse_tripit_ics(t)
    if src == "json" or (src == "auto" and t[:1] in "[{"):
        return "flightlog-json", parse_flightlog_json(t)
    if src == "openflights":
        return "openflights", parse_openflights_csv(t)
    if src in ("fr24", "myfr24", "flightradar24"):
        return "fr24", parse_fr24_csv(t)
    if src == "flighty":
        return "flighty", parse_flighty_csv(t)
    head = t.splitlines()[0].lower() if t else ""
    if "flight_number" in head and "seat_type" in head:
        return "openflights", parse_openflights_csv(t)
    if "tail number" in head or "aircraft_type_name" in head or (
        "airline" in head and "gate" in head and "from" in head
    ):
        return "flighty", parse_flighty_csv(t)
    if "from" in head and "to" in head:
        if "flight_number" in head or "seat_type" in head or "plane" in head:
            return "openflights", parse_openflights_csv(t)
        if "flight number" in head or "flight class" in head:
            return "fr24", parse_fr24_csv(t)
        return "flighty", parse_flighty_csv(t)
    if src == "auto":
        for name, fn in (
            ("flighty", parse_flighty_csv),
            ("fr24", parse_fr24_csv),
            ("openflights", parse_openflights_csv),
        ):
            rows = fn(t)
            if rows:
                return name, rows
        raise ValueError(
            "无法识别文件格式，请指定 source=openflights|fr24|flighty|tripit|json"
        )
    raise ValueError(f"未知 source：{source}")
