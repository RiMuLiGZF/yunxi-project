"""边缘计算路由.

提供边缘计算相关的 API 端点：
- POST /api/v3/edge/task/submit     - 提交边缘任务
- GET  /api/v3/edge/task/{id}       - 任务状态
- POST /api/v3/edge/function/register - 注册边缘函数
- GET  /api/v3/edge/functions       - 函数列表
- POST /api/v3/edge/function/{id}/invoke - 调用函数
- GET  /api/v3/edge/metrics         - 边缘计算指标
"""

from __future__ import annotations

import structlog
from fastapi import APIRouter, Depends, Path, Query, Request

from edge_cloud_kernel.api.dependencies import get_kernel_manager, get_trace_id
from edge_cloud_kernel.api.mock_responses import mock_response
from edge_cloud_kernel.core.kernel_manager import KernelManager

logger = structlog.get_logger(__name__)

router = APIRouter(tags=["Edge Computing"])


# ---------------------------------------------------------------------------
# 边缘任务
# ---------------------------------------------------------------------------


@router.post("/api/v3/edge/task/submit", summary="提交边缘任务")
async def submit_edge_task(
    request: Request,
    trace_id: str = Depends(get_trace_id),
    kernel: KernelManager = Depends(get_kernel_manager),
):
    """提交边缘计算任务.

    Args:
        request: FastAPI 请求对象.
        trace_id: 请求追踪 ID.
        kernel: 内核管理器.

    Returns:
        任务提交结果.
    """
    try:
        body = await request.json()
    except Exception:
        body = {}

    edge_scheduler = kernel.get_component("edge_scheduler")

    if edge_scheduler is not None and not kernel.is_mock("edge_scheduler"):
        try:
            task_id = await edge_scheduler.submit_task(
                task_data=body.get("data", {}),
                task_type=body.get("task_type", "general"),
                name=body.get("name", ""),
                priority=body.get("priority", "normal"),
                complexity=body.get("complexity", 50.0),
                latency_requirement_ms=body.get("latency_requirement_ms", -1.0),
                privacy_level=body.get("privacy_level", 3),
                strategy=body.get("strategy", "adaptive"),
            )
            return mock_response(
                data={"task_id": task_id, "status": "submitted"},
                trace_id=trace_id,
            )
        except Exception as e:
            logger.error("edge.task.submit.failed", error=str(e), trace_id=trace_id)

    # Mock 模式
    return mock_response(
        data={
            "task_id": f"task-{trace_id[:8]}",
            "status": "submitted",
            "target": "local",
            "strategy": body.get("strategy", "adaptive"),
        },
        trace_id=trace_id,
    )


@router.get("/api/v3/edge/task/{task_id}", summary="任务状态")
async def get_edge_task(
    request: Request,
    task_id: str = Path(..., description="任务 ID", min_length=2, max_length=64),
    trace_id: str = Depends(get_trace_id),
    kernel: KernelManager = Depends(get_kernel_manager),
):
    """获取边缘任务状态.

    Args:
        request: FastAPI 请求对象.
        task_id: 任务 ID.
        trace_id: 请求追踪 ID.
        kernel: 内核管理器.

    Returns:
        任务状态.
    """
    edge_scheduler = kernel.get_component("edge_scheduler")

    if edge_scheduler is not None and not kernel.is_mock("edge_scheduler"):
        try:
            task = edge_scheduler.get_task(task_id)
            if task:
                return mock_response(
                    data={
                        "task_id": task.task_id,
                        "name": task.name,
                        "status": task.status.value if hasattr(task.status, "value") else str(task.status),
                        "target": task.target.value if hasattr(task.target, "value") else str(task.target),
                        "result": task.result,
                        "error": task.error,
                        "created_at": task.created_at,
                        "started_at": task.started_at,
                        "completed_at": task.completed_at,
                    },
                    trace_id=trace_id,
                )
        except Exception as e:
            logger.error("edge.task.get.failed", error=str(e), trace_id=trace_id)

    # Mock 模式
    return mock_response(
        data={
            "task_id": task_id,
            "name": f"task-{task_id[:8]}",
            "status": "completed",
            "target": "local",
            "result": {"output": "mock result"},
            "created_at": 0,
            "started_at": 0,
            "completed_at": 0,
        },
        trace_id=trace_id,
    )


# ---------------------------------------------------------------------------
# 边缘函数
# ---------------------------------------------------------------------------


@router.post("/api/v3/edge/function/register", summary="注册边缘函数")
async def register_edge_function(
    request: Request,
    trace_id: str = Depends(get_trace_id),
    kernel: KernelManager = Depends(get_kernel_manager),
):
    """注册边缘函数.

    Args:
        request: FastAPI 请求对象.
        trace_id: 请求追踪 ID.
        kernel: 内核管理器.

    Returns:
        注册结果.
    """
    try:
        body = await request.json()
    except Exception:
        body = {}

    edge_functions = kernel.get_component("edge_functions")

    if edge_functions is not None and not kernel.is_mock("edge_functions"):
        try:
            function_id = edge_functions.register_function(
                name=body.get("name", "unnamed"),
                code=body.get("code", lambda e, c: {}),
                runtime=body.get("runtime", "python"),
                handler=body.get("handler", "handler"),
                description=body.get("description", ""),
                version=body.get("version", "1.0.0"),
                tags=body.get("tags", []),
                timeout_seconds=body.get("timeout_seconds", 30),
                memory_limit_mb=body.get("memory_limit_mb", 256),
                warm_pool_size=body.get("warm_pool_size", 1),
            )
            return mock_response(
                data={"function_id": function_id, "status": "registered"},
                trace_id=trace_id,
            )
        except Exception as e:
            logger.error("edge.function.register.failed", error=str(e), trace_id=trace_id)

    # Mock 模式
    return mock_response(
        data={
            "function_id": f"func-{trace_id[:8]}",
            "name": body.get("name", "unnamed"),
            "version": body.get("version", "1.0.0"),
            "status": "registered",
        },
        trace_id=trace_id,
    )


@router.get("/api/v3/edge/functions", summary="函数列表")
async def list_edge_functions(
    request: Request,
    page: int = Query(1, ge=1, le=10000, description="页码"),
    page_size: int = Query(20, ge=1, le=100, description="每页条数"),
    tag: str | None = Query(None, description="按标签过滤"),
    trace_id: str = Depends(get_trace_id),
    kernel: KernelManager = Depends(get_kernel_manager),
):
    """获取边缘函数列表.

    Args:
        request: FastAPI 请求对象.
        page: 页码.
        page_size: 每页条数.
        tag: 标签过滤.
        trace_id: 请求追踪 ID.
        kernel: 内核管理器.

    Returns:
        函数列表.
    """
    edge_functions = kernel.get_component("edge_functions")

    if edge_functions is not None and not kernel.is_mock("edge_functions"):
        try:
            functions = edge_functions.list_functions(tag=tag, limit=page_size)
            total = len(functions)
            items = [
                {
                    "function_id": f.function_id,
                    "name": f.name,
                    "description": f.description,
                    "status": f.status.value if hasattr(f.status, "value") else str(f.status),
                    "default_version": f.default_version,
                    "version_count": len(f.versions),
                    "timeout_seconds": f.timeout_seconds,
                    "created_at": f.created_at,
                }
                for f in functions
            ]
            return mock_response(
                data={
                    "items": items,
                    "total": total,
                    "page": page,
                    "page_size": page_size,
                },
                trace_id=trace_id,
            )
        except Exception as e:
            logger.error("edge.functions.list.failed", error=str(e), trace_id=trace_id)

    # Mock 模式
    return mock_response(
        data={
            "items": [
                {
                    "function_id": "func-mock-001",
                    "name": "image_processing",
                    "description": "Mock image processing function",
                    "status": "active",
                    "default_version": "1.0.0",
                    "version_count": 2,
                    "timeout_seconds": 30,
                    "created_at": 0,
                }
            ],
            "total": 1,
            "page": page,
            "page_size": page_size,
        },
        trace_id=trace_id,
    )


@router.post("/api/v3/edge/function/{function_id}/invoke", summary="调用函数")
async def invoke_edge_function(
    request: Request,
    function_id: str = Path(..., description="函数 ID", min_length=2, max_length=64),
    trace_id: str = Depends(get_trace_id),
    kernel: KernelManager = Depends(get_kernel_manager),
):
    """调用边缘函数.

    Args:
        request: FastAPI 请求对象.
        function_id: 函数 ID.
        trace_id: 请求追踪 ID.
        kernel: 内核管理器.

    Returns:
        函数执行结果.
    """
    try:
        body = await request.json()
    except Exception:
        body = {}

    edge_functions = kernel.get_component("edge_functions")

    if edge_functions is not None and not kernel.is_mock("edge_functions"):
        try:
            result = await edge_functions.invoke(
                function_id=function_id,
                event=body.get("event", {}),
                version=body.get("version"),
                context=body.get("context"),
            )
            return mock_response(
                data={
                    "function_id": function_id,
                    "invocation_id": result.invocation_id,
                    "success": result.success,
                    "result": result.result,
                    "error": result.error,
                    "duration_ms": result.duration_ms,
                    "cold_start": result.cold_start,
                },
                trace_id=trace_id,
            )
        except Exception as e:
            logger.error("edge.function.invoke.failed", error=str(e), trace_id=trace_id)

    # Mock 模式
    return mock_response(
        data={
            "function_id": function_id,
            "invocation_id": f"inv-{trace_id[:8]}",
            "success": True,
            "result": {"output": "mock function result"},
            "error": "",
            "duration_ms": 12.5,
            "cold_start": False,
        },
        trace_id=trace_id,
    )


# ---------------------------------------------------------------------------
# 边缘计算指标
# ---------------------------------------------------------------------------


@router.get("/api/v3/edge/metrics", summary="边缘计算指标")
async def get_edge_metrics(
    request: Request,
    trace_id: str = Depends(get_trace_id),
    kernel: KernelManager = Depends(get_kernel_manager),
):
    """获取边缘计算指标.

    Args:
        request: FastAPI 请求对象.
        trace_id: 请求追踪 ID.
        kernel: 内核管理器.

    Returns:
        边缘计算指标.
    """
    edge_scheduler = kernel.get_component("edge_scheduler")
    edge_functions = kernel.get_component("edge_functions")

    scheduler_metrics = {}
    function_metrics = {}

    if edge_scheduler is not None and not kernel.is_mock("edge_scheduler"):
        try:
            scheduler_metrics = edge_scheduler.get_metrics()
        except Exception:
            pass

    if edge_functions is not None and not kernel.is_mock("edge_functions"):
        try:
            function_metrics = edge_functions.get_metrics()
        except Exception:
            pass

    if scheduler_metrics or function_metrics:
        return mock_response(
            data={
                "scheduler": scheduler_metrics,
                "functions": function_metrics,
            },
            trace_id=trace_id,
        )

    # Mock 模式
    return mock_response(
        data={
            "scheduler": {
                "total_tasks": 100,
                "completed": 85,
                "failed": 5,
                "running": 3,
                "pending": 7,
                "local_executions": 60,
                "cloud_executions": 40,
                "device_performance_score": 72.5,
            },
            "functions": {
                "total_functions": 5,
                "active_functions": 4,
                "total_invocations": 500,
                "success_count": 480,
                "failure_count": 20,
                "cold_start_count": 50,
                "average_duration_ms": 45.2,
            },
        },
        trace_id=trace_id,
    )
