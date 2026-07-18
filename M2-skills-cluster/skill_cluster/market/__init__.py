from __future__ import annotations

"""技能市场模块.

提供技能的上架、浏览、搜索、安装、卸载、评分等市场功能。
对外导出 MarketRegistry / SkillMarket / market_router / market_v2_router。

【P1 技能体系完善】新增 SkillMarket 高级服务层，提供：
- 多维度搜索过滤（价格、官方、认证、评分）
- 用户维度安装管理
- 评论点赞系统
- 分类元数据管理
- 技能上架信息更新

所有新增功能为纯增量，不影响原有 MarketRegistry 和 market_router。
"""

from skill_cluster.market.registry import MarketRegistry
from skill_cluster.market.router import market_router
from skill_cluster.market.skill_market import (
    CategoryInfo,
    InstalledSkill,
    SearchFilters,
    SkillListing,
    SkillMarket,
    SkillRatingStats,
    SkillReview,
)

__all__ = [
    "MarketRegistry",
    "SkillMarket",
    "SkillListing",
    "SkillReview",
    "SkillRatingStats",
    "InstalledSkill",
    "CategoryInfo",
    "SearchFilters",
    "market_router",
]
