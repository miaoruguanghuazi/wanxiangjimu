"""
L2 短期记忆 — 会话摘要 + 关键消息

职责:
- 当 L1 溢出时，LLM 压缩旧消息为摘要
- 存储关键消息（高重要性标记）
- 内存 + JSON 文件持久化（无需 Redis）
"""

from __future__ import annotations

import json
import time
import os
import logging
from typing import Optional
from .models import SessionSummary

logger = logging.getLogger(__name__)


class ShortTermMemory:
    """L2 短期记忆管理器"""

    def __init__(self, persist_path: str = "./data/short_term"):
        self.persist_path = persist_path
        self._summaries: dict[str, SessionSummary] = {}
        os.makedirs(persist_path, exist_ok=True)
        self._load()

    def _file_path(self, session_id: str) -> str:
        safe_id = session_id.replace("/", "_").replace("\\", "_")
        return os.path.join(self.persist_path, f"{safe_id}.json")

    def _load(self):
        """从磁盘加载所有摘要"""
        for fname in os.listdir(self.persist_path):
            if not fname.endswith(".json"):
                continue
            try:
                with open(os.path.join(self.persist_path, fname), "r", encoding="utf-8") as f:
                    data = json.load(f)
                summary = SessionSummary(**data)
                self._summaries[summary.session_id] = summary
            except Exception as e:
                logger.warning(f"加载短期记忆失败 {fname}: {e}")

    def _save(self, summary: SessionSummary):
        with open(self._file_path(summary.session_id), "w", encoding="utf-8") as f:
            json.dump(summary.to_dict(), f, ensure_ascii=False, indent=2)

    def get(self, session_id: str) -> Optional[SessionSummary]:
        return self._summaries.get(session_id)

    def update_summary(self, session_id: str, summary: str, user_id: str = "default"):
        """更新会话摘要"""
        # 限制摘要长度为 2000 字符
        MAX_SUMMARY_CHARS = 2000
        if len(summary) > MAX_SUMMARY_CHARS:
            summary = summary[:MAX_SUMMARY_CHARS]
            logger.info(f"会话 {session_id} 摘要截断至 {MAX_SUMMARY_CHARS} 字符")
        if session_id not in self._summaries:
            self._summaries[session_id] = SessionSummary(
                session_id=session_id, user_id=user_id
            )
        s = self._summaries[session_id]
        s.summary = summary
        s.updated_at = time.time()
        self._save(s)

    def add_key_message(self, session_id: str, message: dict, user_id: str = "default"):
        """添加关键消息"""
        MAX_KEY_MESSAGES = 20
        if session_id not in self._summaries:
            self._summaries[session_id] = SessionSummary(
                session_id=session_id, user_id=user_id
            )
        s = self._summaries[session_id]
        s.key_messages.append({
            "content": message.get("content", ""),
            "role": message.get("role", "user"),
            "timestamp": time.time(),
        })
        # 限制 key_messages 数量为 20 条
        if len(s.key_messages) > MAX_KEY_MESSAGES:
            s.key_messages = s.key_messages[-MAX_KEY_MESSAGES:]
        s.updated_at = time.time()
        self._save(s)

    def increment_turn(self, session_id: str, user_id: str = "default"):
        if session_id not in self._summaries:
            self._summaries[session_id] = SessionSummary(
                session_id=session_id, user_id=user_id
            )
        self._summaries[session_id].turn_count += 1
        self._save(self._summaries[session_id])

    def get_summary_text(self, session_id: str) -> str:
        """获取摘要文本（用于注入 prompt）"""
        s = self._summaries.get(session_id)
        if not s or not s.summary:
            return ""
        parts = [f"[近期对话摘要] {s.summary}"]
        if s.key_messages:
            key_texts = [m["content"][:100] for m in s.key_messages[-3:]]
            parts.append(f"[重要消息] {'; '.join(key_texts)}")
        return "\n".join(parts)

    def close_session(self, session_id: str):
        """关闭会话"""
        if session_id in self._summaries:
            self._summaries[session_id].status = "closed"
            self._save(self._summaries[session_id])

    def all_summaries(self) -> dict[str, SessionSummary]:
        return self._summaries

    def count(self) -> int:
        return len(self._summaries)
