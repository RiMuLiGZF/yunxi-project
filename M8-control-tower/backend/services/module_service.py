"""
M8 控制塔 - 模块服务 (ModuleService)

封装模块管理相关的业务逻辑，供 modules.py router 调用。
Router 只负责：参数校验 → 调用 service → 返回响应

职责：
1. 模块注册/发现
2. 模块状态查询与健康检查
3. 模块启动/停止/重启操作
4. 模块配置管理
5. 模块代理转发（封装 ModuleClient）

注意：
- 模块通信优先使用 shared.business.module_client.ModuleRegistry
- 模块注册表是全局单例，本服务作为业务逻辑封装层
- 健康检查结果带缓存，避免频繁检测
"""

from __future__ import annotations

import sys
import time
import asyncio
import threading
import logging
from pathlib import Path
from typing import Optional, List, Dict, Any, Tuple

# 将项目根目录加入 path，以便导入 shared 模块
_project_root = Path(__file__).parent.parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

from ..errors import M8ErrorCode, M8Exception
from shared.core.observability import get_logger

logger = get_logger("m8.module_service")


# ===========================================================================
# 缓存配置
# ===========================================================================

STATUS_CACHE_TTL = 5.0       # 模块状态缓存 TTL（秒）
HEALTH_CACHE_TTL = 10.0      # 健康检查结果缓存 TTL（秒）
PORT_CHECK_TIMEOUT = 0.8     # TCP 端口检测超时（秒）


# ===========================================================================
# ModuleService - 模块服务主类
# ===========================================================================

class ModuleService:
    """模块服务

    封装模块管理相关的业务逻辑。
    底层依赖 shared.business.module_client.ModuleRegistry。
    """

    def __init__(self):
        self._registry = None
        self._cache = {}
        self._cache_lock = threading.Lock()
        self._init_registry()

    def _init_registry(self) -> None:
        """初始化模块注册表"""
        try:
            from shared.business.module_client import get_module_registry
            self._registry = get_module_registry()
            logger.info("模块注册表初始化成功")
        except ImportError as e:
            logger.warning(f"无法导入模块注册表: {e}")
            self._registry = None

    @property
    def registry(self):
        """获取模块注册表"""
        if self._registry is None:
            self._init_registry()
        return self._registry

    # -----------------------------------------------------------------------
    # 缓存管理
    # -----------------------------------------------------------------------

    def _get_cache(self, key: str) -> Optional[Any]:
        """获取缓存值"""
        with self._cache_lock:
            entry = self._cache.get(key)
            if entry is None:
                return None
            value, expire_at = entry
            if time.time() > expire_at:
                del self._cache[key]
                return None
            return value

    def _set_cache(self, key: str, value: Any, ttl: float) -> None:
        """设置缓存值"""
        with self._cache_lock:
            self._cache[key] = (value, time.time() + ttl)

    def _invalidate_cache(self, key: str = "") -> None:
        """清除缓存

        Args:
            key: 要清除的 key，为空则清除所有
        """
        with self._cache_lock:
            if key:
                self._cache.pop(key, None)
            else:
                self._cache.clear()

    # -----------------------------------------------------------------------
    # 模块列表/查询
    # -----------------------------------------------------------------------

    def list_modules(self, category: Optional[str] = None,
                     status_filter: Optional[str] = None) -> List[Dict[str, Any]]:
        """获取所有模块列表

        Args:
            category: 按分类过滤
            status_filter: 按状态过滤

        Returns:
            模块信息列表
        """
        if not self.registry:
            return []

        modules = self.registry.get_all_modules()
        result = []

        for mod in modules:
            info = self._module_to_dict(mod)

            if category and info.get("category") != category:
                continue
            if status_filter and info.get("status") != status_filter:
                continue

            result.append(info)

        return result

    def get_module(self, module_key: str) -> Optional[Dict[str, Any]]:
        """获取单个模块信息

        Args:
            module_key: 模块标识

        Returns:
            模块信息 dict，不存在返回 None
        """
        if not self.registry:
            return None

        try:
            mod = self.registry.get_module(module_key)
            if mod is None:
                return None
            return self._module_to_dict(mod)
        except Exception:
            return None

    def get_module_summary(self) -> Dict[str, Any]:
        """获取模块状态总览

        Returns:
            状态统计摘要
        """
        cache_key = "module_summary"
        cached = self._get_cache(cache_key)
        if cached is not None:
            return cached

        modules = self.list_modules()
        summary = {
            "total": len(modules),
            "running": 0,
            "stopped": 0,
            "starting": 0,
            "stopping": 0,
            "error": 0,
            "unknown": 0,
            "healthy": 0,
            "degraded": 0,
            "unhealthy": 0,
            "modules": [],
        }

        for mod in modules:
            status = mod.get("status", "unknown")
            health = mod.get("health", "unknown")

            if status in summary:
                summary[status] += 1
            else:
                summary["unknown"] += 1

            if health == "healthy":
                summary["healthy"] += 1
            elif health == "degraded":
                summary["degraded"] += 1
            elif health == "unhealthy":
                summary["unhealthy"] += 1

        summary["modules"] = modules

        self._set_cache(cache_key, summary, STATUS_CACHE_TTL)
        return summary

    # -----------------------------------------------------------------------
    # 健康检查
    # -----------------------------------------------------------------------

    async def check_health(self, module_key: Optional[str] = None,
                           deep: bool = False) -> Dict[str, Any]:
        """检查模块健康状态

        Args:
            module_key: 指定模块，为空则检查所有
            deep: 是否深度检查

        Returns:
            健康检查结果
        """
        if not self.registry:
            return {
                "healthy": False,
                "message": "模块注册表不可用",
                "results": {},
            }

        try:
            await self.registry.check_all_health()
        except Exception as e:
            logger.warning(f"健康检查异常: {e}")

        if module_key:
            mod = self.get_module(module_key)
            if not mod:
                raise M8Exception(
                    code=M8ErrorCode.MODULE_NOT_FOUND,
                    message=f"模块 {module_key} 不存在",
                )
            return {
                "module_key": module_key,
                "health": mod.get("health", "unknown"),
                "status": mod.get("status", "unknown"),
                "details": mod,
            }

        # 全量检查
        summary = self.get_module_summary()
        return {
            "total": summary["total"],
            "healthy": summary["healthy"],
            "degraded": summary["degraded"],
            "unhealthy": summary["unhealthy"],
            "modules": summary["modules"],
        }

    async def check_module_port(self, module_key: str,
                                timeout: float = PORT_CHECK_TIMEOUT) -> bool:
        """快速检查模块端口是否开放（轻量健康检查）

        Args:
            module_key: 模块标识
            timeout: 超时时间（秒）

        Returns:
            端口是否可达
        """
        mod = self.get_module(module_key)
        if not mod or not mod.get("port"):
            return False

        port = mod["port"]
        try:
            reader, writer = await asyncio.wait_for(
                asyncio.open_connection("127.0.0.1", port),
                timeout=timeout,
            )
            writer.close()
            await writer.wait_closed()
            return True
        except Exception:
            return False

    async def check_all_ports(self) -> Dict[str, Dict[str, Any]]:
        """批量检查所有模块的端口状态

        Returns:
            {module_key: {running, port, latency_ms}}
        """
        cache_key = "module_ports"
        cached = self._get_cache(cache_key)
        if cached is not None:
            return cached

        modules = self.list_modules()
        results: Dict[str, Dict[str, Any]] = {}

        async def check_one(mod):
            key = mod["key"]
            port = mod.get("port")
            if not port:
                results[key] = {"running": False, "port": None, "latency_ms": 0}
                return

            start = time.time()
            is_running = await self.check_module_port(key)
            latency_ms = (time.time() - start) * 1000

            results[key] = {
                "running": is_running,
                "port": port,
                "latency_ms": round(latency_ms, 2),
            }

        tasks = [check_one(mod) for mod in modules]
        await asyncio.gather(*tasks, return_exceptions=True)

        self._set_cache(cache_key, results, STATUS_CACHE_TTL)
        return results

    # -----------------------------------------------------------------------
    # 模块操作
    # -----------------------------------------------------------------------

    async def start_module(self, module_key: str, force: bool = False,
                           timeout: int = 30) -> Dict[str, Any]:
        """启动模块

        Args:
            module_key: 模块标识
            force: 是否强制执行
            timeout: 超时时间（秒）

        Returns:
            操作结果
        """
        if not self.registry:
            raise M8Exception(
                code=M8ErrorCode.MODULE_OPERATION_FAILED,
                message="模块注册表不可用",
            )

        mod = self.get_module(module_key)
        if not mod:
            raise M8Exception(
                code=M8ErrorCode.MODULE_NOT_FOUND,
                message=f"模块 {module_key} 不存在",
            )

        prev_status = mod.get("status", "unknown")

        try:
            # 尝试通过 registry 启动
            if hasattr(self.registry, "start_module"):
                result = await self.registry.start_module(module_key)
                self._invalidate_cache()
                return {
                    "module_key": module_key,
                    "action": "start",
                    "success": True,
                    "message": f"模块 {module_key} 启动成功",
                    "previous_status": prev_status,
                    "current_status": "running",
                }

            # 回退：通过 HTTP 调用启动接口
            client = self.registry.get_client(module_key)
            result = await client.post("/api/admin/start")
            self._invalidate_cache()
            return {
                "module_key": module_key,
                "action": "start",
                "success": True,
                "message": f"模块 {module_key} 启动命令已发送",
                "previous_status": prev_status,
                "current_status": "starting",
            }

        except Exception as e:
            logger.error(f"启动模块 {module_key} 失败: {e}")
            return {
                "module_key": module_key,
                "action": "start",
                "success": False,
                "message": f"启动失败: {e}",
                "previous_status": prev_status,
                "current_status": prev_status,
                "error": str(e),
            }

    async def stop_module(self, module_key: str, force: bool = False,
                          timeout: int = 30) -> Dict[str, Any]:
        """停止模块

        Args:
            module_key: 模块标识
            force: 是否强制停止
            timeout: 超时时间（秒）

        Returns:
            操作结果
        """
        if not self.registry:
            raise M8Exception(
                code=M8ErrorCode.MODULE_OPERATION_FAILED,
                message="模块注册表不可用",
            )

        mod = self.get_module(module_key)
        if not mod:
            raise M8Exception(
                code=M8ErrorCode.MODULE_NOT_FOUND,
                message=f"模块 {module_key} 不存在",
            )

        prev_status = mod.get("status", "unknown")

        try:
            if hasattr(self.registry, "stop_module"):
                result = await self.registry.stop_module(module_key)
                self._invalidate_cache()
                return {
                    "module_key": module_key,
                    "action": "stop",
                    "success": True,
                    "message": f"模块 {module_key} 停止成功",
                    "previous_status": prev_status,
                    "current_status": "stopped",
                }

            client = self.registry.get_client(module_key)
            result = await client.post("/api/admin/stop")
            self._invalidate_cache()
            return {
                "module_key": module_key,
                "action": "stop",
                "success": True,
                "message": f"模块 {module_key} 停止命令已发送",
                "previous_status": prev_status,
                "current_status": "stopping",
            }

        except Exception as e:
            logger.error(f"停止模块 {module_key} 失败: {e}")
            return {
                "module_key": module_key,
                "action": "stop",
                "success": False,
                "message": f"停止失败: {e}",
                "previous_status": prev_status,
                "current_status": prev_status,
                "error": str(e),
            }

    async def restart_module(self, module_key: str, force: bool = False,
                             timeout: int = 60) -> Dict[str, Any]:
        """重启模块

        Args:
            module_key: 模块标识
            force: 是否强制重启
            timeout: 超时时间（秒）

        Returns:
            操作结果
        """
        stop_result = await self.stop_module(module_key, force=force, timeout=timeout // 2)
        if not stop_result["success"]:
            return stop_result

        # 等待一小段时间
        await asyncio.sleep(1)

        start_result = await self.start_module(module_key, force=force, timeout=timeout // 2)
        return start_result

    async def batch_operation(self, module_keys: List[str], action: str,
                              force: bool = False) -> Dict[str, Any]:
        """批量操作模块

        Args:
            module_keys: 模块标识列表
            action: 操作类型 (start/stop/restart)
            force: 是否强制执行

        Returns:
            批量操作结果
        """
        results = []
        succeeded = 0
        failed = 0

        for key in module_keys:
            try:
                if action == "start":
                    result = await self.start_module(key, force=force)
                elif action == "stop":
                    result = await self.stop_module(key, force=force)
                elif action == "restart":
                    result = await self.restart_module(key, force=force)
                else:
                    result = {
                        "module_key": key,
                        "action": action,
                        "success": False,
                        "message": f"不支持的操作: {action}",
                    }

                if result.get("success"):
                    succeeded += 1
                else:
                    failed += 1
                results.append(result)

            except Exception as e:
                failed += 1
                results.append({
                    "module_key": key,
                    "action": action,
                    "success": False,
                    "message": str(e),
                })

        return {
            "total": len(module_keys),
            "succeeded": succeeded,
            "failed": failed,
            "results": results,
        }

    # -----------------------------------------------------------------------
    # 模块代理转发
    # -----------------------------------------------------------------------

    async def proxy_request(self, module_key: str, path: str,
                            method: str = "GET",
                            params: Optional[Dict] = None,
                            body: Optional[Dict] = None,
                            headers: Optional[Dict] = None,
                            timeout: Optional[float] = None) -> Dict[str, Any]:
        """代理请求到目标模块

        Args:
            module_key: 目标模块标识
            path: 目标路径
            method: HTTP 方法
            params: 查询参数
            body: 请求体
            headers: 请求头
            timeout: 超时时间

        Returns:
            代理结果 {proxied, status_code, data, latency_ms, error}
        """
        if not self.registry:
            return {
                "proxied": False,
                "status_code": 503,
                "data": None,
                "latency_ms": 0,
                "error": "模块注册表不可用",
            }

        start = time.time()

        try:
            client = self.registry.get_client(module_key)

            method_upper = method.upper()
            if method_upper == "GET":
                result = await client.get(path, params=params)
            elif method_upper == "POST":
                result = await client.post(path, params=params, json_data=body)
            elif method_upper == "PUT":
                result = await client.put(path, params=params, json_data=body)
            elif method_upper == "DELETE":
                result = await client.delete(path, params=params)
            else:
                raise ValueError(f"不支持的 HTTP 方法: {method}")

            latency_ms = (time.time() - start) * 1000
            return {
                "proxied": True,
                "status_code": 200,
                "data": result,
                "latency_ms": round(latency_ms, 2),
                "error": None,
            }

        except Exception as e:
            latency_ms = (time.time() - start) * 1000
            return {
                "proxied": False,
                "status_code": 502,
                "data": None,
                "latency_ms": round(latency_ms, 2),
                "error": str(e),
            }

    # -----------------------------------------------------------------------
    # 模块配置
    # -----------------------------------------------------------------------

    def get_module_config(self, module_key: str) -> Dict[str, Any]:
        """获取模块配置

        Args:
            module_key: 模块标识

        Returns:
            配置信息
        """
        mod = self.get_module(module_key)
        if not mod:
            raise M8Exception(
                code=M8ErrorCode.MODULE_NOT_FOUND,
                message=f"模块 {module_key} 不存在",
            )

        return {
            "module_key": module_key,
            "config": mod.get("config", {}),
            "updated_at": mod.get("updated_at"),
        }

    def update_module_config(self, module_key: str, config: Dict[str, Any]) -> Dict[str, Any]:
        """更新模块配置

        Args:
            module_key: 模块标识
            config: 配置项

        Returns:
            更新结果
        """
        if not self.registry:
            raise M8Exception(
                code=M8ErrorCode.MODULE_OPERATION_FAILED,
                message="模块注册表不可用",
            )

        try:
            if hasattr(self.registry, "update_module_config"):
                self.registry.update_module_config(module_key, config)
            self._invalidate_cache()
            return {
                "module_key": module_key,
                "success": True,
                "message": "配置更新成功",
            }
        except Exception as e:
            logger.error(f"更新模块 {module_key} 配置失败: {e}")
            raise M8Exception(
                code=M8ErrorCode.MODULE_OPERATION_FAILED,
                message=f"配置更新失败: {e}",
            )

    # -----------------------------------------------------------------------
    # 工具方法
    # -----------------------------------------------------------------------

    def _module_to_dict(self, mod: Any) -> Dict[str, Any]:
        """将模块对象转为 dict

        Args:
            mod: 模块对象（ModuleInfo 或类似）

        Returns:
            标准化的模块信息 dict
        """
        if hasattr(mod, "__dict__"):
            info = {k: v for k, v in vars(mod).items() if not k.startswith("_")}
        elif isinstance(mod, dict):
            info = dict(mod)
        else:
            info = {
                "key": getattr(mod, "key", ""),
                "name": getattr(mod, "name", ""),
                "status": getattr(mod, "status", "unknown"),
                "port": getattr(mod, "port", None),
                "base_url": getattr(mod, "base_url", None),
                "version": getattr(mod, "version", None),
            }

        # 确保关键字段存在
        info.setdefault("key", "")
        info.setdefault("name", info.get("key", ""))
        info.setdefault("category", "business")
        info.setdefault("status", "unknown")
        info.setdefault("health", "unknown")
        info.setdefault("enabled", True)
        info.setdefault("priority", 100)

        return info


# 全局 ModuleService 单例
_module_service: Optional[ModuleService] = None
_module_service_lock = threading.Lock()


def get_module_service() -> ModuleService:
    """获取 ModuleService 单例"""
    global _module_service
    if _module_service is None:
        with _module_service_lock:
            if _module_service is None:
                _module_service = ModuleService()
    return _module_service
