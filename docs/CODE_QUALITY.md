# 代码质量规范

## 概述

本文档定义云汐项目的代码质量标准、检查工具和质量门禁要求。所有提交到 main/develop 分支的代码都应符合本文档的规范。

## 质量工具清单

| 工具 | 检查维度 | 配置文件 | 阻断级别 |
|------|----------|----------|----------|
| Ruff Lint | 代码风格、常见 bug、安全、复杂度 | `pyproject.toml` | 信息性 |
| Ruff Format | 代码格式化 | `pyproject.toml` | 信息性 |
| Mypy | 类型安全 | `pyproject.toml` | 信息性（核心模块） |
| Bandit | 安全漏洞 | `.bandit` | 信息性 |
| Radon | 代码复杂度、可维护性 | `.radon` | 信息性 |
| pytest + pytest-cov | 测试质量、覆盖率 | `pytest.ini` / `.coveragerc` | 信息性 |
| codespell | 拼写检查 | `.pre-commit-config.yaml` | 信息性 |

> 注：当前阶段所有工具均为信息性输出（不阻断提交），后续将逐步提升为阻断性门禁。

## 代码风格规范

### 行长度

- **最大行长度**: 120 字符
- 长字符串、URL、注释等可适当超出，但应尽量避免

### 缩进

- 使用 4 空格缩进（不使用 Tab）
- 换行使用括号内垂直悬挂缩进

### 命名规范

| 类型 | 规范 | 示例 |
|------|------|------|
| 模块/包 | 全小写，下划线分隔 | `user_profile`, `api_client` |
| 类 | 大驼峰（PascalCase） | `UserManager`, `ApiClient` |
| 函数/方法 | 全小写，下划线分隔 | `get_user()`, `process_data()` |
| 常量 | 全大写，下划线分隔 | `MAX_RETRY`, `DEFAULT_TIMEOUT` |
| 变量 | 全小写，下划线分隔 | `user_name`, `result_list` |
| 私有成员 | 前缀单下划线 | `_internal_method()`, `_cache` |

### 导入排序

按照以下顺序分组，组间空一行：

1. `__future__` 导入
2. 标准库导入
3. 第三方库导入
4. 本地项目导入（shared/各模块）
5. 相对导入（`.` 开头）

示例：

```python
from __future__ import annotations

import os
import sys
from datetime import datetime
from typing import List, Optional

import httpx
from fastapi import FastAPI

from shared.core.config import BaseConfig
from shared.core.errors import AppError

from .models import User
```

### 文档字符串

- 使用 Google 风格 docstring
- 公共 API 必须有 docstring
- 模块、类、公共方法/函数建议添加 docstring
- `__init__.py` 和 `__init__` 方法不强制 docstring

示例：

```python
def fetch_data(url: str, timeout: int = 30) -> dict:
    """从指定 URL 获取数据。

    Args:
        url: 目标 URL
        timeout: 请求超时时间（秒）

    Returns:
        解析后的 JSON 数据字典

    Raises:
        ConnectionError: 网络连接失败
        ValueError: 响应格式错误
    """
    ...
```

### 注释

- 注释应解释"为什么"而非"做什么"
- 避免与代码重复的无意义注释
- 使用中文注释（团队协作语言）
- `TODO` / `FIXME` 注释应标注负责人和日期

```python
# TODO(zhangsan): 2024-06-01 优化算法，当前时间复杂度为 O(n^2)
```

## 类型检查规范

### 渐进式策略

采用渐进式类型检查，从核心模块开始逐步推广：

| 模块 | 严格度 | 要求 |
|------|--------|------|
| `shared/core` | 中等 | 所有函数必须有类型标注 |
| `shared/data` | 中等 | 所有函数必须有类型标注 |
| `shared/business` | 宽松 | 仅检查已有标注的代码 |
| 其他模块 | 宽松 | 不强制类型标注 |
| 测试代码 | 最宽松 | 不检查类型错误 |

### 类型标注建议

- 公共 API 必须有完整的类型标注
- 返回类型必须标注，不能依赖推断
- 复杂类型使用 `typing` 模块（Python 3.10+ 也可使用内置类型）
- 使用 `TypeVar` 和 `Generic` 处理泛型

```python
# 推荐
def process_items(items: list[str]) -> dict[str, int]:
    """处理项目列表，返回统计结果。"""
    result: dict[str, int] = {}
    for item in items:
        result[item] = result.get(item, 0) + 1
    return result
```

### 类型忽略

使用 `# type: ignore` 时必须标注原因：

```python
result = some_dynamic_function()  # type: ignore[attr-defined]  # 动态属性，运行时存在
```

## 安全编码规范

### 必须遵守

1. **禁止硬编码密钥/密码**：使用环境变量或配置文件
2. **SQL 注入防护**：使用参数化查询，禁止字符串拼接 SQL
3. **XSS 防护**：用户输入输出必须转义
4. **密码存储**：使用 bcrypt/argon2 等安全哈希算法
5. **JWT 安全**：使用强密钥、设置合理过期时间
6. **文件上传**：校验文件类型、大小、存储路径

### Bandit 规则

启用的主要安全规则：

| 规则 ID | 说明 |
|---------|------|
| S101 | 测试文件外的 assert 使用 |
| S301-S320 | 不安全的加密算法 |
| S401-S409 | 不安全的模块导入 |
| S501-S509 | 注入类漏洞 |
| S601-S609 | 命令注入风险 |
| S701-S707 | 其他安全问题 |

已豁免的规则（全局）：
- `S101`: 测试文件中允许使用 assert
- `S311`: `random` 模块用于非安全场景
- `S602/S603/S607`: 子进程调用（已做参数校验）

## 复杂度规范

### 圈复杂度（Cyclomatic Complexity）

使用 McCabe 圈复杂度度量，阈值如下：

| 等级 | 复杂度 | 说明 | 处理建议 |
|------|--------|------|----------|
| A | 1-5 | 非常简单 | 无需处理 |
| B | 6-10 | 低复杂度 | 无需处理 |
| C | 11-15 | 中等复杂度 | 关注，考虑重构 |
| D | 16-20 | 高复杂度 | 建议重构 |
| E | 21-30 | 非常复杂 | 必须重构 |
| F | 31+ | 极复杂 | 必须拆分 |

- **当前告警阈值**: C 级（>10）
- **重构阈值**: D 级（>15）

### 可维护性指数（Maintainability Index）

| 等级 | 指数 | 说明 |
|------|------|------|
| A | 100-80 | 高可维护性 |
| B | 79-65 | 中等可维护性 |
| C | 64-50 | 低可维护性 |
| D | 49-0 | 极低可维护性 |

### 函数长度建议

- 理想：< 30 行
- 警告：30-50 行
- 必须重构：> 50 行

## 测试规范

### 测试类型比例

| 类型 | 比例 | 说明 |
|------|------|------|
| 单元测试 | 70% | 快速、独立、mock 外部依赖 |
| 集成测试 | 20% | 模块间交互测试 |
| 端到端测试 | 10% | 完整业务流程 |

### 覆盖率目标

| 模块 | 目标覆盖率 |
|------|-----------|
| shared/core | >= 70% |
| shared/data | >= 65% |
| 核心业务模块 | >= 60% |
| 整体核心 | >= 60% |

### 测试质量要求

- 每个测试必须独立，不依赖执行顺序
- 使用 fixtures 管理测试数据和环境
- 测试命名清晰，描述预期行为
- 遵循 AAA 模式（Arrange-Act-Assert）
- 边界条件必须覆盖

## 质量门禁

### 提交前（pre-commit）

每次 git commit 前自动运行：

1. 行尾空格清理
2. 文件末尾换行检查
3. YAML/JSON/TOML 格式检查
4. 合并冲突标记检查
5. 大文件检测（>500KB）
6. Ruff 代码格式化
7. Ruff Lint 检查（自动修复）
8. Mypy 类型检查（核心模块）
9. Bandit 安全扫描（核心模块）
10. 拼写检查

### CI 流水线

CI 流水线包含以下 Job：

1. **代码质量检查**：Ruff Lint + Format + Mypy + Bandit + Radon
2. **单元测试与覆盖率**：多 Python 版本矩阵测试
3. **集成测试**：模块间交互测试
4. **构建与结构检查**：语法检查 + 模块完整性
5. **质量门禁汇总**：综合质量报告

### 质量评级

根据检查通过率计算质量评级：

| 等级 | 通过率 | 说明 |
|------|--------|------|
| A | >= 90% | 优秀 |
| B | 75-89% | 良好 |
| C | 60-74% | 合格 |
| D | < 60% | 需改进 |

## 工具使用指南

### 本地快速检查

```bash
# 一键运行所有质量检查（Windows）
.\scripts\quality_check.ps1

# 快速模式（仅 lint + format）
.\scripts\quality_check.ps1 -Quick

# 仅核心模块
.\scripts\quality_check.ps1 -CoreOnly

# 自动修复模式
.\scripts\quality_check.ps1 -Fix
```

### 运行特定工具

```bash
# Ruff 检查并自动修复
ruff check --fix shared/core

# Ruff 格式化
ruff format shared/core

# Mypy 类型检查
mypy shared/core shared/data --config-file=pyproject.toml

# Bandit 安全扫描
bandit -r shared/core -ll -c .bandit

# Radon 复杂度分析
radon cc shared/core -a -nc
radon mi shared/core -s

# 测试覆盖率
pytest --cov=shared/core --cov-report=term-missing --cov-report=html
```

### Pre-commit 钩子

```bash
# 安装钩子（首次使用）
pre-commit install

# 手动运行所有检查
pre-commit run --all-files

# 运行特定钩子
pre-commit run ruff --all-files
pre-commit run mypy --all-files

# 更新钩子版本
pre-commit autoupdate
```

## 渐进式推进计划

### 阶段一：信息性输出（当前）
- 所有工具均为信息性输出
- 不阻断提交和合并
- 目标：发现问题、积累数据

### 阶段二：核心模块阻断
- Ruff Lint（E/F 级别错误）→ 阻断
- Ruff Format → 阻断
- 核心模块单元测试 → 阻断
- 覆盖率核心模块 >= 50%

### 阶段三：全模块质量门禁
- Ruff Lint 全部规则 → 阻断
- Mypy 核心模块 → 阻断
- Bandit 高危问题 → 阻断
- 覆盖率核心模块 >= 60%

### 阶段四：全面质量门禁
- 所有质量工具 → 阻断
- 覆盖率核心模块 >= 70%
- 代码复杂度 D 级以上 → 阻断
- 安全扫描中危及以上 → 阻断

## 附录

### 相关配置文件

- `pyproject.toml` - Ruff / Mypy 配置
- `pytest.ini` - pytest 配置
- `.coveragerc` - 覆盖率配置
- `.bandit` - Bandit 安全扫描配置
- `.radon` - Radon 复杂度配置
- `.pre-commit-config.yaml` - pre-commit 钩子配置
- `.github/workflows/ci.yml` - CI 流水线配置

### 参考文档

- [PEP 8 - Style Guide for Python Code](https://peps.python.org/pep-0008/)
- [Ruff 规则列表](https://docs.astral.sh/ruff/rules/)
- [Mypy 官方文档](https://mypy.readthedocs.io/)
- [Bandit 规则列表](https://bandit.readthedocs.io/en/latest/plugins/)
- [pytest 官方文档](https://docs.pytest.org/)
