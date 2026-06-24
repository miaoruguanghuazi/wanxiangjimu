"""
marketplace.py — Marketplace API
================================

插件市场入口 API，提供：
1. 浏览   — 列出可用 Skill，按分类/标签筛选
2. 搜索   — 关键词搜索 Skill
3. 评分   — 对 Skill 评分和评论
4. 安装   — 一键安装 Skill
5. 详情   — 查看 Skill 详细信息
6. 发布   — 发布新 Skill 到市场

Marketplace 整合了 SkillStore（仓库）、PluginRuntime（运行时）
和评分系统，是面向用户的统一入口。
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Optional

from .base import SkillManifest
from .runtime import PluginRuntime
from .store import SkillStore

logger = logging.getLogger(__name__)


# ──────────────────────────────────────────────
# 评分与评论
# ──────────────────────────────────────────────

@dataclass
class SkillRating:
    """Skill 评分记录"""
    skill_id: str
    user_id: str
    score: int                      # 1-5 分
    comment: str = ""
    created_at: datetime = field(default_factory=datetime.now)

    def to_dict(self) -> dict:
        return {
            "skill_id": self.skill_id,
            "user_id": self.user_id,
            "score": self.score,
            "comment": self.comment,
            "created_at": self.created_at.isoformat(),
        }


@dataclass
class SkillListing:
    """
    市场中的 Skill 展示信息

    包含 Skill 的元数据、统计信息和评分，
    供浏览和搜索结果使用。
    """
    skill_id: str
    name: str
    version: str
    description: str
    author: str
    icon: str = "🔧"
    tags: list[str] = field(default_factory=list)
    triggers: list[str] = field(default_factory=list)
    capabilities: list[str] = field(default_factory=list)
    permissions: list[str] = field(default_factory=list)
    downloads: int = 0
    avg_rating: float = 0.0
    rating_count: int = 0
    installed: bool = False         # 当前用户是否已安装
    featured: bool = False          # 是否推荐

    def to_dict(self) -> dict:
        return {
            "skill_id": self.skill_id,
            "name": self.name,
            "version": self.version,
            "description": self.description,
            "author": self.author,
            "icon": self.icon,
            "tags": self.tags,
            "triggers": self.triggers,
            "capabilities": self.capabilities,
            "permissions": self.permissions,
            "downloads": self.downloads,
            "avg_rating": round(self.avg_rating, 1),
            "rating_count": self.rating_count,
            "installed": self.installed,
            "featured": self.featured,
        }


# ──────────────────────────────────────────────
# Marketplace — 市场入口
# ──────────────────────────────────────────────

class Marketplace:
    """
    Skill 市场入口

    整合 SkillStore + PluginRuntime + 评分系统，
    提供统一的浏览/搜索/安装/评分 API。

    使用示例::

        store = SkillStore()
        runtime = PluginRuntime(store, sandbox)
        market = Marketplace(store=store, runtime=runtime)

        # 浏览
        listings = await market.browse(category="生活")

        # 搜索
        results = await market.search("天气")

        # 安装
        await market.install("weather", config={"api_key": "xxx"})

        # 评分
        await market.rate("weather", user_id="u1", score=5, comment="很好用")
    """

    # 内置目录（模拟远程市场数据）
    _BUILTIN_CATALOG: list[dict] = [
        {
            "skill_id": "weather",
            "name": "天气查询",
            "version": "2.1.0",
            "description": "查询城市天气信息，支持实时天气和未来 7 天预报",
            "author": "community",
            "icon": "🌤️",
            "tags": ["生活", "天气"],
            "triggers": ["天气", "下雨", "温度", "weather"],
            "capabilities": ["realtime_weather", "7day_forecast"],
            "permissions": ["web_request"],
            "featured": True,
        },
        {
            "skill_id": "translator",
            "name": "多语言翻译",
            "version": "1.5.0",
            "description": "支持中英日韩等 20+ 语言的实时翻译",
            "author": "community",
            "icon": "🌐",
            "tags": ["工具", "翻译"],
            "triggers": ["翻译", "translate", "英语怎么说"],
            "capabilities": ["text_translate", "detect_language"],
            "permissions": ["web_request", "llm_call"],
            "featured": True,
        },
        {
            "skill_id": "code_reviewer",
            "name": "代码审查",
            "version": "3.0.0",
            "description": "AI 驱动的代码审查，支持 10+ 编程语言",
            "author": "wanxiang-team",
            "icon": "🔍",
            "tags": ["开发", "代码"],
            "triggers": ["代码审查", "review", "code review"],
            "capabilities": ["code_analysis", "security_check", "style_check"],
            "permissions": ["llm_call"],
            "featured": False,
        },
        {
            "skill_id": "calendar",
            "name": "日程管理",
            "version": "1.2.0",
            "description": "创建、查询和管理日程安排",
            "author": "community",
            "icon": "📅",
            "tags": ["效率", "日程"],
            "triggers": ["日程", "日历", "提醒", "schedule"],
            "capabilities": ["create_event", "query_events", "reminder"],
            "permissions": ["calendar", "notification"],
            "featured": False,
        },
        {
            "skill_id": "image_gen",
            "name": "AI 绘画",
            "version": "2.0.0",
            "description": "基于 Stable Diffusion 的 AI 图像生成",
            "author": "wanxiang-team",
            "icon": "🎨",
            "tags": ["创意", "AI", "图片"],
            "triggers": ["画画", "生成图片", "AI 绘画", "draw"],
            "capabilities": ["text_to_image", "image_editing"],
            "permissions": ["web_request"],
            "featured": True,
        },
        {
            "skill_id": "email_sender",
            "name": "邮件发送",
            "version": "1.0.0",
            "description": "通过邮件发送消息和文件",
            "author": "community",
            "icon": "📧",
            "tags": ["工具", "邮件"],
            "triggers": ["发邮件", "email", "send email"],
            "capabilities": ["send_email", "attach_file"],
            "permissions": ["send_email", "file_read"],
            "featured": False,
        },
    ]

    def __init__(
        self,
        store: SkillStore,
        runtime: PluginRuntime,
    ):
        """
        Args:
            store:   Skill 仓库
            runtime: 插件运行时
        """
        self.store = store
        self.runtime = runtime
        self._ratings: dict[str, list[SkillRating]] = {}  # {skill_id: [ratings]}
        self._download_counts: dict[str, int] = {}          # {skill_id: count}
        self._lock = asyncio.Lock()

    # ──────────────────────────────────────────
    # 浏览
    # ──────────────────────────────────────────

    async def browse(
        self,
        category: Optional[str] = None,
        tag: Optional[str] = None,
        featured_only: bool = False,
        sort_by: str = "downloads",       # downloads / rating / name / newest
        limit: int = 50,
    ) -> list[dict]:
        """
        浏览 Skill 市场

        Args:
            category:     分类筛选（如 "生活", "工具", "开发"）
            tag:          标签筛选
            featured_only: 只看推荐
            sort_by:      排序方式
            limit:        返回条数上限

        Returns:
            Skill 展示信息列表
        """
        listings = await self._build_listings()

        # 筛选
        if category:
            listings = [l for l in listings if category in l.tags]
        if tag:
            listings = [l for l in listings if tag in l.tags]
        if featured_only:
            listings = [l for l in listings if l.featured]

        # 排序
        if sort_by == "downloads":
            listings.sort(key=lambda x: x.downloads, reverse=True)
        elif sort_by == "rating":
            listings.sort(key=lambda x: x.avg_rating, reverse=True)
        elif sort_by == "name":
            listings.sort(key=lambda x: x.name)
        elif sort_by == "newest":
            listings.sort(key=lambda x: x.version, reverse=True)

        return [l.to_dict() for l in listings[:limit]]

    async def categories(self) -> list[dict]:
        """获取所有分类及其 Skill 数量"""
        listings = await self._build_listings()
        cat_count: dict[str, int] = {}

        for listing in listings:
            for tag in listing.tags:
                cat_count[tag] = cat_count.get(tag, 0) + 1

        return [
            {"name": cat, "count": count}
            for cat, count in sorted(cat_count.items(), key=lambda x: -x[1])
        ]

    # ──────────────────────────────────────────
    # 搜索
    # ──────────────────────────────────────────

    async def search(
        self,
        query: str,
        limit: int = 20,
    ) -> list[dict]:
        """
        搜索 Skill

        搜索范围：
        - 名称（权重 3）
        - 描述（权重 2）
        - 触发词（权重 2）
        - 标签（权重 1）

        Args:
            query: 搜索关键词
            limit: 返回条数上限

        Returns:
            匹配的 Skill 列表（按相关度排序）
        """
        query_lower = query.lower()
        listings = await self._build_listings()
        scored: list[tuple[SkillListing, int]] = []

        for listing in listings:
            score = 0

            # 名称匹配（权重 3）
            if query_lower in listing.name.lower():
                score += 3 * len(query)

            # 描述匹配（权重 2）
            if query_lower in listing.description.lower():
                score += 2

            # 触发词匹配（权重 2）
            for trigger in listing.triggers:
                if query_lower in trigger.lower():
                    score += 2

            # 标签匹配（权重 1）
            for tag in listing.tags:
                if query_lower in tag.lower():
                    score += 1

            # 能力匹配（权重 1）
            for cap in listing.capabilities:
                if query_lower in cap.lower():
                    score += 1

            if score > 0:
                scored.append((listing, score))

        # 按分数降序排序
        scored.sort(key=lambda x: x[1], reverse=True)

        return [listing.to_dict() for listing, _ in scored[:limit]]

    # ──────────────────────────────────────────
    # 详情
    # ──────────────────────────────────────────

    async def detail(self, skill_id: str) -> Optional[dict]:
        """
        获取 Skill 详细信息

        Returns:
            Skill 详情（包含 manifest、评分、安装状态等）
        """
        # 从目录中查找
        catalog_item = None
        for item in self._BUILTIN_CATALOG:
            if item["skill_id"] == skill_id:
                catalog_item = item
                break

        if not catalog_item:
            # 检查本地已安装
            manifest = self.runtime.get_manifest(skill_id)
            if manifest:
                catalog_item = manifest.to_dict()
            else:
                return None

        # 获取评分
        ratings = self._ratings.get(skill_id, [])
        avg_rating = sum(r.score for r in ratings) / len(ratings) if ratings else 0.0

        # 构建详情
        detail = {
            **catalog_item,
            "avg_rating": round(avg_rating, 1),
            "rating_count": len(ratings),
            "reviews": [r.to_dict() for r in ratings[-10:]],  # 最近 10 条评论
            "installed": self.runtime.is_installed(skill_id),
            "downloads": self._download_counts.get(skill_id, 0),
            "available_versions": await self.store.get_versions(skill_id) if self.runtime.is_installed(skill_id) else [],
        }

        return detail

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
        一键安装 Skill

        Args:
            skill_id: Skill 标识
            version:  版本
            config:   配置

        Returns:
            安装结果
        """
        result = await self.runtime.install(skill_id, version, config)

        # 更新下载计数
        if result.get("status") == "installed":
            async with self._lock:
                self._download_counts[skill_id] = self._download_counts.get(skill_id, 0) + 1

        return result

    async def uninstall(self, skill_id: str, force: bool = False) -> dict:
        """卸载 Skill"""
        return await self.runtime.uninstall(skill_id, force)

    async def upgrade(
        self,
        skill_id: str,
        target_version: str = "latest",
        strategy: str = "rolling",
        config: Optional[dict] = None,
    ) -> dict:
        """升级 Skill"""
        return await self.runtime.upgrade(skill_id, target_version, strategy, config)

    # ──────────────────────────────────────────
    # 评分 / 评论
    # ──────────────────────────────────────────

    async def rate(
        self,
        skill_id: str,
        user_id: str,
        score: int,
        comment: str = "",
    ) -> dict:
        """
        对 Skill 评分

        Args:
            skill_id: Skill 标识
            user_id:  评分用户 ID
            score:    评分（1-5）
            comment:  评论（可选）

        Returns:
            评分结果
        """
        if not 1 <= score <= 5:
            return {"status": "error", "message": "评分必须在 1-5 之间"}

        async with self._lock:
            if skill_id not in self._ratings:
                self._ratings[skill_id] = []

            # 检查用户是否已评分过
            existing = next(
                (r for r in self._ratings[skill_id] if r.user_id == user_id),
                None,
            )

            if existing:
                # 更新已有评分
                existing.score = score
                existing.comment = comment
                existing.created_at = datetime.now()
                action = "updated"
            else:
                # 添加新评分
                self._ratings[skill_id].append(
                    SkillRating(
                        skill_id=skill_id,
                        user_id=user_id,
                        score=score,
                        comment=comment,
                    )
                )
                action = "created"

            ratings = self._ratings[skill_id]
            avg = sum(r.score for r in ratings) / len(ratings)

            return {
                "status": "ok",
                "action": action,
                "skill_id": skill_id,
                "avg_rating": round(avg, 1),
                "rating_count": len(ratings),
            }

    async def get_ratings(
        self,
        skill_id: str,
        limit: int = 20,
    ) -> list[dict]:
        """获取 Skill 的评分列表"""
        ratings = self._ratings.get(skill_id, [])
        return [r.to_dict() for r in ratings[-limit:]]

    # ──────────────────────────────────────────
    # 发布
    # ──────────────────────────────────────────

    async def publish(
        self,
        manifest: dict,
        author_id: str,
    ) -> dict:
        """
        发布 Skill 到市场

        Args:
            manifest: Skill 元数据
            author_id: 发布者 ID

        Returns:
            发布结果
        """
        required_fields = ["skill_id", "name", "version", "description"]
        for field_name in required_fields:
            if not manifest.get(field_name):
                return {
                    "status": "error",
                    "message": f"缺少必填字段: {field_name}",
                }

        # 检查是否已存在
        skill_id = manifest["skill_id"]
        for item in self._BUILTIN_CATALOG:
            if item["skill_id"] == skill_id:
                return {
                    "status": "error",
                    "message": f"Skill {skill_id} 已存在",
                }

        # 添加到目录
        new_entry = {
            "skill_id": skill_id,
            "name": manifest["name"],
            "version": manifest["version"],
            "description": manifest["description"],
            "author": manifest.get("author", author_id),
            "icon": manifest.get("icon", "🔧"),
            "tags": manifest.get("tags", []),
            "triggers": manifest.get("triggers", []),
            "capabilities": manifest.get("capabilities", []),
            "permissions": manifest.get("permissions", []),
            "featured": False,
        }

        self._BUILTIN_CATALOG.append(new_entry)

        logger.info(f"新 Skill 已发布: {skill_id}@{manifest['version']} by {author_id}")

        return {
            "status": "published",
            "skill_id": skill_id,
            "version": manifest["version"],
        }

    # ──────────────────────────────────────────
    # 统计
    # ──────────────────────────────────────────

    async def market_stats(self) -> dict:
        """获取市场统计信息"""
        listings = await self._build_listings()

        total_downloads = sum(l.downloads for l in listings)
        total_ratings = sum(l.rating_count for l in listings)
        installed_count = sum(1 for l in listings if l.installed)

        return {
            "total_skills": len(listings),
            "installed_skills": installed_count,
            "total_downloads": total_downloads,
            "total_ratings": total_ratings,
            "featured_count": sum(1 for l in listings if l.featured),
            "categories": await self.categories(),
            "runtime_stats": self.runtime.get_stats(),
        }

    # ──────────────────────────────────────────
    # 内部方法
    # ──────────────────────────────────────────

    async def _build_listings(self) -> list[SkillListing]:
        """从目录和已安装列表构建 SkillListing"""
        listings: list[SkillListing] = []
        installed_ids = set()

        # 已安装的 Skill
        for item in self.runtime.list_installed():
            installed_ids.add(item["skill_id"])
            ratings = self._ratings.get(item["skill_id"], [])
            avg = sum(r.score for r in ratings) / len(ratings) if ratings else 0.0

            listings.append(SkillListing(
                skill_id=item["skill_id"],
                name=item["name"],
                version=item["version"],
                description=item["description"],
                author="installed",
                icon=item.get("icon", "🔧"),
                tags=item.get("triggers", []),
                triggers=item.get("triggers", []),
                capabilities=item.get("capabilities", []),
                permissions=item.get("permissions", []),
                downloads=self._download_counts.get(item["skill_id"], 0),
                avg_rating=avg,
                rating_count=len(ratings),
                installed=True,
            ))

        # 市场目录中的 Skill
        for item in self._BUILTIN_CATALOG:
            if item["skill_id"] in installed_ids:
                continue  # 已在已安装列表中

            skill_id = item["skill_id"]
            ratings = self._ratings.get(skill_id, [])
            avg = sum(r.score for r in ratings) / len(ratings) if ratings else 0.0

            listings.append(SkillListing(
                skill_id=skill_id,
                name=item["name"],
                version=item["version"],
                description=item["description"],
                author=item["author"],
                icon=item.get("icon", "🔧"),
                tags=item.get("tags", []),
                triggers=item.get("triggers", []),
                capabilities=item.get("capabilities", []),
                permissions=item.get("permissions", []),
                downloads=self._download_counts.get(skill_id, 0),
                avg_rating=avg,
                rating_count=len(ratings),
                installed=False,
                featured=item.get("featured", False),
            ))

        return listings
