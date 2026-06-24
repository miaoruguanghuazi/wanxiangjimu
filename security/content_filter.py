"""
内容安全过滤 — 敏感话题 + 恶意内容过滤

检测:
- 违法犯罪相关
- 暴力/伤害相关
- 个人隐私窃取（社工攻击）
- 恶意代码请求
"""

from __future__ import annotations

import re
import logging
from dataclasses import dataclass
from enum import Enum

logger = logging.getLogger(__name__)


class ContentLevel(str, Enum):
    SAFE = "safe"
    WARNING = "warning"
    BLOCKED = "blocked"


@dataclass
class ContentResult:
    ok: bool
    level: ContentLevel
    message: str
    flags: list[str] = None

    def __post_init__(self):
        if self.flags is None:
            self.flags = []


# 违法犯罪相关
ILLEGAL_PATTERNS = [
    re.compile(r"(制造|合成|制作|提炼).{0,10}(炸弹|爆炸物|毒品|违禁药)", re.I),
    re.compile(r"(如何|怎么|方法).{0,10}(洗钱|逃税|漏税|行贿|受贿)", re.I),
    re.compile(r"(入侵|攻击|黑掉).{0,10}(银行|政府|军事|电力|水利)", re.I),
    re.compile(r"(伪造|变造).{0,10}(身份证|护照|印章|货币)", re.I),
    re.compile(r"(购买|出售|交易).{0,10}(毒品|枪支|弹药|管制刀具)", re.I),
]

# 暴力/伤害
VIOLENCE_PATTERNS = [
    re.compile(r"(如何|怎么|方法).{0,10}(自杀|自残|自伤)", re.I),
    re.compile(r"(伤害|杀害|攻击|绑架).{0,10}(他人|别人|某人|特定人)", re.I),
    re.compile(r"(制造|获取|使用).{0,10}(武器|毒药|致命)", re.I),
]

# 社工攻击
SOCIAL_ENGINEERING_PATTERNS = [
    re.compile(r"(获取|查到|知道).{0,10}(他人|别人|某人).{0,10}(密码|账号|身份|手机号|地址)", re.I),
    re.compile(r"(冒充|伪装).{0,10}(他人|别人|官方|客服|警察)", re.I),
    re.compile(r"(社工|社会工程学).{0,10}(攻击|手段|方法)", re.I),
]

# 恶意代码请求
MALWARE_PATTERNS = [
    re.compile(r"(写|生成|创建|开发).{0,10}(病毒|木马|后门|勒索软件|恶意软件|rootkit)", re.I),
    re.compile(r"(绕过|突破|破解).{0,10}(杀毒|防火墙|安全软件|检测)", re.I),
]


class ContentFilter:
    """
    内容安全过滤器

    用法:
        f = ContentFilter()
        result = f.check("帮我写一个病毒")
        if not result.ok:
            return result.message
    """

    def __init__(self):
        self._stats = {"checked": 0, "blocked": 0, "warning": 0}

    def check(self, text: str) -> ContentResult:
        """检查内容安全性"""
        self._stats["checked"] += 1
        flags = []

        # 违法犯罪 — 直接拦截
        for pattern in ILLEGAL_PATTERNS:
            if pattern.search(text):
                flags.append(f"违法犯罪: {pattern.pattern[:30]}...")

        # 暴力伤害 — 直接拦截
        for pattern in VIOLENCE_PATTERNS:
            if pattern.search(text):
                flags.append(f"暴力伤害: {pattern.pattern[:30]}...")

        if flags:
            self._stats["blocked"] += 1
            return ContentResult(
                ok=False,
                level=ContentLevel.BLOCKED,
                message="⚠️ 您的请求涉及违法或有害内容，我无法协助处理。",
                flags=flags,
            )

        # 社工攻击 — 拦截
        for pattern in SOCIAL_ENGINEERING_PATTERNS:
            if pattern.search(text):
                flags.append(f"社工攻击: {pattern.pattern[:30]}...")

        # 恶意代码 — 拦截
        for pattern in MALWARE_PATTERNS:
            if pattern.search(text):
                flags.append(f"恶意代码: {pattern.pattern[:30]}...")

        if flags:
            self._stats["blocked"] += 1
            return ContentResult(
                ok=False,
                level=ContentLevel.BLOCKED,
                message="⚠️ 您的请求涉及安全风险内容，我无法协助处理。",
                flags=flags,
            )

        return ContentResult(
            ok=True,
            level=ContentLevel.SAFE,
            message="",
            flags=[],
        )

    def get_stats(self) -> dict:
        return self._stats.copy()
