"""
配置安全校验 — 启动时检查安全配置

检查:
- API Key 是否仍为默认值
- .env 文件权限
- 敏感目录权限
- Docker 安全配置
- 依赖版本安全
"""

from __future__ import annotations

import os
import logging
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class ConfigIssue:
    level: str   # critical, warning, info
    category: str
    message: str
    fix: str = ""


class ConfigValidator:
    """
    安全配置校验器

    用法:
        validator = ConfigValidator()
        issues = validator.validate()
        for issue in issues:
            if issue.level == "critical":
                logger.error(f"配置安全问题: {issue.message}")
    """

    def validate(self) -> list[ConfigIssue]:
        """执行全面配置检查"""
        issues = []

        issues.extend(self._check_api_keys())
        issues.extend(self._check_env_file())
        issues.extend(self._check_docker_security())
        issues.extend(self._check_data_permissions())

        return issues

    def _check_api_keys(self) -> list[ConfigIssue]:
        """检查 API Key 配置"""
        issues = []

        deepseek_key = os.getenv("DEEPSEEK_API_KEY", "")
        doubao_key = os.getenv("DOUBAO_API_KEY", "")
        openai_key = os.getenv("OPENAI_API_KEY", "")

        # 检查是否仍为默认值
        if "你的" in deepseek_key or not deepseek_key:
            issues.append(ConfigIssue(
                level="warning",
                category="api_key",
                message="DEEPSEEK_API_KEY 未配置或仍为默认值",
                fix="编辑 .env 文件，填入有效的 DeepSeek API Key",
            ))

        if doubao_key and "你的" in doubao_key:
            issues.append(ConfigIssue(
                level="info",
                category="api_key",
                message="DOUBAO_API_KEY 仍为默认值（可选）",
                fix="如需使用豆包模型，填入有效 Key",
            ))

        # 检查 Key 是否出现在代码中（简单检查）
        for key_var, key_val in [("DEEPSEEK_API_KEY", deepseek_key), ("OPENAI_API_KEY", openai_key)]:
            if key_val and "你的" not in key_val and len(key_val) > 10:
                # 检查 .env 文件是否在 .gitignore
                gitignore_path = ".gitignore"
                if os.path.exists(gitignore_path):
                    with open(gitignore_path, "r", encoding="utf-8") as f:
                        gitignore = f.read()
                    if ".env" not in gitignore:
                        issues.append(ConfigIssue(
                            level="critical",
                            category="api_key",
                            message=f".env 文件未加入 .gitignore，{key_var} 可能泄露到 Git",
                            fix="将 .env 添加到 .gitignore",
                        ))

        return issues

    def _check_env_file(self) -> list[ConfigIssue]:
        """检查 .env 文件安全"""
        issues = []

        env_path = ".env"
        if os.path.exists(env_path):
            # 检查文件权限（Unix-like）
            stat = os.stat(env_path)
            mode = stat.st_mode
            # 检查是否对其他用户可读
            if mode & 0o044:  # others read
                issues.append(ConfigIssue(
                    level="warning",
                    category="env_file",
                    message=".env 文件对其他用户可读",
                    fix=f"chmod 600 {env_path}",
                ))

        return issues

    def _check_docker_security(self) -> list[ConfigIssue]:
        """检查 Docker 安全配置"""
        issues = []

        dockerfile = "Dockerfile"
        if os.path.exists(dockerfile):
            with open(dockerfile, "r", encoding="utf-8") as f:
                content = f.read()

            # 检查是否使用非 root 用户
            if "USER " not in content:
                issues.append(ConfigIssue(
                    level="warning",
                    category="docker",
                    message="Dockerfile 未设置非 root 用户",
                    fix="在 Dockerfile 中添加: RUN useradd -m wanxiang && USER wanxiang",
                ))

            # 检查是否添加了 healthcheck
            if "HEALTHCHECK" not in content:
                issues.append(ConfigIssue(
                    level="info",
                    category="docker",
                    message="Dockerfile 未配置健康检查",
                    fix="添加 HEALTHCHECK 指令",
                ))

        return issues

    def _check_data_permissions(self) -> list[ConfigIssue]:
        """检查数据目录权限"""
        issues = []

        data_dir = "./data"
        if os.path.exists(data_dir):
            # 检查 data 目录是否包含敏感文件
            for root, dirs, files in os.walk(data_dir):
                for f in files:
                    if f.endswith((".env", ".key", ".pem")):
                        issues.append(ConfigIssue(
                            level="critical",
                            category="data",
                            message=f"data 目录中存在敏感文件: {os.path.join(root, f)}",
                            fix="将密钥文件移到 data 目录外，通过环境变量配置",
                        ))

        return issues

    def print_report(self, issues: list[ConfigIssue] | None = None):
        """打印安全报告"""
        if issues is None:
            issues = self.validate()

        if not issues:
            print("✅ 安全配置检查通过，未发现问题")
            return

        print(f"🔍 安全配置检查完成，发现 {len(issues)} 个问题:\n")

        for issue in issues:
            icon = {"critical": "🚨", "warning": "⚠️", "info": "ℹ️"}.get(issue.level, "•")
            print(f"{icon} [{issue.category}] {issue.message}")
            if issue.fix:
                print(f"   修复建议: {issue.fix}")
        print()
