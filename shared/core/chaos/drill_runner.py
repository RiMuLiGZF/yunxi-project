"""
云汐演练脚本运行器 (Drill Runner)

提供故障演练脚本的编排和执行：
- 预设演练脚本（模块宕机、数据库切换、网络分区、全系统恢复）
- 自定义演练步骤
- 演练状态跟踪
- 演练数据采集

使用方式：
    from shared.core.chaos.drill_runner import DrillsRunner, module_outage_drill

    runner = DrillsRunner()
    result = runner.run_drill(module_outage_drill("m1"))
"""

from __future__ import annotations

import time
import threading
import logging
from enum import Enum
from dataclasses import dataclass, field
from typing import Dict, Any, Optional, List, Callable
from datetime import datetime, timezone

from .fault_injector import FaultInjector, FaultType, FaultSeverity

logger = logging.getLogger(__name__)


# ============================================================
# 枚举
# ============================================================

class DrillStatus(str, Enum):
    """演练状态"""
    PENDING = "pending"
    RUNNING = "running"
    PAUSED = "paused"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class StepStatus(str, Enum):
    """步骤状态"""
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"


# ============================================================
# 数据类
# ============================================================

@dataclass
class DrillStep:
    """演练步骤"""
    step_id: str
    name: str
    description: str = ""
    action: Optional[Callable[["DrillContext"], Dict[str, Any]]] = None
    verify: Optional[Callable[["DrillContext"], bool]] = None
    wait_before: float = 0.0      # 执行前等待（秒）
    wait_after: float = 0.0       # 执行后等待（秒）
    timeout: float = 300.0        # 超时（秒）
    critical: bool = True         # 是否关键步骤（失败则演练失败）
    status: StepStatus = StepStatus.PENDING
    result: Dict[str, Any] = field(default_factory=dict)
    error: str = ""
    duration_seconds: float = 0.0
    started_at: float = 0.0
    completed_at: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "step_id": self.step_id,
            "name": self.name,
            "description": self.description,
            "status": self.status.value,
            "critical": self.critical,
            "timeout": self.timeout,
            "result": self.result,
            "error": self.error,
            "duration_seconds": round(self.duration_seconds, 3),
            "started_at": self.started_at,
            "completed_at": self.completed_at,
        }


@dataclass
class DrillScript:
    """演练脚本"""
    drill_id: str
    name: str
    description: str = ""
    category: str = "general"          # 演练分类
    severity: str = "medium"           # 影响级别
    estimated_duration: float = 300.0  # 预计耗时（秒）
    prerequisites: List[str] = field(default_factory=list)  # 前置条件
    steps: List[DrillStep] = field(default_factory=list)
    rollback_steps: List[DrillStep] = field(default_factory=list)  # 回滚步骤
    tags: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "drill_id": self.drill_id,
            "name": self.name,
            "description": self.description,
            "category": self.category,
            "severity": self.severity,
            "estimated_duration": self.estimated_duration,
            "prerequisites": self.prerequisites,
            "step_count": len(self.steps),
            "steps": [s.to_dict() for s in self.steps],
            "rollback_steps": [s.to_dict() for s in self.rollback_steps],
            "tags": self.tags,
        }


@dataclass
class DrillContext:
    """演练上下文（步骤间传递数据）"""
    drill_id: str
    drill_name: str
    injector: FaultInjector
    data: Dict[str, Any] = field(default_factory=dict)
    events: List[Dict[str, Any]] = field(default_factory=list)
    metrics: Dict[str, Any] = field(default_factory=dict)

    def set(self, key: str, value: Any) -> None:
        self.data[key] = value

    def get(self, key: str, default: Any = None) -> Any:
        return self.data.get(key, default)

    def add_event(self, event_type: str, message: str, **kwargs) -> None:
        self.events.append({
            "timestamp": time.time(),
            "event_type": event_type,
            "message": message,
            **kwargs,
        })

    def set_metric(self, name: str, value: Any) -> None:
        self.metrics[name] = value


# ============================================================
# 演练运行器
# ============================================================

class DrillsRunner:
    """
    演练运行器

    执行演练脚本，收集数据，生成结果。
    """

    def __init__(self, injector: Optional[FaultInjector] = None):
        self.injector = injector or FaultInjector()
        self._running_drills: Dict[str, Dict[str, Any]] = {}
        self._lock = threading.RLock()
        self._results: Dict[str, Dict[str, Any]] = {}

    # ------------------------------------------------------------------
    #  执行演练
    # ------------------------------------------------------------------

    def run_drill(self, script: DrillScript) -> Dict[str, Any]:
        """
        同步执行演练脚本

        Args:
            script: 演练脚本

        Returns:
            演练结果
        """
        context = DrillContext(
            drill_id=script.drill_id,
            drill_name=script.name,
            injector=self.injector,
        )

        result = {
            "drill_id": script.drill_id,
            "drill_name": script.name,
            "status": DrillStatus.RUNNING,
            "start_time": time.time(),
            "end_time": 0,
            "duration_seconds": 0,
            "total_steps": len(script.steps),
            "completed_steps": 0,
            "failed_steps": 0,
            "skipped_steps": 0,
            "steps": [],
            "events": [],
            "metrics": {},
            "error": "",
        }

        context.add_event("drill_started", f"Drill started: {script.name}")

        try:
            for step in script.steps:
                step_result = self._execute_step(step, context)
                result["steps"].append(step.to_dict())

                if step.status == StepStatus.COMPLETED:
                    result["completed_steps"] += 1
                elif step.status == StepStatus.SKIPPED:
                    result["skipped_steps"] += 1
                elif step.status == StepStatus.FAILED:
                    result["failed_steps"] += 1
                    if step.critical:
                        # 关键步骤失败，执行回滚
                        context.add_event("drill_failed",
                                          f"Critical step failed: {step.name}, starting rollback")
                        self._execute_rollback(script, context)
                        result["status"] = DrillStatus.FAILED
                        result["error"] = f"Critical step failed: {step.error}"
                        break

            if result["status"] == DrillStatus.RUNNING:
                result["status"] = DrillStatus.COMPLETED
                context.add_event("drill_completed", f"Drill completed: {script.name}")

        except Exception as e:
            result["status"] = DrillStatus.FAILED
            result["error"] = str(e)
            context.add_event("drill_error", f"Drill error: {e}")
            logger.error("Drill execution error: %s", e)

        result["end_time"] = time.time()
        result["duration_seconds"] = round(result["end_time"] - result["start_time"], 3)
        result["events"] = context.events
        result["metrics"] = context.metrics

        # 保存结果
        with self._lock:
            self._results[script.drill_id] = result

        # 确保所有故障都被清理
        self.injector.recover_all()

        logger.info("Drill %s finished: %s (%.2fs)",
                    script.drill_id, result["status"].value, result["duration_seconds"])
        return result

    def run_drill_async(self, script: DrillScript, callback: Optional[Callable] = None) -> str:
        """
        异步执行演练脚本

        Args:
            script: 演练脚本
            callback: 完成回调

        Returns:
            演练ID
        """
        def _run():
            result = self.run_drill(script)
            if callback:
                try:
                    callback(result)
                except Exception as e:
                    logger.error("Drill callback error: %s", e)

        thread = threading.Thread(
            target=_run,
            name=f"Drill-{script.drill_id}",
            daemon=True,
        )
        thread.start()
        return script.drill_id

    def _execute_step(self, step: DrillStep, context: DrillContext) -> DrillStep:
        """执行单个步骤"""
        step.status = StepStatus.RUNNING
        step.started_at = time.time()

        context.add_event("step_started", f"Step started: {step.name}")

        try:
            # 执行前等待
            if step.wait_before > 0:
                time.sleep(step.wait_before)

            # 执行动作
            if step.action:
                result = step.action(context)
                step.result = result or {}

            # 执行验证
            if step.verify:
                passed = step.verify(context)
                if not passed:
                    step.status = StepStatus.FAILED
                    step.error = "Verification failed"
                    context.add_event("step_verify_failed", f"Verification failed: {step.name}")
                    return step

            # 执行后等待
            if step.wait_after > 0:
                time.sleep(step.wait_after)

            step.status = StepStatus.COMPLETED
            context.add_event("step_completed", f"Step completed: {step.name}")

        except Exception as e:
            step.status = StepStatus.FAILED
            step.error = str(e)
            context.add_event("step_error", f"Step error: {step.name} - {e}")
            logger.error("Drill step error: %s", e)

        step.completed_at = time.time()
        step.duration_seconds = step.completed_at - step.started_at
        return step

    def _execute_rollback(self, script: DrillScript, context: DrillContext) -> None:
        """执行回滚步骤"""
        context.add_event("rollback_started", "Starting rollback")
        for step in script.rollback_steps:
            try:
                if step.action:
                    step.action(context)
                context.add_event("rollback_step", f"Rollback step: {step.name}")
            except Exception as e:
                context.add_event("rollback_error", f"Rollback error: {e}")
                logger.error("Rollback step error: %s", e)
        context.add_event("rollback_completed", "Rollback completed")

    # ------------------------------------------------------------------
    #  结果查询
    # ------------------------------------------------------------------

    def get_result(self, drill_id: str) -> Optional[Dict[str, Any]]:
        """获取演练结果"""
        with self._lock:
            return self._results.get(drill_id)

    def list_results(self, limit: int = 20) -> List[Dict[str, Any]]:
        """列出演练结果"""
        with self._lock:
            results = list(self._results.values())
            results.sort(key=lambda r: r.get("start_time", 0), reverse=True)
            return results[:limit]

    def clear_results(self) -> int:
        """清理结果，返回清理数量"""
        with self._lock:
            count = len(self._results)
            self._results.clear()
            return count


# ============================================================
# 预设演练脚本
# ============================================================

def module_outage_drill(module_name: str, duration: float = 60.0) -> DrillScript:
    """
    模块宕机恢复演练

    目标：验证模块故障后系统的故障转移和恢复能力
    """
    steps = [
        DrillStep(
            step_id="check_initial_state",
            name="检查初始状态",
            description="确认模块在故障注入前正常运行",
            action=lambda ctx: _check_module_health(ctx, module_name),
            verify=lambda ctx: ctx.get("module_healthy", False),
            critical=True,
        ),
        DrillStep(
            step_id="inject_outage",
            name="注入模块故障",
            description=f"模拟 {module_name} 模块宕机",
            action=lambda ctx: _inject_module_outage(ctx, module_name, duration),
            wait_after=5.0,
            critical=True,
        ),
        DrillStep(
            step_id="verify_failure_detected",
            name="验证故障检测",
            description="确认系统检测到模块故障",
            action=lambda ctx: _check_module_unhealthy(ctx, module_name),
            verify=lambda ctx: ctx.get("module_unhealthy", False),
            critical=True,
        ),
        DrillStep(
            step_id="verify_failover",
            name="验证故障转移",
            description="确认故障转移机制生效",
            action=lambda ctx: _check_failover(ctx, module_name),
            verify=lambda ctx: ctx.get("failover_active", False),
            wait_after=10.0,
            critical=False,
        ),
        DrillStep(
            step_id="recover_module",
            name="恢复模块",
            description="手动恢复模块运行",
            action=lambda ctx: _recover_module(ctx, module_name),
            wait_after=5.0,
            critical=True,
        ),
        DrillStep(
            step_id="verify_recovery",
            name="验证恢复",
            description="确认模块已恢复正常",
            action=lambda ctx: _check_module_health(ctx, module_name),
            verify=lambda ctx: ctx.get("module_healthy", False),
            critical=True,
        ),
    ]

    rollback_steps = [
        DrillStep(
            step_id="emergency_recover",
            name="紧急恢复",
            description="紧急恢复所有注入的故障",
            action=lambda ctx: _recover_all(ctx),
        ),
    ]

    return DrillScript(
        drill_id=f"module_outage_{module_name}_{int(time.time())}",
        name=f"模块宕机恢复演练 - {module_name}",
        description=f"模拟 {module_name} 模块宕机，验证故障检测、故障转移和恢复能力",
        category="availability",
        severity="high",
        estimated_duration=120.0,
        prerequisites=[
            f"{module_name} 模块正常运行",
            "故障转移机制已配置",
        ],
        steps=steps,
        rollback_steps=rollback_steps,
        tags=["availability", "failover", module_name],
    )


def database_failover_drill(db_name: str = "primary") -> DrillScript:
    """
    数据库故障切换演练

    目标：验证数据库故障后的自动切换能力
    """
    steps = [
        DrillStep(
            step_id="check_db_health",
            name="检查数据库状态",
            description="确认主数据库正常运行",
            action=lambda ctx: _check_database_health(ctx, db_name),
            verify=lambda ctx: ctx.get("db_healthy", False),
            critical=True,
        ),
        DrillStep(
            step_id="simulate_db_failure",
            name="模拟数据库故障",
            description="模拟主数据库不可用",
            action=lambda ctx: _simulate_db_failure(ctx, db_name),
            wait_after=3.0,
            critical=True,
        ),
        DrillStep(
            step_id="verify_db_failover",
            name="验证数据库切换",
            description="确认系统自动切换到备用数据库",
            action=lambda ctx: _check_db_failover(ctx, db_name),
            verify=lambda ctx: ctx.get("db_failover_done", False),
            wait_after=10.0,
            critical=True,
        ),
        DrillStep(
            step_id="verify_data_access",
            name="验证数据访问",
            description="确认切换后数据可以正常访问",
            action=lambda ctx: _verify_data_access(ctx),
            verify=lambda ctx: ctx.get("data_access_ok", False),
            critical=True,
        ),
        DrillStep(
            step_id="restore_primary",
            name="恢复主数据库",
            description="恢复主数据库并回切",
            action=lambda ctx: _restore_db_primary(ctx, db_name),
            wait_after=5.0,
            critical=False,
        ),
    ]

    rollback_steps = [
        DrillStep(
            step_id="restore_all_dbs",
            name="恢复所有数据库",
            action=lambda ctx: _recover_all(ctx),
        ),
    ]

    return DrillScript(
        drill_id=f"db_failover_{db_name}_{int(time.time())}",
        name=f"数据库故障切换演练 - {db_name}",
        description=f"模拟 {db_name} 数据库故障，验证自动切换和数据访问能力",
        category="data",
        severity="critical",
        estimated_duration=180.0,
        prerequisites=[
            "主备数据库已配置",
            "自动切换机制已启用",
        ],
        steps=steps,
        rollback_steps=rollback_steps,
        tags=["database", "failover", "data"],
    )


def network_partition_drill(target_module: str) -> DrillScript:
    """
    网络分区演练

    目标：验证网络分区情况下的系统行为和恢复能力
    """
    steps = [
        DrillStep(
            step_id="baseline_check",
            name="基线检查",
            description="记录故障前系统状态",
            action=lambda ctx: _record_baseline(ctx),
            critical=True,
        ),
        DrillStep(
            step_id="inject_latency",
            name="注入网络延迟",
            description=f"模拟到 {target_module} 的网络延迟",
            action=lambda ctx: _inject_network_latency(ctx, target_module, 500, 200),
            wait_after=10.0,
            critical=True,
        ),
        DrillStep(
            step_id="verify_degraded",
            name="验证降级行为",
            description="确认系统在高延迟下的降级行为",
            action=lambda ctx: _check_degraded_behavior(ctx, target_module),
            verify=lambda ctx: ctx.get("degraded_ok", True),
            critical=False,
        ),
        DrillStep(
            step_id="inject_partition",
            name="模拟网络分区",
            description=f"模拟完全断开到 {target_module} 的连接",
            action=lambda ctx: _inject_connection_drop(ctx, target_module),
            wait_after=5.0,
            critical=True,
        ),
        DrillStep(
            step_id="verify_partition_handling",
            name="验证分区处理",
            description="确认系统正确处理网络分区",
            action=lambda ctx: _check_partition_handling(ctx, target_module),
            critical=False,
        ),
        DrillStep(
            step_id="restore_network",
            name="恢复网络",
            description="恢复网络连接",
            action=lambda ctx: _recover_network(ctx, target_module),
            wait_after=10.0,
            critical=True,
        ),
        DrillStep(
            step_id="verify_full_recovery",
            name="验证完全恢复",
            description="确认系统恢复到正常状态",
            action=lambda ctx: _check_full_recovery(ctx),
            verify=lambda ctx: ctx.get("fully_recovered", True),
            critical=True,
        ),
    ]

    rollback_steps = [
        DrillStep(
            step_id="restore_network_all",
            name="恢复所有网络",
            action=lambda ctx: _recover_all(ctx),
        ),
    ]

    return DrillScript(
        drill_id=f"network_partition_{target_module}_{int(time.time())}",
        name=f"网络分区演练 - {target_module}",
        description=f"模拟到 {target_module} 的网络延迟和分区，验证系统的容错和恢复能力",
        category="network",
        severity="high",
        estimated_duration=200.0,
        prerequisites=[
            f"{target_module} 模块正常运行",
            "网络监控已启用",
        ],
        steps=steps,
        rollback_steps=rollback_steps,
        tags=["network", "partition", "resilience"],
    )


def full_system_recovery_drill() -> DrillScript:
    """
    全系统故障恢复演练

    目标：验证全系统故障后的恢复能力
    """
    steps = [
        DrillStep(
            step_id="system_snapshot",
            name="系统快照",
            description="记录故障前完整系统状态",
            action=lambda ctx: _record_system_snapshot(ctx),
            critical=True,
        ),
        DrillStep(
            step_id="simulate_cascading_failure",
            name="模拟级联故障",
            description="注入多个故障模拟全系统故障",
            action=lambda ctx: _simulate_cascading_failure(ctx),
            wait_after=5.0,
            critical=True,
        ),
        DrillStep(
            step_id="verify_system_degraded",
            name="验证系统降级",
            description="确认系统进入降级状态",
            action=lambda ctx: _check_system_degraded(ctx),
            critical=False,
        ),
        DrillStep(
            step_id="initiate_recovery",
            name="启动恢复流程",
            description="按顺序恢复各组件",
            action=lambda ctx: _initiate_system_recovery(ctx),
            wait_after=15.0,
            critical=True,
        ),
        DrillStep(
            step_id="verify_service_restoration",
            name="验证服务恢复",
            description="确认核心服务已恢复",
            action=lambda ctx: _verify_service_restoration(ctx),
            verify=lambda ctx: ctx.get("core_services_up", False),
            critical=True,
        ),
        DrillStep(
            step_id="verify_data_integrity",
            name="验证数据完整性",
            description="确认数据完整无丢失",
            action=lambda ctx: _verify_data_integrity(ctx),
            verify=lambda ctx: ctx.get("data_integrity_ok", True),
            critical=True,
        ),
        DrillStep(
            step_id="final_verification",
            name="最终验证",
            description="全系统健康检查",
            action=lambda ctx: _final_system_check(ctx),
            verify=lambda ctx: ctx.get("system_healthy", False),
            critical=True,
        ),
    ]

    rollback_steps = [
        DrillStep(
            step_id="emergency_full_recovery",
            name="紧急全量恢复",
            action=lambda ctx: _recover_all(ctx),
        ),
    ]

    return DrillScript(
        drill_id=f"full_system_recovery_{int(time.time())}",
        name="全系统故障恢复演练",
        description="模拟全系统级联故障，验证完整的恢复流程和数据完整性",
        category="system",
        severity="critical",
        estimated_duration=300.0,
        prerequisites=[
            "全系统正常运行",
            "备份已验证",
            "恢复流程文档齐全",
        ],
        steps=steps,
        rollback_steps=rollback_steps,
        tags=["system", "recovery", "disaster"],
    )


# ============================================================
# 辅助函数（演练步骤动作的模拟实现）
# ============================================================

def _check_module_health(ctx: DrillContext, module: str) -> Dict[str, Any]:
    ctx.set("module_healthy", True)
    ctx.set_metric(f"{module}_initial_health", "healthy")
    return {"status": "healthy", "module": module}


def _inject_module_outage(ctx: DrillContext, module: str, duration: float) -> Dict[str, Any]:
    fault = ctx.injector.inject(
        target=module,
        fault_type=FaultType.MODULE_OUTAGE,
        severity=FaultSeverity.HIGH,
        duration=duration,
    )
    ctx.set("outage_fault_id", fault.fault_id)
    return {"fault_id": fault.fault_id, "module": module}


def _check_module_unhealthy(ctx: DrillContext, module: str) -> Dict[str, Any]:
    ctx.set("module_unhealthy", True)
    return {"status": "unhealthy", "detected": True}


def _check_failover(ctx: DrillContext, module: str) -> Dict[str, Any]:
    ctx.set("failover_active", True)
    ctx.set_metric("failover_time_seconds", 3.5)
    return {"failover_active": True, "standby_taking_over": True}


def _recover_module(ctx: DrillContext, module: str) -> Dict[str, Any]:
    fault_id = ctx.get("outage_fault_id", "")
    if fault_id:
        ctx.injector.recover(fault_id)
    return {"recovered": True, "module": module}


def _recover_all(ctx: DrillContext) -> Dict[str, Any]:
    count = ctx.injector.recover_all()
    return {"recovered_count": count}


def _check_database_health(ctx: DrillContext, db_name: str) -> Dict[str, Any]:
    ctx.set("db_healthy", True)
    ctx.set_metric(f"{db_name}_initial_status", "healthy")
    return {"database": db_name, "status": "healthy"}


def _simulate_db_failure(ctx: DrillContext, db_name: str) -> Dict[str, Any]:
    fault = ctx.injector.inject(
        target=f"db_{db_name}",
        fault_type=FaultType.MODULE_OUTAGE,
        severity=FaultSeverity.CRITICAL,
        duration=120,
    )
    ctx.set("db_fault_id", fault.fault_id)
    return {"fault_id": fault.fault_id, "database": db_name}


def _check_db_failover(ctx: DrillContext, db_name: str) -> Dict[str, Any]:
    ctx.set("db_failover_done", True)
    ctx.set_metric("db_failover_time_seconds", 5.2)
    return {"failover_completed": True, "standby_db": "active"}


def _verify_data_access(ctx: DrillContext) -> Dict[str, Any]:
    ctx.set("data_access_ok", True)
    return {"data_access": "ok", "read_write": "working"}


def _restore_db_primary(ctx: DrillContext, db_name: str) -> Dict[str, Any]:
    fault_id = ctx.get("db_fault_id", "")
    if fault_id:
        ctx.injector.recover(fault_id)
    return {"primary_restored": True}


def _record_baseline(ctx: DrillContext) -> Dict[str, Any]:
    ctx.set("baseline_recorded", True)
    ctx.set_metric("baseline_latency_ms", 12)
    ctx.set_metric("baseline_error_rate", 0.01)
    return {"baseline": "recorded"}


def _inject_network_latency(ctx: DrillContext, target: str, latency: int, jitter: int) -> Dict[str, Any]:
    fault = ctx.injector.inject(
        target=target,
        fault_type=FaultType.NETWORK_LATENCY,
        severity=FaultSeverity.MEDIUM,
        duration=120,
        parameters={"latency_ms": latency, "jitter_ms": jitter},
    )
    ctx.set("latency_fault_id", fault.fault_id)
    return {"fault_id": fault.fault_id, "latency_ms": latency}


def _check_degraded_behavior(ctx: DrillContext, target: str) -> Dict[str, Any]:
    ctx.set("degraded_ok", True)
    ctx.set_metric("degraded_latency_ms", 520)
    return {"degraded": True, "system_still_functional": True}


def _inject_connection_drop(ctx: DrillContext, target: str) -> Dict[str, Any]:
    fault = ctx.injector.inject(
        target=target,
        fault_type=FaultType.CONNECTION_DROP,
        severity=FaultSeverity.HIGH,
        duration=60,
    )
    ctx.set("partition_fault_id", fault.fault_id)
    return {"fault_id": fault.fault_id, "target": target}


def _check_partition_handling(ctx: DrillContext, target: str) -> Dict[str, Any]:
    return {"partition_detected": True, "circuit_breaker_open": True}


def _recover_network(ctx: DrillContext, target: str) -> Dict[str, Any]:
    for fid in ["latency_fault_id", "partition_fault_id"]:
        fault_id = ctx.get(fid, "")
        if fault_id:
            ctx.injector.recover(fault_id)
    return {"network_recovered": True}


def _check_full_recovery(ctx: DrillContext) -> Dict[str, Any]:
    ctx.set("fully_recovered", True)
    return {"recovery": "complete"}


def _record_system_snapshot(ctx: DrillContext) -> Dict[str, Any]:
    ctx.set("system_snapshot", True)
    ctx.set_metric("services_count", 12)
    ctx.set_metric("healthy_services", 12)
    return {"snapshot": "taken"}


def _simulate_cascading_failure(ctx: DrillContext) -> Dict[str, Any]:
    faults = []
    faults.append(ctx.injector.inject("m1", FaultType.MODULE_OUTAGE, FaultSeverity.HIGH, 120).fault_id)
    faults.append(ctx.injector.inject("m2", FaultType.ERROR_RESPONSE, FaultSeverity.MEDIUM, 90,
                                       {"error_rate": 0.3}).fault_id)
    ctx.set("cascading_faults", faults)
    return {"faults_injected": len(faults)}


def _check_system_degraded(ctx: DrillContext) -> Dict[str, Any]:
    return {"system_status": "degraded", "core_services": "partial"}


def _initiate_system_recovery(ctx: DrillContext) -> Dict[str, Any]:
    count = ctx.injector.recover_all()
    return {"recovered_components": count}


def _verify_service_restoration(ctx: DrillContext) -> Dict[str, Any]:
    ctx.set("core_services_up", True)
    return {"core_services": "up", "restored_count": 12}


def _verify_data_integrity(ctx: DrillContext) -> Dict[str, Any]:
    ctx.set("data_integrity_ok", True)
    return {"integrity": "verified", "data_loss": "none"}


def _final_system_check(ctx: DrillContext) -> Dict[str, Any]:
    ctx.set("system_healthy", True)
    return {"system_health": "healthy", "all_services": "running"}
