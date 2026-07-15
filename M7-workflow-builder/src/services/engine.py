"""M7 积木平台 - 工作流执行引擎.

核心 WorkflowEngine 编排类：线性串行与 DAG 并行执行、并发限流、取消支持。
执行器与验证逻辑已拆分至 executor.py / validator.py，本模块保留编排逻辑，
并向后兼容导出原公开名称（BUILTIN_BLOCKS / M2SkillClient / execute_builtin_block /
build_adjacency_list / topological_sort / is_linear_workflow / WorkflowValidator）。
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
import uuid
from collections import deque
from typing import Any, Dict, List, Optional, Set, Tuple

from .executor import BUILTIN_BLOCKS, M2SkillClient, execute_builtin_block
from .validator import (
    WorkflowValidator,
    build_adjacency_list,
    is_linear_workflow,
    topological_sort,
)

logger = logging.getLogger("m7.engine")

class WorkflowEngine:
    """工作流执行引擎.

    支持线性串行执行和 DAG 拓扑排序执行。
    M2 不可用时自动降级到内置积木实现。
    """

    # P1-05: 全局并发控制
    _running_count: int = 0
    _running_lock: asyncio.Lock = asyncio.Lock() if hasattr(asyncio, 'Lock') else None
    _max_running: int = 0

    @classmethod
    def _get_max_running(cls) -> int:
        """获取最大并发工作流数."""
        if cls._max_running <= 0:
            cls._max_running = int(os.environ.get("M7_MAX_RUNNING_WORKFLOWS", "10"))
        return cls._max_running

    @classmethod
    async def _acquire_slot(cls) -> bool:
        """获取执行槽位（并发控制）.

        Returns:
            True 获取成功，False 已满
        """
        if cls._running_lock is None:
            cls._running_lock = asyncio.Lock()
        async with cls._running_lock:
            if cls._running_count >= cls._get_max_running():
                return False
            cls._running_count += 1
            return True

    @classmethod
    async def _release_slot(cls):
        """释放执行槽位."""
        if cls._running_lock is None:
            cls._running_lock = asyncio.Lock()
        async with cls._running_lock:
            if cls._running_count > 0:
                cls._running_count -= 1

    @classmethod
    def get_running_count(cls) -> int:
        """获取当前运行中的工作流数."""
        return cls._running_count

    # P1-04: 活跃任务管理（取消支持）
    _active_tasks: Dict[str, asyncio.Task] = {}

    @classmethod
    def _register_task(cls, run_id: str, task: asyncio.Task):
        """注册运行任务."""
        cls._active_tasks[run_id] = task

    @classmethod
    def _unregister_task(cls, run_id: str):
        """注销运行任务."""
        cls._active_tasks.pop(run_id, None)

    @classmethod
    async def cancel_run(cls, run_id: str) -> bool:
        """取消正在运行的工作流.

        Args:
            run_id: 运行 ID

        Returns:
            是否成功取消
        """
        task = cls._active_tasks.get(run_id)
        if task and not task.done():
            task.cancel()
            return True
        return False

    def __init__(
        self,
        m2_client: Optional[M2SkillClient] = None,
        use_builtin_fallback: bool = True,
        workflow_timeout: Optional[float] = None,
        block_timeout: Optional[float] = None,
    ) -> None:
        """初始化执行引擎.

        Args:
            m2_client: M2 技能客户端
            use_builtin_fallback: 是否使用内置积木降级
            workflow_timeout: 工作流整体超时时间（秒），默认 300 秒
            block_timeout: 单个积木执行超时时间（秒），默认 60 秒
        """
        self.m2_client = m2_client or M2SkillClient()
        self.use_builtin_fallback = use_builtin_fallback
        self._m2_available: Optional[bool] = None
        self._m2_check_time: float = 0
        self._m2_cache_ttl: float = 60.0  # M2 可用性缓存 60 秒

        # 超时配置（从环境变量读取，默认值兜底）
        self.workflow_timeout = workflow_timeout or float(
            os.environ.get("M7_WORKFLOW_TIMEOUT", "300")
        )
        self.block_timeout = block_timeout or float(
            os.environ.get("M7_BLOCK_TIMEOUT", "60")
        )

        # P1-01: DAG 并行执行配置
        self.max_parallel_nodes = int(os.environ.get("M7_MAX_PARALLEL_NODES", "5"))

    async def _check_m2_available(self, force: bool = False) -> bool:
        """检查 M2 是否可用（带缓存）."""
        now = time.time()
        if force or self._m2_available is None or (now - self._m2_check_time) > self._m2_cache_ttl:
            self._m2_available = await self.m2_client.health_check()
            self._m2_check_time = now
        return self._m2_available

    def _resolve_variables(
        self,
        variables_config: List[Dict[str, Any]],
        runtime_vars: Dict[str, Any],
        input_data: Dict[str, Any],
    ) -> Dict[str, Any]:
        """解析工作流变量的最终值.

        Args:
            variables_config: 工作流中定义的变量列表
            runtime_vars: 运行时传入的变量覆盖
            input_data: 输入数据

        Returns:
            解析后的变量字典
        """
        resolved: Dict[str, Any] = {}

        # 先加载默认值
        for var_def in variables_config:
            resolved[var_def["name"]] = var_def.get("default")

        # 输入数据中的变量也合并进来
        resolved.update(input_data)

        # 运行时变量优先级最高
        resolved.update(runtime_vars)

        return resolved

    def _build_step_input(
        self,
        block: Dict[str, Any],
        block_index: int,
        variables: Dict[str, Any],
        step_results: Dict[str, Dict[str, Any]],
        adjacency: Dict[str, List[str]],
    ) -> Dict[str, Any]:
        """构建积木块的输入数据.

        合并积木配置、工作流变量、前驱节点输出。

        Args:
            block: 当前积木块配置
            block_index: 积木块索引
            variables: 工作流变量
            step_results: 已执行步骤的结果 {block_id: result}
            adjacency: 邻接表（用于找前驱）

        Returns:
            输入参数字典
        """
        block_config = block.get("config", {}).copy()

        # 找到所有前驱节点
        predecessors: List[str] = []
        for node, next_nodes in adjacency.items():
            if block["id"] in next_nodes:
                predecessors.append(node)

        # 收集前驱输出
        previous_outputs: Dict[str, Any] = {}
        for pred_id in predecessors:
            if pred_id in step_results:
                pred_output = step_results[pred_id].get("output")
                if isinstance(pred_output, dict):
                    previous_outputs.update(pred_output)
                else:
                    previous_outputs[f"{pred_id}_output"] = pred_output

        # 合并：变量 → 前驱输出 → 积木配置（积木配置优先级最高）
        step_input: Dict[str, Any] = {}
        step_input.update(variables)
        step_input.update(previous_outputs)
        step_input["previous_output"] = previous_outputs if previous_outputs else None
        step_input.update(block_config)

        return step_input

    async def _execute_block(
        self,
        block: Dict[str, Any],
        step_input: Dict[str, Any],
        m2_available: bool,
    ) -> Tuple[Dict[str, Any], bool]:
        """执行单个积木块.

        支持节点级重试（P1-03）：从积木配置中读取重试策略。

        Args:
            block: 积木块配置
            step_input: 输入参数
            m2_available: M2 是否可用

        Returns:
            (结果字典, 是否成功) 元组
        """
        skill_id = block.get("type", "")
        block_config = block.get("config", {})
        action = block_config.get("action", "default")
        # action 已经在 step_input 里可能有，但我们用配置里的
        action = block.get("config", {}).get("action", "default")

        # P1-03: 重试策略
        retry_config = block.get("retry", {})
        max_retries = int(retry_config.get("max_retries", 0))
        retry_delay = float(retry_config.get("retry_delay", 1.0))
        retry_backoff = float(retry_config.get("retry_backoff", 2.0))
        retry_on = retry_config.get("retry_on", [])  # 错误类型白名单，空=所有错误都重试

        result: Dict[str, Any] = {
            "block_id": block["id"],
            "block_name": block.get("name", ""),
            "skill_id": skill_id,
            "action": action,
            "status": "running",
            "input": step_input,
            "output": None,
            "error": None,
            "started_at": time.time(),
            "finished_at": None,
            "duration_ms": 0,
            "retry_count": 0,
            "source": "m2" if m2_available else "builtin",
        }

        last_error = None
        for attempt in range(max_retries + 1):
            try:
                # 节点级超时控制
                async def _do_execute() -> Any:
                    if m2_available:
                        # 调用 M2 技能
                        response = await self.m2_client.invoke_skill(
                            skill_id=skill_id,
                            action=action,
                            params=step_input,
                        )
                        return ("m2", response)
                    elif self.use_builtin_fallback and skill_id in BUILTIN_BLOCKS:
                        # 使用内置降级实现
                        builtin_result = await execute_builtin_block(
                            skill_id=skill_id,
                            action=action,
                            params=step_input,
                        )
                        return ("builtin", builtin_result)
                    else:
                        return ("no_impl", f"M2 不可用且无内置降级实现: {skill_id}")

                exec_result = await asyncio.wait_for(
                    _do_execute(),
                    timeout=self.block_timeout,
                )

                if exec_result[0] == "m2":
                    response = exec_result[1]
                    resp_code = response.get("code", -1)
                    resp_data = response.get("data", {})
                    if resp_code == 20000 or response.get("success", False):
                        invoke_data = (
                            resp_data.get("data", resp_data)
                            if isinstance(resp_data, dict)
                            else resp_data
                        )
                        result["status"] = "success"
                        result["output"] = invoke_data
                    else:
                        result["status"] = "failed"
                        result["error"] = response.get("message", "技能执行失败")
                elif exec_result[0] == "builtin":
                    builtin_result = exec_result[1]
                    if builtin_result.get("success"):
                        result["status"] = "success"
                        result["output"] = builtin_result.get("data")
                    else:
                        result["status"] = "failed"
                        result["error"] = builtin_result.get("error", "内置积木执行失败")
                else:
                    result["status"] = "failed"
                    result["error"] = exec_result[1]

                # 成功则退出重试循环
                if result["status"] == "success":
                    break

                last_error = result["error"]

            except asyncio.TimeoutError:
                last_error = f"节点执行超时（{self.block_timeout}秒）"
                result["status"] = "failed"
                result["error"] = last_error
            except asyncio.CancelledError:
                result["status"] = "cancelled"
                result["error"] = "工作流已被取消"
                result["finished_at"] = time.time()
                result["duration_ms"] = int((result["finished_at"] - result["started_at"]) * 1000)
                return result, False
            except Exception as e:
                last_error = str(e)
                result["status"] = "failed"
                result["error"] = last_error

            # P1-03: 判断是否需要重试
            if attempt < max_retries and result["status"] == "failed":
                # 检查错误类型是否在白名单中
                should_retry = True
                if retry_on:
                    should_retry = any(
                        keyword in (last_error or "").lower()
                        for keyword in retry_on
                    )
                if should_retry:
                    result["retry_count"] = attempt + 1
                    delay = retry_delay * (retry_backoff ** attempt)
                    logger.warning(
                        f"[P1-03] 节点 {block.get('name', block['id'])} "
                        f"第{attempt + 1}次执行失败，{delay:.1f}s后重试: {last_error}"
                    )
                    await asyncio.sleep(delay)
                else:
                    break
            else:
                break

        result["finished_at"] = time.time()
        result["duration_ms"] = int((result["finished_at"] - result["started_at"]) * 1000)

        return result, result["status"] == "success"

    async def run_workflow(
        self,
        workflow: Dict[str, Any],
        input_data: Optional[Dict[str, Any]] = None,
        start_block: Optional[str] = None,
        runtime_variables: Optional[Dict[str, Any]] = None,
        triggered_by: str = "",
    ) -> Dict[str, Any]:
        """运行工作流.

        支持线性串行和 DAG 两种执行模式。自动检测工作流结构。
        DAG 模式下支持同层节点并行执行（P1-01）。
        支持取消（P1-04）和并发限流（P1-05）。
        """
        blocks = workflow.get("blocks", [])
        if not blocks:
            return {
                "run_id": f"run_{uuid.uuid4().hex[:12]}",
                "workflow_id": workflow.get("id", ""),
                "workflow_name": workflow.get("name", ""),
                "status": "failed",
                "started_at": time.time(),
                "finished_at": time.time(),
                "duration_ms": 0,
                "steps": [],
                "total_blocks": 0,
                "success_blocks": 0,
                "failed_blocks": 0,
                "skipped_blocks": 0,
                "triggered_by": triggered_by,
                "trigger_type": workflow.get("trigger", {}).get("type", "manual"),
                "input_data": input_data or {},
                "final_output": None,
                "error": "工作流中没有积木块",
            }

        run_id = f"run_{uuid.uuid4().hex[:12]}"
        run_start_time = time.time()
        input_data = input_data or {}
        runtime_variables = runtime_variables or {}

        # P1-05: 并发限流
        if not await WorkflowEngine._acquire_slot():
            return {
                "run_id": run_id,
                "workflow_id": workflow.get("id", ""),
                "workflow_name": workflow.get("name", ""),
                "status": "rejected",
                "started_at": run_start_time,
                "finished_at": time.time(),
                "duration_ms": 0,
                "steps": [],
                "total_blocks": len(blocks),
                "success_blocks": 0,
                "failed_blocks": 0,
                "skipped_blocks": 0,
                "triggered_by": triggered_by,
                "trigger_type": workflow.get("trigger", {}).get("type", "manual"),
                "input_data": input_data,
                "final_output": None,
                "error": f"系统繁忙，并发工作流数已达上限（{WorkflowEngine._get_max_running()}）",
                "running_count": WorkflowEngine.get_running_count(),
            }

        # 解析变量
        variables_config = workflow.get("variables", [])
        variables = self._resolve_variables(variables_config, runtime_variables, input_data)

        # 构建邻接表
        adjacency, in_degree = build_adjacency_list(blocks)

        # 拓扑排序得到执行顺序
        try:
            execution_order = topological_sort(blocks, start_block)
        except ValueError as e:
            await WorkflowEngine._release_slot()
            return {
                "run_id": run_id,
                "workflow_id": workflow.get("id", ""),
                "workflow_name": workflow.get("name", ""),
                "status": "failed",
                "started_at": run_start_time,
                "finished_at": time.time(),
                "duration_ms": 0,
                "steps": [],
                "total_blocks": len(blocks),
                "success_blocks": 0,
                "failed_blocks": 0,
                "skipped_blocks": len(blocks),
                "triggered_by": triggered_by,
                "trigger_type": workflow.get("trigger", {}).get("type", "manual"),
                "input_data": input_data,
                "final_output": None,
                "error": str(e),
            }

        # 检查 M2 可用性
        m2_available = await self._check_m2_available()

        # 执行
        steps: List[Dict[str, Any]] = []
        step_results: Dict[str, Dict[str, Any]] = {}
        overall_status = "success"
        block_map = {b["id"]: b for b in blocks}
        skipped_count = 0
        timeout_error: Optional[str] = None

        # P2-15: 条件分支跳过集合
        condition_skip: Set[str] = set()

        # P1-01: DAG 并行执行（线性工作流保持串行）
        is_linear = is_linear_workflow(blocks)

        try:
            if is_linear:
                # 线性串行执行
                for block_id in execution_order:
                    # 检查取消
                    if asyncio.current_task().cancelled():
                        overall_status = "cancelled"
                        break

                    # 检查工作流整体超时
                    elapsed = time.time() - run_start_time
                    if elapsed > self.workflow_timeout:
                        timeout_error = f"工作流执行超时（{self.workflow_timeout}秒）"
                        overall_status = "failed"
                        break

                    step_result = await self._process_single_block(
                        block_id=block_id,
                        block_map=block_map,
                        adjacency=adjacency,
                        execution_order=execution_order,
                        variables=variables,
                        step_results=step_results,
                        condition_skip=condition_skip,
                        m2_available=m2_available,
                        run_start_time=run_start_time,
                    )

                    if step_result is None:
                        # 被条件跳过或依赖失败跳过
                        skipped_count += 1
                        continue

                    steps.append(step_result)
                    step_results[block_id] = step_result

                    # 条件分支处理
                    block = block_map.get(block_id, {})
                    if block.get("type", "") == "logic.condition" and step_result.get("status") == "success":
                        self._handle_condition_branch(block, step_result, condition_skip, block_map)

                    if step_result.get("status") == "cancelled":
                        overall_status = "cancelled"
                        break

                    if not step_result.get("status") == "success":
                        overall_status = "failed"
                        break
            else:
                # P1-01: DAG BFS 层级并行执行
                overall_status, steps, step_results, skipped_count, timeout_error = (
                    await self._run_dag_parallel(
                        blocks=blocks,
                        block_map=block_map,
                        adjacency=adjacency,
                        in_degree=in_degree.copy(),
                        variables=variables,
                        step_results=step_results,
                        condition_skip=condition_skip,
                        m2_available=m2_available,
                        run_start_time=run_start_time,
                        start_block=start_block,
                    )
                )

        except asyncio.CancelledError:
            overall_status = "cancelled"
        finally:
            await WorkflowEngine._release_slot()

        run_end_time = time.time()

        # 统计
        success_count = sum(1 for s in steps if s["status"] == "success")
        failed_count = sum(1 for s in steps if s["status"] == "failed")
        cancelled_count = sum(1 for s in steps if s["status"] == "cancelled")
        skipped_count = sum(1 for s in steps if s["status"] == "skipped")

        # 找出最终输出（最后一个成功的节点输出）
        final_output = None
        for step in reversed(steps):
            if step["status"] == "success":
                final_output = step.get("output")
                break

        return {
            "run_id": run_id,
            "workflow_id": workflow.get("id", ""),
            "workflow_name": workflow.get("name", ""),
            "status": overall_status,
            "started_at": run_start_time,
            "finished_at": run_end_time,
            "duration_ms": int((run_end_time - run_start_time) * 1000),
            "steps": steps,
            "total_blocks": len(execution_order),
            "success_blocks": success_count,
            "failed_blocks": failed_count,
            "skipped_blocks": skipped_count,
            "triggered_by": triggered_by,
            "trigger_type": workflow.get("trigger", {}).get("type", "manual"),
            "input_data": input_data,
            "final_output": final_output if overall_status == "success" else None,
            "error": timeout_error if timeout_error else (None if overall_status == "success" else "工作流执行失败"),
            "execution_mode": "dag_parallel" if not is_linear else "linear",
            "workflow_timeout": self.workflow_timeout,
            "block_timeout": self.block_timeout,
            "max_parallel_nodes": self.max_parallel_nodes if not is_linear else 1,
        }

    def _handle_condition_branch(
        self,
        block: Dict[str, Any],
        step_result: Dict[str, Any],
        condition_skip: Set[str],
        block_map: Dict[str, Dict[str, Any]],
    ):
        """处理条件分支积木的跳过逻辑."""
        cond_result = step_result.get("output", {}).get("result", False)
        block_config = block.get("config", {})
        true_branch = block_config.get("true_branch", [])
        false_branch = block_config.get("false_branch", [])
        next_blocks = block.get("next", [])
        if not true_branch and not false_branch and len(next_blocks) >= 2:
            true_branch = [next_blocks[0]]
            false_branch = next_blocks[1:]
        skip_branch = false_branch if cond_result else true_branch
        for sid in skip_branch:
            if sid in block_map:
                condition_skip.add(sid)

    async def _process_single_block(
        self,
        block_id: str,
        block_map: Dict[str, Dict[str, Any]],
        adjacency: Dict[str, List[str]],
        execution_order: List[str],
        variables: Dict[str, Any],
        step_results: Dict[str, Dict[str, Any]],
        condition_skip: Set[str],
        m2_available: bool,
        run_start_time: float,
    ) -> Optional[Dict[str, Any]]:
        """处理单个积木块的执行（含条件跳过、依赖检查）.

        Returns:
            执行结果字典，如果被跳过返回 None
        """
        block = block_map.get(block_id)
        if not block:
            return {
                "block_id": block_id,
                "block_name": "",
                "skill_id": "",
                "action": "default",
                "status": "skipped",
                "input": {},
                "output": None,
                "error": "积木块不存在",
                "started_at": time.time(),
                "finished_at": time.time(),
                "duration_ms": 0,
                "retry_count": 0,
            }

        # 计算前驱
        predecessors = [n for n, ns in adjacency.items() if block_id in ns]
        pred_success = 0
        pred_failed = 0
        pred_cond_skip = 0
        for pred_id in predecessors:
            if pred_id not in step_results:
                continue
            ps = step_results[pred_id].get("status")
            if ps == "success":
                pred_success += 1
            elif ps == "skipped" and step_results[pred_id].get("skip_reason") == "condition_branch":
                pred_cond_skip += 1
            else:
                pred_failed += 1

        # 条件分支跳过判断
        should_cond_skip = False
        if block_id in condition_skip:
            should_cond_skip = True
        elif predecessors and pred_cond_skip > 0 and pred_success == 0 and pred_failed == 0:
            if pred_cond_skip + pred_failed + pred_success == len(predecessors):
                should_cond_skip = True
                condition_skip.add(block_id)

        if should_cond_skip:
            skip_result = {
                "block_id": block_id,
                "block_name": block.get("name", ""),
                "skill_id": block.get("type", ""),
                "action": block.get("config", {}).get("action", "default"),
                "status": "skipped",
                "input": {},
                "output": None,
                "error": "条件分支未命中",
                "started_at": time.time(),
                "finished_at": time.time(),
                "duration_ms": 0,
                "retry_count": 0,
                "skip_reason": "condition_branch",
            }
            step_results[block_id] = skip_result
            return None  # 由调用方计数

        # 依赖失败检查
        if pred_failed > 0:
            skip_result = {
                "block_id": block_id,
                "block_name": block.get("name", ""),
                "skill_id": block.get("type", ""),
                "action": block.get("config", {}).get("action", "default"),
                "status": "skipped",
                "input": {},
                "output": None,
                "error": "前置依赖执行失败",
                "started_at": time.time(),
                "finished_at": time.time(),
                "duration_ms": 0,
                "retry_count": 0,
            }
            step_results[block_id] = skip_result
            return None  # 由调用方计数

        # 构建输入并执行
        step_input = self._build_step_input(
            block=block,
            block_index=execution_order.index(block_id) if block_id in execution_order else 0,
            variables=variables,
            step_results=step_results,
            adjacency=adjacency,
        )

        step_result, success = await self._execute_block(
            block=block,
            step_input=step_input,
            m2_available=m2_available,
        )
        return step_result

    async def _run_dag_parallel(
        self,
        blocks: List[Dict[str, Any]],
        block_map: Dict[str, Dict[str, Any]],
        adjacency: Dict[str, List[str]],
        in_degree: Dict[str, int],
        variables: Dict[str, Any],
        step_results: Dict[str, Dict[str, Any]],
        condition_skip: Set[str],
        m2_available: bool,
        run_start_time: float,
        start_block: Optional[str] = None,
    ) -> Tuple[str, List[Dict], Dict[str, Dict], int, Optional[str]]:
        """P1-01: DAG BFS 层级并行执行.

        使用 BFS 拓扑层级，同层入度已满足的节点并行执行。
        使用 asyncio.Semaphore 控制最大并发度。

        Returns:
            (overall_status, steps, step_results, skipped_count, timeout_error)
        """
        steps: List[Dict[str, Any]] = []
        overall_status = "success"
        skipped_count = 0
        timeout_error: Optional[str] = None
        semaphore = asyncio.Semaphore(self.max_parallel_nodes)

        # BFS 队列：找到所有入度为 0 的起始节点
        queue: deque = deque()
        if start_block:
            queue.append(start_block)
        else:
            for node_id, degree in in_degree.items():
                if degree == 0:
                    queue.append(node_id)

        # 按层级处理
        while queue:
            # 检查超时
            elapsed = time.time() - run_start_time
            if elapsed > self.workflow_timeout:
                timeout_error = f"工作流执行超时（{self.workflow_timeout}秒）"
                return "failed", steps, step_results, skipped_count, timeout_error

            # 检查取消
            if asyncio.current_task().cancelled():
                return "cancelled", steps, step_results, skipped_count, None

            current_layer = list(queue)
            queue.clear()

            # 过滤出可以执行的节点（入度为0且不在condition_skip中）
            executable = []
            for bid in current_layer:
                block = block_map.get(bid)
                if not block:
                    skipped_count += 1
                    continue

                # 条件跳过检查
                if bid in condition_skip:
                    skip_result = {
                        "block_id": bid,
                        "block_name": block.get("name", ""),
                        "skill_id": block.get("type", ""),
                        "action": block.get("config", {}).get("action", "default"),
                        "status": "skipped",
                        "input": {},
                        "output": None,
                        "error": "条件分支未命中",
                        "started_at": time.time(),
                        "finished_at": time.time(),
                        "duration_ms": 0,
                        "retry_count": 0,
                        "skip_reason": "condition_branch",
                    }
                    step_results[bid] = skip_result
                    steps.append(skip_result)
                    skipped_count += 1
                    # 更新后继入度
                    for next_id in adjacency.get(bid, []):
                        in_degree[next_id] = in_degree.get(next_id, 1) - 1
                        if in_degree[next_id] <= 0:
                            queue.append(next_id)
                    continue

                # 依赖失败检查
                predecessors = [n for n, ns in adjacency.items() if bid in ns]
                pred_failed = any(
                    step_results.get(p, {}).get("status") in ("failed", "cancelled")
                    for p in predecessors
                    if p in step_results
                )
                if pred_failed:
                    skip_result = {
                        "block_id": bid,
                        "block_name": block.get("name", ""),
                        "skill_id": block.get("type", ""),
                        "action": block.get("config", {}).get("action", "default"),
                        "status": "skipped",
                        "input": {},
                        "output": None,
                        "error": "前置依赖执行失败",
                        "started_at": time.time(),
                        "finished_at": time.time(),
                        "duration_ms": 0,
                        "retry_count": 0,
                    }
                    step_results[bid] = skip_result
                    steps.append(skip_result)
                    skipped_count += 1
                    for next_id in adjacency.get(bid, []):
                        in_degree[next_id] = in_degree.get(next_id, 1) - 1
                        if in_degree[next_id] <= 0:
                            queue.append(next_id)
                    continue

                executable.append(bid)

            if not executable:
                continue

            # 并行执行当前层
            async def _exec_with_semaphore(bid: str) -> Tuple[str, Dict[str, Any]]:
                async with semaphore:
                    step_input = self._build_step_input(
                        block=block_map[bid],
                        block_index=0,
                        variables=variables,
                        step_results=step_results,
                        adjacency=adjacency,
                    )
                    result, _ = await self._execute_block(
                        block=block_map[bid],
                        step_input=step_input,
                        m2_available=m2_available,
                    )
                    return bid, result

            layer_tasks = [_exec_with_semaphore(bid) for bid in executable]
            layer_results = await asyncio.gather(*layer_tasks, return_exceptions=True)

            # 处理结果
            has_failure = False
            for lr in layer_results:
                if isinstance(lr, Exception):
                    logger.error(f"[P1-01] DAG并行执行异常: {lr}")
                    continue
                bid, result = lr
                step_results[bid] = result
                steps.append(result)

                # 条件分支处理
                block = block_map.get(bid, {})
                if block.get("type", "") == "logic.condition" and result.get("status") == "success":
                    self._handle_condition_branch(block, result, condition_skip, block_map)

                if result.get("status") == "cancelled":
                    overall_status = "cancelled"
                    return overall_status, steps, step_results, skipped_count, None

                if result.get("status") != "success":
                    has_failure = True

            if has_failure:
                overall_status = "failed"

            # 更新后继入度
            for bid in executable:
                for next_id in adjacency.get(bid, []):
                    in_degree[next_id] = in_degree.get(next_id, 1) - 1
                    if in_degree[next_id] <= 0:
                        queue.append(next_id)

        return overall_status, steps, step_results, skipped_count, timeout_error
