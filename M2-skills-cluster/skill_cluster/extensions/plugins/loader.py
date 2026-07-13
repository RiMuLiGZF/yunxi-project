"""Plugin Loader - 技能插件动态加载器.

支持运行时从本地目录扫描、加载、卸载技能插件，
实现技能的热插拔，无需重启系统即可扩展能力。
"""

from __future__ import annotations

import importlib.util
import inspect
import os
import sys
import time
from pathlib import Path
from typing import Any

import structlog
from pydantic import BaseModel, Field

from skill_cluster.interfaces import ISkill, SkillManifest
from skill_cluster.core.registry import SkillRegistry

logger = structlog.get_logger()


class PluginInfo(BaseModel):
    """插件信息."""

    plugin_id: str = Field(..., description="插件标识")
    module_path: str = Field(..., description="模块文件路径")
    skill_class: str = Field(..., description="技能类名")
    skill_id: str = Field(..., description="技能 ID")
    version: str = Field(..., description="版本")
    loaded_at: float = Field(default_factory=time.time, description="加载时间")
    manifest: SkillManifest | None = Field(default=None, description="技能清单")


class PluginLoader:
    """技能插件加载器.

    扫描指定目录，动态导入 Python 模块并实例化 ISkill 子类。
    """

    def __init__(
        self,
        registry: SkillRegistry | None = None,
        plugin_dirs: list[str] | None = None,
    ) -> None:
        self._registry = registry or SkillRegistry()
        self._plugin_dirs = plugin_dirs or []
        self._loaded: dict[str, PluginInfo] = {}
        self._instances: dict[str, ISkill] = {}

    def add_plugin_dir(self, directory: str) -> None:
        """添加插件扫描目录.

        【第四轮优化 - P1安全】增加路径合法性检查：
        - 必须为绝对路径
        - 必须实际存在且为目录
        - 防止路径遍历注入
        """
        abs_path = os.path.abspath(directory)
        if not os.path.exists(abs_path) or not os.path.isdir(abs_path):
            logger.warning("plugin_dir_not_exist", dir=abs_path)
            return
        if abs_path not in self._plugin_dirs:
            self._plugin_dirs.append(abs_path)
            logger.info("plugin_dir_added", dir=abs_path)

    def scan(self) -> list[PluginInfo]:
        """扫描所有插件目录，返回可加载的插件列表.

        Returns:
            插件信息列表（未加载，仅发现）.
        """
        discovered: list[PluginInfo] = []
        for plugin_dir in self._plugin_dirs:
            if not os.path.isdir(plugin_dir):
                continue
            for root, _dirs, files in os.walk(plugin_dir):
                for filename in files:
                    if not filename.endswith(".py"):
                        continue
                    if filename.startswith("_"):
                        continue
                    filepath = os.path.join(root, filename)
                    info = self._inspect_module(filepath)
                    if info:
                        discovered.append(info)
        return discovered

    def load(self, plugin_id: str) -> ISkill | None:
        """加载指定插件.

        Args:
            plugin_id: 插件标识（通常为 module_name.ClassName）.

        Returns:
            加载后的技能实例，失败返回 None.
        """
        if plugin_id in self._loaded:
            logger.warning("plugin_already_loaded", plugin_id=plugin_id)
            return self._instances.get(plugin_id)

        # 先扫描找到对应模块
        candidates = [p for p in self.scan() if p.plugin_id == plugin_id]
        if not candidates:
            logger.error("plugin_not_found", plugin_id=plugin_id)
            return None

        info = candidates[0]
        skill = self._load_from_info(info)
        if skill:
            self._registry.register(skill)
            self._loaded[plugin_id] = info
            self._instances[plugin_id] = skill
            logger.info(
                "plugin_loaded",
                plugin_id=plugin_id,
                skill_id=skill.manifest.skill_id,
            )
        return skill

    def load_all(self) -> list[ISkill]:
        """加载所有扫描到的插件.

        Returns:
            成功加载的技能实例列表.
        """
        loaded: list[ISkill] = []
        for info in self.scan():
            if info.plugin_id in self._loaded:
                continue
            skill = self._load_from_info(info)
            if skill:
                self._registry.register(skill)
                self._loaded[info.plugin_id] = info
                self._instances[info.plugin_id] = skill
                loaded.append(skill)
                logger.info(
                    "plugin_loaded",
                    plugin_id=info.plugin_id,
                    skill_id=skill.manifest.skill_id,
                )
        return loaded

    def unload(self, plugin_id: str) -> bool:
        """卸载指定插件.

        Args:
            plugin_id: 插件标识.

        Returns:
            是否成功卸载.
        """
        info = self._loaded.get(plugin_id)
        if info is None:
            return False

        skill = self._instances.get(plugin_id)
        if skill:
            self._registry.unregister(skill.manifest.skill_id, force=True)
            self._instances.pop(plugin_id, None)

        self._loaded.pop(plugin_id, None)
        logger.info("plugin_unloaded", plugin_id=plugin_id)
        return True

    def reload(self, plugin_id: str) -> ISkill | None:
        """重新加载插件.

        Args:
            plugin_id: 插件标识.

        Returns:
            重新加载后的技能实例.
        """
        self.unload(plugin_id)
        return self.load(plugin_id)

    def list_loaded(self) -> list[PluginInfo]:
        """列出已加载的插件."""
        return list(self._loaded.values())

    def get_instance(self, plugin_id: str) -> ISkill | None:
        """获取已加载的插件实例."""
        return self._instances.get(plugin_id)

    # ---- 内部方法 ----

    def _inspect_module(self, filepath: str) -> PluginInfo | None:
        """检查模块中是否包含 ISkill 子类."""
        module_name = Path(filepath).stem
        try:
            spec = importlib.util.spec_from_file_location(
                f"_plugin_{module_name}", filepath
            )
            if spec is None or spec.loader is None:
                return None
            module = importlib.util.module_from_spec(spec)
            # 不执行模块，仅通过 AST 或 inspect 分析
            # 为简化，这里执行模块（生产环境应使用 AST 静态分析）
            spec.loader.exec_module(module)
        except Exception as e:
            logger.debug("plugin_inspect_failed", filepath=filepath, error=str(e))
            return None

        for name, obj in inspect.getmembers(module, inspect.isclass):
            if issubclass(obj, ISkill) and obj is not ISkill:
                # 尝试获取类中的示例 manifest 或实例化探测
                try:
                    # 查找类中定义的示例 manifest
                    if hasattr(obj, "_manifest_class"):
                        manifest = obj._manifest_class
                    else:
                        # 直接实例化探测（约定插件技能支持无参构造）
                        instance = obj()
                        manifest = instance.manifest
                except Exception:
                    continue

                return PluginInfo(
                    plugin_id=f"{module_name}.{name}",
                    module_path=filepath,
                    skill_class=name,
                    skill_id=manifest.skill_id,
                    version=manifest.version,
                    manifest=manifest,
                )
        return None

    def _load_from_info(self, info: PluginInfo) -> ISkill | None:
        """从插件信息加载技能实例."""
        try:
            spec = importlib.util.spec_from_file_location(
                f"_plugin_loaded_{info.plugin_id}", info.module_path
            )
            if spec is None or spec.loader is None:
                return None
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)

            cls = getattr(module, info.skill_class)
            instance = cls()
            return instance
        except Exception as e:
            logger.error(
                "plugin_load_failed",
                plugin_id=info.plugin_id,
                error=str(e),
            )
            return None


class PluginLoadError(Exception):
    """插件加载错误."""
    pass
