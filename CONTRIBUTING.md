# 贡献指南 (Contributing Guide)

> 感谢你有兴趣为云汐项目做贡献！本文档描述了参与云汐项目开发的规范和流程。
> 请在提交贡献前仔细阅读本文档，以确保你的贡献能够被高效地评审和合并。

---

## 目录

1. [如何参与贡献](#1-如何参与贡献)
2. [开发环境搭建](#2-开发环境搭建)
3. [代码规范](#3-代码规范)
4. [提交规范](#4-提交规范)
5. [分支策略](#5-分支策略)
6. [Pull Request 流程](#6-pull-request-流程)
7. [模块开发规范](#7-模块开发规范)
8. [Issue 规范](#8-issue-规范)

---

## 1. 如何参与贡献

### 1.1 报告 Bug

如果你发现了 Bug，请通过 Issue 报告。报告前请先搜索已有 Issue，避免重复提交。

一份好的 Bug 报告应包含：

- **清晰的标题**：一句话描述问题
- **复现步骤**：按步骤说明如何复现问题
- **预期行为**：你期望的正确结果
- **实际行为**：实际发生的错误现象
- **环境信息**：操作系统、Python 版本、云汐版本
- **错误日志**：相关的错误堆栈或日志信息
- **复现概率**：必现 / 偶发（约多少概率）

> 请使用 Bug 报告模板创建 Issue，详见 [第 8 节](#8-issue-规范)。

### 1.2 提交功能建议

如果你有新功能或改进的想法，欢迎通过 Issue 提交功能建议。

功能建议应包含：

- **功能描述**：你想要什么功能
- **使用场景**：这个功能解决了什么问题
- **期望行为**：具体的功能表现和交互方式
- **实现思路**：如果你有想法，可以描述大致的实现方案
- **替代方案**：你考虑过的其他实现方式

### 1.3 提交代码

我们欢迎通过 Pull Request 提交代码贡献。请遵循以下流程：

1. Fork 本仓库到你的账号
2. 创建功能分支（详见 [第 5 节 分支策略](#5-分支策略)）
3. 开发并提交代码（遵循 [第 3 节 代码规范](#3-代码规范) 和 [第 4 节 提交规范](#4-提交规范)）
4. 确保所有测试通过（详见 [第 2.4 节 运行测试](#24-运行测试)）
5. 提交 Pull Request（详见 [第 6 节 PR 流程](#6-pull-request-流程)）
6. 等待 Code Review，根据评审意见修改
7. 合并到主分支

---

## 2. 开发环境搭建

### 2.1 环境要求

| 组件 | 版本要求 | 说明 |
|------|---------|------|
| **Python** | 3.10+ | 推荐 3.11 或 3.12 |
| **Git** | 2.30+ | 版本管理 |
| **操作系统** | Windows 10+ / macOS 11+ / Linux | 跨平台支持 |
| **代码编辑器** | VS Code / PyCharm | 推荐 VS Code |
| **Node.js**（前端开发） | 18+ LTS | 前端构建工具 |
| **Ollama**（可选） | 最新版 | 本地 LLM 推理 |
| **Docker**（可选） | 24.0+ | 容器化部署 |

### 2.2 安装步骤

```powershell
# 1. Fork 并克隆仓库
git clone https://github.com/<your-username>/yunxi-project.git
cd yunxi-project

# 2. 添加上游仓库
git remote add upstream https://github.com/RiMuLiGZF/yunxi-project.git

# 3. 创建虚拟环境
python -m venv .venv
.\.venv\Scripts\Activate.ps1

# 4. 安装开发依赖
pip install -r requirements-dev.txt

# 5. 安装 pre-commit hooks
pre-commit install

# 6. 复制配置模板
Copy-Item config\yunxi.env.example config\yunxi.env

# 7. 编辑配置文件
# 至少配置 JWT_SECRET 和必要的 API Key
```

### 2.3 安装模块依赖

每个模块有独立的 `requirements.txt`，根据你开发的模块安装对应依赖：

```powershell
# 以 M8 控制塔为例
cd M8-control-tower\backend
pip install -r requirements.txt
cd ..\..

# 安装 shared 核心依赖
cd shared
pip install -r requirements.txt
cd ..
```

### 2.4 运行测试

```powershell
# 运行全部测试
pytest

# 运行指定模块测试
pytest tests/test_m8/
pytest tests/test_shared/

# 运行单元测试（排除集成测试）
pytest -m "not integration"

# 运行冒烟测试（快速验证核心功能）
pytest -m smoke

# 生成覆盖率报告
pytest --cov=. --cov-report=term-missing --cov-report=html

# 只运行核心模块覆盖率
pytest --cov=shared/core --cov=M8-control-tower/backend --cov-report=html
```

> 提交 PR 前请确保所有相关测试通过，且新增代码有对应的测试覆盖。

### 2.5 验证开发环境

```powershell
# 启动 M8 控制塔
cd M8-control-tower\backend
python server.py

# 另开终端，验证健康检查
curl http://localhost:8008/m8/health
```

---

## 3. 代码规范

### 3.1 Python 代码风格

项目遵循 **PEP 8** 规范，并使用 **ruff** 作为 lint 和格式化工具（配置见 `pyproject.toml`）。

#### 核心规则

- **行宽**：最大 120 字符
- **缩进**：4 空格，不使用 Tab
- **引号**：使用双引号（`"`）
- **空行**：
  - 顶级函数和类之间空两行
  - 类的方法之间空一行
  - 逻辑块之间用空行分隔提高可读性

#### 自动格式化

```powershell
# 格式化代码
ruff format .

# 运行 lint 检查并自动修复
ruff check --fix .
```

> 项目已配置 pre-commit hooks，提交时会自动运行格式化和 lint 检查。

### 3.2 命名规范

| 类型 | 规范 | 示例 |
|------|------|------|
| 模块 / 文件名 | 小写 + 下划线（snake_case） | `user_service.py` |
| 包名 | 小写 + 下划线 | `m8_control_tower` |
| 类名 | 大驼峰（PascalCase） | `UserService` |
| 异常类名 | 大驼峰，以 Error 结尾 | `ValidationError` |
| 函数 / 方法名 | 小写 + 下划线 | `get_user_by_id` |
| 变量名 | 小写 + 下划线 | `user_name` |
| 常量 | 全大写 + 下划线 | `MAX_RETRY_COUNT` |
| 私有成员 | 单下划线前缀 | `_internal_method` |
| 测试函数 | `test_<对象>_<行为>` | `test_create_user_success` |

### 3.3 类型注解要求

所有 **公共函数和方法** 必须添加类型注解：

```python
from typing import Optional, List, Dict, Any
from datetime import datetime

# 正确示例
def get_user(user_id: int) -> Optional[Dict[str, Any]]:
    """根据 ID 获取用户"""
    ...

def list_users(page: int = 1, page_size: int = 20) -> List[Dict[str, Any]]:
    """获取用户列表"""
    ...

def create_user(data: Dict[str, Any]) -> tuple[bool, str]:
    """创建用户，返回 (是否成功, 消息)"""
    ...
```

- 简单函数可以省略返回类型注解（如 `__init__` 返回 `None`）
- 优先使用 `typing` 模块中的类型，Python 3.10+ 可使用 `|` 联合类型
- 核心模块建议逐步开启 mypy 严格检查

### 3.4 文档字符串规范

使用 **Google 风格** 的 docstring：

```python
def calculate_total(items: list[dict], tax_rate: float) -> float:
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

**规则说明**：

- 公共函数、类、模块必须写 docstring
- 简短函数可以只写单行描述
- 测试文件和 `__init__.py` 不强制 docstring
- 中文项目，docstring 优先使用中文

### 3.5 Import 顺序

导入按以下分组排列，**组之间空一行**：

1. `future` 导入
2. **标准库** 导入（`os`、`sys`、`typing` 等）
3. **第三方库** 导入（`fastapi`、`sqlalchemy` 等）
4. **本地项目** 导入（`shared.*`）
5. **本模块内** 导入
6. **相对导入**（`from . import xxx`）

```python
# 标准库
import os
import sys
from typing import Optional, List

# 第三方库
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

# shared 公共库
from shared.core.errors import ValidationError, NotFoundError
from shared.core.responses import ok, fail
from shared.core.logger import get_logger

# 本模块导入
from .services import user_service
from .models import User
from .config import settings
```

> ruff isort 规则已配置，运行 `ruff check --fix .` 可自动整理导入顺序。

---

## 4. 提交规范

### 4.1 Conventional Commits 格式

项目采用 **Conventional Commits** 规范，每次提交信息格式如下：

```
<type>(<scope>): <subject>

<body>

<footer>
```

### 4.2 Type 类型说明

| 类型 | 说明 | 示例 |
|------|------|------|
| `feat` | 新功能 | 新增接口、新模块、新特性 |
| `fix` | 修复 Bug | 修复功能异常、逻辑错误 |
| `docs` | 文档变更 | 更新 README、注释、文档 |
| `style` | 代码格式 | 格式化、空行、分号等（不影响功能） |
| `refactor` | 重构 | 代码重构，不改变功能 |
| `perf` | 性能优化 | 提升性能的代码变更 |
| `test` | 测试相关 | 新增测试、修改测试 |
| `chore` | 构建/工具 | 依赖升级、构建脚本、CI 配置 |
| `ci` | CI 配置 | CI/CD 流水线变更 |
| `revert` | 回滚提交 | 回滚之前的某次提交 |

### 4.3 Scope 作用域说明

影响的模块或范围，使用小写：

| 作用域 | 说明 |
|--------|------|
| `m0` ~ `m12` | 对应 M0 ~ M12 模块 |
| `shared` | shared 公共库 |
| `gateway` | API 网关 |
| `frontend` | 前端代码 |
| `docs` | 文档 |
| `tests` | 测试 |
| `scripts` | 脚本 |
| `config` | 配置 |

> Scope 为可选，当变更涉及多个模块或全局时可以省略。

### 4.4 Subject 描述

- 简短描述，**不超过 50 字符**
- 使用动词开头（添加、修复、重构、优化等）
- 句末不加句号
- 使用现在时态（"添加" 而非 "添加了"）

### 4.5 Body 正文（可选）

- 详细描述变更的内容、原因和影响
- 每行不超过 72 字符
- 可以使用列表项

### 4.6 Footer 页脚（可选）

- 关联 Issue：`Closes #123`、`Fixes #456`
- 破坏性变更：`BREAKING CHANGE: <描述>`

### 4.7 提交示例

**功能开发**：

```
feat(m8): 添加用户角色权限管理

- 实现 RBAC 角色权限体系
- 新增角色管理接口
- 支持角色与权限的多对多关系
- 增加权限中间件

Closes #123
```

**Bug 修复**：

```
fix(m11): 修复 MCP 工具调用超时问题

增加超时配置，默认超时从 30s 调整为 60s，
并添加超时重试机制，提升调用稳定性。

Fixes #456
```

**文档更新**：

```
docs: 更新 API 文档，补充错误码说明
```

**重构**：

```
refactor(shared): 统一日志接口命名

将 get_logger 重命名为 create_logger，
并调整模块内所有调用点，保持 API 一致性。
```

---

## 5. 分支策略

### 5.1 分支模型

项目采用 **简化 Git Flow** 模型：

```
main ───────────────────────────────────── 生产分支
  \
   develop ─────────────────────────────── 开发主分支
     \
      feature/m8-auth ──────────────────── 功能分支
      feature/m1-federation ────────────── 功能分支
      fix/login-bug ────────────────────── 修复分支
      hotfix/security-patch ────────────── 热修复分支
```

### 5.2 分支说明

| 分支类型 | 命名规范 | 来源分支 | 合并目标 | 说明 |
|---------|---------|---------|---------|------|
| **主分支** | `main` | - | - | 生产就绪代码，仅接受 release 或 hotfix 合并 |
| **开发分支** | `develop` | `main` | `main` | 最新开发代码，所有功能合并到这里 |
| **功能分支** | `feature/<功能描述>` | `develop` | `develop` | 新功能开发 |
| **修复分支** | `fix/<问题描述>` | `develop` | `develop` | 非紧急 Bug 修复 |
| **热修复分支** | `hotfix/<问题描述>` | `main` | `main` + `develop` | 生产环境紧急修复 |
| **发布分支** | `release/<版本号>` | `develop` | `main` + `develop` | 版本发布准备 |

### 5.3 命名约定

- 分支名使用 **小写 + 连字符**
- 功能描述简洁明确，能体现开发内容
- 可加模块前缀，如 `feature/m8-auth-enhance`

**好的分支名**：
- `feature/m8-rbac-permission`
- `fix/m11-mcp-timeout`
- `hotfix/security-waf-bypass`

**不好的分支名**：
- `feature/test`（含义不明）
- `fix-bug`（太笼统）
- `dev-xxx`（不符合规范）

---

## 6. Pull Request 流程

### 6.1 分支创建

```powershell
# 1. 同步上游最新代码
git fetch upstream
git checkout develop
git pull upstream develop

# 2. 创建功能分支
git checkout -b feature/m8-auth-enhance

# 3. 开发并提交
git add .
git commit -m "feat(m8): 增强认证功能"

# 4. 推送到你的 fork
git push origin feature/m8-auth-enhance
```

### 6.2 提交前检查清单

提交 PR 前，请确保完成以下检查：

- [ ] 代码遵循 [代码规范](#3-代码规范)，通过 `ruff check` 和 `ruff format`
- [ ] 所有现有测试通过：`pytest`
- [ ] 新增代码有对应的单元测试
- [ ] 类型注解完整（公共函数/方法）
- [ ] 文档字符串符合 Google 风格
- [ ] 更新了相关文档（README、API 文档等）
- [ ] 提交信息符合 [Conventional Commits](#4-提交规范)
- [ ] 无硬编码的密钥、密码等敏感信息
- [ ] CHANGELOG.md 已更新（如适用）

### 6.3 PR 模板

创建 PR 时，请使用以下模板填写：

```markdown
## 变更描述

简要描述本次变更的内容和目的。

## 变更类型

- [ ] feat（新功能）
- [ ] fix（Bug 修复）
- [ ] docs（文档更新）
- [ ] style（代码格式）
- [ ] refactor（重构）
- [ ] perf（性能优化）
- [ ] test（测试）
- [ ] chore（构建/工具）

## 关联 Issue

Closes #123

## 测试情况

- [ ] 单元测试通过
- [ ] 集成测试通过
- [ ] 新增测试覆盖核心逻辑
- [ ] 手动测试验证

## 影响范围

列出受影响的模块：
- M8 控制塔
- shared/core/auth

## 风险评估

- 兼容性：是否影响现有 API？
- 性能：是否有性能影响？
- 安全：是否涉及安全相关变更？

## 截图 / 示例

（如适用，附上截图或示例代码）
```

### 6.4 Code Review 规范

#### 评审者（Reviewer）职责

- **及时响应**：收到评审请求后 24 小时内给出反馈
- **建设性意见**：指出问题的同时给出改进建议
- **关注重点**：
  - 功能正确性
  - 代码质量和可维护性
  - 安全性（敏感信息、注入风险等）
  - 性能影响
  - 测试覆盖
- **明确标记**：使用 "Request Changes" / "Approve" / "Comment" 明确态度

#### 提交者（Author）职责

- **及时回复**：对评审意见逐条回应
- **解释说明**：不同意的地方给出理由，友好讨论
- **分批修改**：修改后标记已解决的评论
- **不强行合并**：至少获得 1 个 Approve 才能合并

#### 合并要求

- 至少 **1 位** 核心开发者 Approve
- 所有 CI 检查通过
- 无未解决的评审意见
- 冲突已解决

---

## 7. 模块开发规范

### 7.1 新模块目录结构

新增模块必须遵循以下标准目录结构：

```
M<编号>-<模块名>/
├── server.py              # 启动入口（必须）
├── requirements.txt       # 模块依赖（必须）
├── README.md              # 模块说明文档（必须）
├── .env.example           # 配置模板（如有独立配置）
├── src/
│   ├── __init__.py
│   ├── main.py           # FastAPI 应用创建 + 路由注册（必须）
│   ├── config.py         # 模块配置
│   ├── models.py         # 数据模型（Pydantic / SQLAlchemy）
│   ├── database.py       # 数据库连接
│   ├── errors.py         # 模块特有错误码
│   ├── routers/          # 路由层（按功能拆分）
│   │   ├── __init__.py
│   │   ├── xxx.py
│   │   └── ...
│   ├── services/         # 业务逻辑层
│   │   ├── __init__.py
│   │   ├── xxx_service.py
│   │   └── ...
│   ├── middleware/       # 中间件（可选）
│   │   └── __init__.py
│   └── m8_api/           # M8 标准接口对接（必须）
│       ├── health_endpoints.py
│       └── m8_auth_middleware.py
├── tests/                # 模块内测试
│   ├── __init__.py
│   ├── conftest.py
│   ├── test_xxx.py
│   └── ...
└── data/                 # 模块数据目录（运行时生成）
```

### 7.2 配置规范

- 所有配置通过 **环境变量** 或 `.env` 文件注入
- **禁止** 在代码中硬编码密码、密钥、Token 等敏感信息
- 使用 `shared.core.config` 统一管理全局配置
- 模块特有配置在模块内 `config.py` 中定义，使用 `pydantic-settings`
- 提供 `.env.example` 配置模板

```python
# 模块配置示例
from pydantic_settings import BaseSettings

class ModuleSettings(BaseSettings):
    """模块配置"""
    module_port: int = 8008
    module_name: str = "m8"

    class Config:
        env_prefix = "M8_"
        env_file = ".env"
```

### 7.3 测试规范

#### 测试目录结构

```
tests/
├── conftest.py              # 全局 fixtures
├── test_shared/             # shared 模块测试
├── test_m8/                 # M8 模块测试
├── test_m9/                 # M9 模块测试
├── test_m11/                # M11 模块测试
├── integration/             # 集成测试
└── e2e/                     # 端到端测试
```

#### 测试编写要求

- 使用 **pytest** 框架
- 测试方法命名：`test_<被测试对象>_<预期行为>`
- 使用 **AAA 模式**（Arrange / Act / Assert）
- 添加合适的 **标记**（`@pytest.mark.unit`、`@pytest.mark.integration` 等）
- 单元测试覆盖率：核心模块不低于 **60%**
- 新增功能必须伴随单元测试

```python
import pytest

@pytest.mark.unit
@pytest.mark.m8
class TestUserService:
    """用户服务测试"""

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

### 7.4 文档规范

每个模块必须包含 `README.md`，内容至少包括：

- 模块功能简介
- 模块定位和架构层级
- 核心功能列表
- API 接口说明（或指向 API 文档的链接）
- 配置说明
- 启动方式
- 依赖关系

### 7.5 M8 标准对接要求

所有模块必须对接 M8 管理控制塔标准，实现以下接口：

#### 健康检查接口

| 接口 | 路径 | 说明 |
|------|------|------|
| 综合健康检查 | `GET /<module>/health` | 返回模块整体健康状态 |
| 存活探针 | `GET /<module>/health/live` | 进程是否存活 |
| 就绪探针 | `GET /<module>/health/ready` | 是否就绪可以接收请求 |

健康检查响应格式：

```json
{
  "status": "healthy",
  "version": "0.4.0",
  "module": "m8",
  "checks": {
    "database": "healthy",
    "cache": "healthy",
    "dependencies": "healthy"
  }
}
```

#### 模块信息接口

| 接口 | 路径 | 说明 |
|------|------|------|
| 模块元信息 | `GET /<module>/info` | 返回模块名称、版本、能力等 |

#### 认证对接

- 所有业务接口必须接入 JWT 认证中间件
- 支持 API Key 认证（服务间调用）
- 使用 `shared.core.auth.dependencies` 中的依赖注入

#### 统一错误码

- 模块错误码遵循 6 位规范：`XX YY ZZ`
- XX = 模块编号，YY = 错误类别，ZZ = 具体序号
- 使用 `shared.core.errors` 中的基类和工具函数

---

## 8. Issue 规范

### 8.1 Bug 报告模板

```markdown
## Bug 描述

清晰简洁地描述 Bug 是什么。

## 复现步骤

复现问题的步骤：

1. 进入 '...'
2. 点击 '....'
3. 滚动到 '....'
4. 出现错误

## 预期行为

描述你期望发生什么。

## 实际行为

描述实际发生了什么。

## 截图 / 日志

如果适用，添加截图或日志来帮助解释问题。

## 环境信息

- 操作系统：[如 Windows 11 / macOS 14 / Ubuntu 22.04]
- Python 版本：[如 3.11.4]
- 云汐版本：[如 v0.4.0]
- 部署方式：[如 裸机 / Docker]

## 复现概率

- [ ] 必现
- [ ] 偶发（约 ___% 概率）

## 附加信息

其他任何相关信息。
```

### 8.2 功能建议模板

```markdown
## 功能描述

清晰简洁地描述你想要的功能。

## 使用场景

描述这个功能解决了什么问题，在什么场景下使用。

## 期望行为

描述你期望这个功能如何工作。

## 实现思路

如果你有想法，描述大致的实现方案。

## 替代方案

描述你考虑过的其他实现方式。

## 相关参考

如果有相关的 Issue、文档、截图，请提供链接。
```

---

## 社区准则

- 尊重他人，友善讨论
- 接受建设性的批评
- 关注对社区最有利的事
- 对新贡献者保持耐心和帮助

---

> 如有任何疑问，欢迎通过 Issue 或讨论区与我们交流。
> 再次感谢你的贡献！
