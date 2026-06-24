"""
四层记忆系统 — 数据模型
"""

from __future__ import annotations

import uuid
import time
import json
from dataclasses import dataclass, field, asdict
from enum import Enum
from typing import Optional


class MemoryType(str, Enum):
    PREFERENCE = "preference"
    FACT = "fact"
    EVENT = "event"
    PERSON = "person"
    SKILL_HINT = "skill_hint"
    CHAT_LOG = "chat_log"


class MemoryStatus(str, Enum):
    ACTIVE = "active"
    PENDING_REVIEW = "pending_review"
    ARCHIVED = "archived"
    CONFLICTED = "conflicted"
    WARM = "warm"


class SourceType(str, Enum):
    AUTO_EXTRACT = "auto_extract"
    USER_STATED = "user_stated"
    SYSTEM_INFERRED = "system_inferred"


# 半衰期映射（天）
HALF_LIFE_MAP = {
    MemoryType.PREFERENCE: 365,
    MemoryType.FACT: 90,
    MemoryType.PERSON: 180,
    MemoryType.EVENT: 30,
    MemoryType.SKILL_HINT: 90,
    MemoryType.CHAT_LOG: 14,
}


@dataclass
class MemoryEntry:
    """长期记忆条目"""
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    user_id: str = "default"
    session_id: str = ""
    memory_type: str = "fact"
    category: str = "user_profile"
    content: str = ""
    importance: float = 0.5
    confidence: float = 1.0
    status: str = "active"
    conflict_with: Optional[str] = None
    source_type: str = "auto_extract"
    source_msg_ids: list = field(default_factory=list)
    access_count: int = 0
    last_accessed: Optional[float] = None
    half_life_days: int = 90
    embedding_id: Optional[str] = None
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    archived_at: Optional[float] = None

    def to_dict(self) -> dict:
        d = asdict(self)
        return d

    @classmethod
    def from_dict(cls, d: dict) -> "MemoryEntry":
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})

    def to_chroma_metadata(self) -> dict:
        """Chroma 元数据（不含 content）"""
        return {
            "memory_id": self.id,
            "user_id": self.user_id,
            "memory_type": self.memory_type,
            "category": self.category,
            "importance": self.importance,
            "status": self.status,
            "created_at": self.created_at,
            "half_life_days": self.half_life_days,
            "access_count": self.access_count,
            "last_accessed": self.last_accessed if self.last_accessed is not None else self.created_at,
        }


@dataclass
class SessionSummary:
    """短期记忆 — 会话摘要"""
    session_id: str
    user_id: str = "default"
    summary: str = ""
    key_messages: list = field(default_factory=list)
    turn_count: int = 0
    topics: list = field(default_factory=list)
    token_count: int = 0
    status: str = "active"
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class ScoredMemory:
    """检索评分结果"""
    memory_id: str
    content: str
    memory_type: str
    category: str
    importance: float
    final_score: float
    semantic_score: float = 0.0
    time_decay: float = 1.0
    access_decay: float = 1.0

    def to_dict(self) -> dict:
        return asdict(self)
