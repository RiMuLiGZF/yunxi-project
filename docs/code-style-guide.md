# 云汐项目 - Python 代码风格指南

> 版本：v1.0.0  
> 适用范围：本项目所有 Python 代码及相关配置文件  
> 维护团队：Yunxi Team

---

## 目录

- [1. 为什么需要代码规范](#1-为什么需要代码规范)
- [2. Python 代码规范](#2-python-代码规范)
  - [2.1 命名规范](#21-命名规范)
  - [2.2 缩进与行长度](#22-缩进与行长度)
  - [2.3 导入顺序](#23-导入顺序)
  - [2.4 注释与文档字符串](#24-注释与文档字符串)
  - [2.5 类型提示](#25-类型提示)
- [3. 项目目录结构规范](#3-项目目录结构规范)
- [4. API 设计规范](#4-api-设计规范)
  - [4.1 RESTful 风格](#41-restful-风格)
  - [4.2 响应格式](#42-响应格式)
  - [4.3 错误处理](#43-错误处理)
- [5. Git 提交规范](#5-git-提交规范)
  - [5.1 Commit Message 格式](#51-commit-message-格式)
  - [5.2 类型说明](#52-类型说明)
  - [5.3 示例](#53-示例)
- [6. 工具使用说明](#6-工具使用说明)
  - [6.1 环境准备](#61-环境准备)
  - [6.2 ruff 使用](#62-ruff-使用)
  - [6.3 mypy 使用](#63-mypy-使用)
  - [6.4 pre-commit 使用](#64-pre-commit-使用)
  - [6.5 codespell 使用](#65-codespell-使用)

---

## 1. 为什么需要代码规范

统一的代码规范对项目的长期健康发展至关重要，主要价值体现在：

- **可读性**：团队成员可以快速理解彼此的代码，降低沟通成本
- **可维护性**：统一的风格让代码修改和重构更加安全
- **质量保障**：自动化 lint 工具可以在提交前发现潜在问题
- **协作效率**：减少代码风格层面的争论，聚焦业务逻辑本身
- **新人上手**：新成员可以依据规范快速融入项目

本规范遵循 **"实用优先、逐步严格"** 的原则，避免过度约束导致落地困难。

---

## 2. Python 代码规范

### 2.1 命名规范

总体遵循 [PEP 8](https://peps.python.org/pep-0008/) 命名约定：

| 类型 | 风格 | 示例 |
|------|------|------|
| 模块/包名 | snake_case（全小写下划线） | `user_service.py`, `data_models` |
| 类名 | PascalCase（大驼峰） | `UserService`, `DataProcessor` |
| 异常类名 | PascalCase，以 Error/Exception 结尾 | `ConfigError`, `ValidationException` |
| 函数/方法名 | snake_case | `get_user_by_id()`, `process_data()` |
| 变量名 | snake_case | `user_id`, `result_list` |
| 常量名 | UPPER_SNAKE_CASE（全大写下划线） | `MAX_RETRY_COUNT`, `DEFAULT_TIMEOUT` |
| 私有成员 | 单下划线前缀 | `_internal_method()`, `_cache_data` |
| 受保护成员 | 单下划线前缀（与私有一致） | `_protected_attr` |

**补充说明：**

- 避免使用单字符变量名（循环计数 `i`, `j`, `k` 除外）
- 布尔变量建议使用 `is_` / `has_` / `can_` 等前缀：`is_active`, `has_permission`
- 集合类型变量使用复数形式：`users`, `items`, `configs`
- 避免使用 Python 内置名称（如 `id`, `type`, `list`, `dict` 等）

### 2.2 缩进与行长度

- **缩进**：使用 4 个空格，不使用 Tab
- **行长度**：最大 120 字符（超出时自动换行）
- **空行**：
  - 顶层函数和类定义之间空两行
  - 类内方法定义之间空一行
  - 逻辑块之间可以用空行分隔，但避免连续空行
- **括号内换行**：使用垂直悬挂缩进，首行不写参数

```python
# 推荐：垂直悬挂缩进
result = some_function(
    arg1,
    arg2,
    arg3,
)

# 不推荐
result = some_function(arg1, arg2,
                       arg3)
```

### 2.3 导入顺序

导入语句按以下顺序分组，组与组之间空一行：

1. **标准库**：Python 内置模块（`os`, `sys`, `json`, `typing` 等）
2. **第三方库**：通过 pip 安装的库（`requests`, `pydantic` 等）
3. **本地项目**：项目内部的模块（`yunxi.core`, `yunxi.models` 等）
4. **相对导入**：当前包内的相对导入（`from . import xxx`）

```python
# 标准库
import json
import os
from typing import Dict, List, Optional

# 第三方库
import requests
from pydantic import BaseModel

# 本地项目
from yunxi.core.config import settings
from yunxi.models.user import User

# 相对导入
from .exceptions import ServiceError
```

**规则：**

- 不要使用通配符导入（`from module import *`）
- 每个导入独占一行
- 导入路径尽量使用绝对路径，避免深层相对导入（最多 `..` 一层）

### 2.4 注释与文档字符串

#### 注释原则

- 注释应该解释 **"为什么"** 而不是 **"做什么"**（代码本身已经说明做什么）
- 保持注释与代码同步更新，避免过时的误导性注释
- 复杂的业务逻辑、算法、正则表达式等必须添加注释
- 临时/调试代码必须标注 `TODO` 或 `FIXME`

```python
# TODO: 后续替换为 Redis 缓存，当前先用内存缓存
# FIXME: 并发场景下可能有竞态条件，需要加锁
```

#### 文档字符串（Docstring）

使用 **Google 风格** 的 docstring，公共 API 必须编写 docstring。

```python
def calculate_discount(price: float, user_level: str) -> float:
    """根据用户等级计算折扣价格。

    Args:
        price: 商品原价，必须为正数。
        user_level: 用户等级，可选值：'normal', 'silver', 'gold', 'platinum'。

    Returns:
        折扣后的价格。

    Raises:
        ValueError: price 为负数或 user_level 不合法时抛出。

    Examples:
        >>> calculate_discount(100.0, 'gold')
        85.0
    """
```

**说明：**

- 模块、类、公有方法、公有函数建议编写 docstring
- 简单的辅助函数/内部方法可以省略 docstring，但应保证命名清晰
- 不强制要求每个参数都写说明，复杂参数才需要

### 2.5 类型提示

类型提示采用 **渐进式** 策略：核心模块优先，非核心模块可选。

```python
# 推荐：函数参数和返回值都标注类型
def find_user(user_id: int, include_deleted: bool = False) -> Optional[User]:
    ...

# 变量类型由推断即可，不必显式标注
user = find_user(123)  # 自动推断为 Optional[User]

# 复杂类型建议标注
user_map: Dict[int, User] = {}
```

**类型使用建议：**

- 使用 Python 3.10+ 的新语法：`list[str]` 而非 `List[str]`，`X | None` 而非 `Optional[X]`
- 函数签名必须标注类型（核心模块），变量类型尽量让解释器推断
- 优先使用 `typing` 中的类型而非自定义类型别名
- mypy 以宽松模式运行，不通过也不阻塞提交，但建议逐步修复

---

## 3. 项目目录结构规范

推荐的项目目录结构：

```
yunxi-project/
├── pyproject.toml              # 项目配置（ruff、mypy 等）
├── .pre-commit-config.yaml     # pre-commit 钩子配置
├── requirements-dev.txt        # 开发依赖
├── requirements.txt            # 生产依赖（可选）
├── README.md                   # 项目说明
├── .gitignore
├── docs/                       # 项目文档
│   └── code-style-guide.md     # 本文档
├── yunxi/                      # 主代码包
│   ├── __init__.py
│   ├── core/                   # 核心基础设施
│   │   ├── __init__.py
│   │   ├── config.py           # 配置管理
│   │   ├── exceptions.py       # 自定义异常
│   │   └── logging.py          # 日志配置
│   ├── models/                 # 数据模型
│   │   ├── __init__.py
│   │   └── user.py
│   ├── services/               # 业务逻辑层
│   │   ├── __init__.py
│   │   └── user_service.py
│   ├── api/                    # API 层
│   │   ├── __init__.py
│   │   └── v1/
│   │       ├── __init__.py
│   │       └── user_api.py
│   └── utils/                  # 工具函数
│       ├── __init__.py
│       └── date_utils.py
├── tests/                      # 测试代码
│   ├── __init__.py
│   ├── conftest.py
│   ├── unit/
│   └── integration/
├── scripts/                    # 脚本工具
│   └── init_db.py
├── data/                       # 本地数据文件（不提交到 Git）
└── logs/                       # 日志文件（不提交到 Git）
```

**目录划分原则：**

- 按 **业务领域** 划分模块，而非按技术分层（小型项目可按技术分层）
- 每个模块职责单一，模块间依赖清晰
- 配置、日志、异常等横切关注点放在 `core` 中
- 测试代码与业务代码分目录，但目录结构尽量对应

---

## 4. API 设计规范

### 4.1 RESTful 风格

- 使用名词表示资源，避免动词出现在 URL 中
- 使用 HTTP 方法表示操作类型

| 操作 | HTTP 方法 | 示例 URL | 说明 |
|------|-----------|----------|------|
| 查询列表 | GET | `/api/v1/users` | 支持分页、筛选、排序 |
| 查询单个 | GET | `/api/v1/users/{id}` | |
| 创建 | POST | `/api/v1/users` | 请求体为资源数据 |
| 全量更新 | PUT | `/api/v1/users/{id}` | 完整替换资源 |
| 部分更新 | PATCH | `/api/v1/users/{id}` | 只更新指定字段 |
| 删除 | DELETE | `/api/v1/users/{id}` | |

**URL 设计原则：**

- 全部使用小写字母，单词用连字符 `-` 分隔
- 路径使用名词复数形式：`/users` 而非 `/user`
- 版本号放在路径最前面：`/api/v1/xxx`
- 层级不超过 3 层：`/api/v1/users/{id}/orders`

### 4.2 响应格式

统一使用 JSON 响应，结构如下：

```json
{
  "code": 0,
  "message": "success",
  "data": {
    "id": 1,
    "name": "张三"
  }
}
```

**字段说明：**

- `code`：业务状态码，`0` 表示成功，非 0 表示错误
- `message`：状态描述，成功时为 `success`，错误时为错误信息
- `data`：响应数据，可为对象、数组或 null

**分页响应格式：**

```json
{
  "code": 0,
  "message": "success",
  "data": {
    "items": [...],
    "total": 100,
    "page": 1,
    "page_size": 20
  }
}
```

### 4.3 错误处理

- 使用标准 HTTP 状态码表达错误大类
- 业务错误码在响应体中细化

| HTTP 状态码 | 含义 | 典型场景 |
|-------------|------|----------|
| 200 | 成功 | 请求正常处理 |
| 400 | 请求参数错误 | 参数缺失、格式错误 |
| 401 | 未认证 | 未登录或 token 无效 |
| 403 | 无权限 | 已登录但无权操作 |
| 404 | 资源不存在 | 查询的 ID 不存在 |
| 409 | 资源冲突 | 唯一键重复 |
| 429 | 请求过于频繁 | 触发限流 |
| 500 | 服务器内部错误 | 未预期的异常 |

**错误响应示例：**

```json
{
  "code": 10001,
  "message": "用户不存在",
  "data": null
}
```

**错误码规范：**

- 使用 5 位数字，前 2 位表示模块，后 3 位表示具体错误
  - `10xxx`：通用错误（参数、认证、权限等）
  - `20xxx`：用户模块
  - `30xxx`：订单模块
  - ...
- 错误信息使用中文，面向前端可直接展示

---

## 5. Git 提交规范

### 5.1 Commit Message 格式

每条提交消息由 **类型** 和 **描述** 组成，格式如下：

```
<类型>(<模块>): <描述>

<可选：详细说明>
```

- 标题不超过 72 个字符
- 类型和模块使用英文，描述使用中文
- 如有必要，空一行后写详细说明

### 5.2 类型说明

| 类型 | 说明 |
|------|------|
| feat | 新功能 / 新特性 |
| fix | 修复 bug |
| docs | 文档变更 |
| style | 代码格式调整（不影响代码逻辑） |
| refactor | 重构（既不是新增功能也不是修复 bug） |
| perf | 性能优化 |
| test | 测试相关变更 |
| chore | 构建/工具/依赖等辅助工具的变动 |
| revert | 回滚提交 |
| ci | CI/CD 相关变更 |

### 5.3 示例

```
feat(user): 添加用户注册接口

新增用户注册 API，支持手机号和邮箱两种注册方式。
- 实现手机号验证码注册
- 实现邮箱密码注册
- 添加注册频率限制
```

```
fix(order): 修复订单状态更新时并发问题

使用数据库乐观锁替代内存锁，避免分布式场景下的状态不一致。
```

```
chore: 升级 ruff 到 0.6.9 并更新 lint 配置
```

---

## 6. 工具使用说明

### 6.1 环境准备

**1. 安装开发依赖**

```powershell
# 进入项目目录
cd yunxi-project

# （推荐）创建虚拟环境
python -m venv .venv
.venv\Scripts\activate

# 安装开发依赖
pip install -r requirements-dev.txt
```

**2. 安装 pre-commit 钩子**

```powershell
pre-commit install
```

安装后，每次执行 `git commit` 时会自动运行配置的检查项。

### 6.2 ruff 使用

ruff 是本项目的主要 lint 和格式化工具，替代了传统的 flake8 + isort + black 组合。

**常用命令：**

```powershell
# 检查所有 Python 文件的 lint 问题
ruff check .

# 自动修复可修复的 lint 问题
ruff check --fix .

# 格式化所有 Python 文件
ruff format .

# 检查格式差异（不实际修改）
ruff format --check .

# 仅检查指定目录
ruff check yunxi/services/
```

**VS Code 集成：**

安装 [Ruff 扩展](https://marketplace.visualstudio.com/items?itemName=charliermarsh.ruff) 后，保存文件时自动格式化和 lint。

### 6.3 mypy 使用

mypy 用于类型检查，本项目采用宽松模式，结果仅供参考。

```powershell
# 检查整个项目
mypy yunxi/

# 检查指定模块
mypy yunxi/services/user_service.py

# 显示错误统计
mypy --stats yunxi/
```

### 6.4 pre-commit 使用

**常用命令：**

```powershell
# 安装钩子到 .git/hooks
pre-commit install

# 卸载钩子
pre-commit uninstall

# 手动运行所有钩子（对所有文件）
pre-commit run --all-files

# 手动运行指定钩子
pre-commit run ruff --all-files

# 更新钩子版本
pre-commit autoupdate
```

**跳过检查：**

特殊情况下可以跳过 pre-commit 检查（不推荐）：

```powershell
git commit --no-verify -m "your message"
```

### 6.5 codespell 使用

codespell 用于检查代码中的常见拼写错误。

```powershell
# 检查整个项目
codespell .

# 检查指定文件类型
codespell --skip="*.pyc,*.txt" .

# 交互式修复
codespell -i 3 -w .
```

---

## 附录：配置文件速查

| 配置文件 | 作用 |
|----------|------|
| `pyproject.toml` | ruff 和 mypy 的配置入口 |
| `.pre-commit-config.yaml` | pre-commit 钩子配置 |
| `requirements-dev.txt` | 开发环境依赖列表 |
| `.gitignore` | Git 忽略文件列表 |

---

> 本文档将随项目演进而持续更新。如有建议或疑问，请在团队内讨论后修订。
