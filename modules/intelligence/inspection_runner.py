# SPDX-License-Identifier: Apache-2.0
# Copyright 2025-2026 fiyo (Jack Ge) <sdfiyon@gmail.com>
# Author: fiyo (Jack Ge) - https://github.com/fiyo/DBCheck

"""协同诊断中枢 · 实时巡检引擎调度。

让「深度巡检分析专员」直接调用 DBCheck 巡检引擎，为目标数据源
实时产出一份巡检报告（getData → checkdb → 智能分析），再交给专员解析，
从而保证诊断结论与所选数据源的真实状态严格相关。
"""

from __future__ import annotations

import os
import sys
from typing import Any, Dict, List, Optional

# 确保项目根目录在 sys.path（与 web_ui 运行环境一致）
_SCRIPT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _db_default(db_type: str) -> str:
    return {
        "mysql": "mysql",
        "mariadb": "mysql",
        "pg": "postgres",
        "oracle": "orcl",
        "oracle_jdbc": "orcl",
        "dm": "DAMENG",
        "sqlserver": "master",
        "tidb": "mysql",
        "oceanbase": "sys",
        "ivorysql": "ivorysql",
        "kingbase": "kingbase",
        "yashandb": "YASHANDB",
        "gbase": "testdb",
    }.get(db_type, "")


def _build_db_info(db_type: str, instance: Dict[str, Any]) -> Dict[str, Any]:
    """把实例管理器的解密信息映射成巡检引擎需要的 db_info。"""
    label = instance.get("name") or instance.get("host") or "unknown"
    return {
        "host": instance.get("host", ""),
        "port": int(instance.get("port", 0) or 0),
        "user": instance.get("user", ""),
        "password": instance.get("password", ""),
        "database": instance.get("database") or _db_default(db_type),
        "service_name": instance.get("service_name"),
        "sid": instance.get("sid"),
        "sysdba": bool(instance.get("sysdba", False)),
        "name": instance.get("name", ""),
        "label": label,
    }


def _score(context: Dict[str, Any]):
    """依据巡检上下文计算健康评分 / 风险等级（与 web_ui 流程一致）。"""
    risk_count = context.get("risk_count", 0)
    if not risk_count:
        issues = context.get("issues", [])
        risk_count = len(issues) if isinstance(issues, list) else 0
    health_status = context.get("health_status", "")
    if "优秀" in health_status or "Excellent" in health_status:
        health_score = 100
    elif "良好" in health_status or "Good" in health_status:
        health_score = 80
    elif "一般" in health_status or "Fair" in health_status:
        health_score = 60
    elif "需关注" in health_status or "Attention" in health_status:
        health_score = 40
    else:
        health_score = 100 - min(risk_count * 5, 50)
    if health_score >= 85:
        risk_level = "healthy"
    elif health_score >= 70:
        risk_level = "low"
    elif health_score >= 50:
        risk_level = "medium"
    elif health_score >= 30:
        risk_level = "high"
    else:
        risk_level = "critical"
    return health_score, risk_count, risk_level, health_status


# 插件类型 db_type → smart_analyze_* 名称（当插件 get_task_config 未声明 smart_analyze 时的兜底）
_PLUGIN_ANALYZER_MAP = {
    "uxdb": "smart_analyze_pg",
    "redis": "smart_analyze_redis",
    "redis-cluster": "smart_analyze_redis_cluster",
    "mongodb": "smart_analyze_mongodb",
    "clickhouse": "smart_analyze_clickhouse",
    "db2": "smart_analyze_db2",
}


def _build_plugin_info(db_type: str, instance: Dict[str, Any]) -> Dict[str, Any]:
    """把实例管理器字典映射为插件 connect_test/getData 期望的 pinfo。

    与 web_ui.py:580-877 的特例对齐：
      - uxdb：database 为空或 'postgres' 时置 'uxdb'
      - mongodb：透传 connect_mode/auth_source/auth_mechanism/replica_set/tls*
      - redis/redis-cluster：透传 database/seed_nodes
    其余字段（ip/host/port/user/password/name/ssh_*）原样透传。
    """
    db = instance.get("database")
    if db_type == "mongodb" and not db:
        db = "admin"
    elif not db:
        db = _db_default(db_type)
    pinfo: Dict[str, Any] = {
        "ip": instance.get("host", ""),
        "host": instance.get("host", ""),
        "port": int(instance.get("port", 0) or 0),
        "user": instance.get("user", ""),
        "password": instance.get("password", ""),
        "name": instance.get("name", ""),
        "database": db,
        "template_id": instance.get("template_id"),
    }
    for _k in ("ssh_host", "ssh_port", "ssh_user", "ssh_password", "ssh_key_file"):
        if _k in instance:
            pinfo[_k] = instance[_k]
    # 类型特例
    if db_type == "uxdb":
        if not pinfo.get("database") or pinfo.get("database") == "postgres":
            pinfo["database"] = "uxdb"
    if db_type == "mongodb":
        for _mk in ("connect_mode", "auth_source", "auth_mechanism",
                    "replica_set", "tls", "tls_ca_file", "tls_cert_key_file",
                    "tls_allow_invalid_certs"):
            if _mk in instance:
                pinfo[_mk] = instance[_mk]
    if db_type in ("redis", "redis-cluster"):
        for _mk in ("database", "seed_nodes"):
            if _mk in instance:
                pinfo[_mk] = instance[_mk]
    return pinfo


def _run_plugin_inspection(
    db_type: str,
    instance: Dict[str, Any],
    goal: str = "",
    inspector_name: str = "Jack",
) -> Optional[Dict[str, Any]]:
    """插件类型实时巡检（复用 plugin_loader 已验证路径，与 Web UI 同源）。

    成功返回与内置路径同构的 report dict；找不到可用插件返回 None（交由主流程回退
    「暂不支持」）；插件连接/采集/分析失败则返回 ok=False 的同构 report（软降级，
    由上层 inspection_expert 走「回退历史报告」，诊断整体不崩溃）。
    """
    instance_name = instance.get("name") or instance.get("host") or ""

    # 配置加载（驱动缺失可能导致插件模块导入失败 → 软降级为 ok=False report）
    try:
        from modules.pluginkit.loader import get_plugin_task_config

        cfg = get_plugin_task_config(db_type)
    except Exception as e:
        return {
            "ok": False,
            "error": f"插件配置加载失败：{e}",
            "auto_analyze": [],
            "db_type": db_type,
            "instance_name": instance_name,
        }
    if not cfg:
        return None

    try:
        import importlib.util
        import os

        plugin_path = cfg.get("plugin_path")
        main_file = cfg.get("main_file", "main_plugin.py")
        if not plugin_path:
            raise RuntimeError("插件路径缺失")
        main_path = os.path.join(plugin_path, main_file)
        spec = importlib.util.spec_from_file_location(f"plugin_{db_type}", main_path)
        if spec is None:
            raise RuntimeError("插件模块加载失败")
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)

        pinfo = _build_plugin_info(db_type, instance)

        # 连接测试（与 web_ui.py:855 一致）
        ok, ver = cfg["connect_test"](*cfg["connect_test_args"](pinfo))
        if not ok:
            raise RuntimeError(f"连接失败：{ver}")

        # 数据采集（与 web_ui.py:894-905 一致）
        _pos, _kw = cfg["getdata_args"](pinfo)
        data = mod.getData(*_pos, **_kw)
        conn_attr = cfg.get("conn_attr")
        if conn_attr and getattr(data, conn_attr, None) is None:
            raise RuntimeError("数据采集失败（无可用连接）")

        # 产出巡检上下文（优先 getData→checkdb，退化到 collect_data）
        if hasattr(data, "checkdb") and callable(data.checkdb):
            context = data.checkdb("builtin")
        elif hasattr(mod, "collect_data"):
            cd = mod.collect_data("")
            if isinstance(cd, tuple) and len(cd) == 2 and cd[0] is False:
                raise RuntimeError(cd[1])
            context = cd if isinstance(cd, dict) else {}
        else:
            context = {}
        if not context:
            raise RuntimeError("巡检上下文为空")

        context["co_name"] = [{"CO_NAME": pinfo.get("database") or pinfo.get("name", "")}]
        context["port"] = [{"PORT": pinfo.get("port")}]
        context["ip"] = [{"IP": pinfo.get("ip")}]

        # 智能分析（优先插件声明的 smart_analyze，缺失回退 _PLUGIN_ANALYZER_MAP）
        analyzer_name = cfg.get("smart_analyze") or _PLUGIN_ANALYZER_MAP.get(db_type)
        auto_analyze: List[Dict[str, Any]] = []
        if analyzer_name:
            import modules.inspection.analyzer as _analyzer

            try:
                auto_analyze = list(getattr(_analyzer, analyzer_name)(context) or [])
            except Exception:
                auto_analyze = []

        # 插件附加规则（尽力而为，失败不影响主流程）
        try:
            from modules.pluginkit.core import run_plugin_inspections_for_db

            plugin_issues = run_plugin_inspections_for_db(cfg["history_db_type"], context)
            if plugin_issues:
                auto_analyze = auto_analyze + list(plugin_issues)
        except Exception:
            pass

        health_score, risk_count, risk_level, health_status = _score(context)
        return {
            "ok": True,
            "db_type": db_type,
            "instance_name": instance_name,
            "auto_analyze": auto_analyze,
            "report_file": None,
            "report_name": None,
            "health_score": health_score,
            "risk_count": risk_count,
            "risk_level": risk_level,
            "health_status": health_status,
            "ai_advice": context.get("ai_advice", ""),
            "error": None,
        }
    except Exception as e:
        # 软降级：任何连接/采集/分析异常都返回 ok=False 同构 report，不抛到上层
        return {
            "ok": False,
            "error": str(e),
            "auto_analyze": [],
            "db_type": db_type,
            "instance_name": instance_name,
        }


def run_target_inspection(
    db_type: str,
    instance: Dict[str, Any],
    inspector_name: str = "Jack",
    template_id=None,
) -> Dict[str, Any]:
    """为目标数据源实时运行巡检引擎，返回结构化结果。

    返回字典包含:
        ok            是否成功
        auto_analyze  智能分析发现列表（每项含 col1/col2/col3 结构）
        report_file / report_name  生成的报告路径
        health_score / risk_count / risk_level / health_status  健康评估
        ai_advice     AI 诊断建议
        error         失败时的错误信息
    """
    if _SCRIPT_DIR not in sys.path:
        sys.path.insert(0, _SCRIPT_DIR)

    import modules.inspection.run as ri

    _RUNNER_MAP = {
        "mysql": ri.run_mysql,
        "mariadb": ri.run_mariadb,
        "pg": ri.run_pg,
        "oracle": ri.run_oracle_full,
        "oracle_jdbc": ri.run_oracle_full,
        "dm": ri.run_dm,
        "sqlserver": ri.run_sqlserver,
        "tidb": ri.run_tidb,
        "ivorysql": ri.run_ivorysql,
        "oceanbase": ri.run_oceanbase,
        "kingbase": ri.run_kingbase,
        "yashandb": ri.run_yashandb,
        "gbase": ri.run_gbase,
    }
    _ENGINE_DB_TYPE = {
        "oracle_jdbc": "oracle",
    }
    _ANALYZER_MAP = {
        "mysql": "smart_analyze_mysql",
        "mariadb": "smart_analyze_mariadb",
        "pg": "smart_analyze_pg",
        "oracle": "smart_analyze_oracle",
        "dm": "smart_analyze_dm",
        "sqlserver": "smart_analyze_sqlserver",
        "tidb": "smart_analyze_tidb",
        "ivorysql": "smart_analyze_ivorysql",
        "kingbase": "smart_analyze_kingbase",
        "yashandb": "smart_analyze_yashandb",
        "oceanbase": "smart_analyze_mysql",
        "gbase": "smart_analyze_gbase",
    }

    runner = _RUNNER_MAP.get(db_type)
    if runner is not None:
        db_info = _build_db_info(db_type, instance)
        engine_db_type = _ENGINE_DB_TYPE.get(db_type, db_type)

        try:
            result = runner(db_info, inspector_name, None)
            # result 形如 (report_file, report_name, context)
            if not isinstance(result, tuple) or len(result) < 3:
                return {"ok": False, "error": "巡检引擎未返回上下文", "auto_analyze": []}
            ofile, fname, context = result[0], result[1], result[2]
            if not context:
                return {"ok": False, "error": "巡检引擎返回空上下文", "auto_analyze": []}

            # 智能分析（与 web_ui 巡检流程一致）
            auto_analyze: List[Dict[str, Any]] = []
            analyzer_name = _ANALYZER_MAP.get(engine_db_type)
            try:
                import modules.inspection.analyzer as analyzer

                fn = getattr(analyzer, analyzer_name, None)
                if fn:
                    auto_analyze = list(fn(context) or [])
            except Exception:
                auto_analyze = []

            # 插件附加风险（尽力而为，失败不影响主流程）
            try:
                from modules.pluginkit.core import run_plugin_inspections_for_db

                plugin_issues = run_plugin_inspections_for_db(engine_db_type, context)
                if plugin_issues:
                    auto_analyze = auto_analyze + list(plugin_issues)
            except Exception:
                pass

            health_score, risk_count, risk_level, health_status = _score(context)
            return {
                "ok": True,
                "db_type": db_type,
                "instance_name": db_info.get("label", ""),
                "auto_analyze": auto_analyze,
                "report_file": ofile,
                "report_name": fname,
                "health_score": health_score,
                "risk_count": risk_count,
                "risk_level": risk_level,
                "health_status": health_status,
                "ai_advice": context.get("ai_advice", ""),
                "error": None,
            }
        except Exception as e:  # 实时巡检失败，交由上层回退历史报告
            return {
                "ok": False,
                "error": str(e),
                "auto_analyze": [],
                "db_type": db_type,
                "instance_name": db_info.get("label", ""),
            }

    # ── 插件路径（复用 plugin_loader 已验证机制，与 Web UI 同源）──
    plugin_report = _run_plugin_inspection(db_type, instance, "", inspector_name)
    if plugin_report is not None:
        return plugin_report

    # ── 暂不支持兜底（保持原文案）──
    return {"ok": False, "error": f"暂不支持的数据库类型：{db_type}", "auto_analyze": []}
