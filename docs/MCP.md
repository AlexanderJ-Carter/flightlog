# FlightLog MCP 接入指南

让 AI 客户端（Claude Desktop、飞象等）直接读写你的飞行档案——对 AI 说「帮我记一下这班飞机」即可入库。

## 接入 Claude Desktop

1. 打开配置文件：`~/Library/Application Support/Claude/claude_desktop_config.json`
2. 把 `server/mcp_config.example.json` 中 `mcpServers` 的内容合并进去（路径改成你的本机路径）：

```json
{
  "mcpServers": {
    "flightlog": {
      "command": "uv",
      "args": [
        "run", "--directory", "/绝对路径/flightlog/server",
        "python", "mcp_server.py"
      ],
      "env": { "FLIGHTLOG_DATA_DIR": "/绝对路径/flightlog/data" }
    }
  }
}
```

完整示例见 `server/mcp_config.example.json`。需本机已安装 [uv](https://github.com/astral-sh/uv)。

3. 重启 Claude Desktop，出现 flightlog 工具图标即成功

MCP 服务在本地运行（不进 Docker 镜像），与 Web 共用 `FLIGHTLOG_DATA_DIR` 下的 SQLite。

## 可用工具（8 个）

| 工具 | 功能 |
|------|------|
| `add_flight` | 录入单条（date/flight/from/to/seat/note/aircraft） |
| `list_flights` | 列出航班 |
| `flight_stats` | 统计 |
| `extract_text` | 解析短信（只解析不入库） |
| `add_flights_from_text` | 解析并批量入库 |
| `update_flight` | 按 id 更新字段 |
| `delete_flight` | 按 id 删除 |
| `export_flights` | 导出航班 JSON |

## 对话示例

> 我：帮我记一下，东航 MU5101，5月1号北京飞上海，座位 32A  
> AI：（调用 add_flight）已录入

> 我：把这条短信记进飞行档案：【您已出票 CA4108 2026-08-15 北京首都→成都双流 座位21K】  
> AI：（调用 add_flights_from_text）解析成功，已入库 1 条

## 技术说明

- 协议：MCP over stdio（JSON-RPC 2.0），protocolVersion `2024-11-05`
- 零第三方依赖，复用 `db.py` / `extract.py` / `airports.py`
- 与 Web 界面共享同一个 SQLite
- `FLIGHTLOG_DB` 可指向独立数据库（测试用）
