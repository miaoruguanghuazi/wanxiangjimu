"""
安全体系 — 万象积木

16维安全防护，分3层实现:
  P0 核心: prompt_guard, sanitizer, sandbox, path_guard, http_guard
  P1 重要: rate_limiter, content_filter, audit, output_guard, session_guard
  P2 加固: config_validator

用法:
  from security import SecurityGate
  gate = SecurityGate()
  result = gate.check_input(user_message, session_id)
  if not result.ok:
      return result.message
  # ... 正常处理 ...
  gate.audit_log(session_id, "chat", "success", {"model": "deepseek-chat"})
"""

from .prompt_guard import PromptGuard, GuardResult
from .sanitizer import Sanitizer
from .sandbox import CodeSandbox
from .path_guard import PathGuard
from .http_guard import HTTPGuard
from .rate_limiter import RateLimiter
from .content_filter import ContentFilter
from .audit import AuditLogger
from .output_guard import OutputGuard
from .session_guard import SessionGuard
from .config_validator import ConfigValidator

__all__ = [
    "PromptGuard", "GuardResult",
    "Sanitizer",
    "CodeSandbox",
    "PathGuard",
    "HTTPGuard",
    "RateLimiter",
    "ContentFilter",
    "AuditLogger",
    "OutputGuard",
    "SessionGuard",
    "ConfigValidator",
]

__version__ = "1.0.0"
