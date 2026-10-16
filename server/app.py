"""flightlog 本地 Web 服务后端 —— FastAPI 入口。

启动方式：
    本地开发: python3 -m uvicorn app:app --port 8321
    Docker:   docker compose up -d  （见 docker-compose.yml）

API 契约（前端按此对接）：
    GET    /api/flights           全部记录（新→旧）
    POST   /api/flights           新增记录
    DELETE /api/flights/{id}      删除记录
    GET    /api/stats             统计
    GET    /api/map               地图数据（机场 + 航线弧线）
    POST   /api/lookup            航班号查询代理
    POST   /api/extract           行程短信结构化提取
"""
import db
import extract as extractor
import lookup as lookup_proxy
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response
from pydantic import BaseModel, ConfigDict, Field
import re as _re

db.init_db()

app = FastAPI(title="flightlog", version="1.0")
# 前端是独立的静态页面（file:// 或另一端口），放开跨域
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# ------------------------------------------------------------------
# 请求体
# ------------------------------------------------------------------
class FlightIn(BaseModel):
    date: str
    flight: str
    from_ap: str = Field(alias="from")
    to: str
    seat: str = ""
    note: str = ""
    aircraft: str = ""
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
    model_config = ConfigDict(populate_by_name=True)


class LookupIn(BaseModel):
    flight: str
    date: str


class ImportIn(BaseModel):
    flights: list[dict] = []
    rows: list[dict] = []       # 兼容两种键名
    replace: bool = False


_DATE_RE = _re.compile(r"^\d{4}-\d{2}-\d{2}$")


def _check_date(date_str):
    """日期格式校验：YYYY-MM-DD（400 而不是 500，方便前端提示）。"""
    if not _DATE_RE.match(date_str or ""):
        raise HTTPException(400, f"日期格式应为 YYYY-MM-DD，收到：{date_str!r}")
    return date_str


class ExtractIn(BaseModel):
    text: str


# ------------------------------------------------------------------
# API
# ------------------------------------------------------------------
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


@app.post("/api/flights")
def post_flight(body: FlightIn):
    _check_date(body.date)
    fid = db.add_flight(
        date=body.date.strip(),
        flight=body.flight.strip().upper(),
        from_ap=body.from_ap.strip().upper(),
        to_ap=body.to.strip().upper(),
        seat=(body.seat or "").strip(),
        note=(body.note or "").strip(),
        aircraft=(body.aircraft or "").strip(),
    )
    return {"ok": True, "id": fid}


@app.put("/api/flights/{fid}")
def put_flight(fid: int, body: FlightPatch):
    """编辑记录：只改传入的字段。"""
    fields = body.model_dump(exclude_unset=True, by_alias=False)
    # to -> to_ap 映射（db 层字段名）
    if "to" in fields:
        fields["to_ap"] = fields.pop("to")
    if not fields:
        raise HTTPException(400, "没有要更新的字段")
    if "date" in fields and fields["date"] is not None:
        _check_date(fields["date"].strip())
    if "flight" in fields and fields["flight"] is not None:
        fields["flight"] = fields["flight"].strip().upper()
    for k in ("from_ap", "to_ap"):
        if fields.get(k):
            fields[k] = fields[k].strip().upper()
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


@app.post("/api/lookup")
def post_lookup(body: LookupIn):
    return lookup_proxy.lookup_flight(body.flight, body.date)


@app.post("/api/extract")
def post_extract(body: ExtractIn):
    rows = extractor.extract(body.text)
    if not rows:  # 正则版识别不到 → AI 兜底接口（当前未接入，返回空）
        rows = extractor.extract_ai(body.text)
    return {"rows": rows}


# ------------------------------------------------------------------
# 数据备份：导出 / 导入（档案是个人资产，必须能带走、能恢复）
# ------------------------------------------------------------------
@app.get("/api/export")
def export_data(format: str = "json", year: str | None = Query(None, pattern=r"^\d{4}$")):
    """导出全部（或某年）航班。format=json 完整备份；format=csv 给 Excel 用。"""
    flights = db.list_flights(year=year)
    if format == "csv":
        import csv as _csv
        import io as _io
        buf = _io.StringIO()
        w = _csv.writer(buf)
        w.writerow(["date", "flight", "from", "to", "seat", "note", "aircraft"])
        for f in flights:
            w.writerow([f["date"], f["flight"], f["from"], f["to"],
                        f["seat"], f["note"], f["aircraft"]])
        fname = f"flightlog{'-' + year if year else ''}.csv"
        return Response(
            content="﻿" + buf.getvalue(),  # BOM：Excel 打开中文不乱码
            media_type="text/csv; charset=utf-8",
            headers={"Content-Disposition": f'attachment; filename="{fname}"'},
        )
    # json：完整备份（忽略 year 筛选），可直接喂回 /api/import 恢复
    import json as _json
    full = db.list_flights()
    payload = _json.dumps({"flights": full}, ensure_ascii=False, indent=2)
    fname = f"flightlog-backup{'-' + year if year else ''}.json"
    return Response(
        content=payload,
        media_type="application/json; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{fname}"'},
    )


@app.post("/api/import")
def import_data(body: ImportIn):
    """恢复备份/批量导入。rows 或 flights 数组任选其一；replace=true 先清空。"""
    rows = body.rows or body.flights
    if not rows:
        raise HTTPException(400, "没有可导入的数据（需要 rows 或 flights 数组）")
    result = db.import_rows(rows, replace=body.replace)
    return {"ok": True, "added": result["added"], "skipped": result["skipped"]}

# ------------------------------------------------------------------
# 前端托管：docker compose up 后浏览器直接访问 http://localhost:8321
# ------------------------------------------------------------------
import os
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

_HERE = os.path.dirname(os.path.abspath(__file__))
WEB_DIR = os.environ.get("FLIGHTLOG_WEB_DIR", "")
if not WEB_DIR:
    for _cand in (os.path.join(_HERE, "web"),          # Docker 镜像内 /app/web
                  os.path.join(_HERE, "..", "web")):   # 本地开发 server/../web
        if os.path.isfile(os.path.join(_cand, "index.html")):
            WEB_DIR = _cand
            break

if os.path.isdir(WEB_DIR):
    app.mount("/assets", StaticFiles(directory=WEB_DIR), name="assets")

    @app.get("/", include_in_schema=False)
    def index():
        return FileResponse(os.path.join(WEB_DIR, "index.html"))

    @app.get("/favicon.ico", include_in_schema=False)
    def favicon():
        p = os.path.join(WEB_DIR, "favicon.ico")
        return FileResponse(p) if os.path.isfile(p) else FileResponse(
            os.path.join(WEB_DIR, "index.html"))
