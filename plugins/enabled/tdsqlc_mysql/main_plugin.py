#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# SPDX-License-Identifier: Apache-2.0
# Copyright 2025-2026 fiyo (Jack Ge) <sdfiyon@gmail.com>
# Author: fiyo (Jack Ge) - https://github.com/fiyo/DBCheck

"""
TDSQL-C MySQL 巡检插件

TDSQL-C MySQL 是腾讯云数据库，100% 兼容 MySQL 协议。
本插件直接复用内核 MySQL 巡检器 MySQLInspector（main_mysql.py），
仅对外以独立的 db_type `tdsqlc_mysql` 注册，实现「单独增加巡检功能」。

要点（与 HGDB 复用 PG 同构）：
- 内部仍使用 MySQLInspector，self.db_type 保持 'mysql'，
  这样 BaseInspectionEngine.collect_data 能正确找到 inspection.db.mysql 下的模板 SQL。
- get_task_config() 的 smart_analyze 指向 'smart_analyze_mysql'，
  analyzer.smart_analyze_mysql 内部已写死 analyze_with_plugins('mysql', ...)，
  因此 mysql.yaml 中 db_types 含 mysql / tdsqlc_mysql 的规则都会自动生效。
"""

import os
from pathlib import Path
from typing import Any, Dict, List

# 复用内核 MySQL 巡检器（位于仓库根目录 main_mysql.py）
from modules.entrypoints.main_mysql import MySQLInspector


def test_connection(host, port, user, password, database=None):
    """TDSQL-C MySQL 连接测试（与 MySQL 协议完全兼容，使用 PyMySQL）。"""
    try:
        import pymysql
        port = int(port)
        if database:
            conn = pymysql.connect(host=host, port=port, user=user, password=password,
                                   database=database, connect_timeout=10, charset='utf8mb4')
        else:
            conn = pymysql.connect(host=host, port=port, user=user, password=password,
                                   connect_timeout=10, charset='utf8mb4')
        cur = conn.cursor()
        cur.execute("SELECT VERSION()")
        ver = cur.fetchone()[0]
        cur.close()
        conn.close()
        return True, ver
    except Exception as e:
        return False, str(e)


def getData(ip, port, user, password, ssh_info=None, template_id=None, database=None):
    """
    创建 TDSQL-C MySQL 巡检器实例（兼容 web_ui.run_inspection_task 旧调用约定）。

    内部直接实例化 MySQLInspector，确保 db_type='mysql'、复用 MySQL 模板与采集逻辑。
    """
    inspector = MySQLInspector(ip, int(port), user, password, database, ssh_info, template_id)
    ok, ver = inspector.connect()
    if not ok:
        raise ConnectionError("TDSQL-C MySQL 连接失败: " + str(ver))

    class CompatWrapper:
        def __init__(self, inspector):
            self.inspector = inspector
            self.conn_db2 = inspector.conn  # 兼容 web_ui 的 conn_attr 检查（此处 conn_attr='' 跳过）

        def checkdb(self, sqlfile=''):
            self.inspector.collect_data()
            return self.inspector.context

        def generate_report(self, output_file, inspector_name="Jack"):
            return self.inspector.generate_report(output_file, inspector_name)

    return CompatWrapper(inspector)


def get_task_config():
    """返回插件任务配置（供 plugin_loader.get_plugin_task_config 调用）。"""
    return {
        'module_name': 'main_plugin',
        'plugin_path': str(Path(__file__).parent),
        'main_file': 'main_plugin.py',
        'connect_test': test_connection,
        'connect_test_args': lambda info: [info.get('ip', ''), info.get('port'),
                                           info.get('user', ''), info.get('password', '')],
        'getdata_args': lambda info: (
            [info.get('ip', ''), int(info.get('port', 3306) or 3306),
             info.get('user', ''), info.get('password', '')],
            {'ssh_info': {},
             'template_id': info.get('template_id'),
             'database': info.get('database')}
        ),
        'conn_attr': '',  # getData 返回 CompatWrapper，跳过 conn_attr 检查
        'filename_key': 'webui.tdsqlc_mysql_report_filename',
        'history_db_type': 'tdsqlc_mysql',   # 对外分组 / 历史快照独立
        'instance_prefix': 'tdsqlc_mysql',
        'error_task_name': 'TDSQL-C MySQL',
        'log_start_key': 'webui.log_mysql_start',
        'err_module_key': 'webui.err_mysql_module',
        'label_default': 'TDSQL-C MySQL',
        'db_name_default': 'mysql',
        'smart_analyze': 'smart_analyze_mysql',  # ← 复用 MySQL 分析器，mysql.yaml 规则自动套用
    }


# ── 注册插件（无侵入式架构）──────────────────────────────────────────
try:
    from modules.pluginkit.core import InspectionPlugin, register

    class TdsqlcMysqlPluginAdapter(InspectionPlugin):
        """TDSQL-C MySQL 插件适配器（实现标准接口）。"""

        def __init__(self, parse_func=None):
            self.id = 'tdsqlc_mysql'  # 与目录名 tdsqlc_mysql / plugin.json 逻辑 id 对齐
            self.name = 'TDSQL-C MySQL'
            self.version = '1.0.0'
            self.db_types = ['tdsqlc_mysql']
            self.author = 'DBCheck Team'
            self.description = '腾讯云 TDSQL-C MySQL 版（MySQL 协议兼容）巡检插件，复用 MySQL 采集与规则'
            self._parse_func = parse_func
            super().__init__()

        def parse_connection_result(self, ok: bool, msg: Any) -> Dict[str, Any]:
            if self._parse_func:
                return self._parse_func(ok, msg)
            return {}

    # 自动注册
    try:
        register(TdsqlcMysqlPluginAdapter())
    except Exception as _e:  # 重复注册等情况下不致命
        print(f"[tdsqlc_mysql] 注册跳过: {_e}")
except Exception as _import_err:
    # plugin_core 不可用时（如独立测试）静默忽略，不影响模块可导入
    print(f"[tdsqlc_mysql] plugin_core 不可用，跳过注册: {_import_err}")
