"""
runtime.py — 热插拔运行时
=========================

PluginRuntime 是插件市场的核心运行时引擎，负责：
1. Skill 安装/卸载 — 动态加载 Skill 代码到运行时
2. Skill 执行      — 带沙箱隔离、引用计数、超时管理
3. Skill 升级      — 灰度滚动 / 立即替换 / 蓝绿部署
4. 安全审计        — 权限检查、恶意代码扫描
5. 生命周期管理    — 安装/卸载/升级钩子

核心机制：
    - 引用计数：确保使用中的 Skill 不会被意外卸载
    - importlib 动态加载：运行时从文件加载 Skill 类
    - 沙箱隔离：通过 SandboxManager 在独立进程中执行 Skill
    - 灰度升级：支持 rolling / immediate / blue_green 三种策略
"""

from __future__ import annotations

import asyncio
import importlib.util
import logging
import os
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Optional, Protocol

from .base import (
    BaseSkill,
    SkillContext,
    SkillError,
    SkillLoadError,
    SkillNotFoundError,
    SkillResult,
    ResultStatus,
    SkillManifest,
)
from .sandbox import SandboxManager, ALLOWED_PERMISSIONS
from .store import SkillStore, SkillPackage

logger = logging.getLogger(__name__)


# ──────────────────────────────────────────────
# 配置存储协议
# ──────────────────────────────────────────────

class ConfigStore(Protocol):
    """配置存储协议"""

    async def get(self, skill_id: str) -> dict:
        """获取 Skill 配置"""
        ...

    async def set(self, skill_id: str, config: dict) -> None:
        """保存 Skill 配置"""
        ...

    async def delete(self, skill_id: str) -> None:
        """删除 Skill 配置"""
        ...


# ──────────────────────────────────────────────
# 内存配置存储（默认实现）
# ──────────────────────────────────────────────

class InMemoryConfigStore:
    """内存配置存储（开发/测试用）"""

    def __init__(self):
        self._configs: dict[str, dict] = {}

    async def get(self, skill_id: str) -> dict:
        return self._configs.get(skill_id, {})

    async def set(self, skill_id: str, config: dict) -> None:
        self._configs[skill_id] = config

    async def delete(self, skill_id: str) -> None:
        self._configs.pop(skill_id, None)


# ──────────────────────────────────────────────
# 执行记录
# ──────────────────────────────────────────────

@dataclass
class ExecutionRecord:
    """Skill 执行记录"""
    skill_id: str
    version: str
    user_id: str
    session_id: str
    start_time: datetime
    end_time: Optional[datetime] = None
    status: str = "running"          # running / success / failed / timeout
    result: Any = None
    error: Optional[str] = None
    latency_ms: float = 0.0
    sandboxed: bool = True
    tokens_used: int = 0

    def to_dict(self) -> dict:
        return {
            "skill_id": self.skill_id,
            "version": self.version,
            "user_id": self.user_id,
            "session_id": self.session_id,
            "start_time": self.start_time.isoformat(),
            "end_time": self.end_time.isoformat() if self.end_time else None,
            "status": self.status,
            "error": self.error,
            "latency_ms": self.latency_ms,
            "sandboxed": self.sandboxed,
            "tokens_used": self.tokens_used,
        }


# ──────────────────────────────────────────────
# 升级策略
# ──────────────────────────────────────────────

class UpgradeStrategy:
    """升级策略枚举"""
    ROLLING = "rolling"         # 灰度滚动：等待现有请求完成后替换
    IMMEDIATE = "immediate"     # 立即替换：可能中断进行中的任务
    BLUE_GREEN = "blue_green"   # 蓝绿部署：新旧并行，验证后切换


# ──────────────────────────────────────────────
# PluginRuntime — 热插拔运行时
# ──────────────────────────────────────────────

class PluginRuntime:
    """
    Skill 热插拔运行时

    核心职责：
        1. 运行时动态加载/卸载 Skill
        2. 沙箱隔离（独立进程 / 资源配额）
        3. 版本管理 + 灰度升级
        4. 引用计数（防止使用中的 Skill 被卸载）
        5. 安全审计（权限检查 + 恶意代码扫描）

    使用示例::

        store = SkillStore()
        sandbox = SandboxManager()
        config_store = InMemoryConfigStore()
        runtime = PluginRuntime(store, sandbox, config_store)

        # 安装
        await runtime.install("weather", config={"api_key": "xxx"})

        # 执行
        result = await runtime.execute_skill("weather", ctx)

        # 卸载
        await runtime.uninstall("weather")
    """

    def __init__(
        self,
        skill_store: SkillStore,
        sandbox_manager: SandboxManager,
        config_store: Optional[ConfigStore] = None,
    ):
        """
        Args:
            skill_store:     Skill 仓库管理器
            sandbox_manager: 沙箱管理器
            config_store:    配置存储（默认使用内存存储）
        """
        self.store = skill_store
        self.sandbox = sandbox_manager
        self.config_store: ConfigStore = config_store or InMemoryConfigStore()

        # 已加载的 Skill 实例 {skill_id: BaseSkill}
        self._loaded_skills: dict[str, BaseSkill] = {}

        # 引用计数 {skill_id: int}
        self._reference_count: dict[str, int] = {}

        # Skill 元数据缓存 {skill_id: SkillManifest}
        self._manifests: dict[str, SkillManifest] = {}

        # 执行历史记录
        self._execution_history: list[ExecutionRecord] = []
        self._max_history: int = 1000

        # 已加载的模块（防止重复加载）
        self._loaded_modules: dict[str, object] = {}

        # 并发锁
        self._lock = asyncio.Lock()

        logger.info("PluginRuntime 初始化完成")

    # ──────────────────────────────────────────
    # 安装 / 卸载
    # ──────────────────────────────────────────

    async def install(
        self,
        skill_id: str,
        version: str = "latest",
        config: Optional[dict] = None,
    ) -> dict:
        """
        安装 Skill

        流程：
        1. 从仓库下载 Skill 包
        2. 安全审计（权限检查 + 恶意代码扫描）
        3. 安装 Python 依赖
        4. 动态加载 Skill 类（importlib）
        5. 实例化并调用 on_install 钩子
        6. 注册到运行时

        Args:
            skill_id: Skill 标识
            version:  版本（"latest" 表示最新）
            config:   Skill 配置

        Returns:
            安装结果 {"status": "installed", "skill_id": ..., "version": ...}

        Raises:
            SkillError: 安装失败
        """
        async with self._lock:
            # 检查是否已安装
            if skill_id in self._loaded_skills:
                existing = self._loaded_skills[skill_id]
                if existing.manifest.version == version or version == "latest":
                    logger.info(f"Skill {skill_id} 已安装 (v{existing.manifest.version})")
                    return {
                        "status": "already_installed",
                        "skill_id": skill_id,
                        "version": existing.manifest.version,
                    }

            # 1. 下载 Skill 包
            logger.info(f"开始安装 Skill: {skill_id}@{version}")
            package = await self.store.download(skill_id, version)

            # 2. 安全审计
            audit = await self._security_audit(package)
            if not audit["safe"]:
                logger.warning(f"Skill {skill_id} 安全审计未通过: {audit['reason']}")
                return {
                    "status": "rejected",
                    "reason": audit["reason"],
                    "skill_id": skill_id,
                }

            # 3. 安装依赖
            if package.dependencies:
                await self._install_dependencies(package.dependencies)

            # 4. 动态加载 Skill 类
            skill_class = self._load_skill_class(package)
            instance = skill_class(config=config)

            # 5. 调用安装钩子
            install_result = await instance.on_install(config)

            # 6. 保存配置
            await self.config_store.set(skill_id, config or {})

            # 7. 注册到运行时
            self._loaded_skills[skill_id] = instance
            self._reference_count[skill_id] = 0
            self._manifests[skill_id] = instance.manifest

            logger.info(
                f"Skill 安装成功: {skill_id}@{instance.manifest.version}"
            )

            return {
                "status": "installed",
                "skill_id": skill_id,
                "version": instance.manifest.version,
                "manifest": instance.manifest.to_dict(),
                "install_result": install_result,
            }

    async def uninstall(self, skill_id: str, force: bool = False) -> dict:
        """
        卸载 Skill

        如果 Skill 正在被使用（引用计数 > 0）：
        - force=False: 拒绝卸载
        - force=True:  强制卸载（可能影响进行中的任务）

        Args:
            skill_id: Skill 标识
            force:    是否强制卸载

        Returns:
            卸载结果
        """
        async with self._lock:
            if skill_id not in self._loaded_skills:
                return {"status": "not_found", "skill_id": skill_id}

            ref_count = self._reference_count.get(skill_id, 0)
            if ref_count > 0 and not force:
                return {
                    "status": "in_use",
                    "message": f"有 {ref_count} 个任务正在使用此 Skill",
                    "skill_id": skill_id,
                }

            instance = self._loaded_skills.pop(skill_id, None)
            self._reference_count.pop(skill_id, None)
            self._manifests.pop(skill_id, None)
            self._loaded_modules.pop(skill_id, None)

            if instance:
                try:
                    await instance.on_uninstall()
                except Exception as e:
                    logger.error(f"Skill {skill_id} 卸载钩子执行失败: {e}")

            # 清理配置
            await self.config_store.delete(skill_id)

            logger.info(f"Skill 已卸载: {skill_id}")

            return {"status": "uninstalled", "skill_id": skill_id}

    # ──────────────────────────────────────────
    # 执行
    # ──────────────────────────────────────────

    async def execute_skill(
        self,
        skill_id: str,
        ctx: SkillContext,
    ) -> Any:
        """
        执行 Skill

        流程：
        1. 检查 Skill 是否已加载
        2. 引用计数 +1
        3. 参数校验
        4. 沙箱执行（如果 Skill 声明了 sandbox=True）
        5. 引用计数 -1
        6. 记录执行历史

        Args:
            skill_id: Skill 标识
            ctx:      执行上下文

        Returns:
            Skill 执行结果

        Raises:
            SkillNotFoundError: Skill 未安装
            SkillError:         执行失败
        """
        if skill_id not in self._loaded_skills:
            raise SkillNotFoundError(skill_id)

        skill = self._loaded_skills[skill_id]
        version = skill.manifest.version

        # 创建执行记录
        record = ExecutionRecord(
            skill_id=skill_id,
            version=version,
            user_id=ctx.user_id,
            session_id=ctx.session_id,
            start_time=datetime.now(),
            sandboxed=skill.manifest.sandbox,
        )

        # 参数校验
        is_valid, error_msg = await skill.validate_params(ctx.params)
        if not is_valid:
            record.status = "failed"
            record.error = f"参数校验失败: {error_msg}"
            record.end_time = datetime.now()
            record.latency_ms = (record.end_time - record.start_time).total_seconds() * 1000
            self._add_history(record)
            raise SkillError(f"参数校验失败: {error_msg}")

        # 引用计数 +1
        self._reference_count[skill_id] = self._reference_count.get(skill_id, 0) + 1

        # 注入上下文工具
        self._inject_context_tools(ctx, skill)

        try:
            start = time.time()

            # 沙箱执行 or 直接执行
            if skill.manifest.sandbox:
                result = await self.sandbox.execute(
                    skill_id=skill_id,
                    fn=skill.execute,
                    args=(ctx,),
                    timeout=skill.manifest.quota_limit,
                    permissions=skill.manifest.permissions,
                )
            else:
                result = await asyncio.wait_for(
                    skill.execute(ctx),
                    timeout=skill.manifest.quota_limit,
                )

            elapsed_ms = (time.time() - start) * 1000
            record.status = "success"
            record.result = result
            record.latency_ms = elapsed_ms
            record.end_time = datetime.now()

            logger.info(
                f"Skill 执行完成: {skill_id}@{version}, "
                f"耗时={elapsed_ms:.0f}ms"
            )

            return result

        except asyncio.TimeoutError:
            record.status = "timeout"
            record.error = f"执行超时 ({skill.manifest.quota_limit}s)"
            record.end_time = datetime.now()
            record.latency_ms = (record.end_time - record.start_time).total_seconds() * 1000
            logger.warning(f"Skill 执行超时: {skill_id}")
            raise SkillError(f"Skill {skill_id} 执行超时")

        except Exception as e:
            record.status = "failed"
            record.error = str(e)
            record.end_time = datetime.now()
            record.latency_ms = (record.end_time - record.start_time).total_seconds() * 1000
            logger.error(f"Skill 执行失败: {skill_id}: {e}", exc_info=True)
            raise SkillError(f"Skill {skill_id} 执行失败: {e}") from e

        finally:
            # 引用计数 -1
            self._reference_count[skill_id] = max(
                0, self._reference_count.get(skill_id, 0) - 1
            )
            self._add_history(record)

    # ──────────────────────────────────────────
    # 升级
    # ──────────────────────────────────────────

    async def upgrade(
        self,
        skill_id: str,
        target_version: str = "latest",
        strategy: str = UpgradeStrategy.ROLLING,
        config: Optional[dict] = None,
    ) -> dict:
        """
        Skill 升级

        支持三种策略：
        - rolling  : 灰度滚动（等待现有请求完成后替换）
        - immediate: 立即替换（可能中断进行中的任务）
        - blue_green: 蓝绿部署（新旧并行，验证后切换）

        Args:
            skill_id:       Skill 标识
            target_version: 目标版本
            strategy:       升级策略
            config:         新配置（可选，默认沿用旧配置）

        Returns:
            升级结果
        """
        async with self._lock:
            old_instance = self._loaded_skills.get(skill_id)
            old_version = old_instance.manifest.version if old_instance else None

            if old_version == target_version:
                return {
                    "status": "already_up_to_date",
                    "skill_id": skill_id,
                    "version": old_version,
                }

            logger.info(
                f"升级 Skill {skill_id}: {old_version} → {target_version} "
                f"(strategy={strategy})"
            )

            if strategy == UpgradeStrategy.BLUE_GREEN:
                return await self._upgrade_blue_green(
                    skill_id, target_version, old_instance, old_version, config
                )

            elif strategy == UpgradeStrategy.IMMEDIATE:
                return await self._upgrade_immediate(
                    skill_id, target_version, old_instance, old_version, config
                )

            elif strategy == UpgradeStrategy.ROLLING:
                return await self._upgrade_rolling(
                    skill_id, target_version, old_instance, old_version, config
                )

            else:
                raise ValueError(f"未知升级策略: {strategy}")

    async def _upgrade_blue_green(
        self,
        skill_id: str,
        target_version: str,
        old_instance: Optional[BaseSkill],
        old_version: Optional[str],
        config: Optional[dict],
    ) -> dict:
        """蓝绿升级：新版本以临时 ID 加载，验证后切换"""
        temp_id = f"{skill_id}__candidate"

        # 安装新版本到临时 ID
        install_result = await self.install(temp_id, target_version, config)

        if install_result["status"] not in ("installed", "already_installed"):
            return {
                "status": "upgrade_failed",
                "reason": "新版本安装失败",
                "detail": install_result,
            }

        # 验证新版本
        valid = await self._validate_upgrade(skill_id, temp_id)

        if not valid:
            await self.uninstall(temp_id, force=True)
            return {
                "status": "upgrade_failed",
                "reason": "新版本验证未通过",
                "skill_id": skill_id,
            }

        # 切换流量
        new_instance = self._loaded_skills.pop(temp_id)
        self._reference_count[skill_id] = self._reference_count.pop(temp_id, 0)
        self._loaded_skills[skill_id] = new_instance
        self._manifests[skill_id] = new_instance.manifest

        # 调用旧版本升级钩子
        if old_instance:
            try:
                await old_instance.on_upgrade(old_version, config)
            except Exception as e:
                logger.warning(f"旧版本升级钩子失败: {e}")

        logger.info(f"蓝绿升级完成: {skill_id} {old_version} → {target_version}")
        return {
            "status": "upgraded",
            "skill_id": skill_id,
            "from": old_version,
            "to": target_version,
            "strategy": "blue_green",
        }

    async def _upgrade_immediate(
        self,
        skill_id: str,
        target_version: str,
        old_instance: Optional[BaseSkill],
        old_version: Optional[str],
        config: Optional[dict],
    ) -> dict:
        """立即升级：直接卸载旧版本，安装新版本"""
        if old_instance:
            await self.uninstall(skill_id, force=True)

        result = await self.install(skill_id, target_version, config)
        result["strategy"] = "immediate"
        result["from"] = old_version
        return result

    async def _upgrade_rolling(
        self,
        skill_id: str,
        target_version: str,
        old_instance: Optional[BaseSkill],
        old_version: Optional[str],
        config: Optional[dict],
    ) -> dict:
        """
        灰度滚动升级：等待引用计数归零后替换

        最多等待 60 秒，超时后转为强制卸载 + 安装。
        """
        if not old_instance:
            return await self.install(skill_id, target_version, config)

        # 等待引用计数归零
        wait_seconds = 0
        max_wait = 60
        while self._reference_count.get(skill_id, 0) > 0 and wait_seconds < max_wait:
            await asyncio.sleep(1)
            wait_seconds += 1

        if self._reference_count.get(skill_id, 0) > 0:
            logger.warning(
                f"灰度升级等待超时 ({max_wait}s)，强制卸载 Skill {skill_id}"
            )
            await self.uninstall(skill_id, force=True)
        else:
            await self.uninstall(skill_id)

        result = await self.install(skill_id, target_version, config)
        result["strategy"] = "rolling"
        result["from"] = old_version
        return result

    async def _validate_upgrade(self, old_id: str, new_id: str) -> bool:
        """
        验证新版本 Skill 是否正常工作

        运行一个简单的冒烟测试，检查 Skill 能否正常 describe()。
        """
        new_skill = self._loaded_skills.get(new_id)
        if not new_skill:
            return False

        try:
            desc = await new_skill.describe()
            return bool(desc)
        except Exception as e:
            logger.error(f"新版本验证失败: {e}")
            return False

    # ──────────────────────────────────────────
    # 动态加载
    # ──────────────────────────────────────────

    def _load_skill_class(self, package: SkillPackage) -> type[BaseSkill]:
        """
        使用 importlib 动态加载 Skill 类

        1. 从文件路径创建模块 spec
        2. 执行模块代码
        3. 查找继承 BaseSkill 的类
        4. 返回 Skill 类（未实例化）

        Args:
            package: Skill 包信息

        Returns:
            BaseSkill 子类

        Raises:
            SkillLoadError: 加载失败
        """
        if not package.entry_point_path or not os.path.exists(package.entry_point_path):
            raise SkillLoadError(
                f"Skill 入口文件不存在: {package.entry_point_path}"
            )

        try:
            # 生成唯一模块名
            module_name = f"wanxiang_skill_{package.skill_id}_{package.version.replace('.', '_')}"

            spec = importlib.util.spec_from_file_location(
                module_name,
                package.entry_point_path,
            )

            if spec is None or spec.loader is None:
                raise SkillLoadError(
                    f"无法创建模块 spec: {package.entry_point_path}"
                )

            module = importlib.util.module_from_spec(spec)

            # 将模块加入 sys.modules（支持相对导入）
            sys.modules[module_name] = module

            # 执行模块代码
            spec.loader.exec_module(module)

            # 查找 BaseSkill 子类
            for attr_name in dir(module):
                attr = getattr(module, attr_name)
                if (
                    isinstance(attr, type)
                    and issubclass(attr, BaseSkill)
                    and attr is not BaseSkill
                ):
                    logger.debug(
                        f"加载 Skill 类: {attr_name} from {package.entry_point_path}"
                    )
                    return attr

            raise SkillLoadError(
                f"在 {package.entry_point_path} 中未找到 BaseSkill 子类"
            )

        except Exception as e:
            logger.error(f"Skill 加载失败: {e}", exc_info=True)
            raise SkillLoadError(f"加载 Skill 失败: {e}") from e

    # ──────────────────────────────────────────
    # 安全审计
    # ──────────────────────────────────────────

    async def _security_audit(self, package: SkillPackage) -> dict:
        """
        Skill 安装安全审计

        检查项：
        1. 权限声明是否合法（都在 ALLOWED_PERMISSIONS 中）
        2. 代码中是否有危险导入（os.system, subprocess 等）
        3. 依赖包是否安全
        4. Python 版本兼容性

        Returns:
            {"safe": bool, "reason": str}
        """
        checks: dict[str, bool] = {}

        # 1. 权限检查
        checks["permissions_ok"] = all(
            p in ALLOWED_PERMISSIONS for p in package.permissions
        )

        # 2. 恶意代码扫描
        checks["no_malicious_imports"] = self._scan_malicious_code(
            package.entry_point_path
        )

        # 3. 依赖安全（简化版：检查是否有已知危险包）
        checks["dependencies_safe"] = self._audit_dependencies(
            package.dependencies
        )

        # 4. Python 版本兼容
        checks["version_compatible"] = self._check_python_version(
            package.python_version
        )

        all_safe = all(checks.values())
        failed = [k for k, v in checks.items() if not v]

        return {
            "safe": all_safe,
            "checks": checks,
            "reason": "; ".join(failed) if failed else "",
        }

    @staticmethod
    def _scan_malicious_code(file_path: str) -> bool:
        """
        扫描代码中的危险模式

        检测：
        - os.system / subprocess.call 直接执行命令
        - eval / exec 执行动态代码
        - __import__ 动态导入
        - open 写入敏感路径

        Returns:
            True = 安全（未检测到危险模式）
            False = 检测到危险代码
        """
        if not file_path or not os.path.exists(file_path):
            return True  # 没有代码可检查，跳过

        try:
            code = Path(file_path).read_text(encoding="utf-8")
        except Exception:
            return True

        dangerous_patterns = [
            "os.system(",
            "subprocess.call(",
            "subprocess.Popen(",
            "subprocess.run(",
            "eval(",
            "exec(",
            "__import__(",
            "shutil.rmtree('/",
            "shutil.rmtree('C:",
            "open('/etc/",
            "open('C:\\\\Windows",
        ]

        code_lower = code.lower()
        for pattern in dangerous_patterns:
            if pattern.lower() in code_lower:
                logger.warning(f"检测到危险代码模式: {pattern} in {file_path}")
                return False

        return True

    @staticmethod
    def _audit_dependencies(dependencies: list[str]) -> bool:
        """
        审计 Python 依赖安全性

        检查是否有已知的不安全包。
        """
        # 已知危险包（示例）
        blocked_packages = {"malicious_pkg", "trojan_horse", "eval_utils"}
        for dep in dependencies:
            # 提取包名（去掉版本号）
            pkg_name = dep.split(">")[0].split("<")[0].split("=")[0].strip()
            if pkg_name.lower() in blocked_packages:
                logger.warning(f"检测到不安全依赖: {pkg_name}")
                return False
        return True

    @staticmethod
    def _check_python_version(required: str) -> bool:
        """检查 Python 版本兼容性"""
        try:
            required_parts = tuple(int(x) for x in required.split("."))
            actual_parts = sys.version_info[:2]
            return actual_parts >= required_parts
        except (ValueError, AttributeError):
            return True  # 无法解析版本号，跳过检查

    async def _install_dependencies(self, dependencies: list[str]) -> None:
        """
        安装 Skill 的 Python 依赖

        使用 pip 安装指定的依赖包。
        """
        if not dependencies:
            return

        logger.info(f"安装 Skill 依赖: {dependencies}")

        # 构建 pip install 命令
        cmd = [sys.executable, "-m", "pip", "install", "--quiet"] + dependencies

        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

        stdout, stderr = await process.communicate()

        if process.returncode != 0:
            error_msg = stderr.decode("utf-8", errors="replace")
            logger.error(f"依赖安装失败: {error_msg}")
            raise SkillError(f"依赖安装失败: {error_msg}")

        logger.info("依赖安装完成")

    # ──────────────────────────────────────────
    # 上下文注入
    # ──────────────────────────────────────────

    def _inject_context_tools(self, ctx: SkillContext, skill: BaseSkill):
        """
        向 SkillContext 注入工具调用实现

        根据 Skill 的权限声明，限制可调用的工具。
        """

        # 覆盖 call_tool 方法
        async def _call_tool(tool_name: str, params: dict) -> dict:
            """受权限控制的工具调用"""
            # 权限检查
            if tool_name == "api_caller" and "web_request" not in skill.manifest.permissions:
                raise SkillError(
                    f"Skill {skill.manifest.skill_id} 无 web_request 权限"
                )

            logger.debug(
                f"Skill {skill.manifest.skill_id} 调用工具 {tool_name}: {params}"
            )

            # 模拟工具调用（实际实现由外部注入）
            # 在生产环境中，这里会调用实际的工具服务
            return {
                "success": True,
                "data": params,  # 回显参数作为模拟数据
            }

        async def _call_llm(prompt: str, model: str = "auto") -> str:
            """受配额控制的 LLM 调用"""
            logger.debug(
                f"Skill {skill.manifest.skill_id} 调用 LLM: model={model}"
            )
            # 模拟 LLM 响应
            return f"[LLM 响应] {prompt[:200]}"

        # 替换上下文方法
        ctx.call_tool = _call_tool
        ctx.call_llm = _call_llm

    # ──────────────────────────────────────────
    # 查询接口
    # ──────────────────────────────────────────

    def list_installed(self) -> list[dict]:
        """列出已安装的 Skill"""
        return [
            {
                "skill_id": skill_id,
                "name": skill.manifest.name,
                "version": skill.manifest.version,
                "description": skill.manifest.description,
                "icon": skill.manifest.icon,
                "triggers": skill.manifest.triggers,
                "capabilities": skill.manifest.capabilities,
                "permissions": skill.manifest.permissions,
                "reference_count": self._reference_count.get(skill_id, 0),
                "initialized": skill._initialized,
            }
            for skill_id, skill in self._loaded_skills.items()
        ]

    def get_manifest(self, skill_id: str) -> Optional[SkillManifest]:
        """获取已安装 Skill 的 Manifest"""
        return self._manifests.get(skill_id)

    def get_reference_count(self, skill_id: str) -> int:
        """获取 Skill 的当前引用计数"""
        return self._reference_count.get(skill_id, 0)

    def is_installed(self, skill_id: str) -> bool:
        """检查 Skill 是否已安装"""
        return skill_id in self._loaded_skills

    def match_skill(self, message: str) -> list[str]:
        """
        根据用户消息匹配 Skill（通过触发词）

        Returns:
            匹配的 skill_id 列表（按匹配度排序）
        """
        message_lower = message.lower()
        matched: list[tuple[str, int]] = []

        for skill_id, manifest in self._manifests.items():
            score = 0
            for trigger in manifest.triggers:
                if trigger.lower() in message_lower:
                    score += len(trigger)  # 越长的触发词匹配权重越高
            if score > 0:
                matched.append((skill_id, score))

        matched.sort(key=lambda x: x[1], reverse=True)
        return [skill_id for skill_id, _ in matched]

    # ──────────────────────────────────────────
    # 执行历史
    # ──────────────────────────────────────────

    def _add_history(self, record: ExecutionRecord):
        """添加执行记录到历史"""
        self._execution_history.append(record)
        if len(self._execution_history) > self._max_history:
            self._execution_history = self._execution_history[-self._max_history:]

    def get_execution_history(
        self,
        skill_id: Optional[str] = None,
        limit: int = 50,
    ) -> list[dict]:
        """
        获取执行历史

        Args:
            skill_id: 过滤指定 Skill（None 表示所有）
            limit:    返回条数上限
        """
        records = self._execution_history
        if skill_id:
            records = [r for r in records if r.skill_id == skill_id]
        return [r.to_dict() for r in records[-limit:]]

    def get_stats(self) -> dict:
        """获取运行时统计信息"""
        total = len(self._execution_history)
        success = sum(1 for r in self._execution_history if r.status == "success")
        failed = sum(1 for r in self._execution_history if r.status == "failed")
        timeout = sum(1 for r in self._execution_history if r.status == "timeout")

        avg_latency = 0.0
        if self._execution_history:
            latencies = [r.latency_ms for r in self._execution_history if r.latency_ms > 0]
            avg_latency = sum(latencies) / len(latencies) if latencies else 0.0

        return {
            "installed_skills": len(self._loaded_skills),
            "total_executions": total,
            "success_count": success,
            "failed_count": failed,
            "timeout_count": timeout,
            "success_rate": f"{(success / total * 100):.1f}%" if total > 0 else "N/A",
            "avg_latency_ms": round(avg_latency, 2),
            "active_references": sum(self._reference_count.values()),
        }

    # ──────────────────────────────────────────
    # 清理
    # ──────────────────────────────────────────

    async def shutdown(self) -> None:
        """关闭运行时，卸载所有 Skill"""
        logger.info("关闭 PluginRuntime...")

        for skill_id in list(self._loaded_skills.keys()):
            await self.uninstall(skill_id, force=True)

        await self.sandbox.shutdown()
        logger.info("PluginRuntime 已关闭")


# 需要导入 Path（用于安全扫描读取文件）
from pathlib import Path
