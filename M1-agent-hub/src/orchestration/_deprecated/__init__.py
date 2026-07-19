"""
已废弃的 Orchestrator 历史版本归档。

本目录包含 M1 Agent 集群编排器的历史版本（v2/v3/v4/v5/v7），
这些版本已被 v8/v9 替代，仅作为内部依赖链和向后兼容保留。

请勿在新代码中直接使用这些版本。推荐使用：
- OrchestratorV9（当前生产版）
- OrchestratorV8（上一个稳定版，回滚备选）

归档日期：2026-07-19
归档版本：v2, v3, v4, v5, v7
保留版本：v8（稳定）, v9（最新）
"""

__all__ = [
    "orchestrator_v2",
    "orchestrator_v3",
    "orchestrator_v4",
    "orchestrator_v5",
    "orchestrator_v7",
]
