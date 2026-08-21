# -*- coding: utf-8 -*-
# SPDX-License-Identifier: Apache-2.0
# Copyright 2025-2026 fiyo (Jack Ge) <sdfiyon@gmail.com>
# Author: fiyo (Jack Ge) - https://github.com/fiyo/DBCheck

"""DocKB 数据模型与检索。

数据存 data/doc_kb.db（不进 git）。提供：
- 建表 ensure_db()（幂等）
- 来源 / 事实 的 CRUD
- lookup_for_diagnosis()：为 AI 诊断做纯 SQL 结构化召回（零 embedding 依赖），
  返回对齐 modules.rag.vector_store.search 的 schema，并附带 DocKB 专属字段。

版权边界：只存「短事实摘录 + official_url 引用」，绝不整本搬运官方文档。
"""
import os
import re
import sqlite3
from pathlib import Path

from modules.core import paths

DB_PATH = paths.DOC_KB_DB

# 库类型展示名（用于标题与检索别名）
_DB_LABEL = {
    "mysql": "MySQL",
    "oracle": "Oracle",
    "pg": "PostgreSQL",
    "postgresql": "PostgreSQL",
    "sqlserver": "SQL Server",
    "dm": "DM8",
    "tidb": "TiDB",
}
# 检索别名：命中官方文档常见英文术语
_DB_ALIASES = {
    "mysql": ["mysql", "innodb", "myisam"],
    "oracle": ["oracle", "pga", "sga"],
    "pg": ["postgresql", "postgres", "pg"],
    "postgresql": ["postgresql", "postgres", "pg"],
    "sqlserver": ["sqlserver", "sql server"],
}
_CAT_LABEL = {
    "param": "参数",
    "baseline": "基线",
    "rule": "规则",
    "bug": "BUG",
}

_TOKEN_RE = re.compile(r"[A-Za-z0-9_]+|[一-鿿]+")


# ─────────────────────────── 连接 / 建表 ───────────────────────────
def _connect() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    return conn


def ensure_db() -> None:
    """幂等建表（重复执行安全）。"""
    with _connect() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS doc_sources (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                db_type      TEXT NOT NULL,
                version      TEXT NOT NULL,
                title        TEXT,
                official_url TEXT NOT NULL,
                fetched_at   TEXT,
                license_note TEXT,
                note         TEXT
            );
            CREATE TABLE IF NOT EXISTS doc_facts (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                source_id    INTEGER,
                db_type      TEXT NOT NULL,
                version      TEXT NOT NULL DEFAULT 'all',
                category     TEXT NOT NULL,
                key          TEXT NOT NULL,
                value        TEXT,
                excerpt      TEXT,
                official_url TEXT,
                severity     TEXT,
                lang         TEXT NOT NULL DEFAULT 'both',
                created_by   TEXT,
                created_at   TEXT DEFAULT (datetime('now')),
                updated_at   TEXT
            );
            CREATE INDEX IF NOT EXISTS idx_fact_lookup
                ON doc_facts(db_type, category, key);
            """
        )


# ─────────────────────────── 来源 CRUD ───────────────────────────
def insert_source(db_type: str, version: str, official_url: str,
                  title: str = None, license_note: str = None,
                  note: str = None, fetched_at: str = None) -> int:
    with _connect() as conn:
        cur = conn.execute(
            """INSERT INTO doc_sources
               (db_type, version, official_url, title, license_note, note, fetched_at)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (db_type, version, official_url, title, license_note, note, fetched_at),
        )
        return int(cur.lastrowid)


def get_sources(db_type: str = None) -> list:
    sql = "SELECT * FROM doc_sources"
    params = []
    if db_type:
        sql += " WHERE db_type = ?"
        params.append(db_type)
    sql += " ORDER BY db_type, version, id"
    with _connect() as conn:
        return [dict(r) for r in conn.execute(sql, params).fetchall()]


# ─────────────────────────── 事实 CRUD ───────────────────────────
def insert_fact(source_id, db_type: str, version: str, category: str, key: str,
                value: str = None, excerpt: str = None, official_url: str = None,
                severity: str = None, lang: str = "both", created_by: str = None) -> int:
    with _connect() as conn:
        cur = conn.execute(
            """INSERT INTO doc_facts
               (source_id, db_type, version, category, key, value, excerpt,
                official_url, severity, lang, created_by, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))""",
            (source_id, db_type, version, category, key, value, excerpt,
             official_url, severity, lang, created_by),
        )
        return int(cur.lastrowid)


def get_facts(db_type: str = None, category: str = None, q: str = None,
              version: str = None) -> list:
    sql = (
        "SELECT f.*, s.official_url AS src_url, s.title AS src_title "
        "FROM doc_facts f LEFT JOIN doc_sources s ON f.source_id = s.id"
    )
    conds, params = [], []
    if db_type:
        conds.append("f.db_type = ?")
        params.append(db_type)
    if category:
        conds.append("f.category = ?")
        params.append(category)
    if version:
        conds.append("f.version = ?")
        params.append(version)
    if q:
        like = f"%{q}%"
        conds.append("(f.key LIKE ? OR f.value LIKE ? OR f.excerpt LIKE ?)")
        params.extend([like, like, like])
    if conds:
        sql += " WHERE " + " AND ".join(conds)
    sql += " ORDER BY f.db_type, f.category, f.key"
    with _connect() as conn:
        return [dict(r) for r in conn.execute(sql, params).fetchall()]


def get_fact(fid: int):
    with _connect() as conn:
        row = conn.execute(
            "SELECT * FROM doc_facts WHERE id = ?", (fid,)
        ).fetchone()
        return dict(row) if row else None


def update_fact(fid: int, fields: dict) -> bool:
    allowed = {"source_id", "db_type", "version", "category", "key",
               "value", "excerpt", "official_url", "severity", "lang"}
    sets, params = [], []
    for k, v in fields.items():
        if k in allowed:
            sets.append(f"{k} = ?")
            params.append(v)
    if not sets:
        return False
    sets.append("updated_at = datetime('now')")
    params.append(fid)
    with _connect() as conn:
        cur = conn.execute(
            f"UPDATE doc_facts SET {', '.join(sets)} WHERE id = ?", params
        )
        return cur.rowcount > 0


def delete_fact(fid: int) -> bool:
    with _connect() as conn:
        cur = conn.execute("DELETE FROM doc_facts WHERE id = ?", (fid,))
        return cur.rowcount > 0


# ─────────────────────────── 种子数据（随包自动播种）──────────────────────────
def seed_from_json(seed_path=None) -> int:
    """从随包策展种子 JSON 幂等播种官方文档事实（不覆盖既有数据）。

    场景：Docker / exe 分发时 data/ 是全新运行时目录（data/doc_kb.db 不进
    git 也不随包），若 AI 诊断要引用官方事实，首次启动必须自动播种，否则
    DocKB 页面与检索均为空。本函数在应用启动时调用：

    - 仅追加缺失项（按 (db_type, version, key) 判重），**绝不清空/覆盖**
      用户既有数据，等价 scripts/seed_doc_kb.py 的 --keep 语义；
    - 来源按 (db_type, version, official_url) 判重，避免重复插入；
    - 种子文件默认 ``modules/config/doc_kb_seed.json``（随包、可入库）。

    Returns:
        本次新增的事实条数（0 表示跳过/无种子/全部已存在）。
    """
    import json as _json

    try:
        if seed_path is None:
            seed_path = str(Path(__file__).resolve().parent.parent / "config" / "doc_kb_seed.json")
        if not os.path.isfile(seed_path):
            return 0
        with open(seed_path, encoding="utf-8") as f:
            seed = _json.load(f)
        sources = seed.get("sources") or []
        facts = seed.get("facts") or []
        if not sources or not facts:
            return 0

        ensure_db()
        with _connect() as conn:
            # 已存在来源键：(db_type, version, official_url)
            have_src = {
                (r["db_type"], r["version"], r["official_url"])
                for r in conn.execute("SELECT db_type, version, official_url FROM doc_sources")
            }
            # 已存在事实键：(db_type, version, key)
            have_fact = {
                (r["db_type"], r["version"], r["key"])
                for r in conn.execute("SELECT db_type, version, key FROM doc_facts")
            }
            src_ids = []
            for s in sources:
                key = (s.get("db_type", ""), str(s.get("version") or ""), s.get("official_url", ""))
                if key in have_src:
                    row = conn.execute(
                        "SELECT id FROM doc_sources WHERE db_type=? AND version=? AND official_url=?",
                        (key[0], key[1], key[2]),
                    ).fetchone()
                    src_ids.append(row["id"])
                    continue
                cur = conn.execute(
                    "INSERT INTO doc_sources (db_type, version, official_url, title, license_note, note)"
                    " VALUES (?, ?, ?, ?, ?, ?)",
                    (key[0], key[1], key[2], s.get("title"), s.get("license_note"), "curated seed"),
                )
                src_ids.append(int(cur.lastrowid))
                have_src.add(key)

            added = 0
            for f in facts:
                try:
                    idx = int(f["source_idx"])
                    sid = src_ids[idx]
                    src = sources[idx]
                except (KeyError, ValueError, IndexError):
                    continue
                # db_type / version 以来源为准（facts 仅携带 source_idx 关联）
                db_type = str(src.get("db_type") or "")
                version = str(src.get("version") or "all")
                fkey = str(f.get("key") or "")
                if not db_type or not fkey:
                    continue
                if (db_type, version, fkey) in have_fact:
                    continue
                conn.execute(
                    "INSERT INTO doc_facts"
                    " (source_id, db_type, version, category, key, value, excerpt,"
                    "  official_url, severity, lang, created_by, updated_at)"
                    " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))",
                    (
                        sid, db_type, version,
                        str(f.get("category") or "param"), fkey,
                        f.get("value"), f.get("excerpt"), f.get("official_url"),
                        f.get("severity"), str(f.get("lang") or "both"),
                        "seed",
                    ),
                )
                have_fact.add((db_type, version, fkey))
                added += 1
        return added
    except Exception:  # noqa: BLE001 — 种子播种失败绝不影响启动
        return 0


# ─────────────────────────── 检索（AI 诊断用）───────────────────────────
def _tokenize(text: str) -> list:
    if not text:
        return []
    return _TOKEN_RE.findall(text)


def _extract_topics(db_type: str, metrics: dict, issues: list) -> list:
    """从诊断上下文抽取检索词（库别名 + issue 关键词 + 指标名/值）。"""
    topics = set()
    for a in _DB_ALIASES.get(db_type.lower(), [db_type.lower()]):
        if a:
            topics.add(a)
    for issue in (issues or [])[:8]:
        if isinstance(issue, dict):
            for raw in (issue.get("col1", ""), issue.get("col3", "")):
                for tok in _tokenize(raw):
                    if len(tok) >= 3:
                        topics.add(tok)
    if isinstance(metrics, dict):
        for k, v in metrics.items():
            if k and isinstance(k, str):
                topics.add(k.lower())
            if v and isinstance(v, str) and len(v) < 60:
                for tok in _tokenize(v):
                    if len(tok) >= 3:
                        topics.add(tok)
    return [t for t in topics if 2 <= len(t) <= 40]


def _relevance(row: dict, topics: list) -> float:
    """官方事实相关性评分：基础分 + 关键词命中加权（authoritative 事实优先）。"""
    score = 0.85
    key = (row["key"] or "").lower()
    value = (row["value"] or "").lower()
    excerpt = (row["excerpt"] or "").lower()
    for t in topics:
        tl = t.lower()
        if not tl:
            continue
        if tl in key:
            score += 0.15
        elif tl in value:
            score += 0.10
        elif tl in excerpt:
            score += 0.05
    return min(score, 1.2)


def _fact_title(row: dict) -> str:
    db_label = _DB_LABEL.get(row["db_type"], row["db_type"])
    cat_label = _CAT_LABEL.get(row["category"], row["category"])
    return f"{db_label} / {cat_label} / {row['key']}"


def _default_content(row: dict) -> str:
    out = row["key"] or ""
    if row["value"]:
        out = f"{out}：{row['value']}" if out else row["value"]
    return out


def lookup_for_diagnosis(db_type: str, metrics: dict, issues: list,
                         top_k: int = 3) -> list:
    """为 AI 诊断检索相关官方事实（纯 SQL，零 embedding 依赖）。

    返回对齐 modules.rag.vector_store.search 的 schema，并附带 DocKB 专属字段：
      doc_id, chunk_index, content, source, title, db_type, score,
      official_url, category, key, value, severity

    即使向量/embedding 不可用，AI 诊断仍能引到官方事实。
    """
    topics = _extract_topics(db_type, metrics, issues)
    if not topics:
        return []

    in_params = [db_type, "all"]
    topic_conds, params = [], list(in_params)
    for t in topics:
        like = f"%{t}%"
        topic_conds.append("(f.key LIKE ? OR f.value LIKE ? OR f.excerpt LIKE ? OR f.official_url LIKE ?)")
        params.extend([like, like, like, like])
    where = "f.db_type IN (?, ?) AND (" + " OR ".join(topic_conds) + ")"
    sql = (
        "SELECT f.*, s.official_url AS src_url, s.title AS src_title "
        f"FROM doc_facts f LEFT JOIN doc_sources s ON f.source_id = s.id "
        f"WHERE {where}"
    )

    try:
        with _connect() as conn:
            rows = conn.execute(sql, params).fetchall()
    except Exception:
        return []

    results = []
    for r in rows:
        r = dict(r)
        official_url = r.get("official_url") or r.get("src_url")
        content = r.get("excerpt") or _default_content(r)
        results.append({
            "doc_id": f"fact_{r['id']}",
            "chunk_index": 0,
            "content": content,
            "source": official_url or "",
            "title": _fact_title(r),
            "db_type": r["db_type"],
            "score": round(_relevance(r, topics), 3),
            "official_url": official_url or "",
            "category": r["category"],
            "key": r["key"],
            "value": r.get("value") or "",
            "severity": r.get("severity") or "",
        })

    results.sort(key=lambda x: x["score"], reverse=True)
    return results[:top_k]
