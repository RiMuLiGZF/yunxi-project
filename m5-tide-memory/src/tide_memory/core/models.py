"""
潮汐记忆系统核心数据模型
"""

from __future__ import annotations

import uuid
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field, field_validator


class MemoryLayer(str, Enum):
    """记忆层级"""
    L0_BEACH = "l0_beach"      # 沙滩层 - 瞬时记忆
    L1_SHALLOW = "l1_shallow"  # 浅水层 - 短期记忆
    L2_DEEP = "l2_deep"        # 深水层 - 中期记忆
    L3_ABYSS = "l3_abyss"      # 深海层 - 长期记忆


class MemoryDomain(str, Enum):
    """记忆域（三级隔离）"""
    PRIVATE = "private"    # Agent私有域
    SHARED = "shared"      # 协作共享域
    CORE = "core"          # 全局核心域


class ClassificationLevel(str, Enum):
    """密级分类"""
    PUBLIC = "PUBLIC"              # 公开级
    INTERNAL = "INTERNAL"          # 内部级
    CONFIDENTIAL = "CONFIDENTIAL"  # 机密级
    TOP_SECRET = "TOP_SECRET"      # 绝密级


class EmotionState(BaseModel):
    """情绪状态"""
    valence: float = Field(default=0.0, description="效价（正负向），-1到1")
    arousal: float = Field(default=0.0, description="唤醒度，0到1")
    ei_score: float = Field(default=0.0, description="EI情绪指数，0到1")
    dominant_emotion: str = Field(default="neutral", description="主导情绪标签")
    confidence: float = Field(default=0.0, description="置信度")


class MemoryItem(BaseModel):
    """单条记忆"""
    memory_id: str = Field(default_factory=lambda: f"mem_{uuid.uuid4().hex[:16]}")
    content_hash: str = ""  # 内容哈希，用于同步比对（不存原文）
    layer: MemoryLayer = MemoryLayer.L1_SHALLOW
    domain: MemoryDomain = MemoryDomain.PRIVATE
    owner_agent: str = "system"
    
    # 元数据
    created_at: datetime = Field(default_factory=datetime.now)
    updated_at: datetime = Field(default_factory=datetime.now)
    last_accessed_at: Optional[datetime] = None
    access_count: int = 0
    
    # 情绪标记
    emotion: EmotionState = Field(default_factory=EmotionState)
    
    # 质量评分
    quality_score: float = 50.0  # 0-100
    quality_level: str = "normal"  # excellent/good/normal/low/poor
    
    # 保留策略
    retention_days: int = -1  # -1表示永久
    retention_multiplier: float = 1.0
    
    # 标签
    tags: List[str] = Field(default_factory=list)
    metadata: Dict[str, Any] = Field(default_factory=dict)
    
    # 同步
    sync_version: int = 0
    is_dirty: bool = False
    
    # 密级
    classification: ClassificationLevel = ClassificationLevel.TOP_SECRET

    # P2-任务1: 可选原文存储（内存中暂存，落盘时加密）
    original_content: Optional[str] = None  # 原文内容（仅在内存中持有，落盘时加密存入 original_encrypted 列）

    def touch(self) -> None:
        """标记被访问"""
        self.last_accessed_at = datetime.now()
        self.access_count += 1
        self.updated_at = datetime.now()
    
    def promote(self) -> None:
        """提升记忆层级（巩固）"""
        layers = [MemoryLayer.L0_BEACH, MemoryLayer.L1_SHALLOW, 
                   MemoryLayer.L2_DEEP, MemoryLayer.L3_ABYSS]
        current_idx = layers.index(self.layer)
        if current_idx < len(layers) - 1:
            self.layer = layers[current_idx + 1]
            self.updated_at = datetime.now()
            self.is_dirty = True
    
    def demote(self) -> bool:
        """降低层级（遗忘），返回是否被彻底遗忘"""
        layers = [MemoryLayer.L0_BEACH, MemoryLayer.L1_SHALLOW, 
                   MemoryLayer.L2_DEEP, MemoryLayer.L3_ABYSS]
        current_idx = layers.index(self.layer)
        if current_idx > 0:
            self.layer = layers[current_idx - 1]
            self.updated_at = datetime.now()
            self.is_dirty = True
            return False
        return True  # 从L0被遗忘


class MemoryStats(BaseModel):
    """记忆统计"""
    total_memories: int = 0
    layers: Dict[str, Dict] = Field(default_factory=dict)
    by_domain: Dict[str, int] = Field(default_factory=dict)
    to