"""M11 MCP Bus - MCP 积木执行器.

供 M7 积木平台调用执行 MCP 积木的执行器。
本质上是 M11 总线的客户端封装，将 MCP 工具调用
转换为 M7 积木执行的标准结果格式。

支持同步执行、批量执行、流式输出等特性。
"""

from __future__ import annotations

import asyncio
import json
import time
from typing import Any, AsyncGenerator, Dict, List, Optional

import httpx

from ..sdk.mcp_bus_client import McpBusClient


class McpBlockExecutor:
    """MCP 积木执行器.

    供 M7 等消费者调用执行 MCP 积木（即 M11 总线上的工具）。
    提供统一的结果格式，与 M7 积木执行结果格式一致。

    每个 MCP 工具对应一个 M7 积木块，积木的输入参数
    对应工具的 inputSchema，执行逻辑就是调用 M11 总线的工具。

    示例::

        executor = McpBlockExecutor("http://localhost:8011")
        result = executor.execute_block(
            "server_name.tool_name",
            {"arg1": "value1"}
        )
    """

    # 默认超时时间（秒）
    DEFAULT_TIMEOUT = 60.0

    def __init__(
        self,
        bus_url: str = "http://localhost:8011",
        api_key: str = "",
        timeout: float = DEFAULT_TIMEOUT,
    ) -> None:
        """初始化 MCP 积木执行器.

        Args:
            bus_url: M11 总线服务地址
            api_key: API 密钥（可选）
            timeout: 默认超时时间（秒）
        """
        self._bus_url = bus_url.rstrip("/")
        self._api_key = api_key
        self._timeout = timeout
        self._client = McpBusClient(
            bus_url=bus_url,
            api_key=api_key,
            timeout=timeout,
        )
        # 积木名 -> 工具名 的映射缓存
        self._block_tool_map: Dict[str, str] = {}

    # ============================================================
    # 单积木执行
    # ============================================================

    def execute_block(
        self,
        block_name: str,
        params: Optional[Dict[str, Any]] = None,
        consumer: str = "m7-block",
    ) -> Dict[str, Any]:
        """执行一个 MCP 积木（同步）.

        调用 M11 总线上对应的工具，返回标准化的执行结果。
        结果格式与 M7 积木执行结果格式一致。

        Args:
            block_name: 积木名称（即 MCP 工具全名，格式：{server_name}.{tool_name}）
            params: 积木输入参数
            consumer: 调用方标识

        Returns:
            标准化的执行结果：
            {
                "block_name": str,       # 积木名称
                "success": bool,         # 是否成功
                "status": str,           # 状态：success / failed
                "output": Any,           # 输出结果（成功时）
                "error": str,            # 错误信息（失败时）
                "duration_ms": int,      # 执行耗时（毫秒）
                "metadata": {            # 元数据
                    "tool_name": str,    # 对应 MCP 工具名
                    "call_id": int,      # 调用记录 ID
                    "from_cache": bool,  # 是否来自缓存
                    "source": "m11-mcp", # 来源标识
                }
            }
        """
        params = params or {}
        tool_name = self._resolve_tool_name(block_name)
        start_time = time.time()

        try:
            result = self._client.call_tool(
                tool_name=tool_name,
                arguments=params,
                consumer=consumer,
            )
            duration_ms = int((time.time() - start_time) * 1000)

            success = result.get("success", False)
            return self._build_result(
                block_name=block_name,
                tool_name=tool_name,
                success=success,
                output=result.get("result"),
                error=result.get("error"),
                duration_ms=result.get("duration_ms", duration_ms),
                call_id=result.get("call_id", 0),
                from_cache=result.get("from_cache", False),
            )

        except httpx.HTTPStatusError as e:
            duration_ms = int((time.time() - start_time) * 1000)
            error_msg = f"HTTP 错误（{e.response.status_code}）"
            try:
                err_data = e.response.json()
                error_msg = err_data.get("detail", err_data.get("message", error_msg))
            except Exception:
                # JSON 解析失败，保持默认错误信息
                import logging
                logging.getLogger(__name__).debug(
                    "解析 HTTP 错误响应 JSON 失败，使用默认错误信息"
                )
            return self._build_result(
                block_name=block_name,
                tool_name=tool_name,
                success=False,
                output=None,
                error=error_msg,
                duration_ms=duration_ms,
            )

        except Exception as e:
            duration_ms = int((time.time() - start_time) * 1000)
            return self._build_result(
                block_name=block_name,
                tool_name=tool_name,
                success=False,
                output=None,
                error=str(e),
                duration_ms=duration_ms,
            )

    # ============================================================
    # 批量执行
    # ============================================================

    def batch_execute(
        self,
        blocks: List[Dict[str, Any]],
        consumer: str = "m7-batch",
    ) -> List[Dict[str, Any]]:
        """批量执行 MCP 积木.

        顺序执行多个积木，返回每个积木的执行结果。
        支持指定每个积木的参数和超时时间。

        Args:
            blocks: 积木执行列表，每项格式：
                {
                    "block_name": str,       # 积木名称
                    "params": dict,          # 输入参数（可选）
                    "timeout": float,        # 超时时间（可选）
                }
            consumer: 调用方标识

        Returns:
            执行结果列表，顺序与输入一致，每项格式同 execute_block 返回值
        """
        results = []
        for block in blocks:
            block_name = block.get("block_name", "")
            params = block.get("params", {})
            timeout = block.get("timeout")

            if timeout is not None:
                # 临时修改超时时间
                original_timeout = self._client._timeout
                self._client._client = httpx.Client(timeout=timeout)
                try:
                    result = self.execute_block(block_name, params, consumer=consumer)
                finally:
                    self._client._client = httpx.Client(timeout=original_timeout)
            else:
                result = self.execute_block(block_name, params, consumer=consumer)

            results.append(result)

        return results

    # ============================================================
    # 异步批量执行
    # ============================================================

    async def batch_execute_async(
        self,
        blocks: List[Dict[str, Any]],
        consumer: str = "m7-batch-async",
        max_concurrent: int = 5,
    ) -> List[Dict[str, Any]]:
        """异步批量执行 MCP 积木（并发）.

        使用异步方式并发执行多个积木，提高批量执行效率。

        Args:
            blocks: 积木执行列表，格式同 batch_execute
            consumer: 调用方标识
            max_concurrent: 最大并发数

        Returns:
            执行结果列表，顺序与输入一致
        """
        semaphore = asyncio.Semaphore(max_concurrent)

        async def _execute_one(block: Dict[str, Any]) -> Dict[str, Any]:
            async with semaphore:
                block_name = block.get("block_name", "")
                params = block.get("params", {})
                # 使用 run_in_executor 在后台线程中执行同步调用
                loop = asyncio.get_event_loop()
                return await loop.run_in_executor(
                    None,
                    lambda: self.execute_block(block_name, params, consumer=consumer),
                )

        tasks = [_execute_one(block) for block in blocks]
        results = await asyncio.gather(*tasks)
        return list(results)

    # ============================================================
    # 流式输出支持
    # ============================================================

    async def execute_block_stream(
        self,
        block_name: str,
        params: Optional[Dict[str, Any]] = None,
        consumer: str = "m7-stream",
    ) -> AsyncGenerator[Dict[str, Any], None]:
        """流式执行 MCP 积木（如果工具支持流式输出）.

        通过 SSE 或长连接的方式接收工具的流式输出，
        逐块 yield 给调用方。

        注意：此方法为异步生成器，需要使用 async for 迭代。

        Args:
            block_name: 积木名称
            params: 输入参数
            consumer: 调用方标识

        Yields:
            流式输出块：
            {
                "type": str,           # 块类型：chunk / complete / error
                "block_name": str,     # 积木名称
                "content": Any,        # 内容数据
                "done": bool,          # 是否完成
            }
        """
        params = params or {}
        tool_name = self._resolve_tool_name(block_name)

        # 先尝试同步调用，如果工具支持流式输出再走流式路径
        # 简化实现：先同步调用，完成后一次性返回
        # 生产环境可接入 SSE 或 WebSocket 实现真正的流式输出
        try:
            result = self._client.call_tool(
                tool_name=tool_name,
                arguments=params,
                consumer=consumer,
            )

            output = result.get("result")
            if isinstance(output, str):
                # 对字符串结果模拟流式输出，逐字返回
                chunk_size = 50
                for i in range(0, len(output), chunk_size):
                    chunk = output[i : i + chunk_size]
                    yield {
                        "type": "chunk",
                        "block_name": block_name,
                        "content": chunk,
                        "done": False,
                    }
                    await asyncio.sleep(0.01)
            else:
                # 非字符串结果直接返回一块
                yield {
                    "type": "chunk",
                    "block_name": block_name,
                    "content": output,
                    "done": False,
                }

            yield {
                "type": "complete",
                "block_name": block_name,
                "content": None,
                "done": True,
            }

        except Exception as e:
            yield {
                "type": "error",
                "block_name": block_name,
                "content": str(e),
                "done": True,
            }

    # ============================================================
    # 积木信息查询
    # ============================================================

    def get_block_info(self, block_name: str) -> Optional[Dict[str, Any]]:
        """获取积木（MCP 工具）详情.

        Args:
            block_name: 积木名称

        Returns:
            积木详情字典，不存在则返回 None
        """
        tool_name = self._resolve_tool_name(block_name)
        try:
            tool_info = self._client.get_tool(tool_name)
            return {
                "block_name": block_name,
                "tool_name": tool_info.get("name", tool_name),
                "description": tool_info.get("description", ""),
                "category": tool_info.get("category", "general"),
                "server_name": tool_info.get("server_name", ""),
                "input_schema": tool_info.get("input_schema", {}),
                "source": "m11-mcp",
            }
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 404:
                return None
            raise

    def list_blocks(
        self,
        category: Optional[str] = None,
        keyword: Optional[str] = None,
        page: int = 1,
        page_size: int = 100,
    ) -> Dict[str, Any]:
        """获取可用积木列表.

        Args:
            category: 按分类过滤
            keyword: 关键词搜索
            page: 页码
            page_size: 每页数量

        Returns:
            积木列表响应
        """
        result = self._client.list_tools(
            category=category,
            keyword=keyword,
            page=page,
            page_size=page_size,
        )

        # 将工具格式转换为积木格式
        items = []
        for tool in result.get("items", []):
            items.append({
                "block_name": tool.get("name", ""),
                "tool_name": tool.get("name", ""),
                "description": tool.get("description", ""),
                "category": tool.get("category", "general"),
                "server_name": tool.get("server_name", ""),
                "input_schema": tool.get("input_schema", {}),
                "source": "m11-mcp",
            })

        return {
            "items": items,
            "total": result.get("total", 0),
            "page": result.get("page", page),
            "page_size": result.get("page_size", page_size),
            "categories": result.get("categories", []),
        }

    # ============================================================
    # 内部方法
    # ============================================================

    def _resolve_tool_name(self, block_name: str) -> str:
        """解析积木名对应的 MCP 工具名.

        当前实现：积木名与工具名一一对应，直接返回。
        未来可支持积木别名映射。

        Args:
            block_name: 积木名称

        Returns:
            MCP 工具全名
        """
        if block_name in self._block_tool_map:
            return self._block_tool_map[block_name]
        # 默认积木名即工具名
        return block_name

    def _build_result(
        self,
        block_name: str,
        tool_name: str,
        success: bool,
        output: Any,
        error: Optional[str],
        duration_ms: int,
        call_id: int = 0,
        from_cache: bool = False,
    ) -> Dict[str, Any]:
        """构建标准化的积木执行结果.

        结果格式与 M7 积木执行结果格式保持一致。

        Args:
            block_name: 积木名称
            tool_name: MCP 工具名
            success: 是否成功
            output: 输出结果
            error: 错误信息
            duration_ms: 耗时（毫秒）
            call_id: 调用记录 ID
            from_cache: 是否来自缓存

        Returns:
            标准化结果字典
        """
        return {
            "block_name": block_name,
            "success": success,
            "status": "success" if success else "failed",
            "output": output,
            "error": error,
            "duration_ms": duration_ms,
            "metadata": {
                "tool_name": tool_name,
                "call_id": call_id,
                "from_cache": from_cache,
                "source": "m11-mcp",
                "bus_url": self._bus_url,
            },
        }

    def close(self) -> None:
        """关闭执行器，释放资源."""
        self._client.close()

    def __enter__(self) -> "McpBlockExecutor":
        """上下文管理器入口."""
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        """上下文管理器出口，自动关闭连接."""
        self.close()


# ============================================================
# 单例实例
# ============================================================

_mcp_block_executor: Optional[McpBlockExecutor] = None


def get_mcp_block_executor(
    bus_url: str = "http://localhost:8011",
    api_key: str = "",
) -> McpBlockExecutor:
    """获取 MCP 积木执行器单例.

    Args:
        bus_url: M11 总线地址
        api_key: API 密钥

    Returns:
        McpBlockExecutor 实例
    """
    global _mcp_block_executor
    if _mcp_block_executor is None:
        _mcp_block_executor = McpBlockExecutor(bus_url=bus_url, api_key=api_key)
    return _mcp_block_executor
