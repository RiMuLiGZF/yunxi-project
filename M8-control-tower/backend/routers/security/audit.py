"""
审计日志路由（升级版）
=======================
SC-007 P1级 - 审计日志全覆盖

已升级接入统一审计框架，新增 API：
- GET /logs - 查询审计日志（增强：支持分类、级别筛选）
- GET /logs/{event_id} - 获取单条审计详情
- GET /stats - 审计统计数据
- GET /export - 导出审计日志（支持 CSV/JSON）
- GET /categories - 获取审计分类列表
- GET /levels - 获取审计级别列表
- GET /integrity - 验证审计日志完整性
- POST /logs - 手动记录审计事件（内部使用）

**向后兼容**：原有 API 保持不变，旧前端可继续使用。
"""

import sys
import json
import logging
import io
from pathlib import Path
from datetime import datetime
from fastapi import APIRouter, Depends, Query, Request, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Any

project_root = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(project_root))

from ...schemas import ApiResponse
from ...auth import get_current_user, has_role
from ...audit import (
    query_audit_logs,
    export_audit_logs_csv,
    export_audit_logs_json,
    get_audit_stats,
    get_audit_categories,
    get_audit_levels,
    get_audit_actions,
    verify_audit_integrity,
    clean_expired_audit_logs,
    log_authentication,
    log_user_management,
    log_configuration_change,
    log_security_event,
    log_system_event,
    get_m8_audit_logger,
)
from shared.core.audit_framework import (
    AuditEvent,
    AuditCategory,
    AuditLevel,
    AuditResult,
)

router = APIRouter()

logger = logging.getLogger("m8.audit.router")


# ===========================================================================
# 请求体模型
# ===========================================================================

class ManualAuditRequest(BaseModel):
    """手动记录审计事件的请求体"""
    category: str = Field(default="system", description="审计分类")
    level: str = Field(default="info", description="严重级别")
    action: str = Field(..., description="操作类型")
    module: str = Field(default="system", description="模块")
    description: str = Field(default="", description="描述")
    result: str = Field(default="success", description="结果")
    resource_type: str = Field(default="", description="资源类型")
    resource_id: str = Field(default="", description="资源ID")
    metadata: Optional[Dict[str, Any]] = Field(default=None, description="附加元数据")


class AuditForwardRequest(BaseModel):
    """审计日志转发请求体"""
    path: str = ""
    method: str = ""
    description: str = ""


# ===========================================================================
# 权限检查辅助函数
# ===========================================================================

def _check_audit_permission(current_user: dict, target_username: Optional[str] = None) -> bool:
    """
    检查审计权限

    - owner/auditor: 可查看全部
    - admin: 只能查看自己的日志

    Args:
        current_user: 当前用户
        target_username: 目标用户名（如果是查询特定用户）

    Returns:
        True 表示有权限
    """
    user_role = current_user.get("role", "")
    username = current_user.get("username", "")

    if has_role(user_role, "owner") or user_role == "auditor":
        return True

    # admin 只能查看自己的
    if target_username and target_username == username:
        return True

    return False


def _apply_permission_filter(current_user: dict, username: Optional[str]) -> Optional[str]:
    """
    应用权限过滤

    如果用户没有查看全部的权限，强制限定为只能查看自己的日志。
    """
    user_role = current_user.get("role", "")
    current_username = current_user.get("username", "")

    if has_role(user_role, "owner") or user_role == "auditor":
        return username  # 保持原样

    # 普通用户只能看自己的
    return current_username


# ===========================================================================
# 查询审计日志
# ===========================================================================

@router.get("/logs")
async def get_audit_logs(
    username: Optional[str] = Query(None, description="按用户名/操作者筛选"),
    action: Optional[str] = Query(None, description="按操作类型筛选"),
    module: Optional[str] = Query(None, description="按模块筛选"),
    result: Optional[str] = Query(None, description="按结果筛选（success/failed）"),
    category: Optional[str] = Query(None, description="按事件分类筛选"),
    level: Optional[str] = Query(None, description="按严重级别筛选"),
    start_time: Optional[str] = Query(None, description="开始时间 YYYY-MM-DD HH:MM:SS"),
    end_time: Optional[str] = Query(None, description="结束时间 YYYY-MM-DD HH:MM:SS"),
    page: int = Query(1, ge=1, description="页码"),
    page_size: int = Query(20, ge=1, le=100, description="每页数量"),
    sort_by: str = Query("timestamp", description="排序字段"),
    sort_order: str = Query("desc", description="排序方向（asc/desc）"),
    current_user: dict = Depends(get_current_user),
):
    """获取审计日志列表（分页+筛选+排序）

    **权限**：
    - owner/auditor: 可查看全部
    - admin: 只能查看自己的日志
    """
    # 应用权限过滤
    filtered_username = _apply_permission_filter(current_user, username)

    result_data = query_audit_logs(
        username=filtered_username,
        action=action,
        module=module,
        result=result,
        category=category,
        level=level,
        start_time=start_time,
        end_time=end_time,
        page=page,
        page_size=page_size,
        sort_by=sort_by,
        sort_order=sort_order,
    )

    return ApiResponse.success(data=result_data)


# ===========================================================================
# 获取单条审计详情
# ===========================================================================

@router.get("/logs/{event_id}")
async def get_audit_detail(
    event_id: str,
    current_user: dict = Depends(get_current_user),
):
    """获取单条审计事件详情

    **权限**：
    - owner/auditor: 可查看任意日志
    - admin: 只能查看自己的日志
    """
    audit = get_m8_audit_logger()
    event = audit.get_event(event_id)

    if not event:
        raise HTTPException(status_code=404, detail="审计事件不存在")

    # 权限检查
    user_role = current_user.get("role", "")
    username = current_user.get("username", "")

    if not has_role(user_role, "owner") and user_role != "auditor":
        if event.get("actor") != username:
            raise HTTPException(status_code=403, detail="无权查看此审计日志")

    return ApiResponse.success(data=event)


# ===========================================================================
# 导出审计日志
# ===========================================================================

@router.get("/logs/export")
async def export_audit_logs(
    username: Optional[str] = Query(None, description="按用户名筛选"),
    action: Optional[str] = Query(None, description="按操作类型筛选"),
    module: Optional[str] = Query(None, description="按模块筛选"),
    result: Optional[str] = Query(None, description="按结果筛选"),
    category: Optional[str] = Query(None, description="按事件分类筛选"),
    level: Optional[str] = Query(None, description="按严重级别筛选"),
    start_time: Optional[str] = Query(None, description="开始时间 YYYY-MM-DD HH:MM:SS"),
    end_time: Optional[str] = Query(None, description="结束时间 YYYY-MM-DD HH:MM:SS"),
    format: str = Query("csv", description="导出格式（csv/json）"),
    current_user: dict = Depends(get_current_user),
):
    """导出审计日志（支持 CSV 和 JSON 格式）

    **权限**：
    - owner/auditor: 可导出全部
    - admin: 只能导出自己的日志
    """
    # 应用权限过滤
    filtered_username = _apply_permission_filter(current_user, username)

    if format.lower() == "json":
        content = export_audit_logs_json(
            username=filtered_username,
            action=action,
            module=module,
            result=result,
            category=category,
            level=level,
            start_time=start_time,
            end_time=end_time,
        )
        media_type = "application/json"
        ext = "json"
    else:
        content = export_audit_logs_csv(
            username=filtered_username,
            action=action,
            module=module,
            result=result,
            category=category,
            level=level,
            start_time=start_time,
            end_time=end_time,
        )
        media_type = "text/csv"
        ext = "csv"

    filename = f"audit_logs_{datetime.now().strftime('%Y%m%d_%H%M%S')}.{ext}"

    return StreamingResponse(
        io.StringIO(content),
        media_type=f"{media_type}; charset=utf-8",
        headers={
            "Content-Disposition": f"attachment; filename={filename}",
        },
    )


# ===========================================================================
# 审计统计
# ===========================================================================

@router.get("/stats")
async def get_audit_statistics(
    time_range: str = Query("24h", description="时间范围（1h/24h/7d/30d/all）"),
    current_user: dict = Depends(get_current_user),
):
    """获取审计统计数据（用于仪表板）

    返回按分类、级别、模块、操作等维度的统计数据。

    **权限**：
    - owner/auditor: 可查看全部统计
    - admin: 只能查看自己的统计（暂不支持，返回空数据）
    """
    user_role = current_user.get("role", "")

    if not has_role(user_role, "owner") and user_role != "auditor":
        # 普通用户暂不提供统计数据
        return ApiResponse.success(data={
            "total": 0,
            "time_range": time_range,
            "by_category": {},
            "by_level": {},
            "by_module": {},
            "by_result": {},
            "top_actions": [],
            "by_day": {},
            "critical_count": 0,
            "warning_count": 0,
            "failure_count": 0,
        })

    stats = get_audit_stats(time_range=time_range)
    return ApiResponse.success(data=stats)


# ===========================================================================
# 获取审计分类/级别/操作列表
# ===========================================================================

@router.get("/categories")
async def list_audit_categories(
    current_user: dict = Depends(get_current_user),
):
    """获取所有审计事件分类列表（用于筛选下拉框）"""
    categories = get_audit_categories()
    return ApiResponse.success(data=categories)


@router.get("/levels")
async def list_audit_levels(
    current_user: dict = Depends(get_current_user),
):
    """获取所有审计级别列表（用于筛选下拉框）"""
    levels = get_audit_levels()
    return ApiResponse.success(data=levels)


@router.get("/logs/actions")
async def get_audit_actions_list(
    current_user: dict = Depends(get_current_user),
):
    """获取所有操作类型列表（用于筛选下拉框）

    **向后兼容**：保留原有接口，同时返回新增的分类和级别。
    """
    actions = get_audit_actions()
    modules = [
        "auth", "user", "system", "module", "security", "audit",
        "configuration", "data_management", "api",
    ]
    results = ["success", "failed"]

    return ApiResponse.success(
        data={
            "actions": actions,
            "modules": modules,
            "results": results,
            "categories": get_audit_categories(),
            "levels": get_audit_levels(),
        }
    )


# ===========================================================================
# 审计完整性校验
# ===========================================================================

@router.get("/integrity")
async def check_audit_integrity(
    current_user: dict = Depends(get_current_user),
):
    """验证审计日志完整性（链式哈希校验）

    检查审计日志是否被篡改。

    **权限**：仅 owner 和 auditor
    """
    user_role = current_user.get("role", "")

    if not has_role(user_role, "owner") and user_role != "auditor":
        raise HTTPException(status_code=403, detail="需要 owner 或 auditor 权限")

    result = verify_audit_integrity()
    return ApiResponse.success(data=result)


# ===========================================================================
# 手动记录审计事件（内部使用）
# ===========================================================================

@router.post("/logs")
async def create_audit_log(
    req: ManualAuditRequest,
    request: Request,
    current_user: dict = Depends(get_current_user),
):
    """手动记录审计事件（内部使用）

    用于模块间调用或特殊场景下手动添加审计记录。

    **权限**：需要 owner 权限
    """
    user_role = current_user.get("role", "")
    if not has_role(user_role, "owner"):
        raise HTTPException(status_code=403, detail="需要 owner 权限")

    # 提取请求信息
    ip_address = ""
    user_agent = ""
    try:
        if request.client:
            ip_address = request.client.host
        forwarded = request.headers.get("X-Forwarded-For", "")
        if forwarded:
            ip_address = forwarded.split(",")[0].strip()
        user_agent = request.headers.get("User-Agent", "")
    except Exception:
        pass

    audit = get_m8_audit_logger()
    event = AuditEvent(
        category=req.category,
        level=req.level,
        actor=current_user.get("username", ""),
        module=req.module,
        action=req.action,
        resource_type=req.resource_type,
        resource_id=req.resource_id,
        description=req.description,
        result=req.result,
        ip_address=ip_address,
        user_agent=user_agent,
        metadata=req.metadata or {},
    )
    audit.log(event)

    return ApiResponse.success(data=event.to_dict(), message="审计事件已记录")


# ===========================================================================
# 清理过期审计日志
# ===========================================================================

@router.post("/cleanup")
async def cleanup_expired_logs(
    retention_days: int = Query(180, ge=1, le=3650, description="保留天数"),
    current_user: dict = Depends(get_current_user),
):
    """清理过期的审计日志

    **权限**：仅 owner
    """
    user_role = current_user.get("role", "")
    if not has_role(user_role, "owner"):
        raise HTTPException(status_code=403, detail="需要 owner 权限")

    deleted = clean_expired_audit_logs(retention_days)
    return ApiResponse.success(data={"deleted_files": deleted}, message=f"已清理 {deleted} 个过期日志文件")


# ===========================================================================
# 审计日志转发到 M12（向后兼容）
# ===========================================================================

M12_FORWARD_URL = "http://localhost:8012/api/m12/auto-response/events"


@router.post("/forward")
async def forward_audit_to_m12(
    req: AuditForwardRequest,
    request: Request,
    current_user: dict = Depends(get_current_user),
):
    """转发审计日志条目到 M12 自动响应系统（尽力而为，失败不影响主流程）"""
    import httpx

    source_ip = "unknown"
    try:
        if request.client:
            source_ip = request.client.host
    except Exception:
        pass

    payload = {
        "event_type": "audit_log",
        "source_ip": source_ip,
        "severity": "info",
        "target_path": req.path,
        "method": req.method,
        "description": req.description,
    }

    try:
        async with httpx.AsyncClient(timeout=5.0) as m12_client:
            m12_resp = await m12_client.post(M12_FORWARD_URL, json=payload)
            if m12_resp.status_code == 200:
                return ApiResponse.success(data={"forwarded": True}, message="审计日志已转发到 M12")
            else:
                logger.warning(
                    "审计日志转发到 M12 返回非 200 状态码: %s",
                    m12_resp.status_code,
                )
                return ApiResponse.success(data={"forwarded": False}, message="M12 返回非成功状态码")
    except Exception as e:
        logger.warning("审计日志转发到 M12 失败（尽力而为）: %s", str(e))
        return ApiResponse.success(data={"forwarded": False}, message="转发失败，但不影响审计记录")
