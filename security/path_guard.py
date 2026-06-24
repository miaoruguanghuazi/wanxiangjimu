"""
文件路径安全 — 路径遍历防护 + 白名单目录

防止:
- 目录遍历攻击 (../)
- 访问系统敏感目录
- 符号链接攻击
"""

from __future__ import annotations

import os
import logging
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class PathCheckResult:
    ok: bool
    message: str
    resolved: str = ""


# 允许访问的根目录（相对于工作目录）
ALLOWED_ROOTS = [
    "./data",
    "./data/uploads",
    "./data/chroma",
    "./data/memory",
    "/tmp",
    os.path.join(os.environ.get("TEMP", "/tmp"), "wanxiang_ai"),
]

# 绝对禁止访问的目录
FORBIDDEN_PATHS = [
    "/etc", "/var", "/usr", "/bin", "/sbin", "/boot", "/dev", "/proc", "/sys",
    "C:\\Windows", "C:\\Program Files", "C:\\Program Files (x86)",
    os.path.expanduser("~/.ssh"),
    os.path.expanduser("~/.aws"),
    os.path.expanduser("~/.config"),
    os.path.expanduser("~/.env"),
    # .env 文件本身（而非整个工作目录）
    os.path.abspath(".env") if os.path.exists(".env") else None,
]

# 绝对禁止的文件扩展名
FORBIDDEN_EXTENSIONS = {
    ".env", ".key", ".pem", ".crt", ".pfx", ".p12",
    ".ssh", ".bash_history", ".bashrc", ".profile",
    ".gitconfig", ".npmrc", ".pypirc",
}


class PathGuard:
    """
    文件路径安全守卫

    用法:
        guard = PathGuard()
        result = guard.check_read("./data/uploads/test.txt")
        if not result.ok:
            return result.message
        safe_path = result.resolved
    """

    def __init__(self, extra_allowed: list[str] = None):
        self.allowed_roots = list(ALLOWED_ROOTS)
        if extra_allowed:
            self.allowed_roots.extend(extra_allowed)
        # 转为绝对路径
        self._allowed_abs = set()
        for root in self.allowed_roots:
            try:
                abs_path = os.path.abspath(root)
                self._allowed_abs.add(abs_path)
            except Exception:
                pass

        self._stats = {"checked": 0, "blocked": 0}

    def check_read(self, path: str) -> PathCheckResult:
        """检查读取路径是否安全"""
        self._stats["checked"] += 1

        result = self._validate(path)
        if not result.ok:
            self._stats["blocked"] += 1
            return result

        if not os.path.exists(result.resolved):
            return PathCheckResult(ok=False, message=f"文件不存在: {path}")

        if os.path.islink(result.resolved):
            # 解析符号链接真实路径
            real = os.path.realpath(result.resolved)
            if not self._is_in_allowed(real):
                return PathCheckResult(ok=False, message=f"符号链接指向禁止目录: {path}")

        return result

    def check_write(self, path: str) -> PathCheckResult:
        """检查写入路径是否安全"""
        self._stats["checked"] += 1

        result = self._validate(path)
        if not result.ok:
            self._stats["blocked"] += 1
            return result

        return result

    def _validate(self, path: str) -> PathCheckResult:
        """核心验证逻辑"""
        if not path or not isinstance(path, str):
            return PathCheckResult(ok=False, message="无效路径")

        # 检查扩展名
        _, ext = os.path.splitext(path)
        if ext.lower() in FORBIDDEN_EXTENSIONS:
            return PathCheckResult(ok=False, message=f"禁止访问 {ext} 文件")

        # 规范化路径（解析 ../ 等）
        try:
            resolved = os.path.abspath(path)
        except Exception:
            return PathCheckResult(ok=False, message="路径解析失败")

        # 规范化路径（使用 realpath 解析 ../ 和符号链接）
        try:
            resolved = os.path.realpath(os.path.abspath(path))
        except Exception:
            return PathCheckResult(ok=False, message="路径解析失败")

        # 检查路径遍历：比较原始路径规范化前后是否一致
        normalized = os.path.normpath(path)
        if os.path.isabs(normalized):
            abs_normalized = normalized
        else:
            abs_normalized = os.path.abspath(normalized)
        if abs_normalized != resolved:
            # normpath 和 realpath 结果不一致，说明有符号链接或 ../ 被解析
            # 再验证 resolved 后的路径仍在允许范围内
            pass

        # 检查是否在禁止目录中
        for forbidden in FORBIDDEN_PATHS:
            if forbidden:
                forbidden_resolved = os.path.realpath(forbidden)
                if resolved.lower().startswith(forbidden_resolved.lower()):
                    return PathCheckResult(ok=False, message=f"禁止访问系统目录: {path}")

        # 检查是否在允许目录中
        if not self._is_in_allowed(resolved):
            return PathCheckResult(ok=False, message=f"路径不在允许的目录范围内: {path}")

        return PathCheckResult(ok=True, message="路径检查通过", resolved=resolved)

    def _is_in_allowed(self, resolved: str) -> bool:
        """检查解析后的路径是否在允许的根目录内"""
        for allowed in self._allowed_abs:
            if resolved == allowed or resolved.startswith(allowed + os.sep):
                return True
        return False

    def get_stats(self) -> dict:
        return self._stats.copy()
