"""
base.py — Skill SDK 核心接口
============================

定义所有 Skill 的基类、元数据结构、执行上下文和结果类型。

核心概念：
    - SkillManifest : Skill 自描述元数据（名称、版本、触发词、权限等）
    - SkillContext  : Skill 执行上下文（用户信息、参数、记忆、工具调用）
    - SkillResult   : Skill 执行结果（标准化输出格式）
    - BaseSkill     : 所有 Skill 必须继承的抽象基类
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional, Protocol

logger = logging.getLogger(__name__)


# ──────────────────────────────────────────────
# 异常定义
# ──────────────────────────────────────────────

class SkillError(Exception):
    """Skill 相关错误基类"""


class SkillNotFoundError(SkillError):
    """Skill 未找到"""

    def __init__(self, skill_id: str):
        super().__init__(f"Skill 未找到: {skill_id}")
        self.skill_id = skill_id


class SkillLoadError(SkillError):
    """Skill 加载失败"""


class SkillTimeoutError(SkillError):
    """Skill 执行超时"""

    def __init__(self, message: str):
        super().__init__(message)


class SkillValidationError(SkillError):
    """Skill 参数校验失败"""

    def __init__(self, field_name: str, reason: str):
        super().__init__(f"参数校验失败 [{field_name}]: {reason}")
        self.field_name = field_name
        self.reason = reason


# ──────────────────────────────────────────────
# 辅助协议（Protocol）
# ──────────────────────────────────────────────

class MemorySystem(Protocol):
    """记忆系统协议（供 SkillContext 引用）"""

    async def recall(self, query: str, top_k: int = 5) -> list[dict]:
        """检索相关记忆"""
        ...

    async def remember(self, content: str, metadata: dict = None) -> None:
        """写入记忆"""
        ...


class ToolResult(Protocol):
    """工具调用结果协议"""

    success: bool
    data: Any
    error: Optional[str]


# ──────────────────────────────────────────────
# SkillResult — 标准化执行结果
# ──────────────────────────────────────────────

class ResultStatus(Enum):
    """Skill 执行状态枚举"""
    SUCCESS = "success"
    FAILED = "failed"
    PARTIAL = "partial"          # 部分成功
    TIMEOUT = "timeout"
    CANCELLED = "cancelled"


@dataclass
class SkillResult:
    """
    Skill 执行结果（标准化输出）

    无论 Skill 内部返回什么，最终都会被包装成 SkillResult，
    方便 Orchestrator 统一处理。
    """
    status: ResultStatus = ResultStatus.SUCCESS
    data: Any = None                # 主要返回数据
    message: str = ""               # 人类可读消息
    metadata: dict = field(default_factory=dict)  # 额外元数据
    error: Optional[str] = None     # 错误信息（status != success 时）
    latency_ms: float = 0.0         # 执行耗时（毫秒）
    tokens_used: int = 0            # LLM Token 消耗

    def to_dict(self) -> dict:
        """转为字典"""
        return {
            "status": self.status.value,
            "data": self.data,
            "message": self.message,
            "metadata": self.metadata,
            "error": self.error,
            "latency_ms": self.latency_ms,
            "tokens_used": self.tokens_used,
        }

    @classmethod
    def success(cls, data: Any = None, message: str = "") -> "SkillResult":
        """快速构造成功结果"""
        return cls(status=ResultStatus.SUCCESS, data=data, message=message)

    @classmethod
    def failed(cls, error: str, data: Any = None) -> "SkillResult":
        """快速构造失败结果"""
        return cls(status=ResultStatus.FAILED, error=error, data=data)


# ──────────────────────────────────────────────
# SkillManifest — Skill 元数据
# ──────────────────────────────────────────────

@dataclass
class SkillManifest:
    """
    Skill 自描述元数据

    每个 Skill 必须声明自己的 manifest，供运行时进行：
    - 意图匹配（triggers）
    - 权限审计（permissions）
    - 配置校验（config_schema）
    - 配额控制（quota_limit）
    """
    skill_id: str                              # 唯一标识，如 "weather"
    name: str                                  # 显示名称，如 "天气查询"
    version: str                               # 语义化版本，如 "2.1.0"
    description: str                           # 简短描述
    author: str = "unknown"                    # 作者
    triggers: list[str] = field(default_factory=list)   # 触发词列表
    capabilities: list[str] = field(default_factory=list)  # 能力标签
    permissions: list[str] = field(default_factory=list)   # 权限声明
    sandbox: bool = True                        # 是否需要沙箱隔离
    quota_limit: int = 100                      # 每分钟最大调用次数
    config_schema: dict = field(default_factory=dict)  # 配置项 JSON Schema
    tags: list[str] = field(default_factory=list)      # 分类标签
    icon: str = "🔧"                           # 图标 emoji
    python_version: str = "3.12"               # 要求的 Python 版本
    dependencies: list[str] = field(default_factory=list)  # Python 依赖包

    def __post_init__(self):
        """校验必填字段"""
        if not self.skill_id:
            raise ValueError("skill_id 不能为空")
        if not self.name:
            raise ValueError("name 不能为空")
        if not self.version:
            raise ValueError("version 不能为空")

    def to_dict(self) -> dict:
        """转为字典"""
        return {
            "skill_id": self.skill_id,
            "name": self.name,
            "version": self.version,
            "description": self.description,
            "author": self.author,
            "triggers": self.triggers,
            "capabilities": self.capabilities,
            "permissions": self.permissions,
            "sandbox": self.sandbox,
            "quota_limit": self.quota_limit,
            "config_schema": self.config_schema,
            "tags": self.tags,
            "icon": self.icon,
            "python_version": self.python_version,
            "dependencies": self.dependencies,
        }


# ──────────────────────────────────────────────
# SkillContext — 执行上下文
# ──────────────────────────────────────────────

class SkillContext:
    """
    Skill 执行上下文

    封装 Skill 执行时所需的一切：
    - 用户信息（user_id, session_id, tenant_id）
    - 输入数据（message, params）
    - 记忆系统（memory）
    - 工具调用（call_tool）
    - LLM 调用（call_llm）

    Skill 通过 Context 访问外部资源，运行时可拦截并审计这些调用。
    """

    def __init__(
        self,
        user_id: str,
        session_id: str,
        tenant_id: str,
        message: str,
        params: Optional[dict] = None,
        memory: Optional[MemorySystem] = None,
    ):
        self.user_id = user_id
        self.session_id = session_id
        self.tenant_id = tenant_id
        self.message = message
        self.params = params or {}
        self.memory = memory
        self._tool_calls: list[dict] = []      # 工具调用审计日志
        self._llm_calls: list[dict] = []       # LLM 调用审计日志

    async def call_tool(self, tool_name: str, params: dict) -> ToolResult:
        """
        Skill 内部调用工具（受沙箱限制）

        所有工具调用都会被记录，便于审计和回放。
        子类可覆盖此方法以添加权限检查。
        """
        logger.debug(f"Skill 调用工具: {tool_name}, params={params}")
        self._tool_calls.append({
            "tool": tool_name,
            "params": params,
        })
        # 实际实现由运行时注入
        raise NotImplementedError("call_tool 需要由运行时注入实现")

    async def call_llm(self, prompt: str, model: str = "auto") -> str:
        """
        Skill 内部调用 LLM

        所有 LLM 调用都会被记录，用于成本追踪。
        """
        logger.debug(f"Skill 调用 LLM: model={model}, prompt={prompt[:100]}...")
        self._llm_calls.append({
            "model": model,
            "prompt": prompt,
        })
        # 实际实现由运行时注入
        raise NotImplementedError("call_llm 需要由运行时注入实现")

    def audit_trail(self) -> dict:
        """返回审计日志（工具调用 + LLM 调用）"""
        return {
            "tool_calls": self._tool_calls,
            "llm_calls": self._llm_calls,
        }


# ──────────────────────────────────────────────
# BaseSkill — 抽象基类
# ──────────────────────────────────────────────

class BaseSkill(ABC):
    """
    所有 Skill 必须继承的基类

    子类必须：
    1. 定义 manifest: SkillManifest
    2. 实现 execute(ctx: SkillContext) -> Any

    可选覆盖：
    - validate_params : 自定义参数校验
    - describe        : 自定义描述（供 NLU 匹配）
    - on_install      : 安装时初始化
    - on_uninstall    : 卸载时清理
    - on_upgrade      : 升级时迁移
    """

    manifest: SkillManifest  # 子类必须定义此属性

    def __init__(self, config: Optional[dict] = None):
        self.config: dict = config or {}
        self._initialized: bool = False

    @abstractmethod
    async def execute(self, ctx: SkillContext) -> Any:
        """
        Skill 核心执行逻辑

        返回值可以是：
        - str       : 纯文本回复
        - dict      : 结构化数据
        - list      : 列表数据
        - SkillResult : 标准化结果

        由调用方（PluginRuntime）负责将返回值统一包装为 SkillResult。
        """
        ...

    async def validate_params(self, params: dict) -> tuple[bool, str]:
        """
        校验输入参数

        默认实现基于 manifest.config_schema 做基本校验。
        子类可覆盖以实现更复杂的校验逻辑。

        返回: (is_valid, error_message)
        """
        if not self.manifest.config_schema:
            return True, ""

        for field_name, schema in self.manifest.config_schema.items():
            is_required = schema.get("required", False)
            if is_required and field_name not in params:
                # 如果该字段有默认值，可以跳过
                if "default" not in schema:
                    return False, f"缺少必填参数: {field_name}"

            if field_name in params:
                value = params[field_name]
                expected_type = schema.get("type")
                if expected_type:
                    type_map = {
                        "string": str,
                        "integer": int,
                        "float": (int, float),
                        "boolean": bool,
                        "list": list,
                        "dict": dict,
                    }
                    py_type = type_map.get(expected_type)
                    if py_type and not isinstance(value, py_type):
                        return False, f"参数 {field_name} 类型错误: 期望 {expected_type}, 得到 {type(value).__name__}"

                # 枚举值校验
                enum_values = schema.get("enum")
                if enum_values and value not in enum_values:
                    return False, f"参数 {field_name} 值 {value} 不在允许范围: {enum_values}"

        return True, ""

    async def describe(self) -> str:
        """
        返回自然语言描述（供 NLU 引擎匹配用）

        默认返回 manifest 中的基本信息，子类可覆盖以提供更丰富的描述。
        """
        return (
            f"{self.manifest.name} v{self.manifest.version}: "
            f"{self.manifest.description}\n"
            f"触发词: {', '.join(self.manifest.triggers)}\n"
            f"能力: {', '.join(self.manifest.capabilities)}"
        )

    async def on_install(self, config: Optional[dict] = None) -> dict:
        """
        安装钩子：初始化依赖、创建配置

        在 Skill 被加载到运行时后调用。子类可覆盖以执行
        自定义初始化逻辑（如创建数据库表、下载模型等）。
        """
        self.config = config or self.config
        self._initialized = True
        logger.info(f"Skill {self.manifest.skill_id} v{self.manifest.version} 安装完成")
        return {"status": "installed", "config": self.config}

    async def on_uninstall(self) -> dict:
        """
        卸载钩子：清理资源

        在 Skill 从运行时移除前调用。子类可覆盖以执行
        清理逻辑（如关闭连接、删除临时文件等）。
        """
        self._initialized = False
        logger.info(f"Skill {self.manifest.skill_id} 已卸载")
        return {"status": "uninstalled"}

    async def on_upgrade(self, old_version: str, new_config: Optional[dict] = None) -> dict:
        """
        升级钩子：数据迁移

        当 Skill 从旧版本升级时调用。子类可覆盖以执行
        数据迁移、配置转换等逻辑。

        Args:
            old_version: 旧版本号
            new_config:  新配置（可选）
        """
        self.config = new_config or self.config
        logger.info(
            f"Skill {self.manifest.skill_id} 从 {old_version} 升级到 {self.manifest.version}"
        )
        return {"status": "upgraded", "from": old_version, "to": self.manifest.version}

    def __repr__(self) -> str:
        return (
            f"<{self.__class__.__name__} "
            f"skill_id={self.manifest.skill_id!r} "
            f"version={self.manifest.version!r} "
            f"initialized={self._initialized}>"
        )
