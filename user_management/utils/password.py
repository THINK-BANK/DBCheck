# -*- coding: utf-8 -*-
# SPDX-License-Identifier: Apache-2.0
# Copyright 2025-2026 fiyo (Jack Ge) <sdfiyon@gmail.com>
# Author: fiyo (Jack Ge) - https://github.com/fiyo/DBCheck

"""
密码工具 - bcrypt 加密和验证
"""

import bcrypt


def hash_password(plain: str) -> str:
    """将明文密码加密为 bcrypt hash"""
    return bcrypt.hashpw(
        plain.encode('utf-8'),
        bcrypt.gensalt()
    ).decode('utf-8')


def verify_password(plain: str, hashed: str) -> bool:
    """验证明文密码是否匹配 hash"""
    return bcrypt.checkpw(
        plain.encode('utf-8'),
        hashed.encode('utf-8')
    )
