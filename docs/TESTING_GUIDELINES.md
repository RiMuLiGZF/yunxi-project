# 云汐系统测试规范

> **文档版本**：v1.0
> **更新日期**：2026-07-18
> **适用范围**：云汐系统全模块测试
> **对应问题**：TST-004（测试目录结构不统一）

---

## 目录

- [1. 概述](#1-概述)
- [2. 测试目录结构规范](#2-测试目录结构规范)
- [3. 测试文件命名规范](#3-测试文件命名规范)
- [4. Pytest Markers 使用规范](#4-pytest-markers-使用规范)
- [5. 测试编写指南](#5-测试编写指南)
- [6. Fixture 使用规范](#6-fixture-使用规范)
- [7. 覆盖率目标](#7-覆盖率目标)
- [8. 测试分类与执行](#8-测试分类与执行)
- [9. 当前测试目录现状](#9-当前测试目录现状)
- [10. 迁移计划](#10-迁移计划)

---

## 1. 概述

本文档定义云汐系统的测试规范，包括测试目录结构、命名规范、编写指南、覆盖率目标等。目的是统一各模块的测试组织方式，提高测试质量和可维护性。

### 1.1 测试金字塔

```
        /\                 ← E2E 测试（少量）
       /--\
      /----\              ← 集成测试（适量）
     /------\
    /--------\            ← 组件测试（较多）
   /----------\
  /------------\          ← 单元测试（大量，基础）
 /--------------\
```

- **单元测试**：测试单个函数/类的行为，不依赖外部系统
- **组件测试**：测试模块内多个组件的协同
- **集成测试**：测试模块间的交互
- **E2E 测试**：从用户视角测试完整业务流程

---

## 2. 测试目录结构规范

### 2.1 目录结构总览

```
yunxi-project/
├── tests/                          # 根级测试目录（跨模块测试）
│   ├── unit/                       # 根级单元测试（通用工具等）
│   ├── integration/                # 集成测试（模块间交互）
│   ├── e2e/                        # 端到端测试
│   ├── performance/                # 性能测试
│   ├── test_shared/                # shared 模块测试（历史位置，逐步迁移）
│   ├── test_m{1..12}/              # 各模块集成测试（历史位置，逐步迁移）
│   ├── utils/                      # 测试工具函数
│   ├── conftest.py                 # 根级 pytest 配置
│   └── README.md                   # 测试说明文档
│
├── shared/
│   └── tests/                      # shared 核心库单元测试
│       ├── test_jwt_boundary.py
│       ├── test_password_boundary.py
│       ├── test_config_boundary.py
│       └── ...
│
├── M1-agent-hub/
│   └── tests/                      # M1 模块测试
│       ├── unit/                   # 单元测试
│       ├── integration/            # 模块内集成测试
│       └── conftest.py
│
├── M2-skills-cluster/
│   └── skill_cluster/
│       └── tests/                  # M2 模块测试（根据包结构）
│           ├── unit/
│           └── integration/
│
├── M8-control-tower/
│   └── backend/
│       └── tests/                  # M8 后端测试（根据模块结构）
│           ├── unit/
│           └── integration/
│
├── API-Gateway/
│   └── tests/                      # 网关模块测试
│       ├── unit/
│       └── integration/
│
└── {其他模块}/
    └── tests/                      # 各模块自己的测试目录
        ├── unit/
        └── integration/
```

### 2.2 目录位置规则

| 模块类型 | 测试目录位置 | 说明 |
|---------|------------|------|
| 扁平结构模块 | `{module}/tests/` | 如 `M1-agent-hub/tests/`、`API-Gateway/tests/` |
| 包结构模块 | `{module}/{package}/tests/` | 如 `M2-skills-cluster/skill_cluster/tests/` |
| 有 backend 子目录 | `{module}/backend/tests/` | 如 `M8-control-tower/backend/tests/`、`M9-dev-workshop/backend/tests/`、`M12-security-shield/backend/tests/` |
| shared 核心库 | `shared/tests/` | 共享核心库的单元测试 |
| 跨模块集成测试 | `tests/integration/` | 根级集成测试 |
| E2E 测试 | `tests/e2e/` | 端到端测试 |
| 性能测试 | `tests/performance/` | 性能基准测试 |

### 2.3 各模块测试目录位置（现状）

| 模块 | 测试目录 | 结构类型 | 状态 |
|------|---------|---------|------|
| M1 多Agent集群 | `M1-agent-hub/tests/` | 扁平结构 | 已存在 |
| M2 技能集群 | `M2-skills-cluster/skill_cluster/tests/` | 包结构 | 已存在 |
| M3 端云协同 | `M3-edge-cloud/edge_cloud_kernel/tests/` | 包结构 | 已存在 |
| M4 场景引擎 | `M4-scene-engine/tests/` | 扁平结构 | 已存在 |
| M5 潮汐记忆 | `M5-tide-memory/tests/` | 扁平结构 | 已存在 |
| M6 硬件外设 | `M6-hardware-peripheral/tests/` | 扁平结构 | 已存在 |
| M8 控制塔 | `M8-control-tower/backend/tests/` | backend 子目录 | 已存在 |
| M9 开发者工坊 | `M9-dev-workshop/backend/tests/` | backend 子目录 | 已存在 |
| M10 系统卫士 | `M10-system-guard/tests/` | 扁平结构 | 已存在 |
| M11 MCP总线 | `M11-mcp-bus/tests/` | 扁平结构 | 已存在 |
| M12 安全盾 | `M12-security-shield/backend/tests/` | backend 子目录 | 已存在 |
| M0 主理人控制台 | `M0-principal-console/tests/` | 扁平结构 | 已存在 |
| API 网关 | `API-Gateway/tests/` | 扁平结构 | 已存在 |
| shared 核心库 | `shared/tests/` | 核心库 | 已存在 |
| 根级测试 | `tests/` | 根级 | 已存在 |

---

## 3. 测试文件命名规范

### 3.1 文件命名

测试文件必须以 `test_` 开头，使用小写蛇形命名法：

```
test_{被测对象}_{测试类型}.py
```

**示例**：

| 文件名 | 说明 |
|--------|------|
| `test_auth.py` | 认证模块基本测试 |
| `test_jwt_boundary.py` | JWT 边界条件测试 |
| `test_password_boundary.py` | 密码哈希边界测试 |
| `test_config_boundary.py` | 配置模块边界测试 |
| `test_circuit_breaker.py` | 熔断器测试 |
| `test_rate_limiter.py` | 限流器测试 |
| `test_api_integration.py` | API 集成测试 |
| `test_user_journey.py` | 用户旅程 E2E 测试 |
| `test_api_benchmark.py` | API 性能基准测试 |

### 3.2 测试类命名

测试类使用 `Test` 前缀，大驼峰命名法：

```python
class TestUserAuthentication:
    """用户认证测试"""

class TestJWTExpiryBoundary:
    """JWT 过期边界测试"""
```

### 3.3 测试函数命名

测试函数使用 `test_` 前缀，描述性命名，清晰说明测试的场景和预期：

```python
def test_empty_password_raises_value_error():
    """空密码应抛出 ValueError"""

def test_expired_token_decode_returns_none():
    """过期 Token 解码应返回 None"""

def test_admin_can_access_protected_endpoint():
    """管理员可以访问受保护端点"""
```

**命名模式**：

```
test_{动作/条件}_{预期结果}
```

---

## 4. Pytest Markers 使用规范

### 4.1 标准 Markers

| Marker | 含义 | 说明 |
|--------|------|------|
| `@pytest.mark.unit` | 单元测试 | 测试单个函数/类，不依赖外部系统 |
| `@pytest.mark.integration` | 集成测试 | 测试多个组件或模块间的交互 |
| `@pytest.mark.e2e` | 端到端测试 | 测试完整业务流程，需要完整环境 |
| `@pytest.mark.performance` | 性能测试 | 性能基准、负载测试 |
| `@pytest.mark.slow` | 慢测试 | 执行时间较长的测试，CI 中可选执行 |
| `@pytest.mark.security` | 安全测试 | 安全相关的测试用例 |
| `@pytest.mark.boundary` | 边界测试 | 边界条件和异常路径测试 |

### 4.2 Marker 使用示例

```python
import pytest

@pytest.mark.unit
def test_password_hash_basic():
    """单元测试：基本密码哈希"""
    pass

@pytest.mark.boundary
def test_password_hash_empty():
    """边界测试：空密码"""
    pass

@pytest.mark.integration
def test_api_login_flow():
    """集成测试：API 登录流程"""
    pass

@pytest.mark.slow
@pytest.mark.performance
def test_throughput_benchmark():
    """性能测试：吞吐量基准"""
    pass
```

### 4.3 测试执行命令

```bash
# 执行所有单元测试
pytest -m unit

# 执行所有集成测试
pytest -m integration

# 执行所有 E2E 测试
pytest -m e2e

# 排除慢测试
pytest -m "not slow"

# 只执行边界测试
pytest -m boundary

# 执行指定模块的测试
pytest M1-agent-hub/tests/

# 执行 shared 测试
pytest shared/tests/

# 生成覆盖率报告
pytest --cov=shared/core --cov-report=html shared/tests/
```

### 4.4 pytest.ini / pyproject.toml 配置

建议在项目根目录配置 pytest markers：

```ini
# pytest.ini
[pytest]
markers =
    unit: 单元测试
    integration: 集成测试
    e2e: 端到端测试
    performance: 性能测试
    slow: 慢测试
    security: 安全测试
    boundary: 边界条件测试
```

---

## 5. 测试编写指南

### 5.1 AAA 模式

每个测试用例遵循 **Arrange-Act-Assert** 模式：

```python
def test_user_login_success():
    # Arrange - 准备测试数据和环境
    user = create_user(username="testuser", password="TestPass123!")
    
    # Act - 执行被测操作
    result = login("testuser", "TestPass123!")
    
    # Assert - 验证结果
    assert result.success is True
    assert result.user.username == "testuser"
```

### 5.2 一个测试一个断言点

每个测试函数专注于验证一个行为：

```python
# 好的做法
def test_empty_password_raises_error():
    with pytest.raises(ValueError):
        hash_password("")

def test_very_long_password_is_hashed():
    result = hash_password("a" * 1000)
    assert len(result) > 0

# 避免的做法
def test_password_hash():
    # 太多断言，失败时难以定位问题
    assert hash_password("test") != "test"
    assert verify_password("test", hash_password("test"))
    with pytest.raises(ValueError):
        hash_password("")
```

### 5.3 参数化测试

使用 `@pytest.mark.parametrize` 对多组输入输出进行测试：

```python
@pytest.mark.parametrize("empty_input", [
    "",
    None,
    "   ",
    "\t\n",
])
def test_decode_empty_token_returns_none(empty_input):
    result = jwt_handler.decode_token(empty_input)
    assert result is None
```

### 5.4 边界值测试原则

对每个输入参数，至少测试以下边界：

| 边界类型 | 示例 |
|---------|------|
| 最小值 | 端口 1、密码长度 0 |
| 最小值-1 | 端口 0、密码长度 -1 |
| 最大值 | 端口 65535、bcrypt 72 字节 |
| 最大值+1 | 端口 65536、bcrypt 73 字节 |
| 空值 | `""`、`None`、`[]`、`{}` |
| 非法值 | 类型错误、格式错误 |
| 特殊值 | Unicode、emoji、控制字符 |
| 超长值 | 10000 字符、10MB 数据 |

### 5.5 异常测试

使用 `pytest.raises` 测试预期的异常：

```python
def test_empty_password_raises_value_error():
    with pytest.raises(ValueError, match="密码不能为空"):
        hash_password("")
```

### 5.6 测试数据隔离

- 每个测试用例的数据相互独立
- 使用 fixture 管理测试数据的创建和清理
- 不依赖测试执行顺序
- 测试完成后清理测试数据

### 5.7 测试描述

每个测试文件、类、函数都应有 docstring 说明测试目的：

```python
"""
JWT 模块边界条件与异常路径测试

对应问题：TST-006
覆盖场景：空 Token、过期 Token、篡改签名、算法不匹配等
"""

class TestExpiredToken:
    """过期 Token 边界测试"""

    def test_expired_access_token_decode_fails(self):
        """已过期的 Token 解码应返回 None"""
        pass
```

---

## 6. Fixture 使用规范

### 6.1 Fixture 作用域

| 作用域 | 适用场景 | 示例 |
|-------|---------|------|
| `function` | 每个测试函数使用一次（默认） | 测试数据、Mock 对象 |
| `class` | 每个测试类使用一次 | 类级共享资源 |
| `module` | 每个测试模块使用一次 | 数据库连接、配置加载 |
| `session` | 整个测试会话使用一次 | 测试服务启动、全局配置 |

### 6.2 Fixture 命名

```python
# 资源型 fixture - 名词
@pytest.fixture
def db_connection():
    ...

@pytest.fixture
def jwt_handler():
    ...

# 数据型 fixture - 描述数据内容
@pytest.fixture
def test_user():
    ...

@pytest.fixture
def sample_token():
    ...
```

### 6.3 常用 Fixture 示例

```python
# conftest.py
import pytest
from shared.core.auth.jwt import JWTHandler, JWTConfig

@pytest.fixture(scope="module")
def jwt_handler():
    """JWT 处理器 fixture"""
    config = JWTConfig(
        secret="test-secret-key-32-characters-minimum!!",
        algorithm="HS256",
        require_secure_secret=False,
    )
    return JWTHandler(config)

@pytest.fixture
def sample_user():
    """示例用户数据"""
    return {
        "id": 1,
        "username": "testuser",
        "email": "test@example.com",
    }
```

---

## 7. 覆盖率目标

### 7.1 覆盖率指标

| 模块类型 | 行覆盖率目标 | 分支覆盖率目标 | 说明 |
|---------|------------|-------------|------|
| 核心安全模块（auth/jwt/password） | >= 90% | >= 85% | 安全关键代码必须高覆盖 |
| 核心配置模块（config） | >= 85% | >= 80% | 配置模块高覆盖 |
| shared 通用库 | >= 80% | >= 75% | 通用库应高覆盖 |
| 业务模块 | >= 70% | >= 60% | 业务逻辑核心路径覆盖 |
| 整体目标 | >= 75% | >= 65% | 全系统平均覆盖率 |

### 7.2 覆盖率检查

```bash
# 生成覆盖率报告
pytest --cov=shared/core --cov-report=html --cov-report=term-missing shared/tests/

# 检查覆盖率是否达标
pytest --cov=shared/core --cov-fail-under=80 shared/tests/
```

### 7.3 覆盖率关注点

- 优先覆盖核心业务逻辑
- 确保所有异常路径都有测试
- 边界条件必须覆盖
- 不要为了覆盖率而写无意义的测试
- 定期审查未覆盖的代码，评估是否需要补充测试

---

## 8. 测试分类与执行

### 8.1 测试分层

| 层级 | 位置 | 运行频率 | 执行时间 |
|------|------|---------|---------|
| 单元测试 | 各模块 `tests/unit/`、`shared/tests/` | 每次提交 | 快（< 1 分钟） |
| 组件测试 | 各模块 `tests/` | 每次提交 | 中等（< 5 分钟） |
| 集成测试 | `tests/integration/` | 每日构建 | 中等（< 10 分钟） |
| E2E 测试 | `tests/e2e/` | 每日/每周构建 | 慢（< 30 分钟） |
| 性能测试 | `tests/performance/` | 每周/版本发布 | 慢（< 1 小时） |

### 8.2 CI/CD 中的测试

```
代码提交
    ↓
单元测试 + 边界测试    ← 必须通过
    ↓
组件测试              ← 必须通过
    ↓
代码覆盖率检查        ← 低于阈值则失败
    ↓
合并到主干
    ↓
集成测试              ← 每日夜间构建
    ↓
E2E 测试              ← 每日夜间构建
    ↓
性能测试              ← 每周/版本发布前
```

---

## 9. 当前测试目录现状

### 9.1 现有测试文件统计（部分）

| 位置 | 测试文件数量 | 说明 |
|------|------------|------|
| `M1-agent-hub/tests/` | 30+ | 最大的测试目录 |
| `M2-skills-cluster/skill_cluster/tests/` | 30+ | 技能集群测试 |
| `API-Gateway/tests/` | 11 | 网关测试 |
| `M12-security-shield/tests/` | 10 | 安全盾测试 |
| `M4-scene-engine/tests/` | 12 | 场景引擎测试 |
| `M3-edge-cloud/edge_cloud_kernel/tests/` | 20+ | 端云协同测试 |
| `shared/tests/` | 8 | shared 核心库测试 |
| `tests/`（根级） | 30+ | 根级测试（集成、E2E、性能等） |

### 9.2 历史遗留问题

1. **根级 tests/ 目录混杂**：包含了 `test_m{1..12}/` 子目录（各模块的集成测试），也包含 `test_shared/`（共享库测试）
2. **模块测试位置不统一**：
   - 有的在 `{module}/tests/`
   - 有的在 `{module}/{package}/tests/`
   - 有的在 `{module}/backend/tests/`
3. **缺少统一的 marker 标记**：大部分测试没有标记 unit/integration/e2e

### 9.3 改进建议

1. **短期（本次）**：制定统一规范并文档化（即本文档）
2. **中期**：逐步为现有测试添加 marker 标记
3. **长期**：逐步将根级 `test_m{1..12}/` 中的测试迁移回各模块的 `tests/` 目录

---

## 10. 迁移计划

### 10.1 第一阶段：规范制定（已完成）

- [x] 制定测试目录结构规范
- [x] 制定测试命名规范
- [x] 定义 pytest markers
- [x] 编写测试编写指南
- [x] 定义覆盖率目标
- [x] 本文档创建

### 10.2 第二阶段：标记现有测试

- [ ] 为 `shared/tests/` 中的测试添加 marker
- [ ] 为 `API-Gateway/tests/` 中的测试添加 marker
- [ ] 为各模块测试逐步添加 marker
- [ ] 在 pytest.ini 中注册所有 markers

### 10.3 第三阶段：结构优化（可选）

- [ ] 将 `tests/test_shared/` 迁移到 `shared/tests/`
- [ ] 将 `tests/test_m{1..12}/` 中的集成测试逐步迁移到各模块
- [ ] 根级 `tests/` 只保留跨模块的集成、E2E、性能测试

> **注意**：测试文件迁移是较大的改动，需在评估影响后逐步进行，避免破坏现有 CI/CD 流程。

---

## 相关文档

- [文档目录](README.md) - 所有文档索引
- [开发者指南](DEVELOPMENT.md) - 开发规范与指南
- [代码质量文档](CODE_QUALITY.md) - 代码质量标准
- [安全文档](SECURITY.md) - 安全测试相关
- [配置参考手册](CONFIG_REFERENCE.md) - 配置项参考
