"""M11 MCP Bus - M1 多Agent调度中心适配器.

将 M1 多Agent调度中心的任务管理、Agent 管理、消息总线、
分身池、联邦决策与隐私扫描能力封装为 MCP 工具服务。
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

import httpx

from .base import BaseMcpAdapter


class M1AgentAdapter(BaseMcpAdapter):
    """M1 多Agent调度中心 MCP 适配器.

    提供的 MCP 工具：
    - m1.submit_task: 提交任务
    - m1.chat: 同步对话
    - m1.list_agents: 列出 Agent
    - m1.get_agent_status: 获取 Agent 状态
    - m1.list_tasks: 列出任务
    - m1.get_task_status: 获取任务状态
    - m1.bus_publish: 消息总线发布
    - m1.request_clone: 申请分身
    - m1.release_clone: 释放分身
    - m1.fed_decide: 联邦决策
    - m1.fed_invoke: 调用外部 Agent
    - m1.fed_compare: 多 Agent 对比
    - m1.privacy_scan: 隐私扫描
    """

    adapter_name: str = "m1"
    adapter_description: str = "M1 多Agent调度中心 - 任务调度、Agent管理、消息总线、分身池与联邦决策"

    def __init__(
        self,
        m1_base_url: str = "http://localhost:8001",
        bus_url: str = "http://localhost:8011",
        server_endpoint: Optional[str] = None,
    ) -> None:
        super().__init__(
            bus_url=bus_url,
            server_name="m1",
            server_endpoint=server_endpoint,
        )
        self.m1_base_url = m1_base_url.rstrip("/")

    def get_tools(self) -> List[Dict[str, Any]]:
        return [
            {
                "name": "m1.submit_task",
                "description": "提交任务到 M1 调度中心。",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "task_type": {
                            "type": "string",
                            "description": "任务类型",
                        },
                        "payload": {
                            "type": "object",
                            "description": "任务负载内容",
                        },
                        "priority": {
                            "type": "integer",
                            "description": "任务优先级（可选）",
                        },
                    },
                    "required": ["task_type"],
                },
            },
            {
                "name": "m1.chat",
                "description": "与 M1 进行同步对话。",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "message": {
                            "type": "string",
                            "description": "对话消息内容",
                        },
                        "agent_id": {
                            "type": "string",
                            "description": "目标 Agent ID（可选）",
                        },
                        "context": {
                            "type": "object",
                            "description": "对话上下文（可选）",
                        },
                    },
                    "required": ["message"],
                },
            },
            {
                "name": "m1.list_agents",
                "description": "列出 M1 中所有可用的 Agent。",
                "inputSchema": {
                    "type": "object",
                    "properties": {},
                },
            },
            {
                "name": "m1.get_agent_status",
                "description": "获取指定 Agent 的运行状态。",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "agent_id": {
                            "type": "string",
                            "description": "Agent ID",
                        },
                    },
                    "required": ["agent_id"],
                },
            },
            {
                "name": "m1.list_tasks",
                "description": "列出 M1 中的所有任务。",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "status": {
                            "type": "string",
                            "description": "按状态筛选（可选）",
                        },
                        "limit": {
                            "type": "integer",
                            "description": "返回数量上限（可选）",
                        },
                    },
                },
            },
            {
                "name": "m1.get_task_status",
                "description": "获取指定任务的执行状态。",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "task_id": {
                            "type": "string",
                            "description": "任务 ID",
                        },
                    },
                    "required": ["task_id"],
                },
            },
            {
                "name": "m1.bus_publish",
                "description": "向 M1 消息总线发布消息。",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "topic": {
                            "type": "string",
                            "description": "消息主题",
                        },
                        "message": {
                            "type": "object",
                            "description": "消息内容",
                        },
                    },
                    "required": ["topic", "message"],
                },
            },
            {
                "name": "m1.request_clone",
                "description": "向 M1 分身池申请一个 Agent 分身。",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "agent_id": {
                            "type": "string",
                            "description": "源 Agent ID",
                        },
                        "reason": {
                            "type": "string",
                            "description": "申请原因（可选）",
                        },
                    },
                    "required": ["agent_id"],
                },
            },
            {
                "name": "m1.release_clone",
                "description": "释放 M1 分身池中的一个 Agent 分身。",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "clone_id": {
                            "type": "string",
                            "description": "分身 ID",
                        },
                    },
                    "required": ["clone_id"],
                },
            },
            {
                "name": "m1.fed_decide",
                "description": "通过 M1 联邦机制进行多 Agent 决策。",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "query": {
                            "type": "string",
                            "description": "决策查询内容",
                        },
                        "candidates": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "参与决策的 Agent ID 列表",
                        },
                    },
                    "required": ["query"],
                },
            },
            {
                "name": "m1.fed_invoke",
                "description": "通过 M1 联邦机制调用外部 Agent。",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "target_agent": {
                            "type": "string",
                            "description": "目标 Agent ID",
                        },
                        "method": {
                            "type": "string",
                            "description": "调用方法名",
                        },
                        "params": {
                            "type": "object",
                            "description": "调用参数（可选）",
                        },
                    },
                    "required": ["target_agent", "method"],
                },
            },
            {
                "name": "m1.fed_compare",
                "description": "通过 M1 联邦机制对多个 Agent 进行对比评估。",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "query": {
                            "type": "string",
                            "description": "对比查询内容",
                        },
                        "agents": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "参与对比的 Agent ID 列表",
                        },
                    },
                    "required": ["query", "agents"],
                },
            },
            {
                "name": "m1.privacy_scan",
                "description": "通过 M1 联邦隐私机制对数据进行隐私扫描。",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "data": {
                            "type": "object",
                            "description": "待扫描的数据",
                        },
                        "scan_level": {
                            "type": "string",
                            "description": "扫描级别（可选）",
                        },
                    },
                    "required": ["data"],
                },
            },
        ]

    def call_tool(self, name: str, args: Dict[str, Any]) -> Dict[str, Any]:
        tool_map = {
            "m1.submit_task": self._call_submit_task,
            "m1.chat": self._call_chat,
            "m1.list_agents": self._call_list_agents,
            "m1.get_agent_status": self._call_get_agent_status,
            "m1.list_tasks": self._call_list_tasks,
            "m1.get_task_status": self._call_get_task_status,
            "m1.bus_publish": self._call_bus_publish,
            "m1.request_clone": self._call_request_clone,
            "m1.release_clone": self._call_release_clone,
            "m1.fed_decide": self._call_fed_decide,
            "m1.fed_invoke": self._call_fed_invoke,
            "m1.fed_compare": self._call_fed_compare,
            "m1.privacy_scan": self._call_privacy_scan,
        }
        handler = tool_map.get(name)
        if not handler:
            raise ValueError(f"未知的 M1 工具: {name}")
        result = handler(args)
        return self._wrap_result(result)

    # ---- 工具调用实现 ----

    def _call_submit_task(self, args: Dict[str, Any]) -> Any:
        task_type = args.get("task_type", "")
        if not task_type:
            raise ValueError("task_type 为必填参数")
        payload = args.get("payload", {})
        priority = args.get("priority")
        body: Dict[str, Any] = {"task_type": task_type, "payload": payload}
        if priority is not None:
            body["priority"] = priority
        return self._request_m1(method="POST", path="/api/v1/tasks/submit", json=body)

    def _call_chat(self, args: Dict[str, Any]) -> Any:
        message = args.get("message", "")
        if not message:
            raise ValueError("message 为必填参数")
        body: Dict[str, Any] = {"message": message}
        if args.get("agent_id"):
            body["agent_id"] = args["agent_id"]
        if args.get("context"):
            body["context"] = args["context"]
        return self._request_m1(method="POST", path="/api/v1/chat", json=body)

    def _call_list_agents(self, args: Dict[str, Any]) -> Any:
        return self._request_m1(method="GET", path="/agents")

    def _call_get_agent_status(self, args: Dict[str, Any]) -> Any:
        agent_id = args.get("agent_id", "")
        if not agent_id:
            raise ValueError("agent_id 为必填参数")
        return self._request_m1(
            method="GET",
            path=f"/api/v1/agents/{agent_id}/status",
        )

    def _call_list_tasks(self, args: Dict[str, Any]) -> Any:
        params: Dict[str, Any] = {}
        if args.get("status"):
            params["status"] = args["status"]
        if args.get("limit") is not None:
            params["limit"] = args["limit"]
        return self._request_m1(method="GET", path="/api/v1/tasks", params=params)

    def _call_get_task_status(self, args: Dict[str, Any]) -> Any:
        task_id = args.get("task_id", "")
        if not task_id:
            raise ValueError("task_id 为必填参数")
        return self._request_m1(
            method="GET",
            path=f"/api/v1/tasks/{task_id}/status",
        )

    def _call_bus_publish(self, args: Dict[str, Any]) -> Any:
        topic = args.get("topic", "")
        message = args.get("message")
        if not topic:
            raise ValueError("topic 为必填参数")
        if message is None:
            raise ValueError("message 为必填参数")
        return self._request_m1(
            method="POST",
            path="/api/v1/bus/publish",
            json={"topic": topic, "message": message},
        )

    def _call_request_clone(self, args: Dict[str, Any]) -> Any:
        agent_id = args.get("agent_id", "")
        if not agent_id:
            raise ValueError("agent_id 为必填参数")
        body: Dict[str, Any] = {"agent_id": agent_id}
        if args.get("reason"):
            body["reason"] = args["reason"]
        return self._request_m1(method="POST", path="/v1/pool/request", json=body)

    def _call_release_clone(self, args: Dict[str, Any]) -> Any:
        clone_id = args.get("clone_id", "")
        if not clone_id:
            raise ValueError("clone_id 为必填参数")
        return self._request_m1(
            method="POST",
            path="/v1/pool/release",
            json={"clone_id": clone_id},
        )

    def _call_fed_decide(self, args: Dict[str, Any]) -> Any:
        query = args.get("query", "")
        if not query:
            raise ValueError("query 为必填参数")
        body: Dict[str, Any] = {"query": query}
        if args.get("candidates"):
            body["candidates"] = args["candidates"]
        return self._request_m1(method="POST", path="/v1/federation/decide", json=body)

    def _call_fed_invoke(self, args: Dict[str, Any]) -> Any:
        target_agent = args.get("target_agent", "")
        method = args.get("method", "")
        if not target_agent:
            raise ValueError("target_agent 为必填参数")
        if not method:
            raise ValueError("method 为必填参数")
        body: Dict[str, Any] = {"target_agent": target_agent, "method": method}
        if args.get("params"):
            body["params"] = args["params"]
        return self._request_m1(method="POST", path="/v1/federation/invoke", json=body)

    def _call_fed_compare(self, args: Dict[str, Any]) -> Any:
        query = args.get("query", "")
        agents = args.get("agents")
        if not query:
            raise ValueError("query 为必填参数")
        if not agents:
            raise ValueError("agents 为必填参数")
        return self._request_m1(
            method="POST",
            path="/v1/federation/compare",
            json={"query": query, "agents": agents},
        )

    def _call_privacy_scan(self, args: Dict[str, Any]) -> Any:
        data = args.get("data")
        if data is None:
            raise ValueError("data 为必填参数")
        body: Dict[str, Any] = {"data": data}
        if args.get("scan_level"):
            body["scan_level"] = args["scan_level"]
        return self._request_m1(
            method="POST",
            path="/v1/federation/privacy/scan",
            json=body,
        )

    # ---- HTTP 请求封装 ----

    def _request_m1(
        self,
        method: str,
        path: str,
        json: Optional[Dict[str, Any]] = None,
        params: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        url = f"{self.m1_base_url}{path}"
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
            raise RuntimeError(f"M1 API 调用失败（{e.response.status_code}）: {detail}") from e
        except httpx.HTTPError as e:
            raise RuntimeError(f"M1 API 网络错误: {e}") from e