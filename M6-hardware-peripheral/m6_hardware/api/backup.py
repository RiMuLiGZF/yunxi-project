"""
M6 硬件外设 - 备份管理 API

P2-6 改造：提供数据库备份的 REST API 接口，
包括列出备份、立即备份、恢复备份、备份统计、校验备份等。

端点：
- GET  /api/v1/backup/list    - 列出备份
- POST /api/v1/backup/now     - 立即备份
- POST /api/v1/backup/restore/{backup_id} - 恢复备份
- GET  /api/v1/backup/stats   - 备份统计
- POST /api/v1/backup/verify/{backup_id} - 校验备份
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Path

from .deps import get_config
from .utils import success_response, error_response
from ..config import M6Config
from ..models.errors import ErrorCode, M6Exception

from ..database import backup as backup_module

router = APIRouter()


# ============================================================================
# API 端点
# ============================================================================

@router.get("/list", summary="列出备份")
async def list_backups(
    limit: int = 20,
    config: M6Config = Depends(get_config),
):
    """列出数据库备份列表

    Args:
        limit: 最多返回的备份数量，默认 20

    Returns:
        备份列表，按时间倒序排列
    """
    try:
        backups = backup_module.list_backups(limit=limit)
        return success_response({
            "backups": backups,
            "total": len(backups),
            "limit": limit,
        })
    except Exception as e:
        raise M6Exception(
            code=ErrorCode.INTERNAL_ERROR,
            message=f"获取备份列表失败: {e}",
        )


@router.post("/now", summary="立即备份")
async def backup_now(
    config: M6Config = Depends(get_config),
):
    """立即创建数据库备份

    Returns:
        备份结果信息
    """
    try:
        result = backup_module.backup_database()

        if not result.get("success"):
            raise M6Exception(
                code=ErrorCode.INTERNAL_ERROR,
                message=f"备份失败: {result.get('error', 'unknown error')}",
                details={"errors": result.get("errors", [])},
            )

        return success_response({
            "backup_id": result.get("backup_id"),
            "backup_dir": result.get("backup_dir"),
            "size_bytes": result.get("total_size_bytes"),
            "size_mb": result.get("total_size_mb"),
            "success_dbs": result.get("success_dbs"),
            "failed_dbs": result.get("failed_dbs"),
            "timestamp": result.get("timestamp"),
        }, message="备份创建成功")

    except M6Exception:
        raise
    except Exception as e:
        raise M6Exception(
            code=ErrorCode.INTERNAL_ERROR,
            message=f"创建备份时发生异常: {e}",
        )


@router.post("/restore/{backup_id}", summary="恢复备份")
async def restore_backup(
    backup_id: str = Path(..., description="备份标识（目录名）"),
    config: M6Config = Depends(get_config),
):
    """从指定备份恢复数据库

    恢复前自动创建当前数据库的安全网备份，
    如果恢复失败则自动回滚到安全网备份。

    **注意**：此操作具有破坏性，请谨慎操作。
    建议在恢复前先校验备份完整性。

    Args:
        backup_id: 备份标识

    Returns:
        恢复结果信息
    """
    try:
        result = backup_module.restore_from_backup(
            backup_id,
            auto_rollback=True,
        )

        if not result.get("success"):
            raise M6Exception(
                code=ErrorCode.INTERNAL_ERROR,
                message=f"恢复失败: {result.get('error', 'unknown error')}",
                details={
                    "safety_net_created": result.get("safety_net_created", False),
                    "rolled_back": result.get("rolled_back", False),
                    "safety_net_path": result.get("safety_net_path"),
                    "errors": result.get("errors", []),
                },
            )

        return success_response({
            "backup_id": backup_id,
            "restored_to": result.get("restored_to"),
            "safety_net_path": result.get("safety_net_path"),
            "safety_net_created": result.get("safety_net_created", False),
            "rolled_back": result.get("rolled_back", False),
        }, message="数据库恢复成功")

    except M6Exception:
        raise
    except Exception as e:
        raise M6Exception(
            code=ErrorCode.INTERNAL_ERROR,
            message=f"恢复备份时发生异常: {e}",
        )


@router.get("/stats", summary="备份统计")
async def backup_stats(
    config: M6Config = Depends(get_config),
):
    """获取备份统计信息

    Returns:
        备份统计数据，包括总数、总大小、最新备份、调度器状态等
    """
    try:
        stats = backup_module.get_backup_stats()
        return success_response(stats)
    except Exception as e:
        raise M6Exception(
            code=ErrorCode.INTERNAL_ERROR,
            message=f"获取备份统计失败: {e}",
        )


@router.post("/verify/{backup_id}", summary="校验备份")
async def verify_backup(
    backup_id: str = Path(..., description="备份标识（目录名）"),
    config: M6Config = Depends(get_config),
):
    """校验指定备份的完整性

    执行以下检查：
    1. 文件存在性与大小检查
    2. MD5 校验和计算
    3. PRAGMA integrity_check 完整性检查
    4. PRAGMA quick_check 快速检查
    5. 表数量验证

    Args:
        backup_id: 备份标识

    Returns:
        校验结果详情
    """
    try:
        result = backup_module.verify_backup(backup_id)

        if not result.get("valid"):
            # 校验失败不抛异常，返回详细结果让调用方判断
            return success_response({
                "valid": False,
                "backup_id": backup_id,
                "backup_file": result.get("backup_file"),
                "file_valid": result.get("file_valid", False),
                "file_size_bytes": result.get("file_size_bytes", 0),
                "md5_checksum": result.get("md5_checksum", ""),
                "integrity_check": result.get("integrity_check", ""),
                "quick_check": result.get("quick_check", ""),
                "table_count": result.get("table_count", 0),
                "has_tables": result.get("has_tables", False),
                "errors": result.get("errors", []),
            }, message="备份校验未通过")

        return success_response({
            "valid": True,
            "backup_id": backup_id,
            "backup_file": result.get("backup_file"),
            "file_valid": result.get("file_valid"),
            "file_size_bytes": result.get("file_size_bytes"),
            "md5_checksum": result.get("md5_checksum"),
            "integrity_check": result.get("integrity_check"),
            "quick_check": result.get("quick_check"),
            "table_count": result.get("table_count"),
            "has_tables": result.get("has_tables"),
        }, message="备份校验通过")

    except M6Exception:
        raise
    except Exception as e:
        raise M6Exception(
            code=ErrorCode.INTERNAL_ERROR,
            message=f"校验备份时发生异常: {e}",
        )
