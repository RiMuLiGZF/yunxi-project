"""
性能测试 pytest 配置

提供性能测试专用的 fixtures 和配置。
"""

import os
import sys
import json
import time
import tempfile
from pathlib import Path
from typing import Optional, Dict, Any

import pytest

# 确保项目根目录在 Python 路径中
PROJECT_ROOT = Path(__file__).parent.parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

# 确保 shared 模块在路径中
SHARED_DIR = PROJECT_ROOT / "shared"
if str(SHARED_DIR) not in sys.path:
    sys.path.insert(0, str(SHARED_DIR))

from tests.performance.benchmark import (
    BenchmarkStats,
    BenchmarkCollector,
    BaselineManager,
)


# ============================================================
# pytest hooks
# ============================================================

def pytest_configure(config):
    """pytest 配置钩子"""
    # 注册自定义标记
    config.addinivalue_line(
        "markers",
        "performance: 性能基准测试（运行时间较长，默认不运行）",
    )
    config.addinivalue_line(
        "markers",
        "slow: 慢速性能测试（运行时间很长，默认跳过）",
    )


def pytest_addoption(parser):
    """添加命令行选项"""
    group = parser.getgroup("performance")
    group.addoption(
        "--benchmark-only",
        action="store_true",
        default=False,
        help="只运行性能基准测试",
    )
    group.addoption(
        "--benchmark-save-baseline",
        action="store_true",
        default=False,
        help="将当前测试结果保存为基线",
    )
    group.addoption(
        "--benchmark-compare",
        action="store_true",
        default=False,
        help="运行测试后与基线对比",
    )
    group.addoption(
        "--benchmark-report",
        type=str,
        default=None,
        help="生成 HTML 性能报告的输出路径",
    )
    group.addoption(
        "--benchmark-iterations",
        type=int,
        default=100,
        help="性能测试迭代次数（默认 100）",
    )
    group.addoption(
        "--benchmark-warmup",
        type=int,
        default=5,
        help="预热次数（默认 5）",
    )
    group.addoption(
        "--benchmark-threshold",
        type=float,
        default=20.0,
        help="性能退化告警阈值百分比（默认 20%%）",
    )


def pytest_collection_modifyitems(config, items):
    """修改测试集合"""
    if config.getoption("--benchmark-only"):
        # 只运行 performance 标记的测试
        selected = []
        deselected = []
        for item in items:
            if item.get_closest_marker("performance") or "performance" in str(item.fspath):
                selected.append(item)
            else:
                deselected.append(item)
        items[:] = selected
        config.hook.pytest_deselected(items=deselected)


def pytest_terminal_summary(terminalreporter, exitstatus, config):
    """测试结束时输出性能报告"""
    # 检查是否需要生成报告
    report_path = config.getoption("--benchmark-report")
    if report_path:
        _generate_report(report_path)

    # 检查是否需要对比基线
    if config.getoption("--benchmark-compare"):
        _compare_with_baselines(config)


def _generate_report(report_path: str):
    """生成性能报告（HTML）"""
    try:
        from tests.performance.report import generate_html_report
        collector = BenchmarkCollector.get_instance()
        results = collector.get_all_results()
        memory_results = collector.get_memory_results()
        html = generate_html_report(results, memory_results)

        output_path = Path(report_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with open(output_path, "w", encoding="utf-8") as f:
            f.write(html)
        print(f"\n性能报告已生成: {output_path}")
    except Exception as e:
        print(f"\n生成性能报告失败: {e}")


def _compare_with_baselines(config):
    """与基线对比"""
    collector = BenchmarkCollector.get_instance()
    results = collector.get_all_results()
    threshold = config.getoption("--benchmark-threshold")

    print("\n" + "=" * 80)
    print("性能基线对比结果")
    print("=" * 80)

    manager = BaselineManager()

    regressions = 0
    improvements = 0
    ok_count = 0

    for name, result_data in results.items():
        stats = BenchmarkStats(name=name)
        # 从结果重建统计（只使用 mean 进行简单对比）
        stats.add_measurement(result_data.get("mean_ms", 0))

        comparison = manager.compare(name, stats, threshold_pct=threshold)
        status = comparison.get("status", "unknown")
        message = comparison.get("message", "")

        status_icon = {
            "ok": "[OK]",
            "regression": "[!]",
            "improvement": "[+]",
            "no_baseline": "[?]",
        }.get(status, "[?]")

        print(f"  {status_icon} {name}: {message}")

        if status == "regression":
            regressions += 1
        elif status == "improvement":
            improvements += 1
        elif status == "ok":
            ok_count += 1

    print(f"\n总计: OK={ok_count}, 提升={improvements}, 退化={regressions}")
    print("=" * 80)

    # 保存为基线
    if config.getoption("--benchmark-save-baseline"):
        for name, result_data in results.items():
            stats = BenchmarkStats(name=name)
            stats.add_measurement(result_data.get("mean_ms", 0))
            manager.save_baseline(name, stats)
        print(f"基线已保存到: {manager.baseline_file}")


# ============================================================
# Fixtures
# ============================================================

@pytest.fixture(scope="session")
def benchmark_iterations(request):
    """性能测试迭代次数"""
    return request.config.getoption("--benchmark-iterations")


@pytest.fixture(scope="session")
def benchmark_warmup(request):
    """预热次数"""
    return request.config.getoption("--benchmark-warmup")


@pytest.fixture(scope="session")
def benchmark_threshold(request):
    """性能退化阈值"""
    return request.config.getoption("--benchmark-threshold")


@pytest.fixture
def benchmark_collector():
    """全局基准结果收集器"""
    collector = BenchmarkCollector.get_instance()
    yield collector


@pytest.fixture
def baseline_manager():
    """基线管理器"""
    return BaselineManager()


@pytest.fixture
def temp_db_path(tmp_path):
    """临时数据库路径（用于性能测试）"""
    db_path = tmp_path / "benchmark_test.db"
    return str(db_path)


@pytest.fixture
def perf_temp_dir(tmp_path):
    """性能测试临时目录"""
    return tmp_path


@pytest.fixture(scope="session")
def performance_config():
    """性能测试配置"""
    return {
        "iterations": 100,
        "warmup": 5,
        "threshold_pct": 20.0,
        "slow_query_ms": 100.0,
    }


@pytest.fixture
def sample_data_generator():
    """生成测试数据的工厂函数"""
    def _generator(n: int = 1000):
        return [
            {
                "id": i,
                "name": f"item_{i}",
                "value": f"value_{i}",
                "score": i * 1.5,
                "category": f"cat_{i % 10}",
            }
            for i in range(n)
        ]
    return _generator
