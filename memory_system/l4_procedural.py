"""
L4 程序记忆 — Skill/快捷指令固化

职责:
- 匹配用户意图到已注册的 Skill
- 存储用户自定义快捷指令
- 统计使用频率

简化版: 基于 JSON 文件存储，无需 PostgreSQL
"""

from __future__ import annotations

import json
import os
import time
import logging
from dataclasses import dataclass, field, asdict
from typing import Optional

logger = logging.getLogger(__name__)


@dataclass
class ProceduralSkill:
    """程序记忆条目 — Skill 定义"""
    id: str
    user_id: str = "default"
    skill_name: str = ""
    trigger_patterns: list = field(default_factory=list)
    description: str = ""
    workflow: dict = field(default_factory=dict)
    system_prompt: str = ""
    tools_required: list = field(default_factory=list)
    usage_count: int = 0
    auto_generated: bool = False
    version: int = 1
    enabled: bool = True
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict:
        return asdict(self)


class ProceduralMemory:
    """L4 程序记忆管理器"""

    def __init__(self, persist_path: str = "./data/procedural"):
        self.persist_path = persist_path
        self._skills: dict[str, ProceduralSkill] = {}
        os.makedirs(persist_path, exist_ok=True)
        self._load()

    def _file_path(self) -> str:
        return os.path.join(self.persist_path, "skills.json")

    def _load(self):
        path = self._file_path()
        if not os.path.exists(path):
            return
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            for skill_id, skill_data in data.items():
                self._skills[skill_id] = ProceduralSkill(**skill_data)
            logger.info(f"✅ 程序记忆已加载: {len(self._skills)} 个 Skill")
        except Exception as e:
            logger.warning(f"加载程序记忆失败: {e}")

    def _save(self):
        path = self._file_path()
        with open(path, "w", encoding="utf-8") as f:
            json.dump(
                {k: v.to_dict() for k, v in self._skills.items()},
                f, ensure_ascii=False, indent=2,
            )

    def register_skill(self, skill: ProceduralSkill):
        """注册新 Skill"""
        self._skills[skill.id] = skill
        self._save()
        logger.info(f"Skill 已注册: {skill.skill_name}")

    def match_skill(self, message: str, user_id: str = "default") -> Optional[ProceduralSkill]:
        """
        匹配用户消息到 Skill

        匹配规则: 关键词包含匹配
        """
        msg_lower = message.lower()
        for skill in self._skills.values():
            if not skill.enabled:
                continue
            if skill.user_id not in ("default", user_id, ""):
                continue
            for pattern in skill.trigger_patterns:
                ptype = pattern.get("type", "keyword")
                pvalue = pattern.get("value", "").lower()
                if ptype == "keyword" and pvalue in msg_lower:
                    skill.usage_count += 1
                    self._save()
                    return skill
                elif ptype == "exact" and msg_lower.strip() == pvalue:
                    skill.usage_count += 1
                    self._save()
                    return skill
        return None

    def list_skills(self, user_id: str = "default") -> list[dict]:
        """列出所有可用的 Skill"""
        result = []
        for skill in self._skills.values():
            if not skill.enabled:
                continue
            if skill.user_id not in ("default", user_id, ""):
                continue
            result.append(skill.to_dict())
        return result

    def delete_skill(self, skill_id: str) -> bool:
        if skill_id in self._skills:
            del self._skills[skill_id]
            self._save()
            return True
        return False

    def count(self) -> int:
        return len(self._skills)
