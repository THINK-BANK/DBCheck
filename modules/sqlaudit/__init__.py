"""SQL 审核内置模块（MVP1）。

形态：内置可开关模块（与 modules/inspection、modules/web 同级），非 plugins/ 驱动型插件，
因其强依赖实例管理、规则引擎、RBAC 等内部能力。审计引擎（各库执行计划适配器）后续以
可插拔方式扩展，呼应品牌 X = eXtensible。

MVP1 范围：单实例 MySQL 审核（解析 + 规则 + 评分 + 报告），不执行、执行计划分析关闭。
"""
from flask import Blueprint

bp = Blueprint("sql_audit", __name__, url_prefix="/api/sql-audit")

# 路由在 routes 模块中定义；导入即把路由挂到 bp 上。
from . import routes  # noqa: E402,F401


def register_sql_audit(app) -> None:
    """注册 SQL 审核蓝图。社区版内置，始终可用。"""
    app.register_blueprint(bp)
