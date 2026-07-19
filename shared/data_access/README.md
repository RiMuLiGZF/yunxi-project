# 云汐统一数据访问层（Data Access Layer）

> 云汐项目统一数据访问标准，打通各模块数据孤岛，提供可复用的 Repository、UnitOfWork、迁移管理和连接管理抽象。

## 目录

- [快速开始](#快速开始)
- [核心组件](#核心组件)
- [BaseRepository 使用](#baserepository-使用)
- [SQLAlchemyRepository 使用](#sqlalchemyrepository-使用)
- [UnitOfWork 使用](#unitofwork-使用)
- [软删除 Mixin](#软删除-mixin)
- [迁移管理](#迁移管理)
- [数据库连接管理](#数据库连接管理)
- [从自建实现迁移](#从自建实现迁移)
- [最佳实践](#最佳实践)

---

## 快速开始

### 安装

本模块位于 `shared/data_access/`，直接导入即可使用：

```python
from shared.data_access import (
    SQLAlchemyRepository,
    SQLAlchemyUnitOfWork,
    DatabaseManager,
    DatabaseConfig,
    DatabaseType,
    MigrationManager,
    ModuleMigrationManager,
)
```

### 依赖

- `SQLAlchemy >= 2.0`（SQLAlchemyRepository / 连接管理 / 迁移适配器必需）
- 无额外依赖（核心抽象层纯 Python 实现）

### 最简示例

```python
from sqlalchemy import Column, Integer, String
from sqlalchemy.orm import declarative_base
from shared.data_access import (
    SQLAlchemyRepository,
    create_sqlite_manager,
)

Base = declarative_base()

class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True)
    username = Column(String(50), unique=True)
    email = Column(String(200))

class UserRepository(SQLAlchemyRepository):
    model_class = User

# 使用
db = create_sqlite_manager("data/app.db")
db.init_db(Base)

with db.get_session() as session:
    repo = UserRepository(session)
    user = repo.create({"username": "alice", "email": "alice@test.com"})
    found = repo.get_by_id(user.id)
    assert found.username == "alice"
```

---

## 核心组件

| 组件 | 文件 | 用途 |
|------|------|------|
| `BaseRepository` | `base.py` | 仓库基类抽象（后端无关） |
| `SQLAlchemyRepository` | `sqlalchemy_repo.py` | SQLAlchemy 2.0 仓库实现（**推荐使用**） |
| `SQLAlchemyUnitOfWork` | `sqlalchemy_repo.py` | SQLAlchemy 工作单元 |
| `UnitOfWork` | `base.py` | 工作单元抽象 |
| `SoftDeleteMixin` | `mixins.py` | 软删除 Mixin |
| `TimestampMixin` | `mixins.py` | 时间戳 Model Mixin |
| `DatabaseManager` | `connection.py` | 统一数据库连接管理 |
| `MigrationManager` | `migration.py` | 迁移管理器抽象 |
| `ModuleMigrationManager` | `sqlalchemy_migration.py` | SQLAlchemy 模块迁移管理器 |
| `ModelRegistry` | `registry.py` | 跨模块模型注册中心 |

---

## BaseRepository 使用

`BaseRepository` 是后端无关的仓库基类抽象，定义了标准 CRUD 接口。
对于使用 SQLAlchemy 的模块，建议直接使用 `SQLAlchemyRepository`。

### 标准 CRUD

```python
from shared.data_access import BaseRepository

class MyRepository(BaseRepository):
    _model_class = MyModel  # 自定义模型

    def _do_create(self, data): ...
    def _do_get_by_id(self, pk): ...
    def _do_update(self, pk, data): ...
    def _do_delete(self, pk): ...
    def _execute_query(self, filters, order_by, limit, offset): ...
    def _execute_paginated_query(self, filters, order_by, page, page_size): ...
    def _count_query(self, filters): ...
```

### 查询构造器

```python
# 链式查询
results = repo.query() \
    .filter(role="admin", status="active") \
    .filter(age__gt=18) \
    .order_by("created_at", ascending=False) \
    .all()

# 分页
page = repo.query() \
    .filter(role="admin") \
    .paginate(page=1, page_size=20)
# page.items, page.total, page.total_pages
```

### 支持的过滤操作符

| 操作符 | 说明 | 示例 |
|--------|------|------|
| `eq` | 等于 | `filter(name="test")` |
| `ne` | 不等于 | `filter(status__ne="deleted")` |
| `gt` | 大于 | `filter(age__gt=18)` |
| `gte` | 大于等于 | `filter(score__gte=60)` |
| `lt` | 小于 | `filter(count__lt=100)` |
| `lte` | 小于等于 | `filter(price__lte=99.9)` |
| `in` | 在列表中 | `query().add_filter("role", "in", ["admin", "editor"])` |
| `not_in` | 不在列表中 | `query().add_filter("role", "not_in", ["guest"])` |
| `like` | 模糊匹配 | `query().add_filter("name", "like", "test%")` |
| `contains` | 包含 | `filter(name__contains="abc")` |
| `between` | 范围 | `query().add_filter("age", "between", [18, 30])` |
| `is_null` | 为空 | `query().add_filter("email", "is_null")` |
| `is_not_null` | 不为空 | `query().add_filter("email", "is_not_null")` |

### 批量操作

```python
# 批量创建
users = repo.bulk_create([
    {"username": "alice"},
    {"username": "bob"},
    {"username": "charlie"},
])

# 批量更新
count = repo.bulk_update([
    (1, {"email": "new@test.com"}),
    (2, {"role": "admin"}),
])

# 批量删除
count = repo.bulk_delete([1, 2, 3])
```

---

## SQLAlchemyRepository 使用

**推荐使用**。基于 SQLAlchemy 2.0 的标准仓库实现，适用于所有使用 SQLAlchemy 的模块。

### 定义 Repository

```python
from shared.data_access import SQLAlchemyRepository
from my_models import UserModel

class UserRepository(SQLAlchemyRepository):
    """用户 Repository"""
    model_class = UserModel
```

只需设置 `model_class`，即可获得完整的 CRUD + 分页 + 查询 + 批量操作能力。

### 基础 CRUD

```python
from sqlalchemy.orm import Session

def create_user(session: Session, data: dict):
    repo = UserRepository(session)
    return repo.create(data)

def get_user(session: Session, user_id: int):
    repo = UserRepository(session)
    return repo.get_by_id(user_id)

def update_user(session: Session, user_id: int, data: dict):
    repo = UserRepository(session)
    return repo.update(user_id, data)

def delete_user(session: Session, user_id: int) -> bool:
    repo = UserRepository(session)
    return repo.delete(user_id)
```

### 分页查询

```python
# 便捷分页
result = repo.paginate(
    page=1,
    page_size=20,
    order_by="created_at",
    ascending=False,
    role="admin",
    status="active",
)

print(f"共 {result.total} 条，第 {result.page} 页")
for item in result.items:
    print(item.username)
```

### 自定义业务方法

```python
class UserRepository(SQLAlchemyRepository):
    model_class = UserModel

    def get_active_admins(self) -> list:
        """获取所有活跃的管理员"""
        return self.filter_by(role="admin", is_active=True)

    def find_by_email(self, email: str):
        """按邮箱查找"""
        return self.get_by_field("email", email)

    def activate_user(self, user_id: int) -> bool:
        """激活用户"""
        result = self.update(user_id, {"is_active": True})
        return result is not None
```

---

## UnitOfWork 使用

工作单元模式，确保一组数据库操作在同一事务中执行。

### SQLAlchemy UnitOfWork

```python
from shared.data_access import SQLAlchemyUnitOfWork

uow = SQLAlchemyUnitOfWork(SessionLocal)

with uow as session:
    user_repo = UserRepository(session)
    profile_repo = ProfileRepository(session)

    user = user_repo.create({"username": "alice"})
    profile_repo.create({"user_id": user.id, "bio": "Hello"})

# 正常退出：自动 commit
# 发生异常：自动 rollback
```

### 模块级 UnitOfWork（推荐）

为模块定义专属的 UnitOfWork，封装所有 Repository：

```python
from shared.data_access import SQLAlchemyRepository

class UserRepository(SQLAlchemyRepository):
    model_class = User

class ProfileRepository(SQLAlchemyRepository):
    model_class = Profile

class MyModuleUnitOfWork:
    def __init__(self, session_factory):
        self._session_factory = session_factory
        self._session = None
        self._users = None
        self._profiles = None

    def __enter__(self):
        self._session = self._session_factory()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if self._session is None:
            return False
        if exc_type:
            self._session.rollback()
        else:
            self._session.commit()
        self._session.close()
        return exc_type is None

    @property
    def users(self) -> UserRepository:
        if self._users is None:
            self._users = UserRepository(self._session)
        return self._users

    @property
    def profiles(self) -> ProfileRepository:
        if self._profiles is None:
            self._profiles = ProfileRepository(self._session)
        return self._profiles

# 使用
with MyModuleUnitOfWork(SessionLocal) as uow:
    user = uow.users.create({...})
    uow.profiles.create({...})
```

参考 M12 模块的 `M12UnitOfWork` 实现。

---

## 软删除 Mixin

为 Repository 添加软删除能力。

### Repository 级别

```python
from shared.data_access import SQLAlchemyRepository, SoftDeleteMixin

class UserRepository(SoftDeleteMixin, SQLAlchemyRepository):
    model_class = UserModel
    soft_delete_field = "is_deleted"
    deleted_at_field = "deleted_at"

# 使用
repo = UserRepository(session)
repo.delete(user_id)          # 软删除（设置 is_deleted=True）
repo.soft_delete(user_id)     # 显式软删除
repo.hard_delete(user_id)     # 硬删除（真正删除）
repo.restore(user_id)         # 恢复软删除的记录
```

### Model 级别

```python
from shared.data_access import SoftDeleteModelMixin, TimestampMixin, VersionMixin
from sqlalchemy.orm import declarative_base

Base = declarative_base()

class User(SoftDeleteModelMixin, TimestampMixin, VersionMixin, Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True)
    username = Column(String(50))
```

可用的 Model Mixin：

| Mixin | 字段 | 说明 |
|--------|------|------|
| `TimestampMixin` | `created_at`, `updated_at` | 自动时间戳 |
| `SoftDeleteModelMixin` | `is_deleted`, `deleted_at` | 软删除字段 |
| `VersionMixin` | `version` | 乐观锁版本号 |
| `AuditMixin` | `created_by`, `updated_by` + 时间戳 | 审计字段 |

---

## 迁移管理

### ModuleMigrationManager（推荐）

为使用 SQLAlchemy 的模块提供标准迁移管理，替代各模块自建实现。

```python
from shared.data_access import ModuleMigrationManager

mgr = ModuleMigrationManager(
    engine=sa_engine,
    db_name="m12_security_shield",
    migrations_dir="backend/migrations",
)

# 迁移到最新版本
result = mgr.migrate()
print(f"从 {result['from_version']} 迁移到 {result['to_version']}")

# 回滚
mgr.rollback(target_version="0")

# 查看状态
status = mgr.get_status()
print(status["is_up_to_date"])
print(status["pending_versions"])
```

### 迁移脚本规范

迁移脚本放在 `migrations/` 目录下，文件名格式：
`{version}_{description}.py`

示例：`migrations/001_initial.py`

```python
from shared.data_access import Migration, MigrationContext

class InitialMigration(Migration):
    version = "001"
    description = "初始化数据库表结构"

    def up(self, ctx: MigrationContext) -> bool:
        """升级"""
        engine = ctx.backend
        with engine.connect() as conn:
            conn.execute(text("""
                CREATE TABLE IF NOT EXISTS users (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    username TEXT UNIQUE NOT NULL,
                    email TEXT
                )
            """))
            conn.commit()
        return True

    def down(self, ctx: MigrationContext) -> bool:
        """回滚"""
        engine = ctx.backend
        with engine.connect() as conn:
            conn.execute(text("DROP TABLE IF EXISTS users"))
            conn.commit()
        return True
```

### 与自建迁移管理器的区别

| 特性 | 自建实现 | 标准 ModuleMigrationManager |
|------|----------|---------------------------|
| 接口统一 | 各模块不同 | 统一 API |
| 迁移历史存储 | 各自实现 | 标准 SQLAlchemy 表 |
| 版本管理 | 各模块不一致 | 统一版本号规则 |
| 错误处理 | 各模块自行实现 | 统一异常处理 + 审计 |
| CLI 工具 | 各自实现 | 可复用通用 CLI |

---

## 数据库连接管理

### DatabaseManager

统一的数据库连接管理，支持 SQLite 和 PostgreSQL。

```python
from shared.data_access import DatabaseManager, DatabaseConfig, DatabaseType

# SQLite
config = DatabaseConfig(
    db_type=DatabaseType.SQLITE,
    db_path="data/app.db",
    wal_mode=True,
    foreign_keys=True,
)
db = DatabaseManager(config)
db.init_db()  # 初始化，创建所有表

# 便捷创建
from shared.data_access import create_sqlite_manager, create_memory_manager

db = create_sqlite_manager("data/app.db")
test_db = create_memory_manager()  # 用于测试
```

### Session 管理

```python
# 上下文管理器（自动 commit/rollback/close）
with db.get_session() as session:
    user = session.query(User).first()
    # 正常退出自动 commit
    # 异常自动 rollback

# FastAPI 依赖注入
from fastapi import Depends

def get_current_user(session: Session = Depends(db.get_session_dependency)):
    ...
```

### 健康检查

```python
health = db.health_check()
# {
#     "status": "healthy",          # healthy / unhealthy
#     "response_time_ms": 2.34,     # 响应时间
#     "error": None,                # 错误信息
#     "db_type": "sqlite",
# }

# 带重试的连接检查
ok = db.check_connection(max_retries=3, retry_delay=1.0)
```

### 重试装饰器

```python
from shared.data_access import retry_on_db_error

@retry_on_db_error(max_retries=3, retry_delay=1.0)
def create_user(session, data):
    user = User(**data)
    session.add(user)
    session.commit()
    return user
```

---

## 从自建实现迁移

### 步骤 1：定义标准 Repository

```python
# 之前（自建）
class UserRepository:
    @staticmethod
    def get_by_id(db, user_id):
        return db.query(UserModel).filter(UserModel.id == user_id).first()

# 之后（标准）
from shared.data_access import SQLAlchemyRepository

class UserRepository(SQLAlchemyRepository):
    model_class = UserModel
```

### 步骤 2：替换静态方法为实例方法

```python
# 之前
UserRepository.get_by_id(db, user_id)

# 之后
repo = UserRepository(db)
repo.get_by_id(user_id)
```

### 步骤 3：使用标准分页替代手写分页

```python
# 之前
query = db.query(User).filter(User.role == "admin")
total = query.count()
items = query.offset((page-1)*page_size).limit(page_size).all()

# 之后
repo = UserRepository(session)
result = repo.paginate(page=page, page_size=page_size, role="admin")
# result.total, result.items
```

### 步骤 4：迁移迁移管理器

```python
# 之前
from .migration_manager import M12MigrationManager
mgr = M12MigrationManager()
mgr.migrate()

# 之后
from shared.data_access import ModuleMigrationManager
mgr = ModuleMigrationManager(
    engine=engine,
    db_name="m12_security_shield",
    migrations_dir="backend/migrations",
)
mgr.migrate()
```

### 迁移策略：渐进式

- **不强制一次性替换**：新旧实现可以共存
- **新功能用标准实现**：新增的 Repository 直接继承 SQLAlchemyRepository
- **旧功能逐步迁移**：有改动的地方顺便迁移到标准实现
- **保持向后兼容**：旧接口可以保留，内部委托给标准实现

---

## 最佳实践

### 1. Repository 分层

```
模块/
  models.py           # SQLAlchemy 模型定义
  repositories/       # Repository 层
    __init__.py
    user_repo.py      # UserRepository
    order_repo.py     # OrderRepository
  services/           # 业务逻辑层
  api/                # API 层
```

### 2. 一个 Model 对应一个 Repository

每个数据模型对应一个 Repository 类，Repository 名称为 `{ModelName}Repository`。

### 3. 业务方法放在 Repository 中

数据访问相关的业务逻辑（如统计、聚合查询）放在 Repository 中，而不是散落在各处。

### 4. 使用 UnitOfWork 管理事务

涉及多个 Repository 的操作，必须使用 UnitOfWork 确保事务一致性。

### 5. 软删除用于可恢复数据

- 用户数据、配置数据等需要保留审计痕迹的使用软删除
- 日志、临时数据等使用硬删除

### 6. 迁移脚本规范

- 版本号使用 3 位数字：`001`, `002`, `003`
- 每个迁移脚本必须实现 `up` 和 `down`
- 迁移脚本应幂等（重复执行不报错）
- 破坏性操作（DROP TABLE）必须谨慎

### 7. 连接管理

- 使用 `DatabaseManager` 统一管理连接
- 会话使用完后及时关闭
- 读操作可使用只读会话
- 写操作使用 UnitOfWork 确保事务

### 8. 测试

- 单元测试使用内存 SQLite
- Repository 测试覆盖 CRUD + 分页 + 业务方法
- UnitOfWork 测试验证事务提交/回滚

---

## 相关文件

| 文件 | 说明 |
|------|------|
| `base.py` | 核心抽象（BaseRepository/UnitOfWork/QueryBuilder） |
| `sqlalchemy_repo.py` | SQLAlchemy 标准 Repository 实现 |
| `sqlalchemy_migration.py` | SQLAlchemy 迁移适配器 |
| `mixins.py` | Mixin 集合（软删除/时间戳/版本号/审计） |
| `connection.py` | 数据库连接管理 |
| `migration.py` | 迁移框架抽象 |
| `registry.py` | 模型注册中心 |
| `backends/` | 多后端实现（SQLite/JSON/Memory） |
| `sync/` | 数据同步引擎 |
| `aggregation/` | 数据聚合服务 |
| `quality/` | 数据质量框架 |
