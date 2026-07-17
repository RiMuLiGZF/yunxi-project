"""M9 开发者工坊 - 代码质量工具路由.

提供代码格式化、检查、类型检查等质量工具的 API 接口。
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, Request, HTTPException, Query, Body

try:
    from core.response import ApiResponse
except ImportError:
    from ..core.response import ApiResponse

try:
    from core.auth_middleware import get_current_user
except ImportError:
    from ..core.auth_middleware import get_current_user


router = APIRouter(prefix="/api/v1/quality", tags=["代码质量"])

_quality_mgr = None


def _get_quality_manager():
    """获取代码质量管理器实例."""
    global _quality_mgr
    if _quality_mgr is None:
        try:
            from code_quality import get_code_quality_manager as _gcqm
            _quality_mgr = _gcqm()
        except ImportError:
            pass
    return _quality_mgr


@router.get("/tools", summary="获取可用的代码质量工具")
async def list_quality_tools(
    request: Request,
    current_user: dict = Depends(get_current_user),
):
    """获取当前环境中可用的代码质量工具列表。"""
    mgr = _get_quality_manager()
    if not mgr:
        return ApiResponse.error(
            code=500,
            message="代码质量管理器不可用",
            request_id=request.headers.get("X-Request-ID", ""),
        )

    tools = mgr.get_available_tools()
    return ApiResponse.success(
        data={
            "tools": tools,
            "descriptions": {
                "black": "Python 代码格式化工具",
                "ruff": "Rust 实现的 Python linter",
                "ruff_format": "Ruff 代码格式化",
                "flake8": "Python 代码风格检查工具",
                "mypy": "Python 静态类型检查器",
            },
        },
        request_id=request.headers.get("X-Request-ID", ""),
    )


@router.post("/format", summary="格式化代码")
async def format_code(
    request: Request,
    body: Dict[str, Any] = Body(...),
    current_user: dict = Depends(get_current_user),
):
    """格式化代码。

    请求体：
    - code: 代码内容
    - tool: 工具（black/ruff_format，默认 black）
    - line_length: 行长度（默认 88）
    """
    mgr = _get_quality_manager()
    if not mgr:
        return ApiResponse.error(
            code=500,
            message="代码质量管理器不可用",
            request_id=request.headers.get("X-Request-ID", ""),
        )

    code = body.get("code", "")
    if not code:
        return ApiResponse.error(
            code=400,
            message="代码内容不能为空",
            request_id=request.headers.get("X-Request-ID", ""),
        )

    result = mgr.format_code(
        code=code,
        tool=body.get("tool", "black"),
        line_length=body.get("line_length", 88),
    )

    if not result.get("success"):
        return ApiResponse.error(
            code=400,
            message=result.get("error", "格式化失败"),
            data=result,
            request_id=request.headers.get("X-Request-ID", ""),
        )

    return ApiResponse.success(
        message="格式化完成",
        data=result,
        request_id=request.headers.get("X-Request-ID", ""),
    )


@router.post("/lint", summary="代码质量检查")
async def lint_code(
    request: Request,
    body: Dict[str, Any] = Body(...),
    current_user: dict = Depends(get_current_user),
):
    """检查代码质量。

    请求体：
    - code: 代码内容
    - tool: 工具（ruff/flake8，默认 ruff）
    - select: 选择的规则列表（可选）
    """
    mgr = _get_quality_manager()
    if not mgr:
        return ApiResponse.error(
            code=500,
            message="代码质量管理器不可用",
            request_id=request.headers.get("X-Request-ID", ""),
        )

    code = body.get("code", "")
    if not code:
        return ApiResponse.error(
            code=400,
            message="代码内容不能为空",
            request_id=request.headers.get("X-Request-ID", ""),
        )

    result = mgr.lint_code(
        code=code,
        tool=body.get("tool", "ruff"),
        select=body.get("select"),
    )

    if not result.get("success"):
        return ApiResponse.error(
            code=400,
            message=result.get("error", "检查失败"),
            data=result,
            request_id=request.headers.get("X-Request-ID", ""),
        )

    return ApiResponse.success(
        message="检查完成",
        data=result,
        request_id=request.headers.get("X-Request-ID", ""),
    )


@router.post("/type-check", summary="类型检查")
async def type_check(
    request: Request,
    body: Dict[str, Any] = Body(...),
    current_user: dict = Depends(get_current_user),
):
    """对代码进行静态类型检查。

    请求体：
    - code: 代码内容
    - strict: 是否使用严格模式（默认 false）
    """
    mgr = _get_quality_manager()
    if not mgr:
        return ApiResponse.error(
            code=500,
            message="代码质量管理器不可用",
            request_id=request.headers.get("X-Request-ID", ""),
        )

    code = body.get("code", "")
    if not code:
        return ApiResponse.error(
            code=400,
            message="代码内容不能为空",
            request_id=request.headers.get("X-Request-ID", ""),
        )

    result = mgr.type_check(
        code=code,
        strict=body.get("strict", False),
    )

    if not result.get("success"):
        return ApiResponse.error(
            code=400,
            message=result.get("error", "类型检查失败"),
            data=result,
            request_id=request.headers.get("X-Request-ID", ""),
        )

    return ApiResponse.success(
        message="类型检查完成",
        data=result,
        request_id=request.headers.get("X-Request-ID", ""),
    )


@router.post("/complexity", summary="代码复杂度分析")
async def analyze_complexity(
    request: Request,
    body: Dict[str, Any] = Body(...),
    current_user: dict = Depends(get_current_user),
):
    """分析代码的复杂度（基于 AST，不依赖外部工具）。

    请求体：
    - code: 代码内容
    """
    mgr = _get_quality_manager()
    if not mgr:
        return ApiResponse.error(
            code=500,
            message="代码质量管理器不可用",
            request_id=request.headers.get("X-Request-ID", ""),
        )

    code = body.get("code", "")
    if not code:
        return ApiResponse.error(
            code=400,
            message="代码内容不能为空",
            request_id=request.headers.get("X-Request-ID", ""),
        )

    result = mgr.analyze_complexity(code=code)

    if not result.get("success"):
        return ApiResponse.error(
            code=400,
            message=result.get("error", "复杂度分析失败"),
            data=result,
            request_id=request.headers.get("X-Request-ID", ""),
        )

    return ApiResponse.success(
        message="复杂度分析完成",
        data=result,
        request_id=request.headers.get("X-Request-ID", ""),
    )


@router.post("/report", summary="综合质量报告")
async def full_quality_report(
    request: Request,
    body: Dict[str, Any] = Body(...),
    current_user: dict = Depends(get_current_user),
):
    """生成代码综合质量报告。

    请求体：
    - code: 代码内容
    - tools: 要运行的工具列表（可选，默认全部）
    """
    mgr = _get_quality_manager()
    if not mgr:
        return ApiResponse.error(
            code=500,
            message="代码质量管理器不可用",
            request_id=request.headers.get("X-Request-ID", ""),
        )

    code = body.get("code", "")
    if not code:
        return ApiResponse.error(
            code=400,
            message="代码内容不能为空",
            request_id=request.headers.get("X-Request-ID", ""),
        )

    result = mgr.full_quality_report(
        code=code,
        tools=body.get("tools"),
    )

    if not result.get("success"):
        return ApiResponse.error(
            code=400,
            message=result.get("error", "质量报告生成失败"),
            data=result,
            request_id=request.headers.get("X-Request-ID", ""),
        )

    return ApiResponse.success(
        message="质量报告生成完成",
        data=result,
        request_id=request.headers.get("X-Request-ID", ""),
    )
