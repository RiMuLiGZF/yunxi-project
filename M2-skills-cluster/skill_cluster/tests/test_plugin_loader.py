from __future__ import annotations

import os
import tempfile

import pytest

from skill_cluster.plugin_loader import PluginInfo, PluginLoader
from skill_cluster.skill_registry import SkillRegistry


def _write_plugin_file(directory: str, filename: str, code: str) -> str:
    path = os.path.join(directory, filename)
    with open(path, "w") as f:
        f.write(code)
    return path


@pytest.fixture
def plugin_dir() -> str:
    return tempfile.mkdtemp(prefix="plugins_")


@pytest.fixture
def loader(plugin_dir: str) -> PluginLoader:
    reg = SkillRegistry()
    pl = PluginLoader(registry=reg, plugin_dirs=[plugin_dir])
    return pl


def test_scan_empty(loader: PluginLoader) -> None:
    results = loader.scan()
    assert results == []


def test_scan_finds_skill(loader: PluginLoader, plugin_dir: str) -> None:
    code = '''
from skill_cluster.interfaces import ISkill, SkillManifest

class TestSkill(ISkill):
    def __init__(self):
        self._manifest = SkillManifest(
            skill_id="skill.test_plugin",
            name="TestPlugin",
            version="0.0.1",
            description="A test plugin",
            author="test",
            entrypoint="TestSkill",
        )

    @property
    def manifest(self):
        return self._manifest

    async def invoke(self, request):
        return None

    async def health(self):
        return {"healthy": True}

    async def configure(self, config):
        pass
'''
    _write_plugin_file(plugin_dir, "test_skill.py", code)
    results = loader.scan()
    assert len(results) == 1
    assert results[0].skill_id == "skill.test_plugin"
    assert results[0].skill_class == "TestSkill"


def test_scan_ignores_private(loader: PluginLoader, plugin_dir: str) -> None:
    _write_plugin_file(plugin_dir, "_private.py", "x = 1")
    results = loader.scan()
    assert len(results) == 0


def test_scan_ignores_non_python(loader: PluginLoader, plugin_dir: str) -> None:
    _write_plugin_file(plugin_dir, "readme.txt", "hello")
    results = loader.scan()
    assert len(results) == 0


def test_load_and_get_instance(loader: PluginLoader, plugin_dir: str) -> None:
    code = '''
from skill_cluster.interfaces import ISkill, SkillManifest

class DemoSkill(ISkill):
    def __init__(self):
        self._manifest = SkillManifest(
            skill_id="skill.demo",
            name="Demo",
            version="1.0.0",
            description="Demo",
            author="test",
            entrypoint="DemoSkill",
        )

    @property
    def manifest(self):
        return self._manifest

    async def invoke(self, request):
        return None

    async def health(self):
        return {"ok": True}

    async def configure(self, config):
        pass
'''
    _write_plugin_file(plugin_dir, "demo.py", code)
    skill = loader.load("demo.DemoSkill")
    assert skill is not None
    assert skill.manifest.skill_id == "skill.demo"
    assert loader.get_instance("demo.DemoSkill") is skill


def test_load_all(loader: PluginLoader, plugin_dir: str) -> None:
    code1 = '''
from skill_cluster.interfaces import ISkill, SkillManifest
class SkillA(ISkill):
    def __init__(self):
        self._manifest = SkillManifest(
            skill_id="skill.a", name="A", version="1.0.0",
            description="A", author="t", entrypoint="SkillA",
        )
    @property
    def manifest(self): return self._manifest
    async def invoke(self, request): return None
    async def health(self): return {}
    async def configure(self, config): pass
'''
    code2 = '''
from skill_cluster.interfaces import ISkill, SkillManifest
class SkillB(ISkill):
    def __init__(self):
        self._manifest = SkillManifest(
            skill_id="skill.b", name="B", version="1.0.0",
            description="B", author="t", entrypoint="SkillB",
        )
    @property
    def manifest(self): return self._manifest
    async def invoke(self, request): return None
    async def health(self): return {}
    async def configure(self, config): pass
'''
    _write_plugin_file(plugin_dir, "skill_a.py", code1)
    _write_plugin_file(plugin_dir, "skill_b.py", code2)
    loaded = loader.load_all()
    assert len(loaded) == 2
    ids = {s.manifest.skill_id for s in loaded}
    assert ids == {"skill.a", "skill.b"}


def test_unload(loader: PluginLoader, plugin_dir: str) -> None:
    code = '''
from skill_cluster.interfaces import ISkill, SkillManifest
class TempSkill(ISkill):
    def __init__(self):
        self._manifest = SkillManifest(
            skill_id="skill.temp", name="Temp", version="1.0.0",
            description="Temp", author="t", entrypoint="TempSkill",
        )
    @property
    def manifest(self): return self._manifest
    async def invoke(self, request): return None
    async def health(self): return {}
    async def configure(self, config): pass
'''
    _write_plugin_file(plugin_dir, "temp.py", code)
    skill = loader.load("temp.TempSkill")
    assert skill is not None
    ok = loader.unload("temp.TempSkill")
    assert ok is True
    assert loader.get_instance("temp.TempSkill") is None


def test_reload(loader: PluginLoader, plugin_dir: str) -> None:
    code = '''
from skill_cluster.interfaces import ISkill, SkillManifest
class ReloadSkill(ISkill):
    def __init__(self):
        self._manifest = SkillManifest(
            skill_id="skill.reload", name="Reload", version="1.0.0",
            description="Reload", author="t", entrypoint="ReloadSkill",
        )
    @property
    def manifest(self): return self._manifest
    async def invoke(self, request): return None
    async def health(self): return {}
    async def configure(self, config): pass
'''
    _write_plugin_file(plugin_dir, "reload.py", code)
    skill1 = loader.load("reload.ReloadSkill")
    assert skill1 is not None
    skill2 = loader.reload("reload.ReloadSkill")
    assert skill2 is not None
    assert skill2.manifest.skill_id == "skill.reload"


def test_list_loaded(loader: PluginLoader, plugin_dir: str) -> None:
    code = '''
from skill_cluster.interfaces import ISkill, SkillManifest
class ListSkill(ISkill):
    def __init__(self):
        self._manifest = SkillManifest(
            skill_id="skill.list", name="List", version="2.0.0",
            description="List", author="t", entrypoint="ListSkill",
        )
    @property
    def manifest(self): return self._manifest
    async def invoke(self, request): return None
    async def health(self): return {}
    async def configure(self, config): pass
'''
    _write_plugin_file(plugin_dir, "list_skill.py", code)
    loader.load("list_skill.ListSkill")
    loaded = loader.list_loaded()
    assert len(loaded) == 1
    assert loaded[0].version == "2.0.0"


def test_load_not_found(loader: PluginLoader) -> None:
    result = loader.load("nonexistent.Foo")
    assert result is None


def test_unload_not_loaded(loader: PluginLoader) -> None:
    ok = loader.unload("nonexistent.Foo")
    assert ok is False
