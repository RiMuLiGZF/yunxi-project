"""
云汐 API 网关 - 插件基类

定义插件接口和上下文对象。
"""
from typing import Dict, Any, Optional
from dataclasses import dataclass, field


@dataclass
class PluginContext:
    """插件上下文

    在插件之间传递的请求/响应上下文。
    """
    # 请求信息
    request_method: str = ""
    request_path: str = ""
    request_headers: Dict[str, str] = field(default_factory=dict)
    request_query: Dict[str, Any] = field(default_factory=dict)
    request_body: Optional[bytes] = None
    client_ip: str = ""
    user_info: Optional[Dict[str, Any]] = None

    # 响应信息（post_response 阶段填充）
    response_status: int = 0
    response_headers: Dict[str, str] = field(default_factory=dict)
    response_body: Optional[bytes] = None

    # 元数据
    request_id: str = ""
    route_key: str = ""
    start_time: float = 0.0
    latency_ms: float = 0.0

    # 错误信息（on_error 阶段填充）
    error: Optional[Exception] = None
    error_message: str = ""

    # 插件间共享数据
    extra: Dict[str, Any] = field(default_factory=dict)


class BasePlugin:
    """插件基类

    所有插件都必须继承此类，并实现相应的钩子方法。

    钩子执行顺序：
    1. pre_request - 请求进入时，在路由和认证之前
    2. post_response - 响应返回时，在发送给客户端之前
    3. on_error - 发生错误时
    """

    # 插件名称（唯一标识）
    name: str = "base_plugin"

    # 插件版本
    version: str = "1.0.0"

    # 插件描述
    description: str = ""

    # 优先级（越小越先执行 pre_request，越后执行 post_response）
    priority: int = 100

    # 是否启用
    enabled: bool = True

    def __init__(self, name: str = "", priority: int = 100, enabled: bool = True):
        if name:
            self.name = name
        self.priority = priority
        self.enabled = enabled
        self._stats = {
            "pre_request_calls": 0,
            "post_response_calls": 0,
            "on_error_calls": 0,
        }

    async def pre_request(self, ctx: PluginContext) -> Optional[PluginContext]:
        """请求前钩子

        在请求被路由和处理之前调用。
        可以修改 ctx 中的请求信息。

        Args:
            ctx: 插件上下文

        Returns:
            - 返回 None: 继续正常处理
            - 返回 ctx: 修改后的上下文，继续处理
            - 抛出异常: 终止请求，进入 on_error 流程
        """
        self._stats["pre_request_calls"] += 1
        return ctx

    async def post_response(self, ctx: PluginContext) -> PluginContext:
        """响应后钩子

        在响应发送给客户端之前调用。
        可以修改 ctx 中的响应信息。

        Args:
            ctx: 插件上下文（包含响应信息）

        Returns:
            修改后的上下文
        """
        self._stats["post_response_calls"] += 1
        return ctx

    async def on_error(self, ctx: PluginContext) -> PluginContext:
        """错误钩子

        请求处理过程中发生错误时调用。

        Args:
            ctx: 插件上下文（包含错误信息）

        Returns:
            修改后的上下文
        """
        self._stats["on_error_calls"] += 1
        return ctx

    def get_stats(self) -> Dict[str, Any]:
        """获取插件统计"""
        return {
            "name": self.name,
            "version": self.version,
            "enabled": self.enabled,
            "priority": self.priority,
            **self._stats,
        }

    def reset_stats(self):
        """重置统计"""
        for key in self._stats:
            self._stats[key] = 0

    def __repr__(self) -> str:
        return f"<Plugin {self.name} v{self.version} (priority={self.priority}, enabled={self.enabled})>"
