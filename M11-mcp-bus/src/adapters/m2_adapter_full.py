"""M11 MCP Bus - M2 技能集群适配器（完整封装版）.

将 M2 技能集群的核心能力直接封装为 MCP 工具服务，
所有工具统一映射到 M2 的 REST 端点 `POST /api/v1/skills/invoke`。

提供的 MCP 工具：
- m2.invoke_skill: 通用技能调用
- m2.translate: 文本翻译
- m2.fulltext_search: 全文搜索
- m2.doc_proc: 文档处理
- m2.data_analysis: 数据分析
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

import httpx

from .base import BaseMcpAdapter


class M2FullSkillAdapter(BaseMcpAdapter):
    """M2 技能集群 MCP 适配器（完整封装版）.

    提供的 MCP 工具：
    - m2.invoke_skill: 调用指定技能
    - m2.translate: 文本翻译
    - m2.fulltext_search: 全文搜索
    - m2.doc_proc: 文档处理
    - m2.data_analysis: 数据分析
    """

    adapter_name: str = "m2"
    adapter_description: str = "M2 技能集群 - 技能调用、翻译、全文搜索、文档处理、数据分析"

    def __init__(
        self,
        m2_base_url: str = "http://localhost:8002",
        bus_url: str = "http://localhost:8011",
        server_endpoint: Optional[str] = None,
    ) -> None:
        super().__init__(
            bus_url=bus_url,
            server_name="m2",
            server_endpoint=server_endpoint,
        )
        self.m2_base_url = m2_base_url.rstrip("/")

    def get_tools(self) -> List[Dict[str, Any]]:
        return [
            {
                "name": "m2.invoke_skill",
                "description": "调用指定的 M2 技能。需提供 skill_id、action 和可选参数。",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "skill_id": {
                            "type": "string",
                            "description": "技能 ID，如 skill.translate、skill.data_analysis",
                        },
                        "action": {
                            "type": "string",
                            "description": "技能动作，如 translate_text、search、analyze",
                        },
                        "params": {
                            "type": "object",
                            "description": "技能调用参数",
                            "default": {},
                        },
                    },
                    "required": ["skill_id", "action"],
                },
            },
            {
                "name": "m2.translate",
                "description": "文本翻译，支持多语言互译。",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "text": {
                            "type": "string",
                            "description": "待翻译的文本内容",
                        },
                        "source_lang": {
                            "type": "string",
                            "description": "源语言代码，如 zh、en、ja，auto 表示自动检测",
                            "default": "auto",
                        },
                        "target_lang": {
                            "type": "string",
                            "description": "目标语言代码，如 zh、en、ja",
                            "default": "en",
                        },
                    },
                    "required": ["text"],
                },
            },
            {
                "name": "m2.fulltext_search",
                "description": "全文搜索，在指定索引中搜索相关文档。",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "query": {
                            "type": "string",
                            "description": "搜索查询语句",
                        },
                        "index_name": {
                            "type": "string",
                            "description": "索引名称",
                            "default": "default",
                        },
                    },
                    "required": ["query"],
                },
            },
            {
                "name": "m2.doc_proc",
                "description": "文档处理，包括解析、摘要、信息提取等操作。",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "document": {
                            "type": "string",
                            "description": "文档内容或文档路径",
                        },
                        "operation": {
                            "type": "string",
                            "description": "操作类型：parse(解析)/summarize(摘要)/extract(提取)",
                            "default": "parse",
                        },
                    },
                    "required": ["document"],
                },
            },
            {
                "name": "m2.data_analysis",
                "description": "数据分析，对提供的数据执行统计、趋势、关联等分析。",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "data": {
                            "description": "待分析的数据，可以是列表、字典或表格数据",
                        },
                        "method": {
                            "type": "string",
                            "description": "分析方法：summary(汇总)/statistics(统计)/correlation(关联)/trend(趋势)",
                            "default": "summary",
                        },
                    },
                    "required": ["data"],
                },
            },
        ]

    def call_tool(self, name: str, args: Dict[str, Any]) -> Dict[str, Any]:
        tool_map = {
            "m2.invoke_skill": self._call_invoke_skill,
            "m2.translate": self._call_translate,
            "m2.fulltext_search": self._call_fulltext_search,
            "m2.doc_proc": self._call_doc_proc,
            "m2.data_analysis": self._call_data_analysis,
        }
        handler = tool_map.get(name)
        if not handler:
            raise ValueError(f"未知的 M2 工具: {name}")
        result = handler(args)
        return self._wrap_result(result)

    def _call_invoke_skill(self, args: Dict[str, Any]) -> Any:
        skill_id = args.get("skill_id", "")
        action = args.get("action", "")
        if not skill_id or not action:
            raise ValueError("skill_id 和 action 为必填参数")
        return self._request_m2(
            method="POST",
            path="/api/v1/skills/invoke",
            json={
                "skill_id": skill_id,
                "action": action,
                "params": args.get("params", {}),
            },
        )

    def _call_translate(self, args: Dict[str, Any]) -> Any:
        text = args.get("text", "")
        if not text:
            raise ValueError("text 为必填参数")
        return self._request_m2(
            method="POST",
            path="/api/v1/skills/invoke",
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

    def _call_fulltext_search(self, args: Dict[str, Any]) -> Any:
        query = args.get("query", "")
        if not query:
            raise ValueError("query 为必填参数")
        return self._request_m2(
            method="POST",
            path="/api/v1/skills/invoke",
            json={
                "skill_id": "skill.fulltext_search",
                "action": "search",
                "params": {
                    "query": query,
                    "index_name": args.get("index_name", "default"),
                },
            },
        )

    def _call_doc_proc(self, args: Dict[str, Any]) -> Any:
        document = args.get("document", "")
        if not document:
            raise ValueError("document 为必填参数")
        return self._request_m2(
            method="POST",
            path="/api/v1/skills/invoke",
            json={
                "skill_id": "skill.doc_proc",
                "action": args.get("operation", "parse"),
                "params": {
                    "document": document,
                },
            },
        )

    def _call_data_analysis(self, args: Dict[str, Any]) -> Any:
        if "data" not in args:
            raise ValueError("data 为必填参数")
        return self._request_m2(
            method="POST",
            path="/api/v1/skills/invoke",
            json={
                "skill_id": "skill.data_analysis",
                "action": "analyze",
                "params": {
                    "data": args["data"],
                    "method": args.get("method", "summary"),
                },
            },
        )

    def _request_m2(
        self,
        method: str,
        path: str,
        json: Optional[Dict[str, Any]] = None,
        params: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        url = f"{self.m2_base_url}{path}"
        try:
            with httpx.Client(timeout=30.0) as client:
                response = client.request(
                    method=method,
                    url=url,
                    json=json,
                    params=params,
                )
                response.raise_for_status()
                return response.json()
        except httpx.HTTPStatusError as e:
            detail = ""
            try:
                detail = e.response.json().get("detail", e.response.text)
            except Exception:
                detail = e.response.text or str(e)
            raise RuntimeError(f"M2 API 调用失败（{e.response.status_code}）: {detail}") from e
        except httpx.HTTPError as e:
            raise RuntimeError(f"M2 API 网络错误: {e}") from e
