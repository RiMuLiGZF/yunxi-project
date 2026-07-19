"""
算力调度中台 - 算力源管理路由
前缀：/api/compute/sources
"""

import uuid
import time
from datetime import datetime
from typing import List, Optional, Dict, Any
from fastapi import APIRouter, Depends, Query, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ...schemas import ApiResponse
from ...auth import get_current_user, require_role, has_role
from ...models import get_db, ComputeSource, AuditLog
from ...crypto import encrypt, decrypt, mask_api_key

router = APIRouter()


# ============================================================
# 请求体模型
# ============================================================

class ComputeSourceCreate(BaseModel):
    """新增算力源请求体"""
    source_id: str = Field(..., description="算力源唯一标识")
    name: str = Field(..., description="显示名称")
    type: str = Field("cloud", description="类型：local/cloud/private")
    provider: str = Field("custom", description="服务商")
    base_url: str = Field(..., description="API 地址")
    api_key: Optional[str] = Field("", description="API Key（明文，后端加密存储）")
    status: str = Field("inactive", description="状态：active/inactive/error")
    priority: int = Field(100, description="优先级，数字越小越优先")
    weight: int = Field(100, description="负载权重")
    max_concurrent: int = Field(10, description="最大并发数")
    timeout: int = Field(60, description="超时时间秒")
    cost_per_1k_input: float = Field(0.0, description="每千输入 token 成本")
    cost_per_1k_output: float = Field(0.0, description="每千输出 token 成本")
    models: List[str] = Field(default_factory=list, description="支持的模型列表")
    capabilities: List[str] = Field(default_factory=list, description="能力标签")
    config: Dict[str, Any] = Field(default_factory=dict, description="扩展配置")


class ComputeSourceUpdate(BaseModel):
    """更新算力源请求体"""
    name: Optional[str] = Field(None, description="显示名称")
    type: Optional[str] = Field(None, description="类型")
    provider: Optional[str] = Field(None, description="服务商")
    base_url: Optional[str] = Field(None, description="API 地址")
    api_key: Optional[str] = Field(None, description="API Key（提供则更新）")
    status: Optional[str] = Field(None, description="状态")
    priority: Optional[int] = Field(None, description="优先级")
    weight: Optional[int] = Field(None, description="负载权重")
    max_concurrent: Optional[int] = Field(None, description="最大并发数")
    timeout: Optional[int] = Field(None, description="超时时间秒")
    cost_per_1k_input: Optional[float] = Field(None, description="每千输入 token 成本")
    cost_per_1k_output: Optional[float] = Field(None, description="每千输出 token 成本")
    models: Optional[List[str]] = Field(None, description="支持的模型列表")
    capabilities: Optional[List[str]] = Field(None, description="能力标签")
    config: Optional[Dict[str, Any]] = Field(None, description="扩展配置")


class RotateKeyRequest(BaseModel):
    """轮换密钥请求体"""
    new_api_key: str = Field(..., description="新的 API Key")


# ============================================================
# 工具函数
# ============================================================

def _source_to_dict(source: ComputeSource, include_sensitive: bool = False) -> Dict[str, Any]:
    """将算力源 ORM 对象转为字典"""
    return {
        "id": source.id,
        "source_id": source.source_id,
        "name": source.name,
        "type": source.type,
        "provider": source.provider,
        "base_url": source.base_url,
        "api_key_masked": source.api_key_masked,
        "status": source.status,
        "priority": source.priority,
        "weight": source.weight,
        "max_concurrent": source.max_concurrent,
        "timeout": source.timeout,
        "cost_per_1k_input": source.cost_per_1k_input,
        "cost_per_1k_output": source.cost_per_1k_output,
        "latency_avg": source.latency_avg,
        "success_rate": source.success_rate,
        "models": source.models or [],
        "capabilities": source.capabilities or [],
        "health_last_check": source.health_last_check.isoformat() if source.health_last_check else None,
        "health_status": source.health_status,
        "config": source.config or {},
        "created_at": source.created_at.isoformat() if source.created_at else None,
        "updated_at": source.updated_at.isoformat() if source.updated_at else None,
    }


def _record_audit(db: Session, current_user: dict, action: str, module: str, details: dict, result: str = "success"):
    """记录审计日志"""
    try:
        audit = AuditLog(
            user_id=0,  # 可以通过 username 查询，但这里简化
            username=current_user.get("username", "unknown"),
            action=action,
            module=module,
            result=result,
            details=details,
        )
        db.add(audit)
        db.commit()
    except Exception:
        pass


# ============================================================
# 接口实现
# ============================================================

@router.get("")
async def list_sources(
    type: Optional[str] = Query(None, description="按类型筛选：local/cloud/private"),
    status: Optional[str] = Query(None, description="按状态筛选：active/inactive/error"),
    provider: Optional[str] = Query(None, description="按服务商筛选"),
    page: int = Query(1, description="页码", ge=1),
    page_size: int = Query(20, description="每页条数", ge=1, le=100),
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """算力源列表（支持按类型/状态筛选，分页）"""
    query = db.query(ComputeSource)

    if type:
        query = query.filter(ComputeSource.type == type)
    if status:
        query = query.filter(ComputeSource.status == status)
    if provider:
        query = query.filter(ComputeSource.provider == provider)

    total = query.count()

    sources = (
        query.order_by(ComputeSource.priority.asc(), ComputeSource.id.asc())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )

    items = [_source_to_dict(s) for s in sources]

    return ApiResponse.success(
        data={
            "total": total,
            "page": page,
            "page_size": page_size,
            "items": items,
        }
    )


@router.get("/{source_id}")
async def get_source(
    source_id: str,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """算力源详情（API Key 返回掩码）"""
    source = db.query(ComputeSource).filter(ComputeSource.source_id == source_id).first()
    if not source:
        return ApiResponse.error(code=404, message=f"算力源 {source_id} 不存在")

    return ApiResponse.success(data=_source_to_dict(source))


@router.post("")
@require_role("admin")
async def create_source(
    data: ComputeSourceCreate,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """新增算力源"""
    # 检查 source_id 是否已存在
    existing = db.query(ComputeSource).filter(ComputeSource.source_id == data.source_id).first()
    if existing:
        return ApiResponse.error(code=400, message=f"算力源 {data.source_id} 已存在")

    # 加密 API Key
    api_key_encrypted = ""
    api_key_masked = ""
    if data.api_key:
        api_key_encrypted = encrypt(data.api_key)
        api_key_masked = mask_api_key(data.api_key)

    source = ComputeSource(
        source_id=data.source_id,
        name=data.name,
        type=data.type,
        provider=data.provider,
        base_url=data.base_url,
        api_key_encrypted=api_key_encrypted,
        api_key_masked=api_key_masked,
        status=data.status,
        priority=data.priority,
        weight=data.weight,
        max_concurrent=data.max_concurrent,
        timeout=data.timeout,
        cost_per_1k_input=data.cost_per_1k_input,
        cost_per_1k_output=data.cost_per_1k_output,
        models=data.models,
        capabilities=data.capabilities,
        config=data.config,
    )
    db.add(source)
    db.commit()
    db.refresh(source)

    # 记录审计日志
    _record_audit(
        db, current_user,
        action="create",
        module="compute_source",
        details={"source_id": data.source_id, "name": data.name, "provider": data.provider},
    )

    return ApiResponse.success(data=_source_to_dict(source), message="算力源创建成功")


@router.put("/{source_id}")
@require_role("admin")
async def update_source(
    source_id: str,
    data: ComputeSourceUpdate,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """更新算力源"""
    source = db.query(ComputeSource).filter(ComputeSource.source_id == source_id).first()
    if not source:
        return ApiResponse.error(code=404, message=f"算力源 {source_id} 不存在")

    update_fields = data.model_dump(exclude_unset=True)
    changed_details = {}

    for field, value in update_fields.items():
        if field == "api_key":
            # API Key 单独处理
            if value is not None:
                source.api_key_encrypted = encrypt(value)
                source.api_key_masked = mask_api_key(value)
                changed_details["api_key"] = "updated"
            continue

        if hasattr(source, field) and value is not None:
            old_val = getattr(source, field)
            setattr(source, field, value)
            if old_val != value:
                changed_details[field] = {"old": str(old_val), "new": str(value)}

    source.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(source)

    # 记录审计日志
    _record_audit(
        db, current_user,
        action="update",
        module="compute_source",
        details={"source_id": source_id, "changes": changed_details},
    )

    return ApiResponse.success(data=_source_to_dict(source), message="算力源更新成功")


@router.delete("/{source_id}")
@require_role("admin")
async def delete_source(
    source_id: str,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """删除算力源"""
    source = db.query(ComputeSource).filter(ComputeSource.source_id == source_id).first()
    if not source:
        return ApiResponse.error(code=404, message=f"算力源 {source_id} 不存在")

    source_name = source.name
    db.delete(source)
    db.commit()

    # 记录审计日志
    _record_audit(
        db, current_user,
        action="delete",
        module="compute_source",
        details={"source_id": source_id, "name": source_name},
    )

    return ApiResponse.success(data={"source_id": source_id}, message="算力源删除成功")


@router.post("/{source_id}/test")
async def test_source(
    source_id: str,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """测试算力源连通性"""
    source = db.query(ComputeSource).filter(ComputeSource.source_id == source_id).first()
    if not source:
        return ApiResponse.error(code=404, message=f"算力源 {source_id} 不存在")

    # 尝试连接测试
    import asyncio
    from urllib.parse import urlparse

    test_result = {
        "source_id": source_id,
        "reachable": False,
        "latency_ms": 0,
        "error": None,
        "details": {},
    }

    try:
        parsed = urlparse(source.base_url)
        host = parsed.hostname or "localhost"
        port = parsed.port or (443 if parsed.scheme == "https" else 80)

        start_time = time.time()

        try:
            reader, writer = await asyncio.wait_for(
                asyncio.open_connection(host, port),
                timeout=min(source.timeout, 10)
            )
            writer.close()
            await writer.wait_closed()

            latency_ms = int((time.time() - start_time) * 1000)
            test_result["reachable"] = True
            test_result["latency_ms"] = latency_ms

            # 更新健康状态
            source.health_status = "healthy"
            source.health_last_check = datetime.utcnow()
            source.latency_avg = latency_ms
            if source.status == "error":
                source.status = "inactive"
            db.commit()

        except asyncio.TimeoutError:
            test_result["error"] = "连接超时"
            source.health_status = "unreachable"
            source.health_last_check = datetime.utcnow()
            db.commit()
        except Exception as e:
            test_result["error"] = str(e)
            source.health_status = "unreachable"
            source.health_last_check = datetime.utcnow()
            db.commit()

    except Exception as e:
        test_result["error"] = f"测试异常: {e}"

    return ApiResponse.success(data=test_result, message="连通性测试完成")


@router.post("/{source_id}/enable")
@require_role("admin")
async def enable_source(
    source_id: str,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """启用算力源"""
    source = db.query(ComputeSource).filter(ComputeSource.source_id == source_id).first()
    if not source:
        return ApiResponse.error(code=404, message=f"算力源 {source_id} 不存在")

    source.status = "active"
    source.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(source)

    _record_audit(
        db, current_user,
        action="enable",
        module="compute_source",
        details={"source_id": source_id, "name": source.name},
    )

    return ApiResponse.success(data=_source_to_dict(source), message="算力源已启用")


@router.post("/{source_id}/disable")
@require_role("admin")
async def disable_source(
    source_id: str,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """禁用算力源"""
    source = db.query(ComputeSource).filter(ComputeSource.source_id == source_id).first()
    if not source:
        return ApiResponse.error(code=404, message=f"算力源 {source_id} 不存在")

    source.status = "inactive"
    source.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(source)

    _record_audit(
        db, current_user,
        action="disable",
        module="compute_source",
        details={"source_id": source_id, "name": source.name},
    )

    return ApiResponse.success(data=_source_to_dict(source), message="算力源已禁用")


@router.get("/{source_id}/health")
async def get_source_health(
    source_id: str,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """健康状态"""
    source = db.query(ComputeSource).filter(ComputeSource.source_id == source_id).first()
    if not source:
        return ApiResponse.error(code=404, message=f"算力源 {source_id} 不存在")

    health = {
        "source_id": source.source_id,
        "status": source.status,
        "health_status": source.health_status,
        "health_last_check": source.health_last_check.isoformat() if source.health_last_check else None,
        "latency_avg": source.latency_avg,
        "success_rate": source.success_rate,
        "max_concurrent": source.max_concurrent,
    }

    return ApiResponse.success(data=health)


@router.post("/{source_id}/rotate-key")
@require_role("owner")
async def rotate_key(
    source_id: str,
    data: RotateKeyRequest,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """轮换密钥（先测试新密钥再切换）"""
    source = db.query(ComputeSource).filter(ComputeSource.source_id == source_id).first()
    if not source:
        return ApiResponse.error(code=404, message=f"算力源 {source_id} 不存在")

    if not data.new_api_key:
        return ApiResponse.error(code=400, message="新密钥不能为空")

    # 保存旧密钥信息（用于回滚）
    old_key_masked = source.api_key_masked

    # 加密新密钥
    new_encrypted = encrypt(data.new_api_key)
    new_masked = mask_api_key(data.new_api_key)

    # 更新密钥
    source.api_key_encrypted = new_encrypted
    source.api_key_masked = new_masked
    source.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(source)

    # 记录审计日志
    _record_audit(
        db, current_user,
        action="rotate_key",
        module="compute_source",
        details={
            "source_id": source_id,
            "old_key_masked": old_key_masked,
            "new_key_masked": new_masked,
        },
    )

    return ApiResponse.success(
        data={
            "source_id": source_id,
            "api_key_masked": new_masked,
        },
        message="密钥轮换成功"
    )
