"""M9 开发者工坊 - 文件管理路由.

提供项目文件管理相关的 API 接口。
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


router = APIRouter(prefix="/api/v1/files", tags=["文件管理"])

_file_manager = None


def _get_file_manager():
    """获取文件管理器实例."""
    global _file_manager
    if _file_manager is None:
        try:
            from file_manager import get_file_manager as _gfm
            _file_manager = _gfm()
        except ImportError:
            pass
    return _file_manager


@router.get("/tree", summary="获取项目文件树")
async def get_file_tree(
    request: Request,
    project_path: str = Query(..., description="项目路径"),
    max_depth: int = Query(5, description="最大深度"),
    show_hidden: bool = Query(False, description="是否显示隐藏文件"),
    current_user: dict = Depends(get_current_user),
):
    """获取指定项目的文件树结构。"""
    fm = _get_file_manager()
    if not fm:
        return ApiResponse.error(
            code=500,
            message="文件管理器不可用",
            request_id=request.headers.get("X-Request-ID", ""),
        )

    result = fm.get_file_tree(
        project_path=project_path,
        max_depth=max_depth,
        show_hidden=show_hidden,
    )

    if not result.get("success"):
        return ApiResponse.error(
            code=400,
            message=result.get("error", "获取文件树失败"),
            request_id=request.headers.get("X-Request-ID", ""),
        )

    return ApiResponse.success(
        data=result,
        request_id=request.headers.get("X-Request-ID", ""),
    )


@router.get("/read", summary="读取文件内容")
async def read_file(
    request: Request,
    project_path: str = Query(..., description="项目路径"),
    file_path: str = Query(..., description="文件相对路径"),
    max_size_kb: int = Query(1024, description="最大读取大小(KB)"),
    current_user: dict = Depends(get_current_user),
):
    """读取指定文件的内容。"""
    fm = _get_file_manager()
    if not fm:
        return ApiResponse.error(
            code=500,
            message="文件管理器不可用",
            request_id=request.headers.get("X-Request-ID", ""),
        )

    result = fm.read_file(
        project_path=project_path,
        file_path=file_path,
        max_size_kb=max_size_kb,
    )

    if not result.get("success"):
        return ApiResponse.error(
            code=400,
            message=result.get("error", "读取文件失败"),
            request_id=request.headers.get("X-Request-ID", ""),
        )

    return ApiResponse.success(
        data=result,
        request_id=request.headers.get("X-Request-ID", ""),
    )


@router.post("/write", summary="写入文件内容")
async def write_file(
    request: Request,
    body: Dict[str, Any] = Body(...),
    current_user: dict = Depends(get_current_user),
):
    """写入文件内容。

    请求体：
    - project_path: 项目路径
    - file_path: 文件相对路径
    - content: 文件内容
    - create_parents: 是否自动创建父目录（默认 true）
    """
    fm = _get_file_manager()
    if not fm:
        return ApiResponse.error(
            code=500,
            message="文件管理器不可用",
            request_id=request.headers.get("X-Request-ID", ""),
        )

    project_path = body.get("project_path", "")
    file_path = body.get("file_path", "")
    content = body.get("content", "")

    if not project_path or not file_path:
        return ApiResponse.error(
            code=400,
            message="项目路径和文件路径不能为空",
            request_id=request.headers.get("X-Request-ID", ""),
        )

    result = fm.write_file(
        project_path=project_path,
        file_path=file_path,
        content=content,
        create_parents=body.get("create_parents", True),
    )

    if not result.get("success"):
        return ApiResponse.error(
            code=400,
            message=result.get("error", "写入文件失败"),
            request_id=request.headers.get("X-Request-ID", ""),
        )

    return ApiResponse.success(
        message="文件写入成功",
        data=result,
        request_id=request.headers.get("X-Request-ID", ""),
    )


@router.get("/search", summary="搜索文件")
async def search_files(
    request: Request,
    project_path: str = Query(..., description="项目路径"),
    query: str = Query(..., description="搜索关键词"),
    search_content: bool = Query(False, description="是否搜索文件内容"),
    file_pattern: Optional[str] = Query(None, description="文件模式过滤"),
    max_results: int = Query(50, description="最大结果数"),
    current_user: dict = Depends(get_current_user),
):
    """在项目中搜索文件，支持文件名和内容搜索。"""
    fm = _get_file_manager()
    if not fm:
        return ApiResponse.error(
            code=500,
            message="文件管理器不可用",
            request_id=request.headers.get("X-Request-ID", ""),
        )

    result = fm.search_files(
        project_path=project_path,
        query=query,
        search_content=search_content,
        file_pattern=file_pattern,
        max_results=max_results,
    )

    if not result.get("success"):
        return ApiResponse.error(
            code=400,
            message=result.get("error", "搜索失败"),
            request_id=request.headers.get("X-Request-ID", ""),
        )

    return ApiResponse.success(
        data=result,
        request_id=request.headers.get("X-Request-ID", ""),
    )


@router.post("/batch", summary="批量文件操作")
async def batch_operation(
    request: Request,
    body: Dict[str, Any] = Body(...),
    current_user: dict = Depends(get_current_user),
):
    """批量文件操作（删除、复制、移动等）。

    请求体：
    - project_path: 项目路径
    - operation: 操作类型（delete/copy/move）
    - files: 文件路径列表
    - destination: 目标路径（copy/move 需要）
    """
    fm = _get_file_manager()
    if not fm:
        return ApiResponse.error(
            code=500,
            message="文件管理器不可用",
            request_id=request.headers.get("X-Request-ID", ""),
        )

    project_path = body.get("project_path", "")
    operation = body.get("operation", "")
    files = body.get("files", [])

    if not project_path or not operation or not files:
        return ApiResponse.error(
            code=400,
            message="参数不完整",
            request_id=request.headers.get("X-Request-ID", ""),
        )

    result = fm.batch_operation(
        project_path=project_path,
        operation=operation,
        files=files,
        destination=body.get("destination", ""),
    )

    if not result.get("success"):
        return ApiResponse.error(
            code=400,
            message=result.get("error", "批量操作失败"),
            request_id=request.headers.get("X-Request-ID", ""),
        )

    return ApiResponse.success(
        message="批量操作完成",
        data=result,
        request_id=request.headers.get("X-Request-ID", ""),
    )


@router.get("/info", summary="获取文件信息")
async def get_file_info(
    request: Request,
    project_path: str = Query(..., description="项目路径"),
    file_path: str = Query(..., description="文件相对路径"),
    current_user: dict = Depends(get_current_user),
):
    """获取文件或目录的详细信息。"""
    fm = _get_file_manager()
    if not fm:
        return ApiResponse.error(
            code=500,
            message="文件管理器不可用",
            request_id=request.headers.get("X-Request-ID", ""),
        )

    result = fm.get_file_info(
        project_path=project_path,
        file_path=file_path,
    )

    if not result.get("success"):
        return ApiResponse.error(
            code=400,
            message=result.get("error", "获取文件信息失败"),
            request_id=request.headers.get("X-Request-ID", ""),
        )

    return ApiResponse.success(
        data=result,
        request_id=request.headers.get("X-Request-ID", ""),
    )


@router.post("/mkdir", summary="创建目录")
async def create_directory(
    request: Request,
    body: Dict[str, Any] = Body(...),
    current_user: dict = Depends(get_current_user),
):
    """创建新目录。

    请求体：
    - project_path: 项目路径
    - dir_path: 目录相对路径
    """
    fm = _get_file_manager()
    if not fm:
        return ApiResponse.error(
            code=500,
            message="文件管理器不可用",
            request_id=request.headers.get("X-Request-ID", ""),
        )

    project_path = body.get("project_path", "")
    dir_path = body.get("dir_path", "")

    if not project_path or not dir_path:
        return ApiResponse.error(
            code=400,
            message="参数不完整",
            request_id=request.headers.get("X-Request-ID", ""),
        )

    result = fm.create_directory(
        project_path=project_path,
        dir_path=dir_path,
    )

    if not result.get("success"):
        return ApiResponse.error(
            code=400,
            message=result.get("error", "创建目录失败"),
            request_id=request.headers.get("X-Request-ID", ""),
        )

    return ApiResponse.success(
        message="目录创建成功",
        data=result,
        request_id=request.headers.get("X-Request-ID", ""),
    )
