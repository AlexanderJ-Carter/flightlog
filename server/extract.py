"""行程短信 → 结构化提取（正则版）。

识别：航班号、日期、城市（→三字码）、座位号；输出与 POST /api/flights
一致的行结构。末尾预留 extract_ai() 接口，后续接 LLM 时替换实现即可，
签名与 extract() 相同。
"""
import re
from datetime import date

from db import CITY_TO_AP

# ------------------------------------------------------------------
# 航班号：二字码（字母/数字组合，至少含一个字母）+ 3~4 位数字，如 MU5101 / 3U8888 / 9C8899
# ------------------------------------------------------------------
FLIGHT_RE = re.compile(
    r"(?<![0-9A-Z])((?:[0-9][A-Z]|[A-Z][0-9]|[A-Z]{2})[-\s]?(\d{3,4}))(?![0-9A-Z])",
    re.IGNORECASE,
)

# ------------------------------------------------------------------
# 日期：按优先级依次匹配
# ------------------------------------------------------------------
DATE_FULL_RE = re.compile(
    r"(20\d{2})\s*[-/年.]\s*(\d{1,2})\s*[-/月.]\s*(\d{1,2})\s*日?")
DATE_MD_RE = re.compile(r"(\d{1,2})\s*月\s*(\d{1,2})\s*日?")

# ------------------------------------------------------------------
# 座位：如 座位34A / 34A座 / Seat 12C
# ------------------------------------------------------------------
SEAT_RES = [
    re.compile(r"(?:座位|Seat|SEAT|seat)\s*[:：]?\s*(\d{1,2}[A-Z])"),
    re.compile(r"(\d{1,2}[A-Z])\s*[座排位]"),
]

# 城市 -> 三字码的路由匹配：长名优先（如"上海虹桥"先于"上海"）
_CITY_ALT = sorted(CITY_TO_AP.keys(), key=len, reverse=True)
_CITY_PAT = "|".join(_CITY_ALT)
# 连接模式：北京-上海 / 北京→上海 / 北京至上海
PAIR_RE = re.compile(rf"({_CITY_PAT})(?:市)?\s*[-–—~至到→>]\s*({_CITY_PAT})(?:市)?")
# 出发模式：从北京 / 北京出发
DEP_RES = [
    re.compile(rf"从\s*({_CITY_PAT})"),
    re.compile(rf"({_CITY_PAT})\s*(?:出发|起飞)"),
]
# 到达模式：飞往/前往/开往/抵达/到 上海
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
    # 1) 连接模式：北京-上海 / 北京至上海（一次拿两端）
    m = PAIR_RE.search(text)
    if m:
        frm = CITY_TO_AP[m.group(1)]
        to = CITY_TO_AP[m.group(2)]
        return frm, to
    # 2) 出发模式：从北京 / 北京出发
    for pat in DEP_RES:
        m = pat.search(text)
        if m:
            frm = CITY_TO_AP[m.group(1)]
            break
    # 3) 到达模式：飞往/前往/到 上海
    for pat in ARR_RES:
        m = pat.search(text)
        if m:
            to = CITY_TO_AP[m.group(1)]
            break
    return frm, to


def extract(text):
    """POST /api/extract 的实现：短信原文 → 行列表。

    每个识别到的航班号出一条行；日期/路由/座位取文中第一次出现。
    识别不到的字段为空串，交由前端引导用户补全。
    """
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
        })
    # 没识别到航班号，但日期/城市有信息 → 也给一条候选行
    if not rows and (dates or (frm and to)):
        rows.append({
            "date": dates[0] if dates else "",
            "flight": "",
            "from": frm,
            "to": to,
            "seat": seat,
            "note": "",
        })
    return rows


def extract_ai(text):
    """预留 AI 提取接口。

    接入 LLM 后把这里替换为真实实现（签名与 extract() 一致，返回同样的行
    结构），app.py 会在正则版提取为空时自动调用本函数兜底。
    """
    return []
