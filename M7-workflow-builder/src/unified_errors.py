"""
M7 工作流构建器 - 模块级错误码定义（统一 6 位错误码体系）

遵循云汐系统统一 6 位错误码规范：XX YY ZZ
  - XX = 07 (模块编号，M7)
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

    class M7ErrorCode(ModuleErrorCode):
        """M7 工作流构建器错误码常量.

        模块编号: 07
        范围: 070100 - 070999
        """
        MODULE = ModuleCode.M7

        # ---------- 参数错误 (0701xx) ----------
        INVALID_WORKFLOW_ID = build_error_code(ModuleCode.M7, ErrorCategory.VALIDATION, 1)
        """无效的工作流 ID"""
        INVALID_WORKFLOW_NAME = build_error_code(ModuleCode.M7, ErrorCategory.VALIDATION, 2)
        """无效的工作流名称"""
        INVALID_NODE_CONFIG = build_error_code(ModuleCode.M7, ErrorCategory.VALIDATION, 3)
        """无效的节点配置"""
        INVALID_EDGE_CONFIG = build_error_code(ModuleCode.M7, ErrorCategory.VALIDATION, 4)
        """无效的连线配置"""
        INVALID_VARIABLE = build_error_code(ModuleCode.M7, ErrorCategory.VALIDATION, 5)
        """无效的变量定义"""
        INVALID_TEMPLATE = build_error_code(ModuleCode.M7, ErrorCategory.VALIDATION, 6)
        """无效的模板"""

        # ---------- 资源不存在 (0704xx) ----------
        WORKFLOW_NOT_FOUND = build_error_code(ModuleCode.M7, ErrorCategory.NOT_FOUND, 1)
        """工作流不存在"""
        NODE_NOT_FOUND = build_error_code(ModuleCode.M7, ErrorCategory.NOT_FOUND, 2)
        """节点不存在"""
        TEMPLATE_NOT_FOUND = build_error_code(ModuleCode.M7, ErrorCategory.NOT_FOUND, 3)
        """模板不存在"""
        EXECUTION_NOT_FOUND = build_error_code(ModuleCode.M7, ErrorCategory.NOT_FOUND, 4)
        """执行记录不存在"""

        # ---------- 业务错误 (0705xx) ----------
        WORKFLOW_ALREADY_EXISTS = build_error_code(ModuleCode.M7, ErrorCategory.BUSINESS, 1)
        """工作流已存在"""
        WORKFLOW_RUNNING = build_error_code(ModuleCode.M7, ErrorCategory.BUSINESS, 2)
        """工作流正在运行"""
        WORKFLOW_NOT_RUNNING = build_error_code(ModuleCode.M7, ErrorCategory.BUSINESS, 3)
        """工作流未运行"""
        CYCLE_DETECTED = build_error_code(ModuleCode.M7, ErrorCategory.BUSINESS, 4)
        """检测到循环依赖"""
        NODE_EXECUTION_FAILED = build_error_code(ModuleCode.M7, ErrorCategory.BUSINESS, 5)
        """节点执行失败"""
        WORKFLOW_VALIDATION_FAILED = build_error_code(ModuleCode.M7, ErrorCategory.BUSINESS, 6)
        """工作流校验失败"""
        VARIABLE_RESOLUTION_FAILED = build_error_code(ModuleCode.M7, ErrorCategory.BUSINESS, 7)
        """变量解析失败"""
        TEMPLATE_IMPORT_FAILED = build_error_code(ModuleCode.M7, ErrorCategory.BUSINESS, 8)
        """模板导入失败"""
        TEMPLATE_EXPORT_FAILED = build_error_code(ModuleCode.M7, ErrorCategory.BUSINESS, 9)
        """模板导出失败"""
        WORKFLOW_SUSPENDED = build_error_code(ModuleCode.M7, ErrorCategory.BUSINESS, 10)
        """工作流已暂停"""

        # ---------- 系统错误 (0706xx) ----------
        EXECUTION_ENGINE_ERROR = build_error_code(ModuleCode.M7, ErrorCategory.SYSTEM, 1)
        """执行引擎错误"""
        STORAGE_ERROR = build_error_code(ModuleCode.M7, ErrorCategory.SYSTEM, 2)
        """存储错误"""
        SCHEDULER_ERROR = build_error_code(ModuleCode.M7, ErrorCategory.SYSTEM, 3)
        """调度器错误"""

    # 便捷别名
    M7_ERR = M7ErrorCode

else:
    # 回退模式
    class M7ErrorCode:
        """M7 错误码常量（回退模式）"""
        INVALID_WORKFLOW_ID = 70101
        INVALID_WORKFLOW_NAME = 70102
        INVALID_NODE_CONFIG = 70103
        INVALID_EDGE_CONFIG = 70104
        INVALID_VARIABLE = 70105
        INVALID_TEMPLATE = 70106
        WORKFLOW_NOT_FOUND = 70401
        NODE_NOT_FOUND = 70402
        TEMPLATE_NOT_FOUND = 70403
        EXECUTION_NOT_FOUND = 70404
        WORKFLOW_ALREADY_EXISTS = 70501
        WORKFLOW_RUNNING = 70502
        WORKFLOW_NOT_RUNNING = 70503
        CYCLE_DETECTED = 70504
        NODE_EXECUTION_FAILED = 70505
        WORKFLOW_VALIDATION_FAILED = 70506
        VARIABLE_RESOLUTION_FAILED = 70507
        TEMPLATE_IMPORT_FAILED = 70508
        TEMPLATE_EXPORT_FAILED = 70509
        WORKFLOW_SUSPENDED = 70510
        EXECUTION_ENGINE_ERROR = 70601
        STORAGE_ERROR = 70602
        SCHEDULER_ERROR = 70603

    M7_ERR = M7ErrorCode


__all__ = [
    "M7ErrorCode",
    "M7_ERR",
    "_UNIFIED_ERRORS_AVAILABLE",
]
