"""
熔断器 — 三状态自动机
CLOSED → OPEN → HALF_OPEN → CLOSED/OPEN
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Optional

logger = logging.getLogger(__name__)


class CircuitState(Enum):
    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


@dataclass
class CircuitBreaker:
    """单个模型的熔断器"""
    model_id: str
    failure_threshold: int = 3
    success_threshold: int = 2
    open_timeout_seconds: int = 60
    half_open_max_calls: int = 3

    state: CircuitState = CircuitState.CLOSED
    failure_count: int = 0
    success_count: int = 0
    half_open_calls: int = 0
    last_failure_time: Optional[datetime] = None
    last_failure_reason: str = ""

    def can_execute(self) -> bool:
        if self.state == CircuitState.CLOSED:
            return True

        if self.state == CircuitState.OPEN:
            if self.last_failure_time:
                elapsed = datetime.now(timezone.utc) - self.last_failure_time
                if elapsed.total_seconds() >= self.open_timeout_seconds:
                    self._transition_to_half_open()
                    return True
            return False

        # HALF_OPEN
        return self.half_open_calls < self.half_open_max_calls

    def record_success(self):
        self.failure_count = 0
        if self.state == CircuitState.HALF_OPEN:
            self.success_count += 1
            self.half_open_calls += 1
            if self.success_count >= self.success_threshold:
                self._transition_to_closed()
        else:
            self.success_count = 1
            self.half_open_calls = 0

    def record_failure(self, reason: str = ""):
        self.failure_count += 1
        self.last_failure_time = datetime.now(timezone.utc)
        self.last_failure_reason = reason

        if self.state == CircuitState.HALF_OPEN:
            self._transition_to_open()
        elif self.state == CircuitState.CLOSED:
            if self.failure_count >= self.failure_threshold:
                self._transition_to_open()

    def _transition_to_open(self):
        self.state = CircuitState.OPEN
        self.half_open_calls = 0
        self.success_count = 0
        logger.warning(f"熔断器 [OPEN] {self.model_id}: 连续失败 {self.failure_count} 次, 原因: {self.last_failure_reason}")

    def _transition_to_half_open(self):
        self.state = CircuitState.HALF_OPEN
        self.half_open_calls = 0
        self.success_count = 0
        logger.info(f"熔断器 [HALF_OPEN] {self.model_id}: 超时恢复，进入半开状态")

    def _transition_to_closed(self):
        self.state = CircuitState.CLOSED
        self.failure_count = 0
        self.success_count = 0
        logger.info(f"熔断器 [CLOSED] {self.model_id}: 连续成功 {self.success_threshold} 次，完全恢复")

    def to_dict(self) -> dict:
        return {
            "model_id": self.model_id,
            "state": self.state.value,
            "failure_count": self.failure_count,
            "success_count": self.success_count,
            "last_failure_at": self.last_failure_time.isoformat() if self.last_failure_time else None,
            "last_failure_reason": self.last_failure_reason,
        }


class CircuitBreakerManager:
    """熔断器管理器 — 为每个模型维护独立熔断器"""

    def __init__(self, config: dict = None):
        cfg = config or {}
        self.failure_threshold = cfg.get("failure_threshold", 3)
        self.success_threshold = cfg.get("success_threshold", 2)
        self.open_timeout = cfg.get("open_timeout_seconds", 60)
        self.half_open_max = cfg.get("half_open_max_calls", 3)
        self._breakers: dict[str, CircuitBreaker] = {}

    def get(self, model_id: str) -> CircuitBreaker:
        if model_id not in self._breakers:
            self._breakers[model_id] = CircuitBreaker(
                model_id=model_id,
                failure_threshold=self.failure_threshold,
                success_threshold=self.success_threshold,
                open_timeout_seconds=self.open_timeout,
                half_open_max_calls=self.half_open_max,
            )
        return self._breakers[model_id]

    def can_execute(self, model_id: str) -> bool:
        return self.get(model_id).can_execute()

    def record_success(self, model_id: str):
        self.get(model_id).record_success()

    def record_failure(self, model_id: str, reason: str = ""):
        self.get(model_id).record_failure(reason)

    def is_available(self, model_id: str) -> bool:
        return self.can_execute(model_id)

    def all_status(self) -> dict:
        return {mid: cb.to_dict() for mid, cb in self._breakers.items()}
