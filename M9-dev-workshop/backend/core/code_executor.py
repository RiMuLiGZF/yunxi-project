"""云汐 M9 开发者工坊 - 代码执行器"""

import subprocess
import tempfile
import os
import time
import threading
from typing import Optional
from config import get_settings
from core.models_code import CodeExecutionRequest, CodeExecutionResult
from core.sandbox_security import is_code_allowed, get_safe_environ, validate_code_size


class CodeExecutor:
    """代码执行器（沙箱环境）"""

    def __init__(self):
        self._exec_count = 0        # 总执行次数
        self._exec_success = 0      # 成功次数
        self._exec_failed = 0       # 失败次数
        self._exec_total_time = 0.0 # 总执行时间
        self._stats_lock = threading.Lock()

    @property
    def exec_count(self):
        return self._exec_count

    @property
    def exec_success_count(self):
        return self._exec_success

    @property
    def exec_failed_count(self):
        return self._exec_failed

    @property
    def avg_exec_time(self):
        return round(self._exec_total_time / max(self._exec_count, 1), 3)

    LANGUAGE_EXTENSIONS = {
        "python": ".py",
        "javascript": ".js",
        "typescript": ".ts",
        "java": ".java",
        "c": ".c",
        "cpp": ".cpp",
        "go": ".go",
        "rust": ".rs",
        "bash": ".sh",
    }
    
    LANGUAGE_COMMANDS = {
        "python": ["python"],
        "javascript": ["node"],
        "typescript": ["npx", "ts-node"],
        "bash": ["bash"],
    }
    
    def execute(self, request: CodeExecutionRequest) -> CodeExecutionResult:
        """执行代码（沙箱模式）"""
        start_time = time.time()
        settings = get_settings()

        try:
            # P2-23: 代码大小检查
            size_ok, size_msg = validate_code_size(request.code, max_size_kb=100)
            if not size_ok:
                return CodeExecutionResult(
                    success=False,
                    stderr=size_msg,
                    execution_time=time.time() - start_time
                )

            # P2-23: 沙箱模式下检查危险代码
            if settings.code_exec_sandbox_enabled:
                allowed, findings = is_code_allowed(
                    request.code,
                    request.language,
                    sandbox_level="strict"
                )
                if not allowed:
                    danger_list = "; ".join(
                        f"第{f['line']}行: {f['description']}" for f in findings[:5]
                    )
                    return CodeExecutionResult(
                        success=False,
                        stderr=f"沙箱安全检测未通过: {danger_list}",
                        execution_time=time.time() - start_time,
                        exit_code=126
                    )

            # 创建临时文件
            ext = self.LANGUAGE_EXTENSIONS.get(request.language, ".txt")
            with tempfile.NamedTemporaryFile(mode='w', suffix=ext, delete=False, encoding='utf-8') as f:
                f.write(request.code)
                temp_file = f.name

            # 构建执行命令
            cmd_template = self.LANGUAGE_COMMANDS.get(request.language)
            if not cmd_template:
                return CodeExecutionResult(
                    success=False,
                    stderr=f"不支持的编程语言: {request.language}",
                    execution_time=time.time() - start_time
                )

            cmd = cmd_template + [temp_file]

            # P2-23: 使用安全的环境变量（移除敏感信息）
            env = get_safe_environ()
            if request.env and settings.code_exec_sandbox_enabled:
                # 沙箱模式下只允许设置白名单内的环境变量
                allowed_env_vars = {"LANG", "LC_ALL", "TZ", "PATH"}
                for k, v in request.env.items():
                    if k.upper() in allowed_env_vars or k.upper().startswith("PYTHON"):
                        env[k] = v
            elif request.env:
                env.update(request.env)

            # P2-23: 确保超时在限制内
            timeout = min(request.timeout, settings.code_exec_timeout)

            # 执行代码
            try:
                result = subprocess.run(
                    cmd,
                    capture_output=True,
                    text=True,
                    timeout=timeout,
                    env=env,
                )
                
                execution_time_val = time.time() - start_time
                with self._stats_lock:
                    self._exec_count += 1
                    self._exec_success += 1
                    self._exec_total_time += execution_time_val

                return CodeExecutionResult(
                    success=result.returncode == 0,
                    stdout=result.stdout,
                    stderr=result.stderr,
                    exit_code=result.returncode,
                    execution_time=execution_time_val
                )
            except subprocess.TimeoutExpired:
                with self._stats_lock:
                    self._exec_count += 1
                    self._exec_failed += 1
                return CodeExecutionResult(
                    success=False,
                    stderr=f"执行超时（{request.timeout}秒）",
                    execution_time=request.timeout
                )
        
        except Exception as e:
            with self._stats_lock:
                self._exec_count += 1
                self._exec_failed += 1
            return CodeExecutionResult(
                success=False,
                stderr=str(e),
                execution_time=time.time() - start_time
            )
        finally:
            # 清理临时文件
            try:
                if 'temp_file' in locals():
                    os.unlink(temp_file)
            except Exception:
                pass


# 全局单例
code_executor = CodeExecutor()
