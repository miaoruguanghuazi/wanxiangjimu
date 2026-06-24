"""
三轴评分器 — cost / quality / speed 加权评分
"""

from __future__ import annotations

import math
import logging
from dataclasses import dataclass
from typing import Optional

from .registry import ModelConfig
from .classifier import TaskType

logger = logging.getLogger(__name__)


@dataclass
class ModelScore:
    """模型评分结果"""
    model_id: str
    final_score: float
    cost_score: float
    quality_score: float
    speed_score: float

    def to_dict(self) -> dict:
        return {
            "model_id": self.model_id,
            "final_score": round(self.final_score, 2),
            "cost_score": round(self.cost_score, 2),
            "quality_score": round(self.quality_score, 2),
            "speed_score": round(self.speed_score, 2),
        }


class ThreeAxisScorer:
    """
    三轴评分器
    Cost Score: 越便宜越高
    Quality Score: 基于任务类型的质量维度
    Speed Score: 越快越高
    """

    MAX_COST = 15.0      # USD/1M tokens 满分基准
    MAX_QUALITY = 10.0
    MAX_SPEED_TIER = 5.0

    # 任务类型 → 质量维度映射
    DIMENSION_MAP = {
        "chat": "general_qa",
        "qa": "general_qa",
        "code": "coding",
        "writing": "creative_writing",
        "reasoning": "reasoning",
        "multimodal": "general_qa",
        "long_context": "general_qa",
    }

    def __init__(self, weights: dict = None):
        w = weights or {}
        self.cost_weight = w.get("cost_weight", 0.33)
        self.quality_weight = w.get("quality_weight", 0.34)
        self.speed_weight = w.get("speed_weight", 0.33)

    def score(self, model_cfg: ModelConfig, task_type: str, estimated_tokens: int = 2000) -> ModelScore:
        cost_s = self._cost_score(model_cfg, estimated_tokens)
        quality_s = self._quality_score(model_cfg, task_type)
        speed_s = self._speed_score(model_cfg)

        total = (self.cost_weight * cost_s +
                 self.quality_weight * quality_s +
                 self.speed_weight * speed_s)

        return ModelScore(
            model_id=model_cfg.model_id,
            final_score=round(total, 2),
            cost_score=round(cost_s, 2),
            quality_score=round(quality_s, 2),
            speed_score=round(speed_s, 2),
        )

    def _cost_score(self, model_cfg: ModelConfig, estimated_tokens: int) -> float:
        est_input = estimated_tokens * 0.4
        est_output = model_cfg.max_output * 0.3
        cost = model_cfg.cost_per_call(int(est_input), int(est_output))
        score = 100 * math.exp(-cost / 2.0)
        return min(100, score)

    def _quality_score(self, model_cfg: ModelConfig, task_type: str) -> float:
        dim = self.DIMENSION_MAP.get(task_type, "general_qa")
        raw = model_cfg.quality_scores.get(dim, 5)
        return (raw / self.MAX_QUALITY) * 100

    def _speed_score(self, model_cfg: ModelConfig) -> float:
        tier = model_cfg.speed_tier
        return (1 - (tier - 1) / (self.MAX_SPEED_TIER - 1)) * 100

    def rank(self, candidates: list[ModelConfig], task_type: str, top_k: int = 5) -> list[ModelScore]:
        scored = [self.score(m, task_type) for m in candidates]
        scored.sort(key=lambda x: x.final_score, reverse=True)
        return scored[:top_k]


# 预设权重策略
PREFERENCE_WEIGHTS = {
    "balanced": {"cost_weight": 0.33, "quality_weight": 0.34, "speed_weight": 0.33},
    "cheap": {"cost_weight": 0.55, "quality_weight": 0.25, "speed_weight": 0.20},
    "best": {"cost_weight": 0.15, "quality_weight": 0.60, "speed_weight": 0.25},
    "fast": {"cost_weight": 0.20, "quality_weight": 0.25, "speed_weight": 0.55},
}
