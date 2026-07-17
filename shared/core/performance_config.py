"""
性能配置模块

提供统一的性能调优配置管理，支持环境变量覆盖。
所有性能相关的配置集中在此，方便统一管理和调优。

使用方式::

    from shared.core.performance_config import get_perf_config, PerformanceConfig

    config = get_perf_config()
    print(config.cache.max_size)
"""

import os
from typing import Any, Dict, Optional
from dataclasses import dataclass, field


# ============================================================
# 缓存配置
# ============================================================

@dataclass
class CacheConfig:
    """缓存配置"""
    # L1 内存缓存
    l1_enabled: bool = True
    l1_max_size: int = 5000
    l1_default_ttl: float = 60.0  # 秒
    l1_cleanup_interval: float = 60.0
    l1_hot_ratio: float = 0.2
    l1_hot_ttl_multiplier: float = 3.0
    l1_hot_access_threshold: int = 3

    # L2 二级缓存
    l2_enabled: bool = False
    l2_type: str = "file"  # redis / file
    l2_ttl_multiplier: float = 5.0
    l2_max_size_mb: int = 100
    l2_redis_url: str = "redis://localhost:6379/0"

    # 防护配置
    null_ttl: float = 30.0  # 空值缓存时间（穿透防护）
    jitter_ratio: float = 0.1  # TTL 抖动比例（雪崩防护）
    enable_penetration_guard: bool = True
    enable_breakdown_guard: bool = True
    enable_avalanche_guard: bool = True

    # 查询缓存
    query_cache_enabled: bool = True
    query_cache_size: int = 500
    query_cache_ttl: float = 30.0


# ============================================================
# 数据库配置
# ============================================================

@dataclass
class DatabaseConfig:
    """数据库性能配置"""
    # 连接池
    pool_enabled: bool = True
    pool_size: int = 5
    max_overflow: int = 10
    idle_timeout: float = 300.0

    # SQLite 优化
    journal_mode: str = "WAL"
    synchronous: str = "NORMAL"
    cache_size_kb: int = -20000  # 负数表示页数 * 1024
    mmap_size: int = 268435456  # 256MB
    busy_timeout_ms: int = 30000
    temp_store: str = "MEMORY"
    wal_autocheckpoint: int = 1000

    # 慢查询
    slow_query_threshold_ms: float = 1000.0
    slow_query_log_enabled: bool = True

    # 索引
    auto_optimize_indexes: bool = True

    # 批量操作
    batch_insert_size: int = 500


# ============================================================
# 日志配置
# ============================================================

@dataclass
class LogConfig:
    """日志性能配置"""
    # 异步日志
    async_enabled: bool = True
    async_queue_size: int = 1000
    async_batch_size: int = 50
    async_flush_interval: float = 0.5

    # 日志级别
    level: str = "INFO"
    console_level: str = "INFO"
    file_level: str = "DEBUG"

    # 格式
    json_format: bool = True
    use_color: bool = False

    # 文件轮转
    rotation_enabled: bool = True
    rotation_when: str = "midnight"
    rotation_backup_count: int = 30
    rotation_max_bytes: int = 104857600  # 100MB
    rotation_compress: bool = True

    # 敏感字段脱敏
    desensitize_enabled: bool = True


# ============================================================
# API / HTTP 配置
# ============================================================

@dataclass
class APIConfig:
    """API 性能配置"""
    # 响应缓存
    response_cache_enabled: bool = True
    response_cache_ttl: float = 5.0
    response_cache_max_size: int = 1000

    # 限流
    rate_limit_enabled: bool = True
    rate_limit_default: int = 100  # 每分钟请求数
    rate_limit_burst: int = 50

    # 并发
    max_concurrent_requests: int = 200
    request_timeout: float = 30.0

    # 序列化
    json_library: str = "auto"  # auto / orjson / ujson / json

    # Gzip 压缩
    gzip_enabled: bool = True
    gzip_min_size: int = 1024  # 1KB 以上才压缩


# ============================================================
# 线程/并发配置
# ============================================================

@dataclass
class ConcurrencyConfig:
    """并发配置"""
    # 线程池
    worker_threads: int = 10
    io_threads: int = 20
    max_workers: int = 32

    # 队列
    default_queue_size: int = 10000

    # 批量处理
    default_batch_size: int = 100
    default_flush_interval: float = 1.0


# ============================================================
# 总配置
# ============================================================

@dataclass
class PerformanceConfig:
    """性能配置总览"""
    env: str = "production"
    cache: CacheConfig = field(default_factory=CacheConfig)
    database: DatabaseConfig = field(default_factory=DatabaseConfig)
    log: LogConfig = field(default_factory=LogConfig)
    api: APIConfig = field(default_factory=APIConfig)
    concurrency: ConcurrencyConfig = field(default_factory=ConcurrencyConfig)

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            "env": self.env,
            "cache": {
                k: v for k, v in self.cache.__dict__.items()
            },
            "database": {
                k: v for k, v in self.database.__dict__.items()
            },
            "log": {
                k: v for k, v in self.log.__dict__.items()
            },
            "api": {
                k: v for k, v in self.api.__dict__.items()
            },
            "concurrency": {
                k: v for k, v in self.concurrency.__dict__.items()
            },
        }


# ============================================================
# 配置加载
# ============================================================

def _env_bool(name: str, default: bool) -> bool:
    """从环境变量读取布尔值"""
    val = os.getenv(name, "")
    if not val:
        return default
    return val.lower() in ("true", "1", "yes", "on")


def _env_int(name: str, default: int) -> int:
    """从环境变量读取整数值"""
    val = os.getenv(name, "")
    if not val:
        return default
    try:
        return int(val)
    except (ValueError, TypeError):
        return default


def _env_float(name: str, default: float) -> float:
    """从环境变量读取浮点值"""
    val = os.getenv(name, "")
    if not val:
        return default
    try:
        return float(val)
    except (ValueError, TypeError):
        return default


def _env_str(name: str, default: str) -> str:
    """从环境变量读取字符串值"""
    return os.getenv(name, default)


def load_performance_config(env: Optional[str] = None) -> PerformanceConfig:
    """从环境变量加载性能配置

    Args:
        env: 运行环境，None 则自动检测

    Returns:
        PerformanceConfig 对象
    """
    if env is None:
        env = os.getenv("YUNXI_ENV", os.getenv("ENV", "production"))

    config = PerformanceConfig(env=env)

    # ---- 缓存配置 ----
    config.cache.l1_enabled = _env_bool("PERF_CACHE_L1_ENABLED", config.cache.l1_enabled)
    config.cache.l1_max_size = _env_int("PERF_CACHE_L1_MAX_SIZE", config.cache.l1_max_size)
    config.cache.l1_default_ttl = _env_float("PERF_CACHE_L1_TTL", config.cache.l1_default_ttl)
    config.cache.l2_enabled = _env_bool("PERF_CACHE_L2_ENABLED", config.cache.l2_enabled)
    config.cache.l2_type = _env_str("PERF_CACHE_L2_TYPE", config.cache.l2_type)
    config.cache.query_cache_enabled = _env_bool("PERF_QUERY_CACHE_ENABLED", config.cache.query_cache_enabled)
    config.cache.query_cache_size = _env_int("PERF_QUERY_CACHE_SIZE", config.cache.query_cache_size)
    config.cache.query_cache_ttl = _env_float("PERF_QUERY_CACHE_TTL", config.cache.query_cache_ttl)

    # ---- 数据库配置 ----
    config.database.pool_enabled = _env_bool("PERF_DB_POOL_ENABLED", config.database.pool_enabled)
    config.database.pool_size = _env_int("PERF_DB_POOL_SIZE", config.database.pool_size)
    config.database.slow_query_threshold_ms = _env_float(
        "SLOW_QUERY_THRESHOLD_MS", config.database.slow_query_threshold_ms
    )
    config.database.batch_insert_size = _env_int("PERF_DB_BATCH_SIZE", config.database.batch_insert_size)

    # ---- 日志配置 ----
    config.log.async_enabled = _env_bool("PERF_LOG_ASYNC", config.log.async_enabled)
    config.log.async_queue_size = _env_int("PERF_LOG_QUEUE_SIZE", config.log.async_queue_size)
    config.log.level = _env_str("LOG_LEVEL", config.log.level)
    config.log.json_format = _env_bool("LOG_JSON_FORMAT", config.log.json_format)

    # ---- API 配置 ----
    config.api.response_cache_enabled = _env_bool("PERF_API_CACHE_ENABLED", config.api.response_cache_enabled)
    config.api.rate_limit_enabled = _env_bool("PERF_RATE_LIMIT_ENABLED", config.api.rate_limit_enabled)
    config.api.max_concurrent_requests = _env_int(
        "PERF_MAX_CONCURRENT", config.api.max_concurrent_requests
    )
    config.api.json_library = _env_str("PERF_JSON_LIBRARY", config.api.json_library)

    # ---- 并发配置 ----
    config.concurrency.worker_threads = _env_int("PERF_WORKER_THREADS", config.concurrency.worker_threads)
    config.concurrency.io_threads = _env_int("PERF_IO_THREADS", config.concurrency.io_threads)
    config.concurrency.default_batch_size = _env_int(
        "PERF_BATCH_SIZE", config.concurrency.default_batch_size
    )

    return config


# 全局单例
_config: Optional[PerformanceConfig] = None
_config_lock = None  # 惰性初始化


def get_perf_config() -> PerformanceConfig:
    """获取全局性能配置单例"""
    global _config, _config_lock
    if _config is not None:
        return _config

    if _config_lock is None:
        import threading
        _config_lock = threading.Lock()

    with _config_lock:
        if _config is None:
            _config = load_performance_config()
        return _config


def reset_perf_config() -> None:
    """重置配置（用于测试）"""
    global _config
    _config = None


# ============================================================
# 预设配置模板
# ============================================================

def get_development_config() -> PerformanceConfig:
    """开发环境配置（调试优先）"""
    config = PerformanceConfig(env="development")
    config.cache.l1_max_size = 1000
    config.cache.l2_enabled = False
    config.log.async_enabled = False
    config.log.level = "DEBUG"
    config.log.json_format = False
    config.log.use_color = True
    config.database.slow_query_threshold_ms = 500.0
    return config


def get_production_config() -> PerformanceConfig:
    """生产环境配置（性能优先）"""
    return PerformanceConfig(env="production")


def get_high_performance_config() -> PerformanceConfig:
    """高性能配置（极致性能，可能牺牲部分一致性）"""
    config = PerformanceConfig(env="high_performance")
    config.cache.l1_max_size = 20000
    config.cache.l2_enabled = True
    config.cache.l2_type = "redis"
    config.cache.l1_default_ttl = 300.0
    config.database.pool_size = 20
    config.database.synchronous = "OFF"  # 牺牲一点一致性换性能
    config.database.cache_size_kb = -100000  # 100MB 缓存
    config.log.async_enabled = True
    config.log.async_queue_size = 5000
    config.log.level = "WARNING"
    config.api.json_library = "orjson"
    config.concurrency.worker_threads = 32
    config.concurrency.io_threads = 64
    return config


# 预设配置映射
PRESET_CONFIGS = {
    "development": get_development_config,
    "production": get_production_config,
    "high_performance": get_high_performance_config,
}


def get_preset_config(preset: str) -> PerformanceConfig:
    """获取预设配置

    Args:
        preset: 预设名称 (development/production/high_performance)

    Returns:
        PerformanceConfig 对象
    """
    factory = PRESET_CONFIGS.get(preset.lower())
    if factory is None:
        raise ValueError(f"Unknown preset: {preset}. Available: {list(PRESET_CONFIGS.keys())}")
    return factory()
