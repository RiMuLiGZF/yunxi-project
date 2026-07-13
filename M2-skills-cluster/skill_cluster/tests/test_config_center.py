from __future__ import annotations

"""Config Center 单元测试."""

import asyncio
import os

import pytest

from skill_cluster.infrastructure.config_center import ConfigCenter


@pytest.fixture
def config_center(tmp_path) -> ConfigCenter:
    return ConfigCenter(config_dir=str(tmp_path / "config"))


def test_load_save(config_center: ConfigCenter) -> None:
    config_center.save("skill.test", {"timeout": 30, "retry": 3})
    data = config_center.load("skill.test")
    assert data["timeout"] == 30
    assert data["retry"] == 3


def test_get_set(config_center: ConfigCenter) -> None:
    config_center.save("skill.test", {"timeout": 30})
    assert config_center.get("skill.test", "timeout") == 30
    assert config_center.get("skill.test", "missing", 10) == 10

    config_center.set("skill.test", "timeout", 60)
    assert config_center.get("skill.test", "timeout") == 60


@pytest.mark.asyncio
async def test_subscribe_notify(config_center: ConfigCenter) -> None:
    changes: list[tuple[str, Any, Any]] = []

    async def handler(key: str, old: Any, new: Any) -> None:
        changes.append((key, old, new))

    await config_center.subscribe("skill.test", handler)
    config_center.save("skill.test", {"timeout": 30}, notify=True)

    # 给异步通知一点时间
    await asyncio.sleep(0.1)
    assert len(changes) == 1
    assert changes[0] == ("timeout", None, 30)


@pytest.mark.asyncio
async def test_set_notify(config_center: ConfigCenter) -> None:
    changes: list[tuple[str, Any, Any]] = []

    async def handler(key: str, old: Any, new: Any) -> None:
        changes.append((key, old, new))

    config_center.save("skill.test", {"timeout": 30})
    await config_center.subscribe("skill.test", handler)
    config_center.set("skill.test", "timeout", 60)

    await asyncio.sleep(0.1)
    assert len(changes) == 1
    assert changes[0] == ("timeout", 30, 60)


def test_diff(config_center: ConfigCenter) -> None:
    changes = ConfigCenter._diff(
        {"a": 1, "b": 2, "c": 3},
        {"a": 1, "b": 3, "d": 4},
    )
    assert "b" in changes
    assert changes["b"] == (2, 3)
    assert "c" in changes
    assert changes["c"] == (3, None)
    assert "d" in changes
    assert changes["d"] == (None, 4)


def test_list_configs(config_center: ConfigCenter) -> None:
    config_center.save("skill.a", {})
    config_center.save("skill.b", {})
    assert sorted(config_center.list_configs()) == ["skill.a", "skill.b"]


def test_load_missing(config_center: ConfigCenter) -> None:
    data = config_center.load("skill.missing")
    assert data == {}
