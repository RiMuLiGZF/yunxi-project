"""M11 MCP Bus - 沙箱安全测试.

测试覆盖：
- 参数校验（类型/长度/深度/敏感字符）
- 危险函数检测（eval/exec/os.system/subprocess 等）
- 速率限制测试（滑动窗口/超限拦截）
- 路径安全测试（路径遍历/符号链接/敏感路径）
- 沙箱级别切换测试
- 审计日志测试
- 向后兼容测试
"""

from __future__ import annotations

import os
import sys
import time
from typing import Any, Dict

import pytest

# 添加项目根目录到 path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.security.sandbox import (  # noqa: E402
    COMMAND_INJECTION_PATTERNS,
    DANGEROUS_FUNCTIONS,
    DEFAULT_SANDBOX_LEVEL,
    SANDBOX_LEVEL_BASIC,
    SANDBOX_LEVEL_STRICT,
    SANDBOX_LEVEL_UNLIMITED,
    DangerDetector,
    FileSystemIsolator,
    ParameterValidator,
    SandboxConfig,
    SandboxedExecutor,
    SandboxExecutionContext,
    SandboxManager,
    SandboxRateLimiter,
    SandboxResult,
    SENSITIVE_PATH_PATTERNS,
    SSRF_BLOCKED_PATTERNS,
)


# ============================================================
# Fixtures
# ============================================================

@pytest.fixture
def basic_config():
    """基础沙箱配置（Level 1）."""
    return SandboxConfig(
        level=SANDBOX_LEVEL_BASIC,
        timeout=5,
        max_output_size=1024 * 1024,
        max_string_length=1000,
        max_list_length=100,
        max_dict_keys=100,
        max_nesting_depth=5,
        rate_limit_per_tool=10,
        rate_limit_per_key=100,
        max_concurrent_executions=5,
    )


@pytest.fixture
def param_validator(basic_config):
    """参数校验器."""
    return ParameterValidator(basic_config)


@pytest.fixture
def danger_detector(basic_config):
    """危险检测器."""
    return DangerDetector(basic_config)


@pytest.fixture
def rate_limiter(basic_config):
    """速率限制器."""
    return SandboxRateLimiter(basic_config)


@pytest.fixture
def fs_isolator(basic_config):
    """文件系统隔离器."""
    return FileSystemIsolator(basic_config)


@pytest.fixture
def sandbox_executor(basic_config):
    """沙箱执行器."""
    return SandboxedExecutor(basic_config)


@pytest.fixture
def sandbox_manager():
    """沙箱管理器（每次测试重置）."""
    SandboxManager.reset_instance()
    manager = SandboxManager.get_instance()
    yield manager
    SandboxManager.reset_instance()


# ============================================================
# 一、参数校验测试
# ============================================================

class TestParameterValidator:
    """参数校验测试."""

    # --- 类型校验 ---

    def test_validate_dict_success(self, param_validator):
        """正常字典参数应通过校验."""
        result = param_validator.validate({"key": "value", "num": 123})
        assert result.allowed is True
        assert result.blocked_by == ""

    def test_validate_non_dict_fails(self, param_validator):
        """非字典参数应失败."""
        result = param_validator.validate("not a dict")  # type: ignore
        assert result.allowed is False
        assert result.blocked_by == "param_validation"
        assert "字典类型" in result.reason

    def test_validate_none_fails(self, param_validator):
        """None 参数应失败."""
        result = param_validator.validate(None)  # type: ignore
        assert result.allowed is False
        assert result.blocked_by == "param_validation"

    def test_validate_empty_dict(self, param_validator):
        """空字典应通过."""
        result = param_validator.validate({})
        assert result.allowed is True

    # --- 长度限制 ---

    def test_string_too_long_fails(self, param_validator):
        """过长字符串应失败."""
        long_str = "a" * 2000  # 超过 max_string_length=1000
        result = param_validator.validate({"data": long_str})
        assert result.allowed is False
        assert "字符串长度" in result.reason

    def test_string_within_limit_passes(self, param_validator):
        """字符串在限制内应通过."""
        ok_str = "a" * 500
        result = param_validator.validate({"data": ok_str})
        assert result.allowed is True

    def test_list_too_long_fails(self, param_validator):
        """过长列表应失败."""
        long_list = list(range(200))  # 超过 max_list_length=100
        result = param_validator.validate({"items": long_list})
        assert result.allowed is False
        assert "列表长度" in result.reason

    def test_list_within_limit_passes(self, param_validator):
        """列表在限制内应通过."""
        ok_list = list(range(50))
        result = param_validator.validate({"items": ok_list})
        assert result.allowed is True

    def test_dict_too_many_keys_fails(self, param_validator):
        """过多键的字典应失败."""
        big_dict = {f"key{i}": i for i in range(200)}
        result = param_validator.validate(big_dict)
        assert result.allowed is False
        assert "键数量" in result.reason

    # --- 嵌套深度限制 ---

    def test_nesting_depth_exceeded_fails(self, param_validator):
        """超过嵌套深度限制应失败."""
        # 构建深度为 6 的嵌套结构（max_nesting_depth=5）
        deep = {}
        current = deep
        for i in range(6):
            current["next"] = {}
            current = current["next"]
        result = param_validator.validate(deep)
        assert result.allowed is False
        assert "嵌套深度" in result.reason

    def test_nesting_depth_within_limit_passes(self, param_validator):
        """嵌套深度在限制内应通过."""
        # 构建深度为 3 的嵌套结构
        nested = {"a": {"b": {"c": "value"}}}
        result = param_validator.validate(nested)
        assert result.allowed is True

    # --- 敏感字符过滤 ---

    def test_command_injection_semicolon_fails(self, param_validator):
        """检测到分号命令注入应失败."""
        result = param_validator.validate({"cmd": "ls -la; rm -rf /"})
        assert result.allowed is False
        assert result.blocked_by == "param_validation"

    def test_command_injection_pipe_fails(self, param_validator):
        """检测到管道命令注入应失败."""
        result = param_validator.validate({"cmd": "cat /etc/passwd | grep root"})
        assert result.allowed is False

    def test_command_injection_backtick_fails(self, param_validator):
        """检测到反引号命令注入应失败."""
        result = param_validator.validate({"cmd": "echo `whoami`"})
        assert result.allowed is False

    def test_path_traversal_fails(self, param_validator):
        """检测到路径遍历应失败."""
        result = param_validator.validate({"path": "../../etc/passwd"})
        assert result.allowed is False

    def test_normal_string_passes(self, param_validator):
        """正常字符串应通过."""
        result = param_validator.validate({"name": "hello world", "desc": "正常的描述"})
        assert result.allowed is True

    # --- 各种类型支持 ---

    def test_integer_passes(self, param_validator):
        """整数参数应通过."""
        result = param_validator.validate({"count": 42, "price": 99.9})
        assert result.allowed is True

    def test_boolean_passes(self, param_validator):
        """布尔参数应通过."""
        result = param_validator.validate({"enabled": True, "flag": False})
        assert result.allowed is True

    def test_none_value_passes(self, param_validator):
        """None 值应通过."""
        result = param_validator.validate({"optional": None})
        assert result.allowed is True

    def test_nested_list_in_dict_passes(self, param_validator):
        """嵌套列表和字典应通过（深度内）."""
        data = {
            "users": [
                {"name": "alice", "roles": ["admin", "user"]},
                {"name": "bob", "roles": ["user"]},
            ]
        }
        result = param_validator.validate(data)
        assert result.allowed is True


# ============================================================
# 二、危险函数检测测试
# ============================================================

class TestDangerDetector:
    """危险函数检测测试."""

    # --- 代码危险检测 ---

    def test_detect_eval_fails(self, danger_detector):
        """检测到 eval 应失败."""
        code = "result = eval('1 + 1')"
        result = danger_detector.detect_code_danger(code)
        assert result.allowed is False
        assert "eval" in result.reason

    def test_detect_exec_fails(self, danger_detector):
        """检测到 exec 应失败."""
        code = "exec('print(1)')"
        result = danger_detector.detect_code_danger(code)
        assert result.allowed is False
        assert "exec" in result.reason

    def test_detect_os_system_fails(self, danger_detector):
        """检测到 os.system 应失败."""
        code = "os.system('ls')"
        result = danger_detector.detect_code_danger(code)
        assert result.allowed is False
        assert "os.system" in result.reason

    def test_detect_subprocess_fails(self, danger_detector):
        """检测到 subprocess.call 应失败."""
        code = "subprocess.call(['ls', '-la'])"
        result = danger_detector.detect_code_danger(code)
        assert result.allowed is False

    def test_detect_pickle_loads_fails(self, danger_detector):
        """检测到 pickle.loads 应失败."""
        code = "data = pickle.loads(raw_data)"
        result = danger_detector.detect_code_danger(code)
        assert result.allowed is False

    def test_detect_import_fails(self, danger_detector):
        """检测到 import 语句应失败."""
        code = "import os\nprint(os.getcwd())"
        result = danger_detector.detect_code_danger(code)
        assert result.allowed is False
        assert "import_statement" in result.details.get("dangerous_items", [])

    def test_safe_code_passes(self, danger_detector):
        """安全代码应通过."""
        code = "result = a + b\nprint(result)"
        result = danger_detector.detect_code_danger(code)
        assert result.allowed is True

    def test_empty_code_passes(self, danger_detector):
        """空代码应通过."""
        result = danger_detector.detect_code_danger("")
        assert result.allowed is True

    # --- 路径危险检测 ---

    def test_detect_etc_passwd_fails(self, danger_detector):
        """检测到 /etc/passwd 应失败."""
        result = danger_detector.detect_path_danger("/etc/passwd")
        assert result.allowed is False
        assert "敏感路径" in result.reason

    def test_detect_ssh_path_fails(self, danger_detector):
        """检测到 .ssh 路径应失败."""
        result = danger_detector.detect_path_danger("/home/user/.ssh/id_rsa")
        assert result.allowed is False

    def test_detect_proc_path_fails(self, danger_detector):
        """检测到 /proc 路径应失败."""
        result = danger_detector.detect_path_danger("/proc/self/environ")
        assert result.allowed is False

    def test_normal_path_passes(self, danger_detector):
        """正常路径应通过."""
        result = danger_detector.detect_path_danger("/tmp/data.txt")
        assert result.allowed is True

    def test_current_dir_passes(self, danger_detector):
        """当前目录路径应通过."""
        result = danger_detector.detect_path_danger("./data/file.txt")
        assert result.allowed is True

    # --- SSRF 检测 ---

    def test_detect_localhost_ssrf_fails(self, danger_detector):
        """检测到 localhost SSRF 应失败."""
        result = danger_detector.detect_ssrf("http://localhost:8080/internal")
        assert result.allowed is False
        assert "SSRF" in result.reason

    def test_detect_127_ssrf_fails(self, danger_detector):
        """检测到 127.x.x.x SSRF 应失败."""
        result = danger_detector.detect_ssrf("http://127.0.0.1/admin")
        assert result.allowed is False

    def test_detect_192_168_ssrf_fails(self, danger_detector):
        """检测到 192.168.x.x SSRF 应失败."""
        result = danger_detector.detect_ssrf("http://192.168.1.1/admin")
        assert result.allowed is False

    def test_detect_10_ssrf_fails(self, danger_detector):
        """检测到 10.x.x.x SSRF 应失败."""
        result = danger_detector.detect_ssrf("http://10.0.0.1/internal")
        assert result.allowed is False

    def test_external_url_passes(self, danger_detector):
        """外部 URL 应通过."""
        result = danger_detector.detect_ssrf("https://example.com/api")
        assert result.allowed is True

    def test_empty_url_passes(self, danger_detector):
        """空 URL 应通过."""
        result = danger_detector.detect_ssrf("")
        assert result.allowed is True

    # --- 参数扫描 ---

    def test_scan_args_with_code_injection_fails(self, danger_detector):
        """扫描包含代码注入的参数应失败."""
        args = {"code": "eval('1+1')", "name": "test"}
        result = danger_detector.scan_arguments_for_danger(args)
        assert result.allowed is False

    def test_scan_args_with_ssrf_fails(self, danger_detector):
        """扫描包含 SSRF URL 的参数应失败."""
        args = {"url": "http://localhost:3000/secret"}
        result = danger_detector.scan_arguments_for_danger(args)
        assert result.allowed is False

    def test_scan_args_with_path_traversal_fails(self, danger_detector):
        """扫描包含路径遍历的参数应失败."""
        args = {"file": "../../etc/shadow"}
        result = danger_detector.scan_arguments_for_danger(args)
        assert result.allowed is False

    def test_scan_args_safe_passes(self, danger_detector):
        """扫描安全参数应通过."""
        args = {
            "name": "test",
            "count": 10,
            "items": ["a", "b", "c"],
            "nested": {"key": "value"},
        }
        result = danger_detector.scan_arguments_for_danger(args)
        assert result.allowed is True


# ============================================================
# 三、速率限制测试
# ============================================================

class TestSandboxRateLimiter:
    """速率限制测试."""

    def test_tool_rate_within_limit_passes(self, rate_limiter):
        """工具限流在限制内应通过."""
        for i in range(10):
            result = rate_limiter.check_tool_rate("test_tool")
            assert result.allowed is True

    def test_tool_rate_exceeded_fails(self, rate_limiter):
        """工具限流超过限制应失败."""
        # 先消耗掉所有限额
        for i in range(10):
            rate_limiter.check_tool_rate("test_tool")
        # 第 11 次应失败
        result = rate_limiter.check_tool_rate("test_tool")
        assert result.allowed is False
        assert result.blocked_by == "rate_limit"

    def test_tool_rate_independent(self, rate_limiter):
        """不同工具的限流应独立."""
        # 消耗 tool_a 的限额
        for i in range(10):
            rate_limiter.check_tool_rate("tool_a")
        # tool_a 第 11 次应失败
        result_a = rate_limiter.check_tool_rate("tool_a")
        assert result_a.allowed is False
        # tool_b 第 1 次应通过
        result_b = rate_limiter.check_tool_rate("tool_b")
        assert result_b.allowed is True

    def test_key_rate_within_limit_passes(self, rate_limiter):
        """API Key 限流在限制内应通过."""
        for i in range(50):
            result = rate_limiter.check_key_rate(1)
            assert result.allowed is True

    def test_key_rate_exceeded_fails(self, rate_limiter):
        """API Key 限流超过限制应失败."""
        for i in range(100):
            rate_limiter.check_key_rate(1)
        result = rate_limiter.check_key_rate(1)
        assert result.allowed is False

    def test_key_rate_none_passes(self, rate_limiter):
        """None Key 应通过（不限制）."""
        for i in range(200):
            result = rate_limiter.check_key_rate(None)
            assert result.allowed is True

    def test_concurrent_within_limit_passes(self, rate_limiter):
        """并发在限制内应通过."""
        for i in range(5):
            result = rate_limiter.check_concurrent()
            assert result.allowed is True

    def test_concurrent_exceeded_fails(self, rate_limiter):
        """并发超过限制应失败."""
        for i in range(5):
            rate_limiter.check_concurrent()
        result = rate_limiter.check_concurrent()
        assert result.allowed is False

    def test_release_concurrent(self, rate_limiter):
        """释放并发槽位后应能再次获取."""
        # 占满
        for i in range(5):
            rate_limiter.check_concurrent()
        # 释放一个
        rate_limiter.release_concurrent()
        # 应能再获取一个
        result = rate_limiter.check_concurrent()
        assert result.allowed is True

    def test_reset_clears_all(self, rate_limiter):
        """重置应清除所有计数."""
        for i in range(5):
            rate_limiter.check_tool_rate("tool1")
            rate_limiter.check_key_rate(1)
            rate_limiter.check_concurrent()
        rate_limiter.reset()
        stats = rate_limiter.get_stats()
        assert stats["tool_limits_tracked"] == 0
        assert stats["key_limits_tracked"] == 0
        assert stats["concurrent_count"] == 0

    def test_zero_limit_disables(self, basic_config):
        """限制为 0 应禁用限流."""
        config = SandboxConfig(
            level=SANDBOX_LEVEL_BASIC,
            rate_limit_per_tool=0,
            rate_limit_per_key=0,
            max_concurrent_executions=0,
        )
        rl = SandboxRateLimiter(config)
        # 工具限流
        for i in range(100):
            assert rl.check_tool_rate("tool").allowed is True
        # Key 限流
        for i in range(100):
            assert rl.check_key_rate(1).allowed is True
        # 并发限流
        for i in range(100):
            assert rl.check_concurrent().allowed is True


# ============================================================
# 四、路径安全测试
# ============================================================

class TestFileSystemIsolator:
    """文件系统隔离测试."""

    def test_validate_sensitive_etc_fails(self, fs_isolator):
        """访问 /etc 路径应失败."""
        result = fs_isolator.validate_path("/etc/passwd")
        assert result.allowed is False
        assert result.blocked_by == "filesystem_isolation"

    def test_validate_normal_path_passes(self, fs_isolator):
        """正常路径应通过."""
        result = fs_isolator.validate_path("/tmp/myapp/data.json")
        assert result.allowed is True

    def test_validate_ssh_path_fails(self, fs_isolator):
        """SSH 密钥路径应失败."""
        result = fs_isolator.validate_path("/home/user/.ssh/id_rsa")
        assert result.allowed is False

    def test_validate_dotenv_fails(self, fs_isolator):
        """.env 文件路径应失败."""
        result = fs_isolator.validate_path("/app/.env")
        assert result.allowed is False

    def test_validate_empty_passes(self, fs_isolator):
        """空路径应通过."""
        result = fs_isolator.validate_path("")
        assert result.allowed is True

    def test_working_directory_restriction(self):
        """工作目录限制应生效."""
        import tempfile
        with tempfile.TemporaryDirectory() as tmpdir:
            config = SandboxConfig(
                level=SANDBOX_LEVEL_BASIC,
                working_directory=tmpdir,
            )
            isolator = FileSystemIsolator(config)
            # 工作目录内的路径应通过
            inner_path = os.path.join(tmpdir, "data.txt")
            result = isolator.validate_path(inner_path)
            assert result.allowed is True

    def test_working_directory_escape_fails(self):
        """逃出工作目录应失败."""
        import tempfile
        with tempfile.TemporaryDirectory() as tmpdir:
            config = SandboxConfig(
                level=SANDBOX_LEVEL_BASIC,
                working_directory=tmpdir,
            )
            isolator = FileSystemIsolator(config)
            # 工作目录外的路径应失败
            outer_path = os.path.join(os.path.dirname(tmpdir), "outside.txt")
            result = isolator.validate_path(outer_path)
            assert result.allowed is False


# ============================================================
# 五、沙箱执行器测试
# ============================================================

class TestSandboxedExecutor:
    """沙箱执行器测试."""

    def test_execute_success(self, sandbox_executor):
        """正常执行应成功."""
        def my_func(args):
            return {"result": args.get("x", 0) * 2}

        success, result, error = sandbox_executor.execute(
            tool_name="test_tool",
            arguments={"x": 21},
            actual_executor=my_func,
        )
        assert success is True
        assert result == {"result": 42}
        assert error == ""

    def test_execute_with_dangerous_param_blocked(self, sandbox_executor):
        """危险参数应被拦截."""
        def my_func(args):
            return args

        success, result, error = sandbox_executor.execute(
            tool_name="test_tool",
            arguments={"cmd": "eval('1+1')"},
            actual_executor=my_func,
        )
        assert success is False
        assert result is None
        assert len(error) > 0

    def test_execute_with_command_injection_blocked(self, sandbox_executor):
        """命令注入应被拦截."""
        def my_func(args):
            return args

        success, result, error = sandbox_executor.execute(
            tool_name="test_tool",
            arguments={"input": "hello; rm -rf /"},
            actual_executor=my_func,
        )
        assert success is False

    def test_execute_level_unlimited_passes_everything(self, basic_config):
        """Level 0 应放行所有请求."""
        basic_config.level = SANDBOX_LEVEL_UNLIMITED
        executor = SandboxedExecutor(basic_config)

        def my_func(args):
            return args

        # 即使包含危险内容也应通过
        success, result, error = executor.execute(
            tool_name="test_tool",
            arguments={"cmd": "eval('1+1'); os.system('ls')"},
            actual_executor=my_func,
        )
        assert success is True

    def test_execute_level_strict_concurrency(self, basic_config):
        """Level 2 应有并发限制."""
        basic_config.level = SANDBOX_LEVEL_STRICT
        basic_config.max_concurrent_executions = 2
        executor = SandboxedExecutor(basic_config)

        def slow_func(args):
            time.sleep(0.01)
            return "done"

        # 前两个应通过
        import threading
        results = []
        errors = []
        locks = []

        def run_with_lock():
            success, result, error = executor.execute(
                tool_name="slow_tool",
                arguments={},
                actual_executor=slow_func,
            )
            results.append(success)
            errors.append(error)

        threads = [threading.Thread(target=run_with_lock) for _ in range(2)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert all(results)

    def test_output_size_limit_blocked(self, basic_config):
        """输出超过大小限制应被拦截."""
        basic_config.max_output_size = 100  # 100 字节
        executor = SandboxedExecutor(basic_config)

        def big_output(args):
            return {"data": "x" * 1000}

        success, result, error = executor.execute(
            tool_name="big_tool",
            arguments={},
            actual_executor=big_output,
        )
        assert success is False
        assert "输出大小" in error

    def test_validate_only_passes(self, sandbox_executor):
        """仅校验模式应只检查不执行."""
        result = sandbox_executor.validate_only(
            tool_name="test_tool",
            arguments={"name": "hello", "count": 10},
        )
        assert result.allowed is True

    def test_validate_only_blocked(self, sandbox_executor):
        """仅校验模式应能检测到危险."""
        result = sandbox_executor.validate_only(
            tool_name="test_tool",
            arguments={"cmd": "eval('malicious')"},
        )
        assert result.allowed is False

    def test_tool_blacklist_blocked(self, basic_config):
        """黑名单工具应被拦截."""
        basic_config.tool_blacklist = ["dangerous_tool"]
        executor = SandboxedExecutor(basic_config)

        def my_func(args):
            return args

        success, result, error = executor.execute(
            tool_name="dangerous_tool",
            arguments={},
            actual_executor=my_func,
        )
        assert success is False
        assert "黑名单" in error

    def test_tool_whitelist_blocked(self, basic_config):
        """不在白名单中的工具应被拦截."""
        basic_config.tool_whitelist = ["allowed_tool"]
        executor = SandboxedExecutor(basic_config)

        def my_func(args):
            return args

        success, result, error = executor.execute(
            tool_name="other_tool",
            arguments={},
            actual_executor=my_func,
        )
        assert success is False
        assert "白名单" in error

    def test_tool_whitelist_passes(self, basic_config):
        """白名单中的工具应通过."""
        basic_config.tool_whitelist = ["allowed_tool"]
        executor = SandboxedExecutor(basic_config)

        def my_func(args):
            return args

        success, result, error = executor.execute(
            tool_name="allowed_tool",
            arguments={"key": "value"},
            actual_executor=my_func,
        )
        assert success is True

    def test_tool_whitelist_wildcard(self, basic_config):
        """白名单通配符应生效."""
        basic_config.tool_whitelist = ["safe_*"]
        executor = SandboxedExecutor(basic_config)

        def my_func(args):
            return args

        success, result, error = executor.execute(
            tool_name="safe_read_file",
            arguments={"path": "data.txt"},
            actual_executor=my_func,
        )
        assert success is True


# ============================================================
# 六、沙箱管理器测试
# ============================================================

class TestSandboxManager:
    """沙箱管理器测试."""

    def test_singleton(self, sandbox_manager):
        """沙箱管理器应为单例."""
        m1 = SandboxManager.get_instance()
        m2 = SandboxManager.get_instance()
        assert m1 is m2

    def test_reset_instance(self):
        """重置单例应创建新实例."""
        m1 = SandboxManager.get_instance()
        SandboxManager.reset_instance()
        m2 = SandboxManager.get_instance()
        assert m1 is not m2
        SandboxManager.reset_instance()

    def test_set_level(self, sandbox_manager):
        """设置沙箱级别应生效."""
        sandbox_manager.set_level(SANDBOX_LEVEL_STRICT)
        assert sandbox_manager.config.level == SANDBOX_LEVEL_STRICT

    def test_set_invalid_level_fails(self, sandbox_manager):
        """设置无效级别应抛出异常."""
        with pytest.raises(ValueError):
            sandbox_manager.set_level(999)

    def test_add_remove_whitelist(self, sandbox_manager):
        """白名单增删应生效."""
        sandbox_manager.add_to_whitelist("test_tool")
        assert "test_tool" in sandbox_manager.config.tool_whitelist

        sandbox_manager.remove_from_whitelist("test_tool")
        assert "test_tool" not in sandbox_manager.config.tool_whitelist

    def test_add_remove_blacklist(self, sandbox_manager):
        """黑名单增删应生效."""
        sandbox_manager.add_to_blacklist("bad_tool")
        assert "bad_tool" in sandbox_manager.config.tool_blacklist

        sandbox_manager.remove_from_blacklist("bad_tool")
        assert "bad_tool" not in sandbox_manager.config.tool_blacklist

    def test_stats_initial(self, sandbox_manager):
        """初始统计应为零."""
        stats = sandbox_manager.get_stats()
        assert stats["total_executions"] == 0
        assert stats["blocked_executions"] == 0

    def test_stats_update_after_execution(self, sandbox_manager):
        """执行后统计应更新."""
        executor = sandbox_manager.get_executor()

        def my_func(args):
            return {"ok": True}

        executor.execute(
            tool_name="stat_test",
            arguments={"x": 1},
            actual_executor=my_func,
        )

        stats = sandbox_manager.get_stats()
        assert stats["total_executions"] == 1
        assert stats["blocked_executions"] == 0

    def test_stats_blocked(self, sandbox_manager):
        """拦截后统计应更新."""
        # 设置黑名单
        sandbox_manager.add_to_blacklist("blocked_tool")
        executor = sandbox_manager.get_executor()

        def my_func(args):
            return args

        executor.execute(
            tool_name="blocked_tool",
            arguments={},
            actual_executor=my_func,
        )

        stats = sandbox_manager.get_stats()
        assert stats["total_executions"] == 1
        assert stats["blocked_executions"] == 1

    def test_tool_stats(self, sandbox_manager):
        """工具级别统计应正确."""
        executor = sandbox_manager.get_executor()

        def my_func(args):
            return args

        for i in range(3):
            executor.execute(
                tool_name="tool_a",
                arguments={"i": i},
                actual_executor=my_func,
            )

        tool_stats = sandbox_manager.get_tool_stats("tool_a")
        assert tool_stats["total"] == 3
        assert tool_stats["blocked"] == 0

    def test_alert_callback(self, sandbox_manager):
        """告警回调应被调用."""
        alerts = []

        def on_alert(alert_type, details):
            alerts.append((alert_type, details))

        sandbox_manager.register_alert_callback(on_alert)
        sandbox_manager.add_to_blacklist("alert_test")
        executor = sandbox_manager.get_executor()

        def my_func(args):
            return args

        executor.execute(
            tool_name="alert_test",
            arguments={},
            actual_executor=my_func,
        )

        assert len(alerts) > 0
        assert alerts[0][0] == "tool_blacklisted"

    def test_audit_callback(self, sandbox_manager):
        """审计回调应被调用."""
        audit_logs = []

        def on_audit(context):
            audit_logs.append(context)

        sandbox_manager.register_audit_callback(on_audit)
        executor = sandbox_manager.get_executor()

        def my_func(args):
            return {"ok": True}

        executor.execute(
            tool_name="audit_test",
            arguments={"data": "test"},
            actual_executor=my_func,
            caller="test_user",
        )

        assert len(audit_logs) == 1
        assert audit_logs[0].tool_name == "audit_test"
        assert audit_logs[0].caller == "test_user"
        assert audit_logs[0].blocked is False

    def test_reset_stats(self, sandbox_manager):
        """重置统计应清零."""
        executor = sandbox_manager.get_executor()

        def my_func(args):
            return args

        executor.execute(
            tool_name="reset_test",
            arguments={},
            actual_executor=my_func,
        )

        assert sandbox_manager.get_stats()["total_executions"] == 1
        sandbox_manager.reset_stats()
        assert sandbox_manager.get_stats()["total_executions"] == 0


# ============================================================
# 七、向后兼容测试
# ============================================================

class TestBackwardCompatibility:
    """向后兼容测试."""

    def test_sandbox_config_default_level(self):
        """默认沙箱级别应为 Level 1（基础隔离）."""
        config = SandboxConfig()
        assert config.level == SANDBOX_LEVEL_BASIC
        assert config.level == DEFAULT_SANDBOX_LEVEL

    def test_sandbox_manager_default_level(self):
        """沙箱管理器默认级别应为 Level 1."""
        SandboxManager.reset_instance()
        manager = SandboxManager.get_instance()
        try:
            assert manager.config.level == SANDBOX_LEVEL_BASIC
        finally:
            SandboxManager.reset_instance()

    def test_existing_tools_not_affected(self, basic_config):
        """现有工具（非黑名单/白名单）应正常工作."""
        executor = SandboxedExecutor(basic_config)

        def normal_func(args):
            return {"message": f"hello {args.get('name', 'world')}"}

        success, result, error = executor.execute(
            tool_name="existing.greet",
            arguments={"name": "Alice"},
            actual_executor=normal_func,
        )
        assert success is True
        assert result == {"message": "hello Alice"}

    def test_config_access_via_getattr(self):
        """配置应可通过 getattr 访问（向后兼容）."""
        config = SandboxConfig()
        # 所有配置项都应可访问
        assert hasattr(config, "level")
        assert hasattr(config, "timeout")
        assert hasattr(config, "max_output_size")
        assert hasattr(config, "tool_whitelist")
        assert hasattr(config, "tool_blacklist")

    def test_sandbox_does_not_break_normal_flow(self, basic_config):
        """沙箱不应破坏正常的工具调用流程."""
        executor = SandboxedExecutor(basic_config)

        call_count = 0

        def counter_func(args):
            nonlocal call_count
            call_count += 1
            return {"count": call_count}

        # 多次调用都应正常工作
        for i in range(5):
            success, result, error = executor.execute(
                tool_name="counter",
                arguments={"step": i},
                actual_executor=counter_func,
            )
            assert success is True
            assert result["count"] == i + 1

        assert call_count == 5

    def test_sandbox_can_be_disabled_via_level_0(self, basic_config):
        """Level 0 应完全禁用沙箱检查."""
        basic_config.level = SANDBOX_LEVEL_UNLIMITED
        executor = SandboxedExecutor(basic_config)

        def func(args):
            return args

        # 各种危险内容都应通过
        test_cases = [
            {"cmd": "eval('1+1')"},
            {"path": "../../etc/passwd"},
            {"url": "http://localhost/admin"},
        ]

        for args in test_cases:
            success, result, error = executor.execute(
                tool_name="test",
                arguments=args,
                actual_executor=func,
            )
            assert success is True, f"Level 0 应放行: {args}"


# ============================================================
# 八、配置默认值测试
# ============================================================

class TestSandboxConfigDefaults:
    """配置默认值测试."""

    def test_default_sandbox_level(self):
        """默认沙箱级别应为 1."""
        config = SandboxConfig()
        assert config.level == 1

    def test_default_timeout(self):
        """默认超时应为 30 秒."""
        config = SandboxConfig()
        assert config.timeout == 30

    def test_default_max_output_size(self):
        """默认最大输出应为 1MB."""
        config = SandboxConfig()
        assert config.max_output_size == 1024 * 1024

    def test_default_security_headers_enabled(self):
        """默认应启用安全响应头."""
        config = SandboxConfig()
        assert config.security_headers_enabled is True

    def test_dangerous_functions_not_empty(self):
        """危险函数列表不应为空."""
        assert len(DANGEROUS_FUNCTIONS) > 0
        assert "eval" in DANGEROUS_FUNCTIONS
        assert "exec" in DANGEROUS_FUNCTIONS

    def test_sensitive_path_patterns_not_empty(self):
        """敏感路径模式不应为空."""
        assert len(SENSITIVE_PATH_PATTERNS) > 0

    def test_command_injection_patterns_not_empty(self):
        """命令注入模式不应为空."""
        assert len(COMMAND_INJECTION_PATTERNS) > 0

    def test_ssrf_blocked_patterns_not_empty(self):
        """SSRF 防护模式不应为空."""
        assert len(SSRF_BLOCKED_PATTERNS) > 0


# ============================================================
# 九、SandboxResult 测试
# ============================================================

class TestSandboxResult:
    """SandboxResult 测试."""

    def test_bool_true_when_allowed(self):
        """allowed 为 True 时 bool 应为 True."""
        result = SandboxResult(allowed=True)
        assert bool(result) is True

    def test_bool_false_when_blocked(self):
        """allowed 为 False 时 bool 应为 False."""
        result = SandboxResult(allowed=False, reason="test")
        assert bool(result) is False

    def test_default_values(self):
        """默认值应正确."""
        result = SandboxResult(allowed=True)
        assert result.reason == ""
        assert result.blocked_by == ""
        assert result.details == {}


# ============================================================
# 十、安全中间件配置测试
# ============================================================

class TestSecurityMiddlewareConfig:
    """安全中间件配置测试."""

    def test_import_security_middleware(self):
        """应能导入安全中间件模块."""
        from src.middleware.security_middleware import (
            DEFAULT_MAX_REQUEST_SIZE,
            DEFAULT_SECURITY_HEADERS,
            SecurityMiddleware,
            SecurityMiddlewareConfig,
        )
        assert SecurityMiddleware is not None
        assert SecurityMiddlewareConfig is not None
        assert len(DEFAULT_SECURITY_HEADERS) > 0
        assert DEFAULT_MAX_REQUEST_SIZE > 0

    def test_security_headers_include_important_ones(self):
        """安全响应头应包含关键头."""
        from src.middleware.security_middleware import DEFAULT_SECURITY_HEADERS

        important_headers = [
            "X-Content-Type-Options",
            "X-Frame-Options",
            "Content-Security-Policy",
            "Strict-Transport-Security",
            "Referrer-Policy",
        ]
        for header in important_headers:
            assert header in DEFAULT_SECURITY_HEADERS, f"缺少安全头: {header}"

    def test_middleware_config_defaults(self):
        """中间件配置默认值应正确."""
        from src.middleware.security_middleware import SecurityMiddlewareConfig

        config = SecurityMiddlewareConfig()
        assert config.security_headers_enabled is True
        assert config.max_request_size > 0
        assert len(config.allowed_methods) > 0
        assert config.request_id_enabled is True
