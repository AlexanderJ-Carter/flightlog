# 竞品对标与超越路径

面向「乘客个人飞行档案」（不是飞行员执飞日志）。借鉴成熟开源，保持我们已有优势：本地 SQLite、自建 `catalog`/`fleet`、合法 ADS-B、短信/航班号录入、低资源 Docker。

## 对标项目

| 项目 | 定位 | 数据怎么用 | 可学 | 我们已强 / 可超 |
|------|------|------------|------|----------------|
| **[AirTrail](https://github.com/johanohly/AirTrail)** | 最成熟的乘客航迹站 | OurAirports 机场；航班含舱位/座位类型/事由/时刻/航迹；多源导入（FR24/Flighty/OpenFlights…）；国家访问；统计很全 | 字段模型、统计维度、导入生态 | 我们有自建目录库+机尾库+实时采集；保持单机轻量，不做重 OAuth |
| **[perdian/flightlog](https://github.com/perdian/flightlog)** | 经典乘客档案 | OpenFlights 机场/航司；舱位/座位类型/事由；距离与时长；Docker | 航班实体字段、备份导出 | UI/中文/飞友数据我们可更强 |
| **[VECTOR](https://github.com/haoruizhou/vector-logbook)** | 飞行员日志 | OurAirports+FAA fixes；周更数据集；ForeFlight CSV | 坐标数据集刷新策略、离线包 | 乘客场景不同，学其「构建时打进镜像 + 运行时刷新」 |
| **[web-logbook](https://github.com/vsimakhin/web-logbook)** | EASA 飞行员日志 | mwgg Airports JSON / OurAirports；自定义机场 | 多机场源切换、自定义机场 | 乘客档案不跟执照体系 |
| **[OpenFlights](https://openflights.org)** | 老牌社区 | airports/airlines/routes.dat | 航线机型提示 | 数据已进 `catalog.net_*` |
| **[adsbdb](https://github.com/mrjackwills/adsbdb)** | 航线/机尾 API | 自建 PG | API 形状 | 我们本地化沉淀，不依赖其可用性 |

## AirTrail / perdian 航班字段（精华借鉴）

- 舱位 `cabin_class`：economy / economy+ / business / first  
- 座位类型 `seat_type`：window / aisle / middle（可由座位号推断）  
- 出行事由 `flight_reason`：leisure / business / other  
- 时长 `duration_min`（分钟；可后补估算）  
- 航司名（可由航班号前缀 + `catalog.net_airlines` 解析）  
- 统计：大洲、舱位分布、座位分布、事由、按月/按星期  

## 我们刻意不照搬的

- 多用户 / 完整 OAuth / 权限矩阵（个人档案场景过重）  
- Flightradar24 抓取式 lookup（ToS；我们走公开 API）  
- 飞行员执照/夜航/PIC 货币性（那是 VECTOR / web-logbook 赛道）  

## 超越抓手

1. **数据纵深**：`catalog.db` 分层地理 + FAA + 航线网 + `fleet` 观测（竞品多半只有机场表）  
2. **录入体验**：航班号查询 / 短信 / 机尾自动补全  
3. **运维**：低资源 Docker、数据不进 git、合法限速自动采集  
4. **产品完整度**：对齐 AirTrail 级统计与字段，同时保持中文与飞友语境  

本仓库字段扩展见 `server/db.py` 与 `GET /api/stats`。

## 已落地（相对 AirTrail）

- 舱位 / 座位类型 / 事由 + 统计图
- 时刻 / 航站楼 / 登机口 / 行程 / 距离落库
- 多源导入：OpenFlights / FR24 / Flighty CSV、TripIt ICS、自有 JSON；重复补全
- 未知机场写入 `geo_airports.custom`
- 访问国家：`GET /api/countries` + 档案图
- 可选航迹：`/api/flights/{id}/track`
- 仍保留自建 catalog/fleet 与合法采集优势
