"""
M0 主理人管控台 - M8 API 客户端

通过 httpx 调用 M8 控制塔的管理接口，
M8 未启动时提供 fallback mock 数据。
"""

from __future__ import annotations

import asyncio
from datetime import datetime
from typing import Any, Dict, List, Optional

import httpx

try:
    import psutil as _psutil
    _HAS_PSUTIL = True
except ImportError:
    _HAS_PSUTIL = False

from ..config import settings
from ..models import (
    AlertItem,
    DashboardSummary,
    ModuleDetail,
    ModuleStatusItem,
    SystemResources,
)

MODULE_PORTS = {
    "m0": 8000, "m1": 8001, "m2": 8002, "m3": 8003,
    "m4": 8004, "m5": 8005, "m6": 8006, "m7": 8007,
    "m8": 8008, "m9": 8009, "m10": 8010, "m11": 8011, "m12": 8012,
}

MODULE_NAMES = {
    "m0": "M0 主理人控制台",
    "m1": "M1 Agent Hub",
    "m2": "M2 技能集群",
    "m3": "M3 边云协同",
    "m4": "M4 场景引擎",
    "m5": "M5 潮汐记忆",
    "m6": "M6 硬件外设",
    "m7": "M7 积木平台",
    "m8": "M8 控制塔",
    "m9": "M9 开发工坊",
    "m10": "M10 系统守护",
    "m11": "M11 MCP 总线",
    "m12": "M12 扩展服务",
}


class M8Client:
    """
    M8 API 客户端

    封装对 M8 控制塔的 HTTP 调用，提供统一的接口。
    所有方法在 M8 不可用时都会返回 fallback mock 数据。
    """

    def __init__(self) -> None:
        """初始化 M8 客户端"""
        self.base_url = settings.m8_base_url.rstrip("/")
        self.timeout = settings.m8.timeout
        self.api_prefix = settings.m8.api_prefix
        self._client: Optional[httpx.AsyncClient] = None

    async def _get_client(self) -> httpx.AsyncClient:
        """
        获取或创建 httpx 异步客户端

        Returns:
            httpx.AsyncClient: 异步 HTTP 客户端
        """
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                base_url=self.base_url,
                timeout=self.timeout,
            )
        return self._client

    async def close(self) -> None:
        """关闭 HTTP 客户端连接"""
        if self._client and not self._client.is_closed:
            await self._client.aclose()
            self._client = None

    async def _request(
        self,
        method: str,
        path: str,
        params: Optional[Dict[str, Any]] = None,
        json_data: Optional[Dict[str, Any]] = None,
    ) -> Optional[Dict[str, Any]]:
        """
        发送 HTTP 请求到 M8

        Args:
            method: HTTP 方法
            path: API 路径（自动添加 api_prefix）
            params: 查询参数
            json_data: JSON 请求体

        Returns:
            Optional[Dict]: 响应 JSON 数据，失败返回 None
        """
        try:
            client = await self._get_client()
            full_path = f"{self.api_prefix}/{path.lstrip('/')}"
            response = await client.request(
                method=method,
                url=full_path,
                params=params,
                json=json_data,
            )
            if response.status_code == 200:
                return response.json()
            return None
        except (httpx.HTTPError, Exception):
            return None

    # ------------------------------------------------------------------
    # 健康检查
    # ------------------------------------------------------------------

    async def check_health(self) -> bool:
        """
        检查 M8 服务是否健康

        Returns:
            bool: M8 是否正常运行
        """
        try:
            client = await self._get_client()
            response = await client.get("/health")
            return response.status_code == 200
        except Exception:
            return False

    # ------------------------------------------------------------------
    # 模块状态收集
    # ------------------------------------------------------------------

    async def _collect_from_modules(self) -> List[ModuleStatusItem]:
        """
        直接轮询各模块的健康接口收集真实状态。
        策略：优先 /health（白名单无需认证），失败回退 /m8/health。
        """
        async def _extract(data: dict) -> dict:
            """统一提取 status / version，兼容多种响应格式"""
            inner = data.get("data", data)
            return {
                "status": inner.get("status", data.get("status", "unknown")),
                "version": inner.get("version", data.get("version")),
            }

        async def _probe(module: str, port: int) -> ModuleStatusItem:
            try:
                async with httpx.AsyncClient(timeout=3.0) as client:
                    # 第一轮：/health（白名单端点，所有模块均有，无需认证）
                    resp = await client.get(f"http://127.0.0.1:{port}/health")
                    if resp.status_code == 200:
                        info = await _extract(resp.json())
                        return ModuleStatusItem(
                            key=module,
                            name=MODULE_NAMES.get(module, module),
                            status=info["status"],
                            port=port,
                            version=info.get("version"),
                            last_heartbeat=datetime.now(),
                        )
                    # 第二轮：/m8/health（需要 token，提供更丰富信息）
                    if resp.status_code == 404:
                        headers = {"X-M8-Token": f"yunxi-{module}-admin-token-2026"}
                        resp2 = await client.get(
                            f"http://127.0.0.1:{port}/m8/health",
                            headers=headers,
                        )
                        if resp2.status_code == 200:
                            info = await _extract(resp2.json())
                            return ModuleStatusItem(
                                key=module,
                                name=MODULE_NAMES.get(module, module),
                                status=info["status"],
                                port=port,
                                version=info.get("version"),
                                last_heartbeat=datetime.now(),
                            )
                    # 服务可达但异常（500/401/403 等）
                    return ModuleStatusItem(
                        key=module,
                        name=MODULE_NAMES.get(module, module),
                        status="error",
                        port=port,
                        version=None,
                        last_heartbeat=None,
                    )
            except Exception:
                pass
            return ModuleStatusItem(
                key=module,
                name=MODULE_NAMES.get(module, module),
                status="stopped",
                port=port,
                version=None,
                last_heartbeat=None,
            )

        tasks = [_probe(m, p) for m, p in MODULE_PORTS.items()]
        results = await asyncio.gather(*tasks)
        return list(results)

    # ------------------------------------------------------------------
    # 模块管理
    # ------------------------------------------------------------------

    async def get_modules(self) -> List[ModuleStatusItem]:
        """
        获取所有模块列表

        Returns:
            List[ModuleStatusItem]: 模块状态列表
        """
        modules = await self._collect_from_modules()
        if any(m.status != "stopped" for m in modules):
            return modules
        # Fallback: 返回 mock 数据
        return self._mock_modules()

    async def get_module_detail(self, module_key: str) -> Optional[ModuleDetail]:
        """
        获取单个模块详情

        Args:
            module_key: 模块标识

        Returns:
            Optional[ModuleDetail]: 模块详情，不存在返回 None
        """
        result = await self._request("GET", f"/modules/{module_key}")
        if result and result.get("code") == 0 and result.get("data"):
            m = result["data"]
            return ModuleDetail(
                key=m.get("key", module_key),
                name=m.get("name", module_key),
                description=m.get("description"),
                status=m.get("status", "unknown"),
                port=m.get("port"),
                version=m.get("version"),
                config=m.get("config", {}),
                endpoints=m.get("endpoints", []),
                last_heartbeat=m.get("last_heartbeat"),
            )
        # Fallback: 从 mock 数据中查找
        modules = self._mock_modules()
        for m in modules:
            if m.key == module_key:
                return ModuleDetail(
                    key=m.key,
                    name=m.name,
                    description=f"{m.name} - 云汐系统模块",
                    status=m.status,
                    port=m.port,
                    version=m.version or "1.0.0",
                    config={"enabled": True, "log_level": "info"},
                    endpoints=["/health", "/api/status"],
                    last_heartbeat=datetime.now(),
                )
        return None

    # ------------------------------------------------------------------
    # 仪表盘数据
    # ------------------------------------------------------------------

    def _collect_system_resources(self) -> SystemResources:
        """使用 psutil 采集真实系统资源，不可用时返回零值"""
        if not _HAS_PSUTIL:
            return SystemResources()
        try:
            cpu = _psutil.cpu_percent(interval=0.5)
            mem = _psutil.virtual_memory()
            disk = _psutil.disk_usage("/")
            return SystemResources(
                cpu_usage=round(cpu, 1),
                memory_usage=round(mem.percent, 1),
                memory_total_gb=round(mem.total / (1024 ** 3), 1),
                memory_used_gb=round(mem.used / (1024 ** 3), 1),
                disk_usage=round(disk.percent, 1),
            )
        except Exception:
            return SystemResources()

    async def get_dashboard_summary(self) -> DashboardSummary:
        """
        获取仪表盘总览数据

        Returns:
            DashboardSummary: 仪表盘汇总数据
        """
        modules = await self._collect_from_modules()
        if all(m.status == "stopped" for m in modules):
            return self._mock_dashboard_summary()

        running = sum(1 for m in modules if m.status not in ("stopped", "error"))
        stopped = sum(1 for m in modules if m.status == "stopped")
        mock = self._mock_dashboard_summary()

        return DashboardSummary(
            module_count=len(modules),
            module_running=running,
            module_stopped=stopped,
            system_resources=self._collect_system_resources(),
            alerts=mock.alerts,
            alert_critical_count=mock.alert_critical_count,
            alert_warning_count=mock.alert_warning_count,
            version=settings.version,
            today_conversations=mock.today_conversations,
            memory_total=mock.memory_total,
            uptime_hours=mock.uptime_hours,
        )

    async def get_alerts(self) -> List[AlertItem]:
        """
        获取告警列表

        Returns:
            List[AlertItem]: 告警列表
        """
        result = await self._request("GET", "/monitor/alerts")
        if result and result.get("code") == 0 and result.get("data"):
            alerts_data = result["data"]
            if isinstance(alerts_data, list):
                return [AlertItem(**a) for a in alerts_data]
        # Fallback
        return self._mock_alerts()

    # ------------------------------------------------------------------
    # Mock 数据（M8 不可用时使用）
    # ------------------------------------------------------------------

    def _mock_modules(self) -> List[ModuleStatusItem]:
        """生成 mock 模块列表"""
        return [
            ModuleStatusItem(
                key="m1", name="M1 Agent 集群", status="running",
                port=8001, version="1.2.0", last_heartbeat=datetime.now(),
            ),
            ModuleStatusItem(
                key="m2", name="M2 技能集群", status="running",
                port=8002, version="1.1.0", last_heartbeat=datetime.now(),
            ),
            ModuleStatusItem(
                key="m3", name="M3 边云协同", status="running",
                port=8003, version="1.0.0", last_heartbeat=datetime.now(),
            ),
            ModuleStatusItem(
                key="m4", name="M4 场景引擎", status="degraded",
                port=8004, version="0.9.5", last_heartbeat=datetime.now(),
            ),
            ModuleStatusItem(
                key="m5", name="M5 潮汐记忆", status="running",
                port=8005, version="1.3.0", last_heartbeat=datetime.now(),
            ),
            ModuleStatusItem(
                key="m6", name="M6 硬件外设", status="stopped",
                port=8006, version="1.0.0", last_heartbeat=None,
            ),
            ModuleStatusItem(
                key="m7", name="M7 积木平台", status="running",
                port=8007, version="1.1.0", last_heartbeat=datetime.now(),
            ),
            ModuleStatusItem(
                key="m8", name="M8 控制塔", status="running",
                port=8000, version="2.0.0", last_heartbeat=datetime.now(),
            ),
            ModuleStatusItem(
                key="m9", name="M9 开发工坊", status="running",
                port=8009, version="0.8.0", last_heartbeat=datetime.now(),
            ),
            ModuleStatusItem(
                key="m10", name="M10 系统守护", status="running",
                port=8010, version="1.0.0", last_heartbeat=datetime.now(),
            ),
            ModuleStatusItem(
                key="m11", name="M11 MCP 总线", status="running",
                port=8011, version="0.5.0", last_heartbeat=datetime.now(),
            ),
        ]

    def _mock_alerts(self) -> List[AlertItem]:
        """生成 mock 告警列表"""
        now = datetime.now()
        return [
            AlertItem(
                id="alert-001", level="critical",
                title="M4 场景引擎响应延迟过高",
                module="m4",
                created_at=now,
                resolved=False,
            ),
            AlertItem(
                id="alert-002", level="warning",
                title="M6 硬件外设服务已停止",
                module="m6",
                created_at=now,
                resolved=False,
            ),
            AlertItem(
                id="alert-003", level="info",
                title="系统版本更新可用",
                module="system",
                created_at=now,
                resolved=False,
            ),
        ]

    def _mock_dashboard_summary(self) -> DashboardSummary:
        """生成 mock 仪表盘汇总数据"""
        modules = self._mock_modules()
        alerts = self._mock_alerts()
        running = sum(1 for m in modules if m.status == "running")
        stopped = sum(1 for m in modules if m.status == "stopped")
        critical = sum(1 for a in alerts if a.level == "critical")
        warning = sum(1 for a in alerts if a.level == "warning")

        return DashboardSummary(
            module_count=len(modules),
            module_running=running,
            module_stopped=stopped,
            system_resources=SystemResources(
                cpu_usage=32.5,
                memory_usage=58.2,
                memory_total_gb=32.0,
                memory_used_gb=18.6,
                disk_usage=45.3,
            ),
            alerts=alerts,
            alert_critical_count=critical,
            alert_warning_count=warning,
            version=settings.version,
            today_conversations=128,
            memory_total=2048,
            uptime_hours=72.5,
        )


# 全局单例
m8_client = M8Client()
