"""
M8 人际关系模式 API

P3-15: 数据库持久化改造
- 优先使用 SQLite 数据库（SQLAlchemy + Repository 模式）
- 数据库不可用时回退到内存数据（向前兼容）
- 所有 API 需要 JWT 认证
"""
from fastapi import APIRouter, Depends
from pydantic import BaseModel
from datetime import datetime, timedelta
from typing import Optional, List
from sqlalchemy.orm import Session

from ..models import get_db
from ..auth import get_current_user
from ..repositories.social_repository import SocialRepository

router = APIRouter()


# ========== 内存 fallback 数据 ==========
# 当数据库不可用时使用，保持向前兼容

_contacts = [
    {"id": 1, "name": "张小明", "avatar": "👨‍💼", "relation": "同事", "closeness": 85, "last_contact": "昨天", "contact_count": 12, "tags": ["工作", "朋友"]},
    {"id": 2, "name": "李雨晴", "avatar": "👩‍🎓", "relation": "同学", "closeness": 92, "last_contact": "3天前", "contact_count": 28, "tags": ["同学", "挚友"]},
    {"id": 3, "name": "王大伟", "avatar": "👨‍🏫", "relation": "导师", "closeness": 70, "last_contact": "1周前", "contact_count": 8, "tags": ["学业", "导师"]},
    {"id": 4, "name": "陈思琪", "avatar": "👩‍💻", "relation": "同事", "closeness": 78, "last_contact": "今天", "contact_count": 15, "tags": ["工作", "项目组"]},
    {"id": 5, "name": "刘子豪", "avatar": "🧑‍🎨", "relation": "朋友", "closeness": 88, "last_contact": "2天前", "contact_count": 35, "tags": ["朋友", "兴趣"]},
    {"id": 6, "name": "赵雅婷", "avatar": "👩‍⚕️", "relation": "家人", "closeness": 95, "last_contact": "昨天", "contact_count": 50, "tags": ["家人", "姐姐"]},
    {"id": 7, "name": "孙浩然", "avatar": "👨‍🔬", "relation": "合作伙伴", "closeness": 65, "last_contact": "2周前", "contact_count": 6, "tags": ["工作", "合作"]},
    {"id": 8, "name": "周雨萱", "avatar": "👩‍🎨", "relation": "朋友", "closeness": 80, "last_contact": "5天前", "contact_count": 20, "tags": ["朋友", "兴趣"]},
]

_relation_nodes = [
    {"id": 1, "name": "我", "x": 300, "y": 200, "level": 0, "color": "#1890FF"},
    {"id": 2, "name": "张小明", "x": 180, "y": 100, "level": 1, "color": "#52C41A"},
    {"id": 3, "name": "李雨晴", "x": 420, "y": 80, "level": 1, "color": "#722ED1"},
    {"id": 4, "name": "王大伟", "x": 100, "y": 200, "level": 2, "color": "#FAAD14"},
    {"id": 5, "name": "陈思琪", "x": 500, "y": 180, "level": 1, "color": "#13C2C2"},
    {"id": 6, "name": "刘子豪", "x": 200, "y": 320, "level": 1, "color": "#EB2F96"},
    {"id": 7, "name": "赵雅婷", "x": 400, "y": 320, "level": 1, "color": "#F5222D"},
    {"id": 8, "name": "孙浩然", "x": 80, "y": 320, "level": 2, "color": "#FA8C16"},
]

_relation_links = [
    {"source": 1, "target": 2, "strength": 0.85},
    {"source": 1, "target": 3, "strength": 0.92},
    {"source": 1, "target": 4, "strength": 0.7},
    {"source": 1, "target": 5, "strength": 0.78},
    {"source": 1, "target": 6, "strength": 0.88},
    {"source": 1, "target": 7, "strength": 0.95},
    {"source": 1, "target": 8, "strength": 0.65},
    {"source": 2, "target": 5, "strength": 0.6},
    {"source": 6, "target": 8, "strength": 0.5},
]

_interactions = [
    {"id": 1, "contact_id": 4, "contact_name": "陈思琪", "type": "聊天", "content": "讨论了项目进度，确认了下一阶段目标", "date": "今天 14:30", "emotion": "positive"},
    {"id": 2, "contact_id": 6, "contact_name": "赵雅婷", "type": "电话", "content": "聊了聊最近的生活，姐姐说周末回家吃饭", "date": "昨天 20:00", "emotion": "positive"},
    {"id": 3, "contact_id": 2, "contact_name": "张小明", "type": "会议", "content": "项目周会，同步各模块进展", "date": "昨天 10:00", "emotion": "neutral"},
    {"id": 4, "contact_id": 3, "contact_name": "李雨晴", "type": "微信", "content": "约了周末一起看电影", "date": "3天前", "emotion": "positive"},
    {"id": 5, "contact_id": 5, "contact_name": "刘子豪", "type": "聚餐", "content": "和朋友们一起吃了火锅，聊得很开心", "date": "5天前", "emotion": "positive"},
    {"id": 6, "contact_id": 7, "contact_name": "孙浩然", "type": "邮件", "content": "确认了合作项目的合同细节", "date": "2周前", "emotion": "neutral"},
]

_reminders = [
    {"id": 1, "type": "birthday", "title": "李雨晴生日", "description": "下周三是李雨晴的生日，记得准备礼物", "date": "3天后", "priority": "high", "status": "pending"},
    {"id": 2, "type": "contact", "title": "久未联系", "description": "和王大伟导师已经1周没联系了，有空问候一下", "date": "1周前", "priority": "medium", "status": "pending"},
    {"id": 3, "type": "anniversary", "title": "入职纪念日", "description": "和张小明共事一周年纪念日", "date": "5天后", "priority": "low", "status": "pending"},
    {"id": 4, "type": "event", "title": "同学聚会", "description": "高中同学聚会，记得参加", "date": "下周六", "priority": "medium", "status": "pending"},
]

_eq_courses = [
    {"id": 1, "title": "情绪识别与表达", "progress": 80, "total_lessons": 10, "completed_lessons": 8, "description": "学习识别自己和他人的情绪，掌握有效表达方法"},
    {"id": 2, "title": "有效沟通技巧", "progress": 50, "total_lessons": 12, "completed_lessons": 6, "description": "提升沟通效率，建立良好的人际关系"},
    {"id": 3, "title": "冲突管理与解决", "progress": 20, "total_lessons": 8, "completed_lessons": 2, "description": "学会以积极的方式处理人际冲突"},
    {"id": 4, "title": "同理心培养", "progress": 65, "total_lessons": 6, "completed_lessons": 4, "description": "站在他人角度思考，增进理解与信任"},
]

_social_stats = {
    "total_contacts": 8,
    "total_interactions": 125,
    "avg_closeness": 81,
    "eq_score": 78,
    "week_interactions": 12,
    "streak_days": 15,
}


# ========== 请求模型 ==========

class ContactCreateRequest(BaseModel):
    name: str
    avatar: str = "👤"
    relation: str = "朋友"
    tags: List[str] = []


class InteractionCreateRequest(BaseModel):
    contact_id: int
    contact_name: str
    type: str
    content: str
    emotion: str = "neutral"
    duration_minutes: int = 0
    location: str = ""


class ReminderCreateRequest(BaseModel):
    type: str
    title: str
    description: str = ""
    date: str = ""
    priority: str = "medium"


class ContactUpdateRequest(BaseModel):
    name: Optional[str] = None
    avatar: Optional[str] = None
    relation: Optional[str] = None
    relationship_type: Optional[str] = None
    closeness: Optional[int] = None
    importance: Optional[int] = None
    tags: Optional[List[str]] = None
    phone: Optional[str] = None
    email: Optional[str] = None
    note: Optional[str] = None


class ReminderUpdateRequest(BaseModel):
    status: Optional[str] = None


# ========== 辅助函数 ==========

def _get_repo(db: Session, user: dict) -> Optional[SocialRepository]:
    """获取 SocialRepository，失败返回 None（使用内存 fallback）"""
    try:
        user_id = user.get("user_id", 1)
        # 如果 user 字典中没有 user_id，默认用 1
        if not isinstance(user_id, int):
            user_id = 1
        return SocialRepository(db, user_id=user_id)
    except Exception as e:
        print(f"[Social] 数据库不可用，使用内存 fallback: {e}")
        return None


def _build_relation_graph(contacts: List[dict]) -> dict:
    """根据联系人动态构建关系图谱"""
    if not contacts:
        return {"nodes": _relation_nodes, "links": _relation_links}

    # 中心节点
    nodes = [{"id": 0, "name": "我", "x": 300, "y": 200, "level": 0, "color": "#1890FF"}]
    links = []

    # 颜色映射
    color_map = {
        "同事": "#52C41A",
        "同学": "#722ED1",
        "导师": "#FAAD14",
        "朋友": "#EB2F96",
        "家人": "#F5222D",
        "合作伙伴": "#FA8C16",
    }

    import math
    total = len(contacts)
    radius_level1 = 120
    radius_level2 = 180

    for idx, c in enumerate(contacts):
        # 按亲密度分级
        closeness = c.get("closeness", 50)
        level = 1 if closeness >= 75 else 2
        radius = radius_level1 if level == 1 else radius_level2

        # 均匀分布在圆周上
        angle = 2 * math.pi * idx / total - math.pi / 2
        x = int(300 + radius * math.cos(angle))
        y = int(200 + radius * math.sin(angle))

        color = color_map.get(c.get("relation", ""), "#13C2C2")

        nodes.append({
            "id": c["id"],
            "name": c["name"],
            "x": x,
            "y": y,
            "level": level,
            "color": color,
        })
        links.append({
            "source": 0,
            "target": c["id"],
            "strength": round(closeness / 100, 2),
        })

    return {"nodes": nodes, "links": links}


# ========== 概览 ==========

@router.get("/overview")
async def get_overview(
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """人际关系概览"""
    repo = _get_repo(db, current_user)
    if repo:
        try:
            contacts = repo.list_contacts()
            contact_dicts = [c.to_dict() for c in contacts]
            total_contacts = repo.count_contacts()
            total_interactions = repo.count_interactions()
            avg_closeness = int(repo.avg_importance())
            eq_data = repo.get_eq_score()
            week_interactions = repo.count_week_interactions()

            stats = {
                "total_contacts": total_contacts,
                "total_interactions": total_interactions,
                "avg_closeness": avg_closeness,
                "eq_score": eq_data["score"],
                "week_interactions": week_interactions,
                "streak_days": 15,  # 连续打卡天数（待实现）
            }
            top_contacts = sorted(contact_dicts, key=lambda x: x["closeness"], reverse=True)[:3]

            return {
                "code": 0,
                "message": "ok",
                "data": {
                    "stats": stats,
                    "top_contacts": top_contacts,
                },
            }
        except Exception as e:
            print(f"[Social] overview 查询失败，使用 fallback: {e}")

    # 内存 fallback
    return {
        "code": 0,
        "message": "ok",
        "data": {
            "stats": _social_stats,
            "top_contacts": _contacts[:3],
        },
    }


# ========== 关系图谱 ==========

@router.get("/relation-graph")
async def get_relation_graph(
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """获取关系图谱"""
    repo = _get_repo(db, current_user)
    if repo:
        try:
            contacts = repo.list_contacts()
            contact_dicts = [c.to_dict() for c in contacts]
            graph = _build_relation_graph(contact_dicts)
            return {"code": 0, "message": "ok", "data": graph}
        except Exception as e:
            print(f"[Social] relation-graph 查询失败，使用 fallback: {e}")

    # 内存 fallback
    return {
        "code": 0,
        "message": "ok",
        "data": {
            "nodes": _relation_nodes,
            "links": _relation_links,
        },
    }


# ========== 联系人 ==========

@router.get("/contacts")
async def get_contacts(
    relation: Optional[str] = None,
    tag: Optional[str] = None,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """获取联系人列表"""
    repo = _get_repo(db, current_user)
    if repo:
        try:
            contacts = repo.list_contacts(relation=relation, tag=tag)
            result = [c.to_dict() for c in contacts]
            return {"code": 0, "message": "ok", "data": result}
        except Exception as e:
            print(f"[Social] contacts 查询失败，使用 fallback: {e}")

    # 内存 fallback
    result = _contacts
    if relation:
        result = [c for c in result if c["relation"] == relation]
    if tag:
        result = [c for c in result if tag in c["tags"]]
    return {"code": 0, "message": "ok", "data": result}


@router.get("/contacts/{cid}")
async def get_contact_detail(
    cid: int,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """获取联系人详情"""
    repo = _get_repo(db, current_user)
    if repo:
        try:
            contact = repo.get_contact(cid)
            if not contact:
                return {"code": 404, "message": "联系人不存在", "data": None}

            interactions = repo.list_interactions(contact_id=cid)
            interaction_dicts = [i.to_dict() for i in interactions]

            return {
                "code": 0,
                "message": "ok",
                "data": {
                    "contact": contact.to_dict(),
                    "interactions": interaction_dicts,
                },
            }
        except Exception as e:
            print(f"[Social] contact detail 查询失败，使用 fallback: {e}")

    # 内存 fallback
    contact = next((c for c in _contacts if c["id"] == cid), None)
    if not contact:
        return {"code": 404, "message": "联系人不存在", "data": None}

    interactions = [i for i in _interactions if i["contact_id"] == cid]

    return {
        "code": 0,
        "message": "ok",
        "data": {
            "contact": contact,
            "interactions": interactions,
        },
    }


@router.post("/contacts")
async def create_contact(
    req: ContactCreateRequest,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """新增联系人"""
    repo = _get_repo(db, current_user)
    if repo:
        try:
            contact = repo.create_contact(
                name=req.name,
                avatar=req.avatar,
                relation=req.relation,
                tags=req.tags,
            )
            return {"code": 0, "message": "联系人添加成功", "data": contact.to_dict()}
        except Exception as e:
            print(f"[Social] create_contact 失败，使用 fallback: {e}")

    # 内存 fallback
    cid = max((c["id"] for c in _contacts), default=0) + 1
    contact = {
        "id": cid,
        "name": req.name,
        "avatar": req.avatar,
        "relation": req.relation,
        "closeness": 50,
        "last_contact": "刚刚",
        "contact_count": 0,
        "tags": req.tags,
    }
    _contacts.append(contact)
    return {"code": 0, "message": "联系人添加成功", "data": contact}


@router.put("/contacts/{cid}")
async def update_contact(
    cid: int,
    req: ContactUpdateRequest,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """更新联系人信息"""
    repo = _get_repo(db, current_user)
    if repo:
        try:
            update_data = req.dict(exclude_unset=True)
            contact = repo.update_contact(cid, **update_data)
            if not contact:
                return {"code": 404, "message": "联系人不存在", "data": None}
            return {"code": 0, "message": "更新成功", "data": contact.to_dict()}
        except Exception as e:
            print(f"[Social] update_contact 失败，使用 fallback: {e}")

    # 内存 fallback
    contact = next((c for c in _contacts if c["id"] == cid), None)
    if not contact:
        return {"code": 404, "message": "联系人不存在", "data": None}

    if req.name is not None:
        contact["name"] = req.name
    if req.avatar is not None:
        contact["avatar"] = req.avatar
    if req.relation is not None:
        contact["relation"] = req.relation
    if req.closeness is not None:
        contact["closeness"] = req.closeness
    if req.tags is not None:
        contact["tags"] = req.tags

    return {"code": 0, "message": "更新成功", "data": contact}


@router.delete("/contacts/{cid}")
async def delete_contact(
    cid: int,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """删除联系人"""
    repo = _get_repo(db, current_user)
    if repo:
        try:
            success = repo.delete_contact(cid)
            if not success:
                return {"code": 404, "message": "联系人不存在", "data": None}
            return {"code": 0, "message": "删除成功", "data": None}
        except Exception as e:
            print(f"[Social] delete_contact 失败，使用 fallback: {e}")

    # 内存 fallback
    global _contacts, _interactions, _reminders
    original_len = len(_contacts)
    _contacts = [c for c in _contacts if c["id"] != cid]
    _interactions = [i for i in _interactions if i["contact_id"] != cid]
    _reminders = [r for r in _reminders if r.get("contact_id") != cid]
    if len(_contacts) == original_len:
        return {"code": 404, "message": "联系人不存在", "data": None}
    return {"code": 0, "message": "删除成功", "data": None}


# ========== 交往记录 ==========

@router.get("/interactions")
async def get_interactions(
    contact_id: Optional[int] = None,
    limit: int = 20,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """获取交往记录"""
    repo = _get_repo(db, current_user)
    if repo:
        try:
            interactions = repo.list_interactions(contact_id=contact_id, limit=limit)
            result = [i.to_dict() for i in interactions]
            return {"code": 0, "message": "ok", "data": result}
        except Exception as e:
            print(f"[Social] interactions 查询失败，使用 fallback: {e}")

    # 内存 fallback
    result = _interactions
    if contact_id:
        result = [i for i in result if i["contact_id"] == contact_id]
    return {"code": 0, "message": "ok", "data": result[:limit]}


@router.post("/interactions")
async def create_interaction(
    req: InteractionCreateRequest,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """记录交往"""
    repo = _get_repo(db, current_user)
    if repo:
        try:
            interaction = repo.create_interaction(
                contact_id=req.contact_id,
                contact_name=req.contact_name,
                type=req.type,
                content=req.content,
                emotion=req.emotion,
                duration_minutes=req.duration_minutes,
                location=req.location,
            )
            # 更新联系人统计
            repo.update_contact_stats(req.contact_id)
            return {"code": 0, "message": "记录成功", "data": interaction.to_dict()}
        except Exception as e:
            print(f"[Social] create_interaction 失败，使用 fallback: {e}")

    # 内存 fallback
    iid = max((i["id"] for i in _interactions), default=0) + 1
    interaction = {
        "id": iid,
        "contact_id": req.contact_id,
        "contact_name": req.contact_name,
        "type": req.type,
        "content": req.content,
        "date": "刚刚",
        "emotion": req.emotion,
        "duration_minutes": req.duration_minutes,
        "location": req.location,
    }
    _interactions.insert(0, interaction)

    # 更新联系人
    contact = next((c for c in _contacts if c["id"] == req.contact_id), None)
    if contact:
        contact["last_contact"] = "刚刚"
        contact["contact_count"] += 1

    return {"code": 0, "message": "记录成功", "data": interaction}


# ========== 社交提醒 ==========

@router.get("/reminders")
async def get_reminders(
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """获取社交提醒"""
    repo = _get_repo(db, current_user)
    if repo:
        try:
            reminders = repo.list_reminders()
            result = [r.to_dict() for r in reminders]
            return {"code": 0, "message": "ok", "data": result}
        except Exception as e:
            print(f"[Social] reminders 查询失败，使用 fallback: {e}")

    # 内存 fallback
    return {"code": 0, "message": "ok", "data": _reminders}


@router.post("/reminders")
async def create_reminder(
    req: ReminderCreateRequest,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """添加提醒"""
    repo = _get_repo(db, current_user)
    if repo:
        try:
            reminder = repo.create_reminder(
                type=req.type,
                title=req.title,
                description=req.description,
                date=req.date,
                priority=req.priority,
            )
            return {"code": 0, "message": "提醒创建成功", "data": reminder.to_dict()}
        except Exception as e:
            print(f"[Social] create_reminder 失败，使用 fallback: {e}")

    # 内存 fallback
    rid = max((r["id"] for r in _reminders), default=0) + 1
    reminder = {
        "id": rid,
        "type": req.type,
        "title": req.title,
        "description": req.description,
        "date": req.date,
        "priority": req.priority,
    }
    _reminders.append(reminder)
    return {"code": 0, "message": "提醒创建成功", "data": reminder}


@router.patch("/reminders/{rid}")
async def update_reminder(
    rid: int,
    req: ReminderUpdateRequest,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """更新提醒（支持状态切换）"""
    repo = _get_repo(db, current_user)
    if repo:
        try:
            if req.status is not None:
                reminder = repo.update_reminder_status(rid, req.status)
                if not reminder:
                    return {"code": 404, "message": "提醒不存在", "data": None}
                return {"code": 0, "message": "更新成功", "data": reminder.to_dict()}
            return {"code": 400, "message": "没有需要更新的字段", "data": None}
        except Exception as e:
            print(f"[Social] update_reminder 失败，使用 fallback: {e}")

    # 内存 fallback
    reminder = next((r for r in _reminders if r["id"] == rid), None)
    if not reminder:
        return {"code": 404, "message": "提醒不存在", "data": None}

    if req.status is not None:
        reminder["status"] = req.status

    return {"code": 0, "message": "更新成功", "data": reminder}


@router.delete("/reminders/{rid}")
async def delete_reminder(
    rid: int,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """删除提醒"""
    repo = _get_repo(db, current_user)
    if repo:
        try:
            success = repo.delete_reminder(rid)
            if not success:
                return {"code": 404, "message": "提醒不存在", "data": None}
            return {"code": 0, "message": "删除成功", "data": None}
        except Exception as e:
            print(f"[Social] delete_reminder 失败，使用 fallback: {e}")

    # 内存 fallback
    global _reminders
    _reminders = [r for r in _reminders if r["id"] != rid]
    return {"code": 0, "message": "删除成功", "data": None}


# ========== 情商提升 ==========

@router.get("/eq-courses")
async def get_eq_courses(
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """获取情商课程"""
    repo = _get_repo(db, current_user)
    if repo:
        try:
            lessons = repo.list_eq_lessons()
            result = [l.to_dict() for l in lessons]
            return {"code": 0, "message": "ok", "data": result}
        except Exception as e:
            print(f"[Social] eq-courses 查询失败，使用 fallback: {e}")

    # 内存 fallback
    return {"code": 0, "message": "ok", "data": _eq_courses}


@router.get("/eq-score")
async def get_eq_score(
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """获取情商得分"""
    repo = _get_repo(db, current_user)
    if repo:
        try:
            eq_data = repo.get_eq_score()
            return {
                "code": 0,
                "message": "ok",
                "data": eq_data,
            }
        except Exception as e:
            print(f"[Social] eq-score 查询失败，使用 fallback: {e}")

    # 内存 fallback
    return {
        "code": 0,
        "message": "ok",
        "data": {
            "score": _social_stats["eq_score"],
            "level": "良好",
            "dimensions": [
                {"name": "自我认知", "score": 82},
                {"name": "情绪管理", "score": 75},
                {"name": "自我激励", "score": 80},
                {"name": "同理心", "score": 78},
                {"name": "社交技能", "score": 76},
            ],
        },
    }
