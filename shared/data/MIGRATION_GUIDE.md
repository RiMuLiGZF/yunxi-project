# 数据迁移框架使用指南

> 本文档介绍云汐项目统一数据迁移框架的使用方法、版本规范和最佳实践。

## 目录

- [1. 框架概述](#1-框架概述)
- [2. 核心组件](#2-核心组件)
- [3. 快速开始](#3-快速开始)
- [4. 迁移脚本规范](#4-迁移脚本规范)
- [5. 版本管理](#5-版本管理)
- [6. 命令行工具](#6-命令行工具)
- [7. 模块接入指南](#7-模块接入指南)
- [8. 最佳实践](#8-最佳实践)
- [9. 故障排查](#9-故障排查)

---

## 1. 框架概述

### 1.1 设计目标

统一数据迁移框架为全模块提供标准化的数据库版本管理能力，核心目标：

- **统一接口**：所有模块使用相同的迁移 API 和 CLI
- **双后端支持**：同时支持 SQLite 和 PostgreSQL
- **数据安全**：迁移前自动备份，支持完整性校验
- **幂等可靠**：迁移脚本可重复执行，不会破坏数据
- **可回滚**：每个迁移版本都有对应的回滚脚本
- **可追踪**：完整的迁移历史和审计记录

### 1.2 架构层次

```
┌─────────────────────────────────────────┐
│           统一迁移 CLI (migrate.py)      │  ← 命令行入口
├─────────────────────────────────────────┤
│      各模块迁移管理器 (migration_manager) │  ← 模块级封装
├─────────────────────────────────────────┤
│       EnhancedMigrationEngine           │  ← 增强型迁移引擎
│  (完整性校验 / 重试 / Dry-run / 检查点)  │
├─────────────────────────────────────────┤
│           MigrationEngine               │  ← 基础迁移引擎
│  (版本管理 / 迁移执行 / 回滚 / 历史)     │
├─────────────────────────────────────────┤
│   SQLite 适配器   │   PostgreSQL 适配器  │  ← 数据库适配层
├─────────────────────────────────────────┤
│  DatabaseManager │  SQLAlchemy Engine   │  ← 底层数据库
└─────────────────────────────────────────┘
```

### 1.3 已接入模块

| 模块 | 数据库类型 | 迁移管理器 | 迁移脚本数 |
|------|-----------|-----------|-----------|
| M0 主理人管控台 | SQLite | `src/migration_manager.py` | 2 |
| M4 场景引擎 | SQLite | `src/models/db/migrations/` | 1+ |
| M5 成长核心 | SQLite | `database/migration_manager.py` | 2+ |
| M6 硬件外设 | SQLite | `database/migrations/` | 2 |
| M7 工作流构建器 | SQLite | `src/migrations/` | 1 |
| M9 开发工坊 | SQLite | `backend/migration_manager.py` | 2 |
| M10 系统卫士 | SQLite | `m10_system_guard/migration_manager.py` | 2 |
| M12 安全盾 | SQLite | `backend/migration_manager.py` | 2 |

---

## 2. 核心组件

### 2.1 MigrationEngine（基础迁移引擎）

位置：`shared/data/data_layer/migration.py`

核心功能：
- 版本化迁移管理
- 迁移脚本自动扫描
- 升级（up）和回滚（down）
- 迁移历史记录
- 迁移前自动备份
- 校验和验证

### 2.2 EnhancedMigrationEngine（增强型迁移引擎）

位置：`shared/data/data_layer/migration_enhanced.py`

在基础引擎之上提供：

| 特性 | 说明 |
|------|------|
| 数据完整性校验 | 迁移前后行数对比，检测数据丢失 |
| 错误重试机制 | 指数退避重试，应对临时性错误 |
| 幂等性保证 | 确保迁移脚本可安全重复执行 |
| Dry-run 模式 | 模拟执行，预览变更而不实际修改 |
| 进度追踪 | 实时显示迁移进度 |
| 检查点/断点续传 | 中断后可从检查点继续 |

### 2.3 PostgreSQL 适配器

位置：`shared/data/data_layer/postgres_adapter.py`

提供 PostgreSQL 数据库的迁移适配能力，支持：
- DSN 字符串或连接参数初始化
- 事务管理
- Schema 隔离
- 与 MigrationEngine 完全兼容

### 2.4 BackupManager（备份管理器）

位置：`shared/data/data_layer/backup_manager.py`

- 自动备份（迁移前触发）
- 多格式支持（SQLite 文件拷贝 / pg_dump）
- 备份压缩
- 备份验证
- 保留策略

---

## 3. 快速开始

### 3.1 使用统一 CLI

```bash
# 进入 shared/data/data_layer 目录
cd shared/data/data_layer

# 查看所有可用模块
python migrate.py status --list

# 查看所有模块迁移状态
python migrate.py status --all

# 迁移指定模块到最新版本
python migrate.py migrate --module m5

# 迁移所有模块（dry-run 模式，先预览）
python migrate.py migrate --all --dry-run

# 确认无误后执行实际迁移
python migrate.py migrate --all

# 回滚指定模块到版本 0
python migrate.py rollback --module m10 --target 0

# 检查数据库完整性
python migrate.py check --all
```

### 3.2 使用模块级 CLI

每个模块也有自己独立的迁移命令：

```bash
# M0 主理人管控台
cd M0-principal-console/src
python migration_manager.py status
python migration_manager.py migrate --dry-run
python migration_manager.py migrate

# M10 系统卫士
cd M10-system-guard/m10_system_guard
python migration_manager.py status
python migration_manager.py migrate

# M12 安全盾
cd M12-security-shield/backend
python migration_manager.py status
python migration_manager.py migrate
```

### 3.3 在代码中使用

```python
from data.data_layer import MigrationEngine, EnhancedMigrationEngine

# 基础迁移
engine = MigrationEngine(db_manager=dbm)
result = engine.migrate(db_name="mydb", migrations=migrations)

# 增强型迁移（推荐）
enhanced = EnhancedMigrationEngine(engine=engine)
result = enhanced.migrate_enhanced(
    db_name="mydb",
    migrations=migrations,
    dry_run=False,
    enable_integrity_check=True,
    enable_retry=True,
    pre_migration_backup=True,
)
```

---

## 4. 迁移脚本规范

### 4.1 文件命名

迁移脚本文件必须放在模块的 `migrations/` 目录下，命名格式：

```
v{版本号}_{描述性名称}.py
```

示例：
```
migrations/
├── __init__.py
├── v001_initial.py          # 初始表结构
├── v002_user_profile.py     # 新增用户资料表
├── v003_add_indexes.py      # 新增索引
└── v004_audit_logs.py       # 新增审计日志表
```

**版本号规则**：
- 使用 3 位数字，零填充（v001, v002, ..., v999）
- 版本号全局递增，不可重复
- 合并代码时如果版本号冲突，后合并的一方需要递增版本号

### 4.2 脚本结构

每个迁移脚本必须包含：

```python
"""
迁移脚本 v001 - initial

描述此迁移的功能和变更内容。
"""

from __future__ import annotations

# 迁移元数据（必需）
__migration_name__ = "initial"           # 迁移名称
__description__ = "初始表结构创建"       # 迁移描述


def up(conn):
    """
    升级迁移 - 执行数据库变更

    Args:
        conn: 数据库连接对象
              - SQLite/DatabaseManager 模式：传入 (engine, db_name)
              - SQLAlchemy 模式：传入 Connection 对象
    """
    # 你的升级逻辑
    pass


def down(conn):
    """
    降级迁移（回滚） - 撤销数据库变更

    Args:
        conn: 数据库连接对象（同 up）
    """
    # 你的回滚逻辑
    pass
```

### 4.3 两种脚本风格

#### 风格 A：SQLAlchemy 模式（推荐用于 SQLAlchemy 项目）

```python
def up(conn):
    from sqlalchemy import text

    conn.execute(text("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name VARCHAR(100) NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """))

    conn.execute(text("""
        CREATE INDEX IF NOT EXISTS idx_users_name ON users (name)
    """))


def down(conn):
    from sqlalchemy import text

    conn.execute(text("DROP TABLE IF EXISTS users"))
```

#### 风格 B：DatabaseManager 模式（用于原生 SQLite 项目）

```python
def up(engine, db_name: str = "m0"):
    engine.execute(db_name, """
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            created_at TEXT NOT NULL
        )
    """)

    engine.execute(db_name,
        "CREATE INDEX IF NOT EXISTS idx_users_name ON users (name)"
    )


def down(engine, db_name: str = "m0"):
    engine.execute(db_name, "DROP TABLE IF EXISTS users")
```

### 4.4 编写要求

1. **幂等性**：使用 `IF NOT EXISTS` / `IF EXISTS` 确保脚本可重复执行
2. **安全性**：删除操作必须谨慎，回滚脚本不能丢失数据
3. **原子性**：单个迁移脚本应在一个事务中完成
4. **向后兼容**：新增字段必须有默认值或允许 NULL
5. **性能**：大表变更需考虑锁表时间，必要时分批处理
6. **文档**：脚本头部必须有清晰的功能描述

---

## 5. 版本管理

### 5.1 版本号规则

- 版本号是单调递增的整数（从 1 开始）
- 每个迁移脚本对应一个版本号
- 版本 0 表示未执行任何迁移（空数据库）
- 迁移记录表（`schema_migrations`）记录当前版本

### 5.2 迁移记录表

框架自动创建 `schema_migrations` 表，记录：

| 字段 | 说明 |
|------|------|
| version | 版本号 |
| name | 迁移名称 |
| description | 迁移描述 |
| applied_at | 应用时间 |
| duration_ms | 执行耗时（毫秒） |
| status | 状态（success/failed） |
| checksum | 迁移脚本校验和 |
| rollback_available | 是否可回滚 |

### 5.3 回滚策略

- 每个迁移必须有对应的 `down()` 函数
- 默认支持回滚到任意历史版本
- 破坏性迁移（如删除表）回滚后数据丢失
- 建议：回滚前自动备份

---

## 6. 命令行工具

### 6.1 统一 CLI

位置：`shared/data/data_layer/migrate.py`

#### 命令列表

| 命令 | 说明 |
|------|------|
| `init` | 初始化迁移记录表 |
| `migrate` | 执行迁移（升级） |
| `rollback` | 回滚迁移（降级） |
| `status` | 查看迁移状态 |
| `history` | 查看迁移历史 |
| `check` | 检查数据库完整性 |

#### 通用参数

| 参数 | 说明 |
|------|------|
| `--module, -m` | 指定模块（多个用逗号分隔） |
| `--all, -a` | 操作所有模块 |

#### migrate 命令参数

| 参数 | 说明 | 默认值 |
|------|------|--------|
| `--target` | 目标版本号 | 最新版本 |
| `--no-backup` | 跳过迁移前备份 | False（不跳过） |
| `--dry-run` | 试运行模式 | False |
| `--no-retry` | 禁用错误重试 | False（启用重试） |

#### rollback 命令参数

| 参数 | 说明 | 默认值 |
|------|------|--------|
| `--target` | 回滚到的版本号 | 0（全部回滚） |
| `--force` | 跳过确认提示 | False |

### 6.2 退出码

| 退出码 | 说明 |
|--------|------|
| 0 | 全部成功 |
| 1 | 部分或全部失败 |

---

## 7. 模块接入指南

### 7.1 接入步骤

为新模块添加迁移能力，需完成以下步骤：

#### 步骤 1：创建迁移目录

```bash
mkdir -p <module_path>/migrations
touch <module_path>/migrations/__init__.py
```

#### 步骤 2：编写初始迁移脚本

创建 `migrations/v001_initial.py`，包含所有现有表的建表语句。

```python
"""
迁移脚本 v001 - initial
模块名 初始表结构创建。
"""

from __future__ import annotations

__migration_name__ = "initial"
__description__ = "模块名 初始表结构"


def up(conn):
    from sqlalchemy import text
    # 建表语句...
    pass


def down(conn):
    from sqlalchemy import text
    # 删除表...
    pass
```

#### 步骤 3：创建迁移管理器

创建 `migration_manager.py`，封装 MigrationEngine。

参考模板（SQLAlchemy 模式）：

```python
"""模块名 - 迁移管理器"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Optional

# 确保 shared 在路径中
project_root = Path(__file__).resolve().parent.parent.parent
shared_path = str(project_root / "shared")
if shared_path not in sys.path:
    sys.path.insert(0, shared_path)

from data.data_layer import (
    MigrationEngine,
    EnhancedMigrationEngine,
    SQLAlchemyMigrationAdapter,
)

from .database import engine, settings


class ModuleMigrationManager:
    def __init__(self):
        self._adapter = SQLAlchemyMigrationAdapter(
            engine, db_path=str(settings.db_path)
        )
        self._engine = MigrationEngine(db_manager=self._adapter)
        self._enhanced = EnhancedMigrationEngine(engine=self._engine)
        self._migrations_dir = str(
            Path(__file__).resolve().parent / "migrations"
        )

    def scan_migrations(self):
        return self._engine.scan_migrations(self._migrations_dir)

    def get_current_version(self):
        return self._engine.get_current_version("module_db_name")

    def migrate(self, **kwargs):
        migrations = self.scan_migrations()
        return self._enhanced.migrate_enhanced(
            db_name="module_db_name",
            migrations=migrations,
            **kwargs,
        )

    # ... rollback, status, history, check 等方法
```

#### 步骤 4：在统一 CLI 中注册

在 `shared/data/data_layer/migrate.py` 的 `_auto_discover_modules()` 函数中添加模块配置。

### 7.2 已有数据库的模块

如果模块已有数据库（非迁移框架创建），接入时：

1. 编写 `v001_initial.py`，内容为现有表结构的 `CREATE TABLE IF NOT EXISTS` 语句
2. 首次执行迁移时，因表已存在，`IF NOT EXISTS` 会安全跳过
3. 迁移框架会记录版本号，但不修改数据
4. 后续新增变更使用递增版本号

---

## 8. 最佳实践

### 8.1 迁移前检查清单

- [ ] 已在测试环境验证迁移脚本
- [ ] 已备份生产数据库
- [ ] 已评估迁移耗时（大表需特别注意）
- [ ] 已准备回滚方案
- [ ] 已确认迁移期间的业务影响

### 8.2 发布流程

1. **开发阶段**：本地编写迁移脚本，通过单元测试
2. **预览阶段**：在测试环境执行 `--dry-run`，确认变更内容
3. **测试阶段**：在测试环境执行实际迁移，验证功能
4. **备份阶段**：生产环境迁移前执行全量备份
5. **执行阶段**：在生产环境执行迁移，监控进度
6. **验证阶段**：迁移完成后进行数据完整性校验和功能验证
7. **回滚预案**：出现问题时，按预案回滚

### 8.3 数据安全原则

1. **永远备份**：迁移前自动备份是默认行为，不要轻易禁用
2. **Dry-run 优先**：生产环境先 dry-run 预览，确认后再执行
3. **小步快跑**：每次迁移变更尽量小，降低风险
4. **可回滚**：每个迁移都必须有回滚脚本
5. **幂等性**：迁移脚本必须可重复执行
6. **向后兼容**：数据库变更不能破坏现有代码

### 8.4 性能建议

- 大表加索引使用 `CREATE INDEX IF NOT EXISTS`
- 大批量数据更新分批执行（每批 1000-5000 条）
- 避免在业务高峰期执行迁移
- 迁移前估算锁表时间，评估业务影响

### 8.5 代码审查

迁移脚本必须经过代码审查，重点关注：

- 是否有数据丢失风险
- 是否有性能问题
- 是否遵循命名规范
- 回滚逻辑是否正确
- 是否有完善的注释

---

## 9. 故障排查

### 9.1 迁移失败

**现象**：迁移过程中报错，状态为 failed

**排查步骤**：
1. 查看错误信息，定位失败的版本
2. 检查是否有锁表或并发冲突
3. 检查数据库磁盘空间
4. 从备份恢复后重新执行

**恢复步骤**：
1. 不要手动修改 `schema_migrations` 表
2. 优先使用备份恢复
3. 修复脚本问题后重新执行

### 9.2 校验和不匹配

**现象**：`verify_checksums` 报告校验和不一致

**原因**：已应用的迁移脚本被修改

**处理**：
1. 确认是否为预期内的修改
2. 如果是 bugfix，应新增迁移版本，不要修改已发布的脚本
3. 特殊情况需要修改的，记录变更原因并重新计算校验和

### 9.3 回滚失败

**现象**：rollback 命令报错

**常见原因**：
- 回滚脚本有 bug
- 依赖的数据已被删除
- 外部约束导致无法删除表

**处理**：
1. 检查回滚脚本逻辑
2. 手动处理依赖关系
3. 从备份恢复是最终手段

### 9.4 获取帮助

如遇无法解决的迁移问题，请：
1. 收集完整的错误日志
2. 记录当前版本和目标版本
3. 准备数据库备份
4. 联系架构组协助排查

---

## 附录

### A. 文件结构参考

```
shared/data/
├── data_layer/
│   ├── migration.py              # 基础迁移引擎
│   ├── migration_enhanced.py     # 增强型迁移引擎
│   ├── migration_tools.py        # 迁移工具集
│   ├── postgres_adapter.py       # PostgreSQL 适配器
│   ├── migrate.py                # 统一 CLI 工具
│   ├── backup_manager.py         # 备份管理器
│   ├── database_manager.py       # 数据库管理器
│   └── __init__.py
├── data_governance/
│   ├── data_sovereignty.json     # 数据主权清单
│   ├── sovereignty.py            # 主权查询工具
│   └── __init__.py
└── MIGRATION_GUIDE.md            # 本文档
```

### B. 相关文档

- 数据治理框架文档
- 备份与恢复指南
- 数据主权清单

---

*文档版本：v1.0*
*最后更新：2026-07*
