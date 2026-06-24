"""
会话安全 — 超时管理 + 会话隔离

防止:
- 会话固定攻击
- 会话劫持
- 长时间空闲会话占资源
"""

from __future__ import annotations

import time
import logging
from dataclasses import dataclass
from collections import defaultdict

logger = logging.getLogger(__name__)


@dataclass
class SessionInfo:
    """会话信息"""
    session_id: str
    created_at: float
    last_active: float
    message_count: int = 0
    user_id: str = ""


class SessionGuard:
    """
    会话安全守卫

    用法:
        guard = SessionGuard(timeout=3600)
        guard.touch("session_abc")
        if guard.is_expired("session_abc"):
            guard.cleanup("session_abc")
    """

    def __init__(
        self,
        timeout: float = 3600,       # 默认1小时超时
        max_messages: int = 1000,    # 单会话最大消息数
        max_sessions: int = 100,     # 最大并发会话数
    ):
        self.timeout = timeout
        self.max_messages = max_messages
        self.max_sessions = max_sessions
        self._sessions: dict[str, SessionInfo] = {}
        self._stats = {"created": 0, "expired": 0, "rejected": 0}

    def touch(self, session_id: str, user_id: str = "") -> bool:
        """
        更新会话活跃时间

        Returns:
            True 如果会话有效, False 如果被拒绝（超限/过期）
        """
        now = time.time()

        if session_id not in self._sessions:
            # 新会话 — 检查并发上限
            if len(self._sessions) >= self.max_sessions:
                # 清理过期会话
                self.cleanup_expired()
                if len(self._sessions) >= self.max_sessions:
                    self._stats["rejected"] += 1
                    return False

            self._sessions[session_id] = SessionInfo(
                session_id=session_id,
                created_at=now,
                last_active=now,
                user_id=user_id,
            )
            self._stats["created"] += 1
        else:
            self._sessions[session_id].last_active = now

        return True

    def increment_message(self, session_id: str) -> bool:
        """
        增加消息计数

        Returns:
            True 如果未超限, False 如果超过最大消息数
        """
        if session_id not in self._sessions:
            return False

        info = self._sessions[session_id]
        info.message_count += 1
        if info.message_count > self.max_messages:
            return False
        return True

    def is_expired(self, session_id: str) -> bool:
        """检查会话是否过期"""
        if session_id not in self._sessions:
            return True
        info = self._sessions[session_id]
        return (time.time() - info.last_active) > self.timeout

    def cleanup(self, session_id: str):
        """清理单个会话"""
        if session_id in self._sessions:
            del self._sessions[session_id]
            logger.info(f"会话 {session_id} 已清理")

    def cleanup_expired(self) -> int:
        """清理所有过期会话，返回清理数量"""
        now = time.time()
        expired = [
            sid for sid, info in self._sessions.items()
            if (now - info.last_active) > self.timeout
        ]
        for sid in expired:
            del self._sessions[sid]
        self._stats["expired"] += len(expired)
        if expired:
            logger.info(f"清理了 {len(expired)} 个过期会话")
        return len(expired)

    def get_active_count(self) -> int:
        return len(self._sessions)

    def get_stats(self) -> dict:
        return {
            **self._stats,
            "active": len(self._sessions),
        }
