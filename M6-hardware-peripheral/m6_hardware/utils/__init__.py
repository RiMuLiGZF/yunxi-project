"""
M6 硬件外设 - 工具包

P2-2/P2-4 改造：提供熔断器、限流器、性能监控埋点等通用基础设施。
"""

from .circuit_breaker import CircuitBreaker
from .metrics import Metrics

__all__ = ["CircuitBreaker", "Metrics"]
