"""
记忆巩固调度器

使用简单的定时任务机制，在配置的时间点自动触发记忆巩固。
支持 cron 格式的简单子集（分 时 日 月 周），默认为每天凌晨 3 点。

如果系统安装了 APScheduler，则优先使用 APScheduler；
否则使用 threading + time.sleep 的轻量级实现。
"""

from __future__ import annotations

import threading
import time
from datetime import datetime
from typing import Optional

import structlog

logger = structlog.get_logger(__name__)

# 全局调度器实例
_scheduler_instance: Optional["ConsolidationScheduler"] = None
_scheduler_lock = threading.Lock()


class ConsolidationScheduler:
    """
    记忆巩固调度器

    按照 cron 表达式定时触发 ConsolidationEngine 的 consolidate() 方法。
    支持简单的 cron 格式："分 时 日 月 周"（5 字段）。

    实现说明：
    - 优先使用 APScheduler（如果已安装）
    - 回退方案：使用 threading + time.sleep 的轮询实现
    - 每次触发默认执行 full 模式的巩固
    """

    def __init__(self, consolidation_engine, cron_expr: str = "0 3 * * *", mode: str = "full"):
        """
        初始化调度器

        Args:
            consolidation_engine: ConsolidationEngine 实例
            cron_expr: cron 表达式（5 字段格式：分 时 日 月 周），默认 "0 3 * * *"
            mode: 巩固模式（quick/normal/full），默认 "full"
        """
        self._engine = consolidation_engine
        self._cron_expr = cron_expr
        self._mode = mode
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._run_count = 0
        self._last_run_at: Optional[datetime] = None
        self._last_result: Optional[dict] = None

        # 尝试使用 APScheduler
        self._use_apscheduler = False
        self._aps_scheduler = None
        try:
            from apscheduler.schedulers.background import BackgroundScheduler
            from apscheduler.triggers.cron import CronTrigger
            self._aps_scheduler = BackgroundScheduler()
            parts = cron_expr.split()
            if len(parts) == 5:
                trigger = CronTrigger(
                    minute=parts[0],
                    hour=parts[1],
                    day=parts[2],
                    month=parts[3],
                    day_of_week=parts[4],
                )
                self._aps_scheduler.add_job(
                    self._do_consolidate,
                    trigger=trigger,
                    id="consolidation_job",
                    replace_existing=True,
                )
                self._use_apscheduler = True
                logger.info("使用 APScheduler 作为调度器后端")
        except ImportError:
            logger.info("APScheduler 未安装，使用内置轮询调度器")
        except Exception as e:
            logger.warning(f"APScheduler 初始化失败，回退到内置调度器: {e}")

    def start(self) -> None:
        """启动调度器"""
        if self._running:
            return

        self._running = True
        self._stop_event.clear()

        if self._use_apscheduler and self._aps_scheduler:
            self._aps_scheduler.start()
            logger.info(f"巩固调度器已启动（APScheduler），cron: {self._cron_expr}")
        else:
            self._thread = threading.Thread(target=self._run_loop, daemon=True, name="consolidation-scheduler")
            self._thread.start()
            logger.info(f"巩固调度器已启动（内置轮询），cron: {self._cron_expr}")

    def stop(self) -> None:
        """停止调度器"""
        if not self._running:
            return

        self._running = False
        self._stop_event.set()

        if self._use_apscheduler and self._aps_scheduler:
            self._aps_scheduler.shutdown(wait=False)
        elif self._thread:
            self._thread.join(timeout=5)

        logger.info("巩固调度器已停止")

    def _run_loop(self) -> None:
        """主循环（内置轮询实现）"""
        # 解析 cron 表达式
        parts = self._cron_expr.split()
        if len(parts) != 5:
            logger.warning(f"无效的 cron 表达式: {self._cron_expr}，使用默认值 0 3 * * *")
            parts = ["0", "3", "*", "*", "*"]

        minute_expr, hour_expr, day_expr, month_expr, dow_expr = parts

        def _matches(value: int, expr: str, max_val: int) -> bool:
            """检查值是否匹配 cron 字段表达式"""
            if expr == "*":
                return True
            # 支持简单的列表：1,3,5
            if "," in expr:
                values = [int(x) for x in expr.split(",")]
                return value in values
            # 支持范围：1-5
            if "-" in expr and not expr.startswith("*"):
                start, end = expr.split("-")
                return int(start) <= value <= int(end)
            # 单值
            try:
                return value == int(expr)
            except ValueError:
                return True

        last_fired_minute = -1

        while not self._stop_event.is_set():
            now = datetime.now()
            current_minute = now.minute
            current_hour = now.hour
            current_day = now.day
            current_month = now.month
            current_dow = now.weekday()  # 0=周一, 6=周日

            # 检查是否到了触发时间（每分钟检查一次）
            if (
                last_fired_minute != current_minute
                and _matches(current_minute, minute_expr, 59)
                and _matches(current_hour, hour_expr, 23)
                and _matches(current_day, day_expr, 31)
                and _matches(current_month, month_expr, 12)
                and _matches(current_dow, dow_expr, 6)
            ):
                last_fired_minute = current_minute
                try:
                    self._do_consolidate()
                except Exception as e:
                    logger.error(f"定时巩固执行失败: {e}")

            # 每秒检查一次停止信号，每分钟触发一次判断
            for _ in range(60):
                if self._stop_event.is_set():
                    break
                time.sleep(1)

    def _do_consolidate(self) -> None:
        """执行巩固任务"""
        logger.info(f"定时巩固开始（模式: {self._mode}）")
        try:
            result = self._engine.run_consolidation(mode=self._mode)
            self._run_count += 1
            self._last_run_at = datetime.now()
            self._last_result = result
            logger.info(
                f"定时巩固完成: 升级{result.get('promoted', 0)}, "
                f"降级{result.get('demoted', 0)}, "
                f"遗忘{result.get('forgotten', 0)}"
            )
        except Exception as e:
            logger.error(f"定时巩固异常: {e}")
            raise

    @property
    def running(self) -> bool:
        """调度器是否在运行"""
        return self._running

    @property
    def run_count(self) -> int:
        """已执行次数"""
        return self._run_count

    @property
    def last_run_at(self) -> Optional[datetime]:
        """上次执行时间"""
        return self._last_run_at

    @property
    def last_result(self) -> Optional[dict]:
        """上次执行结果"""
        return self._last_result

    def get_status(self) -> dict:
        """获取调度器状态"""
        return {
            "running": self._running,
            "cron": self._cron_expr,
            "mode": self._mode,
            "run_count": self._run_count,
            "last_run_at": self._last_run_at.isoformat() if self._last_run_at else None,
            "last_result": self._last_result,
            "backend": "apscheduler" if self._use_apscheduler else "builtin",
        }


# ============================================================
# 全局调度器管理函数
# ============================================================

def start_scheduler(app_context: dict = None) -> Optional[ConsolidationScheduler]:
    """
    启动全局巩固调度器

    Args:
        app_context: 应用上下文字典，包含 consolidation 和 config

    Returns:
        调度器实例，如果已在运行则返回现有实例
    """
    global _scheduler_instance

    with _scheduler_lock:
        if _scheduler_instance is not None and _scheduler_instance.running:
            return _scheduler_instance

        app_context = app_context or {}
        consolidation = app_context.get("consolidation")
        config = app_context.get("config")

        if consolidation is None:
            logger.warning("未找到巩固引擎实例，调度器未启动")
            return None

        # 从配置读取 cron 表达式
        cron_expr = "0 3 * * *"  # 默认每天凌晨 3 点
        mode = "full"
        if config:
            cron_expr = config.get("memory.consolidation_schedule", cron_expr)
            # 如果配置了巩固模式
            mode = config.get("memory.consolidation_mode", mode)

        _scheduler_instance = ConsolidationScheduler(
            consolidation_engine=consolidation,
            cron_expr=cron_expr,
            mode=mode,
        )
        _scheduler_instance.start()
        return _scheduler_instance


def stop_scheduler() -> None:
    """停止全局巩固调度器"""
    global _scheduler_instance

    with _scheduler_lock:
        if _scheduler_instance is not None:
            _scheduler_instance.stop()
            _scheduler_instance = None


def get_scheduler() -> Optional[ConsolidationScheduler]:
    """获取全局调度器实例"""
    return _scheduler_instance
# vim: set et ts=4 sw=4:
