from __future__ import annotations

"""Skill Experience Bank - 技能经验沉淀库.

独创设计：将每次技能调用的 outcome（成功/失败/延迟/参数组合）
沉淀为结构化经验，形成 Skill-to-Outcome 映射。长期运行后，
经验库成为技能选择的最可靠数据源，实现类似 SkillRL 的
递归自我进化——越用越准，越用越快。

核心机制：
1. Experience Record: 记录 (skill_id, action, params_hash, outcome)
2. Success Pattern: 统计最优参数组合（top-k 参数指纹）
3. Failure Blacklist: 记录失败模式（action + params_hash → 失败原因）
4. Latency Profile: 延迟分位数统计，支持 7B 本地部署的 SLA 预判
"""

import hashlib
import json
import math
import time
from typing import Any

import structlog
from pydantic import BaseModel, Field

logger = structlog.get_logger()


class ExperienceRecord(BaseModel):
    """单次调用经验记录."""

    record_id: str = Field(..., description="记录唯一标识")
    skill_id: str = Field(..., description="技能 ID")
    action: str = Field(..., description="动作标识")
    params_hash: str = Field(default="", description="参数指纹")
    params_summary: dict[str, Any] = Field(
        default_factory=dict, description="参数摘要（不含敏感值）"
    )
    outcome: str = Field(
        ...,
        description="结果: success / failure / timeout / error",
    )
    latency_ms: float = Field(..., description="延迟")
    error: str | None = Field(default=None, description="错误信息")
    agent_id: str = Field(default="", description="调用 Agent")
    timestamp: float = Field(default_factory=time.time, description="时间")
    quality_score: float = Field(
        default=0.0, description="质量评分 (0-1)，综合延迟和成功率"
    )


class SuccessPattern(BaseModel):
    """成功模式（最优参数指纹）."""

    skill_id: str = Field(..., description="技能 ID")
    action: str = Field(..., description="动作标识")
    params_hash: str = Field(default="", description="参数指纹")
    params_summary: dict[str, Any] = Field(
        default_factory=dict, description="参数摘要"
    )
    call_count: int = Field(default=0, description="成功调用次数")
    avg_latency_ms: float = Field(default=0.0, description="平均延迟")
    success_rate: float = Field(default=1.0, description="成功率")
    quality_score: float = Field(default=0.0, description="质量评分")


class SkillExperienceBank:
    """技能经验沉淀库.

    收集技能调用经验，提炼成功模式，建立失败黑名单，
    为后续技能选择提供数据驱动的决策依据。
    """

    def __init__(
        self,
        max_records: int = 10_000,
        max_patterns_per_skill: int = 50,
    ) -> None:
        self._records: list[ExperienceRecord] = []
        self._patterns: dict[str, SuccessPattern] = {}  # key: skill_id:action:params_hash
        self._failure_blacklist: dict[str, list[str]] = {}  # key: skill_id:action, value: [error_types]
        self._latency_profiles: dict[str, list[float]] = {}  # key: skill_id, value: [latencies]
        self._max_records = max_records
        self._max_patterns = max_patterns_per_skill

    # ---- 经验记录 ----

    def record(
        self,
        skill_id: str,
        action: str,
        params: dict[str, Any],
        outcome: str,
        latency_ms: float,
        error: str | None = None,
        agent_id: str = "",
    ) -> ExperienceRecord:
        """记录一次技能调用经验.

        Args:
            skill_id: 技能 ID.
            action: 动作标识.
            params: 调用参数.
            outcome: 结果状态.
            latency_ms: 延迟.
            error: 错误信息.
            agent_id: Agent ID.

        Returns:
            经验记录.
        """
        params_hash = self._hash_params(params)
        params_summary = self._summarize_params(params)

        quality = self._compute_quality(outcome, latency_ms)

        record = ExperienceRecord(
            record_id=f"exp_{int(time.time()*1000)}_{hash(params_hash) % 10000}",
            skill_id=skill_id,
            action=action,
            params_hash=params_hash,
            params_summary=params_summary,
            outcome=outcome,
            latency_ms=latency_ms,
            error=error,
            agent_id=agent_id,
            quality_score=quality,
        )

        self._records.append(record)
        if len(self._records) > self._max_records:
            self._records = self._records[-self._max_records:]

        # 更新成功模式
        if outcome == "success":
            self._update_success_pattern(record)
        else:
            self._update_failure_blacklist(record)

        # 更新延迟画像
        self._latency_profiles.setdefault(skill_id, []).append(latency_ms)
        # 保留最近 1000 条延迟记录
        lat_list = self._latency_profiles[skill_id]
        if len(lat_list) > 1000:
            self._latency_profiles[skill_id] = lat_list[-1000:]

        return record

    # ---- 经验查询 ----

    def get_best_params(
        self, skill_id: str, action: str
    ) -> dict[str, Any] | None:
        """获取某技能某动作的历史最优参数组合.

        Returns:
            最优参数摘要，若无经验则返回 None.
        """
        candidates = [
            p
            for key, p in self._patterns.items()
            if p.skill_id == skill_id
            and p.action == action
            and p.call_count >= 3
        ]
        if not candidates:
            return None
        best = max(candidates, key=lambda p: p.quality_score)
        return best.params_summary

    def predict_success_rate(
        self, skill_id: str, action: str
    ) -> float:
        """预测某技能某动作的成功率.

        基于历史经验的加权移动平均。
        """
        patterns = [
            p
            for key, p in self._patterns.items()
            if p.skill_id == skill_id and p.action == action
        ]
        if not patterns:
            return 0.5  # 无经验时中性预测

        total_calls = sum(p.call_count for p in patterns)
        weighted_rate = sum(
            p.success_rate * p.call_count for p in patterns
        ) / total_calls
        return weighted_rate

    def predict_latency(
        self, skill_id: str, percentile: float = 0.9
    ) -> float | None:
        """预测某技能的延迟分位数.

        Args:
            skill_id: 技能 ID.
            percentile: 分位数（0-1），默认 P90.

        Returns:
            预测延迟（ms），无数据返回 None.
        """
        latencies = self._latency_profiles.get(skill_id)
        if not latencies:
            return None
        sorted_lat = sorted(latencies)
        idx = min(int(len(sorted_lat) * percentile), len(sorted_lat) - 1)
        return sorted_lat[idx]

    def is_known_failure_pattern(
        self, skill_id: str, action: str, params: dict[str, Any]
    ) -> str | None:
        """检查参数组合是否匹配已知失败模式.

        Returns:
            失败原因描述，若非已知失败模式则返回 None.
        """
        params_hash = self._hash_params(params)
        key = f"{skill_id}:{action}"
        errors = self._failure_blacklist.get(key, [])
        # 检查是否有 3 次以上相同参数指纹的失败
        fail_count = sum(
            1
            for r in self._records
            if r.skill_id == skill_id
            and r.action == action
            and r.params_hash == params_hash
            and r.outcome != "success"
        )
        if fail_count >= 3:
            return f"Known failure pattern: {fail_count} failures with similar params"
        return None

    def get_skill_stats(self, skill_id: str) -> dict[str, Any]:
        """获取技能的经验统计.

        Returns:
            统计字典.
        """
        skill_records = [
            r for r in self._records if r.skill_id == skill_id
        ]
        if not skill_records:
            return {
                "total_calls": 0,
                "success_rate": 0.0,
                "avg_latency_ms": 0.0,
                "p90_latency_ms": 0.0,
            }

        total = len(skill_records)
        successes = sum(1 for r in skill_records if r.outcome == "success")
        avg_lat = sum(r.latency_ms for r in skill_records) / total
        p90_lat = self.predict_latency(skill_id, 0.9) or 0.0

        return {
            "total_calls": total,
            "success_rate": successes / total,
            "avg_latency_ms": round(avg_lat, 2),
            "p90_latency_ms": round(p90_lat, 2),
            "experience_count": total,
        }

    def get_top_skills(
        self, n: int = 10
    ) -> list[tuple[str, float, int]]:
        """获取经验最丰富的技能排名.

        Returns:
            [(skill_id, avg_quality, call_count)] 列表.
        """
        skill_stats: dict[str, dict] = {}
        for r in self._records:
            if r.skill_id not in skill_stats:
                skill_stats[r.skill_id] = {
                    "total_quality": 0.0,
                    "count": 0,
                }
            skill_stats[r.skill_id]["total_quality"] += r.quality_score
            skill_stats[r.skill_id]["count"] += 1

        ranked = [
            (sid, stats["total_quality"] / stats["count"], stats["count"])
            for sid, stats in skill_stats.items()
        ]
        ranked.sort(key=lambda x: x[1], reverse=True)
        return ranked[:n]

    # ---- 经验管理 ----

    def forget_old(self, max_age_hours: float = 720.0) -> int:
        """清理过期经验（默认 30 天）."""
        threshold = time.time() - max_age_hours * 3600
        old_count = len(self._records)
        self._records = [
            r for r in self._records if r.timestamp >= threshold
        ]
        removed = old_count - len(self._records)

        # 同步清理失效的模式和延迟数据
        active_keys = {
            f"{r.skill_id}:{r.action}:{r.params_hash}"
            for r in self._records
            if r.outcome == "success"
        }
        self._patterns = {
            k: v
            for k, v in self._patterns.items()
            if f"{v.skill_id}:{v.action}:{v.params_hash}" in active_keys
        }
        return removed

    def export(self) -> dict[str, Any]:
        """导出经验库为可序列化的字典."""
        return {
            "records": [r.model_dump() for r in self._records[-100:]],
            "patterns": {
                k: v.model_dump() for k, v in self._patterns.items()
            },
            "failure_blacklist": dict(self._failure_blacklist),
        }

    # ---- 内部方法 ----

    def _hash_params(self, params: dict[str, Any]) -> str:
        """计算参数指纹."""
        serialized = json.dumps(params, sort_keys=True, default=str)
        return hashlib.md5(serialized.encode()).hexdigest()[:12]

    def _summarize_params(
        self, params: dict[str, Any]
    ) -> dict[str, Any]:
        """提取参数摘要（去掉大值，保留结构）."""
        summary: dict[str, Any] = {}
        for k, v in params.items():
            if isinstance(v, (str, int, float, bool)):
                if isinstance(v, str) and len(v) > 100:
                    summary[k] = v[:100] + "..."
                else:
                    summary[k] = v
            else:
                summary[k] = f"<{type(v).__name__}>"
        return summary

    def _compute_quality(
        self, outcome: str, latency_ms: float
    ) -> float:
        """计算质量评分 (0-1).

        综合 outcome 和延迟。
        """
        if outcome == "success":
            # 延迟越低质量越高，500ms 为满分基准
            latency_score = max(0.0, 1.0 - latency_ms / 5000.0)
            return 0.7 + 0.3 * latency_score  # 成功基础分 0.7
        elif outcome == "timeout":
            return 0.1
        else:
            return 0.0  # failure / error

    def _update_success_pattern(
        self, record: ExperienceRecord
    ) -> None:
        """更新成功模式."""
        key = (
            f"{record.skill_id}:{record.action}:{record.params_hash}"
        )
        if key in self._patterns:
            p = self._patterns[key]
            p.call_count += 1
            p.avg_latency_ms = (
                (p.avg_latency_ms * (p.call_count - 1) + record.latency_ms)
                / p.call_count
            )
            p.quality_score = record.quality_score
        else:
            self._patterns[key] = SuccessPattern(
                skill_id=record.skill_id,
                action=record.action,
                params_hash=record.params_hash,
                params_summary=record.params_summary,
                call_count=1,
                avg_latency_ms=record.latency_ms,
                quality_score=record.quality_score,
            )

    def _update_failure_blacklist(
        self, record: ExperienceRecord
    ) -> None:
        """更新失败黑名单."""
        key = f"{record.skill_id}:{record.action}"
        error_type = record.error or record.outcome
        if key not in self._failure_blacklist:
            self._failure_blacklist[key] = []
        if error_type not in self._failure_blacklist[key]:
            self._failure_blacklist[key].append(error_type)
