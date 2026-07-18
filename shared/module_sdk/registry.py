"""
云汐系统模块间通信 SDK - 服务注册中心客户端
============================================

提供服务注册、发现、心跳的统一客户端。

支持两种模式：
1. 内存模式（默认）：进程内注册发现，适用于单体部署
2. 远程模式：通过 HTTP 调用 M8 控制塔的注册中心 API，适用于分布式部署

使用方式：
    from shared.module_sdk.registry import ServiceRegistryClient, get_registry_client

    # 注册
    registry = get_registry_client()
    registry.register("m1", "m1-instance-1", "127.0.0.1", 8001)

    # 发现
    instances = registry.discover("m1")
"""

from __future__ import annotations

import sys
import time
import threading
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional, Callable

# 确保可以导入 shared 包
_shared_parent = Path(__file__).resolve().parent.parent.parent
if str(_shared_parent) not in sys.path:
    sys.path.insert(0, str(_shared_parent))

from .models import ServiceInstance, ServiceStatus, SdkErrorCode

logger = logging.getLogger(__name__)


# ============================================================
# 内存模式注册中心
# ============================================================

class InMemoryRegistry:
    """
    内存模式服务注册中心。

    所有服务实例存储在进程内存中，适用于单体部署或测试环境。
    线程安全。
    """

    def __init__(self):
        self._services: Dict[str, Dict[str, ServiceInstance]] = {}
        self._lock = threading.RLock()

        # 心跳超时设置
        self.heartbeat_timeout: float = 30.0  # 秒
        self.cleanup_interval: float = 10.0   # 秒

        # 回调
        self._on_register_callbacks: List[Callable[[ServiceInstance], None]] = []
        self._on_deregister_callbacks: List[Callable[[ServiceInstance], None]] = []

        # 清理线程
        self._cleanup_thread: Optional[threading.Thread] = None
        self._cleanup_stop = threading.Event()

    # ------------------------------------------------------------------
    #  注册/注销
    # ------------------------------------------------------------------

    def register(
        self,
        service_name: str,
        instance_id: str,
        address: str,
        port: int,
        metadata: Optional[Dict[str, Any]] = None,
        version: str = "1.0.0",
        weight: int = 1,
    ) -> bool:
        """注册服务实例"""
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

        with self._lock:
            if service_name not in self._services:
                self._services[service_name] = {}
            is_new = instance_id not in self._services[service_name]
            self._services[service_name][instance_id] = instance

        if is_new:
            logger.info("Service registered: %s/%s (%s:%d)",
                        service_name, instance_id, address, port)
            self._fire_register(instance)
        else:
            logger.debug("Service updated: %s/%s", service_name, instance_id)

        return True

    def deregister(self, service_name: str, instance_id: str) -> bool:
        """注销服务实例"""
        service_name = service_name.lower()
        instance: Optional[ServiceInstance] = None

        with self._lock:
            service_instances = self._services.get(service_name)
            if not service_instances or instance_id not in service_instances:
                return False
            instance = service_instances.pop(instance_id)
            if not service_instances:
                del self._services[service_name]

        if instance:
            logger.info("Service deregistered: %s/%s", service_name, instance_id)
            self._fire_deregister(instance)

        return True

    def heartbeat(self, service_name: str, instance_id: str) -> bool:
        """发送心跳"""
        service_name = service_name.lower()
        with self._lock:
            service_instances = self._services.get(service_name)
            if not service_instances or instance_id not in service_instances:
                return False
            instance = service_instances[instance_id]
            instance.last_heartbeat = time.time()
            if instance.status != ServiceStatus.HEALTHY:
                instance.status = ServiceStatus.HEALTHY
            return True

    # ------------------------------------------------------------------
    #  发现
    # ------------------------------------------------------------------

    def discover(self, service_name: str) -> List[ServiceInstance]:
        """发现健康的服务实例列表"""
        service_name = service_name.lower()
        with self._lock:
            service_instances = self._services.get(service_name)
            if not service_instances:
                return []
            return [
                inst for inst in service_instances.values()
                if inst.status == ServiceStatus.HEALTHY
            ]

    def get_all_instances(self, service_name: str) -> List[ServiceInstance]:
        """获取服务的所有实例（含不健康的）"""
        service_name = service_name.lower()
        with self._lock:
            service_instances = self._services.get(service_name)
            if not service_instances:
                return []
            return list(service_instances.values())

    def get_all_services(self) -> Dict[str, List[ServiceInstance]]:
        """获取所有服务及其实例"""
        with self._lock:
            result: Dict[str, List[ServiceInstance]] = {}
            for name, instances in self._services.items():
                result[name] = list(instances.values())
            return result

    def get_service_names(self) -> List[str]:
        """获取所有服务名称"""
        with self._lock:
            return list(self._services.keys())

    def has_service(self, service_name: str) -> bool:
        """服务是否存在"""
        service_name = service_name.lower()
        with self._lock:
            return service_name in self._services and len(self._services[service_name]) > 0

    def get_instance(self, service_name: str, instance_id: str) -> Optional[ServiceInstance]:
        """获取指定实例"""
        service_name = service_name.lower()
        with self._lock:
            service_instances = self._services.get(service_name)
            if not service_instances:
                return None
            return service_instances.get(instance_id)

    # ------------------------------------------------------------------
    #  回调
    # ------------------------------------------------------------------

    def on_register(self, callback: Callable[[ServiceInstance], None]) -> None:
        """注册实例注册回调"""
        self._on_register_callbacks.append(callback)

    def on_deregister(self, callback: Callable[[ServiceInstance], None]) -> None:
        """注册实例注销回调"""
        self._on_deregister_callbacks.append(callback)

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
            name="InMemoryRegistryCleanup",
            daemon=True,
        )
        self._cleanup_thread.start()
        logger.info("In-memory registry auto-cleanup started (timeout=%.1fs)",
                    self.heartbeat_timeout)
        return True

    def stop_auto_cleanup(self) -> None:
        """停止自动清理"""
        self._cleanup_stop.set()
        if self._cleanup_thread:
            self._cleanup_thread.join(timeout=5)
            self._cleanup_thread = None

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
                            logger.warning("Instance heartbeat timeout, marked unhealthy: %s/%s",
                                           service_name, instance_id)
                        else:
                            to_remove.append((service_name, instance_id))

        for service_name, instance_id in to_remove:
            self.deregister(service_name, instance_id)
            logger.info("Instance removed due to timeout: %s/%s",
                        service_name, instance_id)

        return len(to_remove)

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

    def clear(self) -> None:
        """清空所有服务（测试用）"""
        with self._lock:
            self._services.clear()


# ============================================================
# 远程模式注册中心客户端
# ============================================================

class RemoteRegistryClient:
    """
    远程服务注册中心客户端。

    通过 HTTP 调用 M8 控制塔的注册中心 API。
    适用于分布式部署场景。
    """

    def __init__(self, registry_url: str, token: str = "", timeout: float = 5.0):
        """
        初始化远程注册中心客户端。

        Args:
            registry_url: 注册中心地址（如 "http://127.0.0.1:8008"）
            token: 服务间认证 token
            timeout: 请求超时（秒）
        """
        self.registry_url = registry_url.rstrip("/")
        self.token = token
        self.timeout = timeout
        self._client: Optional[Any] = None  # httpx.AsyncClient 延迟导入

    def _get_client(self):
        """延迟获取 httpx 客户端"""
        if self._client is None:
            import httpx
            self._client = httpx.Client(
                base_url=self.registry_url,
                timeout=self.timeout,
            )
        return self._client

    def _headers(self) -> Dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        return headers

    def register(
        self,
        service_name: str,
        instance_id: str,
        address: str,
        port: int,
        metadata: Optional[Dict[str, Any]] = None,
        version: str = "1.0.0",
        weight: int = 1,
    ) -> bool:
        """注册服务实例"""
        try:
            client = self._get_client()
            resp = client.post(
                "/registry/register",
                json={
                    "service_name": service_name,
                    "instance_id": instance_id,
                    "address": address,
                    "port": port,
                    "metadata": metadata or {},
                    "version": version,
                    "weight": weight,
                },
                headers=self._headers(),
            )
            resp.raise_for_status()
            data = resp.json()
            return data.get("code", -1) == 0
        except Exception as e:
            logger.error("Remote register failed: %s", e)
            return False

    def deregister(self, service_name: str, instance_id: str) -> bool:
        """注销服务实例"""
        try:
            client = self._get_client()
            resp = client.post(
                "/registry/deregister",
                json={
                    "service_name": service_name,
                    "instance_id": instance_id,
                },
                headers=self._headers(),
            )
            resp.raise_for_status()
            data = resp.json()
            return data.get("code", -1) == 0
        except Exception as e:
            logger.error("Remote deregister failed: %s", e)
            return False

    def heartbeat(self, service_name: str, instance_id: str) -> bool:
        """发送心跳"""
        try:
            client = self._get_client()
            resp = client.post(
                "/registry/heartbeat",
                json={
                    "service_name": service_name,
                    "instance_id": instance_id,
                },
                headers=self._headers(),
            )
            resp.raise_for_status()
            data = resp.json()
            return data.get("code", -1) == 0
        except Exception as e:
            logger.error("Remote heartbeat failed: %s", e)
            return False

    def discover(self, service_name: str) -> List[ServiceInstance]:
        """发现服务实例"""
        try:
            client = self._get_client()
            resp = client.get(
                f"/registry/services/{service_name}",
                headers=self._headers(),
            )
            resp.raise_for_status()
            data = resp.json()
            if data.get("code", -1) != 0:
                return []
            instances_data = data.get("data", {}).get("instances", [])
            return [ServiceInstance.from_dict(d) for d in instances_data]
        except Exception as e:
            logger.error("Remote discover failed: %s", e)
            return []

    def get_all_services(self) -> Dict[str, List[ServiceInstance]]:
        """获取所有服务"""
        try:
            client = self._get_client()
            resp = client.get(
                "/registry/services",
                headers=self._headers(),
            )
            resp.raise_for_status()
            data = resp.json()
            if data.get("code", -1) != 0:
                return {}
            services_data = data.get("data", {}).get("services", {})
            result = {}
            for name, inst_list in services_data.items():
                result[name] = [ServiceInstance.from_dict(d) for d in inst_list]
            return result
        except Exception as e:
            logger.error("Remote get_all_services failed: %s", e)
            return {}

    def get_service_names(self) -> List[str]:
        """获取所有服务名称"""
        return list(self.get_all_services().keys())

    def has_service(self, service_name: str) -> bool:
        """服务是否存在"""
        return len(self.discover(service_name)) > 0

    def get_instance(self, service_name: str, instance_id: str) -> Optional[ServiceInstance]:
        """获取指定实例"""
        instances = self.discover(service_name)
        for inst in instances:
            if inst.instance_id == instance_id:
                return inst
        return None

    def close(self) -> None:
        """关闭客户端"""
        if self._client:
            try:
                self._client.close()
            except Exception:
                pass
            self._client = None


# ============================================================
# 统一注册中心客户端接口
# ============================================================

class ServiceRegistryClient:
    """
    服务注册中心统一客户端。

    根据配置自动选择内存模式或远程模式。
    提供统一的注册、注销、心跳、发现接口。
    """

    def __init__(
        self,
        mode: str = "memory",
        registry_url: str = "",
        token: str = "",
        heartbeat_timeout: float = 30.0,
    ):
        """
        初始化注册中心客户端。

        Args:
            mode: 模式 ("memory" 或 "remote")
            registry_url: 远程注册中心地址（remote 模式必填）
            token: 服务间认证 token
            heartbeat_timeout: 心跳超时（秒，仅 memory 模式）
        """
        self.mode = mode
        self._impl: Any = None

        if mode == "memory":
            self._impl = InMemoryRegistry()
            self._impl.heartbeat_timeout = heartbeat_timeout
            self._impl.start_auto_cleanup()
        elif mode == "remote":
            if not registry_url:
                raise ValueError("Remote mode requires registry_url")
            self._impl = RemoteRegistryClient(registry_url, token=token)
        else:
            raise ValueError(f"Unsupported registry mode: {mode}")

    # ---- 代理方法 ----

    def register(
        self,
        service_name: str,
        instance_id: str,
        address: str,
        port: int,
        metadata: Optional[Dict[str, Any]] = None,
        version: str = "1.0.0",
        weight: int = 1,
    ) -> bool:
        """注册服务实例"""
        return self._impl.register(
            service_name, instance_id, address, port,
            metadata=metadata, version=version, weight=weight,
        )

    def deregister(self, service_name: str, instance_id: str) -> bool:
        """注销服务实例"""
        return self._impl.deregister(service_name, instance_id)

    def heartbeat(self, service_name: str, instance_id: str) -> bool:
        """发送心跳"""
        return self._impl.heartbeat(service_name, instance_id)

    def discover(self, service_name: str) -> List[ServiceInstance]:
        """发现健康的服务实例列表"""
        return self._impl.discover(service_name)

    def get_all_services(self) -> Dict[str, List[ServiceInstance]]:
        """获取所有服务及其实例"""
        return self._impl.get_all_services()

    def get_service_names(self) -> List[str]:
        """获取所有服务名称"""
        return self._impl.get_service_names()

    def has_service(self, service_name: str) -> bool:
        """服务是否存在（有健康实例）"""
        return self._impl.has_service(service_name)

    def get_instance(self, service_name: str, instance_id: str) -> Optional[ServiceInstance]:
        """获取指定实例"""
        return self._impl.get_instance(service_name, instance_id)

    def get_all_instances(self, service_name: str) -> List[ServiceInstance]:
        """获取服务的所有实例（含不健康的）"""
        if hasattr(self._impl, "get_all_instances"):
            return self._impl.get_all_instances(service_name)
        return self.discover(service_name)

    def get_stats(self) -> Dict[str, Any]:
        """获取统计信息"""
        if hasattr(self._impl, "get_stats"):
            return self._impl.get_stats()
        return {"mode": self.mode}

    def on_register(self, callback: Callable[[ServiceInstance], None]) -> None:
        """注册实例注册回调（仅 memory 模式）"""
        if hasattr(self._impl, "on_register"):
            self._impl.on_register(callback)

    def on_deregister(self, callback: Callable[[ServiceInstance], None]) -> None:
        """注册实例注销回调（仅 memory 模式）"""
        if hasattr(self._impl, "on_deregister"):
            self._impl.on_deregister(callback)

    def clear(self) -> None:
        """清空所有服务（测试用）"""
        if hasattr(self._impl, "clear"):
            self._impl.clear()

    def close(self) -> None:
        """关闭客户端"""
        if hasattr(self._impl, "stop_auto_cleanup"):
            self._impl.stop_auto_cleanup()
        if hasattr(self._impl, "close"):
            self._impl.close()


# ============================================================
# 全局单例
# ============================================================

_registry_client: Optional[ServiceRegistryClient] = None
_registry_lock = threading.Lock()


def get_registry_client(
    mode: str = "memory",
    registry_url: str = "",
    token: str = "",
) -> ServiceRegistryClient:
    """
    获取全局注册中心客户端单例。

    Args:
        mode: 模式 ("memory" 或 "remote")
        registry_url: 远程注册中心地址
        token: 服务间认证 token

    Returns:
        ServiceRegistryClient 实例
    """
    global _registry_client
    if _registry_client is None:
        with _registry_lock:
            if _registry_client is None:
                _registry_client = ServiceRegistryClient(
                    mode=mode,
                    registry_url=registry_url,
                    token=token,
                )
    return _registry_client


def reset_registry_client() -> None:
    """重置注册中心客户端（测试用）"""
    global _registry_client
    with _registry_lock:
        if _registry_client:
            _registry_client.close()
        _registry_client = None


# ============================================================
# 模块导出
# ============================================================

__all__ = [
    "ServiceRegistryClient",
    "InMemoryRegistry",
    "RemoteRegistryClient",
    "get_registry_client",
    "reset_registry_client",
]
