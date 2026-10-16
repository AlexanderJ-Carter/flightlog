# FlightLog MCP 接入指南

让 AI 客户端（Claude Desktop、飞象等）直接读写你的飞行档案——对 AI 说"帮我记一下这班飞机"即可入库。

## 接入 Claude Desktop

1. 打开配置文件：`~/Library/Application Support/Claude/claude_desktop_config.json`
   （不存在就创建，注意 JSON 格式）
2. 把 `server/mcp_config.example.json` 中 `mcpServers` 的内容合并进去：

```json
{
  "mcpServers": {
    "flightlog": {
      "command": "/opt/homebrew/opt/python@3.11/bin/python3.11",
      "args": ["/Users/你的用户名/Desktop/flightlog/server/mcp_server.py"],
      "env": { "FLIGHTLOG_DATA_DIR": "/Users/你的用户名/Desktop/flightlog/data" }
    }
  }
}
```

3. 重启 Claude Desktop，出现 flightlog 工具图标即成功

## 可用工具（5 个）

| 工具 | 功能 |
|------|------|
| `add_flight` | 录入单条航班（date/flight/from/to/seat/note） |
| `list_flights` | 列出全部航班 |
| `flight_stats` | 统计（总里程/机场数/航司/年度趋势） |
| `extract_text` | 解析订票短信为结构化数据（只解析不入库） |
| `add_flights_from_text` | 短信解析+批量入库（识别不完整的行自动跳过并说明原因） |

## 对话示例

> 我：帮我记一下，东航 MU5101，5月1号北京飞上海，座位 32A
> AI：（调用 add_flight）已录入 ✈️ 累计飞行 28 次、62,653 公里

> 我：把这条短信记进飞行档案：【您已出票 CA4108 2026-08-15 北京首都→成都双流 座位21K】
> AI：（调用 add_flights_from_text）解析成功，已入库 1 条

## 技术说明

- 协议：MCP over stdio（JSON-RPC 2.0，换行分帧），protocolVersion `2024-11-05`
- 零第三方依赖，复用 flightlog 的 db.py / extract.py
- 与 Web 界面共享同一个 SQLite 数据库，两边操作互通
- 环境变量 `FLIGHTLOG_DB` 可指向独立数据库（测试用）
