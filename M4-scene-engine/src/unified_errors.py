"""
M4 场景引擎 - 模块级错误码定义（统一 6 位错误码体系）

遵循云汐系统统一 6 位错误码规范：XX YY ZZ
  - XX = 04 (模块编号，M4)
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

    class M4ErrorCode(ModuleErrorCode):
        """M4 场景引擎错误码常量.

        模块编号: 04
        范围: 040100 - 040999
        """
        MODULE = ModuleCode.M4

        # ---------- 参数错误 (0401xx) ----------
        INVALID_SCENE_ID = build_error_code(ModuleCode.M4, ErrorCategory.VALIDATION, 1)
        """无效的场景 ID"""
        INVALID_SCENE_CONFIG = build_error_code(ModuleCode.M4, ErrorCategory.VALIDATION, 2)
        """无效的场景配置"""
        INVALID_TRIGGER = build_error_code(ModuleCode.M4, ErrorCategory.VALIDATION, 3)
        """无效的触发器"""
        INVALID_CONDITION = build_error_code(ModuleCode.M4, ErrorCategory.VALIDATION, 4)
        """无效的条件表达式"""
        INVALID_ACTION = build_error_code(ModuleCode.M4, ErrorCategory.VALIDATION, 5)
        """无效的动作配置"""
        INVALID_SCENE_NAME = build_error_code(ModuleCode.M4, ErrorCategory.VALIDATION, 6)
        """无效的场景名称"""

        # ---------- 资源不存在 (0404xx) ----------
        SCENE_NOT_FOUND = build_error_code(ModuleCode.M4, ErrorCategory.NOT_FOUND, 1)
        """场景不存在"""
        TRIGGER_NOT_FOUND = build_error_code(ModuleCode.M4, ErrorCategory.NOT_FOUND, 2)
        """触发器不存在"""
        ACTION_NOT_FOUND = build_error_code(ModuleCode.M4, ErrorCategory.NOT_FOUND, 3)
        """动作不存在"""
        SCENE_TEMPLATE_NOT_FOUND = build_error_code(ModuleCode.M4, ErrorCategory.NOT_FOUND, 4)
        """场景模板不存在"""

        # ---------- 业务错误 (0405xx) ----------
        SCENE_ALREADY_EXISTS = build_error_code(ModuleCode.M4, ErrorCategory.BUSINESS, 1)
        """场景已存在"""
        SCENE_ALREADY_ACTIVE = build_error_code(ModuleCode.M4, ErrorCategory.BUSINESS, 2)
        """场景已激活"""
        SCENE_NOT_ACTIVE = build_error_code(ModuleCode.M4, ErrorCategory.BUSINESS, 3)
        """场景未激活"""
        TRIGGER_CONFLICT = build_error_code(ModuleCode.M4, ErrorCategory.BUSINESS, 4)
        """触发器冲突"""
        ACTION_EXECUTION_FAILED = build_error_code(ModuleCode.M4, ErrorCategory.BUSINESS, 5)
        """动作执行失败"""
        CONDITION_EVALUATION_FAILED = build_error_code(ModuleCode.M4, ErrorCategory.BUSINESS, 6)
        """条件评估失败"""
        SCENE_CYCLE_DETECTED = build_error_code(ModuleCode.M4, ErrorCategory.BUSINESS, 7)
        """检测到场景循环依赖"""

        # ---------- 系统错误 (0406xx) ----------
        ENGINE_INIT_FAILED = build_error_code(ModuleCode.M4, ErrorCategory.SYSTEM, 1)
        """场景引擎初始化失败"""
        EVENT_BUS_ERROR = build_error_code(ModuleCode.M4, ErrorCategory.SYSTEM, 2)
        """事件总线错误"""
        SCHEDULER_ERROR = build_error_code(ModuleCode.M4, ErrorCategory.SYSTEM, 3)
        """调度器错误"""

    # 便捷别名
    M4_ERR = M4ErrorCode

else:
    # 回退模式
    class M4ErrorCode:
        """M4 错误码常量（回退模式）"""
        INVALID_SCENE_ID = 40101
        INVALID_SCENE_CONFIG = 40102
        INVALID_TRIGGER = 40103
        INVALID_CONDITION = 40104
        INVALID_ACTION = 40105
        INVALID_SCENE_NAME = 40106
        SCENE_NOT_FOUND = 40401
        TRIGGER_NOT_FOUND = 40402
        ACTION_NOT_FOUND = 40403
        SCENE_TEMPLATE_NOT_FOUND = 40404
        SCENE_ALREADY_EXISTS = 40501
        SCENE_ALREADY_ACTIVE = 40502
        SCENE_NOT_ACTIVE = 40503
        TRIGGER_CONFLICT = 40504
        ACTION_EXECUTION_FAILED = 40505
        CONDITION_EVALUATION_FAILED = 40506
        SCENE_CYCLE_DETECTED = 40507
        ENGINE_INIT_FAILED = 40601
        EVENT_BUS_ERROR = 40602
        SCHEDULER_ERROR = 40603

    M4_ERR = M4ErrorCode


__all__ = [
    "M4ErrorCode",
    "M4_ERR",
    "_UNIFIED_ERRORS_AVAILABLE",
]
