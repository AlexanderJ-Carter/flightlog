# 竞品对齐第一批：航班字段 + Flighty/TripIt + 去重

## 目标

吸收 AirTrail / perdian 级航班实体与导入能力，保持单机 SQLite、不碰商业抓取。

## 航班字段（flightlog.db）

| 字段 | 说明 |
|------|------|
| dep_time / arr_time | 本地时刻 `HH:MM` 或 ISO 片段 |
| dep_terminal / arr_terminal | 航站楼 |
| dep_gate / arr_gate | 登机口 |
| trip_id | 行程分组（自由文本） |
| distance_km | 大圆距离，写入时按起降计算 |

## 导入

- Flighty CSV、TripIt ICS
- 重复（同日+航班+航线）：默认补全空字段，不跳过整行
- 返回 `added` / `updated` / `skipped`

## 不做

多用户、照片、OAuth、商业站爬取。
