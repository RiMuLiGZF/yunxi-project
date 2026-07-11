from __future__ import annotations

"""SkillPermissionManager 单元测试."""

import pytest

from skill_cluster.permissions import PermissionMatrix, SkillPermissionManager


@pytest.fixture
def pm(tmp_path) -> SkillPermissionManager:
    return SkillPermissionManager(config_dir=str(tmp_path / "config"))


def test_default_read_permission(pm: SkillPermissionManager) -> None:
    # 默认 read 权限
    assert pm.check("agent1", "skill.doc_proc", "read") is True
    assert pm.check("agent1", "skill.doc_proc", "write") is False


def test_tide_memory_default_none(pm: SkillPermissionManager) -> None:
    # tide_memory 默认 none
    assert pm.check("agent1", "skill.tide_memory", "read") is False


def test_grant_and_check(pm: SkillPermissionManager) -> None:
    pm.grant("agent1", "skill.doc_proc", "write", "admin")
    assert pm.check("agent1", "skill.doc_proc", "write") is True
    assert pm.check("agent1", "skill.doc_proc", "admin") is False


def test_grant_admin(pm: SkillPermissionManager) -> None:
    pm.grant("agent1", "skill.doc_proc", "admin", "admin")
    assert pm.check("agent1", "skill.doc_proc", "read") is True
    assert pm.check("agent1", "skill.doc_proc", "write") is True
    assert pm.check("agent1", "skill.doc_proc", "admin") is True


def test_revoke(pm: SkillPermissionManager) -> None:
    pm.grant("agent1", "skill.doc_proc", "write", "admin")
    pm.revoke("agent1", "skill.doc_proc")
    # 【第五轮优化】撤销后回退到 none（完全禁止），不再保留 read
    assert pm.check("agent1", "skill.doc_proc", "read") is False
    assert pm.check("agent1", "skill.doc_proc", "write") is False


def test_list_for_agent(pm: SkillPermissionManager) -> None:
    pm.grant("agent1", "skill.a", "write", "admin")
    pm.grant("agent1", "skill.b", "admin", "admin")
    perms = pm.list_for_agent("agent1")
    assert len(perms) == 2


def test_persistence(tmp_path) -> None:
    config_dir = str(tmp_path / "config")
    pm1 = SkillPermissionManager(config_dir=config_dir)
    pm1.grant("agent1", "skill.x", "write", "admin")

    pm2 = SkillPermissionManager(config_dir=config_dir)
    assert pm2.check("agent1", "skill.x", "write") is True
