"""
数据访问层增强功能测试套件
==========================

测试覆盖（增强功能）：
1. SQLAlchemyRepository CRUD 测试
2. SQLAlchemyRepository 分页查询测试
3. SQLAlchemyRepository 批量操作测试
4. 软删除 Mixin 测试
5. SQLAlchemyUnitOfWork 事务测试
6. DatabaseManager 连接管理测试
7. ModuleMigrationManager 迁移测试
8. M10 模块接入集成测试
9. M12 模块接入集成测试

所有测试使用内存 SQLite，不依赖外部数据库。
"""

from __future__ import annotations

import sys
import os
import time
from pathlib import Path

import pytest

# 添加项目根目录到 path
project_root = Path(__file__).parent.parent.parent.parent.parent
sys.path.insert(0, str(project_root))

# ============================================================
# 导入测试对象
# ============================================================

from sqlalchemy import Column, Integer, String, Float, Boolean, Text
from sqlalchemy.orm import declarative_base, Session, sessionmaker
from sqlalchemy import create_engine, text

from shared.data_access import (
    SQLAlchemyRepository,
    SQLAlchemyUnitOfWork,
    SoftDeleteMixin,
    PaginationResult,
    DatabaseManager,
    DatabaseConfig,
    DatabaseType,
    create_memory_manager,
    create_sqlite_manager,
    retry_on_db_error,
    Migration,
    MigrationContext,
    ModuleMigrationManager,
    SQLAlchemyMigrationHistoryStore,
)
from shared.data_access.migration import MigrationStatus

Base = declarative_base()


# ============================================================
# 测试用模型
# ============================================================

class TestUser(Base):
    """测试用户模型"""
    __tablename__ = "test_users"

    id = Column(Integer, primary_key=True, autoincrement=True)
    username = Column(String(50), unique=True, nullable=False)
    email = Column(String(200))
    age = Column(Integer)
    role = Column(String(20), default="viewer")
    status = Column(String(20), default="active")
    is_deleted = Column(Integer, default=0)
    created_at = Column(Float, default=time.time)
    updated_at = Column(Float, default=time.time)
    version = Column(Integer, default=1)


class TestProduct(Base):
    """测试商品模型"""
    __tablename__ = "test_products"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(200), nullable=False)
    category = Column(String(50), default="general")
    price = Column(Float, default=0.0)
    stock = Column(Integer, default=0)
    is_deleted = Column(Integer, default=0)


class TestOrder(Base):
    """测试订单模型"""
    __tablename__ = "test_orders"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, nullable=False)
    product_id = Column(Integer, nullable=False)
    quantity = Column(Integer, default=1)
    total_amount = Column(Float, default=0.0)
    status = Column(String(20), default="pending")


# ============================================================
# 测试用 Repository
# ============================================================

class TestUserRepository(SQLAlchemyRepository[TestUser]):
    model_class = TestUser


class TestProductRepository(SQLAlchemyRepository[TestProduct]):
    model_class = TestProduct


class TestOrderRepository(SQLAlchemyRepository[TestOrder]):
    model_class = TestOrder


class TestSoftDeleteUserRepository(SoftDeleteMixin, SQLAlchemyRepository[TestUser]):
    """带软删除的用户 Repository"""
    model_class = TestUser
    soft_delete_field = "is_deleted"
    deleted_at_field = None  # 不使用 deleted_at 时间字段


# ============================================================
# Fixture
# ============================================================

@pytest.fixture
def db_engine():
    """创建内存数据库引擎"""
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    yield engine
    engine.dispose()


@pytest.fixture
def db_session(db_engine):
    """创建数据库 session"""
    Session = sessionmaker(bind=db_engine)
    session = Session()
    yield session
    session.close()


@pytest.fixture
def user_repo(db_session):
    """用户 Repository"""
    return TestUserRepository(db_session)


@pytest.fixture
def product_repo(db_session):
    """商品 Repository"""
    return TestProductRepository(db_session)


@pytest.fixture
def order_repo(db_session):
    """订单 Repository"""
    return TestOrderRepository(db_session)


@pytest.fixture
def soft_delete_user_repo(db_session):
    """软删除用户 Repository"""
    return TestSoftDeleteUserRepository(db_session)


# ============================================================
# 一、SQLAlchemyRepository CRUD 测试
# ============================================================

class TestSQLAlchemyRepositoryCRUD:
    """SQLAlchemyRepository 基础 CRUD 测试"""

    def test_create_user(self, user_repo):
        """测试创建用户"""
        user = user_repo.create({"username": "alice", "email": "alice@test.com"})
        assert user.id is not None
        assert user.username == "alice"
        assert user.email == "alice@test.com"
        assert user.role == "viewer"  # 默认值
        assert user.status == "active"

    def test_get_by_id(self, user_repo):
        """测试按 ID 获取"""
        user = user_repo.create({"username": "bob", "email": "bob@test.com"})
        fetched = user_repo.get_by_id(user.id)
        assert fetched is not None
        assert fetched.id == user.id
        assert fetched.username == "bob"

    def test_get_by_id_not_found(self, user_repo):
        """测试获取不存在的记录"""
        result = user_repo.get_by_id(9999)
        assert result is None

    def test_update_user(self, user_repo):
        """测试更新用户"""
        user = user_repo.create({"username": "charlie", "email": "old@test.com"})
        updated = user_repo.update(user.id, {"email": "new@test.com", "role": "admin"})
        assert updated is not None
        assert updated.email == "new@test.com"
        assert updated.role == "admin"

    def test_update_not_found(self, user_repo):
        """测试更新不存在的记录"""
        result = user_repo.update(9999, {"email": "x@test.com"})
        assert result is None

    def test_delete_user(self, user_repo):
        """测试删除用户"""
        user = user_repo.create({"username": "dave"})
        assert user_repo.delete(user.id) is True
        assert user_repo.get_by_id(user.id) is None

    def test_delete_not_found(self, user_repo):
        """测试删除不存在的记录"""
        assert user_repo.delete(9999) is False

    def test_list_all(self, user_repo):
        """测试列出所有记录"""
        user_repo.create({"username": "user1"})
        user_repo.create({"username": "user2"})
        user_repo.create({"username": "user3"})

        all_users = user_repo.list_all()
        assert len(all_users) == 3

    def test_count(self, user_repo):
        """测试统计数量"""
        assert user_repo.count() == 0
        user_repo.create({"username": "a"})
        user_repo.create({"username": "b"})
        assert user_repo.count() == 2

    def test_exists(self, user_repo):
        """测试存在性检查"""
        user_repo.create({"username": "exists_test"})
        assert user_repo.exists(username="exists_test") is True
        assert user_repo.exists(username="nonexistent") is False

    def test_find_one(self, user_repo):
        """测试查找单条记录"""
        user_repo.create({"username": "find_one", "role": "admin"})
        user_repo.create({"username": "other", "role": "viewer"})

        found = user_repo.find_one(role="admin")
        assert found is not None
        assert found.username == "find_one"

    def test_find_many(self, user_repo):
        """测试查找多条记录"""
        user_repo.create({"username": "a1", "role": "admin"})
        user_repo.create({"username": "a2", "role": "admin"})
        user_repo.create({"username": "v1", "role": "viewer"})

        admins = user_repo.find_many(role="admin")
        assert len(admins) == 2

    def test_get_by_field(self, user_repo):
        """测试按字段查找"""
        user_repo.create({"username": "field_test", "email": "field@test.com"})
        found = user_repo.get_by_field("email", "field@test.com")
        assert found is not None
        assert found.username == "field_test"

    def test_filter_by(self, user_repo):
        """测试 filter_by 方法"""
        user_repo.create({"username": "f1", "status": "active"})
        user_repo.create({"username": "f2", "status": "inactive"})
        user_repo.create({"username": "f3", "status": "active"})

        active = user_repo.filter_by(status="active")
        assert len(active) == 2


# ============================================================
# 二、分页查询测试
# ============================================================

class TestSQLAlchemyRepositoryPagination:
    """SQLAlchemyRepository 分页查询测试"""

    def test_basic_pagination(self, user_repo):
        """测试基础分页"""
        for i in range(25):
            user_repo.create({"username": f"user{i}", "age": 20 + i})

        result = user_repo.paginate(page=1, page_size=10)
        assert isinstance(result, PaginationResult)
        assert result.total == 25
        assert result.page == 1
        assert result.page_size == 10
        assert result.total_pages == 3
        assert len(result.items) == 10

    def test_pagination_page_2(self, user_repo):
        """测试第二页"""
        for i in range(25):
            user_repo.create({"username": f"user{i:02d}", "age": 20 + i})

        result = user_repo.paginate(page=2, page_size=10, order_by="username")
        assert len(result.items) == 10
        assert result.items[0].username == "user10"

    def test_pagination_last_page(self, user_repo):
        """测试最后一页"""
        for i in range(25):
            user_repo.create({"username": f"user{i}"})

        result = user_repo.paginate(page=3, page_size=10)
        assert len(result.items) == 5  # 最后一页只有 5 条

    def test_pagination_with_filters(self, user_repo):
        """测试带过滤的分页"""
        for i in range(20):
            role = "admin" if i < 8 else "viewer"
            user_repo.create({"username": f"user{i}", "role": role})

        result = user_repo.paginate(page=1, page_size=5, role="admin")
        assert result.total == 8
        assert len(result.items) == 5

    def test_pagination_with_order(self, user_repo):
        """测试带排序的分页"""
        for i in range(10):
            user_repo.create({"username": f"user{i:02d}", "age": 30 - i})

        result = user_repo.paginate(page=1, page_size=5, order_by="age", ascending=True)
        assert result.items[0].age == 21
        assert result.items[4].age == 25

    def test_pagination_empty(self, user_repo):
        """测试空分页"""
        result = user_repo.paginate(page=1, page_size=10)
        assert result.total == 0
        assert len(result.items) == 0
        assert result.total_pages == 0

    def test_pagination_out_of_range(self, user_repo):
        """测试页码超出范围"""
        for i in range(5):
            user_repo.create({"username": f"user{i}"})

        result = user_repo.paginate(page=10, page_size=10)
        assert result.total == 5
        assert len(result.items) == 0


# ============================================================
# 三、批量操作测试
# ============================================================

class TestSQLAlchemyRepositoryBulk:
    """SQLAlchemyRepository 批量操作测试"""

    def test_bulk_create(self, user_repo):
        """测试批量创建"""
        users_data = [
            {"username": "bulk1", "email": "bulk1@test.com"},
            {"username": "bulk2", "email": "bulk2@test.com"},
            {"username": "bulk3", "email": "bulk3@test.com"},
        ]
        result = user_repo.bulk_create(users_data)
        assert len(result) == 3
        assert user_repo.count() == 3

    def test_bulk_create_empty(self, user_repo):
        """测试批量创建空列表"""
        result = user_repo.bulk_create([])
        assert len(result) == 0

    def test_bulk_update(self, user_repo):
        """测试批量更新"""
        u1 = user_repo.create({"username": "bu1", "role": "viewer"})
        u2 = user_repo.create({"username": "bu2", "role": "viewer"})
        u3 = user_repo.create({"username": "bu3", "role": "viewer"})

        count = user_repo.bulk_update([
            (u1.id, {"role": "admin"}),
            (u2.id, {"role": "editor"}),
        ])
        assert count == 2

        assert user_repo.get_by_id(u1.id).role == "admin"
        assert user_repo.get_by_id(u2.id).role == "editor"
        assert user_repo.get_by_id(u3.id).role == "viewer"  # 未更新

    def test_bulk_delete(self, user_repo):
        """测试批量删除"""
        u1 = user_repo.create({"username": "bd1"})
        u2 = user_repo.create({"username": "bd2"})
        u3 = user_repo.create({"username": "bd3"})

        count = user_repo.bulk_delete([u1.id, u2.id])
        assert count == 2
        assert user_repo.count() == 1
        assert user_repo.get_by_id(u3.id) is not None

    def test_bulk_delete_empty(self, user_repo):
        """测试批量删除空列表"""
        count = user_repo.bulk_delete([])
        assert count == 0


# ============================================================
# 四、软删除 Mixin 测试
# ============================================================

class TestSoftDeleteMixin:
    """软删除 Mixin 测试"""

    def test_soft_delete(self, soft_delete_user_repo):
        """测试软删除"""
        user = soft_delete_user_repo.create({"username": "sd_test", "is_deleted": 0})
        assert soft_delete_user_repo.delete(user.id) is True

        # 软删除后记录仍存在，但 is_deleted = 1
        fetched = soft_delete_user_repo.get_by_id(user.id)
        assert fetched is not None
        assert fetched.is_deleted == 1

    def test_hard_delete(self, soft_delete_user_repo):
        """测试硬删除"""
        user = soft_delete_user_repo.create({"username": "hd_test"})
        assert soft_delete_user_repo.hard_delete(user.id) is True
        assert soft_delete_user_repo.get_by_id(user.id) is None

    def test_restore(self, soft_delete_user_repo):
        """测试恢复软删除的记录"""
        user = soft_delete_user_repo.create({"username": "restore_test"})
        soft_delete_user_repo.soft_delete(user.id)

        # 确认已删除
        assert soft_delete_user_repo.get_by_id(user.id).is_deleted == 1

        # 恢复
        assert soft_delete_user_repo.restore(user.id) is True
        assert soft_delete_user_repo.get_by_id(user.id).is_deleted == 0

    def test_soft_delete_default(self, soft_delete_user_repo):
        """测试默认 delete 是软删除"""
        user = soft_delete_user_repo.create({"username": "default_sd"})
        soft_delete_user_repo.delete(user.id)

        # 记录还在
        assert soft_delete_user_repo.get_by_id(user.id) is not None
        assert soft_delete_user_repo.get_by_id(user.id).is_deleted == 1


# ============================================================
# 五、SQLAlchemyUnitOfWork 事务测试
# ============================================================

class TestSQLAlchemyUnitOfWork:
    """SQLAlchemyUnitOfWork 事务测试"""

    def test_commit(self, db_engine):
        """测试事务提交"""
        SessionLocal = sessionmaker(bind=db_engine)

        uow = SQLAlchemyUnitOfWork(SessionLocal)
        with uow as session:
            repo = TestUserRepository(session)
            repo.create({"username": "uow_commit"})

        # 提交后数据应存在
        verify_session = SessionLocal()
        repo2 = TestUserRepository(verify_session)
        assert repo2.count() == 1
        verify_session.close()

    def test_rollback_on_exception(self, db_engine):
        """测试异常时自动回滚"""
        SessionLocal = sessionmaker(bind=db_engine)

        try:
            uow = SQLAlchemyUnitOfWork(SessionLocal)
            with uow as session:
                repo = TestUserRepository(session)
                repo.create({"username": "uow_rollback"})
                raise ValueError("test error")
        except ValueError:
            pass

        # 回滚后数据不应存在
        verify_session = SessionLocal()
        repo2 = TestUserRepository(verify_session)
        assert repo2.count() == 0
        verify_session.close()

    def test_nested_operations(self, db_engine):
        """测试同一事务内多个 Repository 操作"""
        SessionLocal = sessionmaker(bind=db_engine)

        uow = SQLAlchemyUnitOfWork(SessionLocal)
        with uow as session:
            user_repo = TestUserRepository(session)
            product_repo = TestProductRepository(session)
            order_repo = TestOrderRepository(session)

            user = user_repo.create({"username": "order_user"})
            product = product_repo.create({"name": "Test Product", "price": 99.99})
            order_repo.create({
                "user_id": user.id,
                "product_id": product.id,
                "quantity": 2,
                "total_amount": 199.98,
            })

        # 验证所有数据都已提交
        verify = SessionLocal()
        assert TestUserRepository(verify).count() == 1
        assert TestProductRepository(verify).count() == 1
        assert TestOrderRepository(verify).count() == 1
        verify.close()

    def test_get_repository_reuse(self, db_engine):
        """测试 Repository 实例复用"""
        SessionLocal = sessionmaker(bind=db_engine)

        uow = SQLAlchemyUnitOfWork(SessionLocal)
        uow.begin()
        try:
            repo1 = uow.get_repository(TestUserRepository)
            repo2 = uow.get_repository(TestUserRepository)
            assert repo1 is repo2  # 同一 UoW 内应复用
        finally:
            uow.rollback()


# ============================================================
# 六、DatabaseManager 连接管理测试
# ============================================================

class TestDatabaseManager:
    """DatabaseManager 连接管理测试"""

    def test_create_memory_manager(self):
        """测试创建内存数据库管理器"""
        db = create_memory_manager()
        assert db is not None
        assert isinstance(db, DatabaseManager)

    def test_create_sqlite_manager(self, tmp_path):
        """测试创建 SQLite 数据库管理器"""
        db_path = str(tmp_path / "test.db")
        db = create_sqlite_manager(db_path=db_path)
        db.init_db(Base)

        assert Path(db_path).exists()
        db.dispose()

    def test_health_check(self):
        """测试健康检查"""
        db = create_memory_manager()
        db.init_db(Base)

        health = db.health_check()
        assert health["status"] == "healthy"
        assert health["response_time_ms"] >= 0
        assert health["db_type"] == "sqlite"

    def test_get_session_context_manager(self):
        """测试 get_session 上下文管理器"""
        db = create_memory_manager()
        db.init_db(Base)

        with db.get_session() as session:
            repo = TestUserRepository(session)
            repo.create({"username": "session_test"})
            assert repo.count() == 1

    def test_list_tables(self):
        """测试列出所有表"""
        db = create_memory_manager()
        db.init_db(Base)

        tables = db.list_tables()
        assert "test_users" in tables
        assert "test_products" in tables
        assert "test_orders" in tables

    def test_table_exists(self):
        """测试检查表是否存在"""
        db = create_memory_manager()
        db.init_db(Base)

        assert db.table_exists("test_users") is True
        assert db.table_exists("nonexistent") is False

    def test_database_config_url(self):
        """测试数据库配置 URL 生成"""
        config = DatabaseConfig(
            db_type=DatabaseType.SQLITE,
            db_path="/tmp/test.db",
        )
        url = config.get_database_url()
        assert url == "sqlite:////tmp/test.db"

    def test_retry_decorator(self, db_engine):
        """测试重试装饰器"""
        call_count = 0

        @retry_on_db_error(max_retries=2, retry_delay=0.01)
        def flaky_operation(session):
            nonlocal call_count
            call_count += 1
            if call_count < 2:
                from sqlalchemy.exc import OperationalError
                raise OperationalError("test", params=None, orig=Exception("test"))
            return "success"

        SessionLocal = sessionmaker(bind=db_engine)
        session = SessionLocal()
        result = flaky_operation(session)
        assert result == "success"
        assert call_count == 2
        session.close()


# ============================================================
# 七、ModuleMigrationManager 迁移测试
# ============================================================

class TestModuleMigrationManager:
    """ModuleMigrationManager 迁移管理测试"""

    def test_create_manager(self, db_engine):
        """测试创建迁移管理器"""
        mgr = ModuleMigrationManager(
            engine=db_engine,
            db_name="test_db",
        )
        assert mgr is not None
        assert mgr.db_name == "test_db"

    def test_get_initial_version(self, db_engine):
        """测试初始版本号为 None"""
        mgr = ModuleMigrationManager(engine=db_engine, db_name="test")
        assert mgr.get_current_version() is None

    def test_register_and_upgrade(self, db_engine):
        """测试注册迁移并升级"""

        class V1Migration(Migration):
            version = "001"
            description = "Test migration v1"

            def up(self, ctx: MigrationContext) -> bool:
                ctx.extra["v1_applied"] = True
                return True

            def down(self, ctx: MigrationContext) -> bool:
                ctx.extra["v1_applied"] = False
                return True

        mgr = ModuleMigrationManager(engine=db_engine, db_name="test")
        mgr.manager.register(V1Migration)

        result = mgr.migrate()
        assert result["success"] is True
        assert result["applied_count"] == 1
        assert mgr.get_current_version() == "001"

    def test_multiple_migrations(self, db_engine):
        """测试多个迁移按顺序执行"""

        class V1(Migration):
            version = "001"
            description = "v1"
            def up(self, ctx): ctx.extra["order"] = ctx.extra.get("order", []) + [1]; return True
            def down(self, ctx): return True

        class V2(Migration):
            version = "002"
            description = "v2"
            def up(self, ctx): ctx.extra["order"] = ctx.extra.get("order", []) + [2]; return True
            def down(self, ctx): return True

        class V3(Migration):
            version = "003"
            description = "v3"
            def up(self, ctx): ctx.extra["order"] = ctx.extra.get("order", []) + [3]; return True
            def down(self, ctx): return True

        mgr = ModuleMigrationManager(engine=db_engine, db_name="test")
        mgr.manager.register(V1)
        mgr.manager.register(V2)
        mgr.manager.register(V3)

        result = mgr.migrate()
        assert result["success"] is True
        assert result["applied_count"] == 3
        assert mgr.get_current_version() == "003"
        assert mgr.manager._ctx.extra["order"] == [1, 2, 3]

    def test_rollback(self, db_engine):
        """测试回滚"""

        class V1(Migration):
            version = "001"
            description = "v1"
            def up(self, ctx): return True
            def down(self, ctx): ctx.extra["v1_rolled_back"] = True; return True

        mgr = ModuleMigrationManager(engine=db_engine, db_name="test")
        mgr.manager.register(V1)
        mgr.migrate()

        result = mgr.rollback(target_version="0")
        assert result["success"] is True
        assert result["rolled_back_count"] == 1
        assert mgr.get_current_version() is None

    def test_get_status(self, db_engine):
        """测试获取状态"""

        class V1(Migration):
            version = "001"
            description = "v1"
            def up(self, ctx): return True
            def down(self, ctx): return True

        mgr = ModuleMigrationManager(engine=db_engine, db_name="test")
        mgr.manager.register(V1)

        status = mgr.get_status()
        assert status["total_migrations"] == 1
        assert status["pending_count"] == 1
        assert status["is_up_to_date"] is False

        mgr.migrate()
        status = mgr.get_status()
        assert status["applied_count"] == 1
        assert status["is_up_to_date"] is True

    def test_sqlalchemy_history_store(self, db_engine):
        """测试 SQLAlchemy 迁移历史存储"""
        store = SQLAlchemyMigrationHistoryStore(db_engine)
        store.initialize()

        # 表应该已创建
        from sqlalchemy import inspect
        inspector = inspect(db_engine)
        tables = inspector.get_table_names()
        assert "_yunxi_migration_history" in tables


# ============================================================
# 八、M10 模块接入集成测试
# ============================================================

class TestM10Integration:
    """M10 模块接入标准数据层集成测试"""

    @pytest.fixture
    def m10_db(self, db_engine):
        """初始化 M10 测试数据库"""
        # 动态创建 M10 模型的表（使用独立的 Base 避免冲突）
        from sqlalchemy.orm import declarative_base as new_base
        from sqlalchemy import Column, Integer, String, Float, Boolean, Text, Index
        import json

        M10Base = new_base()

        class TestAuditLogDB(M10Base):
            __tablename__ = "m10_audit_logs"
            id = Column(Integer, primary_key=True, autoincrement=True)
            log_id = Column(String(32), unique=True, index=True)
            timestamp = Column(Float, index=True, default=time.time)
            level = Column(String(20), index=True)
            log_type = Column(String(100), index=True)
            trigger_condition = Column(String(500))
            action = Column(String(500))
            result = Column(String(500))
            details_json = Column(Text, default="{}")

        class TestGuardPolicyDB(M10Base):
            __tablename__ = "m10_guard_policies"
            id = Column(Integer, primary_key=True, autoincrement=True)
            metric_type = Column(String(50), unique=True, index=True)
            info_threshold = Column(Float)
            warning_threshold = Column(Float)
            critical_threshold = Column(Float)
            emergency_threshold = Column(Float)
            enabled = Column(Boolean, default=True)
            updated_at = Column(Float, default=time.time)

        M10Base.metadata.create_all(bind=db_engine)

        class AuditRepo(SQLAlchemyRepository):
            model_class = TestAuditLogDB

        class PolicyRepo(SQLAlchemyRepository):
            model_class = TestGuardPolicyDB

        return {
            "engine": db_engine,
            "AuditRepo": AuditRepo,
            "PolicyRepo": PolicyRepo,
            "AuditModel": TestAuditLogDB,
            "PolicyModel": TestGuardPolicyDB,
        }

    def test_audit_log_crud(self, m10_db):
        """测试审计日志 CRUD（M10 接入验证）"""
        SessionLocal = sessionmaker(bind=m10_db["engine"])
        session = SessionLocal()
        repo = m10_db["AuditRepo"](session)

        # 创建
        log = repo.create({
            "log_id": "audit_001",
            "level": "info",
            "log_type": "login",
            "trigger_condition": "user_login",
            "action": "allow",
            "result": "success",
        })
        assert log.id is not None
        assert log.log_id == "audit_001"

        # 查询
        fetched = repo.get_by_id(log.id)
        assert fetched is not None
        assert fetched.log_type == "login"

        # 更新
        updated = repo.update(log.id, {"level": "warning"})
        assert updated.level == "warning"

        # 删除
        assert repo.delete(log.id) is True
        assert repo.get_by_id(log.id) is None

        session.close()

    def test_policy_upsert(self, m10_db):
        """测试策略 upsert（M10 业务方法验证）"""
        SessionLocal = sessionmaker(bind=m10_db["engine"])
        session = SessionLocal()
        repo = m10_db["PolicyRepo"](session)

        # 初始插入
        policy = repo.create({
            "metric_type": "cpu",
            "info_threshold": 60.0,
            "warning_threshold": 75.0,
            "critical_threshold": 85.0,
            "emergency_threshold": 95.0,
        })
        assert policy.id is not None

        # 查询
        found = repo.find_one(metric_type="cpu")
        assert found is not None
        assert found.info_threshold == 60.0

        # 更新
        updated = repo.update(found.id, {"warning_threshold": 80.0})
        assert updated.warning_threshold == 80.0

        session.close()

    def test_audit_log_pagination(self, m10_db):
        """测试审计日志分页（M10 接入验证）"""
        SessionLocal = sessionmaker(bind=m10_db["engine"])
        session = SessionLocal()
        repo = m10_db["AuditRepo"](session)

        for i in range(15):
            repo.create({
                "log_id": f"log_{i:03d}",
                "level": "info" if i % 2 == 0 else "warning",
                "log_type": "type_a" if i < 10 else "type_b",
                "trigger_condition": "test",
                "action": "test",
                "result": "success",
            })

        # 全量分页
        result = repo.paginate(page=1, page_size=5, order_by="log_id")
        assert result.total == 15
        assert len(result.items) == 5

        # 按级别过滤分页
        result = repo.paginate(page=1, page_size=10, level="warning")
        assert result.total == 7  # 1,3,5,7,9,11,13

        session.close()

    def test_m10_unit_of_work(self, m10_db):
        """测试 M10 事务（UnitOfWork 接入验证）"""
        SessionLocal = sessionmaker(bind=m10_db["engine"])

        uow = SQLAlchemyUnitOfWork(SessionLocal)
        with uow as session:
            audit_repo = m10_db["AuditRepo"](session)
            policy_repo = m10_db["PolicyRepo"](session)

            audit_repo.create({
                "log_id": "tx_log_001",
                "level": "info",
                "log_type": "test",
                "trigger_condition": "tx_test",
                "action": "test",
                "result": "success",
            })
            policy_repo.create({
                "metric_type": "memory",
                "info_threshold": 60.0,
                "warning_threshold": 75.0,
                "critical_threshold": 85.0,
                "emergency_threshold": 95.0,
            })

        # 验证都已提交
        verify = SessionLocal()
        assert m10_db["AuditRepo"](verify).count() == 1
        assert m10_db["PolicyRepo"](verify).count() == 1
        verify.close()

    def test_m10_bulk_create(self, m10_db):
        """测试 M10 批量创建（M10 接入验证）"""
        SessionLocal = sessionmaker(bind=m10_db["engine"])
        session = SessionLocal()
        repo = m10_db["AuditRepo"](session)

        logs = [
            {"log_id": f"bulk_{i}", "level": "info", "log_type": "bulk_test",
             "trigger_condition": "test", "action": "test", "result": "ok"}
            for i in range(10)
        ]
        result = repo.bulk_create(logs)
        assert len(result) == 10
        assert repo.count() == 10

        session.close()


# ============================================================
# 九、M12 模块接入集成测试
# ============================================================

class TestM12Integration:
    """M12 模块接入标准数据层集成测试"""

    @pytest.fixture
    def m12_db(self, db_engine):
        """初始化 M12 测试数据库"""
        from sqlalchemy.orm import declarative_base as new_base
        from sqlalchemy import Column, Integer, String, Float, Boolean, Text, DateTime, JSON, Index
        from datetime import datetime, timezone

        M12Base = new_base()

        def _utc_now():
            return datetime.now(timezone.utc)

        class TestSecurityEventDB(M12Base):
            __tablename__ = "m12_security_events"
            id = Column(Integer, primary_key=True)
            event_type = Column(String(100), default="")
            severity = Column(String(20), default="info")
            source_ip = Column(String(50), default="")
            status = Column(String(20), default="active")
            description = Column(Text, default="")
            created_at = Column(DateTime, default=_utc_now)

        class TestApiKeyDB(M12Base):
            __tablename__ = "m12_api_keys"
            id = Column(Integer, primary_key=True)
            key_name = Column(String(200), default="")
            key_hash = Column(String(255), unique=True)
            owner = Column(String(200), default="")
            is_active = Column(Boolean, default=True)
            call_count = Column(Integer, default=0)
            created_at = Column(DateTime, default=_utc_now)

        class TestIpBlacklistDB(M12Base):
            __tablename__ = "m12_ip_blacklist"
            id = Column(Integer, primary_key=True)
            ip_address = Column(String(50), unique=True)
            reason = Column(Text, default="")
            severity = Column(String(20), default="medium")
            is_active = Column(Boolean, default=True)
            hit_count = Column(Integer, default=0)
            banned_at = Column(DateTime, default=_utc_now)

        M12Base.metadata.create_all(bind=db_engine)

        class EventRepo(SQLAlchemyRepository):
            model_class = TestSecurityEventDB

        class KeyRepo(SQLAlchemyRepository):
            model_class = TestApiKeyDB

        class IpRepo(SQLAlchemyRepository):
            model_class = TestIpBlacklistDB

        return {
            "engine": db_engine,
            "EventRepo": EventRepo,
            "KeyRepo": KeyRepo,
            "IpRepo": IpRepo,
        }

    def test_security_event_crud(self, m12_db):
        """测试安全事件 CRUD（M12 接入验证）"""
        SessionLocal = sessionmaker(bind=m12_db["engine"])
        session = SessionLocal()
        repo = m12_db["EventRepo"](session)

        event = repo.create({
            "event_type": "waf_block",
            "severity": "high",
            "source_ip": "192.168.1.100",
            "description": "SQL injection attempt",
        })
        assert event.id is not None
        assert event.event_type == "waf_block"

        fetched = repo.get_by_id(event.id)
        assert fetched.severity == "high"

        updated = repo.update(event.id, {"status": "resolved"})
        assert updated.status == "resolved"

        assert repo.delete(event.id) is True
        session.close()

    def test_api_key_operations(self, m12_db):
        """测试 API 密钥操作（M12 接入验证）"""
        SessionLocal = sessionmaker(bind=m12_db["engine"])
        session = SessionLocal()
        repo = m12_db["KeyRepo"](session)

        key = repo.create({
            "key_name": "test-key",
            "key_hash": "abc123hash",
            "owner": "test_user",
        })
        assert key.id is not None

        # 按哈希查找
        found = repo.get_by_field("key_hash", "abc123hash")
        assert found is not None
        assert found.key_name == "test-key"

        # 停用
        updated = repo.update(key.id, {"is_active": False})
        assert updated.is_active is False

        # 活跃密钥列表
        active = repo.filter_by(is_active=True)
        assert len(active) == 0

        session.close()

    def test_ip_blacklist_operations(self, m12_db):
        """测试 IP 黑名单操作（M12 接入验证）"""
        SessionLocal = sessionmaker(bind=m12_db["engine"])
        session = SessionLocal()
        repo = m12_db["IpRepo"](session)

        # 封禁 IP
        record = repo.create({
            "ip_address": "10.0.0.1",
            "reason": "Brute force attack",
            "severity": "high",
        })
        assert record.id is not None

        # 检查是否被封禁
        found = repo.find_one(ip_address="10.0.0.1", is_active=True)
        assert found is not None

        # 解封
        updated = repo.update(record.id, {"is_active": False})
        assert updated.is_active is False

        session.close()

    def test_m12_pagination(self, m12_db):
        """测试 M12 分页查询（M12 接入验证）"""
        SessionLocal = sessionmaker(bind=m12_db["engine"])
        session = SessionLocal()
        repo = m12_db["EventRepo"](session)

        for i in range(20):
            repo.create({
                "event_type": "type_a" if i % 2 == 0 else "type_b",
                "severity": "high" if i < 5 else "medium",
                "source_ip": f"10.0.0.{i}",
            })

        result = repo.paginate(page=1, page_size=10, event_type="type_a")
        assert result.total == 10
        assert len(result.items) == 10

        result = repo.paginate(page=1, page_size=20, severity="high")
        assert result.total == 5

        session.close()

    def test_m12_unit_of_work(self, m12_db):
        """测试 M12 事务管理（M12 接入验证）"""
        SessionLocal = sessionmaker(bind=m12_db["engine"])

        uow = SQLAlchemyUnitOfWork(SessionLocal)
        with uow as session:
            event_repo = m12_db["EventRepo"](session)
            ip_repo = m12_db["IpRepo"](session)

            # 创建安全事件
            event_repo.create({
                "event_type": "ip_ban",
                "severity": "critical",
                "source_ip": "203.0.113.1",
                "description": "Automated ban",
            })
            # 同时封禁 IP
            ip_repo.create({
                "ip_address": "203.0.113.1",
                "reason": "Auto-ban from security event",
                "severity": "critical",
            })

        verify = SessionLocal()
        assert m12_db["EventRepo"](verify).count() == 1
        assert m12_db["IpRepo"](verify).count() == 1
        verify.close()


# ============================================================
# 主入口
# ============================================================

if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
