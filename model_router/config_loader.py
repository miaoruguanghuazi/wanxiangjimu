"""
模型配置加载器 — 从 YAML 文件加载模型配置

支持:
- 从 YAML 文件加载
- 条件注册（依赖环境变量）
- 热加载外部 YAML
"""

from __future__ import annotations

import os
import logging
from typing import Optional

from .registry import ModelRegistry, ModelConfig

logger = logging.getLogger(__name__)


def load_from_yaml(yaml_path: str) -> ModelRegistry:
    """
    从 YAML 文件加载模型配置

    用法:
        registry = load_from_yaml("conf/models.yaml")
        # 如果文件不存在，回退到默认注册表
    """
    registry = ModelRegistry()

    try:
        import yaml
    except ImportError:
        logger.warning("PyYAML 未安装（pip install pyyaml），回退到默认注册表")
        from .registry import default_registry
        return default_registry()

    if not os.path.exists(yaml_path):
        logger.warning(f"YAML 配置不存在: {yaml_path}，回退到默认注册表")
        from .registry import default_registry
        return default_registry()

    try:
        with open(yaml_path, 'r', encoding='utf-8') as f:
            data = yaml.safe_load(f)
    except Exception as e:
        logger.error(f"YAML 解析失败: {e}，回退到默认注册表")
        from .registry import default_registry
        return default_registry()

    if not data or 'models' not in data:
        logger.warning("YAML 配置为空或无 models 字段，回退到默认注册表")
        from .registry import default_registry
        return default_registry()

    count = 0
    for cfg in data['models']:
        # 条件检查：如果定义了 condition 字段，检查对应环境变量
        condition = cfg.get('condition')
        if condition:
            env_val = os.environ.get(condition, '')
            if not env_val or 'xxxxx' in env_val.lower():
                logger.info(f"条件未满足 ({condition})，跳过注册 {cfg.get('model_id')}")
                continue

        # 转换 litellm_model 中的环境变量引用 {VAR_NAME}
        litellm_model = cfg.get('litellm_model', '')
        if '{' in litellm_model:
            import re
            for match in re.finditer(r'\{(\w+)\}', litellm_model):
                var_name = match.group(1)
                var_val = os.environ.get(var_name, '')
                if var_val:
                    litellm_model = litellm_model.replace(match.group(0), var_val)
                else:
                    logger.warning(f"litellm_model 引用了未设置的环境变量 {var_name}，跳过 {cfg.get('model_id')}")
                    continue

        try:
            model_config = ModelConfig(
                model_id=cfg['model_id'],
                litellm_model=litellm_model,
                provider=cfg.get('provider', 'unknown'),
                api_key_env=cfg.get('api_key_env', ''),
                context_window=cfg.get('context_window', 64000),
                max_output=cfg.get('max_output', 4096),
                pricing=cfg.get('pricing', {"input": 0.0, "output": 0.0}),
                capabilities=cfg.get('capabilities', ["text"]),
                speed_tier=cfg.get('speed_tier', 3),
                quality_scores=cfg.get('quality_scores', {}),
            )
            registry.register(model_config)
            count += 1
        except Exception as e:
            logger.warning(f"注册模型 {cfg.get('model_id', '?')} 失败: {e}")

    if count == 0:
        logger.warning("YAML 配置未注册任何模型，回退到默认注册表")
        from .registry import default_registry
        return default_registry()

    logger.info(f"✅ 从 YAML 配置加载了 {count} 个模型: {yaml_path}")
    return registry
