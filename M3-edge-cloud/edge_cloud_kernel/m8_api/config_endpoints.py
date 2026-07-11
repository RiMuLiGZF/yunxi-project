"""配置管理接口（M8 标准）.

提供 M8 管理平台需要的配置管理接口：
- GET  /api/v3/config          # 获取配置（敏感字段脱敏）
- POST /api/v3/config/update   # 更新配置（点路径，热更新）
"""

from __future__ import annotations

import copy
import os
import time
import uuid
from typing import Any

import structlog
import yaml

from edge_cloud_kernel.m8_api.error_codes import ERR_INVALID_PARAM

logger = structlog.get_logger(__name__)

# 敏感字段列表（输出时脱敏，且不允许通过 API 更新）
SENSITIVE_KEYS = {
    "encryption_key",
    "admin_token",
    "password",
    "secret",
    "private_key",
    "api_key",
}

# 需要重启的配置键
RESTART_REQUIRED_KEYS = {
    "basic.port",
    "database.path",
    "database.type",
    "storage.local_path",
}


class ConfigManager:
    """配置管理器.

    提供配置的加载、查询、更新（热更新）功能。
    敏感字段在输出时自动脱敏，且不允许通过 API 更新。

    Attributes:
        _config: 当前配置字典.
        _config_path: 配置文件路径.
        _audit_log: 配置变更审计日志.
    """

    def __init__(self, config_path: str = "") -> None:
        """初始化配置管理器.

        Args:
            config_path: 配置文件路径（YAML格式）。为空则使用默认配置.
        """
        self._config: dict[str, Any] = {}
        self._config_path = config_path
        self._audit_log: list[dict[str, Any]] = []
        self._default_config = self._get_default_config()

        if config_path and os.path.exists(config_path):
            self._load_from_file(config_path)
        else:
            self._config = copy.deepcopy(self._default_config)

        logger.info(
            "config_manager.initialized",
            path=config_path or "default",
            keys_count=len(self._flatten_keys(self._config)),
        )

    def _get_default_config(self) -> dict[str, Any]:
        """获取默认配置."""
        return {
            "basic": {
                "name": "m3-sync",
                "version": "2.1.2",
                "port": 8003,
                "log_level": "info",
                "env": "production",
            },
            "security": {
                "encryption_key": "",
                "admin_token": "",
                "cors_origins": ["http://localhost:3000"],
                "e2ee": {
                    "enabled": True,
                    "algorithm": "AES-256-GCM",
                },
            },
            "sync": {
                "mode": "auto",
                "interval": 60,
                "conflict_strategy": "newest_wins",
                "max_concurrent": 10,
                "max_file_size": 100,
            },
            "storage": {
                "local_path": "./data/sync",
                "cloud_type": "local",
                "cloud_path": "./data/cloud",
                "cache_size": 512,
            },
            "offline": {
                "queue_size": 1000,
                "retry": {
                    "max_attempts": 5,
                    "backoff": "exponential",
                },
            },
            "database": {
                "type": "sqlite",
                "path": "./data/m3.db",
            },
            "logging": {
                "format": "json",
                "level": "info",
                "file": "./logs/m3.log",
                "max_size": "100MB",
                "max_files": 10,
                "sensitive_fields": ["encryption_key", "password"],
            },
            "devices": {
                "registry_type": "memory",
                "db_path": "./data/devices.db",
            },
        }

    def _load_from_file(self, path: str) -> None:
        """从 YAML 文件加载配置."""
        try:
            with open(path, "r", encoding="utf-8") as f:
                loaded = yaml.safe_load(f) or {}
            # 与默认配置合并
            self._config = self._deep_merge(self._default_config, loaded)
            logger.info("config_manager.loaded", path=path)
        except Exception as e:
            logger.error("config_manager.load_error", path=path, error=str(e))
            self._config = copy.deepcopy(self._default_config)

    def _deep_merge(self, base: dict, override: dict) -> dict:
        """深度合并两个字典（override 覆盖 base）."""
        result = copy.deepcopy(base)
        for key, value in override.items():
            if key in result and isinstance(result[key], dict) and isinstance(value, dict):
                result[key] = self._deep_merge(result[key], value)
            else:
                result[key] = value
        return result

    # -----------------------------------------------------------------------
    # GET /api/v3/config
    # -----------------------------------------------------------------------

    def get_config_sanitized(self, request_id: str = "") -> dict[str, Any]:
        """获取配置（敏感字段脱敏）.

        Args:
            request_id: 请求追踪ID.

        Returns:
            脱敏后的配置字典.
        """
        if not request_id:
            request_id = uuid.uuid4().hex[:16]
        sanitized = self._sanitize(copy.deepcopy(self._config))
        return sanitized

    def _sanitize(self, config: dict[str, Any]) -> dict[str, Any]:
        """递归脱敏敏感字段."""
        for key, value in config.items():
            if key.lower() in SENSITIVE_KEYS:
                if value:
                    config[key] = "***"
            elif isinstance(value, dict):
                config[key] = self._sanitize(value)
            elif isinstance(value, list):
                config[key] = [
                    self._sanitize(item) if isinstance(item, dict) else item
                    for item in value
                ]
        return config

    # -----------------------------------------------------------------------
    # POST /api/v3/config/update
    # -----------------------------------------------------------------------

    def update_config(
        self,
        updates: dict[str, Any],
        request_id: str = "",
    ) -> tuple[bool, dict[str, Any]]:
        """更新配置（点路径方式）.

        Args:
            updates: 点路径的更新字典，如 {"sync.mode": "manual", "logging.level": "debug"}.
            request_id: 请求追踪ID.

        Returns:
            (是否成功, 结果字典).
        """
        if not request_id:
            request_id = uuid.uuid4().hex[:16]

        if not isinstance(updates, dict) or not updates:
            return False, {
                "error": ERR_INVALID_PARAM.message,
                "code": ERR_INVALID_PARAM.code,
            }

        updated_keys: list[str] = []
        restart_required = False
        rejected_keys: list[str] = []

        for dot_key, value in updates.items():
            # 检查是否为敏感字段（不允许更新）
            if self._is_sensitive_key(dot_key):
                rejected_keys.append(dot_key)
                continue

            # 检查 key 是否存在
            if not self._key_exists(dot_key):
                rejected_keys.append(f"{dot_key}(not_found)")
                continue

            # 执行更新
            self._set_by_dot_key(dot_key, value)
            updated_keys.append(dot_key)

            # 检查是否需要重启
            if dot_key in RESTART_REQUIRED_KEYS:
                restart_required = True

        # 记录审计日志
        if updated_keys:
            self._audit_log.append({
                "request_id": request_id,
                "updated_keys": updated_keys,
                "timestamp": time.time(),
            })
            logger.info(
                "config_manager.updated",
                request_id=request_id,
                updated_count=len(updated_keys),
                restart_required=restart_required,
            )

        if rejected_keys:
            logger.warning(
                "config_manager.rejected",
                request_id=request_id,
                rejected=rejected_keys,
            )

        return True, {
            "updated_keys": updated_keys,
            "rejected_keys": rejected_keys,
            "restart_required": restart_required,
        }

    def _is_sensitive_key(self, dot_key: str) -> bool:
        """判断点路径 key 是否为敏感字段."""
        parts = dot_key.split(".")
        last_key = parts[-1].lower()
        return last_key in SENSITIVE_KEYS

    def _key_exists(self, dot_key: str) -> bool:
        """检查点路径 key 是否存在于配置中."""
        current = self._config
        for part in dot_key.split("."):
            if isinstance(current, dict) and part in current:
                current = current[part]
            else:
                return False
        return True

    def _set_by_dot_key(self, dot_key: str, value: Any) -> None:
        """按点路径设置配置值."""
        current = self._config
        parts = dot_key.split(".")
        for part in parts[:-1]:
            if part not in current:
                current[part] = {}
            current = current[part]
        current[parts[-1]] = value

    def _flatten_keys(self, config: dict, prefix: str = "") -> list[str]:
        """获取所有点路径的 key 列表."""
        keys = []
        for key, value in config.items():
            full_key = f"{prefix}.{key}" if prefix else key
            if isinstance(value, dict):
                keys.extend(self._flatten_keys(value, full_key))
            else:
                keys.append(full_key)
        return keys

    # -----------------------------------------------------------------------
    # 其他方法
    # -----------------------------------------------------------------------

    def get(self, key: str, default: Any = None) -> Any:
        """按点路径获取配置值."""
        current = self._config
        for part in key.split("."):
            if isinstance(current, dict) and part in current:
                current = current[part]
            else:
                return default
        return current

    @property
    def raw_config(self) -> dict[str, Any]:
        """获取原始配置（含敏感字段，内部使用）."""
        return copy.deepcopy(self._config)

    @property
    def audit_log(self) -> list[dict[str, Any]]:
        """获取审计日志."""
        return self._audit_log.copy()
