"""行程短信 → 结构化提取（正则版）。

识别：航班号、日期、城市（→三字码）、座位号；输出与 POST /api/flights
一致的行结构。
"""
import re
from datetime import date

from airports import CITY_TO_AP

FLIGHT_RE = re.compile(
    r"(?<![0-9A-Z])((?:[0-9][A-Z]|[A-Z][0-9]|[A-Z]{2})[-\s]?(\d{3,4}))(?![0-9A-Z])",
    re.IGNORECASE,
)

DATE_FULL_RE = re.compile(
    r"(20\d{2})\s*[-/年.]\s*(\d{1,2})\s*[-/月.]\s*(\d{1,2})\s*日?")
DATE_MD_RE = re.compile(r"(\d{1,2})\s*月\s*(\d{1,2})\s*日?")

SEAT_RES = [
    re.compile(r"(?:座位|Seat|SEAT|seat)\s*[:：]?\s*(\d{1,2}[A-Z])"),
    re.compile(r"(\d{1,2}[A-Z])\s*[座排位]"),
]

_CITY_ALT = sorted(CITY_TO_AP.keys(), key=len, reverse=True)
_CITY_PAT = "|".join(_CITY_ALT)
PAIR_RE = re.compile(rf"({_CITY_PAT})(?:市)?\s*[-–—~至到→>]\s*({_CITY_PAT})(?:市)?")
DEP_RES = [
    re.compile(rf"从\s*({_CITY_PAT})"),
    re.compile(rf"({_CITY_PAT})\s*(?:出发|起飞)"),
]
ARR_RES = [
    re.compile(rf"(?:飞往|前往|开往|抵达|到达|飞到|飞至)\s*({_CITY_PAT})"),
    re.compile(rf"[到至]\s*({_CITY_PAT})"),
]


def _parse_dates(text):
    """返回 text 中出现的所有日期，格式 YYYY-MM-DD，去重保序。"""
    out = []
    for m in DATE_FULL_RE.finditer(text):
        y, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
        try:
            out.append(f"{y:04d}-{mo:02d}-{d:02d}")
        except ValueError:
            pass
    for m in DATE_MD_RE.finditer(text):
        mo, d = int(m.group(1)), int(m.group(2))
        try:
            out.append(f"{date.today().year:04d}-{mo:02d}-{d:02d}")
        except ValueError:
            pass
    seen, uniq = set(), []
    for d in out:
        if d not in seen:
            seen.add(d)
            uniq.append(d)
    return uniq


def _parse_flights(text):
    """返回所有航班号（大写、去掉中间空白），去重保序。"""
    out = []
    for m in FLIGHT_RE.finditer(text):
        raw = re.sub(r"[-\s]", "", m.group(1)).upper()
        if raw not in out:
            out.append(raw)
    return out


def _parse_seat(text):
    for pat in SEAT_RES:
        m = pat.search(text)
        if m:
            return m.group(1).upper()
    return ""


def _parse_route(text):
    """返回 (from_ap, to_ap)，识别不到的端点为空串。"""
    frm, to = "", ""
    m = PAIR_RE.search(text)
    if m:
        return CITY_TO_AP[m.group(1)], CITY_TO_AP[m.group(2)]
    for pat in DEP_RES:
        m = pat.search(text)
        if m:
            frm = CITY_TO_AP[m.group(1)]
            break
    for pat in ARR_RES:
        m = pat.search(text)
        if m:
            to = CITY_TO_AP[m.group(1)]
            break
    return frm, to


def extract(text):
    """POST /api/extract：短信原文 → 行列表。正则优先，空结果时可选 AI。"""
    text = text or ""
    if not text.strip():
        return []

    dates = _parse_dates(text)
    flights = _parse_flights(text)
    frm, to = _parse_route(text)
    seat = _parse_seat(text)

    rows = []
    for i, flight in enumerate(flights):
        rows.append({
            "date": dates[i] if i < len(dates) else (dates[0] if dates else ""),
            "flight": flight,
            "from": frm,
            "to": to,
            "seat": seat,
            "note": "",
            "aircraft": "",
        })
    if not rows and (dates or (frm and to)):
        rows.append({
            "date": dates[0] if dates else "",
            "flight": "",
            "from": frm,
            "to": to,
            "seat": seat,
            "note": "",
            "aircraft": "",
        })
    if rows:
        return rows

    import ai_assist
    if ai_assist.available():
        return ai_assist.extract_flights(text)
    return []
