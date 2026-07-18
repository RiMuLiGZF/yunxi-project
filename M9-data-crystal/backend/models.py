"""
云汐 M9 数据水晶 - 数据模型模块

P3 优化：数据采集管道 + 连接器生态
定义连接器、管道、执行记录等数据模型
"""

import sys
import time
import logging
from datetime import datetime
from typing import Optional, List
from pathlib import Path

_backend_dir = Path(__file__).resolve().parent
if str(_backend_dir) not in sys.path:
    sys.path.insert(0, str(_backend_dir))

try:
    from .config import get_config
except ImportError:
    from config import get_config

from sqlalchemy import (
    create_engine,
    Column,
    Integer,
    String,
    Text,
    DateTime,
    Boolean,
    Float,
    JSON,
    Index,
)
from sqlalchemy.orm import declarative_base, sessionmaker
from sqlalchemy.pool import StaticPool

slow_query_logger = logging.getLogger("m9_dc.slow_query")

settings = get_config()
engine = create_engine(
    settings.get_db_url(),
    connect_args={"check_same_thread": False},
    echo=settings.debug if hasattr(settings, 'debug') else False,
    poolclass=StaticPool,
)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


def get_db():
    """获取数据库会话"""
    db = SessionLocal()
    try:
        start = time.time()
        yield db
        elapsed = time.time() - start
        if elapsed > 1.0:
            slow_query_logger.warning(f"慢查询检测: {elapsed:.2f}s")
    finally:
        db.close()


def init_db():
    """初始化数据库，创建所有表"""
    Base.metadata.create_all(bind=engine)


# ============================================================
# 连接器模型
# ============================================================

class Connector(Base):
    """数据源连接器模型"""
    __tablename__ = "dc_connectors"

    id = Column(Integer, primary_key=True, index=True, comment="连接器ID")
    name = Column(String(255), nullable=False, comment="连接器名称")
    connector_type = Column(String(50), nullable=False, index=True, comment="连接器类型")
    description = Column(Text, default="", comment="连接器描述")
    config = Column(JSON, default=dict, comment="连接配置")
    status = Column(String(20), default="disconnected", index=True, comment="状态")
    health_status = Column(String(20), default="unknown", comment="健康状态")
    last_health_check = Column(DateTime, nullable=True, comment="最后健康检查时间")
    total_reads = Column(Integer, default=0, comment="总读取次数")
    total_writes = Column(Integer, default=0, comment="总写入次数")
    total_bytes = Column(Integer, default=0, comment="总数据量（字节）")
    created_at = Column(DateTime, default=datetime.now, comment="创建时间")
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now, comment="更新时间")

    __table_args__ = (
        Index('idx_conn_type', 'connector_type'),
        Index('idx_conn_status', 'status'),
        Index('idx_conn_name', 'name'),
    )

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "connector_type": self.connector_type,
            "description": self.description,
            "config": self.config or {},
            "status": self.status,
            "health_status": self.health_status,
            "last_health_check": self.last_health_check.isoformat() if self.last_health_check else None,
            "stats": {
                "total_reads": self.total_reads,
                "total_writes": self.total_writes,
                "total_bytes": self.total_bytes,
            },
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


# ============================================================
# 管道模型
# ============================================================

class Pipeline(Base):
    """数据管道模型"""
    __tablename__ = "dc_pipelines"

    id = Column(Integer, primary_key=True, index=True, comment="管道ID")
    name = Column(String(255), nullable=False, comment="管道名称")
    description = Column(Text, default="", comment="管道描述")
    source_connector_id = Column(Integer, nullable=True, index=True, comment="源连接器ID")
    target_connector_id = Column(Integer, nullable=True, index=True, comment="目标连接器ID")
    stages = Column(JSON, default=list, comment="处理阶段配置")
    schedule_type = Column(String(20), default="manual", comment="调度类型：manual/cron/interval")
    schedule_config = Column(JSON, default=dict, comment="调度配置")
    is_enabled = Column(Boolean, default=True, index=True, comment="是否启用")
    total_runs = Column(Integer, default=0, comment="总执行次数")
    success_runs = Column(Integer, default=0, comment="成功次数")
    failed_runs = Column(Integer, default=0, comment="失败次数")
    last_run_at = Column(DateTime, nullable=True, comment="最后执行时间")
    last_run_status = Column(String(20), default="idle", comment="最后执行状态")
    created_at = Column(DateTime, default=datetime.now, comment="创建时间")
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now, comment="更新时间")

    __table_args__ = (
        Index('idx_pipe_enabled', 'is_enabled'),
        Index('idx_pipe_source', 'source_connector_id'),
        Index('idx_pipe_target', 'target_connector_id'),
    )

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "source_connector_id": self.source_connector_id,
            "target_connector_id": self.target_connector_id,
            "stages": self.stages or [],
            "schedule_type": self.schedule_type,
            "schedule_config": self.schedule_config or {},
            "is_enabled": self.is_enabled,
            "stats": {
                "total_runs": self.total_runs,
                "success_runs": self.success_runs,
                "failed_runs": self.failed_runs,
            },
            "last_run_at": self.last_run_at.isoformat() if self.last_run_at else None,
            "last_run_status": self.last_run_status,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


# ============================================================
# 管道执行记录模型
# ============================================================

class PipelineRun(Base):
    """管道执行记录模型"""
    __tablename__ = "dc_pipeline_runs"

    id = Column(Integer, primary_key=True, index=True, comment="执行ID")
    pipeline_id = Column(Integer, nullable=False, index=True, comment="管道ID")
    status = Column(String(20), default="pending", index=True, comment="状态")
    trigger_type = Column(String(20), default="manual", comment="触发类型")
    started_at = Column(DateTime, nullable=True, comment="开始时间")
    finished_at = Column(DateTime, nullable=True, comment="结束时间")
    duration_seconds = Column(Float, default=0.0, comment="执行时长（秒）")
    records_read = Column(Integer, default=0, comment="读取记录数")
    records_processed = Column(Integer, default=0, comment="处理记录数")
    records_written = Column(Integer, default=0, comment="写入记录数")
    error_message = Column(Text, default="", comment="错误信息")
    stage_results = Column(JSON, default=list, comment="各阶段结果")
    retry_count = Column(Integer, default=0, comment="重试次数")
    cancelled = Column(Boolean, default=False, comment="是否已取消")
    created_at = Column(DateTime, default=datetime.now, comment="创建时间")

    __table_args__ = (
        Index('idx_run_pipeline_id', 'pipeline_id'),
        Index('idx_run_status', 'status'),
        Index('idx_run_started_at', 'started_at'),
    )

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "pipeline_id": self.pipeline_id,
            "status": self.status,
            "trigger_type": self.trigger_type,
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "finished_at": self.finished_at.isoformat() if self.finished_at else None,
            "duration_seconds": round(self.duration_seconds, 3),
            "records_read": self.records_read,
            "records_processed": self.records_processed,
            "records_written": self.records_written,
            "error_message": self.error_message,
            "stage_results": self.stage_results or [],
            "retry_count": self.retry_count,
            "cancelled": self.cancelled,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


# ============================================================
# Pydantic 模型（如果可用）
# ============================================================

try:
    from pydantic import BaseModel, Field
    from typing import List as PydanticList, Dict as PydanticDict, Any

    class ConnectorCreate(BaseModel):
        name: str
        connector_type: str
        description: str = ""
        config: PydanticDict[str, Any] = Field(default_factory=dict)

    class ConnectorUpdate(BaseModel):
        name: Optional[str] = None
        description: Optional[str] = None
        config: Optional[PydanticDict[str, Any]] = None

    class PipelineCreate(BaseModel):
        name: str
        description: str = ""
        source_connector_id: Optional[int] = None
        target_connector_id: Optional[int] = None
        stages: PydanticList[PydanticDict[str, Any]] = Field(default_factory=list)
        schedule_type: str = "manual"
        schedule_config: PydanticDict[str, Any] = Field(default_factory=dict)

    class PipelineUpdate(BaseModel):
        name: Optional[str] = None
        description: Optional[str] = None
        source_connector_id: Optional[int] = None
        target_connector_id: Optional[int] = None
        stages: Optional[PydanticList[PydanticDict[str, Any]]] = None
        schedule_type: Optional[str] = None
        schedule_config: Optional[PydanticDict[str, Any]] = None
        is_enabled: Optional[bool] = None

    class PipelineRunRequest(BaseModel):
        trigger_type: str = "manual"
        params: PydanticDict[str, Any] = Field(default_factory=dict)

except ImportError:
    pass


if __name__ == "__main__":
    init_db()
    print(f"数据库已初始化: {settings.db_path}")
    print("已创建表:")
    for table in Base.metadata.tables:
        print(f"  - {table}")
