# -*- coding: utf-8 -*-
# SPDX-License-Identifier: Apache-2.0
# Copyright 2025-2026 fiyo (Jack Ge) <sdfiyon@gmail.com>
# Author: fiyo (Jack Ge) - https://github.com/fiyo/DBCheck

"""DocKB — 官方数据库文档知识库（结构化事实 + 引用链接）内容层与 API。

定位：AI 诊断的「官方文档参考」数据源。Phase 0/1 为纯结构化 SQL 检索，零 embedding 依赖，
      通过 modules.rag.RAGRetriever 把命中事实喂进 rag_context，让 AI「边分析边引官方文档」。
数据存 data/doc_kb.db（不进 git）。蓝图注册沿用 sql_audit 范式。
"""
from flask import Blueprint

bp = Blueprint("doc_kb", __name__, url_prefix="/api/doc-kb")

# 路由在 routes 模块中定义；导入即把路由挂到 bp 上。
from . import routes  # noqa: E402,F401
from .models import lookup_for_diagnosis, ensure_db  # 供 modules.rag 直接调用


def register_doc_kb(app) -> None:
    """注册 DocKB 蓝图并幂等建表（社区版内置，始终可用）。"""
    # 幂等建表（建表失败仅降级告警，不阻断应用启动）
    try:
        from .models import ensure_db
        ensure_db()
    except Exception as e:
        print(f"[doc_kb][WARN] 建表失败（降级）: {e}")
    app.register_blueprint(bp)
