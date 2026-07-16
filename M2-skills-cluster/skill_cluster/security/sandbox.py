"""Skill Sandbox 安全执行沙箱.

为代码执行类技能提供进程级隔离环境，支持资源限制（超时/内存/CPU）、
模块白名单/黑名单、以及文件系统访问控制。

【模型迁移说明】
Pydantic 模型 ``SandboxConfig`` 已迁移至 ``skill_cluster.models.security``，
本文件保留 import 别名以保持向后兼容。
"""

from __future__ import annotations

import ast
import json
import os
import resource
import subprocess
import sys
import tempfile
import time
from typing import Any

import structlog

from skill_cluster.interfaces import SkillInvokeRequest, SkillInvokeResult

# ---- 从 models.security 导入 Pydantic 模型（向后兼容） ----
from skill_cluster.models.security import SandboxConfig

logger = structlog.get_logger()


class SandboxPolicy:
    """安全策略检查器.

    【第二轮优化】统一静态检查与运行时白名单逻辑：
    - 默认安全白名单（DEFAULT_SAFE_MODULES），与运行时 _safe_import 保持一致
    - allowed_modules 非空时严格白名单模式（仅允许列表内模块）
    - allowed_modules 为空时使用默认安全白名单
    - blocked_modules 仍保留作为额外黑名单层（在白名单基础上叠加禁止）
    - 新增 getattr/__builtins__ 动态属性访问防护
    """

    DEFAULT_SAFE_MODULES: frozenset[str] = frozenset({
        "math", "json", "re", "datetime", "collections", "itertools",
        "functools", "statistics", "random", "string", "typing", "enum",
        "dataclasses", "copy", "decimal", "fractions", "hashlib", "uuid",
        "time", "calendar", "html", "xml", "csv", "bisect", "heapq",
        "array", "pprint", "textwrap", "difflib", "traceback", "types", "abc",
    })

    def __init__(self, config: SandboxConfig) -> None:
        self._config = config
        # 构建有效白名单：与运行时 _safe_import 一致
        if config.allowed_modules:
            self._effective_whitelist = frozenset(config.allowed_modules)
        else:
            self._effective_whitelist = self.DEFAULT_SAFE_MODULES

    def check_code(self, code: str) -> tuple[bool, str | None]:
        """静态检查代码安全性（AST 级深度扫描）.
        
        检测项：
        1. 危险导入（白名单优先 + 黑名单叠加）
        2. 危险函数调用：eval/exec/compile/__import__/globals/locals/vars/dir
        3. 危险属性访问：双下划线属性、func_/im_/gi_/cr_ 内部属性
        4. 危险函数：getattr/setattr/delattr/hasattr（配合 dunder 检查）
        5. 动态代码执行相关：breakpoint/help
        6. 文件系统操作：open/file/write/remove/rmdir等
        7. 网络/系统：socket/subprocess/os.system 等属性形式
        8. pickle/yaml/marshal 反序列化危险
        9. 内存/反射：ctypes/memoryview 等

        Returns:
            (是否通过, 错误信息).
        """
        try:
            tree = ast.parse(code)
        except SyntaxError as e:
            return False, f"Syntax error: {e}"

        # 危险内置函数名（Call.Name 形式）
        _dangerous_builtins = {
            "__import__", "eval", "exec", "compile",
            "globals", "locals", "vars", "dir",
            "breakpoint", "help", "memoryview",
            "open", "input",
            "getattr", "setattr", "delattr", "hasattr",
        }

        # 危险属性名（Attribute.attr 形式）
        _dangerous_attrs = {
            # 双下划线属性
            "__import__", "__builtins__", "__globals__", "__locals__",
            "__code__", "__func__", "__class__", "__bases__",
            "__mro__", "__subclasses__", "__init__", "__new__",
            "__dict__", "__getattr__", "__setattr__",
            "__reduce__", "__reduce_ex__",  # pickle 利用
            # 内部属性前缀
            "func_code", "func_globals", "func_closure",
            "im_func", "im_class", "im_self",
            "gi_frame", "gi_code",
            "cr_frame", "cr_code",
            # 系统调用
            "system", "popen", "execve", "spawn",
            # 文件删除
            "remove", "unlink", "rmdir", "rmtree", "unlinkat",
            # 网络
            "socket", "connect", "bind", "listen",
            # 子进程
            "Popen", "call", "run",
        }

        # 危险模块（即使通过属性形式访问也要拦截）
        _dangerous_module_attrs = {
            "subprocess", "os", "sys", "socket", "ctypes",
            "pickle", "marshal", "shelve",
        }

        for node in ast.walk(tree):
            # 1. 检查危险导入（白名单优先）
            if isinstance(node, ast.Import):
                for alias in node.names:
                    mod = alias.name.split(".")[0]
                    if not self._is_module_allowed(mod):
                        return False, f"Import of module '{mod}' is not allowed"
            elif isinstance(node, ast.ImportFrom):
                mod = (node.module or "").split(".")[0]
                if not self._is_module_allowed(mod):
                    return False, f"Import from module '{mod}' is not allowed"

            # 2. 检查危险函数调用（Name 形式）
            if isinstance(node, ast.Call):
                if isinstance(node.func, ast.Name):
                    fname = node.func.id
                    if fname in _dangerous_builtins:
                        # 对 getattr/setattr/delattr/hasattr 额外检查 dunder 参数
                        if fname in ("getattr", "setattr", "delattr", "hasattr"):
                            if len(node.args) >= 2:
                                second_arg = node.args[1]
                                if (
                                    isinstance(second_arg, ast.Constant)
                                    and isinstance(second_arg.value, str)
                                    and (
                                        second_arg.value.startswith("__")
                                        or second_arg.value.startswith("func_")
                                        or second_arg.value.startswith("im_")
                                        or second_arg.value.startswith("gi_")
                                        or second_arg.value.startswith("cr_")
                                    )
                                ):
                                    return False, (
                                        f"{fname} access to internal attribute "
                                        f"'{second_arg.value}' is not allowed"
                                    )
                        else:
                            return False, f"Call to '{fname}' is not allowed"

                # 3. 检查属性形式的危险调用（如 os.system、subprocess.Popen）
                if isinstance(node.func, ast.Attribute):
                    attr_name = node.func.attr
                    if attr_name in _dangerous_attrs:
                        return False, f"Call to '{attr_name}' is not allowed"
                    
                    # 检查是否是危险模块的属性调用（如 os.system("cmd")）
                    if isinstance(node.func.value, ast.Name):
                        if node.func.value.id in _dangerous_module_attrs:
                            return False, (
                                f"Call to '{node.func.value.id}.{attr_name}' "
                                f"is not allowed"
                            )

            # 4. 检查危险属性访问（即使不调用，访问 __builtins__ 也可能危险）
            if isinstance(node, ast.Attribute):
                attr_name = node.attr
                # 双下划线属性访问
                if attr_name.startswith("__") and attr_name.endswith("__"):
                    # 放过一些常见安全的（如 __name__, __doc__）
                    if attr_name not in ("__name__", "__doc__", "__file__"):
                        return False, f"Access to dunder attribute '{attr_name}' is not allowed"
                # 内部属性前缀
                if any(attr_name.startswith(p) for p in ("func_", "im_", "gi_", "cr_", "f_")):
                    return False, f"Access to internal attribute '{attr_name}' is not allowed"

            # 5. 检查文件操作（即使通过别名模块访问）
            if not self._config.allow_file_write:
                if isinstance(node, ast.Call):
                    if isinstance(node.func, ast.Attribute):
                        if node.func.attr in ("remove", "unlink", "rmdir", "rmtree", "unlinkat"):
                            return False, f"File deletion '{node.func.attr}' is not allowed"
                        if node.func.attr in ("write", "writelines"):
                            return False, f"File write '{node.func.attr}' is not allowed"

            # 6. 检查赋值给危险变量（如 __builtins__ = ...）
            if isinstance(node, ast.Assign):
                for target in node.targets:
                    if isinstance(target, ast.Name):
                        if target.id.startswith("__") and target.id.endswith("__"):
                            return False, f"Assignment to dunder '{target.id}' is not allowed"
                    if isinstance(target, ast.Attribute):
                        if target.attr.startswith("__") and target.attr.endswith("__"):
                            return False, f"Assignment to dunder '{target.attr}' is not allowed"

        return True, None

    def _is_module_allowed(self, module: str) -> bool:
        """白名单优先检查，blocked_modules 作为额外黑名单层."""
        # 额外黑名单层：即使在白名单中也禁止
        if module in self._config.blocked_modules:
            return False
        # 白名单检查
        return module in self._effective_whitelist


class SandboxExecutor:
    """沙箱执行器.

    在隔离的子进程中执行 Python 代码，并施加资源限制。
    """

    def __init__(self, config: SandboxConfig | None = None) -> None:
        self._config = config or SandboxConfig()
        self._policy = SandboxPolicy(self._config)

    def execute(self, code: str, input_data: dict[str, Any] | None = None) -> SkillInvokeResult:
        """在沙箱中执行代码.

        Args:
            code: Python 代码字符串.
            input_data: 注入到沙箱的输入变量（通过 JSON 序列化）.

        Returns:
            SkillInvokeResult.
        """
        start = time.perf_counter()

        # 静态安全检查
        passed, error = self._policy.check_code(code)
        if not passed:
            latency = (time.perf_counter() - start) * 1000
            return SkillInvokeResult(
                skill_id="skill.sandbox",
                action="execute",
                status="failure",
                error=f"Security check failed: {error}",
                latency_ms=latency,
                trace_id="",
            )

        # 构建沙箱执行脚本
        script = self._build_sandbox_script(code, input_data or {})

        # 创建临时文件运行
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".py", delete=False
        ) as f:
            f.write(script)
            script_path = f.name

        try:
            result = self._run_in_subprocess(script_path)
        finally:
            os.unlink(script_path)

        latency = (time.perf_counter() - start) * 1000

        if result["exit_code"] != 0:
            return SkillInvokeResult(
                skill_id="skill.sandbox",
                action="execute",
                status="failure",
                error=result.get("stderr", "Unknown error"),
                data={"stdout": result.get("stdout", "")},
                latency_ms=latency,
                trace_id="",
            )

        return SkillInvokeResult(
            skill_id="skill.sandbox",
            action="execute",
            status="success",
            data={
                "stdout": result.get("stdout", ""),
                "output": result.get("output"),
            },
            latency_ms=latency,
            trace_id="",
        )

    def _build_sandbox_script(
        self, code: str, input_data: dict[str, Any]
    ) -> str:
        """构建在子进程中运行的沙箱脚本."""
        import json as _json

        input_json = _json.dumps(input_data, ensure_ascii=False)

        # 预计算白名单模块列表
        if self._config.allowed_modules:
            allowed_str = repr(sorted(self._config.allowed_modules))[1:-1]
        else:
            allowed_str = ""

        script = f'''
import json
import os
import resource
import sys

# 资源限制（在代码执行前设置）
try:
    _max_mem_mb = int(os.environ.get("SANDBOX_MAX_MEMORY_MB", "256"))
    resource.setrlimit(
        resource.RLIMIT_AS,
        (_max_mem_mb * 1024 * 1024, _max_mem_mb * 1024 * 1024)
    )
    _max_cpu_sec = int(os.environ.get("SANDBOX_MAX_CPU_SECONDS", "10"))
    resource.setrlimit(
        resource.RLIMIT_CPU,
        (_max_cpu_sec, _max_cpu_sec)
    )
except Exception:
    pass

# 注入输入数据
__sandbox_input = json.loads({repr(input_json)})

# 构建受限 builtins —— 安全校验修复：使用白名单替代黑名单
# 白名单模块
_config_allowed = "{allowed_str}"
if _config_allowed:
    _allowed_modules = set(_config_allowed.split(", "))
else:
    _allowed_modules = {{"math", "json", "re", "datetime", "collections", "itertools", "functools", "statistics", "random", "string", "typing", "enum", "dataclasses", "copy", "decimal", "fractions", "hashlib", "uuid", "time", "calendar", "html", "xml", "csv", "bisect", "heapq", "array", "pprint", "textwrap", "difflib", "traceback", "types", "abc"}}

_original_import = __import__

def _safe_import(name, globals=None, locals=None, fromlist=(), level=0):
    """安全的 import 函数：仅允许白名单模块."""
    top_level = name.split(".")[0]
    if top_level not in _allowed_modules:
        raise ImportError(f"Sandbox: import of '{{name}}' is not allowed (not in whitelist)")
    return _original_import(name, globals, locals, fromlist, level)

_restricted = {{}}
for _name in dir(__builtins__):
    if not _name.startswith("__"):
        _restricted[_name] = getattr(__builtins__, _name)
# 移除危险内置函数
for _dangerous in ["open", "eval", "compile", "exec", "breakpoint", "exit", "quit"]:
    _restricted.pop(_dangerous, None)
# 注入安全的 import
_restricted["__import__"] = _safe_import
_restricted["__name__"] = "__sandbox__"
# 移除 __builtins__ 本身以防止 __builtins__.__import__ 绕过
# 设置 __builtins__ 为受限字典

# 执行用户代码
_locals = {{"input_data": __sandbox_input}}
try:
    exec({repr(code)}, {{"__builtins__": _restricted, "__builtins__": _restricted}}, _locals)
except Exception as e:
    print(f"ERROR: {{e}}", file=sys.stderr)
    sys.exit(1)

# 输出结果
output = _locals.get("output", None)
print("__SANDBOX_OUTPUT__")
print(json.dumps(output, ensure_ascii=False))
'''
        return script

    def _run_in_subprocess(self, script_path: str) -> dict[str, Any]:
        """在子进程中运行脚本并施加资源限制."""
        cmd = [sys.executable, script_path]
        env = os.environ.copy()
        # 禁用网络（通过环境变量提示，实际隔离依赖运行环境）
        if not self._config.allow_network:
            env["SANDBOX_NO_NETWORK"] = "1"
        # 传递资源限制到子进程
        env["SANDBOX_MAX_MEMORY_MB"] = str(self._config.max_memory_mb)
        env["SANDBOX_MAX_CPU_SECONDS"] = str(self._config.max_cpu_time_seconds)

        try:
            proc = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=self._config.timeout_seconds,
                env=env,
                cwd=self._config.working_dir,
            )
        except subprocess.TimeoutExpired:
            return {
                "exit_code": -1,
                "stderr": f"Execution timed out after {self._config.timeout_seconds}s",
                "stdout": "",
            }

        stdout = proc.stdout
        stderr = proc.stderr
        output = None

        # 解析 __SANDBOX_OUTPUT__ 行后的 JSON
        if "__SANDBOX_OUTPUT__\n" in stdout:
            parts = stdout.split("__SANDBOX_OUTPUT__\n", 1)
            stdout = parts[0]
            try:
                output = json.loads(parts[1].strip())
            except Exception:
                output = parts[1].strip()

        return {
            "exit_code": proc.returncode,
            "stdout": stdout,
            "stderr": stderr,
            "output": output,
        }


class SandboxMiddleware:
    """沙箱中间件.

    作为中间件集成到 MiddlewarePipeline，自动对标记为
    `sandbox_required` 的技能启用沙箱执行。
    """

    def __init__(self, config: SandboxConfig | None = None) -> None:
        self._config = config or SandboxConfig()
        self._executor = SandboxExecutor(self._config)

    async def __call__(
        self,
        request: SkillInvokeRequest,
        agent_id: str,
        next_handler: Any,
    ) -> SkillInvokeResult:
        """中间件入口."""
        params = request.params or {}
        code = params.get("code")

        if not code or not isinstance(code, str):
            return await next_handler()

        return self._executor.execute(code, params.get("input_data"))


def create_sandbox_middleware(
    config: SandboxConfig | None = None,
) -> SandboxMiddleware:
    """创建沙箱中间件实例."""
    return SandboxMiddleware(config)
