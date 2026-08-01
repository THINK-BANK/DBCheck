# -*- coding: utf-8 -*-
# SPDX-License-Identifier: Apache-2.0
# Copyright 2025-2026 fiyo (Jack Ge) <sdfiyon@gmail.com>
# Author: fiyo (Jack Ge) - https://github.com/fiyo/DBCheck

"""
巡检「章节可选」共享过滤 helper。

所有针对 inspection.db (SQLite) 的章节过滤都调用 build_chapter_filter_sql，
逻辑单点：
  - chapter_ids 为 None      -> 不过滤（等价旧行为，全量巡检）
  - chapter_ids 为非空 list   -> 追加 " AND <alias>.id IN (?, ?, ?)" 片段 + 对应参数
  - chapter_ids 为 [] (空列表) -> 视为非法输入，上层（api_start_inspection）应已拦截 400；
                                  此处兜底返回不过滤（等价全量），避免生成非法 SQL 导致崩溃
                                  （绝不会生成 "IN ()" 这种无效语句）。

SQL 占位符统一使用 ?（SQLite 参数化），禁止对 chapter_ids 做字符串拼接。
"""

from typing import List, Optional, Tuple, Union


def _is_safe_identifier(name: str) -> bool:
    """校验 SQL 标识符（别名）是否安全，仅允许字母/数字/下划线。

    防止任何注入风险：alias 仅来自代码内部常量，不从用户输入取值。
    """
    return bool(name) and all(c.isalnum() or c == '_' for c in name)


def build_chapter_filter_sql(
    chapter_ids: Optional[Union[List[int], Tuple[int, ...]]],
    alias: str = 'ch',
) -> Tuple[str, List[int]]:
    """构建章节 IN 过滤的 SQL 片段与参数。

    Args:
        chapter_ids: 选中的章节 ID 列表。
                     None  -> 全量（不过滤）；
                     非空 list -> 仅包含这些章节；
                     空 list  -> 非法（上层应已 400），兜底不过滤。
        alias: inspection_chapter 表在 SQL 中的别名。
               'ch'  （默认）：用于 JOIN inspection_chapter ch ... 的查询；
               '' / None：直接用于 "FROM inspection_chapter WHERE ..." 无别名的查询。

    Returns:
        (sql_fragment, params) 元组：
          - sql_fragment: 形如 " AND ch.id IN (?, ?, ?)" 的字符串（不含前导空格外的额外字符），
                          或空字符串（不过滤时）。
          - params: 对应章节 ID 列表（不过滤时为空列表）。

    Examples:
        >>> build_chapter_filter_sql(None)
        ('', [])
        >>> build_chapter_filter_sql([1, 2, 5])
        (' AND ch.id IN (?, ?, ?)', [1, 2, 5])
        >>> build_chapter_filter_sql([], alias='')
        ('', [])
    """
    # None 或空列表：不过滤（全量）。空列表由上层 400 拦截，这里兜底。
    if not chapter_ids:
        return '', []

    # 规整为 int 列表，过滤掉非整数，保证参数化类型安全
    safe_ids: List[int] = []
    for _cid in chapter_ids:
        try:
            safe_ids.append(int(_cid))
        except (TypeError, ValueError):
            # 跳过无法转换为 int 的脏数据，避免注入/崩溃
            continue

    if not safe_ids:
        return '', []

    # 安全别名：仅 'ch' 等受控常量；非法别名回退为 'ch'
    if alias:
        col = ('ch' if not _is_safe_identifier(alias) else alias) + '.id'
    else:
        col = 'id'

    placeholders = ', '.join('?' for _ in safe_ids)
    sql_fragment = f' AND {col} IN ({placeholders})'
    return sql_fragment, safe_ids
