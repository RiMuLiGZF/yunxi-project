"""
四级密级标记系统

密级分级：
- PUBLIC: 公开级，可对外共享
- INTERNAL: 内部级，仅限本系统内部访问
- CONFIDENTIAL: 机密级，仅限授权人员访问
- TOP_SECRET: 绝密级，仅限最高权限访问（本地加密存储）
"""

from __future__ import annotations

from enum import Enum
from typing import Dict, Optional


class ClassificationLevel(str, Enum):
    PUBLIC = "PUBLIC"                    # 公开级
    INTERNAL = "INTERNAL"                # 内部级
    CONFIDENTIAL = "CONFIDENTIAL"        # 机密级
    TOP_SECRET = "TOP_SECRET"            # 绝密级


# 密级降级策略
_LEVEL_ORDER = [
    ClassificationLevel.PUBLIC,
    ClassificationLevel.INTERNAL,
    ClassificationLevel.CONFIDENTIAL,
    ClassificationLevel.TOP_SECRET,
]


class SecretMarker:
    """
    密级标记管理器
    
    功能：
    - 记忆密级打标
    - 密级自动降级（基于时间）
    - 访问权限校验
    - 审计追踪
    """

    # 各密级保留天数（超过后自动降级）
    _RETENTION_DAYS = {
        ClassificationLevel.TOP_SECRET: 365,
        ClassificationLevel.CONFIDENTIAL: 180,
        ClassificationLevel.INTERNAL: 90,
        ClassificationLevel.PUBLIC: -1,  # 永久
    }

    # 各密级的访问角色
    _ACCESS_ROLES = {
        ClassificationLevel.PUBLIC: ["*"],  # 所有人
        ClassificationLevel.INTERNAL: ["internal", "confidential", "top_secret", "admin"],
        ClassificationLevel.CONFIDENTIAL: ["confidential", "top_secret", "admin"],
        ClassificationLevel.TOP_SECRET: ["top_secret", "admin"],
    }

    def __init__(self, default_level: ClassificationLevel = ClassificationLevel.TOP_SECRET):
        self._default_level = default_level
        self._markers: Dict[str, dict] = {}  # memory_id -> {level, marked_at, downgrade_scheduled}

    def mark(self, memory_id: str, level: ClassificationLevel = None,
             reason: str = "") -> dict:
        """
        给记忆打密级标记
        
        Args:
            memory_id: 记忆ID
            level: 密级，默认使用系统默认级
            reason: 标记原因
        
        Returns:
            标记结果
        """
        from datetime import datetime
        target_level = level or self._default_level

        self._markers[memory_id] = {
            "level": target_level.value,
            "marked_at": datetime.now().isoformat(),
            "reason": reason,
            "downgrade_scheduled": self._should_downgrade(target_level),
        }

        return {
            "memory_id": memory_id,
            "classification": target_level.value,
            "encrypted": target_level in [ClassificationLevel.CONFIDENTIAL, ClassificationLevel.TOP_SECRET],
            "local_only": target_level == ClassificationLevel.TOP_SECRET,
        }

    def check_access(self, memory_id: str, role: str) -> bool:
        """
        检查角色是否有权限访问指定密级的记忆
        
        Args:
            memory_id: 记忆ID
            role: 访问者角色
        """
        marker = self._markers.get(memory_id)
        if not marker:
            # 未标记的按默认级处理
            level = self._default_level
        else:
            level = ClassificationLevel(marker["level"])

        allowed_roles = self._ACCESS_ROLES.get(level, ["admin"])
        if "*" in allowed_roles:
            return True
        return role in allowed_roles

    def downgrade(self, memory_id: str) -> Optional[str]:
        """
        手动降级密级
        
        Returns:
            降级后的密级，如果已是最低级返回None
        """
        marker = self._markers.get(memory_id)
        if not marker:
            return None

        current = ClassificationLevel(marker["level"])
        current_idx = _LEVEL_ORDER.index(current)

        if current_idx > 0:
            new_level = _LEVEL_ORDER[current_idx - 1]
            marker["level"] = new_level.value
            return new_level.value
        return None

    def upgrade(self, memory_id: str, reason: str = "") -> Optional[str]:
        """升级密级"""
        marker = self._markers.get(memory_id)
        if not marker:
            self.mark(memory_id, ClassificationLevel.CONFIDENTIAL, reason)
            return ClassificationLevel.CONFIDENTIAL.value

        current = ClassificationLevel(marker["level"])
        current_idx = _LEVEL_ORDER.index(current)

        if current_idx < len(_LEVEL_ORDER) - 1:
            new_level = _LEVEL_ORDER[current_idx + 1]
            marker["level"] = new_level.value
            marker["reason"] = reason
            return new_level.value
        return None

    def get_level(self, memory_id: str) -> str:
        """获取记忆密级"""
        marker = self._markers.get(memory_id)
        if marker:
            return marker["level"]
        return self._default_level.value

    def _should_downgrade(self, level: ClassificationLevel) -> bool:
        """判断是否需要计划降级"""
        return self._RETENTION_DAYS.get(level, -1) > 0

    def batch_check_downgrade(self) -> list:
        """
        批量检查需要降级的记忆
        
        Returns:
            需要降级的记忆列表
        """
        from datetime import datetime, timedelta
        to_downgrade = []

        for memory_id, marker in self._markers.items():
            level = ClassificationLevel(marker["level"])
            retention = self._RETENTION_DAYS.get(level, -1)
            if retention <= 0:
                continue

            marked_at = datetime.fromisoformat(marker["marked_at"])
            if datetime.now() - marked_at > timedelta(days=retention):
                to_downgrade.append({
                    "memory_id": memory_id,
                    "current_level": level.value,
                    "marked_days": (datetime.now() - marked_at).days,
                    "retention_days": retention,
                })

        return to_downgrade

    def encrypt_required(self, level: ClassificationLevel) -> bool:
        """判断该密级是否需要加密存储"""
        return level in [ClassificationLevel.CONFIDENTIAL, ClassificationLevel.TOP_SECRET]

    def local_only(self, level: ClassificationLevel) -> bool:
        """判断该密级是否仅限本地存储（不能同步云端）"""
        return level == ClassificationLevel.TOP_SECRET

    def get_stats(self) -> Dict:
        stats = {level.value: 0 for level in ClassificationLevel}
        for marker in self._markers.values():
            level = marker["level"]
            if level in stats:
                stats[level] += 1
        return stats
# vim: set et ts=4 sw=4:
