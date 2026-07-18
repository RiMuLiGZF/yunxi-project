"""
M8 控制塔 - 用户管理 Schema 模型

包含用户列表、用户详情、用户创建/更新等用户管理相关的 Pydantic 模型。
"""

from typing import Optional, List, Dict, Any
from datetime import datetime
from pydantic import BaseModel, Field, EmailStr, field_validator


# ═══════════════════════════════════════════════════════
# 用户基础信息
# ═══════════════════════════════════════════════════════

class UserBase(BaseModel):
    """用户基础字段"""
    username: str = Field(..., min_length=3, max_length=50, description="用户名")
    nickname: Optional[str] = Field(default=None, max_length=50, description="昵称")
    email: Optional[str] = Field(default=None, max_length=100, description="邮箱")
    phone: Optional[str] = Field(default=None, max_length=20, description="手机号")
    role: str = Field(default="user", description="角色: admin/user/guest")
    status: str = Field(default="active", description="状态: active/disabled/locked")


class UserCreate(UserBase):
    """创建用户请求"""
    password: str = Field(..., min_length=8, max_length=256, description="密码（至少8位）")
    confirm_password: str = Field(..., description="确认密码")

    @field_validator("confirm_password")
    @classmethod
    def passwords_match(cls, v: str, info) -> str:
        password = info.data.get("password")
        if password and v != password:
            raise ValueError("两次输入的密码不一致")
        return v


class UserUpdate(BaseModel):
    """更新用户请求（部分更新）"""
    nickname: Optional[str] = Field(default=None, max_length=50, description="昵称")
    email: Optional[str] = Field(default=None, max_length=100, description="邮箱")
    phone: Optional[str] = Field(default=None, max_length=20, description="手机号")
    role: Optional[str] = Field(default=None, description="角色")
    status: Optional[str] = Field(default=None, description="状态")
    avatar: Optional[str] = Field(default=None, description="头像URL")


class UserResponse(BaseModel):
    """用户信息响应"""
    id: int = Field(description="用户ID")
    username: str = Field(description="用户名")
    nickname: str = Field(description="昵称")
    email: Optional[str] = Field(default=None, description="邮箱")
    phone: Optional[str] = Field(default=None, description="手机号")
    role: str = Field(description="角色")
    status: str = Field(description="状态")
    avatar: Optional[str] = Field(default=None, description="头像URL")
    created_at: Optional[datetime] = Field(default=None, description="创建时间")
    updated_at: Optional[datetime] = Field(default=None, description="更新时间")
    last_login: Optional[datetime] = Field(default=None, description="最后登录时间")
    last_login_ip: Optional[str] = Field(default=None, description="最后登录IP")
    failed_login_count: int = Field(default=0, description="连续失败登录次数")
    locked_until: Optional[datetime] = Field(default=None, description="锁定截止时间")

    model_config = {"from_attributes": True}


class UserDetailResponse(UserResponse):
    """用户详情响应（含更多信息）"""
    bio: Optional[str] = Field(default=None, description="个人简介")
    timezone: str = Field(default="Asia/Shanghai", description="时区")
    language: str = Field(default="zh-CN", description="语言")
    theme: str = Field(default="auto", description="主题: light/dark/auto")
    preferences: Dict[str, Any] = Field(default_factory=dict, description="用户偏好设置")


# ═══════════════════════════════════════════════════════
# 用户列表
# ═══════════════════════════════════════════════════════

class UserListItem(BaseModel):
    """用户列表项"""
    id: int = Field(description="用户ID")
    username: str = Field(description="用户名")
    nickname: str = Field(description="昵称")
    email: Optional[str] = Field(default=None, description="邮箱")
    role: str = Field(description="角色")
    status: str = Field(description="状态")
    avatar: Optional[str] = Field(default=None, description="头像URL")
    created_at: Optional[datetime] = Field(default=None, description="创建时间")
    last_login: Optional[datetime] = Field(default=None, description="最后登录时间")


class UserListResponse(BaseModel):
    """用户列表响应"""
    items: List[UserListItem] = Field(default_factory=list, description="用户列表")
    total: int = Field(default=0, description="总记录数")
    page: int = Field(default=1, description="当前页码")
    page_size: int = Field(default=20, description="每页条数")
    total_pages: int = Field(default=0, description="总页数")


# ═══════════════════════════════════════════════════════
# 用户偏好设置
# ═══════════════════════════════════════════════════════

class UserPreferencesUpdate(BaseModel):
    """更新用户偏好设置"""
    theme: Optional[str] = Field(default=None, description="主题")
    language: Optional[str] = Field(default=None, description="语言")
    timezone: Optional[str] = Field(default=None, description="时区")
    notifications: Optional[Dict[str, bool]] = Field(default=None, description="通知开关")
    ui_settings: Optional[Dict[str, Any]] = Field(default=None, description="界面设置")


class UserPreferencesResponse(BaseModel):
    """用户偏好设置响应"""
    theme: str = Field(default="auto", description="主题")
    language: str = Field(default="zh-CN", description="语言")
    timezone: str = Field(default="Asia/Shanghai", description="时区")
    notifications: Dict[str, bool] = Field(default_factory=dict, description="通知开关")
    ui_settings: Dict[str, Any] = Field(default_factory=dict, description="界面设置")


# ═══════════════════════════════════════════════════════
# 用户状态管理
# ═══════════════════════════════════════════════════════

class UserStatusUpdate(BaseModel):
    """用户状态更新"""
    status: str = Field(..., description="目标状态: active/disabled/locked")
    reason: Optional[str] = Field(default=None, description="操作原因")


class UserRoleUpdate(BaseModel):
    """用户角色更新"""
    role: str = Field(..., description="目标角色")


class BatchUserOperationRequest(BaseModel):
    """批量操作用户请求"""
    user_ids: List[int] = Field(..., min_length=1, description="用户ID列表")
    operation: str = Field(..., description="操作类型: enable/disable/lock/unlock/delete")
    reason: Optional[str] = Field(default=None, description="操作原因")


# ═══════════════════════════════════════════════════════
# 当前用户（个人中心）
# ═══════════════════════════════════════════════════════

class CurrentUserResponse(UserDetailResponse):
    """当前登录用户信息"""
    permissions: List[str] = Field(default_factory=list, description="权限列表")
    is_admin: bool = Field(default=False, description="是否为管理员")


class ProfileUpdate(BaseModel):
    """更新个人资料"""
    nickname: Optional[str] = Field(default=None, max_length=50, description="昵称")
    email: Optional[str] = Field(default=None, max_length=100, description="邮箱")
    phone: Optional[str] = Field(default=None, max_length=20, description="手机号")
    bio: Optional[str] = Field(default=None, description="个人简介")
    avatar: Optional[str] = Field(default=None, description="头像URL")
