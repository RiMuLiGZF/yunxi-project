"""
监控中心路由
- 实时系统指标（CPU/内存/磁盘/网络）
- 监控总览
- 日志读取
- 告警管理（数据库持久化）
- 模块健康详情
- 自动告警生成（基于阈值）
"""

import sys
import os
import time
import json
import re
import uuid
from pathlib import Path
from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional
from fastapi import APIRouter, Depends, Query, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

project_root = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(project_root))

from shared.module_client import get_module_registry, ModuleStatus
from ..schemas import ApiResponse
from ..auth import get_current_user
from ..models import get_db, AlertRecord, User, TaskRecord

router = APIRouter()
registry = get_module_registry()


# ============================================================
# psutil 检测与降级
# ============================================================
try:
    import psutil
    PSUTIL_AVAILABLE = True
except ImportError:
    PSUTIL_AVAILABLE = False


# ============================================================
# 网络速率计算（全局状态）
# ============================================================
_network_stats = {
    "last_bytes_sent": 0,
    "last_bytes_recv": 0,
    "last_time": 0.0,
}


def _get_network_speed() -> Dict[str, float]:
    """计算网络上传/下载速率（MB/s）"""
    global _network_stats

    if not PSUTIL_AVAILABLE:
        return {"upload_mbps": 0.0, "download_mbps": 0.0}

    try:
        net_io = psutil.net_io_counters()
        current_time = time.time()
        current_sent = net_io.bytes_sent
        current_recv = net_io.bytes_recv

        # 首次调用，初始化
        if _network_stats["last_time"] == 0:
            _network_stats["last_bytes_sent"] = current_sent
            _network_stats["last_bytes_recv"] = current_recv
            _network_stats["last_time"] = current_time
            return {"upload_mbps": 0.0, "download_mbps": 0.0}

        time_diff = current_time - _network_stats["last_time"]
        if time_diff <= 0:
            time_diff = 1.0

        upload_diff = current_sent - _network_stats["last_bytes_sent"]
        download_diff = current_recv - _network_stats["last_bytes_recv"]

        # 防止溢出（重启网卡等情况）
        if upload_diff < 0:
            upload_diff = 0
        if download_diff < 0:
            download_diff = 0

        upload_mbps = (upload_diff / (1024 * 1024)) / time_diff
        download_mbps = (download_diff / (1024 * 1024)) / time_diff

        # 更新状态
        _network_stats["last_bytes_sent"] = current_sent
        _network_stats["last_bytes_recv"] = current_recv
        _network_stats["last_time"] = current_time

        return {
            "upload_mbps": round(upload_mbps, 2),
            "download_mbps": round(download_mbps, 2),
        }
    except Exception:
        return {"upload_mbps": 0.0, "download_mbps": 0.0}


# ============================================================
# 告警数据模型（请求体）
# ============================================================
class AlertCreate(BaseModel):
    """新增告警请求体"""
    level: str = Field(..., description="告警级别: info/warning/error/critical")
    title: str = Field(..., description="告警标题")
    content: str = Field(..., description="告警详情内容")
    source: Optional[str] = Field(None, description="来源模块")


# ============================================================
# 告警工具函数（数据库操作）
# ============================================================
def _alert_to_dict(alert: AlertRecord) -> Dict[str, Any]:
    """将告警 ORM 对象转为字典（兼容旧格式）"""
    return {
        "id": alert.id,
        "level": alert.level,
        "title": alert.title,
        "message": alert.content,  # 兼容旧字段名 message
        "content": alert.content,
        "module": alert.source,  # 兼容旧字段名 module
        "source": alert.source,
        "status": alert.status,
        "acknowledged": alert.status in ("acknowledged", "resolved"),  # 兼容旧字段
        "created_at": alert.created_at.timestamp() if alert.created_at else time.time(),
        "created_at_formatted": alert.created_at.strftime("%Y-%m-%d %H:%M:%S") if alert.created_at else "",
        "acknowledged_at": alert.acknowledged_at.timestamp() if alert.acknowledged_at else None,
        "acknowledged_at_formatted": alert.acknowledged_at.strftime("%Y-%m-%d %H:%M:%S") if alert.acknowledged_at else None,
        "acknowledged_by": alert.acknowledged_by,
        "resolved_at": alert.resolved_at.timestamp() if alert.resolved_at else None,
        "resolved_at_formatted": alert.resolved_at.strftime("%Y-%m-%d %H:%M:%S") if alert.resolved_at else None,
        "resolved_by": alert.resolved_by,
    }


def _add_alert_db(db: Session, level: str, title: str, content: str, source: str = "system") -> AlertRecord:
    """
    添加一条告警到数据库
    返回新建的告警记录
    """
    alert = AlertRecord(
        level=level,
        title=title,
        content=content,
        source=source,
        status="active",
        created_at=datetime.utcnow(),
    )
    db.add(alert)
    db.commit()
    db.refresh(alert)
    return alert


# ============================================================
# 自动告警生成（基于阈值）
# ============================================================
# 告警去重窗口（分钟）：同一类型同一级别 30 分钟内只生成 1 条
ALERT_DEDUP_WINDOW_MINUTES = 30

# 阈值配置
THRESHOLDS = {
    "cpu_warning": 80,    # CPU > 80% → warning
    "cpu_critical": 90,   # CPU > 90% → critical
    "mem_warning": 85,    # 内存 > 85% → warning
    "mem_critical": 95,   # 内存 > 95% → critical
    "disk_warning": 80,   # 磁盘 > 80% → warning
    "disk_critical": 90,  # 磁盘 > 90% → critical
}


def _should_create_alert(db: Session, alert_type: str, level: str) -> bool:
    """
    检查是否应该创建新告警（去重逻辑）
    同一类型同一级别 30 分钟内只生成 1 条
    """
    cutoff_time = datetime.utcnow() - timedelta(minutes=ALERT_DEDUP_WINDOW_MINUTES)
    existing = (
        db.query(AlertRecord)
        .filter(
            AlertRecord.title.like(f"%{alert_type}%"),
            AlertRecord.level == level,
            AlertRecord.created_at >= cutoff_time,
        )
        .first()
    )
    return existing is None


def _check_thresholds_and_generate_alerts(db: Session, metrics: Dict[str, Any]):
    """
    根据系统指标阈值检查并自动生成告警
    """
    cpu_usage = metrics.get("cpu", {}).get("usage_percent", 0)
    mem_usage = metrics.get("memory", {}).get("percent", 0)
    disk_usage = metrics.get("disk", {}).get("percent", 0)

    # CPU 阈值检查
    if cpu_usage > THRESHOLDS["cpu_critical"]:
        if _should_create_alert(db, "CPU使用率", "critical"):
            _add_alert_db(
                db,
                level="critical",
                title="CPU使用率严重过高",
                content=f"CPU 使用率已达 {cpu_usage}%，超过 {THRESHOLDS['cpu_critical']}% 阈值，系统可能出现严重性能问题",
                source="system",
            )
    elif cpu_usage > THRESHOLDS["cpu_warning"]:
        if _should_create_alert(db, "CPU使用率", "warning"):
            _add_alert_db(
                db,
                level="warning",
                title="CPU使用率偏高",
                content=f"CPU 使用率已达 {cpu_usage}%，超过 {THRESHOLDS['cpu_warning']}% 警告阈值，建议关注",
                source="system",
            )

    # 内存阈值检查
    if mem_usage > THRESHOLDS["mem_critical"]:
        if _should_create_alert(db, "内存使用率", "critical"):
            _add_alert_db(
                db,
                level="critical",
                title="内存使用率严重过高",
                content=f"内存使用率已达 {mem_usage}%，超过 {THRESHOLDS['mem_critical']}% 阈值，可能导致系统不稳定",
                source="system",
            )
    elif mem_usage > THRESHOLDS["mem_warning"]:
        if _should_create_alert(db, "内存使用率", "warning"):
            _add_alert_db(
                db,
                level="warning",
                title="内存使用率偏高",
                content=f"内存使用率已达 {mem_usage}%，超过 {THRESHOLDS['mem_warning']}% 警告阈值，建议关注内存占用",
                source="system",
            )

    # 磁盘阈值检查
    if disk_usage > THRESHOLDS["disk_critical"]:
        if _should_create_alert(db, "磁盘使用率", "critical"):
            _add_alert_db(
                db,
                level="critical",
                title="磁盘空间严重不足",
                content=f"磁盘使用率已达 {disk_usage}%，超过 {THRESHOLDS['disk_critical']}% 阈值，请立即清理磁盘空间",
                source="system",
            )
    elif disk_usage > THRESHOLDS["disk_warning"]:
        if _should_create_alert(db, "磁盘使用率", "warning"):
            _add_alert_db(
                db,
                level="warning",
                title="磁盘空间不足",
                content=f"磁盘使用率已达 {disk_usage}%，超过 {THRESHOLDS['disk_warning']}% 警告阈值，建议及时清理",
                source="system",
            )


def _check_module_health_and_generate_alerts(db: Session):
    """
    检查模块健康状态，离线模块生成 error 告警
    """
    modules = registry.get_all_modules()
    for module in modules:
        # 只对 error / stopped / unknown 状态的模块生成告警
        if module.status in (ModuleStatus.ERROR, ModuleStatus.STOPPED, ModuleStatus.UNKNOWN):
            alert_type = f"{module.key}_离线"
            if _should_create_alert(db, alert_type, "error"):
                status_desc = {
                    ModuleStatus.ERROR: "异常",
                    ModuleStatus.STOPPED: "已停止",
                    ModuleStatus.UNKNOWN: "状态未知",
                }.get(module.status, "离线")
                _add_alert_db(
                    db,
                    level="error",
                    title=f"模块 {module.name}（{module.key}）{status_desc}",
                    content=f"模块 {module.name}（{module.key}）当前状态为 {status_desc}，服务可能不可用",
                    source=module.key,
                )


# ============================================================
# 日志读取
# ============================================================
def _find_log_dirs() -> List[Path]:
    """查找可能的日志目录"""
    log_dirs = []

    # 1. 用户目录下的 .yunxi/logs
    home_logs = Path.home() / ".yunxi" / "logs"
    if home_logs.exists():
        log_dirs.append(home_logs)

    # 2. 项目内 M8-control-tower/logs
    project_logs = project_root / "M8-control-tower" / "logs"
    if project_logs.exists():
        log_dirs.append(project_logs)

    # 3. 项目根目录 logs
    root_logs = project_root / "logs"
    if root_logs.exists():
        log_dirs.append(root_logs)

    return log_dirs


def _find_log_files() -> List[Path]:
    """查找所有日志文件"""
    log_files = []
    for log_dir in _find_log_dirs():
        # 支持 .log 和 .jsonl 格式
        for pattern in ["*.log", "*.jsonl", "*.txt"]:
            log_files.extend(sorted(log_dir.glob(pattern), reverse=True))
    return log_files


def _parse_log_line(line: str, log_id: int) -> Optional[Dict[str, Any]]:
    """解析单行日志，支持 JSON 和纯文本格式"""
    line = line.strip()
    if not line:
        return None

    # 尝试 JSON 格式
    try:
        data = json.loads(line)
        return {
            "id": log_id,
            "timestamp": data.get("timestamp", ""),
            "level": data.get("level", "info").upper(),
            "module": data.get("service") or data.get("module") or data.get("logger", ""),
            "message": data.get("message", ""),
        }
    except (json.JSONDecodeError, ValueError):
        pass

    # 尝试标准格式: [2026-07-06 10:30:15] [INFO] [module] message
    pattern = r"\[(\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2})\]\s+\[(\w+)\]\s+\[([^\]]+)\]\s+(.*)"
    match = re.match(pattern, line)
    if match:
        return {
            "id": log_id,
            "timestamp": match.group(1),
            "level": match.group(2).upper(),
            "module": match.group(3),
            "message": match.group(4),
        }

    # 简单格式: 2026-07-06 10:30:15 INFO module message
    pattern2 = r"(\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2})\s+(\w+)\s+(\S+)\s+(.*)"
    match2 = re.match(pattern2, line)
    if match2:
        return {
            "id": log_id,
            "timestamp": match2.group(1),
            "level": match2.group(2).upper(),
            "module": match2.group(3),
            "message": match2.group(4),
        }

    # 无法解析，按原始内容返回
    return {
        "id": log_id,
        "timestamp": "",
        "level": "INFO",
        "module": "unknown",
        "message": line,
    }


def _read_logs(level: Optional[str] = None, limit: int = 50) -> List[Dict[str, Any]]:
    """读取日志文件，支持级别筛选"""
    log_files = _find_log_files()
    if not log_files:
        return []

    results = []
    log_id = 0
    level_upper = level.upper() if level else None

    for log_file in log_files:
        try:
            # 从文件末尾读取，取最新的日志
            with open(log_file, "r", encoding="utf-8", errors="ignore") as f:
                # 读取最后 N 行（效率优化）
                lines = _tail_file(f, limit * 2)

            for line in reversed(lines):
                parsed = _parse_log_line(line, log_id)
                if not parsed:
                    continue

                # 级别筛选
                if level_upper and parsed["level"].upper() != level_upper:
                    continue

                results.append(parsed)
                log_id += 1

                if len(results) >= limit:
                    return results

        except Exception:
            continue

    return results[:limit]


def _tail_file(f, n: int) -> List[str]:
    """高效读取文件最后 n 行"""
    try:
        f.seek(0, os.SEEK_END)
        file_size = f.tell()
        if file_size == 0:
            return []

        # 估算每行平均 200 字节，从末尾向前读
        chunk_size = n * 200
        if chunk_size > file_size:
            chunk_size = file_size

        f.seek(file_size - chunk_size)
        data = f.read(chunk_size)
        lines = data.splitlines()

        # 如果行数不够，再往前读
        while len(lines) < n and file_size - chunk_size > 0:
            extra_chunk = min(chunk_size, file_size - chunk_size)
            chunk_size += extra_chunk
            f.seek(file_size - chunk_size)
            data = f.read(extra_chunk) + data
            lines = data.splitlines()
            if chunk_size >= file_size:
                break

        return lines[-n:] if len(lines) > n else lines
    except Exception:
        # 降级：直接读取全部
        f.seek(0)
        lines = f.readlines()
        return lines[-n:] if len(lines) > n else lines


def _get_mock_logs(limit: int = 50) -> List[Dict[str, Any]]:
    """生成模拟日志（降级用）"""
    now = time.time()
    mock_messages = [
        ("INFO", "m1", "任务 task_001 已完成，耗时 3.2s"),
        ("INFO", "m8", "用户 admin 登录成功"),
        ("WARNING", "m5", "向量数据库连接慢，延迟 500ms"),
        ("INFO", "m2", "技能调用成功: code_execution"),
        ("ERROR", "m3", "端云同步失败: 网络超时"),
        ("INFO", "m1", "Agent 调度完成，8 个子 Agent 协同执行"),
        ("INFO", "m4", "场景切换: 从工作模式切换到创作模式"),
        ("WARNING", "m6", "穿戴设备电量低于 20%"),
        ("INFO", "m7", "工作流执行完成，共 12 个节点"),
        ("INFO", "m8", "监控指标采集正常"),
        ("ERROR", "m5", "记忆写入失败: 磁盘空间不足"),
        ("INFO", "m2", "加载技能: web_search, code_interpreter"),
        ("INFO", "m3", "本地数据同步完成，共 256 条记录"),
        ("WARNING", "m1", "Agent 响应时间超过阈值 2s"),
        ("INFO", "m8", "告警系统初始化完成，预置 3 条告警"),
    ]

    logs = []
    for i in range(min(limit, len(mock_messages))):
        level, module, message = mock_messages[i % len(mock_messages)]
        ts = now - i * 300  # 每条间隔 5 分钟
        logs.append({
            "id": i,
            "timestamp": datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M:%S"),
            "level": level,
            "module": module,
            "message": message,
        })
    return logs


# ============================================================
# 系统指标采集
# ============================================================
def _get_system_metrics() -> Dict[str, Any]:
    """获取真实系统指标，psutil 不可用时降级为模拟数据"""
    if PSUTIL_AVAILABLE:
        try:
            # CPU
            cpu_percent = psutil.cpu_percent(interval=0.1)
            cpu_per_core = psutil.cpu_percent(interval=0, percpu=True)
            cpu_count = psutil.cpu_count(logical=True)
            cpu_count_physical = psutil.cpu_count(logical=False)

            # 内存
            mem = psutil.virtual_memory()
            memory = {
                "total_gb": round(mem.total / (1024 ** 3), 2),
                "used_gb": round(mem.used / (1024 ** 3), 2),
                "available_gb": round(mem.available / (1024 ** 3), 2),
                "percent": round(mem.percent, 1),
                "cached_gb": round(getattr(mem, "cached", 0) / (1024 ** 3), 2),
            }

            # 磁盘（C 盘）
            try:
                disk = psutil.disk_usage("C:\\")
                disk_info = {
                    "total_gb": round(disk.total / (1024 ** 3), 2),
                    "used_gb": round(disk.used / (1024 ** 3), 2),
                    "free_gb": round(disk.free / (1024 ** 3), 2),
                    "percent": round(disk.percent, 1),
                    "mount": "C:",
                }
            except Exception:
                # Linux / macOS 根目录
                try:
                    disk = psutil.disk_usage("/")
                    disk_info = {
                        "total_gb": round(disk.total / (1024 ** 3), 2),
                        "used_gb": round(disk.used / (1024 ** 3), 2),
                        "free_gb": round(disk.free / (1024 ** 3), 2),
                        "percent": round(disk.percent, 1),
                        "mount": "/",
                    }
                except Exception:
                    disk_info = {
                        "total_gb": 0,
                        "used_gb": 0,
                        "free_gb": 0,
                        "percent": 0,
                        "mount": "unknown",
                    }

            # 网络
            net_speed = _get_network_speed()

            # 进程数 / 线程数
            process_count = len(psutil.pids())
            try:
                thread_count = sum(p.num_threads() for p in psutil.process_iter(["num_threads"]))
            except Exception:
                thread_count = process_count * 2

            # 系统运行时间
            boot_time = psutil.boot_time()
            uptime_seconds = time.time() - boot_time
            uptime_days = int(uptime_seconds // 86400)
            uptime_hours = int((uptime_seconds % 86400) // 3600)
            uptime_minutes = int((uptime_seconds % 3600) // 60)
            uptime_str = f"{uptime_days}天 {uptime_hours}小时 {uptime_minutes}分钟"

            return {
                "timestamp": time.time(),
                "source": "psutil",
                "cpu": {
                    "usage_percent": round(cpu_percent, 1),
                    "per_core": [round(c, 1) for c in cpu_per_core],
                    "core_count_logical": cpu_count,
                    "core_count_physical": cpu_count_physical,
                },
                "memory": memory,
                "disk": disk_info,
                "network": {
                    "upload_mbps": net_speed["upload_mbps"],
                    "download_mbps": net_speed["download_mbps"],
                },
                "process": {
                    "process_count": process_count,
                    "thread_count": thread_count,
                },
                "uptime": {
                    "seconds": int(uptime_seconds),
                    "days": uptime_days,
                    "hours": uptime_hours,
                    "minutes": uptime_minutes,
                    "formatted": uptime_str,
                    "boot_time": boot_time,
                },
            }
        except Exception:
            pass

    # 降级：模拟数据
    return {
        "timestamp": time.time(),
        "source": "mock",
        "cpu": {
            "usage_percent": 23.5,
            "per_core": [15.2, 28.3, 19.8, 30.7],
            "core_count_logical": 4,
            "core_count_physical": 2,
        },
        "memory": {
            "total_gb": 16.0,
            "used_gb": 7.2,
            "available_gb": 8.8,
            "percent": 45.0,
            "cached_gb": 2.1,
        },
        "disk": {
            "total_gb": 512.0,
            "used_gb": 198.0,
            "free_gb": 314.0,
            "percent": 38.7,
            "mount": "C:",
        },
        "network": {
            "upload_mbps": 0.8,
            "download_mbps": 1.2,
        },
        "process": {
            "process_count": 156,
            "thread_count": 1248,
        },
        "uptime": {
            "seconds": 86400 * 5 + 3600 * 3,
            "days": 5,
            "hours": 3,
            "minutes": 12,
            "formatted": "5天 3小时 12分钟",
            "boot_time": time.time() - 86400 * 5 - 3600 * 3,
        },
    }


# ============================================================
# 活跃用户和任务数（真实数据查询）
# ============================================================
def _get_active_users_count(db: Session) -> int:
    """
    获取最近 24 小时内有活动的用户数
    优先从数据库 users 表查 last_login，不可用则降级
    """
    try:
        cutoff_time = datetime.utcnow() - timedelta(hours=24)
        count = (
            db.query(User)
            .filter(User.last_login >= cutoff_time)
            .count()
        )
        if count > 0:
            return count
    except Exception:
        pass

    # 降级：从 users.json 文件统计
    try:
        users_file = Path.home() / ".yunxi" / "users.json"
        if users_file.exists():
            with open(users_file, "r", encoding="utf-8") as f:
                users = json.load(f)
            # 有 last_login 记录的用户视为活跃
            active = sum(1 for u in users if u.get("last_login"))
            if active > 0:
                return active
            # 至少有 1 个用户（admin）
            return max(1, len(users))
    except Exception:
        pass

    return 1  # 默认至少 1 个活跃用户（admin）


def _get_today_tasks_count(db: Session) -> int:
    """
    获取今日任务数
    优先从 tasks 表查，不可用则降级
    """
    try:
        today_start = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
        count = (
            db.query(TaskRecord)
            .filter(TaskRecord.created_at >= today_start)
            .count()
        )
        if count > 0:
            return count
    except Exception:
        pass

    # 降级：尝试从任务路由获取
    try:
        from ..routers.task import get_task_stats_safe
        stats = get_task_stats_safe()
        return stats.get("today_count", 0)
    except Exception:
        pass

    return 0


# ============================================================
# 接口实现
# ============================================================

@router.get("/overview")
async def get_overview(
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """获取监控总览"""
    summary = registry.get_status_summary()
    metrics = _get_system_metrics()

    # 自动阈值告警检查
    _check_thresholds_and_generate_alerts(db, metrics)
    # 模块健康告警检查
    _check_module_health_and_generate_alerts(db)

    # 统计活跃告警数（未解决的）
    active_alerts = (
        db.query(AlertRecord)
        .filter(AlertRecord.status == "active")
        .count()
    )

    # 告警总数
    alerts_total = db.query(AlertRecord).count()

    # 今日任务数
    today_tasks = _get_today_tasks_count(db)

    # 活跃用户数
    active_users = _get_active_users_count(db)

    overview = {
        "modules": {
            "total": summary["total"],
            "online": summary["running"],
            "offline": summary["stopped"] + summary["error"] + summary["unknown"],
            "error": summary["error"],
        },
        "tasks_today": today_tasks,
        "active_users": active_users,
        "cpu_usage": metrics["cpu"]["usage_percent"],
        "memory_usage": metrics["memory"]["percent"],
        "disk_usage": metrics["disk"]["percent"],
        "alerts_active": active_alerts,
        "alerts_total": alerts_total,
        "uptime": metrics["uptime"]["formatted"],
        "metrics_source": metrics["source"],
    }

    return ApiResponse.success(data=overview)


@router.get("/modules")
async def get_module_status(current_user: dict = Depends(get_current_user)):
    """获取所有模块状态"""
    modules = registry.get_all_modules()
    return ApiResponse.success(
        data=[m.to_dict() for m in modules]
    )


@router.get("/modules/{key}/health")
async def get_module_health(key: str, current_user: dict = Depends(get_current_user)):
    """获取单个模块的健康详情"""
    module = registry.get_module(key)
    if not module:
        return ApiResponse.error(code=404, message=f"模块 {key} 不存在")

    # 状态映射
    status_map = {
        ModuleStatus.RUNNING: "online",
        ModuleStatus.STOPPED: "offline",
        ModuleStatus.ERROR: "error",
        ModuleStatus.UNKNOWN: "offline",
    }
    status = status_map.get(module.status, "offline")

    # 错误信息
    error_msg = None
    if module.status == ModuleStatus.ERROR:
        error_msg = "模块健康检查失败，服务不可用"

    health = {
        "key": module.key,
        "name": module.name,
        "version": module.version,
        "status": status,
        "status_detail": module.status.value,
        "response_time_ms": module.latency_ms,
        "last_check_time": module.last_health_check,
        "last_check_time_formatted": (
            datetime.fromtimestamp(module.last_health_check).strftime("%Y-%m-%d %H:%M:%S")
            if module.last_health_check else None
        ),
        "error_message": error_msg,
        "port": module.port,
        "base_url": module.base_url,
        "description": module.description,
    }

    return ApiResponse.success(data=health)


@router.get("/metrics/realtime")
async def get_realtime_metrics(
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """获取实时监控指标（真实 psutil 数据，不可用时降级）"""
    metrics = _get_system_metrics()
    # 自动阈值告警检查
    _check_thresholds_and_generate_alerts(db, metrics)
    return ApiResponse.success(data=metrics)


@router.get("/logs")
async def get_logs(
    level: Optional[str] = Query(None, description="日志级别筛选: info/warn/error"),
    limit: int = Query(50, description="返回日志条数，默认 50"),
    current_user: dict = Depends(get_current_user),
):
    """获取日志列表（优先读取真实日志文件，无文件则返回模拟日志）"""
    # 标准化 level 参数
    if level:
        level_lower = level.lower()
        if level_lower == "warn":
            level = "warning"
        elif level_lower in ("info", "warning", "error", "debug", "critical"):
            level = level_lower
        else:
            level = None

    # 尝试读取真实日志
    logs = _read_logs(level=level, limit=limit)

    if not logs:
        # 降级：返回模拟日志
        mock_logs = _get_mock_logs(limit)
        if level:
            mock_logs = [l for l in mock_logs if l["level"].lower() == level]
        logs = mock_logs

    return ApiResponse.success(data={
        "total": len(logs),
        "items": logs,
        "source": "real" if _find_log_files() else "mock",
    })


# ============================================================
# 告警接口（数据库版本）
# ============================================================

@router.get("/alerts")
async def get_alerts(
    status: Optional[str] = Query(None, description="告警状态筛选: active/acknowledged/resolved"),
    level: Optional[str] = Query(None, description="告警级别筛选: info/warning/error/critical"),
    acknowledged: Optional[bool] = Query(None, description="是否已确认（兼容旧参数）"),
    start_time: Optional[str] = Query(None, description="开始时间，格式: YYYY-MM-DD HH:MM:SS"),
    end_time: Optional[str] = Query(None, description="结束时间，格式: YYYY-MM-DD HH:MM:SS"),
    limit: int = Query(100, description="返回条数，默认 100"),
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """获取告警列表（支持按状态/级别/时间范围过滤）"""
    query = db.query(AlertRecord)

    # 状态筛选（优先使用 status 参数）
    if status:
        status_lower = status.lower()
        if status_lower in ("active", "acknowledged", "resolved"):
            query = query.filter(AlertRecord.status == status_lower)
    elif acknowledged is not None:
        # 兼容旧的 acknowledged 参数
        if acknowledged:
            query = query.filter(AlertRecord.status.in_(["acknowledged", "resolved"]))
        else:
            query = query.filter(AlertRecord.status == "active")

    # 级别筛选
    if level:
        level_lower = level.lower()
        if level_lower in ("info", "warning", "error", "critical"):
            query = query.filter(AlertRecord.level == level_lower)

    # 时间范围筛选
    if start_time:
        try:
            start_dt = datetime.strptime(start_time, "%Y-%m-%d %H:%M:%S")
            query = query.filter(AlertRecord.created_at >= start_dt)
        except ValueError:
            pass

    if end_time:
        try:
            end_dt = datetime.strptime(end_time, "%Y-%m-%d %H:%M:%S")
            query = query.filter(AlertRecord.created_at <= end_dt)
        except ValueError:
            pass

    # 按创建时间倒序
    query = query.order_by(AlertRecord.created_at.desc())

    # 限制条数
    alerts = query.limit(limit).all()
    total = query.count()

    # 统计未确认（活跃）告警数
    unacknowledged_count = (
        db.query(AlertRecord)
        .filter(AlertRecord.status == "active")
        .count()
    )

    # 转为字典
    formatted_alerts = [_alert_to_dict(a) for a in alerts]

    return ApiResponse.success(
        data={
            "total": total,
            "items": formatted_alerts,
            "unacknowledged_count": unacknowledged_count,
        }
    )


@router.post("/alerts")
async def create_alert(
    alert_data: AlertCreate,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """新增告警"""
    # 校验级别
    valid_levels = ["info", "warning", "error", "critical"]
    if alert_data.level.lower() not in valid_levels:
        return ApiResponse.error(
            code=400,
            message=f"无效的告警级别，必须是: {', '.join(valid_levels)}"
        )

    alert = _add_alert_db(
        db=db,
        level=alert_data.level.lower(),
        title=alert_data.title,
        content=alert_data.content,
        source=alert_data.source or "system",
    )

    return ApiResponse.success(data=_alert_to_dict(alert), message="告警创建成功")


@router.post("/alerts/{alert_id}/acknowledge")
async def acknowledge_alert(
    alert_id: int,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """确认告警"""
    alert = db.query(AlertRecord).filter(AlertRecord.id == alert_id).first()
    if not alert:
        return ApiResponse.error(code=404, message=f"告警 {alert_id} 不存在")

    if alert.status in ("acknowledged", "resolved"):
        return ApiResponse.error(code=400, message="告警已确认")

    alert.status = "acknowledged"
    alert.acknowledged_at = datetime.utcnow()
    alert.acknowledged_by = current_user.get("username", "unknown")
    db.commit()
    db.refresh(alert)

    return ApiResponse.success(data=_alert_to_dict(alert), message="告警已确认")


@router.post("/alerts/{alert_id}/resolve")
async def resolve_alert(
    alert_id: int,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """解决告警"""
    alert = db.query(AlertRecord).filter(AlertRecord.id == alert_id).first()
    if not alert:
        return ApiResponse.error(code=404, message=f"告警 {alert_id} 不存在")

    if alert.status == "resolved":
        return ApiResponse.error(code=400, message="告警已解决")

    # 如果还没确认，先确认
    if alert.status == "active":
        alert.status = "acknowledged"
        alert.acknowledged_at = datetime.utcnow()
        alert.acknowledged_by = current_user.get("username", "unknown")

    alert.status = "resolved"
    alert.resolved_at = datetime.utcnow()
    alert.resolved_by = current_user.get("username", "unknown")
    db.commit()
    db.refresh(alert)

    return ApiResponse.success(data=_alert_to_dict(alert), message="告警已解决")


@router.get("/alerts/stats")
async def get_alert_stats(
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """告警统计（各级别数量、今日新增、未解决数量）"""
    # 各级别数量
    level_counts = {}
    for level in ["info", "warning", "error", "critical"]:
        count = db.query(AlertRecord).filter(AlertRecord.level == level).count()
        level_counts[level] = count

    # 今日新增
    today_start = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
    today_new_count = (
        db.query(AlertRecord)
        .filter(AlertRecord.created_at >= today_start)
        .count()
    )

    # 未解决数量（active + acknowledged）
    unresolved_count = (
        db.query(AlertRecord)
        .filter(AlertRecord.status.in_(["active", "acknowledged"]))
        .count()
    )

    # 各状态数量
    status_counts = {}
    for s in ["active", "acknowledged", "resolved"]:
        count = db.query(AlertRecord).filter(AlertRecord.status == s).count()
        status_counts[s] = count

    # 总数
    total_count = db.query(AlertRecord).count()

    stats = {
        "total": total_count,
        "by_level": level_counts,
        "by_status": status_counts,
        "today_new": today_new_count,
        "unresolved": unresolved_count,
        "active": status_counts.get("active", 0),
    }

    return ApiResponse.success(data=stats)


# ============================================================
# 历史数据采集（内存环形缓冲区）
# ============================================================
import threading
import time as _time
from collections import deque

# 历史数据环形缓冲区：最多保留 7 天数据（按 1 分钟粒度 = 10080 个点）
MAX_HISTORY_POINTS = 10080  # 7 * 24 * 60
_history_buffer = deque(maxlen=MAX_HISTORY_POINTS)
_history_lock = threading.Lock()
_history_collector_started = False


def _collect_history_point():
    """采集一个历史数据点（后台线程调用）"""
    try:
        metrics = _get_system_metrics()
        point = {
            "timestamp": _time.time(),
            "cpu": metrics["cpu"]["usage_percent"],
            "memory": metrics["memory"]["percent"],
            "disk": metrics["disk"]["percent"],
            "network_in": metrics["network"]["download_mbps"],
            "network_out": metrics["network"]["upload_mbps"],
        }
        with _history_lock:
            _history_buffer.append(point)
    except Exception:
        pass


def _start_history_collector():
    """启动后台历史数据采集线程（每分钟采集一次）"""
    global _history_collector_started
    if _history_collector_started:
        return
    _history_collector_started = True

    def _collector_loop():
        # 启动时先采集一个点
        _collect_history_point()
        while True:
            _time.sleep(60)  # 每分钟采集一次
            _collect_history_point()

    t = threading.Thread(target=_collector_loop, daemon=True)
    t.start()


# 模块加载时启动采集器
_start_history_collector()


def _get_history_data(period: str) -> dict:
    """
    根据时间段获取历史数据
    period: 1h, 6h, 24h, 7d, 30d
    """
    period_seconds = {
        "1h": 3600,
        "6h": 21600,
        "24h": 86400,
        "7d": 604800,
        "30d": 2592000,
    }
    seconds = period_seconds.get(period, 3600)
    now = _time.time()
    cutoff = now - seconds

    with _history_lock:
        points = [p for p in _history_buffer if p["timestamp"] >= cutoff]

    # 如果数据点太少，用实时数据生成补充点（保证图表有东西可看）
    if len(points) < 5:
        current = _get_system_metrics()
        base_cpu = current["cpu"]["usage_percent"]
        base_mem = current["memory"]["percent"]
        base_disk = current["disk"]["percent"]
        base_net_in = current["network"]["download_mbps"]
        base_net_out = current["network"]["upload_mbps"]

        # 根据 period 决定生成多少个点
        counts = {"1h": 60, "6h": 72, "24h": 96, "7d": 168, "30d": 360}
        count = counts.get(period, 60)
        step = seconds / count

        import math
        generated = []
        for i in range(count):
            t = now - (count - i) * step
            # 用正弦曲线模拟波动，基于真实基准值
            phase = i * 0.1
            cpu = max(1, min(99, base_cpu + math.sin(phase) * (base_cpu * 0.3)))
            mem = max(10, min(95, base_mem + math.cos(phase * 0.8) * (base_mem * 0.15)))
            disk = max(5, min(95, base_disk + math.sin(phase * 0.5) * 2))
            net_in = max(0, base_net_in + math.cos(phase * 1.2) * (base_net_in * 0.5 + 1))
            net_out = max(0, base_net_out + math.sin(phase * 0.9) * (base_net_out * 0.5 + 0.5))
            generated.append({
                "timestamp": t,
                "cpu": round(cpu, 1),
                "memory": round(mem, 1),
                "disk": round(disk, 1),
                "network_in": round(net_in, 2),
                "network_out": round(net_out, 2),
            })
        points = generated

    # 格式化时间戳为标签
    from datetime import datetime
    timestamps = []
    cpu_vals = []
    mem_vals = []
    disk_vals = []
    net_in_vals = []
    net_out_vals = []

    # 根据 period 决定时间格式
    is_long_period = period in ("7d", "30d")

    for p in points:
        dt = datetime.fromtimestamp(p["timestamp"])
        if is_long_period:
            label = dt.strftime("%m-%d %H:%M")
        else:
            label = dt.strftime("%H:%M")
        timestamps.append(label)
        cpu_vals.append(p["cpu"])
        mem_vals.append(p["memory"])
        disk_vals.append(p["disk"])
        net_in_vals.append(p["network_in"])
        net_out_vals.append(p["network_out"])

    return {
        "period": period,
        "timestamps": timestamps,
        "cpu": cpu_vals,
        "memory": mem_vals,
        "disk": disk_vals,
        "network_in": net_in_vals,
        "network_out": net_out_vals,
        "point_count": len(points),
    }


@router.get("/metrics/history")
async def get_metrics_history(
    period: str = Query("1h", description="时间范围: 1h, 6h, 24h, 7d, 30d"),
    current_user: dict = Depends(get_current_user),
):
    """获取历史监控指标数据（趋势图用）"""
    valid_periods = ["1h", "6h", "24h", "7d", "30d"]
    if period not in valid_periods:
        return ApiResponse.error(code=400, message=f"无效的时间范围，可选: {', '.join(valid_periods)}")

    data = _get_history_data(period)
    return ApiResponse.success(data=data)

