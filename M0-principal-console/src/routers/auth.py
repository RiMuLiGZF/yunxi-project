"""
M0 主理人管控台 - 认证路由

提供登录、登出、Token 刷新等认证相关接口。
只有 Owner 角色才能登录 M0。
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from fastapi import APIRouter, Depends

from ..auth import (
    authenticate_principal,
    create_access_token,
    get_principal_user,
)
from ..config import settings
from ..errors import AuthenticationError
from ..models import ApiResponse, LoginData, LoginRequest, UserInfo

router = APIRouter(tags=["认证"])


@router.post("/login", summary="主理人登录")
async def login(request: LoginRequest) -> ApiResponse[LoginData]:
    """
    主理人登录接口

    验证用户名密码，成功后返回 JWT Token（Owner 角色）。
    """
    user = authenticate_principal(request.username, request.password)
    if not user:
        raise AuthenticationError(message="用户名或密码错误")

    # 创建 Token
    access_token = create_access_token(
        data={
            "sub": user["username"],
            "role": user["role"],
            "display_name": user.get("display_name", ""),
        },
        expires_delta=timedelta(minutes=settings.access_token_expire_minutes),
    )

    login_data = LoginData(
        access_token=access_token,
        token_type="bearer",
        username=user["username"],
        role=user["role"],
        expires_in=settings.access_token_expire_minutes * 60,
    )

    return ApiResponse.success(data=login_data, message="登录成功")


@router.post("/logout", summary="登出")
async def logout(user: dict = Depends(get_principal_user)) -> ApiResponse[Any]:
    """
    登出接口

    MVP 版本：前端清除 Token 即可，后端无需特殊处理。
    """
    return ApiResponse.success(message="登出成功")


@router.get("/me", summary="获取当前用户信息")
async def get_me(user: dict = Depends(get_principal_user)) -> ApiResponse[UserInfo]:
    """
    获取当前登录用户信息
    """
    user_info = UserInfo(
        username=user["username"],
        role=user["role"],
        display_name=user.get("display_name", "主理人"),
    )
    return ApiResponse.success(data=user_info)


@router.post("/refresh", summary="刷新 Token")
async def refresh_token(user: dict = Depends(get_principal_user)) -> ApiResponse[LoginData]:
    """
    刷新访问令牌

    使用当前有效 Token 获取新的 Token。
    """
    new_token = create_access_token(
        data={
            "sub": user["username"],
            "role": user["role"],
        },
        expires_delta=timedelta(minutes=settings.access_token_expire_minutes),
    )

    login_data = LoginData(
        access_token=new_token,
        token_type="bearer",
        username=user["username"],
        role=user["role"],
        expires_in=settings.access_token_expire_minutes * 60,
    )

    return ApiResponse.success(data=login_data, message="Token 刷新成功")
