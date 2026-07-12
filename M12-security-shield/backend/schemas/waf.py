"""
云汐 M12 安全盾 - WAF 相关 Pydantic 模型
定义 WAF 防护墙接口的请求和响应数据模型
"""

from typing import Optional, List, Dict, Any
from datetime import datetime
from pydantic import BaseModel, Field


# ===========================================================================
# WAF 规则模型
# ===========================================================================

class WafRuleBase(BaseModel):
    """WAF 规则基础模型"""

    rule_name: str = Field(..., max_length=200, description="规则名称")
    rule_type: str = Field(default="custom", max_length=50, description="规则类型")
    category: str = Field(default="", max_length=50, description="规则分类")
    pattern: str = Field(..., description="匹配规则（正则表达式）")
    match_target: str = Field(default="query", max_length=50, description="匹配目标")
    severity: str = Field(default="medium", max_length=20, description="严重级别")
    action: str = Field(default="block", max_length=20, description="触发动作")
    description: str = Field(default="", description="规则描述")
    is_active: bool = Field(default=True, description="是否启用")


class WafRuleCreate(WafRuleBase):
    """创建 WAF 规则请求"""
    pass


class WafRuleUpdate(BaseModel):
    """更新 WAF 规则请求"""

    rule_name: Optional[str] = Field(default=None, max_length=200, description="规则名称")
    rule_type: Optional[str] = Field(default=None, max_length=50, description="规则类型")
    category: Optional[str] = Field(default=None, max_length=50, description="规则分类")
    pattern: Optional[str] = Field(default=None, description="匹配规则")
    match_target: Optional[str] = Field(default=None, max_length=50, description="匹配目标")
    severity: Optional[str] = Field(default=None, max_length=20, description="严重级别")
    action: Optional[str] = Field(default=None, max_length=20, description="触发动作")
    description: Optional[str] = Field(default=None, description="规则描述")
    is_active: Optional[bool] = Field(default=None, description="是否启用")


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

    method: str = Field(default="GET", description="请求方法")
    path: str = Field(..., description="请求路径")
    query: str = Field(default="", description="查询字符串")
    body: str = Field(default="", description="请求体内容")
    headers: Dict[str, str] = Field(default_factory=dict, description="请求头")
    client_ip: str = Field(default="", description="客户端 IP")


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
