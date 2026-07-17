"""
M6 硬件外设 - 模块级错误码定义（统一 6 位错误码体系）

遵循云汐系统统一 6 位错误码规范：XX YY ZZ
  - XX = 06 (模块编号，M6)
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

    class M6ErrorCode(ModuleErrorCode):
        """M6 硬件外设错误码常量.

        模块编号: 06
        范围: 060100 - 060999
        """
        MODULE = ModuleCode.M6

        # ---------- 参数错误 (0601xx) ----------
        INVALID_DEVICE_ID = build_error_code(ModuleCode.M6, ErrorCategory.VALIDATION, 1)
        """无效的设备 ID"""
        INVALID_DEVICE_TYPE = build_error_code(ModuleCode.M6, ErrorCategory.VALIDATION, 2)
        """无效的设备类型"""
        INVALID_COMMAND = build_error_code(ModuleCode.M6, ErrorCategory.VALIDATION, 3)
        """无效的控制命令"""
        INVALID_SENSOR_DATA = build_error_code(ModuleCode.M6, ErrorCategory.VALIDATION, 4)
        """无效的传感器数据"""
        INVALID_DRIVER_CONFIG = build_error_code(ModuleCode.M6, ErrorCategory.VALIDATION, 5)
        """无效的驱动配置"""

        # ---------- 资源不存在 (0604xx) ----------
        DEVICE_NOT_FOUND = build_error_code(ModuleCode.M6, ErrorCategory.NOT_FOUND, 1)
        """设备不存在"""
        DRIVER_NOT_FOUND = build_error_code(ModuleCode.M6, ErrorCategory.NOT_FOUND, 2)
        """驱动不存在"""
        SENSOR_NOT_FOUND = build_error_code(ModuleCode.M6, ErrorCategory.NOT_FOUND, 3)
        """传感器不存在"""
        PERIPHERAL_NOT_FOUND = build_error_code(ModuleCode.M6, ErrorCategory.NOT_FOUND, 4)
        """外设不存在"""

        # ---------- 业务错误 (0605xx) ----------
        DEVICE_OFFLINE = build_error_code(ModuleCode.M6, ErrorCategory.BUSINESS, 1)
        """设备离线"""
        DEVICE_BUSY = build_error_code(ModuleCode.M6, ErrorCategory.BUSINESS, 2)
        """设备繁忙"""
        COMMUNICATION_FAILED = build_error_code(ModuleCode.M6, ErrorCategory.BUSINESS, 3)
        """通信失败"""
        COMMAND_TIMEOUT = build_error_code(ModuleCode.M6, ErrorCategory.BUSINESS, 4)
        """命令超时"""
        DEVICE_INIT_FAILED = build_error_code(ModuleCode.M6, ErrorCategory.BUSINESS, 5)
        """设备初始化失败"""
        DRIVER_LOAD_FAILED = build_error_code(ModuleCode.M6, ErrorCategory.BUSINESS, 6)
        """驱动加载失败"""
        HARDWARE_ERROR = build_error_code(ModuleCode.M6, ErrorCategory.BUSINESS, 7)
        """硬件错误"""
        SENSOR_READ_FAILED = build_error_code(ModuleCode.M6, ErrorCategory.BUSINESS, 8)
        """传感器读取失败"""

        # ---------- 系统错误 (0606xx) ----------
        SERIAL_PORT_ERROR = build_error_code(ModuleCode.M6, ErrorCategory.SYSTEM, 1)
        """串口错误"""
        USB_ERROR = build_error_code(ModuleCode.M6, ErrorCategory.SYSTEM, 2)
        """USB 错误"""
        GPIO_ERROR = build_error_code(ModuleCode.M6, ErrorCategory.SYSTEM, 3)
        """GPIO 错误"""
        I2C_ERROR = build_error_code(ModuleCode.M6, ErrorCategory.SYSTEM, 4)
        """I2C 错误"""
        SPI_ERROR = build_error_code(ModuleCode.M6, ErrorCategory.SYSTEM, 5)
        """SPI 错误"""

    # 便捷别名
    M6_ERR = M6ErrorCode

else:
    # 回退模式
    class M6ErrorCode:
        """M6 错误码常量（回退模式）"""
        INVALID_DEVICE_ID = 60101
        INVALID_DEVICE_TYPE = 60102
        INVALID_COMMAND = 60103
        INVALID_SENSOR_DATA = 60104
        INVALID_DRIVER_CONFIG = 60105
        DEVICE_NOT_FOUND = 60401
        DRIVER_NOT_FOUND = 60402
        SENSOR_NOT_FOUND = 60403
        PERIPHERAL_NOT_FOUND = 60404
        DEVICE_OFFLINE = 60501
        DEVICE_BUSY = 60502
        COMMUNICATION_FAILED = 60503
        COMMAND_TIMEOUT = 60504
        DEVICE_INIT_FAILED = 60505
        DRIVER_LOAD_FAILED = 60506
        HARDWARE_ERROR = 60507
        SENSOR_READ_FAILED = 60508
        SERIAL_PORT_ERROR = 60601
        USB_ERROR = 60602
        GPIO_ERROR = 60603
        I2C_ERROR = 60604
        SPI_ERROR = 60605

    M6_ERR = M6ErrorCode


__all__ = [
    "M6ErrorCode",
    "M6_ERR",
    "_UNIFIED_ERRORS_AVAILABLE",
]
