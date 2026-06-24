"""
数据模型定义

定义 RAG 管线中使用的核心数据结构：Document、Chunk、RetrievalResult、UpdateResult。
使用 dataclass 进行声明，类型标注齐全。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional
import uuid as _uuid
import hashlib as _hashlib


# ──────────────────────────── 工具函数 ────────────────────────────

def uuid() -> str:
    """生成 UUID4 字符串"""
    return str(_uuid.uuid4())


def now_iso() -> str:
    """当前 UTC 时间的 ISO-8601 字符串"""
    return datetime.now(timezone.utc).isoformat()


def compute_hash(data: bytes | str) -> str:
    """计算 MD5 哈希，用于增量更新判断"""
    if isinstance(data, str):
        data = data.encode("utf-8")
    return _hashlib.md5(data).hexdigest()


# ──────────────────────────── Document ────────────────────────────

@dataclass
class Document:
    """原始文档

    代表一个经过解析后的完整文档，包含纯文本内容和元数据。

    Attributes:
        doc_id: 文档唯一 ID
        tenant_id: 租户 ID（多租户隔离）
        source_name: 文件名或 URL
        source_type: 文件格式 ("pdf" | "docx" | "md" | "html" | "txt" | "csv" | "xlsx" | "pptx")
        content: 解析后的纯文本
        metadata: 额外元数据 (作者、日期、页数等)
        created_at: 创建时间 (ISO-8601)
        updated_at: 更新时间 (ISO-8601)
        file_hash: 文件 MD5 哈希，用于增量更新
    """

    doc_id: str = field(default_factory=uuid)
    tenant_id: str = ""
    source_name: str = ""
    source_type: str = ""
    content: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: str = field(default_factory=now_iso)
    updated_at: str = field(default_factory=now_iso)
    file_hash: str = ""


# ──────────────────────────── Chunk ────────────────────────────

@dataclass
class Chunk:
    """文档切片

    文档被切分为多个 Chunk，每个 Chunk 包含一段文本及其元数据。
    支持父子块层级：检索命中子块时，可返回父块提供更完整的上下文。

    Attributes:
        chunk_id: 切片唯一 ID
        doc_id: 所属文档 ID
        tenant_id: 租户 ID
        content: 切片文本内容
        chunk_type: 切片类型 ("text" | "table" | "code" | "heading" | "parent")
        parent_chunk_id: 父块 ID（父子块层级）
        children_ids: 子块 ID 列表
        page: 来源页码
        section: 来源章节标题
        token_count: token 数量估算
        embedding: 向量（1536 维）
        metadata: 额外元数据
        score: 检索得分
    """

    chunk_id: str = field(default_factory=uuid)
    doc_id: str = ""
    tenant_id: str = ""
    content: str = ""
    chunk_type: str = "text"
    parent_chunk_id: Optional[str] = None
    children_ids: list[str] = field(default_factory=list)
    page: Optional[int] = None
    section: Optional[str] = None
    token_count: int = 0
    embedding: list[float] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
    score: float = 0.0


# ──────────────────────────── RetrievalResult ────────────────────────────

@dataclass
class RetrievalResult:
    """检索结果

    封装一次检索操作返回的全部信息。

    Attributes:
        chunks: 检索到的切片列表（按得分排序）
        query: 原始查询
        retrieval_type: 检索类型 ("hybrid" | "vector" | "keyword" | "hybrid_reranked")
        total_found: 去重后命中的总切片数
        reranked: 是否经过 Rerank
    """

    chunks: list[Chunk] = field(default_factory=list)
    query: str = ""
    retrieval_type: str = "hybrid"
    total_found: int = 0
    reranked: bool = False


# ──────────────────────────── UpdateResult ────────────────────────────

@dataclass
class UpdateResult:
    """增量更新结果

    Attributes:
        status: 更新状态 ("unchanged" | "updated" | "created")
        updated_chunks: 更新的切片数
        deleted_chunks: 删除的切片数
        inserted_chunks: 新增的切片数
        doc_id: 文档 ID
        message: 附加消息
    """

    status: str = "unchanged"
    updated_chunks: int = 0
    deleted_chunks: int = 0
    inserted_chunks: int = 0
    doc_id: str = ""
    message: str = ""
