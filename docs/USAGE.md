# FlightLog 使用手册

## 30 秒上手

```bash
docker compose up -d
# 打开 http://localhost:8321
```

就这些。数据库自动创建，无任何必填配置。

## 三种录入方式

### 1. 手动录入
填日期/航班号/三字码（如 PEK、SHA）即可。机场代码见页面提示，常用 42 个机场内置。

### 2. 航班号查询（可选配 key）
输入航班号+日期 → 自动查起降机场/时刻/航司 → 一键存入。
- key 配置：https://aviationstack.com 免费注册 → `server/api_keys.json` 写 `{"aviationstack": "你的key"}` → 重启容器
- 不配置也能用全部其他功能；免费档主要覆盖近期航班

### 3. 短信导入（推荐，零配置）
粘贴任何订票短信/行程邮件，自动解析出航班号/日期/城市→三字码/座位，勾选后批量入库。支持多段行程。

## 主题

- 默认跟随系统深浅色
- 点右上角 🌗 手动切换，选择会被记住（localStorage）
- 地图瓦片同步切换（暗色/亮色 CARTO）

## 数据自主

- 数据在 `./data/flightlog.db`（SQLite 单文件）
- 备份：复制这个文件即可
- 迁移到新机器：拷整个目录 + `docker compose up -d`
- 删除全部数据：`docker compose down` 后删 `data/`

## 常见问题

**Q: 端口被占用？**
`docker-compose.yml` 里改 `"8321:8321"` 左边的数字。

**Q: 短信里的座位没识别出来？**
正则版需要"座位/Seat"等关键词或"45C座"格式；纯"已值机 45C"抓不到，可手动补。

**Q: 国际航班？**
内置 42 机场含主要国际枢纽（HKG/NRT/SIN/LAX/LHR 等），未收录机场会提示，可在 `server/db.py` 的机场字典自行添加。

**Q: 想让 AI 帮我记航班？**
见 `docs/MCP.md`——配置一次后，在支持 MCP 的 AI 客户端里直接说"把这条短信记进飞行档案"。

## 开发者

- 后端：`server/`（FastAPI + SQLite，接口文档见 `docs/API.md`，或启动后访问 `/docs` 看交互式文档）
- 前端：`web/index.html`（单文件，改完刷新即生效）
- 本地开发：`cd server && python3 -m uvicorn app:app --port 8321`
