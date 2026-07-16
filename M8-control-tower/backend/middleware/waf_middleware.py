"""
云汐 M8 管理台 - WAF 中间件
对接 M12 安全盾的 WAF 检测服务，为 M8 网关提供 Web 应用防火墙防护。

功能：
1. 每个请求到达时，提取关键信息发送给 M12 检测
2. 支持两种模式：
   - 检测模式（monitor）：只检测不拦截，记录日志
   - 拦截模式（block）：检测到攻击时返回 403
3. 可配置哪些路径需要 WAF 检测

性能优化：
- 异步检测，不阻塞主请求（检测模式下）
- 拦截模式下同步检测
- M12 不可用时自动降级（放行 + 记录告警）

配置项（环境变量）：
- M8_WAF_ENABLED：是否启用 WAF（默认 False）
- M8_WAF_MODE：monitor / block（默认 monitor）
- M12_WAF_URL：M12 WAF 检测接口地址
- M12_WAF_API_KEY：调用 M12 的 API Key
- M8_WAF_TIMEOUT：检测超时时间（默认 100ms）
"""

import os
import time
import logging
import asyncio
from typing import Optional, List, Set
from urllib.parse import urlparse

from fastapi import Request, status
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.types import ASGIApp

import httpx


logger = logging.getLogger(__name__)


# ===========================================================================
# 配置
# ===========================================================================

def _get_env_bool(name: str, default: bool = False) -> bool:
    """从环境变量读取布尔值"""
    val = os.environ.get(name, "")
    if val.lower() in ("true", "1", "yes", "on"):
        return True
    if val.lower() in ("false", "0", "no", "off"):
        return False
    return default


def _get_env_int(name: str, default: int) -> int:
    """从环境变量读取整数值"""
    try:
        return int(os.environ.get(name, default))
    except (ValueError, TypeError):
        return default


# WAF 配置
WAF_ENABLED = _get_env_bool("M8_WAF_ENABLED", False)
WAF_MODE = os.environ.get("M8_WAF_MODE", "monitor").lower()  # monitor / block
M12_WAF_URL = os.environ.get("M12_WAF_URL", "http://127.0.0.1:8012/api/m12/waf/gateway-check")
M12_WAF_API_KEY = os.environ.get("M12_WAF_API_KEY", "")
WAF_TIMEOUT_MS = _get_env_int("M8_WAF_TIMEOUT", 100)  # 默认 100ms

# 验证 WAF_MODE
if WAF_MODE not in ("monitor", "block"):
    logger.warning(f"无效的 M8_WAF_MODE: {WAF_MODE}，使用默认值 monitor")
    WAF_MODE = "monitor"


# ===========================================================================
# 路径匹配配置
# ===========================================================================

# 默认排除的路径（不进行 WAF 检测）
DEFAULT_EXCLUDE_PATHS: Set[str] = {
    "/health",
    "/m8/health",
    "/m8/metrics",
    "/m8/config",
    "/api/system/check",
    "/api/modules/status",
    "/docs",
    "/openapi.json",
    "/redoc",
    "/favicon.ico",
}

# 默认需要检测的路径前缀（留空表示所有路径都检测，除非排除）
DEFAULT_INCLUDE_PREFIXES: List[str] = []  # 空列表 = 全部检测


# ===========================================================================
# WAF 中间件
# ===========================================================================

class WafMiddleware(BaseHTTPMiddleware):
    """
    WAF 中间件

    对接 M12 安全盾的 WAF 检测服务，为 M8 网关提供 Web 应用防火墙防护。

    工作模式：
    - monitor：只检测不拦截，异步发送，不影响主请求性能
    - block：同步检测，发现攻击立即返回 403

    降级策略：
    - M12 不可用时自动降级，放行请求并记录告警
    - 超时也视为降级，放行请求
    """

    def __init__(
        self,
        app: ASGIApp,
        enabled: bool = None,
        mode: str = None,
        m12_url: str = None,
        api_key: str = None,
        timeout_ms: int = None,
        exclude_paths: Set[str] = None,
        include_prefixes: List[str] = None,
    ):
        """初始化 WAF 中间件

        Args:
            app: ASGI 应用
            enabled: 是否启用
            mode: 工作模式（monitor/block）
            m12_url: M12 WAF 检测接口地址
            api_key: M12 API Key
            timeout_ms: 超时时间（毫秒）
            exclude_paths: 排除的路径集合
            include_prefixes: 包含的路径前缀列表
        """
        super().__init__(app)
        self.enabled = enabled if enabled is not None else WAF_ENABLED
        self.mode = (mode or WAF_MODE).lower()
        self.m12_url = m12_url or M12_WAF_URL
        self.api_key = api_key or M12_WAF_API_KEY
        self.timeout_seconds = (timeout_ms or WAF_TIMEOUT_MS) / 1000.0
        self.exclude_paths = exclude_paths or DEFAULT_EXCLUDE_PATHS
        self.include_prefixes = include_prefixes or DEFAULT_INCLUDE_PREFIXES

        # HTTP 客户端（异步）
        self._async_client: Optional[httpx.AsyncClient] = None

        # 统计
        self._stats = {
            "total_requests": 0,
            "checked_requests": 0,
            "blocked_requests": 0,
            "degraded_count": 0,  # 降级次数（M12 不可用）
            "timeout_count": 0,
            "total_check_time_ms": 0,
        }

        # 熔断器状态
        self._circuit_open = False
        self._circuit_open_time = 0.0
        self._circuit_reset_seconds = 30  # 30 秒后尝试恢复
        self._failure_threshold = 10  # 连续 10 次失败打开熔断器

        if self.enabled:
            logger.info(
                f"[WAF] 中间件已启用 - 模式: {self.mode}, "
                f"M12: {self.m12_url}, 超时: {self.timeout_seconds*1000:.0f}ms"
            )
        else:
            logger.info("[WAF] 中间件未启用")

    async def dispatch(self, request: Request, call_next):
        """处理请求

        Args:
            request: 请求对象
            call_next: 下一个处理函数

        Returns:
            响应对象
        """
        # 如果未启用，直接放行
        if not self.enabled:
            return await call_next(request)

        path = request.url.path
        self._stats["total_requests"] += 1

        # 检查是否需要检测
        if not self._should_check(path):
            return await call_next(request)

        # 提取请求信息
        try:
            request_info = await self._extract_request_info(request)
        except Exception:
            # 提取失败，放行
            return await call_next(request)

        self._stats["checked_requests"] += 1

        # 根据模式决定处理方式
        if self.mode == "block":
            # 拦截模式：同步检测
            return await self._check_and_block(request, call_next, request_info)
        else:
            # 检测模式：异步检测，不阻塞
            asyncio.create_task(self._async_check(request_info))
            return await call_next(request)

    def _should_check(self, path: str) -> bool:
        """判断路径是否需要 WAF 检测

        Args:
            path: 请求路径

        Returns:
            是否需要检测
        """
        # 精确匹配排除路径
        if path in self.exclude_paths:
            return False

        # 如果有包含前缀，只检测匹配前缀的路径
        if self.include_prefixes:
            for prefix in self.include_prefixes:
                if path.startswith(prefix):
                    return True
            return False

        # 默认检测所有路径
        return True

    async def _extract_request_info(self, request: Request) -> dict:
        """提取请求信息用于 WAF 检测

        Args:
            request: 请求对象

        Returns:
            请求信息字典
        """
        # 获取客户端 IP
        client_ip = self._get_client_ip(request)

        # 获取请求头
        headers = {}
        for key, value in request.headers.items():
            headers[key] = value

        # 获取用户代理
        user_agent = request.headers.get("user-agent", "")

        # 读取请求体（只在 block 模式或有 body 时读取）
        # 注意：读取 body 会消耗 stream，需要重建 request body
        body = ""
        body_bytes = b""
        if request.method in ("POST", "PUT", "PATCH"):
            try:
                body_bytes = await request.body()
                if body_bytes:
                    # 只取前 10KB 用于检测，避免大 body 影响性能
                    body = body_bytes[:10240].decode("utf-8", errors="ignore")
                
                # 重建请求体流（关键：否则后续路由拿不到body）
                # 通过覆盖 request._receive 来重新播放 body
                await self._rebuild_request_body(request, body_bytes)
            except Exception:
                pass

        return {
            "method": request.method,
            "path": path if (path := request.url.path + ("?" + request.url.query if request.url.query else "")) else request.url.path,
            "headers": headers,
            "body": body,
            "client_ip": client_ip,
            "user_agent": user_agent,
        }

    def _get_client_ip(self, request: Request) -> str:
        """获取客户端真实 IP

        优先从 X-Forwarded-For、X-Real-IP 等代理头获取，
        其次从 request.client 获取。

        Args:
            request: 请求对象

        Returns:
            客户端 IP 地址
        """
        # 常见的代理头
        forwarded_for = request.headers.get("x-forwarded-for")
        if forwarded_for:
            # 取第一个 IP（最原始的客户端）
            return forwarded_for.split(",")[0].strip()

        real_ip = request.headers.get("x-real-ip")
        if real_ip:
            return real_ip.strip()

        client = request.client
        if client:
            return client.host

        return ""

    async def _rebuild_request_body(self, request: Request, body_bytes: bytes):
        """
        重建请求体流
        
        Starlette 的 Request.body() 会消耗底层 receive 流，
        后续路由再次读取时会得到空body。
        通过覆盖 request._receive 来重新播放 body 数据。
        
        Args:
            request: 请求对象
            body_bytes: 原始请求体字节
        """
        if not body_bytes:
            return
        
        # 构建 ASGI message 序列
        # 参考 starlette.requests.Request 的 body 实现
        from starlette.requests import HTTPConnection
        try:
            # 保存原始 receive
            original_receive = request._receive
            
            # 标记 body 是否已被消费
            consumed = False
            
            async def receive():
                nonlocal consumed
                if not consumed:
                    consumed = True
                    return {
                        "type": "http.request",
                        "body": body_bytes,
                        "more_body": False,
                    }
                # 后续消息（如 disconnect）
                return await original_receive()
            
            request._receive = receive
        except Exception:
            # 重建失败不影响主流程，静默降级
            pass

    async def _check_and_block(self, request: Request, call_next, request_info: dict):
        """拦截模式：同步检测，发现攻击返回 403

        Args:
            request: 请求对象
            call_next: 下一个处理函数
            request_info: 请求信息

        Returns:
            响应对象
        """
        # 检查熔断器状态
        if self._circuit_open:
            # 熔断器打开，检查是否到了恢复时间
            now = time.time()
            if now - self._circuit_open_time < self._circuit_reset_seconds:
                # 还在熔断期，降级放行
                self._stats["degraded_count"] += 1
                return await call_next(request)
            else:
                # 尝试半开状态，重新检测一次
                self._circuit_open = False

        try:
            start_time = time.time()
            result = await self._call_m12_waf(request_info)
            elapsed_ms = (time.time() - start_time) * 1000
            self._stats["total_check_time_ms"] += elapsed_ms

            if result and result.get("blocked"):
                self._stats["blocked_requests"] += 1
                logger.warning(
                    f"[WAF] 拦截请求 - IP: {request_info['client_ip']}, "
                    f"路径: {request_info['path'][:100]}, "
                    f"原因: {result.get('reason', 'unknown')}, "
                    f"规则: {result.get('rule_id', 'unknown')}, "
                    f"级别: {result.get('risk_level', 'high')}"
                )
                return JSONResponse(
                    status_code=status.HTTP_403_FORBIDDEN,
                    content={
                        "code": 403,
                        "message": "请求被安全防护系统拦截",
                        "data": {
                            "reason": result.get("reason", ""),
                            "rule_id": result.get("rule_id", ""),
                            "risk_level": result.get("risk_level", ""),
                        },
                    },
                )

            # 检测通过，放行
            return await call_next(request)

        except httpx.TimeoutException:
            # 超时，降级放行
            self._stats["timeout_count"] += 1
            self._stats["degraded_count"] += 1
            logger.warning(f"[WAF] M12 检测超时，降级放行 - 路径: {request_info['path'][:100]}")
            self._check_circuit_breaker()
            return await call_next(request)

        except Exception as e:
            # 其他错误，降级放行
            self._stats["degraded_count"] += 1
            logger.warning(f"[WAF] M12 检测失败，降级放行: {e}")
            self._check_circuit_breaker()
            return await call_next(request)

    async def _async_check(self, request_info: dict) -> None:
        """异步检测（monitor 模式）

        Args:
            request_info: 请求信息
        """
        try:
            result = await self._call_m12_waf(request_info)
            if result and result.get("blocked"):
                logger.info(
                    f"[WAF] 检测到攻击（monitor 模式，未拦截）- "
                    f"IP: {request_info['client_ip']}, "
                    f"路径: {request_info['path'][:100]}, "
                    f"原因: {result.get('reason', 'unknown')}"
                )
        except Exception:
            # 异步检测失败，静默忽略
            pass

    async def _call_m12_waf(self, request_info: dict) -> Optional[dict]:
        """调用 M12 WAF 检测接口

        Args:
            request_info: 请求信息

        Returns:
            检测结果字典，失败返回 None
        """
        # 懒创建 HTTP 客户端
        if self._async_client is None:
            self._async_client = httpx.AsyncClient(
                timeout=httpx.Timeout(self.timeout_seconds),
                limits=httpx.Limits(max_connections=50, max_keepalive_connections=20),
            )

        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["X-API-Key"] = self.api_key

        payload = {
            "method": request_info["method"],
            "path": request_info["path"],
            "headers": request_info.get("headers", {}),
            "body": request_info.get("body", ""),
            "client_ip": request_info["client_ip"],
            "user_agent": request_info.get("user_agent", ""),
        }

        response = await self._async_client.post(
            self.m12_url,
            json=payload,
            headers=headers,
        )

        if response.status_code == 200:
            data = response.json()
            # 适配 M12 的统一响应格式 {code, message, data}
            if isinstance(data, dict) and "data" in data and "blocked" in data["data"]:
                return data["data"]
            if isinstance(data, dict) and "blocked" in data:
                return data

        return None

    def _check_circuit_breaker(self) -> None:
        """检查熔断器状态

        连续失败达到阈值时打开熔断器。
        """
        # 简化实现：连续失败计数可以后续完善
        # 这里每次降级都增加计数，超过阈值打开熔断器
        if self._stats["degraded_count"] >= self._failure_threshold:
            if not self._circuit_open:
                self._circuit_open = True
                self._circuit_open_time = time.time()
                logger.warning(
                    f"[WAF] 熔断器已打开（连续失败 {self._failure_threshold} 次），"
                    f"{self._circuit_reset_seconds}s 后自动恢复"
                )

    def get_stats(self) -> dict:
        """获取中间件统计信息

        Returns:
            统计字典
        """
        avg_time = 0.0
        if self._stats["checked_requests"] > 0:
            avg_time = self._stats["total_check_time_ms"] / self._stats["checked_requests"]

        return {
            "enabled": self.enabled,
            "mode": self.mode,
            "m12_url": self.m12_url,
            "circuit_open": self._circuit_open,
            "total_requests": self._stats["total_requests"],
            "checked_requests": self._stats["checked_requests"],
            "blocked_requests": self._stats["blocked_requests"],
            "degraded_count": self._stats["degraded_count"],
            "timeout_count": self._stats["timeout_count"],
            "avg_check_time_ms": round(avg_time, 2),
        }

    async def close(self) -> None:
        """关闭中间件，释放资源"""
        if self._async_client:
            await self._async_client.aclose()
            self._async_client = None


# ===========================================================================
# 注册函数
# ===========================================================================

def register_waf_middleware(app, **kwargs) -> Optional[WafMiddleware]:
    """注册 WAF 中间件到 FastAPI 应用

    Args:
        app: FastAPI 应用实例
        **kwargs: 传递给 WafMiddleware 的参数

    Returns:
        WafMiddleware 实例，如果未启用返回 None
    """
    enabled = kwargs.pop("enabled", None)
    if enabled is None:
        enabled = WAF_ENABLED

    if not enabled:
        logger.info("[WAF] WAF 中间件未启用（M8_WAF_ENABLED=false）")
        return None

    middleware = WafMiddleware(app, enabled=enabled, **kwargs)
    app.add_middleware(WafMiddleware, enabled=enabled, **kwargs)
    return middleware


# 兼容直接运行测试
if __name__ == "__main__":
    print("M8 WAF 中间件")
    print(f"  启用: {WAF_ENABLED}")
    print(f"  模式: {WAF_MODE}")
    print(f"  M12 地址: {M12_WAF_URL}")
    print(f"  超时: {WAF_TIMEOUT_MS}ms")
    print()
    print("排除路径:")
    for p in sorted(DEFAULT_EXCLUDE_PATHS):
        print(f"  - {p}")
