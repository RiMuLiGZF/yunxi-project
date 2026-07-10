"""
M9 开发者工坊 - VS Code 管理测试
测试内容：
1. VS Code 安装检测
2. 版本获取
3. 扩展列表
4. 会话管理
5. 路径打开/关闭

使用方式：
    cd M9-dev-workshop/backend
    python -m pytest tests/test_vscode.py -v
    或
    python tests/test_vscode.py
"""

import sys
from pathlib import Path

# 添加项目路径
backend_dir = Path(__file__).parent.parent.resolve()
if str(backend_dir) not in sys.path:
    sys.path.insert(0, str(backend_dir))

import pytest
from unittest.mock import patch, MagicMock

from vscode_manager import VSCodeManager, get_vscode_manager


# ==================== Fixtures ====================

@pytest.fixture
def vscode_manager():
    """创建 VSCodeManager 实例"""
    return VSCodeManager()


# ==================== 基础功能测试 ====================

class TestVSCodeBasics:
    """VS Code 基础功能测试"""

    def test_manager_initialization(self, vscode_manager):
        """测试管理器初始化"""
        assert vscode_manager is not None
        assert hasattr(vscode_manager, 'vscode_path')
        assert hasattr(vscode_manager, 'extensions')

    def test_get_status(self, vscode_manager):
        """测试获取状态"""
        status = vscode_manager.get_status()
        assert "installed" in status
        assert "running" in status
        assert "version" in status
        assert isinstance(status["installed"], bool)

    def test_get_version(self, vscode_manager):
        """测试获取版本"""
        result = vscode_manager.get_version()
        assert isinstance(result, dict)
        assert "success" in result
        # 结果可能是成功或失败，但格式必须正确
        if result["success"]:
            assert "version" in result


# ==================== 扩展管理测试 ====================

class TestExtensions:
    """扩展管理测试"""

    def test_list_extensions(self, vscode_manager):
        """测试列出扩展"""
        result = vscode_manager.list_extensions()
        assert isinstance(result, list)
        # 结果可能是空列表或有扩展，但格式必须正确
        for ext in result:
            assert "name" in ext or "id" in ext

    def test_get_extensions_count(self, vscode_manager):
        """测试获取扩展数量"""
        exts = vscode_manager.list_extensions()
        assert isinstance(len(exts), int)


# ==================== 会话管理测试 ====================

class TestSessions:
    """会话管理测试"""

    def test_get_sessions(self, vscode_manager):
        """测试获取会话列表"""
        sessions = vscode_manager.get_sessions()
        assert isinstance(sessions, list)

    def test_get_sessions_with_limit(self, vscode_manager):
        """测试带限制的会话获取"""
        sessions = vscode_manager.get_sessions(limit=5)
        assert isinstance(sessions, list)
        assert len(sessions) <= 5

    def test_get_sessions_with_status_filter(self, vscode_manager):
        """测试按状态筛选会话"""
        running = vscode_manager.get_sessions(status="running")
        assert isinstance(running, list)
        stopped = vscode_manager.get_sessions(status="stopped")
        assert isinstance(stopped, list)

    def test_get_session_by_pid(self, vscode_manager):
        """测试按 PID 获取会话"""
        # 先获取所有会话
        sessions = vscode_manager.get_sessions()
        if sessions and sessions[0].get("pid"):
            pid = sessions[0]["pid"]
            session = vscode_manager.get_session_by_pid(pid)
            if session:
                assert session.get("pid") == pid


# ==================== 打开/关闭测试 ====================

class TestOpenClose:
    """打开关闭功能测试"""

    def test_open_path_with_invalid_path(self, vscode_manager):
        """测试打开不存在的路径（应该返回失败但不崩溃）"""
        result = vscode_manager.open_path(path="/nonexistent/path/12345")
        assert isinstance(result, dict)
        assert "success" in result

    def test_close_with_invalid_pid(self, vscode_manager):
        """测试关闭不存在的 PID（应该返回失败但不崩溃）"""
        result = vscode_manager.close(pid=999999)
        assert isinstance(result, dict)
        assert "success" in result

    def test_close_without_pid(self, vscode_manager):
        """测试不传 PID 关闭（关闭全部）"""
        result = vscode_manager.close()
        assert isinstance(result, dict)
        assert "success" in result


# ==================== 进程管理测试 ====================

class TestProcesses:
    """进程管理测试"""

    def test_get_processes(self, vscode_manager):
        """测试获取进程列表"""
        procs = vscode_manager.get_processes()
        assert isinstance(procs, list)

    def test_get_running_processes_count(self, vscode_manager):
        """测试获取运行中的进程数"""
        status = vscode_manager.get_status()
        assert isinstance(status.get("running"), bool) or isinstance(status.get("running"), int)


# ==================== Mock 测试 ====================

class TestWithMock:
    """使用 Mock 的测试"""

    @patch('vscode_manager.subprocess.run')
    def test_get_version_mock_success(self, mock_run, vscode_manager):
        """模拟成功获取版本"""
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout="1.80.0\n"
        )
        result = vscode_manager.get_version()
        assert result["success"] is True
        assert "version" in result

    @patch('vscode_manager.subprocess.run')
    def test_get_version_mock_failure(self, mock_run, vscode_manager):
        """模拟获取版本失败"""
        mock_run.return_value = MagicMock(
            returncode=1,
            stderr="command not found"
        )
        result = vscode_manager.get_version()
        assert result["success"] is False


# ==================== 单例模式测试 ====================

class TestSingleton:
    """单例模式测试"""

    def test_same_instance(self):
        """测试单例模式返回同一实例"""
        m1 = get_vscode_manager()
        m2 = get_vscode_manager()
        assert m1 is m2


# ==================== 直接运行入口 ====================

if __name__ == "__main__":
    print("=" * 60)
    print("M9 VS Code 管理测试")
    print("=" * 60)

    # 使用 pytest 运行
    exit_code = pytest.main([__file__, "-v", "--tb=short"])
    sys.exit(exit_code)
