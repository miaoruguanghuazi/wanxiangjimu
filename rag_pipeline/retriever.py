"""
检索层（ChromaDB 本地化版）

检索策略：
1. 向量语义检索（ChromaDB 内置）— 捕获语义相似性
2. 关键词匹配（ChromaDB where_document 条件）— 捕获精确匹配
3. RRF 融合 — 合并两个排序列表

支持多租户过滤和自定义过滤条件。
无需 Elasticsearch，全部在 ChromaDB 内完成。
"""

from __future__ import annotations

import asyncio
import logging
import re
from typing import Any, Optional

from .models import Chunk, RetrievalResult

logger = logging.getLogger(__name__)


class Reranker:
    """简单 Reranker（本地关键词匹配评分）

    用 TF-IDF 思想对检索结果进行精排。
    无需外部服务，纯 Python 实现。
    """

    async def rerank(
        self,
        query: str,
        documents: list[str],
        top_k: int = 10,
    ) -> list[dict[str, Any]]:
        """对文档列表进行 Rerank

        Args:
            query: 查询文本
            documents: 文档文本列表
            top_k: 返回前 K 个

        Returns:
            排序结果列表，每个元素包含 index 和 relevance_score
        """
        if not documents:
            return []

        # 分词
        query_terms = set(self._tokenize(query))

        scores: list[tuple[int, float]] = []
        for idx, doc in enumerate(documents):
            doc_terms = self._tokenize(doc)
            if not doc_terms:
                scores.append((idx, 0.0))
                continue

            # TF 计算
            doc_term_count: dict[str, int] = {}
            for term in doc_terms:
                doc_term_count[term] = doc_term_count.get(term, 0) + 1

            # 简单 TF-IDF：query term 在 doc 中出现次数 / doc 长度
            tf_score: float = 0.0
            for term in query_terms:
                if term in doc_term_count:
                    tf_score += doc_term_count[term] / len(doc_terms)

            # 归一化
            normalized = tf_score / max(len(query_terms), 1)
            scores.append((idx, normalized))

        # 按分数降序排序
        scores.sort(key=lambda x: x[1], reverse=True)

        return [
            {"index": idx, "relevance_score": score}
            for idx, score in scores[:top_k]
        ]

    @staticmethod
    def _tokenize(text: str) -> list[str]:
        """简单分词：中英文混合"""
        # 英文：按空格和标点分
        # 中文：按字分（简单方案，不依赖 jieba）
        tokens: list[str] = []
        # 英文单词
        en_tokens = re.findall(r'[a-zA-Z]{2,}', text.lower())
        tokens.extend(en_tokens)
        # 中文单字
        zh_chars = re.findall(r'[\u4e00-\u9fff]', text)
        tokens.extend(zh_chars)
        return tokens


class HybridRetriever:
    """混合检索器（ChromaDB 版）

    融合向量语义检索和关键词检索，通过 RRF 合并。

    Usage::

        from rag_pipeline import VectorIndexer, HybridRetriever

        indexer = VectorIndexer(persist_path="./data/chroma")
        retriever = HybridRetriever(indexer=indexer)
        result = await retriever.retrieve("如何配置数据库", tenant_id="t001", top_k=5)
    """

    def __init__(
        self,
        indexer: Any = None,
        collection: Any = None,
        reranker: Optional[Reranker] = None,
        collection_name: str = "wanxiang_rag",
    ) -> None:
        """初始化检索器

        Args:
            indexer: VectorIndexer 实例（用于获取 Collection）
            collection: 直接传入 ChromaDB Collection（与 indexer 二选一）
            reranker: Reranker 实例（可选，无则跳过 Rerank）
            collection_name: Collection 名称
        """
        self.indexer = indexer
        if collection:
            self.collection = collection
        elif indexer:
            self.collection = indexer.collection
        else:
            self.collection = None
        self.reranker = reranker or Reranker()
        self.collection_name = collection_name

    # ──────────────────────────── 检索入口 ────────────────────────────

    async def retrieve(
        self,
        query: str,
        tenant_id: str = "default",
        top_k: int = 10,
        filters: Optional[dict[str, Any]] = None,
        rerank: bool = True,
    ) -> RetrievalResult:
        """混合检索

        Step 1: 向量语义检索（ChromaDB）
        Step 2: 关键词检索（ChromaDB where_document）
        Step 3: RRF 融合合并去重
        Step 4: 本地 Rerank（可选）
        Step 5: 返回 Top-K

        Args:
            query: 查询文本
            tenant_id: 租户 ID
            top_k: 返回前 K 个结果
            filters: 过滤条件
            rerank: 是否执行 Rerank

        Returns:
            RetrievalResult 检索结果
        """
        if not self.collection:
            return RetrievalResult(
                chunks=[],
                query=query,
                retrieval_type="none",
                total_found=0,
                reranked=False,
            )

        # 构建 ChromaDB where 条件
        where_clause: dict[str, Any] = {"tenant_id": tenant_id}
        if filters:
            for key, value in filters.items():
                where_clause[key] = value

        # Step 1+2: 并行检索
        tasks: list[asyncio.Task] = [
            asyncio.create_task(
                self._vector_search(query, where_clause, top_k=20)
            ),
            asyncio.create_task(
                self._keyword_search(query, where_clause, top_k=20)
            ),
        ]

        results = await asyncio.gather(*tasks, return_exceptions=True)

        vector_results: list[Chunk] = results[0] if not isinstance(results[0], Exception) else []
        if isinstance(results[0], Exception):
            logger.warning(f"向量检索失败: {results[0]}")

        keyword_results: list[Chunk] = results[1] if not isinstance(results[1], Exception) else []
        if isinstance(results[1], Exception):
            logger.warning(f"关键词检索失败: {results[1]}")

        # Step 3: RRF 融合
        merged: list[Chunk] = self._reciprocal_rank_fusion(
            vector_results, keyword_results, k=60
        )

        if not merged:
            return RetrievalResult(
                chunks=[],
                query=query,
                retrieval_type="hybrid",
                total_found=0,
                reranked=False,
            )

        # Step 4: Rerank
        reranked: bool = False
        if rerank and self.reranker and len(merged) > 1:
            rerank_results = await self.reranker.rerank(
                query=query,
                documents=[c.content for c in merged],
                top_k=top_k,
            )
            for item in rerank_results:
                idx: int = item["index"]
                if idx < len(merged):
                    merged[idx].score = float(item["relevance_score"])
            merged = [merged[item["index"]] for item in rerank_results if item["index"] < len(merged)]
            reranked = True

        # Step 5: 组装结果
        retrieval_type: str = "hybrid_reranked" if reranked else "hybrid"

        return RetrievalResult(
            chunks=merged[:top_k],
            query=query,
            retrieval_type=retrieval_type,
            total_found=len(merged),
            reranked=reranked,
        )

    # ──────────────────────────── 向量语义检索 ────────────────────────────

    async def _vector_search(
        self,
        query: str,
        where_clause: dict[str, Any],
        top_k: int = 20,
    ) -> list[Chunk]:
        """ChromaDB 向量语义检索

        Args:
            query: 查询文本（ChromaDB 自动向量化）
            where_clause: 元数据过滤条件
            top_k: 返回数量

        Returns:
            切片列表
        """
        def _search():
            return self.collection.query(
                query_texts=[query],
                n_results=top_k,
                where=where_clause,
                include=["documents", "metadatas", "distances"],
            )

        result = await asyncio.to_thread(_search)

        chunks: list[Chunk] = []
        if not result or not result.get("ids"):
            return chunks

        ids_list = result["ids"][0] if result["ids"] else []
        docs_list = result["documents"][0] if result["documents"] else []
        meta_list = result["metadatas"][0] if result["metadatas"] else []
        dist_list = result["distances"][0] if result["distances"] else []

        for i, doc_text in enumerate(docs_list):
            meta = meta_list[i] if i < len(meta_list) else {}
            distance = dist_list[i] if i < len(dist_list) else 1.0
            # ChromaDB distance → similarity score (cosine: distance=0→sim=1)
            score = max(0.0, 1.0 - distance)

            chunks.append(Chunk(
                chunk_id=meta.get("chunk_id", ids_list[i]),
                doc_id=meta.get("doc_id", ""),
                tenant_id=meta.get("tenant_id", "default"),
                content=doc_text,
                chunk_type=meta.get("chunk_type", "text"),
                parent_chunk_id=meta.get("parent_chunk_id") or None,
                children_ids=[],
                page=meta.get("page") if meta.get("page", -1) != -1 else None,
                section=meta.get("section") or None,
                token_count=meta.get("token_count", 0),
                embedding=[],
                metadata=meta,
                score=score,
            ))

        return chunks

    # ──────────────────────────── 关键词检索 ────────────────────────────

    async def _keyword_search(
        self,
        query: str,
        where_clause: dict[str, Any],
        top_k: int = 20,
    ) -> list[Chunk]:
        """ChromaDB 关键词检索

        使用 ChromaDB 的 where_document 功能进行关键词匹配。

        Args:
            query: 查询文本
            where_clause: 元数据过滤条件
            top_k: 返回数量

        Returns:
            切片列表
        """
        # 提取关键词
        keywords = self._extract_keywords(query)
        if not keywords:
            return []

        def _search():
            # ChromaDB where_document 支持 $contains
            results = []
            for kw in keywords[:3]:  # 最多用3个关键词
                try:
                    r = self.collection.query(
                        query_texts=None,
                        where_document={"$contains": kw},
                        where=where_clause,
                        n_results=top_k,
                        include=["documents", "metadatas", "distances"],
                    )
                    if r and r.get("ids"):
                        results.append(r)
                except Exception as e:
                    logger.debug(f"关键词 '{kw}' 检索失败: {e}")
            return results

        raw_results = await asyncio.to_thread(_search)

        # 合并去重
        seen_ids: set[str] = set()
        chunks: list[Chunk] = []

        for raw in raw_results:
            if not raw or not raw.get("ids"):
                continue
            ids_list = raw["ids"][0] if raw["ids"] else []
            docs_list = raw["documents"][0] if raw["documents"] else []
            meta_list = raw["metadatas"][0] if raw["metadatas"] else []

            for i, doc_text in enumerate(docs_list):
                meta = meta_list[i] if i < len(meta_list) else {}
                cid = meta.get("chunk_id", ids_list[i])

                if cid in seen_ids:
                    continue
                seen_ids.add(cid)

                # 关键词匹配数作为分数
                match_count = sum(1 for kw in keywords if kw in doc_text)
                score = match_count / max(len(keywords), 1)

                chunks.append(Chunk(
                    chunk_id=cid,
                    doc_id=meta.get("doc_id", ""),
                    tenant_id=meta.get("tenant_id", "default"),
                    content=doc_text,
                    chunk_type=meta.get("chunk_type", "text"),
                    parent_chunk_id=meta.get("parent_chunk_id") or None,
                    children_ids=[],
                    page=meta.get("page") if meta.get("page", -1) != -1 else None,
                    section=meta.get("section") or None,
                    token_count=meta.get("token_count", 0),
                    embedding=[],
                    metadata=meta,
                    score=score,
                ))

        # 按匹配分数排序
        chunks.sort(key=lambda c: c.score, reverse=True)
        return chunks[:top_k]

    # ──────────────────────────── RRF 融合 ────────────────────────────

    @staticmethod
    def _reciprocal_rank_fusion(
        vector_results: list[Chunk],
        keyword_results: list[Chunk],
        k: int = 60,
    ) -> list[Chunk]:
        """RRF（Reciprocal Rank Fusion）融合算法

        score(d) = Σ 1 / (k + rank(d))

        Args:
            vector_results: 向量检索结果列表
            keyword_results: 关键词检索结果列表
            k: RRF 平滑常数

        Returns:
            融合后的切片列表（按 RRF 分数降序）
        """
        rrf_scores: dict[str, float] = {}
        chunk_map: dict[str, Chunk] = {}

        for rank, chunk in enumerate(vector_results):
            cid: str = chunk.chunk_id
            chunk_map[cid] = chunk
            rrf_scores[cid] = rrf_scores.get(cid, 0.0) + 1.0 / (k + rank + 1)

        for rank, chunk in enumerate(keyword_results):
            cid = chunk.chunk_id
            if cid not in chunk_map:
                chunk_map[cid] = chunk
            rrf_scores[cid] = rrf_scores.get(cid, 0.0) + 1.0 / (k + rank + 1)

        sorted_ids: list[str] = sorted(rrf_scores, key=rrf_scores.get, reverse=True)

        result: list[Chunk] = []
        for cid in sorted_ids:
            chunk: Chunk = chunk_map[cid]
            chunk.score = rrf_scores[cid]
            result.append(chunk)

        return result

    # ──────────────────────────── 关键词提取 ────────────────────────────

    @staticmethod
    def _extract_keywords(query: str) -> list[str]:
        """从查询中提取关键词

        简单方案：去停用词，取有意义的词
        """
        # 停用词
        stop_words = {
            "的", "了", "是", "在", "我", "有", "和", "就", "不", "人", "都",
            "一", "一个", "上", "也", "很", "到", "说", "要", "去", "你",
            "会", "着", "没有", "看", "好", "自己", "这", "那", "怎么",
            "什么", "为什么", "哪里", "哪个", "如何", "可以", "能", "吗",
            "呢", "吧", "啊", "请", "帮", "帮我", "查找", "搜索",
            "the", "a", "an", "is", "are", "was", "were", "be", "been",
            "to", "of", "in", "on", "at", "by", "for", "with", "about",
            "how", "what", "why", "where", "which", "can", "could",
        }

        # 英文词
        en_words = re.findall(r'[a-zA-Z]{2,}', query.lower())
        # 中文连续字（2-4字）
        zh_words = re.findall(r'[\u4e00-\u9fff]{2,4}', query)

        keywords = []
        for w in en_words + zh_words:
            if w not in stop_words and len(w) >= 2:
                keywords.append(w)

        # 如果没有提取到，用单字
        if not keywords:
            zh_chars = re.findall(r'[\u4e00-\u9fff]', query)
            keywords = [c for c in zh_chars if c not in stop_words]

        return keywords[:5]  # 最多5个关键词
