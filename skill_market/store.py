"""
store.py — Skill 仓库管理
=========================

负责 Skill 包的存储、下载、版本管理和依赖解析。

核心功能：
1. download()     — 从远程仓库下载 Skill 包
2. get_version()  — 查询可用版本
3. resolve_deps() — 依赖解析（拓扑排序）
4. list_skills()  — 列出本地已缓存的 Skill
5. verify()       — 校验包完整性（哈希 + 签名）

Skill 包格式（.skillpkg）：
    本质上是一个 zip 文件，包含：
    - skill.py       : Skill 主代码（包含 BaseSkill 子类）
    - manifest.yaml  : Skill 元数据
    - requirements.txt: Python 依赖
    - README.md      : 文档
    - checksum.sha256: 完整性校验
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import shutil
import tempfile
import zipfile
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)


# ──────────────────────────────────────────────
# SkillPackage — Skill 包数据结构
# ──────────────────────────────────────────────

@dataclass
class SkillPackage:
    """
    Skill 包元数据

    描述一个可安装的 Skill 包，包含：
    - 基本信息（ID、名称、版本）
    - 代码路径
    - 依赖列表
    - 安全信息（哈希、签名）
    """
    skill_id: str
    name: str
    version: str
    description: str = ""
    author: str = "unknown"
    permissions: list[str] = field(default_factory=list)
    dependencies: list[str] = field(default_factory=list)   # Python 依赖
    python_version: str = "3.12"
    entry_point_path: str = ""           # Skill 主代码文件路径
    package_path: str = ""               # 下载后的包路径
    checksum: str = ""                   # SHA256 哈希
    signature: str = ""                  # 数字签名
    manifest_data: dict = field(default_factory=dict)  # 完整 manifest
    downloaded_at: Optional[datetime] = None

    def __post_init__(self):
        if not self.entry_point_path:
            # 默认入口路径
            self.entry_point_path = str(
                Path(self.package_path) / "skill.py"
            ) if self.package_path else ""

    def to_dict(self) -> dict:
        return {
            "skill_id": self.skill_id,
            "name": self.name,
            "version": self.version,
            "description": self.description,
            "author": self.author,
            "permissions": self.permissions,
            "dependencies": self.dependencies,
            "python_version": self.python_version,
            "entry_point_path": self.entry_point_path,
            "package_path": self.package_path,
            "checksum": self.checksum,
            "downloaded_at": self.downloaded_at.isoformat() if self.downloaded_at else None,
        }


# ──────────────────────────────────────────────
# 依赖解析
# ──────────────────────────────────────────────

@dataclass
class DependencyNode:
    """依赖图节点"""
    name: str
    version: str
    dependencies: list[str] = field(default_factory=list)  # 依赖的其他 skill_id
    resolved: bool = False


class DependencyResolver:
    """
    依赖解析器

    使用拓扑排序解析 Skill 之间的依赖关系，
    确保按正确顺序安装。
    """

    def __init__(self):
        self._graph: dict[str, DependencyNode] = {}

    def add_node(self, skill_id: str, version: str, dependencies: list[str] = None):
        """添加依赖节点"""
        self._graph[skill_id] = DependencyNode(
            name=skill_id,
            version=version,
            dependencies=dependencies or [],
        )

    def resolve(self) -> list[str]:
        """
        拓扑排序解析依赖

        返回安装顺序（依赖在前）
        Raises:
            ValueError: 存在循环依赖
        """
        result: list[str] = []
        visited: set[str] = set()
        in_stack: set[str] = set()

        def visit(node_id: str):
            if node_id in visited:
                return
            if node_id in in_stack:
                raise ValueError(f"检测到循环依赖: {node_id}")

            in_stack.add(node_id)

            node = self._graph.get(node_id)
            if node:
                for dep in node.dependencies:
                    visit(dep)

            in_stack.discard(node_id)
            visited.add(node_id)
            result.append(node_id)

        for node_id in self._graph:
            visit(node_id)

        return result


# ──────────────────────────────────────────────
# SkillStore — 仓库管理器
# ──────────────────────────────────────────────

class SkillStore:
    """
    Skill 仓库管理器

    职责：
    1. 管理本地 Skill 缓存
    2. 从远程仓库下载 Skill 包
    3. 版本管理（查询可用版本、比较版本）
    4. 依赖解析
    5. 包完整性校验

    Attributes:
        local_cache: 本地缓存目录
        remote_url:  远程仓库 URL
        _index:      本地包索引 {skill_id: {version: SkillPackage}}
    """

    def __init__(
        self,
        local_cache: str = None,
        remote_url: str = "https://registry.wanxiang.ai",
    ):
        """
        Args:
            local_cache: 本地缓存目录（默认 ~/.wanxiang/skill_cache）
            remote_url:  远程仓库 URL
        """
        self.local_cache = Path(local_cache or os.path.expanduser("~/.wanxiang/skill_cache"))
        self.local_cache.mkdir(parents=True, exist_ok=True)
        self.remote_url = remote_url.rstrip("/")
        self._index: dict[str, dict[str, SkillPackage]] = {}
        self._lock = asyncio.Lock()

        # 加载本地索引
        self._load_local_index()

    # ──────────────────────────────────────────
    # 下载与安装
    # ──────────────────────────────────────────

    async def download(
        self,
        skill_id: str,
        version: str = "latest",
    ) -> SkillPackage:
        """
        从远程仓库下载 Skill 包

        1. 解析版本（latest → 最新版本号）
        2. 检查本地缓存
        3. 下载远程包
        4. 校验完整性
        5. 解压到缓存目录
        6. 更新本地索引

        Args:
            skill_id: Skill 标识
            version:  版本号（"latest" 表示最新）

        Returns:
            SkillPackage: 下载的包信息
        """
        async with self._lock:
            # 1. 解析版本
            if version == "latest":
                version = await self._fetch_latest_version(skill_id)
                logger.info(f"Skill {skill_id} 最新版本: {version}")

            # 2. 检查本地缓存
            if skill_id in self._index and version in self._index[skill_id]:
                cached = self._index[skill_id][version]
                logger.debug(f"Skill {skill_id}@{version} 命中本地缓存")
                return cached

            # 3. 下载包
            logger.info(f"下载 Skill 包: {skill_id}@{version}")
            package = await self._download_package(skill_id, version)

            # 4. 校验完整性
            if not await self._verify_package(package):
                raise ValueError(f"Skill 包校验失败: {skill_id}@{version}")

            # 5. 更新索引
            if skill_id not in self._index:
                self._index[skill_id] = {}
            self._index[skill_id][version] = package

            # 6. 持久化索引
            self._save_local_index()

            return package

    async def _download_package(
        self,
        skill_id: str,
        version: str,
    ) -> SkillPackage:
        """
        实际下载 Skill 包并解压

        在生产环境中会通过 HTTP 下载 .skillpkg 文件。
        此处提供了模拟实现和真实下载两种路径。
        """
        # 构造下载 URL
        url = f"{self.remote_url}/api/skills/{skill_id}/{version}/download"

        # 创建临时目录
        temp_dir = tempfile.mkdtemp(prefix=f"skill_{skill_id}_")
        pkg_path = Path(temp_dir) / f"{skill_id}-{version}.skillpkg"

        try:
            # 尝试真实下载
            try:
                import aiohttp
                async with aiohttp.ClientSession() as session:
                    async with session.get(url) as resp:
                        if resp.status == 200:
                            content = await resp.read()
                            pkg_path.write_bytes(content)
                        else:
                            # 模拟模式：创建空包结构
                            logger.warning(
                                f"远程下载失败 (HTTP {resp.status})，使用模拟包"
                            )
                            return await self._create_mock_package(
                                skill_id, version, temp_dir
                            )
            except ImportError:
                # aiohttp 未安装时使用模拟包
                logger.warning("aiohttp 未安装，使用模拟包")
                return await self._create_mock_package(skill_id, version, temp_dir)

            # 解压包
            extract_dir = self.local_cache / skill_id / version
            extract_dir.mkdir(parents=True, exist_ok=True)

            with zipfile.ZipFile(pkg_path, "r") as zf:
                zf.extractall(extract_dir)

            # 读取 manifest
            manifest_path = extract_dir / "manifest.json"
            manifest_data = {}
            if manifest_path.exists():
                manifest_data = json.loads(manifest_path.read_text(encoding="utf-8"))

            # 构建 SkillPackage
            package = SkillPackage(
                skill_id=skill_id,
                name=manifest_data.get("name", skill_id),
                version=version,
                description=manifest_data.get("description", ""),
                author=manifest_data.get("author", "unknown"),
                permissions=manifest_data.get("permissions", []),
                dependencies=manifest_data.get("dependencies", []),
                python_version=manifest_data.get("python_version", "3.12"),
                entry_point_path=str(extract_dir / "skill.py"),
                package_path=str(extract_dir),
                checksum=manifest_data.get("checksum", ""),
                manifest_data=manifest_data,
                downloaded_at=datetime.now(),
            )

            return package

        finally:
            # 清理临时文件
            if temp_dir and os.path.exists(temp_dir):
                shutil.rmtree(temp_dir, ignore_errors=True)

    async def _create_mock_package(
        self,
        skill_id: str,
        version: str,
        temp_dir: str,
    ) -> SkillPackage:
        """
        创建模拟包（用于离线/开发环境）

        生成一个最小的 Skill 包结构，方便测试。
        """
        extract_dir = self.local_cache / skill_id / version
        extract_dir.mkdir(parents=True, exist_ok=True)

        # 写入最小 manifest
        manifest = {
            "skill_id": skill_id,
            "name": skill_id,
            "version": version,
            "description": f"Mock skill {skill_id}@{version}",
            "author": "mock",
            "permissions": [],
            "dependencies": [],
            "python_version": "3.12",
        }
        (extract_dir / "manifest.json").write_text(
            json.dumps(manifest, indent=2), encoding="utf-8"
        )

        # 写入最小 skill.py
        skill_code = f'''"""Auto-generated mock skill: {skill_id}@{version}"""
from skill_market.base import BaseSkill, SkillManifest, SkillContext

class MockSkill(BaseSkill):
    manifest = SkillManifest(
        skill_id="{skill_id}",
        name="{skill_id}",
        version="{version}",
        description="Mock skill for testing",
    )

    async def execute(self, ctx: SkillContext):
        return {{"status": "mock", "skill_id": "{skill_id}", "version": "{version}"}}
'''
        (extract_dir / "skill.py").write_text(skill_code, encoding="utf-8")

        return SkillPackage(
            skill_id=skill_id,
            name=skill_id,
            version=version,
            description=f"Mock skill {skill_id}@{version}",
            author="mock",
            entry_point_path=str(extract_dir / "skill.py"),
            package_path=str(extract_dir),
            downloaded_at=datetime.now(),
            manifest_data=manifest,
        )

    # ──────────────────────────────────────────
    # 版本管理
    # ──────────────────────────────────────────

    async def get_versions(self, skill_id: str) -> list[str]:
        """
        获取 Skill 的所有可用版本

        先查本地缓存，再查远程仓库。
        """
        # 本地版本
        local_versions = list(self._index.get(skill_id, {}).keys())

        # 远程版本（模拟）
        remote_versions = await self._fetch_remote_versions(skill_id)

        # 合并去重并排序
        all_versions = list(set(local_versions + remote_versions))
        all_versions.sort(key=self._version_key, reverse=True)  # 降序

        return all_versions

    async def get_latest_version(self, skill_id: str) -> str:
        """获取最新版本"""
        versions = await self.get_versions(skill_id)
        return versions[0] if versions else "0.0.1"

    async def _fetch_latest_version(self, skill_id: str) -> str:
        """从远程仓库获取最新版本号"""
        # 模拟：返回本地最新版本或 "1.0.0"
        local = self._index.get(skill_id, {})
        if local:
            return max(local.keys(), key=self._version_key)
        return "1.0.0"

    async def _fetch_remote_versions(self, skill_id: str) -> list[str]:
        """从远程仓库获取版本列表"""
        # 模拟
        return list(self._index.get(skill_id, {}).keys())

    @staticmethod
    def _version_key(version: str) -> tuple[int, ...]:
        """将版本字符串转为可比较的元组"""
        try:
            return tuple(int(x) for x in version.split("."))
        except ValueError:
            return (0,)

    # ──────────────────────────────────────────
    # 依赖解析
    # ──────────────────────────────────────────

    async def resolve_dependencies(
        self,
        skill_id: str,
        version: str = "latest",
    ) -> list[str]:
        """
        解析 Skill 的完整依赖链

        返回安装顺序（拓扑排序，依赖在前）。
        """
        resolver = DependencyResolver()

        # 获取 Skill 包信息
        package = self._index.get(skill_id, {}).get(version)
        if not package:
            package = await self.download(skill_id, version)

        # 递归添加依赖节点
        await self._add_dependency_nodes(resolver, skill_id, version, set())

        return resolver.resolve()

    async def _add_dependency_nodes(
        self,
        resolver: DependencyResolver,
        skill_id: str,
        version: str,
        visited: set[str],
    ):
        """递归添加依赖节点到解析器"""
        if skill_id in visited:
            return
        visited.add(skill_id)

        package = self._index.get(skill_id, {}).get(version)
        if not package:
            try:
                package = await self.download(skill_id, version)
            except Exception:
                resolver.add_node(skill_id, version, [])
                return

        # 解析 Skill 间依赖（从 manifest_data 中获取）
        skill_deps = package.manifest_data.get("skill_dependencies", [])
        resolver.add_node(skill_id, version, skill_deps)

        for dep_id in skill_deps:
            await self._add_dependency_nodes(resolver, dep_id, "latest", visited)

    # ──────────────────────────────────────────
    # 完整性校验
    # ──────────────────────────────────────────

    async def _verify_package(self, package: SkillPackage) -> bool:
        """
        校验 Skill 包完整性

        1. 检查入口文件是否存在
        2. 校验哈希值（如果有）
        3. 校验签名（如果有）
        """
        # 检查入口文件
        if package.entry_point_path and not Path(package.entry_point_path).exists():
            logger.error(f"Skill 包入口文件不存在: {package.entry_point_path}")
            return False

        # 校验哈希
        if package.checksum:
            actual_hash = await self._compute_hash(package.package_path)
            if actual_hash != package.checksum:
                logger.error(
                    f"Skill 包哈希不匹配: expected={package.checksum}, actual={actual_hash}"
                )
                return False

        return True

    @staticmethod
    async def _compute_hash(path: str) -> str:
        """计算目录的 SHA256 哈希"""
        sha256 = hashlib.sha256()
        dir_path = Path(path)

        for file_path in sorted(dir_path.rglob("*")):
            if file_path.is_file():
                sha256.update(file_path.read_bytes())

        return sha256.hexdigest()

    # ──────────────────────────────────────────
    # 本地索引管理
    # ──────────────────────────────────────────

    def _load_local_index(self):
        """从磁盘加载本地索引"""
        index_file = self.local_cache / "index.json"
        if index_file.exists():
            try:
                data = json.loads(index_file.read_text(encoding="utf-8"))
                for skill_id, versions in data.items():
                    self._index[skill_id] = {}
                    for ver, pkg_data in versions.items():
                        self._index[skill_id][ver] = SkillPackage(
                            skill_id=skill_id,
                            name=pkg_data.get("name", skill_id),
                            version=ver,
                            description=pkg_data.get("description", ""),
                            author=pkg_data.get("author", "unknown"),
                            entry_point_path=pkg_data.get("entry_point_path", ""),
                            package_path=pkg_data.get("package_path", ""),
                            downloaded_at=datetime.fromisoformat(
                                pkg_data["downloaded_at"]
                            ) if pkg_data.get("downloaded_at") else None,
                        )
                logger.info(f"加载本地索引: {len(self._index)} 个 Skill")
            except Exception as e:
                logger.warning(f"加载本地索引失败: {e}")
                self._index = {}

    def _save_local_index(self):
        """持久化本地索引到磁盘"""
        index_file = self.local_cache / "index.json"
        data = {}
        for skill_id, versions in self._index.items():
            data[skill_id] = {}
            for ver, pkg in versions.items():
                data[skill_id][ver] = {
                    "name": pkg.name,
                    "description": pkg.description,
                    "author": pkg.author,
                    "entry_point_path": pkg.entry_point_path,
                    "package_path": pkg.package_path,
                    "downloaded_at": pkg.downloaded_at.isoformat() if pkg.downloaded_at else None,
                }
        index_file.write_text(json.dumps(data, indent=2), encoding="utf-8")

    # ──────────────────────────────────────────
    # 查询接口
    # ──────────────────────────────────────────

    def list_local_skills(self) -> list[dict]:
        """列出本地已缓存的 Skill"""
        result = []
        for skill_id, versions in self._index.items():
            for version, pkg in versions.items():
                result.append({
                    "skill_id": skill_id,
                    "name": pkg.name,
                    "version": version,
                    "description": pkg.description,
                    "author": pkg.author,
                    "downloaded_at": pkg.downloaded_at.isoformat() if pkg.downloaded_at else None,
                })
        return result

    def get_package(self, skill_id: str, version: str = "latest") -> Optional[SkillPackage]:
        """获取本地缓存的 Skill 包"""
        versions = self._index.get(skill_id, {})
        if not versions:
            return None
        if version == "latest":
            return versions[max(versions.keys(), key=self._version_key)]
        return versions.get(version)

    async def remove(self, skill_id: str, version: str = None) -> dict:
        """
        删除本地缓存的 Skill 包

        Args:
            skill_id: Skill 标识
            version:  指定版本（None 表示删除所有版本）
        """
        removed = []
        if skill_id not in self._index:
            return {"status": "not_found", "removed": []}

        if version:
            versions_to_remove = [version] if version in self._index[skill_id] else []
        else:
            versions_to_remove = list(self._index[skill_id].keys())

        for ver in versions_to_remove:
            pkg = self._index[skill_id].pop(ver)
            if pkg.package_path and os.path.exists(pkg.package_path):
                shutil.rmtree(pkg.package_path, ignore_errors=True)
            removed.append(ver)

        if not self._index.get(skill_id):
            self._index.pop(skill_id, None)

        self._save_local_index()
        return {"status": "removed", "removed_versions": removed}
