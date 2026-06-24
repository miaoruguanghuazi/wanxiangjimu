"""
生成 + 引用溯源层

基于 RAG 检索结果，使用 LLM 生成回答，并标注引用来源。
支持多模型路由（auto / GPT / Claude / 本地模型）。
"""

from __future__ import annotations

import logging
from typing import Any, Optional, Protocol

from .models import Chunk, RetrievalResult

logger = logging.getLogger(__name__)


# ──────────────────────────── ModelRouter 协议 ────────────────────────────

class ModelRouterProtocol(Protocol):
    """模型路由协议

    任何实现了 call 方法的对象都可以作为 ModelRouter 使用。
    """

    async def call(self, model: str, messages: list[dict[str, str]]) -> Any:
        """调用 LLM

        Args:
            model: 模型名称（"auto" | "gpt-4o" | "claude-3-opus" | ...）
            messages: 消息列表

        Returns:
            模型响应对象，需包含 content 属性
        """
        ...


# ──────────────────────────── 简单实现 ────────────────────────────

class SimpleModelRouter:
    """简单的模型路由实现

    通过 aiohttp 调用 OpenAI 兼容 API。
    可替换为更复杂的路由逻辑。
    """

    def __init__(
        self,
        api_base: str = "http://llm-gateway:8001/v1/chat/completions",
        api_key: str = "",
        default_model: str = "gpt-4o",
    ) -> None:
        """初始化

        Args:
            api_base: LLM API 地址
            api_key: API Key
            default_model: 默认模型
        """
        self.api_base = api_base
        self.api_key = api_key
        self.default_model = default_model

    async def call(self, model: str, messages: list[dict[str, str]]) -> Any:
        """调用 LLM

        Args:
            model: 模型名称（"auto" 时使用 default_model）
            messages: 消息列表

        Returns:
            响应对象
        """
        import aiohttp
        from dataclasses import dataclass

        actual_model: str = self.default_model if model == "auto" else model

        async with aiohttp.ClientSession() as session:
            resp = await session.post(
                self.api_base,
                json={
                    "model": actual_model,
                    "messages": messages,
                    "temperature": 0.3,
                    "max_tokens": 2048,
                },
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                },
                timeout=aiohttp.ClientTimeout(total=120),
            )
            if resp.status != 200:
                error_text = await resp.text()
                raise RuntimeError(f"LLM API 返回 {resp.status}: {error_text}")

            data: dict = await resp.json()
            content: str = data.get("choices", [{}])[0].get("message", {}).get("content", "")

            @dataclass
            class Response:
                content: str

            return Response(content=content)


# ──────────────────────────── RAGGenerator ────────────────────────────

class RAGGenerator:
    """RAG 生成器

    基于 RAG 检索结果生成回答，并标注引用来源。

    功能：
    1. 构建结构化上下文（含引用标记）
    2. 调用 LLM 生成回答
    3. 支持引用溯源（每个关键事实标注来源）
    4. 支持多轮对话（传入历史消息）

    Usage::

        generator = RAGGenerator(model_router=router)
        answer = await generator.generate(query="如何配置数据库", retrieval=result)
    """

    # 系统提示
    SYSTEM_PROMPT: str = (
        "你是万象积木 的知识问答助手，基于 RAG 知识库回答问题。"
        "你必须严格基于提供的上下文信息回答，不编造、不臆测。"
    )

    # 生成提示模板
    GENERATION_PROMPT: str = """请根据提供的上下文信息回答用户问题。

规则：
1. 仅基于提供的上下文信息回答，不要编造
2. 每个关键事实必须标注引用来源，格式：[来源: 文档名, 第X页, §章节]
3. 如果上下文不足以回答，明确说明"根据已有信息无法完全回答该问题"
4. 如果不同来源信息有冲突，列出不同来源的说法
5. 回答结构清晰，使用 Markdown 格式

上下文信息：
{context}

用户问题：{question}

请回答："""

    # 追问提示模板
    FOLLOW_UP_PROMPT: str = """基于之前的对话和新的上下文信息，请回答用户的追问。

之前的对话：
{history}

新的上下文信息：
{context}

用户追问：{question}

请回答："""

    def __init__(
        self,
        model_router: ModelRouterProtocol = None,
        model: str = "auto",
        max_context_chunks: int = 10,
        max_history_turns: int = 5,
    ) -> None:
        """初始化生成器

        Args:
            model_router: 模型路由器（实现了 call 方法）
            model: 默认模型名称
            max_context_chunks: 上下文中最多包含的切片数
            max_history_turns: 多轮对话保留的历史轮数
        """
        self.model_router = model_router or SimpleModelRouter()
        self.model = model
        self.max_context_chunks = max_context_chunks
        self.max_history_turns = max_history_turns

    # ──────────────────────────── 生成入口 ────────────────────────────

    async def generate(
        self,
        query: str,
        retrieval: RetrievalResult,
        model: Optional[str] = None,
        history: Optional[list[dict[str, str]]] = None,
    ) -> str:
        """生成回答

        Args:
            query: 用户查询
            retrieval: 检索结果
            model: 模型名称（None 使用默认）
            history: 对话历史 [{"role": "user", "content": "..."}, ...]

        Returns:
            LLM 生成的回答（含引用标记）
        """
        use_model: str = model or self.model

        # 1. 构建上下文（含引用标记）
        context: str = self._build_context(retrieval)

        # 2. 构建提示
        if history:
            history_text: str = self._format_history(history[-self.max_history_turns * 2:])
            prompt: str = self.FOLLOW_UP_PROMPT.format(
                history=history_text,
                context=context,
                question=query,
            )
        else:
            prompt = self.GENERATION_PROMPT.format(
                context=context,
                question=query,
            )

        # 3. 构建消息
        messages: list[dict[str, str]] = [
            {"role": "system", "content": self.SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
        ]

        # 4. 调用 LLM
        try:
            response = await self.model_router.call(use_model, messages)
            answer: str = response.content

            # 5. 追加引用列表
            citations: str = self._build_citation_list(retrieval)
            if citations:
                answer = answer.rstrip() + "\n\n---\n**引用来源：**\n" + citations

            return answer
        except Exception as e:
            logger.error(f"LLM 生成失败: {e}")
            return self._fallback_answer(query, retrieval, str(e))

    # ──────────────────────────── 上下文构建 ────────────────────────────

    def _build_context(self, retrieval: RetrievalResult) -> str:
        """构建结构化上下文

        将检索到的切片按顺序编号，附带引用标记。

        Args:
            retrieval: 检索结果

        Returns:
            格式化的上下文字符串
        """
        if not retrieval.chunks:
            return "（无可用上下文信息）"

        parts: list[str] = []
        for i, chunk in enumerate(retrieval.chunks[:self.max_context_chunks]):
            citation: str = self._format_citation(chunk, i + 1)
            parts.append(f"[{i + 1}] {chunk.content}\n{citation}")

        separator: str = "\n\n---\n\n"
        return separator.join(parts)

    # ──────────────────────────── 引用格式化 ────────────────────────────

    @staticmethod
    def _format_citation(chunk: Chunk, index: int) -> str:
        """格式化单个引用标记

        Args:
            chunk: 切片
            index: 编号

        Returns:
            引用字符串，如 "[来源: report.pdf, 第3页, §架构设计]"
        """
        # 尝试从 metadata 获取文件名
        doc_name: str = chunk.metadata.get("file_name", chunk.doc_id[:12] + "...")

        citation_parts: list[str] = [f"[来源{index}: {doc_name}"]

        if chunk.page:
            citation_parts.append(f"第{chunk.page}页")

        if chunk.section:
            citation_parts.append(f"§{chunk.section}")

        citation_parts.append(f"相似度={chunk.score:.3f}]")

        return ", ".join(citation_parts[:-1]) + ", " + citation_parts[-1]

    # ──────────────────────────── 引用列表 ────────────────────────────

    def _build_citation_list(self, retrieval: RetrievalResult) -> str:
        """构建完整引用列表

        Args:
            retrieval: 检索结果

        Returns:
            引用列表字符串
        """
        if not retrieval.chunks:
            return ""

        lines: list[str] = []
        for i, chunk in enumerate(retrieval.chunks[:self.max_context_chunks]):
            doc_name: str = chunk.metadata.get("file_name", chunk.doc_id[:12] + "...")
            line_parts: list[str] = [f"[{i + 1}] {doc_name}"]

            if chunk.page:
                line_parts.append(f"第{chunk.page}页")
            if chunk.section:
                line_parts.append(f"§{chunk.section}")
            line_parts.append(f"得分={chunk.score:.4f}")
            line_parts.append(f"类型={chunk.chunk_type}")

            lines.append(" | ".join(line_parts))

        return "\n".join(lines)

    # ──────────────────────────── 历史格式化 ────────────────────────────

    @staticmethod
    def _format_history(history: list[dict[str, str]]) -> str:
        """格式化对话历史

        Args:
            history: 历史消息列表

        Returns:
            格式化的历史文本
        """
        role_map: dict[str, str] = {
            "user": "用户",
            "assistant": "助手",
            "system": "系统",
        }
        lines: list[str] = []
        for msg in history:
            role: str = role_map.get(msg.get("role", ""), msg.get("role", ""))
            content: str = msg.get("content", "")
            lines.append(f"**{role}**: {content}")
        return "\n\n".join(lines)

    # ──────────────────────────── 降级回答 ────────────────────────────

    @staticmethod
    def _fallback_answer(query: str, retrieval: RetrievalResult, error: str) -> str:
        """LLM 生成失败时的降级回答

        直接拼接检索到的切片内容。

        Args:
            query: 用户查询
            retrieval: 检索结果
            error: 错误信息

        Returns:
            降级回答字符串
        """
        if not retrieval.chunks:
            return f"抱歉，生成回答时发生错误，且没有可用的检索结果。\n\n错误: {error}"

        parts: list[str] = [
            f"⚠️ LLM 生成失败（{error}），以下为检索到的相关内容：\n",
        ]
        for i, chunk in enumerate(retrieval.chunks[:5]):
            parts.append(f"**[{i + 1}]** {chunk.content[:500]}")
            if chunk.section:
                parts.append(f"  _来源: §{chunk.section}_")

        return "\n\n".join(parts)

    # ──────────────────────────── 流式生成 ────────────────────────────

    async def generate_stream(
        self,
        query: str,
        retrieval: RetrievalResult,
        model: Optional[str] = None,
        history: Optional[list[dict[str, str]]] = None,
    ):
        """流式生成回答

        逐 token 返回生成结果，适用于实时展示场景。

        Args:
            query: 用户查询
            retrieval: 检索结果
            model: 模型名称
            history: 对话历史

        Yields:
            str: 生成的文本片段
        """
        use_model: str = model or self.model
        context: str = self._build_context(retrieval)

        if history:
            history_text = self._format_history(history[-self.max_history_turns * 2:])
            prompt = self.FOLLOW_UP_PROMPT.format(
                history=history_text,
                context=context,
                question=query,
            )
        else:
            prompt = self.GENERATION_PROMPT.format(
                context=context,
                question=query,
            )

        messages: list[dict[str, str]] = [
            {"role": "system", "content": self.SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
        ]

        try:
            # 如果 model_router 支持 stream，则使用
            if hasattr(self.model_router, "call_stream"):
                async for token in self.model_router.call_stream(use_model, messages):
                    yield token
            else:
                # 降级为非流式
                response = await self.model_router.call(use_model, messages)
                yield response.content
        except Exception as e:
            yield self._fallback_answer(query, retrieval, str(e))
