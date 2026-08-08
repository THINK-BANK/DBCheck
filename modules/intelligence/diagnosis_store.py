# SPDX-License-Identifier: Apache-2.0
# Copyright 2025-2026 fiyo (Jack Ge) <sdfiyon@gmail.com>
# Author: fiyo (Jack Ge) - https://github.com/fiyo/DBCheck

"""协同诊断 · 诊断历史存储。

每一次协同诊断的完整结果都会落库（本仓库内 SQLite），
支持按数据源筛选、列表浏览、查看完整结果，并可从历史记录一键回填工单。
"""

from __future__ import annotations

import json
import os
import shutil
import sqlite3
import sys
import threading
from datetime import datetime
from typing import Any, Dict, List, Optional

from modules.core import paths

# 诊断库一律以 modules.core.paths.DATA_DIR 为准，禁止用 __file__ 上溯推算：
# intelligence/ 迁入 modules/intelligence/ 后，__file__ 上溯两级只到
# D:/DBCheck/modules，会把库错写到 modules/data/intelligence_diagnoses.db，
# 与 inspection.db / instances.db 等运行时数据脱离同一持久目录。
_DB_PATH = str(paths.DATA_DIR / "intelligence_diagnoses.db")

# 旧（错误）位置：仅用于一次性幂等迁移，见 _migrate_legacy_db()
_DB_PATH_LEGACY = str(
    paths.PROJECT_ROOT / "modules" / "data" / "intelligence_diagnoses.db"
)

_LOCK = threading.Lock()
# 迁移专用锁：与 _LOCK 分离，避免与 _init_db 的 `with _LOCK` 形成嵌套
_MIGRATE_LOCK = threading.Lock()

_MIGRATED = False

_SEV_ORDER = {"critical": 3, "warning": 2, "info": 1}


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _migrate_legacy_db() -> None:
    """把错写在 modules/data/ 的旧诊断库幂等迁移到 data/。

    迁移条件（保守，严格避免覆盖既有数据）：
      - 新位置 data/intelligence_diagnoses.db **不存在**；且
      - 旧位置 modules/data/intelligence_diagnoses.db 存在。
    采用 ``shutil.copy2`` 只复制、**保留旧文件**（与 instance_manager 的
    ``.db_key`` 迁移同策略），避免任何数据丢失风险。
    先复制到同目录临时文件再 ``os.replace`` 落位，保证其它线程要么看不到新库、
    要么看到完整新库，不会读到复制到一半的残缺文件。
    降级策略：迁移失败仅告警，不阻断启动（新库会自动重新建表）。
    """
    global _MIGRATED
    if _MIGRATED:
        return
    with _MIGRATE_LOCK:
        if _MIGRATED:  # 双检：并发下只执行一次
            return
        _MIGRATED = True
        tmp = _DB_PATH + ".migrating"
        try:
            if os.path.exists(_DB_PATH) or not os.path.exists(_DB_PATH_LEGACY):
                return
            os.makedirs(os.path.dirname(_DB_PATH), exist_ok=True)
            shutil.copy2(_DB_PATH_LEGACY, tmp)
            os.replace(tmp, _DB_PATH)  # 同目录原子落位
            print(
                f"[diagnosis_store] 已将诊断历史库迁移到持久目录: "
                f"{_DB_PATH_LEGACY} → {_DB_PATH}（内容不变，旧文件保留）"
            )
        except Exception as e:  # 降级：迁移失败不阻断启动
            print(
                f"[diagnosis_store][WARN] 诊断历史库迁移失败（{_DB_PATH_LEGACY} → "
                f"{_DB_PATH}）: {e}",
                file=sys.stderr,
            )
            try:  # 清理残留临时文件，避免污染 data/
                if os.path.exists(tmp):
                    os.remove(tmp)
            except OSError:
                pass


def _conn() -> sqlite3.Connection:
    os.makedirs(os.path.dirname(_DB_PATH), exist_ok=True)
    c = sqlite3.connect(_DB_PATH)
    c.row_factory = sqlite3.Row
    return c


def _init_db():
    _migrate_legacy_db()
    with _LOCK, _conn() as c:
        c.execute("""
            CREATE TABLE IF NOT EXISTS diagnoses (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                diag_no TEXT UNIQUE NOT NULL,
                created_at TEXT NOT NULL,
                instance_id TEXT,
                instance_name TEXT,
                db_type TEXT,
                goal TEXT,
                severity TEXT,
                finding_count INTEGER DEFAULT 0,
                plan_count INTEGER DEFAULT 0,
                result_json TEXT
            )
        """)
        c.commit()


def _next_no() -> str:
    d = datetime.now().strftime("%Y%m%d")
    with _LOCK, _conn() as c:
        cur = c.execute(
            "SELECT COUNT(*) FROM diagnoses WHERE diag_no LIKE ?",
            (f"DC-D-{d}-%",),
        )
        n = cur.fetchone()[0]
    return f"DC-D-{d}-{n + 1:03d}"


def _top_severity(findings: List[Dict[str, Any]]) -> str:
    sev = "info"
    for f in findings or []:
        s = f.get("severity") if isinstance(f, dict) else None
        if s in _SEV_ORDER and _SEV_ORDER[s] > _SEV_ORDER.get(sev, 0):
            sev = s
    return sev


def save_diagnosis(instance_id: str, instance_name: str, goal: str,
                   result: Dict[str, Any]) -> Dict[str, Any]:
    """把一次协同诊断结果落库，返回带 id / diag_no 的摘要。"""
    _init_db()
    result = result or {}
    findings = result.get("findings") or []
    plan = result.get("plan") or []
    meta = result.get("target_meta") or {}
    db_type = meta.get("db_type") or result.get("db_type") or ""
    if not instance_name:
        instance_name = meta.get("instance_name") or ""
    severity = _top_severity(findings)
    diag_no = _next_no()
    now = _now()
    with _LOCK, _conn() as c:
        cur = c.execute(
            """INSERT INTO diagnoses
               (diag_no, created_at, instance_id, instance_name, db_type, goal,
                severity, finding_count, plan_count, result_json)
               VALUES (?,?,?,?,?,?,?,?,?,?)""",
            (
                diag_no, now, instance_id, instance_name, db_type,
                goal or result.get("goal") or "", severity,
                len(findings), len(plan), _json(result),
            ),
        )
        did = cur.lastrowid
    return get_diagnosis(did) or {}


def list_diagnoses(instance_id: str = None, limit: int = 200) -> List[Dict[str, Any]]:
    """列表（摘要，不含完整 result_json）。"""
    _init_db()
    sql = ("SELECT id, diag_no, created_at, instance_id, instance_name, db_type, "
           "goal, severity, finding_count, plan_count FROM diagnoses WHERE 1=1")
    args: List[Any] = []
    if instance_id:
        sql += " AND instance_id=?"
        args.append(instance_id)
    sql += " ORDER BY id DESC LIMIT ?"
    args.append(int(limit or 200))
    with _conn() as c:
        rows = c.execute(sql, args).fetchall()
    return [dict(r) for r in rows]


def get_diagnosis(did: int) -> Optional[Dict[str, Any]]:
    """单条完整记录（含解析后的 result）。"""
    _init_db()
    with _conn() as c:
        row = c.execute("SELECT * FROM diagnoses WHERE id=?", (did,)).fetchone()
    if not row:
        return None
    d = dict(row)
    d["result"] = _parse(d.pop("result_json", "") or "") or {}
    return d


def delete_diagnosis(did: int) -> bool:
    _init_db()
    with _LOCK, _conn() as c:
        cur = c.execute("DELETE FROM diagnoses WHERE id=?", (did,))
    return cur.rowcount > 0


def _json(v) -> str:
    return json.dumps(v, ensure_ascii=False)


def _parse(s: str):
    try:
        return json.loads(s) if s else None
    except (ValueError, TypeError):
        return None
