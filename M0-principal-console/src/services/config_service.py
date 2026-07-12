"""
M0 主理人管控台 - 配置服务

管理全局配置的读取和更新，
MVP 版本存储在本地 JSON 文件中。
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from ..config import settings


class ConfigService:
    """
    配置服务

    提供全局配置的 CRUD 操作，
    配置持久化存储在 data 目录下的 JSON 文件中。
    """

    def __init__(self) -> None:
        """初始化配置服务"""
        self._config_file: Path = settings.data_dir / "global_config.json"
        self._ensure_config_file()

    def _ensure_config_file(self) -> None:
        """确保配置文件存在，如果不存在则创建默认配置"""
        if not self._config_file.exists():
            default_config = {
                "meta": {
                    "updated_at": datetime.now().isoformat(),
                    "updated_by": "system",
                    "version": "1.0.0",
                },
                "categories": {
                    "system": {
                        "name": "系统设置",
                        "description": "全局系统级配置",
                        "items": {
                            "env": {
                                "value": "production",
                                "description": "运行环境",
                            },
                            "log_level": {
                                "value": "info",
                                "description": "日志级别",
                            },
                            "timezone": {
                                "value": "Asia/Shanghai",
                                "description": "时区",
                            },
                        },
                    },
                    "modules": {
                        "name": "模块管理",
                        "description": "各模块开关与基础配置",
                        "items": {
                            "auto_restart": {
                                "value": True,
                                "description": "模块异常时自动重启",
                            },
                            "heartbeat_interval": {
                                "value": 30,
                                "description": "心跳检测间隔（秒）",
                            },
                        },
                    },
                    "security": {
                        "name": "安全策略",
                        "description": "认证、授权、审计相关配置",
                        "items": {
                            "session_timeout": {
                                "value": 1440,
                                "description": "会话超时时间（分钟）",
                            },
                            "max_login_attempts": {
                                "value": 5,
                                "description": "最大登录尝试次数",
                            },
                            "audit_enabled": {
                                "value": True,
                                "description": "是否启用审计日志",
                            },
                        },
                    },
                    "notification": {
                        "name": "通知告警",
                        "description": "告警通知相关配置",
                        "items": {
                            "alert_enabled": {
                                "value": True,
                                "description": "是否启用告警通知",
                            },
                            "alert_channels": {
                                "value": ["email", "desktop"],
                                "description": "告警通知渠道",
                            },
                        },
                    },
                },
            }
            self._save_config(default_config)

    def _load_config(self) -> Dict[str, Any]:
        """
        从文件加载配置

        Returns:
            Dict: 完整配置字典
        """
        try:
            with open(self._config_file, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            # 文件损坏时返回默认空配置
            return {"meta": {}, "categories": {}}

    def _save_config(self, config: Dict[str, Any]) -> None:
        """
        保存配置到文件

        Args:
            config: 配置字典
        """
        self._config_file.parent.mkdir(parents=True, exist_ok=True)
        with open(self._config_file, "w", encoding="utf-8") as f:
            json.dump(config, f, ensure_ascii=False, indent=2)

    def get_all_config(self) -> Dict[str, Any]:
        """
        获取所有配置

        Returns:
            Dict: 完整配置，包含 meta 和 categories
        """
        return self._load_config()

    def get_categories(self) -> List[Dict[str, Any]]:
        """
        获取所有配置分类列表

        Returns:
            List[Dict]: 分类列表
        """
        config = self._load_config()
        categories = config.get("categories", {})
        result = []
        for key, cat in categories.items():
            item_count = len(cat.get("items", {}))
            result.append({
                "key": key,
                "name": cat.get("name", key),
                "description": cat.get("description", ""),
                "item_count": item_count,
            })
        return result

    def get_config_by_category(self, category: str) -> Dict[str, Any]:
        """
        获取指定分类的配置项

        Args:
            category: 分类键名

        Returns:
            Dict: 该分类的所有配置项
        """
        config = self._load_config()
        categories = config.get("categories", {})
        cat = categories.get(category)
        if not cat:
            return {}
        return cat.get("items", {})

    def get_config_value(self, category: str, key: str) -> Optional[Any]:
        """
        获取单个配置项的值

        Args:
            category: 分类键名
            key: 配置项键名

        Returns:
            Optional[Any]: 配置值，不存在返回 None
        """
        items = self.get_config_by_category(category)
        item = items.get(key)
        if item:
            return item.get("value")
        return None

    def update_config(
        self,
        category: str,
        key: str,
        value: Any,
        operator: str = "owner",
    ) -> bool:
        """
        更新单个配置项的值

        Args:
            category: 分类键名
            key: 配置项键名
            value: 新的配置值
            operator: 操作人

        Returns:
            bool: 是否更新成功
        """
        config = self._load_config()
        categories = config.setdefault("categories", {})
        cat = categories.setdefault(category, {"name": category, "items": {}})
        items = cat.setdefault("items", {})

        if key in items:
            items[key]["value"] = value
        else:
            items[key] = {"value": value, "description": ""}

        # 更新元信息
        meta = config.setdefault("meta", {})
        meta["updated_at"] = datetime.now().isoformat()
        meta["updated_by"] = operator

        self._save_config(config)
        return True

    def batch_update_config(
        self,
        updates: Dict[str, Dict[str, Any]],
        operator: str = "owner",
    ) -> int:
        """
        批量更新配置项

        Args:
            updates: 更新字典，格式为 {category: {key: value}}
            operator: 操作人

        Returns:
            int: 成功更新的配置项数量
        """
        count = 0
        for category, items in updates.items():
            for key, value in items.items():
                if self.update_config(category, key, value, operator):
                    count += 1
        return count

    def reset_config(self, operator: str = "owner") -> bool:
        """
        重置所有配置（删除配置文件，下次加载时重新生成默认配置）

        Args:
            operator: 操作人

        Returns:
            bool: 是否重置成功
        """
        try:
            if self._config_file.exists():
                self._config_file.unlink()
            self._ensure_config_file()
            return True
        except Exception:
            return False


# 全局单例
config_service = ConfigService()
