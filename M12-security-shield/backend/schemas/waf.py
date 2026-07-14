"""
云汐 M12 安全盾 - WAF 相关 Pydantic 模型
定义 WAF 防护墙接口的请求和响应数据模型
"""

import re
try:
    from .common import validate_no_path_traversal
except ImportError:
    from common import validate_no_path_traversal
from typing import Optional, List, Dict, Any
from datetime import datetime
from pydantic import BaseModel, Field, field_validator


# ===========================================================================
# 安全校验工具
# ===========================================================================

# ===========================================================================
# WAF 规则模型
# ===========================================================================

class WafRuleBase(BaseModel):
    """WAF 规则基础模型"""

    rule_name: str = Field(..., min_length=1, max_length=100, description="规则名称（1-100字符）")
    rule_type: str = Field(default="custom", max_length=50, description="规则类型")
    category: str = Field(default="", max_length=50, description="规则分类")
    pattern: str = Field(..., max_length=2000, description="匹配规则（正则表达式，最多2000字符）")
    match_target: str = Field(default="query", max_length=50, description="匹配目标")
    severity: str = Field(default="medium", max_length=20, description="严重级别")
    action: str = Field(default="block", max_length=20, description="触发动作")
    description: str = Field(default="", max_length=500, description="规则描述（最多500字符）")
    is_active: bool = Field(default=True, description="是否启用")

    @field_validator("rule_name")
    @classmethod
    def validate_rule_name(cls, v: str) -> str:
        """校验规则名称：禁止路径遍历和危险字符"""
        v = v.strip()
        if not v:
            raise ValueError("规则名称不能为空")
        validate_no_path_traversal(v)
        return v

    @field_validator("rule_type")
    @classmethod
    def validate_rule_type(cls, v: str) -> str:
        """校验规则类型：禁止路径遍历"""
        if v:
            validate_no_path_traversal(v)
        return v

    @field_validator("category")
    @classmethod
    def validate_category(cls, v: str) -> str:
        """校验规则分类：禁止路径遍历"""
        if v:
            validate_no_path_traversal(v)
        return v

    @field_validator("match_target")
    @classmethod
    def validate_match_target(cls, v: str) -> str:
        """校验匹配目标：只能是预定义的值"""
        allowed = {"query", "body", "header", "path", "all", "cookie", "url"}
        if v not in allowed:
            raise ValueError(f"match_target 必须是以下值之一: {allowed}")
        return v

    @field_validator("severity")
    @classmethod
    def validate_severity(cls, v: str) -> str:
        """校验严重级别"""
        allowed = {"info", "low", "medium", "high", "critical"}
        if v not in allowed:
            raise ValueError(f"severity 必须是以下值之一: {allowed}")
        return v

    @field_validator("action")
    @classmethod
    def validate_action(cls, v: str) -> str:
        """校验触发动作"""
        allowed = {"block", "log", "challenge", "allow"}
        if v not in allowed:
            raise ValueError(f"action 必须是以下值之一: {allowed}")
        return v

    @field_validator("description")
    @classmethod
    def validate_description(cls, v: str) -> str:
        """校验描述：禁止路径遍历"""
        if v:
            validate_no_path_traversal(v)
        return v

    @field_validator("pattern")
    @classmethod
    def validate_pattern(cls, v: str) -> str:
        """校验正则表达式模式：验证是否为有效正则"""
        if not v:
            raise ValueError("匹配规则（pattern）不能为空")
        try:
            re.compile(v)
        except re.error as e:
            raise ValueError(f"无效的正则表达式: {e}")
        return v


class WafRuleCreate(WafRuleBase):
    """创建 WAF 规则请求"""
    pass


class WafRuleUpdate(BaseModel):
    """更新 WAF 规则请求"""

    rule_name: Optional[str] = Field(default=None, min_length=1, max_length=100, description="规则名称")
    rule_type: Optional[str] = Field(default=None, max_length=50, description="规则类型")
    category: Optional[str] = Field(default=None, max_length=50, description="规则分类")
    pattern: Optional[str] = Field(default=None, max_length=2000, description="匹配规则")
    match_target: Optional[str] = Field(default=None, max_length=50, description="匹配目标")
    severity: Optional[str] = Field(default=None, max_length=20, description="严重级别")
    action: Optional[str] = Field(default=None, max_length=20, description="触发动作")
    description: Optional[str] = Field(default=None, max_length=500, description="规则描述")
    is_active: Optional[bool] = Field(default=None, description="是否启用")

    @field_validator("rule_name")
    @classmethod
    def validate_rule_name(cls, v: Optional[str]) -> Optional[str]:
        """校验规则名称"""
        if v is not None:
            v = v.strip()
            if not v:
                raise ValueError("规则名称不能为空")
            validate_no_path_traversal(v)
        return v

    @field_validator("rule_type")
    @classmethod
    def validate_rule_type(cls, v: Optional[str]) -> Optional[str]:
        """校验规则类型"""
        if v is not None:
            validate_no_path_traversal(v)
        return v

    @field_validator("category")
    @classmethod
    def validate_category(cls, v: Optional[str]) -> Optional[str]:
        """校验规则分类"""
        if v is not None:
            validate_no_path_traversal(v)
        return v

    @field_validator("pattern")
    @classmethod
    def validate_pattern(cls, v: Optional[str]) -> Optional[str]:
        """校验正则表达式模式"""
        if v is not None:
            if not v:
                raise ValueError("匹配规则（pattern）不能为空")
            try:
                re.compile(v)
            except re.error as e:
                raise ValueError(f"无效的正则表达式: {e}")
        return v

    @field_validator("match_target")
    @classmethod
    def validate_match_target(cls, v: Optional[str]) -> Optional[str]:
        """校验匹配目标"""
        if v is not None:
            allowed = {"query", "body", "header", "path", "all", "cookie", "url"}
            if v not in allowed:
                raise ValueError(f"match_target 必须是以下值之一: {allowed}")
        return v

    @field_validator("severity")
    @classmethod
    def validate_severity(cls, v: Optional[str]) -> Optional[str]:
        """校验严重级别"""
        if v is not None:
            allowed = {"info", "low", "medium", "high", "critical"}
            if v not in allowed:
                raise ValueError(f"severity 必须是以下值之一: {allowed}")
        return v

    @field_validator("action")
    @classmethod
    def validate_action(cls, v: Optional[str]) -> Optional[str]:
        """校验触发动作"""
        if v is not None:
            allowed = {"block", "log", "challenge", "allow"}
            if v not in allowed:
                raise ValueError(f"action 必须是以下值之一: {allowed}")
        return v

    @field_validator("description")
    @classmethod
    def validate_description(cls, v: Optional[str]) -> Optional[str]:
        """校验描述"""
        if v is not None:
            validate_no_path_traversal(v)
        return v


class WafRuleResponse(BaseModel):
    """WAF 规则响应"""

    id: int = Field(..., description="规则ID")
    rule_name: str = Field(..., description="规则名称")
    rule_type: str = Field(..., description="规则类型")
    category: str = Field(default="", description="规则分类")
    pattern: str = Field(..., description="匹配规则")
    match_target: str = Field(..., description="匹配目标")
    severity: str = Field(..., description="严重级别")
    action: str = Field(..., description="触发动作")
    description: str = Field(default="", description="规则描述")
    is_builtin: bool = Field(default=False, description="是否内置规则")
    is_active: bool = Field(default=True, description="是否启用")
    hit_count: int = Field(default=0, description="命中次数")
    last_hit_at: Optional[datetime] = Field(default=None, description="最后命中时间")
    created_by: str = Field(default="system", description="创建人")
    created_at: Optional[datetime] = Field(default=None, description="创建时间")
    updated_at: Optional[datetime] = Field(default=None, description="更新时间")

    class Config:
        """Pydantic 配置"""
        from_attributes = True


# ===========================================================================
# WAF 状态模型
# ===========================================================================

class WafStatusResponse(BaseModel):
    """WAF 状态响应"""

    enabled: bool = Field(default=True, description="WAF 是否启用")
    total_rules: int = Field(default=0, description="规则总数")
    active_rules: int = Field(default=0, description="启用的规则数")
    builtin_rules: int = Field(default=0, description="内置规则数")
    custom_rules: int = Field(default=0, description="自定义规则数")
    rules_by_type: Dict[str, int] = Field(default_factory=dict, description="按类型统计的规则数")
    today_blocks: int = Field(default=0, description="今日拦截次数")
    total_blocks: int = Field(default=0, description="累计拦截次数")


# ===========================================================================
# WAF 检测模型
# ===========================================================================

class WafCheckRequest(BaseModel):
    """WAF 检测请求"""

    method: str = Field(default="GET", max_length=20, description="请求方法")
    path: str = Field(..., max_length=2000, description="请求路径（最多2000字符）")
    query: str = Field(default="", max_length=4000, description="查询字符串（最多4000字符）")
    body: str = Field(default="", max_length=100000, description="请求体内容（最多100KB）")
    headers: Dict[str, str] = Field(default_factory=dict, description="请求头")
    client_ip: str = Field(default="", max_length=50, description="客户端 IP")

    @field_validator("method")
    @classmethod
    def validate_method(cls, v: str) -> str:
        """校验请求方法：必须是标准 HTTP 方法"""
        allowed_methods = {"GET", "POST", "PUT", "DELETE", "PATCH", "HEAD", "OPTIONS", "CONNECT", "TRACE"}
        v_upper = v.upper()
        if v_upper not in allowed_methods:
            raise ValueError(f"不支持的 HTTP 方法: {v}")
        return v_upper

    @field_validator("path")
    @classmethod
    def validate_path(cls, v: str) -> str:
        """校验请求路径：必须以 / 开头"""
        if not v:
            raise ValueError("请求路径不能为空")
        if not v.startswith("/"):
            raise ValueError("请求路径必须以 / 开头")
        return v

    @field_validator("client_ip")
    @classmethod
    def validate_client_ip(cls, v: str) -> str:
        """校验客户端 IP 格式（可选字段）"""
        if v:
            import ipaddress
            try:
                ipaddress.ip_address(v)
            except ValueError:
                raise ValueError(f"无效的 IP 地址格式: {v}")
        return v


class WafCheckResponse(BaseModel):
    """WAF 检测结果响应"""

    passed: bool = Field(..., description="是否通过检测")
    rule_name: str = Field(default="", description="触发的规则名称")
    rule_type: str = Field(default="", description="触发的规则类型")
    severity: str = Field(default="", description="严重级别")
    action: str = Field(default="", description="触发动作")
    matched_content: str = Field(default="", description="匹配到的内容")
    match_target: str = Field(default="", description="匹配的目标位置")
    details: Dict[str, Any] = Field(default_factory=dict, description="详细信息")


# ===========================================================================
# WAF 规则统计模型
# ===========================================================================

class WafStatsResponse(BaseModel):
    """WAF 统计响应"""

    total_requests: int = Field(default=0, description="总请求数")
    blocked_requests: int = Field(default=0, description="被拦截请求数")
    passed_requests: int = Field(default=0, description="通过请求数")
    block_rate: float = Field(default=0.0, description="拦截率(%)")
    top_rules: List[Dict[str, Any]] = Field(default_factory=list, description="命中最多的规则")
    top_attack_types: List[Dict[str, Any]] = Field(default_factory=list, description="攻击类型分布")
    trend_data: List[Dict[str, Any]] = Field(default_factory=list, description="趋势数据")


# ===========================================================================
# 网关 WAF 检测模型（M8 网关专用）
# ===========================================================================

class GatewayWafCheckRequest(BaseModel):
    """网关 WAF 检测请求（M8 网关调用）

    专门为网关接入设计的高性能检测接口，
    字段精简，响应格式符合网关期望。
    """

    method: str = Field(default="GET", max_length=20, description="HTTP 请求方法")
    path: str = Field(..., max_length=2000, description="请求路径")
    headers: Dict[str, str] = Field(default_factory=dict, description="请求头")
    body: str = Field(default="", max_length=100000, description="请求体（最多100KB）")
    client_ip: str = Field(default="", max_length=50, description="客户端 IP")
    user_agent: str = Field(default="", max_length=500, description="用户代理")

    @field_validator("method")
    @classmethod
    def validate_method(cls, v: str) -> str:
        allowed = {"GET", "POST", "PUT", "DELETE", "PATCH", "HEAD", "OPTIONS", "CONNECT", "TRACE"}
        v_upper = v.upper()
        if v_upper not in allowed:
            raise ValueError(f"不支持的 HTTP 方法: {v}")
        return v_upper

    @field_validator("path")
    @classmethod
    def validate_path(cls, v: str) -> str:
        if not v:
            raise ValueError("请求路径不能为空")
        if not v.startswith("/"):
            raise ValueError("请求路径必须以 / 开头")
        return v

    @field_validator("client_ip")
    @classmethod
    def validate_client_ip(cls, v: str) -> str:
        if v:
            import ipaddress
            try:
                ipaddress.ip_address(v)
            except ValueError:
                raise ValueError(f"无效的 IP 地址格式: {v}")
        return v


class GatewayWafCheckResponse(BaseModel):
    """网关 WAF 检测响应

    精简格式，方便网关快速判断：
    - blocked: 是否拦截
    - reason: 拦截原因
    - rule_id: 触发的规则 ID
    - risk_level: 风险级别
    """

    blocked: bool = Field(default=False, description="是否拦截该请求")
    reason: str = Field(default="", description="拦截/检测原因")
    rule_id: str = Field(default="", description="触发的规则 ID/名称")
    risk_level: str = Field(default="low", description="风险级别：low/medium/high/critical")
    detection_time_ms: float = Field(default=0.0, description="检测耗时（毫秒）")


class GatewayWafBatchRequest(BaseModel):
    """网关 WAF 批量检测请求"""

    requests: List[GatewayWafCheckRequest] = Field(..., min_length=1, max_length=100, description="批量检测请求列表（1-100个）")


class GatewayWafBatchResponse(BaseModel):
    """网关 WAF 批量检测响应"""

    results: List[GatewayWafCheckResponse] = Field(default_factory=list, description="检测结果列表（与请求顺序对应）")
    total_count: int = Field(default=0, description="总检测数")
    blocked_count: int = Field(default=0, description="拦截数")
    total_time_ms: float = Field(default=0.0, description="总耗时（毫秒）")
