"""M8 标准健康检查与性能指标接口.

提供 M8 管理平台需要的标准健康检查和性能指标接口：
- GET /health              - 健康检查（白名单，无需鉴权）
- GET /api/v1/admin/health - M8 标准健康检查（白名单）
- GET /api/v1/admin/metrics - 性能指标（需鉴权）
"""

from __future__ import annotations

import os
import time
from dataclasses import dataclass, field
from typing import Any

import structlog

logger = structlog.get_logger(__name__)

VERSION = "1.0.0"
MODULE_NAME = "m4"


@dataclass
class MetricsCollector:
    """性能指标收集器.

    收集并维护模块运行时的性能指标数据。
    """

    # 请求统计
    requests_total: int = 0
    requests_error: int = 0
    response_time_sum_ms: float = 0.0
    response_time_count: int = 0

    # 场景统计
    recognize_count: int = 0
    switch_count: int = 0
    auto_switch_count: int = 0

    # 时间窗口（最近 60 秒的请求计数）
    _window_start: float = field(default_factory=time.time)
    _window_requests: int = 0

    def record_request(self, success: bool, response_ms: float) -> None:
        """记录一次请求."""
        self.requests_total += 1
        if not success:
            self.requests_error += 1
        self.response_time_sum_ms += response_ms
        self.response_time_count += 1
        self._window_requests += 1

        # 重置窗口（每60秒）
        now = time.time()
        if now - self._window_start >= 60:
            self._window_start = now
            self._window_requests = 1

    def record_recognize(self) -> None:
        """记录一次场景识别."""
        self.recognize_count += 1

    def record_switch(self, auto: bool = False) -> None:
        """记录一次场景切换."""
        self.switch_count += 1
        if auto:
            self.auto_switch_count += 1

    @property
    def requests_per_second(self) -> float:
        """最近窗口的 RPS."""
        elapsed = time.time() - self._window_start
        if elapsed <= 0:
            return 0.0
        return round(self._window_requests / elapsed, 2)

    @property
    def avg_response_ms(self) -> float:
        """平均响应时间（毫秒）."""
        if self.response_time_count == 0:
            return 0.0
        return round(self.response_time_sum_ms / self.response_time_count, 1)

    @property
    def error_rate(self) -> float:
        """错误率."""
        if self.requests_total == 0:
            return 0.0
        return round(self.requests_error / self.requests_total, 4)


class HealthMetricsService:
    """健康检查与性能指标服务.

    封装健康检查和性能指标的业务逻辑。
    """

    def __init__(
        self,
        data_path: str = "",
        context_store: Any = None,
        switch_manager: Any = None,
        recognizer: Any = None,
    ) -> None:
        """初始化健康指标服务.

        Args:
            data_path: 数据目录路径
            context_store: 上下文存储服务
            switch_manager: 场景切换管理器
            recognizer: 场景识别器
        """
        self._start_time = time.time()
        self._data_path = data_path
        self._context_store = context_store
        self._switch_manager = switch_manager
        self._recognizer = recognizer
        self._metrics = MetricsCollector()

    # -----------------------------------------------------------------------
    # 健康检查
    # -----------------------------------------------------------------------

    async def get_health(self) -> dict[str, Any]:
        """获取健康检查结果.

        Returns:
            健康状态字典
        """
        checks: dict[str, str] = {}

        # 存储检查
        checks["storage"] = self._check_storage()

        # 上下文服务检查
        checks["context_store"] = self._check_context_store()

        # 场景引擎检查
        checks["scene_engine"] = self._check_scene_engine()

        # 总体状态
        status = self._compute_overall_status(checks)

        return {
            "status": status,
            "version": VERSION,
            "uptime_seconds": int(time.time() - self._start_time),
            "module": MODULE_NAME,
            "checks": checks,
        }

    def _check_storage(self) -> str:
        """检查存储状态."""
        try:
            if self._data_path and os.path.exists(self._data_path):
                # 检查是否可写
                test_file = os.path.join(self._data_path, ".health_check")
                with open(test_file, "w") as f:
                    f.write("ok")
                os.unlink(test_file)
                return "healthy"
            return "healthy"  # 内存模式
        except Exception as e:
            logger.warning("health.storage_check_failed", error_type=type(e).__name__, error=str(e))
            return "unhealthy"

    def _check_context_store(self) -> str:
        """检查上下文存储服务."""
        try:
            if self._context_store is not None:
                # 简单探测
                status = self._context_store.get_all_status()
                if isinstance(status, dict):
                    return "healthy"
            return "healthy"
        except Exception as e:
            logger.warning("health.context_store_check_failed", error_type=type(e).__name__, error=str(e))
            return "unhealthy"

    def _check_scene_engine(self) -> str:
        """检查场景引擎."""
        try:
            if self._recognizer is not None:
                result = self._recognizer.recognize("测试")
                if isinstance(result, dict):
                    return "healthy"
            return "healthy"
        except Exception as e:
            logger.warning("health.scene_engine_check_failed", error_type=type(e).__name__, error=str(e))
            return "unhealthy"

    def _compute_overall_status(self, checks: dict[str, str]) -> str:
        """根据各分项计算总体状态."""
        values = list(checks.values())
        if "unhealthy" in values:
            return "unhealthy"
        if "degraded" in values:
            return "degraded"
        return "healthy"

    # -----------------------------------------------------------------------
    # 性能指标
    # -----------------------------------------------------------------------

    async def get_metrics(self) -> dict[str, Any]:
        """获取性能指标.

        Returns:
            性能指标字典
        """
        # 系统资源
        cpu_percent, memory_mb = self._get_system_resources()

        # 磁盘使用
        disk_usage_mb = self._get_disk_usage_mb()

        # 场景统计
        scene_stats = self._get_scene_stats()

        return {
            "cpu_percent": cpu_percent,
            "memory_mb": memory_mb,
            "disk_usage_mb": disk_usage_mb,
            "requests_total": self._metrics.requests_total,
            "requests_per_second": self._metrics.requests_per_second,
            "avg_response_ms": self._metrics.avg_response_ms,
            "error_rate": self._metrics.error_rate,
            "recognize_count": self._metrics.recognize_count,
            "switch_count": self._metrics.switch_count,
            "auto_switch_count": self._metrics.auto_switch_count,
            "scene_stats": scene_stats,
            "uptime_seconds": int(time.time() - self._start_time),
            "module": MODULE_NAME,
            "version": VERSION,
        }

    def _get_system_resources(self) -> tuple[float, float]:
        """获取 CPU 和内存使用情况."""
        try:
            import psutil  # type: ignore
            cpu = psutil.cpu_percent(interval=0.1)
            mem = psutil.virtual_memory()
            memory_mb = round(mem.used / (1024 * 1024), 1)
            return cpu, memory_mb
        except ImportError:
            return 0.0, 0.0
        except Exception as e:
            logger.warning("health.system_resources_failed", error_type=type(e).__name__, error=str(e))
            return 0.0, 0.0

    def _get_disk_usage_mb(self) -> float:
        """获取磁盘使用量（MB）."""
        try:
            path = self._data_path or "."
            if not os.path.exists(path):
                return 0.0
            total_size = 0
            for dirpath, _dirnames, filenames in os.walk(path):
                for f in filenames:
                    fp = os.path.join(dirpath, f)
                    try:
                        total_size += os.path.getsize(fp)
                    except OSError:
                        pass
            return round(total_size / (1024 * 1024), 1)
        except Exception as e:
            logger.warning("health.disk_usage_failed", error_type=type(e).__name__, error=str(e))
            return 0.0

    def _get_scene_stats(self) -> dict[str, Any]:
        """获取场景相关统计."""
        stats: dict[str, Any] = {
            "total_scenes": 6,
            "current_scene_distribution": {},
        }

        try:
            if self._switch_manager is not None:
                all_status = self._switch_manager.get_all_scene_status()
                stats["total_users"] = len(all_status)
                distribution: dict[str, int] = {}
                for _, info in all_status.items():
                    sid = info.get("scene_id", "unknown")
                    distribution[sid] = distribution.get(sid, 0) + 1
                stats["current_scene_distribution"] = distribution
        except Exception as e:
            logger.warning("health.scene_stats_failed", error_type=type(e).__name__, error=str(e))
            pass

        try:
            if self._context_store is not None:
                ctx_status = self._context_store.get_all_status()
                stats["context_users"] = ctx_status.get("total_users", 0)
        except Exception as e:
            logger.warning("health.context_stats_failed", error_type=type(e).__name__, error=str(e))
            pass

        return stats

    @property
    def metrics(self) -> MetricsCollector:
        """获取指标收集器（用于记录指标）."""
        return self._metrics
