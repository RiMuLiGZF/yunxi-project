"""技能基类模块.

定义所有技能的基类 BaseSkill，提供统一的接口规范，
包括技能基本信息、参数 Schema、执行方法和工具定义生成等。
"""

from __future__ import annotations

from typing import Any


class BaseSkill:
    """技能基类.

    所有内置技能和自定义技能都应继承此类，
    实现 execute 方法，并设置必要的属性。

    属性:
        name: 技能唯一标识（英文，用于函数调用）
        display_name: 显示名称（中文，用于界面展示）
        description: 技能描述（详细说明技能功能和用法）
        category: 技能分类，可选值：development / productivity / communication / system
        icon: 图标（emoji 字符）
        version: 版本号（语义化版本）
        parameters: JSON Schema 格式的参数定义（用于 function calling）
    """

    # 技能基本信息（子类必须覆盖）
    name: str = ""
    display_name: str = ""
    description: str = ""
    category: str = "system"  # development / productivity / communication / system
    icon: str = "🔧"
    version: str = "1.0.0"

    # 技能参数 Schema（JSON Schema 格式，用于 function calling）
    parameters: dict[str, Any] = {}

    # -----------------------------------------------------------------------
    # 核心方法
    # -----------------------------------------------------------------------

    def execute(self, params: dict[str, Any], context: dict[str, Any] | None = None) -> dict[str, Any]:
        """执行技能，返回结果字典.

        子类必须实现此方法。

        Args:
            params: 技能参数字典
            context: 执行上下文字典（可选，包含用户ID、场景ID等信息）

        Returns:
            执行结果字典，建议包含:
            - success: bool 是否成功
            - message: str 描述信息
            - data: dict 结果数据
        """
        raise NotImplementedError("子类必须实现 execute 方法")

    # -----------------------------------------------------------------------
    # 健康检查
    # -----------------------------------------------------------------------

    def health_check(self) -> bool:
        """技能健康检查.

        检查技能依赖的服务或资源是否可用。
        子类可根据需要重写此方法。

        Returns:
            True 表示健康，False 表示不可用
        """
        return True

    # -----------------------------------------------------------------------
    # 工具定义（供 Agent function calling 使用）
    # -----------------------------------------------------------------------

    def get_tool_definition(self) -> dict[str, Any]:
        """获取 function calling 格式的工具定义.

        返回符合 OpenAI function calling 规范的工具定义，
        供 Agent 框架使用。

        Returns:
            工具定义字典
        """
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }

    # -----------------------------------------------------------------------
    # 元信息获取
    # -----------------------------------------------------------------------

    def get_info(self) -> dict[str, Any]:
        """获取技能基本信息.

        Returns:
            技能信息字典
        """
        return {
            "name": self.name,
            "display_name": self.display_name,
            "description": self.description,
            "category": self.category,
            "icon": self.icon,
            "version": self.version,
            "parameters": self.parameters,
        }

    def __repr__(self) -> str:
        return f"<{self.__class__.__name__} name={self.name!r} version={self.version!r}>"
