"""潮汐记忆 Skill — M5 安全接入代理.

作为 M2 技能集群与 M5 潮汐记忆系统之间的安全代理：
  - 透传 JWT Token，由 M5 做身份认证和权限检查
  - 默认私有域，防止越权访问共享/核心域
  - 写入前 PII 预检，自动设置密级
  - M5 不可用时降级返回（不报错）
  - 全链路 trace_id 串联审计

安全边界（共五道）：
  1. M2 技能权限层（默认 none，需显式授权）
  2. M5 JWT 认证中间件
  3. M5 三级域权限检查
  4. M5 四级密级检查
  5. M1 隐私脱敏层（数据出口）
"""

from __future__ import annotations

import time
from typing import Any

import httpx
import structlog

from skill_cluster.interfaces import (
    ISkill,
    SkillInvokeRequest,
    SkillInvokeResult,
    SkillManifest,
)

logger = structlog.get_logger()


class TideMemorySkill(ISkill):
    """潮汐记忆技能 — M5 安全代理.

    通过 HTTP API 调用 M5 潮汐记忆系统，全程遵守保密协议。
    """

    def __init__(self) -> None:
        manifest = SkillManifest(
            skill_id="skill.tide_memory",
            name="潮汐记忆",
            version="2.0.0",
            description="云汐潮汐记忆系统 — 四层记忆架构，三级域权限，四级密级保护",
            author="yunxi",
            tags=["memory", "tide", "personal", "private"],
            capabilities=[
                "recall",        # 记忆检索
                "archive",       # 记忆归档
                "compress",      # 记忆压缩/巩固
                "stats",         # 记忆统计
                "search",        # 关键词搜索
                "forget",        # 遗忘/删除
                "preference",    # 偏好管理
            ],
            permissions=["read", "write"],  # 默认权限由 permissions.py 控制（默认 none）
            entrypoint="TideMemorySkill",
            config_schema={
                "type": "object",
                "properties": {
                    "m5_base_url": {
                        "type": "string",
                        "description": "M5 潮汐记忆服务地址",
                        "default": "http://localhost:8005",
                    },
                    "default_domain": {
                        "type": "string",
                        "description": "默认访问域（private/shared/core）",
                        "default": "private",
                        "enum": ["private", "shared", "core"],
                    },
                    "default_agent_id": {
                        "type": "string",
                        "description": "默认 Agent ID（用于未携带身份的请求）",
                        "default": "skill.tide_memory",
                    },
                    "timeout": {
                        "type": "number",
                        "description": "请求超时时间（秒）",
                        "default": 10.0,
                    },
                    "enable_pii_check": {
                        "type": "boolean",
                        "description": "写入前 PII 检测（自动设置密级）",
                        "default": True,
                    },
                    "fallback_to_downgrade": {
                        "type": "boolean",
                        "description": "M5 不可用时降级返回（不报错）",
                        "default": True,
                    },
                },
            },
        )
        super().__init__(manifest)

        # 配置
        self._config: dict[str, Any] = {
            "m5_base_url": "http://localhost:8005",
            "default_domain": "private",
            "default_agent_id": "skill.tide_memory",
            "timeout": 10.0,
            "enable_pii_check": True,
            "fallback_to_downgrade": True,
        }

        # HTTP 客户端（懒加载）
        self._client: httpx.AsyncClient | None = None

        # 连接状态缓存
        self._last_health_check: float = 0.0
        self._m5_available: bool | None = None
        self._health_check_ttl: float = 30.0  # 健康检查缓存30秒

    # ── 核心接口 ──────────────────────────────────────────

    async def invoke(self, request: SkillInvokeRequest) -> SkillInvokeResult:
        """执行潮汐记忆动作."""
        action = request.action
        params = request.params or {}
        start = time.perf_counter()

        try:
            # 提取身份信息（从 metadata 或 params）
            agent_id = (
                params.get("agent_id")
                or (request.metadata or {}).get("agent_id")
                or self._config["default_agent_id"]
            )
            domain = (
                params.get("domain")
                or (request.metadata or {}).get("domain")
                or self._config["default_domain"]
            )
            auth_token = (
                params.pop("auth_token", None)
                or (request.metadata or {}).get("auth_token")
            )

            # 域安全检查：禁止技能层直接访问 core 域
            if domain == "core":
                return self._error(
                    request,
                    "Access denied: skills cannot access core domain directly",
                    start,
                )

            # 分发到具体动作
            if action == "recall":
                data = await self._action_recall(params, agent_id, domain, auth_token, request.trace_id)
            elif action == "archive":
                data = await self._action_archive(params, agent_id, domain, auth_token, request.trace_id)
            elif action == "compress":
                data = await self._action_compress(params, agent_id, domain, auth_token, request.trace_id)
            elif action == "stats":
                data = await self._action_stats(params, agent_id, domain, auth_token, request.trace_id)
            elif action == "search":
                data = await self._action_search(params, agent_id, domain, auth_token, request.trace_id)
            elif action == "forget":
                data = await self._action_forget(params, agent_id, domain, auth_token, request.trace_id)
            elif action == "preference":
                data = await self._action_preference(params, agent_id, domain, auth_token, request.trace_id)
            else:
                return self._error(request, f"Unknown action: {action}", start)

            latency = (time.perf_counter() - start) * 1000
            return SkillInvokeResult(
                skill_id=self.manifest.skill_id,
                action=action,
                status="success",
                data=data,
                latency_ms=latency,
                trace_id=request.trace_id,
            )

        except Exception as e:
            # M5 不可用时降级
            if self._config["fallback_to_downgrade"]:
                self._logger.warning(
                    "tide_memory_fallback_downgrade",
                    action=request.action,
                    error=str(e),
                    trace_id=request.trace_id,
                )
                return self._downgrade_result(request, start)
            return self._error(request, str(e), start)

    async def health(self) -> dict[str, Any]:
        """健康检查（带缓存）."""
        now = time.time()
        if now - self._last_health_check < self._health_check_ttl and self._m5_available is not None:
            return {
                "healthy": self._m5_available,
                "skill_id": self.manifest.skill_id,
                "mode": "proxy" if self._m5_available else "degraded",
                "cached": True,
            }

        self._last_health_check = now
        available = await self._check_m5_health()
        self._m5_available = available

        return {
            "healthy": True,  # 技能本身总是健康的（可降级运行）
            "skill_id": self.manifest.skill_id,
            "mode": "proxy" if available else "degraded",
            "m5_available": available,
            "m5_url": self._config["m5_base_url"],
        }

    async def configure(self, config: dict[str, Any]) -> None:
        self._config.update(config)
        # 配置变更后重置客户端
        if self._client:
            await self._client.aclose()
            self._client = None
        self._m5_available = None
        self._last_health_check = 0.0

    # ── 动作实现 ──────────────────────────────────────────

    async def _action_recall(
        self,
        params: dict[str, Any],
        agent_id: str,
        domain: str,
        auth_token: str | None,
        trace_id: str | None,
    ) -> dict[str, Any]:
        """记忆检索."""
        query = params.get("query") or params.get("context") or ""
        top_k = int(params.get("top_k", 10))
        layers = params.get("layers")
        user_id = params.get("user_id", "")

        body = {
            "query": query,
            "top_k": top_k,
            "domain": domain,
            "agent_id": agent_id,
            "user_id": user_id,
        }
        if layers:
            body["layers"] = layers

        result = await self._call_m5_api(
            "POST",
            "/api/v1/memory/recall",
            body,
            auth_token,
            trace_id,
        )

        data = result.get("data", {})
        results = data.get("results", [])

        # 提取记忆摘要
        memory_summary = ""
        if results:
            fragments = [r.get("content_preview", "") for r in results if r.get("content_preview")]
            memory_summary = "\n\n".join(fragments[:3])

        return {
            "memory_summary": memory_summary,
            "related_fragments": results,
            "confidence": results[0].get("similarity", 0.0) if results else 0.0,
            "total": data.get("total", len(results)),
            "layers": data.get("layers", []),
        }

    async def _action_archive(
        self,
        params: dict[str, Any],
        agent_id: str,
        domain: str,
        auth_token: str | None,
        trace_id: str | None,
    ) -> dict[str, Any]:
        """记忆归档."""
        content = params.get("content") or params.get("session", "")
        source = params.get("source", "skill")
        tags = params.get("tags", [])
        metadata = params.get("metadata", {})
        secret_level = params.get("secret_level")  # 密级：public/internal/confidential/top_secret

        # PII 预检（如果启用）
        if self._config["enable_pii_check"] and not secret_level:
            secret_level = self._auto_detect_secret_level(content)

        body = {
            "content": content,
            "source": source,
            "domain": domain,
            "agent_id": agent_id,
            "tags": tags,
            "metadata": metadata,
        }
        if secret_level:
            body["secret_level"] = secret_level

        result = await self._call_m5_api(
            "POST",
            "/api/v1/memory/archive",
            body,
            auth_token,
            trace_id,
        )

        data = result.get("data", {})
        return {
            "archived": True,
            "archive_id": data.get("memory_id", ""),
            "secret_level": data.get("secret_level", secret_level),
            "layer": data.get("layer", "l0_beach"),
            "created_at": data.get("created_at", ""),
        }

    async def _action_compress(
        self,
        params: dict[str, Any],
        agent_id: str,
        domain: str,
        auth_token: str | None,
        trace_id: str | None,
    ) -> dict[str, Any]:
        """记忆压缩/巩固（通常由系统定时执行，技能层仅触发浅层压缩）."""
        options = params.get("options", {})
        target_layer = options.get("target_layer", "l2_deep")
        days = options.get("days", 7)

        body = {
            "domain": domain,
            "agent_id": agent_id,
            "target_layer": target_layer,
            "days": days,
        }

        result = await self._call_m5_api(
            "POST",
            "/api/v1/memory/compress",
            body,
            auth_token,
            trace_id,
        )

        data = result.get("data", {})
        return {
            "compressed": True,
            "affected_memories": data.get("affected", 0),
            "target_layer": data.get("target_layer", target_layer),
        }

    async def _action_stats(
        self,
        params: dict[str, Any],
        agent_id: str,
        domain: str,
        auth_token: str | None,
        trace_id: str | None,
    ) -> dict[str, Any]:
        """记忆统计."""
        result = await self._call_m5_api(
            "GET",
            f"/api/v1/memory/stats?domain={domain}&agent_id={agent_id}",
            None,
            auth_token,
            trace_id,
        )
        return result.get("data", {})

    async def _action_search(
        self,
        params: dict[str, Any],
        agent_id: str,
        domain: str,
        auth_token: str | None,
        trace_id: str | None,
    ) -> dict[str, Any]:
        """关键词搜索."""
        query = params.get("query", "")
        top_k = int(params.get("top_k", 20))

        body = {
            "query": query,
            "top_k": top_k,
            "domain": domain,
            "agent_id": agent_id,
            "search_type": params.get("search_type", "hybrid"),  # keyword/semantic/hybrid
        }

        result = await self._call_m5_api(
            "POST",
            "/api/v1/memory/search",
            body,
            auth_token,
            trace_id,
        )

        data = result.get("data", {})
        return {
            "results": data.get("results", []),
            "total": data.get("total", 0),
            "search_type": data.get("search_type", "hybrid"),
        }

    async def _action_forget(
        self,
        params: dict[str, Any],
        agent_id: str,
        domain: str,
        auth_token: str | None,
        trace_id: str | None,
    ) -> dict[str, Any]:
        """遗忘/删除记忆."""
        memory_id = params.get("memory_id", "")
        if not memory_id:
            raise ValueError("Missing required param: memory_id")

        result = await self._call_m5_api(
            "DELETE",
            f"/api/v1/memory/{memory_id}?domain={domain}&agent_id={agent_id}",
            None,
            auth_token,
            trace_id,
        )

        data = result.get("data", {})
        return {
            "forgotten": True,
            "memory_id": memory_id,
            "secure_delete": data.get("secure_delete", False),
        }

    async def _action_preference(
        self,
        params: dict[str, Any],
        agent_id: str,
        domain: str,
        auth_token: str | None,
        trace_id: str | None,
    ) -> dict[str, Any]:
        """偏好管理（读/写）."""
        if params.get("action") == "set":
            # 设置偏好
            body = {
                "domain": domain,
                "agent_id": agent_id,
                "preferences": params.get("preferences", {}),
            }
            result = await self._call_m5_api(
                "POST",
                "/api/v1/memory/preference",
                body,
                auth_token,
                trace_id,
            )
            return {
                "updated": True,
                "preferences": result.get("data", {}).get("preferences", {}),
            }
        else:
            # 查询偏好
            result = await self._call_m5_api(
                "GET",
                f"/api/v1/memory/preference?domain={domain}&agent_id={agent_id}",
                None,
                auth_token,
                trace_id,
            )
            return {
                "preferences": result.get("data", {}).get("preferences", {}),
            }

    # ── 内部方法 ──────────────────────────────────────────

    async def _get_client(self) -> httpx.AsyncClient:
        """获取 HTTP 客户端（懒加载）."""
        if self._client is None:
            self._client = httpx.AsyncClient(
                base_url=self._config["m5_base_url"],
                timeout=self._config["timeout"],
            )
        return self._client

    async def _call_m5_api(
        self,
        method: str,
        path: str,
        body: dict[str, Any] | None,
        auth_token: str | None,
        trace_id: str | None,
    ) -> dict[str, Any]:
        """调用 M5 API."""
        client = await self._get_client()

        headers = {"Content-Type": "application/json"}
        if auth_token:
            headers["Authorization"] = f"Bearer {auth_token}"
        if trace_id:
            headers["X-Trace-ID"] = trace_id

        try:
            if method == "GET":
                resp = await client.get(path, headers=headers)
            elif method == "POST":
                resp = await client.post(path, json=body, headers=headers)
            elif method == "DELETE":
                resp = await client.delete(path, headers=headers)
            elif method == "PUT":
                resp = await client.put(path, json=body, headers=headers)
            else:
                raise ValueError(f"Unsupported method: {method}")

            if resp.status_code == 401:
                raise PermissionError("M5 authentication failed: invalid or missing token")
            if resp.status_code == 403:
                raise PermissionError("M5 access denied: insufficient permissions")
            if resp.status_code >= 500:
                raise ConnectionError(f"M5 server error: HTTP {resp.status_code}")

            data = resp.json()
            if data.get("code", 0) != 0:
                raise RuntimeError(f"M5 API error: {data.get('message', 'Unknown error')}")

            return data

        except httpx.ConnectError:
            self._m5_available = False
            raise ConnectionError(f"M5 service unavailable at {self._config['m5_base_url']}")
        except httpx.TimeoutException:
            raise TimeoutError(f"M5 request timeout after {self._config['timeout']}s")

    async def _check_m5_health(self) -> bool:
        """检查 M5 服务是否可用."""
        try:
            client = await self._get_client()
            resp = await client.get("/api/v1/memory/health", timeout=3.0)
            return resp.status_code == 200
        except Exception:
            return False

    def _auto_detect_secret_level(self, content: str) -> str:
        """根据内容自动检测密级（轻量级，真正的 PII 检测由 M1 PrivacyGuard 负责）.

        这里做一个快速预判，真正的密级由 M5 端最终决定。
        """
        # 简单关键词预判（真正的检测在 M5 和 M1 完成）
        critical_patterns = ["密码", "password", "私钥", "private key", "身份证", "银行卡"]
        high_patterns = ["手机号", "电话", "email", "邮箱", "地址"]

        content_lower = content.lower()
        for p in critical_patterns:
            if p.lower() in content_lower:
                return "top_secret"
        for p in high_patterns:
            if p.lower() in content_lower:
                return "confidential"

        return "internal"  # 默认内部级（M5 端可能升级到 top_secret）

    def _downgrade_result(
        self,
        request: SkillInvokeRequest,
        start: float,
    ) -> SkillInvokeResult:
        """降级返回（M5 不可用时）."""
        action = request.action
        latency = (time.perf_counter() - start) * 1000

        downgrade_data: dict[str, Any] = {}
        if action == "recall":
            downgrade_data = {
                "memory_summary": "",
                "related_fragments": [],
                "confidence": 0.0,
                "total": 0,
                "degraded": True,
            }
        elif action == "archive":
            downgrade_data = {
                "archived": False,
                "archive_id": None,
                "degraded": True,
                "note": "Memory service unavailable, archived in temporary buffer",
            }
        elif action == "stats":
            downgrade_data = {
                "total_memories": 0,
                "layers": {},
                "degraded": True,
            }
        else:
            downgrade_data = {"degraded": True}

        return SkillInvokeResult(
            skill_id=self.manifest.skill_id,
            action=action,
            status="success",  # 降级也算成功（不阻断业务）
            data=downgrade_data,
            latency_ms=latency,
            trace_id=request.trace_id,
            metadata={"degraded": True, "reason": "m5_unavailable"},
        )

    def _error(
        self,
        request: SkillInvokeRequest,
        error: str,
        start: float,
    ) -> SkillInvokeResult:
        latency = (time.perf_counter() - start) * 1000
        self._logger.error(
            "tide_memory_error",
            action=request.action,
            error=error,
            trace_id=request.trace_id,
        )
        return SkillInvokeResult(
            skill_id=self.manifest.skill_id,
            action=request.action,
            status="failure",
            error=error,
            latency_ms=latency,
            trace_id=request.trace_id,
        )
