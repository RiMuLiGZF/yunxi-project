from __future__ import annotations

"""Dynamic Config 热更新配置中心.

支持 Skill 配置的实时热更新、配置版本管理、变更通知，无需重启即可生效。
"""

import asyncio
import json
import os
import time
from typing import Any, Awaitable, Callable

import structlog
import yaml

logger = structlog.get_logger()

# 【第三轮优化】延迟导入 watchdog，避免强依赖导致整个模块无法加载
_watchdog_available = False
try:
    from watchdog.events import FileSystemEventHandler
    from watchdog.observers import Observer
    _watchdog_available = True
except ImportError:
    FileSystemEventHandler = None  # type: ignore[misc,assignment]
    Observer = None  # type: ignore[misc,assignment]

ConfigChangeHandler = Callable[[str, Any, Any], Awaitable[None]]


class ConfigCenter:
    """配置中心.

    支持文件热加载、内存缓存、变更通知、多来源合并。
    """

    def __init__(self, config_dir: str | None = None) -> None:
        self._config_dir = config_dir or os.path.expanduser("~/.yunxi/config")
        os.makedirs(self._config_dir, exist_ok=True)
        self._configs: dict[str, dict[str, Any]] = {}
        self._handlers: dict[str, list[ConfigChangeHandler]] = {}
        self._watchers: dict[str, Observer] = {}
        self._lock = asyncio.Lock()

    def _file_path(self, config_name: str) -> str:
        return os.path.join(self._config_dir, f"{config_name}.yaml")

    def load(self, config_name: str) -> dict[str, Any]:
        """加载配置.

        先读内存缓存，未命中则读文件。
        """
        if config_name in self._configs:
            return dict(self._configs[config_name])

        path = self._file_path(config_name)
        if not os.path.exists(path):
            self._configs[config_name] = {}
            return {}

        try:
            with open(path, encoding="utf-8") as f:
                data = yaml.safe_load(f) or {}
            self._configs[config_name] = data
            return dict(data)
        except Exception as e:
            logger.warning("config_load_failed", config_name=config_name, error=str(e))
            return {}

    def save(self, config_name: str, data: dict[str, Any], notify: bool = False) -> None:
        """保存配置到文件.

        Args:
            config_name: 配置名.
            data: 配置数据.
            notify: 是否触发变更通知. 默认 False，避免初始化时误通知.
        """
        path = self._file_path(config_name)
        old_data = dict(self._configs.get(config_name, {}))
        self._configs[config_name] = dict(data)

        try:
            with open(path, "w", encoding="utf-8") as f:
                yaml.safe_dump(data, f, allow_unicode=True)
        except Exception as e:
            logger.error("config_save_failed", config_name=config_name, error=str(e))
            return

        # 异步通知变更
        if notify:
            changes = self._diff(old_data, data)
            if changes:
                try:
                    loop = asyncio.get_running_loop()
                    loop.create_task(self._notify(config_name, changes))
                except RuntimeError:
                    pass  # 无事件循环时跳过异步通知

    def get(self, config_name: str, key: str, default: Any = None) -> Any:
        """获取配置项."""
        config = self.load(config_name)
        return config.get(key, default)

    def set(
        self, config_name: str, key: str, value: Any, notify: bool = True
    ) -> None:
        """设置配置项."""
        config = self.load(config_name)
        old_value = config.get(key)
        if old_value == value:
            return

        config[key] = value
        self._configs[config_name] = config

        path = self._file_path(config_name)
        try:
            with open(path, "w", encoding="utf-8") as f:
                yaml.safe_dump(config, f, allow_unicode=True)
        except Exception as e:
            logger.error("config_set_failed", config_name=config_name, key=key, error=str(e))
            return

        if notify:
            try:
                loop = asyncio.get_running_loop()
                loop.create_task(
                    self._notify(config_name, {key: (old_value, value)})
                )
            except RuntimeError:
                pass  # 无事件循环时跳过异步通知

    async def subscribe(
        self, config_name: str, handler: ConfigChangeHandler
    ) -> None:
        """订阅配置变更."""
        async with self._lock:
            self._handlers.setdefault(config_name, []).append(handler)

    async def unsubscribe(
        self, config_name: str, handler: ConfigChangeHandler
    ) -> None:
        """取消订阅."""
        async with self._lock:
            handlers = self._handlers.get(config_name, [])
            if handler in handlers:
                handlers.remove(handler)

    async def _notify(
        self, config_name: str, changes: dict[str, tuple[Any, Any]]
    ) -> None:
        """通知变更."""
        handlers = self._handlers.get(config_name, [])
        for key, (old_val, new_val) in changes.items():
            for handler in handlers:
                try:
                    await handler(key, old_val, new_val)
                except Exception as e:
                    logger.error(
                        "config_handler_error",
                        config_name=config_name,
                        key=key,
                        error=str(e),
                    )

    def start_watch(self, config_name: str) -> None:
        """启动文件监控，实现热加载."""
        # 【第三轮优化】watchdog 未安装时优雅降级
        if not _watchdog_available:
            logger.warning(
                "config_watch_disabled",
                reason="watchdog not installed",
                config_name=config_name,
            )
            return

        if config_name in self._watchers:
            return

        path = self._file_path(config_name)
        if not os.path.exists(path):
            return

        class _Handler(FileSystemEventHandler):
            def __init__(self, center: ConfigCenter, name: str) -> None:
                self._center = center
                self._name = name
                self._last_modified = 0.0

            def on_modified(self, event) -> None:  # type: ignore[override]
                if event.src_path != path:
                    return
                now = time.time()
                if now - self._last_modified < 1.0:
                    return
                self._last_modified = now
                try:
                    with open(path, encoding="utf-8") as f:
                        data = yaml.safe_load(f) or {}
                    old_data = self._center._configs.get(self._name, {})
                    self._center._configs[self._name] = data
                    changes = self._center._diff(old_data, data)
                    if changes:
                        try:
                            loop = asyncio.get_running_loop()
                            asyncio.run_coroutine_threadsafe(
                                self._center._notify(self._name, changes),
                                loop,
                            )
                        except RuntimeError:
                            pass
                        logger.info(
                            "config_hot_reloaded",
                            config_name=self._name,
                            changes=list(changes.keys()),
                        )
                except Exception as e:
                    logger.error(
                        "config_hot_reload_failed",
                        config_name=self._name,
                        error=str(e),
                    )

        observer = Observer()
        observer.schedule(_Handler(self, config_name), self._config_dir, recursive=False)
        observer.start()
        self._watchers[config_name] = observer
        logger.info("config_watch_started", config_name=config_name)

    def stop_watch(self, config_name: str) -> None:
        """停止文件监控."""
        observer = self._watchers.pop(config_name, None)
        if observer:
            observer.stop()
            observer.join()
            logger.info("config_watch_stopped", config_name=config_name)

    def stop_all_watches(self) -> None:
        """停止所有监控."""
        for name in list(self._watchers.keys()):
            self.stop_watch(name)

    @staticmethod
    def _diff(
        old: dict[str, Any], new: dict[str, Any]
    ) -> dict[str, tuple[Any, Any]]:
        """计算配置差异."""
        changes: dict[str, tuple[Any, Any]] = {}
        all_keys = set(old.keys()) | set(new.keys())
        for key in all_keys:
            old_val = old.get(key)
            new_val = new.get(key)
            if old_val != new_val:
                changes[key] = (old_val, new_val)
        return changes

    def list_configs(self) -> list[str]:
        """列出所有已加载配置."""
        return list(self._configs.keys())
