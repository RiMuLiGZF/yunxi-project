"""显存报告模型.

定义显存监控报告和显存水位线枚举。
"""

from __future__ import annotations

import time
from enum import Enum

from pydantic import BaseModel, Field


class VRAMLevel(str, Enum):
    """显存水位线级别枚举.

    Attributes:
        SAFE: 安全水位，使用率 < 70%.
        WARNING: 警戒水位，使用率 70%-85%.
        CRITICAL: 危险水位，使用率 > 85%.
    """

    SAFE = "safe"
    WARNING = "warning"
    CRITICAL = "critical"


class VRAMReport(BaseModel):
    """显存监控报告.

    由 VRAMMonitor 定期生成，反映当前 GPU 显存使用状况。

    Attributes:
        total_mb: GPU 总显存（MB）.
        used_mb: 已使用显存（MB）.
        free_mb: 空闲显存（MB）.
        usage_ratio: 使用率 (0.0-1.0).
        level: 水位线级别.
        model_resident_mb: 当前驻留模型占用的显存（MB）.
        kv_cache_mb: KV-Cache 占用的显存（MB）.
        timestamp: 报告生成时间戳.
    """

    total_mb: float = Field(default=0.0, ge=0.0, description="总显存 MB")
    used_mb: float = Field(default=0.0, ge=0.0, description="已用显存 MB")
    free_mb: float = Field(default=0.0, ge=0.0, description="空闲显存 MB")
    usage_ratio: float = Field(default=0.0, ge=0.0, le=1.0, description="使用率")
    level: VRAMLevel = Field(default=VRAMLevel.SAFE, description="水位线级别")
    model_resident_mb: float = Field(default=0.0, ge=0.0, description="模型驻留 MB")
    kv_cache_mb: float = Field(default=0.0, ge=0.0, description="KV-Cache MB")
    timestamp: float = Field(default_factory=time.time, description="报告时间戳")

    @property
    def can_load_model(self, required_mb: float) -> bool:
        """判断是否有足够显存加载指定大小的模型.

        Args:
            required_mb: 模型所需显存（MB）.

        Returns:
            是否可以加载.
        """
        return self.free_mb >= required_mb

    @property
    def should_offload(self) -> bool:
        """判断是否应该卸载模型以释放显存.

        Returns:
            当水位线为 CRITICAL 时返回 True.
        """
        return self.level == VRAMLevel.CRITICAL
