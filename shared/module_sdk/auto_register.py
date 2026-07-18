"""
云汐系统模块间通信 SDK - 模块自动注册启动器
==============================================

模块启动时自动注册到注册中心，自动发送心跳，优雅关闭时自动注销。

可作为 FastAPI startup/shutdown 事件钩子使用。

使用方式：
    from shared.module_sdk.auto_register import ModuleAutoRegister

    # 基本用法
    registrar = ModuleAutoRegister(
        module_name="m1",
        instance_id="m1-node-1",
        address="127.0.0.1",
        port=8001,
    )
    registrar.start()
    # ... 业务逻辑 ...
    registrar.stop()

    # FastAPI 集成
    from fastapi import FastAPI
    app = FastAPI()
    setup_module_registration(app, module_name="m1", port=8001)
"""

from __future__ import annotations

import sys
import os
import time
import atexit
import signal
import threading
import uuid
import logging
from pathlib import Path
from typing import Any, Callable, Dict, Optional

# 确保可以导入 shared 包
_shared_parent = Path(__file__).resolve().parent.parent.parent
if str(_shared_parent) not in sys.path:
    sys.path.insert(0, str(_shared_parent))

from .registry import get_registry_client, ServiceRegistryClient

logger = logging.getLogger(__name__)


# ============================================================
# 模块自动注册器
# ============================================================

class ModuleAutoRegister:
    """
    模块自动注册器。

    功能：
    - 启动时自动注册到注册中心
    - 后台线程定期发送心跳
    - 进程退出时自动注销
    - 支持注册成功/失败回调
    """

    def __init__(
        self,
        module_name: str,
        instance_id: str = "",
        address: str = "127.0.0.1",
        port: int = 0,
        metadata: Optional[Dict[str, Any]] = None,
        version: str = "1.0.0",
        weight: int = 1,
        heartbeat_interval: float = 10.0,
        registry: Optional[ServiceRegistryClient] = None,
        on_register_success: Optional[Callable[[], None]] = None,
        on_register_failed: Optional[Callable[[Exception], None]] = None,
        on_deregister: Optional[Callable[[], None]] = None,
    ):
        """
        初始化自动注册器。

        Args:
            module_name: 模块名（如 "m1", "m8"）
            instance_id: 实例 ID，为空时自动生成
            address: 服务地址
            port: 服务端口
            metadata: 元数据
            version: 版本号
            weight: 权重
            heartbeat_interval: 心跳间隔（秒）
            registry: 注册中心客户端，None 时使用全局单例
            on_register_success: 注册成功回调
            on_register_failed: 注册失败回调
            on_deregister: 注销回调
        """
        self.module_name = module_name.lower()
        self.instance_id = instance_id or f"{self.module_name}-{uuid.uuid4().hex[:8]}"
        self.address = address
        self.port = port
        self.metadata = metadata or {}
        self.version = version
        self.weight = weight
        self.heartbeat_interval = heartbeat_interval

        self._registry = registry
        self._heartbeat_thread: Optional[threading.Thread] = None
        self._heartbeat_stop = threading.Event()
        self._registered = False
        self._started = False

        # 回调
        self._on_register_success = on_register_success
        self._on_register_failed = on_register_failed
        self._on_deregister = on_deregister

        # 注册 atexit 钩子
        self._atexit_registered = False

    # ------------------------------------------------------------------
    #  启动/停止
    # ------------------------------------------------------------------

    def start(self) -> bool:
        """
        启动自动注册。

        Returns:
            True 表示注册成功（或重试中）
        """
        if self._started:
            return True

        # 注册
        success = self._do_register()

        if success:
            # 启动心跳线程
            self._start_heartbeat()
            # 注册 atexit
            self._register_atexit()
            self._started = True

        return success

    def stop(self) -> None:
        """停止自动注册（注销 + 停止心跳）"""
        if not self._started:
            return

        self._stop_heartbeat()
        self._do_deregister()
        self._started = False

    # ------------------------------------------------------------------
    #  注册/注销
    # ------------------------------------------------------------------

    def _do_register(self) -> bool:
        """执行注册"""
        try:
            registry = self._get_registry()
            success = registry.register(
                service_name=self.module_name,
                instance_id=self.instance_id,
                address=self.address,
                port=self.port,
                metadata=self.metadata,
                version=self.version,
                weight=self.weight,
            )

            if success:
                self._registered = True
                logger.info(
                    "Module registered: %s/%s (%s:%d)",
                    self.module_name, self.instance_id,
                    self.address, self.port,
                )
                if self._on_register_success:
                    try:
                        self._on_register_success()
                    except Exception as e:
                        logger.error("on_register_success callback error: %s", e)
                return True
            else:
                logger.warning("Module registration failed: %s/%s",
                               self.module_name, self.instance_id)
                if self._on_register_failed:
                    try:
                        self._on_register_failed(Exception("Registration returned False"))
                    except Exception as e:
                        logger.error("on_register_failed callback error: %s", e)
                return False

        except Exception as e:
            logger.error("Module registration error: %s", e)
            if self._on_register_failed:
                try:
                    self._on_register_failed(e)
                except Exception as ce:
                    logger.error("on_register_failed callback error: %s", ce)
            return False

    def _do_deregister(self) -> bool:
        """执行注销"""
        if not self._registered:
            return False

        try:
            registry = self._get_registry()
            success = registry.deregister(self.module_name, self.instance_id)
            self._registered = False

            if success:
                logger.info("Module deregistered: %s/%s",
                            self.module_name, self.instance_id)
            else:
                logger.warning("Module deregistration returned false: %s/%s",
                               self.module_name, self.instance_id)

            if self._on_deregister:
                try:
                    self._on_deregister()
                except Exception as e:
                    logger.error("on_deregister callback error: %s", e)

            return success

        except Exception as e:
            logger.error("Module deregistration error: %s", e)
            return False

    # ------------------------------------------------------------------
    #  心跳
    # ------------------------------------------------------------------

    def _start_heartbeat(self) -> None:
        """启动心跳线程"""
        if self.heartbeat_interval <= 0:
            return

        if self._heartbeat_thread and self._heartbeat_thread.is_alive():
            return

        self._heartbeat_stop.clear()
        self._heartbeat_thread = threading.Thread(
            target=self._heartbeat_loop,
            name=f"Heartbeat-{self.module_name}",
            daemon=True,
        )
        self._heartbeat_thread.start()
        logger.debug("Heartbeat thread started for %s (interval=%.1fs)",
                     self.module_name, self.heartbeat_interval)

    def _stop_heartbeat(self) -> None:
        """停止心跳线程"""
        self._heartbeat_stop.set()
        if self._heartbeat_thread:
            self._heartbeat_thread.join(timeout=3)
            self._heartbeat_thread = None

    def _heartbeat_loop(self) -> None:
        """心跳循环"""
        while not self._heartbeat_stop.is_set():
            try:
                if self._registered:
                    registry = self._get_registry()
                    ok = registry.heartbeat(self.module_name, self.instance_id)
                    if not ok:
                        logger.debug("Heartbeat failed for %s, attempting re-register",
                                     self.module_name)
                        # 心跳失败，尝试重新注册
                        self._do_register()
            except Exception as e:
                logger.warning("Heartbeat error for %s: %s", self.module_name, e)

            self._heartbeat_stop.wait(self.heartbeat_interval)

    # ------------------------------------------------------------------
    #  atexit
    # ------------------------------------------------------------------

    def _register_atexit(self) -> None:
        """注册进程退出钩子"""
        if self._atexit_registered:
            return

        def _on_exit():
            try:
                self.stop()
            except Exception:
                pass

        atexit.register(_on_exit)
        self._atexit_registered = True

        # 也注册信号处理（仅 Unix）
        try:
            def _signal_handler(signum, frame):
                self.stop()
                # 重新抛出默认信号行为
                signal.signal(signum, signal.SIG_DFL)
                os.kill(os.getpid(), signum)

            signal.signal(signal.SIGTERM, _signal_handler)
            signal.signal(signal.SIGINT, _signal_handler)
        except Exception:
            # Windows 可能不支持某些信号
            pass

    # ------------------------------------------------------------------
    #  工具方法
    # ------------------------------------------------------------------

    def _get_registry(self) -> ServiceRegistryClient:
        """获取注册中心客户端"""
        if self._registry is None:
            self._registry = get_registry_client()
        return self._registry

    @property
    def is_registered(self) -> bool:
        """是否已注册"""
        return self._registered

    @property
    def is_running(self) -> bool:
        """是否运行中"""
        return self._started


# ============================================================
# FastAPI 集成
# ============================================================

def setup_module_registration(
    app: Any,
    module_name: str,
    port: int,
    instance_id: str = "",
    address: str = "127.0.0.1",
    metadata: Optional[Dict[str, Any]] = None,
    version: str = "1.0.0",
    heartbeat_interval: float = 10.0,
    registry: Optional[ServiceRegistryClient] = None,
) -> ModuleAutoRegister:
    """
    为 FastAPI 应用设置自动注册。

    自动注册 startup/shutdown 事件钩子。

    Args:
        app: FastAPI 应用实例
        module_name: 模块名
        port: 服务端口
        instance_id: 实例 ID
        address: 服务地址
        metadata: 元数据
        version: 版本号
        heartbeat_interval: 心跳间隔
        registry: 注册中心客户端

    Returns:
        ModuleAutoRegister 实例
    """
    registrar = ModuleAutoRegister(
        module_name=module_name,
        instance_id=instance_id,
        address=address,
        port=port,
        metadata=metadata,
        version=version,
        heartbeat_interval=heartbeat_interval,
        registry=registry,
    )

    # 注册启动事件
    @app.on_event("startup")
    async def _on_startup():
        registrar.start()

    # 注册关闭事件
    @app.on_event("shutdown")
    async def _on_shutdown():
        registrar.stop()

    return registrar


def setup_module_registration_lifespan(
    module_name: str,
    port: int,
    instance_id: str = "",
    address: str = "127.0.0.1",
    metadata: Optional[Dict[str, Any]] = None,
    version: str = "1.0.0",
    heartbeat_interval: float = 10.0,
    registry: Optional[ServiceRegistryClient] = None,
) -> Callable:
    """
    创建 lifespan 上下文管理器（用于 FastAPI 新的 lifespan 方式）。

    使用方式：
        from contextlib import asynccontextmanager
        from fastapi import FastAPI

        lifespan = setup_module_registration_lifespan("m1", 8001)
        app = FastAPI(lifespan=lifespan)

    Args:
        module_name: 模块名
        port: 服务端口
        instance_id: 实例 ID
        address: 服务地址
        metadata: 元数据
        version: 版本号
        heartbeat_interval: 心跳间隔
        registry: 注册中心客户端

    Returns:
        lifespan 函数
    """
    from contextlib import asynccontextmanager

    registrar = ModuleAutoRegister(
        module_name=module_name,
        instance_id=instance_id,
        address=address,
        port=port,
        metadata=metadata,
        version=version,
        heartbeat_interval=heartbeat_interval,
        registry=registry,
    )

    @asynccontextmanager
    async def lifespan(app):
        # 启动
        registrar.start()
        yield
        # 关闭
        registrar.stop()

    return lifespan


# ============================================================
# 便捷函数
# ============================================================

def auto_register_module(
    module_name: str,
    port: int,
    address: str = "127.0.0.1",
    instance_id: str = "",
    metadata: Optional[Dict[str, Any]] = None,
    version: str = "1.0.0",
    heartbeat_interval: float = 10.0,
) -> ModuleAutoRegister:
    """
    便捷函数：自动注册模块并启动心跳。

    Args:
        module_name: 模块名
        port: 服务端口
        address: 服务地址
        instance_id: 实例 ID
        metadata: 元数据
        version: 版本号
        heartbeat_interval: 心跳间隔

    Returns:
        ModuleAutoRegister 实例
    """
    registrar = ModuleAutoRegister(
        module_name=module_name,
        instance_id=instance_id,
        address=address,
        port=port,
        metadata=metadata,
        version=version,
        heartbeat_interval=heartbeat_interval,
    )
    registrar.start()
    return registrar


# ============================================================
# 模块导出
# ============================================================

__all__ = [
    "ModuleAutoRegister",
    "setup_module_registration",
    "setup_module_registration_lifespan",
    "auto_register_module",
]
