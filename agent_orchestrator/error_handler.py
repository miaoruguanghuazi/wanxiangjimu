"""
error_handler.py — 四级错误处理策略实现

错误处理分级：
  Level 1: 工具级错误（单个 Tool 调用失败）
    → 重试 × 2（指数退避：1s → 3s）
    → 替代工具（python_sandbox 失败 → shell 替代）
    → 跳过该工具，标记 partial_result，继续执行

  Level 2: Agent 级错误（单 Agent 任务失败）
    → 重试 × 1（换模型重试）
    → 降级 Agent（CodeAgent 失败 → GeneralAgent 简化处理）
    → 返回部分结果 + 错误说明

  Level 3: Plan 级错误（编排计划整体失败）
    → 串行链：失败阶段的前序结果保留，返回 partial
    → 并行扇出：成功分片结果保留，失败分片报告
    → 人工审批超时：操作取消，通知用户

  Level 4: 系统级错误（模型 API 全面不可用）
    → 熔断器 OPEN
    → 降级链：缓存兜底 → 简单模型 → 本地模型 → 友好提示
    → 自动告警 + 运维通知
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable

from .models import (
    AgentResult,
    FusedResult,
    OrchestrationMode,
    OrchestrationPlan,
    TaskNode,
    TaskStatus,
)

logger = logging.getLogger(__name__)


# ===========================================================================
# 错误等级枚举
# ===========================================================================

class ErrorLevel(Enum):
    """错误处理等级"""
    TOOL = 1          # 工具级
    AGENT = 2         # Agent 级
    PLAN = 3          # Plan 级
    SYSTEM = 4        # 系统级


# ===========================================================================
# 熔断器状态
# ===========================================================================

class CircuitState(Enum):
    """熔断器状态"""
    CLOSED = "closed"      # 正常，请求通过
    OPEN = "open"          # 熔断，请求被拒绝
    HALF_OPEN = "half_open"  # 半开，允许试探请求


@dataclass
class CircuitBreaker:
    """
    熔断器

    当连续失败次数达到阈值时进入 OPEN 状态，
    经过冷却时间后进入 HALF_OPEN，试探请求成功则恢复 CLOSED。
    """
    failure_threshold: int = 5         # 连续失败阈值
    recovery_timeout: float = 60.0     # 冷却时间（秒）
    state: CircuitState = CircuitState.CLOSED
    failure_count: int = 0
    last_failure_time: float = 0.0

    def record_success(self) -> None:
        """记录成功"""
        self.failure_count = 0
        if self.state in (CircuitState.OPEN, CircuitState.HALF_OPEN):
            self.state = CircuitState.CLOSED
            logger.info("熔断器恢复：CLOSED")

    def record_failure(self) -> None:
        """记录失败"""
        self.failure_count += 1
        self.last_failure_time = time.time()

        if self.failure_count >= self.failure_threshold:
            if self.state != CircuitState.OPEN:
                self.state = CircuitState.OPEN
                logger.warning(
                    "熔断器触发 OPEN（连续失败 %d 次）", self.failure_count
                )

    def can_execute(self) -> bool:
        """是否允许执行"""
        if self.state == CircuitState.CLOSED:
            return True

        if self.state == CircuitState.OPEN:
            # 检查是否过了冷却期
            if time.time() - self.last_failure_time >= self.recovery_timeout:
                self.state = CircuitState.HALF_OPEN
                logger.info("熔断器进入 HALF_OPEN，试探请求")
                return True
            return False

        # HALF_OPEN：允许一次试探
        return True


# ===========================================================================
# Level 1: 工具级错误处理
# ===========================================================================

class ToolErrorHandler:
    """
    工具级错误处理

    策略：重试 → 替代工具 → 跳过并标记
    """

    # 工具替代映射
    FALLBACK_TOOLS: dict[str, str] = {
        "python_sandbox": "shell",
        "db_query": "file_read",       # 数据库不可用时回退到文件
        "web_search": "rag_search",    # 搜索不可用时回退到知识库
    }

    def __init__(self, tool_engine: Any) -> None:
        self.tool_engine = tool_engine
        self.circuit = CircuitBreaker(failure_threshold=3, recovery_timeout=30.0)

    async def call_with_retry(
        self,
        tool_name: str,
        params: dict,
        max_retries: int = 2,
        backoff_base: float = 1.0,
    ) -> dict:
        """
        带重试的工具调用

        Args:
            tool_name: 工具名称
            params: 调用参数
            max_retries: 最大重试次数
            backoff_base: 退避基数（秒），实际退避 = base * 2^attempt

        Returns:
            工具返回结果 dict

        Raises:
            RuntimeError: 所有重试 + 替代工具均失败时抛出
        """
        last_error: Exception | None = None

        # 原始工具重试
        for attempt in range(max_retries + 1):
            try:
                if not self.circuit.can_execute():
                    raise RuntimeError("工具熔断器处于 OPEN 状态")

                result = await self.tool_engine.call(tool_name, params)
                self.circuit.record_success()
                return result

            except Exception as e:
                last_error = e
                self.circuit.record_failure()
                logger.warning(
                    "工具 %s 第 %d 次调用失败: %s", tool_name, attempt + 1, e
                )

                if attempt < max_retries:
                    # 指数退避：1s → 2s → 4s ...
                    backoff = backoff_base * (2 ** attempt)
                    await asyncio.sleep(backoff)

        # 尝试替代工具
        fallback = self.FALLBACK_TOOLS.get(tool_name)
        if fallback:
            logger.info("尝试替代工具: %s → %s", tool_name, fallback)
            try:
                result = await self.tool_engine.call(fallback, params)
                result["_fallback"] = True
                result["_fallback_from"] = tool_name
                return result
            except Exception as e:
                logger.error("替代工具 %s 也失败: %s", fallback, e)
                last_error = e

        # 全部失败
        raise RuntimeError(
            f"工具 {tool_name} 调用失败（已重试 {max_retries} 次"
            f"{'并尝试替代工具 ' + fallback if fallback else ''}）: {last_error}"
        )


# ===========================================================================
# Level 2: Agent 级错误处理
# ===========================================================================

class AgentErrorHandler:
    """
    Agent 级错误处理

    策略：换模型重试 → 降级 Agent → 返回部分结果
    """

    # Agent 降级映射
    FALLBACK_AGENTS: dict[str, str] = {
        "code_agent": "general_agent",
        "data_agent": "general_agent",
        "ops_agent": "general_agent",
        "design_agent": "general_agent",
        "research_agent": "general_agent",
    }

    def __init__(self, agent_registry: Any, model_router: Any) -> None:
        self.registry = agent_registry
        self.model_router = model_router

    async def execute_with_retry(
        self,
        agent_id: str,
        action: str,
        params: dict,
        retry_with_alternative_model: bool = True,
    ) -> AgentResult:
        """
        带 Agent 级容错的执行

        Args:
            agent_id: 首选 Agent ID
            action: 动作
            params: 参数
            retry_with_alternative_model: 是否在失败后换模型重试

        Returns:
            AgentResult

        Raises:
            RuntimeError: 所有降级策略均失败
        """
        agent = self.registry.get(agent_id)

        # 第一次尝试
        try:
            model = await self.model_router.select(action)
            result = await agent.execute(action=action, params=params, model=model)
            return result
        except Exception as e:
            logger.warning("Agent %s 执行失败: %s", agent_id, e)

        # 换模型重试
        if retry_with_alternative_model:
            try:
                alt_model = "general-model"  # 降级到通用模型
                logger.info("使用替代模型 %s 重试", alt_model)
                result = await agent.execute(
                    action=action, params=params, model=alt_model
                )
                result.metadata["retried_with_model"] = alt_model
                return result
            except Exception as e:
                logger.warning("换模型重试也失败: %s", e)

        # 降级 Agent
        fallback_agent_id = self.FALLBACK_AGENTS.get(agent_id)
        if fallback_agent_id and fallback_agent_id != agent_id:
            try:
                fallback_agent = self.registry.get(fallback_agent_id)
                logger.info("降级到 Agent: %s → %s", agent_id, fallback_agent_id)
                result = await fallback_agent.execute(
                    action=action, params=params, model="general-model"
                )
                result.metadata["fallback_agent"] = fallback_agent_id
                return result
            except Exception as e:
                logger.error("降级 Agent %s 也失败: %s", fallback_agent_id, e)

        # 全部失败
        raise RuntimeError(
            f"Agent {agent_id} 执行 {action} 完全失败"
            f"（已尝试换模型 + 降级 Agent）"
        )


# ===========================================================================
# Level 3: Plan 级错误处理
# ===========================================================================

class PlanErrorHandler:
    """
    Plan 级错误处理

    策略：
      - 串行链：保留前序成功结果，返回 partial
      - 并行扇出：保留成功分片，报告失败分片
      - 人工审批超时：取消操作，通知用户
    """

    def handle_plan_failure(
        self, plan: OrchestrationPlan, error: str | None = None
    ) -> FusedResult:
        """
        处理编排计划级别的失败

        Args:
            plan: 失败的编排计划
            error: 失败原因

        Returns:
            FusedResult 包含部分成功结果的 FusedResult
        """
        succeeded = [
            n for n in plan.nodes if n.status == TaskStatus.SUCCESS
        ]
        failed = [
            n for n in plan.nodes
            if n.status in (TaskStatus.FAILED, TaskStatus.TIMEOUT)
        ]
        cancelled = [
            n for n in plan.nodes if n.status == TaskStatus.CANCELLED
        ]

        # 根据编排模式构建不同的错误结果
        if plan.mode == OrchestrationMode.SEQUENTIAL:
            return self._handle_sequential_failure(succeeded, failed, cancelled, plan)
        elif plan.mode == OrchestrationMode.PARALLEL_FANOUT:
            return self._handle_fanout_failure(succeeded, failed, cancelled, plan)
        elif plan.mode == OrchestrationMode.HUMAN_APPROVAL:
            return self._handle_approval_failure(succeeded, failed, cancelled, plan)
        else:
            return self._handle_generic_failure(succeeded, failed, cancelled, error)

    def _handle_sequential_failure(
        self,
        succeeded: list[TaskNode],
        failed: list[TaskNode],
        cancelled: list[TaskNode],
        plan: OrchestrationPlan,
    ) -> FusedResult:
        """串行链失败：保留前序成功结果"""
        content_parts = ["⚠️ 串行链执行中断\n\n## 已完成阶段\n"]

        for node in succeeded:
            duration = node.duration_seconds
            duration_str = f" ({duration:.1f}s)" if duration else ""
            content_parts.append(
                f"- ✅ {node.node_id}: {node.action}: 成功{duration_str}\n"
            )

        for node in failed:
            content_parts.append(
                f"- ❌ {node.node_id}: {node.action}: {node.error or '失败'}\n"
            )

        for node in cancelled:
            content_parts.append(
                f"- ⏭️ {node.node_id}: {node.action}: 已取消\n"
            )

        # 附带最后成功结果的内容
        if succeeded:
            last = succeeded[-1]
            if last.result and isinstance(last.result, AgentResult):
                content_parts.append(f"\n\n---\n\n{last.result.content}")

        return FusedResult(
            success=False,
            content="".join(content_parts),
            partial_results=[
                {"action": n.action, "status": n.status.value,
                 "error": n.error}
                for n in plan.nodes
            ],
        )

    def _handle_fanout_failure(
        self,
        succeeded: list[TaskNode],
        failed: list[TaskNode],
        cancelled: list[TaskNode],
        plan: OrchestrationPlan,
    ) -> FusedResult:
        """并行扇出失败：保留成功分片，报告失败分片"""
        content_parts = ["⚠️ 部分并行任务失败\n\n## 成功的分片\n"]

        for node in succeeded:
            if node.result and isinstance(node.result, AgentResult):
                content_parts.append(
                    f"### {node.node_id}: {node.action}\n{node.result.content[:200]}...\n\n"
                )

        if failed:
            content_parts.append("## 失败的分片\n")
            for node in failed:
                content_parts.append(
                    f"- ❌ {node.node_id}: {node.action}: {node.error}\n"
                )

        return FusedResult(
            success=False,
            content="".join(content_parts),
            partial_results=[
                {"action": n.action, "status": n.status.value,
                 "error": n.error}
                for n in plan.nodes
            ],
        )

    def _handle_approval_failure(
        self,
        succeeded: list[TaskNode],
        failed: list[TaskNode],
        cancelled: list[TaskNode],
        plan: OrchestrationPlan,
    ) -> FusedResult:
        """人工审批失败：取消操作，通知用户"""
        # 判断失败原因
        for node in cancelled:
            if node.action == "execute":
                return FusedResult(
                    success=False,
                    content="⏰ 审批超时或被拒绝，操作已取消",
                    partial_results=[
                        {"action": n.action, "status": n.status.value}
                        for n in plan.nodes
                    ],
                )

        return FusedResult(
            success=False,
            content="❌ 人工审批流程失败",
            partial_results=[
                {"action": n.action, "status": n.status.value,
                 "error": n.error}
                for n in plan.nodes
            ],
        )

    def _handle_generic_failure(
        self,
        succeeded: list[TaskNode],
        failed: list[TaskNode],
        cancelled: list[TaskNode],
        error: str | None,
    ) -> FusedResult:
        """通用错误处理"""
        return FusedResult(
            success=False,
            content=f"❌ 编排计划执行失败：{error or '未知错误'}",
            partial_results=[
                {"action": n.action, "status": n.status.value}
                for n in succeeded + failed + cancelled
            ],
        )


# ===========================================================================
# Level 4: 系统级错误处理
# ===========================================================================

class SystemErrorHandler:
    """
    系统级错误处理

    策略：
      - 熔断器 OPEN
      - 降级链：缓存兜底 → 简单模型 → 本地模型 → 友好提示
      - 自动告警 + 运维通知
    """

    # 降级链
    DEGRADATION_CHAIN: list[str] = [
        "cache",          # 缓存兜底
        "simple_model",   # 简单模型
        "local_model",    # 本地模型
        "friendly_msg",   # 友好提示
    ]

    def __init__(self) -> None:
        self.circuit = CircuitBreaker(
            failure_threshold=10, recovery_timeout=120.0
        )
        self._cache: dict[str, str] = {}  # 简单缓存
        self._alert_handlers: list[Callable] = []

    def add_alert_handler(self, handler: Callable) -> None:
        """添加告警处理器"""
        self._alert_handlers.append(handler)

    async def handle_system_failure(
        self, query: str, error: str
    ) -> FusedResult:
        """
        处理系统级故障

        按降级链依次尝试，直到返回可用结果。
        """
        # 触发告警
        await self._trigger_alert(error)

        # 降级链
        for strategy in self.DEGRADATION_CHAIN:
            try:
                result = await self._try_degradation(strategy, query, error)
                if result:
                    return result
            except Exception as e:
                logger.error("降级策略 %s 失败: %s", strategy, e)
                continue

        # 最终兜底
        return FusedResult(
            success=False,
            content=(
                "😔 系统当前遇到技术问题，暂时无法处理您的请求。\n"
                f"错误信息：{error}\n"
                "请稍后重试，或联系运维团队。"
            ),
        )

    async def _try_degradation(
        self, strategy: str, query: str, error: str
    ) -> FusedResult | None:
        """尝试单个降级策略"""

        if strategy == "cache":
            # 尝试缓存
            cache_key = hash(query)
            if cache_key in self._cache:
                logger.info("降级策略：缓存命中")
                return FusedResult(
                    success=True,
                    content=self._cache[cache_key],
                    metadata={"degraded": True, "strategy": "cache"},
                )

        elif strategy == "simple_model":
            # 尝试简单模型（占位）
            logger.info("降级策略：简单模型")
            return FusedResult(
                success=True,
                content=f"[降级响应] 基于简单模型的回复。原始查询: {query[:100]}",
                metadata={"degraded": True, "strategy": "simple_model"},
            )

        elif strategy == "local_model":
            # 尝试本地模型（占位）
            logger.info("降级策略：本地模型")
            return FusedResult(
                success=True,
                content=f"[降级响应] 基于本地模型的回复。原始查询: {query[:100]}",
                metadata={"degraded": True, "strategy": "local_model"},
            )

        elif strategy == "friendly_msg":
            # 友好提示
            return FusedResult(
                success=False,
                content=(
                    "😔 系统当前遇到技术问题，暂时无法处理您的请求。\n"
                    f"错误信息：{error}\n"
                    "请稍后重试。"
                ),
                metadata={"degraded": True, "strategy": "friendly_msg"},
            )

        return None

    async def _trigger_alert(self, error: str) -> None:
        """触发告警通知"""
        alert_msg = f"[系统告警] 模型 API 故障: {error}"
        logger.critical(alert_msg)

        for handler in self._alert_handlers:
            try:
                if asyncio.iscoroutinefunction(handler):
                    await handler(alert_msg)
                else:
                    handler(alert_msg)
            except Exception as e:
                logger.error("告警处理器异常: %s", e)

    def cache_result(self, query: str, content: str) -> None:
        """缓存查询结果（供后续降级使用）"""
        self._cache[hash(query)] = content


# ===========================================================================
# 统一错误处理器（门面模式）
# ===========================================================================

class ErrorHandler:
    """
    统一错误处理器

    将四级错误处理策略整合为一个入口，
    根据错误等级自动分派到对应的处理器。
    """

    def __init__(
        self,
        tool_engine: Any = None,
        agent_registry: Any = None,
        model_router: Any = None,
    ) -> None:
        self.tool_handler = ToolErrorHandler(tool_engine) if tool_engine else None
        self.agent_handler = (
            AgentErrorHandler(agent_registry, model_router)
            if agent_registry and model_router
            else None
        )
        self.plan_handler = PlanErrorHandler()
        self.system_handler = SystemErrorHandler()

    async def handle(
        self,
        level: ErrorLevel,
        error: str,
        context: dict | None = None,
    ) -> Any:
        """
        统一错误处理入口

        Args:
            level: 错误等级
            error: 错误描述
            context: 上下文（包含 plan, node, tool_name 等）

        Returns:
            根据错误等级返回不同类型的结果
        """
        context = context or {}

        if level == ErrorLevel.TOOL:
            return await self._handle_tool(error, context)
        elif level == ErrorLevel.AGENT:
            return await self._handle_agent(error, context)
        elif level == ErrorLevel.PLAN:
            return self._handle_plan(error, context)
        elif level == ErrorLevel.SYSTEM:
            return await self._handle_system(error, context)

    async def _handle_tool(self, error: str, context: dict) -> dict:
        """工具级错误处理"""
        tool_name = context.get("tool_name", "unknown")
        params = context.get("params", {})

        if self.tool_handler:
            try:
                return await self.tool_handler.call_with_retry(tool_name, params)
            except RuntimeError as e:
                # 工具完全不可用，返回降级结果
                return {
                    "tool": tool_name,
                    "output": f"⚠️ 工具 {tool_name} 不可用: {e}",
                    "success": False,
                    "degraded": True,
                }
        return {"tool": tool_name, "output": error, "success": False}

    async def _handle_agent(self, error: str, context: dict) -> AgentResult:
        """Agent 级错误处理"""
        agent_id = context.get("agent_id", "general_agent")
        action = context.get("action", "")
        params = context.get("params", {})

        if self.agent_handler:
            return await self.agent_handler.execute_with_retry(
                agent_id, action, params
            )

        return AgentResult(
            content=f"⚠️ Agent 执行失败: {error}",
            metadata={"error": error},
        )

    def _handle_plan(self, error: str, context: dict) -> FusedResult:
        """Plan 级错误处理"""
        plan = context.get("plan")
        if plan:
            return self.plan_handler.handle_plan_failure(plan, error)
        return FusedResult(success=False, content=f"❌ 编排失败: {error}")

    async def _handle_system(self, error: str, context: dict) -> FusedResult:
        """系统级错误处理"""
        query = context.get("query", "")
        return await self.system_handler.handle_system_failure(query, error)
