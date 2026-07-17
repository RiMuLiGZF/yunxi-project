"""
云汐服务注册表 (Service Registry)

基于模块注册表的服务发现增强：
- 服务实例注册与注销
- 健康实例自动发现
- 服务健康状态跟踪
- 实例元数据管理
- 服务查询接口

与 ModuleRegistry 集成，作为其高可用增强层。

使用方式：
    from shared.core.ha.service_registry import ServiceRegistry, ServiceInstanceInfo

    registry = ServiceRegistry()
    registry.register_instance(ServiceInstanceInfo(
        service_name="m1",
        instance_id="m1-node1",
        host="127.0.0.1",
        port=8001,
    ))
    instances = registry.get_healthy_instances("m1")
"""

from __future__ import annotations

import time
import threading
import logging
from enum import Enum
from dataclasses import dataclass, field
from typing import Dict, Any, Optional, List, Set, Callable
from collections import defaultdict
from datetime import datetime, timezone

logger = logging.getLogger(__name__)


# ============================================================
# 枚举
# ============================================================

class ServiceStatus(str, Enum):
    """服务实例状态"""
    HEALTHY = "healthy"
    UNHEALTHY = "unhealthy"
    STARTING = "starting"
    STOPPING = "stopping"
    UNKNOWN = "unknown"


# ============================================================
# 数据类
# ============================================================

@dataclass
class ServiceInstanceInfo:
    """服务实例信息"""
    service_name: str
    instance_id: str
    host: str
    port: int
    version: str = "1.0.0"
    weight: int = 1
    status: ServiceStatus = ServiceStatus.HEALTHY
    health_check_url: str = ""
    last_heartbeat: float = field(default_factory=time.time)
    metadata: Dict[str, Any] = field(default_factory=dict)

    @property
    def address(self) -> str:
        return f"http://{self.host}:{self.port}"

    @property
    def is_healthy(self) -> bool:
        return self.status == ServiceStatus.HEALTHY

    def to_dict(self) -> Dict[str, Any]:
        return {
            "service_name": self.service_name,
            "instance_id": self.instance_id,
            "host": self.host,
            "port": self.port,
            "address": self.address,
            "version": self.version,
            "weight": self.weight,
            "status": self.status.value,
            "health_check_url": self.health_check_url,
            "last_heartbeat": self.last_heartbeat,
            "metadata": self.metadata,
        }


# ============================================================
# 服务注册表
# ============================================================

class ServiceRegistry:
    """
    服务注册表

    管理所有服务实例的注册、发现和健康状态。
    支持按服务名查询健康实例，支持心跳保活。
    """

    # 单例
    _instance: Optional["ServiceRegistry"] = None
    _instance_lock = threading.Lock()

    def __init__(self):
        self._services: Dict[str, Dict[str, ServiceInstanceInfo]] = defaultdict(dict)
        self._lock = threading.RLock()

        # 心跳超时设置
        self.heartbeat_timeout: float = 30.0  # 秒
        self.cleanup_interval: float = 10.0   # 秒

        # 回调
        self._on_register_callbacks: List[Callable[[ServiceInstanceInfo], None]] = []
        self._on_deregister_callbacks: List[Callable[[ServiceInstanceInfo], None]] = []
        self._on_health_change_callbacks: List[Callable[[ServiceInstanceInfo, ServiceStatus, ServiceStatus], None]] = []

        # 清理线程
        self._cleanup_thread: Optional[threading.Thread] = None
        self._cleanup_stop = threading.Event()

    @classmethod
    def get_instance(cls) -> "ServiceRegistry":
        """获取全局单例"""
        if cls._instance is None:
            with cls._instance_lock:
                if cls._instance is None:
                    cls._instance = cls()
        return cls._instance

    # ------------------------------------------------------------------
    #  注册/注销
    # ------------------------------------------------------------------

    def register_instance(self, instance: ServiceInstanceInfo) -> bool:
        """注册服务实例"""
        with self._lock:
            service_instances = self._services[instance.service_name]
            if instance.instance_id in service_instances:
                logger.warning("Instance already registered: %s/%s",
                               instance.service_name, instance.instance_id)
                # 更新实例信息
                old_status = service_instances[instance.instance_id].status
                service_instances[instance.instance_id] = instance
                if old_status != instance.status:
                    self._fire_health_change(instance, old_status, instance.status)
                return False

            service_instances[instance.instance_id] = instance
            logger.info("Instance registered: %s/%s (%s:%d)",
                        instance.service_name, instance.instance_id,
                        instance.host, instance.port)

        self._fire_register(instance)
        return True

    def deregister_instance(self, service_name: str, instance_id: str) -> bool:
        """注销服务实例"""
        with self._lock:
            service_instances = self._services.get(service_name)
            if not service_instances or instance_id not in service_instances:
                return False

            instance = service_instances.pop(instance_id)
            if not service_instances:
                del self._services[service_name]

            logger.info("Instance deregistered: %s/%s", service_name, instance_id)

        self._fire_deregister(instance)
        return True

    def heartbeat(self, service_name: str, instance_id: str, status: Optional[ServiceStatus] = None) -> bool:
        """实例心跳上报"""
        with self._lock:
            service_instances = self._services.get(service_name)
            if not service_instances or instance_id not in service_instances:
                return False

            instance = service_instances[instance_id]
            old_status = instance.status
            instance.last_heartbeat = time.time()

            if status and status != old_status:
                instance.status = status
                self._fire_health_change(instance, old_status, status)

            return True

    # ------------------------------------------------------------------
    #  查询
    # ------------------------------------------------------------------

    def get_instance(self, service_name: str, instance_id: str) -> Optional[ServiceInstanceInfo]:
        """获取指定实例"""
        with self._lock:
            service_instances = self._services.get(service_name)
            if not service_instances:
                return None
            return service_instances.get(instance_id)

    def get_all_instances(self, service_name: str) -> List[ServiceInstanceInfo]:
        """获取服务的所有实例"""
        with self._lock:
            service_instances = self._services.get(service_name)
            if not service_instances:
                return []
            return list(service_instances.values())

    def get_healthy_instances(self, service_name: str) -> List[ServiceInstanceInfo]:
        """获取服务的健康实例"""
        with self._lock:
            service_instances = self._services.get(service_name)
            if not service_instances:
                return []
            return [
                inst for inst in service_instances.values()
                if inst.status == ServiceStatus.HEALTHY
            ]

    def get_service_names(self) -> List[str]:
        """获取所有服务名称"""
        with self._lock:
            return list(self._services.keys())

    def has_service(self, service_name: str) -> bool:
        """服务是否存在（有实例）"""
        with self._lock:
            return service_name in self._services and len(self._services[service_name]) > 0

    def has_healthy_instance(self, service_name: str) -> bool:
        """服务是否有健康实例"""
        return len(self.get_healthy_instances(service_name)) > 0

    def get_service_count(self) -> int:
        """获取服务数量"""
        with self._lock:
            return len(self._services)

    def get_total_instance_count(self) -> int:
        """获取总实例数"""
        with self._lock:
            return sum(len(v) for v in self._services.values())

    def get_healthy_instance_count(self) -> int:
        """获取健康实例总数"""
        with self._lock:
            count = 0
            for service_instances in self._services.values():
                for inst in service_instances.values():
                    if inst.status == ServiceStatus.HEALTHY:
                        count += 1
            return count

    # ------------------------------------------------------------------
    #  状态管理
    # ------------------------------------------------------------------

    def set_instance_status(self, service_name: str, instance_id: str, status: ServiceStatus) -> bool:
        """设置实例状态"""
        with self._lock:
            service_instances = self._services.get(service_name)
            if not service_instances or instance_id not in service_instances:
                return False

            instance = service_instances[instance_id]
            old_status = instance.status
            if old_status == status:
                return True

            instance.status = status
            self._fire_health_change(instance, old_status, status)
            logger.info("Instance status changed: %s/%s %s -> %s",
                        service_name, instance_id, old_status.value, status.value)
            return True

    def mark_healthy(self, service_name: str, instance_id: str) -> bool:
        """标记实例健康"""
        return self.set_instance_status(service_name, instance_id, ServiceStatus.HEALTHY)

    def mark_unhealthy(self, service_name: str, instance_id: str) -> bool:
        """标记实例不健康"""
        return self.set_instance_status(service_name, instance_id, ServiceStatus.UNHEALTHY)

    # ------------------------------------------------------------------
    #  回调
    # ------------------------------------------------------------------

    def on_register(self, callback: Callable[[ServiceInstanceInfo], None]) -> None:
        """注册实例注册回调"""
        self._on_register_callbacks.append(callback)

    def on_deregister(self, callback: Callable[[ServiceInstanceInfo], None]) -> None:
        """注册实例注销回调"""
        self._on_deregister_callbacks.append(callback)

    def on_health_change(self, callback: Callable[[ServiceInstanceInfo, ServiceStatus, ServiceStatus], None]) -> None:
        """注册健康状态变化回调"""
        self._on_health_change_callbacks.append(callback)

    def _fire_register(self, instance: ServiceInstanceInfo) -> None:
        for cb in self._on_register_callbacks:
            try:
                cb(instance)
            except Exception as e:
                logger.error("Register callback error: %s", e)

    def _fire_deregister(self, instance: ServiceInstanceInfo) -> None:
        for cb in self._on_deregister_callbacks:
            try:
                cb(instance)
            except Exception as e:
                logger.error("Deregister callback error: %s", e)

    def _fire_health_change(
        self,
        instance: ServiceInstanceInfo,
        old_status: ServiceStatus,
        new_status: ServiceStatus,
    ) -> None:
        for cb in self._on_health_change_callbacks:
            try:
                cb(instance, old_status, new_status)
            except Exception as e:
                logger.error("Health change callback error: %s", e)

    # ------------------------------------------------------------------
    #  自动清理（心跳超时）
    # ------------------------------------------------------------------

    def start_auto_cleanup(self) -> bool:
        """启动自动清理线程"""
        if self._cleanup_thread and self._cleanup_thread.is_alive():
            return True

        self._cleanup_stop.clear()
        self._cleanup_thread = threading.Thread(
            target=self._cleanup_loop,
            name="ServiceRegistryCleanup",
            daemon=True,
        )
        self._cleanup_thread.start()
        logger.info("Service registry auto-cleanup started (timeout=%.1fs)", self.heartbeat_timeout)
        return True

    def stop_auto_cleanup(self) -> None:
        """停止自动清理"""
        self._cleanup_stop.set()
        if self._cleanup_thread:
            self._cleanup_thread.join(timeout=5)
            self._cleanup_thread = None

    def _cleanup_loop(self) -> None:
        """清理循环"""
        while not self._cleanup_stop.is_set():
            try:
                self._cleanup_timed_out_instances()
            except Exception as e:
                logger.error("Cleanup loop error: %s", e)

            self._cleanup_stop.wait(self.cleanup_interval)

    def _cleanup_timed_out_instances(self) -> int:
        """清理心跳超时的实例，返回清理数量"""
        now = time.time()
        to_remove: List[tuple] = []

        with self._lock:
            for service_name, instances in self._services.items():
                for instance_id, instance in instances.items():
                    if now - instance.last_heartbeat > self.heartbeat_timeout:
                        if instance.status == ServiceStatus.HEALTHY:
                            # 先标记为不健康
                            old_status = instance.status
                            instance.status = ServiceStatus.UNHEALTHY
                            self._fire_health_change(instance, old_status, ServiceStatus.UNHEALTHY)
                            logger.warning("Instance heartbeat timed out, marked unhealthy: %s/%s",
                                           service_name, instance_id)
                        else:
                            # 已经不健康且超时，移除
                            to_remove.append((service_name, instance_id))

        # 移除超时的不健康实例
        for service_name, instance_id in to_remove:
            self.deregister_instance(service_name, instance_id)
            logger.info("Instance removed due to timeout: %s/%s", service_name, instance_id)

        return len(to_remove)

    # ------------------------------------------------------------------
    #  统计
    # ------------------------------------------------------------------

    def get_stats(self) -> Dict[str, Any]:
        """获取注册表统计"""
        with self._lock:
            services = {}
            for service_name, instances in self._services.items():
                healthy = sum(1 for i in instances.values() if i.status == ServiceStatus.HEALTHY)
                unhealthy = sum(1 for i in instances.values() if i.status == ServiceStatus.UNHEALTHY)
                services[service_name] = {
                    "total": len(instances),
                    "healthy": healthy,
                    "unhealthy": unhealthy,
                    "instances": [inst.to_dict() for inst in instances.values()],
                }

        return {
            "service_count": len(services),
            "total_instances": sum(s["total"] for s in services.values()),
            "healthy_instances": sum(s["healthy"] for s in services.values()),
            "unhealthy_instances": sum(s["unhealthy"] for s in services.values()),
            "heartbeat_timeout": self.heartbeat_timeout,
            "services": services,
        }

    def clear(self) -> None:
        """清空注册表（测试用）"""
        with self._lock:
            self._services.clear()
