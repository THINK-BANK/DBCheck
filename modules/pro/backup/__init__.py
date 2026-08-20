# -*- coding: utf-8 -*-
# SPDX-License-Identifier: Apache-2.0
# Copyright 2025-2026 fiyo (Jack Ge) <sdfiyon@gmail.com>
# Author: fiyo (Jack Ge) - https://github.com/fiyo/DBCheck

"""
RaccoonX Backup Module
数据库备份模块
"""

from .base import BaseBackupEngine, BackupResult
from .mysql_backup import MySQLBackupEngine
from .pg_backup import PGBackupEngine
from .oracle_backup import OracleBackupEngine
from .sqlserver_backup import SQLServerBackupEngine
from .manager import BackupManager, get_backup_manager

__all__ = [
    "BaseBackupEngine",
    "BackupResult",
    "MySQLBackupEngine",
    "PGBackupEngine",
    "OracleBackupEngine",
    "SQLServerBackupEngine",
    "BackupManager",
    "get_backup_manager",
]
