"""
算力调度中台 - 模型绑定管理路由
前缀：/api/compute/models
"""

from datetime import datetime
from typing import List, Optional, Dict, Any
from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from ..schemas import ApiResponse
from ..auth import get_current_user, require_role
from ..models import get_db, ComputeModelBinding, ComputeKeyGroup, AuditLog

router = APIRouter()


# ============================================================
# 请求体模型
# ============================================================

class ComputeModelCreate(BaseModel):
    """新增模型绑定请求体"""
    model_config = ConfigDict(protected_namespaces=())

    model_key: str = Field(..., description="模型标识，如 default-chat")
    model_name: str = Field(..., description="显示名称")
    purpose: str = Field("chat", description="用途：chat/embedding/code/vision")
    group_id: str = Field(..., description="绑定的密钥分组")
    fallback_model_key: str = Field("", description="降级模型")
    max_tokens: int = Field(4096, description="最大 token 数")
    temperature_default: float = Field(0.7, description="默认温度")


class ComputeModelUpdate(BaseModel):
    """更新模型绑定请求体"""
    model_config = ConfigDict(protected_namespaces=())

    model_name: Optional[str] = Field(None, description="显示名称")
    purpose: Optional[str] = Field(None, description="用途")
    group_id: Optional[str] = Field(None, description="绑定的密钥分组")
    fallback_model_key: Optional[str] = Field(None, description="降级模型")
    max_tokens: Optional[int] = Field(None, description="最大 token 数")
    temperature_default: Optional[float] = Field(None, description="默认温度")


# ============================================================
# 工具函数
# ============================================================

def _model_to_dict(model: ComputeModelBinding, group: Optional[ComputeKeyGroup] = None) -> Dict[str, Any]:
    """将模型绑定 ORM 对象转为字典"""
    result = {
        "id": model.id,
        "model_key": model.model_key,
        "model_name": model.model_name,
        "purpose": model.purpose,
        "group_id": model.group_id,
        "fallback_model_key": model.fallback_model_key,
        "max_tokens": model.max_tokens,
        "temperature_default": model.temperature_default,
        "created_at": model.created_at.isoformat() if model.created_at else None,
        "updated_at": model.updated_at.isoformat() if model.updated_at else None,
    }
    if group:
        result["group"] = {
            "group_id": group.group_id,
            "name": group.name,
            "source_count": len(group.source_ids or []),
        }
    return result


def _record_audit(db: Session, current_user: dict, action: str, module: str, details: dict):
    """记录审计日志"""
    try:
        audit = AuditLog(
            user_id=0,
            username=current_user.get("username", "unknown"),
            action=action,
            module=module,
            result="success",
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
async def list_models(
    purpose: Optional[str] = Query(None, description="按用途筛选：chat/embedding/code/vision"),
    group_id: Optional[str] = Query(None, description="按分组筛选"),
    page: int = Query(1, description="页码", ge=1),
    page_size: int = Query(50, description="每页条数", ge=1, le=100),
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """模型绑定列表"""
    query = db.query(ComputeModelBinding)

    if purpose:
        query = query.filter(ComputeModelBinding.purpose == purpose)
    if group_id:
        query = query.filter(ComputeModelBinding.group_id == group_id)

    total = query.count()

    models = (
        query.order_by(ComputeModelBinding.id.asc())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )

    # 查询关联的分组信息
    group_ids = {m.group_id for m in models if m.group_id}
    groups = []
    if group_ids:
        groups = db.query(ComputeKeyGroup).filter(
            ComputeKeyGroup.group_id.in_(group_ids)
        ).all()
    group_map = {g.group_id: g for g in groups}

    items = [_model_to_dict(m, group_map.get(m.group_id)) for m in models]

    return ApiResponse.success(
        data={
            "total": total,
            "page": page,
            "page_size": page_size,
            "items": items,
        }
    )


@router.get("/{model_key}")
async def get_model(
    model_key: str,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """模型详情"""
    model = db.query(ComputeModelBinding).filter(ComputeModelBinding.model_key == model_key).first()
    if not model:
        return ApiResponse.error(code=404, message=f"模型绑定 {model_key} 不存在")

    # 查询关联的分组
    group = None
    if model.group_id:
        group = db.query(ComputeKeyGroup).filter(
            ComputeKeyGroup.group_id == model.group_id
        ).first()

    return ApiResponse.success(data=_model_to_dict(model, group))


@router.post("")
@require_role("admin")
async def create_model(
    data: ComputeModelCreate,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """新增模型绑定"""
    existing = db.query(ComputeModelBinding).filter(
        ComputeModelBinding.model_key == data.model_key
    ).first()
    if existing:
        return ApiResponse.error(code=400, message=f"模型绑定 {data.model_key} 已存在")

    # 校验 group_id 是否存在
    if data.group_id:
        group = db.query(ComputeKeyGroup).filter(
            ComputeKeyGroup.group_id == data.group_id
        ).first()
        if not group:
            return ApiResponse.error(code=400, message=f"密钥分组 {data.group_id} 不存在")

    # 校验 fallback_model_key 是否存在（如果有设置）
    if data.fallback_model_key:
        fallback = db.query(ComputeModelBinding).filter(
            ComputeModelBinding.model_key == data.fallback_model_key
        ).first()
        if not fallback:
            return ApiResponse.error(code=400, message=f"降级模型 {data.fallback_model_key} 不存在")

    model = ComputeModelBinding(
        model_key=data.model_key,
        model_name=data.model_name,
        purpose=data.purpose,
        group_id=data.group_id,
        fallback_model_key=data.fallback_model_key,
        max_tokens=data.max_tokens,
        temperature_default=data.temperature_default,
    )
    db.add(model)
    db.commit()
    db.refresh(model)

    _record_audit(
        db, current_user,
        action="create",
        module="compute_model",
        details={"model_key": data.model_key, "model_name": data.model_name, "purpose": data.purpose},
    )

    return ApiResponse.success(data=_model_to_dict(model), message="模型绑定创建成功")


@router.put("/{model_key}")
@require_role("admin")
async def update_model(
    model_key: str,
    data: ComputeModelUpdate,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """更新模型绑定"""
    model = db.query(ComputeModelBinding).filter(ComputeModelBinding.model_key == model_key).first()
    if not model:
        return ApiResponse.error(code=404, message=f"模型绑定 {model_key} 不存在")

    update_fields = data.model_dump(exclude_unset=True)
    changed_details = {}

    # 校验 group_id
    if "group_id" in update_fields and update_fields["group_id"] is not None:
        group = db.query(ComputeKeyGroup).filter(
            ComputeKeyGroup.group_id == update_fields["group_id"]
        ).first()
        if not group:
            return ApiResponse.error(code=400, message=f"密钥分组 {update_fields['group_id']} 不存在")

    # 校验 fallback_model_key
    if "fallback_model_key" in update_fields and update_fields["fallback_model_key"]:
        # 不能指向自己
        if update_fields["fallback_model_key"] == model_key:
            return ApiResponse.error(code=400, message="降级模型不能是自身")
        fallback = db.query(ComputeModelBinding).filter(
            ComputeModelBinding.model_key == update_fields["fallback_model_key"]
        ).first()
        if not fallback:
            return ApiResponse.error(code=400, message=f"降级模型 {update_fields['fallback_model_key']} 不存在")

    for field, value in update_fields.items():
        if hasattr(model, field) and value is not None:
            old_val = getattr(model, field)
            setattr(model, field, value)
            if old_val != value:
                changed_details[field] = {"old": str(old_val), "new": str(value)}

    model.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(model)

    _record_audit(
        db, current_user,
        action="update",
        module="compute_model",
        details={"model_key": model_key, "changes": changed_details},
    )

    return ApiResponse.success(data=_model_to_dict(model), message="模型绑定更新成功")


@router.delete("/{model_key}")
@require_role("admin")
async def delete_model(
    model_key: str,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """删除模型绑定"""
    model = db.query(ComputeModelBinding).filter(ComputeModelBinding.model_key == model_key).first()
    if not model:
        return ApiResponse.error(code=404, message=f"模型绑定 {model_key} 不存在")

    # 检查是否有其他模型将此作为降级模型
    dependents = db.query(ComputeModelBinding).filter(
        ComputeModelBinding.fallback_model_key == model_key
    ).all()
    if dependents:
        dep_keys = [m.model_key for m in dependents]
        return ApiResponse.error(
            code=400,
            message=f"模型 {model_key} 被以下模型作为降级模型引用，无法删除: {', '.join(dep_keys)}"
        )

    model_name = model.model_name
    db.delete(model)
    db.commit()

    _record_audit(
        db, current_user,
        action="delete",
        module="compute_model",
        details={"model_key": model_key, "model_name": model_name},
    )

    return ApiResponse.success(data={"model_key": model_key}, message="模型绑定删除成功")
