"""M11 MCP Bus - M2 技能集群适配器.

将 M2 技能集群封装为标准 MCP 工具服务。

M2 提供了内置 MCP 端点（/mcp/v1/tools/list 和 /mcp/v1/tools/call），
本适配器优先尝试桥接 M2 的 MCP 端点；如果桥接失败，则回退到
通过 M2 REST API 手动封装工具的方式。
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

import httpx

from .base import BaseMcpAdapter


class M2SkillAdapter(BaseMcpAdapter):
    """M2 技能集群 MCP 适配器.

    将 M2 技能集群的能力封装为 MCP 标准工具，注册到 M11 总线。

    支持两种工作模式：
    1. 桥接模式（优先）：直接转发 M2 内置 MCP 端点的请求响应
    2. 封装模式（回退）：通过 M2 REST API 手动封装工具列表和调用

    提供的 MCP 工具：
    - m2.list_skills: 获取所有技能列表
    - m2.invoke_skill: 调用指定技能
    - m2.translate: 翻译
    - m2.web_fetch: 网页抓取
    - m2.search: 全文搜索
    - m2.analyze_data: 数据分析
    """

    adapter_name: str = "m2"
    adapter_description: str = "M2 技能集群 - 翻译、网页抓取、全文搜索、数据分析等通用技能"

    def __init__(
        self,
        m2_base_url: str = "http://localhost:8002",
        bus_url: str = "http://localhost:8011",
        server_endpoint: Optional[str] = None,
        use_bridge_mode: bool = True,
    ) -> None:
        """初始化 M2 适配器.

        Args:
            m2_base_url: M2 技能集群服务地址
            bus_url: M11 总线地址
            server_endpoint: 本适配器的 MCP 端点地址
            use_bridge_mode: 是否优先使用桥接模式（直接转发 M2 的 MCP 端点）
        """
        super().__init__(
            bus_url=bus_url,
            server_name="m2",
            server_endpoint=server_endpoint,
        )

        self.m2_base_url = m2_base_url.rstrip("/")
        self._use_bridge_mode = use_bridge_mode
        self._bridge_available: Optional[bool] = None

    # ============================================================
    # 桥接模式检测
    # ============================================================

    def _check_bridge_available(self) -> bool:
        """检测 M2 是否支持 MCP 端点（桥接模式是否可用）.

        Returns:
            True 表示桥接模式可用，False 表示不可用
        """
        if self._bridge_available is not None:
            return self._bridge_available

        try:
            with httpx.Client(timeout=3.0) as client:
                response = client.post(
                    f"{self.m2_base_url}/mcp/v1/tools/list",
                    json={
                        "jsonrpc": "2.0",
                        "id": 1,
                        "method": "tools/list",
                        "params": {},
                    },
                )
                if response.status_code == 200:
                    data = response.json()
                    if "result" in data and "tools" in data.get("result", {}):
                        self._bridge_available = True
                        print(f"[{self.server_name}] 检测到 M2 内置 MCP 端点，启用桥接模式")
                        return True
        except Exception as e:
            # M2 MCP 端点不可用，记录后降级到封装模式
            import logging
            logging.getLogger(__name__).debug(
                "检测 M2 MCP 端点失败，将使用封装模式: %s", e
            )

        self._bridge_available = False
        print(f"[{self.server_name}] M2 MCP 端点不可用，使用封装模式")
        return False

    # ============================================================
    # 工具列表
    # ============================================================

    def get_tools(self) -> List[Dict[str, Any]]:
        """获取 M2 工具列表.

        桥接模式：直接从 M2 的 MCP 端点获取工具列表
        封装模式：返回预定义的工具封装列表

        Returns:
            MCP 标准格式的工具列表
        """
        if self._use_bridge_mode and self._check_bridge_available():
            return self._get_tools_bridge()

        return self._get_tools_wrapped()

    def _get_tools_bridge(self) -> List[Dict[str, Any]]:
        """桥接模式：从 M2 MCP 端点获取工具列表.

        Returns:
            MCP 标准格式的工具列表
        """
        try:
            with httpx.Client(timeout=5.0) as client:
                response = client.post(
                    f"{self.m2_base_url}/mcp/v1/tools/list",
                    json={
                        "jsonrpc": "2.0",
                        "id": 1,
                        "method": "tools/list",
                        "params": {},
                    },
                )
                response.raise_for_status()
                data = response.json()

            if "result" in data and "tools" in data["result"]:
                return data["result"]["tools"]
        except Exception as e:
            print(f"[{self.server_name}] 桥接获取工具列表失败: {e}")

        # 桥接失败，回退到封装模式
        return self._get_tools_wrapped()

    def _get_tools_wrapped(self) -> List[Dict[str, Any]]:
        """封装模式：返回预定义的 M2 工具列表.

        Returns:
            MCP 标准格式的工具列表
        """
        return [
            {
                "name": "m2.list_skills",
                "description": "获取 M2 所有技能列表，支持按分类和关键词筛选",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "category": {
                            "type": "string",
                            "description": "技能分类筛选，如 translation、search、analysis 等",
                        },
                        "keyword": {
                            "type": "string",
                            "description": "关键词搜索（名称或描述）",
                        },
                    },
                },
            },
            {
                "name": "m2.invoke_skill",
                "description": "调用指定的 M2 技能，需提供 skill_id、action 和参数",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "skill_id": {
                            "type": "string",
                            "description": "技能 ID，如 skill.translate",
                        },
                        "action": {
                            "type": "string",
                            "description": "技能动作，如 translate_text、fetch_url",
                        },
                        "params": {
                            "type": "object",
                            "description": "技能调用参数，具体格式取决于技能",
                            "default": {},
                        },
                    },
                    "required": ["skill_id", "action"],
                },
            },
            {
                "name": "m2.translate",
                "description": "文本翻译，支持多语言互译，调用 skill.translate 的 translate_text",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "text": {
                            "type": "string",
                            "description": "待翻译的文本内容",
                        },
                        "source_lang": {
                            "type": "string",
                            "description": "源语言代码，如 zh、en、ja 等，auto 表示自动检测",
                            "default": "auto",
                        },
                        "target_lang": {
                            "type": "string",
                            "description": "目标语言代码，如 zh、en、ja 等",
                            "default": "en",
                        },
                    },
                    "required": ["text"],
                },
            },
            {
                "name": "m2.web_fetch",
                "description": "网页内容抓取，获取指定 URL 的网页文本内容，调用 skill.web_fetch 的 fetch_url",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "url": {
                            "type": "string",
                            "description": "要抓取的网页 URL 地址",
                        },
                    },
                    "required": ["url"],
                },
            },
            {
                "name": "m2.search",
                "description": "全文搜索，在指定索引中搜索相关文档，调用 skill.fulltext_search 的 search",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "query": {
                            "type": "string",
                            "description": "搜索查询语句",
                        },
                        "index_name": {
                            "type": "string",
                            "description": "索引名称，指定在哪个索引中搜索",
                            "default": "default",
                        },
                    },
                    "required": ["query"],
                },
            },
            {
                "name": "m2.analyze_data",
                "description": "数据分析，对提供的数据执行指定的分析方法，调用 skill.data_analysis",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "data": {
                            "description": "待分析的数据，可以是列表、字典或表格数据",
                        },
                        "method": {
                            "type": "string",
                            "description": "分析方法，如 summary、statistics、correlation、trend 等",
                            "default": "summary",
                        },
                    },
                    "required": ["data"],
                },
            },
            {
                "name": "m2.market_list",
                "description": "浏览技能市场，获取可安装的技能包列表",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "category": {"type": "string", "description": "分类筛选"},
                        "tag": {"type": "string", "description": "标签筛选"},
                        "page": {"type": "integer", "description": "页码", "default": 1},
                        "size": {"type": "integer", "description": "每页数量", "default": 20},
                    },
                },
            },
            {
                "name": "m2.market_search",
                "description": "在技能市场中搜索技能",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "query": {"type": "string", "description": "搜索关键词"},
                    },
                    "required": ["query"],
                },
            },
            {
                "name": "m2.market_install",
                "description": "从技能市场安装一个技能包",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "package_id": {"type": "string", "description": "技能包ID"},
                    },
                    "required": ["package_id"],
                },
            },
            {
                "name": "m2.market_publish",
                "description": "将当前已注册的技能发布到市场",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "skill_id": {"type": "string", "description": "要发布的技能ID"},
                        "description": {"type": "string", "description": "技能描述"},
                        "category": {"type": "string", "description": "分类", "default": "general"},
                        "tags": {"type": "array", "items": {"type": "string"}, "description": "标签列表", "default": []},
                    },
                    "required": ["skill_id"],
                },
            },
        ]

    # ============================================================
    # 工具调用
    # ============================================================

    def call_tool(self, name: str, args: Dict[str, Any]) -> Dict[str, Any]:
        """调用 M2 工具.

        桥接模式：直接转发到 M2 的 MCP 端点
        封装模式：根据工具名调用对应的 M2 REST API

        Args:
            name: 工具名称
            args: 工具参数

        Returns:
            MCP 标准格式的调用结果

        Raises:
            ValueError: 工具不存在或调用失败
            RuntimeError: 调用异常
        """
        if self._use_bridge_mode and self._check_bridge_available():
            return self._call_tool_bridge(name, args)

        return self._call_tool_wrapped(name, args)

    def _call_tool_bridge(self, name: str, args: Dict[str, Any]) -> Dict[str, Any]:
        """桥接模式：转发调用到 M2 的 MCP 端点.

        Args:
            name: 工具名称
            args: 工具参数

        Returns:
            MCP 标准格式的调用结果

        Raises:
            ValueError: 调用失败时回退到封装模式
        """
        try:
            with httpx.Client(timeout=30.0) as client:
                response = client.post(
                    f"{self.m2_base_url}/mcp/v1/tools/call",
                    json={
                        "jsonrpc": "2.0",
                        "id": 1,
                        "method": "tools/call",
                        "params": {
                            "name": name,
                            "arguments": args,
                        },
                    },
                )
                response.raise_for_status()
                data = response.json()

            if "result" in data:
                return data["result"]

            error = data.get("error", {})
            raise ValueError(error.get("message", "调用失败"))

        except httpx.HTTPError as e:
            # 桥接失败，回退到封装模式
            print(f"[{self.server_name}] 桥接调用失败，回退到封装模式: {e}")
            return self._call_tool_wrapped(name, args)

    def _call_tool_wrapped(self, name: str, args: Dict[str, Any]) -> Dict[str, Any]:
        """封装模式：根据工具名调用对应的 M2 REST API.

        Args:
            name: 工具名称
            args: 工具参数

        Returns:
            MCP 标准格式的调用结果

        Raises:
            ValueError: 工具不存在或调用失败
            RuntimeError: 调用异常
        """
        tool_map = {
            "m2.list_skills": self._call_list_skills,
            "m2.invoke_skill": self._call_invoke_skill,
            "m2.translate": self._call_translate,
            "m2.web_fetch": self._call_web_fetch,
            "m2.search": self._call_search,
            "m2.analyze_data": self._call_analyze_data,
            "m2.market_list": self._call_market_list,
            "m2.market_search": self._call_market_search,
            "m2.market_install": self._call_market_install,
            "m2.market_publish": self._call_market_publish,
        }

        handler = tool_map.get(name)
        if not handler:
            raise ValueError(f"未知的 M2 工具: {name}")

        result = handler(args)
        return self._wrap_result(result)

    # ============================================================
    # 各工具的 REST API 实现（封装模式）
    # ============================================================

    def _call_list_skills(self, args: Dict[str, Any]) -> Any:
        """处理 list_skills 工具：获取技能列表.

        Args:
            args: 工具参数（category, keyword）

        Returns:
            技能列表数据
        """
        params: Dict[str, Any] = {}
        if args.get("category"):
            params["category"] = args["category"]
        if args.get("keyword"):
            params["keyword"] = args["keyword"]

        return self._request_m2(
            method="GET",
            path="/api/v2/skills",
            params=params,
        )

    def _call_invoke_skill(self, args: Dict[str, Any]) -> Any:
        """处理 invoke_skill 工具：调用指定技能.

        Args:
            args: 工具参数（skill_id, action, params）

        Returns:
            技能调用结果
        """
        skill_id = args.get("skill_id", "")
        action = args.get("action", "")
        params = args.get("params", {})

        if not skill_id or not action:
            raise ValueError("skill_id 和 action 为必填参数")

        return self._request_m2(
            method="POST",
            path="/api/v2/skills/invoke",
            json={
                "skill_id": skill_id,
                "action": action,
                "params": params,
            },
        )

    def _call_translate(self, args: Dict[str, Any]) -> Any:
        """处理 translate 工具：文本翻译.

        调用 skill.translate 的 translate_text 动作。

        Args:
            args: 工具参数（text, source_lang, target_lang）

        Returns:
            翻译结果
        """
        text = args.get("text", "")
        if not text:
            raise ValueError("text 为必填参数")

        return self._request_m2(
            method="POST",
            path="/api/v2/skills/invoke",
            json={
                "skill_id": "skill.translate",
                "action": "translate_text",
                "params": {
                    "text": text,
                    "source_lang": args.get("source_lang", "auto"),
                    "target_lang": args.get("target_lang", "en"),
                },
            },
        )

    def _call_web_fetch(self, args: Dict[str, Any]) -> Any:
        """处理 web_fetch 工具：网页抓取.

        调用 skill.web_fetch 的 fetch_url 动作。

        Args:
            args: 工具参数（url）

        Returns:
            网页内容
        """
        url = args.get("url", "")
        if not url:
            raise ValueError("url 为必填参数")

        return self._request_m2(
            method="POST",
            path="/api/v2/skills/invoke",
            json={
                "skill_id": "skill.web_fetch",
                "action": "fetch_url",
                "params": {
                    "url": url,
                },
            },
        )

    def _call_search(self, args: Dict[str, Any]) -> Any:
        """处理 search 工具：全文搜索.

        调用 skill.fulltext_search 的 search 动作。

        Args:
            args: 工具参数（query, index_name）

        Returns:
            搜索结果
        """
        query = args.get("query", "")
        if not query:
            raise ValueError("query 为必填参数")

        return self._request_m2(
            method="POST",
            path="/api/v2/skills/invoke",
            json={
                "skill_id": "skill.fulltext_search",
                "action": "search",
                "params": {
                    "query": query,
                    "index_name": args.get("index_name", "default"),
                },
            },
        )

    def _call_analyze_data(self, args: Dict[str, Any]) -> Any:
        """处理 analyze_data 工具：数据分析.

        调用 skill.data_analysis 技能。

        Args:
            args: 工具参数（data, method）

        Returns:
            分析结果
        """
        if "data" not in args:
            raise ValueError("data 为必填参数")

        return self._request_m2(
            method="POST",
            path="/api/v2/skills/invoke",
            json={
                "skill_id": "skill.data_analysis",
                "action": "analyze",
                "params": {
                    "data": args["data"],
                    "method": args.get("method", "summary"),
                },
            },
        )

    def _call_market_list(self, args: Dict[str, Any]) -> Any:
        params = {}
        for k in ("category", "tag", "page", "size"):
            if k in args:
                params[k] = args[k]
        return self._request_m2("GET", "/api/v2/market/list", params=params)

    def _call_market_search(self, args: Dict[str, Any]) -> Any:
        return self._request_m2("GET", "/api/v2/market/search", params={"q": args.get("query", "")})

    def _call_market_install(self, args: Dict[str, Any]) -> Any:
        return self._request_m2("POST", f"/api/v2/market/{args['package_id']}/install", json={})

    def _call_market_publish(self, args: Dict[str, Any]) -> Any:
        return self._request_m2("POST", "/api/v2/market/publish", json={
            "skill_id": args["skill_id"],
            "description": args.get("description", ""),
            "category": args.get("category", "general"),
            "tags": args.get("tags", []),
            "is_public": True,
        })

    # ============================================================
    # M2 API 调用封装
    # ============================================================

    def _request_m2(
        self,
        method: str,
        path: str,
        json: Optional[Dict[str, Any]] = None,
        params: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """调用 M2 技能集群 API.

        Args:
            method: HTTP 方法（GET/POST 等）
            path: API 路径
            json: 请求体 JSON 数据
            params: URL 查询参数

        Returns:
            API 响应数据

        Raises:
            RuntimeError: 请求失败时抛出
        """
        url = f"{self.m2_base_url}{path}"

        headers = {"Content-Type": "application/json"}

        try:
            with httpx.Client(timeout=30.0) as client:
                response = client.request(
                    method=method,
                    url=url,
                    json=json,
                    params=params,
                    headers=headers,
                )
                response.raise_for_status()
                return response.json()
        except httpx.HTTPStatusError as e:
            detail = ""
            try:
                error_data = e.response.json()
                detail = error_data.get("detail", error_data.get("message", str(e)))
            except Exception:
                detail = e.response.text or str(e)
            raise RuntimeError(f"M2 技能 API 调用失败（{e.response.status_code}）: {detail}") from e
        except httpx.HTTPError as e:
            raise RuntimeError(f"M2 技能 API 网络错误: {e}") from e
        except Exception as e:
            raise RuntimeError(f"M2 技能 API 调用异常: {e}") from e

    # ============================================================
    # 健康检查
    # ============================================================

    def check_m2_health(self) -> Dict[str, Any]:
        """检查 M2 服务健康状态.

        Returns:
            健康状态信息
        """
        try:
            with httpx.Client(timeout=3.0) as client:
                response = client.get(f"{self.m2_base_url}/api/v2/health")
                response.raise_for_status()
                return {
                    "status": "healthy",
                    "m2_status": response.json(),
                }
        except Exception as e:
            return {
                "status": "unhealthy",
                "error": str(e),
            }
