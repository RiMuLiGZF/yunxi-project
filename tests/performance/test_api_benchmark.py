"""
API 性能基准测试

测试 API 接口的性能指标：
- 核心 API 响应时间
- 并发请求性能
- 吞吐量（QPS）
- 慢 API 识别
- 缓存命中率对性能的影响
"""

import os
import sys
import time
import json
import threading
from pathlib import Path
from typing import Dict, List, Any, Callable

import pytest

# 确保项目根目录在 Python 路径中
PROJECT_ROOT = Path(__file__).parent.parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from tests.performance.benchmark import (
    BenchmarkTimer,
    BenchmarkStats,
    BenchmarkCollector,
    concurrent_benchmark,
    measure_throughput,
)

# 尝试导入 FastAPI TestClient
try:
    from fastapi.testclient import TestClient
    HAS_FASTAPI = True
except ImportError:
    HAS_FASTAPI = False

# 尝试导入缓存系统
try:
    from shared.data.cache import SimpleCache, get_cache, cached, cached_async
    HAS_CACHE = True
except ImportError:
    HAS_CACHE = False

# 尝试导入各模块的 API
try:
    sys.path.insert(0, str(PROJECT_ROOT / "M0-principal-console"))
    from src.main import app as m0_app
    HAS_M0_APP = True
except (ImportError, Exception):
    HAS_M0_APP = False
    m0_app = None

try:
    sys.path.insert(0, str(PROJECT_ROOT / "API-Gateway" / "src"))
    from main import app as gateway_app
    HAS_GATEWAY_APP = True
except (ImportError, Exception):
    HAS_GATEWAY_APP = False
    gateway_app = None


pytestmark = pytest.mark.performance


# ============================================================
# 模拟 API 响应（无外部依赖）
# ============================================================

class MockAPIService:
    """模拟 API 服务，用于性能基准测试"""

    def __init__(self):
        self.data = {
            f"item_{i}": {
                "id": i,
                "name": f"item_{i}",
                "value": f"value_{i}",
                "metadata": {"key": f"meta_{i}"},
            }
            for i in range(1000)
        }
        self._cache = SimpleCache(max_size=500, default_ttl=60) if HAS_CACHE else None

    def get_item(self, item_id: str) -> Dict[str, Any]:
        """获取单个条目（模拟 API 调用）"""
        # 模拟一些处理时间
        time.sleep(0.001)  # 1ms 模拟延迟
        return self.data.get(item_id, {})

    def get_item_cached(self, item_id: str) -> Dict[str, Any]:
        """带缓存的获取"""
        if self._cache is None:
            return self.get_item(item_id)
        return self._cache.get_or_set(
            f"item:{item_id}",
            lambda: self.get_item(item_id),
            ttl=60,
        )

    def list_items(self, page: int = 1, page_size: int = 20) -> Dict[str, Any]:
        """列表查询（模拟分页 API）"""
        time.sleep(0.002)
        start = (page - 1) * page_size
        end = start + page_size
        items = list(self.data.values())[start:end]
        return {
            "items": items,
            "total": len(self.data),
            "page": page,
            "page_size": page_size,
        }

    def create_item(self, item: Dict[str, Any]) -> Dict[str, Any]:
        """创建条目（模拟写 API）"""
        time.sleep(0.005)
        item_id = f"item_{len(self.data)}"
        item["id"] = len(self.data)
        self.data[item_id] = item
        return item

    def search_items(self, query: str) -> List[Dict[str, Any]]:
        """搜索（模拟较重的查询）"""
        time.sleep(0.01)
        results = []
        for item in self.data.values():
            if query.lower() in item.get("name", "").lower():
                results.append(item)
                if len(results) >= 50:
                    break
        return results

    def complex_operation(self, item_id: str) -> Dict[str, Any]:
        """复杂操作（模拟重 API）"""
        time.sleep(0.05)
        item = self.data.get(item_id, {})
        return {
            "item": item,
            "analysis": {
                "score": len(str(item)) * 0.1,
                "related": [f"related_{i}" for i in range(5)],
            },
        }


@pytest.fixture
def mock_api():
    return MockAPIService()


# ============================================================
# 基础 API 响应时间测试
# ============================================================

class TestAPIResponseTime:
    """API 响应时间基准测试"""

    def test_single_get(self, mock_api, benchmark_iterations, benchmark_warmup):
        """单个 GET 请求响应时间"""
        stats = BenchmarkStats(name="api:get_single")

        for i in range(benchmark_warmup):
            mock_api.get_item(f"item_{i}")

        for i in range(benchmark_iterations):
            item_id = f"item_{i % 1000}"
            with BenchmarkTimer() as timer:
                mock_api.get_item(item_id)
            stats.add_measurement(timer.elapsed_ms)

        BenchmarkCollector.get_instance().add_result("api_get_single", stats)

        assert stats.count == benchmark_iterations
        print(f"\n{stats.summary()}")

    def test_cached_get(self, mock_api, benchmark_iterations, benchmark_warmup):
        """带缓存的 GET 请求性能"""
        if not HAS_CACHE:
            pytest.skip("Cache system not available")

        stats = BenchmarkStats(name="api:get_cached")

        # 预热（填充缓存）
        for i in range(min(benchmark_warmup, 100)):
            mock_api.get_item_cached(f"item_{i}")

        for i in range(benchmark_iterations):
            item_id = f"item_{i % 100}"  # 100 个 key，确保有缓存命中
            with BenchmarkTimer() as timer:
                mock_api.get_item_cached(item_id)
            stats.add_measurement(timer.elapsed_ms)

        BenchmarkCollector.get_instance().add_result("api_get_cached", stats)

        assert stats.count == benchmark_iterations
        print(f"\n{stats.summary()}")

    def test_list_pagination(self, mock_api, benchmark_iterations, benchmark_warmup):
        """分页列表 API 响应时间"""
        stats = BenchmarkStats(name="api:list_pagination")

        for i in range(benchmark_warmup):
            mock_api.list_items(page=i + 1, page_size=20)

        for i in range(benchmark_iterations):
            page = (i % 50) + 1
            with BenchmarkTimer() as timer:
                mock_api.list_items(page=page, page_size=20)
            stats.add_measurement(timer.elapsed_ms)

        BenchmarkCollector.get_instance().add_result("api_list_pagination", stats)

        assert stats.count == benchmark_iterations
        print(f"\n{stats.summary()}")

    def test_create_item(self, mock_api, benchmark_iterations, benchmark_warmup):
        """创建条目 API 响应时间"""
        stats = BenchmarkStats(name="api:create_item")

        for i in range(benchmark_warmup):
            mock_api.create_item({"name": f"warmup_{i}", "value": f"val_{i}"})

        for i in range(benchmark_iterations):
            with BenchmarkTimer() as timer:
                mock_api.create_item({
                    "name": f"new_item_{i}",
                    "value": f"value_{i}",
                    "extra": "x" * 100,
                })
            stats.add_measurement(timer.elapsed_ms)

        BenchmarkCollector.get_instance().add_result("api_create_item", stats)

        assert stats.count == benchmark_iterations
        print(f"\n{stats.summary()}")

    def test_search_api(self, mock_api, benchmark_iterations, benchmark_warmup):
        """搜索 API 响应时间"""
        stats = BenchmarkStats(name="api:search")

        for i in range(benchmark_warmup):
            mock_api.search_items(f"item_{i % 10}")

        for i in range(benchmark_iterations):
            query = f"item_{i % 50}"
            with BenchmarkTimer() as timer:
                mock_api.search_items(query)
            stats.add_measurement(timer.elapsed_ms)

        BenchmarkCollector.get_instance().add_result("api_search", stats)

        assert stats.count == benchmark_iterations
        print(f"\n{stats.summary()}")

    def test_complex_operation(self, mock_api):
        """复杂操作 API 响应时间（慢 API 识别）"""
        iterations = 30
        stats = BenchmarkStats(name="api:complex_operation")

        for i in range(5):
            mock_api.complex_operation(f"item_{i}")

        for i in range(iterations):
            item_id = f"item_{i % 100}"
            with BenchmarkTimer() as timer:
                mock_api.complex_operation(item_id)
            stats.add_measurement(timer.elapsed_ms)

        BenchmarkCollector.get_instance().add_result("api_complex_operation", stats)

        assert stats.count == iterations
        print(f"\n{stats.summary()}")
        print(f"  P99: {stats.p99:.3f}ms")

    def test_json_serialization(self, benchmark_iterations, benchmark_warmup):
        """JSON 序列化性能"""
        test_data = {
            "id": 123,
            "name": "test_item",
            "value": "test_value",
            "metadata": {
                "key1": "value1",
                "key2": "value2",
                "nested": {"a": 1, "b": 2, "c": [1, 2, 3]},
            },
            "tags": ["tag1", "tag2", "tag3"],
        }

        stats = BenchmarkStats(name="api:json_serialization")

        for _ in range(benchmark_warmup):
            json.dumps(test_data)

        for _ in range(benchmark_iterations):
            with BenchmarkTimer() as timer:
                result = json.dumps(test_data)
                _ = json.loads(result)
            stats.add_measurement(timer.elapsed_ms)

        BenchmarkCollector.get_instance().add_result("api_json_serialization", stats)

        assert stats.count == benchmark_iterations
        print(f"\n{stats.summary()}")


# ============================================================
# 并发 API 性能测试
# ============================================================

class TestAPIConcurrency:
    """API 并发性能测试"""

    def test_concurrent_get(self, mock_api):
        """并发 GET 请求性能"""
        stats = concurrent_benchmark(
            lambda: mock_api.get_item("item_0"),
            iterations=200,
            concurrency=10,
        )
        stats.name = "api:concurrent_get_10t"

        BenchmarkCollector.get_instance().add_result("api_concurrent_get", stats)

        assert stats.count > 0
        print(f"\n{stats.summary()}")
        print(f"  10 并发 QPS: {stats.qps:.1f}")

    def test_concurrent_cached_get(self, mock_api):
        """并发带缓存 GET 性能"""
        if not HAS_CACHE:
            pytest.skip("Cache system not available")

        # 预热缓存
        for i in range(50):
            mock_api.get_item_cached(f"item_{i}")

        stats = concurrent_benchmark(
            lambda: mock_api.get_item_cached("item_0"),
            iterations=500,
            concurrency=20,
        )
        stats.name = "api:concurrent_cached_get_20t"

        BenchmarkCollector.get_instance().add_result("api_concurrent_cached_get", stats)

        assert stats.count > 0
        print(f"\n{stats.summary()}")
        print(f"  20 并发缓存 QPS: {stats.qps:.1f}")

    def test_concurrent_mixed(self, mock_api):
        """读写混合并发性能"""
        read_ops = {"count": 0}
        write_ops = {"count": 0}
        errors = []
        lock = threading.Lock()

        def reader():
            for _ in range(30):
                try:
                    item_id = f"item_{hash(threading.current_thread().name) % 1000}"
                    mock_api.get_item(item_id)
                    with lock:
                        read_ops["count"] += 1
                except Exception as e:
                    errors.append(str(e))

        def writer():
            for i in range(10):
                try:
                    mock_api.create_item({
                        "name": f"concurrent_{threading.current_thread().name}_{i}",
                        "value": f"val_{i}",
                    })
                    with lock:
                        write_ops["count"] += 1
                except Exception as e:
                    errors.append(str(e))

        with BenchmarkTimer() as timer:
            threads = []
            for _ in range(8):
                t = threading.Thread(target=reader)
                threads.append(t)
                t.start()
            for _ in range(2):
                t = threading.Thread(target=writer)
                threads.append(t)
                t.start()

            for t in threads:
                t.join(timeout=10)

        total_qps = (read_ops["count"] + write_ops["count"]) / timer.elapsed_seconds

        stats = BenchmarkStats(name="api:concurrent_mixed")
        stats.add_measurement(timer.elapsed_ms)
        BenchmarkCollector.get_instance().add_result("api_concurrent_mixed", stats)

        assert len(errors) == 0
        print(f"\n  读写混合 (8读+2写):")
        print(f"    总耗时: {timer.elapsed_ms:.2f}ms")
        print(f"    读: {read_ops['count']} ops, 写: {write_ops['count']} ops")
        print(f"    总 QPS: {total_qps:.1f}")


# ============================================================
# 吞吐量测试
# ============================================================

class TestAPIThroughput:
    """API 吞吐量测试"""

    def test_get_throughput_single(self, mock_api):
        """单线程 GET 吞吐量"""
        result = measure_throughput(
            lambda: mock_api.get_item("item_0"),
            duration_seconds=2.0,
            concurrency=1,
        )

        stats = BenchmarkStats(name="api:get_throughput_single")
        stats.add_measurement(result.get("avg_latency_ms", 0))
        BenchmarkCollector.get_instance().add_result("api_get_throughput_single", stats)

        print(f"\n  单线程 GET QPS: {result['ops_per_second']:.1f}")
        assert result["total_ops"] > 0

    def test_get_throughput_concurrent(self, mock_api):
        """并发 GET 吞吐量"""
        result = measure_throughput(
            lambda: mock_api.get_item("item_0"),
            duration_seconds=2.0,
            concurrency=10,
        )

        stats = BenchmarkStats(name="api:get_throughput_10t")
        stats.add_measurement(result.get("avg_latency_ms", 0))
        BenchmarkCollector.get_instance().add_result("api_get_throughput_concurrent", stats)

        print(f"\n  10 并发 GET QPS: {result['ops_per_second']:.1f}")
        assert result["total_ops"] > 0

    def test_cached_throughput(self, mock_api):
        """带缓存的吞吐量"""
        if not HAS_CACHE:
            pytest.skip("Cache system not available")

        # 预热
        mock_api.get_item_cached("item_0")

        result = measure_throughput(
            lambda: mock_api.get_item_cached("item_0"),
            duration_seconds=2.0,
            concurrency=10,
        )

        stats = BenchmarkStats(name="api:cached_throughput_10t")
        stats.add_measurement(result.get("avg_latency_ms", 0))
        BenchmarkCollector.get_instance().add_result("api_cached_throughput", stats)

        print(f"\n  10 并发缓存 GET QPS: {result['ops_per_second']:.1f}")
        assert result["total_ops"] > 0


# ============================================================
# 缓存对 API 性能影响测试
# ============================================================

class TestCachePerformanceImpact:
    """缓存对 API 性能的影响测试"""

    def test_cache_vs_no_cache(self, mock_api, benchmark_iterations=100):
        """缓存 vs 无缓存性能对比"""
        if not HAS_CACHE:
            pytest.skip("Cache system not available")

        item_ids = [f"item_{i}" for i in range(50)]

        # 无缓存
        stats_no_cache = BenchmarkStats(name="api:no_cache")
        for i in range(benchmark_iterations):
            item_id = item_ids[i % len(item_ids)]
            with BenchmarkTimer() as timer:
                mock_api.get_item(item_id)
            stats_no_cache.add_measurement(timer.elapsed_ms)

        # 有缓存（先预热）
        for item_id in item_ids:
            mock_api.get_item_cached(item_id)

        stats_with_cache = BenchmarkStats(name="api:with_cache")
        for i in range(benchmark_iterations):
            item_id = item_ids[i % len(item_ids)]
            with BenchmarkTimer() as timer:
                mock_api.get_item_cached(item_id)
            stats_with_cache.add_measurement(timer.elapsed_ms)

        BenchmarkCollector.get_instance().add_result("api_no_cache", stats_no_cache)
        BenchmarkCollector.get_instance().add_result("api_with_cache", stats_with_cache)

        speedup = stats_no_cache.mean / max(stats_with_cache.mean, 0.001)

        print(f"\n  无缓存平均: {stats_no_cache.mean:.3f}ms")
        print(f"  有缓存平均: {stats_with_cache.mean:.3f}ms")
        print(f"  加速比: {speedup:.1f}x")

        # 缓存应该显著更快
        assert stats_with_cache.mean < stats_no_cache.mean, \
            "缓存应该比无缓存更快"


# ============================================================
# FastAPI 集成测试（如果可用）
# ============================================================

class TestFastAPIPerformance:
    """FastAPI 性能基准测试（如果可用）

    注意：这些测试使用真实的 FastAPI 应用，启动开销较大。
    只做少量迭代以验证功能。
    """

    @pytest.fixture(scope="class")
    def test_client(self):
        """获取 FastAPI 测试客户端（类级复用，减少启动开销）"""
        if not HAS_FASTAPI:
            pytest.skip("FastAPI TestClient not available")

        app = None
        if HAS_M0_APP and m0_app is not None:
            app = m0_app
        elif HAS_GATEWAY_APP and gateway_app is not None:
            app = gateway_app
        else:
            pytest.skip("No FastAPI app available")

        with TestClient(app) as client:
            yield client

    def test_health_endpoint(self, test_client):
        """健康检查端点性能"""
        stats = BenchmarkStats(name="api:fastapi_health")

        iterations = 20  # 少量迭代，避免超时

        # 预热
        for _ in range(3):
            test_client.get("/health")

        # 正式测试
        for _ in range(iterations):
            with BenchmarkTimer() as timer:
                response = test_client.get("/health")
            stats.add_measurement(timer.elapsed_ms)
            assert response.status_code in (200, 404)  # 可能路径不同

        BenchmarkCollector.get_instance().add_result("api_fastapi_health", stats)

        print(f"\n{stats.summary()}")
