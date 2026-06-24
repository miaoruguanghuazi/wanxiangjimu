"""
base.py — 工具基类和数据模型

所有工具继承 BaseTool，实现 execute() 方法。
工具通过 ToolMetadata 声明自己的能力，供 LLM 做工具选择。
"""

from __future__ import annotations

import abc
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class ParamType(str, Enum):
    STRING = "string"
    INTEGER = "integer"
    FLOAT = "float"
    BOOLEAN = "boolean"
    ARRAY = "array"
    OBJECT = "object"


@dataclass
class Parameter:
    """工具参数定义"""
    name: str
    type: ParamType
    description: str
    required: bool = False
    default: Any = None
    min_value: float | None = None
    max_value: float | None = None
    min_length: int | None = None
    max_length: int | None = None
    enum: list[str] | None = None

    def to_json_schema(self) -> dict:
        """转换为 JSON Schema 片段"""
        schema: dict = {"type": self.type.value, "description": self.description}
        if self.default is not None:
            schema["default"] = self.default
        if self.min_value is not None:
            schema["minimum"] = self.min_value
        if self.max_value is not None:
            schema["maximum"] = self.max_value
        if self.enum:
            schema["enum"] = self.enum
        return schema


@dataclass
class ToolMetadata:
    """工具元数据"""
    name: str
    description: str
    category: str = "general"
    version: str = "1.0.0"
    tags: list[str] = field(default_factory=list)
    examples: list[str] = field(default_factory=list)
    parameters: list[Parameter] = field(default_factory=list)
    timeout: float = 30.0

    def to_openai_function(self) -> dict:
        """转换为 OpenAI function calling 格式"""
        properties = {}
        required = []
        for p in self.parameters:
            properties[p.name] = p.to_json_schema()
            if p.required:
                required.append(p.name)

        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": {
                    "type": "object",
                    "properties": properties,
                    "required": required,
                },
            },
        }


@dataclass
class ToolResult:
    """工具执行结果"""
    success: bool
    output: str
    data: Any = None
    error: str | None = None
    duration: float = 0.0

    def to_dict(self) -> dict:
        return {
            "success": self.success,
            "output": self.output,
            "data": self.data,
            "error": self.error,
            "duration": self.duration,
        }


class BaseTool(abc.ABC):
    """工具基类 — 所有工具必须继承"""

    metadata: ToolMetadata

    @abc.abstractmethod
    async def execute(self, **kwargs) -> ToolResult:
        """执行工具，子类必须实现"""
        ...

    def get_openai_schema(self) -> dict:
        """获取 OpenAI function calling 格式的 schema"""
        return self.metadata.to_openai_function()

    def validate_params(self, params: dict) -> list[str]:
        """参数校验，返回错误列表（空列表=通过）"""
        errors = []
        param_map = {p.name: p for p in self.metadata.parameters}

        for name, param_def in param_map.items():
            if param_def.required and name not in params:
                errors.append(f"缺少必填参数: {name}")

        for name, value in params.items():
            if name not in param_map:
                errors.append(f"未知参数: {name}")
                continue
            p = param_map[name]
            if p.type == ParamType.STRING and not isinstance(value, str):
                errors.append(f"参数 {name} 应为字符串")
            elif p.type == ParamType.INTEGER and not isinstance(value, int):
                errors.append(f"参数 {name} 应为整数")
            elif p.type == ParamType.BOOLEAN and not isinstance(value, bool):
                errors.append(f"参数 {name} 应为布尔值")
            if p.enum and value not in p.enum:
                errors.append(f"参数 {name} 的值必须是 {p.enum} 之一")

        return errors
