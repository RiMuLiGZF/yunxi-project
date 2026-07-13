"""
云汐内核 V5 - Agent 插件热加载系统

⚠️ [V10.0-R02 DEPRECATED] 本模块属于模块2（Skill集群）职责范围，
将在模块2就绪后迁移。当前保留作为向后兼容的临时实现。

M1应通过 SkillsInterface 调用模块2的插件加载能力，
不直接操作插件文件系统。

灵感来源：VS Code Extension Host / WordPress Plugin System

支持运行时从目录动态加载、卸载、重载 Agent 插件，
无需重启整个内核服务。

核心能力：
- 扫描插件目录，自动发现 Agent 类
- 文件变化监听，自动重载
- 安全隔离：加载失败不影响已有 Agent
- 依赖注入：向插件暴露 registry、bus、config 等上下文
"""

from __future__ import annotations

import importlib.util
import inspect
import sys
import time
from pathlib import Path
from typing import Any

import structlog

from interfaces import IAgentPlugin

logger = structlog.get_logger(__name__)


class PluginLoadError(Exception):
    """插件加载异常"""
    pass


class PluginContext:
    """插件上下文

    向插件暴露的内核能力注入对象。
    """

    def __init__(
        self,
        registry: Any = None,
        message_bus: Any = None,
        config: Any = None,
        event_store: Any = None,
    ) -> None:
        self.registry = registry
        self.message_bus = message_bus
        self.config = config
        self.event_store = event_store


class PluginLoader:
    """Agent 插件加载器

    从文件系统动态加载实现了 IAgentPlugin 接口的 Python 模块。
    """

    def __init__(
        self,
        plugin_dir: str = "./plugins",
        watch_interval: float = 10.0,
        auto_reload: bool = True,
    ) -> None:
        self.plugin_dir = Path(plugin_dir)
        self.watch_interval = watch_interval
        self.auto_reload = auto_reload
        self._plugins: dict[str, Any] = {}  # file_path -> module
        self._agent_classes: dict[str, type] = {}  # agent_id -> class
        self._instances: dict[str, IAgentPlugin] = {}  # agent_id -> instance
        self._last_scan: float = 0.0
        self._last_mtimes: dict[str, float] = {}
        self._context: PluginContext | None = None
        self._logger = logger.bind(service="plugin_loader")

    def set_context(self, context: PluginContext) -> None:
        """设置插件上下文"""
        self._context = context

    # ── 扫描与加载 ──────────────────────────────────────

    def scan(self) -> list[Path]:
        """扫描插件目录，返回所有 .py 文件路径"""
        if not self.plugin_dir.exists():
            self.plugin_dir.mkdir(parents=True, exist_ok=True)
            return []

        files = [
            f for f in self.plugin_dir.iterdir()
            if f.is_file() and f.suffix == ".py" and not f.name.startswith("_")
        ]
        return sorted(files)

    def load_file(self, file_path: Path) -> list[type]:
        """加载单个插件文件

        Returns:
            文件中发现的 IAgentPlugin 子类列表
        """
        module_name = f"yunxi_plugin_{file_path.stem}"

        try:
            spec = importlib.util.spec_from_file_location(module_name, file_path)
            if spec is None or spec.loader is None:
                raise PluginLoadError(f"无法创建模块规范: {file_path}")

            module = importlib.util.module_from_spec(spec)
            sys.modules[module_name] = module
            spec.loader.exec_module(module)

            # 查找 IAgentPlugin 子类
            agent_classes = []
            for name, obj in inspect.getmembers(module, inspect.isclass):
                if issubclass(obj, IAgentPlugin) and obj is not IAgentPlugin:
                    agent_classes.append(obj)

            self._plugins[str(file_path)] = module
            self._last_mtimes[str(file_path)] = file_path.stat().st_mtime

            self._logger.info(
                "plugin_loaded",
                file=file_path.name,
                agents=[cls.__name__ for cls in agent_classes],
            )
            return agent_classes

        except Exception as exc:
            self._logger.error("plugin_load_failed", file=str(file_path), error=str(exc))
            raise PluginLoadError(f"加载插件失败 {file_path}: {exc}") from exc

    async def load_all(self, registry: Any | None = None) -> list[IAgentPlugin]:
        """加载所有插件并注册到 AgentRegistry

        Returns:
            成功创建的 Agent 实例列表
        """
        files = self.scan()
        instances: list[IAgentPlugin] = []

        for file_path in files:
            try:
                agent_classes = self.load_file(file_path)
                for agent_class in agent_classes:
                    instance = agent_class()
                    agent_id = getattr(instance, "agent_id", "")
                    if not agent_id:
                        self._logger.warning("plugin_no_agent_id", agent_class=agent_class.__name__)
                        continue

                    self._agent_classes[agent_id] = agent_class
                    self._instances[agent_id] = instance

                    if registry is not None:
                        if hasattr(registry, "register_sync"):
                            registry.register_sync(instance)
                        elif hasattr(registry, "register"):
                            await registry.register(instance)

                    instances.append(instance)
                    self._logger.info("agent_loaded_from_plugin", agent_id=agent_id, file=file_path.name)
            except PluginLoadError:
                # 单个插件失败不影响其他
                continue

        return instances

    # ── 热重载 ──────────────────────────────────────────

    async def check_reload(self, registry: Any | None = None) -> list[IAgentPlugin]:
        """检查文件变化并自动重载

        Returns:
            新加载或重载的 Agent 实例列表
        """
        if not self.auto_reload:
            return []

        now = time.time()
        if now - self._last_scan < self.watch_interval:
            return []
        self._last_scan = now

        reloaded: list[IAgentPlugin] = []
        files = self.scan()
        current_paths = {str(f) for f in files}

        # 检测新增或修改
        for file_path in files:
            path_str = str(file_path)
            mtime = file_path.stat().st_mtime

            if path_str not in self._last_mtimes:
                # 新增插件
                self._logger.info("plugin_discovered", file=file_path.name)
                try:
                    instances = await self._reload_single(file_path, registry)
                    reloaded.extend(instances)
                except PluginLoadError:
                    pass
            elif mtime > self._last_mtimes[path_str]:
                # 修改过的插件
                self._logger.info("plugin_modified", file=file_path.name)
                try:
                    instances = await self._reload_single(file_path, registry)
                    reloaded.extend(instances)
                except PluginLoadError:
                    pass

        # 检测删除
        removed = set(self._last_mtimes.keys()) - current_paths
        for path_str in removed:
            self._logger.info("plugin_removed", file=Path(path_str).name)
            self._last_mtimes.pop(path_str, None)
            self._plugins.pop(path_str, None)

        return reloaded

    async def _reload_single(self, file_path: Path, registry: Any | None = None) -> list[IAgentPlugin]:
        """重载单个插件文件"""
        # 先卸载该文件中的旧 Agent
        path_str = str(file_path)
        old_agents = [
            aid for aid, inst in self._instances.items()
            if getattr(inst, "__plugin_file__", "") == path_str
        ]
        for aid in old_agents:
            self._instances.pop(aid, None)
            self._agent_classes.pop(aid, None)
            if registry is not None and hasattr(registry, "unregister"):
                await registry.unregister(aid)

        # 重新加载
        agent_classes = self.load_file(file_path)
        instances = []
        for agent_class in agent_classes:
            instance = agent_class()
            agent_id = getattr(instance, "agent_id", "")
            if not agent_id:
                continue
            # 标记来源文件
            object.__setattr__(instance, "__plugin_file__", path_str)
            self._agent_classes[agent_id] = agent_class
            self._instances[agent_id] = instance

            if registry is not None:
                if hasattr(registry, "register_sync"):
                    registry.register_sync(instance)
                elif hasattr(registry, "register"):
                    await registry.register(instance)

            instances.append(instance)

        return instances

    # ── 查询 ────────────────────────────────────────────

    def list_loaded(self) -> list[str]:
        """列出已加载的 Agent ID"""
        return list(self._instances.keys())

    def get_instance(self, agent_id: str) -> IAgentPlugin | None:
        """获取已加载的 Agent 实例"""
        return self._instances.get(agent_id)

    def get_class(self, agent_id: str) -> type | None:
        """获取 Agent 类"""
        return self._agent_classes.get(agent_id)

    def stats(self) -> dict[str, Any]:
        """获取加载器统计"""
        return {
            "plugin_dir": str(self.plugin_dir),
            "loaded_files": len(self._plugins),
            "loaded_agents": len(self._instances),
            "agent_ids": list(self._instances.keys()),
            "auto_reload": self.auto_reload,
        }
