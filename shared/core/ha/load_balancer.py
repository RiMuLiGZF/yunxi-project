"""
云汐负载均衡模块 (Load Balancer)

提供多种负载均衡策略：
- 轮询 (Round Robin)
- 加权轮询 (Weighted Round Robin)
- 最少连接 (Least Connections)
- 最快响应 (Fastest Response)
- 一致性哈希 (Consistent Hash)

支持动态增删实例、健康实例过滤、权重调整。

使用方式：
    from shared.core.ha.load_balancer import create_load_balancer, LoadBalanceStrategy

    lb = create_load_balancer(LoadBalanceStrategy.ROUND_ROBIN)
    lb.add_instance("server1", "http://127.0.0.1:8001", weight=3)
    lb.add_instance("server2", "http://127.0.0.1:8002", weight=1)
    instance = lb.next_instance()
"""

from __future__ import annotations

import time
import hashlib
import threading
import logging
from enum import Enum
from dataclasses import dataclass, field
from typing import Dict, Any, Optional, List, Callable
from collections import defaultdict

logger = logging.getLogger(__name__)


# ============================================================
# 枚举与常量
# ============================================================

class LoadBalanceStrategy(str, Enum):
    """负载均衡策略"""
    ROUND_ROBIN = "round_robin"                 # 轮询
    WEIGHTED_ROUND_ROBIN = "weighted_round_robin"  # 加权轮询
    LEAST_CONNECTIONS = "least_connections"     # 最少连接
    FASTEST_RESPONSE = "fastest_response"       # 最快响应
    CONSISTENT_HASH = "consistent_hash"         # 一致性哈希


class InstanceStatus(str, Enum):
    """实例状态"""
    HEALTHY = "healthy"
    UNHEALTHY = "unhealthy"
    DRAINING = "draining"  # 正在排空（不再接受新请求）


# ============================================================
# 数据类
# ============================================================

@dataclass
class ServiceInstance:
    """服务实例"""
    instance_id: str
    address: str               # 服务地址（URL 或 host:port）
    weight: int = 1            # 权重（加权轮询使用）
    status: InstanceStatus = InstanceStatus.HEALTHY
    active_connections: int = 0  # 当前活跃连接数
    total_requests: int = 0      # 总请求数
    total_errors: int = 0        # 总错误数
    avg_response_time_ms: float = 0.0  # 平均响应时间
    last_response_time_ms: float = 0.0  # 最近响应时间
    last_used_at: float = 0.0       # 最后使用时间
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "instance_id": self.instance_id,
            "address": self.address,
            "weight": self.weight,
            "status": self.status.value,
            "active_connections": self.active_connections,
            "total_requests": self.total_requests,
            "total_errors": self.total_errors,
            "avg_response_time_ms": round(self.avg_response_time_ms, 2),
            "last_response_time_ms": round(self.last_response_time_ms, 2),
            "last_used_at": self.last_used_at,
            "metadata": self.metadata,
        }


# ============================================================
# 负载均衡基类
# ============================================================

class LoadBalancer:
    """
    负载均衡器基类

    提供实例管理、健康过滤、统计等通用能力。
    具体策略由子类实现 next_instance() 方法。
    """

    strategy: LoadBalanceStrategy = LoadBalanceStrategy.ROUND_ROBIN

    def __init__(self, service_name: str = "default"):
        self.service_name = service_name
        self._instances: Dict[str, ServiceInstance] = {}
        self._lock = threading.RLock()

    # ------------------------------------------------------------------
    #  实例管理
    # ------------------------------------------------------------------

    def add_instance(
        self,
        instance_id: str,
        address: str,
        weight: int = 1,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> bool:
        """添加服务实例"""
        with self._lock:
            if instance_id in self._instances:
                logger.warning("Instance already exists: %s", instance_id)
                return False

            instance = ServiceInstance(
                instance_id=instance_id,
                address=address,
                weight=max(1, weight),
                metadata=metadata or {},
            )
            self._instances[instance_id] = instance
            self._on_instance_added(instance)
            logger.info("Instance added: %s (%s), weight=%d", instance_id, address, weight)
            return True

    def remove_instance(self, instance_id: str) -> bool:
        """移除服务实例"""
        with self._lock:
            if instance_id not in self._instances:
                return False

            instance = self._instances.pop(instance_id)
            self._on_instance_removed(instance)
            logger.info("Instance removed: %s", instance_id)
            return True

    def update_instance_weight(self, instance_id: str, weight: int) -> bool:
        """更新实例权重"""
        with self._lock:
            instance = self._instances.get(instance_id)
            if instance is None:
                return False
            instance.weight = max(1, weight)
            self._on_weight_changed(instance)
            logger.info("Instance weight updated: %s -> %d", instance_id, weight)
            return True

    def set_instance_status(self, instance_id: str, status: InstanceStatus) -> bool:
        """设置实例状态"""
        with self._lock:
            instance = self._instances.get(instance_id)
            if instance is None:
                return False
            instance.status = status
            logger.info("Instance status changed: %s -> %s", instance_id, status.value)
            return True

    def mark_healthy(self, instance_id: str) -> bool:
        """标记实例健康"""
        return self.set_instance_status(instance_id, InstanceStatus.HEALTHY)

    def mark_unhealthy(self, instance_id: str) -> bool:
        """标记实例不健康"""
        return self.set_instance_status(instance_id, InstanceStatus.UNHEALTHY)

    def drain_instance(self, instance_id: str) -> bool:
        """开始排空实例（不再接受新请求）"""
        return self.set_instance_status(instance_id, InstanceStatus.DRAINING)

    # ------------------------------------------------------------------
    #  请求统计
    # ------------------------------------------------------------------

    def record_request(self, instance_id: str, response_time_ms: float, success: bool = True) -> None:
        """记录一次请求结果（用于统计）"""
        with self._lock:
            instance = self._instances.get(instance_id)
            if instance is None:
                return

            instance.total_requests += 1
            instance.last_response_time_ms = response_time_ms
            instance.last_used_at = time.time()

            # 更新平均响应时间（指数加权移动平均）
            if instance.avg_response_time_ms == 0:
                instance.avg_response_time_ms = response_time_ms
            else:
                alpha = 0.3
                instance.avg_response_time_ms = (
                    alpha * response_time_ms + (1 - alpha) * instance.avg_response_time_ms
                )

            if not success:
                instance.total_errors += 1

    def increment_connection(self, instance_id: str) -> None:
        """增加活跃连接计数"""
        with self._lock:
            instance = self._instances.get(instance_id)
            if instance:
                instance.active_connections += 1

    def decrement_connection(self, instance_id: str) -> None:
        """减少活跃连接计数"""
        with self._lock:
            instance = self._instances.get(instance_id)
            if instance and instance.active_connections > 0:
                instance.active_connections -= 1

    # ------------------------------------------------------------------
    #  核心方法：选择实例（子类实现）
    # ------------------------------------------------------------------

    def next_instance(self, key: Optional[str] = None) -> Optional[ServiceInstance]:
        """
        选择下一个服务实例

        Args:
            key: 一致性哈希等策略使用的 key

        Returns:
            选中的实例，或 None（没有可用实例）
        """
        raise NotImplementedError("Subclasses must implement next_instance()")

    # ------------------------------------------------------------------
    #  辅助方法
    # ------------------------------------------------------------------

    def _get_healthy_instances(self) -> List[ServiceInstance]:
        """获取所有健康的实例列表"""
        return [
            inst for inst in self._instances.values()
            if inst.status == InstanceStatus.HEALTHY
        ]

    def _on_instance_added(self, instance: ServiceInstance) -> None:
        """实例添加回调（子类可重写）"""
        pass

    def _on_instance_removed(self, instance: ServiceInstance) -> None:
        """实例移除回调（子类可重写）"""
        pass

    def _on_weight_changed(self, instance: ServiceInstance) -> None:
        """权重变化回调（子类可重写）"""
        pass

    # ------------------------------------------------------------------
    #  查询接口
    # ------------------------------------------------------------------

    def get_instance(self, instance_id: str) -> Optional[ServiceInstance]:
        """获取指定实例"""
        with self._lock:
            return self._instances.get(instance_id)

    def get_all_instances(self) -> List[ServiceInstance]:
        """获取所有实例列表"""
        with self._lock:
            return list(self._instances.values())

    def get_healthy_instances(self) -> List[ServiceInstance]:
        """获取健康实例列表"""
        with self._lock:
            return self._get_healthy_instances()

    def get_instance_count(self) -> int:
        """获取实例总数"""
        with self._lock:
            return len(self._instances)

    def get_healthy_count(self) -> int:
        """获取健康实例数"""
        with self._lock:
            return len(self._get_healthy_instances())

    def has_healthy_instance(self) -> bool:
        """是否有健康实例"""
        with self._lock:
            return len(self._get_healthy_instances()) > 0

    def get_stats(self) -> Dict[str, Any]:
        """获取负载均衡统计"""
        with self._lock:
            instances = [inst.to_dict() for inst in self._instances.values()]
            total_requests = sum(inst.total_requests for inst in self._instances.values())
            total_errors = sum(inst.total_errors for inst in self._instances.values())

        return {
            "service_name": self.service_name,
            "strategy": self.strategy.value,
            "instance_count": len(instances),
            "healthy_count": sum(1 for i in instances if i["status"] == "healthy"),
            "total_requests": total_requests,
            "total_errors": total_errors,
            "error_rate": round(total_errors / total_requests * 100, 2) if total_requests > 0 else 0,
            "instances": instances,
        }


# ============================================================
# 轮询负载均衡
# ============================================================

class RoundRobinBalancer(LoadBalancer):
    """轮询负载均衡器"""

    strategy = LoadBalanceStrategy.ROUND_ROBIN

    def __init__(self, service_name: str = "default"):
        super().__init__(service_name)
        self._index = 0

    def next_instance(self, key: Optional[str] = None) -> Optional[ServiceInstance]:
        with self._lock:
            healthy = self._get_healthy_instances()
            if not healthy:
                return None

            # 按实例ID排序，确保顺序稳定
            healthy.sort(key=lambda i: i.instance_id)

            if self._index >= len(healthy):
                self._index = 0

            instance = healthy[self._index]
            self._index = (self._index + 1) % len(healthy)
            return instance

    def _on_instance_removed(self, instance: ServiceInstance) -> None:
        # 移除实例后重置索引，避免越界
        healthy_count = len(self._get_healthy_instances())
        if healthy_count > 0 and self._index >= healthy_count:
            self._index = 0


# ============================================================
# 加权轮询负载均衡
# ============================================================

class WeightedRoundRobinBalancer(LoadBalancer):
    """
    加权轮询负载均衡器

    使用平滑加权轮询算法（Nginx 风格），确保请求分布平滑，
    不会出现某个高权重实例被连续选中的情况。
    """

    strategy = LoadBalanceStrategy.WEIGHTED_ROUND_ROBIN

    def __init__(self, service_name: str = "default"):
        super().__init__(service_name)
        self._current_weights: Dict[str, int] = {}

    def next_instance(self, key: Optional[str] = None) -> Optional[ServiceInstance]:
        with self._lock:
            healthy = self._get_healthy_instances()
            if not healthy:
                return None

            # 初始化当前权重
            for inst in healthy:
                if inst.instance_id not in self._current_weights:
                    self._current_weights[inst.instance_id] = 0

            # 清理已移除实例的权重
            for iid in list(self._current_weights.keys()):
                if iid not in self._instances:
                    del self._current_weights[iid]

            # 平滑加权轮询算法
            total_weight = sum(inst.weight for inst in healthy)
            if total_weight == 0:
                return healthy[0]

            # 每个实例的当前权重 += 其权重
            for inst in healthy:
                self._current_weights[inst.instance_id] += inst.weight

            # 选择当前权重最大的实例
            selected = max(healthy, key=lambda i: self._current_weights[i.instance_id])

            # 选中后，当前权重 -= 总权重
            self._current_weights[selected.instance_id] -= total_weight

            return selected

    def _on_instance_added(self, instance: ServiceInstance) -> None:
        self._current_weights[instance.instance_id] = 0

    def _on_instance_removed(self, instance: ServiceInstance) -> None:
        self._current_weights.pop(instance.instance_id, None)

    def _on_weight_changed(self, instance: ServiceInstance) -> None:
        # 权重变化时重置当前权重，避免累积偏差
        self._current_weights[instance.instance_id] = 0


# ============================================================
# 最少连接负载均衡
# ============================================================

class LeastConnectionsBalancer(LoadBalancer):
    """最少连接负载均衡器"""

    strategy = LoadBalanceStrategy.LEAST_CONNECTIONS

    def next_instance(self, key: Optional[str] = None) -> Optional[ServiceInstance]:
        with self._lock:
            healthy = self._get_healthy_instances()
            if not healthy:
                return None

            # 选择活跃连接最少的实例，相同则按总请求数少的优先
            selected = min(
                healthy,
                key=lambda i: (i.active_connections, i.total_requests, i.instance_id),
            )
            return selected


# ============================================================
# 最快响应负载均衡
# ============================================================

class FastestResponseBalancer(LoadBalancer):
    """最快响应负载均衡器"""

    strategy = LoadBalanceStrategy.FASTEST_RESPONSE

    def next_instance(self, key: Optional[str] = None) -> Optional[ServiceInstance]:
        with self._lock:
            healthy = self._get_healthy_instances()
            if not healthy:
                return None

            # 区分有历史数据和无历史数据的实例
            with_data = [i for i in healthy if i.avg_response_time_ms > 0]
            without_data = [i for i in healthy if i.avg_response_time_ms == 0]

            if without_data:
                # 优先选择还没有数据的实例（让每个实例都有机会被探测）
                # 按总请求数最少的优先
                selected = min(without_data, key=lambda i: (i.total_requests, i.instance_id))
                return selected

            # 选择平均响应时间最短的
            selected = min(
                with_data,
                key=lambda i: (i.avg_response_time_ms, i.instance_id),
            )
            return selected


# ============================================================
# 一致性哈希负载均衡
# ============================================================

class ConsistentHashBalancer(LoadBalancer):
    """
    一致性哈希负载均衡器

    使用虚拟节点（vnode）提高分布均匀性。
    相同的 key 总是路由到同一个实例（只要实例列表不变）。
    """

    strategy = LoadBalanceStrategy.CONSISTENT_HASH
    VNODE_COUNT = 150  # 每个实例的虚拟节点数

    def __init__(self, service_name: str = "default"):
        super().__init__(service_name)
        self._ring: List[tuple] = []  # (hash_value, instance_id)
        self._rebuild_ring()

    def next_instance(self, key: Optional[str] = None) -> Optional[ServiceInstance]:
        if key is None:
            # 如果没有 key，退化到轮询
            with self._lock:
                healthy = self._get_healthy_instances()
                if not healthy:
                    return None
                healthy.sort(key=lambda i: i.instance_id)
                return healthy[0]

        with self._lock:
            if not self._ring:
                return None

            hash_value = self._hash(key)

            # 在环上找第一个 >= hash_value 的节点
            for node_hash, instance_id in self._ring:
                if node_hash >= hash_value:
                    instance = self._instances.get(instance_id)
                    if instance and instance.status == InstanceStatus.HEALTHY:
                        return instance
                    # 如果该实例不健康，继续找下一个
                    continue

            # 如果绕了一圈都没找到健康的，从头开始找
            for node_hash, instance_id in self._ring:
                instance = self._instances.get(instance_id)
                if instance and instance.status == InstanceStatus.HEALTHY:
                    return instance

            return None

    def _hash(self, key: str) -> int:
        """计算哈希值（返回 0 - 2^32 范围）"""
        digest = hashlib.md5(key.encode("utf-8")).digest()
        return int.from_bytes(digest[:4], byteorder="big")

    def _rebuild_ring(self) -> None:
        """重建哈希环"""
        ring = []
        for instance_id, instance in self._instances.items():
            for i in range(self.VNODE_COUNT * instance.weight):
                vnode_key = f"{instance_id}#vnode#{i}"
                h = self._hash(vnode_key)
                ring.append((h, instance_id))

        # 按哈希值排序
        ring.sort(key=lambda x: x[0])
        self._ring = ring

    def _on_instance_added(self, instance: ServiceInstance) -> None:
        self._rebuild_ring()

    def _on_instance_removed(self, instance: ServiceInstance) -> None:
        self._rebuild_ring()

    def _on_weight_changed(self, instance: ServiceInstance) -> None:
        self._rebuild_ring()

    def get_ring_stats(self) -> Dict[str, Any]:
        """获取哈希环统计"""
        with self._lock:
            distribution = defaultdict(int)
            for _, instance_id in self._ring:
                distribution[instance_id] += 1

        return {
            "total_vnodes": len(self._ring),
            "distribution": dict(distribution),
        }


# ============================================================
# 工厂函数
# ============================================================

_STRATEGY_MAP = {
    LoadBalanceStrategy.ROUND_ROBIN: RoundRobinBalancer,
    LoadBalanceStrategy.WEIGHTED_ROUND_ROBIN: WeightedRoundRobinBalancer,
    LoadBalanceStrategy.LEAST_CONNECTIONS: LeastConnectionsBalancer,
    LoadBalanceStrategy.FASTEST_RESPONSE: FastestResponseBalancer,
    LoadBalanceStrategy.CONSISTENT_HASH: ConsistentHashBalancer,
}


def create_load_balancer(
    strategy: LoadBalanceStrategy,
    service_name: str = "default",
) -> LoadBalancer:
    """
    创建负载均衡器

    Args:
        strategy: 负载均衡策略
        service_name: 服务名称

    Returns:
        对应的 LoadBalancer 实例
    """
    cls = _STRATEGY_MAP.get(strategy)
    if cls is None:
        raise ValueError(f"Unsupported load balance strategy: {strategy}")
    return cls(service_name)
