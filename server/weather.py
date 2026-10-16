"""NOAA Aviation Weather Center 公开 API（机场信息 / METAR）。"""

from __future__ import annotations

import httpx

BASE = "https://aviationweather.gov/api/data"


def _get(path: str, params: dict, timeout: float = 12.0) -> object | None:
    url = f"{BASE}/{path}"
    with httpx.Client(timeout=timeout, follow_redirects=True) as client:
        r = client.get(
            url,
            params=params,
            headers={"User-Agent": "FlightLogWeather/1.0", "Accept": "application/json"},
        )
        if r.status_code != 200:
            return None
        if not r.content:
            return None
        return r.json()


def airport_wx(ids: str) -> dict | None:
    """按 ICAO/IATA 取 NOAA 机场静态信息。"""
    code = (ids or "").strip().upper()
    if not code:
        return None
    data = _get("airport", {"ids": code, "format": "json"})
    if isinstance(data, list) and data:
        return data[0] if isinstance(data[0], dict) else None
    if isinstance(data, dict):
        return data
    return None


def metar(ids: str) -> list[dict]:
    """最近 METAR；超时或失败返回空列表。"""
    code = (ids or "").strip().upper()
    if not code:
        return []
    data = _get("metar", {"ids": code, "format": "json", "hours": 2}, timeout=8.0)
    if isinstance(data, list):
        return [x for x in data if isinstance(x, dict)]
    if isinstance(data, dict):
        return [data]
    return []
