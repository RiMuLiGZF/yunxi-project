"""
云汐 API 网关 - 权重路由 / 灰度发布

功能：
1. 按权重将流量分配到多个后端实例
2. 支持基于用户 ID 的一致性哈希（同一用户始终打到同一后端）
3. 灰度发布场景：新版本 10% 流量，旧版本 90% 流量
"""
import hashlib
import threading
import random
from typing import List, Optional, Dict, Any
from dataclasses import dataclass, field


@dataclass
class RouteTarget:
    """路由目标（后端实例）

    Attributes:
        url: 后端服务地址
        weight: 权重（0-100），权重越大分配的流量越多
        name: 目标名称（如 v1, v2, canary）
        healthy: 是否健康
    """
    url: str
    weight: int = 50
    name: str = ""
    healthy: bool = True

    def __post_init__(self):
        if not self.name:
            self.name = self.url


class WeightedRouter:
    """权重路由器

    支持两种路由策略：
    1. 权重轮询 - 按权重比例随机分配
    2. 一致性哈希 - 基于用户 ID 的一致性哈希，同一用户始终打到同一后端
    """

    def __init__(self, targets: Optional[List[RouteTarget]] = None):
        """
        Args:
            targets: 后端目标列表
        """
        self._targets: List[RouteTarget] = targets or []
        self._lock = threading.Lock()
        self._stats: Dict[str, Dict[str, Any]] = {}
        self._build_weighted_list()

    def _build_weighted_list(self):
        """构建权重列表（用于快速随机选择）"""
        self._weighted_targets: List[RouteTarget] = []
        healthy_targets = [t for t in self._targets if t.healthy]
        total_weight = sum(t.weight for t in healthy_targets)

        if total_weight == 0:
            return

        # 使用权重构建扩展列表（最多100个元素，保证精度）
        scale = 100 / total_weight if total_weight > 0 else 1
        for target in healthy_targets:
            count = max(1, int(round(target.weight * scale)))
            self._weighted_targets.extend([target] * count)

    def set_targets(self, targets: List[RouteTarget]):
        """设置目标列表"""
        with self._lock:
            self._targets = targets
            self._build_weighted_list()

    def add_target(self, target: RouteTarget):
        """添加目标"""
        with self._lock:
            # 移除同名目标（如果存在）
            self._targets = [t for t in self._targets if t.name != target.name]
            self._targets.append(target)
            self._build_weighted_list()

    def remove_target(self, name: str) -> bool:
        """移除目标"""
        with self._lock:
            original_len = len(self._targets)
            self._targets = [t for t in self._targets if t.name != name]
            if len(self._targets) != original_len:
                self._build_weighted_list()
                return True
            return False

    def update_target_health(self, name: str, healthy: bool) -> bool:
        """更新目标健康状态"""
        with self._lock:
            for target in self._targets:
                if target.name == name:
                    target.healthy = healthy
                    self._build_weighted_list()
                    return True
            return False

    def select_target(self, user_id: Optional[str] = None) -> Optional[RouteTarget]:
        """选择一个后端目标

        Args:
            user_id: 用户 ID（提供时使用一致性哈希策略）

        Returns:
            选中的目标，无可用目标时返回 None
        """
        with self._lock:
            if not self._weighted_targets:
                return None

            if user_id:
                # 一致性哈希：同一用户始终打到同一后端
                return self._consistent_hash_select(user_id)
            else:
                # 权重随机
                return random.choice(self._weighted_targets)

    def _consistent_hash_select(self, user_id: str) -> Optional[RouteTarget]:
        """基于用户 ID 的一致性哈希选择

        使用一致性哈希确保同一用户始终路由到同一后端，
        当后端列表变化时，尽量减少用户的重新分配。
        """
        healthy_targets = [t for t in self._targets if t.healthy]
        if not healthy_targets:
            return None

        # 使用虚拟节点提高分布均匀性
        virtual_nodes = 100
        ring: Dict[int, RouteTarget] = {}

        for target in healthy_targets:
            for i in range(virtual_nodes):
                key = f"{target.name}-{i}"
                hash_val = int(hashlib.md5(key.encode()).hexdigest(), 16)
                ring[hash_val] = target

        if not ring:
            return None

        # 计算用户哈希
        user_hash = int(hashlib.md5(user_id.encode()).hexdigest(), 16)

        # 在环上查找最近的节点
        sorted_keys = sorted(ring.keys())
        for key in sorted_keys:
            if key >= user_hash:
                return ring[key]

        # 绕回第一个节点
        return ring[sorted_keys[0]]

    def get_targets(self) -> List[Dict[str, Any]]:
        """获取所有目标信息"""
        with self._lock:
            return [
                {
                    "name": t.name,
                    "url": t.url,
                    "weight": t.weight,
                    "healthy": t.healthy,
                }
                for t in self._targets
            ]

    def get_stats(self) -> Dict[str, Any]:
        """获取路由统计"""
        with self._lock:
            healthy = sum(1 for t in self._targets if t.healthy)
            total_weight = sum(t.weight for t in self._targets if t.healthy)
            return {
                "total_targets": len(self._targets),
                "healthy_targets": healthy,
                "unhealthy_targets": len(self._targets) - healthy,
                "total_weight": total_weight,
                "targets": [
                    {
                        "name": t.name,
                        "url": t.url,
                        "weight": t.weight,
                        "weight_percent": round(
                            t.weight / total_weight * 100, 2
                        ) if total_weight > 0 else 0,
                        "healthy": t.healthy,
                    }
                    for t in self._targets
                ],
            }

    def validate(self) -> bool:
        """验证配置是否有效"""
        if not self._targets:
            return False
        # 至少有一个健康的目标
        if not any(t.healthy for t in self._targets):
            return False
        # 权重必须为正
        if any(t.weight < 0 for t in self._targets):
            return False
        return True
