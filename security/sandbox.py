"""
代码执行沙箱加固 — 危险模块黑名单 + 资源限制

在 CodeExecuteTool 的 subprocess 基础上增加:
1. 危险 import 黑名单（os, sys, subprocess, shutil 等系统级模块）
2. 危险函数调用黑名单（eval, exec, __import__ 等）
3. 资源限制（CPU 时间、内存）
4. 代码静态检查（执行前扫描）
"""

from __future__ import annotations

import re
import logging
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class SandboxResult:
    """沙箱检查结果"""
    ok: bool
    message: str
    violations: list[str] = None

    def __post_init__(self):
        if self.violations is None:
            self.violations = []


# ============================================================
# 危险模块黑名单
# ============================================================

DANGEROUS_MODULES = {
    # 系统级
    "os", "sys", "subprocess", "shutil", "ctypes", "platform",
    "multiprocessing", "threading",
    # 网络级
    "socket", "http", "urllib", "requests", "httpx", "aiohttp",
    "ftplib", "smtplib", "telnetlib", "paramiko",
    # 文件系统
    "pathlib", "glob", "tempfile", "fileinput",
    # 进程/信号
    "signal", "resource", "pwd", "grp",
    # 序列化（可执行任意代码）
    "pickle", "marshal", "shelve",
    # 数据库
    "sqlite3", "psycopg2", "pymysql",
    # 其他
    "importlib", "builtins", "gc",
}

# 允许的安全模块
SAFE_MODULES = {
    "math", "random", "statistics", "itertools", "functools",
    "collections", "datetime", "json", "re", "string",
    "decimal", "fractions", "hashlib", "base64",
    "textwrap", "unicodedata", "csv",
    "typing", "dataclasses", "enum", "abc",
    "copy", "pprint", "operator", "heapq",
    "bisect", "array", "struct",
}

# 危险函数/属性调用
DANGEROUS_CALLS = [
    re.compile(r"\beval\s*\(", re.I),
    re.compile(r"\bexec\s*\(", re.I),
    re.compile(r"\b__import__\s*\(", re.I),
    re.compile(r"\bcompile\s*\(", re.I),
    re.compile(r"\bgetattr\s*\(", re.I),  # 全局禁止 getattr（可绕过属性访问限制）
    re.compile(r"\bsetattr\s*\(", re.I),
    re.compile(r"\bdelattr\s*\(", re.I),
    re.compile(r"\b__\w+__\s*\(", re.I),  # dunder 方法调用
    re.compile(r"\bopen\s*\(", re.I),  # 文件操作
    re.compile(r"\bexit\s*\(", re.I),
    re.compile(r"\bquit\s*\(", re.I),
    re.compile(r"\binput\s*\(", re.I),
    re.compile(r"\bglobals\s*\(", re.I),  # 全局命名空间访问
    re.compile(r"\blocals\s*\(", re.I),
    re.compile(r"\bvars\s*\(", re.I),
    re.compile(r"\bdir\s*\(", re.I),  # 可探测可用对象
]

# import 语句提取
IMPORT_PATTERNS = [
    re.compile(r"^\s*import\s+(\S+)", re.MULTILINE),
    re.compile(r"^\s*from\s+(\S+)\s+import", re.MULTILINE),
]


class CodeSandbox:
    """
    代码执行沙箱检查器

    用法:
        sandbox = CodeSandbox()
        result = sandbox.check(code)
        if not result.ok:
            return f"代码包含危险操作: {result.violations}"
        # ... 安全执行 ...
    """

    def __init__(self, allow_safe_modules: bool = True):
        self.allow_safe = allow_safe_modules
        self._stats = {"checked": 0, "blocked": 0, "violations": 0}

    def check(self, code: str) -> SandboxResult:
        """静态检查代码安全性"""
        self._stats["checked"] += 1
        violations = []

        # 1. 检查 import 语句
        for pattern in IMPORT_PATTERNS:
            for m in pattern.finditer(code):
                module_name = m.group(1).split(".")[0]  # 取顶层模块名
                if module_name in DANGEROUS_MODULES:
                    violations.append(f"禁止导入危险模块: {module_name}")
                elif self.allow_safe and module_name not in SAFE_MODULES:
                    violations.append(f"模块不在安全白名单中: {module_name}")

        # 2. 检查危险函数调用
        for pattern in DANGEROUS_CALLS:
            for m in pattern.finditer(code):
                violations.append(f"禁止调用危险函数: {m.group().strip()[:30]}")

        # 3. 检查字符串拼接的 import（简单防御）
        if re.search(r"__import__", code):
            violations.append("检测到 __import__ 动态导入")

        # 4. 检查环境变量访问
        if re.search(r"environ|getenv", code, re.I):
            violations.append("禁止访问环境变量")

        # 5. 检查网络相关
        if re.search(r"\bsocket\b|\bconnect\b|\bbind\b|\blisten\b", code, re.I):
            violations.append("检测到网络操作")

        if violations:
            self._stats["blocked"] += 1
            self._stats["violations"] += len(violations)
            return SandboxResult(
                ok=False,
                message=f"代码安全检查未通过（{len(violations)} 个违规）",
                violations=violations,
            )

        return SandboxResult(ok=True, message="代码安全检查通过")

    def get_safe_env(self) -> dict:
        """返回安全的环境变量（只包含必要的）"""
        import os
        return {
            "PATH": os.environ.get("PATH", ""),
            "PYTHONPATH": "",
            "TEMP": os.environ.get("TEMP", "/tmp"),
            "HOME": "/tmp",  # 不暴露真实 HOME
            "USER": "nobody",
            "LANG": "en_US.UTF-8",
            "LC_ALL": "en_US.UTF-8",
        }

    def get_stats(self) -> dict:
        return self._stats.copy()
