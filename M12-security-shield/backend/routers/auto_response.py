"""
云汐 M12 安全盾 - 自动响应管理 API
提供响应规则管理、封禁 IP 管理、响应设置等接口

所有接口均需鉴权保护。
"""

from fastapi import APIRouter, Depends, Query
from typing import Optional
from pydantic import BaseModel, Field

# 兼容相对导入和直接运行
try:
    from ..schemas.common import make_response, make_error_response
    from ..services.auto_response import (
        get_auto_response_engine,
        SecurityEvent,
        RESPONSE_LEVEL_DETECT,
        RESPONSE_LEVEL_LOG,
        RESPONSE_LEVEL_BLOCK,
        VALID_RESPONSE_LEVELS,
    )
    from ..auth import get_current_user, require_role, require_scope
    from ..auth import ROLE_ADMIN, ROLE_OPERATOR, ROLE_VIEWER
except ImportError:
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from schemas.common import make_response, make_error_response
    from services.auto_response import (
        get_auto_response_engine,
        SecurityEvent,
        RESPONSE_LEVEL_DETECT,
        RESPONSE_LEVEL_LOG,
        RESPONSE_LEVEL_BLOCK,
        VALID_RESPONSE_LEVELS,
    )
    from auth import get_current_user, require_role, require_scope
    from auth import ROLE_ADMIN, ROLE_OPERATOR, ROLE_VIEWER

router = APIRouter(prefix="/api/m12/auto-response", tags=["M12-自动响应"])


# ===========================================================================
# 请求/响应模型
# ===========================================================================

class UpdateRuleRequest(BaseModel):
    """更新规则请求"""
    name: Optional[str] = Field(default=None, max_length=200, description="规则名称")
    description: Optional[str] = Field(default=None, max_length=500, description="规则描述")
    threshold: Optional[int] = Field(default=None, ge=1, description="触发阈值")
    time_window_seconds: Optional[int] = Field(default=None, ge=1, description="时间窗口（秒）")
    action: Optional[str] = Field(default=None, description="动作：log/ban/alert")
    ban_duration_minutes: Optional[int] = Field(default=None, ge=0, description="封禁时长（分钟）")
    risk_level: Optional[str] = Field(default=None, description="风险级别")
    enabled: Optional[bool] = Field(default=None, description="是否启用")


class UpdateSettingsRequest(BaseModel):
    """更新设置请求"""
    response_level: str = Field(..., description="响应级别：detect/log/block")

    @classmethod
    def validate_response_level(cls, v: str) -> str:
        if v not in VALID_RESPONSE_LEVELS:
            raise ValueError(f"response_level 必须是以下值之一: {VALID_RESPONSE_LEVELS}")
        return v


class BanIpRequest(BaseModel):
    """手动封禁 IP 请求"""
    ip_address: str = Field(..., max_length=50, description="IP 地址")
    duration_minutes: int = Field(default=60, ge=0, description="封禁时长（分钟），0 表示永久")
    reason: str = Field(default="", max_length=500, description="封禁原因")
    rule_id: str = Field(default="manual", max_length=100, description="规则 ID")


class EventSubmitRequest(BaseModel):
    """提交安全事件请求"""
    event_type: str = Field(..., max_length=100, description="事件类型")
    source_ip: str = Field(..., max_length=50, description="来源 IP")
    severity: str = Field(default="medium", max_length=20, description="严重级别")
    target_path: str = Field(default="", max_length=500, description="目标路径")
    method: str = Field(default="", max_length=10, description="请求方法")
    description: str = Field(default="", max_length=1000, description="事件描述")
    rule_name: str = Field(default="", max_length=200, description="触发的规则名称")
    user_agent: str = Field(default="", max_length=500, description="用户代理")


# ===========================================================================
# 响应规则管理
# ===========================================================================

@router.get("/rules", summary="获取响应规则列表")
async def list_response_rules(
    current_user: dict = Depends(require_role(ROLE_VIEWER)),
):
    """
    获取所有自动响应规则列表（需鉴权）
    """
    try:
        engine = get_auto_response_engine()
        rules = engine.get_rules()
        return make_response(data={
            "items": rules,
            "total": len(rules),
        })
    except Exception as e:
        return make_error_response(f"获取响应规则失败: {str(e)}")


@router.put("/rules/{rule_id}", summary="修改响应规则")
async def update_response_rule(
    rule_id: str,
    request: UpdateRuleRequest,
    current_user: dict = Depends(require_role(ROLE_ADMIN)),
):
    """
    修改指定的自动响应规则配置（需管理员权限）
    """
    try:
        engine = get_auto_response_engine()
        updates = request.model_dump(exclude_none=True)
        if not updates:
            return make_error_response("没有需要更新的字段", code=400)

        result = engine.update_rule(rule_id, updates)
        if not result:
            return make_error_response(f"规则不存在: {rule_id}", code=404)

        return make_response(data=result, message="规则更新成功")
    except Exception as e:
        return make_error_response(f"更新规则失败: {str(e)}")


# ===========================================================================
# 封禁 IP 管理
# ===========================================================================

@router.get("/banned-ips", summary="获取封禁 IP 列表")
async def list_banned_ips(
    active_only: bool = Query(default=True, description="是否只返回生效的封禁"),
    page: int = Query(default=1, ge=1, description="页码"),
    page_size: int = Query(default=20, ge=1, le=100, description="每页数量"),
    current_user: dict = Depends(require_role(ROLE_VIEWER)),
):
    """
    获取被封禁的 IP 列表（需鉴权）
    """
    try:
        engine = get_auto_response_engine()
        all_banned = engine.get_banned_ips(active_only=active_only)

        # 分页
        total = len(all_banned)
        offset = (page - 1) * page_size
        paged = all_banned[offset:offset + page_size]
        total_pages = (total + page_size - 1) // page_size if page_size > 0 else 0

        return make_response(data={
            "items": paged,
            "total": total,
            "page": page,
            "page_size": page_size,
            "total_pages": total_pages,
        })
    except Exception as e:
        return make_error_response(f"获取封禁列表失败: {str(e)}")


@router.post("/banned-ips/{ip}/unban", summary="手动解封 IP")
async def unban_ip(
    ip: str,
    current_user: dict = Depends(require_role(ROLE_OPERATOR)),
):
    """
    手动解封指定 IP（需运维人员权限）
    """
    try:
        engine = get_auto_response_engine()
        success = engine.unban_ip(ip)
        if not success:
            return make_error_response(f"IP 未被封禁或不存在: {ip}", code=404)

        return make_response(
            data={"ip": ip, "unbanned": True},
            message="IP 已解封"
        )
    except Exception as e:
        return make_error_response(f"解封失败: {str(e)}")


@router.post("/banned-ips", summary="手动封禁 IP")
async def ban_ip(
    request: BanIpRequest,
    current_user: dict = Depends(require_role(ROLE_OPERATOR)),
):
    """
    手动封禁 IP（需运维人员权限）
    """
    try:
        engine = get_auto_response_engine()
        success = engine.ban_ip(
            ip=request.ip_address,
            duration_minutes=request.duration_minutes,
            reason=request.reason,
            rule_id=request.rule_id,
        )
        if not success:
            return make_error_response("封禁失败", code=500)

        return make_response(
            data={
                "ip_address": request.ip_address,
                "duration_minutes": request.duration_minutes,
                "reason": request.reason,
                "banned": True,
            },
            message="IP 已封禁"
        )
    except Exception as e:
        return make_error_response(f"封禁失败: {str(e)}")


# ===========================================================================
# 响应设置
# ===========================================================================

@router.get("/settings", summary="获取响应设置")
async def get_response_settings(
    current_user: dict = Depends(require_role(ROLE_VIEWER)),
):
    """
    获取自动响应设置（需鉴权）
    """
    try:
        engine = get_auto_response_engine()
        stats = engine.get_stats()
        return make_response(data={
            "response_level": stats["response_level"],
            "valid_levels": sorted(list(VALID_RESPONSE_LEVELS)),
            "level_descriptions": {
                RESPONSE_LEVEL_DETECT: "只记录，不拦截（默认，安全模式）",
                RESPONSE_LEVEL_LOG: "记录 + 告警",
                RESPONSE_LEVEL_BLOCK: "记录 + 拦截 + 封禁（严格模式）",
            },
            "total_rules": stats["total_rules"],
            "enabled_rules": stats["enabled_rules"],
        })
    except Exception as e:
        return make_error_response(f"获取设置失败: {str(e)}")


@router.put("/settings", summary="修改响应设置")
async def update_response_settings(
    request: UpdateSettingsRequest,
    current_user: dict = Depends(require_role(ROLE_ADMIN)),
):
    """
    修改自动响应设置（需管理员权限）

    响应级别说明：
    - detect：只记录，不拦截（默认，最安全，不影响业务）
    - log：记录 + 告警（有告警但不拦截）
    - block：记录 + 拦截 + 封禁（严格模式，可能误封）
    """
    try:
        # 验证级别
        if request.response_level not in VALID_RESPONSE_LEVELS:
            return make_error_response(
                f"无效的响应级别: {request.response_level}，"
                f"有效值: {VALID_RESPONSE_LEVELS}",
                code=400
            )

        engine = get_auto_response_engine()
        success = engine.set_response_level(request.response_level)
        if not success:
            return make_error_response("设置失败", code=500)

        return make_response(
            data={"response_level": request.response_level},
            message=f"响应级别已设置为: {request.response_level}"
        )
    except Exception as e:
        return make_error_response(f"设置更新失败: {str(e)}")


# ===========================================================================
# 事件提交与告警
# ===========================================================================

@router.post("/events", summary="提交安全事件")
async def submit_event(
    request: EventSubmitRequest,
    current_user: dict = Depends(get_current_user),
):
    """
    提交安全事件，触发自动响应处理（需鉴权）

    系统会根据当前响应级别和规则自动判断是否执行响应动作。
    """
    try:
        engine = get_auto_response_engine()
        event = SecurityEvent(
            event_type=request.event_type,
            source_ip=request.source_ip,
            severity=request.severity,
            target_path=request.target_path,
            method=request.method,
            description=request.description,
            rule_name=request.rule_name,
            user_agent=request.user_agent,
        )
        result = engine.process_event(event)
        return make_response(data=result)
    except Exception as e:
        return make_error_response(f"事件处理失败: {str(e)}")


@router.get("/alerts", summary="获取告警列表")
async def get_alerts(
    limit: int = Query(default=50, ge=1, le=500, description="返回数量"),
    current_user: dict = Depends(require_role(ROLE_VIEWER)),
):
    """
    获取最近的告警列表（需鉴权）
    """
    try:
        engine = get_auto_response_engine()
        alerts = engine.get_alerts(limit=limit)
        return make_response(data={
            "items": alerts,
            "total": len(alerts),
        })
    except Exception as e:
        return make_error_response(f"获取告警失败: {str(e)}")


@router.get("/stats", summary="自动响应统计")
async def get_auto_response_stats(
    current_user: dict = Depends(require_role(ROLE_VIEWER)),
):
    """
    获取自动响应统计信息（需鉴权）
    """
    try:
        engine = get_auto_response_engine()
        stats = engine.get_stats()
        return make_response(data=stats)
    except Exception as e:
        return make_error_response(f"获取统计失败: {str(e)}")
