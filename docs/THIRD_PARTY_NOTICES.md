# 第三方数据与组件声明

本仓库**源代码**以 [MIT License](../LICENSE) 发布。  
运行时下载到 `data/` 的开放数据**不纳入 git**，各自遵循原许可证；使用前请自行核对。

FlightLog **不爬取** Flightradar24、航旅纵横等禁止抓取的商业站点。

## 运行时数据源（落盘于 `data/`，勿提交）

| 来源 | 用途 | 许可 / 条款（摘要） |
|------|------|---------------------|
| [OurAirports](https://ourairports.com/data/) | 机场 / 跑道 / 频率 / 导航台 / 国家地区 | Public Domain（Unlicense） |
| [OpenFlights](https://openflights.org/data.html) | 航司、航线、机型、时区补丁 | Open Database / 项目条款；数据较旧 |
| [OpenSky Network](https://opensky-network.org/) | 机尾 CSV、区域 states API | 研究/非商用友好；请遵守其 API 与 ToS |
| [adsb.fi Open Data](https://github.com/adsbfi/opendata) | 枢纽周边实时机迹 | 公开 API；请限速、建议馈送回馈 |
| [adsbdb](https://adsbdb.com) | 免费航线/机尾查询 API | 服务条款以站点为准；本应用仅作客户端 |
| [FAA Releasable Aircraft](https://www.faa.gov/licenses_certificates/aircraft_certification/aircraft_registry/releasable_aircraft_download) | 美国 N 号登记 | 美国政府公开数据 |
| [AviationShop 开放集](https://github.com/AviationShop) | ICAO 机型、登记前缀、METAR/应答机释义 | CC0 1.0 |
| [IP2Location IATA-ICAO](https://github.com/ip2location/ip2location-iata-icao) | 补缺省 IATA | 以仓库 LICENSE 为准 |
| [NOAA Aviation Weather](https://aviationweather.gov/) | METAR / 机场信息（实时，默认可不落库） | 美国政府公开数据 |
| [aviowiki Open Data](https://aviowiki.com/open-data/)（可选，未默认导入） | 机场 JSON | CC BY 4.0（需署名） |

## 捆绑进镜像/仓库的前端资源

| 组件 | 用途 | 许可 |
|------|------|------|
| [Leaflet](https://leafletjs.com/) | 地图 | BSD-2-Clause |
| 自托管字体（见 `web/fonts/`） | UI 字体 | 以各字体文件附带许可为准 |
| Esri World 底图瓦片 | 地图底图（运行时请求） | 须遵守 Esri 服务条款 |

`server/airports_iata.json` 为 OurAirports 派生的小型 IATA 快照（Public Domain），供无 `catalog.db` 时冷启动；完整地理层以 `sync_catalog.py` 为准。

## 可选商业/密钥服务

| 服务 | 说明 |
|------|------|
| AviationStack | 可选；密钥仅存本地 `data/api_keys.json`，勿提交 |
| 用户自备 LLM API | 可选；同上 |

## 自动采集说明

定时任务只请求**明确开放**的 API（adsb.fi / OpenSky），带 User-Agent 与约 1 req/s 限速。  
默认「轻量模式」只扫少量枢纽、不每次拉取机型表、目录库默认手动/每周且默认关闭 FAA 大包自动下载，以控制容器 CPU/内存与流量。
