"""
Agent 管理与密钥管理 API 路由（M1 联邦调度系统）

将原 M8 控制塔的 Agent 管理台路由迁入 M1，作为联邦调度系统的
标准管理接口。M8 端保留代理路由，向后兼容。

接口清单（共 13 个）：
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

鉴权方式：M8 Admin Token（X-M8-Token 请求头），与 M8 标准接口一致。
"""

from __future__ import annotations

import os
import time
from typing import Any, Optional

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, Header
from pydantic import BaseModel, ConfigDict, Field

logger = structlog.get_logger(__name__)

# ── 鉴权 ──────────────────────────────────────────────

M8_TOKEN_ENV = "M1_ADMIN_TOKEN"


def _verify_m8_token(x_m8_token: str = "") -> bool:
    """验证 M8 管理令牌"""
    expected = os.environ.get(M8_TOKEN_ENV, "")
    if not expected:
        # 未配置 Token 时，开发模式允许访问
        return True
    import hmac
    return hmac.compare_digest(x_m8_token, expected)


def _m8_auth_required(x_m8_token: str = Header(default="")) -> None:
    """M8 Token 鉴权依赖"""
    if not _verify_m8_token(x_m8_token):
        raise HTTPException(status_code=401, detail="M8 管理令牌无效")


# ── 统一响应格式 ──────────────────────────────────────

class ApiResponse(BaseModel):
    """统一 API 响应格式（与 M8 ApiResponse 对齐，便于代理透传）"""
    code: int = Field(default=0, description="状态码，0 表示成功")
    message: str = Field(default="ok", description="状态消息")
    data: Optional[Any] = Field(default=None, description="响应数据")
    trace_id: Optional[str] = Field(default=None, description="链路追踪 ID")
    timestamp: float = Field(
        default_factory=lambda: time.time(),
        description="响应时间戳（秒）",
    )

    @classmethod
    def success(cls, data: Any = None, message: str = "ok", trace_id: str | None = None) -> "ApiResponse":
        return cls(code=0, message=message, data=data, trace_id=trace_id)

    @classmethod
    def error(cls, code: int, message: str, data: Any = None, trace_id: str | None = None) -> "ApiResponse":
        return cls(code=code, message=message, data=data, trace_id=trace_id)


# ── 请求模型 ──────────────────────────────────────────

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


# ── 懒加载核心组件 ────────────────────────────────────

_external_registry: Any = None
_key_manager: Any = None


def _get_external_registry() -> Any:
    """懒加载外部 Agent 注册表"""
    global _external_registry
    if _external_registry is None:
        try:
            from src.federation.registry import ExternalAgentRegistry
            _external_registry = ExternalAgentRegistry()
        except (ImportError, RuntimeError) as exc:
            logger.warning("external_registry_init_failed", error=str(exc))
            raise HTTPException(status_code=500, detail=f"Agent 注册表初始化失败: {exc}")
    return _external_registry


def _get_key_manager() -> Any:
    """懒加载统一密钥管理器"""
    global _key_manager
    if _key_manager is None:
        try:
            from src.federation.key_manager import get_key_manager
            _key_manager = get_key_manager()
        except (ImportError, RuntimeError) as exc:
            logger.warning("key_manager_init_failed", error=str(exc))
            raise HTTPException(status_code=500, detail=f"密钥管理器初始化失败: {exc}")
    return _key_manager


def _profile_to_dict(profile: Any) -> dict[str, Any]:
    """将 ExternalAgentProfile 转换为字典"""
    if profile is None:
        return {}

    def _enum_value(val: Any) -> str:
        if val is None:
            return ""
        if hasattr(val, "value"):
            return val.value
        return str(val)

    result = {
        "agent_id": getattr(profile, "agent_id", ""),
        "display_name": getattr(profile, "display_name", ""),
        "provider": getattr(profile, "provider", ""),
        "agent_type": _enum_value(getattr(profile, "agent_type", "")),
        "capabilities": getattr(profile, "capabilities", []),
        "description": getattr(profile, "description", ""),
        "status": getattr(profile, "status", ""),
        "privacy_level": _enum_value(getattr(profile, "privacy_level", "")),
        "connection_type": _enum_value(getattr(profile, "connection_type", "")),
        "config": getattr(profile, "config", {}),
        "license": _enum_value(getattr(profile, "license", "")),
        "created_at": getattr(profile, "created_at", 0),
        "updated_at": getattr(profile, "updated_at", 0),
        "last_health_check": getattr(profile, "last_health_check", 0),
    }
    # 成本模型
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


# ── Router 实例 ───────────────────────────────────────

router = APIRouter(dependencies=[Depends(_m8_auth_required)])


# ═══════════════════════════════════════════════════════
# Agent 管理接口（6 个）
# ═══════════════════════════════════════════════════════

@router.get("")
async def list_agents(
    agent_type: Optional[str] = Query(None, description="按 Agent 类型筛选"),
    status: Optional[str] = Query(None, description="按状态筛选"),
):
    """获取 Agent 列表

    Args:
        agent_type: Agent 类型筛选 (llm/code/voice/etc)
        status: 状态筛选 (active/inactive/unhealthy)
    """
    try:
        ext_registry = _get_external_registry()

        # 类型转换
        type_filter = None
        if agent_type:
            try:
                from shared_models import ExternalAgentType
                type_filter = ExternalAgentType(agent_type)
            except ValueError:
                type_filter = None

        agents = ext_registry.list_agents(
            agent_type=type_filter,
            status=status,
        )

        items = [_profile_to_dict(a) for a in agents]

        return ApiResponse.success(
            data={
                "total": len(items),
                "items": items,
            }
        )
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("list_agents_failed", error=str(exc))
        return ApiResponse.error(code=500, message=f"获取 Agent 列表失败: {exc}")


@router.post("/register")
async def register_agent(req: AgentRegisterRequest):
    """注册新 Agent

    向 M1 联邦调度系统注册一个新的外部 Agent。
    """
    try:
        ext_registry = _get_external_registry()

        # 枚举类型转换
        from shared_models import (
            ExternalAgentType,
            AgentPrivacyLevel,
            ConnectionType,
            LicenseType,
        )

        # Agent 类型
        try:
            agent_type_enum = ExternalAgentType(req.agent_type)
        except ValueError:
            agent_type_enum = ExternalAgentType.LLM

        # 隐私等级
        try:
            privacy_enum = AgentPrivacyLevel(req.privacy_level)
        except ValueError:
            privacy_enum = AgentPrivacyLevel.STANDARD

        # 连接类型
        try:
            connection_enum = ConnectionType(req.connection_type)
        except ValueError:
            connection_enum = ConnectionType.API_KEY

        # 许可证
        try:
            license_enum = LicenseType(req.license)
        except ValueError:
            license_enum = LicenseType.OTHER

        # 构建 config
        config = {
            "mode": req.mode,
            "adapter_type": "external",
            "description": req.description,
        }
        if req.mode == "api" and req.api_provider:
            config["api_provider"] = req.api_provider
            if req.api_base_url:
                config["api_base_url"] = req.api_base_url
            if req.model_name:
                config["model_name"] = req.model_name

        # 成本模型默认值
        cost_model = req.cost_model or {
            "input_per_1k": 0.005,
            "output_per_1k": 0.015,
            "currency": "USD",
        }

        profile = ext_registry.register_agent(
            display_name=req.display_name,
            provider=req.provider,
            agent_type=agent_type_enum,
            capabilities=req.capabilities or ["text_generation"],
            cost_model=cost_model,
            privacy_level=privacy_enum,
            connection_type=connection_enum,
            config=config,
            api_key="",  # 密钥通过统一密钥管理器管理
            license=license_enum,
            confirm_license_risk=False,
        )

        return ApiResponse.success(
            data=_profile_to_dict(profile),
            message="Agent 注册成功",
        )
    except ValueError as exc:
        return ApiResponse.error(code=400, message=str(exc))
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("register_agent_failed", error=str(exc))
        return ApiResponse.error(code=500, message=f"注册 Agent 失败: {exc}")


@router.delete("/{agent_id}")
async def delete_agent(agent_id: str):
    """删除 Agent"""
    try:
        ext_registry = _get_external_registry()
        success = ext_registry.delete_agent(agent_id)

        if not success:
            return ApiResponse.error(code=404, message=f"未找到 Agent: {agent_id}")

        return ApiResponse.success(message="Agent 删除成功")
    except HTTPException:
        raise
    except Exception as exc:
        return ApiResponse.error(code=500, message=f"删除 Agent 失败: {exc}")


@router.post("/{agent_id}/health-check")
async def agent_health_check(agent_id: str):
    """Agent 健康检查

    测试指定 Agent 的连通性和可用性。
    """
    try:
        ext_registry = _get_external_registry()
        result = await ext_registry.check_health(agent_id)
        return ApiResponse.success(data=result, message="健康检查完成")
    except HTTPException:
        raise
    except Exception as exc:
        return ApiResponse.error(code=500, message=f"健康检查失败: {exc}")


@router.post("/{agent_id}/toggle")
async def toggle_agent(agent_id: str, req: AgentToggleRequest):
    """启用 / 禁用 Agent"""
    try:
        ext_registry = _get_external_registry()
        agent = ext_registry.get_agent(agent_id)

        if not agent:
            return ApiResponse.error(code=404, message=f"未找到 Agent: {agent_id}")

        new_status = "active" if req.enabled else "inactive"
        updated = ext_registry.update_agent(agent_id, status=new_status)

        if updated:
            return ApiResponse.success(
                data={"agent_id": agent_id, "status": new_status, "enabled": req.enabled},
                message=f"Agent 已{'启用' if req.enabled else '禁用'}",
            )
        else:
            return ApiResponse.error(code=500, message="更新状态失败")
    except HTTPException:
        raise
    except Exception as exc:
        return ApiResponse.error(code=500, message=f"切换 Agent 状态失败: {exc}")


@router.get("/stats")
async def agent_stats():
    """Agent 统计信息

    返回 Agent 总数、按类型/服务商/状态分类的统计数据，以及密钥统计。
    """
    try:
        ext_registry = _get_external_registry()
        stats = ext_registry.stats()

        # 补充密钥统计
        key_manager = _get_key_manager()
        key_stats = key_manager.stats()
        stats["keys_total"] = key_stats["total_keys"]
        stats["keys_providers"] = key_stats["providers"]

        return ApiResponse.success(data=stats)
    except HTTPException:
        raise
    except Exception as exc:
        return ApiResponse.error(code=500, message=f"获取统计信息失败: {exc}")


# ═══════════════════════════════════════════════════════
# 密钥管理接口（7 个）
# ═══════════════════════════════════════════════════════

@router.get("/keys")
async def list_keys():
    """获取密钥列表（掩码显示）

    返回所有已配置的 API 密钥，仅显示掩码预览，不返回明文。
    """
    try:
        key_manager = _get_key_manager()
        keys = key_manager.list_keys()

        return ApiResponse.success(
            data={
                "total": len(keys),
                "items": keys,
                "supported_providers": key_manager.list_supported_providers(),
            }
        )
    except HTTPException:
        raise
    except Exception as exc:
        return ApiResponse.error(code=500, message=f"获取密钥列表失败: {exc}")


@router.post("/keys")
async def save_key(req: KeySaveRequest):
    """保存 / 更新 API 密钥

    新增或更新指定服务商的 API 密钥。密钥将被 Fernet 加密后存储。
    """
    try:
        if not req.provider:
            return ApiResponse.error(code=400, message="服务商不能为空")
        if not req.api_key:
            return ApiResponse.error(code=400, message="API Key 不能为空")

        key_manager = _get_key_manager()
        result = key_manager.add_key(
            provider=req.provider,
            api_key=req.api_key,
            base_url=req.base_url,
            model=req.model,
        )

        if result.get("success"):
            return ApiResponse.success(
                data={
                    "provider": result["provider"],
                    "display_name": result["display_name"],
                    "key_preview": result["key_preview"],
                    "base_url": result["base_url"],
                    "model": result["model"],
                    "action": result["action"],
                },
                message=f"密钥{'更新' if result['action'] == 'updated' else '添加'}成功",
            )
        else:
            return ApiResponse.error(code=400, message=result.get("error", "保存失败"))
    except HTTPException:
        raise
    except Exception as exc:
        return ApiResponse.error(code=500, message=f"保存密钥失败: {exc}")


@router.delete("/keys/{provider}")
async def delete_key(provider: str):
    """删除指定服务商的 API 密钥"""
    try:
        key_manager = _get_key_manager()
        result = key_manager.remove_key(provider)

        if result.get("success"):
            return ApiResponse.success(message=f"{provider} 密钥已删除")
        else:
            return ApiResponse.error(code=404, message=result.get("error", "密钥不存在"))
    except HTTPException:
        raise
    except Exception as exc:
        return ApiResponse.error(code=500, message=f"删除密钥失败: {exc}")


@router.post("/keys/{provider}/health-check")
async def key_health_check(provider: str):
    """测试指定服务商密钥的连通性"""
    try:
        key_manager = _get_key_manager()
        result = await key_manager.health_check(provider)
        return ApiResponse.success(data=result, message="密钥健康检查完成")
    except HTTPException:
        raise
    except Exception as exc:
        return ApiResponse.error(code=500, message=f"密钥健康检查失败: {exc}")


@router.post("/keys/health-check-all")
async def key_health_check_all():
    """检查所有密钥的健康状态"""
    try:
        key_manager = _get_key_manager()
        result = await key_manager.health_check_all()
        return ApiResponse.success(data=result, message="全部密钥健康检查完成")
    except HTTPException:
        raise
    except Exception as exc:
        return ApiResponse.error(code=500, message=f"批量健康检查失败: {exc}")


@router.get("/keys/providers")
async def list_supported_providers():
    """获取支持的服务商列表及其默认配置"""
    try:
        key_manager = _get_key_manager()
        providers = key_manager.list_supported_providers()
        return ApiResponse.success(
            data={
                "total": len(providers),
                "items": providers,
            }
        )
    except HTTPException:
        raise
    except Exception as exc:
        return ApiResponse.error(code=500, message=f"获取服务商列表失败: {exc}")


# ═══════════════════════════════════════════════════════
# 模块初始化：注册路由到 FastAPI 应用
# ═══════════════════════════════════════════════════════

def register_agents_routes(
    app: Any,
    prefix: str = "/api/agents",
    external_registry: Any = None,
    key_manager: Any = None,
) -> None:
    """注册 Agent 管理路由到 FastAPI 应用

    Args:
        app: FastAPI 应用实例
        prefix: 路由前缀
        external_registry: 外部 Agent 注册表实例（可选，用于注入）
        key_manager: 密钥管理器实例（可选，用于注入）
    """
    global _external_registry, _key_manager

    # 支持依赖注入（便于测试和生产环境使用共享实例）
    if external_registry is not None:
        _external_registry = external_registry
    if key_manager is not None:
        _key_manager = key_manager

    app.include_router(router, prefix=prefix, tags=["Agent管理"])
    logger.info(
        "agents_routes_registered",
        prefix=prefix,
        has_external_registry=_external_registry is not None,
        has_key_manager=_key_manager is not None,
    )
