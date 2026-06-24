"""
统一模型调用适配器 — 接入 litellm

提供:
- call(): 普通调用（含熔断 + 降级）
- stream_call(): 流式调用
- 自动降级到 fallback_chain 中的下一个模型
"""

from __future__ import annotations

import time
import logging
from dataclasses import dataclass
from typing import Optional, AsyncGenerator

from .registry import ModelRegistry, ModelConfig
from .circuit_breaker import CircuitBreakerManager
from .engine import RouterEngine, RouteResult

logger = logging.getLogger(__name__)


@dataclass
class LLMResponse:
    content: str
    model: str
    token_usage: dict
    latency_ms: float
    finish_reason: str = "stop"
    from_cache: bool = False


class ModelAdapter:
    """
    统一模型调用适配器

    用法:
        adapter = ModelAdapter(registry, circuit_manager)
        result = await adapter.call_with_route(
            route_result=engine.route("你好"),
            messages=[{"role": "user", "content": "你好"}],
        )
    """

    def __init__(
        self,
        registry: ModelRegistry,
        circuit_manager: CircuitBreakerManager,
    ):
        self.registry = registry
        self.circuit = circuit_manager

    async def call(
        self,
        model_id: str,
        messages: list[dict],
        temperature: float = 0.7,
        max_tokens: int = 4096,
    ) -> LLMResponse:
        """直接调用指定模型"""
        cfg = self.registry.get(model_id)
        if not cfg:
            raise ValueError(f"未知模型: {model_id}")

        if not self.circuit.can_execute(model_id):
            raise CircuitOpenError(f"模型 {model_id} 熔断中")

        from litellm import acompletion

        start = time.time()
        try:
            kwargs = {
                "model": cfg.litellm_model,
                "messages": messages,
                "temperature": temperature,
                "max_tokens": max_tokens,
            }
            if cfg.api_key:
                kwargs["api_key"] = cfg.api_key
            response = await acompletion(**kwargs)
            elapsed = (time.time() - start) * 1000
            self.circuit.record_success(model_id)

            return LLMResponse(
                content=response.choices[0].message.content or "",
                model=model_id,
                token_usage={
                    "prompt_tokens": getattr(response.usage, "prompt_tokens", 0),
                    "completion_tokens": getattr(response.usage, "completion_tokens", 0),
                    "total_tokens": getattr(response.usage, "total_tokens", 0),
                },
                latency_ms=elapsed,
                finish_reason=response.choices[0].finish_reason or "stop",
            )
        except CircuitOpenError:
            raise
        except Exception as e:
            self.circuit.record_failure(model_id, reason=str(e))
            raise

    async def call_with_route(
        self,
        route_result: RouteResult,
        messages: list[dict],
        temperature: float = 0.7,
        max_tokens: int = 4096,
    ) -> LLMResponse:
        """
        按路由结果调用，含自动降级

        先尝试 primary_model，失败则依次尝试 fallback_chain
        """
        # 构建尝试列表: primary + fallbacks
        try_models = [route_result.primary_model] + route_result.fallback_chain

        last_error = None
        for model_id in try_models:
            cfg = self.registry.get(model_id)
            if not cfg or not cfg.is_available:
                continue

            if not self.circuit.can_execute(model_id):
                logger.info(f"跳过 {model_id}（熔断中）")
                continue

            try:
                return await self.call(model_id, messages, temperature, max_tokens)
            except CircuitOpenError:
                raise
            except Exception as e:
                logger.warning(f"模型 {model_id} 调用失败: {e}")
                last_error = e
                continue

        raise RuntimeError(f"所有模型调用失败，最后错误: {last_error}")

    async def stream_call(
        self,
        model_id: str,
        messages: list[dict],
        temperature: float = 0.7,
        max_tokens: int = 4096,
    ) -> AsyncGenerator[str, None]:
        """流式调用指定模型"""
        cfg = self.registry.get(model_id)
        if not cfg:
            raise ValueError(f"未知模型: {model_id}")

        if not self.circuit.can_execute(model_id):
            raise CircuitOpenError(f"模型 {model_id} 熔断中")

        from litellm import acompletion

        try:
            kwargs = {
                "model": cfg.litellm_model,
                "messages": messages,
                "temperature": temperature,
                "max_tokens": max_tokens,
                "stream": True,
            }
            if cfg.api_key:
                kwargs["api_key"] = cfg.api_key
            response = await acompletion(**kwargs)
            async for chunk in response:
                delta = chunk.choices[0].delta
                if delta and delta.content:
                    yield delta.content

            self.circuit.record_success(model_id)
        except CircuitOpenError:
            raise
        except Exception as e:
            self.circuit.record_failure(model_id, reason=str(e))
            raise

    async def stream_call_with_route(
        self,
        route_result: RouteResult,
        messages: list[dict],
        temperature: float = 0.7,
        max_tokens: int = 4096,
    ) -> AsyncGenerator[str, None]:
        """流式调用，含自动降级"""
        try_models = [route_result.primary_model] + route_result.fallback_chain

        last_error = None
        for model_id in try_models:
            cfg = self.registry.get(model_id)
            if not cfg or not cfg.is_available:
                continue

            if not self.circuit.can_execute(model_id):
                logger.info(f"跳过 {model_id}（熔断中）")
                continue

            try:
                async for chunk in self.stream_call(model_id, messages, temperature, max_tokens):
                    yield chunk
                return  # 成功完成，不再尝试下一个
            except CircuitOpenError:
                raise
            except Exception as e:
                logger.warning(f"模型 {model_id} 流式调用失败: {e}")
                last_error = e
                continue

        # 所有模型都失败了
        yield f"\n\n❌ 所有模型调用失败: {last_error}"


class CircuitOpenError(Exception):
    """熔断器开启异常"""
    pass
