"""M2 技能集群 - 插件扩展.

动态加载外部 Skill 插件。
"""

from __future__ import annotations

from skill_cluster.extensions.plugins.loader import (
    PluginInfo,
    PluginLoadError,
    PluginLoader,
)

__all__ = ["PluginLoader", "PluginInfo", "PluginLoadError"]
