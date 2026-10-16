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
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, ConfigDict, Field

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
    model_config = ConfigDict(populate_by_name=True)


class LookupIn(BaseModel):
    flight: str
    date: str


class ExtractIn(BaseModel):
    text: str


# ------------------------------------------------------------------
# API
# ------------------------------------------------------------------
@app.get("/api/flights")
def get_flights():
    return {"flights": db.list_flights()}


@app.post("/api/flights")
def post_flight(body: FlightIn):
    fid = db.add_flight(
        date=body.date.strip(),
        flight=body.flight.strip().upper(),
        from_ap=body.from_ap.strip().upper(),
        to_ap=body.to.strip().upper(),
        seat=(body.seat or "").strip(),
        note=(body.note or "").strip(),
    )
    return {"ok": True, "id": fid}


@app.delete("/api/flights/{fid}")
def delete_flight(fid: int):
    db.delete_flight(fid)
    return {"ok": True}


@app.get("/api/stats")
def get_stats():
    return db.stats()


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
# 前端托管：docker compose up 后浏览器直接访问 http://localhost:8321
# ------------------------------------------------------------------
import os
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

WEB_DIR = os.environ.get("FLIGHTLOG_WEB_DIR",
                         os.path.join(os.path.dirname(__file__), "web"))

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
