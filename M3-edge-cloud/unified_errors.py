"""
M3 端云协同 - 模块级错误码定义（统一 6 位错误码体系）

遵循云汐系统统一 6 位错误码规范：XX YY ZZ
  - XX = 03 (模块编号，M3)
  - YY = 错误类别
  - ZZ = 序号
"""

try:
    from shared.core.errors import (
        ModuleCode,
        ErrorCategory,
        build_error_code,
        ModuleErrorCode,
    )
    _UNIFIED_ERRORS_AVAILABLE = True
except ImportError:
    _UNIFIED_ERRORS_AVAILABLE = False
    ModuleCode = None  # type: ignore
    ErrorCategory = None  # type: ignore
    ModuleErrorCode = object  # type: ignore

    def build_error_code(module, category, seq):  # type: ignore
        return int(module) * 10000 + int(category) * 100 + seq


if _UNIFIED_ERRORS_AVAILABLE:

    class M3ErrorCode(ModuleErrorCode):
        """M3 端云协同错误码常量.

        模块编号: 03
        范围: 030100 - 030999
        """
        MODULE = ModuleCode.M3

        # ---------- 参数错误 (0301xx) ----------
        INVALID_DEVICE_ID = build_error_code(ModuleCode.M3, ErrorCategory.VALIDATION, 1)
        """无效的设备 ID"""
        INVALID_EDGE_NODE = build_error_code(ModuleCode.M3, ErrorCategory.VALIDATION, 2)
        """无效的边端节点"""
        INVALID_SYNC_TASK = build_error_code(ModuleCode.M3, ErrorCategory.VALIDATION, 3)
        """无效的同步任务"""
        INVALID_OFFLINE_DATA = build_error_code(ModuleCode.M3, ErrorCategory.VALIDATION, 4)
        """无效的离线数据"""

        # ---------- 认证错误 (0302xx) ----------
        DEVICE_AUTH_FAILED = build_error_code(ModuleCode.M3, ErrorCategory.AUTHENTICATION, 1)
        """设备认证失败"""
        EDGE_NODE_AUTH_FAILED = build_error_code(ModuleCode.M3, ErrorCategory.AUTHENTICATION, 2)
        """边端节点认证失败"""
        INVALID_DEVICE_TOKEN = build_error_code(ModuleCode.M3, ErrorCategory.AUTHENTICATION, 3)
        """无效的设备令牌"""

        # ---------- 权限错误 (0303xx) ----------
        DEVICE_NOT_REGISTERED = build_error_code(ModuleCode.M3, ErrorCategory.AUTHORIZATION, 1)
        """设备未注册"""
        EDGE_NODE_FORBIDDEN = build_error_code(ModuleCode.M3, ErrorCategory.AUTHORIZATION, 2)
        """边端节点无权限"""

        # ---------- 资源不存在 (0304xx) ----------
        DEVICE_NOT_FOUND = build_error_code(ModuleCode.M3, ErrorCategory.NOT_FOUND, 1)
        """设备不存在"""
        EDGE_NODE_NOT_FOUND = build_error_code(ModuleCode.M3, ErrorCategory.NOT_FOUND, 2)
        """边端节点不存在"""
        SYNC_TASK_NOT_FOUND = build_error_code(ModuleCode.M3, ErrorCategory.NOT_FOUND, 3)
        """同步任务不存在"""

        # ---------- 业务错误 (0305xx) ----------
        DEVICE_OFFLINE = build_error_code(ModuleCode.M3, ErrorCategory.BUSINESS, 1)
        """设备离线"""
        EDGE_NODE_OFFLINE = build_error_code(ModuleCode.M3, ErrorCategory.BUSINESS, 2)
        """边端节点离线"""
        SYNC_CONFLICT = build_error_code(ModuleCode.M3, ErrorCategory.BUSINESS, 3)
        """数据同步冲突"""
        OFFLINE_QUEUE_FULL = build_error_code(ModuleCode.M3, ErrorCategory.BUSINESS, 4)
        """离线队列已满"""
        CLOUD_SYNC_FAILED = build_error_code(ModuleCode.M3, ErrorCategory.BUSINESS, 5)
        """云端同步失败"""
        EDGE_DEPLOY_FAILED = build_error_code(ModuleCode.M3, ErrorCategory.BUSINESS, 6)
        """边端部署失败"""

        # ---------- 系统错误 (0306xx) ----------
        MQTT_CONNECTION_FAILED = build_error_code(ModuleCode.M3, ErrorCategory.SYSTEM, 1)
        """MQTT 连接失败"""
        REDIS_SYNC_FAILED = build_error_code(ModuleCode.M3, ErrorCategory.SYSTEM, 2)
        """Redis 同步失败"""
        MESSAGE_QUEUE_ERROR = build_error_code(ModuleCode.M3, ErrorCategory.SYSTEM, 3)
        """消息队列错误"""

    # 便捷别名
    M3_ERR = M3ErrorCode

else:
    # 回退模式
    class M3ErrorCode:
        """M3 错误码常量（回退模式）"""
        INVALID_DEVICE_ID = 30101
        INVALID_EDGE_NODE = 30102
        INVALID_SYNC_TASK = 30103
        INVALID_OFFLINE_DATA = 30104
        DEVICE_AUTH_FAILED = 30201
        EDGE_NODE_AUTH_FAILED = 30202
        INVALID_DEVICE_TOKEN = 30203
        DEVICE_NOT_REGISTERED = 30301
        EDGE_NODE_FORBIDDEN = 30302
        DEVICE_NOT_FOUND = 30401
        EDGE_NODE_NOT_FOUND = 30402
        SYNC_TASK_NOT_FOUND = 30403
        DEVICE_OFFLINE = 30501
        EDGE_NODE_OFFLINE = 30502
        SYNC_CONFLICT = 30503
        OFFLINE_QUEUE_FULL = 30504
        CLOUD_SYNC_FAILED = 30505
        EDGE_DEPLOY_FAILED = 30506
        MQTT_CONNECTION_FAILED = 30601
        REDIS_SYNC_FAILED = 30602
        MESSAGE_QUEUE_ERROR = 30603

    M3_ERR = M3ErrorCode


__all__ = [
    "M3ErrorCode",
    "M3_ERR",
    "_UNIFIED_ERRORS_AVAILABLE",
]
