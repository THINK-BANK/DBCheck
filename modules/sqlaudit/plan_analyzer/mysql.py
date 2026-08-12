# -*- coding: utf-8 -*-
# SPDX-License-Identifier: Apache-2.0
# Copyright 2025-2026 fiyo (Jack Ge) <sdfiyon@gmail.com>
# Author: fiyo (Jack Ge) - https://github.com/fiyo/DBCheck

"""MySQL 执行计划适配器：EXPLAIN <stmt>，解析 type / key / rows / Extra。"""
from .base import BasePlanAnalyzer, _cost_hint, _build_advice


class MySQLPlanAnalyzer(BasePlanAnalyzer):
    engine = "mysql"

    def explain(self, conn, stmt):
        cur = conn.cursor()
        try:
            cur.execute("EXPLAIN " + stmt)
            return cur.fetchall()
        finally:
            cur.close()

    def parse(self, plan_rows) -> dict:
        rows = plan_rows or []
        full_table_scan = any(str(r.get("type", "")).upper() == "ALL" for r in rows)
        index_used = [
            r.get("key") for r in rows
            if r.get("key") and str(r.get("key")).upper() != "NULL"
        ]
        try:
            estimated_rows = max(int(r.get("rows") or 0) for r in rows) if rows else None
        except Exception:
            estimated_rows = None
        extra_flags = [r.get("Extra", "") or "" for r in rows]
        cost_hint = _cost_hint(estimated_rows, full_table_scan)
        advice = _build_advice(full_table_scan, index_used, extra_flags)
        return {
            "engine": self.engine,
            "applicable": True,
            "full_table_scan": full_table_scan,
            "index_used": index_used,
            "estimated_rows": estimated_rows,
            "cost_hint": cost_hint,
            "advice": advice,
        }
