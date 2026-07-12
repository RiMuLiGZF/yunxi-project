"""
云汐 M12 安全盾 - IP 控制相关 Pydantic 模型
定义 IP 黑白名单管理接口的请求和响应数据模型
"""

from typing import Optional, List, Dict, Any
from datetime import datetime
from pydantic import BaseModel, Field, IPvAnyAddress


# ===========================================================================
# IP 黑名单模型
# ===========================================================================

class IpBlacklistBase(BaseModel):
    """IP 黑名单基础模型"""

    ip_address: str = Field(..., max_length=50, description="IP 地址或 CIDR 段")
    ip_type: str = Field(default="single", max_length=20, description="IP 类型：single/cidr/range")
    reason: str = Field(default="", description="封禁原因")
    severity: str = Field(default="medium", max_length=20, description="威胁级别")
    source: str = Field(default="manual", max_length=100, description="来源")
    expires_at: Optional[datetime] = Field(default=None, description="过期时间（NULL=永久）")


class IpBlacklistCreate(IpBlacklistBase):
    """添加 IP 黑名单请求"""
    pass


class IpBlacklistUpdate(BaseModel):
    """更新 IP 黑名单请求"""

    reason: Optional[str] = Field(default=None, description="封禁原因")
    severity: Optional[str] = Field(default=None, max_length=20, description="威胁级别")
    expires_at: Optional[datetime] = Field(default=None, description="过期时间")
    is_active: Optional[bool] = Field(default=None, description="是否生效")


class IpBlacklistResponse(BaseModel):
    """IP 黑名单响应"""

    id: int = Field(..., description="记录ID")
    ip_address: str = Field(..., description="IP 地址或 CIDR 段")
    ip_type: str = Field(default="single", description="IP 类型")
    reason: str = Field(default="", description="封禁原因")
    severity: str = Field(default="medium", description="威胁级别")
    source: str = Field(default="manual", description="来源")
    banned_by: str = Field(default="system", description="封禁操作人")
    banned_at: Optional[datetime] = Field(default=None, description="封禁时间")
    expires_at: Optional[datetime] = Field(default=None, description="过期时间")
    is_active: bool = Field(default=True, description="是否生效")
    hit_count: int = Field(default=0, description="命中次数")
    last_hit_at: Optional[datetime] = Field(default=None, description="最后命中时间")
    extra_data: Dict[str, Any] = Field(default_factory=dict, description="附加数据")

    class Config:
        """Pydantic 配置"""
        from_attributes = True


# ===========================================================================
# IP 白名单模型
# ===========================================================================

class IpWhitelistBase(BaseModel):
    """IP 白名单基础模型"""

    ip_address: str = Field(..., max_length=50, description="IP 地址或 CIDR 段")
    ip_type: str = Field(default="single", max_length=20, description="IP 类型")
    reason: str = Field(default="", description="添加原因")
    source: str = Field(default="manual", max_length=100, description="来源")
    expires_at: Optional[datetime] = Field(default=None, description="过期时间")
    description: str = Field(default="", description="描述说明")


class IpWhitelistCreate(IpWhitelistBase):
    """添加 IP 白名单请求"""
    pass


class IpWhitelistResponse(BaseModel):
    """IP 白名单响应"""

    id: int = Field(..., description="记录ID")
    ip_address: str = Field(..., description="IP 地址或 CIDR 段")
    ip_type: str = Field(default="single", description="IP 类型")
    reason: str = Field(default="", description="添加原因")
    source: str = Field(default="manual", description="来源")
    added_by: str = Field(default="system", description="添加人")
    added_at: Optional[datetime] = Field(default=None, description="添加时间")
    expires_at: Optional[datetime] = Field(default=None, description="过期时间")
    is_active: bool = Field(default=True, description="是否生效")
    description: str = Field(default="", description="描述说明")

    class Config:
        """Pydantic 配置"""
        from_attributes = True


# ===========================================================================
# IP 检测模型
# ===========================================================================

class IpCheckRequest(BaseModel):
    """IP 检测请求"""

    ip_address: str = Field(..., description="要检测的 IP 地址")


class IpCheckResponse(BaseModel):
    """IP 检测结果响应"""

    ip_address: str = Field(..., description="检测的 IP 地址")
    is_blacklisted: bool = Field(default=False, description="是否在黑名单中")
    is_whitelisted: bool = Field(default=False, description="是否在白名单中")
    blacklist_info: Optional[IpBlacklistResponse] = Field(default=None, description="黑名单信息")
    whitelist_info: Optional[IpWhitelistResponse] = Field(default=None, description="白名单信息")
    risk_level: str = Field(default="low", description="风险级别")
    recommendation: str = Field(default="allow", description="建议动作：allow/block/challenge")


# ===========================================================================
# IP 统计模型
# ===========================================================================

class IpStatsResponse(BaseModel):
    """IP 统计响应"""

    blacklist_count: int = Field(default=0, description="黑名单总数")
    whitelist_count: int = Field(default=0, description="白名单总数")
    active_blacklist: int = Field(default=0, description="生效的黑名单数")
    active_whitelist: int = Field(default=0, description="生效的白名单数")
    auto_banned_today: int = Field(default=0, description="今日自动封禁数")
    top_blocked_ips: List[Dict[str, Any]] = Field(default_factory=list, description="被拦截最多的 IP")
