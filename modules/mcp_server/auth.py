# SPDX-License-Identifier: Apache-2.0
# Copyright 2025-2026 fiyo (Jack Ge) <sdfiyon@gmail.com>
# Author: fiyo (Jack Ge) - https://github.com/fiyo/DBCheck

"""MCP Server 纯函数 API Key 校验。

复用现有存储契约（data/pro_data/api_keys.db，sha256(key) 作 key_hash，
is_active=1 有效），但**不依赖 Flask**：现有 _verify_api_key() 失败分支调用
jsonify() 需要 app context，stdio 模式没有。这里复刻其 20 行核心逻辑。

注意：仅 stdio（本地受信）时协议层不强制鉴权；HTTP transport 阶段再强制。
"""

import os
import sqlite3
import hashlib

from modules.core import paths


def hash_key(key: str) -> str:
    """与 modules/web/api.py:_hash_key 完全一致。"""
    return hashlib.sha256(key.encode("utf-8")).hexdigest()


def _db_path() -> str:
    return str(paths.PRO_DATA_DIR / "api_keys.db")


def verify_api_key_raw(key: str):
    """纯函数校验 API Key。

    返回 (ok: bool, owner: str | None)。
    - key 为空或库不存在 → (False, None)
    - 命中有效记录 → (True, row['name'])
    - 其它 → (False, None)
    """
    if not key:
        return (False, None)
    db = _db_path()
    if not os.path.exists(db):
        return (False, None)
    try:
        conn = sqlite3.connect(db)
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT name FROM api_keys WHERE key_hash=? AND is_active=1",
            (hash_key(key),),
        ).fetchone()
        conn.close()
    except Exception:
        return (False, None)
    if row:
        return (True, row["name"])
    return (False, None)
