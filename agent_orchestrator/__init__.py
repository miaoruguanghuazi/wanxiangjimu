"""
agent_orchestrator — Agent 编排层

万象积木的中央调度子系统，负责：
  1. 接收 NLU 输出的意图结果
  2. 判断编排模式（串行/并行/条件/审批）
  3. 选派 Specialist Agent
  4. 管理执行生命周期（启动/监控/取消/超时）
  5. 聚合结果 + 错误处理
  6. 可观测埋点

核心组件：
  - PlanBuilder    ：任务规划器，意图 → OrchestrationPlan
  - TaskManager    ：任务管理器，执行编排计划
  - ResultFuser    ：结果聚合器，合并多 Agent 结果
  - ErrorHandler   ：四级错误处理器
  - AgentRegistry  ：Agent 注册表
  - CodeAgent / DataAgent / ResearchAgent ：三个 Specialist Agent

用法示例：
    import asyncio
    from agent_orchestrator import (
        PlanBuilder, TaskManager, ResultFuser, ErrorHandler,
        AgentRegistry, ModelRouter, ToolEngine,
        CodeAgent, DataAgent, ResearchAgent,
        IntentResult,
    )

    async def main():
        # 1. 初始化组件
        registry = AgentRegistry()
        model_router = ModelRouter()
        tool_engine = ToolEngine()

        # 2. 注册 Agent 实例
        registry.register_instance("code_agent",
            CodeAgent(registry.get_spec("code_agent"), model_router, tool_engine))
        registry.register_instance("data_agent",
            DataAgent(registry.get_spec("data_agent"), model_router, tool_engine))
        registry.register_instance("research_agent",
            ResearchAgent(registry.get_spec("research_agent"), model_router, tool_engine))

        # 3. 创建管理器
        plan_builder = PlanBuilder()
        task_manager = TaskManager(registry, model_router, tool_engine)
        result_fuser = ResultFuser(model_router)

        # 4. 构建计划并执行
        intent = IntentResult(intent="tool.code", slots={"requirement": "写一个快速排序"})
        plan = plan_builder.build(intent, {"user_id": "u1", "session_id": "s1"})
        result = await task_manager.execute(plan)

        print(result.content)

    asyncio.run(main())
"""

from .models import (
    AgentResult,
    AgentSpec,
    FusedResult,
    OrchestrationMode,
    OrchestrationPlan,
    TaskNode,
    TaskStatus,
)
from .agents import (
    AGENT_REGISTRY,
    AgentRegistry,
    BaseAgent,
    CodeAgent,
    DataAgent,
    ResearchAgent,
    ModelRouter,
    ToolEngine,
)
from .plan_builder import PlanBuilder, IntentResult
from .task_manager import TaskManager
from .result_fuser import ResultFuser
from .error_handler import (
    CircuitBreaker,
    CircuitState,
    ErrorHandler,
    ErrorLevel,
    AgentErrorHandler,
    PlanErrorHandler,
    SystemErrorHandler,
    ToolErrorHandler,
)

__all__ = [
    # 核心数据模型
    "OrchestrationMode",
    "TaskStatus",
    "AgentSpec",
    "TaskNode",
    "OrchestrationPlan",
    "FusedResult",
    "AgentResult",
    # Agent 注册表 + 实现
    "AGENT_REGISTRY",
    "AgentRegistry",
    "BaseAgent",
    "CodeAgent",
    "DataAgent",
    "ResearchAgent",
    "ModelRouter",
    "ToolEngine",
    # 任务规划
    "PlanBuilder",
    "IntentResult",
    # 任务执行
    "TaskManager",
    # 结果聚合
    "ResultFuser",
    # 错误处理
    "ErrorHandler",
    "ErrorLevel",
    "CircuitBreaker",
    "CircuitState",
    "ToolErrorHandler",
    "AgentErrorHandler",
    "PlanErrorHandler",
    "SystemErrorHandler",
]

__version__ = "1.0.0"
