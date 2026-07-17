# 云汐项目测试体系

## 概述

本文档描述云汐项目（yunxi-project）的测试框架、测试分类、编写规范、覆盖率目标和质量工具。

## 测试框架与工具

### 核心框架

| 工具 | 用途 | 配置文件 |
|------|------|----------|
| pytest | 测试框架 | `pytest.ini` |
| pytest-cov | 代码覆盖率 | `.coveragerc` |
| pytest-asyncio | 异步测试支持 | - |
| pytest-xdist | 并行测试 | - |
| pytest-timeout | 测试超时控制 | - |
| pytest-rerunfailures | 失败重跑 | - |
| pytest-mock | Mock 工具增强 | - |
| httpx / TestClient | HTTP 测试 | - |

### 质量工具

| 工具 | 用途 | 配置文件 |
|------|------|----------|
| ruff | Lint + 格式化 + 安全检查 | `pyproject.toml` |
| mypy | 类型检查 | `pyproject.toml` |
| bandit | 安全扫描 | `.bandit` |
| radon | 复杂度/可维护性 | `.radon` |
| pre-commit | 提交前钩子 | `.pre-commit-config.yaml` |

## 项目结构

```
tests/
├── conftest.py              # 全局配置和 fixtures
├── pytest.ini               # pytest 配置（项目根目录）
├── .coveragerc              # 覆盖率配置（项目根目录）
├── README.md                # 本文档
│
├── utils/                   # 共享测试工具
│   ├── __init__.py
│   ├── api_client.py        # 统一 API 测试客户端
│   ├── data_generator.py    # 测试数据工厂
│   ├── mock_helpers.py      # Mock 辅助函数
│   ├── assertions.py        # 自定义断言工具
│   └── fixtures.py          # 可复用测试 Fixtures
│
├── test_shared/             # shared/core 模块测试
│   ├── test_config.py       # 配置模块测试
│   ├── test_errors_new.py   # 错误码模块测试
│   ├── test_responses_new.py# 响应格式测试
│   ├── test_auth.py         # 认证工具测试
│   └── test_logger.py       # 日志工具测试
│
├── test_m8/                 # M8 控制塔模块测试
├── test_m9/                 # M9 开发工坊模块测试
├── test_m11/                # M11 MCP 总线模块测试
│
├── integration/             # 集成测试
│   ├── test_module_health.py
│   ├── test_api_gateway.py
│   ├── test_auth_flow.py
│   └── test_database_migration.py
│
├── test_integration/        # 端到端集成测试
│
└── reports/                 # 测试报告输出
    ├── coverage_html/       # HTML 覆盖率报告
    ├── coverage.xml         # XML 覆盖率报告
    ├── coverage.json        # JSON 覆盖率报告
    └── pytest.log           # 测试日志
```

## 如何运行测试

### 前置条件

```bash
pip install -r requirements-dev.txt
```

### 基础命令

```bash
# 运行所有测试
pytest

# 运行指定模块的测试
pytest tests/test_m8/
pytest tests/test_m9/
pytest tests/test_m11/
pytest tests/test_shared/

# 运行集成测试
pytest tests/integration/

# 运行单元测试（排除集成测试）
pytest -m "not integration"

# 运行标记为 slow 的测试
pytest -m slow

# 运行冒烟测试（CI 快速验证）
pytest -m smoke
```

### 并行测试

```bash
# 使用 pytest-xdist 并行运行（自动检测 CPU 核心数）
pytest -n auto

# 指定并行进程数
pytest -n 4
```

### 失败重跑

```bash
# 对 flaky 标记的测试自动重跑 2 次
pytest --reruns 2 --only-rerun=flaky

# 对所有失败的测试重跑 1 次
pytest --reruns 1
```

### 测试超时

```bash
# 设置全局超时（已在 pytest.ini 中配置为 30s）
pytest --timeout=60

# 单个测试函数设置超时
@pytest.mark.timeout(120)
def test_slow_operation():
    ...
```

### 覆盖率报告

```bash
# 生成终端摘要 + 未覆盖行
pytest --cov=shared/core --cov=shared/data --cov-report=term-missing

# 生成 HTML 报告
pytest --cov=shared/core --cov=shared/data --cov-report=html

# 生成 XML 报告（CI 使用）
pytest --cov=shared/core --cov=shared/data --cov-report=xml

# 多种格式同时输出
pytest --cov=shared/core --cov-report=term-missing --cov-report=html --cov-report=xml

# 使用脚本运行
python scripts/run_coverage.py --html
```

### 测试性能监控

```bash
# 显示最慢的 20 个测试（已在 pytest.ini 中配置）
pytest --durations=20 --durations-min=1.0

# 生成 HTML 测试报告
pytest --html=tests/reports/test_report.html --self-contained-html
```

## 测试分类

### 按测试级别

| 标记 | 类型 | 说明 | 运行方式 |
|------|------|------|----------|
| `@pytest.mark.smoke` | 冒烟测试 | 核心功能快速验证（CI 必跑） | `pytest -m smoke` |
| `@pytest.mark.unit` | 单元测试 | 测试单个函数/类/模块，mock 外部依赖 | `pytest -m unit` |
| `@pytest.mark.integration` | 集成测试 | 测试模块间交互、API 调用链 | `pytest -m integration` |
| `@pytest.mark.e2e` | 端到端测试 | 完整业务流程测试 | `pytest -m e2e` |
| `@pytest.mark.security` | 安全测试 | 安全相关功能验证 | `pytest -m security` |
| `@pytest.mark.performance` | 性能测试 | 性能基准与回归测试 | `pytest -m performance` |
| `@pytest.mark.slow` | 慢速测试 | 执行时间较长的测试（默认排除） | `pytest -m slow` |
| `@pytest.mark.flaky` | 不稳定测试 | 偶发失败的测试，启用重跑 | `pytest -m flaky --reruns 2` |

### 按模块

| 标记 | 模块 |
|------|------|
| `@pytest.mark.m0` ~ `@pytest.mark.m12` | M0~M12 各模块 |
| `@pytest.mark.shared` | shared 公共模块 |
| `@pytest.mark.gateway` | API 网关 |

## 测试工具使用

### Mock 辅助函数

```python
from tests.utils.mock_helpers import (
    mock_http_response,
    mock_async_http_response,
    mock_httpx_client,
    mock_db_session,
    capture_logs,
    patch_env_vars,
    async_return,
    async_raise,
)

# Mock HTTP 响应
def test_api_call():
    mock_resp = mock_http_response(200, {"code": 0, "data": "ok"})
    with patch("requests.get", return_value=mock_resp):
        result = some_function()
        assert result == "ok"

# 捕获日志
def test_logging():
    with capture_logs("my_module") as logs:
        do_something()
        assert any("error" in msg.lower() for msg in logs.messages)
```

### 自定义断言

```python
from tests.utils.assertions import (
    assert_api_success,
    assert_api_error,
    assert_api_pagination,
    assert_dict_contains,
    assert_is_valid_uuid,
    assert_execution_time,
)

def test_api_response():
    result = client.get("/api/users")
    assert_api_success(result)
    assert_api_pagination(result["data"])

def test_performance():
    assert_execution_time(my_function, max_seconds=1.0, args=(arg1,))
```

### 测试数据工厂

```python
from tests.utils.data_generator import TestDataGenerator

gen = TestDataGenerator(seed=42)  # 固定种子，可复现

user = gen.generate_user()
task = gen.generate_task()
modules = gen.generate_all_modules_status()
```

## 测试编写规范

### 1. 文件命名

- 测试文件以 `test_` 开头
- 测试类以 `Test` 开头
- 测试方法以 `test_` 开头

### 2. 测试结构（AAA 模式）

```python
import pytest

class TestFeatureName:
    """功能描述"""

    @pytest.mark.unit
    @pytest.mark.module
    def test_specific_behavior(self, fixture_name):
        """测试具体行为"""
        # Arrange - 准备测试数据
        data = ...

        # Act - 执行操作
        result = function_under_test(data)

        # Assert - 验证结果
        assert result == expected_value
```

### 3. 命名约定

- 测试方法名：`test_<被测试对象>_<预期行为>`
  - 正确：`test_login_success_with_valid_credentials`
  - 错误：`test_login_1`

### 4. 独立性原则

- 每个测试用例独立运行，不依赖其他测试的执行结果
- 使用 fixtures 准备和清理测试数据
- 不依赖测试执行顺序

### 5. Mock 原则

- 单元测试中 mock 所有外部依赖（数据库、网络、文件系统等）
- 集成测试中使用真实的轻量级依赖（内存 SQLite、临时目录等）
- 使用 `unittest.mock` 或 `pytest-mock` 进行 mock

### 6. 跳过测试

当测试依赖的模块/接口不存在时，使用 `pytest.skip()` 跳过：

```python
def test_some_feature(self):
    try:
        from some_module import some_function
    except ImportError:
        pytest.skip("some_module 不可用")
```

### 7. 参数化测试

对多组输入输出使用 `@pytest.mark.parametrize`：

```python
@pytest.mark.parametrize("input,expected", [
    (1, 2),
    (2, 4),
    (3, 6),
])
def test_double(input, expected):
    assert double(input) == expected
```

### 8. 超时设置

为可能挂起的测试设置超时：

```python
@pytest.mark.timeout(30)  # 30 秒超时
def test_network_call():
    ...
```

## 覆盖率目标

### 总体目标

| 模块 | 目标覆盖率 | 说明 |
|------|-----------|------|
| shared/core | >= 70% | 核心工具库，高覆盖率 |
| shared/data | >= 65% | 数据层模块 |
| M8 控制塔 | >= 60% | 核心业务模块 |
| M9 开发工坊 | >= 60% | 核心业务模块 |
| M11 MCP 总线 | >= 60% | 核心业务模块 |
| 整体核心模块 | >= 60% | 加权平均 |

### 覆盖率统计范围

**包含**:
- `shared/core/` - 公共核心模块
- `shared/data/` - 公共数据模块
- `shared/business/` - 公共业务模块
- `M8-control-tower/backend/` - M8 后端代码
- `M9-dev-workshop/backend/` - M9 后端代码
- `M11-mcp-bus/src/` - M11 源代码

**排除**:
- `tests/` - 测试代码
- `*/migrations/` - 数据库迁移文件
- `__pycache__/` - Python 缓存
- `*.pyc` - 编译的 Python 文件
- `_archive/` / `archive/` - 存档代码
- `frontend/` - 前端代码
- 虚拟环境目录

### 查看覆盖率

```bash
# 终端简要报告
pytest --cov=shared/core --cov-report=term-missing

# HTML 详细报告（可点击查看每行覆盖情况）
pytest --cov=shared/core --cov-report=html
# 打开 htmlcov/index.html
```

## 代码质量检查

### 一键运行所有检查

```bash
# Windows
.\scripts\quality_check.ps1

# 快速检查（仅 lint + format）
.\scripts\quality_check.ps1 -Quick

# 仅核心模块
.\scripts\quality_check.ps1 -CoreOnly

# 自动修复模式
.\scripts\quality_check.ps1 -Fix
```

### Ruff 代码风格检查

```bash
# 检查
ruff check shared/core

# 自动修复
ruff check --fix shared/core

# 格式化
ruff format shared/core

# 格式化检查（不修改文件）
ruff format --check shared/core
```

### Mypy 类型检查

```bash
# 检查核心模块
mypy shared/core shared/data --config-file=pyproject.toml

# 检查单个文件
mypy shared/core/config.py
```

### Bandit 安全扫描

```bash
# 扫描核心模块（中等级别及以上）
bandit -r shared/core shared/data -ll -c .bandit

# 全量扫描（所有级别）
bandit -r shared -c .bandit
```

### Radon 复杂度分析

```bash
# 圈复杂度（显示 C 级及以上）
radon cc shared/core -a -nc

# 可维护性指数
radon mi shared/core -s

# 原始度量
radon raw shared/core -s
```

### Pre-commit 钩子

```bash
# 安装钩子
pre-commit install

# 手动运行所有检查
pre-commit run --all-files

# 运行单个钩子
pre-commit run ruff --all-files

# 跳过钩子提交（不推荐）
git commit --no-verify
```

## 常用命令速查

```bash
# 快速运行单元测试
pytest -m "unit and not slow" -q

# 运行 M8 模块测试
pytest tests/test_m8/ -v

# 运行集成测试
pytest tests/integration/ -v

# 生成覆盖率报告
pytest --cov=shared/core --cov=shared/data --cov=shared/business \
       --cov-report=html --cov-report=term-missing

# 并行运行测试
pytest -n auto -m "unit and not integration"

# 运行单个测试文件
pytest tests/test_m8/test_auth_middleware.py -v

# 运行单个测试方法
pytest tests/test_m8/test_auth_middleware.py::TestAuthAPI::test_login_success_admin -v

# 仅运行上次失败的测试
pytest --lf

# 失败时进入调试
pytest --pdb
```

## 常见问题

### Q: 测试很多被跳过了怎么办？

A: 很多测试使用了 `pytest.skip()` 来处理模块不可用的情况。确保：
1. 所有依赖已安装：`pip install -r requirements.txt`
2. 在项目根目录运行测试
3. 环境变量配置正确（如 `ENV=testing`）

### Q: 如何添加新的测试？

A:
1. 在对应模块的测试目录下创建 `test_<功能>.py`
2. 编写测试类和方法
3. 添加适当的标记（`@pytest.mark.unit` 等）
4. 运行测试验证通过

### Q: 覆盖率不够怎么办？

A:
1. 先分析未覆盖的代码：打开覆盖率 HTML 报告
2. 优先覆盖核心业务逻辑
3. 对于难以测试的边界情况，可以使用 `# pragma: no cover` 注释排除

### Q: Mypy 报错太多怎么办？

A:
1. 从核心模块开始逐步修复
2. 使用 `# type: ignore` 临时忽略已知问题（需标注原因）
3. 配置文件中已设置渐进式策略，核心模块严格度更高
4. 运行 `mypy --config-file=pyproject.toml shared/core` 仅检查核心模块
