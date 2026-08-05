#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# SPDX-License-Identifier: Apache-2.0
# Copyright 2025-2026 fiyo (Jack Ge) <sdfiyon@gmail.com>
# Author: fiyo (Jack Ge) - https://github.com/fiyo/DBCheck

"""
SQL Server 连接配置数据类 + JDBC URL / Properties 构建器。

字段对齐 web_ui / inspection_dal 透传给插件的实例字典
（database / jdbc_url / instance_name / encrypt / trust_server_certificate 等可选）。

设计要点：
  - JDBC URL 通过 build_jdbc_url() 拼接（支持 jdbc_url 透传与字段拼接两种模式）
  - 加密/连接超时等参数走 build_properties() 返回的字典（main_plugin 转换为
    java.util.Properties 后交给 DriverManager.getConnection(url, props)）
  - 命名实例（host\\instance）通过 instance_name 字段表达，URL 中
    `instanceName=xxx` 替代 `port=1433`
  - 默认 encrypt=true + trustServerCertificate=true（MS JDBC 13.x 要求
    encrypt=true 才能成功握手；trustServerCertificate=true 便于本地开发）
"""

from dataclasses import dataclass
from typing import Dict


@dataclass
class MssqlJdbcConnectionConfig:
    """SQL Server JDBC 连接配置。

    Attributes:
        host: SQL Server 主机名或 IP
        port: 端口（默认实例 1433；命名实例可留空，URL 自动用 instanceName 替代）
        user: 登录用户名（默认 sa）
        password: 登录密码
        database: 目标数据库名（默认 master）
        instance_name: 命名实例名（默认实例留空；非空时 URL 用 instanceName=xxx 替代端口）
        jdbc_url: 完整 JDBC URL（可选；以 jdbc:sqlserver:// 开头则直接透传）
        encrypt: 启用 TLS 加密（MS JDBC 13.x 默认 true，否则连接被拒）
        trust_server_certificate: 信任自签证书（dev 友好，prod 应配置 CA）
        login_timeout_s: 登录超时（秒）
        application_name: 应用标识（DMV sys.dm_exec_sessions.program_name 可见）
    """

    host: str = "127.0.0.1"
    port: int = 1433
    user: str = "sa"
    password: str = ""
    database: str = "master"
    instance_name: str = ""
    jdbc_url: str = ""
    encrypt: bool = True
    trust_server_certificate: bool = True
    login_timeout_s: int = 10
    application_name: str = "DBCheck"

    def build_jdbc_url(self) -> str:
        """构建 JDBC URL。

        优先级：
          1. 若 jdbc_url 以 'jdbc:sqlserver://' 开头 → 原样透传
          2. 若 instance_name 非空 → jdbc:sqlserver://{host};instanceName={instance};...
          3. 否则 → jdbc:sqlserver://{host}:{port};databaseName={database};...

        Returns:
            可用的 JDBC 连接 URL 字符串
        """
        if self.jdbc_url and str(self.jdbc_url).strip().lower().startswith("jdbc:sqlserver"):
            return self.jdbc_url.strip()

        # 公共参数：databaseName / encrypt / trustServerCertificate / loginTimeout / applicationName
        common_params = (
            f"databaseName={self.database or 'master'}"
            f";encrypt={'true' if self.encrypt else 'false'}"
            f";trustServerCertificate={'true' if self.trust_server_certificate else 'false'}"
            f";loginTimeout={int(self.login_timeout_s) if self.login_timeout_s and self.login_timeout_s > 0 else 10}"
            f";applicationName={self.application_name or 'DBCheck'}"
        )

        if self.instance_name:
            # 命名实例：不带端口；MS JDBC 通过 SQL Browser 解析
            return f"jdbc:sqlserver://{self.host};instanceName={self.instance_name};{common_params}"
        return f"jdbc:sqlserver://{self.host}:{int(self.port) if self.port else 1433};{common_params}"

    def build_properties(self) -> Dict[str, str]:
        """构建 JDBC 连接属性字典。

        返回 Python dict；main_plugin 负责转换为 java.util.Properties 并
        与 user/password 一并交给 DriverManager.getConnection(url, props)。

        Returns:
            连接属性字典（含 user / password）
        """
        props: Dict[str, str] = {
            "user": self.user,
            "password": self.password,
        }
        return props

    @classmethod
    def from_instance(cls, inst: dict) -> "MssqlJdbcConnectionConfig":
        """从 web_ui / inspection_dal 透传的实例字典构建配置。

        Args:
            inst: 含 host/port/user/password/database/instance_name/jdbc_url/
                  encrypt/trust_server_certificate 等键的字典（缺失键使用默认值，
                  向后兼容）

        Returns:
            MssqlJdbcConnectionConfig 实例
        """
        if not inst:
            inst = {}

        def _get_str(key: str, default: str = "") -> str:
            val = inst.get(key, default)
            return str(val) if val is not None else default

        def _get_bool(key: str, default: bool) -> bool:
            val = inst.get(key, default)
            if isinstance(val, bool):
                return val
            if isinstance(val, str):
                return val.strip().lower() in ("true", "1", "yes", "on")
            return bool(val)

        def _get_int(key: str, default: int) -> int:
            try:
                return int(inst.get(key, default))
            except (TypeError, ValueError):
                return default

        return cls(
            host=_get_str("host", "127.0.0.1") or "127.0.0.1",
            port=_get_int("port", 1433) or 1433,
            user=_get_str("user", "sa") or "sa",
            password=_get_str("password", ""),
            database=_get_str("database", "master") or "master",
            instance_name=_get_str("instance_name", ""),
            jdbc_url=_get_str("jdbc_url", ""),
            encrypt=_get_bool("encrypt", True),
            trust_server_certificate=_get_bool("trust_server_certificate", True),
            login_timeout_s=_get_int("login_timeout_s", 10),
            application_name=_get_str("application_name", "DBCheck") or "DBCheck",
        )

    def __repr__(self) -> str:
        """安全的字符串表示（隐藏密码）。"""
        safe_pass = "***" if self.password else ""
        return (
            f"MssqlJdbcConnectionConfig(host={self.host!r}, port={self.port}, "
            f"database={self.database!r}, user={self.user!r}, "
            f"instance_name={self.instance_name!r}, "
            f"jdbc_url={self.jdbc_url!r}, encrypt={self.encrypt}, "
            f"trust_server_certificate={self.trust_server_certificate}, "
            f"login_timeout_s={self.login_timeout_s}, "
            f"application_name={self.application_name!r}, "
            f"password={safe_pass!r})"
        )
