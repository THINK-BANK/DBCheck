# -*- coding: utf-8 -*-
# SPDX-License-Identifier: Apache-2.0
# Copyright 2025-2026 fiyo (Jack Ge) <sdfiyon@gmail.com>
# Author: fiyo (Jack Ge) - https://github.com/fiyo/DBCheck

"""
HGDB 规则引擎回归测试 —— 验证「规则引擎缺少 HGDB 数据」Bug 修复。

覆盖：
  1) 规则加载：get_enabled_rules('hgdb') == 12 条，id 均以 hgdb_ 前缀、db_types 含 hgdb
  2) 规则触发：构造"问题" mock context，验证关键高危规则被触发
  3) 不误报：构造"健康" mock context，验证关键高危规则不触发
  4) 不破坏其它库：uxdb / pg 规则仍可用
  5) 插件 collect_data 集成：模块可导入、含 analyze_with_plugins('hgdb') 调用
  6) 编译：两个插件 main_plugin.py 通过 py_compile

运行：在 D:/DBCheck 下执行  python tests/test_hgdb_rule_engine.py
（脚本会自动把仓库根目录加入 sys.path，因此也可从任意目录运行）
"""

import os
import sys
import importlib.util

# ── 路径准备：把仓库根目录加入 sys.path，保证 import pro / plugins 可用 ──
REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

# ── 简单的 PASS/FAIL 计数器与详情收集 ──
_PASS = 0
_FAIL = 0
_LINES = []


def check(name, cond, detail=""):
    """记录一条断言结果。"""
    global _PASS, _FAIL
    if cond:
        _PASS += 1
        _LINES.append("  [PASS] %s%s" % (name, (" -- " + detail) if detail else ""))
    else:
        _FAIL += 1
        _LINES.append("  [FAIL] %s%s" % (name, (" -- " + detail) if detail else ""))


def section(title):
    _LINES.append("")
    _LINES.append("=== %s ===" % title)


def main():
    section("0. 环境")
    check("仓库根目录存在 pro/rules/builtin", os.path.isdir(os.path.join(REPO_ROOT, "pro", "rules", "builtin")))

    # 延迟导入，确保 sys.path 已就绪
    from pro.rule_engine import get_rule_engine, analyze_with_plugins

    e = get_rule_engine()

    # ─────────────────────────────────────────────────────────────
    section("1. 规则加载 (get_enabled_rules('hgdb'))")
    rs = e.get_enabled_rules("hgdb")
    check("hgdb 启用规则数 == 12", len(rs) == 12, "actual=%d" % len(rs))
    check("每条规则 id 以 'hgdb_' 开头",
          all((r.get("id") or "").startswith("hgdb_") for r in rs),
          "ids=%s" % [r.get("id") for r in rs])
    check("每条规则 db_types 含 'hgdb'",
          all("hgdb" in (r.get("db_types") or []) for r in rs))

    # ─────────────────────────────────────────────────────────────
    section("2. 规则触发 (问题 context -> 应触发)")
    problem_ctx = {
        "hgdb_settings": [
            {"name": "max_connections", "setting": "50"},
            {"name": "max_wal_senders", "setting": "1"},
        ],
        "hgdb_connections": [],
        "hgdb_lock_waits": [],
        "hgdb_tables": [],
        "hgdb_roles": [
            {"rolname": "a", "rolsuper": True},
            {"rolname": "b", "rolsuper": True},
        ],
        "hgdb_wal_level": [{"wal_level": "minimal"}],
        "hgdb_archive_mode": [{"archive_mode": "off"}],
        "hgdb_shared_buffers": [{"shared_buffers": "0"}],
        "hgdb_auth_settings": [{"password_encryption": "plain"}],
        "system_info": {"memory": {"usage_percent": 95}, "disk_list": []},
    }
    issues = e.analyze("hgdb", problem_ctx)
    ids = {i.get("_rule_id") for i in issues}
    check("问题 context 返回 issue 列表非空", len(issues) > 0, "issues=%d" % len(issues))
    for rid in [
        "hgdb_max_conn_low",
        "hgdb_mem_usage_high",
        "hgdb_wal_level_minimal",
        "hgdb_archive_off",
        "hgdb_shared_buffers_zero",
        "hgdb_password_plain",
        "hgdb_superuser_many",
    ]:
        check("触发 '%s'" % rid, rid in ids, "triggered=%s" % sorted(ids))

    # ─────────────────────────────────────────────────────────────
    section("3. 不误报 (健康 context -> 不应触发高危规则)")
    healthy_ctx = {
        "hgdb_settings": [
            {"name": "max_connections", "setting": "200"},
            {"name": "max_wal_senders", "setting": "10"},
        ],
        "hgdb_connections": [],
        "hgdb_lock_waits": [],
        "hgdb_tables": [],
        "hgdb_roles": [{"rolname": "a", "rolsuper": True}],
        "hgdb_wal_level": [{"wal_level": "replica"}],
        "hgdb_archive_mode": [{"archive_mode": "on"}],
        "hgdb_shared_buffers": [{"shared_buffers": "4GB"}],
        "hgdb_auth_settings": [{"password_encryption": "scram-sha-256"}],
        "system_info": {"memory": {"usage_percent": 30}, "disk_list": []},
    }
    issues_h = e.analyze("hgdb", healthy_ctx)
    ids_h = {i.get("_rule_id") for i in issues_h}
    for rid in [
        "hgdb_max_conn_low",
        "hgdb_mem_usage_high",
        "hgdb_wal_level_minimal",
        "hgdb_archive_off",
        "hgdb_shared_buffers_zero",
        "hgdb_password_plain",
        "hgdb_superuser_many",
    ]:
        check("健康 context 不触发 '%s'" % rid, rid not in ids_h,
              "误报!" if rid in ids_h else "")
    check("健康 context 整体零误报 (issue 数为 0)", len(issues_h) == 0, "issues=%d" % len(issues_h))

    # ─────────────────────────────────────────────────────────────
    section("4. 不破坏其它数据库规则")
    uxdb_rules = e.get_enabled_rules("uxdb")
    pg_rules = e.get_enabled_rules("pg")
    check("uxdb 规则仍可用 (>0)", len(uxdb_rules) > 0, "uxdb=%d" % len(uxdb_rules))
    check("pg 规则仍可用 (>0)", len(pg_rules) > 0, "pg=%d" % len(pg_rules))

    # ─────────────────────────────────────────────────────────────
    section("5. 插件 collect_data 集成 (独立方式导入)")
    avail_mod = os.path.join(REPO_ROOT, "plugins", "available", "hgdb_jdbc", "main_plugin.py")
    enab_mod = os.path.join(REPO_ROOT, "plugins", "enabled", "hgdb_jdbc", "main_plugin.py")
    check("available/main_plugin.py 存在", os.path.isfile(avail_mod))
    check("enabled/main_plugin.py 存在", os.path.isfile(enab_mod))

    # 以独立模块名导入（模仿插件加载器），避免污染全局 sys.modules
    import_ok = False
    mod = None
    try:
        spec = importlib.util.spec_from_file_location("hgdb_jdbc_main_iso", avail_mod)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        import_ok = True
    except Exception as ex:  # noqa: BLE001
        _LINES.append("    导入异常: %s: %s" % (type(ex).__name__, ex))
    check("plugins.available.hgdb_jdbc.main_plugin 可导入", import_ok)
    if mod is not None:
        check("HgdbJdbcInspector.collect_data 方法存在",
              hasattr(mod, "HgdbJdbcInspector") and hasattr(mod.HgdbJdbcInspector, "collect_data"))
        try:
            src = open(avail_mod, encoding="utf-8").read()
            check("collect_data 内含 analyze_with_plugins('hgdb' 调用",
                  "analyze_with_plugins('hgdb'" in src)
        except Exception as ex:  # noqa: BLE001
            check("collect_data 内含 analyze_with_plugins('hgdb' 调用", False, str(ex))

    # ─────────────────────────────────────────────────────────────
    section("6. 编译 (py_compile)")
    import py_compile
    try:
        py_compile.compile(avail_mod, doraise=True)
        py_compile.compile(enab_mod, doraise=True)
        check("两处 main_plugin.py 通过 py_compile", True)
    except py_compile.PyCompileError as ex:
        check("两处 main_plugin.py 通过 py_compile", False, str(ex))

    # ─────────────────────────────────────────────────────────────
    section("7. 规则文件 YAML 可解析 & 12 条")
    try:
        import yaml
        hgdb_yaml = os.path.join(REPO_ROOT, "pro", "rules", "builtin", "hgdb.yaml")
        with open(hgdb_yaml, encoding="utf-8") as f:
            data = yaml.safe_load(f)
        rules = data.get("rules", [])
        check("hgdb.yaml 解析成功且含 12 条规则", len(rules) == 12, "rules=%d" % len(rules))
        check("hgdb.yaml 中每条 id 唯一且以 hgdb_ 开头",
              len({r.get("id") for r in rules}) == 12 and
              all((r.get("id") or "").startswith("hgdb_") for r in rules))
    except Exception as ex:  # noqa: BLE001
        check("hgdb.yaml 解析", False, str(ex))

    # ── 汇总输出 ──
    _LINES.append("")
    _LINES.append("=" * 52)
    _LINES.append("总计: %d 条断言 | PASS: %d | FAIL: %d" % (_PASS + _FAIL, _PASS, _FAIL))
    _LINES.append("加载 hgdb 规则数: %d | 问题context触发: %d 条 | 健康context触发: %d 条"
                  % (len(rs), len(issues), len(issues_h)))
    _LINES.append("=" * 52)
    result = "\n".join(_LINES)
    print(result)

    return _FAIL


if __name__ == "__main__":
    sys.exit(1 if main() > 0 else 0)
