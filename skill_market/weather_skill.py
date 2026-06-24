"""
weather_skill.py — 天气查询 Skill 示例实现
==========================================

这是一个完整的 BaseSkill 子类示例，展示了：
1. 如何定义 SkillManifest 元数据
2. 如何实现 execute() 方法
3. 如何通过 SkillContext 调用外部 API
4. 如何处理参数校验和错误情况
5. 如何覆盖生命周期钩子

注册到运行时后，当用户消息包含"天气""下雨""温度"等触发词时，
Orchestrator 会将请求路由到此 Skill。
"""

from __future__ import annotations

import logging
from typing import Any, Optional

from .base import BaseSkill, SkillContext, SkillManifest, SkillResult, ResultStatus

logger = logging.getLogger(__name__)


class WeatherSkill(BaseSkill):
    """
    天气查询 Skill

    功能：
    - 查询指定城市的实时天气
    - 支持 7 天预报
    - 支持摄氏/华氏单位切换

    权限要求：
    - web_request: 需要调用外部天气 API

    配置项：
    - api_key:     天气 API 密钥（必填）
    - default_city: 默认城市（默认"北京"）
    - units:       温度单位 metric/imperial（默认 metric）
    """

    manifest = SkillManifest(
        skill_id="weather",
        name="天气查询",
        version="2.1.0",
        description="查询城市天气信息，支持实时天气和未来 7 天预报",
        author="community",
        triggers=["天气", "下雨", "温度", "天气怎么样", "weather", "forecast"],
        capabilities=["realtime_weather", "7day_forecast"],
        permissions=["web_request"],
        sandbox=True,
        quota_limit=50,                       # 每分钟最多 50 次
        config_schema={
            "api_key": {
                "type": "string",
                "required": True,
                "description": "天气 API Key",
            },
            "default_city": {
                "type": "string",
                "default": "北京",
                "description": "默认查询城市",
            },
            "units": {
                "type": "string",
                "enum": ["metric", "imperial"],
                "default": "metric",
                "description": "温度单位制",
            },
        },
        tags=["生活", "天气"],
        icon="🌤️",
        python_version="3.12",
        dependencies=["aiohttp>=3.9"],
    )

    # ──────────────────────────────────────────
    # 生命周期钩子
    # ──────────────────────────────────────────

    async def on_install(self, config: Optional[dict] = None) -> dict:
        """安装时校验 API Key 是否存在"""
        self.config = config or {}

        if not self.config.get("api_key"):
            logger.warning("WeatherSkill 安装时未提供 api_key，运行时将无法查询天气")

        self._initialized = True
        logger.info(f"WeatherSkill v{self.manifest.version} 安装完成")
        return {"status": "installed", "config": self.config}

    async def on_uninstall(self) -> dict:
        """卸载时清理缓存"""
        self._initialized = False
        logger.info("WeatherSkill 已卸载")
        return {"status": "uninstalled"}

    async def on_upgrade(self, old_version: str, new_config: Optional[dict] = None) -> dict:
        """升级时处理配置迁移"""
        if new_config:
            self.config = {**self.config, **new_config}

        # 版本间数据迁移示例
        if old_version < "2.0.0":
            # v1.x → v2.x: api_key 字段名从 apiKey 改为 api_key
            if "apiKey" in self.config:
                self.config["api_key"] = self.config.pop("apiKey")

        logger.info(f"WeatherSkill 从 {old_version} 升级到 {self.manifest.version}")
        return {"status": "upgraded", "from": old_version, "to": self.manifest.version}

    # ──────────────────────────────────────────
    # 核心执行逻辑
    # ──────────────────────────────────────────

    async def execute(self, ctx: SkillContext) -> dict:
        """
        执行天气查询

        参数（通过 ctx.params 传入）:
            city:   查询城市（可选，默认使用配置中的 default_city）
            units:  温度单位（可选，默认使用配置中的 units）

        返回:
            dict: 天气信息，包含城市、温度、描述、湿度、风速和 7 天预报

        异常:
            SkillError: API 调用失败或参数错误
        """
        # 1. 解析参数
        city = ctx.params.get("city") or self.config.get("default_city", "北京")
        units = ctx.params.get("units") or self.config.get("units", "metric")
        api_key = self.config.get("api_key")

        if not api_key:
            return SkillResult.failed(
                error="未配置天气 API Key，请在 Skill 配置中设置 api_key",
                data={"city": city},
            ).to_dict()

        logger.info(f"WeatherSkill 查询: city={city}, units={units}")

        # 2. 调用外部天气 API
        #    通过 ctx.call_tool 间接调用，运行时会进行权限审计
        try:
            weather_data = await ctx.call_tool("api_caller", {
                "url": "https://api.weather.com/v1/current",
                "method": "GET",
                "params": {
                    "city": city,
                    "units": units,
                    "lang": "zh_cn",
                },
                "headers": {
                    "Authorization": f"Bearer {api_key}",
                    "Accept": "application/json",
                },
                "timeout": 10,
            })
        except Exception as e:
            logger.error(f"WeatherSkill API 调用失败: {e}")
            return SkillResult.failed(
                error=f"天气 API 调用失败: {e}",
                data={"city": city},
            ).to_dict()

        # 3. 解析并格式化结果
        if not weather_data or not weather_data.get("success", True):
            error_msg = weather_data.get("error", "未知错误") if weather_data else "空响应"
            return SkillResult.failed(
                error=error_msg,
                data={"city": city},
            ).to_dict()

        raw = weather_data.get("data", weather_data)

        result = {
            "city": city,
            "temperature": raw.get("temp") or raw.get("temperature"),
            "feels_like": raw.get("feels_like"),
            "description": self._extract_description(raw),
            "humidity": raw.get("humidity"),
            "wind": {
                "speed": raw.get("wind_speed") or raw.get("wind", {}).get("speed"),
                "direction": raw.get("wind_dir") or raw.get("wind", {}).get("direction"),
            },
            "units": units,
            "forecast_7day": self._extract_forecast(raw),
            "source": "api.weather.com",
        }

        return result

    # ──────────────────────────────────────────
    # 辅助方法
    # ──────────────────────────────────────────

    @staticmethod
    def _extract_description(raw: dict) -> str:
        """从 API 响应中提取天气描述"""
        if "weather" in raw and isinstance(raw["weather"], list) and raw["weather"]:
            return raw["weather"][0].get("description", "未知")
        return raw.get("description", "未知")

    @staticmethod
    def _extract_forecast(raw: dict) -> list[dict]:
        """从 API 响应中提取 7 天预报"""
        daily = raw.get("daily", [])
        forecast = []
        for day in daily[:7]:
            forecast.append({
                "date": day.get("date") or day.get("dt"),
                "temp_high": day.get("temp", {}).get("max") or day.get("temp_max"),
                "temp_low": day.get("temp", {}).get("min") or day.get("temp_min"),
                "description": (
                    day.get("weather", [{}])[0].get("description", "未知")
                    if day.get("weather") else day.get("description", "未知")
                ),
                "precipitation": day.get("precipitation_prob") or day.get("pop"),
            })
        return forecast

    async def describe(self) -> str:
        """返回详细的 Skill 描述（供 NLU 引擎匹配）"""
        return (
            f"🌤️ {self.manifest.name} (v{self.manifest.version})\n"
            f"功能: {self.manifest.description}\n"
            f"触发词: {', '.join(self.manifest.triggers)}\n"
            f"能力: {', '.join(self.manifest.capabilities)}\n"
            f"用法: 直接说「北京天气怎么样」或「明天会下雨吗」即可触发\n"
            f"配置: 需要 api_key（天气 API 密钥）"
        )
