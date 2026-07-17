"""
M8 控制塔 - 模块级错误码定义
============================

遵循云汐系统统一 6 位错误码规范：XX YY ZZ
  - XX = 08（M8 控制塔）
  - YY = 错误类别
  - ZZ = 具体错误序号

模块范围：080100 - 080999
"""

from shared.core.errors import (
    ModuleCode,
    ErrorCategory,
    build_error_code,
    ModuleErrorCode,
)


class M8ErrorCode(ModuleErrorCode):
    """M8 控制塔错误码常量.

    模块编号: 08
    范围: 080100 - 080999
    """
    MODULE = ModuleCode.M8

    # ---------- 参数错误 (0801xx) ----------
    INVALID_MODULE_KEY = build_error_code(ModuleCode.M8, ErrorCategory.VALIDATION, 1)
    """无效的模块标识"""
    INVALID_MODE_NAME = build_error_code(ModuleCode.M8, ErrorCategory.VALIDATION, 2)
    """无效的模式名称"""
    INVALID_INSPECTION_TYPE = build_error_code(ModuleCode.M8, ErrorCategory.VALIDATION, 3)
    """无效的巡检类型"""

    # ---------- 认证错误 (0802xx) ----------
    ADMIN_TOKEN_REQUIRED = build_error_code(ModuleCode.M8, ErrorCategory.AUTHENTICATION, 1)
    """需要管理员 Token"""
    M8_TOKEN_INVALID = build_error_code(ModuleCode.M8, ErrorCategory.AUTHENTICATION, 2)
    """M8 标准接口 Token 无效"""

    # ---------- 权限错误 (0803xx) ----------
    MODULE_OPERATION_FORBIDDEN = build_error_code(ModuleCode.M8, ErrorCategory.AUTHORIZATION, 1)
    """模块操作权限不足"""
    EVOLUTION_FORBIDDEN = build_error_code(ModuleCode.M8, ErrorCategory.AUTHORIZATION, 2)
    """自进化操作权限不足"""

    # ---------- 资源不存在 (0804xx) ----------
    MODULE_NOT_FOUND = build_error_code(ModuleCode.M8, ErrorCategory.NOT_FOUND, 1)
    """模块不存在"""
    MODE_NOT_FOUND = build_error_code(ModuleCode.M8, ErrorCategory.NOT_FOUND, 2)
    """模式不存在"""
    INSPECTION_NOT_FOUND = build_error_code(ModuleCode.M8, ErrorCategory.NOT_FOUND, 3)
    """巡检任务不存在"""

    # ---------- 业务错误 (0805xx) ----------
    MODULE_START_FAILED = build_error_code(ModuleCode.M8, ErrorCategory.BUSINESS, 1)
    """模块启动失败"""
    MODULE_STOP_FAILED = build_error_code(ModuleCode.M8, ErrorCategory.BUSINESS, 2)
    """模块停止失败"""
    MODULE_RESTART_FAILED = build_error_code(ModuleCode.M8, ErrorCategory.BUSINESS, 3)
    """模块重启失败"""
    MODULE_ALREADY_RUNNING = build_error_code(ModuleCode.M8, ErrorCategory.BUSINESS, 4)
    """模块已在运行"""
    MODULE_NOT_RUNNING = build_error_code(ModuleCode.M8, ErrorCategory.BUSINESS, 5)
    """模块未运行"""
    MODE_SWITCH_FAILED = build_error_code(ModuleCode.M8, ErrorCategory.BUSINESS, 6)
    """模式切换失败"""
    INSPECTION_RUN_FAILED = build_error_code(ModuleCode.M8, ErrorCategory.BUSINESS, 7)
    """巡检执行失败"""
    DEPLOYMENT_FAILED = build_error_code(ModuleCode.M8, ErrorCategory.BUSINESS, 8)
    """部署失败"""

    # ---------- 系统错误 (0806xx) ----------
    DATABASE_INIT_FAILED = build_error_code(ModuleCode.M8, ErrorCategory.SYSTEM, 1)
    """数据库初始化失败"""
    ORCHESTRATOR_ERROR = build_error_code(ModuleCode.M8, ErrorCategory.SYSTEM, 2)
    """编排器错误"""

    # ---------- 第三方/模块调用错误 (0807xx) ----------
    M4_PROXY_ERROR = build_error_code(ModuleCode.M8, ErrorCategory.THIRD_PARTY, 1)
    """M4 代理错误"""
    M5_PROXY_ERROR = build_error_code(ModuleCode.M8, ErrorCategory.THIRD_PARTY, 2)
    """M5 记忆代理错误"""
    M6_DEVICE_ERROR = build_error_code(ModuleCode.M8, ErrorCategory.THIRD_PARTY, 3)
    """M6 设备通信错误"""

    # ---------- 限流错误 (0808xx) ----------
    MODULE_OPERATION_RATE_LIMITED = build_error_code(ModuleCode.M8, ErrorCategory.RATE_LIMIT, 1)
    """模块操作频率超限"""

    # ---------- 数据错误 (0809xx) ----------
    SETTINGS_CONFLICT = build_error_code(ModuleCode.M8, ErrorCategory.DATA, 1)
    """配置冲突"""
    USER_DATA_ERROR = build_error_code(ModuleCode.M8, ErrorCategory.DATA, 2)
    """用户数据错误"""


# 便捷别名
M8_ERR = M8ErrorCode
