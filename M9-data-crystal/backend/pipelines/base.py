"""
云汐 M9 数据水晶 - 管道基类

P3 优化：数据采集管道 + 连接器生态
定义数据管道的核心框架：阶段（Stage）和管道（Pipeline）
"""

from __future__ import annotations

import time
import logging
from abc import ABC, abstractmethod
from typing import Iterator, List, Dict, Any, Optional
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


# ============================================================
# 管道执行状态
# ============================================================

class PipelineStatus:
    """管道执行状态常量"""
    PENDING = "pending"
    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"
    CANCELLED = "cancelled"
    PAUSED = "paused"


# ============================================================
# 阶段结果
# ============================================================

@dataclass
class StageResult:
    """阶段执行结果"""
    stage_name: str = ""
    status: str = PipelineStatus.PENDING
    records_in: int = 0
    records_out: int = 0
    errors: int = 0
    duration_seconds: float = 0.0
    error_message: str = ""
    details: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "stage_name": self.stage_name,
            "status": self.status,
            "records_in": self.records_in,
            "records_out": self.records_out,
            "errors": self.errors,
            "duration_seconds": round(self.duration_seconds, 3),
            "error_message": self.error_message,
            "details": self.details,
        }


# ============================================================
# 管道执行结果
# ============================================================

@dataclass
class PipelineResult:
    """管道执行结果"""
    pipeline_name: str = ""
    status: str = PipelineStatus.PENDING
    total_records_read: int = 0
    total_records_processed: int = 0
    total_records_written: int = 0
    total_errors: int = 0
    duration_seconds: float = 0.0
    stage_results: List[StageResult] = field(default_factory=list)
    error_message: str = ""
    started_at: Optional[float] = None
    finished_at: Optional[float] = None
    cancelled: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return {
            "pipeline_name": self.pipeline_name,
            "status": self.status,
            "total_records_read": self.total_records_read,
            "total_records_processed": self.total_records_processed,
            "total_records_written": self.total_records_written,
            "total_errors": self.total_errors,
            "duration_seconds": round(self.duration_seconds, 3),
            "stage_results": [sr.to_dict() for sr in self.stage_results],
            "error_message": self.error_message,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "cancelled": self.cancelled,
        }


# ============================================================
# 管道阶段基类
# ============================================================

class PipelineStage(ABC):
    """
    管道阶段基类

    所有数据处理阶段都必须继承此类并实现 process 方法。
    阶段是管道中的一个数据处理节点，接收数据流并输出数据流。
    """

    name: str = "stage"
    description: str = ""

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        """
        初始化阶段

        Args:
            config: 阶段配置
        """
        self._config: Dict[str, Any] = config or {}
        self._stats: Dict[str, Any] = {
            "total_records_in": 0,
            "total_records_out": 0,
            "total_errors": 0,
            "total_runs": 0,
        }

    @abstractmethod
    def process(self, data: Iterator[Dict[str, Any]]) -> Iterator[Dict[str, Any]]:
        """
        处理数据流

        Args:
            data: 输入数据迭代器

        Yields:
            dict: 输出数据
        """
        pass

    def process_batch(self, data: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        批量处理数据

        Args:
            data: 输入数据列表

        Returns:
            list[dict]: 输出数据列表
        """
        return list(self.process(iter(data)))

    def validate_config(self) -> bool:
        """验证配置是否有效，子类可重写"""
        return True

    def get_stats(self) -> Dict[str, Any]:
        """获取阶段统计信息"""
        return dict(self._stats)

    def reset_stats(self) -> None:
        """重置统计信息"""
        self._stats = {
            "total_records_in": 0,
            "total_records_out": 0,
            "total_errors": 0,
            "total_runs": 0,
        }

    def _record_in(self, count: int = 1) -> None:
        """记录输入数据量"""
        self._stats["total_records_in"] += count

    def _record_out(self, count: int = 1) -> None:
        """记录输出数据量"""
        self._stats["total_records_out"] += count

    def _record_error(self) -> None:
        """记录错误"""
        self._stats["total_errors"] += 1


# ============================================================
# 阶段注册表
# ============================================================

class StageRegistry:
    """阶段注册表"""

    _stages: Dict[str, type] = {}

    @classmethod
    def register(cls, stage_class: type) -> type:
        """注册阶段类（可作为装饰器）"""
        if not issubclass(stage_class, PipelineStage):
            raise TypeError(f"{stage_class.__name__} 必须继承 PipelineStage")
        name = stage_class.__name__
        cls._stages[name] = stage_class
        logger.debug(f"管道阶段已注册: {name}")
        return stage_class

    @classmethod
    def unregister(cls, name: str) -> bool:
        """注销阶段"""
        if name in cls._stages:
            del cls._stages[name]
            return True
        return False

    @classmethod
    def get(cls, name: str) -> Optional[type]:
        """获取阶段类"""
        return cls._stages.get(name)

    @classmethod
    def create(cls, name: str, config: Optional[Dict[str, Any]] = None) -> PipelineStage:
        """创建阶段实例"""
        stage_class = cls.get(name)
        if stage_class is None:
            raise ValueError(f"未知的阶段类型: {name}")
        return stage_class(config=config)

    @classmethod
    def list_all(cls) -> List[str]:
        """列出所有阶段名称"""
        return list(cls._stages.keys())

    @classmethod
    def clear(cls) -> None:
        """清空注册表（测试用）"""
        cls._stages.clear()


# ============================================================
# 数据管道
# ============================================================

class DataPipeline:
    """
    数据管道

    由多个阶段串联组成，从源连接器读取数据，
    经过一系列处理阶段后，写入目标连接器。
    """

    def __init__(self, name: str = "", stages: Optional[List[PipelineStage]] = None):
        """
        初始化管道

        Args:
            name: 管道名称
            stages: 处理阶段列表
        """
        self.name = name
        self.stages: List[PipelineStage] = stages or []
        self._cancelled = False

    def add_stage(self, stage: PipelineStage) -> None:
        """添加处理阶段"""
        self.stages.append(stage)

    def insert_stage(self, index: int, stage: PipelineStage) -> None:
        """在指定位置插入阶段"""
        self.stages.insert(index, stage)

    def remove_stage(self, index: int) -> PipelineStage:
        """移除指定位置的阶段"""
        return self.stages.pop(index)

    def cancel(self) -> None:
        """取消管道执行"""
        self._cancelled = True

    def is_cancelled(self) -> bool:
        """检查是否已取消"""
        return self._cancelled

    def run(self, source: Any = None, target: Any = None,
            source_query: Optional[Dict[str, Any]] = None) -> PipelineResult:
        """
        同步执行管道

        Args:
            source: 源连接器（BaseConnector 实例或数据迭代器）
            target: 目标连接器（可选）
            source_query: 源查询参数

        Returns:
            PipelineResult: 执行结果
        """
        result = PipelineResult(pipeline_name=self.name)
        result.started_at = time.time()
        result.status = PipelineStatus.RUNNING
        self._cancelled = False

        try:
            # 获取数据源
            if source is None:
                raise ValueError("必须指定数据源")

            if hasattr(source, 'read') and callable(source.read):
                # 连接器
                data_iter = source.read(source_query)
            elif isinstance(source, (list, Iterator)):
                # 直接传入数据
                data_iter = iter(source)
            else:
                raise ValueError(f"不支持的数据源类型: {type(source)}")

            # 计数读取的记录
            def count_wrapper(iterator):
                count = 0
                for item in iterator:
                    count += 1
                    yield item
                result.total_records_read = count

            current_data = count_wrapper(data_iter)

            # 依次执行各阶段
            for stage in self.stages:
                if self._cancelled:
                    result.status = PipelineStatus.CANCELLED
                    result.cancelled = True
                    break

                stage_result = StageResult(stage_name=stage.name)
                stage_result.status = PipelineStatus.RUNNING
                stage_start = time.time()

                try:
                    # 计算输入记录数
                    input_records = list(current_data)
                    stage_result.records_in = len(input_records)

                    # 执行阶段处理
                    output_records = list(stage.process(iter(input_records)))
                    stage_result.records_out = len(output_records)
                    stage_result.status = PipelineStatus.SUCCESS

                    current_data = iter(output_records)

                except Exception as e:
                    stage_result.status = PipelineStatus.FAILED
                    stage_result.error_message = str(e)
                    stage_result.errors = 1
                    result.total_errors += 1
                    logger.error(f"阶段 [{stage.name}] 执行失败: {e}")
                    raise

                finally:
                    stage_result.duration_seconds = time.time() - stage_start
                    result.stage_results.append(stage_result)

            if not self._cancelled:
                # 写入目标连接器
                if target is not None and hasattr(target, 'write') and callable(target.write):
                    final_data = list(current_data)
                    result.total_records_processed = len(final_data)
                    try:
                        written = target.write(final_data)
                        result.total_records_written = written
                    except Exception as e:
                        logger.error(f"写入目标失败: {e}")
                        raise
                else:
                    # 无目标，计算处理数
                    final_data = list(current_data)
                    result.total_records_processed = len(final_data)

                result.status = PipelineStatus.SUCCESS

        except Exception as e:
            result.status = PipelineStatus.FAILED
            result.error_message = str(e)
            logger.error(f"管道 [{self.name}] 执行失败: {e}")

        finally:
            result.finished_at = time.time()
            result.duration_seconds = result.finished_at - (result.started_at or result.finished_at)

        return result

    def run_stream(self, source: Any = None, target: Any = None,
                   source_query: Optional[Dict[str, Any]] = None) -> Iterator[Dict[str, Any]]:
        """
        流式执行管道，逐行产出处理后的数据

        Args:
            source: 源连接器或数据迭代器
            target: 目标连接器（可选）
            source_query: 源查询参数

        Yields:
            dict: 处理后的数据记录
        """
        self._cancelled = False

        # 获取数据源
        if source is None:
            raise ValueError("必须指定数据源")

        if hasattr(source, 'read') and callable(source.read):
            data_iter = source.read(source_query)
        elif isinstance(source, (list, Iterator)):
            data_iter = iter(source)
        else:
            raise ValueError(f"不支持的数据源类型: {type(source)}")

        current_data = data_iter

        # 依次通过各阶段
        for stage in self.stages:
            if self._cancelled:
                return
            current_data = stage.process(current_data)

        # 产出最终数据
        count = 0
        for record in current_data:
            if self._cancelled:
                break
            count += 1
            yield record

    def validate(self) -> bool:
        """验证管道配置"""
        for stage in self.stages:
            if not stage.validate_config():
                return False
        return True
