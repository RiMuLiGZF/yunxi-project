"""复盘总结模式 - API 路由.

提供复盘总结模式的 RESTful API 接口，包括概览统计、复盘生成与保存、
情绪追踪、决策回溯、认知偏差检测、私密日记等功能。
"""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Header, Query

from src.database import get_session
from src.models import make_response
from src.modes.review.models import (
    BiasAnalyzeRequest,
    DecisionCreateRequest,
    DecisionUpdateRequest,
    DiaryCreateRequest,
    EmotionRecordRequest,
    ReviewCreateRequest,
    ReviewGenerateRequest,
)
from src.modes.review.service import ReviewService

# ---------------------------------------------------------------------------
# 路由配置
# ---------------------------------------------------------------------------

router = APIRouter(
    prefix="/api/v1/review",
    tags=["复盘总结模式"],
)


# ---------------------------------------------------------------------------
# 辅助函数
# ---------------------------------------------------------------------------


def _get_service(x_user_id: str = "default") -> ReviewService:
    """获取 ReviewService 实例.

    Args:
        x_user_id: 用户 ID（从请求头获取）

    Returns:
        ReviewService 实例
    """
    db = get_session()
    return ReviewService(db, user_id=x_user_id)


# ---------------------------------------------------------------------------
# 概览接口
# ---------------------------------------------------------------------------


@router.get("/overview", summary="获取复盘总结概览")
async def get_overview(
    x_user_id: str = Header("default", description="用户 ID"),
):
    """获取复盘总结概览数据.

    包含统计数据、情绪分布、最近复盘和最近日记。
    """
    try:
        service = _get_service(x_user_id)
        data = service.get_overview()
        return make_response(data=data)
    except Exception as e:
        print(f"[Review] overview 异常: {e}")
        return make_response(
            code=51001,
            message=f"获取概览失败: {e}",
            data={},
        )


# ---------------------------------------------------------------------------
# 复盘生成与保存接口
# ---------------------------------------------------------------------------


@router.post("/generate", summary="AI 生成复盘内容")
async def generate_review(
    req: ReviewGenerateRequest,
    x_user_id: str = Header("default", description="用户 ID"),
):
    """生成复盘内容（仅生成，不保存）.

    优先调用真实 LLM 生成，失败时降级使用模板生成。
    返回生成的内容，前端可编辑后调用 POST /reviews 保存。
    """
    try:
        service = _get_service(x_user_id)
        data = service.generate_review(rtype=req.type, date=req.date)
        return make_response(message="复盘生成成功", data=data)
    except Exception as e:
        print(f"[Review] generate 异常: {e}")
        return make_response(
            code=51002,
            message=f"生成复盘失败: {e}",
            data={},
        )


@router.post("/reviews", summary="保存复盘记录")
async def create_review(
    req: ReviewCreateRequest,
    x_user_id: str = Header("default", description="用户 ID"),
):
    """创建/保存复盘记录.

    将编辑好的复盘内容保存到数据库。
    """
    try:
        service = _get_service(x_user_id)
        data = service.create_review(
            rtype=req.type,
            content=req.content or "",
            date=req.date,
        )
        return make_response(message="复盘保存成功", data=data)
    except Exception as e:
        print(f"[Review] create review 异常: {e}")
        return make_response(
            code=51003,
            message=f"保存复盘失败: {e}",
            data={},
        )


@router.get("/reviews", summary="获取复盘记录列表")
async def list_reviews(
    review_type: Optional[str] = Query(None, description="按类型筛选：daily/weekly/monthly"),
    limit: int = Query(20, description="返回条数限制", ge=1, le=100),
    x_user_id: str = Header("default", description="用户 ID"),
):
    """获取复盘记录列表，支持按类型筛选."""
    try:
        service = _get_service(x_user_id)
        data = service.list_reviews(review_type=review_type, limit=limit)
        return make_response(data=data)
    except Exception as e:
        print(f"[Review] list reviews 异常: {e}")
        return make_response(
            code=51004,
            message=f"获取复盘列表失败: {e}",
            data=[],
        )


@router.get("/reviews/{review_id}", summary="获取复盘详情")
async def get_review_detail(
    review_id: int,
    x_user_id: str = Header("default", description="用户 ID"),
):
    """获取复盘详情."""
    try:
        service = _get_service(x_user_id)
        data = service.get_review_detail(review_id)
        if data is None:
            return make_response(
                code=40401,
                message="复盘记录不存在",
                data={},
            )
        return make_response(data=data)
    except Exception as e:
        print(f"[Review] review detail 异常: {e}")
        return make_response(
            code=51005,
            message=f"获取复盘详情失败: {e}",
            data={},
        )


@router.delete("/reviews/{review_id}", summary="删除复盘记录")
async def delete_review(
    review_id: int,
    x_user_id: str = Header("default", description="用户 ID"),
):
    """删除复盘记录."""
    try:
        service = _get_service(x_user_id)
        success = service.delete_review(review_id)
        if not success:
            return make_response(
                code=40401,
                message="复盘记录不存在",
                data={},
            )
        return make_response(message="复盘删除成功", data={})
    except Exception as e:
        print(f"[Review] delete review 异常: {e}")
        return make_response(
            code=51006,
            message=f"删除复盘失败: {e}",
            data={},
        )


# ---------------------------------------------------------------------------
# 情绪追踪接口
# ---------------------------------------------------------------------------


@router.get("/emotions", summary="获取情绪记录列表")
async def list_emotions(
    days: int = Query(30, description="获取最近 N 天的记录", ge=1, le=365),
    x_user_id: str = Header("default", description="用户 ID"),
):
    """获取情绪记录列表."""
    try:
        service = _get_service(x_user_id)
        data = service.list_emotions(days=days)
        return make_response(data=data)
    except Exception as e:
        print(f"[Review] list emotions 异常: {e}")
        return make_response(
            code=51007,
            message=f"获取情绪记录失败: {e}",
            data=[],
        )


@router.post("/emotions", summary="记录情绪")
async def record_emotion(
    req: EmotionRecordRequest,
    x_user_id: str = Header("default", description="用户 ID"),
):
    """记录一条情绪数据."""
    try:
        service = _get_service(x_user_id)
        data = service.record_emotion(
            emotion=req.emotion,
            level=req.level,
            trigger=req.trigger or "",
            note=req.note or "",
        )
        return make_response(message="情绪记录成功", data=data)
    except Exception as e:
        print(f"[Review] record emotion 异常: {e}")
        return make_response(
            code=51008,
            message=f"记录情绪失败: {e}",
            data={},
        )


@router.get("/emotions/stats", summary="获取情绪统计")
async def get_emotion_stats(
    days: int = Query(30, description="统计天数", ge=1, le=365),
    x_user_id: str = Header("default", description="用户 ID"),
):
    """获取情绪统计数据，包括分布、趋势和主导情绪."""
    try:
        service = _get_service(x_user_id)
        data = service.get_emotion_stats(days=days)
        return make_response(data=data)
    except Exception as e:
        print(f"[Review] emotion stats 异常: {e}")
        return make_response(
            code=51009,
            message=f"获取情绪统计失败: {e}",
            data={},
        )


# ---------------------------------------------------------------------------
# 决策回溯接口
# ---------------------------------------------------------------------------


@router.get("/decisions", summary="获取决策记录列表")
async def list_decisions(
    limit: int = Query(20, description="返回条数限制", ge=1, le=100),
    x_user_id: str = Header("default", description="用户 ID"),
):
    """获取决策记录列表."""
    try:
        service = _get_service(x_user_id)
        data = service.list_decisions(limit=limit)
        return make_response(data=data)
    except Exception as e:
        print(f"[Review] list decisions 异常: {e}")
        return make_response(
            code=51010,
            message=f"获取决策列表失败: {e}",
            data=[],
        )


@router.get("/decisions/{decision_id}", summary="获取决策详情")
async def get_decision_detail(
    decision_id: int,
    x_user_id: str = Header("default", description="用户 ID"),
):
    """获取决策详情."""
    try:
        service = _get_service(x_user_id)
        data = service.get_decision_detail(decision_id)
        if data is None:
            return make_response(
                code=40402,
                message="决策记录不存在",
                data={},
            )
        return make_response(data=data)
    except Exception as e:
        print(f"[Review] decision detail 异常: {e}")
        return make_response(
            code=51011,
            message=f"获取决策详情失败: {e}",
            data={},
        )


@router.post("/decisions", summary="创建决策记录")
async def create_decision(
    req: DecisionCreateRequest,
    x_user_id: str = Header("default", description="用户 ID"),
):
    """创建一条决策记录."""
    try:
        service = _get_service(x_user_id)
        data = service.create_decision(
            title=req.title,
            description=req.description,
            options=req.options,
            final_choice=req.final_choice or "",
            result=req.result or "",
            emotion_level=req.emotion_level or 5,
        )
        return make_response(message="决策记录创建成功", data=data)
    except Exception as e:
        print(f"[Review] create decision 异常: {e}")
        return make_response(
            code=51012,
            message=f"创建决策失败: {e}",
            data={},
        )


@router.put("/decisions/{decision_id}", summary="更新决策记录")
async def update_decision(
    decision_id: int,
    req: DecisionUpdateRequest,
    x_user_id: str = Header("default", description="用户 ID"),
):
    """更新决策记录，支持部分更新.

    可更新字段：title, description, status, final_choice, result, emotion_level, alternatives
    """
    try:
        service = _get_service(x_user_id)
        # 只传递非 None 的字段
        update_data = req.dict(exclude_unset=True)
        if not update_data:
            return make_response(
                code=40001,
                message="没有需要更新的字段",
                data={},
            )
        data = service.update_decision(decision_id, update_data)
        if data is None:
            return make_response(
                code=40402,
                message="决策记录不存在",
                data={},
            )
        return make_response(message="决策更新成功", data=data)
    except Exception as e:
        print(f"[Review] update decision 异常: {e}")
        return make_response(
            code=51013,
            message=f"更新决策失败: {e}",
            data={},
        )


@router.delete("/decisions/{decision_id}", summary="删除决策记录")
async def delete_decision(
    decision_id: int,
    x_user_id: str = Header("default", description="用户 ID"),
):
    """删除决策记录."""
    try:
        service = _get_service(x_user_id)
        success = service.delete_decision(decision_id)
        if not success:
            return make_response(
                code=40402,
                message="决策记录不存在",
                data={},
            )
        return make_response(message="决策删除成功", data={})
    except Exception as e:
        print(f"[Review] delete decision 异常: {e}")
        return make_response(
            code=51014,
            message=f"删除决策失败: {e}",
            data={},
        )


# ---------------------------------------------------------------------------
# 认知偏差检测接口
# ---------------------------------------------------------------------------


@router.get("/biases", summary="获取认知偏差列表")
async def list_biases(
    x_user_id: str = Header("default", description="用户 ID"),
):
    """获取认知偏差检测列表."""
    try:
        service = _get_service(x_user_id)
        data = service.list_biases()
        return make_response(data=data)
    except Exception as e:
        print(f"[Review] list biases 异常: {e}")
        return make_response(
            code=51015,
            message=f"获取偏差列表失败: {e}",
            data=[],
        )


@router.post("/biases/analyze", summary="分析认知偏差")
async def analyze_bias(
    req: BiasAnalyzeRequest,
    x_user_id: str = Header("default", description="用户 ID"),
):
    """分析文本中的认知偏差.

    接收决策描述文本，检测其中可能存在的认知偏差，
    返回偏差名称、描述、风险等级和建议。
    """
    try:
        service = _get_service(x_user_id)
        data = service.analyze_bias(req.text)
        return make_response(message="分析完成", data=data)
    except Exception as e:
        print(f"[Review] analyze bias 异常: {e}")
        return make_response(
            code=51016,
            message=f"偏差分析失败: {e}",
            data={},
        )


# ---------------------------------------------------------------------------
# 私密日记接口
# ---------------------------------------------------------------------------


@router.get("/diaries", summary="获取日记列表")
async def list_diaries(
    limit: int = Query(20, description="返回条数限制", ge=1, le=100),
    x_user_id: str = Header("default", description="用户 ID"),
):
    """获取日记列表."""
    try:
        service = _get_service(x_user_id)
        data = service.list_diaries(limit=limit)
        return make_response(data=data)
    except Exception as e:
        print(f"[Review] list diaries 异常: {e}")
        return make_response(
            code=51017,
            message=f"获取日记列表失败: {e}",
            data=[],
        )


@router.get("/diaries/{diary_id}", summary="获取日记详情")
async def get_diary_detail(
    diary_id: int,
    x_user_id: str = Header("default", description="用户 ID"),
):
    """获取日记详情."""
    try:
        service = _get_service(x_user_id)
        data = service.get_diary_detail(diary_id)
        if data is None:
            return make_response(
                code=40403,
                message="日记不存在",
                data={},
            )
        return make_response(data=data)
    except Exception as e:
        print(f"[Review] diary detail 异常: {e}")
        return make_response(
            code=51018,
            message=f"获取日记详情失败: {e}",
            data={},
        )


@router.post("/diaries", summary="创建日记")
async def create_diary(
    req: DiaryCreateRequest,
    x_user_id: str = Header("default", description="用户 ID"),
):
    """创建一篇日记."""
    try:
        service = _get_service(x_user_id)
        data = service.create_diary(
            title=req.title,
            content=req.content,
            mood=req.mood or "neutral",
            tags=req.tags,
        )
        return make_response(message="日记保存成功", data=data)
    except Exception as e:
        print(f"[Review] create diary 异常: {e}")
        return make_response(
            code=51019,
            message=f"保存日记失败: {e}",
            data={},
        )


@router.delete("/diaries/{diary_id}", summary="删除日记")
async def delete_diary(
    diary_id: int,
    x_user_id: str = Header("default", description="用户 ID"),
):
    """删除日记."""
    try:
        service = _get_service(x_user_id)
        success = service.delete_diary(diary_id)
        if not success:
            return make_response(
                code=40403,
                message="日记不存在",
                data={},
            )
        return make_response(message="日记删除成功", data={})
    except Exception as e:
        print(f"[Review] delete diary 异常: {e}")
        return make_response(
            code=51020,
            message=f"删除日记失败: {e}",
            data={},
        )


# ---------------------------------------------------------------------------
# 复盘模板接口
# ---------------------------------------------------------------------------


@router.get("/templates", summary="获取复盘模板列表")
async def get_templates(
    x_user_id: str = Header("default", description="用户 ID"),
):
    """获取复盘模板列表."""
    try:
        service = _get_service(x_user_id)
        data = service.get_templates()
        return make_response(data=data)
    except Exception as e:
        print(f"[Review] templates 异常: {e}")
        return make_response(
            code=51021,
            message=f"获取模板失败: {e}",
            data=[],
        )


# ---------------------------------------------------------------------------
# 数据统计接口
# ---------------------------------------------------------------------------


@router.get("/stats", summary="获取复盘数据统计")
async def get_stats(
    x_user_id: str = Header("default", description="用户 ID"),
):
    """获取复盘数据统计，包括总数、字数、月度统计和质量分布."""
    try:
        service = _get_service(x_user_id)
        data = service.get_stats()
        return make_response(data=data)
    except Exception as e:
        print(f"[Review] stats 异常: {e}")
        return make_response(
            code=51022,
            message=f"获取统计失败: {e}",
            data={},
        )
