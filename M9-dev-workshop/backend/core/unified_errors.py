"""
M9 开发者工坊 - 模块级错误码定义
================================

遵循云汐系统统一 6 位错误码规范：XX YY ZZ
  - XX = 09（M9 开发者工坊）
  - YY = 错误类别
  - ZZ = 具体错误序号

模块范围：090100 - 090999

M9 原有错误码格式（3 位 + 模块前缀，如 401xx VSCode, 402xx 工作区）
通过兼容层映射到新的 6 位体系。
"""

from shared.core.errors import (
    ModuleCode,
    ErrorCategory,
    build_error_code,
    ModuleErrorCode,
)


class M9ErrorCode(ModuleErrorCode):
    """M9 开发者工坊错误码常量.

    模块编号: 09
    范围: 090100 - 090999
    """
    MODULE = ModuleCode.M9

    # ---------- 参数错误 (0901xx) ----------
    INVALID_PARAMS = build_error_code(ModuleCode.M9, ErrorCategory.VALIDATION, 1)
    """请求参数无效"""
    INVALID_PROJECT_NAME = build_error_code(ModuleCode.M9, ErrorCategory.VALIDATION, 2)
    """项目名称无效"""
    INVALID_FILE_PATH = build_error_code(ModuleCode.M9, ErrorCategory.VALIDATION, 3)
    """文件路径无效"""
    INVALID_CODE_LANGUAGE = build_error_code(ModuleCode.M9, ErrorCategory.VALIDATION, 4)
    """不支持的编程语言"""
    INVALID_TAG_FORMAT = build_error_code(ModuleCode.M9, ErrorCategory.VALIDATION, 5)
    """标签格式无效"""

    # ---------- 认证错误 (0902xx) ----------
    TOKEN_INVALID = build_error_code(ModuleCode.M9, ErrorCategory.AUTHENTICATION, 1)
    """Token 无效"""
    TOKEN_MISSING = build_error_code(ModuleCode.M9, ErrorCategory.AUTHENTICATION, 2)
    """Token 缺失"""
    ADMIN_TOKEN_REQUIRED = build_error_code(ModuleCode.M9, ErrorCategory.AUTHENTICATION, 3)
    """需要管理员 Token"""

    # ---------- 权限错误 (0903xx) ----------
    PERMISSION_DENIED = build_error_code(ModuleCode.M9, ErrorCategory.AUTHORIZATION, 1)
    """无访问权限"""
    WORKSPACE_ACCESS_DENIED = build_error_code(ModuleCode.M9, ErrorCategory.AUTHORIZATION, 2)
    """工作区访问被拒绝"""
    CODE_EXEC_FORBIDDEN = build_error_code(ModuleCode.M9, ErrorCategory.AUTHORIZATION, 3)
    """代码执行被禁止"""

    # ---------- 资源不存在 (0904xx) ----------
    PROJECT_NOT_FOUND = build_error_code(ModuleCode.M9, ErrorCategory.NOT_FOUND, 1)
    """项目不存在"""
    FILE_NOT_FOUND = build_error_code(ModuleCode.M9, ErrorCategory.NOT_FOUND, 2)
    """文件不存在"""
    VSCODE_NOT_FOUND = build_error_code(ModuleCode.M9, ErrorCategory.NOT_FOUND, 3)
    """VS Code 未安装"""
    MCP_TOOL_NOT_FOUND = build_error_code(ModuleCode.M9, ErrorCategory.NOT_FOUND, 4)
    """MCP 工具不存在"""
    BACKUP_NOT_FOUND = build_error_code(ModuleCode.M9, ErrorCategory.NOT_FOUND, 5)
    """备份不存在"""

    # ---------- 业务错误 (0905xx) ----------
    PROJECT_ALREADY_EXISTS = build_error_code(ModuleCode.M9, ErrorCategory.BUSINESS, 1)
    """项目已存在"""
    PROJECT_PATH_EXISTS = build_error_code(ModuleCode.M9, ErrorCategory.BUSINESS, 2)
    """项目路径已存在"""
    VSCODE_START_FAILED = build_error_code(ModuleCode.M9, ErrorCategory.BUSINESS, 3)
    """VS Code 启动失败"""
    VSCODE_STOP_FAILED = build_error_code(ModuleCode.M9, ErrorCategory.BUSINESS, 4)
    """VS Code 停止失败"""
    CODE_EXEC_TIMEOUT = build_error_code(ModuleCode.M9, ErrorCategory.BUSINESS, 5)
    """代码执行超时"""
    CODE_EXEC_FAILED = build_error_code(ModuleCode.M9, ErrorCategory.BUSINESS, 6)
    """代码执行失败"""
    MCP_CALL_FAILED = build_error_code(ModuleCode.M9, ErrorCategory.BUSINESS, 7)
    """MCP 工具调用失败"""
    MCP_TOOL_DISABLED = build_error_code(ModuleCode.M9, ErrorCategory.BUSINESS, 8)
    """MCP 工具已禁用"""
    BACKUP_CREATE_FAILED = build_error_code(ModuleCode.M9, ErrorCategory.BUSINESS, 9)
    """备份创建失败"""
    BACKUP_RESTORE_FAILED = build_error_code(ModuleCode.M9, ErrorCategory.BUSINESS, 10)
    """备份恢复失败"""
    SCAN_FAILED = build_error_code(ModuleCode.M9, ErrorCategory.BUSINESS, 11)
    """扫描失败"""

    # ---------- 系统错误 (0906xx) ----------
    INTERNAL_ERROR = build_error_code(ModuleCode.M9, ErrorCategory.SYSTEM, 1)
    """内部服务错误"""
    DATABASE_ERROR = build_error_code(ModuleCode.M9, ErrorCategory.SYSTEM, 2)
    """数据库错误"""
    WORKSPACE_INIT_FAILED = build_error_code(ModuleCode.M9, ErrorCategory.SYSTEM, 3)
    """工作区初始化失败"""

    # ---------- 第三方错误 (0907xx) ----------
    GIT_ERROR = build_error_code(ModuleCode.M9, ErrorCategory.THIRD_PARTY, 1)
    """Git 操作错误"""
    VSCODE_EXTENSION_ERROR = build_error_code(ModuleCode.M9, ErrorCategory.THIRD_PARTY, 2)
    """VS Code 扩展错误"""
    MCP_UPSTREAM_ERROR = build_error_code(ModuleCode.M9, ErrorCategory.THIRD_PARTY, 3)
    """MCP 上游服务错误"""

    # ---------- 限流错误 (0908xx) ----------
    RATE_LIMITED = build_error_code(ModuleCode.M9, ErrorCategory.RATE_LIMIT, 1)
    """请求频率超限"""
    CODE_EXEC_RATE_LIMITED = build_error_code(ModuleCode.M9, ErrorCategory.RATE_LIMIT, 2)
    """代码执行频率超限"""

    # ---------- 数据错误 (0909xx) ----------
    PATH_UNSAFE = build_error_code(ModuleCode.M9, ErrorCategory.DATA, 1)
    """路径安全校验失败"""
    SANDBOX_VIOLATION = build_error_code(ModuleCode.M9, ErrorCategory.DATA, 2)
    """沙箱安全违规"""
    DATA_CORRUPTED = build_error_code(ModuleCode.M9, ErrorCategory.DATA, 3)
    """数据损坏"""


# M9 旧错误码 -> 新 6 位错误码 映射
# 旧格式: 400xx=通用, 401xx=VSCode, 402xx=工作区, 403xx=MCP, 404xx=代码执行, 405xx=认证
M9_LEGACY_ERROR_MAP = {
    40001: M9ErrorCode.INVALID_PARAMS,
    40401: M9ErrorCode.PROJECT_NOT_FOUND,
    50001: M9ErrorCode.INTERNAL_ERROR,
    50301: M9ErrorCode.INTERNAL_ERROR,  # 服务暂不可用
    40101: M9ErrorCode.VSCODE_NOT_FOUND,
    40102: M9ErrorCode.VSCODE_START_FAILED,
    40103: M9ErrorCode.VSCODE_STOP_FAILED,
    40201: M9ErrorCode.PROJECT_NOT_FOUND,
    40202: M9ErrorCode.PROJECT_PATH_EXISTS,
    40203: M9ErrorCode.PATH_UNSAFE,
    40301: M9ErrorCode.MCP_TOOL_NOT_FOUND,
    40302: M9ErrorCode.MCP_TOOL_DISABLED,
    40303: M9ErrorCode.MCP_CALL_FAILED,
    40401: M9ErrorCode.INVALID_CODE_LANGUAGE,
    40402: M9ErrorCode.SANDBOX_VIOLATION,
    40403: M9ErrorCode.CODE_EXEC_TIMEOUT,
    40404: M9ErrorCode.CODE_EXEC_FAILED,
    40501: M9ErrorCode.TOKEN_INVALID,
    40502: M9ErrorCode.TOKEN_MISSING,
    40503: M9ErrorCode.RATE_LIMITED,
}


# 便捷别名
M9_ERR = M9ErrorCode
