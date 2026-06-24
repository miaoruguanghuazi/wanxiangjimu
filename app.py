"""
万象积木 — 集成版主入口
========================

集成以下子系统：
  1. 多模型对话（litellm + DeepSeek/豆包/OpenAI）
  2. Agent 编排层（agent_orchestrator）
  3. RAG 知识库（rag_pipeline）
  4. 插件市场（skill_market）
  5. 四层记忆系统（内存 + Redis + Chroma + Skill）
  6. 安全体系（Prompt防护 + 脱敏 + 沙箱 + 审计 + 速率限制）

启动：python app.py
访问：http://localhost:7860
"""

from __future__ import annotations

import os
import asyncio
import logging
from datetime import datetime
from typing import Any

from dotenv import load_dotenv

# 加载环境变量
load_dotenv()

# ---------------------------------------------------------------------------
# 日志配置
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("wanxiang-jimu")

# ---------------------------------------------------------------------------
# 子系统懒加载（避免启动时因缺少可选依赖崩溃）
# ---------------------------------------------------------------------------

_orchestrator = None
_rag_pipeline = None
_skill_runtime = None
_model_router = None  # 多模型路由系统
_memory_system = None  # 四层记忆系统
_security = None       # 安全体系


# ---------------------------------------------------------------------------
# 安全体系（单例）
# ---------------------------------------------------------------------------

def get_security():
    """懒加载安全体系"""
    global _security
    if _security is None:
        try:
            from security import (
                PromptGuard, Sanitizer, CodeSandbox, PathGuard,
                HTTPGuard, RateLimiter, ContentFilter, AuditLogger,
                OutputGuard, SessionGuard, ConfigValidator,
            )
            _security = {
                "prompt_guard": PromptGuard(strict=False),
                "sanitizer": Sanitizer(),
                "sandbox": CodeSandbox(),
                "path_guard": PathGuard(),
                "http_guard": HTTPGuard(),
                "rate_limiter": RateLimiter(
                    user_capacity=20,
                    user_refill_rate=2.0,
                    global_capacity=200,
                    global_refill_rate=20.0,
                ),
                "content_filter": ContentFilter(),
                "audit": AuditLogger(log_dir="./data/audit"),
                "output_guard": OutputGuard(),
                "session_guard": SessionGuard(timeout=3600),
                "config_validator": ConfigValidator(),
            }
            logger.info("✅ 安全体系已加载（11个模块）")
            # 启动时检查配置
            issues = _security["config_validator"].validate()
            for issue in issues:
                if issue.level == "critical":
                    logger.error(f"🚨 配置安全: {issue.message}")
                elif issue.level == "warning":
                    logger.warning(f"⚠️ 配置安全: {issue.message}")
        except Exception as e:
            logger.warning(f"⚠️ 安全体系加载失败（非致命）: {e}")
            import traceback; traceback.print_exc()
    return _security


def get_memory_system():
    """懒加载四层记忆系统"""
    global _memory_system
    if _memory_system is None:
        try:
            import chromadb
            from memory_system import MemorySystem

            chroma_client = chromadb.PersistentClient(path="./data/chroma")
            _memory_system = MemorySystem(
                chroma_client=chroma_client,
                data_path="./data/memory",
            )
            stats = _memory_system.get_stats()
            logger.info(f"✅ 四层记忆系统已加载 (L3: {stats['L3_long_term']['total']} 条记忆, L4: {stats['L4_procedural']['skills']} 个Skill)")
        except Exception as e:
            logger.warning(f"⚠️ 四层记忆系统加载失败（非致命）: {e}")
            import traceback
            traceback.print_exc()
    return _memory_system


def get_model_router():
    """懒加载多模型路由系统"""
    global _model_router
    if _model_router is None:
        try:
            from model_router import (
                CircuitBreakerManager, RouterEngine, ModelAdapter,
                load_from_yaml,
            )
            registry = load_from_yaml("conf/models.yaml")
            circuit_mgr = CircuitBreakerManager()
            engine = RouterEngine(registry, circuit_mgr)
            adapter = ModelAdapter(registry, circuit_mgr)
            available = [m.model_id for m in registry.all_enabled()]
            _model_router = {
                "registry": registry,
                "circuit": circuit_mgr,
                "engine": engine,
                "adapter": adapter,
                "available_models": available,
            }
            logger.info(f"✅ 多模型路由系统已加载（可用模型: {', '.join(available) if available else '无'}）")
        except Exception as e:
            logger.warning(f"⚠️ 多模型路由系统加载失败（非致命）: {e}")
    return _model_router

def get_orchestrator():
    """懒加载 Agent 编排层"""
    global _orchestrator
    if _orchestrator is None:
        try:
            from agent_orchestrator import (
                AgentRegistry, ModelRouter, ToolEngine,
                PlanBuilder, TaskManager, ResultFuser,
                CodeAgent, DataAgent, ResearchAgent,
                IntentResult,
            )
            registry = AgentRegistry()
            router = ModelRouter()
            tools = ToolEngine()

            # 注册 Agent 实例
            for agent_id, cls in [
                ("code_agent", CodeAgent),
                ("data_agent", DataAgent),
                ("research_agent", ResearchAgent),
            ]:
                spec = registry.get_spec(agent_id)
                if spec:
                    registry.register_instance(agent_id, cls(spec, router, tools))

            _orchestrator = {
                "registry": registry,
                "router": router,
                "tools": tools,
                "plan_builder": PlanBuilder(),
                "task_manager": TaskManager(registry, router, tools),
                "result_fuser": ResultFuser(router),
            }
            logger.info("✅ Agent 编排层已加载")
        except Exception as e:
            logger.warning(f"⚠️ Agent 编排层加载失败（非致命）: {e}")
    return _orchestrator


def get_rag_pipeline():
    """懒加载 RAG 管线（ChromaDB 本地化版）"""
    global _rag_pipeline
    if _rag_pipeline is None:
        try:
            from rag_pipeline import (
                DocumentParser, SmartChunker,
                VectorIndexer, HybridRetriever, RAGGenerator,
            )
            # ChromaDB 嵌入式，无需外部服务
            indexer = VectorIndexer(persist_path="./data/chroma")
            retriever = HybridRetriever(indexer=indexer)
            _rag_pipeline = {
                "parser": DocumentParser(),
                "chunker": SmartChunker(),
                "indexer": indexer,
                "retriever": retriever,
                "generator": None,  # 延迟初始化，需要 ModelRouter
            }
            chunk_count = indexer.count()
            logger.info(f"✅ RAG 管线已加载（ChromaDB 本地化，知识库已有 {chunk_count} 个切片）")
        except Exception as e:
            logger.warning(f"⚠️ RAG 管线加载失败（非致命）: {e}")
            import traceback
            traceback.print_exc()
    return _rag_pipeline


async def upload_document_to_rag(file_path: str, tenant_id: str = "default") -> str:
    """将上传的文档写入 RAG 知识库"""
    rag = get_rag_pipeline()
    if not rag:
        return "❌ RAG 管线未加载"

    try:
        # 1. 解析文档
        doc = await rag["parser"].parse(file_path, tenant_id=tenant_id)
        # 2. 切片
        chunks = await rag["chunker"].chunk(doc)
        # 3. 索引
        await rag["indexer"].index_chunks(chunks)

        return f"✅ 文档已入库: {doc.source_name} | {len(chunks)} 个切片 | 知识库总计 {rag['indexer'].count()} 个切片"
    except Exception as e:
        return f"❌ 文档入库失败: {str(e)}"


async def rag_query(query: str, tenant_id: str = "default", top_k: int = 5) -> str:
    """RAG 知识库问答"""
    rag = get_rag_pipeline()
    if not rag or not rag["retriever"]:
        return "❌ RAG 检索不可用"

    try:
        # 检索
        result = await rag["retriever"].retrieve(
            query=query, tenant_id=tenant_id, top_k=top_k, rerank=True
        )

        if not result.chunks:
            return "❌ 知识库中未找到相关内容"

        # 构造上下文
        context_parts = []
        citations = []
        for i, chunk in enumerate(result.chunks):
            source = chunk.metadata.get("source_name", "未知")
            section = chunk.section or ""
            context_parts.append(f"[{i+1}] {chunk.content}")
            citations.append(f"[{i+1}] {source} §{section}")

        context = "\n\n".join(context_parts)
        citation_str = "\n".join(citations)

        # 用路由系统调用 LLM 生成回答
        messages = [
            {"role": "system", "content": f"你是万象积木。根据以下检索到的知识库内容回答用户问题。"
             f"如果知识库内容不足以回答，请说明。在回答末尾列出引用来源。\n\n知识库内容:\n{context}"},
            {"role": "user", "content": query},
        ]
        router = get_model_router()
        if router:
            adapter = router["adapter"]
            engine = router["engine"]
            route_result = engine.route(query, preference="balanced")
            response = await adapter.call_with_route(route_result, messages, temperature=0.3)
            answer = response.content
        else:
            from litellm import acompletion
            model = os.getenv("DEFAULT_MODEL", "deepseek/deepseek-chat")
            response = await acompletion(model=model, messages=messages, temperature=0.3)
            answer = response.choices[0].message.content or ""

        return f"{answer}\n\n---\n📚 引用来源:\n{citation_str}"
    except Exception as e:
        return f"❌ RAG 查询失败: {str(e)}"


def get_skill_runtime():
    """懒加载插件市场"""
    global _skill_runtime
    if _skill_runtime is None:
        try:
            from skill_market import PluginRuntime, SkillStore, SandboxManager
            _skill_runtime = {
                "store": SkillStore(remote_url="https://registry.wanxiang-jimu.ai"),
                "sandbox": SandboxManager(),
                "runtime": None,  # PluginRuntime 需要 store + sandbox 完整初始化
            }
            logger.info("✅ 插件市场 SDK 已加载")
        except Exception as e:
            logger.warning(f"⚠️ 插件市场加载失败（非致命）: {e}")
    return _skill_runtime


# ---------------------------------------------------------------------------
# LLM 模型配置
# ---------------------------------------------------------------------------

# 从路由注册表动态生成模型列表
def _get_model_list():
    """获取可用模型列表（用于 UI 下拉框）"""
    router = get_model_router()
    if router:
        models = router["registry"].list_models()
        return [m["litellm_model"] for m in models if m["enabled"]]
    return ["deepseek/deepseek-chat", "deepseek/deepseek-coder"]

MODEL_LIST = _get_model_list()

DEFAULT_SYSTEM_PROMPT = """你是「万象积木」，一个聪明、友好、高效的智能助手。

你的能力包括：
1. 💬 日常对话和问答
2. 💻 代码生成、审查和修复
3. 📊 数据分析和可视化
4. 🔍 多源信息检索和深度调研
5. 📄 文档解析和知识库问答
6. 🔧 插件扩展和工具调用

回答要求：
- 准确、简洁、有帮助
- 涉及代码时给出完整可运行的代码
- 不确定的内容要说明
- 保持友好和耐心的语气"""


# ---------------------------------------------------------------------------
# 对话记忆（内存版，L1 工作记忆）
# ---------------------------------------------------------------------------

class ConversationMemory:
    """对话记忆管理器 — L1 工作记忆层"""

    def __init__(self, max_turns: int = 20):
        self.max_turns = max_turns
        self._sessions: dict[str, list[dict]] = {}

    def get_history(self, session_id: str = "default") -> list[dict]:
        return self._sessions.get(session_id, [])

    def add_message(self, session_id: str, role: str, content: str):
        if session_id not in self._sessions:
            self._sessions[session_id] = []
        self._sessions[session_id].append({"role": role, "content": content})
        # 超出上限时移除最早的消息（保留 system prompt）
        msgs = self._sessions[session_id]
        if len(msgs) > self.max_turns * 2 + 1:
            self._sessions[session_id] = [msgs[0]] + msgs[-(self.max_turns * 2):]

    def clear(self, session_id: str = "default"):
        self._sessions[session_id] = []

    def get_summary(self, session_id: str = "default") -> str:
        """返回对话摘要（简单版：取最近3轮）"""
        history = self._sessions.get(session_id, [])
        if len(history) <= 1:
            return "（无对话历史）"
        recent = history[-6:]  # 最近3轮
        lines = []
        for msg in recent:
            role = "👤" if msg["role"] == "user" else "🐋"
            content = msg["content"][:80] + "..." if len(msg["content"]) > 80 else msg["content"]
            lines.append(f"{role} {content}")
        return "\n".join(lines)


# 保留旧接口兼容（内部使用 MemorySystem）
memory = ConversationMemory(max_turns=20)

# 初始化四层记忆系统
_ms = None


def _get_ms():
    """获取四层记忆系统单例"""
    global _ms
    if _ms is None:
        _ms = get_memory_system()
    return _ms


# ---------------------------------------------------------------------------
# 核心：LLM 调用
# ---------------------------------------------------------------------------

async def call_llm(
    messages: list[dict],
    model: str,
    temperature: float = 0.7,
    stream: bool = True,
):
    """调用 LLM（通过 litellm 统一接口）"""
    from litellm import acompletion

    response = await acompletion(
        model=model,
        messages=messages,
        temperature=temperature,
        stream=stream,
    )
    return response


async def call_llm_with_router(
    messages: list[dict],
    user_message: str,
    temperature: float = 0.7,
    stream: bool = True,
    preference: str = None,
):
    """
    通过多模型路由系统调用 LLM
    返回: (async_generator_or_response, route_info_dict)
    """
    router = get_model_router()
    if not router:
        # 降级到直接调用
        model = os.getenv("DEFAULT_MODEL", "deepseek/deepseek-chat")
        return await call_llm(messages, model, temperature, stream), {"fallback": True, "model": model}

    engine = router["engine"]
    adapter = router["adapter"]

    # 路由决策
    route_result = engine.route(user_message, preference=preference)
    route_info = route_result.to_dict()

    if stream:
        # 流式调用（含降级）
        async def stream_gen():
            async for chunk in adapter.stream_call_with_route(
                route_result, messages, temperature
            ):
                yield chunk
        return stream_gen(), route_info
    else:
        # 非流式调用
        response = await adapter.call_with_route(route_result, messages, temperature)
        return response, route_info


# ---------------------------------------------------------------------------
# 意图识别（简单规则版，后续可替换为 NLU 模型）
# ---------------------------------------------------------------------------

def detect_intent(message: str) -> str:
    """根据用户消息识别意图"""
    msg = message.lower()

    # 代码相关
    if any(kw in msg for kw in ["代码", "函数", "写一个", "bug", "重构", "code", "python", "java", "golang", "rust"]):
        return "tool.code"

    # 数据分析
    if any(kw in msg for kw in ["分析", "数据", "图表", "可视化", "报表", "excel", "csv"]):
        return "tool.data_analysis"

    # 调研
    if any(kw in msg for kw in ["调研", "对比", "搜索", "查找资料", "竞品", "research"]):
        return "research.multi_source"

    # 文档/RAG
    if any(kw in msg for kw in ["文档", "上传", "解析", "pdf", "word", "知识库"]):
        return "rag.query"

    # 默认：通用对话
    return "chat.general"


# ---------------------------------------------------------------------------
# Gradio 界面
# ---------------------------------------------------------------------------

CUSTOM_CSS = """
/* ========== 全局变量 ========== */
:root {
    --primary-color: #6366f1;
    --primary-light: #818cf8;
    --primary-gradient: linear-gradient(135deg, #6366f1 0%, #8b5cf6 50%, #a855f7 100%);
    --secondary-color: #06b6d4;
    --success-color: #10b981;
    --warning-color: #f59e0b;
    --error-color: #ef4444;
    --bg-main: #0f172a;
    --bg-card: #1e293b;
    --bg-card-hover: #334155;
    --bg-input: #0f172a;
    --text-primary: #f1f5f9;
    --text-secondary: #94a3b8;
    --text-muted: #64748b;
    --border-color: #334155;
    --border-light: #475569;
}

* { border-color: var(--border-color) !important; }

body {
    background: linear-gradient(135deg, #0f172a 0%, #1e1b4b 30%, #0f172a 70%, #1e1b4b 100%);
    background-attachment: fixed;
    color: var(--text-primary);
    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
}

.gradio-container { max-width: 1400px !important; }

.app-header {
    background: var(--primary-gradient) !important;
    padding: 24px 32px !important;
    border-radius: 20px;
    margin-bottom: 24px;
    box-shadow: 0 20px 60px rgba(99, 102, 241, 0.3);
    position: relative;
    overflow: hidden;
}
.app-header::before {
    content: '';
    position: absolute;
    top: -50%; right: -10%;
    width: 300px; height: 300px;
    background: radial-gradient(circle, rgba(255,255,255,0.1) 0%, transparent 70%);
    border-radius: 50%;
}
.app-header h1 { color: white !important; font-weight: 700; font-size: 32px; margin: 0; position: relative; z-index: 1; }
.app-header p { color: rgba(255,255,255,0.85) !important; margin: 6px 0 0 0; font-size: 15px; position: relative; z-index: 1; }

.chat-container, .sidebar-card {
    background: var(--bg-card) !important;
    border: 1px solid var(--border-color) !important;
    border-radius: 16px !important;
    box-shadow: 0 4px 24px rgba(0,0,0,0.15);
}

.chatbot .message {
    border-radius: 16px !important;
    padding: 14px 18px !important;
    margin-bottom: 12px;
    max-width: 85%;
    line-height: 1.6;
    box-shadow: 0 2px 8px rgba(0,0,0,0.1);
}
.chatbot .user {
    background: var(--primary-gradient) !important;
    color: white !important;
    margin-left: auto;
    border-bottom-right-radius: 4px !important;
}
.chatbot .bot {
    background: var(--bg-card-hover) !important;
    color: var(--text-primary) !important;
    margin-right: auto;
    border-bottom-left-radius: 4px !important;
    border: 1px solid var(--border-color);
}

button.primary-btn {
    background: var(--primary-gradient) !important;
    border: none !important;
    border-radius: 12px !important;
    color: white !important;
    font-weight: 600;
    padding: 12px 28px !important;
    box-shadow: 0 4px 15px rgba(99,102,241,0.35);
    transition: all 0.3s cubic-bezier(0.4,0,0.2,1);
}
button.primary-btn:hover { transform: translateY(-2px); box-shadow: 0 6px 20px rgba(99,102,241,0.45); }

textarea, input, select {
    background: var(--bg-input) !important;
    border: 1px solid var(--border-color) !important;
    border-radius: 12px !important;
    color: var(--text-primary) !important;
    font-size: 14px;
    transition: all 0.3s ease;
}
textarea:focus, input:focus, select:focus {
    border-color: var(--primary-color) !important;
    box-shadow: 0 0 0 3px rgba(99,102,241,0.15) !important;
    outline: none !important;
}

::-webkit-scrollbar { width: 8px; height: 8px; }
::-webkit-scrollbar-track { background: var(--bg-main); border-radius: 4px; }
::-webkit-scrollbar-thumb { background: var(--border-color); border-radius: 4px; }
::-webkit-scrollbar-thumb:hover { background: var(--primary-color); }

.status-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 10px; }
.status-item {
    background: var(--bg-input);
    border: 1px solid var(--border-color);
    border-radius: 10px;
    padding: 12px;
    text-align: center;
}
.status-item:hover { border-color: var(--success-color); background: rgba(16,185,129,0.05); }

input[type="range"] { -webkit-appearance: none; height: 6px; border-radius: 3px; background: var(--bg-card-hover); }
input[type="range"]::-webkit-slider-thumb {
    -webkit-appearance: none; width: 20px; height: 20px; border-radius: 50%;
    background: var(--primary-gradient); cursor: pointer;
    border: 2px solid white;
}

.footer-text { color: var(--text-muted); font-size: 12px; text-align: center; margin-top: 24px; }

pre, code { background: #0f172a !important; border-radius: 8px !important; border: 1px solid var(--border-color) !important; }

"""


def build_ui():
    import gradio as gr

    with gr.Blocks(
        title="🐋 万象积木",
    ) as demo:

        gr.HTML("""
        <div class="app-header">
            <h1>🐋 万象积木</h1>
            <p>多模型路由 · Agent编排 · RAG知识库 · 四层记忆 · 安全防护</p>
        </div>
        """)

        # === 状态 ===
        current_model = gr.State(os.getenv("DEFAULT_MODEL", MODEL_LIST[0]))
        session_id = gr.State(f"session_{datetime.now().strftime('%Y%m%d%H%M%S')}")
        session_list_state = gr.State([])  # 多会话列表
        last_user_msg = gr.State("")  # 上一条用户消息
        user_id = gr.State("default")  # 当前用户

        with gr.Tabs():
          with gr.Tab("💬 对话"):
           with gr.Row():
            # ========== 左侧：聊天区 ==========
            with gr.Column(scale=3):
                # 会话管理
                with gr.Row(equal_height=True):
                    session_selector = gr.Dropdown(
                        label="会话列表",
                        choices=[],
                        value=None,
                        interactive=True,
                        scale=3,
                        elem_id="session-selector",
                    )
                    new_session_btn = gr.Button("➕ 新会话", size="sm", scale=1, elem_classes=["quick-btn"])
                    del_session_btn = gr.Button("🗑️ 删除", size="sm", scale=1, elem_classes=["quick-btn"])
                    user_selector = gr.Dropdown(
                        choices=["default", "user1", "user2"],
                        value="default",
                        label="用户",
                        interactive=True,
                        scale=1,
                        min_width=80,
                    )
                # 快捷示例
                with gr.Row():
                    example_btn1 = gr.Button("💻 写代码", size="sm", elem_classes=["quick-btn"])
                    example_btn2 = gr.Button("📊 数据分析", size="sm", elem_classes=["quick-btn"])
                    example_btn3 = gr.Button("🔍 技术调研", size="sm", elem_classes=["quick-btn"])
                    example_btn4 = gr.Button("📖 知识问答", size="sm", elem_classes=["quick-btn"])

                chatbot = gr.Chatbot(
                    height=500,
                    show_label=False,
                    avatar_images=(None, "🐋"),
                )
                msg_input = gr.Textbox(
                    label="输入消息",
                    placeholder="输入你的问题，按回车发送...",
                    lines=2,
                    scale=4,
                )
                with gr.Row():
                    send_btn = gr.Button("🚀 发送", variant="primary", scale=1)
                    stop_btn = gr.Button("⏹️ 停止", variant="stop", scale=1)
                    clear_btn = gr.Button("🗑️ 清空", variant="secondary", scale=1)

            # ========== 右侧：控制面板 ==========
            with gr.Column(scale=1):
                gr.Markdown("### ⚙️ 设置")

                model_dropdown = gr.Dropdown(
                    choices=MODEL_LIST,
                    value=os.getenv("DEFAULT_MODEL", MODEL_LIST[0]),
                    label="选择模型",
                    info="DeepSeek 便宜好用，GPT-4o 最强",
                )

                temperature_slider = gr.Slider(
                    minimum=0, maximum=2, value=0.7, step=0.1,
                    label="温度", info="0=精确 · 2=创意",
                )

                system_prompt_box = gr.Textbox(
                    value=DEFAULT_SYSTEM_PROMPT,
                    label="系统提示词",
                    lines=4,
                    placeholder="定义AI的角色和行为...",
                )

                gr.Markdown("### 📊 系统状态")

                # 子系统状态 — HTML 卡片式
                def get_status_html():
                    orch = get_orchestrator()
                    rag = get_rag_pipeline()
                    skill = get_skill_runtime()
                    mr = get_model_router()
                    ms = get_memory_system()
                    sec = get_security()

                    cards = []

                    # 模型路由
                    if mr:
                        available = mr["available_models"]
                        cb_status = mr["circuit"].all_status()
                        open_count = sum(1 for v in cb_status.values() if v["state"] == "open")
                        cls = "ok" if open_count == 0 else "warn"
                        val = f"{len(available)} 个可用" + (f" · ⚠️ {open_count} 熔断" if open_count else "")
                    else:
                        cls = "warn"
                        val = "未加载"
                    cards.append(f'<div class="status-card {cls}"><div class="label">🧭 模型路由</div><div class="value">{val}</div></div>')

                    # 四层记忆
                    if ms:
                        mstats = ms.get_stats()
                        l1 = mstats['L1_working']['sessions']
                        l2 = mstats['L2_short_term']['summaries']
                        l3 = mstats['L3_long_term']['total']
                        l4 = mstats['L4_procedural']['skills']
                        val = f"L1={l1} · L2={l2} · L3={l3} · L4={l4}"
                        cls = "ok"
                    else:
                        cls = "warn"
                        val = "未加载"
                    cards.append(f'<div class="status-card {cls}"><div class="label">🧠 四层记忆</div><div class="value">{val}</div></div>')

                    # 安全体系
                    if sec:
                        audit_stats = sec["audit"].get_stats()
                        pg_stats = sec["prompt_guard"].get_stats()
                        sg_stats = sec["session_guard"].get_stats()
                        blocked = pg_stats.get("blocked", 0)
                        total_audit = audit_stats.get("total", 0)
                        active_sessions = sg_stats.get("active", 0)
                        cls = "danger" if blocked > 10 else ("ok" if blocked == 0 else "warn")
                        val = f"{total_audit} 审计 · {blocked} 拦截 · {active_sessions} 会话"
                    else:
                        cls = "warn"
                        val = "未加载"
                    cards.append(f'<div class="status-card {cls}"><div class="label">🛡️ 安全体系</div><div class="value">{val}</div></div>')

                    # Agent编排
                    cls = "ok" if orch else "warn"
                    val = "就绪" if orch else "未加载"
                    cards.append(f'<div class="status-card {cls}"><div class="label">🤖 Agent编排</div><div class="value">{val}</div></div>')

                    # RAG
                    cls = "ok" if rag else "warn"
                    val = "就绪" if rag else "未加载"
                    cards.append(f'<div class="status-card {cls}"><div class="label">📄 RAG管线</div><div class="value">{val}</div></div>')

                    # 插件市场
                    cls = "ok" if skill else "warn"
                    val = "就绪" if skill else "未加载"
                    cards.append(f'<div class="status-card {cls}"><div class="label">🔧 插件市场</div><div class="value">{val}</div></div>')

                    # 工具
                    try:
                        from tools.registry import create_default_registry
                        reg = create_default_registry()
                        tool_count = len(reg.list_names())
                        val = f"{tool_count} 个内置"
                        cls = "ok"
                    except Exception:
                        val = "加载中"
                        cls = "warn"
                    cards.append(f'<div class="status-card {cls}"><div class="label">🛠️ 内置工具</div><div class="value">{val}</div></div>')

                    return '<div class="status-grid">' + "\n".join(cards) + '</div>'

                status_display = gr.HTML(
                    value=get_status_html(),
                )

                # 定时刷新 (gr.Timer 需要 Gradio 4.10+)
                try:
                    timer = gr.Timer(value=10)
                    timer.tick(fn=get_status_html, outputs=status_display)
                except AttributeError:
                    pass  # 旧版 Gradio 无 Timer，手动刷新即可

                refresh_btn = gr.Button("🔄 刷新状态", size="sm")

                gr.Markdown("### 📝 对话记忆")
                memory_display = gr.Textbox(label="最近对话摘要", lines=5, interactive=False, visible=True)

                # 别名：respond() 内部使用 get_status_text 名称
                get_status_text = get_status_html

          with gr.Tab("📚 知识库"):
            with gr.Row():
              with gr.Column(scale=1):
                gr.Markdown("### 📤 上传文档")
                gr.Markdown("支持 PDF / Word / Markdown / HTML / TXT / CSV")
                file_upload = gr.File(
                    label="选择文档",
                    file_count="multiple",
                    file_types=[".pdf", ".docx", ".doc", ".md", ".html", ".htm", ".txt", ".csv", ".xlsx", ".pptx"],
                )
                upload_btn = gr.Button("📥 上传并索引", variant="primary")
                upload_status = gr.Textbox(label="上传结果", lines=3, interactive=False)

                gr.Markdown("---")
                gr.Markdown("### 📊 知识库统计")
                rag_status_btn = gr.Button("🔄 刷新", size="sm")
                rag_status = gr.Textbox(label="统计", lines=3, interactive=False)

              with gr.Column(scale=1):
                gr.Markdown("### 🔍 知识库问答")
                rag_query_input = gr.Textbox(
                    label="输入问题",
                    placeholder="基于知识库内容回答问题...",
                    lines=4,
                )
                rag_ask_btn = gr.Button("🔍 查询", variant="primary")
                rag_answer = gr.Markdown(label="回答", value="_等待查询..._")

            def do_upload(files):
                if not files:
                    return "请选择文件"
                results = []
                for f in files:
                    file_path = f if isinstance(f, str) else f.name
                    result = asyncio.run(upload_document_to_rag(file_path))
                    results.append(result)
                return "\n".join(results)

            def do_rag_query(query_text):
                if not query_text.strip():
                    return "请输入问题"
                return asyncio.run(rag_query(query_text))

            def get_rag_status():
                rag = get_rag_pipeline()
                if not rag or not rag["indexer"]:
                    return "RAG 管线未加载"
                stats = rag["indexer"].get_stats()
                return f"Collection: {stats.get('collection', '?')}\n总切片数: {stats.get('total_chunks', 0)}\n存储路径: {stats.get('persist_path', '?')}"

            upload_btn.click(fn=do_upload, inputs=[file_upload], outputs=[upload_status])
            rag_ask_btn.click(fn=do_rag_query, inputs=[rag_query_input], outputs=[rag_answer])
            rag_status_btn.click(fn=get_rag_status, outputs=[rag_status])

          with gr.Tab("🧠 记忆"):
            from app_memory_panel import build_memory_panel_tab
            get_ms_ref = lambda: get_memory_system()
            build_memory_panel_tab(get_ms_ref)

          with gr.Tab("📊 系统"):
            from app_dashboard import build_dashboard_tab
            get_mr_ref = lambda: get_model_router()
            get_sec_ref = lambda: get_security()
            get_orch_ref = lambda: get_orchestrator()
            build_dashboard_tab(get_mr_ref, get_sec_ref, get_orch_ref)

          with gr.Tab("🛠️ 工具"):
            gr.Markdown("### 🔧 内置工具 · 安全标注")
            tool_cards_html = ""
            try:
                from tools.registry import create_default_registry
                _reg = create_default_registry()
                # 安全标注映射
                sec_map = {
                    "code_execute": "🔒 沙箱预检",
                    "file_read": "🔒 路径守卫",
                    "file_write": "🔒 路径守卫",
                    "http_get": "🔒 SSRF 防护",
                    "web_search": "—",
                    "datetime": "—",
                }
                for t in _reg.list_all():
                    schema = t.get_openai_schema()
                    fn = schema["function"]
                    name = fn["name"]
                    desc = fn["description"]
                    sec_tag = sec_map.get(name, "—")
                    # 参数列表
                    params = fn.get("parameters", {}).get("properties", {})
                    required = fn.get("parameters", {}).get("required", [])
                    param_parts = []
                    for pname, pschema in params.items():
                        req_mark = "*" if pname in required else ""
                        ptype = pschema.get("type", "?")
                        param_parts.append(f"{pname}{req_mark}:{ptype}")
                    param_str = ", ".join(param_parts) if param_parts else "无参数"
                    tool_cards_html += f'''
                    <div class="tool-card">
                      <div class="tool-name">🔧 {name}</div>
                      <div class="tool-desc">{desc}</div>
                      <div class="tool-sec">{sec_tag}</div>
                      <div class="tool-params">参数: {param_str}</div>
                    </div>'''
            except Exception as e:
                tool_cards_html = f'<div class="tool-card"><div class="tool-desc">工具加载中...</div></div>'
            gr.HTML(tool_cards_html)

        # ========== 事件处理 ==========

        # 意图 → 动作映射
        INTENT_ACTION_MAP = {
            "tool.code": "code_gen",
            "tool.data_analysis": "data_analysis",
            "research.multi_source": "research.single",
            "rag.query": "research.single",
            "chat.general": "chat",
        }

        # 意图 → Agent 映射
        INTENT_AGENT_MAP = {
            "tool.code": "code_agent",
            "tool.data_analysis": "data_agent",
            "research.multi_source": "research_agent",
            "rag.query": "research_agent",
            "chat.general": "general_agent",
        }

        async def respond(message, history, model, temperature, system_prompt, sid, sid_list=None):
            """处理用户消息 — 通过 Agent 编排层"""
            import gradio as gr

            if not message.strip():
                yield "", history, "", get_status_text()
                return

            # === 安全体系检查 ===
            sec = get_security()
            if sec:
                # 1. 速率限制
                rl_result = sec["rate_limiter"].check(sid)
                if not rl_result.ok:
                    sec["audit"].log_security("rate_limited", "blocked", session_id=sid, level="warning")
                    new_history = list(history) + [
                        gr.ChatMessage(role="user", content=message),
                        gr.ChatMessage(role="assistant", content=rl_result.message),
                    ]
                    yield "", new_history, "", get_status_text()
                    return

                # 2. Prompt Injection 检测
                pg_result = sec["prompt_guard"].check(message)
                if not pg_result.ok:
                    sec["audit"].log_security("prompt_injection", "blocked", session_id=sid, level="critical",
                                              detail={"threats": pg_result.threats})
                    new_history = list(history) + [
                        gr.ChatMessage(role="user", content=message),
                        gr.ChatMessage(role="assistant", content=pg_result.message),
                    ]
                    yield "", new_history, "", get_status_text()
                    return

                # 3. 内容安全过滤
                cf_result = sec["content_filter"].check(message)
                if not cf_result.ok:
                    sec["audit"].log_security("content_filtered", "blocked", session_id=sid, level="warning",
                                              detail={"flags": cf_result.flags})
                    new_history = list(history) + [
                        gr.ChatMessage(role="user", content=message),
                        gr.ChatMessage(role="assistant", content=cf_result.message),
                    ]
                    yield "", new_history, "", get_status_text()
                    return

                # 4. 会话安全
                if not sec["session_guard"].touch(sid):
                    sec["audit"].log_security("session_rejected", "blocked", session_id=sid, level="warning")
                    new_history = list(history) + [
                        gr.ChatMessage(role="user", content=message),
                        gr.ChatMessage(role="assistant", content="⚠️ 系统会话数已达上限，请稍后再试。"),
                    ]
                    yield "", new_history, "", get_status_text()
                    return
                sec["session_guard"].increment_message(sid)

                # 使用消毒后的输入
                safe_message = pg_result.sanitized

                # 系统提示词加固
                system_prompt = sec["prompt_guard"].wrap_system_prompt(system_prompt)

                # 记录安全事件（可疑但不拦截）
                if pg_result.level.value == "suspicious":
                    sec["audit"].log_security("prompt_injection", "suspicious", session_id=sid, level="info",
                                              detail={"threats": pg_result.threats})

                # 记录审计日志
                sec["audit"].log_event("user_message", session_id=sid,
                                        detail={"length": len(message), "intent": "pending"})
            else:
                safe_message = message

            # 记录用户消息（系统提示词仅首次添加）
            if not any(m.get("role") == "system" for m in memory.get_history(sid)):
                memory.add_message(sid, "system", system_prompt)
            memory.add_message(sid, "user", safe_message)

            # 四层记忆系统：记录消息 + 触发压缩/提取
            ms = _get_ms()
            if ms:
                ms.add_message(sid, "user", safe_message)
                # 异步触发压缩和提取（不阻塞主流程）
                try:
                    asyncio.ensure_future(ms.maybe_compress(sid))
                    asyncio.ensure_future(ms.maybe_extract(sid))
                    asyncio.ensure_future(ms.auto_extract_and_store(safe_message, user_id=user_id, session_id=sid))
                except Exception as e:
                    logger.warning(f"记忆压缩/提取触发失败 (session={sid}): {e}")

            # 意图识别
            intent = detect_intent(message)
            action = INTENT_ACTION_MAP.get(intent, "chat")
            agent_id = INTENT_AGENT_MAP.get(intent, "general_agent")

            # 先显示一个"思考中"的消息
            thinking_msg = f"🔍 意图识别：{intent}  |  🤖 分派 Agent：{agent_id}\n\n正在思考..."
            new_history = list(history) + [
                gr.ChatMessage(role="user", content=message),
                gr.ChatMessage(role="assistant", content=thinking_msg),
            ]
            yield "", new_history, "", get_status_text()

            # 获取编排层
            orch = get_orchestrator()

            if orch and intent != "chat.general":
                # === 走编排层 ===
                try:
                    from agent_orchestrator import IntentResult

                    plan_builder = orch["plan_builder"]
                    task_manager = orch["task_manager"]

                    # 构建编排计划
                    intent_result = IntentResult(
                        intent=intent,
                        slots={"requirement": message, "target": message},
                        confidence=0.9,
                    )
                    context = {
                        "user_id": sid,
                        "session_id": sid,
                    }
                    plan = plan_builder.build(intent_result, context)

                    # 更新状态：显示编排信息
                    mode_text = {"SINGLE": "单任务", "SEQUENTIAL": "串行链", "PARALLEL_FANOUT": "并行扇出", "HUMAN_APPROVAL": "人工审批"}.get(plan.mode.value, plan.mode.value)
                    node_count = len(plan.nodes)
                    status_msg = f"🔍 意图：{intent}\n🤖 Agent：{agent_id}\n📋 模式：{mode_text}（{node_count}个节点）\n\n正在执行..."

                    new_history = list(history) + [
                        gr.ChatMessage(role="user", content=message),
                        gr.ChatMessage(role="assistant", content=status_msg),
                    ]
                    yield "", new_history, "", get_status_text()

                    # 执行编排计划
                    result = await task_manager.execute(plan)

                    # 格式化输出
                    if result.success:
                        content = result.content
                        # 添加元信息
                        meta_lines = []
                        if result.metadata and "token_usage" in result.metadata:
                            tu = result.metadata["token_usage"]
                            meta_lines.append(f"📊 Token: {tu.get('total', 0)}")
                        if result.partial_results:
                            stages = [p.get("action", "") for p in result.partial_results if p.get("status") == "success"]
                            if stages:
                                meta_lines.append(f"🔧 阶段: {' → '.join(stages)}")
                        if meta_lines:
                            content += f"\n\n---\n{' | '.join(meta_lines)}"
                    else:
                        content = result.content or "❌ 编排执行失败"
                        if result.partial_results:
                            for p in result.partial_results:
                                if p.get("status") == "failed":
                                    content += f"\n  - ❌ {p.get('action', '')}: {p.get('error', '')}"

                    # 输出安全过滤
                    sec = get_security()
                    if sec:
                        og_result = sec["output_guard"].check(content)
                        if not og_result.ok:
                            content = og_result.filtered
                            sec["audit"].log_security("output_filtered", "filtered", session_id=sid, level="info")
                        sec["audit"].log_event("assistant_response", session_id=sid,
                                                detail={"length": len(content), "mode": "orchestrator"})

                    memory.add_message(sid, "assistant", content)
                    if ms:
                        ms.add_message(sid, "assistant", content)

                    final_history = list(history) + [
                        gr.ChatMessage(role="user", content=message),
                        gr.ChatMessage(role="assistant", content=content),
                    ]
                    yield "", final_history, memory.get_summary(sid), get_status_text()

                except Exception as e:
                    # 编排层出错，降级到直接 LLM
                    fallback_msg = f"⚠️ 编排层出错，降级为直接对话：{str(e)[:100]}"
                    new_history = list(history) + [
                        gr.ChatMessage(role="user", content=message),
                        gr.ChatMessage(role="assistant", content=fallback_msg),
                    ]
                    yield "", new_history, "", get_status_text()

                    # 降级：直接流式 LLM
                    messages = memory.get_history(sid)
                    try:
                        response = await call_llm(messages, model, temperature, stream=True)
                        partial = ""
                        async for chunk in response:
                            delta = chunk.choices[0].delta
                            if delta and delta.content:
                                partial += delta.content
                                new_history = list(history) + [
                                    gr.ChatMessage(role="user", content=message),
                                    gr.ChatMessage(role="assistant", content=partial),
                                ]
                                yield "", new_history, "", get_status_text()

                        # 输出安全过滤
                        sec = get_security()
                        if sec:
                            og_result = sec["output_guard"].check(partial)
                            if not og_result.ok:
                                partial = og_result.filtered
                            sec["audit"].log_event("assistant_response", session_id=sid,
                                                    detail={"length": len(partial), "mode": "fallback"})

                        memory.add_message(sid, "assistant", partial)
                        if ms:
                            ms.add_message(sid, "assistant", partial)
                        final_history = list(history) + [
                            gr.ChatMessage(role="user", content=message),
                            gr.ChatMessage(role="assistant", content=partial),
                        ]
                        yield "", final_history, memory.get_summary(sid), get_status_text()
                    except Exception as e2:
                        error_msg = f"⚠️ LLM 也出错了：{str(e2)}"
                        sec = get_security()
                        if sec:
                            sec["audit"].log_error("llm_error", session_id=sid, context={"error": str(e2)[:200]})
                        err_history = list(history) + [
                            gr.ChatMessage(role="user", content=message),
                            gr.ChatMessage(role="assistant", content=error_msg),
                        ]
                        yield "", err_history, memory.get_summary(sid), get_status_text()

            else:
                # === 通用对话：通过多模型路由系统 ===
                # 使用四层记忆系统构建 prompt
                if ms:
                    messages = ms.build_prompt(sid, message, system_prompt, user_id=user_id)
                else:
                    messages = memory.get_history(sid)
                try:
                    # 优先走路由系统
                    stream_gen, route_info = await call_llm_with_router(
                        messages, message, temperature, stream=True
                    )

                    # 显示路由信息 — 富卡片风格
                    if route_info.get("fallback"):
                        route_text = f"📌 模型: {route_info['model']} (直接调用)"
                        route_html = f"""<div style="background:#f0fdf4;border:1px solid #bbf7d0;border-radius:8px;padding:8px 12px;margin-bottom:8px;font-size:13px">📌 直接调用 <b>{route_info['model']}</b></div>"""
                    else:
                        steps_lines = []
                        for s in route_info.get("route_steps", []):
                            icon = s.get("icon", "•")
                            label = s.get("step", "").split(" ")[-1]
                            detail = s.get("detail", "")
                            steps_lines.append(f'<div style="display:flex;align-items:center;gap:6px;padding:2px 0"><span>{icon}</span><span style="color:#64748b;min-width:70px;font-size:12px">{label}</span><span>{detail}</span></div>')
                        steps_html = "".join(steps_lines)
                        scores_lines = []
                        for i, sc in enumerate(route_info.get("scores", [])[:5]):
                            bar_w = max(sc.get("final_score", 0), 5)
                            medal = "🥇" if i == 0 else "🥈" if i == 1 else "🥉" if i == 2 else "　"
                            fw = "600" if i == 0 else "400"
                            scores_lines.append(f'<div style="display:flex;align-items:center;gap:6px;padding:1px 0;font-size:12px"><span>{medal}</span><span style="width:120px;font-weight:{fw}">{sc.get("model_id", "?")}</span><div style="flex:1;height:14px;background:#e2e8f0;border-radius:7px;overflow:hidden"><div style="width:{bar_w}%;height:100%;background:linear-gradient(90deg,#22c55e,#16a34a);border-radius:7px"></div></div><span style="width:40px;text-align:right;color:#475569">{sc.get("final_score", 0)}</span></div>')
                        scores_html = "".join(scores_lines)
                        fbs = " → ".join(route_info.get("fallback_chain", [])[:3]) or "无"
                        route_html = f'<div style="background:#f8fafc;border:1px solid #e2e8f0;border-radius:10px;padding:10px 14px;margin-bottom:8px;font-size:13px"><div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:6px;padding-bottom:6px;border-bottom:1px solid #e2e8f0"><span style="font-weight:600;color:#1e293b">🧭 路由决策</span><span style="color:#94a3b8;font-size:11px">{route_info.get("elapsed_ms", 0)}ms</span></div>{steps_html}<div style="margin-top:6px;padding-top:6px;border-top:1px solid #e2e8f0"><div style="font-size:11px;color:#94a3b8;margin-bottom:3px">🏆 模型评分排名</div>{scores_html}</div><div style="margin-top:4px;font-size:11px;color:#94a3b8">降级链: {fbs}</div></div>'

                    partial = ""
                    new_history = list(history) + [
                        gr.ChatMessage(role="user", content=message),
                        gr.ChatMessage(role="assistant", content=route_html + "⏳ 正在思考..."),
                    ]
                    yield "", new_history, "", get_status_text()

                    async for chunk in stream_gen:
                        partial += chunk
                        new_history = list(history) + [
                            gr.ChatMessage(role="user", content=message),
                            gr.ChatMessage(role="assistant", content=partial),
                        ]
                        yield "", new_history, "", get_status_text()

                    # 去掉路由信息前缀后保存到记忆
                    original_content = partial
                    original_content = partial.replace(route_text + "\n\n", "", 1) if partial.startswith(route_text) else partial
                    if not original_content.strip():
                        original_content = "⚠️ 模型未返回内容"

                    # 输出安全过滤
                    sec = get_security()
                    if sec:
                        og_result = sec["output_guard"].check(original_content)
                        if not og_result.ok:
                            filtered_content = og_result.filtered
                            # 用过滤后内容替换展示内容中的原始内容
                            partial = partial.replace(original_content, filtered_content, 1) if original_content in partial else partial
                            save_content = filtered_content
                            sec["audit"].log_security("output_filtered", "filtered", session_id=sid, level="info")
                        else:
                            save_content = original_content
                        sec["audit"].log_event("assistant_response", session_id=sid,
                                                detail={"length": len(save_content), "mode": "router",
                                                        "route": route_info.get("primary_model", "?")})
                    else:
                        save_content = original_content

                    memory.add_message(sid, "assistant", save_content)
                    if ms:
                        ms.add_message(sid, "assistant", save_content)

                    final_history = list(history) + [
                        gr.ChatMessage(role="user", content=message),
                        gr.ChatMessage(role="assistant", content=partial),
                    ]
                    yield "", final_history, memory.get_summary(sid), get_status_text()

                except Exception as e:
                    # 降级到直接 litellm 调用
                    logger.warning(f"路由系统调用失败，降级到直接调用: {e}")
                    try:
                        response = await call_llm(messages, model, temperature, stream=True)
                        partial = ""
                        async for chunk in response:
                            delta = chunk.choices[0].delta
                            if delta and delta.content:
                                partial += delta.content
                                new_history = list(history) + [
                                    gr.ChatMessage(role="user", content=message),
                                    gr.ChatMessage(role="assistant", content=partial),
                                ]
                                yield "", new_history, "", get_status_text()

                        if not partial:
                            partial = "⚠️ 模型未返回内容"

                        # 输出安全过滤
                        sec = get_security()
                        if sec:
                            og_result = sec["output_guard"].check(partial)
                            if not og_result.ok:
                                partial = og_result.filtered
                            sec["audit"].log_event("assistant_response", session_id=sid,
                                                    detail={"length": len(partial), "mode": "direct"})

                        memory.add_message(sid, "assistant", partial)
                        if ms:
                            ms.add_message(sid, "assistant", partial)
                        final_history = list(history) + [
                            gr.ChatMessage(role="user", content=message),
                            gr.ChatMessage(role="assistant", content=partial),
                        ]
                        yield "", final_history, memory.get_summary(sid), get_status_text()
                    except Exception as e2:
                        hint = "⚠️ 出错了：" + str(e2) + "\n\n💡 可能的原因：\n1. API Key 是否正确？→ 编辑 .env 文件\n2. 网络连接是否正常？→ 检查代理/防火墙\n3. 模型服务是否可用？→ 在「系统」页查看熔断状态\n\n🔧 尝试：点击清空按钮重新开始对话"
                        error_msg = hint
                        sec = get_security()
                        if sec:
                            sec["audit"].log_error("llm_error", session_id=sid, context={"error": str(e2)[:200]})
                        err_history = list(history) + [
                            gr.ChatMessage(role="user", content=message),
                            gr.ChatMessage(role="assistant", content=error_msg),
                        ]
                        yield "", err_history, memory.get_summary(sid), get_status_text()

        # ===== 多会话管理 =====
        def create_session(sid, existing, sid_list):
            import uuid
            new_sid = f"session_{datetime.now().strftime('%Y%m%d%H%M%S')}_{str(uuid.uuid4())[:8]}"
            session_list = list(sid_list) if sid_list else []
            session_list.append(new_sid)
            # 获取摘要
            ms = _get_ms()
            summary_text = ""
            return new_sid, session_list, gr.Dropdown(choices=session_list, value=new_sid), summary_text

        def switch_session(sid, sid_list):
            ms = _get_ms()
            summary_text = ms.l2.get_summary_text(sid) if ms and ms.l2 else ""
            return sid, summary_text

        def delete_session(sid, sid_list):
            ms = _get_ms()
            if ms:
                ms.clear_session(sid)
            session_list = list(sid_list) if sid_list else []
            if sid in session_list:
                session_list.remove(sid)
            if session_list:
                new_sid = session_list[-1]
                summary = ms.l2.get_summary_text(new_sid) if ms and ms.l2 else ""
                return new_sid, session_list, gr.Dropdown(choices=session_list, value=new_sid), [], summary
            else:
                new_sid = f"session_{datetime.now().strftime('%Y%m%d%H%M%S')}"
                session_list = [new_sid]
                return new_sid, session_list, gr.Dropdown(choices=session_list, value=new_sid), [], ""

        new_session_btn.click(
            fn=create_session,
            inputs=[session_id, session_id, session_list_state],
            outputs=[session_id, session_list_state, session_selector, memory_display],
        )

        user_selector.change(fn=lambda u: u, inputs=[user_selector], outputs=[user_id])
        session_selector.change(
            fn=switch_session,
            inputs=[session_selector, session_list_state],
            outputs=[session_id, memory_display],
        )

        del_session_btn.click(
            fn=delete_session,
            inputs=[session_id, session_list_state],
            outputs=[session_id, session_list_state, session_selector, chatbot, memory_display],
        )

        # 初始化会话列表
        def init_session_list(sid):
            return [sid]

        demo.load(fn=init_session_list, inputs=[session_id], outputs=[session_list_state])

        # 原有绑定事件
        msg_input.submit(
            respond,
            inputs=[msg_input, chatbot, model_dropdown, temperature_slider,
                    system_prompt_box, session_id, session_list_state],
            outputs=[msg_input, chatbot, memory_display, status_display],
        )

        send_btn.click(
            respond,
            inputs=[msg_input, chatbot, model_dropdown, temperature_slider,
                    system_prompt_box, session_id, session_list_state],
            outputs=[msg_input, chatbot, memory_display, status_display],
        )

        # 快捷示例按钮 — 填入 msg_input
        def fill_example(text):
            return text
        example_btn1.click(fn=lambda: "写一个 Python 异步爬虫，要求支持并发和重试", outputs=msg_input)
        example_btn2.click(fn=lambda: "分析这组数据的趋势并给出可视化建议", outputs=msg_input)
        example_btn3.click(fn=lambda: "帮我做一份 RAG 技术方案调研报告", outputs=msg_input)
        example_btn4.click(fn=lambda: "解释一下向量检索和 RRF 融合的原理", outputs=msg_input)

        def clear_chat(sid):
            memory.clear(sid)
            ms = _get_ms()
            if ms:
                ms.clear_session(sid)
            return [], ""

        clear_btn.click(
            clear_chat,
            inputs=[session_id],
            outputs=[chatbot, memory_display],
        )

        def export_chat(sid):
            import json, datetime
            ms = _get_ms()
            if not ms:
                return "No chat data", None
            msgs = ms.l1.get_messages(sid)
            if not msgs:
                return "No messages", None
            export = {
                "session_id": sid,
                "exported_at": datetime.datetime.now().isoformat(),
                "messages": [{"role": m.get("role"), "content": m.get("content")} for m in msgs]
            }
            json_str = json.dumps(export, ensure_ascii=False, indent=2)
            # Also create a markdown version
            md = f"# Chat Export: {sid}\n\n"
            for m in msgs:
                role = m.get("role", "unknown")
                content = m.get("content", "")
                md += f"## {role}\n{content}\n\n"
            return md, json_str

        export_btn.click(
            fn=export_chat,
            inputs=[session_id],
            outputs=[memory_display, msg_input],
        )

        # ===== 重新生成 / 编辑 =====
        def show_action_btns():
            return gr.update(visible=True), gr.update(visible=True)
        def hide_action_btns():
            return gr.update(visible=False), gr.update(visible=False)

        send_btn.click(fn=show_action_btns, inputs=[], outputs=[regenerate_btn, edit_btn])
        clear_btn.click(fn=hide_action_btns, inputs=[], outputs=[regenerate_btn, edit_btn])

        def do_regenerate(sid):
            ms = _get_ms()
            if ms:
                msgs = ms.l1.get_messages(sid)
                for m in reversed(msgs):
                    if m.get("role") == "user":
                        return m.get("content", "")
            return ""

        regenerate_btn.click(fn=do_regenerate, inputs=[session_id], outputs=[msg_input])
        edit_btn.click(fn=do_regenerate, inputs=[session_id], outputs=[msg_input])

        refresh_btn.click(
            fn=get_status_html,
            outputs=status_display,
        )

        # 模型切换
        def on_model_change(model):
            return model
        model_dropdown.change(on_model_change, inputs=[model_dropdown], outputs=[current_model])

        gr.HTML("""
        <div class="wanxiang-footer">
            <p>🐋 万象积木 v1.4 · 多模型路由 · 四层记忆 · Agent编排 · RAG · 安全防护</p>
        </div>
        """)

    return demo


# ---------------------------------------------------------------------------
# 启动
# ---------------------------------------------------------------------------

def main():
    # 确保 localhost 不走代理（Gradio 启动检查需要）
    no_proxy = os.environ.get("NO_PROXY", "")
    if "localhost" not in no_proxy:
        os.environ["NO_PROXY"] = f"{no_proxy},localhost,127.0.0.1".strip(",")
        os.environ["no_proxy"] = os.environ["NO_PROXY"]

    # 预加载子系统
    logger.info("🐳 万象积木启动中...")

    # 检查 API Key
    has_deepseek = bool(os.getenv("DEEPSEEK_API_KEY") and "你的" not in os.getenv("DEEPSEEK_API_KEY", ""))
    has_doubao = bool(os.getenv("DOUBAO_API_KEY") and "你的" not in os.getenv("DOUBAO_API_KEY", ""))

    if not has_deepseek and not has_doubao:
        logger.warning("⚠️ 未检测到有效的 API Key！请编辑 .env 文件填入 API Key")
        logger.warning("   DeepSeek 申请：https://platform.deepseek.com/")
        logger.warning("   豆包申请：https://www.volcengine.com/product/doubao")
    else:
        if has_deepseek:
            logger.info("✅ DeepSeek API Key 已配置")
        if has_doubao:
            logger.info("✅ 豆包 API Key 已配置")

    # 加载子系统
    get_model_router()
    get_memory_system()
    get_security()
    get_orchestrator()
    get_rag_pipeline()
    get_skill_runtime()

    # 构建 UI
    import gradio as gr
    demo = build_ui()

    # 启动
    logger.info("📖 访问地址：http://localhost:7860")
    demo.launch(
        server_name="0.0.0.0",
        server_port=7860,
        share=False,
        show_error=True,
        css=CUSTOM_CSS,
    )


if __name__ == "__main__":
    main()
