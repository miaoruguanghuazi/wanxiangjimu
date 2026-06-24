"""
四层记忆系统 — 统一管理器

整合 L1~L4，提供统一接口:
- add_message(): 添加消息（自动触发压缩/提取）
- build_prompt(): 构建包含四层记忆的完整 prompt
- get_stats(): 获取统计信息
"""

from __future__ import annotations

import time
import logging
from typing import Optional

from .l1_working import WorkingMemoryManager
from .l2_short_term import ShortTermMemory
from .l3_long_term import LongTermMemory
from .l4_procedural import ProceduralMemory
from .extractor import MemoryExtractor, CompressionEngine
from .models import MemoryEntry, ScoredMemory, HALF_LIFE_MAP, MemoryType

logger = logging.getLogger(__name__)


class MemorySystem:
    """
    四层记忆系统统一管理器

    用法:
        memory = MemorySystem(chroma_client=chroma_client)
        memory.add_message(session_id, "user", "我喜欢Python")
        messages = memory.build_prompt(session_id, "帮我写代码", system_prompt)
    """

    def __init__(
        self,
        chroma_client=None,
        data_path: str = "./data",
    ):
        # L1 工作记忆（内存）
        self.l1 = WorkingMemoryManager()

        # L2 短期记忆（JSON 文件）
        self.l2 = ShortTermMemory(persist_path=f"{data_path}/short_term")

        # L3 长期记忆（ChromaDB）
        self.l3 = LongTermMemory(chroma_client=chroma_client)

        # L4 程序记忆（JSON 文件）
        self.l4 = ProceduralMemory(persist_path=f"{data_path}/procedural")

        # 提取器与压缩引擎
        self.extractor = MemoryExtractor()
        self.compressor = CompressionEngine()

        # 嵌入模型（用于 L3 向量化）
        self._embed_model = None
        self._init_embed_model()

    def _init_embed_model(self):
        """初始化嵌入模型（复用 RAG 的 sentence-transformers）"""
        try:
            from sentence_transformers import SentenceTransformer
            model_name = "all-MiniLM-L6-v2"
            self._embed_model = SentenceTransformer(model_name)
            logger.info(f"✅ 记忆系统嵌入模型已加载: {model_name}")
        except Exception as e:
            logger.warning(f"⚠️ 嵌入模型加载失败，长期记忆将无法向量化: {e}")

    def _embed(self, text: str) -> list[float]:
        """生成文本嵌入向量"""
        if self._embed_model:
            return self._embed_model.encode(text).tolist()
        return []

    def add_message(
        self,
        session_id: str,
        role: str,
        content: str,
        user_id: str = "default",
    ):
        """添加消息到工作记忆"""
        self.l1.add_message(session_id, role, content, user_id)
        if role == "user":
            self.l2.increment_turn(session_id, user_id)

    async def maybe_compress(self, session_id: str) -> bool:
        """
        检查并执行 L1→L2 压缩

        返回: 是否执行了压缩
        """
        wm = self.l1.get(session_id)
        if not wm.should_compress():
            return False

        overflow = wm.get_overflow_messages()
        if not overflow:
            return False

        logger.info(f"会话 {session_id} 触发记忆压缩: {len(overflow)} 条旧消息")

        # LLM 压缩
        summary = await self.compressor.compress(overflow)

        # 更新 L2 摘要
        existing = self.l2.get(session_id)
        if existing and existing.summary:
            full_summary = f"{existing.summary}\n{summary}"
        else:
            full_summary = summary
        self.l2.update_summary(session_id, full_summary)

        # 压缩 L1
        wm.compress(len(overflow))
        return True

    async def maybe_extract(self, session_id: str, user_id: str = "default") -> bool:
        """
        检查并执行 L2→L3 记忆提取

        返回: 是否执行了提取
        """
        wm = self.l1.get(session_id, user_id)
        last_msg = wm.get_recent(1)
        if not last_msg:
            return False

        last_content = last_msg[0].get("content", "")
        if not self.extractor.should_extract(last_content, wm.turn_count):
            return False

        logger.info(f"会话 {session_id} 触发记忆提取")

        # 获取最近的所有消息
        messages = wm.get_messages()
        entries = await self.extractor.extract(messages, user_id, session_id)

        if not entries:
            return False

        # 写入 L3
        for entry in entries:
            embedding = self._embed(entry.content)
            if embedding:
                await self.l3.store(entry, embedding)

        logger.info(f"会话 {session_id} 提取并存储了 {len(entries)} 条长期记忆")
        return True

    def retrieve_long_term(
        self,
        query: str,
        user_id: str = "default",
        top_k: int = 5,
    ) -> list[ScoredMemory]:
        """检索长期记忆"""
        # 优先用文本搜索（ChromaDB 内置 embedding）
        return self.l3.search_by_content_sync(query, user_id, top_k)

    def match_skill(self, message: str, user_id: str = "default"):
        """匹配程序记忆（Skill）"""
        return self.l4.match_skill(message, user_id)

    def build_prompt(
        self,
        session_id: str,
        current_message: str,
        base_system_prompt: str,
        user_id: str = "default",
        enable_long_term: bool = True,
        enable_short_term: bool = True,
        enable_skill: bool = True,
    ) -> list[dict]:
        """
        构建包含四层记忆的完整 prompt

        输出结构:
        [0] system (含长期记忆注入)
        [1] system (短期记忆摘要, 可选)
        [2] system (Skill 指令, 可选)
        [3..N-1] 工作记忆 (最近 N 轮)
        [N] 当前消息
        """
        messages = []

        # === L3 长期记忆检索 + 注入 ===
        memory_sections = []
        if enable_long_term:
            long_term = self.retrieve_long_term(current_message, user_id, top_k=5)
            if long_term:
                by_type = {}
                for m in long_term:
                    by_type.setdefault(m.memory_type, []).append(m)

                type_labels = {
                    "preference": "[用户偏好]",
                    "fact": "[用户事实]",
                    "event": "[近期事件]",
                    "person": "[人物关系]",
                    "skill_hint": "[技能提示]",
                }

                type_order = ["preference", "fact", "event", "person", "skill_hint"]
                ordered_items = []
                seen = set()
                for mt in type_order:
                    if mt in by_type:
                        for m in by_type[mt]:
                            if m.content not in seen:
                                seen.add(m.content)
                                ordered_items.append((mt, m))

                memory_sections.append("## 关于用户的信息")
                for mtype, m in ordered_items[:5]:
                    label = type_labels.get(mtype, f"[{mtype}]")
                    memory_sections.append(f"- {label} {m.content}")

        # 组装 system prompt
        enhanced_prompt = base_system_prompt
        if memory_sections:
            enhanced_prompt += "\n\n" + "\n".join(memory_sections)
            enhanced_prompt += (
                "\n\n你在回答时如果发现以上信息与当前问题相关，可以自然地引用它们来提供更贴心的回答。"
                "不要刻意说「我记得你说过」，直接融入回答即可。"
            )

        messages.append({"role": "system", "content": enhanced_prompt})

        # === L2 短期记忆注入 ===
        if enable_short_term:
            summary_text = self.l2.get_summary_text(session_id)
            if summary_text:
                messages.append({"role": "system", "content": summary_text})

        # === L4 程序记忆匹配 ===
        if enable_skill:
            skill = self.l4.match_skill(current_message, user_id)
            if skill:
                skill_text = f"[当前任务模式: {skill.description}]\n{skill.system_prompt}"
                messages.append({"role": "system", "content": skill_text})

        # === L1 工作记忆 ===
        working = self.l1.get_messages(session_id)
        # 去掉已经作为 system 注入的旧消息
        for msg in working:
            if msg.get("role") == "system":
                continue
            messages.append({"role": msg["role"], "content": msg["content"]})

        # === 当前消息 ===
        messages.append({"role": "user", "content": current_message})

        return messages

    def get_all_memories(self, user_id: str = "default", limit: int = 50) -> list[dict]:
        """获取用户所有长期记忆（用于管理界面展示）"""
        return self.l3.get_all(user_id=user_id, limit=limit)

    def delete_memory(self, memory_id: str) -> bool:
        """删除一条长期记忆"""
        try:
            self.l3.delete(memory_id)
            return True
        except Exception as e:
            logger.error(f"删除记忆失败: {e}")
            return False

    def clear_session(self, session_id: str):
        """清空会话记忆"""
        self.l1.clear(session_id)
        self.l2.close_session(session_id)

    def get_stats(self) -> dict:
        """获取四层记忆统计"""
        return {
            "L1_working": {
                "sessions": self.l1.session_count(),
            },
            "L2_short_term": {
                "summaries": self.l2.count(),
            },
            "L3_long_term": self.l3.get_stats(),
            "L4_procedural": {
                "skills": self.l4.count(),
            },
        }

    # 自动记忆提取的关键词规则（不依赖 LLM）
    AUTO_MEMORY_PATTERNS = {
        "preference": [
            "我喜欢", "我偏好", "我更喜欢", "我讨厌", "我不喜欢",
            "我习惯", "我常用", "我用的是", "我主要用",
        ],
        "fact": [
            "我叫", "我是", "我在", "我住在", "我的电话",
            "我的邮箱", "我公司", "我的项目", "我在做",
        ],
        "event": [
            "我计划", "我打算", "我要去", "我明天", "我下周",
            "我安排了", "我记得",
        ],
        "person": [
            "我同事", "我朋友", "我家", "我妈妈", "我爸爸",
            "我老婆", "我老公", "我孩子",
        ],
    }

    async def auto_extract_and_store(self, message: str, user_id: str = "default", session_id: str = "") -> int:
        """
        自动从用户消息中提取记忆并存储到 L3（规则引擎，不依赖 LLM）
        返回存储的记忆数量
        """
        count = 0
        for memory_type, patterns in self.AUTO_MEMORY_PATTERNS.items():
            for pattern in patterns:
                if pattern in message:
                    # 提取关键内容（取整句话）
                    start = message.find(pattern)
                    end = min(start + 80, len(message))
                    # 找到句号或结尾
                    for sep in "。！？.!?\n":
                        idx = message.find(sep, start)
                        if idx != -1 and idx < end:
                            end = idx + 1
                            break
                    content = message[start:end].strip()
                    if content:
                        await self.store_explicit_memory(
                            content=content,
                            memory_type=memory_type,
                            user_id=user_id,
                            session_id=session_id,
                            importance=0.7 if memory_type == "preference" else 0.6,
                        )
                        count += 1
                    break  # 每类只存一条
        if count > 0:
            logger.info(f"规则引擎自动提取并存储了 {count} 条记忆")
        return count

    async def store_explicit_memory(
        self,
        content: str,
        memory_type: str = "fact",
        user_id: str = "default",
        session_id: str = "",
        importance: float = 0.8,
    ) -> bool:
        """
        显式存储一条记忆（用户说"记住xxx"时调用）
        """
        half_life = HALF_LIFE_MAP.get(MemoryType(memory_type), 90)

        entry = MemoryEntry(
            user_id=user_id,
            session_id=session_id,
            memory_type=memory_type,
            content=content,
            importance=importance,
            confidence=1.0,
            source_type="user_stated",
            half_life_days=half_life,
        )

        embedding = self._embed(entry.content)
        if embedding:
            await self.l3.store(entry, embedding)
            return True
        else:
            logger.warning("嵌入模型不可用，无法存储长期记忆")
            return False
