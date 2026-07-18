"""M11 MCP Bus - 安全层 - Sandbox 安全沙箱.

提供 MCP 工具执行的安全隔离机制，支持 4 个安全级别：
- Level 0 - 无限制：开发环境默认，所有工具直接执行
- Level 1 - 基础隔离：参数校验 + 危险函数检测 + 速率限制
- Level 2 - 严格隔离：子进程执行 + 资源限制 + 超时 + 文件系统隔离
- Level 3 - 最大安全：Docker 容器执行（预留接口）

核心类：
- SandboxedExecutor: 沙箱执行器，封装单次工具调用的安全检查
- SandboxManager: 沙箱管理器，全局单例，管理配置和统计

安全管道：
    参数校验 → 危险检测 → 速率检查 → 资源限制 → 实际执行 → 审计日志
"""

from __future__ import annotations

import json
import os
import re
import time
from collections import defaultdict
from dataclasses import dataclass, field
from threading import Lock, RLock
from typing import Any, Callable, Dict, List, Optional, Set, Tuple

import structlog

logger = structlog.get_logger(__name__)


# ============================================================
# 常量定义
# ============================================================

# 沙箱安全级别
SANDBOX_LEVEL_UNLIMITED = 0      # 无限制（开发环境）
SANDBOX_LEVEL_BASIC = 1          # 基础隔离（默认）
SANDBOX_LEVEL_STRICT = 2         # 严格隔离
SANDBOX_LEVEL_MAXIMUM = 3        # 最大安全（Docker）

# 默认配置
DEFAULT_SANDBOX_LEVEL = SANDBOX_LEVEL_BASIC
DEFAULT_TIMEOUT = 30             # 秒
DEFAULT_MAX_OUTPUT_SIZE = 1024 * 1024  # 1MB
DEFAULT_MAX_STRING_LENGTH = 10000
DEFAULT_MAX_LIST_LENGTH = 1000
DEFAULT_MAX_DICT_KEYS = 1000
DEFAULT_MAX_NESTING_DEPTH = 10
DEFAULT_RATE_LIMIT_PER_TOOL = 100  # 每分钟
DEFAULT_RATE_LIMIT_PER_KEY = 1000  # 每分钟
DEFAULT_MAX_CONCURRENT = 10

# 危险函数/模式黑名单（Python 代码中检测）
DANGEROUS_FUNCTIONS: List[str] = [
    "eval", "exec", "compile",
    "os.system", "os.popen", "os.execl", "os.execle", "os.execlp",
    "os.execlpe", "os.execv", "os.execve", "os.execvp", "os.execvpe",
    "subprocess.call", "subprocess.run", "subprocess.Popen",
    "subprocess.getoutput", "subprocess.getstatusoutput",
    "__import__", "importlib.import_module",
    "pickle.loads", "pickle.load",
    "marshal.loads", "marshal.load",
    "ctypes", "ctypes.CDLL", "ctypes.WinDLL",
    "globals", "locals", "vars",
    "getattr", "setattr", "delattr",
    "open", "file",  # 文件操作
    "input", "raw_input",  # 标准输入
    "exit", "quit", "os._exit",
    "memoryview", "bytearray",
]

# 敏感路径模式（文件系统隔离）
SENSITIVE_PATH_PATTERNS: List[str] = [
    r"^/etc/",
    r"^/etc$",
    r"^/root/",
    r"^/root$",
    r"^/proc/",
    r"^/proc$",
    r"^/sys/",
    r"^/sys$",
    r"^/dev/",
    r"^/dev$",
    r"^/var/run/",
    r"^/var/log/",
    r"\.ssh/",
    r"\.ssh$",
    r"\.aws/",
    r"\.aws$",
    r"\.env",
    r"\.git/",
    r"\.git$",
    r"^C:\\Windows\\",
    r"^C:\\Program Files\\",
    r"^C:\\Users\\.*\\AppData\\",
    r"\\.ssh\\",
    r"\\.aws\\",
]

# 命令注入敏感字符
COMMAND_INJECTION_PATTERNS: List[str] = [
    r";",           # 命令分隔符
    r"\|",          # 管道
    r"&&",          # 逻辑与
    r"\|\|",        # 逻辑或
    r"`.*?`",       # 反引号命令替换
    r"\$\(.*?\)",   # 命令替换
    r">\s*/",       # 重定向到根路径
    r"<\s*/",       # 输入重定向
    r"\.\./",       # 路径遍历
    r"\.\.\\",      # Windows 路径遍历
    r"\n",          # 换行符
    r"\r",          # 回车符
]

# SSRF 防护 - 内网地址模式
SSRF_BLOCKED_PATTERNS: List[str] = [
    r"^http://localhost",
    r"^http://127\.",
    r"^http://0\.0\.0\.0",
    r"^http://10\.",
    r"^http://172\.(1[6-9]|2[0-9]|3[01])\.",
    r"^http://192\.168\.",
    r"^http://169\.254\.",
    r"^http://\[::1\]",
    r"^http://\[fe80",
    r"^http://metadata",
    r"^http://169\.254\.169\.254",  # AWS/GCP metadata
]


# ============================================================
# 数据类
# ============================================================

@dataclass
class SandboxConfig:
    """沙箱配置."""
    level: int = DEFAULT_SANDBOX_LEVEL
    timeout: int = DEFAULT_TIMEOUT
    max_output_size: int = DEFAULT_MAX_OUTPUT_SIZE
    max_string_length: int = DEFAULT_MAX_STRING_LENGTH
    max_list_length: int = DEFAULT_MAX_LIST_LENGTH
    max_dict_keys: int = DEFAULT_MAX_DICT_KEYS
    max_nesting_depth: int = DEFAULT_MAX_NESTING_DEPTH
    rate_limit_per_tool: int = DEFAULT_RATE_LIMIT_PER_TOOL
    rate_limit_per_key: int = DEFAULT_RATE_LIMIT_PER_KEY
    max_concurrent_executions: int = DEFAULT_MAX_CONCURRENT
    dangerous_functions: List[str] = field(default_factory=lambda: list(DANGEROUS_FUNCTIONS))
    sensitive_path_patterns: List[str] = field(default_factory=lambda: list(SENSITIVE_PATH_PATTERNS))
    command_injection_patterns: List[str] = field(default_factory=lambda: list(COMMAND_INJECTION_PATTERNS))
    ssrf_blocked_patterns: List[str] = field(default_factory=lambda: list(SSRF_BLOCKED_PATTERNS))
    tool_whitelist: List[str] = field(default_factory=list)
    tool_blacklist: List[str] = field(default_factory=list)
    ip_whitelist: List[str] = field(default_factory=list)
    ip_blacklist: List[str] = field(default_factory=list)
    working_directory: str = ""
    security_headers_enabled: bool = True


@dataclass
class SandboxResult:
    """沙箱执行结果."""
    allowed: bool
    reason: str = ""
    blocked_by: str = ""  # 被哪个检查拦截：param_validation / danger_detection / rate_limit / ...
    details: Dict[str, Any] = field(default_factory=dict)

    def __bool__(self) -> bool:
        return self.allowed


@dataclass
class SandboxExecutionContext:
    """沙箱执行上下文."""
    tool_name: str
    arguments: Dict[str, Any]
    caller: str = ""
    api_key_id: Optional[int] = None
    ip_address: str = ""
    start_time: float = 0.0
    duration_ms: int = 0
    blocked: bool = False
    block_reason: str = ""
    result: Any = None
    error: str = ""


# ============================================================
# 参数校验器
# ============================================================

class ParameterValidator:
    """参数校验器.

    提供对工具调用参数的安全校验：
    - 类型校验
    - 长度限制（字符串/列表/字典）
    - 嵌套深度限制
    - 敏感字符过滤
    """

    def __init__(self, config: SandboxConfig) -> None:
        """初始化参数校验器.

        Args:
            config: 沙箱配置
        """
        self._config = config
        # 预编译正则表达式
        self._cmd_injection_regex = [
            re.compile(p, re.IGNORECASE) for p in config.command_injection_patterns
        ]

    def validate(
        self,
        arguments: Dict[str, Any],
        tool_name: str = "",
    ) -> SandboxResult:
        """校验参数字典.

        Args:
            arguments: 工具调用参数字典
            tool_name: 工具名称（用于日志）

        Returns:
            SandboxResult，allowed=True 表示通过校验
        """
        if not isinstance(arguments, dict):
            return SandboxResult(
                allowed=False,
                blocked_by="param_validation",
                reason=f"参数必须是字典类型，实际为 {type(arguments).__name__}",
            )

        # 检查字典键数量
        if len(arguments) > self._config.max_dict_keys:
            return SandboxResult(
                allowed=False,
                blocked_by="param_validation",
                reason=f"参数字典键数量超过限制: {len(arguments)} > {self._config.max_dict_keys}",
            )

        # 递归校验每个值
        for key, value in arguments.items():
            result = self._validate_value(value, key, depth=1)
            if not result.allowed:
                return result

        return SandboxResult(allowed=True)

    def _validate_value(
        self,
        value: Any,
        path: str,
        depth: int,
    ) -> SandboxResult:
        """递归校验单个值.

        Args:
            value: 待校验的值
            path: 值的路径（用于错误信息）
            depth: 当前嵌套深度

        Returns:
            SandboxResult
        """
        # 检查嵌套深度
        if depth > self._config.max_nesting_depth:
            return SandboxResult(
                allowed=False,
                blocked_by="param_validation",
                reason=f"参数嵌套深度超过限制: {depth} > {self._config.max_nesting_depth} (路径: {path})",
            )

        # 字符串校验
        if isinstance(value, str):
            return self._validate_string(value, path)

        # 列表/元组校验
        if isinstance(value, (list, tuple)):
            if len(value) > self._config.max_list_length:
                return SandboxResult(
                    allowed=False,
                    blocked_by="param_validation",
                    reason=f"列表长度超过限制: {len(value)} > {self._config.max_list_length} (路径: {path})",
                )
            for i, item in enumerate(value):
                result = self._validate_value(item, f"{path}[{i}]", depth + 1)
                if not result.allowed:
                    return result
            return SandboxResult(allowed=True)

        # 字典校验
        if isinstance(value, dict):
            if len(value) > self._config.max_dict_keys:
                return SandboxResult(
                    allowed=False,
                    blocked_by="param_validation",
                    reason=f"字典键数量超过限制: {len(value)} > {self._config.max_dict_keys} (路径: {path})",
                )
            for k, v in value.items():
                # 键名也需要校验（字符串长度）
                key_result = self._validate_string(str(k), f"{path}.<key>")
                if not key_result.allowed:
                    return key_result
                result = self._validate_value(v, f"{path}.{k}", depth + 1)
                if not result.allowed:
                    return result
            return SandboxResult(allowed=True)

        # 数字、布尔、None 直接通过
        if value is None or isinstance(value, (int, float, bool)):
            return SandboxResult(allowed=True)

        # 其他类型（bytes 等）
        if isinstance(value, bytes):
            if len(value) > self._config.max_string_length:
                return SandboxResult(
                    allowed=False,
                    blocked_by="param_validation",
                    reason=f"字节长度超过限制: {len(value)} > {self._config.max_string_length} (路径: {path})",
                )
            return SandboxResult(allowed=True)

        # 未知类型，检查是否可序列化
        try:
            json.dumps(value, default=str)
        except (TypeError, ValueError):
            return SandboxResult(
                allowed=False,
                blocked_by="param_validation",
                reason=f"不支持的参数类型: {type(value).__name__} (路径: {path})",
            )

        return SandboxResult(allowed=True)

    def _validate_string(self, value: str, path: str) -> SandboxResult:
        """校验字符串值.

        Args:
            value: 字符串值
            path: 值的路径

        Returns:
            SandboxResult
        """
        # 长度检查
        if len(value) > self._config.max_string_length:
            return SandboxResult(
                allowed=False,
                blocked_by="param_validation",
                reason=f"字符串长度超过限制: {len(value)} > {self._config.max_string_length} (路径: {path})",
            )

        # 命令注入检测
        for pattern in self._cmd_injection_regex:
            if pattern.search(value):
                return SandboxResult(
                    allowed=False,
                    blocked_by="param_validation",
                    reason=f"检测到潜在命令注入模式 (路径: {path}, 模式: {pattern.pattern})",
                    details={"matched_pattern": pattern.pattern, "path": path},
                )

        # 路径遍历检测
        if ".." in value and ("/" in value or "\\" in value):
            # 检查是否为路径遍历攻击
            if re.search(r"(\.\.[/\\])+", value):
                return SandboxResult(
                    allowed=False,
                    blocked_by="param_validation",
                    reason=f"检测到路径遍历模式 (路径: {path})",
                    details={"path": path, "value_preview": value[:100]},
                )

        return SandboxResult(allowed=True)


# ============================================================
# 危险函数检测器
# ============================================================

class DangerDetector:
    """危险函数/操作检测器.

    检测 Python 代码和参数中的危险操作：
    - 危险函数调用（eval, exec, os.system 等）
    - 文件系统操作的路径安全
    - 网络请求的目标地址（SSRF 防护）
    """

    def __init__(self, config: SandboxConfig) -> None:
        """初始化危险检测器.

        Args:
            config: 沙箱配置
        """
        self._config = config
        # 预编译 SSRF 检测正则
        self._ssrf_regex = [
            re.compile(p, re.IGNORECASE) for p in config.ssrf_blocked_patterns
        ]
        # 预编译敏感路径正则
        self._sensitive_path_regex = [
            re.compile(p, re.IGNORECASE) for p in config.sensitive_path_patterns
        ]

    def detect_code_danger(self, code: str) -> SandboxResult:
        """检测代码中的危险操作.

        Args:
            code: 待检测的代码字符串

        Returns:
            SandboxResult
        """
        if not isinstance(code, str) or not code.strip():
            return SandboxResult(allowed=True)

        # 检测危险函数
        found_dangers: List[str] = []
        for func in self._config.dangerous_functions:
            # 匹配函数名（考虑 import 别名和点号调用）
            pattern = r'\b' + re.escape(func).replace(r'\.', r'\.') + r'\s*\('
            if re.search(pattern, code):
                found_dangers.append(func)

        # 检测 __ 开头的魔法方法访问
        if re.search(r'__\w+__', code):
            found_dangers.append("magic_method_access")

        # 检测 import 语句
        if re.search(r'\b(import|from)\s+\w+', code):
            found_dangers.append("import_statement")

        if found_dangers:
            return SandboxResult(
                allowed=False,
                blocked_by="danger_detection",
                reason=f"检测到危险操作: {', '.join(found_dangers)}",
                details={"dangerous_items": found_dangers},
            )

        return SandboxResult(allowed=True)

    def detect_path_danger(self, path: str) -> SandboxResult:
        """检测文件路径的安全性.

        Args:
            path: 文件路径

        Returns:
            SandboxResult
        """
        if not isinstance(path, str):
            return SandboxResult(allowed=True)

        # 规范化路径（同时处理正斜杠和反斜杠）
        # 统一使用正斜杠进行模式匹配，确保跨平台兼容
        normalized_path = path.replace("\\", "/")
        normalized_path = os.path.normpath(normalized_path).replace("\\", "/")

        # 检测敏感路径
        for pattern in self._sensitive_path_regex:
            if pattern.search(normalized_path):
                return SandboxResult(
                    allowed=False,
                    blocked_by="danger_detection",
                    reason=f"检测到敏感路径访问: {path}",
                    details={"matched_pattern": pattern.pattern, "path": path},
                )

        # 符号链接检测（尝试解析符号链接）
        try:
            real_path = os.path.realpath(path)
            real_path_normalized = real_path.replace("\\", "/")
            if real_path_normalized != normalized_path:
                # 是符号链接，检查目标路径
                for pattern in self._sensitive_path_regex:
                    if pattern.search(real_path_normalized):
                        return SandboxResult(
                            allowed=False,
                            blocked_by="danger_detection",
                            reason=f"符号链接指向敏感路径: {path} -> {real_path}",
                            details={"real_path": real_path, "path": path},
                        )
        except (OSError, ValueError):
            pass  # 文件不存在时跳过

        return SandboxResult(allowed=True)

    def detect_ssrf(self, url: str) -> SandboxResult:
        """检测 SSRF（服务端请求伪造）风险.

        Args:
            url: 待检测的 URL

        Returns:
            SandboxResult
        """
        if not isinstance(url, str) or not url.strip():
            return SandboxResult(allowed=True)

        for pattern in self._ssrf_regex:
            if pattern.search(url):
                return SandboxResult(
                    allowed=False,
                    blocked_by="danger_detection",
                    reason=f"检测到 SSRF 风险: {url}",
                    details={"matched_pattern": pattern.pattern, "url": url},
                )

        return SandboxResult(allowed=True)

    def scan_arguments_for_danger(self, arguments: Dict[str, Any]) -> SandboxResult:
        """扫描参数字典中的危险内容.

        递归扫描所有字符串值，检测代码注入、路径遍历、SSRF 等。

        Args:
            arguments: 参数字典

        Returns:
            SandboxResult
        """
        if not isinstance(arguments, dict):
            return SandboxResult(allowed=True)

        return self._scan_value(arguments, "arguments")

    def _scan_value(self, value: Any, path: str) -> SandboxResult:
        """递归扫描值中的危险内容."""
        if isinstance(value, str):
            # 检测代码危险（检查是否包含危险函数调用）
            # 直接检测常见危险模式，不依赖长度阈值
            if any(danger in value for danger in [
                "eval(", "exec(", "os.system(", "subprocess.",
                "pickle.loads", "compile(", "__import__(",
            ]):
                code_result = self.detect_code_danger(value)
                if not code_result.allowed:
                    code_result.details["path"] = path
                    return code_result

            # 对于较长的字符串，做更全面的代码检测
            if len(value) > 50 and any(
                kw in value for kw in ("def ", "class ", "import ", "return ")
            ):
                code_result = self.detect_code_danger(value)
                if not code_result.allowed:
                    code_result.details["path"] = path
                    return code_result

            # 检测 SSRF（如果看起来像 URL）
            if value.startswith(("http://", "https://", "ftp://")):
                ssrf_result = self.detect_ssrf(value)
                if not ssrf_result.allowed:
                    ssrf_result.details["path"] = path
                    return ssrf_result

            # 检测路径危险（如果看起来像文件路径）
            if "/" in value or "\\" in value:
                # 检测路径遍历攻击
                if ".." in value and re.search(r"(\.\.[/\\])+", value):
                    return SandboxResult(
                        allowed=False,
                        blocked_by="danger_detection",
                        reason=f"检测到路径遍历模式 (路径: {path})",
                        details={"path": path, "value_preview": value[:100]},
                    )
                # 只检测明显的路径（包含路径分隔符且有一定长度）
                if len(value) > 3 and (
                    value.startswith("/")
                    or value.startswith("\\")
                    or value[1:3] in (":\\", ":/")
                    or ".." in value
                ):
                    path_result = self.detect_path_danger(value)
                    if not path_result.allowed:
                        path_result.details["path"] = path
                        return path_result

            return SandboxResult(allowed=True)

        if isinstance(value, (list, tuple)):
            for i, item in enumerate(value):
                result = self._scan_value(item, f"{path}[{i}]")
                if not result.allowed:
                    return result
            return SandboxResult(allowed=True)

        if isinstance(value, dict):
            for k, v in value.items():
                result = self._scan_value(v, f"{path}.{k}")
                if not result.allowed:
                    return result
            return SandboxResult(allowed=True)

        return SandboxResult(allowed=True)


# ============================================================
# 速率限制器（沙箱级别）
# ============================================================

class SandboxRateLimiter:
    """沙箱速率限制器.

    提供滑动窗口算法的速率限制：
    - 每个工具的调用频率限制
    - 每个 API Key 的总调用限制
    - 并发执行限制
    """

    def __init__(self, config: SandboxConfig) -> None:
        """初始化速率限制器.

        Args:
            config: 沙箱配置
        """
        self._config = config
        self._tool_requests: Dict[str, List[float]] = defaultdict(list)
        self._key_requests: Dict[str, List[float]] = defaultdict(list)
        self._concurrent_count: int = 0
        self._lock = Lock()

    def check_tool_rate(self, tool_name: str) -> SandboxResult:
        """检查工具级别的速率限制.

        Args:
            tool_name: 工具名称

        Returns:
            SandboxResult
        """
        limit = self._config.rate_limit_per_tool
        if limit <= 0:
            return SandboxResult(allowed=True)

        now = time.time()
        window_seconds = 60  # 每分钟

        with self._lock:
            # 清理过期的请求记录
            self._tool_requests[tool_name] = [
                t for t in self._tool_requests[tool_name]
                if now - t < window_seconds
            ]

            if len(self._tool_requests[tool_name]) >= limit:
                return SandboxResult(
                    allowed=False,
                    blocked_by="rate_limit",
                    reason=f"工具 {tool_name} 超过速率限制 (每分钟 {limit} 次)",
                    details={
                        "tool_name": tool_name,
                        "limit": limit,
                        "current": len(self._tool_requests[tool_name]),
                        "window_seconds": window_seconds,
                    },
                )

            self._tool_requests[tool_name].append(now)
            return SandboxResult(allowed=True)

    def check_key_rate(self, api_key_id: Optional[int]) -> SandboxResult:
        """检查 API Key 级别的速率限制.

        Args:
            api_key_id: API Key ID

        Returns:
            SandboxResult
        """
        if api_key_id is None:
            return SandboxResult(allowed=True)

        limit = self._config.rate_limit_per_key
        if limit <= 0:
            return SandboxResult(allowed=True)

        key = str(api_key_id)
        now = time.time()
        window_seconds = 60

        with self._lock:
            self._key_requests[key] = [
                t for t in self._key_requests[key]
                if now - t < window_seconds
            ]

            if len(self._key_requests[key]) >= limit:
                return SandboxResult(
                    allowed=False,
                    blocked_by="rate_limit",
                    reason=f"API Key {api_key_id} 超过速率限制 (每分钟 {limit} 次)",
                    details={
                        "api_key_id": api_key_id,
                        "limit": limit,
                        "current": len(self._key_requests[key]),
                        "window_seconds": window_seconds,
                    },
                )

            self._key_requests[key].append(now)
            return SandboxResult(allowed=True)

    def check_concurrent(self) -> SandboxResult:
        """检查并发执行限制.

        Returns:
            SandboxResult
        """
        limit = self._config.max_concurrent_executions
        if limit <= 0:
            return SandboxResult(allowed=True)

        with self._lock:
            if self._concurrent_count >= limit:
                return SandboxResult(
                    allowed=False,
                    blocked_by="rate_limit",
                    reason=f"超过最大并发执行限制: {self._concurrent_count}/{limit}",
                    details={
                        "current": self._concurrent_count,
                        "limit": limit,
                    },
                )

            self._concurrent_count += 1
            return SandboxResult(allowed=True)

    def release_concurrent(self) -> None:
        """释放一个并发执行槽位."""
        with self._lock:
            if self._concurrent_count > 0:
                self._concurrent_count -= 1

    def get_stats(self) -> Dict[str, Any]:
        """获取速率限制统计.

        Returns:
            统计信息字典
        """
        with self._lock:
            return {
                "tool_limits_tracked": len(self._tool_requests),
                "key_limits_tracked": len(self._key_requests),
                "concurrent_count": self._concurrent_count,
                "max_concurrent": self._config.max_concurrent_executions,
            }

    def reset(self) -> None:
        """重置所有计数."""
        with self._lock:
            self._tool_requests.clear()
            self._key_requests.clear()
            self._concurrent_count = 0


# ============================================================
# 文件系统隔离器
# ============================================================

class FileSystemIsolator:
    """文件系统隔离器.

    提供文件系统操作的安全限制：
    - 工作目录限制（只能在指定目录内操作）
    - 禁止访问敏感路径
    - 符号链接检测
    - 路径规范化校验
    """

    def __init__(self, config: SandboxConfig) -> None:
        """初始化文件系统隔离器.

        Args:
            config: 沙箱配置
        """
        self._config = config
        self._sensitive_regex = [
            re.compile(p, re.IGNORECASE) for p in config.sensitive_path_patterns
        ]

    @property
    def working_directory(self) -> str:
        """获取工作目录."""
        return self._config.working_directory or os.getcwd()

    def validate_path(self, path: str) -> SandboxResult:
        """验证路径是否在允许的范围内.

        Args:
            path: 待验证的路径

        Returns:
            SandboxResult
        """
        if not isinstance(path, str) or not path.strip():
            return SandboxResult(allowed=True)

        # 规范化路径（统一使用正斜杠进行模式匹配）
        try:
            normalized = os.path.normpath(path).replace("\\", "/")
        except Exception:
            return SandboxResult(
                allowed=False,
                blocked_by="filesystem_isolation",
                reason=f"路径规范化失败: {path}",
            )

        # 检测敏感路径
        for pattern in self._sensitive_regex:
            if pattern.search(normalized):
                return SandboxResult(
                    allowed=False,
                    blocked_by="filesystem_isolation",
                    reason=f"禁止访问敏感路径: {path}",
                    details={"matched_pattern": pattern.pattern},
                )

        # 工作目录限制（如果配置了工作目录）
        if self._config.working_directory:
            try:
                work_dir = os.path.abspath(self._config.working_directory).replace("\\", "/")
                # 确保工作目录以 / 结尾，避免前缀误匹配
                if not work_dir.endswith("/"):
                    work_dir_with_sep = work_dir + "/"
                else:
                    work_dir_with_sep = work_dir

                abs_path = os.path.abspath(normalized.replace("/", os.sep)).replace("\\", "/")
                if not abs_path.startswith(work_dir_with_sep) and abs_path != work_dir:
                    return SandboxResult(
                        allowed=False,
                        blocked_by="filesystem_isolation",
                        reason=f"路径超出工作目录范围: {path}",
                        details={"working_directory": work_dir, "path": abs_path},
                    )
            except Exception:
                pass

        # 符号链接检测
        try:
            if os.path.islink(path):
                real_path = os.path.realpath(path).replace("\\", "/")
                # 检查真实路径是否在允许范围内
                if self._config.working_directory:
                    work_dir = os.path.abspath(self._config.working_directory).replace("\\", "/")
                    if not work_dir.endswith("/"):
                        work_dir_with_sep = work_dir + "/"
                    else:
                        work_dir_with_sep = work_dir
                    if not real_path.startswith(work_dir_with_sep) and real_path != work_dir:
                        return SandboxResult(
                            allowed=False,
                            blocked_by="filesystem_isolation",
                            reason=f"符号链接指向工作目录外: {path} -> {real_path}",
                            details={"real_path": real_path},
                        )
        except (OSError, ValueError):
            pass  # 文件不存在时跳过

        return SandboxResult(allowed=True)


# ============================================================
# 沙箱执行器
# ============================================================

class SandboxedExecutor:
    """沙箱执行器.

    封装单次工具调用的完整安全管道：
    参数校验 → 危险检测 → 速率检查 → 资源限制 → 实际执行 → 审计日志

    使用方式：
        executor = SandboxedExecutor(config)
        result = executor.execute(
            tool_name="my_tool",
            arguments={"key": "value"},
            actual_executor=lambda args: my_function(**args),
        )
    """

    def __init__(
        self,
        config: SandboxConfig,
        audit_callback: Optional[Callable[[SandboxExecutionContext], None]] = None,
        alert_callback: Optional[Callable[[str, Dict[str, Any]], None]] = None,
    ) -> None:
        """初始化沙箱执行器.

        Args:
            config: 沙箱配置
            audit_callback: 审计日志回调函数
            alert_callback: 安全告警回调函数
        """
        self._config = config
        self._param_validator = ParameterValidator(config)
        self._danger_detector = DangerDetector(config)
        self._fs_isolator = FileSystemIsolator(config)
        self._rate_limiter = SandboxRateLimiter(config)
        self._audit_callback = audit_callback
        self._alert_callback = alert_callback

    @property
    def config(self) -> SandboxConfig:
        """获取沙箱配置."""
        return self._config

    @property
    def rate_limiter(self) -> SandboxRateLimiter:
        """获取速率限制器."""
        return self._rate_limiter

    def execute(
        self,
        tool_name: str,
        arguments: Dict[str, Any],
        actual_executor: Callable[[Dict[str, Any]], Any],
        caller: str = "",
        api_key_id: Optional[int] = None,
        ip_address: str = "",
    ) -> Tuple[bool, Any, str]:
        """在沙箱中执行工具调用.

        Args:
            tool_name: 工具名称
            arguments: 调用参数
            actual_executor: 实际执行函数，接收参数字典，返回结果
            caller: 调用者标识
            api_key_id: API Key ID
            ip_address: 调用者 IP 地址

        Returns:
            (是否成功, 结果数据, 错误信息) 元组
        """
        context = SandboxExecutionContext(
            tool_name=tool_name,
            arguments=arguments,
            caller=caller,
            api_key_id=api_key_id,
            ip_address=ip_address,
            start_time=time.time(),
        )

        try:
            # Level 0: 无限制，直接执行
            if self._config.level == SANDBOX_LEVEL_UNLIMITED:
                return self._do_execute(context, actual_executor)

            # 检查工具白名单/黑名单
            tool_check = self._check_tool_list(tool_name)
            if not tool_check.allowed:
                context.blocked = True
                context.block_reason = tool_check.reason
                self._record_audit(context)
                self._trigger_alert("tool_blacklisted", context)
                return False, None, tool_check.reason

            # Level 1+: 参数校验
            if self._config.level >= SANDBOX_LEVEL_BASIC:
                param_result = self._param_validator.validate(arguments, tool_name)
                if not param_result.allowed:
                    context.blocked = True
                    context.block_reason = param_result.reason
                    self._record_audit(context)
                    self._trigger_alert("param_validation_failed", context)
                    return False, None, param_result.reason

                # 危险检测
                danger_result = self._danger_detector.scan_arguments_for_danger(arguments)
                if not danger_result.allowed:
                    context.blocked = True
                    context.block_reason = danger_result.reason
                    self._record_audit(context)
                    self._trigger_alert("danger_detected", context)
                    return False, None, danger_result.reason

                # 速率限制 - 工具级别
                tool_rate_result = self._rate_limiter.check_tool_rate(tool_name)
                if not tool_rate_result.allowed:
                    context.blocked = True
                    context.block_reason = tool_rate_result.reason
                    self._record_audit(context)
                    return False, None, tool_rate_result.reason

                # 速率限制 - API Key 级别
                key_rate_result = self._rate_limiter.check_key_rate(api_key_id)
                if not key_rate_result.allowed:
                    context.blocked = True
                    context.block_reason = key_rate_result.reason
                    self._record_audit(context)
                    return False, None, key_rate_result.reason

            # Level 2+: 并发限制 + 资源限制
            if self._config.level >= SANDBOX_LEVEL_STRICT:
                # 并发限制
                concurrency_result = self._rate_limiter.check_concurrent()
                if not concurrency_result.allowed:
                    context.blocked = True
                    context.block_reason = concurrency_result.reason
                    self._record_audit(context)
                    return False, None, concurrency_result.reason

                try:
                    return self._do_execute(context, actual_executor)
                finally:
                    self._rate_limiter.release_concurrent()

            # Level 1: 直接执行
            return self._do_execute(context, actual_executor)

        except Exception as e:
            context.error = str(e)
            context.duration_ms = int((time.time() - context.start_time) * 1000)
            self._record_audit(context)
            return False, None, str(e)

    def _do_execute(
        self,
        context: SandboxExecutionContext,
        actual_executor: Callable[[Dict[str, Any]], Any],
    ) -> Tuple[bool, Any, str]:
        """执行实际的工具调用并记录结果."""
        try:
            result = actual_executor(context.arguments)
            context.result = result
            context.duration_ms = int((time.time() - context.start_time) * 1000)

            # 检查输出大小
            output_size = self._estimate_output_size(result)
            if output_size > self._config.max_output_size:
                context.blocked = True
                context.block_reason = f"输出大小超过限制: {output_size} > {self._config.max_output_size}"
                self._record_audit(context)
                return False, None, context.block_reason

            self._record_audit(context)
            return True, result, ""

        except Exception as e:
            context.error = str(e)
            context.duration_ms = int((time.time() - context.start_time) * 1000)
            self._record_audit(context)
            return False, None, str(e)

    def _check_tool_list(self, tool_name: str) -> SandboxResult:
        """检查工具是否在白名单/黑名单中.

        Args:
            tool_name: 工具名称

        Returns:
            SandboxResult
        """
        # 黑名单优先
        if self._config.tool_blacklist:
            for pattern in self._config.tool_blacklist:
                if self._match_tool_pattern(tool_name, pattern):
                    return SandboxResult(
                        allowed=False,
                        blocked_by="tool_blacklist",
                        reason=f"工具在黑名单中: {tool_name}",
                    )

        # 白名单（如果配置了白名单，则只有白名单中的工具允许）
        if self._config.tool_whitelist:
            for pattern in self._config.tool_whitelist:
                if self._match_tool_pattern(tool_name, pattern):
                    return SandboxResult(allowed=True)
            return SandboxResult(
                allowed=False,
                blocked_by="tool_whitelist",
                reason=f"工具不在白名单中: {tool_name}",
            )

        return SandboxResult(allowed=True)

    @staticmethod
    def _match_tool_pattern(tool_name: str, pattern: str) -> bool:
        """匹配工具名模式（支持通配符 *）.

        Args:
            tool_name: 工具名称
            pattern: 匹配模式

        Returns:
            True 表示匹配
        """
        if "*" not in pattern:
            return tool_name == pattern
        # 简单的通配符匹配
        import fnmatch
        return fnmatch.fnmatch(tool_name, pattern)

    @staticmethod
    def _estimate_output_size(result: Any) -> int:
        """估算输出结果的大小（字节）.

        Args:
            result: 结果数据

        Returns:
            估算的字节大小
        """
        if result is None:
            return 0
        try:
            return len(json.dumps(result, default=str, ensure_ascii=False).encode("utf-8"))
        except (TypeError, ValueError):
            return len(str(result).encode("utf-8"))

    def _record_audit(self, context: SandboxExecutionContext) -> None:
        """记录审计日志."""
        if self._audit_callback:
            try:
                self._audit_callback(context)
            except Exception as e:
                logger.warning("sandbox.audit_callback_failed", error=str(e))

    def _trigger_alert(self, alert_type: str, context: SandboxExecutionContext) -> None:
        """触发安全告警."""
        if self._alert_callback:
            try:
                self._alert_callback(
                    alert_type,
                    {
                        "tool_name": context.tool_name,
                        "caller": context.caller,
                        "ip_address": context.ip_address,
                        "api_key_id": context.api_key_id,
                        "reason": context.block_reason,
                        "alert_type": alert_type,
                    },
                )
            except Exception as e:
                logger.warning("sandbox.alert_callback_failed", error=str(e))

    def validate_only(
        self,
        tool_name: str,
        arguments: Dict[str, Any],
        api_key_id: Optional[int] = None,
    ) -> SandboxResult:
        """仅做安全校验，不实际执行.

        用于预检查场景，如前端表单验证。

        Args:
            tool_name: 工具名称
            arguments: 调用参数
            api_key_id: API Key ID

        Returns:
            SandboxResult
        """
        if self._config.level == SANDBOX_LEVEL_UNLIMITED:
            return SandboxResult(allowed=True)

        # 工具列表检查
        tool_check = self._check_tool_list(tool_name)
        if not tool_check.allowed:
            return tool_check

        # 参数校验
        param_result = self._param_validator.validate(arguments, tool_name)
        if not param_result.allowed:
            return param_result

        # 危险检测
        danger_result = self._danger_detector.scan_arguments_for_danger(arguments)
        if not danger_result.allowed:
            return danger_result

        return SandboxResult(allowed=True)


# ============================================================
# 沙箱管理器（全局单例）
# ============================================================

class SandboxManager:
    """沙箱管理器.

    全局单例，负责：
    - 沙箱级别配置管理
    - 工具白名单/黑名单管理
    - 执行统计
    - 危险操作告警回调
    - 创建 SandboxedExecutor 实例
    """

    _instance: Optional["SandboxManager"] = None
    _instance_lock = RLock()

    def __init__(self, config: Optional[SandboxConfig] = None) -> None:
        """初始化沙箱管理器.

        Args:
            config: 沙箱配置，为 None 时使用默认配置
        """
        self._config = config or SandboxConfig()
        self._executor: Optional[SandboxedExecutor] = None
        self._total_executions: int = 0
        self._blocked_executions: int = 0
        self._tool_stats: Dict[str, Dict[str, int]] = defaultdict(
            lambda: {"total": 0, "blocked": 0}
        )
        self._lock = RLock()
        self._alert_callbacks: List[Callable[[str, Dict[str, Any]], None]] = []
        self._audit_callbacks: List[Callable[[SandboxExecutionContext], None]] = []

    # --------------------------------------------------------
    # 单例模式
    # --------------------------------------------------------

    @classmethod
    def get_instance(cls, config: Optional[SandboxConfig] = None) -> "SandboxManager":
        """获取全局单例.

        Args:
            config: 首次创建时的配置

        Returns:
            SandboxManager 单例
        """
        if cls._instance is None:
            with cls._instance_lock:
                if cls._instance is None:
                    cls._instance = cls(config)
        return cls._instance

    @classmethod
    def reset_instance(cls) -> None:
        """重置单例（主要用于测试）."""
        with cls._instance_lock:
            cls._instance = None

    # --------------------------------------------------------
    # 配置管理
    # --------------------------------------------------------

    @property
    def config(self) -> SandboxConfig:
        """获取当前配置."""
        return self._config

    def update_config(self, config: SandboxConfig) -> None:
        """更新配置.

        Args:
            config: 新的沙箱配置
        """
        with self._lock:
            self._config = config
            # 重新创建执行器
            self._executor = None
            logger.info(
                "sandbox.config_updated",
                level=config.level,
                timeout=config.timeout,
            )

    def set_level(self, level: int) -> None:
        """设置沙箱安全级别.

        Args:
            level: 安全级别（0-3）
        """
        if level < SANDBOX_LEVEL_UNLIMITED or level > SANDBOX_LEVEL_MAXIMUM:
            raise ValueError(f"无效的沙箱级别: {level}，有效范围 0-3")

        with self._lock:
            self._config.level = level
            self._executor = None
            logger.info("sandbox.level_changed", level=level)

    # --------------------------------------------------------
    # 白名单/黑名单管理
    # --------------------------------------------------------

    def add_to_whitelist(self, tool_pattern: str) -> None:
        """添加工具到白名单.

        Args:
            tool_pattern: 工具名模式（支持通配符）
        """
        with self._lock:
            if tool_pattern not in self._config.tool_whitelist:
                self._config.tool_whitelist.append(tool_pattern)

    def remove_from_whitelist(self, tool_pattern: str) -> None:
        """从白名单移除工具.

        Args:
            tool_pattern: 工具名模式
        """
        with self._lock:
            if tool_pattern in self._config.tool_whitelist:
                self._config.tool_whitelist.remove(tool_pattern)

    def add_to_blacklist(self, tool_pattern: str) -> None:
        """添加工具到黑名单.

        Args:
            tool_pattern: 工具名模式
        """
        with self._lock:
            if tool_pattern not in self._config.tool_blacklist:
                self._config.tool_blacklist.append(tool_pattern)

    def remove_from_blacklist(self, tool_pattern: str) -> None:
        """从黑名单移除工具.

        Args:
            tool_pattern: 工具名模式
        """
        with self._lock:
            if tool_pattern in self._config.tool_blacklist:
                self._config.tool_blacklist.remove(tool_pattern)

    # --------------------------------------------------------
    # 回调管理
    # --------------------------------------------------------

    def register_alert_callback(
        self, callback: Callable[[str, Dict[str, Any]], None]
    ) -> None:
        """注册安全告警回调.

        Args:
            callback: 回调函数 (alert_type, details) -> None
        """
        with self._lock:
            self._alert_callbacks.append(callback)
            self._executor = None  # 重建执行器

    def register_audit_callback(
        self, callback: Callable[[SandboxExecutionContext], None]
    ) -> None:
        """注册审计日志回调.

        Args:
            callback: 回调函数 (context) -> None
        """
        with self._lock:
            self._audit_callbacks.append(callback)
            self._executor = None  # 重建执行器

    # --------------------------------------------------------
    # 执行器获取
    # --------------------------------------------------------

    def get_executor(self) -> SandboxedExecutor:
        """获取沙箱执行器实例.

        Returns:
            SandboxedExecutor 实例
        """
        if self._executor is None:
            with self._lock:
                if self._executor is None:
                    self._executor = SandboxedExecutor(
                        config=self._config,
                        audit_callback=self._combined_audit_callback,
                        alert_callback=self._combined_alert_callback,
                    )
        return self._executor

    def _combined_audit_callback(self, context: SandboxExecutionContext) -> None:
        """组合的审计回调（调用所有已注册的回调）."""
        # 更新统计
        with self._lock:
            self._total_executions += 1
            if context.blocked:
                self._blocked_executions += 1
            self._tool_stats[context.tool_name]["total"] += 1
            if context.blocked:
                self._tool_stats[context.tool_name]["blocked"] += 1

        # 调用所有注册的回调
        for callback in self._audit_callbacks:
            try:
                callback(context)
            except Exception as e:
                logger.warning("sandbox.audit_callback_error", error=str(e))

    def _combined_alert_callback(
        self, alert_type: str, details: Dict[str, Any]
    ) -> None:
        """组合的告警回调."""
        for callback in self._alert_callbacks:
            try:
                callback(alert_type, details)
            except Exception as e:
                logger.warning("sandbox.alert_callback_error", error=str(e))

    # --------------------------------------------------------
    # 统计
    # --------------------------------------------------------

    def get_stats(self) -> Dict[str, Any]:
        """获取沙箱统计信息.

        Returns:
            统计信息字典
        """
        with self._lock:
            return {
                "level": self._config.level,
                "total_executions": self._total_executions,
                "blocked_executions": self._blocked_executions,
                "blocked_rate": (
                    self._blocked_executions / self._total_executions
                    if self._total_executions > 0
                    else 0
                ),
                "tool_count": len(self._tool_stats),
                "whitelist_size": len(self._config.tool_whitelist),
                "blacklist_size": len(self._config.tool_blacklist),
                "rate_limiter": self.get_executor().rate_limiter.get_stats(),
            }

    def get_tool_stats(self, tool_name: Optional[str] = None) -> Any:
        """获取工具级别的统计.

        Args:
            tool_name: 工具名称，为 None 则返回所有工具统计

        Returns:
            工具统计信息
        """
        with self._lock:
            if tool_name:
                return dict(self._tool_stats.get(tool_name, {"total": 0, "blocked": 0}))
            return {k: dict(v) for k, v in self._tool_stats.items()}

    def reset_stats(self) -> None:
        """重置所有统计."""
        with self._lock:
            self._total_executions = 0
            self._blocked_executions = 0
            self._tool_stats.clear()
            if self._executor:
                self._executor.rate_limiter.reset()


# ============================================================
# 便捷函数
# ============================================================

def get_sandbox_manager() -> SandboxManager:
    """获取全局沙箱管理器单例.

    Returns:
        SandboxManager 实例
    """
    return SandboxManager.get_instance()


def execute_in_sandbox(
    tool_name: str,
    arguments: Dict[str, Any],
    actual_executor: Callable[[Dict[str, Any]], Any],
    caller: str = "",
    api_key_id: Optional[int] = None,
    ip_address: str = "",
) -> Tuple[bool, Any, str]:
    """便捷函数：在沙箱中执行工具调用.

    Args:
        tool_name: 工具名称
        arguments: 调用参数
        actual_executor: 实际执行函数
        caller: 调用者标识
        api_key_id: API Key ID
        ip_address: 调用者 IP

    Returns:
        (是否成功, 结果数据, 错误信息) 元组
    """
    manager = get_sandbox_manager()
    executor = manager.get_executor()
    return executor.execute(
        tool_name=tool_name,
        arguments=arguments,
        actual_executor=actual_executor,
        caller=caller,
        api_key_id=api_key_id,
        ip_address=ip_address,
    )


# ============================================================
# 模块导出
# ============================================================

__all__ = [
    # 常量
    "SANDBOX_LEVEL_UNLIMITED",
    "SANDBOX_LEVEL_BASIC",
    "SANDBOX_LEVEL_STRICT",
    "SANDBOX_LEVEL_MAXIMUM",
    "DEFAULT_SANDBOX_LEVEL",
    "DEFAULT_TIMEOUT",
    "DEFAULT_MAX_OUTPUT_SIZE",
    "DANGEROUS_FUNCTIONS",
    "SENSITIVE_PATH_PATTERNS",
    "COMMAND_INJECTION_PATTERNS",
    "SSRF_BLOCKED_PATTERNS",
    # 数据类
    "SandboxConfig",
    "SandboxResult",
    "SandboxExecutionContext",
    # 组件类
    "ParameterValidator",
    "DangerDetector",
    "SandboxRateLimiter",
    "FileSystemIsolator",
    # 主类
    "SandboxedExecutor",
    "SandboxManager",
    # 便捷函数
    "get_sandbox_manager",
    "execute_in_sandbox",
]
