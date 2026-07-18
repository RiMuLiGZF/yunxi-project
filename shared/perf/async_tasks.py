"""
异步任务队列 (Async Task Queue)

功能:
- 简单的内存任务队列
- 任务优先级
- 任务状态追踪
- 任务重试 (失败重试)
- Worker 池 (可配置 worker 数量)
- 任务结果持久化 (可选)

使用方式::

    from shared.perf.async_tasks import AsyncTaskQueue, Task

    queue = AsyncTaskQueue(worker_count=4)
    queue.start()

    # 提交任务
    task_id = queue.submit(send_email, to="user@example.com", subject="Hello")

    # 查询任务状态
    status = queue.get_task_status(task_id)

    # 获取结果
    result = queue.get_result(task_id)
"""

from __future__ import annotations

import os
import time
import uuid
import json
import threading
import logging
import queue as _queue
from typing import Any, Dict, List, Optional, Callable, Tuple
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path


logger = logging.getLogger(__name__)


# ============================================================
# 任务状态
# ============================================================

class TaskStatus(str, Enum):
    PENDING = "pending"       # 等待执行
    RUNNING = "running"       # 执行中
    COMPLETED = "completed"   # 完成
    FAILED = "failed"         # 失败
    CANCELLED = "cancelled"   # 已取消
    RETRYING = "retrying"     # 重试中


# ============================================================
# 任务
# ============================================================

@dataclass
class Task:
    """任务对象"""
    id: str
    func: Callable
    args: tuple = ()
    kwargs: Dict[str, Any] = field(default_factory=dict)
    priority: int = 5  # 1-10, 数字越小优先级越高
    status: TaskStatus = TaskStatus.PENDING
    result: Any = None
    error: Optional[str] = None
    retries: int = 0
    max_retries: int = 3
    retry_delay: float = 1.0  # 秒
    created_at: float = field(default_factory=time.time)
    started_at: Optional[float] = None
    completed_at: Optional[float] = None
    duration_ms: float = 0.0
    progress: float = 0.0  # 0-1
    progress_message: str = ""
    queue_name: str = "default"
    dependencies: List[str] = field(default_factory=list)  # 依赖的任务 ID

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "func_name": getattr(self.func, "__name__", str(self.func)),
            "priority": self.priority,
            "status": self.status.value,
            "result": str(self.result)[:500] if self.result is not None else None,
            "error": self.error,
            "retries": self.retries,
            "max_retries": self.max_retries,
            "created_at": self.created_at,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "duration_ms": round(self.duration_ms, 3),
            "progress": self.progress,
            "progress_message": self.progress_message,
            "queue": self.queue_name,
            "dependencies": self.dependencies,
        }


# ============================================================
# 优先级队列
# ============================================================

class PriorityTaskQueue:
    """优先级任务队列

    使用 heapq 实现，优先级数字越小越先执行。
    """

    def __init__(self):
        self._queue: _queue.PriorityQueue = _queue.PriorityQueue()
        self._counter = 0  # 用于同优先级的 FIFO 排序

    def put(self, task: Task) -> None:
        """添加任务"""
        self._counter += 1
        # (priority, counter, task) - 先按优先级，再按加入顺序
        self._queue.put((task.priority, self._counter, task))

    def get(self, timeout: Optional[float] = None) -> Task:
        """获取任务"""
        _, _, task = self._queue.get(timeout=timeout)
        return task

    def qsize(self) -> int:
        """队列大小"""
        return self._queue.qsize()

    def empty(self) -> bool:
        """是否为空"""
        return self._queue.empty()


# ============================================================
# 异步任务队列
# ============================================================

class AsyncTaskQueue:
    """异步任务队列 (内存版)

    特性:
    - Worker 池 (可配置数量)
    - 任务优先级 (1-10)
    - 失败重试 (可配置次数和延迟)
    - 任务状态追踪
    - 任务取消
    - 任务进度上报
    - 任务依赖
    - 任务结果持久化 (可选)
    """

    def __init__(
        self,
        worker_count: int = 4,
        max_retries: int = 3,
        retry_delay: float = 1.0,
        max_tasks: int = 10000,
        persist_path: Optional[str] = None,
        queue_names: Optional[List[str]] = None,
    ):
        """
        Args:
            worker_count: Worker 线程数
            max_retries: 默认最大重试次数
            retry_delay: 默认重试延迟 (秒)
            max_tasks: 最大任务数 (历史记录)
            persist_path: 任务结果持久化目录
            queue_names: 队列名称列表
        """
        self.worker_count = worker_count
        self.max_retries = max_retries
        self.retry_delay = retry_delay
        self.max_tasks = max_tasks
        self.persist_path = persist_path

        # 队列 (支持多个命名队列)
        self._queues: Dict[str, PriorityTaskQueue] = {}
        queue_names = queue_names or ["default", "io", "cpu", "background"]
        for name in queue_names:
            self._queues[name] = PriorityTaskQueue()

        # 任务注册表
        self._tasks: Dict[str, Task] = {}
        self._tasks_lock = threading.Lock()

        # Worker
        self._workers: List[threading.Thread] = []
        self._stop_event = threading.Event()
        self._started = False

        # 进度回调
        self._progress_callbacks: List[Callable] = []

        # 持久化目录
        if persist_path:
            Path(persist_path).mkdir(parents=True, exist_ok=True)

    @classmethod
    def from_env(cls) -> "AsyncTaskQueue":
        """从环境变量创建"""
        def env_int(name: str, default: int) -> int:
            try:
                return int(os.getenv(name, str(default)))
            except (ValueError, TypeError):
                return default

        def env_bool(name: str, default: bool) -> bool:
            val = os.getenv(name, "")
            return val.lower() in ("true", "1", "yes", "on") if val else default

        return cls(
            worker_count=env_int("PERF_TASK_WORKERS", 4),
            max_retries=env_int("PERF_TASK_MAX_RETRIES", 3),
            max_tasks=env_int("PERF_TASK_MAX_TASKS", 10000),
        )

    # ---------- 生命周期 ----------

    def start(self) -> None:
        """启动 Worker 池"""
        if self._started:
            return
        self._started = True
        self._stop_event.clear()

        for i in range(self.worker_count):
            t = threading.Thread(
                target=self._worker_loop,
                name=f"TaskWorker-{i}",
                daemon=True,
            )
            t.start()
            self._workers.append(t)

    def stop(self, wait: bool = True) -> None:
        """停止 Worker 池"""
        self._stop_event.set()
        if wait:
            for t in self._workers:
                t.join(timeout=5.0)
        self._workers.clear()
        self._started = False

    # ---------- 任务提交 ----------

    def submit(
        self,
        func: Callable,
        *args,
        queue: str = "default",
        priority: int = 5,
        max_retries: Optional[int] = None,
        retry_delay: Optional[float] = None,
        dependencies: Optional[List[str]] = None,
        **kwargs,
    ) -> str:
        """提交任务

        Args:
            func: 要执行的函数
            *args: 位置参数
            queue: 队列名
            priority: 优先级 (1-10，越小越高)
            max_retries: 最大重试次数
            retry_delay: 重试延迟 (秒)
            dependencies: 依赖的任务 ID 列表
            **kwargs: 关键字参数

        Returns:
            任务 ID
        """
        task_id = str(uuid.uuid4())
        task = Task(
            id=task_id,
            func=func,
            args=args,
            kwargs=kwargs,
            priority=max(1, min(10, priority)),
            max_retries=max_retries if max_retries is not None else self.max_retries,
            retry_delay=retry_delay if retry_delay is not None else self.retry_delay,
            queue_name=queue,
            dependencies=dependencies or [],
        )

        self._register_task(task)

        # 获取目标队列
        target_queue = self._queues.get(queue)
        if target_queue is None:
            target_queue = self._queues["default"]

        target_queue.put(task)

        logger.debug(f"Task submitted: {task_id} ({func.__name__})")
        return task_id

    def submit_delayed(
        self,
        delay_seconds: float,
        func: Callable,
        *args,
        **kwargs,
    ) -> str:
        """提交延迟任务

        Args:
            delay_seconds: 延迟秒数
            func: 要执行的函数
            *args, **kwargs: 其他参数同 submit

        Returns:
            任务 ID
        """
        def delayed_wrapper():
            time.sleep(delay_seconds)
            return func(*args, **kwargs)

        # 用低优先级模拟延迟 (简单实现)
        return self.submit(delayed_wrapper, queue="background", priority=10)

    # ---------- 任务查询 ----------

    def get_task_status(self, task_id: str) -> Optional[Dict[str, Any]]:
        """获取任务状态"""
        with self._tasks_lock:
            task = self._tasks.get(task_id)
            return task.to_dict() if task else None

    def get_result(self, task_id: str, timeout: Optional[float] = None) -> Any:
        """获取任务结果 (阻塞等待)

        Args:
            task_id: 任务 ID
            timeout: 超时时间 (秒)，None 则立即返回

        Returns:
            任务结果

        Raises:
            TimeoutError: 超时
            ValueError: 任务不存在
            RuntimeError: 任务执行失败
        """
        start = time.time()
        while True:
            with self._tasks_lock:
                task = self._tasks.get(task_id)
                if task is None:
                    raise ValueError(f"Task not found: {task_id}")

                if task.status == TaskStatus.COMPLETED:
                    return task.result
                elif task.status == TaskStatus.FAILED:
                    raise RuntimeError(f"Task failed: {task.error}")
                elif task.status == TaskStatus.CANCELLED:
                    raise RuntimeError("Task was cancelled")

            if timeout is None:
                return None

            if time.time() - start > timeout:
                raise TimeoutError(f"Task timeout: {task_id}")

            time.sleep(0.1)

    def list_tasks(
        self,
        status: Optional[TaskStatus] = None,
        queue: Optional[str] = None,
        limit: int = 100,
    ) -> List[Dict[str, Any]]:
        """列出任务

        Args:
            status: 按状态过滤
            queue: 按队列过滤
            limit: 返回数量

        Returns:
            任务列表 (最新的在前)
        """
        with self._tasks_lock:
            tasks = list(self._tasks.values())

        if status is not None:
            tasks = [t for t in tasks if t.status == status]
        if queue is not None:
            tasks = [t for t in tasks if t.queue_name == queue]

        tasks.sort(key=lambda t: t.created_at, reverse=True)
        return [t.to_dict() for t in tasks[:limit]]

    # ---------- 任务控制 ----------

    def cancel_task(self, task_id: str) -> bool:
        """取消任务

        只能取消 PENDING 状态的任务。
        """
        with self._tasks_lock:
            task = self._tasks.get(task_id)
            if task is None:
                return False
            if task.status != TaskStatus.PENDING:
                return False
            task.status = TaskStatus.CANCELLED
            return True

    def update_progress(
        self,
        task_id: str,
        progress: float,
        message: str = "",
    ) -> None:
        """更新任务进度

        任务函数内部可以调用此方法上报进度。
        """
        with self._tasks_lock:
            task = self._tasks.get(task_id)
            if task:
                task.progress = max(0.0, min(1.0, progress))
                task.progress_message = message

        # 触发进度回调
        for callback in self._progress_callbacks:
            try:
                callback(task_id, progress, message)
            except Exception:
                pass

    # ---------- Worker ----------

    def _worker_loop(self) -> None:
        """Worker 主循环"""
        while not self._stop_event.is_set():
            try:
                # 从所有队列中取任务 (按优先级)
                task = self._get_next_task()
                if task is None:
                    time.sleep(0.1)
                    continue

                self._execute_task(task)

            except Exception:
                logger.exception("Task worker error")
                time.sleep(0.1)

    def _get_next_task(self) -> Optional[Task]:
        """从所有队列获取下一个任务 (非阻塞)"""
        # 按优先级检查各队列
        for q in self._queues.values():
            try:
                task = q.get(timeout=0.01)
                # 检查依赖
                if task.dependencies:
                    if not self._check_dependencies(task):
                        # 依赖未完成，重新入队
                        q.put(task)
                        time.sleep(0.01)
                        continue
                # 检查是否被取消
                with self._tasks_lock:
                    current = self._tasks.get(task.id)
                    if current and current.status == TaskStatus.CANCELLED:
                        continue
                return task
            except _queue.Empty:
                continue
        return None

    def _check_dependencies(self, task: Task) -> bool:
        """检查任务依赖是否都已完成"""
        with self._tasks_lock:
            for dep_id in task.dependencies:
                dep = self._tasks.get(dep_id)
                if dep is None or dep.status != TaskStatus.COMPLETED:
                    return False
        return True

    def _execute_task(self, task: Task) -> None:
        """执行任务"""
        with self._tasks_lock:
            task.status = TaskStatus.RUNNING
            task.started_at = time.time()

        start = time.perf_counter()

        try:
            # 执行函数
            result = task.func(*task.args, **task.kwargs)

            with self._tasks_lock:
                task.status = TaskStatus.COMPLETED
                task.result = result
                task.completed_at = time.time()
                task.duration_ms = (time.perf_counter() - start) * 1000
                task.progress = 1.0

            # 持久化结果
            self._persist_task(task)

            logger.debug(f"Task completed: {task.id} ({task.duration_ms:.2f}ms)")

        except Exception as e:
            error_msg = str(e)
            logger.warning(f"Task failed: {task.id}, error: {error_msg}")

            with self._tasks_lock:
                if task.retries < task.max_retries:
                    # 重试
                    task.retries += 1
                    task.status = TaskStatus.RETRYING
                    task.error = error_msg

                    # 延迟重试 (重新入队，用指数退避)
                    delay = task.retry_delay * (2 ** (task.retries - 1))
                    # 简单实现: 用低优先级 + 延迟线程
                    def retry_after_delay():
                        time.sleep(delay)
                        with self._tasks_lock:
                            if task.status == TaskStatus.RETRYING:
                                task.status = TaskStatus.PENDING
                                target_queue = self._queues.get(task.queue_name)
                                if target_queue:
                                    target_queue.put(task)

                    threading.Thread(target=retry_after_delay, daemon=True).start()
                else:
                    # 超过重试次数，标记失败
                    task.status = TaskStatus.FAILED
                    task.error = error_msg
                    task.completed_at = time.time()
                    task.duration_ms = (time.perf_counter() - start) * 1000

                    # 持久化失败结果
                    self._persist_task(task)

    # ---------- 任务注册 ----------

    def _register_task(self, task: Task) -> None:
        """注册任务 (维护任务列表)"""
        with self._tasks_lock:
            # 限制任务数
            if len(self._tasks) >= self.max_tasks:
                # 移除最老的已完成任务
                completed = [
                    t for t in self._tasks.values()
                    if t.status in (TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.CANCELLED)
                ]
                completed.sort(key=lambda t: t.created_at)
                to_remove = completed[:max(1, len(completed) // 10)]
                for t in to_remove:
                    del self._tasks[t.id]

            self._tasks[task.id] = task

    def _persist_task(self, task: Task) -> None:
        """持久化任务结果"""
        if not self.persist_path:
            return
        try:
            filepath = os.path.join(self.persist_path, f"{task.id}.json")
            with open(filepath, "w", encoding="utf-8") as f:
                json.dump(task.to_dict(), f, ensure_ascii=False, default=str)
        except Exception:
            pass

    # ---------- 统计 ----------

    def get_stats(self) -> Dict[str, Any]:
        """获取队列统计"""
        with self._tasks_lock:
            total = len(self._tasks)
            pending = sum(1 for t in self._tasks.values() if t.status == TaskStatus.PENDING)
            running = sum(1 for t in self._tasks.values() if t.status == TaskStatus.RUNNING)
            completed = sum(1 for t in self._tasks.values() if t.status == TaskStatus.COMPLETED)
            failed = sum(1 for t in self._tasks.values() if t.status == TaskStatus.FAILED)
            cancelled = sum(1 for t in self._tasks.values() if t.status == TaskStatus.CANCELLED)

        queue_sizes = {name: q.qsize() for name, q in self._queues.items()}

        return {
            "worker_count": self.worker_count,
            "total_tasks": total,
            "pending": pending,
            "running": running,
            "completed": completed,
            "failed": failed,
            "cancelled": cancelled,
            "queue_sizes": queue_sizes,
            "success_rate": round(completed / max(1, completed + failed), 4),
        }
