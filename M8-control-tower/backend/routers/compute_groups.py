"""
算力调度中台 - 密钥分组管理路由
前缀：/api/compute/groups
"""

import time
from datetime import datetime
from typing import List, Optional, Dict, Any
from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ..schemas import ApiResponse
from ..auth import get_current_user, require_role
from ..models import get_db, ComputeKeyGroup, ComputeSource, AuditLog

router = APIRouter()


# ============================================================
# 请求体模型
# ============================================================

class ComputeGroupCreate(BaseModel):
    """新增密钥分组请求体"""
    group_id: str = Field(..., description="分组唯一标识")
    name: str = Field(..., description="分组名称")
    description: str = Field("", description="描述")
    source_ids: List[str] = Field(default_factory=list, description="绑定的算力源 ID 列表")
    default_source: str = Field("", description="默认算力源")
    routing_strategy: str = Field("auto", description="路由策略")


class ComputeGroupUpdate(BaseModel):
    """更新密钥分组请求体"""
    name: Optional[str] = Field(None, description="分组名称")
    description: Optional[str] = Field(None, description="描述")
    source_ids: Optional[List[str]] = Field(None, description="绑定的算力源 ID 列表")
    default_source: Optional[str] = Field(None, description="默认算力源")
    routing_strategy: Optional[str] = Field(None, description="路由策略")


# ============================================================
# 工具函数
# ============================================================

def _group_to_dict(group: ComputeKeyGroup, sources: Optional[List[ComputeSource]] = None) -> Dict[str, Any]:
    """将密钥分组 ORM 对象转为字典"""
    source_details = []
    if sources:
        source_map = {s.source_id: s for s in sources}
        for sid in (group.source_ids or []):
            s = source_map.get(sid)
            if s:
                source_details.append({
                    "source_id": s.source_id,
                    "name": s.name,
                    "type": s.type,
                    "provider": s.provider,
                    "status": s.status,
                    "health_status": s.health_status,
                })

    return {
        "id": group.id,
        "group_id": group.group_id,
        "name": group.name,
        "description": group.description,
        "source_ids": group.source_ids or [],
        "source_count": len(group.source_ids or []),
        "default_source": group.default_source,
        "routing_strategy": group.routing_strategy,
        "sources": source_details,
        "created_at": group.created_at.isoformat() if group.created_at else None,
        "updated_at": group.updated_at.isoformat() if group.updated_at else None,
    }


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
async def list_groups(
    page: int = Query(1, description="页码", ge=1),
    page_size: int = Query(50, description="每页条数", ge=1, le=100),
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """分组列表"""
    query = db.query(ComputeKeyGroup)
    total = query.count()

    groups = (
        query.order_by(ComputeKeyGroup.id.asc())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )

    # 收集所有 source_id 查询算力源信息
    all_source_ids = set()
    for g in groups:
        for sid in (g.source_ids or []):
            all_source_ids.add(sid)

    sources = []
    if all_source_ids:
        sources = db.query(ComputeSource).filter(ComputeSource.source_id.in_(all_source_ids)).all()

    items = [_group_to_dict(g, sources) for g in groups]

    return ApiResponse.success(
        data={
            "total": total,
            "page": page,
            "page_size": page_size,
            "items": items,
        }
    )


@router.get("/{group_id}")
async def get_group(
    group_id: str,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """分组详情"""
    group = db.query(ComputeKeyGroup).filter(ComputeKeyGroup.group_id == group_id).first()
    if not group:
        return ApiResponse.error(code=404, message=f"分组 {group_id} 不存在")

    # 查询绑定的算力源详情
    sources = []
    if group.source_ids:
        sources = db.query(ComputeSource).filter(
            ComputeSource.source_id.in_(group.source_ids)
        ).all()

    return ApiResponse.success(data=_group_to_dict(group, sources))


@router.post("")
@require_role("admin")
async def create_group(
    data: ComputeGroupCreate,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """新增分组"""
    existing = db.query(ComputeKeyGroup).filter(ComputeKeyGroup.group_id == data.group_id).first()
    if existing:
        return ApiResponse.error(code=400, message=f"分组 {data.group_id} 已存在")

    # 校验 source_ids 是否都存在
    if data.source_ids:
        existing_sources = db.query(ComputeSource).filter(
            ComputeSource.source_id.in_(data.source_ids)
        ).all()
        existing_ids = {s.source_id for s in existing_sources}
        invalid_ids = [sid for sid in data.source_ids if sid not in existing_ids]
        if invalid_ids:
            return ApiResponse.error(code=400, message=f"无效的算力源: {', '.join(invalid_ids)}")

    group = ComputeKeyGroup(
        group_id=data.group_id,
        name=data.name,
        description=data.description,
        source_ids=data.source_ids,
        default_source=data.default_source,
        routing_strategy=data.routing_strategy,
    )
    db.add(group)
    db.commit()
    db.refresh(group)

    _record_audit(
        db, current_user,
        action="create",
        module="compute_group",
        details={"group_id": data.group_id, "name": data.name},
    )

    return ApiResponse.success(data=_group_to_dict(group), message="分组创建成功")


@router.put("/{group_id}")
@require_role("admin")
async def update_group(
    group_id: str,
    data: ComputeGroupUpdate,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """更新分组"""
    group = db.query(ComputeKeyGroup).filter(ComputeKeyGroup.group_id == group_id).first()
    if not group:
        return ApiResponse.error(code=404, message=f"分组 {group_id} 不存在")

    update_fields = data.model_dump(exclude_unset=True)
    changed_details = {}

    # 如果更新 source_ids，校验有效性
    if "source_ids" in update_fields and update_fields["source_ids"] is not None:
        new_source_ids = update_fields["source_ids"]
        if new_source_ids:
            existing_sources = db.query(ComputeSource).filter(
                ComputeSource.source_id.in_(new_source_ids)
            ).all()
            existing_ids = {s.source_id for s in existing_sources}
            invalid_ids = [sid for sid in new_source_ids if sid not in existing_ids]
            if invalid_ids:
                return ApiResponse.error(code=400, message=f"无效的算力源: {', '.join(invalid_ids)}")

    for field, value in update_fields.items():
        if hasattr(group, field) and value is not None:
            old_val = getattr(group, field)
            setattr(group, field, value)
            if old_val != value:
                changed_details[field] = {"old": str(old_val), "new": str(value)}

    group.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(group)

    _record_audit(
        db, current_user,
        action="update",
        module="compute_group",
        details={"group_id": group_id, "changes": changed_details},
    )

    return ApiResponse.success(data=_group_to_dict(group), message="分组更新成功")


@router.delete("/{group_id}")
@require_role("admin")
async def delete_group(
    group_id: str,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """删除分组"""
    group = db.query(ComputeKeyGroup).filter(ComputeKeyGroup.group_id == group_id).first()
    if not group:
        return ApiResponse.error(code=404, message=f"分组 {group_id} 不存在")

    group_name = group.name
    db.delete(group)
    db.commit()

    _record_audit(
        db, current_user,
        action="delete",
        module="compute_group",
        details={"group_id": group_id, "name": group_name},
    )

    return ApiResponse.success(data={"group_id": group_id}, message="分组删除成功")


@router.post("/{group_id}/sources/{source_id}")
@require_role("admin")
async def bind_source(
    group_id: str,
    source_id: str,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """绑定算力源到分组"""
    group = db.query(ComputeKeyGroup).filter(ComputeKeyGroup.group_id == group_id).first()
    if not group:
        return ApiResponse.error(code=404, message=f"分组 {group_id} 不存在")

    source = db.query(ComputeSource).filter(ComputeSource.source_id == source_id).first()
    if not source:
        return ApiResponse.error(code=404, message=f"算力源 {source_id} 不存在")

    source_ids = list(group.source_ids or [])
    if source_id in source_ids:
        return ApiResponse.error(code=400, message=f"算力源 {source_id} 已在分组中")

    source_ids.append(source_id)
    group.source_ids = source_ids
    group.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(group)

    _record_audit(
        db, current_user,
        action="bind_source",
        module="compute_group",
        details={"group_id": group_id, "source_id": source_id},
    )

    return ApiResponse.success(data=_group_to_dict(group), message="算力源绑定成功")


@router.delete("/{group_id}/sources/{source_id}")
@require_role("admin")
async def unbind_source(
    group_id: str,
    source_id: str,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """解绑算力源"""
    group = db.query(ComputeKeyGroup).filter(ComputeKeyGroup.group_id == group_id).first()
    if not group:
        return ApiResponse.error(code=404, message=f"分组 {group_id} 不存在")

    source_ids = list(group.source_ids or [])
    if source_id not in source_ids:
        return ApiResponse.error(code=400, message=f"算力源 {source_id} 不在分组中")

    source_ids.remove(source_id)
    group.source_ids = source_ids

    # 如果默认算力源被移除，清空默认
    if group.default_source == source_id:
        group.default_source = source_ids[0] if source_ids else ""

    group.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(group)

    _record_audit(
        db, current_user,
        action="unbind_source",
        module="compute_group",
        details={"group_id": group_id, "source_id": source_id},
    )

    return ApiResponse.success(data=_group_to_dict(group), message="算力源解绑成功")


@router.post("/{group_id}/test")
async def test_group(
    group_id: str,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """测试分组所有算力源"""
    group = db.query(ComputeKeyGroup).filter(ComputeKeyGroup.group_id == group_id).first()
    if not group:
        return ApiResponse.error(code=404, message=f"分组 {group_id} 不存在")

    source_ids = group.source_ids or []
    if not source_ids:
        return ApiResponse.success(
            data={"group_id": group_id, "results": [], "total": 0, "success": 0},
            message="分组中没有算力源"
        )

    import asyncio
    from urllib.parse import urlparse

    results = []
    success_count = 0

    async def test_one(source: ComputeSource):
        test_result = {
            "source_id": source.source_id,
            "name": source.name,
            "reachable": False,
            "latency_ms": 0,
            "error": None,
        }
        try:
            parsed = urlparse(source.base_url)
            host = parsed.hostname or "localhost"
            port = parsed.port or (443 if parsed.scheme == "https" else 80)

            start_time = time.time()
            try:
                reader, writer = await asyncio.wait_for(
                    asyncio.open_connection(host, port),
                    timeout=min(source.timeout, 5)
                )
                writer.close()
                await writer.wait_closed()
                test_result["reachable"] = True
                test_result["latency_ms"] = int((time.time() - start_time) * 1000)
            except asyncio.TimeoutError:
                test_result["error"] = "连接超时"
            except Exception as e:
                test_result["error"] = str(e)
        except Exception as e:
            test_result["error"] = f"测试异常: {e}"
        return test_result

    async def run_all_tests():
        sources = db.query(ComputeSource).filter(
            ComputeSource.source_id.in_(source_ids)
        ).all()
        tasks = [test_one(s) for s in sources]
        return await asyncio.gather(*tasks)

    results = asyncio.run(run_all_tests())
    success_count = sum(1 for r in results if r["reachable"])

    return ApiResponse.success(
        data={
            "group_id": group_id,
            "total": len(results),
            "success": success_count,
            "failed": len(results) - success_count,
            "results": results,
        },
        message="分组测试完成"
    )
