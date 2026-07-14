"""
复盘总结模式路由
提供日报/周报/月报生成、情绪追踪、决策回溯、认知偏差检测、私密日记等 API
数据存储：SQLite 数据库（从内存迁移而来）
"""
import sys
import uuid
from pathlib import Path
from datetime import datetime, timedelta
from typing import Optional, List

from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..config import settings
from ..models import (
    get_db,
    ReviewReview,
    ReviewDiary,
    ReviewDecision,
    ReviewEmotion,
    ReviewBias,
)

# 导入 LLM 客户端
project_root = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(project_root))
try:
    from shared.llm_client import LLMClient
    _llm_available = True
except Exception:
    _llm_available = False

router = APIRouter(tags=["复盘总结"])

config = settings

# 默认用户 ID（单用户模式）
DEFAULT_USER_ID = 1

# LLM 客户端实例（懒加载）
_llm_client = None


def _get_llm():
    """获取 LLM 客户端实例（懒加载，失败返回 None）"""
    global _llm_client
    if not _llm_available:
        return None
    if _llm_client is None:
        try:
            _llm_client = LLMClient()
        except Exception:
            _llm_client = None
            globals()['_llm_available'] = False
    return _llm_client


# ============================================================
# 数据模型
# ============================================================

class ReviewCreateRequest(BaseModel):
    """创建复盘请求"""
    type: str  # daily, weekly, monthly
    date: Optional[str] = None
    content: Optional[str] = ""


class ReviewGenerateRequest(BaseModel):
    """AI 生成复盘请求"""
    type: str  # daily, weekly, monthly
    date: Optional[str] = None


class DiaryCreateRequest(BaseModel):
    title: str
    content: str
    mood: Optional[str] = "neutral"
    tags: Optional[List[str]] = []


class DecisionCreateRequest(BaseModel):
    title: str
    description: str
    options: List[str]
    final_choice: Optional[str] = ""
    result: Optional[str] = ""
    emotion_level: Optional[int] = 5


class DecisionUpdateRequest(BaseModel):
    """更新决策请求（所有字段可选）"""
    title: Optional[str] = None
    description: Optional[str] = None
    status: Optional[str] = None  # pending, executing, completed
    final_choice: Optional[str] = None
    result: Optional[str] = None
    emotion_level: Optional[int] = None
    alternatives: Optional[List[str]] = None


class EmotionRecordRequest(BaseModel):
    emotion: str  # happy, calm, neutral, sad, anxious, angry
    level: int  # 1-10
    trigger: Optional[str] = ""
    note: Optional[str] = ""


class BiasAnalyzeRequest(BaseModel):
    """认知偏差分析请求"""
    text: str


# ============================================================
# 数据初始化
# ============================================================

def _ensure_data_initialized(db: Session, user_id: int = DEFAULT_USER_ID):
    """确保示例数据已初始化（表为空时自动插入）"""
    _init_sample_review_data(db, user_id)


def _init_sample_review_data(db: Session, user_id: int = DEFAULT_USER_ID):
    """初始化复盘总结模式示例数据"""
    now = datetime.utcnow()

    # 复盘记录表为空时插入示例数据
    if db.query(ReviewReview).filter_by(user_id=user_id).count() == 0:
        review_templates = [
            ("daily", "完成用户模块接口开发，修复3个bug", "high"),
            ("daily", "参与产品需求评审，确定Q3规划", "medium"),
            ("daily", "系统性能优化，响应速度提升40%", "high"),
            ("weekly", "本周完成3个功能模块，修复8个bug", "high"),
            ("monthly", "本月完成2个大版本迭代，交付15个功能点", "high"),
        ]
        type_names = ["日", "日", "日", "周", "月"]
        for i, (rtype, summary, quality) in enumerate(review_templates):
            rid = i + 1
            date = now - timedelta(days=i)
            date_str = date.strftime("%Y-%m-%d")
            content = f"""【完成工作】
1. {summary}

【问题与解决】
遇到接口性能问题，通过缓存优化解决

【明日计划】
1. 继续推进功能开发
2. 编写技术文档

【心得】
持续优化代码质量很重要"""
            review = ReviewReview(
                review_id=rid,
                type=rtype,
                title=f"{type_names[i]}报 - {date_str}",
                content=content,
                quality=quality,
                date=date_str,
                word_count=200 + i * 50,
                insights=[],
                actions=[],
                created_at=date,
                updated_at=date,
                user_id=user_id,
            )
            db.add(review)
        db.commit()

    # 日记表为空时插入示例数据
    if db.query(ReviewDiary).filter_by(user_id=user_id).count() == 0:
        diary_titles = [
            "关于职业规划的思考",
            "今天的学习收获",
            "一次重要的决策",
            "读书笔记：深度工作",
            "周末的反思",
        ]
        moods = ["happy", "calm", "neutral", "thoughtful", "excited"]
        for i, title in enumerate(diary_titles):
            did = i + 1
            date = now - timedelta(days=i * 3)
            content = f"今天想了很多关于{title}的事情...\n\n记录一下当下的想法和感受。\n\n希望未来的自己看到这些文字时，能够有所感悟。"
            diary = ReviewDiary(
                diary_id=did,
                title=title,
                content=content,
                mood=moods[i % 5],
                weather="",
                tags=["思考", "成长", "记录"][: (i % 3) + 1],
                word_count=150 + i * 30,
                encrypted=True,
                created_at=date,
                updated_at=date,
                user_id=user_id,
            )
            db.add(diary)
        db.commit()

    # 决策记录表为空时插入示例数据
    if db.query(ReviewDecision).filter_by(user_id=user_id).count() == 0:
        decision_titles = [
            "是否跳槽到新公司",
            "技术选型：React vs Vue",
            "是否读研深造",
            "买房还是租房",
        ]
        final_choices = ["选项A", "选项B", "选项A", ""]
        results = ["已执行，效果良好", "执行中", "已执行，需要观察", "待决策"]
        for i, title in enumerate(decision_titles):
            did = i + 1
            date = now - timedelta(days=i * 7)
            decision = ReviewDecision(
                decision_id=did,
                title=title,
                description=f"关于{title}的决策过程记录",
                alternatives=["选项A：积极推进", "选项B：保守观望", "选项C：暂缓决策"],
                outcome=results[i],
                lessons="",
                status="completed" if final_choices[i] else "pending",
                final_choice=final_choices[i],
                result=results[i],
                emotion_level=6 + i,
                created_at=date,
                updated_at=date,
                user_id=user_id,
            )
            db.add(decision)
        db.commit()

    # 情绪记录表为空时插入示例数据（最近 30 天）
    if db.query(ReviewEmotion).filter_by(user_id=user_id).count() == 0:
        emotions_list = [
            "happy", "calm", "neutral", "happy", "calm", "anxious", "calm",
            "happy", "happy", "neutral", "sad", "calm", "happy", "calm",
            "neutral", "happy", "calm", "happy", "anxious", "calm",
            "happy", "happy", "neutral", "calm", "happy", "calm",
            "happy", "calm", "neutral", "happy",
        ]
        for i, emo in enumerate(emotions_list):
            date = now - timedelta(days=29 - i)
            date_str = date.strftime("%Y-%m-%d")
            emotion = ReviewEmotion(
                date=date_str,
                emotion=emo,
                intensity=5 + (i % 5),
                trigger="",
                note="",
                created_at=date,
                user_id=user_id,
            )
            db.add(emotion)
        db.commit()

    # 认知偏差表为空时插入示例数据
    if db.query(ReviewBias).filter_by(user_id=user_id).count() == 0:
        bias_templates = [
            ("确认偏误", "在寻找信息时倾向于寻找支持自己观点的证据", "high", 3),
            ("锚定效应", "决策时过度依赖第一印象", "medium", 2),
            ("损失厌恶", "对损失的痛苦大于对收益的快乐", "medium", 1),
            ("幸存者偏差", "只关注成功案例而忽略失败案例", "low", 0),
        ]
        for i, (name, desc, level, count) in enumerate(bias_templates):
            bid = i + 1
            bias = ReviewBias(
                bias_id=bid,
                name=name,
                description=desc,
                category="",
                level=level,
                detected_count=count,
                last_detected=now - timedelta(days=i * 5) if count > 0 else None,
                suggestions=[
                    "主动寻找反面证据",
                    "考虑多个参考点",
                    "使用决策平衡表",
                ],
                user_id=user_id,
            )
            db.add(bias)
        db.commit()


# ============================================================
# 辅助工具：ORM → Dict
# ============================================================

def _review_to_dict(r: ReviewReview) -> dict:
    """复盘记录 ORM → 字典（兼容原格式）"""
    return {
        "id": r.review_id,
        "type": r.type,
        "title": r.title,
        "content": r.content,
        "date": r.date,
        "quality": r.quality,
        "word_count": r.word_count,
        "created_at": r.created_at.isoformat() if r.created_at else None,
        "updated_at": r.updated_at.isoformat() if r.updated_at else None,
    }


def _diary_to_dict(d: ReviewDiary) -> dict:
    """日记 ORM → 字典（兼容原格式）"""
    return {
        "id": d.diary_id,
        "title": d.title,
        "content": d.content,
        "mood": d.mood,
        "tags": d.tags or [],
        "word_count": d.word_count,
        "created_at": d.created_at.isoformat() if d.created_at else None,
        "updated_at": d.updated_at.isoformat() if d.updated_at else None,
        "encrypted": d.encrypted,
    }


def _decision_to_dict(d: ReviewDecision) -> dict:
    """决策记录 ORM → 字典（兼容原格式）"""
    return {
        "id": d.decision_id,
        "title": d.title,
        "description": d.description,
        "options": d.alternatives or [],
        "final_choice": d.final_choice,
        "result": d.result,
        "emotion_level": d.emotion_level,
        "status": d.status,
        "created_at": d.created_at.isoformat() if d.created_at else None,
        "updated_at": d.updated_at.isoformat() if d.updated_at else None,
    }


def _emotion_to_dict(e: ReviewEmotion) -> dict:
    """情绪记录 ORM → 字典（兼容原格式）"""
    return {
        "id": e.id,
        "emotion": e.emotion,
        "level": e.intensity,
        "trigger": e.trigger,
        "note": e.note,
        "date": e.date,
        "created_at": e.created_at.isoformat() if e.created_at else None,
    }


def _bias_to_dict(b: ReviewBias) -> dict:
    """认知偏差 ORM → 字典（兼容原格式）"""
    return {
        "id": b.bias_id,
        "name": b.name,
        "description": b.description,
        "level": b.level,
        "detection_count": b.detected_count,
        "last_detected": b.last_detected.isoformat() if b.last_detected else None,
        "suggestions": b.suggestions or [],
    }


# ============================================================
# 内部工具：模板生成（LLM 不可用时降级）
# ============================================================

def _generate_template_content(rtype, date_str):
    """生成模板内容（降级方案）"""
    type_names = {"daily": "日报", "weekly": "周报", "monthly": "月报"}
    type_name = type_names.get(rtype, "日报")

    contents = {
        "daily": """【今日完成】
1. 完成核心功能模块开发，代码质量良好
2. 修复 3 个线上 bug，用户反馈积极
3. 参与产品需求评审会议，确定下一阶段目标

【遇到的问题】
• 接口性能瓶颈，响应时间偏长
• 解决方案：引入缓存机制，优化数据库查询

【明日计划】
1. 继续推进功能开发
2. 编写技术文档
3. 代码评审

【心得感悟】
持续优化代码质量和架构设计，比快速堆功能更重要。
今天的小优化，是明天的大提升。""",
        "weekly": """【本周概述】
完成 3 个功能模块开发，修复 8 个 bug
代码提交 24 次，新增代码 1500+ 行

【重点成果】
✅ 用户系统重构完成
✅ 支付接口对接上线
✅ 性能优化 - 响应速度提升 40%

【问题挑战】
⚠️ 第三方接口不稳定 → 已做降级处理
⚠️ 需求变更频繁 → 加强沟通确认

【下周计划】
1. 完成订单模块开发
2. 开展代码评审
3. 推进测试覆盖

【成长收获】
学会了在压力下保持代码质量，
也更懂得了团队协作的重要性。""",
        "monthly": """【工作总览】
完成 2 个大版本迭代，交付 15 个功能点
代码提交 120 次，团队协作效率提升 25%

【目标达成】
🎯 核心目标完成率：92%
🎯 用户体系重构：已完成
🎯 支付系统上线：已完成
🎯 性能优化专项：进行中

【里程碑】
🏆 月活用户突破 10 万
🏆 系统稳定性达到 99.9%
🏆 团队 Code Review 覆盖率 100%

【反思与改进】
• 需求管理可以更规范
• 技术债务需要定期清理
• 知识沉淀和分享有待加强

【下月计划】
1. 启动新功能开发
2. 优化系统架构
3. 加强团队建设""",
    }
    return contents.get(rtype, contents["daily"])


async def _generate_with_llm(rtype, date_str, db):
    """通过 LLM 生成复盘内容，失败返回 None"""
    llm = _get_llm()
    if not llm:
        return None

    type_names = {"daily": "日报", "weekly": "周报", "monthly": "月报"}
    type_name = type_names.get(rtype, "日报")

    # 收集近期情绪摘要
    try:
        recent_emotions = db.query(ReviewEmotion).filter_by(
            user_id=DEFAULT_USER_ID
        ).order_by(ReviewEmotion.date.desc()).limit(7).all()
        emotion_summary = ""
        if recent_emotions:
            emo_counts = {}
            for e in recent_emotions:
                emo_counts[e.emotion] = emo_counts.get(e.emotion, 0) + 1
            emo_parts = [f"{k}({v}天)" for k, v in emo_counts.items()]
            emotion_summary = "近期情绪分布：" + "、".join(emo_parts)
    except Exception:
        emotion_summary = ""

    # 收集近期任务/复盘摘要
    try:
        recent_reviews = db.query(ReviewReview).filter_by(
            user_id=DEFAULT_USER_ID
        ).order_by(ReviewReview.created_at.desc()).limit(3).all()
        review_summary = ""
        if recent_reviews:
            titles = [r.title for r in recent_reviews]
            review_summary = "最近复盘：" + "、".join(titles)
    except Exception:
        review_summary = ""

    system_prompt = f"""你是一个专业的复盘助手，擅长帮助用户生成高质量的{type_name}内容。
请根据以下信息，生成一份结构清晰、内容充实的{type_name}：

复盘类型：{type_name}
日期：{date_str}
{emotion_summary}
{review_summary}

要求：
1. 使用中文，语气亲切自然
2. 结构清晰，分点明确
3. 内容具体，有细节和数据
4. 包含完成事项、问题反思、计划安排、心得感悟等模块
5. 字数约 300-500 字
6. 直接输出复盘内容，不要寒暄或解释"""

    user_message = f"请帮我生成一份{date_str}的{type_name}，基于我近期的状态和习惯。"

    try:
        reply = await llm.chat(
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_message},
            ],
            temperature=0.7,
            max_tokens=1500,
        )
        if reply and len(reply.strip()) > 50:
            return reply.strip()
    except Exception:
        pass

    return None


# ============================================================
# 概览统计
# ============================================================

@router.get("/overview")
async def review_overview(
    db: Session = Depends(get_db),
):
    """复盘模式概览统计"""
    _ensure_data_initialized(db, DEFAULT_USER_ID)

    reviews = db.query(ReviewReview).filter_by(user_id=DEFAULT_USER_ID).all()
    diaries = db.query(ReviewDiary).filter_by(user_id=DEFAULT_USER_ID).all()
    decisions = db.query(ReviewDecision).filter_by(user_id=DEFAULT_USER_ID).all()
    emotions = db.query(ReviewEmotion).filter_by(user_id=DEFAULT_USER_ID).all()

    total_reviews = len(reviews)
    total_diaries = len(diaries)
    total_decisions = len(decisions)
    total_emotions = len(emotions)

    # 情绪统计
    emotion_counts = {}
    for e in emotions:
        emotion_counts[e.emotion] = emotion_counts.get(e.emotion, 0) + 1

    # 本周复盘数
    now = datetime.utcnow()
    week_ago = now - timedelta(days=7)
    week_reviews = sum(
        1 for r in reviews
        if r.created_at and r.created_at > week_ago
    )

    # 连续打卡天数
    streak = 0
    for i in range(30):
        date = (now - timedelta(days=i)).strftime("%Y-%m-%d")
        has_review = any(r.date == date for r in reviews)
        has_emotion = any(e.date == date for e in emotions)
        if has_review or has_emotion:
            streak += 1
        else:
            break

    # 最近复盘
    recent_reviews = sorted(
        [_review_to_dict(r) for r in reviews],
        key=lambda x: x["created_at"],
        reverse=True
    )[:5]

    # 最近日记
    recent_diaries = sorted(
        [_diary_to_dict(d) for d in diaries],
        key=lambda x: x["created_at"],
        reverse=True
    )[:3]

    return {
        "code": 0,
        "message": "ok",
        "data": {
            "stats": {
                "total_reviews": total_reviews,
                "total_diaries": total_diaries,
                "total_decisions": total_decisions,
                "total_emotions": total_emotions,
                "week_reviews": week_reviews,
                "streak_days": streak,
            },
            "emotion_distribution": emotion_counts,
            "recent_reviews": recent_reviews,
            "recent_diaries": recent_diaries,
        }
    }


# ============================================================
# 复盘生成与保存
# ============================================================

@router.post("/generate")
async def generate_review(
    req: ReviewGenerateRequest,
    db: Session = Depends(get_db),
):
    """AI 生成复盘内容（仅生成，不保存）

    优先调用真实 LLM 生成，失败时降级使用模板生成。
    返回生成的内容，前端可编辑后调用 POST /reviews 保存。
    """
    _ensure_data_initialized(db, DEFAULT_USER_ID)

    review_types = {
        "daily": "日报",
        "weekly": "周报",
        "monthly": "月报",
    }
    rtype = req.type if req.type in review_types else "daily"
    type_name = review_types[rtype]
    date_str = req.date or datetime.now().strftime("%Y-%m-%d")

    # 尝试通过 LLM 生成
    content = None
    is_ai_generated = False
    try:
        content = await _generate_with_llm(rtype, date_str, db)
        if content:
            is_ai_generated = True
    except Exception:
        pass

    # 降级使用模板
    if not content:
        content = _generate_template_content(rtype, date_str)

    # 计算质量
    word_count = len(content)
    quality = "high" if word_count > 500 else "medium" if word_count > 200 else "low"

    return {
        "code": 0,
        "message": f"{type_name}生成成功",
        "data": {
            "type": rtype,
            "date": date_str,
            "title": f"{type_name} - {date_str}",
            "content": content,
            "word_count": word_count,
            "quality": quality,
            "is_ai_generated": is_ai_generated,
        },
    }


@router.post("/reviews")
async def create_review(
    req: ReviewCreateRequest,
    db: Session = Depends(get_db),
):
    """创建/保存复盘记录

    将编辑好的复盘内容保存到数据库。
    """
    _ensure_data_initialized(db, DEFAULT_USER_ID)

    review_types = {
        "daily": "日报",
        "weekly": "周报",
        "monthly": "月报",
    }
    rtype = req.type if req.type in review_types else "daily"
    type_name = review_types[rtype]
    date_str = req.date or datetime.now().strftime("%Y-%m-%d")
    content = req.content or ""

    # 找最大的 review_id
    all_reviews = db.query(ReviewReview).filter_by(user_id=DEFAULT_USER_ID).all()
    rid = max((r.review_id for r in all_reviews), default=0) + 1

    # 计算质量
    word_count = len(content)
    quality = "high" if word_count > 500 else "medium" if word_count > 200 else "low"

    now = datetime.utcnow()
    review = ReviewReview(
        review_id=rid,
        type=rtype,
        title=f"{type_name} - {date_str}",
        content=content,
        quality=quality,
        date=date_str,
        word_count=word_count,
        insights=[],
        actions=[],
        created_at=now,
        updated_at=now,
        user_id=DEFAULT_USER_ID,
    )
    db.add(review)
    db.commit()
    db.refresh(review)

    return {
        "code": 0,
        "message": f"{type_name}保存成功",
        "data": _review_to_dict(review),
    }


@router.post("/generate/save")
async def generate_and_save_review(
    req: ReviewCreateRequest,
    db: Session = Depends(get_db),
):
    """【已废弃】生成并保存复盘（兼容旧接口）

    建议使用：
    - POST /generate 生成内容
    - POST /reviews 保存内容
    """
    # 如果有 content，走保存逻辑（兼容旧行为）
    if req.content:
        return await create_review(req, db)

    # 没有 content，走生成+保存逻辑
    gen_req = ReviewGenerateRequest(type=req.type, date=req.date)
    gen_result = await generate_review(gen_req, db)
    gen_data = gen_result["data"]

    # 直接保存生成的内容
    save_req = ReviewCreateRequest(
        type=gen_data["type"],
        date=gen_data["date"],
        content=gen_data["content"],
    )
    return await create_review(save_req, db)


@router.get("/reviews")
async def list_reviews(
    review_type: Optional[str] = None,
    limit: int = 20,
    db: Session = Depends(get_db),
):
    """复盘记录列表"""
    _ensure_data_initialized(db, DEFAULT_USER_ID)

    query = db.query(ReviewReview).filter_by(user_id=DEFAULT_USER_ID)
    if review_type:
        query = query.filter_by(type=review_type)

    reviews = query.order_by(ReviewReview.created_at.desc()).limit(limit).all()
    return {"code": 0, "message": "ok", "data": [_review_to_dict(r) for r in reviews]}


@router.get("/reviews/{review_id}")
async def get_review(
    review_id: int,
    db: Session = Depends(get_db),
):
    """复盘详情"""
    _ensure_data_initialized(db, DEFAULT_USER_ID)

    review = db.query(ReviewReview).filter_by(
        user_id=DEFAULT_USER_ID, review_id=review_id
    ).first()
    if not review:
        raise HTTPException(status_code=404, detail="复盘记录不存在")
    return {"code": 0, "message": "ok", "data": _review_to_dict(review)}


# ============================================================
# 情绪追踪
# ============================================================


@router.delete("/reviews/{review_id}")
async def delete_review(
    review_id: int,
    db: Session = Depends(get_db),
):
    """删除复盘记录"""
    _ensure_data_initialized(db, DEFAULT_USER_ID)

    review = db.query(ReviewReview).filter_by(
        user_id=DEFAULT_USER_ID, review_id=review_id
    ).first()
    if not review:
        raise HTTPException(status_code=404, detail="复盘记录不存在")

    db.delete(review)
    db.commit()
    return {"code": 0, "message": "复盘删除成功", "data": {"id": review_id}}

@router.get("/emotions")
async def list_emotions(
    days: int = 30,
    db: Session = Depends(get_db),
):
    """情绪记录列表"""
    _ensure_data_initialized(db, DEFAULT_USER_ID)

    emotions = db.query(ReviewEmotion).filter_by(
        user_id=DEFAULT_USER_ID
    ).order_by(ReviewEmotion.date.desc()).limit(days).all()

    return {"code": 0, "message": "ok", "data": [_emotion_to_dict(e) for e in emotions]}


@router.post("/emotions")
async def record_emotion(
    req: EmotionRecordRequest,
    db: Session = Depends(get_db),
):
    """记录情绪"""
    _ensure_data_initialized(db, DEFAULT_USER_ID)

    now = datetime.utcnow()
    date_str = now.strftime("%Y-%m-%d")

    emotion = ReviewEmotion(
        date=date_str,
        emotion=req.emotion,
        intensity=req.level,
        trigger=req.trigger or "",
        note=req.note or "",
        created_at=now,
        user_id=DEFAULT_USER_ID,
    )
    db.add(emotion)
    db.commit()
    db.refresh(emotion)

    return {"code": 0, "message": "情绪记录成功", "data": _emotion_to_dict(emotion)}


@router.get("/emotions/stats")
async def emotion_stats(
    days: int = 30,
    db: Session = Depends(get_db),
):
    """情绪统计"""
    _ensure_data_initialized(db, DEFAULT_USER_ID)

    # 取最近 N 天的记录
    now = datetime.utcnow()
    start_date = (now - timedelta(days=days - 1)).strftime("%Y-%m-%d")
    recent = db.query(ReviewEmotion).filter(
        ReviewEmotion.user_id == DEFAULT_USER_ID,
        ReviewEmotion.date >= start_date,
    ).order_by(ReviewEmotion.date.asc()).all()

    # 按情绪类型统计
    emotion_counts = {}
    for e in recent:
        emotion_counts[e.emotion] = emotion_counts.get(e.emotion, 0) + 1

    # 情绪趋势（按天）
    daily = []
    now_date = datetime.utcnow()
    for i in range(days - 1, -1, -1):
        date = (now_date - timedelta(days=i)).strftime("%Y-%m-%d")
        day_emotions = [e for e in recent if e.date == date]
        if day_emotions:
            avg_level = sum(e.intensity for e in day_emotions) / len(day_emotions)
            daily.append({"date": date, "avg_level": round(avg_level, 1), "count": len(day_emotions)})
        else:
            daily.append({"date": date, "avg_level": 0, "count": 0})

    # 主导情绪
    dominant = max(emotion_counts, key=emotion_counts.get) if emotion_counts else "neutral"

    avg_level = round(
        sum(e.intensity for e in recent) / len(recent), 1
    ) if recent else 0

    return {
        "code": 0,
        "message": "ok",
        "data": {
            "total_records": len(recent),
            "emotion_distribution": emotion_counts,
            "dominant_emotion": dominant,
            "daily_trend": daily,
            "avg_level": avg_level,
        }
    }


# ============================================================
# 决策回溯
# ============================================================

@router.get("/decisions")
async def list_decisions(
    limit: int = 20,
    db: Session = Depends(get_db),
):
    """决策记录列表"""
    _ensure_data_initialized(db, DEFAULT_USER_ID)

    decisions = db.query(ReviewDecision).filter_by(
        user_id=DEFAULT_USER_ID
    ).order_by(ReviewDecision.created_at.desc()).limit(limit).all()

    return {"code": 0, "message": "ok", "data": [_decision_to_dict(d) for d in decisions]}


@router.get("/decisions/{decision_id}")
async def get_decision(
    decision_id: int,
    db: Session = Depends(get_db),
):
    """决策详情"""
    _ensure_data_initialized(db, DEFAULT_USER_ID)

    decision = db.query(ReviewDecision).filter_by(
        user_id=DEFAULT_USER_ID, decision_id=decision_id
    ).first()
    if not decision:
        raise HTTPException(status_code=404, detail="决策记录不存在")
    return {"code": 0, "message": "ok", "data": _decision_to_dict(decision)}



@router.delete("/decisions/{decision_id}")
async def delete_decision(
    decision_id: int,
    db: Session = Depends(get_db),
):
    """删除决策记录"""
    _ensure_data_initialized(db, DEFAULT_USER_ID)

    decision = db.query(ReviewDecision).filter_by(
        user_id=DEFAULT_USER_ID, decision_id=decision_id
    ).first()
    if not decision:
        raise HTTPException(status_code=404, detail="决策记录不存在")

    db.delete(decision)
    db.commit()
    return {"code": 0, "message": "决策删除成功", "data": {"id": decision_id}}

@router.post("/decisions")
async def create_decision(
    req: DecisionCreateRequest,
    db: Session = Depends(get_db),
):
    """创建决策记录"""
    _ensure_data_initialized(db, DEFAULT_USER_ID)

    # 找最大的 decision_id
    all_decisions = db.query(ReviewDecision).filter_by(user_id=DEFAULT_USER_ID).all()
    did = max((d.decision_id for d in all_decisions), default=0) + 1

    now = datetime.utcnow()
    decision = ReviewDecision(
        decision_id=did,
        title=req.title,
        description=req.description,
        alternatives=req.options,
        outcome=req.result or "",
        lessons="",
        status="pending" if not req.final_choice else "completed",
        final_choice=req.final_choice or "",
        result=req.result or "",
        emotion_level=req.emotion_level or 5,
        created_at=now,
        updated_at=now,
        user_id=DEFAULT_USER_ID,
    )
    db.add(decision)
    db.commit()
    db.refresh(decision)

    return {"code": 0, "message": "决策记录创建成功", "data": _decision_to_dict(decision)}


@router.put("/decisions/{decision_id}")
async def update_decision(
    decision_id: int,
    req: DecisionUpdateRequest,
    db: Session = Depends(get_db),
):
    """更新决策记录

    可更新字段：title, description, status, final_choice, result, emotion_level, alternatives
    仅更新传入的字段，未传入的字段保持不变。
    """
    _ensure_data_initialized(db, DEFAULT_USER_ID)

    decision = db.query(ReviewDecision).filter_by(
        user_id=DEFAULT_USER_ID, decision_id=decision_id
    ).first()
    if not decision:
        raise HTTPException(status_code=404, detail="决策记录不存在")

    # 更新字段（仅更新有值的）
    if req.title is not None:
        decision.title = req.title
    if req.description is not None:
        decision.description = req.description
    if req.status is not None:
        valid_statuses = ["pending", "executing", "completed"]
        if req.status not in valid_statuses:
            raise HTTPException(status_code=400, detail=f"无效状态，可选值：{valid_statuses}")
        decision.status = req.status
    if req.final_choice is not None:
        decision.final_choice = req.final_choice
        # 如果设置了最终选择，自动标记为已完成
        if req.final_choice and not req.status:
            decision.status = "completed"
    if req.result is not None:
        decision.result = req.result
        decision.outcome = req.result
    if req.emotion_level is not None:
        if 1 <= req.emotion_level <= 10:
            decision.emotion_level = req.emotion_level
    if req.alternatives is not None:
        decision.alternatives = req.alternatives

    decision.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(decision)

    return {"code": 0, "message": "决策更新成功", "data": _decision_to_dict(decision)}


# ============================================================
# 认知偏差检测
# ============================================================

@router.get("/biases")
async def list_biases(
    db: Session = Depends(get_db),
):
    """认知偏差检测列表"""
    _ensure_data_initialized(db, DEFAULT_USER_ID)

    biases = db.query(ReviewBias).filter_by(user_id=DEFAULT_USER_ID).all()
    return {"code": 0, "message": "ok", "data": [_bias_to_dict(b) for b in biases]}


@router.post("/biases/analyze")
async def analyze_bias(
    req: BiasAnalyzeRequest,
    db: Session = Depends(get_db),
):
    """分析文本中的认知偏差

    接收决策描述文本，检测其中可能存在的认知偏差，
    返回偏差名称、描述、风险等级和建议。
    """
    _ensure_data_initialized(db, DEFAULT_USER_ID)

    text = req.text or ""
    if not text.strip():
        return {
            "code": 0,
            "message": "分析完成",
            "data": {
                "detected_biases": [],
                "bias_details": [],
                "bias_count": 0,
                "risk_level": "none",
                "suggestions": ["暂无文本可分析"],
            }
        }

    # 偏差检测规则库
    bias_rules = {
        "确认偏误": {
            "keywords": ["我认为", "我觉得", "肯定是", "一定", "毫无疑问", "显然", "毋庸置疑"],
            "description": "在寻找信息时倾向于寻找支持自己观点的证据，忽略反面信息",
            "level": "high",
            "suggestions": [
                "主动寻找与自己观点相反的证据",
                "尝试站在对立面思考问题",
                "列出支持和反对的理由各 3 条",
            ],
        },
        "锚定效应": {
            "keywords": ["第一印象", "最初", "一开始", "首先想到", "第一感觉"],
            "description": "决策时过度依赖第一印象或最初获得的信息，难以调整判断",
            "level": "medium",
            "suggestions": [
                "收集多个参考点，避免单一信息源",
                "延迟决策，给自己足够的思考时间",
                "从不同角度重新评估信息",
            ],
        },
        "损失厌恶": {
            "keywords": ["亏了", "损失", "舍不得", "怕失去", "万一失败"],
            "description": "对损失的痛苦感受大于对同等收益的快乐感受，导致过于保守",
            "level": "medium",
            "suggestions": [
                "使用决策平衡表权衡利弊",
                "问自己：如果不做这件事，1年后会后悔吗",
                "区分可承受损失和不可承受损失",
            ],
        },
        "幸存者偏差": {
            "keywords": ["成功人士", "他们都", "别人都行", "大家都成功"],
            "description": "只关注成功案例而忽略失败案例，高估成功概率",
            "level": "low",
            "suggestions": [
                "主动了解失败案例和沉默数据",
                "分析成功背后的概率和条件",
                "考虑基础概率和样本偏差",
            ],
        },
        "从众效应": {
            "keywords": ["大家都", "别人都", "所有人都", "主流"],
            "description": "倾向于跟随大众的选择，忽视独立判断",
            "level": "medium",
            "suggestions": [
                "先独立思考再参考他人意见",
                "问自己：如果没有人这么做，我还会选吗",
                "区分事实判断和群体压力",
            ],
        },
        "过度自信": {
            "keywords": ["没问题", "肯定行", "很简单", "一定能", "小菜一碟"],
            "description": "高估自己的能力和判断的准确性，低估风险",
            "level": "high",
            "suggestions": [
                "事前预估风险，准备 Plan B",
                "参考外部视角和他人评价",
                "用数据验证而非凭感觉判断",
            ],
        },
        "情绪化决策": {
            "keywords": ["生气", "难过", "焦虑", "害怕", "激动", "兴奋"],
            "description": "在强烈情绪影响下做出决策，缺乏理性分析",
            "level": "high",
            "suggestions": [
                "高情绪状态下延迟重大决策",
                "情绪平复后重新评估选项",
                "使用决策框架辅助理性分析",
            ],
        },
    }

    # 检测偏差
    detected_names = []
    bias_details = []
    text_lower = text.lower()

    for bias_name, rule in bias_rules.items():
        found = False
        for kw in rule["keywords"]:
            if kw in text:
                found = True
                break
        if found:
            detected_names.append(bias_name)
            bias_details.append({
                "name": bias_name,
                "description": rule["description"],
                "level": rule["level"],
                "suggestions": rule["suggestions"],
            })

    # 计算风险等级
    high_count = sum(1 for b in bias_details if b["level"] == "high")
    medium_count = sum(1 for b in bias_details if b["level"] == "medium")
    if high_count >= 2 or len(bias_details) >= 4:
        risk_level = "high"
    elif high_count >= 1 or medium_count >= 2 or len(bias_details) >= 2:
        risk_level = "medium"
    elif len(bias_details) >= 1:
        risk_level = "low"
    else:
        risk_level = "none"

    # 汇总建议
    all_suggestions = []
    for bd in bias_details:
        all_suggestions.extend(bd["suggestions"])
    # 去重并限制数量
    unique_suggestions = list(dict.fromkeys(all_suggestions))[:8]

    if not bias_details:
        unique_suggestions = ["认知状态良好，继续保持理性思考"]

    # 更新检测计数
    now = datetime.utcnow()
    for bias_name in detected_names:
        bias = db.query(ReviewBias).filter_by(
            user_id=DEFAULT_USER_ID, name=bias_name
        ).first()
        if bias:
            bias.detected_count = (bias.detected_count or 0) + 1
            bias.last_detected = now
    if detected_names:
        db.commit()

    return {
        "code": 0,
        "message": "分析完成",
        "data": {
            "detected_biases": detected_names,
            "bias_details": bias_details,
            "bias_count": len(detected_names),
            "risk_level": risk_level,
            "suggestions": unique_suggestions,
        }
    }


# ============================================================
# 私密日记
# ============================================================

@router.get("/diaries")
async def list_diaries(
    limit: int = 20,
    db: Session = Depends(get_db),
):
    """日记列表"""
    _ensure_data_initialized(db, DEFAULT_USER_ID)

    diaries = db.query(ReviewDiary).filter_by(
        user_id=DEFAULT_USER_ID
    ).order_by(ReviewDiary.created_at.desc()).limit(limit).all()

    return {"code": 0, "message": "ok", "data": [_diary_to_dict(d) for d in diaries]}


@router.get("/diaries/{diary_id}")
async def get_diary(
    diary_id: int,
    db: Session = Depends(get_db),
):
    """日记详情"""
    _ensure_data_initialized(db, DEFAULT_USER_ID)

    diary = db.query(ReviewDiary).filter_by(
        user_id=DEFAULT_USER_ID, diary_id=diary_id
    ).first()
    if not diary:
        raise HTTPException(status_code=404, detail="日记不存在")
    return {"code": 0, "message": "ok", "data": _diary_to_dict(diary)}



@router.delete("/diaries/{diary_id}")
async def delete_diary(
    diary_id: int,
    db: Session = Depends(get_db),
):
    """删除日记"""
    _ensure_data_initialized(db, DEFAULT_USER_ID)

    diary = db.query(ReviewDiary).filter_by(
        user_id=DEFAULT_USER_ID, diary_id=diary_id
    ).first()
    if not diary:
        raise HTTPException(status_code=404, detail="日记不存在")

    db.delete(diary)
    db.commit()
    return {"code": 0, "message": "日记删除成功", "data": {"id": diary_id}}

@router.post("/diaries")
async def create_diary(
    req: DiaryCreateRequest,
    db: Session = Depends(get_db),
):
    """创建日记"""
    _ensure_data_initialized(db, DEFAULT_USER_ID)

    # 找最大的 diary_id
    all_diaries = db.query(ReviewDiary).filter_by(user_id=DEFAULT_USER_ID).all()
    did = max((d.diary_id for d in all_diaries), default=0) + 1

    now = datetime.utcnow()
    diary = ReviewDiary(
        diary_id=did,
        title=req.title,
        content=req.content,
        mood=req.mood or "neutral",
        weather="",
        tags=req.tags or [],
        word_count=len(req.content),
        encrypted=True,
        created_at=now,
        updated_at=now,
        user_id=DEFAULT_USER_ID,
    )
    db.add(diary)
    db.commit()
    db.refresh(diary)

    return {"code": 0, "message": "日记保存成功", "data": _diary_to_dict(diary)}


# ============================================================
# 复盘模板
# ============================================================

@router.get("/templates")
async def review_templates():
    """复盘模板列表"""
    templates = [
        {
            "id": "daily",
            "name": "日报模板",
            "description": "每日工作/学习复盘",
            "sections": ["今日完成", "遇到的问题", "解决方案", "明日计划", "心得感悟"],
            "icon": "📝",
        },
        {
            "id": "weekly",
            "name": "周报模板",
            "description": "每周总结与规划",
            "sections": ["本周概述", "重点成果", "问题挑战", "下周计划", "成长收获"],
            "icon": "📊",
        },
        {
            "id": "monthly",
            "name": "月报模板",
            "description": "月度深度复盘",
            "sections": ["工作总览", "目标达成", "里程碑", "反思改进", "下月计划"],
            "icon": "📅",
        },
        {
            "id": "kpt",
            "name": "KPT 复盘法",
            "description": "Keep / Problem / Try",
            "sections": ["Keep 保持", "Problem 问题", "Try 尝试"],
            "icon": "🔄",
        },
        {
            "id": "star",
            "name": "STAR 复盘法",
            "description": "情境 / 任务 / 行动 / 结果",
            "sections": ["Situation 情境", "Task 任务", "Action 行动", "Result 结果"],
            "icon": "⭐",
        },
        {
            "id": "growing",
            "name": "成长复盘",
            "description": "个人成长专项复盘",
            "sections": ["目标回顾", "进度评估", "学到了什么", "改进方向", "下一步行动"],
            "icon": "🌱",
        },
    ]
    return {"code": 0, "message": "ok", "data": templates}


# ============================================================
# 数据统计
# ============================================================

@router.get("/stats")
async def review_stats(
    db: Session = Depends(get_db),
):
    """复盘数据统计"""
    _ensure_data_initialized(db, DEFAULT_USER_ID)

    reviews = db.query(ReviewReview).filter_by(user_id=DEFAULT_USER_ID).all()
    diaries = db.query(ReviewDiary).filter_by(user_id=DEFAULT_USER_ID).all()
    decisions = db.query(ReviewDecision).filter_by(user_id=DEFAULT_USER_ID).all()

    total_words_reviews = sum(r.word_count or 0 for r in reviews)
    total_words_diaries = sum(d.word_count or 0 for d in diaries)

    # 月度统计
    now = datetime.utcnow()
    monthly_stats = []
    for i in range(5, -1, -1):
        month_date = now - timedelta(days=i * 30)
        month_start = month_date.replace(day=1).strftime("%Y-%m")
        month_reviews = [
            r for r in reviews
            if r.created_at and r.created_at.strftime("%Y-%m") == month_start
        ]
        monthly_stats.append({
            "month": month_start,
            "review_count": len(month_reviews),
            "word_count": sum(r.word_count or 0 for r in month_reviews),
        })

    # 质量分布
    quality_distribution = {
        "high": sum(1 for r in reviews if r.quality == "high"),
        "medium": sum(1 for r in reviews if r.quality == "medium"),
        "low": sum(1 for r in reviews if r.quality == "low"),
    }

    return {
        "code": 0,
        "message": "ok",
        "data": {
            "total_reviews": len(reviews),
            "total_diaries": len(diaries),
            "total_decisions": len(decisions),
            "total_words_reviews": total_words_reviews,
            "total_words_diaries": total_words_diaries,
            "total_words": total_words_reviews + total_words_diaries,
            "monthly_stats": monthly_stats,
            "quality_distribution": quality_distribution,
        }
    }
