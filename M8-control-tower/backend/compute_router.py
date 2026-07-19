"""
算力调度中台 - 路由引擎
提供算力源路由决策、故障转移、熔断、限流、离线降级等核心功能

兼容第一部分表结构：
- ComputeSource: type(不是deployment_type), api_key_encrypted, latency_avg, models, health_last_check, config
- ComputeKeyGroup: routing_strategy, default_source, 无status字段
- ComputeModelBinding: group_id(不是key_group_id), fallback_model_key, max_tokens
- ComputeSkillBinding: allowed_sources(不是allowed_source_ids), quota_daily/monthly, rate_limit_per_min
- ComputeCallLog: call_id(不是log_id), error_code, 无failover_count等
- ComputeQuota: scope/scope_key/period, limit_amount/used_amount, reset_at, action_on_exceed, 无quota_id
- ComputeRoutingPolicy: mode, default_strategy, config, vram_*, network_latency_threshold
- ComputeAlert: type, severity, resolved, details
"""

import time
import uuid
import threading
import asyncio
from collections import deque
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Any, Tuple
from datetime import datetime, timedelta
from enum import Enum


# ============================================================
# 数据类定义
# ============================================================

class RouteStatus(str, Enum):
    """路由结果状态"""
    SUCCESS = "success"
    NO_AVAILABLE = "no_available"
    RATE_LIMITED = "rate_limited"
    QUOTA_EXCEEDED = "quota_exceeded"
    CIRCUIT_OPEN = "circuit_open"
    SKILL_DENIED = "skill_denied"


class CircuitState(str, Enum):
    """熔断器状态"""
    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


@dataclass
class RouteResult:
    """路由决策结果"""
    status: RouteStatus = RouteStatus.SUCCESS
    source_id: Optional[str] = None
    source_name: Optional[str] = None
    model_key: str = ""
    score: float = 0.0
    latency_ms: float = 0.0
    cost_estimate: float = 0.0
    quality_score: float = 0.0
    failover_list: List[Dict[str, Any]] = field(default_factory=list)
    reason: str = ""
    route_id: str = ""
    policy_id: str = ""
    created_at: float = 0.0

    def __post_init__(self):
        if not self.route_id:
            self.route_id = str(uuid.uuid4())
        if not self.created_at:
            self.created_at = time.time()


@dataclass
class CircuitBreaker:
    """熔断器 - 每个算力源一个"""
    source_id: str
    state: CircuitState = CircuitState.CLOSED
    failure_count: int = 0
    success_count: int = 0
    total_count: int = 0
    last_failure_time: float = 0.0
    last_state_change: float = 0.0
    open_time: float = 0.0
    half_open_probe_count: int = 0
    # 滑动窗口：存储 (timestamp, is_success)
    window: deque = field(default_factory=lambda: deque())
    window_seconds: int = 60
    error_threshold: float = 0.5
    cooldown_seconds: int = 30
    half_open_probes: int = 3
    lock: threading.Lock = field(default_factory=threading.Lock)

    def record_result(self, success: bool):
        """记录调用结果"""
        now = time.time()
        with self.lock:
            self.window.append((now, success))
            self.total_count += 1
            if not success:
                self.failure_count += 1
                self.last_failure_time = now
            else:
                self.success_count += 1

            # 清理过期窗口数据
            cutoff = now - self.window_seconds
            while self.window and self.window[0][0] < cutoff:
                self.window.popleft()

            # 状态转换检查
            self._check_state_transition(now, success)

    def _check_state_transition(self, now: float, success: bool):
        """检查状态转换（调用方需持有锁）"""
        if self.state == CircuitState.CLOSED:
            # 检查是否需要打开熔断器
            error_rate = self._get_error_rate_locked()
            if len(self.window) >= 5 and error_rate >= self.error_threshold:
                self.state = CircuitState.OPEN
                self.open_time = now
                self.last_state_change = now
                self.half_open_probe_count = 0

        elif self.state == CircuitState.OPEN:
            # 检查冷却是否结束
            if now - self.open_time >= self.cooldown_seconds:
                self.state = CircuitState.HALF_OPEN
                self.last_state_change = now
                self.half_open_probe_count = 0

        elif self.state == CircuitState.HALF_OPEN:
            if not success:
                # 半开探测失败，重新打开
                self.state = CircuitState.OPEN
                self.open_time = now
                self.last_state_change = now
                self.half_open_probe_count = 0
            else:
                self.half_open_probe_count += 1
                if self.half_open_probe_count >= self.half_open_probes:
                    # 探测成功次数达标，关闭熔断器
                    self.state = CircuitState.CLOSED
                    self.last_state_change = now
                    self.window.clear()
                    self.failure_count = 0
                    self.success_count = 0

    def _get_error_rate_locked(self) -> float:
        """计算错误率（调用方需持有锁）"""
        if not self.window:
            return 0.0
        failures = sum(1 for _, s in self.window if not s)
        return failures / len(self.window)

    def can_allow_request(self) -> bool:
        """检查是否允许请求通过"""
        now = time.time()
        with self.lock:
            if self.state == CircuitState.CLOSED:
                return True
            elif self.state == CircuitState.OPEN:
                # 检查冷却是否结束
                if now - self.open_time >= self.cooldown_seconds:
                    self.state = CircuitState.HALF_OPEN
                    self.last_state_change = now
                    self.half_open_probe_count = 0
                    return True
                return False
            elif self.state == CircuitState.HALF_OPEN:
                return True
        return False

    def get_error_rate(self) -> float:
        """获取当前错误率"""
        with self.lock:
            return self._get_error_rate_locked()

    def reset(self):
        """重置熔断器"""
        with self.lock:
            self.state = CircuitState.CLOSED
            self.failure_count = 0
            self.success_count = 0
            self.total_count = 0
            self.window.clear()
            self.half_open_probe_count = 0
            self.last_state_change = time.time()

    def get_stats(self) -> Dict[str, Any]:
        """获取熔断器状态"""
        with self.lock:
            return {
                "source_id": self.source_id,
                "state": self.state.value,
                "failure_count": self.failure_count,
                "success_count": self.success_count,
                "total_count": self.total_count,
                "error_rate": round(self._get_error_rate_locked(), 4),
                "window_size": len(self.window),
                "open_time": self.open_time,
                "cooldown_remaining": max(0, self.cooldown_seconds - (time.time() - self.open_time))
                if self.state == CircuitState.OPEN else 0,
                "half_open_probe_count": self.half_open_probe_count,
                "last_state_change": self.last_state_change,
            }


@dataclass
class RateLimiter:
    """令牌桶限流器"""
    rate_per_minute: int = 0  # 0 表示不限流
    tokens: float = 0.0
    capacity: float = 0.0
    last_refill_time: float = 0.0
    lock: threading.Lock = field(default_factory=threading.Lock)

    def __post_init__(self):
        if self.rate_per_minute > 0:
            self.capacity = float(self.rate_per_minute)
            self.tokens = self.capacity
        self.last_refill_time = time.time()

    def _refill(self):
        """补充令牌（调用方需持有锁）"""
        if self.rate_per_minute <= 0:
            return
        now = time.time()
        elapsed = now - self.last_refill_time
        if elapsed > 0:
            refill_amount = (elapsed / 60.0) * self.rate_per_minute
            self.tokens = min(self.capacity, self.tokens + refill_amount)
            self.last_refill_time = now

    def try_acquire(self, tokens_needed: float = 1.0) -> bool:
        """尝试获取令牌"""
        with self.lock:
            if self.rate_per_minute <= 0:
                return True
            self._refill()
            if self.tokens >= tokens_needed:
                self.tokens -= tokens_needed
                return True
            return False

    def get_available_tokens(self) -> float:
        """获取当前可用令牌数"""
        with self.lock:
            self._refill()
            return round(self.tokens, 2)

    def reset(self):
        """重置限流器"""
        with self.lock:
            if self.rate_per_minute > 0:
                self.tokens = self.capacity
            self.last_refill_time = time.time()

    def get_stats(self) -> Dict[str, Any]:
        """获取限流状态"""
        with self.lock:
            self._refill()
            return {
                "rate_per_minute": self.rate_per_minute,
                "available_tokens": round(self.tokens, 2),
                "capacity": self.capacity,
                "is_limited": self.rate_per_minute > 0 and self.tokens < 1.0,
            }


# ============================================================
# 主路由引擎类
# ============================================================

class ComputeRouter:
    """
    算力路由引擎 - 单例模式
    提供路由决策、故障转移、熔断、限流、离线降级等功能
    """

    _instance = None
    _instance_lock = threading.Lock()

    def __new__(cls):
        if cls._instance is None:
            with cls._instance_lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return
        self._initialized = True

        # 线程安全锁
        self._lock = threading.RLock()

        # 内存缓存（标准化后的内部数据结构）
        self._sources: Dict[str, Dict[str, Any]] = {}
        self._key_groups: Dict[str, Dict[str, Any]] = {}
        self._model_bindings: Dict[str, Dict[str, Any]] = {}
        self._policies: Dict[str, Dict[str, Any]] = {}
        self._skill_bindings: Dict[str, Dict[str, Any]] = {}
        self._quotas: Dict[str, Dict[str, Any]] = {}

        # 熔断器映射：source_id -> CircuitBreaker
        self._circuit_breakers: Dict[str, CircuitBreaker] = {}

        # 限流器映射
        self._global_rate_limiter: Optional[RateLimiter] = None
        self._source_rate_limiters: Dict[str, RateLimiter] = {}
        self._module_rate_limiters: Dict[str, RateLimiter] = {}
        self._skill_rate_limiters: Dict[str, RateLimiter] = {}

        # 监控数据缓存
        self._cache: Dict[str, Tuple[float, Any]] = {}
        self._cache_ttl = 5  # 5秒过期

        # 离线状态
        self._is_offline = False
        self._offline_since: float = 0.0
        self._replay_queue: deque = deque()

        # 后台线程控制
        self._stop_event = threading.Event()
        self._health_thread: Optional[threading.Thread] = None
        self._quota_reset_thread: Optional[threading.Thread] = None

        # 统计数据
        self._call_stats: Dict[str, Dict[str, Any]] = {}

        # 数据库会话工厂
        self._db_session_factory = None

    def initialize(self, db_session_factory=None):
        """
        初始化路由引擎
        从数据库加载配置，启动后台线程
        """
        if db_session_factory:
            self._db_session_factory = db_session_factory

        # 从数据库加载配置
        self._load_config_from_db()

        # 初始化熔断器
        self._init_circuit_breakers()

        # 初始化限流器
        self._init_rate_limiters()

        # 启动健康检查线程
        self._start_health_check_thread()

        # 启动额度重置定时任务
        self._start_quota_reset_thread()

        # 初始化调用统计
        self._init_call_stats()

    def _get_db(self):
        """获取数据库会话"""
        if self._db_session_factory:
            return self._db_session_factory()
        try:
            from .models import SessionLocal
            return SessionLocal()
        except ImportError:
            from models import SessionLocal
            return SessionLocal()

    def _load_config_from_db(self):
        """从数据库加载所有配置（适配第一部分表结构）"""
        try:
            db = self._get_db()
            try:
                try:
                    from .models import (
                        ComputeSource, ComputeKeyGroup, ComputeModelBinding,
                        ComputeRoutingPolicy, ComputeSkillBinding, ComputeQuota,
                    )
                except ImportError:
                    from models import (
                        ComputeSource, ComputeKeyGroup, ComputeModelBinding,
                        ComputeRoutingPolicy, ComputeSkillBinding, ComputeQuota,
                    )

                with self._lock:
                    # 加载算力源 - 适配第一部分字段
                    self._sources = {}
                    for s in db.query(ComputeSource).all():
                        self._sources[s.source_id] = self._source_to_dict(s)

                    # 加载密钥分组
                    self._key_groups = {}
                    for g in db.query(ComputeKeyGroup).all():
                        self._key_groups[g.group_id] = self._group_to_dict(g)

                    # 加载模型绑定
                    self._model_bindings = {}
                    for m in db.query(ComputeModelBinding).all():
                        self._model_bindings[m.model_key] = self._binding_to_dict(m)

                    # 加载路由策略
                    self._policies = {}
                    for p in db.query(ComputeRoutingPolicy).all():
                        self._policies[p.policy_id] = self._policy_to_dict(p)

                    # 加载技能绑定
                    self._skill_bindings = {}
                    for sk in db.query(ComputeSkillBinding).all():
                        self._skill_bindings[sk.skill_id] = self._skill_to_dict(sk)

                    # 加载额度配置 - 生成 quota_id
                    self._quotas = {}
                    for q in db.query(ComputeQuota).all():
                        # 用 scope+scope_key+period 生成唯一 key
                        qid = f"{q.scope}_{q.scope_key}_{q.period}"
                        self._quotas[qid] = self._quota_to_dict(q, qid)
            finally:
                db.close()
        except Exception as e:
            import logging
            logger = logging.getLogger("m8.compute_router")
            logger.warning(f"从数据库加载配置失败: {e}")

    def _source_to_dict(self, source) -> Dict[str, Any]:
        """算力源 ORM 转内部标准字典（适配第一部分字段）"""
        # 第一部分字段：type, api_key_encrypted, api_key_masked, latency_avg,
        # models, health_last_check, config, priority(越小越优先), weight(int)
        # 内部标准字段统一为更完整的格式
        config = getattr(source, 'config', {}) or {}
        models = getattr(source, 'models', []) or []
        capabilities = getattr(source, 'capabilities', []) or []

        # 从 config 中提取额外配置
        quality_score = config.get('quality_score', 0.8)
        privacy_level = config.get('privacy_level', 'public')
        rate_limit_per_minute = config.get('rate_limit_per_minute', 0)
        rate_limit_per_day = config.get('rate_limit_per_day', 0)
        auto_failover = config.get('auto_failover', True)
        region = config.get('region', '')
        current_concurrent = config.get('current_concurrent', 0)

        # type 映射到 deployment_type
        deployment_type = getattr(source, 'type', 'cloud')
        if deployment_type == 'local':
            privacy_level = 'top_secret'
        elif deployment_type == 'private':
            privacy_level = 'confidential'

        return {
            "source_id": source.source_id,
            "name": source.name,
            "provider": source.provider,
            "base_url": source.base_url,
            "model_name": models[0] if models else "",
            "models": models,
            "deployment_type": deployment_type,
            "priority": getattr(source, 'priority', 100),
            "weight": float(getattr(source, 'weight', 100)) / 100.0,  # 转为 0-1+ 的权重
            "status": "active" if source.status == "active" else "disabled",
            "health_status": source.health_status,
            "latency_ms": getattr(source, 'latency_avg', 0.0),
            "success_rate": getattr(source, 'success_rate', 1.0),
            "max_concurrent": getattr(source, 'max_concurrent', 10),
            "current_concurrent": current_concurrent,
            "cost_per_1k_input": source.cost_per_1k_input,
            "cost_per_1k_output": source.cost_per_1k_output,
            "quality_score": quality_score,
            "privacy_level": privacy_level,
            "capabilities": capabilities,
            "region": region,
            "rate_limit_per_minute": rate_limit_per_minute,
            "rate_limit_per_day": rate_limit_per_day,
            "auto_failover": auto_failover,
            "extra_config": config,
            "api_key_masked": getattr(source, 'api_key_masked', ''),
            "timeout": getattr(source, 'timeout', 60),
        }

    def _group_to_dict(self, group) -> Dict[str, Any]:
        """分组 ORM 转内部标准字典"""
        return {
            "group_id": group.group_id,
            "name": group.name,
            "description": getattr(group, 'description', ''),
            "status": "active",  # 第一部分没有 status 字段，默认 active
            "source_ids": group.source_ids or [],
            "default_source": getattr(group, 'default_source', ''),
            "load_balance_strategy": getattr(group, 'routing_strategy', 'auto'),
        }

    def _binding_to_dict(self, binding) -> Dict[str, Any]:
        """模型绑定 ORM 转内部标准字典"""
        return {
            "model_key": binding.model_key,
            "model_name": binding.model_name,
            "purpose": binding.purpose,
            "key_group_id": binding.group_id,  # 第一部分叫 group_id
            "fallback_group_id": "",  # 第一部分没有 fallback_group_id，用 fallback_model_key
            "fallback_model_key": getattr(binding, 'fallback_model_key', ''),
            "default_policy_id": "default",  # 第一部分没有 default_policy_id
            "max_input_tokens": getattr(binding, 'max_tokens', 4096),
            "max_output_tokens": getattr(binding, 'max_tokens', 4096),
            "status": "active",  # 第一部分没有 status 字段
            "temperature_default": getattr(binding, 'temperature_default', 0.7),
        }

    def _policy_to_dict(self, policy) -> Dict[str, Any]:
        """策略 ORM 转内部标准字典（适配第一部分）"""
        config = getattr(policy, 'config', {}) or {}
        return {
            "policy_id": policy.policy_id,
            "name": policy.name,
            "is_active": getattr(policy, 'mode', 'auto') == 'auto',  # 用 mode 表示是否激活
            "mode": getattr(policy, 'mode', 'auto'),
            "default_strategy": getattr(policy, 'default_strategy', 'latency_first'),
            "latency_weight": policy.latency_weight,
            "cost_weight": policy.cost_weight,
            "quality_weight": policy.quality_weight,
            "privacy_weight": policy.privacy_weight,
            "circuit_breaker_enabled": policy.circuit_breaker_enabled,
            "cb_error_threshold": config.get('cb_error_threshold', 0.5),
            "cb_window_seconds": config.get('cb_window_seconds', 60),
            "cb_cooldown_seconds": config.get('cb_cooldown_seconds', 30),
            "cb_half_open_probes": config.get('cb_half_open_probes', 3),
            "rate_limit_enabled": policy.rate_limit_enabled,
            "global_rate_per_minute": config.get('global_rate_per_minute', 1000),
            "auto_failover": policy.auto_failover,
            "max_failover_attempts": config.get('max_failover_attempts', 3),
            "offline_degradation": policy.offline_fallback_enabled,
            "vram_safe_threshold": getattr(policy, 'vram_safe_threshold', 70.0),
            "vram_critical_threshold": getattr(policy, 'vram_critical_threshold', 90.0),
            "network_latency_threshold": getattr(policy, 'network_latency_threshold', 500),
            "extra_config": config,
        }

    def _skill_to_dict(self, skill) -> Dict[str, Any]:
        """技能绑定 ORM 转内部标准字典（适配第一部分）"""
        return {
            "skill_id": skill.skill_id,
            "skill_name": skill.skill_name,
            "description": "",
            "allowed_source_ids": getattr(skill, 'allowed_sources', []) or [],
            "denied_source_ids": [],
            "allowed_groups": getattr(skill, 'allowed_groups', []) or [],
            "max_tokens_per_request": 0,
            "daily_token_quota": 0,
            "quota_daily": getattr(skill, 'quota_daily', 0.0),
            "quota_monthly": getattr(skill, 'quota_monthly', 0.0),
            "rate_limit_per_min": getattr(skill, 'rate_limit_per_min', 0),
            "priority_bonus": 0.0,
            "priority": getattr(skill, 'priority', 50),
            "status": "active",
        }

    def _quota_to_dict(self, quota, quota_id: str) -> Dict[str, Any]:
        """额度 ORM 转内部标准字典（适配第一部分）"""
        return {
            "quota_id": quota_id,
            "scope": quota.scope,
            "scope_key": quota.scope_key,
            "period": quota.period,
            "limit_type": "cost",  # 第一部分额度都是成本型
            "limit_value": quota.limit_amount,
            "used_value": quota.used_amount,
            "alert_threshold": quota.alert_threshold / 100.0,  # 百分比转小数
            "status": "active",
            "action_on_exceed": getattr(quota, 'action_on_exceed', 'alert_only'),
            "reset_at": quota.reset_at,
            "last_reset_at": None,
        }

    def _init_circuit_breakers(self):
        """初始化所有算力源的熔断器"""
        with self._lock:
            active_policy = self._get_active_policy()
            for source_id in self._sources:
                if source_id not in self._circuit_breakers:
                    cb = CircuitBreaker(
                        source_id=source_id,
                        window_seconds=active_policy.get("cb_window_seconds", 60) if active_policy else 60,
                        error_threshold=active_policy.get("cb_error_threshold", 0.5) if active_policy else 0.5,
                        cooldown_seconds=active_policy.get("cb_cooldown_seconds", 30) if active_policy else 30,
                        half_open_probes=active_policy.get("cb_half_open_probes", 3) if active_policy else 3,
                    )
                    self._circuit_breakers[source_id] = cb

    def _init_rate_limiters(self):
        """初始化限流器"""
        with self._lock:
            active_policy = self._get_active_policy()
            # 全局限流器
            rate = active_policy.get("global_rate_per_minute", 1000) if active_policy else 1000
            self._global_rate_limiter = RateLimiter(rate_per_minute=rate)

            # 按算力源限流
            for source_id, source in self._sources.items():
                src_rate = source.get("rate_limit_per_minute", 0)
                self._source_rate_limiters[source_id] = RateLimiter(rate_per_minute=src_rate)

            # 按技能限流
            for skill_id, skill in self._skill_bindings.items():
                skill_rate = skill.get("rate_limit_per_min", 0)
                if skill_rate > 0:
                    self._skill_rate_limiters[skill_id] = RateLimiter(rate_per_minute=skill_rate)

    def _init_call_stats(self):
        """初始化调用统计"""
        with self._lock:
            for source_id in self._sources:
                if source_id not in self._call_stats:
                    self._call_stats[source_id] = {
                        "total_calls": 0,
                        "success_calls": 0,
                        "failed_calls": 0,
                        "total_latency_ms": 0.0,
                        "total_cost": 0.0,
                        "total_tokens": 0,
                        "today_calls": 0,
                        "today_success": 0,
                        "today_failed": 0,
                        "today_cost": 0.0,
                        "today_tokens": 0,
                        "last_reset_date": datetime.utcnow().date().isoformat(),
                    }

    def _get_active_policy(self) -> Optional[Dict[str, Any]]:
        """获取当前激活的策略（调用方需持有锁）"""
        # 第一部分用 mode=='auto' 表示激活，或者找第一个
        for policy in self._policies.values():
            if policy.get("is_active"):
                return policy
        if self._policies:
            return list(self._policies.values())[0]
        return None

    # ============================================================
    # 路由决策核心方法
    # ============================================================

    async def route(
        self,
        model_key: str = "default-chat",
        purpose: str = "chat",
        caller_module: str = "m8",
        caller_skill: str = None,
        input_tokens: int = 0,
        priority: str = "normal",
        privacy_level: str = "public",
        prefer_local: bool = False,
        exclude_sources: list = None,
    ) -> RouteResult:
        """
        路由决策 - 选择最优算力源
        """
        with self._lock:
            # 1. 获取模型绑定
            binding = self._model_bindings.get(model_key)
            if not binding:
                return RouteResult(
                    status=RouteStatus.NO_AVAILABLE,
                    model_key=model_key,
                    reason=f"模型 {model_key} 不存在",
                )

            # 2. 获取激活的策略
            policy = self._get_active_policy()
            if not policy:
                policy = {
                    "latency_weight": 0.4,
                    "cost_weight": 0.3,
                    "quality_weight": 0.2,
                    "privacy_weight": 0.1,
                    "circuit_breaker_enabled": True,
                    "rate_limit_enabled": True,
                    "auto_failover": True,
                    "max_failover_attempts": 3,
                    "offline_degradation": True,
                }

            policy_id = policy.get("policy_id", "default")

            # 3. 获取主分组的所有算力源
            source_ids = []
            group_id = binding.get("key_group_id", "")
            main_group = self._key_groups.get(group_id)
            if main_group:
                source_ids.extend(main_group.get("source_ids", []))

            # 备用：如果有 fallback_model_key，也加入
            fallback_model = binding.get("fallback_model_key", "")
            if fallback_model and fallback_model != model_key:
                fallback_binding = self._model_bindings.get(fallback_model)
                if fallback_binding:
                    fallback_group = self._key_groups.get(fallback_binding.get("key_group_id", ""))
                    if fallback_group:
                        for sid in fallback_group.get("source_ids", []):
                            if sid not in source_ids:
                                source_ids.append(sid)

            if not source_ids:
                return RouteResult(
                    status=RouteStatus.NO_AVAILABLE,
                    model_key=model_key,
                    reason="没有可用的算力源分组",
                    policy_id=policy_id,
                )

            # 4. 离线降级：只保留本地算力源
            if self._is_offline and policy.get("offline_degradation"):
                source_ids = [
                    sid for sid in source_ids
                    if self._sources.get(sid, {}).get("deployment_type") == "local"
                ]
                if not source_ids:
                    return RouteResult(
                        status=RouteStatus.NO_AVAILABLE,
                        model_key=model_key,
                        reason="离线模式下无本地算力源可用",
                        policy_id=policy_id,
                    )

            # 5. 过滤不可用的算力源
            candidates = []
            exclude_set = set(exclude_sources or [])
            for sid in source_ids:
                source = self._sources.get(sid)
                if not source:
                    continue
                # 排除指定的源（用于故障转移）
                if sid in exclude_set:
                    continue
                # 检查状态
                if source["status"] != "active":
                    continue
                # 检查健康状态
                if source["health_status"] in ("unreachable", "unknown"):
                    # unknown 也排除？如果所有源都是 unknown 就麻烦了，这里保留 degraded 和 healthy
                    if source["health_status"] == "unreachable":
                        continue
                # 检查能力匹配
                if purpose and source.get("capabilities"):
                    if purpose not in source["capabilities"]:
                        continue

                # 6. 检查熔断器
                if policy.get("circuit_breaker_enabled"):
                    cb = self._circuit_breakers.get(sid)
                    if cb and not cb.can_allow_request():
                        continue

                # 7. 检查技能权限
                if caller_skill and not self._check_skill_permission(caller_skill, sid):
                    continue

                candidates.append(source)

            if not candidates:
                return RouteResult(
                    status=RouteStatus.NO_AVAILABLE,
                    model_key=model_key,
                    reason="所有算力源均不可用（健康/熔断/权限）",
                    policy_id=policy_id,
                )

            # 8. 检查全局限流
            if policy.get("rate_limit_enabled") and self._global_rate_limiter:
                if not self._global_rate_limiter.try_acquire():
                    return RouteResult(
                        status=RouteStatus.RATE_LIMITED,
                        model_key=model_key,
                        reason="全局请求频率超限",
                        policy_id=policy_id,
                    )

            # 9. 检查技能级限流
            if caller_skill and caller_skill in self._skill_rate_limiters:
                skill_limiter = self._skill_rate_limiters[caller_skill]
                if not skill_limiter.try_acquire():
                    # 退还全局限流令牌（简化：不退还）
                    return RouteResult(
                        status=RouteStatus.RATE_LIMITED,
                        model_key=model_key,
                        reason=f"技能 {caller_skill} 调用频率超限",
                        policy_id=policy_id,
                    )

            # 10. 检查额度（成本型额度）
            quota_result = self._check_quotas(caller_module, caller_skill, model_key)
            if quota_result:
                return RouteResult(
                    status=RouteStatus.QUOTA_EXCEEDED,
                    model_key=model_key,
                    reason=quota_result,
                    policy_id=policy_id,
                )

            # 11. 对候选算力源进行评分排序
            scored_sources = []
            for source in candidates:
                # 检查算力源级别的限流
                src_limiter = self._source_rate_limiters.get(source["source_id"])
                if src_limiter and not src_limiter.try_acquire():
                    continue

                score = self._calculate_score(source, policy, privacy_level, prefer_local, caller_skill)
                scored_sources.append((source, score))

            if not scored_sources:
                return RouteResult(
                    status=RouteStatus.RATE_LIMITED,
                    model_key=model_key,
                    reason="所有算力源均被限流",
                    policy_id=policy_id,
                )

            # 按得分降序排列
            scored_sources.sort(key=lambda x: x[1], reverse=True)

            # 12. 构建结果
            best_source, best_score = scored_sources[0]

            # 计算备选列表
            failover_list = []
            if policy.get("auto_failover", True):
                for src, sc in scored_sources[1:]:
                    if src.get("auto_failover", True):
                        failover_list.append({
                            "source_id": src["source_id"],
                            "source_name": src["name"],
                            "score": round(sc, 4),
                            "latency_ms": src["latency_ms"],
                            "deployment_type": src["deployment_type"],
                        })

            # 估算成本
            cost_estimate = self._estimate_cost(best_source, input_tokens)

            result = RouteResult(
                status=RouteStatus.SUCCESS,
                source_id=best_source["source_id"],
                source_name=best_source["name"],
                model_key=model_key,
                score=round(best_score, 4),
                latency_ms=best_source["latency_ms"],
                cost_estimate=round(cost_estimate, 6),
                quality_score=best_source["quality_score"],
                failover_list=failover_list,
                reason="",
                policy_id=policy_id,
            )

            return result

    def _calculate_score(
        self,
        source: Dict[str, Any],
        policy: Dict[str, Any],
        privacy_level: str,
        prefer_local: bool,
        caller_skill: str = None,
    ) -> float:
        """计算算力源综合得分（0-100分）"""
        latency_score = self._calc_latency_score(source["latency_ms"])
        cost_score = self._calc_cost_score(source)
        quality_score = source["quality_score"] * 100
        privacy_score = self._calc_privacy_score(source["privacy_level"], privacy_level, prefer_local)

        # 健康状态加分
        health_bonus = 0.0
        if source["health_status"] == "healthy":
            health_bonus = 10
        elif source["health_status"] == "degraded":
            health_bonus = 5

        # 成功率加成
        success_bonus = source["success_rate"] * 10

        # 优先级加成（注意：第一部分 priority 越小越优先，这里转换成越大越优先）
        priority_val = source.get("priority", 100)
        priority_bonus = (100 - priority_val) * 0.1  # 优先级 1 的比 100 的多 9.9 分

        # 技能优先级加成
        skill_bonus = 0.0
        if caller_skill:
            skill = self._skill_bindings.get(caller_skill)
            if skill:
                # priority 值越小越优先
                skill_priority = skill.get("priority", 50)
                skill_bonus = (50 - skill_priority) * 0.1

        # 权重
        lw = policy.get("latency_weight", 0.4)
        cw = policy.get("cost_weight", 0.3)
        qw = policy.get("quality_weight", 0.2)
        pw = policy.get("privacy_weight", 0.1)

        # 综合得分
        total_weight = lw + cw + qw + pw
        if total_weight > 0:
            weighted_score = (
                latency_score * lw +
                cost_score * cw +
                quality_score * qw +
                privacy_score * pw
            ) / total_weight
        else:
            weighted_score = (latency_score + cost_score + quality_score + privacy_score) / 4

        # 加上额外加分
        total_score = weighted_score + health_bonus + success_bonus + priority_bonus + skill_bonus

        # 乘以负载权重
        total_score *= source.get("weight", 1.0)

        return total_score

    def _calc_latency_score(self, latency_ms: float) -> float:
        """计算延迟得分：越快分越高（0-100）"""
        if latency_ms <= 0:
            return 100.0
        if latency_ms <= 100:
            return 100.0
        elif latency_ms >= 5000:
            return 0.0
        else:
            return 100.0 * (1 - (latency_ms - 100) / 4900)

    def _calc_cost_score(self, source: Dict[str, Any]) -> float:
        """计算成本得分：越便宜分越高（0-100）"""
        avg_cost = (source["cost_per_1k_input"] + source["cost_per_1k_output"]) / 2
        if avg_cost <= 0:
            return 100.0
        if avg_cost <= 0.001:
            return 100.0
        elif avg_cost >= 0.1:
            return 10.0
        else:
            return 100.0 * (1 - (avg_cost - 0.001) / 0.099)

    def _calc_privacy_score(self, source_privacy: str, required_privacy: str, prefer_local: bool) -> float:
        """计算隐私得分"""
        privacy_order = {"public": 1, "internal": 2, "confidential": 3, "top_secret": 4}
        source_level = privacy_order.get(source_privacy, 1)
        required_level = privacy_order.get(required_privacy, 1)

        if source_level >= required_level:
            base_score = 80.0 + (source_level - required_level) * 5
        else:
            base_score = max(0, 40.0 - (required_level - source_level) * 20)

        if prefer_local and source_privacy == "top_secret":
            base_score += 15

        return min(100.0, base_score)

    def _check_skill_permission(self, skill_id: str, source_id: str) -> bool:
        """检查技能是否有权限使用某个算力源"""
        skill = self._skill_bindings.get(skill_id)
        if not skill:
            return True  # 没有技能绑定限制，默认允许

        # 检查允许的分组
        allowed_groups = skill.get("allowed_groups", [])
        if allowed_groups:
            # 检查源是否在任意允许的分组中
            source_in_allowed_group = False
            for gid in allowed_groups:
                group = self._key_groups.get(gid)
                if group and source_id in group.get("source_ids", []):
                    source_in_allowed_group = True
                    break
            if not source_in_allowed_group:
                # 再检查直接允许的算力源
                allowed_sources = skill.get("allowed_source_ids", [])
                if allowed_sources and source_id not in allowed_sources:
                    return False

        # 检查允许的算力源
        allowed_sources = skill.get("allowed_source_ids", [])
        if allowed_sources and source_id not in allowed_sources:
            # 如果有分组限制且已经通过分组检查，则允许
            if not allowed_groups:
                return False

        return True

    def _check_quotas(self, module: str, skill: str, model_key: str) -> Optional[str]:
        """检查额度限制"""
        with self._lock:
            for quota_id, quota in self._quotas.items():
                if quota["status"] != "active":
                    continue
                if quota["limit_value"] <= 0:
                    continue

                scope = quota["scope"]
                scope_key = quota["scope_key"]

                # 检查范围匹配
                if scope == "global":
                    pass
                elif scope == "module" and scope_key != module:
                    continue
                elif scope == "skill" and scope_key != skill:
                    continue
                elif scope == "source":
                    continue  # 源级额度在选源后检查
                elif scope == "group":
                    continue
                elif scope == "model" and scope_key != model_key:
                    continue
                else:
                    continue

                # 检查是否需要重置
                self._check_quota_reset(quota)

                used = quota["used_value"]
                limit = quota["limit_value"]

                # 成本型额度，估算一下（简化处理）
                if quota["limit_type"] == "cost":
                    # 这里只检查是否已经超额
                    if used >= limit:
                        return f"额度不足: {quota_id} 已用 {used:.2f}/{limit:.2f} 元"

            return None

    def _check_quota_reset(self, quota: Dict[str, Any]):
        """检查额度是否需要重置（调用方需持有锁）"""
        period = quota["period"]
        now = datetime.utcnow()
        reset_at = quota.get("reset_at")

        if period == "daily":
            if reset_at and reset_at > now:
                return  # 还没到重置时间
            # 检查是否已经是今天重置过
            last_reset = quota.get("last_reset_at")
            if not last_reset or last_reset.date() != now.date():
                quota["used_value"] = 0.0
                quota["last_reset_at"] = now
                # 设置下次重置时间（明天 0 点）
                tomorrow = now.replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=1)
                quota["reset_at"] = tomorrow
        elif period == "monthly":
            last_reset = quota.get("last_reset_at")
            if not last_reset or last_reset.month != now.month or last_reset.year != now.year:
                quota["used_value"] = 0.0
                quota["last_reset_at"] = now

    def _estimate_cost(self, source: Dict[str, Any], input_tokens: int, output_tokens: int = 0) -> float:
        """估算调用成本"""
        input_cost = (input_tokens / 1000.0) * source["cost_per_1k_input"]
        output_cost = (output_tokens / 1000.0) * source["cost_per_1k_output"]
        return input_cost + output_cost

    # ============================================================
    # 故障转移
    # ============================================================

    async def failover(self, failed_source_id: str, model_key: str, reason: str) -> Optional[RouteResult]:
        """故障转移 - 当主算力源失败时切换到备选"""
        # 记录失败到熔断器
        cb = self._circuit_breakers.get(failed_source_id)
        if cb:
            cb.record_result(False)

        # 更新调用统计
        self._update_call_stats(failed_source_id, success=False, latency_ms=0, cost=0, tokens=0)

        # 重新路由，排除失败的源
        result = await self.route(
            model_key=model_key,
            purpose="chat",
            exclude_sources=[failed_source_id],
        )
        if result.status == RouteStatus.SUCCESS and result.source_id != failed_source_id:
            result.reason = f"故障转移: {reason}"
            return result
        return None

    # ============================================================
    # 调用记录与统计
    # ============================================================

    def record_call(
        self,
        route_result: RouteResult,
        success: bool,
        output_tokens: int = 0,
        latency_ms: float = 0.0,
        error_message: str = "",
    ):
        """记录调用结果，更新统计数据"""
        source_id = route_result.source_id
        if not source_id:
            return

        # 更新熔断器
        cb = self._circuit_breakers.get(source_id)
        if cb:
            cb.record_result(success)

        # 计算实际成本
        cost = 0.0
        source = self._sources.get(source_id)
        if source:
            cost = self._estimate_cost(source, 0, output_tokens)

        # 更新统计
        self._update_call_stats(source_id, success, latency_ms, cost, output_tokens)

        # 更新额度使用量
        self._update_quota_usage(source_id, output_tokens, cost, route_result)

        # 写入数据库
        self._write_call_log(route_result, success, output_tokens, latency_ms, cost, error_message)

    def _update_call_stats(self, source_id: str, success: bool, latency_ms: float, cost: float, tokens: int):
        """更新调用统计（内存）"""
        with self._lock:
            if source_id not in self._call_stats:
                self._call_stats[source_id] = {
                    "total_calls": 0,
                    "success_calls": 0,
                    "failed_calls": 0,
                    "total_latency_ms": 0.0,
                    "total_cost": 0.0,
                    "total_tokens": 0,
                    "today_calls": 0,
                    "today_success": 0,
                    "today_failed": 0,
                    "today_cost": 0.0,
                    "today_tokens": 0,
                    "last_reset_date": datetime.utcnow().date().isoformat(),
                }

            stats = self._call_stats[source_id]
            stats["total_calls"] += 1
            stats["total_latency_ms"] += latency_ms
            stats["total_cost"] += cost
            stats["total_tokens"] += tokens

            if success:
                stats["success_calls"] += 1
            else:
                stats["failed_calls"] += 1

            # 今日统计
            today = datetime.utcnow().date().isoformat()
            if stats["last_reset_date"] != today:
                stats["today_calls"] = 0
                stats["today_success"] = 0
                stats["today_failed"] = 0
                stats["today_cost"] = 0.0
                stats["today_tokens"] = 0
                stats["last_reset_date"] = today

            stats["today_calls"] += 1
            stats["today_cost"] += cost
            stats["today_tokens"] += tokens
            if success:
                stats["today_success"] += 1
            else:
                stats["today_failed"] += 1

            # 更新算力源的实时延迟（滑动平均）
            if source_id in self._sources and latency_ms > 0:
                old_latency = self._sources[source_id]["latency_ms"]
                if old_latency > 0:
                    self._sources[source_id]["latency_ms"] = old_latency * 0.9 + latency_ms * 0.1
                else:
                    self._sources[source_id]["latency_ms"] = latency_ms

                # 更新成功率
                if stats["today_calls"] > 0:
                    self._sources[source_id]["success_rate"] = stats["today_success"] / stats["today_calls"]

    def _update_quota_usage(self, source_id: str, tokens: int, cost: float, route_result: RouteResult):
        """更新额度使用量"""
        with self._lock:
            for quota in self._quotas.values():
                if quota["status"] != "active" or quota["limit_value"] <= 0:
                    continue

                scope = quota["scope"]
                scope_key = quota["scope_key"]

                # 检查范围匹配
                if scope == "global":
                    pass
                elif scope == "source" and scope_key == source_id:
                    pass
                elif scope == "model" and scope_key == route_result.model_key:
                    pass
                else:
                    continue

                # 检查重置
                self._check_quota_reset(quota)

                if quota["limit_type"] == "cost":
                    quota["used_value"] += cost

    def _write_call_log(self, route_result: RouteResult, success: bool, output_tokens: int, latency_ms: float, cost: float, error_message: str):
        """写入调用日志到数据库（适配第一部分表结构）"""
        try:
            db = self._get_db()
            try:
                try:
                    from .models import ComputeCallLog
                except ImportError:
                    from models import ComputeCallLog

                status = "success" if success else "failed"
                if not success and error_message:
                    if "rate" in error_message.lower():
                        status = "rate_limited"
                    elif "quota" in error_message.lower():
                        status = "failed"

                log = ComputeCallLog(
                    call_id=str(uuid.uuid4()),  # 第一部分用 call_id
                    source_id=route_result.source_id or "",
                    model_key=route_result.model_key,
                    caller_module="m8",
                    caller_skill="",
                    input_tokens=0,
                    output_tokens=output_tokens,
                    cost=cost,
                    latency_ms=int(latency_ms),
                    status=status,
                    error_code="",
                    error_message=error_message,
                    request_hash="",
                    created_at=datetime.utcnow(),
                )
                db.add(log)
                db.commit()
            finally:
                db.close()
        except Exception as e:
            import logging
            logger = logging.getLogger("m8.compute_router")
            logger.warning(f"写入调用日志失败: {e}")

    # ============================================================
    # 健康检查后台线程
    # ============================================================

    def _start_health_check_thread(self):
        """启动健康检查线程"""
        self._health_thread = threading.Thread(
            target=self._health_check_loop,
            daemon=True,
            name="compute-router-health",
        )
        self._health_thread.start()

    def _health_check_loop(self):
        """健康检查循环"""
        while not self._stop_event.is_set():
            try:
                self._run_health_check()
            except Exception as e:
                import logging
                logger = logging.getLogger("m8.compute_router")
                logger.warning(f"健康检查异常: {e}")

            self._stop_event.wait(30)  # 30秒检查一次

    def _run_health_check(self):
        """执行一次健康检查（检测网络状态）"""
        import socket

        online = False
        try:
            socket.create_connection(("8.8.8.8", 53), timeout=3)
            online = True
        except Exception:
            try:
                socket.create_connection(("114.114.114.114", 53), timeout=3)
                online = True
            except Exception:
                online = False

        with self._lock:
            was_offline = self._is_offline
            self._is_offline = not online

            if not online and not was_offline:
                self._offline_since = time.time()
            elif online and was_offline:
                self._offline_since = 0.0

    # ============================================================
    # 额度重置定时任务
    # ============================================================

    def _start_quota_reset_thread(self):
        """启动额度重置定时任务线程"""
        self._quota_reset_thread = threading.Thread(
            target=self._quota_reset_loop,
            daemon=True,
            name="compute-router-quota",
        )
        self._quota_reset_thread.start()

    def _quota_reset_loop(self):
        """额度重置循环"""
        while not self._stop_event.is_set():
            try:
                self._check_and_reset_quotas()
            except Exception as e:
                import logging
                logger = logging.getLogger("m8.compute_router")
                logger.warning(f"额度重置异常: {e}")

            self._stop_event.wait(60)  # 每分钟检查一次

    def _check_and_reset_quotas(self):
        """检查并重置额度"""
        with self._lock:
            for quota in self._quotas.values():
                self._check_quota_reset(quota)

    # ============================================================
    # 公共 API
    # ============================================================

    def reload_config(self):
        """重新加载配置"""
        self._load_config_from_db()
        self._init_circuit_breakers()
        self._init_rate_limiters()
        self._init_call_stats()

    def get_all_sources(self) -> Dict[str, Dict[str, Any]]:
        """获取所有算力源"""
        with self._lock:
            return dict(self._sources)

    def get_source(self, source_id: str) -> Optional[Dict[str, Any]]:
        """获取单个算力源"""
        with self._lock:
            return self._sources.get(source_id)

    def get_all_policies(self) -> Dict[str, Dict[str, Any]]:
        """获取所有路由策略"""
        with self._lock:
            return dict(self._policies)

    def get_active_policy(self) -> Optional[Dict[str, Any]]:
        """获取激活的策略"""
        with self._lock:
            return self._get_active_policy()

    def get_circuit_breaker(self, source_id: str) -> Optional[CircuitBreaker]:
        """获取指定算力源的熔断器"""
        return self._circuit_breakers.get(source_id)

    def get_all_circuit_breakers(self) -> Dict[str, Dict[str, Any]]:
        """获取所有熔断器状态"""
        result = {}
        for sid, cb in self._circuit_breakers.items():
            result[sid] = cb.get_stats()
        return result

    def reset_circuit_breaker(self, source_id: str) -> bool:
        """重置熔断器"""
        cb = self._circuit_breakers.get(source_id)
        if cb:
            cb.reset()
            return True
        return False

    def get_rate_limits(self) -> Dict[str, Any]:
        """获取所有限流状态"""
        result = {
            "global": self._global_rate_limiter.get_stats() if self._global_rate_limiter else {},
            "sources": {},
            "modules": {},
            "skills": {},
        }
        for sid, rl in self._source_rate_limiters.items():
            result["sources"][sid] = rl.get_stats()
        for mid, rl in self._module_rate_limiters.items():
            result["modules"][mid] = rl.get_stats()
        for sid, rl in self._skill_rate_limiters.items():
            result["skills"][sid] = rl.get_stats()
        return result

    def reset_rate_limit(self, scope: str, key: str = "") -> bool:
        """重置限流计数"""
        if scope == "global":
            if self._global_rate_limiter:
                self._global_rate_limiter.reset()
            return True
        elif scope == "source":
            rl = self._source_rate_limiters.get(key)
            if rl:
                rl.reset()
                return True
        elif scope == "module":
            rl = self._module_rate_limiters.get(key)
            if rl:
                rl.reset()
                return True
        elif scope == "skill":
            rl = self._skill_rate_limiters.get(key)
            if rl:
                rl.reset()
                return True
        return False

    def get_call_stats(self, source_id: str = None) -> Dict[str, Any]:
        """获取调用统计"""
        with self._lock:
            if source_id:
                return dict(self._call_stats.get(source_id, {}))
            return {sid: dict(stats) for sid, stats in self._call_stats.items()}

    def get_overall_stats(self) -> Dict[str, Any]:
        """获取总体统计数据"""
        with self._lock:
            total_sources = len(self._sources)
            healthy_sources = sum(
                1 for s in self._sources.values()
                if s["status"] == "active" and s["health_status"] == "healthy"
            )
            degraded_sources = sum(
                1 for s in self._sources.values()
                if s["status"] == "active" and s["health_status"] == "degraded"
            )
            failed_sources = total_sources - healthy_sources - degraded_sources

            today_calls = 0
            today_success = 0
            today_failed = 0
            today_cost = 0.0
            total_latency = 0.0
            total_calls = 0

            for stats in self._call_stats.values():
                today_calls += stats["today_calls"]
                today_success += stats["today_success"]
                today_failed += stats["today_failed"]
                today_cost += stats["today_cost"]
                total_latency += stats["total_latency_ms"]
                total_calls += stats["total_calls"]

            success_rate = today_success / today_calls if today_calls > 0 else 1.0
            avg_latency = total_latency / total_calls if total_calls > 0 else 0.0

            active_connections = sum(
                s.get("current_concurrent", 0) for s in self._sources.values()
            )

            return {
                "sources": {
                    "total": total_sources,
                    "healthy": healthy_sources,
                    "degraded": degraded_sources,
                    "failed": failed_sources,
                    "unreachable": sum(
                        1 for s in self._sources.values()
                        if s["health_status"] == "unreachable"
                    ),
                },
                "today": {
                    "calls": today_calls,
                    "success": today_success,
                    "failed": today_failed,
                    "success_rate": round(success_rate, 4),
                    "avg_latency_ms": round(avg_latency, 2),
                    "total_cost": round(today_cost, 6),
                },
                "active_connections": active_connections,
                "is_offline": self._is_offline,
                "offline_since": self._offline_since,
            }

    def get_all_quotas(self) -> Dict[str, Dict[str, Any]]:
        """获取所有额度配置"""
        with self._lock:
            return {qid: dict(q) for qid, q in self._quotas.items()}

    def reset_quota(self, quota_id: str) -> bool:
        """重置额度使用量"""
        with self._lock:
            quota = self._quotas.get(quota_id)
            if quota:
                quota["used_value"] = 0.0
                quota["last_reset_at"] = datetime.utcnow()
                return True
            return False

    def get_all_skills(self) -> Dict[str, Dict[str, Any]]:
        """获取所有技能绑定"""
        with self._lock:
            return dict(self._skill_bindings)

    def is_offline(self) -> bool:
        """检查是否离线"""
        return self._is_offline

    def shutdown(self):
        """关闭路由引擎"""
        self._stop_event.set()
        if self._health_thread:
            self._health_thread.join(timeout=5)
        if self._quota_reset_thread:
            self._quota_reset_thread.join(timeout=5)


# 全局单例
def get_compute_router() -> ComputeRouter:
    """获取算力路由引擎单例"""
    return ComputeRouter()
