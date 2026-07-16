"""
用户画像与个性化设置 API
"""

import sys
from pathlib import Path
from typing import Optional, List, Dict, Any
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

project_root = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(project_root))

from ..schemas import ApiResponse
from ..auth import get_current_user
from shared.user_profile import get_user_profile_manager, PreferenceCategory

router = APIRouter()
profile_mgr = get_user_profile_manager()


# ==================== Pydantic 模型 ====================

class PreferenceUpdate(BaseModel):
    """偏好更新请求"""
    category: str
    key: str
    value: Any
    source: str = "explicit"


class ProfileUpdate(BaseModel):
    """画像更新请求"""
    nickname: Optional[str] = None
    avatar: Optional[str] = None
    age: Optional[int] = None
    gender: Optional[str] = None
    location: Optional[str] = None
    language: Optional[str] = None


class UserCreate(BaseModel):
    """创建用户请求"""
    user_id: str
    nickname: str = ""
    avatar: str = ""


# ==================== 用户画像接口 ====================

@router.get("/profile")
async def get_profile(
    user_id: Optional[str] = None,
    current_user: dict = Depends(get_current_user)
):
    """获取用户画像"""
    uid = user_id or "default"
    profile = profile_mgr.get_profile(uid)
    return ApiResponse.success(data=profile.to_dict())


@router.put("/profile")
async def update_profile(
    update: ProfileUpdate,
    user_id: Optional[str] = None,
    current_user: dict = Depends(get_current_user)
):
    """更新用户画像基本信息"""
    uid = user_id or "default"
    profile = profile_mgr.get_profile(uid)
    
    update_data = update.model_dump(exclude_unset=True)
    for key, value in update_data.items():
        if hasattr(profile, key):
            setattr(profile, key, value)
    
    # 手动触发保存
    profile_mgr._save_profile(profile)
    
    return ApiResponse.success(
        message="画像更新成功",
        data=profile.to_dict()
    )


@router.get("/users")
async def list_users(current_user: dict = Depends(get_current_user)):
    """获取所有用户列表"""
    users = profile_mgr.get_all_users()
    return ApiResponse.success(data={
        "total": len(users),
        "items": users,
    })


@router.post("/users")
async def create_user(
    user: UserCreate,
    current_user: dict = Depends(get_current_user)
):
    """创建新用户"""
    profile = profile_mgr.create_profile(
        user_id=user.user_id,
        nickname=user.nickname,
        avatar=user.avatar,
    )
    return ApiResponse.success(
        message="用户创建成功",
        data=profile.to_dict()
    )


@router.delete("/users/{user_id}")
async def delete_user(
    user_id: str,
    current_user: dict = Depends(get_current_user)
):
    """删除用户"""
    success = profile_mgr.delete_profile(user_id)
    if not success:
        return ApiResponse.error(message="删除失败或用户不存在")
    return ApiResponse.success(message="用户删除成功")


# ==================== 偏好设置接口 ====================

@router.get("/preferences")
async def get_preferences(
    user_id: Optional[str] = None,
    category: Optional[str] = None,
    current_user: dict = Depends(get_current_user)
):
    """获取用户偏好"""
    uid = user_id or "default"
    prefs = profile_mgr.get_all_preferences(uid, category)
    return ApiResponse.success(data=prefs)


@router.put("/preferences")
async def set_preference(
    pref: PreferenceUpdate,
    user_id: Optional[str] = None,
    current_user: dict = Depends(get_current_user)
):
    """设置用户偏好"""
    uid = user_id or "default"
    profile_mgr.set_preference(
        uid,
        category=pref.category,
        key=pref.key,
        value=pref.value,
        source=pref.source,
    )
    return ApiResponse.success(message="偏好设置成功")


@router.get("/preferences/categories")
async def get_preference_categories(current_user: dict = Depends(get_current_user)):
    """获取偏好类别列表"""
    categories = [
        {"id": cat.value, "name": _get_category_name(cat.value), "description": _get_category_desc(cat.value)}
        for cat in PreferenceCategory
    ]
    return ApiResponse.success(data=categories)


@router.get("/preferences/topics")
async def get_top_topics(
    user_id: Optional[str] = None,
    top_n: int = 5,
    current_user: dict = Depends(get_current_user)
):
    """获取用户最感兴趣的话题"""
    uid = user_id or "default"
    topics = profile_mgr.get_topics(uid, top_n)
    return ApiResponse.success(data={
        "topics": [{"topic": t, "confidence": c} for t, c in topics]
    })


@router.get("/preferences/active-hours")
async def get_active_hours(
    user_id: Optional[str] = None,
    current_user: dict = Depends(get_current_user)
):
    """获取用户活跃时段"""
    uid = user_id or "default"
    hours = profile_mgr.get_active_hours(uid)
    return ApiResponse.success(data={"active_hours": hours})


# ==================== 个性化提示词接口 ====================

@router.post("/personalize-prompt")
async def personalize_prompt(
    prompt: str,
    user_id: Optional[str] = None,
    current_user: dict = Depends(get_current_user)
):
    """生成个性化提示词"""
    uid = user_id or "default"
    personalized = profile_mgr.get_personalized_prompt(uid, prompt)
    return ApiResponse.success(data={
        "original": prompt,
        "personalized": personalized,
        "has_enhancements": personalized != prompt,
    })


# ==================== 辅助函数 ====================

def _get_category_name(category: str) -> str:
    """获取类别中文名"""
    names = {
        "communication_style": "沟通风格",
        "content_depth": "内容深度",
        "voice": "语音偏好",
        "topic_interest": "话题兴趣",
        "language": "语言偏好",
        "visual": "视觉偏好",
        "habit": "使用习惯",
    }
    return names.get(category, category)


def _get_category_desc(category: str) -> str:
    """获取类别描述"""
    descs = {
        "communication_style": "语气、正式程度、回复长度等沟通偏好",
        "content_depth": "内容详细程度、技术深度偏好",
        "voice": "音色、语速、情感等语音偏好",
        "topic_interest": "感兴趣的话题领域",
        "language": "使用语言、方言偏好",
        "visual": "界面主题、视觉效果偏好",
        "habit": "使用时段、常用功能等习惯",
    }
    return descs.get(category, "")
