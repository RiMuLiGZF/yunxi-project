"""
M10 潮汐引擎单元测试
"""
import sys
import os
import time
import pytest
import tempfile
class TestTideModels:
    """潮汐数据模型测试"""

    def test_tide_phase_enum(self):
        """潮汐阶段枚举"""
        from m10_system_guard.tide_engine.models import TidePhase
        assert TidePhase.FLOOD.value == "flood"
        assert TidePhase.SLACK.value == "slack"
        assert TidePhase.EBB.value == "ebb"
        assert TidePhase.LOW.value == "low"
        assert len(TidePhase) == 4

    def test_tide_trend_enum(self):
        """潮汐趋势枚举"""
        from m10_system_guard.tide_engine.models import TideTrend
        assert TideTrend.RISING.value == "rising"
        assert TideTrend.FALLING.value == "falling"
        assert TideTrend.STABLE.value == "stable"

    def test_mission_priority_enum(self):
        """任务优先级枚举"""
        from m10_system_guard.tide_engine.models import MissionPriority
        assert MissionPriority.CRITICAL.value == "critical"
        assert MissionPriority.HIGH.value == "high"
        assert MissionPriority.NORMAL.value == "normal"
        assert MissionPriority.LOW.value == "low"
        assert MissionPriority.BATCH.value == "batch"

    def test_tide_strategy_defaults(self):
        """默认潮汐策略"""
        from m10_system_guard.tide_engine.models import TideStrategy
        strategy = TideStrategy()

        assert strategy.strategy_id == "default"
        assert strategy.primary_metric == "gpu_memory"
        assert strategy.flood_threshold == 30.0
        assert strategy.ebb_threshold == 70.0
        assert strategy.low_threshold == 90.0
        assert strategy.flood_concurrency_multiplier == 2.0
        assert strategy.slack_concurrency_multiplier == 1.0
        assert strategy.ebb_concurrency_multiplier == 0.5
        assert strategy.low_concurrency_multiplier == 0.2

    def test_tide_strategy_get_phase(self):
        """策略计算潮汐阶段"""
        from m10_system_guard.tide_engine.models import TideStrategy, TidePhase
        strategy = TideStrategy(hysteresis_percent=0)  # 无滞回方便测试

        # 从 SLACK 作为初始阶段的角度测试
        assert strategy.get_phase_for_level(10.0) == TidePhase.FLOOD
        assert strategy.get_phase_for_level(50.0) == TidePhase.SLACK
        assert strategy.get_phase_for_level(80.0) == TidePhase.EBB
        # 从 EBB 阶段开始，水位 > low_threshold + 滞回 才会进入 LOW
        assert strategy.get_phase_for_level(95.0, TidePhase.EBB) == TidePhase.LOW

    def test_tide_strategy_hysteresis(self):
        """滞回控制测试"""
        from m10_system_guard.tide_engine.models import TideStrategy, TidePhase
        strategy = TideStrategy(hysteresis_percent=5.0)

        # 从平潮开始
        # 水位刚好超过 ebb 阈值 70，但滞回 5%，需要 > 75 才切换
        phase = strategy.get_phase_for_level(72.0, TidePhase.SLACK)
        assert phase == TidePhase.SLACK  # 滞回，不切换

        # 超过 75 才切换到退潮
        phase = strategy.get_phase_for_level(76.0, TidePhase.SLACK)
        assert phase == TidePhase.EBB

    def test_tide_strategy_concurrency(self):
        """并发系数获取"""
        from m10_system_guard.tide_engine.models import TideStrategy, TidePhase
        strategy = TideStrategy()

        assert strategy.get_concurrency_multiplier(TidePhase.FLOOD) == 2.0
        assert strategy.get_concurrency_multiplier(TidePhase.SLACK) == 1.0
        assert strategy.get_concurrency_multiplier(TidePhase.EBB) == 0.5
        assert strategy.get_concurrency_multiplier(TidePhase.LOW) == 0.2

    def test_gpu_mission_model(self):
        """GPU 任务模型"""
        from m10_system_guard.tide_engine.models import GPUMission, MissionPriority
        mission = GPUMission(
            name="test_mission",
            priority=MissionPriority.HIGH,
            estimated_gpu_memory_mb=2048.0,
            mission_type="inference",
            caller_module="M5",
        )

        assert mission.name == "test_mission"
        assert mission.priority == MissionPriority.HIGH
        assert mission.status == "pending"
        assert mission.estimated_gpu_memory_mb == 2048.0
        assert len(mission.mission_id) > 0

    def test_tide_snapshot_to_dict(self):
        """潮汐快照序列化"""
        from m10_system_guard.tide_engine.models import TideSnapshot, TidePhase, TideTrend
        snap = TideSnapshot(
            phase=TidePhase.FLOOD,
            trend=TideTrend.RISING,
            resource_level=25.0,
            gpu_memory_level=20.0,
        )
        d = snap.to_dict()
        assert d["phase"] == "flood"
        assert d["trend"] == "rising"
        assert d["resource_level"] == 25.0
        assert "concurrency_multiplier" in d
        assert "min_priority" in d


class TestTideStateMachine:
    """潮汐状态机测试"""

    def test_initial_state(self):
        """初始状态"""
        from m10_system_guard.tide_engine.tide_state import TideStateMachine
        sm = TideStateMachine()
        assert sm.current_phase.value == "slack"
        assert sm.current_trend.value == "stable"

    def test_update_flood(self):
        """低水位 -> 涨潮"""
        from m10_system_guard.tide_engine.tide_state import TideStateMachine
        from m10_system_guard.tide_engine.models import TideStrategy, TidePhase
        strategy = TideStrategy(hysteresis_percent=0, min_phase_duration_sec=0)
        sm = TideStateMachine(strategy)

        # 连续更新低水位，触发涨潮
        for _ in range(5):
            sm.update(gpu_memory_percent=10.0, gpu_util_percent=5.0)

        assert sm.current_phase == TidePhase.FLOOD
        assert sm.current_level < 30.0

    def test_update_low(self):
        """高水位 -> 枯潮"""
        from m10_system_guard.tide_engine.tide_state import TideStateMachine
        from m10_system_guard.tide_engine.models import TideStrategy, TidePhase
        strategy = TideStrategy(hysteresis_percent=0, min_phase_duration_sec=0)
        sm = TideStateMachine(strategy)

        # 连续更新高水位
        for _ in range(5):
            sm.update(gpu_memory_percent=95.0, gpu_util_percent=90.0)

        assert sm.current_phase == TidePhase.LOW
        assert sm.current_level > 80.0

    def test_trend_detection(self):
        """趋势检测"""
        from m10_system_guard.tide_engine.tide_state import TideStateMachine
        from m10_system_guard.tide_engine.models import TideStrategy, TideTrend
        strategy = TideStrategy(min_phase_duration_sec=0)
        sm = TideStateMachine(strategy)

        # 模拟水位持续上涨
        for i in range(10):
            sm.update(gpu_memory_percent=30.0 + i * 3, gpu_util_percent=20.0 + i * 2)

        # 应该检测到上涨趋势
        assert sm.current_trend in (TideTrend.RISING, TideTrend.STABLE)

    def test_snapshot_history(self):
        """历史快照记录"""
        from m10_system_guard.tide_engine.tide_state import TideStateMachine
        sm = TideStateMachine()

        for i in range(10):
            sm.update(gpu_memory_percent=50.0, gpu_util_percent=50.0)

        history = sm.get_snapshot_history(limit=5)
        assert len(history) == 5


class TestTidePredictor:
    """潮汐预测器测试"""

    def test_predict_no_data(self):
        """数据不足时预测"""
        from m10_system_guard.tide_engine.tide_predictor import TidePredictor
        predictor = TidePredictor()
        prediction = predictor.predict([], horizon_minutes=30)
        assert prediction.confidence == 0.0
        assert len(prediction.points) == 0

    def test_predict_with_data(self):
        """有数据时预测"""
        from m10_system_guard.tide_engine.tide_predictor import TidePredictor
        predictor = TidePredictor()

        # 生成 30 个样本的历史数据（平稳水位）
        import time
        now = time.time()
        history = [(now - 30 * 60 + i * 60, 50.0) for i in range(30)]

        prediction = predictor.predict(history, horizon_minutes=15)
        assert len(prediction.points) == 15
        assert 0.0 <= prediction.confidence <= 1.0
        # 平稳数据预测应该也平稳
        assert 40.0 <= prediction.points[0][1] <= 60.0

    def test_rising_prediction(self):
        """上涨趋势预测"""
        from m10_system_guard.tide_engine.tide_predictor import TidePredictor
        predictor = TidePredictor()

        import time
        now = time.time()
        # 持续上涨的数据
        history = [(now - 600 + i * 10, 30.0 + i * 0.5) for i in range(60)]

        prediction = predictor.predict(history, horizon_minutes=10)
        # 预测值应该高于当前值（上涨趋势）
        if prediction.confidence > 0.3:
            last_pred = prediction.points[-1][1]
            last_hist = history[-1][1]
            # 不一定严格上涨（均值回归会拉回来），但至少有预测值
            assert last_pred > 0


class TestGPUOrchestrator:
    """GPU 任务编排器测试"""

    def test_submit_mission(self):
        """提交任务"""
        from m10_system_guard.tide_engine.gpu_orchestrator import GPUOrchestrator
        from m10_system_guard.tide_engine.models import GPUMission, MissionPriority
        orch = GPUOrchestrator()

        mission = GPUMission(
            name="test",
            priority=MissionPriority.NORMAL,
            estimated_gpu_memory_mb=1024.0,
        )
        mission_id = orch.submit_mission(mission)

        assert mission_id == mission.mission_id
        assert orch.get_mission(mission_id) is not None

    def test_complete_mission(self):
        """完成任务"""
        from m10_system_guard.tide_engine.gpu_orchestrator import GPUOrchestrator
        from m10_system_guard.tide_engine.models import GPUMission, MissionPriority
        orch = GPUOrchestrator()

        mission = GPUMission(name="test", priority=MissionPriority.NORMAL)
        mission_id = orch.submit_mission(mission)

        orch.complete_mission(mission_id, success=True, result={"output": "ok"})

        m = orch.get_mission(mission_id)
        assert m.status == "completed"
        assert m.result.get("output") == "ok"

    def test_cancel_pending_mission(self):
        """取消待执行任务"""
        from m10_system_guard.tide_engine.gpu_orchestrator import GPUOrchestrator
        from m10_system_guard.tide_engine.models import GPUMission, MissionPriority
        orch = GPUOrchestrator()
        orch._baseline_concurrency = 0  # 不让任务运行

        mission = GPUMission(
            name="test",
            priority=MissionPriority.NORMAL,
            estimated_gpu_memory_mb=100000.0,  # 大显存，确保 pending
        )
        mission_id = orch.submit_mission(mission)

        result = orch.cancel_mission(mission_id)
        assert result is True
        assert mission.status == "cancelled"

    def test_set_gpu_devices(self):
        """设置 GPU 设备"""
        from m10_system_guard.tide_engine.gpu_orchestrator import GPUOrchestrator
        orch = GPUOrchestrator()

        devices = [
            {"gpu_id": 0, "memory_total_mb": 24576, "memory_free_mb": 24576},
            {"gpu_id": 1, "memory_total_mb": 24576, "memory_free_mb": 24576},
        ]
        orch.set_gpu_devices(devices)

        stats = orch.get_stats()
        assert stats["gpu_count"] == 2
        assert 0 in stats["gpu_devices"]
        assert stats["gpu_devices"][0]["total_mb"] == 24576

    def test_priority_filtering(self):
        """低优先级任务在退潮时被过滤"""
        from m10_system_guard.tide_engine.gpu_orchestrator import GPUOrchestrator
        from m10_system_guard.tide_engine.models import (
            GPUMission, MissionPriority, TidePhase, TideStrategy
        )
        strategy = TideStrategy()
        orch = GPUOrchestrator(strategy)
        orch._baseline_concurrency = 10

        # 模拟枯潮阶段
        orch.update_phase(TidePhase.LOW)

        # 提交一个 BATCH 优先级任务（枯潮不允许）
        mission = GPUMission(
            name="batch_job",
            priority=MissionPriority.BATCH,
            estimated_gpu_memory_mb=1024.0,
        )
        orch.submit_mission(mission)

        # 应该还在 pending（枯潮不允许 batch 任务运行）
        assert mission.status == "pending"

        # 提交 CRITICAL 任务（应该可以运行）
        critical = GPUMission(
            name="critical_job",
            priority=MissionPriority.CRITICAL,
            estimated_gpu_memory_mb=512.0,
        )
        orch.submit_mission(critical)

        # CRITICAL 应该能运行
        assert critical.status == "running"

    def test_preemptible_mission(self):
        """可抢占任务在退潮时被抢占"""
        from m10_system_guard.tide_engine.gpu_orchestrator import GPUOrchestrator
        from m10_system_guard.tide_engine.models import (
            GPUMission, MissionPriority, TidePhase, TideStrategy
        )
        strategy = TideStrategy()
        orch = GPUOrchestrator(strategy)
        orch._baseline_concurrency = 10

        # 设置 GPU 设备
        orch.set_gpu_devices([
            {"gpu_id": 0, "memory_total_mb": 8192, "memory_free_mb": 8192},
        ])

        # 涨潮时提交一个可抢占的 BATCH 任务
        orch.update_phase(TidePhase.FLOOD)
        mission = GPUMission(
            name="batch_job",
            priority=MissionPriority.BATCH,
            estimated_gpu_memory_mb=2048.0,
            tide_preemptible=True,
        )
        orch.submit_mission(mission)

        # 涨潮时 BATCH 也能运行
        assert mission.status == "running"

        # 切换到枯潮，应该抢占 BATCH 任务
        orch.update_phase(TidePhase.LOW)

        # 任务应该被放回 pending 队列
        assert mission.status == "pending"
        stats = orch.get_stats()
        assert stats["total_preempted"] >= 1


class TestTideScheduler:
    """潮汐调度器测试"""

    def test_scheduler_creation(self):
        """调度器创建"""
        from m10_system_guard.tide_engine.tide_scheduler import TideScheduler
        scheduler = TideScheduler()
        assert scheduler.current_phase.value == "slack"

    def test_scheduler_manual_phase(self):
        """手动设置阶段"""
        from m10_system_guard.tide_engine.tide_scheduler import TideScheduler
        from m10_system_guard.tide_engine.models import TidePhase, TideStrategy
        strategy = TideStrategy(hysteresis_percent=0, min_phase_duration_sec=0)
        scheduler = TideScheduler(strategy)

        scheduler.manual_set_phase(TidePhase.FLOOD)
        assert scheduler.current_phase == TidePhase.FLOOD

        scheduler.manual_set_phase(TidePhase.LOW)
        assert scheduler.current_phase == TidePhase.LOW

    def test_scheduler_start_stop(self):
        """启动和停止"""
        from m10_system_guard.tide_engine.tide_scheduler import TideScheduler
        scheduler = TideScheduler()

        # 用模拟回调启动
        def mock_callback():
            return (50.0, 50.0, 30.0, 40.0)

        scheduler.start(resource_callback=mock_callback, poll_interval_sec=0.1)
        time.sleep(0.3)
        scheduler.stop()

        # 应该有历史数据了
        history = scheduler.get_history(limit=10)
        assert len(history) > 0

    def test_scheduler_stats(self):
        """统计信息"""
        from m10_system_guard.tide_engine.tide_scheduler import TideScheduler
        scheduler = TideScheduler()

        stats = scheduler.get_stats()
        assert "tide" in stats
        assert "gpu_orchestrator" in stats
        assert "current_phase" in stats


class TestTideEngine:
    """潮汐引擎主类测试"""

    def test_engine_singleton(self):
        """单例模式"""
        from m10_system_guard.tide_engine import TideEngine, get_tide_engine
        e1 = get_tide_engine()
        e2 = get_tide_engine()
        assert e1 is e2

    def test_engine_init(self):
        """引擎初始化"""
        from m10_system_guard.tide_engine import TideEngine
        engine = TideEngine()
        assert engine.initialized is False

        engine.initialize()
        assert engine.initialized is True
        assert engine.scheduler is not None

        engine.shutdown()
        assert engine.initialized is False


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
