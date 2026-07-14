"""M11 MCP Bus - M4 场景引擎适配器.

将 M4 场景引擎的代码生成、场景识别、场景切换能力封装为 MCP 工具服务。
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

import httpx

from .base import BaseMcpAdapter


class M4SceneAdapter(BaseMcpAdapter):
    """M4 场景引擎 MCP 适配器.

    提供的 MCP 工具：
    - m4.code_generate: AI 代码生成
    - m4.scene_recognize: 场景识别
    - m4.scene_switch: 场景切换
    - m4.scene_list: 获取场景列表
    """

    adapter_name: str = "m4"
    adapter_description: str = "M4 场景引擎 - AI 代码生成、场景识别与切换"

    def __init__(
        self,
        m4_base_url: str = "http://localhost:8004",
        bus_url: str = "http://localhost:8011",
        server_endpoint: Optional[str] = None,
    ) -> None:
        super().__init__(
            bus_url=bus_url,
            server_name="m4",
            server_endpoint=server_endpoint,
        )
        self.m4_base_url = m4_base_url.rstrip("/")

    def get_tools(self) -> List[Dict[str, Any]]:
        return [
            {
                "name": "m4.code_generate",
                "description": "AI 代码生成。根据自然语言描述生成指定编程语言的代码，支持生成、审查、调试、优化、重构、解释、测试等操作。",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "prompt": {
                            "type": "string",
                            "description": "代码需求描述，如'写一个快速排序函数'",
                        },
                        "language": {
                            "type": "string",
                            "description": "编程语言，如 python、javascript、java、go、rust 等",
                            "default": "python",
                        },
                        "operation_type": {
                            "type": "string",
                            "description": "操作类型：generate(生成)/review(审查)/debug(调试)/optimize(优化)/refactor(重构)/explain(解释)/test(测试)",
                            "default": "generate",
                        },
                    },
                    "required": ["prompt"],
                },
            },
            {
                "name": "m4.scene_recognize",
                "description": "场景识别。根据用户输入判断当前场景（工作开发、学业规划、复盘总结、人际关系、情感陪伴、生活管理）。",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "text": {
                            "type": "string",
                            "description": "用户输入文本",
                        },
                    },
                    "required": ["text"],
                },
            },
            {
                "name": "m4.scene_switch",
                "description": "场景切换。切换到指定的场景模式。",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "scene_id": {
                            "type": "string",
                            "description": "场景 ID：work_dev(工作开发)/study(学业规划)/review(复盘总结)/social(人际关系)/emotional(情感陪伴)/life(生活管理)",
                        },
                    },
                    "required": ["scene_id"],
                },
            },
            {
                "name": "m4.scene_list",
                "description": "获取 M4 支持的所有场景列表。",
                "inputSchema": {
                    "type": "object",
                    "properties": {},
                },
            },
        ]

    def call_tool(self, name: str, args: Dict[str, Any]) -> Dict[str, Any]:
        tool_map = {
            "m4.code_generate": self._call_code_generate,
            "m4.scene_recognize": self._call_scene_recognize,
            "m4.scene_switch": self._call_scene_switch,
            "m4.scene_list": self._call_scene_list,
        }
        handler = tool_map.get(name)
        if not handler:
            raise ValueError(f"未知的 M4 工具: {name}")
        result = handler(args)
        return self._wrap_result(result)

    def _call_code_generate(self, args: Dict[str, Any]) -> Any:
        prompt = args.get("prompt", "")
        if not prompt:
            raise ValueError("prompt 为必填参数")
        return self._request_m4(
            method="POST",
            path="/api/v1/work-dev/code/generate",
            json={
                "prompt": prompt,
                "language": args.get("language", "python"),
                "operation_type": args.get("operation_type", "generate"),
            },
        )

    def _call_scene_recognize(self, args: Dict[str, Any]) -> Any:
        text = args.get("text", "")
        if not text:
            raise ValueError("text 为必填参数")
        return self._request_m4(
            method="POST",
            path="/api/v1/scene/recognize",
            json={"text": text},
        )

    def _call_scene_switch(self, args: Dict[str, Any]) -> Any:
        scene_id = args.get("scene_id", "")
        if not scene_id:
            raise ValueError("scene_id 为必填参数")
        return self._request_m4(
            method="POST",
            path="/api/v1/scene/switch",
            json={"scene_id": scene_id},
        )

    def _call_scene_list(self, args: Dict[str, Any]) -> Any:
        return self._request_m4(
            method="GET",
            path="/api/v1/scene/list",
        )

    def _request_m4(
        self,
        method: str,
        path: str,
        json: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        url = f"{self.m4_base_url}{path}"
        try:
            with httpx.Client(timeout=60.0) as client:
                response = client.request(method=method, url=url, json=json)
                response.raise_for_status()
                return response.json()
        except httpx.HTTPStatusError as e:
            detail = ""
            try:
                detail = e.response.json().get("detail", e.response.text)
            except Exception:
                detail = e.response.text or str(e)
            raise RuntimeError(f"M4 API 调用失败（{e.response.status_code}）: {detail}") from e
        except httpx.HTTPError as e:
            raise RuntimeError(f"M4 API 网络错误: {e}") from e
