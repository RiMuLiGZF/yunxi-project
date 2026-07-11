"""M11 MCP Bus - M7 积木同步服务.

负责将 M11 总线上的所有 MCP 工具同步为 M7 平台的自定义积木块。
每个 MCP 工具变成一个 M7 积木，积木的输入参数对应工具的 inputSchema，
积木的执行逻辑就是调用 M11 总线的工具。

如果 M7 平台提供了自定义积木创建 API，则通过 API 同步；
如果没有，则生成积木配置 JSON 文件，供手动导入。
"""

from __future__ import annotations

import json
import os
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

import httpx

from ..sdk.mcp_bus_client import McpBusClient


class McpToM7Sync:
    """MCP 工具到 M7 积木的同步服务.

    将 M11 总线上注册的所有 MCP 工具同步为 M7 平台的自定义积木块。
    支持通过 API 同步和生成配置文件两种模式。

    同步流程：
    1. 从 M11 总线获取所有 MCP 工具列表
    2. 将每个工具转换为 M7 积木配置格式
    3. 调用 M7 自定义积木创建 API（如果可用）
    4. 记录同步状态（成功/失败/跳过）

    示例::

        sync = McpToM7Sync(
            bus_url="http://localhost:8011",
            m7_api_url="http://localhost:8007/api",
        )
        result = sync.sync_to_m7()
        print(f"已同步: {result['synced']}, 失败: {result['failed']}")
    """

    # 积木分类前缀（M7 中 MCP 积木的分类标识）
    MCP_BLOCK_CATEGORY = "mcp-tools"
    # 积木命名空间前缀
    MCP_BLOCK_NAMESPACE = "mcp"

    def __init__(
        self,
        bus_url: str = "http://localhost:8011",
        bus_api_key: str = "",
        m7_api_url: str = "",
        m7_api_key: str = "",
        output_dir: Optional[str] = None,
    ) -> None:
        """初始化 M7 同步服务.

        Args:
            bus_url: M11 总线服务地址
            bus_api_key: M11 总线 API 密钥
            m7_api_url: M7 平台 API 地址（为空则只生成配置文件）
            m7_api_key: M7 平台 API 密钥
            output_dir: 积木配置文件输出目录（默认 data/m7_blocks/）
        """
        self._bus_url = bus_url.rstrip("/")
        self._bus_api_key = bus_api_key
        self._m7_api_url = m7_api_url.rstrip("/") if m7_api_url else ""
        self._m7_api_key = m7_api_key

        # M11 总线客户端
        self._bus_client = McpBusClient(
            bus_url=bus_url,
            api_key=bus_api_key,
        )

        # 输出目录
        if output_dir:
            self._output_dir = Path(output_dir)
        else:
            self._output_dir = Path(__file__).resolve().parent.parent.parent / "data" / "m7_blocks"

        # 同步状态
        self._last_sync_time: Optional[float] = None
        self._last_sync_result: Optional[Dict[str, Any]] = None

        # 定时同步相关
        self._auto_sync_thread: Optional[threading.Thread] = None
        self._auto_sync_stop = threading.Event()
        self._auto_sync_interval: int = 300  # 秒

    # ============================================================
    # 核心同步方法
    # ============================================================

    def sync_to_m7(self, m7_api_url: Optional[str] = None) -> Dict[str, Any]:
        """将所有 MCP 工具同步为 M7 自定义积木.

        流程：
        1. 从 M11 总线获取所有 MCP 工具
        2. 将每个工具转换为 M7 积木配置
        3. 如果配置了 M7 API，则调用创建接口
        4. 否则生成 JSON 配置文件

        Args:
            m7_api_url: M7 API 地址（可选，覆盖初始化时的配置）

        Returns:
            同步结果统计：
            {
                "total": int,           # 总工具数
                "synced": int,          # 成功同步数
                "failed": int,          # 失败数
                "skipped": int,         # 跳过数（已存在且未变化）
                "errors": [             # 错误详情
                    {"tool_name": str, "error": str}
                ],
                "output_file": str,     # 生成的配置文件路径（API 模式也会生成）
                "sync_mode": str,       # "api" 或 "file"
                "sync_time": float,     # 同步时间戳
                "duration_ms": int,     # 耗时（毫秒）
            }
        """
        start_time = time.time()
        api_url = m7_api_url.rstrip("/") if m7_api_url else self._m7_api_url
        sync_mode = "api" if api_url else "file"

        result: Dict[str, Any] = {
            "total": 0,
            "synced": 0,
            "failed": 0,
            "skipped": 0,
            "errors": [],
            "output_file": "",
            "sync_mode": sync_mode,
            "sync_time": time.time(),
            "duration_ms": 0,
        }

        try:
            # 1. 获取所有 MCP 工具
            all_tools = self._fetch_all_tools()
            result["total"] = len(all_tools)

            if result["total"] == 0:
                result["duration_ms"] = int((time.time() - start_time) * 1000)
                self._last_sync_result = result
                self._last_sync_time = time.time()
                return result

            # 2. 转换为 M7 积木配置
            blocks_config = self._tools_to_m7_blocks(all_tools)

            # 3. 生成配置文件（两种模式都生成）
            output_file = self._save_blocks_config(blocks_config)
            result["output_file"] = str(output_file)

            # 4. API 模式：调用 M7 接口创建积木
            if sync_mode == "api" and api_url:
                api_result = self._sync_via_api(blocks_config, api_url)
                result["synced"] = api_result["synced"]
                result["failed"] = api_result["failed"]
                result["skipped"] = api_result["skipped"]
                result["errors"] = api_result["errors"]
            else:
                # 文件模式：全部视为已同步（写入文件即成功）
                result["synced"] = len(blocks_config["blocks"])

        except Exception as e:
            result["errors"].append({"tool_name": "*", "error": f"同步异常: {str(e)}"})
            result["failed"] = max(result["total"], 1)

        result["duration_ms"] = int((time.time() - start_time) * 1000)
        self._last_sync_result = result
        self._last_sync_time = time.time()
        return result

    # ============================================================
    # 同步状态查询
    # ============================================================

    def get_sync_status(self) -> Dict[str, Any]:
        """获取同步状态.

        Returns:
            当前同步状态：
            {
                "last_sync_time": float,     # 上次同步时间戳（None 表示从未同步）
                "last_sync_result": dict,    # 上次同步结果（None 表示从未同步）
                "auto_sync_enabled": bool,   # 是否启用了自动同步
                "auto_sync_interval": int,   # 自动同步间隔（秒）
                "bus_url": str,              # M11 总线地址
                "m7_api_url": str,           # M7 API 地址
                "sync_mode": str,            # 默认同步模式
            }
        """
        return {
            "last_sync_time": self._last_sync_time,
            "last_sync_result": self._last_sync_result,
            "auto_sync_enabled": self._auto_sync_thread is not None and self._auto_sync_thread.is_alive(),
            "auto_sync_interval": self._auto_sync_interval,
            "bus_url": self._bus_url,
            "m7_api_url": self._m7_api_url,
            "sync_mode": "api" if self._m7_api_url else "file",
        }

    # ============================================================
    # 自动同步
    # ============================================================

    def auto_sync(self, interval: int = 300) -> None:
        """启动定时自动同步.

        在后台线程中定期执行同步，保持 M7 积木与 MCP 工具的同步。

        Args:
            interval: 同步间隔时间（秒），默认 300 秒（5 分钟）
        """
        if self._auto_sync_thread and self._auto_sync_thread.is_alive():
            print("[M7同步] 自动同步已在运行中")
            return

        self._auto_sync_interval = interval
        self._auto_sync_stop.clear()

        self._auto_sync_thread = threading.Thread(
            target=self._auto_sync_loop,
            daemon=True,
            name="m7-sync-auto",
        )
        self._auto_sync_thread.start()
        print(f"[M7同步] 自动同步已启动，间隔 {interval} 秒")

    def stop_auto_sync(self) -> None:
        """停止自动同步."""
        self._auto_sync_stop.set()
        if self._auto_sync_thread:
            self._auto_sync_thread.join(timeout=5)
            self._auto_sync_thread = None
        print("[M7同步] 自动同步已停止")

    def _auto_sync_loop(self) -> None:
        """自动同步循环（后台线程）."""
        while not self._auto_sync_stop.is_set():
            try:
                result = self.sync_to_m7()
                status = f"成功 {result['synced']}/{result['total']}"
                if result["failed"] > 0:
                    status += f"，失败 {result['failed']}"
                print(f"[M7同步] 自动同步完成: {status}（耗时 {result['duration_ms']}ms）")
            except Exception as e:
                print(f"[M7同步] 自动同步异常: {e}")

            # 等待间隔时间，可被 stop 中断
            self._auto_sync_stop.wait(self._auto_sync_interval)

    # ============================================================
    # 内部方法 - 工具获取
    # ============================================================

    def _fetch_all_tools(self) -> List[Dict[str, Any]]:
        """从 M11 总线获取所有 MCP 工具.

        分页获取所有工具，返回完整列表。

        Returns:
            工具列表，每项为工具详情字典
        """
        all_tools: List[Dict[str, Any]] = []
        page = 1
        page_size = 100

        while True:
            result = self._bus_client.list_tools(
                page=page,
                page_size=page_size,
            )
            items = result.get("items", [])
            all_tools.extend(items)

            if len(items) < page_size:
                break
            page += 1

        return all_tools

    # ============================================================
    # 内部方法 - 工具转积木
    # ============================================================

    def _tools_to_m7_blocks(self, tools: List[Dict[str, Any]]) -> Dict[str, Any]:
        """将 MCP 工具列表转换为 M7 积木配置.

        每个 MCP 工具对应一个 M7 积木块：
        - 积木名 = mcp_{server_name}_{tool_name}
        - 积木分类 = mcp-tools
        - 输入参数 = 工具的 inputSchema
        - 执行逻辑 = 调用 M11 总线的工具

        Args:
            tools: MCP 工具列表

        Returns:
            M7 积木配置字典：
            {
                "version": "1.0",
                "source": "m11-mcp-bus",
                "bus_url": str,
                "generated_at": float,
                "blocks": [
                    {
                        "block_name": str,
                        "display_name": str,
                        "description": str,
                        "category": str,
                        "source_tool": str,
                        "server_name": str,
                        "input_schema": dict,
                        "output_type": str,
                        "execution": {
                            "type": "mcp_call",
                            "bus_url": str,
                            "tool_name": str,
                        },
                    },
                    ...
                ]
            }
        """
        blocks = []
        for tool in tools:
            tool_name = tool.get("name", "")
            server_name = tool.get("server_name", "")
            description = tool.get("description", "")
            input_schema = tool.get("input_schema", {})
            category = tool.get("category", "general")

            # 积木名：mcp_{server}_{tool}
            safe_tool_name = tool_name.replace(".", "_")
            block_name = f"{self.MCP_BLOCK_NAMESPACE}_{safe_tool_name}"

            # 显示名：提取原始工具名
            display_name = tool_name
            if "." in tool_name:
                display_name = tool_name.split(".", 1)[1]
            # 转换为更友好的显示名
            display_name = display_name.replace("_", " ").replace("-", " ").title()

            block_config = {
                "block_name": block_name,
                "display_name": display_name,
                "description": description,
                "category": f"{self.MCP_BLOCK_CATEGORY}/{category}",
                "source_tool": tool_name,
                "server_name": server_name,
                "input_schema": input_schema,
                "output_type": "auto",
                "icon": "🔧",
                "tags": ["mcp", server_name, category],
                "execution": {
                    "type": "mcp_call",
                    "bus_url": self._bus_url,
                    "tool_name": tool_name,
                    "transport": "http",
                    "timeout_ms": 30000,
                },
            }
            blocks.append(block_config)

        return {
            "version": "1.0",
            "source": "m11-mcp-bus",
            "bus_url": self._bus_url,
            "generated_at": time.time(),
            "total_blocks": len(blocks),
            "blocks": blocks,
        }

    # ============================================================
    # 内部方法 - 文件输出
    # ============================================================

    def _save_blocks_config(self, config: Dict[str, Any]) -> Path:
        """保存积木配置到 JSON 文件.

        Args:
            config: 积木配置字典

        Returns:
            输出文件路径
        """
        self._output_dir.mkdir(parents=True, exist_ok=True)

        timestamp = int(time.time())
        filename = f"mcp_blocks_{timestamp}.json"
        output_path = self._output_dir / filename

        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(config, f, ensure_ascii=False, indent=2)

        # 同时更新 latest 符号链接/副本
        latest_path = self._output_dir / "mcp_blocks_latest.json"
        with open(latest_path, "w", encoding="utf-8") as f:
            json.dump(config, f, ensure_ascii=False, indent=2)

        return output_path

    # ============================================================
    # 内部方法 - API 同步
    # ============================================================

    def _sync_via_api(
        self,
        blocks_config: Dict[str, Any],
        api_url: str,
    ) -> Dict[str, Any]:
        """通过 M7 API 同步积木.

        尝试调用 M7 的自定义积木创建接口。
        如果接口不存在或调用失败，记录错误但不抛出异常。

        Args:
            blocks_config: 积木配置字典
            api_url: M7 API 地址

        Returns:
            API 同步结果：
            {
                "synced": int,
                "failed": int,
                "skipped": int,
                "errors": [...],
            }
        """
        result = {
            "synced": 0,
            "failed": 0,
            "skipped": 0,
            "errors": [],
        }

        blocks = blocks_config.get("blocks", [])
        headers = {"Content-Type": "application/json"}
        if self._m7_api_key:
            headers["Authorization"] = f"Bearer {self._m7_api_key}"

        with httpx.Client(timeout=15.0) as client:
            for block in blocks:
                block_name = block["block_name"]
                try:
                    # 尝试调用 M7 自定义积木创建/更新接口
                    # 接口路径按常见约定推测，实际需根据 M7 的 API 文档调整
                    endpoint = f"{api_url}/blocks/custom"

                    response = client.post(
                        endpoint,
                        json=block,
                        headers=headers,
                    )

                    if response.status_code == 200:
                        result["synced"] += 1
                    elif response.status_code == 409:
                        # 积木已存在，跳过或更新
                        result["skipped"] += 1
                    elif response.status_code == 404:
                        # 接口不存在，降级为文件模式
                        result["errors"].append({
                            "tool_name": block_name,
                            "error": "M7 自定义积木 API 不存在（404），已降级为文件模式",
                        })
                        result["failed"] = len(blocks) - result["synced"]
                        break
                    else:
                        error_detail = ""
                        try:
                            err_data = response.json()
                            error_detail = err_data.get("detail", err_data.get("message", ""))
                        except Exception:
                            error_detail = response.text[:200]
                        result["failed"] += 1
                        result["errors"].append({
                            "tool_name": block_name,
                            "error": f"HTTP {response.status_code}: {error_detail}",
                        })

                except httpx.ConnectError as e:
                    result["errors"].append({
                        "tool_name": block_name,
                        "error": f"无法连接 M7 API: {str(e)}",
                    })
                    result["failed"] = len(blocks) - result["synced"]
                    break
                except Exception as e:
                    result["failed"] += 1
                    result["errors"].append({
                        "tool_name": block_name,
                        "error": str(e),
                    })

        return result

    # ============================================================
    # 资源清理
    # ============================================================

    def close(self) -> None:
        """关闭同步服务，停止自动同步，释放资源."""
        self.stop_auto_sync()
        self._bus_client.close()

    def __enter__(self) -> "McpToM7Sync":
        """上下文管理器入口."""
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        """上下文管理器出口."""
        self.close()


# ============================================================
# 单例实例
# ============================================================

_mcp_to_m7_sync: Optional[McpToM7Sync] = None


def get_mcp_to_m7_sync(
    bus_url: str = "http://localhost:8011",
    bus_api_key: str = "",
    m7_api_url: str = "",
    m7_api_key: str = "",
) -> McpToM7Sync:
    """获取 M7 同步服务单例.

    Args:
        bus_url: M11 总线地址
        bus_api_key: M11 总线 API 密钥
        m7_api_url: M7 API 地址
        m7_api_key: M7 API 密钥

    Returns:
        McpToM7Sync 实例
    """
    global _mcp_to_m7_sync
    if _mcp_to_m7_sync is None:
        _mcp_to_m7_sync = McpToM7Sync(
            bus_url=bus_url,
            bus_api_key=bus_api_key,
            m7_api_url=m7_api_url,
            m7_api_key=m7_api_key,
        )
    return _mcp_to_m7_sync
