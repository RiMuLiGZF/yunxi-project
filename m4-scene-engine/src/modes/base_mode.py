"""业务模式基类模块.

定义所有业务模式的基类 BaseMode，提供统一的接口规范，
包括模式基本信息、生命周期方法、消息处理和配置管理等。

所有 8 大业务模式（成长中心、工作开发、复盘总结等）
都应继承此类并实现相应的方法。
"""

from __future__ import annotations

from typing import Any


class BaseMode:
    """业务模式基类.

    所有业务模式都应继承此类，实现生命周期方法和消息处理方法，
    并设置必要的基本信息属性。

    属性:
        mode_id: 模式唯一标识（英文小写，下划线分隔）
        mode_name: 模式名称（中文，用于界面展示）
        mode_description: 模式详细描述
        icon: 模式图标（emoji 字符）
        category: 模式分类（growth/work/study/life/social/emotion/appearance）
        priority: 优先级（数字越小优先级越高，用于推荐排序）
        is_enabled: 是否启用（禁用的模式不会出现在列表中）
    """

    # 模式基本信息（子类必须覆盖）
    mode_id: str = ""
    mode_name: str = ""
    mode_description: str = ""
    icon: str = "📦"
    category: str = "general"
    priority: int = 100
    is_enabled: bool = True

    # -----------------------------------------------------------------------
    # 生命周期方法
    # -----------------------------------------------------------------------

    async def on_enter(self, context: dict[str, Any]) -> dict[str, Any]:
        """进入模式时调用.

        子类可重写此方法，执行模式初始化、资源加载、欢迎语生成等操作。

        Args:
            context: 进入模式时的上下文字典，包含用户ID、当前场景、
                    历史记录等信息。

        Returns:
            进入模式的结果字典，建议包含:
            - success: bool 是否成功进入
            - message: str 欢迎消息或提示信息
            - data: dict 模式相关数据
            - context_updates: dict 需要更新到全局上下文的数据
        """
        return {
            "success": True,
            "message": f"已进入「{self.mode_name}」模式",
            "data": {},
            "context_updates": {},
        }

    async def on_leave(self, context: dict[str, Any]) -> dict[str, Any]:
        """离开模式时调用.

        子类可重写此方法，执行资源释放、状态保存、数据持久化等操作。

        Args:
            context: 离开模式时的上下文字典。

        Returns:
            离开模式的结果字典，建议包含:
            - success: bool 是否成功离开
            - message: str 离开消息
            - data: dict 离开时的数据
        """
        return {
            "success": True,
            "message": f"已离开「{self.mode_name}」模式",
            "data": {},
        }

    # -----------------------------------------------------------------------
    # 消息处理方法
    # -----------------------------------------------------------------------

    async def handle_message(
        self,
        message: str,
        context: dict[str, Any],
    ) -> dict[str, Any]:
        """处理用户消息.

        子类应实现此方法，处理用户在当前模式下的输入消息，
        并返回响应结果。

        Args:
            message: 用户输入的文本消息
            context: 当前上下文字典

        Returns:
            消息处理结果字典，建议包含:
            - success: bool 是否处理成功
            - reply: str 回复给用户的文本
            - data: dict 附加数据
            - context_updates: dict 需要更新的上下文
        """
        return {
            "success": True,
            "reply": f"[{self.mode_name}] 收到消息：{message}",
            "data": {},
            "context_updates": {},
        }

    # -----------------------------------------------------------------------
    # 配置管理方法
    # -----------------------------------------------------------------------

    async def get_config(self) -> dict[str, Any]:
        """获取模式配置.

        返回模式的可配置项及其当前值，供前端展示和用户调整。

        Returns:
            配置字典，格式为:
            {
                "config_key": {
                    "name": "配置项名称",
                    "description": "配置项描述",
                    "type": "string|number|boolean|select",
                    "value": 当前值,
                    "options": [选项列表] (仅 select 类型)
                }
            }
        """
        return {}

    # -----------------------------------------------------------------------
    # 信息获取方法
    # -----------------------------------------------------------------------

    def get_info(self) -> dict[str, Any]:
        """获取模式基本信息.

        Returns:
            模式信息字典，包含所有基本属性
        """
        return {
            "mode_id": self.mode_id,
            "mode_name": self.mode_name,
            "mode_description": self.mode_description,
            "icon": self.icon,
            "category": self.category,
            "priority": self.priority,
            "is_enabled": self.is_enabled,
        }

    # -----------------------------------------------------------------------
    # 特殊方法
    # -----------------------------------------------------------------------

    def __repr__(self) -> str:
        """返回模式的字符串表示."""
        return (
            f"<{self.__class__.__name__} "
            f"mode_id={self.mode_id!r} "
            f"mode_name={self.mode_name!r} "
            f"enabled={self.is_enabled}>"
        )
