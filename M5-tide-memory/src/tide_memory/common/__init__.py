"""
通用工具模块

提供幂等性管理、缓存工具等跨模块通用能力。
"""

from .idempotency import IdempotencyManager, get_idempotency_manager

__all__ = ["IdempotencyManager", "get_idempotency_manager"]
# vim: set et ts=4 sw=4:
