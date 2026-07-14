"""
算力调度中台 - 技能权限绑定路由
提供技能与算力源/分组的权限绑定管理接口

兼容第一部分表结构：
- ComputeSkillBinding: skill_id/skill_name/allowed_groups/allowed_sources,
  quota_daily/quota_monthly, rate_limit_per_min, priority
  没有 description/denied_source_ids/max_tokens_per_request/daily_token_quota/priority_bonus/status
"""

from datetime import datetime
from typing import List, Dict, Any, Optional
from fastapi import APIRouter, Depends, Query, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ..schemas import ApiResponse
from ..auth import get_current_user, require_role
from ..models import get_db, ComputeSkillBinding
from ..compute_router import get_compute_router

router = APIRouter()
compute_router = get_compute_router()


# ============================================================
# 请求体模型
# ============================================================

class SkillCreate(BaseModel):
    """新增技能绑定请求体"""
    skill_id: str = Field(..., description="技能ID")
    skill_name: str = Field(..., description="技能名称")
    allowed_sources: List[str] = Field(default_factory=list, description="允许的算力源ID列表")
    allowed_groups: List[str] = Field(default_factory=list, description="允许的分组ID列表")
    quota_daily: float = Field(0.0, description="日额度（元），0表示不限制")
    quota_monthly: float = Field(0.0, description="月额度（元），0表示不限制")
    rate_limit_per_min: int = Field(0, description="每分钟调用限制，0表示不限制")
    priority: int = Field(50, description="调用优先级，数值越小越优先")


class SkillUpdate(BaseModel):
    """更新技能绑定请求体"""
    skill_name: Optional[str] = None
    allowed_sources: Optional[List[str]] = None
    allowed_groups: Optional[List[str]] = None
    quota_daily: Optional[float] = None
    quota_monthly: Optional[float] = None
    rate_limit_per_min: Optional[int] = None
    priority: Optional[int] = None


# ============================================================
# 工具函数
# ============================================================

def _skill_to_dict(skill: ComputeSkillBinding) -> Dict[str, Any]:
    """技能绑定 ORM 转字典（适配第一部分表结构）"""
    return {
        "skill_id": skill.skill_id,
        "skill_name": skill.skill_name,
        "description": "",  # 第一部分没有
        "allowed_source_ids": getattr(skill, 'allowed_sources', []) or [],
        "allowed_sources": getattr(skill, 'allowed_sources', []) or [],
        "denied_source_ids": [],  # 第一部分没有
        "allowed_groups": getattr(skill, 'allowed_groups', []) or [],
        "max_tokens_per_request": 0,  # 第一部分没有
        "daily_token_quota": 0,  # 第一部分没有
        "quota_daily": getattr(skill, 'quota_daily', 0.0),
        "quota_monthly": getattr(skill, 'quota_monthly', 0.0),
        "rate_limit_per_min": getattr(skill, 'rate_limit_per_min', 0),
        "priority_bonus": 0.0,  # 第一部分没有
        "priority": getattr(skill, 'priority', 50),
        "status": "active",  # 第一部分没有
        "created_at": skill.created_at.timestamp() if skill.created_at else None,
        "updated_at": skill.updated_at.timestamp() if getattr(skill, 'updated_at', None) else None,
    }


# ============================================================
# CRUD 接口
# ============================================================

@router.get("/")
async def list_skills(
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """获取技能绑定列表"""
    skills = db.query(ComputeSkillBinding).order_by(
        ComputeSkillBinding.priority,
        ComputeSkillBinding.created_at.desc(),
    ).all()
    
    return ApiResponse.success(
        data={
            "total": len(skills),
            "items": [_skill_to_dict(s) for s in skills],
        }
    )


@router.get("/{skill_id}")
async def get_skill(
    skill_id: str,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """获取技能绑定详情"""
    skill = db.query(ComputeSkillBinding).filter(
        ComputeSkillBinding.skill_id == skill_id
    ).first()
    
    if not skill:
        return ApiResponse.error(code=404, message=f"技能 {skill_id} 不存在")
    
    # 补充可用算力源信息
    sources = compute_router.get_all_sources()
    skill_dict = _skill_to_dict(skill)
    skill_dict["available_sources"] = [
        {"source_id": sid, "name": s["name"]}
        for sid, s in sources.items()
    ]
    
    # 补充可用分组信息
    groups = {}
    # 从路由引擎获取分组信息
    for sid, s in sources.items():
        pass  # 暂不补充分组详情
    
    return ApiResponse.success(data=skill_dict)


@router.post("/")
@require_role("admin")
async def create_skill(
    skill_data: SkillCreate,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """新增技能绑定"""
    # 检查是否已存在
    existing = db.query(ComputeSkillBinding).filter(
        ComputeSkillBinding.skill_id == skill_data.skill_id
    ).first()
    if existing:
        return ApiResponse.error(code=400, message=f"技能ID {skill_data.skill_id} 已存在")
    
    now = datetime.utcnow()
    skill = ComputeSkillBinding(
        skill_id=skill_data.skill_id,
        skill_name=skill_data.skill_name,
        allowed_groups=skill_data.allowed_groups,
        allowed_sources=skill_data.allowed_sources,
        quota_daily=skill_data.quota_daily,
        quota_monthly=skill_data.quota_monthly,
        rate_limit_per_min=skill_data.rate_limit_per_min,
        priority=skill_data.priority,
        created_at=now,
        updated_at=now,
    )
    db.add(skill)
    db.commit()
    db.refresh(skill)
    
    # 重新加载路由引擎配置
    compute_router.reload_config()
    
    return ApiResponse.success(data=_skill_to_dict(skill), message="技能绑定创建成功")


@router.put("/{skill_id}")
@require_role("admin")
async def update_skill(
    skill_id: str,
    skill_data: SkillUpdate,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """更新技能绑定"""
    skill = db.query(ComputeSkillBinding).filter(
        ComputeSkillBinding.skill_id == skill_id
    ).first()
    
    if not skill:
        return ApiResponse.error(code=404, message=f"技能 {skill_id} 不存在")
    
    # 更新字段
    update_data = skill_data.dict(exclude_unset=True)
    
    # 直接更新表中存在的字段
    direct_fields = [
        'skill_name', 'allowed_groups', 'allowed_sources',
        'quota_daily', 'quota_monthly', 'rate_limit_per_min', 'priority',
    ]
    
    for key in direct_fields:
        if key in update_data and update_data[key] is not None:
            setattr(skill, key, update_data[key])
    
    skill.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(skill)
    
    # 重新加载配置
    compute_router.reload_config()
    
    return ApiResponse.success(data=_skill_to_dict(skill), message="技能绑定更新成功")


@router.delete("/{skill_id}")
@require_role("admin")
async def delete_skill(
    skill_id: str,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """删除技能绑定"""
    skill = db.query(ComputeSkillBinding).filter(
        ComputeSkillBinding.skill_id == skill_id
    ).first()
    
    if not skill:
        return ApiResponse.error(code=404, message=f"技能 {skill_id} 不存在")
    
    db.delete(skill)
    db.commit()
    
    # 重新加载配置
    compute_router.reload_config()
    
    return ApiResponse.success(message="技能绑定删除成功")
