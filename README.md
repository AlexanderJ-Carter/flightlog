# FlightLog · 我的飞行档案

本地优先的个人飞行档案：地图航迹、统计、多源导入、备份导出，以及合法的公开数据采集。代码 [MIT](LICENSE)，数据库与密钥不进 git。

在线实例：<https://flightlog.alexander.xin>

```bash
docker compose up -d --build
# 打开 http://localhost:8321
```

数据落在 `./data/`（航班库、观测库、参考库、可选密钥）——**已 gitignore，勿提交**。备份该目录即可。

容器默认偏省资源（约 ≤256MB / 0.5 CPU）：轻量自动采集开、目录全量同步关。详见 [docs/DATA.md](docs/DATA.md)。

## 产品能力

| 表面 | 做什么 |
|------|--------|
| **档案** | 航线地图为主视觉 + 紧凑统计 + 可展开图表 |
| **明细** | 筛选 / 编辑删除 / 多源导入（Flighty·FR24·OpenFlights·TripIt）/ 备份导出 |
| **录入** | 手动（时刻·航站楼·行程）· 航班号查询 · 短信解析 · 智能配置 |

### 航班号查询与自建数据（默认免费）

1. **adsbdb** — 典型起降；支持 `CA1902` / 纯数字 `1902`
2. **OurAirports** — IATA 机场 + 可同步跑道 / 频率 / 导航台
3. **adsb.fi + OpenSky** — 在飞时补机型 / 注册号；定时合法采集
4. **`data/fleet.db`** — OpenSky 机尾、OpenFlights 航线、FAA 登记、CC0 参考表
5. **NOAA** — 机场天气 / METAR（实时，不落库）
6. 可选：AviationStack / LLM（录入 → 智能配置）

不爬商业航班站。

```bash
mkdir -p data && cd server
FLIGHTLOG_DATA_DIR=../data uv run python sync_open_data.py   # 机尾 + 航线
FLIGHTLOG_DATA_DIR=../data uv run python sync_catalog.py     # 机场目录 / FAA
FLIGHTLOG_DATA_DIR=../data uv run python harvest_live.py     # 合法实时采集
```

## Docker

| 项 | 说明 |
|----|------|
| 镜像 | 多阶段构建（`uv` 锁依赖 → slim 运行时） |
| 进程 | 非 root（uid 1000）、单 worker |
| 资源 | 默认 `mem_limit=256m`、`cpus=0.5`（可用环境变量改） |
| 自动采集 | 默认开、轻量枢纽 + OpenSky 中国框，约每 12h |
| 目录同步 | 默认关（`FLIGHTLOG_CATALOG_AUTO=1` 可开） |
| 端口 | `FLIGHTLOG_PORT`（默认 8321） |
| 卷 | `./data → /app/data`（不进 git） |

常用环境变量见 [docs/USAGE.md](docs/USAGE.md)。

```bash
docker compose up -d --build
docker compose logs -f
docker compose down
```

## 开发

```bash
uv sync
uv run --directory server uvicorn app:app --port 8321 --reload
# 或：cd server && uv run uvicorn app:app --port 8321 --reload
```

前端无构建：改 `web/` 刷新即可。依赖以根目录 `pyproject.toml` / `uv.lock` 为准；`server/requirements.txt` 由 `uv export` 生成。

## 架构

```
浏览器 ──► FastAPI :8321
              ├── 静态 web/
              ├── flightlog.db（档案）+ fleet.db（观测）+ catalog.db（参考）
              ├── 多源导入 / 定时采集 / 目录同步
              └── 公开 API（adsbdb / adsb.fi / NOAA …）
```

## 文档

- [使用手册](docs/USAGE.md)
- [自建数据库](docs/DATA.md)
- [竞品对标](docs/COMPETITIVE.md)
- [第三方许可](docs/THIRD_PARTY_NOTICES.md)
- [API](docs/API.md)
- [MCP](docs/MCP.md)

## License

- 代码：[MIT](LICENSE)
- 第三方数据与组件：[docs/THIRD_PARTY_NOTICES.md](docs/THIRD_PARTY_NOTICES.md)
