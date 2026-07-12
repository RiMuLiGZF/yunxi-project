"""M3 统一错误码（M8 标准对接）.

错误码段：30000-39999
- 30000-30099: 通用错误
- 30100-30199: 同步相关错误
- 30200-30299: 冲突相关错误
- 30300-30399: 设备相关错误
- 30400-30499: 鉴权与安全错误
- 30500-30599: 离线队列错误
- 30600-30699: 资源相关错误
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ErrorCode:
    """错误码定义."""
    code: int
    message: str
    http_status: int = 400


# ---------- 通用错误（30000-30099） ----------
ERR_SUCCESS = ErrorCode(30000, "Success", 200)
ERR_UNKNOWN = ErrorCode(30001, "Unknown error", 500)
ERR_INVALID_PARAM = ErrorCode(30002, "Invalid parameter", 400)
ERR_NOT_FOUND = ErrorCode(30003, "Resource not found", 404)
ERR_SERVICE_UNAVAILABLE = ErrorCode(30005, "Service unavailable", 503)

# ---------- 同步相关错误（30100-30199） ----------
ERR_SYNC_FAILED = ErrorCode(30100, "Synchronization failed", 500)
ERR_SYNC_IN_PROGRESS = ErrorCode(30101, "Synchronization already in progress", 409)
ERR_SYNC_SESSION_NOT_FOUND = ErrorCode(30102, "Sync session not found", 404)
ERR_SYNC_VERSION_CONFLICT = ErrorCode(30103, "Version conflict", 409)
ERR_SYNC_NETWORK_ERROR = ErrorCode(30104, "Network error during sync", 502)

# ---------- 冲突相关错误（30200-30299） ----------
ERR_CONFLICT_NOT_FOUND = ErrorCode(30200, "Conflict not found", 404)
ERR_CONFLICT_ALREADY_RESOLVED = ErrorCode(30201, "Conflict already resolved", 409)
ERR_CONFLICT_INVALID_RESOLUTION = ErrorCode(30202, "Invalid resolution strategy", 400)
ERR_CONFLICT_MERGE_FAILED = ErrorCode(30203, "Conflict merge failed", 422)

# ---------- 设备相关错误（30300-30399） ----------
ERR_DEVICE_NOT_FOUND = ErrorCode(30300, "Device not found", 404)
ERR_DEVICE_ALREADY_EXISTS = ErrorCode(30301, "Device already exists", 409)
ERR_DEVICE_OFFLINE = ErrorCode(30302, "Device is offline", 400)
ERR_DEVICE_LIMIT_REACHED = ErrorCode(30303, "Device limit reached", 403)

# ---------- 鉴权与安全错误（30400-30499） ----------
ERR_AUTH_REQUIRED = ErrorCode(30401, "Authentication required", 401)
ERR_AUTH_TOKEN_INVALID = ErrorCode(30402, "Invalid token", 401)
ERR_AUTH_FORBIDDEN = ErrorCode(30403, "Forbidden", 403)
ERR_ENCRYPTION_FAILED = ErrorCode(30404, "Encryption/decryption failed", 500)

# ---------- 离线队列错误（30500-30599） ----------
ERR_QUEUE_FULL = ErrorCode(30500, "Offline queue is full", 503)
ERR_QUEUE_CORRUPTED = ErrorCode(30501, "Offline queue corrupted", 500)
ERR_QUEUE_REPLAY_FAILED = ErrorCode(30502, "Queue replay failed", 500)

# ---------- 资源相关错误（30600-30699） ----------
ERR_VRAM_OVERFLOW = ErrorCode(30600, "VRAM overflow", 503)
ERR_RATE_LIMITED = ErrorCode(30601, "Rate limit exceeded", 429)
ERR_CIRCUIT_OPEN = ErrorCode(30602, "Circuit breaker is open", 503)
