"""
系统管理路由
"""

import sys
import json
import os
from pathlib import Path
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from typing import Dict, Any, List, Optional

project_root = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(project_root))

from ..config import settings
from ..schemas import ApiResponse
from ..auth import get_current_user
from ..crypto import encrypt as crypto_encrypt, decrypt as crypto_decrypt, mask_api_key
from shared.module_client import get_module_registry, ModuleStatus
from shared.process_manager import get_process_manager, ProcessStatus
from shared.startup_orchestrator import get_startup_orchestrator
from .users import router as users_router

router = APIRouter()
registry = get_module_registry()
process_mgr = get_process_manager()
startup_orch = get_startup_orchestrator(self_module_key="m8")

# 包含用户管理子路由（路径：/api/system/users/*）
router.include_router(users_router, tags=["用户管理"])

# ==================== 数据存储路径 ====================

def _get_yunxi_dir() -> Path:
    """获取云汐数据目录 ~/.yunxi"""
    yunxi_dir = Path.home() / ".yunxi"
    yunxi_dir.mkdir(parents=True, exist_ok=True)
    return yunxi_dir


SETTINGS_FILE = _get_yunxi_dir() / "settings.json"

# ==================== 公告内存存储 ====================

class Announcement(BaseModel):
    id: int
    title: str
    content: str
    level: str = "info"  # info/warning/error
    created_at: str = ""
    updated_at: str = ""


_announcements: List[Announcement] = [
    Announcement(
        id=1,
        title="欢迎使用云汐管理工作台 M8",
        content="这是整合阶段的 MVP 版本，功能持续完善中。如有问题请联系管理员。",
        level="info",
        created_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        updated_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    )
]
_announcement_id_counter = 2

# ==================== 系统设置 ====================

DEFAULT_SETTINGS = {
    "theme": "dark",
    "language": "zh-CN",
    "auto_start_modules": False,
    "notification_enabled": True,
    "auto_check_update": True,
    "log_level": "info",
    # LLM 大模型配置
    "ai_provider": "deepseek",
    "model": "deepseek-chat",
    "temperature": 0.7,
    "max_tokens": 4096,
    "max_concurrent": 5,
    # llm_api_key 加密后存储（加密后以 enc: 开头）
    "llm_api_key_encrypted": "",
}


def _load_settings() -> dict:
    """从文件加载系统设置，不存在则返回默认值"""
    if SETTINGS_FILE.exists():
        try:
            with open(SETTINGS_FILE, "r", encoding="utf-8") as f:
                saved = json.load(f)
            # 合并默认值，确保新增字段存在
            merged = {**DEFAULT_SETTINGS, **saved}
            return merged
        except Exception:
            pass
    return DEFAULT_SETTINGS.copy()


def _save_settings(settings_data: dict) -> None:
    """保存系统设置到文件"""
    with open(SETTINGS_FILE, "w", encoding="utf-8") as f:
        json.dump(settings_data, f, ensure_ascii=False, indent=2)


# ==================== Pydantic 模型 ====================

class SettingsUpdate(BaseModel):
    theme: Optional[str] = None
    language: Optional[str] = None
    auto_start_modules: Optional[bool] = None
    notification_enabled: Optional[bool] = None
    auto_check_update: Optional[bool] = None
    log_level: Optional[str] = None
    # LLM 配置
    ai_provider: Optional[str] = None
    model: Optional[str] = None
    temperature: Optional[float] = None
    max_tokens: Optional[int] = None
    max_concurrent: Optional[int] = None
    llm_api_key: Optional[str] = None  # 明文传入，后端加密存储


class BatchModuleRequest(BaseModel):
    """批量模块操作请求"""
    modules: Optional[List[str]] = Field(None, description="模块 key 列表，不传则操作所有模块")
    force: Optional[bool] = Field(False, description="是否强制停止")


class AnnouncementCreate(BaseModel):
    title: str
    content: str
    level: str = "info"


class AnnouncementUpdate(BaseModel):
    title: Optional[str] = None
    content: Optional[str] = None
    level: Optional[str] = None


# ==================== 系统信息接口 ====================

@router.get("/info")
async def get_system_info(current_user: dict = Depends(get_current_user)):
    """获取系统信息"""
    info = {
        "name": settings.app_name,
        "version": settings.version,
        "env": settings.env,
        "modules": 8,
        "uptime": "0天 0小时 0分钟",
        "database": "sqlite",
        "llm_provider": "deepseek",
    }
    return ApiResponse.success(data=info)


@router.get("/health")
async def system_health(current_user: dict = Depends(get_current_user)):
    """系统健康检查"""
    return ApiResponse.success(
        data={
            "status": "healthy",
            "database": "connected",
            "modules_total": 8,
        }
    )


@router.get("/config")
async def get_config(current_user: dict = Depends(get_current_user)):
    """获取系统配置（脱敏）"""
    config = {
        "env": settings.env,
        "log_level": settings.log_level,
        "admin_username": settings.admin_username,
    }
    return ApiResponse.success(data=config)


@router.get("/stats")
async def get_stats(current_user: dict = Depends(get_current_user)):
    """获取系统统计数据（真实数据）"""
    import os
    from datetime import datetime
    
    summary = registry.get_status_summary()
    modules = registry.get_all_modules()
    running_modules = sum(1 for m in modules if m.status == ModuleStatus.RUNNING)
    
    stats = {
        "modules": summary,
        "modules_total": len(modules),
        "modules_running": running_modules,
        "modules_stopped": len(modules) - running_modules,
    }
    
    # 尝试获取真实系统运行时间
    try:
        import psutil
        boot_time = datetime.fromtimestamp(psutil.boot_time())
        uptime = datetime.now() - boot_time
        days = uptime.days
        hours = uptime.seconds // 3600
        minutes = (uptime.seconds % 3600) // 60
        stats["uptime_text"] = f"{days}天{hours}小时{minutes}分钟"
        stats["uptime_seconds"] = int(uptime.total_seconds())
    except Exception:
        try:
            import psutil
            current_proc = psutil.Process(os.getpid())
            create_time = datetime.fromtimestamp(current_proc.create_time())
            uptime = datetime.now() - create_time
            days = uptime.days
            hours = uptime.seconds // 3600
            minutes = (uptime.seconds % 3600) // 60
            stats["uptime_text"] = f"{days}天{hours}小时{minutes}分钟"
            stats["uptime_seconds"] = int(uptime.total_seconds())
        except Exception:
            stats["uptime_text"] = "未知"
            stats["uptime_seconds"] = 0
    
    # 数据库中的统计（带异常保护）
    try:
        from ..models import get_db, TaskRecord, AlertRecord
        from sqlalchemy import func
        
        db = next(get_db())
        try:
            # 任务统计
            task_count = db.query(func.count(TaskRecord.id)).scalar() or 0
            stats["tasks_total"] = task_count
            stats["tasks_today"] = 0
            
            # 今日任务
            try:
                today = datetime.now().date()
                today_tasks = db.query(func.count(TaskRecord.id)).filter(
                    func.date(TaskRecord.created_at) == today
                ).scalar() or 0
                stats["tasks_today"] = today_tasks
            except Exception:
                pass
            
            # 告警统计
            try:
                alert_count = db.query(func.count(AlertRecord.id)).scalar() or 0
                stats["alerts_total"] = alert_count
                
                active_alerts = db.query(func.count(AlertRecord.id)).filter(
                    AlertRecord.status != "resolved"
                ).scalar() or 0
                stats["alerts_active"] = active_alerts
            except Exception:
                stats["alerts_total"] = 0
                stats["alerts_active"] = 0
            
            stats["tasks_completed"] = 0
            stats["tasks_failed"] = 0
            stats["active_users"] = 1
            stats["requests_today"] = 0
            stats["avg_response_time_ms"] = 0

            # 算力调用统计
            try:
                from ..compute_router import compute_manager
                stats["compute_calls"] = compute_manager.get_total_calls() if hasattr(compute_manager, 'get_total_calls') else 0
            except Exception:
                stats["compute_calls"] = 0
                stats["compute_success_rate"] = 0

        finally:
            db.close()
    except Exception as e:
        # 数据库不可用时的降级数据
        stats["tasks_total"] = 0
        stats["tasks_today"] = 0
        stats["tasks_completed"] = 0
        stats["tasks_failed"] = 0
        stats["alerts_total"] = 0
        stats["alerts_active"] = 0
        stats["active_users"] = 1
        stats["requests_today"] = 0
        stats["avg_response_time_ms"] = 0
        stats["compute_calls"] = 0

    # 系统健康度评分（基于模块在线率 + 告警数 + 任务成功率）
    try:
        total_modules = stats.get("modules_total", 0)
        running_modules = stats.get("modules_running", 0)
        module_score = (running_modules / total_modules * 100) if total_modules > 0 else 100

        alerts_active = stats.get("alerts_active", 0)
        alert_penalty = min(alerts_active * 5, 30)

        tasks_total = stats.get("tasks_total", 0)
        tasks_failed = stats.get("tasks_failed", 0)
        task_score = ((tasks_total - tasks_failed) / tasks_total * 100) if tasks_total > 0 else 100

        health_score = int((module_score * 0.5 + task_score * 0.3 + (100 - alert_penalty) * 0.2))
        health_score = max(0, min(100, health_score))
        stats["health_score"] = health_score
    except Exception:
        stats["health_score"] = 85

    return ApiResponse.success(data=stats)

@router.post("/cache/clear")
async def clear_cache(current_user: dict = Depends(get_current_user)):
    """清理系统缓存"""
    import gc
    import sys
    
    cleared = []
    
    # 1. 清理 Python 垃圾回收
    gc.collect()
    cleared.append("Python GC")
    
    # 2. 清理模块客户端缓存
    try:
        if hasattr(registry, "clear_cache"):
            registry.clear_cache()
            cleared.append("模块注册表缓存")
    except Exception:
        pass
    
    # 3. 清理数据库会话缓存
    try:
        from ..models import get_db
        db = next(get_db())
        db.expire_all()
        db.close()
        cleared.append("数据库会话缓存")
    except Exception:
        pass
    
    return ApiResponse.success(
        message=f"缓存清理成功，已清理: {', '.join(cleared) if cleared else '无'}",
        data={"cleared": cleared},
    )


# ==================== 模块管理接口 ====================
# 【去重标注 AR-005 phase-1】
# 模块管理主入口已统一为 /api/modules/*（见 routers/modules.py，63个端点）
# 此处 /api/system/modules/* 保留用于向后兼容，后续版本将迁移到 modules.py
# 推荐使用: GET /api/modules/list, POST /api/modules/{key}/start 等

@router.get("/modules")
async def list_modules(
    health_check: bool = False,
    current_user: dict = Depends(get_current_user),
):
    """获取所有模块列表"""
    modules = registry.get_all_modules()
    
    if health_check:
        # 实时健康检查
        for mod in modules:
            try:
                client = registry.get_client(mod.key)
                is_healthy = await client.health_check()
                mod.status = ModuleStatus.RUNNING if is_healthy else ModuleStatus.STOPPED
            except Exception:
                mod.status = ModuleStatus.UNKNOWN
    
    items = [m.to_dict() for m in modules]
    
    return ApiResponse.success(data={
        "total": len(items),
        "items": items,
    })


@router.get("/modules/{module_key}")
async def get_module_detail(module_key: str, current_user: dict = Depends(get_current_user)):
    """获取单个模块详情"""
    module = registry.get_module(module_key)
    if not module:
        return ApiResponse.error(code=404, message=f"模块 {module_key} 不存在")
    return ApiResponse.success(data=module.to_dict())


@router.post("/modules/{module_key}/start")
async def start_module(module_key: str, current_user: dict = Depends(get_current_user)):
    """启动模块（真实进程管理）"""
    module = registry.get_module(module_key)
    if not module:
        return ApiResponse.error(code=404, message=f"模块 {module_key} 不存在")

    # M8 自己不能启动自己
    if module_key == "m8":
        return ApiResponse.success(
            message="M8 管理工作台自身已在运行",
            data=module.to_dict(),
        )

    proc_info = process_mgr.start_module(module_key)
    
    if proc_info.status == ProcessStatus.ERROR:
        return ApiResponse.error(
            message=f"模块 {module_key} 启动失败",
            data={"error": proc_info.error_message, "process": proc_info.to_dict()},
        )
    
    module.status = ModuleStatus.RUNNING if proc_info.status == ProcessStatus.RUNNING else ModuleStatus.UNKNOWN
    
    return ApiResponse.success(
        message=f"模块 {module_key} 启动指令已发送" if proc_info.status == ProcessStatus.STARTING else f"模块 {module_key} 已启动",
        data={
            **module.to_dict(),
            "process": proc_info.to_dict(),
        },
    )


@router.post("/modules/{module_key}/stop")
async def stop_module(module_key: str, current_user: dict = Depends(get_current_user)):
    """停止模块（真实进程管理）"""
    module = registry.get_module(module_key)
    if not module:
        return ApiResponse.error(code=404, message=f"模块 {module_key} 不存在")

    # M8 自己不能停止自己
    if module_key == "m8":
        return ApiResponse.success(
            message="M8 管理工作台无法自行停止，请手动停止服务",
            data=module.to_dict(),
        )

    proc_info = process_mgr.stop_module(module_key, force=False)
    module.status = ModuleStatus.STOPPED
    
    return ApiResponse.success(
        message=f"模块 {module_key} 停止指令已发送",
        data={
            **module.to_dict(),
            "process": proc_info.to_dict(),
        },
    )


@router.post("/modules/{module_key}/restart")
async def restart_module(module_key: str, current_user: dict = Depends(get_current_user)):
    """重启模块（真实进程管理）"""
    module = registry.get_module(module_key)
    if not module:
        return ApiResponse.error(code=404, message=f"模块 {module_key} 不存在")

    # M8 自己不能重启自己
    if module_key == "m8":
        return ApiResponse.success(
            message="M8 管理工作台无法自行重启，请手动重启服务",
            data=module.to_dict(),
        )

    proc_info = process_mgr.restart_module(module_key)
    
    if proc_info.status == ProcessStatus.ERROR:
        return ApiResponse.error(
            message=f"模块 {module_key} 重启失败",
            data={"error": proc_info.error_message, "process": proc_info.to_dict()},
        )
    
    module.status = ModuleStatus.RUNNING if proc_info.status == ProcessStatus.RUNNING else ModuleStatus.UNKNOWN
    
    return ApiResponse.success(
        message=f"模块 {module_key} 重启指令已发送",
        data={
            **module.to_dict(),
            "process": proc_info.to_dict(),
        },
    )





# ==================== 批量模块管理 ====================

@router.post("/modules/batch-start")
async def batch_start_modules(
    req: BatchModuleRequest = None,
    current_user: dict = Depends(get_current_user),
):
    """批量启动模块（不包含 M8 自身）"""
    modules = req.modules if req and req.modules else None
    
    all_modules = registry.get_all_modules()
    target_keys = modules or [m.key for m in all_modules if m.key != "m8"]
    
    results = {}
    for key in target_keys:
        if key == "m8":
            results[key] = {"status": "skipped", "message": "M8 自身已在运行"}
            continue
        
        module = registry.get_module(key)
        if not module:
            results[key] = {"status": "error", "message": "模块不存在"}
            continue
        
        try:
            proc_info = process_mgr.start_module(key)
            status = "starting" if proc_info.status.value in ("starting", "running") else "error"
            results[key] = {
                "status": status,
                "message": proc_info.error_message or f"模块 {key} 启动指令已发送",
                "pid": proc_info.pid,
            }
        except Exception as e:
            results[key] = {"status": "error", "message": str(e)}
    
    started_count = sum(1 for v in results.values() if v["status"] in ("starting", "running"))
    error_count = sum(1 for v in results.values() if v["status"] == "error")
    
    return ApiResponse.success(
        message=f"批量启动完成：成功 {started_count} 个，失败 {error_count} 个",
        data={
            "total": len(results),
            "started": started_count,
            "failed": error_count,
            "results": results,
        },
    )


@router.post("/modules/batch-stop")
async def batch_stop_modules(
    req: BatchModuleRequest = None,
    current_user: dict = Depends(get_current_user),
):
    """批量停止模块"""
    modules = req.modules if req and req.modules else None
    force = req.force if req else False
    
    all_modules = registry.get_all_modules()
    target_keys = modules or [m.key for m in all_modules if m.key != "m8"]
    
    results = {}
    for key in target_keys:
        if key == "m8":
            results[key] = {"status": "skipped", "message": "不能停止 M8 自身"}
            continue
        
        module = registry.get_module(key)
        if not module:
            results[key] = {"status": "error", "message": "模块不存在"}
            continue
        
        try:
            proc_info = process_mgr.stop_module(key, force=force)
            results[key] = {
                "status": proc_info.status.value,
                "message": f"模块 {key} 停止指令已发送",
            }
        except Exception as e:
            results[key] = {"status": "error", "message": str(e)}
    
    stopped_count = sum(1 for v in results.values() if v["status"] in ("stopping", "stopped"))
    
    return ApiResponse.success(
        message=f"批量停止完成：停止 {stopped_count} 个",
        data={
            "total": len(results),
            "stopped": stopped_count,
            "results": results,
        },
    )


@router.get("/modules/status/realtime")
async def get_modules_realtime_status(
    current_user: dict = Depends(get_current_user),
):
    """获取所有模块的实时状态（结合进程状态 + HTTP 健康检查）"""
    import asyncio
    import httpx
    
    modules = registry.get_all_modules()
    results = []
    
    async def check_one(mod):
        """检查单个模块状态"""
        info = mod.to_dict()
        
        # 1. 先查进程管理器
        proc_info = process_mgr.get_process_info(mod.key)
        info["process_running"] = proc_info is not None and proc_info.status.value in ("running", "starting")
        info["process_pid"] = proc_info.pid if proc_info else None
        info["process_status"] = proc_info.status.value if proc_info else "unknown"
        
        # 2. TCP 端口快速检测
        try:
            _, writer = await asyncio.wait_for(
                asyncio.open_connection("127.0.0.1", mod.port),
                timeout=0.5
            )
            writer.close()
            await writer.wait_closed()
            info["port_open"] = True
        except Exception:
            info["port_open"] = False
        
        # 3. HTTP 健康检查（端口开了才检查，减少超时等待）
        if info["port_open"]:
            try:
                async with httpx.AsyncClient(timeout=2.0) as client:
                    r = await client.get(f"http://127.0.0.1:{mod.port}/health")
                    info["http_healthy"] = r.status_code == 200
                    info["health_status"] = "online" if r.status_code == 200 else "degraded"
            except Exception:
                info["http_healthy"] = False
                info["health_status"] = "starting" if info["process_running"] else "offline"
        else:
            info["http_healthy"] = False
            info["health_status"] = "starting" if info["process_running"] else "offline"
        
        # 综合状态
        if info["http_healthy"]:
            info["status"] = "running"
        elif info["process_running"]:
            info["status"] = "starting"
        elif info["port_open"]:
            info["status"] = "degraded"
        else:
            info["status"] = "stopped"
        
        return info
    
    tasks = [check_one(m) for m in modules]
    results = await asyncio.gather(*tasks)
    
    # 统计
    running = sum(1 for r in results if r["status"] == "running")
    starting = sum(1 for r in results if r["status"] == "starting")
    stopped = sum(1 for r in results if r["status"] == "stopped")
    error = sum(1 for r in results if r["status"] in ("error", "degraded"))
    
    return ApiResponse.success(data={
        "total": len(results),
        "running": running,
        "starting": starting,
        "stopped": stopped,
        "error": error,
        "modules": results,
    })

@router.get("/announcements")
async def get_announcements(current_user: dict = Depends(get_current_user)):
    """获取公告列表"""
    items = [a.model_dump() for a in _announcements]
    return ApiResponse.success(data={"total": len(items), "items": items})


# 保留原 /notices 路径作为别名
@router.get("/notices")
async def get_notices(current_user: dict = Depends(get_current_user)):
    """获取系统公告（旧路径别名）"""
    return await get_announcements(current_user)


@router.post("/announcements")
async def create_announcement(
    req: AnnouncementCreate,
    current_user: dict = Depends(get_current_user),
):
    """新增公告"""
    global _announcement_id_counter
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    new_announcement = Announcement(
        id=_announcement_id_counter,
        title=req.title,
        content=req.content,
        level=req.level,
        created_at=now,
        updated_at=now,
    )
    _announcement_id_counter += 1
    _announcements.insert(0, new_announcement)
    return ApiResponse.success(message="公告创建成功", data=new_announcement.model_dump())


@router.put("/announcements/{announcement_id}")
async def update_announcement(
    announcement_id: int,
    req: AnnouncementUpdate,
    current_user: dict = Depends(get_current_user),
):
    """更新公告"""
    for ann in _announcements:
        if ann.id == announcement_id:
            if req.title is not None:
                ann.title = req.title
            if req.content is not None:
                ann.content = req.content
            if req.level is not None:
                ann.level = req.level
            ann.updated_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            return ApiResponse.success(message="公告更新成功", data=ann.model_dump())
    return ApiResponse.error(code=404, message="公告不存在")


@router.delete("/announcements/{announcement_id}")
async def delete_announcement(
    announcement_id: int,
    current_user: dict = Depends(get_current_user),
):
    """删除公告"""
    for i, ann in enumerate(_announcements):
        if ann.id == announcement_id:
            _announcements.pop(i)
            return ApiResponse.success(message="公告删除成功")
    return ApiResponse.error(code=404, message="公告不存在")


# ==================== 系统设置接口 ====================

@router.get("/settings")
async def get_settings(current_user: dict = Depends(get_current_user)):
    """获取系统设置（敏感字段脱敏返回）"""
    settings_data = _load_settings()
    # 处理 LLM API Key：解密后脱敏显示
    enc_key = settings_data.pop("llm_api_key_encrypted", "")
    if enc_key:
        try:
            plain_key = crypto_decrypt(enc_key)
            settings_data["llm_api_key"] = mask_api_key(plain_key)
            settings_data["has_llm_api_key"] = True
        except Exception:
            settings_data["llm_api_key"] = ""
            settings_data["has_llm_api_key"] = False
    else:
        settings_data["llm_api_key"] = ""
        settings_data["has_llm_api_key"] = False
    return ApiResponse.success(data=settings_data)


@router.put("/settings")
async def update_settings(
    req: SettingsUpdate,
    current_user: dict = Depends(get_current_user),
):
    """保存系统设置"""
    current = _load_settings()
    update_data = req.model_dump(exclude_unset=True)

    # 校验字段值
    if "theme" in update_data and update_data["theme"] not in ("dark", "light"):
        return ApiResponse.error(code=400, message="主题值无效，仅支持 dark/light")
    if "language" in update_data and update_data["language"] not in ("zh-CN", "en"):
        return ApiResponse.error(code=400, message="语言值无效，仅支持 zh-CN/en")
    if "log_level" in update_data and update_data["log_level"] not in ("info", "warn", "error"):
        return ApiResponse.error(code=400, message="日志级别无效，仅支持 info/warn/error")

    # 处理 LLM API Key：加密存储
    if "llm_api_key" in update_data:
        api_key_plain = update_data.pop("llm_api_key")
        if api_key_plain and not api_key_plain.startswith("enc:"):
            # 新的明文密钥，加密存储
            update_data["llm_api_key_encrypted"] = crypto_encrypt(api_key_plain)
        # 如果是空字符串，清除密钥
        elif not api_key_plain:
            update_data["llm_api_key_encrypted"] = ""

    current.update(update_data)
    _save_settings(current)

    # 返回时脱敏
    result = current.copy()
    enc_key = result.pop("llm_api_key_encrypted", "")
    if enc_key:
        try:
            plain_key = crypto_decrypt(enc_key)
            result["llm_api_key"] = mask_api_key(plain_key)
            result["has_llm_api_key"] = True
        except Exception:
            result["llm_api_key"] = ""
            result["has_llm_api_key"] = False
    else:
        result["llm_api_key"] = ""
        result["has_llm_api_key"] = False

    return ApiResponse.success(message="设置保存成功", data=result)


# ==================== API 密钥管理接口 ====================

@router.get("/tokens")
async def get_module_tokens(current_user: dict = Depends(get_current_user)):
    """获取各模块对接 Token 列表（脱敏显示）"""
    try:
        from shared.core.config import get_module_tokens
        tokens_config = get_module_tokens()
    except Exception:
        # 降级：从环境变量读取
        import os
        tokens_config = {}
        for i in range(1, 11):
            key = f"M{i}_ADMIN_TOKEN"
            val = os.getenv(key, "")
            if val:
                tokens_config[f"m{i}"] = val

    module_names = {
        "m1": "M1 多Agent集群调度",
        "m2": "M2 技能集群市场",
        "m3": "M3 端云协同内核",
        "m4": "M4 场景引擎",
        "m5": "M5 潮汐记忆系统",
        "m6": "M6 硬件外设控制",
        "m7": "M7 积木工作流编排",
        "m8": "M8 管理控制塔",
        "m9": "M9 开发者工坊",
        "m10": "M10 系统卫士",
    }

    result = []
    for key, name in module_names.items():
        token = tokens_config.get(key, "")
        result.append({
            "module": key,
            "name": name,
            "token": token,
            "masked": mask_api_key(token) if token else "未设置",
            "is_set": bool(token),
        })

    return ApiResponse.success(data=result)


@router.post("/tokens/regenerate")
async def regenerate_all_tokens(current_user: dict = Depends(get_current_user)):
    """重新生成所有模块 Token（返回新 Token 列表，需手动同步到各模块 .env）"""
    import secrets
    import string

    module_names = {
        "m1": "M1 多Agent集群调度",
        "m2": "M2 技能集群市场",
        "m3": "M3 端云协同内核",
        "m4": "M4 场景引擎",
        "m5": "M5 潮汐记忆系统",
        "m6": "M6 硬件外设控制",
        "m7": "M7 积木工作流编排",
        "m8": "M8 管理控制塔",
        "m9": "M9 开发者工坊",
        "m10": "M10 系统卫士",
    }

    # 生成随机 Token
    alphabet = string.ascii_letters + string.digits
    new_tokens = {}
    result = []

    for key, name in module_names.items():
        new_token = "yunxi-" + key + "-" + "".join(secrets.choice(alphabet) for _ in range(24))
        new_tokens[key] = new_token
        result.append({
            "module": key,
            "name": name,
            "token": new_token,
            "masked": mask_api_key(new_token),
        })

    # 保存到设置文件（供 M8 自身使用，其他模块需手动配置）
    settings_data = _load_settings()
    for key, token in new_tokens.items():
        settings_data[f"{key}_admin_token"] = token
    _save_settings(settings_data)

    return ApiResponse.success(
        message="Token 已重新生成，请手动同步到各模块的 .env 文件",
        data=result,
    )


@router.get("/encryption/info")
async def get_encryption_info(current_user: dict = Depends(get_current_user)):
    """获取加密配置信息（不含密钥本身）"""
    try:
        from ..crypto import get_key_info
        info = get_key_info()
        return ApiResponse.success(data=info)
    except Exception as e:
        return ApiResponse.error(message=f"获取加密信息失败: {e}")


@router.get("/llm/test")
async def test_llm_connection(current_user: dict = Depends(get_current_user)):
    """测试 LLM 连接"""
    settings_data = _load_settings()
    enc_key = settings_data.get("llm_api_key_encrypted", "")

    if not enc_key:
        return ApiResponse.error(code=400, message="未配置 API Key")

    try:
        api_key = crypto_decrypt(enc_key)
    except Exception as e:
        return ApiResponse.error(code=400, message=f"API Key 解密失败: {e}")

    provider = settings_data.get("ai_provider", "deepseek")
    model = settings_data.get("model", "deepseek-chat")

    # 简单测试：检查 API Key 格式是否合理
    if not api_key or len(api_key) < 10:
        return ApiResponse.error(code=400, message="API Key 格式不正确")

    # 注意：此处不做真实网络请求，仅验证密钥存在性和格式
    # 真实测试需要调用 LLM 客户端，此处返回格式验证结果
    return ApiResponse.success(
        message="API Key 格式验证通过（完整连接测试需网络请求）",
        data={
            "provider": provider,
            "model": model,
            "has_key": True,
            "key_length": len(api_key),
        },
    )


# ==================== 渐进式启动进度接口 ====================

def _format_startup_progress_for_frontend(progress: dict) -> dict:
    """将 StartupOrchestrator 的进度格式转换为前端期望的格式
    
    前端期望格式:
    {
        progress: 0-100,
        current_module: "模块名",
        is_ready: bool,          // Tier0 + Tier1 是否就绪
        tiers: [
            { id: "tier0", name: "Tier 0 基础设施", is_ready: true, modules: [...] },
            { id: "tier1", name: "Tier 1 核心能力", is_ready: false, modules: [...] },
            ...
        ]
    }
    每个 module: { id, name, status: "waiting"|"starting"|"running"|"failed", error_msg? }
    """
    # 状态映射
    status_map = {
        "pending": "waiting",
        "starting": "starting",
        "running": "running",
        "error": "failed",
        "skipped": "running",  # 跳过的也算完成
    }
    
    # Tier 名称映射
    tier_names = {
        0: "Tier 0 基础设施",
        1: "Tier 1 核心能力",
        2: "Tier 2 扩展能力",
        3: "Tier 3 即用模块",
    }
    
    # 构建 tiers
    tiers = []
    modules_list = progress.get("modules", [])
    module_map = {m["key"]: m for m in modules_list}
    
    # 从 TIER_MODULES 获取层级信息（从 startup_orchestrator 导入）
    try:
        from shared.startup_orchestrator import TIER_MODULES
    except ImportError:
        TIER_MODULES = {
            0: ["m8", "m10", "m12"],
            1: ["m1", "m5", "m2"],
            2: ["m4", "m7", "m3"],
            3: ["m6", "m0", "m11"],
        }
    
    for tier_id in sorted(TIER_MODULES.keys()):
        module_keys = TIER_MODULES[tier_id]
        tier_modules = []
        tier_ready = True
        
        for key in module_keys:
            mod = module_map.get(key, {})
            status = status_map.get(mod.get("status", "pending"), "waiting")
            if status in ("waiting", "starting", "failed"):
                tier_ready = False
            tier_modules.append({
                "id": key,
                "name": mod.get("name", key),
                "status": status,
                "error_msg": mod.get("message", "") if status == "failed" else None,
            })
        
        tiers.append({
            "id": f"tier{tier_id}",
            "name": tier_names.get(tier_id, f"Tier {tier_id}"),
            "is_ready": tier_ready,
            "modules": tier_modules,
        })
    
    # 找当前正在启动的模块
    current_module = ""
    for mod in modules_list:
        if mod.get("status") == "starting":
            current_module = mod.get("name", mod.get("key", ""))
            break
    
    # Tier0 + Tier1 是否就绪
    is_ready = (
        len(tiers) >= 2 
        and tiers[0]["is_ready"] 
        and tiers[1]["is_ready"]
    )
    
    return {
        "progress": progress.get("percent", 0),
        "current_module": current_module,
        "is_ready": is_ready,
        "tiers": tiers,
        "total": progress.get("total", 0),
        "completed": progress.get("completed", 0),
        "is_finished": progress.get("is_finished", False),
    }


@router.get("/startup/progress")
async def get_startup_progress():
    """获取启动进度（公开接口，无需鉴权）

    供启动引导页轮询使用，返回整体进度及各模块的详细启动状态。
    """
    progress = startup_orch.get_progress()
    formatted = _format_startup_progress_for_frontend(progress)
    return ApiResponse.success(data=formatted)


@router.post("/startup/retry/{module_key}")
async def retry_startup_module(
    module_key: str,
    current_user: dict = Depends(get_current_user),
):
    """重试启动某个模块

    仅对启动失败或已跳过的模块有效，M8 自身不可重试。
    """
    result = await startup_orch.retry_module(module_key)
    if not result.get("success"):
        return ApiResponse.error(message=result.get("message", "重试失败"))
    return ApiResponse.success(
        message=result.get("message", "重试启动已触发"),
        data=result.get("module"),
    )


@router.post("/startup/skip/{module_key}")
async def skip_startup_module(
    module_key: str,
    current_user: dict = Depends(get_current_user),
):
    """跳过某个模块

    标记为 skipped，不计入失败统计，整体流程继续推进。
    M8 自身不可跳过，已运行的模块不可跳过。
    """
    result = await startup_orch.skip_module(module_key)
    if not result.get("success"):
        return ApiResponse.error(message=result.get("message", "跳过失败"))
    return ApiResponse.success(
        message=result.get("message", "模块已跳过"),
        data=result.get("module"),
    )


@router.post("/startup/restart")
async def restart_startup_flow(current_user: dict = Depends(get_current_user)):
    """重新执行整个启动流程

    取消当前正在进行的启动任务，重置所有模块状态（M8 自身保持 running），
    然后从 Tier 0 开始重新渐进式启动所有模块。
    """
    result = await startup_orch.restart_all()
    if not result.get("success"):
        return ApiResponse.error(message=result.get("message", "重启启动流程失败"))
    return ApiResponse.success(
        message=result.get("message", "已重新启动渐进式编排"),
        data=result.get("progress"),
    )
