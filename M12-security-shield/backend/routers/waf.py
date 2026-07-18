"""
云汐 M12 安全盾 - WAF 防护墙 API
提供 WAF 规则管理、状态查询、攻击检测等接口
"""

from fastapi import APIRouter, Query, Depends
from typing import Optional, List

# 兼容相对导入和直接运行
try:
    from ..schemas.common import make_response, make_error_response
    from ..services.waf_engine import get_waf_engine
    from ..schemas.waf import (
        WafRuleCreate, WafRuleUpdate,
        GatewayWafCheckRequest, GatewayWafCheckResponse,
        GatewayWafBatchRequest, GatewayWafBatchResponse,
    )
    from ..auth import get_current_user, require_scope, require_role, SCOPE_WAF_READ, SCOPE_WAF_WRITE, ROLE_ADMIN
except ImportError:
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from schemas.common import make_response, make_error_response
    from services.waf_engine import get_waf_engine
    from schemas.waf import (
        WafRuleCreate, WafRuleUpdate,
        GatewayWafCheckRequest, GatewayWafCheckResponse,
        GatewayWafBatchRequest, GatewayWafBatchResponse,
    )
    from auth import get_current_user, require_scope, require_role, SCOPE_WAF_READ, SCOPE_WAF_WRITE, ROLE_ADMIN

router = APIRouter(prefix="/api/m12/waf", tags=["M12-WAF防护墙"])


# ===========================================================================
# WAF 状态
# ===========================================================================

@router.get("/status", summary="WAF 状态查询")
def waf_status():
    """
    获取 WAF 防护墙的当前运行状态
    """
    try:
        waf = get_waf_engine()
        status = waf.get_status()
        return make_response(data=status)
    except Exception as e:
        return make_error_response(f"获取WAF状态失败: {str(e)}")


@router.post("/toggle", summary="启用/禁用 WAF")
def waf_toggle(
    enabled: Optional[bool] = None,
    current_user: dict = Depends(require_role(ROLE_ADMIN)),
):
    """
    启用或禁用 WAF 防护墙

    - 如果指定 enabled 参数，则设置为指定状态
    - 如果不指定，则切换当前状态
    """
    try:
        waf = get_waf_engine()
        if enabled is not None:
            if enabled:
                waf.enable()
            else:
                waf.disable()
        else:
            waf.toggle()

        status = waf.get_status()
        return make_response(data={
            "enabled": status["enabled"],
            "message": f"WAF已{'启用' if status['enabled'] else '禁用'}",
        })
    except Exception as e:
        return make_error_response(f"切换WAF状态失败: {str(e)}")


# ===========================================================================
# WAF 规则管理
# ===========================================================================

@router.get("/rules", summary="获取规则列表")
def list_rules(
    rule_type: Optional[str] = Query(None, description="规则类型筛选"),
    is_active: Optional[bool] = Query(None, description="是否启用筛选"),
    page: int = Query(1, ge=1, description="页码"),
    page_size: int = Query(20, ge=1, le=100, description="每页数量"),
):
    """
    获取 WAF 规则列表，支持按类型和状态筛选
    """
    try:
        waf = get_waf_engine()
        rules = waf.get_rules(rule_type=rule_type, is_active=is_active)

        # 分页
        total = len(rules)
        offset = (page - 1) * page_size
        paged_rules = rules[offset:offset + page_size]
        total_pages = (total + page_size - 1) // page_size if page_size > 0 else 0

        return make_response(data={
            "items": paged_rules,
            "total": total,
            "page": page,
            "page_size": page_size,
            "total_pages": total_pages,
        })
    except Exception as e:
        return make_error_response(f"获取规则列表失败: {str(e)}")


@router.get("/rules/{rule_id}", summary="获取规则详情")
def get_rule(rule_id: int):
    """
    根据 ID 获取单个 WAF 规则的详细信息
    """
    try:
        waf = get_waf_engine()
        rules = waf.get_rules()
        rule = next((r for r in rules if r["id"] == rule_id), None)

        if not rule:
            return make_error_response(f"规则不存在: {rule_id}", code=404)

        return make_response(data=rule)
    except Exception as e:
        return make_error_response(f"获取规则详情失败: {str(e)}")


@router.post("/rules", summary="新增自定义规则")
def create_rule(
    rule_name: str,
    pattern: str,
    rule_type: str = "custom",
    category: str = "",
    match_target: str = "all",
    severity: str = "medium",
    action: str = "block",
    description: str = "",
    is_active: bool = True,
    current_user: dict = Depends(require_role(ROLE_ADMIN)),
):
    """
    新增自定义 WAF 防护规则
    """
    try:
        waf = get_waf_engine()
        new_rule = waf.add_rule({
            "name": rule_name,
            "type": rule_type,
            "category": category,
            "pattern": pattern,
            "match_target": match_target,
            "severity": severity,
            "action": action,
            "description": description,
            "is_active": is_active,
        })
        return make_response(data=new_rule, message="规则创建成功")
    except Exception as e:
        return make_error_response(f"创建规则失败: {str(e)}")


@router.put("/rules/{rule_id}", summary="更新规则")
def update_rule(
    rule_id: int,
    rule_name: Optional[str] = None,
    pattern: Optional[str] = None,
    severity: Optional[str] = None,
    action: Optional[str] = None,
    description: Optional[str] = None,
    is_active: Optional[bool] = None,
    current_user: dict = Depends(require_role(ROLE_ADMIN)),
):
    """
    更新指定的 WAF 规则配置
    """
    try:
        waf = get_waf_engine()
        updates = {}
        if rule_name is not None:
            updates["name"] = rule_name
        if pattern is not None:
            updates["pattern"] = pattern
        if severity is not None:
            updates["severity"] = severity
        if action is not None:
            updates["action"] = action
        if description is not None:
            updates["description"] = description
        if is_active is not None:
            updates["is_active"] = is_active

        updated = waf.update_rule(rule_id, updates)
        if not updated:
            return make_error_response(f"规则不存在或无法修改: {rule_id}", code=404)

        return make_response(data=updated, message="规则更新成功")
    except Exception as e:
        return make_error_response(f"更新规则失败: {str(e)}")


@router.delete("/rules/{rule_id}", summary="删除规则")
def delete_rule(
    rule_id: int,
    current_user: dict = Depends(require_role(ROLE_ADMIN)),
):
    """
    删除指定的 WAF 规则（仅自定义规则可删除）
    """
    try:
        waf = get_waf_engine()
        success = waf.delete_rule(rule_id)
        if not success:
            return make_error_response(f"规则不存在或为内置规则，无法删除: {rule_id}", code=400)

        return make_response(data={"deleted": True}, message="规则删除成功")
    except Exception as e:
        return make_error_response(f"删除规则失败: {str(e)}")


# ===========================================================================
# WAF 检测
# ===========================================================================

@router.post("/check", summary="请求检测")
def waf_check(
    method: str = "GET",
    path: str = "/",
    query: str = "",
    body: str = "",
    client_ip: str = "127.0.0.1",
):
    """
    手动检测一个请求是否会被 WAF 拦截，用于规则测试
    """
    try:
        waf = get_waf_engine()
        result = waf.check_request(
            method=method,
            path=path,
            query=query,
            body=body,
            client_ip=client_ip,
        )
        return make_response(data=result)
    except Exception as e:
        return make_error_response(f"WAF检测失败: {str(e)}")


# ===========================================================================
# 网关 WAF 检测（M8 网关专用，高性能）
# ===========================================================================

@router.post("/gateway-check", summary="网关WAF检测（高性能）")
async def waf_gateway_check(request: GatewayWafCheckRequest):
    """
    网关专用 WAF 检测接口，高性能、精简响应格式。

    - 专为 M8 网关接入设计
    - 检测时间 < 1ms（正常请求）
    - 返回 blocked/reason/rule_id/risk_level
    """
    try:
        waf = get_waf_engine()
        result = waf.gateway_check(
            method=request.method,
            path=request.path,
            headers=request.headers,
            body=request.body,
            client_ip=request.client_ip,
            user_agent=request.user_agent,
        )
        return make_response(data=result)
    except Exception as e:
        return make_error_response(f"WAF网关检测失败: {str(e)}")


@router.post("/gateway-batch-check", summary="网关WAF批量检测")
async def waf_gateway_batch_check(request: GatewayWafBatchRequest):
    """
    批量 WAF 检测接口，一次提交多个请求进行检测。

    - 最多支持 100 个请求/批次
    - 返回每个请求的检测结果
    """
    try:
        waf = get_waf_engine()
        req_list = [
            {
                "method": r.method,
                "path": r.path,
                "headers": r.headers,
                "body": r.body,
                "client_ip": r.client_ip,
                "user_agent": r.user_agent,
            }
            for r in request.requests
        ]
        result = waf.gateway_batch_check(req_list)
        return make_response(data=result)
    except Exception as e:
        return make_error_response(f"WAF批量检测失败: {str(e)}")


@router.get("/performance", summary="WAF 性能统计")
async def waf_performance(current_user: dict = Depends(require_scope(SCOPE_WAF_READ))):
    """
    获取 WAF 引擎性能统计信息（需鉴权）
    """
    try:
        waf = get_waf_engine()
        perf = waf.get_performance_stats()
        return make_response(data=perf)
    except Exception as e:
        return make_error_response(f"获取性能统计失败: {str(e)}")


# ===========================================================================
# WAF 统计
# ===========================================================================

@router.get("/stats", summary="WAF 统计信息")
def waf_stats():
    """
    获取 WAF 防护统计信息
    """
    try:
        waf = get_waf_engine()
        status = waf.get_status()

        # 按类型统计命中
        rules = waf.get_rules()
        hits_by_type: dict = {}
        top_rules = sorted(rules, key=lambda r: r.get("hit_count", 0), reverse=True)[:10]

        for rule in rules:
            rtype = rule["type"]
            hits = rule.get("hit_count", 0)
            hits_by_type[rtype] = hits_by_type.get(rtype, 0) + hits

        return make_response(data={
            "total_rules": status["total_rules"],
            "active_rules": status["active_rules"],
            "total_blocks": status["total_blocks"],
            "today_blocks": status["today_blocks"],
            "blocks_by_type": hits_by_type,
            "top_rules": [
                {"id": r["id"], "name": r["name"], "type": r["type"], "hits": r.get("hit_count", 0)}
                for r in top_rules
            ],
        })
    except Exception as e:
        return make_error_response(f"获取WAF统计失败: {str(e)}")


# ===========================================================================
# WAF 拦截日志（增强版）
# ===========================================================================

@router.get("/logs", summary="WAF 拦截日志")
def waf_block_logs(
    rule_type: Optional[str] = Query(None, description="规则类型筛选"),
    severity: Optional[str] = Query(None, description="严重级别筛选"),
    client_ip: Optional[str] = Query(None, description="来源 IP 筛选"),
    page: int = Query(1, ge=1, description="页码"),
    page_size: int = Query(20, ge=1, le=100, description="每页数量"),
    current_user: dict = Depends(require_role(ROLE_VIEWER)),
):
    """
    获取 WAF 拦截日志列表（增强版）
    """
    try:
        from ..core.waf import get_waf_core
        waf_core = get_waf_core()
        logs = waf_core.get_block_logs(
            rule_type=rule_type,
            severity=severity,
            client_ip=client_ip,
            page=page,
            page_size=page_size,
        )
        return make_response(data=logs)
    except ImportError:
        return make_error_response("增强版 WAF 模块未启用", code=501)
    except Exception as e:
        return make_error_response(f"获取拦截日志失败: {str(e)}")


@router.get("/stats/enhanced", summary="增强版 WAF 统计")
def waf_stats_enhanced(
    current_user: dict = Depends(require_role(ROLE_VIEWER)),
):
    """
    获取增强版 WAF 统计信息（含 7 层防护分类统计）
    """
    try:
        from ..core.waf import get_waf_core
        waf_core = get_waf_core()
        stats = waf_core.get_stats()
        return make_response(data=stats)
    except ImportError:
        return make_error_response("增强版 WAF 模块未启用", code=501)
    except Exception as e:
        return make_error_response(f"获取增强统计失败: {str(e)}")


@router.put("/low-confidence-mode", summary="设置低误报模式")
def set_low_confidence_mode(
    enabled: bool = Query(..., description="是否启用低误报模式"),
    current_user: dict = Depends(require_role(ROLE_ADMIN)),
):
    """
    设置 WAF 低误报模式：
    - 启用：仅拦截 high/critical 级别攻击
    - 禁用：拦截所有级别攻击
    """
    try:
        from ..core.waf import get_waf_core
        waf_core = get_waf_core()
        waf_core.set_low_confidence_mode(enabled)
        return make_response(data={
            "low_confidence_mode": enabled,
            "message": f"低误报模式已{'启用' if enabled else '禁用'}",
        })
    except ImportError:
        return make_error_response("增强版 WAF 模块未启用", code=501)
    except Exception as e:
        return make_error_response(f"设置低误报模式失败: {str(e)}")
