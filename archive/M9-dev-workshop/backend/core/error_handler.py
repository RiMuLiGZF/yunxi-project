"""云汐 M9 开发者工坊 - 统一错误处理

定义错误码体系、自定义异常类、全局异常处理器。
"""

from fastapi import Request
from fastapi.responses import JSONResponse
from typing import Optional, Dict, Any
import uuid
import time

# ===== 错误码定义 =====
# M9xxxy: M9-模块(xxx)-序号(y)
# 模块: 00=通用, 01=VSCode, 02=工作区, 03=MCP, 04=代码执行, 05=认证

class M9ErrorCode:
    """M9 错误码常量"""
    # 通用错误 400xx
    INVALID_PARAMS = (40001, "请求参数无效")
    NOT_FOUND = (40401, "资源不存在")
    INTERNAL_ERROR = (50001, "内部服务错误")
    SERVICE_UNAVAILABLE = (50301, "服务暂不可用")

    # VSCode 401xx
    VSCODE_NOT_INSTALLED = (40101, "VS Code 未安装")
    VSCODE_START_FAILED = (40102, "VS Code 启动失败")
    VSCODE_STOP_FAILED = (40103, "VS Code 停止失败")

    # 工作区 402xx
    PROJECT_NOT_FOUND = (40201, "项目不存在")
    PROJECT_PATH_EXISTS = (40202, "项目路径已存在")
    PATH_UNSAFE = (40203, "路径安全校验失败")

    # MCP 403xx
    MCP_TOOL_NOT_FOUND = (40301, "MCP 工具不存在")
    MCP_TOOL_DISABLED = (40302, "MCP 工具已禁用")
    MCP_CALL_FAILED = (40303, "MCP 工具调用失败")

    # 代码执行 404xx
    CODE_EXEC_LANGUAGE_UNSUPPORTED = (40401, "不支持的编程语言")
    CODE_EXEC_SANDBOX_BLOCKED = (40402, "沙箱安全检测未通过")
    CODE_EXEC_TIMEOUT = (40403, "代码执行超时")
    CODE_EXEC_FAILED = (40404, "代码执行失败")

    # 认证 405xx
    AUTH_TOKEN_INVALID = (40501, "Token 无效")
    AUTH_TOKEN_MISSING = (40502, "Token 缺失")
    AUTH_RATE_LIMITED = (40503, "请求频率超限")


class M9BaseException(Exception):
    """M9 基础异常类"""
    def __init__(self, code: int, message: str, detail: str = "", http_status: int = 500):
        self.code = code
        self.message = message
        self.detail = detail
        self.http_status = http_status
        super().__init__(message)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "code": self.code,
            "message": self.message,
            "detail": self.detail,
        }


class M9NotFoundError(M9BaseException):
    """资源不存在异常 (HTTP 404)"""
    def __init__(self, message: str = "资源不存在", detail: str = ""):
        super().__init__(M9ErrorCode.NOT_FOUND[0], message, detail, 404)


class M9PathUnsafeError(M9BaseException):
    """路径安全异常 (HTTP 400)"""
    def __init__(self, message: str = "路径安全校验失败", detail: str = ""):
        super().__init__(M9ErrorCode.PATH_UNSAFE[0], message, detail, 400)


class M9ValidationError(M9BaseException):
    """参数验证异常 (HTTP 422)"""
    def __init__(self, message: str = "参数验证失败", detail: str = ""):
        super().__init__(M9ErrorCode.INVALID_PARAMS[0], message, detail, 422)


def m9_error_response(
    code: int,
    message: str,
    detail: str = "",
    http_status: int = 500,
    request_id: Optional[str] = None,
) -> JSONResponse:
    """构建统一的错误响应"""
    return JSONResponse(
        status_code=http_status,
        content={
            "code": code,
            "message": message,
            "detail": detail,
            "request_id": request_id or str(uuid.uuid4())[:8],
            "timestamp": int(time.time()),
        },
    )


async def global_exception_handler(request: Request, exc: Exception):
    """全局异常处理器"""
    from core.logging_config import get_logger
    logger = get_logger("error_handler")
    request_id = str(uuid.uuid4())[:8]

    if isinstance(exc, M9BaseException):
        logger.warning(f"[{request_id}] M9Exception: {exc.code} - {exc.message}")
        return m9_error_response(exc.code, exc.message, exc.detail, exc.http_status, request_id)

    logger.error(f"[{request_id}] Unhandled exception: {type(exc).__name__}: {exc}", exc_info=True)
    return m9_error_response(50001, "内部服务错误", str(exc), 500, request_id)
