"""
潮汐记忆系统配置管理

支持从以下位置加载配置（优先级从高到低）：
1. 环境变量
2. 项目根目录 config/yunxi.env（全局配置）
3. M5 模块目录 config/.env（模块私有配置）
4. 默认值
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any, Dict, Optional


def _find_project_root() -> Optional[Path]:
    """
    查找 yunxi-project 项目根目录。
    
    从当前文件位置向上查找，找到包含 config/yunxi.env 的目录。
    """
    current = Path(__file__).resolve()
    # 向上遍历最多 10 层
    for _ in range(10):
        current = current.parent
        if (current / "config" / "yunxi.env").exists():
            return current
    return None


def _load_dotenv_file(env_path: Path) -> None:
    """加载 .env 文件到环境变量（如果 python-dotenv 可用）"""
    if not env_path.exists():
        return
    try:
        from dotenv import load_dotenv
        load_dotenv(env_path, override=False)  # override=False 表示不覆盖已有的环境变量
    except ImportError:
        # python-dotenv 不可用时手动解析
        try:
            with open(env_path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line or line.startswith("#") or "=" not in line:
                        continue
                    key, _, value = line.partition("=")
                    key = key.strip()
                    value = value.strip().strip('"').strip("'")
                    if key and key not in os.environ:
                        os.environ[key] = value
        except Exception:
            pass


class TideConfig:
    """
    潮汐记忆系统配置管理器
    
    配置优先级：环境变量 > yunxi.env > 模块 .env > 配置文件 > 默认值
    """

    _DEFAULTS = {
        "basic": {
            "name": "m5-memory",
            "version": "2.4.0",
            "port": 8005,
            "log_level": "info",
            "env": "production",
        },
        "security": {
            "high_secret_local_only": True,
            "encrypt_at_rest": True,
            "encryption_algorithm": "AES-256-GCM",
            "access_audit": True,
            "secure_delete": True,
            "encryption_key": None,
            "admin_token": None,
            "jwt_secret": None,
        },
        "memory": {
            "layers": {
                "l0_beach": {"max_items": 100, "retention_hours": 1, "access_priority": 10},
                "l1_shallow": {"max_items": 1000, "retention_days": 1, "access_priority": 7},
                "l2_deep": {"max_items": 10000, "retention_days": 30, "access_priority": 4},
                "l3_abyss": {"max_items": 100000, "retention_days": -1, "access_priority": 1},
            },
            "consolidation_schedule": "0 3 * * *",
            "sleep_consolidation": True,
            "deduplication": True,
            "quality_driven_transfer": True,
        },
        "emotion": {
            "ei_inference": True,
            "model": "valence-arousal",
            "dimensions": ["valence", "arousal"],
            "high_emotion_priority": True,
        },
        "vector": {
            "type": "chroma",
            "embedding_model": "text-embedding-3-small",
            "dimension": 1536,
            "top_k": 10,
            "similarity_threshold": 0.7,
            "hnsw_index": True,
            "embedding_api_key": None,
            "embedding_base_url": None,
        },
        "storage": {
            "local_path": "./data/memory",
            "cloud_sync": False,
        },
        "audit": {
            "log_path": "./logs/m5-audit.log",
            "enabled": True,
        },
    }

    def __init__(self, config_path: Optional[str] = None):
        self._config: Dict[str, Any] = {}
        self._project_root: Optional[Path] = _find_project_root()
        
        # 1. 加载默认配置
        self._load_defaults()
        
        # 2. 从全局配置文件 yunxi.env 加载（项目根目录 config/yunxi.env）
        self._load_yunxi_env()
        
        # 3. 从模块私有配置文件加载
        self._load_module_env()
        
        # 4. 从指定配置文件加载（YAML/JSON）
        if config_path and os.path.exists(config_path):
            self._load_file(config_path)
        
        # 5. 从环境变量加载（最高优先级）
        self._load_env()

    def _load_defaults(self) -> None:
        """加载默认配置"""
        import copy
        self._config = copy.deepcopy(self._DEFAULTS)

    def _load_yunxi_env(self) -> None:
        """从项目根目录的 config/yunxi.env 加载全局配置"""
        if self._project_root:
            yunxi_env_path = self._project_root / "config" / "yunxi.env"
            if yunxi_env_path.exists():
                _load_dotenv_file(yunxi_env_path)

    def _load_module_env(self) -> None:
        """从 M5 模块目录的 config/.env 加载模块私有配置"""
        module_dir = Path(__file__).resolve().parent.parent.parent.parent  # M5-tide-memory/
        module_env_path = module_dir / "config" / ".env"
        if module_env_path.exists():
            _load_dotenv_file(module_env_path)

    def _load_file(self, path: str) -> None:
        """从配置文件加载（YAML 或 JSON）"""
        try:
            import yaml
            with open(path, "r", encoding="utf-8") as f:
                file_config = yaml.safe_load(f) or {}
            self._deep_update(self._config, file_config)
        except ImportError:
            # 没有pyyaml时使用简单JSON格式
            import json
            try:
                with open(path, "r", encoding="utf-8") as f:
                    file_config = json.load(f)
                self._deep_update(self._config, file_config)
            except (json.JSONDecodeError, FileNotFoundError):
                pass

    def _load_env(self) -> None:
        """从环境变量加载配置（覆盖所有其他来源）"""
        env_map = {
            # 基础配置
            "M5_PORT": ("basic.port", int),
            "M5_ENV": ("basic.env", str),
            "M5_LOG_LEVEL": ("basic.log_level", str),
            # 安全配置
            "M5_ENCRYPTION_KEY": ("security.encryption_key", str),
            "M5_ADMIN_TOKEN": ("security.admin_token", str),
            "M5_JWT_SECRET": ("security.jwt_secret", str),
            # 向量配置
            "M5_EMBEDDING_API_KEY": ("vector.embedding_api_key", str),
            "M5_EMBEDDING_BASE_URL": ("vector.embedding_base_url", str),
            "M5_VECTOR_BACKEND": ("vector.type", str),
            # 存储配置
            "M5_STORAGE_PATH": ("storage.local_path", str),
            # 审计配置
            "M5_AUDIT_ENABLED": ("audit.enabled", lambda v: v.lower() in ("true", "1", "yes")),
            "M5_AUDIT_LOG_PATH": ("audit.log_path", str),
        }
        for env_key, (config_path, converter) in env_map.items():
            value = os.environ.get(env_key)
            if value is not None:
                if converter and callable(converter) and converter is not str:
                    try:
                        value = converter(value)
                    except (ValueError, TypeError):
                        pass
                self.set(config_path, value)

    def get(self, path: str, default: Any = None) -> Any:
        """按路径获取配置，如 'memory.layers.l0_beach.max_items'"""
        keys = path.split(".")
        current = self._config
        for key in keys:
            if isinstance(current, dict) and key in current:
                current = current[key]
            else:
                return default
        return current

    def set(self, path: str, value: Any) -> None:
        """设置配置值"""
        keys = path.split(".")
        current = self._config
        for key in keys[:-1]:
            if key not in current or not isinstance(current[key], dict):
                current[key] = {}
            current = current[key]
        current[keys[-1]] = value

    @property
    def project_root(self) -> Optional[Path]:
        """获取项目根目录路径"""
        return self._project_root

    def to_dict(self) -> Dict[str, Any]:
        """导出完整配置字典（会脱敏敏感字段）"""
        import copy
        result = copy.deepcopy(self._config)
        # 脱敏敏感字段
        sensitive = ["encryption_key", "admin_token", "jwt_secret", "embedding_api_key"]
        self._sanitize_dict(result, sensitive)
        return result

    def _sanitize_dict(self, d: Dict, sensitive_keys: list) -> None:
        for key in list(d.keys()):
            if key in sensitive_keys and d[key]:
                d[key] = "***MASKED***"
            elif isinstance(d[key], dict):
                self._sanitize_dict(d[key], sensitive_keys)

    def _deep_update(self, base: Dict, update: Dict) -> None:
        """深度合并字典"""
        for key, value in update.items():
            if isinstance(value, dict) and key in base and isinstance(base[key], dict):
                self._deep_update(base[key], value)
            else:
                base[key] = value
# vim: set et ts=4 sw=4:
