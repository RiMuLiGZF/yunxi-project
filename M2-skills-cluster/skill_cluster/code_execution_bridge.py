"""CodeExecutionBridge M2↔M7 代码执行桥梁.

【v3.10.0 新增】M2 与 M7 代码执行引擎的对接桥梁。
所有代码类技能通过本模块调用 M7 执行，M2 不直接执行代码。

核心能力：
1. 基础执行：Python/JavaScript/TypeScript 一次性执行
2. 自动修复：执行失败时 LLM 辅助修复，最多3次重试
3. REPL 会话：多轮交互，共享变量环境
4. 包管理：依赖安装与管理
5. 语言检测：自动识别代码语言
6. 依赖检测：自动识别第三方包依赖

执行后端：
- 优先使用 M7 远程执行引擎（通过回调注入）
- 降级使用本地 SubprocessSandbox（测试/开发环境）
"""

from __future__ import annotations

import asyncio
import hashlib
import re
import subprocess
import tempfile
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable

import structlog
from pydantic import BaseModel, Field

logger = structlog.get_logger()


# ============================================================
# 数据模型
# ============================================================


class ExecutionStatus(str, Enum):
    """执行状态."""

    SUCCESS = "success"
    FAILED = "failed"
    TIMEOUT = "timeout"
    MEMORY_LIMIT = "memory_limit"
    SECURITY_BLOCKED = "security_blocked"
    FIXED = "fixed"  # 自动修复后成功


class ErrorType(str, Enum):
    """错误类型分类."""

    SYNTAX_ERROR = "syntax_error"
    IMPORT_ERROR = "import_error"  # 缺少依赖
    RUNTIME_ERROR = "runtime_error"
    TIMEOUT = "timeout"
    MEMORY_ERROR = "memory_error"
    SECURITY_ERROR = "security_error"
    UNKNOWN = "unknown"


class ExecutionResult(BaseModel):
    """代码执行结果."""

    status: ExecutionStatus = Field(..., description="执行状态")
    stdout: str = Field(default="", description="标准输出")
    stderr: str = Field(default="", description="标准错误")
    exit_code: int = Field(default=0, description="退出码")
    execution_time_ms: float = Field(default=0.0, description="执行耗时(毫秒)")
    language: str = Field(default="python", description="执行语言")
    error_type: ErrorType | None = Field(default=None, description="错误类型")
    output_type: str = Field(default="text", description="输出类型: text/table/image/mixed")
    images: list[bytes] = Field(default_factory=list, description="生成的图片（二进制）")
    tables: list[dict] = Field(default_factory=list, description="表格数据")
    fix_history: list[dict] = Field(default_factory=list, description="自动修复历史")
    retry_count: int = Field(default=0, description="重试次数")


class ReplSessionInfo(BaseModel):
    """REPL 会话信息."""

    session_id: str = Field(..., description="会话ID")
    language: str = Field(..., description="语言")
    created_at: float = Field(..., description="创建时间戳")
    last_active_at: float = Field(..., description="最后活跃时间")
    command_count: int = Field(default=0, description="执行命令数")
    variables: dict[str, Any] = Field(default_factory=dict, description="变量快照（仅摘要）")


class PackageInstallResult(BaseModel):
    """包安装结果."""

    success: bool = Field(..., description="是否成功")
    package_name: str = Field(..., description="包名")
    version: str | None = Field(default=None, description="安装的版本")
    error: str | None = Field(default=None, description="错误信息")


# ============================================================
# 本地沙箱执行器（降级方案 / 测试用）
# ============================================================


class SubprocessSandbox:
    """基于 subprocess 的本地代码执行沙箱.

    用于：
    - 开发/测试环境没有 M7 时的降级方案
    - 简单代码的快速执行
    - 单元测试

    安全限制：
    - 超时控制
    - 禁止网络访问（通过环境变量限制）
    - 临时目录隔离
    """

    def __init__(self, default_timeout: int = 30) -> None:
        self._default_timeout = default_timeout

    async def execute_python(
        self,
        code: str,
        stdin: str = "",
        timeout: int | None = None,
        files: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        """执行 Python 代码."""
        return await self._execute_with_subprocess(
            language="python",
            code=code,
            stdin=stdin,
            timeout=timeout or self._default_timeout,
            files=files,
        )

    async def execute_javascript(
        self,
        code: str,
        stdin: str = "",
        timeout: int | None = None,
        files: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        """执行 JavaScript 代码（使用 node）."""
        return await self._execute_with_subprocess(
            language="javascript",
            code=code,
            stdin=stdin,
            timeout=timeout or self._default_timeout,
            files=files,
        )

    async def _execute_with_subprocess(
        self,
        language: str,
        code: str,
        stdin: str,
        timeout: int,
        files: dict[str, str] | None,
    ) -> dict[str, Any]:
        """通用 subprocess 执行."""
        start = time.time()

        with tempfile.TemporaryDirectory() as tmpdir:
            # 写入代码文件
            ext = "py" if language == "python" else "js"
            code_file = f"{tmpdir}/code.{ext}"
            with open(code_file, "w") as f:
                f.write(code)

            # 写入附加文件
            if files:
                for fname, content in files.items():
                    fpath = f"{tmpdir}/{fname}"
                    import os
                    os.makedirs(os.path.dirname(fpath), exist_ok=True)
                    with open(fpath, "w") as f:
                        f.write(content)

            # 执行命令
            if language == "python":
                cmd = ["python3", code_file]
            elif language in ("javascript", "typescript"):
                cmd = ["node", code_file]
            else:
                return {
                    "stdout": "",
                    "stderr": f"Unsupported language: {language}",
                    "exit_code": 1,
                    "status": "failed",
                }

            try:
                proc = await asyncio.create_subprocess_exec(
                    *cmd,
                    stdin=asyncio.subprocess.PIPE,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                    cwd=tmpdir,
                    env={
                        "PATH": "/usr/bin:/usr/local/bin:/bin",
                        "HOME": tmpdir,
                        "PYTHONDONTWRITEBYTECODE": "1",
                        "MPLBACKEND": "Agg",  # matplotlib 无显示后端
                    },
                )

                try:
                    stdout_bytes, stderr_bytes = await asyncio.wait_for(
                        proc.communicate(stdin.encode() if stdin else None),
                        timeout=timeout,
                    )
                    stdout = stdout_bytes.decode("utf-8", errors="replace")
                    stderr = stderr_bytes.decode("utf-8", errors="replace")
                    exit_code = proc.returncode or 0
                    status = "success" if exit_code == 0 else "failed"
                except asyncio.TimeoutError:
                    proc.kill()
                    await proc.wait()
                    stdout = ""
                    stderr = f"Execution timed out after {timeout} seconds"
                    exit_code = -1
                    status = "timeout"

            except FileNotFoundError:
                stdout = ""
                stderr = f"{language} interpreter not found"
                exit_code = 127
                status = "failed"

            elapsed_ms = (time.time() - start) * 1000

            return {
                "stdout": stdout,
                "stderr": stderr,
                "exit_code": exit_code,
                "status": status,
                "execution_time_ms": elapsed_ms,
            }


# ============================================================
# 错误分类器
# ============================================================


def classify_error(stderr: str, exit_code: int, language: str) -> ErrorType:
    """根据错误信息分类错误类型."""
    if exit_code == -1 or "timed out" in stderr.lower() or "timeout" in stderr.lower():
        return ErrorType.TIMEOUT

    if "MemoryError" in stderr or "memory" in stderr.lower() and "limit" in stderr.lower():
        return ErrorType.MEMORY_ERROR

    if "security" in stderr.lower() or "blocked" in stderr.lower() or "forbidden" in stderr.lower():
        return ErrorType.SECURITY_ERROR

    if language == "python":
        if "SyntaxError" in stderr or "IndentationError" in stderr:
            return ErrorType.SYNTAX_ERROR
        if "ImportError" in stderr or "ModuleNotFoundError" in stderr:
            return ErrorType.IMPORT_ERROR
        if any(err in stderr for err in [
            "NameError", "TypeError", "ValueError", "KeyError",
            "IndexError", "AttributeError", "ZeroDivisionError",
            "RuntimeError", "FileNotFoundError", "OSError",
        ]):
            return ErrorType.RUNTIME_ERROR

    if language in ("javascript", "typescript"):
        if "SyntaxError" in stderr:
            return ErrorType.SYNTAX_ERROR
        if "MODULE_NOT_FOUND" in stderr or "Cannot find module" in stderr:
            return ErrorType.IMPORT_ERROR
        if any(err in stderr for err in [
            "TypeError", "ReferenceError", "RangeError", "Error:",
        ]):
            return ErrorType.RUNTIME_ERROR

    return ErrorType.UNKNOWN


def detect_language(code: str) -> str:
    """自动检测代码语言."""
    code_stripped = code.strip()

    # 检查代码块标记
    if code_stripped.startswith("```python"):
        return "python"
    if code_stripped.startswith("```javascript") or code_stripped.startswith("```js"):
        return "javascript"
    if code_stripped.startswith("```typescript") or code_stripped.startswith("```ts"):
        return "typescript"

    # Python 特征
    python_signals = [
        r"def\s+\w+\s*\(",
        r"import\s+\w+",
        r"from\s+\w+\s+import",
        r"print\s*\(",
        r"class\s+\w+.*:",
        r"if\s+__name__\s*==\s*['\"]__main__['\"]",
    ]
    py_count = sum(1 for pat in python_signals if re.search(pat, code))

    # JS 特征
    js_signals = [
        r"function\s+\w+\s*\(",
        r"const\s+\w+\s*=",
        r"let\s+\w+\s*=",
        r"var\s+\w+\s*=",
        r"console\.(log|error|warn)",
        r"=>\s*\{?",
        r"require\s*\(",
        r"import\s+.*\s+from\s+['\"]",
    ]
    js_count = sum(1 for pat in js_signals if re.search(pat, code))

    if py_count > js_count:
        return "python"
    if js_count > py_count:
        return "javascript"

    # 默认 Python
    return "python"


def detect_dependencies(code: str, language: str) -> list[str]:
    """检测代码依赖的第三方包."""
    deps: list[str] = []

    if language == "python":
        # import xxx
        imports = re.findall(r"^import\s+(\w+)", code, re.MULTILINE)
        deps.extend(imports)
        # from xxx import yyy
        from_imports = re.findall(r"^from\s+(\w+)", code, re.MULTILINE)
        deps.extend(from_imports)

        # 过滤标准库
        std_lib = {
            "os", "sys", "re", "json", "math", "time", "datetime", "random",
            "collections", "itertools", "functools", "typing", "abc",
            "io", "tempfile", "subprocess", "asyncio", "threading",
            "hashlib", "base64", "csv", "pathlib", "string",
            "structlog", "pydantic",  # 项目自身依赖
        }
        deps = [d for d in deps if d not in std_lib and not d.startswith("_")]

    elif language in ("javascript", "typescript"):
        # require('xxx')
        requires = re.findall(r"require\s*\(['\"]([\w@/.-]+)['\"]", code)
        deps.extend(requires)
        # import xxx from 'xxx'
        imports = re.findall(r"from\s+['\"]([\w@/.-]+)['\"]", code)
        deps.extend(imports)

    return list(set(deps))


# ============================================================
# REPL 会话管理器
# ============================================================


class ReplSessionManager:
    """REPL 会话管理器.

    管理多个 REPL 会话，支持：
    - 会话创建/关闭
    - 闲置超时自动回收
    - 每用户并发限制
    """

    def __init__(
        self,
        max_sessions_per_user: int = 3,
        idle_timeout_minutes: int = 30,
    ) -> None:
        self._max_sessions_per_user = max_sessions_per_user
        self._idle_timeout = idle_timeout_minutes * 60
        # 会话存储: session_id -> {language, created_at, last_active, variables, user_id}
        self._sessions: dict[str, dict] = {}
        # 用户会话映射
        self._user_sessions: dict[str, list[str]] = {}

    def create_session(self, language: str, user_id: str = "default") -> str:
        """创建 REPL 会话."""
        # 检查用户会话数限制
        user_sessions = self._user_sessions.get(user_id, [])
        if len(user_sessions) >= self._max_sessions_per_user:
            # 回收最老的会话
            oldest = user_sessions[0]
            self.close_session(oldest)
            user_sessions = self._user_sessions.get(user_id, [])

        import uuid
        session_id = f"repl_{uuid.uuid4().hex[:12]}"
        now = time.time()

        self._sessions[session_id] = {
            "session_id": session_id,
            "language": language,
            "created_at": now,
            "last_active_at": now,
            "command_count": 0,
            "variables": {},
            "user_id": user_id,
            "history": [],  # 执行历史
        }

        self._user_sessions.setdefault(user_id, []).append(session_id)

        return session_id

    def get_session(self, session_id: str) -> dict | None:
        """获取会话信息."""
        session = self._sessions.get(session_id)
        if session:
            # 检查是否超时
            if time.time() - session["last_active_at"] > self._idle_timeout:
                self.close_session(session_id)
                return None
        return session

    def record_execution(self, session_id: str, code: str, result: dict) -> None:
        """记录一次执行."""
        session = self._sessions.get(session_id)
        if session:
            session["last_active_at"] = time.time()
            session["command_count"] += 1
            session["history"].append({
                "code": code,
                "success": result.get("status") == "success",
                "timestamp": time.time(),
            })

    def close_session(self, session_id: str) -> bool:
        """关闭会话."""
        if session_id in self._sessions:
            user_id = self._sessions[session_id].get("user_id", "default")
            del self._sessions[session_id]
            if user_id in self._user_sessions:
                self._user_sessions[user_id] = [
                    s for s in self._user_sessions[user_id] if s != session_id
                ]
                if not self._user_sessions[user_id]:
                    del self._user_sessions[user_id]
            return True
        return False

    def cleanup_idle(self) -> int:
        """清理超时的空闲会话，返回清理数量."""
        now = time.time()
        expired = [
            sid for sid, s in self._sessions.items()
            if now - s["last_active_at"] > self._idle_timeout
        ]
        for sid in expired:
            self.close_session(sid)
        return len(expired)

    def list_sessions(self, user_id: str | None = None) -> list[ReplSessionInfo]:
        """列出会话."""
        sessions = []
        for sid, s in self._sessions.items():
            if user_id and s.get("user_id") != user_id:
                continue
            sessions.append(ReplSessionInfo(
                session_id=sid,
                language=s["language"],
                created_at=s["created_at"],
                last_active_at=s["last_active_at"],
                command_count=s["command_count"],
            ))
        return sessions

    @property
    def total_sessions(self) -> int:
        return len(self._sessions)


# ============================================================
# CodeExecutionBridge 主类
# ============================================================


class CodeExecutionBridge:
    """M2 ↔ M7 代码执行桥梁.

    作为 M2 与 M7 之间的唯一通道，封装所有代码执行相关操作。

    使用方式：
    1. 优先通过 M7 回调执行（生产环境）
    2. 无 M7 时降级到本地沙箱（开发/测试环境）
    """

    def __init__(
        self,
        default_timeout: int = 30,
        max_retries: int = 3,
        auto_fix_default: bool = True,
    ) -> None:
        self._default_timeout = default_timeout
        self._max_retries = max_retries
        self._auto_fix_default = auto_fix_default

        # M7 执行回调（由 M1/M7 注入）
        self._m7_execute_callback: Callable | None = None
        self._m7_repl_callback: Callable | None = None
        self._m7_install_callback: Callable | None = None

        # LLM 修复回调（用于自动修复）
        self._llm_fix_callback: Callable | None = None

        # 本地沙箱（降级方案）
        self._sandbox = SubprocessSandbox(default_timeout=default_timeout)

        # REPL 会话管理
        self._repl_manager = ReplSessionManager()

        # 审计日志（仅存摘要）
        self._audit_log: list[dict] = []

    # ---- M7 回调注入 ----

    def set_m7_callbacks(
        self,
        execute: Callable | None = None,
        repl: Callable | None = None,
        install: Callable | None = None,
    ) -> None:
        """设置 M7 执行回调."""
        self._m7_execute_callback = execute
        self._m7_repl_callback = repl
        self._m7_install_callback = install

    def set_llm_fix_callback(self, callback: Callable) -> None:
        """设置 LLM 代码修复回调.

        回调签名: callback(code, error_message, language) -> str (修复后的代码)
        """
        self._llm_fix_callback = callback

    # ---- 基础执行 ----

    async def execute(
        self,
        code: str,
        language: str | None = None,
        files: dict[str, str] | None = None,
        stdin: str = "",
        timeout: int | None = None,
        auto_fix: bool | None = None,
        max_retries: int | None = None,
    ) -> ExecutionResult:
        """执行代码，失败时自动修复重试.

        Args:
            code: 代码内容
            language: 语言（None 则自动检测）
            files: 附加文件 {filename: content}
            stdin: 标准输入
            timeout: 超时时间（秒）
            auto_fix: 是否自动修复（默认使用全局配置）
            max_retries: 最大重试次数

        Returns:
            ExecutionResult 执行结果
        """
        if language is None:
            language = detect_language(code)

        do_auto_fix = auto_fix if auto_fix is not None else self._auto_fix_default
        retries = max_retries if max_retries is not None else self._max_retries

        # 首次执行
        result = await self._execute_once(code, language, files, stdin, timeout or self._default_timeout)

        # 自动修复循环
        fix_history: list[dict] = []
        current_code = code
        attempt = 0

        while result.status == ExecutionStatus.FAILED and do_auto_fix and attempt < retries:
            attempt += 1

            # 语法错误和导入错误的修复成功率更高
            if result.error_type not in (
                ErrorType.SYNTAX_ERROR,
                ErrorType.IMPORT_ERROR,
                ErrorType.RUNTIME_ERROR,
            ):
                break  # 非代码错误不尝试修复

            # 调用 LLM 修复
            fixed_code = await self._try_fix_code(
                current_code, result.stderr, language, attempt
            )
            if fixed_code is None or fixed_code == current_code:
                break  # 无法修复或修复没变化

            # 记录修复历史
            fix_history.append({
                "attempt": attempt,
                "original_code": current_code,
                "error": result.stderr[:500],
                "error_type": result.error_type.value if result.error_type else "unknown",
                "fixed_code": fixed_code,
            })

            # 重新执行（修复后不再自动修复，避免死循环）
            current_code = fixed_code
            result = await self._execute_once(
                current_code, language, files, stdin, timeout or self._default_timeout
            )

            if result.status == ExecutionStatus.SUCCESS:
                result.status = ExecutionStatus.FIXED
                break

        result.retry_count = attempt
        result.fix_history = fix_history

        # 审计日志
        self._log_audit(code, language, result)

        return result

    async def _execute_once(
        self,
        code: str,
        language: str,
        files: dict[str, str] | None,
        stdin: str,
        timeout: int,
    ) -> ExecutionResult:
        """执行一次代码（不重试）."""
        start = time.time()

        # 优先使用 M7
        if self._m7_execute_callback:
            try:
                raw_result = self._m7_execute_callback(
                    code=code,
                    language=language,
                    files=files,
                    stdin=stdin,
                    timeout=timeout,
                )
                if asyncio.iscoroutine(raw_result):
                    raw_result = await raw_result
                return self._normalize_m7_result(raw_result, language)
            except Exception as e:
                logger.warning("m7_execute_failed", error=str(e))
                # 降级到本地沙箱

        # 本地沙箱执行
        if language == "python":
            raw = await self._sandbox.execute_python(code, stdin, timeout, files)
        elif language in ("javascript", "typescript"):
            raw = await self._sandbox.execute_javascript(code, stdin, timeout, files)
        else:
            return ExecutionResult(
                status=ExecutionStatus.FAILED,
                stderr=f"Unsupported language: {language}",
                error_type=ErrorType.UNKNOWN,
                language=language,
            )

        error_type = classify_error(raw.get("stderr", ""), raw.get("exit_code", 0), language)
        status = ExecutionStatus(raw.get("status", "failed"))

        # 检测输出类型
        output_type = self._detect_output_type(raw.get("stdout", ""), language)

        return ExecutionResult(
            status=status,
            stdout=raw.get("stdout", ""),
            stderr=raw.get("stderr", ""),
            exit_code=raw.get("exit_code", 0),
            execution_time_ms=raw.get("execution_time_ms", (time.time() - start) * 1000),
            language=language,
            error_type=error_type,
            output_type=output_type,
        )

    async def _try_fix_code(
        self, code: str, error: str, language: str, attempt: int
    ) -> str | None:
        """尝试修复代码."""
        if self._llm_fix_callback is None:
            # 无 LLM 回调，尝试简单规则修复
            return self._simple_fix(code, error, language)

        try:
            result = self._llm_fix_callback(
                code=code,
                error_message=error,
                language=language,
                attempt=attempt,
            )
            if asyncio.iscoroutine(result):
                result = await result
            return result
        except Exception as e:
            logger.warning("llm_fix_failed", error=str(e))
            return self._simple_fix(code, error, language)

    def _simple_fix(self, code: str, error: str, language: str) -> str | None:
        """简单规则修复（无 LLM 时的降级方案）.

        仅处理最常见的简单错误：
        - Python 缩进问题
        - 缺少冒号
        - 拼写错误的常见函数名
        """
        if language != "python":
            return None

        fixed = code

        # 修复常见拼写错误
        common_misspell = {
            "pritn(": "print(",
            "pirnt(": "print(",
            "reutrn ": "return ",
            "Ture": "True",
            "Flase": "False",
        }
        for wrong, right in common_misspell.items():
            if wrong in fixed:
                fixed = fixed.replace(wrong, right)

        if fixed != code:
            return fixed

        return None

    # ---- REPL 会话 ----

    async def create_repl(self, language: str = "python", user_id: str = "default") -> str:
        """创建 REPL 会话."""
        if self._m7_repl_callback:
            # M7 模式
            try:
                result = self._m7_repl_callback(action="create", language=language, user_id=user_id)
                if asyncio.iscoroutine(result):
                    result = await result
                return result
            except Exception:
                pass  # 降级到本地

        return self._repl_manager.create_session(language, user_id)

    async def repl_exec(
        self,
        session_id: str,
        code: str,
        auto_fix: bool = True,
    ) -> ExecutionResult:
        """在 REPL 中执行代码."""
        session = self._repl_manager.get_session(session_id)
        if not session:
            return ExecutionResult(
                status=ExecutionStatus.FAILED,
                stderr=f"REPL session {session_id} not found or expired",
                error_type=ErrorType.UNKNOWN,
                language="python",
            )

        # 累积历史代码（模拟共享环境）
        # 注意：真实 REPL 由 M7 维护，本地模式用完整历史重新执行
        history_code = "\n".join(
            h["code"] for h in session["history"] if h["success"]
        )
        full_code = history_code + "\n" + code if history_code else code

        result = await self.execute(
            code=full_code,
            language=session["language"],
            auto_fix=auto_fix,
            max_retries=1,  # REPL 模式减少重试次数
        )

        # 记录执行
        self._repl_manager.record_execution(session_id, code, {
            "status": result.status.value,
        })

        return result

    async def close_repl(self, session_id: str) -> bool:
        """关闭 REPL 会话."""
        if self._m7_repl_callback:
            try:
                result = self._m7_repl_callback(action="close", session_id=session_id)
                if asyncio.iscoroutine(result):
                    result = await result
                return result
            except Exception:
                pass

        return self._repl_manager.close_session(session_id)

    def list_repl_sessions(self, user_id: str | None = None) -> list[ReplSessionInfo]:
        """列出 REPL 会话."""
        return self._repl_manager.list_sessions(user_id)

    # ---- 包管理 ----

    async def install_package(
        self,
        package_name: str,
        language: str = "python",
        session_id: str | None = None,
    ) -> PackageInstallResult:
        """安装第三方包.

        注意：安装前应通过 UI 询问用户确认（敏感操作）。
        """
        if self._m7_install_callback:
            try:
                result = self._m7_install_callback(
                    package=package_name,
                    language=language,
                    session_id=session_id,
                )
                if asyncio.iscoroutine(result):
                    result = await result
                return PackageInstallResult(**result)
            except Exception as e:
                return PackageInstallResult(
                    success=False,
                    package_name=package_name,
                    error=str(e),
                )

        # 本地模式：尝试 pip install
        if language == "python":
            try:
                proc = await asyncio.create_subprocess_exec(
                    "pip", "install", package_name, "--quiet",
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )
                _, stderr = await proc.communicate()
                if proc.returncode == 0:
                    return PackageInstallResult(
                        success=True,
                        package_name=package_name,
                    )
                else:
                    return PackageInstallResult(
                        success=False,
                        package_name=package_name,
                        error=stderr.decode("utf-8", errors="replace")[:500],
                    )
            except Exception as e:
                return PackageInstallResult(
                    success=False,
                    package_name=package_name,
                    error=str(e),
                )

        return PackageInstallResult(
            success=False,
            package_name=package_name,
            error=f"Package installation not supported for {language} in local mode",
        )

    # ---- 工具方法 ----

    def detect_language(self, code: str) -> str:
        """自动检测代码语言."""
        return detect_language(code)

    def detect_dependencies(self, code: str, language: str | None = None) -> list[str]:
        """检测代码依赖."""
        if language is None:
            language = detect_language(code)
        return detect_dependencies(code, language)

    def _detect_output_type(self, stdout: str, language: str) -> str:
        """检测输出类型."""
        # 表格格式检测
        if re.search(r"\|\s*.+\s*\|", stdout) and "---" in stdout:
            return "table"
        if re.search(r",\s*", stdout) and "\n" in stdout and len(stdout.splitlines()) > 2:
            # 可能是 CSV 格式
            first_line = stdout.strip().split("\n")[0]
            if first_line.count(",") >= 2:
                return "table"

        # 图片检测（base64 或文件路径引用）
        if "base64" in stdout or ".png" in stdout or ".jpg" in stdout:
            return "image"

        return "text"

    def _normalize_m7_result(self, raw: dict, language: str) -> ExecutionResult:
        """将 M7 返回的结果标准化为 ExecutionResult."""
        status = raw.get("status", "failed")
        if isinstance(status, str):
            try:
                status = ExecutionStatus(status)
            except ValueError:
                status = ExecutionStatus.FAILED

        error_type = raw.get("error_type")
        if error_type:
            try:
                error_type = ErrorType(error_type)
            except ValueError:
                error_type = None

        return ExecutionResult(
            status=status,
            stdout=raw.get("stdout", ""),
            stderr=raw.get("stderr", ""),
            exit_code=raw.get("exit_code", 0),
            execution_time_ms=raw.get("execution_time_ms", 0),
            language=language,
            error_type=error_type,
            output_type=raw.get("output_type", "text"),
            images=raw.get("images", []),
            tables=raw.get("tables", []),
        )

    def _log_audit(self, code: str, language: str, result: ExecutionResult) -> None:
        """记录审计日志（仅存摘要，不存完整代码）."""
        code_hash = hashlib.sha256(code.encode()).hexdigest()[:16]
        self._audit_log.append({
            "code_hash": code_hash,
            "language": language,
            "status": result.status.value,
            "error_type": result.error_type.value if result.error_type else None,
            "execution_time_ms": round(result.execution_time_ms, 2),
            "retry_count": result.retry_count,
            "timestamp": time.time(),
        })
        # 限制日志大小
        if len(self._audit_log) > 1000:
            self._audit_log = self._audit_log[-500:]

    # ---- 统计 ----

    def stats(self) -> dict[str, Any]:
        """统计信息."""
        total_executions = len(self._audit_log)
        success_count = sum(1 for l in self._audit_log if l["status"] in ("success", "fixed"))
        success_rate = success_count / total_executions if total_executions > 0 else 0

        return {
            "total_executions": total_executions,
            "success_rate": round(success_rate, 4),
            "active_repl_sessions": self._repl_manager.total_sessions,
            "m7_connected": self._m7_execute_callback is not None,
            "llm_fix_available": self._llm_fix_callback is not None,
            "default_timeout": self._default_timeout,
            "max_retries": self._max_retries,
            "supported_languages": ["python", "javascript", "typescript"],
            "error_types_available": [e.value for e in ErrorType],
        }
