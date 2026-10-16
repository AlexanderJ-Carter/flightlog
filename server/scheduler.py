"""后台定时任务：合法采集公开 ADS-B，并周期性刷新开放目录库。"""
from __future__ import annotations

import threading
import time

import fleet_db

_lock = threading.Lock()
_thread: threading.Thread | None = None
_catalog_thread: threading.Thread | None = None
_stop = threading.Event()
_running_job = False
_running_catalog = False
_last_result: dict = {}
_last_catalog: dict = {}

# 目录库默认每 14 天刷新（秒）；FAA 大包另由 skip_faa 控制
_CATALOG_INTERVAL_SEC = 14 * 24 * 3600


def _interval_sec() -> float:
    fleet_db.init()
    # 默认 12 小时，降低后台负载
    hours = fleet_db.get_meta_float("harvest_interval_hours", 12.0)
    if hours <= 0:
        return 0.0
    return max(hours, 1.0) * 3600


def _auto_enabled() -> bool:
    return fleet_db.get_meta("harvest_auto", "1") != "0"


def _catalog_auto_enabled() -> bool:
    return fleet_db.get_meta("catalog_auto", "0") != "0"


def run_harvest_job(reason: str = "manual") -> dict:
    """同步执行一轮采集（可被 API / 定时器调用）。"""
    global _running_job, _last_result
    with _lock:
        if _running_job:
            return {"ok": False, "busy": True, "reason": "已有采集在进行"}
        _running_job = True
    try:
        import harvest_live

        result = harvest_live.run_once()
        result["ok"] = True
        result["reason"] = reason
        result["finished_at"] = time.time()
        _last_result = result
        fleet_db.set_meta("last_harvest_at", str(result["finished_at"]))
        fleet_db.set_meta("last_harvest_ok", "1")
        fleet_db.set_meta(
            "last_harvest_msg",
            f"sightings={result.get('after', {}).get('sightings')} "
            f"+{result.get('delta_sightings', 0)}",
        )
        return result
    except Exception as e:
        _last_result = {
            "ok": False,
            "reason": reason,
            "error": str(e),
            "finished_at": time.time(),
        }
        fleet_db.set_meta("last_harvest_at", str(_last_result["finished_at"]))
        fleet_db.set_meta("last_harvest_ok", "0")
        fleet_db.set_meta("last_harvest_msg", str(e)[:200])
        return _last_result
    finally:
        with _lock:
            _running_job = False


def run_catalog_job(reason: str = "manual", *, skip_faa: bool | None = None) -> dict:
    """同步刷新 OurAirports 等开放目录（默认跳过 FAA 大包）。"""
    global _running_catalog, _last_catalog
    with _lock:
        if _running_catalog:
            return {"ok": False, "busy": True, "reason": "目录同步进行中"}
        _running_catalog = True
    try:
        import os

        import catalog_db
        import sync_catalog

        if skip_faa is None:
            skip_faa = os.environ.get("FLIGHTLOG_CATALOG_SKIP_FAA", "1").lower() not in (
                "0", "false", "no",
            )
        counts = sync_catalog.run_all(skip_faa=skip_faa)
        cat = catalog_db.stats()
        result = {
            "ok": True,
            "reason": reason,
            "counts": counts,
            "catalog": cat,
            "finished_at": time.time(),
        }
        _last_catalog = result
        fleet_db.set_meta("last_catalog_at", str(result["finished_at"]))
        fleet_db.set_meta("last_catalog_ok", "1")
        geo = cat["counts"]["geo"]
        fleet_db.set_meta(
            "last_catalog_msg",
            f"airports={geo.get('geo_airports')} runways={geo.get('geo_runways')}",
        )
        return result
    except Exception as e:
        _last_catalog = {
            "ok": False,
            "reason": reason,
            "error": str(e),
            "finished_at": time.time(),
        }
        fleet_db.set_meta("last_catalog_at", str(_last_catalog["finished_at"]))
        fleet_db.set_meta("last_catalog_ok", "0")
        fleet_db.set_meta("last_catalog_msg", str(e)[:200])
        return _last_catalog
    finally:
        with _lock:
            _running_catalog = False


def status() -> dict:
    fleet_db.init()
    last_at = fleet_db.get_meta_float("last_harvest_at", 0.0)
    last_cat = fleet_db.get_meta_float("last_catalog_at", 0.0)
    return {
        "auto": _auto_enabled(),
        "interval_hours": fleet_db.get_meta_float("harvest_interval_hours", 6.0),
        "busy": _running_job,
        "catalog_busy": _running_catalog,
        "last_harvest_at": last_at or None,
        "last_harvest_ok": fleet_db.get_meta("last_harvest_ok", "") == "1",
        "last_harvest_msg": fleet_db.get_meta("last_harvest_msg", ""),
        "last_result": _last_result or None,
        "last_catalog_at": last_cat or None,
        "last_catalog_ok": fleet_db.get_meta("last_catalog_ok", "") == "1",
        "last_catalog_msg": fleet_db.get_meta("last_catalog_msg", ""),
        "last_catalog": _last_catalog or None,
        "catalog": _catalog_stats(),
        "fleet": fleet_db.stats(),
        "scheduler_alive": bool(_thread and _thread.is_alive()),
    }


def _catalog_stats() -> dict:
    import catalog_db
    return catalog_db.stats()


def set_settings(*, auto: bool | None = None, interval_hours: float | None = None):
    if auto is not None:
        fleet_db.set_meta("harvest_auto", "1" if auto else "0")
    if interval_hours is not None:
        fleet_db.set_meta(
            "harvest_interval_hours", str(max(0.0, float(interval_hours)))
        )


def _loop():
    # 启动后稍等再跑，避免拖慢冷启动
    import os
    delay = float(os.environ.get("FLIGHTLOG_HARVEST_START_DELAY", "45"))
    delay = fleet_db.get_meta_float("harvest_start_delay_sec", delay)
    if _stop.wait(delay):
        return
    while not _stop.is_set():
        if _auto_enabled():
            run_harvest_job(reason="schedule")
        interval = _interval_sec()
        if interval <= 0:
            # 自动关闭时仍每分钟醒一次看设置是否变回开启
            if _stop.wait(60):
                return
            continue
        if _stop.wait(interval):
            return


def _catalog_loop():
    import os

    delay = float(os.environ.get("FLIGHTLOG_CATALOG_START_DELAY", "120"))
    if _stop.wait(delay):
        return
    while not _stop.is_set():
        last = fleet_db.get_meta_float("last_catalog_at", 0.0)
        due = (time.time() - last) >= _CATALOG_INTERVAL_SEC if last else True
        if due and _catalog_auto_enabled():
            run_catalog_job(reason="schedule")
        if _stop.wait(3600):
            return


def start():
    """启动后台线程（幂等）。"""
    global _thread, _catalog_thread
    fleet_db.init()
    # 环境变量可覆盖默认间隔
    import os

    env_h = os.environ.get("FLIGHTLOG_HARVEST_INTERVAL_HOURS")
    if env_h is not None and fleet_db.get_meta("harvest_interval_hours", "") == "":
        fleet_db.set_meta("harvest_interval_hours", env_h)
    if fleet_db.get_meta("harvest_auto", "") == "":
        # 默认开启轻量自动采集
        auto = os.environ.get("FLIGHTLOG_HARVEST_AUTO", "1")
        fleet_db.set_meta("harvest_auto", "0" if auto in ("0", "false", "no") else "1")
    if fleet_db.get_meta("catalog_auto", "") == "":
        # 默认关闭目录全量同步（省资源；需要时手动或改环境变量）
        cauto = os.environ.get("FLIGHTLOG_CATALOG_AUTO", "0")
        fleet_db.set_meta(
            "catalog_auto", "0" if cauto in ("0", "false", "no") else "1"
        )
    if fleet_db.get_meta("harvest_interval_hours", "") == "":
        fleet_db.set_meta(
            "harvest_interval_hours",
            os.environ.get("FLIGHTLOG_HARVEST_INTERVAL_HOURS", "12"),
        )

    with _lock:
        if not (_thread and _thread.is_alive()):
            _stop.clear()
            _thread = threading.Thread(target=_loop, name="fleet-harvest", daemon=True)
            _thread.start()
        if not (_catalog_thread and _catalog_thread.is_alive()):
            _catalog_thread = threading.Thread(
                target=_catalog_loop, name="fleet-catalog", daemon=True
            )
            _catalog_thread.start()


def stop():
    _stop.set()
