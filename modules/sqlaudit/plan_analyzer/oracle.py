# -*- coding: utf-8 -*-
# SPDX-License-Identifier: Apache-2.0
# Copyright 2025-2026 fiyo (Jack Ge) <sdfiyon@gmail.com>
# Author: fiyo (Jack Ge) - https://github.com/fiyo/DBCheck

"""Oracle 执行计划适配器：EXPLAIN PLAN FOR <stmt> + DBMS_XPLAN.DISPLAY，解析 TABLE ACCESS FULL / INDEX。"""
import re

from .base import BasePlanAnalyzer, _cost_hint, _build_advice


class OraclePlanAnalyzer(BasePlanAnalyzer):
    engine = "oracle"

    def explain(self, conn, stmt):
        cur = conn.cursor()
        try:
            cur.execute("EXPLAIN PLAN FOR " + stmt)
            cur.execute("SELECT PLAN_TABLE_OUTPUT FROM TABLE(DBMS_XPLAN.DISPLAY())")
            return [row[0] for row in cur.fetchall()]
        finally:
            cur.close()

    def parse(self, plan_rows) -> dict:
        lines = [str(r) for r in (plan_rows or []) if r]
        text = "\n".join(lines)

        full_table_scan = "TABLE ACCESS FULL" in text
        # DBMS_XPLAN 输出为管道分隔表：INDEX RANGE SCAN | IDX_DEPTNO
        index_used = re.findall(r"INDEX\s+\w+\s+SCAN\s*\|\s*(\S+)", text)
        # 预估行数取 SELECT STATEMENT 行的 Rows 列（最可靠）
        m = re.search(r"SELECT STATEMENT\b.*?\|\s*(\d+)\s*\|\s*(\d+)", text, re.S)
        estimated_rows = int(m.group(1)) if m else None
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
