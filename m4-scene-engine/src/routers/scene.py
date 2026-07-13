"""场景管理路由.

提供场景列表、当前场景、切换场景、场景识别、切换历史等接口。
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request, Query

from src.models import (
    SCENE_DEFINITIONS,
    SceneSwitchRequest,
    SceneRecognizeRequest,
    make_response,
)

router = APIRouter(prefix="/api/v1", tags=["场景管理"])


# ---------------------------------------------------------------------------
# 辅助函数
# ---------------------------------------------------------------------------

def _get_services(request: Request) -> dict[str, Any]:
    """从 request state 获取服务实例."""
    return {
        "switch_manager": request.app.state.switch_manager,
        "recognizer": request.app.state.recognizer,
        "health_metrics": getattr(request.app.state, "health_metrics", None),
    }


# ---------------------------------------------------------------------------
# 场景列表
# ---------------------------------------------------------------------------

@router.get("/scenes", summary="获取场景列表")
async def list_scenes(request: Request):
    """获取所有场景定义列表."""
    scenes = []
    for scene_id, scene_def in SCENE_DEFINITIONS.items():
        scenes.append({
            "id": scene_def["id"],
            "name": scene_def["name"],
            "icon": scene_def["icon"],
            "description": scene_def["description"],
            "tone": scene_def["tone"],
            "keyword_count": len(scene_def.get("keywords", [])),
        })

    return make_response(data={
        "total": len(scenes),
        "scenes": scenes,
    })


# ---------------------------------------------------------------------------
# 当前场景
# ---------------------------------------------------------------------------

@router.get("/scene/current", summary="获取当前场景")
async def get_current_scene(
    request: Request,
    user_id: str = Query("default", description="用户ID"),
):
    """获取当前激活的场景."""
    services = _get_services(request)
    switch_manager = services["switch_manager"]

    current_scene_id = switch_manager.get_current_scene(user_id)
    scene_def = SCENE_DEFINITIONS.get(current_scene_id, {
        "id": current_scene_id,
        "name": "未知场景",
        "icon": "❓",
        "description": "",
        "tone": "",
    })

    switch_count = switch_manager.get_switch_count(user_id)

    return make_response(data={
        "scene_id": current_scene_id,
        "scene_name": scene_def.get("name", ""),
        "icon": scene_def.get("icon", ""),
        "description": scene_def.get("description", ""),
        "tone": scene_def.get("tone", ""),
        "switch_count": switch_count,
        "user_id": user_id,
    })


# ---------------------------------------------------------------------------
# 切换场景
# ---------------------------------------------------------------------------

@router.post("/scene/switch", summary="切换场景")
async def switch_scene(request: Request, body: SceneSwitchRequest):
    """切换到指定场景.

    请求体:
        - from_scene: 源场景ID（可选，为空则使用当前场景）
        - to_scene: 目标场景ID
        - trigger_type: 触发类型 manual/auto/recognize
        - user_id: 用户ID
        - reason: 切换原因
    """
    services = _get_services(request)
    switch_manager = services["switch_manager"]
    health_metrics = services["health_metrics"]

    result = switch_manager.switch_scene(
        to_scene=body.to_scene,
        from_scene=body.from_scene,
        trigger_type=body.trigger_type,
        user_id=body.user_id,
        reason=body.reason,
    )

    # 记录指标
    if health_metrics is not None:
        health_metrics.metrics.record_switch(
            auto=(body.trigger_type == "auto")
        )

    if not result.get("success", False):
        return make_response(
            code=40001,
            message=result.get("reason", "场景切换失败"),
            data=result,
        )

    return make_response(data=result)


# ---------------------------------------------------------------------------
# 场景识别
# ---------------------------------------------------------------------------

@router.post("/scene/recognize", summary="场景识别")
async def recognize_scene(request: Request, body: SceneRecognizeRequest):
    """根据用户输入文本识别当前场景.

    请求体:
        - text: 用户输入文本
        - context: 上下文信息
        - user_id: 用户ID
        - include_all_scores: 是否返回所有场景得分
    """
    services = _get_services(request)
    recognizer = services["recognizer"]
    switch_manager = services["switch_manager"]
    health_metrics = services["health_metrics"]

    # 执行识别
    result = recognizer.recognize(
        text=body.text,
        context=body.context,
        include_all_scores=body.include_all_scores,
    )

    # 记录指标
    if health_metrics is not None:
        health_metrics.metrics.record_recognize()

    # 如果识别结果置信度足够高，且启用了自动切换，则自动切换
    top_scene = result.get("scene", "unknown")
    confidence = result.get("confidence", 0)
    auto_switch = getattr(request.app.state, "config", {}).get("auto_switch", True)
    threshold = getattr(request.app.state, "config", {}).get(
        "switch_confidence_threshold", 0.7
    )

    auto_switched = False
    if (
        auto_switch
        and top_scene != "unknown"
        and confidence >= threshold
        and top_scene in SCENE_DEFINITIONS
    ):
        current = switch_manager.get_current_scene(body.user_id)
        if top_scene != current:
            switch_manager.switch_scene(
                to_scene=top_scene,
                trigger_type="recognize",
                user_id=body.user_id,
                reason=f"自动识别切换，置信度 {confidence:.2%}",
            )
            auto_switched = True
            if health_metrics is not None:
                health_metrics.metrics.record_switch(auto=True)

    # 兼容 M1 scene_manager_agent 的返回格式
    response_data = {
        "result": result,
        "scene": top_scene,
        "top_scene": top_scene,
        "confidence": confidence,
        "auto_switched": auto_switched,
    }
    if body.include_all_scores:
        response_data["all_scores"] = result.get("all_scores", {})
        response_data["scores"] = result.get("scores", {})

    return make_response(data=response_data)


# ---------------------------------------------------------------------------
# 切换历史
# ---------------------------------------------------------------------------

@router.get("/scene/history", summary="场景切换历史")
async def get_scene_history(
    request: Request,
    user_id: str = Query("default", description="用户ID"),
    limit: int = Query(20, ge=1, le=100, description="返回条数"),
    offset: int = Query(0, ge=0, description="偏移量"),
):
    """获取场景切换历史记录."""
    services = _get_services(request)
    switch_manager = services["switch_manager"]

    history = switch_manager.get_history(
        user_id=user_id,
        limit=limit,
        offset=offset,
    )

    return make_response(data=history)
