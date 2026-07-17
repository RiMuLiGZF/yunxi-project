"""
M9 单元测试 - 运行历史管理测试

覆盖: 运行记录添加、历史查询、统计、清除
运行: python -m pytest tests/unit/test_run_history.py -v
"""
import os
import sys
import pytest
import tempfile
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "..", "shared"))

from run_history import RunHistoryManager, RunConfiguration


@pytest.fixture
def temp_workspace():
    """临时工作区 fixture"""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield tmpdir


@pytest.fixture
def history_manager(temp_workspace):
    """运行历史管理器 fixture"""
    import config
    original_root = config.get_settings().workspace_root
    config.get_settings().workspace_root = temp_workspace

    mgr = RunHistoryManager()
    # 覆盖历史目录
    mgr._history_dir = temp_workspace + "/.run_history"
    os.makedirs(mgr._history_dir, exist_ok=True)

    yield mgr

    config.get_settings().workspace_root = original_root


@pytest.fixture
def sample_config():
    """示例运行配置"""
    return {
        "name": "main",
        "language": "python",
        "command": "python main.py",
        "args": [],
        "env": {"ENV": "test"},
        "working_dir": "/project",
        "timeout": 30,
    }


@pytest.fixture
def sample_result():
    """示例运行结果"""
    return {
        "success": True,
        "exit_code": 0,
        "stdout": "Hello, World!\n",
        "stderr": "",
        "execution_time": 0.123,
    }


class TestRunConfiguration:
    """运行配置测试"""

    def test_create_config(self):
        """创建运行配置"""
        config = RunConfiguration(
            name="test",
            language="python",
            command="python test.py",
        )
        assert config.name == "test"
        assert config.language == "python"
        assert config.command == "python test.py"

    def test_config_defaults(self):
        """配置默认值"""
        config = RunConfiguration()
        assert config.name == "default"
        assert config.language == "python"
        assert config.timeout == 30

    def test_config_to_dict(self):
        """配置转字典"""
        config = RunConfiguration(
            name="test",
            language="python",
            command="python main.py",
        )
        d = config.to_dict()
        assert d["name"] == "test"
        assert d["language"] == "python"
        assert d["command"] == "python main.py"

    def test_config_from_dict(self):
        """从字典创建配置"""
        data = {
            "name": "custom",
            "language": "python",
            "command": "python app.py",
            "args": ["--debug"],
            "env": {"DEBUG": "1"},
            "timeout": 60,
        }
        config = RunConfiguration.from_dict(data)
        assert config.name == "custom"
        assert config.command == "python app.py"
        assert config.args == ["--debug"]
        assert config.timeout == 60


class TestRunHistoryManager:
    """运行历史管理器测试"""

    def test_init(self, history_manager):
        """初始化测试"""
        assert history_manager is not None
        assert os.path.exists(history_manager._history_dir)

    def test_add_run_record(self, history_manager, sample_config, sample_result):
        """添加运行记录"""
        record = history_manager.add_run_record(
            project_path="/test/project",
            config=sample_config,
            result=sample_result,
        )

        assert "run_id" in record
        assert record["run_id"].startswith("run_")
        assert record["config"] == sample_config
        assert record["result"]["success"] is True
        assert "timestamp" in record

    def test_get_run_history_empty(self, history_manager):
        """空历史记录"""
        result = history_manager.get_run_history("/nonexistent/project")
        assert result["total"] == 0
        assert result["items"] == []

    def test_get_run_history(self, history_manager, sample_config, sample_result):
        """获取运行历史"""
        # 添加几条记录
        for i in range(5):
            sample_result_copy = dict(sample_result)
            sample_result_copy["execution_time"] = 0.1 * i
            history_manager.add_run_record(
                project_path="/test/project",
                config=sample_config,
                result=sample_result_copy,
            )

        result = history_manager.get_run_history("/test/project", limit=10)
        assert result["total"] == 5
        assert len(result["items"]) == 5

    def test_run_history_order(self, history_manager, sample_config, sample_result):
        """历史记录按时间倒序"""
        for i in range(3):
            time.sleep(0.01)  # 确保时间戳不同
            history_manager.add_run_record(
                project_path="/test/project",
                config=sample_config,
                result=sample_result,
            )

        result = history_manager.get_run_history("/test/project")
        items = result["items"]
        # 最新的应该在前面
        assert items[0]["timestamp"] >= items[-1]["timestamp"]

    def test_run_history_pagination(self, history_manager, sample_config, sample_result):
        """历史记录分页"""
        for i in range(10):
            history_manager.add_run_record(
                project_path="/test/project",
                config=sample_config,
                result=sample_result,
            )

        page1 = history_manager.get_run_history("/test/project", limit=3, offset=0)
        page2 = history_manager.get_run_history("/test/project", limit=3, offset=3)

        assert len(page1["items"]) == 3
        assert len(page2["items"]) == 3
        # 不同页的记录 ID 不同
        assert page1["items"][0]["run_id"] != page2["items"][0]["run_id"]

    def test_run_history_success_only(self, history_manager, sample_config):
        """仅返回成功记录"""
        # 添加成功和失败的记录
        success_result = {"success": True, "exit_code": 0, "stdout": "", "stderr": "", "execution_time": 0.1}
        fail_result = {"success": False, "exit_code": 1, "stdout": "", "stderr": "error", "execution_time": 0.1}

        for i in range(3):
            history_manager.add_run_record("/test/project", sample_config, success_result)
        for i in range(2):
            history_manager.add_run_record("/test/project", sample_config, fail_result)

        all_records = history_manager.get_run_history("/test/project")
        success_records = history_manager.get_run_history("/test/project", success_only=True)

        assert all_records["total"] == 5
        assert success_records["total"] == 3

    def test_run_history_by_language(self, history_manager):
        """按语言过滤"""
        python_config = {"language": "python", "command": "python main.py"}
        node_config = {"language": "javascript", "command": "node index.js"}
        result = {"success": True, "exit_code": 0, "stdout": "", "stderr": "", "execution_time": 0.1}

        history_manager.add_run_record("/test/project", python_config, result)
        history_manager.add_run_record("/test/project", node_config, result)

        python_records = history_manager.get_run_history("/test/project", language="python")
        assert python_records["total"] == 1
        assert python_records["items"][0]["language"] == "python"

    def test_get_run_detail(self, history_manager, sample_config, sample_result):
        """获取运行详情"""
        record = history_manager.add_run_record(
            "/test/project", sample_config, sample_result
        )
        run_id = record["run_id"]

        detail = history_manager.get_run_detail("/test/project", run_id)
        assert detail is not None
        assert detail["run_id"] == run_id
        assert detail["config"] == sample_config

    def test_get_run_detail_not_found(self, history_manager):
        """获取不存在的运行详情"""
        result = history_manager.get_run_detail("/test/project", "nonexistent")
        assert result is None

    def test_clear_history(self, history_manager, sample_config, sample_result):
        """清除历史记录"""
        for i in range(3):
            history_manager.add_run_record(
                "/test/project", sample_config, sample_result
            )

        # 确认有记录
        before = history_manager.get_run_history("/test/project")
        assert before["total"] == 3

        # 清除
        success = history_manager.clear_history("/test/project")
        assert success is True

        # 确认已清除
        after = history_manager.get_run_history("/test/project")
        assert after["total"] == 0

    def test_get_stats(self, history_manager, sample_config):
        """获取运行统计"""
        success_result = {"success": True, "exit_code": 0, "stdout": "", "stderr": "", "execution_time": 0.1}
        fail_result = {"success": False, "exit_code": 1, "stdout": "", "stderr": "error", "execution_time": 0.2}

        history_manager.add_run_record("/test/project", sample_config, success_result)
        history_manager.add_run_record("/test/project", sample_config, success_result)
        history_manager.add_run_record("/test/project", sample_config, fail_result)

        stats = history_manager.get_stats("/test/project")
        assert stats["total_runs"] == 3
        assert stats["success_count"] == 2
        assert stats["failed_count"] == 1
        assert stats["success_rate"] == pytest.approx(66.67, rel=1e-2)
        assert stats["avg_execution_time"] > 0
        assert "last_run_at" in stats
        assert "by_language" in stats

    def test_get_stats_empty(self, history_manager):
        """空统计"""
        stats = history_manager.get_stats("/nonexistent/project")
        assert stats["total_runs"] == 0
        assert stats["success_count"] == 0
        assert stats["success_rate"] == 0

    def test_multiple_projects(self, history_manager, sample_config, sample_result):
        """多个项目的历史互不干扰"""
        history_manager.add_run_record("/project/a", sample_config, sample_result)
        history_manager.add_run_record("/project/b", sample_config, sample_result)
        history_manager.add_run_record("/project/b", sample_config, sample_result)

        a_history = history_manager.get_run_history("/project/a")
        b_history = history_manager.get_run_history("/project/b")

        assert a_history["total"] == 1
        assert b_history["total"] == 2

    def test_max_records_limit(self, temp_workspace, sample_config, sample_result):
        """最大记录数限制"""
        mgr = RunHistoryManager()
        mgr._history_dir = temp_workspace + "/.run_history2"
        mgr._max_records = 5
        os.makedirs(mgr._history_dir, exist_ok=True)

        for i in range(10):
            mgr.add_run_record("/test/project", sample_config, sample_result)

        history = mgr.get_run_history("/test/project", limit=100)
        assert history["total"] == 5  # 受 max_records 限制


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
