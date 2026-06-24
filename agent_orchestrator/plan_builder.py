"""
plan_builder.py — PlanBuilder 任务规划器

根据 IntentResult + 上下文生成 OrchestrationPlan。
支持 4 种编排模式：
  - SINGLE：单 Agent 直接执行
  - SEQUENTIAL：串行链（工程工作流）
  - PARALLEL_FANOUT：并行扇出（多源调研）
  - HUMAN_APPROVAL：人工审批（高风险操作）
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from .models import (
    OrchestrationMode,
    OrchestrationPlan,
    TaskNode,
)


# ===========================================================================
# 轻量 IntentResult 占位（实际由 NLU 层产出）
# ===========================================================================

class IntentResult:
    """
    NLU 层输出的意图识别结果（轻量占位）

    实际实现中应替换为 NLU 模块的标准产出。
    """

    def __init__(self, intent: str, slots: dict | None = None,
                 confidence: float = 1.0) -> None:
        self.intent = intent          # 如 "tool.code", "research.multi_source"
        self.slots = slots or {}      # 意图槽位参数
        self.confidence = confidence


# ===========================================================================
# PlanBuilder
# ===========================================================================

class PlanBuilder:
    """
    根据 IntentResult + 上下文 → 生成 OrchestrationPlan

    规划策略：
    - 简单意图 → SINGLE（单 Agent 直接执行）
    - 复杂意图 → 根据依赖关系自动选择编排模式
    - 用户显式要求 → 尊重用户指定的模式
    """

    # 意图 → 默认编排模式 的映射
    INTENT_MODE_MAP: dict[str, OrchestrationMode] = {
        "chat.general":           OrchestrationMode.SINGLE,
        "chat.question":          OrchestrationMode.SINGLE,
        "chat.summary":           OrchestrationMode.SINGLE,
        "chat.analysis":          OrchestrationMode.SINGLE,
        "tool.search":            OrchestrationMode.SINGLE,
        "tool.code":              OrchestrationMode.SINGLE,
        "tool.file":              OrchestrationMode.SINGLE,
        "media.image_gen":        OrchestrationMode.SINGLE,
        "media.image_understand": OrchestrationMode.SINGLE,
        "workflow.engineering":   OrchestrationMode.SEQUENTIAL,
        "research.multi_source":  OrchestrationMode.PARALLEL_FANOUT,
        "workflow.destructive":   OrchestrationMode.HUMAN_APPROVAL,
    }

    # 意图 → Agent 分配 的映射
    INTENT_AGENT_MAP: dict[str, str] = {
        "tool.code":              "code_agent",
        "workflow.engineering":   "code_agent",
        "tool.data_analysis":     "data_agent",
        "tool.visualization":     "data_agent",
        "workflow.deploy":        "ops_agent",
        "workflow.monitor":       "ops_agent",
        "media.image_gen":        "design_agent",
        "media.video_gen":        "design_agent",
        "research.multi_source":  "research_agent",
        "research.compare":       "research_agent",
    }

    def build(self, intent_result: IntentResult, context: dict) -> OrchestrationPlan:
        """
        构建 OrchestrationPlan

        Args:
            intent_result: NLU 输出的意图结果
            context: 上下文（需包含 user_id, session_id）

        Returns:
            OrchestrationPlan 可执行编排计划
        """
        intent = intent_result.intent
        mode = self.INTENT_MODE_MAP.get(intent, OrchestrationMode.SINGLE)
        agent_id = self.INTENT_AGENT_MAP.get(intent, "general_agent")

        # 用户可显式覆盖编排模式
        if "force_mode" in context:
            mode = OrchestrationMode(context["force_mode"])

        if mode == OrchestrationMode.SINGLE:
            return self._build_single(agent_id, intent_result, context)
        elif mode == OrchestrationMode.SEQUENTIAL:
            return self._build_sequential(intent_result, context)
        elif mode == OrchestrationMode.PARALLEL_FANOUT:
            return self._build_fanout(intent_result, context)
        elif mode == OrchestrationMode.HUMAN_APPROVAL:
            return self._build_approval(agent_id, intent_result, context)
        else:
            # 兜底：SINGLE
            return self._build_single(agent_id, intent_result, context)

    # -----------------------------------------------------------------------
    # SINGLE 模式
    # -----------------------------------------------------------------------

    def _build_single(self, agent_id: str, intent_result: IntentResult,
                      context: dict) -> OrchestrationPlan:
        """单 Agent 直接执行"""
        return OrchestrationPlan(
            plan_id=self._gen_id(),
            mode=OrchestrationMode.SINGLE,
            nodes=[TaskNode(
                node_id="task_0",
                agent_id=agent_id,
                action=intent_result.intent,
                params={**intent_result.slots, **context},
            )],
            user_id=context["user_id"],
            session_id=context["session_id"],
            timeout_seconds=self._get_agent_timeout(agent_id),
        )

    # -----------------------------------------------------------------------
    # SEQUENTIAL 模式
    # -----------------------------------------------------------------------

    def _build_sequential(self, intent_result: IntentResult,
                          context: dict) -> OrchestrationPlan:
        """
        工程工作流串行链

        根据意图槽位选择需要的阶段，各阶段顺序依赖。
        """
        stages = self._select_stages(intent_result.slots)
        nodes: list[TaskNode] = []
        prev_id: str | None = None

        for i, stage in enumerate(stages):
            node = TaskNode(
                node_id=f"stage_{i}",
                agent_id="code_agent",
                action=stage["action"],
                params=stage.get("params", {}),
                depends_on=[prev_id] if prev_id else [],
            )
            nodes.append(node)
            prev_id = node.node_id

        return OrchestrationPlan(
            plan_id=self._gen_id(),
            mode=OrchestrationMode.SEQUENTIAL,
            nodes=nodes,
            user_id=context["user_id"],
            session_id=context["session_id"],
            timeout_seconds=600,  # 工程任务 10 分钟超时
        )

    def _select_stages(self, slots: dict) -> list[dict]:
        """
        根据意图槽位选择工程工作流的阶段

        完整工程链路：
        1. requirements_analysis  — 需求分析
        2. architecture_design    — 架构设计
        3. code_implementation    — 代码实现
        4. code_review            — 代码审查
        5. test_generation        — 测试生成
        6. deployment             — 部署
        """
        all_stages = [
            {"action": "requirements_analysis", "params": {}},
            {"action": "architecture_design", "params": {}},
            {"action": "code_implementation", "params": {}},
            {"action": "code_review", "params": {}},
            {"action": "test_generation", "params": {}},
            {"action": "deployment", "params": {}},
        ]

        # 如果用户指定了起始/结束阶段，裁剪
        start = slots.get("start_stage", 0)
        end = slots.get("end_stage", len(all_stages))

        # 如果指定了跳过某些阶段
        skip = set(slots.get("skip_stages", []))
        selected = [
            stage for i, stage in enumerate(all_stages)
            if start <= i < end and stage["action"] not in skip
        ]

        return selected if selected else all_stages[:3]  # 默认至少前三阶段

    # -----------------------------------------------------------------------
    # PARALLEL_FANOUT 模式
    # -----------------------------------------------------------------------

    def _build_fanout(self, intent_result: IntentResult,
                      context: dict) -> OrchestrationPlan:
        """
        并行扇出：独立子任务并行执行

        例如："分析这 10 个竞品" → 10 个并行调研 + 1 个聚合节点
        """
        items = intent_result.slots.get("items", [])
        if not items:
            # 无 items 时，将整体查询作为单一任务
            items = [intent_result.slots.get("query", "默认主题")]

        nodes: list[TaskNode] = []

        # 扇出节点：每个 item 一个并行任务
        for i, item in enumerate(items):
            nodes.append(TaskNode(
                node_id=f"fan_{i}",
                agent_id="research_agent",
                action="research.single",
                params={"target": item},
                depends_on=[],  # 无依赖，全部并行
            ))

        # 聚合节点：依赖所有扇出节点
        nodes.append(TaskNode(
            node_id="aggregate",
            agent_id="research_agent",
            action="research.aggregate",
            params={"fan_count": len(items)},
            depends_on=[f"fan_{i}" for i in range(len(items))],
        ))

        return OrchestrationPlan(
            plan_id=self._gen_id(),
            mode=OrchestrationMode.PARALLEL_FANOUT,
            nodes=nodes,
            user_id=context["user_id"],
            session_id=context["session_id"],
            timeout_seconds=300,
        )

    # -----------------------------------------------------------------------
    # HUMAN_APPROVAL 模式
    # -----------------------------------------------------------------------

    def _build_approval(self, agent_id: str, intent_result: IntentResult,
                        context: dict) -> OrchestrationPlan:
        """
        高风险操作：先执行预检，等人工审批后再执行

        节点结构：
        1. precheck  — 预检（自动）
        2. execute   — 执行（需 precheck 通过 + 人工确认）
        """
        return OrchestrationPlan(
            plan_id=self._gen_id(),
            mode=OrchestrationMode.HUMAN_APPROVAL,
            nodes=[
                TaskNode(
                    node_id="precheck",
                    agent_id=agent_id,
                    action="precheck",
                    params={**intent_result.slots, **context},
                ),
                TaskNode(
                    node_id="execute",
                    agent_id=agent_id,
                    action="execute",
                    params={**intent_result.slots, **context},
                    depends_on=["precheck"],
                    # 实际执行需要 precheck 通过 + 人工确认
                ),
            ],
            user_id=context["user_id"],
            session_id=context["session_id"],
            timeout_seconds=3600,  # 审批节点 1 小时超时
        )

    # -----------------------------------------------------------------------
    # 辅助方法
    # -----------------------------------------------------------------------

    @staticmethod
    def _gen_id() -> str:
        """生成唯一 plan_id"""
        return f"plan_{uuid.uuid4().hex[:12]}"

    @staticmethod
    def _get_agent_timeout(agent_id: str) -> int:
        """获取 Agent 的默认超时时间"""
        # 与 AGENT_REGISTRY 中的 timeout_seconds 对应
        timeout_map = {
            "general_agent": 60,
            "code_agent": 180,
            "data_agent": 120,
            "ops_agent": 120,
            "design_agent": 180,
            "research_agent": 150,
        }
        return timeout_map.get(agent_id, 120)
