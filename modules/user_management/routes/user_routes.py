# -*- coding: utf-8 -*-
# SPDX-License-Identifier: Apache-2.0
# Copyright 2025-2026 fiyo (Jack Ge) <sdfiyon@gmail.com>
# Author: fiyo (Jack Ge) - https://github.com/fiyo/DBCheck

"""
用户管理路由 - 用户 CRUD API
"""

from flask import Blueprint, request, jsonify, g
from modules.user_management.utils.auth_decorator import (
    login_required, require_permission, require_admin
)
from modules.user_management.services.user_service import UserService
from modules.user_management.services.perm_service import PermService

user_bp = Blueprint('um_user', __name__, url_prefix='/api/um/user')
user_service = UserService()
perm_service = PermService()


@user_bp.route('/list', methods=['GET'])
@require_permission('system_manage')
def list_users():
    """获取用户列表"""
    page = request.args.get('page', 1, type=int)
    size = request.args.get('size', 20, type=int)
    status = request.args.get('status', type=int)
    result = user_service.list_users(page, size, status)
    return jsonify({'code': 0, 'data': result})


@user_bp.route('', methods=['POST'])
@require_permission('system_manage')
def create_user():
    """新建用户"""
    data = request.get_json(silent=True) or {}
    required = ['username', 'password']
    for field in required:
        if field not in data:
            return jsonify({
                'code': 400,
                'msg': f'缺少必填字段: {field}'
            }), 400

    try:
        user_id = user_service.create_user(
            username=data['username'],
            password=data['password'],
            nickname=data.get('nickname', ''),
            email=data.get('email', '')
        )
        return jsonify({
            'code': 0,
            'data': {'id': user_id},
            'msg': '用户创建成功'
        })
    except ValueError as e:
        return jsonify({'code': 400, 'msg': str(e)}), 400


@user_bp.route('/<int:uid>', methods=['GET'])
@require_permission('system_manage')
def get_user(uid):
    """获取用户详情"""
    user = user_service.get_user(uid)
    if not user:
        return jsonify({'code': 404, 'msg': '用户不存在'}), 404

    # 不返回密码
    user.pop('password', None)
    return jsonify({'code': 0, 'data': user})


@user_bp.route('/<int:uid>', methods=['PUT'])
@require_permission('system_manage')
def update_user(uid):
    """修改用户信息"""
    data = request.get_json(silent=True) or {}
    allowed = ['nickname', 'email', 'status', 'password']
    updates = {k: v for k, v in data.items()
               if k in allowed and v is not None}
    if not updates:
        return jsonify({
            'code': 400,
            'msg': '没有可更新的字段'
        }), 400

    user_service.update_user(uid, **updates)
    return jsonify({'code': 0, 'msg': '用户更新成功'})


@user_bp.route('/<int:uid>', methods=['DELETE'])
@require_admin
def delete_user(uid):
    """删除用户"""
    # 1. 不能删除自己
    if uid == g.current_user['user_id']:
        return jsonify({'code': 400, 'msg': '不能删除当前登录用户'}), 400

    # 2. 检查是否要删除的是管理员，且是最后一个
    user = user_service.get_user(uid)
    if user and 'admin' in [r.get('role_code') for r in user.get('roles', [])]:
        admin_count = user_service.count_users_by_role('admin')
        if admin_count <= 1:
            return jsonify({'code': 400, 'msg': '不能删除最后一个管理员用户'}), 400

    user_service.delete_user(uid)
    return jsonify({'code': 0, 'msg': '用户已删除'})


@user_bp.route('/<int:uid>/roles', methods=['GET'])
@require_permission('system_manage')
def get_user_roles(uid):
    """获取用户角色"""
    roles = user_service.get_user_roles(uid)
    return jsonify({'code': 0, 'data': roles})


@user_bp.route('/<int:uid>/roles', methods=['PUT'])
@require_permission('system_manage')
def assign_roles(uid):
    """为用户分配角色"""
    data = request.get_json(silent=True) or {}
    new_role_ids = data.get('role_ids', [])

    # 如果目标用户是管理员，检查是否是最后一个
    user = user_service.get_user(uid)
    if user and 'admin' in [r.get('role_code') for r in user.get('roles', [])]:
        admin_count = user_service.count_users_by_role('admin')
        # 检查新角色列表里是否还包含 admin 角色
        admin_role = user_service.db.query_one(
            "SELECT id FROM um_role WHERE role_code='admin'", ()
        )
        if admin_role and admin_role['id'] not in new_role_ids:
            if admin_count <= 1:
                return jsonify({
                    'code': 400,
                    'msg': '不能移除最后一个管理员用户的管理员角色'
                }), 400

    user_service.assign_roles(uid, new_role_ids)
    return jsonify({'code': 0, 'msg': '角色分配成功'})


@user_bp.route('/<int:uid>/assets', methods=['GET'])
@require_permission('system_manage')
def get_user_assets(uid):
    """获取用户绑定的资产"""
    allowed_ids = perm_service.get_allowed_asset_ids(uid)
    return jsonify({'code': 0, 'data': allowed_ids})


@user_bp.route('/<int:uid>/assets', methods=['PUT'])
@require_permission('system_manage')
def bind_assets(uid):
    """为用户绑定可见数据库资产"""
    data = request.get_json(silent=True) or {}
    asset_ids = data.get('asset_ids', [])
    user_service.bind_assets(uid, asset_ids)
    return jsonify({'code': 0, 'msg': '资产绑定成功'})


@user_bp.route('/<int:uid>/modules', methods=['PUT'])
@require_permission('system_manage')
def bind_modules(uid):
    """为用户配置模块可见性和权限级别"""
    data = request.get_json(silent=True) or {}
    modules = data.get('modules', [])
    # modules 格式: [{"menu_id": 1, "perm_id": 2}, ...]
    user_service.bind_modules(uid, modules)
    return jsonify({'code': 0, 'msg': '模块配置成功'})


@user_bp.route('/menus', methods=['GET'])
@login_required
def get_my_menus():
    """获取当前用户可见菜单及权限"""
    user_id = g.current_user['user_id']
    menus = perm_service.get_user_visible_menus(user_id)
    return jsonify({'code': 0, 'data': menus})


@user_bp.route('/profile', methods=['PUT'])
@login_required
def update_profile():
    """修改当前用户个人信息（昵称、邮箱）"""
    user_id = g.current_user['user_id']
    data = request.get_json(silent=True) or {}
    allowed = ['nickname', 'email']
    updates = {k: v for k, v in data.items() if k in allowed and v is not None}
    if not updates:
        return jsonify({'code': 400, 'msg': '没有可更新的字段'}), 400
    user_service.update_user(user_id, **updates)
    return jsonify({'code': 0, 'msg': '保存成功'})


@user_bp.route('/password', methods=['PUT'])
@login_required
def change_password():
    """修改当前用户密码"""
    user_id = g.current_user['user_id']
    data = request.get_json(silent=True) or {}
    old_password = data.get('old_password', '')
    new_password = data.get('new_password', '')
    if not old_password or not new_password:
        return jsonify({'code': 400, 'msg': '请填写旧密码和新密码'}), 400
    if len(new_password) < 6:
        return jsonify({'code': 400, 'msg': '新密码至少6位'}), 400
    if old_password == new_password:
        return jsonify({'code': 400, 'msg': '新密码不能与旧密码相同'}), 400
    # 验证旧密码
    from modules.user_management.utils.password import verify_password, hash_password
    user = user_service.get_user(user_id)
    if not user or not verify_password(old_password, user['password']):
        return jsonify({'code': 400, 'msg': '旧密码错误'}), 400
    # 更新密码
    user_service.update_user(user_id, password=hash_password(new_password))
    return jsonify({'code': 0, 'msg': '密码修改成功'})
