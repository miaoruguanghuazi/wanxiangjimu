"""
L3 长期记忆 — 向量检索 + 时间衰减 + 重要性加权

职责:
- ChromaDB 向量存储与检索
- 时间衰减计算（半衰期）
- 重要性加权
- 冲突检测
- LLM 信息提取（从对话中提取记忆条目）
"""

from __future__ import annotations

import time
import json
import logging
from typing import Optional
from collections import defaultdict

from .models import MemoryEntry, ScoredMemory, MemoryType, MemoryStatus, HALF_LIFE_MAP

logger = logging.getLogger(__name__)


class LongTermMemory:
    """L3 长期记忆管理器"""

    def __init__(
        self,
        chroma_client=None,
        collection_name: str = "wanxiang_long_term_memory",
    ):
        self._chroma = chroma_client
        self._collection = None
        self._collection_name = collection_name
        self._init_collection()

    def _init_collection(self):
        if self._chroma is None:
            logger.warning("ChromaDB 未初始化，长期记忆功能不可用")
            return
        try:
            self._collection = self._chroma.get_or_create_collection(
                name=self._collection_name,
                metadata={"hnsw:space": "cosine"},
            )
            logger.info(f"✅ 长期记忆集合已加载: {self._collection_name}")
        except Exception as e:
            logger.error(f"初始化长期记忆集合失败: {e}")

    def count(self) -> int:
        if not self._collection:
            return 0
        try:
            return self._collection.count()
        except Exception:
            return 0

    async def store(self, memory: MemoryEntry, embedding: list[float]):
        """存储记忆条目"""
        if not self._collection:
            logger.warning("ChromaDB 集合不可用，跳过存储")
            return

        self._collection.add(
            ids=[memory.id],
            documents=[memory.content],
            embeddings=[embedding],
            metadatas=[memory.to_chroma_metadata()],
        )
        logger.info(f"记忆已存储: {memory.memory_type} | {memory.content[:50]}")

    async def retrieve(
        self,
        query_embedding: list[float],
        user_id: str = "default",
        top_k: int = 5,
        memory_types: list[str] = None,
    ) -> list[ScoredMemory]:
        """
        检索长期记忆

        算法: 语义检索(60%) + 时间衰减(20%) + 重要性(10%) + 访问活跃度(10%)
        """
        if not self._collection:
            return []

        where_filter = {"$and": [{"user_id": user_id}, {"status": "active"}]}
        if memory_types:
            where_filter["$and"].append({"memory_type": {"$in": memory_types}})

        try:
            results = self._collection.query(
                query_embeddings=[query_embedding],
                n_results=min(top_k * 4, 20),
                where=where_filter,
                include=["documents", "metadatas", "distances"],
            )
        except Exception as e:
            logger.error(f"长期记忆检索失败: {e}")
            return []

        if not results["documents"] or not results["documents"][0]:
            return []

        now = time.time()
        scored = []

        for i, doc in enumerate(results["documents"][0]):
            meta = results["metadatas"][0][i]
            distance = results["distances"][0][i]

            # 语义相似度 (cosine distance → similarity)
            semantic_score = max(0, 1 - distance / 2.0)

            # 时间衰减
            created_at = meta.get("created_at", now)
            age_days = max(0, (now - created_at) / 86400)
            half_life = meta.get("half_life_days", 90)
            time_decay = 0.5 ** (age_days / half_life)

            # 重要性加权
            importance = meta.get("importance", 0.5)
            importance_weight = 1 + importance * 0.5

            # 访问活跃度衰减：access_count 越高记忆越「热」，但边际递减
            access_count = meta.get("access_count", 0)
            last_accessed = meta.get("last_accessed", created_at)
            time_since_access = max(0, (now - last_accessed) / 86400)
            # 近期访问的记忆有加权，长期未访问的有衰减
            recency_boost = 0.5 ** (time_since_access / 30)  # 30天半衰期
            access_decay = recency_boost * (1 + min(access_count, 10) * 0.05)

            # 综合得分
            final_score = (
                semantic_score * 0.6
                + time_decay * 0.2
                + importance_weight * 0.1
                + access_decay * 0.1
            )

            scored.append(ScoredMemory(
                memory_id=meta.get("memory_id", ""),
                content=doc,
                memory_type=meta.get("memory_type", "fact"),
                category=meta.get("category", "user_profile"),
                importance=importance,
                final_score=final_score,
                semantic_score=semantic_score,
                time_decay=time_decay,
                access_decay=access_decay,
            ))

        # 检索后更新 access_count 和 last_accessed
        for sm in scored:
            if sm.memory_id:
                try:
                    # ChromaDB update 会覆盖整个 metadata，需要先获取原值再合并
                    existing = self._collection.get(ids=[sm.memory_id], include=["metadatas"])
                    if existing and existing.get("metadatas"):
                        old_meta = existing["metadatas"][0]
                        old_meta["access_count"] = old_meta.get("access_count", 0) + 1
                        old_meta["last_accessed"] = now
                        self._collection.update(
                            ids=[sm.memory_id],
                            metadatas=[old_meta],
                        )
                except Exception:
                    pass  # 更新失败不影响检索结果

        scored.sort(key=lambda x: x.final_score, reverse=True)
        return scored[:top_k]

    async def search_by_content(
        self,
        query_text: str,
        user_id: str = "default",
        top_k: int = 5,
    ) -> list[ScoredMemory]:
        """通过文本搜索（ChromaDB 内置 embedding）"""
        if not self._collection:
            return []

        where_filter = {"$and": [{"user_id": user_id}, {"status": "active"}]}

        try:
            results = self._collection.query(
                query_texts=[query_text],
                n_results=min(top_k * 4, 20),
                where=where_filter,
                include=["documents", "metadatas", "distances"],
            )
        except Exception as e:
            logger.error(f"长期记忆文本搜索失败: {e}")
            return []

        if not results["documents"] or not results["documents"][0]:
            return []

        now = time.time()
        scored = []

        for i, doc in enumerate(results["documents"][0]):
            meta = results["metadatas"][0][i]
            distance = results["distances"][0][i]

            semantic_score = max(0, 1 - distance / 2.0)
            created_at = meta.get("created_at", now)
            age_days = max(0, (now - created_at) / 86400)
            half_life = meta.get("half_life_days", 90)
            time_decay = 0.5 ** (age_days / half_life)
            importance = meta.get("importance", 0.5)
            importance_weight = 1 + importance * 0.5
            access_count = meta.get("access_count", 0)
            last_accessed = meta.get("last_accessed", created_at)
            time_since_access = max(0, (now - last_accessed) / 86400)
            recency_boost = 0.5 ** (time_since_access / 30)
            access_decay = recency_boost * (1 + min(access_count, 10) * 0.05)

            final_score = (
                semantic_score * 0.6
                + time_decay * 0.2
                + importance_weight * 0.1
                + access_decay * 0.1
            )

            scored.append(ScoredMemory(
                memory_id=meta.get("memory_id", ""),
                content=doc,
                memory_type=meta.get("memory_type", "fact"),
                category=meta.get("category", "user_profile"),
                importance=importance,
                final_score=final_score,
                semantic_score=semantic_score,
                time_decay=time_decay,
                access_decay=access_decay,
            ))

        scored.sort(key=lambda x: x.final_score, reverse=True)
        return scored[:top_k]

    def delete(self, memory_id: str):
        """删除记忆"""
        if self._collection:
            self._collection.delete(ids=[memory_id])

    def search_by_content_sync(
        self,
        query_text: str,
        user_id: str = "default",
        top_k: int = 5,
    ) -> list[ScoredMemory]:
        """同步版文本搜索（用于 build_prompt）"""
        return self._do_search_by_content(query_text, user_id, top_k)

    def _do_search_by_content(
        self,
        query_text: str,
        user_id: str = "default",
        top_k: int = 5,
    ) -> list[ScoredMemory]:
        """内部: 通过文本搜索"""
        if not self._collection:
            return []

        where_filter = {"$and": [{"user_id": user_id}, {"status": "active"}]}

        try:
            results = self._collection.query(
                query_texts=[query_text],
                n_results=min(top_k * 4, 20),
                where=where_filter,
                include=["documents", "metadatas", "distances"],
            )
        except Exception as e:
            logger.error(f"长期记忆文本搜索失败: {e}")
            return []

        if not results["documents"] or not results["documents"][0]:
            return []

        now = time.time()
        scored = []

        for i, doc in enumerate(results["documents"][0]):
            meta = results["metadatas"][0][i]
            distance = results["distances"][0][i]

            semantic_score = max(0, 1 - distance / 2.0)
            created_at = meta.get("created_at", now)
            age_days = max(0, (now - created_at) / 86400)
            half_life = meta.get("half_life_days", 90)
            time_decay = 0.5 ** (age_days / half_life)
            importance = meta.get("importance", 0.5)
            importance_weight = 1 + importance * 0.5
            access_count = meta.get("access_count", 0)
            last_accessed = meta.get("last_accessed", created_at)
            time_since_access = max(0, (now - last_accessed) / 86400)
            recency_boost = 0.5 ** (time_since_access / 30)
            access_decay = recency_boost * (1 + min(access_count, 10) * 0.05)

            final_score = (
                semantic_score * 0.6
                + time_decay * 0.2
                + importance_weight * 0.1
                + access_decay * 0.1
            )

            scored.append(ScoredMemory(
                memory_id=meta.get("memory_id", ""),
                content=doc,
                memory_type=meta.get("memory_type", "fact"),
                category=meta.get("category", "user_profile"),
                importance=importance,
                final_score=final_score,
                semantic_score=semantic_score,
                time_decay=time_decay,
                access_decay=access_decay,
            ))

        scored.sort(key=lambda x: x.final_score, reverse=True)
        return scored[:top_k]

    def get_all(
        self,
        user_id: str = "default",
        limit: int = 50,
        offset: int = 0,
    ) -> list[dict]:
        """获取用户的所有记忆（用于管理界面）"""
        if not self._collection:
            return []
        try:
            where_filter = {"user_id": user_id}
            total = self._collection.count()
            results = self._collection.get(
                where=where_filter,
                limit=limit,
                offset=offset,
                include=["documents", "metadatas"],
            )
            if not results or not results.get("ids"):
                return []
            items = []
            for i, doc_id in enumerate(results["ids"]):
                doc = results["documents"][i] if results.get("documents") else ""
                meta = results["metadatas"][i] if results.get("metadatas") else {}
                items.append({
                    "id": doc_id,
                    "content": doc,
                    "memory_type": meta.get("memory_type", ""),
                    "category": meta.get("category", ""),
                    "importance": meta.get("importance", 0),
                    "created_at": meta.get("created_at", 0),
                    "access_count": meta.get("access_count", 0),
                })
            return items
        except Exception as e:
            logger.error(f"获取记忆列表失败: {e}")
            return []

    def get_stats(self) -> dict:
        """获取统计信息"""
        if not self._collection:
            return {"total": 0, "collection": self._collection_name}
        try:
            return {
                "total": self._collection.count(),
                "collection": self._collection_name,
            }
        except Exception:
            return {"total": 0, "collection": self._collection_name}
