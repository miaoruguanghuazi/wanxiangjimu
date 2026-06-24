"""
result_fuser.py — ResultFuser 结果聚合器

将多个 Agent / 节点的执行结果聚合为最终的 FusedResult。

策略：
  - 单结果：直接包装返回
  - 并行扇出：LLM 合并各分片为统一输出
  - 串行链：取最终阶段结果 + 各阶段摘要
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from .models import (
    AgentResult,
    FusedResult,
    OrchestrationMode,
    OrchestrationPlan,
    TaskStatus,
)


class ResultFuser:
    """
    结果聚合器

    将 OrchestrationPlan 中各节点的执行结果聚合为统一的 FusedResult。
    可选注入 model_router 用于 LLM 合并。
    """

    def __init__(self, model_router: Any = None) -> None:
        """
        Args:
            model_router: 模型路由器（可选，用于 LLM 合并并行结果）
        """
        self.model_router = model_router

    async def fuse(self, plan: OrchestrationPlan) -> FusedResult:
        """
        聚合编排计划中所有节点的结果

        Args:
            plan: 已执行完毕（或部分执行）的编排计划

        Returns:
            FusedResult 聚合后的最终结果
        """
        all_results = [n for n in plan.nodes if n.status == TaskStatus.SUCCESS]
        failed = [
            n for n in plan.nodes
            if n.status in (TaskStatus.FAILED, TaskStatus.TIMEOUT)
        ]

        # 所有子任务都失败
        if not all_results:
            return FusedResult(
                success=False,
                content="❌ 所有子任务均失败",
                partial_results=[
                    {"action": n.action, "status": n.status.value,
                     "error": n.error}
                    for n in plan.nodes
                ],
            )

        # 只有一个成功结果
        if len(all_results) == 1:
            return self._single_result(all_results[0], failed)

        # 并行扇出模式：LLM 合并
        if plan.mode == OrchestrationMode.PARALLEL_FANOUT:
            return await self._merge_parallel(all_results, failed)

        # 串行链模式：取最终阶段 + 摘要
        if plan.mode == OrchestrationMode.SEQUENTIAL:
            return self._chain_result(all_results, failed)

        # 其他模式：取最后一个成功结果
        return self._single_result(all_results[-1], failed)

    # ===================================================================
    # 单结果包装
    # ===================================================================

    def _single_result(self, node: Any, failed: list) -> FusedResult:
        """将单个节点的结果包装为 FusedResult"""
        result = node.result
        content = result.content if isinstance(result, AgentResult) else str(result)

        # 如果有失败节点，追加警告
        if failed:
            content += "\n\n⚠️ 部分子任务失败：" + ", ".join(
                f"{n.action}({n.error})" for n in failed
            )

        attachments = []
        if isinstance(result, AgentResult):
            attachments = result.attachments

        return FusedResult(
            success=len(failed) == 0,
            content=content,
            attachments=attachments,
            metadata={
                "token_usage": result.token_usage if isinstance(result, AgentResult) else {},
            },
            partial_results=[
                {"action": node.action, "status": node.status.value}
            ] + [
                {"action": n.action, "status": n.status.value, "error": n.error}
                for n in failed
            ],
        )

    # ===================================================================
    # 并行扇出合并
    # ===================================================================

    async def _merge_parallel(self, results: list, failed: list) -> FusedResult:
        """
        并行扇出：合并各分片结果

        如果有 model_router，使用 LLM 合并为连贯输出；
        否则用简单拼接。
        """
        parts = []
        for i, node in enumerate(results):
            content = (
                node.result.content
                if isinstance(node.result, AgentResult)
                else str(node.result)
            )
            parts.append(f"### 结果 {i + 1}：{node.action}（{node.node_id}）\n{content}")

        if self.model_router:
            # 使用 LLM 合并
            merged = await self._llm_merge(parts)
        else:
            # 简单拼接
            merged = "\n\n---\n\n".join(parts)

        # 追加失败信息
        if failed:
            merged += f"\n\n⚠️ {len(failed)} 个子任务失败：" + ", ".join(
                f"{n.action}({n.error})" for n in failed
            )

        # 聚合 attachments
        all_attachments = []
        for node in results:
            if isinstance(node.result, AgentResult):
                all_attachments.extend(node.result.attachments)

        return FusedResult(
            success=len(failed) == 0,
            content=merged,
            attachments=all_attachments,
            metadata=self._aggregate_token_usage(results),
            partial_results=[
                {"action": n.action, "status": n.status.value}
                for n in results
            ] + [
                {"action": n.action, "status": n.status.value, "error": n.error}
                for n in failed
            ],
        )

    async def _llm_merge(self, parts: list[str]) -> str:
        """使用 LLM 合并多个并行结果"""
        system_prompt = (
            "你是结果聚合器。将以下多个并行任务的结果合并为一份连贯的输出。"
            "要求：去重、逻辑连贯、结构清晰。"
        )
        user_prompt = "请合并以下结果：\n\n" + "\n\n---\n\n".join(parts)

        model_id = await self.model_router.select("merge")
        response = await self.model_router.call(
            model_id,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
        )
        return response["content"]

    # ===================================================================
    # 串行链结果
    # ===================================================================

    def _chain_result(self, results: list, failed: list) -> FusedResult:
        """
        串行链：取最终阶段结果 + 各阶段执行摘要

        输出格式：
        ## 执行摘要
        - ✅ stage_0: 需求分析: 成功 (2.3s)
        - ✅ stage_1: 架构设计: 成功 (5.1s)
        - ❌ stage_2: 代码实现: 超时
        ---
        [最终阶段输出内容]
        """
        final_node = results[-1]
        final_result = final_node.result
        final_content = (
            final_result.content
            if isinstance(final_result, AgentResult)
            else str(final_result)
        )

        # 构建执行摘要
        summary = "## 执行摘要\n"
        for node in results:
            duration = node.duration_seconds
            duration_str = f" ({duration:.1f}s)" if duration else ""
            summary += f"- ✅ {node.node_id}: {node.action}: 成功{duration_str}\n"

        for n in failed:
            summary += f"- ❌ {n.node_id}: {n.action}: {n.error or '失败'}\n"

        # 聚合 attachments
        all_attachments = []
        for node in results:
            if isinstance(node.result, AgentResult):
                all_attachments.extend(node.result.attachments)

        return FusedResult(
            success=len(failed) == 0,
            content=summary + "\n\n---\n\n" + final_content,
            attachments=all_attachments,
            metadata=self._aggregate_token_usage(results),
            partial_results=[
                {
                    "action": n.action,
                    "status": n.status.value,
                    "duration": n.duration_seconds,
                }
                for n in results
            ] + [
                {
                    "action": n.action,
                    "status": n.status.value,
                    "error": n.error,
                }
                for n in failed
            ],
        )

    # ===================================================================
    # 辅助方法
    # ===================================================================

    def _aggregate_token_usage(self, nodes: list) -> dict:
        """聚合各节点的 Token 用量"""
        total_prompt = 0
        total_completion = 0

        for node in nodes:
            if isinstance(node.result, AgentResult):
                usage = node.result.token_usage
                total_prompt += usage.get("prompt", 0)
                total_completion += usage.get("completion", 0)

        return {
            "token_usage": {
                "prompt": total_prompt,
                "completion": total_completion,
                "total": total_prompt + total_completion,
            },
        }
