#!/usr/bin/env python3
# -*- coding:utf-8 -*-
# SPDX-License-Identifier: Apache-2.0
# Copyright 2025-2026 fiyo (Jack Ge) <sdfiyon@gmail.com>
# Author: fiyo (Jack Ge) - https://github.com/fiyo/DBCheck

from modules.config.version import __version__ as VER
from i18n import get_lang, t as _t
from modules.inspection.engine import BaseInspectionEngine
from modules.core import entry

"""
崖山 YashanDB 数据库自动化健康巡检工具 {VER}
支持 YashanDB 23+ 及以上版本
依赖: yasdb (pip install yasdb), python-docx, docxtpl, openpyxl, psutil, paramiko>=2.8,<2.10
"""

import warnings
warnings.filterwarnings("ignore")
import sys
import datetime
import argparse
import getpass

# 兼容函数 — 供 web_ui.py 旧代码调用

def getData(ip, port, user, password, ssh_info=None, db_name=None, template_id=None, driver_version=''):
    """
    原有 API - 创建 YashanDbInspector 实例
    """
    inspector = YashanDbInspector(ip, port, user, password, db_name, ssh_info, template_id, driver_version)
    ok, ver = inspector.connect()
    if not ok:
        return None

    class CompatWrapper:
        def __init__(self, inspector):
            self.inspector = inspector
            self.conn_db = inspector.conn

        def checkdb(self, sqlfile=''):
            self.inspector.collect_data()
            return self.inspector.context

        def generate_report(self, output_file, inspector_name="Jack"):
            return self.inspector.generate_report(output_file, inspector_name)

    return CompatWrapper(inspector)


def create_word_template(inspector_name):
    """原有 API - 创建 Word 模板"""
    return '_yashandb_inspector_generated_'


def saveDoc(context, ofile, ifile, inspector_name, **kwargs):
    """原有 API - 保存 Word 报告"""
    inspector = kwargs.get('H')
    class CompatWrapper:
        def __init__(self, context, ofile, inspector, inspector_name):
            self.context = context
            self.ofile = ofile
            self._inspector = inspector
            self._inspector_name = inspector_name

        def contextsave(self):
            if self._inspector and hasattr(self._inspector, 'generate_report'):
                return self._inspector.generate_report(self.ofile, self._inspector_name) is not None
            from docx import Document
            doc = Document()
            doc.save(self.ofile)
            return True
    return CompatWrapper(context, ofile, inspector, inspector_name)


# 崖山 YashanDB 驱动（可选，未安装时不影响其它功能）
try:
    import yasdb as yashandb_driver
    YASHANDB_DRIVER = 'yasdb'
except ImportError:
    yashandb_driver = None
    YASHANDB_DRIVER = None


class YashanDbInspector(BaseInspectionEngine):
    """
    崖山 YashanDB 巡检引擎
    继承 BaseInspectionEngine，只需实现 connect()
    """

    def __init__(self, host, port, user, password, database=None, ssh_info=None, template_id=None, driver_version=''):
        super().__init__(host, port, user, password, database, ssh_info, template_id)
        self.db_type = 'yashandb'
        self._lang = get_lang()
        self.driver_version = driver_version or ''

    def connect(self):
        """
        连接崖山 YashanDB 数据库（统一 JDBC 优先，回退 yasdb）。

        YashanDB 官方驱动 com.yashandb.jdbc.Driver / jdbc:yashandb://；
        JDBC 不可用（无驱动/无 JVM 环境）时回退 yasdb 原生驱动。
        """
        try:
            import os as _os
            from modules.jdbc_connector import open_jdbc_connection
            from modules.core.paths import PROJECT_ROOT
            _conn, _meta = open_jdbc_connection(
                'yashandb', self.host, int(self.port),
                user=self.user, password=self.password,
                database=self.database or 'yashandb',
                driver_version=self.driver_version,
                fallback_dirs=[_os.path.join(str(PROJECT_ROOT), 'drivers', 'yashandb')],
            )
            if _conn is None:
                return self._connect_native((_meta or {}).get('error') or 'JDBC 连接失败')
            self.conn = _conn
            self.cursor = self.conn.cursor()

            # 获取 YashanDB 版本号
            version = self._query_version()
            self.context['version'] = [{'VERSION': version}]

            print(_t("yashandb_connect_success").format(host=self.host, port=self.port))
            return True, version

        except Exception as e:
            return self._connect_native(str(e))

    def _query_version(self):
        """读取 YashanDB 版本号（兼容 V$VERSION / V$INSTANCE 两种视图）。"""
        try:
            self.cursor.execute("SELECT BANNER FROM V$VERSION WHERE ROWNUM=1")
            return self.cursor.fetchone()[0]
        except Exception:  # noqa: BLE001
            try:
                self.cursor.execute("SELECT VERSION FROM V$INSTANCE")
                return self.cursor.fetchone()[0]
            except Exception:  # noqa: BLE001
                return 'Unknown'

    def _connect_native(self, reason=''):
        """回退：yasdb 原生驱动（pip install yasdb）。"""
        try:
            if yashandb_driver is None:
                return False, (f'{reason}；且未安装 yasdb（pip install yasdb），'
                               f'无法原生回退。请到「数据库驱动管理」上传 YashanDB JDBC 驱动 jar。')
            self.conn = yashandb_driver.connect(
                host=self.host,
                port=int(self.port),
                user=self.user,
                password=self.password
            )
            self.cursor = self.conn.cursor()

            # 获取 YashanDB 版本号
            version = self._query_version()
            self.context['version'] = [{'VERSION': version}]

            print(f"YashanDB yasdb 回退连接成功: {self.host}:{self.port}（JDBC: {reason[:80]}...）" if reason else _t("yashandb_connect_success").format(host=self.host, port=self.port))
            return True, version

        except Exception as e:
            err_msg = str(e)
            print(_t("yashandb_connect_fail").format(error=err_msg))
            import traceback
            traceback.print_exc()
            return False, (f'{reason}；yasdb 回退也失败: {err_msg}' if reason else err_msg)

# ============================================================
# CLI 入口
# ============================================================
def main_cli():
    """独立运行时的 argparse 入口"""
    entry.ensure_bootstrapped('yashandb')
    parser = argparse.ArgumentParser(description=_t("yashandb_cli_desc"))
    parser.add_argument('-H', '--host', required=True, help=_t("cli_host"))
    parser.add_argument('-P', '--port', type=int, default=1688, help=_t("yashandb_cli_port"))
    parser.add_argument('-u', '--user', default='sys', help=_t("cli_user"))
    parser.add_argument('-p', '--password', help=_t("cli_password"))
    parser.add_argument('-o', '--output', help=_t("cli_output"))
    parser.add_argument('--ssh-host', help=_t("cli_ssh_host"))
    parser.add_argument('--ssh-port', type=int, default=22, help=_t("cli_ssh_port"))
    parser.add_argument('--ssh-user', default='root', help=_t("cli_ssh_user"))
    parser.add_argument('--ssh-password', help=_t("cli_ssh_password"))
    args = parser.parse_args()

    password = args.password
    if not password:
        password = getpass.getpass(_t("cli_pwd_prompt"))

    ssh_info = None
    if args.ssh_host:
        ssh_info = {
            'ssh_host': args.ssh_host,
            'ssh_port': args.ssh_port,
            'ssh_user': args.ssh_user,
            'ssh_password': args.ssh_password
        }

    inspector = YashanDbInspector(
        host=args.host,
        port=args.port,
        user=args.user,
        password=password,
        ssh_info=ssh_info
    )

    ok, version = inspector.connect()
    if not ok:
        print(_t("yashandb_conn_fail_exit"))
        sys.exit(1)

    inspector.collect_data()
    output_file = args.output or "YashanDB_Inspection_Report_{}.docx".format(datetime.now().strftime('%Y%m%d_%H%M%S'))
    inspector.generate_report(output_file)
    print(_t("yashandb_report_generated").format(file=output_file))


def main(host=None, port=None, user=None, password=None, output=None, ssh_info=None):
    """YashanDB 巡检 CLI 入口 - 支持交互模式和参数模式"""
    entry.ensure_bootstrapped('yashandb')
    if host is None:
        # 交互模式（从 main.py 调用时）
        print(u"YashanDB 数据库巡检")
        print(u"=" * 50)
        host = input(u"主机地址 [localhost]: ") or "localhost"
        port = int(input(u"端口 [1688]: ") or 1688)
        user = input(u"用户名 [sys]: ") or "sys"
        if not user:
            print(u"用户名不能为空")
            return
        if password is None:
            password = getpass.getpass(u"密码: ")
        output = input(u"输出文件 [YashanDB_Inspection_Report.docx]: ") or "YashanDB_Inspection_Report.docx"

    inspector = YashanDbInspector(
        host=host,
        port=port,
        user=user,
        password=password,
        ssh_info=ssh_info
    )

    ok, version = inspector.connect()
    if not ok:
        print(u"连接失败: {}".format(version))
        return

    inspector.collect_data()
    output_file = output or "YashanDB_Inspection_Report_{}.docx".format(datetime.now().strftime('%Y%m%d_%H%M%S'))
    inspector.generate_report(output_file)
    print(u"报告已生成: {}".format(output_file))


if __name__ == '__main__':
    main_cli()
