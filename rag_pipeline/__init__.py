"""
RAG 管线包 — 万象积木 子系统

提供文档解析、智能切片、向量化索引、混合检索、生成溯源、增量更新全流程能力。

典型用法::

    from rag_pipeline import DocumentParser, SmartChunker, VectorIndexer, HybridRetriever, RAGGenerator

    parser = DocumentParser()
    chunker = SmartChunker()
    indexer = VectorIndexer(persist_path="./data/chroma")
    retriever = HybridRetriever(indexer.collection, reranker)
    generator = RAGGenerator(model_router)
"""

from .models import Document, Chunk, RetrievalResult, UpdateResult
from .parser import DocumentParser
from .chunker import SmartChunker
from .indexer import VectorIndexer
from .retriever import HybridRetriever
from .generator import RAGGenerator
from .incremental import IncrementalUpdater

__all__ = [
    "Document",
    "Chunk",
    "RetrievalResult",
    "UpdateResult",
    "DocumentParser",
    "SmartChunker",
    "VectorIndexer",
    "HybridRetriever",
    "RAGGenerator",
    "IncrementalUpdater",
]

__version__ = "1.0.0"
