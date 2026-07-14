"""M9 统一错误码与异常"""

from enum import IntEnum
from fastapi import HTTPException


class ErrorCode(IntEnum):
    """M9 错误码枚举"""

    # 通用错误 (10xxx)
    INTERNAL_ERROR = 10001
    NOT_FOUND = 10002
    INVALID_PARAMS = 10003
    UNAUTHORIZED = 10004
    RATE_LIMITED = 10005

    # 代码执行错误 (11xxx)
    CODE_EXEC_FAILED = 11001
    CODE_EXEC_TIMEOUT = 11002
    CODE_EXEC_BLOCKED = 11003
    CODE_SIZE_EXCEEDED = 11004
    UNSUPPORTED_LANGUAGE = 11005

    # VSCode错误 (12xxx)
    VSCODE_NOT_FOUND = 12001
    VSCODE_START_FAILED = 12002
    VSCODE_OPEN_FAILED = 12003

    # 项目错误 (13xxx)
    PROJECT_NOT_FOUND = 13001
    PROJECT_CREATE_FAILED = 13002
    PROJECT_DELETE_FAILED = 13003
    PATH_TRAVERSAL = 13004


class M9Exception(Exception):
    """M9 模块统一异常"""

    def __init__(self, code: ErrorCode, message: str, detail: str = ""):
        self.code = code
        self.message = message
        self.detail = detail
        super().__init__(message)


def http_from_error(error: M9Exception) -> HTTPException:
    """将 M9Exception 转换为 HTTPException.

    Args:
        error: M9 模块异常

    Returns:
        对应的 HTTPException
    """
    status_map = {
        ErrorCode.NOT_FOUND: 404,
        ErrorCode.UNAUTHORIZED: 401,
        ErrorCode.RATE_LIMITED: 429,
        ErrorCode.INVALID_PARAMS: 400,
        ErrorCode.PATH_TRAVERSAL: 403,
    }
    status = status_map.get(error.code, 500)
    return HTTPException(
        status_code=status,
        detail={
            "code": error.code,
            "message": error.message,
            "detail": error.detail,
        },
    )
