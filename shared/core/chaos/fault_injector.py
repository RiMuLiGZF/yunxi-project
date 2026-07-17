"""
云汐故障注入工具 (Fault Injector)

Chaos Engineering 简化版，支持多种故障注入：
- 模块故障模拟（模拟模块宕机）
- 网络延迟注入
- 错误响应注入
- 资源耗尽模拟（CPU、内存、磁盘）

所有故障注入都是可控的、可恢复的，支持自动恢复。

使用方式：
    from shared.core.chaos.fault_injector import FaultInjector, FaultType

    injector = FaultInjector()
    injector.inject("m1", FaultType.MODULE_OUTAGE, duration=60)
    injector.recover("m1")
"""

from __future__ import annotations

import time
import threading
import logging
import random
from enum import Enum
from dataclasses import dataclass, field
from typing import Dict, Any, Optional, List, Callable
from datetime import datetime, timezone

logger = logging.getLogger(__name__)


# ============================================================
# 枚举
# ============================================================

class FaultType(str, Enum):
    """故障类型"""
    MODULE_OUTAGE = "module_outage"           # 模块宕机
    NETWORK_LATENCY = "network_latency"       # 网络延迟
    ERROR_RESPONSE = "error_response"         # 错误响应
    CPU_EXHAUSTION = "cpu_exhaustion"         # CPU 耗尽
    MEMORY_EXHAUSTION = "memory_exhaustion"   # 内存耗尽
    DISK_IO_SLOW = "disk_io_slow"             # 磁盘IO变慢
    CONNECTION_DROP = "connection_drop"       # 连接断开


class FaultState(str, Enum):
    """故障状态"""
    INJECTING = "injecting"    # 正在注入
    ACTIVE = "active"          # 已生效
    RECOVERING = "recovering"  # 正在恢复
    RECOVERED = "recovered"    # 已恢复
    FAILED = "failed"          # 注入失败


class FaultSeverity(str, Enum):
    """故障严重程度"""
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


# ============================================================
# 数据类
# ============================================================

@dataclass
class InjectedFault:
    """已注入的故障"""
    fault_id: str
    target: str                     # 目标（模块名、服务名等）
    fault_type: FaultType
    severity: FaultSeverity = FaultSeverity.MEDIUM
    state: FaultState = FaultState.INJECTING
    duration_seconds: float = 60.0  # 持续时间（0=永久，需手动恢复）
    injected_at: float = field(default_factory=time.time)
    auto_recover_at: float = 0.0
    recovered_at: float = 0.0
    parameters: Dict[str, Any] = field(default_factory=dict)
    error: str = ""
    impact_assessment: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "fault_id": self.fault_id,
            "target": self.target,
            "fault_type": self.fault_type.value,
            "severity": self.severity.value,
            "state": self.state.value,
            "duration_seconds": self.duration_seconds,
            "injected_at": self.injected_at,
            "auto_recover_at": self.auto_recover_at,
            "recovered_at": self.recovered_at,
            "parameters": self.parameters,
            "error": self.error,
            "impact_assessment": self.impact_assessment,
            "metadata": self.metadata,
            "elapsed_seconds": round(time.time() - self.injected_at, 2),
        }


# ============================================================
# 故障注入器
# ============================================================

class FaultInjector:
    """
    故障注入器

    提供统一的故障注入和恢复接口。
    实际的故障注入通过注册的处理器函数实现。
    """

    def __init__(self):
        self._faults: Dict[str, InjectedFault] = {}
        self._processors: Dict[FaultType, Callable] = {}
        self._recoverers: Dict[FaultType, Callable] = {}
        self._lock = threading.RLock()

        # 监控线程（自动恢复）
        self._monitor_thread: Optional[threading.Thread] = None
        self._monitor_stop = threading.Event()

        # 回调
        self._on_inject_callbacks: List[Callable[[InjectedFault], None]] = []
        self._on_recover_callbacks: List[Callable[[InjectedFault], None]] = []

        # 注册默认处理器（模拟实现）
        self._register_default_processors()

        # 资源耗尽控制
        self._cpu_stress_thread: Optional[threading.Thread] = None
        self._cpu_stress_stop = threading.Event()
        self._memory_stress_data: List[bytes] = []

    # ------------------------------------------------------------------
    #  注册故障处理器
    # ------------------------------------------------------------------

    def register_processor(self, fault_type: FaultType, inject_fn: Callable, recover_fn: Callable) -> None:
        """注册故障注入和恢复处理器"""
        self._processors[fault_type] = inject_fn
        self._recoverers[fault_type] = recover_fn

    def _register_default_processors(self) -> None:
        """注册默认的模拟处理器"""
        # 模块宕机 - 模拟实现
        self.register_processor(
            FaultType.MODULE_OUTAGE,
            self._simulate_module_outage,
            self._recover_module_outage,
        )
        # 网络延迟 - 模拟实现
        self.register_processor(
            FaultType.NETWORK_LATENCY,
            self._simulate_network_latency,
            self._recover_network_latency,
        )
        # 错误响应 - 模拟实现
        self.register_processor(
            FaultType.ERROR_RESPONSE,
            self._simulate_error_response,
            self._recover_error_response,
        )
        # CPU耗尽
        self.register_processor(
            FaultType.CPU_EXHAUSTION,
            self._simulate_cpu_exhaustion,
            self._recover_cpu_exhaustion,
        )
        # 内存耗尽
        self.register_processor(
            FaultType.MEMORY_EXHAUSTION,
            self._simulate_memory_exhaustion,
            self._recover_memory_exhaustion,
        )

    # ------------------------------------------------------------------
    #  故障注入
    # ------------------------------------------------------------------

    def inject(
        self,
        target: str,
        fault_type: FaultType,
        severity: FaultSeverity = FaultSeverity.MEDIUM,
        duration: float = 60.0,
        parameters: Optional[Dict[str, Any]] = None,
    ) -> InjectedFault:
        """
        注入故障

        Args:
            target: 目标（模块名、服务名等）
            fault_type: 故障类型
            severity: 严重程度
            duration: 持续时间（秒），0=永久
            parameters: 故障参数

        Returns:
            注入的故障信息
        """
        fault_id = f"fault_{int(time.time() * 1000)}_{random.randint(1000, 9999)}"

        fault = InjectedFault(
            fault_id=fault_id,
            target=target,
            fault_type=fault_type,
            severity=severity,
            duration_seconds=duration,
            parameters=parameters or {},
            auto_recover_at=time.time() + duration if duration > 0 else 0,
        )

        with self._lock:
            self._faults[fault_id] = fault

        logger.warning("Injecting fault: %s on %s (type=%s, severity=%s, duration=%.0fs)",
                       fault_id, target, fault_type.value, severity.value, duration)

        try:
            processor = self._processors.get(fault_type)
            if processor:
                success = processor(target, fault)
                if success:
                    fault.state = FaultState.ACTIVE
                else:
                    fault.state = FaultState.FAILED
                    fault.error = "Processor returned failure"
            else:
                fault.state = FaultState.ACTIVE  # 没有处理器也标记为激活（记录用）

        except Exception as e:
            fault.state = FaultState.FAILED
            fault.error = str(e)
            logger.error("Fault injection failed: %s", e)

        # 触发回调
        for cb in self._on_inject_callbacks:
            try:
                cb(fault)
            except Exception as e:
                logger.error("Inject callback error: %s", e)

        # 启动监控线程（自动恢复）
        if duration > 0 and fault.state == FaultState.ACTIVE:
            self._ensure_monitor()

        return fault

    def recover(self, fault_id: str) -> Optional[InjectedFault]:
        """
        手动恢复故障

        Args:
            fault_id: 故障ID

        Returns:
            恢复后的故障信息，或None
        """
        with self._lock:
            fault = self._faults.get(fault_id)

        if not fault:
            return None

        if fault.state in (FaultState.RECOVERED, FaultState.RECOVERING):
            return fault

        fault.state = FaultState.RECOVERING
        logger.info("Recovering fault: %s", fault_id)

        try:
            recoverer = self._recoverers.get(fault.fault_type)
            if recoverer:
                recoverer(fault.target, fault)

            fault.state = FaultState.RECOVERED
            fault.recovered_at = time.time()

        except Exception as e:
            fault.error = f"Recovery failed: {e}"
            logger.error("Fault recovery failed: %s", e)

        # 触发回调
        for cb in self._on_recover_callbacks:
            try:
                cb(fault)
            except Exception as e:
                logger.error("Recover callback error: %s", e)

        return fault

    def recover_all(self) -> int:
        """恢复所有故障，返回恢复数量"""
        count = 0
        with self._lock:
            fault_ids = list(self._faults.keys())

        for fid in fault_ids:
            if self.recover(fid):
                count += 1
        return count

    # ------------------------------------------------------------------
    #  默认处理器（模拟实现）
    # ------------------------------------------------------------------

    def _simulate_module_outage(self, target: str, fault: InjectedFault) -> bool:
        """模拟模块宕机（标记状态，不实际停止进程）"""
        fault.metadata["simulation"] = True
        fault.metadata["original_status"] = "running"
        fault.impact_assessment = f"Module {target} will respond with 503 errors"
        logger.warning("SIMULATED: Module outage on %s", target)
        return True

    def _recover_module_outage(self, target: str, fault: InjectedFault) -> None:
        """恢复模块宕机"""
        logger.info("RECOVERED: Module %s back online", target)

    def _simulate_network_latency(self, target: str, fault: InjectedFault) -> bool:
        """模拟网络延迟"""
        latency_ms = fault.parameters.get("latency_ms", 500)
        jitter_ms = fault.parameters.get("jitter_ms", 100)
        fault.metadata["latency_ms"] = latency_ms
        fault.metadata["jitter_ms"] = jitter_ms
        fault.impact_assessment = f"Network latency to {target}: {latency_ms}ms +/- {jitter_ms}ms"
        logger.warning("SIMULATED: Network latency to %s: %dms", target, latency_ms)
        return True

    def _recover_network_latency(self, target: str, fault: InjectedFault) -> None:
        """恢复网络延迟"""
        logger.info("RECOVERED: Network latency removed for %s", target)

    def _simulate_error_response(self, target: str, fault: InjectedFault) -> bool:
        """模拟错误响应"""
        error_rate = fault.parameters.get("error_rate", 0.5)
        error_code = fault.parameters.get("error_code", 500)
        fault.metadata["error_rate"] = error_rate
        fault.metadata["error_code"] = error_code
        fault.impact_assessment = f"{target} will return {error_code} for {error_rate*100}% of requests"
        logger.warning("SIMULATED: Error responses on %s: rate=%.0f%%, code=%d",
                       target, error_rate * 100, error_code)
        return True

    def _recover_error_response(self, target: str, fault: InjectedFault) -> None:
        """恢复错误响应"""
        logger.info("RECOVERED: Error responses removed for %s", target)

    def _simulate_cpu_exhaustion(self, target: str, fault: InjectedFault) -> bool:
        """模拟CPU耗尽（实际占用CPU）"""
        usage_percent = fault.parameters.get("usage_percent", 80)
        core_count = fault.parameters.get("core_count", 1)

        if self._cpu_stress_thread and self._cpu_stress_thread.is_alive():
            self._cpu_stress_stop.set()
            self._cpu_stress_thread.join(timeout=2)

        self._cpu_stress_stop.clear()
        self._cpu_stress_thread = threading.Thread(
            target=self._cpu_stress_worker,
            args=(usage_percent, core_count),
            name="CPUStress",
            daemon=True,
        )
        self._cpu_stress_thread.start()

        fault.metadata["usage_percent"] = usage_percent
        fault.metadata["core_count"] = core_count
        fault.impact_assessment = f"CPU usage increased to ~{usage_percent}% on {core_count} core(s)"
        logger.warning("SIMULATED: CPU exhaustion: ~%d%% usage", usage_percent)
        return True

    def _cpu_stress_worker(self, usage_percent: int, core_count: int) -> None:
        """CPU压力测试线程"""
        import math
        while not self._cpu_stress_stop.is_set():
            # 忙等：做一些计算
            for _ in range(10000):
                math.sqrt(random.random())
            # 休眠控制使用率
            sleep_time = (100 - usage_percent) / 100.0 * 0.1
            if sleep_time > 0:
                time.sleep(sleep_time)

    def _recover_cpu_exhaustion(self, target: str, fault: InjectedFault) -> None:
        """恢复CPU耗尽"""
        self._cpu_stress_stop.set()
        if self._cpu_stress_thread:
            self._cpu_stress_thread.join(timeout=2)
            self._cpu_stress_thread = None
        logger.info("RECOVERED: CPU exhaustion removed")

    def _simulate_memory_exhaustion(self, target: str, fault: InjectedFault) -> bool:
        """模拟内存耗尽（实际占用内存）"""
        mb_to_allocate = fault.parameters.get("mb", 500)

        # 分配内存
        chunk_size = 10 * 1024 * 1024  # 10MB chunks
        chunks = mb_to_allocate // 10
        for _ in range(chunks):
            self._memory_stress_data.append(bytearray(chunk_size))

        fault.metadata["allocated_mb"] = mb_to_allocate
        fault.impact_assessment = f"Memory usage increased by ~{mb_to_allocate}MB"
        logger.warning("SIMULATED: Memory exhaustion: ~%dMB allocated", mb_to_allocate)
        return True

    def _recover_memory_exhaustion(self, target: str, fault: InjectedFault) -> None:
        """恢复内存耗尽"""
        self._memory_stress_data.clear()
        import gc
        gc.collect()
        logger.info("RECOVERED: Memory exhaustion removed")

    # ------------------------------------------------------------------
    #  自动恢复监控
    # ------------------------------------------------------------------

    def _ensure_monitor(self) -> None:
        """确保监控线程运行"""
        if self._monitor_thread and self._monitor_thread.is_alive():
            return

        self._monitor_stop.clear()
        self._monitor_thread = threading.Thread(
            target=self._monitor_loop,
            name="FaultMonitor",
            daemon=True,
        )
        self._monitor_thread.start()

    def _monitor_loop(self) -> None:
        """监控循环 - 自动恢复到期的故障"""
        while not self._monitor_stop.is_set():
            try:
                now = time.time()
                to_recover = []

                with self._lock:
                    for fid, fault in self._faults.items():
                        if fault.state == FaultState.ACTIVE and fault.auto_recover_at > 0:
                            if now >= fault.auto_recover_at:
                                to_recover.append(fid)

                for fid in to_recover:
                    logger.info("Auto-recovering fault: %s", fid)
                    self.recover(fid)

                # 如果没有活跃故障了，停止监控
                with self._lock:
                    active_count = sum(
                        1 for f in self._faults.values()
                        if f.state == FaultState.ACTIVE and f.auto_recover_at > 0
                    )

                if active_count == 0:
                    break

            except Exception as e:
                logger.error("Fault monitor error: %s", e)

            self._monitor_stop.wait(1.0)

    # ------------------------------------------------------------------
    #  回调
    # ------------------------------------------------------------------

    def on_inject(self, callback: Callable[[InjectedFault], None]) -> None:
        self._on_inject_callbacks.append(callback)

    def on_recover(self, callback: Callable[[InjectedFault], None]) -> None:
        self._on_recover_callbacks.append(callback)

    # ------------------------------------------------------------------
    #  查询
    # ------------------------------------------------------------------

    def get_fault(self, fault_id: str) -> Optional[InjectedFault]:
        """获取故障信息"""
        with self._lock:
            return self._faults.get(fault_id)

    def get_active_faults(self) -> List[InjectedFault]:
        """获取所有活跃故障"""
        with self._lock:
            return [f for f in self._faults.values() if f.state == FaultState.ACTIVE]

    def list_faults(self, state: Optional[FaultState] = None) -> List[InjectedFault]:
        """列出故障"""
        with self._lock:
            faults = list(self._faults.values())

        if state:
            faults = [f for f in faults if f.state == state]

        faults.sort(key=lambda f: f.injected_at, reverse=True)
        return faults

    def clear_history(self) -> int:
        """清理已恢复的故障历史，返回清理数量"""
        with self._lock:
            to_remove = [fid for fid, f in self._faults.items() if f.state == FaultState.RECOVERED]
            for fid in to_remove:
                del self._faults[fid]
            return len(to_remove)

    def get_stats(self) -> Dict[str, Any]:
        """获取统计信息"""
        with self._lock:
            faults = list(self._faults.values())

        return {
            "total_faults": len(faults),
            "active_faults": sum(1 for f in faults if f.state == FaultState.ACTIVE),
            "recovered_faults": sum(1 for f in faults if f.state == FaultState.RECOVERED),
            "failed_faults": sum(1 for f in faults if f.state == FaultState.FAILED),
            "faults_by_type": {
                ft.value: sum(1 for f in faults if f.fault_type == ft)
                for ft in FaultType
            },
            "faults_by_severity": {
                s.value: sum(1 for f in faults if f.severity == s)
                for s in FaultSeverity
            },
        }
