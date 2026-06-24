"""
向量化 + 索引层（ChromaDB 本地化版）

负责将文本切片转化为向量并索引入 ChromaDB 向量库。
使用 ChromaDB 默认的 Sentence Transformers Embedding 模型（本地运行，无需 API Key）。

依赖：
- chromadb
"""

from __future__ import annotations

import logging
import os
from typing import Any, Optional

# 设置 HuggingFace 镜像（国内加速）
os.environ.setdefault("HF_ENDPOINT", "https://hf-mirror.com")

from .models import Chunk

logger = logging.getLogger(__name__)


class VectorIndexer:
    """向量化 + 索引入库（ChromaDB 嵌入式）

    功能：
    1. 使用 ChromaDB 内置 Embedding（Sentence Transformers all-MiniLM-L6-v2）
    2. ChromaDB 嵌入式存储（本地 SQLite + DuckDB，无需外部服务）
    3. 支持 Payload 元数据过滤

    Usage::

        indexer = VectorIndexer(persist_path="./data/chroma")
        await indexer.index_chunks(chunks)
    """

    # 默认配置
    COLLECTION_NAME: str = "wanxiang_rag"

    def __init__(
        self,
        persist_path: str = "./data/chroma",
        collection_name: Optional[str] = None,
        embedding_function: Any = None,
    ) -> None:
        """初始化 ChromaDB 索引器

        Args:
            persist_path: ChromaDB 持久化存储路径
            collection_name: Collection 名称
            embedding_function: 自定义 Embedding 函数（默认用 ChromaDB 内置 Sentence Transformers）
        """
        import chromadb

        self.persist_path = persist_path
        self.collection_name = collection_name or self.COLLECTION_NAME

        # 创建持久化客户端
        self.client = chromadb.PersistentClient(path=persist_path)

        # Embedding 函数
        if embedding_function is None:
            try:
                from chromadb.utils.embedding_functions import (
                    SentenceTransformerEmbeddingFunction,
                )
                self._ef = SentenceTransformerEmbeddingFunction(
                    model_name="all-MiniLM-L6-v2"
                )
                logger.info("使用 Sentence Transformers all-MiniLM-L6-v2 Embedding")
            except Exception as e:
                logger.warning(f"Sentence Transformers 加载失败: {e}，使用 ChromaDB 默认 Embedding")
                self._ef = None
        else:
            self._ef = embedding_function

        # 获取或创建 Collection
        if self._ef:
            self.collection = self.client.get_or_create_collection(
                name=self.collection_name,
                embedding_function=self._ef,
                metadata={"hnsw:space": "cosine"},
            )
        else:
            self.collection = self.client.get_or_create_collection(
                name=self.collection_name,
                metadata={"hnsw:space": "cosine"},
            )

        logger.info(f"ChromaDB 索引器初始化完成: {self.persist_path}")

    # ──────────────────────────── 批量索引 ────────────────────────────

    async def index_chunks(self, chunks: list[Chunk], batch_size: int = 100) -> None:
        """批量向量化 + 索引入库

        Args:
            chunks: 待索引的切片列表
            batch_size: 每批大小（ChromaDB upsert 上限）
        """
        if not chunks:
            return

        total: int = len(chunks)
        logger.info(f"开始索引 {total} 个切片到 ChromaDB")

        for i in range(0, total, batch_size):
            batch: list[Chunk] = chunks[i:i + batch_size]

            ids: list[str] = [c.chunk_id for c in batch]
            documents: list[str] = [c.content for c in batch]
            metadatas: list[dict] = [
                {
                    "chunk_id": c.chunk_id,
                    "tenant_id": c.tenant_id,
                    "doc_id": c.doc_id,
                    "chunk_type": c.chunk_type,
                    "page": c.page if c.page is not None else -1,
                    "section": c.section or "",
                    "token_count": c.token_count,
                    "content_preview": c.content[:200],
                    "parent_chunk_id": c.parent_chunk_id or "",
                    "source_name": c.metadata.get("source_name", ""),
                }
                for c in batch
            ]

            # ChromaDB upsert（自动向量化）
            self.collection.upsert(
                ids=ids,
                documents=documents,
                metadatas=metadatas,
            )

            logger.info(f"已索引 {min(i + batch_size, total)}/{total} 切片")

        logger.info(f"索引完成: {total} 个切片 → ChromaDB")

    # ──────────────────────────── 查询向量化 ────────────────────────────

    def embed_query(self, query: str) -> list[float]:
        """单条查询向量化

        Args:
            query: 查询文本

        Returns:
            查询向量
        """
        if self._ef:
            embeddings = self._ef([query])
            return embeddings[0]
        # ChromaDB query 时会自动 embedding，不需要手动调
        return []

    # ──────────────────────────── 删除索引 ────────────────────────────

    def delete_by_doc(self, doc_id: str) -> None:
        """删除指定文档的所有切片索引

        Args:
            doc_id: 文档 ID
        """
        try:
            # ChromaDB 按 metadata 过滤删除
            self.collection.delete(where={"doc_id": doc_id})
            logger.info(f"已从 ChromaDB 删除文档 {doc_id} 的所有切片")
        except Exception as e:
            logger.error(f"ChromaDB 删除失败: {e}")

    # ──────────────────────────── 统计信息 ────────────────────────────

    def count(self) -> int:
        """返回 Collection 中的切片总数"""
        try:
            return self.collection.count()
        except Exception:
            return 0

    def get_stats(self) -> dict[str, Any]:
        """返回索引统计信息"""
        try:
            return {
                "collection": self.collection_name,
                "total_chunks": self.collection.count(),
                "persist_path": self.persist_path,
            }
        except Exception as e:
            return {"error": str(e)}
