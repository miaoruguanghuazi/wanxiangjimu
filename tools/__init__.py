"""
tools — 万象积木工具调用框架

提供：
  - BaseTool: 工具基类
  - ToolRegistry: 工具注册表
  - ToolExecutor: 工具执行器（带超时+错误处理）
  - 内置工具: web_search, code_execute, file_read, file_write, http_get
"""

from .base import BaseTool, ToolResult, ToolMetadata, Parameter, ParamType
from .registry import ToolRegistry, ToolExecutor
from .builtins import (
    WebSearchTool,
    CodeExecuteTool,
    FileReadTool,
    FileWriteTool,
    HTTPGetTool,
    DateTimeTool,
)

__all__ = [
    "BaseTool", "ToolResult", "ToolMetadata", "Parameter", "ParamType",
    "ToolRegistry", "ToolExecutor",
    "WebSearchTool", "CodeExecuteTool", "FileReadTool",
    "FileWriteTool", "HTTPGetTool", "DateTimeTool",
]

__version__ = "1.0.0"
