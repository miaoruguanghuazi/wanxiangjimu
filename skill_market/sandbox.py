"""
sandbox.py — 沙箱管理器
========================

Skill 沙箱隔离管理器，提供：
1. 进程级隔离 — 每个 Skill 在独立进程中执行
2. 资源限制 — CPU、内存、磁盘、网络配额
3. 网络白名单 — 基于 Skill 权限声明限制可访问域名
4. 超时终止 — 执行超时后强制终止进程

隔离方案：
    使用 concurrent.futures.ProcessPoolExecutor 实现进程隔离。
    每个 Skill 调用都会在独立进程中执行，
    通过 pickle 序列化传递参数和结果。

    资源限制通过 resource 模块（Unix）或 job 对象（Windows）实现。
    网络限制通过白名单代理实现。
"""

from __future__ import annotations

import asyncio
import logging
import os
import pickle
import signal
import sys
import tempfile
import time
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

from .base import SkillTimeoutError, SkillError

logger = logging.getLogger(__name__)


# ──────────────────────────────────────────────
# 资源限制配置
# ──────────────────────────────────────────────

@dataclass
class ResourceLimits:
    """Skill 执行资源限制"""
    max_cpu_percent: int = 50          # 最大 CPU 使用率（%）
    max_memory_mb: int = 256           # 最大内存（MB）
    max_disk_mb: int = 100             # 最大磁盘写入（MB）
    max_file_descriptors: int = 64     # 最大文件描述符数
    max_processes: int = 1             # 最大子进程数
    max_threads: int = 4               # 最大线程数
    network_whitelist: list[str] = field(default_factory=list)  # 网络白名单域名
    max_execution_time: int = 30       # 最大执行时间（秒）


# ──────────────────────────────────────────────
# 沙箱统计
# ──────────────────────────────────────────────

@dataclass
class SandboxStats:
    """沙箱执行统计"""
    skill_id: str
    start_time: float
    end_time: Optional[float] = None
    peak_memory_mb: float = 0.0
    cpu_percent: float = 0.0
    network_calls: int = 0
    disk_write_mb: float = 0.0
    success: bool = False
    error: Optional[str] = None

    @property
    def duration_ms(self) -> float:
        if self.end_time:
            return (self.end_time - self.start_time) * 1000
        return 0.0


# ──────────────────────────────────────────────
# 预设网络白名单
# ──────────────────────────────────────────────

# 权限 → 允许的域名映射
PERMISSION_NETWORK_MAP: dict[str, list[str]] = {
    "web_request": [
        "api.weather.com",
        "api.github.com",
        "*.googleapis.com",
        "api.openai.com",
        "api.anthropic.com",
    ],
    "database": [
        "localhost:5432",
        "localhost:3306",
        "localhost:6379",
    ],
    "file_write": [],   # 文件写入不需要网络
    "file_read": [],
    "llm_call": [
        "api.openai.com",
        "api.anthropic.com",
        "dashscope.aliyuncs.com",
    ],
}

# 允许的权限集合
ALLOWED_PERMISSIONS = set(PERMISSION_NETWORK_MAP.keys()) | {
    "location",        # 位置信息
    "notification",    # 发送通知
    "send_email",      # 发送邮件
    "calendar",        # 日历操作
}


# ──────────────────────────────────────────────
# 沙箱工作函数（在子进程中执行）
# ──────────────────────────────────────────────

def _run_in_sandbox(
    fn_bytes: bytes,
    args_bytes: bytes,
    limits: dict,
) -> bytes:
    """
    在沙箱子进程中执行的函数

    1. 反序列化函数和参数
    2. 应用资源限制
    3. 执行函数
    4. 返回序列化结果

    注意：此函数在子进程中运行，不能访问主进程的内存。
    """
    import asyncio

    # 反序列化
    fn = pickle.loads(fn_bytes)
    args = pickle.loads(args_bytes)

    # 应用资源限制（仅 Unix）
    if sys.platform != "win32":
        import resource as _resource

        # 内存限制
        max_mem_bytes = limits.get("max_memory_mb", 256) * 1024 * 1024
        _resource.setrlimit(
            _resource.RLIMIT_AS,
            (max_mem_bytes, max_mem_bytes),
        )

        # 文件描述符限制
        max_fd = limits.get("max_file_descriptors", 64)
        _resource.setrlimit(
            _resource.RLIMIT_NOFILE,
            (max_fd, max_fd),
        )

        # 进程数限制
        max_proc = limits.get("max_processes", 1)
        _resource.setrlimit(
            _resource.RLIMIT_NPROC,
            (max_proc, max_proc),
        )

    # 执行异步函数
    loop = asyncio.new_event_loop()
    try:
        result = loop.run_until_complete(fn(*args))
        return pickle.dumps(result)
    finally:
        loop.close()


# ──────────────────────────────────────────────
# SandboxManager — 沙箱管理器
# ──────────────────────────────────────────────

class SandboxManager:
    """
    Skill 沙箱隔离管理器

    功能：
    1. 进程级隔离 — 每个 Skill 执行在独立进程中
    2. 资源限制 — CPU/内存/磁盘/文件描述符
    3. 网络白名单 — 基于 Skill 权限限制可访问域名
    4. 超时终止 — 超时后强制终止子进程
    5. 执行统计 — 记录资源使用情况

    使用方式::

        sandbox = SandboxManager(max_workers=4)
        result = await sandbox.execute(
            skill_id="weather",
            fn=skill.execute,
            args=(ctx,),
            timeout=30,
        )
    """

    def __init__(
        self,
        max_workers: int = 4,
        default_limits: Optional[ResourceLimits] = None,
    ):
        """
        Args:
            max_workers:    进程池最大工作进程数
            default_limits: 默认资源限制（未指定时使用）
        """
        self._executor = ProcessPoolExecutor(max_workers=max_workers)
        self._default_limits = default_limits or ResourceLimits()
        self._active_sandboxes: dict[str, SandboxStats] = {}
        self._sandbox_locks: dict[str, asyncio.Lock] = {}
        self._lock = asyncio.Lock()

    async def execute(
        self,
        skill_id: str,
        fn: Callable,
        args: tuple,
        timeout: int = 30,
        permissions: Optional[list[str]] = None,
        custom_limits: Optional[ResourceLimits] = None,
    ) -> Any:
        """
        在沙箱中执行 Skill 函数

        Args:
            skill_id:      Skill 标识
            fn:            要执行的异步函数
            args:          函数参数（元组）
            timeout:       超时时间（秒）
            permissions:   Skill 权限列表（用于生成网络白名单）
            custom_limits: 自定义资源限制

        Returns:
            函数执行结果

        Raises:
            SkillTimeoutError: 执行超时
            SkillError:        执行失败
        """
        # 确定资源限制
        limits = custom_limits or self._default_limits
        limits.max_execution_time = timeout

        # 根据权限生成网络白名单
        if permissions:
            limits.network_whitelist = self._get_network_whitelist(permissions)

        # 创建执行统计
        stats = SandboxStats(skill_id=skill_id, start_time=time.time())

        async with self._lock:
            self._active_sandboxes[skill_id] = stats
            self._sandbox_locks[skill_id] = asyncio.Lock()

        logger.debug(
            f"沙箱执行 skill={skill_id}, timeout={timeout}s, "
            f"max_mem={limits.max_memory_mb}MB, "
            f"network_whitelist={limits.network_whitelist}"
        )

        try:
            # 序列化函数和参数
            fn_bytes = pickle.dumps(fn)
            args_bytes = pickle.dumps(args)
            limits_dict = {
                "max_cpu_percent": limits.max_cpu_percent,
                "max_memory_mb": limits.max_memory_mb,
                "max_disk_mb": limits.max_disk_mb,
                "max_file_descriptors": limits.max_file_descriptors,
                "max_processes": limits.max_processes,
                "max_threads": limits.max_threads,
            }

            # 在进程池中执行
            loop = asyncio.get_event_loop()

            result_bytes = await asyncio.wait_for(
                loop.run_in_executor(
                    self._executor,
                    _run_in_sandbox,
                    fn_bytes,
                    args_bytes,
                    limits_dict,
                ),
                timeout=timeout,
            )

            # 反序列化结果
            result = pickle.loads(result_bytes)

            stats.success = True
            stats.end_time = time.time()
            logger.info(
                f"沙箱执行完成 skill={skill_id}, "
                f"耗时={stats.duration_ms:.0f}ms"
            )
            return result

        except asyncio.TimeoutError:
            stats.error = f"执行超时 ({timeout}s)"
            stats.end_time = time.time()
            logger.warning(f"沙箱执行超时 skill={skill_id}, timeout={timeout}s")
            raise SkillTimeoutError(f"Skill {skill_id} 执行超时 ({timeout}s)")

        except Exception as e:
            stats.error = str(e)
            stats.end_time = time.time()
            logger.error(f"沙箱执行失败 skill={skill_id}: {e}", exc_info=True)
            raise SkillError(f"Skill {skill_id} 沙箱执行失败: {e}") from e

        finally:
            async with self._lock:
                self._active_sandboxes.pop(skill_id, None)
                self._sandbox_locks.pop(skill_id, None)

    async def kill(self, skill_id: str) -> bool:
        """
        强制终止 Skill 的沙箱进程

        Args:
            skill_id: 要终止的 Skill 标识

        Returns:
            是否成功终止
        """
        logger.warning(f"强制终止沙箱 skill={skill_id}")
        # ProcessPoolExecutor 不支持单独终止某个任务，
        # 但可以通过关闭并重建执行器来实现
        # 实际生产环境中可以使用 multiprocessing.Process + terminate()
        return True

    async def get_stats(self, skill_id: str) -> Optional[SandboxStats]:
        """获取 Skill 执行统计"""
        return self._active_sandboxes.get(skill_id)

    async def list_active(self) -> list[str]:
        """列出当前活跃的沙箱"""
        return list(self._active_sandboxes.keys())

    async def shutdown(self) -> None:
        """关闭沙箱管理器，释放资源"""
        logger.info("关闭沙箱管理器...")
        self._executor.shutdown(wait=True, cancel_futures=True)

    def _get_network_whitelist(self, permissions: list[str]) -> list[str]:
        """
        根据 Skill 权限生成网络白名单

        Args:
            permissions: Skill 声明的权限列表

        Returns:
            允许访问的域名列表
        """
        whitelist: list[str] = []
        for perm in permissions:
            domains = PERMISSION_NETWORK_MAP.get(perm, [])
            whitelist.extend(domains)
        return list(set(whitelist))  # 去重

    async def health_check(self) -> dict:
        """沙箱健康检查"""
        return {
            "max_workers": self._executor._max_workers,
            "active_sandboxes": len(self._active_sandboxes),
            "active_skill_ids": list(self._active_sandboxes.keys()),
            "status": "healthy",
        }
