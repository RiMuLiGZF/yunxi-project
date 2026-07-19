"""
[DEPRECATED] OrchestratorV4 兼容存根

本文件已迁移至 src.orchestration._deprecated.orchestrator_v4
OrchestratorV4 是历史版本，已被 OrchestratorV8（稳定版）和 OrchestratorV9（最新版）替代。

为保持向后兼容，本文件继续从 _deprecated/ 重新导出 OrchestratorV4，
但直接导入会触发 DeprecationWarning。

推荐使用：
- from src.orchestration.orchestrator_v9 import OrchestratorV9  # 最新生产版
- from src.orchestration.orchestrator_v8 import OrchestratorV8  # 上一个稳定版

归档日期：2026-07-19
"""

from __future__ import annotations

import warnings

# 发出弃用警告
warnings.warn(
    "OrchestratorV4 已废弃并归档至 src.orchestration._deprecated.orchestrator_v4。"
    "请升级到 OrchestratorV9（生产版）或 OrchestratorV8（稳定版）。"
    "当前存根将在未来版本中移除。",
    DeprecationWarning,
    stacklevel=2,
)

from src.orchestration._deprecated.orchestrator_v4 import OrchestratorV4  # noqa: F401

__all__ = ["OrchestratorV4"]
