from __future__ import annotations

"""Skill Selection Strategy - 统一技能选择策略接口.

【第二轮优化 - P0-2 解决】
解决 AdaptiveRouter（epsilon-greedy 基于指标评分）与 SkillBanditRouter
（Thompson Sampling 基于Beta分布）的职责重叠问题。

设计思路：
- 抽象统一接口 ISkillSelectionStrategy
- AdaptiveRouterSelection 和 BanditSelection 分别适配
- CompositeSelection 支持策略组合（如先Bandit探索再Adaptive精细）
- SkillSelectionOrchestrator 作为门面，统一调度入口

参考：
- Strategy Pattern（GoF）
- CoCoMaMa（Contextual Combinatorial MAB Router, ECAI 2025）
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

import structlog

logger = structlog.get_logger()


@dataclass
class SelectionContext:
    """技能选择上下文.

    包含所有策略可能需要的环境信息，策略从中提取所需维度。
    """
    candidates: list[str] = field(default_factory=list)
    request_params: dict[str, Any] = field(default_factory=dict)
    agent_id: str = ""
    task_type: str = ""  # 如 "code_gen", "data_analysis", "search"
    urgency: float = 0.5  # 0=不紧急, 1=极紧急
    user_feedback: float | None = None  # 最近一次用户反馈评分


@dataclass
class SelectionResult:
    """选择结果."""
    skill_id: str
    strategy_name: str
    confidence: float = 0.0
    metadata: dict[str, Any] = field(default_factory=dict)


class SelectionStrategyType(Enum):
    """策略类型枚举."""
    ADAPTIVE = "adaptive"
    BANDIT = "bandit"
    COMPOSITE = "composite"
    ROUND_ROBIN = "round_robin"


class ISkillSelectionStrategy(ABC):
    """统一技能选择策略抽象接口.

    所有路由策略（Adaptive、Bandit、RoundRobin等）均实现此接口，
    实现策略热插拔和组合编排。
    """

    @property
    @abstractmethod
    def strategy_type(self) -> SelectionStrategyType: ...

    @property
    @abstractmethod
    def strategy_name(self) -> str: ...

    @abstractmethod
    def select(self, context: SelectionContext) -> SelectionResult | None: ...

    @abstractmethod
    def record_feedback(
        self,
        skill_id: str,
        success: bool,
        latency_ms: float = 0.0,
        context: SelectionContext | None = None,
    ) -> None: ...


class RoundRobinSelection(ISkillSelectionStrategy):
    """轮询策略（简单兜底）."""

    def __init__(self) -> None:
        self._index = 0

    @property
    def strategy_type(self) -> SelectionStrategyType:
        return SelectionStrategyType.ROUND_ROBIN

    @property
    def strategy_name(self) -> str:
        return "round_robin"

    def select(self, context: SelectionContext) -> SelectionResult | None:
        if not context.candidates:
            return None
        idx = self._index % len(context.candidates)
        self._index += 1
        return SelectionResult(
            skill_id=context.candidates[idx],
            strategy_name=self.strategy_name,
            confidence=1.0 / len(context.candidates),
        )

    def record_feedback(
        self,
        skill_id: str,
        success: bool,
        latency_ms: float = 0.0,
        context: SelectionContext | None = None,
    ) -> None:
        pass  # 轮询策略无需反馈


class AdaptiveSelection(ISkillSelectionStrategy):
    """适配 AdaptiveRouter 的策略包装.

    将 AdaptiveRouter 的 epsilon-greedy 选择逻辑适配到统一接口。
    """

    def __init__(self, adaptive_router: Any) -> None:
        from skill_cluster.adaptive_router import AdaptiveRouter
        if not isinstance(adaptive_router, AdaptiveRouter):
            raise TypeError("adaptive_router must be an AdaptiveRouter instance")
        self._router = adaptive_router

    @property
    def strategy_type(self) -> SelectionStrategyType:
        return SelectionStrategyType.ADAPTIVE

    @property
    def strategy_name(self) -> str:
        return "adaptive_score"

    def select(self, context: SelectionContext) -> SelectionResult | None:
        if not context.candidates:
            return None
        selected = self._router.select_skill(context.candidates)
        if selected is None:
            return None
        metrics = self._router.get_metrics(selected)
        confidence = metrics.score if metrics else 0.5
        return SelectionResult(
            skill_id=selected,
            strategy_name=self.strategy_name,
            confidence=round(confidence, 4),
        )

    def record_feedback(
        self,
        skill_id: str,
        success: bool,
        latency_ms: float = 0.0,
        context: SelectionContext | None = None,
    ) -> None:
        # AdaptiveRouter 通过 invoke() 自动记录，此处为手动反馈入口
        if skill_id in self._router._metrics:
            self._router._metrics[skill_id].record_call(
                latency_ms, success, None if success else "manual_feedback"
            )


class BanditSelection(ISkillSelectionStrategy):
    """适配 SkillBanditRouter 的策略包装.

    将 SkillBanditRouter 的 Thompson Sampling 逻辑适配到统一接口。
    【第二轮优化】增加上下文感知奖励：结合 success、latency、user_feedback。
    """

    def __init__(self, bandit_router: Any) -> None:
        from skill_cluster.skill_bandit_router import SkillBanditRouter
        if not isinstance(bandit_router, SkillBanditRouter):
            raise TypeError("bandit_router must be a SkillBanditRouter instance")
        self._router = bandit_router

    @property
    def strategy_type(self) -> SelectionStrategyType:
        return SelectionStrategyType.BANDIT

    @property
    def strategy_name(self) -> str:
        return "bandit_thompson"

    def select(self, context: SelectionContext) -> SelectionResult | None:
        if not context.candidates:
            return None

        # 【第三轮优化】urgency 调制 explore_rate：
        # 紧急任务降低探索概率，优先利用已知最优技能
        original_rate = self._router._explore_rate
        if context.urgency > 0.7:
            self._router._explore_rate = max(0.0, original_rate * 0.3)
        elif context.urgency < 0.3:
            self._router._explore_rate = min(1.0, original_rate * 1.5)

        # Bandit 使用 (skill_id, action) 元组
        candidates = [(sid, "default") for sid in context.candidates]
        sid, _act = self._router.select(candidates)

        # 恢复原始 explore_rate
        self._router._explore_rate = original_rate

        arm_stats = self._router.get_arm_stats(sid, "default")
        confidence = arm_stats.get("success_rate", 0.5)
        return SelectionResult(
            skill_id=sid,
            strategy_name=self.strategy_name,
            confidence=round(confidence, 4),
            metadata={"urgency": context.urgency, "explore_rate": original_rate},
        )

    def record_feedback(
        self,
        skill_id: str,
        success: bool,
        latency_ms: float = 0.0,
        context: SelectionContext | None = None,
    ) -> None:
        self._router.record(skill_id, "default", success, latency_ms)


class CompositeSelection(ISkillSelectionStrategy):
    """组合策略：按优先级链式尝试多个策略.

    例如：先用 Bandit 做探索-利用选择，若置信度过低则降级到 Adaptive。

    【第二轮优化 - 创新】参考 CoCoMaMa 组合路由思想：
    - 主策略 + 降级策略
    - confidence_threshold 控制降级触发
    """

    def __init__(
        self,
        strategies: list[ISkillSelectionStrategy],
        confidence_threshold: float = 0.3,
    ) -> None:
        if not strategies:
            raise ValueError("At least one strategy required")
        self._strategies = strategies
        self._confidence_threshold = confidence_threshold

    @property
    def strategy_type(self) -> SelectionStrategyType:
        return SelectionStrategyType.COMPOSITE

    @property
    def strategy_name(self) -> str:
        parts = [s.strategy_name for s in self._strategies]
        return "composite(" + "+".join(parts) + ")"

    def select(self, context: SelectionContext) -> SelectionResult | None:
        for strategy in self._strategies:
            result = strategy.select(context)
            if result is not None and result.confidence >= self._confidence_threshold:
                result.strategy_name = self.strategy_name
                result.metadata["delegated_to"] = strategy.strategy_name
                return result
        # 所有策略置信度都低于阈值，使用第一个策略的结果
        first_result = self._strategies[0].select(context)
        if first_result is not None:
            first_result.strategy_name = self.strategy_name
            first_result.metadata["fallback"] = True
        return first_result

    def record_feedback(
        self,
        skill_id: str,
        success: bool,
        latency_ms: float = 0.0,
        context: SelectionContext | None = None,
    ) -> None:
        # 向所有策略广播反馈
        for strategy in self._strategies:
            strategy.record_feedback(skill_id, success, latency_ms, context)


class SkillSelectionOrchestrator:
    """技能选择编排器（门面模式）.

    统一入口，管理策略注册、切换、组合。
    支持运行时策略热插拔（不中断当前调用）。
    """

    def __init__(
        self,
        default_strategy: ISkillSelectionStrategy | None = None,
    ) -> None:
        self._strategies: dict[str, ISkillSelectionStrategy] = {}
        self._active_strategy_name: str = ""
        if default_strategy:
            self.register_strategy(default_strategy)
            self._active_strategy_name = default_strategy.strategy_name

    def register_strategy(self, strategy: ISkillSelectionStrategy) -> None:
        """注册策略."""
        self._strategies[strategy.strategy_name] = strategy
        logger.info(
            "selection_strategy_registered",
            name=strategy.strategy_name,
            type=strategy.strategy_type.value,
        )

    def switch_strategy(self, strategy_name: str) -> bool:
        """切换活跃策略（热插拔）."""
        if strategy_name not in self._strategies:
            return False
        old = self._active_strategy_name
        self._active_strategy_name = strategy_name
        logger.info(
            "selection_strategy_switched",
            old=old, new=strategy_name,
        )
        return True

    def select(
        self,
        candidates: list[str],
        context_extra: dict[str, Any] | None = None,
    ) -> SelectionResult | None:
        """统一选择入口."""
        if not self._active_strategy_name:
            return None
        strategy = self._strategies.get(self._active_strategy_name)
        if strategy is None:
            return None
        context = SelectionContext(
            candidates=candidates,
            **(context_extra or {}),
        )
        return strategy.select(context)

    def record_feedback(
        self,
        skill_id: str,
        success: bool,
        latency_ms: float = 0.0,
    ) -> None:
        """记录执行反馈."""
        if not self._active_strategy_name:
            return
        strategy = self._strategies.get(self._active_strategy_name)
        if strategy:
            strategy.record_feedback(skill_id, success, latency_ms)

    def get_active_strategy(self) -> str:
        return self._active_strategy_name

    def list_strategies(self) -> list[dict[str, str]]:
        return [
            {
                "name": s.strategy_name,
                "type": s.strategy_type.value,
                "active": s.strategy_name == self._active_strategy_name,
            }
            for s in self._strategies.values()
        ]
