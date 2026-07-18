"""
云汐系统性能基准测试框架

提供系统级性能基准测试，量化性能指标和优化效果。

测试类别：
- API 性能基准测试
- 数据库性能基准测试
- 内存使用基准测试
- 缓存性能基准测试

使用方式：
    # 运行所有性能测试
    pytest tests/performance/ -v --benchmark-only

    # 运行指定类别
    pytest tests/performance/test_db_benchmark.py -v

    # 生成性能报告
    pytest tests/performance/ --benchmark-report=report.html
"""

__version__ = "1.2.0"
