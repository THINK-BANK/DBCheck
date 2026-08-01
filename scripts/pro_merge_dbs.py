# SPDX-License-Identifier: Apache-2.0
# Copyright 2025-2026 fiyo (Jack Ge) <sdfiyon@gmail.com>
# Author: fiyo (Jack Ge) - https://github.com/fiyo/DBCheck

"""合并所有分散 .db 文件到统一的 dbcheck.db (v2)"""
import sqlite3
import os
import re
import sys
from pathlib import Path

# 保证从任意位置运行时都能 import core.paths
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from modules.core import paths  # noqa: E402


ROOT = str(paths.PROJECT_ROOT)
DATA = str(paths.PRO_DATA_DIR)
TARGET = os.path.join(DATA, "dbcheck.db")

if os.path.exists(TARGET):
    os.remove(TARGET)

tgt = sqlite3.connect(TARGET)
tc = tgt.cursor()

def copy_table(src_path, src_table, tgt_table, extra_cols="", extra_vals=()):
    """复制表：读取源表结构+数据 → 写入目标"""
    if not os.path.exists(src_path):
        print(f"  SKIP {os.path.basename(src_path)}/{src_table} (file not found)")
        return 0

    src = sqlite3.connect(src_path)
    sc = src.cursor()
    sc.execute(f"SELECT name FROM sqlite_master WHERE type='table' AND name=?", (src_table,))
    if not sc.fetchone():
        print(f"  SKIP {src_table} (not in source)")
        src.close()
        return 0

    # 获取列信息
    sc.execute(f"PRAGMA table_info('{src_table}')")
    cols = sc.fetchall()

    # 构建 CREATE TABLE
    col_defs = []
    pk_cols = []
    for c in cols:
        name, typ, not_null, dflt, pk = c[1], c[2], c[3], c[4], c[5]
        defn = f'"{name}" {typ}'
        if pk:
            pk_cols.append(name)
        if dflt is not None:
            # dflt_value 已经是 SQL 格式（含引号等）
            defn += f" DEFAULT {dflt}"
        col_defs.append(defn)

    if pk_cols:
        col_defs.append(f'PRIMARY KEY ({", ".join(f"\"{p}\"" for p in pk_cols)})')

    if extra_cols:
        col_defs.append(extra_cols)

    tc.execute(f'DROP TABLE IF EXISTS "{tgt_table}"')
    tc.execute(f'CREATE TABLE "{tgt_table}" ({", ".join(col_defs)})')

    # 复制数据
    sc.execute(f'SELECT * FROM "{src_table}"')
    rows = sc.fetchall()
    if rows:
        col_names = [c[1] for c in cols]
        placeholders = ','.join(['?'] * len(col_names))
        cols_q = ','.join([f'"{n}"' for n in col_names])
        tc.executemany(
            f'INSERT INTO "{tgt_table}" ({cols_q}) VALUES ({placeholders})',
            [tuple(r) for r in rows]
        )

    count = len(rows)
    src.close()
    print(f"  OK   {tgt_table}  ({count} rows)")
    return count

print("═" * 50)
print("  DB Merge → pro_data/dbcheck.db")
print("═" * 50)

total = 0

# 1. history.db (项目根目录)
print("\n📦 history.db")
root_db = os.path.join(ROOT, "history.db")
total += copy_table(root_db, "instances", "history_instances")
total += copy_table(root_db, "rag_documents", "rag_documents")
total += copy_table(root_db, "rag_embeddings", "rag_embeddings")
# snapshots 表有外键引用 instances，在 history_instances 存在后复制
total += copy_table(root_db, "snapshots", "snapshots")

# 2. instances.db (Pro版)
print("\n📦 instances.db")
total += copy_table(os.path.join(DATA, "instances.db"), "instances", "instances")

# 3. groups.db
print("\n📦 groups.db")
total += copy_table(os.path.join(DATA, "groups.db"), "groups", "groups")

# 4. pro_history.db
print("\n📦 pro_history.db")
total += copy_table(os.path.join(DATA, "pro_history.db"), "inspection_history", "inspection_history")
total += copy_table(os.path.join(DATA, "pro_history.db"), "instance_trend", "instance_trend")

# 5. users.db
print("\n📦 users.db")
total += copy_table(os.path.join(DATA, "users.db"), "users", "users")
total += copy_table(os.path.join(DATA, "users.db"), "login_log", "login_log")

# 6. api_keys.db
print("\n📦 api_keys.db")
total += copy_table(os.path.join(DATA, "api_keys.db"), "api_keys", "api_keys")

# 7. backup_history.db
print("\n📦 backup_history.db")
total += copy_table(os.path.join(DATA, "backup_history.db"), "backup_history", "backup_history")
total += copy_table(os.path.join(DATA, "backup_history.db"), "backup_schedules", "backup_schedules")

# 8. pro.db
print("\n📦 pro.db")
total += copy_table(os.path.join(DATA, "pro.db"), "sql_execution_log", "sql_execution_log")

tgt.commit()
tgt.close()

print(f"\n{'═' * 50}")
print(f"  Done: 13 tables, ~{total} rows → dbcheck.db")
print(f"{'═' * 50}")
