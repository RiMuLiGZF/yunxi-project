"""
云汐 M9 数据水晶 - 管道管理器

P3 优化：数据采集管道 + 连接器生态
管理管道定义、执行调度、执行历史、状态监控、失败重试
"""

from __future__ import annotations

import time
import threading
import logging
from typing import Dict, List, Any, Optional
from dataclasses import dataclass, field

from .base import (
    DataPipeline,
    PipelineStage,
    PipelineResult,
    PipelineStatus,
    StageRegistry,
)

logger = logging.getLogger(__name__)


# ============================================================
# 管道定义
# ============================================================

@dataclass
class PipelineDefinition:
    """管道定义"""
    id: str
    name: str
    description: str = ""
    source_connector_id: Optional[str] = None
    target_connector_id: Optional[str] = None
    stages: List[Dict[str, Any]] = field(default_factory=list)
    schedule_type: str = "manual"
    schedule_config: Dict[str, Any] = field(default_factory=dict)
    is_enabled: bool = True
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    total_runs: int = 0
    success_runs: int = 0
    failed_runs: int = 0
    last_run_at: Optional[float] = None
    last_run_status: str = PipelineStatus.PENDING

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "source_connector_id": self.source_connector_id,
            "target_connector_id": self.target_connector_id,
            "stages": self.stages,
            "schedule_type": self.schedule_type,
            "schedule_config": self.schedule_config,
            "is_enabled": self.is_enabled,
            "stats": {
                "total_runs": self.total_runs,
                "success_runs": self.success_runs,
                "failed_runs": self.failed_runs,
            },
            "last_run_at": self.last_run_at,
            "last_run_status": self.last_run_status,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }


# ============================================================
# 管道运行记录
# ============================================================

@dataclass
class PipelineRunRecord:
    """管道运行记录"""
    run_id: str
    pipeline_id: str
    status: str = PipelineStatus.PENDING
    trigger_type: str = "manual"
    started_at: Optional[float] = None
    finished_at: Optional[float] = None
    duration_seconds: float = 0.0
    records_read: int = 0
    records_processed: int = 0
    records_written: int = 0
    error_message: str = ""
    stage_results: List[Dict[str, Any]] = field(default_factory=list)
    retry_count: int = 0
    cancelled: bool = False
    pipeline_instance: Optional[DataPipeline] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "run_id": self.run_id,
            "pipeline_id": self.pipeline_id,
            "status": self.status,
            "trigger_type": self.trigger_type,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "duration_seconds": round(self.duration_seconds, 3),
            "records_read": self.records_read,
            "records_processed": self.records_processed,
            "records_written": self.records_written,
            "error_message": self.error_message,
            "stage_results": self.stage_results,
            "retry_count": self.retry_count,
            "cancelled": self.cancelled,
        }


# ============================================================
# 管道管理器
# ============================================================

class PipelineManager:
    """
    管道管理器

    功能：
    - 管道定义存储
    - 管道执行调度
    - 执行历史记录
    - 执行状态监控
    - 失败重试
    """

    def __init__(self, max_concurrent: int = 5, retry_max_attempts: int = 3,
                 retry_delay: float = 5.0):
        """
        初始化管道管理器

        Args:
            max_concurrent: 最大并发执行数
            retry_max_attempts: 最大重试次数
            retry_delay: 重试延迟（秒）
        """
        self._max_concurrent = max_concurrent
        self._retry_max_attempts = retry_max_attempts
        self._retry_delay = retry_delay

        # 管道定义存储
        self._pipelines: Dict[str, PipelineDefinition] = {}
        # 运行记录
        self._runs: Dict[str, PipelineRunRecord] = {}
        # 活跃运行数
        self._active_runs: int = 0
        # 下一个 ID
        self._next_pipeline_id = 1
        self._next_run_id = 1

        self._lock = threading.RLock()
        self._connector_manager = None

    def set_connector_manager(self, connector_manager) -> None:
        """设置连接器管理器"""
        self._connector_manager = connector_manager

    # ============================================================
    # 管道定义管理
    # ============================================================

    def create_pipeline(self, name: str, stages: List[Dict[str, Any]],
                        description: str = "", source_connector_id: Optional[str] = None,
                        target_connector_id: Optional[str] = None,
                        schedule_type: str = "manual",
                        schedule_config: Optional[Dict[str, Any]] = None,
                        pipeline_id: Optional[str] = None) -> str:
        """
        创建管道定义

        Returns:
            str: 管道 ID
        """
        with self._lock:
            if pipeline_id is None:
                pipeline_id = f"pipe_{self._next_pipeline_id}"
                self._next_pipeline_id += 1

            if pipeline_id in self._pipelines:
                raise ValueError(f"管道 ID 已存在: {pipeline_id}")

            # 验证阶段配置
            for stage_config in stages:
                stage_type = stage_config.get("type", "")
                if not StageRegistry.get(stage_type):
                    raise ValueError(f"未知的阶段类型: {stage_type}")

            pipeline_def = PipelineDefinition(
                id=pipeline_id,
                name=name,
                description=description,
                source_connector_id=source_connector_id,
                target_connector_id=target_connector_id,
                stages=stages,
                schedule_type=schedule_type,
                schedule_config=schedule_config or {},
            )

            self._pipelines[pipeline_id] = pipeline_def
            logger.info(f"管道已创建: {pipeline_id} ({name})")
            return pipeline_id

    def get_pipeline(self, pipeline_id: str) -> PipelineDefinition:
        """获取管道定义"""
        with self._lock:
            if pipeline_id not in self._pipelines:
                raise KeyError(f"管道不存在: {pipeline_id}")
            return self._pipelines[pipeline_id]

    def update_pipeline(self, pipeline_id: str, **kwargs) -> bool:
        """更新管道定义"""
        with self._lock:
            if pipeline_id not in self._pipelines:
                raise KeyError(f"管道不存在: {pipeline_id}")

            pipeline = self._pipelines[pipeline_id]
            updateable_fields = {
                "name", "description", "stages", "source_connector_id",
                "target_connector_id", "schedule_type", "schedule_config", "is_enabled",
            }

            for key, value in kwargs.items():
                if key in updateable_fields and value is not None:
                    setattr(pipeline, key, value)

            pipeline.updated_at = time.time()
            logger.info(f"管道已更新: {pipeline_id}")
            return True

    def delete_pipeline(self, pipeline_id: str) -> bool:
        """删除管道"""
        with self._lock:
            if pipeline_id not in self._pipelines:
                return False

            del self._pipelines[pipeline_id]
            logger.info(f"管道已删除: {pipeline_id}")
            return True

    def list_pipelines(self) -> List[Dict[str, Any]]:
        """列出所有管道"""
        with self._lock:
            return [p.to_dict() for p in self._pipelines.values()]

    # ============================================================
    # 管道实例化
    # ============================================================

    def _build_pipeline_instance(self, pipeline_def: PipelineDefinition) -> DataPipeline:
        """根据管道定义构建管道实例"""
        pipeline = DataPipeline(name=pipeline_def.name)

        for stage_config in pipeline_def.stages:
            stage_type = stage_config.get("type", "")
            stage_params = stage_config.get("config", {})

            stage_class = StageRegistry.get(stage_type)
            if stage_class is None:
                raise ValueError(f"未知的阶段类型: {stage_type}")

            stage = stage_class(config=stage_params)
            pipeline.add_stage(stage)

        return pipeline

    # ============================================================
    # 管道执行
    # ============================================================

    def run_pipeline(self, pipeline_id: str, trigger_type: str = "manual",
                     source_data: Any = None, params: Optional[Dict[str, Any]] = None) -> PipelineRunRecord:
        """
        同步执行管道

        Args:
            pipeline_id: 管道 ID
            trigger_type: 触发类型
            source_data: 源数据（可选，若不提供则使用管道配置的源连接器）
            params: 执行参数

        Returns:
            PipelineRunRecord: 运行记录
        """
        pipeline_def = self.get_pipeline(pipeline_id)

        with self._lock:
            # 检查并发限制
            if self._active_runs >= self._max_concurrent:
                raise RuntimeError(f"已达到最大并发数: {self._max_concurrent}")

            self._active_runs += 1

            # 创建运行记录
            run_id = f"run_{self._next_run_id}"
            self._next_run_id += 1
            run_record = PipelineRunRecord(
                run_id=run_id,
                pipeline_id=pipeline_id,
                trigger_type=trigger_type,
                status=PipelineStatus.RUNNING,
                started_at=time.time(),
            )
            self._runs[run_id] = run_record

        try:
            # 构建管道实例
            pipeline = self._build_pipeline_instance(pipeline_def)
            run_record.pipeline_instance = pipeline

            # 获取源
            source = source_data
            source_query = None
            if source is None and pipeline_def.source_connector_id and self._connector_manager:
                source_connector = self._connector_manager.get_connector(
                    pipeline_def.source_connector_id
                )
                if not source_connector.is_connected():
                    source_connector.connect()
                source = source_connector
                source_query = (params or {}).get("source_query")

            # 获取目标
            target = None
            if pipeline_def.target_connector_id and self._connector_manager:
                target_connector = self._connector_manager.get_connector(
                    pipeline_def.target_connector_id
                )
                if not target_connector.is_connected():
                    target_connector.connect()
                target = target_connector

            # 执行管道
            result = pipeline.run(source=source, target=target, source_query=source_query)

            # 更新运行记录
            run_record.status = result.status
            run_record.finished_at = result.finished_at
            run_record.duration_seconds = result.duration_seconds
            run_record.records_read = result.total_records_read
            run_record.records_processed = result.total_records_processed
            run_record.records_written = result.total_records_written
            run_record.error_message = result.error_message
            run_record.stage_results = [sr.to_dict() for sr in result.stage_results]
            run_record.cancelled = result.cancelled

            # 更新管道统计
            with self._lock:
                pipeline_def.total_runs += 1
                pipeline_def.last_run_at = time.time()
                pipeline_def.last_run_status = result.status
                if result.status == PipelineStatus.SUCCESS:
                    pipeline_def.success_runs += 1
                elif result.status == PipelineStatus.FAILED:
                    pipeline_def.failed_runs += 1

                    # 失败重试
                    if self._retry_max_attempts > 0 and params and not params.get("no_retry"):
                        self._retry_pipeline(pipeline_def, run_record, source, target, source_query)

            return run_record

        except Exception as e:
            run_record.status = PipelineStatus.FAILED
            run_record.finished_at = time.time()
            run_record.duration_seconds = run_record.finished_at - (run_record.started_at or run_record.finished_at)
            run_record.error_message = str(e)

            with self._lock:
                pipeline_def.total_runs += 1
                pipeline_def.last_run_at = time.time()
                pipeline_def.last_run_status = PipelineStatus.FAILED
                pipeline_def.failed_runs += 1

            logger.error(f"管道执行失败 [{pipeline_id}]: {e}")
            return run_record

        finally:
            with self._lock:
                self._active_runs -= 1

    def _retry_pipeline(self, pipeline_def: PipelineDefinition, run_record: PipelineRunRecord,
                        source: Any, target: Any, source_query: Optional[Dict[str, Any]]) -> None:
        """失败重试"""
        for attempt in range(self._retry_max_attempts):
            time.sleep(self._retry_delay)

            if run_record.cancelled:
                break

            run_record.retry_count += 1
            logger.info(f"管道重试 [{pipeline_def.id}] 第 {run_record.retry_count} 次")

            pipeline = self._build_pipeline_instance(pipeline_def)
            result = pipeline.run(source=source, target=target, source_query=source_query)

            run_record.status = result.status
            run_record.finished_at = result.finished_at
            run_record.duration_seconds = result.duration_seconds
            run_record.records_read = result.total_records_read
            run_record.records_processed = result.total_records_processed
            run_record.records_written = result.total_records_written
            run_record.error_message = result.error_message
            run_record.stage_results = [sr.to_dict() for sr in result.stage_results]

            if result.status == PipelineStatus.SUCCESS:
                pipeline_def.success_runs += 1
                pipeline_def.failed_runs -= 1  # 抵消之前的失败计数
                break

    def run_pipeline_async(self, pipeline_id: str, trigger_type: str = "manual",
                           source_data: Any = None,
                           params: Optional[Dict[str, Any]] = None) -> str:
        """
        异步执行管道

        Returns:
            str: 运行 ID
        """
        pipeline_def = self.get_pipeline(pipeline_id)

        with self._lock:
            run_id = f"run_{self._next_run_id}"
            self._next_run_id += 1
            run_record = PipelineRunRecord(
                run_id=run_id,
                pipeline_id=pipeline_id,
                trigger_type=trigger_type,
                status=PipelineStatus.PENDING,
            )
            self._runs[run_id] = run_record

        # 在后台线程执行
        thread = threading.Thread(
            target=self._run_pipeline_thread,
            args=(pipeline_id, run_id, trigger_type, source_data, params),
            daemon=True,
            name=f"pipeline-{run_id}",
        )
        thread.start()

        return run_id

    def _run_pipeline_thread(self, pipeline_id: str, run_id: str,
                             trigger_type: str, source_data: Any,
                             params: Optional[Dict[str, Any]]) -> None:
        """后台线程执行管道"""
        try:
            self.run_pipeline(pipeline_id, trigger_type=trigger_type,
                              source_data=source_data, params=params)
        except Exception as e:
            with self._lock:
                if run_id in self._runs:
                    run = self._runs[run_id]
                    run.status = PipelineStatus.FAILED
                    run.error_message = str(e)
                    run.finished_at = time.time()

    def cancel_run(self, run_id: str) -> bool:
        """取消管道运行"""
        with self._lock:
            if run_id not in self._runs:
                return False

            run_record = self._runs[run_id]
            run_record.cancelled = True

            if run_record.pipeline_instance:
                run_record.pipeline_instance.cancel()

            if run_record.status == PipelineStatus.RUNNING:
                run_record.status = PipelineStatus.CANCELLED

            logger.info(f"管道运行已取消: {run_id}")
            return True

    # ============================================================
    # 运行历史
    # ============================================================

    def get_run(self, run_id: str) -> PipelineRunRecord:
        """获取运行记录"""
        with self._lock:
            if run_id not in self._runs:
                raise KeyError(f"运行记录不存在: {run_id}")
            return self._runs[run_id]

    def list_runs(self, pipeline_id: Optional[str] = None,
                  status: Optional[str] = None,
                  limit: int = 100,
                  offset: int = 0) -> List[Dict[str, Any]]:
        """列出运行记录"""
        with self._lock:
            runs = list(self._runs.values())

            # 过滤
            if pipeline_id:
                runs = [r for r in runs if r.pipeline_id == pipeline_id]
            if status:
                runs = [r for r in runs if r.status == status]

            # 按开始时间倒序
            runs.sort(key=lambda r: r.started_at or 0, reverse=True)

            # 分页
            runs = runs[offset:offset + limit]

            return [r.to_dict() for r in runs]

    # ============================================================
    # 统计信息
    # ============================================================

    def get_stats(self) -> Dict[str, Any]:
        """获取管理器统计信息"""
        with self._lock:
            return {
                "total_pipelines": len(self._pipelines),
                "total_runs": len(self._runs),
                "active_runs": self._active_runs,
                "max_concurrent": self._max_concurrent,
                "retry_max_attempts": self._retry_max_attempts,
            }

    def shutdown(self) -> None:
        """关闭管理器"""
        with self._lock:
            # 取消所有运行中的管道
            for run_id, run in self._runs.items():
                if run.status == PipelineStatus.RUNNING and run.pipeline_instance:
                    run.pipeline_instance.cancel()
        logger.info("管道管理器已关闭")


# ============================================================
# 单例
# ============================================================

_pipeline_manager: Optional[PipelineManager] = None


def get_pipeline_manager() -> PipelineManager:
    """获取管道管理器单例"""
    global _pipeline_manager
    if _pipeline_manager is None:
        from config import get_config
        settings = get_config()
        _pipeline_manager = PipelineManager(
            max_concurrent=getattr(settings, 'pipeline_max_concurrent', 5),
            retry_max_attempts=getattr(settings, 'pipeline_retry_max_attempts', 3),
            retry_delay=getattr(settings, 'pipeline_retry_delay', 5.0),
        )
    return _pipeline_manager
