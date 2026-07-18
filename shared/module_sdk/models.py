"""
云汐系统模块间通信 SDK - 数据模型
====================================

统一的请求/响应格式、服务实例模型、事件模型、错误码定义。

使用方式：
    from shared.module_sdk.models import (
        ApiResponse,
        ServiceInstance,
        Event,
        SdkErrorCode,
    )
"""

from __future__ import annotations

import time
import uuid
from enum import Enum, IntEnum
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


# ============================================================
# 统一响应格式
# ============================================================

@dataclass
class ApiResponse:
    """
    统一 API 响应格式。

    所有模块间通信都应使用此格式包装响应：
    {
        "code": 0,           # 0 表示成功，非 0 为错误码
        "message": "success",# 描述信息
        "data": {...},       # 业务数据
        "trace_id": "xxx",   # 链路追踪 ID
        "timestamp": 123456  # 时间戳
    }
    """

    code: int = 0
    message: str = "success"
    data: Any = None
    trace_id: str = ""
    timestamp: float = field(default_factory=time.time)

    @property
    def is_success(self) -> bool:
        """是否成功"""
        return self.code == 0

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            "code": self.code,
            "message": self.message,
            "data": self.data,
            "trace_id": self.trace_id,
            "timestamp": self.timestamp,
        }

    @classmethod
    def success(
        cls,
        data: Any = None,
        message: str = "success",
        trace_id: str = "",
    ) -> "ApiResponse":
        """创建成功响应"""
        return cls(code=0, message=message, data=data, trace_id=trace_id)

    @classmethod
    def error(
        cls,
        code: int,
        message: str = "error",
        data: Any = None,
        trace_id: str = "",
    ) -> "ApiResponse":
        """创建错误响应"""
        return cls(code=code, message=message, data=data, trace_id=trace_id)

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "ApiResponse":
        """从字典解析"""
        return cls(
            code=d.get("code", -1),
            message=d.get("message", ""),
            data=d.get("data"),
            trace_id=d.get("trace_id", ""),
            timestamp=d.get("timestamp", time.time()),
        )


# ============================================================
# 服务实例模型
# ============================================================

class ServiceStatus(str, Enum):
    """服务实例状态"""
    HEALTHY = "healthy"
    UNHEALTHY = "unhealthy"
    STARTING = "starting"
    STOPPING = "stopping"
    UNKNOWN = "unknown"


@dataclass
class ServiceInstance:
    """
    服务实例信息。

    用于服务注册与发现，表示一个具体的服务实例。
    """

    service_name: str          # 服务名（如 "m8", "m1"）
    instance_id: str           # 实例唯一 ID
    address: str               # 主机地址
    port: int                  # 端口
    version: str = "1.0.0"     # 版本号
    weight: int = 1            # 权重（负载均衡用）
    status: ServiceStatus = ServiceStatus.HEALTHY
    health_check_url: str = "/health"
    last_heartbeat: float = field(default_factory=time.time)
    metadata: Dict[str, Any] = field(default_factory=dict)

    @property
    def base_url(self) -> str:
        """获取 base URL"""
        return f"http://{self.address}:{self.port}"

    @property
    def is_healthy(self) -> bool:
        """是否健康"""
        return self.status == ServiceStatus.HEALTHY

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            "service_name": self.service_name,
            "instance_id": self.instance_id,
            "address": self.address,
            "port": self.port,
            "base_url": self.base_url,
            "version": self.version,
            "weight": self.weight,
            "status": self.status.value,
            "health_check_url": self.health_check_url,
            "last_heartbeat": self.last_heartbeat,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "ServiceInstance":
        """从字典创建"""
        return cls(
            service_name=d["service_name"],
            instance_id=d["instance_id"],
            address=d.get("address", d.get("host", "127.0.0.1")),
            port=int(d["port"]),
            version=d.get("version", "1.0.0"),
            weight=int(d.get("weight", 1)),
            status=ServiceStatus(d.get("status", "healthy")),
            health_check_url=d.get("health_check_url", "/health"),
            last_heartbeat=float(d.get("last_heartbeat", time.time())),
            metadata=d.get("metadata", {}),
        )


# ============================================================
# 事件模型
# ============================================================

@dataclass
class Event:
    """
    事件数据模型。

    用于事件总线的发布/订阅。
    """

    event_type: str                    # 事件类型（如 "module.started", "user.created"）
    data: Dict[str, Any]               # 事件数据
    source: str = ""                   # 事件来源模块
    event_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    timestamp: float = field(default_factory=time.time)
    trace_id: str = ""                 # 链路追踪 ID
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            "event_id": self.event_id,
            "event_type": self.event_type,
            "data": self.data,
            "source": self.source,
            "timestamp": self.timestamp,
            "trace_id": self.trace_id,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "Event":
        """从字典创建"""
        return cls(
            event_type=d["event_type"],
            data=d.get("data", {}),
            source=d.get("source", ""),
            event_id=d.get("event_id", str(uuid.uuid4())),
            timestamp=float(d.get("timestamp", time.time())),
            trace_id=d.get("trace_id", ""),
            metadata=d.get("metadata", {}),
        )

    def matches(self, pattern: str) -> bool:
        """
        检查事件是否匹配订阅模式。

        支持通配符：
        - "*" 匹配单级（如 "module.*" 匹配 "module.started" 但不匹配 "module.started.error"）
        - "#" 匹配多级（如 "module.#" 匹配 "module.started" 和 "module.started.error"）

        Args:
            pattern: 订阅模式

        Returns:
            是否匹配
        """
        return _match_event_pattern(self.event_type, pattern)


def _match_event_pattern(event_type: str, pattern: str) -> bool:
    """
    事件类型模式匹配。

    规则：
    - 完全相等则匹配
    - "*" 匹配单级任意值
    - "#" 匹配 0 或多级任意值（只能在末尾）

    Examples:
        "module.started" 匹配 "module.started"
        "module.started" 匹配 "module.*"
        "module.started.error" 不匹配 "module.*"
        "module.started.error" 匹配 "module.#"
        "module.started.error" 匹配 "#"
    """
    if pattern == "#":
        return True
    if pattern == event_type:
        return True

    event_parts = event_type.split(".")
    pattern_parts = pattern.split(".")

    ei = 0
    pi = 0
    while ei < len(event_parts) and pi < len(pattern_parts):
        pp = pattern_parts[pi]
        if pp == "#":
            # # 匹配剩余所有
            return True
        if pp == "*":
            # * 匹配一级
            ei += 1
            pi += 1
            continue
        if pp == event_parts[ei]:
            ei += 1
            pi += 1
            continue
        return False

    # 模式用完，事件也用完
    if pi == len(pattern_parts) and ei == len(event_parts):
        return True
    # 模式还剩一个 #
    if pi == len(pattern_parts) - 1 and pattern_parts[pi] == "#":
        return True
    return False


# ============================================================
# SDK 错误码定义（00 系统模块 + 10 序号段）
# ============================================================

class SdkErrorCode(IntEnum):
    """
    SDK 模块错误码（使用 00 系统模块 + 第 10+ 序号段，避免与现有错误码冲突）。

    格式：00 XX YY
    - 00: 系统通用模块
    - XX: 错误类别（沿用 ErrorCategory）
    - YY: 具体错误序号（从 10 起，SDK 专用）
    """

    # ---------- 成功 ----------
    SUCCESS = 0

    # ---------- 服务发现错误 (00041x) ----------
    SERVICE_NOT_FOUND = 410       # 服务未找到
    NO_HEALTHY_INSTANCE = 411    # 无健康实例
    INSTANCE_NOT_FOUND = 412     # 实例不存在

    # ---------- 服务调用错误 (00071x) ----------
    CALL_FAILED = 710            # 调用失败
    CALL_TIMEOUT = 711           # 调用超时
    CALL_RETRY_EXHAUSTED = 712   # 重试耗尽

    # ---------- 熔断/限流 (00081x) ----------
    CIRCUIT_OPEN = 810           # 熔断器打开
    RATE_LIMITED = 811           # 限流

    # ---------- 配置错误 (00061x) ----------
    CONFIG_ERROR = 610           # 配置错误
    INVALID_CONFIG = 611         # 无效配置

    # ---------- 事件总线错误 (00051x) ----------
    EVENT_PUBLISH_FAILED = 510   # 事件发布失败
    EVENT_SUBSCRIBE_FAILED = 511 # 事件订阅失败
    INVALID_EVENT_TYPE = 512     # 无效事件类型

    # ---------- 注册中心错误 (00061x, 复用系统错误) ----------
    REGISTRY_UNAVAILABLE = 612   # 注册中心不可用
    REGISTER_FAILED = 613        # 注册失败
    DEREGISTER_FAILED = 614      # 注销失败
    HEARTBEAT_FAILED = 615       # 心跳失败


# ============================================================
# 负载均衡策略枚举
# ============================================================

class LoadBalanceStrategy(str, Enum):
    """负载均衡策略"""
    ROUND_ROBIN = "round_robin"              # 轮询
    RANDOM = "random"                        # 随机
    WEIGHTED_ROUND_ROBIN = "weighted_round_robin"  # 加权轮询
    LEAST_CONNECTIONS = "least_connections"  # 最少连接
    CONSISTENT_HASH = "consistent_hash"      # 一致性哈希


# ============================================================
# 熔断器状态
# ============================================================

class CircuitState(str, Enum):
    """熔断器状态"""
    CLOSED = "closed"          # 关闭（正常，允许请求通过）
    OPEN = "open"              # 打开（熔断，拒绝请求）
    HALF_OPEN = "half_open"    # 半开（尝试放行少量请求探测）


# ============================================================
# 模块导出
# ============================================================

__all__ = [
    "ApiResponse",
    "ServiceInstance",
    "ServiceStatus",
    "Event",
    "SdkErrorCode",
    "LoadBalanceStrategy",
    "CircuitState",
]
