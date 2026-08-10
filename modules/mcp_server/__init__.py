"""DBCheck MCP Server (M1 Spike)。

最小可用 MCP Server：以标准 JSON-RPC 2.0 over stdio 暴露 DBCheck 能力，
首批仅两个 tool：dbcheck.list_instances / dbcheck.run_inspection。

设计原则（见 docs/ai-agent-trio-implementation-plan.md §0）：
- 不引入任何第三方 Agent Framework；
- 仅复用现有 service 层（instance_manager / inspection_runner），不重写巡检逻辑；
- 零新增依赖（手搓协议合规的 stdio 服务器，对真实 Claude Desktop 同样兼容）；
- 不触碰 modules/inspection、modules/web/app.py 现有路由。
"""

__version__ = "0.1.0-spike"
