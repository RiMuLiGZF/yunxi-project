"""业务模式模块.

统一导出所有业务模式和模式注册表，方便外部使用。

使用方式:
    from src.modes import mode_registry, GrowthMode, WorkDevMode
    # 或获取所有已注册的模式
    modes = mode_registry.list_enabled()
"""

from __future__ import annotations

from src.modes.base_mode import BaseMode
from src.modes.mode_registry import ModeRegistry

# 导入 8 大业务模式
from src.modes.growth import GrowthMode
from src.modes.work_dev import WorkDevMode
from src.modes.review import ReviewMode
from src.modes.study_plan import StudyPlanMode
from src.modes.life_management import LifeManagementMode
from src.modes.social_relation import SocialRelationMode
from src.modes.emotion_comfort import EmotionComfortMode
from src.modes.appearance import AppearanceMode


# ---------------------------------------------------------------------------
# 全局模式注册表实例
# ---------------------------------------------------------------------------

#: 全局模式注册表单例
mode_registry: ModeRegistry = ModeRegistry.get_instance()


# ---------------------------------------------------------------------------
# 注册所有内置模式
# ---------------------------------------------------------------------------

def register_all_modes() -> None:
    """注册所有内置业务模式到全局注册表.

    按优先级顺序注册 8 大业务模式。
    此函数可被重复调用（幂等），已注册的模式不会重复注册。
    """
    # 定义所有模式类，按优先级排序
    mode_classes = [
        GrowthMode,
        WorkDevMode,
        ReviewMode,
        StudyPlanMode,
        LifeManagementMode,
        SocialRelationMode,
        EmotionComfortMode,
        AppearanceMode,
    ]

    for mode_cls in mode_classes:
        mode_instance = mode_cls()
        if not mode_registry.has(mode_instance.mode_id):
            mode_registry.register(mode_instance)


# 自动注册所有模式
register_all_modes()


# ---------------------------------------------------------------------------
# 导出列表
# ---------------------------------------------------------------------------

__all__ = [
    # 基类
    "BaseMode",
    # 注册表
    "ModeRegistry",
    "mode_registry",
    "register_all_modes",
    # 8 大业务模式
    "GrowthMode",
    "WorkDevMode",
    "ReviewMode",
    "StudyPlanMode",
    "LifeManagementMode",
    "SocialRelationMode",
    "EmotionComfortMode",
    "AppearanceMode",
]
