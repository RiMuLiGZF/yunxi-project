"""M9 开发者工坊 - 项目模板路由.

提供项目模板相关的 API 接口。
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, Request, HTTPException, Query, Body

# 导入配置和响应模型
try:
    from config import get_settings
except ImportError:
    from ..config import get_settings

try:
    from core.response import ApiResponse
except ImportError:
    from ..core.response import ApiResponse

try:
    from core.auth_middleware import get_current_user
except ImportError:
    from ..core.auth_middleware import get_current_user

# 导入模板管理器
try:
    from project_templates import get_template_manager
except ImportError:
    try:
        from ..project_templates import get_template_manager
    except ImportError:
        def get_template_manager():
            return None


router = APIRouter(prefix="/api/v1/templates", tags=["项目模板"])

_template_mgr = None


def _get_template_manager():
    """获取模板管理器实例."""
    global _template_mgr
    if _template_mgr is None:
        try:
            from project_templates import get_template_manager as _gtm
            _template_mgr = _gtm()
        except ImportError:
            pass
    return _template_mgr


@router.get("", summary="获取项目模板列表")
async def list_templates(
    request: Request,
    category: Optional[str] = Query(None, description="按分类筛选"),
    language: Optional[str] = Query(None, description="按语言筛选"),
    keyword: Optional[str] = Query(None, description="关键词搜索"),
    current_user: dict = Depends(get_current_user),
):
    """获取所有可用的项目模板列表，支持分类、语言筛选和关键词搜索。"""
    mgr = _get_template_manager()
    if not mgr:
        return ApiResponse.error(
            code=500,
            message="模板管理器不可用",
            request_id=request.headers.get("X-Request-ID", ""),
        )

    templates = mgr.list_templates(
        category=category,
        language=language,
        keyword=keyword,
    )

    # 获取分类列表
    categories = mgr.list_categories()

    return ApiResponse.success(
        data={
            "items": templates,
            "total": len(templates),
            "categories": categories,
        },
        request_id=request.headers.get("X-Request-ID", ""),
    )


@router.get("/categories", summary="获取模板分类列表")
async def list_template_categories(
    request: Request,
    current_user: dict = Depends(get_current_user),
):
    """获取所有模板分类及其模板数量。"""
    mgr = _get_template_manager()
    if not mgr:
        return ApiResponse.error(
            code=500,
            message="模板管理器不可用",
            request_id=request.headers.get("X-Request-ID", ""),
        )

    categories = mgr.list_categories()
    return ApiResponse.success(
        data=categories,
        request_id=request.headers.get("X-Request-ID", ""),
    )


@router.get("/{template_id}", summary="获取模板详情")
async def get_template_detail(
    request: Request,
    template_id: str,
    current_user: dict = Depends(get_current_user),
):
    """获取指定模板的详细信息，包含文件结构预览。"""
    mgr = _get_template_manager()
    if not mgr:
        return ApiResponse.error(
            code=500,
            message="模板管理器不可用",
            request_id=request.headers.get("X-Request-ID", ""),
        )

    template = mgr.get_template(template_id)
    if not template:
        return ApiResponse.error(
            code=404,
            message=f"模板不存在: {template_id}",
            request_id=request.headers.get("X-Request-ID", ""),
        )

    # 获取文件列表
    files = template.get("files", {})
    file_list = [
        {
            "path": path,
            "size": len(content.encode("utf-8")),
            "preview": content[:500] if len(content) > 500 else content,
            "is_truncated": len(content) > 500,
        }
        for path, content in files.items()
    ]

    return ApiResponse.success(
        data={
            **template,
            "file_list": file_list,
            "file_count": len(files),
        },
        request_id=request.headers.get("X-Request-ID", ""),
    )


@router.post("/{template_id}/create", summary="从模板创建项目")
async def create_from_template(
    request: Request,
    template_id: str,
    body: Dict[str, Any] = Body(default={}),
    current_user: dict = Depends(get_current_user),
):
    """从指定模板创建一个新项目。

    请求体：
    - project_name: 项目名称（必填）
    - project_path: 项目路径（可选，默认在工作区根目录下）
    - description: 项目描述（可选）
    """
    mgr = _get_template_manager()
    if not mgr:
        return ApiResponse.error(
            code=500,
            message="模板管理器不可用",
            request_id=request.headers.get("X-Request-ID", ""),
        )

    project_name = body.get("project_name", "")
    if not project_name:
        return ApiResponse.error(
            code=400,
            message="项目名称不能为空",
            request_id=request.headers.get("X-Request-ID", ""),
        )

    result = mgr.create_project_from_template(
        template_id=template_id,
        project_name=project_name,
        project_path=body.get("project_path"),
        description=body.get("description", ""),
    )

    if not result.get("success"):
        return ApiResponse.error(
            code=400,
            message=result.get("error", "创建项目失败"),
            request_id=request.headers.get("X-Request-ID", ""),
        )

    return ApiResponse.success(
        message="项目创建成功",
        data=result,
        request_id=request.headers.get("X-Request-ID", ""),
    )


@router.post("/custom", summary="保存自定义模板")
async def save_custom_template(
    request: Request,
    body: Dict[str, Any] = Body(...),
    current_user: dict = Depends(get_current_user),
):
    """保存自定义项目模板。

    请求体：
    - name: 模板名称
    - description: 模板描述
    - category: 分类
    - language: 语言
    - files: 文件字典 {path: content}
    - icon: 图标（可选）
    - tags: 标签列表（可选）
    """
    mgr = _get_template_manager()
    if not mgr:
        return ApiResponse.error(
            code=500,
            message="模板管理器不可用",
            request_id=request.headers.get("X-Request-ID", ""),
        )

    result = mgr.save_custom_template(template_data=body)

    if not result.get("success"):
        return ApiResponse.error(
            code=400,
            message=result.get("error", "保存模板失败"),
            request_id=request.headers.get("X-Request-ID", ""),
        )

    return ApiResponse.success(
        message="模板保存成功",
        data=result,
        request_id=request.headers.get("X-Request-ID", ""),
    )


@router.delete("/custom/{template_id}", summary="删除自定义模板")
async def delete_custom_template(
    request: Request,
    template_id: str,
    current_user: dict = Depends(get_current_user),
):
    """删除指定的自定义模板。"""
    mgr = _get_template_manager()
    if not mgr:
        return ApiResponse.error(
            code=500,
            message="模板管理器不可用",
            request_id=request.headers.get("X-Request-ID", ""),
        )

    result = mgr.delete_custom_template(template_id)

    if not result.get("success"):
        return ApiResponse.error(
            code=400,
            message=result.get("error", "删除模板失败"),
            request_id=request.headers.get("X-Request-ID", ""),
        )

    return ApiResponse.success(
        message="模板删除成功",
        request_id=request.headers.get("X-Request-ID", ""),
    )
