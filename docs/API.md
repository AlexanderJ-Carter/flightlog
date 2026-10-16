# FlightLog API 接口指南

Base URL：`http://localhost:8321`（Docker 启动后）

所有接口均为 JSON。错误时返回 `{"detail": "..."}` 或结构化 detail + 4xx/5xx。

## 航班记录

### `GET /api/flights`

查询参数（均可选）：

| 参数 | 说明 |
|------|------|
| `year` | 四位年份 |
| `airline` | 航司二字码前缀（如 MU） |
| `airport` | 机场三字码（出发或到达） |
| `q` | 自由文本（航班号/机场/备注/机型） |
| `limit` / `offset` | 分页 |

```json
{"flights": [
  {"id": 1, "date": "2026-05-01", "flight": "MU5101",
   "from": "PEK", "to": "SHA", "seat": "32A", "note": "出差",
   "aircraft": "A320", "registration": "B-1234",
   "cabin_class": "economy", "seat_type": "window", "flight_reason": "business",
   "dep_time": "08:30", "arr_time": "10:40",
   "dep_terminal": "T3", "arr_terminal": "T2",
   "dep_gate": "C12", "arr_gate": "B5",
   "trip_id": "spring", "distance_km": 1075.7, "duration_min": 130,
   "airline_name": "China Eastern"}
]}
```

### `POST /api/flights`

成功 `201`。除必填 `date/flight/from/to` 外，可选舱位、座位类型、事由、时刻、航站楼、登机口、行程、`duration_min`、`distance_km`（未传则按大圆估算）等。

```json
{"date": "2026-05-01", "flight": "MU5101", "from": "PEK", "to": "SHA",
 "seat": "32A", "dep_time": "08:30", "cabin_class": "economy"}
```

```json
{"ok": true, "id": 3}
```

同日同航班同航线已存在时返回 `409`：

```json
{"detail": {"message": "已存在相同航班记录", "id": 3}}
```

### `PUT /api/flights/{id}`

部分更新：只传要改的字段。响应 `{"ok": true, "id": n}`。冲突同样 `409`。

### `DELETE /api/flights/{id}`

幂等。响应 `{"ok": true}`。

## 统计

### `GET /api/stats`

```json
{"total": 28, "km": 62653.2, "duration_min": 4120, "airports": 15,
 "airlines": {"MU": 12, "CA": 9},
 "years": {"2024": 10, "2025": 12},
 "routes": {"PEK-SHA": 5},
 "cabin_class": {"economy": 20}, "seat_type": {"window": 12},
 "flight_reason": {"leisure": 15}, "continents": {"AS": 10},
 "countries": {"CN": {"count": 12, "name": "China"}},
 "months": {"2026-05": 3}, "weekdays": {"Mon": 4},
 "aircraft": {"A320": 8, "B737": 5}, "aircraft_types": 2}
```

`km` 优先累计已落库 `distance_km`，否则按 haversine（无坐标记 0）。

## 地图

### `GET /api/map`

```json
{
  "airports": [["PEK", "北京首都", 40.08, 116.58]],
  "routes": [
    {"path": [[40.08,116.58], [35.6,119.0], [31.19,121.33]], "weight": 2}
  ]
}
```

`path` 为 3 点弧线；`weight` 为次数（正反向合并）。

## 机场

### `GET /api/airports?q=&limit=20`

按三字码或中文名模糊搜索，供录入自动完成。

```json
{"airports": [{"code": "PEK", "name": "北京首都", "lat": 40.08, "lon": 116.58, "known": true}]}
```

### `GET /api/airports/{code}`

`catalog.db` 地理层详情（主档 / 跑道 / 频率 / 导航台 / 国家地区名）。`code` 为 IATA 或 ICAO。

### `GET /api/catalog`

参考库分层行数与各数据源导入记录。

### `GET /api/weather/{code}`

NOAA 公开机场信息 + 最近 METAR（失败时对应字段为空）。

### `POST /api/fleet/catalog`

后台刷新 `catalog.db`（地理 + 登记 + 词典）。

### `POST /api/import/file`

多源文件导入（multipart）。字段：`file`、`source`（`auto|json|openflights|fr24|flighty|tripit`）、`replace`、`dry_run`。重复航班会补全空字段（`updated`）。

### `GET /api/countries`

访问国家统计（机场所属国家聚合）。

### `GET|PUT|DELETE /api/flights/{id}/track`

可选航迹：`points` 为 `[[lat,lon],...]`。

## 智能能力

### `POST /api/lookup`

```json
{"flight": "CA1902", "date": "2026-05-01"}
```

也支持纯数字：`{"flight":"1902","date":"..."}` → 返回 `candidates`（零配置为 adsbdb 真实命中的典型航线；配置 AviationStack 后优先实时结果，可含 `aircraft`）。

命中示例：

```json
{"found": true, "flight": "CA1902", "from": "URC", "to": "PEK",
 "from_name": "乌鲁木齐地窝堡", "to_name": "北京首都",
 "airline": "Air China", "aircraft": "A333", "registration": "B-1234",
 "source": "adsbdb", "note": "典型航线（非当日动态时刻）"}
```

`aircraft` / `registration` / `photo` 仅在该呼号当前有 ADS-B 空中目标时可能出现。

零配置走免费航线库 + OurAirports。可选密钥经页面「智能配置」写入 `data/api_keys.json`（勿放进 git）。

### `POST /api/extract`

```json
{"text": "您已出票 MU5101 2026-05-01 北京首都→上海虹桥 座位32A"}
```

```json
{"rows": [
  {"date": "2026-05-01", "flight": "MU5101", "from": "PEK",
   "to": "SHA", "seat": "32A", "note": "", "aircraft": ""}
]}
```

## 备份

### `GET /api/export?format=json|csv&year=`

- `json`：备份（可喂回 import）；传 `year` 时只导出该年
- `csv`：Excel 友好（含 BOM）；同样支持 `year`

### `POST /api/import`

```json
{"rows": [...], "replace": false}
```

`flights` 与 `rows` 二选一。`replace: true` 先清空再写入。重复行计入 `skipped`。

## 错误码

| 状态 | 场景 |
|------|------|
| 400 | 日期格式错误、无导入数据等 |
| 404 | 编辑不存在的 id |
| 409 | 重复航班 |
| 422 | 请求体校验失败 |

## 配置与健康

### `GET /api/health`

```json
{"ok": true, "version": "2.0", "providers": ["adsbdb"],
 "live_lookup": false, "airports": 8798, "catalog": {"counts": {}}}
```

`catalog` 为参考库分层统计，详见 `GET /api/catalog`。

### `GET /api/config` / `PUT /api/config/keys`

配置状态与密钥写入（密钥不回传明文）。详见使用手册「智能配置」。

## MCP

见 [MCP.md](MCP.md)。
