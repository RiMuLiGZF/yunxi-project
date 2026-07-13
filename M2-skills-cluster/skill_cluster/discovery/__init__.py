"""发现推荐层 - 技能发现、推荐与路由选择.

包含技能发现引擎、智能推荐器、选择策略、懒加载发现器等模块。
"""

from skill_cluster.discovery.engine import (
    CATEGORY_META,
    SCENE_CATEGORY_WEIGHTS,
    SceneType,
    SkillCategory,
    SkillCategoryInfo,
    SkillDiscoveryEngine,
    SkillDiscoveryItem,
    SkillDiscoveryResult,
    TimeContext,
    UserProfile,
)
from skill_cluster.discovery.recommender import (
    SkillRecommendation,
    SkillRecommender,
)
from skill_cluster.discovery.selection import (
    AdaptiveSelection,
    BanditSelection,
    CompositeSelection,
    ISkillSelectionStrategy,
    RoundRobinSelection,
    SelectionContext,
    SelectionResult,
    SelectionStrategyType,
    SkillSelectionOrchestrator,
)
from skill_cluster.discovery.lazy_discoverer import (
    ToolLazyDiscoverer,
    ToolReference,
)
from skill_cluster.discovery.routers.adaptive import (
    AdaptiveRouter,
    SkillMetrics,
)
from skill_cluster.discovery.routers.bandit import (
    BanditArm,
    SkillBanditRouter,
)
from skill_cluster.discovery.routers.edge_cloud import (
    EdgeCloudConfig,
    EdgeCloudOrchestrator,
)

__all__ = [
    # engine
    "CATEGORY_META",
    "SCENE_CATEGORY_WEIGHTS",
    "SceneType",
    "SkillCategory",
    "SkillCategoryInfo",
    "SkillDiscoveryEngine",
    "SkillDiscoveryItem",
    "SkillDiscoveryResult",
    "TimeContext",
    "UserProfile",
    # recommender
    "SkillRecommendation",
    "SkillRecommender",
    # selection
    "AdaptiveSelection",
    "BanditSelection",
    "CompositeSelection",
    "ISkillSelectionStrategy",
    "RoundRobinSelection",
    "SelectionContext",
    "SelectionResult",
    "SelectionStrategyType",
    "SkillSelectionOrchestrator",
    # lazy_discoverer
    "ToolLazyDiscoverer",
    "ToolReference",
    # routers/adaptive
    "AdaptiveRouter",
    "SkillMetrics",
    # routers/bandit
    "BanditArm",
    "SkillBanditRouter",
    # routers/edge_cloud
    "EdgeCloudConfig",
    "EdgeCloudOrchestrator",
]
