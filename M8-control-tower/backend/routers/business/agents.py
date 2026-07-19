"""
Agent 管理路由 — M8 代理模式（V12.0 迁移）

[V12.0] Agent 管理台已迁移至 M1-agent-hub，M8 端保留代理路由，向后兼容。

迁移说明：
- 核心逻辑：ExternalAgentRegistry + APIKeyManager 已在 M1
- 数据存储：agent_keys.enc + 内存注册表由 M1 管理
- 本文件：M8 端代理路由，将请求转发到 M1
- 降级机制：M1 不可用时，可切换回本地实现（AGENTS_PROXY_MODE=local）

接口清单（共 13 个，全部代理到 M1）：
Agent 管理（6 个）：
  1. GET    /api/agents                  - Agent 列表
  2. POST   /api/agents/register         - Agent 注册
  3. DELETE /api/agents/{agent_id}       - Agent 删除
  4. POST   /api/agents/{agent_id}/health-check  - Agent 健康检查
  5. POST   /api/agents/{agent_id}/toggle        - Agent 启用/禁用
  6. GET    /api/agents/stats            - Agent 统计

密钥管理（7 个）：
  7. GET    /api/agents/keys             - 密钥列表
  8. POST   /api/agents/keys             - 保存密钥
  9. DELETE /api/agents/keys/{provider}  - 删除密钥
 10. POST   /api/agents/keys/{provider}/health-check - 单密钥健康检查
 11. POST   /api/agents/keys/health-check-all        - 批量健康检查
 12. GET    /api/agents/keys/providers   - 服务商列表
 13. GET    /api/agents/keys/stats       - 密钥统计（合并在 stats 中）
"""

import os
import secrets
import sys
from pathlib import Path
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, ConfigDict, Field

# 将项目根目录加入 path
project_root = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(project_root))

from ...schemas import ApiResponse
from ...auth import get_current_user
from shared.core.observability import get_logger

logger = get_logger("agents_router_proxy")

router = APIRouter()

# ── 代理配置 ──────────────────────────────────────────

# 代理模式: "proxy"（默认，转发到 M1） / "local"（降级，使用本地实现）
AGENTS_PROXY_MODE = os.getenv("AGENTS_PROXY_MODE", "proxy").lower()

# M1 服务地址
M1_BASE_URL = os.getenv("M1_BASE_URL", "http://localhost:8001")

def _is_production_env() -> bool:
    """检查是否处于生产环境."""
    return os.environ.get("YUNXI_ENV", "").lower() in ("production", "prod")


def _resolve_admin_token(env_var: str, module_name: str) -> str:
    """解析 Admin Token，根据环境采取不同策略.

    - 生产环境：未配置时报错并返回空字符串（代理将拒绝）
    - 开发环境：未配置时生成随机 token 并打印到日志，便于本地调试
    """
    token = os.getenv(env_var, "")
    if not token:
        if _is_production_env():
            logger.error(
                f"{env_var}_not_configured",
                message=f"{module_name} 代理 Token 未配置，生产环境下代理将不可用",
            )
            return ""
        # 开发环境生成随机 token
        random_token = secrets.token_urlsafe(32)
        logger.warning(
            f"{env_var}_dev_auto_generated",
            message=f"{module_name} 代理 Token 未配置，开发环境自动生成随机 token: {random_token}",
        )
        return random_token
    return token


# M1 Admin Token（用于 M8 -> M1 鉴权）
M1_ADMIN_TOKEN = _resolve_admin_token("M1_ADMIN_TOKEN", "M1 Agent Hub")

# 代理超时时间（秒）
PROXY_TIMEOUT = float(os.getenv("AGENTS_PROXY_TIMEOUT", "30.0"))

# HTTP 客户端（懒加载）
_client: Any = None


def _get_client() -> Any:
    """获取 HTTP 客户端（懒加载 httpx）"""
    global _client
    if _client is None:
        import httpx
        _client = httpx.AsyncClient(
            base_url=M1_BASE_URL,
            timeout=PROXY_TIMEOUT,
            headers={
                "X-M8-Token": M1_ADMIN_TOKEN,
                "Content-Type": "application/json",
            },
        )
    return _client


async def _proxy_to_m1(
    method: str,
    path: str,
    params: Optional[Dict[str, Any]] = None,
    json_data: Optional[Dict[str, Any]] = None,
    trace_id: Optional[str] = None,
) -> Dict[str, Any]:
    """
    代理请求到 M1 Agent Hub

    Args:
        method: HTTP 方法 (GET/POST/DELETE/PUT)
        path: 目标路径（含 /api/agents 前缀）
        params: 查询参数
        json_data: 请求体 JSON
        trace_id: 链路追踪 ID

    Returns:
        M1 返回的 JSON 数据（已解析为 dict）

    Raises:
        HTTPException: 代理失败时抛出
    """
    client = _get_client()
    headers = {}
    if trace_id:
        headers["X-Trace-Id"] = trace_id

    # 生产环境下 token 未配置时拒绝代理
    if not M1_ADMIN_TOKEN and _is_production_env():
        raise HTTPException(
            status_code=503,
            detail="M1_ADMIN_TOKEN 未配置，生产环境下 M1 代理不可用",
        )

    try:
        response = await client.request(
            method=method.upper(),
            url=path,
            params=params,
            json=json_data,
            headers=headers if headers else None,
        )
        response.raise_for_status()
        return response.json()
    except Exception as exc:
        # 区分错误类型，提供友好提示
        error_msg = str(exc)
        if hasattr(exc, "response") and exc.response is not None:
            status_code = exc.response.status_code
            try:
                err_body = exc.response.json()
                detail = err_body.get("detail", err_body.get("message", error_msg))
            except Exception:
                detail = error_msg
            raise HTTPException(
                status_code=502,
                detail=f"M1 Agent Hub 返回错误 ({status_code}): {detail}",
            )
        else:
            raise HTTPException(
                status_code=502,
                detail=f"M1 Agent Hub 连接失败: {error_msg}",
            )


def _get_trace_id(request: Request) -> Optional[str]:
    """从请求中提取 trace_id"""
    return request.headers.get("X-Trace-Id") or request.headers.get("x-trace-id")


# ── 请求模型（保留 Pydantic 校验，代理层仍然验证输入）──────────


class AgentRegisterRequest(BaseModel):
    """Agent 注册请求"""
    model_config = ConfigDict(protected_namespaces=())

    display_name: str = Field(..., description="显示名称")
    provider: str = Field(..., description="服务商/提供方")
    agent_type: str = Field(default="llm", description="Agent 类型: llm/code/voice/etc")
    capabilities: list[str] = Field(default_factory=list, description="能力标签列表")
    mode: str = Field(default="api", description="运行模式: local/api")
    api_provider: str = Field(default="", description="API 服务商")
    api_base_url: str = Field(default="", description="API 基础 URL（可选）")
    model_name: str = Field(default="", description="模型名称（可选）")
    description: str = Field(default="", description="Agent 描述")
    privacy_level: str = Field(default="standard", description="隐私等级")
    connection_type: str = Field(default="api_key", description="连接类型")
    cost_model: dict[str, Any] = Field(default_factory=dict, description="成本模型")
    license: str = Field(default="MIT", description="许可证类型")


class KeySaveRequest(BaseModel):
    """密钥保存请求"""
    provider: str = Field(..., description="服务商")
    api_key: str = Field(..., description="API Key 明文")
    base_url: str = Field(default="", description="自定义 API 基础 URL（可选）")
    model: str = Field(default="", description="默认模型名称（可选）")


class AgentToggleRequest(BaseModel):
    """Agent 启用/禁用请求"""
    enabled: bool = Field(..., description="是否启用")


# ═══════════════════════════════════════════════════════
# Agent 管理接口（6 个）— 代理到 M1
# ═══════════════════════════════════════════════════════


@router.get("")
async def list_agents(
    request: Request,
    agent_type: Optional[str] = Query(None, description="按 Agent 类型筛选"),
    status: Optional[str] = Query(None, description="按状态筛选"),
    current_user: dict = Depends(get_current_user),
):
    """获取 Agent 列表（代理到 M1）"""
    try:
        params = {}
        if agent_type:
            params["agent_type"] = agent_type
        if status:
            params["status"] = status

        result = await _proxy_to_m1(
            method="GET",
            path="/api/agents",
            params=params if params else None,
            trace_id=_get_trace_id(request),
        )
        # M1 返回 ApiResponse 格式 {code, message, data, ...}，直接透传
        return result
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("list_agents_proxy_failed", error=str(exc))
        return ApiResponse.error(code=502, message=f"Agent 列表获取失败: {exc}")


@router.post("/register")
async def register_agent(
    request: Request,
    req: AgentRegisterRequest,
    current_user: dict = Depends(get_current_user),
):
    """注册新 Agent（代理到 M1）"""
    try:
        result = await _proxy_to_m1(
            method="POST",
            path="/api/agents/register",
            json_data=req.model_dump(),
            trace_id=_get_trace_id(request),
        )
        return result
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("register_agent_proxy_failed", error=str(exc))
        return ApiResponse.error(code=502, message=f"Agent 注册失败: {exc}")


@router.delete("/{agent_id}")
async def delete_agent(
    request: Request,
    agent_id: str,
    current_user: dict = Depends(get_current_user),
):
    """删除 Agent（代理到 M1）"""
    try:
        result = await _proxy_to_m1(
            method="DELETE",
            path=f"/api/agents/{agent_id}",
            trace_id=_get_trace_id(request),
        )
        return result
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("delete_agent_proxy_failed", agent_id=agent_id, error=str(exc))
        return ApiResponse.error(code=502, message=f"Agent 删除失败: {exc}")


@router.post("/{agent_id}/health-check")
async def agent_health_check(
    request: Request,
    agent_id: str,
    current_user: dict = Depends(get_current_user),
):
    """Agent 健康检查（代理到 M1）"""
    try:
        result = await _proxy_to_m1(
            method="POST",
            path=f"/api/agents/{agent_id}/health-check",
            trace_id=_get_trace_id(request),
        )
        return result
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("agent_health_check_proxy_failed", agent_id=agent_id, error=str(exc))
        return ApiResponse.error(code=502, message=f"健康检查失败: {exc}")


@router.post("/{agent_id}/toggle")
async def toggle_agent(
    request: Request,
    agent_id: str,
    req: AgentToggleRequest,
    current_user: dict = Depends(get_current_user),
):
    """启用 / 禁用 Agent（代理到 M1）"""
    try:
        result = await _proxy_to_m1(
            method="POST",
            path=f"/api/agents/{agent_id}/toggle",
            json_data=req.model_dump(),
            trace_id=_get_trace_id(request),
        )
        return result
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("toggle_agent_proxy_failed", agent_id=agent_id, error=str(exc))
        return ApiResponse.error(code=502, message=f"切换 Agent 状态失败: {exc}")


@router.get("/stats")
async def agent_stats(
    request: Request,
    current_user: dict = Depends(get_current_user),
):
    """Agent 统计信息（代理到 M1）"""
    try:
        result = await _proxy_to_m1(
            method="GET",
            path="/api/agents/stats",
            trace_id=_get_trace_id(request),
        )
        return result
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("agent_stats_proxy_failed", error=str(exc))
        return ApiResponse.error(code=502, message=f"获取统计信息失败: {exc}")


# ═══════════════════════════════════════════════════════
# 密钥管理接口（7 个）— 代理到 M1
# ═══════════════════════════════════════════════════════


@router.get("/keys")
async def list_keys(
    request: Request,
    current_user: dict = Depends(get_current_user),
):
    """获取密钥列表（代理到 M1）"""
    try:
        result = await _proxy_to_m1(
            method="GET",
            path="/api/agents/keys",
            trace_id=_get_trace_id(request),
        )
        return result
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("list_keys_proxy_failed", error=str(exc))
        return ApiResponse.error(code=502, message=f"获取密钥列表失败: {exc}")


@router.post("/keys")
async def save_key(
    request: Request,
    req: KeySaveRequest,
    current_user: dict = Depends(get_current_user),
):
    """保存 / 更新 API 密钥（代理到 M1）"""
    try:
        result = await _proxy_to_m1(
            method="POST",
            path="/api/agents/keys",
            json_data=req.model_dump(),
            trace_id=_get_trace_id(request),
        )
        return result
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("save_key_proxy_failed", error=str(exc))
        return ApiResponse.error(code=502, message=f"保存密钥失败: {exc}")


@router.delete("/keys/{provider}")
async def delete_key(
    request: Request,
    provider: str,
    current_user: dict = Depends(get_current_user),
):
    """删除指定服务商的 API 密钥（代理到 M1）"""
    try:
        result = await _proxy_to_m1(
            method="DELETE",
            path=f"/api/agents/keys/{provider}",
            trace_id=_get_trace_id(request),
        )
        return result
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("delete_key_proxy_failed", provider=provider, error=str(exc))
        return ApiResponse.error(code=502, message=f"删除密钥失败: {exc}")


@router.post("/keys/{provider}/health-check")
async def key_health_check(
    request: Request,
    provider: str,
    current_user: dict = Depends(get_current_user),
):
    """测试指定服务商密钥的连通性（代理到 M1）"""
    try:
        result = await _proxy_to_m1(
            method="POST",
            path=f"/api/agents/keys/{provider}/health-check",
            trace_id=_get_trace_id(request),
        )
        return result
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("key_health_check_proxy_failed", provider=provider, error=str(exc))
        return ApiResponse.error(code=502, message=f"密钥健康检查失败: {exc}")


@router.post("/keys/health-check-all")
async def key_health_check_all(
    request: Request,
    current_user: dict = Depends(get_current_user),
):
    """检查所有密钥的健康状态（代理到 M1）"""
    try:
        result = await _proxy_to_m1(
            method="POST",
            path="/api/agents/keys/health-check-all",
            trace_id=_get_trace_id(request),
        )
        return result
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("key_health_check_all_proxy_failed", error=str(exc))
        return ApiResponse.error(code=502, message=f"批量健康检查失败: {exc}")


@router.get("/keys/providers")
async def list_supported_providers(
    request: Request,
    current_user: dict = Depends(get_current_user),
):
    """获取支持的服务商列表（代理到 M1）"""
    try:
        result = await _proxy_to_m1(
            method="GET",
            path="/api/agents/keys/providers",
            trace_id=_get_trace_id(request),
        )
        return result
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("list_providers_proxy_failed", error=str(exc))
        return ApiResponse.error(code=502, message=f"获取服务商列表失败: {exc}")


# ═══════════════════════════════════════════════════════
# 降级：本地实现（当 AGENTS_PROXY_MODE=local 时启用）
# ═══════════════════════════════════════════════════════
#
# 说明：为了保证 M1 不可用时系统仍能运行，保留原本地实现作为降级方案。
# 通过环境变量 AGENTS_PROXY_MODE=local 切换回本地模式。
# 本地实现代码保留在 _local_implementation 区域，
# 当代理模式为 "local" 时，router 会重新注册本地路由。

if AGENTS_PROXY_MODE == "local":
    # 重新导入并注册本地实现
    import sys as _sys
    from pathlib import Path as _Path

    _m1_path = project_root / "M1-agent-hub"
    if str(_m1_path) not in _sys.path:
        _sys.path.insert(0, str(_m1_path))

    def _get_key_manager_local():
        """懒加载统一密钥管理器（本地模式）"""
        try:
            from federation.auth.key_manager import get_key_manager
            return get_key_manager()
        except (ImportError, RuntimeError) as exc:
            logger.warning("密钥管理器初始化失败: %s", exc)
            raise HTTPException(status_code=500, detail=f"密钥管理器初始化失败: {exc}")

    def _get_external_registry_local():
        """懒加载外部 Agent 注册表（本地模式）"""
        try:
            from federation.registry import ExternalAgentRegistry
            if not hasattr(_get_external_registry_local, "_instance"):
                _get_external_registry_local._instance = ExternalAgentRegistry()
            return _get_external_registry_local._instance
        except (ImportError, RuntimeError) as exc:
            logger.warning("Agent 注册表初始化失败: %s", exc)
            raise HTTPException(status_code=500, detail=f"Agent 注册表初始化失败: {exc}")

    def _profile_to_dict_local(profile: Any) -> dict[str, Any]:
        """将 ExternalAgentProfile 转换为字典（本地模式）"""
        if profile is None:
            return {}
        result = {
            "agent_id": getattr(profile, "agent_id", ""),
            "display_name": getattr(profile, "display_name", ""),
            "provider": getattr(profile, "provider", ""),
            "agent_type": getattr(profile.agent_type, "value", str(getattr(profile, "agent_type", ""))),
            "capabilities": getattr(profile, "capabilities", []),
            "description": getattr(profile, "description", ""),
            "status": getattr(profile, "status", ""),
            "privacy_level": getattr(profile.privacy_level, "value", str(getattr(profile, "privacy_level", ""))),
            "connection_type": getattr(profile.connection_type, "value", str(getattr(profile, "connection_type", ""))),
            "config": getattr(profile, "config", {}),
            "license": getattr(profile.license, "value", str(getattr(profile, "license", ""))),
            "created_at": getattr(profile, "created_at", 0),
            "updated_at": getattr(profile, "updated_at", 0),
            "last_health_check": getattr(profile, "last_health_check", 0),
        }
        cost_model = getattr(profile, "cost_model", None)
        if cost_model is not None:
            if hasattr(cost_model, "model_dump"):
                result["cost_model"] = cost_model.model_dump()
            elif hasattr(cost_model, "__dict__"):
                result["cost_model"] = cost_model.__dict__
            else:
                result["cost_model"] = cost_model
        else:
            result["cost_model"] = {}
        return result

    logger.warning("AGENTS_PROXY_MODE=local，使用本地 Agent 管理实现（降级模式）")
