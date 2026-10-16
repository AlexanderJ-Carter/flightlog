#!/usr/bin/env python3
"""flightlog MCP Server —— 让 MCP 客户端（Claude Desktop / 飞象等）直接读写飞行档案。

协议：MCP over stdio（JSON-RPC 2.0，每行一条消息，换行分隔）
协议版本：2024-11-05
依赖：零第三方依赖（标准库 json/sys）；复用同目录 db.py / extract.py

暴露 8 个工具：
    add_flight(date, flight, from_ap, to_ap, seat?, note?, aircraft?)  录入单条航班
    list_flights()                                          全部航班（新→旧）
    flight_stats()                                          总里程/机场数/航司/年度统计
    extract_text(text)                                      订票短信 → 结构化（不入库）
    add_flights_from_text(text)                             短信解析 + 批量入库
    update_flight(id, ...)                                  编辑记录（部分更新）
    delete_flight(id)                                       删除记录
    export_flights()                                        导出档案 JSON 备份

用法（MCP 客户端配置见 mcp_config.example.json）：
    由客户端以 stdio 子进程方式拉起，本脚本从 stdin 读 JSON-RPC、往 stdout 写结果，
    日志走 stderr（stdout 被协议占用，禁止 print 到 stdout）。
"""
import json
import sys

import db
import extract as extractor

PROTOCOL_VERSION = "2024-11-05"
SERVER_INFO = {"name": "flightlog", "version": "1.0.0"}


def log(msg):
    """日志走 stderr；stdout 是协议通道，绝不能写。"""
    print(f"[mcp_server] {msg}", file=sys.stderr, flush=True)


# ------------------------------------------------------------------
# 工具定义（inputSchema 遵循 JSON Schema）
# ------------------------------------------------------------------
def _ap_schema(desc):
    return {"type": "string", "description": desc}


TOOLS = [
    {
        "name": "add_flight",
        "description": "录入一条飞行记录到飞行档案。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "date": {"type": "string", "description": "飞行日期 YYYY-MM-DD"},
                "flight": {"type": "string", "description": "航班号，如 MU5101"},
                "from_ap": _ap_schema("出发机场三字码，如 PEK"),
                "to_ap": _ap_schema("到达机场三字码，如 SHA"),
                "seat": {"type": "string", "description": "座位号（可选），如 34A"},
                "note": {"type": "string", "description": "备注（可选）"},
                "aircraft": {"type": "string", "description": "机型（可选），如 A320"},
                "registration": {"type": "string", "description": "注册号（可选），如 B-1234"},
            },
            "required": ["date", "flight", "from_ap", "to_ap"],
        },
    },
    {
        "name": "list_flights",
        "description": "列出飞行档案中的全部航班，按日期从新到旧。",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "flight_stats",
        "description": "飞行统计：总次数、总里程（公里，haversine）、"
                       "去过的机场数、各航司次数、各年度次数、各航线次数。",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "extract_text",
        "description": "把订票/出票短信原文解析成结构化航班信息"
                       "（航班号/日期/出发到达机场三字码/座位）。只解析，不写入档案。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "text": {"type": "string", "description": "短信原文"},
            },
            "required": ["text"],
        },
    },
    {
        "name": "add_flights_from_text",
        "description": "解析订票短信并把识别出的航班批量写入飞行档案。"
                       "返回解析明细和每条的入库 id；识别结果不完整"
                       "（缺日期/机场）的行会被跳过并在结果中说明。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "text": {"type": "string", "description": "短信原文"},
            },
            "required": ["text"],
        },
    },
    {
        "name": "update_flight",
        "description": "编辑一条已有记录：只传需要修改的字段，未传的不动。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "id": {"type": "integer", "description": "记录 id（list_flights 可查到）"},
                "date": {"type": "string", "description": "新日期 YYYY-MM-DD（可选）"},
                "flight": {"type": "string", "description": "新航班号（可选）"},
                "from_ap": {"type": "string", "description": "新出发机场（可选）"},
                "to_ap": {"type": "string", "description": "新到达机场（可选）"},
                "seat": {"type": "string", "description": "新座位（可选）"},
                "note": {"type": "string", "description": "新备注（可选）"},
                "aircraft": {"type": "string", "description": "新机型（可选）"},
                "registration": {"type": "string", "description": "新注册号（可选）"},
            },
            "required": ["id"],
        },
    },
    {
        "name": "delete_flight",
        "description": "按 id 删除一条飞行记录（幂等：删不存在的 id 也返回成功）。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "id": {"type": "integer", "description": "要删除的记录 id"},
            },
            "required": ["id"],
        },
    },
    {
        "name": "export_flights",
        "description": "导出整个飞行档案（JSON 列表），用于备份或迁移到其他工具。",
        "inputSchema": {"type": "object", "properties": {}},
    },
]


# ------------------------------------------------------------------
# 工具实现
# ------------------------------------------------------------------
def tool_add_flight(args):
    if not all(args.get(k, "").strip() for k in ("date", "flight", "from_ap", "to_ap")):
        raise ValueError("date/flight/from_ap/to_ap 均为必填，不能为空")
    fid = db.add_flight(
        date=args["date"].strip(),
        flight=args["flight"].strip().upper(),
        from_ap=args["from_ap"].strip().upper(),
        to_ap=args["to_ap"].strip().upper(),
        seat=(args.get("seat") or "").strip(),
        note=(args.get("note") or "").strip(),
        aircraft=(args.get("aircraft") or "").strip(),
        registration=(args.get("registration") or "").strip().upper(),
    )
    return {"ok": True, "id": fid,
            "added": {"date": args["date"], "flight": args["flight"].upper(),
                      "from": args["from_ap"].upper(), "to": args["to_ap"].upper()}}


def tool_list_flights(_args):
    flights = db.list_flights()
    return {"count": len(flights), "flights": flights}


def tool_flight_stats(_args):
    return db.stats()


def tool_extract_text(args):
    text = (args.get("text") or "").strip()
    if not text:
        raise ValueError("text 不能为空")
    rows = extractor.extract(text)
    return {"count": len(rows), "rows": rows,
            "hint": "这是解析结果，未写入档案；确认无误后可用 add_flight 入库"}


def tool_add_flights_from_text(args):
    text = (args.get("text") or "").strip()
    if not text:
        raise ValueError("text 不能为空")
    rows = extractor.extract(text)
    added, skipped = [], []
    for r in rows:
        # 关键字段不完整的行跳过，避免脏数据进档案
        if not (r["date"] and r["flight"] and r["from"] and r["to"]):
            skipped.append({**r, "reason": "缺少必要字段（日期/航班号/机场）"})
            continue
        fid = db.add_flight(date=r["date"], flight=r["flight"],
                            from_ap=r["from"], to_ap=r["to"],
                            seat=r.get("seat", ""), note=r.get("note", ""),
                            aircraft=r.get("aircraft", ""))
        added.append({"id": fid, **r})
    return {"added_count": len(added), "added": added,
            "skipped_count": len(skipped), "skipped": skipped}


def tool_update_flight(args):
    fid = args.get("id")
    if not isinstance(fid, int):
        raise ValueError("id 必须是整数（来自 list_flights 的记录 id）")
    fields = {k: v for k, v in args.items()
              if k != "id" and v not in (None, "")}
    if not fields:
        raise ValueError("除 id 外至少还要传一个要修改的字段")
    if "flight" in fields:
        fields["flight"] = str(fields["flight"]).strip().upper()
    for k in ("from_ap", "to_ap"):
        if k in fields:
            fields[k] = str(fields[k]).strip().upper()
    ok = db.update_flight(fid, **fields)
    if not ok:
        raise ValueError(f"记录 id={fid} 不存在")
    return {"ok": True, "id": fid, "updated_fields": sorted(fields)}


def tool_delete_flight(args):
    fid = args.get("id")
    if not isinstance(fid, int):
        raise ValueError("id 必须是整数")
    db.delete_flight(fid)
    return {"ok": True, "deleted_id": fid}


def tool_export_flights(_args):
    flights = db.list_flights()
    return {"count": len(flights),
            "hint": "JSON 备份；把 flights 数组喂回 add_flight 可恢复",
            "flights": flights}


TOOL_IMPLS = {
    "add_flight": tool_add_flight,
    "list_flights": tool_list_flights,
    "flight_stats": tool_flight_stats,
    "extract_text": tool_extract_text,
    "add_flights_from_text": tool_add_flights_from_text,
    "update_flight": tool_update_flight,
    "delete_flight": tool_delete_flight,
    "export_flights": tool_export_flights,
}


# ------------------------------------------------------------------
# MCP 方法分发
# ------------------------------------------------------------------
def handle_initialize(_params):
    return {
        "protocolVersion": PROTOCOL_VERSION,
        "capabilities": {"tools": {}},
        "serverInfo": SERVER_INFO,
    }


def handle_tools_list(_params):
    return {"tools": TOOLS}


def handle_tools_call(params):
    name = params.get("name", "")
    impl = TOOL_IMPLS.get(name)
    if impl is None:
        # 规范要求：未知工具返回 isError 的工具结果，而不是协议错误
        return {
            "content": [{"type": "text", "text": f"未知工具：{name}"}],
            "isError": True,
        }
    args = params.get("arguments") or {}
    try:
        result = impl(args)
        return {
            "content": [{"type": "text",
                         "text": json.dumps(result, ensure_ascii=False, indent=2)}],
            "isError": False,
        }
    except Exception as e:  # 工具内部错误也走 isError 结果
        return {
            "content": [{"type": "text", "text": f"工具执行失败：{e}"}],
            "isError": True,
        }


METHODS = {
    "initialize": handle_initialize,
    "tools/list": handle_tools_list,
    "tools/call": handle_tools_call,
    # 客户端常发的通知，接受但无需响应
    "notifications/initialized": None,
    "ping": lambda _p: {},
}


def process_message(msg):
    """处理一条 JSON-RPC 消息，返回应答 dict 或 None（通知无应答）。"""
    method = msg.get("method", "")
    msg_id = msg.get("id")  # 没有 id 的是通知，一律不应答

    if method not in METHODS:
        if msg_id is not None:
            return {"jsonrpc": "2.0", "id": msg_id,
                    "error": {"code": -32601, "message": f"Method not found: {method}"}}
        return None

    handler = METHODS[method]
    if handler is None:  # 通知
        return None

    try:
        result = handler(msg.get("params") or {})
    except Exception as e:
        if msg_id is None:
            log(f"处理 {method} 出错: {e}")
            return None
        return {"jsonrpc": "2.0", "id": msg_id,
                "error": {"code": -32603, "message": f"Internal error: {e}"}}

    if msg_id is None:  # request 型消息却没带 id（不合规），也不应答
        return None
    return {"jsonrpc": "2.0", "id": msg_id, "result": result}


def main():
    db.init_db()
    log(f"ready. db={db.DB_PATH} tools={[t['name'] for t in TOOLS]}")
    # MCP stdio：一行一条 JSON-RPC 消息
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except ValueError:
            log(f"非 JSON 输入，忽略: {line[:80]}")
            continue
        reply = process_message(msg)
        if reply is not None:
            sys.stdout.write(json.dumps(reply, ensure_ascii=False) + "\n")
            sys.stdout.flush()
    log("stdin closed, exit")


if __name__ == "__main__":
    main()
