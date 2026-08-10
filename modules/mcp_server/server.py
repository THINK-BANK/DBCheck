# SPDX-License-Identifier: Apache-2.0
# Copyright 2025-2026 fiyo (Jack Ge) <sdfiyon@gmail.com>
# Author: fiyo (Jack Ge) - https://github.com/fiyo/DBCheck

"""DBCheck MCP Server —— 协议合规的最小 stdio 实现。

协议：JSON-RPC 2.0，行分隔（每行一条 JSON），stdin 收请求、stdout 发响应。
支持的 method：
- initialize            -> 返回 protocolVersion / capabilities / serverInfo
- notifications/initialized (通知，不回)
- ping                 -> {}
- tools/list           -> 两个 tool 的 name/description/inputSchema
- tools/call           -> 调 dbcheck.list_instances / dbcheck.run_inspection

关键约束：stdout 只能放 JSON-RPC 响应，任何 DBCheck 模块的散落 print
（如迁移日志、巡检进度）必须重定向到 stderr，否则会污染 Claude Desktop 的
协议流。做法：进入 main 后把 sys.stdout 指向 sys.stderr，协议回复写
sys.__stdout__（原始 stdout fd）。
"""

import json
import os
import sys

PROTOCOL_VERSION = "2024-11-05"
SERVER_NAME = "dbcheck-mcp"
SERVER_VERSION = "0.1.0-spike"


def _log(msg: str) -> None:
    sys.stderr.write(f"[mcp-server] {msg}\n")
    sys.stderr.flush()


def build_tools() -> list:
    return [
        {
            "name": "dbcheck.list_instances",
            "description": (
                "列出 DBCheck 中已保存的全部数据源（数据库实例）。"
                "返回 id / name / db_type / host / port 等元信息，密码已被剔除。"
            ),
            "inputSchema": {
                "type": "object",
                "properties": {
                    "mask_password": {
                        "type": "boolean",
                        "description": "是否脱敏密码（默认 true；无论真假本 tool 都剔除密码键）",
                        "default": True,
                    }
                },
                "required": [],
            },
        },
        {
            "name": "dbcheck.run_inspection",
            "description": (
                "对指定数据源执行一次全量健康检查巡检，返回健康分、风险项与 AI 修复建议。"
                "同步阻塞（视库规模可能耗时数分钟）。"
            ),
            "inputSchema": {
                "type": "object",
                "properties": {
                    "instance_id": {
                        "type": "string",
                        "description": "数据源 ID（来自 dbcheck.list_instances 的 id 字段）",
                    },
                    "template_id": {
                        "type": "string",
                        "description": "可选巡检模板 ID",
                    },
                    "inspector_name": {
                        "type": "string",
                        "description": "巡检人署名",
                        "default": "Jack",
                    },
                },
                "required": ["instance_id"],
            },
        },
    ]


def call_tool(name: str, args: dict) -> dict:
    from modules.mcp_server.tools import list_instances_tool, run_inspection_tool

    if name == "dbcheck.list_instances":
        return list_instances_tool(mask_password=args.get("mask_password", True))
    if name == "dbcheck.run_inspection":
        iid = args.get("instance_id")
        if not iid:
            return {"ok": False, "error": "instance_id required"}
        return run_inspection_tool(
            iid,
            template_id=args.get("template_id"),
            inspector_name=args.get("inspector_name", "Jack"),
        )
    return {"ok": False, "error": f"unknown tool: {name}"}


def handle(msg: dict):
    method = msg.get("method")
    mid = msg.get("id")
    params = msg.get("params", {}) or {}

    if method == "initialize":
        return {
            "jsonrpc": "2.0",
            "id": mid,
            "result": {
                "protocolVersion": params.get("protocolVersion", PROTOCOL_VERSION),
                "capabilities": {"tools": {}},
                "serverInfo": {"name": SERVER_NAME, "version": SERVER_VERSION},
            },
        }

    if method == "notifications/initialized":
        return None  # 通知，无需回应

    if method == "ping":
        return {"jsonrpc": "2.0", "id": mid, "result": {}}

    if method == "tools/list":
        return {"jsonrpc": "2.0", "id": mid, "result": {"tools": build_tools()}}

    if method == "tools/call":
        name = params.get("name")
        args = params.get("arguments", {}) or {}
        try:
            res = call_tool(name, args)
        except Exception as e:
            _log(f"tools/call {name} crashed: {e}")
            return {
                "jsonrpc": "2.0",
                "id": mid,
                "result": {
                    "content": [{"type": "text", "text": json.dumps(
                        {"ok": False, "error": f"tool crashed: {e}"},
                        ensure_ascii=True, default=str)}],
                    "isError": True,
                },
            }
        text = json.dumps(res, ensure_ascii=True, indent=2, default=str)
        return {
            "jsonrpc": "2.0",
            "id": mid,
            "result": {
                "content": [{"type": "text", "text": text}],
                "isError": not res.get("ok", True),
            },
        }

    if mid is not None:
        return {
            "jsonrpc": "2.0",
            "id": mid,
            "error": {"code": -32601, "message": f"method not found: {method}"},
        }
    return None


def main() -> None:
    # 把所有散落 stdout 输出（迁移日志、巡检进度等）重定向到 stderr，
    # 保护 JSON-RPC 协议流。协议回复写原始 stdout fd。
    sys.stdout = sys.stderr

    from modules.mcp_server.bootstrap import bootstrap  # noqa: E402
    bootstrap()

    # 可选鉴权闸门（stdio 本地受信场景可关闭；HTTP transport 阶段再强制）
    if os.environ.get("DBCHECK_MCP_REQUIRE_AUTH") == "1":
        from modules.mcp_server.auth import verify_api_key_raw  # noqa: E402
        ok, owner = verify_api_key_raw(os.environ.get("DBCHECK_MCP_API_KEY", ""))
        if not ok:
            _log("FATAL: DBCHECK_MCP_REQUIRE_AUTH=1 但 API Key 无效，拒绝启动")
            sys.exit(2)
        _log(f"auth ok, owner={owner}")

    # 关键修复：直接写 UTF-8 字节到原始 stdout 的二进制缓冲，绕过 TextIOWrapper
    # 编码。子进程在非控制台(管道)环境下 sys.__stdout__ 默认编码可能是 cp936/mbcs，
    # 写原始中文字符会被替换成 '?' 导致客户端乱码（如 ����）。
    out = sys.__stdout__.buffer
    try:
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass
    _log(f"{SERVER_NAME} {SERVER_VERSION} stdio server started")

    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except Exception:
            continue
        try:
            resp = handle(msg)
        except Exception as e:
            _log(f"handle error: {e}")
            resp = {
                "jsonrpc": "2.0",
                "id": msg.get("id"),
                "error": {"code": -32603, "message": str(e)},
            }
        if resp is not None:
            out.write(
                (json.dumps(resp, ensure_ascii=True, default=str) + "\n").encode("utf-8")
            )
            out.flush()
