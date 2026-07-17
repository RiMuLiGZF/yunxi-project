"""
模块管理路由 — 统一管理 M1~M8 各模块的状态、健康检查与代理调用

提供 M8 管理工作台的模块管理接口：
- 模块列表 / 详情 / 健康检查 / 指标
- M1 多 Agent 管理代理（联邦 Agent、任务）
- M2 技能集群管理代理（技能列表、分类、统计、调用）

所有代理请求通过 ModuleClient 转发到对应模块，
保持统一的 {code, message, data, trace_id} 响应格式。

错误码规范（M8 模块，08 前缀）：
- 080401 = 模块不存在
- 080501 = 模块启动失败
- 080502 = 模块停止失败
- 080701 = M4 代理错误
- 080704 = 模块调用失败
"""

import sys
from pathlib import Path
from typing import Any, Optional, Dict

from fastapi import APIRouter, Depends, Query, Body

# 将项目根目录加入 path，以便导入 shared 模块
project_root = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(project_root))

from ..schemas import ApiResponse
from ..auth import get_current_user
from ..errors import M8ErrorCode
from shared.business.module_client import get_module_registry, ModuleStatus, ModuleClient
from shared.core.config import get_config
from shared.core.observability import get_logger
from shared.core.errors import ModuleCallError, NotFoundError
from shared.data.cache import get_cache, get_path_ttl

logger = get_logger("m8.modules")

router = APIRouter()
registry = get_module_registry()
config = get_config()
_cache = get_cache()


# ═══════════════════════════════════════════════════════
# 内部工具：安全代理请求
# ═══════════════════════════════════════════════════════

async def _proxy_get(module_key: str, path: str, params: Optional[Dict] = None) -> Dict[str, Any]:
    """
    代理 GET 请求到目标模块，统一处理异常

    Returns:
        解析后的 JSON 响应（已保证是 dict）
    """
    try:
        client = registry.get_client(module_key)
        result = await client.get(path, params=params)
        return result
    except Exception as exc:
        logger.warning(f"Proxy GET {module_key}{path} failed: {exc}")
        raise


async def _proxy_post(module_key: str, path: str, json_data: Optional[Dict] = None) -> Dict[str, Any]:
    """
    代理 POST 请求到目标模块，统一处理异常
    """
    try:
        client = registry.get_client(module_key)
        result = await client.post(path, json_data=json_data)
        return result
    except Exception as exc:
        logger.warning(f"Proxy POST {module_key}{path} failed: {exc}")
        raise


async def _proxy_put(module_key: str, path: str, json_data: Optional[Dict] = None) -> Dict[str, Any]:
    """
    代理 PUT 请求到目标模块，统一处理异常
    """
    try:
        client = registry.get_client(module_key)
        result = await client.put(path, json_data=json_data)
        return result
    except Exception as exc:
        logger.warning(f"Proxy PUT {module_key}{path} failed: {exc}")
        raise


async def _proxy_delete(module_key: str, path: str) -> Dict[str, Any]:
    """
    代理 DELETE 请求到目标模块，统一处理异常
    """
    try:
        client = registry.get_client(module_key)
        result = await client.delete(path)
        return result
    except Exception as exc:
        logger.warning(f"Proxy DELETE {module_key}{path} failed: {exc}")
        raise


def _module_unavailable(module_key: str, detail: str = "") -> ApiResponse:
    """模块不可用时的友好响应"""
    module = registry.get_module(module_key)
    return ApiResponse(
        code=0,
        message=f"模块 {module_key} 暂不可用",
        data={
            "key": module_key,
            "name": module.name if module else module_key,
            "status": "stopped",
            "detail": detail,
        },
    )


# ═══════════════════════════════════════════════════════
# 模块管理接口
# ═══════════════════════════════════════════════════════


@router.get("/status")
async def modules_status():
    """获取所有模块运行状态（公开接口，供入口页使用）
    使用 TCP 端口快速检测，避免 HTTP 健康检查的超时问题
    结果缓存 5 秒，避免频繁检测
    """
    import asyncio

    cache_key = "m8:modules:status"
    cached = _cache.get(cache_key)
    if cached is not None:
        return cached

    modules_status = {}
    
    async def check_port(key: str, port: int):
        try:
            reader, writer = await asyncio.wait_for(
                asyncio.open_connection("127.0.0.1", port),
                timeout=0.8
            )
            writer.close()
            await writer.wait_closed()
            modules_status[key] = {"running": True, "port": port}
        except Exception:
            modules_status[key] = {"running": False, "port": port}
    
    tasks = []
    for mod in registry.get_all_modules():
        tasks.append(check_port(mod.key, mod.port))
    
    await asyncio.gather(*tasks, return_exceptions=True)
    
    running_count = sum(1 for m in modules_status.values() if m["running"])
    
    result = {
        "code": 0,
        "message": "ok",
        "data": {
            "modules": modules_status,
            "running_count": running_count,
            "total": len(modules_status),
        },
    }

    # 缓存结果 5 秒
    _cache.set(cache_key, result, ttl=5.0, tags=["m8:modules"])

    return result


@router.get("")
async def list_modules(
    current_user: dict = Depends(get_current_user),
):
    """获取所有模块列表（带实时状态）
    结果缓存 10 秒，避免频繁健康检查
    """
    cache_key = "m8:modules:list"
    cached = _cache.get(cache_key)
    if cached is not None:
        return cached

    try:
        # 先做一次健康检查，更新状态
        await registry.check_all_health()
        summary = registry.get_status_summary()
        result = ApiResponse.success(data=summary)
        # 缓存结果 10 秒
        _cache.set(cache_key, result, ttl=10.0, tags=["m8:modules"])
        return result
    except Exception as exc:
        logger.error(f"获取模块列表失败: {exc}")
        return ApiResponse.error(code=500, message=f"获取模块列表失败: {exc}")


@router.get("/{module_key}")
async def get_module_detail(
    module_key: str,
    current_user: dict = Depends(get_current_user),
):
    """获取单个模块详情"""
    module = registry.get_module(module_key)
    if not module:
        # 使用统一 6 位错误码
        raise NotFoundError(
            message=f"未找到模块: {module_key}",
            code=M8ErrorCode.MODULE_NOT_FOUND,
            details={"module_key": module_key},
        )

    try:
        # 实时健康检查
        client = registry.get_client(module_key)
        is_healthy = await client.health_check()
        module.status = ModuleStatus.RUNNING if is_healthy else ModuleStatus.STOPPED
    except Exception:
        module.status = ModuleStatus.STOPPED

    return ApiResponse.success(data=module.to_dict())


@router.get("/{module_key}/health")
async def module_health(
    module_key: str,
    current_user: dict = Depends(get_current_user),
):
    """模块健康检查"""
    module = registry.get_module(module_key)
    if not module:
        raise NotFoundError(
            message=f"未找到模块: {module_key}",
            code=M8ErrorCode.MODULE_NOT_FOUND,
            details={"module_key": module_key},
        )

    try:
        client = registry.get_client(module_key)
        is_healthy = await client.health_check()
        module.status = ModuleStatus.RUNNING if is_healthy else ModuleStatus.STOPPED
        return ApiResponse.success(
            data={
                "key": module_key,
                "name": module.name,
                "status": module.status.value,
                "healthy": is_healthy,
                "latency_ms": module.latency_ms,
            },
            message="健康检查完成",
        )
    except Exception as exc:
        module.status = ModuleStatus.STOPPED
        return ApiResponse(
            code=0,
            message="健康检查完成",
            data={
                "key": module_key,
                "name": module.name,
                "status": "stopped",
                "healthy": False,
                "detail": str(exc),
            },
        )


@router.get("/{module_key}/metrics")
async def module_metrics(
    module_key: str,
    current_user: dict = Depends(get_current_user),
):
    """获取模块指标（如果模块提供的话）"""
    module = registry.get_module(module_key)
    if not module:
        raise NotFoundError(
            message=f"未找到模块: {module_key}",
            code=M8ErrorCode.MODULE_NOT_FOUND,
            details={"module_key": module_key},
        )

    # 尝试从常见指标端点获取（按优先级）
    metric_paths = [
        "/m8/metrics",            # M8 标准接口（所有模块统一）
        "/api/v2/stats/system",   # M2 旧版
        "/v1/federation/stats",   # M1
        "/metrics",               # 通用
    ]

    last_error = ""
    for path in metric_paths:
        try:
            result = await _proxy_get(module_key, path)
            return ApiResponse.success(data=result.get("data", result))
        except Exception as exc:
            last_error = str(exc)
            continue

    # 没有可用的指标接口，返回基本状态
    return _module_unavailable(module_key, f"暂无指标数据: {last_error}")


# ═══════════════════════════════════════════════════════
# M1 多 Agent 管理（代理到 M1 联邦调度系统）
# ═══════════════════════════════════════════════════════


@router.get("/m1/agents")
async def m1_list_agents(
    agent_type: Optional[str] = Query(None, description="按 Agent 类型筛选"),
    status: Optional[str] = Query(None, description="按状态筛选"),
    current_user: dict = Depends(get_current_user),
):
    """获取 M1 联邦 Agent 列表（代理到 M1）"""
    try:
        params = {}
        if agent_type:
            params["agent_type"] = agent_type
        if status:
            params["status"] = status

        result = await _proxy_get("m1", "/v1/federation/agents", params=params if params else None)
        # 透传 data 字段，保持统一格式
        data = result.get("data", result)
        return ApiResponse.success(data=data)
    except Exception as exc:
        return _module_unavailable("m1", str(exc))


@router.get("/m1/agents/{agent_id}")
async def m1_get_agent(
    agent_id: str,
    current_user: dict = Depends(get_current_user),
):
    """获取 M1 单个 Agent 详情（代理到 M1）"""
    try:
        result = await _proxy_get("m1", f"/v1/federation/agents/{agent_id}")
        data = result.get("data", result)
        return ApiResponse.success(data=data)
    except Exception as exc:
        return _module_unavailable("m1", str(exc))


@router.get("/m1/tasks")
async def m1_list_tasks(
    limit: int = Query(20, description="返回数量", ge=1, le=100),
    offset: int = Query(0, description="偏移量", ge=0),
    status: Optional[str] = Query(None, description="任务状态筛选"),
    current_user: dict = Depends(get_current_user),
):
    """获取 M1 任务列表（代理到 M1）"""
    try:
        # M1 的任务接口：通过 /api/v1/tasks 列表（如果存在）或从 ledger 查询
        # 尝试多个路径
        params = {"limit": limit, "offset": offset}
        if status:
            params["status"] = status

        try:
            result = await _proxy_get("m1", "/api/v1/tasks", params=params)
            data = result.get("data", result)
            return ApiResponse.success(data=data)
        except Exception:
            # 回退：返回空列表和模块信息
            pass

        # 如果标准接口不可用，尝试获取健康信息作为替代
        client = registry.get_client("m1")
        healthy = await client.health_check()
        return ApiResponse(
            code=0,
            message="ok",
            data={
                "total": 0,
                "items": [],
                "module_healthy": healthy,
                "note": "任务列表接口暂不可用",
            },
        )
    except Exception as exc:
        return _module_unavailable("m1", str(exc))


@router.get("/m1/tasks/{task_id}")
async def m1_get_task(
    task_id: str,
    current_user: dict = Depends(get_current_user),
):
    """获取 M1 单个任务详情（代理到 M1）"""
    try:
        result = await _proxy_get("m1", f"/api/v1/tasks/{task_id}/status")
        data = result.get("data", result)
        return ApiResponse.success(data=data)
    except Exception as exc:
        return _module_unavailable("m1", str(exc))


@router.post("/m1/tasks")
async def m1_submit_task(
    body: dict = Body(..., description="任务提交参数"),
    current_user: dict = Depends(get_current_user),
):
    """提交任务到 M1（代理到 M1）"""
    try:
        result = await _proxy_post("m1", "/api/v1/tasks/submit", json_data=body)
        data = result.get("data", result)
        return ApiResponse.success(data=data, message="任务提交成功")
    except Exception as exc:
        return _module_unavailable("m1", str(exc))


# ═══════════════════════════════════════════════════════
# M2 技能集群管理（代理到 M2）
# ═══════════════════════════════════════════════════════


@router.get("/m2/skills")
async def m2_list_skills(
    category: Optional[str] = Query(None, description="按分类筛选"),
    keyword: Optional[str] = Query(None, description="关键词搜索"),
    limit: int = Query(50, description="返回数量", ge=1, le=200),
    offset: int = Query(0, description="偏移量", ge=0),
    current_user: dict = Depends(get_current_user),
):
    """获取 M2 技能列表（代理到 M2 /api/v2/skills）"""
    try:
        params = {"limit": limit, "offset": offset}
        if category:
            params["category"] = category
        if keyword:
            params["keyword"] = keyword

        result = await _proxy_get("m2", "/api/v2/skills", params=params)
        data = result.get("data", result)
        return ApiResponse.success(data=data)
    except Exception as exc:
        return _module_unavailable("m2", str(exc))


@router.get("/m2/skills/{skill_id}")
async def m2_get_skill(
    skill_id: str,
    current_user: dict = Depends(get_current_user),
):
    """获取 M2 单个技能详情（代理到 M2）"""
    try:
        result = await _proxy_get("m2", f"/api/v2/skills/{skill_id}")
        data = result.get("data", result)
        return ApiResponse.success(data=data)
    except Exception as exc:
        return _module_unavailable("m2", str(exc))


@router.get("/m2/categories")
async def m2_list_categories(
    current_user: dict = Depends(get_current_user),
):
    """获取 M2 技能分类（代理到 M2）"""
    try:
        result = await _proxy_get("m2", "/api/v2/categories")
        data = result.get("data", result)
        return ApiResponse.success(data=data)
    except Exception as exc:
        return _module_unavailable("m2", str(exc))


@router.get("/m2/stats")
async def m2_stats(
    current_user: dict = Depends(get_current_user),
):
    """获取 M2 技能统计（聚合 accuracy / invocations / system）"""
    try:
        stats = {}

        # 并行获取各类统计（串行，保持简单）
        for stat_type in ["system", "accuracy", "invocations"]:
            try:
                result = await _proxy_get("m2", f"/api/v2/stats/{stat_type}")
                stats[stat_type] = result.get("data", result)
            except Exception:
                stats[stat_type] = None

        return ApiResponse.success(data=stats)
    except Exception as exc:
        return _module_unavailable("m2", str(exc))


@router.post("/m2/skills/invoke")
async def m2_invoke_skill(
    body: dict = Body(..., description="技能调用参数: {skill_id, params}"),
    current_user: dict = Depends(get_current_user),
):
    """调用 M2 技能（代理到 M2）"""
    try:
        skill_id = body.get("skill_id", "")
        if not skill_id:
            return ApiResponse.error(code=400, message="缺少 skill_id 参数")

        invoke_params = body.get("params", {})
        result = await _proxy_post("m2", "/api/v2/skills/invoke", json_data=body)
        data = result.get("data", result)
        return ApiResponse.success(data=data, message="技能调用完成")
    except Exception as exc:
        return _module_unavailable("m2", str(exc))


# ═══════════════════════════════════════════════════════
# M3 端云协同管理（代理到 M3）
# ═══════════════════════════════════════════════════════


# ---------- 同步管理 ----------

@router.get("/m3/sync/status")
async def m3_sync_status(
    current_user: dict = Depends(get_current_user),
):
    """获取 M3 同步状态（代理到 M3）"""
    try:
        result = await _proxy_get("m3", "/api/v3/sync/status")
        data = result.get("data", result)
        return ApiResponse.success(data=data)
    except Exception as exc:
        return _module_unavailable("m3", str(exc))


@router.post("/m3/sync/trigger")
async def m3_sync_trigger(
    body: dict = Body(..., description="同步触发参数"),
    current_user: dict = Depends(get_current_user),
):
    """触发 M3 同步（代理到 M3）"""
    try:
        result = await _proxy_post("m3", "/api/v3/sync/trigger", json_data=body)
        data = result.get("data", result)
        return ApiResponse.success(data=data, message="同步触发成功")
    except Exception as exc:
        return _module_unavailable("m3", str(exc))


@router.get("/m3/sync/conflicts")
async def m3_sync_conflicts(
    page: int = Query(1, description="页码", ge=1),
    page_size: int = Query(20, description="每页数量", ge=1, le=200),
    current_user: dict = Depends(get_current_user),
):
    """获取 M3 同步冲突列表（代理到 M3）"""
    try:
        params = {"page": page, "page_size": page_size}
        result = await _proxy_get("m3", "/api/v3/sync/conflicts", params=params)
        data = result.get("data", result)
        return ApiResponse.success(data=data)
    except Exception as exc:
        return _module_unavailable("m3", str(exc))


@router.post("/m3/sync/conflicts/{conflict_id}/resolve")
async def m3_resolve_conflict(
    conflict_id: str,
    body: dict = Body(..., description="冲突解决参数"),
    current_user: dict = Depends(get_current_user),
):
    """解决 M3 同步冲突（代理到 M3）"""
    try:
        result = await _proxy_post("m3", f"/api/v3/sync/conflicts/{conflict_id}/resolve", json_data=body)
        data = result.get("data", result)
        return ApiResponse.success(data=data, message="冲突已解决")
    except Exception as exc:
        return _module_unavailable("m3", str(exc))


# ---------- 设备管理 ----------

@router.get("/m3/devices")
async def m3_list_devices(
    page: int = Query(1, description="页码", ge=1),
    page_size: int = Query(20, description="每页数量", ge=1, le=200),
    status: Optional[str] = Query(None, description="按设备状态筛选"),
    current_user: dict = Depends(get_current_user),
):
    """获取 M3 设备列表（代理到 M3）"""
    try:
        params = {"page": page, "page_size": page_size}
        if status:
            params["status"] = status

        result = await _proxy_get("m3", "/api/v3/devices", params=params)
        data = result.get("data", result)
        return ApiResponse.success(data=data)
    except Exception as exc:
        return _module_unavailable("m3", str(exc))


@router.post("/m3/devices/{device_id}/remove")
async def m3_remove_device(
    device_id: str,
    current_user: dict = Depends(get_current_user),
):
    """移除 M3 设备（代理到 M3）"""
    try:
        result = await _proxy_post("m3", f"/api/v3/devices/{device_id}/remove")
        data = result.get("data", result)
        return ApiResponse.success(data=data, message="设备已移除")
    except Exception as exc:
        return _module_unavailable("m3", str(exc))


# ═══════════════════════════════════════════════════════
# M4 场景引擎代理（代理到 M4）
# ═══════════════════════════════════════════════════════


# ---------- 场景管理 ----------

@router.get("/m4/scenes")
async def m4_list_scenes(
    current_user: dict = Depends(get_current_user),
):
    """获取 M4 场景列表（代理到 M4）"""
    try:
        result = await _proxy_get("m4", "/api/v1/scenes")
        return ApiResponse.success(data=result.get("data", result))
    except Exception as exc:
        return _module_unavailable("m4", str(exc))


@router.get("/m4/scene/current")
async def m4_current_scene(
    current_user: dict = Depends(get_current_user),
):
    """获取 M4 当前场景（代理到 M4）"""
    try:
        result = await _proxy_get("m4", "/api/v1/scene/current")
        return ApiResponse.success(data=result.get("data", result))
    except Exception as exc:
        return _module_unavailable("m4", str(exc))


@router.post("/m4/scene/switch")
async def m4_switch_scene(
    body: dict = Body(..., description="切换场景参数"),
    current_user: dict = Depends(get_current_user),
):
    """切换 M4 场景（代理到 M4）"""
    try:
        result = await _proxy_post("m4", "/api/v1/scene/switch", json_data=body)
        return ApiResponse.success(data=result.get("data", result), message="场景切换成功")
    except Exception as exc:
        return _module_unavailable("m4", str(exc))


@router.post("/m4/scene/recognize")
async def m4_recognize_scene(
    body: dict = Body(..., description="场景识别参数"),
    current_user: dict = Depends(get_current_user),
):
    """M4 场景识别（代理到 M4）"""
    try:
        result = await _proxy_post("m4", "/api/v1/scene/recognize", json_data=body)
        return ApiResponse.success(data=result.get("data", result), message="场景识别完成")
    except Exception as exc:
        return _module_unavailable("m4", str(exc))


@router.get("/m4/scene/history")
async def m4_scene_history(
    current_user: dict = Depends(get_current_user),
):
    """获取 M4 场景切换历史（代理到 M4）"""
    try:
        result = await _proxy_get("m4", "/api/v1/scene/history")
        return ApiResponse.success(data=result.get("data", result))
    except Exception as exc:
        return _module_unavailable("m4", str(exc))


@router.get("/m4/scene/{scene_id}/config")
async def m4_get_scene_config(
    scene_id: str,
    current_user: dict = Depends(get_current_user),
):
    """获取 M4 场景配置（代理到 M4）"""
    try:
        result = await _proxy_get("m4", f"/api/v1/scene/{scene_id}/config")
        return ApiResponse.success(data=result.get("data", result))
    except Exception as exc:
        return _module_unavailable("m4", str(exc))


@router.post("/m4/scene/{scene_id}/config")
async def m4_update_scene_config(
    scene_id: str,
    body: dict = Body(..., description="场景配置参数"),
    current_user: dict = Depends(get_current_user),
):
    """更新 M4 场景配置（代理到 M4）"""
    try:
        result = await _proxy_post("m4", f"/api/v1/scene/{scene_id}/config", json_data=body)
        return ApiResponse.success(data=result.get("data", result), message="配置更新成功")
    except Exception as exc:
        return _module_unavailable("m4", str(exc))


# ---------- 上下文管理 ----------

@router.get("/m4/context/status")
async def m4_context_status(
    current_user: dict = Depends(get_current_user),
):
    """获取 M4 上下文状态（代理到 M4）"""
    try:
        result = await _proxy_get("m4", "/api/v1/context/status")
        return ApiResponse.success(data=result.get("data", result))
    except Exception as exc:
        return _module_unavailable("m4", str(exc))


@router.get("/m4/context/{scene_id}")
async def m4_get_context(
    scene_id: str,
    current_user: dict = Depends(get_current_user),
):
    """获取 M4 场景上下文（代理到 M4）"""
    try:
        result = await _proxy_get("m4", f"/api/v1/context/{scene_id}")
        return ApiResponse.success(data=result.get("data", result))
    except Exception as exc:
        return _module_unavailable("m4", str(exc))


@router.post("/m4/context/{scene_id}")
async def m4_save_context(
    scene_id: str,
    body: dict = Body(..., description="上下文数据"),
    current_user: dict = Depends(get_current_user),
):
    """保存 M4 场景上下文（代理到 M4）"""
    try:
        result = await _proxy_post("m4", f"/api/v1/context/{scene_id}", json_data=body)
        return ApiResponse.success(data=result.get("data", result), message="上下文保存成功")
    except Exception as exc:
        return _module_unavailable("m4", str(exc))


@router.delete("/m4/context/{scene_id}")
async def m4_clear_context(
    scene_id: str,
    current_user: dict = Depends(get_current_user),
):
    """清空 M4 场景上下文（代理到 M4）"""
    try:
        result = await _proxy_delete("m4", f"/api/v1/context/{scene_id}")
        return ApiResponse.success(data=result.get("data", result), message="上下文已清空")
    except Exception as exc:
        return _module_unavailable("m4", str(exc))


# ---------- 管理 ----------

@router.get("/m4/admin/config")
async def m4_admin_config(
    current_user: dict = Depends(get_current_user),
):
    """获取 M4 全局配置（代理到 M4）"""
    try:
        result = await _proxy_get("m4", "/api/v1/admin/config")
        return ApiResponse.success(data=result.get("data", result))
    except Exception as exc:
        return _module_unavailable("m4", str(exc))


@router.put("/m4/admin/config")
async def m4_update_admin_config(
    body: dict = Body(..., description="全局配置参数"),
    current_user: dict = Depends(get_current_user),
):
    """更新 M4 全局配置（代理到 M4）"""
    try:
        result = await _proxy_put("m4", "/api/v1/admin/config", json_data=body)
        return ApiResponse.success(data=result.get("data", result), message="配置更新成功")
    except Exception as exc:
        return _module_unavailable("m4", str(exc))


@router.get("/m4/admin/metrics")
async def m4_admin_metrics(
    current_user: dict = Depends(get_current_user),
):
    """获取 M4 运行指标（代理到 M4）"""
    try:
        result = await _proxy_get("m4", "/api/v1/admin/metrics")
        return ApiResponse.success(data=result.get("data", result))
    except Exception as exc:
        return _module_unavailable("m4", str(exc))


# ═══════════════════════════════════════════════════════
# M7 积木平台代理（代理到 M7）
# ═══════════════════════════════════════════════════════


# ---------- 工作流 ----------

@router.get("/m7/workflows")
async def m7_list_workflows(
    current_user: dict = Depends(get_current_user),
):
    """获取 M7 工作流列表（代理到 M7）"""
    try:
        result = await _proxy_get("m7", "/api/v1/workflows")
        return ApiResponse.success(data=result.get("data", result))
    except Exception as exc:
        return _module_unavailable("m7", str(exc))


@router.post("/m7/workflows")
async def m7_create_workflow(
    body: dict = Body(..., description="工作流参数"),
    current_user: dict = Depends(get_current_user),
):
    """创建 M7 工作流（代理到 M7）"""
    try:
        result = await _proxy_post("m7", "/api/v1/workflows", json_data=body)
        return ApiResponse.success(data=result.get("data", result), message="工作流创建成功")
    except Exception as exc:
        return _module_unavailable("m7", str(exc))


@router.get("/m7/workflows/{id}")
async def m7_get_workflow(
    id: str,
    current_user: dict = Depends(get_current_user),
):
    """获取 M7 工作流详情（代理到 M7）"""
    try:
        result = await _proxy_get("m7", f"/api/v1/workflows/{id}")
        return ApiResponse.success(data=result.get("data", result))
    except Exception as exc:
        return _module_unavailable("m7", str(exc))


@router.put("/m7/workflows/{id}")
async def m7_update_workflow(
    id: str,
    body: dict = Body(..., description="工作流参数"),
    current_user: dict = Depends(get_current_user),
):
    """更新 M7 工作流（代理到 M7）"""
    try:
        result = await _proxy_put("m7", f"/api/v1/workflows/{id}", json_data=body)
        return ApiResponse.success(data=result.get("data", result), message="工作流更新成功")
    except Exception as exc:
        return _module_unavailable("m7", str(exc))


@router.delete("/m7/workflows/{id}")
async def m7_delete_workflow(
    id: str,
    current_user: dict = Depends(get_current_user),
):
    """删除 M7 工作流（代理到 M7）"""
    try:
        result = await _proxy_delete("m7", f"/api/v1/workflows/{id}")
        return ApiResponse.success(data=result.get("data", result), message="工作流已删除")
    except Exception as exc:
        return _module_unavailable("m7", str(exc))


@router.post("/m7/workflows/{id}/duplicate")
async def m7_duplicate_workflow(
    id: str,
    current_user: dict = Depends(get_current_user),
):
    """复制 M7 工作流（代理到 M7）"""
    try:
        result = await _proxy_post("m7", f"/api/v1/workflows/{id}/duplicate")
        return ApiResponse.success(data=result.get("data", result), message="工作流复制成功")
    except Exception as exc:
        return _module_unavailable("m7", str(exc))


@router.post("/m7/workflows/{id}/run")
async def m7_run_workflow(
    id: str,
    body: dict = Body(..., description="运行参数"),
    current_user: dict = Depends(get_current_user),
):
    """运行 M7 工作流（代理到 M7）"""
    try:
        result = await _proxy_post("m7", f"/api/v1/workflows/{id}/run", json_data=body)
        return ApiResponse.success(data=result.get("data", result), message="工作流运行中")
    except Exception as exc:
        return _module_unavailable("m7", str(exc))


# ---------- 运行历史 ----------

@router.get("/m7/workflows/{id}/runs")
async def m7_workflow_runs(
    id: str,
    current_user: dict = Depends(get_current_user),
):
    """获取 M7 工作流运行历史（代理到 M7）"""
    try:
        result = await _proxy_get("m7", f"/api/v1/workflows/{id}/runs")
        return ApiResponse.success(data=result.get("data", result))
    except Exception as exc:
        return _module_unavailable("m7", str(exc))


@router.get("/m7/runs/{run_id}")
async def m7_get_run(
    run_id: str,
    current_user: dict = Depends(get_current_user),
):
    """获取 M7 运行详情（代理到 M7）"""
    try:
        result = await _proxy_get("m7", f"/api/v1/runs/{run_id}")
        return ApiResponse.success(data=result.get("data", result))
    except Exception as exc:
        return _module_unavailable("m7", str(exc))


# ---------- 积木 ----------

@router.get("/m7/blocks")
async def m7_list_blocks(
    current_user: dict = Depends(get_current_user),
):
    """获取 M7 积木列表（代理到 M7）"""
    try:
        result = await _proxy_get("m7", "/api/v1/blocks")
        return ApiResponse.success(data=result.get("data", result))
    except Exception as exc:
        return _module_unavailable("m7", str(exc))


@router.get("/m7/blocks/categories")
async def m7_block_categories(
    current_user: dict = Depends(get_current_user),
):
    """获取 M7 积木分类（代理到 M7）"""
    try:
        result = await _proxy_get("m7", "/api/v1/blocks/categories")
        return ApiResponse.success(data=result.get("data", result))
    except Exception as exc:
        return _module_unavailable("m7", str(exc))


@router.get("/m7/blocks/{block_id}")
async def m7_get_block(
    block_id: str,
    current_user: dict = Depends(get_current_user),
):
    """获取 M7 积木详情（代理到 M7）"""
    try:
        result = await _proxy_get("m7", f"/api/v1/blocks/{block_id}")
        return ApiResponse.success(data=result.get("data", result))
    except Exception as exc:
        return _module_unavailable("m7", str(exc))


# ---------- 模板 ----------

@router.get("/m7/templates")
async def m7_list_templates(
    current_user: dict = Depends(get_current_user),
):
    """获取 M7 模板列表（代理到 M7）"""
    try:
        result = await _proxy_get("m7", "/api/v1/templates")
        return ApiResponse.success(data=result.get("data", result))
    except Exception as exc:
        return _module_unavailable("m7", str(exc))


@router.get("/m7/templates/{id}")
async def m7_get_template(
    id: str,
    current_user: dict = Depends(get_current_user),
):
    """获取 M7 模板详情（代理到 M7）"""
    try:
        result = await _proxy_get("m7", f"/api/v1/templates/{id}")
        return ApiResponse.success(data=result.get("data", result))
    except Exception as exc:
        return _module_unavailable("m7", str(exc))


@router.post("/m7/templates/{id}/apply")
async def m7_apply_template(
    id: str,
    body: dict = Body(..., description="应用模板参数"),
    current_user: dict = Depends(get_current_user),
):
    """应用 M7 模板（代理到 M7）"""
    try:
        result = await _proxy_post("m7", f"/api/v1/templates/{id}/apply", json_data=body)
        return ApiResponse.success(data=result.get("data", result), message="模板应用成功")
    except Exception as exc:
        return _module_unavailable("m7", str(exc))


# ═══════════════════════════════════════════════════════
# 模块注册表管理 API (CQ-001, P1级)
# ═══════════════════════════════════════════════════════
#
# 基于 ModuleRegistry 的模块管理接口，支持：
# - 列出所有已注册模块（含配置信息）
# - 获取模块详情
# - 启用/禁用模块
# - 动态注册/注销模块
# - 修改模块配置
# - 保存配置到文件
# - 模块自注册（心跳上报）
#
# 注：这些接口操作的是内存中的注册表，
#     调用 /save 才会持久化到 config/modules.yaml

from shared.core.module_registry import (
    ModuleRegistry,
    ModuleInfo,
    ModuleCategory,
    ModuleStatus,
    get_module_registry as get_core_module_registry,
)

_core_registry = get_core_module_registry()


@router.get("/registry/list")
async def registry_list_modules(
    category: Optional[str] = Query(None, description="按分类筛选"),
    enabled_only: bool = Query(False, description="是否只返回启用的模块"),
    current_user: dict = Depends(get_current_user),
):
    """
    获取注册表中的所有模块列表（含完整配置信息）。

    CQ-001: 基于 ModuleRegistry 的模块列表接口，
    比 GET /modules 更详细，包含启动配置、优先级等。
    """
    try:
        modules = _core_registry.list_modules(
            category=category,
            enabled_only=enabled_only,
        )
        data = [m.to_dict(include_runtime=True) for m in modules]
        return ApiResponse.success(
            data={
                "items": data,
                "total": len(data),
                "summary": _core_registry.get_status_summary(),
            },
            message="获取模块列表成功",
        )
    except Exception as exc:
        logger.error(f"获取注册表模块列表失败: {exc}")
        return ApiResponse.error(code=500, message=f"获取模块列表失败: {exc}")


@router.get("/registry/{module_id}")
async def registry_get_module(
    module_id: str,
    current_user: dict = Depends(get_current_user),
):
    """获取指定模块的详细配置信息"""
    module = _core_registry.get_module(module_id)
    if not module:
        raise NotFoundError(
            message=f"未找到模块: {module_id}",
            code=M8ErrorCode.MODULE_NOT_FOUND,
            details={"module_id": module_id},
        )

    return ApiResponse.success(data=module.to_dict(include_runtime=True))


@router.post("/registry/register")
async def registry_register_module(
    body: dict = Body(..., description="模块配置信息"),
    current_user: dict = Depends(get_current_user),
):
    """
    动态注册新模块。

    请求体示例：
    {
        "id": "m13",
        "name": "新模块",
        "port": 8013,
        "directory": "M13-new-module",
        "start_command": "python server.py",
        "category": "core",
        "priority": 50,
        "enabled": true
    }
    """
    try:
        module_info = ModuleInfo(**body)
        result = _core_registry.register_module(module_info)
        logger.info(f"模块 {module_info.id} 已通过 API 注册")
        return ApiResponse.success(
            data=result.to_dict(),
            message=f"模块 {module_info.id} 注册成功",
        )
    except Exception as exc:
        logger.error(f"注册模块失败: {exc}")
        return ApiResponse.error(code=400, message=f"注册模块失败: {exc}")


@router.delete("/registry/{module_id}")
async def registry_unregister_module(
    module_id: str,
    current_user: dict = Depends(get_current_user),
):
    """注销模块（从注册表中移除）"""
    if not _core_registry.has_module(module_id):
        raise NotFoundError(
            message=f"未找到模块: {module_id}",
            code=M8ErrorCode.MODULE_NOT_FOUND,
            details={"module_id": module_id},
        )

    success = _core_registry.unregister_module(module_id)
    if success:
        logger.info(f"模块 {module_id} 已通过 API 注销")
        return ApiResponse.success(message=f"模块 {module_id} 注销成功")
    else:
        return ApiResponse.error(code=500, message=f"模块 {module_id} 注销失败")


@router.put("/registry/{module_id}")
async def registry_update_module(
    module_id: str,
    body: dict = Body(..., description="要更新的模块配置字段"),
    current_user: dict = Depends(get_current_user),
):
    """
    更新模块配置。

    可更新字段：name, port, directory, start_command, priority,
                enabled, category, health_check_path, description 等
    """
    if not _core_registry.has_module(module_id):
        raise NotFoundError(
            message=f"未找到模块: {module_id}",
            code=M8ErrorCode.MODULE_NOT_FOUND,
            details={"module_id": module_id},
        )

    try:
        # 不允许修改 id
        body.pop("id", None)
        result = _core_registry.update_module(module_id, **body)
        if result:
            return ApiResponse.success(
                data=result.to_dict(),
                message=f"模块 {module_id} 更新成功",
            )
        else:
            return ApiResponse.error(code=500, message=f"模块 {module_id} 更新失败")
    except Exception as exc:
        logger.error(f"更新模块 {module_id} 失败: {exc}")
        return ApiResponse.error(code=400, message=f"更新模块失败: {exc}")


@router.post("/registry/{module_id}/enable")
async def registry_enable_module(
    module_id: str,
    current_user: dict = Depends(get_current_user),
):
    """启用模块"""
    if not _core_registry.has_module(module_id):
        raise NotFoundError(
            message=f"未找到模块: {module_id}",
            code=M8ErrorCode.MODULE_NOT_FOUND,
            details={"module_id": module_id},
        )

    _core_registry.enable_module(module_id)
    return ApiResponse.success(message=f"模块 {module_id} 已启用")


@router.post("/registry/{module_id}/disable")
async def registry_disable_module(
    module_id: str,
    current_user: dict = Depends(get_current_user),
):
    """禁用模块"""
    if not _core_registry.has_module(module_id):
        raise NotFoundError(
            message=f"未找到模块: {module_id}",
            code=M8ErrorCode.MODULE_NOT_FOUND,
            details={"module_id": module_id},
        )

    _core_registry.disable_module(module_id)
    return ApiResponse.success(message=f"模块 {module_id} 已禁用")


@router.post("/registry/save")
async def registry_save_config(
    current_user: dict = Depends(get_current_user),
):
    """
    保存当前注册表配置到 config/modules.yaml。

    将内存中的配置持久化到配置文件，重启后仍然有效。
    """
    try:
        success = _core_registry.save()
        if success:
            path = str(_core_registry.config_path) if _core_registry.config_path else "默认路径"
            return ApiResponse.success(
                data={"saved_to": path},
                message="配置已保存",
            )
        else:
            return ApiResponse.error(code=500, message="保存配置失败")
    except Exception as exc:
        logger.error(f"保存配置失败: {exc}")
        return ApiResponse.error(code=500, message=f"保存配置失败: {exc}")


@router.post("/registry/reload")
async def registry_reload_config(
    current_user: dict = Depends(get_current_user),
):
    """重新从配置文件加载模块配置"""
    try:
        count = _core_registry.reload()
        return ApiResponse.success(
            data={"module_count": count},
            message=f"配置已重新加载，共 {count} 个模块",
        )
    except Exception as exc:
        logger.error(f"重新加载配置失败: {exc}")
        return ApiResponse.error(code=500, message=f"重新加载配置失败: {exc}")


@router.get("/registry/status/summary")
async def registry_status_summary(
    current_user: dict = Depends(get_current_user),
):
    """获取模块状态汇总统计"""
    summary = _core_registry.get_status_summary()
    return ApiResponse.success(data=summary)


@router.get("/registry/startup/order")
async def registry_startup_order(
    enabled_only: bool = Query(True, description="是否只包含启用的模块"),
    current_user: dict = Depends(get_current_user),
):
    """获取模块启动顺序（按优先级排序）"""
    modules = _core_registry.get_startup_order(enabled_only=enabled_only)
    data = [
        {
            "id": m.id,
            "name": m.name,
            "priority": m.priority,
            "port": m.port,
            "category": m.category.value,
            "enabled": m.enabled,
        }
        for m in modules
    ]
    return ApiResponse.success(
        data={"items": data, "total": len(data)},
        message="获取启动顺序成功",
    )


# ---- 模块自注册 / 心跳接口（公开，供模块调用） ----

@router.post("/registry/heartbeat")
async def registry_module_heartbeat(
    body: dict = Body(..., description="心跳数据"),
):
    """
    模块心跳上报接口（模块自注册用）。

    各模块启动后定期调用此接口上报心跳，
    注册中心据此跟踪模块健康状态。

    请求体：
    {
        "module_id": "m8",
        "status": "running",   // 可选
        "metrics": {...}       // 可选，附加指标
    }
    """
    module_id = body.get("module_id", "")
    if not module_id:
        return ApiResponse.error(code=400, message="缺少 module_id 参数")

    status = body.get("status", None)
    success = _core_registry.heartbeat(module_id, status=status)

    if success:
        return ApiResponse.success(
            data={"module_id": module_id, "received": True},
            message="心跳已接收",
        )
    else:
        # 模块未注册，返回提示
        return ApiResponse(
            code=0,
            message="模块未注册，请先调用 /register 接口",
            data={"module_id": module_id, "registered": False},
        )


@router.post("/registry/self-register")
async def registry_self_register(
    body: dict = Body(..., description="模块自注册信息"),
):
    """
    模块自注册接口（公开，供各模块启动时调用）。

    请求体示例：
    {
        "id": "m13",
        "name": "新模块",
        "port": 8013,
        "category": "core",
        "version": "v1.0.0"
    }
    """
    try:
        # 自注册的模块默认优先级较高（动态发现）
        if "priority" not in body:
            body["priority"] = 50
        if "enabled" not in body:
            body["enabled"] = True

        module_info = ModuleInfo(**body)

        # 如果已存在，更新状态为 running
        existing = _core_registry.get_module(module_info.id)
        if existing:
            existing.status = ModuleStatus.RUNNING
            existing.last_heartbeat = __import__("time").time()
            logger.info(f"模块 {module_info.id} 自注册（已存在，更新状态）")
            return ApiResponse.success(
                data=existing.to_dict(),
                message=f"模块 {module_info.id} 已注册，状态已更新",
            )

        result = _core_registry.register_module(module_info)
        logger.info(f"模块 {module_info.id} 自注册成功")
        return ApiResponse.success(
            data=result.to_dict(),
            message=f"模块 {module_info.id} 自注册成功",
        )
    except Exception as exc:
        logger.error(f"模块自注册失败: {exc}")
        return ApiResponse.error(code=400, message=f"自注册失败: {exc}")
