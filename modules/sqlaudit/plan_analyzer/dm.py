# -*- coding: utf-8 -*-
# SPDX-License-Identifier: Apache-2.0
# Copyright 2025-2026 fiyo (Jack Ge) <sdfiyon@gmail.com>
# Author: fiyo (Jack Ge) - https://github.com/fiyo/DBCheck

"""达梦（DM8）执行计划适配器：EXPLAIN <stmt>，解析 CSCN/TSCN（全表扫描）/ SSCN/SSEK/CSEK（索引）/ 预估行数。

达梦 DM8 的 EXPLAIN 以结果集形式返回文本化执行计划（算子形如 #CSCN2 / #SSEK2），
EXPLAIN 只生成计划、不真正执行原 SQL（只读安全）。使用 dmPython 游标取回计划，
按文本规则解析。

算子速查：
- #CSCN2 / #TSCN2：全表扫描（代价扫描 / 表扫描）
- #SSCN2：索引扫描；#SSEK2 / #CSEK2：索引/聚集索引定位（Seek）
- 算子方括号 `[time, rows, bytes]` 中的第 2 项为预估行数（card）
"""
import re

from .base import BasePlanAnalyzer, _cost_hint, _build_advice


class DamengPlanAnalyzer(BasePlanAnalyzer):
    engine = "dm"

    def explain(self, conn, stmt):
        cur = conn.cursor()
        try:
            cur.execute("EXPLAIN " + stmt)
            return cur.fetchall()
        finally:
            cur.close()

    def parse(self, plan_rows) -> dict:
        # DM EXPLAIN 返回可能为 [(lineid, operator, ...), ...] 或 [(text,), ...]，统一拼成文本
        lines = []
        for r in (plan_rows or []):
            if isinstance(r, (list, tuple)):
                lines.extend(str(c) for c in r if c is not None)
            else:
                lines.append(str(r))
        text = "\n".join(lines)

        # 全表扫描：CSCN（代价扫描=全表扫描）/ TSCN（表扫描）
        full_table_scan = ("CSCN" in text) or ("TSCN" in text)

        # 命中索引：SSCN/SSEK/CSEK 后通过 SCAN INDEX <name> 引用的索引名
        index_used = re.findall(r"SCAN INDEX\s+(\S+)", text)

        # 预估行数：取每个算子 [time, rows, bytes] 中的 rows（第 2 个数）最大值
        ests = re.findall(r"\[[\d.]+\s*,\s*([\d.]+)", text)
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
