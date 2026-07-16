"""人际关系模式 - API 路由.

提供人际关系模式的 RESTful API 接口，包括概览、联系人管理、
交往记录、社交提醒、情商课程、关系图谱等功能。
"""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Header, Query

from src.models.db import get_session
from src.models import make_response
from src.modes.social_relation.models import (
    ContactCreateRequest,
    ContactUpdateRequest,
    InteractionCreateRequest,
    ReminderCreateRequest,
    ReminderUpdateRequest,
)
from src.modes.social_relation.service import SocialService

import structlog

logger = structlog.get_logger(__name__)

# ---------------------------------------------------------------------------
# 路由配置
# ---------------------------------------------------------------------------

router = APIRouter(
    prefix="/api/v1/social-relation",
    tags=["人际关系模式"],
)


# ---------------------------------------------------------------------------
# 辅助函数
# ---------------------------------------------------------------------------


def _get_service(x_user_id: str = "default") -> SocialService:
    """获取 SocialService 实例.

    Args:
        x_user_id: 用户 ID（从请求头获取）

    Returns:
        SocialService 实例
    """
    db = get_session()
    return SocialService(db, user_id=x_user_id)


# ---------------------------------------------------------------------------
# 概览接口
# ---------------------------------------------------------------------------


@router.get("/overview", summary="获取人际关系概览")
async def get_overview(
    x_user_id: str = Header("default", description="用户 ID"),
):
    """获取人际关系概览数据.

    包含统计数据和 Top3 亲密联系人。
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
# 关系图谱接口
# ---------------------------------------------------------------------------


@router.get("/relation-graph", summary="获取关系图谱")
async def get_relation_graph(
    x_user_id: str = Header("default", description="用户 ID"),
):
    """获取人际关系可视化图谱数据."""
    try:
        service = _get_service(x_user_id)
        data = service.build_relation_graph()
        return make_response(data=data)
    except Exception as e:
        logger.error("relation-graph 异常", error=str(e), error_type=type(e).__name__, exc_info=True)
        return make_response(
            code=50002,
            message=f"获取关系图谱失败: {e}",
            data={"nodes": [], "links": []},
        )


# ---------------------------------------------------------------------------
# 联系人接口
# ---------------------------------------------------------------------------


@router.get("/contacts", summary="获取联系人列表")
async def get_contacts(
    relation: Optional[str] = Query(None, description="按关系类型筛选"),
    tag: Optional[str] = Query(None, description="按标签筛选"),
    x_user_id: str = Header("default", description="用户 ID"),
):
    """获取联系人列表，支持按关系类型和标签筛选."""
    try:
        service = _get_service(x_user_id)
        data = service.list_contacts(relation=relation, tag=tag)
        return make_response(data=data)
    except Exception as e:
        logger.error("contacts 异常", error=str(e), error_type=type(e).__name__, exc_info=True)
        return make_response(
            code=50003,
            message=f"获取联系人列表失败: {e}",
            data=[],
        )


@router.get("/contacts/{cid}", summary="获取联系人详情")
async def get_contact_detail(
    cid: int,
    x_user_id: str = Header("default", description="用户 ID"),
):
    """获取联系人详情，包含交往记录."""
    try:
        service = _get_service(x_user_id)
        data = service.get_contact_detail(cid)
        if data is None:
            return make_response(
                code=40401,
                message="联系人不存在",
                data={},
            )
        return make_response(data=data)
    except Exception as e:
        logger.error("contact detail 异常", error=str(e), error_type=type(e).__name__, exc_info=True)
        return make_response(
            code=50004,
            message=f"获取联系人详情失败: {e}",
            data={},
        )


@router.post("/contacts", summary="新增联系人")
async def create_contact(
    req: ContactCreateRequest,
    x_user_id: str = Header("default", description="用户 ID"),
):
    """新增一个联系人."""
    try:
        service = _get_service(x_user_id)
        data = service.create_contact(
            name=req.name,
            avatar=req.avatar,
            relation=req.relation,
            tags=req.tags,
        )
        return make_response(message="联系人添加成功", data=data)
    except Exception as e:
        logger.error("create contact 异常", error=str(e), error_type=type(e).__name__, exc_info=True)
        return make_response(
            code=50005,
            message=f"添加联系人失败: {e}",
            data={},
        )


@router.put("/contacts/{cid}", summary="更新联系人信息")
async def update_contact(
    cid: int,
    req: ContactUpdateRequest,
    x_user_id: str = Header("default", description="用户 ID"),
):
    """更新联系人信息，支持部分更新."""
    try:
        service = _get_service(x_user_id)
        # 只传递非 None 的字段
        update_data = req.dict(exclude_unset=True)
        data = service.update_contact(cid, update_data)
        if data is None:
            return make_response(
                code=40401,
                message="联系人不存在",
                data={},
            )
        return make_response(message="更新成功", data=data)
    except Exception as e:
        logger.error("update contact 异常", error=str(e), error_type=type(e).__name__, exc_info=True)
        return make_response(
            code=50006,
            message=f"更新联系人失败: {e}",
            data={},
        )


@router.delete("/contacts/{cid}", summary="删除联系人")
async def delete_contact(
    cid: int,
    x_user_id: str = Header("default", description="用户 ID"),
):
    """删除联系人及其相关的交往记录和提醒."""
    try:
        service = _get_service(x_user_id)
        success = service.delete_contact(cid)
        if not success:
            return make_response(
                code=40401,
                message="联系人不存在",
                data={},
            )
        return make_response(message="删除成功", data={})
    except Exception as e:
        logger.error("delete contact 异常", error=str(e), error_type=type(e).__name__, exc_info=True)
        return make_response(
            code=50007,
            message=f"删除联系人失败: {e}",
            data={},
        )


# ---------------------------------------------------------------------------
# 交往记录接口
# ---------------------------------------------------------------------------


@router.get("/interactions", summary="获取交往记录")
async def get_interactions(
    contact_id: Optional[int] = Query(None, description="按联系人 ID 筛选"),
    limit: int = Query(20, description="返回条数限制", ge=1, le=100),
    x_user_id: str = Header("default", description="用户 ID"),
):
    """获取交往记录列表，支持按联系人和数量筛选."""
    try:
        service = _get_service(x_user_id)
        data = service.list_interactions(contact_id=contact_id, limit=limit)
        return make_response(data=data)
    except Exception as e:
        logger.error("interactions 异常", error=str(e), error_type=type(e).__name__, exc_info=True)
        return make_response(
            code=50008,
            message=f"获取交往记录失败: {e}",
            data=[],
        )


@router.post("/interactions", summary="记录交往")
async def create_interaction(
    req: InteractionCreateRequest,
    x_user_id: str = Header("default", description="用户 ID"),
):
    """新增一条交往记录，同时更新联系人统计信息."""
    try:
        service = _get_service(x_user_id)
        data = service.create_interaction(
            contact_id=req.contact_id,
            contact_name=req.contact_name,
            type=req.type,
            content=req.content,
            emotion=req.emotion,
            duration_minutes=req.duration_minutes,
            location=req.location,
        )
        return make_response(message="记录成功", data=data)
    except Exception as e:
        logger.error("create interaction 异常", error=str(e), error_type=type(e).__name__, exc_info=True)
        return make_response(
            code=50009,
            message=f"记录交往失败: {e}",
            data={},
        )


# ---------------------------------------------------------------------------
# 社交提醒接口
# ---------------------------------------------------------------------------


@router.get("/reminders", summary="获取社交提醒")
async def get_reminders(
    x_user_id: str = Header("default", description="用户 ID"),
):
    """获取所有社交提醒列表."""
    try:
        service = _get_service(x_user_id)
        data = service.list_reminders()
        return make_response(data=data)
    except Exception as e:
        logger.error("reminders 异常", error=str(e), error_type=type(e).__name__, exc_info=True)
        return make_response(
            code=50010,
            message=f"获取提醒列表失败: {e}",
            data=[],
        )


@router.post("/reminders", summary="添加提醒")
async def create_reminder(
    req: ReminderCreateRequest,
    x_user_id: str = Header("default", description="用户 ID"),
):
    """新增一条社交提醒."""
    try:
        service = _get_service(x_user_id)
        data = service.create_reminder(
            type=req.type,
            title=req.title,
            description=req.description,
            date=req.date,
            priority=req.priority,
        )
        return make_response(message="提醒创建成功", data=data)
    except Exception as e:
        logger.error("create reminder 异常", error=str(e), error_type=type(e).__name__, exc_info=True)
        return make_response(
            code=50011,
            message=f"创建提醒失败: {e}",
            data={},
        )


@router.patch("/reminders/{rid}", summary="更新提醒状态")
async def update_reminder(
    rid: int,
    req: ReminderUpdateRequest,
    x_user_id: str = Header("default", description="用户 ID"),
):
    """更新提醒状态（pending/done/cancelled）."""
    try:
        service = _get_service(x_user_id)
        if req.status is None:
            return make_response(
                code=40001,
                message="没有需要更新的字段",
                data={},
            )
        data = service.update_reminder_status(rid, req.status)
        if data is None:
            return make_response(
                code=40402,
                message="提醒不存在",
                data={},
            )
        return make_response(message="更新成功", data=data)
    except Exception as e:
        logger.error("update reminder 异常", error=str(e), error_type=type(e).__name__, exc_info=True)
        return make_response(
            code=50012,
            message=f"更新提醒失败: {e}",
            data={},
        )


@router.delete("/reminders/{rid}", summary="删除提醒")
async def delete_reminder(
    rid: int,
    x_user_id: str = Header("default", description="用户 ID"),
):
    """删除一条社交提醒."""
    try:
        service = _get_service(x_user_id)
        success = service.delete_reminder(rid)
        if not success:
            return make_response(
                code=40402,
                message="提醒不存在",
                data={},
            )
        return make_response(message="删除成功", data={})
    except Exception as e:
        logger.error("delete reminder 异常", error=str(e), error_type=type(e).__name__, exc_info=True)
        return make_response(
            code=50013,
            message=f"删除提醒失败: {e}",
            data={},
        )


# ---------------------------------------------------------------------------
# 情商课程接口
# ---------------------------------------------------------------------------


@router.get("/eq-courses", summary="获取情商课程")
async def get_eq_courses(
    x_user_id: str = Header("default", description="用户 ID"),
):
    """获取情商提升课程列表."""
    try:
        service = _get_service(x_user_id)
        data = service.list_eq_courses()
        return make_response(data=data)
    except Exception as e:
        logger.error("eq-courses 异常", error=str(e), error_type=type(e).__name__, exc_info=True)
        return make_response(
            code=50014,
            message=f"获取情商课程失败: {e}",
            data=[],
        )


@router.get("/eq-score", summary="获取情商得分")
async def get_eq_score(
    x_user_id: str = Header("default", description="用户 ID"),
):
    """获取情商综合得分及各维度分数."""
    try:
        service = _get_service(x_user_id)
        data = service.get_eq_score()
        return make_response(data=data)
    except Exception as e:
        logger.error("eq-score 异常", error=str(e), error_type=type(e).__name__, exc_info=True)
        return make_response(
            code=50015,
            message=f"获取情商得分失败: {e}",
            data={},
        )
