# SPDX-License-Identifier: Apache-2.0
# Copyright 2025-2026 fiyo (Jack Ge) <sdfiyon@gmail.com>
# Author: fiyo (Jack Ge) - https://github.com/fiyo/DBCheck

"""协同诊断中枢的 Web 接口。"""

from __future__ import annotations

import json

from flask import Blueprint, Response, jsonify, request, session, stream_with_context

from modules.config.version import EDITION
from .hub import get_hub

intelligence_bp = Blueprint("intelligence", __name__)


def _save_history(result: dict, instance_id: str, goal: str) -> dict:
    """把一次诊断结果落库到诊断历史，返回摘要（失败静默）。"""
    try:
        from .diagnosis_store import save_diagnosis

        meta = result.get("target_meta") or {}
        return save_diagnosis(
            instance_id=instance_id,
            instance_name=meta.get("instance_name") or "",
            goal=goal or result.get("goal") or "",
            result=result,
        )
    except Exception:
        return {}


@intelligence_bp.route("/api/intelligence/capabilities")
def capabilities():
    hub = get_hub()
    return jsonify({"edition": EDITION, "capabilities": hub.capabilities()})


@intelligence_bp.route("/api/intelligence/diagnose")
def diagnose():
    hub = get_hub()
    instance_id = request.args.get("instance_id", "").strip()
    goal = request.args.get("goal", "").strip()
    if not instance_id:
        return jsonify({"ok": False, "msg": "instance_id required"}), 400
    result = hub.dispatch(goal=goal, instance_id=instance_id)
    record = _save_history(result, instance_id, goal)
    if record:
        result["history_id"] = record.get("id")
        result["diag_no"] = record.get("diag_no")
    return jsonify({"ok": True, **result})


@intelligence_bp.route("/api/intelligence/diagnose/stream")
def diagnose_stream():
    """SSE 流式诊断：逐个专员执行并推送进度，最后推送完整结果。"""
    hub = get_hub()
    instance_id = request.args.get("instance_id", "").strip()
    goal = request.args.get("goal", "").strip()

    def _gen():
        if not instance_id:
            yield "data: " + json.dumps(
                {"type": "error", "msg": "instance_id required"},
                ensure_ascii=False) + "\n\n"
            return
        try:
            for evt in hub.dispatch_stream(goal=goal, instance_id=instance_id):
                if evt.get("type") == "result":
                    record = _save_history(evt["result"], instance_id, goal)
                    if record:
                        evt["result"]["history_id"] = record.get("id")
                        evt["result"]["diag_no"] = record.get("diag_no")
                yield "data: " + json.dumps(evt, ensure_ascii=False) + "\n\n"
        except Exception as e:
            yield "data: " + json.dumps(
                {"type": "error", "msg": str(e)}, ensure_ascii=False) + "\n\n"

    resp = Response(stream_with_context(_gen()), mimetype="text/event-stream")
    resp.headers["Cache-Control"] = "no-cache"
    resp.headers["X-Accel-Buffering"] = "no"
    return resp


# ── 诊断历史 ──────────────────────────────────────────
@intelligence_bp.route("/api/intelligence/history")
def list_history():
    instance_id = request.args.get("instance_id", "").strip()
    try:
        from .diagnosis_store import list_diagnoses

        rows = list_diagnoses(instance_id=instance_id or None)
        return jsonify({"ok": True, "history": rows})
    except Exception as e:
        return jsonify({"ok": False, "msg": str(e)}), 500


@intelligence_bp.route("/api/intelligence/history/<int:diag_id>", methods=["GET"])
def get_history(diag_id: int):
    try:
        from .diagnosis_store import get_diagnosis

        rec = get_diagnosis(diag_id)
        if not rec:
            return jsonify({"ok": False, "msg": "diagnosis not found"}), 404
        return jsonify({"ok": True, "record": rec})
    except Exception as e:
        return jsonify({"ok": False, "msg": str(e)}), 500


@intelligence_bp.route("/api/intelligence/history/<int:diag_id>", methods=["DELETE"])
def delete_history(diag_id: int):
    try:
        from .diagnosis_store import delete_diagnosis

        ok = delete_diagnosis(diag_id)
        return jsonify({"ok": ok})
    except Exception as e:
        return jsonify({"ok": False, "msg": str(e)}), 500


# ── 工单执行闭环 ──────────────────────────────────────────
@intelligence_bp.route("/api/intelligence/ticket", methods=["POST"])
def create_ticket():
    data = request.get_json(silent=True) or {}
    instance_id = (data.get("instance_id") or "").strip()
    if not instance_id:
        return jsonify({"ok": False, "msg": "instance_id required"}), 400
    instance_name = data.get("instance_name") or ""
    goal = data.get("goal") or ""
    findings = data.get("findings") or []
    plan = data.get("plan") or []
    plan_validation = data.get("plan_validation") or {}
    # 取最高严重级别作为工单严重度
    sev_order = {"critical": 3, "warning": 2, "info": 1}
    severity = "info"
    for f in findings:
        s = f.get("severity") if isinstance(f, dict) else None
        if s in sev_order and sev_order[s] > sev_order.get(severity, 0):
            severity = s
    try:
        from .ticket_store import create_ticket as _create

        ticket = _create(
            instance_id=instance_id,
            instance_name=instance_name,
            goal=goal,
            findings=findings,
            plan=plan,
            plan_validation=plan_validation,
            severity=severity,
        )
        return jsonify({"ok": True, "ticket": ticket})
    except Exception as e:
        return jsonify({"ok": False, "msg": str(e)}), 500


@intelligence_bp.route("/api/intelligence/tickets")
def list_tickets():
    instance_id = request.args.get("instance_id", "").strip()
    status = request.args.get("status", "").strip()
    try:
        from .ticket_store import list_tickets as _list

        tickets = _list(instance_id=instance_id or None, status=status or None)
        return jsonify({"ok": True, "tickets": tickets})
    except Exception as e:
        return jsonify({"ok": False, "msg": str(e)}), 500


@intelligence_bp.route("/api/intelligence/ticket/<int:ticket_id>", methods=["GET"])
def get_ticket(ticket_id: int):
    try:
        from .ticket_store import get_ticket as _get

        ticket = _get(ticket_id)
        if not ticket:
            return jsonify({"ok": False, "msg": "ticket not found"}), 404
        return jsonify({"ok": True, "ticket": ticket})
    except Exception as e:
        return jsonify({"ok": False, "msg": str(e)}), 500


@intelligence_bp.route("/api/intelligence/ticket/<int:ticket_id>/update", methods=["POST"])
def update_ticket(ticket_id: int):
    data = request.get_json(silent=True) or {}
    status = (data.get("status") or "").strip() or None
    assignee = (data.get("assignee") or "").strip() or None
    note = data.get("note")
    if note is not None:
        note = str(note).strip()
    try:
        from .ticket_store import update_ticket as _update

        ticket = _update(ticket_id, status=status, assignee=assignee, note=note)
        if not ticket:
            return jsonify({"ok": False, "msg": "ticket not found"}), 404
        return jsonify({"ok": True, "ticket": ticket})
    except ValueError as e:
        return jsonify({"ok": False, "msg": str(e)}), 400
    except Exception as e:
        return jsonify({"ok": False, "msg": str(e)}), 500


# ── 系统字典表（schema_knowledge）维护 ───────────────────────────────────
def _schema_dict_writer_ok() -> bool:
    """仅 admin / operator 可写系统字典表。"""
    roles = session.get("user_roles", []) or []
    if session.get("is_admin", False):
        return True
    return any(r in ("admin", "operator") for r in roles)


def _require_writer():
    if not _schema_dict_writer_ok():
        return jsonify({"ok": False, "msg": "权限不足：仅 admin / operator 可维护系统字典表"}), 403
    return None


@intelligence_bp.route("/api/intelligence/schema-dict", methods=["GET"])
def schema_dict_get():
    """读取系统字典表。可选项：db_type / view 过滤。"""
    from .schema_knowledge import get_knowledge

    db_type = request.args.get("db_type", "").strip()
    view = request.args.get("view", "").strip()
    kb = get_knowledge()
    databases = kb.get("databases", {})

    if db_type:
        databases = {db_type: databases.get(db_type, {})}
    if view:
        filtered = {}
        for dt, dt_info in databases.items():
            views = dt_info.get("views", {})
            if view in views:
                filtered[dt] = {"description": dt_info.get("description", ""), "views": {view: views[view]}}
        databases = filtered

    return jsonify({"ok": True, "databases": databases, "version": kb.get("version", "")})


@intelligence_bp.route("/api/intelligence/schema-dict", methods=["POST"])
def schema_dict_post():
    """新增：库 / 视图 / 字段。body 至少含 db_type。"""
    deny = _require_writer()
    if deny:
        return deny
    data = request.get_json(silent=True) or {}
    db_type = (data.get("db_type") or "").strip()
    view = (data.get("view") or "").strip()
    field = (data.get("field") or "").strip()
    if not db_type:
        return jsonify({"ok": False, "msg": "db_type 必填"}), 400

    from .schema_knowledge import get_knowledge, save_knowledge

    kb = get_knowledge()
    databases = kb.setdefault("databases", {})
    dt_info = databases.setdefault(db_type, {"description": data.get("description", "") or db_type, "views": {}})
    views = dt_info.setdefault("views", {})

    if not view:
        # 仅新增库类型
        return jsonify({"ok": True, "msg": "已确保库类型存在", "databases": databases})

    view_info = views.setdefault(view, {
        "description": data.get("view_description", "") or view,
        "keywords": data.get("keywords", []) or [],
        "fields": {},
    })
    if not field:
        return jsonify({"ok": True, "msg": "已确保视图存在", "databases": databases})

    if field in view_info.get("fields", {}):
        return jsonify({"ok": False, "msg": f"字段 {field} 已存在"}), 409
    view_info.setdefault("fields", {})[field] = {
        "type": (data.get("field_type") or "VARCHAR").strip(),
        "desc": (data.get("field_desc") or "").strip(),
    }
    if not save_knowledge(kb):
        return jsonify({"ok": False, "msg": "保存失败"}), 500
    return jsonify({"ok": True, "msg": "已新增字段", "databases": databases})


@intelligence_bp.route("/api/intelligence/schema-dict", methods=["PUT"])
def schema_dict_put():
    """更新：视图描述/keywords，或字段 type/desc。"""
    deny = _require_writer()
    if deny:
        return deny
    data = request.get_json(silent=True) or {}
    db_type = (data.get("db_type") or "").strip()
    view = (data.get("view") or "").strip()
    field = (data.get("field") or "").strip()
    if not db_type or not view:
        return jsonify({"ok": False, "msg": "db_type 与 view 必填"}), 400

    from .schema_knowledge import get_knowledge, save_knowledge

    kb = get_knowledge()
    views = kb.get("databases", {}).get(db_type, {}).get("views", {})
    if view not in views:
        return jsonify({"ok": False, "msg": "视图不存在"}), 404
    view_info = views[view]

    if field:
        if field not in view_info.get("fields", {}):
            return jsonify({"ok": False, "msg": "字段不存在"}), 404
        if data.get("field_type") is not None:
            view_info["fields"][field]["type"] = str(data["field_type"]).strip()
        if data.get("field_desc") is not None:
            view_info["fields"][field]["desc"] = str(data["field_desc"]).strip()
    else:
        if data.get("view_description") is not None:
            view_info["description"] = str(data["view_description"]).strip()
        if data.get("keywords") is not None:
            view_info["keywords"] = data["keywords"]

    if not save_knowledge(kb):
        return jsonify({"ok": False, "msg": "保存失败"}), 500
    return jsonify({"ok": True, "msg": "已更新", "databases": kb.get("databases", {})})


@intelligence_bp.route("/api/intelligence/schema-dict", methods=["DELETE"])
def schema_dict_delete():
    """删除：按 field > view > db_type 优先级逐层删除。"""
    deny = _require_writer()
    if deny:
        return deny
    db_type = request.args.get("db_type", "").strip()
    view = request.args.get("view", "").strip()
    field = request.args.get("field", "").strip()
    if not db_type:
        return jsonify({"ok": False, "msg": "db_type 必填"}), 400

    from .schema_knowledge import get_knowledge, save_knowledge

    kb = get_knowledge()
    databases = kb.get("databases", {})
    if db_type not in databases:
        return jsonify({"ok": False, "msg": "库类型不存在"}), 404
    dt_info = databases[db_type]
    views = dt_info.get("views", {})

    if field and view:
        if view not in views or field not in views[view].get("fields", {}):
            return jsonify({"ok": False, "msg": "字段不存在"}), 404
        del views[view]["fields"][field]
        msg = f"已删除字段 {field}"
    elif view:
        if view not in views:
            return jsonify({"ok": False, "msg": "视图不存在"}), 404
        del views[view]
        msg = f"已删除视图 {view}"
    else:
        del databases[db_type]
        msg = f"已删除库类型 {db_type}"

    if not save_knowledge(kb):
        return jsonify({"ok": False, "msg": "保存失败"}), 500
    return jsonify({"ok": True, "msg": msg, "databases": kb.get("databases", {})})
