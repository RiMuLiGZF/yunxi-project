"""
云汐系统 - 模块间调用客户端 ModuleClient
所有模块通过 HTTP API 互相调用，统一的客户端封装
"""

import time
import asyncio
from typing import Dict, Any, Optional, List
from enum import Enum

import httpx

from ..config import get_config
from ..core.logger import get_logger

logger = get_logger("yunxi.module")


class ModuleStatus(str, Enum):
    """模块状态枚举"""
    RUNNING = "running"
    STOPPED = "stopped"
    ERROR = "error"
    UNKNOWN = "unknown"


class ModuleKey(str, Enum):
    """模块键枚举，统一管理所有模块的 key"""

    M0 = "m0"  # 主理人管控台
    M1 = "m1"  # 多Agent调度中心
    M2 = "m2"  # 技能集群
    M3 = "m3"  # 端云协同内核
    M4 = "m4"  # 业务场景引擎
    M5 = "m5"  # 潮汐记忆系统
    M6 = "m6"  # 穿戴硬件外设
    M7 = "m7"  # 积木编排平台
    M8 = "m8"  # 管理工作台
    M9 = "m9"  # 编程开发
    M10 = "m10"  # 系统卫士


class ModuleCategory(str, Enum):
    """模块分类枚举"""

    CONTROL = "control"  # 管控类
    CORE = "core"  # 核心能力类
    TOOL = "tool"  # 工具类
    INFRA = "infra"  # 基础设施类


class ModuleInfo:
    """模块信息"""

    def __init__(
        self,
        key: str,
        name: str,
        version: str,
        port: int,
        base_url: str,
        health_endpoint: str = "/health",
        status: ModuleStatus = ModuleStatus.UNKNOWN,
        description: str = "",
        category: str = "core",
    ):
        self.key = key
        self.name = name
        self.version = version
        self.port = port
        self.base_url = base_url
        self.health_endpoint = health_endpoint
        self.status = status
        self.description = description
        self.category = category
        self.last_health_check = None
        self.latency_ms = 0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "key": self.key,
            "name": self.name,
            "version": self.version,
            "port": self.port,
            "base_url": self.base_url,
            "status": self.status.value,
            "description": self.description,
            "health_endpoint": self.health_endpoint,
            "category": self.category,
            "last_health_check": self.last_health_check,
            "latency_ms": self.latency_ms,
        }


class ModuleClient:
    """
    模块调用客户端
    封装了对其他模块的 HTTP 调用，支持重试、超时、鉴权
    """

    def __init__(self, module_key: str):
        """
        Args:
            module_key: 目标模块的 key (如 m1, m2, m5)
        """
        self.module_key = module_key.lower()
        self._config = get_config()
        self.base_url = self._config.get_module_base_url(self.module_key)
        self.token = self._config.get_module_token(self.module_key)
        self.timeout = self._config.request_timeout
        self.max_retry = self._config.max_retry
        self.retry_delay = self._config.retry_delay

        if not self.base_url:
            raise ValueError(f"Unknown module: {module_key}")

        self._client = httpx.AsyncClient(
            base_url=self.base_url.rstrip("/"),
            timeout=self.timeout,
        )

    def _get_headers(self, use_auth: bool = True) -> Dict[str, str]:
        headers = {
            "Content-Type": "application/json",
        }
        if use_auth and self.token:
            headers["X-M8-Token"] = self.token
            headers["Authorization"] = f"Bearer {self.token}"
        return headers

    async def request(
        self,
        method: str,
        path: str,
        params: Optional[Dict] = None,
        json_data: Optional[Dict] = None,
        use_auth: bool = True,
        **kwargs,
    ) -> Dict[str, Any]:
        """
        发送 HTTP 请求，带重试

        Args:
            method: HTTP 方法 (GET, POST, PUT, DELETE)
            path: 请求路径
            params: URL 参数
            json_data: JSON 请求体
            use_auth: 是否使用鉴权
            **kwargs: 其他 httpx 参数

        Returns:
            解析后的 JSON 响应
        """
        last_error = None

        for attempt in range(self.max_retry):
            try:
                start_time = time.time()
                response = await self._client.request(
                    method=method.upper(),
                    url=path,
                    params=params,
                    json=json_data,
                    headers=self._get_headers(use_auth),
                    **kwargs,
                )
                latency = (time.time() - start_time) * 1000

                response.raise_for_status()
                result = response.json()
                logger.debug(
                    f"[{self.module_key}] {method} {path} - {response.status_code} - {latency:.0f}ms"
                )
                return result

            except httpx.HTTPStatusError as e:
                last_error = e
                logger.warning(
                    f"[{self.module_key}] {method} {path} - HTTP {e.response.status_code} "
                    f"(attempt {attempt + 1}/{self.max_retry})"
                )
                # 4xx 错误不重试
                if 400 <= e.response.status_code < 500:
                    raise

            except Exception as e:
                last_error = e
                logger.warning(
                    f"[{self.module_key}] {method} {path} - error: {e} "
                    f"(attempt {attempt + 1}/{self.max_retry})"
                )

            if attempt < self.max_retry - 1:
                await asyncio.sleep(self.retry_delay)

        raise last_error

    async def get(self, path: str, params: Optional[Dict] = None, **kwargs) -> Dict[str, Any]:
        """GET 请求"""
        return await self.request("GET", path, params=params, **kwargs)

    async def post(self, path: str, json_data: Optional[Dict] = None, **kwargs) -> Dict[str, Any]:
        """POST 请求"""
        return await self.request("POST", path, json_data=json_data, **kwargs)

    async def put(self, path: str, json_data: Optional[Dict] = None, **kwargs) -> Dict[str, Any]:
        """PUT 请求"""
        return await self.request("PUT", path, json_data=json_data, **kwargs)

    async def delete(self, path: str, **kwargs) -> Dict[str, Any]:
        """DELETE 请求"""
        return await self.request("DELETE", path, **kwargs)

    async def health_check(self) -> bool:
        """健康检查"""
        try:
            response = await self._client.get("/health", timeout=5)
            return response.status_code == 200
        except Exception:
            return False

    async def close(self):
        """关闭客户端"""
        await self._client.aclose()


class ModuleRegistry:
    """
    模块注册中心
    管理所有模块的信息、状态、健康检查
    M8 管理台的核心组件之一
    """

    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self):
        if hasattr(self, "_initialized") and self._initialized:
            return
        self._config = get_config()
        self._modules: Dict[str, ModuleInfo] = {}
        self._clients: Dict[str, ModuleClient] = {}
        self._register_default_modules()
        self._initialized = True
        logger.info(f"ModuleRegistry initialized with {len(self._modules)} modules")

    def _register_default_modules(self):
        """注册默认的 10 个模块"""
        default_modules = [
            {
                "key": "m0",
                "name": "主理人管控台",
                "version": "v1.0.0",
                "port": self._config.get_module_port("m0"),
                "base_url": self._config.get_module_base_url("m0"),
                "description": "云汐系统主理人专属管控平台，最高权限",
                "category": "control",
            },
            {
                "key": "m1",
                "name": "多Agent调度中心",
                "version": "v11.1",
                "port": self._config.get_module_port("m1"),
                "base_url": self._config.get_module_base_url("m1"),
                "description": "联邦调度系统，8子Agent协同",
                "category": "core",
            },
            {
                "key": "m2",
                "name": "技能集群",
                "version": "v3.10.2",
                "port": self._config.get_module_port("m2"),
                "base_url": self._config.get_module_base_url("m2"),
                "description": "6大类28个技能，BM25语义检索",
                "category": "core",
            },
            {
                "key": "m3",
                "name": "端云协同内核",
                "version": "v2.1.2",
                "port": self._config.get_module_port("m3"),
                "base_url": self._config.get_module_base_url("m3"),
                "description": "端云双向同步、离线缓存、冲突消解",
                "category": "infra",
            },
            {
                "key": "m4",
                "name": "业务场景引擎",
                "version": "v2.9.0",
                "port": self._config.get_module_port("m4"),
                "base_url": self._config.get_module_base_url("m4"),
                "description": "六大模式、场景切换、暖切换过渡",
                "category": "core",
            },
            {
                "key": "m5",
                "name": "潮汐记忆系统",
                "version": "v2.4.0",
                "port": self._config.get_module_port("m5"),
                "base_url": self._config.get_module_base_url("m5"),
                "description": "四层潮汐记忆、AES-256加密、向量检索",
                "category": "core",
            },
            {
                "key": "m6",
                "name": "穿戴硬件外设",
                "version": "v7.0.0",
                "port": self._config.get_module_port("m6"),
                "base_url": self._config.get_module_base_url("m6"),
                "description": "智能手表/戒指/无人机/桌面屏，模拟模式",
                "category": "infra",
            },
            {
                "key": "m7",
                "name": "积木编排平台",
                "version": "v1.1.0",
                "port": self._config.get_module_port("m7"),
                "base_url": self._config.get_module_base_url("m7"),
                "description": "可视化工作流编排、36个积木、代码执行",
                "category": "tool",
            },
            {
                "key": "m8",
                "name": "管理工作台",
                "version": "v1.0.0",
                "port": self._config.get_module_port("m8"),
                "base_url": self._config.get_module_base_url("m8"),
                "description": "部署中心、监控中心、汐舷、开发者模式",
                "category": "control",
            },
            {
                "key": "m9",
                "name": "编程开发",
                "version": "v0.1.0",
                "port": self._config.get_module_port("m9"),
                "base_url": self._config.get_module_base_url("m9"),
                "description": "VSCode管理、代码执行沙箱、项目管理",
                "category": "tool",
            },
            {
                "key": "m10",
                "name": "系统卫士",
                "version": "v1.0.0",
                "port": self._config.get_module_port("m10"),
                "base_url": self._config.get_module_base_url("m10"),
                "description": "系统资源监控、进程管理、阈值防护、审计日志",
                "category": "infra",
            },
        ]

        for m in default_modules:
            info = ModuleInfo(**m)
            self._modules[info.key] = info

    def register_module(self, module_info: ModuleInfo):
        """注册一个模块"""
        self._modules[module_info.key] = module_info
        logger.info(f"Module registered: {module_info.key} ({module_info.name})")

    def unregister_module(self, key: str):
        """注销模块"""
        if key in self._modules:
            del self._modules[key]
            if key in self._clients:
                del self._clients[key]
            logger.info(f"Module unregistered: {key}")

    def get_module(self, key: str) -> Optional[ModuleInfo]:
        """获取模块信息"""
        return self._modules.get(key.lower())

    def get_all_modules(self) -> List[ModuleInfo]:
        """获取所有模块列表"""
        return list(self._modules.values())

    def get_client(self, key: str) -> ModuleClient:
        """获取模块调用客户端"""
        key = key.lower()
        if key not in self._clients:
            if key not in self._modules:
                raise ValueError(f"Unknown module: {key}")
            self._clients[key] = ModuleClient(key)
        return self._clients[key]

    async def check_all_health(self) -> Dict[str, bool]:
        """检查所有模块的健康状态"""
        results = {}
        for key, module in self._modules.items():
            try:
                client = self.get_client(key)
                is_healthy = await client.health_check()
                module.status = (
                    ModuleStatus.RUNNING if is_healthy else ModuleStatus.ERROR
                )
                module.last_health_check = time.time()
                results[key] = is_healthy
            except Exception as e:
                module.status = ModuleStatus.ERROR
                results[key] = False
                logger.error(f"Health check failed for {key}: {e}")
        return results

    def get_status_summary(self) -> Dict[str, Any]:
        """获取状态摘要"""
        total = len(self._modules)
        running = sum(1 for m in self._modules.values() if m.status == ModuleStatus.RUNNING)
        stopped = sum(1 for m in self._modules.values() if m.status == ModuleStatus.STOPPED)
        error = sum(1 for m in self._modules.values() if m.status == ModuleStatus.ERROR)
        unknown = sum(1 for m in self._modules.values() if m.status == ModuleStatus.UNKNOWN)

        return {
            "total": total,
            "running": running,
            "stopped": stopped,
            "error": error,
            "unknown": unknown,
            "modules": [m.to_dict() for m in self._modules.values()],
        }


def get_module_registry() -> ModuleRegistry:
    """获取模块注册中心单例"""
    return ModuleRegistry()
