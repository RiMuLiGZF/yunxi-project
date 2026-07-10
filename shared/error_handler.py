"""
云汐系统 - 统一错误处理模块
提供全局异常捕获、标准化错误响应格式、错误码定义
所有模块共用此错误处理规范，确保前后端交互一致
"""

from fastapi import Request, status
from fastapi.responses import JSONResponse
from fastapi.exceptions import HTTPException, RequestValidationError
from typing import Optional, Dict, Any
import logging
import traceback
from datetime import datetime

logger = logging.getLogger("yunxi.error_handler")


# ==================== 错误码定义 ====================

class ErrorCode:
    """统一错误码定义
    格式: 模块前缀(2位) + 错误类型(2位) + 序号(3位)
    模块前缀: 00-系统通用, 01-M1 Agent, 02-M2 Skill, 03-M3 Edge, 04-M4 Scene,
             05-M5 Memory, 06-M6 Device, 07-M7 Workflow, 08-M8 Control, 09-M9 Dev, 10-M10 Guard
    错误类型: 00-参数错误, 01-认证授权, 02-资源不存在, 03-业务逻辑, 04-系统错误, 05-第三方依赖
    """

    # 00xxxxx - 系统通用
    SUCCESS = 0
    UNKNOWN_ERROR = 10000
    INVALID_PARAMS = 10001
    RESOURCE_NOT_FOUND = 10002
    OPERATION_FAILED = 10003
    RATE_LIMITED = 10004
    SERVICE_UNAVAILABLE = 10005
    TIMEOUT = 10006

    # 0001xxx - 认证授权
    UNAUTHORIZED = 10100
    FORBIDDEN = 10101
    TOKEN_EXPIRED = 10102
    TOKEN_INVALID = 10103

    # 09xxxx - M9 开发者工坊
    M9_VSCODE_NOT_INSTALLED = 90001
    M9_VSCODE_START_FAILED = 90002
    M9_PROJECT_NOT_FOUND = 90003
    M9_MCP_TOOL_NOT_FOUND = 90004
    M9_MCP_CALL_FAILED = 90005


# ==================== 标准化异常类 ====================

class YunxiException(Exception):
    """云汐系统基础异常类"""

    def __init__(
        self,
        code: int,
        message: str,
        detail: Optional[Dict[str, Any]] = None,
        status_code: int = status.HTTP_400_BAD_REQUEST,
    ):
        self.code = code
        self.message = message
        self.detail = detail or {}
        self.status_code = status_code
        super().__init__(message)


class ParameterError(YunxiException):
    """参数错误"""

    def __init__(self, message: str = "参数错误", detail: Optional[Dict] = None):
        super().__init__(
            code=ErrorCode.INVALID_PARAMS,
            message=message,
            detail=detail,
            status_code=status.HTTP_400_BAD_REQUEST,
        )


class NotFoundError(YunxiException):
    """资源不存在"""

    def __init__(self, message: str = "资源不存在", detail: Optional[Dict] = None):
        super().__init__(
            code=ErrorCode.RESOURCE_NOT_FOUND,
            message=message,
            detail=detail,
            status_code=status.HTTP_404_NOT_FOUND,
        )


class BusinessError(YunxiException):
    """业务逻辑错误"""

    def __init__(
        self,
        message: str = "操作失败",
        code: int = ErrorCode.OPERATION_FAILED,
        detail: Optional[Dict] = None,
    ):
        super().__init__(
            code=code,
            message=message,
            detail=detail,
            status_code=status.HTTP_400_BAD_REQUEST,
        )


class AuthError(YunxiException):
    """认证授权错误"""

    def __init__(
        self,
        message: str = "未授权访问",
        code: int = ErrorCode.UNAUTHORIZED,
        detail: Optional[Dict] = None,
    ):
        super().__init__(
            code=code,
            message=message,
            detail=detail,
            status_code=status.HTTP_401_UNAUTHORIZED,
        )


class SystemError(YunxiException):
    """系统错误"""

    def __init__(
        self,
        message: str = "系统内部错误",
        code: int = ErrorCode.UNKNOWN_ERROR,
        detail: Optional[Dict] = None,
    ):
        super().__init__(
            code=code,
            message=message,
            detail=detail,
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )


# ==================== 标准化响应格式 ====================

def error_response(
    code: int,
    message: str,
    detail: Optional[Dict[str, Any]] = None,
    status_code: int = status.HTTP_400_BAD_REQUEST,
    request: Optional[Request] = None,
) -> JSONResponse:
    """生成标准化错误响应

    统一格式:
    {
        "success": false,
        "error": {
            "code": 错误码,
            "message": 错误信息,
            "detail": 详细信息,
            "timestamp": 时间戳,
            "path": 请求路径
        }
    }
    """
    error_body = {
        "success": False,
        "error": {
            "code": code,
            "message": message,
            "detail": detail or {},
            "timestamp": datetime.now().isoformat(),
        }
    }

    if request:
        error_body["error"]["path"] = request.url.path
        error_body["error"]["method"] = request.method

    return JSONResponse(
        status_code=status_code,
        content=error_body,
    )


def success_response(
    data: Any = None,
    message: str = "操作成功",
    **kwargs,
) -> Dict[str, Any]:
    """生成标准化成功响应

    统一格式:
    {
        "success": true,
        "message": 成功信息,
        "data": 数据,
        ... 其他字段
    }
    """
    result = {
        "success": True,
        "message": message,
        "data": data,
    }
    result.update(kwargs)
    return result


# ==================== 全局异常处理器 ====================

def register_exception_handlers(app):
    """为 FastAPI 应用注册全局异常处理器

    使用方式:
        from shared.error_handler import register_exception_handlers
        register_exception_handlers(app)
    """

    @app.exception_handler(YunxiException)
    async def yunxi_exception_handler(request: Request, exc: YunxiException):
        """处理云汐自定义异常"""
        logger.warning(f"[YunxiError] {exc.code} - {exc.message} - {request.url.path}")
        return error_response(
            code=exc.code,
            message=exc.message,
            detail=exc.detail,
            status_code=exc.status_code,
            request=request,
        )

    @app.exception_handler(HTTPException)
    async def http_exception_handler(request: Request, exc: HTTPException):
        """处理 FastAPI HTTPException，转换为统一格式"""
        # 将 detail 转换为标准格式
        detail = exc.detail
        if isinstance(detail, str):
            detail = {"reason": detail}
        elif not isinstance(detail, dict):
            detail = {"detail": detail}

        # 根据状态码映射错误码
        code_map = {
            400: ErrorCode.INVALID_PARAMS,
            401: ErrorCode.UNAUTHORIZED,
            403: ErrorCode.FORBIDDEN,
            404: ErrorCode.RESOURCE_NOT_FOUND,
            429: ErrorCode.RATE_LIMITED,
            500: ErrorCode.UNKNOWN_ERROR,
            503: ErrorCode.SERVICE_UNAVAILABLE,
        }
        code = code_map.get(exc.status_code, ErrorCode.UNKNOWN_ERROR)

        logger.warning(
            f"[HTTPError] {exc.status_code} - {exc.detail} - {request.url.path}"
        )

        return error_response(
            code=code,
            message=str(exc.detail) if isinstance(exc.detail, str) else "请求错误",
            detail=detail,
            status_code=exc.status_code,
            request=request,
        )

    @app.exception_handler(RequestValidationError)
    async def validation_exception_handler(request: Request, exc: RequestValidationError):
        """处理请求参数验证错误"""
        errors = []
        for err in exc.errors():
            errors.append({
                "field": " -> ".join(str(loc) for loc in err.get("loc", [])),
                "message": err.get("msg", ""),
                "type": err.get("type", ""),
            })

        logger.warning(f"[ValidationError] {len(errors)} errors - {request.url.path}")

        return error_response(
            code=ErrorCode.INVALID_PARAMS,
            message=f"请求参数验证失败，共 {len(errors)} 个错误",
            detail={"errors": errors},
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            request=request,
        )

    @app.exception_handler(Exception)
    async def general_exception_handler(request: Request, exc: Exception):
        """处理所有未捕获的异常"""
        # 记录完整堆栈
        tb_str = traceback.format_exc()
        logger.error(
            f"[UnhandledError] {type(exc).__name__}: {exc}\n"
            f"Path: {request.url.path}\n"
            f"{tb_str}"
        )

        # 生产环境不返回详细错误信息
        # debug 模式下返回堆栈信息
        debug = getattr(getattr(request.app, "state", None), "debug", False)
        detail = {}
        if debug:
            detail["exception_type"] = type(exc).__name__
            detail["traceback"] = tb_str

        return error_response(
            code=ErrorCode.UNKNOWN_ERROR,
            message="系统内部错误，请稍后重试或联系管理员",
            detail=detail,
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            request=request,
        )

    logger.info("[ErrorHandler] 全局异常处理器已注册")
