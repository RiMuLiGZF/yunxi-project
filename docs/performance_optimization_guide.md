# 云汐系统性能优化指南

## 目录

1. [性能测试方法](#1-性能测试方法)
2. [性能监控指标](#2-性能监控指标)
3. [常见性能问题与优化方法](#3-常见性能问题与优化方法)
4. [性能优化 Checklist](#4-性能优化-checklist)
5. [配置调优参考](#5-配置调优参考)
6. [性能测试框架使用说明](#6-性能测试框架使用说明)

---

## 1. 性能测试方法

### 1.1 基准测试流程

```
建立基线 → 识别瓶颈 → 实施优化 → 验证效果 → 保存新基线
```

1. **建立基线**：在优化之前运行完整的性能测试，保存为基线数据
2. **识别瓶颈**：分析测试结果，找出最慢的 API/查询/操作
3. **实施优化**：针对瓶颈进行优化，一次只改一个变量
4. **验证效果**：重新运行测试，对比基线数据
5. **保存基线**：如果优化有效，将新结果保存为基线

### 1.2 运行性能测试

```bash
# 运行所有性能测试
pytest tests/performance/ -v

# 只运行性能测试
pytest tests/performance/ -v --benchmark-only

# 指定迭代次数
pytest tests/performance/ --benchmark-iterations=500 -v

# 生成 HTML 性能报告
pytest tests/performance/ --benchmark-report=report.html

# 与基线对比
pytest tests/performance/ --benchmark-compare -v

# 保存当前结果为基线
pytest tests/performance/ --benchmark-save-baseline -v

# 运行数据库性能测试
pytest tests/performance/test_db_benchmark.py -v

# 运行 API 性能测试
pytest tests/performance/test_api_benchmark.py -v

# 运行内存性能测试
pytest tests/performance/test_memory_benchmark.py -v
```

### 1.3 测试注意事项

- **预热**：正式测试前先运行几次，让 JIT/缓存预热
- **多次运行取平均**：单次结果可能有波动，取多次的平均/中位数
- **隔离环境**：测试时尽量减少其他进程的干扰
- **控制变量**：一次只改一个参数，方便归因
- **记录环境**：记录测试时的硬件、软件环境信息

---

## 2. 性能监控指标

### 2.1 API 性能指标

| 指标 | 说明 | 目标值（参考） |
|------|------|---------------|
| 平均响应时间 | 所有请求的平均耗时 | < 100ms |
| P50（中位数） | 50% 请求的响应时间 | < 50ms |
| P95 | 95% 请求的响应时间 | < 200ms |
| P99 | 99% 请求的响应时间 | < 500ms |
| QPS | 每秒处理请求数 | 视业务而定 |
| 错误率 | 失败请求占比 | < 0.1% |
| 并发用户数 | 同时在线用户数 | 视业务而定 |

### 2.2 数据库性能指标

| 指标 | 说明 | 目标值（参考） |
|------|------|---------------|
| 平均查询时间 | 单次查询平均耗时 | < 10ms |
| 慢查询率 | 慢查询占总查询的比例 | < 1% |
| QPS | 每秒查询数 | > 1000 |
| 连接数 | 活跃数据库连接数 | < 池大小的 80% |
| 缓存命中率 | 查询缓存命中率 | > 80% |
| 锁等待时间 | 数据库锁等待时间 | < 10ms |

### 2.3 缓存性能指标

| 指标 | 说明 | 目标值（参考） |
|------|------|---------------|
| 命中率 | 缓存命中 / 总请求 | > 80%（越高越好） |
| L1 命中率 | 一级缓存命中率 | > 60% |
| 淘汰数 | 被 LRU 淘汰的条目数 | 适量，不宜过多 |
| 内存占用 | 缓存占用的内存 | < 可用内存的 30% |
| 平均响应时间 | 缓存读取耗时 | < 1ms |

### 2.4 系统资源指标

| 指标 | 说明 | 告警阈值（参考） |
|------|------|-----------------|
| CPU 使用率 | CPU 利用率 | > 80% |
| 内存使用率 | 内存利用率 | > 85% |
| 磁盘 I/O | 磁盘读写速度 | 视磁盘而定 |
| 网络 I/O | 网络带宽使用 | > 带宽的 70% |
| 句柄数 | 打开的文件句柄数 | > 上限的 70% |
| GC 次数/时间 | 垃圾回收频率和耗时 | 视语言而定 |

---

## 3. 常见性能问题与优化方法

### 3.1 数据库相关

#### 问题 1：慢查询

**症状**：
- 某些 API 响应特别慢
- 数据库 CPU 占用高
- 慢查询日志频繁输出

**优化方法**：
1. **添加索引**：为 WHERE/JOIN/ORDER BY/GROUP BY 的字段添加索引
   ```python
   # 使用索引优化器
   from shared.data.index_optimizer import optimize_indexes
   optimize_indexes(db_path)
   ```

2. **优化 SQL**：
   - 避免 SELECT *，只查需要的字段
   - 用 JOIN 代替子查询
   - 合理使用 LIMIT
   - 避免在 WHERE 中使用函数（会导致索引失效）

3. **查询缓存**：
   ```python
   from shared.data.data_layer.query_optimizer import QueryCache
   
   cache = QueryCache(db_manager, max_size=500, default_ttl=30)
   result = cache.query_all("mydb", "SELECT * FROM users WHERE active=1")
   ```

4. **读写分离**：读操作走从库，写操作走主库（如果使用主从架构）

#### 问题 2：N+1 查询

**症状**：
- 列表页加载慢
- 数据库查询次数与列表长度成正比

**优化方法**：
1. **批量加载**：使用 BatchLoader
   ```python
   from shared.data.data_layer.query_optimizer import BatchLoader
   
   user_loader = BatchLoader(db, "mydb", "users", "id")
   users = user_loader.load_many([user_id1, user_id2, user_id3])
   ```

2. **JOIN 查询**：用一条 JOIN 查询代替多条单条查询

3. **预加载**：在主查询时就把关联数据查出来

#### 问题 3：连接泄漏

**症状**：
- 数据库连接数持续增长
- 最终报 "too many connections" 错误

**优化方法**：
1. 使用上下文管理器确保连接释放
2. 使用连接池管理连接
3. 设置合理的连接超时时间

### 3.2 缓存相关

#### 问题 1：缓存穿透

**症状**：
- 大量请求查询不存在的数据
- 这些请求全部打到数据库
- 数据库压力大

**优化方法**：
1. **空值缓存**：缓存不存在的 key（短 TTL）
   ```python
   # SimpleCache 已内置支持
   cache.set("key", None, ttl=30, is_null=True)
   ```

2. **布隆过滤器**：在缓存前加一层布隆过滤器
3. **参数校验**：在入口处校验参数合法性

#### 问题 2：缓存击穿

**症状**：
- 某个热点 key 过期
- 瞬间大量请求打到数据库
- 数据库压力陡增

**优化方法**：
1. **单飞锁**：同一 key 只有一个请求回源
   ```python
   # MultiLevelCache 已内置支持
   cache.get_or_set("hot_key", load_from_db)
   ```

2. **永不过期**：热点数据逻辑过期，后台异步更新
3. **缓存预热**：启动时预加载热点数据

#### 问题 3：缓存雪崩

**症状**：
- 大量 key 同时过期
- 数据库压力瞬间飙升
- 可能导致数据库宕机

**优化方法**：
1. **TTL 抖动**：给每个 key 的 TTL 加随机值
   ```python
   # SimpleCache 已内置支持（jitter_ratio 参数）
   ```

2. **分批过期**：将 key 分散到不同时间点过期
3. **多级缓存**：L1 + L2，减少同时失效的影响

#### 问题 4：缓存一致性

**症状**：
- 数据更新后，缓存还是旧数据
- 用户看到的数据不一致

**优化方法**：
1. **Cache-Aside 模式**：读时缓存，写时失效
   ```python
   # 写操作后删除缓存
   db.update(data)
   cache.delete(key)
   ```

2. **Write-Through 模式**：写操作同步更新缓存
3. **设置合理的 TTL**：最终一致性

### 3.3 API / 网络相关

#### 问题 1：响应慢

**症状**：
- API 响应时间长
- 用户等待时间久

**优化方法**：
1. **添加缓存**：对热点接口做响应缓存
2. **异步处理**：非核心逻辑异步执行
3. **数据压缩**：启用 Gzip 压缩
4. **批量接口**：提供批量查询接口，减少往返
5. **分页**：大数据量接口做分页

#### 问题 2：并发能力不足

**症状**：
- 高并发时响应变慢
- 错误率上升

**优化方法**：
1. **连接池优化**：合理设置连接池大小
2. **异步 I/O**：使用 async/await 提高并发
3. **限流保护**：保护下游系统不被打垮
4. **熔断降级**：下游故障时快速失败

### 3.4 内存相关

#### 问题 1：内存泄漏

**症状**：
- 内存占用持续增长
- GC 后内存不下降
- 最终 OOM

**排查方法**：
1. 使用 `tracemalloc` 分析内存分配
2. 使用 `objgraph` 查看对象引用
3. 使用内存性能测试对比

**常见原因**：
- 全局缓存/字典只增不减
- 监听器/回调未注销
- 线程池/连接池未正确关闭
- 循环引用

#### 问题 2：频繁 GC

**症状**：
- CPU 占用高，但业务量不大
- GC 日志显示频繁 GC

**优化方法**：
1. **对象池**：复用创建开销大的对象
   ```python
   from shared.core.performance_utils import ObjectPool
   pool = ObjectPool(create_func=create_expensive_object, max_size=10)
   ```

2. **减少临时对象**：避免在循环中创建大量对象
3. **使用 `__slots__`**：减少对象内存占用
4. **生成器**：用生成器代替列表，惰性计算

### 3.5 日志相关

#### 问题 1：日志影响性能

**症状**：
- 开启 DEBUG 日志后性能下降明显
- I/O wait 高

**优化方法**：
1. **异步日志**：使用异步日志处理器
   ```python
   from shared.core.performance_utils import AsyncLogHandler
   handler = AsyncLogHandler(file_handler)
   ```

2. **合理设置日志级别**：生产环境用 INFO/WARNING
3. **避免在循环中打日志**：批量输出或采样
4. **日志脱敏**：在输出前脱敏，减少字符串处理

---

## 4. 性能优化 Checklist

### 4.1 数据库优化

- [ ] 所有常用查询都有合适的索引
- [ ] 慢查询率 < 1%
- [ ] 没有 N+1 查询问题
- [ ] 使用参数化查询防 SQL 注入（同时有助性能）
- [ ] 合理的连接池大小
- [ ] 启用 WAL 模式（SQLite）
- [ ] 配置了合适的缓存大小
- [ ] 定期清理过期数据

### 4.2 缓存优化

- [ ] 热点数据已缓存
- [ ] 缓存命中率 > 80%
- [ ] 有空值缓存（防穿透）
- [ ] 有单飞锁（防击穿）
- [ ] TTL 有抖动（防空崩）
- [ ] 写操作后正确失效缓存
- [ ] 缓存内存占用在可控范围内
- [ ] 有缓存预热机制

### 4.3 API 优化

- [ ] 核心接口响应时间 < 100ms
- [ ] P99 < 500ms
- [ ] 启用了响应缓存
- [ ] 启用了 Gzip 压缩
- [ ] 有合适的限流策略
- [ ] 有熔断降级机制
- [ ] 大接口做了分页
- [ ] 批量操作有专门接口

### 4.4 代码优化

- [ ] 热路径上没有不必要的计算
- [ ] 使用了合适的数据结构
- [ ] 字符串拼接使用 join 而不是 +=
- [ ] 频繁调用的函数加了 lru_cache
- [ ] 惰性加载（lazy loading）适用的属性
- [ ] 避免在循环中做重操作
- [ ] 使用生成器处理大数据
- [ ] 适当使用 __slots__

### 4.5 配置优化

- [ ] 线程池大小合理
- [ ] 连接池大小合理
- [ ] 日志级别合适
- [ ] JSON 序列化使用了快速库
- [ ] 生产环境关闭了调试模式
- [ ] 静态资源有 CDN/缓存
- [ ] 数据库配置已调优

### 4.6 监控告警

- [ ] API 响应时间监控
- [ ] 数据库慢查询监控
- [ ] 缓存命中率监控
- [ ] CPU/内存/磁盘监控
- [ ] 错误率监控
- [ ] QPS 监控
- [ ] 告警阈值已设置
- [ ] 有性能基线数据

---

## 5. 配置调优参考

### 5.1 生产环境推荐配置

```bash
# 缓存
PERF_CACHE_L1_ENABLED=true
PERF_CACHE_L1_MAX_SIZE=10000
PERF_CACHE_L1_TTL=60
PERF_CACHE_L2_ENABLED=false
PERF_QUERY_CACHE_ENABLED=true
PERF_QUERY_CACHE_SIZE=500
PERF_QUERY_CACHE_TTL=30

# 数据库
PERF_DB_POOL_ENABLED=true
PERF_DB_POOL_SIZE=10
SLOW_QUERY_THRESHOLD_MS=1000
DB_CACHE_SIZE_KB=-20000
DB_MMAP_SIZE=268435456

# 日志
PERF_LOG_ASYNC=true
PERF_LOG_QUEUE_SIZE=1000
LOG_LEVEL=INFO
LOG_JSON_FORMAT=true

# API
PERF_API_CACHE_ENABLED=true
PERF_RATE_LIMIT_ENABLED=true
PERF_MAX_CONCURRENT=200
PERF_JSON_LIBRARY=orjson

# 并发
PERF_WORKER_THREADS=16
PERF_IO_THREADS=32
PERF_BATCH_SIZE=100
```

### 5.2 高性能配置（极致性能）

```bash
# 缓存（更大缓存，开启 L2）
PERF_CACHE_L1_MAX_SIZE=20000
PERF_CACHE_L1_TTL=300
PERF_CACHE_L2_ENABLED=true
PERF_CACHE_L2_TYPE=redis

# 数据库（牺牲一点一致性换性能）
PERF_DB_POOL_SIZE=20
DB_CACHE_SIZE_KB=-100000
DB_SYNCHRONOUS=OFF

# 日志（减少日志量）
LOG_LEVEL=WARNING
PERF_LOG_ASYNC=true
PERF_LOG_QUEUE_SIZE=5000

# API
PERF_JSON_LIBRARY=orjson
PERF_MAX_CONCURRENT=500

# 并发
PERF_WORKER_THREADS=32
PERF_IO_THREADS=64
```

### 5.3 开发环境配置

```bash
# 缓存（小缓存，方便调试）
PERF_CACHE_L1_MAX_SIZE=1000
PERF_CACHE_L2_ENABLED=false

# 数据库（更严格的慢查询阈值）
SLOW_QUERY_THRESHOLD_MS=100

# 日志（同步 + 详细 + 彩色）
PERF_LOG_ASYNC=false
LOG_LEVEL=DEBUG
LOG_JSON_FORMAT=false

# API
PERF_RATE_LIMIT_ENABLED=false
```

---

## 6. 性能测试框架使用说明

### 6.1 框架结构

```
tests/performance/
├── __init__.py          # 包初始化
├── conftest.py          # pytest 配置和 fixtures
├── benchmark.py         # 基准测试工具类
├── test_api_benchmark.py    # API 性能基准测试
├── test_db_benchmark.py     # 数据库性能基准测试
├── test_memory_benchmark.py # 内存使用基准测试
└── report.py            # 性能报告生成
```

### 6.2 核心工具类

#### BenchmarkTimer - 高精度计时器

```python
from tests.performance.benchmark import BenchmarkTimer

# 上下文管理器
with BenchmarkTimer() as timer:
    do_something()
print(f"耗时: {timer.elapsed_ms:.2f}ms")

# 装饰器
@BenchmarkTimer.decorator("my_func")
def my_func():
    pass
```

#### BenchmarkStats - 统计计算器

```python
from tests.performance.benchmark import BenchmarkStats

stats = BenchmarkStats(name="my_test")
for i in range(100):
    with BenchmarkTimer() as t:
        do_something()
    stats.add_measurement(t.elapsed_ms)

print(f"均值: {stats.mean:.3f}ms")
print(f"中位数: {stats.median:.3f}ms")
print(f"P95: {stats.p95:.3f}ms")
print(f"P99: {stats.p99:.3f}ms")
print(f"QPS: {stats.qps:.1f}")
print(stats.summary())
```

#### MemoryProfiler - 内存监测

```python
from tests.performance.benchmark import MemoryProfiler, measure_memory

profiler = MemoryProfiler()
profiler.start()
do_something()
snapshot = profiler.stop()
print(f"内存增长: {snapshot.current_mb:.3f}MB")

# 便捷函数
result, snapshot = measure_memory(my_func, arg1, arg2)
```

#### BaselineManager - 基线管理

```python
from tests.performance.benchmark import BaselineManager

manager = BaselineManager()

# 保存基线
manager.save_baseline("my_test", stats, version="v1.0")

# 对比
result = manager.compare("my_test", current_stats, threshold_pct=20)
print(result["status"])  # ok / improvement / regression
print(result["message"])
```

### 6.3 编写性能测试

```python
import pytest
from tests.performance.benchmark import BenchmarkTimer, BenchmarkStats, BenchmarkCollector

pytestmark = pytest.mark.performance

class TestMyModule:
    def test_my_operation(self, benchmark_iterations, benchmark_warmup):
        """我的操作性能测试"""
        stats = BenchmarkStats(name="my_module:my_operation")

        # 预热
        for i in range(benchmark_warmup):
            my_operation(i)

        # 正式测试
        for i in range(benchmark_iterations):
            with BenchmarkTimer() as timer:
                my_operation(i)
            stats.add_measurement(timer.elapsed_ms)

        # 收集结果
        BenchmarkCollector.get_instance().add_result("my_operation", stats)

        # 断言性能达标
        assert stats.mean < 100, f"平均耗时 {stats.mean:.2f}ms 超过阈值"
        print(f"\n{stats.summary()}")
```

### 6.4 生成性能报告

```python
from tests.performance.report import generate_html_report

# 从收集器获取结果
from tests.performance.benchmark import BenchmarkCollector
collector = BenchmarkCollector.get_instance()

results = collector.get_all_results()
memory_results = collector.get_memory_results()

# 生成 HTML 报告
html = generate_html_report(results, memory_results, environment="production")

with open("performance_report.html", "w", encoding="utf-8") as f:
    f.write(html)
```

---

## 附录：性能优化原则

1. **先测量，再优化**：不要凭感觉优化，用数据说话
2. **避免过早优化**：先让功能正确工作，再考虑性能
3. **避免过度优化**：优化到满足需求即可，不要追求极致
4. **保持代码可读性**：优化不应以牺牲可维护性为代价
5. **一次只改一个变量**：方便定位优化效果和引入的问题
6. **优化后验证**：确保优化有效，且没有引入新问题
7. **记录优化过程**：记录做了什么、效果如何，方便后续参考
8. **关注用户体验**：性能优化的最终目标是提升用户体验
