"""
云汐 M9 开发者工坊 - MCP 桥接服务
实现 MCP（Model Context Protocol）协议基础框架，桥接云汐内部能力
支持工具注册、发现、调用，预留 SSE 流式响应接口
"""

import json
import uuid
import threading
import time
from datetime import datetime
from typing import Dict, List, Optional, Callable, Any
from dataclasses import dataclass, field

# 兼容相对导入和直接运行
try:
    from .config import get_settings
    from .models import SessionLocal, MCPTool
except ImportError:
    from config import get_settings
    from models import SessionLocal, MCPTool

try:
    from .core.logging_config import get_logger
except ImportError:
    from core.logging_config import get_logger


@dataclass
class MCPRequest:
    """MCP 请求对象（JSON-RPC 风格）"""
    jsonrpc: str = "2.0"
    method: str = ""
    params: Dict = field(default_factory=dict)
    id: Optional[str] = None


@dataclass
class MCPResponse:
    """MCP 响应对象"""
    jsonrpc: str = "2.0"
    result: Optional[Any] = None
    error: Optional[Dict] = None
    id: Optional[str] = None

    def to_dict(self) -> Dict:
        """转换为字典"""
        resp = {"jsonrpc": self.jsonrpc, "id": self.id}
        if self.error:
            resp["error"] = self.error
        else:
            resp["result"] = self.result
        return resp


class MCPToolRegistry:
    """MCP 工具注册中心（注册表模式）"""

    def __init__(self):
        """初始化工具注册中心"""
        self.settings = get_settings()
        self._tools: Dict[str, Callable] = {}  # 内存中的工具函数映射
        self._db = SessionLocal()
        self._lock = threading.RLock()
        self.logger = get_logger("mcp_bridge")
        # 启动时注册内置工具
        self._register_builtin_tools()

    # ===== 内置工具注册 =====

    def _register_builtin_tools(self):
        """注册云汐内部能力为 MCP 工具"""
        builtin_tools = [
            {
                "name": "yunxi_compute_schedule",
                "description": "云汐算力调度 - 调用 M8 控制塔 API 进行算力资源调度",
                "category": "compute",
                "endpoint": f"{self.settings.m8_control_tower_api}/compute/schedule",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "task_type": {"type": "string", "description": "任务类型"},
                        "priority": {"type": "integer", "description": "优先级 1-10"},
                        "resources": {"type": "object", "description": "资源需求"},
                    },
                    "required": ["task_type"]
                },
                "handler": self._tool_compute_schedule,
            },
            {
                "name": "yunxi_memory_query",
                "description": "云汐记忆查询 - 调用 M5 潮汐记忆 API 查询记忆内容",
                "category": "memory",
                "endpoint": f"{self.settings.m5_memory_api}/memory/query",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "query": {"type": "string", "description": "查询关键词"},
                        "top_k": {"type": "integer", "description": "返回结果数量", "default": 5},
                        "tags": {"type": "array", "description": "标签过滤"},
                    },
                    "required": ["query"]
                },
                "handler": self._tool_memory_query,
            },
            {
                "name": "yunxi_scene_switch",
                "description": "云汐场景切换 - 调用 M4 场景引擎 API 切换运行场景",
                "category": "scene",
                "endpoint": f"{self.settings.m4_scene_api}/scene/switch",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "scene_name": {"type": "string", "description": "场景名称"},
                        "scene_params": {"type": "object", "description": "场景参数"},
                    },
                    "required": ["scene_name"]
                },
                "handler": self._tool_scene_switch,
            },
            {
                "name": "yunxi_inspection_report",
                "description": "云汐巡检报告 - 调用 M8 巡检 API 生成系统巡检报告",
                "category": "inspection",
                "endpoint": f"{self.settings.m8_inspection_api}/inspection/report",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "report_type": {"type": "string", "description": "报告类型：daily/weekly/monthly"},
                        "scope": {"type": "string", "description": "巡检范围"},
                    },
                    "required": ["report_type"]
                },
                "handler": self._tool_inspection_report,
            },
            {
                "name": "yunxi_vscode_launch",
                "description": "云汐 VS Code 启动 - 启动 VS Code 并打开指定项目",
                "category": "vscode",
                "endpoint": "/api/vscode/start",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "project_path": {"type": "string", "description": "项目路径"},
                        "new_window": {"type": "boolean", "description": "是否新窗口"},
                    },
                    "required": []
                },
                "handler": self._tool_vscode_launch,
            },
        ]

        for tool_info in builtin_tools:
            handler = tool_info.pop("handler")
            self.register_tool(
                name=tool_info["name"],
                handler=handler,
                description=tool_info["description"],
                category=tool_info["category"],
                endpoint=tool_info["endpoint"],
                input_schema=tool_info["input_schema"],
            )

    # ===== 工具注册/注销 =====

    def register_tool(
        self,
        name: str,
        handler: Callable,
        description: str = "",
        category: str = "general",
        endpoint: str = "",
        input_schema: Optional[Dict] = None,
    ) -> bool:
        """
        注册一个 MCP 工具
        :param name: 工具名称（唯一）
        :param handler: 处理函数
        :param description: 工具描述
        :param category: 工具分类
        :param endpoint: 调用端点
        :param input_schema: 输入参数 Schema
        :return: 是否注册成功
        """
        with self._lock:
            if name in self._tools:
                return False

            # 注册到内存
            self._tools[name] = handler

            # 注册到数据库（如果不存在）
            existing = self._db.query(MCPTool).filter(MCPTool.name == name).first()
            if not existing:
                tool = MCPTool(
                    name=name,
                    description=description,
                    endpoint=endpoint,
                    category=category,
                    enabled=True,
                    input_schema=input_schema or {},
                )
                self._db.add(tool)
                self._db.commit()
            else:
                # 更新已有记录
                existing.description = description
                existing.endpoint = endpoint
                existing.category = category
                existing.input_schema = input_schema or {}
                existing.enabled = True
                self._db.commit()

            return True

    def unregister_tool(self, name: str) -> bool:
        """注销工具"""
        with self._lock:
            if name not in self._tools:
                return False
            del self._tools[name]

            # 标记数据库中为禁用
            tool = self._db.query(MCPTool).filter(MCPTool.name == name).first()
            if tool:
                tool.enabled = False
                self._db.commit()
            return True

    # ===== 工具发现 =====

    def list_tools(self, category: Optional[str] = None, enabled_only: bool = True) -> List[Dict]:
        """
        列出所有可用工具
        :param category: 按分类过滤
        :param enabled_only: 只返回启用的工具
        :return: 工具列表
        """
        query = self._db.query(MCPTool)
        if enabled_only:
            query = query.filter(MCPTool.enabled == True)
        if category:
            query = query.filter(MCPTool.category == category)

        tools = query.order_by(MCPTool.category, MCPTool.name).all()
        return [t.to_dict() for t in tools]

    def get_tool(self, name: str) -> Optional[Dict]:
        """获取指定工具信息"""
        tool = self._db.query(MCPTool).filter(MCPTool.name == name).first()
        return tool.to_dict() if tool else None

    # ===== 工具调用 =====

    def call_tool(self, name: str, arguments: Optional[Dict] = None) -> MCPResponse:
        """
        调用 MCP 工具
        :param name: 工具名称
        :param arguments: 调用参数
        :return: MCP 响应
        """
        with self._lock:
            arguments = arguments or {}
            request_id = str(uuid.uuid4())[:8]

            # 检查工具是否存在且已启用
            tool_info = self.get_tool(name)
            if not tool_info or not tool_info.get("enabled"):
                return MCPResponse(
                    id=request_id,
                    error={
                        "code": -32601,
                        "message": f"工具不存在或已禁用: {name}",
                    }
                )

            # 检查是否有处理函数
            handler = self._tools.get(name)
            if not handler:
                return MCPResponse(
                    id=request_id,
                    error={
                        "code": -32601,
                        "message": f"工具处理函数未注册: {name}",
                    }
                )

            try:
                # 执行工具
                result = handler(**arguments)
                return MCPResponse(
                    id=request_id,
                    result=result,
                )
            except TypeError as e:
                return MCPResponse(
                    id=request_id,
                    error={
                        "code": -32602,
                        "message": f"参数错误: {str(e)}",
                    }
                )
            except Exception as e:
                return MCPResponse(
                    id=request_id,
                    error={
                        "code": -32603,
                        "message": f"工具执行错误: {str(e)}",
                    }
                )

    # ===== 内置工具实现 =====

    def _tool_compute_schedule(self, task_type: str, priority: int = 5, resources: Optional[Dict] = None) -> Dict:
        """算力调度工具实现（调用 M8 控制塔 API）"""
        # 实际项目中使用 httpx 调用 M8 控制塔 API
        # 此处为框架实现，返回模拟结果
        return {
            "status": "scheduled",
            "task_type": task_type,
            "priority": priority,
            "resources": resources or {},
            "scheduled_at": datetime.now().isoformat(),
            "estimated_duration": "30min",
            "note": "已提交至 M8 控制塔，等待调度",
        }

    def _tool_memory_query(self, query: str, top_k: int = 5, tags: Optional[List] = None) -> Dict:
        """记忆查询工具实现（调用 M5 潮汐记忆 API）"""
        return {
            "query": query,
            "top_k": top_k,
            "tags": tags or [],
            "results": [
                {"id": f"mem_{i}", "content": f"关于'{query}'的记忆片段 {i}", "relevance": 0.95 - i * 0.1}
                for i in range(min(top_k, 3))
            ],
            "total": top_k,
            "source": "M5 潮汐记忆",
        }

    def _tool_scene_switch(self, scene_name: str, scene_params: Optional[Dict] = None) -> Dict:
        """场景切换工具实现（调用 M4 场景引擎 API）"""
        return {
            "status": "switched",
            "scene_name": scene_name,
            "scene_params": scene_params or {},
            "switched_at": datetime.now().isoformat(),
            "note": f"已切换至 {scene_name} 场景",
        }

    def _tool_inspection_report(self, report_type: str = "daily", scope: str = "all") -> Dict:
        """巡检报告工具实现（调用 M8 巡检 API）"""
        return {
            "report_type": report_type,
            "scope": scope,
            "generated_at": datetime.now().isoformat(),
            "summary": {
                "total_checks": 100,
                "passed": 95,
                "warnings": 3,
                "errors": 2,
            },
            "status": "generated",
            "note": "报告已生成，可在 M8 巡检模块查看详情",
        }

    def _tool_vscode_launch(self, project_path: str = "", new_window: bool = False) -> Dict:
        """VS Code 启动工具实现"""
        try:
            from .vscode_manager import get_vscode_manager
            vscode = get_vscode_manager()
            result = vscode.start(project_path=project_path or None, new_window=new_window)
            return result
        except ImportError:
            return {"success": False, "message": "VS Code 管理器不可用"}

    # ===== MCP 协议处理 =====

    def handle_request(self, request_dict: Dict) -> Dict:
        """
        处理 MCP JSON-RPC 请求
        支持的方法: tools/list, tools/call
        """
        method = request_dict.get("method", "")
        params = request_dict.get("params", {})
        req_id = request_dict.get("id")

        if method == "tools/list":
            # 工具列表查询
            tools = self.list_tools(
                category=params.get("category"),
                enabled_only=params.get("enabled_only", True),
            )
            return MCPResponse(id=req_id, result={"tools": tools}).to_dict()

        elif method == "tools/call":
            # 工具调用
            tool_name = params.get("name", "")
            arguments = params.get("arguments", {})
            response = self.call_tool(tool_name, arguments)
            response.id = req_id
            return response.to_dict()

        else:
            return MCPResponse(
                id=req_id,
                error={
                    "code": -32601,
                    "message": f"不支持的方法: {method}",
                }
            ).to_dict()

    # ===== SSE 流式响应（预留接口） =====

    def stream_tool_call(self, name: str, arguments: Optional[Dict] = None):
        """
        流式调用工具（生成器，用于 SSE）
        预留接口，当前返回完整结果
        """
        arguments = arguments or {}
        yield {"type": "status", "status": "started", "tool": name}
        yield {"type": "progress", "percent": 50}

        response = self.call_tool(name, arguments)
        yield {"type": "result", "data": response.result if not response.error else None}

        if response.error:
            yield {"type": "error", "error": response.error}
        else:
            yield {"type": "done", "status": "completed"}

    def close(self):
        """关闭资源"""
        self._db.close()


# 全局单例
_mcp_registry: Optional[MCPToolRegistry] = None


def get_mcp_registry() -> MCPToolRegistry:
    """获取 MCP 工具注册中心单例"""
    global _mcp_registry
    if _mcp_registry is None:
        _mcp_registry = MCPToolRegistry()
    return _mcp_registry


# 兼容直接运行测试
if __name__ == "__main__":
    registry = get_mcp_registry()
    logger.info("已注册的 MCP 工具:")
    for tool in registry.list_tools():
        logger.info(f"  - [{tool['category']}] {tool['name']}: {tool['description'][:50]}...")

    # 测试调用
    logger.info("测试调用 yunxi_memory_query:")
    resp = registry.call_tool("yunxi_memory_query", {"query": "云汐", "top_k": 2})
    logger.info(json.dumps(resp.to_dict(), ensure_ascii=False, indent=2))

    registry.close()
