# -*- coding: utf-8 -*-
# SPDX-License-Identifier: Apache-2.0
# Copyright 2025-2026 fiyo (Jack Ge) <sdfiyon@gmail.com>
# Author: fiyo (Jack Ge) - https://github.com/fiyo/DBCheck

"""
密码工具 - bcrypt 加密和验证

兼容性说明（重要）：
- bcrypt < 5 暴露顶层函数 `bcrypt.hashpw` / `bcrypt.checkpw` / `bcrypt.gensalt`。
- bcrypt >= 5.0.0（2025-09-25 发布）**移除了上述顶层函数**，改用
  `bcrypt.hash(password)` / `bcrypt.check(password, hashed)`（详见 pyca/bcrypt
  issue #1082，这是一次 breaking change）。

DBCheck 的依赖约束为 `bcrypt>=4.0.0`（无上限），Docker 多架构（含 arm64）
重新构建 / `pip install -r requirements` 时会解析安装到最新的 5.x，导致
`bcrypt.hashpw` 直接抛 `AttributeError`，进而使登录与修改密码在后端 500、
前端表现为「请求失败 / 网络错误」（Windows 冻结版因锁定旧 bcrypt 故正常）。

因此这里做版本自适应，无论宿主机装的是 4.x 还是 5.x 都能正常工作。
"""

import bcrypt

# bcrypt >= 4.1 新增 hash/check；>= 5 移除 hashpw/checkpw/gensalt。
_BCRYPT_V5 = hasattr(bcrypt, "hash") and hasattr(bcrypt, "check")


def hash_password(plain: str) -> str:
    """将明文密码加密为 bcrypt hash（返回字符串）。"""
    pwd = plain.encode("utf-8")
    if _BCRYPT_V5:
        # bcrypt >= 4.1 的 hash() 接受 bytes/str，返回 str。
        return bcrypt.hash(pwd)
    return bcrypt.hashpw(pwd, bcrypt.gensalt()).decode("utf-8")


def verify_password(plain: str, hashed: str) -> bool:
    """验证明文密码是否匹配 hash。"""
    pwd = plain.encode("utf-8")
    h = hashed.encode("utf-8")
    try:
        if _BCRYPT_V5:
            return bcrypt.check(pwd, h)
        return bcrypt.checkpw(pwd, h)
    except (ValueError, TypeError):
        # bcrypt >= 5 对 >72 字节密码抛 ValueError；非法 hash 抛 TypeError。
        # 一律视为校验失败，避免异常向上冒泡成 500。
        return False
