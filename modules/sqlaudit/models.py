# -*- coding: utf-8 -*-
# SPDX-License-Identifier: Apache-2.0
# Copyright 2025-2026 fiyo (Jack Ge) <sdfiyon@gmail.com>
# Author: fiyo (Jack Ge) - https://github.com/fiyo/DBCheck

"""SQL 审核数据模型（SQLite，库位于 data/sql_audit.db）。

不依赖 ORM，使用标准 sqlite3，与项目其余数据层保持一致；路径使用
modules.core.paths.DATA_DIR，不通过 __file__ 上溯取项目根。
"""
import json
import os
import sqlite3
from datetime import datetime, timezone

from modules.core import paths
from .rules import SEED_RULES

DB_PATH = os.path.join(str(paths.DATA_DIR), "sql_audit.db")

SCHEMA = """
CREATE TABLE IF NOT EXISTS sql_audit_tasks (
    id            INTEGER PRIMARY KEY,
    task_no       TEXT    NOT NULL UNIQUE,
    submitter     TEXT    NOT NULL,
    instance_id   TEXT,
    env           TEXT    NOT NULL DEFAULT 'prod',
    db_type       TEXT    NOT NULL DEFAULT 'mysql',
    sql_text      TEXT    NOT NULL,
    sql_count     INTEGER NOT NULL DEFAULT 1,
    status        TEXT    NOT NULL DEFAULT 'analyzed',
    risk_level    TEXT    NOT NULL DEFAULT 'low',
    risk_score    INTEGER NOT NULL DEFAULT 0,
    plan_enabled  INTEGER NOT NULL DEFAULT 0,
    exec_enabled  INTEGER NOT NULL DEFAULT 0,
    created_at    TEXT    NOT NULL,
    updated_at    TEXT    NOT NULL,
    remark        TEXT
);
CREATE INDEX IF NOT EXISTS idx_sat_status    ON sql_audit_tasks(status);
CREATE INDEX IF NOT EXISTS idx_sat_submitter ON sql_audit_tasks(submitter);
CREATE INDEX IF NOT EXISTS idx_sat_instance  ON sql_audit_tasks(instance_id);

CREATE TABLE IF NOT EXISTS sql_audit_items (
    id           INTEGER PRIMARY KEY,
    task_id      INTEGER NOT NULL,
    seq          INTEGER NOT NULL,
    sql_text     TEXT    NOT NULL,
    sql_type     TEXT,
    op_type      TEXT,
    tables_json  TEXT,
    risk_level   TEXT    NOT NULL DEFAULT 'low',
    risk_score   INTEGER NOT NULL DEFAULT 0,
    rule_hits    TEXT,
    plan_json    TEXT,                            -- JSON: 执行计划分析结果(MVP2)
    created_at   TEXT    NOT NULL,
    FOREIGN KEY (task_id) REFERENCES sql_audit_tasks(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_sai_task ON sql_audit_items(task_id);

CREATE TABLE IF NOT EXISTS sql_audit_rules (
    id          INTEGER PRIMARY KEY,
    rule_id     TEXT    NOT NULL UNIQUE,
    name        TEXT    NOT NULL,
    db_type     TEXT    NOT NULL DEFAULT 'all',
    category    TEXT    NOT NULL,
    severity    TEXT    NOT NULL,
    logic       TEXT    NOT NULL,
    enabled     INTEGER NOT NULL DEFAULT 1,
    description TEXT,
    suggestion  TEXT,
    created_at  TEXT    NOT NULL,
    updated_at  TEXT    NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_sar_rule ON sql_audit_rules(rule_id);

-- 以下三张表为 MVP3/MVP4（审批 / 执行 / 回滚）预留，MVP1 仅建表不写入。
CREATE TABLE IF NOT EXISTS sql_audit_approvals (
    id         INTEGER PRIMARY KEY,
    task_id    INTEGER NOT NULL,
    approver   TEXT    NOT NULL,
    action     TEXT    NOT NULL,
    comment    TEXT,
    created_at TEXT    NOT NULL,
    FOREIGN KEY (task_id) REFERENCES sql_audit_tasks(id) ON DELETE CASCADE
);
CREATE TABLE IF NOT EXISTS sql_audit_executions (
    id           INTEGER PRIMARY KEY,
    task_id      INTEGER NOT NULL,
    item_id      INTEGER,
    mode         TEXT    NOT NULL,
    executed_sql TEXT,
    affected_rows INTEGER,
    started_at   TEXT,
    finished_at  TEXT,
    status       TEXT    NOT NULL,
    error        TEXT,
    FOREIGN KEY (task_id) REFERENCES sql_audit_tasks(id) ON DELETE CASCADE
);
CREATE TABLE IF NOT EXISTS sql_audit_rollbacks (
    id           INTEGER PRIMARY KEY,
    task_id      INTEGER NOT NULL,
    item_id      INTEGER,
    rollback_sql TEXT,
    backup_ref   TEXT,
    auto_rollback INTEGER NOT NULL DEFAULT 0,
    note         TEXT,
    created_at   TEXT    NOT NULL,
    FOREIGN KEY (task_id) REFERENCES sql_audit_tasks(id) ON DELETE CASCADE
);
"""


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def get_conn() -> sqlite3.Connection:
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    # SQLite 默认关闭外键约束，必须每连接显式开启，sql_audit_items 的
    # ON DELETE CASCADE（任务删除级联清明细）才会真正生效。
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def _ensure_column(conn: sqlite3.Connection, table: str, column: str, coltype: str) -> None:
    """幂等补齐缺失列（老库升级用）。

    通过 PRAGMA table_info 探测列是否存在，不存在才 ALTER，避免重复加列报错。
    """
    cur = conn.cursor()
    cur.execute(f"PRAGMA table_info({table})")
    existing = {row[1] for row in cur.fetchall()}
    if column not in existing:
        cur.execute(f"ALTER TABLE {table} ADD COLUMN {column} {coltype}")
        conn.commit()


def init_db() -> None:
    """初始化库表并写入内置规则种子（仅当规则表为空时）。"""
    conn = get_conn()
    conn.executescript(SCHEMA)
    # MVP2 幂等补齐：老库可能缺 plan_json 列，这里按需 ALTER（PRAGMA 探测避免重复加列）。
    _ensure_column(conn, "sql_audit_items", "plan_json", "TEXT")
    # MVP3 幂等补齐：任务表补审批/执行留痕列（设计文档 §5.1，老库升级用）。
    _ensure_column(conn, "sql_audit_tasks", "approved_by", "TEXT")
    _ensure_column(conn, "sql_audit_tasks", "approved_at", "TEXT")
    _ensure_column(conn, "sql_audit_tasks", "executed_at", "TEXT")
    _ensure_column(conn, "sql_audit_rollbacks", "note", "TEXT")
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM sql_audit_rules")
    if cur.fetchone()[0] == 0:
        now = _now()
        for r in SEED_RULES:
            cur.execute(
                "INSERT INTO sql_audit_rules "
                "(rule_id, name, db_type, category, severity, logic, enabled, description, suggestion, created_at, updated_at) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (
                    r["id"], r["name"], r["db_type"], r["category"], r["severity"],
                    json.dumps(r["logic"], ensure_ascii=False), 1,
                    r.get("description", ""), r.get("suggestion", ""),
                    now, now,
                ),
            )
    conn.commit()
    conn.close()


def gen_task_no() -> str:
    """生成任务号 SA-YYYYMMDD-NNNN。"""
    datepart = datetime.now().strftime("%Y%m%d")
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM sql_audit_tasks WHERE task_no LIKE ?", (f"SA-{datepart}-%",))
    cnt = cur.fetchone()[0] + 1
    conn.close()
    return f"SA-{datepart}-{cnt:04d}"


def delete_task(task_id: int) -> int:
    """删除单个审核任务；其明细通过 ON DELETE CASCADE 级联删除。

    返回被删除的任务行数（0 表示任务不存在）。
    """
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("DELETE FROM sql_audit_tasks WHERE id=?", (task_id,))
    n = cur.rowcount
    conn.commit()
    conn.close()
    return n


def get_enabled_rules(db_type: str) -> list:
    """返回对给定库型启用且适用的规则（logic 解析为 dict）。"""
    init_db()
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT * FROM sql_audit_rules WHERE enabled=1")
    rows = [dict(r) for r in cur.fetchall()]
    conn.close()
    out = []
    for r in rows:
        if r["db_type"] not in ("all", db_type):
            continue
        r["logic"] = json.loads(r["logic"]) if r["logic"] else {}
        out.append(r)
    return out


def list_rules() -> list:
    init_db()
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT * FROM sql_audit_rules ORDER BY id")
    rows = [dict(r) for r in cur.fetchall()]
    conn.close()
    for r in rows:
        r["logic"] = json.loads(r["logic"]) if r["logic"] else {}
    return rows


# ─────────────────────────────────────────────────────────────────────────────
# MVP3：执行记录 / 回滚备援 写入与查询（表结构已在 SCHEMA 中建好，此处补读写）
# ─────────────────────────────────────────────────────────────────────────────

def insert_execution(task_id: int, item_id, mode: str, executed_sql, affected_rows,
                      status: str, started_at: str, finished_at: str, error=None) -> int:
    """写入一条执行记录，返回新行 id。"""
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO sql_audit_executions "
        "(task_id, item_id, mode, executed_sql, affected_rows, started_at, finished_at, status, error) "
        "VALUES (?,?,?,?,?,?,?,?,?)",
        (task_id, item_id, mode, executed_sql, affected_rows, started_at, finished_at, status, error),
    )
    rid = cur.lastrowid
    conn.commit()
    conn.close()
    return rid


def insert_rollback(task_id: int, item_id, rollback_sql, backup_ref, auto_rollback: bool,
                    created_at: str, note: str = None) -> int:
    """写入一条回滚备援记录，返回新行 id。"""
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO sql_audit_rollbacks "
        "(task_id, item_id, rollback_sql, backup_ref, auto_rollback, note, created_at) "
        "VALUES (?,?,?,?,?,?,?)",
        (task_id, item_id, rollback_sql, backup_ref, 1 if auto_rollback else 0,
         note, created_at),
    )
    rid = cur.lastrowid
    conn.commit()
    conn.close()
    return rid


def get_executions(task_id: int) -> list:
    """返回某任务的全部执行记录（按 id 升序）。"""
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT * FROM sql_audit_executions WHERE task_id=? ORDER BY id", (task_id,))
    rows = [dict(r) for r in cur.fetchall()]
    conn.close()
    return rows


def get_rollbacks(task_id: int) -> list:
    """返回某任务的全部回滚备援记录（按 id 升序）。"""
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT * FROM sql_audit_rollbacks WHERE task_id=? ORDER BY id", (task_id,))
    rows = [dict(r) for r in cur.fetchall()]
    conn.close()
    return rows


# ─────────────────────────────────────────────────────────────────────────────
# MVP3 审批流：审批记录写入与查询（表结构已在 SCHEMA 中建好，此处补读写）
# ─────────────────────────────────────────────────────────────────────────────

def insert_approval(task_id: int, approver: str, action: str, comment: str = None) -> int:
    """写入一条审批记录，返回新行 id。action: approve / reject。"""
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO sql_audit_approvals (task_id, approver, action, comment, created_at) "
        "VALUES (?,?,?,?,?)",
        (task_id, approver, action, comment, _now()),
    )
    rid = cur.lastrowid
    conn.commit()
    conn.close()
    return rid


def get_approvals(task_id: int) -> list:
    """返回某任务的全部审批记录（按 id 升序）。"""
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT * FROM sql_audit_approvals WHERE task_id=? ORDER BY id", (task_id,))
    rows = [dict(r) for r in cur.fetchall()]
    conn.close()
    return rows


def update_task_status(task_id: int, status: str, **fields) -> None:
    """更新任务状态及可选留痕字段（approved_by/approved_at/executed_at/remark）。"""
    allowed = {"approved_by", "approved_at", "executed_at", "remark"}
    sets = ["status=?", "updated_at=?"]
    params = [status, _now()]
    for k, v in fields.items():
        if k in allowed:
            sets.append(f"{k}=?")
            params.append(v)
    params.append(task_id)
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(f"UPDATE sql_audit_tasks SET {', '.join(sets)} WHERE id=?", params)
    conn.commit()
    conn.close()


def update_task_instance(task_id: int, instance_id: str) -> None:
    """为已提交任务补充/更正目标实例（用于执行前发现未指定实例时）。"""
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        "UPDATE sql_audit_tasks SET instance_id=?, updated_at=? WHERE id=?",
        (instance_id, _now(), task_id),
    )
    conn.commit()
    conn.close()


# ─────────────────────────────────────────────────────────────────────────────
# MVP3.5：规则在线 CRUD（运维自调规则，无需改种子代码）
# 业务标识用 rule_id（与种子规则一致），主键 id 自增；CRUD 均以 rule_id 定位。
# ─────────────────────────────────────────────────────────────────────────────

def get_rule(rule_id: str) -> dict:
    """按 rule_id 查询单条规则（logic 解析为 dict），不存在返回 None。"""
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT * FROM sql_audit_rules WHERE rule_id=?", (rule_id,))
    row = cur.fetchone()
    conn.close()
    if not row:
        return None
    r = dict(row)
    r["logic"] = json.loads(r["logic"]) if r["logic"] else {}
    return r


def insert_rule(rule_id: str, name: str, db_type: str, category: str,
                severity: str, logic: dict, enabled: bool = True,
                description: str = "", suggestion: str = "") -> int:
    """写入一条规则，返回新行 id。rule_id 调用方需保证唯一。"""
    conn = get_conn()
    cur = conn.cursor()
    now = _now()
    cur.execute(
        "INSERT INTO sql_audit_rules "
        "(rule_id, name, db_type, category, severity, logic, enabled, description, suggestion, created_at, updated_at) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
        (rule_id, name, db_type, category, severity,
         json.dumps(logic, ensure_ascii=False), 1 if enabled else 0,
         description, suggestion, now, now),
    )
    rid = cur.lastrowid
    conn.commit()
    conn.close()
    return rid


def update_rule(rule_id: str, **fields) -> int:
    """按 rule_id 更新规则字段（白名单过滤）。返回被更新行数。"""
    allowed = {"name", "db_type", "category", "severity", "logic", "enabled",
               "description", "suggestion"}
    sets, params = [], []
    for k, v in fields.items():
        if k not in allowed or v is None:
            continue
        if k == "logic":
            v = json.dumps(v, ensure_ascii=False)
        if k == "enabled":
            v = 1 if v else 0
        sets.append(f"{k}=?")
        params.append(v)
    if not sets:
        return 0
    sets.append("updated_at=?")
    params.append(_now())
    params.append(rule_id)
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(f"UPDATE sql_audit_rules SET {', '.join(sets)} WHERE rule_id=?", params)
    n = cur.rowcount
    conn.commit()
    conn.close()
    return n


def delete_rule(rule_id: str) -> int:
    """按 rule_id 删除规则，返回被删除行数。"""
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("DELETE FROM sql_audit_rules WHERE rule_id=?", (rule_id,))
    n = cur.rowcount
    conn.commit()
    conn.close()
    return n
