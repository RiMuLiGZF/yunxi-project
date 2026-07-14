"""
M6 硬件外设 - 数据采集服务
后台定时任务，采集所有在线设备的传感器数据并存入 SQLite

P1-5 改造：数据库操作委托给 Repository，连接管理委托给 DatabaseConnection，
本层仅保留业务事务编排与采集调度逻辑。

P2-4 改造：集成 Metrics 指标埋点，记录采集次数、采集耗时、设备写入数等。
"""

import asyncio
import logging
import time
import traceback
from datetime import datetime
from typing import Dict, Any, List, Optional

from ..config import get_config
from ..database import DatabaseConnection, get_db, SensorDataRepository, DeviceStatusRepository
from .device_manager import get_device_manager

# P2-4: 导入 Metrics 单例用于采集指标埋点
try:
    from ..utils.metrics import Metrics
except ImportError:
    Metrics = None  # type: ignore[assignment, misc]

logger = logging.getLogger(__name__)


class DataCollector:
    """数据采集服务

    定期采集所有在线设备的传感器数据，存储到 SQLite 数据库，
    支持历史数据查询。

    P0-4 改造：移除 __new__ 单例模式，改为由 FastAPI lifespan 统一创建管理。
    模块级 get_data_collector() 作为向后兼容层保留（标记 deprecated）。

    P1-5 改造：数据库 SQL 操作下沉至 Repository，连接管理下沉至 DatabaseConnection。
    """

    def __init__(self, config=None, device_manager=None):
        """
        Args:
            config: 配置实例，为 None 时从兼容层获取（向后兼容）
            device_manager: 设备管理器实例，为 None 时从兼容层获取（向后兼容）
        """
        self._config = config if config is not None else get_config()
        self._device_manager = device_manager if device_manager is not None else get_device_manager()
        self._db_path = self._config.database_path
        self._running = False
        self._task: Optional[asyncio.Task] = None
        # P1-5: 自动建表（幂等）
        get_db(self._db_path, auto_init=True)

    async def start(self):
        """启动数据采集服务"""
        if self._running:
            return
        self._running = True
        self._task = asyncio.create_task(self._collection_loop())

    async def stop(self):
        """停止数据采集服务"""
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

    async def _collection_loop(self):
        """采集循环"""
        interval = self._config.collection_interval
        while self._running:
            try:
                self._collect_once()
            except Exception as e:
                print(f"[DataCollector] 采集异常: {e}")
            await asyncio.sleep(interval)

    def _collect_once(self):
        """执行一次数据采集

        所有设备的传感器数据与状态历史写入在同一个数据库事务中完成，
        任何一个设备写入失败则全部回滚，保证批次内数据一致性。

        P2-4 改造：添加 Metrics 指标埋点（采集计数、耗时直方图、设备写入数）。
        """
        # P2-4: 采集开始计时
        collect_start = time.time()
        metrics = Metrics() if Metrics is not None else None

        # 驱动所有设备步进（设备 I/O 操作，独立于 DB 事务）
        self._device_manager.tick_all()

        with DatabaseConnection(self._db_path, isolation_level=None) as conn:
            failed_device_id = None
            try:
                conn.execute("BEGIN IMMEDIATE")
                devices = self._device_manager.list_devices()

                for dev_data in devices:
                    device_id = dev_data["device_id"]
                    try:
                        # 写入设备状态历史（纳入同一事务）
                        DeviceStatusRepository.insert(
                            device_id=device_id,
                            status=dev_data["status"],
                            battery=dev_data.get("battery"),
                            signal=dev_data.get("signal_strength"),
                            conn=conn,
                        )

                        # 写入传感器数据
                        sensors = dev_data.get("sensors", {})
                        SensorDataRepository.insert_batch(
                            device_id=device_id,
                            readings=sensors,
                            conn=conn,
                        )
                    except Exception as e:
                        # 捕获单设备异常，记录设备上下文后抛出，触发整体回滚
                        failed_device_id = device_id
                        logger.error(
                            "[DataCollector] 设备数据写入失败，事务将回滚 | "
                            "device_id=%s, error_type=%s, error_msg=%s\n%s",
                            device_id,
                            type(e).__name__,
                            str(e),
                            traceback.format_exc(),
                        )
                        raise

                # 全部设备写入成功，提交事务
                conn.commit()
                logger.debug(
                    "[DataCollector] 采集事务提交成功，设备数=%d",
                    len(devices),
                )

                # P2-4 埋点：采集成功指标
                if metrics is not None:
                    elapsed = (time.time() - collect_start) * 1000
                    metrics.inc("collection_total")
                    metrics.inc("collection_success")
                    metrics.observe("collection_duration_ms", elapsed)
                    metrics.set_gauge("collection_device_count", len(devices))
                    metrics.set_gauge("collection_sensor_count", sum(
                        len(d.get("sensors", {})) for d in devices
                    ))

                # ---- 过期数据清理（独立事务，失败不影响采集结果）----
                try:
                    SensorDataRepository.cleanup_old(
                        self._config.data_retention_days, conn
                    )
                    DeviceStatusRepository.cleanup_old(
                        self._config.data_retention_days, conn
                    )
                    conn.commit()
                except Exception as e:
                    conn.rollback()
                    logger.warning(
                        "[DataCollector] 过期数据清理失败（不影响采集）: %s: %s",
                        type(e).__name__,
                        e,
                    )

            except Exception as e:
                # 主事务回滚
                conn.rollback()

                # P2-4 埋点：采集失败指标
                if metrics is not None:
                    metrics.inc("collection_total")
                    metrics.inc("collection_failures")

                if failed_device_id:
                    logger.error(
                        "[DataCollector] 采集事务已回滚 | 失败设备=%s, "
                        "error_type=%s, error_msg=%s",
                        failed_device_id,
                        type(e).__name__,
                        str(e),
                    )
                else:
                    logger.error(
                        "[DataCollector] 采集事务已回滚 | error_type=%s, "
                        "error_msg=%s\n%s",
                        type(e).__name__,
                        str(e),
                        traceback.format_exc(),
                    )
                raise  # 继续向上抛出，保持与原有调用方的行为一致

    def get_sensor_history(
        self,
        device_id: str,
        sensor_type: Optional[str] = None,
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None,
        limit: int = 1000,
    ) -> List[Dict[str, Any]]:
        """查询传感器历史数据

        Args:
            device_id: 设备ID
            sensor_type: 传感器类型（可选）
            start_time: 开始时间（可选）
            end_time: 结束时间（可选）
            limit: 最大返回条数

        Returns:
            历史数据列表
        """
        with DatabaseConnection(self._db_path) as conn:
            return SensorDataRepository.query_history(
                device_id=device_id,
                start=start_time,
                end=end_time,
                sensor_type=sensor_type,
                limit=limit,
                conn=conn,
            )

    def get_latest_sensor_data(self, device_id: str) -> Optional[Dict[str, Any]]:
        """获取设备最新传感器数据

        Args:
            device_id: 设备ID

        Returns:
            最新传感器数据集合
        """
        # 直接从设备管理器获取（内存中的最新数据）
        dev = self._device_manager.get_device(device_id)
        if not dev:
            return None
        return {
            "device_id": device_id,
            "sensors": dev.get("sensors", {}),
            "collected_at": datetime.now().isoformat(),
        }

    def get_status_history(
        self,
        device_id: str,
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None,
        limit: int = 500,
    ) -> List[Dict[str, Any]]:
        """查询设备状态历史

        Args:
            device_id: 设备ID
            start_time: 开始时间
            end_time: 结束时间
            limit: 最大条数

        Returns:
            状态历史列表
        """
        with DatabaseConnection(self._db_path) as conn:
            return DeviceStatusRepository.query_history(
                device_id=device_id,
                start=start_time,
                end=end_time,
                limit=limit,
                conn=conn,
            )


_instance: DataCollector | None = None


def get_data_collector() -> DataCollector:
    """获取数据采集服务单例

    .. deprecated:: P0-4
        推荐使用 FastAPI 依赖注入 ``Depends(get_data_collector)`` 方式，
        由 lifespan 统一管理实例生命周期。本函数作为向后兼容层保留。
    """
    global _instance
    if _instance is None:
        _instance = DataCollector()
    return _instance
