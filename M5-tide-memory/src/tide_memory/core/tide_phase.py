"""
潮汐四相循环控制器（基础版）

P2-任务5: 实现记忆系统的生命周期状态管理。

四相定义：
- 潮起 (Flood)：召回活跃期，优先保证检索速度
- 涨潮 (Rising)：写入活跃期，优先保证写入速度
- 平潮 (Slack)：空闲期，可执行巩固、蒸馏等后台任务
- 潮落 (Ebb)：低峰期，执行深度整理、遗忘等重任务

Phase 2 实现：基于时间的相位切换（白天Flood/Rising，夜晚Slack/Ebb）
"""

from __future__ import annotations

import logging
import threading
import time
from datetime import datetime, timedelta
from enum import Enum
from typing import Callable, Dict, Optional

logger = logging.getLogger(__name__)


class TidePhase(str, Enum):
    """潮汐四相"""
    FLOOD = "flood"       # 潮起 - 召回活跃期
    RISING = "rising"     # 涨潮 - 写入活跃期
    SLACK = "slack"       # 平潮 - 空闲期
    EBB = "ebb"           # 潮落 - 低峰期


class TidePhaseController:
    """
    潮汐四相循环控制器（基础版 - 时间驱动）

    根据一天中的时间自动切换相位：
    - 09:00-12:00  Flood 潮起（上午活跃，检索优先）
    - 14:00-18:00 Rising 涨潮（下午活跃，写入优先）
    - 12:00-14:00 Slack 平潮（午间空闲，轻量巩固）
    - 22:00-06:00 Ebb 潮落（夜间低峰，深度整理）
    - 其余时间   Slack 平潮

    相位策略：
    - Flood 潮起：L0 缓存全开，检索超时短，跳过巩固
    - Rising 涨潮：写入批处理，L1 同步持久化
    - Slack 平潮：正常巩固，轻量蒸馏
    - Ebb 潮落：深度巩固，全量遗忘，语义蒸馏
    """

    # 默认时间配置（24小时制）
    _DEFAULT_SCHEDULE = {
        TidePhase.FLOOD:   (9, 12),    # 09:00-12:00
        TidePhase.RISING:  (14, 18),   # 14:00-18:00
        TidePhase.SLACK:   [(12, 14), (18, 22), (6, 9)],  # 多个平潮时段
        TidePhase.EBB:     (22, 6),    # 22:00-06:00（跨天）
    }

    def __init__(
        self,
        schedule: Dict = None,
        initial_phase: Optional[TidePhase] = None,
        auto_switch: bool = True,
        check_interval: int = 60,  # 检查相位切换的间隔（秒）
    ):
        """
        初始化潮汐相位控制器

        Args:
            schedule: 自定义时间调度表，格式同 _DEFAULT_SCHEDULE
            initial_phase: 初始相位，None 则根据当前时间计算
            auto_switch: 是否自动切换相位
            check_interval: 自动检查间隔（秒）
        """
        self._schedule = schedule or self._DEFAULT_SCHEDULE
        self._auto_switch = auto_switch
        self._check_interval = check_interval

        # 当前相位
        self._current_phase: TidePhase = initial_phase or self._compute_phase_for_now()
        self._phase_since: datetime = datetime.now()

        # 相位切换回调
        self._on_phase_change_callbacks: list = []

        # 统计信息
        self._phase_stats: Dict[str, Dict] = {
            phase.value: {"count": 0, "total_seconds": 0.0}
            for phase in TidePhase
        }
        self._switch_count: int = 0

        # 自动切换线程
        self._running: bool = False
        self._thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._lock = threading.Lock()

        # 启动自动切换
        if self._auto_switch:
            self.start()

    # ============================================================
    # 相位计算
    # ============================================================

    def _compute_phase_for_now(self) -> TidePhase:
        """根据当前时间计算应该处于的相位"""
        now = datetime.now()
        current_hour = now.hour + now.minute / 60.0

        # 按优先级检查：Ebb > Flood > Rising > Slack
        # Ebb（跨天，单独处理）
        ebb_start, ebb_end = self._schedule.get(TidePhase.EBB, (22, 6))
        if ebb_start > ebb_end:  # 跨天，如 22:00-06:00
            if current_hour >= ebb_start or current_hour < ebb_end:
                return TidePhase.EBB
        else:
            if ebb_start <= current_hour < ebb_end:
                return TidePhase.EBB

        # Flood
        flood_start, flood_end = self._schedule.get(TidePhase.FLOOD, (9, 12))
        if flood_start <= current_hour < flood_end:
            return TidePhase.FLOOD

        # Rising
        rising_start, rising_end = self._schedule.get(TidePhase.RISING, (14, 18))
        if rising_start <= current_hour < rising_end:
            return TidePhase.RISING

        # 其余时间都是 Slack
        return TidePhase.SLACK

    # ============================================================
    # 自动切换
    # ============================================================

    def start(self) -> None:
        """启动自动相位切换"""
        if self._running:
            return

        self._running = True
        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._auto_switch_loop,
            daemon=True,
            name="tide-phase-controller",
        )
        self._thread.start()
        logger.info(f"潮汐相位控制器已启动，当前相位: {self._current_phase.value}")

    def stop(self) -> None:
        """停止自动相位切换"""
        if not self._running:
            return

        self._running = False
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=5)
        logger.info("潮汐相位控制器已停止")

    def _auto_switch_loop(self) -> None:
        """自动切换主循环"""
        while not self._stop_event.is_set():
            try:
                expected_phase = self._compute_phase_for_now()
                if expected_phase != self._current_phase:
                    self.switch_to(expected_phase, reason="time_based")
            except Exception as e:
                logger.warning(f"相位切换检查失败: {e}")

            # 等待下一次检查
            self._stop_event.wait(self._check_interval)

    # ============================================================
    # 手动切换
    # ============================================================

    def switch_to(self, phase: TidePhase, reason: str = "manual") -> bool:
        """
        手动切换到指定相位

        Args:
            phase: 目标相位
            reason: 切换原因

        Returns:
            是否成功切换（如果已经是该相位返回 False）
        """
        with self._lock:
            if phase == self._current_phase:
                return False

            old_phase = self._current_phase
            self._current_phase = phase

            # 更新统计
            now = datetime.now()
            duration = (now - self._phase_since).total_seconds()
            self._phase_stats[old_phase.value]["total_seconds"] += duration
            self._phase_stats[phase.value]["count"] += 1
            self._phase_since = now
            self._switch_count += 1

            logger.info(
                f"相位切换: {old_phase.value} → {phase.value} "
                f"(原因: {reason}, 持续: {duration:.0f}s)"
            )

            # 触发回调
            for callback in self._on_phase_change_callbacks:
                try:
                    callback(old_phase, phase)
                except Exception as e:
                    logger.warning(f"相位切换回调执行失败: {e}")

            return True

    # ============================================================
    # 相位策略查询
    # ============================================================

    @property
    def current_phase(self) -> TidePhase:
        """当前相位"""
        return self._current_phase

    def get_phase_policy(self) -> Dict:
        """
        获取当前相位的策略配置

        Returns:
            策略字典，包含各模块的行为调整参数
        """
        phase = self._current_phase

        if phase == TidePhase.FLOOD:
            return {
                "phase": "flood",
                "description": "潮起 - 召回活跃期，优先保证检索速度",
                "cache": {
                    "l0_enabled": True,
                    "l0_max_items": 200,  # L0 缓存扩容
                    "preload_enabled": True,
                },
                "search": {
                    "timeout_ms": 500,       # 检索超时短
                    "top_k_expand": 2,       # 扩大召回范围
                },
                "consolidation": {
                    "enabled": False,        # 跳过巩固
                    "mode": "none",
                },
                "write": {
                    "batch_size": 10,        # 小批量写入
                    "async_write": True,     # 异步写入
                },
            }

        elif phase == TidePhase.RISING:
            return {
                "phase": "rising",
                "description": "涨潮 - 写入活跃期，优先保证写入速度",
                "cache": {
                    "l0_enabled": True,
                    "l0_max_items": 100,
                    "preload_enabled": False,
                },
                "search": {
                    "timeout_ms": 2000,
                    "top_k_expand": 1,
                },
                "consolidation": {
                    "enabled": False,
                    "mode": "none",
                },
                "write": {
                    "batch_size": 100,       # 大批量写入
                    "async_write": True,     # 异步写入
                    "l1_sync": True,         # L1 同步持久化
                },
            }

        elif phase == TidePhase.SLACK:
            return {
                "phase": "slack",
                "description": "平潮 - 空闲期，可执行巩固、蒸馏等后台任务",
                "cache": {
                    "l0_enabled": True,
                    "l0_max_items": 100,
                    "preload_enabled": True,
                },
                "search": {
                    "timeout_ms": 2000,
                    "top_k_expand": 1,
                },
                "consolidation": {
                    "enabled": True,
                    "mode": "quick",         # 快速巩固
                    "distill_enabled": False,  # 轻量，不做蒸馏
                },
                "write": {
                    "batch_size": 50,
                    "async_write": False,
                },
            }

        else:  # EBB
            return {
                "phase": "ebb",
                "description": "潮落 - 低峰期，执行深度整理、遗忘等重任务",
                "cache": {
                    "l0_enabled": False,      # 关闭 L0 缓存（省电/省内存）
                    "l0_max_items": 10,
                    "preload_enabled": False,
                },
                "search": {
                    "timeout_ms": 5000,       # 检索可慢一些
                    "top_k_expand": 1,
                },
                "consolidation": {
                    "enabled": True,
                    "mode": "full",           # 完整巩固
                    "distill_enabled": True,  # 语义蒸馏
                    "forget_enabled": True,   # 全量遗忘
                },
                "write": {
                    "batch_size": 200,
                    "async_write": False,
                },
            }

    # ============================================================
    # 回调注册
    # ============================================================

    def on_phase_change(self, callback: Callable[[TidePhase, TidePhase], None]) -> None:
        """
        注册相位切换回调

        Args:
            callback: 回调函数，参数为 (old_phase, new_phase)
        """
        self._on_phase_change_callbacks.append(callback)

    # ============================================================
    # 统计信息
    # ============================================================

    def get_stats(self) -> Dict:
        """
        获取控制器统计信息

        Returns:
            统计字典
        """
        with self._lock:
            # 更新当前相位的持续时间
            now = datetime.now()
            current_duration = (now - self._phase_since).total_seconds()
            stats_copy = {
                "current_phase": self._current_phase.value,
                "phase_since": self._phase_since.isoformat(),
                "current_duration_seconds": round(current_duration, 1),
                "switch_count": self._switch_count,
                "auto_switch": self._auto_switch,
                "running": self._running,
                "phase_policy": self.get_phase_policy(),
                "phase_stats": {},
            }

            # 复制各相位统计（加上当前相位的当前持续时间）
            for phase in TidePhase:
                phase_stat = dict(self._phase_stats[phase.value])
                if phase == self._current_phase:
                    phase_stat["total_seconds"] = round(
                        phase_stat["total_seconds"] + current_duration, 1
                    )
                stats_copy["phase_stats"][phase.value] = phase_stat

            return stats_copy

    # ============================================================
    # 下一相位预测
    # ============================================================

    def get_next_phase(self) -> Dict:
        """
        获取下一个相位及切换时间

        Returns:
            {"phase": 下一个相位, "switch_at": 切换时间}
        """
        now = datetime.now()
        current_hour = now.hour + now.minute / 60.0

        # 找到今天中接下来最近的相位切换点
        phases_today = []

        # 收集所有相位的开始时间点
        for phase, time_range in self._schedule.items():
            if isinstance(time_range, list):
                for start, _ in time_range:
                    phases_today.append((start, phase))
            else:
                start, _ = time_range
                phases_today.append((start, phase))

        # 按时间排序
        phases_today.sort(key=lambda x: x[0])

        # 找到下一个
        for hour, phase in phases_today:
            if hour > current_hour:
                switch_time = now.replace(
                    hour=int(hour),
                    minute=int((hour % 1) * 60),
                    second=0,
                    microsecond=0,
                )
                return {
                    "phase": phase.value,
                    "switch_at": switch_time.isoformat(),
                    "seconds_until": int((switch_time - now).total_seconds()),
                }

        # 今天没有了，明天第一个
        first_hour, first_phase = phases_today[0]
        tomorrow = now + timedelta(days=1)
        switch_time = tomorrow.replace(
            hour=int(first_hour),
            minute=int((first_hour % 1) * 60),
            second=0,
            microsecond=0,
        )
        return {
            "phase": first_phase.value,
            "switch_at": switch_time.isoformat(),
            "seconds_until": int((switch_time - now).total_seconds()),
        }

    def __del__(self):
        """析构时停止"""
        try:
            self.stop()
        except Exception:
            pass
# vim: set et ts=4 sw=4:
