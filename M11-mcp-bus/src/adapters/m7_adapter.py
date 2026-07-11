"""M11 MCP Bus - M7 积木平台适配器.

将 M7 积木平台的工作流和积木块封装为标准 MCP 工具服务，
注册到 M11 总线，供其他模块调用。
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

import httpx

from .base import BaseMcpAdapter


class M7BlockAdapter(BaseMcpAdapter):
    """M7 积木平台 MCP 适配器.

    将 M7 积木平台的工作流管理、运行、积木块列表等能力
    封装为 MCP 标准工具，注册到 M11 总线。

    提供的 MCP 工具：
    - m7.list_workflows: 获取工作流列表
    - m7.get_workflow: 获取工作流详情
    - m7.run_workflow: 运行工作流
    - m7.get_run_status: 获取运行状态
    - m7.list_blocks: 获取积木块列表
    """

    adapter_name: str = "m7"
    adapter_description: str = "M7 积木平台 - 工作流管理、运行、积木块库"

    def __init__(
        self,
        m7_base_url: str = "http://localhost:8007",
        bus_url: str = "http://localhost:8011",
        server_endpoint: Optional[str] = None,
    ) -> None:
        """初始化 M7 适配器.

        Args:
            m7_base_url: M7 积木平台服务地址
            bus_url: M11 总线地址
            server_endpoint: 本适配器的 MCP 端点地址
        """
        super().__init__(
            bus_url=bus_url,
            server_name="m7",
            server_endpoint=server_endpoint,
        )

        self.m7_base_url = m7_base_url.rstrip("/")

    # ============================================================
    # 工具列表
    # ============================================================

    def get_tools(self) -> List[Dict[str, Any]]:
        """获取 M7 工具列表.

        Returns:
            MCP 标准格式的工具列表
        """
        return [
            {
                "name": "m7.list_workflows",
                "description": "获取 M7 工作流列表，支持按分类、关键词筛选和分页",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "category": {
                            "type": "string",
                            "description": "工作流分类筛选",
                        },
                        "keyword": {
                            "type": "string",
                            "description": "关键词搜索（名称或描述）",
                        },
                        "page": {
                            "type": "integer",
                            "description": "页码，从 1 开始",
                            "default": 1,
                            "minimum": 1,
                        },
                        "page_size": {
                            "type": "integer",
                            "description": "每页数量",
                            "default": 20,
                            "minimum": 1,
                            "maximum": 100,
                        },
                    },
                },
            },
            {
                "name": "m7.get_workflow",
                "description": "获取指定工作流的详细信息，包括节点配置和连线关系",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "workflow_id": {
                            "type": "string",
                            "description": "工作流 ID",
                        },
                    },
                    "required": ["workflow_id"],
                },
            },
            {
                "name": "m7.run_workflow",
                "description": "运行指定的工作流，传入变量参数，返回运行结果和 run_id",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "workflow_id": {
                            "type": "string",
                            "description": "工作流 ID",
                        },
                        "variables": {
                            "type": "object",
                            "description": "工作流输入变量，键值对形式",
                            "default": {},
                        },
                    },
                    "required": ["workflow_id"],
                },
            },
            {
                "name": "m7.get_run_status",
                "description": "获取工作流运行状态和结果，支持轮询查询异步运行的工作流",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "workflow_id": {
                            "type": "string",
                            "description": "工作流 ID",
                        },
                        "run_id": {
                            "type": "string",
                            "description": "运行实例 ID",
                        },
                    },
                    "required": ["workflow_id", "run_id"],
                },
            },
            {
                "name": "m7.list_blocks",
                "description": "获取 M7 积木块列表，即可以在工作流中使用的节点类型",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "category": {
                            "type": "string",
                            "description": "积木块分类筛选，如 input、output、logic、data 等",
                        },
                    },
                },
            },
        ]

    # ============================================================
    # 工具调用
    # ============================================================

    def call_tool(self, name: str, args: Dict[str, Any]) -> Dict[str, Any]:
        """调用 M7 工具.

        根据工具名调用对应的 M7 REST API。

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
            "m7.list_workflows": self._call_list_workflows,
            "m7.get_workflow": self._call_get_workflow,
            "m7.run_workflow": self._call_run_workflow,
            "m7.get_run_status": self._call_get_run_status,
            "m7.list_blocks": self._call_list_blocks,
        }

        handler = tool_map.get(name)
        if not handler:
            raise ValueError(f"未知的 M7 工具: {name}")

        result = handler(args)
        return self._wrap_result(result)

    # ============================================================
    # 各工具的 REST API 实现
    # ============================================================

    def _call_list_workflows(self, args: Dict[str, Any]) -> Any:
        """处理 list_workflows 工具：获取工作流列表.

        Args:
            args: 工具参数（category, keyword, page, page_size）

        Returns:
            工作流列表数据
        """
        params: Dict[str, Any] = {}
        if args.get("category"):
            params["category"] = args["category"]
        if args.get("keyword"):
            params["keyword"] = args["keyword"]

        page = args.get("page", 1)
        page_size = args.get("page_size", 20)
        params["page"] = page
        params["page_size"] = page_size

        return self._request_m7(
            method="GET",
            path="/api/v1/workflows",
            params=params,
        )

    def _call_get_workflow(self, args: Dict[str, Any]) -> Any:
        """处理 get_workflow 工具：获取工作流详情.

        Args:
            args: 工具参数（workflow_id）

        Returns:
            工作流详情数据
        """
        workflow_id = args.get("workflow_id", "")
        if not workflow_id:
            raise ValueError("workflow_id 为必填参数")

        return self._request_m7(
            method="GET",
            path=f"/api/v1/workflows/{workflow_id}",
        )

    def _call_run_workflow(self, args: Dict[str, Any]) -> Any:
        """处理 run_workflow 工具：运行工作流.

        Args:
            args: 工具参数（workflow_id, variables）

        Returns:
            运行结果数据（包含 run_id、状态、输出等）
        """
        workflow_id = args.get("workflow_id", "")
        if not workflow_id:
            raise ValueError("workflow_id 为必填参数")

        variables = args.get("variables", {})

        return self._request_m7(
            method="POST",
            path=f"/api/v1/workflows/{workflow_id}/run",
            json={"variables": variables},
            timeout=60.0,
        )

    def _call_get_run_status(self, args: Dict[str, Any]) -> Any:
        """处理 get_run_status 工具：获取运行状态.

        Args:
            args: 工具参数（workflow_id, run_id）

        Returns:
            运行状态和结果数据
        """
        workflow_id = args.get("workflow_id", "")
        run_id = args.get("run_id", "")

        if not workflow_id or not run_id:
            raise ValueError("workflow_id 和 run_id 均为必填参数")

        # 从运行历史中查找指定 run_id
        runs_data = self._request_m7(
            method="GET",
            path=f"/api/v1/workflows/{workflow_id}/runs",
        )

        # 尝试从列表中找到对应的 run
        runs = runs_data.get("items", runs_data.get("runs", []))
        if isinstance(runs_data, list):
            runs = runs_data

        target_run = None
        for run in runs:
            if str(run.get("id", "")) == str(run_id) or str(run.get("run_id", "")) == str(run_id):
                target_run = run
                break

        if target_run is not None:
            return target_run

        # 如果没找到，返回整个运行历史供调用方参考
        return {
            "warning": f"未找到 run_id={run_id} 的运行记录",
            "workflow_id": workflow_id,
            "run_id": run_id,
            "recent_runs": runs[:10],
        }

    def _call_list_blocks(self, args: Dict[str, Any]) -> Any:
        """处理 list_blocks 工具：获取积木块列表.

        Args:
            args: 工具参数（category）

        Returns:
            积木块列表数据
        """
        params: Dict[str, Any] = {}
        if args.get("category"):
            params["category"] = args["category"]

        return self._request_m7(
            method="GET",
            path="/api/v1/blocks",
            params=params,
        )

    # ============================================================
    # M7 API 调用封装
    # ============================================================

    def _request_m7(
        self,
        method: str,
        path: str,
        json: Optional[Dict[str, Any]] = None,
        params: Optional[Dict[str, Any]] = None,
        timeout: float = 30.0,
    ) -> Dict[str, Any]:
        """调用 M7 积木平台 API.

        Args:
            method: HTTP 方法（GET/POST 等）
            path: API 路径
            json: 请求体 JSON 数据
            params: URL 查询参数
            timeout: 请求超时时间（秒）

        Returns:
            API 响应数据

        Raises:
            RuntimeError: 请求失败时抛出
        """
        url = f"{self.m7_base_url}{path}"

        headers = {"Content-Type": "application/json"}

        try:
            with httpx.Client(timeout=timeout) as client:
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
            raise RuntimeError(f"M7 积木平台 API 调用失败（{e.response.status_code}）: {detail}") from e
        except httpx.HTTPError as e:
            raise RuntimeError(f"M7 积木平台 API 网络错误: {e}") from e
        except Exception as e:
            raise RuntimeError(f"M7 积木平台 API 调用异常: {e}") from e

    # ============================================================
    # 健康检查
    # ============================================================

    def check_m7_health(self) -> Dict[str, Any]:
        """检查 M7 服务健康状态.

        Returns:
            健康状态信息
        """
        try:
            with httpx.Client(timeout=3.0) as client:
                response = client.get(f"{self.m7_base_url}/health")
                response.raise_for_status()
                return {
                    "status": "healthy",
                    "m7_status": response.json(),
                }
        except Exception as e:
            return {
                "status": "unhealthy",
                "error": str(e),
            }
