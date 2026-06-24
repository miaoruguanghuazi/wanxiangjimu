"""
审计日志 — 结构化安全审计

记录:
- 用户请求（脱敏后）
- 安全事件（注入检测、速率限制、内容过滤等）
- 工具调用
- 系统事件

存储: JSON Lines 格式，按日期轮转
"""

from __future__ import annotations

import json
import time
import logging
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


class AuditLogger:
    """
    结构化审计日志

    用法:
        audit = AuditLogger(log_dir="./data/audit")
        audit.log_event("user_message", session_id="s1", detail={"msg": "你好"})
        audit.log_security("prompt_injection", "blocked", session_id="s1", detail={...})
    """

    def __init__(self, log_dir: str = "./data/audit", max_file_size: int = 10 * 1024 * 1024):
        self.log_dir = Path(log_dir)
        self.log_dir.mkdir(parents=True, exist_ok=True)
        self.max_file_size = max_file_size
        self._stats = {"total": 0, "security": 0, "tool_calls": 0, "errors": 0}

    def _write(self, entry: dict):
        """写入一条审计日志"""
        self._stats["total"] += 1
        entry["timestamp"] = datetime.now().isoformat()
        entry["epoch"] = time.time()

        log_file = self.log_dir / f"audit_{datetime.now().strftime('%Y%m%d')}.jsonl"

        # 文件大小检查 + 轮转
        if log_file.exists() and log_file.stat().st_size > self.max_file_size:
            rotated = self.log_dir / f"audit_{datetime.now().strftime('%Y%m%d')}_{int(time.time())}.jsonl"
            log_file.rename(rotated)

        with open(log_file, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")

    def log_event(
        self,
        event_type: str,
        session_id: str = "",
        user_id: str = "",
        detail: dict | None = None,
    ):
        """记录普通事件"""
        self._write({
            "type": "event",
            "event": event_type,
            "session_id": session_id,
            "user_id": user_id,
            "detail": detail or {},
        })

    def log_security(
        self,
        event: str,
        result: str,
        session_id: str = "",
        level: str = "warning",
        detail: dict | None = None,
    ):
        """
        记录安全事件

        Args:
            event: 事件类型 (prompt_injection, rate_limited, content_filtered, ...)
            result: 结果 (blocked, suspicious, allowed, ...)
            session_id: 会话 ID
            level: 级别 (info, warning, critical)
            detail: 详细信息
        """
        self._stats["security"] += 1
        self._write({
            "type": "security",
            "event": event,
            "result": result,
            "session_id": session_id,
            "level": level,
            "detail": detail or {},
        })
        if level == "critical":
            logger.warning(f"🚨 安全事件: {event} | result={result} | session={session_id}")

    def log_tool_call(
        self,
        tool_name: str,
        session_id: str = "",
        params: dict | None = None,
        result: str = "",
        duration: float = 0.0,
    ):
        """记录工具调用"""
        self._stats["tool_calls"] += 1
        self._write({
            "type": "tool_call",
            "tool": tool_name,
            "session_id": session_id,
            "params": params or {},
            "result": result,
            "duration": duration,
        })

    def log_error(
        self,
        error: str,
        session_id: str = "",
        context: dict | None = None,
    ):
        """记录错误"""
        self._stats["errors"] += 1
        self._write({
            "type": "error",
            "error": error,
            "session_id": session_id,
            "context": context or {},
        })

    def get_stats(self) -> dict:
        return self._stats.copy()

    def cleanup(self, days: int = 30) -> int:
        """
        清理超过指定天数的审计日志文件

        Args:
            days: 保留最近多少天的日志

        Returns:
            删除的文件数量
        """
        cutoff = datetime.now() - timedelta(days=days)
        cutoff_date = cutoff.strftime('%Y%m%d')
        deleted_count = 0

        for log_file in self.log_dir.glob("audit_*.jsonl"):
            # 从文件名提取日期 (audit_YYYYMMDD.jsonl 或 audit_YYYYMMDD_timestamp.jsonl)
            name = log_file.name
            # 尝试匹配 audit_YYYYMMDD.jsonl 或 audit_YYYYMMDD_xxx.jsonl
            parts = name.replace("audit_", "").replace(".jsonl", "").split("_")
            if parts and parts[0].isdigit() and len(parts[0]) == 8:
                file_date = parts[0]
                if file_date < cutoff_date:
                    try:
                        log_file.unlink()
                        deleted_count += 1
                        logger.info(f"已删除过期审计日志: {name}")
                    except Exception as e:
                        logger.warning(f"删除审计日志失败 {name}: {e}")

        if deleted_count:
            logger.info(f"审计日志清理完成: 删除 {deleted_count} 个过期文件 (>{days}天)")
        return deleted_count

    def query(
        self,
        event_type: str | None = None,
        session_id: str | None = None,
        since: float | None = None,
        limit: int = 100,
    ) -> list[dict]:
        """查询审计日志"""
        results = []
        for log_file in sorted(self.log_dir.glob("audit_*.jsonl"), reverse=True):
            with open(log_file, "r", encoding="utf-8") as f:
                for line in f:
                    try:
                        entry = json.loads(line.strip())
                        if event_type and entry.get("event") != event_type:
                            continue
                        if session_id and entry.get("session_id") != session_id:
                            continue
                        if since and entry.get("epoch", 0) < since:
                            continue
                        results.append(entry)
                        if len(results) >= limit:
                            return results
                    except json.JSONDecodeError:
                        continue
        return results
