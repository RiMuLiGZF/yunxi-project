from __future__ import annotations

import pytest

from skill_cluster.sandbox import (
    SandboxConfig,
    SandboxExecutor,
    SandboxPolicy,
    create_sandbox_middleware,
)


def test_sandbox_policy_allowed() -> None:
    policy = SandboxPolicy(SandboxConfig())
    ok, err = policy.check_code("x = 1 + 2\nprint(x)")
    assert ok is True
    assert err is None


def test_sandbox_policy_blocks_import() -> None:
    policy = SandboxPolicy(SandboxConfig())
    ok, err = policy.check_code("import os\nos.system('ls')")
    assert ok is False
    assert "os" in (err or "")


def test_sandbox_policy_blocks_eval() -> None:
    policy = SandboxPolicy(SandboxConfig())
    ok, err = policy.check_code("eval('1+1')")
    assert ok is False
    assert "eval" in (err or "")


def test_sandbox_policy_allows_whitelisted() -> None:
    config = SandboxConfig(
        allowed_modules=["json"],
        blocked_modules=[],
    )
    policy = SandboxPolicy(config)
    ok, err = policy.check_code("import json\njson.dumps({})")
    assert ok is True


def test_sandbox_policy_blocks_non_whitelisted() -> None:
    config = SandboxConfig(
        allowed_modules=["json"],
        blocked_modules=[],
    )
    policy = SandboxPolicy(config)
    ok, err = policy.check_code("import os")
    assert ok is False


def test_sandbox_executor_success() -> None:
    executor = SandboxExecutor(SandboxConfig(timeout_seconds=5))
    code = "output = {'sum': 1 + 2}"
    result = executor.execute(code)

    assert result.status == "success"
    assert result.data is not None
    assert result.data["output"] == {"sum": 3}


def test_sandbox_executor_uses_input_data() -> None:
    executor = SandboxExecutor(SandboxConfig(timeout_seconds=5))
    code = "output = {'value': input_data['x'] * 2}"
    result = executor.execute(code, input_data={"x": 5})

    assert result.status == "success"
    assert result.data["output"] == {"value": 10}


def test_sandbox_executor_blocks_bad_import() -> None:
    executor = SandboxExecutor(SandboxConfig(timeout_seconds=5))
    code = "import os\noutput = 1"
    result = executor.execute(code)

    assert result.status == "failure"
    assert "Security check failed" in (result.error or "")


def test_sandbox_executor_timeout() -> None:
    executor = SandboxExecutor(SandboxConfig(timeout_seconds=1))
    code = "import time\ntime.sleep(10)\noutput = 1"
    result = executor.execute(code)

    assert result.status == "failure"
    assert "timed out" in (result.error or "") or "Timeout" in (result.error or "")


def test_sandbox_executor_syntax_error() -> None:
    executor = SandboxExecutor(SandboxConfig(timeout_seconds=5))
    code = "if true:\n    print(1"
    result = executor.execute(code)

    assert result.status == "failure"
    assert "Syntax" in (result.error or "") or "invalid" in (result.error or "").lower()


def test_sandbox_executor_runtime_error() -> None:
    executor = SandboxExecutor(SandboxConfig(timeout_seconds=5))
    code = "output = 1 / 0"
    result = executor.execute(code)

    assert result.status == "failure"
    # 除以零在子进程中触发异常
    assert result.error is not None


def test_sandbox_policy_blocks_getattr_dunder():
    """第二轮优化：防护 getattr(__builtins__, '__import__') 绕过."""
    policy = SandboxPolicy(SandboxConfig())
    ok, err = policy.check_code("getattr(__builtins__, '__import__')")
    assert ok is False
    assert "dunder" in (err or "")


def test_sandbox_policy_blocks_getattr_exec():
    policy = SandboxPolicy(SandboxConfig())
    ok, err = policy.check_code("getattr(builtins, '__import__')")
    assert ok is False


def test_sandbox_policy_default_whitelist():
    """第二轮优化：默认使用白名单，未列出的模块被拒绝."""
    policy = SandboxPolicy(SandboxConfig(blocked_modules=[]))
    # os 不在默认白名单中
    ok, err = policy.check_code("import os")
    assert ok is False
    # math 在默认白名单中
    ok2, err2 = policy.check_code("import math\nx = math.sqrt(4)")
    assert ok2 is True


def test_create_sandbox_middleware() -> None:
    mw = create_sandbox_middleware()
    assert isinstance(mw, type(create_sandbox_middleware()).__bases__[0])
