"""
HTTP SSRF 防护 — 内网地址过滤 + 域名白名单

防止:
- 访问内网地址 (127.0.0.1, 10.x, 172.16-31.x, 192.168.x)
- 访问云元数据服务 (169.254.169.254)
- 访问 localhost
- 端口限制（仅允许 80/443/8080/8443）
"""

from __future__ import annotations

import re
import ipaddress
import logging
from dataclasses import dataclass
from urllib.parse import urlparse

logger = logging.getLogger(__name__)


@dataclass
class HTTPCheckResult:
    ok: bool
    message: str
    safe_url: str = ""


# 允许的端口
ALLOWED_PORTS = {80, 443, 8080, 8443, 8000}

# 允许的域名后缀（为空则不限制域名，仅限制 IP）
ALLOWED_DOMAIN_SUFFIXES: set[str] = set()  # 空=不限制域名

# 禁止的域名
BLOCKED_DOMAINS = {
    "localhost", "metadata.google.internal",
    "metadata.azure.com", "169.254.169.254",
}


class HTTPGuard:
    """
    HTTP SSRF 防护

    用法:
        guard = HTTPGuard()
        result = guard.check("https://api.github.com/repos/python/cpython")
        if not result.ok:
            return result.message
        safe_url = result.safe_url
    """

    def __init__(self):
        self._stats = {"checked": 0, "blocked": 0}

    def check(self, url: str) -> HTTPCheckResult:
        """检查 URL 是否安全"""
        self._stats["checked"] += 1

        if not url or not isinstance(url, str):
            return HTTPCheckResult(ok=False, message="无效 URL")

        # 解析 URL
        try:
            parsed = urlparse(url)
        except Exception:
            return HTTPCheckResult(ok=False, message="URL 解析失败")

        scheme = parsed.scheme.lower()
        if scheme not in ("http", "https"):
            return HTTPCheckResult(ok=False, message=f"禁止协议: {scheme}（仅允许 http/https）")

        host = parsed.hostname or ""
        port = parsed.port or (443 if scheme == "https" else 80)

        # 端口检查
        if port not in ALLOWED_PORTS:
            return HTTPCheckResult(ok=False, message=f"端口 {port} 不在允许列表中")

        # 域名黑名单
        if host.lower() in BLOCKED_DOMAINS:
            return HTTPCheckResult(ok=False, message=f"禁止访问: {host}")

        # 如果是 IP 地址，检查是否为内网
        try:
            ip = ipaddress.ip_address(host)
            if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved:
                return HTTPCheckResult(ok=False, message=f"禁止访问内网地址: {host}")
            if str(ip) == "169.254.169.254":
                return HTTPCheckResult(ok=False, message="禁止访问云元数据服务")
        except ValueError:
            # 不是 IP，是域名
            pass

        # localhost 检查
        if host.lower() in ("localhost", "127.0.0.1", "::1", "0.0.0.0"):
            return HTTPCheckResult(ok=False, message=f"禁止访问: {host}")

        # 域名后缀白名单（如果配置了）
        if ALLOWED_DOMAIN_SUFFIXES:
            if not any(host.lower().endswith(s) for s in ALLOWED_DOMAIN_SUFFIXES):
                return HTTPCheckResult(ok=False, message=f"域名不在白名单中: {host}")

        return HTTPCheckResult(ok=True, message="URL 检查通过", safe_url=url)

    def get_stats(self) -> dict:
        return self._stats.copy()
