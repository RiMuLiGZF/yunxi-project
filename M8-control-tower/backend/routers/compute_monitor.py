"""
算力调度中台 - 监控大盘路由
提供总览数据、算力源状态、调用日志、成本统计、延迟统计、告警管理、额度监控等接口

兼容第一部分表结构：
- ComputeCallLog: call_id(不是log_id), 没有purpose/total_tokens/failover_count等
- ComputeAlert: type/severity/message/details/resolved(不是level/title/content/status)
- ComputeQuota: limit_amount/used_amount(不是limit_value/used_value), 没有quota_id/limit_type/status
"""

import time
from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional
from fastapi import APIRouter, Depends, Query, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
from sqlalchemy import func

from ..schemas import ApiResponse
from ..auth import get_current_user, require_role
from ..models import (
    get_db, ComputeCallLog, ComputeAlert, ComputeQuota,
    ComputeSource,
)
from ..compute_router import get_compute_router

router = APIRouter()
compute_router = get_compute_router()


# ============================================================
# 工具函数
# ============================================================

def _call_log_to_dict(log: ComputeCallLog) -> Dict[str, Any]:
    """调用日志 ORM 转字典（适配第一部分表结构）"""
    total_tokens = (log.input_tokens or 0) + (log.output_tokens or 0)
    return {
        "log_id": log.call_id,  # 第一部分用 call_id
        "call_id": log.call_id,
        "model_key": log.model_key,
        "source_id": log.source_id,
        "caller_module": log.caller_module,
        "caller_skill": log.caller_skill or "",
        "input_tokens": log.input_tokens or 0,
        "output_tokens": log.output_tokens or 0,
        "total_tokens": total_tokens,
        "cost": log.cost or 0.0,
        "latency_ms": log.latency_ms or 0,
        "status": log.status,
        "error_code": getattr(log, 'error_code', ''),
        "error_message": log.error_message or "",
        "request_hash": getattr(log, 'request_hash', ''),
        "failover_count": 0,  # 第一部分没有
        "original_source_id": "",  # 第一部分没有
        "priority": "normal",  # 第一部分没有
        "privacy_level": "public",  # 第一部分没有
        "extra_data": {},  # 第一部分没有
        "created_at": log.created_at.timestamp() if log.created_at else None,
        "created_at_formatted": log.created_at.strftime("%Y-%m-%d %H:%M:%S") if log.created_at else "",
    }


def _alert_to_dict(alert: ComputeAlert) -> Dict[str, Any]:
    """算力告警 ORM 转字典（适配第一部分表结构）"""
    # 第一部分字段: alert_id, type, severity, source_id, message, details, resolved, resolved_at, created_at
    severity = getattr(alert, 'severity', 'info')
    alert_type = getattr(alert, 'type', 'health')
    details = getattr(alert, 'details', {}) or {}
    resolved = getattr(alert, 'resolved', False)
    
    return {
        "id": alert.id,
        "alert_id": alert.alert_id,
        "type": alert_type,
        "severity": severity,
        "level": severity,  # 兼容字段
        "title": alert.message or "",  # message 映射到 title
        "content": alert.message or "",
        "message": alert.message or "",
        "source_type": alert_type,
        "source_key": getattr(alert, 'source_id', ''),
        "source_id": getattr(alert, 'source_id', ''),
        "status": "resolved" if resolved else "active",
        "resolved": resolved,
        "details": details,
        "acknowledged_at": None,  # 第一部分没有
        "acknowledged_by": "",  # 第一部分没有
        "resolved_at": alert.resolved_at.timestamp() if getattr(alert, 'resolved_at', None) else None,
        "resolved_by": "system",  # 第一部分没有
        "created_at": alert.created_at.timestamp() if alert.created_at else None,
        "created_at_formatted": alert.created_at.strftime("%Y-%m-%d %H:%M:%S") if alert.created_at else "",
    }


def _quota_to_dict(quota: ComputeQuota) -> Dict[str, Any]:
    """额度 ORM 转字典（适配第一部分表结构）"""
    # 第一部分字段: scope, scope_key, period, limit_amount, used_amount, reset_at, alert_threshold(百分比), action_on_exceed
    limit_amount = getattr(quota, 'limit_amount', 0.0) or 0.0
    used_amount = getattr(quota, 'used_amount', 0.0) or 0.0
    alert_threshold_pct = getattr(quota, 'alert_threshold', 80.0) or 80.0
    
    usage_percent = 0.0
    if limit_amount > 0:
        usage_percent = round(used_amount / limit_amount * 100, 2)
    
    # 用 scope+scope_key+period 生成唯一 quota_id
    quota_id = f"{quota.scope}_{quota.scope_key}_{quota.period}"
    
    return {
        "quota_id": quota_id,
        "scope": quota.scope,
        "scope_key": quota.scope_key,
        "period": quota.period,
        "limit_type": "cost",  # 第一部分都是成本型
        "limit_value": limit_amount,
        "limit_amount": limit_amount,
        "used_value": round(used_amount, 6),
        "used_amount": round(used_amount, 6),
        "usage_percent": usage_percent,
        "remaining": round(max(0, limit_amount - used_amount), 6),
        "alert_threshold": alert_threshold_pct / 100.0,  # 转小数
        "alert_threshold_pct": alert_threshold_pct,
        "action_on_exceed": getattr(quota, 'action_on_exceed', 'alert_only'),
        "status": "active",  # 第一部分没有 status 字段
        "is_alerting": usage_percent >= alert_threshold_pct,
        "reset_at": quota.reset_at.timestamp() if getattr(quota, 'reset_at', None) else None,
        "last_reset_at": None,  # 第一部分没有
        "created_at": quota.created_at.timestamp() if getattr(quota, 'created_at', None) else None,
    }


# ============================================================
# 总览数据
# ============================================================

@router.get("/overview")
async def get_overview(
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """获取算力监控总览数据"""
    # 从路由引擎获取内存统计（快速）
    overall = compute_router.get_overall_stats()
    
    # 今日时间范围
    today_start = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
    
    # 从数据库补充统计
    try:
        # 今日调用次数
        today_calls = db.query(ComputeCallLog).filter(
            ComputeCallLog.created_at >= today_start
        ).count()
        
        # 今日成功次数
        today_success = db.query(ComputeCallLog).filter(
            ComputeCallLog.created_at >= today_start,
            ComputeCallLog.status == "success",
        ).count()
        
        # 今日总成本
        today_cost_result = db.query(
            func.sum(ComputeCallLog.cost)
        ).filter(
            ComputeCallLog.created_at >= today_start
        ).scalar()
        today_cost = float(today_cost_result or 0.0)
        
        # 成功率
        success_rate = today_success / today_calls if today_calls > 0 else 1.0
        
        # 平均延迟
        avg_latency_result = db.query(
            func.avg(ComputeCallLog.latency_ms)
        ).filter(
            ComputeCallLog.created_at >= today_start,
            ComputeCallLog.status == "success",
        ).scalar()
        avg_latency = float(avg_latency_result or 0.0)
        
        # 活跃告警数（未解决的）
        active_alerts = db.query(ComputeAlert).filter(
            ComputeAlert.resolved == False
        ).count()
        
        # 更新总览数据（优先使用数据库数据）
        overall["today"].update({
            "calls": today_calls,
            "success": today_success,
            "failed": today_calls - today_success,
            "success_rate": round(success_rate, 4),
            "avg_latency_ms": round(avg_latency, 2),
            "total_cost": round(today_cost, 6),
        })
        overall["active_alerts"] = active_alerts
    except Exception as e:
        # 表可能还不存在，使用内存数据
        overall["active_alerts"] = 0
    
    return ApiResponse.success(data=overall)


# ============================================================
# 算力源实时状态
# ============================================================

@router.get("/sources/status")
async def get_sources_status(
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """获取各算力源实时状态列表"""
    sources = compute_router.get_all_sources()
    call_stats = compute_router.get_call_stats()
    cb_stats = compute_router.get_all_circuit_breakers()
    
    result = []
    for source_id, source in sources.items():
        stats = call_stats.get(source_id, {})
        cb = cb_stats.get(source_id, {})
        
        today_calls = stats.get("today_calls", 0)
        today_success = stats.get("today_success", 0)
        success_rate = today_success / today_calls if today_calls > 0 else 1.0
        
        result.append({
            "source_id": source_id,
            "name": source["name"],
            "provider": source["provider"],
            "model_name": source["model_name"],
            "deployment_type": source["deployment_type"],
            "status": source["status"],
            "health_status": source["health_status"],
            "latency_ms": source["latency_ms"],
            "success_rate": round(success_rate, 4),
            "current_concurrent": source.get("current_concurrent", 0),
            "max_concurrent": source["max_concurrent"],
            "today_calls": today_calls,
            "today_cost": round(stats.get("today_cost", 0.0), 6),
            "circuit_breaker_state": cb.get("state", "unknown"),
            "circuit_breaker_error_rate": cb.get("error_rate", 0),
            "weight": source["weight"],
            "priority": source["priority"],
            "region": source.get("region", ""),
        })
    
    # 按优先级排序（priority 越小越优先）
    result.sort(key=lambda x: x["priority"])
    
    return ApiResponse.success(
        data={
            "total": len(result),
            "items": result,
        }
    )


# ============================================================
# 调用日志
# ============================================================

@router.get("/call-logs")
async def get_call_logs(
    source_id: Optional[str] = Query(None, description="按算力源筛选"),
    model_key: Optional[str] = Query(None, description="按模型筛选"),
    module: Optional[str] = Query(None, description="按模块筛选"),
    status: Optional[str] = Query(None, description="按状态筛选"),
    start_time: Optional[str] = Query(None, description="开始时间 YYYY-MM-DD HH:MM:SS"),
    end_time: Optional[str] = Query(None, description="结束时间 YYYY-MM-DD HH:MM:SS"),
    page: int = Query(1, description="页码", ge=1),
    page_size: int = Query(50, description="每页条数", ge=1, le=500),
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """获取调用日志列表（分页+筛选）"""
    try:
        query = db.query(ComputeCallLog)
        
        # 筛选条件
        if source_id:
            query = query.filter(ComputeCallLog.source_id == source_id)
        if model_key:
            query = query.filter(ComputeCallLog.model_key == model_key)
        if module:
            query = query.filter(ComputeCallLog.caller_module == module)
        if status:
            query = query.filter(ComputeCallLog.status == status)
        if start_time:
            try:
                start_dt = datetime.strptime(start_time, "%Y-%m-%d %H:%M:%S")
                query = query.filter(ComputeCallLog.created_at >= start_dt)
            except ValueError:
                pass
        if end_time:
            try:
                end_dt = datetime.strptime(end_time, "%Y-%m-%d %H:%M:%S")
                query = query.filter(ComputeCallLog.created_at <= end_dt)
            except ValueError:
                pass
        
        # 总数
        total = query.count()
        
        # 分页
        offset = (page - 1) * page_size
        logs = (
            query.order_by(ComputeCallLog.created_at.desc())
            .offset(offset)
            .limit(page_size)
            .all()
        )
        
        return ApiResponse.success(
            data={
                "total": total,
                "page": page,
                "page_size": page_size,
                "items": [_call_log_to_dict(log) for log in logs],
            }
        )
    except Exception as e:
        # 表可能不存在，返回空
        return ApiResponse.success(
            data={
                "total": 0,
                "page": page,
                "page_size": page_size,
                "items": [],
            }
        )


# ============================================================
# 成本统计
# ============================================================

@router.get("/cost/stats")
async def get_cost_stats(
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """获取成本统计数据"""
    today_start = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
    week_start = today_start - timedelta(days=today_start.weekday())
    month_start = today_start.replace(day=1)
    
    result = {
        "today": 0.0,
        "week": 0.0,
        "month": 0.0,
        "by_source": {},
        "by_module": {},
        "by_model": {},
    }
    
    try:
        # 今日成本
        today_cost = db.query(func.sum(ComputeCallLog.cost)).filter(
            ComputeCallLog.created_at >= today_start
        ).scalar()
        result["today"] = round(float(today_cost or 0.0), 6)
        
        # 本周成本
        week_cost = db.query(func.sum(ComputeCallLog.cost)).filter(
            ComputeCallLog.created_at >= week_start
        ).scalar()
        result["week"] = round(float(week_cost or 0.0), 6)
        
        # 本月成本
        month_cost = db.query(func.sum(ComputeCallLog.cost)).filter(
            ComputeCallLog.created_at >= month_start
        ).scalar()
        result["month"] = round(float(month_cost or 0.0), 6)
        
        # 按算力源分布（今日）
        source_costs = db.query(
            ComputeCallLog.source_id,
            func.sum(ComputeCallLog.cost).label("total_cost")
        ).filter(
            ComputeCallLog.created_at >= today_start
        ).group_by(ComputeCallLog.source_id).all()
        
        for src_id, cost in source_costs:
            result["by_source"][src_id] = round(float(cost or 0.0), 6)
        
        # 按模块分布（今日）
        module_costs = db.query(
            ComputeCallLog.caller_module,
            func.sum(ComputeCallLog.cost).label("total_cost")
        ).filter(
            ComputeCallLog.created_at >= today_start
        ).group_by(ComputeCallLog.caller_module).all()
        
        for mod, cost in module_costs:
            result["by_module"][mod] = round(float(cost or 0.0), 6)
        
        # 按模型分布（今日）
        model_costs = db.query(
            ComputeCallLog.model_key,
            func.sum(ComputeCallLog.cost).label("total_cost")
        ).filter(
            ComputeCallLog.created_at >= today_start
        ).group_by(ComputeCallLog.model_key).all()
        
        for m_key, cost in model_costs:
            result["by_model"][m_key] = round(float(cost or 0.0), 6)
        
    except Exception as e:
        pass
    
    return ApiResponse.success(data=result)


# ============================================================
# 延迟统计
# ============================================================

@router.get("/latency/stats")
async def get_latency_stats(
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """获取延迟统计（各算力源的 P50/P95/P99 延迟）"""
    result = {}
    today_start = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
    
    try:
        # 获取所有算力源
        sources = compute_router.get_all_sources()
        
        for source_id, source in sources.items():
            # 查询今日成功调用的延迟数据
            logs = db.query(ComputeCallLog.latency_ms).filter(
                ComputeCallLog.source_id == source_id,
                ComputeCallLog.created_at >= today_start,
                ComputeCallLog.status == "success",
                ComputeCallLog.latency_ms > 0,
            ).order_by(ComputeCallLog.latency_ms).all()
            
            latencies = [log[0] for log in logs if log[0] > 0]
            
            if not latencies:
                result[source_id] = {
                    "name": source["name"],
                    "p50": 0,
                    "p95": 0,
                    "p99": 0,
                    "avg": 0,
                    "min": 0,
                    "max": 0,
                    "count": 0,
                }
                continue
            
            n = len(latencies)
            
            def percentile(data, p):
                """计算百分位数"""
                k = (len(data) - 1) * p
                f = int(k)
                c = f + 1
                if c >= len(data):
                    return data[-1]
                return data[f] + (data[c] - data[f]) * (k - f)
            
            result[source_id] = {
                "name": source["name"],
                "p50": round(percentile(latencies, 0.5), 2),
                "p95": round(percentile(latencies, 0.95), 2),
                "p99": round(percentile(latencies, 0.99), 2),
                "avg": round(sum(latencies) / n, 2),
                "min": round(latencies[0], 2),
                "max": round(latencies[-1], 2),
                "count": n,
            }
    
    except Exception as e:
        # 表不存在或其他错误
        sources = compute_router.get_all_sources()
        for source_id, source in sources.items():
            result[source_id] = {
                "name": source["name"],
                "p50": source["latency_ms"],
                "p95": source["latency_ms"] * 1.5,
                "p99": source["latency_ms"] * 2,
                "avg": source["latency_ms"],
                "min": 0,
                "max": 0,
                "count": 0,
            }
    
    return ApiResponse.success(data=result)


# ============================================================
# 告警管理
# ============================================================

@router.get("/alerts")
async def get_alerts(
    status: Optional[str] = Query(None, description="告警状态: active/resolved"),
    severity: Optional[str] = Query(None, description="告警级别: info/warning/critical"),
    alert_type: Optional[str] = Query(None, description="告警类型"),
    limit: int = Query(100, description="返回条数"),
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """获取算力告警列表"""
    try:
        query = db.query(ComputeAlert)
        
        if status:
            if status == "active":
                query = query.filter(ComputeAlert.resolved == False)
            elif status == "resolved":
                query = query.filter(ComputeAlert.resolved == True)
        
        if severity:
            query = query.filter(ComputeAlert.severity == severity)
        
        if alert_type:
            query = query.filter(ComputeAlert.type == alert_type)
        
        alerts = query.order_by(ComputeAlert.created_at.desc()).limit(limit).all()
        total = query.count()
        
        # 统计活跃告警数
        active_count = db.query(ComputeAlert).filter(
            ComputeAlert.resolved == False
        ).count()
        
        return ApiResponse.success(
            data={
                "total": total,
                "active_count": active_count,
                "items": [_alert_to_dict(a) for a in alerts],
            }
        )
    except Exception as e:
        return ApiResponse.success(
            data={
                "total": 0,
                "active_count": 0,
                "items": [],
            }
        )


@router.post("/alerts/{alert_id}/resolve")
@require_role("admin")
async def resolve_alert(
    alert_id: int,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """标记告警已解决"""
    try:
        alert = db.query(ComputeAlert).filter(ComputeAlert.id == alert_id).first()
        if not alert:
            return ApiResponse.error(code=404, message="告警不存在")
        
        if alert.resolved:
            return ApiResponse.error(code=400, message="告警已解决")
        
        alert.resolved = True
        alert.resolved_at = datetime.utcnow()
        db.commit()
        db.refresh(alert)
        
        return ApiResponse.success(data=_alert_to_dict(alert), message="告警已解决")
    except Exception as e:
        return ApiResponse.error(code=500, message=f"操作失败: {str(e)}")


# ============================================================
# 额度管理
# ============================================================

@router.get("/quotas")
async def get_quotas(
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """获取额度使用情况"""
    try:
        quotas = db.query(ComputeQuota).order_by(ComputeQuota.scope, ComputeQuota.period).all()
        
        # 同步内存中的使用量到结果
        mem_quotas = compute_router.get_all_quotas()
        
        result = []
        for quota in quotas:
            q_dict = _quota_to_dict(quota)
            # 如果内存中有更新的使用量，使用内存数据
            qid = q_dict["quota_id"]
            mem_quota = mem_quotas.get(qid)
            if mem_quota and mem_quota.get("used_value", 0) > q_dict["used_value"]:
                q_dict["used_value"] = round(mem_quota["used_value"], 6)
                q_dict["used_amount"] = round(mem_quota["used_value"], 6)
                if q_dict["limit_value"] > 0:
                    q_dict["usage_percent"] = round(
                        q_dict["used_value"] / q_dict["limit_value"] * 100, 2
                    )
                    q_dict["remaining"] = round(
                        max(0, q_dict["limit_value"] - q_dict["used_value"]), 6
                    )
                    q_dict["is_alerting"] = (
                        q_dict["usage_percent"] >= q_dict["alert_threshold_pct"]
                    )
            result.append(q_dict)
        
        # 告警统计
        alerting_count = sum(1 for q in result if q["is_alerting"])
        
        return ApiResponse.success(
            data={
                "total": len(result),
                "alerting_count": alerting_count,
                "items": result,
            }
        )
    except Exception as e:
        # 表不存在时使用内存数据
        mem_quotas = compute_router.get_all_quotas()
        items = []
        for qid, q in mem_quotas.items():
            limit_val = q.get("limit_value", 0)
            used_val = q.get("used_value", 0)
            usage_percent = 0.0
            if limit_val > 0:
                usage_percent = round(used_val / limit_val * 100, 2)
            alert_threshold = q.get("alert_threshold", 0.8)
            items.append({
                "quota_id": qid,
                "scope": q.get("scope", ""),
                "scope_key": q.get("scope_key", ""),
                "period": q.get("period", ""),
                "limit_type": q.get("limit_type", "cost"),
                "limit_value": limit_val,
                "used_value": round(used_val, 6),
                "usage_percent": usage_percent,
                "remaining": round(max(0, limit_val - used_val), 6),
                "alert_threshold": alert_threshold,
                "status": q.get("status", "active"),
                "is_alerting": usage_percent >= alert_threshold * 100,
            })
        
        alerting_count = sum(1 for q in items if q["is_alerting"])
        return ApiResponse.success(
            data={
                "total": len(items),
                "alerting_count": alerting_count,
                "items": items,
            }
        )


@router.post("/quotas/reset")
@require_role("admin")
async def reset_quotas(
    quota_id: Optional[str] = Query(None, description="指定额度ID，不传则重置所有"),
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """手动重置额度"""
    try:
        now = datetime.utcnow()
        
        if quota_id:
            # 从 quota_id 解析 scope/scope_key/period
            parts = quota_id.split("_", 2)
            if len(parts) == 3:
                scope, scope_key, period = parts
                quota = db.query(ComputeQuota).filter(
                    ComputeQuota.scope == scope,
                    ComputeQuota.scope_key == scope_key,
                    ComputeQuota.period == period,
                ).first()
                if quota:
                    quota.used_amount = 0.0
                    db.commit()
            else:
                return ApiResponse.error(code=404, message=f"额度 {quota_id} 不存在")
            
            # 重置内存中的额度
            compute_router.reset_quota(quota_id)
        else:
            # 重置所有额度
            db.query(ComputeQuota).update({
                ComputeQuota.used_amount: 0.0,
            })
            db.commit()
            
            # 重置内存中的所有额度
            mem_quotas = compute_router.get_all_quotas()
            for qid in mem_quotas:
                compute_router.reset_quota(qid)
        
        return ApiResponse.success(message="额度已重置")
    except Exception as e:
        # 数据库操作失败，尝试只重置内存
        if quota_id:
            compute_router.reset_quota(quota_id)
        else:
            mem_quotas = compute_router.get_all_quotas()
            for qid in mem_quotas:
                compute_router.reset_quota(qid)
        return ApiResponse.success(message="内存额度已重置（数据库操作跳过）")
