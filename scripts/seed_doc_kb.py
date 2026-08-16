# -*- coding: utf-8 -*-
# SPDX-License-Identifier: Apache-2.0
# Copyright 2025-2026 fiyo (Jack Ge) <sdfiyon@gmail.com>
# Author: fiyo (Jack Ge) - https://github.com/fiyo/DBCheck
"""DocKB 官方文档知识库 - 种子示例数据。

将一组经过人工策展（curated）的官方事实写入 data/doc_kb.db，
供 AI 诊断在 Phase 0 链路中引用（零 embedding 依赖）。

注意：
- data/doc_kb.db 不进 git，可随时删除重建，零风险。
- 默认行为：清空 doc_facts / doc_sources 后重新写入策展种子，
  以保证知识库处于可复现的干净状态。
- 传入 --keep 则跳过清空，仅在缺失时追加（幂等），保留既有数据。

用法：
    python scripts/seed_doc_kb.py            # 清空并重写策展种子
    python scripts/seed_doc_kb.py --keep     # 仅追加缺失项
"""
import argparse
import os
import sys

# ── 路径收口：剥离可能遮蔽 D:\DBCheck 的会话目录命名空间包 ──
HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)  # D:\DBCheck （脚本位于 scripts/ 下）
sys.path = [REPO] + [
    p for p in sys.path
    if p and os.path.abspath(p or ".") != REPO
    and "2026-06-19-10-06-09" not in p
]
os.chdir(REPO)

from modules.doc_kb import models  # noqa: E402


# ─────────────────────────── 策展内容 ───────────────────────────
# 来源（库类型 -> 官方文档元信息）
SOURCES = [
    {
        "db_type": "mysql", "version": "8.0",
        "title": "MySQL 8.0 Reference Manual",
        "official_url": "https://dev.mysql.com/doc/refman/8.0/en/",
        "license_note": "MySQL 文档遵循 Oracle 使用条款，本库仅摘录事实并标注来源链接。",
    },
    {
        "db_type": "oracle", "version": "19c",
        "title": "Oracle Database 19c Reference",
        "official_url": "https://docs.oracle.com/en/database/oracle/oracle-database/19/",
        "license_note": "Oracle 文档遵循 Oracle 使用条款，本库仅摘录事实并标注来源链接。",
    },
    {
        "db_type": "pg", "version": "15",
        "title": "PostgreSQL 15 Documentation",
        "official_url": "https://www.postgresql.org/docs/15/",
        "license_note": "PostgreSQL 文档采用 PostgreSQL License，可自由引用；本库仅摘录事实并标注来源链接。",
    },
]

# 事实（每条绑定一个来源下标 _src）
FACTS = [
    # ───────── MySQL 8.0 ─────────
    dict(_src=0, category="param", key="innodb_buffer_pool_size",
         value="默认 128MB（134217728 字节）",
         excerpt="InnoDB 缓冲池默认 128MB。官方建议专用数据库服务器上设为物理内存的 50%~75%，以缓存更多数据、减少磁盘 I/O。",
         official_url="https://dev.mysql.com/doc/refman/8.0/en/innodb-buffer-pool-resize.html",
         severity="mid", lang="both"),
    dict(_src=0, category="baseline", key="innodb_buffer_pool_size_tuning",
         value="专用服务器建议设为物理内存 50%~75%",
         excerpt="On a dedicated database server, you might set the buffer pool size to 80% of machine memory.",
         official_url="https://dev.mysql.com/doc/refman/8.0/en/innodb-buffer-pool-resize.html",
         severity="mid", lang="both"),
    dict(_src=0, category="param", key="max_connections",
         value="默认 151",
         excerpt="MySQL 默认最大并发连接数为 151；并发高时需调大，并关注内存与线程调度开销。",
         official_url="https://dev.mysql.com/doc/refman/8.0/en/server-system-variables.html#sysvar_max_connections",
         severity="low", lang="both"),
    dict(_src=0, category="param", key="innodb_log_file_size",
         value="默认 48MB（redo 日志总量约 96MB）",
         excerpt="单个 redo 日志文件默认 48MB；增大可提升写吞吐，但会延长崩溃恢复时间。",
         official_url="https://dev.mysql.com/doc/refman/8.0/en/innodb-redo-log.html",
         severity="low", lang="both"),
    dict(_src=0, category="param", key="innodb_flush_log_at_trx_commit",
         value="默认 1（完全 ACID，每次提交刷盘）",
         excerpt="默认 1 保证每次提交持久化（最安全）；设为 2 或 0 可提升性能，但故障可能丢失已提交事务。",
         official_url="https://dev.mysql.com/doc/refman/8.0/en/innodb-parameters.html#sysvar_innodb_flush_log_at_trx_commit",
         severity="high", lang="both"),
    dict(_src=0, category="param", key="sync_binlog",
         value="默认 1（每事务刷盘）",
         excerpt="默认 1 保证 binlog 与事务一致；设为 0 或 N 可提升性能，但崩溃可能丢失已提交事务的 binlog。",
         official_url="https://dev.mysql.com/doc/refman/8.0/en/replication-options-binary-log.html#sysvar_sync_binlog",
         severity="mid", lang="both"),

    # ───────── Oracle 19c ─────────
    dict(_src=1, category="param", key="sga_target",
         value="默认 0（0 表示由各 SGA 组件参数手动管理）",
         excerpt="SGA_TARGET 默认 0；设为大于 0 可启用 SGA 自动内存管理（ASMM），并在 SGA_MAX_SIZE 内自动分配各组件。",
         official_url="https://docs.oracle.com/en/database/oracle/oracle-database/19/refrn/SGA_TARGET.html",
         severity="mid", lang="both"),
    dict(_src=1, category="baseline", key="sga_target_tuning",
         value="专用库建议 SGA_TARGET ≈ 物理内存 60%~70%",
         excerpt="在专用数据库服务器上，Oracle 建议 SGA 占物理内存约 60%~70%，剩余留给 PGA 与操作系统。",
         official_url="https://docs.oracle.com/en/database/oracle/oracle-database/19/admin/managing-memory.html",
         severity="mid", lang="both"),
    dict(_src=1, category="param", key="pga_aggregate_target",
         value="默认 0（自动调优为 SGA 约 20%）",
         excerpt="PGA_AGGREGATE_TARGET 默认 0；若未设置 MEMORY_TARGET，Oracle 自动将其调优为 SGA 的约 20%。",
         official_url="https://docs.oracle.com/en/database/oracle/oracle-database/19/refrn/PGA_AGGREGATE_TARGET.html",
         severity="low", lang="both"),
    dict(_src=1, category="param", key="processes",
         value="默认 300",
         excerpt="PROCESSES 默认 300，控制最大并发进程/会话数；连接密集场景需调大并相应调整 SESSIONS。",
         official_url="https://docs.oracle.com/en/database/oracle/oracle-database/19/refrn/PROCESSES.html",
         severity="low", lang="both"),
    dict(_src=1, category="param", key="open_cursors",
         value="默认 300",
         excerpt="OPEN_CURSORS 默认 300，控制单个会话可同时打开的游标数；应用使用大量游标时需调大。",
         official_url="https://docs.oracle.com/en/database/oracle/oracle-database/19/refrn/OPEN_CURSORS.html",
         severity="low", lang="both"),

    # ───────── PostgreSQL 15 ─────────
    dict(_src=2, category="param", key="shared_buffers",
         value="默认 128MB",
         excerpt="shared_buffers 默认 128MB。官方建议专用服务器设为物理内存约 25%（不超过 40%）。",
         official_url="https://www.postgresql.org/docs/15/runtime-config-resource.html#GUC-SHARED-BUFFERS",
         severity="mid", lang="both"),
    dict(_src=2, category="baseline", key="shared_buffers_tuning",
         value="建议约物理内存 25%（不超过 40%）",
         excerpt="For a dedicated database server, a common starting value for shared_buffers is 25% of the system memory.",
         official_url="https://www.postgresql.org/docs/15/runtime-config-resource.html#GUC-SHARED-BUFFERS",
         severity="mid", lang="both"),
    dict(_src=2, category="param", key="work_mem",
         value="默认 4MB",
         excerpt="work_mem 默认 4MB，为每个排序/哈希操作按（进程×操作数）分配；设置过大易引发内存压力。",
         official_url="https://www.postgresql.org/docs/15/runtime-config-resource.html#GUC-WORK-MEM",
         severity="low", lang="both"),
    dict(_src=2, category="param", key="max_connections",
         value="默认 100",
         excerpt="max_connections 默认 100；高并发场景建议配合连接池（如 pgbouncer）而非盲目调大。",
         official_url="https://www.postgresql.org/docs/15/runtime-config-connection.html#GUC-MAX-CONNECTIONS",
         severity="low", lang="both"),
    dict(_src=2, category="param", key="effective_cache_size",
         value="默认 4GB（建议设为物理内存约 50%）",
         excerpt="effective_cache_size 默认 4GB，仅用于优化器代价估算；建议设为 OS 与数据库可缓存内存的约 50%。",
         official_url="https://www.postgresql.org/docs/15/runtime-config-query.html#GUC-EFFECTIVE-CACHE-SIZE",
         severity="low", lang="both"),
    dict(_src=2, category="param", key="maintenance_work_mem",
         value="默认 64MB",
         excerpt="maintenance_work_mem 默认 64MB，用于 VACUUM / ANALYZE / 索引创建等维护操作，可适当调大加速维护。",
         official_url="https://www.postgresql.org/docs/15/runtime-config-resource.html#GUC-MAINTENANCE-WORK-MEM",
         severity="low", lang="both"),
]


def _existing_keys() -> set:
    keys = set()
    for f in models.get_facts():
        keys.add((f["db_type"], f.get("version") or "all", f["key"]))
    return keys


def seed(reset: bool) -> None:
    models.ensure_db()

    if reset:
        with models._connect() as conn:
            conn.execute("DELETE FROM doc_facts")
            conn.execute("DELETE FROM doc_sources")
            try:
                conn.execute("DELETE FROM sqlite_sequence "
                             "WHERE name IN ('doc_facts','doc_sources')")
            except Exception:
                pass
        print("[seed] 已清空 doc_facts / doc_sources，准备重写策展种子。")
    else:
        print("[seed] 保留既有数据，仅追加缺失项（幂等）。")

    have = _existing_keys() if not reset else set()
    src_ids = []
    for s in SOURCES:
        sid = models.insert_source(
            db_type=s["db_type"], version=s["version"],
            official_url=s["official_url"], title=s["title"],
            license_note=s.get("license_note"),
            note="curated seed",
        )
        src_ids.append(sid)

    added = 0
    for f in FACTS:
        s = SOURCES[f["_src"]]
        ver = s["version"]
        if (s["db_type"], ver, f["key"]) in have:
            continue
        models.insert_fact(
            source_id=src_ids[f["_src"]],
            db_type=s["db_type"], version=ver,
            category=f["category"], key=f["key"],
            value=f.get("value"), excerpt=f.get("excerpt"),
            official_url=f.get("official_url"),
            severity=f.get("severity"), lang=f.get("lang", "both"),
            created_by="seed",
        )
        added += 1

    total = len(models.get_facts())
    print(f"[seed] 完成：新增 {added} 条事实，当前库共 {total} 条事实 / {len(src_ids)} 个来源。")


def main() -> None:
    ap = argparse.ArgumentParser(description="DocKB 策展种子数据写入")
    ap.add_argument("--keep", action="store_true",
                    help="不清空既有数据，仅在缺失时追加（幂等）")
    args = ap.parse_args()
    seed(reset=not args.keep)


if __name__ == "__main__":
    main()
