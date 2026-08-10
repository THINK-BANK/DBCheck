# SPDX-License-Identifier: Apache-2.0
# Copyright 2025-2026 fiyo (Jack Ge) <sdfiyon@gmail.com>
# Author: fiyo (Jack Ge) - https://github.com/fiyo/DBCheck

"""MCP Spike 的两个 tool 实现。

每个 tool 只是现有 service 层的一层薄封装：
- list_instances  -> InstanceManager.get_all_instances(mask_password=True)
- run_inspection  -> run_target_inspection(db_type, instance, ...)
均同步、无 Flask 依赖。
"""

_STATE: dict = {}


def _ensure() -> dict:
    """懒加载并缓存底层 service 单例（首次调用时引导 sys.path + 迁移）。"""
    if "IM" in _STATE:
        return _STATE
    from modules.mcp_server.bootstrap import bootstrap  # noqa: E402
    bootstrap()
    from modules.pro import get_instance_manager  # noqa: E402
    from modules.intelligence.inspection_runner import run_target_inspection  # noqa: E402
    _STATE["IM"] = get_instance_manager()
    _STATE["run"] = run_target_inspection
    return _STATE


def list_instances_tool(mask_password: bool = True) -> dict:
    st = _ensure()
    rows = st["IM"].get_all_instances(mask_password=mask_password)
    clean = []
    for r in rows:
        d = dict(r)
        d.pop("password", None)  # 即便脱敏也直接剔除密码键
        clean.append(d)
    return {"ok": True, "count": len(clean), "instances": clean}


def run_inspection_tool(
    instance_id: str,
    template_id=None,
    inspector_name: str = "Jack",
) -> dict:
    st = _ensure()
    try:
        inst = st["IM"].get_instance_decrypted(instance_id)
    except Exception:
        inst = None
    if not inst:
        return {"ok": False, "error": f"instance not found: {instance_id}"}
    db_type = inst.get("db_type")
    if not db_type:
        return {"ok": False, "error": "instance missing db_type"}
    try:
        result = st["run"](db_type, inst, inspector_name, template_id)
    except Exception as e:  # 软降级，绝不抛给 MCP 协议层
        return {"ok": False, "error": f"inspection failed: {e}"}
    return {"ok": True, "result": result}
