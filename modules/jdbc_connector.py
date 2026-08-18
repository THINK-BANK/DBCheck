# -*- coding: utf-8 -*-
# SPDX-License-Identifier: Apache-2.0
# Copyright 2025-2026 fiyo (Jack Ge) <sdfiyon@gmail.com>
# Author: fiyo (Jack Ge) - https://github.com/fiyo/DBCheck
"""
统一 JDBC 连接层（jdbc_connector）

目标：所有走 JDBC 的数据库类型（8 类：6 个 JDBC 插件 + 核心内置 dm/gbase）
共用同一套连接方法 —— 每种库只差「连接串模板 + 驱动类」，其余全部统一：

  - 驱动解析：driver_registry.resolve_jdbc_driver_jars（驱动管理优先，目录兜底）
  - JVM 启动：addClassPath 必须在 startJVM 之前；JVM 已启动则补 classpath
  - 建连：jaydebeapi.connect(driver_class, jdbc_url, [user, password], jars)
  - 报错规范化：统一返回 (conn, meta) / (None, err)

注册表 JDBC_PROFILES 的 key 是「巡检/数据源分派令牌」（与前端下拉、plugin.json
db_type 一致）：oracle_jdbc / sqlserver_jdbc / db2 / hgdb / clickhouse / uxdb /
dm / gbase。新增 JDBC 类型只需在 driver_registry 登记驱动 + 本表加一行模板。
"""
from __future__ import annotations

import os
import sys
from typing import Any, Dict, List, Optional, Tuple

from modules.driver_registry import JDBC_PLUGIN_TO_CATALOG, resolve_jdbc_driver_jars

# ═══════════════════════════════════════════════════════════════════════════
# 注册表：分派令牌 → 连接串模板
# 模板占位符：{host} {port} {db} {service} {server}；None/空 的段自动回退默认
# ═══════════════════════════════════════════════════════════════════════════
JDBC_PROFILES: Dict[str, Dict[str, Any]] = {
    'oracle_jdbc': {
        'driver_class': 'oracle.jdbc.driver.OracleDriver',
        # use_sid=True 时走 @host:port:SID 旧格式（见 build_jdbc_url 特判）
        'url': 'jdbc:oracle:thin:@//{host}:{port}/{service}',
        'port': 1521,
        'service_default': 'ORCLCDB',
    },
    'sqlserver_jdbc': {
        'driver_class': 'com.microsoft.sqlserver.jdbc.SQLServerDriver',
        # encrypt/trust/instance_name 逻辑在 build_jdbc_url 特判（SQL Server 细节多）
        'url': 'jdbc:sqlserver://{host}:{port};databaseName={db}',
        'port': 1433,
        'db_default': 'master',
    },
    'db2': {
        'driver_class': 'com.ibm.db2.jcc.DB2Driver',
        'url': 'jdbc:db2://{host}:{port}/{db}',
        'port': 50000,
    },
    'hgdb': {
        'driver_class': 'com.highgo.jdbc.Driver',
        # HighGo 兼容 PostgreSQL 协议
        'url': 'jdbc:postgresql://{host}:{port}/{db}',
        'port': 5866,
    },
    'clickhouse': {
        'driver_class': 'com.clickhouse.jdbc.ClickHouseDriver',
        'url': 'jdbc:clickhouse://{host}:{port}/{db}',
        'port': 8123,
        'db_default': 'default',
    },
    'uxdb': {
        'driver_class': 'uxdb.Driver',
        'url': 'jdbc:uxdb://{host}:{port}/{db}',
        'port': 33060,
    },
    'dm': {
        'driver_class': 'dm.jdbc.driver.DmDriver',
        'url': 'jdbc:dm://{host}:{port}',
        'port': 5236,
        'db_default': 'DAMENG',
    },
    'gbase': {
        'driver_class': 'com.gbasedbt.jdbc.Driver',
        'url': 'jdbc:gbasedbt-sqli://{host}:{port}/{db}:GBASEDBTSERVER={server};',
        'port': 9088,
        'db_default': 'gbase01',
        'server_default': 'gbase01',
    },
}

# 需要隔离到 JVM 子进程的 JDBC 类型全集（与 jdbc_inspection_cli.JVM_INSPECTION_DB_TYPES 对齐，
# 供调用方快速判定；单一事实来源在 driver_registry.JDBC_PLUGIN_TO_CATALOG）。
JDBC_DB_TYPES: Tuple[str, ...] = tuple(JDBC_PROFILES.keys())


# ═══════════════════════════════════════════════════════════════════════════
# JAVA_HOME 探测（与 main_gbase / 各插件的探测逻辑合并后的统一版本）
# ═══════════════════════════════════════════════════════════════════════════
def detect_java_home() -> Optional[str]:
    """探测 JAVA_HOME：优先环境变量，其次常见安装路径。返回 None 表示未找到。"""
    _env = os.environ.get('JAVA_HOME') or os.environ.get('JRE_HOME')
    if _env and os.path.isdir(_env):
        return _env
    _candidates = []
    if sys.platform == 'win32':
        _candidates = [
            r'C:\Program Files\Java\jdk-17',
            r'C:\Program Files\Java\jdk-11',
            r'C:\Program Files\Java\jdk-1.8',
            r'C:\Program Files\Java\jre-1.8',
            r'C:\Program Files\Microsoft\jdk-17.0.12.7-hotspot',
            r'C:\Program Files\Eclipse Adoptium',
            r'C:\Program Files\Zulu',
        ]
        for _base in _candidates:
            if os.path.isdir(_base):
                # 返回含 bin/server 的 JDK 根；Adoptium/Zulu 下有多版本子目录，取第一个
                if os.path.isdir(os.path.join(_base, 'bin', 'server')):
                    return _base
                try:
                    for _sub in sorted(os.listdir(_base)):
                        _p = os.path.join(_base, _sub)
                        if os.path.isdir(os.path.join(_p, 'bin', 'server')):
                            return _p
                except OSError:
                    pass
    else:
        for _cand in ('/usr/lib/jvm/java-17-openjdk', '/usr/lib/jvm/java-11-openjdk',
                      '/usr/lib/jvm/java-8-openjdk', '/usr/lib/jvm/default-java'):
            if os.path.isdir(_cand):
                return _cand
    return None


def setup_jvm_env() -> None:
    """设置 JAVA_HOME / PATH，供 startJVM 使用（幂等）。"""
    _java_home = detect_java_home()
    if _java_home:
        os.environ['JAVA_HOME'] = _java_home
        _jvm_dir = os.path.join(_java_home, 'bin', 'server')
        if os.path.isdir(_jvm_dir):
            os.environ['PATH'] = _jvm_dir + os.pathsep + os.environ.get('PATH', '')


# ═══════════════════════════════════════════════════════════════════════════
# 连接串构造：每种库只差这里
# ═══════════════════════════════════════════════════════════════════════════
def build_jdbc_url(
    db_type: str,
    host: str,
    port: Optional[int] = None,
    database: Optional[str] = None,
    service_name: Optional[str] = None,
    use_sid: bool = False,
    gbase_server_name: Optional[str] = None,
    encrypt: Optional[bool] = None,
    trust_server_certificate: Optional[bool] = None,
    jdbc_url: Optional[str] = None,
    **extra: Any,
) -> str:
    """按分派令牌构造 JDBC URL。

    - jdbc_url 非空 → 原样透传（支持用户自定义/多主机/故障转移，调用方自行保证格式）
    - 否则按 JDBC_PROFILES[db_type].url 模板填充；未知类型回退
      ``jdbc:<db_type>://host:port`` 最简格式（仍可连，报错信息友好）。
    """
    if jdbc_url and str(jdbc_url).strip():
        return str(jdbc_url).strip()

    _prof = JDBC_PROFILES.get(db_type) or {}
    _tpl = _prof.get('url') or f'jdbc:{db_type}://{{host}}:{{port}}'
    _port = int(port or _prof.get('port') or 0)
    _db = database or _prof.get('db_default') or ''
    # 空库名：去掉 /{db} 段（clickhouse/db2/hgdb 统一行为：不产生尾部斜杠）
    if not _db:
        _tpl = _tpl.replace('/{db}', '')

    # Oracle：use_sid 走 @host:port:SID 旧格式（service_name 字段承载 SID 值）
    if db_type == 'oracle_jdbc' and use_sid:
        _sid = service_name or _prof.get('service_default') or 'ORCL'
        return f'jdbc:oracle:thin:@{host}:{_port}:{_sid}'

    # SQL Server：encrypt=false 时省略 trustServerCertificate（部分驱动/服务器在
    # 强制加密场景下带 false 会走异常 SSL 分支报 unexpected_message）；命名实例
    # 不带端口，由 SQL Browser 解析（instance_name 经 extra 传入）。
    if db_type == 'sqlserver_jdbc':
        _instance = extra.get('instance_name') or ''
        _host_part = f'{host};instanceName={_instance}' if _instance else f'{host}:{_port}'
        _url = f'jdbc:sqlserver://{_host_part};databaseName={_db or "master"}'
        if encrypt:
            _trust = 'true' if trust_server_certificate else 'false'
            _url += f';encrypt=true;trustServerCertificate={_trust};sslProtocol=TLSv1.2'
        else:
            _url += ';encrypt=false'
        return _url

    _svc = service_name or _prof.get('service_default') or _db
    _server = gbase_server_name or _prof.get('server_default') or 'gbase01'

    _url = _tpl.format(
        host=host,
        port=_port,
        db=_db,
        service=_svc,
        server=_server,
        encrypt='true' if encrypt else 'false',
        trust='true' if trust_server_certificate else 'false',
    )
    return _url


# ═══════════════════════════════════════════════════════════════════════════
# 驱动解析：驱动管理优先，目录自动发现兜底
# ═══════════════════════════════════════════════════════════════════════════
def _sort_jars_by_version(jars: List[str]) -> List[str]:
    """按文件名中的数字版本降序排序（DmJdbcDriver18 > 11 > 8 > 7 > 6），
    避免字符串序把 DmJdbcDriver6 排到 18 前面。"""
    import re

    def _ver(p: str):
        _m = re.search(r'(\d+)', os.path.basename(p))
        return int(_m.group(1)) if _m else 0
    return sorted(jars, key=_ver, reverse=True)


def resolve_driver_jars(db_type: str, driver_version: str = '', *,
                        fallback_dirs: Optional[List[str]] = None,
                        recursive: bool = False) -> Optional[List[str]]:
    """解析驱动 jar 列表。

    1) 驱动管理（登记/激活/指定版本）：resolve_jdbc_driver_jars
    2) fallback_dirs 提供的目录 glob（如 drivers/dm8/、drivers/gbase/）；
       recursive=True 时含子目录（drivers/dm/ 下按版本分子目录），
       结果按文件名数字版本降序（高版本优先）。
    """
    try:
        _resolved = resolve_jdbc_driver_jars(db_type, driver_version or None)
        if _resolved:
            return _resolved
    except Exception:  # noqa: BLE001
        pass
    for _d in (fallback_dirs or []):
        if not _d or not os.path.isdir(_d):
            continue
        import glob
        _pat = os.path.join(_d, '**', '*.jar') if recursive else os.path.join(_d, '*.jar')
        _jars = _sort_jars_by_version(glob.glob(_pat, recursive=recursive))
        if _jars:
            return _jars
    return None


def _start_jvm(jars: List[str]) -> None:
    """启动 JVM：addClassPath 必须在 startJVM 之前；已启动则补 classpath。"""
    import jpype
    setup_jvm_env()
    if not jpype.isJVMStarted():
        try:
            for _jar in jars:
                jpype.addClassPath(_jar)
            jpype.startJVM()
        except Exception:  # noqa: BLE001 - JVM 启动失败由调用方抛连接错误
            pass
    else:
        try:
            for _jar in jars:
                jpype.addClassPath(_jar)
        except Exception:  # noqa: BLE001
            pass


# ═══════════════════════════════════════════════════════════════════════════
# 统一建连入口
# ═══════════════════════════════════════════════════════════════════════════
def open_jdbc_connection(
    db_type: str,
    host: str,
    port: Optional[int] = None,
    user: str = '',
    password: str = '',
    driver_version: str = '',
    jdbc_url: Optional[str] = None,
    database: Optional[str] = None,
    service_name: Optional[str] = None,
    use_sid: bool = False,
    gbase_server_name: Optional[str] = None,
    encrypt: Optional[bool] = None,
    trust_server_certificate: Optional[bool] = None,
    fallback_dirs: Optional[List[str]] = None,
    **extra: Any,
) -> Tuple[Any, Dict[str, Any]]:
    """统一 JDBC 建连。

    Returns:
        (conn, meta) 或 (None, {'error': ...})。
        meta 含 driver / url / driver_class，供日志与错误提示。
    """
    _prof = JDBC_PROFILES.get(db_type) or {}
    _url = build_jdbc_url(
        db_type, host, port,
        database=database, service_name=service_name, use_sid=use_sid,
        gbase_server_name=gbase_server_name, encrypt=encrypt,
        trust_server_certificate=trust_server_certificate, jdbc_url=jdbc_url,
    )

    _jars = resolve_driver_jars(db_type, driver_version, fallback_dirs=fallback_dirs)
    if not _jars:
        _catalog = JDBC_PLUGIN_TO_CATALOG.get(db_type, db_type)
        return None, {
            'error': f'{db_type} JDBC 驱动未找到：请到「数据库驱动管理」上传 {_catalog} 驱动，'
                     f'或放入 drivers/{_catalog}/ 目录',
            'driver': None, 'url': _url, 'driver_class': _prof.get('driver_class'),
        }

    try:
        import jaydebeapi
    except Exception as e:  # noqa: BLE001
        return None, {'error': f'未安装 jaydebeapi：{e}', 'driver': None,
                      'url': _url, 'driver_class': _prof.get('driver_class')}

    _start_jvm(_jars)

    _driver_class = _prof.get('driver_class')
    _basename = os.path.basename(_jars[0]) if _jars else ''
    try:
        conn = jaydebeapi.connect(
            _driver_class, _url, [user, password], _jars,
        )
        return conn, {'driver': _basename, 'url': _url, 'driver_class': _driver_class}
    except Exception as e:  # noqa: BLE001
        _err = f'{db_type} JDBC 连接失败: {e}\nJDBC URL: {_url}\n驱动: {_basename}'
        # 达梦 -70089：服务端开启通信加密（COMM_ENCRYPT）时，驱动
        # （DmCipherEncryptDLL.loadLibrary('zbCrypto')）需 JNI 加载本机达梦
        # 客户端原生加密库；未安装客户端即报 -70089。与驱动版本新旧无关。
        if db_type == 'dm' and ('-70089' in str(e) or 'Encryption module' in str(e)):
            _err += (
                '\n\n[达梦 -70089 修复指引] 当前达梦服务端开启了通信加密（COMM_ENCRYPT），'
                'JDBC 驱动的加密模块（zbCrypto）依赖本机达梦客户端原生库。请任选其一：\n'
                '  ① 服务端 dm.ini 将 COMM_ENCRYPT 设为 0（不加密）后重启实例；\n'
                '  ② 本机安装达梦数据库客户端（含加密库，安装后其 bin 目录自动生效）；\n'
                '  ③ 若服务端是 DM7/DM6，请改用对应版本的 JDBC 驱动。'
            )
        return None, {'error': _err,
                      'driver': _basename, 'url': _url, 'driver_class': _driver_class}
