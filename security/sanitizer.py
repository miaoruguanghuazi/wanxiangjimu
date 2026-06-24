"""
敏感信息脱敏 — 正则检测 + 自动脱敏

检测: API Key, 密码, 邮箱, 手机号, 身份证, 银行卡, IP地址
脱敏: 部分遮蔽（保留前几位用于识别，中间用 * 替代）
"""

from __future__ import annotations

import re
import logging
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class SensitiveMatch:
    """敏感信息匹配结果"""
    type: str          # 类型: api_key, password, email, phone, id_card, bank_card, ip
    original: str      # 原始文本
    masked: str        # 脱敏后文本
    position: tuple    # (start, end)


# ============================================================
# 敏感信息正则模式
# ============================================================

PATTERNS = {
    # API Key 格式（OpenAI: sk-xxx, DeepSeek: sk-xxx, 通用: xxx_key=xxx）
    "api_key": [
        re.compile(r"sk-[a-zA-Z0-9]{20,}", re.I),
        re.compile(r"(?:api[_-]?key|secret[_-]?key)\s*[=:]\s*['\"]?[a-zA-Z0-9]{16,}['\"]?", re.I),
        re.compile(r"(?:Bearer)\s+[a-zA-Z0-9\._-]{20,}", re.I),
    ],
    # 密码赋值
    "password": [
        re.compile(r"(?:password|passwd|pwd)\s*[=:]\s*['\"]?[^\s'\"]{6,}['\"]?", re.I),
    ],
    # 邮箱
    "email": [
        re.compile(r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}"),
    ],
    # 中国手机号
    "phone": [
        re.compile(r"1[3-9]\d{9}"),
    ],
    # 身份证号（18位）
    "id_card": [
        re.compile(r"\b\d{17}[\dXx]\b"),
    ],
    # 银行卡号（16-19位数字）
    "bank_card": [
        re.compile(r"\b\d{16,19}\b"),
    ],
    # IP 地址
    "ip": [
        re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b"),
    ],
}


class Sanitizer:
    """
    敏感信息脱敏器

    用法:
        sanitizer = Sanitizer()
        clean = sanitizer.mask("我的邮箱是 test@example.com")
        # -> "我的邮箱是 t***@example.com"
        matches = sanitizer.detect("API Key: sk-abc123...")
        # -> [SensitiveMatch(type='api_key', ...)]
    """

    def __init__(self):
        self._stats = {"masked": 0, "detected": 0}

    def mask(self, text: str) -> str:
        """脱敏文本中的敏感信息"""
        result = text
        for info_type, patterns in PATTERNS.items():
            for pattern in patterns:
                result = pattern.sub(
                    lambda m: self._mask_value(m.group(), info_type),
                    result,
                )
        return result

    def detect(self, text: str) -> list[SensitiveMatch]:
        """检测文本中的敏感信息（不修改）"""
        matches = []
        for info_type, patterns in PATTERNS.items():
            for pattern in patterns:
                for m in pattern.finditer(text):
                    matches.append(SensitiveMatch(
                        type=info_type,
                        original=m.group(),
                        masked=self._mask_value(m.group(), info_type),
                        position=(m.start(), m.end()),
                    ))
        self._stats["detected"] += len(matches)
        return matches

    def is_safe_for_log(self, text: str) -> bool:
        """检查文本是否安全可入日志（不含敏感信息）"""
        return len(self.detect(text)) == 0

    def safe_log(self, text: str, max_length: int = 500) -> str:
        """返回脱敏后的安全日志文本"""
        masked = self.mask(text)
        if len(masked) > max_length:
            masked = masked[:max_length] + "..."
        self._stats["masked"] += 1
        return masked

    def _mask_value(self, value: str, info_type: str) -> str:
        """对单个敏感值进行脱敏"""
        if info_type == "email":
            parts = value.split("@")
            if len(parts) == 2:
                name = parts[0]
                if len(name) <= 2:
                    return f"{name[0]}***@{parts[1]}"
                return f"{name[:2]}***@{parts[1]}"
            return "***@***"

        if info_type == "phone":
            if len(value) == 11:
                return f"{value[:3]}****{value[-4:]}"

        if info_type == "id_card":
            if len(value) == 18:
                return f"{value[:6]}********{value[-4:]}"

        if info_type == "bank_card":
            if len(value) >= 16:
                return f"{value[:4]}****{value[-4:]}"

        if info_type == "ip":
            parts = value.split(".")
            if len(parts) == 4:
                return f"{parts[0]}.{parts[1]}.*.*"

        if info_type == "api_key":
            if len(value) > 8:
                return f"{value[:4]}***{value[-4:]}"

        if info_type == "password":
            # 提取 key=value 格式中的 value 并脱敏
            if "=" in value:
                key_part = value.split("=")[0] + "="
                val_part = value.split("=", 1)[1].strip("'\" ")
                return f"{key_part}***"
            if ":" in value:
                key_part = value.split(":")[0] + ":"
                val_part = value.split(":", 1)[1].strip("'\" ")
                return f"{key_part} ***"

        # 默认: 遮蔽中间部分
        if len(value) <= 4:
            return "****"
        return f"{value[:2]}***{value[-2:]}"

    def get_stats(self) -> dict:
        return self._stats.copy()
