"""边缘任务调度器.

提供边缘计算任务调度能力：
1. 三种调度策略：本地优先、云端优先、自适应调度
2. 任务分片：大任务拆分为小任务，并行处理，结果合并
3. 算力评估：设备性能评分、电池状态、网络状态、温度/负载

可插拔设计：不影响现有路由决策引擎 (route_engine.py)，
作为增强层提供更细粒度的边缘任务调度能力。
"""

from __future__ import annotations

import asyncio
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable

import structlog

logger = structlog.get_logger(__name__)

# ---------------------------------------------------------------------------
# 枚举类型
# ---------------------------------------------------------------------------


class SchedulingStrategy(str, Enum):
    """调度策略枚举.

    Attributes:
        LOCAL_FIRST: 本地优先（低延迟需求）
        CLOUD_FIRST: 云端优先（高算力需求）
        ADAPTIVE: 自适应调度（根据网络/算力/电量动态调整）
    """

    LOCAL_FIRST = "local_first"
    CLOUD_FIRST = "cloud_first"
    ADAPTIVE = "adaptive"


class TaskStatus(str, Enum):
    """任务状态枚举.

    Attributes:
        PENDING: 等待调度.
        SCHEDULED: 已调度.
        RUNNING: 执行中.
        COMPLETED: 已完成.
        FAILED: 失败.
        CANCELLED: 已取消.
    """

    PENDING = "pending"
    SCHEDULED = "scheduled"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class TaskPriority(str, Enum):
    """任务优先级枚举.

    Attributes:
        LOW: 低优先级.
        NORMAL: 普通优先级.
        HIGH: 高优先级.
        CRITICAL: 关键优先级.
    """

    LOW = "low"
    NORMAL = "normal"
    HIGH = "high"
    CRITICAL = "critical"


class ExecutionTarget(str, Enum):
    """执行目标枚举.

    Attributes:
        LOCAL: 本地执行.
        CLOUD: 云端执行.
        HYBRID: 混合执行（部分本地，部分云端）.
    """

    LOCAL = "local"
    CLOUD = "cloud"
    HYBRID = "hybrid"


# ---------------------------------------------------------------------------
# 数据结构
# ---------------------------------------------------------------------------


@dataclass
class DeviceComputeProfile:
    """设备算力画像.

    Attributes:
        device_id: 设备 ID.
        performance_score: 综合性能评分（0-100）.
        cpu_cores: CPU 核心数.
        cpu_usage: CPU 使用率（0-100）.
        memory_gb: 内存大小（GB）.
        memory_usage: 内存使用率（0-100）.
        gpu_available: 是否有 GPU.
        gpu_vram_gb: GPU 显存（GB）.
        battery_level: 电池电量（0-100，-1 表示无电池）.
        battery_charging: 是否充电中.
        network_type: 网络类型（wifi/5g/4g/ethernet/none）.
        network_latency_ms: 网络延迟（毫秒）.
        network_bandwidth_mbps: 网络带宽（Mbps）.
        temperature_celsius: 温度（摄氏度）.
        thermal_throttling: 是否温度降频.
        last_updated: 最后更新时间.
    """

    device_id: str
    performance_score: float = 50.0
    cpu_cores: int = 4
    cpu_usage: float = 0.0
    memory_gb: float = 8.0
    memory_usage: float = 0.0
    gpu_available: bool = False
    gpu_vram_gb: float = 0.0
    battery_level: float = -1.0
    battery_charging: bool = False
    network_type: str = "none"
    network_latency_ms: float = 9999.0
    network_bandwidth_mbps: float = 0.0
    temperature_celsius: float = 25.0
    thermal_throttling: bool = False
    last_updated: float = field(default_factory=time.time)

    def is_capable_of(self, task_complexity: float) -> bool:
        """判断设备是否有能力处理指定复杂度的任务.

        Args:
            task_complexity: 任务复杂度（0-100）.

        Returns:
            是否有能力处理.
        """
        # 性能评分必须高于任务复杂度
        if self.performance_score < task_complexity * 0.5:
            return False
        # 温度降频时不处理高复杂度任务
        if self.thermal_throttling and task_complexity > 50:
            return False
        # 电量不足时不处理高复杂度任务
        if 0 < self.battery_level < 20 and not self.battery_charging and task_complexity > 30:
            return False
        return True


@dataclass
class TaskFragment:
    """任务分片.

    Attributes:
        fragment_id: 分片 ID.
        task_id: 所属任务 ID.
        index: 分片序号.
        total_fragments: 总分片数.
        data: 分片数据.
        target: 执行目标（local/cloud）.
        status: 分片状态.
        result: 分片结果.
        error: 错误信息.
        started_at: 开始时间.
        completed_at: 完成时间.
    """

    fragment_id: str
    task_id: str
    index: int
    total_fragments: int
    data: dict[str, Any] = field(default_factory=dict)
    target: ExecutionTarget = ExecutionTarget.LOCAL
    status: TaskStatus = TaskStatus.PENDING
    result: Any = None
    error: str = ""
    started_at: float = 0.0
    completed_at: float = 0.0


@dataclass
class EdgeTask:
    """边缘计算任务.

    Attributes:
        task_id: 任务 ID.
        name: 任务名称.
        task_type: 任务类型.
        data: 任务数据.
        priority: 优先级.
        complexity: 复杂度估算（0-100）.
        latency_requirement_ms: 延迟要求（毫秒，-1 表示无要求）.
        privacy_level: 隐私等级（0-10，越高越敏感）.
        strategy: 调度策略.
        target: 最终执行目标.
        status: 任务状态.
        result: 任务结果.
        error: 错误信息.
        fragments: 任务分片列表.
        created_at: 创建时间.
        scheduled_at: 调度时间.
        started_at: 开始时间.
        completed_at: 完成时间.
    """

    task_id: str
    name: str = ""
    task_type: str = "general"
    data: dict[str, Any] = field(default_factory=dict)
    priority: TaskPriority = TaskPriority.NORMAL
    complexity: float = 50.0
    latency_requirement_ms: float = -1.0
    privacy_level: int = 3
    strategy: SchedulingStrategy = SchedulingStrategy.ADAPTIVE
    target: ExecutionTarget = ExecutionTarget.LOCAL
    status: TaskStatus = TaskStatus.PENDING
    result: Any = None
    error: str = ""
    fragments: list[TaskFragment] = field(default_factory=list)
    created_at: float = field(default_factory=time.time)
    scheduled_at: float = 0.0
    started_at: float = 0.0
    completed_at: float = 0.0


@dataclass
class SchedulingDecision:
    """调度决策.

    Attributes:
        task_id: 任务 ID.
        target: 执行目标.
        strategy: 使用的调度策略.
        reason: 决策理由.
        confidence: 决策置信度（0-1）.
        estimated_latency_ms: 预估延迟（毫秒）.
        estimated_cost: 预估成本.
        should_fragment: 是否需要分片.
        fragment_count: 建议分片数.
    """

    task_id: str
    target: ExecutionTarget
    strategy: SchedulingStrategy
    reason: str = ""
    confidence: float = 0.8
    estimated_latency_ms: float = 0.0
    estimated_cost: float = 0.0
    should_fragment: bool = False
    fragment_count: int = 1


# ---------------------------------------------------------------------------
# EdgeScheduler
# ---------------------------------------------------------------------------


class EdgeScheduler:
    """边缘任务调度器.

    提供边缘计算任务的智能调度能力，支持：
    - 三种调度策略（本地优先/云端优先/自适应）
    - 任务分片与并行处理
    - 设备算力评估
    - 任务队列管理

    可插拔设计：不依赖现有路由引擎，可独立使用或与现有系统集成。

    Attributes:
        _default_strategy: 默认调度策略.
        _device_profile: 当前设备算力画像.
        _tasks: 任务字典 {task_id: EdgeTask}.
        _task_queue: 任务队列（按优先级排序）.
        _local_executor: 本地执行器回调.
        _cloud_executor: 云端执行器回调.
        _max_concurrent_local: 最大并发本地任务数.
        _max_concurrent_cloud: 最大并发云端任务数.
    """

    def __init__(
        self,
        default_strategy: SchedulingStrategy = SchedulingStrategy.ADAPTIVE,
        max_concurrent_local: int = 4,
        max_concurrent_cloud: int = 10,
    ) -> None:
        """初始化边缘调度器.

        Args:
            default_strategy: 默认调度策略.
            max_concurrent_local: 最大并发本地任务数.
            max_concurrent_cloud: 最大并发云端任务数.
        """
        self._default_strategy = default_strategy
        self._max_concurrent_local = max_concurrent_local
        self._max_concurrent_cloud = max_concurrent_cloud

        self._device_profile = DeviceComputeProfile(device_id="local")
        self._tasks: dict[str, EdgeTask] = {}
        self._task_queue: list[EdgeTask] = []
        self._local_executor: Callable[[dict[str, Any]], Any] | None = None
        self._cloud_executor: Callable[[dict[str, Any]], Any] | None = None

        self._running_local = 0
        self._running_cloud = 0
        self._queue_lock = asyncio.Lock()

        logger.info(
            "edge_scheduler.init",
            strategy=default_strategy.value,
            max_local=max_concurrent_local,
            max_cloud=max_concurrent_cloud,
        )

    # ------------------------------------------------------------------
    # 执行器注册
    # ------------------------------------------------------------------

    def register_local_executor(
        self, executor: Callable[[dict[str, Any]], Any]
    ) -> None:
        """注册本地执行器.

        Args:
            executor: 接收任务数据，返回执行结果的回调函数.
        """
        self._local_executor = executor
        logger.debug("edge_scheduler.local_executor_registered")

    def register_cloud_executor(
        self, executor: Callable[[dict[str, Any]], Any]
    ) -> None:
        """注册云端执行器.

        Args:
            executor: 接收任务数据，返回执行结果的回调函数.
        """
        self._cloud_executor = executor
        logger.debug("edge_scheduler.cloud_executor_registered")

    # ------------------------------------------------------------------
    # 设备算力评估
    # ------------------------------------------------------------------

    def update_device_profile(self, profile: DeviceComputeProfile) -> None:
        """更新设备算力画像.

        Args:
            profile: 设备算力画像.
        """
        self._device_profile = profile
        self._device_profile.last_updated = time.time()
        logger.debug(
            "edge_scheduler.profile_updated",
            score=profile.performance_score,
            cpu_usage=profile.cpu_usage,
            network=profile.network_type,
        )

    def get_device_profile(self) -> DeviceComputeProfile:
        """获取当前设备算力画像."""
        return self._device_profile

    def evaluate_device_performance(
        self,
        cpu_usage: float | None = None,
        memory_usage: float | None = None,
        battery_level: float | None = None,
        network_latency_ms: float | None = None,
        temperature_celsius: float | None = None,
    ) -> float:
        """实时评估设备性能评分（0-100）.

        根据多个因素计算综合性能评分：
        - CPU 使用率（越低分越高）
        - 内存使用率（越低分越高）
        - 电池电量（越充分分越高）
        - 网络延迟（越低分越高）
        - 温度（越低分越高）

        Args:
            cpu_usage: CPU 使用率（0-100）.
            memory_usage: 内存使用率（0-100）.
            battery_level: 电池电量（0-100，-1 表示无电池）.
            network_latency_ms: 网络延迟（毫秒）.
            temperature_celsius: 温度（摄氏度）.

        Returns:
            综合性能评分（0-100）.
        """
        # 更新画像
        if cpu_usage is not None:
            self._device_profile.cpu_usage = cpu_usage
        if memory_usage is not None:
            self._device_profile.memory_usage = memory_usage
        if battery_level is not None:
            self._device_profile.battery_level = battery_level
        if network_latency_ms is not None:
            self._device_profile.network_latency_ms = network_latency_ms
        if temperature_celsius is not None:
            self._device_profile.temperature_celsius = temperature_celsius
            self._device_profile.thermal_throttling = temperature_celsius > 80

        # 计算评分（各项权重）
        scores = []
        weights = []

        # CPU 评分（权重 0.25）
        cpu_score = 100 - self._device_profile.cpu_usage
        scores.append(cpu_score)
        weights.append(0.25)

        # 内存评分（权重 0.20）
        mem_score = 100 - self._device_profile.memory_usage
        scores.append(mem_score)
        weights.append(0.20)

        # 电池评分（权重 0.15，无电池时给满分）
        if self._device_profile.battery_level < 0:
            battery_score = 100
        else:
            battery_score = self._device_profile.battery_level
        scores.append(battery_score)
        weights.append(0.15)

        # 网络评分（权重 0.20，基于延迟）
        latency = self._device_profile.network_latency_ms
        if latency <= 10:
            net_score = 100
        elif latency <= 50:
            net_score = 90
        elif latency <= 100:
            net_score = 70
        elif latency <= 500:
            net_score = 40
        else:
            net_score = 10
        scores.append(net_score)
        weights.append(0.20)

        # 温度评分（权重 0.20）
        temp = self._device_profile.temperature_celsius
        if temp < 50:
            temp_score = 100
        elif temp < 70:
            temp_score = 80
        elif temp < 85:
            temp_score = 50
        else:
            temp_score = 20
        scores.append(temp_score)
        weights.append(0.20)

        # 归一化权重并计算加权平均
        total_weight = sum(weights)
        if total_weight > 0:
            final_score = sum(s * w for s, w in zip(scores, weights)) / total_weight
        else:
            final_score = 50.0

        self._device_profile.performance_score = round(final_score, 1)
        self._device_profile.last_updated = time.time()

        return self._device_profile.performance_score

    # ------------------------------------------------------------------
    # 任务调度策略
    # ------------------------------------------------------------------

    def schedule_task(self, task: EdgeTask) -> SchedulingDecision:
        """调度任务：决定在本地还是云端执行.

        根据任务的策略、复杂度、延迟要求、隐私等级和设备状态做出决策。

        Args:
            task: 边缘任务.

        Returns:
            调度决策.
        """
        strategy = task.strategy or self._default_strategy

        if strategy == SchedulingStrategy.LOCAL_FIRST:
            return self._schedule_local_first(task)
        elif strategy == SchedulingStrategy.CLOUD_FIRST:
            return self._schedule_cloud_first(task)
        elif strategy == SchedulingStrategy.ADAPTIVE:
            return self._schedule_adaptive(task)
        else:
            return self._schedule_adaptive(task)

    def _schedule_local_first(self, task: EdgeTask) -> SchedulingDecision:
        """本地优先调度策略.

        只要本地有能力处理，就优先本地执行，降低延迟。
        仅在本地能力不足时回退到云端。
        """
        can_local = self._device_profile.is_capable_of(task.complexity)

        if can_local and self._running_local < self._max_concurrent_local:
            return SchedulingDecision(
                task_id=task.task_id,
                target=ExecutionTarget.LOCAL,
                strategy=SchedulingStrategy.LOCAL_FIRST,
                reason="本地有能力处理，优先本地执行以降低延迟",
                confidence=0.9,
                estimated_latency_ms=task.complexity * 10,
                estimated_cost=0.0,
            )
        else:
            return SchedulingDecision(
                task_id=task.task_id,
                target=ExecutionTarget.CLOUD,
                strategy=SchedulingStrategy.LOCAL_FIRST,
                reason="本地资源不足，回退到云端执行",
                confidence=0.7,
                estimated_latency_ms=self._device_profile.network_latency_ms + task.complexity * 5,
                estimated_cost=task.complexity * 0.01,
            )

    def _schedule_cloud_first(self, task: EdgeTask) -> SchedulingDecision:
        """云端优先调度策略.

        对于高算力需求的任务，优先使用云端资源。
        仅在网络不可用时回退到本地。
        """
        network_ok = (
            self._device_profile.network_type != "none"
            and self._device_profile.network_latency_ms < 1000
        )

        if network_ok and task.complexity > 30:
            return SchedulingDecision(
                task_id=task.task_id,
                target=ExecutionTarget.CLOUD,
                strategy=SchedulingStrategy.CLOUD_FIRST,
                reason="高算力需求任务，优先云端执行",
                confidence=0.85,
                estimated_latency_ms=self._device_profile.network_latency_ms + task.complexity * 3,
                estimated_cost=task.complexity * 0.01,
            )
        else:
            can_local = self._device_profile.is_capable_of(task.complexity)
            if can_local:
                return SchedulingDecision(
                    task_id=task.task_id,
                    target=ExecutionTarget.LOCAL,
                    strategy=SchedulingStrategy.CLOUD_FIRST,
                    reason="网络不可用或任务简单，回退到本地执行",
                    confidence=0.6,
                    estimated_latency_ms=task.complexity * 10,
                    estimated_cost=0.0,
                )
            else:
                return SchedulingDecision(
                    task_id=task.task_id,
                    target=ExecutionTarget.CLOUD,
                    strategy=SchedulingStrategy.CLOUD_FIRST,
                    reason="本地能力不足，必须云端执行",
                    confidence=0.5,
                    estimated_latency_ms=self._device_profile.network_latency_ms + task.complexity * 5,
                    estimated_cost=task.complexity * 0.02,
                )

    def _schedule_adaptive(self, task: EdgeTask) -> SchedulingDecision:
        """自适应调度策略.

        综合考虑以下因素动态决策：
        - 任务复杂度 vs 设备性能
        - 延迟要求
        - 隐私等级
        - 网络状态
        - 电池状态
        - 温度/负载
        """
        local_score = 0.0
        cloud_score = 0.0

        # 1. 性能因素（权重 0.25）
        perf = self._device_profile.performance_score
        if perf >= task.complexity:
            local_score += 25
        else:
            local_score += 25 * (perf / max(task.complexity, 1))

        cloud_score += 20  # 云端算力通常充足

        # 2. 延迟因素（权重 0.20）
        if task.latency_requirement_ms > 0:
            local_latency = task.complexity * 10
            cloud_latency = self._device_profile.network_latency_ms + task.complexity * 3

            if local_latency <= task.latency_requirement_ms:
                local_score += 20
            if cloud_latency <= task.latency_requirement_ms:
                cloud_score += 20

            # 延迟越满足得分越高
            local_score += max(0, 20 * (1 - local_latency / max(task.latency_requirement_ms * 2, 1)))
            cloud_score += max(0, 20 * (1 - cloud_latency / max(task.latency_requirement_ms * 2, 1)))
        else:
            # 无延迟要求时，本地略占优
            local_score += 15
            cloud_score += 12

        # 3. 隐私因素（权重 0.20）
        privacy_bonus = task.privacy_level * 2  # 0-20
        local_score += privacy_bonus
        cloud_score += max(0, 20 - privacy_bonus)

        # 4. 网络因素（权重 0.20）
        net_type = self._device_profile.network_type
        if net_type in ("ethernet", "wifi"):
            cloud_score += 20
        elif net_type in ("5g", "4g"):
            cloud_score += 12
        else:
            cloud_score += 2

        local_score += 15  # 本地不依赖网络

        # 5. 电池/温度因素（权重 0.15）
        if self._device_profile.battery_level > 0:
            if self._device_profile.battery_level > 50 or self._device_profile.battery_charging:
                local_score += 15
            elif self._device_profile.battery_level > 20:
                local_score += 8
            else:
                local_score += 3
        else:
            local_score += 15  # 无电池（插电）满分

        if self._device_profile.thermal_throttling:
            local_score -= 10

        # 决策
        confidence = abs(local_score - cloud_score) / 100.0
        confidence = max(0.3, min(0.99, confidence))

        if local_score >= cloud_score:
            target = ExecutionTarget.LOCAL
            reason = f"本地评分({local_score:.1f}) >= 云端评分({cloud_score:.1f})"
            est_latency = task.complexity * 10
            est_cost = 0.0
        else:
            target = ExecutionTarget.CLOUD
            reason = f"云端评分({cloud_score:.1f}) > 本地评分({local_score:.1f})"
            est_latency = self._device_profile.network_latency_ms + task.complexity * 3
            est_cost = task.complexity * 0.01

        # 判断是否需要分片
        should_fragment = task.complexity > 70 and target == ExecutionTarget.LOCAL
        fragment_count = 1
        if should_fragment:
            fragment_count = max(2, min(8, int(task.complexity / 20)))

        return SchedulingDecision(
            task_id=task.task_id,
            target=target,
            strategy=SchedulingStrategy.ADAPTIVE,
            reason=reason,
            confidence=round(confidence, 2),
            estimated_latency_ms=round(est_latency, 1),
            estimated_cost=round(est_cost, 4),
            should_fragment=should_fragment,
            fragment_count=fragment_count,
        )

    # ------------------------------------------------------------------
    # 任务分片
    # ------------------------------------------------------------------

    def fragment_task(
        self,
        task: EdgeTask,
        fragment_count: int,
    ) -> list[TaskFragment]:
        """将大任务拆分为多个小任务分片.

        Args:
            task: 原始任务.
            fragment_count: 分片数量.

        Returns:
            任务分片列表.
        """
        if fragment_count <= 1:
            fragment = TaskFragment(
                fragment_id=f"{task.task_id}-f0",
                task_id=task.task_id,
                index=0,
                total_fragments=1,
                data=task.data,
                target=ExecutionTarget.LOCAL,
            )
            return [fragment]

        fragments = []
        data_keys = list(task.data.keys())

        for i in range(fragment_count):
            # 简单分片策略：按数据 key 分配
            fragment_data = {}
            start_idx = i * len(data_keys) // fragment_count
            end_idx = (i + 1) * len(data_keys) // fragment_count

            for key in data_keys[start_idx:end_idx]:
                fragment_data[key] = task.data[key]

            # 如果数据不足以分片，使用索引标记
            if not fragment_data:
                fragment_data = {"_fragment_index": i, "_fragment_total": fragment_count}
                fragment_data.update(task.data)

            fragment = TaskFragment(
                fragment_id=f"{task.task_id}-f{i}",
                task_id=task.task_id,
                index=i,
                total_fragments=fragment_count,
                data=fragment_data,
                target=ExecutionTarget.LOCAL,
            )
            fragments.append(fragment)

        task.fragments = fragments
        logger.debug(
            "edge_scheduler.task_fragmented",
            task_id=task.task_id,
            fragments=fragment_count,
        )
        return fragments

    async def execute_fragments_parallel(
        self,
        fragments: list[TaskFragment],
    ) -> list[TaskFragment]:
        """并行执行任务分片.

        Args:
            fragments: 任务分片列表.

        Returns:
            执行后的分片列表（包含结果）.
        """
        async def _execute_fragment(frag: TaskFragment) -> TaskFragment:
            frag.status = TaskStatus.RUNNING
            frag.started_at = time.time()

            try:
                if frag.target == ExecutionTarget.LOCAL and self._local_executor:
                    result = self._local_executor(frag.data)
                    if asyncio.iscoroutine(result):
                        result = await result
                    frag.result = result
                elif frag.target == ExecutionTarget.CLOUD and self._cloud_executor:
                    result = self._cloud_executor(frag.data)
                    if asyncio.iscoroutine(result):
                        result = await result
                    frag.result = result
                else:
                    # 无执行器时，模拟执行
                    frag.result = {"fragment_id": frag.fragment_id, "status": "simulated"}

                frag.status = TaskStatus.COMPLETED
            except Exception as e:
                frag.status = TaskStatus.FAILED
                frag.error = str(e)
                logger.error(
                    "edge_scheduler.fragment_failed",
                    fragment_id=frag.fragment_id,
                    error=str(e),
                )

            frag.completed_at = time.time()
            return frag

        tasks = [_execute_fragment(frag) for frag in fragments]
        results = await asyncio.gather(*tasks)
        return list(results)

    def merge_fragment_results(
        self,
        fragments: list[TaskFragment],
    ) -> dict[str, Any]:
        """合并多个分片的执行结果.

        Args:
            fragments: 已完成的任务分片列表.

        Returns:
            合并后的结果字典.
        """
        merged: dict[str, Any] = {}
        success_count = 0
        failed_fragments = []

        for frag in fragments:
            if frag.status == TaskStatus.COMPLETED and isinstance(frag.result, dict):
                merged.update(frag.result)
                success_count += 1
            elif frag.status == TaskStatus.FAILED:
                failed_fragments.append(frag.fragment_id)

        merged["_meta"] = {
            "total_fragments": len(fragments),
            "success_count": success_count,
            "failed_fragments": failed_fragments,
            "all_success": len(failed_fragments) == 0,
        }

        return merged

    # ------------------------------------------------------------------
    # 任务管理
    # ------------------------------------------------------------------

    async def submit_task(
        self,
        task_data: dict[str, Any],
        task_type: str = "general",
        name: str = "",
        priority: TaskPriority = TaskPriority.NORMAL,
        complexity: float = 50.0,
        latency_requirement_ms: float = -1.0,
        privacy_level: int = 3,
        strategy: SchedulingStrategy | None = None,
    ) -> str:
        """提交边缘计算任务.

        Args:
            task_data: 任务数据.
            task_type: 任务类型.
            name: 任务名称.
            priority: 优先级.
            complexity: 复杂度（0-100）.
            latency_requirement_ms: 延迟要求（毫秒）.
            privacy_level: 隐私等级（0-10）.
            strategy: 调度策略，None 使用默认策略.

        Returns:
            任务 ID.
        """
        task_id = str(uuid.uuid4())
        task = EdgeTask(
            task_id=task_id,
            name=name or f"task-{task_id[:8]}",
            task_type=task_type,
            data=task_data,
            priority=priority,
            complexity=max(0.0, min(100.0, complexity)),
            latency_requirement_ms=latency_requirement_ms,
            privacy_level=max(0, min(10, privacy_level)),
            strategy=strategy or self._default_strategy,
        )

        # 调度决策
        decision = self.schedule_task(task)
        task.target = decision.target
        task.status = TaskStatus.SCHEDULED
        task.scheduled_at = time.time()

        # 如需分片
        if decision.should_fragment:
            self.fragment_task(task, decision.fragment_count)

        self._tasks[task_id] = task

        # 加入队列
        async with self._queue_lock:
            self._task_queue.append(task)
            self._task_queue.sort(key=lambda t: (
                _priority_order(t.priority),
                t.created_at,
            ))

        logger.info(
            "edge_scheduler.task_submitted",
            task_id=task_id,
            type=task_type,
            target=decision.target.value,
            strategy=decision.strategy.value,
        )

        # 异步触发执行
        asyncio.create_task(self._process_queue())

        return task_id

    def get_task(self, task_id: str) -> EdgeTask | None:
        """获取任务状态.

        Args:
            task_id: 任务 ID.

        Returns:
            任务对象，不存在返回 None.
        """
        return self._tasks.get(task_id)

    def list_tasks(
        self,
        status: TaskStatus | None = None,
        limit: int = 50,
    ) -> list[EdgeTask]:
        """列出任务.

        Args:
            status: 按状态过滤.
            limit: 最大返回数.

        Returns:
            任务列表.
        """
        tasks = list(self._tasks.values())
        if status:
            tasks = [t for t in tasks if t.status == status]
        tasks.sort(key=lambda t: t.created_at, reverse=True)
        return tasks[:limit]

    async def cancel_task(self, task_id: str) -> bool:
        """取消任务.

        Args:
            task_id: 任务 ID.

        Returns:
            是否成功取消.
        """
        task = self._tasks.get(task_id)
        if not task:
            return False

        if task.status in (TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.CANCELLED):
            return False

        task.status = TaskStatus.CANCELLED
        task.completed_at = time.time()

        # 从队列中移除
        async with self._queue_lock:
            self._task_queue = [t for t in self._task_queue if t.task_id != task_id]

        logger.info("edge_scheduler.task_cancelled", task_id=task_id)
        return True

    async def _process_queue(self) -> None:
        """处理任务队列."""
        async with self._queue_lock:
            if not self._task_queue:
                return

            # 选取可执行的任务
            ready_tasks: list[EdgeTask] = []
            remaining: list[EdgeTask] = []

            for task in self._task_queue:
                if task.status != TaskStatus.SCHEDULED:
                    remaining.append(task)
                    continue

                if task.target == ExecutionTarget.LOCAL:
                    if self._running_local < self._max_concurrent_local:
                        ready_tasks.append(task)
                        self._running_local += 1
                    else:
                        remaining.append(task)
                elif task.target == ExecutionTarget.CLOUD:
                    if self._running_cloud < self._max_concurrent_cloud:
                        ready_tasks.append(task)
                        self._running_cloud += 1
                    else:
                        remaining.append(task)
                else:
                    remaining.append(task)

            self._task_queue = remaining

        # 执行就绪任务
        for task in ready_tasks:
            asyncio.create_task(self._execute_task(task))

    async def _execute_task(self, task: EdgeTask) -> None:
        """执行单个任务."""
        task.status = TaskStatus.RUNNING
        task.started_at = time.time()

        try:
            if task.fragments and len(task.fragments) > 1:
                # 分片执行
                results = await self.execute_fragments_parallel(task.fragments)
                task.result = self.merge_fragment_results(results)
                all_success = all(
                    f.status == TaskStatus.COMPLETED for f in results
                )
                task.status = TaskStatus.COMPLETED if all_success else TaskStatus.FAILED
            else:
                # 单片执行
                if task.target == ExecutionTarget.LOCAL and self._local_executor:
                    result = self._local_executor(task.data)
                    if asyncio.iscoroutine(result):
                        result = await result
                    task.result = result
                elif task.target == ExecutionTarget.CLOUD and self._cloud_executor:
                    result = self._cloud_executor(task.data)
                    if asyncio.iscoroutine(result):
                        result = await result
                    task.result = result
                else:
                    # 模拟执行
                    task.result = {
                        "task_id": task.task_id,
                        "status": "simulated",
                        "target": task.target.value,
                    }

                task.status = TaskStatus.COMPLETED

        except Exception as e:
            task.status = TaskStatus.FAILED
            task.error = str(e)
            logger.error(
                "edge_scheduler.task_failed",
                task_id=task.task_id,
                error=str(e),
            )

        finally:
            task.completed_at = time.time()
            if task.target == ExecutionTarget.LOCAL:
                self._running_local = max(0, self._running_local - 1)
            else:
                self._running_cloud = max(0, self._running_cloud - 1)

            # 继续处理队列
            asyncio.create_task(self._process_queue())

    # ------------------------------------------------------------------
    # 统计指标
    # ------------------------------------------------------------------

    def get_metrics(self) -> dict[str, Any]:
        """获取调度器统计指标.

        Returns:
            指标字典.
        """
        total = len(self._tasks)
        completed = sum(1 for t in self._tasks.values() if t.status == TaskStatus.COMPLETED)
        failed = sum(1 for t in self._tasks.values() if t.status == TaskStatus.FAILED)
        running = sum(1 for t in self._tasks.values() if t.status == TaskStatus.RUNNING)
        pending = sum(1 for t in self._tasks.values() if t.status in (TaskStatus.PENDING, TaskStatus.SCHEDULED))

        local_count = sum(1 for t in self._tasks.values() if t.target == ExecutionTarget.LOCAL)
        cloud_count = sum(1 for t in self._tasks.values() if t.target == ExecutionTarget.CLOUD)

        return {
            "total_tasks": total,
            "completed": completed,
            "failed": failed,
            "running": running,
            "pending": pending,
            "local_executions": local_count,
            "cloud_executions": cloud_count,
            "running_local": self._running_local,
            "running_cloud": self._running_cloud,
            "queue_size": len(self._task_queue),
            "device_performance_score": self._device_profile.performance_score,
        }


def _priority_order(priority: TaskPriority) -> int:
    """优先级排序辅助（值越小越优先）."""
    order = {
        TaskPriority.CRITICAL: 0,
        TaskPriority.HIGH: 1,
        TaskPriority.NORMAL: 2,
        TaskPriority.LOW: 3,
    }
    return order.get(priority, 2)
