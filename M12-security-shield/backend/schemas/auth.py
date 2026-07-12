"""
云汐 M12 安全盾 - 鉴权相关 Pydantic 模型
定义认证和 API 密钥管理接口的请求和响应数据模型
"""

from typing import Optional, List
from datetime import datetime
from pydantic import BaseModel, Field, EmailStr


# ===========================================================================
# 登录模型
# ===========================================================================

class LoginRequest(BaseModel):
    """登录请求"""

    username: str = Field(..., min_length=3, max_length=100, description="用户名")
    password: str = Field(..., min_length=6, max_length=200, description="密码")
    remember_me: bool = Field(default=False, description="是否记住我（延长过期时间）")


class LoginResponse(BaseModel):
    """登录响应"""

    access_token: str = Field(..., description="访问令牌")
    refresh_token: str = Field(..., description="刷新令牌")
    token_type: str = Field(default="bearer", description="令牌类型")
    expires_in: int = Field(default=86400, description="过期时间（秒）")
    user: dict = Field(default_factory=dict, description="用户信息")


class TokenRefreshRequest(BaseModel):
    """刷新 Token 请求"""

    refresh_token: str = Field(..., description="刷新令牌")


class TokenRefreshResponse(BaseModel):
    """刷新 Token 响应"""

    access_token: str = Field(..., description="新的访问令牌")
    refresh_token: str = Field(..., description="新的刷新令牌")
    token_type: str = Field(default="bearer", description="令牌类型")
    expires_in: int = Field(default=86400, description="过期时间（秒）")


class LogoutRequest(BaseModel):
    """登出请求"""

    refresh_token: Optional[str] = Field(default=None, description="刷新令牌（可选）")


# ===========================================================================
# API 密钥模型
# ===========================================================================

class ApiKeyBase(BaseModel):
    """API 密钥基础模型"""

    key_name: str = Field(..., max_length=200, description="密钥名称")
    owner: str = Field(default="", max_length=200, description="所有者")
    roles: List[str] = Field(default_factory=list, description="角色列表")
    scopes: List[str] = Field(default_factory=list, description="权限范围列表")
    rate_limit: int = Field(default=0, ge=0, description="自定义速率限制（0=默认）")
    expires_at: Optional[datetime] = Field(default=None, description="过期时间")
    description: str = Field(default="", description="描述说明")


class ApiKeyCreate(ApiKeyBase):
    """创建 API 密钥请求"""
    pass


class ApiKeyUpdate(BaseModel):
    """更新 API 密钥请求"""

    key_name: Optional[str] = Field(default=None, max_length=200, description="密钥名称")
    owner: Optional[str] = Field(default=None, max_length=200, description="所有者")
    roles: Optional[List[str]] = Field(default=None, description="角色列表")
    scopes: Optional[List[str]] = Field(default=None, description="权限范围列表")
    rate_limit: Optional[int] = Field(default=None, ge=0, description="自定义速率限制")
    expires_at: Optional[datetime] = Field(default=None, description="过期时间")
    description: Optional[str] = Field(default=None, description="描述说明")
    is_active: Optional[bool] = Field(default=None, description="是否启用")


class ApiKeyResponse(BaseModel):
    """API 密钥响应"""

    id: int = Field(..., description="密钥ID")
    key_name: str = Field(..., description="密钥名称")
    key_prefix: str = Field(default="", description="密钥前缀（展示用）")
    owner: str = Field(default="", description="所有者")
    roles: List[str] = Field(default_factory=list, description="角色列表")
    scopes: List[str] = Field(default_factory=list, description="权限范围列表")
    rate_limit: int = Field(default=0, description="自定义速率限制")
    call_count: int = Field(default=0, description="累计调用次数")
    last_used_at: Optional[datetime] = Field(default=None, description="最后使用时间")
    expires_at: Optional[datetime] = Field(default=None, description="过期时间")
    is_active: bool = Field(default=True, description="是否启用")
    created_by: str = Field(default="system", description="创建人")
    created_at: Optional[datetime] = Field(default=None, description="创建时间")
    description: str = Field(default="", description="描述说明")

    class Config:
        """Pydantic 配置"""
        from_attributes = True


class ApiKeyCreatedResponse(ApiKeyResponse):
    """API 密钥创建响应（包含完整密钥）"""

    api_key: str = Field(..., description="完整 API Key（仅创建时返回一次）")


# ===========================================================================
# 角色模型
# ===========================================================================

class RoleInfo(BaseModel):
    """角色信息"""

    name: str = Field(..., description="角色名称")
    level: int = Field(..., description="角色级别")
    description: str = Field(default="", description="角色描述")
    scopes: List[str] = Field(default_factory=list, description="默认权限范围")
