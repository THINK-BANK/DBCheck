# -*- coding: utf-8 -*-
# SPDX-License-Identifier: Apache-2.0
# Copyright 2025-2026 fiyo (Jack Ge) <sdfiyon@gmail.com>
# Author: fiyo (Jack Ge) - https://github.com/fiyo/DBCheck

"""
权限模型 - 权限定义
"""

from modules.user_management.models.db_manager import DBManager


class PermissionModel:
    """权限数据访问层"""

    def __init__(self):
        self.db = DBManager()

    def get_all(self) -> list:
        return self.db.query_all(
            "SELECT * FROM um_permission ORDER BY perm_level"
        )

    def get_by_code(self, perm_code: str) -> dict:
        return self.db.query_one(
            "SELECT * FROM um_permission WHERE perm_code=?", (perm_code,)
        )

    def get_by_level(self, perm_level: int) -> dict:
        return self.db.query_one(
            "SELECT * FROM um_permission WHERE perm_level=?", (perm_level,)
        )
