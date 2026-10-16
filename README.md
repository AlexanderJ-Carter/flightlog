# FlightLog · 我的飞行档案

> 一次 `docker compose up -d`，浏览器打开就是完整的个人飞行档案系统。

## 这是什么

纯本地的个人飞行记录与统计系统：
- ✈️ **航线地图**：Leaflet 真地图，弧形航线 + 机场点位
- 📊 **统计**：总航班 / 总里程 / 绕地球圈数 / 机场数 / 年度趋势 / 航司排行
- ✏️ **三种录入**：手动表单 / 航班号查询（API 自动补全）/ 订票短信粘贴解析
- 💾 **数据自主**：SQLite 单文件，备份 `data/` 目录 = 备份全部数据，不上传任何服务器

## 快速开始（唯一需要的一步）

```bash
docker compose up -d
```

浏览器打开 **http://localhost:8321** —— 完成。

停止：`docker compose down`（数据保留在 `./data/`）

## 可选配置

航班号自动查询需要免费 API key（不配置也不影响其他功能，只是查询 Tab 会提示未配置）：

1. 到 https://aviationstack.com 免费注册（30 秒）
2. `server/api_keys.json` 写入：`{"aviationstack": "你的key"}`
3. 重启容器

## 架构（单容器）

```
浏览器 → http://localhost:8321
            │
            ├── /            → 前端 SPA（打包进镜像的 web/index.html）
            └── /api/*       → FastAPI 后端
                                ├── SQLite（docker volume 持久化）
                                ├── 航班号查询代理（key 只存服务端）
                                └── 短信解析引擎
```

## 开发

```bash
# 后端（无需 Docker）
cd server && pip install -r requirements.txt
python3 -m uvicorn app:app --port 8321

# 前端
# 直接编辑 web/index.html，刷新即生效（无构建步骤）
```

## API

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | /api/flights | 全部航班（新→旧） |
| POST | /api/flights | 新增 {date, flight, from, to, seat?, note?} |
| DELETE | /api/flights/{id} | 删除 |
| GET | /api/stats | 统计（总里程/机场/航司/年度） |
| GET | /api/map | 地图数据（机场坐标+航线弧线） |
| POST | /api/lookup | 航班号查询 {flight, date} |
| POST | /api/extract | 短信解析 {text} |

## Roadmap

- [ ] 里程计算改用真实航路距离
- [ ] 年度海报导出（朋友圈分享图）
- [ ] 铁路记录支持
- [ ] 多人档案合并

## License

MIT
