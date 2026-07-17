# 云汐项目 Monorepo 包管理迁移指南

> **文档编号**: AR-012
> **优先级**: P1
> **状态**: PoC 验证阶段
> **方案选型**: PDM + Workspace
> **创建日期**: 2026-07-17
> **负责人**: Yunxi Team

---

## 目录

1. [背景与问题](#1-背景与问题)
2. [方案选型](#2-方案选型)
3. [目标架构设计](#3-目标架构设计)
4. [版本管理方案](#4-版本管理方案)
5. [依赖管理策略](#5-依赖管理策略)
6. [迁移路线图](#6-迁移路线图)
7. [PoC 验证说明](#7-poc-验证说明)
8. [关键决策点](#8-关键决策点)
9. [风险与回滚](#9-风险与回滚)
10. [FAQ](#10-faq)

---

## 1. 背景与问题

### 1.1 现状

当前云汐项目是一个多模块 monorepo，包含 12+ 个业务模块（M0~M12）和一个 shared 公共库。各模块独立管理依赖，通过 `sys.path` 方式引用 shared 库。

### 1.2 核心痛点

| 痛点 | 影响 | 严重程度 |
|------|------|----------|
| 各模块独立 `requirements.txt` | 依赖版本不一致，部署时可能出现兼容性问题 | 高 |
| shared 库通过 `sys.path` 引用 | 不规范，IDE 支持差，容易出现导入错误 | 高 |
| 无统一版本号管理 | 各模块版本独立，系统级发布困难 | 中 |
| CI 缓存效率低 | 每个模块单独安装依赖，缓存命中率低 | 中 |
| 依赖升级困难 | 需要逐个模块修改，无法统一升级 | 中 |
| 发布流程不清晰 | 缺少 CHANGELOG 管理，版本追溯困难 | 低 |

### 1.3 项目规模

- 模块数量：12+ 业务模块 + 1 个公共库 + 1 个 API 网关
- 代码量：~50K 行 Python 代码
- 依赖数量：单模块平均 15-25 个直接依赖
- Python 版本：3.10+
- 主要框架：FastAPI + SQLAlchemy + Pydantic v2

---

## 2. 方案选型

### 2.1 候选方案

| 维度 | PDM + Workspace | Poetry + Workspace | Hatch + Workspace | 纯 pip + requirements |
|------|-----------------|-------------------|-------------------|----------------------|
| **Monorepo 支持** | 优秀（原生 workspace） | 良好（1.8+ 支持） | 一般（需插件） | 无（需自行管理） |
| **依赖解析速度** | 快（基于 pip-resolution） | 较慢（自定义解析器） | 快（pip-tools） | 慢（无解析） |
| **锁文件支持** | pdm.lock（标准格式） | poetry.lock（自定义格式） | 无（需 pip-tools） | 无（需 pip freeze） |
| **发布管理** | 内置支持 | 内置支持 | 内置支持 | 需手动配置 |
| **PEP 标准遵循** | 高（PEP 621 / 735） | 中（历史包袱） | 高（PEP 621） | 低 |
| **学习曲线** | 中等 | 中等 | 较低 | 最低 |
| **插件生态** | 丰富 | 丰富 | 一般 | 无 |
| **与现有项目兼容性** | 高 | 中 | 高 | 最高 |
| **Windows 支持** | 良好 | 良好 | 良好 | 最好 |
| **CI/CD 适配** | 简单 | 中等 | 简单 | 最简单 |

### 2.2 选型结论

**推荐方案：PDM + Workspace**

#### 核心理由

1. **原生 PEP 标准支持**：完全遵循 PEP 621（项目元数据）、PEP 735（依赖组），无 vendor lock-in，未来迁移成本低
2. **Workspace 成熟度高**：内置 monorepo 工作区支持，包之间依赖通过 `workspace:` 协议自动解析，无需额外配置
3. **解析速度优势**：基于 pip-resolution 引擎，比 Poetry 快 2-3 倍，对大型项目更友好
4. **锁文件可靠**：`pdm.lock` 采用标准格式，支持跨平台一致性
5. **依赖组（Dependency Groups）**：PEP 735 标准实现，比 Poetry 的 groups 更规范
6. **与 M5 模块已有 pyproject.toml 兼容**：M5-tide-memory 已有 pyproject.toml，迁移成本低
7. **插件生态丰富**：支持 pdm-bump（版本管理）、pdm-publish（发布）等官方插件

#### 不选其他方案的原因

- **Poetry**：虽然社区最大，但 workspace 支持较新（1.8+），锁文件格式非标准，迁移到 PEP 标准需要额外工作
- **Hatch**：环境管理强，但 monorepo 支持较弱，需要额外工具配合
- **纯 pip**：维持现状，无法解决核心痛点

---

## 3. 目标架构设计

### 3.1 目录结构

```
yunxi-project/
├── pyproject.toml              # 根配置（workspace 定义 + 全局工具）
├── pdm.lock                    # 统一锁文件
├── .pdm-python                 # Python 版本锁定
├── packages/                   # 所有可发布的包
│   ├── shared/                 # 公共库（核心包）
│   │   ├── pyproject.toml
│   │   ├── README.md
│   │   ├── CHANGELOG.md
│   │   ├── src/
│   │   │   └── yunxi_shared/   # 包名：yunxi_shared
│   │   │       ├── __init__.py
│   │   │       ├── core/       # 核心组件
│   │   │       ├── data/       # 数据层
│   │   │       └── business/   # 业务组件
│   │   └── tests/
│   │
│   ├── api-gateway/            # API 网关
│   │   ├── pyproject.toml
│   │   ├── src/yunxi_gateway/
│   │   └── tests/
│   │
│   ├── m1-agent-hub/           # M1 代理调度中心
│   │   ├── pyproject.toml
│   │   ├── src/yunxi_m1/
│   │   └── tests/
│   │
│   ├── m8-control-tower/       # M8 控制塔
│   │   ├── pyproject.toml
│   │   ├── src/yunxi_m8/
│   │   └── tests/
│   │
│   └── ...                     # 其他模块
│
├── apps/                       # 应用级配置（可选，PoC 阶段不实现）
│   └── deployment/
│
├── docs/                       # 项目文档
│   └── MONOREPO_GUIDE.md       # 本文件
│
├── scripts/                    # 全局脚本
│
└── config/                     # 全局配置
```

### 3.2 包命名规范

| 类型 | 目录名 | PyPI 包名 | Python 导入名 |
|------|--------|-----------|---------------|
| 公共库 | shared | yunxi-shared | yunxi_shared |
| API 网关 | api-gateway | yunxi-api-gateway | yunxi_gateway |
| M1 模块 | m1-agent-hub | yunxi-m1-agent-hub | yunxi_m1 |
| M8 模块 | m8-control-tower | yunxi-m8-control-tower | yunxi_m8 |
| Mx 模块 | mx-xxx-xxx | yunxi-mx-xxx-xxx | yunxi_mx |

**命名规则**：
- 目录名：小写 + 连字符（kebab-case）
- PyPI 包名：`yunxi-` 前缀 + 模块名（kebab-case）
- Python 导入名：`yunxi_` 前缀 + 模块缩写（snake_case）

### 3.3 Workspace 成员间依赖关系

```
                    ┌─────────────┐
                    │ yunxi-shared│  ← 公共基础库
                    └──────┬──────┘
                           │
           ┌───────────────┼───────────────┐
           │               │               │
    ┌──────▼──────┐ ┌──────▼──────┐ ┌──────▼──────┐
    │  api-gateway│ │ m1-agent-hub│ │m8-control-  │
    │             │ │             │ │  tower      │
    └─────────────┘ └─────────────┘ └─────────────┘
           │               │               │
           └───────────────┼───────────────┘
                           │
                    ┌──────▼──────┐
                    │ 其他 M 模块  │
                    └─────────────┘
```

---

## 4. 版本管理方案

### 4.1 版本号规范

采用 **语义化版本（SemVer）**：`MAJOR.MINOR.PATCH`

- **MAJOR**：不兼容的 API 变更
- **MINOR**：向下兼容的功能性新增
- **PATCH**：向下兼容的问题修正

### 4.2 单一真源（Single Source of Truth）

**版本号的唯一来源：根 `pyproject.toml` 的 `version` 字段**

```toml
# pyproject.toml
[project]
name = "yunxi-monorepo"
version = "0.5.0"  # 系统版本号，所有子包继承此版本
```

### 4.3 各模块版本与系统版本的关系

| 策略 | 说明 | 适用场景 |
|------|------|----------|
| **统一版本** | 所有包版本号与系统版本号一致 | PoC 阶段、早期快速迭代 |
| **独立版本** | 各包独立维护版本号 | 成熟稳定后，各模块独立发布 |

**PoC 阶段采用统一版本策略**，理由：
- 项目处于快速迭代期，各模块耦合度高
- 简化发布流程，降低管理成本
- 便于问题定位和版本追溯

### 4.4 版本发布流程

```
开发分支 → 功能完成 → 代码审查 → 合并到 develop
    ↓
    发布分支 (release/x.y.z)
    ↓
    ├── 更新 CHANGELOG.md
    ├── 提升版本号 (pdm bump minor/major/patch)
    ├── 冻结依赖 (pdm lock)
    ├── 运行完整测试
    └── 合并到 main → 打 Tag → 发布
```

### 4.5 CHANGELOG 管理

采用 **Keep a Changelog** 格式，每个包维护独立的 CHANGELOG.md：

```markdown
# Changelog - yunxi-shared

## [0.5.0] - 2026-07-17

### Added
- 新增 xxx 功能
- 新增 yyy 接口

### Changed
- 优化 zzz 性能

### Fixed
- 修复 aaa bug
```

**工具链**：
- 手动维护（当前阶段）
- 未来可考虑：`commitizen` + `conventional commits` 自动生成

---

## 5. 依赖管理策略

### 5.1 依赖分类

#### 5.1.1 核心依赖（Core Dependencies）

所有模块共享的基础依赖，在 `yunxi-shared` 中定义：

| 类别 | 代表依赖 | 说明 |
|------|---------|------|
| Web 框架 | fastapi, uvicorn, pydantic | 所有模块均使用 FastAPI |
| 配置管理 | python-dotenv, pyyaml | 统一配置加载方式 |
| 日志 | structlog | 统一结构化日志 |
| 加密 | cryptography | 统一安全基础 |
| 数据库 | sqlalchemy | 统一 ORM |
| HTTP 客户端 | httpx | 统一异步 HTTP 客户端 |

#### 5.1.2 开发依赖（Dev Dependencies）

在根项目的 `[dependency-groups]` 中统一定义：

| 类别 | 代表依赖 | 说明 |
|------|---------|------|
| Lint/格式化 | ruff, mypy, codespell | 代码质量工具 |
| 测试框架 | pytest, pytest-asyncio, pytest-cov | 测试工具链 |
| 安全扫描 | bandit, pip-audit | 安全审计工具 |
| 代码质量 | radon, pre-commit | 质量保障工具 |

#### 5.1.3 可选依赖（Optional Dependencies）

按功能分组，各模块按需选用，在 `[project.optional-dependencies]` 中定义：

```toml
# yunxi-shared 的可选依赖示例
[project.optional-dependencies]
db = ["alembic", "aiosqlite"]      # 数据库扩展
auth = ["python-jose", "bcrypt"]   # 认证扩展
test = ["pytest", "pytest-asyncio"] # 测试依赖
all = ["yunxi-shared[db,auth,test]"] # 全部
```

### 5.2 版本锁定策略

#### 5.2.1 锁文件

- **位置**：根目录 `pdm.lock`
- **作用**：锁定所有直接和间接依赖的精确版本
- **维护**：修改依赖后执行 `pdm lock` 更新
- **CI 安装**：`pdm sync --frozen-lockfile` 确保 CI 环境与开发环境一致

#### 5.2.2 版本范围规范

| 依赖类型 | 版本范围 | 示例 | 说明 |
|---------|---------|------|------|
| 核心框架 | `>=最低版本,<下一大版本` | `fastapi>=0.100.0,<1.0.0` | 允许小版本升级 |
| 稳定工具库 | `>=最低版本` | `httpx>=0.25.0` | 较宽松 |
| 开发工具 | `>=最低版本,<下一大版本` | `ruff>=0.6.0,<1.0.0` | 防止破坏配置 |
| 生产关键依赖 | 精确版本 `==` | `pydantic==2.9.2` | 最高稳定性 |

### 5.3 安全漏洞扫描

- **工具**：`pip-audit` + `safety`
- **频率**：CI 每日扫描 + 每次发布前扫描
- **响应机制**：高危漏洞 24 小时内修复，中危 7 天内修复

---

## 6. 迁移路线图

### 阶段一：配置准备（不动代码）

**目标**：创建所有配置文件，验证方案可行性，不影响现有开发流程

**任务清单**：
- [x] 创建根 `pyproject.toml`（workspace 配置）
- [x] 创建 `packages/shared/pyproject.toml`（shared 库配置）
- [x] 创建 3 个示例模块的 `pyproject.toml`
- [x] 创建 `.pdm-python` 版本文件
- [x] 更新 `.gitignore`
- [x] 编写迁移指南文档
- [ ] 团队培训：PDM 基础使用
- [ ] CI 环境安装 PDM

**预估工作量**：3 人天
**风险**：低（仅新增配置文件，不改动代码）
**回滚方案**：删除新增的配置文件即可

### 阶段二：shared 库包化（保持向后兼容）

**目标**：将 shared 库打包为可安装的 Python 包，同时保持 `sys.path` 方式可用

**任务清单**：
- [ ] 移动 shared 代码到 `packages/shared/src/yunxi_shared/`
- [ ] 修复包导入路径（`shared.core` → `yunxi_shared.core`）
- [ ] 提供向后兼容层（`shared/` 目录 re-export `yunxi_shared`）
- [ ] 编写 shared 库的完整测试
- [ ] 验证 shared 库可通过 `pip install` 安装
- [ ] 更新 CI 流程，增加 shared 库独立测试

**预估工作量**：5 人天
**风险**：中（导入路径变更可能影响所有模块）
**回滚方案**：保留旧的 `shared/` 目录和 `sys.path` 方式，出现问题可立即回退

**向后兼容策略**：
```python
# shared/__init__.py （兼容层）
# 将 yunxi_shared 的内容 re-export，保证旧代码无需修改
from yunxi_shared.core import *
from yunxi_shared.data import *
from yunxi_shared.business import *
```

### 阶段三：逐个模块迁移

**目标**：将各模块逐个迁移到 workspace 结构

**迁移顺序建议**（按依赖关系从下到上）：
1. M5-tide-memory（已有 pyproject.toml，最容易）
2. M12-security-shield（依赖少）
3. M11-mcp-bus
4. M10-system-guard
5. M9-dev-workshop
6. M7-workflow-builder
7. M6-hardware-peripheral
8. M4-scene-engine
9. M3-edge-cloud
10. M2-skills-cluster
11. M1-agent-hub（PoC 已完成配置）
12. M8-control-tower（PoC 已完成配置）
13. API-Gateway（PoC 已完成配置）
14. M0-principal-console

**每个模块的迁移步骤**：
1. 创建 `packages/<module>/pyproject.toml`
2. 移动代码到 `src/yunxi_<xx>/` 目录
3. 修复导入路径
4. 声明对 `yunxi-shared` 的依赖
5. 运行测试验证
6. 更新 CI 配置

**预估工作量**：每个模块 1-2 人天，总计 ~20 人天
**风险**：中（模块间依赖关系复杂，需逐个验证）
**回滚方案**：每个模块独立迁移，出问题仅回滚单个模块

### 阶段四：清理旧方式

**目标**：移除旧的 `sys.path` 方式和 `requirements.txt`

**任务清单**：
- [ ] 删除所有模块的 `requirements.txt`
- [ ] 删除 `sys.path.append` 相关代码
- [ ] 删除兼容层（shared/ 旧目录）
- [ ] 统一使用 `pdm run` 启动各模块
- [ ] 更新所有文档中的安装说明

**预估工作量**：3 人天
**风险**：高（删除旧方式后无法快速回退）
**回滚方案**：从 Git 历史恢复旧文件

**前置条件**：
- 所有模块迁移完成并稳定运行 2 周以上
- CI/CD 全部切换到 PDM
- 所有开发人员已熟悉 PDM 工作流

### 阶段五：CI/CD 深度适配

**目标**：充分利用 PDM 特性优化 CI/CD 流程

**任务清单**：
- [ ] 优化 CI 缓存策略（缓存 `pdm.lock` 解析结果）
- [ ] 实现按模块变更触发测试（monorepo 增量测试）
- [ ] 实现依赖自动更新（Dependabot 或 pdm update --check）
- [ ] 实现自动化版本发布流程
- [ ] 集成安全扫描到 CI 流水线

**预估工作量**：5 人天
**风险**：低（优化性质，不影响功能）
**回滚方案**：回退到旧 CI 配置

### 总览甘特图

```
阶段一: ██████ (3天)
阶段二:       ██████████ (5天)
阶段三:           ████████████████████████████ (20天)
阶段四:                                       ██████ (3天)
阶段五:                                       ██████████ (5天，可与阶段四并行)
```

**总预估工作量**：~36 人天
**建议时间窗口**：2-3 个迭代周期（6-9 周）

---

## 7. PoC 验证说明

### 7.1 已创建的文件

| 文件路径 | 说明 | 状态 |
|---------|------|------|
| `pyproject.toml` | 根 workspace 配置（已更新，保留原有 ruff/mypy 配置） | 已创建 |
| `packages/shared/pyproject.toml` | shared 库包化配置 | 已创建 |
| `packages/m8-control-tower/pyproject.toml` | M8 模块配置示例 | 已创建 |
| `packages/m1-agent-hub/pyproject.toml` | M1 模块配置示例 | 已创建 |
| `packages/api-gateway/pyproject.toml` | API 网关配置示例 | 已创建 |
| `.pdm-python` | Python 版本锁定 | 已创建 |
| `.gitignore` | 新增 PDM 相关忽略项 | 已更新 |
| `docs/MONOREPO_GUIDE.md` | 本迁移指南 | 已创建 |

### 7.2 验证步骤

#### 前置条件

```bash
# 安装 PDM
pip install pdm

# 验证安装
pdm --version
```

#### 验证 1：Workspace 成员识别

```bash
# 在项目根目录执行
pdm info --workspace

# 预期输出：列出所有 workspace 成员包
# - packages/shared
# - packages/m8-control-tower
# - packages/m1-agent-hub
# - packages/api-gateway
```

#### 验证 2：依赖安装

```bash
# 安装所有依赖（首次执行较慢）
pdm install -G dev

# 验证 shared 库可被导入
pdm run python -c "from yunxi_shared.core.config import settings; print('OK')"
```

#### 验证 3：模块间依赖

```bash
# 进入 M8 模块目录
cd packages/m8-control-tower

# 查看依赖树
pdm list --graph

# 验证 yunxi-shared 被正确解析为 workspace 依赖
pdm run python -c "import yunxi_shared; print(yunxi_shared.__version__)"
```

#### 验证 4：运行测试

```bash
# 在根目录运行所有测试
pdm run pytest

# 运行单个模块的测试
pdm run pytest packages/shared/tests/
```

### 7.3 PoC 不包含的内容

以下内容不在本次 PoC 范围内，留待正式迁移时实现：

- [ ] 实际移动代码到 `packages/` 目录
- [ ] 修改导入路径（`shared.xxx` → `yunxi_shared.xxx`）
- [ ] 删除旧的 `requirements.txt`
- [ ] 删除 `sys.path` 引用方式
- [ ] CI/CD 流水线改造
- [ ] 前端部分的 monorepo 改造（如有需要，可考虑 pnpm/npm workspaces）

---

## 8. 关键决策点

### 决策 1：包管理工具选择

- **决策**：PDM
- **理由**：见第 2 节方案选型
- **影响范围**：全项目
- **可逆性**：中等（迁移到 Poetry 也可行，但有一定成本）

### 决策 2：包的导入命名空间

- **决策**：统一使用 `yunxi_` 前缀（如 `yunxi_shared`, `yunxi_m8`）
- **理由**：
  - 避免与其他包命名冲突
  - 清晰标识项目归属
  - 符合 Python 包命名最佳实践
- **影响范围**：所有模块的导入语句
- **可逆性**：低（导入路径变更影响面大）

### 决策 3：版本管理策略

- **决策**：PoC 阶段采用统一版本号，成熟后考虑独立版本
- **理由**：当前项目耦合度高，独立版本管理成本大于收益
- **影响范围**：发布流程
- **可逆性**：高（未来可随时切换为独立版本）

### 决策 4：目录结构布局

- **决策**：所有包放在 `packages/` 目录下
- **理由**：
  - 与 PDM workspace 的默认模式一致
  - 清晰区分包和非包内容（文档、脚本、配置等）
  - 业界主流做法（参考 Turborepo、Nx 等）
- **影响范围**：目录结构调整
- **可逆性**：中等（移动目录有一定成本）

### 决策 5：向后兼容策略

- **决策**：迁移过程中保留旧的导入方式作为兼容层
- **理由**：降低迁移风险，支持渐进式迁移
- **影响范围**：shared 库
- **可逆性**：高（兼容层可随时删除）

---

## 9. 风险与回滚

### 9.1 风险矩阵

| 风险 | 概率 | 影响 | 等级 | 缓解措施 |
|------|------|------|------|---------|
| 导入路径变更导致大量错误 | 中 | 高 | 高 | 保留兼容层，逐个模块迁移验证 |
| 依赖版本冲突 | 中 | 中 | 中 | 统一锁文件，CI 验证 |
| 团队学习成本 | 高 | 低 | 中 | 培训 + 文档 + 渐进式引入 |
| CI/CD 改造影响发布 | 低 | 高 | 中 | 新旧方式并行，稳定后切换 |
| Windows 兼容性问题 | 低 | 中 | 低 | PoC 阶段充分验证 |
| PDM 社区活跃度下降 | 低 | 中 | 低 | 基于 PEP 标准，迁移成本低 |

### 9.2 回滚方案

#### 快速回滚（< 1 小时）

适用于 PoC 阶段和迁移早期：

```bash
# 1. 删除 PDM 相关文件
rm pyproject.toml  # 恢复旧版本
rm -rf packages/
rm .pdm-python

# 2. 从 Git 恢复旧文件
git checkout <commit-before-migration> -- pyproject.toml

# 3. 继续使用旧方式
pip install -r requirements-dev.txt
```

#### 模块级回滚

适用于单个模块迁移失败：

```bash
# 1. 将模块从 packages/ 移回原位置
mv packages/m8-control-tower/* M8-control-tower/

# 2. 恢复该模块的 requirements.txt
git checkout <commit> -- M8-control-tower/requirements.txt

# 3. 恢复导入路径
# 将 yunxi_shared 改回 shared
```

### 9.3 迁移锚点

开始迁移前，创建 Git Tag 作为回滚锚点：

```bash
# 迁移前打 Tag
git tag -a pre-monorepo-migration -m "Monorepo 迁移前的稳定版本"

# 如需回滚
git checkout pre-monorepo-migration
```

---

## 10. FAQ

### Q1：为什么不用 Poetry？Poetry 社区更大。

A：Poetry 确实社区更大，但有以下问题：
1. Poetry 的 workspace 支持较新（1.8 版本才加入），成熟度不如 PDM
2. Poetry 的锁文件格式是自定义的，不是标准格式
3. PDM 完全遵循 PEP 621 / PEP 735 标准，未来迁移成本更低
4. PDM 的依赖解析速度更快

如果团队更熟悉 Poetry，迁移成本也不会太高，因为两者都基于 pyproject.toml。

### Q2：shared 库为什么要改名为 yunxi_shared？

A：主要原因：
1. `shared` 是一个非常通用的名字，容易与其他包冲突
2. 加上 `yunxi_` 前缀可以清晰标识项目归属
3. 符合 Python 社区的命名最佳实践
4. 未来如果开源，命名空间更清晰

### Q3：为什么不使用 src 布局？

A：PoC 阶段为了降低改动量，暂时使用了指向原目录的方式。正式迁移时会采用标准的 `src/` 布局，这是 Python 打包的最佳实践。

### Q4：每个模块都要变成可发布的包吗？

A：不一定。对于仅内部使用、不需要独立发布的模块，可以：
1. 仍然作为 workspace 成员，但不配置发布
2. 或者放在 `apps/` 目录下，不作为独立包

建议所有模块都作为 workspace 成员，统一管理依赖，但只有 shared 库等少数包需要发布到 PyPI。

### Q5：PDM 在 Windows 上好用吗？

A：PDM 对 Windows 的支持很好，官方 CI 包含 Windows 测试。相比之下，Poetry 在 Windows 上也不错，但 PDM 的虚拟环境管理对 Windows 更友好。

### Q6：迁移期间日常开发怎么进行？

A：迁移期间新旧方式并行：
- 已迁移的模块：使用 `pdm run` 启动
- 未迁移的模块：继续使用 `pip install -r requirements.txt` + `sys.path`
- shared 库：通过兼容层同时支持两种导入方式

### Q7：前端部分怎么处理？

A：本次 PoC 仅覆盖 Python 后端。前端部分如果也需要 monorepo 管理，可以考虑：
- pnpm workspaces（推荐，速度快）
- npm workspaces（内建，简单）
- Turborepo（构建优化）

前端 monorepo 改造是另一个独立的项目，不在本次范围内。

---

## 附录

### A. PDM 常用命令速查

```bash
# 初始化
pdm init                    # 创建新项目
pdm install                 # 安装所有依赖
pdm install -G dev          # 安装指定依赖组

# 依赖管理
pdm add requests            # 添加依赖
pdm add -dG dev pytest      # 添加到开发依赖组
pdm remove requests         # 移除依赖
pdm update                  # 更新所有依赖
pdm lock                    # 更新锁文件

# 运行
pdm run python script.py    # 运行脚本
pdm run pytest              # 运行测试
pdm run lint                # 运行自定义脚本

# Workspace
pdm info --workspace        # 查看 workspace 成员
pdm list --workspace        # 列出所有 workspace 包

# 发布
pdm build                   # 构建包
pdm publish                 # 发布到 PyPI
```

### B. 相关文档链接

- [PDM 官方文档](https://pdm.fming.dev/)
- [PEP 621 - 项目元数据](https://peps.python.org/pep-0621/)
- [PEP 735 - 依赖组](https://peps.python.org/pep-0735/)
- [SemVer 语义化版本](https://semver.org/lang/zh-CN/)
- [Keep a Changelog](https://keepachangelog.com/zh-CN/)

### C. 变更记录

| 版本 | 日期 | 变更内容 | 作者 |
|------|------|---------|------|
| 0.1.0 | 2026-07-17 | 初始版本，PoC 方案设计 | Yunxi Team |

---

**文档结束**
