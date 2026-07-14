"""M11 MCP Bus - M5 潮汐记忆适配器.

将 M5 潮汐记忆系统的记忆存储、查询、搜索能力封装为 MCP 工具服务。
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

import httpx

from .base import BaseMcpAdapter


class M5MemoryAdapter(BaseMcpAdapter):
    """M5 潮汐记忆 MCP 适配器.

    提供的 MCP 工具：
    - m5.memory_store: 存储记忆
    - m5.memory_recall: 检索记忆
    - m5.memory_search: 高级搜索记忆
    - m5.memory_stats: 获取记忆统计
    """

    adapter_name: str = "m5"
    adapter_description: str = "M5 潮汐记忆 - 记忆存储、检索与搜索"

    def __init__(
        self,
        m5_base_url: str = "http://localhost:8005",
        bus_url: str = "http://localhost:8011",
        server_endpoint: Optional[str] = None,
    ) -> None:
        super().__init__(
            bus_url=bus_url,
            server_name="m5",
            server_endpoint=server_endpoint,
        )
        self.m5_base_url = m5_base_url.rstrip("/")

    def get_tools(self) -> List[Dict[str, Any]]:
        return [
            {
                "name": "m5.memory_store",
                "description": "存储记忆到 M5 潮汐记忆系统。可用于保存代码生成结果、对话摘要、用户偏好等。",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "content": {
                            "type": "string",
                            "description": "记忆内容，1-10000 字符",
                        },
                        "domain": {
                            "type": "string",
                            "description": "记忆域：private(私有)/shared(共享)/core(核心)",
                            "default": "private",
                        },
                        "tags": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "标签列表，如 [\"code_generation\", \"python\"]",
                            "default": [],
                        },
                        "source": {
                            "type": "string",
                            "description": "记忆来源标识",
                            "default": "mcp",
                        },
                        "metadata": {
                            "type": "object",
                            "description": "附加元数据",
                            "default": {},
                        },
                    },
                    "required": ["content"],
                },
            },
            {
                "name": "m5.memory_recall",
                "description": "从 M5 潮汐记忆系统检索相关记忆。支持按查询语句和层级检索。",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "query": {
                            "type": "string",
                            "description": "检索查询语句",
                        },
                        "top_k": {
                            "type": "integer",
                            "description": "返回条数",
                            "default": 5,
                        },
                        "layers": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "检索层级：l1_shallow(浅层)/l2_deep(深层)",
                            "default": ["l1_shallow", "l2_deep"],
                        },
                        "domain": {
                            "type": "string",
                            "description": "记忆域筛选",
                            "default": "private",
                        },
                    },
                    "required": ["query"],
                },
            },
            {
                "name": "m5.memory_search",
                "description": "高级搜索 M5 记忆，支持全文搜索和过滤。",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "query": {
                            "type": "string",
                            "description": "搜索查询语句",
                        },
                        "top_k": {
                            "type": "integer",
                            "description": "返回条数",
                            "default": 10,
                        },
                        "domain": {
                            "type": "string",
                            "description": "记忆域筛选",
                            "default": "private",
                        },
                    },
                    "required": ["query"],
                },
            },
            {
                "name": "m5.memory_stats",
                "description": "获取 M5 潮汐记忆系统的统计信息（总记忆数、层级分布等）。",
                "inputSchema": {
                    "type": "object",
                    "properties": {},
                },
            },
        ]

    def call_tool(self, name: str, args: Dict[str, Any]) -> Dict[str, Any]:
        tool_map = {
            "m5.memory_store": self._call_memory_store,
            "m5.memory_recall": self._call_memory_recall,
            "m5.memory_search": self._call_memory_search,
            "m5.memory_stats": self._call_memory_stats,
        }
        handler = tool_map.get(name)
        if not handler:
            raise ValueError(f"未知的 M5 工具: {name}")
        result = handler(args)
        return self._wrap_result(result)

    def _call_memory_store(self, args: Dict[str, Any]) -> Any:
        content = args.get("content", "")
        if not content:
            raise ValueError("content 为必填参数")
        return self._request_m5(
            method="POST",
            path="/api/v1/memory/store",
            json={
                "content": content,
                "domain": args.get("domain", "private"),
                "agent_id": "mcp",
                "tags": args.get("tags", []),
                "source": args.get("source", "mcp"),
                "metadata": args.get("metadata", {}),
            },
        )

    def _call_memory_recall(self, args: Dict[str, Any]) -> Any:
        query = args.get("query", "")
        if not query:
            raise ValueError("query 为必填参数")
        return self._request_m5(
            method="POST",
            path="/api/v1/memory/recall",
            json={
                "query": query,
                "top_k": args.get("top_k", 5),
                "layers": args.get("layers", ["l1_shallow", "l2_deep"]),
                "domain": args.get("domain", "private"),
                "agent_id": "mcp",
            },
        )

    def _call_memory_search(self, args: Dict[str, Any]) -> Any:
        query = args.get("query", "")
        if not query:
            raise ValueError("query 为必填参数")
        return self._request_m5(
            method="POST",
            path="/api/v1/memory/search",
            json={
                "query": query,
                "top_k": args.get("top_k", 10),
                "layers": ["l1_shallow", "l2_deep"],
                "domain": args.get("domain", "private"),
                "agent_id": "mcp",
            },
        )

    def _call_memory_stats(self, args: Dict[str, Any]) -> Any:
        return self._request_m5(
            method="GET",
            path="/api/v1/memory/stats",
        )

    def _request_m5(
        self,
        method: str,
        path: str,
        json: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        url = f"{self.m5_base_url}{path}"
        try:
            with httpx.Client(timeout=10.0) as client:
                response = client.request(method=method, url=url, json=json)
                response.raise_for_status()
                return response.json()
        except httpx.HTTPStatusError as e:
            detail = ""
            try:
                detail = e.response.json().get("detail", e.response.text)
            except Exception:
                detail = e.response.text or str(e)
            raise RuntimeError(f"M5 API 调用失败（{e.response.status_code}）: {detail}") from e
        except httpx.HTTPError as e:
            raise RuntimeError(f"M5 API 网络错误: {e}") from e
