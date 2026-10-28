"""由座位号 + 机型（+ 舱位）推断靠窗 / 过道 / 中间。

布局按民航常见字母配置（跳过 I）；未知机型回落到窄体 3-3 经验规则。
显式 seat_type 仍优先，本模块只负责推断。
"""
from __future__ import annotations

import re

# letter -> window | aisle | middle
Layout = dict[str, str]

# 窄体经济舱 3-3：A B C | D E F
Y_3_3: Layout = {
    "A": "window", "B": "middle", "C": "aisle",
    "D": "aisle", "E": "middle", "F": "window",
}

# 窄体/支线 2-2：A C | D F（常见商务/支线）
Y_2_2: Layout = {
    "A": "window", "C": "aisle",
    "D": "aisle", "F": "window",
}

# 宽体 2-4-2（多见于 787 / 部分 330 经济舱）：A C | D E F G | H K
Y_2_4_2: Layout = {
    "A": "window", "C": "aisle",
    "D": "aisle", "E": "middle", "F": "middle", "G": "aisle",
    "H": "aisle", "K": "window",
}

# 宽体 2-3-2（老 330 等）：A C | D E F | G K
Y_2_3_2: Layout = {
    "A": "window", "C": "aisle",
    "D": "aisle", "E": "middle", "F": "aisle",
    "G": "aisle", "K": "window",
}

# 宽体 3-3-3（777/350 常见经济舱）：A B C | D E F | G H J
Y_3_3_3: Layout = {
    "A": "window", "B": "middle", "C": "aisle",
    "D": "aisle", "E": "middle", "F": "aisle",
    "G": "aisle", "H": "middle", "J": "window",
}

# 宽体 3-4-3（部分 777）：A B C | D E F G | H J K
Y_3_4_3: Layout = {
    "A": "window", "B": "middle", "C": "aisle",
    "D": "aisle", "E": "middle", "F": "middle", "G": "aisle",
    "H": "aisle", "J": "middle", "K": "window",
}

# 商务 1-2-1 / 2-2-2 粗分：两侧靠窗，中间对为过道侧
J_1_2_1: Layout = {
    "A": "window", "K": "window",
    "D": "aisle", "F": "aisle", "E": "aisle", "G": "aisle",
    "C": "aisle", "H": "aisle",
}
J_2_2: Layout = {
    "A": "window", "C": "aisle",
    "D": "aisle", "F": "window",
    "H": "window", "K": "window",
}

# 机型族 → 经济舱默认布局
_ECONOMY_BY_FAMILY: dict[str, Layout] = {
    "narrowbody": Y_3_3,
    "regional_22": Y_2_2,
    "wide_242": Y_2_4_2,
    "wide_232": Y_2_3_2,
    "wide_333": Y_3_3_3,
    "wide_343": Y_3_4_3,
}

# 规范化后的机型 token → 族
_TYPE_FAMILY: dict[str, str] = {}


def _add_types(family: str, *tokens: str) -> None:
    for t in tokens:
        _TYPE_FAMILY[t.upper()] = family


_add_types(
    "narrowbody",
    # Airbus A32x
    "A318", "A319", "A320", "A321", "A20N", "A21N", "A19N",
    "318", "319", "320", "321", "32A", "32B", "32N", "32Q",
    # Boeing 737
    "B731", "B732", "B733", "B734", "B735", "B736", "B737", "B738", "B739",
    "B37M", "B38M", "B39M", "7M8", "7M9",
    "731", "732", "733", "734", "735", "736", "737", "738", "739", "73G", "73H", "73J", "73W",
    "73C", "73E", "73L", "73N", "73P", "73Q", "73R",
)

_add_types(
    "wide_242",
    "B788", "B789", "B78X", "788", "789", "78X", "78J",
    "A359", "A35K", "359", "351",  # A350 多数航司经济舱近 3-3-3，下面再覆盖
)

# A350 / 部分 777 更常见 3-3-3
_add_types(
    "wide_333",
    "A359", "A35K", "A350", "359", "351", "35K",
    "B772", "B77W", "B77L", "B778", "B779",
    "772", "77W", "77L", "778", "779", "777",
    "A388", "A380", "380", "388",
)

_add_types(
    "wide_343",
    "B773", "773",  # 部分 777-300 经济舱 3-4-3
)

_add_types(
    "wide_232",
    "A332", "A333", "A338", "A339", "A330",
    "332", "333", "338", "339", "330",
    "B762", "B763", "B764", "762", "763", "764", "767",
)

# 787 默认 2-4-2（覆盖上面误入 333 的 token）
_add_types("wide_242", "B788", "B789", "B78X", "788", "789", "78X", "78J", "787")

_add_types(
    "regional_22",
    "E170", "E175", "E190", "E195", "E75L", "E75S", "E90", "E95",
    "CRJ1", "CRJ2", "CRJ7", "CRJ9", "CRJX",
    "AT72", "AT75", "AT76", "ATR",
)


def normalize_aircraft_token(aircraft: str) -> str:
    """从自由文本机型里抽出可比对的代号。"""
    s = (aircraft or "").strip().upper()
    if not s:
        return ""
    s = s.replace("_", " ").replace("-", " ")
    # 直接命中短码
    compact = re.sub(r"[^A-Z0-9]", "", s)
    if compact in _TYPE_FAMILY:
        return compact
    # Boeing 737-800 / Airbus A320-200
    m = re.search(r"\b(A\d{2}(?:\d|[A-Z]){0,2}|B\d{2}(?:\d|[A-Z]){0,2})\b", s)
    if m:
        return m.group(1)
    m = re.search(r"\b(7\d{2}|3\d{2}|A3\d{2}|B7\d{2})\b", s)
    if m:
        return m.group(1)
    # 737800 / A320200
    m = re.search(r"(737|320|321|330|350|380|787|777|767|757)[-\s]?(\d{0,3})", s)
    if m:
        base, suf = m.group(1), m.group(2)
        mapping = {
            ("737", "800"): "B738",
            ("737", "700"): "B737",
            ("737", "900"): "B739",
            ("737", "8"): "B38M",
            ("737", "9"): "B39M",
            ("320", ""): "A320",
            ("320", "200"): "A320",
            ("321", ""): "A321",
            ("321", "200"): "A321",
            ("330", "200"): "A332",
            ("330", "300"): "A333",
            ("330", ""): "A333",
            ("350", "900"): "A359",
            ("350", ""): "A359",
            ("380", ""): "A388",
            ("787", "8"): "B788",
            ("787", "9"): "B789",
            ("787", "10"): "B78X",
            ("787", ""): "B789",
            ("777", "200"): "B772",
            ("777", "300"): "B77W",
            ("777", ""): "B77W",
            ("767", ""): "B763",
            ("757", ""): "B752",
        }
        hit = mapping.get((base, suf)) or mapping.get((base, ""))
        if hit:
            return hit
    return compact[:6]


def family_for_aircraft(aircraft: str) -> str:
    token = normalize_aircraft_token(aircraft)
    if not token:
        return "narrowbody"
    if token in _TYPE_FAMILY:
        return _TYPE_FAMILY[token]
    # 前缀模糊
    for key, fam in _TYPE_FAMILY.items():
        if token.startswith(key) or key.startswith(token):
            return fam
    if token.startswith(("A32", "B73", "7M", "32")):
        return "narrowbody"
    if token.startswith(("B78", "78")):
        return "wide_242"
    if token.startswith(("A33", "B76", "33", "76")):
        return "wide_232"
    if token.startswith(("A35", "B77", "A38", "35", "77", "38")):
        return "wide_333"
    return "narrowbody"


def layout_for(aircraft: str = "", cabin_class: str = "") -> Layout:
    cabin = (cabin_class or "").strip().lower()
    fam = family_for_aircraft(aircraft)
    if cabin in ("business", "first", "j", "f", "c"):
        if fam.startswith("wide"):
            return J_1_2_1
        return J_2_2
    return _ECONOMY_BY_FAMILY.get(fam, Y_3_3)


def seat_letter(seat: str) -> str:
    s = (seat or "").strip().upper()
    return next((c for c in reversed(s) if c.isalpha()), "")


def infer_seat_type(seat: str, aircraft: str = "", cabin_class: str = "") -> str:
    """返回 window / aisle / middle；无法判断则空串。"""
    letter = seat_letter(seat)
    if not letter:
        return ""
    layout = layout_for(aircraft, cabin_class)
    if letter in layout:
        return layout[letter]
    # 未知字母：保留旧启发式（部分航司扩展字母）
    if letter in "AFHK":
        return "window"
    if letter in "CDGJ":
        return "aisle"
    if letter in "BE":
        return "middle"
    if letter in "L":  # 偶见左侧靠窗标记
        return "window"
    return ""


def explain_inference(seat: str, aircraft: str = "", cabin_class: str = "") -> dict:
    """给 API / UI 用的解释信息。"""
    token = normalize_aircraft_token(aircraft)
    fam = family_for_aircraft(aircraft)
    letter = seat_letter(seat)
    st = infer_seat_type(seat, aircraft, cabin_class)
    return {
        "seat": (seat or "").strip().upper(),
        "letter": letter,
        "aircraft_token": token,
        "family": fam,
        "cabin_class": (cabin_class or "").strip().lower(),
        "seat_type": st,
        "layout": layout_for(aircraft, cabin_class),
    }
