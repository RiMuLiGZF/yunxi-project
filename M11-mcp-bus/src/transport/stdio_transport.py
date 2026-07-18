"""M11 MCP Bus - stdio 传输实现.

基于标准输入输出的子进程传输实现，继承 BaseTransport。
适用于与通过 stdin/stdout 通信的本地 MCP 服务通信。

特点:
- 子进程管理（启动、停止、重启）
- stdin/stdout 管道通信
- JSON-RPC 请求-响应匹配
- 通知消息支持
- 错误流捕获
"""

from __future__ import annotations

import asyncio
import json
import os
import signal
from asyncio import Queue
from typing import Any, Dict, List, Optional

from .base import BaseTransport, TransportState


class StdioTransport(BaseTransport):
    """stdio 传输实现.

    通过子进程的 stdin/stdout 管道进行 JSON-RPC 通信。
    每行一条 JSON-RPC 消息。

    使用方式:
        transport = StdioTransport(
            command="python",
            args=["-m", "my_mcp_server"],
        )
        await transport.connect()
        response = await transport.request({"jsonrpc": "2.0", "method": "tools/list", "id": 1})
        await transport.disconnect()
    """

    def __init__(
        self,
        command: str,
        args: Optional[List[str]] = None,
        env: Optional[Dict[str, str]] = None,
        cwd: Optional[str] = None,
        timeout: float = 30.0,
        start_timeout: float = 10.0,
        stop_timeout: float = 5.0,
    ) -> None:
        """初始化 stdio 传输.

        Args:
            command: 要执行的命令
            args: 命令参数列表
            env: 额外的环境变量
            cwd: 工作目录
            timeout: 请求超时时间（秒）
            start_timeout: 启动超时时间（秒）
            stop_timeout: 停止超时时间（秒）
        """
        super().__init__(transport_type="stdio", endpoint=f"{command} {' '.join(args or [])}")
        self._command = command
        self._args = args or []
        self._env = env or {}
        self._cwd = cwd
        self._timeout = timeout
        self._start_timeout = start_timeout
        self._stop_timeout = stop_timeout

        # 进程相关
        self._process: Optional[asyncio.subprocess.Process] = None
        self._pid: Optional[int] = None
        self._exit_code: Optional[int] = None
        self._error_message: str = ""

        # 请求-响应匹配
        self._pending_requests: Dict[Any, asyncio.Future] = {}
        self._next_request_id: int = 1

        # 消息队列
        self._message_queue: Queue[Dict[str, Any]] = Queue(maxsize=1000)

        # 通知回调（直接在消息处理中触发 BaseTransport 的 on_message）

        # 后台任务
        self._stdout_task: Optional[asyncio.Task] = None
        self._stderr_task: Optional[asyncio.Task] = None
        self._monitor_task: Optional[asyncio.Task] = None

        # stderr 日志缓存
        self._stderr_logs: List[str] = []

    # ============================================================
    # 连接管理
    # ============================================================

    async def connect(self) -> None:
        """启动子进程并建立 stdio 通信."""
        async with self._lock:
            if self._state == TransportState.CONNECTED:
                return

            self._set_state(TransportState.CONNECTING)

            try:
                # 构建环境变量
                proc_env = os.environ.copy()
                if self._env:
                    proc_env.update(self._env)

                # 启动子进程
                self._process = await asyncio.create_subprocess_exec(
                    self._command,
                    *self._args,
                    stdin=asyncio.subprocess.PIPE,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                    env=proc_env,
                    cwd=self._cwd,
                )

                self._pid = self._process.pid

                # 启动后台读取任务
                self._stdout_task = asyncio.create_task(
                    self._read_stdout(),
                    name=f"stdio_stdout_{self._pid}",
                )
                self._stderr_task = asyncio.create_task(
                    self._read_stderr(),
                    name=f"stdio_stderr_{self._pid}",
                )
                self._monitor_task = asyncio.create_task(
                    self._monitor_process(),
                    name=f"stdio_monitor_{self._pid}",
                )

                # 等待服务启动（通过 initialize 握手检测）
                await self._wait_for_startup()

                self._set_state(TransportState.CONNECTED)
                await self._emit_connect()

            except FileNotFoundError as e:
                self._set_state(TransportState.ERROR)
                self._error_message = f"Command not found: {e}"
                await self._emit_error(e)
                raise ConnectionError(f"Command not found: {self._command}") from e
            except Exception as e:
                self._set_state(TransportState.ERROR)
                self._error_message = str(e)
                await self._emit_error(e)
                raise ConnectionError(f"Stdio connection failed: {e}") from e

    async def disconnect(self) -> None:
        """停止子进程并断开连接."""
        async with self._lock:
            if self._state == TransportState.DISCONNECTED:
                return

            self._set_state(TransportState.DISCONNECTING)

            # 清理 pending requests
            for future in self._pending_requests.values():
                if not future.done():
                    future.set_exception(ConnectionError("Stdio transport closed"))
            self._pending_requests.clear()

            # 终止进程
            if self._process:
                try:
                    await self._terminate_process()
                except Exception:
                    pass

            # 取消后台任务
            for task_attr in ("_stdout_task", "_stderr_task", "_monitor_task"):
                task = getattr(self, task_attr, None)
                if task and not task.done():
                    task.cancel()
                    try:
                        await task
                    except (asyncio.CancelledError, Exception):
                        pass

            self._process = None
            self._pid = None
            self._set_state(TransportState.DISCONNECTED)
            await self._emit_disconnect("normal")

    # ============================================================
    # 消息收发
    # ============================================================

    async def send(self, message: Dict[str, Any]) -> None:
        """发送消息到子进程 stdin.

        Args:
            message: 消息字典

        Raises:
            ConnectionError: 连接未建立
            RuntimeError: 发送失败
        """
        if not self.is_connected():
            raise ConnectionError("Stdio transport not connected")

        if not self._process or self._process.stdin is None:
            raise RuntimeError("Process stdin not available")

        try:
            message_json = json.dumps(message, ensure_ascii=False) + "\n"
            self._process.stdin.write(message_json.encode("utf-8"))
            await self._process.stdin.drain()
        except Exception as e:
            await self._emit_error(e)
            raise RuntimeError(f"Stdio send failed: {e}") from e

    async def receive(self, timeout: Optional[float] = None) -> Optional[Dict[str, Any]]:
        """从消息队列接收一条消息.

        Args:
            timeout: 超时时间（秒），None 表示一直等待

        Returns:
            消息字典，超时返回 None
        """
        try:
            if timeout is None:
                return await self._message_queue.get()
            else:
                return await asyncio.wait_for(
                    self._message_queue.get(), timeout=timeout
                )
        except asyncio.TimeoutError:
            return None

    async def request(
        self,
        message: Dict[str, Any],
        timeout: Optional[float] = None,
    ) -> Dict[str, Any]:
        """发送请求并等待匹配的响应.

        如果消息没有 id（通知），直接发送后返回空字典。

        Args:
            message: 请求消息字典
            timeout: 超时时间（秒）

        Returns:
            响应消息字典

        Raises:
            ConnectionError: 连接未建立
            TimeoutError: 请求超时
            RuntimeError: 请求失败
        """
        if not self.is_connected():
            raise ConnectionError("Stdio transport not connected")

        request_id = message.get("id")
        if request_id is None:
            # 通知消息
            await self.send(message)
            return {}

        # 创建 Future 等待响应
        loop = asyncio.get_event_loop()
        future = loop.create_future()
        self._pending_requests[request_id] = future

        try:
            await self.send(message)
            response = await asyncio.wait_for(
                future, timeout=timeout or self._timeout
            )
            return response
        except asyncio.TimeoutError as e:
            raise TimeoutError(
                f"Stdio request timed out (id={request_id})"
            ) from e
        finally:
            self._pending_requests.pop(request_id, None)

    # ============================================================
    # 进程管理
    # ============================================================

    async def _terminate_process(self) -> None:
        """终止子进程.

        先发送 SIGTERM，超时后强制杀死。
        """
        if not self._process:
            return

        try:
            if self._process.returncode is None:
                # 尝试优雅终止
                if hasattr(signal, "SIGTERM"):
                    self._process.terminate()
                else:
                    self._process.terminate()  # Windows

                try:
                    await asyncio.wait_for(
                        self._process.wait(),
                        timeout=self._stop_timeout,
                    )
                except asyncio.TimeoutError:
                    # 强制杀死
                    if hasattr(signal, "SIGKILL"):
                        self._process.kill()
                    else:
                        self._process.kill()  # Windows
                    try:
                        await asyncio.wait_for(self._process.wait(), timeout=5.0)
                    except asyncio.TimeoutError:
                        pass

            self._exit_code = self._process.returncode
        except Exception:
            pass

    async def _wait_for_startup(self) -> None:
        """等待服务启动完成.

        通过发送 initialize 请求来检测服务是否就绪。
        """
        # 给进程一点启动时间
        await asyncio.sleep(0.5)

        # 检查进程是否已退出
        if self._process and self._process.returncode is not None:
            raise RuntimeError(
                f"Process exited immediately (exit_code={self._process.returncode})"
            )

        # 尝试发送 initialize 请求
        start_time = asyncio.get_event_loop().time()
        while True:
            elapsed = asyncio.get_event_loop().time() - start_time
            if elapsed >= self._start_timeout:
                raise TimeoutError("Stdio service startup timed out")

            # 检查进程状态
            if self._process and self._process.returncode is not None:
                raise RuntimeError(
                    f"Process exited unexpectedly (exit_code={self._process.returncode})"
                )

            try:
                result = await self._try_initialize(
                    remaining=self._start_timeout - elapsed
                )
                if result is not None:
                    return
            except (asyncio.TimeoutError, RuntimeError, ValueError):
                await asyncio.sleep(0.5)
                continue

    async def _try_initialize(self, remaining: float) -> Optional[Dict[str, Any]]:
        """尝试发送 initialize 请求.

        Args:
            remaining: 剩余超时时间

        Returns:
            初始化结果，失败返回 None
        """
        if not self._process or self._process.stdin is None:
            return None

        req_id = self._next_request_id
        self._next_request_id += 1

        request = {
            "jsonrpc": "2.0",
            "id": req_id,
            "method": "initialize",
            "params": {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {
                    "name": "m11-mcp-bus",
                    "version": "0.5.0",
                },
            },
        }

        loop = asyncio.get_event_loop()
        future = loop.create_future()
        self._pending_requests[req_id] = future

        try:
            request_json = json.dumps(request, ensure_ascii=False) + "\n"
            self._process.stdin.write(request_json.encode("utf-8"))
            await self._process.stdin.drain()

            response = await asyncio.wait_for(future, timeout=min(remaining, 5.0))

            if "result" in response:
                return response["result"]
            return None

        except Exception:
            return None
        finally:
            self._pending_requests.pop(req_id, None)

    # ============================================================
    # 后台读取任务
    # ============================================================

    async def _read_stdout(self) -> None:
        """后台读取 stdout 任务."""
        if not self._process or self._process.stdout is None:
            return

        try:
            while True:
                line = await self._process.stdout.readline()
                if not line:
                    break

                line_str = line.decode("utf-8", errors="replace").strip()
                if not line_str:
                    continue

                # 尝试解析 JSON
                try:
                    message = json.loads(line_str)
                except json.JSONDecodeError:
                    # 非 JSON 行，记录到 stderr 日志
                    self._stderr_logs.append(f"[stdout non-json] {line_str}")
                    continue

                # 处理消息
                await self._handle_message(message)

        except asyncio.CancelledError:
            raise
        except Exception as e:
            self._stderr_logs.append(f"[stdout error] {e}")

    async def _read_stderr(self) -> None:
        """后台读取 stderr 任务."""
        if not self._process or self._process.stderr is None:
            return

        try:
            while True:
                line = await self._process.stderr.readline()
                if not line:
                    break

                line_str = line.decode("utf-8", errors="replace").rstrip("\n")
                if line_str:
                    self._stderr_logs.append(line_str)

        except asyncio.CancelledError:
            raise
        except Exception:
            pass

    async def _monitor_process(self) -> None:
        """监控进程退出的后台任务."""
        if not self._process:
            return

        try:
            exit_code = await self._process.wait()
            self._exit_code = exit_code

            # 进程意外退出
            if self._state not in (
                TransportState.DISCONNECTING,
                TransportState.DISCONNECTED,
            ):
                self._set_state(TransportState.ERROR)
                self._error_message = (
                    f"Process exited unexpectedly (exit_code={exit_code})"
                )

                # 清理 pending requests
                for future in self._pending_requests.values():
                    if not future.done():
                        future.set_exception(
                            ConnectionError(
                                f"Process exited unexpectedly (exit_code={exit_code})"
                            )
                        )
                self._pending_requests.clear()

                await self._emit_disconnect(
                    f"process exited (code={exit_code})"
                )

        except asyncio.CancelledError:
            raise
        except Exception:
            pass

    async def _handle_message(self, message: Dict[str, Any]) -> None:
        """处理收到的 JSON-RPC 消息.

        Args:
            message: 解析后的消息字典
        """
        msg_id = message.get("id")

        if msg_id is not None:
            # 响应消息 - 匹配 pending request
            future = self._pending_requests.get(msg_id)
            if future and not future.done():
                future.set_result(message)

        # 放入消息队列
        try:
            self._message_queue.put_nowait(message)
        except asyncio.QueueFull:
            # 队列满，丢弃最旧的
            try:
                self._message_queue.get_nowait()
                self._message_queue.put_nowait(message)
            except asyncio.QueueFull:
                pass

        # 触发消息回调
        await self._emit_message(message)

    # ============================================================
    # 额外属性
    # ============================================================

    @property
    def pid(self) -> Optional[int]:
        """进程 PID."""
        return self._pid

    @property
    def exit_code(self) -> Optional[int]:
        """进程退出码."""
        return self._exit_code

    @property
    def error_message(self) -> str:
        """错误消息."""
        return self._error_message

    def get_stderr_logs(self, limit: int = 100) -> List[str]:
        """获取 stderr 日志.

        Args:
            limit: 返回的最大行数

        Returns:
            日志行列表（最新的在前）
        """
        logs = list(self._stderr_logs)
        return logs[-limit:] if limit > 0 else logs


__all__ = ["StdioTransport"]
