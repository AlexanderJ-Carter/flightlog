"""flightlog 本地 Web 服务后端 —— FastAPI 入口。

启动方式：
    本地开发: python3 -m uvicorn app:app --port 8321
    Docker:   docker compose up -d  （见 docker-compose.yml）
"""
import os
import re as _re
import threading
from contextlib import asynccontextmanager

import airports as airports_mod
import auth_oidc
import catalog_db
import config_store
import db
import extract as extractor
import fleet_db
import lookup as lookup_proxy
import scheduler
from fastapi import FastAPI, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field

db.init_db()
fleet_db.init()
catalog_db.init()


def _catalog_stats() -> dict:
    return catalog_db.stats()


@asynccontextmanager
async def lifespan(_app: FastAPI):
    scheduler.start()
    yield
    scheduler.stop()


app = FastAPI(title="flightlog", version="2.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def oidc_gate(request, call_next):
    blocked = auth_oidc.require(request)
    if blocked is not None:
        return blocked
    return await call_next(request)


@app.get("/api/auth/login")
async def auth_login(request: Request):
    if not auth_oidc.enabled():
        return RedirectResponse("/")
    return await auth_oidc.login(request)


@app.get("/api/auth/callback")
async def auth_callback(request: Request):
    return await auth_oidc.callback(request)


@app.get("/api/auth/logout")
def auth_logout(request: Request):
    return auth_oidc.logout(request)


@app.get("/api/auth/status")
def auth_status(request: Request):
    return auth_oidc.status_payload(request)


@app.middleware("http")
async def no_cache_frontend(request, call_next):
    """本地无构建前端：避免浏览器死缓存旧 JS/CSS。"""
    response = await call_next(request)
    path = request.url.path
    if path.startswith(("/js/", "/css/", "/fonts/")) or path in ("/", "/index.html"):
        response.headers["Cache-Control"] = "no-cache"
    return response


class FlightIn(BaseModel):
    date: str
    flight: str
    from_ap: str = Field(alias="from")
    to: str
    seat: str = ""
    note: str = ""
    aircraft: str = ""
    registration: str = ""
    cabin_class: str = ""
    seat_type: str = ""
    flight_reason: str = ""
    duration_min: int | None = None
    airline_name: str = ""
    dep_time: str = ""
    arr_time: str = ""
    dep_terminal: str = ""
    arr_terminal: str = ""
    dep_gate: str = ""
    arr_gate: str = ""
    trip_id: str = ""
    distance_km: float | None = None
    model_config = ConfigDict(populate_by_name=True)


class FlightPatch(BaseModel):
    """部分更新：只传要改的字段，未传的不动。"""
    date: str | None = None
    flight: str | None = None
    from_ap: str | None = Field(None, alias="from")
    to: str | None = None
    seat: str | None = None
    note: str | None = None
    aircraft: str | None = None
    registration: str | None = None
    cabin_class: str | None = None
    seat_type: str | None = None
    flight_reason: str | None = None
    duration_min: int | None = None
    airline_name: str | None = None
    dep_time: str | None = None
    arr_time: str | None = None
    dep_terminal: str | None = None
    arr_terminal: str | None = None
    dep_gate: str | None = None
    arr_gate: str | None = None
    trip_id: str | None = None
    distance_km: float | None = None
    model_config = ConfigDict(populate_by_name=True)


class LookupIn(BaseModel):
    flight: str
    date: str


class ImportIn(BaseModel):
    flights: list[dict] = []
    rows: list[dict] = []
    replace: bool = False


class ExtractIn(BaseModel):
    text: str


class KeysIn(BaseModel):
    aviationstack: str | None = None
    variflight: str | None = None
    llm: str | None = None
    llm_base: str | None = None
    llm_model: str | None = None


class FleetSettingsIn(BaseModel):
    auto: bool | None = None
    interval_hours: float | None = None


class TrackIn(BaseModel):
    points: list = []
    source_format: str = "json"
    source_name: str = ""


_DATE_RE = _re.compile(r"^\d{4}-\d{2}-\d{2}$")


def _check_date(date_str):
    """日期格式校验：YYYY-MM-DD。"""
    if not _DATE_RE.match(date_str or ""):
        raise HTTPException(400, f"日期格式应为 YYYY-MM-DD，收到：{date_str!r}")
    return date_str


@app.get("/api/flights")
def get_flights(
    year: str | None = Query(None, pattern=r"^\d{4}$"),
    airline: str | None = Query(None, max_length=4),
    airport: str | None = Query(None, max_length=3),
    q: str | None = Query(None, max_length=64),
    limit: int | None = Query(None, ge=1, le=10000),
    offset: int = Query(0, ge=0),
):
    return {"flights": db.list_flights(year=year, airline=airline,
                                       airport=airport, q=q,
                                       limit=limit, offset=offset)}


@app.post("/api/flights", status_code=201)
def post_flight(body: FlightIn):
    _check_date(body.date)
    date = body.date.strip()
    flight = body.flight.strip().upper()
    from_ap = body.from_ap.strip().upper()
    to_ap = body.to.strip().upper()
    dup = db.find_duplicate(date, flight, from_ap, to_ap)
    if dup is not None:
        raise HTTPException(
            409,
            detail={"message": "已存在相同航班记录", "id": dup},
        )
    import catalog_db
    catalog_db.ensure_custom_airport(from_ap)
    catalog_db.ensure_custom_airport(to_ap)
    fid = db.add_flight(
        date=date, flight=flight, from_ap=from_ap, to_ap=to_ap,
        seat=(body.seat or "").strip(),
        note=(body.note or "").strip(),
        aircraft=(body.aircraft or "").strip(),
        registration=(body.registration or "").strip().upper(),
        cabin_class=(body.cabin_class or "").strip(),
        seat_type=(body.seat_type or "").strip(),
        flight_reason=(body.flight_reason or "").strip(),
        duration_min=body.duration_min,
        airline_name=(body.airline_name or "").strip(),
        dep_time=(body.dep_time or "").strip(),
        arr_time=(body.arr_time or "").strip(),
        dep_terminal=(body.dep_terminal or "").strip(),
        arr_terminal=(body.arr_terminal or "").strip(),
        dep_gate=(body.dep_gate or "").strip(),
        arr_gate=(body.arr_gate or "").strip(),
        trip_id=(body.trip_id or "").strip(),
        distance_km=body.distance_km,
    )
    return {"ok": True, "id": fid}


@app.put("/api/flights/{fid}")
def put_flight(fid: int, body: FlightPatch):
    """编辑记录：只改传入的字段。"""
    fields = body.model_dump(exclude_unset=True, by_alias=False)
    if "to" in fields:
        fields["to_ap"] = fields.pop("to")
    if not fields:
        raise HTTPException(400, "没有要更新的字段")
    if "date" in fields and fields["date"] is not None:
        _check_date(fields["date"].strip())
        fields["date"] = fields["date"].strip()
    if "flight" in fields and fields["flight"] is not None:
        fields["flight"] = fields["flight"].strip().upper()
    if "registration" in fields and fields["registration"] is not None:
        fields["registration"] = fields["registration"].strip().upper()
    for k in ("from_ap", "to_ap"):
        if fields.get(k):
            fields[k] = fields[k].strip().upper()

    existing = db.get_flight(fid)
    if not existing:
        raise HTTPException(404, f"航班 id={fid} 不存在")
    check_date = fields.get("date", existing["date"])
    check_flight = fields.get("flight", existing["flight"])
    check_from = fields.get("from_ap", existing["from"])
    check_to = fields.get("to_ap", existing["to"])
    dup = db.find_duplicate(check_date, check_flight, check_from, check_to,
                            exclude_id=fid)
    if dup is not None:
        raise HTTPException(
            409,
            detail={"message": "已存在相同航班记录", "id": dup},
        )
    if not db.update_flight(fid, **fields):
        raise HTTPException(404, f"航班 id={fid} 不存在")
    return {"ok": True, "id": fid}


@app.delete("/api/flights/{fid}")
def delete_flight(fid: int):
    db.delete_flight(fid)
    return {"ok": True}


@app.get("/api/stats")
def get_stats():
    s = db.stats()
    s.update(db.aircraft_stats())
    return s


@app.get("/api/map")
def get_map():
    return db.map_data()


@app.get("/api/airports")
def get_airports(
    q: str = Query("", max_length=32),
    limit: int = Query(20, ge=1, le=500),
):
    """机场搜索（三字码 / 中文名），供录入自动完成。"""
    return {"airports": airports_mod.search(q, limit)}


@app.get("/api/airports/{code}")
def get_airport_detail(code: str):
    """机场详情：catalog.db 地理层（主档/跑道/频率/导航台）。"""
    detail = catalog_db.airport_detail(code)
    if not detail:
        raise HTTPException(404, "机场未找到")
    return detail


@app.get("/api/catalog")
def get_catalog():
    """参考库分层统计与数据源。"""
    return catalog_db.stats()


@app.get("/api/weather/{code}")
def get_weather(code: str):
    """NOAA 机场信息 + METAR（公开 API，失败则字段为空）。"""
    import weather as wx

    icao = code.strip().upper()
    detail = catalog_db.airport_detail(icao)
    if detail and detail.get("airport", {}).get("icao"):
        icao = detail["airport"]["icao"]
    return {
        "code": code.strip().upper(),
        "icao": icao,
        "airport": wx.airport_wx(icao),
        "metar": wx.metar(icao),
    }


@app.post("/api/lookup")
def post_lookup(body: LookupIn):
    return lookup_proxy.lookup_flight(body.flight, body.date)


@app.post("/api/extract")
def post_extract(body: ExtractIn):
    return {"rows": extractor.extract(body.text)}


@app.get("/api/config")
def get_config():
    """智能能力配置状态（不含密钥明文）。"""
    return config_store.status()


@app.put("/api/config/keys")
def put_keys(body: KeysIn):
    """写入/更新密钥；传空字符串可清除对应项。"""
    patch = body.model_dump(exclude_unset=True)
    return {"ok": True, **config_store.save_keys(patch)}


@app.get("/api/health")
def health():
    """健康检查：供 Docker / 前端探活。"""
    cfg = config_store.status()
    fleet = fleet_db.stats()
    sch = scheduler.status()
    return {
        "ok": True,
        "version": "2.0",
        "providers": cfg["providers"],
        "live_lookup": cfg["live_lookup"],
        "airports": airports_mod.count(),
        "fleet": fleet,
        "catalog": sch.get("catalog") or _catalog_stats(),
        "harvest": {
            "auto": sch["auto"],
            "interval_hours": sch["interval_hours"],
            "last_harvest_at": sch["last_harvest_at"],
            "busy": sch["busy"],
        },
    }


@app.get("/api/fleet")
def get_fleet():
    """飞友本地库状态 + 定时采集设置。"""
    return scheduler.status()


@app.put("/api/fleet/settings")
def put_fleet_settings(body: FleetSettingsIn):
    """更新自动采集开关与间隔（小时）。"""
    if body.auto is None and body.interval_hours is None:
        raise HTTPException(400, "没有要更新的设置")
    scheduler.set_settings(auto=body.auto, interval_hours=body.interval_hours)
    return {"ok": True, **scheduler.status()}


@app.post("/api/fleet/harvest")
def post_fleet_harvest():
    """立即触发一轮合法采集（后台线程，不阻塞请求太久）。"""
    st = scheduler.status()
    if st["busy"]:
        return {"ok": False, "busy": True, "message": "采集进行中"}

    def _job():
        scheduler.run_harvest_job(reason="api")

    threading.Thread(target=_job, name="fleet-harvest-api", daemon=True).start()
    return {"ok": True, "started": True, "message": "已开始采集"}


@app.post("/api/fleet/catalog")
def post_fleet_catalog():
    """立即同步开放目录（OurAirports / FAA），后台执行。"""
    st = scheduler.status()
    if st.get("catalog_busy"):
        return {"ok": False, "busy": True, "message": "目录同步进行中"}

    def _job():
        scheduler.run_catalog_job(reason="api")

    threading.Thread(target=_job, name="fleet-catalog-api", daemon=True).start()
    return {"ok": True, "started": True, "message": "已开始目录同步"}


@app.get("/api/fleet/network")
def get_fleet_network(
    airports: str = Query("", description="逗号分隔机场码，如 PEK,SHA"),
    airline: str = Query("", max_length=2),
    limit: int = Query(180, ge=1, le=2000),
):
    """参考航线网（OpenFlights），供地图浅色叠加。"""
    codes = [c.strip().upper() for c in airports.split(",") if c.strip()]
    routes = fleet_db.network_routes(
        airports=codes or None, airline=airline, limit=limit
    )
    return {"routes": routes, "count": len(routes)}


@app.get("/api/export")
def export_data(format: str = "json", year: str | None = Query(None, pattern=r"^\d{4}$")):
    """导出航班。format=json 可喂回 import；format=csv 给 Excel。year 可选筛年。"""
    flights = db.list_flights(year=year)
    suffix = f"-{year}" if year else ""
    if format == "csv":
        import csv as _csv
        import io as _io
        buf = _io.StringIO()
        w = _csv.writer(buf)
        w.writerow([
            "date", "flight", "from", "to", "seat", "seat_type", "cabin_class",
            "flight_reason", "note", "aircraft", "registration",
            "duration_min", "airline_name", "dep_time", "arr_time",
            "dep_terminal", "arr_terminal", "dep_gate", "arr_gate",
            "trip_id", "distance_km",
        ])
        for f in flights:
            w.writerow([
                f["date"], f["flight"], f["from"], f["to"],
                f["seat"], f.get("seat_type", ""), f.get("cabin_class", ""),
                f.get("flight_reason", ""), f["note"], f["aircraft"],
                f.get("registration", ""), f.get("duration_min") or "",
                f.get("airline_name", ""),
                f.get("dep_time", ""), f.get("arr_time", ""),
                f.get("dep_terminal", ""), f.get("arr_terminal", ""),
                f.get("dep_gate", ""), f.get("arr_gate", ""),
                f.get("trip_id", ""), f.get("distance_km") or "",
            ])
        return Response(
            content="\ufeff" + buf.getvalue(),
            media_type="text/csv; charset=utf-8",
            headers={
                "Content-Disposition":
                f'attachment; filename="flightlog{suffix}.csv"',
            },
        )
    import json as _json
    payload = _json.dumps({"flights": flights}, ensure_ascii=False, indent=2)
    return Response(
        content=payload,
        media_type="application/json; charset=utf-8",
        headers={
            "Content-Disposition":
            f'attachment; filename="flightlog-backup{suffix}.json"',
        },
    )


@app.post("/api/import")
def import_data(body: ImportIn):
    """恢复备份/批量导入。rows 或 flights 任选；replace=true 先清空。"""
    rows = body.rows or body.flights
    if not rows:
        raise HTTPException(400, "没有可导入的数据（需要 rows 或 flights 数组）")
    result = db.import_rows(rows, replace=body.replace)
    return {
        "ok": True,
        "added": result["added"],
        "updated": result.get("updated", 0),
        "skipped": result["skipped"],
    }


@app.post("/api/import/file")
async def import_file(
    file: UploadFile = File(...),
    source: str = Form("auto"),
    replace: bool = Form(False),
    dry_run: bool = Form(False),
):
    """多源文件导入：OpenFlights / FR24 CSV / FlightLog JSON。"""
    import importers

    raw = (await file.read()).decode("utf-8", errors="replace")
    if not raw.strip():
        raise HTTPException(400, "空文件")
    try:
        detected, rows = importers.detect_and_parse(raw, source=source)
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    if not rows:
        raise HTTPException(400, "未解析出任何航班行")
    if dry_run:
        return {
            "ok": True,
            "dry_run": True,
            "source": detected,
            "parsed": len(rows),
            "preview": rows[:20],
        }
    result = db.import_rows(rows, replace=replace)
    return {
        "ok": True,
        "source": detected,
        "parsed": len(rows),
        "added": result["added"],
        "updated": result.get("updated", 0),
        "skipped": result["skipped"],
    }


@app.get("/api/countries")
def get_countries():
    """访问国家统计（基于 catalog 机场国家）。"""
    return {"countries": db.visited_countries()}


@app.get("/api/flights/{fid}/track")
def get_track(fid: int):
    tr = db.get_flight_track(fid)
    if not tr:
        raise HTTPException(404, "无航迹")
    return tr


@app.put("/api/flights/{fid}/track")
def put_track(fid: int, body: TrackIn):
    try:
        return {"ok": True, **db.set_flight_track(
            fid,
            body.points,
            source_format=body.source_format,
            source_name=body.source_name,
        )}
    except ValueError as e:
        raise HTTPException(404, str(e)) from e


@app.delete("/api/flights/{fid}/track")
def delete_track(fid: int):
    db.delete_flight_track(fid)
    return {"ok": True}


# ------------------------------------------------------------------
# 前端托管：css/js 子目录 + index.html
# ------------------------------------------------------------------
_HERE = os.path.dirname(os.path.abspath(__file__))
WEB_DIR = os.environ.get("FLIGHTLOG_WEB_DIR", "")
if not WEB_DIR:
    for _cand in (os.path.join(_HERE, "web"),
                  os.path.join(_HERE, "..", "web")):
        if os.path.isfile(os.path.join(_cand, "index.html")):
            WEB_DIR = os.path.abspath(_cand)
            break

if os.path.isdir(WEB_DIR):
    css_dir = os.path.join(WEB_DIR, "css")
    js_dir = os.path.join(WEB_DIR, "js")
    fonts_dir = os.path.join(WEB_DIR, "fonts")
    if os.path.isdir(css_dir):
        app.mount("/css", StaticFiles(directory=css_dir), name="css")
    if os.path.isdir(js_dir):
        app.mount("/js", StaticFiles(directory=js_dir), name="js")
    if os.path.isdir(fonts_dir):
        app.mount("/fonts", StaticFiles(directory=fonts_dir), name="fonts")

    @app.get("/", include_in_schema=False)
    def index():
        return FileResponse(os.path.join(WEB_DIR, "index.html"))

    @app.get("/404.html", include_in_schema=False)
    def not_found_page():
        p = os.path.join(WEB_DIR, "404.html")
        if os.path.isfile(p):
            return FileResponse(p, status_code=404)
        raise HTTPException(404)

    @app.get("/favicon.ico", include_in_schema=False)
    def favicon():
        p = os.path.join(WEB_DIR, "favicon.ico")
        if os.path.isfile(p):
            return FileResponse(p)
        raise HTTPException(404)
