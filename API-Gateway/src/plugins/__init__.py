"""
云汐 API 网关 - 插件系统

插件框架：
- 定义插件接口（pre_request / post_response / on_error）
- 插件管理器（注册、启用、禁用、排序）

内置插件：
- 日志增强插件（详细请求/响应日志）
- 指标采集插件（Prometheus 格式指标）
- 请求 ID 插件（生成和传递 request_id）
- CORS 插件（跨域处理）
- 安全头插件（安全响应头）
"""

from .plugin_base import BasePlugin, PluginContext
from .plugin_manager import PluginManager
from .builtin_plugins import (
    LoggingPlugin,
    MetricsPlugin,
    RequestIdPlugin,
    CorsPlugin,
    SecurityHeadersPlugin,
)

__all__ = [
    "BasePlugin",
    "PluginContext",
    "PluginManager",
    "LoggingPlugin",
    "MetricsPlugin",
    "RequestIdPlugin",
    "CorsPlugin",
    "SecurityHeadersPlugin",
]
