"""
M8 管理工作台 - 算力调度模型

包含 ComputeSource, ComputeKeyGroup, ComputeModelBinding, ComputeRoutingPolicy,
ComputeCallLog, ComputeAlert, ComputeQuota, ComputeSkillBinding, ComputeConfigBackup。
"""

from sqlalchemy import Column, Integer, String, DateTime, Text, Boolean, Float, JSON
from datetime import datetime

from .base import Base


class ComputeSource(Base):
    """算力调度 - 算力源表"""
    __tablename__ = "compute_sources"

    id = Column(Integer, primary_key=True, index=True)
    source_id = Column(String(64), unique=True, index=True, comment="算力源唯一标识")
    name = Column(String(100), comment="显示名称")
    type = Column(String(20), default="cloud", comment="类型：local/cloud/private")
    provider = Column(String(50), default="custom", comment="服务商")
    base_url = Column(String(255), comment="API 地址")
    api_key_encrypted = Column(Text, default="", comment="加密后的 API Key")
    api_key_masked = Column(String(100), default="", comment="掩码后的 API Key")
    status = Column(String(20), default="inactive", comment="状态：active/inactive/error")
    priority = Column(Integer, default=100, comment="优先级，数字越小越优先")
    weight = Column(Integer, default=100, comment="负载权重")
    max_concurrent = Column(Integer, default=10, comment="最大并发数")
    timeout = Column(Integer, default=60, comment="超时时间秒")
    cost_per_1k_input = Column(Float, default=0.0, comment="每千输入 token 成本")
    cost_per_1k_output = Column(Float, default=0.0, comment="每千输出 token 成本")
    latency_avg = Column(Float, default=0.0, comment="平均延迟(ms)")
    success_rate = Column(Float, default=1.0, comment="成功率")
    models = Column(JSON, default=list, comment="支持的模型列表")
    capabilities = Column(JSON, default=list, comment="能力标签列表")
    health_status = Column(String(20), default="unknown", comment="健康状态：healthy/unhealthy/unknown")
    health_last_check = Column(DateTime, nullable=True, comment="最近健康检查时间")
    config = Column(JSON, default=dict, comment="扩展配置（JSON）")
    created_at = Column(DateTime, default=datetime.utcnow, comment="创建时间")
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, comment="更新时间")

    def to_dict(self):
        return {
            "id": self.id,
            "source_id": self.source_id,
            "name": self.name,
            "type": self.type,
            "provider": self.provider,
            "base_url": self.base_url,
            "api_key_masked": self.api_key_masked,
            "status": self.status,
            "priority": self.priority,
            "weight": self.weight,
            "max_concurrent": self.max_concurrent,
            "timeout": self.timeout,
            "cost_per_1k_input": self.cost_per_1k_input,
            "cost_per_1k_output": self.cost_per_1k_output,
            "latency_avg": self.latency_avg,
            "success_rate": self.success_rate,
            "models": self.models or [],
            "capabilities": self.capabilities or [],
            "health_status": self.health_status,
            "health_last_check": self.health_last_check.isoformat() if self.health_last_check else None,
            "config": self.config or {},
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


class ComputeKeyGroup(Base):
    """算力调度 - 密钥分组表"""
    __tablename__ = "compute_key_groups"

    id = Column(Integer, primary_key=True, index=True)
    group_id = Column(String(64), unique=True, index=True, comment="分组唯一标识")
    name = Column(String(100), comment="分组名称")
    description = Column(Text, default="", comment="描述")
    source_ids = Column(JSON, default=list, comment="绑定的算力源 ID 列表")
    default_source = Column(String(64), default="", comment="默认算力源")
    routing_strategy = Column(String(50), default="auto", comment="路由策略")
    created_at = Column(DateTime, default=datetime.utcnow, comment="创建时间")
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, comment="更新时间")

    def to_dict(self):
        return {
            "id": self.id,
            "group_id": self.group_id,
            "name": self.name,
            "description": self.description,
            "source_ids": self.source_ids or [],
            "source_count": len(self.source_ids or []),
            "default_source": self.default_source,
            "routing_strategy": self.routing_strategy,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


class ComputeModelBinding(Base):
    """算力调度 - 模型绑定表"""
    __tablename__ = "compute_model_bindings"

    id = Column(Integer, primary_key=True, index=True)
    model_key = Column(String(64), unique=True, index=True, comment="模型标识，如 default-chat")
    model_name = Column(String(100), comment="显示名称")
    purpose = Column(String(20), default="chat", comment="用途：chat/embedding/code/vision")
    group_id = Column(String(64), default="", comment="绑定的密钥分组 ID")
    fallback_model_key = Column(String(64), default="", comment="降级模型 key")
    max_tokens = Column(Integer, default=4096, comment="最大 token 数")
    temperature_default = Column(Float, default=0.7, comment="默认温度")
    created_at = Column(DateTime, default=datetime.utcnow, comment="创建时间")
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, comment="更新时间")

    def to_dict(self):
        return {
            "id": self.id,
            "model_key": self.model_key,
            "model_name": self.model_name,
            "purpose": self.purpose,
            "group_id": self.group_id,
            "fallback_model_key": self.fallback_model_key,
            "max_tokens": self.max_tokens,
            "temperature_default": self.temperature_default,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


class ComputeRoutingPolicy(Base):
    """算力调度 - 路由策略表"""
    __tablename__ = "compute_routing_policies"

    id = Column(Integer, primary_key=True, index=True)
    policy_id = Column(String(64), unique=True, index=True, comment="策略ID")
    name = Column(String(100), comment="策略名称")
    mode = Column(String(20), default="auto", comment="模式：manual/auto")
    default_strategy = Column(String(50), default="latency_first", comment="默认策略")
    latency_weight = Column(Float, default=0.4, comment="延迟权重")
    cost_weight = Column(Float, default=0.3, comment="成本权重")
    quality_weight = Column(Float, default=0.2, comment="质量权重")
    privacy_weight = Column(Float, default=0.1, comment="隐私权重")
    circuit_breaker_enabled = Column(Boolean, default=True, comment="是否启用熔断")
    rate_limit_enabled = Column(Boolean, default=True, comment="是否启用限流")
    auto_failover = Column(Boolean, default=True, comment="是否自动故障转移")
    offline_fallback_enabled = Column(Boolean, default=True, comment="是否启用离线降级")
    vram_safe_threshold = Column(Float, default=70.0, comment="显存安全阈值")
    vram_critical_threshold = Column(Float, default=90.0, comment="显存危险阈值")
    network_latency_threshold = Column(Integer, default=500, comment="网络延迟阈值ms")
    config = Column(JSON, default=dict, comment="额外配置（JSON）")
    created_at = Column(DateTime, default=datetime.utcnow, comment="创建时间")
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, comment="更新时间")

    def to_dict(self):
        config = self.config or {}
        return {
            "id": self.id,
            "policy_id": self.policy_id,
            "name": self.name,
            "mode": self.mode,
            "default_strategy": self.default_strategy,
            "is_active": self.mode == "auto",
            "latency_weight": self.latency_weight,
            "cost_weight": self.cost_weight,
            "quality_weight": self.quality_weight,
            "privacy_weight": self.privacy_weight,
            "circuit_breaker_enabled": self.circuit_breaker_enabled,
            "cb_error_threshold": config.get("cb_error_threshold", 0.5),
            "cb_window_seconds": config.get("cb_window_seconds", 60),
            "cb_cooldown_seconds": config.get("cb_cooldown_seconds", 30),
            "cb_half_open_probes": config.get("cb_half_open_probes", 3),
            "rate_limit_enabled": self.rate_limit_enabled,
            "global_rate_per_minute": config.get("global_rate_per_minute", 1000),
            "auto_failover": self.auto_failover,
            "max_failover_attempts": config.get("max_failover_attempts", 3),
            "offline_fallback_enabled": self.offline_fallback_enabled,
            "offline_degradation": self.offline_fallback_enabled,
            "vram_safe_threshold": self.vram_safe_threshold,
            "vram_critical_threshold": self.vram_critical_threshold,
            "network_latency_threshold": self.network_latency_threshold,
            "extra_config": config,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


class ComputeCallLog(Base):
    """算力调度 - 调用日志表"""
    __tablename__ = "compute_call_logs"

    id = Column(Integer, primary_key=True, index=True)
    call_id = Column(String(64), unique=True, index=True, comment="调用ID")
    model_key = Column(String(64), index=True, comment="模型 key")
    source_id = Column(String(64), index=True, comment="算力源 ID")
    caller_module = Column(String(20), index=True, comment="调用模块")
    caller_skill = Column(String(100), default="", comment="调用技能")
    input_tokens = Column(Integer, default=0, comment="输入 token 数")
    output_tokens = Column(Integer, default=0, comment="输出 token 数")
    cost = Column(Float, default=0.0, comment="成本")
    latency_ms = Column(Integer, default=0, comment="延迟(ms)")
    status = Column(String(20), default="success", comment="状态：success/failed")
    error_code = Column(String(50), default="", comment="错误码")
    error_message = Column(Text, default="", comment="错误信息")
    request_hash = Column(String(64), default="", comment="请求哈希")
    created_at = Column(DateTime, default=datetime.utcnow, index=True, comment="创建时间")

    def to_dict(self):
        total_tokens = (self.input_tokens or 0) + (self.output_tokens or 0)
        return {
            "id": self.id,
            "log_id": self.call_id,
            "call_id": self.call_id,
            "model_key": self.model_key,
            "source_id": self.source_id,
            "caller_module": self.caller_module,
            "caller_skill": self.caller_skill or "",
            "input_tokens": self.input_tokens or 0,
            "output_tokens": self.output_tokens or 0,
            "total_tokens": total_tokens,
            "cost": self.cost or 0.0,
            "latency_ms": self.latency_ms or 0,
            "status": self.status,
            "error_code": self.error_code or "",
            "error_message": self.error_message or "",
            "request_hash": self.request_hash or "",
            "failover_count": 0,
            "original_source_id": "",
            "priority": "normal",
            "privacy_level": "public",
            "extra_data": {},
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


class ComputeAlert(Base):
    """算力调度 - 算力告警表"""
    __tablename__ = "compute_alerts"

    id = Column(Integer, primary_key=True, index=True)
    alert_id = Column(String(64), index=True, comment="告警ID")
    type = Column(String(50), default="health", comment="告警类型")
    severity = Column(String(20), default="info", comment="严重级别：info/warning/critical")
    source_id = Column(String(64), default="", comment="关联的算力源ID")
    message = Column(String(255), default="", comment="告警消息")
    details = Column(JSON, default=dict, comment="告警详情（JSON）")
    resolved = Column(Boolean, default=False, comment="是否已解决")
    resolved_at = Column(DateTime, nullable=True, comment="解决时间")
    created_at = Column(DateTime, default=datetime.utcnow, index=True, comment="创建时间")

    def to_dict(self):
        return {
            "id": self.id,
            "alert_id": self.alert_id,
            "type": self.type,
            "severity": self.severity,
            "level": self.severity,
            "title": self.message or "",
            "content": self.message or "",
            "message": self.message or "",
            "source_type": self.type,
            "source_key": self.source_id,
            "source_id": self.source_id,
            "status": "resolved" if self.resolved else "active",
            "resolved": self.resolved,
            "details": self.details or {},
            "acknowledged_at": None,
            "acknowledged_by": "",
            "resolved_at": self.resolved_at.isoformat() if self.resolved_at else None,
            "resolved_by": "system",
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


class ComputeQuota(Base):
    """算力调度 - 额度配置表"""
    __tablename__ = "compute_quotas"

    id = Column(Integer, primary_key=True, index=True)
    scope = Column(String(20), index=True, comment="范围：global/source/module/skill")
    scope_key = Column(String(64), index=True, comment="范围对应的 key")
    period = Column(String(20), default="daily", comment="周期：daily/weekly/monthly/total")
    limit_amount = Column(Float, default=0.0, comment="限制额度")
    used_amount = Column(Float, default=0.0, comment="已使用额度")
    alert_threshold = Column(Float, default=80.0, comment="告警阈值（百分比）")
    action_on_exceed = Column(String(30), default="alert_only", comment="超额动作：alert_only/reject/throttle")
    reset_at = Column(DateTime, nullable=True, comment="重置时间")
    created_at = Column(DateTime, default=datetime.utcnow, comment="创建时间")

    def to_dict(self):
        usage_percent = 0.0
        if self.limit_amount and self.limit_amount > 0:
            usage_percent = round(self.used_amount / self.limit_amount * 100, 2)
        quota_id = f"{self.scope}_{self.scope_key}_{self.period}"
        return {
            "id": self.id,
            "quota_id": quota_id,
            "scope": self.scope,
            "scope_key": self.scope_key,
            "period": self.period,
            "limit_type": "cost",
            "limit_value": self.limit_amount,
            "limit_amount": self.limit_amount,
            "used_value": round(self.used_amount, 6),
            "used_amount": round(self.used_amount, 6),
            "usage_percent": usage_percent,
            "remaining": round(max(0, self.limit_amount - self.used_amount), 6),
            "alert_threshold": self.alert_threshold / 100.0,
            "alert_threshold_pct": self.alert_threshold,
            "action_on_exceed": self.action_on_exceed,
            "status": "active",
            "is_alerting": usage_percent >= self.alert_threshold,
            "reset_at": self.reset_at.isoformat() if self.reset_at else None,
            "last_reset_at": None,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


class ComputeSkillBinding(Base):
    """算力调度 - 技能权限绑定表"""
    __tablename__ = "compute_skill_bindings"

    id = Column(Integer, primary_key=True, index=True)
    skill_id = Column(String(64), unique=True, index=True, comment="技能ID")
    skill_name = Column(String(100), comment="技能名称")
    allowed_groups = Column(JSON, default=list, comment="允许的分组ID列表")
    allowed_sources = Column(JSON, default=list, comment="允许的算力源ID列表")
    quota_daily = Column(Float, default=0.0, comment="日额度（元），0表示不限制")
    quota_monthly = Column(Float, default=0.0, comment="月额度（元），0表示不限制")
    rate_limit_per_min = Column(Integer, default=0, comment="每分钟调用限制，0表示不限制")
    priority = Column(Integer, default=50, comment="调用优先级，数值越小越优先")
    created_at = Column(DateTime, default=datetime.utcnow, comment="创建时间")
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, comment="更新时间")

    def to_dict(self):
        return {
            "id": self.id,
            "skill_id": self.skill_id,
            "skill_name": self.skill_name,
            "description": "",
            "allowed_source_ids": self.allowed_sources or [],
            "allowed_sources": self.allowed_sources or [],
            "denied_source_ids": [],
            "allowed_groups": self.allowed_groups or [],
            "max_tokens_per_request": 0,
            "daily_token_quota": 0,
            "quota_daily": self.quota_daily or 0.0,
            "quota_monthly": self.quota_monthly or 0.0,
            "rate_limit_per_min": self.rate_limit_per_min or 0,
            "priority_bonus": 0.0,
            "priority": self.priority,
            "status": "active",
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


class ComputeConfigBackup(Base):
    """算力调度 - 配置备份表"""
    __tablename__ = "compute_config_backups"

    id = Column(Integer, primary_key=True, index=True)
    backup_id = Column(String(64), unique=True, index=True, comment="备份ID")
    name = Column(String(200), default="", comment="备份名称")
    description = Column(Text, default="", comment="备份描述")
    backup_type = Column(String(20), default="manual", comment="类型：manual/auto")
    config_data = Column(JSON, default=dict, comment="备份的配置数据（JSON）")
    item_count = Column(Integer, default=0, comment="配置项数量")
    created_by = Column(String(50), default="system", comment="创建人")
    created_at = Column(DateTime, default=datetime.utcnow, index=True, comment="创建时间")

    def to_dict(self):
        return {
            "id": self.id,
            "backup_id": self.backup_id,
            "name": self.name,
            "description": self.description,
            "backup_type": self.backup_type,
            "item_count": self.item_count,
            "created_by": self.created_by,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }
