"""Skill Pipeline 流水线编排引擎.

支持声明式定义 Skill 之间的串联、并联、条件分支、循环执行模式，
实现复杂工作流的自动化编排。

【模型迁移说明】
Pydantic 模型已迁移至 ``skill_cluster.models.pipeline``，
本文件保留 import 别名以保持向后兼容。
"""

from __future__ import annotations

import asyncio
import time
import uuid
from typing import Any, Awaitable, Callable, Literal

import structlog

from skill_cluster.interfaces import SkillInvokeRequest, SkillInvokeResult
from skill_cluster.skill_router import SkillRouter

# ---- 从 models.pipeline 导入 Pydantic 模型（向后兼容） ----
from skill_cluster.models.pipeline import (
    PipelineContext,
    PipelineDefinition,
    PipelineStep,
)

logger = structlog.get_logger()


class PipelineEngine:
    """流水线执行引擎."""

    def __init__(self, router: SkillRouter | None = None) -> None:
        self._router = router
        self._definitions: dict[str, PipelineDefinition] = {}

    def register(self, definition: PipelineDefinition) -> None:
        """注册流水线定义."""
        self._definitions[definition.pipeline_id] = definition
        logger.info("pipeline_registered", pipeline_id=definition.pipeline_id)

    def unregister(self, pipeline_id: str) -> None:
        """注销流水线定义."""
        self._definitions.pop(pipeline_id, None)

    def get_definition(self, pipeline_id: str) -> PipelineDefinition | None:
        """获取流水线定义."""
        return self._definitions.get(pipeline_id)

    async def execute(
        self,
        pipeline_id: str,
        agent_id: str,
        initial_params: dict[str, Any] | None = None,
        trace_id: str | None = None,
    ) -> PipelineContext:
        """执行流水线.

        Args:
            pipeline_id: 流水线 ID.
            agent_id: Agent 标识.
            initial_params: 初始参数，注入到 variables.
            trace_id: 追踪 ID.

        Returns:
            执行上下文（含所有步骤结果）.
        """
        definition = self._definitions.get(pipeline_id)
        if definition is None:
            raise ValueError(f"Pipeline {pipeline_id} not found")

        ctx = PipelineContext(
            pipeline_id=pipeline_id,
            trace_id=trace_id or f"trace_{uuid.uuid4().hex[:16]}",
            agent_id=agent_id,
            variables=initial_params or {},
        )

        if self._router is None:
            ctx.status = "failure"
            return ctx

        try:
            if definition.mode == "sequential":
                await self._execute_sequential(definition, ctx)
            elif definition.mode == "parallel":
                await self._execute_parallel(definition, ctx)
            elif definition.mode == "dag":
                await self._execute_dag(definition, ctx)
            else:
                raise ValueError(f"Unknown mode: {definition.mode}")
        except asyncio.CancelledError:
            ctx.status = "cancelled"
            raise
        except Exception as e:
            ctx.status = "failure"
            logger.error("pipeline_failed", pipeline_id=pipeline_id, error=str(e))

        # 如果有任何步骤失败，整体状态为 failure
        if ctx.status == "running":
            if any(
                r.status != "success"
                for r in ctx.step_results.values()
            ):
                ctx.status = "failure"
            else:
                ctx.status = "success"

        ctx.finished_at = time.time()
        logger.info(
            "pipeline_finished",
            pipeline_id=pipeline_id,
            run_id=ctx.run_id,
            status=ctx.status,
            duration_ms=(ctx.finished_at - ctx.started_at) * 1000,
        )
        return ctx

    async def _execute_sequential(
        self, definition: PipelineDefinition, ctx: PipelineContext
    ) -> None:
        """顺序执行."""
        for step in definition.steps:
            if not self._check_condition(step.condition, ctx):
                logger.info("step_skipped", step_id=step.step_id, condition=step.condition)
                continue
            result = await self._execute_step(step, ctx)
            ctx.step_results[step.step_id] = result
            if result.status != "success":
                logger.warning(
                    "step_failed_abort",
                    step_id=step.step_id,
                    status=result.status,
                )
                break

    async def _execute_parallel(
        self, definition: PipelineDefinition, ctx: PipelineContext
    ) -> None:
        """并行执行所有步骤（无依赖关系时）."""
        semaphore = asyncio.Semaphore(definition.max_parallelism)

        async def _run(step: PipelineStep) -> tuple[str, SkillInvokeResult]:
            async with semaphore:
                if not self._check_condition(step.condition, ctx):
                    return step.step_id, SkillInvokeResult(
                        skill_id=step.skill_id,
                        action=step.action,
                        status="skipped",
                        latency_ms=0.0,
                        trace_id=ctx.trace_id,
                    )
                result = await self._execute_step(step, ctx)
                return step.step_id, result

        tasks = [asyncio.create_task(_run(step)) for step in definition.steps]
        for task in asyncio.as_completed(tasks):
            step_id, result = await task
            ctx.step_results[step_id] = result

    async def _execute_dag(
        self, definition: PipelineDefinition, ctx: PipelineContext
    ) -> None:
        """DAG 模式：拓扑排序 + 波次并行执行."""
        # 1. 构建依赖图：从 params_mapping 推断依赖关系
        in_degree: dict[str, int] = {s.step_id: 0 for s in definition.steps}
        dependents: dict[str, list[str]] = {s.step_id: [] for s in definition.steps}
        step_map: dict[str, PipelineStep] = {s.step_id: s for s in definition.steps}

        for step in definition.steps:
            if step.params_mapping:
                for src in step.params_mapping.keys():
                    # src 格式如 "upstream_step_id.data.key" 或 "upstream_step_id.status"
                    dep_id = src.split(".")[0]
                    if dep_id in step_map and dep_id != step.step_id:
                        in_degree[step.step_id] += 1
                        dependents[dep_id].append(step.step_id)

        # 2. Kahn 拓扑排序 + 波次并行
        semaphore = asyncio.Semaphore(definition.max_parallelism)
        completed: set[str] = set()

        async def _run_step(step: PipelineStep) -> tuple[str, SkillInvokeResult]:
            async with semaphore:
                if not self._check_condition(step.condition, ctx):
                    return step.step_id, SkillInvokeResult(
                        skill_id=step.skill_id,
                        action=step.action,
                        status="skipped",
                        latency_ms=0.0,
                        trace_id=ctx.trace_id,
                    )
                result = await self._execute_step(step, ctx)
                return step.step_id, result

        while len(completed) < len(definition.steps):
            # 找出当前可执行的步骤（入度为0且未执行）
            wave = [
                step_map[sid]
                for sid, deg in in_degree.items()
                if deg == 0 and sid not in completed
            ]
            if not wave:
                # 存在循环依赖
                logger.error("pipeline_dag_cycle_detected")
                break

            # 并行执行当前波次
            tasks = [asyncio.create_task(_run_step(s)) for s in wave]
            for task in asyncio.as_completed(tasks):
                step_id, result = await task
                ctx.step_results[step_id] = result
                completed.add(step_id)
                # 减少下游步骤的入度
                for dep_id in dependents[step_id]:
                    in_degree[dep_id] -= 1

    async def _execute_step(
        self, step: PipelineStep, ctx: PipelineContext
    ) -> SkillInvokeResult:
        """执行单步."""
        params = dict(step.params)
        # 参数映射：从上游结果或变量池提取数据
        if step.params_mapping:
            for src, dst in step.params_mapping.items():
                val = self._resolve_value(src, ctx)
                if val is not None:
                    params[dst] = val

        # 变量池中的全局参数也注入
        for key, val in ctx.variables.items():
            if key not in params:
                params[key] = val

        request = SkillInvokeRequest(
            skill_id=step.skill_id,
            action=step.action,
            params=params,
            trace_id=ctx.trace_id,
            timeout=step.timeout,
        )
        return await self._router.invoke(request, ctx.agent_id)

    def _check_condition(
        self, condition: str | None, ctx: PipelineContext
    ) -> bool:
        """检查条件表达式."""
        if condition is None:
            return True
        # 简化条件引擎：支持 'step_id.status == success' 格式
        try:
            parts = condition.split("==")
            left = parts[0].strip()
            right = parts[1].strip().strip("'\"") if len(parts) > 1 else ""
            val = self._resolve_value(left, ctx)
            return str(val) == right
        except Exception:
            logger.warning("condition_eval_failed", condition=condition)
            return False

    def _resolve_value(self, path: str, ctx: PipelineContext) -> Any:
        """从上下文中解析值路径.

        支持:
        - 'step_id.data.key' -> 从步骤结果中提取
        - 'variables.key' -> 从变量池提取
        - 'step_id.status' -> 步骤状态
        """
        parts = path.split(".")
        if len(parts) < 2:
            return None
        if parts[0] == "variables":
            return ctx.variables.get(".".join(parts[1:]))
        step_id = parts[0]
        result = ctx.step_results.get(step_id)
        if result is None:
            return None
        if parts[1] == "status":
            return result.status
        if parts[1] == "data" and result.data:
            # 支持嵌套路径: data.echo.x -> result.data['echo']['x']
            val = result.data
            for p in parts[2:]:
                if isinstance(val, dict) and p in val:
                    val = val[p]
                else:
                    return None
            return val
        return None
