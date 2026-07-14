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
       