# -*- coding: utf-8 -*-
# SPDX-License-Identifier: Apache-2.0
# Copyright 2025-2026 fiyo (Jack Ge) <sdfiyon@gmail.com>
# Author: fiyo (Jack Ge) - https://github.com/fiyo/DBCheck

"""DocKB REST 路由（蓝图 doc_kb_bp，前缀 /api/doc-kb）。

路由：
  GET    /sources             来源列表（读）
  POST   /sources             新增来源（写，admin/operator）
  GET    /facts?db_type=&category=&q=&version=   事实列表/搜索（读）
  POST   /facts              新增事实（写）
  PUT    /facts/<id>         更新事实（写）
  DELETE /facts/<id>         删除事实（写）
  POST   /import             批量导入（facts 列表）或 AI 抽取（Phase 2 占位）（写）

权限：写操作以 DOCKB_WRITER_ROLES 角色闸 + 403（仅「已登录但角色不足」）；读操作放行，
与 sqlaudit 范式一致——兼容免登录/单用户部署（X-User 或匿名）。
"""
from flask import request, jsonify, session

from . import bp
from . import service
from . import models


# 写操作角色闸（与审批/规则端点一致：admin / operator）
DOCKB_WRITER_ROLES = {"admin", "operator"}


def _current_actor():
    """解析当前操作用户（与 user_management.auth_decorator 语义一致，惰性导入避免顶层依赖）。

    优先 JWT Bearer，其次 Flask session；返回 (username, roles)。未登录回退 X-User 头或 'anonymous'，
    roles 为空（与 sqlaudit._current_actor 一致：免登录/单用户部署放行，仅由角色闸拦截「已登录但角色不足」）。
    """
    token = request.headers.get("Authorization", "").replace("Bearer ", "")
    if token:
        try:
            from modules.user_management.utils.jwt_util import decode_token
            p = decode_token(token)
            return p.get("username") or p.get("user_id"), list(p.get("roles", []))
        except Exception:
            pass
    if session.get("user_id"):
        try:
            from modules.user_management.services.user_service import UserService
            u = UserService().get_user(session["user_id"])
            if u:
                return u.get("username"), [r["role_code"] for r in u.get("roles", [])]
        except Exception:
            pass
    # 未登录：回退到 X-User 头；无头则记为 anonymous，与 sqlaudit._current_actor 对齐。
    # 读/写操作在免登录/单用户部署下放行，仅由角色闸拦截「已登录但角色不足」。
    return request.headers.get("X-User") or "anonymous", []


def _require_reader():
    """读操作放行：与 sqlaudit 读范式一致，免登录/单用户部署下直接放行（不再 401）。

    理由：DocKB 事实/来源列表为只读知识库，应兼容免登录部署；否则整页 401 不可用。
    若需限制，由上层部署（反向代理 / 会话）控制。
    """
    username, roles = _current_actor()
    return (username, roles), None


def _require_writer():
    """写操作角色闸：仅当已登录且角色不足时返回 403；免登录部署放行，与 sqlaudit 一致。"""
    username, roles = _current_actor()
    if roles and not (set(roles) & DOCKB_WRITER_ROLES):
        return None, (jsonify({"ok": False, "error": "权限不足（需要 admin/operator）"}), 403)
    return (username, roles), None


# ─────────────────────────── 来源 ───────────────────────────
@bp.route("/sources", methods=["GET"])
def list_sources():
    actor, err = _require_reader()
    if err:
        return err
    db_type = request.args.get("db_type")
    return jsonify({"ok": True, "data": models.get_sources(db_type)})


@bp.route("/sources", methods=["POST"])
def add_source():
    actor, err = _require_writer()
    if err:
        return err
    username, _ = actor
    data = request.get_json(force=True, silent=True) or {}
    data["created_by"] = username
    res = service.create_source(data)
    if not res["ok"]:
        return jsonify(res), 400
    return jsonify(res), 201


# ─────────────────────────── 事实 ───────────────────────────
@bp.route("/facts", methods=["GET"])
def list_facts():
    actor, err = _require_reader()
    if err:
        return err
    db_type = request.args.get("db_type")
    category = request.args.get("category")
    q = request.args.get("q")
    version = request.args.get("version")
    return jsonify({
        "ok": True,
        "data": models.get_facts(db_type, category, q, version),
    })


@bp.route("/facts", methods=["POST"])
def add_fact():
    actor, err = _require_writer()
    if err:
        return err
    username, _ = actor
    data = request.get_json(force=True, silent=True) or {}
    data["created_by"] = username
    res = service.create_fact(data)
    if not res["ok"]:
        return jsonify(res), 400
    return jsonify(res), 201


@bp.route("/facts/<int:fid>", methods=["PUT"])
def edit_fact(fid: int):
    actor, err = _require_writer()
    if err:
        return err
    data = request.get_json(force=True, silent=True) or {}
    res = service.update_fact(fid, data)
    if not res["ok"]:
        return jsonify(res), 400
    return jsonify(res)


@bp.route("/facts/<int:fid>", methods=["DELETE"])
def remove_fact(fid: int):
    actor, err = _require_writer()
    if err:
        return err
    res = service.delete_fact(fid)
    if not res["ok"]:
        return jsonify({"ok": False, "error": "未找到该事实或删除失败"}), 404
    return jsonify(res)


# ─────────────────────────── 导入 ───────────────────────────
@bp.route("/import", methods=["POST"])
def import_facts():
    actor, err = _require_writer()
    if err:
        return err
    username, _ = actor
    data = request.get_json(force=True, silent=True) or {}

    # 模式 1：批量手动粘贴事实
    facts = data.get("facts")
    if isinstance(facts, list):
        res = service.bulk_import(facts, created_by=username)
        return jsonify(res)

    # 模式 2：AI 抽取官方页（Phase 2 能力，当前版本降级返回提示）
    url = (data.get("url") or "").strip()
    db_type = data.get("db_type", "")
    version = (data.get("version") or "all").strip()
    if not url:
        return jsonify({"ok": False, "error": "需提供 facts 列表或 url"}), 400
    return jsonify(service.extract_from_url(url, db_type, version))
