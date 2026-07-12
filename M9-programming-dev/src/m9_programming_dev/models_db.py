"""M9 开发者工坊 - 数据库模型.

P2-27: 项目索引模型，用于加速项目列表查询。
"""

from __future__ import annotations

from datetime import datetime
from sqlalchemy import Column, Integer, String, Text, DateTime

from .db import Base


class ProjectIndex(Base):
    """项目索引表.

    存储项目元数据索引，加速列表查询和筛选。
    实际项目文件仍在文件系统中。
    """
    __tablename__ = "project_index"

    id = Column(String(64), primary_key=True, index=True, comment="项目ID")
    name = Column(String(200), index=True, default="", comment="项目名称")
    path = Column(String(500), default="", comment="项目路径")
    description = Column(Text, default="", comment="项目描述")
    language = Column(String(50), index=True, default="", comment="主要语言")
    created_at = Column(DateTime, default=datetime.utcnow, index=True, comment="创建时间")
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, index=True, comment="更新时间")
    file_count = Column(Integer, default=0, comment="文件数量")
    size_bytes = Column(Integer, default=0, comment="总大小(字节)")

    def to_dict(self) -> dict:
        """转换为字典."""
        return {
            "id": self.id,
            "name": self.name,
            "path": self.path,
            "description": self.description,
            "language": self.language,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
            "file_count": self.file_count,
            "size_bytes": self.size_bytes,
        }
