# -*- coding: utf-8 -*-
# SPDX-License-Identifier: Apache-2.0
#
# Copyright (c) 2025-2026 fiyo (Jack Ge) <sdfiyon@gmail.com>
#
# This file is part of DBCheck, an open-source database health inspection tool.
# DBCheck Professional — 专有商业软件，保留一切权利（Proprietary Software, All Rights Reserved）.
# See LICENSE for full license text.
#
"""ClickHouse 连接配置数据类 + JDBC URL 构建器。

字段对齐 web_ui / inspection_dal 透传给插件的实例字典
（database / jdbc_url / ssl / custom_http_headers 等可选）。

设计要点（决策 ⑨）：
  - account/password 经 JDBC 属性 user/password 透传，驱动内部映射为
    X-ClickHouse-User / X-ClickHouse-Key HTTP 头；
  - 自定义 HTTP 头 custom_http_headers 作为额外键值对透传（安全校验防注入，
    见 build_properties 与 _sanitize_header）；
  - SSL/TLS 经 ssl=true 交由驱动走 HTTPS（8443 由驱动按 URL scheme 决定）；
  - Kerberos / mTLS 仅预留扩展位，本版不实现（决策 Q3 / P2）。
"""

from dataclasses import dataclass, field
from typing import Dict


@dataclass
class ClickHouseConnectionConfig:
    """ClickHouse JDBC 连接配置。

    Attributes:
        host: ClickHouse 服务器主机名或 IP
        port: ClickHouse HTTP 端口（默认 8123，JDBC-over-HTTP）
        user: 登录用户名（默认 default）
        password: 登录密码
        database: 目标数据库名（ClickHouse 中可选，留空用 server 默认库）
        jdbc_url: 完整 JDBC URL（可选；以 jdbc:clickhouse 开头则直接透传）
        ssl: 是否启用 SSL/TLS（HTTPS）
        custom_http_headers: 自定义 HTTP 头（决策 ⑨），如
            {'X-ClickHouse-User': ..., 'X-ClickHouse-Key': ...}
        kerberos: 是否启用 Kerberos（预留，本版不实现）
        mtls_keystore: mTLS 密钥库路径（预留，本版不实现）
        mtls_truststore: mTLS 信任库路径（预留，本版不实现）
        connect_timeout_ms: 连接超时（毫秒，可选）
    """

    host: str = "127.0.0.1"
    port: int = 8123
    user: str = "default"
    password: str = ""
    database: str = ""
    jdbc_url: str = ""
    ssl: bool = False
    custom_http_headers: Dict[str, str] = field(default_factory=dict)
    kerberos: bool = False
    mtls_keystore: str = ""
    mtls_truststore: str = ""
    connect_timeout_ms: int = 10000

    def build_jdbc_url(self) -> str:
        """构建 JDBC URL。

        - 若 jdbc_url 以 'jdbc:clickhouse' 开头：原样透传（支持自定义属性）
        - 否则按标准格式拼接： jdbc:clickhouse://{host}:{port}/{database}

        Returns:
            可用的 JDBC 连接 URL 字符串
        """
        if self.jdbc_url and str(self.jdbc_url).strip().lower().startswith("jdbc:clickhouse"):
            return self.jdbc_url.strip()
        db_part = "/%s" % self.database.strip() if self.database and self.database.strip() else ""
        return f"jdbc:clickhouse://{self.host}:{self.port}{db_part}"

    @staticmethod
    def _sanitize_header(key: str, value: str) -> bool:
        """校验自定义 HTTP 头键值是否安全（防 CRLF / 头注入）。

        Returns:
            True 表示通过校验（键值均不含控制字符/换行且键名合规）。
        """
        if not isinstance(key, str) or not key:
            return False
        # 键名只允许可见 ASCII 字母数字及连字符/下划线
        for ch in key:
            if not (ch.isalnum() or ch in "-_"):
                return False
        # 键值禁止回车/换行等控制字符（CRLF 注入）
        for ch in str(value):
            if ord(ch) < 0x20 or ch in "\r\n":
                return False
        if len(str(value)) > 4096:
            return False
        return True

    def build_properties(self) -> Dict[str, str]:
        """构建 JDBC 连接属性字典。

        返回 Python dict；main_plugin 负责转换为 java.util.Properties 并
        与 url 一并交给 DriverManager.getConnection(url, props)。

        认证映射（决策 ⑨）：user/password -> X-ClickHouse-User/X-ClickHouse-Key
        （由 clickhouse-jdbc 驱动内部完成映射）。自定义 HTTP 头作为额外属性透传。

        Returns:
            连接属性字典（含 user / password / ssl / 自定义头）
        """
        props: Dict[str, str] = {
            "user": self.user,
            "password": self.password,
        }
        if self.connect_timeout_ms and self.connect_timeout_ms > 0:
            # ClickHouse JDBC 客户端 socket 超时（毫秒）
            props["socket_timeout"] = str(self.connect_timeout_ms)

        if self.ssl:
            props["ssl"] = "true"

        # 自定义 HTTP 头透传（安全校验后）
        for k, v in (self.custom_http_headers or {}).items():
            if self._sanitize_header(k, v):
                props[str(k)] = str(v)
            else:
                print(f"[ClickHouse] 跳过不安全的自定义 HTTP 头: {k}")

        return props

    @classmethod
    def from_instance(cls, inst: dict) -> "ClickHouseConnectionConfig":
        """从 web_ui / inspection_dal 透传的实例字典构建配置。

        Args:
            inst: 含 host/port/user/password/database/jdbc_url/ssl/
                  custom_http_headers 等键的字典（缺失键使用默认值）。

        Returns:
            ClickHouseConnectionConfig 实例
        """
        if not inst:
            inst = {}

        def _get_str(key: str, default: str = "") -> str:
            val = inst.get(key, default)
            return str(val) if val is not None else default

        def _get_bool(key: str, default: bool = False) -> bool:
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

        raw_headers = inst.get("custom_http_headers") or {}
        if isinstance(raw_headers, str):
            # 允许以 "k1=v1;k2=v2" 形式传入
            parsed: Dict[str, str] = {}
            for part in raw_headers.split(";"):
                if "=" in part:
                    k, v = part.split("=", 1)
                    parsed[k.strip()] = v.strip()
            raw_headers = parsed
        if not isinstance(raw_headers, dict):
            raw_headers = {}

        return cls(
            host=_get_str("host", "127.0.0.1") or "127.0.0.1",
            port=_get_int("port", 8123) or 8123,
            user=_get_str("user", "default") or "default",
            password=_get_str("password", ""),
            database=_get_str("database", ""),
            jdbc_url=_get_str("jdbc_url", ""),
            ssl=_get_bool("ssl", False),
            custom_http_headers={str(k): str(v) for k, v in raw_headers.items()},
            kerberos=_get_bool("kerberos", False),
            mtls_keystore=_get_str("mtls_keystore", ""),
            mtls_truststore=_get_str("mtls_truststore", ""),
            connect_timeout_ms=_get_int("connect_timeout_ms", 10000),
        )

    def __repr__(self) -> str:
        """安全的字符串表示（隐藏密码）。"""
        safe_pass = "***" if self.password else ""
        return (
            f"ClickHouseConnectionConfig(host={self.host!r}, port={self.port}, "
            f"database={self.database!r}, user={self.user!r}, "
            f"jdbc_url={self.jdbc_url!r}, ssl={self.ssl}, "
            f"custom_http_headers={list(self.custom_http_headers.keys())}, "
            f"password={safe_pass!r})"
        )
