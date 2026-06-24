"""
记忆提取器 — 从对话中提取结构化记忆条目

使用 LLM 从对话内容中提取:
- 用户偏好 (preference)
- 客观事实 (fact)
- 事件日程 (event)
- 人物关系 (person)
"""

from __future__ import annotations

import json
import logging
from typing import Optional

from .models import MemoryEntry, MemoryType, SourceType, HALF_LIFE_MAP

logger = logging.getLogger(__name__)


EXTRACTION_PROMPT = """你是一个记忆提取专家。请从以下对话中提取值得长期记住的信息。

输出格式（JSON数组，如果没有值得记住的信息则返回空数组 []）:
[
  {
    "type": "preference",
    "category": "user_profile",
    "content": "用户偏好 Python，讨厌 Java",
    "importance": 0.8,
    "confidence": 0.9
  }
]

类型说明:
- preference: 用户的偏好、习惯、喜恶（importance 高）
- fact: 客观事实，如姓名、职业、项目信息
- event: 时间相关的事件，如日程、计划、里程碑
- person: 人物关系，如同事、朋友、家人

分类说明:
- user_profile: 用户个人信息
- domain_knowledge: 领域知识
- social: 社交关系
- task: 任务相关
- hobby: 爱好
- health: 健康
- location: 位置

提取规则:
- 明确表述（"我喜欢..."）→ confidence=1.0
- 推断得出（从对话推断）→ confidence=0.6-0.8
- 忽略寒暄、闲聊、无信息量的内容
- importance: preference 0.7-0.9, fact 0.6-0.8, event 0.5-0.7, person 0.4-0.6

只输出 JSON 数组，不要其他文字。

对话内容:
"""


class MemoryExtractor:
    """记忆提取器"""

    # 是否触发记忆提取的关键词
    EXPLICIT_PATTERNS = [
        "记住", "帮我记", "我偏好", "我喜欢", "我讨厌", "别忘了",
        "我叫", "名字是", "电话", "地址", "邮箱", "公司是",
        "我的项目", "我在做", "我用的是",
    ]

    def should_extract(self, message: str, turn_count: int, is_session_end: bool = False) -> bool:
        """判断是否应该触发记忆提取"""
        # 条件1: 用户明确要求记住
        for pattern in self.EXPLICIT_PATTERNS:
            if pattern in message:
                return True

        # 条件2: 会话结束
        if is_session_end:
            return True

        # 条件3: 每10轮提取一次
        if turn_count > 0 and turn_count % 10 == 0:
            return True

        return False

    async def extract(
        self,
        messages: list[dict],
        user_id: str = "default",
        session_id: str = "",
    ) -> list[MemoryEntry]:
        """
        从对话中提取记忆条目

        返回 MemoryEntry 列表（未写入存储，需调用方写入）
        """
        # 构建对话文本
        conversation = self._format_messages(messages)

        try:
            extracted = await self._llm_extract(conversation)
        except Exception as e:
            logger.error(f"LLM 记忆提取失败: {e}")
            return []

        results = []
        for item in extracted:
            memory_type = item.get("type", "fact")
            half_life = HALF_LIFE_MAP.get(MemoryType(memory_type), 90)

            entry = MemoryEntry(
                user_id=user_id,
                session_id=session_id,
                memory_type=memory_type,
                category=item.get("category", "user_profile"),
                content=item.get("content", ""),
                importance=float(item.get("importance", 0.5)),
                confidence=float(item.get("confidence", 0.8)),
                source_type=SourceType.AUTO_EXTRACT.value,
                half_life_days=half_life,
            )
            results.append(entry)

        logger.info(f"从对话中提取了 {len(results)} 条记忆")
        return results

    def _format_messages(self, messages: list[dict]) -> str:
        """格式化消息列表为文本"""
        lines = []
        for msg in messages:
            role = msg.get("role", "user")
            content = msg.get("content", "")
            if role == "system":
                continue
            label = "用户" if role == "user" else "助手"
            lines.append(f"{label}: {content}")
        return "\n".join(lines)

    async def _llm_extract(self, conversation: str) -> list[dict]:
        """调用 LLM 提取记忆"""
        import os

        prompt = EXTRACTION_PROMPT + conversation

        try:
            from litellm import acompletion
            model = os.getenv("DEFAULT_MODEL", "deepseek/deepseek-chat")
            response = await acompletion(
                model=model,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.1,
                max_tokens=2000,
            )
            text = response.choices[0].message.content or "[]"

            # 尝试解析 JSON
            # 处理可能的 markdown 代码块包裹
            text = text.strip()
            if text.startswith("```"):
                lines = text.split("\n")
                text = "\n".join(lines[1:-1]) if lines[-1].startswith("```") else "\n".join(lines[1:])

            return json.loads(text)
        except json.JSONDecodeError as e:
            logger.warning(f"记忆提取 JSON 解析失败: {e}")
            return []
        except Exception as e:
            logger.error(f"记忆提取 LLM 调用失败: {e}")
            return []


class CompressionEngine:
    """L1 → L2 压缩引擎：将旧消息压缩为摘要"""

    COMPRESSION_PROMPT = """请将以下对话压缩为简洁的摘要，保留关键信息和用户偏好。

要求:
- 保留用户的核心需求和偏好
- 保留关键的技术决策和事实
- 保留重要的事件和时间节点
- 去除寒暄和重复内容
- 控制在 200 字以内

对话内容:
"""

    async def compress(self, messages: list[dict]) -> str:
        """将消息列表压缩为摘要文本"""
        import os

        conversation = "\n".join(
            f"{'用户' if m.get('role') == 'user' else '助手'}: {m.get('content', '')[:200]}"
            for m in messages
            if m.get("role") != "system"
        )

        prompt = self.COMPRESSION_PROMPT + conversation

        try:
            from litellm import acompletion
            model = os.getenv("DEFAULT_MODEL", "deepseek/deepseek-chat")
            response = await acompletion(
                model=model,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.3,
                max_tokens=500,
            )
            return response.choices[0].message.content or ""
        except Exception as e:
            logger.error(f"记忆压缩失败: {e}")
            # 降级: 简单截取
            return "; ".join(
                m.get("content", "")[:50]
                for m in messages[-5:]
                if m.get("role") == "user"
            )
