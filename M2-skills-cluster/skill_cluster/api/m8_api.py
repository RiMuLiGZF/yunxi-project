"""M8 标准对接接口.

为 M2 技能集群提供 M8 管理平台标准对接的三个核心端点：

- GET /m8/health   健康检查（Token 鉴权）
- GET /m8/metrics  性能指标（Token 鉴权）
- GET /m8/config   配置查询（脱敏，无需鉴权）

设计要点：
- Token 来源：环境变量 ``M2_M8_TOKEN``（优先）或 ``M8_TOKEN``
- 鉴权方式：``hmac.compare_digest``（恒定时间比较，防时序攻击）
- /m8/health 与 /m8/metrics 需要携带 ``X-M8-Token`` 请求头
- /m8/config 返回脱敏后的配置，不要求鉴权
- 版本号从 :mod:`skill_cluster.version` 读取，避免硬编码
- 全程使用 structlog 结构化日志

鉴权策略：
- 未配置 Token（开发模式）：放行并记录 warning 日志
- 已配置 Token 但请求未携带/不匹配：返回 401
- /m8/* 路径已加入全局 M8TokenAuthMiddleware 白名单，
  由本模块独立完成鉴权，避免与 v2 API 的 M2_ADMIN_TOKEN 冲突
"""

from __future__ import annotations

import hmac
import os
import time
from datetime import datetime, timezone
from typing import Any

import structlog

logger = structlog.get_logger()

# FastAPI 可选导入（未安装时优雅降级）
_fastapi_available = False
try:
    from fastapi import Header, HTTPException
    _fastapi_available = True
except ImportError:  # pragma: no cover - 仅在无 FastAPI 环境触发
    Header = None  # type: ignore[assignment, misc]
    HTTPException = None  # type: ignore[assignment, misc]


# ============================================================
# 模块常量
# ============================================================

MODULE_ID = "m2-skills"
MODULE_NAME = "技能集群"

# 配置脱敏：匹配以下子串（小写）的键值将被掩码
_SENSITIVE_KEY_HINTS = frozenset({
    "api_key", "password", "token", "secret", "authorization",
    "jwt_secret", "encryption_key", "credential",
})


# ============================================================
# 工具函数
# ============================================================

def _get_module_version() -> str:
    """从 skill_cluster.version 读取模块版本号.

    优先使用 ``__version_info__`` 元组拼接（如 (3, 10, 2) -> "3.10.2"），
    回退到 ``__version__`` 字符串，再回退到 "unknown"。
    """
    try:
        from skill_cluster import version as _ver
        info = getattr(_ver, "__version_info__", None)
        if info:
            return ".".join(str(p) for p in info)
        ver = getattr(_ver, "__version__", None)
        if ver:
            return ver
    except Exception as e:  # pragma: no cover - 防御性
        logger.warning("m8_version_read_failed", error=str(e))
    return "unknown"


def _get_m8_token() -> str:
    """从环境变量读取 M8 对接 Token.

    优先级：M2_M8_TOKEN > M8_TOKEN
    """
    return os.environ.get("M2_M8_TOKEN", "") or os.environ.get("M8_TOKEN", "")


def _verify_token(provided: str) -> bool:
    """验证 M8 Token（使用 hmac.compare_digest 防时序攻击）.

    - 未配置 Token（开发模式）：放行并记录 warning
    - 已配置 Token：恒定时间比较 provided 与预期值
    """
    expected = _get_m8_token()
    if not expected:
        logger.warning(
            "m8_token_not_configured",
            message="M2_M8_TOKEN/M8_TOKEN 未配置，M8 接口鉴权已禁用（开发模式）",
        )
        return True
    if not provided:
        return False
    return hmac.compare_digest(provided, expected)


def _require_auth(x_m8_token: str) -> None:
    """执行鉴权，失败时抛出 401 HTTPException."""
    if not _verify_token(x_m8_token):
        logger.warning("m8_auth_failed", reason="invalid_or_missing_token")
        raise HTTPException(status_code=401, detail="Invalid M8 token")


def _iso_timestamp() -> str:
    """返回 ISO 8601 时间戳（UTC，含时区偏移）。"""
    return datetime.now(timezone.utc).isoformat()


def _get_system_metrics() -> tuple[float, int]:
    """采集系统 CPU 使用率(%)与进程内存(MB).

    psutil 不可用时回退到 0。
    """
    try:
        import psutil
        cpu = psutil.cpu_percent(interval=0.1)
        mem_mb = int(psutil.Process().memory_info().rss / (1024 * 1024))
        return round(cpu, 1), mem_mb
    except Exception:
        return 0.0, 0


def _get_skill_metrics(registry: Any) -> tuple[int, int]:
    """从注册中心获取技能总数与活跃（启用）技能数.

    Returns:
        (skill_count, active_skills)
    """
    skill_count = 0
    active_skills = 0
    if registry is not None:
        try:
            all_skills = (
                registry.list_all() if hasattr(registry, "list_all") else []
            )
            skill_count = len(all_skills)
            for sk in all_skills:
                if getattr(sk, "enabled", True):
                    active_skills += 1
        except Exception as e:
            logger.warning("m8_skill_metrics_error", error=str(e))
    return skill_count, active_skills


def _get_cache_hit_rate(cache: Any = None) -> float:
    """获取缓存命中率.

    【v3.11.0 优化】SkillCache 已维护命中/未命中计数器，
    直接读取 hit_rate 属性即可。兼容旧版无属性情况。

    若传入具备 ``hit_count`` / ``miss_count`` 属性的缓存对象，
    则按 hits / (hits + misses) 计算。
    """
    if cache is None:
        return 0.0
    try:
        # 优先读取已计算好的 hit_rate 属性
        if hasattr(cache, "hit_rate"):
            rate = getattr(cache, "hit_rate")
            if isinstance(rate, (int, float)):
                return round(float(rate), 4)
        # 回退：手动计算
        hits = getattr(cache, "hit_count", 0) or 0
        misses = getattr(cache, "miss_count", 0) or 0
        total = hits + misses
        if total <= 0:
            return 0.0
        return round(hits / total, 4)
    except Exception:
        return 0.0


def _mask_value(value: Any) -> Any:
    """递归脱敏：将敏感键的值替换为 '***'."""
    if isinstance(value, dict):
        return {
            k: ("***" if _is_sensitive_key(k) else _mask_value(v))
            for k, v in value.items()
        }
    if isinstance(value, list):
        return [_mask_value(v) for v in value]
    return value


def _is_sensitive_key(key: str) -> bool:
    """判断键名是否属于敏感字段（大小写不敏感）。"""
    lowered = str(key).lower()
    return any(hint in lowered for hint in _SENSITIVE_KEY_HINTS)


def _get_desensitized_config() -> dict[str, Any]:
    """构建脱敏后的模块配置字典.

    从 AppConfig 单例导出，注入运行时环境配置，再递归脱敏。
    """
    config_dict: dict[str, Any] = {}
    try:
        from skill_cluster.config import get_config
        cfg = get_config()
        if hasattr(cfg, "model_dump"):
            config_dict = cfg.model_dump()
        elif hasattr(cfg, "dict"):
            config_dict = cfg.dict()
    except Exception as e:
        logger.warning("m8_config_load_failed", error=str(e))

    # 注入运行时配置（环境变量优先）
    basic = config_dict.setdefault("basic", {})
    if not isinstance(basic, dict):
        basic = {}
        config_dict["basic"] = basic
    basic["port"] = int(os.environ.get("M2_PORT", "8002"))
    basic["host"] = os.environ.get("M2_HOST", "0.0.0.0")
    basic["env"] = os.environ.get(
        "M2_ENV", os.environ.get("YUNXI_ENV", "development")
    )

    return _mask_value(config_dict)


# ============================================================
# 路由注册
# ============================================================

def register_m8_routes(
    app: Any,
    registry: Any = None,
    start_time: float | None = None,
    cache: Any = None,
) -> None:
    """在 FastAPI 应用上注册 M8 标准对接路由.

    Args:
        app: FastAPI 应用实例。
        registry: SkillRegistry 实例（可选，用于指标采集）。
        start_time: 服务启动时间戳（可选，用于计算 uptime）。
        cache: 缓存实例（可选，用于计算 cache_hit_rate）。

    Note:
        调用前请确保 /m8/* 路径已在全局 M8TokenAuthMiddleware 白名单中，
        以避免与 v2 API 的 M2_ADMIN_TOKEN 鉴权产生冲突。
        本模块使用独立的 M2_M8_TOKEN / M8_TOKEN 进行鉴权。
    """
    if not _fastapi_available:
        logger.warning("m8_routes_disabled", reason="fastapi not installed")
        return

    _start_time = start_time if start_time is not None else time.time()
    version = _get_module_version()

    # ---- GET /m8/health ----
    @app.get("/m8/health", tags=["M8-标准接口"], summary="M8标准健康检查")
    async def m8_health(
        x_m8_token: str = Header(default="", alias="X-M8-Token"),
    ):
        """M8 标准健康检查接口（需 Token 鉴权）.

        返回模块标识、版本、健康状态与时间戳。
        """
        _require_auth(x_m8_token)
        uptime = int(time.time() - _start_time)
        skill_count, _ = _get_skill_metrics(registry)
        logger.info(
            "m8_health_checked",
            module=MODULE_ID,
            version=version,
            uptime=uptime,
            skill_count=skill_count,
        )
        return {
            "code": 0,
            "message": "ok",
            "data": {
                "module": MODULE_ID,
                "module_name": MODULE_NAME,
                "version": version,
                "status": "healthy",
                "skill_count": skill_count,
                "uptime_seconds": uptime,
                "timestamp": _iso_timestamp(),
            },
        }

    # ---- GET /m8/metrics ----
    @app.get("/m8/metrics", tags=["M8-标准接口"], summary="M8标准性能指标")
    async def m8_metrics(
        x_m8_token: str = Header(default="", alias="X-M8-Token"),
    ):
        """M8 标准性能指标接口（需 Token 鉴权）.

        返回技能数量、活跃技能、缓存命中率、CPU 使用率、内存占用。
        """
        _require_auth(x_m8_token)
        skill_count, active_skills = _get_skill_metrics(registry)
        cache_hit_rate = _get_cache_hit_rate(cache)
        cpu_usage, memory_mb = _get_system_metrics()
        logger.info(
            "m8_metrics_reported",
            module=MODULE_ID,
            skill_count=skill_count,
            active_skills=active_skills,
            cache_hit_rate=cache_hit_rate,
            cpu_usage=cpu_usage,
            memory_mb=memory_mb,
        )
        return {
            "code": 0,
            "message": "ok",
            "data": {
                "module": MODULE_ID,
                "skill_count": skill_count,
                "active_skills": active_skills,
                "cache_hit_rate": cache_hit_rate,
                "cpu_usage": cpu_usage,
                "memory_mb": memory_mb,
            },
        }

    # ---- GET /m8/config ----
    @app.get("/m8/config", tags=["M8-标准接口"], summary="M8标准配置查询")
    async def m8_config():
        """M8 标准配置查询接口（脱敏，无需鉴权）.

        返回模块标识、名称、版本与脱敏后的完整配置。

        注意：_get_desensitized_config() 为同步函数，内部仅做
        Pydantic model_dump + 环境变量注入 + 递归脱敏，均为内存操作，
        无 I/O 阻塞风险。若后续引入同步 DB/网络 调用，需改用
        asyncio.to_thread() 包装以避免阻塞事件循环。
        """
        config = _get_desensitized_config()
        logger.info("m8_config_queried", module=MODULE_ID)
        return {
            "code": 0,
            "message": "ok",
            "data": {
                "module": MODULE_ID,
                "module_name": MODULE_NAME,
                "version": version,
                "config": config,
            },
        }

    logger.info(
        "m8_routes_registered",
        module=MODULE_ID,
        version=version,
        endpoints=["/m8/health", "/m8/metrics", "/m8/config"],
    )
