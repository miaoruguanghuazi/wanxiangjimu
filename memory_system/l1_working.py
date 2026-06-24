"""
L1 工作记忆 — 内存中的当前对话上下文

职责:
- 维护当前会话的 messages[] 列表
- Token 计数与溢出检测
- 溢出时触发 L2 压缩
"""

from __future__ import annotations

import time
import logging
from dataclasses import dataclass, field
from typing import Optional

logger = logging.getLogger(__name__)


@dataclass
class WorkingMemory:
    """L1 工作记忆 — 单会话"""
    session_id: str
    user_id: str = "default"
    messages: list[dict] = field(default_factory=list)
    max_turns: int = 20          # 保留的最大轮数
    max_tokens: int = 120000     # 上下文窗口预算
    turn_count: int = 0

    def add_message(self, role: str, content: str, metadata: dict = None):
        msg = {"role": role, "content": content}
        if metadata:
            msg["metadata"] = metadata
        self.messages.append(msg)
        if role == "user":
            self.turn_count += 1

    def get_messages(self) -> list[dict]:
        """获取当前工作记忆中的消息列表"""
        return self.messages

    def get_recent(self, n: int = 10) -> list[dict]:
        """获取最近 n 条消息"""
        return self.messages[-n:]

    def estimate_tokens(self) -> int:
        """粗略估算 token 数：中文字符按 1 字符≈2 token，英文按 1 word≈1.3 token"""
        import re
        total_tokens = 0
        for m in self.messages:
            content = m.get("content", "")
            # 提取中文字符
            chinese_chars = re.findall(r'[\u4e00-\u9fff]', content)
            # 移除中文后剩余部分按英文单词计
            non_chinese = re.sub(r'[\u4e00-\u9fff]', ' ', content)
            english_words = non_chinese.split()
            total_tokens += len(chinese_chars) * 2 + len(english_words) * 1.3
        return int(total_tokens)

    def should_compress(self) -> bool:
        """是否需要触发压缩"""
        if self.estimate_tokens() > self.max_tokens * 0.8:
            return True
        if len(self.messages) > self.max_turns * 2:
            return True
        return False

    def get_overflow_messages(self) -> list[dict]:
        """获取需要压缩的旧消息（保留最近 N 轮）"""
        keep_count = min(self.max_turns * 2, len(self.messages))
        if len(self.messages) > keep_count:
            return self.messages[:-keep_count]
        return []

    def compress(self, removed_count: int):
        """压缩：移除前 removed_count 条消息"""
        self.messages = self.messages[removed_count:]

    def clear(self):
        self.messages.clear()
        self.turn_count = 0


class WorkingMemoryManager:
    """L1 工作记忆管理器 — 管理多个会话"""

    def __init__(self):
        self._sessions: dict[str, WorkingMemory] = {}

    def get(self, session_id: str, user_id: str = "default") -> WorkingMemory:
        if session_id not in self._sessions:
            self._sessions[session_id] = WorkingMemory(
                session_id=session_id, user_id=user_id
            )
        return self._sessions[session_id]

    def add_message(self, session_id: str, role: str, content: str, user_id: str = "default"):
        wm = self.get(session_id, user_id)
        wm.add_message(role, content)
        return wm

    def get_messages(self, session_id: str) -> list[dict]:
        wm = self.get(session_id)
        return wm.get_messages()

    def clear(self, session_id: str):
        if session_id in self._sessions:
            self._sessions[session_id].clear()

    def all_sessions(self) -> dict[str, WorkingMemory]:
        return self._sessions

    def session_count(self) -> int:
        return len(self._sessions)
