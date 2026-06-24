"""
task_manager.py — TaskManager 任务管理器

管理编排计划的执行生命周期：
  - SINGLE：单任务直接执行
  - SEQUENTIAL：DAG 拓扑排序后依次执行
  - PARALLEL_FANOUT：无依赖节点并行执行，有依赖节点等待前序完成
  - HUMAN_APPROVAL：预检 → 人工审批 → 执行

特性：
  - asyncio 异步执行
  - 超时处理（整体 + 单节点）
  - 取消机制
  - 拓扑排序保证 DAG 正确执行顺序
  - 人工审批 webhook 集成
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import datetime
from typing import Any, Callable

from .models import (
    AgentResult,
    FusedResult,
    OrchestrationMode,
    OrchestrationPlan,
    TaskNode,
    TaskStatus,
)


# ===========================================================================
# 超时上下文管理器（兼容 Python 3.11+ 的 asyncio.timeout）
# ===========================================================================

class _TimeoutContext:
    """
    asyncio 超时上下文管理器

    Python 3.11+ 可直接用 asyncio.timeout()，
    此处提供兼容性封装。
    """

    def __init__(self, seconds: int | float) -> None:
        self.seconds = seconds
        self._task: asyncio.Task | None = None

    async def __aenter__(self) -> "_TimeoutContext":
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> bool:
        return False


async def _run_with_timeout(coro: Any, timeout: float) -> Any:
    """
    运行协程并设定超时

    使用 asyncio.wait_for 实现超时控制。
    """
    return await asyncio.wait_for(coro, timeout=timeout)


# ===========================================================================
# 审批回调类型
# ===========================================================================

ApprovalCallback = Callable[[str, dict], "asyncio.Future"]
"""审批回调函数类型：(plan_id, approval_msg) → Future[decision]"""


# ===========================================================================
# TaskManager
# ===========================================================================

class TaskManager:
    """
    管理编排计划的执行生命周期

    支持四种模式的异步执行 + 超时处理 + 取消 + 人工审批集成。
    """

    def __init__(
        self,
        agent_registry: Any,
        model_router: Any,
        tool_engine: Any,
        approval_callback: ApprovalCallback | None = None,
    ) -> None:
        """
        Args:
            agent_registry: AgentRegistry 实例（提供 get() 获取 Agent）
            model_router: ModelRouter 实例（提供 select() 选择模型）
            tool_engine: ToolEngine 实例（供 Agent 内部使用）
            approval_callback: 人工审批回调函数（plan_id, msg → Future[decision]）
        """
        self.registry = agent_registry
        self.model_router = model_router
        self.tool_engine = tool_engine
        self.approval_callback = approval_callback
        self._running_tasks: dict[str, asyncio.Task] = {}
        # 审批等待队列：plan_id → Future，外部调用 resolve_approval() 解析
        self._pending_approvals: dict[str, asyncio.Future] = {}

    async def execute(self, plan: OrchestrationPlan) -> FusedResult:
        """
        根据 plan.mode 分派到对应的执行器

        Args:
            plan: OrchestrationPlan 编排计划

        Returns:
            FusedResult 聚合结果
        """
        try:
            if plan.mode == OrchestrationMode.SINGLE:
                result = await self._exec_single(plan)
            elif plan.mode == OrchestrationMode.SEQUENTIAL:
                result = await self._exec_sequential(plan)
            elif plan.mode == OrchestrationMode.PARALLEL_FANOUT:
                result = await self._exec_fanout(plan)
            elif plan.mode == OrchestrationMode.HUMAN_APPROVAL:
                result = await self._exec_with_approval(plan)
            else:
                result = self._build_error_result(f"不支持的编排模式: {plan.mode}")
        except asyncio.CancelledError:
            result = self._build_error_result("任务被取消")
        except Exception as e:
            result = self._build_error_result(f"执行异常: {e}")

        # 后处理：写入记忆 + 记录 Token 用量
        await self._post_process(plan, result)
        return result

    # ===================================================================
    # SINGLE 模式
    # ===================================================================

    async def _exec_single(self, plan: OrchestrationPlan) -> FusedResult:
        """单任务直接执行"""
        node = plan.nodes[0]
        agent = self.registry.get(node.agent_id)

        try:
            node.mark_running()

            result = await _run_with_timeout(
                agent.execute(
                    action=node.action,
                    params=node.params,
                    model=await self.model_router.select(node.action),
                ),
                timeout=plan.timeout_seconds,
            )

            node.mark_success(result)

            return FusedResult(
                success=True,
                content=result.content,
                attachments=result.attachments,
                metadata={
                    "token_usage": result.token_usage,
                    "duration": node.duration_seconds,
                },
            )

        except asyncio.TimeoutError:
            node.status = TaskStatus.TIMEOUT
            node.completed_at = datetime.utcnow()
            return self._build_error_result(
                f"任务执行超时（{plan.timeout_seconds}s）",
                partial=node,
            )
        except Exception as e:
            node.mark_failed(str(e))
            return self._build_error_result(f"任务执行失败: {e}", partial=node)

    # ===================================================================
    # SEQUENTIAL 模式
    # ===================================================================

    async def _exec_sequential(self, plan: OrchestrationPlan) -> FusedResult:
        """
        DAG 拓扑排序后依次执行

        每个节点执行前检查其依赖是否全部成功，
        并将上游结果传递给当前节点。
        """
        node_map = plan.node_map
        results: list[AgentResult] = []

        # 拓扑排序
        ordered = self._topological_sort(plan.nodes)

        for node in ordered:
            # 检查依赖是否全部成功
            for dep_id in node.depends_on:
                dep = node_map[dep_id]
                if dep.status == TaskStatus.FAILED:
                    node.status = TaskStatus.CANCELLED
                    node.error = f"依赖节点 {dep_id} 失败，取消执行"
                    return self._build_partial_error(
                        results, node.error, plan
                    )

            # 传递上游结果
            upstream_results = {
                dep_id: node_map[dep_id].result
                for dep_id in node.depends_on
                if node_map[dep_id].status == TaskStatus.SUCCESS
            }
            node.params["upstream_results"] = upstream_results

            # 执行当前节点
            agent = self.registry.get(node.agent_id)
            node_timeout = plan.timeout_seconds  # 使用整体超时

            try:
                node.mark_running()
                result = await _run_with_timeout(
                    agent.execute(
                        action=node.action,
                        params=node.params,
                        model=await self.model_router.select(node.action),
                    ),
                    timeout=node_timeout,
                )
                node.mark_success(result)
                results.append(result)

            except asyncio.TimeoutError:
                node.status = TaskStatus.TIMEOUT
                node.completed_at = datetime.utcnow()
                return self._build_partial_error(
                    results, f"阶段 {node.action} 超时", plan
                )
            except Exception as e:
                node.mark_failed(str(e))
                return self._build_partial_error(
                    results, f"阶段 {node.action} 失败: {e}", plan
                )

        # 取最后一个阶段的结果作为最终内容
        final_content = results[-1].content if results else ""
        all_attachments = [a for r in results for a in r.attachments]

        return FusedResult(
            success=True,
            content=final_content,
            attachments=all_attachments,
            metadata=self._aggregate_metadata(results),
            partial_results=[
                {"action": n.action, "status": n.status.value,
                 "duration": n.duration_seconds}
                for n in plan.nodes
            ],
        )

    # ===================================================================
    # PARALLEL_FANOUT 模式
    # ===================================================================

    async def _exec_fanout(self, plan: OrchestrationPlan) -> FusedResult:
        """
        无依赖节点并行执行，有依赖节点等待前序完成

        算法：
        1. 找出所有无依赖的 pending 节点，并行执行
        2. 执行完成后，检查是否有新节点可以执行（依赖全部满足）
        3. 重复直到所有节点完成
        """
        node_map = plan.node_map
        results: dict[str, AgentResult] = {}
        pending = [n for n in plan.nodes if not n.depends_on]

        while pending:
            # 并行执行所有待执行节点
            tasks = []
            for node in pending:
                agent = self.registry.get(node.agent_id)
                tasks.append(self._exec_node_safe(agent, node, plan))

            done_results = await asyncio.gather(*tasks, return_exceptions=True)

            # 处理结果 + 解锁下游节点
            newly_ready: list[TaskNode] = []
            for node, result in zip(pending, done_results):
                if isinstance(result, Exception):
                    node.mark_failed(str(result))
                else:
                    node.mark_success(result)
                    results[node.node_id] = result

                # 检查是否有新节点可以执行
                for other in plan.nodes:
                    if other.status == TaskStatus.PENDING:
                        if all(
                            node_map[d].status == TaskStatus.SUCCESS
                            for d in other.depends_on
                        ):
                            newly_ready.append(other)

            # 避免重复添加
            pending = list({n.node_id: n for n in newly_ready}.values())

        # 判断整体是否成功
        all_success = all(
            n.status == TaskStatus.SUCCESS for n in plan.nodes
        )

        # 合并内容
        content = self._merge_fanout_results(results, plan)

        return FusedResult(
            success=all_success,
            content=content,
            partial_results=[
                {"action": n.action, "status": n.status.value,
                 "error": n.error}
                for n in plan.nodes
            ],
        )

    async def _exec_node_safe(self, agent: Any, node: TaskNode,
                              plan: OrchestrationPlan) -> AgentResult:
        """安全执行单个节点（带超时），异常向上抛出"""
        node.mark_running()
        result = await _run_with_timeout(
            agent.execute(
                action=node.action,
                params=node.params,
                model=await self.model_router.select(node.action),
            ),
            timeout=plan.timeout_seconds,
        )
        return result

    def _merge_fanout_results(self, results: dict[str, AgentResult],
                              plan: OrchestrationPlan) -> str:
        """合并并行扇出的各分片结果"""
        if not results:
            return "❌ 所有子任务均失败"

        parts = []
        for node in plan.nodes:
            if node.status == TaskStatus.SUCCESS and node.result:
                parts.append(f"### {node.action}（{node.node_id}）\n{node.result.content}")

        # 如果有聚合节点，使用聚合节点结果
        for node in plan.nodes:
            if node.action == "research.aggregate" and node.status == TaskStatus.SUCCESS:
                return node.result.content

        return "\n\n---\n\n".join(parts)

    # ===================================================================
    # HUMAN_APPROVAL 模式
    # ===================================================================

    async def _exec_with_approval(self, plan: OrchestrationPlan) -> FusedResult:
        """
        先预检 → 发送审批请求 → 等待人工确认 → 执行

        流程：
        1. 执行 precheck 节点（自动）
        2. 如果预检不安全 → 直接返回
        3. 发送审批请求到用户通道
        4. 等待人工审批（最长 1 小时）
        5. 审批通过 → 执行 execute 节点
        6. 审批拒绝/超时 → 取消
        """

        # Step 1: 预检
        precheck_node = plan.nodes[0]
        agent = self.registry.get(precheck_node.agent_id)
        precheck_node.mark_running()

        try:
            precheck_result = await _run_with_timeout(
                agent.execute(
                    action="precheck",
                    params=precheck_node.params,
                    model=await self.model_router.select("precheck"),
                ),
                timeout=plan.timeout_seconds,
            )
            precheck_node.mark_success(precheck_result)
        except Exception as e:
            precheck_node.mark_failed(str(e))
            return self._build_error_result(f"预检失败: {e}")

        # Step 2: 检查预检结果是否安全
        # precheck_result.content 可能是 JSON 或纯文本
        safe, reason = self._parse_precheck_result(precheck_result.content)
        if not safe:
            return FusedResult(
                success=False,
                content=f"⚠️ 预检未通过：{reason}",
                partial_results=[
                    {"action": "precheck", "status": "success",
                     "safe": False, "reason": reason}
                ],
            )

        # Step 3: 发送审批请求
        exec_node = plan.nodes[1]
        exec_node.status = TaskStatus.WAITING  # 标记为等待审批

        approval_msg = {
            "type": "approval_request",
            "plan_id": plan.plan_id,
            "action": exec_node.action,
            "params": exec_node.params,
            "precheck_summary": precheck_result.content[:200],
            "options": ["approve", "reject", "modify"],
        }

        # 通过回调发送审批通知
        if self.approval_callback:
            await self.approval_callback(plan.plan_id, approval_msg)

        # Step 4: 等待人工审批
        decision = await self._wait_for_approval(plan.plan_id, timeout=3600)

        if decision is None:
            # 超时
            exec_node.status = TaskStatus.CANCELLED
            return FusedResult(
                success=False,
                content="⏰ 审批超时，操作已取消",
                partial_results=[
                    {"action": "precheck", "status": "success"},
                    {"action": "execute", "status": "cancelled"},
                ],
            )

        if decision.get("decision") == "reject":
            exec_node.status = TaskStatus.CANCELLED
            return FusedResult(
                success=False,
                content="❌ 用户拒绝了操作",
                partial_results=[
                    {"action": "precheck", "status": "success"},
                    {"action": "execute", "status": "cancelled"},
                ],
            )

        # Step 5: 审批通过，执行
        # 如果用户修改了参数，合并修改
        modifications = decision.get("modifications", {})
        exec_node.params.update(modifications)

        try:
            exec_node.mark_running()
            result = await _run_with_timeout(
                agent.execute(
                    action=exec_node.action,
                    params=exec_node.params,
                    model=await self.model_router.select(exec_node.action),
                ),
                timeout=plan.timeout_seconds,
            )
            exec_node.mark_success(result)

            return FusedResult(
                success=True,
                content=result.content,
                attachments=result.attachments,
                metadata={"token_usage": result.token_usage},
                partial_results=[
                    {"action": "precheck", "status": "success"},
                    {"action": "execute", "status": "success"},
                ],
            )

        except asyncio.TimeoutError:
            exec_node.status = TaskStatus.TIMEOUT
            exec_node.completed_at = datetime.utcnow()
            return self._build_error_result("执行超时")
        except Exception as e:
            exec_node.mark_failed(str(e))
            return self._build_error_result(f"执行失败: {e}")

    def _parse_precheck_result(self, content: str) -> tuple[bool, str]:
        """
        解析预检结果

        Returns:
            (safe, reason)
        """
        import json as _json

        # 尝试解析 JSON
        try:
            data = _json.loads(content)
            return data.get("safe", True), data.get("reason", "")
        except _json.JSONDecodeError:
            # 非 JSON，默认安全
            return True, ""

    async def _wait_for_approval(self, plan_id: str,
                                  timeout: int = 3600) -> dict | None:
        """
        等待人工审批

        通过 _pending_approvals 中的 Future 实现：
        - 外部调用 resolve_approval(plan_id, decision) 解析
        - 超时返回 None
        """
        future: asyncio.Future = asyncio.get_event_loop().create_future()
        self._pending_approvals[plan_id] = future

        try:
            decision = await _run_with_timeout(future, timeout=timeout)
            return decision
        except asyncio.TimeoutError:
            return None
        finally:
            self._pending_approvals.pop(plan_id, None)

    def resolve_approval(self, plan_id: str, decision: dict) -> bool:
        """
        外部调用：解析审批等待

        Args:
            plan_id: 编排计划 ID
            decision: {"decision": "approve"/"reject", "modifications": {...}}

        Returns:
            bool 是否成功解析
        """
        future = self._pending_approvals.get(plan_id)
        if future is None or future.done():
            return False
        future.set_result(decision)
        return True

    # ===================================================================
    # 拓扑排序
    # ===================================================================

    def _topological_sort(self, nodes: list[TaskNode]) -> list[TaskNode]:
        """
        Kahn 算法拓扑排序

        确保被依赖的节点先执行。
        """
        node_map = {n.node_id: n for n in nodes}
        in_degree = {n.node_id: len(n.depends_on) for n in nodes}
        # 邻接表：dep_id → 依赖它的 node_id 列表
        adj: dict[str, list[str]] = {n.node_id: [] for n in nodes}
        for n in nodes:
            for dep_id in n.depends_on:
                if dep_id in adj:
                    adj[dep_id].append(n.node_id)

        # 入度为 0 的节点入队
        queue = [nid for nid, deg in in_degree.items() if deg == 0]
        result: list[TaskNode] = []

        while queue:
            nid = queue.pop(0)
            result.append(node_map[nid])
            for downstream in adj[nid]:
                in_degree[downstream] -= 1
                if in_degree[downstream] == 0:
                    queue.append(downstream)

        # 检查是否有环
        if len(result) != len(nodes):
            raise ValueError("DAG 中存在循环依赖，无法拓扑排序")

        return result

    # ===================================================================
    # 辅助方法
    # ===================================================================

    def _build_error_result(self, msg: str,
                            partial: TaskNode | None = None) -> FusedResult:
        """构建错误结果"""
        partial_list = []
        if partial:
            partial_list.append({
                "action": partial.action,
                "status": partial.status.value,
                "error": partial.error,
            })
        return FusedResult(
            success=False,
            content=f"❌ {msg}",
            partial_results=partial_list,
        )

    def _build_partial_error(self, results: list[AgentResult],
                             error: str, plan: OrchestrationPlan) -> FusedResult:
        """构建部分成功的错误结果（串行链中途中断）"""
        return FusedResult(
            success=False,
            content=f"⚠️ {error}\n\n已完成阶段：\n"
                    + "\n".join(
                        f"- ✅ {r.content[:50]}..." for r in results
                    ),
            attachments=[a for r in results for a in r.attachments],
            metadata=self._aggregate_metadata(results),
            partial_results=[
                {"action": n.action, "status": n.status.value,
                 "error": n.error}
                for n in plan.nodes
            ],
        )

    def _aggregate_metadata(self, results: list[AgentResult]) -> dict:
        """聚合多个 AgentResult 的元数据"""
        total_prompt = sum(r.token_usage.get("prompt", 0) for r in results)
        total_completion = sum(r.token_usage.get("completion", 0) for r in results)
        return {
            "token_usage": {
                "prompt": total_prompt,
                "completion": total_completion,
                "total": total_prompt + total_completion,
            },
            "stages_completed": len(results),
        }

    async def _post_process(self, plan: OrchestrationPlan,
                            result: FusedResult) -> None:
        """
        后处理：写入记忆 + 记录可观测指标

        实际生产中可接入：
        - 记忆系统（写入对话历史）
        - 监控系统（Prometheus 埋点）
        - 成本追踪（Token 用量统计）
        """
        # 此处为占位实现
        pass

    # ===================================================================
    # 取消机制
    # ===================================================================

    def cancel(self, plan_id: str) -> bool:
        """
        取消正在执行的计划

        Args:
            plan_id: 要取消的编排计划 ID

        Returns:
            bool 是否成功取消
        """
        # 如果有对应的 asyncio.Task，取消它
        task = self._running_tasks.get(plan_id)
        if task and not task.done():
            task.cancel()
            return True
        return False
