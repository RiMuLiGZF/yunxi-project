"""
算力调度中台 - 配置管理路由
提供配置导出、导入、验证、备份管理等接口

兼容第一部分表结构：
- ComputeSource: type(不是deployment_type), api_key_encrypted(不是api_key),
  models(不是model_name), latency_avg(不是latency_ms),
  config(JSON存额外配置), capabilities, health_last_check
- ComputeKeyGroup: routing_strategy(不是load_balance_strategy), default_source, 没有status
- ComputeModelBinding: group_id(不是key_group_id), fallback_model_key(不是fallback_group_id),
  max_tokens(不是max_input_tokens), 没有status/default_policy_id
- ComputeRoutingPolicy: mode(不是is_active), default_strategy, config(JSON),
  vram_*, network_latency_threshold, offline_fallback_enabled
- ComputeSkillBinding: allowed_sources(不是allowed_source_ids), quota_daily/monthly,
  rate_limit_per_min, priority, 没有description/denied_source_ids/status
- ComputeQuota: scope/scope_key/period, limit_amount/used_amount, alert_threshold(百分比),
  action_on_exceed, 没有quota_id/limit_type/status
"""

import json
import uuid
import time
from datetime import datetime
from typing import List, Dict, Any, Optional
from fastapi import APIRouter, Depends, Query, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ..schemas import ApiResponse
from ..auth import get_current_user, require_role
from ..models import (
    get_db,
    ComputeSource, ComputeKeyGroup, ComputeModelBinding,
    ComputeRoutingPolicy, ComputeSkillBinding, ComputeQuota,
    ComputeConfigBackup,
)
from ..compute_router import get_compute_router

router = APIRouter()
compute_router = get_compute_router()


# ============================================================
# 请求体模型
# ============================================================

class ImportConfigRequest(BaseModel):
    """导入配置请求体"""
    config_data: Dict[str, Any] = Field(..., description="配置数据（JSON）")
    mode: str = Field("merge", description="导入模式: overwrite(全量覆盖) / merge(增量合并)")
    validate_only: bool = Field(False, description="仅验证不导入")


class ValidateConfigRequest(BaseModel):
    """验证配置请求体"""
    config_data: Dict[str, Any] = Field(..., description="配置数据（JSON）")


class CreateBackupRequest(BaseModel):
    """创建备份请求体"""
    name: str = Field("", description="备份名称")
    description: str = Field("", description="备份描述")


# ============================================================
# 工具函数
# ============================================================

def _mask_api_key(api_key: str) -> str:
    """掩码 API Key，只保留前后各 4 位"""
    if not api_key:
        return ""
    if len(api_key) <= 8:
        return "*" * len(api_key)
    return api_key[:4] + "*" * (len(api_key) - 8) + api_key[-4:]


def _collect_config_data(db: Session, mask_keys: bool = True) -> Dict[str, Any]:
    """收集全部配置数据（适配第一部分表结构）"""
    
    # 算力源
    sources = []
    for s in db.query(ComputeSource).all():
        config = getattr(s, 'config', {}) or {}
        models = getattr(s, 'models', []) or []
        capabilities = getattr(s, 'capabilities', []) or []
        
        # 从 config 中提取额外配置
        quality_score = config.get('quality_score', 0.8)
        privacy_level = config.get('privacy_level', 'public')
        rate_limit_per_minute = config.get('rate_limit_per_minute', 0)
        rate_limit_per_day = config.get('rate_limit_per_day', 0)
        auto_failover = config.get('auto_failover', True)
        region = config.get('region', '')
        
        # type 映射
        deployment_type = getattr(s, 'type', 'cloud')
        if deployment_type == 'local':
            privacy_level = 'top_secret'
        elif deployment_type == 'private':
            privacy_level = 'confidential'
        
        # API Key 处理
        api_key_encrypted = getattr(s, 'api_key_encrypted', '')
        api_key_masked = getattr(s, 'api_key_masked', '')
        if mask_keys:
            api_key = api_key_masked or _mask_api_key(api_key_encrypted)
        else:
            api_key = api_key_encrypted  # 导出加密后的 key
        
        source_dict = {
            "source_id": s.source_id,
            "name": s.name,
            "provider": s.provider,
            "base_url": s.base_url,
            "api_key": api_key,
            "api_key_encrypted": api_key_encrypted,
            "api_key_masked": api_key_masked,
            "model_name": models[0] if models else "",
            "models": models,
            "deployment_type": deployment_type,
            "type": deployment_type,  # 兼容字段
            "priority": s.priority,
            "weight": s.weight,
            "status": s.status,
            "health_status": s.health_status,
            "latency_ms": getattr(s, 'latency_avg', 0.0),
            "latency_avg": getattr(s, 'latency_avg', 0.0),
            "success_rate": s.success_rate,
            "max_concurrent": s.max_concurrent,
            "timeout": getattr(s, 'timeout', 60),
            "cost_per_1k_input": s.cost_per_1k_input,
            "cost_per_1k_output": s.cost_per_1k_output,
            "quality_score": quality_score,
            "privacy_level": privacy_level,
            "capabilities": capabilities,
            "region": region,
            "rate_limit_per_minute": rate_limit_per_minute,
            "rate_limit_per_day": rate_limit_per_day,
            "auto_failover": auto_failover,
            "extra_config": config,
            "health_last_check": s.health_last_check.isoformat() if getattr(s, 'health_last_check', None) else None,
        }
        sources.append(source_dict)
    
    # 密钥分组
    groups = []
    for g in db.query(ComputeKeyGroup).all():
        groups.append({
            "group_id": g.group_id,
            "name": g.name,
            "description": getattr(g, 'description', ''),
            "status": "active",  # 第一部分没有 status 字段
            "source_ids": g.source_ids or [],
            "default_source": getattr(g, 'default_source', ''),
            "load_balance_strategy": getattr(g, 'routing_strategy', 'auto'),
            "routing_strategy": getattr(g, 'routing_strategy', 'auto'),
        })
    
    # 模型绑定
    bindings = []
    for b in db.query(ComputeModelBinding).all():
        bindings.append({
            "model_key": b.model_key,
            "model_name": b.model_name,
            "purpose": b.purpose,
            "key_group_id": b.group_id,  # 兼容字段
            "group_id": b.group_id,
            "fallback_model_key": getattr(b, 'fallback_model_key', ''),
            "fallback_group_id": "",  # 第一部分没有
            "default_policy_id": "default",  # 第一部分没有
            "max_input_tokens": getattr(b, 'max_tokens', 4096),
            "max_output_tokens": getattr(b, 'max_tokens', 4096),
            "max_tokens": getattr(b, 'max_tokens', 4096),
            "temperature_default": getattr(b, 'temperature_default', 0.7),
            "status": "active",  # 第一部分没有
        })
    
    # 路由策略
    policies = []
    for p in db.query(ComputeRoutingPolicy).all():
        config = getattr(p, 'config', {}) or {}
        is_active = getattr(p, 'mode', 'auto') == 'auto'
        
        policies.append({
            "policy_id": p.policy_id,
            "name": p.name,
            "description": "",  # 第一部分没有
            "is_active": is_active,
            "mode": getattr(p, 'mode', 'auto'),
            "default_strategy": getattr(p, 'default_strategy', 'latency_first'),
            "latency_weight": p.latency_weight,
            "cost_weight": p.cost_weight,
            "quality_weight": p.quality_weight,
            "privacy_weight": p.privacy_weight,
            "circuit_breaker_enabled": p.circuit_breaker_enabled,
            "cb_error_threshold": config.get('cb_error_threshold', 0.5),
            "cb_window_seconds": config.get('cb_window_seconds', 60),
            "cb_cooldown_seconds": config.get('cb_cooldown_seconds', 30),
            "cb_half_open_probes": config.get('cb_half_open_probes', 3),
            "rate_limit_enabled": p.rate_limit_enabled,
            "global_rate_per_minute": config.get('global_rate_per_minute', 1000),
            "auto_failover": p.auto_failover,
            "max_failover_attempts": config.get('max_failover_attempts', 3),
            "offline_degradation": p.offline_fallback_enabled,
            "offline_fallback_enabled": p.offline_fallback_enabled,
            "vram_safe_threshold": getattr(p, 'vram_safe_threshold', 70.0),
            "vram_critical_threshold": getattr(p, 'vram_critical_threshold', 90.0),
            "network_latency_threshold": getattr(p, 'network_latency_threshold', 500),
            "extra_config": config,
        })
    
    # 技能绑定
    skills = []
    for s in db.query(ComputeSkillBinding).all():
        skills.append({
            "skill_id": s.skill_id,
            "skill_name": s.skill_name,
            "description": "",  # 第一部分没有
            "allowed_source_ids": getattr(s, 'allowed_sources', []) or [],
            "allowed_sources": getattr(s, 'allowed_sources', []) or [],
            "denied_source_ids": [],  # 第一部分没有
            "allowed_groups": getattr(s, 'allowed_groups', []) or [],
            "max_tokens_per_request": 0,  # 第一部分没有
            "daily_token_quota": 0,  # 第一部分没有
            "quota_daily": getattr(s, 'quota_daily', 0.0),
            "quota_monthly": getattr(s, 'quota_monthly', 0.0),
            "rate_limit_per_min": getattr(s, 'rate_limit_per_min', 0),
            "priority_bonus": 0.0,  # 第一部分没有
            "priority": getattr(s, 'priority', 50),
            "status": "active",  # 第一部分没有
        })
    
    # 额度配置
    quotas = []
    for q in db.query(ComputeQuota).all():
        quota_id = f"{q.scope}_{q.scope_key}_{q.period}"
        quotas.append({
            "quota_id": quota_id,
            "scope": q.scope,
            "scope_key": q.scope_key,
            "period": q.period,
            "limit_type": "cost",  # 第一部分都是成本型
            "limit_value": q.limit_amount,
            "limit_amount": q.limit_amount,
            "used_value": q.used_amount,
            "used_amount": q.used_amount,
            "alert_threshold": q.alert_threshold / 100.0,  # 百分比转小数
            "alert_threshold_pct": q.alert_threshold,
            "action_on_exceed": getattr(q, 'action_on_exceed', 'alert_only'),
            "status": "active",  # 第一部分没有
            "reset_at": q.reset_at.isoformat() if getattr(q, 'reset_at', None) else None,
        })
    
    item_count = len(sources) + len(groups) + len(bindings) + len(policies) + len(skills) + len(quotas)
    
    return {
        "version": "1.0",
        "export_time": datetime.utcnow().isoformat(),
        "item_count": item_count,
        "sources": sources,
        "key_groups": groups,
        "model_bindings": bindings,
        "routing_policies": policies,
        "skill_bindings": skills,
        "quotas": quotas,
    }


def _validate_config(config_data: Dict[str, Any]) -> Dict[str, Any]:
    """
    验证配置文件有效性
    返回 {"valid": bool, "errors": [], "warnings": []}
    """
    errors = []
    warnings = []
    
    # 检查必需字段
    if not isinstance(config_data, dict):
        return {"valid": False, "errors": ["配置数据必须是 JSON 对象"], "warnings": []}
    
    # 检查算力源
    sources = config_data.get("sources", [])
    if not isinstance(sources, list):
        errors.append("sources 必须是数组")
    else:
        source_ids = set()
        for i, s in enumerate(sources):
            if not s.get("source_id"):
                errors.append(f"sources[{i}]: source_id 不能为空")
            elif s["source_id"] in source_ids:
                errors.append(f"sources[{i}]: source_id '{s['source_id']}' 重复")
            else:
                source_ids.add(s["source_id"])
            if not s.get("name"):
                errors.append(f"sources[{i}]: name 不能为空")
    
    # 检查密钥分组
    groups = config_data.get("key_groups", [])
    if not isinstance(groups, list):
        errors.append("key_groups 必须是数组")
    else:
        group_ids = set()
        for i, g in enumerate(groups):
            if not g.get("group_id"):
                errors.append(f"key_groups[{i}]: group_id 不能为空")
            elif g["group_id"] in group_ids:
                errors.append(f"key_groups[{i}]: group_id '{g['group_id']}' 重复")
            else:
                group_ids.add(g["group_id"])
            
            # 检查引用的算力源是否存在
            for sid in g.get("source_ids", []):
                if sources and sid not in source_ids:
                    warnings.append(f"key_groups[{i}]: source_id '{sid}' 引用的算力源不存在")
    
    # 检查模型绑定
    bindings = config_data.get("model_bindings", [])
    if not isinstance(bindings, list):
        errors.append("model_bindings 必须是数组")
    else:
        model_keys = set()
        for i, b in enumerate(bindings):
            if not b.get("model_key"):
                errors.append(f"model_bindings[{i}]: model_key 不能为空")
            elif b["model_key"] in model_keys:
                errors.append(f"model_bindings[{i}]: model_key '{b['model_key']}' 重复")
            else:
                model_keys.add(b["model_key"])
            
            group_id = b.get("key_group_id") or b.get("group_id")
            if group_id and groups and group_id not in group_ids:
                warnings.append(f"model_bindings[{i}]: group_id '{group_id}' 引用的分组不存在")
    
    # 检查路由策略
    policies = config_data.get("routing_policies", [])
    if not isinstance(policies, list):
        errors.append("routing_policies 必须是数组")
    else:
        policy_ids = set()
        active_count = 0
        for i, p in enumerate(policies):
            if not p.get("policy_id"):
                errors.append(f"routing_policies[{i}]: policy_id 不能为空")
            elif p["policy_id"] in policy_ids:
                errors.append(f"routing_policies[{i}]: policy_id '{p['policy_id']}' 重复")
            else:
                policy_ids.add(p["policy_id"])
            
            if p.get("is_active") or p.get("mode") == "auto":
                active_count += 1
            
            # 检查权重之和
            weights = sum([
                p.get("latency_weight", 0),
                p.get("cost_weight", 0),
                p.get("quality_weight", 0),
                p.get("privacy_weight", 0),
            ])
            if weights <= 0:
                errors.append(f"routing_policies[{i}]: 权重之和必须大于 0")
        
        if active_count > 1:
            warnings.append(f"路由策略中有 {active_count} 个激活策略，应该只有一个")
    
    # 检查技能绑定
    skills = config_data.get("skill_bindings", [])
    if not isinstance(skills, list):
        errors.append("skill_bindings 必须是数组")
    else:
        skill_ids = set()
        for i, s in enumerate(skills):
            if not s.get("skill_id"):
                errors.append(f"skill_bindings[{i}]: skill_id 不能为空")
            elif s["skill_id"] in skill_ids:
                errors.append(f"skill_bindings[{i}]: skill_id '{s['skill_id']}' 重复")
            else:
                skill_ids.add(s["skill_id"])
    
    # 检查额度配置
    quotas = config_data.get("quotas", [])
    if not isinstance(quotas, list):
        errors.append("quotas 必须是数组")
    else:
        quota_ids = set()
        for i, q in enumerate(quotas):
            qid = q.get("quota_id") or f"{q.get('scope', '')}_{q.get('scope_key', '')}_{q.get('period', '')}"
            if not qid or qid == "__":
                errors.append(f"quotas[{i}]: 缺少 scope/scope_key/period 标识")
            elif qid in quota_ids:
                errors.append(f"quotas[{i}]: quota_id '{qid}' 重复")
            else:
                quota_ids.add(qid)
            
            valid_periods = ["daily", "weekly", "monthly", "total"]
            if q.get("period") and q["period"] not in valid_periods:
                errors.append(f"quotas[{i}]: period 必须是 {valid_periods} 之一")
    
    valid = len(errors) == 0
    
    return {
        "valid": valid,
        "errors": errors,
        "warnings": warnings,
        "item_count": {
            "sources": len(sources) if isinstance(sources, list) else 0,
            "key_groups": len(groups) if isinstance(groups, list) else 0,
            "model_bindings": len(bindings) if isinstance(bindings, list) else 0,
            "routing_policies": len(policies) if isinstance(policies, list) else 0,
            "skill_bindings": len(skills) if isinstance(skills, list) else 0,
            "quotas": len(quotas) if isinstance(quotas, list) else 0,
        }
    }


def _backup_to_dict(backup: ComputeConfigBackup) -> Dict[str, Any]:
    """备份记录 ORM 转字典"""
    return {
        "id": backup.id,
        "backup_id": backup.backup_id,
        "name": backup.name,
        "description": backup.description,
        "backup_type": backup.backup_type,
        "item_count": backup.item_count,
        "created_by": backup.created_by,
        "created_at": backup.created_at.timestamp() if backup.created_at else None,
        "created_at_formatted": backup.created_at.strftime("%Y-%m-%d %H:%M:%S") if backup.created_at else "",
    }


def _source_from_dict(data: Dict[str, Any]) -> Dict[str, Any]:
    """从配置字典转换为第一部分表字段"""
    config = data.get("extra_config", {}) or {}
    
    # 提取额外配置字段
    if "quality_score" in data:
        config["quality_score"] = data["quality_score"]
    if "privacy_level" in data:
        config["privacy_level"] = data["privacy_level"]
    if "rate_limit_per_minute" in data:
        config["rate_limit_per_minute"] = data["rate_limit_per_minute"]
    if "rate_limit_per_day" in data:
        config["rate_limit_per_day"] = data["rate_limit_per_day"]
    if "auto_failover" in data:
        config["auto_failover"] = data["auto_failover"]
    if "region" in data:
        config["region"] = data["region"]
    
    # deployment_type 映射到 type
    src_type = data.get("type") or data.get("deployment_type", "cloud")
    models = data.get("models", [data.get("model_name", "")]) if data.get("models") else [data.get("model_name", "")]
    
    return {
        "source_id": data["source_id"],
        "name": data["name"],
        "provider": data.get("provider", "custom"),
        "base_url": data.get("base_url", ""),
        "type": src_type,
        "api_key_encrypted": data.get("api_key_encrypted", data.get("api_key", "")),
        "api_key_masked": data.get("api_key_masked", ""),
        "status": data.get("status", "inactive"),
        "priority": data.get("priority", 100),
        "weight": data.get("weight", 100),
        "max_concurrent": data.get("max_concurrent", 10),
        "timeout": data.get("timeout", 60),
        "cost_per_1k_input": data.get("cost_per_1k_input", 0.0),
        "cost_per_1k_output": data.get("cost_per_1k_output", 0.0),
        "latency_avg": data.get("latency_avg", data.get("latency_ms", 0.0)),
        "success_rate": data.get("success_rate", 1.0),
        "models": models,
        "capabilities": data.get("capabilities", []),
        "health_status": data.get("health_status", "unknown"),
        "config": config,
    }


def _group_from_dict(data: Dict[str, Any]) -> Dict[str, Any]:
    """从配置字典转换为第一部分表字段"""
    return {
        "group_id": data["group_id"],
        "name": data["name"],
        "description": data.get("description", ""),
        "source_ids": data.get("source_ids", []),
        "default_source": data.get("default_source", ""),
        "routing_strategy": data.get("routing_strategy", data.get("load_balance_strategy", "auto")),
    }


def _binding_from_dict(data: Dict[str, Any]) -> Dict[str, Any]:
    """从配置字典转换为第一部分表字段"""
    return {
        "model_key": data["model_key"],
        "model_name": data.get("model_name", data["model_key"]),
        "purpose": data.get("purpose", "chat"),
        "group_id": data.get("group_id", data.get("key_group_id", "")),
        "fallback_model_key": data.get("fallback_model_key", ""),
        "max_tokens": data.get("max_tokens", data.get("max_input_tokens", 4096)),
        "temperature_default": data.get("temperature_default", 0.7),
    }


def _policy_from_dict(data: Dict[str, Any]) -> Dict[str, Any]:
    """从配置字典转换为第一部分表字段"""
    config = data.get("extra_config", {}) or {}
    
    # 提取额外配置字段
    cb_fields = ["cb_error_threshold", "cb_window_seconds", "cb_cooldown_seconds", "cb_half_open_probes"]
    for f in cb_fields:
        if f in data:
            config[f] = data[f]
    if "global_rate_per_minute" in data:
        config["global_rate_per_minute"] = data["global_rate_per_minute"]
    if "max_failover_attempts" in data:
        config["max_failover_attempts"] = data["max_failover_attempts"]
    
    # mode 字段
    mode = data.get("mode", "auto")
    if "is_active" in data and "mode" not in data:
        mode = "auto" if data["is_active"] else "manual"
    
    return {
        "policy_id": data["policy_id"],
        "name": data["name"],
        "mode": mode,
        "default_strategy": data.get("default_strategy", "latency_first"),
        "latency_weight": data.get("latency_weight", 0.4),
        "cost_weight": data.get("cost_weight", 0.3),
        "quality_weight": data.get("quality_weight", 0.2),
        "privacy_weight": data.get("privacy_weight", 0.1),
        "circuit_breaker_enabled": data.get("circuit_breaker_enabled", True),
        "rate_limit_enabled": data.get("rate_limit_enabled", True),
        "auto_failover": data.get("auto_failover", True),
        "offline_fallback_enabled": data.get("offline_fallback_enabled", data.get("offline_degradation", True)),
        "vram_safe_threshold": data.get("vram_safe_threshold", 70.0),
        "vram_critical_threshold": data.get("vram_critical_threshold", 90.0),
        "network_latency_threshold": data.get("network_latency_threshold", 500),
        "config": config,
    }


def _skill_from_dict(data: Dict[str, Any]) -> Dict[str, Any]:
    """从配置字典转换为第一部分表字段"""
    return {
        "skill_id": data["skill_id"],
        "skill_name": data.get("skill_name", data["skill_id"]),
        "allowed_groups": data.get("allowed_groups", []),
        "allowed_sources": data.get("allowed_sources", data.get("allowed_source_ids", [])),
        "quota_daily": data.get("quota_daily", 0.0),
        "quota_monthly": data.get("quota_monthly", 0.0),
        "rate_limit_per_min": data.get("rate_limit_per_min", 0),
        "priority": data.get("priority", 50),
    }


def _quota_from_dict(data: Dict[str, Any]) -> Dict[str, Any]:
    """从配置字典转换为第一部分表字段"""
    # 从 quota_id 解析 scope/scope_key/period
    scope = data.get("scope", "")
    scope_key = data.get("scope_key", "")
    period = data.get("period", "daily")
    
    if not scope and data.get("quota_id"):
        parts = data["quota_id"].split("_", 2)
        if len(parts) == 3:
            scope, scope_key, period = parts
    
    # alert_threshold 处理（可能是百分比或小数）
    alert_threshold = data.get("alert_threshold", 80.0)
    if alert_threshold <= 1.0:
        alert_threshold = alert_threshold * 100  # 转百分比
    
    return {
        "scope": scope,
        "scope_key": scope_key,
        "period": period,
        "limit_amount": data.get("limit_amount", data.get("limit_value", 0.0)),
        "used_amount": data.get("used_amount", data.get("used_value", 0.0)),
        "alert_threshold": alert_threshold,
        "action_on_exceed": data.get("action_on_exceed", "alert_only"),
    }


# ============================================================
# 配置导出
# ============================================================

@router.get("/export")
@require_role("admin")
async def export_config(
    mask_keys: bool = Query(True, description="是否掩码 API Key"),
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """导出全部配置（JSON）"""
    try:
        config_data = _collect_config_data(db, mask_keys=mask_keys)
        return ApiResponse.success(
            data=config_data,
            message=f"配置导出成功，共 {config_data['item_count']} 项",
        )
    except Exception as e:
        return ApiResponse.error(code=500, message=f"导出失败: {str(e)}")


# ============================================================
# 配置导入
# ============================================================

@router.post("/import")
@require_role("owner")
async def import_config(
    request: ImportConfigRequest,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """
    导入配置
    支持全量覆盖(overwrite)和增量合并(merge)两种模式
    """
    config_data = request.config_data
    mode = request.mode.lower()
    
    if mode not in ("overwrite", "merge"):
        return ApiResponse.error(code=400, message="mode 必须是 overwrite 或 merge")
    
    # 验证配置
    validation = _validate_config(config_data)
    if not validation["valid"]:
        return ApiResponse.error(
            code=400,
            message="配置验证失败",
            data=validation,
        )
    
    if request.validate_only:
        return ApiResponse.success(data=validation, message="配置验证通过")
    
    # 导入前先备份现有配置
    try:
        existing_config = _collect_config_data(db, mask_keys=False)
        backup = ComputeConfigBackup(
            backup_id=f"backup-pre-import-{int(time.time())}",
            name=f"导入前备份 - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
            description=f"导入配置前自动备份，模式: {mode}",
            backup_type="auto",
            config_data=existing_config,
            item_count=existing_config["item_count"],
            created_by=current_user.get("username", "system"),
            created_at=datetime.utcnow(),
        )
        db.add(backup)
        db.flush()
    except Exception as e:
        # 备份失败不阻止导入
        pass
    
    # 执行导入
    stats = {"created": 0, "updated": 0, "skipped": 0, "deleted": 0}
    
    try:
        if mode == "overwrite":
            # 全量覆盖：先清空所有配置表
            db.query(ComputeQuota).delete()
            db.query(ComputeSkillBinding).delete()
            db.query(ComputeRoutingPolicy).delete()
            db.query(ComputeModelBinding).delete()
            db.query(ComputeKeyGroup).delete()
            db.query(ComputeSource).delete()
            stats["deleted"] = "all"
        
        # 导入算力源
        for s_data in config_data.get("sources", []):
            source_dict = _source_from_dict(s_data)
            existing = db.query(ComputeSource).filter(
                ComputeSource.source_id == source_dict["source_id"]
            ).first()
            if existing:
                if mode == "merge":
                    # 更新
                    for key, value in source_dict.items():
                        if key != "api_key_encrypted" or (value and not value.startswith("****")):
                            if hasattr(existing, key):
                                setattr(existing, key, value)
                    stats["updated"] += 1
                else:
                    new_source = ComputeSource(**source_dict)
                    db.add(new_source)
                    stats["created"] += 1
            else:
                new_source = ComputeSource(**source_dict)
                db.add(new_source)
                stats["created"] += 1
        
        # 导入密钥分组
        for g_data in config_data.get("key_groups", []):
            group_dict = _group_from_dict(g_data)
            existing = db.query(ComputeKeyGroup).filter(
                ComputeKeyGroup.group_id == group_dict["group_id"]
            ).first()
            if existing:
                if mode == "merge":
                    for key, value in group_dict.items():
                        if hasattr(existing, key):
                            setattr(existing, key, value)
                    stats["updated"] += 1
                else:
                    new_group = ComputeKeyGroup(**group_dict)
                    db.add(new_group)
                    stats["created"] += 1
            else:
                new_group = ComputeKeyGroup(**group_dict)
                db.add(new_group)
                stats["created"] += 1
        
        # 导入模型绑定
        for b_data in config_data.get("model_bindings", []):
            binding_dict = _binding_from_dict(b_data)
            existing = db.query(ComputeModelBinding).filter(
                ComputeModelBinding.model_key == binding_dict["model_key"]
            ).first()
            if existing:
                if mode == "merge":
                    for key, value in binding_dict.items():
                        if hasattr(existing, key):
                            setattr(existing, key, value)
                    stats["updated"] += 1
                else:
                    new_binding = ComputeModelBinding(**binding_dict)
                    db.add(new_binding)
                    stats["created"] += 1
            else:
                new_binding = ComputeModelBinding(**binding_dict)
                db.add(new_binding)
                stats["created"] += 1
        
        # 导入路由策略
        for p_data in config_data.get("routing_policies", []):
            policy_dict = _policy_from_dict(p_data)
            existing = db.query(ComputeRoutingPolicy).filter(
                ComputeRoutingPolicy.policy_id == policy_dict["policy_id"]
            ).first()
            if existing:
                if mode == "merge":
                    for key, value in policy_dict.items():
                        if hasattr(existing, key):
                            setattr(existing, key, value)
                    stats["updated"] += 1
                else:
                    new_policy = ComputeRoutingPolicy(**policy_dict)
                    db.add(new_policy)
                    stats["created"] += 1
            else:
                new_policy = ComputeRoutingPolicy(**policy_dict)
                db.add(new_policy)
                stats["created"] += 1
        
        # 导入技能绑定
        for s_data in config_data.get("skill_bindings", []):
            skill_dict = _skill_from_dict(s_data)
            existing = db.query(ComputeSkillBinding).filter(
                ComputeSkillBinding.skill_id == skill_dict["skill_id"]
            ).first()
            if existing:
                if mode == "merge":
                    for key, value in skill_dict.items():
                        if hasattr(existing, key):
                            setattr(existing, key, value)
                    stats["updated"] += 1
                else:
                    new_skill = ComputeSkillBinding(**skill_dict)
                    db.add(new_skill)
                    stats["created"] += 1
            else:
                new_skill = ComputeSkillBinding(**skill_dict)
                db.add(new_skill)
                stats["created"] += 1
        
        # 导入额度配置
        for q_data in config_data.get("quotas", []):
            quota_dict = _quota_from_dict(q_data)
            existing = db.query(ComputeQuota).filter(
                ComputeQuota.scope == quota_dict["scope"],
                ComputeQuota.scope_key == quota_dict["scope_key"],
                ComputeQuota.period == quota_dict["period"],
            ).first()
            if existing:
                if mode == "merge":
                    for key, value in quota_dict.items():
                        if hasattr(existing, key) and key != "used_amount":
                            setattr(existing, key, value)
                    stats["updated"] += 1
                else:
                    new_quota = ComputeQuota(**quota_dict)
                    db.add(new_quota)
                    stats["created"] += 1
            else:
                new_quota = ComputeQuota(**quota_dict)
                db.add(new_quota)
                stats["created"] += 1
        
        db.commit()
        
        # 重新加载路由引擎配置
        compute_router.reload_config()
        
        return ApiResponse.success(
            data={
                "mode": mode,
                "stats": stats,
                "validation": validation,
            },
            message=f"配置导入成功，新增 {stats['created']} 项，更新 {stats['updated']} 项",
        )
    
    except Exception as e:
        db.rollback()
        return ApiResponse.error(code=500, message=f"导入失败: {str(e)}")


# ============================================================
# 配置验证
# ============================================================

@router.post("/validate")
async def validate_config(
    request: ValidateConfigRequest,
    current_user: dict = Depends(get_current_user),
):
    """验证配置文件有效性"""
    result = _validate_config(request.config_data)
    return ApiResponse.success(data=result)


# ============================================================
# 配置备份管理
# ============================================================

@router.get("/backup/list")
@require_role("admin")
async def list_backups(
    backup_type: Optional[str] = Query(None, description="按类型筛选"),
    limit: int = Query(50, description="返回条数"),
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """获取配置备份列表"""
    try:
        query = db.query(ComputeConfigBackup)
        
        if backup_type:
            query = query.filter(ComputeConfigBackup.backup_type == backup_type)
        
        backups = query.order_by(ComputeConfigBackup.created_at.desc()).limit(limit).all()
        total = query.count()
        
        return ApiResponse.success(
            data={
                "total": total,
                "items": [_backup_to_dict(b) for b in backups],
            }
        )
    except Exception as e:
        return ApiResponse.success(data={"total": 0, "items": []})


@router.post("/backup/create")
@require_role("admin")
async def create_backup(
    request: CreateBackupRequest,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """手动创建备份"""
    try:
        config_data = _collect_config_data(db, mask_keys=False)
        
        backup_name = request.name or f"手动备份 - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
        
        backup = ComputeConfigBackup(
            backup_id=f"backup-manual-{int(time.time())}-{uuid.uuid4().hex[:8]}",
            name=backup_name,
            description=request.description,
            backup_type="manual",
            config_data=config_data,
            item_count=config_data["item_count"],
            created_by=current_user.get("username", "system"),
            created_at=datetime.utcnow(),
        )
        db.add(backup)
        db.commit()
        db.refresh(backup)
        
        return ApiResponse.success(data=_backup_to_dict(backup), message="备份创建成功")
    except Exception as e:
        db.rollback()
        return ApiResponse.error(code=500, message=f"创建备份失败: {str(e)}")


@router.post("/backup/{backup_id}/restore")
@require_role("owner")
async def restore_backup(
    backup_id: str,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """从备份恢复配置"""
    try:
        backup = db.query(ComputeConfigBackup).filter(
            ComputeConfigBackup.backup_id == backup_id
        ).first()
        
        if not backup:
            return ApiResponse.error(code=404, message=f"备份 {backup_id} 不存在")
        
        config_data = backup.config_data
        if not config_data:
            return ApiResponse.error(code=400, message="备份数据为空")
        
        # 验证备份数据
        validation = _validate_config(config_data)
        if not validation["valid"]:
            return ApiResponse.error(
                code=400,
                message="备份数据验证失败",
                data=validation,
            )
        
        # 恢复前先备份当前配置
        current_config = _collect_config_data(db, mask_keys=False)
        pre_restore_backup = ComputeConfigBackup(
            backup_id=f"backup-pre-restore-{int(time.time())}",
            name=f"恢复前备份 - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
            description=f"恢复备份 {backup_id} 前的自动备份",
            backup_type="auto",
            config_data=current_config,
            item_count=current_config["item_count"],
            created_by=current_user.get("username", "system"),
            created_at=datetime.utcnow(),
        )
        db.add(pre_restore_backup)
        
        # 清空现有配置
        db.query(ComputeQuota).delete()
        db.query(ComputeSkillBinding).delete()
        db.query(ComputeRoutingPolicy).delete()
        db.query(ComputeModelBinding).delete()
        db.query(ComputeKeyGroup).delete()
        db.query(ComputeSource).delete()
        
        # 恢复算力源
        for s_data in config_data.get("sources", []):
            source_dict = _source_from_dict(s_data)
            new_source = ComputeSource(**source_dict)
            db.add(new_source)
        
        # 恢复密钥分组
        for g_data in config_data.get("key_groups", []):
            group_dict = _group_from_dict(g_data)
            new_group = ComputeKeyGroup(**group_dict)
            db.add(new_group)
        
        # 恢复模型绑定
        for b_data in config_data.get("model_bindings", []):
            binding_dict = _binding_from_dict(b_data)
            new_binding = ComputeModelBinding(**binding_dict)
            db.add(new_binding)
        
        # 恢复路由策略
        for p_data in config_data.get("routing_policies", []):
            policy_dict = _policy_from_dict(p_data)
            new_policy = ComputeRoutingPolicy(**policy_dict)
            db.add(new_policy)
        
        # 恢复技能绑定
        for s_data in config_data.get("skill_bindings", []):
            skill_dict = _skill_from_dict(s_data)
            new_skill = ComputeSkillBinding(**skill_dict)
            db.add(new_skill)
        
        # 恢复额度配置
        for q_data in config_data.get("quotas", []):
            quota_dict = _quota_from_dict(q_data)
            new_quota = ComputeQuota(**quota_dict)
            db.add(new_quota)
        
        db.commit()
        
        # 重新加载路由引擎配置
        compute_router.reload_config()
        
        return ApiResponse.success(
            data={
                "restored_backup_id": backup_id,
                "pre_restore_backup_id": pre_restore_backup.backup_id,
                "item_count": backup.item_count,
            },
            message="配置恢复成功",
        )
    
    except Exception as e:
        db.rollback()
        return ApiResponse.error(code=500, message=f"恢复失败: {str(e)}")
