"""
builtins.py — 内置工具实现

6个核心工具：
  1. WebSearchTool    — 网页搜索（DuckDuckGo，免费无需API Key）
  2. CodeExecuteTool  — Python 代码执行（subprocess沙箱）
  3. FileReadTool     — 读文件
  4. FileWriteTool    — 写文件
  5. HTTPGetTool      — HTTP GET 请求
  6. DateTimeTool     — 日期时间查询
"""

from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys
import time
import logging
from datetime import datetime
from typing import Any

from .base import BaseTool, ToolResult, ToolMetadata, Parameter, ParamType

logger = logging.getLogger(__name__)

# ============================================================
# 安全组件惰性加载
# ============================================================

_sandbox = None
_path_guard = None
_http_guard = None


def _get_sandbox():
    """惰性加载代码沙箱（fail-closed: 加载失败返回 None，调用方必须拒绝）"""
    global _sandbox
    if _sandbox is None:
        try:
            from security.sandbox import CodeSandbox
            _sandbox = CodeSandbox()
        except Exception as e:
            logger.error(f"CodeSandbox 加载失败，代码执行将被拒绝: {e}")
            _sandbox = False  # 标记加载失败
    return _sandbox if _sandbox is not False else None


def _get_path_guard():
    """惰性加载路径守卫（fail-closed）"""
    global _path_guard
    if _path_guard is None:
        try:
            from security.path_guard import PathGuard
            _path_guard = PathGuard()
        except Exception as e:
            logger.error(f"PathGuard 加载失败，文件操作将被拒绝: {e}")
            _path_guard = False
    return _path_guard if _path_guard is not False else None


def _get_http_guard():
    """惰性加载 HTTP 守卫（fail-closed）"""
    global _http_guard
    if _http_guard is None:
        try:
            from security.http_guard import HTTPGuard
            _http_guard = HTTPGuard()
        except Exception as e:
            logger.error(f"HTTPGuard 加载失败，HTTP 请求将被拒绝: {e}")
            _http_guard = False
    return _http_guard if _http_guard is not False else None


# ============================================================
# 1. WebSearchTool — 网页搜索
# ============================================================

class WebSearchTool(BaseTool):
    """网页搜索工具（使用 DuckDuckGo，免费无需 API Key）"""

    metadata = ToolMetadata(
        name="web_search",
        description="搜索互联网获取实时信息。支持搜索新闻、天气、价格、技术文档等。使用 DuckDuckGo 搜索引擎。",
        category="web",
        tags=["search", "web", "internet"],
        timeout=15.0,
        parameters=[
            Parameter(name="query", type=ParamType.STRING,
                      description="搜索关键词", required=True, max_length=200),
            Parameter(name="num_results", type=ParamType.INTEGER,
                      description="返回结果数量", default=5, min_value=1, max_value=10),
        ],
        examples=[
            'web_search(query="Python 3.12 新特性")',
            'web_search(query="今天北京天气", num_results=3)',
        ],
    )

    async def execute(self, query: str, num_results: int = 5) -> ToolResult:
        try:
            # 使用 DuckDuckGo HTML 搜索（无需 API Key）
            from urllib.request import urlopen, Request
            from urllib.parse import quote_plus
            import re

            url = f"https://html.duckduckgo.com/html/?q={quote_plus(query)}"
            req = Request(url, headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
            })

            def _fetch():
                with urlopen(req, timeout=10) as resp:
                    return resp.read().decode("utf-8", errors="ignore")

            html = await asyncio.to_thread(_fetch)

            # 解析结果
            results = []
            # DuckDuckGo HTML 结果格式
            pattern = r'<a[^>]+class="result__a"[^>]*href="([^"]+)"[^>]*>(.*?)</a>.*?<a[^>]+class="result__snippet"[^>]*>(.*?)</a>'
            matches = re.findall(pattern, html, re.DOTALL)

            for url_match, title_match, snippet_match in matches[:num_results]:
                # 清理 HTML 标签
                title = re.sub(r'<[^>]+>', '', title_match).strip()
                snippet = re.sub(r'<[^>]+>', '', snippet_match).strip()
                # DuckDuckGo 的 URL 跳转
                if url_match.startswith("//duckduckgo.com/l/?uddg="):
                    from urllib.parse import unquote, parse_qs, urlparse
                    parsed = urlparse(url_match)
                    params = parse_qs(parsed.query)
                    url_match = unquote(params.get("uddg", [url_match])[0])
                results.append({
                    "title": title,
                    "url": url_match,
                    "snippet": snippet[:200],
                })

            if not results:
                return ToolResult(
                    success=True,
                    output=f"搜索 \"{query}\" 未找到结果，或 DuckDuckGo 暂时不可用。",
                    data=[],
                )

            # 格式化输出
            lines = [f"搜索 \"{query}\" 的结果：\n"]
            for i, r in enumerate(results, 1):
                lines.append(f"{i}. {r['title']}")
                lines.append(f"   URL: {r['url']}")
                lines.append(f"   摘要: {r['snippet']}\n")

            return ToolResult(
                success=True,
                output="\n".join(lines),
                data=results,
            )

        except Exception as e:
            return ToolResult(
                success=False,
                output="",
                error=f"搜索失败: {str(e)}",
            )


# ============================================================
# 2. CodeExecuteTool — Python 代码执行
# ============================================================

class CodeExecuteTool(BaseTool):
    """Python 代码执行工具（subprocess 沙箱）"""

    metadata = ToolMetadata(
        name="code_execute",
        description="执行 Python 代码并返回输出。支持 print、计算、数据处理等。代码在受限沙箱中运行，禁止网络和文件系统访问（除临时目录）。",
        category="code",
        tags=["python", "execute", "sandbox"],
        timeout=30.0,
        parameters=[
            Parameter(name="code", type=ParamType.STRING,
                      description="要执行的 Python 代码", required=True),
            Parameter(name="timeout", type=ParamType.INTEGER,
                      description="执行超时（秒）", default=10, min_value=1, max_value=30),
        ],
        examples=[
            'code_execute(code="print(2+2)")',
            'code_execute(code="for i in range(5): print(i)")',
        ],
    )

    async def execute(self, code: str, timeout: int = 10) -> ToolResult:
        try:
            # 🔒 安全沙箱预检（fail-closed: 无沙箱则拒绝执行）
            sandbox = _get_sandbox()
            if not sandbox:
                return ToolResult(
                    success=False, output="",
                    error="🛡️ 安全拦截: 沙箱未加载，代码执行被禁止",
                )
            check = sandbox.check(code)
            if not check.ok:
                return ToolResult(
                    success=False, output="",
                    error=f"🛡️ 安全拦截: {check.violations[0] if check.violations else check.message}",
                )

            # 在 subprocess 中执行，带超时
            def _run():
                result = subprocess.run(
                    [sys.executable, "-c", code],
                    capture_output=True,
                    text=True,
                    timeout=timeout,
                    env={
                        "PATH": os.environ.get("PATH", ""),
                        "PYTHONPATH": "",
                        "TEMP": os.environ.get("TEMP", "/tmp"),
                    },
                )
                return result

            result = await asyncio.to_thread(_run)

            output = result.stdout.strip()
            if result.returncode != 0:
                output += f"\n[STDERR]\n{result.stderr.strip()}" if result.stderr else ""
                return ToolResult(
                    success=False,
                    output=output,
                    error=f"退出码 {result.returncode}",
                )

            return ToolResult(
                success=True,
                output=output or "(无输出)",
                data={"returncode": result.returncode},
            )

        except subprocess.TimeoutExpired:
            return ToolResult(
                success=False,
                output="",
                error=f"代码执行超时（{timeout}s）",
            )
        except Exception as e:
            return ToolResult(
                success=False,
                output="",
                error=f"执行异常: {str(e)}",
            )


# ============================================================
# 3. FileReadTool — 读文件
# ============================================================

class FileReadTool(BaseTool):
    """文件读取工具"""

    metadata = ToolMetadata(
        name="file_read",
        description="读取本地文件内容。支持文本文件。",
        category="file",
        tags=["file", "read"],
        timeout=5.0,
        parameters=[
            Parameter(name="path", type=ParamType.STRING,
                      description="文件路径", required=True),
            Parameter(name="encoding", type=ParamType.STRING,
                      description="文件编码", default="utf-8"),
        ],
        examples=[
            'file_read(path="/tmp/data.txt")',
        ],
    )

    async def execute(self, path: str, encoding: str = "utf-8") -> ToolResult:
        try:
            # 🔒 路径安全预检（fail-closed）
            guard = _get_path_guard()
            if not guard:
                return ToolResult(
                    success=False, output="",
                    error="🛡️ 安全拦截: 路径守卫未加载，文件读取被禁止",
                )
            check = guard.check_read(path)
            if not check.ok:
                return ToolResult(
                    success=False, output="", error=f"🛡️ 安全拦截: {check.message}"
                )
            safe_path = check.resolved

            if not os.path.exists(safe_path):
                return ToolResult(
                    success=False, output="", error=f"文件不存在: {path}"
                )
            if os.path.getsize(safe_path) > 1024 * 1024:  # 1MB 限制
                return ToolResult(
                    success=False, output="", error="文件过大（>1MB）"
                )

            def _read():
                with open(safe_path, "r", encoding=encoding) as f:
                    return f.read()

            content = await asyncio.to_thread(_read)
            return ToolResult(
                success=True,
                output=content[:5000],  # 限制输出长度
                data={"path": path, "size": len(content)},
            )
        except Exception as e:
            return ToolResult(success=False, output="", error=str(e))


# ============================================================
# 4. FileWriteTool — 写文件
# ============================================================

class FileWriteTool(BaseTool):
    """文件写入工具"""

    metadata = ToolMetadata(
        name="file_write",
        description="写入内容到本地文件。如果文件已存在则覆盖。",
        category="file",
        tags=["file", "write"],
        timeout=5.0,
        parameters=[
            Parameter(name="path", type=ParamType.STRING,
                      description="文件路径", required=True),
            Parameter(name="content", type=ParamType.STRING,
                      description="文件内容", required=True),
        ],
        examples=[
            'file_write(path="/tmp/output.txt", content="Hello World")',
        ],
    )

    async def execute(self, path: str, content: str) -> ToolResult:
        try:
            # 🔒 路径安全预检（fail-closed）
            guard = _get_path_guard()
            if not guard:
                return ToolResult(
                    success=False, output="",
                    error="🛡️ 安全拦截: 路径守卫未加载，文件写入被禁止",
                )
            check = guard.check_write(path)
            if not check.ok:
                return ToolResult(
                    success=False, output="", error=f"🛡️ 安全拦截: {check.message}"
                )
            safe_path = check.resolved

            def _write():
                os.makedirs(os.path.dirname(safe_path) if os.path.dirname(safe_path) else ".", exist_ok=True)
                with open(safe_path, "w", encoding="utf-8") as f:
                    f.write(content)

            await asyncio.to_thread(_write)
            return ToolResult(
                success=True,
                output=f"已写入 {len(content)} 字节到 {path}",
                data={"path": path, "size": len(content)},
            )
        except Exception as e:
            return ToolResult(success=False, output="", error=str(e))


# ============================================================
# 5. HTTPGetTool — HTTP GET 请求
# ============================================================

class HTTPGetTool(BaseTool):
    """HTTP GET 请求工具"""

    metadata = ToolMetadata(
        name="http_get",
        description="发送 HTTP GET 请求获取网页内容或 API 数据。支持 JSON 和文本响应。",
        category="web",
        tags=["http", "request", "api"],
        timeout=15.0,
        parameters=[
            Parameter(name="url", type=ParamType.STRING,
                      description="请求 URL", required=True),
            Parameter(name="max_chars", type=ParamType.INTEGER,
                      description="最大返回字符数", default=3000, min_value=100, max_value=10000),
        ],
        examples=[
            'http_get(url="https://api.github.com/repos/python/cpython")',
        ],
    )

    async def execute(self, url: str, max_chars: int = 3000) -> ToolResult:
        try:
            # 🔒 HTTP SSRF 防护（fail-closed）
            guard = _get_http_guard()
            if not guard:
                return ToolResult(
                    success=False, output="",
                    error="🛡️ 安全拦截: HTTP 守卫未加载，请求被禁止",
                )
            check = guard.check(url)
            if not check.ok:
                return ToolResult(
                    success=False, output="", error=f"🛡️ 安全拦截: {check.message}"
                )

            from urllib.request import urlopen, Request

            def _fetch():
                req = Request(url, headers={
                    "User-Agent": "Mozilla/5.0 (compatible; JinliAI/1.0)"
                })
                with urlopen(req, timeout=10) as resp:
                    content_type = resp.headers.get("Content-Type", "")
                    data = resp.read()
                    if "json" in content_type:
                        return data.decode("utf-8"), content_type
                    return data.decode("utf-8", errors="ignore"), content_type

            text, content_type = await asyncio.to_thread(_fetch)

            # 尝试格式化 JSON
            if "json" in content_type:
                try:
                    parsed = json.loads(text)
                    text = json.dumps(parsed, ensure_ascii=False, indent=2)
                except json.JSONDecodeError:
                    pass

            return ToolResult(
                success=True,
                output=text[:max_chars],
                data={"url": url, "content_type": content_type, "size": len(text)},
            )
        except Exception as e:
            return ToolResult(success=False, output="", error=str(e))


# ============================================================
# 6. DateTimeTool — 日期时间查询
# ============================================================

class DateTimeTool(BaseTool):
    """日期时间查询工具"""

    metadata = ToolMetadata(
        name="datetime",
        description="获取当前日期和时间。支持查询特定时区。",
        category="utility",
        tags=["date", "time", "datetime"],
        timeout=2.0,
        parameters=[
            Parameter(name="timezone", type=ParamType.STRING,
                      description="时区名称（如 Asia/Shanghai, UTC, US/Eastern）",
                      default="local"),
        ],
        examples=[
            'datetime()',
            'datetime(timezone="UTC")',
        ],
    )

    async def execute(self, timezone: str = "local") -> ToolResult:
        try:
            from datetime import timezone as tz_module
            from zoneinfo import ZoneInfo

            if timezone == "local":
                now = datetime.now()
                tz_name = "本地时间"
            elif timezone.upper() == "UTC":
                now = datetime.now(tz_module.utc)
                tz_name = "UTC"
            else:
                try:
                    tz = ZoneInfo(timezone)
                    now = datetime.now(tz)
                    tz_name = timezone
                except Exception:
                    return ToolResult(
                        success=False,
                        output="",
                        error=f"未知时区: {timezone}",
                    )

            formatted = now.strftime("%Y年%m月%d日 %H:%M:%S %A")
            return ToolResult(
                success=True,
                output=f"{tz_name}: {formatted}",
                data={"iso": now.isoformat(), "timezone": tz_name},
            )
        except Exception as e:
            return ToolResult(success=False, output="", error=str(e))
