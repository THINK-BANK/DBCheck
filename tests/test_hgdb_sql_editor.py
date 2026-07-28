# coding: utf-8
# SPDX-License-Identifier: Apache-2.0
# -*- test-case-name: tests.test_hgdb_sql_editor -*-
"""
HGDB SQL 编辑器 Bug 修复回归测试（离线静态 + mock 方式）

被测修复：SQL 编辑器 3 个后端端点（databases / objects / execute_sql）的
`db_type` 白名单原本只含 ('postgresql', 'ivorysql', 'kingbase')，漏了 'hgdb'，
导致点击 HGDB 节点走 else 分支报 400。

本机未安装 psycopg2，因此本测试：
  1) py_compile 校验 web_ui.py 可编译；
  2) 静态字符串断言：3 个端点均已开放 hgdb，且未删减原有库；
  3) 运行时路由模拟：注入假 psycopg2 + 假 pro.get_instance_manager，
     直接调用端点函数，验证 db_type='hgdb' 走 psycopg2 分支（connect 被调用、
     默认库名 highgo），不再返回 400；并验证 postgresql 行为未被破坏。

运行：在 D:/DBCheck 目录下执行  python tests/test_hgdb_sql_editor.py
"""

import os
import sys
import json
import types
import subprocess

# ────────────────────────────────────────────────────────────────────────
# 0. 路径与 sys.path 自愈
# ────────────────────────────────────────────────────────────────────────
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

WEB_UI_PATH = os.path.join(ROOT, "web_ui.py")


# ────────────────────────────────────────────────────────────────────────
# 1. 假 psycopg2（在 import web_ui 前注入，规避未安装 psycopg2 的环境限制）
# ────────────────────────────────────────────────────────────────────────
class _Cursor:
    def __init__(self, fake):
        self._fake = fake
        self.executed = []

    def execute(self, sql, params=None):
        self.executed.append((sql, params))

    def fetchall(self):
        return self._fake.cursor_fetchall

    def fetchmany(self, n):
        return self._fake.cursor_fetchmany

    @property
    def description(self):
        return self._fake.cursor_description

    def close(self):
        pass


class _Conn:
    def __init__(self, fake):
        self._fake = fake
        self.cursor_obj = None

    def cursor(self):
        self.cursor_obj = self._fake.make_cursor()
        return self.cursor_obj

    def close(self):
        pass


class _Psycopg2Fake:
    def __init__(self):
        self.connect_calls = []          # 每次 connect 的关键字参数
        self.cursor_fetchall = []         # 供 fetchall() 返回
        self.cursor_description = []      # 供 description 返回
        self.cursor_fetchmany = []        # 供 fetchmany() 返回

    def make_cursor(self):
        return _Cursor(self)

    def connect(self, *args, **kwargs):
        self.connect_calls.append(kwargs)
        return _Conn(self)


_PG = _Psycopg2Fake()
_fake_psy = types.ModuleType("psycopg2")
_fake_psy.connect = _PG.connect
sys.modules["psycopg2"] = _fake_psy


# ────────────────────────────────────────────────────────────────────────
# 2. 假 pro（注入 get_instance_manager，隔离真实 pro 模块依赖）
# ────────────────────────────────────────────────────────────────────────
_CURRENT_INSTANCE = {"value": None}


class _FakeInstanceManager:
    def get_instance_decrypted(self, ds_id):
        return _CURRENT_INSTANCE["value"]


_fake_pro = types.ModuleType("pro")
_fake_pro.get_instance_manager = lambda: _FakeInstanceManager()
sys.modules["pro"] = _fake_pro


# ────────────────────────────────────────────────────────────────────────
# 3. 导入被测模块
# ────────────────────────────────────────────────────────────────────────
import web_ui  # noqa: E402  (必须在 psycopg2 / pro mock 注入之后)


# ────────────────────────────────────────────────────────────────────────
# 4. 测试夹具数据
# ────────────────────────────────────────────────────────────────────────
HGDB_INSTANCE = {
    "db_type": "hgdb",
    "host": "localhost",
    "port": 5866,
    "user": "highgo",
    "password": "Aa123456@",
}

PG_INSTANCE = {
    "db_type": "postgresql",
    "host": "localhost",
    "port": 5432,
    "user": "postgres",
    "password": "postgres",
}


# ────────────────────────────────────────────────────────────────────────
# 5. 轻量测试框架：收集 PASS / FAIL 并打印关键断言细节
# ────────────────────────────────────────────────────────────────────────
RESULTS = []


def check(name, cond, detail=""):
    RESULTS.append((name, bool(cond), detail))
    status = "PASS" if cond else "FAIL"
    line = "[%s] %s" % (status, name)
    if detail:
        line += " :: %s" % detail
    print(line)
    return bool(cond)


# ────────────────────────────────────────────────────────────────────────
# 6. 端点调用辅助（每个端点独立重置 mock，并配置对应 cursor 行为）
# ────────────────────────────────────────────────────────────────────────
def _reset_pg(fetchall=None, description=None, fetchmany=None):
    _PG.connect_calls = []
    _PG.cursor_fetchall = fetchall or []
    _PG.cursor_description = description or []
    _PG.cursor_fetchmany = fetchmany or []


def call_databases(ds_id):
    _reset_pg(fetchall=[("highgo",), ("postgres",), ("template1",)])
    # 直接调用视图函数需 Flask 应用上下文，否则 jsonify 抛
    # "Working outside of application context"
    with web_ui.app.test_request_context():
        return web_ui.api_ds_databases(ds_id)


def call_objects(ds_id, database):
    _reset_pg(fetchall=[("public", "t_users"), ("public", "t_orders"), ("app", "t_log")])
    with web_ui.app.test_request_context(query_string={"database": database}):
        return web_ui.api_ds_objects(ds_id)


def call_execute_sql(payload):
    _reset_pg(
        description=[("?column?",), ("now",)],
        fetchmany=[("1", "2024-01-01")],
    )
    with web_ui.app.test_request_context(json=payload):
        return web_ui.api_execute_sql()


def _last_connect_kwargs():
    assert _PG.connect_calls, "psycopg2.connect 未被调用"
    return _PG.connect_calls[-1]


def _resp_json(resp):
    return json.loads(resp.get_data(as_text=True))


# ────────────────────────────────────────────────────────────────────────
# 7. 测试主体
# ────────────────────────────────────────────────────────────────────────
def test_compile():
    """(1) py_compile 必须通过（web_ui.py 带 BOM，以 py_compile 为准）"""
    proc = subprocess.run(
        [sys.executable, "-m", "py_compile", WEB_UI_PATH],
        capture_output=True, text=True,
    )
    check(
        "compile: web_ui.py 可编译",
        proc.returncode == 0,
        "returncode=%s stderr=%s" % (proc.returncode, (proc.stderr or "").strip()[:200]),
    )


def test_static_strings():
    """(2) 静态字符串断言：3 个端点开放 hgdb，且为追加而非删减"""
    with open(WEB_UI_PATH, "r", encoding="utf-8-sig") as f:
        src = f.read()
    lines = src.splitlines()

    tuple_str = "elif db_type in ('postgresql', 'ivorysql', 'kingbase', 'hgdb'):"
    cnt_tuple = src.count(tuple_str)
    check(
        "static: hgdb 端点白名单 >= 3 处",
        cnt_tuple >= 3,
        "出现 %d 次 (databases/objects/execute_sql)" % cnt_tuple,
    )

    highgo_str = "'highgo' if db_type == 'hgdb'"
    cnt_highgo = src.count(highgo_str)
    check(
        "static: 默认库名 highgo 逻辑 >= 2 处",
        cnt_highgo >= 2,
        "出现 %d 次 (databases/execute_sql)" % cnt_highgo,
    )

    # 未删减原有库：元组仍含 postgresql/ivorysql/kingbase
    for db in ("postgresql", "ivorysql", "kingbase"):
        check(
            "static: 原有库 '%s' 未被删减" % db,
            db in tuple_str,
            tuple_str,
        )

    # 关键断言：三个 SQL 编辑器端点（databases/objects/execute_sql）的
    # 400 错误分支（「不支持」错误）之前最近的 elif 元组已包含 hgdb，
    # 证明 hgdb 已在该 elif 中处理、不会再落入 400 错误分支。
    # 仅对「含 不支持 且 含 400」的错误返回行向上回溯，并限定其前置 elif
    # 必须含 hgdb，避免误伤 redis / 其它数据源端点的同类错误分支。
    error_idxs = [i for i, ln in enumerate(lines)
                  if "不支持" in ln and "400" in ln]
    matched = 0
    for idx in error_idxs:
        else_idx = None
        for j in range(idx - 1, -1, -1):
            if lines[j].strip().startswith("else:"):
                else_idx = j
                break
        if else_idx is None:
            continue
        elif_idx = None
        for j in range(else_idx - 1, -1, -1):
            if "elif db_type in (" in lines[j]:
                elif_idx = j
                break
        if elif_idx is None or "hgdb" not in lines[elif_idx]:
            continue
        matched += 1
        check(
            "static: 端点(L%d) 400 错误前 elif 已含 hgdb" % (idx + 1),
            "不支持" in lines[idx] and "hgdb" in lines[elif_idx],
            "else@L%d <- elif: %s" % (else_idx + 1, lines[elif_idx].strip()),
        )
    check("static: 三个 SQL 编辑器端点 400 结构均已校验", matched >= 3,
          "匹配 %d 个端点" % matched)


def test_databases_hgdb():
    """(3a) databases 端点：hgdb 走 psycopg2 分支，默认库 highgo，返回 200"""
    _CURRENT_INSTANCE["value"] = HGDB_INSTANCE
    resp = call_databases("ds_hgdb")
    data = _resp_json(resp)
    kw = _last_connect_kwargs()

    check("databases[hgdb]: psycopg2.connect 被调用", len(_PG.connect_calls) >= 1,
          "calls=%d" % len(_PG.connect_calls))
    check("databases[hgdb]: dbname == 'highgo'", kw.get("dbname") == "highgo",
          "dbname=%r" % kw.get("dbname"))
    check("databases[hgdb]: host/port/user/password 正确",
          kw.get("host") == "localhost" and kw.get("port") == 5866 and
          kw.get("user") == "highgo" and kw.get("password") == "Aa123456@",
          "host=%r port=%r user=%r" % (kw.get("host"), kw.get("port"), kw.get("user")))
    check("databases[hgdb]: 返回 200 且含 databases 键",
          resp.status_code == 200 and "databases" in data,
          "status=%s data_keys=%s" % (resp.status_code, list(data.keys())))
    check("databases[hgdb]: db_type == 'hgdb'",
          data.get("db_type") == "hgdb", "db_type=%r" % data.get("db_type"))
    err_txt = str(data.get("error", ""))
    check("databases[hgdb]: 未返回「不支持」错误",
          "不支持" not in err_txt, "error=%r" % err_txt)


def test_objects_hgdb():
    """(3b) objects 端点：hgdb 走 psycopg2 分支，dbname == 传入 database"""
    _CURRENT_INSTANCE["value"] = HGDB_INSTANCE
    resp = call_objects("ds_hgdb", "highgo")
    data = _resp_json(resp)
    kw = _last_connect_kwargs()

    check("objects[hgdb]: psycopg2.connect 被调用", len(_PG.connect_calls) >= 1,
          "calls=%d" % len(_PG.connect_calls))
    check("objects[hgdb]: dbname == 传入的 'highgo'",
          kw.get("dbname") == "highgo", "dbname=%r" % kw.get("dbname"))
    check("objects[hgdb]: 返回 200 且含 tables/views",
          resp.status_code == 200 and "tables" in data and "views" in data,
          "status=%s data_keys=%s" % (resp.status_code, list(data.keys())))
    check("objects[hgdb]: db_type == 'hgdb'",
          data.get("db_type") == "hgdb", "db_type=%r" % data.get("db_type"))
    err_txt = str(data.get("error", ""))
    check("objects[hgdb]: 未返回「不支持」错误",
          "不支持" not in err_txt, "error=%r" % err_txt)


def test_execute_sql_hgdb():
    """(3c) execute_sql 端点：hgdb 走 psycopg2 分支，默认库 highgo，返回 columns/rows"""
    _CURRENT_INSTANCE["value"] = HGDB_INSTANCE
    resp = call_execute_sql({
        "instance_id": "ds_hgdb",
        "sql": "SELECT 1",
        "database": "highgo",
    })
    data = _resp_json(resp)
    kw = _last_connect_kwargs()

    check("execute_sql[hgdb]: psycopg2.connect 被调用", len(_PG.connect_calls) >= 1,
          "calls=%d" % len(_PG.connect_calls))
    check("execute_sql[hgdb]: dbname == 'highgo'",
          kw.get("dbname") == "highgo", "dbname=%r" % kw.get("dbname"))
    check("execute_sql[hgdb]: 返回 200 且含 columns/rows",
          resp.status_code == 200 and "columns" in data and "rows" in data,
          "status=%s data_keys=%s" % (resp.status_code, list(data.keys())))
    check("execute_sql[hgdb]: row_count == 1",
          data.get("row_count") == 1, "row_count=%r" % data.get("row_count"))
    err_txt = str(data.get("error", ""))
    check("execute_sql[hgdb]: 未返回「不支持」错误",
          "不支持" not in err_txt, "error=%r" % err_txt)


def test_databases_postgresql_regression():
    """(4) 不破坏其它库：postgresql 仍走同一分支，默认库 postgres"""
    _CURRENT_INSTANCE["value"] = PG_INSTANCE
    resp = call_databases("ds_pg")
    data = _resp_json(resp)
    kw = _last_connect_kwargs()

    check("regression[pg]: psycopg2.connect 被调用", len(_PG.connect_calls) >= 1,
          "calls=%d" % len(_PG.connect_calls))
    check("regression[pg]: dbname == 'postgres'（未被 hgdb 改动影响）",
          kw.get("dbname") == "postgres", "dbname=%r" % kw.get("dbname"))
    check("regression[pg]: 返回 200 且 db_type == 'postgresql'",
          resp.status_code == 200 and data.get("db_type") == "postgresql",
          "status=%s db_type=%r" % (resp.status_code, data.get("db_type")))


# ────────────────────────────────────────────────────────────────────────
# 8. 主流程
# ────────────────────────────────────────────────────────────────────────
def main():
    print("=" * 72)
    print("HGDB SQL 编辑器 Bug 修复回归测试")
    print("web_ui.py: %s" % WEB_UI_PATH)
    print("=" * 72)

    test_compile()
    print("-" * 72)
    test_static_strings()
    print("-" * 72)
    test_databases_hgdb()
    print("-" * 72)
    test_objects_hgdb()
    print("-" * 72)
    test_execute_sql_hgdb()
    print("-" * 72)
    test_databases_postgresql_regression()
    print("=" * 72)

    total = len(RESULTS)
    passed = sum(1 for _, ok, _ in RESULTS if ok)
    failed = total - passed
    print("测试汇总: 总计 %d | 通过 %d | 失败 %d | 通过率 %.1f%%"
          % (total, passed, failed, (passed / total * 100) if total else 0))
    print("=" * 72)

    # 打印失败项明细，便于源码/测试路由判定
    if failed:
        print("失败项明细:")
        for name, ok, detail in RESULTS:
            if not ok:
                print("  - %s :: %s" % (name, detail))
        print("=" * 72)
        sys.exit(1)
    else:
        print("全部通过 ✅")
        sys.exit(0)


if __name__ == "__main__":
    main()
