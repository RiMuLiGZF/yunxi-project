"""
数据库迁移测试

运行: python -m pytest tests/test_db_migration.py -v
"""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import sqlite3

import pytest

from tide_memory.db.migration import DatabaseMigrator, Migration


class TestDatabaseMigratorInit:
    """DatabaseMigrator 初始化测试"""

    def test_init_with_db_path(self, tmp_path):
        """指定 db_path 初始化"""
        db_path = str(tmp_path / "test.db")
        migrator = DatabaseMigrator(db_path)
        assert migrator.db_path == db_path
        assert migrator.latest_version == 0

    def test_init_with_migrations(self, tmp_path):
        """初始化时预注册迁移"""
        db_path = str(tmp_path / "test.db")
        migrations = [
            Migration(version=1, name="first", up_sql=["SELECT 1"]),
            Migration(version=2, name="second", up_sql=["SELECT 2"]),
        ]
        migrator = DatabaseMigrator(db_path, migrations=migrations)
        assert migrator.latest_version == 2

    def test_latest_version_no_migrations(self, tmp_path):
        """无迁移时 latest_version 为 0"""
        migrator = DatabaseMigrator(str(tmp_path / "test.db"))
        assert migrator.latest_version == 0


class TestMigrationRegistration:
    """版本注册和获取测试"""

    def test_register_migration(self, tmp_path):
        """注册单个迁移"""
        migrator = DatabaseMigrator(str(tmp_path / "test.db"))
        m = Migration(version=1, name="init", up_sql=["CREATE TABLE t1 (id INTEGER)"])
        migrator.register_migration(m)
        assert migrator.latest_version == 1

    def test_register_duplicate_version_raises(self, tmp_path):
        """重复版本号抛出 ValueError"""
        migrator = DatabaseMigrator(str(tmp_path / "test.db"))
        migrator.register_migration(Migration(version=1, name="first"))
        with pytest.raises(ValueError, match="already exists"):
            migrator.register_migration(Migration(version=1, name="duplicate"))

    def test_register_negative_version_raises(self, tmp_path):
        """非正数版本号抛出 ValueError"""
        migrator = DatabaseMigrator(str(tmp_path / "test.db"))
        with pytest.raises(ValueError, match="positive"):
            migrator.register_migration(Migration(version=0, name="zero"))

    def test_register_convenience_method(self, tmp_path):
        """便捷 register 方法正常工作"""
        migrator = DatabaseMigrator(str(tmp_path / "test.db"))
        migrator.register(
            version=3,
            name="add_column",
            up_sql=["ALTER TABLE t1 ADD COLUMN name TEXT"],
        )
        assert migrator.latest_version == 3
        assert migrator._migrations[3].name == "add_column"


class TestMigrationExecution:
    """迁移执行（up_sql）测试"""

    def test_migrate_creates_tables(self, tmp_path):
        """执行迁移创建表"""
        db_path = str(tmp_path / "test.db")
        migrator = DatabaseMigrator(db_path)
        migrator.register_migration(
            Migration(
                version=1,
                name="create_users",
                up_sql=[
                    "CREATE TABLE users (id INTEGER PRIMARY KEY, name TEXT NOT NULL)",
                ],
            )
        )

        result = migrator.migrate()

        assert result["status"] == "success"
        assert result["from_version"] == 0
        assert result["to_version"] == 1
        assert len(result["applied"]) == 1

        # 验证表确实被创建
        conn = sqlite3.connect(db_path)
        cursor = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='users'"
        )
        assert cursor.fetchone() is not None
        conn.close()

    def test_migrate_multiple_versions(self, tmp_path):
        """多版本迁移依次执行"""
        db_path = str(tmp_path / "test.db")
        migrator = DatabaseMigrator(db_path)
        migrator.register_migration(
            Migration(
                version=1,
                name="v1",
                up_sql=["CREATE TABLE t1 (id INTEGER PRIMARY KEY)"],
            )
        )
        migrator.register_migration(
            Migration(
                version=2,
                name="v2",
                up_sql=["CREATE TABLE t2 (id INTEGER PRIMARY KEY)"],
            )
        )

        result = migrator.migrate()

        assert result["to_version"] == 2
        assert len(result["applied"]) == 2

        conn = sqlite3.connect(db_path)
        tables = [
            row[0] for row in
            conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
        ]
        assert "t1" in tables
        assert "t2" in tables
        conn.close()

    def test_migrate_already_at_target(self, tmp_path):
        """已在目标版本时直接返回"""
        db_path = str(tmp_path / "test.db")
        migrator = DatabaseMigrator(db_path)
        migrator.register_migration(
            Migration(version=1, name="v1", up_sql=["SELECT 1"]),
        )
        migrator.migrate()  # 执行迁移到 v1

        # 再次执行，应该 already_at_target
        result = migrator.migrate()
        assert result["status"] == "already_at_target"
        assert len(result["applied"]) == 0

    def test_migrate_with_up_func(self, tmp_path):
        """使用 up_func 执行 Python 逻辑"""
        db_path = str(tmp_path / "test.db")

        def seed_data(conn: sqlite3.Connection):
            conn.execute("INSERT INTO config (key, value) VALUES (?, ?)", ("theme", "dark"))

        migrator = DatabaseMigrator(db_path)
        migrator.register_migration(
            Migration(
                version=1,
                name="init_config",
                up_sql=["CREATE TABLE config (key TEXT PRIMARY KEY, value TEXT)"],
                up_func=seed_data,
            )
        )
        migrator.migrate()

        conn = sqlite3.connect(db_path)
        row = conn.execute("SELECT value FROM config WHERE key='theme'").fetchone()
        assert row[0] == "dark"
        conn.close()


class TestMigrationHistory:
    """迁移历史查询测试"""

    def test_get_migration_history_after_migrate(self, tmp_path):
        """迁移后可查询到历史记录"""
        db_path = str(tmp_path / "test.db")
        migrator = DatabaseMigrator(db_path)
        migrator.register_migration(
            Migration(version=1, name="first_migration", up_sql=["SELECT 1"]),
        )
        migrator.migrate()

        history = migrator.get_migration_history()

        assert len(history) == 1
        assert history[0]["version"] == 1
        assert history[0]["name"] == "first_migration"
        assert "applied_at" in history[0]
        assert "duration_ms" in history[0]

    def test_get_migration_history_empty(self, tmp_path):
        """未执行迁移时历史为空"""
        migrator = DatabaseMigrator(str(tmp_path / "test.db"))
        history = migrator.get_migration_history()
        assert history == []

    def test_validate_after_migrate(self, tmp_path):
        """迁移后 validate 显示已最新"""
        db_path = str(tmp_path / "test.db")
        migrator = DatabaseMigrator(db_path)
        migrator.register_migration(
            Migration(version=1, name="v1", up_sql=["SELECT 1"]),
        )
        migrator.migrate()

        validation = migrator.validate()
        assert validation["is_up_to_date"] is True
        assert validation["needs_migration"] is False
        assert validation["current_version"] == 1

    def test_is_initialized(self, tmp_path):
        """is_initialized 在迁移前后返回不同"""
        db_path = str(tmp_path / "test.db")
        migrator = DatabaseMigrator(db_path)

        # 迁移前
        assert migrator.is_initialized() is False

        migrator.register_migration(
            Migration(version=1, name="v1", up_sql=["SELECT 1"]),
        )
        migrator.migrate()

        # 迁移后
        assert migrator.is_initialized() is True