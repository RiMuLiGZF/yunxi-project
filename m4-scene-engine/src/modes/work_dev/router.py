"""工作开发模式 - API 路由.

提供工作开发模式的 RESTful API 接口，包括概览统计、
项目管理、任务看板、AI 代码助手、Git 管理、
代码沙箱、代码片段、可视化统计等功能。
"""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Header, Query

from src.database import get_session
from src.models import make_response
from src.modes.work_dev.models import (
    CodeChatRequest,
    CodeExecuteRequest,
    CodeGenerateRequest,
    GitCommitRequest,
    ProjectCreateRequest,
    ProjectUpdateRequest,
    SnippetCreateRequest,
    SnippetUpdateRequest,
    TaskCreateRequest,
    TaskStatusUpdateRequest,
    TaskUpdateRequest,
)
from src.modes.work_dev.service import WorkDevService

import structlog

logger = structlog.get_logger(__name__)

# ---------------------------------------------------------------------------
# 路由配置
# ---------------------------------------------------------------------------

router = APIRouter(
    prefix="/api/v1/work-dev",
    tags=["工作开发模式"],
)


# ---------------------------------------------------------------------------
# 辅助函数
# ---------------------------------------------------------------------------


def _get_service(x_user_id: str = "default") -> WorkDevService:
    """获取 WorkDevService 实例.

    Args:
        x_user_id: 用户 ID（从请求头获取）

    Returns:
        WorkDevService 实例
    """
    db = get_session()
    return WorkDevService(db, user_id=x_user_id)


# ---------------------------------------------------------------------------
# 概览接口
# ---------------------------------------------------------------------------


@router.get("/overview", summary="获取工作开发概览")
async def get_overview(
    x_user_id: str = Header("default", description="用户 ID"),
):
    """获取工作开发概览数据.

    包含统计数据、最近任务和最近提交。
    """
    try:
        service = _get_service(x_user_id)
        data = service.get_overview()
        return make_response(data=data)
    except Exception as e:
        logger.error("overview 异常", error=str(e), error_type=type(e).__name__, exc_info=True)
        return make_response(
            code=50001,
            message=f"获取概览失败: {e}",
            data={},
        )


# ---------------------------------------------------------------------------
# 项目管理接口
# ---------------------------------------------------------------------------


@router.get("/projects", summary="获取项目列表")
async def get_projects(
    status: Optional[str] = Query(None, description="按状态筛选"),
    category: Optional[str] = Query(None, description="按分类筛选"),
    x_user_id: str = Header("default", description="用户 ID"),
):
    """获取项目列表，支持按状态和分类筛选."""
    try:
        service = _get_service(x_user_id)
        data = service.list_projects(status=status, category=category)
        return make_response(data=data)
    except Exception as e:
        logger.error("projects 异常", error=str(e), error_type=type(e).__name__, exc_info=True)
        return make_response(
            code=50002,
            message=f"获取项目列表失败: {e}",
            data=[],
        )


@router.get("/projects/{project_id}", summary="获取项目详情")
async def get_project_detail(
    project_id: int,
    x_user_id: str = Header("default", description="用户 ID"),
):
    """获取项目详情，包含任务统计和最近提交."""
    try:
        service = _get_service(x_user_id)
        data = service.get_project_detail(project_id)
        if data is None:
            return make_response(
                code=40401,
                message="项目不存在",
                data={},
            )
        return make_response(data=data)
    except Exception as e:
        logger.error("project detail 异常", error=str(e), error_type=type(e).__name__, exc_info=True)
        return make_response(
            code=50003,
            message=f"获取项目详情失败: {e}",
            data={},
        )


@router.get("/projects/{project_id}/stats", summary="获取项目统计")
async def get_project_stats(
    project_id: int,
    x_user_id: str = Header("default", description="用户 ID"),
):
    """获取项目统计数据."""
    try:
        service = _get_service(x_user_id)
        data = service.get_project_stats(project_id)
        if data is None:
            return make_response(
                code=40401,
                message="项目不存在",
                data={},
            )
        return make_response(data=data)
    except Exception as e:
        logger.error("project stats 异常", error=str(e), error_type=type(e).__name__, exc_info=True)
        return make_response(
            code=50004,
            message=f"获取项目统计失败: {e}",
            data={},
        )


@router.post("/projects", summary="创建项目")
async def create_project(
    req: ProjectCreateRequest,
    x_user_id: str = Header("default", description="用户 ID"),
):
    """创建一个新项目."""
    try:
        service = _get_service(x_user_id)
        data = service.create_project(
            name=req.name,
            description=req.description,
            language=req.language,
            category=req.category,
            status=req.status,
        )
        return make_response(message="项目创建成功", data=data)
    except Exception as e:
        logger.error("create project 异常", error=str(e), error_type=type(e).__name__, exc_info=True)
        return make_response(
            code=50005,
            message=f"创建项目失败: {e}",
            data={},
        )


@router.put("/projects/{project_id}", summary="更新项目")
async def update_project(
    project_id: int,
    req: ProjectUpdateRequest,
    x_user_id: str = Header("default", description="用户 ID"),
):
    """更新项目信息，支持部分更新."""
    try:
        service = _get_service(x_user_id)
        update_data = req.dict(exclude_unset=True)
        data = service.update_project(project_id, update_data)
        if data is None:
            return make_response(
                code=40401,
                message="项目不存在",
                data={},
            )
        return make_response(message="更新成功", data=data)
    except Exception as e:
        logger.error("update project 异常", error=str(e), error_type=type(e).__name__, exc_info=True)
        return make_response(
            code=50006,
            message=f"更新项目失败: {e}",
            data={},
        )


@router.delete("/projects/{project_id}", summary="删除项目")
async def delete_project(
    project_id: int,
    x_user_id: str = Header("default", description="用户 ID"),
):
    """删除项目及其关联的任务、提交和代码片段."""
    try:
        service = _get_service(x_user_id)
        success = service.delete_project(project_id)
        if not success:
            return make_response(
                code=40401,
                message="项目不存在",
                data={},
            )
        return make_response(message="删除成功", data={})
    except Exception as e:
        logger.error("delete project 异常", error=str(e), error_type=type(e).__name__, exc_info=True)
        return make_response(
            code=50007,
            message=f"删除项目失败: {e}",
            data={},
        )


# ---------------------------------------------------------------------------
# 任务看板接口
# ---------------------------------------------------------------------------


@router.get("/tasks", summary="获取任务列表")
async def get_tasks(
    project_id: Optional[int] = Query(None, description="按项目 ID 筛选"),
    status: Optional[str] = Query(None, description="按状态筛选"),
    priority: Optional[str] = Query(None, description="按优先级筛选"),
    x_user_id: str = Header("default", description="用户 ID"),
):
    """获取任务列表，支持按项目、状态、优先级筛选."""
    try:
        service = _get_service(x_user_id)
        data = service.list_tasks(
            project_id=project_id, status=status, priority=priority
        )
        return make_response(data=data)
    except Exception as e:
        logger.error("tasks 异常", error=str(e), error_type=type(e).__name__, exc_info=True)
        return make_response(
            code=50008,
            message=f"获取任务列表失败: {e}",
            data=[],
        )


@router.get("/tasks/board", summary="获取任务看板")
async def get_task_board(
    project_id: Optional[int] = Query(None, description="按项目 ID 筛选"),
    x_user_id: str = Header("default", description="用户 ID"),
):
    """获取任务看板数据（按状态分组）."""
    try:
        service = _get_service(x_user_id)
        data = service.get_task_board(project_id=project_id)
        return make_response(data=data)
    except Exception as e:
        logger.error("task board 异常", error=str(e), error_type=type(e).__name__, exc_info=True)
        return make_response(
            code=50009,
            message=f"获取任务看板失败: {e}",
            data={"todo": [], "in_progress": [], "review": [], "done": []},
        )


@router.post("/tasks", summary="创建任务")
async def create_task(
    req: TaskCreateRequest,
    x_user_id: str = Header("default", description="用户 ID"),
):
    """创建一个新任务."""
    try:
        service = _get_service(x_user_id)
        data = service.create_task(
            title=req.title,
            description=req.description,
            status=req.status,
            priority=req.priority,
            project_id=req.project_id,
            assignee=req.assignee,
            due_date=req.due_date,
            tags=req.tags,
            estimate_hours=req.estimate_hours,
        )
        return make_response(message="任务创建成功", data=data)
    except Exception as e:
        logger.error("create task 异常", error=str(e), error_type=type(e).__name__, exc_info=True)
        return make_response(
            code=50010,
            message=f"创建任务失败: {e}",
            data={},
        )


@router.put("/tasks/{task_id}", summary="更新任务")
async def update_task(
    task_id: int,
    req: TaskUpdateRequest,
    x_user_id: str = Header("default", description="用户 ID"),
):
    """更新任务信息，支持部分更新."""
    try:
        service = _get_service(x_user_id)
        update_data = req.dict(exclude_unset=True)
        data = service.update_task(task_id, update_data)
        if data is None:
            return make_response(
                code=40402,
                message="任务不存在",
                data={},
            )
        return make_response(message="更新成功", data=data)
    except Exception as e:
        logger.error("update task 异常", error=str(e), error_type=type(e).__name__, exc_info=True)
        return make_response(
            code=50011,
            message=f"更新任务失败: {e}",
            data={},
        )


@router.patch("/tasks/{task_id}/status", summary="更新任务状态")
async def update_task_status(
    task_id: int,
    req: TaskStatusUpdateRequest,
    x_user_id: str = Header("default", description="用户 ID"),
):
    """更新任务状态（todo/in_progress/review/done）."""
    try:
        service = _get_service(x_user_id)
        data = service.update_task_status(task_id, req.status)
        if data is None:
            return make_response(
                code=40402,
                message="任务不存在",
                data={},
            )
        return make_response(message="状态已更新", data=data)
    except Exception as e:
        logger.error("update task status 异常", error=str(e), error_type=type(e).__name__, exc_info=True)
        return make_response(
            code=50012,
            message=f"更新任务状态失败: {e}",
            data={},
        )


@router.delete("/tasks/{task_id}", summary="删除任务")
async def delete_task(
    task_id: int,
    x_user_id: str = Header("default", description="用户 ID"),
):
    """删除任务."""
    try:
        service = _get_service(x_user_id)
        success = service.delete_task(task_id)
        if not success:
            return make_response(
                code=40402,
                message="任务不存在",
                data={},
            )
        return make_response(message="删除成功", data={})
    except Exception as e:
        logger.error("delete task 异常", error=str(e), error_type=type(e).__name__, exc_info=True)
        return make_response(
            code=50013,
            message=f"删除任务失败: {e}",
            data={},
        )


# ---------------------------------------------------------------------------
# Git 管理接口
# ---------------------------------------------------------------------------


@router.get("/commits", summary="获取提交记录")
async def get_commits(
    project_id: Optional[int] = Query(None, description="按项目 ID 筛选"),
    limit: int = Query(20, description="返回条数限制", ge=1, le=100),
    x_user_id: str = Header("default", description="用户 ID"),
):
    """获取提交记录列表."""
    try:
        service = _get_service(x_user_id)
        data = service.list_commits(project_id=project_id, limit=limit)
        return make_response(data=data)
    except Exception as e:
        logger.error("commits 异常", error=str(e), error_type=type(e).__name__, exc_info=True)
        return make_response(
            code=50014,
            message=f"获取提交记录失败: {e}",
            data=[],
        )


@router.get("/commits/stats", summary="获取提交统计")
async def get_commit_stats(
    project_id: Optional[int] = Query(None, description="按项目 ID 筛选"),
    x_user_id: str = Header("default", description="用户 ID"),
):
    """获取提交统计数据（含每日提交趋势）."""
    try:
        service = _get_service(x_user_id)
        data = service.get_commit_stats(project_id=project_id)
        return make_response(data=data)
    except Exception as e:
        logger.error("commit stats 异常", error=str(e), error_type=type(e).__name__, exc_info=True)
        return make_response(
            code=50015,
            message=f"获取提交统计失败: {e}",
            data={},
        )


@router.post("/commits", summary="创建模拟提交")
async def create_commit(
    req: GitCommitRequest,
    x_user_id: str = Header("default", description="用户 ID"),
):
    """创建一条模拟提交记录."""
    try:
        service = _get_service(x_user_id)
        data = service.create_commit(
            message=req.message,
            project_id=req.project_id,
        )
        return make_response(message="提交成功", data=data)
    except Exception as e:
        logger.error("create commit 异常", error=str(e), error_type=type(e).__name__, exc_info=True)
        return make_response(
            code=50016,
            message=f"创建提交失败: {e}",
            data={},
        )


@router.get("/branches", summary="获取分支列表")
async def get_branches(
    x_user_id: str = Header("default", description="用户 ID"),
):
    """获取分支列表（模拟数据）."""
    try:
        service = _get_service(x_user_id)
        data = service.list_branches()
        return make_response(data=data)
    except Exception as e:
        logger.error("branches 异常", error=str(e), error_type=type(e).__name__, exc_info=True)
        return make_response(
            code=50017,
            message=f"获取分支列表失败: {e}",
            data=[],
        )


# ---------------------------------------------------------------------------
# 代码沙箱接口
# ---------------------------------------------------------------------------


@router.get("/code/languages", summary="获取支持的编程语言")
async def get_supported_languages(
    x_user_id: str = Header("default", description="用户 ID"),
):
    """获取支持的编程语言列表及安装状态."""
    try:
        service = _get_service(x_user_id)
        data = service.get_supported_languages()
        return make_response(data=data)
    except Exception as e:
        logger.error("languages 异常", error=str(e), error_type=type(e).__name__, exc_info=True)
        return make_response(
            code=50018,
            message=f"获取语言列表失败: {e}",
            data=[],
        )


@router.post("/code/execute", summary="执行代码")
async def execute_code(
    req: CodeExecuteRequest,
    x_user_id: str = Header("default", description="用户 ID"),
):
    """在沙箱环境中执行代码（带安全检测）."""
    try:
        service = _get_service(x_user_id)
        data = service.execute_code(
            code=req.code,
            language=req.language,
            stdin=req.stdin,
        )
        return make_response(message="执行完成", data=data)
    except Exception as e:
        logger.error("execute code 异常", error=str(e), error_type=type(e).__name__, exc_info=True)
        return make_response(
            code=50019,
            message=f"代码执行失败: {e}",
            data={},
        )


# ---------------------------------------------------------------------------
# AI 代码助手接口
# ---------------------------------------------------------------------------


@router.post("/code/generate", summary="AI 代码操作")
async def generate_code(
    req: CodeGenerateRequest,
    x_user_id: str = Header("default", description="用户 ID"),
):
    """AI 代码操作（生成/审查/调试/优化/重构/解释/测试生成）.

    当前为简化版（模板匹配 fallback），预留 LLM 接入点。
    """
    try:
        service = _get_service(x_user_id)
        data = service.generate_code(
            prompt=req.prompt,
            language=req.language,
            operation_type=req.operation_type,
        )
        return make_response(message="操作完成", data=data)
    except Exception as e:
        logger.error("generate code 异常", error=str(e), error_type=type(e).__name__, exc_info=True)
        return make_response(
            code=50020,
            message=f"代码操作失败: {e}",
            data={},
        )


@router.post("/code/chat", summary="代码对话")
async def code_chat(
    req: CodeChatRequest,
    x_user_id: str = Header("default", description="用户 ID"),
):
    """代码多轮对话.

    当前为简化版（模板匹配 fallback），预留 LLM 接入点。
    """
    try:
        service = _get_service(x_user_id)
        data = service.code_chat(
            message=req.message,
            language=req.language,
            conversation_id=req.conversation_id,
            context_code=req.context_code,
        )
        return make_response(message="ok", data=data)
    except Exception as e:
        logger.error("code chat 异常", error=str(e), error_type=type(e).__name__, exc_info=True)
        return make_response(
            code=50021,
            message=f"代码对话失败: {e}",
            data={},
        )


@router.get("/code/chat/conversations", summary="获取代码对话会话列表")
async def list_chat_conversations(
    x_user_id: str = Header("default", description="用户 ID"),
):
    """获取代码对话会话列表."""
    try:
        service = _get_service(x_user_id)
        data = service.list_chat_sessions()
        return make_response(data={"conversations": data, "total": len(data)})
    except Exception as e:
        logger.error("chat sessions 异常", error=str(e), error_type=type(e).__name__, exc_info=True)
        return make_response(
            code=50022,
            message=f"获取会话列表失败: {e}",
            data={"conversations": [], "total": 0},
        )


@router.get("/code/chat/conversations/{conversation_id}", summary="获取对话会话详情")
async def get_chat_conversation(
    conversation_id: str,
    x_user_id: str = Header("default", description="用户 ID"),
):
    """获取单个代码对话会话详情."""
    try:
        service = _get_service(x_user_id)
        data = service.get_chat_session(conversation_id)
        return make_response(data=data)
    except Exception as e:
        logger.error("chat session detail 异常", error=str(e), error_type=type(e).__name__, exc_info=True)
        return make_response(
            code=50023,
            message=f"获取会话详情失败: {e}",
            data={},
        )


@router.delete("/code/chat/conversations/{conversation_id}", summary="删除对话会话")
async def delete_chat_conversation(
    conversation_id: str,
    x_user_id: str = Header("default", description="用户 ID"),
):
    """删除代码对话会话."""
    try:
        service = _get_service(x_user_id)
        success = service.delete_chat_session(conversation_id)
        return make_response(message="会话已删除", data={"deleted": success})
    except Exception as e:
        logger.error("delete chat session 异常", error=str(e), error_type=type(e).__name__, exc_info=True)
        return make_response(
            code=50024,
            message=f"删除会话失败: {e}",
            data={},
        )


@router.get("/code/ai/status", summary="AI 代码助手状态")
async def code_ai_status(
    x_user_id: str = Header("default", description="用户 ID"),
):
    """检查 AI 代码助手的服务状态."""
    try:
        return make_response(data={
            "available": False,
            "provider": None,
            "model": None,
            "mode": "fallback（模板匹配）",
        })
    except Exception as e:
        logger.error("ai status 异常", error=str(e), error_type=type(e).__name__, exc_info=True)
        return make_response(
            code=50025,
            message=f"获取状态失败: {e}",
            data={},
        )


# ---------------------------------------------------------------------------
# 代码片段接口
# ---------------------------------------------------------------------------


@router.get("/snippets", summary="获取代码片段列表")
async def get_snippets(
    language: Optional[str] = Query(None, description="按语言筛选"),
    tag: Optional[str] = Query(None, description="按标签筛选"),
    only_favorite: bool = Query(False, description="只显示收藏的"),
    x_user_id: str = Header("default", description="用户 ID"),
):
    """获取代码片段列表."""
    try:
        service = _get_service(x_user_id)
        data = service.list_snippets(
            language=language, tag=tag, only_favorite=only_favorite
        )
        return make_response(data=data)
    except Exception as e:
        logger.error("snippets 异常", error=str(e), error_type=type(e).__name__, exc_info=True)
        return make_response(
            code=50026,
            message=f"获取代码片段失败: {e}",
            data=[],
        )


@router.post("/snippets", summary="创建代码片段")
async def create_snippet(
    req: SnippetCreateRequest,
    x_user_id: str = Header("default", description="用户 ID"),
):
    """创建一个新的代码片段."""
    try:
        service = _get_service(x_user_id)
        data = service.create_snippet(
            title=req.title,
            language=req.language,
            code=req.code,
            description=req.description,
            tags=req.tags,
            project_id=req.project_id,
        )
        return make_response(message="片段创建成功", data=data)
    except Exception as e:
        logger.error("create snippet 异常", error=str(e), error_type=type(e).__name__, exc_info=True)
        return make_response(
            code=50027,
            message=f"创建代码片段失败: {e}",
            data={},
        )


@router.put("/snippets/{snippet_id}", summary="更新代码片段")
async def update_snippet(
    snippet_id: int,
    req: SnippetUpdateRequest,
    x_user_id: str = Header("default", description="用户 ID"),
):
    """更新代码片段信息."""
    try:
        service = _get_service(x_user_id)
        update_data = req.dict(exclude_unset=True)
        data = service.update_snippet(snippet_id, update_data)
        if data is None:
            return make_response(
                code=40403,
                message="代码片段不存在",
                data={},
            )
        return make_response(message="更新成功", data=data)
    except Exception as e:
        logger.error("update snippet 异常", error=str(e), error_type=type(e).__name__, exc_info=True)
        return make_response(
            code=50028,
            message=f"更新代码片段失败: {e}",
            data={},
        )


@router.delete("/snippets/{snippet_id}", summary="删除代码片段")
async def delete_snippet(
    snippet_id: int,
    x_user_id: str = Header("default", description="用户 ID"),
):
    """删除代码片段."""
    try:
        service = _get_service(x_user_id)
        success = service.delete_snippet(snippet_id)
        if not success:
            return make_response(
                code=40403,
                message="代码片段不存在",
                data={},
            )
        return make_response(message="删除成功", data={})
    except Exception as e:
        logger.error("delete snippet 异常", error=str(e), error_type=type(e).__name__, exc_info=True)
        return make_response(
            code=50029,
            message=f"删除代码片段失败: {e}",
            data={},
        )


# ---------------------------------------------------------------------------
# 快速操作 & 最近活动
# ---------------------------------------------------------------------------


@router.get("/quick-actions", summary="获取快速操作列表")
async def get_quick_actions(
    x_user_id: str = Header("default", description="用户 ID"),
):
    """获取快速操作列表."""
    try:
        service = _get_service(x_user_id)
        data = service.get_quick_actions()
        return make_response(data=data)
    except Exception as e:
        logger.error("quick actions 异常", error=str(e), error_type=type(e).__name__, exc_info=True)
        return make_response(
            code=50030,
            message=f"获取快速操作失败: {e}",
            data=[],
        )


@router.get("/activity", summary="获取最近活动")
async def get_recent_activity(
    limit: int = Query(10, description="返回条数限制", ge=1, le=50),
    x_user_id: str = Header("default", description="用户 ID"),
):
    """获取最近活动列表."""
    try:
        service = _get_service(x_user_id)
        data = service.get_recent_activity(limit=limit)
        return make_response(data=data)
    except Exception as e:
        logger.error("activity 异常", error=str(e), error_type=type(e).__name__, exc_info=True)
        return make_response(
            code=50031,
            message=f"获取活动列表失败: {e}",
            data=[],
        )
