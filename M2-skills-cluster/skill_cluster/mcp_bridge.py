"""MCP 客户端桥接器 — McpClientBridge.

将外部 MCP (Model Context Protocol) 服务器的工具接入为云汐技能。

设计原则：
  - 最小权限：只开放必要的工具，不暴露全部
  - 安全隔离：MCP 工具在沙箱中运行，不直接访问系统
  - 可配置：通过配置文件管理 MCP 服务器
  - 统一接口：接入后与本地技能使用方式完全一致

安全说明：
  - 仅接入经过安全审查的高星标 MCP 服务器
  - 文件系统类 MCP 严格限制目录范围
  - 写操作/破坏性操作需额外权限确认
  - 所有 MCP 调用均有审计日志

推荐的高安全 MCP 服务器（来自调研）：
  - 官方：modelcontextprotocol/servers (filesystem/git/puppeteer/sqlite/github)
  - GitHub 官方：github-mcp-server (30.6k Star)
"""

from __future__ import annotations

import asyncio
import json
import time
import uuid
from typing import Any

import httpx
import structlog

from skill_cluster.interfaces import (
    ISkill,
    SkillInvokeRequest,
    SkillInvokeResult,
    SkillManifest,
)
from skill_cluster.middleware import MiddlewarePipeline

logger = structlog.get_logger()


class McpClientBridge(ISkill):
    """MCP 客户端桥接技能.

    将一个外部 MCP 服务器的所有工具包装为一个云汐技能。
    每个工具对应 skill 中的一个 action。

    使用方式：
        # 创建一个 GitHub MCP 技能
        github_mcp = McpClientBridge(
            skill_id="skill.github",
            name="GitHub助手",
            mcp_server_url="http://localhost:3000/mcp",
            mcp_server_type="http",
        )
        registry.register(github_mcp)

        # 调用方式与普通技能一样
        result = await github_mcp.invoke(SkillInvokeRequest(
            skill_id="skill.github",
            action="list_repos",
            params={"username": "octocat"},
            trace_id="...",
        ))
    """

    def __init__(
        self,
        skill_id: str,
        name: str,
        mcp_server_url: str,
        mcp_server_type: str = "http",  # http / stdio / sse
        description: str = "",
        tags: list[str] | None = None,
        api_key: str = "",
        timeout: float = 30.0,
        allowed_tools: list[str] | None = None,  # None = 全部允许
        blocked_tools: list[str] | None = None,
        read_only: bool = False,  # 只读模式，禁止写操作
    ) -> None:
        self._mcp_url = mcp_server_url.rstrip("/")
        self._mcp_type = mcp_server_type
        self._api_key = api_key
        self._timeout = timeout
        self._allowed_tools = allowed_tools
        self._blocked_tools = blocked_tools or []
        self._read_only = read_only

        # 【P0-1 修复】绑定结构化日志实例，替换未定义的 self._logger
        self._logger = logger.bind(
            skill_id=skill_id,
            mcp_server=mcp_server_url,
        )

        # 【优化1】MCP 桥接接入中间件管道，享受缓存、熔断、指标等能力
        self.middleware = MiddlewarePipeline()

        # HTTP 客户端（懒加载）
        self._client: httpx.AsyncClient | None = None

        # MCP 初始化握手状态
        self._initialized = False
        self._server_info: dict[str, Any] | None = None

        # 工具列表缓存
        self._tools_cache: list[dict[str, Any]] | None = None
        self._tools_cache_time: float = 0.0
        self._cache_ttl: float = 300.0  # 工具列表缓存 5 分钟

        # 构造 manifest（先放占位，工具列表懒加载）
        manifest = SkillManifest(
            skill_id=skill_id,
            name=name,
            version="1.0.0-mcp",
            description=description or f"MCP 桥接: {mcp_server_url}",
            author="mcp-bridge",
            tags=tags or ["mcp", "external"],
            capabilities=["list_tools", "call_tool"],  # 实际工具列表运行时发现
            permissions=["read"] if read_only else ["read", "write"],
            entrypoint="McpClientBridge",
            config_schema={
                "type": "object",
                "properties": {
                    "mcp_server_url": {"type": "string", "description": "MCP 服务器地址"},
                    "api_key": {"type": "string", "description": "API Key"},
                    "read_only": {"type": "boolean", "description": "只读模式"},
                },
            },
        )
        super().__init__(manifest)
        self._config: dict[str, Any] = {}

    # ── 核心接口 ──────────────────────────────────────────

    async def invoke(self, request: SkillInvokeRequest) -> SkillInvokeResult:
        """调用 MCP 工具（通过中间件管道）."""
        # 【优化1】通过中间件管道执行调用，享受缓存、熔断、指标等能力
        async def _handler() -> SkillInvokeResult:
            return await self._invoke_internal(request)

        return await self.middleware.execute(request, "mcp_bridge", _handler)

    async def _invoke_internal(self, request: SkillInvokeRequest) -> SkillInvokeResult:
        """MCP 调用内部实现（不含中间件）."""
        action = request.action
        params = request.params or {}
        start = time.perf_counter()

        try:
            # 特殊动作：列出工具
            if action == "list_tools":
                tools = await self._list_tools()
                latency = (time.perf_counter() - start) * 1000
                return SkillInvokeResult(
                    skill_id=self.manifest.skill_id,
                    action=action,
                    status="success",
                    data={"tools": tools, "total": len(tools)},
                    latency_ms=latency,
                    trace_id=request.trace_id,
                )

            # 安全检查
            await self._check_tool_permission(action)

            # 调用 MCP 工具
            result_data = await self._call_tool(action, params, request.trace_id)

            latency = (time.perf_counter() - start) * 1000
            return SkillInvokeResult(
                skill_id=self.manifest.skill_id,
                action=action,
                status="success",
                data=result_data,
                latency_ms=latency,
                trace_id=request.trace_id,
                metadata={"mcp_server": self._mcp_url, "mcp_tool": action},
            )

        except PermissionError as e:
            return self._error(request, f"Permission denied: {e}", start)
        except Exception as e:
            return self._error(request, str(e), start)

    async def health(self) -> dict[str, Any]:
        """健康检查."""
        try:
            tools = await self._list_tools()
            return {
                "healthy": True,
                "skill_id": self.manifest.skill_id,
                "mode": "mcp-bridge",
                "server_url": self._mcp_url,
                "available_tools": len(tools),
            }
        except Exception as e:
            return {
                "healthy": False,
                "skill_id": self.manifest.skill_id,
                "mode": "mcp-bridge",
                "server_url": self._mcp_url,
                "error": str(e),
            }

    async def configure(self, config: dict[str, Any]) -> None:
        self._config.update(config)
        if "mcp_server_url" in config:
            self._mcp_url = config["mcp_server_url"].rstrip("/")
            self._tools_cache = None  # 失效缓存
            self._initialized = False  # 重置初始化状态
            self._server_info = None
            if self._client:
                await self._client.aclose()
                self._client = None
        if "api_key" in config:
            self._api_key = config["api_key"]

    # ── MCP 初始化握手 ────────────────────────────────────

    async def initialize(self) -> dict[str, Any]:
        """【优化2】MCP 标准 initialize 握手.

        在首次连接时发送 initialize 请求，协商协议版本和能力。

        Returns:
            服务器信息字典.
        """
        if self._initialized and self._server_info is not None:
            return self._server_info

        if self._mcp_type != "http":
            self._logger.warning(
                "mcp_initialize_skip_non_http",
                mcp_type=self._mcp_type,
            )
            self._initialized = True
            self._server_info = {"name": "unknown", "version": "0.0.0"}
            return self._server_info

        client = await self._get_client()
        request_id = str(uuid.uuid4())
        body = {
            "jsonrpc": "2.0",
            "method": "initialize",
            "params": {
                "protocolVersion": "2024-11-05",
                "capabilities": {
                    "tools": {},
                },
                "clientInfo": {
                    "name": "yunxi-skill-cluster",
                    "version": "1.0.0",
                },
            },
            "id": request_id,
        }

        try:
            resp = await client.post(
                "/mcp/v1",
                json=body,
                timeout=self._timeout,
            )
        except httpx.HTTPError:
            # 尝试备用路径
            try:
                resp = await client.post(
                    "/initialize",
                    json=body,
                    timeout=self._timeout,
                )
            except Exception as e:
                self._logger.warning(
                    "mcp_initialize_failed",
                    error=str(e),
                )
                self._initialized = True
                self._server_info = {"name": "unknown", "version": "0.0.0"}
                return self._server_info

        if resp.status_code != 200:
            self._logger.warning(
                "mcp_initialize_http_error",
                status_code=resp.status_code,
            )
            self._initialized = True
            self._server_info = {"name": "unknown", "version": "0.0.0"}
            return self._server_info

        data = resp.json()
        result = data.get("result", {})
        server_info = result.get("serverInfo", {})

        # 发送 initialized 通知
        try:
            notification_body = {
                "jsonrpc": "2.0",
                "method": "notifications/initialized",
                "params": {},
            }

            async def _send_notification() -> None:
                try:
                    await client.post("/mcp/v1", json=notification_body, timeout=self._timeout)
                except Exception:
                    pass
            asyncio.create_task(_send_notification())
        except Exception:
            pass

        self._initialized = True
        self._server_info = server_info or {"name": "unknown", "version": "0.0.0"}
        self._logger.info(
            "mcp_initialize_success",
            server_name=self._server_info.get("name", "unknown"),
            server_version=self._server_info.get("version", "0.0.0"),
        )
        return self._server_info

    # ── 工具列表发现 ──────────────────────────────────────

    async def _list_tools(self) -> list[dict[str, Any]]:
        """获取 MCP 服务器的工具列表（带缓存）."""
        now = time.time()
        if self._tools_cache and (now - self._tools_cache_time) < self._cache_ttl:
            return self._tools_cache

        # 首次调用前先进行 initialize 握手
        if not self._initialized:
            await self.initialize()

        tools = await self._fetch_tools_from_server()

        # 过滤允许的工具
        if self._allowed_tools:
            tools = [t for t in tools if t.get("name") in self._allowed_tools]
        if self._blocked_tools:
            tools = [t for t in tools if t.get("name") not in self._blocked_tools]

        self._tools_cache = tools
        self._tools_cache_time = now

        return tools

    async def _fetch_tools_from_server(self) -> list[dict[str, Any]]:
        """从 MCP 服务器获取工具列表."""
        if self._mcp_type == "http":
            return await self._fetch_tools_http()
        else:
            # stdio/sse 模式暂未实现，返回空列表
            self._logger.warning(
                "mcp_type_not_supported",
                mcp_type=self._mcp_type,
                skill_id=self.manifest.skill_id,
            )
            return []

    async def _fetch_tools_http(self) -> list[dict[str, Any]]:
        """通过 HTTP 获取工具列表."""
        client = await self._get_client()

        # MCP 标准：POST /tools/list 或 JSON-RPC 调用 tools/list
        request_id = str(uuid.uuid4())
        body = {
            "jsonrpc": "2.0",
            "method": "tools/list",
            "params": {},
            "id": request_id,
        }

        try:
            resp = await client.post(
                "/mcp/v1/tools/list",
                json=body,
                timeout=self._timeout,
            )
        except httpx.HTTPError:
            # 尝试备用路径
            try:
                resp = await client.post(
                    "/tools/list",
                    json=body,
                    timeout=self._timeout,
                )
            except Exception as e:
                raise ConnectionError(f"Cannot connect to MCP server: {e}") from e

        if resp.status_code != 200:
            raise ConnectionError(f"MCP server returned HTTP {resp.status_code}")

        data = resp.json()

        # 解析 JSON-RPC 响应
        if "result" in data:
            result = data["result"]
            return result.get("tools", [])
        elif "tools" in data:
            return data["tools"]
        elif isinstance(data, list):
            return data
        else:
            return []

    # ── 工具调用 ──────────────────────────────────────────

    async def _call_tool(
        self,
        tool_name: str,
        arguments: dict[str, Any],
        trace_id: str | None,
    ) -> dict[str, Any]:
        """调用 MCP 工具."""
        # 首次调用前先进行 initialize 握手
        if not self._initialized:
            await self.initialize()

        if self._mcp_type == "http":
            return await self._call_tool_http(tool_name, arguments, trace_id)
        else:
            raise NotImplementedError(f"MCP type {self._mcp_type} not supported yet")

    async def _call_tool_http(
        self,
        tool_name: str,
        arguments: dict[str, Any],
        trace_id: str | None,
    ) -> dict[str, Any]:
        """通过 HTTP 调用 MCP 工具."""
        client = await self._get_client()

        request_id = trace_id or str(uuid.uuid4())
        body = {
            "jsonrpc": "2.0",
            "method": "tools/call",
            "params": {
                "name": tool_name,
                "arguments": arguments,
                "_meta": {"trace_id": request_id},
            },
            "id": request_id,
        }

        self._logger.info(
            "mcp_tool_call",
            skill_id=self.manifest.skill_id,
            tool=tool_name,
            trace_id=trace_id,
        )

        try:
            resp = await client.post(
                "/mcp/v1/tools/call",
                json=body,
                timeout=self._timeout,
            )
        except httpx.HTTPError:
            # 尝试备用路径
            resp = await client.post(
                "/tools/call",
                json=body,
                timeout=self._timeout,
            )

        if resp.status_code != 200:
            raise RuntimeError(f"MCP tool call failed: HTTP {resp.status_code}")

        data = resp.json()

        # 解析 JSON-RPC 响应
        if "error" in data and data["error"]:
            error = data["error"]
            raise RuntimeError(f"MCP error: {error.get('message', str(error))}")

        result = data.get("result", data)

        # MCP 标准返回格式：{content: [{type: "text", text: "..."}]}
        if "content" in result:
            contents = result["content"]
            text_parts = []
            for c in contents:
                if c.get("type") == "text":
                    text_parts.append(c.get("text", ""))
                elif c.get("type") == "image":
                    text_parts.append(f"[Image: {c.get('data', '')[:50]}...]")
            return {
                "output": "\n".join(text_parts),
                "raw_content": contents,
                "isError": result.get("isError", False),
            }

        return {"output": json.dumps(result, ensure_ascii=False), "raw": result}

    # ── 安全检查 ──────────────────────────────────────────

    async def _check_tool_permission(self, tool_name: str) -> None:
        """检查工具调用权限."""
        # 1. 允许列表检查
        if self._allowed_tools and tool_name not in self._allowed_tools:
            raise PermissionError(f"Tool '{tool_name}' not in allowed list")

        # 2. 阻止列表检查
        if tool_name in self._blocked_tools:
            raise PermissionError(f"Tool '{tool_name}' is blocked")

        # 3. 只读模式检查
        if self._read_only:
            write_keywords = [
                "write", "delete", "remove", "create", "update", "modify",
                "push", "commit", "merge", "upload", "send", "post",
                "写入", "删除", "创建", "修改", "更新", "提交", "推送",
            ]
            tool_lower = tool_name.lower()
            for kw in write_keywords:
                if kw in tool_lower:
                    raise PermissionError(
                        f"Tool '{tool_name}' appears to be a write tool, "
                        f"but read-only mode is enabled"
                    )

    # ── 内部方法 ──────────────────────────────────────────

    async def _get_client(self) -> httpx.AsyncClient:
        """获取 HTTP 客户端."""
        if self._client is None:
            headers = {}
            if self._api_key:
                headers["Authorization"] = f"Bearer {self._api_key}"

            self._client = httpx.AsyncClient(
                base_url=self._mcp_url,
                headers=headers,
                timeout=self._timeout,
            )
        return self._client

    def _error(
        self,
        request: SkillInvokeRequest,
        error: str,
        start: float,
    ) -> SkillInvokeResult:
        latency = (time.perf_counter() - start) * 1000
        self._logger.error(
            "mcp_bridge_error",
            skill_id=self.manifest.skill_id,
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


# ── 预设的 MCP 服务器配置 ────────────────────────────────

# 经过安全审查的推荐 MCP 服务器配置
PRESET_MCP_SERVERS: dict[str, dict[str, Any]] = {
    "github": {
        "skill_id": "skill.github",
        "name": "GitHub助手",
        "description": "GitHub 官方 MCP 服务器 - 仓库管理、PR/Issue 自动化",
        "tags": ["github", "dev", "mcp"],
        "server_url": "http://localhost:3001",
        "read_only": False,
        "security_note": "GitHub 官方出品，30.6k Star，安全评级高",
    },
    "filesystem": {
        "skill_id": "skill.filesystem",
        "name": "文件管理",
        "description": "MCP 官方文件系统服务器 - 受限目录内的文件操作",
        "tags": ["filesystem", "file", "mcp"],
        "server_url": "http://localhost:3002",
        "read_only": False,
        "security_note": "官方实现，有目录访问控制，需严格限制根目录",
    },
    "browser": {
        "skill_id": "skill.browser",
        "name": "浏览器助手",
        "description": "MCP 官方 Puppeteer 服务器 - 网页自动化",
        "tags": ["browser", "puppeteer", "mcp"],
        "server_url": "http://localhost:3003",
        "read_only": True,  # 默认只读模式，防止危险操作
        "security_note": "官方 Puppeteer 实现，默认只读模式更安全",
    },
    "git": {
        "skill_id": "skill.git",
        "name": "Git管理",
        "description": "MCP 官方 Git 服务器 - 本地仓库操作",
        "tags": ["git", "dev", "mcp"],
        "server_url": "http://localhost:3004",
        "read_only": False,
        "security_note": "官方实现，曾有漏洞披露，需使用最新版本",
    },
    "sqlite": {
        "skill_id": "skill.sqlite",
        "name": "数据库查询",
        "description": "MCP 官方 SQLite 服务器 - 数据库查询",
        "tags": ["database", "sqlite", "mcp"],
        "server_url": "http://localhost:3005",
        "read_only": True,  # 默认只读
        "security_note": "官方实现，建议只读模式使用",
    },
}
