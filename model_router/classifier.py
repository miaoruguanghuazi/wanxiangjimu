"""
任务分类器 — LLM-free 规则引擎
基于关键词 + 正则匹配快速判断任务类型
"""

from __future__ import annotations

import re
import logging
from enum import Enum
from typing import Optional

logger = logging.getLogger(__name__)


class TaskType(str, Enum):
    CHAT = "chat"
    QA = "qa"
    CODE = "code"
    WRITING = "writing"
    REASONING = "reasoning"
    MULTIMODAL = "multimodal"
    LONG_CONTEXT = "long_context"


class TaskClassifier:
    """任务分类器 — 规则引擎"""

    PATTERNS: dict[TaskType, list[str]] = {
        TaskType.CODE: [
            r"写代码|写程序|生成代码|代码",
            r"\bdef\s|\bfunction\s|\bclass\s",
            r"debug|bug\s*fix|code\s*review",
            r"python|javascript|typescript|java|go\s+lang|rust",
            r"api\s*接口|接口文档|swagger",
            r"算法|排序|二分|递归|动态规划",
            r"正则|regex|sql",
        ],
        TaskType.REASONING: [
            r"分析|推理|证明|推导",
            r"为什么|原因是什么|逻辑",
            r"对比|比较|差异|优缺点",
            r"选择.*还是|判断.*是否",
            r"深层|复杂|详细",
            r"思考.*步|step\s+by\s+step",
            r"假如|如果.*会|假设",
        ],
        TaskType.WRITING: [
            r"写.*文章|写作|文案",
            r"帮我写|写一封|起草",
            r"小说|故事|剧本|歌词",
            r"总结|摘要|概括",
            r"润色|修改|改写",
            r"简历|报告|方案",
        ],
        TaskType.QA: [
            r"是什么|什么是",
            r"解释一下|请说明",
            r"请问|问一下",
            r"怎么用|如何使用",
            r"定义|概念|名词解释",
        ],
        TaskType.MULTIMODAL: [
            r"图片|照片|截图|图表",
            r"这张图|图片中|识别",
            r"视频|音频|语音",
            r"看图|分析这张|描述这张",
            r"\.png|\.jpg|\.jpeg|\.gif",
        ],
        TaskType.LONG_CONTEXT: [
            r"总结.*文档|全文|长文",
            r"分析.*报告|论文|书籍",
            r"一万字|两万字|长文本",
            r"读取.*文件|pdf|文档",
        ],
    }

    PRIORITY = [
        TaskType.CODE,
        TaskType.REASONING,
        TaskType.MULTIMODAL,
        TaskType.LONG_CONTEXT,
        TaskType.WRITING,
        TaskType.QA,
        TaskType.CHAT,
    ]

    def classify(self, message: str, attachments: list = None) -> TaskType:
        text = message.lower()

        if attachments:
            for att in attachments:
                att_type = att.get("type", "")
                if att_type in ("image", "audio", "video"):
                    return TaskType.MULTIMODAL

        for task_type in self.PRIORITY:
            for pattern in self.PATTERNS.get(task_type, []):
                if re.search(pattern, text, re.I):
                    return task_type

        return TaskType.CHAT

    @staticmethod
    def get_required_capabilities(task_type: TaskType) -> list[str]:
        mapping = {
            TaskType.CHAT: ["text"],
            TaskType.QA: ["text"],
            TaskType.CODE: ["code"],
            TaskType.WRITING: ["text"],
            TaskType.REASONING: ["reasoning"],
            TaskType.MULTIMODAL: ["multimodal_vision"],
            TaskType.LONG_CONTEXT: ["text"],
        }
        return mapping.get(task_type, ["text"])
