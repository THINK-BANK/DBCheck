# -*- coding: utf-8 -*-
# SPDX-License-Identifier: Apache-2.0
# Copyright 2025-2026 fiyo (Jack Ge) <sdfiyon@gmail.com>
# Author: fiyo (Jack Ge) - https://github.com/fiyo/DBCheck

"""
DBCheck Pro Module
专业版核心模块
"""

def is_pro():
    """Return True if this is the professional edition"""
    return False

def get_edition():
    """Return edition name"""
    return 'community'

def register_web_extensions(app):
    """Register professional-only web blueprints.

    Professional branch: registers the Pro flow blueprint.
    The community (main) branch provides a no-op implementation so that
    modules/web/app.py can call this unconditionally while staying byte-identical
    across both branches.
    """
    # 社区版无 Pro Web 扩展，no-op
    return

from .instance_manager import (
    InstanceManager,
    DatabaseInstance,
    InstanceGroup,
    get_instance_manager,
)
from .report_score import (
    ReportScorer,
    ScoreReport,
    ScoreItem,
    InspectionDataScorer,
    format_score_report,
)
from .rule_engine import (
    RuleEngine,
    get_rule_engine,
)
from .backup import (
    BackupManager,
    BackupResult,
    get_backup_manager,
)

__all__ = [
    # Pro status (no license required)
    "is_pro",
    "get_edition",
    "register_web_extensions",
    # Instance
    "InstanceManager",
    "DatabaseInstance",
    "InstanceGroup",
    "get_instance_manager",
    # Report Score
    "ReportScorer",
    "ScoreReport",
    "ScoreItem",
    "InspectionDataScorer",
    "format_score_report",
    # Rule Engine
    "RuleEngine",
    "get_rule_engine",
    # Backup
    "BackupManager",
    "BackupResult",
    "get_backup_manager",
]
