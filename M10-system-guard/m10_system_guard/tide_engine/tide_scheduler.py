"""
潮汐调度器

整合潮汐状态机、预测器和 GPU 编排器，提供统一的调度接口。
后台线程持续监测资源状态，自动调整潮汐阶段。
"""

from __future__ import annotations

import time
import threading
from typing import Optional, Dict, List, Any

import structlog

from .models import (
    TidePhase,
    TideSnapshot,
    TideStrategy,
    TidePrediction,
    GPUMission,
    TideStats,
)
from .tide_state import TideStateMachine
from .tide_predictor import TidePredictor
from .gpu_orchestrator import GPUOrchestrator

logger = structlog.get_logger(__name__)


class TideScheduler:
    """潮汐调度器

    整合所有潮汐组件，提供统一调度接口。
    """

    def __init__(self, strategy: Optional[TideStrategy] = None):
        self._strategy = strategy or TideStrategy()
        self._state_machine = TideStateMachine(self._strategy)
        self._predictor = TidePredictor(self._strategy)
        self._gpu_orchestrator = GPUOrchestrator(self._strategy)

        self._running = False
        self._monitor_thread: Optional[threading.Thread] = None
        self._poll_interval_sec: float = 2.0

        # 资源获取回调
        self._resource_callback = None

        # 阶段变化回调
        self._phase_change_callbacks = []

        # 统计
        self._stats = TideStats()
        self._phase_start_time: float = time.time()
        self._stats.phase_time_distribution = {
            TidePhase.FLOOD.value: 0.0,
            TidePhase.SLACK.value: 0.0,
            TidePhase.EBB.value: 0.0,
            TidePhase.LOW.value: 0.0,
        }

        self._lock = threading.Lock()

    # ============================================================
    # 生命周期
    # ============================================================

    def start(self, resource_callback=None, poll_interval_sec: float = 2.0):
        """启动潮汐调度器

        Args:
            resource_callback: 回调函数，返回 (gpu_mem_pct, gpu_util_pct, cpu_pct, mem_pct)
            poll_interval_sec: 轮询间隔（秒）
        """
        if self._running:
            return

        self._resource_callback = resource_callback
        self._poll_interval_sec = poll_interval_sec
        self._running = True
        self._phase_start_time = time.time()

        self._monitor_thread = threading.Thread(
            target=self._monitor_loop,
            daemon=True,
            name="tide-scheduler",
        )
        self._monitor_thread.start()

        logger.info("潮汐调度器已启动")

    def stop(self):
        """停止潮汐调度器"""
        self._running = False
        if self._monitor_thread:
            self._monitor_thread.join(timeout=5.0)
        logger.info("潮汐调度器已停止")

    # ============================================================
    # 监控循环
    # ============================================================

    def _monitor_loop(self):
        """后台监控循环"""
        while self._running:
            try:
                self._tick()
            except Exception as e:
                logger.error(f"潮汐调度器监控循环异常: {e}")

            time.sleep(self._poll_interval_sec)

    def _tick(self):
        """一次调度周期"""
        # 1. 获取资源数据
        if self._resource_callback:
            try:
                gpu_mem, gpu_util, cpu, mem = self._resource_callback()
            except Exception:
                gpu_mem, gpu_util, cpu, mem = 0.0, 0.0, 0.0, 0.0
        else:
            gpu_mem, gpu_util, cpu, mem = 0.0, 0.0, 0.0, 0.0

        # 2. 更新状态机
        old_phase = self._state_machine.current_phase
        snapshot = self._state_machine.update(gpu_mem, gpu_util, cpu, mem)
        new_phase = snapshot.phase

        # 3. 更新阶段时间统计
        now = time.time()
        elapsed = now - self._phase_start_time
        with self._lock:
            self._stats.phase_time_distribution[old_phase.value] += elapsed
            self._phase_start_time = now

        # 4. 阶段变化时触发回调
        if new_phase != old_phase:
            with self._lock:
                self._stats.phase_transition_count += 1

            self._gpu_orchestrator.update_phase(new_phase)

            for callback in self._phase_change_callbacks:
                try:
                    callback(old_phase, new_phase, snapshot)
                except Exception as e:
                    logger.error(f"潮汐阶段回调异常: {e}")

        # 5. 预测（每 10 个 tick 预测一次）
        if self._strategy.prediction_enabled:
            # 简化：每次都更新预测
            level_history = self._state_machine.get_level_history(
                limit=self._strategy.prediction_samples
            )
            prediction = self._predictor.predict(
                level_history,
                horizon_minutes=self._strategy.prediction_window_minutes,
            )
            snapshot.predicted_phase_5min = prediction.predicted_phases.get(5)
            snapshot.predicted_phase_15min = prediction.predicted_phases.get(15)
            snapshot.predicted_phase_30min = prediction.predicted_phases.get(30)

        # 6. 更新 GPU 编排器的设备信息（如果有回调）
        if hasattr(self._resource_callback, 'get_gpu_devices'):
            try:
                devices = self._resource_callback.get_gpu_devices()
                self._gpu_orchestrator.set_gpu_devices(devices)
            except Exception:
                pass

    # ============================================================
    # 任务管理
    # ============================================================

    def submit_mission(self, mission: GPUMission) -> str:
        """提交 GPU 任务"""
        return self._gpu_orchestrator.submit_mission(mission)

    def complete_mission(self, mission_id: str, success: bool = True, result: Dict = None, error: str = ""):
        """完成 GPU 任务"""
        self._gpu_orchestrator.complete_mission(mission_id, success, result, error)

    def cancel_mission(self, mission_id: str) -> bool:
        """取消任务"""
        return self._gpu_orchestrator.cancel_mission(mission_id)

    # ============================================================
    # 查询接口
    # ============================================================

    @property
    def current_phase(self) -> TidePhase:
        return self._state_machine.current_phase

    def get_snapshot(self) -> TideSnapshot:
        """获取当前潮汐快照"""
        history = self._state_machine.get_snapshot_history(limit=1)
        if history:
            return history[-1]
        return TideSnapshot()

    def get_history(self, limit: int = 30) -> List[TideSnapshot]:
        """获取历史快照"""
        return self._state_machine.get_snapshot_history(limit=limit)

    def get_prediction(self) -> Optional[TidePrediction]:
        """获取最新预测"""
        if not self._strategy.prediction_enabled:
            return None
        level_history = self._state_machine.get_level_history(
            limit=self._strategy.prediction_samples
        )
        return self._predictor.predict(
            level_history,
            horizon_minutes=self._strategy.prediction_window_minutes,
        )

    def get_mission(self, mission_id: str) -> Optional[GPUMission]:
        return self._gpu_orchestrator.get_mission(mission_id)

    def list_missions(self, status: str = None, limit: int = 20) -> List[GPUMission]:
        """列出任务"""
        if status == "pending":
            return self._gpu_orchestrator.list_pending(limit)
        elif status == "running":
            return self._gpu_orchestrator.list_running(limit)
        elif status == "completed":
            return self._gpu_orchestrator.list_completed(limit)
        else:
            # 全部
            result = []
            result.extend(self._gpu_orchestrator.list_running(limit))
            remaining = limit - len(result)
            if remaining > 0:
                result.extend(self._gpu_orchestrator.list_pending(remaining))
            remaining = limit - len(result)
            if remaining > 0:
                result.extend(self._gpu_orchestrator.list_completed(remaining))
            return result

    def get_stats(self) -> Dict[str, Any]:
        """获取统计信息"""
        gpu_stats = self._gpu_orchestrator.get_stats()
        tide_stats = self._stats.to_dict()
        return {
            "tide": tide_stats,
            "gpu_orchestrator": gpu_stats,
            "current_phase": self._state_machine.current_phase.value,
            "current_trend": self._state_machine.current_trend.value,
            "resource_level": self._state_machine.current_level,
        }

    # ============================================================
    # 策略管理
    # ============================================================

    def update_strategy(self, strategy: TideStrategy):
        """更新调度策略"""
        self._strategy = strategy
        self._state_machine.update_strategy(strategy)
        self._predictor.update_strategy(strategy)
        self._gpu_orchestrator.update_strategy(strategy)

    def get_strategy(self) -> TideStrategy:
        return self._strategy

    def register_phase_change_callback(self, callback):
        """注册阶段变化回调"""
        self._phase_change_callbacks.append(callback)

    # ============================================================
    # 手动控制
    # ============================================================

    def manual_set_phase(self, phase: TidePhase):
        """手动设置潮汐阶段（调试用）"""
        # 直接触发状态机更新到目标阶段
        # 这是一个简化实现，通过模拟水位实现
        if phase == TidePhase.FLOOD:
            level = self._strategy.flood_threshold - 10
        elif phase == TidePhase.SLACK:
            level = (self._strategy.flood_threshold + self._strategy.ebb_threshold) / 2
        elif phase == TidePhase.EBB:
            level = (self._strategy.ebb_threshold + self._strategy.low_threshold) / 2
        else:  # LOW
            level = self._strategy.low_threshold + 5

        # 连续更新几次以通过滞回
        for _ in range(10):
            self._state_machine.update(level, level, 0, 0)
