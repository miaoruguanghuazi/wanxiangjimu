"""
智能切片层

多策略智能切片引擎：
- 语义分块：按段落/句子边界切分，512-1024 tokens
- 父子块层级：大块（父）→ 小块（子），检索命中小块但返回上下文大块
- 特殊处理：表格/代码块保持完整，不拆分
"""

from __future__ import annotations

import logging
import re
from typing import Any, Optional

from .models import Chunk, Document

logger = logging.getLogger(__name__)


class SmartChunker:
    """多策略智能切片引擎

    根据内容类型自动选择切片策略：
    - 文本：语义分块（按段落边界，带重叠）
    - 表格：保持完整
    - 代码：保持完整

    支持父子块层级：当一段内容被切分为多个子块时，自动创建父块。

    Usage::

        chunker = SmartChunker()
        chunks = await chunker.chunk(document)
    """

    # 切片参数
    DEFAULT_CHUNK_SIZE: int = 768       # 默认块大小（tokens）
    DEFAULT_OVERLAP: int = 128          # 重叠 tokens
    MIN_CHUNK_SIZE: int = 128           # 最小块
    MAX_CHUNK_SIZE: int = 1536          # 最大块
    PARENT_MAX_FACTOR: int = 2          # 父块最大长度因子（× MAX_CHUNK_SIZE）

    def __init__(
        self,
        chunk_size: int = None,
        overlap: int = None,
    ) -> None:
        """初始化切片器

        Args:
            chunk_size: 自定义块大小（tokens），None 使用默认值
            overlap: 自定义重叠大小（tokens），None 使用默认值
        """
        if chunk_size is not None:
            self.DEFAULT_CHUNK_SIZE = chunk_size
        if overlap is not None:
            self.DEFAULT_OVERLAP = overlap

    # ──────────────────────────── 公共入口 ────────────────────────────

    async def chunk(self, document: Document) -> list[Chunk]:
        """对文档进行智能切片

        Args:
            document: 待切片的文档

        Returns:
            切片列表（包含父块和子块）
        """
        # 1. 将文档内容拆分为语义段落
        sections: list[dict[str, Any]] = self._split_sections(document.content)

        all_chunks: list[Chunk] = []
        chunk_counter: int = 0

        for section in sections:
            # 2. 按类型分发切片策略
            if section["type"] == "table":
                chunks: list[Chunk] = self._chunk_table(section, document, chunk_counter)
            elif section["type"] == "code":
                chunks = self._chunk_code(section, document, chunk_counter)
            elif section["type"] == "heading":
                chunks = self._chunk_heading(section, document, chunk_counter)
            else:
                chunks = self._chunk_text(section, document, chunk_counter)

            chunk_counter += len(chunks)

            # 3. 多个子块时建立父子块关系
            if len(chunks) > 1:
                parent_chunk: Chunk = self._create_parent_chunk(chunks, document)
                for child in chunks:
                    child.parent_chunk_id = parent_chunk.chunk_id
                    parent_chunk.children_ids.append(child.chunk_id)
                all_chunks.append(parent_chunk)

            all_chunks.extend(chunks)

        logger.info(
            f"文档 {document.doc_id} 切片完成: "
            f"{len(sections)} 段落 → {len(all_chunks)} 切片"
        )
        return all_chunks

    # ──────────────────────────── 段落拆分 ────────────────────────────

    @staticmethod
    def _split_sections(content: str) -> list[dict[str, Any]]:
        """将文档内容拆分为带类型标记的段落

        识别代码块（```...```）、表格（| ... |）、标题（# ...）和普通文本。

        Args:
            content: 文档全文

        Returns:
            段落字典列表，每个包含 type, content, heading, page 等字段
        """
        sections: list[dict[str, Any]] = []
        lines: list[str] = content.split("\n")
        current_block: list[str] = []
        current_type: str = "text"
        current_heading: Optional[str] = None
        current_page: Optional[int] = None
        in_code_block: bool = False

        def _flush_block() -> None:
            """将当前缓存的内容作为一个段落输出"""
            nonlocal current_block, current_type
            if not current_block:
                return
            text = "\n".join(current_block).strip()
            if not text:
                current_block = []
                return

            # 检测表格（Markdown 表格至少两行，含 | 分隔）
            if current_type == "text" and _is_table(text):
                current_type = "table"

            sections.append({
                "type": current_type,
                "content": text,
                "heading": current_heading,
                "page": current_page,
                "doc_id": "",  # 后续填充
                "tenant_id": "",
                "metadata": {},
            })
            current_block = []
            current_type = "text"

        def _is_table(text: str) -> bool:
            """判断文本是否为 Markdown 表格"""
            tlines = text.strip().split("\n")
            if len(tlines) < 2:
                return False
            return all("|" in line and line.strip().startswith("|") for line in tlines[:2])

        for line in lines:
            # 页码标记
            page_match = re.match(r"\[Page (\d+)", line, re.IGNORECASE)
            if page_match:
                current_page = int(page_match.group(1))

            # OCR 标记
            if re.match(r"\[Page \d+ OCR\]", line, re.IGNORECASE):
                current_page = int(re.search(r"\d+", line).group())
                current_type = "text"
                current_block.append(line)
                continue

            # 代码块开始/结束
            if line.strip().startswith("```"):
                if in_code_block:
                    current_block.append(line)
                    _flush_block()
                    in_code_block = False
                    current_type = "text"
                else:
                    _flush_block()
                    in_code_block = True
                    current_type = "code"
                    current_block.append(line)
                continue

            if in_code_block:
                current_block.append(line)
                continue

            # 标题行
            heading_match = re.match(r"^(#{1,6})\s+(.+)", line)
            if heading_match:
                _flush_block()
                current_heading = heading_match.group(2).strip()
                sections.append({
                    "type": "heading",
                    "content": line,
                    "heading": current_heading,
                    "page": current_page,
                    "doc_id": "",
                    "tenant_id": "",
                    "metadata": {},
                })
                continue

            # 空行 → 段落边界
            if not line.strip():
                if current_block:
                    _flush_block()
                continue

            current_block.append(line)

        _flush_block()
        return sections

    # ──────────────────────────── 文本切片 ────────────────────────────

    def _chunk_text(
        self,
        section: dict[str, Any],
        document: Document,
        start_idx: int,
    ) -> list[Chunk]:
        """语义文本切片

        按段落边界切分，块大小达到阈值时输出。
        单段落超长时按句子切分。块间保留重叠。

        Args:
            section: 段落字典
            document: 所属文档
            start_idx: 起始编号

        Returns:
            切片列表
        """
        text: str = section["content"]
        paragraphs: list[str] = text.split("\n")

        chunks: list[Chunk] = []
        current_chunk: str = ""
        current_tokens: int = 0
        chunk_idx: int = 0

        for para in paragraphs:
            para = para.strip()
            if not para:
                continue

            para_tokens: int = self._count_tokens(para)

            # 单段落超长 → 按句子切分
            if para_tokens > self.MAX_CHUNK_SIZE:
                if current_chunk:
                    chunks.append(self._make_chunk(
                        current_chunk, section, document, start_idx + chunk_idx
                    ))
                    chunk_idx += 1
                    current_chunk = ""
                    current_tokens = 0

                sentence_chunks = self._chunk_long_paragraph(para, section, document, start_idx + chunk_idx)
                chunks.extend(sentence_chunks)
                chunk_idx += len(sentence_chunks)
                continue

            # 当前块 + 新段落超长 → 输出当前块，开始新块
            if current_tokens + para_tokens > self.DEFAULT_CHUNK_SIZE and current_chunk:
                chunks.append(self._make_chunk(
                    current_chunk, section, document, start_idx + chunk_idx
                ))
                chunk_idx += 1

                # 保留重叠：取当前块尾部
                overlap_text: str = self._get_overlap(current_chunk)
                current_chunk = overlap_text + "\n" + para if overlap_text else para
                current_tokens = self._count_tokens(current_chunk)
            else:
                current_chunk += "\n" + para if current_chunk else para
                current_tokens += para_tokens

        if current_chunk and current_chunk.strip():
            chunks.append(self._make_chunk(
                current_chunk, section, document, start_idx + chunk_idx
            ))

        return chunks

    def _chunk_long_paragraph(
        self,
        para: str,
        section: dict[str, Any],
        document: Document,
        start_idx: int,
    ) -> list[Chunk]:
        """超长段落按句子切分

        中文按句号/问号/叹号切分，英文按句号切分。

        Args:
            para: 超长段落文本
            section: 段落字典
            document: 所属文档
            start_idx: 起始编号

        Returns:
            切片列表
        """
        # 按句子切分（中文标点 + 英文标点）
        sentences: list[str] = re.split(r"(?<=[。！？.!?])\s*", para)
        sentences = [s.strip() for s in sentences if s.strip()]

        chunks: list[Chunk] = []
        current_chunk: str = ""
        current_tokens: int = 0
        chunk_idx: int = 0

        for sentence in sentences:
            sent_tokens: int = self._count_tokens(sentence)

            # 单句超长 → 强制按 token 数硬切
            if sent_tokens > self.MAX_CHUNK_SIZE:
                if current_chunk:
                    chunks.append(self._make_chunk(
                        current_chunk, section, document, start_idx + chunk_idx
                    ))
                    chunk_idx += 1
                    current_chunk = ""
                    current_tokens = 0

                # 硬切
                hard_chunks = self._hard_split(sentence, section, document, start_idx + chunk_idx)
                chunks.extend(hard_chunks)
                chunk_idx += len(hard_chunks)
                continue

            if current_tokens + sent_tokens > self.DEFAULT_CHUNK_SIZE and current_chunk:
                chunks.append(self._make_chunk(
                    current_chunk, section, document, start_idx + chunk_idx
                ))
                chunk_idx += 1
                overlap_text: str = self._get_overlap(current_chunk)
                current_chunk = overlap_text + " " + sentence if overlap_text else sentence
                current_tokens = self._count_tokens(current_chunk)
            else:
                current_chunk += " " + sentence if current_chunk else sentence
                current_tokens += sent_tokens

        if current_chunk and current_chunk.strip():
            chunks.append(self._make_chunk(
                current_chunk, section, document, start_idx + chunk_idx
            ))

        return chunks

    def _hard_split(
        self,
        text: str,
        section: dict[str, Any],
        document: Document,
        start_idx: int,
    ) -> list[Chunk]:
        """按字符数硬切分

        当句子本身超过 MAX_CHUNK_SIZE 时使用。

        Args:
            text: 超长文本
            section: 段落字典
            document: 所属文档
            start_idx: 起始编号

        Returns:
            切片列表
        """
        chunks: list[Chunk] = []
        # 按预估字符数切分（4 字符 ≈ 1 token）
        max_chars: int = self.MAX_CHUNK_SIZE * 3  # 安全系数
        chunk_idx: int = 0

        for i in range(0, len(text), max_chars):
            piece: str = text[i:i + max_chars]
            chunks.append(self._make_chunk(
                piece, section, document, start_idx + chunk_idx
            ))
            chunk_idx += 1

        return chunks

    # ──────────────────────────── 表格切片 ────────────────────────────

    def _chunk_table(
        self,
        section: dict[str, Any],
        document: Document,
        start_idx: int,
    ) -> list[Chunk]:
        """表格切片：保持表格完整，不拆分

        Args:
            section: 段落字典
            document: 所属文档
            start_idx: 起始编号

        Returns:
            包含单个表格切片的列表
        """
        return [
            self._make_chunk(
                section["content"], section, document, start_idx, chunk_type="table"
            )
        ]

    # ──────────────────────────── 代码切片 ────────────────────────────

    def _chunk_code(
        self,
        section: dict[str, Any],
        document: Document,
        start_idx: int,
    ) -> list[Chunk]:
        """代码切片：保持代码块完整

        Args:
            section: 段落字典
            document: 所属文档
            start_idx: 起始编号

        Returns:
            包含单个代码切片的列表
        """
        return [
            self._make_chunk(
                section["content"], section, document, start_idx, chunk_type="code"
            )
        ]

    # ──────────────────────────── 标题切片 ────────────────────────────

    def _chunk_heading(
        self,
        section: dict[str, Any],
        document: Document,
        start_idx: int,
    ) -> list[Chunk]:
        """标题切片

        Args:
            section: 段落字典
            document: 所属文档
            start_idx: 起始编号

        Returns:
            包含单个标题切片的列表
        """
        return [
            self._make_chunk(
                section["content"], section, document, start_idx, chunk_type="heading"
            )
        ]

    # ──────────────────────────── 父块创建 ────────────────────────────

    def _create_parent_chunk(
        self,
        children: list[Chunk],
        document: Document,
    ) -> Chunk:
        """创建父块

        合并所有子块内容，父块可以更长（最多 MAX_CHUNK_SIZE × PARENT_MAX_FACTOR）。
        父块用于在检索命中小块时提供更完整的上下文。

        Args:
            children: 子块列表
            document: 所属文档

        Returns:
            父块 Chunk
        """
        combined: str = "\n\n".join(c.content for c in children)
        max_parent_len: int = self.MAX_CHUNK_SIZE * self.PARENT_MAX_FACTOR

        # 截断保护
        if len(combined) > max_parent_len * 4:  # 字符级保护
            combined = combined[:max_parent_len * 4]

        first_child: Chunk = children[0]
        parent_id: str = f"{document.doc_id}_parent_{first_child.chunk_id[-8:]}"

        return Chunk(
            chunk_id=parent_id,
            doc_id=document.doc_id,
            tenant_id=document.tenant_id,
            content=combined,
            chunk_type="parent",
            parent_chunk_id=None,
            children_ids=[c.chunk_id for c in children],
            page=first_child.page,
            section=first_child.section,
            token_count=self._count_tokens(combined),
            embedding=[],  # 延迟向量化
            metadata={
                "child_count": len(children),
                "child_ids": [c.chunk_id for c in children],
            },
            score=0.0,
        )

    # ──────────────────────────── Chunk 构建 ────────────────────────────

    def _make_chunk(
        self,
        text: str,
        section: dict[str, Any],
        document: Document,
        idx: int,
        chunk_type: str = "text",
    ) -> Chunk:
        """构建单个 Chunk

        Args:
            text: 切片文本
            section: 段落字典
            document: 所属文档
            idx: 编号
            chunk_type: 切片类型

        Returns:
            Chunk 对象
        """
        chunk_id: str = f"{document.doc_id}_chunk_{idx:04d}"
        return Chunk(
            chunk_id=chunk_id,
            doc_id=document.doc_id,
            tenant_id=document.tenant_id,
            content=text.strip(),
            chunk_type=chunk_type,
            parent_chunk_id=None,
            children_ids=[],
            page=section.get("page"),
            section=section.get("heading"),
            token_count=self._count_tokens(text),
            embedding=[],  # 延迟向量化
            metadata=section.get("metadata", {}),
            score=0.0,
        )

    # ──────────────────────────── 工具方法 ────────────────────────────

    def _get_overlap(self, text: str) -> str:
        """获取重叠文本

        从当前块尾部取约 DEFAULT_OVERLAP tokens 的文本作为下一块的开头。

        Args:
            text: 当前块文本

        Returns:
            重叠文本
        """
        if not text:
            return ""
        # 粗略估算：DEFAULT_OVERLAP tokens ≈ DEFAULT_OVERLAP * 4 字符（中文 1:1，英文 1:4）
        char_count: int = self.DEFAULT_OVERLAP * 3
        if len(text) <= char_count:
            return text
        return text[-char_count:]

    @staticmethod
    def _count_tokens(text: str) -> int:
        """粗略估算 token 数量

        中文 1 字 ≈ 1 token，英文 1 词 ≈ 1.3 tokens。

        Args:
            text: 文本

        Returns:
            token 数量
        """
        if not text:
            return 0
        chinese_chars: int = sum(1 for c in text if "\u4e00" <= c <= "\u9fff")
        english_words: int = len(re.findall(r"[a-zA-Z]+", text))
        return int(chinese_chars + english_words * 1.3)
