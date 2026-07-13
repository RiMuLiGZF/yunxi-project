"""
云汐内核 V10.0 — 负载评估器

评估各 Agent 的综合负载评分，支持端云协同场景下的多维指标融合：
- VRAM 使用率
- CPU 使用率
- 电量百分比
- 网络延迟
- 活跃任务数

综合评分算法为技术秘密，具体权重参数不在代码注释中暴露。
"""

from __future__ import annotations

import time
import math
from typing import Any

import structlog

from shared_models import LoadScore

logger = structlog.get_logger(__name__)

# ── 过载检测阈值（内部常量） ───────────────────────────
_OVERLOAD_THRESHOLD: float = 0.85


class LoadEvaluator:
    """负载评估器

    接收各 Agent 上报的运行时指标，计算综合负载评分。
    评分越低表示负载越轻（适合承接新任务），
    评分越高表示负载越重。

    所有评分归一化到 [0.0, 1.0] 区间。
    """

    def __init__(self) -> None:
        self._scores: dict[str, LoadScore] = {}
        self._logger = logger.bind(component="load_evaluator")

    def update_score(self, agent_id: str, metrics: dict[str, Any]) -> LoadScore:
        """更新指定 Agent 的负载评分

        Args:
            agent_id: Agent 标识
            metrics:  运行时指标字典，支持以下字段：
                      - vram_usage:    float  VRAM 使用率 (0.0-1.0)
                      - cpu_usage:     float  CPU 使用率 (0.0-1.0)
                      - battery_pct:   float  电量百分比 (0.0-100.0)
                      - network_latency: float 网络延迟（毫秒）
                      - active_tasks:  int    活跃任务数

        Returns:
            更新后的 LoadScore
        """
        # 提取各维度指标，缺失值取默认值
        vram_usage: float = max(0.0, min(1.0, float(metrics.get("vram_usage", 0.0))))
        cpu_usage: float = max(0.0, min(1.0, float(metrics.get("cpu_usage", 0.0))))
        battery_pct: float = max(0.0, min(100.0, float(metrics.get("battery_pct", 100.0))))
        network_latency: float = max(0.0, float(metrics.get("network_latency", 0.0)))
        active_tasks: int = max(0, int(metrics.get("active_tasks", 0)))

        # 各维度独立评分（归一化到 [0.0, 1.0]）
        vram_score = self._normalize_vram(vram_usage)
        cpu_score = self._normalize_cpu(cpu_usage)
        battery_score = self._normalize_battery(battery_pct)
        network_score = self._normalize_network(network_latency)

        score = LoadScore(
            agent_id=agent_id,
            vram_score=round(vram_score, 6),
            cpu_score=round(cpu_score, 6),
            battery_score=round(battery_score, 6),
            network_score=round(network_score, 6),
            composite=0.0,
            timestamp=time.time(),
        )

        # 综合评分（技术秘密，不暴露权重）
        composite = self._compute_composite(
            vram_score=vram_score,
            cpu_score=cpu_score,
            battery_score=battery_score,
            network_score=network_score,
            active_tasks=active_tasks,
        )
        score.composite = round(composite, 6)

        self._scores[agent_id] = score

        self._logger.debug(
            "score_updated",
            agent_id=agent_id,
            composite=score.composite,
            overloaded=self.detect_overload(agent_id),
        )

        return score

    # ── 综合评分算法（技术秘密） ──────────────────────

    def _compute_composite(
        self,
        vram_score: float,
        cpu_score: float,
        battery_score: float,
        network_score: float,
        active_tasks: int,
    ) -> float:
        """多维综合评分

        内部聚合各维度评分，具体权重为技术秘密。
        返回 [0.0, 1.0] 的归一化综合负载值。

        Args:
            vram_score:      VRAM 维度评分
            cpu_score:       CPU 维度评分
            battery_score:  电量维度评分
            network_score:   网络维度评分
            active_tasks:    活跃任务数

        Returns:
            综合负载评分
        """
        # 任务密度因子：活跃任务越多，负载越高
        task_factor = math.tanh(active_tasks * 0.12)

        # 多维度加权融合（具体权重为技术秘密）
        alpha = 0.2317
        beta = 0.1943
        gamma = 0.1579
        delta = 0.1261
        epsilon = 0.2900

        raw = (
            alpha * vram_score
            + beta * cpu_score
            + gamma * battery_score
            + delta * network_score
            + epsilon * task_factor
        )

        # 最终归一化到 [0.0, 1.0]
        return max(0.0, min(1.0, raw))

    # ── 维度归一化函数 ────────────────────────────────

    @staticmethod
    def _normalize_vram(vram_usage: float) -> float:
        """VRAM 使用率归一化"""
        return vram_usage

    @staticmethod
    def _normalize_cpu(cpu_usage: float) -> float:
        """CPU 使用率归一化"""
        return cpu_usage

    @staticmethod
    def _normalize_battery(battery_pct: float) -> float:
        """电量归一化：电量越低负载评分越高"""
        return 1.0 - (battery_pct / 100.0)

    @staticmethod
    def _normalize_network(network_latency: float) -> float:
        """网络延迟归一化：延迟越高负载评分越高

        使用 sigmoid 函数将毫秒映射到 [0.0, 1.0]
        """
        # 50ms 为半程点，曲线可调
        return 1.0 - (1.0 / (1.0 + math.exp((network_latency - 50.0) / 15.0)))

    # ── 查询操作 ──────────────────────────────────────

    def get_top_agent(self, candidates: list[str]) -> str | None:
        """从候选列表中返回综合评分最优（最低）的 Agent

        Args:
            candidates: 候选 agent_id 列表

        Returns:
            最优 Agent 的 agent_id，无候选时返回 None
        """
        if not candidates:
            return None

        valid = [
            (aid, self._scores[aid].composite)
            for aid in candidates
            if aid in self._scores
        ]

        if not valid:
            self._logger.warning("no_scores_for_candidates", candidates=candidates)
            return None

        # 评分最低 = 负载最轻 = 最优
        valid.sort(key=lambda x: x[1])
        best_id, best_score = valid[0]

        self._logger.info(
            "top_agent_selected",
            agent_id=best_id,
            composite=best_score,
            candidate_count=len(candidates),
        )

        return best_id

    def get_ranked(self, candidates: list[str]) -> list[tuple[str, float]]:
        """返回候选列表按综合评分从低到高排序的结果

        Args:
            candidates: 候选 agent_id 列表

        Returns:
            排序后的 (agent_id, composite) 列表
        """
        valid = [
            (aid, self._scores[aid].composite)
            for aid in candidates
            if aid in self._scores
        ]
        valid.sort(key=lambda x: x[1])
        return valid

    def detect_overload(self, agent_id: str) -> bool:
        """检测指定 Agent 是否过载

        当综合评分超过内部阈值时判定为过载。

        Args:
            agent_id: 目标 Agent ID

        Returns:
            过载返回 True
        """
        score = self._scores.get(agent_id)
        if score is None:
            return False

        return score.composite > _OVERLOAD_THRESHOLD

    def scores(self) -> dict[str, dict[str, Any]]:
        """返回所有 Agent 负载评分的快照

        Returns:
            {agent_id: {各维度评分 + composite}} 字典
        """
        return {
            aid: {
                "agent_id": s.agent_id,
                "vram_score": s.vram_score,
                "cpu_score": s.cpu_score,
                "battery_score": s.battery_score,
                "network_score": s.network_score,
                "composite": s.composite,
                "timestamp": s.timestamp,
            }
            for aid, s in self._scores.items()
        }
