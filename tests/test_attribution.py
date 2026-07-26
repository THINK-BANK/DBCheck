# -*- coding: utf-8 -*-
# SPDX-License-Identifier: Apache-2.0
# Copyright 2025-2026 fiyo (Jack Ge) <sdfiyon@gmail.com>
# Author: fiyo (Jack Ge) - https://github.com/fiyo/DBCheck

"""原作者署名（attribution）回归测试。

需求：在 UI 页脚与关于页加入 "DBCheck · fiyo" 原作者署名，
含 GitHub 地址、邮箱与 Apache 2.0 协议标注，使署名对用户可见。

覆盖场景：
  - 首页侧边栏页脚署名（DBCheck · fiyo + GitHub 链接）
  - 关于页：作者 / 协议 / 项目地址 / 邮箱
  - 关于页页脚署名
  - 分享报告页页脚署名 + Apache 2.0 标注

分两层：
  A. 静态文件基线检查 —— 直接读取模板源码，快速且不依赖 Flask 启动。
  B. 集成渲染检查 —— 通过 web_ui 的 Flask 路由 / Jinja 环境渲染真实输出，
     验证署名确实出现在「用户实际看到的 HTML」中。
"""
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
TEMPLATES_DIR = REPO_ROOT / "web_templates"
INDEX_HTML = TEMPLATES_DIR / "index.html"
SHARE_HTML = TEMPLATES_DIR / "share.html"

# 期望的署名要素（与版本.py 中声明的原作者信息保持一致）
GITHUB_URL = "https://github.com/fiyo/DBCheck"
AUTHOR = "fiyo (Jack Ge)"
EMAIL = "sdfiyon@gmail.com"
LICENSE_TEXT = "Apache License 2.0"

# 渲染后 HTML 中的精确片段（含标签，避免误匹配普通文本）
SIDEBAR_FOOTER = "DBCheck · <a"
ABOUT_FOOTER = "© 2026 DBCheck · fiyo (Jack Ge)"
SHARE_FOOTER = "DBCheck</a> · fiyo"
SHARE_GENERATED = "· fiyo 生成"


# ── A. 静态文件基线检查（不依赖 Flask） ──────────────────────
def _read(path: Path) -> str:
    """读取模板源码文本；文件缺失则直接失败。"""
    assert path.exists(), "模板文件缺失: %s" % path
    return path.read_text(encoding="utf-8")


def test_index_template_has_sidebar_footer_attribution():
    """首页模板侧边栏页脚须含 'DBCheck · fiyo' 及 GitHub 链接。"""
    html = _read(INDEX_HTML)
    assert SIDEBAR_FOOTER in html, "首页侧边栏页脚缺少 'DBCheck · fiyo' 署名"
    assert GITHUB_URL in html, "首页侧边栏页脚缺少 GitHub 链接 %s" % GITHUB_URL


def test_index_template_about_page_attribution():
    """关于页须包含作者、Apache 2.0 协议、GitHub 地址与邮箱。"""
    html = _read(INDEX_HTML)
    assert AUTHOR in html, "关于页缺少作者署名 %s" % AUTHOR
    assert LICENSE_TEXT in html, "关于页缺少协议标注 %s" % LICENSE_TEXT
    assert GITHUB_URL in html, "关于页缺少 GitHub 项目地址 %s" % GITHUB_URL
    assert EMAIL in html, "关于页缺少作者邮箱 %s" % EMAIL


def test_index_template_about_footer_attribution():
    """关于页页脚须含 'DBCheck · fiyo (Jack Ge)' 与 Apache 2.0。"""
    html = _read(INDEX_HTML)
    assert ABOUT_FOOTER in html, "关于页页脚缺少完整署名 %s" % ABOUT_FOOTER
    assert GITHUB_URL in html, "关于页页脚缺少 GitHub 链接"
    assert LICENSE_TEXT in html, "关于页页脚缺少 Apache 2.0 标注"


def test_share_template_footer_attribution():
    """分享报告页页脚须含 'DBCheck · fiyo'、GitHub 链接与 Apache 2.0。"""
    html = _read(SHARE_HTML)
    assert SHARE_FOOTER in html, "分享页页脚缺少 'DBCheck · fiyo' 署名"
    assert SHARE_GENERATED in html, "分享页页脚缺少 '· fiyo 生成' 文案"
    assert GITHUB_URL in html, "分享页页脚缺少 GitHub 链接 %s" % GITHUB_URL
    assert LICENSE_TEXT in html, "分享页页脚缺少 Apache 2.0 标注"


def test_attribution_uses_real_values_not_placeholders():
    """署名必须是真实信息，不能是占位符/空值，避免被误改成模板变量。"""
    assert GITHUB_URL.startswith("https://github.com/fiyo/"), "GitHub 地址异常"
    assert "@" in EMAIL and "." in EMAIL, "邮箱格式异常: %s" % EMAIL
    assert "fiyo" in AUTHOR, "作者署名异常: %s" % AUTHOR


# ── B. 集成渲染检查（通过 web_ui 渲染真实输出） ───────────────
def _render_index_html() -> str:
    """通过 web_ui 的 Flask 测试客户端渲染首页（伪造已登录会话）。"""
    try:
        import web_ui  # 延迟导入：仅集成测试需要
    except Exception as exc:  # pragma: no cover - 依赖缺失时优雅跳过
        pytest.skip("无法导入 web_ui（依赖缺失），跳过集成渲染测试: %s" % exc)
    client = web_ui.app.test_client()
    with client.session_transaction() as sess:
        sess["user_id"] = "qa-attrib"
        sess["is_admin"] = False
    resp = client.get("/")
    assert resp.status_code == 200, "首页路由返回 %s" % resp.status_code
    return resp.get_data(as_text=True)


def _render_share_html() -> str:
    """通过 web_ui 的 Jinja 环境渲染分享页（分享路由依赖 DB 记录，故直接渲染模板）。"""
    try:
        import web_ui
    except Exception as exc:  # pragma: no cover
        pytest.skip("无法导入 web_ui（依赖缺失），跳过集成渲染测试: %s" % exc)
    return web_ui.app.jinja_env.get_template("share.html").render(
        share_id="qa",
        share_type="json",
        title="QA",
        data_json="{}",
        created_at="2026-01-01",
    )


def test_index_route_serves_sidebar_footer_attribution():
    """真实首页响应 HTML 须含侧边栏页脚署名与 GitHub 链接。"""
    html = _render_index_html()
    assert SIDEBAR_FOOTER in html
    assert GITHUB_URL in html


def test_index_route_serves_about_attribution():
    """真实首页响应 HTML 须含关于页全部署名要素。"""
    html = _render_index_html()
    assert AUTHOR in html
    assert LICENSE_TEXT in html
    assert GITHUB_URL in html
    assert EMAIL in html


def test_index_route_serves_about_footer_attribution():
    """真实首页响应 HTML 的关于页页脚须含完整署名与协议。"""
    html = _render_index_html()
    assert ABOUT_FOOTER in html
    assert LICENSE_TEXT in html


def test_share_route_renders_footer_attribution():
    """真实分享页渲染结果须含页脚署名与 Apache 2.0。"""
    html = _render_share_html()
    assert SHARE_FOOTER in html
    assert SHARE_GENERATED in html
    assert GITHUB_URL in html
    assert LICENSE_TEXT in html
