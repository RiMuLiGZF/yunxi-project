"""
云汐 M12 安全盾 - WAF 中间件

在请求进入业务逻辑之前进行 WAF 检测，拦截恶意请求。
支持：
- 请求进入时检测
- 命中规则时拦截（返回 403）
- 可配置规则开关
- 日志记录
- 低误报模式（仅拦截高危）
- 白名单路径跳过
"""

import time
import logging
import json
from typing import Optional, List, Set
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.types import ASGIApp

logger = logging.getLogger(__name__)


class WAFMiddleware(BaseHTTPMiddleware):
    """
    WAF 防护中间件

    在请求处理前进行安全检测，拦截包含攻击特征的请求。

    配置选项：
    - enabled: 是否启用 WAF
    - low_confidence_mode: 低误报模式（仅拦截 high/critical）
    - whitelist_paths: 白名单路径（跳过 WAF 检测）
    - whitelist_ips: 白名单 IP（跳过 WAF 检测）
    - block_action: 拦截动作（block/challenge/log）
    """

    def __init__(
        self,
        app: ASGIApp,
        enabled: bool = True,
        low_confidence_mode: bool = False,
        whitelist_paths: Optional[List[str]] = None,
        whitelist_ips: Optional[List[str]] = None,
        block_action: str = "block",
    ):
        super().__init__(app)
        self.enabled = enabled
        self.low_confidence_mode = low_confidence_mode
        self.whitelist_paths: Set[str] = set(whitelist_paths or [])
        self.whitelist_ips: Set[str] = set(whitelist_ips or [])
        self.block_action = block_action

        # 统计
        self._total_requests = 0
        self._blocked_requests = 0
        self._total_detection_time_ns = 0

        # 延迟加载 WAF 引擎
        self._waf_core = None

    def _get_waf(self):
        """延迟获取 WAF 核心引擎"""
        if self._waf_core is None:
            try:
                from backend.core.waf import get_waf_core
                self._waf_core = get_waf_core()
                if self.low_confidence_mode:
                    self._waf_core.set_low_confidence_mode(True)
            except ImportError:
                try:
                    from core.waf import get_waf_core
                    self._waf_core = get_waf_core()
                except ImportError:
                    logger.warning("WAF 核心引擎不可用，中间件将跳过检测")
                    self._waf_core = None
        return self._waf_core

    async def dispatch(self, request: Request, call_next):
        """处理请求

        Args:
            request: HTTP 请求
            call_next: 下一个处理函数

        Returns:
            HTTP 响应
        """
        start_time = time.perf_counter_ns()

        # WAF 未启用，直接放行
        if not self.enabled:
            return await call_next(request)

        # 白名单路径检查
        path = request.url.path
        if self._is_whitelisted_path(path):
            return await call_next(request)

        # 白名单 IP 检查
        client_ip = self._get_client_ip(request)
        if client_ip in self.whitelist_ips:
            return await call_next(request)

        # 获取 WAF 引擎
        waf = self._get_waf()
        if waf is None:
            return await call_next(request)

        # 收集请求数据用于检测
        method = request.method
        query_string = request.url.query or ""

        # 请求头
        headers = {}
        for key, value in request.headers.items():
            headers[key] = value

        # 获取请求体（仅对非 GET 请求）
        body = ""
        if method in ("POST", "PUT", "PATCH", "DELETE"):
            try:
                # 读取请求体（需要注意流式请求）
                body_bytes = await request.body()
                if body_bytes:
                    try:
                        body = body_bytes.decode("utf-8", errors="replace")
                    except Exception:
                        body = str(body_bytes[:10000])
            except Exception:
                pass

        # 执行 WAF 检测
        result = waf.check_request(
            method=method,
            path=path,
            query=query_string,
            body=body,
            headers=headers,
            client_ip=client_ip,
            user_agent=headers.get("user-agent", ""),
        )

        detection_time_ns = time.perf_counter_ns() - start_time
        self._total_requests += 1
        self._total_detection_time_ns += detection_time_ns

        # 命中规则且动作为 block 时拦截
        if not result["passed"] and result["action"] == "block" and self.block_action == "block":
            self._blocked_requests += 1

            # 记录拦截日志
            logger.warning(
                "WAF 拦截请求: ip=%s method=%s path=%s rule=%s type=%s severity=%s target=%s",
                client_ip, method, path,
                result["rule_name"], result["rule_type"],
                result["severity"], result["match_target"],
            )

            # 构造 403 响应
            response_data = {
                "code": 403,
                "message": "请求被安全防护系统拦截",
                "data": {
                    "blocked": True,
                    "rule_name": result["rule_name"],
                    "rule_type": result["rule_type"],
                    "severity": result["severity"],
                    "match_target": result["match_target"],
                    "detection_time_ms": result["detection_time_ms"],
                    "request_id": self._generate_request_id(),
                },
            }

            return JSONResponse(
                status_code=403,
                content=response_data,
                headers={
                    "X-WAF-Blocked": "true",
                    "X-WAF-Rule": result["rule_name"],
                    "X-WAF-Severity": result["severity"],
                },
            )

        # 通过检测，继续处理
        response = await call_next(request)

        # 添加 WAF 检测头
        response.headers["X-WAF-Checked"] = "true"
        response.headers["X-WAF-Detection-Time"] = f"{result.get('detection_time_ms', 0):.3f}ms"

        return response

    def _is_whitelisted_path(self, path: str) -> bool:
        """检查路径是否在白名单中"""
        if path in self.whitelist_paths:
            return True
        # 支持前缀匹配（以 / 结尾的路径）
        for wp in self.whitelist_paths:
            if wp.endswith("/") and path.startswith(wp):
                return True
        return False

    def _get_client_ip(self, request: Request) -> str:
        """获取客户端真实 IP"""
        # 优先从 X-Forwarded-For 获取
        xff = request.headers.get("x-forwarded-for")
        if xff:
            # 取第一个 IP（最原始的客户端 IP）
            return xff.split(",")[0].strip()

        # 其次从 X-Real-IP 获取
        xri = request.headers.get("x-real-ip")
        if xri:
            return xri.strip()

        # 最后使用连接 IP
        client = request.client
        if client:
            return client.host or ""

        return ""

    def _generate_request_id(self) -> str:
        """生成请求 ID"""
        import uuid
        return uuid.uuid4().hex[:16]

    def get_stats(self) -> dict:
        """获取中间件统计"""
        avg_time_ns = 0
        if self._total_requests > 0:
            avg_time_ns = self._total_detection_time_ns / self._total_requests

        return {
            "enabled": self.enabled,
            "low_confidence_mode": self.low_confidence_mode,
            "total_requests": self._total_requests,
            "blocked_requests": self._blocked_requests,
            "block_rate": (
                self._blocked_requests / self._total_requests
                if self._total_requests > 0
                else 0
            ),
            "avg_detection_time_ms": avg_time_ns / 1_000_000.0,
            "whitelist_paths_count": len(self.whitelist_paths),
            "whitelist_ips_count": len(self.whitelist_ips),
            "block_action": self.block_action,
        }

    def add_whitelist_path(self, path: str) -> None:
        """添加白名单路径"""
        self.whitelist_paths.add(path)

    def remove_whitelist_path(self, path: str) -> None:
        """移除白名单路径"""
        self.whitelist_paths.discard(path)

    def add_whitelist_ip(self, ip: str) -> None:
        """添加白名单 IP"""
        self.whitelist_ips.add(ip)

    def remove_whitelist_ip(self, ip: str) -> None:
        """移除白名单 IP"""
        self.whitelist_ips.discard(ip)

    def set_enabled(self, enabled: bool) -> None:
        """设置是否启用"""
        self.enabled = enabled

    def set_low_confidence_mode(self, enabled: bool) -> None:
        """设置低误报模式"""
        self.low_confidence_mode = enabled
        waf = self._get_waf()
        if waf:
            waf.set_low_confidence_mode(enabled)
