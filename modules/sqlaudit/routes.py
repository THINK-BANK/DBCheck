# -*- coding: utf-8 -*-
# SPDX-License-Identifier: Apache-2.0
# Copyright 2025-2026 fiyo (Jack Ge) <sdfiyon@gmail.com>
# Author: fiyo (Jack Ge) - https://github.com/fiyo/DBCheck

"""SQL 审核 API 路由（蓝图 sqlaudit_bp）。

路由前缀 /api/sql-audit：
  POST   /submit          提交审核（SQL + 实例 + 环境 + 库类型）
  GET    /tasks           任务列表（支持 submitter / status 过滤）
  GET    /tasks/<id>      任务详情（含 items / rule_hits）
  GET    /rules           规则列表
  GET    /instances       可选目标实例列表（取自 InstanceManager）
"""
from flask import request, jsonify, g, session

from . import bp
from . import service


# 可审批 / 可执行角色（与 RBAC 种子角色 admin/viewer/operator 对齐；viewer 只读不可审批/执行）
APPROVER_ROLES = {"admin", "operator"}


def _current_actor():
    """解析当前操作用户（与 user_management.auth_decorator 语义一致，惰性导入避免顶层依赖）。

    优先 JWT Bearer，其次 Flask session；返回 (username, roles)。未登录返回 (None, [])。
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
    # 未登录：回退到 X-User 头（免登录/单用户部署可用），无角色信息
    return request.headers.get("X-User") or "anonymous", []


@bp.route("/submit", methods=["POST"])
def submit():
    try:
        data = request.get_json(force=True, silent=True) or {}
        sql_text = (data.get("sql_text") or "").strip()
        if not sql_text:
            return jsonify({"ok": False, "error": "sql_text 不能为空"}), 400
        username, _roles = _current_actor()
        submitter = data.get("submitter") or username or request.headers.get("X-User") or "anonymous"
        instance_id = data.get("instance_id")
        db_type = (data.get("db_type") or "mysql").lower()
        env = data.get("env") or "prod"
        plan_enabled = bool(data.get("plan_enabled", False))
        exec_enabled = bool(data.get("exec_enabled", False))
        remark = data.get("remark", "")
        task = service.submit_audit(
            submitter=submitter, instance_id=instance_id, db_type=db_type,
            env=env, sql_text=sql_text, plan_enabled=plan_enabled,
            exec_enabled=exec_enabled, remark=remark,
        )
        return jsonify({"ok": True, "task": task})
    except Exception as e:  # noqa: BLE001
        return jsonify({"ok": False, "error": str(e)}), 500


@bp.route("/tasks", methods=["GET"])
def tasks():
    submitter = request.args.get("submitter")
    status = request.args.get("status")
    try:
        rows = service.list_tasks(submitter=submitter, status=status)
        return jsonify({"ok": True, "tasks": rows})
    except Exception as e:  # noqa: BLE001
        return jsonify({"ok": False, "error": str(e)}), 500


@bp.route("/tasks/<int:task_id>", methods=["GET"])
def task_detail(task_id):
    try:
        t = service.get_task(task_id)
        if not t:
            return jsonify({"ok": False, "error": "任务不存在"}), 404
        return jsonify({"ok": True, "task": t})
    except Exception as e:  # noqa: BLE001
        return jsonify({"ok": False, "error": str(e)}), 500


@bp.route("/tasks/<int:task_id>", methods=["DELETE"])
def delete_task(task_id):
    try:
        n = service.delete_task(task_id)
        if n == 0:
            return jsonify({"ok": False, "error": "任务不存在或已删除"}), 404
        return jsonify({"ok": True, "deleted": n})
    except Exception as e:  # noqa: BLE001
        return jsonify({"ok": False, "error": str(e)}), 500


@bp.route("/tasks/<int:task_id>/execute", methods=["POST"])
def execute_task_route(task_id):
    """受控执行 SQL 审核任务（MVP3 执行器 + 回滚）。

    请求体: {mode: 'dry_run'|'real', max_affected_rows?, timeout?}
    dry_run 默认只读重跑执行计划；real 需任务已开启 exec_enabled、且高风险任务须先审批通过。
    需登录（RBAC），执行人取当前登录用户；免登录部署回退到 X-User 头身份。
    """
    try:
        username, _roles = _current_actor()
        data = request.get_json(force=True, silent=True) or {}
        mode = (data.get("mode") or "dry_run").lower()
        operator = username
        max_affected_rows = data.get("max_affected_rows")
        timeout = data.get("timeout")
        result = service.execute_task(
            task_id, mode=mode, operator=operator,
            max_affected_rows=max_affected_rows, timeout=timeout,
        )
        return jsonify(result)
    except Exception as e:  # noqa: BLE001
        return jsonify({"ok": False, "error": str(e)}), 500


@bp.route("/tasks/<int:task_id>/approve", methods=["POST"])
def approve_task_route(task_id):
    """审批 SQL 审核任务（需 admin / operator 角色）。

    请求体: {action: 'approve'|'reject', comment?}
    """
    try:
        username, roles = _current_actor()
        # 仅当已登录且角色不足时才拦截；免登录部署（无角色）放行，审批人记为当前身份。
        # 核心安全闸（高风险真实执行须 approved_by）在 executor.real_execute 中独立 enforced。
        if roles and not (APPROVER_ROLES & set(roles)):
            return jsonify({"ok": False, "error": "权限不足：审批需 admin 或 operator 角色"}), 403
        data = request.get_json(force=True, silent=True) or {}
        action = data.get("action") or ""
        comment = data.get("comment", "")
        task = service.approve_task(task_id, username, action, comment)
        return jsonify({"ok": True, "task": task})
    except Exception as e:  # noqa: BLE001
        return jsonify({"ok": False, "error": str(e)}), 500


@bp.route("/rules", methods=["GET"])
def rules():
    try:
        return jsonify({"ok": True, "rules": service.list_rules()})
    except Exception as e:  # noqa: BLE001
        return jsonify({"ok": False, "error": str(e)}), 500


@bp.route("/instances", methods=["GET"])
def instances():
    try:
        from modules.pro.instance_manager import get_instance_manager
        insts = get_instance_manager().get_all_instances(mask_password=True)
        out = [{
            "id": i.get("id"),
            "name": i.get("name") or i.get("host"),
            "db_type": i.get("db_type"),
            "host": i.get("host"),
        } for i in insts]
        return jsonify({"ok": True, "instances": out})
    except Exception as e:  # noqa: BLE001
        return jsonify({"ok": False, "error": str(e), "instances": []}), 500


def _list_rules():
    from . import models
    return models.list_rules()
