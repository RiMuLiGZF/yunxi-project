"""
向后兼容性测试

测试覆盖:
- perf 模块入口 API 可用性
- 与现有 shared.data.cache 的兼容性
- 与现有 shared.data.data_layer.query_optimizer 的兼容性
- 与现有 shared.core.performance_utils 的兼容性
- 默认开启但不强制
- 不影响现有业务逻辑
"""

import sys
import pytest
from pathlib import Path

_project_root = Path(__file__).resolve().parents[3]
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))


# ============================================================
# 模块导入测试
# ============================================================

class TestModuleImports:
    """模块导入测试"""

    def test_perf_module_import(self):
        """测试 perf 模块可以正常导入"""
        from shared.perf import (
            PERF_ENABLED,
            get_cache_manager,
            get_perf_profiler,
            get_metrics_collector,
            get_async_task_queue,
            cache_result,
            cache_invalidate,
            profile_time,
            background_task,
        )
        assert PERF_ENABLED is True  # 默认开启

    def test_cache_manager_module(self):
        """测试 cache_manager 模块"""
        from shared.perf.cache_manager import (
            CacheManager,
            cache_result,
            cache_invalidate,
            NULL_VALUE,
        )
        assert CacheManager is not None

    def test_cache_middleware_module(self):
        """测试 cache_middleware 模块"""
        from shared.perf.cache_middleware import (
            ResponseCacheMiddleware,
            CacheMiddlewareConfig,
        )
        assert ResponseCacheMiddleware is not None

    def test_profiler_module(self):
        """测试 profiler 模块"""
        from shared.perf.profiler import (
            PerformanceProfiler,
            profile_time,
        )
        assert PerformanceProfiler is not None

    def test_metrics_module(self):
        """测试 metrics 模块"""
        from shared.perf.metrics import (
            MetricsCollector,
            SlidingWindowQPS,
        )
        assert MetricsCollector is not None

    def test_performance_report_module(self):
        """测试 performance_report 模块"""
        from shared.perf.performance_report import (
            PerformanceReportGenerator,
            AlertRule,
            AlertLevel,
            AlertType,
        )
        assert PerformanceReportGenerator is not None

    def test_async_tasks_module(self):
        """测试 async_tasks 模块"""
        from shared.perf.async_tasks import (
            AsyncTaskQueue,
            TaskStatus,
            Task,
        )
        assert AsyncTaskQueue is not None

    def test_background_tasks_module(self):
        """测试 background_tasks 模块"""
        from shared.perf.background_tasks import (
            background_task,
            get_task_queue,
            ProgressReporter,
        )
        assert background_task is not None

    def test_query_optimizer_module(self):
        """测试 query_optimizer 模块"""
        from shared.perf.query_optimizer import (
            QueryOptimizer,
            QueryCache,
        )
        assert QueryOptimizer is not None

    def test_connection_pool_module(self):
        """测试 connection_pool 模块"""
        from shared.perf.connection_pool import (
            ConnectionPoolManager,
            PoolStats,
        )
        assert ConnectionPoolManager is not None


# ============================================================
# 与现有模块的兼容性测试
# ============================================================

class TestBackwardCompatibility:
    """向后兼容性测试"""

    def test_existing_cache_still_works(self):
        """测试现有的 shared.data.cache 仍然可用"""
        from shared.data.cache import (
            SimpleCache,
            get_cache,
            cached,
            cached_async,
            CacheStats,
        )
        assert SimpleCache is not None

        # 验证功能正常
        cache = SimpleCache(max_size=10, default_ttl=60)
        cache.set("test", "value")
        assert cache.get("test") == "value"
        cache.shutdown()

    def test_existing_multi_level_cache_still_works(self):
        """测试现有的 shared.data.multi_level_cache 仍然可用"""
        from shared.data.multi_level_cache import (
            MultiLevelCache,
            CacheWarmer,
        )
        assert MultiLevelCache is not None

        cache = MultiLevelCache(
            l1_max_size=10,
            l1_default_ttl=60,
            use_l2=False,
        )
        cache.set("test", "value")
        assert cache.get("test") == "value"
        cache.shutdown()

    def test_existing_performance_utils_still_works(self):
        """测试现有的 shared.core.performance_utils 仍然可用"""
        from shared.core.performance_utils import (
            fast_json_dumps,
            fast_json_loads,
            AsyncLogHandler,
            ObjectPool,
            lazy_property,
            RateLimiter,
            timed,
        )
        assert fast_json_dumps is not None
        assert fast_json_loads is not None

        # 验证 JSON 功能
        data = {"key": "value", "num": 42}
        json_str = fast_json_dumps(data)
        parsed = fast_json_loads(json_str)
        assert parsed["key"] == "value"

    def test_existing_performance_config_still_works(self):
        """测试现有的 shared.core.performance_config 仍然可用"""
        from shared.core.performance_config import (
            PerformanceConfig,
            get_perf_config,
            CacheConfig,
            DatabaseConfig,
        )
        assert PerformanceConfig is not None

        config = get_perf_config()
        assert config is not None
        assert hasattr(config, 'cache')
        assert hasattr(config, 'database')

    def test_existing_query_optimizer_still_works(self):
        """测试现有的 shared.data.data_layer.query_optimizer 仍然可用"""
        from shared.data.data_layer.query_optimizer import (
            QueryCache as OldQueryCache,
            BatchLoader,
            QueryAnalyzer,
            ConnectionPool as OldConnectionPool,
        )
        assert OldQueryCache is not None
        assert BatchLoader is not None

    def test_existing_index_optimizer_still_works(self):
        """测试现有的 shared.data.index_optimizer 仍然可用"""
        from shared.data.index_optimizer import (
            optimize_indexes,
            get_missing_indexes,
            RECOMMENDED_INDEXES,
        )
        assert RECOMMENDED_INDEXES is not None
        assert isinstance(RECOMMENDED_INDEXES, dict)
        assert len(RECOMMENDED_INDEXES) > 0


# ============================================================
# 默认开启但不强制测试
# ============================================================

class TestDefaultBehavior:
    """默认行为测试"""

    def test_perf_enabled_by_default(self):
        """测试性能优化默认开启"""
        import os
        # 确保环境变量未设置
        if "PERF_ENABLED" in os.environ:
            del os.environ["PERF_ENABLED"]

        # 直接读取模块常量
        import importlib
        import shared.perf
        importlib.reload(shared.perf)

        # 默认应该是开启的
        assert shared.perf.PERF_ENABLED is True

    def test_can_disable_via_env(self):
        """测试可以通过环境变量关闭"""
        import os
        os.environ["PERF_ENABLED"] = "false"

        import importlib
        import shared.perf
        importlib.reload(shared.perf)

        assert shared.perf.PERF_ENABLED is False

        # 清理
        del os.environ["PERF_ENABLED"]
        importlib.reload(shared.perf)

    def test_cache_manager_can_be_disabled_per_level(self):
        """测试缓存可以逐层禁用"""
        from shared.perf.cache_manager import CacheManager

        # 只开 L1
        cm1 = CacheManager(
            l1_enabled=True,
            l2_enabled=False,
            l3_enabled=False,
        )
        assert cm1.l1 is not None
        assert cm1.l2 is None
        assert cm1.l3 is None
        cm1.shutdown()

        # 全部关闭 (L1 至少开一个)
        cm2 = CacheManager(
            l1_enabled=False,
            l2_enabled=False,
            l3_enabled=False,
        )
        assert cm2.l1 is None
        cm2.shutdown()


# ============================================================
# 不影响现有业务逻辑测试
# ============================================================

class TestBusinessLogicUnaffected:
    """不影响现有业务逻辑测试"""

    def test_cache_does_not_change_function_behavior(self):
        """测试缓存装饰器不改变函数行为"""
        from shared.perf.cache_manager import cache_result, reset_default_cache_manager

        call_count = 0

        @cache_result(ttl=60, key_prefix="compat_test")
        def compute(x, y):
            nonlocal call_count
            call_count += 1
            return x * y + x + y

        # 第一次调用
        result1 = compute(3, 4)
        assert result1 == 3 * 4 + 3 + 4  # 19
        assert call_count == 1

        # 第二次调用 (相同参数)，结果应该相同
        result2 = compute(3, 4)
        assert result2 == result1
        # 调用次数不变 (缓存命中)
        assert call_count == 1

        # 不同参数应该重新计算
        result3 = compute(5, 6)
        assert result3 == 5 * 6 + 5 + 6  # 41
        assert call_count == 2

        reset_default_cache_manager()

    def test_profiler_does_not_change_function_behavior(self):
        """测试性能分析不改变函数行为"""
        from shared.perf.profiler import PerformanceProfiler

        profiler = PerformanceProfiler(slow_threshold_ms=1000)

        @profiler.profile(name="test_func")
        def add(a, b):
            return a + b

        # 函数应该正常工作
        assert add(1, 2) == 3
        assert add(10, 20) == 30
        assert add(-1, 1) == 0

    def test_task_queue_preserves_function_result(self):
        """测试任务队列保留函数返回值"""
        from shared.perf.async_tasks import AsyncTaskQueue
        import time

        queue = AsyncTaskQueue(worker_count=1, max_retries=0)
        queue.start()

        def compute(x):
            return x ** 2

        task_id = queue.submit(compute, 5)
        result = queue.get_result(task_id, timeout=5.0)

        assert result == 25

        queue.stop(wait=True)

    def test_query_optimizer_preserves_results(self):
        """测试查询优化器保留查询结果"""
        import tempfile
        import sqlite3
        import os
        from shared.perf.query_optimizer import QueryOptimizer

        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = os.path.join(tmpdir, "test.db")
            conn = sqlite3.connect(db_path)
            conn.execute("CREATE TABLE test (id INTEGER PRIMARY KEY, value TEXT)")
            conn.execute("INSERT INTO test VALUES (1, 'hello')")
            conn.execute("INSERT INTO test VALUES (2, 'world')")
            conn.commit()

            optimizer = QueryOptimizer(db_connection=conn)

            # 直接查询
            rows = optimizer.query_all("SELECT * FROM test ORDER BY id")
            assert len(rows) == 2
            assert rows[0][1] == "hello"
            assert rows[1][1] == "world"

            # 带缓存查询 (结果应该相同)
            rows2 = optimizer.query_all("SELECT * FROM test ORDER BY id")
            assert len(rows2) == 2

            conn.close()


# ============================================================
# API 完整性测试
# ============================================================

class TestAPICompleteness:
    """API 完整性测试 (验证所有要求的 API 都存在)"""

    def test_cache_manager_api(self):
        """测试缓存管理器 API 完整性"""
        from shared.perf.cache_manager import CacheManager

        cm = CacheManager(l1_max_size=10, l2_enabled=False, l3_enabled=False)

        # 要求的 API
        assert hasattr(cm, 'get')
        assert hasattr(cm, 'set')
        assert hasattr(cm, 'delete')
        assert hasattr(cm, 'exists')
        assert hasattr(cm, 'clear')
        assert hasattr(cm, 'get_stats')
        assert hasattr(cm, 'get_or_set')
        assert hasattr(cm, 'get_many')
        assert hasattr(cm, 'set_many')

        cm.shutdown()

    def test_profiler_api(self):
        """测试性能分析器 API 完整性"""
        from shared.perf.profiler import PerformanceProfiler

        p = PerformanceProfiler()

        assert hasattr(p, 'profile')
        assert hasattr(p, 'profile_block')
        assert hasattr(p, 'get_slow_requests')
        assert hasattr(p, 'get_stats')
        assert hasattr(p, 'get_bottlenecks')
        assert hasattr(p, 'get_trace_chain')
        assert hasattr(p, 'start_trace')
        assert hasattr(p, 'end_trace')

    def test_metrics_api(self):
        """测试指标收集器 API 完整性"""
        from shared.perf.metrics import MetricsCollector

        m = MetricsCollector(enable_system_metrics=False)

        assert hasattr(m, 'record_request')
        assert hasattr(m, 'record_db_query')
        assert hasattr(m, 'get_summary')
        assert hasattr(m, 'get_api_metrics')
        assert hasattr(m, 'get_db_metrics')
        assert hasattr(m, 'get_slow_queries')
        assert hasattr(m, 'get_system_metrics')

    def test_async_task_api(self):
        """测试异步任务 API 完整性"""
        from shared.perf.async_tasks import AsyncTaskQueue

        q = AsyncTaskQueue(worker_count=1, max_retries=0)

        assert hasattr(q, 'submit')
        assert hasattr(q, 'submit_delayed')
        assert hasattr(q, 'get_task_status')
        assert hasattr(q, 'get_result')
        assert hasattr(q, 'list_tasks')
        assert hasattr(q, 'cancel_task')
        assert hasattr(q, 'update_progress')
        assert hasattr(q, 'get_stats')
        assert hasattr(q, 'start')
        assert hasattr(q, 'stop')

        q.start()
        q.stop(wait=True)

    def test_performance_report_api(self):
        """测试性能报告 API 完整性"""
        from shared.perf.performance_report import PerformanceReportGenerator

        r = PerformanceReportGenerator(alert_rules=[])

        assert hasattr(r, 'get_dashboard')
        assert hasattr(r, 'get_daily_report')
        assert hasattr(r, 'get_trend_analysis')
        assert hasattr(r, 'get_alerts')
        assert hasattr(r, 'get_active_alerts')
        assert hasattr(r, 'acknowledge_alert')
        assert hasattr(r, 'check_alerts')

    def test_connection_pool_api(self):
        """测试连接池 API 完整性"""
        import tempfile
        import os
        from shared.perf.connection_pool import ConnectionPoolManager

        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = os.path.join(tmpdir, "test.db")
            pool = ConnectionPoolManager(
                db_path=db_path,
                pool_size=2,
                health_check_interval=0,
            )

            assert hasattr(pool, 'acquire')
            assert hasattr(pool, 'release')
            assert hasattr(pool, 'connection')
            assert hasattr(pool, 'get_stats')
            assert hasattr(pool, 'close_all')
            assert hasattr(pool, 'reset')

            pool.close_all()
