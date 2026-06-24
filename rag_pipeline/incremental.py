"""
增量更新机制

文档变更检测 + 智能重索引。
不全量重建，仅处理变更部分，降低索引开销。

策略：
1. 文件哈希比对：未变更则跳过
2. 新文档：全量索引
3. 已变更文档：差异检测 → 只重索引变更的切片
4. 使用 LLM 辅助智能对比（可选）
"""

from __future__ import annotations

import asyncio
import logging
import os
from typing import Any, Optional

from .models import Chunk, Document, UpdateResult, compute_hash, now_iso, uuid
from .parser import DocumentParser
from .chunker import SmartChunker
from .indexer import VectorIndexer

logger = logging.getLogger(__name__)


class IncrementalUpdater:
    """增量更新器

    检测文档变更，只重索引变更部分。

    Usage::

        updater = IncrementalUpdater(
            parser=DocumentParser(),
            chunker=SmartChunker(),
            indexer=indexer,
            db=db_adapter,
        )
        result = await updater.update_document("/path/to/updated.pdf", tenant_id="t001")
    """

    def __init__(
        self,
        parser: DocumentParser,
        chunker: SmartChunker,
        indexer: VectorIndexer,
        db: Any = None,
    ) -> None:
        """初始化增量更新器

        Args:
            parser: 文档解析器
            chunker: 智能切片器
            indexer: 向量索引器
            db: 数据库适配器（需实现 get_document_by_path / update_document / save_document 方法）
        """
        self.parser = parser
        self.chunker = chunker
        self.indexer = indexer
        self.db = db

    # ──────────────────────────── 更新入口 ────────────────────────────

    async def update_document(
        self,
        file_path: str,
        tenant_id: str,
    ) -> UpdateResult:
        """增量更新文档

        流程：
        1. 计算新文件哈希
        2. 查找旧版本
        3. 哈希相同 → 跳过
        4. 新文档 → 全量索引
        5. 已变更 → 差异检测 → 部分重索引

        Args:
            file_path: 文件路径
            tenant_id: 租户 ID

        Returns:
            UpdateResult 更新结果
        """
        # 1. 读取并计算哈希
        if not os.path.exists(file_path):
            return UpdateResult(
                status="error",
                message=f"文件不存在: {file_path}",
            )

        raw: bytes = await self._read_file(file_path)
        new_hash: str = compute_hash(raw)

        # 2. 查找旧版本
        old_doc: Optional[Document] = await self._get_document_by_path(file_path, tenant_id)

        # 3. 新文档 → 全量索引
        if old_doc is None:
            logger.info(f"新文档，执行全量索引: {file_path}")
            return await self._full_index(file_path, tenant_id)

        # 4. 哈希相同 → 跳过
        if old_doc.file_hash == new_hash:
            logger.info(f"文档未变更，跳过: {file_path}")
            return UpdateResult(
                status="unchanged",
                doc_id=old_doc.doc_id,
                message="文件哈希未变化",
            )

        # 5. 已变更 → 差异检测
        logger.info(f"文档已变更，执行增量更新: {file_path}")
        return await self._incremental_update(file_path, tenant_id, old_doc, new_hash)

    # ──────────────────────────── 全量索引 ────────────────────────────

    async def _full_index(self, file_path: str, tenant_id: str) -> UpdateResult:
        """全量索引新文档

        Args:
            file_path: 文件路径
            tenant_id: 租户 ID

        Returns:
            UpdateResult
        """
        try:
            # 解析
            doc: Document = await self.parser.parse(file_path, tenant_id)

            # 切片
            chunks: list[Chunk] = await self.chunker.chunk(doc)

            # 索引
            await self.indexer.index_chunks(chunks)

            # 保存到 DB
            await self._save_document(doc)

            logger.info(f"全量索引完成: {file_path} → {len(chunks)} 切片")

            return UpdateResult(
                status="created",
                inserted_chunks=len(chunks),
                doc_id=doc.doc_id,
                message=f"新文档已索引，共 {len(chunks)} 个切片",
            )
        except Exception as e:
            logger.error(f"全量索引失败: {e}")
            return UpdateResult(
                status="error",
                message=f"全量索引失败: {e}",
            )

    # ──────────────────────────── 增量更新 ────────────────────────────

    async def _incremental_update(
        self,
        file_path: str,
        tenant_id: str,
        old_doc: Document,
        new_hash: str,
    ) -> UpdateResult:
        """增量更新已变更文档

        策略：
        1. 解析新文档
        2. 对比新旧内容，找出变更段落
        3. 删除旧切片，索引新切片

        Args:
            file_path: 文件路径
            tenant_id: 租户 ID
            old_doc: 旧版本文档
            new_hash: 新文件哈希

        Returns:
            UpdateResult
        """
        try:
            # 1. 解析新文档
            new_doc: Document = await self.parser.parse(file_path, tenant_id)
            new_doc.doc_id = old_doc.doc_id  # 保持文档 ID 不变

            # 2. 切片
            new_chunks: list[Chunk] = await self.chunker.chunk(new_doc)

            # 3. 获取旧切片（从 DB 或 ChromaDB）
            old_chunks: list[Chunk] = await self._get_chunks_by_doc(old_doc.doc_id)

            # 4. 差异检测
            diff: dict[str, Any] = self._smart_diff(old_doc.content, new_doc.content, old_chunks, new_chunks)

            # 5. 执行变更
            deleted_count: int = 0
            updated_count: int = 0
            inserted_count: int = 0

            # 删除旧切片
            if diff["to_delete"]:
                for chunk_id in diff["to_delete"]:
                    await self._delete_chunk(chunk_id)
                deleted_count = len(diff["to_delete"])

            # 索引新切片
            if diff["to_index"]:
                await self.indexer.index_chunks(diff["to_index"])
                inserted_count = len(diff["to_index"])

            # 6. 更新文档元数据
            new_doc.file_hash = new_hash
            new_doc.updated_at = now_iso()
            await self._update_document(old_doc.doc_id, {
                "content": new_doc.content,
                "file_hash": new_hash,
                "updated_at": now_iso(),
                "metadata": new_doc.metadata,
            })

            logger.info(
                f"增量更新完成: 删除 {deleted_count}, 新增 {inserted_count} 切片"
            )

            return UpdateResult(
                status="updated",
                deleted_chunks=deleted_count,
                inserted_chunks=inserted_count,
                updated_chunks=updated_count,
                doc_id=old_doc.doc_id,
                message=f"增量更新: 删除 {deleted_count}, 新增 {inserted_count} 切片",
            )
        except Exception as e:
            logger.error(f"增量更新失败: {e}")
            return UpdateResult(
                status="error",
                doc_id=old_doc.doc_id,
                message=f"增量更新失败: {e}",
            )

    # ──────────────────────────── 差异检测 ────────────────────────────

    @staticmethod
    def _smart_diff(
        old_content: str,
        new_content: str,
        old_chunks: list[Chunk],
        new_chunks: list[Chunk],
    ) -> dict[str, Any]:
        """智能差异检测

        对比新旧内容和切片，输出需要删除/索引的操作列表。

        策略：
        - 内容完全不同 → 删除所有旧切片，索引所有新切片
        - 内容部分变更 → 按段落比对，只处理变更部分

        Args:
            old_content: 旧文档内容
            new_content: 新文档内容
            old_chunks: 旧切片列表
            new_chunks: 新切片列表

        Returns:
            操作字典 {"to_delete": [...], "to_index": [...]}
        """
        old_sections: list[str] = [s.strip() for s in old_content.split("\n\n") if s.strip()]
        new_sections: list[str] = [s.strip() for s in new_content.split("\n\n") if s.strip()]

        # 快速判断：段落数和内容差异
        if old_sections == new_sections:
            return {"to_delete": [], "to_index": []}

        # 使用集合比对段落
        old_set: set[str] = set(old_sections)
        new_set: set[str] = set(new_sections)

        # 新增的段落
        added_sections: set[str] = new_set - old_set
        # 删除的段落
        removed_sections: set[str] = old_set - new_set

        # 判断哪些旧切片需要删除（内容在已删除段落中的）
        to_delete: list[str] = []
        for chunk in old_chunks:
            # 如果切片内容的主要部分在已删除段落中
            chunk_in_removed = any(
                removed_section in chunk.content or chunk.content in removed_section
                for removed_section in removed_sections
            )
            if chunk_in_removed:
                to_delete.append(chunk.chunk_id)

        # 判断哪些新切片需要索引（内容在新增段落中的，或内容有变更的）
        to_index: list[Chunk] = []
        old_chunk_contents: set[str] = {c.content.strip() for c in old_chunks}

        for chunk in new_chunks:
            # 内容完全相同 → 跳过
            if chunk.content.strip() in old_chunk_contents:
                continue

            # 内容在新增段落中 → 需要索引
            chunk_in_added = any(
                added_section in chunk.content or chunk.content in added_section
                for added_section in added_sections
            )

            # 内容有变更 → 需要索引
            if chunk_in_added or chunk.content.strip() not in old_chunk_contents:
                to_index.append(chunk)

        logger.info(
            f"差异检测: 删除 {len(to_delete)} 切片, "
            f"新增/更新 {len(to_index)} 切片"
        )

        return {
            "to_delete": to_delete,
            "to_index": to_index,
        }

    # ──────────────────────────── DB 适配 ────────────────────────────

    async def _get_document_by_path(self, file_path: str, tenant_id: str) -> Optional[Document]:
        """从 DB 查询文档

        Args:
            file_path: 文件路径
            tenant_id: 租户 ID

        Returns:
            Document 或 None
        """
        if self.db is None:
            return None

        try:
            if hasattr(self.db, "get_document_by_path"):
                return await self.db.get_document_by_path(file_path, tenant_id)
        except Exception as e:
            logger.warning(f"查询文档失败: {e}")
        return None

    async def _get_chunks_by_doc(self, doc_id: str) -> list[Chunk]:
        """从 DB 或 ChromaDB 获取文档的所有切片

        Args:
            doc_id: 文档 ID

        Returns:
            切片列表
        """
        if self.db and hasattr(self.db, "get_chunks_by_doc"):
            try:
                return await self.db.get_chunks_by_doc(doc_id)
            except Exception as e:
                logger.warning(f"查询切片失败: {e}")

        # 降级：从 ChromaDB 查询
        try:
            results = self.indexer.collection.get(
                where={"doc_id": doc_id},
                limit=10000,
                include=["metadatas", "documents"],
            )
            chunks: list[Chunk] = []
            if results and results.get("ids"):
                for i, chunk_id in enumerate(results["ids"]):
                    payload: dict = (results.get("metadatas") or [{}])[i] if i < len(results.get("metadatas", [])) else {}
                    content: str = (results.get("documents") or [""])[i] if i < len(results.get("documents", [])) else ""
                    chunks.append(
                        Chunk(
                            chunk_id=payload.get("chunk_id", chunk_id),
                            doc_id=payload.get("doc_id", doc_id),
                            tenant_id=payload.get("tenant_id", ""),
                            content=content,
                            chunk_type=payload.get("chunk_type", "text"),
                            page=payload.get("page"),
                            section=payload.get("section"),
                            token_count=payload.get("token_count", 0),
                            metadata=payload.get("metadata", {}),
                        )
                    )
            return chunks
        except Exception as e:
            logger.warning(f"从 ChromaDB 查询切片失败: {e}")
            return []

    async def _save_document(self, doc: Document) -> None:
        """保存文档到 DB

        Args:
            doc: 文档对象
        """
        if self.db is None:
            return
        try:
            if hasattr(self.db, "save_document"):
                await self.db.save_document(doc)
        except Exception as e:
            logger.warning(f"保存文档失败: {e}")

    async def _update_document(self, doc_id: str, updates: dict[str, Any]) -> None:
        """更新文档元数据

        Args:
            doc_id: 文档 ID
            updates: 更新字段
        """
        if self.db is None:
            return
        try:
            if hasattr(self.db, "update_document"):
                await self.db.update_document(doc_id, updates)
        except Exception as e:
            logger.warning(f"更新文档失败: {e}")

    async def _delete_chunk(self, chunk_id: str) -> None:
        """删除单个切片

        Args:
            chunk_id: 切片 ID
        """
        try:
            self.indexer.collection.delete(
                where={"chunk_id": chunk_id},
            )
        except Exception as e:
            logger.warning(f"删除切片 {chunk_id} 失败: {e}")

    # ──────────────────────────── 文件读取 ────────────────────────────

    @staticmethod
    async def _read_file(file_path: str) -> bytes:
        """异步读取文件"""
        def _read() -> bytes:
            with open(file_path, "rb") as f:
                return f.read()
        return await asyncio.to_thread(_read)

    # ──────────────────────────── 批量更新 ────────────────────────────

    async def batch_update(
        self,
        file_paths: list[str],
        tenant_id: str,
        concurrency: int = 3,
    ) -> list[UpdateResult]:
        """批量更新文档

        并发更新多个文档，控制并发数避免资源过载。

        Args:
            file_paths: 文件路径列表
            tenant_id: 租户 ID
            concurrency: 最大并发数

        Returns:
            更新结果列表
        """
        semaphore: asyncio.Semaphore = asyncio.Semaphore(concurrency)
        results: list[UpdateResult] = []

        async def _update_one(path: str) -> UpdateResult:
            async with semaphore:
                return await self.update_document(path, tenant_id)

        tasks: list[asyncio.Task] = [
            asyncio.create_task(_update_one(path)) for path in file_paths
        ]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        # 处理异常
        final_results: list[UpdateResult] = []
        for i, result in enumerate(results):
            if isinstance(result, Exception):
                logger.error(f"批量更新 {file_paths[i]} 失败: {result}")
                final_results.append(UpdateResult(
                    status="error",
                    message=f"更新失败: {result}",
                ))
            else:
                final_results.append(result)

        return final_results
