"""通用工具模块.

提供端云协同内核各子模块共享的通用组件，包括：
- 幂等性管理器（IdempotencyManager）
"""

from edge_cloud_kernel.common.idempotency import (
    IdempotencyManager,
    IdempotencyGuard,
    IdempotencyError,
    generate_sync_key,
    generate_config_key,
    generate_request_key,
)

__all__ = [
    "IdempotencyManager",
    "IdempotencyGuard",
    "IdempotencyError",
    "generate_sync_key",
    "generate_config_key",
    "generate_request_key",
]
