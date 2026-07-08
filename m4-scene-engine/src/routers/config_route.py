"""场景配置路由.

提供场景配置的获取和更新接口。
"""

from __future__ import annotations

import copy
from typing import Any

from fastapi import APIRouter, Request

try:
    from src.models import SCENE_DEFINITIONS, SceneConfigUpdateRequest, make_response
except ImportError:
    from models import (  # type: ignore
        SCENE_DEFINITIONS,
        SceneConfigUpdateRequest,
        make_response,
    )

router = APIRouter(prefix="/api/v1/scene", tags=["场景配置"])

# 场景配置存储（内存）
_scene_configs: dict[str, dict[str, Any]] = {}


def _init_default_configs() -> None:
    """初始化默认场景配置."""
    global _scene_configs
    for scene_id, scene_def in SCENE_DEFINITIONS.items():
        _scene_configs[scene_id] = {
            "id": scene_def["id"],
            "name": scene_def["name"],
            "icon": scene_def["icon"],
            "description": scene_def["description"],
            "tone": scene_def["tone"],
            "keywords": list(scene_def.get("keywords", [])),
            "enabled": True,
            "priority": 50,
            "auto_switch_enabled": True,
            "custom_params": {},
        }


_init_default_configs()


# ---------------------------------------------------------------------------
# 获取场景配置
# ---------------------------------------------------------------------------

@router.get("/{scene_id}/config", summary="获取场景配置")
async def get_scene_config(
    request: Request,
    scene_id: str,
):
    """获取指定场景的配置信息.

    路径参数:
        scene_id: 场景ID
    """
    global _scene_configs

    if scene_id not in _scene_configs and scene_id not in SCENE_DEFINITIONS:
        return make_response(
            code=40401,
            message=f"场景不存在: {scene_id}",
            data={},
        )

    config = _scene_configs.get(scene_id)
    if config is None:
        # 从定义中创建
        scene_def = SCENE_DEFINITIONS.get(scene_id, {})
        config = {
            "id": scene_id,
            "name": scene_def.get("name", scene_id),
            "icon": scene_def.get("icon", "❓"),
            "description": scene_def.get("description", ""),
            "tone": scene_def.get("tone", ""),
            "keywords": list(scene_def.get("keywords", [])),
            "enabled": True,
            "priority": 50,
            "auto_switch_enabled": True,
            "custom_params": {},
        }
        _scene_configs[scene_id] = config

    # 兼容 M1 scene_manager_agent 的返回格式
    result = {
        "config": config,
        "scene_id": scene_id,
        "result": {"config": config},
    }

    return make_response(data=result)


# ---------------------------------------------------------------------------
# 更新场景配置
# ---------------------------------------------------------------------------

@router.post("/{scene_id}/config", summary="更新场景配置")
async def update_scene_config(
    request: Request,
    scene_id: str,
    body: SceneConfigUpdateRequest,
):
    """更新指定场景的配置信息.

    路径参数:
        scene_id: 场景ID
    请求体:
        config: 配置更新字典
    """
    global _scene_configs

    if scene_id not in _scene_configs and scene_id not in SCENE_DEFINITIONS:
        return make_response(
            code=40401,
            message=f"场景不存在: {scene_id}",
            data={},
        )

    if scene_id not in _scene_configs:
        # 初始化
        scene_def = SCENE_DEFINITIONS.get(scene_id, {})
        _scene_configs[scene_id] = {
            "id": scene_id,
            "name": scene_def.get("name", scene_id),
            "icon": scene_def.get("icon", "❓"),
            "description": scene_def.get("description", ""),
            "tone": scene_def.get("tone", ""),
            "keywords": list(scene_def.get("keywords", [])),
            "enabled": True,
            "priority": 50,
            "auto_switch_enabled": True,
            "custom_params": {},
        }

    config = _scene_configs[scene_id]
    updates = body.config
    updated_keys = []

    # 应用更新
    for key, value in updates.items():
        if key in ("id",):
            continue  # 不允许修改 ID
        config[key] = value
        updated_keys.append(key)

        # 如果更新了关键词，同步到识别器
        if key == "keywords" and hasattr(request.app.state, "recognizer"):
            request.app.state.recognizer.update_scene_keywords(
                scene_id, value
            )

    # 兼容 M1 返回格式
    result = {
        "config": config,
        "scene_id": scene_id,
        "updated_keys": updated_keys,
        "result": {"config": config},
    }

    return make_response(data=result)
