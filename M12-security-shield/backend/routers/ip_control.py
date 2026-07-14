"""
云汐 M12 安全盾 - IP 访问控制 API
提供 IP 黑白名单管理、IP 检测、自动封禁等接口
"""

from fastapi import APIRouter, Query, Depends
from typing import Optional
from datetime import datetime

# 兼容相对导入和直接运行
try:
    from ..models import make_response, make_error_response
    from ..services.ip_filter import get_ip_filter
    from ..auth import require_role, ROLE_ADMIN, ROLE_OPERATOR
except ImportError:
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from models import make_response, make_error_response
    from services.ip_filter import get_ip_filter
    from auth import require_role, ROLE_ADMIN, ROLE_OPERATOR

router = APIRouter(prefix="/api/m12/ip", tags=["M12-IP访问控制"])


# ===========================================================================
# IP 检测
# ===========================================================================

@router.get("/check", summary="IP 状态检测")
def check_ip(ip_address: str = Query(..., description="要检测的 IP 地址")):
    """
    检测指定 IP 的状态（是否在黑白名单中、风险级别等）
    """
    try:
        ipf = get_ip_filter()
        result = ipf.check_ip(ip_address)
        return make_response(data=result)
    except Exception as e:
        return make_error_response(f"IP 检测失败: {str(e)}")


# ===========================================================================
# 黑名单管理
# ===========================================================================

@router.get("/blacklist", summary="黑名单列表")
def list_blacklist(
    severity: Optional[str] = Query(None, description="威胁级别筛选"),
    active_only: bool = Query(True, description="只返回生效的"),
    page: int = Query(1, ge=1, description="页码"),
    page_size: int = Query(20, ge=1, le=100, description="每页数量"),
):
    """
    获取 IP 黑名单列表
    """
    try:
        ipf = get_ip_filter()
        entries = ipf.get_blacklist(severity=severity, active_only=active_only)

        # 转换为字典
        items = [
            {
                "id": i + 1,
                "ip_address": e.ip_address,
                "ip_type": e.ip_type,
                "reason": e.reason,
                "severity": e.severity,
                "source": e.source,
                "banned_by": e.added_by,
                "banned_at": datetime.fromtimestamp(e.added_at).isoformat() if e.added_at else None,
                "expires_at": datetime.fromtimestamp(e.expires_at).isoformat() if e.expires_at else None,
                "is_active": e.is_active,
                "hit_count": e.hit_count,
                "last_hit_at": datetime.fromtimestamp(e.last_hit_at).isoformat() if e.last_hit_at else None,
            }
            for i, e in enumerate(entries)
        ]
        items.reverse()

        # 分页
        total = len(items)
        offset = (page - 1) * page_size
        paged_items = items[offset:offset + page_size]
        total_pages = (total + page_size - 1) // page_size if page_size > 0 else 0

        return make_response(data={
            "items": paged_items,
            "total": total,
            "page": page,
            "page_size": page_size,
            "total_pages": total_pages,
        })
    except Exception as e:
        return make_error_response(f"获取黑名单失败: {str(e)}")


@router.post("/blacklist", summary="添加黑名单")
def add_blacklist(
    ip_address: str,
    reason: str = "",
    severity: str = "medium",
    source: str = "manual",
    description: str = "",
    current_user: dict = Depends(require_role(ROLE_ADMIN)),
):
    """
    添加 IP 到黑名单
    """
    try:
        ipf = get_ip_filter()
        entry = ipf.add_to_blacklist(
            ip_address=ip_address,
            reason=reason,
            severity=severity,
            source=source,
            added_by="system",
            description=description,
        )

        result = {
            "ip_address": entry.ip_address,
            "ip_type": entry.ip_type,
            "reason": entry.reason,
            "severity": entry.severity,
            "source": entry.source,
            "banned_by": entry.added_by,
            "banned_at": datetime.fromtimestamp(entry.added_at).isoformat(),
            "expires_at": datetime.fromtimestamp(entry.expires_at).isoformat() if entry.expires_at else None,
            "is_active": entry.is_active,
            "hit_count": entry.hit_count,
            "description": entry.description,
        }

        return make_response(data=result, message="已添加到黑名单")
    except Exception as e:
        return make_error_response(f"添加黑名单失败: {str(e)}")


@router.delete("/blacklist/{ip_address}", summary="移除黑名单")
def remove_blacklist(
    ip_address: str,
    current_user: dict = Depends(require_role(ROLE_ADMIN)),
):
    """
    从黑名单中移除指定 IP
    """
    try:
        ipf = get_ip_filter()
        success = ipf.remove_from_blacklist(ip_address)
        if not success:
            return make_error_response(f"IP 不在黑名单中: {ip_address}", code=404)

        return make_response(data={"removed": True, "ip_address": ip_address}, message="已从黑名单移除")
    except Exception as e:
        return make_error_response(f"移除黑名单失败: {str(e)}")


# ===========================================================================
# 白名单管理
# ===========================================================================

@router.get("/whitelist", summary="白名单列表")
def list_whitelist(
    active_only: bool = Query(True, description="只返回生效的"),
    page: int = Query(1, ge=1, description="页码"),
    page_size: int = Query(20, ge=1, le=100, description="每页数量"),
):
    """
    获取 IP 白名单列表
    """
    try:
        ipf = get_ip_filter()
        entries = ipf.get_whitelist(active_only=active_only)

        # 转换为字典
        items = [
            {
                "id": i + 1,
                "ip_address": e.ip_address,
                "ip_type": e.ip_type,
                "reason": e.reason,
                "source": e.source,
                "added_by": e.added_by,
                "added_at": datetime.fromtimestamp(e.added_at).isoformat() if e.added_at else None,
                "expires_at": datetime.fromtimestamp(e.expires_at).isoformat() if e.expires_at else None,
                "is_active": e.is_active,
                "description": e.description,
            }
            for i, e in enumerate(entries)
        ]
        items.reverse()

        # 分页
        total = len(items)
        offset = (page - 1) * page_size
        paged_items = items[offset:offset + page_size]
        total_pages = (total + page_size - 1) // page_size if page_size > 0 else 0

        return make_response(data={
            "items": paged_items,
            "total": total,
            "page": page,
            "page_size": page_size,
            "total_pages": total_pages,
        })
    except Exception as e:
        return make_error_response(f"获取白名单失败: {str(e)}")


@router.post("/whitelist", summary="添加白名单")
def add_whitelist(
    ip_address: str,
    reason: str = "",
    source: str = "manual",
    description: str = "",
    current_user: dict = Depends(require_role(ROLE_ADMIN)),
):
    """
    添加 IP 到白名单
    """
    try:
        ipf = get_ip_filter()
        entry = ipf.add_to_whitelist(
            ip_address=ip_address,
            reason=reason,
            source=source,
            added_by="system",
            description=description,
        )

        result = {
            "ip_address": entry.ip_address,
            "ip_type": entry.ip_type,
            "reason": entry.reason,
            "source": entry.source,
            "added_by": entry.added_by,
            "added_at": datetime.fromtimestamp(entry.added_at).isoformat(),
            "expires_at": datetime.fromtimestamp(entry.expires_at).isoformat() if entry.expires_at else None,
            "is_active": entry.is_active,
            "description": entry.description,
        }

        return make_response(data=result, message="已添加到白名单")
    except Exception as e:
        return make_error_response(f"添加白名单失败: {str(e)}")


@router.delete("/whitelist/{ip_address}", summary="移除白名单")
def remove_whitelist(
    ip_address: str,
    current_user: dict = Depends(require_role(ROLE_ADMIN)),
):
    """
    从白名单中移除指定 IP
    """
    try:
        ipf = get_ip_filter()
        success = ipf.remove_from_whitelist(ip_address)
        if not success:
            return make_error_response(f"IP 不在白名单中: {ip_address}", code=404)

        return make_response(data={"removed": True, "ip_address": ip_address}, message="已从白名单移除")
    except Exception as e:
        return make_error_response(f"移除白名单失败: {str(e)}")


# ===========================================================================
# 统计信息
# ===========================================================================

@router.get("/stats", summary="IP 控制统计")
def ip_stats():
    """
    获取 IP 访问控制的统计信息
    """
    try:
        ipf = get_ip_filter()
        stats = ipf.get_stats()
        return make_response(data=stats)
    except Exception as e:
        return make_error_response(f"获取统计信息失败: {str(e)}")
