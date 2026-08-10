# SPDX-License-Identifier: Apache-2.0
# Copyright 2025-2026 fiyo (Jack Ge) <sdfiyon@gmail.com>
# Author: fiyo (Jack Ge) - https://github.com/fiyo/DBCheck

"""MCP Server 启动引导。

必须在 import 任何 modules.* 之前把仓库根加入 sys.path，并先执行
paths.ensure_migrated()（InstanceManager 默认参数在导入期求值 PRO_DATA_DIR）。
切勿 import modules.web.app（会建 Flask + SocketIO、抢端口、打 banner）。
"""

import os
import sys

# 引导层例外：此处尚未把仓库根加入 sys.path，无法 import modules.core.paths，
# 故只能自 __file__ 上溯推导（<root>/modules/mcp_server/bootstrap.py → 上溯 3 级）。
# 一旦 sys.path 就绪，全项目仍统一使用 paths.py 常量，不得再用 __file__ 取根。
_SELF_ROOT = os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
)
DEFAULT_ROOT = os.environ.get("DBCHECK_ROOT") or _SELF_ROOT


def bootstrap(root: str | None = None) -> str:
    """把仓库根加入 sys.path，执行幂等迁移与巡检 DAL 初始化，返回根路径。"""
    root = root or DEFAULT_ROOT
    if root not in sys.path:
        sys.path.insert(0, root)

    from modules.core import paths  # noqa: E402  (path 已就绪)
    paths.ensure_migrated()

    try:
        from modules.inspection.dal import init_database as _init_db  # noqa: E402
        _init_db()
    except Exception:
        # DAL 初始化失败不致命：仅影响需要 template/baseline 的极端场景
        pass

    return root
