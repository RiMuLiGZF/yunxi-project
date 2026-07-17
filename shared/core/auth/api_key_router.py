"""
API Key 管理 - FastAPI Router

提供完整的 API Key 管理 REST 接口，可直接挂载到任意 FastAPI 应用中。
支持创建、查询、更新、吊销、轮换等完整生命周期管理。

用法：
    from fastapi import FastAPI
    from shared.core.auth.api_key_router import create_api_key_router
    from shared.core.auth.api_key_manager import get_api_key_manager

    app = FastAPI()
    manager = get_api_key_manager()

    # 挂载管理 API（需要 admin 级别认证保护）
    app.include_router(
        create_api_key_router(manager),
        prefix="/api-keys",
        tags=["API Keys"],
    )

    # 可选：启用服务间调用验证中间件
"""

import logging
from typing import Optional, List, Dict, Any
from datetime import datetime

try:
    from fastapi import APIRouter, HTTPException, Query, status, Request
    from pydantic import BaseModel, Field
    _fastapi_available = True
except ImportError:  # pragma: no cover
    _fastapi_available = False
    APIRouter = None
    HTTPException = None
    Query = None
    status = None
    Request = None
    BaseModel = object
    Field = lambda *args, **kwargs: None  # noqa: E731

from .api_key_manager import (
    ApiKeyManager,
    ApiKeyLevel,
    ManagedApiKeyInfo,
)

logger = logging.getLogger(__name__)


def is_fastapi_available() -> bool:
    """检查 FastAPI 是否可用"""
    return _fastapi_available


# ===========================================================================
# Pydantic 模型（FastAPI 可用时才有效）
# ===========================================================================

if _fastapi_available:

    class CreateKeyRequest(BaseModel):
        """创建 Key 请求"""
        name: str = Field(..., min_length=1, max_length=100, description="Key 名称")
        level: ApiKeyLevel = Field(default=ApiKeyLevel.SERVICE, description="权限级别")
        owner: str = Field(default="", max_length=100, description="所有者")
        expires_at: Optional[datetime] = Field(default=None, description="过期时间")
        scopes: Optional[List[str]] = Field(default=None, description="权限范围（None=使用级别默认值）")
        rate_limit: Optional[Dict[str, int]] = Field(default=None, description="限流配置")
        description: str = Field(default="", max_length=500, description="描述")
        prefix: str = Field(default="yx-", max_length=20, description="Key 前缀")
        extra: Optional[Dict[str, Any]] = Field(default=None, description="扩展字段")

    class UpdateKeyRequest(BaseModel):
        """更新 Key 请求"""
        name: Optional[str] = Field(default=None, min_length=1, max_length=100)
        owner: Optional[str] = Field(default=None, max_length=100)
        level: Optional[ApiKeyLevel] = Field(default=None)
        scopes: Optional[List[str]] = Field(default=None)
        expires_at: Optional[datetime] = Field(default=None)
        description: Optional[str] = Field(default=None, max_length=500)
        rate_limit: Optional[Dict[str, int]] = Field(default=None)
        extra: Optional[Dict[str, Any]] = Field(default=None)

    class RevokeKeyRequest(BaseModel):
        """吊销 Key 请求"""
        reason: str = Field(default="", max_length=200, description="吊销原因")

    class RotateKeyRequest(BaseModel):
        """轮换 Key 请求"""
        grace_days: int = Field(default=7, ge=1, le=30, description="旧 Key 宽限天数")

    class CreateKeyResponse(BaseModel):
        """创建 Key 响应（仅创建时返回明文）"""
        api_key: str = Field(..., description="明文 API Key（仅显示一次）")
        key_info: Dict[str, Any] = Field(..., description="Key 信息")

    class KeyListResponse(BaseModel):
        """Key 列表响应"""
        items: List[Dict[str, Any]] = Field(..., description="Key 列表")
        total: int = Field(..., description="总数")
        page: int = Field(..., description="当前页码")
        page_size: int = Field(..., description="每页数量")

    class VerifyKeyRequest(BaseModel):
        """验证 Key 请求"""
        api_key: str = Field(..., description="API Key 明文")
        required_level: Optional[ApiKeyLevel] = Field(default=None, description="要求的最低级别")
        required_scopes: Optional[List[str]] = Field(default=None, description="要求的权限范围")


# ===========================================================================
# Router 创建函数
# ===========================================================================

def create_api_key_router(
    manager: ApiKeyManager,
    require_admin: bool = True,
    admin_check_dependency=None,
) -> "APIRouter":
    """创建 API Key 管理 Router

    Args:
        manager: ApiKeyManager 实例
        require_admin: 是否要求管理员权限（建议生产环境开启）
        admin_check_dependency: 自定义管理员权限检查依赖（FastAPI Depends）
            如果为 None 且 require_admin=True，则使用 manager 自身的 admin Key 验证

    Returns:
        FastAPI APIRouter 实例

    Raises:
        RuntimeError: FastAPI 不可用时
    """
    if not _fastapi_available:
        raise RuntimeError("FastAPI 不可用，请先安装: pip install fastapi")

    router = APIRouter()

    # -------------------------------------------------------------------
    # 认证依赖
    # -------------------------------------------------------------------

    def _admin_key_dependency(request: Request) -> Dict[str, Any]:
        """默认的管理员 Key 验证依赖

        从 X-API-Key 或 Authorization: Bearer 中提取 Key，
        验证是否为 admin 级别。
        """
        if not require_admin:
            return {"auth_type": "none", "level": "admin"}

        api_key = request.headers.get("x-api-key")
        if not api_key:
            auth = request.headers.get("authorization", "")
            if auth.lower().startswith("bearer "):
                api_key = auth[7:].strip()

        if not api_key:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="缺少 API Key，请在 X-API-Key 或 Authorization: Bearer 请求头中提供",
                headers={"WWW-Authenticate": "Bearer"},
            )

        key_info = manager.verify_key(api_key, required_level=ApiKeyLevel.ADMIN)
        if not key_info:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="API Key 无效或权限不足（需要 admin 级别）",
                headers={"WWW-Authenticate": "Bearer"},
            )

        return {
            "auth_type": "api_key",
            "key_id": key_info.key_id,
            "key_name": key_info.key_name,
            "level": key_info.level.value,
            "scopes": key_info.scopes,
        }

    # 使用自定义依赖或默认依赖
    admin_dep = admin_check_dependency if admin_check_dependency is not None else _admin_key_dependency

    # -------------------------------------------------------------------
    # 路由 - 创建 Key
    # -------------------------------------------------------------------

    @router.post("", response_model=CreateKeyResponse, status_code=status.HTTP_201_CREATED)
    async def create_key(
        request: CreateKeyRequest,
        current_user: dict = Depends(admin_dep),  # type: ignore
    ):
        """创建新的 API Key

        创建后返回明文 Key，**仅显示一次**，请妥善保存。
        """
        try:
            api_key, key_info = manager.create_key(
                name=request.name,
                level=request.level,
                owner=request.owner,
                expires_at=request.expires_at,
                scopes=request.scopes,
                rate_limit=request.rate_limit,
                description=request.description,
                created_by=current_user.get("key_name", "api"),
                extra=request.extra,
                prefix=request.prefix,
            )
            return CreateKeyResponse(
                api_key=api_key,
                key_info=key_info.to_dict(),
            )
        except ValueError as e:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=str(e),
            )

    # -------------------------------------------------------------------
    # 路由 - 列出 Key
    # -------------------------------------------------------------------

    @router.get("", response_model=KeyListResponse)
    async def list_keys(
        owner: Optional[str] = Query(default=None, description="按所有者筛选"),
        level: Optional[ApiKeyLevel] = Query(default=None, description="按级别筛选"),
        status_filter: Optional[str] = Query(
            default=None, alias="status", description="按状态筛选：active/revoked/rotated/expired"
        ),
        page: int = Query(default=1, ge=1, description="页码"),
        page_size: int = Query(default=50, ge=1, le=200, description="每页数量"),
        current_user: dict = Depends(admin_dep),  # type: ignore
    ):
        """列出 API Key（分页、筛选）"""
        keys, total = manager.list_keys(
            owner=owner,
            level=level,
            status=status_filter,
            page=page,
            page_size=page_size,
        )
        return KeyListResponse(
            items=[k.to_dict() for k in keys],
            total=total,
            page=page,
            page_size=page_size,
        )

    # -------------------------------------------------------------------
    # 路由 - 获取 Key 详情
    # -------------------------------------------------------------------

    @router.get("/{key_id}")
    async def get_key(
        key_id: str,
        current_user: dict = Depends(admin_dep),  # type: ignore
    ):
        """获取单个 API Key 详情"""
        key_info = manager.get_key(key_id)
        if not key_info:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Key 不存在: {key_id}",
            )
        return key_info.to_dict()

    # -------------------------------------------------------------------
    # 路由 - 更新 Key
    # -------------------------------------------------------------------

    @router.put("/{key_id}")
    async def update_key(
        key_id: str,
        request: UpdateKeyRequest,
        current_user: dict = Depends(admin_dep),  # type: ignore
    ):
        """更新 API Key 配置"""
        updated = manager.update_key(
            key_id=key_id,
            name=request.name,
            owner=request.owner,
            scopes=request.scopes,
            level=request.level,
            expires_at=request.expires_at,
            description=request.description,
            extra=request.extra,
            rate_limit=request.rate_limit,
        )
        if not updated:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Key 不存在: {key_id}",
            )
        return updated.to_dict()

    # -------------------------------------------------------------------
    # 路由 - 吊销 Key
    # -------------------------------------------------------------------

    @router.delete("/{key_id}", status_code=status.HTTP_200_OK)
    async def revoke_key(
        key_id: str,
        reason: str = Query(default="", description="吊销原因"),
        current_user: dict = Depends(admin_dep),  # type: ignore
    ):
        """吊销 API Key

        吊销后 Key 立即失效，不可恢复。
        """
        success = manager.revoke_key(key_id, reason=reason)
        if not success:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Key 不存在: {key_id}",
            )
        return {"message": "Key 已吊销", "key_id": key_id}

    # -------------------------------------------------------------------
    # 路由 - 轮换 Key
    # -------------------------------------------------------------------

    @router.post("/{key_id}/rotate", response_model=CreateKeyResponse)
    async def rotate_key(
        key_id: str,
        request: RotateKeyRequest,
        current_user: dict = Depends(admin_dep),  # type: ignore
    ):
        """轮换 API Key

        创建新 Key，旧 Key 在宽限期后失效（默认 7 天）。
        新 Key 的明文**仅显示一次**。
        """
        try:
            new_api_key, new_key_info = manager.rotate_key(
                key_id,
                grace_days=request.grace_days,
            )
            return CreateKeyResponse(
                api_key=new_api_key,
                key_info=new_key_info.to_dict(),
            )
        except ValueError as e:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=str(e),
            )

    # -------------------------------------------------------------------
    # 路由 - 重新生成 Key（等同于轮换，但旧 Key 立即失效）
    # -------------------------------------------------------------------

    @router.post("/{key_id}/regenerate", response_model=CreateKeyResponse)
    async def regenerate_key(
        key_id: str,
        current_user: dict = Depends(admin_dep),  # type: ignore
    ):
        """重新生成 API Key

        旧 Key 立即吊销，生成新 Key。新 Key 明文**仅显示一次**。
        """
        key_info = manager.get_key(key_id)
        if not key_info:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Key 不存在: {key_id}",
            )

        # 先吊销旧 Key
        manager.revoke_key(key_id, reason="regenerate")

        # 创建新 Key（同级同配置）
        api_key, new_info = manager.create_key(
            name=key_info.key_name,
            level=key_info.level,
            owner=key_info.owner,
            expires_at=key_info.expires_at,
            scopes=list(key_info.scopes),
            rate_limit=key_info.quota.to_dict(),
            description=f"{key_info.description} (regenerated)",
            created_by=current_user.get("key_name", "api"),
            extra={**key_info.extra, "regenerated_from": key_id},
        )

        return CreateKeyResponse(
            api_key=api_key,
            key_info=new_info.to_dict(),
        )

    # -------------------------------------------------------------------
    # 路由 - 统计信息
    # -------------------------------------------------------------------

    @router.get("/stats/summary")
    async def get_stats(
        current_user: dict = Depends(admin_dep),  # type: ignore
    ):
        """获取 API Key 统计概览"""
        return manager.get_key_stats()

    # -------------------------------------------------------------------
    # 路由 - 使用量统计
    # -------------------------------------------------------------------

    @router.get("/stats/usage")
    async def get_usage_stats(
        current_user: dict = Depends(admin_dep),  # type: ignore
    ):
        """获取使用量统计（Top Key 排行等）"""
        return manager.get_usage_stats()

    # -------------------------------------------------------------------
    # 路由 - 验证 Key（公开端点，用于服务自检）
    # -------------------------------------------------------------------

    @router.post("/verify")
    async def verify_key_endpoint(request: VerifyKeyRequest):
        """验证 API Key（公开端点）

        验证 Key 是否有效以及是否满足级别/范围要求。
        不返回敏感信息，仅返回验证结果。
        """
        key_info = manager.verify_key(
            request.api_key,
            required_level=request.required_level,
            required_scopes=request.required_scopes,
        )
        if not key_info:
            return {
                "valid": False,
                "reason": "invalid_key_or_insufficient_permissions",
            }
        return {
            "valid": True,
            "key_id": key_info.key_id,
            "key_name": key_info.key_name,
            "key_prefix": key_info.key_prefix,
            "level": key_info.level.value,
            "scopes": key_info.scopes,
            "owner": key_info.owner,
        }

    # -------------------------------------------------------------------
    # 路由 - 配额查询
    # -------------------------------------------------------------------

    @router.get("/{key_id}/quota")
    async def get_key_quota(
        key_id: str,
        current_user: dict = Depends(admin_dep),  # type: ignore
    ):
        """查看指定 Key 的配额和使用情况"""
        key_info = manager.get_key(key_id)
        if not key_info:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Key 不存在: {key_id}",
            )
        usage = manager._quota.get_usage(key_id) or {}
        return {
            "key_id": key_id,
            "key_name": key_info.key_name,
            "quota": key_info.quota.to_dict(),
            "call_count": key_info.call_count,
            "current_usage": usage,
        }

    # -------------------------------------------------------------------
    # 路由 - 清理维护
    # -------------------------------------------------------------------

    @router.post("/maintenance/cleanup")
    async def cleanup(
        current_user: dict = Depends(admin_dep),  # type: ignore
    ):
        """执行清理维护

        - 清理过期的配额记录
        - 清理已吊销超过 30 天的 Key
        - 标记已过期的 Key
        """
        result = manager.cleanup()
        return {"message": "清理完成", "details": result}

    logger.info("API Key 管理 Router 已创建 (require_admin=%s)", require_admin)
    return router


# 导入 Depends（延迟导入避免未安装 FastAPI 时报错）
if _fastapi_available:
    from fastapi import Depends  # noqa: F401
