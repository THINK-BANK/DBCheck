# -*- coding: utf-8 -*-
# SPDX-License-Identifier: Apache-2.0
# Copyright 2025-2026 fiyo (Jack Ge) <sdfiyon@gmail.com>
# Author: fiyo (Jack Ge) - https://github.com/fiyo/DBCheck

"""SQL 解析工具（方言无关的轻量实现，不依赖第三方 SQL parser）。

MVP1 聚焦 MySQL；解析结果（语句类型 / 操作类型 / 涉及表 / 是否含 WHERE 等）
供审核规则匹配使用。后续多库方言扩展时，可在此增加方言特化解析分支。
"""
import re

_COMMENT_BLOCK = re.compile(r"/\*.*?\*/", re.S)
_COMMENT_LINE = re.compile(r"(--[^\n]*|#[^\n]*)")

_LEAD = re.compile(r"^\s*(?:LOCK\s+TABLES\s+)?([A-Za-z]+)", re.I)

# 识别的语句大类与操作类型
_DDL = {"CREATE", "ALTER", "DROP", "TRUNCATE", "RENAME"}
_DML = {"INSERT", "UPDATE", "DELETE", "REPLACE", "MERGE"}
_DQL = {"SELECT", "SHOW", "WITH", "DESC", "DESCRIBE", "EXPLAIN"}
_DCL = {"GRANT", "REVOKE"}

_IDENT = r"(?:`[^`]+`|[\w$]+)(?:\.(?:`[^`]+`|[\w$]+))?"
_TABLE_PATTERNS = [
    (re.compile(r"\bFROM\s+(" + _IDENT + r")", re.I), 1),
    (re.compile(r"\bJOIN\s+(" + _IDENT + r")", re.I), 1),
    (re.compile(r"\bUPDATE\s+(" + _IDENT + r")", re.I), 1),
    (re.compile(r"\bINSERT\s+(?:INTO\s+)?(" + _IDENT + r")", re.I), 1),
    (re.compile(r"\bDELETE\s+FROM\s+(" + _IDENT + r")", re.I), 1),
    (re.compile(r"\bCREATE\s+(?:TEMPORARY\s+)?TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?(" + _IDENT + r")", re.I), 1),
    (re.compile(r"\bDROP\s+TABLE\s+(?:IF\s+EXISTS\s+)?(" + _IDENT + r")", re.I), 1),
    (re.compile(r"\bALTER\s+TABLE\s+(" + _IDENT + r")", re.I), 1),
    (re.compile(r"\bTRUNCATE\s+(?:TABLE\s+)?(" + _IDENT + r")", re.I), 1),
]


def _strip_comments(sql: str) -> str:
    sql = _COMMENT_BLOCK.sub(" ", sql)
    sql = _COMMENT_LINE.sub(" ", sql)
    return sql


def split_statements(sql_text: str) -> list:
    """按分号切分多条语句，尊重单/双引号与注释。

    返回去除首尾空白的非空语句列表。
    """
    if not sql_text:
        return []
    cleaned = _strip_comments(sql_text)
    statements = []
    buf = []
    in_single = in_double = False
    for ch in cleaned:
        if ch == "'" and not in_double:
            in_single = not in_single
            buf.append(ch)
        elif ch == '"' and not in_single:
            in_double = not in_double
            buf.append(ch)
        elif ch == ";" and not in_single and not in_double:
            stmt = "".join(buf).strip()
            if stmt:
                statements.append(stmt)
            buf = []
        else:
            buf.append(ch)
    tail = "".join(buf).strip()
    if tail:
        statements.append(tail)
    return statements


def classify_statement(stmt: str):
    """返回 (sql_type, op_type)。

    sql_type ∈ {DDL, DML, DQL, DCL, OTHER}
    op_type  ∈ {CREATE, ALTER, DROP, TRUNCATE, INSERT, UPDATE, DELETE, SELECT, GRANT, ...}
    """
    m = _LEAD.match(stmt)
    if not m:
        return ("OTHER", "UNKNOWN")
    kw = m.group(1).upper()
    if kw in _DDL:
        return ("DDL", kw)
    if kw in _DML:
        return ("DML", kw)
    if kw in _DQL:
        return ("DQL", kw)
    if kw in _DCL:
        return ("DCL", kw)
    return ("OTHER", kw)


def _clean_ident(s: str) -> str:
    return s.strip().strip("`").strip('"').strip()


def extract_tables(stmt: str) -> list:
    """从语句中提取涉及的表名（去重，保持出现顺序）。"""
    out = []
    for rx, grp in _TABLE_PATTERNS:
        for m in rx.finditer(stmt):
            t = _clean_ident(m.group(grp))
            if t and t.upper() not in ("IF", "NOT", "EXISTS", "TEMPORARY", "TABLE"):
                if t not in out:
                    out.append(t)
    return out


def analyze_statement(stmt: str) -> dict:
    """将单条语句解析为供规则匹配使用的结构化字典。"""
    sql_type, op_type = classify_statement(stmt)
    tables = extract_tables(stmt)
    is_select = sql_type == "DQL" and op_type == "SELECT"
    return {
        "sql_text": stmt,
        "sql_type": sql_type,
        "op_type": op_type,
        "tables": tables,
        "has_where": bool(re.search(r"\bWHERE\b", stmt, re.I)),
        "has_limit": bool(re.search(r"\bLIMIT\b", stmt, re.I)),
        "is_select_star": bool(re.search(r"\bSELECT\s+\*", stmt, re.I)) if is_select else False,
        "plan_json": None,  # MVP1 执行计划分析关闭；MVP2 起填充
    }
