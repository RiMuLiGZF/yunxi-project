"""
云汐 M12 安全盾 - IP 控制相关 Pydantic 模型
定义 IP 黑白名单管理接口的请求和响应数据模型
"""

import ipaddress
import re
from typing import Optional, List, Dict, Any
from datetime import datetime
from pydantic import BaseModel, Field, IPvAnyAddress, field_validator


# ===========================================================================
# 安全校验工具
# ===========================================================================

# 路径遍历攻击特征模式
_PATH_TRAVERSAL_PATTERN = re.compile(
    r'(\.\./|\.\.\\|%2e%2e%2f|%2e%2e/|\.\.%2f|%2e\.%2f|%2e\.%5c)',
    re.IGNORECASE,
)


def _validate_ip_or_cidr(value: str) -> str:
    """校验 IP 地址或 CIDR 段格式是否合法

    支持 IPv4、IPv6 单地址和 CIDR 段格式。

    Args:
        value: 待校验的 IP 地址或 CIDR 字符串

    Returns:
        校验通过的原始值

    Raises:
        ValueError: 格式不合法时抛出
    """
    if not value:
        raise ValueError("IP 地址不能为空")

    value = value.strip()

    # 检查是否为 CIDR 格式
    if "/" in value:
        try:
            ipaddress.ip_network(value, strict=False)
            return value
        except ValueError:
            raise ValueError(f"无效的 CIDR 地址格式: {value}")
    else:
        # 单 IP 地址
        try:
            ipaddress.ip_address(value)
            return value
        except ValueError:
            raise ValueError(f"无效的 IP 地址格式: {value}")


def _validate_no_path_traversal(value: str, field_name: str) -> str:
    """校验字段中不包含路径遍历字符"""
    if value and _PATH_TRAVERSAL_PATTERN.search(value):
        raise ValueError(
            f"{field_name} 包含非法的路径遍历字符，不允许使用 ../ 等特殊序列"
        )
    return value


# ===========================================================================
# IP 黑名单模型
# ===========================================================================

class IpBlacklistBase(BaseModel):
    """IP 黑名单基础模型"""

    ip_address: str = Field(..., max_length=50, description="IP 地址或 CIDR 段")
    ip_type: str = Field(default="single", max_length=20, description="IP 类型：single/cidr/range")
    reason: str = Field(default="", max_length=500, description="封禁原因（最多500字符）")
    severity: str = Field(default="medium", max_length=20, description="威胁级别")
    source: str = Field(default="manual", max_length=100, description="来源")
    expires_at: Optional[datetime] = Field(default=None, description="过期时间（NULL=永久）")

    @field_validator("ip_address")
    @classmethod
    def validate_ip_address(cls, v: str) -> str:
        """校验 IP 地址格式"""
        return _validate_ip_or_cidr(v)

    @field_validator("reason")
    @classmethod
    def validate_reason(cls, v: str) -> str:
        """校验封禁原因：禁止路径遍历"""
        if v:
            _validate_no_path_traversal(v, "封禁原因")
        return v

    @field_validator("ip_type")
    @classmethod
    def validate_ip_type(cls, v: str) -> str:
        """校验 IP 类型值"""
        allowed_types = {"single", "cidr", "range"}
        if v not in allowed_types:
            raise ValueError(f"ip_type 必须是以下值之一: {allowed_types}")
        return v

    @field_validator("severity")
    @classmethod
    def validate_severity(cls, v: str) -> str:
        """校验威胁级别"""
        allowed = {"low", "medium", "high", "critical", "info"}
        if v not in allowed:
            raise ValueError(f"severity 必须是以下值之一: {allowed}")
        return v


class IpBlacklistCreate(IpBlacklistBase):
    """添加 IP 黑名单请求"""
    pass


class IpBlacklistUpdate(BaseModel):
    """更新 IP 黑名单请求"""

    reason: Optional[str] = Field(default=None, max_length=500, description="封禁原因")
    severity: Optional[str] = Field(default=None, max_length=20, description="威胁级别")
    expires_at: Optional[datetime] = Field(default=None, description="过期时间")
    is_active: Optional[bool] = Field(default=None, description="是否生效")

    @field_validator("reason")
    @classmethod
    def validate_reason(cls, v: Optional[str]) -> Optional[str]:
        """校验封禁原因"""
        if v is not None:
            _validate_no_path_traversal(v, "封禁原因")
        return v

    @field_validator("severity")
    @classmethod
    def validate_severity(cls, v: Optional[str]) -> Optional[str]:
        """校验威胁级别"""
        if v is not None:
            allowed = {"low", "medium", "high", "critical", "info"}
            if v not in allowed:
                raise ValueError(f"severity 必须是以下值之一: {allowed}")
        return v


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
    reason: str = Field(default="", max_length=500, description="添加原因（最多500字符）")
    source: str = Field(default="manual", max_length=100, description="来源")
    expires_at: Optional[datetime] = Field(default=None, description="过期时间")
    description: str = Field(default="", max_length=500, description="描述说明（最多500字符）")

    @field_validator("ip_address")
    @classmethod
    def validate_ip_address(cls, v: str) -> str:
        """校验 IP 地址格式"""
        return _validate_ip_or_cidr(v)

    @field_validator("reason")
    @classmethod
    def validate_reason(cls, v: str) -> str:
        """校验添加原因：禁止路径遍历"""
        if v:
            _validate_no_path_traversal(v, "添加原因")
        return v

    @field_validator("ip_type")
    @classmethod
    def validate_ip_type(cls, v: str) -> str:
        """校验 IP 类型值"""
        allowed_types = {"single", "cidr", "range"}
        if v not in allowed_types:
            raise ValueError(f"ip_type 必须是以下值之一: {allowed_types}")
        return v

    @field_validator("description")
    @classmethod
    def validate_description(cls, v: str) -> str:
        """校验描述：禁止路径遍历"""
        if v:
            _validate_no_path_traversal(v, "描述")
        return v


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

    @field_validator("ip_address")
    @classmethod
    def validate_ip_address(cls, v: str) -> str:
        """校验 IP 地址格式"""
        return _validate_ip_or_cidr(v)


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
