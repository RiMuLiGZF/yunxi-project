"""
M0 主理人管控台 - 审计日志路由

记录和查询系统操作审计日志。
MVP 版本：存储在本地 SQLite 数据库中。
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, Depends, Query

from ..auth import get_principal_user
from ..database import execute_query, execute_update
from ..models import ApiResponse, AuditLogItem, PaginatedData

router = APIRouter(tags=["审计日志"])


def _record_audit_log(
    action: str,
    operator: str,
    module: str = "system",
    detail: str = "",
    ip: Optional[str] = None,
    success: bool = True,
) -> None:
    """
    记录审计日志（内部工具函数）

    Args:
        action: 操作类型
        operator: 操作人
        module: 涉及模块
        detail: 操作详情
        ip: IP 地址
        success: 是否成功
    """
    log_id = str(uuid.uuid4())
    created_at = datetime.now().isoformat()

    execute_update(
        """
        INSERT INTO audit_logs (id, action, operator, module, detail, ip, success, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (log_id, action, operator, module, detail, ip, 1 if success else 0, created_at),
    )


@router.get("", summary="获取审计日志列表")
async def list_audit_logs(
    page: int = Query(1, ge=1, description="页码"),
    page_size: int = Query(20, ge=1, le=100, description="每页数量"),
    action: Optional[str] = Query(None, description="按操作类型筛选"),
    module: Optional[str] = Query(None, description="按模块筛选"),
    operator: Optional[str] = Query(None, description="按操作人筛选"),
    user: dict = Depends(get_principal_user),
) -> ApiResponse[PaginatedData[AuditLogItem]]:
    """
    分页获取审计日志列表

    支持按操作类型、模块、操作人筛选。
    """
    # 构建查询条件
    conditions = []
    params: list = []

    if action:
        conditions.append("action = ?")
        params.append(action)
    if module:
        conditions.append("module = ?")
        params.append(module)
    if operator:
        conditions.append("operator = ?")
        params.append(operator)

    where_clause = ""
    if conditions:
        where_clause = "WHERE " + " AND ".join(conditions)

    # 查询总数
    count_sql = f"SELECT COUNT(*) as total FROM audit_logs {where_clause}"
    count_result = execute_query(count_sql, tuple(params))
    total = count_result[0]["total"] if count_result else 0

    # 查询分页数据
    offset = (page - 1) * page_size
    data_sql = f"""
        SELECT * FROM audit_logs {where_clause}
        ORDER BY created_at DESC
        LIMIT ? OFFSET ?
    """
    data_params = tuple(params) + (page_size, offset)
    rows = execute_query(data_sql, data_params)

    # 转换为模型
    items = []
    for row in rows:
        items.append(AuditLogItem(
            id=row["id"],
            action=row["action"],
            operator=row["operator"],
            module=row["module"],
            detail=row["detail"],
            ip=row["ip"],
            success=bool(row["success"]),
            created_at=row["created_at"],
        ))

    paginated = PaginatedData[AuditLogItem](
        items=items,
        total=total,
        page=page,
        page_size=page_size,
    )

    return ApiResponse.success(data=paginated, message=f"共 {total} 条记录")


@router.get("/{log_id}", summary="获取审计日志详情")
async def get_audit_log(
    log_id: str,
    user: dict = Depends(get_principal_user),
) -> ApiResponse[AuditLogItem]:
    """
    获取单条审计日志的详细信息
    """
    rows = execute_query(
        "SELECT * FROM audit_logs WHERE id = ?",
        (log_id,),
    )

    if not rows:
        return ApiResponse.error(message="审计日志不存在", code=40400)

    row = rows[0]
    item = AuditLogItem(
        id=row["id"],
        action=row["action"],
        operator=row["operator"],
        module=row["module"],
        detail=row["detail"],
        ip=row["ip"],
        success=bool(row["success"]),
        created_at=row["created_at"],
    )

    return ApiResponse.success(data=item, message="获取成功")


@router.get("/actions/types", summary="获取操作类型列表")
async def get_action_types(
    user: dict = Depends(get_principal_user),
) -> ApiResponse[List[str]]:
    """
    获取所有操作类型（用于筛选下拉框）
    """
    rows = execute_query("SELECT DISTINCT action FROM audit_logs ORDER BY action")
    actions = [row["action"] for row in rows]

    # 如果数据库为空，返回默认操作类型
    if not actions:
        actions = [
            "login", "logout", "config_update", "config_reset",
            "module_start", "module_stop", "module_restart",
            "user_create", "user_update", "user_delete",
            "role_change", "system_upgrade", "system_rollback",
            "emergency_lockdown", "emergency_unlock",
        ]

    return ApiResponse.success(data=actions, message="获取成功")
