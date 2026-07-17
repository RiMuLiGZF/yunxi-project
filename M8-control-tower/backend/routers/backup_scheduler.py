"""
备份调度中心路由 — 全系统备份的统一管理入口

提供以下接口：
- 模块管理：注册/更新/删除/查询备份模块
- 备份执行：触发全系统备份、单模块备份
- 历史查询：备份历史记录、统计分析
- 调度状态：调度器运行状态查询

所有接口遵循 M8 统一的 {code, message, data} 响应格式。
"""

import sys
from pathlib import Path
from typing import Optional, Dict, Any

from fastapi import APIRouter, Depends, Query, Body, HTTPException

# 将项目根目录加入 path，以便导入 shared 模块
project_root = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(project_root))

from ..schemas import ApiResponse
from ..auth import get_current_user
from ..services.backup_scheduler import get_backup_orchestrator_service
from shared.logger import get_logger

logger = get_logger("m8.backup_scheduler.router")

router = APIRouter()
orchestrator = get_backup_orchestrator_service()


# ============================================================
# 模块管理接口
# ============================================================

@router.get("/modules", summary="列出所有注册的备份模块")
async def list_modules(
    current_user: dict = Depends(get_current_user),
):
    """获取所有已注册的备份模块列表"""
    try:
        modules = orchestrator.list_modules()
        return ApiResponse.success(data={
            "total": len(modules),
            "items": modules,
        })
    except Exception as exc:
        logger.error(f"获取模块列表失败: {exc}")
        return ApiResponse.error(code=500, message=f"获取模块列表失败: {exc}")


@router.post("/modules", summary="注册新的备份模块")
async def register_module(
    body: dict = Body(..., description="模块配置"),
    current_user: dict = Depends(get_current_user),
):
    """注册新的备份模块

    请求体字段：
    - module_id: 模块唯一标识（必填）
    - module_name: 模块显示名称
    - backup_endpoint: 备份API端点URL
    - auth_token: 认证Token
    - schedule_type: 调度类型：daily/interval/none
    - schedule_time: 每日备份时间，如 "03:00"
    - schedule_interval_minutes: 间隔分钟数
    - enabled: 是否启用
    - max_backups: 最大保留备份数
    - description: 模块描述
    - extra_config: 扩展配置（JSON）
    """
    try:
        result = orchestrator.register_module(body)
        if result.get("success"):
            return ApiResponse.success(
                data=result.get("module"),
                message="模块注册成功",
            )
        else:
            return ApiResponse.error(
                code=400,
                message=result.get("error", "注册失败"),
            )
    except Exception as exc:
        logger.error(f"注册模块失败: {exc}")
        return ApiResponse.error(code=500, message=f"注册模块失败: {exc}")


@router.get("/modules/{module_id}", summary="获取模块详情")
async def get_module(
    module_id: str,
    current_user: dict = Depends(get_current_user),
):
    """获取指定备份模块的配置详情"""
    try:
        module = orchestrator.get_module(module_id)
        if not module:
            return ApiResponse.error(code=404, message=f"未找到模块: {module_id}")
        return ApiResponse.success(data=module)
    except Exception as exc:
        logger.error(f"获取模块详情失败: {exc}")
        return ApiResponse.error(code=500, message=f"获取模块详情失败: {exc}")


@router.put("/modules/{module_id}", summary="更新模块配置")
async def update_module(
    module_id: str,
    body: dict = Body(..., description="更新的配置"),
    current_user: dict = Depends(get_current_user),
):
    """更新指定备份模块的配置"""
    try:
        result = orchestrator.update_module(module_id, body)
        if result.get("success"):
            return ApiResponse.success(
                data=result.get("module"),
                message="模块配置更新成功",
            )
        else:
            return ApiResponse.error(
                code=400,
                message=result.get("error", "更新失败"),
            )
    except Exception as exc:
        logger.error(f"更新模块配置失败: {exc}")
        return ApiResponse.error(code=500, message=f"更新模块配置失败: {exc}")


@router.delete("/modules/{module_id}", summary="删除备份模块")
async def delete_module(
    module_id: str,
    current_user: dict = Depends(get_current_user),
):
    """删除指定的备份模块"""
    try:
        result = orchestrator.delete_module(module_id)
        if result.get("success"):
            return ApiResponse.success(message="模块删除成功")
        else:
            return ApiResponse.error(
                code=400,
                message=result.get("error", "删除失败"),
            )
    except Exception as exc:
        logger.error(f"删除模块失败: {exc}")
        return ApiResponse.error(code=500, message=f"删除模块失败: {exc}")


# ============================================================
# 备份执行接口
# ============================================================

@router.post("/backup/all", summary="触发全系统备份")
async def trigger_all_backup(
    body: dict = Body(default=None, description="备份参数"),
    current_user: dict = Depends(get_current_user),
):
    """触发全系统备份，备份所有已启用的模块

    请求体（可选）：
    - backup_type: 备份类型：full/incremental，默认 full
    """
    try:
        backup_type = "full"
        if body and body.get("backup_type"):
            backup_type = body["backup_type"]

        # 异步执行（后台线程），立即返回
        import threading
        result_container = {}

        def _run_backup():
            result = orchestrator.trigger_all_backup(
                trigger_type="api",
                backup_type=backup_type,
            )
            result_container["result"] = result

        thread = threading.Thread(target=_run_backup, daemon=True)
        thread.start()

        return ApiResponse.success(
            data={
                "status": "running",
                "backup_type": backup_type,
                "message": "全系统备份已启动，请查看历史记录获取执行结果",
            },
            message="全系统备份已启动",
        )
    except Exception as exc:
        logger.error(f"触发全系统备份失败: {exc}")
        return ApiResponse.error(code=500, message=f"触发全系统备份失败: {exc}")


@router.post("/backup/{module_id}", summary="触发指定模块备份")
async def trigger_module_backup(
    module_id: str,
    body: dict = Body(default=None, description="备份参数"),
    current_user: dict = Depends(get_current_user),
):
    """触发指定模块的备份

    请求体（可选）：
    - backup_type: 备份类型：full/incremental，默认 full
    """
    try:
        backup_type = "full"
        if body and body.get("backup_type"):
            backup_type = body["backup_type"]

        result = orchestrator.trigger_backup(
            module_id,
            trigger_type="api",
            backup_type=backup_type,
        )

        if result.get("success"):
            return ApiResponse.success(
                data=result,
                message="备份执行成功",
            )
        else:
            return ApiResponse.error(
                code=500,
                message=result.get("error", "备份执行失败"),
                data=result,
            )
    except Exception as exc:
        logger.error(f"触发模块备份失败: {exc}")
        return ApiResponse.error(code=500, message=f"触发模块备份失败: {exc}")


# ============================================================
# 历史记录接口
# ============================================================

@router.get("/history", summary="备份历史记录")
async def get_backup_history(
    module_id: Optional[str] = Query(None, description="按模块筛选"),
    status: Optional[str] = Query(None, description="按状态筛选：success/failed/running"),
    limit: int = Query(50, description="返回条数", ge=1, le=500),
    offset: int = Query(0, description="偏移量", ge=0),
    current_user: dict = Depends(get_current_user),
):
    """查询备份历史记录"""
    try:
        result = orchestrator.get_history(
            module_id=module_id,
            status=status,
            limit=limit,
            offset=offset,
        )
        return ApiResponse.success(data=result)
    except Exception as exc:
        logger.error(f"获取备份历史失败: {exc}")
        return ApiResponse.error(code=500, message=f"获取备份历史失败: {exc}")


# ============================================================
# 统计分析接口
# ============================================================

@router.get("/stats", summary="备份统计信息")
async def get_backup_stats(
    current_user: dict = Depends(get_current_user),
):
    """获取备份统计信息

    返回：
    - 模块总数、启用数
    - 总备份次数、成功次数、失败次数
    - 成功率
    - 总备份大小
    - 各模块统计
    - 最近7天每日统计
    """
    try:
        stats = orchestrator.get_stats()
        return ApiResponse.success(data=stats)
    except Exception as exc:
        logger.error(f"获取备份统计失败: {exc}")
        return ApiResponse.error(code=500, message=f"获取备份统计失败: {exc}")


# ============================================================
# 调度器状态接口
# ============================================================

@router.get("/status", summary="调度器状态")
async def get_scheduler_status(
    current_user: dict = Depends(get_current_user),
):
    """获取备份调度中心的运行状态"""
    try:
        status = orchestrator.get_scheduler_status()
        return ApiResponse.success(data=status)
    except Exception as exc:
        logger.error(f"获取调度器状态失败: {exc}")
        return ApiResponse.error(code=500, message=f"获取调度器状态失败: {exc}")
