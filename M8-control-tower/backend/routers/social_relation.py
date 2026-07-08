"""人际关系模式 API"""
from fastapi import APIRouter
from pydantic import BaseModel
from datetime import datetime, timedelta
from typing import Optional, List

router = APIRouter()

# ========== 内存数据 ==========

# 联系人
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

# 关系图谱节点
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

# 交往记录
_interactions = [
    {"id": 1, "contact_id": 4, "contact_name": "陈思琪", "type": "聊天", "content": "讨论了项目进度，确认了下一阶段目标", "date": "今天 14:30", "emotion": "positive"},
    {"id": 2, "contact_id": 6, "contact_name": "赵雅婷", "type": "电话", "content": "聊了聊最近的生活，姐姐说周末回家吃饭", "date": "昨天 20:00", "emotion": "positive"},
    {"id": 3, "contact_id": 2, "contact_name": "张小明", "type": "会议", "content": "项目周会，同步各模块进展", "date": "昨天 10:00", "emotion": "neutral"},
    {"id": 4, "contact_id": 3, "contact_name": "李雨晴", "type": "微信", "content": "约了周末一起看电影", "date": "3天前", "emotion": "positive"},
    {"id": 5, "contact_id": 5, "contact_name": "刘子豪", "type": "聚餐", "content": "和朋友们一起吃了火锅，聊得很开心", "date": "5天前", "emotion": "positive"},
    {"id": 6, "contact_id": 7, "contact_name": "孙浩然", "type": "邮件", "content": "确认了合作项目的合同细节", "date": "2周前", "emotion": "neutral"},
]

# 社交提醒
_reminders = [
    {"id": 1, "type": "birthday", "title": "李雨晴生日", "description": "下周三是李雨晴的生日，记得准备礼物", "date": "3天后", "priority": "high"},
    {"id": 2, "type": "contact", "title": "久未联系", "description": "和王大伟导师已经1周没联系了，有空问候一下", "date": "1周前", "priority": "medium"},
    {"id": 3, "type": "anniversary", "title": "入职纪念日", "description": "和张小明共事一周年纪念日", "date": "5天后", "priority": "low"},
    {"id": 4, "type": "event", "title": "同学聚会", "description": "高中同学聚会，记得参加", "date": "下周六", "priority": "medium"},
]

# 情商提升课程
_eq_courses = [
    {"id": 1, "title": "情绪识别与表达", "progress": 80, "total_lessons": 10, "completed_lessons": 8, "description": "学习识别自己和他人的情绪，掌握有效表达方法"},
    {"id": 2, "title": "有效沟通技巧", "progress": 50, "total_lessons": 12, "completed_lessons": 6, "description": "提升沟通效率，建立良好的人际关系"},
    {"id": 3, "title": "冲突管理与解决", "progress": 20, "total_lessons": 8, "completed_lessons": 2, "description": "学会以积极的方式处理人际冲突"},
    {"id": 4, "title": "同理心培养", "progress": 65, "total_lessons": 6, "completed_lessons": 4, "description": "站在他人角度思考，增进理解与信任"},
]

# 社交统计
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


class ReminderCreateRequest(BaseModel):
    type: str
    title: str
    description: str = ""
    date: str = ""
    priority: str = "medium"


# ========== 概览 ==========
@router.get("/overview")
async def get_overview():
    """人际关系概览"""
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
async def get_relation_graph():
    """获取关系图谱"""
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
async def get_contacts(relation: Optional[str] = None, tag: Optional[str] = None):
    """获取联系人列表"""
    result = _contacts
    if relation:
        result = [c for c in result if c["relation"] == relation]
    if tag:
        result = [c for c in result if tag in c["tags"]]
    return {"code": 0, "message": "ok", "data": result}


@router.get("/contacts/{cid}")
async def get_contact_detail(cid: int):
    """获取联系人详情"""
    contact = next((c for c in _contacts if c["id"] == cid), None)
    if not contact:
        return {"code": 404, "message": "联系人不存在", "data": None}
    
    # 交往记录
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
async def create_contact(req: ContactCreateRequest):
    """新增联系人"""
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


# ========== 交往记录 ==========
@router.get("/interactions")
async def get_interactions(contact_id: Optional[int] = None, limit: int = 20):
    """获取交往记录"""
    result = _interactions
    if contact_id:
        result = [i for i in result if i["contact_id"] == contact_id]
    return {"code": 0, "message": "ok", "data": result[:limit]}


@router.post("/interactions")
async def create_interaction(req: InteractionCreateRequest):
    """记录交往"""
    iid = max((i["id"] for i in _interactions), default=0) + 1
    interaction = {
        "id": iid,
        "contact_id": req.contact_id,
        "contact_name": req.contact_name,
        "type": req.type,
        "content": req.content,
        "date": "刚刚",
        "emotion": req.emotion,
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
async def get_reminders():
    """获取社交提醒"""
    return {"code": 0, "message": "ok", "data": _reminders}


@router.post("/reminders")
async def create_reminder(req: ReminderCreateRequest):
    """添加提醒"""
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


@router.delete("/reminders/{rid}")
async def delete_reminder(rid: int):
    """删除提醒"""
    global _reminders
    _reminders = [r for r in _reminders if r["id"] != rid]
    return {"code": 0, "message": "删除成功", "data": None}


# ========== 情商提升 ==========
@router.get("/eq-courses")
async def get_eq_courses():
    """获取情商课程"""
    return {"code": 0, "message": "ok", "data": _eq_courses}


@router.get("/eq-score")
async def get_eq_score():
    """获取情商得分"""
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
