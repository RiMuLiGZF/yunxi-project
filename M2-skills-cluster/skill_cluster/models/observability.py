"""M2 技能集群 - 可观测性模型.

包含指标、追踪、事件等可观测性相关的数据模型。

注意：
    当前指标样本（MetricSample）、追踪 Span/Chain（TraceSpan, TraceChain）
    使用 dataclass 定义在 ``metrics.py`` 和 ``trace_aggregator.py`` 中，
    事件（SkillEvent）使用普通类定义在 ``event_bus.py`` 中。

    本模块预留作为可观测性模型的统一入口，后续可将 dataclass 模型
    逐步迁移为 Pydantic 模型以获得更好的序列化与校验能力。
"""

from __future__ import annotations

# 当前可观测性相关的数据结构使用 dataclass / 普通类定义，
# 未使用 Pydantic BaseModel，因此暂无可迁移的 Pydantic 模型。
# 此处预留模块位置，保持目录结构完整性。

__all__: list[str] = []
