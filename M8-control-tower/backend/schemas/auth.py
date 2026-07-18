"""
M8 控制塔 - 认证 Schema 模型

包含登录、注册、Token 刷新、密码修改等认证相关的 Pydantic 模型。
用于请求参数校验和响应数据格式化。
"""

from typing import Optional, List
from datetime import datetime
from pydantic import BaseModel, Field, EmailStr, field_validator


# ═══════════════════════════════════════════════════════
# 登录相关
# ═══════════════════════════════════════════════════════

class LoginRequest(BaseModel):
    """登录请求体"""
    username: str = Field(..., min_length=3, max_length=50, description="用户名")
    password: str = Field(..., min_length=6, max_length=256, description="密码")
    remember_me: bool = Field(default=False, description="是否记住我（延长有效期）")


class LoginResponseData(BaseModel):
    """登录成功响应数据"""
    access_token: str = Field(description="访问令牌")
    refresh_token: str = Field(description="刷新令牌")
    token_type: str = Field(default="bearer", description="令牌类型")
    expires_in: int = Field(description="访问令牌有效期（秒）")
    user: "UserInfo" = Field(description="用户信息")


class LoginResponse(BaseModel):
    """登录响应"""
    code: int = Field(default=0, description="状态码")
    message: str = Field(default="登录成功", description="消息")
    data: Optional[LoginResponseData] = Field(default=None, description="响应数据")


# ═══════════════════════════════════════════════════════
# 注册相关
# ═══════════════════════════════════════════════════════

class RegisterRequest(BaseModel):
    """注册请求体"""
    username: str = Field(..., min_length=3, max_length=50, description="用户名")
    password: str = Field(..., min_length=8, max_length=256, description="密码（至少8位）")
    confirm_password: str = Field(..., description="确认密码")
    nickname: Optional[str] = Field(default=None, max_length=50, description="昵称")
    email: Optional[str] = Field(default=None, max_length=100, description="邮箱")

    @field_validator("confirm_password")
    @classmethod
    def passwords_match(cls, v: str, info) -> str:
        password = info.data.get("password")
        if password and v != password:
            raise ValueError("两次输入的密码不一致")
        return v


class RegisterResponseData(BaseModel):
    """注册成功响应数据"""
    user_id: int = Field(description="用户ID")
    username: str = Field(description="用户名")
    nickname: str = Field(description="昵称")
    role: str = Field(description="角色")
    created_at: datetime = Field(description="创建时间")


# ═══════════════════════════════════════════════════════
# Token 相关
# ═══════════════════════════════════════════════════════

class TokenRefreshRequest(BaseModel):
    """刷新 Token 请求体"""
    refresh_token: str = Field(..., description="刷新令牌")


class TokenRefreshResponseData(BaseModel):
    """刷新 Token 响应数据"""
    access_token: str = Field(description="新的访问令牌")
    refresh_token: str = Field(description="新的刷新令牌")
    token_type: str = Field(default="bearer", description="令牌类型")
    expires_in: int = Field(description="有效期（秒）")


class TokenInfo(BaseModel):
    """Token 详细信息"""
    jti: str = Field(description="令牌唯一标识")
    sub: str = Field(description="主体（用户名）")
    role: str = Field(description="用户角色")
    iat: datetime = Field(description="签发时间")
    exp: datetime = Field(description="过期时间")
    is_expired: bool = Field(description="是否已过期")
    is_blacklisted: bool = Field(description="是否已加入黑名单")


class LogoutRequest(BaseModel):
    """登出请求体"""
    refresh_token: Optional[str] = Field(default=None, description="刷新令牌（可选，用于撤销 refresh token）")


# ═══════════════════════════════════════════════════════
# 密码管理
# ═══════════════════════════════════════════════════════

class ChangePasswordRequest(BaseModel):
    """修改密码请求体"""
    old_password: str = Field(..., description="原密码")
    new_password: str = Field(..., min_length=8, max_length=256, description="新密码（至少8位）")
    confirm_password: str = Field(..., description="确认新密码")

    @field_validator("confirm_password")
    @classmethod
    def passwords_match(cls, v: str, info) -> str:
        new_password = info.data.get("new_password")
        if new_password and v != new_password:
            raise ValueError("两次输入的密码不一致")
        return v


class ResetPasswordRequest(BaseModel):
    """重置密码请求体（管理员用）"""
    user_id: int = Field(..., description="用户ID")
    new_password: str = Field(..., min_length=8, max_length=256, description="新密码")


class PasswordStrengthCheckRequest(BaseModel):
    """密码强度检测请求"""
    password: str = Field(..., description="待检测的密码")


class PasswordStrengthInfo(BaseModel):
    """密码强度信息"""
    score: int = Field(description="强度评分 0-4")
    level: str = Field(description="强度等级: very_weak/weak/medium/strong/very_strong")
    suggestions: List[str] = Field(default_factory=list, description="改进建议")


# ═══════════════════════════════════════════════════════
# 用户信息（嵌套模型，需后向引用）
# ═══════════════════════════════════════════════════════

class UserInfo(BaseModel):
    """用户基础信息（用于登录响应等场景）"""
    id: int = Field(description="用户ID")
    username: str = Field(description="用户名")
    nickname: str = Field(description="昵称")
    role: str = Field(description="角色: admin/user/guest")
    email: Optional[str] = Field(default=None, description="邮箱")
    avatar: Optional[str] = Field(default=None, description="头像URL")
    status: str = Field(default="active", description="状态: active/disabled/locked")
    created_at: Optional[datetime] = Field(default=None, description="创建时间")
    last_login: Optional[datetime] = Field(default=None, description="最后登录时间")


# ═══════════════════════════════════════════════════════
# 验证码相关
# ═══════════════════════════════════════════════════════

class CaptchaResponseData(BaseModel):
    """验证码响应"""
    captcha_id: str = Field(description="验证码ID")
    captcha_image: str = Field(description="验证码图片（base64）")
    expires_in: int = Field(default=300, description="有效期（秒）")


class CaptchaVerifyRequest(BaseModel):
    """验证码校验请求"""
    captcha_id: str = Field(description="验证码ID")
    captcha_code: str = Field(description="验证码值")


# 解决前向引用
LoginResponseData.model_rebuild()
