"""
云汐系统 - 统一响应标准错误码与常量
====================================

标准错误码常量、业务错误码区间定义、标准消息模板。

与 shared/core/errors.py 的 6 位错误码体系完全兼容。
本模块提供常用的便捷常量引用，避免各模块重复定义。

错误码体系（6 位）：XX YY ZZ
  - XX: 模块编号（00=系统通用, 01-12=M1-M12）
  - YY: 错误类别（01=参数, 02=认证, 03=权限, 04=不存在, 05=业务, 06=系统, 07=第三方, 08=限流, 09=数据）
  - ZZ: 具体序号（00-99）
"""

from __future__ import annotations

from typing import Dict


# ============================================================
# 标准 HTTP 状态码常量
# ============================================================

HTTP_OK = 200
HTTP_CREATED = 201
HTTP_ACCEPTED = 202
HTTP_NO_CONTENT = 204
HTTP_BAD_REQUEST = 400
HTTP_UNAUTHORIZED = 401
HTTP_FORBIDDEN = 403
HTTP_NOT_FOUND = 404
HTTP_METHOD_NOT_ALLOWED = 405
HTTP_CONFLICT = 409
HTTP_TOO_MANY_REQUESTS = 429
HTTP_INTERNAL_SERVER_ERROR = 500
HTTP_BAD_GATEWAY = 502
HTTP_SERVICE_UNAVAILABLE = 503
HTTP_GATEWAY_TIMEOUT = 504


# ============================================================
# 标准业务错误码（系统通用模块 00）
# ============================================================

# 成功
SUCCESS = 0

# 参数错误 (0001xx)
ERR_VALIDATION = 101          # 000101 - 通用参数错误
ERR_MISSING_FIELD = 102       # 000102 - 缺少必填字段
ERR_INVALID_FORMAT = 103      # 000103 - 格式错误
ERR_TOO_LONG = 104            # 000104 - 内容过长
ERR_TOO_SHORT = 105           # 000105 - 内容过短
ERR_INVALID_VALUE = 106       # 000106 - 无效值

# 认证错误 (0002xx)
ERR_AUTH_FAILED = 201         # 000201 - 认证失败
ERR_TOKEN_EXPIRED = 202       # 000202 - Token 过期
ERR_TOKEN_INVALID = 203       # 000203 - Token 无效
ERR_LOGIN_REQUIRED = 204      # 000204 - 需要登录

# 权限错误 (0003xx)
ERR_PERMISSION_DENIED = 301   # 000301 - 无权限
ERR_ROLE_REQUIRED = 302       # 000302 - 缺少角色
ERR_SCOPE_INSUFFICIENT = 303  # 000303 - 权限范围不足

# 资源不存在 (0004xx)
ERR_NOT_FOUND = 401           # 000401 - 资源不存在
ERR_ENDPOINT_NOT_FOUND = 402  # 000402 - 接口不存在
ERR_USER_NOT_FOUND = 403      # 000403 - 用户不存在

# 业务错误 (0005xx)
ERR_BUSINESS = 501            # 000501 - 通用业务错误
ERR_OPERATION_FAILED = 502    # 000502 - 操作失败
ERR_ALREADY_EXISTS = 503      # 000503 - 资源已存在
ERR_STATE_CONFLICT = 504      # 000504 - 状态冲突

# 系统错误 (0006xx)
ERR_INTERNAL = 601            # 000601 - 服务器内部错误
ERR_SERVICE_UNAVAILABLE = 602 # 000602 - 服务不可用
ERR_TIMEOUT = 603             # 000603 - 超时
ERR_DEPENDENCY_FAILURE = 604  # 000604 - 依赖服务故障

# 第三方错误 (0007xx)
ERR_UPSTREAM_ERROR = 701      # 000701 - 上游服务错误
ERR_UPSTREAM_TIMEOUT = 702    # 000702 - 上游超时
ERR_EXTERNAL_API = 703        # 000703 - 外部 API 错误

# 限流错误 (0008xx)
ERR_RATE_LIMITED = 801        # 000801 - 触发限流
ERR_QUOTA_EXCEEDED = 802      # 000802 - 配额超限
ERR_TOO_MANY_CONNECTIONS = 803 # 000803 - 连接数过多

# 数据错误 (0009xx)
ERR_DATA_INTEGRITY = 901      # 000901 - 数据完整性错误
ERR_DATA_CONFLICT = 902       # 000902 - 数据冲突
ERR_DATA_CORRUPTED = 903      # 000903 - 数据损坏


# ============================================================
# 业务错误码区间定义（各模块预留）
# ============================================================

MODULE_CODE_RANGES: Dict[str, tuple] = {
    "system": (0, 9999),            # 系统通用: 000000 - 009999
    "m1": (10000, 19999),           # M1 智能体集群: 010000 - 019999
    "m2": (20000, 29999),           # M2 技能集群: 020000 - 029999
    "m3": (30000, 39999),           # M3 边端云协同: 030000 - 039999
    "m4": (40000, 49999),           # M4 场景引擎: 040000 - 049999
    "m5": (50000, 59999),           # M5 潮汐记忆: 050000 - 059999
    "m6": (60000, 69999),           # M6 硬件外设: 060000 - 069999
    "m7": (70000, 79999),           # M7 积木平台: 070000 - 079999
    "m8": (80000, 89999),           # M8 控制塔: 080000 - 089999
    "m9": (90000, 99999),           # M9 开发工坊: 090000 - 099999
    "m10": (100000, 109999),        # M10 系统卫士: 100000 - 109999
    "m11": (110000, 119999),        # M11 MCP 总线: 110000 - 119999
    "m12": (120000, 129999),        # M12 安全盾: 120000 - 129999
}


# ============================================================
# 标准消息模板
# ============================================================

STANDARD_MESSAGES: Dict[int, str] = {
    SUCCESS: "ok",
    ERR_VALIDATION: "参数验证失败",
    ERR_MISSING_FIELD: "缺少必填字段",
    ERR_INVALID_FORMAT: "数据格式错误",
    ERR_AUTH_FAILED: "认证失败",
    ERR_TOKEN_EXPIRED: "Token 已过期",
    ERR_TOKEN_INVALID: "Token 无效",
    ERR_LOGIN_REQUIRED: "请先登录",
    ERR_PERMISSION_DENIED: "无权限访问",
    ERR_ROLE_REQUIRED: "缺少必要角色",
    ERR_SCOPE_INSUFFICIENT: "权限范围不足",
    ERR_NOT_FOUND: "资源不存在",
    ERR_ENDPOINT_NOT_FOUND: "接口不存在",
    ERR_USER_NOT_FOUND: "用户不存在",
    ERR_BUSINESS: "业务处理失败",
    ERR_OPERATION_FAILED: "操作失败",
    ERR_ALREADY_EXISTS: "资源已存在",
    ERR_STATE_CONFLICT: "状态冲突",
    ERR_INTERNAL: "服务器内部错误",
    ERR_SERVICE_UNAVAILABLE: "服务暂不可用",
    ERR_TIMEOUT: "请求超时",
    ERR_DEPENDENCY_FAILURE: "依赖服务故障",
    ERR_UPSTREAM_ERROR: "上游服务错误",
    ERR_UPSTREAM_TIMEOUT: "上游服务超时",
    ERR_EXTERNAL_API: "外部 API 调用失败",
    ERR_RATE_LIMITED: "请求过于频繁，请稍后再试",
    ERR_QUOTA_EXCEEDED: "配额已用尽",
    ERR_TOO_MANY_CONNECTIONS: "连接数过多",
    ERR_DATA_INTEGRITY: "数据完整性错误",
    ERR_DATA_CONFLICT: "数据冲突",
    ERR_DATA_CORRUPTED: "数据已损坏",
}


# ============================================================
# 错误码 -> HTTP 状态码映射
# ============================================================

ERROR_HTTP_STATUS_MAP: Dict[int, int] = {
    SUCCESS: HTTP_OK,
    ERR_VALIDATION: HTTP_BAD_REQUEST,
    ERR_MISSING_FIELD: HTTP_BAD_REQUEST,
    ERR_INVALID_FORMAT: HTTP_BAD_REQUEST,
    ERR_TOO_LONG: HTTP_BAD_REQUEST,
    ERR_TOO_SHORT: HTTP_BAD_REQUEST,
    ERR_INVALID_VALUE: HTTP_BAD_REQUEST,
    ERR_AUTH_FAILED: HTTP_UNAUTHORIZED,
    ERR_TOKEN_EXPIRED: HTTP_UNAUTHORIZED,
    ERR_TOKEN_INVALID: HTTP_UNAUTHORIZED,
    ERR_LOGIN_REQUIRED: HTTP_UNAUTHORIZED,
    ERR_PERMISSION_DENIED: HTTP_FORBIDDEN,
    ERR_ROLE_REQUIRED: HTTP_FORBIDDEN,
    ERR_SCOPE_INSUFFICIENT: HTTP_FORBIDDEN,
    ERR_NOT_FOUND: HTTP_NOT_FOUND,
    ERR_ENDPOINT_NOT_FOUND: HTTP_NOT_FOUND,
    ERR_USER_NOT_FOUND: HTTP_NOT_FOUND,
    ERR_BUSINESS: HTTP_CONFLICT,
    ERR_OPERATION_FAILED: HTTP_CONFLICT,
    ERR_ALREADY_EXISTS: HTTP_CONFLICT,
    ERR_STATE_CONFLICT: HTTP_CONFLICT,
    ERR_INTERNAL: HTTP_INTERNAL_SERVER_ERROR,
    ERR_SERVICE_UNAVAILABLE: HTTP_SERVICE_UNAVAILABLE,
    ERR_TIMEOUT: HTTP_GATEWAY_TIMEOUT,
    ERR_DEPENDENCY_FAILURE: HTTP_BAD_GATEWAY,
    ERR_UPSTREAM_ERROR: HTTP_BAD_GATEWAY,
    ERR_UPSTREAM_TIMEOUT: HTTP_GATEWAY_TIMEOUT,
    ERR_EXTERNAL_API: HTTP_BAD_GATEWAY,
    ERR_RATE_LIMITED: HTTP_TOO_MANY_REQUESTS,
    ERR_QUOTA_EXCEEDED: HTTP_TOO_MANY_REQUESTS,
    ERR_TOO_MANY_CONNECTIONS: HTTP_TOO_MANY_REQUESTS,
    ERR_DATA_INTEGRITY: HTTP_CONFLICT,
    ERR_DATA_CONFLICT: HTTP_CONFLICT,
    ERR_DATA_CORRUPTED: HTTP_INTERNAL_SERVER_ERROR,
}


def get_standard_message(code: int) -> str:
    """获取错误码对应的标准消息.

    Args:
        code: 错误码

    Returns:
        标准消息文本，未定义时返回 "error"
    """
    return STANDARD_MESSAGES.get(code, "error")


def get_http_status(code: int) -> int:
    """根据错误码推断 HTTP 状态码.

    Args:
        code: 错误码

    Returns:
        对应的 HTTP 状态码，未定义时默认返回 500
    """
    if code == SUCCESS or code == 0:
        return HTTP_OK
    return ERROR_HTTP_STATUS_MAP.get(code, HTTP_INTERNAL_SERVER_ERROR)


# ============================================================
# 模块导出
# ============================================================

__all__ = [
    # HTTP 状态码
    "HTTP_OK",
    "HTTP_CREATED",
    "HTTP_ACCEPTED",
    "HTTP_NO_CONTENT",
    "HTTP_BAD_REQUEST",
    "HTTP_UNAUTHORIZED",
    "HTTP_FORBIDDEN",
    "HTTP_NOT_FOUND",
    "HTTP_METHOD_NOT_ALLOWED",
    "HTTP_CONFLICT",
    "HTTP_TOO_MANY_REQUESTS",
    "HTTP_INTERNAL_SERVER_ERROR",
    "HTTP_BAD_GATEWAY",
    "HTTP_SERVICE_UNAVAILABLE",
    "HTTP_GATEWAY_TIMEOUT",
    # 标准错误码
    "SUCCESS",
    "ERR_VALIDATION",
    "ERR_MISSING_FIELD",
    "ERR_INVALID_FORMAT",
    "ERR_TOO_LONG",
    "ERR_TOO_SHORT",
    "ERR_INVALID_VALUE",
    "ERR_AUTH_FAILED",
    "ERR_TOKEN_EXPIRED",
    "ERR_TOKEN_INVALID",
    "ERR_LOGIN_REQUIRED",
    "ERR_PERMISSION_DENIED",
    "ERR_ROLE_REQUIRED",
    "ERR_SCOPE_INSUFFICIENT",
    "ERR_NOT_FOUND",
    "ERR_ENDPOINT_NOT_FOUND",
    "ERR_USER_NOT_FOUND",
    "ERR_BUSINESS",
    "ERR_OPERATION_FAILED",
    "ERR_ALREADY_EXISTS",
    "ERR_STATE_CONFLICT",
    "ERR_INTERNAL",
    "ERR_SERVICE_UNAVAILABLE",
    "ERR_TIMEOUT",
    "ERR_DEPENDENCY_FAILURE",
    "ERR_UPSTREAM_ERROR",
    "ERR_UPSTREAM_TIMEOUT",
    "ERR_EXTERNAL_API",
    "ERR_RATE_LIMITED",
    "ERR_QUOTA_EXCEEDED",
    "ERR_TOO_MANY_CONNECTIONS",
    "ERR_DATA_INTEGRITY",
    "ERR_DATA_CONFLICT",
    "ERR_DATA_CORRUPTED",
    # 区间和映射
    "MODULE_CODE_RANGES",
    "STANDARD_MESSAGES",
    "ERROR_HTTP_STATUS_MAP",
    # 工具函数
    "get_standard_message",
    "get_http_status",
]
