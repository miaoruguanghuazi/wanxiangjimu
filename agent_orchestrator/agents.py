"""
agents.py — Agent 注册表 + BaseAgent 基类 + 三个具体实现

包含：
  - AGENT_REGISTRY：预注册的 Agent 规格
  - AgentRegistry：运行时 Agent 注册/查询管理器
  - BaseAgent：所有 Specialist Agent 的抽象基类
  - CodeAgent：代码专家 Agent
  - DataAgent：数据专家 Agent
  - ResearchAgent：调研专家 Agent
"""

from __future__ import annotations

import json
import re
from abc import ABC, abstractmethod
from typing import Any

from .models import AgentSpec, AgentResult


# ===========================================================================
# 预注册 Agent 规格
# ===========================================================================

AGENT_REGISTRY: dict[str, AgentSpec] = {
    "general_agent": AgentSpec(
        agent_id="general_agent",
        name="通用助手",
        description="处理日常对话、问答、总结等通用任务",
        capabilities=["chat", "summary", "analysis", "translation"],
        tools=["web_search", "file_read", "memory_search"],
        timeout_seconds=60,
    ),
    "code_agent": AgentSpec(
        agent_id="code_agent",
        name="代码专家",
        description="代码生成、审查、修复、工程工作流",
        capabilities=["code_gen", "code_review", "bug_fix", "refactor", "test_gen"],
        tools=["python_sandbox", "git", "docker", "file_read", "file_write", "shell"],
        timeout_seconds=180,
    ),
    "data_agent": AgentSpec(
        agent_id="data_agent",
        name="数据专家",
        description="数据分析、可视化、ETL、报表生成",
        capabilities=["data_analysis", "visualization", "etl", "report_gen"],
        tools=["python_sandbox", "db_query", "spreadsheet", "file_read", "file_write"],
        timeout_seconds=120,
    ),
    "ops_agent": AgentSpec(
        agent_id="ops_agent",
        name="运维专家",
        description="部署、监控、告警响应、故障排查",
        capabilities=["deploy", "monitor", "incident_response", "log_analysis"],
        tools=["shell", "docker", "ci_cd", "web_search", "file_read"],
        timeout_seconds=120,
    ),
    "design_agent": AgentSpec(
        agent_id="design_agent",
        name="创意专家",
        description="图片/视频/3D/音乐生成与编辑",
        capabilities=["image_gen", "video_gen", "image_edit", "music_gen", "3d_gen"],
        tools=["sd_api", "tts", "video_engine", "file_write"],
        timeout_seconds=180,
    ),
    "research_agent": AgentSpec(
        agent_id="research_agent",
        name="调研专家",
        description="多源信息检索、对比分析、深度调研",
        capabilities=["web_research", "compare", "summarize_sources", "fact_check"],
        tools=["web_search", "web_scrape", "rag_search", "file_write"],
        timeout_seconds=150,
    ),
}


# ===========================================================================
# Agent 注册表管理器
# ===========================================================================

class AgentRegistry:
    """
    运行时 Agent 注册与查询管理器

    职责：
    - 维护 agent_id → AgentSpec 映射
    - 维护 agent_id → BaseAgent 实例 映射
    - 支持按能力查询 Agent
    """

    def __init__(self) -> None:
        self._specs: dict[str, AgentSpec] = dict(AGENT_REGISTRY)
        self._instances: dict[str, BaseAgent] = {}

    def register_spec(self, spec: AgentSpec) -> None:
        """注册或更新 Agent 规格"""
        self._specs[spec.agent_id] = spec

    def register_instance(self, agent_id: str, instance: BaseAgent) -> None:
        """注册 Agent 实例（绑定模型路由和工具引擎后）"""
        self._instances[agent_id] = instance

    def get_spec(self, agent_id: str) -> AgentSpec | None:
        """获取 Agent 规格"""
        return self._specs.get(agent_id)

    def get(self, agent_id: str) -> BaseAgent:
        """
        获取 Agent 实例。
        如果未注册实例则抛出 KeyError。
        """
        if agent_id not in self._instances:
            raise KeyError(f"Agent 实例未注册: {agent_id}，请先调用 register_instance()")
        return self._instances[agent_id]

    def find_by_capability(self, capability: str) -> list[str]:
        """按能力查询所有匹配的 agent_id"""
        return [
            spec.agent_id
            for spec in self._specs.values()
            if capability in spec.capabilities
        ]

    def list_all(self) -> list[AgentSpec]:
        """列出所有已注册的 Agent 规格"""
        return list(self._specs.values())


# ===========================================================================
# 模型路由 & 工具引擎的轻量协议（便于解耦，实际实现由外部注入）
# ===========================================================================

class ModelRouter:
    """
    模型路由器 — 通过 litellm 统一调用多个 LLM

    支持的模型 ID（litellm 格式）：
      - "deepseek/deepseek-chat"      通用对话
      - "deepseek/deepseek-coder"     代码专家
      - "doubao/ep-xxxxx"             豆包系列
      - "gpt-4o" / "gpt-3.5-turbo"   OpenAI

    路由规则：
      code_*         → deepseek-coder（如配置了 Key）
      research/*     → deepseek-chat（长上下文）
      data_*         → deepseek-chat
      默认            → deepseek-chat
    """

    # 模型 ID → litellm model 字符串
    _MODEL_MAP: dict[str, str] = {
        "code-model": "deepseek/deepseek-coder",
        "research-model": "deepseek/deepseek-chat",
        "general-model": "deepseek/deepseek-chat",
    }

    async def select(self, action: str) -> str:
        """根据 action 选择合适的模型 ID"""
        if "code" in action:
            return "code-model"
        if "research" in action or "search" in action:
            return "research-model"
        return "general-model"

    async def call(self, model_id: str, messages: list[dict],
                   tools: list | None = None) -> dict:
        """
        通过 litellm 调用 LLM

        Returns:
            {"content": str, "token_usage": {"prompt": int, "completion": int}}
        """
        import os
        from litellm import acompletion

        litellm_model = self._MODEL_MAP.get(model_id, "deepseek/deepseek-chat")

        # 如果没配 API Key，返回降级提示
        has_key = (
            (litellm_model.startswith("deepseek") and os.getenv("DEEPSEEK_API_KEY") and "你的" not in os.getenv("DEEPSEEK_API_KEY", ""))
            or (litellm_model.startswith("gpt") and os.getenv("OPENAI_API_KEY"))
            or (litellm_model.startswith("doubao") and os.getenv("DOUBAO_API_KEY") and "你的" not in os.getenv("DOUBAO_API_KEY", ""))
        )
        if not has_key:
            return {
                "content": f"⚠️ 模型 {litellm_model} 未配置有效的 API Key，请在 .env 文件中填入。",
                "token_usage": {"prompt": 0, "completion": 0},
            }

        kwargs: dict[str, Any] = {
            "model": litellm_model,
            "messages": messages,
            "temperature": 0.7,
        }
        if tools:
            kwargs["tools"] = tools

        response = await acompletion(**kwargs)

        content = response.choices[0].message.content or ""
        usage = response.usage

        return {
            "content": content,
            "token_usage": {
                "prompt": usage.prompt_tokens if usage else 0,
                "completion": usage.completion_tokens if usage else 0,
            },
        }


class ToolEngine:
    """
    工具引擎 — 接入真实工具调用框架

    通过 tools.ToolRegistry + ToolExecutor 执行真实工具调用。
    支持：web_search, code_execute, file_read, file_write, http_get, datetime
    """

    def __init__(self) -> None:
        self._registry = None
        self._executor = None
        self._initialized = False

    def _ensure_init(self):
        """懒加载工具注册表"""
        if not self._initialized:
            try:
                from tools.registry import create_default_registry, ToolExecutor
                self._registry = create_default_registry()
                self._executor = ToolExecutor(self._registry)
                self._initialized = True
            except Exception as e:
                import logging
                logging.getLogger(__name__).warning(f"ToolEngine 初始化失败: {e}")

    async def call(self, tool_name: str, params: dict) -> dict:
        """调用工具"""
        self._ensure_init()
        if not self._executor:
            return {
                "tool": tool_name,
                "output": f"[工具引擎未初始化] {tool_name}",
                "success": False,
            }

        result = await self._executor.execute(tool_name, params)
        return {
            "tool": tool_name,
            "output": result.output,
            "success": result.success,
            "error": result.error,
            "data": result.data,
        }

    def list_tools(self) -> list[str]:
        """列出可用工具"""
        self._ensure_init()
        if self._registry:
            return self._registry.list_names()
        return []

    def get_openai_schemas(self) -> list[dict]:
        """获取所有工具的 OpenAI function calling schema"""
        self._ensure_init()
        if self._registry:
            return self._registry.get_openai_schemas()
        return []


# ===========================================================================
# BaseAgent 抽象基类
# ===========================================================================

class BaseAgent(ABC):
    """
    所有 Specialist Agent 的基类

    子类必须实现 execute() 方法。
    通过 model_router 和 tool_engine 注入实现与外部解耦。
    """

    def __init__(self, spec: AgentSpec, model_router: ModelRouter,
                 tool_engine: ToolEngine) -> None:
        self.spec = spec
        self.model_router = model_router
        self.tool_engine = tool_engine

    @abstractmethod
    async def execute(self, action: str, params: dict, model: str) -> AgentResult:
        """
        执行具体任务，子类必须实现。

        Args:
            action: 动作类型（如 "code_gen", "data_analysis"）
            params: 动作参数
            model: 指定的模型 ID

        Returns:
            AgentResult 标准化结果
        """
        ...

    async def call_llm(self, system_prompt: str, user_prompt: str,
                       tools: list | None = None, **kwargs: Any) -> str:
        """统一的 LLM 调用入口"""
        model_id = kwargs.get("model") or await self.model_router.select("general")
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]
        response = await self.model_router.call(model_id, messages, tools=tools)
        return response["content"]

    async def use_tool(self, tool_name: str, params: dict) -> dict:
        """工具调用"""
        return await self.tool_engine.call(tool_name, params)


# ===========================================================================
# CodeAgent — 代码专家 Agent
# ===========================================================================

class CodeAgent(BaseAgent):
    """代码专家 Agent：代码生成、审查、修复、工程工作流"""

    SYSTEM_PROMPT = """你是万象积木 的代码专家 Agent。你的职责：
1. 根据用户需求生成高质量代码（带类型标注和文档）
2. 审查代码质量（Lint、类型检查、安全扫描）
3. 修复 Bug（自动诊断 + 修复 + 回归测试）
4. 执行工程工作流（从需求到部署的完整链路）

工具使用规则：
- 代码执行必须通过 python_sandbox 工具
- 文件操作必须通过 file_read/file_write 工具
- Git 操作必须通过 git 工具
- 生成代码后自动运行测试验证"""

    async def execute(self, action: str, params: dict, model: str) -> AgentResult:
        # 动作 → 提示词生成函数 的分派表
        prompt_builders = {
            "code_gen": self._prompt_code_gen,
            "code_review": self._prompt_code_review,
            "bug_fix": self._prompt_bug_fix,
            "refactor": self._prompt_refactor,
            "test_gen": self._prompt_test_gen,
            "precheck": self._prompt_precheck,
        }

        prompt_fn = prompt_builders.get(action, self._prompt_code_gen)
        user_prompt = prompt_fn(params)

        # 调用 LLM 生成方案
        plan_text = await self.call_llm(
            system_prompt=self.SYSTEM_PROMPT,
            user_prompt=user_prompt,
            model=model,
        )

        # 如果需要执行代码，调用沙箱验证
        if params.get("execute", False):
            code = self._extract_code(plan_text)
            if code:
                exec_result = await self.use_tool("python_sandbox", {"code": code})
                plan_text += f"\n\n执行结果：\n{exec_result.get('output', '')}"

        return AgentResult(
            content=plan_text,
            token_usage={"prompt": 1000, "completion": len(plan_text) * 2},
        )

    # --- 各动作的提示词构建 ---

    def _prompt_code_gen(self, params: dict) -> str:
        upstream = params.get("upstream_results", "")
        upstream_section = f"上游结果参考：\n{upstream}" if upstream else ""
        return (
            f"需求：{params.get('requirement', '')}\n"
            f"技术栈：{params.get('tech_stack', 'Python + FastAPI')}\n"
            f"输出要求：完整可运行的代码，带类型标注和注释\n"
            f"{upstream_section}"
        )

    def _prompt_code_review(self, params: dict) -> str:
        return (
            f"请审查以下代码：\n```\n{params.get('code', '')}\n```\n"
            f"关注点：安全性、性能、可读性、类型安全\n"
        )

    def _prompt_bug_fix(self, params: dict) -> str:
        return (
            f"Bug 描述：{params.get('bug_description', '')}\n"
            f"相关代码：\n```\n{params.get('code', '')}\n```\n"
            f"错误信息：{params.get('error', '')}\n"
            f"请诊断根因并给出修复方案。"
        )

    def _prompt_refactor(self, params: dict) -> str:
        return (
            f"请重构以下代码，提升可读性和可维护性：\n```\n{params.get('code', '')}\n```\n"
            f"重构目标：{params.get('goal', '提升代码质量')}\n"
        )

    def _prompt_test_gen(self, params: dict) -> str:
        return (
            f"请为以下代码生成单元测试：\n```\n{params.get('code', '')}\n```\n"
            f"测试框架：{params.get('framework', 'pytest')}\n"
            f"覆盖率目标：{params.get('coverage', '90%')}\n"
        )

    def _prompt_precheck(self, params: dict) -> str:
        return (
            f"请审查以下操作是否安全：\n"
            f"操作类型：{params.get('action_type', '')}\n"
            f"操作参数：{params.get('params', params)}\n\n"
            f'输出 JSON：\n'
            f'{{"safe": true/false, "reason": "...", "risk_level": "low/medium/high", "summary": "..."}}'
        )

    @staticmethod
    def _extract_code(text: str) -> str | None:
        """从 LLM 输出中提取代码块"""
        match = re.search(r"```(?:python)?\n(.*?)```", text, re.DOTALL)
        return match.group(1) if match else None


# ===========================================================================
# DataAgent — 数据专家 Agent
# ===========================================================================

class DataAgent(BaseAgent):
    """数据专家 Agent：数据分析、可视化、ETL、报表生成"""

    SYSTEM_PROMPT = """你是万象积木 的数据专家 Agent。你的职责：
1. 数据分析：统计、分布、相关性、异常检测
2. 数据可视化：折线图、柱状图、散点图、热力图
3. ETL 管线：数据提取、清洗、转换、加载
4. 报表生成：自动化数据报表 + 关键洞察

输出规范：
- 分析结果用 Markdown 表格呈现
- 可视化代码用 Python + matplotlib/plotly
- 关键发现用要点列表总结"""

    async def execute(self, action: str, params: dict, model: str) -> AgentResult:
        prompt_builders = {
            "data_analysis": self._prompt_analysis,
            "visualization": self._prompt_viz,
            "etl": self._prompt_etl,
            "report_gen": self._prompt_report,
            "precheck": self._prompt_precheck,
        }

        prompt_fn = prompt_builders.get(action, self._prompt_analysis)
        user_prompt = prompt_fn(params)

        result_text = await self.call_llm(
            system_prompt=self.SYSTEM_PROMPT,
            user_prompt=user_prompt,
            model=model,
        )

        return AgentResult(
            content=result_text,
            token_usage={"prompt": 800, "completion": len(result_text) * 2},
        )

    def _prompt_analysis(self, params: dict) -> str:
        return (
            f"请分析以下数据：\n{params.get('data', '')}\n"
            f"分析维度：{params.get('dimensions', '默认全维度')}\n"
            f"上游结果：{params.get('upstream_results', '无')}\n"
        )

    def _prompt_viz(self, params: dict) -> str:
        return (
            f"请生成可视化代码：\n"
            f"数据：{params.get('data', '')}\n"
            f"图表类型：{params.get('chart_type', '自动选择')}\n"
            f"输出 matplotlib/plotly Python 代码"
        )

    def _prompt_etl(self, params: dict) -> str:
        return (
            f"请设计 ETL 管线：\n"
            f"数据源：{params.get('source', '')}\n"
            f"目标：{params.get('target', '')}\n"
            f"转换规则：{params.get('transform', '清洗 + 标准化')}\n"
        )

    def _prompt_report(self, params: dict) -> str:
        return (
            f"请生成数据报表：\n"
            f"数据：{params.get('data', '')}\n"
            f"报表格式：{params.get('format', 'Markdown')}\n"
            f"重点指标：{params.get('metrics', '自动选取')}\n"
        )

    def _prompt_precheck(self, params: dict) -> str:
        return (
            f"请审查数据操作是否安全：\n"
            f"操作：{params}\n"
            f'输出 JSON：{{"safe": true, "reason": "...", "risk_level": "low", "summary": "..."}}'
        )


# ===========================================================================
# ResearchAgent — 调研专家 Agent
# ===========================================================================

class ResearchAgent(BaseAgent):
    """调研专家 Agent：多源检索、对比分析、深度调研"""

    SYSTEM_PROMPT = """你是万象积木 的调研专家 Agent。你的职责：
1. 多源信息检索：从多个渠道搜集信息
2. 对比分析：多维度对比，给出优劣
3. 深度调研：系统性整理调研报告
4. 事实核查：交叉验证信息准确性

输出规范：
- 调研报告用结构化 Markdown
- 每条信息标注来源
- 对比分析用表格呈现
- 总结部分给出明确结论"""

    async def execute(self, action: str, params: dict, model: str) -> AgentResult:
        prompt_builders = {
            "research.single": self._prompt_single,
            "research.aggregate": self._prompt_aggregate,
            "research.compare": self._prompt_compare,
            "research.deep": self._prompt_deep,
            "precheck": self._prompt_precheck,
        }

        prompt_fn = prompt_builders.get(action, self._prompt_single)
        user_prompt = prompt_fn(params)

        result_text = await self.call_llm(
            system_prompt=self.SYSTEM_PROMPT,
            user_prompt=user_prompt,
            model=model,
        )

        # 如果有工具可用（web_search），尝试补充实时信息
        if "web_search" in self.spec.tools and params.get("enhance", False):
            search_result = await self.use_tool("web_search", {
                "query": params.get("target", params.get("topic", "")),
            })
            result_text += f"\n\n--- 实时补充 ---\n{search_result.get('output', '')}"

        return AgentResult(
            content=result_text,
            token_usage={"prompt": 600, "completion": len(result_text) * 2},
        )

    def _prompt_single(self, params: dict) -> str:
        return (
            f"请调研以下主题：{params.get('target', params.get('topic', ''))}\n"
            f"调研深度：{params.get('depth', '标准')}\n"
            f"上游结果：{params.get('upstream_results', '无')}\n"
        )

    def _prompt_aggregate(self, params: dict) -> str:
        # 聚合多个 fan-out 子任务的结果
        fan_count = params.get("fan_count", 0)
        return (
            f"请将以下 {fan_count} 个并行调研结果合并为一份连贯的报告。\n"
            f"要求：去重、补全、逻辑连贯，最终输出结构化 Markdown。\n"
        )

    def _prompt_compare(self, params: dict) -> str:
        items = params.get("items", [])
        return (
            f"请对比分析以下对象：\n{', '.join(str(i) for i in items)}\n"
            f"对比维度：{params.get('dimensions', '功能、性能、价格、易用性')}\n"
            f"输出对比表格 + 总结建议。"
        )

    def _prompt_deep(self, params: dict) -> str:
        return (
            f"请对以下主题进行深度调研：\n{params.get('topic', '')}\n"
            f"调研范围：背景、现状、趋势、挑战、机遇\n"
            f"输出完整的调研报告（3000-5000字）。"
        )

    def _prompt_precheck(self, params: dict) -> str:
        return (
            f"请审查调研操作是否安全：\n"
            f"操作：{params}\n"
            f'输出 JSON：{{"safe": true, "reason": "...", "risk_level": "low", "summary": "..."}}'
        )


# ===========================================================================
# GeneralAgent — 通用助手 Agent
# ===========================================================================

class GeneralAgent(BaseAgent):
    """通用助手 Agent：处理日常对话、问答、总结、翻译等通用任务"""

    SYSTEM_PROMPT = """你是万象积木 的通用助手 Agent。你的职责：
1. 日常对话：友好、准确、有信息量
2. 内容总结：提取关键信息，结构化呈现
3. 分析推理：逻辑清晰，论据充分
4. 翻译：中英互译，保持语义和风格

输出规范：
- 回答简洁明了，避免废话
- 复杂内容用 Markdown 结构化
- 不确定的信息明确标注"""

    async def execute(self, action: str, params: dict, model: str) -> AgentResult:
        prompt_builders = {
            "chat": self._prompt_chat,
            "summary": self._prompt_summary,
            "analysis": self._prompt_analysis,
            "translation": self._prompt_translation,
            "precheck": self._prompt_precheck,
        }

        prompt_fn = prompt_builders.get(action, self._prompt_chat)
        user_prompt = prompt_fn(params)

        result_text = await self.call_llm(
            system_prompt=self.SYSTEM_PROMPT,
            user_prompt=user_prompt,
            model=model,
        )

        return AgentResult(
            content=result_text,
            token_usage={"prompt": 500, "completion": len(result_text) * 2},
        )

    def _prompt_chat(self, params: dict) -> str:
        upstream = params.get("upstream_results", "")
        upstream_section = f"\n上游结果参考：\n{upstream}" if upstream else ""
        return f"{params.get('message', params.get('query', ''))}{upstream_section}"

    def _prompt_summary(self, params: dict) -> str:
        return (
            f"请总结以下内容：\n{params.get('content', '')}\n"
            f"总结要求：{params.get('style', '简洁要点')}\n"
        )

    def _prompt_analysis(self, params: dict) -> str:
        return (
            f"请分析以下内容：\n{params.get('content', '')}\n"
            f"分析维度：{params.get('dimensions', '多维度')}\n"
        )

    def _prompt_translation(self, params: dict) -> str:
        return (
            f"请翻译以下内容（{params.get('source_lang', '自动检测')} → {params.get('target_lang', '中文')}）：\n"
            f"{params.get('content', '')}\n"
        )

    def _prompt_precheck(self, params: dict) -> str:
        return (
            f"请审查操作是否安全：\n"
            f"操作：{params}\n"
            f'输出 JSON：{{"safe": true, "reason": "...", "risk_level": "low", "summary": "..."}}'
        )


# ===========================================================================
# OpsAgent — 运维专家 Agent
# ===========================================================================

class OpsAgent(BaseAgent):
    """运维专家 Agent：部署、监控、告警响应、故障排查"""

    SYSTEM_PROMPT = """你是万象积木 的运维专家 Agent。你的职责：
1. 部署：Docker/K8s 部署、配置管理、滚动更新
2. 监控：指标分析、日志排查、健康检查
3. 告警响应：快速定位、止血、根因分析
4. 故障排查：日志分析、链路追踪、性能诊断

输出规范：
- 操作步骤清晰可执行
- 命令用代码块包裹
- 风险操作标注警告"""

    async def execute(self, action: str, params: dict, model: str) -> AgentResult:
        prompt_builders = {
            "deploy": self._prompt_deploy,
            "monitor": self._prompt_monitor,
            "incident_response": self._prompt_incident,
            "log_analysis": self._prompt_log,
            "precheck": self._prompt_precheck,
        }

        prompt_fn = prompt_builders.get(action, self._prompt_deploy)
        user_prompt = prompt_fn(params)

        result_text = await self.call_llm(
            system_prompt=self.SYSTEM_PROMPT,
            user_prompt=user_prompt,
            model=model,
        )

        return AgentResult(
            content=result_text,
            token_usage={"prompt": 700, "completion": len(result_text) * 2},
        )

    def _prompt_deploy(self, params: dict) -> str:
        return (
            f"部署需求：{params.get('requirement', '')}\n"
            f"环境：{params.get('env', 'production')}\n"
            f"技术栈：{params.get('tech_stack', 'Docker')}\n"
            f"上游结果：{params.get('upstream_results', '无')}\n"
        )

    def _prompt_monitor(self, params: dict) -> str:
        return (
            f"请分析以下监控指标：\n{params.get('metrics', '')}\n"
            f"关注：{params.get('focus', 'CPU、内存、延迟、错误率')}\n"
        )

    def _prompt_incident(self, params: dict) -> str:
        return (
            f"告警信息：{params.get('alert', '')}\n"
            f"影响范围：{params.get('impact', '未知')}\n"
            f"请给出止血方案和根因分析。\n"
        )

    def _prompt_log(self, params: dict) -> str:
        return (
            f"请分析以下日志：\n{params.get('logs', '')}\n"
            f"查找异常模式和错误根因。\n"
        )

    def _prompt_precheck(self, params: dict) -> str:
        return (
            f"请审查运维操作是否安全：\n"
            f"操作：{params}\n"
            f'输出 JSON：{{"safe": true, "reason": "...", "risk_level": "low", "summary": "..."}}'
        )


# ===========================================================================
# DesignAgent — 创意专家 Agent
# ===========================================================================

class DesignAgent(BaseAgent):
    """创意专家 Agent：图片/视频/3D/音乐生成与编辑"""

    SYSTEM_PROMPT = """你是万象积木 的创意专家 Agent。你的职责：
1. 图片生成：根据描述生成图片（Stable Diffusion / DALL-E）
2. 视频生成：短视频制作、视频编辑
3. 图片编辑：修图、风格转换、批量处理
4. 音乐生成：背景音乐、音效设计
5. 3D 生成：简单 3D 模型生成

输出规范：
- 生成提示词用英文，附中文翻译
- 参数配置用 YAML 格式
- 创意说明简洁有感染力"""

    async def execute(self, action: str, params: dict, model: str) -> AgentResult:
        prompt_builders = {
            "image_gen": self._prompt_image,
            "video_gen": self._prompt_video,
            "image_edit": self._prompt_image_edit,
            "music_gen": self._prompt_music,
            "3d_gen": self._prompt_3d,
            "precheck": self._prompt_precheck,
        }

        prompt_fn = prompt_builders.get(action, self._prompt_image)
        user_prompt = prompt_fn(params)

        result_text = await self.call_llm(
            system_prompt=self.SYSTEM_PROMPT,
            user_prompt=user_prompt,
            model=model,
        )

        return AgentResult(
            content=result_text,
            token_usage={"prompt": 600, "completion": len(result_text) * 2},
        )

    def _prompt_image(self, params: dict) -> str:
        return (
            f"图片描述：{params.get('description', '')}\n"
            f"风格：{params.get('style', '写实')}\n"
            f"尺寸：{params.get('size', '1024x1024')}\n"
            f"请生成 Stable Diffusion 提示词和参数。\n"
        )

    def _prompt_video(self, params: dict) -> str:
        return (
            f"视频描述：{params.get('description', '')}\n"
            f"时长：{params.get('duration', '10s')}\n"
            f"风格：{params.get('style', '电影感')}\n"
        )

    def _prompt_image_edit(self, params: dict) -> str:
        return (
            f"编辑需求：{params.get('edit', '')}\n"
            f"原图描述：{params.get('source', '')}\n"
        )

    def _prompt_music(self, params: dict) -> str:
        return (
            f"音乐描述：{params.get('description', '')}\n"
            f"风格：{params.get('genre', '轻音乐')}\n"
            f"时长：{params.get('duration', '30s')}\n"
        )

    def _prompt_3d(self, params: dict) -> str:
        return (
            f"3D 模型描述：{params.get('description', '')}\n"
            f"用途：{params.get('purpose', '展示')}\n"
        )

    def _prompt_precheck(self, params: dict) -> str:
        return (
            f"请审查创意操作是否安全：\n"
            f"操作：{params}\n"
            f'输出 JSON：{{"safe": true, "reason": "...", "risk_level": "low", "summary": "..."}}'
        )
