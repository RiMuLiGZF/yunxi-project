"""
模块自注册客户端 (CQ-001)
==========================

提供给各模块启动时调用，用于向注册中心注册自己、发送心跳、上报状态。

使用方式：
    from shared.business.module_self_register import ModuleSelfRegister

    register = ModuleSelfRegister(
        module_id="m8",
        module_name="控制塔",
        port=8008,
    )
    register.register()     # 启动时注册
    register.start_heartbeat()  # 启动心跳

    # 程序退出时
    register.unregister()

也可以使用便捷函数：
    from shared.business.module_self_register import auto_register

    auto_register(module_id="m8", port=8008)
"""

from __future__ import annotations

import os
import sys
import time
import threading
from pathlib import Path
from typing import Any, Dict, Optional

# 确保可以导入 shared 包
_shared_parent = Path(__file__).resolve().parent.parent.parent
if str(_shared_parent) not in sys.path:
    sys.path.insert(0, str(_shared_parent))

from shared.core.module_registry import (
    ModuleRegistry,
    ModuleInfo,
    ModuleStatus,
    HealthStatus,
    get_module_registry,
)

import logging
logger = logging.getLogger(__name__)


class ModuleSelfRegister:
    """
    模块自注册客户端。

    各模块启动时创建实例，调用 register() 注册自己，
    然后通过 start_heartbeat() 定期发送心跳。

    支持两种注册模式：
    1. 进程内模式（默认）：直接调用 ModuleRegistry 的方法
    2. 远程模式：通过 HTTP 调用注册中心的 API（TODO，暂未实现）
    """

    def __init__(
        self,
        module_id: str,
        module_name: str = "",
        port: int = 0,
        host: str = "127.0.0.1",
        category: str = "core",
        description: str = "",
        version: str = "v1.0.0",
        registry: Optional[ModuleRegistry] = None,
        heartbeat_interval: Optional[int] = None,
    ):
        """
        初始化自注册客户端。

        Args:
            module_id: 模块唯一标识
            module_name: 模块显示名称
            port: 服务端口
            host: 服务地址
            category: 模块分类
            description: 模块描述
            version: 模块版本
            registry: 注册表实例，None 时使用全局注册表
            heartbeat_interval: 心跳间隔（秒），None 时使用全局配置
        """
        self.module_id = module_id.lower()
        self.module_name = module_name or module_id
        self.port = port
        self.host = host
        self.category = category
        self.description = description
        self.version = version

        self._registry = registry or get_module_registry()
        self._heartbeat_thread: Optional[threading.Thread] = None
        self._heartbeat_stop = threading.Event()
        self._registered = False

        # 心跳间隔
        if heartbeat_interval is not None:
            self._heartbeat_interval = heartbeat_interval
        else:
            self._heartbeat_interval = self._registry.global_config.heartbeat_interval

    # ------------------------------------------------------------------
    #  注册/注销
    # ------------------------------------------------------------------

    def register(self) -> bool:
        """
        注册模块到注册中心。

        Returns:
            True 表示注册成功
        """
        try:
            # 检查是否已注册
            existing = self._registry.get_module(self.module_id)
            if existing:
                # 更新状态
                existing.status = ModuleStatus.RUNNING
                existing.health = HealthStatus.HEALTHY
                existing.last_heartbeat = time.time()
                if self.port and existing.port != self.port:
                    existing.port = self.port
                self._registered = True
                logger.info("模块 %s 已重新注册到注册中心", self.module_id)
                return True

            # 新注册
            module_info = ModuleInfo(
                id=self.module_id,
                name=self.module_name,
                port=self.port,
                host=self.host,
                category=self.category,
                description=self.description,
                version=self.version,
                status=ModuleStatus.RUNNING,
                health=HealthStatus.HEALTHY,
                last_heartbeat=time.time(),
                enabled=True,
                priority=100,
            )
            self._registry.register_module(module_info)
            self._registered = True
            logger.info("模块 %s (%s) 已注册到注册中心，端口: %d",
                       self.module_id, self.module_name, self.port)
            return True

        except Exception as e:
            logger.error("模块 %s 注册失败: %s", self.module_id, e)
            return False

    def unregister(self) -> bool:
        """
        从注册中心注销模块。

        Returns:
            True 表示注销成功
        """
        try:
            self.stop_heartbeat()

            # 更新状态为已停止（而不是直接删除，保留记录）
            module = self._registry.get_module(self.module_id)
            if module:
                module.status = ModuleStatus.STOPPED
                module.health = HealthStatus.UNKNOWN
                module.pid = None

            self._registered = False
            logger.info("模块 %s 已从注册中心注销", self.module_id)
            return True

        except Exception as e:
            logger.error("模块 %s 注销失败: %s", self.module_id, e)
            return False

    # ------------------------------------------------------------------
    #  心跳
    # ------------------------------------------------------------------

    def heartbeat(self) -> bool:
        """
        发送一次心跳。

        Returns:
            True 表示成功
        """
        try:
            return self._registry.heartbeat(self.module_id, "running")
        except Exception as e:
            logger.warning("模块 %s 心跳发送失败: %s", self.module_id, e)
            return False

    def start_heartbeat(self) -> bool:
        """
        启动心跳线程。

        Returns:
            True 表示成功启动
        """
        if self._heartbeat_interval <= 0:
            logger.debug("心跳间隔为 0，跳过心跳线程启动")
            return False

        if self._heartbeat_thread and self._heartbeat_thread.is_alive():
            return True

        # 确保已注册
        if not self._registered:
            self.register()

        self._heartbeat_stop.clear()
        self._heartbeat_thread = threading.Thread(
            target=self._heartbeat_loop,
            name=f"Heartbeat-{self.module_id}",
            daemon=True,
        )
        self._heartbeat_thread.start()
        logger.info("模块 %s 心跳线程已启动（间隔 %ds）",
                   self.module_id, self._heartbeat_interval)
        return True

    def stop_heartbeat(self) -> None:
        """停止心跳线程"""
        self._heartbeat_stop.set()
        if self._heartbeat_thread:
            self._heartbeat_thread.join(timeout=2)
            self._heartbeat_thread = None

    def _heartbeat_loop(self) -> None:
        """心跳循环（后台线程）"""
        while not self._heartbeat_stop.is_set():
            try:
                self.heartbeat()
            except Exception as e:
                logger.error("模块 %s 心跳异常: %s", self.module_id, e)

            self._heartbeat_stop.wait(self._heartbeat_interval)

    # ------------------------------------------------------------------
    #  状态上报
    # ------------------------------------------------------------------

    def update_status(self, status: str, message: str = "") -> bool:
        """
        更新模块状态。

        Args:
            status: 状态字符串（running/stopped/error/starting等）
            message: 状态描述

        Returns:
            True 表示成功
        """
        module = self._registry.get_module(self.module_id)
        if module is None:
            return False

        try:
            module.status = ModuleStatus(status)
            if message:
                # 临时存储在 extra 字段中（Pydantic extra allow）
                pass
            return True
        except Exception as e:
            logger.warning("更新模块 %s 状态失败: %s", self.module_id, e)
            return False

    def report_error(self, error_message: str) -> bool:
        """上报错误状态"""
        return self.update_status("error")

    @property
    def is_registered(self) -> bool:
        """是否已注册"""
        return self._registered

    @property
    def registry(self) -> ModuleRegistry:
        """获取注册表实例"""
        return self._registry


# =============================================================================
#  便捷函数
# =============================================================================

def auto_register(
    module_id: str,
    module_name: str = "",
    port: int = 0,
    host: str = "127.0.0.1",
    enable_heartbeat: bool = True,
    **kwargs: Any,
) -> ModuleSelfRegister:
    """
    便捷函数：自动注册模块并启动心跳。

    使用示例：
        register = auto_register("m8", "控制塔", 8008)

    Args:
        module_id: 模块标识
        module_name: 模块名称
        port: 端口
        host: 地址
        enable_heartbeat: 是否启动心跳
        **kwargs: 其他参数传递给 ModuleSelfRegister

    Returns:
        ModuleSelfRegister 实例
    """
    reg = ModuleSelfRegister(
        module_id=module_id,
        module_name=module_name,
        port=port,
        host=host,
        **kwargs,
    )
    reg.register()

    if enable_heartbeat:
        reg.start_heartbeat()

    return reg


def register_on_startup(
    app=None,
    module_id: str = "",
    module_name: str = "",
    port: int = 0,
) -> Optional[ModuleSelfRegister]:
    """
    FastAPI 启动事件处理：自动注册模块。

    可作为 FastAPI 的 startup event 使用：
        @app.on_event("startup")
        async def on_startup():
            register_on_startup(app, "m8", "控制塔", 8008)

    Args:
        app: FastAPI 应用实例（可选）
        module_id: 模块标识
        module_name: 模块名称
        port: 端口

    Returns:
        ModuleSelfRegister 实例，或 None 如果失败
    """
    if not module_id:
        logger.warning("register_on_startup: module_id 为空，跳过注册")
        return None

    try:
        register = auto_register(
            module_id=module_id,
            module_name=module_name,
            port=port,
        )

        # 如果有 app，注册 shutdown 事件
        if app is not None:
            import atexit
            atexit.register(register.unregister)

        return register

    except Exception as e:
        logger.error("模块启动注册失败: %s", e)
        return None


# =============================================================================
#  模块导出
# =============================================================================

__all__ = [
    "ModuleSelfRegister",
    "auto_register",
    "register_on_startup",
]
