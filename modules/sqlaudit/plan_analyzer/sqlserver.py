# -*- coding: utf-8 -*-
# SPDX-License-Identifier: Apache-2.0
# Copyright 2025-2026 fiyo (Jack Ge) <sdfiyon@gmail.com>
# Author: fiyo (Jack Ge) - https://github.com/fiyo/DBCheck

"""SQL Server 执行计划适配器。

SQL Server 没有 EXPLAIN 关键字，改用会话级 `SET SHOWPLAN_XML ON`：
开启后执行原语句只会返回执行计划 XML、而不会真正执行原 SQL（只读安全）。
使用 pyodbc 游标取回计划 XML 文本，解析 Table Scan / Clustered Index Scan、
引用的索引与预估行数。
"""
import re

from .base import BasePlanAnalyzer, _cost_hint, _build_advice


class SqlServerPlanAnalyzer(BasePlanAnalyzer):
    engine = "sqlserver"

    def explain(self, conn, stmt):
        cur = conn.cursor()
        try:
            # 仅生成执行计划而不执行原 SQL —— 符合「默认只读 / 不执行」原则
            cur.execute("SET SHOWPLAN_XML ON")
            cur.execute(stmt)
            return [str(r[0]) for r in cur.fetchall()]
        finally:
            try:
                cur.execute("SET SHOWPLAN_XML OFF")
            except Exception:  # noqa: BLE001
                pass
            cur.close()

    def parse(self, plan_rows) -> dict:
        text = "".join(str(r) for r in (plan_rows or []) if r)

        # 全表扫描：Table Scan 或 Clustered Index Scan 命中即视为全表扫描
        full_table_scan = ("Table Scan" in text) or ("Clustered Index Scan" in text)

        # 命中索引：执行计划中引用的索引名（Object 元素的 Index 属性）
        index_used = re.findall(r'Index="([^"]+)"', text)
        if not index_used:
            index_used = re.findall(r'Index="\s*\[\s*([^\]]+?)\s*\]\s*"', text)

        # 预估行数：取所有 RelOp 的 EstimateRows 最大值
        ests = re.findall(r'EstimateRows="([\d.]+)"', text)
        estimated_rows = None
        if ests:
            try:
                estimated_rows = max(int(float(x)) for x in ests)
            except Exception:  # noqa: BLE001
                estimated_rows = None

        cost_hint = _cost_hint(estimated_rows, full_table_scan)
        advice = _build_advice(full_table_scan, index_used, [text])
        return {
            "engine": self.engine,
            "applicable": True,
            "full_table_scan": full_table_scan,
            "index_used": index_used,
            "estimated_rows": estimated_rows,
            "cost_hint": cost_hint,
            "advice": advice,
        }
