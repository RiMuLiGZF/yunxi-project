"""
P2-23: 系统设置数据仓库

key-value 存储，支持批量读取和写入。
迁移过渡期：优先读 DB，DB 为空时自动从 settings.json 迁移。
"""

import json
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, Optional, List
from sqlalchemy.orm import Session

from ..models import SystemSetting

# 默认设置
DEFAULT_SETTINGS = {
    "theme": "dark",
    "language": "zh-CN",
    "auto_start_modules": False,
    "notification_enabled": True,
    "auto_check_update": True,
    "log_level": "info",
}

# 设置描述
SETTING_DESCRIPTIONS = {
    "theme": "主题（dark/light）",
    "language": "语言（zh-CN/en-US）",
    "auto_start_modules": "是否自动启动模块",
    "notification_enabled": "是否启用通知",
    "auto_check_update": "是否自动检查更新",
    "log_level": "日志级别",
}


def _get_settings_json_path() -> Path:
    """获取 settings.json 文件路径"""
    return Path.home() / ".yunxi" / "settings.json"


def _load_settings_json() -> Dict[str, Any]:
    """从 JSON 文件加载设置"""
    json_path = _get_settings_json_path()
    if json_path.exists():
        try:
            with open(json_path, "r", encoding="utf-8") as f:
                saved = json.load(f)
            # 合并默认值
            merged = {**DEFAULT_SETTINGS, **saved}
            return merged
        except Exception:
            pass
    return DEFAULT_SETTINGS.copy()


def migrate_settings_from_json(db: Session) -> int:
    """将 settings.json 迁移到数据库.

    幂等操作：DB 中已有设置键则不覆盖。

    Args:
        db: 数据库 session

    Returns:
        迁移的设置数量
    """
    settings_json = _load_settings_json()
    if not settings_json:
        return 0

    migrated = 0
    for key, value in settings_json.items():
        existing = db.query(SystemSetting).filter(SystemSetting.setting_key == key).first()
        if not existing:
            db_setting = SystemSetting(
                setting_key=key,
                setting_value=value,
                description=SETTING_DESCRIPTIONS.get(key, ""),
                updated_at=datetime.utcnow(),
            )
            db.add(db_setting)
            migrated += 1

    if migrated > 0:
        db.commit()
        print(f"[Migration] 系统设置迁移完成: {migrated} 项")

    return migrated


class SettingsRepository:
    """系统设置数据仓库"""

    def __init__(self, db: Session):
        self.db = db
        self._ensure_migrated()

    def _ensure_migrated(self):
        """确保数据已迁移"""
        try:
            count = self.db.query(SystemSetting).count()
            if count == 0:
                migrate_settings_from_json(self.db)
        except Exception as e:
            print(f"[Migration] 系统设置迁移跳过: {e}")

    def get_all(self) -> Dict[str, Any]:
        """获取所有设置（合并默认值）"""
        result = DEFAULT_SETTINGS.copy()
        db_settings = self.db.query(SystemSetting).all()
        for s in db_settings:
            result[s.setting_key] = s.setting_value
        return result

    def get(self, key: str, default: Any = None) -> Any:
        """获取单个设置"""
        setting = self.db.query(SystemSetting).filter(SystemSetting.setting_key == key).first()
        if setting:
            return setting.setting_value
        return DEFAULT_SETTINGS.get(key, default)

    def set(self, key: str, value: Any, description: str = "") -> SystemSetting:
        """设置单个值（不存在则创建）"""
        setting = self.db.query(SystemSetting).filter(SystemSetting.setting_key == key).first()
        if setting:
            setting.setting_value = value
            if description:
                setting.description = description
            setting.updated_at = datetime.utcnow()
        else:
            setting = SystemSetting(
                setting_key=key,
                setting_value=value,
                description=description or SETTING_DESCRIPTIONS.get(key, ""),
                updated_at=datetime.utcnow(),
            )
            self.db.add(setting)
        self.db.commit()
        self.db.refresh(setting)
        return setting

    def update_batch(self, updates: Dict[str, Any]) -> Dict[str, Any]:
        """批量更新设置"""
        for key, value in updates.items():
            self.set(key, value)
        return self.get_all()

    def reset(self, key: str) -> bool:
        """重置单个设置为默认值"""
        if key not in DEFAULT_SETTINGS:
            return False
        self.set(key, DEFAULT_SETTINGS[key])
        return True

    def reset_all(self) -> Dict[str, Any]:
        """重置所有设置为默认值"""
        self.db.query(SystemSetting).delete()
        self.db.commit()
        # 重新写入默认值
        for key, value in DEFAULT_SETTINGS.items():
            self.db.add(SystemSetting(
                setting_key=key,
                setting_value=value,
                description=SETTING_DESCRIPTIONS.get(key, ""),
            ))
        self.db.commit()
        return DEFAULT_SETTINGS.copy()

    def count(self) -> int:
        """设置项数量"""
        return self.db.query(SystemSetting).count()
