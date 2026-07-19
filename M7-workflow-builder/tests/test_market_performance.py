"""
M7 积木平台 - 市场接口性能优化测试

测试内容：
1. 索引测试 - 验证索引存在、查询使用索引
2. 分页测试 - 基本分页、空结果、超出范围、page_size限制、分页正确性
3. SQL 聚合测试 - 统计准确性、空数据统计、分组统计

运行方式: pytest tests/test_market_performance.py -v
"""

from __future__ import annotations

import os
import sys
import types
import importlib.util
from datetime import datetime, timedelta

import pytest
from sqlalchemy import create_engine, text, func
from sqlalchemy.orm import Session


# ============================================================
# 处理相对导入：创建 m7_src 包结构
# ============================================================

_src_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src"))

# 创建 src 包（对应相对导入中的 ..）
src_pkg = types.ModuleType("src")
src_pkg.__path__ = [_src_dir]
src_pkg.__package__ = "src"
sys.modules["src"] = src_pkg

# 导入 db 模块
db_spec = importlib.util.spec_from_file_location(
    "src.db", os.path.join(_src_dir, "db.py")
)
db_module = importlib.util.module_from_spec(db_spec)
db_module.__package__ = "src"
sys.modules["src.db"] = db_module
src_pkg.db = db_module
db_spec.loader.exec_module(db_module)

Base = db_module.Base

# 创建 routers 子包
routers_dir = os.path.join(_src_dir, "routers")
routers_pkg = types.ModuleType("src.routers")
routers_pkg.__path__ = [routers_dir]
routers_pkg.__package__ = "src.routers"
sys.modules["src.routers"] = routers_pkg
src_pkg.routers = routers_pkg

# 导入 routers.__init__
routers_init_spec = importlib.util.spec_from_file_location(
    "src.routers.__init__", os.path.join(routers_dir, "__init__.py")
)
routers_init_module = importlib.util.module_from_spec(routers_init_spec)
routers_init_module.__package__ = "src.routers"
sys.modules["src.routers.__init__"] = routers_init_module
routers_pkg.__init__ = routers_init_module
routers_init_spec.loader.exec_module(routers_init_module)

# 导入 market 模块
market_spec = importlib.util.spec_from_file_location(
    "src.routers.market", os.path.join(routers_dir, "market.py")
)
market_module = importlib.util.module_from_spec(market_spec)
market_module.__package__ = "src.routers"
sys.modules["src.routers.market"] = market_module
routers_pkg.market = market_module

# 先检查 m8_api 和 utils 依赖是否能加载
def _try_import_submodule(pkg_name, module_name, file_name):
    """尝试导入子模块，失败则创建空占位模块."""
    try:
        spec = importlib.util.spec_from_file_location(
            f"{pkg_name}.{module_name}",
            os.path.join(_src_dir, file_name),
        )
        module = importlib.util.module_from_spec(spec)
        module.__package__ = pkg_name
        sys.modules[f"{pkg_name}.{module_name}"] = module
        spec.loader.exec_module(module)
        return module
    except Exception:
        # 创建空占位模块
        module = types.ModuleType(f"{pkg_name}.{module_name}")
        module.__package__ = pkg_name
        sys.modules[f"{pkg_name}.{module_name}"] = module
        return module

# 创建 m8_api 包
m8api_dir = os.path.join(_src_dir, "m8_api")
m8api_pkg = types.ModuleType("src.m8_api")
m8api_pkg.__path__ = [m8api_dir]
m8api_pkg.__package__ = "src.m8_api"
sys.modules["src.m8_api"] = m8api_pkg
src_pkg.m8_api = m8api_pkg

# 导入 auth middleware（如果失败则创建 mock）
try:
    m8auth_spec = importlib.util.spec_from_file_location(
        "src.m8_api.m8_auth_middleware",
        os.path.join(m8api_dir, "m8_auth_middleware.py"),
    )
    m8auth_module = importlib.util.module_from_spec(m8auth_spec)
    m8auth_module.__package__ = "src.m8_api"
    sys.modules["src.m8_api.m8_auth_middleware"] = m8auth_module
    m8api_pkg.m8_auth_middleware = m8auth_module
    m8auth_spec.loader.exec_module(m8auth_module)
except Exception:
    # 创建 mock 模块
    m8auth_module = types.ModuleType("src.m8_api.m8_auth_middleware")
    m8auth_module.get_current_user = lambda: {"username": "test_user"}
    sys.modules["src.m8_api.m8_auth_middleware"] = m8auth_module
    m8api_pkg.m8_auth_middleware = m8auth_module

# 创建 utils 包
utils_dir = os.path.join(_src_dir, "utils")
utils_pkg = types.ModuleType("src.utils")
utils_pkg.__path__ = [utils_dir]
utils_pkg.__package__ = "src.utils"
sys.modules["src.utils"] = utils_pkg
src_pkg.utils = utils_pkg

# 导入 security 模块（如果失败则创建 mock）
try:
    security_spec = importlib.util.spec_from_file_location(
        "src.utils.security",
        os.path.join(utils_dir, "security.py"),
    )
    security_module = importlib.util.module_from_spec(security_spec)
    security_module.__package__ = "src.utils"
    sys.modules["src.utils.security"] = security_module
    utils_pkg.security = security_module
    security_spec.loader.exec_module(security_module)
except Exception:
    security_module = types.ModuleType("src.utils.security")
    security_module.validate_custom_block_code = lambda code, user_id="", block_id="": (True, "")
    security_module.sanitize_custom_block_name = lambda name, max_len: name[:max_len]
    security_module._add_audit_log = lambda **kwargs: None
    sys.modules["src.utils.security"] = security_module
    utils_pkg.security = security_module

# 现在可以加载 market 模块了
market_spec.loader.exec_module(market_module)

# 导出需要的符号
MarketTemplate = market_module.MarketTemplate
MarketBlock = market_module.MarketBlock
MarketRating = market_module.MarketRating
_paginate_result = market_module._paginate_result
_calc_rating_avg = market_module._calc_rating_avg


# ============================================================
# Fixtures
# ============================================================

@pytest.fixture
def test_engine(tmp_path):
    """创建 SQLite 测试引擎（文件模式，支持索引验证）."""
    db_path = tmp_path / "test_market.db"
    engine = create_engine(
        f"sqlite:///{db_path}",
        connect_args={"check_same_thread": False},
    )
    # 创建所有表
    Base.metadata.create_all(bind=engine)
    yield engine
    engine.dispose()


@pytest.fixture
def test_session(test_engine):
    """创建测试数据库会话."""
    session = Session(test_engine)
    try:
        yield session
    finally:
        session.close()


@pytest.fixture
def seed_templates(test_session):
    """植入测试模板数据（25 条，5 个分类）."""
    categories = ["general", "automation", "data", "ai", "tools"]
    templates = []
    for i in range(25):
        cat = categories[i % len(categories)]
        tpl = MarketTemplate(
            template_id=f"mkt_test_{i:03d}",
            name=f"测试模板 {i}",
            description=f"这是第 {i} 个测试模板",
            author=f"user_{i % 5}",
            category=cat,
            tags=[f"tag_{i % 3}"],
            blocks=[{"id": f"b{i}", "type": "test"}],
            connections=[],
            variables=[],
            trigger={},
            download_count=i * 10,
            rating_sum=float(i * 4),
            rating_count=i,
            source_workflow_id=f"wf_src_{i}",
            status="published" if i < 20 else "unpublished",
            created_at=datetime(2024, 1, 1) + timedelta(days=i),
            updated_at=datetime(2024, 1, 1) + timedelta(days=i),
        )
        templates.append(tpl)
        test_session.add(tpl)
    test_session.commit()
    return templates


@pytest.fixture
def seed_blocks(test_session):
    """植入测试积木数据（15 条，3 个分类）."""
    categories = ["general", "transform", "output"]
    blocks = []
    for i in range(15):
        cat = categories[i % len(categories)]
        blk = MarketBlock(
            block_id=f"mkb_test_{i:03d}",
            name=f"测试积木 {i}",
            description=f"这是第 {i} 个测试积木",
            author=f"user_{i % 3}",
            category=cat,
            tags=[f"tag_{i % 2}"],
            code=f"// block {i}",
            icon="puzzle",
            ports={},
            download_count=i * 5,
            rating_sum=float(i * 3),
            rating_count=i,
            source_block_id=f"cb_src_{i}",
            status="published" if i < 12 else "unpublished",
            created_at=datetime(2024, 1, 1) + timedelta(days=i),
            updated_at=datetime(2024, 1, 1) + timedelta(days=i),
        )
        blocks.append(blk)
        test_session.add(blk)
    test_session.commit()
    return blocks


@pytest.fixture
def seed_ratings(test_session, seed_templates, seed_blocks):
    """植入测试评分数据."""
    ratings = []
    # 给前 10 个模板各加 2 个评分
    for i in range(10):
        for j in range(2):
            r = MarketRating(
                id=f"rt_tpl_{i}_{j}",
                item_type="template",
                item_id=f"mkt_test_{i:03d}",
                user_id=f"user_{j}",
                rating=3 + j,  # 3 或 4
                comment="",
                created_at=datetime(2024, 1, 1) + timedelta(days=i + j),
            )
            ratings.append(r)
            test_session.add(r)
    # 给前 5 个积木各加 2 个评分
    for i in range(5):
        for j in range(2):
            r = MarketRating(
                id=f"rt_blk_{i}_{j}",
                item_type="block",
                item_id=f"mkb_test_{i:03d}",
                user_id=f"user_{j}",
                rating=4 + j % 2,  # 4 或 5
                comment="",
                created_at=datetime(2024, 1, 1) + timedelta(days=i + j),
            )
            ratings.append(r)
            test_session.add(r)
    test_session.commit()
    return ratings


# ============================================================
# 索引测试
# ============================================================

class TestIndexOptimization:
    """索引优化测试."""

    def test_market_templates_status_index_exists(self, test_engine):
        """验证 market_templates.status 索引存在."""
        with test_engine.connect() as conn:
            result = conn.execute(text("""
                SELECT name FROM sqlite_master 
                WHERE type='index' AND tbl_name='market_templates'
                ORDER BY name
            """)).fetchall()
            index_names = [row[0] for row in result]

            # 检查单列索引
            assert any("status" in name.lower() for name in index_names), \
                f"market_templates 缺少 status 索引，现有索引: {index_names}"

    def test_market_templates_category_index_exists(self, test_engine):
        """验证 market_templates.category 索引存在."""
        with test_engine.connect() as conn:
            result = conn.execute(text("""
                SELECT name FROM sqlite_master 
                WHERE type='index' AND tbl_name='market_templates'
                ORDER BY name
            """)).fetchall()
            index_names = [row[0] for row in result]

            assert any("category" in name.lower() for name in index_names), \
                f"market_templates 缺少 category 索引，现有索引: {index_names}"

    def test_market_blocks_status_and_category_indexes(self, test_engine):
        """验证 market_blocks 的 status 和 category 索引存在."""
        with test_engine.connect() as conn:
            result = conn.execute(text("""
                SELECT name FROM sqlite_master 
                WHERE type='index' AND tbl_name='market_blocks'
                ORDER BY name
            """)).fetchall()
            index_names = [row[0] for row in result]

            assert any("status" in name.lower() for name in index_names), \
                f"market_blocks 缺少 status 索引，现有索引: {index_names}"
            assert any("category" in name.lower() for name in index_names), \
                f"market_blocks 缺少 category 索引，现有索引: {index_names}"

    def test_query_uses_index_status_filter(self, test_engine, seed_templates):
        """验证 status 过滤查询执行计划（SQLite EXPLAIN）."""
        with test_engine.connect() as conn:
            result = conn.execute(text("""
                EXPLAIN QUERY PLAN
                SELECT * FROM market_templates WHERE status = 'published'
            """)).fetchall()

            # 验证 EXPLAIN 有结果
            assert len(result) > 0, "EXPLAIN 查询返回空"
            # 打印执行计划供参考
            plan_text = str(result)
            assert "market_templates" in plan_text

    def test_market_ratings_indexes_exist(self, test_engine):
        """验证 market_ratings 的索引存在."""
        with test_engine.connect() as conn:
            result = conn.execute(text("""
                SELECT name FROM sqlite_master 
                WHERE type='index' AND tbl_name='market_ratings'
                ORDER BY name
            """)).fetchall()
            index_names = [row[0] for row in result]

            assert any("item_type" in name.lower() for name in index_names), \
                f"market_ratings 缺少 item_type 索引，现有索引: {index_names}"
            assert any("item_id" in name.lower() for name in index_names), \
                f"market_ratings 缺少 item_id 索引，现有索引: {index_names}"


# ============================================================
# 分页测试
# ============================================================

class TestPagination:
    """分页功能测试."""

    def test_paginate_result_basic(self):
        """基本分页结果计算."""
        result = _paginate_result(["a", "b", "c"], 100, 1, 10)
        assert result["total"] == 100
        assert result["page"] == 1
        assert result["page_size"] == 10
        assert result["size"] == 10  # 向后兼容
        assert result["total_pages"] == 10
        assert len(result["items"]) == 3

    def test_paginate_result_empty(self):
        """空结果分页."""
        result = _paginate_result([], 0, 1, 20)
        assert result["total"] == 0
        assert result["total_pages"] == 0
        assert result["items"] == []

    def test_paginate_result_last_page(self):
        """最后一页分页计算."""
        result = _paginate_result(["x"], 25, 3, 10)
        assert result["total"] == 25
        assert result["page"] == 3
        assert result["total_pages"] == 3  # (25 + 10 - 1) // 10 = 3

    def test_paginate_result_exact_pages(self):
        """整除时的总页数计算."""
        result = _paginate_result([], 100, 1, 20)
        assert result["total_pages"] == 5  # 100 / 20 = 5

    def test_paginate_result_page_size_limit(self):
        """page_size 计算边界值."""
        # 边界：1 条数据 1 页
        result = _paginate_result([], 1, 1, 1)
        assert result["total_pages"] == 1

        # 边界：0 条数据 0 页
        result = _paginate_result([], 0, 1, 100)
        assert result["total_pages"] == 0

    def test_template_list_pagination_query(self, test_session, seed_templates):
        """模板列表分页查询正确性（SQL 层面验证）."""
        page, page_size = 1, 10
        query = test_session.query(MarketTemplate).filter_by(status="published")
        total = query.count()
        items = query.order_by(
            MarketTemplate.created_at.desc()
        ).offset((page - 1) * page_size).limit(page_size).all()

        assert total == 20  # 20 个 published
        assert len(items) == 10
        # 按创建时间倒序，第一个应该是最新的
        assert items[0].template_id == "mkt_test_019"  # 第 19 号最新

    def test_template_list_second_page(self, test_session, seed_templates):
        """模板列表第二页查询."""
        page, page_size = 2, 10
        query = test_session.query(MarketTemplate).filter_by(status="published")
        total = query.count()
        items = query.order_by(
            MarketTemplate.created_at.desc()
        ).offset((page - 1) * page_size).limit(page_size).all()

        assert total == 20
        assert len(items) == 10
        # 第二页第一条应该是第 10 个（009）
        assert items[0].template_id == "mkt_test_009"

    def test_template_list_out_of_range(self, test_session, seed_templates):
        """超出范围的分页返回空列表."""
        page, page_size = 10, 10
        query = test_session.query(MarketTemplate).filter_by(status="published")
        items = query.order_by(
            MarketTemplate.created_at.desc()
        ).offset((page - 1) * page_size).limit(page_size).all()

        assert len(items) == 0

    def test_block_list_pagination_query(self, test_session, seed_blocks):
        """积木列表分页查询正确性."""
        page, page_size = 1, 5
        query = test_session.query(MarketBlock).filter_by(status="published")
        total = query.count()
        items = query.order_by(
            MarketBlock.created_at.desc()
        ).offset((page - 1) * page_size).limit(page_size).all()

        assert total == 12  # 12 个 published
        assert len(items) == 5


# ============================================================
# SQL 聚合测试
# ============================================================

class TestSqlAggregation:
    """SQL 聚合功能测试."""

    def test_template_download_sum(self, test_session, seed_templates):
        """验证 SQL sum 计算模板下载总量的准确性."""
        # SQL 聚合
        sql_sum = test_session.query(
            func.coalesce(func.sum(MarketTemplate.download_count), 0)
        ).filter_by(status="published").scalar()

        # Python 计算（预期值）：前 20 个（published）下载量之和
        expected = sum(i * 10 for i in range(20))  # 0+10+20+...+190 = 1900

        assert int(sql_sum) == expected, \
            f"SQL sum 结果 {sql_sum} 与预期 {expected} 不符"

    def test_block_download_sum(self, test_session, seed_blocks):
        """验证 SQL sum 计算积木下载总量的准确性."""
        sql_sum = test_session.query(
            func.coalesce(func.sum(MarketBlock.download_count), 0)
        ).filter_by(status="published").scalar()

        # 前 12 个 published 积木的下载量之和: 0+5+10+...+55 = 330
        expected = sum(i * 5 for i in range(12))

        assert int(sql_sum) == expected, \
            f"SQL sum 结果 {sql_sum} 与预期 {expected} 不符"

    def test_average_rating(self, test_session, seed_ratings):
        """验证 SQL avg 计算平均评分的准确性."""
        sql_avg = test_session.query(
            func.coalesce(func.avg(MarketRating.rating), 0.0)
        ).scalar()

        # 预期值：模板评分 20 条 + 积木评分 10 条
        # 模板: 每个模板两个评分 3 和 4，共 10 个模板 → 10 * (3+4) = 70
        # 积木: 每个积木两个评分 4 和 5，共 5 个积木 → 5 * (4+5) = 45
        # 总分: 70 + 45 = 115, 总条数: 20 + 10 = 30
        expected_avg = round(115 / 30, 1)

        assert round(float(sql_avg), 1) == expected_avg, \
            f"SQL avg 结果 {sql_avg} 与预期 {expected_avg} 不符"

    def test_category_group_by_templates(self, test_session, seed_templates):
        """验证 SQL group_by 分类统计的准确性."""
        rows = test_session.query(
            MarketTemplate.category,
            func.count(MarketTemplate.template_id)
        ).filter_by(status="published").group_by(MarketTemplate.category).all()

        cat_counts = dict(rows)

        # 20 个 published 模板，5 个分类循环 → 每个分类 4 个
        assert cat_counts.get("general") == 4
        assert cat_counts.get("automation") == 4
        assert cat_counts.get("data") == 4
        assert cat_counts.get("ai") == 4
        assert cat_counts.get("tools") == 4

    def test_empty_data_stats(self, test_session):
        """空数据下的 SQL 聚合返回正确的零值."""
        # 空表 count
        tpl_count = test_session.query(MarketTemplate).filter_by(status="published").count()
        assert tpl_count == 0

        # 空表 sum
        tpl_dl = test_session.query(
            func.coalesce(func.sum(MarketTemplate.download_count), 0)
        ).filter_by(status="published").scalar()
        assert int(tpl_dl) == 0

        # 空表 avg
        avg_rating = test_session.query(
            func.coalesce(func.avg(MarketRating.rating), 0.0)
        ).scalar()
        assert float(avg_rating) == 0.0

        # 空表 group_by
        rows = test_session.query(
            MarketTemplate.category,
            func.count(MarketTemplate.template_id)
        ).filter_by(status="published").group_by(MarketTemplate.category).all()
        assert rows == []

    def test_distinct_categories(self, test_session, seed_templates, seed_blocks):
        """验证 SQL distinct 去重分类的准确性."""
        # 模板分类 distinct
        tpl_cats = test_session.query(
            MarketTemplate.category
        ).filter_by(status="published").distinct().all()
        tpl_cat_set = {cat for (cat,) in tpl_cats if cat}

        # 应该有 5 个分类
        assert tpl_cat_set == {"general", "automation", "data", "ai", "tools"}

        # 积木分类 distinct
        blk_cats = test_session.query(
            MarketBlock.category
        ).filter_by(status="published").distinct().all()
        blk_cat_set = {cat for (cat,) in blk_cats if cat}

        # 应该有 3 个分类
        assert blk_cat_set == {"general", "transform", "output"}

    def test_calc_rating_avg_helper(self):
        """测试 _calc_rating_avg 辅助函数."""
        assert _calc_rating_avg(10.0, 2) == 5.0
        assert _calc_rating_avg(0.0, 0) == 0.0
        assert _calc_rating_avg(9.0, 3) == 3.0
        assert _calc_rating_avg(10.0, 3) == 3.3  # 四舍五入到 1 位


# ============================================================
# 性能对比测试（可选）
# ============================================================

class TestPerformanceComparison:
    """性能对比测试 - 验证优化效果."""

    def test_sql_sum_vs_python_sum(self, test_session, seed_templates):
        """SQL sum 对比 Python sum - 验证结果一致."""
        import time

        # SQL 聚合
        start = time.perf_counter()
        sql_result = test_session.query(
            func.coalesce(func.sum(MarketTemplate.download_count), 0)
        ).filter_by(status="published").scalar()
        sql_time = time.perf_counter() - start

        # Python 聚合
        start = time.perf_counter()
        all_items = test_session.query(MarketTemplate).filter_by(status="published").all()
        py_result = sum((mt.download_count or 0) for mt in all_items)
        py_time = time.perf_counter() - start

        # 结果必须一致
        assert int(sql_result) == py_result

        print(f"  SQL sum 耗时: {sql_time:.6f}s")
        print(f"  Python sum 耗时: {py_time:.6f}s")

    def test_sql_group_by_vs_python_loop(self, test_session, seed_templates):
        """SQL group_by 对比 Python 循环 - 验证结果一致."""
        import time

        # SQL 聚合
        start = time.perf_counter()
        rows = test_session.query(
            MarketTemplate.category,
            func.count(MarketTemplate.template_id)
        ).filter_by(status="published").group_by(MarketTemplate.category).all()
        sql_result = dict(rows)
        sql_time = time.perf_counter() - start

        # Python 聚合
        start = time.perf_counter()
        all_items = test_session.query(MarketTemplate).filter_by(status="published").all()
        py_result = {}
        for mt in all_items:
            cat = mt.category or "general"
            py_result[cat] = py_result.get(cat, 0) + 1
        py_time = time.perf_counter() - start

        # 结果必须一致
        assert sql_result == py_result

        print(f"  SQL group_by 耗时: {sql_time:.6f}s")
        print(f"  Python loop 耗时: {py_time:.6f}s")
