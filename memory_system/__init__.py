"""
四层记忆系统 — 包入口

L1 工作记忆: 内存中的当前对话上下文
L2 短期记忆: 会话摘要 + 关键消息（JSON 文件）
L3 长期记忆: 向量检索 + 时间衰减（ChromaDB）
L4 程序记忆: Skill/快捷指令固化（JSON 文件）
"""

from .l1_working import WorkingMemory, WorkingMemoryManager
from .l2_short_term import ShortTermMemory
from .l3_long_term import LongTermMemory
from .l4_procedural import ProceduralMemory, ProceduralSkill
from .extractor import MemoryExtractor, CompressionEngine
from .manager import MemorySystem
from .models import (
    MemoryEntry, ScoredMemory, SessionSummary,
    MemoryType, MemoryStatus, SourceType, HALF_LIFE_MAP,
)

__all__ = [
    # L1
    "WorkingMemory", "WorkingMemoryManager",
    # L2
    "ShortTermMemory",
    # L3
    "LongTermMemory",
    # L4
    "ProceduralMemory", "ProceduralSkill",
    # 提取器
    "MemoryExtractor", "CompressionEngine",
    # 统一管理器
    "MemorySystem",
    # 数据模型
    "MemoryEntry", "ScoredMemory", "SessionSummary",
    "MemoryType", "MemoryStatus", "SourceType", "HALF_LIFE_MAP",
]
