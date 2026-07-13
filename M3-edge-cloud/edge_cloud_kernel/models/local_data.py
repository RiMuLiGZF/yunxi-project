"""本地数据层模型.

定义本地数据管理和冲突解决相关的数据模型。
整合自原 local_data/conflict_resolver.py 中的 Pydantic 模型。
"""

from __future__ import annotations

from pydantic import Field

from edge_cloud_kernel.models.base import EdgeCloudBaseModel


class VersionVector(EdgeCloudBaseModel):
    """版本向量 -- CouchDB风格的多设备冲突检测.

    每个设备维护自己的单调递增版本号。
    例：{"desktop_001": 5, "laptop_002": 3, "phone_003": 1}
    """

    vectors: dict[str, int] = Field(default_factory=dict)

    def increment(self, device_id: str) -> None:
        """递增指定设备的版本号."""
        self.vectors[device_id] = self.vectors.get(device_id, 0) + 1

    def merge(self, other: "VersionVector") -> "VersionVector":
        """合并两个版本向量（取每个设备ID的最大值）."""
        merged: dict[str, int] = {}
        all_keys = set(self.vectors) | set(other.vectors)
        for k in all_keys:
            merged[k] = max(self.vectors.get(k, 0), other.vectors.get(k, 0))
        return VersionVector(vectors=merged)

    def dominates(self, other: "VersionVector") -> bool:
        """判断self是否支配other（所有维度>=且至少一个>）."""
        if not other.vectors:
            return bool(self.vectors)
        for k, v in other.vectors.items():
            if self.vectors.get(k, 0) < v:
                return False
        return any(self.vectors.get(k, 0) > v for k, v in other.vectors.items())

    def is_concurrent(self, other: "VersionVector") -> bool:
        """判断两个版本向量是否并发（互不支配）."""
        return not self.dominates(other) and not other.dominates(self)

    @property
    def summary_version(self) -> int:
        """摘要版本号（所有维度之和）."""
        return sum(self.vectors.values())
