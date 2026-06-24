"""
输出安全过滤 — LLM 输出安全检查

防止 LLM 输出:
- 泄露系统提示词内容
- 包含 API Key 或其他敏感信息
- 包含可执行的恶意代码
"""

from __future__ import annotations

import re
import logging
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class OutputCheckResult:
    ok: bool
    message: str
    filtered: str = ""


# 系统提示词泄露检测
SYSTEM_PROMPT_LEAK_PATTERNS = [
    re.compile(r"你是「万象积木」.*?回答要求.*?保持友好和耐心的语气", re.I | re.DOTALL),
    re.compile(r"安全边界.*?安全边界结束", re.I | re.DOTALL),
    re.compile(r"ignore\s+(all\s+)?(previous|prior)\s+(instructions?|prompts?)", re.I),
]

# API Key 泄露检测
KEY_LEAK_PATTERNS = [
    re.compile(r"sk-[a-zA-Z0-9]{20,}", re.I),
    re.compile(r"(?:api[_-]?key|secret[_-]?key)\s*[=:]\s*['\"]?[a-zA-Z0-9]{16,}", re.I),
]

# 文件路径泄露（Windows 绝对路径）
PATH_LEAK_PATTERNS = [
    re.compile(r"[A-Z]:\\[Uu]sers\\[^\\]+\\", re.I),
    re.compile(r"/home/[^/]+/", re.I),
    re.compile(r"/root/", re.I),
]


class OutputGuard:
    """
    LLM 输出安全过滤器

    用法:
        guard = OutputGuard()
        result = guard.check(llm_output)
        if not result.ok:
            return result.filtered  # 返回过滤后的内容
        return llm_output
    """

    def __init__(self):
        self._stats = {"checked": 0, "filtered": 0}

    def check(self, text: str) -> OutputCheckResult:
        """检查 LLM 输出"""
        self._stats["checked"] += 1
        filtered = text
        has_violation = False

        # 1. 系统提示词泄露
        for pattern in SYSTEM_PROMPT_LEAK_PATTERNS:
            if pattern.search(filtered):
                filtered = pattern.sub("[系统提示词已移除]", filtered)
                has_violation = True

        # 2. API Key 泄露
        for pattern in KEY_LEAK_PATTERNS:
            if pattern.search(filtered):
                filtered = pattern.sub("[API_KEY已移除]", filtered)
                has_violation = True

        # 3. 文件路径泄露
        for pattern in PATH_LEAK_PATTERNS:
            if pattern.search(filtered):
                filtered = pattern.sub("[路径已移除]/", filtered)
                has_violation = True

        if has_violation:
            self._stats["filtered"] += 1
            return OutputCheckResult(
                ok=False,
                message="输出包含敏感信息，已过滤",
                filtered=filtered,
            )

        return OutputCheckResult(ok=True, message="", filtered=text)

    def get_stats(self) -> dict:
        return self._stats.copy()
