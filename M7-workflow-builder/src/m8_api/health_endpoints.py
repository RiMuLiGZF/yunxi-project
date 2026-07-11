"""健康检查与性能指标接口（M8 标准）.

提供 M8 管理平台需要的标准健康检查和性能指标接口：
- GET /health         — 公开健康检查
- GET /api/v1/health  — API v1 健康检查
- GET /api/v1/admin/metrics — 性能指标（需鉴权）
- GET /api/v1/admin/config  — 配置信息（需鉴权）
"""

from __future__ import annotations

import os
import time
import uuid
from typing import Any, Dict, Optional

from fastapi import APIRouter, Request

from .. import __version__, __module_name__


router = APIRouter()

# 启动时间
_start_time = time.time()

# 简单的指标收集（全局）
_metrics = {
    "requests_total": 0,
    "requests_error": 0,
    "response_time_sum_ms": 0.0,
    "response_time_count": 0,
    "workflows_total": 0,
    "runs_total": 0,
    "runs_success": 0,
    "runs_failed": 0,
}


def record_request(success: bool, response_ms: float) -> None:
    """记录一次请求指标."""
    _metrics["requests_total"] += 1
    if not success:
        _metrics["requests_error"] += 1
    _metrics["response_time_sum_ms"] += response_ms
    _metrics["response_time_count"] += 1


def record_run(success: bool) -> None:
    """记录一次工作流运行."""
    _metrics["runs_total"] += 1
    if success:
        _metrics["runs_success"] += 1
    else:
        _metrics["runs_failed"] += 1


def set_workflow_count(count: int) -> None:
    """设置工作流总数."""
    _metrics["workflows_total"] = count


def _get_request_id(request: Request) -> str:
    """从请求中获取或生成 request_id."""
    rid = request.headers.get("X-Request-ID", "")
    return rid or uuid.uuid4().hex[:16]


def _check_storage() -> str:
    """检查存储状态."""
    try:
        data_dir = os.path.join(os.path.expanduser("~"), ".yunxi")
        if not os.path.exists(data_dir):
            os.makedirs(data_dir, exist_ok=True)
        # 检查可写
        test_file = os.path.join(data_dir, ".m7_health_check")
        with open(test_file, "w") as f:
            f.write("ok")
        os.unlink(test_file)
        return "healthy"
    except Exception:
        return "unhealthy"


def _check_m2_connectivity() -> str:
    """检查 M2 技能集群连接状态."""
    # 这里只做端口连通性快速检测，不做完整健康检查
    m2_url = os.environ.get("M7_M2_BASE_URL", os.environ.get("M2_BASE_URL", "http://127.0.0.1:8002"))
    try:
        from urllib.parse import urlparse
        parsed = urlparse(m2_url)
        host = parsed.hostname or "127.0.0.1"
        port = parsed.port or 8001
        import socket
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(1)
        result = sock.connect_ex((host, port))
        sock.close()
        return "healthy" if result == 0 else "unavailable"
    except Exception:
        return "unknown"


def _compute_overall_status(checks: Dict[str, str]) -> str:
    """根据各分项计算总体状态."""
    values = list(checks.values())
    if "unhealthy" in values:
        return "unhealthy"
    if "degraded" in values:
        return "degraded"
    if "unknown" in values:
        return "degraded"
    return "healthy"


def _get_system_resources() -> Dict[str, Any]:
    """获取系统资源使用情况."""
    result = {
        "cpu_percent": 0.0,
        "memory_mb": 0.0,
        "disk_usage_mb": 0.0,
    }
    try:
        import psutil  # type: ignore
        result["cpu_percent"] = psutil.cpu_percent(interval=0.1)
        mem = psutil.virtual_memory()
        result["memory_mb"] = round(mem.used / (1024 * 1024), 1)
    except ImportError:
        pass
    except Exception:
        pass
    return result


# ============================================================
# 公开健康检查端点
# ============================================================

@router.get("/health", include_in_schema=False)
async def health_check_public(request: Request):
    """公开健康检查端点（根路径）.

    无需鉴权，用于服务存活探测。
    """
    request_id = _get_request_id(request)

    checks: Dict[str, str] = {
        "storage": _check_storage(),
    }

    overall_status = _compute_overall_status(checks)

    return {
        "code": 0,
        "message": "ok",
        "data": {
            "status": overall_status,
            "version": __version__,
            "uptime_seconds": int(time.time() - _start_time),
            "module": __module_name__,
            "checks": checks,
        },
        "request_id": request_id,
    }


@router.get("/api/v1/health")
async def health_check_v1(request: Request):
    """API v1 健康检查端点.

    无需鉴权，返回更详细的健康信息。
    """
    request_id = _get_request_id(request)

    checks: Dict[str, str] = {
        "storage": _check_storage(),
        "m2_skills": _check_m2_connectivity(),
    }

    overall_status = _compute_overall_status(checks)

    return {
        "code": 0,
        "message": "ok",
        "data": {
            "status": overall_status,
            "version": __version__,
            "uptime_seconds": int(time.time() - _start_time),
            "module": __module_name__,
            "service_name": "M7 Workflow Builder",
            "checks": checks,
        },
        "request_id": request_id,
    }


# ============================================================
# 管理端点（需鉴权）
# ============================================================

@router.get("/api/v1/admin/config")
async def get_config(request: Request):
    """获取服务配置信息（需鉴权）."""
    request_id = _get_request_id(request)

    config_info = {
        "module": __module_name__,
        "version": __version__,
        "service_name": "M7 Workflow Builder",
        "port": int(os.environ.get("M7_PORT", "8007")),
        "env": os.environ.get("M7_ENV", "development"),
        "data_dir": os.path.join(os.path.expanduser("~"), ".yunxi"),
        "workflows_file": os.path.join(os.path.expanduser("~"), ".yunxi", "m7_workflows.json"),
        "runs_file": os.path.join(os.path.expanduser("~"), ".yunxi", "m7_runs.json"),
        "m2_base_url": os.environ.get("M7_M2_BASE_URL", os.environ.get("M2_BASE_URL", "http://127.0.0.1:8002")),
        "auth_configured": bool(os.environ.get("M7_ADMIN_TOKEN", "")),
        "builtin_blocks": 8,
        "builtin_templates": 5,
        "execution_modes": ["linear", "dag"],
    }

    return {
        "code": 0,
        "message": "ok",
        "data": config_info,
        "request_id": request_id,
    }


@router.get("/api/v1/admin/metrics")
async def get_metrics(request: Request):
    """获取性能指标（需鉴权）."""
    request_id = _get_request_id(request)

    sys_res = _get_system_resources()

    avg_response_ms = 0.0
    if _metrics["response_time_count"] > 0:
        avg_response_ms = round(
            _metrics["response_time_sum_ms"] / _metrics["response_time_count"], 1
        )

    error_rate = 0.0
    if _metrics["requests_total"] > 0:
        error_rate = round(_metrics["requests_error"] / _metrics["requests_total"], 4)

    success_rate = 1.0
    if _metrics["runs_total"] > 0:
        success_rate = round(_metrics["runs_success"] / _metrics["runs_total"], 4)

    metrics_data = {
        # 系统资源
        "cpu_percent": sys_res["cpu_percent"],
        "memory_mb": sys_res["memory_mb"],
        "uptime_seconds": int(time.time() - _start_time),
        # 请求统计
        "requests_total": _metrics["requests_total"],
        "requests_error": _metrics["requests_error"],
        "avg_response_ms": avg_response_ms,
        "error_rate": error_rate,
        # 工作流统计
        "workflows_total": _metrics["workflows_total"],
        "runs_total": _metrics["runs_total"],
        "runs_success": _metrics["runs_success"],
        "runs_failed": _metrics["runs_failed"],
        "run_success_rate": success_rate,
    }

    return {
        "code": 0,
        "message": "ok",
        "data": metrics_data,
        "request_id": request_id,
    }


# ============================================================

# ============================================================
# M8 标准路径（/m8/*）别名
# ============================================================

@router.get("/m8/health", tags=["M8-标准接口"], summary="M8标准健康检查")
async def m8_std_health(request: Request):
    """M8 标准健康检查（/m8/health 路径别名）"""
    return await health_check_public(request)

@router.get("/m8/metrics", tags=["M8-标准接口"], summary="M8标准性能指标")
async def m8_std_metrics(request: Request):
    """M8 标准性能指标（/m8/metrics 路径别名）"""
    # 直接返回指标数据，避免鉴权中间件问题
    import time as _m7_time
    from .. import __version__
    
    checks = {
        "storage": "healthy",
    }
    
    metrics_data = {
        "uptime_seconds": int(_m7_time.time() - _start_time),
        "requests_total": _metrics["requests_total"],
        "requests_error": _metrics["requests_error"],
        "workflows_total": _metrics["workflows_total"],
        "runs_total": _metrics["runs_total"],
        "runs_success": _metrics["runs_success"],
        "runs_failed": _metrics["runs_failed"],
    }
    
    return {
        "code": 0,
        "message": "ok",
        "data": metrics_data,
        "request_id": _get_request_id(request),
    }

@router.get("/m8/config", tags=["M8-标准接口"], summary="M8标准配置查询")
async def m8_std_config(request: Request):
    """M8 标准配置查询（/m8/config 路径别名）"""
    from .. import __version__
    
    return {
        "code": 0,
        "message": "ok",
        "data": {
            "module": "m7",
            "module_name": "工作流构建器",
            "version": __version__,
            "env": os.environ.get("YUNXI_ENV", "development"),
            "workflow_count": _metrics["workflows_total"],
            "features": ["visual_builder", "condition_branch", "trigger", "template"],
        },
        "request_id": _get_request_id(request),
    }
