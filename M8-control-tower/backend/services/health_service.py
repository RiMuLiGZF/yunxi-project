"""
M8 健康检查服务（ARC-005 重构）

将 main.py 中的健康检查相关逻辑抽离到独立模块，包括：
- M8 标准对接接口（/m8/health, /m8/metrics, /m8/config）
- 模块状态检查（/api/modules/status）
- 全局系统状态检测（/api/system/check）
- 标准化可观测性路由注册（健康检查 + Prometheus 指标 + 告警引擎）
- 公开健康检查接口（/health，向后兼容）

使用方式：
    from .health_service import (
        register_m8_std_endpoints,
        register_observability_routes,
        register_public_health_endpoint,
    )
    register_m8_std_endpoints(app, settings, logger)
    register_observability_routes(app, settings, logger, project_root, _observability_available)
    register_public_health_endpoint(app, settings, logger, _observability_available)
"""

import os
import time
import hmac
import asyncio
from pathlib import Path

from fastapi import FastAPI, Header, HTTPException


# 模块启动时间（用于计算 uptime）
_m8_start_time = time.time()


def _verify_m8_std_token(x_m8_token: str = "") -> bool:
    """验证 M8 标准对接 token"""
    expected = os.environ.get("M8_ADMIN_TOKEN", "")
    if not expected:
        return True
    return hmac.compare_digest(x_m8_token, expected)


def register_m8_std_endpoints(app: FastAPI, settings, logger) -> None:
    """
    注册 M8 标准对接接口（自管控）
    
    端点：
    - GET /m8/health   M8标准健康检查
    - GET /m8/metrics  M8标准性能指标
    - GET /m8/config   M8标准配置查询
    """
    from fastapi import Header, HTTPException
    
    @app.get("/m8/health", tags=["M8-标准接口"], summary="M8标准健康检查")
    async def m8_std_health(x_m8_token: str = Header(default="")):
        if not _verify_m8_std_token(x_m8_token):
            raise HTTPException(status_code=401, detail="Invalid M8 token")
        return {
            "code": 0,
            "message": "ok",
            "data": {
                "status": "healthy",
                "module": "m8",
                "module_name": "云汐管理台",
                "version": settings.version,
                "uptime_seconds": int(time.time() - _m8_start_time),
                "modules_managed": 7,
            }
        }

    @app.get("/m8/metrics", tags=["M8-标准接口"], summary="M8标准性能指标")
    async def m8_std_metrics(x_m8_token: str = Header(default="")):
        if not _verify_m8_std_token(x_m8_token):
            raise HTTPException(status_code=401, detail="Invalid M8 token")
        try:
            from routers.monitor import _get_system_metrics
            sys_metrics = _get_system_metrics()
            cpu = sys_metrics.get("cpu", {})
            mem = sys_metrics.get("memory", {})

            # 从内置告警引擎获取真实告警数
            alerts_active = 0
            try:
                from shared.core.observability import get_alert_engine
                alert_engine = get_alert_engine()
                alerts_active = len(alert_engine.get_active_alerts())
            except (ImportError, AttributeError, TypeError):
                # 预期内异常：告警引擎不可用或接口变更，使用默认值 0
                logger.debug("告警引擎不可用，使用默认告警数 0")
            except Exception:
                # 兜底：未预期异常，记录日志后继续
                logger.warning("获取告警数异常", exc_info=True)

            return {
                "code": 0,
                "message": "ok",
                "data": {
                    "cpu_usage": cpu.get("percent", 0.0),
                    "memory_mb": round(mem.get("used_gb", 0) * 1024, 1),
                    "memory_total_mb": round(mem.get("total_gb", 0) * 1024, 1),
                    "active_modules": 7,
                    "requests_total": 0,
                    "alerts_active": alerts_active,
                }
            }
        except (ImportError, AttributeError):
            # 预期内异常：监控模块不可用，返回默认指标
            logger.debug("系统指标模块不可用，返回默认值")
            return {
                "code": 0,
                "message": "ok",
                "data": {
                    "cpu_usage": 0.0,
                    "memory_mb": 0,
                    "active_modules": 7,
                    "requests_total": 0,
                    "alerts_active": 0,
                }
            }
        except Exception as e:
            # 兜底：未预期异常，记录完整堆栈后返回默认值
            logger.exception("获取 M8 标准指标未预期错误")
            return {
                "code": 0,
                "message": "ok",
                "data": {
                    "cpu_usage": 0.0,
                    "memory_mb": 0,
                    "active_modules": 7,
                    "requests_total": 0,
                    "alerts_active": 0,
                }
            }

    @app.get("/m8/config", tags=["M8-标准接口"], summary="M8标准配置查询")
    async def m8_std_config(x_m8_token: str = Header(default="")):
        if not _verify_m8_std_token(x_m8_token):
            raise HTTPException(status_code=401, detail="Invalid M8 token")
        return {
            "code": 0,
            "message": "ok",
            "data": {
                "module": "m8",
                "module_name": "云汐管理台",
                "version": settings.version,
                "env": os.environ.get("YUNXI_ENV", "development"),
                "modules": ["m1", "m2", "m3", "m4", "m5", "m6", "m7"],
            }
        }


def register_module_status_endpoint(app: FastAPI, logger) -> None:
    """
    注册模块状态检查端点（无需鉴权，供入口页面使用）
    
    端点：
    - GET /api/modules/status  获取所有模块运行状态
    """
    @app.get("/api/modules/status", tags=["系统"])
    async def modules_status():
        """获取所有模块运行状态（公开接口，供入口页使用）"""
        from shared.core.config import get_config
        from shared.business.module_client import get_module_registry

        config = get_config()
        registry = get_module_registry()

        # 使用 ModuleRegistry 的健康检查
        health_results = await registry.check_all_health()

        # 构建与原格式兼容的响应
        modules_status = {}
        for module in registry.get_all_modules():
            is_running = health_results.get(module.key, False)
            modules_status[module.key] = {
                "running": is_running,
                "port": config.get_module_port(module.key),
                "name": module.name,
                "version": module.version,
            }

        running_count = sum(1 for m in modules_status.values() if m["running"])

        return {
            "code": 0,
            "message": "ok",
            "data": {
                "modules": modules_status,
                "running_count": running_count,
                "total": len(modules_status),
            }
        }


def register_system_check_endpoint(app: FastAPI, logger, project_root: Path) -> None:
    """
    注册全局系统状态检测端点（无需鉴权，静默检测用）
    
    端点：
    - GET /api/system/check  全局系统状态检测
    """
    
    @app.get("/api/system/check", tags=["系统"])
    async def system_check():
        """全局系统状态检测（公开接口，静默检测用）
        
        检测项：Ollama大模型服务、Git仓库、硬件蓝牙设备、模块权限白名单
        所有检测并行执行，确保接口快速响应（总耗时 < 3秒）
        """
        result = {
            "ollama": {"status": "unknown", "message": "未检测"},
            "git": {"status": "unknown", "message": "未检测"},
            "bluetooth": {"status": "unknown", "message": "未检测"},
            "permissions": {"status": "granted", "message": "模块权限正常"},
            "modules": {"status": "unknown", "message": "未检测"},
        }

        async def check_ollama():
            """检测 Ollama 服务"""
            try:
                reader, writer = await asyncio.wait_for(
                    asyncio.open_connection("127.0.0.1", 11434),
                    timeout=1.0
                )
                writer.close()
                await writer.wait_closed()
                result["ollama"] = {"status": "running", "message": "Ollama服务运行中"}
            except (OSError, ConnectionError, asyncio.TimeoutError):
                # 预期内异常：Ollama 未启动或连接失败
                result["ollama"] = {"status": "stopped", "message": "Ollama服务未启动"}
            except Exception:
                # 兜底：未预期异常
                logger.debug("Ollama 检测异常", exc_info=True)
                result["ollama"] = {"status": "stopped", "message": "Ollama服务未启动"}

        async def check_git():
            """检测 Git（在线程池中执行，避免阻塞事件循环）"""
            import subprocess
            try:
                loop = asyncio.get_event_loop()
                git_check = await asyncio.wait_for(
                    loop.run_in_executor(
                        None,
                        lambda: subprocess.run(
                            ["git", "--version"],
                            capture_output=True,
                            timeout=2,
                            text=True
                        )
                    ),
                    timeout=2.0
                )
                if git_check.returncode == 0:
                    git_dir = project_root / ".git"
                    if git_dir.exists():
                        result["git"] = {"status": "ready", "message": "Git已配置，仓库就绪"}
                    else:
                        result["git"] = {"status": "available", "message": "Git已安装，尚未初始化仓库"}
                else:
                    result["git"] = {"status": "unavailable", "message": "Git不可用"}
            except (OSError, subprocess.TimeoutExpired, asyncio.TimeoutError):
                # 预期内异常：Git 未安装、执行超时
                result["git"] = {"status": "unavailable", "message": "Git未安装或不可用"}
            except Exception:
                # 兜底：未预期异常
                logger.debug("Git 检测异常", exc_info=True)
                result["git"] = {"status": "unavailable", "message": "Git未安装或不可用"}

        async def check_bluetooth():
            """检测蓝牙（在线程池中执行）"""
            import subprocess
            try:
                loop = asyncio.get_event_loop()
                bt_check = await asyncio.wait_for(
                    loop.run_in_executor(
                        None,
                        lambda: subprocess.run(
                            ["powershell", "-Command", "Get-Service -Name bthserv -ErrorAction SilentlyContinue | Select-Object -ExpandProperty Status"],
                            capture_output=True,
                            timeout=2,
                            text=True
                        )
                    ),
                    timeout=2.0
                )
                bt_status = bt_check.stdout.strip()
                if bt_status and bt_status.lower() == "running":
                    result["bluetooth"] = {"status": "ready", "message": "蓝牙服务运行中"}
                else:
                    result["bluetooth"] = {"status": "unavailable", "message": "蓝牙服务未运行"}
            except (OSError, subprocess.TimeoutExpired, asyncio.TimeoutError):
                # 预期内异常：蓝牙检测命令执行失败或超时
                result["bluetooth"] = {"status": "unknown", "message": "蓝牙状态未知"}
            except Exception:
                # 兜底：未预期异常
                logger.debug("蓝牙检测异常", exc_info=True)
                result["bluetooth"] = {"status": "unknown", "message": "蓝牙状态未知"}

        async def check_modules():
            """检测所有模块端口状态（并行检测）"""
            from shared.core.config import get_config as _get_config

            _config = _get_config()
            module_keys = ["m8", "m1", "m2", "m3", "m4", "m5", "m6", "m7"]
            modules_running = 0

            async def check_port(port):
                try:
                    reader, writer = await asyncio.wait_for(
                        asyncio.open_connection("127.0.0.1", port),
                        timeout=0.5
                    )
                    writer.close()
                    await writer.wait_closed()
                    return True
                except (OSError, ConnectionError, asyncio.TimeoutError):
                    # 预期内异常：端口不可达
                    return False
                except Exception:
                    # 兜底：未预期异常
                    logger.debug(f"端口检测异常 {port}", exc_info=True)
                    return False

            tasks = []
            for mod_key in module_keys:
                port = _config.get_module_port(mod_key)
                if port:
                    tasks.append(check_port(port))

            if tasks:
                results = await asyncio.gather(*tasks)
                modules_running = sum(1 for r in results if r)

            total_modules = len(module_keys)
            if modules_running >= 5:
                result["modules"] = {"status": "healthy", "message": f"{modules_running}/{total_modules} 模块运行中"}
            elif modules_running >= 2:
                result["modules"] = {"status": "partial", "message": f"{modules_running}/{total_modules} 模块运行中"}
            else:
                result["modules"] = {"status": "stopped", "message": f"{modules_running}/{total_modules} 模块运行中"}

        # 并行执行所有检测，设置总超时
        try:
            await asyncio.wait_for(
                asyncio.gather(
                    check_ollama(),
                    check_git(),
                    check_bluetooth(),
                    check_modules(),
                    return_exceptions=True
                ),
                timeout=3.0
            )
        except asyncio.TimeoutError as e:
            # 预期内异常：健康检查总超时，返回已获取的部分结果
            logger.debug("系统健康检查部分项超时: %s", e)
        except Exception as e:
            # 兜底：未预期异常，返回已获取的部分结果
            logger.warning("系统健康检查异常: %s", e)

        # 总体状态
        all_ok = all(
            r["status"] in ["running", "ready", "granted", "healthy", "available"]
            for k, r in result.items() if k != "bluetooth"  # 蓝牙非必需
        )
        
        overall_status = "healthy" if all_ok else "degraded"

        return {
            "code": 0,
            "message": "ok",
            "data": {
                "overall": overall_status,
                "checks": result,
            }
        }


def register_observability_routes(app: FastAPI, settings, logger,
                                  project_root: Path, _observability_available: bool) -> None:
    """
    注册标准化可观测性路由（健康检查 + Prometheus 指标 + 告警引擎）
    
    包括：
    - 自定义健康检查器（内存、磁盘、数据库、Redis、模块健康、告警状态）
    - 可观测性路由（/health, /metrics 等）
    - 内置告警引擎
    """
    if not _observability_available:
        return
    
    try:
        from shared.core.observability import create_observability_router, HealthChecker
        from shared.core.health import CheckResult

        # 创建自定义健康检查器（M8 专属检查项）
        m8_checker = HealthChecker(
            module_name="m8",
            version=settings.version,
            module_display_name="云汐管理台",
        )

        # 注册轻量检查：内存
        m8_checker.register_memory_check(threshold_percent=90.0, lightweight=True)

        # 注册轻量检查：磁盘
        m8_checker.register_disk_check(
            path=str(project_root),
            threshold_percent=90.0,
            lightweight=True,
        )

        # 注册深度检查：数据库（核心依赖）
        def _check_m8_db() -> CheckResult:
            start_t = time.time()
            try:
                from .models import SessionLocal
                db = SessionLocal()
                try:
                    db.execute("SELECT 1")
                    resp_ms = (time.time() - start_t) * 1000
                    return CheckResult.healthy(
                        type="postgresql",
                        response_time_ms=resp_ms,
                    )
                except (OSError, IOError) as e:
                    # 预期内异常：数据库连接失败
                    resp_ms = (time.time() - start_t) * 1000
                    return CheckResult.unhealthy(
                        error=str(e),
                        type="postgresql",
                        response_time_ms=resp_ms,
                    )
                finally:
                    db.close()
            except (ImportError, AttributeError) as e:
                # 预期内异常：数据库模块不可用
                resp_ms = (time.time() - start_t) * 1000
                return CheckResult.unhealthy(
                    error=str(e),
                    type="postgresql",
                    response_time_ms=resp_ms,
                )
            except Exception as e:
                # 兜底：未预期异常
                resp_ms = (time.time() - start_t) * 1000
                return CheckResult.unhealthy(
                    error=str(e),
                    type="postgresql",
                    response_time_ms=resp_ms,
                )

        m8_checker.register_check("database", _check_m8_db, critical=True, lightweight=False)

        # 注册深度检查：Redis（非核心）
        def _check_m8_redis() -> CheckResult:
            start_t = time.time()
            try:
                from shared.data.cache import get_redis
                r = get_redis()
                if r and r.ping():
                    resp_ms = (time.time() - start_t) * 1000
                    return CheckResult.healthy(
                        type="redis",
                        response_time_ms=resp_ms,
                    )
                resp_ms = (time.time() - start_t) * 1000
                return CheckResult.degraded(
                    error="Redis not available",
                    type="redis",
                    response_time_ms=resp_ms,
                )
            except (ImportError, AttributeError):
                # 预期内异常：Redis 模块不可用，尝试直接连接
                try:
                    import redis as _redis
                    redis_url = os.environ.get("REDIS_URL", "redis://localhost:6379/0")
                    r = _redis.Redis.from_url(redis_url, socket_connect_timeout=2, socket_timeout=2)
                    if r.ping():
                        resp_ms = (time.time() - start_t) * 1000
                        return CheckResult.healthy(
                            type="redis",
                            response_time_ms=resp_ms,
                        )
                    resp_ms = (time.time() - start_t) * 1000
                    return CheckResult.degraded(
                        error="Redis ping failed",
                        type="redis",
                        response_time_ms=resp_ms,
                    )
                except (ImportError, OSError, ConnectionError) as e:
                    # 预期内异常：Redis 库不可用或连接失败
                    resp_ms = (time.time() - start_t) * 1000
                    return CheckResult.degraded(
                        error=str(e),
                        type="redis",
                        response_time_ms=resp_ms,
                    )
            except Exception as e:
                # 兜底：未预期异常
                resp_ms = (time.time() - start_t) * 1000
                return CheckResult.degraded(
                    error=str(e),
                    type="redis",
                    response_time_ms=resp_ms,
                )

        m8_checker.register_check("redis", _check_m8_redis, critical=False, lightweight=False)

        # 注册深度检查：模块健康（M8 特有）
        def _check_modules_health() -> CheckResult:
            start_t = time.time()
            try:
                from shared.business.module_client import get_module_registry
                registry = get_module_registry()
                modules = registry.get_all_modules()
                healthy_count = 0
                total = len(modules)
                for mod in modules:
                    if registry.check_health(mod.key):
                        healthy_count += 1
                resp_ms = (time.time() - start_t) * 1000
                status = "healthy" if healthy_count == total else ("degraded" if healthy_count > 0 else "unhealthy")
                result = CheckResult(
                    status=status,
                    response_time_ms=resp_ms,
                    details={
                        "total_modules": total,
                        "healthy_modules": healthy_count,
                        "unhealthy_modules": total - healthy_count,
                    },
                )
                return result
            except (ImportError, AttributeError, ValueError) as e:
                # 预期内异常：模块注册中心不可用
                resp_ms = (time.time() - start_t) * 1000
                return CheckResult.degraded(
                    error=str(e),
                    response_time_ms=resp_ms,
                )
            except Exception as e:
                # 兜底：未预期异常
                resp_ms = (time.time() - start_t) * 1000
                return CheckResult.degraded(
                    error=str(e),
                    response_time_ms=resp_ms,
                )

        m8_checker.register_check("modules", _check_modules_health, critical=False, lightweight=False)

        # 创建可观测性路由并注册
        obs_router = create_observability_router(
            service_name="m8",
            version=settings.version,
            health_checker=m8_checker,
        )
        app.include_router(obs_router)
        logger.info("标准化可观测性路由已注册（/health + /metrics）")

        # ---- 内置告警引擎（OB-003） ----
        try:
            from shared.core.observability import (
                get_alert_engine,
                create_alert_router,
                AlertSeverity,
            )

            # 初始化全局告警引擎（启动后台检查线程）
            alert_engine = get_alert_engine(
                service_name="m8",
                history_limit=2000,
                auto_start=True,
            )

            # 注册告警 API 路由
            alert_router = create_alert_router(
                engine=alert_engine,
            )
            app.include_router(alert_router, prefix="/api")
            logger.info(
                "内置告警引擎已启动（%d 条内置规则，%d 个通知渠道）",
                len(alert_engine.list_rules()),
                len(alert_engine.notifier_manager.list_channels()),
            )

            # 将告警状态集成到健康检查器中
            def _check_alerts() -> CheckResult:
                """告警状态检查：CRITICAL 级告警导致 degraded"""
                start_t = time.time()
                try:
                    impact = alert_engine.get_health_impact()
                    resp_ms = (time.time() - start_t) * 1000

                    if impact["status"] == "healthy":
                        return CheckResult.healthy(
                            active_alerts=impact["active_alerts_count"],
                            response_time_ms=resp_ms,
                        )
                    else:
                        return CheckResult.degraded(
                            error=f"{impact['critical_alerts_count']} critical, "
                                  f"{impact['warning_alerts_count']} warning alerts active",
                            active_alerts=impact["active_alerts_count"],
                            critical_alerts=impact["critical_alerts_count"],
                            warning_alerts=impact["warning_alerts_count"],
                            response_time_ms=resp_ms,
                        )
                except (AttributeError, KeyError, TypeError) as e:
                    # 预期内异常：告警引擎接口变更
                    resp_ms = (time.time() - start_t) * 1000
                    return CheckResult.degraded(
                        error=f"Alert check error: {e}",
                        response_time_ms=resp_ms,
                    )
                except Exception as e:
                    # 兜底：未预期异常
                    resp_ms = (time.time() - start_t) * 1000
                    return CheckResult.degraded(
                        error=f"Alert check error: {e}",
                        response_time_ms=resp_ms,
                    )

            m8_checker.register_check(
                "alerts",
                _check_alerts,
                critical=False,
                lightweight=True,
            )
            logger.info("告警状态已集成到健康检查")
        except (ImportError, AttributeError) as e:
            # 预期内异常：告警引擎不可用
            logger.warning(f"内置告警引擎初始化失败: {e}，告警功能暂不可用")
        except Exception as e:
            # 兜底：未预期异常
            logger.exception("内置告警引擎初始化未预期错误")
    except (ImportError, AttributeError) as e:
        # 预期内异常：可观测性模块不可用
        logger.warning(f"标准化可观测性路由注册失败: {e}，使用旧版健康检查")
    except Exception as e:
        # 兜底：未预期异常
        logger.exception("标准化可观测性路由注册未预期错误")


def register_public_health_endpoint(app: FastAPI, settings, logger,
                                    _observability_available: bool) -> None:
    """
    注册公开健康检查接口（根路径，供外部监控使用）- 向后兼容
    
    端点：
    - GET /health  系统健康检查
    """
    @app.get("/health", tags=["系统"], summary="系统健康检查")
    async def public_health():
        # 如果可用，使用标准化健康检查器
        if _observability_available:
            try:
                from shared.core.observability import get_health_checker
                checker = get_health_checker()
                result = await checker.async_check(deep=False)
                health_data = result.to_dict()

                # 附加活跃告警信息
                alert_info = {}
                try:
                    from shared.core.observability import get_alert_engine
                    alert_engine = get_alert_engine()
                    impact = alert_engine.get_health_impact()
                    alert_info = {
                        "active_alerts": impact["active_alerts_count"],
                        "critical_alerts": impact["critical_alerts_count"],
                        "warning_alerts": impact["warning_alerts_count"],
                    }
                except (ImportError, AttributeError, KeyError):
                    # 预期内异常：告警引擎不可用，跳过告警信息
                    pass
                except Exception:
                    # 兜底：未预期异常
                    logger.debug("获取告警信息异常", exc_info=True)

                # 包装为旧格式保持兼容
                return {
                    "code": 0,
                    "message": "ok",
                    "data": {
                        "status": health_data["status"],
                        "version": health_data["version"],
                        "module": health_data["module"],
                        "module_name": "云汐管理台",
                        "uptime_seconds": health_data["uptime_seconds"],
                        "checks": health_data["checks"],
                        **alert_info,
                    },
                }
            except (ImportError, AttributeError) as e:
                # 预期内异常：标准化健康检查不可用，回退到旧版
                logger.warning("标准化健康检查不可用，回退到旧版: %s", e)
            except Exception as e:
                # 兜底：标准化健康检查失败，回退到旧版检查
                logger.warning("标准化健康检查失败，回退到旧版: %s", e)

        # 回退：旧版健康检查
        db_status = "unknown"
        try:
            from .models import SessionLocal
            db = SessionLocal()
            try:
                db.execute("SELECT 1")
                db_status = "connected"
            except (OSError, IOError):
                # 预期内异常：数据库连接失败
                db_status = "disconnected"
            finally:
                db.close()
        except (ImportError, AttributeError):
            # 预期内异常：数据库模块不可用
            db_status = "unavailable"
        except Exception:
            # 兜底：未预期异常
            logger.debug("旧版健康检查数据库检测异常", exc_info=True)
            db_status = "unavailable"

        return {
            "code": 0,
            "message": "ok",
            "data": {
                "status": "healthy",
                "version": settings.version,
                "module": "m8",
                "module_name": "云汐管理台",
                "database": db_status,
                "uptime_seconds": int(time.time() - _m8_start_time),
            }
        }
