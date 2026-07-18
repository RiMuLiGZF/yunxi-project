"""
测试：PluginLoader 插件热加载系统
"""

import pytest
import sys
import asyncio
from pathlib import Path
from plugin_loader import PluginLoader, PluginLoadError
from agent_registry import AgentRegistry
from interfaces import AgentTask, AgentResult, IAgentPlugin


class TestPluginAgent(IAgentPlugin):
    agent_id: str = "agent.test_plugin"
    version: str = "1.0.0"
    capabilities: list[str] = ["test.capability"]

    async def handle_task(self, task: AgentTask) -> AgentResult:
        return AgentResult(
            task_id=task.task_id,
            agent_id=self.agent_id,
            status="success",
            output={"reply": "from plugin"},
        )


@pytest.fixture
def tmp_plugin_dir(tmp_path):
    return tmp_path / "plugins"


def test_scan_empty_dir(tmp_path):
    loader = PluginLoader(plugin_dir=str(tmp_path / "plugins"))
    files = loader.scan()
    assert len(files) == 0


def test_load_file(tmp_plugin_dir):
    tmp_plugin_dir.mkdir()
    plugin_file = tmp_plugin_dir / "test_agent.py"
    plugin_file.write_text("""
from interfaces import AgentTask, AgentResult, IAgentPlugin

class PluginAgent(IAgentPlugin):
    agent_id = "agent.from_plugin"
    version = "1.0.0"
    capabilities = ["plugin.capability"]

    async def handle_task(self, task: AgentTask) -> AgentResult:
        return AgentResult(task_id=task.task_id, agent_id=self.agent_id, status="success")
""")

    loader = PluginLoader(plugin_dir=str(tmp_plugin_dir))
    classes = loader.load_file(plugin_file)
    assert len(classes) == 1
    assert classes[0].agent_id == "agent.from_plugin"


def test_load_file_no_agent(tmp_plugin_dir):
    tmp_plugin_dir.mkdir()
    plugin_file = tmp_plugin_dir / "no_agent.py"
    plugin_file.write_text("x = 1")

    loader = PluginLoader(plugin_dir=str(tmp_plugin_dir))
    classes = loader.load_file(plugin_file)
    assert len(classes) == 0


@pytest.mark.asyncio
async def test_load_all(tmp_plugin_dir):
    tmp_plugin_dir.mkdir()
    plugin_file = tmp_plugin_dir / "my_agent.py"
    plugin_file.write_text("""
from interfaces import AgentTask, AgentResult, IAgentPlugin

class MyAgent(IAgentPlugin):
    agent_id = "agent.my_plugin"
    version = "1.0"
    capabilities = ["my.cap"]

    async def handle_task(self, task: AgentTask) -> AgentResult:
        return AgentResult(task_id=task.task_id, agent_id=self.agent_id, status="success")
""")

    registry = AgentRegistry()
    loader = PluginLoader(plugin_dir=str(tmp_plugin_dir))
    instances = await loader.load_all(registry)

    assert len(instances) == 1
    assert instances[0].agent_id == "agent.my_plugin"
    assert registry.get("agent.my_plugin") is not None


def test_stats(tmp_plugin_dir):
    loader = PluginLoader(plugin_dir=str(tmp_plugin_dir))
    stats = loader.stats()
    assert stats["loaded_files"] == 0
    assert stats["loaded_agents"] == 0
    assert stats["auto_reload"] is True


def test_list_loaded(tmp_plugin_dir):
    loader = PluginLoader(plugin_dir=str(tmp_plugin_dir))
    assert loader.list_loaded() == []
