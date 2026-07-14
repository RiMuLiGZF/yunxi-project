"""
技能接口测试

运行: python -m pytest tests/test_skill_interface.py -v
"""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from unittest.mock import MagicMock, patch

import pytest

from tide_memory.core.skill_interface import TideSkillInterface


class TestSkillInterfaceInit:
    """SkillInterface 初始化测试"""

    def test_init_stores_dependencies(self):
        """初始化时保存三个依赖组件"""
        mock_recall = MagicMock()
        mock_domain = MagicMock()
        mock_audit = MagicMock()

        iface = TideSkillInterface(mock_recall, mock_domain, mock_audit)

        assert iface._recall is mock_recall
        assert iface._domain is mock_domain
        assert iface._audit is mock_audit

    def test_init_empty_registered_agents(self):
        """初始化时已注册 Agent 集合为空"""
        iface = TideSkillInterface(MagicMock(), MagicMock(), MagicMock())
        assert len(iface._registered_agents) == 0

    def test_init_registers_agent_on_first_call(self):
        """首次 recall 调用自动注册 Agent"""
        mock_recall = MagicMock()
        mock_domain = MagicMock()
        mock_domain.check_permission.return_value = True
        mock_audit = MagicMock()
        mock_recall.search.return_value = []

        iface = TideSkillInterface(mock_recall, mock_domain, mock_audit)
        iface.recall("test query", permission_check={"agent_id": "agent-001"})

        mock_domain.register_agent.assert_called_once_with("agent-001")
        assert "agent-001" in iface._registered_agents


class TestSkillInterfaceRecall:
    """recall 方法测试"""

    def test_recall_permission_denied(self):
        """recall 权限拒绝时返回错误"""
        mock_recall = MagicMock()
        mock_domain = MagicMock()
        mock_domain.check_permission.return_value = False
        mock_audit = MagicMock()

        iface = TideSkillInterface(mock_recall, mock_domain, mock_audit)
        result = iface.recall(
            "test",
            permission_check={"agent_id": "a1", "domain": "private"},
        )

        assert result["success"] is False
        assert result["error"] == "permission_denied"
        assert result["results"] == []

    def test_recall_success(self):
        """recall 成功返回结果"""
        mock_recall = MagicMock()
        mock_recall.search.return_value = [
            {"memory_id": "mem_001", "content": "hello"},
        ]
        mock_domain = MagicMock()
        mock_domain.check_permission.return_value = True
        mock_audit = MagicMock()

        iface = TideSkillInterface(mock_recall, mock_domain, mock_audit)
        result = iface.recall(
            "hello world",
            permission_check={"agent_id": "a1", "domain": "private"},
        )

        assert result["success"] is True
        assert result["total"] == 1
        assert len(result["results"]) == 1

    def test_recall_uses_default_layers(self):
        """recall 未指定 layer_range 时使用默认值"""
        mock_recall = MagicMock()
        mock_recall.search.return_value = []
        mock_domain = MagicMock()
        mock_domain.check_permission.return_value = True
        mock_audit = MagicMock()

        iface = TideSkillInterface(mock_recall, mock_domain, mock_audit)
        iface.recall("test")

        call_kwargs = mock_recall.search.call_args
        assert call_kwargs[1]["layers"] == ["l1_shallow", "l2_deep"]


class TestSkillInterfaceArchive:
    """archive 方法测试"""

    def test_archive_permission_denied(self):
        """archive 权限拒绝"""
        mock_recall = MagicMock()
        mock_domain = MagicMock()
        mock_domain.check_permission.return_value = False
        mock_audit = MagicMock()

        iface = TideSkillInterface(mock_recall, mock_domain, mock_audit)
        result = iface.archive("content", agent_id="a1")

        assert result["success"] is False
        assert result["error"] == "permission_denied"

    def test_archive_success(self):
        """archive 成功返回 archive_id"""
        mock_recall = MagicMock()
        mock_recall.archive_memory.return_value = {
            "memory_id": "mem_new_001",
            "layer": "l1_shallow",
            "created_at": "2026-07-14T00:00:00",
        }
        mock_domain = MagicMock()
        mock_domain.check_permission.return_value = True
        mock_audit = MagicMock()

        iface = TideSkillInterface(mock_recall, mock_domain, mock_audit)
        result = iface.archive("hello world", agent_id="a1")

        assert result["success"] is True
        assert result["archive_id"] == "mem_new_001"
        assert result["layer"] == "l1_shallow"
        assert "content_hash" in result


class TestSkillInterfaceGetStats:
    """get_stats 方法测试"""

    def test_get_stats_delegates_to_recall(self):
        """get_stats 委托给 recall engine"""
        expected = {"total": 42, "by_layer": {}}
        mock_recall = MagicMock()
        mock_recall.get_stats.return_value = expected
        mock_domain = MagicMock()
        mock_audit = MagicMock()

        iface = TideSkillInterface(mock_recall, mock_domain, mock_audit)
        result = iface.get_stats(domain="private")

        mock_recall.get_stats.assert_called_once_with("private")
        assert result == expected


class TestNormalizeDomain:
    """_normalize_domain 测试"""

    def test_normalize_private_domain(self):
        """private 域自动拼接 agent_id"""
        iface = TideSkillInterface(MagicMock(), MagicMock(), MagicMock())
        result = iface._normalize_domain("private", "agent-001")
        assert result == "private:agent-001"

    def test_normalize_core_domain(self):
        """core 域保持不变"""
        iface = TideSkillInterface(MagicMock(), MagicMock(), MagicMock())
        result = iface._normalize_domain("core", "agent-001")
        assert result == "core"

    def test_normalize_shared_domain_unchanged(self):
        """shared:xxx 格式保持不变"""
        iface = TideSkillInterface(MagicMock(), MagicMock(), MagicMock())
        result = iface._normalize_domain("shared:team1", "agent-001")
        assert result == "shared:team1"