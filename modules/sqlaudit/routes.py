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
from flask import request, jsonify

from . import bp
from . import service


@bp.route("/submit", methods=["POST"])
def submit():
    try:
        data = request.get_json(force=True, silent=True) or {}
        sql_text = (data.get("sql_text") or "").strip()
        if not sql_text:
            return jsonify({"ok": False, "error": "sql_text 不能为空"}), 400
        submitter = data.get("submitter") or request.headers.get("X-User") or "anonymous"
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
