"""路由决策引擎.

根据任务复杂度、隐私等级、显存状态、成本控制和响应速度要求等因素，
通过加权评分模型决定推理请求走本地（local）还是云端（cloud）。
支持强制本地/云端模式，以及混合（hybrid）路由策略。
"""

from __future__ import annotations

import re
from enum import Enum
from typing import Any

import structlog

from edge_cloud_kernel.models.exceptions import RouteError
from edge_cloud_kernel.models.vram_report import VRAMLevel

logger = structlog.get_logger(__name__)

# 默认权重配置
DEFAULT_WEIGHTS: dict[str, float] = {
    "complexity": 0.30,
    "privacy": 0.25,
    "vram": 0.20,
    "cost": 0.15,
    "speed": 0.10,
}

# 默认本地模型映射
DEFAULT_LOCAL_MODEL_MAP: dict[str, str] = {
    "simple": "qwen2.5:1.5b",
    "medium": "qwen2.5:3b",
    "complex": "qwen2.5:7b",
}

# 默认路由模式
DEFAULT_ROUTE: str = "auto"

# 默认成本预算
DEFAULT_COST_BUDGET: str = "normal"

# 复杂度关键词表
COMPLEX_KEYWORDS: list[str] = [
    # 代码相关
    "代码", "编程", "函数", "算法", "调试", "bug", "重构", "优化",
    "实现", "开发", "架构", "设计模式", "接口", "api",
    # 逻辑推理
    "推理", "分析", "证明", "推导", "论证", "比较", "评估",
    "为什么", "如何", "怎么", "原理", "机制",
    # 长文写作
    "写一篇", "撰写", "报告", "论文", "文章", "故事", "小说",
    "总结", "归纳", "翻译",
    # 数学/科学
    "计算", "数学", "公式", "方程", "统计", "数据",
]

SIMPLE_KEYWORDS: list[str] = [
    "你好", "hi", "hello", "谢谢", "再见", "天气", "时间",
    "几点", "今天", "明天", "星期", "打招呼", "问好",
]


class PrivacyLevel(str, Enum):
    """隐私等级枚举.

    Attributes:
        TOP_SECRET: 绝密，必须本地处理.
        CONFIDENTIAL: 机密，必须本地处理.
        INTERNAL: 内部，优先本地.
        PUBLIC: 公开，可云端处理.
    """

    TOP_SECRET = "top_secret"
    CONFIDENTIAL = "confidential"
    INTERNAL = "internal"
    PUBLIC = "public"


class UrgencyLevel(str, Enum):
    """响应速度要求等级.

    Attributes:
        LOW: 不着急，可云端处理.
        NORMAL: 正常.
        HIGH: 需要快速响应，优先本地.
        URGENT: 极其紧急，必须本地.
    """

    LOW = "low"
    NORMAL = "normal"
    HIGH = "high"
    URGENT = "urgent"


class TaskComplexity(str, Enum):
    """任务复杂度等级.

    Attributes:
        SIMPLE: 简单任务，小模型可处理.
        MEDIUM: 中等任务，中等模型.
        COMPLEX: 复杂任务，大模型或云端.
    """

    SIMPLE = "simple"
    MEDIUM = "medium"
    COMPLEX = "complex"


class RouteDecisionEngine:
    """路由决策引擎.

    通过多因子加权评分模型决定推理请求的路由目标。
    决策因子包括：任务复杂度、隐私等级、显存状态、成本控制、响应速度。

    评分规则：
        - 每个因子输出 0.0-1.0 的「本地倾向分」
        - 加权求和得到总分（0.0-1.0）
        - 总分 > 0.6 → 走本地（local）
        - 总分 < 0.4 → 走云端（cloud）
        - 0.4-0.6 之间 → 混合模式（hybrid，优先本地，失败自动降级）

    Attributes:
        _default_route: 默认路由模式（auto/local/cloud）.
        _weights: 各决策因子权重.
        _local_model_map: 任务复杂度到本地模型的映射.
        _cost_budget: 成本预算等级.
        _vram_monitor: 显存监控器实例.
        _force_local_agents: 强制本地的 agent 集合.
        _force_cloud_agents: 强制云端的 agent 集合.
    """

    def __init__(
        self,
        config: dict[str, Any] | None = None,
        vram_monitor: Any = None,
    ) -> None:
        """初始化 RouteDecisionEngine.

        Args:
            config: 配置字典，支持 default_route / weights /
                local_model_map / cost_budget.
            vram_monitor: VRAMMonitor 实例，用于实时显存检查.
        """
        cfg = config or {}
        self._default_route: str = cfg.get("default_route", DEFAULT_ROUTE)
        self._weights: dict[str, float] = dict(cfg.get("weights", DEFAULT_WEIGHTS))
        self._local_model_map: dict[str, str] = dict(
            cfg.get("local_model_map", DEFAULT_LOCAL_MODEL_MAP)
        )
        self._cost_budget: str = cfg.get("cost_budget", DEFAULT_COST_BUDGET)
        self._vram_monitor = vram_monitor

        # 强制路由的 agent 记录
        self._force_local_agents: dict[str, str] = {}  # agent_id -> reason
        self._force_cloud_agents: dict[str, str] = {}  # agent_id -> reason

        # 权重归一化（确保总和为 1.0）
        total_weight = sum(self._weights.values())
        if total_weight > 0 and abs(total_weight - 1.0) > 0.001:
            self._weights = {k: v / total_weight for k, v in self._weights.items()}

        logger.info(
            "route_engine.init",
            default_route=self._default_route,
            weights=self._weights,
            local_model_map=self._local_model_map,
            cost_budget=self._cost_budget,
            has_vram_monitor=vram_monitor is not None,
        )

    # ------------------------------------------------------------------
    # 核心决策方法
    # ------------------------------------------------------------------

    def decide(
        self,
        text: str = "",
        task_type: str | None = None,
        privacy_level: str = "internal",
        urgency: str = "normal",
        agent_id: str | None = None,
    ) -> dict[str, Any]:
        """路由决策.

        根据输入文本和上下文信息，决定请求走本地还是云端。

        Args:
            text: 输入文本（用于复杂度分析）.
            task_type: 任务类型，如 chat / code / summary / analysis 等.
            privacy_level: 隐私等级（top_secret/confidential/internal/public）.
            urgency: 响应速度要求（low/normal/high/urgent）.
            agent_id: 调用方 Agent 标识，用于检查强制路由.

        Returns:
            路由决策字典，包含：
            - route: "local" / "cloud" / "hybrid"
            - reason: 决策理由说明
            - confidence: 决策置信度（0.0-1.0）
            - model: 推荐使用的模型名称
            - provider: 推荐的云端 Provider（云端时），本地时为 None
            - scores: 各因子的评分明细

        Raises:
            RouteError: 决策过程出错.
        """
        try:
            # Step 1: 检查强制路由
            if agent_id and agent_id in self._force_local_agents:
                reason = self._force_local_agents[agent_id] or "forced local by policy"
                complexity = self._assess_complexity(text, task_type).value
                return {
                    "route": "local",
                    "reason": f"Force local: {reason}",
                    "confidence": 1.0,
                    "model": self.get_local_model_for_task(complexity, self._get_vram_level()),
                    "provider": None,
                    "scores": {},
                }

            if agent_id and agent_id in self._force_cloud_agents:
                reason = self._force_cloud_agents[agent_id] or "forced cloud by policy"
                return {
                    "route": "cloud",
                    "reason": f"Force cloud: {reason}",
                    "confidence": 1.0,
                    "model": "",
                    "provider": self.get_cloud_provider_for_task(task_type),
                    "scores": {},
                }

            # Step 2: 检查默认路由模式
            if self._default_route == "local":
                complexity = self._assess_complexity(text, task_type).value
                return {
                    "route": "local",
                    "reason": "Default route is local",
                    "confidence": 0.9,
                    "model": self.get_local_model_for_task(complexity, self._get_vram_level()),
                    "provider": None,
                    "scores": {},
                }

            if self._default_route == "cloud":
                return {
                    "route": "cloud",
                    "reason": "Default route is cloud",
                    "confidence": 0.9,
                    "model": "",
                    "provider": self.get_cloud_provider_for_task(task_type),
                    "scores": {},
                }

            # Step 3: 多因子加权评分
            scores: dict[str, float] = {}

            # 因子 1: 任务复杂度（越高越倾向云端，即本地倾向分越低）
            complexity_score = self._score_complexity(text, task_type)
            scores["complexity"] = complexity_score

            # 因子 2: 隐私等级（越高越倾向本地）
            privacy_score = self._score_privacy(privacy_level)
            scores["privacy"] = privacy_score

            # 隐私等级为最高级时，强制本地
            privacy_enum = self._parse_privacy(privacy_level)
            if privacy_enum in (PrivacyLevel.TOP_SECRET, PrivacyLevel.CONFIDENTIAL):
                complexity = self._assess_complexity(text, task_type).value
                return {
                    "route": "local",
                    "reason": f"Privacy level '{privacy_level}' requires local processing",
                    "confidence": 1.0,
                    "model": self.get_local_model_for_task(complexity, self._get_vram_level()),
                    "provider": None,
                    "scores": scores,
                }

            # 因子 3: 显存状态（越充足越倾向本地）
            vram_score = self._score_vram()
            scores["vram"] = vram_score

            # 显存 CRITICAL 时，强制云端
            vram_level = self._get_vram_level()
            if vram_level == VRAMLevel.CRITICAL:
                return {
                    "route": "cloud",
                    "reason": "VRAM is critical, forcing cloud inference",
                    "confidence": 1.0,
                    "model": "",
                    "provider": self.get_cloud_provider_for_task(task_type),
                    "scores": scores,
                }

            # 因子 4: 成本控制（预算越紧张越倾向本地）
            cost_score = self._score_cost()
            scores["cost"] = cost_score

            # 因子 5: 响应速度要求（越紧急越倾向本地）
            speed_score = self._score_speed(urgency)
            scores["speed"] = speed_score

            # 紧急情况强制本地
            urgency_enum = self._parse_urgency(urgency)
            if urgency_enum == UrgencyLevel.URGENT:
                complexity = self._assess_complexity(text, task_type).value
                return {
                    "route": "local",
                    "reason": "Urgent request, forcing local for low latency",
                    "confidence": 0.95,
                    "model": self.get_local_model_for_task(complexity, vram_level),
                    "provider": None,
                    "scores": scores,
                }

            # Step 4: 加权求和
            total_score = 0.0
            for factor, weight in self._weights.items():
                total_score += scores.get(factor, 0.0) * weight

            # Step 5: 根据总分决定路由
            complexity = self._assess_complexity(text, task_type).value
            local_model = self.get_local_model_for_task(complexity, vram_level)
            cloud_provider = self.get_cloud_provider_for_task(task_type)

            # 置信度：离阈值越远置信度越高
            if total_score >= 0.6:
                confidence = min(1.0, (total_score - 0.5) * 2.5)
                route = "local"
                reason = self._build_reason("local", scores, total_score)
            elif total_score <= 0.4:
                confidence = min(1.0, (0.5 - total_score) * 2.5)
                route = "cloud"
                reason = self._build_reason("cloud", scores, total_score)
            else:
                # 模糊地带 → hybrid 模式
                confidence = 0.5
                route = "hybrid"
                reason = (
                    f"Balanced factors (score={total_score:.2f}), "
                    "use hybrid mode: try local first, fallback to cloud"
                )

            result = {
                "route": route,
                "reason": reason,
                "confidence": round(confidence, 3),
                "model": local_model if route != "cloud" else "",
                "provider": cloud_provider if route != "local" else None,
                "scores": {k: round(v, 3) for k, v in scores.items()},
                "total_score": round(total_score, 3),
            }

            logger.debug(
                "route_engine.decide",
                route=route,
                total_score=round(total_score, 3),
                confidence=round(confidence, 3),
                task_type=task_type,
                privacy=privacy_level,
                urgency=urgency,
                agent_id=agent_id,
            )

            return result

        except Exception as e:
            logger.exception("route_engine.decide_error")
            raise RouteError(
                message=f"Route decision failed: {e}",
                error_code="ROUTE_DECISION_ERROR",
                context={"error": str(e)},
            ) from e

    # ------------------------------------------------------------------
    # 模型/Provider 选择
    # ------------------------------------------------------------------

    def get_local_model_for_task(
        self,
        task_type: str | None = None,
        vram_level: VRAMLevel | None = None,
    ) -> str:
        """根据任务类型和显存状态选择合适的本地模型.

        选择策略：
        - SAFE 水位：按任务复杂度选模型
        - WARNING 水位：降级使用小一档模型
        - CRITICAL 水位：返回空（不应选本地）

        Args:
            task_type: 任务类型或复杂度等级（simple/medium/complex）.
            vram_level: 显存水位线级别.

        Returns:
            推荐的本地模型名称.
        """
        if vram_level is None:
            vram_level = self._get_vram_level()

        # 评估复杂度
        if task_type in ("simple", "medium", "complex"):
            complexity = TaskComplexity(task_type)
        else:
            complexity = self._assess_complexity("", task_type)

        # 显存不足时降级
        model_key = complexity.value
        if vram_level == VRAMLevel.WARNING:
            if model_key == "complex":
                model_key = "medium"
            elif model_key == "medium":
                model_key = "simple"

        return self._local_model_map.get(model_key, self._local_model_map.get("medium", "qwen2.5:3b"))

    def get_cloud_provider_for_task(self, task_type: str | None = None) -> str | None:
        """根据任务类型选择云端 Provider.

        当前实现返回 None（由执行器按优先级自动选择），
        未来可扩展为根据任务类型选择特定 Provider。

        Args:
            task_type: 任务类型.

        Returns:
            推荐的 Provider 名称，None 表示自动选择.
        """
        # 预留：根据 task_type 映射到特定 provider
        # 例：代码任务 → deepseek-coder，通用对话 → qwen-plus
        if task_type in ("code", "coding", "编程", "代码"):
            # 可配置特定的代码模型 provider
            return None

        return None  # 自动选择优先级最高的可用 provider

    # ------------------------------------------------------------------
    # 强制路由控制
    # ------------------------------------------------------------------

    def force_local(self, agent_id: str | None = None, reason: str | None = None) -> None:
        """强制本地模式.

        用于高隐私场景，指定 agent 的所有请求强制走本地推理。

        Args:
            agent_id: Agent 标识，为 None 时设置全局默认路由为 local.
            reason: 强制原因说明.
        """
        if agent_id is None:
            self._default_route = "local"
            logger.warning("route_engine.force_local_global", reason=reason or "")
            return

        self._force_local_agents[agent_id] = reason or "policy"
        logger.warning(
            "route_engine.force_local_agent",
            agent_id=agent_id,
            reason=reason or "",
        )

    def force_cloud(self, agent_id: str | None = None, reason: str | None = None) -> None:
        """强制云端模式.

        用于显存不足或需要更强能力的场景。

        Args:
            agent_id: Agent 标识，为 None 时设置全局默认路由为 cloud.
            reason: 强制原因说明.
        """
        if agent_id is None:
            self._default_route = "cloud"
            logger.warning("route_engine.force_cloud_global", reason=reason or "")
            return

        self._force_cloud_agents[agent_id] = reason or "policy"
        logger.warning(
            "route_engine.force_cloud_agent",
            agent_id=agent_id,
            reason=reason or "",
        )

    def clear_force(self, agent_id: str | None = None) -> None:
        """清除强制路由设置.

        Args:
            agent_id: Agent 标识，为 None 时恢复全局 auto 模式.
        """
        if agent_id is None:
            self._default_route = "auto"
            self._force_local_agents.clear()
            self._force_cloud_agents.clear()
            logger.info("route_engine.clear_force_all")
            return

        self._force_local_agents.pop(agent_id, None)
        self._force_cloud_agents.pop(agent_id, None)
        logger.info("route_engine.clear_force_agent", agent_id=agent_id)

    # ------------------------------------------------------------------
    # 内部方法：各因子评分
    # ------------------------------------------------------------------

    def _score_complexity(self, text: str, task_type: str | None = None) -> float:
        """任务复杂度评分（本地倾向分）.

        越简单的任务，本地倾向分越高（越适合本地）。
        越复杂的任务，本地倾向分越低（越适合云端）。

        Args:
            text: 输入文本.
            task_type: 任务类型.

        Returns:
            本地倾向分（0.0-1.0），越高越适合本地.
        """
        complexity = self._assess_complexity(text, task_type)

        if complexity == TaskComplexity.SIMPLE:
            return 0.9  # 简单任务强烈推荐本地
        elif complexity == TaskComplexity.MEDIUM:
            return 0.6  # 中等任务倾向本地
        else:  # COMPLEX
            return 0.2  # 复杂任务推荐云端

    def _score_privacy(self, privacy_level: str) -> float:
        """隐私等级评分（本地倾向分）.

        隐私等级越高，本地倾向分越高。

        Args:
            privacy_level: 隐私等级.

        Returns:
            本地倾向分（0.0-1.0）.
        """
        level = self._parse_privacy(privacy_level)

        if level == PrivacyLevel.TOP_SECRET:
            return 1.0
        elif level == PrivacyLevel.CONFIDENTIAL:
            return 0.95
        elif level == PrivacyLevel.INTERNAL:
            return 0.7
        else:  # PUBLIC
            return 0.3

    def _score_vram(self) -> float:
        """显存状态评分（本地倾向分）.

        显存越充足，本地倾向分越高。

        Returns:
            本地倾向分（0.0-1.0）.
        """
        level = self._get_vram_level()

        if level == VRAMLevel.SAFE:
            return 0.9
        elif level == VRAMLevel.WARNING:
            return 0.4
        else:  # CRITICAL
            return 0.0

    def _score_cost(self) -> float:
        """成本控制评分（本地倾向分）.

        预算越紧张，本地倾向分越高（本地免费）。

        Returns:
            本地倾向分（0.0-1.0）.
        """
        budget = self._cost_budget.lower()

        if budget == "tight":
            return 0.9  # 预算紧张 → 尽量本地
        elif budget == "normal":
            return 0.5  # 正常预算 → 视情况而定
        elif budget == "unlimited":
            return 0.2  # 预算充足 → 优先云端（更强能力）
        else:
            return 0.5

    def _score_speed(self, urgency: str) -> float:
        """响应速度评分（本地倾向分）.

        要求越快，本地倾向分越高（本地无网络延迟）。

        Args:
            urgency: 响应速度要求等级.

        Returns:
            本地倾向分（0.0-1.0）.
        """
        level = self._parse_urgency(urgency)

        if level == UrgencyLevel.URGENT:
            return 1.0
        elif level == UrgencyLevel.HIGH:
            return 0.8
        elif level == UrgencyLevel.NORMAL:
            return 0.5
        else:  # LOW
            return 0.2

    # ------------------------------------------------------------------
    # 内部方法：复杂度评估
    # ------------------------------------------------------------------

    def _assess_complexity(
        self,
        text: str = "",
        task_type: str | None = None,
    ) -> TaskComplexity:
        """评估任务复杂度.

        综合考虑输入长度、关键词匹配和任务类型。

        Args:
            text: 输入文本.
            task_type: 任务类型.

        Returns:
            任务复杂度等级.
        """
        # 先根据 task_type 判断
        type_complexity = self._task_type_complexity(task_type)
        if type_complexity == TaskComplexity.COMPLEX:
            return TaskComplexity.COMPLEX

        # 文本长度判断
        text_len = len(text) if text else 0
        if text_len > 2000:
            return TaskComplexity.COMPLEX
        elif text_len > 500:
            return TaskComplexity.MEDIUM

        # 关键词匹配
        text_lower = text.lower() if text else ""
        complex_count = sum(1 for kw in COMPLEX_KEYWORDS if kw.lower() in text_lower)
        simple_count = sum(1 for kw in SIMPLE_KEYWORDS if kw.lower() in text_lower)

        if complex_count >= 2:
            return TaskComplexity.COMPLEX
        elif complex_count == 1 or text_len > 200:
            return TaskComplexity.MEDIUM
        elif simple_count > 0 and text_len < 100:
            return TaskComplexity.SIMPLE

        # 默认根据 task_type 或返回 medium
        if type_complexity != TaskComplexity.MEDIUM:
            return type_complexity
        return TaskComplexity.MEDIUM

    @staticmethod
    def _task_type_complexity(task_type: str | None) -> TaskComplexity:
        """根据任务类型判断复杂度.

        Args:
            task_type: 任务类型.

        Returns:
            任务复杂度等级.
        """
        if task_type is None:
            return TaskComplexity.MEDIUM

        t = task_type.lower()

        # 复杂任务
        complex_types = [
            "code", "coding", "programming",
            "analysis", "analyze", "research",
            "translation_long", "summary_long",
            "math", "logic", "reasoning",
        ]
        if any(ct in t for ct in complex_types):
            return TaskComplexity.COMPLEX

        # 简单任务
        simple_types = [
            "chat", "greeting", "qa", "qa_simple",
            "classification", "extraction",
            "translation_short",
        ]
        if any(st in t for st in simple_types):
            return TaskComplexity.SIMPLE

        return TaskComplexity.MEDIUM

    # ------------------------------------------------------------------
    # 内部方法：辅助工具
    # ------------------------------------------------------------------

    def _get_vram_level(self) -> VRAMLevel:
        """获取当前显存水位线.

        Returns:
            VRAMLevel 枚举，无监控器时默认 SAFE.
        """
        if self._vram_monitor is None:
            return VRAMLevel.SAFE
        try:
            return self._vram_monitor.level
        except Exception:
            return VRAMLevel.SAFE

    @staticmethod
    def _parse_privacy(level: str) -> PrivacyLevel:
        """解析隐私等级字符串.

        Args:
            level: 隐私等级字符串.

        Returns:
            PrivacyLevel 枚举.
        """
        try:
            return PrivacyLevel(level.lower())
        except ValueError:
            return PrivacyLevel.INTERNAL

    @staticmethod
    def _parse_urgency(level: str) -> UrgencyLevel:
        """解析紧急度字符串.

        Args:
            level: 紧急度字符串.

        Returns:
            UrgencyLevel 枚举.
        """
        try:
            return UrgencyLevel(level.lower())
        except ValueError:
            return UrgencyLevel.NORMAL

    @staticmethod
    def _build_reason(route: str, scores: dict[str, float], total_score: float) -> str:
        """构建决策理由文本.

        Args:
            route: 路由结果.
            scores: 各因子评分.
            total_score: 总分.

        Returns:
            理由说明字符串.
        """
        # 找出影响最大的 2 个因子
        sorted_factors = sorted(scores.items(), key=lambda x: abs(x[1] - 0.5), reverse=True)
        top_factors = sorted_factors[:2]

        factor_names = {
            "complexity": "任务复杂度",
            "privacy": "隐私等级",
            "vram": "显存状态",
            "cost": "成本控制",
            "speed": "响应速度",
        }

        reason_parts = [f"综合评分 {total_score:.2f}"]
        for factor, score in top_factors:
            name = factor_names.get(factor, factor)
            direction = "倾向本地" if score > 0.5 else "倾向云端"
            reason_parts.append(f"{name}={score:.2f}({direction})")

        return "; ".join(reason_parts)

    # ------------------------------------------------------------------
    # 属性访问
    # ------------------------------------------------------------------

    @property
    def default_route(self) -> str:
        """获取默认路由模式."""
        return self._default_route

    @property
    def weights(self) -> dict[str, float]:
        """获取权重配置（只读副本）."""
        return dict(self._weights)

    @property
    def cost_budget(self) -> str:
        """获取成本预算等级."""
        return self._cost_budget

    def update_weights(self, weights: dict[str, float]) -> None:
        """更新权重配置并重新归一化.

        Args:
            weights: 新的权重组.
        """
        self._weights.update(weights)
        total = sum(self._weights.values())
        if total > 0:
            self._weights = {k: v / total for k, v in self._weights.items()}
        logger.info("route_engine.weights_updated", weights=self._weights)
