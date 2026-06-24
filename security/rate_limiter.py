"""
速率限制 — 令牌桶算法（用户级 + 全局级）

防止:
- 单用户刷接口
- 全局过载
- 恶意自动化调用
"""

from __future__ import annotations

import time
import logging
from dataclasses import dataclass, field
from collections import defaultdict

logger = logging.getLogger(__name__)


@dataclass
class RateLimitResult:
    ok: bool
    message: str
    remaining: int = 0
    reset_at: float = 0.0


@dataclass
class TokenBucket:
    """令牌桶"""
    capacity: int          # 桶容量
    tokens: float          # 当前令牌数
    refill_rate: float     # 每秒补充令牌数
    last_refill: float     # 上次补充时间

    def consume(self, now: float, count: int = 1) -> tuple[bool, int]:
        """尝试消费令牌，返回 (是否成功, 剩余令牌)"""
        # 补充令牌
        elapsed = now - self.last_refill
        self.tokens = min(self.capacity, self.tokens + elapsed * self.refill_rate)
        self.last_refill = now

        if self.tokens >= count:
            self.tokens -= count
            return True, int(self.tokens)
        return False, int(self.tokens)


class RateLimiter:
    """
    速率限制器

    用法:
        limiter = RateLimiter(user_capacity=20, global_capacity=200)
        result = limiter.check(session_id)
        if not result.ok:
            return "请求过于频繁，请稍后再试"
    """

    def __init__(
        self,
        user_capacity: int = 20,       # 每用户桶容量
        user_refill_rate: float = 2.0,  # 每用户每秒补充2个令牌
        global_capacity: int = 200,     # 全局桶容量
        global_refill_rate: float = 20.0,  # 全局每秒补充20个
    ):
        self.user_capacity = user_capacity
        self.user_refill_rate = user_refill_rate
        self.global_capacity = global_capacity
        self.global_refill_rate = global_refill_rate

        self._user_buckets: dict[str, TokenBucket] = {}
        self._global_bucket = TokenBucket(
            capacity=global_capacity,
            tokens=global_capacity,
            refill_rate=global_refill_rate,
            last_refill=time.time(),
        )

        self._stats = {"allowed": 0, "blocked": 0}

    def check(self, user_id: str) -> RateLimitResult:
        """检查速率限制"""
        now = time.time()

        # 全局检查
        global_ok, global_remaining = self._global_bucket.consume(now)
        if not global_ok:
            self._stats["blocked"] += 1
            return RateLimitResult(
                ok=False,
                message="⚠️ 系统繁忙，请稍后再试",
                remaining=0,
                reset_at=now + (1.0 / self.global_refill_rate),
            )

        # 用户级检查
        if user_id not in self._user_buckets:
            self._user_buckets[user_id] = TokenBucket(
                capacity=self.user_capacity,
                tokens=self.user_capacity,
                refill_rate=self.user_refill_rate,
                last_refill=now,
            )

        bucket = self._user_buckets[user_id]
        user_ok, user_remaining = bucket.consume(now)

        if not user_ok:
            self._stats["blocked"] += 1
            return RateLimitResult(
                ok=False,
                message="⚠️ 请求过于频繁，请稍后再试",
                remaining=0,
                reset_at=now + (1.0 / self.user_refill_rate),
            )

        self._stats["allowed"] += 1
        return RateLimitResult(
            ok=True,
            message="",
            remaining=min(user_remaining, global_remaining),
            reset_at=now,
        )

    def get_stats(self) -> dict:
        return {
            **self._stats,
            "active_users": len(self._user_buckets),
            "global_tokens": int(self._global_bucket.tokens),
        }

    def cleanup_stale(self, max_age: float = 3600):
        """清理超过 max_age 秒未活动的用户桶"""
        now = time.time()
        stale = [
            uid for uid, bucket in self._user_buckets.items()
            if now - bucket.last_refill > max_age
        ]
        for uid in stale:
            del self._user_buckets[uid]
        if stale:
            logger.info(f"速率限制器清理了 {len(stale)} 个过期用户桶")
