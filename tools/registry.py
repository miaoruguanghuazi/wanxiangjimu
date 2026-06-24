"""
registry.py — 工具注册表 + 执行器

ToolRegistry: 注册、查询工具
ToolExecutor: 执行工具调用（带超时、重试、错误处理）
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

from .base import BaseTool, ToolResult, ToolMetadata

logger = logging.getLogger(__name__)


class ToolRegistry:
    """工具注册表"""

    def __init__(self) -> None:
        self._tools: dict[str, BaseTool] = {}

    def register(self, tool: BaseTool) -> None:
        """注册工具"""
        name = tool.metadata.name
        if name in self._tools:
            logger.warning(f"工具 {name} 已存在，将被覆盖")
        self._tools[name] = tool
        logger.info(f"已注册工具: {name}")

    def unregister(self, name: str) -> bool:
        """注销工具"""
        if name in self._tools:
            del self._tools[name]
            return True
        return False

    def get(self, name: str) -> BaseTool | None:
        """获取工具实例"""
        return self._tools.get(name)

    def list_all(self) -> list[BaseTool]:
        """列出所有工具"""
        return list(self._tools.values())

    def list_names(self) -> list[str]:
        """列出所有工具名"""
        return list(self._tools.keys())

    def get_openai_schemas(self) -> list[dict]:
        """获取所有工具的 OpenAI function calling schema"""
        return [t.get_openai_schema() for t in self._tools.values()]


class ToolExecutor:
    """
    工具执行器

    特性：
    - 异步执行
    - 超时控制
    - 参数校验
    - 错误处理
    - 执行日志
    - 安全审计
    """

    def __init__(self, registry: ToolRegistry, default_timeout: float = 30.0) -> None:
        self.registry = registry
        self.default_timeout = default_timeout
        self._call_log: list[dict] = []
        self._audit: Any = None

    def set_audit_logger(self, audit) -> None:
        """注入审计日志器"""
        self._audit = audit

    async def execute(self, tool_name: str, params: dict) -> ToolResult:
        """
        执行工具调用

        Args:
            tool_name: 工具名称
            params: 调用参数

        Returns:
            ToolResult 执行结果
        """
        tool = self.registry.get(tool_name)
        if tool is None:
            return ToolResult(
                success=False,
                output="",
                error=f"工具不存在: {tool_name}",
            )

        # 参数校验
        errors = tool.validate_params(params)
        if errors:
            return ToolResult(
                success=False,
                output="",
                error=f"参数校验失败: {'; '.join(errors)}",
            )

        # 执行（带超时）
        timeout = tool.metadata.timeout or self.default_timeout
        start = time.time()

        try:
            result = await asyncio.wait_for(
                tool.execute(**params),
                timeout=timeout,
            )
            result.duration = time.time() - start

            # 记录调用日志
            self._call_log.append({
                "tool": tool_name,
                "params": params,
                "success": result.success,
                "duration": result.duration,
                "timestamp": time.time(),
            })

            # 🔒 审计日志
            if self._audit:
                try:
                    self._audit.log_tool_call(
                        tool_name=tool_name,
                        session_id=params.get("_session_id", "unknown"),
                        result="success" if result.success else "failed",
                        duration=result.duration,
                    )
                except Exception:
                    pass

            return result

        except asyncio.TimeoutError:
            duration = time.time() - start
            logger.warning(f"工具 {tool_name} 超时 ({duration:.1f}s)")
            if self._audit:
                try:
                    self._audit.log_tool_call(
                        tool_name=tool_name,
                        session_id=params.get("_session_id", "unknown"),
                        result="timeout",
                        duration=duration,
                    )
                except Exception:
                    pass
            return ToolResult(
                success=False,
                output="",
                error=f"工具执行超时（{timeout}s）",
                duration=duration,
            )
        except Exception as e:
            duration = time.time() - start
            logger.error(f"工具 {tool_name} 执行异常: {e}")
            if self._audit:
                try:
                    self._audit.log_tool_call(
                        tool_name=tool_name,
                        session_id=params.get("_session_id", "unknown"),
                        result="error",
                        duration=duration,
                    )
                except Exception:
                    pass
            return ToolResult(
                success=False,
                output="",
                error=f"执行异常: {str(e)}",
                duration=duration,
            )

    def get_call_log(self, limit: int = 50) -> list[dict]:
        """获取调用日志"""
        return self._call_log[-limit:]


def create_default_registry() -> ToolRegistry:
    """创建默认工具注册表（注册所有内置工具）"""
    from .builtins import (
        WebSearchTool, CodeExecuteTool, FileReadTool,
        FileWriteTool, HTTPGetTool, DateTimeTool,
    )

    registry = ToolRegistry()
    for tool_cls in [
        WebSearchTool,
        CodeExecuteTool,
        FileReadTool,
        FileWriteTool,
        HTTPGetTool,
        DateTimeTool,
    ]:
        try:
            registry.register(tool_cls())
        except Exception as e:
            logger.warning(f"注册 {tool_cls.__name__} 失败: {e}")

    return registry
