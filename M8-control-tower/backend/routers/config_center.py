"""
M8 配置中心 - API 路由

提供配置中心的 RESTful API 接口，包括：
- 配置 CRUD
- 批量操作
- 版本管理
- 审计日志
- Schema 管理
- 灰度发布
- 长轮询监听
- 健康检查
"""

from __future__ import annotations

import sys
import asyncio
from pathlib import Path
from typing import Optional, List, Dict, Any
from datetime import datetime

from fastapi import APIRouter, Query, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

# 项目路径
project_root = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(project_root))

from ..schemas.common import ApiResponse, PaginatedResponse
from ..models.base import get_db
from ..services.config_center import ConfigCenterService

router = APIRouter()


# ===========================================================================
# 请求/响应模型
# ===========================================================================

class ConfigItemCreate(BaseModel):
    """创建配置请求"""
    config_key: str = Field(..., description="配置键")
    config_value: Any = Field(..., description="配置值")
    config_type: Optional[str] = Field(None, description="配置类型")
    scope: str = Field("global", description="作用域")
    module_name: Optional[str] = Field(None, description="模块名")
    env_name: Optional[str] = Field(None, description="环境名")
    instance_id: Optional[str] = Field(None, description="实例ID")
    description: str = Field("", description="配置描述")
    is_secret: bool = Field(False, description="是否敏感配置")
    reason: str = Field("", description="变更原因")
    schema_name: Optional[str] = Field(None, description="关联 Schema 名称")


class ConfigItemUpdate(BaseModel):
    """更新配置请求"""
    config_value: Optional[Any] = Field(None, description="配置值")
    config_type: Optional[str] = Field(None, description="配置类型")
    description: Optional[str] = Field(None, description="配置描述")
    is_secret: Optional[bool] = Field(None, description="是否敏感配置")
    reason: str = Field("", description="变更原因")


class BatchGetRequest(BaseModel):
    """批量获取请求"""
    keys: List[str] = Field(..., description="配置键列表")
    scope: str = Field("global", description="作用域")
    module_name: Optional[str] = Field(None, description="模块名")
    env_name: Optional[str] = Field(None, description="环境名")
    instance_id: Optional[str] = Field(None, description="实例ID")
    resolve_inheritance: bool = Field(True, description="是否解析层级继承")


class BatchSetItem(BaseModel):
    """批量设置的单个配置项"""
    key: str
    value: Any
    config_type: Optional[str] = None
    description: str = ""
    is_secret: bool = False
    scope: Optional[str] = None
    module_name: Optional[str] = None
    env_name: Optional[str] = None
    instance_id: Optional[str] = None


class BatchSetRequest(BaseModel):
    """批量设置请求"""
    items: List[BatchSetItem]
    scope: str = Field("global", description="默认作用域")
    module_name: Optional[str] = None
    env_name: Optional[str] = None
    instance_id: Optional[str] = None
    reason: str = ""


class RollbackRequest(BaseModel):
    """回滚请求"""
    config_key: str
    target_version: int
    scope: str = "global"
    module_name: Optional[str] = None
    env_name: Optional[str] = None
    instance_id: Optional[str] = None
    reason: str = ""


class CanaryStartRequest(BaseModel):
    """启动灰度发布请求"""
    config_key: str
    canary_value: Any
    scope: str = "module"
    module_name: Optional[str] = None
    env_name: Optional[str] = None
    canary_percent: Optional[int] = None
    canary_instances: Optional[List[str]] = None
    reason: str = ""


class CanaryRollbackRequest(BaseModel):
    """回滚灰度请求"""
    config_key: str
    scope: str = "module"
    module_name: Optional[str] = None
    env_name: Optional[str] = None
    reason: str = ""


class SchemaCreate(BaseModel):
    """创建 Schema 请求"""
    schema_name: str = Field(..., description="Schema 名称")
    schema_json: Dict[str, Any] = Field(..., description="JSON Schema 定义")
    module_name: Optional[str] = None
    description: str = ""


class ConfigImportRequest(BaseModel):
    """导入配置请求"""
    data: Dict[str, Any] = Field(..., description="配置数据（export 格式）")
    overwrite: bool = Field(True, description="是否覆盖已有配置")


# ===========================================================================
# 辅助函数
# ===========================================================================

def _get_service(db: Session) -> ConfigCenterService:
    """获取配置中心服务实例"""
    return ConfigCenterService(db=db)


def _get_operator(request: Request) -> str:
    """从请求中获取操作人"""
    # 优先从认证信息获取，降级为 system
    try:
        user = getattr(request.state, "user", None)
        if user and hasattr(user, "username"):
            return user.username
    except Exception:
        pass
    return "system"


# ===========================================================================
# 1. 配置 CRUD
# ===========================================================================

@router.get("/items", response_model=ApiResponse)
def list_config_items(
    scope: Optional[str] = Query(None, description="作用域过滤"),
    module_name: Optional[str] = Query(None, description="模块名过滤"),
    env_name: Optional[str] = Query(None, description="环境名过滤"),
    instance_id: Optional[str] = Query(None, description="实例ID过滤"),
    prefix: Optional[str] = Query(None, description="配置键前缀过滤"),
    page: int = Query(1, ge=1, description="页码"),
    page_size: int = Query(50, ge=1, le=200, description="每页条数"),
    db: Session = Depends(get_db),
):
    """配置列表（支持过滤）"""
    service = _get_service(db)
    result = service.list_configs(
        scope=scope,
        module_name=module_name,
        env_name=env_name,
        instance_id=instance_id,
        prefix=prefix,
        include_secret=False,
        page=page,
        page_size=page_size,
    )
    return ApiResponse.success(data=result)


@router.get("/items/{config_key}", response_model=ApiResponse)
def get_config_item(
    config_key: str,
    scope: str = Query("global", description="作用域"),
    module_name: Optional[str] = Query(None, description="模块名"),
    env_name: Optional[str] = Query(None, description="环境名"),
    instance_id: Optional[str] = Query(None, description="实例ID"),
    resolve_inheritance: bool = Query(True, description="是否解析层级继承"),
    db: Session = Depends(get_db),
):
    """获取单个配置"""
    service = _get_service(db)
    result = service.get_config(
        key=config_key,
        scope=scope,
        module_name=module_name,
        env_name=env_name,
        instance_id=instance_id,
        resolve_inheritance=resolve_inheritance,
        include_secret=True,  # API 层面返回明文，由权限控制
    )
    if not result:
        raise HTTPException(status_code=404, detail=f"配置 '{config_key}' 不存在")
    return ApiResponse.success(data=result)


@router.post("/items", response_model=ApiResponse)
def create_config_item(
    body: ConfigItemCreate,
    request: Request,
    db: Session = Depends(get_db),
):
    """新增配置"""
    service = _get_service(db)
    operator = _get_operator(request)
    try:
        result = service.set_config(
            key=body.config_key,
            value=body.config_value,
            scope=body.scope,
            module_name=body.module_name,
            env_name=body.env_name,
            instance_id=body.instance_id,
            config_type=body.config_type,
            description=body.description,
            is_secret=body.is_secret,
            operator=operator,
            reason=body.reason,
            schema_name=body.schema_name,
        )
        return ApiResponse.success(data=result, message="配置创建成功")
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.put("/items/{config_key}", response_model=ApiResponse)
def update_config_item(
    config_key: str,
    body: ConfigItemUpdate,
    request: Request,
    scope: str = Query("global", description="作用域"),
    module_name: Optional[str] = Query(None, description="模块名"),
    env_name: Optional[str] = Query(None, description="环境名"),
    instance_id: Optional[str] = Query(None, description="实例ID"),
    db: Session = Depends(get_db),
):
    """更新配置"""
    service = _get_service(db)
    operator = _get_operator(request)

    # 先获取当前配置
    existing = service.get_config(
        key=config_key,
        scope=scope,
        module_name=module_name,
        env_name=env_name,
        instance_id=instance_id,
        resolve_inheritance=False,
        include_secret=True,
    )
    if not existing:
        raise HTTPException(status_code=404, detail=f"配置 '{config_key}' 不存在")

    try:
        result = service.set_config(
            key=config_key,
            value=body.config_value if body.config_value is not None else existing["config_value"],
            scope=scope,
            module_name=module_name,
            env_name=env_name,
            instance_id=instance_id,
            config_type=body.config_type or existing["config_type"],
            description=body.description if body.description is not None else existing.get("description", ""),
            is_secret=body.is_secret if body.is_secret is not None else existing.get("is_secret", False),
            operator=operator,
            reason=body.reason,
        )
        return ApiResponse.success(data=result, message="配置更新成功")
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.delete("/items/{config_key}", response_model=ApiResponse)
def delete_config_item(
    config_key: str,
    request: Request,
    scope: str = Query("global", description="作用域"),
    module_name: Optional[str] = Query(None, description="模块名"),
    env_name: Optional[str] = Query(None, description="环境名"),
    instance_id: Optional[str] = Query(None, description="实例ID"),
    reason: str = Query("", description="删除原因"),
    db: Session = Depends(get_db),
):
    """删除配置"""
    service = _get_service(db)
    operator = _get_operator(request)
    try:
        success = service.delete_config(
            key=config_key,
            scope=scope,
            module_name=module_name,
            env_name=env_name,
            instance_id=instance_id,
            operator=operator,
            reason=reason,
        )
        if not success:
            raise HTTPException(status_code=404, detail=f"配置 '{config_key}' 不存在")
        return ApiResponse.success(data={"deleted": True}, message="配置删除成功")
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


# ===========================================================================
# 2. 批量操作
# ===========================================================================

@router.post("/batch/get", response_model=ApiResponse)
def batch_get_configs(
    body: BatchGetRequest,
    db: Session = Depends(get_db),
):
    """批量获取配置"""
    service = _get_service(db)
    result = service.batch_get(
        keys=body.keys,
        scope=body.scope,
        module_name=body.module_name,
        env_name=body.env_name,
        instance_id=body.instance_id,
        resolve_inheritance=body.resolve_inheritance,
    )
    return ApiResponse.success(data=result)


@router.post("/batch/set", response_model=ApiResponse)
def batch_set_configs(
    body: BatchSetRequest,
    request: Request,
    db: Session = Depends(get_db),
):
    """批量设置配置"""
    service = _get_service(db)
    operator = _get_operator(request)
    items = [item.model_dump() for item in body.items]
    result = service.batch_set(
        items=items,
        scope=body.scope,
        module_name=body.module_name,
        env_name=body.env_name,
        instance_id=body.instance_id,
        operator=operator,
        reason=body.reason,
    )
    return ApiResponse.success(data=result)


# ===========================================================================
# 3. 版本管理
# ===========================================================================

@router.get("/versions", response_model=ApiResponse)
def list_config_versions(
    config_key: str = Query(..., description="配置键"),
    scope: str = Query("global", description="作用域"),
    module_name: Optional[str] = Query(None, description="模块名"),
    env_name: Optional[str] = Query(None, description="环境名"),
    instance_id: Optional[str] = Query(None, description="实例ID"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=200),
    db: Session = Depends(get_db),
):
    """配置版本历史"""
    service = _get_service(db)
    result = service.list_versions(
        key=config_key,
        scope=scope,
        module_name=module_name,
        env_name=env_name,
        instance_id=instance_id,
        page=page,
        page_size=page_size,
    )
    return ApiResponse.success(data=result)


@router.post("/rollback", response_model=ApiResponse)
def rollback_config(
    body: RollbackRequest,
    request: Request,
    db: Session = Depends(get_db),
):
    """配置回滚"""
    service = _get_service(db)
    operator = _get_operator(request)
    try:
        result = service.rollback_config(
            key=body.config_key,
            target_version=body.target_version,
            scope=body.scope,
            module_name=body.module_name,
            env_name=body.env_name,
            instance_id=body.instance_id,
            operator=operator,
            reason=body.reason,
        )
        return ApiResponse.success(data=result, message="配置回滚成功")
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/versions/diff", response_model=ApiResponse)
def diff_versions(
    config_key: str = Query(..., description="配置键"),
    version_a: int = Query(..., description="版本 A"),
    version_b: int = Query(..., description="版本 B"),
    scope: str = Query("global", description="作用域"),
    module_name: Optional[str] = Query(None, description="模块名"),
    env_name: Optional[str] = Query(None, description="环境名"),
    instance_id: Optional[str] = Query(None, description="实例ID"),
    db: Session = Depends(get_db),
):
    """版本对比"""
    service = _get_service(db)
    try:
        result = service.diff_versions(
            key=config_key,
            version_a=version_a,
            version_b=version_b,
            scope=scope,
            module_name=module_name,
            env_name=env_name,
            instance_id=instance_id,
        )
        return ApiResponse.success(data=result)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


# ===========================================================================
# 4. 审计日志
# ===========================================================================

@router.get("/audit", response_model=ApiResponse)
def list_audit_logs(
    config_key: Optional[str] = Query(None, description="配置键过滤"),
    scope: Optional[str] = Query(None, description="作用域过滤"),
    module_name: Optional[str] = Query(None, description="模块名过滤"),
    action: Optional[str] = Query(None, description="操作类型过滤"),
    operator: Optional[str] = Query(None, description="操作人过滤"),
    start_time: Optional[str] = Query(None, description="开始时间 (ISO format)"),
    end_time: Optional[str] = Query(None, description="结束时间 (ISO format)"),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
):
    """审计日志"""
    service = _get_service(db)

    start_dt = None
    end_dt = None
    if start_time:
        try:
            start_dt = datetime.fromisoformat(start_time)
        except ValueError:
            raise HTTPException(status_code=400, detail=f"无效的 start_time 格式: {start_time}")
    if end_time:
        try:
            end_dt = datetime.fromisoformat(end_time)
        except ValueError:
            raise HTTPException(status_code=400, detail=f"无效的 end_time 格式: {end_time}")

    result = service.list_audit_logs(
        key=config_key,
        scope=scope,
        module_name=module_name,
        action=action,
        operator=operator,
        start_time=start_dt,
        end_time=end_dt,
        page=page,
        page_size=page_size,
    )
    return ApiResponse.success(data=result)


# ===========================================================================
# 5. Schema 管理
# ===========================================================================

@router.get("/schemas", response_model=ApiResponse)
def list_schemas(
    module_name: Optional[str] = Query(None, description="模块名过滤"),
    is_active: Optional[bool] = Query(None, description="是否只列出激活的"),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
):
    """配置 Schema 列表"""
    service = _get_service(db)
    result = service.list_schemas(
        module_name=module_name,
        is_active=is_active,
        page=page,
        page_size=page_size,
    )
    return ApiResponse.success(data=result)


@router.post("/schemas", response_model=ApiResponse)
def create_schema(
    body: SchemaCreate,
    request: Request,
    db: Session = Depends(get_db),
):
    """新增 Schema"""
    service = _get_service(db)
    operator = _get_operator(request)
    try:
        result = service.create_schema(
            schema_name=body.schema_name,
            schema_json=body.schema_json,
            module_name=body.module_name,
            description=body.description,
            operator=operator,
        )
        return ApiResponse.success(data=result, message="Schema 创建成功")
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


# ===========================================================================
# 6. 灰度发布
# ===========================================================================

@router.post("/canary/start", response_model=ApiResponse)
def start_canary(
    body: CanaryStartRequest,
    request: Request,
    db: Session = Depends(get_db),
):
    """启动灰度发布"""
    service = _get_service(db)
    operator = _get_operator(request)
    try:
        result = service.start_canary(
            key=body.config_key,
            canary_value=body.canary_value,
            scope=body.scope,
            module_name=body.module_name,
            env_name=body.env_name,
            canary_percent=body.canary_percent,
            canary_instances=body.canary_instances,
            operator=operator,
            reason=body.reason,
        )
        return ApiResponse.success(data=result, message="灰度发布已启动")
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/canary/rollback", response_model=ApiResponse)
def rollback_canary(
    body: CanaryRollbackRequest,
    request: Request,
    db: Session = Depends(get_db),
):
    """灰度回滚"""
    service = _get_service(db)
    operator = _get_operator(request)
    try:
        success = service.rollback_canary(
            key=body.config_key,
            scope=body.scope,
            module_name=body.module_name,
            env_name=body.env_name,
            operator=operator,
            reason=body.reason,
        )
        if not success:
            raise HTTPException(status_code=404, detail="没有进行中的灰度发布")
        return ApiResponse.success(data={"rolled_back": True}, message="灰度已回滚")
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/canary/promote", response_model=ApiResponse)
def promote_canary(
    body: CanaryRollbackRequest,
    request: Request,
    db: Session = Depends(get_db),
):
    """灰度转正（全量发布）"""
    service = _get_service(db)
    operator = _get_operator(request)
    try:
        result = service.promote_canary(
            key=body.config_key,
            scope=body.scope,
            module_name=body.module_name,
            env_name=body.env_name,
            operator=operator,
            reason=body.reason,
        )
        return ApiResponse.success(data=result, message="灰度已转正")
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


# ===========================================================================
# 7. 导入导出
# ===========================================================================

@router.get("/export", response_model=ApiResponse)
def export_configs(
    scope: Optional[str] = Query(None),
    module_name: Optional[str] = Query(None),
    env_name: Optional[str] = Query(None),
    prefix: Optional[str] = Query(None),
    include_secret: bool = Query(False),
    db: Session = Depends(get_db),
):
    """导出配置"""
    service = _get_service(db)
    result = service.export_configs(
        scope=scope,
        module_name=module_name,
        env_name=env_name,
        prefix=prefix,
        include_secret=include_secret,
    )
    return ApiResponse.success(data=result)


@router.post("/import", response_model=ApiResponse)
def import_configs(
    body: ConfigImportRequest,
    request: Request,
    db: Session = Depends(get_db),
):
    """导入配置"""
    service = _get_service(db)
    operator = _get_operator(request)
    result = service.import_configs(
        data=body.data,
        operator=operator,
        overwrite=body.overwrite,
    )
    return ApiResponse.success(data=result, message="配置导入完成")


# ===========================================================================
# 8. 健康检查
# ===========================================================================

@router.get("/health", response_model=ApiResponse)
def config_center_health(
    db: Session = Depends(get_db),
):
    """配置中心健康检查"""
    service = _get_service(db)
    result = service.health_check()
    return ApiResponse.success(data=result)


# ===========================================================================
# 9. 长轮询监听
# ===========================================================================

@router.get("/watch", response_model=ApiResponse)
async def watch_config_changes(
    since_id: int = Query(0, description="上次已知的最新审计日志 ID"),
    scope: str = Query("module", description="监听的作用域"),
    module_name: Optional[str] = Query(None, description="模块名"),
    env_name: Optional[str] = Query(None, description="环境名"),
    timeout: int = Query(30, ge=1, le=60, description="长轮询超时时间（秒）"),
    db: Session = Depends(get_db),
):
    """长轮询监听配置变更

    客户端通过长轮询方式监听配置变更。
    如果有新变更则立即返回，否则等待直到超时。
    """
    service = _get_service(db)

    # 先立即检查一次是否有变更
    changes = service.get_changes_since(
        since_version=since_id,
        scope=scope,
        module_name=module_name,
        env_name=env_name,
    )

    if changes:
        return ApiResponse.success(data={
            "changes": changes,
            "latest_id": changes[-1]["id"] if changes else since_id,
        })

    # 没有变更则等待（简单轮询实现，每秒检查一次）
    interval = 1.0
    waited = 0.0
    while waited < timeout:
        await asyncio.sleep(interval)
        waited += interval

        changes = service.get_changes_since(
            since_version=since_id,
            scope=scope,
            module_name=module_name,
            env_name=env_name,
        )
        if changes:
            return ApiResponse.success(data={
                "changes": changes,
                "latest_id": changes[-1]["id"],
            })

    # 超时，返回空变更
    return ApiResponse.success(data={
        "changes": [],
        "latest_id": since_id,
        "timeout": True,
    })
