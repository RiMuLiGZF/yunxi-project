"""
系统启动快速检查Agent (Startup Quick Check Agent)

归属：云汐系统启动时的快速健康巡检
功能：系统启动时自动运行，快速检查各模块状态

检查项：
1. 数据库连接状态
2. 八大模块（M1-M8）健康检查（调用 /m8/health 接口）
3. Ollama大模型服务状态
4. 算力调度平台状态
5. 磁盘空间/内存等基础资源
6. 配置文件完整性
"""

import time
import uuid
import asyncio
import os
import sys
import shutil
from pathlib import Path
from typing import Dict, Any, Optional, List
from dataclasses import dataclass, field
from datetime import datetime


# 项目根目录
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))


@dataclass
class CheckItemResult:
    """单个检查项结果"""
    name: str
    status: str = "unknown"  # passed/warning/failed/unknown
    message: str = ""
    details: Dict[str, Any] = field(default_factory=dict)
    duration_ms: int = 0


@dataclass
class StartupCheckResult:
    """启动检查整体结果"""
    check_id: str = ""
    overall_status: str = "unknown"  # healthy/degraded/unhealthy
    total_checks: int = 0
    passed_checks: int = 0
    failed_checks: int = 0
    duration_ms: int = 0
    checks: Dict[str, CheckItemResult] = field(default_factory=dict)
    error_summary: str = ""
    triggered_by: str = "system"
    created_at: float = 0.0

    def __post_init__(self):
        if not self.check_id:
            self.check_id = str(uuid.uuid4())
        if not self.created_at:
            self.created_at = time.time()

    def to_dict(self) -> Dict[str, Any]:
        checks_dict = {}
        for key, item in self.checks.items():
            checks_dict[key] = {
                "name": item.name,
                "status": item.status,
                "message": item.message,
                "details": item.details,
                "duration_ms": item.duration_ms,
            }
        return {
            "check_id": self.check_id,
            "overall_status": self.overall_status,
            "total_checks": self.total_checks,
            "passed_checks": self.passed_checks,
            "failed_checks": self.failed_checks,
            "duration_ms": self.duration_ms,
            "checks": checks_dict,
            "error_summary": self.error_summary,
            "triggered_by": self.triggered_by,
            "created_at": self.created_at,
        }


class StartupCheckAgent:
    """
    系统启动快速检查Agent - 单例模式

    负责在系统启动时执行快速健康巡检，
    检查数据库、各模块、Ollama、算力调度、资源、配置等状态。
    """

    _instance = None
    _instance_lock = None  # lazy init

    def __new__(cls):
        if cls._instance is None:
            import threading
            cls._instance_lock = threading.Lock()
            with cls._instance_lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return
        self._initialized = True

        # 最近一次检查结果缓存
        self._last_result: Optional[StartupCheckResult] = None

        # 检查历史（保留最近10条）
        self._history: List[StartupCheckResult] = []

        # 八大模块配置
        self._module_keys = ["m1", "m2", "m3", "m4", "m5", "m6", "m7", "m8"]

    async def run_check(self, triggered_by: str = "system") -> StartupCheckResult:
        """
        执行完整的启动快速检查

        Args:
            triggered_by: 触发方式 (system/manual)

        Returns:
            StartupCheckResult: 检查结果
        """
        overall_start = time.time()
        result = StartupCheckResult(triggered_by=triggered_by)

        # 执行各项检查
        checks = {}

        # 1. 数据库连接状态
        checks["database"] = await self._check_database()

        # 2. 八大模块健康检查
        checks["modules"] = await self._check_modules()

        # 3. Ollama大模型服务状态
        checks["ollama"] = await self._check_ollama()

        # 4. 算力调度平台状态
        checks["compute_platform"] = await self._check_compute_platform()

        # 5. 磁盘空间/内存等基础资源
        checks["resources"] = await self._check_resources()

        # 6. 配置文件完整性
        checks["config"] = await self._check_config()

        # 统计结果
        result.checks = checks
        result.total_checks = len(checks)
        result.passed_checks = sum(
            1 for c in checks.values() if c.status == "passed"
        )
        result.failed_checks = sum(
            1 for c in checks.values() if c.status == "failed"
        )

        # 计算总体状态
        warning_count = sum(
            1 for c in checks.values() if c.status == "warning"
        )
        if result.failed_checks == 0 and warning_count == 0:
            result.overall_status = "healthy"
        elif result.failed_checks == 0 and warning_count > 0:
            result.overall_status = "degraded"
        else:
            result.overall_status = "unhealthy"

        # 错误摘要
        failed_items = [
            c.name for c in checks.values() if c.status == "failed"
        ]
        if failed_items:
            result.error_summary = f"以下检查项失败: {', '.join(failed_items)}"

        result.duration_ms = int((time.time() - overall_start) * 1000)

        # 保存到数据库
        self._save_result_to_db(result)

        # 缓存结果
        self._last_result = result
        self._history.append(result)
        if len(self._history) > 10:
            self._history.pop(0)

        return result

    def get_last_result(self) -> Optional[StartupCheckResult]:
        """获取最近一次检查结果"""
        if self._last_result:
            return self._last_result

        # 从数据库获取最近一条
        try:
            from ..models import SessionLocal, StartupCheckRecord
            db = SessionLocal()
            record = (
                db.query(StartupCheckRecord)
                .order_by(StartupCheckRecord.id.desc())
                .first()
            )
            db.close()

            if record:
                result = StartupCheckResult(
                    check_id=record.check_id,
                    overall_status=record.overall_status,
                    total_checks=record.total_checks,
                    passed_checks=record.passed_checks,
                    failed_checks=record.failed_checks,
                    duration_ms=record.duration_ms,
                    error_summary=record.error_summary or "",
                    triggered_by=record.triggered_by,
                    created_at=record.created_at.timestamp() if record.created_at else 0,
                )
                # 重建 checks
                check_results = record.check_results or {}
                for key, val in check_results.items():
                    result.checks[key] = CheckItemResult(
                        name=val.get("name", key),
                        status=val.get("status", "unknown"),
                        message=val.get("message", ""),
                        details=val.get("details", {}),
                        duration_ms=val.get("duration_ms", 0),
                    )
                self._last_result = result
                return result
        except Exception:
            pass

        return None

    async def _check_database(self) -> CheckItemResult:
        """检查数据库连接状态"""
        start = time.time()
        item = CheckItemResult(name="数据库连接")

        try:
            from ..models import SessionLocal, engine
            from sqlalchemy import text

            db = SessionLocal()
            # 执行简单查询测试连接
            db.execute(text("SELECT 1"))
            db.close()

            item.status = "passed"
            item.message = "数据库连接正常"
            item.details = {
                "database_type": "sqlite",
                "url": str(engine.url),
            }
        except Exception as e:
            item.status = "failed"
            item.message = f"数据库连接失败: {str(e)}"
            item.details = {"error": str(e)}

        item.duration_ms = int((time.time() - start) * 1000)
        return item

    async def _check_modules(self) -> CheckItemResult:
        """检查八大模块健康状态"""
        start = time.time()
        item = CheckItemResult(name="八大模块健康检查")

        module_statuses = {}
        running_count = 0

        try:
            from shared.config import get_config
            config = get_config()
        except Exception:
            config = None

        for mod_key in self._module_keys:
            mod_start = time.time()
            is_running = False
            mod_details = {}

            try:
                port = None
                if config:
                    port = config.get_module_port(mod_key)

                if port:
                    # 使用 TCP 连接测试
                    try:
                        reader, writer = await asyncio.wait_for(
                            asyncio.open_connection("127.0.0.1", port),
                            timeout=1.0
                        )
                        writer.close()
                        await writer.wait_closed()
                        is_running = True
                        mod_details["port"] = port
                    except Exception:
                        is_running = False
                        mod_details["port"] = port
                        mod_details["error"] = "connection_refused"

                # 尝试调用 /m8/health 接口（如果模块支持）
                if is_running and mod_key != "m8":
                    try:
                        import httpx
                        async with httpx.AsyncClient(timeout=2.0) as client:
                            resp = await client.get(
                                f"http://127.0.0.1:{port}/m8/health",
                                headers={"x-m8-token": os.environ.get("M8_ADMIN_TOKEN", "")},
                            )
                            if resp.status_code == 200:
                                data = resp.json()
                                mod_details["health_api"] = True
                                if data.get("data"):
                                    mod_details["version"] = data["data"].get("version", "")
                            else:
                                mod_details["health_api"] = False
                                mod_details["health_status"] = resp.status_code
                    except Exception as e:
                        mod_details["health_api"] = False
                        mod_details["health_error"] = str(e)[:100]

            except Exception as e:
                mod_details["error"] = str(e)[:100]

            if is_running:
                running_count += 1

            mod_details["status"] = "running" if is_running else "stopped"
            mod_details["duration_ms"] = int((time.time() - mod_start) * 1000)
            module_statuses[mod_key] = mod_details

        # 判断状态
        total = len(self._module_keys)
        if running_count == total:
            item.status = "passed"
            item.message = f"全部 {total} 个模块运行正常"
        elif running_count >= 5:
            item.status = "warning"
            item.message = f"{running_count}/{total} 个模块运行中"
        else:
            item.status = "failed"
            item.message = f"仅 {running_count}/{total} 个模块运行"

        item.details = {
            "total_modules": total,
            "running_count": running_count,
            "modules": module_statuses,
        }
        item.duration_ms = int((time.time() - start) * 1000)
        return item

    async def _check_ollama(self) -> CheckItemResult:
        """检查Ollama大模型服务状态"""
        start = time.time()
        item = CheckItemResult(name="Ollama大模型服务")

        try:
            # 先测试端口连通性
            reader, writer = await asyncio.wait_for(
                asyncio.open_connection("127.0.0.1", 11434),
                timeout=2.0
            )
            writer.close()
            await writer.wait_closed()

            # 尝试获取模型列表
            model_count = 0
            try:
                import httpx
                async with httpx.AsyncClient(timeout=3.0) as client:
                    resp = await client.get("http://127.0.0.1:11434/api/tags")
                    if resp.status_code == 200:
                        data = resp.json()
                        models = data.get("models", [])
                        model_count = len(models)
                        item.details["models"] = [
                            m.get("name", "") for m in models[:10]
                        ]
            except Exception:
                pass

            item.status = "passed"
            item.message = f"Ollama服务运行中，已加载 {model_count} 个模型"
            item.details["port"] = 11434
            item.details["model_count"] = model_count

        except Exception as e:
            item.status = "warning"
            item.message = f"Ollama服务未启动: {str(e)[:50]}"
            item.details["error"] = str(e)[:100]

        item.duration_ms = int((time.time() - start) * 1000)
        return item

    async def _check_compute_platform(self) -> CheckItemResult:
        """检查算力调度平台状态"""
        start = time.time()
        item = CheckItemResult(name="算力调度平台")

        try:
            from ..compute_router import get_compute_router

            router = get_compute_router()

            # 检查是否已初始化
            if not hasattr(router, '_initialized') or not router._initialized:
                # 尝试初始化
                from ..models import SessionLocal
                router.initialize(db_session_factory=SessionLocal)

            # 获取基本统计
            source_count = len(router._sources) if hasattr(router, '_sources') else 0
            model_count = len(router._model_bindings) if hasattr(router, '_model_bindings') else 0
            is_offline = router._is_offline if hasattr(router, '_is_offline') else False

            if source_count > 0:
                item.status = "passed"
                item.message = f"算力调度平台正常运行，{source_count} 个算力源，{model_count} 个模型绑定"
            else:
                item.status = "warning"
                item.message = "算力调度平台已启动，但尚未配置算力源"

            item.details = {
                "source_count": source_count,
                "model_count": model_count,
                "is_offline": is_offline,
                "circuit_breaker_count": len(router._circuit_breakers) if hasattr(router, '_circuit_breakers') else 0,
            }

        except Exception as e:
            item.status = "failed"
            item.message = f"算力调度平台初始化失败: {str(e)[:80]}"
            item.details = {"error": str(e)[:200]}

        item.duration_ms = int((time.time() - start) * 1000)
        return item

    async def _check_resources(self) -> CheckItemResult:
        """检查磁盘空间/内存等基础资源"""
        start = time.time()
        item = CheckItemResult(name="基础资源（磁盘/内存）")

        details = {}

        try:
            # 磁盘空间检查
            disk_usage = shutil.disk_usage(str(Path(__file__).parent.parent))
            total_gb = round(disk_usage.total / (1024**3), 2)
            used_gb = round(disk_usage.used / (1024**3), 2)
            free_gb = round(disk_usage.free / (1024**3), 2)
            usage_percent = round((disk_usage.used / disk_usage.total) * 100, 1) if disk_usage.total > 0 else 0

            details["disk"] = {
                "total_gb": total_gb,
                "used_gb": used_gb,
                "free_gb": free_gb,
                "usage_percent": usage_percent,
            }

            # 内存检查（Windows）
            try:
                import ctypes
                kernel32 = ctypes.windll.kernel32

                class MEMORYSTATUSEX(ctypes.Structure):
                    _fields_ = [
                        ("dwLength", ctypes.c_ulong),
                        ("dwMemoryLoad", ctypes.c_ulong),
                        ("ullTotalPhys", ctypes.c_ulonglong),
                        ("ullAvailPhys", ctypes.c_ulonglong),
                        ("ullTotalPageFile", ctypes.c_ulonglong),
                        ("ullAvailPageFile", ctypes.c_ulonglong),
                        ("ullTotalVirtual", ctypes.c_ulonglong),
                        ("ullAvailVirtual", ctypes.c_ulonglong),
                        ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
                    ]

                mem_status = MEMORYSTATUSEX()
                mem_status.dwLength = ctypes.sizeof(MEMORYSTATUSEX)
                kernel32.GlobalMemoryStatusEx(ctypes.byref(mem_status))

                total_mem_gb = round(mem_status.ullTotalPhys / (1024**3), 2)
                avail_mem_gb = round(mem_status.ullAvailPhys / (1024**3), 2)
                mem_load = mem_status.dwMemoryLoad

                details["memory"] = {
                    "total_gb": total_mem_gb,
                    "available_gb": avail_mem_gb,
                    "usage_percent": mem_load,
                }

            except Exception:
                # 非Windows或获取失败，跳过
                pass

            # 判断状态
            issues = []
            if usage_percent > 90:
                issues.append(f"磁盘空间不足（{usage_percent}% 已用）")
            if details.get("memory", {}).get("usage_percent", 0) > 90:
                issues.append(f"内存不足（{details['memory']['usage_percent']}% 已用）")

            if not issues:
                item.status = "passed"
                item.message = "基础资源充足"
            elif len(issues) == 1:
                item.status = "warning"
                item.message = issues[0]
            else:
                item.status = "warning"
                item.message = f"存在 {len(issues)} 个资源警告"

            item.details = details

        except Exception as e:
            item.status = "warning"
            item.message = f"资源检查失败: {str(e)[:50]}"
            item.details = {"error": str(e)[:100]}

        item.duration_ms = int((time.time() - start) * 1000)
        return item

    async def _check_config(self) -> CheckItemResult:
        """检查配置文件完整性"""
        start = time.time()
        item = CheckItemResult(name="配置文件完整性")

        details = {}
        missing_files = []
        found_files = []

        # 检查关键配置文件
        config_paths = [
            ("yunxi_env", project_root / "config" / "yunxi.env"),
            ("compute_master_key", Path(__file__).parent.parent / "data" / "compute_master.key"),
            ("main_config", project_root / "config"),
        ]

        for name, path in config_paths:
            if path.exists():
                found_files.append(name)
                details[name] = {
                    "path": str(path),
                    "exists": True,
                    "size": path.stat().st_size if path.is_file() else None,
                }
            else:
                missing_files.append(name)
                details[name] = {
                    "path": str(path),
                    "exists": False,
                }

        # 检查settings配置是否完整
        try:
            from ..config import settings
            required_settings = [
                ("app_name", bool(settings.app_name)),
                ("version", bool(settings.version)),
                ("jwt_secret", bool(settings.jwt_secret)),
                ("database_url", bool(settings.database_url)),
            ]
            missing_settings = [name for name, ok in required_settings if not ok]

            details["settings"] = {
                "total": len(required_settings),
                "valid": len(required_settings) - len(missing_settings),
                "missing": missing_settings,
            }

            if missing_settings:
                missing_files.extend(f"setting:{s}" for s in missing_settings)
        except Exception as e:
            details["settings_error"] = str(e)[:100]

        item.details = details

        if not missing_files:
            item.status = "passed"
            item.message = "配置文件完整"
        elif len(missing_files) <= 1:
            item.status = "warning"
            item.message = f"部分配置缺失: {', '.join(missing_files)}"
        else:
            item.status = "failed"
            item.message = f"多个配置缺失: {', '.join(missing_files)}"

        item.duration_ms = int((time.time() - start) * 1000)
        return item

    def _save_result_to_db(self, result: StartupCheckResult):
        """保存检查结果到数据库"""
        try:
            from ..models import SessionLocal, StartupCheckRecord

            db = SessionLocal()

            # 构建 checks 的 JSON 格式
            checks_json = {}
            for key, item in result.checks.items():
                checks_json[key] = {
                    "name": item.name,
                    "status": item.status,
                    "message": item.message,
                    "details": item.details,
                    "duration_ms": item.duration_ms,
                }

            record = StartupCheckRecord(
                check_id=result.check_id,
                overall_status=result.overall_status,
                total_checks=result.total_checks,
                passed_checks=result.passed_checks,
                failed_checks=result.failed_checks,
                duration_ms=result.duration_ms,
                check_results=checks_json,
                error_summary=result.error_summary,
                triggered_by=result.triggered_by,
            )

            db.add(record)
            db.commit()
            db.close()
        except Exception as e:
            # 数据库写入失败不影响检查结果
            print(f"[StartupCheckAgent] Failed to save result to DB: {e}")


def get_startup_check_agent() -> StartupCheckAgent:
    """获取启动检查Agent单例"""
    return StartupCheckAgent()
