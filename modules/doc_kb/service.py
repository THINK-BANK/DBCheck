# -*- coding: utf-8 -*-
# SPDX-License-Identifier: Apache-2.0
# Copyright 2025-2026 fiyo (Jack Ge) <sdfiyon@gmail.com>
# Author: fiyo (Jack Ge) - https://github.com/fiyo/DBCheck

"""DocKB 业务逻辑层：枚举白名单、校验、编排、策展辅助。

Phase 0/1：枚举校验 + CRUD 编排。extract_from_url（LLM 抽取官方页为结构化事实草稿）
为 Phase 2 能力，此处给出明确降级的占位实现，避免前端 import 面板调用时静默异常。
"""
from . import models

# 枚举白名单
CATEGORY = {"param", "baseline", "rule", "bug"}
SEVERITY = {"low", "mid", "high", "block"}
LANG = {"zh", "en", "both"}

_VALID_DB_TYPES = {
    "mysql", "oracle", "pg", "postgresql", "sqlserver", "dm", "tidb", "all"
}


def _clean_db_type(db_type: str) -> str:
    dt = (db_type or "").strip().lower()
    if dt == "postgresql":
        dt = "pg"
    return dt


def validate_source(payload: dict):
    """校验来源载荷，返回 (ok, error, cleaned)。"""
    db_type = _clean_db_type(payload.get("db_type", ""))
    version = (payload.get("version") or "").strip()
    official_url = (payload.get("official_url") or "").strip()
    if not db_type:
        return False, "db_type 不能为空", None
    if db_type not in _VALID_DB_TYPES:
        return False, f"不支持的 db_type：{db_type}", None
    if not version:
        return False, "version 不能为空", None
    if not official_url:
        return False, "official_url 不能为空", None
    cleaned = {
        "db_type": db_type,
        "version": version,
        "official_url": official_url,
        "title": (payload.get("title") or "").strip() or None,
        "license_note": (payload.get("license_note") or "").strip() or None,
        "note": (payload.get("note") or "").strip() or None,
        "fetched_at": (payload.get("fetched_at") or "").strip() or None,
    }
    return True, "", cleaned


def validate_fact(payload: dict):
    """校验事实载荷，返回 (ok, error, cleaned)。"""
    db_type = _clean_db_type(payload.get("db_type", ""))
    version = (payload.get("version") or "all").strip() or "all"
    category = (payload.get("category") or "").strip().lower()
    key = (payload.get("key") or "").strip()
    if not db_type:
        return False, "db_type 不能为空", None
    if db_type not in _VALID_DB_TYPES:
        return False, f"不支持的 db_type：{db_type}", None
    if category not in CATEGORY:
        return False, f"category 必须是 {sorted(CATEGORY)} 之一", None
    if not key:
        return False, "key 不能为空", None

    severity = (payload.get("severity") or "").strip().lower() or None
    if severity and severity not in SEVERITY:
        return False, f"severity 必须是 {sorted(SEVERITY)} 之一", None
    lang = (payload.get("lang") or "both").strip().lower()
    if lang not in LANG:
        return False, f"lang 必须是 {sorted(LANG)} 之一", None

    cleaned = {
        "source_id": payload.get("source_id"),
        "db_type": db_type,
        "version": version,
        "category": category,
        "key": key,
        "value": (payload.get("value") or "").strip() or None,
        "excerpt": (payload.get("excerpt") or "").strip() or None,
        "official_url": (payload.get("official_url") or "").strip() or None,
        "severity": severity,
        "lang": lang,
        "created_by": (payload.get("created_by") or "").strip() or None,
    }
    return True, "", cleaned


# ─────────────────────────── 编排 ───────────────────────────
def create_source(payload: dict):
    ok, err, cleaned = validate_source(payload)
    if not ok:
        return {"ok": False, "error": err}
    sid = models.insert_source(**cleaned)
    return {"ok": True, "id": sid}


def create_fact(payload: dict):
    ok, err, cleaned = validate_fact(payload)
    if not ok:
        return {"ok": False, "error": err}
    fid = models.insert_fact(**cleaned)
    return {"ok": True, "id": fid}


def update_fact(fid: int, payload: dict):
    """部分更新事实：仅校验并提供到的字段，不强制全量（PUT 语义）。"""
    updated = {}
    # db_type（可选，若提供需合法并归一化）
    if "db_type" in payload and payload["db_type"] is not None:
        dt = _clean_db_type(payload["db_type"])
        if not dt or dt not in _VALID_DB_TYPES:
            return {"ok": False, "error": f"不支持的 db_type：{payload.get('db_type')}"}
        updated["db_type"] = dt
    # version
    if "version" in payload and payload["version"] is not None:
        v = (payload["version"] or "").strip()
        if not v:
            return {"ok": False, "error": "version 不能为空"}
        updated["version"] = v
    # category
    if "category" in payload and payload["category"] is not None:
        cat = (payload["category"] or "").strip().lower()
        if cat not in CATEGORY:
            return {"ok": False, "error": f"category 必须是 {sorted(CATEGORY)} 之一"}
        updated["category"] = cat
    # key
    if "key" in payload and payload["key"] is not None:
        k = (payload["key"] or "").strip()
        if not k:
            return {"ok": False, "error": "key 不能为空"}
        updated["key"] = k
    # severity
    if "severity" in payload and payload["severity"] is not None:
        sev = (payload["severity"] or "").strip().lower()
        if sev and sev not in SEVERITY:
            return {"ok": False, "error": f"severity 必须是 {sorted(SEVERITY)} 之一"}
        updated["severity"] = sev or None
    # lang
    if "lang" in payload and payload["lang"] is not None:
        lg = (payload["lang"] or "").strip().lower()
        if lg not in LANG:
            return {"ok": False, "error": f"lang 必须是 {sorted(LANG)} 之一"}
        updated["lang"] = lg
    # 自由文本字段（空串归一为 None）
    for fld in ("value", "excerpt", "official_url", "note", "license_note", "title"):
        if fld in payload and payload[fld] is not None:
            updated[fld] = (payload[fld] or "").strip() or None
    if "source_id" in payload:
        updated["source_id"] = payload["source_id"]
    if not updated:
        return {"ok": False, "error": "无可更新字段"}
    ok = models.update_fact(fid, updated)
    return {"ok": ok, "id": fid}


def delete_fact(fid: int):
    ok = models.delete_fact(fid)
    return {"ok": ok, "id": fid}


def bulk_import(facts: list, created_by: str = None):
    """批量导入事实（import 面板手动粘贴场景）。返回成功/失败计数。"""
    created, errors = 0, []
    for i, item in enumerate(facts or []):
        if not isinstance(item, dict):
            errors.append({"index": i, "error": "条目必须是对象"})
            continue
        if created_by:
            item = {**item, "created_by": item.get("created_by") or created_by}
        res = create_fact(item)
        if res["ok"]:
            created += 1
        else:
            errors.append({"index": i, "error": res["error"], "key": item.get("key")})
    return {"ok": True, "created": created, "errors": errors}


# ─────────────────────────── 策展辅助（Phase 2 占位）───────────────────────────
def extract_from_url(url: str, db_type: str, version: str = "all") -> dict:
    """把官方文档页抽成结构化事实草稿（Phase 2 能力，当前版本降级）。

    设计意图：复用 analyzer 的 AI backend 配置（Ollama/OpenAI）把页面内容
    抽成待人工校验的事实列表。Phase 0/1 不实现 LLM 调用，明确返回「未实现」，
    前端 import 面板可据此把按钮置灰或提示。
    """
    return {
        "ok": False,
        "error": "AI 抽取为 Phase 2 能力，当前版本尚未实现；请手动粘贴事实后保存。",
        "draft": [],
        "url": url,
        "db_type": _clean_db_type(db_type),
        "version": version,
    }
