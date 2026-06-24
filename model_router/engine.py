"""
路由引擎 — 核心调度逻辑

流程: 任务分类 → 能力过滤 → 熔断过滤 → 三轴评分 → 排序 → 构建降级链
"""

from __future__ import annotations

import time
import logging
from dataclasses import dataclass, field
from typing import Optional

from .registry import ModelRegistry, ModelConfig
from .circuit_breaker import CircuitBreakerManager
from .classifier import TaskClassifier, TaskType
from .scorer import ThreeAxisScorer, ModelScore, PREFERENCE_WEIGHTS

logger = logging.getLogger(__name__)


@dataclass
class RouteResult:
    """路由决策结果"""
    primary_model: str           # model_id
    litellm_model: str           # litellm 调用名
    fallback_chain: list[str]    # 降级 model_id 列表
    task_type: TaskType
    preference: str              # 使用的偏好策略
    all_scores: list[ModelScore] # 所有候选评分
    reason: str = ""
    # 新增：详细路由链路追踪
    route_steps: list[dict] = field(default_factory=list)  # 每一步的详细信息
    elapsed_ms: float = 0.0

    def to_dict(self) -> dict:
        return {
            "primary_model": self.primary_model,
            "litellm_model": self.litellm_model,
            "fallback_chain": self.fallback_chain,
            "task_type": self.task_type.value,
            "preference": self.preference,
            "scores": [s.to_dict() for s in self.all_scores[:5]],
            "reason": self.reason,
            "route_steps": self.route_steps,
            "elapsed_ms": round(self.elapsed_ms, 1),
        }


class RouterEngine:
    """
    路由引擎

    用法:
        engine = RouterEngine(registry, circuit_manager)
        result = engine.route("帮我写个Python函数", preference="balanced")
        # result.primary_model → "deepseek-coder"
        # result.litellm_model → "deepseek/deepseek-coder"
    """

    # 任务类型 → 默认偏好
    DEFAULT_PREFERENCE = {
        "chat": "fast",
        "qa": "balanced",
        "code": "best",
        "writing": "best",
        "reasoning": "best",
        "multimodal": "best",
        "long_context": "balanced",
    }

    def __init__(
        self,
        registry: ModelRegistry,
        circuit_manager: CircuitBreakerManager,
        default_preference: str = "balanced",
    ):
        self.registry = registry
        self.circuit = circuit_manager
        self.classifier = TaskClassifier()
        self.default_preference = default_preference

    def route(
        self,
        message: str,
        task_type: Optional[TaskType] = None,
        preference: Optional[str] = None,
        attachments: list = None,
    ) -> RouteResult:
        start = time.time()
        steps = []

        # Step 1: 任务分类
        if task_type is None:
            task_type = self.classifier.classify(message, attachments)
        steps.append({"step": "1️⃣ 任务分类", "detail": f"识别为 <b>{task_type.value}</b>", "icon": "🏷️"})

        # Step 2: 确定偏好策略
        pref_name = preference or self.DEFAULT_PREFERENCE.get(task_type.value, self.default_preference)
        weights = PREFERENCE_WEIGHTS.get(pref_name, PREFERENCE_WEIGHTS["balanced"])
        weight_desc = f"成本 {weights['cost_weight']:.0%} · 质量 {weights['quality_weight']:.0%} · 速度 {weights['speed_weight']:.0%}"
        steps.append({"step": "2️⃣ 偏好策略", "detail": f"选用 <b>{pref_name}</b>（{weight_desc}）", "icon": "⚖️"})

        # Step 3: 能力过滤
        required_caps = TaskClassifier.get_required_capabilities(task_type)
        candidates = self.registry.filter_by_capability(required_caps)
        steps.append({"step": "3️⃣ 能力过滤", "detail": f"需要能力 <b>{', '.join(required_caps)}</b>，<b>{len(candidates)}</b> 个模型符合", "icon": "🔍"})

        if not candidates:
            logger.warning(f"无候选模型支持能力 {required_caps}，使用所有可用模型")
            candidates = self.registry.all_enabled()
            steps[-1]["detail"] += " → 无匹配，回退到全部可用模型"

        if not candidates:
            raise RuntimeError("没有可用的模型（所有模型未配置 API Key 或被禁用）")

        # Step 4: 熔断过滤
        total_before = len(candidates)
        available = [m for m in candidates if self.circuit.is_available(m.model_id)]
        circuit_broken = total_before - len(available)
        if circuit_broken > 0:
            steps.append({"step": "4️⃣ 熔断过滤", "detail": f"排除 <b>{circuit_broken}</b> 个熔断模型，<b>{len(available)}</b> 个候选剩余", "icon": "⚡"})
        else:
            steps.append({"step": "4️⃣ 熔断过滤", "detail": f"全部 <b>{len(available)}</b> 个模型状态正常", "icon": "✅"})

        if not available:
            logger.warning("所有候选模型均被熔断，绕过熔断使用候选列表")
            available = candidates
            steps[-1]["detail"] += " → 全部熔断，强制绕过"

        # Step 5: 三轴评分 + 排序
        scorer = ThreeAxisScorer(weights=weights)
        ranked = scorer.rank(available, task_type.value, top_k=len(available))

        # 评分摘要
        top_scores = ranked[:3]
        score_lines = []
        for s in top_scores:
            score_lines.append(f"{s.model_id} ({s.final_score}分)")
        steps.append({"step": "5️⃣ 评分排序", "detail": f"前三: {' → '.join(score_lines)}", "icon": "📊"})

        primary = ranked[0]
        primary_cfg = self.registry.get(primary.model_id)

        # Step 6: 构建降级链
        fallback = [s.model_id for s in ranked[1:] if s.model_id != primary.model_id]
        steps.append({"step": "6️⃣ 降级链", "detail": f"主选 <b>{primary.model_id}</b> → 备选 <b>{len(fallback)}</b> 个", "icon": "🔄"})

        elapsed = (time.time() - start) * 1000
        logger.info(f"路由: {task_type.value} → {primary.model_id} (偏好={pref_name}, 耗时={elapsed:.1f}ms)")

        return RouteResult(
            primary_model=primary.model_id,
            litellm_model=primary_cfg.litellm_model if primary_cfg else primary.model_id,
            fallback_chain=fallback,
            task_type=task_type,
            preference=pref_name,
            all_scores=ranked,
            route_steps=steps,
            elapsed_ms=elapsed,
            reason=f"任务={task_type.value}, 偏好={pref_name}, 候选={len(available)}",
        )
