"""
M4 场景引擎代理工具

提供统一的 proxy_to_m4 函数，用于将业务模式 API 代理到 M4 场景引擎。
M4 不可用时自动回退到本地实现（fallback），保证功能不中断。

使用方式：
    result = await proxy_to_m4(
        path="/api/v1/mode/growth/overview",
        method="GET",
        params={"user_id": 1},
        fallback_func=local_overview_handler,
    )
"""

import sys
from pathlib import Path
from typing import Any, Callable, Dict, Optional, Awaitable

# 将项目根目录加入 path，以便导入 shared 模块
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

from shared.business.module_client import get_module_registry
from shared.core.observability import get_logger

logger = get_logger("m8.m4_proxy")

# M4 模块 key
M4_MODULE_KEY = "m4"

# 代理响应头标识
PROXY_HEADER_KEY = "X-M4-Proxy"


async def proxy_to_m4(
    path: str,
    method: str = "GET",
    params: Optional[Dict[str, Any]] = None,
    body: Optional[Dict[str, Any]] = None,
    headers: Optional[Dict[str, str]] = None,
    fallback_func: Optional[Callable[..., Awaitable[Any]]] = None,
    fallback_args: Optional[tuple] = None,
    fallback_kwargs: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    代理请求到 M4 场景引擎

    M4 可用时，将请求转发到 M4 并返回结果；
    M4 不可用时，调用 fallback_func 返回本地数据。

    Args:
        path: M4 上的目标路径（如 /api/v1/mode/growth/overview）
        method: HTTP 方法 (GET, POST, PUT, DELETE)
        params: URL 查询参数
        body: 请求体 JSON 数据
        headers: 附加请求头
        fallback_func: M4 不可用时的回退函数（异步函数）
        fallback_args: 回退函数的位置参数
        fallback_kwargs: 回退函数的关键字参数

    Returns:
        统一格式的响应字典 {code, message, data}
        如果成功代理到 M4，在响应中附加 _proxied=True 标识
    """
    try:
        registry = get_module_registry()
        client = registry.get_client(M4_MODULE_KEY)

        method_upper = method.upper()
        if method_upper == "GET":
            result = await client.get(path, params=params)
        elif method_upper == "POST":
            result = await client.post(path, params=params, json_data=body)
        elif method_upper == "PUT":
            result = await client.put(path, params=params, json_data=body)
        elif method_upper == "DELETE":
            result = await client.delete(path, params=params)
        else:
            raise ValueError(f"不支持的 HTTP 方法: {method}")

        # 代理成功，附加代理标识
        if isinstance(result, dict):
            result["_proxied"] = True
        logger.debug(f"M4 代理成功: {method} {path}")
        return result

    except Exception as exc:
        # M4 不可用，记录日志并回退
        logger.warning(f"M4 代理失败，回退到本地实现: {method} {path} - {exc}")

        if fallback_func is not None:
            args = fallback_args or ()
            kwargs = fallback_kwargs or {}
            try:
                result = await fallback_func(*args, **kwargs)
                # 确保返回格式是 dict
                if isinstance(result, dict):
                    result["_proxied"] = False
                return result
            except Exception as fallback_exc:
                logger.error(f"M4 代理回退函数也失败了: {fallback_exc}")
                return {
                    "code": 500,
                    "message": f"服务暂时不可用: {fallback_exc}",
                    "data": None,
                    "_proxied": False,
                }
        else:
            # 没有回退函数，返回错误
            return {
                "code": 503,
                "message": f"M4 场景引擎暂不可用: {exc}",
                "data": None,
                "_proxied": False,
            }


async def try_m4_only(
    path: str,
    method: str = "GET",
    params: Optional[Dict[str, Any]] = None,
    body: Optional[Dict[str, Any]] = None,
) -> Optional[Dict[str, Any]]:
    """
    仅尝试代理到 M4，不做回退

    M4 可用时返回响应数据；不可用时返回 None。
    用于在路由处理函数开头做快速代理尝试。

    Args:
        path: M4 目标路径
        method: HTTP 方法
        params: URL 查询参数
        body: 请求体

    Returns:
        M4 响应数据（成功时）或 None（失败时）
    """
    try:
        registry = get_module_registry()
        client = registry.get_client(M4_MODULE_KEY)

        method_upper = method.upper()
        if method_upper == "GET":
            result = await client.get(path, params=params)
        elif method_upper == "POST":
            result = await client.post(path, params=params, json_data=body)
        elif method_upper == "PUT":
            result = await client.put(path, params=params, json_data=body)
        elif method_upper == "DELETE":
            result = await client.delete(path, params=params)
        else:
            raise ValueError(f"不支持的 HTTP 方法: {method}")

        logger.debug(f"M4 代理成功: {method} {path}")
        return result

    except Exception as exc:
        logger.debug(f"M4 不可用（跳过代理）: {method} {path} - {exc}")
        return None


def is_proxied_response(result: Dict[str, Any]) -> bool:
    """判断响应是否来自 M4 代理"""
    return isinstance(result, dict) and result.get("_proxied", False)


def strip_proxy_flag(result: Dict[str, Any]) -> Dict[str, Any]:
    """移除响应中的代理标识（用于返回给前端）"""
    if isinstance(result, dict) and "_proxied" in result:
        # 不修改原 dict，创建副本
        cleaned = {k: v for k, v in result.items() if k != "_proxied"}
        return cleaned
    return result


# ═══════════════════════════════════════════════════════
# 路径映射：M8 业务模式前缀 → M4 路径前缀
# ═══════════════════════════════════════════════════════

M4_PATH_PREFIX_MAP = {
    "growth": "/api/v1/mode/growth",
    "work-dev": "/api/v1/mode/work-dev",
    "review": "/api/v1/mode/review",
    "study-plan": "/api/v1/mode/study-plan",
    "life-management": "/api/v1/mode/life-management",
    "emotion-comfort": "/api/v1/mode/emotion-comfort",
    "social-relation": "/api/v1/mode/social-relation",
    "appearance": "/api/v1/mode/appearance",
}


def get_m4_path(mode_key: str, sub_path: str) -> str:
    """
    根据模式 key 和子路径构建 M4 完整路径

    Args:
        mode_key: 模式 key（如 "growth", "work-dev"）
        sub_path: 子路径（如 "/overview" 或 "overview"）

    Returns:
        M4 完整路径（如 /api/v1/mode/growth/overview）
    """
    prefix = M4_PATH_PREFIX_MAP.get(mode_key, f"/api/v1/mode/{mode_key}")
    # 确保 sub_path 以 / 开头
    if not sub_path.startswith("/"):
        sub_path = "/" + sub_path
    return f"{prefix}{sub_path}"
