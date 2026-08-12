# -*- coding: utf-8 -*-
# SPDX-License-Identifier: Apache-2.0
# Copyright 2025-2026 fiyo (Jack Ge) <sdfiyon@gmail.com>
# Author: fiyo (Jack Ge) - https://github.com/fiyo/DBCheck

"""执行计划分析基类与统一 plan_json 结构。

各库适配器（mysql / postgresql / oracle）继承 BasePlanAnalyzer，分别实现：
- explain(conn, stmt): 在已建立的 DB-API 连接上运行 EXPLAIN，返回原生计划行
- parse(plan_rows): 将原生计划行解析为统一的 plan_json

统一 plan_json 结构（analyze 的返回 / 落库到 sql_audit_items.plan_json）：
{
  "engine": "mysql" | "postgresql" | "oracle",
  "applicable": true/false,            # DDL/DCL 或失败时 false
  "full_table_scan": bool,
  "index_used": [str],                 # 命中的索引/键名
  "estimated_rows": int | None,
  "cost_hint": "low" | "mid" | "high",
  "advice": str,
  "note": str(可选),                   # applicable=false 且非错误时（如 "DDL/DCL 无需执行计划"）
  "error": str(可选)                   # applicable=false 因失败时报错信息
}
EXPLAIN 为只读操作，不会执行原 SQL，符合「默认只读 / 不执行」安全原则。
"""
import re


def _cost_hint(estimated_rows, full_table_scan: bool) -> str:
    """根据预估行数与是否全表扫描给出成本等级。"""
    if estimated_rows is None:
        level = "low"
    elif estimated_rows >= 100000:
        level = "high"
    elif estimated_rows >= 10000:
        level = "mid"
    else:
        level = "low"
    if full_table_scan and level == "low":
        level = "mid"
    return level


def _build_advice(full_table_scan: bool, index_used: list, extra_flags=None) -> str:
    """生成执行计划建议文案（可多条，以中文分号连接）。"""
    advice = []
    if full_table_scan and not index_used:
        advice.append("建议为过滤/WHERE 字段增加索引以规避全表扫描")
    extra_text = " ".join(str(e) for e in (extra_flags or []))
    if "Using filesort" in extra_text or "Using temporary" in extra_text:
        advice.append("注意临时表/文件排序开销，可能拖慢查询")
    if "TABLE ACCESS FULL" in extra_text and not index_used:
        advice.append("存在 TABLE ACCESS FULL，建议评估索引或改写 SQL")
    return "；".join(advice)


class BasePlanAnalyzer:
    engine = "base"

    def explain(self, conn, stmt: str):
        raise NotImplementedError

    def parse(self, plan_rows) -> dict:
        raise NotImplementedError

    def analyze(self, conn, stmt: str, parsed: dict = None) -> dict:
        """运行 EXPLAIN 并解析为统一 plan_json；异常时返回 applicable=False 的错误结构（不向上抛出）。"""
        try:
            rows = self.explain(conn, stmt)
            return self.parse(rows)
        except Exception as e:  # noqa: BLE001
            return {"engine": self.engine, "applicable": False, "error": str(e)}
