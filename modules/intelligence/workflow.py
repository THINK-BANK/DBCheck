# SPDX-License-Identifier: Apache-2.0
# Copyright 2025-2026 fiyo (Jack Ge) <sdfiyon@gmail.com>
# Author: fiyo (Jack Ge) - https://github.com/fiyo/DBCheck

"""轻量 DAG 条件编排（规划文档 4.4 C：Workflow Builder 引擎）。

一个 Workflow 由若干 Step 与有向边 edges 组成；引擎按拓扑序执行，每个 Step 可带
``when`` 条件（基于共享上下文）决定是否执行。Step 复用既有协同诊断能力：

* ``specialist`` —— 调 ``registry.get(ref).analyze(ctx)`` 追加发现（与重规划同一套能力）；
* ``hub``        —— 调 ``DiagnosticHub.dispatch`` 组合一次完整重诊断；
* ``skill``      —— 调 ``dispatch_skill`` 复用阶段 B 的 Skills/WriteGate；
* ``func``       —— 任意可调用 ``callable(ctx, args)``，做数据搬运/条件注入。

本文件仅实现编排引擎；可视化（Workflow Builder UI）属阶段 D。复用不重复造轮子：
专家能力、WriteGate、Reviewer 全部来自既有模块。
"""

from __future__ import annotations

from collections import deque
from typing import Any, Callable, Dict, List, Optional

from .context import SharedContext, Finding


class Step:
    """工作流的一个节点。"""

    def __init__(
        self,
        id: str,
        kind: str = "specialist",
        ref: str = "",
        args: Optional[Dict[str, Any]] = None,
        when: Optional[Callable[[SharedContext], bool]] = None,
        label: str = "",
    ) -> None:
        self.id = id
        self.kind = kind          # specialist | hub | skill | func
        self.ref = ref
        self.args = args or {}
        self.when = when          # Optional[Callable[[SharedContext], bool]] 条件分支
        self.label = label or id


class Workflow:
    """轻量 DAG 编排引擎（Kahn 拓扑序 + when 条件分支）。"""

    def __init__(self, steps: List[Step], edges: Optional[List[tuple]] = None) -> None:
        self.steps = {s.id: s for s in steps}
        self.order = [s.id for s in steps]
        self.edges = edges or []  # List[(from_id, to_id)]

    def _topo_order(self) -> List[str]:
        indeg = {sid: 0 for sid in self.steps}
        adj: Dict[str, List[str]] = {sid: [] for sid in self.steps}
        for a, b in self.edges:
            if a in self.steps and b in self.steps:
                adj[a].append(b)
                indeg[b] += 1
        q = deque(sid for sid in self.steps if indeg[sid] == 0)
        out: List[str] = []
        seen = set()
        while q:
            n = q.popleft()
            if n not in seen:
                out.append(n)
                seen.add(n)
            for m in adj[n]:
                indeg[m] -= 1
                if indeg[m] == 0:
                    q.append(m)
        # 无环且全部入队 → 拓扑序；否则退化为定义顺序（容错，不阻断）
        if len(out) == len(self.steps):
            return out
        return list(self.order)

    def run(
        self,
        goal: str,
        instance_id: str,
        inputs: Optional[Dict[str, Any]] = None,
        ctx: Optional[SharedContext] = None,
    ) -> Dict[str, Any]:
        ctx = ctx or SharedContext(goal=goal, target=instance_id, inputs=dict(inputs or {}))
        order = self._topo_order()
        log: List[Dict[str, Any]] = []
        executed: List[str] = []
        skipped: List[str] = []

        for sid in order:
            step = self.steps[sid]
            if step.when is not None and not step.when(ctx):
                skipped.append(sid)
                log.append({"step": sid, "status": "skipped", "reason": "when 条件不满足"})
                continue
            try:
                self._exec_step(step, ctx, goal, instance_id)
                executed.append(sid)
                log.append({"step": sid, "status": "done"})
            except Exception as e:  # 单步失败不影响整体编排
                log.append({"step": sid, "status": "error", "error": str(e)})

        return {
            "ctx": ctx.to_dict(),
            "steps_executed": executed,
            "steps_skipped": skipped,
            "order": order,
            "log": log,
        }

    def _exec_step(self, step: Step, ctx: SharedContext, goal: str, instance_id: str) -> None:
        if step.kind == "specialist":
            from .registry import registry

            spec = registry.get(step.ref)
            if spec is None:
                raise ValueError(f"unknown specialist: {step.ref}")
            for f in spec.analyze(ctx):
                ctx.add(f)
        elif step.kind == "hub":
            from .hub import get_hub

            res = get_hub().dispatch(goal, instance_id, step.args or {})
            for f in res.get("findings", []):
                if isinstance(f, dict):
                    ctx.add(Finding(
                        source=f.get("source", "hub"),
                        category=f.get("category", "risk"),
                        severity=f.get("severity", "info"),
                        title=f.get("title", ""),
                        detail=f.get("detail", ""),
                        suggestion=f.get("suggestion", ""),
                        tags=f.get("tags", []),
                    ))
            if res.get("plan"):
                ctx.plan.extend(res["plan"])
        elif step.kind == "skill":
            from .skills import dispatch_skill

            dispatch_skill(step.ref, step.args or {}, principal=None)
        elif step.kind == "func":
            fn = step.args.get("callable")
            if callable(fn):
                fn(ctx, step.args)
            elif callable(step.ref):
                step.ref(ctx, step.args)
        else:
            raise ValueError(f"unknown step kind: {step.kind}")
