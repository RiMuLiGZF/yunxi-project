"""
记忆共享数据模型

定义共享包、列表项、请求与响应的 Pydantic 模型。
所有模型仅包含元数据，不含记忆原文（系统本身只存 content_hash）。
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class SharePackage(BaseModel):
    """记忆共享包

    一个共享包包含若干脱敏后的记忆元数据条目，
    可在共享池中发布、检索、导入与评分。
    """

    share_id: str = Field(
        default_factory=lambda: f"shr_{uuid.uuid4().hex[:12]}",
        description="共享包唯一ID",
    )
    title: str = Field(..., description="共享包标题")
    description: str = Field(default="", description="共享包描述")
    author: str = Field(default="anonymous", description="作者（脱敏后的 agent 标识）")

    # 脱敏后的记忆条目（仅元数据，不含原文）
    items: List[Dict[str, Any]] = Field(default_factory=list)

    # 元数据
    tags: List[str] = Field(default_factory=list)
    domain: str = Field(default="shared", description="共享目标域")
    # 导出后密级最高为 INTERNAL，不能导出 CONFIDENTIAL / TOP_SECRET
    classification_level: str = Field(default="INTERNAL")

    # 统计
    import_count: int = Field(default=0, description="被导入次数")
    rating_avg: float = Field(default=0.0, description="平均评分")
    rating_count: int = Field(default=0, description="评分人数")

    # 校验
    checksum: str = Field(default="", description="整个包的 SHA256 校验和")
    item_count: int = Field(default=0, description="条目数量")

    created_at: datetime = Field(default_factory=datetime.utcnow)


class ShareListing(BaseModel):
    """共享池列表项（不含 items 详情，用于浏览/搜索结果）"""

    share_id: str
    title: str
    description: str
    author: str
    tags: List[str] = Field(default_factory=list)
    item_count: int = 0
    import_count: int = 0
    rating_avg: float = 0.0
    rating_count: int = 0
    created_at: datetime


class ExportRequest(BaseModel):
    """导出记忆请求"""

    memory_ids: List[str] = Field(
        default_factory=list,
        description="指定记忆ID列表，空则导出最近 N 条",
    )
    title: str = Field(default="记忆分享包")
    description: str = Field(default="")
    tags: List[str] = Field(default_factory=list)
    limit: int = Field(default=100, ge=1, le=500, description="当 memory_ids 为空时的数量限制")
    domain: str = Field(default="shared")


class ImportRequest(BaseModel):
    """导入共享记忆请求"""

    share_id: str = Field(..., description="要导入的共享包ID")
    target_domain: str = Field(
        default="shared",
        description="目标域，仅允许 shared（安全约束）",
    )
    overwrite: bool = Field(default=False, description="是否覆盖已存在的记忆")


class RatingRequest(BaseModel):
    """评分请求"""

    rating: int = Field(ge=1, le=5, description="评分 1-5")
    comment: str = Field(default="", description="评语")


class ShareStats(BaseModel):
    """共享池统计"""

    total_packages: int = 0
    total_imports: int = 0
    total_items: int = 0
    avg_rating: float = 0.0
    top_imported: List[ShareListing] = Field(default_factory=list)


# vim: set et ts=4 sw=4:
