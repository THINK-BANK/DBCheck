# SPDX-License-Identifier: Apache-2.0
# Copyright 2025-2026 fiyo (Jack Ge) <sdfiyon@gmail.com>
# Author: fiyo (Jack Ge) - https://github.com/fiyo/DBCheck

"""
RAG 检索器 — 将向量检索结果格式化为 Prompt 上下文

核心方法：
- retrieve_for_diagnosis(): 为 AI 诊断场景构建检索查询并格式化结果
- format_rag_context(): 将检索结果格式化为 LLM 可读的文本
"""

from .vector_store import VectorStore
from .embeddings import OllamaEmbedding


class RAGRetriever:
    """RAG 检索器，整合查询构建和结果格式化"""

    def __init__(self, vector_store: VectorStore, embedding_model: OllamaEmbedding = None):
        self.vector_store = vector_store
        self.embedding_model = embedding_model or OllamaEmbedding()

    def retrieve_for_diagnosis(self, db_type: str, metrics: dict,
                               issues: list, top_k: int = 3) -> list:
        """为数据库诊断场景检索参考文档（向量召回 + DocKB 官方事实合并）。

        检索策略：
        1. DocKB 结构化召回（零 embedding 依赖，始终优先，官方事实权威）：
           from modules.doc_kb import lookup_for_diagnosis
        2. 向量召回（依赖 embedding，失败则静默降级）：
           从 issues/metrics 提炼查询 → embedding → vector_store.search
        3. 合并去重（DocKB 优先），返回 list[dict] 供 format_rag_context 渲染。

        Returns:
            结构化结果列表（对齐 vector_store.search schema + DocKB 专属字段）；
            无结果返回 []。注意：本方法只返回原始结果列表，由调用方
            format_rag_context() 渲染——不再在此二次格式化（修复既有 double-format bug）。
        """
        # 1. DocKB 结构化召回（零 embedding 依赖，始终可用，官方事实优先）
        dockb_results = []
        try:
            from modules.doc_kb import lookup_for_diagnosis
            dockb_results = lookup_for_diagnosis(db_type, metrics, issues, top_k=top_k)
        except Exception:
            dockb_results = []

        # 2. 向量召回（依赖 embedding；失败则静默降级）
        vector_results = []
        query_texts = self._build_diagnosis_queries(db_type, metrics, issues)
        if query_texts and self.embedding_model is not None:
            seen_ids = set()
            for query_text in query_texts[:3]:  # 最多 3 个查询
                try:
                    query_emb = self.embedding_model.embed_text(query_text)
                    results = self.vector_store.search(
                        query_emb, db_type=db_type, top_k=top_k
                    )
                    for res in results:
                        key = f"{res['doc_id']}_{res['chunk_index']}"
                        if key not in seen_ids:
                            seen_ids.add(key)
                            vector_results.append(res)
                except Exception:
                    # 单次查询失败不影响整体
                    continue
            vector_results.sort(key=lambda x: x.get('score', 0), reverse=True)

        # 3. 合并去重（DocKB 官方事实优先，向量结果补全），统一 schema
        merged = []
        seen = set()
        for res in (dockb_results + vector_results):
            key = f"{res.get('doc_id')}_{res.get('chunk_index')}"
            if key in seen:
                continue
            seen.add(key)
            merged.append(res)
        return merged[:max(top_k, 5)]

    def _build_diagnosis_queries(self, db_type: str, metrics: dict,
                                  issues: list) -> list[str]:
        """
        从诊断上下文构建检索查询列表

        生成 2~5 个查询，覆盖不同角度：
        - 数据库类型 + 风险类型
        - 数据库类型 + 具体指标
        - 数据库类型 + SQL 语句/错误信息
        """
        queries = []

        # 映射中文 db_type 到英文（便于匹配英文文档）
        type_map = {
            'mysql': 'MySQL',
            'pg': 'PostgreSQL',
            'oracle': 'Oracle',
            'sqlserver': 'SQL Server',
            'tidb': 'TiDB',
            'dm': 'DM8',
        }
        db_name = type_map.get(db_type.lower(), db_type.upper())

        # 从 issues 提取关键词
        risk_keywords = []
        for issue in issues[:5]:
            col1 = issue.get('col1', '')
            col3 = issue.get('col3', '')
            if col1:
                risk_keywords.append(col1[:30])
            if col3:
                # 提取 col3 中的关键名词（去掉句号后的第一句）
                first_sent = col3.split('。')[0].split('.')[0].strip()
                if len(first_sent) < 50:
                    risk_keywords.append(first_sent[:40])

        # 从 metrics 提取异常指标
        metric_keywords = []
        metric_keys = [
            'slow_query_count', 'avg_lock_time', 'cache_hit_ratio',
            'connection_usage', 'disk_usage_max', 'cpu_usage', 'mem_usage',
            'wait_events_top5', 'blocked_sessions', 'long_running_transactions',
            'replication_lag', 'binlog_size', 'undo_tablespace_size',
        ]
        for key in metric_keys:
            if key in metrics and metrics[key] not in (None, 'N/A', '', 0, 0.0):
                label = key.replace('_', ' ')
                metric_keywords.append(label)

        # 组合查询
        if risk_keywords:
            queries.append(f"{db_name} {risk_keywords[0]}")
        if metric_keywords:
            queries.append(f"{db_name} {metric_keywords[0]} performance tuning")

        # 添加通用诊断查询
        queries.append(f"{db_name} database health check best practices")

        # 组合长查询
        if risk_keywords and metric_keywords:
            queries.append(f"{db_name} {risk_keywords[0]} {metric_keywords[0]}")

        # 去重
        seen = set()
        unique_queries = []
        for q in queries:
            if q.lower() not in seen:
                seen.add(q.lower())
                unique_queries.append(q)

        return unique_queries

    def format_rag_context(self, results: list[dict], lang: str = 'zh') -> str:
        """将检索结果格式化为 Prompt 可用的上下文。

        results 来自 vector_store.search（向量片段）或 doc_kb.lookup_for_diagnosis
        （官方事实），二者 schema 兼容：均含 doc_id/chunk_index/content/source/title/
        db_type/score；DocKB 结果额外含 official_url/category/key/value/severity。

        Args:
            results: 结构化结果列表（list[dict]）
            lang: 'zh' 或 'en'

        Returns:
            格式化的上下文文本；空列表返回 ''
        """
        if not results:
            return ''

        if lang == 'zh':
            header = ["## 参考文档知识库（官方文档 + 向量片段）\n"]
            header.append(f"（共检索到 {len(results)} 条相关参考，请优先参考并标注来源）\n")
        else:
            header = ["## Reference Documentation (official docs + vector fragments)\n"]
            header.append(f"({len(results)} relevant references found)\n\n")

        lines = []
        for i, res in enumerate(results, 1):
            db_type = res.get('db_type', '')
            category = res.get('category', '')
            key = res.get('key', '')
            value = res.get('value', '')
            title = res.get('title') or key or res.get('source', '未知来源')
            source = res.get('source', '')
            official_url = res.get('official_url') or source
            score = res.get('score', 0)
            severity = res.get('severity', '')
            content = res.get('content', '')

            # 截断每块内容（避免 Prompt 过长，单块最多 300 字）
            if content and len(content) > 300:
                content = content[:300] + '...'

            # 标签行（中文/英文）
            if lang == 'zh':
                tag = f"片段 {i}｜{db_type}" + (f"｜{category}" if category else "")
                tag += (f"｜{key}" if key else "")
                if isinstance(score, (int, float)):
                    tag += f"｜相关度 {score:.2f}"
                if severity:
                    tag += f"｜严重度 {severity}"
            else:
                tag = f"Fragment {i}｜{db_type}" + (f"｜{category}" if category else "")
                tag += (f"｜{key}" if key else "")
                if isinstance(score, (int, float)):
                    tag += f"｜relevance {score:.2f}"
                if severity:
                    tag += f"｜severity {severity}"

            lines.append(f"### {tag}")
            if value:
                lines.append(f"官方事实: {value}")
            if official_url:
                lines.append(f"来源: {official_url}")
            elif source:
                lines.append(f"来源: {source}")
            if content and content != value:
                lines.append(content)
            lines.append("")  # 空行分隔

        return '\n'.join(header + lines)

    def retrieve_for_chat(self, query_text: str, db_type: str = None,
                          top_k: int = 5) -> str:
        """
        通用问答检索 — 根据用户自然语言问题检索知识库相关片段

        Args:
            query_text: 用户提问文本
            db_type: 可选的数据库类型过滤（mysql/pg/oracle/dm/sqlserver/tidb）
            top_k: 返回结果数量

        Returns:
            格式化的 RAG 上下文文本，空字符串表示无结果
        """
        try:
            emb = self.embedding_model.embed_text(query_text)
            results = self.vector_store.search(emb, db_type=db_type, top_k=top_k)
            if not results:
                return ''
            return self.format_rag_context(results, lang='zh')
        except Exception:
            return ''

    def test_retrieve(self, query_text: str, db_type: str = None,
                      top_k: int = 5) -> list[dict]:
        """
        测试检索（供 Web UI 调用）

        Returns:
            检索结果列表（未格式化）
        """
        try:
            emb = self.embedding_model.embed_text(query_text)
            return self.vector_store.search(emb, db_type=db_type, top_k=top_k)
        except Exception as e:
            raise RuntimeError(f"检索失败: {e}")
