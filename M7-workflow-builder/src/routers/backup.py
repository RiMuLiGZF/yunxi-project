"""M7 工作流模块 - 备份管理 API 路由.

提供备份管理相关的 REST API 端点：
- GET    /api/v1/backup/              - 备份列表
- POST   /api/v1/backup/               - 立即备份
- POST   /api/v1/backup/restore       - 恢复备份
- GET    /api/v1/backup/stats        - 备份统计
- POST   /api/v1/backup/verify       - 校验备份
- GET    /api/v1/backup/schedule     - 获取定时备份状态
- POST   /api/v1/backup/schedule     - 设置定时备份
- DELETE /api/v1/backup/schedule     - 停止定时备份
"""

from __future__ import annotations

import os
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from ..models import ApiResponse


# ============================================================
#  路由
# ============================================================

router = APIRouter(
    prefix="/api/v1/backup",
    tags=["备份管理"],
)


# ============================================================
#  请求/响应模型
# ============================================================

class BackupRestoreRequest(BaseModel):
    """恢复备份请求."""
    backup_path: str = Field(..., description="备份文件或目录路径")
    use_safety_net: bool = Field(True, description="是否使用安全网（恢复前自动备份当前数据")


class BackupVerifyRequest(BaseModel):
    """校验备份请求."""
    backup_path: Optional[str] = Field(None, description="备份路径，为空则校验所有备份")


class ScheduleConfig(BaseModel):
    """定时备份配置."""
    type: str = Field(..., description="调度类型: daily / interval")
    time: Optional[str] = Field(None, description="每日时间，如 '03:00'（type=daily 时使用）")
    hours: Optional[int] = Field(None, description="间隔小时数（type=interval 时使用）")
    minutes: Optional[int] = Field(None, description="间隔分钟数（type=interval 时使用）")


# ============================================================
#  懒加载备份管理器
# ============================================================

def _get_backup_manager():
    """懒加载备份管理器，避免循环导入."""
    from ..backup_manager import get_backup_manager
    return get_backup_manager()


def _get_migration_manager():
    """懒加载迁移管理器."""
    from ..migration_manager import get_migration_manager
    return get_migration_manager()


# ============================================================
#  API 端点
# ============================================================

@router.get("", summary="获取备份列表")
async def list_backups(
    page: int = Query(1, ge=1, description="页码"),
    page_size: int = Query(20, ge=1, le=100, description="每页数量"),
) -> Dict[str, Any]:
    """获取备份列表，按时间倒序排列."""
    try:
        bm = _get_backup_manager()
        all_backups = bm.list_backups()

        # 分页
        total = len(all_backups)
        start = (page - 1) * page_size
        end = start + page_size
        items = all_backups[start:end]

        return ApiResponse.success(data={
            "items": items,
            "total": total,
            "page": page,
            "page_size": page_size,
        }).model_dump()
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("", summary="立即创建备份")
async def create_backup() -> Dict[str, Any]:
    """立即执行一次全量备份."""
    try:
        bm = _get_backup_manager()
        report = bm.backup_now()

        data = {
            "success": report.success,
            "total_dbs": report.total_dbs,
            "success_dbs": report.success_dbs,
            "failed_dbs": report.failed_dbs,
            "total_size_bytes": report.total_size_bytes,
            "total_size_mb": report.total_size_mb,
            "backup_dir": report.backup_dir,
            "timestamp": report.timestamp,
            "details": report.details,
            "errors": report.errors,
        }

        if report.success:
            return ApiResponse.success(data=data, message="备份成功").model_dump()
        else:
            return ApiResponse.error(code=500, message="备份失败", data=data).model_dump()
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/restore", summary="恢复备份")
async def restore_backup(request: BackupRestoreRequest) -> Dict[str, Any]:
    """从指定备份恢复数据库.

    注意：此操作具有破坏性，恢复后当前数据将被替换。
    默认启用安全网，恢复前会自动备份当前数据。
    """
    try:
        bm = _get_backup_manager()
        result = bm.restore(
            backup_path=request.backup_path,
            use_safety_net=request.use_safety_net,
        )

        if result["success"]:
            return ApiResponse.success(
                data=result,
                message="恢复成功",
            ).model_dump()
        else:
            return ApiResponse.error(
                code=500,
                message=result.get("error", "恢复失败"),
                data=result,
            ).model_dump()
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/stats", summary="获取备份统计")
async def get_backup_stats() -> Dict[str, Any]:
    """获取备份统计信息."""
    try:
        bm = _get_backup_manager()
        stats = bm.get_stats()
        return ApiResponse.success(data=stats).model_dump()
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/verify", summary="校验备份")
async def verify_backup(request: BackupVerifyRequest) -> Dict[str, Any]:
    """校验备份文件完整性.

    如果指定了 backup_path，则校验单个备份；
    否则校验所有备份。
    """
    try:
        bm = _get_backup_manager()

        if request.backup_path:
            report = bm.verify_backup(request.backup_path)
            data = {
                "backup_path": report.backup_path,
                "overall_valid": report.overall_valid,
                "file_valid": report.file_valid,
                "file_size_bytes": report.file_size_bytes,
                "md5_checksum": report.md5_checksum,
                "integrity_check": report.integrity_check,
                "quick_check": report.quick_check,
                "table_count": report.table_count,
                "has_tables": report.has_tables,
                "errors": report.errors,
            }
            return ApiResponse.success(data=data).model_dump()
        else:
            # 校验所有备份
            results = bm.verify_all_backups()
            valid_count = sum(1 for r in results if r["overall_valid"])
            data = {
                "total": len(results),
                "valid_count": valid_count,
                "invalid_count": len(results) - valid_count,
                "results": results,
            }
            return ApiResponse.success(data=data).model_dump()
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/schedule", summary="获取定时备份状态")
async def get_schedule_status() -> Dict[str, Any]:
    """获取定时备份调度器状态."""
    try:
        bm = _get_backup_manager()
        status = bm.get_schedule_status()
        return ApiResponse.success(data=status).model_dump()
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/schedule", summary="设置定时备份")
async def set_schedule(config: ScheduleConfig) -> Dict[str, Any]:
    """设置并启动定时备份.

    支持两种调度模式：
    - daily: 每日指定时间执行，如 {"type": "daily", "time": "03:00"}
    - interval: 每隔一段时间执行，如 {"type": "interval", "hours": 6}
    """
    try:
        bm = _get_backup_manager()

        # 构建调度配置
        schedule_config: Dict[str, Any] = {"type": config.type}

        if config.type == "daily":
            if not config.time:
                raise HTTPException(
                    status_code=400,
                    detail="daily 模式必须指定 time 参数",
                )
            schedule_config["time"] = config.time
        elif config.type == "interval":
            if config.hours is not None:
                schedule_config["hours"] = config.hours
            elif config.minutes is not None:
                schedule_config["minutes"] = config.minutes
            else:
                raise HTTPException(
                    status_code=400,
                    detail="interval 模式必须指定 hours 或 minutes 参数",
                )
        else:
            raise HTTPException(
                status_code=400,
                detail=f"不支持的调度类型: {config.type}",
            )

        success = bm.start_schedule(schedule_config)

        if success:
            status = bm.get_schedule_status()
            return ApiResponse.success(
                data=status,
                message="定时备份已启动",
            ).model_dump()
        else:
            return ApiResponse.error(
                code=500,
                message="启动定时备份失败",
            ).model_dump()
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/schedule", summary="停止定时备份")
async def stop_schedule() -> Dict[str, Any]:
    """停止定时备份调度器."""
    try:
        bm = _get_backup_manager()
        success = bm.stop_schedule()

        if success:
            return ApiResponse.success(
                message="定时备份已停止",
                data={"stopped": True},
            ).model_dump()
        else:
            return ApiResponse.error(
                code=400,
                message="定时备份未在运行",
            ).model_dump()
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/migration/status", summary="获取迁移状态")
async def get_migration_status() -> Dict[str, Any]:
    """获取数据库迁移状态."""
    try:
        mm = _get_migration_manager()
        data = {
            "current_version": mm.get_current_version(),
            "latest_version": mm.get_latest_version(),
            "is_latest": mm.get_current_version() >= mm.get_latest_version(),
        }
        return ApiResponse.success(data=data).model_dump()
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/migration/history", summary="获取迁移历史")
async def get_migration_history() -> Dict[str, Any]:
    """获取已应用的迁移历史记录."""
    try:
        mm = _get_migration_manager()
        history = mm.get_migration_history()
        return ApiResponse.success(data={"migrations": history}).model_dump()
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
