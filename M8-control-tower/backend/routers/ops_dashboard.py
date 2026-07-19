"""
M8 控制塔 - 运维仪表盘 API（Ops Dashboard）

提供完整的运维监控接口：
- 仪表盘总览
- 模块状态管理
- 资源使用监控
- 日志查询
- 部署管理
- 备份管理
- 系统配置

所有接口以 /api/ops/ 为前缀。
"""

import sys
import os
import time
from pathlib import Path
from typing import List, Dict, Any, Optional
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, Query, HTTPException, BackgroundTasks
from pydantic import BaseModel, Field

# 项目根路径
project_root = Path(__file__).parent.parent.parent.parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

from ..schemas import ApiResponse
from ..auth import get_current_user
from .ops_status_aggregator import (
    get_ops_aggregator,
    OpsStatusAggregator,
)
from .system import get_system_actions

router = APIRouter(prefix="/ops", tags=["运维管理"])
aggregator: OpsStatusAggregator = get_ops_aggregator()


# ============================================================================
# 请求/响应模型
# ============================================================================

class BackupCreateRequest(BaseModel):
    """创建备份请求"""
    backup_type: str = Field("full", description="备份类型: full/incremental/differential")
    modules: Optional[List[str]] = Field(None, description="要备份的模块列表，None表示全部")
    description: Optional[str] = Field(None, description="备份描述")
    encrypt: bool = Field(False, description="是否加密")


class LogQueryRequest(BaseModel):
    """日志查询请求"""
    module: Optional[str] = None
    level: Optional[str] = None
    keyword: Optional[str] = None
    start_time: Optional[str] = None
    end_time: Optional[str] = None
    limit: int = 100
    offset: int = 0


class DeployTriggerRequest(BaseModel):
    """触发部署请求"""
    module: str
    version: Optional[str] = None
    strategy: str = "rolling"


# ============================================================================
# 仪表盘总览
# ============================================================================

@router.get("/dashboard", summary="运维仪表盘总览")
async def ops_dashboard(
    current_user: dict = Depends(get_current_user),
):
    """获取运维仪表盘总览数据"""
    overview = aggregator.get_dashboard_overview()
    predictions = aggregator.get_failure_predictions()
    recommendations = aggregator.get_capacity_recommendations()

    return ApiResponse.success(data={
        **overview,
        "system_actions": get_system_actions(),
        "predictions": [
            {
                "module": p.module,
                "metric": p.metric,
                "trend": p.trend,
                "risk_level": p.risk_level,
                "description": p.description,
            }
            for p in predictions
        ],
        "recommendations": [
            {
                "resource": r.resource,
                "current_usage": r.current_usage,
                "threshold": r.threshold,
                "recommendation": r.recommendation,
                "severity": r.severity,
            }
            for r in recommendations
        ],
    })


# ============================================================================
# 模块管理
# ============================================================================

@router.get("/modules", summary="模块状态列表")
async def list_modules(
    status: Optional[str] = Query(None, description="按状态过滤"),
    current_user: dict = Depends(get_current_user),
):
    """获取所有模块的状态列表"""
    modules = aggregator.get_module_list()
    if status:
        modules = [m for m in modules if m["status"] == status]
    return ApiResponse.success(data={
        "modules": modules,
        "total": len(modules),
    })


@router.get("/modules/{module_name}", summary="模块详情")
async def get_module_detail(
    module_name: str,
    current_user: dict = Depends(get_current_user),
):
    """获取指定模块的详细信息"""
    detail = aggregator.get_module_detail(module_name)
    if not detail:
        raise HTTPException(status_code=404, detail=f"模块 {module_name} 不存在")
    return ApiResponse.success(data=detail)


@router.get("/modules/{module_name}/restart", summary="重启模块（预留）")
async def restart_module(
    module_name: str,
    background_tasks: BackgroundTasks,
    current_user: dict = Depends(get_current_user),
):
    """重启模块（预留接口，实际重启需配合部署系统）"""
    # 预留接口：实际重启逻辑需要根据部署方式实现
    # 目前只返回成功，记录操作
    return ApiResponse.success(data={
        "module": module_name,
        "status": "scheduled",
        "message": f"模块 {module_name} 重启任务已提交（预留接口）",
    })


# ============================================================================
# 资源监控
# ============================================================================

@router.get("/resources", summary="资源使用情况")
async def get_resources(
    current_user: dict = Depends(get_current_user),
):
    """获取系统资源使用情况"""
    resources = aggregator.get_resource_usage()
    recommendations = aggregator.get_capacity_recommendations()

    return ApiResponse.success(data={
        "current": resources,
        "recommendations": [
            {
                "resource": r.resource,
                "current_usage": r.current_usage,
                "threshold": r.threshold,
                "recommendation": r.recommendation,
                "severity": r.severity,
            }
            for r in recommendations
        ],
    })


# ============================================================================
# 日志查询
# ============================================================================

@router.get("/logs", summary="日志查询")
async def query_logs(
    module: Optional[str] = Query(None, description="模块名"),
    level: Optional[str] = Query(None, description="日志级别: DEBUG/INFO/WARNING/ERROR/CRITICAL"),
    keyword: Optional[str] = Query(None, description="关键词搜索"),
    start_time: Optional[str] = Query(None, description="开始时间 (ISO格式)"),
    end_time: Optional[str] = Query(None, description="结束时间 (ISO格式)"),
    limit: int = Query(100, ge=1, le=1000, description="返回条数"),
    offset: int = Query(0, ge=0, description="偏移量"),
    current_user: dict = Depends(get_current_user),
):
    """查询系统日志"""
    logs = _search_logs(
        module=module,
        level=level,
        keyword=keyword,
        start_time=start_time,
        end_time=end_time,
        limit=limit,
        offset=offset,
    )
    return ApiResponse.success(data=logs)


@router.get("/logs/{module}", summary="模块日志")
async def get_module_logs(
    module: str,
    level: Optional[str] = Query(None),
    keyword: Optional[str] = Query(None),
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0),
    current_user: dict = Depends(get_current_user),
):
    """查询指定模块的日志"""
    logs = _search_logs(
        module=module,
        level=level,
        keyword=keyword,
        limit=limit,
        offset=offset,
    )
    return ApiResponse.success(data=logs)


# ============================================================================
# 部署管理
# ============================================================================

@router.get("/deployments", summary="部署历史")
async def list_deployments(
    limit: int = Query(20, ge=1, le=100),
    module: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user),
):
    """获取部署历史记录"""
    deployments = aggregator.get_deployments(limit=limit)
    if module:
        deployments = [d for d in deployments if d["module"] == module]
    return ApiResponse.success(data={
        "deployments": deployments,
        "total": len(deployments),
    })


@router.post("/deploy/trigger", summary="触发部署（预留）")
async def trigger_deploy(
    request: DeployTriggerRequest,
    background_tasks: BackgroundTasks,
    current_user: dict = Depends(get_current_user),
):
    """触发模块部署（预留接口）"""
    result = aggregator.trigger_deploy(request.module)
    # 记录部署事件
    aggregator.record_deployment(
        module=request.module,
        version=request.version or "latest",
        status="scheduled",
    )
    return ApiResponse.success(data=result)


# ============================================================================
# 备份管理
# ============================================================================

@router.get("/backups", summary="备份列表")
async def list_backups(
    module: Optional[str] = Query(None),
    limit: int = Query(20, ge=1, le=100),
    current_user: dict = Depends(get_current_user),
):
    """获取备份列表"""
    backups = _list_backups(module=module, limit=limit)
    return ApiResponse.success(data={
        "backups": backups,
        "total": len(backups),
    })


@router.post("/backup/create", summary="创建备份")
async def create_backup(
    request: BackupCreateRequest,
    background_tasks: BackgroundTasks,
    current_user: dict = Depends(get_current_user),
):
    """创建系统备份"""
    backup_id = f"backup-{int(time.time())}"
    result = {
        "backup_id": backup_id,
        "type": request.backup_type,
        "modules": request.modules or ["all"],
        "status": "scheduled",
        "created_at": datetime.now().isoformat(),
    }

    # 后台执行备份（实际逻辑由 backup_service 处理）
    background_tasks.add_task(
        _execute_backup,
        backup_id=backup_id,
        backup_type=request.backup_type,
        modules=request.modules,
        encrypt=request.encrypt,
    )

    return ApiResponse.success(data=result)


# ============================================================================
# 系统配置
# ============================================================================

@router.get("/config", summary="系统配置概览")
async def get_system_config(
    current_user: dict = Depends(get_current_user),
):
    """获取系统配置概览"""
    config = aggregator.get_system_config_overview()
    return ApiResponse.success(data=config)


# ============================================================================
# 依赖图
# ============================================================================

@router.get("/dependency-graph", summary="服务依赖图")
async def get_dependency_graph(
    current_user: dict = Depends(get_current_user),
):
    """获取服务依赖关系图"""
    graph = aggregator.get_service_dependency_graph()
    return ApiResponse.success(data=graph)


# ============================================================================
# 健康检查详情
# ============================================================================

@router.get("/health/details", summary="详细健康信息")
async def get_health_details(
    current_user: dict = Depends(get_current_user),
):
    """获取全系统详细健康信息"""
    modules = aggregator.get_module_list()
    summary = aggregator.get_dashboard_overview()["summary"]

    return ApiResponse.success(data={
        "summary": summary,
        "modules": modules,
        "timestamp": datetime.now().isoformat(),
    })


# ============================================================================
# 内部辅助函数
# ============================================================================

def _search_logs(
    module: Optional[str] = None,
    level: Optional[str] = None,
    keyword: Optional[str] = None,
    start_time: Optional[str] = None,
    end_time: Optional[str] = None,
    limit: int = 100,
    offset: int = 0,
) -> Dict[str, Any]:
    """搜索日志文件"""
    logs_dir = project_root / "logs"
    results = []
    total = 0

    try:
        # 尝试使用 LogQueryEngine
        try:
            from shared.core.observability.log_query import get_log_query_engine
            engine = get_log_query_engine()
            search_result = engine.search(
                level=level,
                module=module,
                keyword=keyword,
                limit=limit,
                offset=offset,
            )
            return search_result
        except (ImportError, Exception):
            pass

        # 回退：直接扫描日志文件
        log_files = _find_log_files(logs_dir, module)

        all_lines = []
        for log_file in log_files:
            try:
                lines = _read_log_file(log_file, level, keyword, start_time, end_time)
                all_lines.extend(lines)
            except Exception:
                continue

        # 按时间排序（新的在前）
        all_lines.sort(key=lambda x: x.get("timestamp", ""), reverse=True)
        total = len(all_lines)
        results = all_lines[offset:offset + limit]

    except Exception as e:
        return {"logs": [], "total": 0, "error": str(e)}

    return {
        "logs": results,
        "total": total,
        "limit": limit,
        "offset": offset,
    }


def _find_log_files(logs_dir: Path, module: Optional[str] = None) -> List[Path]:
    """查找日志文件"""
    if not logs_dir.exists():
        return []

    pattern = f"*{module}*.log" if module else "*.log"
    files = list(logs_dir.rglob(pattern))
    # 也包含 error 日志
    if module:
        files.extend(list(logs_dir.rglob(f"*{module}*-error.log")))
    return files


def _read_log_file(
    filepath: Path,
    level: Optional[str] = None,
    keyword: Optional[str] = None,
    start_time: Optional[str] = None,
    end_time: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """读取日志文件并过滤"""
    lines = []
    try:
        # 支持 gzip 压缩日志
        if str(filepath).endswith(".gz"):
            import gzip
            opener = gzip.open(filepath, "rt", encoding="utf-8", errors="ignore")
        else:
            opener = open(filepath, "r", encoding="utf-8", errors="ignore")

        with opener as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue

                # 尝试解析 JSON 格式
                log_entry = _parse_log_line(line, filepath.name)
                if not log_entry:
                    continue

                # 级别过滤
                if level and log_entry.get("level", "").upper() != level.upper():
                    continue

                # 关键词过滤
                if keyword and keyword.lower() not in line.lower():
                    continue

                lines.append(log_entry)

                # 限制单次读取数量，避免内存问题
                if len(lines) > 5000:
                    break
    except Exception:
        pass

    return lines


def _parse_log_line(line: str, source_file: str) -> Optional[Dict[str, Any]]:
    """解析日志行（支持 JSON 和文本格式）"""
    import json

    # 尝试 JSON 格式
    try:
        data = json.loads(line)
        if isinstance(data, dict):
            data["source_file"] = source_file
            return data
    except (json.JSONDecodeError, ValueError):
        pass

    # 文本格式：简单解析
    try:
        return {
            "message": line,
            "source_file": source_file,
            "level": "INFO",
        }
    except Exception:
        return None


def _list_backups(module: Optional[str] = None, limit: int = 20) -> List[Dict[str, Any]]:
    """列出备份文件"""
    backups_dir = project_root / "backups"
    backups = []

    try:
        if not backups_dir.exists():
            return []

        for item in sorted(backups_dir.iterdir(), reverse=True):
            if item.is_dir() or item.is_file():
                # 简单识别备份目录/文件
                name = item.name
                if module and module.lower() not in name.lower():
                    continue

                try:
                    stat = item.stat()
                    backups.append({
                        "name": name,
                        "path": str(item),
                        "size_bytes": stat.st_size if item.is_file() else _get_dir_size(item),
                        "created_at": datetime.fromtimestamp(stat.st_mtime).isoformat(),
                        "type": "file" if item.is_file() else "directory",
                    })
                except Exception:
                    continue

                if len(backups) >= limit:
                    break
    except Exception:
        pass

    return backups


def _get_dir_size(path: Path) -> int:
    """计算目录大小"""
    total = 0
    try:
        for f in path.rglob("*"):
            if f.is_file():
                try:
                    total += f.stat().st_size
                except OSError:
                    pass
    except Exception:
        pass
    return total


def _execute_backup(
    backup_id: str,
    backup_type: str = "full",
    modules: Optional[List[str]] = None,
    encrypt: bool = False,
) -> None:
    """执行备份（后台任务）"""
    try:
        from shared.data.data_layer.backup_manager import BackupManager, BackupType

        backup_manager = BackupManager(
            backup_dir=str(project_root / "backups"),
        )

        type_map = {
            "full": BackupType.FULL,
            "incremental": BackupType.INCREMENTAL,
            "differential": getattr(BackupType, "DIFFERENTIAL", BackupType.FULL),
        }

        backup_manager.create_backup(
            backup_type=type_map.get(backup_type, BackupType.FULL),
            description=f"Ops dashboard backup: {backup_type}",
        )
    except Exception:
        pass
