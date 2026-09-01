# SPDX-License-Identifier: Apache-2.0
# Copyright 2025-2026 fiyo (Jack Ge) <sdfiyon@gmail.com>
# Author: fiyo (Jack Ge) - https://github.com/fiyo/DBCheck

"""专家能力清单：注册所有内置专家能力。"""

from __future__ import annotations

from ..registry import registry
from .monitor_sentinel import MonitorSentinel
from .inspection_expert import InspectionExpert
from .rootcause_expert import RootCauseExpert
from .sql_governance import SqlGovernance
from .lock_analyst import LockAnalyst
from .nl_query_expert import NlQueryExpert
from .coordinator import Coordinator
from .index_advisor import IndexAdvisor
from .baseline_compare import BaselineCompare
from .capacity_analyst import CapacityAnalyst
from .native_db import NativeDbExpert

_registered = False


def register_all() -> None:
    global _registered
    if _registered:
        return
    for s in (
        Coordinator(),
        MonitorSentinel(),
        InspectionExpert(),
        RootCauseExpert(),
        SqlGovernance(),
        LockAnalyst(),
        NlQueryExpert(),
        # ── 阶段 C 专家域扩展（规划文档 4.4 C）──
        IndexAdvisor(),
        BaselineCompare(),
        CapacityAnalyst(),
        NativeDbExpert(),
    ):
        registry.register(s)
    _registered = True
