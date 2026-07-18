"""
云汐系统模块间通信 SDK - 统一模块客户端
==========================================

像调用本地函数一样调用其他模块的接口。

核心能力：
1. 自动服务发现 - 从注册中心获取模块地址
2. 负载均衡 - 多实例时轮询/随机/加权
3. 故障转移 - 实例失败时自动切换
4. 自动重试 - 可配置重试次数和退避策略
5. 熔断机制 - 连续失败时熔断，避免雪崩
6. 统一请求格式 - 统一的请求/响应包装
7. 超时控制 - 可配置超时时间
8. 链路追踪 - 自动注入 trace_id
9. 认证自动处理 - 自动带上服务间认证 token

使用方式：
    from shared.module_sdk.module_client import ModuleClient

    client = ModuleClient("m1")
    result = await client.get("/users", params={"page": 1})
    result = await client.post("/orders", data={"product_id": 123})
"""

from __future__ import annotations

import sys
import time
import uuid
import asyncio
import random
import hashlib
import threading
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

# 确保可以导入 shared 包
_shared_parent = Path(__file__).resolve().parent.parent.parent
if str(_shared_parent) not in sys.path:
    sys.path.insert(0, str(_shared_parent))

from .models import (
    ApiResponse,
    ServiceInstance,
    ServiceStatus,
    LoadBalanceStrategy,
    CircuitState,
    SdkErrorCode,
)
from .registry import get_registry_client, ServiceRegistryClient

logger = logging.getLogger(__name__)


# ============================================================
# 熔断器
# ============================================================

class CircuitBreaker:
    """
    熔断器实现。

    状态转换：
    CLOSED -> OPEN（失败次数超过阈值）
    OPEN -> HALF_OPEN（冷却时间过后）
    HALF_OPEN -> CLOSED（探测成功）
    HALF_OPEN -> OPEN（探测失败）
    """

    def __init__(
        self,
        name: str = "default",
        failure_threshold: int = 5,
        recovery_timeout: float = 30.0,
        half_open_max_calls: int = 1,
    ):
        self.name = name
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self.half_open_max_calls = half_open_max_calls

        self._state = CircuitState.CLOSED
        self._failure_count = 0
        self._success_count = 0
        self._last_failure_time: float = 0.0
        self._half_open_calls = 0
        self._lock = threading.RLock()

    @property
    def state(self) -> CircuitState:
        """当前状态"""
        return self._state

    def allow_request(self) -> bool:
        """
        检查是否允许请求通过。

        Returns:
            True 表示允许，False 表示熔断
        """
        with self._lock:
            if self._state == CircuitState.CLOSED:
                return True

            if self._state == CircuitState.OPEN:
                # 检查是否过了冷却时间
                if time.time() - self._last_failure_time >= self.recovery_timeout:
                    self._state = CircuitState.HALF_OPEN
                    self._half_open_calls = 1  # 首次探测请求计数
                    self._success_count = 0
                    logger.info("Circuit breaker '%s' transitioning to HALF_OPEN", self.name)
                    return True
                return False

            if self._state == CircuitState.HALF_OPEN:
                if self._half_open_calls < self.half_open_max_calls:
                    self._half_open_calls += 1
                    return True
                return False

            return True

    def record_success(self) -> None:
        """记录成功"""
        with self._lock:
            if self._state == CircuitState.HALF_OPEN:
                self._success_count += 1
                if self._success_count >= self.half_open_max_calls:
                    self._state = CircuitState.CLOSED
                    self._failure_count = 0
                    self._success_count = 0
                    logger.info("Circuit breaker '%s' recovered, transitioning to CLOSED", self.name)
            elif self._state == CircuitState.CLOSED:
                # 成功时缓慢减少失败计数
                if self._failure_count > 0:
                    self._failure_count = max(0, self._failure_count - 1)

    def record_failure(self) -> None:
        """记录失败"""
        with self._lock:
            self._last_failure_time = time.time()

            if self._state == CircuitState.CLOSED:
                self._failure_count += 1
                if self._failure_count >= self.failure_threshold:
                    self._state = CircuitState.OPEN
                    logger.warning(
                        "Circuit breaker '%s' opened after %d failures",
                        self.name, self._failure_count,
                    )
            elif self._state == CircuitState.HALF_OPEN:
                self._state = CircuitState.OPEN
                logger.warning(
                    "Circuit breaker '%s' returned to OPEN after half-open failure",
                    self.name,
                )

    def reset(self) -> None:
        """重置熔断器"""
        with self._lock:
            self._state = CircuitState.CLOSED
            self._failure_count = 0
            self._success_count = 0
            self._last_failure_time = 0.0
            self._half_open_calls = 0

    def get_stats(self) -> Dict[str, Any]:
        """获取熔断器统计"""
        with self._lock:
            return {
                "state": self._state.value,
                "failure_count": self._failure_count,
                "success_count": self._success_count,
                "last_failure_time": self._last_failure_time,
                "failure_threshold": self.failure_threshold,
                "recovery_timeout": self.recovery_timeout,
            }


# ============================================================
# 负载均衡器
# ============================================================

class LoadBalancer:
    """
    负载均衡器。

    支持多种策略：轮询、随机、加权轮询、最少连接、一致性哈希。
    """

    def __init__(self, strategy: LoadBalanceStrategy = LoadBalanceStrategy.ROUND_ROBIN):
        self.strategy = strategy
        self._instances: List[ServiceInstance] = []
        self._round_robin_index = 0
        self._weighted_index = 0
        self._weighted_current_weight = 0
        self._lock = threading.RLock()
        # 一致性哈希环
        self._hash_ring: List[tuple[int, ServiceInstance]] = []
        self._hash_replicas = 100

    def update_instances(self, instances: List[ServiceInstance]) -> None:
        """更新实例列表"""
        with self._lock:
            self._instances = list(instances)
            self._round_robin_index = 0
            self._rebuild_hash_ring()

    def select_instance(self, hash_key: str = "") -> Optional[ServiceInstance]:
        """
        选择一个实例。

        Args:
            hash_key: 一致性哈希时使用的 key

        Returns:
            选中的实例，或 None 如果没有可用实例
        """
        with self._lock:
            if not self._instances:
                return None

            if self.strategy == LoadBalanceStrategy.ROUND_ROBIN:
                instance = self._instances[self._round_robin_index % len(self._instances)]
                self._round_robin_index += 1
                return instance

            elif self.strategy == LoadBalanceStrategy.RANDOM:
                return random.choice(self._instances)

            elif self.strategy == LoadBalanceStrategy.WEIGHTED_ROUND_ROBIN:
                return self._weighted_round_robin()

            elif self.strategy == LoadBalanceStrategy.LEAST_CONNECTIONS:
                # 简化实现：随机选一个（内存中无真实连接数）
                return random.choice(self._instances)

            elif self.strategy == LoadBalanceStrategy.CONSISTENT_HASH:
                return self._consistent_hash(hash_key)

            else:
                return random.choice(self._instances)

    def _weighted_round_robin(self) -> ServiceInstance:
        """加权轮询"""
        total_weight = sum(i.weight for i in self._instances)
        if total_weight <= 0:
            return self._instances[self._round_robin_index % len(self._instances)]

        # 经典加权轮询算法
        self._weighted_current_weight += 1
        if self._weighted_current_weight > total_weight:
            self._weighted_current_weight = 1
            self._weighted_index = (self._weighted_index + 1) % len(self._instances)

        # 简化版：按权重累加选择
        acc = 0
        target = self._weighted_current_weight
        for inst in self._instances:
            acc += inst.weight
            if target <= acc:
                return inst

        return self._instances[-1]

    def _consistent_hash(self, key: str) -> ServiceInstance:
        """一致性哈希"""
        if not self._hash_ring:
            return self._instances[0] if self._instances else None

        if not key:
            key = str(time.time())

        h = int(hashlib.md5(key.encode()).hexdigest(), 16)
        for hash_val, inst in self._hash_ring:
            if hash_val >= h:
                return inst

        # 绕回第一个
        return self._hash_ring[0][1]

    def _rebuild_hash_ring(self) -> None:
        """重建一致性哈希环"""
        self._hash_ring = []
        for inst in self._instances:
            for i in range(self._hash_replicas):
                key = f"{inst.instance_id}:{i}"
                h = int(hashlib.md5(key.encode()).hexdigest(), 16)
                self._hash_ring.append((h, inst))
        self._hash_ring.sort(key=lambda x: x[0])

    @property
    def instance_count(self) -> int:
        """实例数量"""
        with self._lock:
            return len(self._instances)


# ============================================================
# 统一模块客户端
# ============================================================

class ModuleClient:
    """
    统一模块调用客户端。

    像调用本地函数一样调用其他模块的接口。
    集成服务发现、负载均衡、故障转移、自动重试、熔断等能力。
    """

    def __init__(
        self,
        module_name: str,
        config: Optional[Dict[str, Any]] = None,
        registry: Optional[ServiceRegistryClient] = None,
    ):
        """
        初始化模块客户端。

        Args:
            module_name: 模块名（如 "m1", "m8"）
            config: 配置字典
            registry: 注册中心客户端实例，None 时使用全局单例
        """
        self.module_name = module_name.lower()
        self._config = config or {}

        # 配置
        self.timeout = float(self._config.get("timeout", 10.0))
        self.max_retries = int(self._config.get("max_retries", 2))
        self.retry_backoff = float(self._config.get("retry_backoff", 0.5))
        self.retry_backoff_multiplier = float(self._config.get("retry_backoff_multiplier", 2.0))
        self.load_balance_strategy = LoadBalanceStrategy(
            self._config.get("load_balance_strategy", "round_robin")
        )
        self.circuit_breaker_enabled = bool(self._config.get("circuit_breaker_enabled", True))
        self.circuit_failure_threshold = int(self._config.get("circuit_failure_threshold", 5))
        self.circuit_recovery_timeout = float(self._config.get("circuit_recovery_timeout", 30.0))
        self.service_discovery_enabled = bool(self._config.get("service_discovery_enabled", True))
        self.auth_token = self._config.get("auth_token", "")
        self.default_base_url = self._config.get("base_url", self._config.get("default_base_url", ""))

        # 注册中心
        self._registry = registry

        # 负载均衡器
        self._load_balancer = LoadBalancer(self.load_balance_strategy)
        self._last_discover_time = 0.0
        self._discover_cache_ttl = float(self._config.get("discover_cache_ttl", 5.0))

        # 熔断器（按服务名）
        self._circuit_breakers: Dict[str, CircuitBreaker] = {}
        self._cb_lock = threading.RLock()

        # HTTP 客户端（延迟创建）
        self._httpx_client: Optional[Any] = None

        # 故障实例黑名单
        self._blacklisted_instances: Dict[str, float] = {}  # instance_id -> 恢复时间
        self._blacklist_timeout = float(self._config.get("blacklist_timeout", 30.0))

    # ------------------------------------------------------------------
    #  服务发现
    # ------------------------------------------------------------------

    def _get_registry(self) -> ServiceRegistryClient:
        """获取注册中心客户端"""
        if self._registry is None:
            self._registry = get_registry_client()
        return self._registry

    def _discover_instances(self, force: bool = False) -> List[ServiceInstance]:
        """
        发现服务实例。

        Args:
            force: 是否强制刷新缓存

        Returns:
            健康实例列表
        """
        if not self.service_discovery_enabled:
            return []

        now = time.time()
        if not force and now - self._last_discover_time < self._discover_cache_ttl:
            # 使用缓存
            pass
        else:
            try:
                registry = self._get_registry()
                instances = registry.discover(self.module_name)
                self._load_balancer.update_instances(instances)
                self._last_discover_time = now
            except Exception as e:
                logger.warning("Service discovery failed for %s: %s", self.module_name, e)

        return self._load_balancer._instances

    def _select_instance(self, hash_key: str = "") -> Optional[ServiceInstance]:
        """
        选择一个健康实例。

        Returns:
            选中的实例，或 None
        """
        # 先清理过期黑名单
        self._clean_blacklist()

        # 发现实例
        instances = self._discover_instances()
        if not instances:
            return None

        # 过滤掉黑名单中的实例
        healthy = [i for i in instances if i.instance_id not in self._blacklisted_instances]
        if not healthy:
            # 所有实例都在黑名单中，强制刷新并尝试
            instances = self._discover_instances(force=True)
            healthy = [i for i in instances if i.instance_id not in self._blacklisted_instances]
            if not healthy and instances:
                # 实在没有就从黑名单里选一个（降级）
                healthy = list(instances)

        if not healthy:
            return None

        # 使用负载均衡器选择（更新负载均衡器的实例列表为健康实例）
        self._load_balancer.update_instances(healthy)
        return self._load_balancer.select_instance(hash_key)

    def _blacklist_instance(self, instance_id: str) -> None:
        """将实例加入黑名单"""
        self._blacklisted_instances[instance_id] = time.time() + self._blacklist_timeout
        logger.debug("Instance blacklisted: %s (%.1fs)", instance_id, self._blacklist_timeout)

    def _clean_blacklist(self) -> None:
        """清理过期的黑名单"""
        now = time.time()
        expired = [iid for iid, t in self._blacklisted_instances.items() if t <= now]
        for iid in expired:
            del self._blacklisted_instances[iid]

    # ------------------------------------------------------------------
    # 熔断器管理
    # ------------------------------------------------------------------

    def _get_circuit_breaker(self, instance_id: str) -> CircuitBreaker:
        """获取实例的熔断器"""
        with self._cb_lock:
            if instance_id not in self._circuit_breakers:
                self._circuit_breakers[instance_id] = CircuitBreaker(
                    name=f"{self.module_name}/{instance_id}",
                    failure_threshold=self.circuit_failure_threshold,
                    recovery_timeout=self.circuit_recovery_timeout,
                )
            return self._circuit_breakers[instance_id]

    # ------------------------------------------------------------------
    # HTTP 客户端
    # ------------------------------------------------------------------

    def _get_httpx_client(self):
        """延迟获取 httpx 客户端"""
        if self._httpx_client is None:
            import httpx
            self._httpx_client = httpx.AsyncClient(timeout=self.timeout)
        return self._httpx_client

    def _build_headers(self, trace_id: str = "") -> Dict[str, str]:
        """构建请求头"""
        headers = {
            "Content-Type": "application/json",
            "X-Module-Client": "yunxi-sdk",
        }
        if trace_id:
            headers["X-Trace-Id"] = trace_id
        if self.auth_token:
            headers["Authorization"] = f"Bearer {self.auth_token}"
            headers["X-Service-Token"] = self.auth_token
        return headers

    # ------------------------------------------------------------------
    #  核心调用方法
    # ------------------------------------------------------------------

    async def call(
        self,
        endpoint: str,
        method: str = "GET",
        data: Optional[Dict[str, Any]] = None,
        params: Optional[Dict[str, Any]] = None,
        trace_id: str = "",
        hash_key: str = "",
    ) -> ApiResponse:
        """
        调用模块接口。

        Args:
            endpoint: 接口路径（如 "/users"）
            method: HTTP 方法
            data: 请求体数据
            params: 查询参数
            trace_id: 链路追踪 ID（自动生成如果为空）
            hash_key: 一致性哈希 key

        Returns:
            ApiResponse 统一响应
        """
        if not trace_id:
            trace_id = str(uuid.uuid4())

        method = method.upper()
        endpoint = endpoint if endpoint.startswith("/") else f"/{endpoint}"

        last_error: Optional[Exception] = None
        backoff = self.retry_backoff

        for attempt in range(self.max_retries + 1):
            # 选择实例
            instance = self._select_instance(hash_key=hash_key)

            if instance is None:
                # 尝试使用默认 base_url（如果配置了）
                if self.default_base_url:
                    base_url = self.default_base_url.rstrip("/")
                    instance_id = "default"
                else:
                    # 没有可用实例
                    return ApiResponse.error(
                        code=SdkErrorCode.NO_HEALTHY_INSTANCE,
                        message=f"No healthy instance found for module: {self.module_name}",
                        trace_id=trace_id,
                    )
            else:
                base_url = instance.base_url
                instance_id = instance.instance_id

            # 检查熔断器
            if self.circuit_breaker_enabled and instance_id != "default":
                cb = self._get_circuit_breaker(instance_id)
                if not cb.allow_request():
                    logger.debug("Circuit open for %s, trying next instance", instance_id)
                    # 熔断了，标记失败并尝试下一个实例
                    last_error = Exception(f"Circuit breaker open: {instance_id}")
                    continue

            # 发起请求
            try:
                result = await self._do_request(
                    base_url=base_url,
                    endpoint=endpoint,
                    method=method,
                    data=data,
                    params=params,
                    headers=self._build_headers(trace_id),
                )

                # 记录成功
                if self.circuit_breaker_enabled and instance_id != "default":
                    cb = self._get_circuit_breaker(instance_id)
                    cb.record_success()

                # 解析响应
                if isinstance(result, dict) and "code" in result:
                    return ApiResponse.from_dict(result)
                else:
                    # 非标准响应，包装成 ApiResponse
                    return ApiResponse.success(data=result, trace_id=trace_id)

            except Exception as e:
                last_error = e
                logger.debug(
                    "Call failed (attempt %d/%d) to %s/%s: %s",
                    attempt + 1, self.max_retries + 1,
                    self.module_name, endpoint, e,
                )

                # 记录失败
                if self.circuit_breaker_enabled and instance_id != "default":
                    cb = self._get_circuit_breaker(instance_id)
                    cb.record_failure()
                    # 加入黑名单
                    self._blacklist_instance(instance_id)

                # 最后一次重试不再等待
                if attempt < self.max_retries:
                    await asyncio.sleep(backoff)
                    backoff *= self.retry_backoff_multiplier

        # 所有重试失败
        return ApiResponse.error(
            code=SdkErrorCode.CALL_RETRY_EXHAUSTED,
            message=f"Call failed after {self.max_retries + 1} attempts: {last_error}",
            data={"error": str(last_error)} if last_error else None,
            trace_id=trace_id,
        )

    async def _do_request(
        self,
        base_url: str,
        endpoint: str,
        method: str,
        data: Optional[Dict[str, Any]],
        params: Optional[Dict[str, Any]],
        headers: Dict[str, str],
    ) -> Any:
        """执行实际的 HTTP 请求"""
        client = self._get_httpx_client()
        url = f"{base_url}{endpoint}"

        request_kwargs: Dict[str, Any] = {
            "headers": headers,
            "params": params,
            "timeout": self.timeout,
        }

        if data is not None and method in ("POST", "PUT", "PATCH"):
            request_kwargs["json"] = data

        response = await client.request(method, url, **request_kwargs)
        response.raise_for_status()

        try:
            return response.json()
        except Exception:
            return {"raw_text": response.text, "status": response.status_code}

    # ------------------------------------------------------------------
    #  便捷方法
    # ------------------------------------------------------------------

    async def get(
        self,
        endpoint: str,
        params: Optional[Dict[str, Any]] = None,
        trace_id: str = "",
    ) -> ApiResponse:
        """GET 请求"""
        return await self.call(endpoint, "GET", params=params, trace_id=trace_id)

    async def post(
        self,
        endpoint: str,
        data: Optional[Dict[str, Any]] = None,
        trace_id: str = "",
    ) -> ApiResponse:
        """POST 请求"""
        return await self.call(endpoint, "POST", data=data, trace_id=trace_id)

    async def put(
        self,
        endpoint: str,
        data: Optional[Dict[str, Any]] = None,
        trace_id: str = "",
    ) -> ApiResponse:
        """PUT 请求"""
        return await self.call(endpoint, "PUT", data=data, trace_id=trace_id)

    async def delete(
        self,
        endpoint: str,
        params: Optional[Dict[str, Any]] = None,
        trace_id: str = "",
    ) -> ApiResponse:
        """DELETE 请求"""
        return await self.call(endpoint, "DELETE", params=params, trace_id=trace_id)

    # ------------------------------------------------------------------
    #  状态与管理
    # ------------------------------------------------------------------

    def get_circuit_breaker_stats(self) -> Dict[str, Any]:
        """获取熔断器状态"""
        with self._cb_lock:
            return {
                iid: cb.get_stats()
                for iid, cb in self._circuit_breakers.items()
            }

    def reset_circuit_breakers(self) -> None:
        """重置所有熔断器"""
        with self._cb_lock:
            for cb in self._circuit_breakers.values():
                cb.reset()

    def clear_blacklist(self) -> None:
        """清空实例黑名单"""
        self._blacklisted_instances.clear()

    def force_discover(self) -> List[ServiceInstance]:
        """强制刷新服务发现"""
        return self._discover_instances(force=True)

    async def close(self) -> None:
        """关闭客户端"""
        if self._httpx_client:
            try:
                await self._httpx_client.aclose()
            except Exception:
                pass
            self._httpx_client = None


# ============================================================
# 模块导出
# ============================================================

__all__ = [
    "ModuleClient",
    "CircuitBreaker",
    "LoadBalancer",
]
