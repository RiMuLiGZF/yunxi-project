"""技能管理路由.

提供技能列表查询、详情获取、技能执行、function calling 工具定义，
以及场景技能绑定管理接口。
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Path, Query, Request

try:
    from src.models import (
        SCENE_DEFINITIONS,
        SkillExecuteRequest,
        SceneSkillsUpdateRequest,
        make_response,
    )
    from src.services.skill_executor import get_skill_executor
except ImportError:
    from models import (  # type: ignore
        SCENE_DEFINITIONS,
        SkillExecuteRequest,
        SceneSkillsUpdateRequest,
        make_response,
    )
    from services.skill_executor import get_skill_executor  # type: ignore


router = APIRouter(prefix="/api/v1", tags=["技能管理"])


# ---------------------------------------------------------------------------
# 场景技能绑定存储（内存）
# ---------------------------------------------------------------------------

#: 场景技能绑定配置: {scene_id: [skill_binding, ...]}
_scene_skills: dict[str, list[dict[str, Any]]] = {}


def _init_scene_skills() -> None:
    """初始化场景技能绑定配置.

    从场景定义中读取默认的 skills 配置。
    """
    global _scene_skills
    for scene_id, scene_def in SCENE_DEFINITIONS.items():
        default_skills = scene_def.get("skills", [])
        _scene_skills[scene_id] = [
            {
                "name": s.get("name", ""),
                "auto_trigger": s.get("auto_trigger", []),
                "default_params": s.get("default_params", {}),
                "required": s.get("required", False),
            }
            for s in default_skills
        ]


_init_scene_skills()


# ---------------------------------------------------------------------------
# 辅助函数
# ---------------------------------------------------------------------------

def _get_skill_executor(request: Request):
    """从 request state 获取技能执行器，没有则使用全局单例."""
    executor = getattr(request.app.state, "skill_executor", None)
    if executor is None:
        executor = get_skill_executor()
    return executor


# ---------------------------------------------------------------------------
# 技能 - 列表
# ---------------------------------------------------------------------------

@router.get("/skills", summary="获取可用技能列表")
async def list_skills(
    request: Request,
    category: str = Query("", description="技能分类筛选（可选）"),
):
    """获取所有可用的技能列表.

    查询参数:
        category: 技能分类筛选（可选），可选值：development / productivity / communication / system
    """
    executor = _get_skill_executor(request)

    skills = executor.list_skills(category=category or None)

    return make_response(data={
        "skills": skills,
        "total": len(skills),
        "category": category or "all",
    })


# ---------------------------------------------------------------------------
# 技能 - 详情
# ---------------------------------------------------------------------------

@router.get("/skills/{skill_name}", summary="获取技能详情")
async def get_skill_detail(
    request: Request,
    skill_name: str = Path(..., description="技能名称"),
):
    """获取指定技能的详细信息.

    路径参数:
        skill_name: 技能名称
    """
    executor = _get_skill_executor(request)

    skill = executor.get_skill(skill_name)
    if skill is None:
        return make_response(
            code=40401,
            message=f"技能不存在: {skill_name}",
            data={"skill_name": skill_name},
        )

    return make_response(data=skill.get_info())


# ---------------------------------------------------------------------------
# 技能 - 执行
# ---------------------------------------------------------------------------

@router.post("/skills/{skill_name}/execute", summary="执行技能")
async def execute_skill(
    request: Request,
    skill_name: str = Path(..., description="技能名称"),
    body: SkillExecuteRequest | None = None,
):
    """执行指定的技能.

    路径参数:
        skill_name: 技能名称
    请求体:
        params: 技能执行参数字典
        context: 执行上下文字典（可选）
    """
    executor = _get_skill_executor(request)

    # 检查技能是否存在
    skill = executor.get_skill(skill_name)
    if skill is None:
        return make_response(
            code=40401,
            message=f"技能不存在: {skill_name}",
            data={"skill_name": skill_name},
        )

    # 解析参数
    params = body.params if body else {}
    context = body.context if body else {}

    # 执行技能
    result = executor.execute_skill(
        skill_name=skill_name,
        params=params,
        context=context,
    )

    if not result.get("success", False):
        return make_response(
            code=50001,
            message=result.get("message", "技能执行失败"),
            data=result,
        )

    return make_response(data=result)


# ---------------------------------------------------------------------------
# 技能 - function calling 工具定义
# ---------------------------------------------------------------------------

@router.get("/skills/tools", summary="获取 function calling 格式的工具定义")
async def get_skill_tools(
    request: Request,
    category: str = Query("", description="技能分类筛选（可选）"),
):
    """获取所有技能的 function calling 格式工具定义，供 Agent 框架使用.

    查询参数:
        category: 技能分类筛选（可选）
    """
    executor = _get_skill_executor(request)

    if category:
        # 按分类筛选
        skills = executor.list_skills(category=category)
        tools = []
        for skill_info in skills:
            skill = executor.get_skill(skill_info["name"])
            if skill:
                tools.append(skill.get_tool_definition())
    else:
        tools = executor.get_tool_definitions()

    return make_response(data={
        "tools": tools,
        "total": len(tools),
        "category": category or "all",
    })


# ---------------------------------------------------------------------------
# 场景技能绑定 - 获取
# ---------------------------------------------------------------------------

@router.get("/scene/{scene_id}/skills", summary="获取场景绑定的技能")
async def get_scene_skills(
    request: Request,
    scene_id: str = Path(..., description="场景ID"),
):
    """获取指定场景绑定的技能列表.

    路径参数:
        scene_id: 场景ID
    """
    global _scene_skills

    # 验证场景
    if scene_id not in SCENE_DEFINITIONS:
        return make_response(
            code=40401,
            message=f"场景不存在: {scene_id}",
            data={},
        )

    skills = _scene_skills.get(scene_id, [])

    return make_response(data={
        "scene_id": scene_id,
        "skills": skills,
        "total": len(skills),
    })


# ---------------------------------------------------------------------------
# 场景技能绑定 - 更新
# ---------------------------------------------------------------------------

@router.post("/scene/{scene_id}/skills", summary="更新场景技能绑定")
async def update_scene_skills(
    request: Request,
    scene_id: str = Path(..., description="场景ID"),
    body: SceneSkillsUpdateRequest | None = None,
):
    """为指定场景绑定技能（全量更新）.

    路径参数:
        scene_id: 场景ID
    请求体:
        skills: 技能绑定配置列表
    """
    global _scene_skills

    # 验证场景
    if scene_id not in SCENE_DEFINITIONS:
        return make_response(
            code=40401,
            message=f"场景不存在: {scene_id}",
            data={},
        )

    if body is None:
        return make_response(
            code=40001,
            message="请求体不能为空",
            data={},
        )

    # 验证并格式化技能配置
    executor = _get_skill_executor(request)
    formatted_skills = []
    valid_triggers = {"on_enter", "on_leave"}

    for skill_cfg in body.skills:
        # 验证技能是否存在
        skill = executor.get_skill(skill_cfg.name)
        if skill is None:
            return make_response(
                code=40002,
                message=f"技能不存在: {skill_cfg.name}",
                data={"skill_name": skill_cfg.name},
            )

        # 验证 auto_trigger 取值
        for trigger in skill_cfg.auto_trigger:
            if trigger not in valid_triggers:
                return make_response(
                    code=40003,
                    message=f"无效的触发时机: {trigger}，必须是 on_enter / on_leave",
                    data={"skill_name": skill_cfg.name},
                )

        formatted_skills.append({
            "name": skill_cfg.name,
            "auto_trigger": skill_cfg.auto_trigger or [],
            "default_params": skill_cfg.default_params or {},
            "required": skill_cfg.required,
        })

    # 更新绑定
    _scene_skills[scene_id] = formatted_skills

    # 同步更新场景定义中的 skills（影响切换自动执行）
    if scene_id in SCENE_DEFINITIONS:
        SCENE_DEFINITIONS[scene_id]["skills"] = formatted_skills

    return make_response(data={
        "scene_id": scene_id,
        "skills": formatted_skills,
        "total": len(formatted_skills),
        "success": True,
    })


# ---------------------------------------------------------------------------
# 技能 - 健康检查
# ---------------------------------------------------------------------------

@router.get("/skills/{skill_name}/health", summary="技能健康检查")
async def skill_health_check(
    request: Request,
    skill_name: str = Path(..., description="技能名称"),
):
    """检查指定技能是否健康可用.

    路径参数:
        skill_name: 技能名称
    """
    executor = _get_skill_executor(request)

    skill = executor.get_skill(skill_name)
    if skill is None:
        return make_response(
            code=40401,
            message=f"技能不存在: {skill_name}",
            data={"skill_name": skill_name, "healthy": False},
        )

    try:
        healthy = skill.health_check()
    except Exception as e:
        return make_response(
            code=50002,
            message=f"健康检查异常: {e}",
            data={"skill_name": skill_name, "healthy": False},
        )

    return make_response(data={
        "skill_name": skill_name,
        "healthy": healthy,
        "status": "healthy" if healthy else "unhealthy",
    })


# ---------------------------------------------------------------------------
# 技能 - 执行日志
# ---------------------------------------------------------------------------

@router.get("/skills/logs", summary="获取技能执行日志")
async def get_skill_logs(
    request: Request,
    limit: int = Query(20, description="返回条数", ge=1, le=200),
    skill_name: str = Query("", description="按技能名筛选（可选）"),
):
    """获取技能执行日志（按时间倒序）.

    查询参数:
        limit: 返回条数，默认 20
        skill_name: 按技能名筛选（可选）
    """
    executor = _get_skill_executor(request)

    logs = executor.get_execution_logs(
        limit=limit,
        skill_name=skill_name or None,
    )

    return make_response(data={
        "logs": logs,
        "total": len(logs),
        "limit": limit,
        "skill_name": skill_name or "all",
    })
