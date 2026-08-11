# -*- coding: utf-8 -*-
# SPDX-License-Identifier: Apache-2.0
# Copyright 2025-2026 fiyo (Jack Ge) <sdfiyon@gmail.com>
# Author: fiyo (Jack Ge) - https://github.com/fiyo/DBCheck

"""SQL 审核编排层（service）。

串联 parser → rules → models，完成一次审核任务的：
  1. 切分并解析 SQL 为多条语句
  2. 对每条语句运行启用规则，收集命中与单句风险
  3. 聚合任务级风险
  4. 落库（sql_audit_tasks / sql_audit_items）并返回完整报告

MVP1：只读分析，不连接目标库、不执行、不做执行计划分析。
"""
import json

from . import models
from .parser import split_statements, analyze_statement
from .rules import SEVERITY_RANK, score_hits


def submit_audit(
    submitter: str,
    instance_id,
    db_type: str,
    env: str,
    sql_text: str,
    plan_enabled: bool = False,
    exec_enabled: bool = False,
    remark: str = "",
) -> dict:
    """提交并立即完成一次 SQL 审核，返回任务详情（含 items）。"""
    models.init_db()
    stmts = split_statements(sql_text)
    if not stmts:
        raise ValueError("未解析到有效 SQL 语句")

    rules = models.get_enabled_rules(db_type)
    items = []
    task_score = 0
    task_level = "low"

    for seq, stmt in enumerate(stmts, 1):
        parsed = analyze_statement(stmt)
        hits = []
        for r in rules:
            if _applies(r, parsed, db_type):
                hits.append({
                    "rule_id": r["rule_id"],
                    "name": r["name"],
                    "category": r["category"],
                    "severity": r["severity"],
                    "message": r.get("description", ""),
                    "suggestion": r.get("suggestion", ""),
                })
        score, level = score_hits(hits)
        if SEVERITY_RANK.get(level, 0) > SEVERITY_RANK.get(task_level, 0):
            task_level = level
        if score > task_score:
            task_score = score
        items.append({**parsed, "seq": seq, "risk_score": score, "risk_level": level, "rule_hits": hits})

    conn = models.get_conn()
    cur = conn.cursor()
    now = models._now()
    task_no = models.gen_task_no()
    cur.execute(
        "INSERT INTO sql_audit_tasks "
        "(task_no, submitter, instance_id, env, db_type, sql_text, sql_count, status, "
        " risk_level, risk_score, plan_enabled, exec_enabled, created_at, updated_at, remark) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (
            task_no, submitter, instance_id, env, db_type, sql_text, len(stmts),
            "analyzed", task_level, task_score,
            1 if plan_enabled else 0, 1 if exec_enabled else 0,
            now, now, remark,
        ),
    )
    task_id = cur.lastrowid
    for it in items:
        cur.execute(
            "INSERT INTO sql_audit_items "
            "(task_id, seq, sql_text, sql_type, op_type, tables_json, risk_level, risk_score, rule_hits, created_at) "
            "VALUES (?,?,?,?,?,?,?,?,?,?)",
            (
                task_id, it["seq"], it["sql_text"], it["sql_type"], it["op_type"],
                json.dumps(it["tables"], ensure_ascii=False),
                it["risk_level"], it["risk_score"],
                json.dumps(it["rule_hits"], ensure_ascii=False), now,
            ),
        )
    conn.commit()
    conn.close()
    return get_task(task_id)


def _applies(rule: dict, parsed: dict, db_type: str) -> bool:
    # 复用 rules.py 的匹配逻辑；此处转发，便于后续扩展（如缓存/调试）。
    from .rules import _rule_applies
    return _rule_applies(rule, parsed, db_type)


def get_task(task_id: int) -> dict:
    models.init_db()
    conn = models.get_conn()
    cur = conn.cursor()
    cur.execute("SELECT * FROM sql_audit_tasks WHERE id=?", (task_id,))
    row = cur.fetchone()
    if not row:
        conn.close()
        return None
    task = dict(row)
    cur.execute("SELECT * FROM sql_audit_items WHERE task_id=? ORDER BY seq", (task_id,))
    items = []
    for r in cur.fetchall():
        it = dict(r)
        # TEXT 列反序列化为结构化对象，方便前端直接使用
        if isinstance(it.get("rule_hits"), str) and it["rule_hits"]:
            try:
                it["rule_hits"] = json.loads(it["rule_hits"])
            except Exception:
                it["rule_hits"] = []
        elif not it.get("rule_hits"):
            it["rule_hits"] = []
        if isinstance(it.get("tables_json"), str) and it["tables_json"]:
            try:
                it["tables"] = json.loads(it["tables_json"])
            except Exception:
                it["tables"] = []
        elif not it.get("tables_json"):
            it["tables"] = []
        items.append(it)
    task["items"] = items
    conn.close()
    return task


def list_tasks(submitter: str = None, status: str = None, limit: int = 100) -> list:
    models.init_db()
    conn = models.get_conn()
    cur = conn.cursor()
    sql = ("SELECT id, task_no, submitter, instance_id, env, db_type, sql_count, status, "
           "risk_level, risk_score, created_at FROM sql_audit_tasks")
    where, params = [], []
    if submitter:
        where.append("submitter=?")
        params.append(submitter)
    if status:
        where.append("status=?")
        params.append(status)
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY id DESC LIMIT ?"
    params.append(limit)
    cur.execute(sql, params)
    rows = [dict(r) for r in cur.fetchall()]
    conn.close()
    return rows


def list_rules() -> list:
    """返回全部审核规则（含 logic 解析）。"""
    return models.list_rules()
