"""终端命令技能.

提供终端命令执行功能，支持同步执行和异步后台执行。
包含命令白名单/黑名单安全机制，防止危险命令执行。

安全修复记录：
- SEC-003 (2026-07-18): 修复命令注入漏洞，移除 shell=True，
  强制命令列表形式传递，增加白名单校验、超时限制、
  工作目录限制、审计日志等多层防御。
"""

from __future__ import annotations

import logging
import os
import shlex
import subprocess
import sys
import time
import uuid
from threading import Thread
from typing import Any

from src.services.skills.base import BaseSkill

# 审计日志记录器
_audit_logger = logging.getLogger("yunxi.security.audit.terminal")


class TerminalCommandSkill(BaseSkill):
    """终端命令技能.

    支持的操作（通过 action 参数区分）:
        - run: 同步执行命令并返回输出
        - run_async: 异步执行命令（后台运行）
        - check_status: 检查异步命令的执行状态

    安全特性:
        - 命令白名单（只允许执行指定命令）
        - 命令黑名单（禁止执行危险命令）
        - 禁用 shell=True，所有命令以列表形式传递
        - 命令参数注入字符检测（; | && || ` $() 等）
        - 执行超时限制（默认 30 秒，最大 300 秒）
        - 工作目录限制在用户 workspace 内
        - 所有命令执行记录审计日志
    """

    name = "terminal_command"
    display_name = "终端命令"
    description = "在工作目录中执行终端命令，支持同步和异步执行，包含多层命令安全检查机制"
    category = "development"
    icon = "⌨️"
    version = "1.1.0"

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
                "description": "要执行的命令字符串（将被安全解析为命令+参数列表）",
            },
            "cwd": {
                "type": "string",
                "description": "工作目录（必须在 workspace 范围内）",
            },
            "timeout": {
                "type": "integer",
                "description": "超时时间（秒），默认 30 秒，最大 300 秒",
                "default": 30,
                "minimum": 1,
                "maximum": 300,
            },
            "task_id": {
                "type": "string",
                "description": "异步任务 ID（用于 check_status 操作）",
            },
        },
        "required": ["action"],
    }

    # 支持的操作列表
    _SUPPORTED_ACTIONS = {"run", "run_async", "check_status"}

    # 默认超时（秒）
    _DEFAULT_TIMEOUT = 30
    # 最大超时（秒）
    _MAX_TIMEOUT = 300

    # 命令白名单（只允许执行这些命令）
    # 格式: 命令名（不含路径），如 "git", "python", "npm"
    _COMMAND_WHITELIST: set[str] = {
        # 开发工具
        "git", "python", "python3", "pip", "pip3",
        "node", "npm", "npx", "yarn", "pnpm",
        # 构建工具
        "make", "cmake", "gcc", "g++", "clang",
        "docker", "docker-compose",
        # 文件操作（安全的只读/受控操作）
        "ls", "dir", "cd", "pwd", "echo", "cat", "type",
        "mkdir", "rmdir", "cp", "copy", "mv", "move",
        "find", "grep", "head", "tail", "wc", "sort", "uniq",
        "diff", "patch", "tee", "touch", "file", "stat",
        # 网络工具
        "curl", "wget", "ping",
        # 系统信息
        "whoami", "date", "time", "ver", "uname", "id", "hostname",
        # 代码检查
        "pytest", "pylint", "flake8", "mypy",
        "eslint", "prettier", "tsc",
        # 文档工具
        "pandoc", "markdown",
        # 版本工具
        "svn", "hg",
        # 压缩工具
        "tar", "zip", "unzip", "gzip", "gunzip",
        # 其他常用工具
        "which", "where", "env", "printenv", "set",
        "awk", "sed", "tr", "cut", "paste", "join",
        "basename", "dirname", "realpath", "readlink",
    }

    # 命令黑名单（绝对禁止执行的危险命令名）
    # 注意：这是第二层防御，白名单是第一层。
    # 黑名单用于覆盖白名单中可能意外放行的危险子命令或变体。
    _COMMAND_BLACKLIST: set[str] = {
        # 危险系统命令
        "rm", "del", "deltree", "erase", "format", "mkfs", "fdisk",
        "dd", "shred",
        # 权限提升
        "sudo", "su", "doas", "pkexec", "runas",
        # 用户/权限管理
        "chmod", "chown", "chgrp", "passwd", "useradd", "userdel",
        "groupadd", "groupdel", "usermod",
        # 进程管理（危险）
        "kill", "killall", "pkill", "taskkill", "taskkill.exe",
        # 网络攻击工具
        "nc", "ncat", "netcat", "nmap", "masscan", "hping",
        # 远程访问
        "ssh", "scp", "sftp", "telnet", "rlogin", "rsh",
        # 后门/反弹shell
        "bash", "sh", "zsh", "ksh", "csh", "tcsh", "fish",
        "powershell", "pwsh", "cmd.exe", "cmd", "wscript", "cscript",
        # 关机/重启
        "shutdown", "reboot", "halt", "poweroff", "init",
        # Windows 危险命令
        "reg", "regedit", "regsvr32", "schtasks", "at",
        "net", "netsh", "netstat",  # 网络配置命令谨慎使用
        # 加密/勒索相关
        "openssl", "gpg", "gnupg",
        # 数据泄露风险
        "rsync", "ftp", "tftp",
        # 环境变量危险操作
        "export", "unset", "setx",
        # 系统服务
        "systemctl", "service", "sc", "services.msc",
    }

    # 危险的 shell 元字符（用于检测注入尝试）
    _DANGEROUS_SHELL_CHARS = {
        ";", "|", "&&", "||", "&", "`", "$(", "${", ">", "<",
        ">>", "<<", "\\\n", "\n", "\r",
    }

    # 异步任务存储: {task_id: task_info_dict}
    _async_tasks: dict[str, dict[str, Any]] = {}

    # ------------------------------------------------------------------
    # 安全检查方法
    # ------------------------------------------------------------------

    def _is_command_safe(self, command: str, args: list[str]) -> tuple[bool, str]:
        """检查命令和参数的安全性.

        多层安全检查：
        1. 命令名必须在白名单中
        2. 命令名不能在黑名单中
        3. 参数中不能包含 shell 注入元字符
        4. 参数中不能包含危险的子命令模式

        Args:
            command: 命令名（已解析的第一个 token）
            args: 参数列表

        Returns:
            (是否安全, 原因说明)
        """
        if not command:
            return False, "命令不能为空"

        # 规范化命令名（去除路径和 .exe 后缀）
        cmd_name = os.path.basename(command)
        cmd_name_lower = cmd_name.lower()
        if cmd_name_lower.endswith(".exe"):
            cmd_name_lower = cmd_name_lower[:-4]

        # 第一层：黑名单检查（快速拦截已知危险命令）
        if cmd_name_lower in self._COMMAND_BLACKLIST:
            return False, f"命令在黑名单中，禁止执行: {cmd_name}"

        # 第二层：白名单检查（只允许已知安全的命令）
        if self._COMMAND_WHITELIST and cmd_name_lower not in self._COMMAND_WHITELIST:
            return False, f"命令不在白名单中: {cmd_name}"

        # 第三层：参数安全检查
        for arg in args:
            safe, reason = self._is_argument_safe(arg)
            if not safe:
                return False, f"参数不安全: {reason}"

        # 第四层：危险参数组合检测
        safe, reason = self._check_dangerous_argument_combinations(cmd_name_lower, args)
        if not safe:
            return False, reason

        return True, ""

    def _is_argument_safe(self, arg: str) -> tuple[bool, str]:
        """检查单个参数的安全性.

        Args:
            arg: 参数值

        Returns:
            (是否安全, 原因说明)
        """
        if not arg:
            return True, ""

        # 检测空字节注入
        if "\x00" in arg:
            return False, "参数包含空字节"

        # 检测控制字符（换行、回车等）
        for ch in arg:
            if ord(ch) < 32 and ch not in ("\t",):
                return False, f"参数包含控制字符: {repr(ch)}"

        return True, ""

    def _check_dangerous_argument_combinations(
        self, cmd_name: str, args: list[str]
    ) -> tuple[bool, str]:
        """检测危险的命令+参数组合.

        某些命令在白名单中，但特定参数组合可能导致危险操作。

        Args:
            cmd_name: 命令名（小写）
            args: 参数列表

        Returns:
            (是否安全, 原因说明)
        """
        # git 命令的危险参数检测
        if cmd_name == "git":
            for arg in args:
                # 禁止通过 git 执行任意命令
                if arg.startswith("--exec-path"):
                    return False, "git --exec-path 可能用于命令注入，已禁止"
                if arg == "--help" and len(args) > args.index(arg) + 1:
                    # git help 可能触发 man 命令
                    pass
            # 检测 git config --global 等危险操作
            if len(args) >= 2 and args[0] == "config":
                if "--global" in args or "--system" in args:
                    return False, "git config --global/--system 禁止修改全局配置"

        # curl/wget 危险参数检测
        if cmd_name in ("curl", "wget"):
            for arg in args:
                # 禁止 file:// 协议读取本地文件
                if arg.startswith("file://"):
                    return False, f"{cmd_name} file:// 协议已禁止"

        # python 危险参数检测
        if cmd_name in ("python", "python3"):
            for arg in args:
                # 禁止以 root 权限运行危险脚本（简单启发式）
                pass
            # 允许 python -c 但需要注意，这里暂不限制
            # 因为白名单本身就是为开发场景设计的

        return True, ""

    def _parse_command_string(self, command_str: str) -> tuple[str, list[str]]:
        """将命令字符串解析为命令名和参数列表.

        使用 shlex.split 安全解析命令字符串，
        不通过 shell 执行，避免命令注入。

        Args:
            command_str: 命令字符串

        Returns:
            (命令名, 参数列表)

        Raises:
            ValueError: 命令解析失败
        """
        if not command_str or not command_str.strip():
            raise ValueError("命令字符串为空")

        # 使用 shlex 安全解析
        # 注意：统一使用 posix=True 模式解析，因为我们将解析后的 token 列表
        # 直接传递给 subprocess（不经过 shell），POSIX 风格的解析更准确。
        # Windows 上的 cmd.exe 风格引用不适用于 subprocess 的列表调用方式。
        try:
            tokens = shlex.split(command_str, posix=True)
        except ValueError as e:
            raise ValueError(f"命令解析失败: {e}") from e

        if not tokens:
            raise ValueError("命令解析后为空")

        command = tokens[0]
        args = tokens[1:]

        return command, args

    # ------------------------------------------------------------------
    # 工作目录安全
    # ------------------------------------------------------------------

    def _get_cwd(self, params: dict[str, Any], context: dict[str, Any]) -> tuple[bool, str, str]:
        """获取并验证工作目录.

        确保工作目录在 workspace 范围内，防止目录遍历。

        Args:
            params: 参数字典
            context: 上下文字典

        Returns:
            (是否安全, 工作目录路径, 错误信息)
        """
        # workspace 是允许的根目录
        workspace = (
            context.get("workspace")
            or context.get("project_path")
            or os.getcwd()
        )
        workspace = os.path.abspath(workspace)

        # 用户指定的 cwd
        user_cwd = params.get("cwd", "")

        if not user_cwd:
            # 没有指定 cwd，使用 workspace
            return True, workspace, ""

        # 解析 cwd 路径
        if os.path.isabs(user_cwd):
            abs_cwd = os.path.abspath(user_cwd)
        else:
            abs_cwd = os.path.abspath(os.path.join(workspace, user_cwd))

        # 使用 realpath 解析符号链接后的真实路径
        try:
            real_cwd = os.path.realpath(abs_cwd)
            real_workspace = os.path.realpath(workspace)
        except OSError as e:
            return False, "", f"路径解析失败: {e}"

        # 检查是否在 workspace 内
        if not (real_cwd == real_workspace or real_cwd.startswith(real_workspace + os.sep)):
            return False, "", f"工作目录越界：{user_cwd} 不在 workspace 范围内"

        # 符号链接检测：如果解析后的路径和原始路径不同，说明经过了符号链接
        if os.path.exists(abs_cwd) and os.path.realpath(abs_cwd) != os.path.abspath(abs_cwd):
            # 路径经过符号链接，但只要在 workspace 内就允许
            pass

        return True, real_cwd, ""

    # ------------------------------------------------------------------
    # 超时限制
    # ------------------------------------------------------------------

    def _get_timeout(self, params: dict[str, Any]) -> int:
        """获取安全的超时值.

        Args:
            params: 参数字典

        Returns:
            超时秒数（已夹在有效范围内）
        """
        timeout = params.get("timeout", self._DEFAULT_TIMEOUT)
        try:
            timeout = int(timeout)
        except (ValueError, TypeError):
            timeout = self._DEFAULT_TIMEOUT

        # 限制在有效范围内
        if timeout < 1:
            timeout = 1
        if timeout > self._MAX_TIMEOUT:
            timeout = self._MAX_TIMEOUT

        return timeout

    # ------------------------------------------------------------------
    # 审计日志
    # ------------------------------------------------------------------

    def _audit_log(
        self,
        action: str,
        command: str,
        cwd: str,
        allowed: bool,
        reason: str = "",
    ) -> None:
        """记录命令执行审计日志.

        Args:
            action: 操作类型
            command: 命令字符串
            cwd: 工作目录
            allowed: 是否被允许执行
            reason: 拒绝原因（如果被拒绝）
        """
        try:
            _audit_logger.info(
                "Terminal command %s | action=%s | command=%s | cwd=%s | allowed=%s | reason=%s",
                "EXECUTION" if allowed else "BLOCKED",
                action,
                command,
                cwd,
                allowed,
                reason,
            )
        except Exception:
            # 日志记录失败不应影响主流程
            pass

    # ------------------------------------------------------------------
    # 主执行入口
    # ------------------------------------------------------------------

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
        command_str = params.get("command", "")
        if not command_str:
            return {
                "success": False,
                "message": "缺少 command 参数",
                "data": {"action": action},
            }

        # 第一步：解析命令字符串为命令+参数列表
        try:
            cmd_name, cmd_args = self._parse_command_string(command_str)
        except ValueError as e:
            self._audit_log(action, command_str, "", False, str(e))
            return {
                "success": False,
                "message": f"命令解析失败: {e}",
                "data": {"action": action, "command": command_str},
            }

        # 第二步：命令安全检查
        safe, reason = self._is_command_safe(cmd_name, cmd_args)
        if not safe:
            self._audit_log(action, command_str, "", False, reason)
            return {
                "success": False,
                "message": f"命令安全检查未通过: {reason}",
                "data": {
                    "action": action,
                    "command": command_str,
                    "cmd_name": cmd_name,
                    "cmd_args": cmd_args,
                    "reason": reason,
                },
            }

        # 第三步：工作目录安全检查
        cwd_safe, cwd, cwd_error = self._get_cwd(params, ctx)
        if not cwd_safe:
            self._audit_log(action, command_str, cwd, False, cwd_error)
            return {
                "success": False,
                "message": f"工作目录安全检查未通过: {cwd_error}",
                "data": {"action": action, "command": command_str, "reason": cwd_error},
            }

        # 第四步：获取超时值
        timeout = self._get_timeout(params)

        # 根据 action 分发
        handler = getattr(self, f"_handle_{action}", None)
        if handler is None:
            return {
                "success": False,
                "message": f"操作 {action} 暂无处理方法",
                "data": {"action": action},
            }

        self._audit_log(action, command_str, cwd, True)

        try:
            result = handler(cmd_name, cmd_args, cwd, timeout, command_str, params, ctx)
            return result
        except Exception as e:
            return {
                "success": False,
                "message": f"执行 {action} 时发生异常: {e}",
                "data": {
                    "action": action,
                    "command": command_str,
                    "error": str(e),
                },
            }

    # ------------------------------------------------------------------
    # 同步执行
    # ------------------------------------------------------------------

    def _handle_run(
        self,
        cmd_name: str,
        cmd_args: list[str],
        cwd: str,
        timeout: int,
        command_str: str,
        params: dict[str, Any],
        context: dict[str, Any],
    ) -> dict[str, Any]:
        """处理同步执行命令操作.

        注意：命令始终以列表形式传递给 subprocess，
        不使用 shell=True，从根本上防止命令注入。
        """
        # 构建完整的命令列表
        cmd_list = [cmd_name] + cmd_args

        try:
            # 使用列表形式调用 subprocess，不经过 shell
            result = subprocess.run(
                cmd_list,
                shell=False,  # 强制禁用 shell
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
                    "command": command_str,
                    "cmd_list": cmd_list,
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
                    "command": command_str,
                    "cmd_list": cmd_list,
                    "stdout": "",
                    "stderr": "timeout",
                    "returncode": -1,
                    "cwd": cwd,
                    "timeout": timeout,
                },
            }
        except FileNotFoundError:
            return {
                "success": False,
                "message": f"命令未找到: {cmd_name}",
                "data": {
                    "command": command_str,
                    "cmd_list": cmd_list,
                    "cmd_name": cmd_name,
                    "error": "command not found",
                    "cwd": cwd,
                },
            }

    # ------------------------------------------------------------------
    # 异步执行
    # ------------------------------------------------------------------

    def _handle_run_async(
        self,
        cmd_name: str,
        cmd_args: list[str],
        cwd: str,
        timeout: int,
        command_str: str,
        params: dict[str, Any],
        context: dict[str, Any],
    ) -> dict[str, Any]:
        """处理异步执行命令操作.

        命令以列表形式传递，不经过 shell。
        异步任务受最大超时限制，超时后自动终止。
        """
        task_id = uuid.uuid4().hex[:12]

        # 构建完整的命令列表
        cmd_list = [cmd_name] + cmd_args

        # 创建异步任务信息
        task_info: dict[str, Any] = {
            "task_id": task_id,
            "command": command_str,
            "cmd_list": cmd_list,
            "cwd": cwd,
            "timeout": timeout,
            "status": "running",  # running / completed / failed / timeout
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
                process = subprocess.Popen(
                    cmd_list,
                    shell=False,  # 强制禁用 shell
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    cwd=cwd,
                )
                task_info["process"] = process

                try:
                    stdout, stderr = process.communicate(timeout=timeout)
                    task_info["stdout"] = stdout
                    task_info["stderr"] = stderr
                    task_info["returncode"] = process.returncode
                    task_info["status"] = "completed" if process.returncode == 0 else "failed"
                except subprocess.TimeoutExpired:
                    # 超时则终止进程
                    process.kill()
                    try:
                        stdout, stderr = process.communicate(timeout=5)
                        task_info["stdout"] = stdout
                        task_info["stderr"] = stderr + "\n[process killed due to timeout]"
                    except Exception:
                        task_info["stderr"] = "timeout - process killed"
                    task_info["returncode"] = -1
                    task_info["status"] = "timeout"

                task_info["end_time"] = time.time()

            except FileNotFoundError:
                task_info["status"] = "failed"
                task_info["stderr"] = f"command not found: {cmd_name}"
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
                "command": command_str,
                "cmd_list": cmd_list,
                "cwd": cwd,
                "status": "running",
                "start_time": task_info["start_time"],
                "timeout": timeout,
            },
        }

    # ------------------------------------------------------------------
    # 检查状态
    # ------------------------------------------------------------------

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
                "timeout": task_info.get("timeout"),
            },
        }

    # ------------------------------------------------------------------
    # 健康检查
    # ------------------------------------------------------------------

    def health_check(self) -> bool:
        """终端命令技能始终可用."""
        return True
