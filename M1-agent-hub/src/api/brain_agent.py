"""
Brain Agent API 路由（M1 Agent Hub）

将 M8 brain 模块中的 Agent/工具/多Agent团队相关接口迁移到 M1，
核心业务逻辑复用 shared/business 下的模块，仅迁移 API 路由层。

接口清单（共 9 个）：
工具系统（3 个）：
  1. GET    /api/brain/tools/list      - 工具列表
  2. GET    /api/brain/tools/stats     - 工具统计
  3. POST   /api/brain/tools/call/{tool_name} - 工具调用

单 Agent（2 个）：
  4. POST   /api/brain/agent/run       - Agent 运行
  5. GET    /api/brain/agent/stats     - Agent 统计

多 Agent 团队（4 个）：
  6. GET    /api/brain/team/profile    - 团队配置
  7. POST   /api/brain/team/query      - 团队查询
  8. GET    /api/brain/team/stats      - 团队统计
  9. GET    /api/brain/team/tasks      - 团队任务历史

鉴权方式：M8 Admin Token（X-M8-Token 请求头），与 agents API 一致。
"""

from __future__ import annotations

import os
import time
from typing import Any, Dict, List, Optional

import structlog
from fastapi import APIRouter, Depends, HTTPException, Header, Query
from pydantic import BaseModel, Field

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

class AgentRunRequest(BaseModel):
    """Agent 运行请求"""
    query: str = Field(..., description="用户查询/任务")
    available_tools: Optional[List[str]] = Field(
        default=None,
        description="可用工具名称列表，None 表示全部可用",
    )


class TeamQueryRequest(BaseModel):
    """多 Agent 团队查询请求"""
    query: str = Field(..., description="查询内容")


# ── 懒加载核心组件 ────────────────────────────────────

_tool_registry: Any = None
_agent_engine: Any = None
_agent_team: Any = None
_builtin_tools_registered = False
_team_registered = False


def _get_tool_registry() -> Any:
    """懒加载工具注册表"""
    global _tool_registry, _builtin_tools_registered
    if _tool_registry is None:
        try:
            from shared.business.tool_system import get_tool_registry
            # 确保内置工具已注册
            if not _builtin_tools_registered:
                from shared.business.builtin_tools import _ensure_registered
                _ensure_registered()
                _builtin_tools_registered = True
            _tool_registry = get_tool_registry()
        except (ImportError, RuntimeError) as exc:
            logger.warning("tool_registry_init_failed", error=str(exc))
            raise HTTPException(status_code=500, detail=f"工具系统初始化失败: {exc}")
    return _tool_registry


def _get_agent_engine() -> Any:
    """懒加载 Agent 引擎"""
    global _agent_engine
    if _agent_engine is None:
        try:
            from shared.business.agent_engine import get_agent_engine
            _agent_engine = get_agent_engine()
        except (ImportError, RuntimeError) as exc:
            logger.warning("agent_engine_init_failed", error=str(exc))
            raise HTTPException(status_code=500, detail=f"Agent 引擎初始化失败: {exc}")
    return _agent_engine


def _get_agent_team() -> Any:
    """懒加载多 Agent 团队"""
    global _agent_team, _team_registered
    if _agent_team is None:
        try:
            # 确保团队已注册
            if not _team_registered:
                from shared.business.agent_team import _ensure_team_registered
                _ensure_team_registered()
                _team_registered = True
            from shared.business.multi_agent import get_agent_team
            _agent_team = get_agent_team()
        except (ImportError, RuntimeError) as exc:
            logger.warning("agent_team_init_failed", error=str(exc))
            raise HTTPException(status_code=500, detail=f"Agent 团队初始化失败: {exc}")
    return _agent_team


# ── Router 实例 ───────────────────────────────────────

router = APIRouter(dependencies=[Depends(_m8_auth_required)])


# ═══════════════════════════════════════════════════════
# 工具系统接口（3 个）
# ═══════════════════════════════════════════════════════

@router.get("/tools/list")
async def list_tools(
    category: Optional[str] = Query(None, description="按工具分类筛选"),
):
    """获取可用工具列表

    Args:
        category: 工具分类 (general/calculation/search/memory/knowledge/system/creative/utility)
    """
    try:
        registry = _get_tool_registry()
        tools = registry.list_tools(category=category)

        return ApiResponse.success(
            data={
                "tools": [t.get_description_for_llm() for t in tools],
                "total": len(tools),
                "categories": list(set(t.category for t in tools)),
            }
        )
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("list_tools_failed", error=str(exc))
        return ApiResponse.error(code=500, message=f"获取工具列表失败: {exc}")


@router.get("/tools/stats")
async def tool_stats():
    """获取工具调用统计"""
    try:
        registry = _get_tool_registry()
        stats = registry.get_stats()
        history = registry.get_call_history(limit=20)

        return ApiResponse.success(
            data={
                "stats": stats,
                "recent_calls": history,
            }
        )
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("tool_stats_failed", error=str(exc))
        return ApiResponse.error(code=500, message=f"获取工具统计失败: {exc}")


@router.post("/tools/call/{tool_name}")
async def call_tool(
    tool_name: str,
    params: Optional[Dict[str, Any]] = None,
):
    """调用指定工具

    Args:
        tool_name: 工具名称
        params: 工具参数
    """
    try:
        registry = _get_tool_registry()
        context = {"user_id": "api_caller"}

        result = registry.call_tool(tool_name, params or {}, context=context)

        return ApiResponse(
            code=0 if result.success else 1,
            message="ok" if result.success else result.error or "调用失败",
            data=result.to_dict(),
        )
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("call_tool_failed", tool_name=tool_name, error=str(exc))
        return ApiResponse.error(code=500, message=f"工具调用失败: {exc}")


# ═══════════════════════════════════════════════════════
# 单 Agent 接口（2 个）
# ═══════════════════════════════════════════════════════

@router.post("/agent/run")
async def agent_run(req: AgentRunRequest):
    """执行 Agent 任务

    使用 ReAct 模式执行用户任务，支持多步推理和工具调用。
    """
    try:
        engine = _get_agent_engine()
        context = {"user_id": "api_caller"}

        result = engine.run(
            query=req.query,
            context=context,
            available_tools=req.available_tools,
        )

        return ApiResponse(
            code=0 if result.success else 1,
            message="ok" if result.success else result.error or "执行失败",
            data=result.to_dict(),
        )
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("agent_run_failed", error=str(exc))
        return ApiResponse.error(code=500, message=f"Agent 执行失败: {exc}")


@router.get("/agent/stats")
async def agent_stats():
    """获取 Agent 统计信息"""
    try:
        engine = _get_agent_engine()
        stats = engine.get_stats()
        history = engine.get_execution_history(limit=10)

        return ApiResponse.success(
            data={
                "stats": stats,
                "recent_executions": history,
            }
        )
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("agent_stats_failed", error=str(exc))
        return ApiResponse.error(code=500, message=f"获取 Agent 统计失败: {exc}")


# ═══════════════════════════════════════════════════════
# 多 Agent 团队接口（4 个）
# ═══════════════════════════════════════════════════════

@router.get("/team/profile")
async def team_profile():
    """获取 Agent 团队简介"""
    try:
        team = _get_agent_team()
        profile = team.get_team_profile()

        return ApiResponse.success(data=profile)
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("team_profile_failed", error=str(exc))
        return ApiResponse.error(code=500, message=f"获取团队简介失败: {exc}")


@router.post("/team/query")
async def team_query(req: TeamQueryRequest):
    """团队协作处理查询

    多 Agent 团队协作处理用户查询，自动分发任务到合适的专业 Agent。
    """
    try:
        team = _get_agent_team()
        context = {"user_id": "api_caller"}

        result = team.handle_query(req.query, context=context)

        return ApiResponse(
            code=0 if result.success else 1,
            message="ok" if result.success else result.error or "执行失败",
            data=result.to_dict(),
        )
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("team_query_failed", error=str(exc))
        return ApiResponse.error(code=500, message=f"团队查询失败: {exc}")


@router.get("/team/stats")
async def team_stats():
    """获取团队统计信息"""
    try:
        team = _get_agent_team()
        stats = team.get_stats()
        history = team.get_task_history(limit=20)

        return ApiResponse.success(
            data={
                "stats": stats,
                "recent_tasks": history,
            }
        )
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("team_stats_failed", error=str(exc))
        return ApiResponse.error(code=500, message=f"获取团队统计失败: {exc}")


@router.get("/team/tasks")
async def team_tasks(
    limit: int = Query(20, description="任务数量限制", ge=1, le=100),
):
    """获取团队任务历史"""
    try:
        team = _get_agent_team()
        tasks = team.get_task_history(limit=limit)

        return ApiResponse.success(
            data={
                "tasks": tasks,
                "total": len(tasks),
            }
        )
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("team_tasks_failed", error=str(exc))
        return ApiResponse.error(code=500, message=f"获取团队任务失败: {exc}")


# ═══════════════════════════════════════════════════════
# 模块初始化：注册路由到 FastAPI 应用
# ═══════════════════════════════════════════════════════

def register_brain_agent_routes(
    app: Any,
    prefix: str = "/api/brain",
    tool_registry: Any = None,
    agent_engine: Any = None,
    agent_team: Any = None,
) -> None:
    """注册 Brain Agent 路由到 FastAPI 应用

    Args:
        app: FastAPI 应用实例
        prefix: 路由前缀
        tool_registry: 工具注册表实例（可选，用于注入）
        agent_engine: Agent 引擎实例（可选，用于注入）
        agent_team: 多 Agent 团队实例（可选，用于注入）
    """
    global _tool_registry, _agent_engine, _agent_team

    # 支持依赖注入（便于测试和生产环境使用共享实例）
    if tool_registry is not None:
        _tool_registry = tool_registry
    if agent_engine is not None:
        _agent_engine = agent_engine
    if agent_team is not None:
        _agent_team = agent_team

    app.include_router(router, prefix=prefix, tags=["Brain-Agent"])
    logger.info(
        "brain_agent_routes_registered",
        prefix=prefix,
        has_tool_registry=_tool_registry is not None,
        has_agent_engine=_agent_engine is not None,
        has_agent_team=_agent_team is not None,
    )
