# -*- coding: utf-8 -*-
# SPDX-License-Identifier: Apache-2.0
# Copyright 2025-2026 fiyo (Jack Ge) <sdfiyon@gmail.com>
# Author: fiyo (Jack Ge) - https://github.com/fiyo/DBCheck

"""PostgreSQL 执行计划适配器：EXPLAIN <stmt>，解析 Seq Scan / Index Scan / rows。"""
import re

from .base import BasePlanAnalyzer, _cost_hint, _build_advice


class PostgresPlanAnalyzer(BasePlanAnalyzer):
    engine = "postgresql"

    def explain(self, conn, stmt):
        cur = conn.cursor()
        try:
            cur.execute("EXPLAIN " + stmt)
            return cur.fetchall()
        finally:
            cur.close()

    def parse(self, plan_rows) -> dict:
        # RealDictCursor 返回 [{'QUERY PLAN': '...'}, ...]；保守兼容 tuple / dict 两种形态
        lines = []
        for r in (plan_rows or []):
            if isinstance(r, dict):
                text = r.get("QUERY PLAN")
            elif isinstance(r, (list, tuple)):
                text = r[0] if r else None
            else:
                text = r
            if text:
                lines.append(str(text))
        text = "\n".join(lines)

        # 任意 Seq Scan（含 Parallel Seq Scan）即视为全表扫描，不因子查询含索引而漏判
        full_table_scan = ("Seq Scan" in text) or ("Parallel Seq Scan" in text)
        index_used = re.findall(r"Index (?:Only )?Scan using (\S+)", text)
        ests = re.findall(r"rows=(\d+)", text)
        estimated_rows = max(int(x) for x in ests) if ests else None
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
