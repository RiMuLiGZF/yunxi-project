from __future__ import annotations

"""技能市场 - 数据模型.

定义技能包、市场列表项、上架/安装/评分请求、市场统计等 Pydantic 模型。
所有模型均继承自 BaseModel，保持轻量且可独立序列化。
"""

from datetime import datetime
from typing import Any, Dict, List, Optional

import uuid
from pydantic import BaseModel, Field


class SkillPackage(BaseModel):
    """技能包完整信息."""

    package_id: str = Field(
        default_factory=lambda: f"pkg_{uuid.uuid4().hex[:12]}"
    )
    skill_id: str
    name: str
    version: str
    description: str
    author: str
    tags: List[str] = []
    category: str = "general"
    capabilities: List[str] = []
    dependencies: List[str] = []
    permissions: List[str] = []
    checksum: str = ""
    file_size: int = 0
    status: str = "published"  # pending/published/unpublished/blocked
    download_count: int = 0
    rating_avg: float = 0.0
    rating_count: int = 0
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
    entry_point: str = "skill.py"


class MarketListing(BaseModel):
    """市场列表项（简要信息）."""

    package_id: str
    name: str
    description: str
    author: str
    version: str
    tags: List[str] = []
    category: str = "general"
    download_count: int = 0
    rating_avg: float = 0.0
    rating_count: int = 0
    created_at: datetime


class PublishRequest(BaseModel):
    """上架技能请求."""

    skill_id: str
    description: str = ""
    category: str = "general"
    tags: List[str] = []
    is_public: bool = True


class InstallRequest(BaseModel):
    """安装技能请求."""

    target_dir: Optional[str] = None  # 默认 ~/.yunxi/skills/installed/


class RatingRequest(BaseModel):
    """评分请求."""

    rating: int = Field(ge=1, le=5)
    comment: str = ""


class MarketStats(BaseModel):
    """市场统计."""

    total_packages: int = 0
    total_downloads: int = 0
    total_ratings: int = 0
    avg_rating: float = 0.0
    categories: Dict[str, int] = {}
    top_downloaded: List[MarketListing] = []
    top_rated: List[MarketListing] = []
