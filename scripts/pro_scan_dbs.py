# SPDX-License-Identifier: Apache-2.0
# Copyright 2025-2026 fiyo (Jack Ge) <sdfiyon@gmail.com>
# Author: fiyo (Jack Ge) - https://github.com/fiyo/DBCheck

"""探查所有 .db 文件的表结构和行数"""
import sqlite3
import os
import sys
from pathlib import Path

# 保证从任意位置运行时都能 import core.paths
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from modules.core import paths  # noqa: E402


db_files = [
    str(paths.PROJECT_ROOT / "history.db"),
    str(paths.PRO_DATA_DIR / "api_keys.db"),
    str(paths.PRO_DATA_DIR / "backup_history.db"),
    str(paths.PRO_DATA_DIR / "groups.db"),
    str(paths.PRO_DATA_DIR / "instances.db"),
    str(paths.PRO_DATA_DIR / "pro.db"),
    str(paths.PRO_DATA_DIR / "pro_history.db"),
    str(paths.PRO_DATA_DIR / "users.db"),
]

for path in db_files:
    name = os.path.basename(path)
    print(f"\n{'='*60}")
    print(f"  {name}")
    print(f"{'='*60}")
    if not os.path.exists(path):
        print("  (file not found)")
        continue
    try:
        conn = sqlite3.connect(path)
        c = conn.cursor()
        c.execute("SELECT name, sql FROM sqlite_master WHERE type='table' ORDER BY name")
        tables = c.fetchall()
        for t_name, t_sql in tables:
            c.execute(f"SELECT COUNT(*) FROM \"{t_name}\"")
            rows = c.fetchone()[0]
            print(f"\n  Table: {t_name}  ({rows} rows)")
            print(f"  SQL:   {t_sql}")
        conn.close()
    except Exception as e:
        print(f"  ERROR: {e}")
