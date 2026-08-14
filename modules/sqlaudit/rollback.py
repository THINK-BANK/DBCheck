# -*- coding: utf-8 -*-
# SPDX-License-Identifier: Apache-2.0
# Copyright 2025-2026 fiyo (Jack Ge) <sdfiyon@gmail.com>
# Author: fiyo (Jack Ge) - https://github.com/fiyo/DBCheck

"""SQL 审核回滚 SQL 生成器（MVP3）。

依据设计文档 §8 回滚策略，为单条语句生成回滚/复原方案：
  - INSERT  → DELETE（按插入值反查删除，可自动回滚）
  - UPDATE  → 反向 SET（依赖执行前原值快照，可自动回滚）
  - DELETE  → INSERT 原行复原（依赖执行前原行快照，可自动回滚）
  - DDL     → 反向 DDL 建议（CREATE→DROP / ADD COLUMN→DROP COLUMN / RENAME 还原；
              DROP/TRUNCATE/DROP COLUMN 不可自动回滚，仅给建议）
  - TRUNCATE→ 提示依赖备份

本模块为「纯函数 + 字符串生成」，不连接数据库、不依赖第三方 SQL parser；
快照数据由 executor 在执行前采集后传入。所有生成语句均为「建议级」，
真实回滚前应由人工核对，尤其是缺少唯一键定位的场景。
"""
import re

from .parser import classify_statement, _strip_comments


# ── 基础工具 ─────────────────────────────────────────────────────────────────

def _clean(ident: str) -> str:
    """去掉反引号/双引号/库名前缀，返回裸标识符。"""
    s = (ident or "").strip()
    s = s.strip("`").strip('"').strip()
    if "." in s:
        s = s.split(".", 1)[1]
    return s


def _split_top_level(s: str) -> list:
    """在括号深度 0 处按逗号切分（用于切分 VALUES 元组 / 列列表）。"""
    parts, buf, depth = [], [], 0
    for ch in s:
        if ch == "(":
            depth += 1; buf.append(ch)
        elif ch == ")":
            depth -= 1; buf.append(ch)
        elif ch == "," and depth == 0:
            parts.append("".join(buf)); buf = []
        else:
            buf.append(ch)
    if buf:
        parts.append("".join(buf))
    return [p.strip() for p in parts if p.strip()]


def _num(s: str):
    try:
        return float(s) if "." in s else int(s)
    except ValueError:
        return s


def _fmt_val(v, db_type: str) -> str:
    """将 Python 值格式化为 SQL 字面量。"""
    if v is None:
        return "NULL"
    if isinstance(v, bool):
        return "1" if v else "0"
    if isinstance(v, (int, float)):
        return str(v)
    # Decimal / datetime 等转为字符串并加引号
    s = str(v)
    s = s.replace("'", "''")
    return f"'{s}'"


def _parse_tuple_values(tup: str):
    """解析一个 VALUES 元组字符串为 Python 值列表；含非字面量（函数/表达式）返回 None。"""
    t = tup.strip()
    if t.startswith("("):
        t = t[1:]
    if t.endswith(")"):
        t = t[:-1]
    parts = _split_top_level(t)
    vals = []
    for p in parts:
        p = p.strip()
        if p.upper() == "NULL":
            vals.append(None)
            continue
        if re.match(r"^[+-]?\d+(\.\d+)?$", p):
            vals.append(_num(p))
            continue
        if len(p) >= 2 and ((p[0] == "'" and p[-1] == "'") or (p[0] == '"' and p[-1] == '"')):
            inner = p[1:-1]
            inner = inner.replace("''", "'") if p[0] == "'" else inner.replace('""', '"')
            vals.append(inner)
            continue
        # 函数调用 / 表达式 / DEFAULT 等非字面量 → 无法精确回滚
        return None
    return vals


def _parse_insert(stmt: str):
    """解析 INSERT/REPLACE：返回 (table, [cols], [value_tuples])；无法解析返回 None。"""
    m = re.match(
        r"\s*(?:INSERT|REPLACE)\s+(?:\w+\s+)?INTO\s+([`\"]?[A-Za-z0-9_$.]+[`\"]?)\s*"
        r"(?:\(([^)]*)\))?\s*VALUES\s*(.*)$",
        stmt, re.I | re.S,
    )
    if not m:
        return None
    table = _clean(m.group(1))
    cols = [_clean(c) for c in m.group(2).split(",")] if m.group(2) else []
    values_part = m.group(3).strip().rstrip(";").strip()
    tuples = _split_top_level(values_part)
    return table, cols, tuples


# ── 各操作回滚方案 ───────────────────────────────────────────────────────────

def _rb_insert(stmt: str, db_type: str, base: dict) -> dict:
    parsed = _parse_insert(stmt)
    if not parsed:
        base["note"] = "无法解析的 INSERT，回滚需依赖执行前备份"
        return base
    table, cols, tuples = parsed
    if not cols:
        base["note"] = "INSERT 未指定列列表，无法生成精确回滚，需依赖备份"
        return base
    deletes = []
    for tup in tuples:
        vals = _parse_tuple_values(tup)
        if vals is None or len(vals) != len(cols):
            base["note"] = "INSERT 含非字面量值（函数/子查询/DEFAULT），无法生成精确 DELETE 回滚，需依赖备份"
            base["auto_rollback"] = False
            return base
        conds = " AND ".join(f"{c}={_fmt_val(v, db_type)}" for c, v in zip(cols, vals))
        deletes.append(f"DELETE FROM {table} WHERE {conds}")
    base["rollback_sql"] = ";\n".join(deletes)
    base["auto_rollback"] = True
    base["strategy"] = "INSERT→DELETE（按插入值反查删除）"
    return base


def _rb_update(stmt: str, db_type: str, snapshot: dict, base: dict) -> dict:
    if not snapshot or not snapshot.get("rows"):
        base["note"] = "缺少执行前原值快照，无法生成 UPDATE 反向回滚（请在执行前开启快照/备份）"
        return base
    table = snapshot["table"]
    cols = snapshot["columns"]
    rows = snapshot["rows"]
    stmts = []
    for row in rows:
        set_clause = ", ".join(f"{c}={_fmt_val(v, db_type)}" for c, v in zip(cols, row))
        where_clause = " AND ".join(f"{c}={_fmt_val(v, db_type)}" for c, v in zip(cols, row))
        stmts.append(f"UPDATE {table} SET {set_clause} WHERE {where_clause}")
    base["rollback_sql"] = ";\n".join(stmts)
    base["auto_rollback"] = True
    base["strategy"] = "UPDATE→反向 SET（依赖执行前原值快照）"
    base["backup_ref"] = snapshot.get("backup_table")
    base["note"] = "回滚以全列等值定位原行，假设目标行可唯一定位；如存在非唯一行请人工核对"
    return base


def _rb_delete(stmt: str, db_type: str, snapshot: dict, base: dict) -> dict:
    if not snapshot or not snapshot.get("rows"):
        base["note"] = "缺少执行前原行快照，无法复原 DELETE 数据（请在执行前开启快照/备份）"
        return base
    table = snapshot["table"]
    cols = snapshot["columns"]
    rows = snapshot["rows"]
    col_list = ", ".join(cols)
    val_rows = ", ".join("(" + ", ".join(_fmt_val(v, db_type) for v in row) + ")" for row in rows)
    base["rollback_sql"] = f"INSERT INTO {table} ({col_list}) VALUES {val_rows}"
    base["auto_rollback"] = True
    base["strategy"] = "DELETE→INSERT 原行复原（依赖执行前原行快照）"
    base["backup_ref"] = snapshot.get("backup_table")
    return base


def _rb_ddl(stmt: str, db_type: str, op_type: str, base: dict) -> dict:
    base["strategy"] = "DDL 反向建议（不可自动回滚）"
    base["auto_rollback"] = False
    if op_type == "CREATE":
        m = re.search(
            r"CREATE\s+(?:TEMPORARY\s+)?TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?([`\"]?[A-Za-z0-9_$.]+[`\"]?)",
            stmt, re.I,
        )
        t = _clean(m.group(1)) if m else "unknown_table"
        base["rollback_sql"] = f"DROP TABLE {t};"
        base["note"] = "CREATE TABLE 的回滚为 DROP TABLE；若表已写入数据将一并丢失，请确认"
        return base
    if op_type == "DROP":
        m = re.search(r"DROP\s+TABLE\s+(?:IF\s+EXISTS\s+)?([`\"]?[A-Za-z0-9_$.]+[`\"]?)", stmt, re.I)
        t = _clean(m.group(1)) if m else "unknown_table"
        base["note"] = f"DROP TABLE {t} 不可自动回滚，需从备份/版本库重建原表结构与数据"
        return base
    if op_type == "TRUNCATE":
        m = re.search(r"TRUNCATE\s+(?:TABLE\s+)?([`\"]?[A-Za-z0-9_$.]+[`\"]?)", stmt, re.I)
        t = _clean(m.group(1)) if m else "unknown_table"
        base["note"] = f"TRUNCATE {t} 不可自动回滚，需从备份恢复全表数据"
        return base
    if op_type == "RENAME":
        m = re.search(
            r"RENAME\s+TABLE\s+([`\"]?[A-Za-z0-9_$.]+[`\"]?)\s+TO\s+([`\"]?[A-Za-z0-9_$.]+[`\"]?)",
            stmt, re.I,
        )
        if m:
            a, b = _clean(m.group(1)), _clean(m.group(2))
            base["rollback_sql"] = f"RENAME TABLE {b} TO {a};"
            base["note"] = "RENAME 反向为还原表名"
            return base
        base["note"] = "RENAME 无法解析，需人工处理"
        return base
    if op_type == "ALTER":
        m_add = re.search(
            r"ALTER\s+TABLE\s+([`\"]?[A-Za-z0-9_$.]+[`\"]?)\s+ADD\s+(?:COLUMN\s+)?([`\"]?[A-Za-z0-9_]+[`\"]?)",
            stmt, re.I,
        )
        if m_add:
            t, c = _clean(m_add.group(1)), _clean(m_add.group(2))
            base["rollback_sql"] = f"ALTER TABLE {t} DROP COLUMN {c};"
            base["note"] = "ALTER ADD COLUMN 的回滚为 DROP COLUMN（数据列一并删除）"
            return base
        m_drop = re.search(
            r"ALTER\s+TABLE\s+([`\"]?[A-Za-z0-9_$.]+[`\"]?)\s+DROP\s+(?:COLUMN\s+)?([`\"]?[A-Za-z0-9_]+[`\"]?)",
            stmt, re.I,
        )
        if m_drop:
            t, c = _clean(m_drop.group(1)), _clean(m_drop.group(2))
            base["note"] = (f"ALTER DROP COLUMN {c} 不可自动回滚，"
                            f"需 ALTER TABLE {t} ADD COLUMN {c} <原类型> 恢复（原类型未知）")
            return base
        base["note"] = "ALTER 语句无法自动解析回滚，请人工评估反向 DDL"
        return base
    base["note"] = f"{op_type} 暂不支持自动回滚方案生成"
    return base


# ── 入口 ─────────────────────────────────────────────────────────────────────

def generate_rollback_plan(stmt: str, db_type: str = "mysql", snapshot: dict = None) -> dict:
    """为单条语句生成回滚方案。

    参数:
      stmt     — 原始 SQL（可含注释/多条由调用方已切分）
      db_type  — 规范库型（mysql/postgresql/oracle/sqlserver/dm）
      snapshot — 执行前快照（UPDATE/DELETE 用），结构:
                  {"table","columns":[...],"rows":[[...],...],"where","backup_table"}
    返回:
      {"op_type","strategy","auto_rollback":bool,"rollback_sql":str|None,
       "backup_ref":str|None,"note":str}
    """
    stmt_clean = _strip_comments(stmt).strip().rstrip(";").strip()
    _sql_type, op_type = classify_statement(stmt_clean)
    base = {
        "op_type": op_type,
        "strategy": "",
        "auto_rollback": False,
        "rollback_sql": None,
        "backup_ref": None,
        "note": "",
    }
    if op_type in ("INSERT", "REPLACE"):
        return _rb_insert(stmt_clean, db_type, base)
    if op_type == "UPDATE":
        return _rb_update(stmt_clean, db_type, snapshot, base)
    if op_type == "DELETE":
        return _rb_delete(stmt_clean, db_type, snapshot, base)
    if op_type in ("CREATE", "ALTER", "DROP", "TRUNCATE", "RENAME"):
        return _rb_ddl(stmt_clean, db_type, op_type, base)
    base["note"] = f"{op_type} 语句暂不支持自动回滚方案生成"
    return base
