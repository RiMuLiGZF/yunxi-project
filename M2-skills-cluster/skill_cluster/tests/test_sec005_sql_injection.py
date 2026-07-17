# -*- coding: utf-8 -*-
"""
SEC-005 测试：M2 技能集群 SQL 注入防护

验证 SQL 注入防护功能：
1. order_by 白名单校验
2. 列名格式校验
3. 表名格式校验
4. select_columns 校验
5. conditions 列名校验
6. SQL 注入攻击向量测试
"""

import sys
import os
import pytest
import tempfile
import sqlite3

# 将 M2 项目根目录加入 path
_m2_root = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
)
sys.path.insert(0, _m2_root)


class TestSQLInjectionProtection:
    """SQL 注入防护测试"""

    def test_validate_identifier_valid_names(self):
        """测试合法标识符通过校验"""
        from skill_cluster.db.skill_repository_base import validate_identifier

        # 合法标识符
        assert validate_identifier("name") == "name"
        assert validate_identifier("created_at") == "created_at"
        assert validate_identifier("user_id") == "user_id"
        assert validate_identifier("_private") == "_private"
        assert validate_identifier("col123") == "col123"
        assert validate_identifier("a" * 100) == "a" * 100  # 长名称

    def test_validate_identifier_invalid_names(self):
        """测试非法标识符被拒绝"""
        from skill_cluster.db.skill_repository_base import validate_identifier

        # SQL 注入攻击向量
        invalid_names = [
            "name; DROP TABLE users--",       # 语句注入
            "name' OR '1'='1",                 # 单引号注入
            "1; DROP TABLE users",             # 数字开头 + 注入
            "name/**/WHERE/**/1=1",           # 注释注入
            "name WHERE 1=1",                  # 空格注入
            "name, password",                  # 多列注入
            "name FROM users--",               # FROM 注入
            "); DROP TABLE users;--",          # 括号注入
            "`name`",                           # 反引号
            '"name"',                           # 双引号
            "",                                  # 空字符串
            "123abc",                           # 数字开头
            "-name",                            # 连字符
            "na me",                            # 空格
        ]

        for name in invalid_names:
            with pytest.raises(ValueError, match="Invalid"):
                validate_identifier(name, "test column")

    def test_validate_order_by_valid(self):
        """测试合法的 ORDER BY 子句"""
        from skill_cluster.db.skill_repository_base import validate_order_by

        # 单例排序
        assert validate_order_by("created_at DESC") == "created_at DESC"
        assert validate_order_by("created_at ASC") == "created_at ASC"
        assert validate_order_by("name") == "name"
        assert validate_order_by("created_at desc") == "created_at desc"  # 不区分大小写

        # 多列排序
        assert validate_order_by("created_at DESC, name ASC") == "created_at DESC, name ASC"
        assert validate_order_by("rating_avg DESC, rating_count DESC") == "rating_avg DESC, rating_count DESC"

    def test_validate_order_by_invalid(self):
        """测试非法 ORDER BY 子句被拒绝"""
        from skill_cluster.db.skill_repository_base import validate_order_by

        invalid_order_bys = [
            "created_at; DROP TABLE users--",     # 语句注入
            "1=1--",                                # 布尔注入
            "(SELECT 1 FROM users WHERE 1=1)",      # 子查询注入
            "name; DELETE FROM packages--",        # 多语句
            "CASE WHEN 1=1 THEN name ELSE id END",  # CASE 注入
            "IF(1=1, name, id)",                    # IF 注入
            "name WHERE 1=1",                       # WHERE 注入
            "name UNION SELECT * FROM users--",     # UNION 注入
            "1, (SELECT password FROM users LIMIT 1)--",  # 子查询列
            "",                                       # 空
        ]

        for ob in invalid_order_bys:
            with pytest.raises(ValueError, match="Invalid"):
                validate_order_by(ob)

    def test_validate_order_by_whitelist(self):
        """测试 ORDER BY 白名单校验"""
        from skill_cluster.db.skill_repository_base import validate_order_by

        allowed = {"created_at", "name", "rating", "download_count"}

        # 白名单内的列应该通过
        assert validate_order_by("created_at DESC", allowed) == "created_at DESC"
        assert validate_order_by("name ASC", allowed) == "name ASC"

        # 白名单外的列应该被拒绝
        with pytest.raises(ValueError, match="not in allowed columns"):
            validate_order_by("password DESC", allowed)

        with pytest.raises(ValueError, match="not in allowed columns"):
            validate_order_by("secret_column ASC", allowed)

        # 多列中有一列不在白名单中也应该被拒绝
        with pytest.raises(ValueError, match="not in allowed columns"):
            validate_order_by("name ASC, password DESC", allowed)

    def test_validate_select_columns_valid(self):
        """测试合法的 SELECT 列名"""
        from skill_cluster.db.skill_repository_base import validate_select_columns

        # 单列
        assert validate_select_columns("*") == "*"
        assert validate_select_columns("name") == "name"
        assert validate_select_columns("id, name, created_at") == "id, name, created_at"

    def test_validate_select_columns_invalid(self):
        """测试非法的 SELECT 列名被拒绝"""
        from skill_cluster.db.skill_repository_base import validate_select_columns

        invalid = [
            "name; DROP TABLE users--",
            "name, (SELECT password FROM users LIMIT 1) as pwd",
            "1=1--",
            "* FROM users--",
            "name' , password",
        ]

        for cols in invalid:
            with pytest.raises(ValueError):
                validate_select_columns(cols)

    def test_validate_conditions_keys(self):
        """测试 conditions 列名校验"""
        from skill_cluster.db.skill_repository_base import validate_conditions_keys

        allowed = {"name", "status", "category"}

        # 合法条件
        valid_conditions = {"name": "test", "status": "active"}
        result = validate_conditions_keys(valid_conditions, allowed)
        assert result == valid_conditions

        # 空条件
        assert validate_conditions_keys({}, allowed) == {}
        assert validate_conditions_keys(None, allowed) is None

        # 非法列名
        with pytest.raises(ValueError, match="not in allowed columns"):
            validate_conditions_keys({"password": "hacked"}, allowed)

    def test_paginated_query_sql_injection_safety(self):
        """测试 paginated_query 的 SQL 注入防护"""
        from skill_cluster.db.skill_repository_base import (
            SkillBaseRepository,
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = os.path.join(tmpdir, "test.db")

            # 创建一个测试 Repository
            class TestRepo(SkillBaseRepository):
                table_name = "test_items"
                primary_key = "id"
                allowed_sort_columns = {"id", "name", "created_at"}
                allowed_columns = {"id", "name", "status", "created_at"}

                def __init__(self, db_path):
                    super().__init__(db_path)

                def _create_tables(self):
                    self._db.execute(
                        """
                        CREATE TABLE IF NOT EXISTS test_items (
                            id TEXT PRIMARY KEY,
                            name TEXT NOT NULL,
                            status TEXT DEFAULT 'active',
                            created_at TEXT
                        )
                        """
                    )

                def _create_indexes(self):
                    pass

                def _init_table(self):
                    # 插入测试数据
                    for i in range(5):
                        self._db.execute(
                            "INSERT INTO test_items (id, name, status, created_at) VALUES (?, ?, ?, ?)",
                            (f"id-{i}", f"item-{i}", "active", f"2025-01-{i+1:02d}"),
                        )

            repo = TestRepo(db_path)
            repo._init_table()

            # 正常查询
            rows, total = repo.paginated_query(
                conditions={"status": "active"},
                order_by="created_at DESC",
                page=1,
                page_size=10,
            )
            assert total == 5
            assert len(rows) == 5

            # 恶意 order_by 应该被拒绝
            with pytest.raises(ValueError):
                repo.paginated_query(order_by="name; DROP TABLE test_items--")

            # 恶意 conditions 列名应该被拒绝
            with pytest.raises(ValueError):
                repo.paginated_query(conditions={"password": "123"})

            # 恶意 select_columns 应该被拒绝
            with pytest.raises(ValueError):
                repo.paginated_query(select_columns="name, (SELECT 1) as hack")

            # 验证表还在（证明注入失败）
            result = repo._db.fetchone(
                "SELECT COUNT(*) FROM test_items"
            )
            assert result[0] == 5

            repo.close()

    def test_update_fields_sql_injection_safety(self):
        """测试 update_fields 的 SQL 注入防护"""
        from skill_cluster.db.skill_repository_base import SkillBaseRepository

        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = os.path.join(tmpdir, "test.db")

            class TestRepo(SkillBaseRepository):
                table_name = "test_items"
                primary_key = "id"
                allowed_columns = {"id", "name", "status"}

                def __init__(self, db_path):
                    super().__init__(db_path)
                    self._db.execute(
                        "INSERT INTO test_items (id, name, status) VALUES (?, ?, ?)",
                        ("test-id", "original", "active"),
                    )

                def _create_tables(self):
                    self._db.execute(
                        "CREATE TABLE IF NOT EXISTS test_items (id TEXT PRIMARY KEY, name TEXT, status TEXT)"
                    )

                def _create_indexes(self):
                    pass

            repo = TestRepo(db_path)

            # 正常更新
            count = repo.update_fields("test-id", {"name": "updated"})
            assert count == 1

            # 恶意字段名应该被拒绝
            with pytest.raises(ValueError):
                repo.update_fields("test-id", {"name = 'hacked' WHERE 1=1--": "x"})

            with pytest.raises(ValueError):
                repo.update_fields("test-id", {"password": "hacked"})

            repo.close()

    def test_like_search_sql_injection_safety(self):
        """测试 like_search 的 SQL 注入防护"""
        from skill_cluster.db.skill_repository_base import SkillBaseRepository

        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = os.path.join(tmpdir, "test.db")

            class TestRepo(SkillBaseRepository):
                table_name = "test_items"
                primary_key = "id"
                allowed_sort_columns = {"name", "created_at"}
                allowed_columns = {"id", "name", "description", "created_at"}

                def __init__(self, db_path):
                    super().__init__(db_path)
                    self._db.execute(
                        "INSERT INTO test_items (id, name, description, created_at) VALUES (?, ?, ?, ?)",
                        ("1", "test-item", "a test item", "2025-01-01"),
                    )

                def _create_tables(self):
                    self._db.execute(
                        """
                        CREATE TABLE IF NOT EXISTS test_items (
                            id TEXT PRIMARY KEY,
                            name TEXT,
                            description TEXT,
                            created_at TEXT
                        )
                        """
                    )

                def _create_indexes(self):
                    pass

            repo = TestRepo(db_path)

            # 正常搜索
            results = repo.like_search(
                keyword="test",
                search_columns=["name", "description"],
            )
            assert len(results) == 1

            # 恶意排序列应该被拒绝
            with pytest.raises(ValueError):
                repo.like_search(
                    keyword="test",
                    search_columns=["name"],
                    order_by="name; DROP TABLE test_items--",
                )

            # 恶意搜索列应该被拒绝
            with pytest.raises(ValueError):
                repo.like_search(
                    keyword="test",
                    search_columns=["name' OR '1'='1"],
                )

            # 恶意条件列应该被拒绝
            with pytest.raises(ValueError):
                repo.like_search(
                    keyword="test",
                    search_columns=["name"],
                    conditions={"password": "123"},
                )

            repo.close()

    def test_table_name_validation(self):
        """测试表名安全校验"""
        from skill_cluster.db.skill_repository_base import SkillBaseRepository, validate_identifier

        # 直接测试 validate_identifier 函数（表名使用与标识符相同的校验规则）
        # 合法表名
        validate_identifier("valid_table_name")
        validate_identifier("users")
        validate_identifier("user_profiles_v2")

        # 非法表名应该被拒绝
        with pytest.raises(ValueError):
            validate_identifier("users; DROP TABLE important--")

        with pytest.raises(ValueError):
            validate_identifier("users DROP TABLE students")

        with pytest.raises(ValueError):
            validate_identifier("")

        with pytest.raises(ValueError):
            validate_identifier("123invalid")

        with pytest.raises(ValueError):
            validate_identifier("table-with-dashes")

        with pytest.raises(ValueError):
            validate_identifier('table"with"quotes')

        # 测试通过具体子类验证表名验证在初始化时被调用
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = os.path.join(tmpdir, "test.db")

            # 定义一个合法表名的子类
            class ValidRepo(SkillBaseRepository):
                table_name = "valid_test_table"
                primary_key = "id"

                def _create_tables(self):
                    pass

                def _create_indexes(self):
                    pass

            repo = ValidRepo(db_path)
            assert repo.table_name == "valid_test_table"
            repo.close()
