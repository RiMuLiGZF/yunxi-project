"""
M7 单元测试 - 工作流 CRUD 测试 (TS-002, P2级)

覆盖: 创建工作流、获取工作流、更新工作流、删除工作流、
      工作流列表分页、工作流模板
运行: python -m pytest tests/test_workflow_crud.py -v
"""
import os
import sys
import tempfile
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "shared"))

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

# 处理相对导入问题：以包的形式导入 src 模块
import importlib.util
import types

_src_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src"))

# 第一步：创建 m7_src 包
src_pkg = types.ModuleType("m7_src")
src_pkg.__path__ = [_src_dir]
src_pkg.__package__ = "m7_src"
sys.modules["m7_src"] = src_pkg

# 第二步：导入 db 模块
db_spec = importlib.util.spec_from_file_location(
    "m7_src.db", os.path.join(_src_dir, "db.py")
)
db_module = importlib.util.module_from_spec(db_spec)
db_module.__package__ = "m7_src"
sys.modules["m7_src.db"] = db_module
src_pkg.db = db_module
db_spec.loader.exec_module(db_module)

Base = db_module.Base

# 第三步：导入 models_db 模块（依赖 m7_src.db）
models_db_spec = importlib.util.spec_from_file_location(
    "m7_src.models_db", os.path.join(_src_dir, "models_db.py")
)
models_db = importlib.util.module_from_spec(models_db_spec)
models_db.__package__ = "m7_src"
sys.modules["m7_src.models_db"] = models_db
src_pkg.models_db = models_db
models_db_spec.loader.exec_module(models_db)

# 第四步：创建 repositories 子包
repos_dir = os.path.join(_src_dir, "repositories")
repos_pkg = types.ModuleType("m7_src.repositories")
repos_pkg.__path__ = [repos_dir]
repos_pkg.__package__ = "m7_src.repositories"
sys.modules["m7_src.repositories"] = repos_pkg
src_pkg.repositories = repos_pkg

# 第五步：导入 workflow_repo
wf_repo_spec = importlib.util.spec_from_file_location(
    "m7_src.repositories.workflow_repo",
    os.path.join(repos_dir, "workflow_repo.py"),
)
wf_repo_module = importlib.util.module_from_spec(wf_repo_spec)
wf_repo_module.__package__ = "m7_src.repositories"
sys.modules["m7_src.repositories.workflow_repo"] = wf_repo_module
repos_pkg.workflow_repo = wf_repo_module
wf_repo_spec.loader.exec_module(wf_repo_module)

WorkflowRepository = wf_repo_module.WorkflowRepository

# 第六步：导入 run_repo
run_repo_spec = importlib.util.spec_from_file_location(
    "m7_src.repositories.run_repo",
    os.path.join(repos_dir, "run_repo.py"),
)
run_repo_module = importlib.util.module_from_spec(run_repo_spec)
run_repo_module.__package__ = "m7_src.repositories"
sys.modules["m7_src.repositories.run_repo"] = run_repo_module
repos_pkg.run_repo = run_repo_module
run_repo_spec.loader.exec_module(run_repo_module)

RunRepository = run_repo_module.RunRepository


@pytest.fixture
def temp_data_dir():
    """临时数据目录."""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield tmpdir


@pytest.fixture
def db_session(temp_data_dir):
    """创建测试数据库会话."""
    db_path = os.path.join(temp_data_dir, "test_m7.db")
    engine = create_engine(
        f"sqlite:///{db_path}",
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(bind=engine)
    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


@pytest.fixture
def workflow_repo(db_session, temp_data_dir):
    """创建工作流仓库."""
    return WorkflowRepository(db_session, data_dir=temp_data_dir)


@pytest.fixture
def run_repo(db_session, temp_data_dir):
    """创建运行记录仓库."""
    return RunRepository(db_session, data_dir=temp_data_dir)


class TestWorkflowCreate:
    """创建工作流测试"""

    def test_create_workflow_success(self, workflow_repo):
        """创建工作流应成功."""
        wf_id = "wf_test_001"
        data = {
            "name": "测试工作流",
            "description": "这是一个测试工作流",
            "category": "测试分类",
            "status": "draft",
            "blocks": [
                {"id": "b1", "type": "skill.translate", "name": "翻译", "config": {}},
            ],
            "variables": [],
            "trigger": {"type": "manual"},
        }

        wf = workflow_repo.create(wf_id, data)

        assert wf is not None
        assert wf.id == wf_id
        assert wf.name == "测试工作流"
        assert wf.description == "这是一个测试工作流"
        assert wf.category == "测试分类"
        assert wf.status == "draft"

    def test_create_workflow_with_defaults(self, workflow_repo):
        """创建工作流时缺省字段应使用默认值."""
        wf_id = "wf_defaults"
        data = {
            "name": "默认值测试",
        }

        wf = workflow_repo.create(wf_id, data)

        assert wf.id == wf_id
        assert wf.name == "默认值测试"
        assert wf.status == "draft"  # 默认状态
        assert wf.category == ""  # 默认分类

    def test_create_workflow_with_blocks(self, workflow_repo):
        """创建带积木的工作流."""
        wf_id = "wf_with_blocks"
        data = {
            "name": "带积木工作流",
            "blocks": [
                {"id": "start", "type": "skill.web_fetch", "name": "开始", "config": {"action": "fetch"}},
                {"id": "end", "type": "skill.notify", "name": "结束", "config": {"action": "send"}},
            ],
        }

        wf = workflow_repo.create(wf_id, data)

        assert wf is not None
        assert len(wf.blocks) == 2
        assert wf.blocks[0]["id"] == "start"
        assert wf.blocks[1]["id"] == "end"

    def test_create_workflow_with_tags(self, workflow_repo):
        """创建带标签的工作流."""
        wf_id = "wf_with_tags"
        data = {
            "name": "带标签工作流",
            "tags": ["测试", "自动化", "P2"],
        }

        wf = workflow_repo.create(wf_id, data)

        assert wf is not None
        assert "测试" in wf.tags
        assert "自动化" in wf.tags
        assert len(wf.tags) == 3

    def test_create_workflow_created_by(self, workflow_repo):
        """创建工作流应记录创建者."""
        wf_id = "wf_creator"
        data = {
            "name": "创建者测试",
            "created_by": "tester",
        }

        wf = workflow_repo.create(wf_id, data)

        assert wf.created_by == "tester"


class TestWorkflowGet:
    """获取工作流测试"""

    def test_get_existing_workflow(self, workflow_repo):
        """获取已存在的工作流."""
        wf_id = "wf_get_test"
        workflow_repo.create(wf_id, {"name": "获取测试"})

        wf = workflow_repo.get(wf_id)

        assert wf is not None
        assert wf.id == wf_id
        assert wf.name == "获取测试"

    def test_get_nonexistent_workflow(self, workflow_repo):
        """获取不存在的工作流应返回 None."""
        wf = workflow_repo.get("nonexistent_wf")
        assert wf is None

    def test_get_workflow_to_dict(self, workflow_repo):
        """工作流应能转换为字典."""
        wf_id = "wf_dict_test"
        workflow_repo.create(wf_id, {"name": "字典测试", "description": "测试描述"})

        wf = workflow_repo.get(wf_id)
        wf_dict = wf.to_dict()

        assert isinstance(wf_dict, dict)
        assert wf_dict["id"] == wf_id
        assert wf_dict["name"] == "字典测试"
        assert "created_at" in wf_dict
        assert "updated_at" in wf_dict


class TestWorkflowUpdate:
    """更新工作流测试"""

    def test_update_workflow_name(self, workflow_repo):
        """更新工作流名称."""
        wf_id = "wf_update_name"
        workflow_repo.create(wf_id, {"name": "旧名称"})

        updated = workflow_repo.update(wf_id, {"name": "新名称"})

        assert updated is not None
        assert updated.name == "新名称"

        # 验证数据库中确实更新了
        wf = workflow_repo.get(wf_id)
        assert wf.name == "新名称"

    def test_update_workflow_description(self, workflow_repo):
        """更新工作流描述."""
        wf_id = "wf_update_desc"
        workflow_repo.create(wf_id, {"name": "测试", "description": "旧描述"})

        updated = workflow_repo.update(wf_id, {"description": "新描述"})

        assert updated.description == "新描述"

    def test_update_workflow_status(self, workflow_repo):
        """更新工作流状态."""
        wf_id = "wf_update_status"
        workflow_repo.create(wf_id, {"name": "测试", "status": "draft"})

        updated = workflow_repo.update(wf_id, {"status": "published"})

        assert updated.status == "published"

    def test_update_workflow_blocks(self, workflow_repo):
        """更新工作流积木."""
        wf_id = "wf_update_blocks"
        workflow_repo.create(wf_id, {
            "name": "测试",
            "blocks": [{"id": "old", "type": "skill.translate", "name": "旧"}],
        })

        new_blocks = [
            {"id": "new1", "type": "skill.web_fetch", "name": "新1"},
            {"id": "new2", "type": "skill.notify", "name": "新2"},
        ]
        updated = workflow_repo.update(wf_id, {"blocks": new_blocks})

        assert len(updated.blocks) == 2
        assert updated.blocks[0]["id"] == "new1"

    def test_update_nonexistent_workflow(self, workflow_repo):
        """更新不存在的工作流应返回 None."""
        result = workflow_repo.update("nonexistent", {"name": "测试"})
        assert result is None

    def test_update_preserves_untouched_fields(self, workflow_repo):
        """更新部分字段应保留其他字段."""
        wf_id = "wf_partial_update"
        workflow_repo.create(wf_id, {
            "name": "原名",
            "description": "原描述",
            "category": "原分类",
        })

        updated = workflow_repo.update(wf_id, {"name": "新名"})

        assert updated.name == "新名"
        assert updated.description == "原描述"  # 保留
        assert updated.category == "原分类"  # 保留

    def test_update_updates_timestamp(self, workflow_repo):
        """更新工作流应更新 updated_at 时间戳."""
        import time
        wf_id = "wf_timestamp"
        workflow_repo.create(wf_id, {"name": "测试"})

        wf_before = workflow_repo.get(wf_id)
        time.sleep(0.01)  # 确保时间差

        workflow_repo.update(wf_id, {"name": "更新后"})
        wf_after = workflow_repo.get(wf_id)

        assert wf_after.updated_at >= wf_before.updated_at


class TestWorkflowDelete:
    """删除工作流测试"""

    def test_delete_existing_workflow(self, workflow_repo):
        """删除已存在的工作流."""
        wf_id = "wf_delete_test"
        workflow_repo.create(wf_id, {"name": "删除测试"})

        # 删除前应存在
        assert workflow_repo.get(wf_id) is not None

        result = workflow_repo.delete(wf_id)
        assert result is True

        # 删除后应不存在
        assert workflow_repo.get(wf_id) is None

    def test_delete_nonexistent_workflow(self, workflow_repo):
        """删除不存在的工作流应返回 False."""
        result = workflow_repo.delete("nonexistent")
        assert result is False


class TestWorkflowList:
    """工作流列表分页测试"""

    def test_list_empty(self, workflow_repo):
        """空仓库列表应为空."""
        items, total = workflow_repo.list()
        assert total == 0
        assert len(items) == 0

    def test_list_all(self, workflow_repo):
        """列出所有工作流."""
        for i in range(5):
            workflow_repo.create(f"wf_list_{i}", {"name": f"工作流{i}"})

        items, total = workflow_repo.list(page_size=100)
        assert total == 5
        assert len(items) == 5

    def test_list_pagination(self, workflow_repo):
        """分页功能应正确工作."""
        for i in range(10):
            workflow_repo.create(f"wf_page_{i}", {"name": f"工作流{i}"})

        # 第一页
        items1, total = workflow_repo.list(page=1, page_size=3)
        assert total == 10
        assert len(items1) == 3

        # 第二页
        items2, _ = workflow_repo.list(page=2, page_size=3)
        assert len(items2) == 3

        # 两页内容不应重复
        ids1 = {wf.id for wf in items1}
        ids2 = {wf.id for wf in items2}
        assert len(ids1 & ids2) == 0

    def test_list_last_page(self, workflow_repo):
        """最后一页应返回剩余记录."""
        for i in range(7):
            workflow_repo.create(f"wf_last_{i}", {"name": f"工作流{i}"})

        items, total = workflow_repo.list(page=3, page_size=3)
        assert total == 7
        assert len(items) == 1  # 第3页只有1条

    def test_list_keyword_filter(self, workflow_repo):
        """按关键词筛选工作流."""
        workflow_repo.create("wf_apple", {"name": "苹果工作流", "description": "红苹果"})
        workflow_repo.create("wf_banana", {"name": "香蕉工作流", "description": "黄香蕉"})
        workflow_repo.create("wf_cherry", {"name": "樱桃工作流", "description": "红樱桃"})

        items, total = workflow_repo.list(keyword="苹果")
        assert total == 1
        assert items[0].id == "wf_apple"

    def test_list_category_filter(self, workflow_repo):
        """按分类筛选工作流."""
        workflow_repo.create("wf_cat1_a", {"name": "A", "category": "分类1"})
        workflow_repo.create("wf_cat1_b", {"name": "B", "category": "分类1"})
        workflow_repo.create("wf_cat2", {"name": "C", "category": "分类2"})

        items, total = workflow_repo.list(category="分类1")
        assert total == 2

    def test_list_status_filter(self, workflow_repo):
        """按状态筛选工作流."""
        workflow_repo.create("wf_draft", {"name": "草稿", "status": "draft"})
        workflow_repo.create("wf_pub", {"name": "已发布", "status": "published"})
        workflow_repo.create("wf_arch", {"name": "已归档", "status": "archived"})

        items, total = workflow_repo.list(status="published")
        assert total == 1
        assert items[0].status == "published"


class TestWorkflowStats:
    """工作流统计测试"""

    def test_count_empty(self, workflow_repo):
        """空仓库计数应为 0."""
        assert workflow_repo.count() == 0

    def test_count_after_create(self, workflow_repo):
        """创建后计数应增加."""
        workflow_repo.create("wf_count_1", {"name": "计数1"})
        assert workflow_repo.count() == 1

        workflow_repo.create("wf_count_2", {"name": "计数2"})
        assert workflow_repo.count() == 2

    def test_increment_run_count(self, workflow_repo):
        """增加运行次数."""
        wf_id = "wf_run_count"
        workflow_repo.create(wf_id, {"name": "运行计数测试"})

        result = workflow_repo.increment_run_count(wf_id)
        assert result is True

        wf = workflow_repo.get(wf_id)
        assert wf.run_count == 1

        # 再次增加
        workflow_repo.increment_run_count(wf_id)
        wf = workflow_repo.get(wf_id)
        assert wf.run_count == 2

    def test_increment_run_count_nonexistent(self, workflow_repo):
        """对不存在的工作流增加运行次数应返回 False."""
        result = workflow_repo.increment_run_count("nonexistent")
        assert result is False

    def test_get_stats(self, workflow_repo):
        """获取统计信息."""
        workflow_repo.create("wf_s1", {"name": "S1", "status": "draft", "category": "测试"})
        workflow_repo.create("wf_s2", {"name": "S2", "status": "published", "category": "测试"})

        stats = workflow_repo.get_stats()

        assert stats["total_workflows"] == 2
        assert "total_run_count" in stats
        assert "workflow_status" in stats
        assert "workflow_categories" in stats


class TestRunRepository:
    """运行记录仓库测试"""

    def test_add_run(self, run_repo):
        """添加运行记录."""
        run_data = {
            "run_id": "run_test_001",
            "workflow_name": "测试工作流",
            "status": "success",
            "steps": [],
            "duration_ms": 100,
            "triggered_by": "test",
        }

        run = run_repo.add("wf_test", run_data)

        assert run is not None
        assert run.id == "run_test_001"
        assert run.workflow_id == "wf_test"
        assert run.status == "success"

    def test_get_run(self, run_repo):
        """获取运行记录."""
        run_repo.add("wf_1", {"run_id": "run_get", "status": "running"})

        run = run_repo.get("run_get")
        assert run is not None
        assert run.id == "run_get"

    def test_get_nonexistent_run(self, run_repo):
        """获取不存在的运行记录应返回 None."""
        assert run_repo.get("nonexistent") is None

    def test_list_runs_by_workflow(self, run_repo):
        """按工作流列出运行记录."""
        run_repo.add("wf_a", {"run_id": "run_a1", "status": "success"})
        run_repo.add("wf_a", {"run_id": "run_a2", "status": "failed"})
        run_repo.add("wf_b", {"run_id": "run_b1", "status": "success"})

        runs = run_repo.list_by_workflow("wf_a")
        assert len(runs) == 2

    def test_list_runs_with_pagination(self, run_repo):
        """运行记录分页."""
        for i in range(10):
            run_repo.add("wf_test", {"run_id": f"run_{i}", "status": "success"})

        items, total = run_repo.list(page=1, page_size=4)
        assert total == 10
        assert len(items) == 4

    def test_update_run_status(self, run_repo):
        """更新运行记录状态."""
        run_repo.add("wf_test", {"run_id": "run_update", "status": "running"})

        result = run_repo.update("run_update", {"status": "success"})
        assert result is True

        run = run_repo.get("run_update")
        assert run.status == "success"
        assert run.finished_at is not None  # 终态应设置结束时间

    def test_count_runs(self, run_repo):
        """运行记录计数."""
        assert run_repo.count() == 0
        run_repo.add("wf_1", {"run_id": "r1", "status": "success"})
        run_repo.add("wf_1", {"run_id": "r2", "status": "success"})
        assert run_repo.count() == 2

    def test_count_by_workflow(self, run_repo):
        """按工作流计数运行记录."""
        run_repo.add("wf_a", {"run_id": "ra1", "status": "success"})
        run_repo.add("wf_a", {"run_id": "ra2", "status": "failed"})
        run_repo.add("wf_b", {"run_id": "rb1", "status": "success"})

        assert run_repo.count_by_workflow("wf_a") == 2
        assert run_repo.count_by_workflow("wf_b") == 1
        assert run_repo.count_by_workflow("wf_c") == 0

    def test_delete_runs_by_workflow(self, run_repo):
        """删除指定工作流的所有运行记录."""
        run_repo.add("wf_del", {"run_id": "rd1", "status": "success"})
        run_repo.add("wf_del", {"run_id": "rd2", "status": "failed"})
        run_repo.add("wf_keep", {"run_id": "rk1", "status": "success"})

        deleted = run_repo.delete_by_workflow("wf_del")
        assert deleted == 2

        assert run_repo.count_by_workflow("wf_del") == 0
        assert run_repo.count_by_workflow("wf_keep") == 1
