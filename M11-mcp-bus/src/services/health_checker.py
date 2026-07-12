"""M11 MCP Bus - 健康检查服务.

定期巡检所有注册的 MCP 服务器，自动更新在线状态。
支持手动触发检查和后台自动巡检两种模式。
"""

from __future__ import annotations

import asyncio
import time
from datetime import datetime
from threading import Lock, Thread
from typing import Any, Dict, List, Optional

import httpx

from ..config import get_settings
from ..models_db import McpServer
from .registry import mcp_registry


class McpHealthChecker:
    """MCP 服务器健康检查器.

    定期巡检所有注册的 MCP 服务器，更新在线状态。
    连续失败 3 次标记为 offline，恢复成功后重新标记为 online。
    """

    def __init__(self) -> None:
        """初始化健康检查器."""
        self._settings = get_settings()
        self._running = False
        self._interval = 60  # 默认60秒巡检一次
        self._timeout = 5  # 超时5秒
        self._max_failures = 3  # 连续失败阈值
        self._thread: Optional[Thread] = None
        self._loop: Optional[asyncio.AbstractEventLoop] = None

        # 服务器健康状态缓存（server_id -> health_info）
        self._health_cache: Dict[int, Dict[str, Any]] = {}
        self._lock = Lock()

    # --------------------------------------------------------
    # 生命周期
    # --------------------------------------------------------

    def start(self) -> None:
        """启动后台巡检线程.

        在独立线程中运行 asyncio 事件循环，定期执行健康检查。
        如果启动失败（如 httpx 不可用），则降级为手动模式，不影响主服务。
        """
        if self._running:
            return

        try:
            self._running = True
            self._thread = Thread(target=self._run_loop, daemon=True, name="mcp-health-checker")
            self._thread.start()
            print("[M11] 健康检查巡检线程已启动")
        except Exception as e:
            self._running = False
            print(f"[M11] 健康检查巡检线程启动失败，降级为手动模式: {e}")

    def stop(self) -> None:
        """停止巡检."""
        self._running = False
        if self._loop and self._loop.is_running():
            # 向事件循环发送停止信号
            self._loop.call_soon_threadsafe(self._loop.stop)
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=5)
        print("[M11] 健康检查巡检线程已停止")

    def _run_loop(self) -> None:
        """后台线程入口：运行 asyncio 事件循环."""
        try:
            self._loop = asyncio.new_event_loop()
            asyncio.set_event_loop(self._loop)
            self._loop.run_until_complete(self._check_loop())
        except Exception as e:
            print(f"[M11] 健康检查巡检线程异常: {e}")
        finally:
            if self._loop:
                self._loop.close()
                self._loop = None
            self._running = False

    async def _check_loop(self) -> None:
        """主巡检循环."""
        while self._running:
            try:
                await self.check_all()
            except Exception as e:
                print(f"[M11] 健康检查巡检异常: {e}")

            # 等待下一轮检查，分段等待以便快速响应停止信号
            wait_seconds = self._interval
            while self._running and wait_seconds > 0:
                await asyncio.sleep(min(1, wait_seconds))
                wait_seconds -= 1

    # --------------------------------------------------------
    # 健康检查
    # --------------------------------------------------------

    async def check_server(self, server_id: int) -> Dict[str, Any]:
        """检查单个服务器健康状态.

        Args:
            server_id: 服务器 ID

        Returns:
            健康状态字典：{status, latency_ms, last_check, error?, consecutive_failures}
        """
        server = mcp_registry.get_server(server_id)
        if not server:
            return {
                "server_id": server_id,
                "status": "unknown",
                "latency_ms": 0,
                "last_check": datetime.utcnow().isoformat(),
                "error": "服务器不存在",
                "consecutive_failures": 0,
            }

        # 确定检查目标 URL
        check_url = self._get_check_url(server)
        if not check_url:
            result = {
                "server_id": server_id,
                "server_name": server.name,
                "status": "unknown",
                "latency_ms": 0,
                "last_check": datetime.utcnow().isoformat(),
                "error": "无可检查的端点地址",
                "consecutive_failures": 0,
            }
            self._update_cache(server_id, result)
            return result

        # 执行 HTTP 检查
        start_time = time.time()
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                if server.health_check_url:
                    # 配置了专门的健康检查 URL，使用 GET
                    response = await client.get(check_url)
                else:
                    # 使用 endpoint，发送 MCP JSON-RPC 探测请求
                    payload = {
                        "jsonrpc": "2.0",
                        "id": "health_check",
                        "method": "tools/list",
                        "params": {},
                    }
                    headers = {"Content-Type": "application/json"}
                    if server.api_key:
                        headers["Authorization"] = f"Bearer {server.api_key}"
                    response = await client.post(check_url, json=payload, headers=headers)

                response.raise_for_status()
                latency_ms = int((time.time() - start_time) * 1000)

                result = {
                    "server_id": server_id,
                    "server_name": server.name,
                    "status": "online",
                    "latency_ms": latency_ms,
                    "last_check": datetime.utcnow().isoformat(),
                    "consecutive_failures": 0,
                }

                # 更新服务器状态为 online（如果之前是 offline 且检查成功）
                if server.status != "online":
                    mcp_registry.heartbeat(server_id, "online")
                else:
                    # 更新心跳时间
                    mcp_registry.heartbeat(server_id, "online")

        except Exception as e:
            latency_ms = int((time.time() - start_time) * 1000)

            # 获取当前连续失败次数
            with self._lock:
                prev_failures = self._health_cache.get(server_id, {}).get("consecutive_failures", 0)
            consecutive_failures = prev_failures + 1

            status = "degraded" if consecutive_failures < self._max_failures else "offline"

            result = {
                "server_id": server_id,
                "server_name": server.name,
                "status": status,
                "latency_ms": latency_ms,
                "last_check": datetime.utcnow().isoformat(),
                "error": str(e),
                "consecutive_failures": consecutive_failures,
            }

            # 连续失败达到阈值，标记为 offline
            if consecutive_failures >= self._max_failures and server.status == "online":
                try:
                    db = mcp_registry._settings  # 不直接操作，通过 registry 的方式
                    # 使用 registry 的心跳超时机制会自动处理，这里直接更新状态
                    from ..db import get_session
                    from ..models_db import McpServer as McpServerModel
                    session = get_session()
                    try:
                        srv = session.query(McpServerModel).filter(McpServerModel.id == server_id).first()
                        if srv:
                            srv.status = "offline"
                            session.commit()
                    finally:
                        session.close()
                except Exception:
                    pass

        self._update_cache(server_id, result)
        return result

    async def check_all(self) -> Dict[str, Any]:
        """检查所有服务器.

        Returns:
            统计信息：{total, online, offline, degraded, checking, results}
        """
        servers = mcp_registry.list_servers()
        if not servers:
            return {
                "total": 0,
                "online": 0,
                "offline": 0,
                "degraded": 0,
                "checking": 0,
                "results": [],
            }

        # 并发检查所有服务器
        tasks = [self.check_server(server.id) for server in servers]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        # 处理结果（过滤异常）
        valid_results = []
        for r in results:
            if isinstance(r, dict):
                valid_results.append(r)
            else:
                valid_results.append({
                    "status": "error",
                    "error": str(r),
                })

        online = sum(1 for r in valid_results if r.get("status") == "online")
        offline = sum(1 for r in valid_results if r.get("status") == "offline")
        degraded = sum(1 for r in valid_results if r.get("status") == "degraded")

        return {
            "total": len(valid_results),
            "online": online,
            "offline": offline,
            "degraded": degraded,
            "checking": 0,
            "results": valid_results,
        }

    # --------------------------------------------------------
    # 状态查询
    # --------------------------------------------------------

    def get_server_health(self, server_id: int) -> Optional[Dict[str, Any]]:
        """获取服务器最新健康状态.

        Args:
            server_id: 服务器 ID

        Returns:
            健康状态字典，不存在则返回 None
        """
        with self._lock:
            return self._health_cache.get(server_id)

    def get_all_health(self) -> List[Dict[str, Any]]:
        """获取所有服务器的健康状态.

        Returns:
            健康状态列表
        """
        with self._lock:
            return list(self._health_cache.values())

    def get_health_summary(self) -> Dict[str, Any]:
        """获取健康状态汇总.

        Returns:
            汇总信息字典
        """
        servers = mcp_registry.list_servers()
        total = len(servers)

        with self._lock:
            cached = list(self._health_cache.values())

        online = sum(1 for h in cached if h.get("status") == "online")
        offline = sum(1 for h in cached if h.get("status") == "offline")
        degraded = sum(1 for h in cached if h.get("status") == "degraded")
        unknown = total - online - offline - degraded

        return {
            "total": total,
            "online": online,
            "offline": offline,
            "degraded": degraded,
            "unknown": unknown if unknown > 0 else 0,
            "checking": 1 if self._running else 0,
            "check_interval": self._interval,
        }

    # --------------------------------------------------------
    # 配置
    # --------------------------------------------------------

    def set_interval(self, seconds: int) -> None:
        """设置巡检间隔.

        Args:
            seconds: 间隔秒数
        """
        if seconds > 0:
            self._interval = seconds

    def set_timeout(self, seconds: int) -> None:
        """设置检查超时时间.

        Args:
            seconds: 超时秒数
        """
        if seconds > 0:
            self._timeout = seconds

    @property
    def is_running(self) -> bool:
        """是否正在运行."""
        return self._running

    # --------------------------------------------------------
    # 内部方法
    # --------------------------------------------------------

    def _get_check_url(self, server: McpServer) -> str:
        """获取健康检查 URL.

        优先使用服务器配置的 health_check_url，没有则使用 endpoint。

        Args:
            server: 服务器对象

        Returns:
            检查 URL，空字符串表示无法检查
        """
        if server.health_check_url:
            return server.health_check_url
        if server.transport_type == "http" and server.endpoint:
            return server.endpoint
        return ""

    def _update_cache(self, server_id: int, result: Dict[str, Any]) -> None:
        """更新健康状态缓存.

        Args:
            server_id: 服务器 ID
            result: 健康检查结果
        """
        with self._lock:
            self._health_cache[server_id] = result


# ============================================================
# 单例实例
# ============================================================

mcp_health_checker = McpHealthChecker()
