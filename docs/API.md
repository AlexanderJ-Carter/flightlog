# FlightLog API 接口指南

Base URL：`http://localhost:8321`（Docker 启动后）

所有接口均为 JSON。错误时返回 `{"detail": "..."}` + 4xx/5xx 状态码。

## 航班记录

### `GET /api/flights`
全部航班，新→旧排序。

```json
{"flights": [
  {"id": 1, "date": "2026-05-01", "flight": "MU5101",
   "from": "PEK", "to": "SHA", "seat": "32A", "note": "出差"}
]}
```

### `POST /api/flights`
```json
// 请求
{"date": "2026-05-01", "flight": "MU5101", "from": "PEK", "to": "SHA",
 "seat": "32A", "note": "出差"}
// seat/note 可省略
// 响应
{"ok": true, "id": 3}
```

### `DELETE /api/flights/{id}`
幂等。响应 `{"ok": true}`。

## 统计

### `GET /api/stats`
```json
{"total": 28, "km": 62653.2, "airports": 15,
 "airlines": {"MU": 12, "CA": 9},
 "years": {"2024": 10, "2025": 12, "2026": 6},
 "routes": {"PEK-SHA": 5, "PEK-CTU": 3}}
```
`km` 按 haversine 球面距离累计。

## 地图

### `GET /api/map`
```json
{
  "airports": [["PEK", "北京首都", 40.08, 116.58], ...],
  "routes": [
    {"path": [[40.08,116.58], [35.6,119.0], [31.19,121.33]], "weight": 2},
    ...
  ]
}
```
`path` 为 3 点弧线（起点/中点/终点），`weight` 为该航线飞行次数（正反向合并）。

## 智能能力

### `POST /api/lookup` — 航班号查询
```json
// 请求
{"flight": "MU5101", "date": "2026-05-01"}
// 命中
{"found": true, "flight": "MU5101", "date": "...", "from": "SHA",
 "to": "PEK", "dep_time": "...", "arr_time": "...", "airline": "东方航空"}
// 未命中（含未配置 key）
{"found": false, "reason": "未配置API key"}
```
数据源：AviationStack（免费注册 https://aviationstack.com，key 放 `server/api_keys.json` 或 `server/data/api_keys.json`）。免费档覆盖近期航班。

### `POST /api/extract` — 订票短信解析
```json
// 请求
{"text": "您已出票 MU5101 2026-05-01 北京首都→上海虹桥 座位32A"}
// 响应
{"rows": [
  {"date": "2026-05-01", "flight": "MU5101", "from": "PEK",
   "to": "SHA", "seat": "32A", "note": ""}
]}
```
支持：城市名/机场名→三字码（"上海浦东"→PVG）、多机场城市、"北京-香港"连接式、数字前缀航班号（9C8899）、多段行程一次解析。识别不到时返回空 `rows`。

## 错误码约定

| 状态 | 场景 |
|------|------|
| 422 | 请求体字段缺失/类型错误 |
| 500 | 数据库异常（查看容器日志） |

## MCP（AI 客户端接入）

详见 `docs/MCP.md` —— 在 Claude Desktop / 飞象等 MCP 客户端中直接对话录入航班：
> "帮我把这条短信记进飞行档案：……"
