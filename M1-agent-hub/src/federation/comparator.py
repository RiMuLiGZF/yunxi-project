"""
多 Agent 结果对比与融合 — MultiAgentComparator

对多个 Agent 的执行结果进行质量评分、对比和融合输出。
"""

from __future__ import annotations

import asyncio
import re
from typing import Any

import structlog

from shared_models import (
    MultiAgentComparison,
    AgentResultItem,
    ComparisonOutputMode,
)

logger = structlog.get_logger(__name__)


# 质量评分权重
QUALITY_WEIGHTS = {
    "correctness": 0.35,   # 正确性
    "completeness": 0.25,  # 完整性
    "readability": 0.20,   # 可读性
    "code_quality": 0.20,  # 代码质量（仅代码任务）
}


class MultiAgentComparator:
    """多 Agent 结果对比器

    功能：
    - 多 Agent 并行执行
    - 四维度质量评分
    - 三种输出模式：单优/融合/对比
    """

    def __init__(self) -> None:
        self._logger = logger.bind(component="multi_agent_comparator")

    # ── 并行执行 ────────────────────────────────────────

    async def execute_parallel(
        self,
        adapters: list[Any],
        prompt: str,
        system_prompt: str = "",
        temperature: float = 0.7,
        max_tokens: int = 2048,
        output_mode: ComparisonOutputMode = ComparisonOutputMode.BEST_ONLY,
        task_type: str = "general",
    ) -> MultiAgentComparison:
        """并行调用多个 Agent 并对比结果

        Args:
            adapters: 适配器列表
            prompt: 用户输入
            system_prompt: 系统提示词
            temperature: 温度
            max_tokens: 最大 token
            output_mode: 输出模式
            task_type: 任务类型

        Returns:
            MultiAgentComparison 对比结果
        """
        if not adapters:
            return MultiAgentComparison(
                results=[],
                comparison_summary="无可用 Agent",
            )

        self._logger.info(
            "parallel_execution_start",
            adapter_count=len(adapters),
            output_mode=output_mode.value,
            task_type=task_type,
        )

        # 并行调用所有 Adapter
        tasks = [
            adapter.invoke(
                prompt=prompt,
                system_prompt=system_prompt,
                temperature=temperature,
                max_tokens=max_tokens,
                metadata={"task_type": task_type},
            )
            for adapter in adapters
        ]

        raw_results = await asyncio.gather(*tasks, return_exceptions=True)

        # 整理结果
        results: list[AgentResultItem] = []
        for i, (adapter, raw) in enumerate(zip(adapters, raw_results)):
            if isinstance(raw, Exception):
                results.append(AgentResultItem(
                    agent_id=adapter.agent_id,
                    agent_name=adapter.display_name,
                    output="",
                    quality_score=0.0,
                    cost=0.0,
                    latency_ms=0.0,
                    success=False,
                    error=str(raw),
                ))
            else:
                # 计算质量分数
                quality = self._score_quality(
                    output=raw.get("output", ""),
                    task_type=task_type,
                    prompt=prompt,
                )
                # 计算成本
                cost = adapter.calculate_cost(
                    raw.get("input_tokens", 0),
                    raw.get("output_tokens", 0),
                )
                results.append(AgentResultItem(
                    agent_id=adapter.agent_id,
                    agent_name=adapter.display_name,
                    output=raw.get("output", ""),
                    quality_score=quality,
                    cost=cost,
                    latency_ms=raw.get("latency_ms", 0),
                    success=raw.get("success", True),
                    error=raw.get("error", ""),
                ))

        # 找出最佳结果
        best_index = 0
        best_score = -1.0
        for i, r in enumerate(results):
            if r.success and r.quality_score > best_score:
                best_score = r.quality_score
                best_index = i

        total_cost = sum(r.cost for r in results)

        # 根据输出模式生成结果
        comparison = MultiAgentComparison(
            results=results,
            best_result_index=best_index,
            output_mode=output_mode,
            total_cost=total_cost,
        )

        if output_mode == ComparisonOutputMode.FUSION:
            comparison.fusion_output = self._fuse_results(results, task_type)

        comparison.comparison_summary = self._build_summary(results, best_index, output_mode)

        self._logger.info(
            "parallel_execution_done",
            best_agent=results[best_index].agent_name if results else "none",
            best_score=round(best_score, 2) if results else 0,
            total_cost=round(total_cost, 4),
        )

        return comparison

    # ── 质量评分 ────────────────────────────────────────

    def _score_quality(
        self,
        output: str,
        task_type: str,
        prompt: str,
    ) -> float:
        """四维度质量评分（0-100）

        维度：正确性、完整性、可读性、代码质量（仅代码任务）
        """
        if not output:
            return 0.0

        scores: dict[str, float] = {}

        # 1. 正确性（概念级：基于是否回答了问题、有无矛盾）
        correctness = self._score_correctness(output, prompt)
        scores["correctness"] = correctness

        # 2. 完整性（概念级：基于长度、结构、覆盖度）
        completeness = self._score_completeness(output, prompt)
        scores["completeness"] = completeness

        # 3. 可读性（概念级：基于段落结构、句子流畅度）
        readability = self._score_readability(output)
        scores["readability"] = readability

        # 4. 代码质量（仅代码任务）
        if task_type in ("code_generation", "code", "coding"):
            code_quality = self._score_code_quality(output)
            scores["code_quality"] = code_quality
        else:
            # 非代码任务：将代码质量权重分配给正确性
            scores["code_quality"] = correctness * 0.5

        # 加权求和
        total = sum(scores[k] * QUALITY_WEIGHTS[k] for k in QUALITY_WEIGHTS)
        return round(total, 2)

    def _score_correctness(self, output: str, prompt: str) -> float:
        """正确性评分（概念级）"""
        score = 60.0  # 基准分

        # 长度适中加分（太短可能不完整，太长可能冗余）
        output_len = len(output)
        if output_len < 50:
            score -= 20
        elif output_len < 100:
            score -= 10
        elif 200 <= output_len <= 2000:
            score += 15
        elif output_len > 5000:
            score -= 5

        # 有结构化标记（列表、标题）加分
        if re.search(r'[#\-\*]', output) or '1.' in output:
            score += 10

        # 有代码块加分（代码任务）
        if '```' in output:
            score += 10

        return max(0.0, min(100.0, score))

    def _score_completeness(self, output: str, prompt: str) -> float:
        """完整性评分（概念级）"""
        score = 50.0

        output_len = len(output)
        prompt_len = len(prompt)

        # 输出/输入比例
        if prompt_len > 0:
            ratio = output_len / prompt_len
            if ratio < 0.5:
                score -= 20
            elif 1.0 <= ratio <= 5.0:
                score += 25
            elif ratio > 10:
                score += 10

        # 段落数量
        paragraphs = [p for p in output.split('\n\n') if p.strip()]
        if len(paragraphs) >= 3:
            score += 15
        elif len(paragraphs) >= 1:
            score += 5

        return max(0.0, min(100.0, score))

    def _score_readability(self, output: str) -> float:
        """可读性评分（概念级）"""
        score = 60.0

        # 句子平均长度
        sentences = re.split(r'[。！？.!?]+', output)
        sentences = [s for s in sentences if s.strip()]
        if sentences:
            avg_len = sum(len(s) for s in sentences) / len(sentences)
            if 15 <= avg_len <= 60:
                score += 20
            elif avg_len > 100:
                score -= 10

        # 段落结构
        if output.count('\n') > 5:
            score += 10

        # 有编号/列表
        if re.search(r'\d+\.', output) or '- ' in output:
            score += 10

        return max(0.0, min(100.0, score))

    def _score_code_quality(self, output: str) -> float:
        """代码质量评分（概念级）"""
        score = 50.0

        # 有代码块
        if '```' in output:
            score += 20

        # 有注释
        code_blocks = re.findall(r'```[\s\S]*?```', output)
        for block in code_blocks:
            if '#' in block or '//' in block or "'''" in block:
                score += 10
                break

        # 有函数/类定义
        if 'def ' in output or 'class ' in output or 'function ' in output:
            score += 15

        # 代码长度适中
        code_len = sum(len(b) for b in code_blocks)
        if code_len > 100:
            score += 5

        return max(0.0, min(100.0, score))

    # ── 结果融合 ────────────────────────────────────────

    def _fuse_results(self, results: list[AgentResultItem], task_type: str) -> str:
        """融合多个 Agent 的结果（概念级）

        融合策略：取最佳结果为主体，补充其他结果的优点。
        """
        if not results:
            return ""

        # 按质量排序
        sorted_results = sorted(
            [r for r in results if r.success],
            key=lambda r: r.quality_score,
            reverse=True,
        )

        if not sorted_results:
            return "所有 Agent 均执行失败"

        if len(sorted_results) == 1:
            return sorted_results[0].output

        best = sorted_results[0]
        second = sorted_results[1]

        # 概念级融合：以最佳结果为主，标注参考了其他 Agent
        fused = (
            f"{best.output}\n\n"
            f"---\n"
            f"*融合说明：本结果基于 {best.agent_name}（评分{best.quality_score:.1f}）为主，"
            f"参考了 {second.agent_name}（评分{second.quality_score:.1f}）的补充观点。*"
        )

        return fused

    def _build_summary(
        self,
        results: list[AgentResultItem],
        best_index: int,
        output_mode: ComparisonOutputMode,
    ) -> str:
        """构建对比摘要"""
        if not results:
            return "无可用结果"

        best = results[best_index]
        success_count = sum(1 for r in results if r.success)
        total = len(results)

        parts = [
            f"共调用 {total} 个 Agent，成功 {success_count} 个",
            f"最佳：{best.agent_name}（质量评分 {best.quality_score:.1f}，费用 ${best.cost:.4f}）",
            f"输出模式：{output_mode.value}",
        ]

        return "；".join(parts)
