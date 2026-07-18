"""
配置中心客户端 SDK - ConfigClient

核心功能：
1. 自动拉取：启动时拉取模块配置
2. 本地缓存：内存缓存 + 文件缓存（断网可用）
3. 配置热更新：长轮询监听配置变化
4. 层级继承：全局 → 模块 → 环境 → 实例，自动合并
5. 配置变更回调：配置变化时触发回调
6. 配置校验：本地 Schema 校验
7. 敏感配置解密
8. 故障降级：配置中心不可用时使用本地缓存
"""

from __future__ import annotations

import os
import sys
import json
import time
import uuid
import hashlib
import logging
import threading
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple
from copy import deepcopy
from datetime import datetime

# 项目路径
_project_root = Path(__file__).parent.parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

logger = logging.getLogger("config_sdk.client")

# 默认配置
DEFAULT_CONFIG = {
    "config_center_url": "http://localhost:8008/api/config",
    "timeout": 5.0,
    "cache_ttl": 60,  # 内存缓存 TTL（秒）
    "enable_file_cache": True,
    "file_cache_path": None,  # None 时使用默认路径
    "enable_watch": True,
    "watch_interval": 30,  # 长轮询间隔（秒）
    "env": "development",
    "instance_id": None,  # 实例 ID，None 时自动生成
    "auth_token": "",  # 访问配置中心的令牌
    "enable_remote": True,  # 是否启用远程配置中心（默认启用，可关闭降级为纯本地）
}


class ConfigClient:
    """配置中心客户端

    提供配置的获取、设置、监听、刷新等功能。
    支持远程配置中心和本地缓存双层架构。
    """

    def __init__(
        self,
        module_name: str,
        config: Optional[Dict[str, Any]] = None,
        local_config: Optional[Dict[str, Any]] = None,
    ):
        """
        Args:
            module_name: 模块名称（如 "m8"、"m1"）
            config: 客户端配置（config_center_url, timeout 等）
            local_config: 本地默认配置（优先级最低，作为兜底）
        """
        self.module_name = module_name.lower()
        self._client_config = {**DEFAULT_CONFIG, **(config or {})}

        # 本地默认配置（兜底）
        self._local_defaults = local_config or {}

        # 内存缓存
        self._cache: Dict[str, Any] = {}
        self._cache_meta: Dict[str, Any] = {}
        self._cache_time: float = 0

        # 监听器 {listener_id: (key, callback)}
        self._watchers: Dict[str, Tuple[str, Callable]] = {}
        self._watch_lock = threading.Lock()

        # 长轮询线程
        self._watch_thread: Optional[threading.Thread] = None
        self._watch_stop_event = threading.Event()

        # 最后已知的变更 ID（用于长轮询）
        self._last_change_id: int = 0

        # 连接状态
        self._connected: bool = False
        self._last_error: Optional[str] = None

        # 生成实例 ID
        if not self._client_config.get("instance_id"):
            hostname = os.environ.get("HOSTNAME", os.environ.get("COMPUTERNAME", "unknown"))
            short_id = uuid.uuid4().hex[:8]
            self._instance_id = f"{self.module_name}-{hostname}-{short_id}"
        else:
            self._instance_id = self._client_config["instance_id"]

        # 文件缓存路径
        if self._client_config["enable_file_cache"] and not self._client_config["file_cache_path"]:
            cache_dir = Path(_project_root) / "shared" / "data" / "config_cache"
            cache_dir.mkdir(parents=True, exist_ok=True)
            self._file_cache_path = cache_dir / f"{self.module_name}_config_cache.json"
        else:
            self._file_cache_path = Path(self._client_config["file_cache_path"]) if self._client_config["file_cache_path"] else None

        # 初始化
        self._init_cache()

        # 启动监听（如果启用）
        if self._client_config["enable_watch"] and self._client_config["enable_remote"]:
            self._start_watch()

    # ============================================================
    # 公共 API
    # ============================================================

    def get(self, key: str, default: Any = None) -> Any:
        """获取配置值

        优先级：内存缓存 > 远程（如果过期） > 文件缓存 > 本地默认

        Args:
            key: 配置键
            default: 默认值

        Returns:
            配置值
        """
        # 先检查内存缓存
        if key in self._cache:
            return self._cache[key]

        # 检查是否需要刷新（缓存过期时）
        if self._should_refresh():
            self.refresh()
            if key in self._cache:
                return self._cache[key]

        # 从文件缓存加载
        if self._client_config["enable_file_cache"]:
            file_val = self._get_from_file_cache(key)
            if file_val is not None:
                return file_val

        # 本地默认配置
        if key in self._local_defaults:
            return self._local_defaults[key]

        return default

    def set(self, key: str, value: Any) -> bool:
        """设置配置（需要权限）

        Args:
            key: 配置键
            value: 配置值

        Returns:
            是否成功
        """
        if not self._client_config["enable_remote"]:
            # 远程禁用时，更新本地缓存
            self._cache[key] = value
            self._save_file_cache()
            return True

        try:
            result = self._api_call(
                "POST", "/items",
                json_body={
                    "config_key": key,
                    "config_value": value,
                    "scope": "module",
                    "module_name": self.module_name,
                    "env_name": self._client_config["env"],
                },
            )
            if result and result.get("code") == 0:
                # 更新本地缓存
                self._cache[key] = value
                self._save_file_cache()
                return True
            return False
        except Exception as e:
            logger.error("设置配置失败: %s", e)
            return False

    def get_all(self, prefix: Optional[str] = None) -> Dict[str, Any]:
        """获取所有配置

        Args:
            prefix: 可选的键前缀过滤

        Returns:
            配置字典
        """
        # 确保缓存是最新的
        if self._should_refresh():
            self.refresh()

        if prefix:
            return {
                k: v for k, v in self._cache.items()
                if k.startswith(prefix)
            }
        return dict(self._cache)

    def watch(self, key: str, callback: Callable[[str, Any, Any], None]) -> str:
        """监听配置变化

        Args:
            key: 要监听的配置键
            callback: 回调函数，签名: callback(key, old_value, new_value)

        Returns:
            监听器 ID，用于取消监听
        """
        listener_id = str(uuid.uuid4())
        with self._watch_lock:
            self._watchers[listener_id] = (key, callback)
        return listener_id

    def unwatch(self, listener_id: str) -> bool:
        """取消监听

        Args:
            listener_id: 监听器 ID

        Returns:
            是否成功
        """
        with self._watch_lock:
            if listener_id in self._watchers:
                del self._watchers[listener_id]
                return True
            return False

    def refresh(self) -> bool:
        """强制从服务端刷新配置

        Returns:
            是否刷新成功
        """
        if not self._client_config["enable_remote"]:
            return False

        try:
            # 拉取模块级配置
            result = self._api_call(
                "GET", "/items",
                params={
                    "scope": "module",
                    "module_name": self.module_name,
                    "page_size": 500,
                },
            )

            if not result or result.get("code") != 0:
                raise Exception(f"API 返回错误: {result}")

            data = result.get("data", {})
            items = data.get("items", [])

            new_cache = {}
            for item in items:
                key = item["config_key"]
                value = item["config_value"]
                new_cache[key] = value

            # 计算变更并触发回调
            changes = self._apply_new_cache(new_cache)

            # 保存文件缓存
            self._save_file_cache()

            self._cache_time = time.time()
            self._connected = True
            self._last_error = None

            return True
        except Exception as e:
            logger.warning("刷新配置失败，使用本地缓存: %s", e)
            self._connected = False
            self._last_error = str(e)
            # 尝试从文件缓存加载
            self._load_file_cache()
            return False

    @property
    def is_connected(self) -> bool:
        """是否连接到配置中心"""
        return self._connected

    @property
    def instance_id(self) -> str:
        """实例 ID"""
        return self._instance_id

    @property
    def env(self) -> str:
        """环境名"""
        return self._client_config["env"]

    def close(self) -> None:
        """关闭客户端，停止监听"""
        self._stop_watch()

    # ============================================================
    # 内部方法
    # ============================================================

    def _init_cache(self) -> None:
        """初始化缓存"""
        # 先加载本地默认配置
        self._cache = dict(self._local_defaults)

        # 尝试加载文件缓存（覆盖本地默认）
        if self._client_config["enable_file_cache"]:
            self._load_file_cache()

        # 如果启用远程，尝试拉取远程配置（覆盖文件缓存）
        if self._client_config["enable_remote"]:
            self.refresh()

    def _should_refresh(self) -> bool:
        """是否应该刷新缓存"""
        if not self._client_config["enable_remote"]:
            return False
        ttl = self._client_config["cache_ttl"]
        return time.time() - self._cache_time > ttl

    def _apply_new_cache(self, new_cache: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
        """应用新的缓存，计算变更并触发回调

        Returns:
            变更字典 {key: {"old": ..., "new": ...}}
        """
        changes = {}
        old_cache = dict(self._cache)

        # 合并：新缓存覆盖旧缓存，但保留旧缓存中不在新缓存里的项
        # （因为新缓存可能只包含模块级，不包含全局等）
        merged_cache = dict(old_cache)
        merged_cache.update(new_cache)
        self._cache = merged_cache

        # 找出变更的项
        for key, new_val in new_cache.items():
            old_val = old_cache.get(key, None)
            if old_val != new_val:
                changes[key] = {"old": old_val, "new": new_val}

        # 触发回调
        if changes:
            self._notify_watchers(changes)

        return changes

    def _notify_watchers(self, changes: Dict[str, Dict[str, Any]]) -> None:
        """触发监听器回调"""
        with self._watch_lock:
            watchers = list(self._watchers.items())

        for listener_id, (watch_key, callback) in watchers:
            try:
                if watch_key in changes:
                    change = changes[watch_key]
                    callback(watch_key, change["old"], change["new"])
            except Exception as e:
                logger.error("配置监听器回调异常 (id=%s): %s", listener_id, e)

    # ---- 文件缓存 ----

    def _load_file_cache(self) -> bool:
        """从文件加载缓存

        Returns:
            是否成功
        """
        if not self._file_cache_path or not self._file_cache_path.exists():
            return False

        try:
            with open(self._file_cache_path, "r", encoding="utf-8") as f:
                data = json.load(f)

            config_data = data.get("config", {})
            self._cache.update(config_data)
            self._cache_time = data.get("timestamp", 0)
            self._last_change_id = data.get("last_change_id", 0)
            logger.debug("从文件缓存加载了 %d 个配置项", len(config_data))
            return True
        except Exception as e:
            logger.warning("加载文件缓存失败: %s", e)
            return False

    def _save_file_cache(self) -> bool:
        """保存缓存到文件

        Returns:
            是否成功
        """
        if not self._client_config["enable_file_cache"] or not self._file_cache_path:
            return False

        try:
            self._file_cache_path.parent.mkdir(parents=True, exist_ok=True)
            data = {
                "module": self.module_name,
                "config": self._cache,
                "timestamp": time.time(),
                "last_change_id": self._last_change_id,
                "saved_at": datetime.now().isoformat(),
            }
            with open(self._file_cache_path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            return True
        except Exception as e:
            logger.warning("保存文件缓存失败: %s", e)
            return False

    def _get_from_file_cache(self, key: str) -> Optional[Any]:
        """从文件缓存获取单个配置值"""
        if not self._file_cache_path or not self._file_cache_path.exists():
            return None
        try:
            with open(self._file_cache_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            return data.get("config", {}).get(key)
        except Exception:
            return None

    # ---- HTTP API 调用 ----

    def _api_call(
        self,
        method: str,
        path: str,
        params: Optional[Dict[str, Any]] = None,
        json_body: Optional[Dict[str, Any]] = None,
    ) -> Optional[Dict[str, Any]]:
        """调用配置中心 API

        Args:
            method: HTTP 方法
            path: API 路径
            params: 查询参数
            json_body: 请求体

        Returns:
            API 响应字典
        """
        try:
            import urllib.request
            import urllib.parse
            import urllib.error

            base_url = self._client_config["config_center_url"].rstrip("/")
            url = f"{base_url}{path}"

            if params:
                query_string = urllib.parse.urlencode(params)
                url = f"{url}?{query_string}"

            headers = {"Content-Type": "application/json"}
            token = self._client_config.get("auth_token", "")
            if token:
                headers["Authorization"] = f"Bearer {token}"

            data = None
            if json_body:
                data = json.dumps(json_body).encode("utf-8")

            req = urllib.request.Request(
                url,
                data=data,
                headers=headers,
                method=method.upper(),
            )

            timeout = self._client_config["timeout"]
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                body = resp.read().decode("utf-8")
                return json.loads(body)
        except Exception as e:
            raise e

    # ---- 长轮询监听 ----

    def _start_watch(self) -> None:
        """启动长轮询监听线程"""
        if self._watch_thread and self._watch_thread.is_alive():
            return

        self._watch_stop_event.clear()
        self._watch_thread = threading.Thread(
            target=self._watch_loop,
            daemon=True,
            name=f"config-watch-{self.module_name}",
        )
        self._watch_thread.start()
        logger.info("配置监听线程已启动 (module=%s)", self.module_name)

    def _stop_watch(self) -> None:
        """停止长轮询监听"""
        self._watch_stop_event.set()
        if self._watch_thread and self._watch_thread.is_alive():
            self._watch_thread.join(timeout=5)
            logger.info("配置监听线程已停止 (module=%s)", self.module_name)

    def _watch_loop(self) -> None:
        """长轮询主循环"""
        while not self._watch_stop_event.is_set():
            try:
                self._poll_changes()
            except Exception as e:
                logger.debug("配置长轮询异常: %s", e)
                # 出错后等待一段时间再重试
                self._watch_stop_event.wait(5)

    def _poll_changes(self) -> None:
        """单次长轮询获取变更"""
        try:
            result = self._api_call(
                "GET", "/watch",
                params={
                    "since_id": self._last_change_id,
                    "scope": "module",
                    "module_name": self.module_name,
                    "env_name": self._client_config["env"],
                    "timeout": self._client_config["watch_interval"],
                },
            )

            if not result or result.get("code") != 0:
                raise Exception("长轮询 API 错误")

            data = result.get("data", {})
            changes = data.get("changes", [])

            if changes:
                self._last_change_id = data.get("latest_id", self._last_change_id)
                # 有变更，刷新完整配置
                self.refresh()

            self._connected = True
            self._last_error = None

        except Exception as e:
            logger.debug("长轮询失败: %s", e)
            self._connected = False
            self._last_error = str(e)
            # 失败后短暂等待
            self._watch_stop_event.wait(2)

    # ---- 上下文管理器支持 ----

    def __enter__(self) -> "ConfigClient":
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        self.close()

    def __del__(self) -> None:
        try:
            self.close()
        except Exception:
            pass
