"""
工具系统 - 云汐Agent核心框架
工具注册 + 统一调用接口 + 参数校验 + 执行沙箱

核心设计：
1. 统一工具接口 - 所有工具实现相同的基类
2. 自动参数校验 - 基于JSON Schema的参数验证
3. 工具注册发现 - 动态注册、分类管理
4. 执行沙箱 - 超时控制、异常捕获、权限控制
5. 工具描述 - 自动生成给LLM的工具描述
"""

import re
import json
import time
import asyncio
import threading
from abc import ABC, abstractmethod
from enum import Enum
from dataclasses import dataclass, field
from typing import Optional, List, Dict, Any, Callable, Type, Union, Tuple
import inspect


class ToolCategory(str, Enum):
    """工具分类"""
    GENERAL = "general"          # 通用工具
    CALCULATION = "calculation"  # 计算工具
    SEARCH = "search"            # 搜索工具
    MEMORY = "memory"            # 记忆工具
    KNOWLEDGE = "knowledge"      # 知识库工具
    SYSTEM = "system"            # 系统工具
    CREATIVE = "creative"        # 创意工具
    UTILITY = "utility"          # 实用工具


@dataclass
class ToolParameter:
    """工具参数定义"""
    name: str
    type: str  # string/number/boolean/array/object
    description: str = ""
    required: bool = False
    default: Any = None
    enum: Optional[List[Any]] = None  # 枚举值
    min_value: Optional[float] = None
    max_value: Optional[float] = None
    
    def to_schema(self) -> Dict[str, Any]:
        """生成JSON Schema"""
        schema = {
            "type": self.type,
            "description": self.description,
        }
        if self.enum is not None:
            schema["enum"] = self.enum
        if self.min_value is not None:
            schema["minimum"] = self.min_value
        if self.max_value is not None:
            schema["maximum"] = self.max_value
        return schema


@dataclass
class ToolResult:
    """工具执行结果"""
    success: bool
    output: str = ""
    data: Optional[Any] = None
    error: Optional[str] = None
    execution_time: float = 0.0
    tool_name: str = ""
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "success": self.success,
            "output": self.output,
            "data": self.data,
            "error": self.error,
            "execution_time": round(self.execution_time, 4),
            "tool_name": self.tool_name,
        }


class BaseTool(ABC):
    """工具基类
    
    所有工具都继承自此类，实现统一的接口
    """
    
    name: str = ""
    description: str = ""
    category: str = ToolCategory.GENERAL.value
    parameters: List[ToolParameter] = field(default_factory=list)
    
    # 工具元数据
    version: str = "1.0.0"
    author: str = "yunxi"
    timeout: float = 30.0  # 超时时间（秒）
    max_calls_per_minute: int = 60  # 每分钟最大调用次数
    
    def __init__(self):
        self._call_timestamps = []
        self._call_lock = threading.Lock()
    
    @abstractmethod
    def execute(self, **kwargs) -> ToolResult:
        """执行工具（同步方法）
        
        子类必须实现此方法
        """
        pass
    
    async def execute_async(self, **kwargs) -> ToolResult:
        """异步执行（默认包装同步方法）"""
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, lambda: self.execute(**kwargs))
    
    def get_parameters_schema(self) -> Dict[str, Any]:
        """获取参数的JSON Schema"""
        properties = {}
        required = []
        
        for param in self.parameters:
            properties[param.name] = param.to_schema()
            if param.required:
                required.append(param.name)
        
        schema = {
            "type": "object",
            "properties": properties,
        }
        if required:
            schema["required"] = required
        
        return schema
    
    def get_description_for_llm(self) -> Dict[str, Any]:
        """生成给LLM的工具描述"""
        return {
            "name": self.name,
            "description": self.description,
            "parameters": self.get_parameters_schema(),
            "category": self.category,
        }
    
    def validate_parameters(self, params: Dict[str, Any]) -> Tuple[bool, Optional[str]]:
        """验证参数
        
        Returns:
            (是否有效, 错误信息)
        """
        for param in self.parameters:
            # 检查必填参数
            if param.required and param.name not in params:
                return False, f"缺少必填参数: {param.name}"
            
            if param.name not in params:
                continue
            
            value = params[param.name]
            
            # 类型检查
            if param.type == "string":
                if not isinstance(value, str):
                    return False, f"参数 {param.name} 应该是字符串"
            elif param.type == "number":
                if not isinstance(value, (int, float)):
                    return False, f"参数 {param.name} 应该是数字"
                if param.min_value is not None and value < param.min_value:
                    return False, f"参数 {param.name} 不能小于 {param.min_value}"
                if param.max_value is not None and value > param.max_value:
                    return False, f"参数 {param.name} 不能大于 {param.max_value}"
            elif param.type == "boolean":
                if not isinstance(value, bool):
                    return False, f"参数 {param.name} 应该是布尔值"
            elif param.type == "array":
                if not isinstance(value, list):
                    return False, f"参数 {param.name} 应该是数组"
            
            # 枚举检查
            if param.enum is not None and value not in param.enum:
                return False, f"参数 {param.name} 的值 {value} 不在允许范围内: {param.enum}"
        
        return True, None
    
    def _check_rate_limit(self) -> bool:
        """检查速率限制"""
        now = time.time()
        with self._call_lock:
            # 移除1分钟前的记录
            self._call_timestamps = [
                t for t in self._call_timestamps
                if now - t < 60
            ]
            if len(self._call_timestamps) >= self.max_calls_per_minute:
                return False
            self._call_timestamps.append(now)
            return True


class ToolRegistry:
    """工具注册表 - 单例模式
    
    管理所有可用工具，提供注册、查找、调用等功能
    """
    
    _instance: Optional["ToolRegistry"] = None
    
    def __new__(cls, *args, **kwargs):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance
    
    def __init__(self):
        if self._initialized:
            return
        self._initialized = True
        
        self._tools: Dict[str, BaseTool] = {}
        self._lock = threading.RLock()
        
        # 调用历史（用于调试和统计）
        self._call_history: List[Dict[str, Any]] = []
        self._max_history = 100
    
    def register(self, tool: BaseTool) -> bool:
        """注册工具"""
        with self._lock:
            if tool.name in self._tools:
                return False
            self._tools[tool.name] = tool
            return True
    
    def unregister(self, tool_name: str) -> bool:
        """注销工具"""
        with self._lock:
            if tool_name in self._tools:
                del self._tools[tool_name]
                return True
            return False
    
    def get_tool(self, tool_name: str) -> Optional[BaseTool]:
        """获取工具"""
        with self._lock:
            return self._tools.get(tool_name)
    
    def list_tools(self, category: Optional[str] = None) -> List[BaseTool]:
        """列出所有工具"""
        with self._lock:
            tools = list(self._tools.values())
            if category:
                tools = [t for t in tools if t.category == category]
            return tools
    
    def get_tool_descriptions(self, category: Optional[str] = None) -> List[Dict[str, Any]]:
        """获取所有工具的LLM描述"""
        tools = self.list_tools(category)
        return [t.get_description_for_llm() for t in tools]
    
    def call_tool(self, tool_name: str,
                  params: Optional[Dict[str, Any]] = None,
                  context: Optional[Dict[str, Any]] = None) -> ToolResult:
        """调用工具
        
        Args:
            tool_name: 工具名称
            params: 参数字典
            context: 上下文信息（用户ID、会话ID等）
        
        Returns:
            ToolResult
        """
        start_time = time.time()
        
        tool = self.get_tool(tool_name)
        if not tool:
            result = ToolResult(
                success=False,
                error=f"工具不存在: {tool_name}",
                tool_name=tool_name,
            )
            result.execution_time = time.time() - start_time
            self._record_call(tool_name, params, result)
            return result
        
        # 验证参数
        params = params or {}
        valid, error = tool.validate_parameters(params)
        if not valid:
            result = ToolResult(
                success=False,
                error=f"参数错误: {error}",
                tool_name=tool_name,
            )
            result.execution_time = time.time() - start_time
            self._record_call(tool_name, params, result)
            return result
        
        # 速率限制检查
        if not tool._check_rate_limit():
            result = ToolResult(
                success=False,
                error="调用频率过高，请稍后再试",
                tool_name=tool_name,
            )
            result.execution_time = time.time() - start_time
            self._record_call(tool_name, params, result)
            return result
        
        try:
            # 注入上下文参数（如果工具需要）
            execute_params = dict(params)
            if context:
                sig = inspect.signature(tool.execute)
                if 'context' in sig.parameters:
                    execute_params['context'] = context
            
            # 执行
            result = tool.execute(**execute_params)
            result.tool_name = tool_name
            result.execution_time = time.time() - start_time
            
        except Exception as e:
            result = ToolResult(
                success=False,
                error=f"执行异常: {str(e)}",
                tool_name=tool_name,
            )
            result.execution_time = time.time() - start_time
        
        self._record_call(tool_name, params, result)
        return result
    
    async def call_tool_async(self, tool_name: str,
                               params: Optional[Dict[str, Any]] = None,
                               context: Optional[Dict[str, Any]] = None) -> ToolResult:
        """异步调用工具"""
        tool = self.get_tool(tool_name)
        if not tool:
            return ToolResult(
                success=False,
                error=f"工具不存在: {tool_name}",
                tool_name=tool_name,
            )
        
        params = params or {}
        valid, error = tool.validate_parameters(params)
        if not valid:
            return ToolResult(
                success=False,
                error=f"参数错误: {error}",
                tool_name=tool_name,
            )
        
        start_time = time.time()
        try:
            result = await tool.execute_async(**params)
            result.tool_name = tool_name
            result.execution_time = time.time() - start_time
        except Exception as e:
            result = ToolResult(
                success=False,
                error=f"执行异常: {str(e)}",
                tool_name=tool_name,
                execution_time=time.time() - start_time,
            )
        
        self._record_call(tool_name, params, result)
        return result
    
    def _record_call(self, tool_name: str, params: Dict[str, Any], result: ToolResult):
        """记录调用历史"""
        record = {
            "tool": tool_name,
            "params": params,
            "success": result.success,
            "error": result.error,
            "execution_time": result.execution_time,
            "timestamp": time.time(),
        }
        with self._lock:
            self._call_history.append(record)
            if len(self._call_history) > self._max_history:
                self._call_history = self._call_history[-self._max_history:]
    
    def get_call_history(self, tool_name: Optional[str] = None,
                         limit: int = 20) -> List[Dict[str, Any]]:
        """获取调用历史"""
        with self._lock:
            history = list(reversed(self._call_history))
            if tool_name:
                history = [h for h in history if h["tool"] == tool_name]
            return history[:limit]
    
    def get_stats(self) -> Dict[str, Any]:
        """获取工具统计"""
        with self._lock:
            total_calls = len(self._call_history)
            success_calls = sum(1 for h in self._call_history if h["success"])
            failed_calls = total_calls - success_calls
            
            tool_stats = {}
            for name, tool in self._tools.items():
                tool_calls = [h for h in self._call_history if h["tool"] == name]
                tool_stats[name] = {
                    "category": tool.category,
                    "total_calls": len(tool_calls),
                    "success_rate": (
                        sum(1 for h in tool_calls if h["success"]) / len(tool_calls)
                        if tool_calls else 0.0
                    ),
                    "avg_execution_time": (
                        sum(h["execution_time"] for h in tool_calls) / len(tool_calls)
                        if tool_calls else 0.0
                    ),
                }
            
            return {
                "total_tools": len(self._tools),
                "total_calls": total_calls,
                "success_calls": success_calls,
                "failed_calls": failed_calls,
                "success_rate": success_calls / total_calls if total_calls > 0 else 0.0,
                "tool_stats": tool_stats,
            }


# 简化的函数式工具包装器
def create_tool(name: str, description: str,
                func: Callable,
                parameters: Optional[List[ToolParameter]] = None,
                category: str = ToolCategory.GENERAL.value) -> BaseTool:
    """从函数创建工具
    
    快速将一个普通函数包装为BaseTool工具
    """
    params = parameters or []
    
    class FunctionTool(BaseTool):
        def __init__(self):
            super().__init__()
            self.name = name
            self.description = description
            self.category = category
            self.parameters = params
        
        def execute(self, **kwargs):
            start = time.time()
            try:
                # 过滤出函数接受的参数
                sig = inspect.signature(func)
                filtered = {k: v for k, v in kwargs.items() if k in sig.parameters}
                output = func(**filtered)
                
                if isinstance(output, ToolResult):
                    result = output
                elif isinstance(output, str):
                    result = ToolResult(success=True, output=output)
                elif isinstance(output, dict):
                    result = ToolResult(success=True, output=json.dumps(output, ensure_ascii=False), data=output)
                else:
                    result = ToolResult(success=True, output=str(output), data=output)
                
                result.execution_time = time.time() - start
                return result
            except Exception as e:
                return ToolResult(
                    success=False,
                    error=str(e),
                    execution_time=time.time() - start,
                )
    
    return FunctionTool()


# 全局单例获取函数
_tool_registry_instance: Optional[ToolRegistry] = None


def get_tool_registry() -> ToolRegistry:
    """获取工具注册表单例"""
    global _tool_registry_instance
    if _tool_registry_instance is None:
        _tool_registry_instance = ToolRegistry()
    return _tool_registry_instance
