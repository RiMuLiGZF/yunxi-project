from __future__ import annotations

"""Skill Bandit Router - Bandit驱动的智能技能路由.

独创设计：参考 KABB（Knowledge-Aware Bayesian Bandits, ICML 2025）
和 CoCoMaMa（Contextual Combinatorial MAB Router, ECAI 2025），
使用 Thompson Sampling 策略为每个技能维护选择概率，
根据执行成功率/延迟/用户反馈在线更新，实现探索-利用最优平衡。
"""

import math
import random
from dataclasses import dataclass, field
from typing import Any

import structlog

logger = structlog.get_logger()


@dataclass
class BanditArm:
    """Bandit 臂（对应一个 skill_id + action 组合）."""

    skill_id: str
    action: str
    alpha: float = 1.0  # Beta 分布成功参数
    beta: float = 1.0   # Beta 分布失败参数
    total_reward: float = 0.0
    total_calls: int = 0
    last_reward: float = 0.0
    decay_factor: float = 0.995  # 指数衰减，淘汰过时数据

    @property
    def sample(self) -> float:
        """Thompson Sampling: 从 Beta(alpha, beta) 分布中采样."""
        return random.betavariate(self.alpha, self.beta)

    def sample_value(self) -> float:
        """实例方法版本，避免 property 被 dataclass 字段覆盖."""
        return random.betavariate(self.alpha, self.beta)

    @property
    def success_rate(self) -> float:
        """当前估计成功率."""
        return self.alpha / (self.alpha + self.beta) if (self.alpha + self.beta) > 0 else 0.5

    def update(self, reward: float) -> None:
        """更新臂的参数（Bandit 反馈）.

        Args:
            reward: 归一化奖励 [0, 1].1=成功, 0=失败.
        """
        # 指数衰减旧数据
        self.alpha = self.alpha * self.decay_factor
        self.beta = self.beta * self.decay_factor
        self.total_reward *= self.decay_factor

        # 更新参数
        if reward >= 0.5:
            self.alpha += reward
        else:
            self.beta += (1 - reward)
        self.total_reward += reward
        self.total_calls += 1
        self.last_reward = reward

    def decay(self) -> None:
        """主动衰减（定期调用，防止数据累积）."""
        self.alpha *= self.decay_factor
        self.beta *= self.decay_factor
        self.total_reward *= self.decay_factor


class SkillBanditRouter:
    """Bandit 驱动的技能路由器.

    与 SkillHandbook（经验视图）互补：
    - Handbook 提供离线统计分析（成功率、延迟画像）
    - BanditRouter 提供在线探索-利用决策（Thompson Sampling）

    使用场景：
    - 多个 skill 可完成同一任务时的自动选择
    - 新技能上线时的冷启动探索
    - 技能性能退化时的自动切换
    """

    def __init__(
        self,
        explore_rate: float = 0.1,
        min_calls_for_exploit: int = 5,
        decay_interval: int = 100,
    ) -> None:
        self._arms: dict[str, BanditArm] = {}  # key: "skill_id:action"
        self._explore_rate = explore_rate
        self._min_calls = min_calls_for_exploit
        self._decay_interval = decay_interval
        self._total_calls = 0

    def register_arm(self, skill_id: str, action: str) -> None:
        """注册 Bandit 臂."""
        key = f"{skill_id}:{action}"
        if key not in self._arms:
            self._arms[key] = BanditArm(skill_id=skill_id, action=action)

    def select(
        self, candidates: list[tuple[str, str]]
    ) -> tuple[str, str]:
        """选择最优 skill（Thompson Sampling + epsilon-greedy）.

        Args:
            candidates: [(skill_id, action)] 候选列表.

        Returns:
            (skill_id, action) 选择结果.
        """
        if not candidates:
            raise ValueError("No candidates provided")

        self._total_calls += 1

        # 定期衰减
        if self._total_calls % self._decay_interval == 0:
            for arm in self._arms.values():
                arm.decay()

        # 确保所有候选都已注册
        for sid, act in candidates:
            self.register_arm(sid, act)

        # epsilon-greedy: 以 explore_rate 概率随机探索
        if random.random() < self._explore_rate:
            return random.choice(candidates)

        # Thompson Sampling: 从每个臂的 Beta 分布采样，选择最大值
        best_key = max(
            (f"{sid}:{act}" for sid, act in candidates),
            key=lambda k: self._arms[k].sample_value(),
        )
        sid, act = best_key.split(":", 1)
        return sid, act

    def record(
        self,
        skill_id: str,
        action: str,
        success: bool,
        latency_ms: float = 0.0,
        user_feedback: float | None = None,
    ) -> float:
        """记录执行结果，计算归一化奖励.

        【第二轮优化】增加上下文感知奖励维度：
        - success: 基础奖励（成功=0.8-1.0，失败=0.0-0.2）
        - latency_ms: 延迟惩罚（线性衰减）
        - user_feedback: 用户满意度反馈（可选，0-1，权重0.15）

        Args:
            skill_id: 技能 ID.
            action: 动作标识.
            success: 是否成功.
            latency_ms: 调用延迟.
            user_feedback: 用户满意度评分 [0, 1].

        Returns:
            归一化奖励 [0, 1].
        """
        self._total_calls += 1

        key = f"{skill_id}:{action}"
        arm = self._arms.get(key)
        if arm is None:
            return 0.5

        # 计算基础奖励：成功=0.8-1.0，失败=0.0-0.2，延迟惩罚
        if success:
            latency_penalty = min(0.2, latency_ms / 50000.0)
            reward = 1.0 - latency_penalty
        else:
            reward = 0.1  # 失败给一个小正奖励，避免 beta 膨胀过快

        # 【新增】用户反馈调制（权重 0.15）
        if user_feedback is not None:
            feedback_delta = (user_feedback - 0.5) * 0.15  # [-0.075, +0.075]
            reward = max(0.0, min(1.0, reward + feedback_delta))

        arm.update(reward)
        return reward

    def get_arm_stats(self, skill_id: str, action: str) -> dict[str, Any]:
        """获取臂的统计信息."""
        key = f"{skill_id}:{action}"
        arm = self._arms.get(key)
        if arm is None:
            return {"registered": False}
        return {
            "registered": True,
            "success_rate": round(arm.success_rate, 3),
            "total_calls": arm.total_calls,
            "total_reward": round(arm.total_reward, 2),
            "alpha": round(arm.alpha, 3),
            "beta": round(arm.beta, 3),
        }

    def rank_candidates(
        self, candidates: list[tuple[str, str]]
    ) -> list[tuple[str, str, float]]:
        """为候选技能排序（按 Thompson Sampling 期望值）.

        Returns:
            [(skill_id, action, expected_value)] 按期望值降序.
        """
        for sid, act in candidates:
            self.register_arm(sid, act)

        ranked = []
        for sid, act in candidates:
            key = f"{sid}:{act}"
            arm = self._arms[key]
            # Beta 分布期望值 = alpha / (alpha + beta)
            expected = arm.success_rate
            ranked.append((sid, act, round(expected, 4)))

        ranked.sort(key=lambda x: x[2], reverse=True)
        return ranked

    def get_stats(self) -> dict[str, Any]:
        """获取路由器统计."""
        total_arms = len(self._arms)
        return {
            "total_arms": total_arms,
            "total_calls": self._total_calls,
            "explore_rate": self._explore_rate,
            "best_arm": max(
                ((k, arm.success_rate) for k, arm in self._arms.items()),
                key=lambda x: x[1],
                default=("", 0.0),
            ),
        }
