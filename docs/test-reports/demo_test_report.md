# 云汐系统 v1.1 · 测试报告

> 自动化测试执行报告
> 生成时间: 2026-07-08 16:11:49

## 📊 概览

❌ **测试结果: 未通过**

| 指标 | 数值 |
|------|------|
| 总用例数 | 42 |
| ✅ 通过 | 37 |
| ❌ 失败 | 3 |
| ⏭️ 跳过 | 2 |
| ⚠️ 错误 | 0 |
| 📈 通过率 | **88.1%** |
| ⏱️ 总耗时 | 12.53s |

## 📦 按模块统计

| 模块 | 总数 | 通过 | 失败 | 跳过 | 通过率 | 耗时 |
|------|------|------|------|------|--------|------|
| `tests` | 36 | ✅ 31 | ❌ 3 | ⏭️ 2 | 86.1% | 19.74s |


## ❌ 失败用例详情 (3)

### 1. `tests/test_m8/test_auth_api.py::TestAuth::test_token_refresh`

- **结果**: failed
- **耗时**: 0.156s
- **错误**: AssertionError

```
AssertionError: 预期返回新 token，但返回了 None

Stacktrace:
  File "test_auth_api.py", line 45, in test_token_refresh
    assert result['access_token'] is not None
AssertionError
```

### 2. `tests/test_m1/test_m8_integration.py::TestM8Integration::test_agent_registration`

- **结果**: failed
- **耗时**: 2.345s
- **错误**: ConnectionError: Connection refused on port 18080

```
ConnectionError: 无法连接到 M8 管理台

Stacktrace:
  File "test_m8_integration.py", line 78, in test_agent_registration
    response = client.post('/api/agents/register', json=agent_data)
  File "client.py", line 120, in post
    raise ConnectionError(f"Connection failed: {e}")
ConnectionError: Connection refused on port 18080
```

### 3. `tests/test_m3/test_graph_query.py::TestGraph::test_complex_query`

- **结果**: failed
- **耗时**: 0.789s
- **错误**: ValueError: Result count mismatch

```
ValueError: 图谱查询返回结果数量不匹配
  期望: 5
  实际: 3

Stacktrace:
  File "test_graph_query.py", line 112, in test_complex_query
    assert len(results) == 5
ValueError: Result count mismatch
```


## 🖥️ 运行环境

| 项目 | 信息 |
|------|------|
| 项目名称 | 云汐系统 v1.1 |
| Python 版本 | 3.10.11 |
| 操作系统 | Windows |
| 平台 | Windows-10-10.0.26200-SP0 |
| 架构 | AMD64 |
| 测试时间 | 2026-07-08 16:11:49 |

---

*本报告由云汐系统自动化测试框架自动生成*
