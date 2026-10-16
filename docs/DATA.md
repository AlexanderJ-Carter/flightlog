# 自建航空数据库

数据分三库，职责清晰、可独立刷新。

| 文件 | 职责 |
|------|------|
| `data/flightlog.db` | 你的航班档案（含时刻/航站楼/登机口/行程/距离） |
| `data/fleet.db` | 观测沉淀：呼号→机尾、OpenSky 机尾缓存 |
| `data/catalog.db` | **参考库**：地理 / 网络 / 登记 / 词典 |

## catalog.db 分层

表名前缀即层级：

| 前缀 | 含义 | 主要表 |
|------|------|--------|
| `geo_` | 地理 | countries, regions, airports, runways, frequencies, navaids |
| `net_` | 网络 | airlines, routes, plane_types |
| `reg_` | 登记 | faa, prefixes, icao_types |
| `lex_` | 词典 | metar, squawk |
| `meta_` | 元数据 | sources, kv |

## 数据源（合法开放）

| 源 | 写入层 | 内容 |
|----|--------|------|
| OurAirports | geo | 国家/地区/机场/跑道/频率/导航台 |
| OpenFlights airports.dat | geo | 时区补丁 |
| 内置中文名 | geo | `name_zh` |
| IP2Location IATA/ICAO | geo | 补缺省 IATA |
| OpenFlights airlines/routes/planes | net | 航司、航线、机型名录 |
| FAA ReleasableAircraft | reg | 美国 N 号（缓存 `data/cache/`） |
| AviationShop CC0 | reg/lex | 机型代号、登记前缀、METAR、应答机 |
| OpenSky CSV | fleet | hex→注册号/机型 |
| adsb.fi / OpenSky API | fleet | 合法实时观测 |

## 刷新命令

```bash
cd server
FLIGHTLOG_DATA_DIR=../data uv run python sync_catalog.py          # geo+reg+lex
FLIGHTLOG_DATA_DIR=../data uv run python sync_open_data.py        # fleet 机尾 + net 航线
FLIGHTLOG_DATA_DIR=../data uv run python harvest_live.py          # 观测沉淀
```

## Git 与许可

- `data/`、`*.db`、下载缓存 **不进 git**（见根目录 `.gitignore`）
- 代码 [MIT](../LICENSE)；数据源声明见 [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)

## 自动采集（可实现，已内置）

合法、限速的后台任务（**不是**爬商业站）：

| 任务 | 默认 | 说明 |
|------|------|------|
| 轻量 ADS-B 采集 | 开 | adsb.fi 少量枢纽 + OpenSky 中国框，约每 12h |
| 目录全量同步 | 关 | OurAirports 等；手动 `sync_catalog.py` 或 `POST /api/fleet/catalog` |
| FAA 大包 | 默认同步时跳过 | `FLIGHTLOG_CATALOG_SKIP_FAA=0` 才下 |

完整采集：`FLIGHTLOG_HARVEST_LIGHT=0`。关闭采集：`FLIGHTLOG_HARVEST_AUTO=0`。

## 低资源容器

`docker-compose.yml` 默认约 `256MB` 内存、`0.5` CPU；单 uvicorn worker。  
闲时几乎只占 SQLite + 少量线程；采集窗口会短时升高网络与 CPU。

## API

- `GET /api/catalog` — 分层行数与来源
- `GET /api/airports/{code}` — 机场详情（主档+跑道+频率+导航台）
- `GET /api/weather/{code}` — NOAA 实时（不落库）
- `GET /api/fleet` — 观测库 + 调度状态
- `POST /api/fleet/harvest` — 立即轻量采集
- `POST /api/fleet/catalog` — 立即刷新参考库（默认跳过 FAA）
