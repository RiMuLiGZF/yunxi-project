"""
配置本地合并器 (LocalConfigMerger)

负责将本地配置文件与远程配置进行合并，支持：
- 本地配置文件（.env / config.yaml / config.json）作为默认值
- 远程配置覆盖本地配置
- 本地可强制覆盖某些配置（override）
- 配置优先级：实例 > 环境 > 模块 > 全局 > 本地文件

使用方式：
    from shared.config_sdk import LocalConfigMerger

    merger = LocalConfigMerger(
        local_config_path="config/config.yaml",
        override_path="config/override.yaml",
    )

    # 合并远程配置和本地配置
    merged = merger.merge(remote_configs)

    # 获取合并后的配置
    value = merger.get("database.host")
"""

from __future__ import annotations

import os
import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional
from copy import deepcopy

logger = logging.getLogger("config_sdk.merger")


class LocalConfigMerger:
    """本地配置合并器

    支持从多种本地配置源读取配置，并与远程配置合并。

    优先级从高到低：
    1. 本地强制覆盖（override）
    2. 实例级远程配置
    3. 环境级远程配置
    4. 模块级远程配置
    5. 全局远程配置
    6. 本地配置文件（.env / yaml / json）
    7. 默认值
    """

    # 优先级常量（数值越大优先级越高）
    PRIORITY_OVERRIDE = 100
    PRIORITY_INSTANCE = 80
    PRIORITY_ENV = 60
    PRIORITY_MODULE = 40
    PRIORITY_GLOBAL = 20
    PRIORITY_LOCAL = 10
    PRIORITY_DEFAULT = 0

    def __init__(
        self,
        local_config_path: Optional[str] = None,
        override_path: Optional[str] = None,
        env_prefix: str = "",
        defaults: Optional[Dict[str, Any]] = None,
    ):
        """
        Args:
            local_config_path: 本地配置文件路径（.yaml/.yml/.json/.env）
            override_path: 本地覆盖配置文件路径（优先级最高）
            env_prefix: 环境变量前缀（如 "M8_"）
            defaults: 默认配置字典
        """
        self._local_config: Dict[str, Any] = {}
        self._override_config: Dict[str, Any] = {}
        self._env_config: Dict[str, Any] = {}
        self._defaults: Dict[str, Any] = defaults or {}
        self._env_prefix = env_prefix

        # 加载本地配置
        if local_config_path:
            self._local_config = self._load_file(local_config_path)

        # 加载覆盖配置
        if override_path:
            self._override_config = self._load_file(override_path)

        # 从环境变量加载
        if env_prefix:
            self._env_config = self._load_from_env(env_prefix)

    # ============================================================
    # 公共 API
    # ============================================================

    def merge(
        self,
        remote_configs: Optional[Dict[str, Any]] = None,
        remote_scope: str = "module",
    ) -> Dict[str, Any]:
        """合并远程配置和本地配置

        Args:
            remote_configs: 远程配置字典 {key: value}
            remote_scope: 远程配置的作用域（global/module/env/instance）

        Returns:
            合并后的完整配置字典
        """
        merged = {}

        # 优先级从低到高依次应用
        # 1. 默认值
        merged.update(deepcopy(self._defaults))

        # 2. 本地配置文件
        merged.update(deepcopy(self._local_config))

        # 3. 环境变量
        merged.update(deepcopy(self._env_config))

        # 4. 远程配置（按作用域）
        if remote_configs:
            merged.update(deepcopy(remote_configs))

        # 5. 本地覆盖（最高优先级）
        merged.update(deepcopy(self._override_config))

        return merged

    def merge_layered(
        self,
        global_configs: Optional[Dict[str, Any]] = None,
        module_configs: Optional[Dict[str, Any]] = None,
        env_configs: Optional[Dict[str, Any]] = None,
        instance_configs: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """分层合并所有级别的配置

        优先级：instance > env > module > global > env vars > local file > defaults > override

        注意：override 优先级最高，用于本地强制覆盖。

        Args:
            global_configs: 全局配置
            module_configs: 模块配置
            env_configs: 环境配置
            instance_configs: 实例配置

        Returns:
            合并后的配置字典
        """
        merged = {}

        # 从低到高
        merged.update(deepcopy(self._defaults))
        merged.update(deepcopy(self._local_config))
        merged.update(deepcopy(self._env_config))
        if global_configs:
            merged.update(deepcopy(global_configs))
        if module_configs:
            merged.update(deepcopy(module_configs))
        if env_configs:
            merged.update(deepcopy(env_configs))
        if instance_configs:
            merged.update(deepcopy(instance_configs))
        # override 优先级最高
        merged.update(deepcopy(self._override_config))

        return merged

    def get(self, key: str, default: Any = None) -> Any:
        """获取合并后的配置值

        Args:
            key: 配置键
            default: 默认值

        Returns:
            配置值
        """
        # 依次从高优先级到低优先级查找
        if key in self._override_config:
            return self._override_config[key]

        if key in self._env_config:
            return self._env_config[key]

        if key in self._local_config:
            return self._local_config[key]

        if key in self._defaults:
            return self._defaults[key]

        return default

    def get_local_config(self) -> Dict[str, Any]:
        """获取本地配置"""
        return dict(self._local_config)

    def get_override_config(self) -> Dict[str, Any]:
        """获取覆盖配置"""
        return dict(self._override_config)

    def get_env_config(self) -> Dict[str, Any]:
        """获取环境变量配置"""
        return dict(self._env_config)

    def get_defaults(self) -> Dict[str, Any]:
        """获取默认配置"""
        return dict(self._defaults)

    def set_override(self, key: str, value: Any) -> None:
        """设置本地覆盖配置

        Args:
            key: 配置键
            value: 配置值
        """
        self._override_config[key] = value

    def clear_override(self, key: str) -> bool:
        """清除本地覆盖

        Args:
            key: 配置键

        Returns:
            是否存在并清除
        """
        if key in self._override_config:
            del self._override_config[key]
            return True
        return False

    # ============================================================
    # 内部方法
    # ============================================================

    def _load_file(self, path: str) -> Dict[str, Any]:
        """从文件加载配置

        支持 .yaml / .yml / .json / .env 格式
        """
        file_path = Path(path)
        if not file_path.exists():
            logger.debug("配置文件不存在: %s", path)
            return {}

        suffix = file_path.suffix.lower()

        try:
            if suffix in (".yaml", ".yml"):
                return self._load_yaml(file_path)
            elif suffix == ".json":
                return self._load_json(file_path)
            elif suffix in (".env", ""):
                return self._load_dotenv(file_path)
            else:
                logger.warning("不支持的配置文件格式: %s", suffix)
                return {}
        except Exception as e:
            logger.error("加载配置文件失败 %s: %s", path, e)
            return {}

    def _load_yaml(self, path: Path) -> Dict[str, Any]:
        """加载 YAML 配置文件"""
        try:
            import yaml
            with open(path, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f) or {}
            if isinstance(data, dict):
                # 扁平化嵌套结构
                return self._flatten_dict(data)
            return {}
        except ImportError:
            logger.warning("PyYAML 未安装，跳过 YAML 配置加载")
            return {}

    def _load_json(self, path: Path) -> Dict[str, Any]:
        """加载 JSON 配置文件"""
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict):
            return self._flatten_dict(data)
        return {}

    def _load_dotenv(self, path: Path) -> Dict[str, Any]:
        """加载 .env 配置文件"""
        result = {}
        try:
            from dotenv import dotenv_values
            values = dotenv_values(str(path))
            for key, value in values.items():
                if value is not None:
                    result[key.lower()] = self._parse_value(value)
        except ImportError:
            # 手动解析
            with open(path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line or line.startswith("#") or "=" not in line:
                        continue
                    key, _, value = line.partition("=")
                    key = key.strip().lower()
                    value = value.strip().strip('"').strip("'")
                    result[key] = self._parse_value(value)
        return result

    def _load_from_env(self, prefix: str) -> Dict[str, Any]:
        """从环境变量加载配置

        只加载带有指定前缀的环境变量。
        """
        result = {}
        prefix_lower = prefix.lower()
        for key, value in os.environ.items():
            key_lower = key.lower()
            if key_lower.startswith(prefix_lower):
                # 去掉前缀
                config_key = key_lower[len(prefix_lower):]
                result[config_key] = self._parse_value(value)
        return result

    def _parse_value(self, value: str) -> Any:
        """解析字符串值为合适的类型"""
        if not isinstance(value, str):
            return value

        # 布尔值
        if value.lower() in ("true", "yes", "1"):
            return True
        if value.lower() in ("false", "no", "0"):
            return False

        # 数字
        try:
            if "." in value:
                return float(value)
            return int(value)
        except (ValueError, TypeError):
            pass

        # JSON
        if (value.startswith("{") and value.endswith("}")) or \
           (value.startswith("[") and value.endswith("]")):
            try:
                return json.loads(value)
            except (json.JSONDecodeError, TypeError):
                pass

        return value

    def _flatten_dict(self, d: Dict[str, Any], parent_key: str = "", sep: str = ".") -> Dict[str, Any]:
        """将嵌套字典扁平化为点分路径键

        例如: {"database": {"host": "localhost"}} -> {"database.host": "localhost"}
        """
        items = {}
        for key, value in d.items():
            new_key = f"{parent_key}{sep}{key}" if parent_key else key
            if isinstance(value, dict):
                items.update(self._flatten_dict(value, new_key, sep))
            else:
                items[new_key] = value
        return items
