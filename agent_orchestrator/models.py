"""
models.py — Agent 编排层核心数据结构

定义编排模式、任务状态、Agent 规格、任务节点、编排计划、聚合结果
等基础数据模型，供 PlanBuilder / TaskManager / ResultFuser / ErrorHandler 共用。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any


class OrchestrationMode(Enum):
    """编排模式枚举"""
    SEQUENTIAL = "sequential"           # 串行链
    PARALLEL_FANOUT = "fanout"          # 并行扇出
    CONDITIONAL = "conditional"         # 条件分支
    HUMAN_APPROVAL = "human_approval"   # 人工审批
    SINGLE = "single"                    # 单 Agent 直接执行


class TaskStatus(Enum):
    """任务状态枚举"""
    PENDING = "pending"
    RUNNING = "running"
    WAITING = "waiting"                 # 等待人工审批
    SUCCESS = "success"
    FAILED = "failed"
    CANCELLED = "cancelled"
    TIMEOUT = "timeout"


@dataclass
class AgentSpec:
    """
    Agent 注册信息

    描述一个 Specialist Agent 的能力、工具、并发限制等元数据。
    由 AgentRegistry 统一管理。
    """
    agent_id: str
    name: str
    description: str
    capabilities: list[str]            # 如 ["code_gen", "code_review", "bug_fix"]
    tools: list[str]                   # 如 ["python_sandbox", "git", "docker"]
    max_concurrent: int = 3            # 最大并发任务数
    timeout_seconds: int = 120         # 单任务超时（秒）
    model_preference: str = "auto"     # 首选模型
    priority: int = 5                  # 优先级（1-10，越高越优先）


@dataclass
class TaskNode:
    """
    编排图中的单个任务节点

    每个节点对应一个 Agent 要执行的具体动作，
    通过 depends_on 字段构成 DAG（有向无环图）。
    """
    node_id: str
    agent_id: str                      # 分配给哪个 Agent
    action: str                        # 具体动作描述
    params: dict = field(default_factory=dict)
    depends_on: list[str] = field(default_factory=list)   # 依赖的 node_id 列表
    mode: OrchestrationMode = OrchestrationMode.SINGLE
    status: TaskStatus = TaskStatus.PENDING
    result: Any = None                  # Agent 执行结果
    error: str | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None
    token_usage: dict = field(default_factory=dict)       # {"prompt": 100, "completion": 200}

    def mark_running(self) -> None:
        """标记为运行中"""
        self.status = TaskStatus.RUNNING
        self.started_at = datetime.utcnow()

    def mark_success(self, result: Any) -> None:
        """标记为成功"""
        self.status = TaskStatus.SUCCESS
        self.result = result
        self.completed_at = datetime.utcnow()

    def mark_failed(self, error: str) -> None:
        """标记为失败"""
        self.status = TaskStatus.FAILED
        self.error = error
        self.completed_at = datetime.utcnow()

    @property
    def duration_seconds(self) -> float | None:
        """执行耗时（秒），未完成返回 None"""
        if self.started_at and self.completed_at:
            return (self.completed_at - self.started_at).total_seconds()
        return None


@dataclass
class OrchestrationPlan:
    """
    编排执行计划

    由 PlanBuilder 生成，包含一组 TaskNode 构成的 DAG，
    描述了完整的任务编排方案，交由 TaskManager 执行。
    """
    plan_id: str
    mode: OrchestrationMode
    nodes: list[TaskNode]
    user_id: str
    session_id: str
    total_budget_tokens: int = 50000   # 整体 Token 预算
    timeout_seconds: int = 300         # 整体超时（秒）
    created_at: datetime = field(default_factory=datetime.utcnow)

    @property
    def node_map(self) -> dict[str, TaskNode]:
        """node_id → TaskNode 的快速查找表"""
        return {n.node_id: n for n in self.nodes}

    @property
    def all_done(self) -> bool:
        """是否所有节点都已到达终态"""
        terminal = {TaskStatus.SUCCESS, TaskStatus.FAILED, TaskStatus.CANCELLED, TaskStatus.TIMEOUT}
        return all(n.status in terminal for n in self.nodes)


@dataclass
class FusedResult:
    """
    聚合后的最终结果

    由 ResultFuser 生成，包含编排计划执行后的最终输出内容、
    附件、元数据和各子任务的执行情况。
    """
    success: bool
    content: str                                    # 最终输出内容
    attachments: list[dict] = field(default_factory=list)   # 文件/图片等附件
    metadata: dict = field(default_factory=dict)            # Token 用量、执行时间等
    partial_results: list[dict] = field(default_factory=list)  # 各子任务结果摘要

    def to_dict(self) -> dict:
        """转换为字典（便于序列化）"""
        return {
            "success": self.success,
            "content": self.content,
            "attachments": self.attachments,
            "metadata": self.metadata,
            "partial_results": self.partial_results,
        }


@dataclass
class AgentResult:
    """
    Agent 执行结果的标准化容器

    所有 Specialist Agent 的 execute() 方法都应返回此类型，
    供 TaskManager 和 ResultFuser 统一处理。
    """
    content: str                                    # Agent 输出的文本内容
    token_usage: dict = field(default_factory=dict)  # {"prompt": N, "completion": M}
    attachments: list[dict] = field(default_factory=list)
    metadata: dict = field(default_factory=dict)

    def get(self, key: str, default: Any = None) -> Any:
        """便捷取值：优先 metadata，再取属性"""
        if key in self.metadata:
            return self.metadata[key]
        return getattr(self, key, default)
