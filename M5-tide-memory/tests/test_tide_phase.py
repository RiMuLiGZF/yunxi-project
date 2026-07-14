"""
潮汐相位控制器测试

运行: python -m pytest tests/test_tide_phase.py -v
"""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from datetime import datetime, timedelta

import pytest

from tide_memory.core.tide_phase import TidePhaseController, TidePhase


class TestTidePhaseControllerInit:
    """TidePhaseController 初始化测试"""

    def test_init_with_defaults(self):
        """默认参数初始化，自动切换启动"""
        controller = TidePhaseController(auto_switch=True, check_interval=9999)
        try:
            assert controller.current_phase in list(TidePhase)
            assert controller._auto_switch is True
            assert controller._check_interval == 9999
        finally:
            controller.stop()

    def test_init_with_explicit_phase(self):
        """指定初始相位初始化"""
        controller = TidePhaseController(
            initial_phase=TidePhase.FLOOD,
            auto_switch=False,
        )
        assert controller.current_phase == TidePhase.FLOOD
        assert controller._auto_switch is False
        assert controller._running is False

    def test_init_with_custom_schedule(self):
        """自定义时间调度表"""
        custom_schedule = {
            TidePhase.FLOOD: (0, 6),
            TidePhase.RISING: (6, 12),
            TidePhase.SLACK: (12, 18),
            TidePhase.EBB: (18, 24),
        }
        controller = TidePhaseController(
            schedule=custom_schedule,
            auto_switch=False,
        )
        assert controller._schedule is custom_schedule

    def test_init_creates_phase_stats(self):
        """初始化时创建四相统计字典"""
        controller = TidePhaseController(auto_switch=False)
        stats = controller._phase_stats
        for phase in TidePhase:
            assert phase.value in stats
            assert stats[phase.value]["count"] == 0
            assert stats[phase.value]["total_seconds"] == 0.0


class TestTidePhaseIdentification:
    """四相识别测试"""

    def test_all_phases_exist(self):
        """验证四个相位枚举值存在"""
        phases = list(TidePhase)
        assert len(phases) == 4
        assert TidePhase.FLOOD.value == "flood"
        assert TidePhase.RISING.value == "rising"
        assert TidePhase.SLACK.value == "slack"
        assert TidePhase.EBB.value == "ebb"

    def test_compute_phase_returns_tide_phase(self):
        """_compute_phase_for_now 返回 TidePhase 枚举"""
        controller = TidePhaseController(auto_switch=False)
        phase = controller._compute_phase_for_now()
        assert isinstance(phase, TidePhase)


class TestTidePhaseTransition:
    """相位转换逻辑测试"""

    def test_switch_to_same_phase_returns_false(self):
        """切换到当前相位返回 False"""
        controller = TidePhaseController(
            initial_phase=TidePhase.FLOOD,
            auto_switch=False,
        )
        result = controller.switch_to(TidePhase.FLOOD)
        assert result is False
        assert controller.current_phase == TidePhase.FLOOD

    def test_switch_to_different_phase_returns_true(self):
        """切换到不同相位返回 True"""
        controller = TidePhaseController(
            initial_phase=TidePhase.FLOOD,
            auto_switch=False,
        )
        result = controller.switch_to(TidePhase.RISING, reason="test")
        assert result is True
        assert controller.current_phase == TidePhase.RISING
        assert controller._switch_count == 1

    def test_switch_updates_stats(self):
        """切换时更新相位统计"""
        controller = TidePhaseController(
            initial_phase=TidePhase.FLOOD,
            auto_switch=False,
        )
        controller.switch_to(TidePhase.EBB)
        # RISING 的 count 应该被递增（因为是切换目标）
        # 这里用 get_stats 检查
        stats = controller.get_stats()
        assert stats["switch_count"] == 1
        assert stats["current_phase"] == "ebb"


class TestPhaseInfoStructure:
    """get_phase_info 返回值结构测试"""

    def test_get_phase_policy_structure(self):
        """get_phase_policy 返回包含必需键的字典"""
        controller = TidePhaseController(
            initial_phase=TidePhase.FLOOD,
            auto_switch=False,
        )
        policy = controller.get_phase_policy()
        assert "phase" in policy
        assert "description" in policy
        assert "cache" in policy
        assert "search" in policy
        assert "consolidation" in policy
        assert "write" in policy

    def test_flood_policy_values(self):
        """Flood 相位策略值检查"""
        controller = TidePhaseController(
            initial_phase=TidePhase.FLOOD,
            auto_switch=False,
        )
        policy = controller.get_phase_policy()
        assert policy["phase"] == "flood"
        assert policy["cache"]["l0_enabled"] is True
        assert policy["consolidation"]["enabled"] is False

    def test_ebb_policy_values(self):
        """Ebb 相位策略值检查"""
        controller = TidePhaseController(
            initial_phase=TidePhase.EBB,
            auto_switch=False,
        )
        policy = controller.get_phase_policy()
        assert policy["phase"] == "ebb"
        assert policy["cache"]["l0_enabled"] is False
        assert policy["consolidation"]["enabled"] is True
        assert policy["consolidation"]["distill_enabled"] is True


class TestCallbackRegistration:
    """回调注册和触发测试"""

    def test_register_callback(self):
        """注册回调后列表长度增加"""
        controller = TidePhaseController(auto_switch=False)
        initial_count = len(controller._on_phase_change_callbacks)
        controller.on_phase_change(lambda old, new: None)
        assert len(controller._on_phase_change_callbacks) == initial_count + 1

    def test_callback_triggered_on_switch(self):
        """相位切换时触发回调"""
        controller = TidePhaseController(
            initial_phase=TidePhase.FLOOD,
            auto_switch=False,
        )
        triggered_phases = []

        def on_change(old_phase, new_phase):
            triggered_phases.append((old_phase, new_phase))

        controller.on_phase_change(on_change)
        controller.switch_to(TidePhase.RISING)

        assert len(triggered_phases) == 1
        assert triggered_phases[0] == (TidePhase.FLOOD, TidePhase.RISING)

    def test_callback_exception_does_not_break_switch(self):
        """回调异常不阻断相位切换"""
        controller = TidePhaseController(
            initial_phase=TidePhase.FLOOD,
            auto_switch=False,
        )

        def bad_callback(old_phase, new_phase):
            raise RuntimeError("intentional error")

        controller.on_phase_change(bad_callback)
        result = controller.switch_to(TidePhase.EBB)

        assert result is True
        assert controller.current_phase == TidePhase.EBB


class TestGetStats:
    """统计信息测试"""

    def test_get_stats_structure(self):
        """get_stats 返回完整统计结构"""
        controller = TidePhaseController(auto_switch=False)
        stats = controller.get_stats()
        assert "current_phase" in stats
        assert "phase_since" in stats
        assert "current_duration_seconds" in stats
        assert "switch_count" in stats
        assert "auto_switch" in stats
        assert "running" in stats
        assert "phase_policy" in stats
        assert "phase_stats" in stats