# 云汐系统开发者指南

> **版本**：v1.0（第四阶段 · 生产就绪）
> **更新时间**：2026-07-17
> **文档类型**：开发者指南 · 适用范围：所有开发者

---

## 目录

- [1. 开发环境搭建](#1-开发环境搭建)
- [2. 项目结构](#2-项目结构)
- [3. 代码规范](#3-代码规范)
- [4. 测试规范](#4-测试规范)
- [5. 提交规范](#5-提交规范)
- [6. 分支策略](#6-分支策略)
- [7. 调试技巧](#7-调试技巧)
- [8. 常见开发问题](#8-常见开发问题)
- [9. 开发工作流](#9-开发工作流)
- [10. 参考资源](#10-参考资源)

---

## 1. 开发环境搭建

### 1.1 环境要求

| 组件 | 版本要求 | 说明 |
|------|---------|------|
| Python | 3.10+ | 推荐 3.11 或 3.12 |
| Git | 2.30+ | 版本管理 |
| 操作系统 | Windows 10+ / macOS 11+ / Linux | 跨平台支持 |
| 代码编辑器 | VS Code / PyCharm | 推荐 VS Code |

### 1.2 获取代码

```bash
# 克隆仓库
git clone https://github.com/RiMuLiGZF/yunxi-project.git
cd yunxi-project

# 确认在主分支
git branch
```

### 1.3 Python 环境配置

建议使用虚拟环境隔离依赖：

```powershell
# Windows PowerShell
python -m venv .venv
.\.venv\Scripts\Activate.ps1

# 验证
python --version  # 应为 3.10+
```

### 1.4 安装依赖

每个模块有独立的 `requirements.txt`，根据开发的模块安装对应依赖：

```powershell
# 安装核心模块依赖（M8 控制塔）
cd M8-control-tower\backend
pip install -r requirements.txt
cd ..\..

# 安装 shared 核心依赖（所有模块通用）
# shared 模块通常被各模块直接引用，无需单独安装
```

### 1.5 配置开发环境

```powershell
# 复制配置模板
Copy-Item config\yunxi.env.example config\yunxi.env

# 编辑配置文件
# 至少需要配置：
# - JWT_SECRET（开发环境可用默认值）
# - 各模块端口（默认即可）
# - LLM API Key（如需使用云端模型）
```

### 1.6 前端环境（可选）

如果需要开发前端页面：

```powershell
# 安装 Node.js（推荐 20.x LTS）
# 然后安装前端依赖
cd frontend\spa
npm install
```

### 1.7 验证环境

```powershell
# 启动 M8 控制塔测试
cd M8-control-tower\backend
python server.py

# 另开一个终端，健康检查
curl http://localhost:8008/m8/health
```

### 1.8 推荐 VS Code 插件

| 插件 | 用途 |
|------|------|
| Python | Python 语言支持、调试 |
| Pylance | 智能提示、类型检查 |
| Black Formatter | 代码格式化 |
| isort | 导入排序 |
| Error Lens | 行内错误提示 |
| GitLens | Git 增强 |
| Thunder Client | API 测试（替代 Postman） |
| Vue Language Features | Vue 3 支持 |
| DotENV | .env 文件支持 |

---

## 2. 项目结构

### 2.1 整体目录结构

```
yunxi-project/
├── M0-principal-console/   # M0 主理人管控台
├── M1-agent-hub/           # M1 多Agent集群调度
├── M2-skills-cluster/      # M2 技能集群
├── M3-edge-cloud/          # M3 端云协同内核
├── M4-scene-engine/        # M4 业务场景引擎
├── M5-tide-memory/         # M5 潮汐分层记忆（私有）
├── M6-hardware-peripheral/ # M6 穿戴硬件外设
├── M7-workflow-builder/    # M7 积木编排平台
├── M8-control-tower/       # M8 管理控制塔
├── M9-dev-workshop/        # M9 开发者工坊
├── M10-system-guard/       # M10 系统卫士
├── M11-mcp-bus/            # M11 MCP总线
├── M12-security-shield/    # M12 安全盾
├── API-Gateway/            # API 网关
├── frontend/               # 前端集合
│   └── spa/                # Vue 3 SPA 应用
├── shared/                 # 公共组件库（三层架构）
│   ├── core/               # 基础工具层
│   ├── data/               # 数据基础设施层
│   └── business/           # 业务能力层
├── scripts/                # 运维与工具脚本
├── tests/                  # 统一测试目录
├── docs/                   # 项目文档
├── config/                 # 配置文件
├── data/                   # 运行时数据
├── logs/                   # 日志文件
├── backups/                # 备份文件
├── artifacts/              # 产物归档
├── archive/                # 归档代码
├── docker-compose.yml      # Docker 编排（开发）
├── start-all.ps1           # 一键启动
├── stop-all.ps1            # 一键停止
└── README.md               # 项目说明
```

### 2.2 模块标准结构

每个后端模块遵循相似的目录结构：

```
模块目录/
├── server.py              # 启动入口
├── requirements.txt       # 依赖列表
├── README.md              # 模块说明
├── src/
│   ├── main.py           # FastAPI 应用创建 + 路由注册
│   ├── config.py         # 模块配置
│   ├── models.py         # 数据模型（Pydantic / SQLAlchemy）
│   ├── database.py       # 数据库连接
│   ├── errors.py         # 模块特有错误码
│   ├── routers/          # 路由层
│   │   ├── __init__.py
│   │   ├── xxx.py
│   │   └── ...
│   ├── services/         # 业务逻辑层
│   │   ├── __init__.py
│   │   ├── xxx_service.py
│   │   └── ...
│   ├── middleware/       # 中间件（可选）
│   └── m8_api/           # M8 标准接口
│       ├── health_endpoints.py
│       └── m8_auth_middleware.py
├── tests/                # 模块内测试
└── data/                 # 模块数据目录
```

### 2.3 Shared 三层架构

```
shared/
├── core/                    # 基础工具层（无业务依赖）
│   ├── config.py            # 全局配置
│   ├── logger.py            # 统一日志
│   ├── errors.py            # 统一错误码
│   ├── responses.py         # 统一响应格式
│   ├── auth.py              # 鉴权工具
│   ├── security.py          # 安全工具
│   ├── utils.py             # 通用工具
│   ├── version.py           # 版本信息
│   ├── waf_middleware.py    # WAF 中间件
│   ├── middleware/          # 中间件
│   │   ├── tracing.py
│   │   └── security_headers.py
│   └── observability/       # 可观测性
│       ├── unified_logger.py
│       ├── tracing.py
│       └── metrics.py
├── data/                    # 数据基础设施层
│   ├── cache/               # 缓存
│   ├── data_layer/          # 数据库管理
│   └── data_governance/     # 数据治理
└── business/                # 业务能力层（过渡期）
    ├── agent_engine.py
    ├── llm_client.py
    ├── module_client.py
    ├── process_manager.py
    └── distributed/
```

> **注意**：新代码优先使用 `shared.core.*` 路径，旧路径仍可用但会有 DeprecationWarning。

---

## 3. 代码规范

### 3.1 Python 代码规范

遵循 **PEP 8** 规范，并结合项目实际做以下约定：

#### 3.1.1 命名规范

| 类型 | 规范 | 示例 |
|------|------|------|
| 模块/文件名 | 小写 + 下划线 | `user_service.py` |
| 类名 | 大驼峰（PascalCase） | `UserService` |
| 函数/方法 | 小写 + 下划线 | `get_user_by_id` |
| 变量 | 小写 + 下划线 | `user_name` |
| 常量 | 全大写 + 下划线 | `MAX_RETRY_COUNT` |
| 私有成员 | 下划线前缀 | `_internal_method` |

#### 3.1.2 代码格式化

使用 **Black** 作为代码格式化工具：

```powershell
# 安装
pip install black

# 格式化指定文件
black path/to/file.py

# 格式化整个目录
black M8-control-tower/backend/
```

使用 **isort** 管理导入排序：

```powershell
# 安装
pip install isort

# 排序导入
isort path/to/file.py
```

#### 3.1.3 类型注解

所有公共函数和方法必须添加类型注解：

```python
# 正确示例
from typing import Optional, List, Dict

def get_user(user_id: int) -> Optional[Dict[str, str]]:
    """根据 ID 获取用户"""
    ...

def list_users(page: int = 1, page_size: int = 20) -> List[Dict]:
    """获取用户列表"""
    ...
```

#### 3.1.4 文档字符串

使用 Google 风格的 docstring：

```python
def calculate_total(items: List[dict], tax_rate: float) -> float:
    """计算订单总金额。

    根据商品列表和税率计算包含税费的总金额。

    Args:
        items: 商品列表，每项包含 name, price, quantity
        tax_rate: 税率，如 0.13 表示 13%

    Returns:
        包含税费的总金额

    Raises:
        ValueError: 商品列表为空或税率无效时

    Examples:
        >>> items = [{"price": 100, "quantity": 2}]
        >>> calculate_total(items, 0.13)
        226.0
    """
    ...
```

### 3.2 API 设计规范

详见 [API 文档](API.md)，核心要点：

- RESTful 风格，使用正确的 HTTP 方法
- 统一响应格式（code / message / data / trace_id）
- 统一错误码体系（6 位错误码）
- API 版本化（`/api/v1/`）
- 使用 Pydantic 模型定义请求和响应

### 3.3 错误处理规范

#### 3.3.1 使用统一异常体系

```python
from shared.core.errors import (
    ValidationError,
    NotFoundError,
    BusinessError,
    raise_not_found,
)
from shared.core.responses import ok, fail
from shared.core.errors import ErrorCode

# 推荐：抛出异常，由全局异常处理器统一处理
def get_user(user_id: int):
    user = db.query(user_id)
    if not user:
        raise_not_found("用户", user_id)
    return user

# 业务错误
def start_module(module_key: str):
    if is_running(module_key):
        raise BusinessError(
            message="模块已在运行",
            code=M8ErrorCode.MODULE_ALREADY_RUNNING,
        )
```

#### 3.3.2 注册全局异常处理器

```python
from fastapi import FastAPI
from shared.core.responses import register_global_exception_handler

app = FastAPI()
register_global_exception_handler(app)
```

### 3.4 日志规范

#### 3.4.1 使用统一日志

```python
from shared.core.logger import get_logger

logger = get_logger("m8.user_service")

# 不同级别日志
logger.debug("调试信息，开发用")
logger.info("普通信息，正常流程")
logger.warning("警告，需要关注但不影响功能")
logger.error("错误，功能异常")
logger.critical("严重错误，系统不可用")
```

#### 3.4.2 日志内容要求

- 不记录敏感信息（密码、Token、密钥等）
- 结构化日志，便于检索
- 关键操作必须记录（登录、修改、删除等）
- 错误日志需包含足够的上下文信息

```python
# 正确：记录上下文
logger.error(
    "模块启动失败",
    extra={
        "module_key": module_key,
        "error": str(e),
        "retry_count": retry_count,
    }
)

# 错误：记录敏感信息
logger.info(f"用户登录，密码: {password}")  # ❌ 绝对禁止
```

### 3.5 配置规范

- 所有配置通过环境变量或配置文件注入
- 禁止在代码中硬编码密码、密钥等敏感信息
- 使用 `shared.core.config` 获取全局配置

```python
from shared.core.config import get_config

config = get_config()
port = config.get_module_port("m8")
```

### 3.6 导入规范

导入顺序按以下分组，组之间空一行：

1. 标准库导入
2. 第三方库导入
3. 本地库导入（shared.*）
4. 项目内其他模块导入
5. 相对导入

```python
# 标准库
import os
import sys
from typing import Optional

# 第三方库
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

# shared 公共库
from shared.core.errors import ValidationError
from shared.core.responses import ok

# 本模块导入
from .services import user_service
from .models import User
```

---

## 4. 测试规范

### 4.1 测试框架

- **测试框架**：pytest
- **覆盖率**：pytest-cov
- **HTTP 测试**：httpx（FastAPI TestClient）
- **Mock 工具**：unittest.mock

### 4.2 测试分类

| 类型 | 标记 | 说明 | 运行命令 |
|------|------|------|---------|
| 单元测试 | `@pytest.mark.unit` | 测试单个函数/类，mock 外部依赖 | `pytest -m unit` |
| 集成测试 | `@pytest.mark.integration` | 测试模块间交互 | `pytest -m integration` |
| 端到端测试 | `@pytest.mark.e2e` | 完整业务流程 | `pytest -m e2e` |
| 慢速测试 | `@pytest.mark.slow` | 涉及 IO、网络等 | `pytest -m slow` |

### 4.3 测试目录结构

```
tests/
├── conftest.py              # 全局 fixtures
├── pytest.ini               # pytest 配置
├── test_shared/             # shared 模块测试
├── test_m8/                 # M8 模块测试
├── test_m9/                 # M9 模块测试
├── test_m11/                # M11 模块测试
└── integration/             # 集成测试
```

### 4.4 测试编写规范

#### 4.4.1 文件命名

- 测试文件：`test_*.py`
- 测试类：`Test*`
- 测试方法：`test_*`

#### 4.4.2 测试结构（AAA 模式）

```python
import pytest

class TestUserService:
    """用户服务测试"""

    @pytest.mark.unit
    def test_create_user_success(self, db_session):
        """创建用户成功"""
        # Arrange - 准备测试数据
        user_data = {"username": "testuser", "password": "Test123456"}

        # Act - 执行操作
        result = user_service.create(db_session, user_data)

        # Assert - 验证结果
        assert result["username"] == "testuser"
        assert "id" in result
```

#### 4.4.3 命名约定

测试方法名：`test_<被测试对象>_<预期行为>`

```python
# 正确
def test_login_success_with_valid_credentials()
def test_create_user_fails_when_username_exists()

# 错误
def test_login_1()
def test_user()
```

### 4.5 覆盖率目标

| 模块 | 目标覆盖率 |
|------|-----------|
| shared/core | >= 70% |
| M8 控制塔 | >= 60% |
| M9 开发工坊 | >= 60% |
| M11 MCP 总线 | >= 60% |
| 核心模块加权平均 | >= 60% |

### 4.6 运行测试

```powershell
# 运行所有测试
pytest

# 运行指定模块测试
pytest tests/test_m8/

# 运行单元测试（排除集成测试）
pytest -m "not integration"

# 生成覆盖率报告
pytest --cov=. --cov-report=term-missing --cov-report=html

# 只运行核心模块覆盖率
pytest --cov=shared/core --cov=M8-control-tower/backend --cov-report=html
```

### 4.7 Mock 原则

- 单元测试中 mock 所有外部依赖
- 集成测试使用真实的轻量级依赖（内存 SQLite、临时目录等）
- 避免过度 mock，测试要有实际意义

```python
from unittest.mock import patch, MagicMock

def test_user_service_with_mock():
    """使用 mock 测试服务层"""
    with patch("module.user_service.db") as mock_db:
        mock_db.query.return_value = {"id": 1, "username": "test"}
        result = user_service.get(1)
        assert result["id"] == 1
```

---

## 5. 提交规范

### 5.1 Conventional Commits

项目采用 **Conventional Commits** 规范，提交信息格式：

```
<type>(<scope>): <subject>

<body>

<footer>
```

### 5.2 Type 类型

| 类型 | 说明 |
|------|------|
| `feat` | 新功能 |
| `fix` | 修复 bug |
| `docs` | 文档变更 |
| `style` | 代码格式（不影响功能） |
| `refactor` | 重构（不是新增功能也不是修 bug） |
| `perf` | 性能优化 |
| `test` | 增加或修改测试 |
| `chore` | 构建过程或辅助工具的变动 |
| `ci` | CI 配置变更 |
| `revert` | 回滚之前的提交 |

### 5.3 Scope（可选）

影响的模块或范围，如：`m8`、`m1`、`shared`、`docs`、`gateway`

### 5.4 Subject

- 简短描述（不超过 50 字符）
- 使用动词开头（添加、修复、重构等）
- 句末不加句号

### 5.5 示例

```
feat(m8): 添加用户角色权限管理

- 实现 RBAC 角色权限体系
- 新增角色管理接口
- 支持角色与权限的多对多关系

Closes #123
```

```
fix(m11): 修复 MCP 工具调用超时问题

增加超时配置，默认超时从 30s 调整为 60s，
并添加超时重试机制。

Fixes #456
```

```
docs: 更新 API 文档，补充错误码说明
```

### 5.6 Git Hooks

项目提供了 Git Hooks 脚本，用于自动检查提交信息格式：

```powershell
# 安装 Git Hooks
.\scripts\git\install_hooks.ps1
```

安装后，每次提交会自动检查：
- 提交信息格式是否符合 Conventional Commits
- 代码格式化检查
- 基本语法检查

---

## 6. 分支策略

### 6.1 分支模型

采用简化的 Git Flow 模型：

```
main ──────────────────────────────────── 生产分支
  \
   develop ───────────────────────────── 开发主分支
     \
      feature/m8-auth ────────────────── 功能分支
      feature/m1-federation ──────────── 功能分支
      hotfix/login-bug ───────────────── 热修复分支
```

### 6.2 分支说明

| 分支 | 命名 | 说明 |
|------|------|------|
| 主分支 | `main` | 生产就绪代码，仅接受从 develop 或 hotfix 的合并 |
| 开发分支 | `develop` | 最新开发代码，所有功能合并到这里 |
| 功能分支 | `feature/<功能描述>` | 新功能开发，从 develop 切出 |
| 修复分支 | `fix/<问题描述>` | Bug 修复，从 develop 切出 |
| 热修复分支 | `hotfix/<问题描述>` | 紧急修复，从 main 切出 |
| 发布分支 | `release/<版本号>` | 发布准备，从 develop 切出 |

### 6.3 开发工作流

```
# 1. 从 develop 切出功能分支
git checkout develop
git checkout -b feature/m8-auth-enhance

# 2. 开发并提交
git add .
git commit -m "feat(m8): 增强认证功能"

# 3. 推送到远程
git push origin feature/m8-auth-enhance

# 4. 创建 Pull Request 合并到 develop
# 代码评审通过后合并

# 5. 合并后删除功能分支
git branch -d feature/m8-auth-enhance
```

### 6.4 版本发布

```
# 1. 从 develop 切出发布分支
git checkout develop
git checkout -b release/v1.0.0

# 2. 版本号更新、文档更新、最终测试

# 3. 合并到 main 并打 tag
git checkout main
git merge release/v1.0.0
git tag -a v1.0.0 -m "v1.0.0 正式版"

# 4. 同步回 develop
git checkout develop
git merge release/v1.0.0
```

### 6.5 热修复

```
# 1. 从 main 切出热修复分支
git checkout main
git checkout -b hotfix/login-bug

# 2. 修复 bug 并提交
git commit -m "fix: 修复登录超时问题"

# 3. 合并回 main
git checkout main
git merge hotfix/login-bug
git tag -a v0.9.2 -m "v0.9.2 热修复"

# 4. 同步回 develop
git checkout develop
git merge hotfix/login-bug
```

---

## 7. 调试技巧

### 7.1 Python 调试

#### 7.1.1 VS Code 调试

在 `.vscode/launch.json` 中添加调试配置：

```json
{
  "version": "0.2.0",
  "configurations": [
    {
      "name": "Python: M8 控制塔",
      "type": "debugpy",
      "request": "launch",
      "program": "${workspaceFolder}/M8-control-tower/backend/server.py",
      "cwd": "${workspaceFolder}/M8-control-tower/backend",
      "env": {
        "PYTHONPATH": "${workspaceFolder}"
      }
    }
  ]
}
```

#### 7.1.2 print 调试

快速调试时使用 print，但注意不要提交到代码库：

```python
# 临时调试（用完删除）
import pprint
pprint.pprint(variable)
```

#### 7.1.3 断点调试

使用 `breakpoint()` 设置断点：

```python
def some_function():
    x = calculate()
    breakpoint()  # 程序会在这里暂停
    return x
```

### 7.2 API 调试

#### 7.2.1 使用 Swagger UI

每个 FastAPI 模块都自带 Swagger UI：

| 模块 | Swagger 地址 |
|------|-------------|
| M8 控制塔 | http://localhost:8008/docs |
| M11 MCP 总线 | http://localhost:8011/docs |
| API 网关 | http://localhost:8080/docs |

直接在浏览器中打开，即可在线测试 API。

#### 7.2.2 使用 curl

```powershell
# GET 请求
curl http://localhost:8008/m8/health

# POST 请求
curl -X POST http://localhost:8008/api/v1/auth/login `
  -H "Content-Type: application/json" `
  -d '{\"username\": \"admin\", \"password\": \"test123\"}'

# 带认证
curl http://localhost:8008/api/v1/modules `
  -H "Authorization: Bearer <token>"
```

### 7.3 日志调试

#### 7.3.1 查看日志

```powershell
# 实时跟踪指定模块日志
.\scripts\logs.ps1 -Module M8 -Follow

# 查看错误日志
.\scripts\logs.ps1 -Level error -Since "1h"

# 搜索关键词
.\scripts\logs.ps1 -Module all -Keyword "timeout"
```

#### 7.3.2 开启调试日志

在配置中调整日志级别：

```
# yunxi.env
LOG_LEVEL=DEBUG
```

### 7.4 数据库调试

#### 7.4.1 直接查询 SQLite

```powershell
# 安装 sqlite3 命令行工具（Linux/macOS 通常自带）
# 进入数据库
sqlite3 data/m8.db

# 查看所有表
.tables

# 查询数据
SELECT * FROM users LIMIT 10;

# 退出
.quit
```

也可以使用 VS Code 插件 "SQLite" 直接在编辑器中查看。

### 7.5 常见调试场景

#### 7.5.1 模块启动失败

```powershell
# 1. 查看详细错误
cd M8-control-tower\backend
python server.py

# 2. 检查端口占用
netstat -ano | findstr 8008

# 3. 检查配置
# 确认 config/yunxi.env 中相关配置正确
```

#### 7.5.2 API 返回 500 错误

1. 查看服务端日志，找到堆栈信息
2. 定位到出错的代码行
3. 在 VS Code 中设置断点调试
4. 确认是参数问题、逻辑错误还是依赖问题

#### 7.5.3 模块间调用失败

```python
# 开启模块调用调试日志
import logging
logging.getLogger("shared.module_client").setLevel(logging.DEBUG)

# 或者直接测试调用
from shared.core.module_client import get_module_client

client = get_module_client("m1")
result = client.get("/m8/health")
print(result)
```

---

## 8. 常见开发问题

### Q: 导入 shared 模块报错 "ModuleNotFoundError"

**A**：需要确保项目根目录在 Python 路径中。

```python
# 在模块入口文件顶部添加
import sys
from pathlib import Path

project_root = Path(__file__).parent.parent.parent  # 根据实际层级调整
sys.path.insert(0, str(project_root))
```

或者设置环境变量：

```powershell
$env:PYTHONPATH = "C:\path\to\yunxi-project"
```

### Q: 端口被占用怎么办？

**A**：查找并结束占用进程，或修改模块端口。

```powershell
# 查找占用 8008 端口的进程
netstat -ano | findstr :8008

# 结束进程（替换 PID）
taskkill /F /PID <PID>
```

### Q: 如何添加新的 API 接口？

**A**：遵循以下步骤：

1. 在 `routers/` 目录下创建或修改路由文件
2. 定义 Pydantic 请求/响应模型
3. 实现业务逻辑（在 services/ 中）
4. 在 `main.py` 中注册路由
5. 添加测试
6. 更新 API 文档

### Q: 如何添加新的错误码？

**A**：

1. 确认错误所属模块和类别
2. 在模块的 `errors.py` 中定义错误码
3. 使用统一的异常类抛出
4. 更新 `shared/core/ERROR_CODES.md` 文档

### Q: 测试时如何 mock 数据库？

**A**：使用内存 SQLite 作为测试数据库。

```python
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

@pytest.fixture
def db_session():
    engine = create_engine("sqlite:///:memory:")
    Session = sessionmaker(bind=engine)
    session = Session()
    # 创建表结构
    # Base.metadata.create_all(engine)
    yield session
    session.close()
```

### Q: 如何调试异步代码？

**A**：使用 `asyncio.run()` 或 pytest-asyncio。

```python
import pytest

@pytest.mark.asyncio
async def test_async_function():
    result = await async_function()
    assert result == expected
```

### Q: M8 标准接口怎么实现？

**A**：每个模块需要实现以下 M8 标准接口：

- `GET /m8/health` — 健康检查
- `GET /m8/metrics` — 运行指标
- `GET /m8/config` — 当前配置（脱敏）
- `POST /m8/config/reload` — 配置热重载（可选）

参考 M9 开发工坊的实现作为模板。

### Q: 如何进行性能分析？

**A**：使用 cProfile 或 py-spy。

```powershell
# 安装 py-spy
pip install py-spy

# 采样运行中的进程
py-spy top --pid <PID>

# 生成火焰图
py-spy record -o profile.svg --pid <PID>
```

### Q: 前端开发如何启动？

**A**：

```powershell
cd frontend\spa
npm install
npm run dev
```

前端开发服务器默认运行在 5173 端口，API 请求通过 Vite 代理转发到后端。

---

## 9. 开发工作流

### 9.1 新功能开发流程

```
1. 需求分析
   ↓
2. 技术方案设计
   ↓
3. 从 develop 切出 feature 分支
   ↓
4. 编写测试用例（TDD 推荐）
   ↓
5. 实现功能代码
   ↓
6. 本地测试通过
   ↓
7. 代码格式化和 lint
   ↓
8. 提交代码（Conventional Commits）
   ↓
9. 创建 Pull Request
   ↓
10. 代码评审
    ↓
11. 合并到 develop
    ↓
12. 删除功能分支
```

### 9.2 Bug 修复流程

```
1. 确认 Bug 和复现步骤
   ↓
2. 从 develop 切出 fix 分支
   ↓
3. 编写失败的测试用例
   ↓
4. 修复 Bug
   ↓
5. 验证测试通过
   ↓
6. 提交代码
   ↓
7. Pull Request + 评审
   ↓
8. 合并到 develop
```

### 9.3 代码评审清单

PR 合并前检查：

- [ ] 功能符合需求
- [ ] 代码风格一致（Black 格式化）
- [ ] 有适当的单元测试
- [ ] 没有硬编码的敏感信息
- [ ] 错误处理完善
- [ ] 日志记录合理
- [ ] 文档已更新
- [ ] 没有性能问题
- [ ] 安全性考虑到位

---

## 10. 参考资源

### 10.1 内部文档

| 文档 | 路径 | 说明 |
|------|------|------|
| 架构文档 | [ARCHITECTURE.md](ARCHITECTURE.md) | 系统架构与模块说明 |
| API 文档 | [API.md](API.md) | API 接口参考 |
| 运维手册 | [OPS.md](OPS.md) | 运维操作指南 |
| 错误码规范 | `../shared/core/ERROR_CODES.md` | 完整错误码列表 |
| 安全文档 | [SECURITY.md](SECURITY.md) | 安全架构与防护 |
| 共享库文档 | `../shared/README.md` | Shared 组件说明 |
| 测试指南 | `../tests/README.md` | 测试体系说明 |

### 10.2 外部资源

- [FastAPI 官方文档](https://fastapi.tiangolo.com/)
- [Pydantic 文档](https://docs.pydantic.dev/)
- [pytest 文档](https://docs.pytest.org/)
- [Conventional Commits](https://www.conventionalcommits.org/)
- [PEP 8 风格指南](https://peps.python.org/pep-0008/)
- [MCP 协议规范](https://modelcontextprotocol.io/)

---

**文档维护**：开发流程变更时更新本文档
**最后更新**：2026-07-17
**版本**：v1.0
