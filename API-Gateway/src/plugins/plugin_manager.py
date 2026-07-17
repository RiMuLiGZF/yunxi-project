"""
云汐 API 网关 - 插件管理器

负责插件的注册、启用、禁用、排序和执行。
"""
import asyncio
import logging
from typing import Dict, List, Optional, Any
from .plugin_base import BasePlugin, PluginContext


logger = logging.getLogger("yunxi-gateway.plugins")


class PluginManager:
    """插件管理器

    管理所有插件的生命周期和执行顺序。
    """

    def __init__(self):
        self._plugins: Dict[str, BasePlugin] = {}
        self._lock = asyncio.Lock()
        self._sorted_pre_plugins: List[BasePlugin] = []
        self._sorted_post_plugins: List[BasePlugin] = []
        self._dirty = True

    # ===================================================================
    # 插件注册与管理
    # ===================================================================

    async def register(self, plugin: BasePlugin) -> bool:
        """注册插件

        Args:
            plugin: 插件实例

        Returns:
            是否注册成功
        """
        async with self._lock:
            if plugin.name in self._plugins:
                logger.warning(f"Plugin '{plugin.name}' already registered, replacing")
            self._plugins[plugin.name] = plugin
            self._dirty = True
            logger.info(f"Plugin '{plugin.name}' registered (priority={plugin.priority})")
            return True

    async def unregister(self, name: str) -> bool:
        """注销插件

        Args:
            name: 插件名称

        Returns:
            是否注销成功
        """
        async with self._lock:
            if name in self._plugins:
                del self._plugins[name]
                self._dirty = True
                logger.info(f"Plugin '{name}' unregistered")
                return True
            return False

    async def enable(self, name: str) -> bool:
        """启用插件"""
        async with self._lock:
            plugin = self._plugins.get(name)
            if plugin and not plugin.enabled:
                plugin.enabled = True
                self._dirty = True
                logger.info(f"Plugin '{name}' enabled")
                return True
            return False

    async def disable(self, name: str) -> bool:
        """禁用插件"""
        async with self._lock:
            plugin = self._plugins.get(name)
            if plugin and plugin.enabled:
                plugin.enabled = False
                self._dirty = True
                logger.info(f"Plugin '{name}' disabled")
                return True
            return False

    def get_plugin(self, name: str) -> Optional[BasePlugin]:
        """获取插件实例"""
        return self._plugins.get(name)

    def has_plugin(self, name: str) -> bool:
        """检查插件是否存在"""
        return name in self._plugins

    # ===================================================================
    # 排序
    # ===================================================================

    def _ensure_sorted(self):
        """确保插件列表已排序"""
        if not self._dirty:
            return

        enabled_plugins = [p for p in self._plugins.values() if p.enabled]

        # pre_request 按 priority 升序（小的先执行）
        self._sorted_pre_plugins = sorted(enabled_plugins, key=lambda p: p.priority)

        # post_response 按 priority 降序（小的后执行，形成洋葱模型）
        self._sorted_post_plugins = sorted(enabled_plugins, key=lambda p: -p.priority)

        self._dirty = False

    # ===================================================================
    # 钩子执行
    # ===================================================================

    async def execute_pre_request(self, ctx: PluginContext) -> Optional[PluginContext]:
        """执行所有插件的 pre_request 钩子

        Args:
            ctx: 插件上下文

        Returns:
            处理后的上下文，或 None 表示请求被终止
        """
        self._ensure_sorted()

        current_ctx = ctx
        for plugin in self._sorted_pre_plugins:
            try:
                result = await plugin.pre_request(current_ctx)
                if result is None:
                    # 插件返回 None 表示终止请求
                    logger.debug(f"Plugin '{plugin.name}' terminated request in pre_request")
                    return None
                current_ctx = result
            except Exception as e:
                logger.error(f"Plugin '{plugin.name}' pre_request error: {e}", exc_info=True)
                # 插件错误不影响主流程，继续执行
                current_ctx.error = e
                current_ctx.error_message = str(e)

        return current_ctx

    async def execute_post_response(self, ctx: PluginContext) -> PluginContext:
        """执行所有插件的 post_response 钩子

        Args:
            ctx: 插件上下文

        Returns:
            处理后的上下文
        """
        self._ensure_sorted()

        current_ctx = ctx
        for plugin in self._sorted_post_plugins:
            try:
                result = await plugin.post_response(current_ctx)
                if result is not None:
                    current_ctx = result
            except Exception as e:
                logger.error(f"Plugin '{plugin.name}' post_response error: {e}", exc_info=True)
                # 插件错误不影响主流程

        return current_ctx

    async def execute_on_error(self, ctx: PluginContext) -> PluginContext:
        """执行所有插件的 on_error 钩子

        Args:
            ctx: 插件上下文（包含错误信息）

        Returns:
            处理后的上下文
        """
        self._ensure_sorted()

        current_ctx = ctx
        for plugin in self._sorted_pre_plugins:
            try:
                result = await plugin.on_error(current_ctx)
                if result is not None:
                    current_ctx = result
            except Exception as e:
                logger.error(f"Plugin '{plugin.name}' on_error error: {e}", exc_info=True)

        return current_ctx

    # ===================================================================
    # 统计与列表
    # ===================================================================

    def list_plugins(self) -> List[Dict[str, Any]]:
        """列出所有插件"""
        self._ensure_sorted()
        return [
            {
                "name": p.name,
                "version": p.version,
                "description": p.description,
                "priority": p.priority,
                "enabled": p.enabled,
            }
            for p in self._sorted_pre_plugins
        ]

    def get_stats(self) -> Dict[str, Any]:
        """获取所有插件的统计"""
        stats = {}
        for name, plugin in self._plugins.items():
            stats[name] = plugin.get_stats()
        return {
            "total_plugins": len(self._plugins),
            "enabled_plugins": sum(1 for p in self._plugins.values() if p.enabled),
            "disabled_plugins": sum(1 for p in self._plugins.values() if not p.enabled),
            "plugins": stats,
        }

    def reset_all_stats(self):
        """重置所有插件的统计"""
        for plugin in self._plugins.values():
            plugin.reset_stats()
