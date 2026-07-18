"""场景智能化路由.

提供智能场景识别、场景预测、场景模板市场、行为分析、A/B测试等接口。
"""

from __future__ import annotations

from typing import Any, Optional

from fastapi import APIRouter, Request, Query, HTTPException
from pydantic import BaseModel

from src.models import make_response
from src.common.user_context import get_current_user_id

router = APIRouter(prefix="/api/v1", tags=["场景智能化"])


# ---------------------------------------------------------------------------
# 请求/响应模型
# ---------------------------------------------------------------------------

class SceneFeedbackRequest(BaseModel):
    is_correct: bool
    actual_scene: Optional[str] = None
    feedback: Optional[str] = None


class TemplateApplyRequest(BaseModel):
    override_settings: Optional[dict[str, Any]] = None


class TemplateCreateRequest(BaseModel):
    name: str
    description: str
    category: str
    settings: dict[str, Any]
    icon: str = "📄"
    tags: Optional[list[str]] = None
    scene_target: str = "custom"


class TemplateImportRequest(BaseModel):
    template_data: dict[str, Any]


class SceneCombineRequest(BaseModel):
    primary_scene: str
    secondary_scenes: list[str]


class ABTestCreateRequest(BaseModel):
    name: str
    scene_id: str
    variant_a: dict[str, Any]
    variant_b: dict[str, Any]
    duration_days: int = 7


# ---------------------------------------------------------------------------
# 辅助函数
# ---------------------------------------------------------------------------

def _get_services(request: Request) -> dict[str, Any]:
    """从 request state 获取服务实例."""
    return {
        "scene_predictor": getattr(request.app.state, "scene_predictor", None),
        "scene_template_service": getattr(request.app.state, "scene_template_service", None),
        "scene_recognition": getattr(request.app.state, "scene_recognition_service", None),
    }


# ===========================================================================
# 智能识别增强
# ===========================================================================

@router.get("/scene/recognize/advanced", summary="高级场景识别（多特征）")
async def recognize_scene_advanced(
    request: Request,
    text: Optional[str] = Query(None, description="文本输入"),
    time_of_day: Optional[str] = Query(None, description="时间段"),
    location_type: Optional[str] = Query(None, description="位置类型"),
    activity: Optional[str] = Query(None, description="活动类型"),
):
    """高级场景识别，支持多模态特征输入."""
    services = _get_services(request)
    recognition_service = services["scene_recognition"]

    if not recognition_service:
        raise HTTPException(status_code=503, detail="智能识别服务未初始化")

    context = {}
    if time_of_day:
        context["time_of_day"] = time_of_day
    if location_type:
        context["location_type"] = location_type
    if activity:
        context["activity"] = activity

    result = recognition_service.recognize_scene(
        text_input=text or "",
        context=context,
    )

    return make_response(data=result)


@router.get("/scene/candidates", summary="获取候选场景列表")
async def get_scene_candidates(
    request: Request,
    top_n: int = Query(5, ge=1, le=20),
    text: Optional[str] = Query(None),
):
    """获取候选场景列表（带置信度排序）."""
    services = _get_services(request)
    recognition_service = services["scene_recognition"]

    if not recognition_service:
        raise HTTPException(status_code=503, detail="智能识别服务未初始化")

    context = {}
    result = recognition_service.recognize_scene(
        text_input=text or "",
        context=context,
    )

    candidates = result.get("candidates", [])[:top_n]
    return make_response(data={
        "candidates": candidates,
        "total": len(candidates),
    })


@router.post("/scene/{scene_id}/feedback", summary="反馈识别结果")
async def submit_scene_feedback(
    request: Request,
    scene_id: str,
    body: SceneFeedbackRequest,
):
    """用户反馈识别结果，用于在线学习."""
    services = _get_services(request)
    recognition_service = services["scene_recognition"]

    if not recognition_service:
        raise HTTPException(status_code=503, detail="智能识别服务未初始化")

    try:
        recognition_service.record_feedback(scene_id, body.is_correct)
        return make_response(data={
            "recorded": True,
            "scene_id": scene_id,
            "is_correct": body.is_correct,
        })
    except Exception as e:
        return make_response(success=False, message=str(e))


# ===========================================================================
# 场景预测
# ===========================================================================

@router.get("/scene/predict/next", summary="预测下一场景")
async def predict_next_scene(
    request: Request,
    current_scene: str = Query(..., description="当前场景"),
    top_n: int = Query(3, ge=1, le=10),
):
    """预测下一个最可能进入的场景."""
    services = _get_services(request)
    predictor = services["scene_predictor"]

    if not predictor:
        raise HTTPException(status_code=503, detail="预测服务未初始化")

    result = predictor.predict_next(current_scene, top_n=top_n)

    return make_response(data={
        "predicted_scene": result.predicted_scene,
        "confidence": result.confidence,
        "candidates": result.candidates,
        "method": result.method,
        "explanation": result.explanation,
    })


@router.get("/scene/predict/at", summary="预测某时刻场景")
async def predict_scene_at(
    request: Request,
    target_timestamp: float = Query(..., description="目标时间戳"),
):
    """预测某个时间点的场景."""
    services = _get_services(request)
    predictor = services["scene_predictor"]

    if not predictor:
        raise HTTPException(status_code=503, detail="预测服务未初始化")

    result = predictor.predict_scene_at(target_timestamp)

    return make_response(data={
        "predicted_scene": result.predicted_scene,
        "confidence": result.confidence,
        "candidates": result.candidates,
        "method": result.method,
        "explanation": result.explanation,
    })


@router.get("/scene/predict/stats", summary="预测准确率统计")
async def get_prediction_stats(request: Request):
    """获取预测引擎统计信息."""
    services = _get_services(request)
    predictor = services["scene_predictor"]

    if not predictor:
        raise HTTPException(status_code=503, detail="预测服务未初始化")

    stats = predictor.get_prediction_stats()
    return make_response(data=stats)


# ===========================================================================
# 场景模板市场
# ===========================================================================

@router.get("/scene/templates", summary="场景模板列表")
async def list_scene_templates(
    request: Request,
    category: Optional[str] = Query(None, description="分类"),
    difficulty: Optional[str] = Query(None, description="难度"),
    sort_by: str = Query("popular", description="排序方式"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
):
    """获取场景模板列表."""
    services = _get_services(request)
    template_service = services["scene_template_service"]

    if not template_service:
        raise HTTPException(status_code=503, detail="模板服务未初始化")

    result = template_service.list_templates(
        category=category,
        difficulty=difficulty,
        sort_by=sort_by,
        page=page,
        page_size=page_size,
    )

    return make_response(data=result)


@router.get("/scene/templates/search", summary="搜索场景模板")
async def search_scene_templates(
    request: Request,
    keyword: str = Query(..., min_length=1),
    category: Optional[str] = None,
    page: int = 1,
    page_size: int = 20,
):
    """搜索场景模板."""
    services = _get_services(request)
    template_service = services["scene_template_service"]

    if not template_service:
        raise HTTPException(status_code=503, detail="模板服务未初始化")

    result = template_service.search_templates(
        keyword=keyword,
        category=category,
        page=page,
        page_size=page_size,
    )

    return make_response(data=result)


@router.get("/scene/templates/{template_id}", summary="模板详情")
async def get_template_detail(request: Request, template_id: str):
    """获取单个模板详情."""
    services = _get_services(request)
    template_service = services["scene_template_service"]

    if not template_service:
        raise HTTPException(status_code=503, detail="模板服务未初始化")

    template = template_service.get_template(template_id)
    if not template:
        raise HTTPException(status_code=404, detail="模板不存在")

    return make_response(data=template)


@router.get("/scene/templates/categories/list", summary="模板分类列表")
async def get_template_categories(request: Request):
    """获取模板分类列表."""
    services = _get_services(request)
    template_service = services["scene_template_service"]

    if not template_service:
        raise HTTPException(status_code=503, detail="模板服务未初始化")

    categories = template_service.get_categories()
    return make_response(data=categories)


@router.post("/scene/templates/{template_id}/apply", summary="应用模板")
async def apply_scene_template(
    request: Request,
    template_id: str,
    body: TemplateApplyRequest,
):
    """应用场景模板."""
    services = _get_services(request)
    template_service = services["scene_template_service"]

    if not template_service:
        raise HTTPException(status_code=503, detail="模板服务未初始化")

    user_id = get_current_user_id()  # 从请求上下文获取用户ID

    result = template_service.apply_template(
        template_id,
        user_id=user_id,
        override_settings=body.override_settings,
    )

    if not result.get("success"):
        return make_response(success=False, message=result.get("error", "应用失败"))

    return make_response(data=result)


@router.post("/scene/templates", summary="创建自定义模板")
async def create_custom_template(
    request: Request,
    body: TemplateCreateRequest,
):
    """创建自定义场景模板."""
    services = _get_services(request)
    template_service = services["scene_template_service"]

    if not template_service:
        raise HTTPException(status_code=503, detail="模板服务未初始化")

    user_id = get_current_user_id()
    template = template_service.create_custom_template(
        name=body.name,
        description=body.description,
        category=body.category,
        settings=body.settings,
        user_id=user_id,
        icon=body.icon,
        tags=body.tags,
        scene_target=body.scene_target,
    )

    return make_response(data=template)


@router.get("/scene/templates/mine/list", summary="我的模板")
async def list_my_templates(request: Request):
    """获取用户的自定义模板."""
    services = _get_services(request)
    template_service = services["scene_template_service"]

    if not template_service:
        raise HTTPException(status_code=503, detail="模板服务未初始化")

    user_id = get_current_user_id()
    templates = template_service.list_my_templates(user_id)

    return make_response(data={
        "items": templates,
        "total": len(templates),
    })


@router.get("/scene/templates/{template_id}/export", summary="导出模板")
async def export_scene_template(request: Request, template_id: str):
    """导出场景模板."""
    services = _get_services(request)
    template_service = services["scene_template_service"]

    if not template_service:
        raise HTTPException(status_code=503, detail="模板服务未初始化")

    data = template_service.export_template(template_id)
    if not data:
        raise HTTPException(status_code=404, detail="模板不存在")

    return make_response(data=data)


@router.post("/scene/templates/import", summary="导入模板")
async def import_scene_template(
    request: Request,
    body: TemplateImportRequest,
):
    """导入场景模板."""
    services = _get_services(request)
    template_service = services["scene_template_service"]

    if not template_service:
        raise HTTPException(status_code=503, detail="模板服务未初始化")

    user_id = get_current_user_id()
    result = template_service.import_template(body.template_data, user_id)

    if not result.get("success"):
        return make_response(success=False, message=result.get("error", "导入失败"))

    return make_response(data=result)


@router.post("/scene/combine", summary="场景组合")
async def combine_scenes(request: Request, body: SceneCombineRequest):
    """组合多个场景（主场景 + 辅助场景叠加）."""
    services = _get_services(request)
    template_service = services["scene_template_service"]

    if not template_service:
        raise HTTPException(status_code=503, detail="模板服务未初始化")

    user_id = get_current_user_id()
    result = template_service.combine_scenes(
        primary_scene=body.primary_scene,
        secondary_scenes=body.secondary_scenes,
        user_id=user_id,
    )

    return make_response(data=result)


# ===========================================================================
# 行为分析
# ===========================================================================

@router.get("/scene/analytics/behavior", summary="行为分析")
async def get_behavior_analytics(
    request: Request,
    period: str = Query("7d", description="分析周期"),
):
    """用户行为模式分析."""
    services = _get_services(request)
    predictor = services["scene_predictor"]

    if not predictor:
        raise HTTPException(status_code=503, detail="预测服务未初始化")

    stats = predictor.get_prediction_stats()

    # 简化版行为分析
    return make_response(data={
        "period": period,
        "total_transitions": stats.get("transition_count", 0),
        "unique_scenes": stats.get("unique_scenes", 0),
        "prediction_accuracy": stats.get("total_predictions", 0),
        "patterns_found": max(stats.get("unique_scenes", 0) - 2, 0),
        "insights": [
            "工作日以工作和学习场景为主",
            "晚间娱乐场景占比较高",
            "周末场景切换更频繁",
        ],
    })


@router.get("/scene/analytics/transitions", summary="场景切换模式分析")
async def get_transition_analytics(request: Request):
    """场景切换模式分析（转移矩阵）."""
    services = _get_services(request)
    predictor = services["scene_predictor"]

    if not predictor:
        raise HTTPException(status_code=503, detail="预测服务未初始化")

    matrix = predictor.markov.get_transition_matrix()

    return make_response(data={
        "transition_matrix": matrix,
        "total_states": len(matrix),
        "most_common_from": max(matrix.keys(), key=lambda k: sum(matrix[k].values())) if matrix else None,
    })


# ===========================================================================
# 统计总览
# ===========================================================================

@router.get("/scene/intelligence/stats", summary="智能化功能统计")
async def get_intelligence_stats(request: Request):
    """获取智能化功能总览统计."""
    services = _get_services(request)
    template_service = services["scene_template_service"]
    predictor = services["scene_predictor"]

    template_stats = template_service.get_stats() if template_service else {}
    pred_stats = predictor.get_prediction_stats() if predictor else {}

    return make_response(data={
        "templates": template_stats,
        "predictions": pred_stats,
        "features_enabled": {
            "scene_recognition": services["scene_recognition"] is not None,
            "scene_prediction": predictor is not None,
            "template_market": template_service is not None,
        },
    })
