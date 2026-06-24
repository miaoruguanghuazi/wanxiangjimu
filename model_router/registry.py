"""
模型注册表 — 管理所有模型配置
支持从环境变量加载 API Key，从 YAML 配置加载模型参数
"""

from __future__ import annotations

import os
import math
import logging
from dataclasses import dataclass, field
from typing import Optional

logger = logging.getLogger(__name__)


@dataclass
class ModelConfig:
    """单个模型的完整配置"""
    model_id: str                          # 唯一标识，如 "deepseek-chat"
    litellm_model: str                     # litellm 调用名，如 "deepseek/deepseek-chat"
    provider: str                          # 提供商
    api_key_env: str                       # 环境变量名
    context_window: int = 64000            # 上下文窗口 tokens
    max_output: int = 4096                 # 最大输出 tokens
    pricing: dict = field(default_factory=lambda: {"input": 0.0, "output": 0.0})  # USD/1M tokens
    capabilities: list[str] = field(default_factory=lambda: ["text"])
    speed_tier: int = 3                    # 1=最快 5=最慢
    quality_scores: dict = field(default_factory=lambda: {"general_qa": 7, "coding": 7, "reasoning": 7, "creative_writing": 7})
    enabled: bool = True

    @property
    def api_key(self) -> str:
        return os.environ.get(self.api_key_env, "")

    @property
    def is_available(self) -> bool:
        """API Key 是否已配置"""
        key = self.api_key
        return bool(key) and "你的" not in key and "sk-xxx" not in key

    def cost_per_call(self, input_tokens: int = 2000, output_tokens: int = 1000) -> float:
        """估算单次调用成本（USD）"""
        return (input_tokens / 1_000_000 * self.pricing["input"] +
                output_tokens / 1_000_000 * self.pricing["output"])

    def has_capability(self, cap: str) -> bool:
        return cap in self.capabilities

    def supports_all(self, caps: list[str]) -> bool:
        return all(c in self.capabilities for c in caps)


class ModelRegistry:
    """模型注册表"""

    def __init__(self):
        self.models: dict[str, ModelConfig] = {}

    def register(self, config: ModelConfig):
        self.models[config.model_id] = config
        return self

    def get(self, model_id: str) -> Optional[ModelConfig]:
        return self.models.get(model_id)

    def all_enabled(self) -> list[ModelConfig]:
        """返回所有已启用且有 API Key 的模型"""
        return [m for m in self.models.values() if m.enabled and m.is_available]

    def filter_by_capability(self, caps: list[str]) -> list[ModelConfig]:
        return [m for m in self.all_enabled() if m.supports_all(caps)]

    def list_models(self) -> list[dict]:
        """返回所有模型信息（用于 UI 展示）"""
        result = []
        for m in self.models.values():
            result.append({
                "model_id": m.model_id,
                "litellm_model": m.litellm_model,
                "provider": m.provider,
                "enabled": m.enabled,
                "available": m.is_available,
                "speed_tier": m.speed_tier,
                "capabilities": m.capabilities,
                "pricing": m.pricing,
                "context_window": m.context_window,
            })
        return result


def default_registry() -> ModelRegistry:
    """
    创建默认模型注册表
    包含 DeepSeek、豆包、OpenAI 等主流模型
    """
    registry = ModelRegistry()

    # DeepSeek
    registry.register(ModelConfig(
        model_id="deepseek-chat",
        litellm_model="deepseek/deepseek-chat",
        provider="deepseek",
        api_key_env="DEEPSEEK_API_KEY",
        context_window=64000,
        max_output=4096,
        pricing={"input": 0.14, "output": 0.28},  # USD/1M tokens
        capabilities=["text", "code", "reasoning"],
        speed_tier=2,
        quality_scores={"general_qa": 8, "coding": 8, "reasoning": 8, "creative_writing": 7},
    ))

    registry.register(ModelConfig(
        model_id="deepseek-coder",
        litellm_model="deepseek/deepseek-coder",
        provider="deepseek",
        api_key_env="DEEPSEEK_API_KEY",
        context_window=64000,
        max_output=4096,
        pricing={"input": 0.14, "output": 0.28},
        capabilities=["text", "code"],
        speed_tier=2,
        quality_scores={"general_qa": 7, "coding": 9, "reasoning": 7, "creative_writing": 6},
    ))

    # 豆包（火山引擎）— 从环境变量读取 endpoint，无则跳过
    doubao_endpoint = os.environ.get("DOUBAO_ENDPOINT", "")
    if doubao_endpoint and "xxxxx" not in doubao_endpoint:
        registry.register(ModelConfig(
            model_id="doubao-pro",
            litellm_model=f"doubao/{doubao_endpoint}",
            provider="volcengine",
            api_key_env="VOLC_API_KEY",
            context_window=32000,
            max_output=4096,
            pricing={"input": 0.11, "output": 0.28},
            capabilities=["text", "reasoning"],
            speed_tier=1,
            quality_scores={"general_qa": 7, "coding": 6, "reasoning": 7, "creative_writing": 7},
        ))
    else:
        logger.info("DOUBAO_ENDPOINT 未配置或包含占位符，跳过注册豆包模型")

    # OpenAI GPT-4o
    registry.register(ModelConfig(
        model_id="gpt-4o",
        litellm_model="gpt-4o",
        provider="openai",
        api_key_env="OPENAI_API_KEY",
        context_window=128000,
        max_output=4096,
        pricing={"input": 2.50, "output": 10.00},
        capabilities=["text", "code", "reasoning", "multimodal_vision"],
        speed_tier=3,
        quality_scores={"general_qa": 9, "coding": 9, "reasoning": 9, "creative_writing": 9},
    ))

    # OpenAI GPT-3.5-turbo（便宜）
    registry.register(ModelConfig(
        model_id="gpt-35-turbo",
        litellm_model="gpt-3.5-turbo",
        provider="openai",
        api_key_env="OPENAI_API_KEY",
        context_window=16000,
        max_output=4096,
        pricing={"input": 0.50, "output": 1.50},
        capabilities=["text", "code"],
        speed_tier=1,
        quality_scores={"general_qa": 7, "coding": 7, "reasoning": 6, "creative_writing": 7},
    ))

    # 通义千问
    registry.register(ModelConfig(
        model_id="qwen-plus",
        litellm_model="dashscope/qwen-plus",
        provider="aliyun",
        api_key_env="DASHSCOPE_API_KEY",
        context_window=128000,
        max_output=4096,
        pricing={"input": 0.40, "output": 1.20},
        capabilities=["text", "code", "reasoning"],
        speed_tier=2,
        quality_scores={"general_qa": 8, "coding": 7, "reasoning": 8, "creative_writing": 8},
    ))

    return registry
