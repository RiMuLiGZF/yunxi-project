"""M11 MCP Bus - stdio 服务管理器.

通过子进程方式启动本地 MCP 服务，使用 stdin/stdout 管道进行 JSON-RPC 通信。
支持服务启动、停止、重启、请求-响应匹配、心跳检测等功能。
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import signal
import secrets
from collections import deque
from datetime import datetime
from typing import Any, Deque, Dict, List, Optional

from ..config import get_settings

logger = logging.getLogger(__name__)


# ============================================================
# 工具函数
# ============================================================

def _generate_service_id() -> str:
    """生成 stdio 服务 ID.

    Returns:
        服务 ID 字符串
    """
    return "stdio_" + secrets.token_hex(8)


# ============================================================
# 服务状态枚举
# ============================================================

class StdioServiceStatus:
    """stdio 服务状态常量."""

    STARTING = "starting"
    RUNNING = "running"
    STOPPING = "stopping"
    STOPPED = "stopped"
    ERROR = "error"


# ============================================================
# 服务实例
# ============================================================

class StdioServiceInstance:
    """stdio 服务实例.

    封装单个子进程的状态、配置和通信管道。
    """

    def __init__(
        self,
        service_id: str,
        name: str,
        command: str,
        args: List[str],
        env: Optional[Dict[str, str]] = None,
        description: str = "",
    ) -> None:
        """初始化服务实例.

        Args:
            service_id: 服务唯一标识
            name: 服务名称
            command: 要执行的命令
            args: 命令参数列表
            env: 环境变量字典
            description: 服务描述
        """
        self.service_id = service_id
        self.name = name
        self.command = command
        self.args = args
        self.env = env or {}
        self.description = description

        # 进程相关
        self.process: Optional[asyncio.subprocess.Process] = None
        self.status: str = StdioServiceStatus.STOPPED
        self.pid: Optional[int] = None
        self.exit_code: Optional[int] = None

        # 时间戳
        self.started_at: Optional[datetime] = None
        self.stopped_at: Optional[datetime] = None
        self.error_message: str = ""

        # 请求-响应匹配
        self._pending_requests: Dict[Any, asyncio.Future] = {}
        self._next_request_id: int = 1

        # 后台任务
        self._stdout_task: Optional[asyncio.Task] = None
        self._stderr_task: Optional[asyncio.Task] = None
        self._monitor_task: Optional[asyncio.Task] = None

        # stderr 日志缓存（环形缓冲区）
        self._stderr_logs: Deque[str] = deque(maxlen=500)

        # 通知回调（用于 notification 消息）
        self._notification_callbacks: List = []

    # --------------------------------------------------------
    # 日志
    # --------------------------------------------------------

    def _append_stderr_log(self, line: str) -> None:
        """追加 stderr 日志行.

        Args:
            line: 日志行内容
        """
        timestamp = datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"
        self._stderr_logs.append(f"[{timestamp}] {line}")

    def get_stderr_logs(self, limit: int = 100) -> List[str]:
        """获取 stderr 日志.

        Args:
            limit: 返回的最大日志行数

        Returns:
            日志行列表（最新的在前）
        """
        logs = list(self._stderr_logs)
        return logs[-limit:] if limit > 0 else logs

    # --------------------------------------------------------
    # 请求 ID 管理
    # --------------------------------------------------------

    def _get_next_request_id(self) -> int:
        """获取下一个请求 ID.

        Returns:
            自增的请求 ID
        """
        req_id = self._next_request_id
        self._next_request_id += 1
        return req_id

    # --------------------------------------------------------
    # 状态序列化
    # --------------------------------------------------------

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典表示.

        Returns:
            服务实例信息字典
        """
        return {
            "service_id": self.service_id,
            "name": self.name,
            "command": self.command,
            "args": self.args,
            "description": self.description,
            "status": self.status,
            "pid": self.pid,
            "exit_code": self.exit_code,
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "stopped_at": self.stopped_at.isoformat() if self.stopped_at else None,
            "error_message": self.error_message,
            "pending_requests": len(self._pending_requests),
        }


# ============================================================
# stdio 服务管理器
# ============================================================

class StdioServiceManager:
    """stdio 服务管理器.

    管理多个通过 stdio 方式通信的 MCP 服务子进程，
    提供启动、停止、请求发送、响应读取等功能。
    """

    def __init__(self) -> None:
        """初始化管理器."""
        self._settings = get_settings()
        self._services: Dict[str, StdioServiceInstance] = {}
        self._lock = asyncio.Lock()

    # --------------------------------------------------------
    # 基础操作
    # --------------------------------------------------------

    async def start_service(
        self,
        name: str,
        command: str,
        args: Optional[List[str]] = None,
        env: Optional[Dict[str, str]] = None,
        description: str = "",
    ) -> StdioServiceInstance:
        """启动一个新的 stdio 服务.

        Args:
            name: 服务名称
            command: 要执行的命令（如 python、node）
            args: 命令参数列表
            env: 额外的环境变量
            description: 服务描述

        Returns:
            已启动的服务实例

        Raises:
            RuntimeError: 服务数量达到上限或启动失败
            asyncio.TimeoutError: 启动超时
        """
        args = args or []
        env = env or {}

        async with self._lock:
            # 检查服务数量上限
            if len(self._services) >= self._settings.stdio_max_services:
                raise RuntimeError(
                    f"stdio 服务数量已达上限 ({self._settings.stdio_max_services})"
                )

            # 检查名称唯一性
            for svc in self._services.values():
                if svc.name == name:
                    raise ValueError(f"服务名称已存在: {name}")

            service_id = _generate_service_id()
            service = StdioServiceInstance(
                service_id=service_id,
                name=name,
                command=command,
                args=args,
                env=env,
                description=description,
            )
            service.status = StdioServiceStatus.STARTING
            self._services[service_id] = service

        try:
            await self._spawn_process(service)
        except Exception:
            # 启动失败，清理记录
            async with self._lock:
                self._services.pop(service_id, None)
            raise

        return service

    async def stop_service(self, service_id: str) -> bool:
        """停止指定的 stdio 服务.

        先发送 SIGTERM，超时后发送 SIGKILL。

        Args:
            service_id: 服务 ID

        Returns:
            是否成功停止

        Raises:
            ValueError: 服务不存在
        """
        service = self._get_service(service_id)

        if service.status in (StdioServiceStatus.STOPPED, StdioServiceStatus.ERROR):
            return True

        service.status = StdioServiceStatus.STOPPING

        try:
            await self._terminate_process(service)
        finally:
            # 清理 pending requests
            for future in service._pending_requests.values():
                if not future.done():
                    future.set_exception(RuntimeError("Service stopped"))
            service._pending_requests.clear()

        return True

    async def restart_service(self, service_id: str) -> StdioServiceInstance:
        """重启 stdio 服务.

        Args:
            service_id: 服务 ID

        Returns:
            重启后的服务实例

        Raises:
            ValueError: 服务不存在
        """
        service = self._get_service(service_id)

        # 保存配置
        name = service.name
        command = service.command
        args = service.args
        env = service.env
        description = service.description

        # 停止当前服务
        await self.stop_service(service_id)

        # 从服务列表中移除旧实例
        async with self._lock:
            self._services.pop(service_id, None)

        # 重新启动（复用原 service_id）
        new_service = StdioServiceInstance(
            service_id=service_id,
            name=name,
            command=command,
            args=args,
            env=env,
            description=description,
        )
        new_service.status = StdioServiceStatus.STARTING

        async with self._lock:
            self._services[service_id] = new_service

        try:
            await self._spawn_process(new_service)
        except Exception:
            async with self._lock:
                self._services.pop(service_id, None)
            raise

        return new_service

    def get_service_status(self, service_id: str) -> Dict[str, Any]:
        """获取服务状态.

        Args:
            service_id: 服务 ID

        Returns:
            服务状态信息字典

        Raises:
            ValueError: 服务不存在
        """
        service = self._get_service(service_id)
        return service.to_dict()

    def list_services(self) -> List[StdioServiceInstance]:
        """列出所有 stdio 服务.

        Returns:
            服务实例列表
        """
        return list(self._services.values())

    # --------------------------------------------------------
    # MCP 请求/响应
    # --------------------------------------------------------

    async def send_request(
        self,
        service_id: str,
        method: str,
        params: Optional[Dict[str, Any]] = None,
        timeout: float = 30.0,
    ) -> Dict[str, Any]:
        """向 stdio 服务发送 JSON-RPC 请求并等待响应.

        Args:
            service_id: 服务 ID
            method: JSON-RPC 方法名
            params: 请求参数
            timeout: 超时时间（秒）

        Returns:
            JSON-RPC 响应的 result 字段

        Raises:
            ValueError: 服务不存在或未运行
            asyncio.TimeoutError: 请求超时
            RuntimeError: 请求执行出错
        """
        service = self._get_service(service_id)

        if service.status != StdioServiceStatus.RUNNING:
            raise ValueError(f"服务未运行: {service.status}")

        if not service.process or service.process.stdin is None:
            raise RuntimeError("进程 stdin 不可用")

        req_id = service._get_next_request_id()

        request = {
            "jsonrpc": "2.0",
            "id": req_id,
            "method": method,
            "params": params or {},
        }

        # 创建 Future 等待响应
        loop = asyncio.get_event_loop()
        future = loop.create_future()
        service._pending_requests[req_id] = future

        try:
            # 写入 stdin
            request_json = json.dumps(request, ensure_ascii=False) + "\n"
            service.process.stdin.write(request_json.encode("utf-8"))
            await service.process.stdin.drain()

            # 等待响应
            response = await asyncio.wait_for(future, timeout=timeout)

            if "error" in response:
                error = response["error"]
                raise RuntimeError(
                    f"JSON-RPC 错误: {error.get('message', '未知错误')} "
                    f"(code: {error.get('code', -1)})"
                )

            return response.get("result", {})

        except asyncio.TimeoutError:
            raise asyncio.TimeoutError(
                f"请求超时 (method={method}, timeout={timeout}s)"
            )
        finally:
            service._pending_requests.pop(req_id, None)

    async def send_notification(
        self,
        service_id: str,
        method: str,
        params: Optional[Dict[str, Any]] = None,
    ) -> None:
        """向 stdio 服务发送 JSON-RPC 通知（无 id，无需响应）.

        Args:
            service_id: 服务 ID
            method: JSON-RPC 方法名
            params: 通知参数

        Raises:
            ValueError: 服务不存在或未运行
            RuntimeError: 进程 stdin 不可用
        """
        service = self._get_service(service_id)

        if service.status != StdioServiceStatus.RUNNING:
            raise ValueError(f"服务未运行: {service.status}")

        if not service.process or service.process.stdin is None:
            raise RuntimeError("进程 stdin 不可用")

        notification = {
            "jsonrpc": "2.0",
            "method": method,
            "params": params or {},
        }

        notification_json = json.dumps(notification, ensure_ascii=False) + "\n"
        service.process.stdin.write(notification_json.encode("utf-8"))
        await service.process.stdin.drain()

    # --------------------------------------------------------
    # 内部方法 - 进程管理
    # --------------------------------------------------------

    async def _spawn_process(self, service: StdioServiceInstance) -> None:
        """启动子进程并初始化后台读取任务.

        Args:
            service: 服务实例

        Raises:
            RuntimeError: 进程创建失败
            asyncio.TimeoutError: 启动超时
        """
        # 构建环境变量
        proc_env = os.environ.copy()
        if service.env:
            proc_env.update(service.env)

        try:
            process = await asyncio.create_subprocess_exec(
                service.command,
                *service.args,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=proc_env,
            )
        except FileNotFoundError as e:
            service.status = StdioServiceStatus.ERROR
            service.error_message = f"命令不存在: {e}"
            raise RuntimeError(f"启动失败，命令不存在: {service.command}") from e
        except Exception as e:
            service.status = StdioServiceStatus.ERROR
            service.error_message = f"进程创建失败: {e}"
            raise RuntimeError(f"进程创建失败: {e}") from e

        service.process = process
        service.pid = process.pid
        service.started_at = datetime.utcnow()

        # 启动后台读取任务
        service._stdout_task = asyncio.create_task(
            self._read_stdout(service),
            name=f"stdio_stdout_{service.service_id}",
        )
        service._stderr_task = asyncio.create_task(
            self._read_stderr(service),
            name=f"stdio_stderr_{service.service_id}",
        )
        service._monitor_task = asyncio.create_task(
            self._monitor_process(service),
            name=f"stdio_monitor_{service.service_id}",
        )

        # 等待启动完成（通过 initialize 握手检测）
        try:
            await self._wait_for_startup(service)
        except asyncio.TimeoutError:
            # 启动超时，强制终止
            logger.warning(f"服务 {service.name} 启动超时，正在终止...")
            await self._force_kill(service)
            service.status = StdioServiceStatus.ERROR
            service.error_message = f"启动超时 (>{self._settings.stdio_start_timeout}s)"
            raise

        service.status = StdioServiceStatus.RUNNING
        logger.info(f"stdio 服务已启动: {service.name} (pid={service.pid})")

    async def _wait_for_startup(self, service: StdioServiceInstance) -> None:
        """等待服务启动完成.

        通过发送 initialize 请求来确认服务已就绪。
        如果 initialize 失败，等待启动超时时间后再判断。

        Args:
            service: 服务实例

        Raises:
            asyncio.TimeoutError: 启动超时
        """
        # 给进程一点启动时间
        await asyncio.sleep(0.5)

        # 检查进程是否已经退出
        if service.process and service.process.returncode is not None:
            raise RuntimeError(
                f"进程启动后立即退出 (exit_code={service.process.returncode})"
            )

        # 尝试发送 initialize 请求
        # 注意：这里不使用 send_request，因为服务还未标记为 RUNNING
        timeout = self._settings.stdio_start_timeout
        start_time = asyncio.get_event_loop().time()

        while True:
            elapsed = asyncio.get_event_loop().time() - start_time
            if elapsed >= timeout:
                raise asyncio.TimeoutError("启动超时")

            # 检查进程状态
            if service.process and service.process.returncode is not None:
                raise RuntimeError(
                    f"进程意外退出 (exit_code={service.process.returncode})"
                )

            try:
                # 手动发送 initialize 请求
                result = await self._try_initialize(service, remaining=timeout - elapsed)
                if result is not None:
                    return
            except (asyncio.TimeoutError, RuntimeError, ValueError):
                # 重试
                await asyncio.sleep(0.5)
                continue

    async def _try_initialize(
        self, service: StdioServiceInstance, remaining: float
    ) -> Optional[Dict[str, Any]]:
        """尝试发送 initialize 请求.

        Args:
            service: 服务实例
            remaining: 剩余超时时间

        Returns:
            初始化结果，失败返回 None
        """
        if not service.process or service.process.stdin is None:
            return None

        req_id = service._get_next_request_id()
        request = {
            "jsonrpc": "2.0",
            "id": req_id,
            "method": "initialize",
            "params": {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {
                    "name": "m11-mcp-bus",
                    "version": "0.1.0",
                },
            },
        }

        loop = asyncio.get_event_loop()
        future = loop.create_future()
        service._pending_requests[req_id] = future

        try:
            request_json = json.dumps(request, ensure_ascii=False) + "\n"
            service.process.stdin.write(request_json.encode("utf-8"))
            await service.process.stdin.drain()

            response = await asyncio.wait_for(future, timeout=min(remaining, 5.0))

            if "result" in response:
                return response["result"]
            return None

        except Exception:
            return None
        finally:
            service._pending_requests.pop(req_id, None)

    async def _terminate_process(self, service: StdioServiceInstance) -> None:
        """终止子进程.

        先发送 SIGTERM，超时后发送 SIGKILL。

        Args:
            service: 服务实例
        """
        if not service.process:
            service.status = StdioServiceStatus.STOPPED
            service.stopped_at = datetime.utcnow()
            return

        try:
            # 尝试优雅终止
            if service.process.returncode is None:
                if hasattr(signal, "SIGTERM"):
                    service.process.terminate()
                else:
                    # Windows 平台使用 terminate（相当于 SIGTERM）
                    service.process.terminate()

                # 等待进程退出
                try:
                    await asyncio.wait_for(
                        service.process.wait(),
                        timeout=self._settings.stdio_stop_timeout,
                    )
                except asyncio.TimeoutError:
                    # 超时，强制杀死
                    logger.warning(
                        f"服务 {service.name} 优雅停止超时，强制杀死..."
                    )
                    if hasattr(signal, "SIGKILL"):
                        service.process.kill()
                    else:
                        # Windows 平台 kill 等同于 terminate
                        service.process.kill()
                    try:
                        await asyncio.wait_for(service.process.wait(), timeout=5.0)
                    except asyncio.TimeoutError:
                        logger.error(f"服务 {service.name} 强制杀死失败")

        finally:
            # 取消后台任务
            for task_attr in ("_stdout_task", "_stderr_task", "_monitor_task"):
                task = getattr(service, task_attr, None)
                if task and not task.done():
                    task.cancel()
                    try:
                        await task
                    except (asyncio.CancelledError, Exception):
                        pass

            service.exit_code = (
                service.process.returncode if service.process else None
            )
            service.status = StdioServiceStatus.STOPPED
            service.stopped_at = datetime.utcnow()
            service.pid = None
            logger.info(f"stdio 服务已停止: {service.name}")

    async def _force_kill(self, service: StdioServiceInstance) -> None:
        """强制杀死进程.

        Args:
            service: 服务实例
        """
        if not service.process:
            return

        try:
            if hasattr(signal, "SIGKILL"):
                service.process.kill()
            else:
                service.process.kill()
            await asyncio.wait_for(service.process.wait(), timeout=5.0)
        except Exception:
            pass

    # --------------------------------------------------------
    # 内部方法 - 后台读取任务
    # --------------------------------------------------------

    async def _read_stdout(self, service: StdioServiceInstance) -> None:
        """后台读取 stdout 任务.

        按行读取 stdout，解析 JSON-RPC 消息，匹配请求或触发通知回调。

        Args:
            service: 服务实例
        """
        if not service.process or service.process.stdout is None:
            return

        try:
            while True:
                line = await service.process.stdout.readline()
                if not line:
                    # EOF，进程已退出
                    break

                line_str = line.decode("utf-8", errors="replace").strip()
                if not line_str:
                    continue

                # 尝试解析 JSON
                try:
                    message = json.loads(line_str)
                except json.JSONDecodeError:
                    # 非 JSON 行，记录到 stderr 日志
                    service._append_stderr_log(f"[stdout non-json] {line_str}")
                    continue

                # 处理消息
                await self._handle_message(service, message)

        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.error(f"读取 stdout 出错 ({service.name}): {e}")
            service._append_stderr_log(f"[stdout error] {e}")

    async def _read_stderr(self, service: StdioServiceInstance) -> None:
        """后台读取 stderr 任务.

        将 stderr 输出记录到日志缓存。

        Args:
            service: 服务实例
        """
        if not service.process or service.process.stderr is None:
            return

        try:
            while True:
                line = await service.process.stderr.readline()
                if not line:
                    break

                line_str = line.decode("utf-8", errors="replace").rstrip("\n")
                if line_str:
                    service._append_stderr_log(line_str)
                    logger.debug(f"[{service.name} stderr] {line_str}")

        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.error(f"读取 stderr 出错 ({service.name}): {e}")

    async def _monitor_process(self, service: StdioServiceInstance) -> None:
        """监控进程退出的后台任务.

        Args:
            service: 服务实例
        """
        if not service.process:
            return

        try:
            exit_code = await service.process.wait()
            service.exit_code = exit_code

            # 进程意外退出（非主动停止）
            if service.status not in (
                StdioServiceStatus.STOPPING,
                StdioServiceStatus.STOPPED,
            ):
                service.status = StdioServiceStatus.ERROR
                service.error_message = f"进程意外退出 (exit_code={exit_code})"
                service.stopped_at = datetime.utcnow()
                service.pid = None

                # 清理 pending requests
                for future in service._pending_requests.values():
                    if not future.done():
                        future.set_exception(
                            RuntimeError(
                                f"进程意外退出 (exit_code={exit_code})"
                            )
                        )
                service._pending_requests.clear()

                logger.error(
                    f"stdio 服务意外退出: {service.name} (exit_code={exit_code})"
                )

                # 通知注册中心更新状态（如果已注册）
                await self._notify_service_exit(service)

        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.error(f"进程监控出错 ({service.name}): {e}")

    # --------------------------------------------------------
    # 内部方法 - 消息处理
    # --------------------------------------------------------

    async def _handle_message(
        self, service: StdioServiceInstance, message: Dict[str, Any]
    ) -> None:
        """处理收到的 JSON-RPC 消息.

        Args:
            service: 服务实例
            message: 解析后的 JSON-RPC 消息
        """
        msg_id = message.get("id")

        if msg_id is not None:
            # 响应消息 - 匹配 pending request
            future = service._pending_requests.get(msg_id)
            if future and not future.done():
                future.set_result(message)
            else:
                # 未匹配到请求，记录日志
                logger.debug(
                    f"收到未匹配的响应 ({service.name}, id={msg_id})"
                )
        else:
            # 通知消息（无 id）
            method = message.get("method", "unknown")
            params = message.get("params", {})
            logger.debug(
                f"收到通知 ({service.name}, method={method})"
            )

            # 触发通知回调
            for callback in service._notification_callbacks:
                try:
                    if asyncio.iscoroutinefunction(callback):
                        await callback(service.service_id, method, params)
                    else:
                        callback(service.service_id, method, params)
                except Exception as e:
                    logger.error(f"通知回调执行失败 ({service.name}): {e}")

    # --------------------------------------------------------
    # 内部方法 - 注册中心通知
    # --------------------------------------------------------

    async def _notify_service_exit(self, service: StdioServiceInstance) -> None:
        """通知注册中心服务退出.

        当 stdio 服务意外退出时，更新注册中心中的状态。

        Args:
            service: 服务实例
        """
        try:
            from .registry import mcp_registry

            # 按名称查找服务器
            server = mcp_registry.get_server_by_name(service.name)
            if server and server.transport_type == "stdio":
                mcp_registry.heartbeat(server.id, status="offline")
                logger.info(
                    f"已更新注册中心状态 ({service.name} -> offline)"
                )
        except Exception as e:
            logger.error(f"更新注册中心状态失败 ({service.name}): {e}")

    # --------------------------------------------------------
    # 工具方法
    # --------------------------------------------------------

    def _get_service(self, service_id: str) -> StdioServiceInstance:
        """获取服务实例.

        Args:
            service_id: 服务 ID

        Returns:
            服务实例

        Raises:
            ValueError: 服务不存在
        """
        service = self._services.get(service_id)
        if not service:
            raise ValueError(f"stdio 服务不存在: {service_id}")
        return service

    async def shutdown_all(self) -> None:
        """停止所有 stdio 服务.

        在应用关闭时调用，确保所有子进程被正确终止，防止僵尸进程。
        """
        if not self._services:
            return

        logger.info(f"正在停止所有 stdio 服务 (共 {len(self._services)} 个)...")

        tasks = []
        for service_id in list(self._services.keys()):
            tasks.append(self.stop_service(service_id))

        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

        logger.info("所有 stdio 服务已停止")


# ============================================================
# 单例实例
# ============================================================

stdio_manager = StdioServiceManager()
