"""终端命令技能.

提供终端命令执行功能，支持同步执行和异步后台执行。
包含命令白名单/黑名单安全机制，防止危险命令执行。
"""

from __future__ import annotations

import os
import shlex
import subprocess
import sys
import time
import uuid
from threading import Thread
from typing import Any

try:
    from src.services.skills.base import BaseSkill
except ImportError:
    from services.skills.base import BaseSkill  # type: ignore


class TerminalCommandSkill(BaseSkill):
    """终端命令技能.

    支持的操作（通过 action 参数区分）:
        - run: 同步执行命令并返回输出
        - run_async: 异步执行命令（后台运行）
        - check_status: 检查异步命令的执行状态

    安全特性:
        - 命令白名单（只允许执行指定命令）
        - 命令黑名单（禁止执行危险命令）
        - 默认启用安全检查
    """

    name = "terminal_command"
    display_name = "终端命令"
    description = "在工作目录中执行终端命令，支持同步和异步执行，包含命令安全检查机制"
    category = "development"
    icon = "⌨️"
    version = "1.0.0"

    parameters = {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "description": "操作类型：run(同步执行) / run_async(异步执行) / check_status(检查状态)",
                "enum": ["run", "run_async", "check_status"],
            },
            "command": {
                "type": "string",
                "description": "要执行的命令字符串",
            },
            "cwd": {
                "type": "string",
                "description": "工作目录（默认为当前工作目录）",
            },
            "timeout": {
                "type": "integer",
                "description": "超时时间（秒），仅用于 run 操作，默认 60 秒",
                "default": 60,
                "minimum": 1,
            },
            "task_id": {
                "type": "string",
                "description": "异步任务 ID（用于 check_status 操作）",
            },
            "shell": {
                "type": "boolean",
                "description": "是否使用 shell 执行（默认 False，更安全）",
                "default": False,
            },
        },
        "required": ["action"],
    }

    # 支持的操作列表
    _SUPPORTED_ACTIONS = {"run", "run_async", "check_status"}

    # 命令白名单（为空表示不启用白名单，允许所有命令通过黑名单检查）
    # 格式: 命令名（不含路径），如 "git", "python", "npm"
    _COMMAND_WHITELIST: set[str] = {
        # 开发工具
        "git", "python", "python3", "pip", "pip3",
        "node", "npm", "npx", "yarn", "pnpm",
        # 构建工具
        "make", "cmake", "gcc", "g++", "clang",
        "docker", "docker-compose",
        # 文件操作
        "ls", "dir", "cd", "pwd", "echo", "cat", "type",
        "mkdir", "rmdir", "cp", "copy", "mv", "move",
        "find", "grep", "head", "tail",
        # 网络工具
        "curl", "wget", "ping",
        # 系统信息
        "whoami", "date", "time", "ver", "uname",
        # 代码检查
        "pytest", "pylint", "flake8", "mypy",
        "eslint", "prettier", "tsc",
    }

    # 命令黑名单（绝对禁止执行的危险命令）
    _COMMAND_BLACKLIST: set[str] = {
        # 危险系统命令
        "rm -rf /", "format", "del /f /s /q",
        # 敏感文件操作
        "sudo", "su", "chmod 777", "chown",
        # 网络攻击
        "nc -lvp", "nmap", "masscan",
        # 加密/勒索
        "openssl enc", "gpg --encrypt",
        # 数据泄露
        "scp -r", "rsync -av",
        # 后门/反弹shell
        "bash -i >&", "/dev/tcp/", "nc -e",
        # 关机/重启
        "shutdown", "reboot", "halt", "poweroff",
        # Windows 危险命令
        "format c:", "del c:\\windows", "rmdir /s /q c:\\",
    }

    # 异步任务存储: {task_id: task_info_dict}
    _async_tasks: dict[str, dict[str, Any]] = {}

    def _check_command_safety(self, command: str) -> tuple[bool, str]:
        """检查命令安全性.

        先检查黑名单，再检查白名单（如果启用）。

        Args:
            command: 命令字符串

        Returns:
            (是否安全, 原因说明)
        """
        if not command or not command.strip():
            return False, "命令不能为空"

        cmd_lower = command.lower().strip()

        # 黑名单检查（精确匹配危险模式）
        for pattern in self._COMMAND_BLACKLIST:
            if pattern.lower() in cmd_lower:
                return False, f"命令包含危险模式: {pattern}"

        # 白名单检查（如果白名单非空）
        if self._COMMAND_WHITELIST:
            # 提取命令名（第一个词）
            if sys.platform == "win32" and cmd_lower.startswith("cmd /c "):
                # Windows cmd /c 包装的命令，提取实际命令
                rest = command.strip()[len("cmd /c "):].strip()
                first_token = rest.split()[0] if rest.split() else ""
            else:
                first_token = command.strip().split()[0] if command.strip() else ""

            # 去除路径，只保留命令名
            cmd_name = os.path.basename(first_token) if first_token else ""
            cmd_name_lower = cmd_name.lower()

            # 移除 .exe 后缀（Windows）
            if cmd_name_lower.endswith(".exe"):
                cmd_name_lower = cmd_name_lower[:-4]

            if cmd_name_lower and cmd_name_lower not in self._COMMAND_WHITELIST:
                return False, f"命令不在白名单中: {cmd_name}"

        return True, ""

    def _get_cwd(self, params: dict[str, Any], context: dict[str, Any]) -> str:
        """获取工作目录.

        Args:
            params: 参数字典
            context: 上下文字典

        Returns:
            工作目录路径
        """
        cwd = (
            params.get("cwd")
            or context.get("project_path")
            or context.get("workspace")
            or os.getcwd()
        )
        return os.path.abspath(cwd) if cwd else os.getcwd()

    def execute(
        self,
        params: dict[str, Any],
        context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """执行终端命令操作.

        Args:
            params: 参数字典
            context: 执行上下文

        Returns:
            执行结果字典
        """
        ctx = context or {}
        action = params.get("action", "")

        if not action:
            return {
                "success": False,
                "message": "缺少 action 参数",
                "data": {"supported_actions": sorted(self._SUPPORTED_ACTIONS)},
            }

        if action not in self._SUPPORTED_ACTIONS:
            return {
                "success": False,
                "message": f"不支持的操作: {action}",
                "data": {"supported_actions": sorted(self._SUPPORTED_ACTIONS)},
            }

        # check_status 不需要命令参数
        if action == "check_status":
            return self._handle_check_status(params, ctx)

        # 其他操作需要命令参数
        command = params.get("command", "")
        if not command:
            return {
                "success": False,
                "message": "缺少 command 参数",
                "data": {"action": action},
            }

        # 安全检查
        safe, reason = self._check_command_safety(command)
        if not safe:
            return {
                "success": False,
                "message": f"命令安全检查未通过: {reason}",
                "data": {"action": action, "command": command, "reason": reason},
            }

        # 根据 action 分发
        handler = getattr(self, f"_handle_{action}", None)
        if handler is None:
            return {
                "success": False,
                "message": f"操作 {action} 暂无处理方法",
                "data": {"action": action},
            }

        try:
            result = handler(command, params, ctx)
            return result
        except Exception as e:
            return {
                "success": False,
                "message": f"执行 {action} 时发生异常: {e}",
                "data": {
                    "action": action,
                    "command": command,
                    "error": str(e),
                },
            }

    def _handle_run(
        self,
        command: str,
        params: dict[str, Any],
        context: dict[str, Any],
    ) -> dict[str, Any]:
        """处理同步执行命令操作."""
        cwd = self._get_cwd(params, context)
        timeout = params.get("timeout", 60)
        use_shell = params.get("shell", False)

        try:
            if use_shell:
                # 使用 shell 执行
                result = subprocess.run(
                    command,
                    shell=True,
                    capture_output=True,
                    text=True,
                    cwd=cwd,
                    timeout=timeout,
                )
            else:
                # 安全执行（参数列表形式）
                if sys.platform == "win32":
                    # Windows 使用 cmd /c
                    cmd_list = ["cmd", "/c", command]
                else:
                    # Unix 使用 sh -c
                    cmd_list = ["sh", "-c", command]

                result = subprocess.run(
                    cmd_list,
                    capture_output=True,
                    text=True,
                    cwd=cwd,
                    timeout=timeout,
                )

            success = result.returncode == 0
            return {
                "success": success,
                "message": "命令执行成功" if success else f"命令执行失败，返回码: {result.returncode}",
                "data": {
                    "command": command,
                    "stdout": result.stdout,
                    "stderr": result.stderr,
                    "returncode": result.returncode,
                    "cwd": cwd,
                    "timeout": timeout,
                },
            }

        except subprocess.TimeoutExpired:
            return {
                "success": False,
                "message": f"命令执行超时（{timeout}秒）",
                "data": {
                    "command": command,
                    "stdout": "",
                    "stderr": "timeout",
                    "returncode": -1,
                    "cwd": cwd,
                    "timeout": timeout,
                },
            }

    def _handle_run_async(
        self,
        command: str,
        params: dict[str, Any],
        context: dict[str, Any],
    ) -> dict[str, Any]:
        """处理异步执行命令操作."""
        cwd = self._get_cwd(params, context)
        task_id = uuid.uuid4().hex[:12]

        # 创建异步任务信息
        task_info: dict[str, Any] = {
            "task_id": task_id,
            "command": command,
            "cwd": cwd,
            "status": "running",  # running / completed / failed
            "stdout": "",
            "stderr": "",
            "returncode": None,
            "start_time": time.time(),
            "end_time": None,
            "process": None,
        }

        # 启动后台线程执行命令
        def _run_async_task():
            try:
                if sys.platform == "win32":
                    cmd_list = ["cmd", "/c", command]
                else:
                    cmd_list = ["sh", "-c", command]

                process = subprocess.Popen(
                    cmd_list,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    cwd=cwd,
                )
                task_info["process"] = process

                stdout, stderr = process.communicate()
                task_info["stdout"] = stdout
                task_info["stderr"] = stderr
                task_info["returncode"] = process.returncode
                task_info["status"] = "completed" if process.returncode == 0 else "failed"
                task_info["end_time"] = time.time()

            except Exception as e:
                task_info["status"] = "failed"
                task_info["stderr"] = str(e)
                task_info["end_time"] = time.time()

        thread = Thread(target=_run_async_task, daemon=True)
        thread.start()

        # 存储任务信息
        self._async_tasks[task_id] = task_info

        return {
            "success": True,
            "message": "命令已启动（后台运行）",
            "data": {
                "task_id": task_id,
                "command": command,
                "cwd": cwd,
                "status": "running",
                "start_time": task_info["start_time"],
            },
        }

    def _handle_check_status(
        self,
        params: dict[str, Any],
        context: dict[str, Any],
    ) -> dict[str, Any]:
        """处理检查异步任务状态操作."""
        task_id = params.get("task_id", "")
        if not task_id:
            return {
                "success": False,
                "message": "缺少 task_id 参数",
                "data": {"action": "check_status"},
            }

        task_info = self._async_tasks.get(task_id)
        if task_info is None:
            return {
                "success": False,
                "message": f"任务不存在: {task_id}",
                "data": {"task_id": task_id},
            }

        # 计算运行时长
        duration = 0.0
        if task_info["end_time"]:
            duration = task_info["end_time"] - task_info["start_time"]
        else:
            duration = time.time() - task_info["start_time"]

        return {
            "success": True,
            "message": f"任务状态: {task_info['status']}",
            "data": {
                "task_id": task_id,
                "command": task_info["command"],
                "status": task_info["status"],
                "stdout": task_info["stdout"],
                "stderr": task_info["stderr"],
                "returncode": task_info["returncode"],
                "start_time": task_info["start_time"],
                "end_time": task_info["end_time"],
                "duration": round(duration, 2),
                "cwd": task_info["cwd"],
            },
        }

    def health_check(self) -> bool:
        """终端命令技能始终可用."""
        return True
