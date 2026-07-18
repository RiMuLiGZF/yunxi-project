"""技能链（Skill Chain）.

将多个技能串联成流水线，支持步骤间数据传递、条件分支、错误处理。
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Callable, Optional


@dataclass
class SkillStep:
    """技能链步骤."""
    step_id: str
    skill_id: str
    name: str = ""
    description: str = ""
    input_mapping: dict[str, str] = field(default_factory=dict)  # 输入字段映射
    output_mapping: dict[str, str] = field(default_factory=dict)  # 输出字段映射
    condition: Optional[str] = None  # 条件表达式（基于前面的输出）
    error_handling: str = "stop"  # stop / continue / retry
    retry_count: int = 0
    enabled: bool = True


@dataclass
class ChainExecutionResult:
    """技能链执行结果."""
    chain_id: str
    success: bool
    total_steps: int
    completed_steps: int
    total_duration: float
    results: dict[str, Any] = field(default_factory=dict)  # step_id -> result
    errors: list[dict[str, Any]] = field(default_factory=list)
    final_output: Any = None


class SkillChain:
    """技能链.

    顺序执行多个技能步骤，步骤间传递数据。
    """

    def __init__(
        self,
        chain_id: str = "",
        name: str = "",
        description: str = "",
        user_id: str = "",
    ) -> None:
        self.chain_id = chain_id or f"chain_{uuid.uuid4().hex[:8]}"
        self.name = name
        self.description = description
        self.user_id = user_id
        self.steps: list[SkillStep] = []
        self._skill_executor: Optional[Callable] = None
        self.created_at = time.time()

    def add_step(
        self,
        skill_id: str,
        name: str = "",
        input_mapping: Optional[dict[str, str]] = None,
        output_mapping: Optional[dict[str, str]] = None,
        condition: Optional[str] = None,
        error_handling: str = "stop",
        retry_count: int = 0,
    ) -> str:
        """添加步骤.

        Returns:
            step_id
        """
        step_id = f"step_{len(self.steps) + 1}_{uuid.uuid4().hex[:4]}"
        step = SkillStep(
            step_id=step_id,
            skill_id=skill_id,
            name=name or f"步骤 {len(self.steps) + 1}",
            input_mapping=input_mapping or {},
            output_mapping=output_mapping or {},
            condition=condition,
            error_handling=error_handling,
            retry_count=retry_count,
        )
        self.steps.append(step)
        return step_id

    def remove_step(self, step_id: str) -> bool:
        """移除步骤."""
        for i, step in enumerate(self.steps):
            if step.step_id == step_id:
                self.steps.pop(i)
                return True
        return False

    def reorder_steps(self, step_ids: list[str]) -> bool:
        """重新排序步骤."""
        if len(step_ids) != len(self.steps):
            return False

        step_map = {s.step_id: s for s in self.steps}
        new_steps = []
        for sid in step_ids:
            if sid not in step_map:
                return False
            new_steps.append(step_map[sid])

        self.steps = new_steps
        return True

    def set_executor(self, executor: Callable) -> None:
        """设置技能执行器.

        executor(skill_id, input_data) -> result
        """
        self._skill_executor = executor

    # ------------------------------------------------------------------
    # 执行
    # ------------------------------------------------------------------

    def execute(
        self,
        input_data: dict[str, Any],
        executor: Optional[Callable] = None,
    ) -> ChainExecutionResult:
        """执行技能链.

        Args:
            input_data: 初始输入数据
            executor: 技能执行器（优先级高于 set_executor）

        Returns:
            ChainExecutionResult
        """
        exec_func = executor or self._skill_executor
        if not exec_func:
            raise ValueError("未设置技能执行器")

        start_time = time.time()
        results: dict[str, Any] = {}
        errors: list[dict[str, Any]] = []
        current_data = dict(input_data)  # 当前可用数据
        completed = 0

        for step in self.steps:
            if not step.enabled:
                continue

            # 检查条件
            if step.condition and not self._evaluate_condition(step.condition, current_data):
                results[step.step_id] = {
                    "skipped": True,
                    "reason": "condition_not_met",
                    "condition": step.condition,
                }
                continue

            # 构建输入
            step_input = self._build_input(step, current_data)

            # 执行（带重试）
            step_result = None
            step_error = None
            max_attempts = step.retry_count + 1

            for attempt in range(max_attempts):
                try:
                    step_result = exec_func(step.skill_id, step_input)
                    step_error = None
                    break
                except Exception as e:
                    step_error = str(e)
                    if attempt < max_attempts - 1:
                        time.sleep(0.1 * (attempt + 1))  # 简单退避
                        continue

            if step_error:
                errors.append({
                    "step_id": step.step_id,
                    "step_name": step.name,
                    "skill_id": step.skill_id,
                    "error": step_error,
                })

                if step.error_handling == "stop":
                    return ChainExecutionResult(
                        chain_id=self.chain_id,
                        success=False,
                        total_steps=len(self.steps),
                        completed_steps=completed,
                        total_duration=time.time() - start_time,
                        results=results,
                        errors=errors,
                    )
                elif step.error_handling == "continue":
                    results[step.step_id] = {"error": step_error}
                    continue
                # retry 已经在上面处理完了

            # 保存结果
            results[step.step_id] = step_result
            completed += 1

            # 更新当前数据（输出映射）
            mapped_output = self._map_output(step, step_result)
            current_data.update(mapped_output)

        duration = time.time() - start_time
        final_output = current_data

        return ChainExecutionResult(
            chain_id=self.chain_id,
            success=len(errors) == 0,
            total_steps=len([s for s in self.steps if s.enabled]),
            completed_steps=completed,
            total_duration=duration,
            results=results,
            errors=errors,
            final_output=final_output,
        )

    # ------------------------------------------------------------------
    # 辅助方法
    # ------------------------------------------------------------------

    def _build_input(
        self,
        step: SkillStep,
        current_data: dict[str, Any],
    ) -> dict[str, Any]:
        """构建步骤输入."""
        if not step.input_mapping:
            return dict(current_data)

        result = {}
        for src_key, dst_key in step.input_mapping.items():
            # src_key 可以是 "step_id.output_field" 的形式
            if "." in src_key:
                step_id, field = src_key.split(".", 1)
                if step_id in current_data:
                    step_result = current_data[step_id]
                    if isinstance(step_result, dict) and field in step_result:
                        result[dst_key] = step_result[field]
            elif src_key in current_data:
                result[dst_key] = current_data[src_key]

        return result

    def _map_output(
        self,
        step: SkillStep,
        step_result: Any,
    ) -> dict[str, Any]:
        """映射步骤输出到数据流."""
        output = {step.step_id: step_result}

        if step.output_mapping and isinstance(step_result, dict):
            for src_key, dst_key in step.output_mapping.items():
                if src_key in step_result:
                    output[dst_key] = step_result[src_key]

        return output

    def _evaluate_condition(
        self,
        condition: str,
        data: dict[str, Any],
    ) -> bool:
        """简单的条件表达式求值.

        支持简单的比较表达式，如:
        - "step_1.result > 10"
        - "step_2.success == True"
        - "step_1.count > 0 and step_2.result < 100"

        为了安全，使用简化的求值器。
        """
        try:
            # 简化：检查是否包含特定关键字
            expr = condition

            # 替换 step_id.field 为实际值（简化版本）
            for key, value in data.items():
                if isinstance(value, (int, float, str, bool)):
                    expr = expr.replace(f"{{{key}}}", str(value))

            # 非常简化的条件：支持 ==, !=, >, <, >=, <=
            # 只支持单条件
            import re
            pattern = r'(\w+)\s*(==|!=|>=|<=|>|<)\s*(.+)'
            match = re.match(pattern, condition.strip())
            if match:
                field, op, val_str = match.groups()
                field_val = data.get(field)
                if field_val is None:
                    # 尝试找 step_id 下的字段
                    for step_data in data.values():
                        if isinstance(step_data, dict) and field in step_data:
                            field_val = step_data[field]
                            break

                if field_val is None:
                    return False

                # 类型转换
                try:
                    val = type(field_val)(val_str)
                except (ValueError, TypeError):
                    val = val_str

                if op == "==":
                    return field_val == val
                elif op == "!=":
                    return field_val != val
                elif op == ">":
                    return field_val > val
                elif op == "<":
                    return field_val < val
                elif op == ">=":
                    return field_val >= val
                elif op == "<=":
                    return field_val <= val

            return True  # 默认通过
        except Exception:
            return True  # 出错时默认通过


class SkillChainManager:
    """技能链管理器."""

    def __init__(self) -> None:
        self._chains: dict[str, SkillChain] = {}
        self._user_chains: dict[str, list[str]] = {}

    def create_chain(
        self,
        name: str,
        steps: list[dict[str, Any]],
        user_id: str = "",
        description: str = "",
    ) -> SkillChain:
        """创建技能链."""
        chain = SkillChain(name=name, description=description, user_id=user_id)

        for step_data in steps:
            chain.add_step(
                skill_id=step_data["skill_id"],
                name=step_data.get("name", ""),
                input_mapping=step_data.get("input_mapping"),
                output_mapping=step_data.get("output_mapping"),
                condition=step_data.get("condition"),
                error_handling=step_data.get("error_handling", "stop"),
                retry_count=step_data.get("retry_count", 0),
            )

        self._chains[chain.chain_id] = chain
        if user_id:
            if user_id not in self._user_chains:
                self._user_chains[user_id] = []
            self._user_chains[user_id].append(chain.chain_id)

        return chain

    def get_chain(self, chain_id: str) -> Optional[SkillChain]:
        """获取技能链."""
        return self._chains.get(chain_id)

    def list_chains(self, user_id: str = "") -> list[dict[str, Any]]:
        """列出技能链."""
        if user_id:
            chain_ids = self._user_chains.get(user_id, [])
            chains = [self._chains[cid] for cid in chain_ids if cid in self._chains]
        else:
            chains = list(self._chains.values())

        return [
            {
                "chain_id": c.chain_id,
                "name": c.name,
                "description": c.description,
                "step_count": len(c.steps),
                "created_at": c.created_at,
            }
            for c in chains
        ]

    def delete_chain(self, chain_id: str, user_id: str = "") -> bool:
        """删除技能链."""
        if chain_id not in self._chains:
            return False

        chain = self._chains[chain_id]
        if user_id and chain.user_id != user_id:
            return False

        del self._chains[chain_id]
        if chain.user_id and chain.user_id in self._user_chains:
            if chain_id in self._user_chains[chain.user_id]:
                self._user_chains[chain.user_id].remove(chain_id)

        return True

    def duplicate_chain(self, chain_id: str, user_id: str = "") -> Optional[SkillChain]:
        """复制技能链."""
        original = self._chains.get(chain_id)
        if not original:
            return None

        new_chain = SkillChain(
            name=f"{original.name} (副本)",
            description=original.description,
            user_id=user_id,
        )

        for step in original.steps:
            new_chain.add_step(
                skill_id=step.skill_id,
                name=step.name,
                input_mapping=dict(step.input_mapping),
                output_mapping=dict(step.output_mapping),
                condition=step.condition,
                error_handling=step.error_handling,
                retry_count=step.retry_count,
            )

        self._chains[new_chain.chain_id] = new_chain
        if user_id:
            if user_id not in self._user_chains:
                self._user_chains[user_id] = []
            self._user_chains[user_id].append(new_chain.chain_id)

        return new_chain

    def execute_chain(
        self,
        chain_id: str,
        input_data: dict[str, Any],
        executor: Callable,
    ) -> Optional[ChainExecutionResult]:
        """执行技能链."""
        chain = self._chains.get(chain_id)
        if not chain:
            return None

        return chain.execute(input_data, executor=executor)
