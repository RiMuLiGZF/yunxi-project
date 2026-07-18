"""
后台任务装饰器 (Background Tasks)

提供便捷的后台任务装饰器，将函数调用转换为异步任务。

功能:
- @background_task 装饰器
- 任务立即/延迟执行
- 任务取消
- 任务进度上报
- 任务依赖

使用方式::

    from shared.perf.background_tasks import background_task, get_task_queue

    # 装饰器用法
    @background_task(queue="io", priority=3, max_retries=3)
    def send_email(to: str, subject: str, body: str) -> bool:
        # 发送邮件
        return True

    # 立即执行 (返回任务 ID)
    task_id = send_email("user@example.com", "Hello", "Body")

    # 延迟执行
    task_id = send_email.delay(30, "user@example.com", "Hello", "Body")

    # 查询状态
    status = send_email.get_status(task_id)

    # 取消任务
    send_email.cancel(task_id)
"""

from __future__ import annotations

import functools
import threading
from typing import Any, Callable, Dict, List, Optional

from shared.perf.async_tasks import AsyncTaskQueue, TaskStatus


# ============================================================
# 全局任务队列
# ============================================================

_default_queue: Optional[AsyncTaskQueue] = None
_queue_lock = threading.Lock()


def get_task_queue() -> AsyncTaskQueue:
    """获取全局任务队列"""
    global _default_queue
    if _default_queue is not None:
        return _default_queue
    with _queue_lock:
        if _default_queue is None:
            _default_queue = AsyncTaskQueue.from_env()
            _default_queue.start()
        return _default_queue


def reset_task_queue() -> None:
    """重置任务队列 (用于测试)"""
    global _default_queue
    with _queue_lock:
        if _default_queue is not None:
            _default_queue.stop(wait=False)
            _default_queue = None


# ============================================================
# 后台任务装饰器
# ============================================================

class BackgroundTaskWrapper:
    """后台任务包装器

    包装一个函数，使其调用变为异步提交任务。
    提供便捷方法: delay, get_status, cancel, get_result
    """

    def __init__(
        self,
        func: Callable,
        queue: str = "default",
        priority: int = 5,
        max_retries: int = 3,
        retry_delay: float = 1.0,
        task_queue: Optional[AsyncTaskQueue] = None,
    ):
        self.func = func
        self.queue = queue
        self.priority = priority
        self.max_retries = max_retries
        self.retry_delay = retry_delay
        self._task_queue = task_queue

        # 保留原函数元数据
        functools.update_wrapper(self, func)

    @property
    def task_queue(self) -> AsyncTaskQueue:
        """获取任务队列"""
        if self._task_queue is None:
            self._task_queue = get_task_queue()
        return self._task_queue

    def __call__(self, *args, **kwargs) -> str:
        """调用函数 = 提交后台任务

        Returns:
            任务 ID
        """
        return self.task_queue.submit(
            self.func,
            *args,
            queue=self.queue,
            priority=self.priority,
            max_retries=self.max_retries,
            retry_delay=self.retry_delay,
            **kwargs,
        )

    def delay(self, delay_seconds: float, *args, **kwargs) -> str:
        """延迟执行

        Args:
            delay_seconds: 延迟秒数
            *args, **kwargs: 函数参数

        Returns:
            任务 ID
        """
        return self.task_queue.submit_delayed(
            delay_seconds,
            self.func,
            *args,
            queue=self.queue,
            priority=self.priority,
            max_retries=self.max_retries,
            retry_delay=self.retry_delay,
            **kwargs,
        )

    def with_dependencies(self, dependencies: List[str], *args, **kwargs) -> str:
        """带依赖的任务提交

        Args:
            dependencies: 依赖的任务 ID 列表
            *args, **kwargs: 函数参数

        Returns:
            任务 ID
        """
        return self.task_queue.submit(
            self.func,
            *args,
            queue=self.queue,
            priority=self.priority,
            max_retries=self.max_retries,
            retry_delay=self.retry_delay,
            dependencies=dependencies,
            **kwargs,
        )

    def get_status(self, task_id: str) -> Optional[Dict[str, Any]]:
        """获取任务状态"""
        return self.task_queue.get_task_status(task_id)

    def get_result(self, task_id: str, timeout: Optional[float] = None) -> Any:
        """获取任务结果 (阻塞)"""
        return self.task_queue.get_result(task_id, timeout=timeout)

    def cancel(self, task_id: str) -> bool:
        """取消任务"""
        return self.task_queue.cancel_task(task_id)

    def update_progress(self, task_id: str, progress: float, message: str = "") -> None:
        """更新任务进度"""
        self.task_queue.update_progress(task_id, progress, message)


def background_task(
    queue: str = "default",
    priority: int = 5,
    max_retries: int = 3,
    retry_delay: float = 1.0,
    task_queue: Optional[AsyncTaskQueue] = None,
):
    """后台任务装饰器

    将函数调用转换为异步任务提交。

    用法::

        @background_task(queue="io", priority=3, max_retries=3)
        def send_email(to: str, subject: str, body: str) -> bool:
            # 发送邮件
            return True

        # 提交任务 (返回任务 ID)
        task_id = send_email("user@example.com", "Hello", "Body")

        # 延迟执行
        task_id = send_email.delay(30, "user@example.com", "Hello", "Body")

        # 带依赖
        task_id2 = send_email.with_dependencies([task_id], "user2@example.com", ...)

        # 查询状态
        status = send_email.get_status(task_id)

        # 获取结果 (阻塞)
        result = send_email.get_result(task_id, timeout=10)

        # 取消
        send_email.cancel(task_id)

    Args:
        queue: 队列名 (default/io/cpu/background)
        priority: 优先级 (1-10，越小越高)
        max_retries: 最大重试次数
        retry_delay: 重试延迟 (秒)
        task_queue: 自定义任务队列

    Returns:
        装饰器
    """
    def decorator(func: Callable) -> BackgroundTaskWrapper:
        return BackgroundTaskWrapper(
            func=func,
            queue=queue,
            priority=priority,
            max_retries=max_retries,
            retry_delay=retry_delay,
            task_queue=task_queue,
        )
    return decorator


# ============================================================
# 进度上报上下文
# ============================================================

class ProgressReporter:
    """任务进度上报器

    在任务函数内部使用，方便上报进度。

    用法::

        @background_task()
        def process_files(files: list, reporter: ProgressReporter):
            total = len(files)
            for i, f in enumerate(files):
                process_one(f)
                reporter.update(i / total, f"Processing {f}")
    """

    def __init__(self, task_id: str, task_queue: Optional[AsyncTaskQueue] = None):
        self.task_id = task_id
        self._queue = task_queue or get_task_queue()

    def update(self, progress: float, message: str = "") -> None:
        """更新进度

        Args:
            progress: 0.0 - 1.0
            message: 进度消息
        """
        self._queue.update_progress(self.task_id, progress, message)

    def increment(self, step: float, message: str = "") -> None:
        """增量更新进度 (需要外部跟踪当前进度，这里简化处理)"""
        # 简化: 直接调用 update (调用方传绝对值)
        self.update(step, message)
