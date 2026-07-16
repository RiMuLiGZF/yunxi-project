"""模式注册表模块.

提供业务模式的注册、注销、查询等管理功能。
所有业务模式在启动时通过 ModeRegistry 注册，
系统通过注册表获取和使用各种模式。
"""

from __future__ import annotations

from typing import Optional

from src.modes.base_mode import BaseMode


class ModeRegistry:
    """业务模式注册表.

    管理所有已注册的业务模式，提供注册、注销、查询、列表等功能。
    采用单例模式，全局只有一个注册表实例。

    使用方式:
        registry = ModeRegistry.get_instance()
        registry.register(GrowthMode())
        mode = registry.get("growth")
    """

    # 单例实例
    _instance: Optional["ModeRegistry"] = None

    # -----------------------------------------------------------------------
    # 单例模式
    # -----------------------------------------------------------------------

    @classmethod
    def get_instance(cls) -> "ModeRegistry":
        """获取注册表单例.

        Returns:
            ModeRegistry 单例实例
        """
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    # -----------------------------------------------------------------------
    # 初始化
    # -----------------------------------------------------------------------

    def __init__(self) -> None:
        """初始化注册表."""
        self._modes: dict[str, BaseMode] = {}
        self._default_mode_id: str = ""

    # -----------------------------------------------------------------------
    # 注册/注销
    # -----------------------------------------------------------------------

    def register(self, mode: BaseMode) -> None:
        """注册一个业务模式.

        Args:
            mode: 要注册的模式实例

        Raises:
            ValueError: 如果 mode_id 为空或已存在相同 mode_id
        """
        if not mode.mode_id:
            raise ValueError("模式 mode_id 不能为空")

        if mode.mode_id in self._modes:
            raise ValueError(f"模式 {mode.mode_id} 已注册")

        self._modes[mode.mode_id] = mode

        # 如果是第一个注册的模式，设为默认模式
        if not self._default_mode_id and mode.is_enabled:
            self._default_mode_id = mode.mode_id

    def unregister(self, mode_id: str) -> bool:
        """注销一个业务模式.

        Args:
            mode_id: 要注销的模式 ID

        Returns:
            True 表示注销成功，False 表示模式不存在
        """
        if mode_id not in self._modes:
            return False

        del self._modes[mode_id]

        # 如果注销的是默认模式，重新选择默认模式
        if mode_id == self._default_mode_id:
            enabled_modes = [
                m for m in self._modes.values() if m.is_enabled
            ]
            if enabled_modes:
                # 按优先级排序，选择优先级最高的作为默认
                enabled_modes.sort(key=lambda m: m.priority)
                self._default_mode_id = enabled_modes[0].mode_id
            else:
                self._default_mode_id = ""

        return True

    # -----------------------------------------------------------------------
    # 查询方法
    # -----------------------------------------------------------------------

    def get(self, mode_id: str) -> Optional[BaseMode]:
        """根据 mode_id 获取模式实例.

        Args:
            mode_id: 模式 ID

        Returns:
            模式实例，如果不存在返回 None
        """
        return self._modes.get(mode_id)

    def list_all(self) -> list[BaseMode]:
        """列出所有已注册的模式.

        Returns:
            所有模式列表，按优先级排序
        """
        modes = list(self._modes.values())
        modes.sort(key=lambda m: m.priority)
        return modes

    def list_enabled(self) -> list[BaseMode]:
        """列出所有已启用的模式.

        Returns:
            已启用模式列表，按优先级排序
        """
        enabled_modes = [m for m in self._modes.values() if m.is_enabled]
        enabled_modes.sort(key=lambda m: m.priority)
        return enabled_modes

    def get_by_category(self, category: str) -> list[BaseMode]:
        """按分类列出模式.

        Args:
            category: 分类名称

        Returns:
            该分类下的模式列表（仅包含已启用的），按优先级排序
        """
        category_modes = [
            m for m in self._modes.values()
            if m.category == category and m.is_enabled
        ]
        category_modes.sort(key=lambda m: m.priority)
        return category_modes

    def get_default(self) -> Optional[BaseMode]:
        """获取默认模式.

        默认模式是已启用模式中优先级最高的模式。

        Returns:
            默认模式实例，如果没有任何已启用的模式返回 None
        """
        if not self._default_mode_id:
            return None
        mode = self._modes.get(self._default_mode_id)
        if mode and mode.is_enabled:
            return mode
        # 默认模式被禁用了，重新选择
        enabled_modes = self.list_enabled()
        if enabled_modes:
            self._default_mode_id = enabled_modes[0].mode_id
            return enabled_modes[0]
        self._default_mode_id = ""
        return None

    # -----------------------------------------------------------------------
    # 其他方法
    # -----------------------------------------------------------------------

    def set_default(self, mode_id: str) -> bool:
        """设置默认模式.

        Args:
            mode_id: 要设为默认的模式 ID

        Returns:
            True 表示设置成功，False 表示模式不存在或未启用
        """
        mode = self._modes.get(mode_id)
        if mode is None or not mode.is_enabled:
            return False
        self._default_mode_id = mode_id
        return True

    def has(self, mode_id: str) -> bool:
        """检查是否存在指定 ID 的模式.

        Args:
            mode_id: 模式 ID

        Returns:
            True 表示存在，False 表示不存在
        """
        return mode_id in self._modes

    def count(self) -> int:
        """获取已注册模式的数量.

        Returns:
            模式总数
        """
        return len(self._modes)

    def count_enabled(self) -> int:
        """获取已启用模式的数量.

        Returns:
            已启用模式数量
        """
        return sum(1 for m in self._modes.values() if m.is_enabled)

    def clear(self) -> None:
        """清空所有已注册的模式."""
        self._modes.clear()
        self._default_mode_id = ""

    # -----------------------------------------------------------------------
    # 特殊方法
    # -----------------------------------------------------------------------

    def __len__(self) -> int:
        """返回已注册模式的数量."""
        return len(self._modes)

    def __contains__(self, mode_id: str) -> bool:
        """检查模式是否存在于注册表中."""
        return mode_id in self._modes

    def __repr__(self) -> str:
        """返回注册表的字符串表示."""
        return (
            f"<ModeRegistry "
            f"total={len(self._modes)} "
            f"enabled={self.count_enabled()} "
            f"default={self._default_mode_id!r}>"
        )
