"""
万象积木 — 插件市场 (Skill SDK + 热插拔运行时)
=====================================

模块概览：
    - base.py         : BaseSkill 基类、SkillManifest、SkillContext、SkillResult
    - weather_skill.py: WeatherSkill 示例实现
    - runtime.py      : PluginRuntime 热插拔运行时（安装/卸载/执行/升级）
    - sandbox.py      : SandboxManager 沙箱管理器（进程隔离 + 资源限制）
    - store.py        : SkillStore 仓库管理（下载/版本管理/依赖解析）
    - marketplace.py  : Marketplace API（浏览/搜索/评分/安装）

使用示例::

    from skill_market import PluginRuntime, SkillStore, SandboxManager

    store = SkillStore(repo_url="https://registry.jinli.ai")
    sandbox = SandboxManager()
    runtime = PluginRuntime(skill_store=store, sandbox_manager=sandbox)

    await runtime.install("weather", config={"api_key": "xxx"})
    result = await runtime.execute_skill("weather", ctx)
"""

from .base import (
    BaseSkill,
    SkillManifest,
    SkillContext,
    SkillResult,
    SkillError,
    SkillNotFoundError,
    SkillLoadError,
    SkillTimeoutError,
)
from .weather_skill import WeatherSkill
from .runtime import PluginRuntime
from .sandbox import SandboxManager
from .store import SkillStore, SkillPackage
from .marketplace import Marketplace

__all__ = [
    # base
    "BaseSkill",
    "SkillManifest",
    "SkillContext",
    "SkillResult",
    "SkillError",
    "SkillNotFoundError",
    "SkillLoadError",
    "SkillTimeoutError",
    # weather 示例
    "WeatherSkill",
    # 运行时
    "PluginRuntime",
    # 沙箱
    "SandboxManager",
    # 仓库
    "SkillStore",
    "SkillPackage",
    # 市场入口
    "Marketplace",
]

__version__ = "1.0.0"
