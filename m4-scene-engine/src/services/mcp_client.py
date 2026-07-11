"""MCP 工具调用客户端.

提供轻量级的 MCP（Model Context Protocol）工具调用能力，
通过 HTTP 接口与 M9 MCP 服务通信，支持工具列表查询、工具详情获取和工具调用。

特性：
- httpx 异步/同步 HTTP 请求
- 超时处理（默认 30 秒）
- 错误处理与优雅降级
- 支持配置 M9 服务地址（环境变量 / 配置文件）
- 单例模式
"""

from __future__ import annotations

import logging
import os
from typing import Any

# ---------------------------------------------------------------------------
# 可选依赖：httpx
# ---------------------------------------------------------------------------
try:
    import httpx
    _HAS_HTTPX = True
except ImportError:
    _HAS_HTTPX = False


logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# 配置常量
# ---------------------------------------------------------------------------

#: 默认 M9 MCP 服务地址
DEFAULT_MCP_BASE_URL = "http://localhost:8000/api/mcp"

#: 默认请求超时时间（秒）
DEFAULT_TIMEOUT = 30.0

#: 环境变量名 - MCP 服务地址
ENV_MCP_BASE_URL = "MCP_BASE_URL"

#: 环境变量名 - MCP API Key
ENV_MCP_API_KEY = "MCP_API_KEY"

#: 环境变量名 - MCP 服务开关
ENV_MCP_ENABLED = "MCP_ENABLED"


# ---------------------------------------------------------------------------
# MCP 客户端
# ---------------------------------------------------------------------------

class McpClient:
    """MCP 工具调用客户端.

    通过 HTTP 与 M9 MCP 服务通信，提供工具列表查询、详情获取和调用能力。
    服务不可用时自动降级，返回友好错误信息，不影响上层业务。
    """

    def __init__(
        self,
        base_url: str | None = None,
        api_key: str | None = None,
        timeout: float = DEFAULT_TIMEOUT,
        enabled: bool = True,
    ) -> None:
        """初始化 MCP 客户端.

        Args:
            base_url: M9 MCP 服务地址，为空则从环境变量读取，再为空使用默认值
            api_key: API 密钥，为空则从环境变量读取
            timeout: 请求超时时间（秒）
            enabled: 是否启用 MCP 服务
        """
        # 从环境变量读取配置
        env_base_url = os.environ.get(ENV_MCP_BASE_URL, "")
        env_api_key = os.environ.get(ENV_MCP_API_KEY, "")
        env_enabled = os.environ.get(ENV_MCP_ENABLED, "").lower()

        self._base_url = (
            base_url
            or env_base_url
            or DEFAULT_MCP_BASE_URL
        ).rstrip("/")
        self._api_key = api_key or env_api_key or ""
        self._timeout = timeout
        self._enabled = enabled if env_enabled == "" else env_enabled not in (
            "0", "false", "no", "off", "disabled"
        )

        # 服务可用状态标记（用于降级）
        self._service_available = True

        # httpx 客户端（延迟创建）
        self._client: httpx.Client | None = None

    # -----------------------------------------------------------------------
    # 内部辅助方法
    # -----------------------------------------------------------------------

    def _get_client(self) -> httpx.Client | None:
        """获取或创建 httpx 客户端.

        Returns:
            httpx.Client 实例，若未安装 httpx 则返回 None
        """
        if not _HAS_HTTPX:
            return None

        if self._client is None:
            headers = {}
            if self._api_key:
                headers["Authorization"] = f"Bearer {self._api_key}"
            self._client = httpx.Client(
                base_url=self._base_url,
                headers=headers,
                timeout=self._timeout,
            )

        return self._client

    def _request(
        self,
        method: str,
        path: str,
        params: dict[str, Any] | None = None,
        json_data: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """发送 HTTP 请求并处理响应.

        Args:
            method: HTTP 方法 (GET/POST 等)
            path: 请求路径（相对于 base_url）
            params: URL 查询参数
            json_data: JSON 请求体

        Returns:
            响应数据字典，包含 success / data / error 等字段
        """
        # 检查是否启用
        if not self._enabled:
            return {
                "success": False,
                "error": "MCP 服务已禁用",
                "error_code": "MCP_DISABLED",
                "data": {},
            }

        # 检查依赖
        client = self._get_client()
        if client is None:
            return {
                "success": False,
                "error": "缺少 httpx 依赖，请安装: pip install httpx",
                "error_code": "MCP_DEPENDENCY_MISSING",
                "data": {},
            }

        # 服务不可用时快速降级
        if not self._service_available:
            return {
                "success": False,
                "error": "MCP 服务不可用（已降级）",
                "error_code": "MCP_SERVICE_UNAVAILABLE",
                "data": {},
            }

        try:
            response = client.request(
                method=method,
                url=path,
                params=params,
                json=json_data,
            )
            response.raise_for_status()

            # 尝试解析 JSON
            try:
                result = response.json()
            except ValueError:
                result = {"raw": response.text}

            # 标记服务可用
            self._service_available = True

            return {
                "success": True,
                "data": result,
                "status_code": response.status_code,
            }

        except httpx.TimeoutException:
            self._service_available = False
            logger.warning("MCP 服务请求超时: %s %s", method, path)
            return {
                "success": False,
                "error": "MCP 服务请求超时",
                "error_code": "MCP_TIMEOUT",
                "data": {},
            }

        except httpx.HTTPStatusError as e:
            if e.response.status_code >= 500:
                self._service_available = False
            logger.warning(
                "MCP 服务返回错误状态码: %s, path=%s",
                e.response.status_code,
                path,
            )
            return {
                "success": False,
                "error": f"MCP 服务错误: {e.response.status_code}",
                "error_code": f"MCP_HTTP_{e.response.status_code}",
                "status_code": e.response.status_code,
                "data": {},
            }

        except httpx.HTTPError as e:
            self._service_available = False
            logger.warning("MCP 服务连接失败: %s", e)
            return {
                "success": False,
                "error": f"MCP 服务连接失败: {e}",
                "error_code": "MCP_CONNECTION_ERROR",
                "data": {},
            }

        except Exception as e:
            logger.exception("MCP 客户端未知错误")
            return {
                "success": False,
                "error": f"未知错误: {e}",
                "error_code": "MCP_UNKNOWN_ERROR",
                "data": {},
            }

    # -----------------------------------------------------------------------
    # 公开 API
    # -----------------------------------------------------------------------

    def list_tools(self, category: str | None = None) -> list[dict[str, Any]]:
        """获取可用 MCP 工具列表.

        Args:
            category: 工具分类筛选（可选）

        Returns:
            工具列表，每个工具为字典格式；服务不可用时返回空列表
        """
        params = {}
        if category:
            params["category"] = category

        result = self._request("GET", "/tools", params=params)

        if not result.get("success", False):
            logger.warning("获取 MCP 工具列表失败: %s", result.get("error"))
            return []

        data = result.get("data", {})
        # 兼容不同的返回格式
        if isinstance(data, list):
            return data
        if isinstance(data, dict):
            tools = data.get("tools", data.get("data", []))
            return tools if isinstance(tools, list) else []
        return []

    def get_tool(self, tool_name: str) -> dict[str, Any]:
        """获取指定 MCP 工具的详情.

        Args:
            tool_name: 工具名称

        Returns:
            工具详情字典，失败时返回包含 error 字段的字典
        """
        if not tool_name:
            return {"success": False, "error": "工具名称不能为空"}

        result = self._request("GET", f"/tools/{tool_name}")

        if not result.get("success", False):
            return {
                "success": False,
                "name": tool_name,
                "error": result.get("error", "获取工具详情失败"),
                "error_code": result.get("error_code", ""),
            }

        data = result.get("data", {})
        # 兼容不同返回格式
        if isinstance(data, dict) and "data" in data:
            tool_data = data["data"]
        else:
            tool_data = data

        return {
            "success": True,
            "name": tool_name,
            "detail": tool_data,
        }

    def call_tool(
        self,
        tool_name: str,
        arguments: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """调用 MCP 工具.

        Args:
            tool_name: 工具名称
            arguments: 工具参数字典（可选）

        Returns:
            调用结果字典，包含 success / result / error 等字段
        """
        if not tool_name:
            return {"success": False, "error": "工具名称不能为空"}

        payload = {"arguments": arguments or {}}

        result = self._request(
            "POST",
            f"/tools/{tool_name}/call",
            json_data=payload,
        )

        if not result.get("success", False):
            return {
                "success": False,
                "tool_name": tool_name,
                "error": result.get("error", "工具调用失败"),
                "error_code": result.get("error_code", ""),
                "result": {},
            }

        data = result.get("data", {})
        # 兼容不同返回格式
        if isinstance(data, dict):
            call_result = data.get("result", data.get("data", data))
        else:
            call_result = data

        return {
            "success": True,
            "tool_name": tool_name,
            "result": call_result,
        }

    def health_check(self) -> bool:
        """检查 MCP 服务是否可用.

        Returns:
            True 表示服务可用，False 表示不可用
        """
        if not self._enabled:
            return False

        if not _HAS_HTTPX:
            return False

        result = self._request("GET", "/health")
        available = result.get("success", False)

        # 更新可用状态
        self._service_available = available

        return available

    # -----------------------------------------------------------------------
    # 属性访问
    # -----------------------------------------------------------------------

    @property
    def base_url(self) -> str:
        """获取 MCP 服务地址."""
        return self._base_url

    @property
    def enabled(self) -> bool:
        """获取 MCP 服务是否启用."""
        return self._enabled

    @enabled.setter
    def enabled(self, value: bool) -> None:
        """设置 MCP 服务启用状态."""
        self._enabled = value

    @property
    def service_available(self) -> bool:
        """获取 MCP 服务是否可用（最近一次请求结果）."""
        return self._service_available

    def update_config(
        self,
        base_url: str | None = None,
        api_key: str | None = None,
        enabled: bool | None = None,
        timeout: float | None = None,
    ) -> None:
        """更新客户端配置.

        更新后会重建 httpx 客户端以应用新配置。

        Args:
            base_url: 新的服务地址
            api_key: 新的 API 密钥
            enabled: 是否启用
            timeout: 超时时间
        """
        changed = False

        if base_url is not None:
            new_url = base_url.rstrip("/")
            if new_url != self._base_url:
                self._base_url = new_url
                changed = True

        if api_key is not None:
            if api_key != self._api_key:
                self._api_key = api_key
                changed = True

        if enabled is not None:
            self._enabled = enabled

        if timeout is not None:
            self._timeout = timeout
            changed = True

        # 配置变化时重建客户端
        if changed and self._client is not None:
            try:
                self._client.close()
            except Exception:
                pass
            self._client = None
            # 重置可用状态
            self._service_available = True

    def close(self) -> None:
        """关闭客户端，释放资源."""
        if self._client is not None:
            try:
                self._client.close()
            except Exception:
                pass
            self._client = None


# ---------------------------------------------------------------------------
# 单例管理
# ---------------------------------------------------------------------------

_mcp_client: McpClient | None = None


def get_mcp_client(
    base_url: str | None = None,
    api_key: str | None = None,
    enabled: bool = True,
) -> McpClient:
    """获取 MCP 客户端单例.

    Args:
        base_url: MCP 服务地址（仅首次调用时有效）
        api_key: API 密钥（仅首次调用时有效）
        enabled: 是否启用（仅首次调用时有效）

    Returns:
        McpClient 单例
    """
    global _mcp_client

    if _mcp_client is None:
        _mcp_client = McpClient(
            base_url=base_url,
            api_key=api_key,
            enabled=enabled,
        )

    return _mcp_client


def reset_mcp_client() -> None:
    """重置 MCP 客户端单例（主要用于测试）."""
    global _mcp_client
    if _mcp_client is not None:
        _mcp_client.close()
        _mcp_client = None


# ---------------------------------------------------------------------------
# 兼容相对导入和直接运行
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    # 直接运行时的简单测试
    client = McpClient()
    print(f"MCP 服务地址: {client.base_url}")
    print(f"MCP 服务启用: {client.enabled}")
    print(f"MCP 服务可用: {client.health_check()}")
    print(f"工具列表: {client.list_tools()}")
