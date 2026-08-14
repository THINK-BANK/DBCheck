#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# SPDX-License-Identifier: Apache-2.0
# Copyright 2025-2026 fiyo (Jack Ge) <sdfiyon@gmail.com>
# Author: fiyo (Jack Ge) - https://github.com/fiyo/DBCheck

"""JDBC 连接测试隔离子进程入口。

背景（为什么必须隔离到子进程）
--------------------------------
Web 端（冻结 exe）通过 ``build/runtime-hook-gevent.py`` 在进程启动阶段执行
``gevent.monkey.patch_all()``。而 HGDB / DB2 / SQL Server(JDBC) 三类数据源
都依赖 JPype 在**当前进程内**启动 JVM（``jpype.startJVM``）并调用
``DriverManager.getConnection``。JVM 使用的是真实 OS 原生线程，且会接管
信号与部分运行时状态，与 gevent 的绿色线程 hub 相互踩踏：一旦在 patch 过的
进程里发起 JDBC 连接，hub 可能被原生线程钉死，HTTP 响应再也写不回去，
表现为「点测试连接后整个界面卡死」。

``app._conn_test_with_timeout`` 里的 ``threading.Thread + Event.wait`` 只能
兜住「Python 层慢」，兜不住「进程级 JVM 死锁」——线程超时返回后，被钉死的
hub 依旧无法把响应写出去。因此唯一可靠的解法是：**把 JVM 挪到另一个没有被
monkey-patch 的干净进程里**，主进程只做 ``subprocess`` 调用 + 超时杀进程。

协议
----
- 子进程由 ``<python|dbcheck.exe> --jdbc-test-cli`` 启动；
- 连接参数以**单个 JSON 对象**经 stdin 传入（不走命令行参数，避免密码出现在
  进程列表 / 任务管理器里）；
- 结果以**唯一一行** ``__DBCHECK_JDBC_TEST_RESULT__{json}`` 写入 stdout。
  插件自身可能打印大量日志，故主进程按该前缀行提取结果，其余输出忽略。

入参 JSON 结构::

    {
      "db_type": "hgdb" | "db2" | "sqlserver_jdbc" | ...,
      "host": "127.0.0.1",
      "port": 5866,
      "user": "highgo",
      "password": "***",
      "kwargs": {"database": "highgo", "jdbc_url": "", ...}
    }

出参 JSON 结构::

    {"ok": true, "msg": "HighGo Database V6.0"}
    {"ok": false, "msg": "连接被拒绝: ..."}
"""

import json
import os
import sys

# 结果行前缀：主进程按此前缀从 stdout 中提取唯一结果行
RESULT_PREFIX = "__DBCHECK_JDBC_TEST_RESULT__"

# 本 CLI 支持隔离执行的数据库类型（均为进程内 JVM/JPype 实现）
SUPPORTED_DB_TYPES = ('hgdb', 'db2', 'sqlserver_jdbc')


def _ensure_project_root_on_path():
    """确保项目根目录在 sys.path 上（开发态 `python modules/jdbc_test_cli.py`）。

    冻结态由 PyInstaller 处理导入，无需干预；开发态直接执行本文件时
    ``sys.path[0]`` 是 ``modules/``，需要把上级目录补进去才能 import modules.*。
    """
    if getattr(sys, 'frozen', False):
        return
    _root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    if _root not in sys.path:
        sys.path.insert(0, _root)


def _find_plugin_dir(db_type):
    """按 db_type 查找**已启用**插件目录。

    Args:
        db_type: 插件声明的数据库类型标识

    Returns:
        (plugin_dir, err)：成功时 err 为 None；失败时 plugin_dir 为 None
    """
    try:
        from modules.pluginkit.loader import discover_plugins
    except Exception as e:  # noqa: BLE001 - 冻结环境缺模块时给出可读原因
        return None, f'插件加载器不可用: {e}'

    try:
        plugins = discover_plugins()
    except Exception as e:  # noqa: BLE001
        return None, f'插件发现失败: {e}'

    for p in plugins:
        if not p.get('enabled'):
            continue
        # 兼容单类型（db_type）与多类型（db_types）两种声明形式
        if p.get('db_type') == db_type or db_type in (p.get('db_types') or []):
            path = p.get('path')
            if path and os.path.isdir(path):
                return path, None
            return None, f'插件目录不存在: {path}'
    return None, f'插件 {db_type} 未启用或不存在'


def _load_plugin_module(plugin_dir):
    """从插件目录动态加载 ``main_plugin.py``。

    Args:
        plugin_dir: 插件根目录

    Returns:
        (module, err)
    """
    import importlib.util

    plugin_path = os.path.join(plugin_dir, 'main_plugin.py')
    if not os.path.exists(plugin_path):
        return None, f'插件主文件不存在: {plugin_path}'

    # 插件内部普遍使用顶层导入（同目录同级模块），需要把插件目录加入 sys.path
    if plugin_dir not in sys.path:
        sys.path.insert(0, plugin_dir)

    try:
        spec = importlib.util.spec_from_file_location('dbcheck_jdbc_test_plugin', plugin_path)
        if spec is None or spec.loader is None:
            return None, f'无法加载插件模块: {plugin_path}'
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module, None
    except Exception as e:  # noqa: BLE001
        return None, f'插件模块导入失败: {e}'


def _tcp_preflight(host, port, timeout=8):
    """JDBC 之前先做一次纯 Python 的 TCP 连通性探测。

    JVM 冷启动要 4~10 秒，而各家 JDBC 驱动的 loginTimeout 语义并不统一
    （Db2 JCC 的 loginTimeout 在部分版本里管不住 TCP connect，会一路挂到
    操作系统级超时，Windows 上约 21 秒）。主机不可达 / 端口未开 / 防火墙丢包
    是最常见的失败场景，用 socket 先探一下即可在几秒内给出准确原因，
    既不用启 JVM，也不会撞上外层硬超时被强杀（那样只能返回笼统的"超时"）。

    Args:
        host / port: 目标地址
        timeout: 探测超时（秒）

    Returns:
        err: None 表示可达（或参数不全无法探测，放行）；否则为可读错误串
    """
    import socket

    if not host:
        return None
    try:
        port = int(port)
    except (TypeError, ValueError):
        return None

    try:
        sock = socket.create_connection((str(host), port), timeout=timeout)
        sock.close()
        return None
    except socket.timeout:
        return (f'无法连接 {host}:{port}（TCP 握手超时 {timeout} 秒）。'
                f'请检查主机地址、端口是否正确，以及防火墙/安全组是否放行。')
    except OSError as e:
        return (f'无法连接 {host}:{port}（{e.strerror or e}）。'
                f'请确认数据库服务已启动并在该端口监听。')


def run_test(payload):
    """执行一次 JDBC 连接测试。

    Args:
        payload: 入参 dict（见模块 docstring）

    Returns:
        (ok: bool, msg: str)
    """
    db_type = (payload.get('db_type') or '').strip()
    if not db_type:
        return False, '缺少 db_type'

    # Oracle（原生 oracledb）连接测试：
    # oracledb thin 模式与 gevent monkey-patch 不兼容（连接会挂死），且启用 Instant
    # Client 时的 thick/OCI 原生库同样会在被 patch 的主进程里钉死 hub。因此必须像
    # JVM 类 JDBC 数据源一样，在未被 patch 的干净子进程内执行。逻辑直接复用
    # app._ct_oracle_pro（含 SSH 隧道 + thick 回退），避免重复实现。
    if db_type == 'oracle':
        try:
            from modules.web.app import _ct_oracle_pro
        except Exception as e:  # noqa: BLE001 - 子进程内导入失败要转成可读错误
            return False, f'Oracle 测试器不可用: {e}'
        _data = {
            'host': payload.get('host'),
            'port': payload.get('port'),
            'user': payload.get('user'),
            'password': payload.get('password'),
        }
        _data.update(payload.get('kwargs') or {})
        try:
            r = _ct_oracle_pro(_data)
        except Exception as e:  # noqa: BLE001
            return False, f'Oracle 连接测试异常: {e}'
        return bool(r.get('ok')), str(r.get('message') or r.get('error') or '')

    # 自定义 jdbc_url 可能指向别的地址（含多主机/故障转移），此时不做预检
    _kw = payload.get('kwargs') or {}
    if not (isinstance(_kw, dict) and _kw.get('jdbc_url')):
        _err = _tcp_preflight(payload.get('host'), payload.get('port'))
        if _err:
            return False, _err

    plugin_dir, err = _find_plugin_dir(db_type)
    if err:
        return False, err

    module, err = _load_plugin_module(plugin_dir)
    if err:
        return False, err

    if not hasattr(module, 'test_connection'):
        return False, f'插件 {db_type} 未提供 test_connection 函数'

    kwargs = payload.get('kwargs') or {}
    if not isinstance(kwargs, dict):
        kwargs = {}

    try:
        result = module.test_connection(
            payload.get('host'),
            payload.get('port'),
            payload.get('user'),
            payload.get('password'),
            **kwargs,
        )
    except TypeError as e:
        # 插件签名不接受某些 kwargs 时降级为最小参数集重试，避免直接失败
        try:
            result = module.test_connection(
                payload.get('host'), payload.get('port'),
                payload.get('user'), payload.get('password'),
            )
        except Exception as e2:  # noqa: BLE001
            return False, f'调用插件 test_connection 失败: {e} / {e2}'
    except Exception as e:  # noqa: BLE001
        return False, str(e)

    # 插件约定返回 (ok, msg)；兼容仅返回 bool 的旧实现
    if isinstance(result, tuple) and len(result) >= 2:
        return bool(result[0]), str(result[1] or '')
    return bool(result), ''


def main(argv=None):
    """子进程入口：stdin 读 JSON，stdout 写单行结果。

    Returns:
        进程退出码：0 表示流程正常（连接失败也算正常流程，结果在 JSON 里），
        2 表示入参不可解析。
    """
    _ensure_project_root_on_path()

    raw = ''
    try:
        raw = sys.stdin.read()
    except Exception:  # noqa: BLE001
        raw = ''

    try:
        payload = json.loads(raw) if raw.strip() else {}
    except Exception as e:  # noqa: BLE001
        _emit({'ok': False, 'msg': f'入参 JSON 解析失败: {e}'})
        return 2

    try:
        ok, msg = run_test(payload)
    except BaseException as e:  # noqa: BLE001 - 子进程内任何异常都要转成结果行
        ok, msg = False, f'连接测试异常: {e}'

    _emit({'ok': bool(ok), 'msg': msg})
    return 0


def _emit(obj):
    """输出结果行并立即冲刷（子进程可能被强杀，必须即时落盘到管道）。"""
    try:
        line = RESULT_PREFIX + json.dumps(obj, ensure_ascii=False)
    except Exception:  # noqa: BLE001
        line = RESULT_PREFIX + '{"ok": false, "msg": "结果序列化失败"}'
    sys.stdout.write('\n' + line + '\n')
    try:
        sys.stdout.flush()
    except Exception:
        pass


if __name__ == '__main__':
    sys.exit(main())
