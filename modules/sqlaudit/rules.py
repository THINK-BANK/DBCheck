# -*- coding: utf-8 -*-
# SPDX-License-Identifier: Apache-2.0
# Copyright 2025-2026 fiyo (Jack Ge) <sdfiyon@gmail.com>
# Author: fiyo (Jack Ge) - https://github.com/fiyo/DBCheck

"""SQL 审核规则：种子规则定义、声明式匹配器与风险评分。

设计要点：
- 规则以「声明式 logic」描述（op_in / op_in_without_where / regex / select_star /
  full_scan / naming_table / naming_index），可直接序列化为 JSON 存入 sql_audit_rules 表，
  也可由运维在 UI/API 中扩展。
- 评分：每条语句取命中最严重规则的权重作为该句风险分；任务风险取全部语句的最大值。
- MVP1 仅内置规则匹配，不依赖外部 GPL 组件（Inception/SQLAdvisor 仅作可选外部二进制，
  不复制其源码，避免污染 Apache 2.0 许可）。
"""
import re

# 严重度 → 排序权重（数值越大越严重）
SEVERITY_RANK = {"low": 1, "mid": 2, "high": 3, "block": 4}
# 严重度 → 风险分
SEVERITY_SCORE = {"low": 15, "mid": 40, "high": 70, "block": 100}

# 内置种子规则（与 docs/design/sql-audit-plugin-design.md §6 对齐）
SEED_RULES = [
    {
        "id": "forbid_drop_table",
        "name": "禁止 DROP TABLE / DATABASE",
        "db_type": "all",
        "category": "forbidden",
        "severity": "block",
        "description": "生产环境禁止执行 DROP TABLE / DROP DATABASE，可能导致数据不可恢复地丢失。",
        "suggestion": "如确需删除，请走审批流程并确认已有备份；优先使用逻辑删除或重命名。",
        "logic": {"kind": "op_in", "ops": ["DROP"]},
    },
    {
        "id": "forbid_truncate",
        "name": "禁止 TRUNCATE",
        "db_type": "all",
        "category": "forbidden",
        "severity": "block",
        "description": "TRUNCATE 多数引擎下不可回滚，且会重置自增与统计信息。",
        "suggestion": "如需清空小表请走审批；大表慎用，执行前确认有备份。",
        "logic": {"kind": "op_in", "ops": ["TRUNCATE"]},
    },
    {
        "id": "dml_without_where",
        "name": "DML 缺少 WHERE 条件",
        "db_type": "all",
        "category": "forbidden",
        "severity": "high",
        "description": "UPDATE / DELETE 缺少 WHERE 会命中全表，极易引发线上事故。",
        "suggestion": "务必补充 WHERE 条件，并先用 SELECT 确认影响行数。",
        "logic": {"kind": "op_in_without_where", "ops": ["UPDATE", "DELETE"]},
    },
    {
        "id": "dml_without_limit",
        "name": "DML 缺少 LIMIT",
        "db_type": "mysql",
        "category": "performance",
        "severity": "high",
        "description": "大批量 DELETE / UPDATE 缺少 LIMIT 会长时间持锁、拖慢主库。",
        "suggestion": "分批执行并加上 LIMIT（如 LIMIT 1000），降低单次锁粒度。",
        "logic": {"kind": "op_in_without_limit", "ops": ["DELETE", "UPDATE"]},
    },
    {
        "id": "online_ddl_risk",
        "name": "在线 DDL 锁表风险",
        "db_type": "mysql",
        "category": "performance",
        "severity": "mid",
        "description": "大表 ALTER 可能锁表或造成复制延迟。",
        "suggestion": "评估表行数；优先使用 Online DDL（ALGORITHM=INPLACE）或在低峰期执行。",
        "logic": {"kind": "op_in", "ops": ["ALTER"]},
    },
    {
        "id": "select_star",
        "name": "SELECT * 投影缺失",
        "db_type": "all",
        "category": "performance",
        "severity": "low",
        "description": "SELECT * 增加 IO/网络开销，且依赖列顺序，不利于索引覆盖。",
        "suggestion": "显式列出所需列，避免 SELECT *。",
        "logic": {"kind": "select_star"},
    },
    {
        "id": "full_scan_risk",
        "name": "潜在全表扫描",
        "db_type": "all",
        "category": "performance",
        "severity": "mid",
        "description": "执行计划判定为全表扫描且无可用索引（需开启执行计划分析）。",
        "suggestion": "为过滤字段增加索引或改写查询以命中索引。",
        "logic": {"kind": "full_scan"},
    },
    {
        "id": "grant_all",
        "name": "高危授权 GRANT ALL",
        "db_type": "all",
        "category": "security",
        "severity": "high",
        "description": "GRANT ALL 授予过高权限，违反最小权限原则。",
        "suggestion": "仅授予业务所需的最小权限集合。",
        "logic": {"kind": "regex", "pattern": "GRANT\\s+ALL"},
    },
    {
        "id": "plaintext_pwd",
        "name": "明文密码出现",
        "db_type": "all",
        "category": "security",
        "severity": "mid",
        "description": "DDL / DCL 中明文出现密码存在泄露风险。",
        "suggestion": "通过参数化 / 变量传入密码，避免明文落库与审计日志。",
        "logic": {"kind": "regex", "pattern": "PASSWORD\\s*=\\s*['\"][^'\"]+['\"]"},
    },
    {
        "id": "naming_table",
        "name": "表命名不规范",
        "db_type": "all",
        "category": "naming",
        "severity": "low",
        "description": "表名不符合命名规范（建议小写字母/数字/下划线，避免关键字）。",
        "suggestion": "表名使用小写下划线命名，如 orders / user_log。",
        "logic": {"kind": "naming_table"},
    },
    {
        "id": "naming_index",
        "name": "索引命名不规范",
        "db_type": "all",
        "category": "naming",
        "severity": "low",
        "description": "索引命名非 idx_ / uk_ / pk_ 前缀。",
        "suggestion": "普通索引 idx_<表>_<列>，唯一索引 uk_<表>_<列>，主键 pk_<表>。",
        "logic": {"kind": "naming_index"},
    },
]


def _rule_applies(rule: dict, parsed: dict, db_type: str) -> bool:
    """判断单条规则是否命中某条已解析语句。"""
    if rule.get("db_type") not in ("all", None, db_type):
        return False
    logic = rule.get("logic", {})
    kind = logic.get("kind")
    op = parsed.get("op_type")
    stmt = parsed.get("sql_text", "")

    if kind == "op_in":
        return op in logic.get("ops", [])
    if kind == "op_in_without_where":
        return op in logic.get("ops", []) and not parsed.get("has_where")
    if kind == "op_in_without_limit":
        return op in logic.get("ops", []) and not parsed.get("has_limit")
    if kind == "select_star":
        return bool(parsed.get("is_select_star"))
    if kind == "full_scan":
        plan = parsed.get("plan_json") or {}
        return bool(plan.get("full_table_scan"))
    if kind == "regex":
        return bool(re.search(logic.get("pattern", ""), stmt, re.I))
    if kind == "naming_table":
        if op in ("CREATE", "ALTER"):
            for t in parsed.get("tables", []):
                if not re.fullmatch(r"[a-z][a-z0-9_]*", t):
                    return True
        return False
    if kind == "naming_index":
        m = re.search(
            r"\b(?:CREATE\s+INDEX|ADD\s+(?:UNIQUE\s+)?INDEX)\s+([`\"]?[A-Za-z0-9_]+[`\"]?)",
            stmt, re.I,
        )
        if not m:
            return False
        name = m.group(1).strip("`\"")
        return not (name.startswith("idx_") or name.startswith("uk_") or name.startswith("pk_"))
    return False


def score_hits(hits: list):
    """根据命中规则计算（risk_score, risk_level）。无命中返回 (0, 'low')。"""
    if not hits:
        return 0, "low"
    worst = max(hits, key=lambda h: SEVERITY_RANK.get(h["severity"], 0))
    return SEVERITY_SCORE.get(worst["severity"], 0), worst["severity"]
