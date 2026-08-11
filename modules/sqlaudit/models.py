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
    return conn


def init_db() -> None:
    """初始化库表并写入内置规则种子（仅当规则表为空时）。"""
    conn = get_conn()
    conn.executescript(SCHEMA)
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
