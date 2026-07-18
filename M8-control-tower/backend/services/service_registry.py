"""
M8 控制塔 - 服务注册中心服务
============================

服务端实现，管理所有模块实例的注册、发现、健康检查。

功能：
- 服务实例存储（内存 + 持久化到 JSON）
- 健康检查（心跳超时检测）
- 服务发现 API（查询接口）
- 实例上下线通知
- 服务依赖关系管理

使用方式：
    from .services.service_registry import get_service_registry_service

    svc = get_service_registry_service()
    svc.register_instance(...)
"""

from __future__ import annotations

import sys
import json
import time
import threading
import logging
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

# 将项目根目录加入 path，以便导入 shared 模块
_project_root = Path(__file__).parent.parent.parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

from shared.module_sdk.models import ServiceInstance, ServiceStatus, ApiResponse

logger = logging.getLogger("m8.service_registry")


# ============================================================
# 服务注册中心服务
# ============================================================

class ServiceRegistryService:
    """
    服务注册中心服务（M8 服务端）。

    管理所有服务实例的生命周期：注册、心跳、发现、注销。
    支持持久化存储和健康检查。
    """

    def __init__(
        self,
        heartbeat_timeout: float = 30.0,
        cleanup_interval: float = 10.0,
        persist_path: Optional[str] = None,
    ):
        """
        初始化服务注册中心。

        Args:
            heartbeat_timeout: 心跳超时（秒）
            cleanup_interval: 清理间隔（秒）
            persist_path: 持久化文件路径，None 表示不持久化
        """
        self._services: Dict[str, Dict[str, ServiceInstance]] = {}
        self._lock = threading.RLock()

        self.heartbeat_timeout = heartbeat_timeout
        self.cleanup_interval = cleanup_interval

        # 持久化
        self._persist_path = Path(persist_path) if persist_path else None

        # 回调
        self._on_register_callbacks: List[Callable[[ServiceInstance], None]] = []
        self._on_deregister_callbacks: List[Callable[[ServiceInstance], None]] = []
        self._on_health_change_callbacks: List[
            Callable[[ServiceInstance, ServiceStatus, ServiceStatus], None]
        ] = []

        # 清理线程
        self._cleanup_thread: Optional[threading.Thread] = None
        self._cleanup_stop = threading.Event()
        self._started = False

        # 服务依赖关系
        self._dependencies: Dict[str, List[str]] = {}  # service -> [dependencies]

        # 启动时加载持久化数据
        if self._persist_path:
            self._load_from_persist()

    # ------------------------------------------------------------------
    #  生命周期
    # ------------------------------------------------------------------

    def start(self) -> None:
        """启动服务（启动清理线程）"""
        if self._started:
            return

        self._cleanup_stop.clear()
        self._cleanup_thread = threading.Thread(
            target=self._cleanup_loop,
            name="ServiceRegistryCleanup",
            daemon=True,
        )
        self._cleanup_thread.start()
        self._started = True
        logger.info("Service registry service started (timeout=%.1fs)", self.heartbeat_timeout)

    def stop(self) -> None:
        """停止服务"""
        if not self._started:
            return

        self._cleanup_stop.set()
        if self._cleanup_thread:
            self._cleanup_thread.join(timeout=5)
            self._cleanup_thread = None

        # 持久化
        if self._persist_path:
            self._persist()

        self._started = False
        logger.info("Service registry service stopped")

    # ------------------------------------------------------------------
    #  注册/注销
    # ------------------------------------------------------------------

    def register_instance(
        self,
        service_name: str,
        instance_id: str,
        address: str,
        port: int,
        version: str = "1.0.0",
        weight: int = 1,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> ApiResponse:
        """
        注册服务实例。

        Args:
            service_name: 服务名
            instance_id: 实例 ID
            address: 地址
            port: 端口
            version: 版本
            weight: 权重
            metadata: 元数据

        Returns:
            ApiResponse
        """
        service_name = service_name.lower()
        instance = ServiceInstance(
            service_name=service_name,
            instance_id=instance_id,
            address=address,
            port=port,
            version=version,
            weight=weight,
            status=ServiceStatus.HEALTHY,
            metadata=metadata or {},
        )

        is_new = True
        old_status: Optional[ServiceStatus] = None

        with self._lock:
            if service_name not in self._services:
                self._services[service_name] = {}
            if instance_id in self._services[service_name]:
                is_new = False
                old_status = self._services[service_name][instance_id].status
            self._services[service_name][instance_id] = instance

            # 持久化
            if self._persist_path:
                self._persist()

        if is_new:
            logger.info("Service registered: %s/%s (%s:%d)",
                        service_name, instance_id, address, port)
            self._fire_register(instance)
        else:
            logger.debug("Service updated: %s/%s", service_name, instance_id)
            if old_status and old_status != instance.status:
                self._fire_health_change(instance, old_status, instance.status)

        return ApiResponse.success(
            data={"registered": True, "is_new": is_new},
            message=f"Service {service_name}/{instance_id} registered",
        )

    def deregister_instance(
        self,
        service_name: str,
        instance_id: str,
    ) -> ApiResponse:
        """
        注销服务实例。

        Args:
            service_name: 服务名
            instance_id: 实例 ID

        Returns:
            ApiResponse
        """
        service_name = service_name.lower()
        instance: Optional[ServiceInstance] = None

        with self._lock:
            service_instances = self._services.get(service_name)
            if not service_instances or instance_id not in service_instances:
                return ApiResponse.error(
                    code=404,
                    message=f"Instance not found: {service_name}/{instance_id}",
                )

            instance = service_instances.pop(instance_id)
            if not service_instances:
                del self._services[service_name]

            if self._persist_path:
                self._persist()

        if instance:
            logger.info("Service deregistered: %s/%s", service_name, instance_id)
            self._fire_deregister(instance)

        return ApiResponse.success(
            data={"deregistered": True},
            message=f"Service {service_name}/{instance_id} deregistered",
        )

    def heartbeat(
        self,
        service_name: str,
        instance_id: str,
        status: Optional[str] = None,
    ) -> ApiResponse:
        """
        实例心跳上报。

        Args:
            service_name: 服务名
            instance_id: 实例 ID
            status: 可选的状态更新

        Returns:
            ApiResponse
        """
        service_name = service_name.lower()

        with self._lock:
            service_instances = self._services.get(service_name)
            if not service_instances or instance_id not in service_instances:
                return ApiResponse.error(
                    code=404,
                    message=f"Instance not found: {service_name}/{instance_id}",
                )

            instance = service_instances[instance_id]
            old_status = instance.status
            instance.last_heartbeat = time.time()

            if status:
                try:
                    new_status = ServiceStatus(status)
                    if new_status != old_status:
                        instance.status = new_status
                        self._fire_health_change(instance, old_status, new_status)
                except ValueError:
                    pass

            # 如果之前不健康，心跳恢复为健康
            if old_status == ServiceStatus.UNHEALTHY:
                instance.status = ServiceStatus.HEALTHY
                self._fire_health_change(instance, old_status, ServiceStatus.HEALTHY)

        return ApiResponse.success(
            data={"heartbeat": True},
            message=f"Heartbeat received for {service_name}/{instance_id}",
        )

    # ------------------------------------------------------------------
    #  发现/查询
    # ------------------------------------------------------------------

    def discover(
        self,
        service_name: str,
        healthy_only: bool = True,
    ) -> ApiResponse:
        """
        发现服务实例。

        Args:
            service_name: 服务名
            healthy_only: 是否只返回健康实例

        Returns:
            ApiResponse with instances list
        """
        service_name = service_name.lower()

        with self._lock:
            service_instances = self._services.get(service_name)
            if not service_instances:
                return ApiResponse.success(
                    data={"service": service_name, "instances": [], "count": 0},
                    message=f"No instances found for {service_name}",
                )

            instances = list(service_instances.values())
            if healthy_only:
                instances = [i for i in instances if i.status == ServiceStatus.HEALTHY]

        return ApiResponse.success(
            data={
                "service": service_name,
                "instances": [i.to_dict() for i in instances],
                "count": len(instances),
            },
        )

    def get_all_services(self) -> ApiResponse:
        """获取所有服务及其实例"""
        with self._lock:
            services: Dict[str, Any] = {}
            for name, instances in self._services.items():
                services[name] = [i.to_dict() for i in instances.values()]

        return ApiResponse.success(
            data={
                "service_count": len(services),
                "services": services,
            },
        )

    def get_service_names(self) -> ApiResponse:
        """获取所有服务名称"""
        with self._lock:
            names = list(self._services.keys())
        return ApiResponse.success(data={"services": names, "count": len(names)})

    def get_instance(
        self,
        service_name: str,
        instance_id: str,
    ) -> ApiResponse:
        """获取指定实例详情"""
        service_name = service_name.lower()

        with self._lock:
            service_instances = self._services.get(service_name)
            if not service_instances or instance_id not in service_instances:
                return ApiResponse.error(
                    code=404,
                    message=f"Instance not found: {service_name}/{instance_id}",
                )
            instance = service_instances[instance_id]

        return ApiResponse.success(data=instance.to_dict())

    # ------------------------------------------------------------------
    #  健康检查
    # ------------------------------------------------------------------

    def health_check(self) -> ApiResponse:
        """注册中心健康状态"""
        with self._lock:
            total_services = len(self._services)
            total_instances = sum(len(v) for v in self._services.values())
            healthy_instances = sum(
                1
                for instances in self._services.values()
                for inst in instances.values()
                if inst.status == ServiceStatus.HEALTHY
            )

        return ApiResponse.success(
            data={
                "status": "healthy",
                "total_services": total_services,
                "total_instances": total_instances,
                "healthy_instances": healthy_instances,
                "unhealthy_instances": total_instances - healthy_instances,
                "heartbeat_timeout": self.heartbeat_timeout,
            },
            message="Service registry is healthy",
        )

    # ------------------------------------------------------------------
    #  依赖管理
    # ------------------------------------------------------------------

    def set_dependencies(
        self,
        service_name: str,
        dependencies: List[str],
    ) -> ApiResponse:
        """设置服务依赖关系"""
        service_name = service_name.lower()
        with self._lock:
            self._dependencies[service_name] = [d.lower() for d in dependencies]
        return ApiResponse.success(
            data={"service": service_name, "dependencies": dependencies},
        )

    def get_dependencies(self, service_name: str) -> ApiResponse:
        """获取服务依赖"""
        service_name = service_name.lower()
        with self._lock:
            deps = self._dependencies.get(service_name, [])
        return ApiResponse.success(
            data={"service": service_name, "dependencies": deps},
        )

    def get_dependents(self, service_name: str) -> ApiResponse:
        """获取依赖于该服务的服务列表"""
        service_name = service_name.lower()
        with self._lock:
            dependents = [
                svc
                for svc, deps in self._dependencies.items()
                if service_name in deps
            ]
        return ApiResponse.success(
            data={"service": service_name, "dependents": dependents},
        )

    # ------------------------------------------------------------------
    #  统计
    # ------------------------------------------------------------------

    def get_stats(self) -> Dict[str, Any]:
        """获取统计信息"""
        with self._lock:
            services = {}
            for name, instances in self._services.items():
                healthy = sum(1 for i in instances.values() if i.status == ServiceStatus.HEALTHY)
                unhealthy = sum(1 for i in instances.values() if i.status == ServiceStatus.UNHEALTHY)
                services[name] = {
                    "total": len(instances),
                    "healthy": healthy,
                    "unhealthy": unhealthy,
                }
        return {
            "service_count": len(services),
            "total_instances": sum(s["total"] for s in services.values()),
            "healthy_instances": sum(s["healthy"] for s in services.values()),
            "services": services,
        }

    # ------------------------------------------------------------------
    #  回调
    # ------------------------------------------------------------------

    def on_register(self, callback: Callable[[ServiceInstance], None]) -> None:
        self._on_register_callbacks.append(callback)

    def on_deregister(self, callback: Callable[[ServiceInstance], None]) -> None:
        self._on_deregister_callbacks.append(callback)

    def on_health_change(
        self,
        callback: Callable[[ServiceInstance, ServiceStatus, ServiceStatus], None],
    ) -> None:
        self._on_health_change_callbacks.append(callback)

    def _fire_register(self, instance: ServiceInstance) -> None:
        for cb in self._on_register_callbacks:
            try:
                cb(instance)
            except Exception as e:
                logger.error("Register callback error: %s", e)

    def _fire_deregister(self, instance: ServiceInstance) -> None:
        for cb in self._on_deregister_callbacks:
            try:
                cb(instance)
            except Exception as e:
                logger.error("Deregister callback error: %s", e)

    def _fire_health_change(
        self,
        instance: ServiceInstance,
        old_status: ServiceStatus,
        new_status: ServiceStatus,
    ) -> None:
        for cb in self._on_health_change_callbacks:
            try:
                cb(instance, old_status, new_status)
            except Exception as e:
                logger.error("Health change callback error: %s", e)

    # ------------------------------------------------------------------
    #  自动清理
    # ------------------------------------------------------------------

    def _cleanup_loop(self) -> None:
        while not self._cleanup_stop.is_set():
            try:
                self._cleanup_timed_out()
            except Exception as e:
                logger.error("Cleanup loop error: %s", e)
            self._cleanup_stop.wait(self.cleanup_interval)

    def _cleanup_timed_out(self) -> int:
        now = time.time()
        to_remove: List[tuple] = []

        with self._lock:
            for service_name, instances in self._services.items():
                for instance_id, instance in instances.items():
                    if now - instance.last_heartbeat > self.heartbeat_timeout:
                        if instance.status == ServiceStatus.HEALTHY:
                            instance.status = ServiceStatus.UNHEALTHY
                            logger.warning(
                                "Instance heartbeat timeout, marked unhealthy: %s/%s",
                                service_name, instance_id,
                            )
                            self._fire_health_change(
                                instance,
                                ServiceStatus.HEALTHY,
                                ServiceStatus.UNHEALTHY,
                            )
                        else:
                            to_remove.append((service_name, instance_id))

        for service_name, instance_id in to_remove:
            self.deregister_instance(service_name, instance_id)
            logger.info("Instance removed due to timeout: %s/%s",
                        service_name, instance_id)

        return len(to_remove)

    # ------------------------------------------------------------------
    #  持久化
    # ------------------------------------------------------------------

    def _persist(self) -> None:
        """持久化到文件"""
        if not self._persist_path:
            return
        try:
            data = {
                "services": {
                    name: {iid: inst.to_dict() for iid, inst in instances.items()}
                    for name, instances in self._services.items()
                },
                "dependencies": self._dependencies,
                "timestamp": time.time(),
            }
            self._persist_path.parent.mkdir(parents=True, exist_ok=True)
            with open(self._persist_path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.error("Failed to persist service registry: %s", e)

    def _load_from_persist(self) -> int:
        """从持久化文件加载"""
        if not self._persist_path or not self._persist_path.exists():
            return 0

        try:
            with open(self._persist_path, "r", encoding="utf-8") as f:
                data = json.load(f)

            services_data = data.get("services", {})
            count = 0
            with self._lock:
                for name, instances in services_data.items():
                    if name not in self._services:
                        self._services[name] = {}
                    for iid, inst_data in instances.items():
                        try:
                            # 加载后标记为 unknown，等待心跳确认
                            instance = ServiceInstance.from_dict(inst_data)
                            instance.status = ServiceStatus.UNKNOWN
                            self._services[name][iid] = instance
                            count += 1
                        except Exception as e:
                            logger.warning("Failed to load instance %s/%s: %s", name, iid, e)

                self._dependencies = data.get("dependencies", {})

            logger.info("Loaded %d instances from persist file", count)
            return count
        except Exception as e:
            logger.error("Failed to load service registry from persist: %s", e)
            return 0

    def clear(self) -> None:
        """清空所有数据（测试用）"""
        with self._lock:
            self._services.clear()
            self._dependencies.clear()


# ============================================================
# 全局单例
# ============================================================

_registry_service: Optional[ServiceRegistryService] = None
_registry_service_lock = threading.Lock()


def get_service_registry_service() -> ServiceRegistryService:
    """获取服务注册中心服务单例"""
    global _registry_service
    if _registry_service is None:
        with _registry_service_lock:
            if _registry_service is None:
                # 默认持久化到 data 目录
                data_dir = Path(__file__).parent.parent / "data"
                persist_path = data_dir / "service_registry.json"
                _registry_service = ServiceRegistryService(
                    persist_path=str(persist_path),
                )
                _registry_service.start()
    return _registry_service


def reset_service_registry_service() -> None:
    """重置服务注册中心（测试用）"""
    global _registry_service
    with _registry_service_lock:
        if _registry_service:
            _registry_service.stop()
        _registry_service = None


# ============================================================
# 模块导出
# ============================================================

__all__ = [
    "ServiceRegistryService",
    "get_service_registry_service",
    "reset_service_registry_service",
]
