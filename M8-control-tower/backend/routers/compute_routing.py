"""
算力调度中台 - 路由调度路由
提供路由策略管理、手动路由决策、故障转移测试、熔断器管理、限流管理等接口

兼容第一部分表结构：
- ComputeRoutingPolicy: mode(不是is_active), default_strategy, config(存额外配置),
  vram_*, network_latency_threshold, offline_fallback_enabled(不是offline_degradation)
"""

import time
import uuid
from datetime import datetime
from typing import List, Dict, Any, Optional
from fastapi import APIRouter, Depends, Query, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ..schemas import ApiResponse
from ..auth import get_current_user, require_role
from ..models import get_db, ComputeRoutingPolicy, ComputeCallLog
from ..compute_router import get_compute_router, RouteStatus

router = APIRouter()
compute_router = get_compute_router()


# ============================================================
# 请求体模型
# ============================================================

class PolicyCreate(BaseModel):
    """新增策略请求体"""
    policy_id: str = Field(..., description="策略ID")
    name: str = Field(..., description="策略名称")
    mode: str = Field("auto", description="模式：manual/auto")
    default_strategy: str = Field("latency_first", description="默认策略")
    latency_weight: float = Field(0.4, description="延迟权重")
    cost_weight: float = Field(0.3, description="成本权重")
    quality_weight: float = Field(0.2, description="质量权重")
    privacy_weight: float = Field(0.1, description="隐私权重")
    circuit_breaker_enabled: bool = Field(True, description="是否启用熔断")
    cb_error_threshold: float = Field(0.5, description="熔断错误率阈值")
    cb_window_seconds: int = Field(60, description="熔断统计窗口")
    cb_cooldown_seconds: int = Field(30, description="熔断冷却时间")
    cb_half_open_probes: int = Field(3, description="半开探测次数")
    rate_limit_enabled: bool = Field(True, description="是否启用限流")
    global_rate_per_minute: int = Field(1000, description="全局每分钟请求限制")
    auto_failover: bool = Field(True, description="是否自动故障转移")
    max_failover_attempts: int = Field(3, description="最大故障转移次数")
    offline_fallback_enabled: bool = Field(True, description="是否启用离线降级")
    vram_safe_threshold: float = Field(70.0, description="显存安全阈值")
    vram_critical_threshold: float = Field(90.0, description="显存危险阈值")
    network_latency_threshold: int = Field(500, description="网络延迟阈值ms")


class PolicyUpdate(BaseModel):
    """更新策略请求体"""
    name: Optional[str] = None
    mode: Optional[str] = None
    default_strategy: Optional[str] = None
    latency_weight: Optional[float] = None
    cost_weight: Optional[float] = None
    quality_weight: Optional[float] = None
    privacy_weight: Optional[float] = None
    circuit_breaker_enabled: Optional[bool] = None
    cb_error_threshold: Optional[float] = None
    cb_window_seconds: Optional[int] = None
    cb_cooldown_seconds: Optional[int] = None
    cb_half_open_probes: Optional[int] = None
    rate_limit_enabled: Optional[bool] = None
    global_rate_per_minute: Optional[int] = None
    auto_failover: Optional[bool] = None
    max_failover_attempts: Optional[int] = None
    offline_fallback_enabled: Optional[bool] = None
    vram_safe_threshold: Optional[float] = None
    vram_critical_threshold: Optional[float] = None
    network_latency_threshold: Optional[int] = None


class RouteRequest(BaseModel):
    """手动路由请求体"""
    model_key: str = Field("default-chat", description="模型 key")
    purpose: str = Field("chat", description="用途")
    caller_module: str = Field("m8", description="调用模块")
    caller_skill: Optional[str] = Field(None, description="调用技能")
    input_tokens: int = Field(0, description="输入 token 数")
    priority: str = Field("normal", description="优先级")
    privacy_level: str = Field("public", description="隐私等级")
    prefer_local: bool = Field(False, description="是否偏好本地")


class FailoverTestRequest(BaseModel):
    """故障转移测试请求体"""
    failed_source_id: str = Field(..., description="失败的算力源ID")
    model_key: str = Field("default-chat", description="模型 key")
    reason: str = Field("test_failover", description="失败原因")


# ============================================================
# 工具函数
# ============================================================

def _policy_to_dict(policy: ComputeRoutingPolicy) -> Dict[str, Any]:
    """策略 ORM 转字典（适配第一部分表结构）"""
    config = getattr(policy, 'config', {}) or {}
    
    # 从 config 中提取熔断/限流等额外配置
    cb_error_threshold = config.get('cb_error_threshold', 0.5)
    cb_window_seconds = config.get('cb_window_seconds', 60)
    cb_cooldown_seconds = config.get('cb_cooldown_seconds', 30)
    cb_half_open_probes = config.get('cb_half_open_probes', 3)
    global_rate_per_minute = config.get('global_rate_per_minute', 1000)
    max_failover_attempts = config.get('max_failover_attempts', 3)
    
    # mode 字段表示策略模式，auto 表示激活可用
    is_active = getattr(policy, 'mode', 'auto') == 'auto'
    
    return {
        "policy_id": policy.policy_id,
        "name": policy.name,
        "mode": getattr(policy, 'mode', 'auto'),
        "default_strategy": getattr(policy, 'default_strategy', 'latency_first'),
        "is_active": is_active,
        "latency_weight": policy.latency_weight,
        "cost_weight": policy.cost_weight,
        "quality_weight": policy.quality_weight,
        "privacy_weight": policy.privacy_weight,
        "circuit_breaker_enabled": policy.circuit_breaker_enabled,
        "cb_error_threshold": cb_error_threshold,
        "cb_window_seconds": cb_window_seconds,
        "cb_cooldown_seconds": cb_cooldown_seconds,
        "cb_half_open_probes": cb_half_open_probes,
        "rate_limit_enabled": policy.rate_limit_enabled,
        "global_rate_per_minute": global_rate_per_minute,
        "auto_failover": policy.auto_failover,
        "max_failover_attempts": max_failover_attempts,
        "offline_degradation": policy.offline_fallback_enabled,
        "offline_fallback_enabled": policy.offline_fallback_enabled,
        "vram_safe_threshold": getattr(policy, 'vram_safe_threshold', 70.0),
        "vram_critical_threshold": getattr(policy, 'vram_critical_threshold', 90.0),
        "network_latency_threshold": getattr(policy, 'network_latency_threshold', 500),
        "extra_config": config,
        "created_at": policy.created_at.timestamp() if policy.created_at else None,
        "updated_at": policy.updated_at.timestamp() if policy.updated_at else None,
    }


def _update_policy_config(policy: ComputeRoutingPolicy, update_data: Dict[str, Any]):
    """更新策略的 config 字段（处理第一部分没有的字段）"""
    config = getattr(policy, 'config', {}) or {}
    config_changed = False
    
    # 需要存入 config 的字段
    config_fields = [
        'cb_error_threshold', 'cb_window_seconds', 'cb_cooldown_seconds',
        'cb_half_open_probes', 'global_rate_per_minute', 'max_failover_attempts',
    ]
    
    for field in config_fields:
        if field in update_data and update_data[field] is not None:
            config[field] = update_data[field]
            config_changed = True
    
    if config_changed:
        policy.config = config
    
    return config_changed


# ============================================================
# 路由策略 CRUD
# ============================================================

@router.get("/policies")
async def list_policies(
    status: Optional[str] = Query(None, description="按状态筛选"),
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """获取路由策略列表"""
    query = db.query(ComputeRoutingPolicy)
    
    if status and status == "active":
        query = query.filter(ComputeRoutingPolicy.mode == "auto")
    
    policies = query.order_by(ComputeRoutingPolicy.created_at.desc()).all()
    
    return ApiResponse.success(
        data={
            "total": len(policies),
            "items": [_policy_to_dict(p) for p in policies],
        }
    )


@router.get("/policies/{policy_id}")
async def get_policy(
    policy_id: str,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """获取策略详情"""
    policy = db.query(ComputeRoutingPolicy).filter(
        ComputeRoutingPolicy.policy_id == policy_id
    ).first()
    
    if not policy:
        return ApiResponse.error(code=404, message=f"策略 {policy_id} 不存在")
    
    return ApiResponse.success(data=_policy_to_dict(policy))


@router.post("/policies")
@require_role("admin")
async def create_policy(
    policy_data: PolicyCreate,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """新增路由策略"""
    # 检查是否已存在
    existing = db.query(ComputeRoutingPolicy).filter(
        ComputeRoutingPolicy.policy_id == policy_data.policy_id
    ).first()
    if existing:
        return ApiResponse.error(code=400, message=f"策略ID {policy_data.policy_id} 已存在")
    
    now = datetime.utcnow()
    
    # 构建 config 字段（存放第一部分表没有的字段）
    config = {
        "cb_error_threshold": policy_data.cb_error_threshold,
        "cb_window_seconds": policy_data.cb_window_seconds,
        "cb_cooldown_seconds": policy_data.cb_cooldown_seconds,
        "cb_half_open_probes": policy_data.cb_half_open_probes,
        "global_rate_per_minute": policy_data.global_rate_per_minute,
        "max_failover_attempts": policy_data.max_failover_attempts,
    }
    
    policy = ComputeRoutingPolicy(
        policy_id=policy_data.policy_id,
        name=policy_data.name,
        mode=policy_data.mode,
        default_strategy=policy_data.default_strategy,
        latency_weight=policy_data.latency_weight,
        cost_weight=policy_data.cost_weight,
        quality_weight=policy_data.quality_weight,
        privacy_weight=policy_data.privacy_weight,
        circuit_breaker_enabled=policy_data.circuit_breaker_enabled,
        rate_limit_enabled=policy_data.rate_limit_enabled,
        auto_failover=policy_data.auto_failover,
        offline_fallback_enabled=policy_data.offline_fallback_enabled,
        vram_safe_threshold=policy_data.vram_safe_threshold,
        vram_critical_threshold=policy_data.vram_critical_threshold,
        network_latency_threshold=policy_data.network_latency_threshold,
        config=config,
        created_at=now,
        updated_at=now,
    )
    db.add(policy)
    db.commit()
    db.refresh(policy)
    
    # 重新加载路由引擎配置
    compute_router.reload_config()
    
    return ApiResponse.success(data=_policy_to_dict(policy), message="策略创建成功")


@router.put("/policies/{policy_id}")
@require_role("admin")
async def update_policy(
    policy_id: str,
    policy_data: PolicyUpdate,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """更新路由策略"""
    policy = db.query(ComputeRoutingPolicy).filter(
        ComputeRoutingPolicy.policy_id == policy_id
    ).first()
    
    if not policy:
        return ApiResponse.error(code=404, message=f"策略 {policy_id} 不存在")
    
    # 更新字段
    update_data = policy_data.dict(exclude_unset=True)
    
    # 直接更新表中存在的字段
    direct_fields = [
        'name', 'mode', 'default_strategy',
        'latency_weight', 'cost_weight', 'quality_weight', 'privacy_weight',
        'circuit_breaker_enabled', 'rate_limit_enabled',
        'auto_failover', 'offline_fallback_enabled',
        'vram_safe_threshold', 'vram_critical_threshold', 'network_latency_threshold',
    ]
    
    for key in direct_fields:
        if key in update_data and update_data[key] is not None:
            setattr(policy, key, update_data[key])
    
    # 更新 config 字段中的内容
    _update_policy_config(policy, update_data)
    
    policy.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(policy)
    
    # 重新加载配置
    compute_router.reload_config()
    
    return ApiResponse.success(data=_policy_to_dict(policy), message="策略更新成功")


@router.delete("/policies/{policy_id}")
@require_role("admin")
async def delete_policy(
    policy_id: str,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """删除路由策略"""
    policy = db.query(ComputeRoutingPolicy).filter(
        ComputeRoutingPolicy.policy_id == policy_id
    ).first()
    
    if not policy:
        return ApiResponse.error(code=404, message=f"策略 {policy_id} 不存在")
    
    if policy.mode == "auto":
        # 检查是否还有其他 auto 模式的策略
        other_active = db.query(ComputeRoutingPolicy).filter(
            ComputeRoutingPolicy.policy_id != policy_id,
            ComputeRoutingPolicy.mode == "auto",
        ).count()
        if other_active == 0:
            return ApiResponse.error(code=400, message="最后一个激活策略不能删除，请先激活其他策略")
    
    db.delete(policy)
    db.commit()
    
    # 重新加载配置
    compute_router.reload_config()
    
    return ApiResponse.success(message="策略删除成功")


@router.post("/policies/{policy_id}/activate")
@require_role("admin")
async def activate_policy(
    policy_id: str,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """激活指定策略（其他策略自动设为 manual 模式）"""
    policy = db.query(ComputeRoutingPolicy).filter(
        ComputeRoutingPolicy.policy_id == policy_id
    ).first()
    
    if not policy:
        return ApiResponse.error(code=404, message=f"策略 {policy_id} 不存在")
    
    # 将所有其他策略设为 manual 模式
    db.query(ComputeRoutingPolicy).filter(
        ComputeRoutingPolicy.policy_id != policy_id
    ).update({ComputeRoutingPolicy.mode: "manual"})
    
    # 激活目标策略（设为 auto 模式）
    policy.mode = "auto"
    policy.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(policy)
    
    # 重新加载配置
    compute_router.reload_config()
    
    return ApiResponse.success(data=_policy_to_dict(policy), message="策略已激活")


# ============================================================
# 路由决策与故障转移
# ============================================================

@router.post("/route")
async def manual_route(
    request: RouteRequest,
    current_user: dict = Depends(get_current_user),
):
    """手动路由决策（测试用）"""
    result = await compute_router.route(
        model_key=request.model_key,
        purpose=request.purpose,
        caller_module=request.caller_module,
        caller_skill=request.caller_skill,
        input_tokens=request.input_tokens,
        priority=request.priority,
        privacy_level=request.privacy_level,
        prefer_local=request.prefer_local,
    )
    
    result_dict = {
        "status": result.status.value,
        "source_id": result.source_id,
        "source_name": result.source_name,
        "model_key": result.model_key,
        "score": result.score,
        "latency_ms": result.latency_ms,
        "cost_estimate": result.cost_estimate,
        "quality_score": result.quality_score,
        "failover_list": result.failover_list,
        "reason": result.reason,
        "route_id": result.route_id,
        "policy_id": result.policy_id,
        "created_at": result.created_at,
    }
    
    return ApiResponse.success(data=result_dict)


@router.post("/failover/test")
@require_role("admin")
async def test_failover(
    request: FailoverTestRequest,
    current_user: dict = Depends(get_current_user),
):
    """测试故障转移"""
    result = await compute_router.failover(
        failed_source_id=request.failed_source_id,
        model_key=request.model_key,
        reason=request.reason,
    )
    
    if result is None:
        return ApiResponse.error(code=503, message="故障转移失败，无可用备选算力源")
    
    result_dict = {
        "status": result.status.value,
        "source_id": result.source_id,
        "source_name": result.source_name,
        "model_key": result.model_key,
        "score": result.score,
        "latency_ms": result.latency_ms,
        "cost_estimate": result.cost_estimate,
        "failover_list": result.failover_list,
        "reason": result.reason,
        "route_id": result.route_id,
        "policy_id": result.policy_id,
    }
    
    return ApiResponse.success(data=result_dict, message="故障转移测试成功")


# ============================================================
# 熔断器管理
# ============================================================

@router.get("/circuit-breakers")
async def list_circuit_breakers(
    current_user: dict = Depends(get_current_user),
):
    """获取所有熔断器状态"""
    cb_stats = compute_router.get_all_circuit_breakers()
    
    # 补充算力源名称
    sources = compute_router.get_all_sources()
    for sid, stats in cb_stats.items():
        stats["source_name"] = sources.get(sid, {}).get("name", sid)
    
    return ApiResponse.success(
        data={
            "total": len(cb_stats),
            "items": list(cb_stats.values()),
        }
    )


@router.post("/circuit-breakers/{source_id}/reset")
@require_role("admin")
async def reset_circuit_breaker(
    source_id: str,
    current_user: dict = Depends(get_current_user),
):
    """重置指定算力源的熔断器"""
    success = compute_router.reset_circuit_breaker(source_id)
    if not success:
        return ApiResponse.error(code=404, message=f"算力源 {source_id} 不存在")
    
    cb = compute_router.get_circuit_breaker(source_id)
    return ApiResponse.success(
        data=cb.get_stats() if cb else {},
        message="熔断器已重置",
    )


# ============================================================
# 限流管理
# ============================================================

@router.get("/rate-limits")
async def get_rate_limits(
    current_user: dict = Depends(get_current_user),
):
    """获取限流状态"""
    rate_limits = compute_router.get_rate_limits()
    return ApiResponse.success(data=rate_limits)


@router.post("/rate-limits/{scope}/reset")
@require_role("admin")
async def reset_rate_limit(
    scope: str,
    key: Optional[str] = Query("", description="范围对应的 key"),
    current_user: dict = Depends(get_current_user),
):
    """重置限流计数"""
    valid_scopes = ["global", "source", "module", "skill"]
    if scope not in valid_scopes:
        return ApiResponse.error(code=400, message=f"无效的 scope，必须是: {', '.join(valid_scopes)}")
    
    success = compute_router.reset_rate_limit(scope, key)
    if not success:
        return ApiResponse.error(code=404, message=f"限流配置 {scope}/{key} 不存在")
    
    return ApiResponse.success(message=f"{scope} 限流已重置")
