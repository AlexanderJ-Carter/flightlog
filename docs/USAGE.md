# FlightLog 使用手册

## 30 秒上手

```bash
docker compose up -d --build
# 打开 http://localhost:8321
```

数据库自动创建，无任何必填配置。镜像为多阶段构建、非 root 运行；数据卷 `./data`。

## 三个表面

| 表面 | 用途 |
|------|------|
| **档案** | 紧凑统计 + 航线地图；可展开年度/航司/机型图表 |
| **明细** | 搜索筛选、编辑删除、多源导入、CSV/JSON 导出 |
| **录入** | 手动 / 航班号查询 / 短信导入 / **智能配置** |

顶栏可切换深浅色主题（跟随系统）。数据源 pill 显示「免费航线库」或「实时+航线」。「API」仅在改后端地址时展开。

地图底图为 Esri Canvas（无需 key）；Leaflet 与字体随应用本地提供，离线也能打开界面（航线库查询仍需外网）。

## 录入方式

### 1. 手动录入

填日期 / 航班号 / 三字码即可；可选时刻、航站楼、登机口、行程、舱位等。机场支持字典提示；未知三字码会写入 `catalog` 自定义机场（无坐标则里程/地图仍为空）。

### 2. 航班号查询

输入航班号 + 日期 → 补全航线信息 → 一键存入。

| 数据源 | 要 key 吗 | 能拿到什么 |
|--------|-----------|------------|
| **adsbdb（默认）** | 否 | 典型航线（起降机场、航司） |
| **OurAirports** | 否 | 全球 IATA 机场名/坐标（内置快照） |
| **adsb.fi + adsbdb 机尾** | 否 | 飞机**正在空中**时：机型、注册号、可选照片 |
| **AviationStack**（可选） | 是，有免费档 | 当日时刻 + 机型 |
| **LLM**（可选） | 是 | 纯数字消歧 / 短信 AI 解析（标注 AI，需确认） |

- 零配置即可查：`CA1902` 或纯数字 `1902`（只返回航线库里真实存在的呼号）
- 机型/注册号：航班在飞时自动补全；也可在手动录入里自己填
- 可选配置在 **录入 → 智能配置**

### 3. 短信导入

粘贴订票短信或行程邮件，解析后可**行内修改**再批量入库。支持多段行程。

录入成功后 toast 提供「在地图上查看」，跳回档案表面。

## 明细与备份

- **搜索 / 年份 / 航司码 / 机场**：走后端筛选
- **CSV / JSON**：导出表格或备份；当前年份筛选会带入导出
- **导入**：FlightLog JSON、OpenFlights / MyFR24 / Flighty CSV、TripIt ICS；重复航班自动补全空字段；对话框选「追加」或「覆盖」
- **时刻 / 航站楼 / 登机口 / 行程**：手动录入页可填；导入源有则写入
- **删除**：需二次确认
- **编辑**：跳到录入表面手动 Tab

相同「日期 + 航班号 + 航线」再次入库会被拒绝（防重复）。

## 数据自主

- 航班：`./data/flightlog.db`
- 航线缓存：`./data/route_cache.db`
- 观测库：`./data/fleet.db`（呼号沉淀 + OpenSky 机尾）
- 参考库：`./data/catalog.db`（机场/航线/FAA 等，分层见 [DATA.md](DATA.md)）
- 备份：复制 `data/` 或导出 JSON
- 迁移：拷整个目录 + `docker compose up -d`
- 清空：`docker compose down` 后删 `data/`

### 自己造飞友库（免费开放数据）

**不做**商业站爬虫（FR24 / 航旅纵横等）。合法来源：

1. **自动沉淀**：查询/录入带机型或注册号 → 写入 `fleet.db`
2. **一键导入开源数据**：

```bash
mkdir -p data
cd server
# OpenFlights 航司+航线（几 MB，快）+ OpenSky 机尾（~100MB，较慢）
FLIGHTLOG_DATA_DIR=../data uv run python sync_open_data.py
# 只要航司航线：
FLIGHTLOG_DATA_DIR=../data uv run python sync_open_data.py --skip-aircraft
```

| 来源 | 内容 |
|------|------|
| OpenSky CSV | hex → 注册号 / 机型 / 航司 |
| OpenFlights | 航司名、航线「常用机型」、机型名录 |
| OurAirports | 机场 / 跑道 / 频率 / 导航台（目录库） |
| FAA ReleasableAircraft | 美国 N 号登记（缓存于 `data/cache/`） |
| AviationShop（CC0） | ICAO 机型代号、登记前缀、航司码、METAR 缩写、应答机代码 |
| NOAA Aviation Weather | 机场信息 + METAR（实时 API，不落库） |
| 使用过程沉淀 | 呼号 → 最近见过的机尾 |
| **合法实时采集** | adsb.fi 枢纽空域 + OpenSky 区域状态 → 呼号/机尾 |

```bash
# 手动再攒一轮（也可在页面「录入 → 智能配置」点「立即采集」）
FLIGHTLOG_DATA_DIR=../data uv run python harvest_live.py

# 扩充机场目录（跑道/频率/导航台；FAA 失败会跳过）
FLIGHTLOG_DATA_DIR=../data uv run python sync_catalog.py
```

服务启动后默认**轻量自动采集**（约每 12 小时，可在智能配置里改间隔或关闭）；目录全量同步默认关（`FLIGHTLOG_CATALOG_AUTO=1` 开启）。  
档案地图可勾选「参考航线」，叠加与你去过机场相关的 OpenFlights 航线网。

环境变量（可选）：

| 变量 | 含义 |
|------|------|
| `FLIGHTLOG_PORT` | 宿主机端口（默认 8321） |
| `FLIGHTLOG_BIND` | 绑定地址（默认 `127.0.0.1`；Tailscale 上可设节点 IP） |
| `FLIGHTLOG_OIDC_ISSUER` | Pocket ID 地址，例如 `https://id.alexander.xin`；留空则不登录 |
| `FLIGHTLOG_OIDC_CLIENT_ID` / `FLIGHTLOG_OIDC_CLIENT_SECRET` | Pocket ID 客户端 |
| `FLIGHTLOG_OIDC_ALLOWED_EMAILS` | 允许登录的邮箱，逗号分隔 |
| `FLIGHTLOG_OIDC_HOSTS` | 允许发起登录的主机名 |
| `FLIGHTLOG_SESSION_SECRET` | 会话签名密钥 |
| `FLIGHTLOG_MEM_LIMIT` / `FLIGHTLOG_CPUS` | 容器上限（默认 256m / 0.5） |
| `FLIGHTLOG_HARVEST_AUTO` | `0` 关闭自动采集（默认开） |
| `FLIGHTLOG_HARVEST_LIGHT` | `0` 完整枢纽扫描（默认 `1` 轻量） |
| `FLIGHTLOG_HARVEST_INTERVAL_HOURS` | 采集间隔（默认 12） |
| `FLIGHTLOG_HARVEST_PLANES` | `1` 采集时拉 planes.dat（默认 0） |
| `FLIGHTLOG_CATALOG_AUTO` | `1` 开启定期目录同步（默认 0） |
| `FLIGHTLOG_CATALOG_SKIP_FAA` | `0` 同步时包含 FAA 大包（默认 1 跳过） |
| `FLIGHTLOG_HARVEST_START_DELAY` | 启动后首次采集延迟秒数 |
| `FLIGHTLOG_CATALOG_START_DELAY` | 启动后首次目录同步延迟秒数 |

## 常见问题

**Q: 端口被占用？**  
改 `docker-compose.yml` 里 `"8321:8321"` 左边端口。

**Q: 短信座位没识别？**  
需要「座位/Seat」等关键词或「45C座」格式；可在解析结果里改。

**Q: 国际航班 / 生僻机场？**  
先跑 `sync_catalog.py` 拉全量 OurAirports；仍未知的三字码可直接入库（自定义机场）。无坐标时不计里程、不进地图。

**Q: 想让 AI 记航班？**  
见 `docs/MCP.md`。

## 开发者

- 依赖：根目录 `pyproject.toml` + `uv.lock`（`uv sync`）
- 后端：`server/`（FastAPI + SQLite）
- 前端：`web/`（`index.html` + `css/` + `js/`，无构建）
- 本地：`uv run --directory server uvicorn app:app --port 8321 --reload`
- Docker：`Dockerfile` + `docker/entrypoint.sh` + `docker-compose.yml`
