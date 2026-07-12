"""M9 Programming Dev - 代码执行器"""

import subprocess
import tempfile
import os
import time
from typing import Optional
from .config import settings
from .models import CodeExecutionRequest, CodeExecutionResult
from .sandbox_security import is_code_allowed, get_safe_environ, validate_code_size


class CodeExecutor:
    """代码执行器（沙箱环境）"""
    
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
                
                return CodeExecutionResult(
                    success=result.returncode == 0,
                    stdout=result.stdout,
                    stderr=result.stderr,
                    exit_code=result.returncode,
                    execution_time=time.time() - start_time
                )
            except subprocess.TimeoutExpired:
                return CodeExecutionResult(
                    success=False,
                    stderr=f"执行超时（{request.timeout}秒）",
                    execution_time=request.timeout
                )
        
        except Exception as e:
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
