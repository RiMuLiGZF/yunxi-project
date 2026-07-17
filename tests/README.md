# 云汐项目测试体系

## 概述

本文档描述云汐项目（yunxi-project）的测试框架、测试分类、编写规范和覆盖率目标。

## 测试框架与工具

### 核心框架

- **测试框架**: pytest
- **覆盖率工具**: pytest-cov (coverage.py)
- **HTTP 测试**: httpx (FastAPI TestClient)
- **Mock 工具**: unittest.mock

### 项目结构

```
tests/
├── conftest.py              # 统一配置和 fixtures
├── pytest.ini               # pytest 配置（项目根目录）
├── .coveragerc              # 覆盖率配置（项目根目录）
├── README.md                # 本文档
│
├── test_shared/             # shared/core 模块测试
│   ├── test_config.py       # 配置模块测试
│   ├── test_errors_new.py   # 错误码模块测试
│   ├── test_responses_new.py# 响应格式测试
│   ├── test_auth.py         # 认证工具测试
│   └── test_logger.py       # 日志工具测试
│
├── test_m8/                 # M8 控制塔模块测试
│   ├── test_health_check.py     # 健康检查接口测试
│   ├── test_module_management.py# 模块管理接口测试
│   ├── test_backup_scheduler.py # 备份调度接口测试
│   └── test_auth_middleware.py  # 认证中间件测试
│
├── test_m9/                 # M9 开发工坊模块测试
│   ├── test_project_crud.py     # 项目 CRUD 测试
│   ├── test_file_management.py  # 文件管理测试
│   └── test_auth_and_workspace.py # 认证与工作空间测试
│
├── test_m11/                # M11 MCP 总线模块测试
│   ├── test_mcp_protocol.py     # MCP 协议与 API Key 测试
│   └── test_tools_and_sse.py    # 工具注册与 SSE 测试
│
└── integration/             # 集成测试
    ├── test_module_health.py    # 模块间健康检查集成测试
    ├── test_api_gateway.py      # API Gateway 转发集成测试
    ├── test_auth_flow.py        # 认证流程集成测试
    └── test_database_migration.py# 数据库迁移集成测试
```

## 如何运行测试

### 前置条件

```bash
pip install pytest pytest-cov httpx
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
```

### 覆盖率报告

```bash
# 生成覆盖率报告
pytest --cov=. --cov-report=term-missing --cov-report=html

# 或者使用脚本
python scripts/run_coverage.py

# 只统计核心模块覆盖率
pytest --cov=shared/core --cov=M8-control-tower --cov=M9-dev-workshop --cov=M11-mcp-bus
```

覆盖率报告会生成在 `htmlcov/` 目录下，打开 `htmlcov/index.html` 查看详细报告。

## 测试分类

### 按测试级别

| 标记 | 类型 | 说明 | 运行方式 |
|------|------|------|----------|
| `@pytest.mark.unit` | 单元测试 | 测试单个函数/类/模块，mock 外部依赖 | `pytest -m unit` |
| `@pytest.mark.integration` | 集成测试 | 测试模块间交互、API 调用链 | `pytest -m integration` |
| `@pytest.mark.e2e` | 端到端测试 | 完整业务流程测试 | `pytest -m e2e` |

### 按速度

| 标记 | 说明 |
|------|------|
| `@pytest.mark.slow` | 慢速测试（可能涉及 IO、网络等） |
| 默认（无标记） | 快速测试（纯函数、内存操作） |

### 按模块

| 标记 | 模块 |
|------|------|
| `@pytest.mark.m8` | M8 控制塔 |
| `@pytest.mark.m9` | M9 开发工坊 |
| `@pytest.mark.m11` | M11 MCP 总线 |
| `@pytest.mark.shared` | shared 公共模块 |

### 按功能

| 标记 | 功能 |
|------|------|
| `@pytest.mark.auth` | 认证相关 |
| `@pytest.mark.health` | 健康检查 |
| `@pytest.mark.db` | 数据库相关 |
| `@pytest.mark.api` | API 接口 |
| `@pytest.mark.error` | 错误处理 |

## 测试 Fixtures

### 全局 Fixtures（conftest.py）

| Fixture | 作用域 | 说明 |
|---------|--------|------|
| `project_root` | session | 项目根目录路径 |
| `test_workspace_dir` | function | 测试工作空间目录（临时） |
| `m8_app` / `m8_client` | function | M8 测试应用/客户端 |
| `m9_app` / `m9_client` | function | M9 测试应用/客户端 |
| `m11_app` / `m11_client` | function | M11 测试应用/客户端 |
| `gateway_app` / `gateway_client` | function | API Gateway 测试应用/客户端 |
| `auth_headers` | function | JWT 认证头 |
| `api_key_headers` | function | API Key 认证头 |
| `test_user` | function | 测试用户 |
| `m8_db_session` | function | M8 数据库会话 |
| `m11_db_session` | function | M11 数据库会话 |

## 测试编写规范

### 1. 文件命名

- 测试文件以 `test_` 开头
- 测试类以 `Test` 开头
- 测试方法以 `test_` 开头

### 2. 测试结构

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
- 使用 `unittest.mock` 进行 mock

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

## 覆盖率目标

### 总体目标

| 模块 | 目标覆盖率 | 说明 |
|------|-----------|------|
| shared/core | >= 70% | 核心工具库，高覆盖率 |
| M8 控制塔 | >= 60% | 核心业务模块 |
| M9 开发工坊 | >= 60% | 核心业务模块 |
| M11 MCP 总线 | >= 60% | 核心业务模块 |
| 整体核心模块 | >= 60% | 加权平均 |

### 覆盖率统计范围

**包含**:
- `shared/core/` - 公共核心模块
- `M8-control-tower/backend/` - M8 后端代码
- `M9-dev-workshop/backend/` - M9 后端代码
- `M11-mcp-bus/src/` - M11 源代码

**排除**:
- `tests/` - 测试代码
- `*/migrations/` - 数据库迁移文件
- `*/static/` - 静态文件
- `*/templates/` - 模板文件
- `node_modules/` - Node.js 依赖
- `__pycache__/` - Python 缓存
- `*.pyc` - 编译的 Python 文件
- `htmlcov/` - 覆盖率报告
- `.venv/` / `venv/` - 虚拟环境

### 查看覆盖率

```bash
# 终端简要报告
pytest --cov=. --cov-report=term-missing

# HTML 详细报告（可点击查看每行覆盖情况）
pytest --cov=. --cov-report=html
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
pytest --cov=shared/core --cov=M8-control-tower/backend \
       --cov=M9-dev-workshop/backend --cov=M11-mcp-bus/src \
       --cov-report=html --cov-report=term-missing

# 运行单个测试文件
pytest tests/test_m8/test_auth_middleware.py -v

# 运行单个测试方法
pytest tests/test_m8/test_auth_middleware.py::TestAuthAPI::test_login_success_admin -v
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
1. 先分析未覆盖的代码：打开 `htmlcov/index.html`
2. 优先覆盖核心业务逻辑
3. 对于难以测试的边界情况，可以使用 `# pragma: no cover` 注释排除
