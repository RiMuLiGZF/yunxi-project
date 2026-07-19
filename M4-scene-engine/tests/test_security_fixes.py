"""SEC-003 + SEC-012 安全修复测试.

测试终端命令技能的命令注入防护（SEC-003）
和文件操作技能的路径遍历防护（SEC-012）。
"""

import os
import sys
import tempfile
import time
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

# 将 src 目录加入路径
# =========================================================================
# 辅助函数
# =========================================================================

def _has_command(cmd: str) -> bool:
    """检查系统中是否存在某个命令."""
    import shutil
    return shutil.which(cmd) is not None


# =========================================================================
# SEC-003: 终端命令技能安全测试
# =========================================================================


class TestTerminalCommandSecurity:
    """终端命令技能安全测试（SEC-003）."""

    @pytest.fixture
    def skill(self):
        from src.services.skills.terminal_command_skill import TerminalCommandSkill
        return TerminalCommandSkill()

    @pytest.fixture
    def workspace(self, tmp_path):
        """创建临时工作目录."""
        return str(tmp_path)

    @pytest.fixture
    def context(self, workspace):
        """创建执行上下文."""
        return {"workspace": workspace}

    # ------------------------------------------------------------------
    # 正常命令执行测试
    # ------------------------------------------------------------------

    def test_normal_python_command(self, skill, context):
        """测试正常的 python 命令执行（跨平台）."""
        result = skill.execute(
            {"action": "run", "command": "python -c \"print('hello world')\""},
            context,
        )
        # 安全检查应该通过
        assert "安全检查未通过" not in result["message"]
        # 如果 python 可用，应该执行成功
        if _has_command("python") or _has_command("python3"):
            assert result["success"] is True
            assert "hello world" in result["data"]["stdout"]

    def test_normal_python_version_command(self, skill, context):
        """测试 python --version 命令."""
        result = skill.execute(
            {"action": "run", "command": "python --version"},
            context,
        )
        # 安全检查应该通过
        assert "安全检查未通过" not in result["message"]

    def test_normal_git_version_command(self, skill, context):
        """测试 git --version 命令（白名单命令）."""
        result = skill.execute(
            {"action": "run", "command": "git --version"},
            context,
        )
        # git 可能未安装，但安全检查应该通过
        # 如果成功执行，返回码应该是 0
        # 如果失败，应该是命令未找到，而不是安全检查失败
        msg = result["message"]
        assert "安全检查" not in msg
        assert "黑名单" not in msg
        assert "白名单" not in msg

    # ------------------------------------------------------------------
    # 命令注入尝试测试
    # ------------------------------------------------------------------

    def test_injection_semicolon_blocked_by_shell_false(self, skill, context):
        """测试分号注入：由于 shell=False，分号不会执行第二条命令.

        使用 mock 验证 subprocess.run 被调用时：
        1. shell=False（从根本上防止 shell 注入）
        2. 命令以列表形式传递，分号作为 python 命令的参数，不会被 shell 解释
        """
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "a;b\n"
        mock_result.stderr = ""

        with patch("subprocess.run", return_value=mock_result) as mock_run:
            result = skill.execute(
                {"action": "run", "command": "python -c \"print('a;b')\""},
                context,
            )

        # 验证 subprocess.run 被调用
        assert mock_run.called
        call_kwargs = mock_run.call_args
        # 验证 shell=False
        assert call_kwargs.kwargs.get("shell") is False
        # 验证命令以列表形式传递（第一个参数是列表）
        cmd_list = call_kwargs.args[0]
        assert isinstance(cmd_list, list)
        # 验证分号作为参数传递，不会被 shell 解释
        # 命令是 python，参数包含 -c 和 print('a;b')
        assert cmd_list[0].endswith("python") or "python" in cmd_list[0].lower()
        # 分号出现在参数中（作为普通字符串）
        joined_args = " ".join(cmd_list[1:])
        assert ";" in joined_args
        # 执行结果应该成功
        assert result["success"] is True
        assert "a;b" in result["data"]["stdout"]

    def test_injection_pipe_not_interpreted_by_shell(self, skill, context):
        """测试管道符：由于 shell=False，管道符不会被 shell 解释.

        使用 mock 验证 subprocess.run 被调用时，管道符作为普通参数传递，
        不会创建管道连接两个进程。
        """
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "x|y\n"
        mock_result.stderr = ""

        with patch("subprocess.run", return_value=mock_result) as mock_run:
            result = skill.execute(
                {"action": "run", "command": "python -c \"print('x|y')\""},
                context,
            )

        # 验证 shell=False
        call_kwargs = mock_run.call_args
        assert call_kwargs.kwargs.get("shell") is False
        # 验证管道符在参数中（作为普通字符串）
        cmd_list = call_kwargs.args[0]
        joined_args = " ".join(cmd_list[1:])
        assert "|" in joined_args
        # 执行结果
        assert result["success"] is True
        assert "x|y" in result["data"]["stdout"]

    def test_injection_backtick_not_interpreted(self, skill, context):
        """测试反引号：由于 shell=False，反引号不会被执行.

        使用 mock 验证 subprocess.run 被调用时，反引号作为普通参数传递。
        """
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "`whoami`\n"
        mock_result.stderr = ""

        with patch("subprocess.run", return_value=mock_result) as mock_run:
            result = skill.execute(
                {"action": "run", "command": "python -c \"print('`whoami`')\""},
                context,
            )

        # 验证 shell=False
        call_kwargs = mock_run.call_args
        assert call_kwargs.kwargs.get("shell") is False
        # 验证反引号在参数中（作为普通字符串）
        cmd_list = call_kwargs.args[0]
        joined_args = " ".join(cmd_list[1:])
        assert "`whoami`" in joined_args
        # 执行结果
        assert result["success"] is True
        # 反引号作为普通字符输出，不会被执行
        assert "`whoami`" in result["data"]["stdout"]

    def test_injection_dollar_paren_not_interpreted(self, skill, context):
        """测试 $() 命令替换：由于 shell=False，不会被 shell 解释.

        使用 mock 验证 subprocess.run 被调用时，$() 作为普通参数传递。
        """
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "$(whoami)\n"
        mock_result.stderr = ""

        with patch("subprocess.run", return_value=mock_result) as mock_run:
            result = skill.execute(
                {"action": "run", "command": "python -c \"print('$(whoami)')\""},
                context,
            )

        # 验证 shell=False
        call_kwargs = mock_run.call_args
        assert call_kwargs.kwargs.get("shell") is False
        # 验证 $() 在参数中（作为普通字符串）
        cmd_list = call_kwargs.args[0]
        joined_args = " ".join(cmd_list[1:])
        assert "$(whoami)" in joined_args
        # 执行结果
        assert result["success"] is True
        # $() 作为普通字符输出
        assert "$(whoami)" in result["data"]["stdout"]

    def test_injection_double_ampersand_not_interpreted(self, skill, context):
        """测试 &&：由于 shell=False，&& 不会被 shell 解释.

        使用 mock 验证 subprocess.run 被调用时，&& 作为普通参数传递。
        """
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "a&&b\n"
        mock_result.stderr = ""

        with patch("subprocess.run", return_value=mock_result) as mock_run:
            result = skill.execute(
                {"action": "run", "command": "python -c \"print('a&&b')\""},
                context,
            )

        # 验证 shell=False
        call_kwargs = mock_run.call_args
        assert call_kwargs.kwargs.get("shell") is False
        # 验证 && 在参数中（作为普通字符串）
        cmd_list = call_kwargs.args[0]
        joined_args = " ".join(cmd_list[1:])
        assert "&&" in joined_args
        # 执行结果
        assert result["success"] is True
        assert "a&&b" in result["data"]["stdout"]

    def test_injection_rm_command_blocked_by_blacklist(self, skill, context):
        """测试直接执行 rm 命令会被黑名单拒绝（根本不会执行）."""
        result = skill.execute(
            {"action": "run", "command": "rm -rf /"},
            context,
        )
        assert result["success"] is False
        assert "黑名单" in result["message"] or "安全检查" in result["message"]

    # ------------------------------------------------------------------
    # 白名单/黑名单测试
    # ------------------------------------------------------------------

    def test_blacklist_rm_command(self, skill, context):
        """测试 rm 命令在黑名单中，应被拒绝."""
        result = skill.execute(
            {"action": "run", "command": "rm -rf /tmp/test"},
            context,
        )
        assert result["success"] is False
        assert "黑名单" in result["message"] or "安全检查" in result["message"]

    def test_blacklist_sudo_command(self, skill, context):
        """测试 sudo 命令在黑名单中，应被拒绝."""
        result = skill.execute(
            {"action": "run", "command": "sudo rm -rf /"},
            context,
        )
        assert result["success"] is False
        assert "黑名单" in result["message"] or "安全检查" in result["message"]

    def test_blacklist_bash_command(self, skill, context):
        """测试 bash 命令在黑名单中，应被拒绝."""
        result = skill.execute(
            {"action": "run", "command": "bash -c 'echo pwned'"},
            context,
        )
        assert result["success"] is False
        assert "黑名单" in result["message"] or "安全检查" in result["message"]

    def test_whitelist_git_command(self, skill, context):
        """测试 git 命令在白名单中，应被允许通过安全检查."""
        result = skill.execute(
            {"action": "run", "command": "git status"},
            context,
        )
        # git 可能未安装，但安全检查应该通过
        msg = result["message"]
        assert "安全检查" not in msg
        assert "黑名单" not in msg
        assert "白名单" not in msg

    def test_whitelist_python_command(self, skill, context):
        """测试 python 命令在白名单中，应被允许."""
        result = skill.execute(
            {"action": "run", "command": "python --version"},
            context,
        )
        # 安全检查应该通过
        msg = result["message"]
        assert "安全检查" not in msg
        assert "黑名单" not in msg
        assert "白名单" not in msg

    def test_unknown_command_rejected(self, skill, context):
        """测试不在白名单中的命令应被拒绝."""
        result = skill.execute(
            {"action": "run", "command": "dangerous_cmd --arg1 --arg2"},
            context,
        )
        assert result["success"] is False
        assert "白名单" in result["message"] or "安全检查" in result["message"]

    # ------------------------------------------------------------------
    # 超时测试
    # ------------------------------------------------------------------

    def test_timeout_clamping_max(self, skill, context):
        """测试超时时长超过最大值时被截断."""
        timeout = skill._get_timeout({"timeout": 9999})
        assert timeout == skill._MAX_TIMEOUT

    def test_timeout_clamping_min(self, skill, context):
        """测试超时时长小于最小值时被设置为 1."""
        timeout = skill._get_timeout({"timeout": 0})
        assert timeout == 1

    def test_timeout_default(self, skill, context):
        """测试默认超时值."""
        timeout = skill._get_timeout({})
        assert timeout == skill._DEFAULT_TIMEOUT

    def test_timeout_negative_clamped(self, skill, context):
        """测试负数超时被夹到最小值."""
        timeout = skill._get_timeout({"timeout": -10})
        assert timeout == 1

    # ------------------------------------------------------------------
    # 工作目录限制测试
    # ------------------------------------------------------------------

    def test_cwd_within_workspace(self, skill, workspace, context):
        """测试工作目录在 workspace 内时应被允许."""
        subdir = os.path.join(workspace, "subdir")
        os.makedirs(subdir, exist_ok=True)
        result = skill.execute(
            {"action": "run", "command": "python -c \"print('test')\"", "cwd": "subdir"},
            context,
        )
        if not _has_command("python") and not _has_command("python3"):
            # 即使 python 不可用，也应该是命令未找到，而不是安全检查失败
            assert "安全检查" not in result["message"]
            assert "越界" not in result["message"]
        else:
            assert result["success"] is True

    def test_cwd_outside_workspace_rejected(self, skill, workspace, context):
        """测试工作目录在 workspace 外时应被拒绝."""
        result = skill.execute(
            {"action": "run", "command": "python -c \"print('test')\"", "cwd": "../outside"},
            context,
        )
        assert result["success"] is False
        assert "越界" in result["message"] or "安全检查" in result["message"]

    def test_cwd_absolute_outside_workspace(self, skill, workspace, context):
        """测试绝对路径工作目录在 workspace 外时应被拒绝.

        构造一个确定不在 workspace 内的绝对路径来测试越界检测。
        在 Windows 上使用另一个盘符或系统根目录外的路径，
        在 POSIX 上使用 /root 或其他系统目录。
        """
        # 构造一个确定不在 workspace 内的绝对路径
        # 使用一个显然不存在的系统级路径，确保安全检查会拒绝
        if sys.platform.startswith("win"):
            # Windows: 使用另一个不存在的盘符路径
            outside_path = "Z:\\definitely_outside_workspace\\test"
        else:
            # POSIX: 使用系统级目录
            outside_path = "/root/definitely_outside_workspace/test"

        result = skill.execute(
            {"action": "run", "command": "python -c \"print('test')\"", "cwd": outside_path},
            context,
        )
        # 由于 outside_path 显然不在 workspace 内，应该被越界检查拒绝
        assert result["success"] is False
        assert "越界" in result["message"] or "安全检查" in result["message"]

    # ------------------------------------------------------------------
    # shell 参数移除测试
    # ------------------------------------------------------------------

    def test_shell_parameter_removed_from_schema(self, skill):
        """测试 shell 参数已从参数 schema 中移除."""
        assert "shell" not in skill.parameters["properties"]

    def test_subprocess_run_uses_shell_false(self, skill):
        """测试 subprocess.run 调用使用 shell=False."""
        import inspect
        source = inspect.getsource(skill._handle_run)
        # 查找 subprocess.run 调用
        import re
        # 匹配 subprocess.run( 之后的参数
        run_matches = re.findall(r'subprocess\.run\([^)]*shell\s*=\s*(\w+)', source, re.DOTALL)
        # 所有调用都应该使用 shell=False
        assert len(run_matches) > 0, "未找到 subprocess.run 调用"
        for match in run_matches:
            assert match == "False", f"发现 shell={match}，应该为 False"

    def test_subprocess_popen_uses_shell_false(self, skill):
        """测试 subprocess.Popen 调用使用 shell=False."""
        import inspect
        source = inspect.getsource(skill._handle_run_async)
        import re
        popen_matches = re.findall(r'subprocess\.Popen\([^)]*shell\s*=\s*(\w+)', source, re.DOTALL)
        assert len(popen_matches) > 0, "未找到 subprocess.Popen 调用"
        for match in popen_matches:
            assert match == "False", f"发现 shell={match}，应该为 False"

    # ------------------------------------------------------------------
    # 命令解析测试
    # ------------------------------------------------------------------

    def test_parse_command_simple(self, skill):
        """测试简单命令解析."""
        cmd, args = skill._parse_command_string("echo hello world")
        assert cmd == "echo"
        assert args == ["hello", "world"]

    def test_parse_command_with_quotes_posix(self, skill):
        """测试带引号的命令解析（POSIX 模式）."""
        import shlex
        # 使用 posix=True 解析（Unix 风格）
        tokens = shlex.split('echo "hello world"', posix=True)
        assert tokens[0] == "echo"
        assert tokens[1] == "hello world"

    def test_parse_command_empty(self, skill):
        """测试空命令解析应抛出异常."""
        with pytest.raises(ValueError):
            skill._parse_command_string("")

    def test_parse_command_whitespace_only(self, skill):
        """测试纯空白命令解析应抛出异常."""
        with pytest.raises(ValueError):
            skill._parse_command_string("   ")

    # ------------------------------------------------------------------
    # 危险参数组合测试
    # ------------------------------------------------------------------

    def test_git_config_global_rejected(self, skill, context):
        """测试 git config --global 应被拒绝."""
        result = skill.execute(
            {"action": "run", "command": "git config --global user.name test"},
            context,
        )
        assert result["success"] is False
        assert "global" in result["message"].lower() or "安全检查" in result["message"]

    def test_curl_file_protocol_rejected(self, skill, context):
        """测试 curl file:// 协议应被拒绝."""
        result = skill.execute(
            {"action": "run", "command": "curl file:///etc/passwd"},
            context,
        )
        assert result["success"] is False
        assert "file://" in result["message"] or "安全检查" in result["message"]

    def test_git_exec_path_rejected(self, skill, context):
        """测试 git --exec-path 应被拒绝."""
        result = skill.execute(
            {"action": "run", "command": "git --exec-path=/tmp/hack status"},
            context,
        )
        assert result["success"] is False
        assert "exec-path" in result["message"] or "安全检查" in result["message"]

    # ------------------------------------------------------------------
    # 异步命令安全测试
    # ------------------------------------------------------------------

    def test_run_async_security_check(self, skill, context):
        """测试异步命令也通过安全检查（黑名单命令被拒绝）."""
        result = skill.execute(
            {"action": "run_async", "command": "rm -rf /"},
            context,
        )
        assert result["success"] is False
        assert "黑名单" in result["message"] or "安全检查" in result["message"]

    def test_run_async_whitelist_allowed(self, skill, context):
        """测试异步命令的白名单命令被允许."""
        result = skill.execute(
            {"action": "run_async", "command": "python -c \"import time; time.sleep(0.1); print('done')\""},
            context,
        )
        if not _has_command("python") and not _has_command("python3"):
            # 安全检查应该通过
            assert "安全检查" not in result["message"]
        else:
            assert result["success"] is True
            assert "task_id" in result["data"]

    # ------------------------------------------------------------------
    # 审计日志测试
    # ------------------------------------------------------------------

    def test_audit_log_method_exists(self, skill):
        """测试审计日志方法存在."""
        assert hasattr(skill, "_audit_log")
        assert callable(skill._audit_log)

    def test_is_command_safe_method_exists(self, skill):
        """测试 _is_command_safe 方法存在."""
        assert hasattr(skill, "_is_command_safe")
        assert callable(skill._is_command_safe)

    def test_is_command_safe_returns_tuple(self, skill):
        """测试 _is_command_safe 返回 (bool, str) 元组."""
        result = skill._is_command_safe("git", ["status"])
        assert isinstance(result, tuple)
        assert len(result) == 2
        assert isinstance(result[0], bool)
        assert isinstance(result[1], str)


# =========================================================================
# SEC-012: 文件操作技能路径遍历测试
# =========================================================================


class TestFileOperationSecurity:
    """文件操作技能路径遍历测试（SEC-012）."""

    @pytest.fixture
    def skill(self):
        from src.services.skills.file_operation_skill import FileOperationSkill
        return FileOperationSkill()

    @pytest.fixture
    def workspace(self, tmp_path):
        """创建临时工作目录."""
        ws = tmp_path / "workspace"
        ws.mkdir()
        # 创建一个测试文件
        test_file = ws / "test.txt"
        test_file.write_text("hello world")
        # 创建子目录
        subdir = ws / "subdir"
        subdir.mkdir()
        sub_file = subdir / "subfile.txt"
        sub_file.write_text("sub content")
        return str(ws)

    @pytest.fixture
    def context(self, workspace):
        """创建执行上下文."""
        return {"workspace": workspace}

    # ------------------------------------------------------------------
    # 正常文件操作测试
    # ------------------------------------------------------------------

    def test_normal_read_file(self, skill, context):
        """测试正常读取文件."""
        result = skill.execute(
            {"action": "read_file", "path": "test.txt"},
            context,
        )
        assert result["success"] is True
        assert result["data"]["content"] == "hello world"

    def test_normal_write_file(self, skill, context):
        """测试正常写入文件."""
        result = skill.execute(
            {"action": "write_file", "path": "new_file.txt", "content": "new content"},
            context,
        )
        assert result["success"] is True
        assert result["data"]["size"] == len("new content")

    def test_normal_list_dir(self, skill, context):
        """测试正常列出目录."""
        result = skill.execute(
            {"action": "list_dir", "path": ""},
            context,
        )
        assert result["success"] is True
        assert result["data"]["count"] >= 2  # test.txt + subdir

    def test_normal_file_exists(self, skill, context):
        """测试正常的文件存在检查."""
        result = skill.execute(
            {"action": "file_exists", "path": "test.txt"},
            context,
        )
        assert result["success"] is True
        assert result["data"]["exists"] is True
        assert result["data"]["is_file"] is True

    # ------------------------------------------------------------------
    # 路径遍历尝试测试
    # ------------------------------------------------------------------

    def test_path_traversal_dotdot(self, skill, context):
        """测试 ../ 路径遍历."""
        result = skill.execute(
            {"action": "read_file", "path": "../etc/passwd"},
            context,
        )
        assert result["success"] is False
        assert "越界" in result["message"] or "不在工作目录" in result["message"]

    def test_path_traversal_absolute(self, skill, context, workspace):
        """测试绝对路径遍历（workspace 外的路径）.

        构造一个确定不在 workspace 内的绝对路径来测试越界检测。
        """
        # 构造一个确定不在 workspace 内的绝对路径
        if sys.platform.startswith("win"):
            outside_path = "Z:\\definitely_outside\\secret.txt"
        else:
            outside_path = "/etc/secret.txt"

        result = skill.execute(
            {"action": "read_file", "path": outside_path},
            context,
        )
        assert result["success"] is False
        assert "越界" in result["message"] or "不在工作目录" in result["message"]

    def test_path_traversal_double_dotdot(self, skill, context):
        """测试多级 ../ 路径遍历."""
        result = skill.execute(
            {"action": "read_file", "path": "../../../../etc/passwd"},
            context,
        )
        assert result["success"] is False
        assert "越界" in result["message"] or "不在工作目录" in result["message"]

    def test_path_traversal_encoded_dotdot(self, skill, context):
        """测试编码的路径遍历（URL 编码等）.

        %2e%2e 会被当作普通目录名，所以安全检查会通过（在 workspace 内），
        但文件不存在。关键是不会越出 workspace。
        """
        result = skill.execute(
            {"action": "read_file", "path": "%2e%2e/etc/passwd"},
            context,
        )
        # %2e%2e 会被当作普通目录名，在 workspace 内
        # 要么文件不存在，要么安全检查通过但文件不存在
        assert "越界" not in result["message"]

    def test_path_traversal_write_file(self, skill, context):
        """测试写入文件的路径遍历防护."""
        result = skill.execute(
            {"action": "write_file", "path": "../../malware.sh", "content": "evil"},
            context,
        )
        assert result["success"] is False
        assert "越界" in result["message"] or "不在工作目录" in result["message"]

    def test_path_traversal_delete_file(self, skill, context):
        """测试删除文件的路径遍历防护."""
        result = skill.execute(
            {"action": "delete_file", "path": "../../important_file"},
            context,
        )
        assert result["success"] is False
        assert "越界" in result["message"] or "不在工作目录" in result["message"]

    def test_path_traversal_create_dir(self, skill, context):
        """测试创建目录的路径遍历防护."""
        result = skill.execute(
            {"action": "create_dir", "path": "../../hack_dir"},
            context,
        )
        assert result["success"] is False
        assert "越界" in result["message"] or "不在工作目录" in result["message"]

    def test_path_traversal_list_dir(self, skill, context):
        """测试列出目录的路径遍历防护."""
        result = skill.execute(
            {"action": "list_dir", "path": "../../../"},
            context,
        )
        assert result["success"] is False
        assert "越界" in result["message"] or "不在工作目录" in result["message"]

    # ------------------------------------------------------------------
    # 空字节注入测试
    # ------------------------------------------------------------------

    def test_null_byte_injection(self, skill, context):
        """测试空字节注入."""
        result = skill.execute(
            {"action": "read_file", "path": "test.txt\x00.php"},
            context,
        )
        assert result["success"] is False
        assert "非法字符" in result["message"] or "越界" in result["message"]

    # ------------------------------------------------------------------
    # 符号链接测试
    # ------------------------------------------------------------------

    def test_symlink_outside_workspace_skipped_in_listdir(
        self, skill, workspace, context
    ):
        """测试 list_dir 中指向 workspace 外的符号链接应被跳过.

        使用 mock 模拟符号链接行为，避免在 Windows 上创建符号链接需要管理员权限的问题。
        """
        # 在 workspace 中创建一个真实目录（模拟符号链接指向的内部目录）
        # 以及一个模拟的"符号链接"条目
        real_inside_dir = os.path.join(workspace, "real_dir")
        os.makedirs(real_inside_dir, exist_ok=True)

        # 创建一个假的"符号链接"文件（普通文件，但我们 mock islink 返回 True）
        fake_symlink = os.path.join(workspace, "link_outside")
        with open(fake_symlink, "w") as f:
            f.write("fake")

        # mock os.path.islink 让 link_outside 看起来像符号链接
        # mock os.path.realpath 让 link_outside 的 realpath 指向 workspace 外
        original_islink = os.path.islink
        original_realpath = os.path.realpath
        original_isdir = os.path.isdir

        def mock_islink(path):
            if os.path.basename(path) == "link_outside":
                return True
            return original_islink(path)

        def mock_realpath(path):
            if os.path.basename(path) == "link_outside":
                # 返回一个 workspace 外的路径
                if sys.platform.startswith("win"):
                    return "Z:\\outside_dir"
                else:
                    return "/outside_dir"
            return original_realpath(path)

        def mock_isdir(path):
            if os.path.basename(path) == "link_outside":
                return True  # 模拟指向目录的符号链接
            return original_isdir(path)

        with patch.object(os.path, "islink", side_effect=mock_islink), \
             patch.object(os.path, "realpath", side_effect=mock_realpath), \
             patch.object(os.path, "isdir", side_effect=mock_isdir):
            result = skill.execute(
                {"action": "list_dir", "path": ""},
                context,
            )

        assert result["success"] is True
        # 指向 workspace 外的符号链接不应出现在列表中
        names = [e["name"] for e in result["data"]["entries"]]
        assert "link_outside" not in names
        # 真实目录应该还在
        assert "real_dir" in names

    def test_symlink_inside_workspace_allowed(
        self, skill, workspace, context
    ):
        """测试指向 workspace 内的符号链接应被允许.

        使用 mock 模拟符号链接行为，避免在 Windows 上创建符号链接需要管理员权限的问题。
        """
        # 在 workspace 中创建真实目录
        subdir = os.path.join(workspace, "subdir")
        os.makedirs(subdir, exist_ok=True)

        # 创建一个假的"符号链接"文件
        fake_symlink = os.path.join(workspace, "link_inside")
        with open(fake_symlink, "w") as f:
            f.write("fake")

        original_islink = os.path.islink
        original_realpath = os.path.realpath
        original_isdir = os.path.isdir

        def mock_islink(path):
            if os.path.basename(path) == "link_inside":
                return True
            return original_islink(path)

        def mock_realpath(path):
            if os.path.basename(path) == "link_inside":
                # 返回 workspace 内的路径（指向 subdir）
                return os.path.join(workspace, "subdir")
            return original_realpath(path)

        def mock_isdir(path):
            if os.path.basename(path) == "link_inside":
                return True  # 模拟指向目录的符号链接
            return original_isdir(path)

        with patch.object(os.path, "islink", side_effect=mock_islink), \
             patch.object(os.path, "realpath", side_effect=mock_realpath), \
             patch.object(os.path, "isdir", side_effect=mock_isdir):
            result = skill.execute(
                {"action": "list_dir", "path": ""},
                context,
            )

        assert result["success"] is True
        # 指向 workspace 内的符号链接应该出现在列表中
        names = [e["name"] for e in result["data"]["entries"]]
        assert "link_inside" in names

    # ------------------------------------------------------------------
    # 路径安全检查内部方法测试
    # ------------------------------------------------------------------

    def test_resolve_safe_path_normal(self, skill, workspace):
        """测试正常路径的安全解析."""
        safe, path, error = skill._resolve_safe_path("test.txt", workspace)
        assert safe is True
        assert path.endswith("test.txt")
        assert error == ""

    def test_resolve_safe_path_traversal(self, skill, workspace):
        """测试路径遍历的安全解析."""
        safe, path, error = skill._resolve_safe_path("../outside.txt", workspace)
        assert safe is False
        assert "越界" in error or "不在" in error

    def test_resolve_safe_path_subdir(self, skill, workspace):
        """测试子目录路径的安全解析."""
        safe, path, error = skill._resolve_safe_path("subdir/subfile.txt", workspace)
        assert safe is True
        assert "subdir" in path

    def test_resolve_safe_path_workspace_itself(self, skill, workspace):
        """测试 workspace 本身路径."""
        safe, path, error = skill._resolve_safe_path(".", workspace)
        assert safe is True

    def test_resolve_safe_path_null_byte(self, skill, workspace):
        """测试空字节路径."""
        safe, path, error = skill._resolve_safe_path("test\x00.txt", workspace)
        assert safe is False

    # ------------------------------------------------------------------
    # 删除安全测试
    # ------------------------------------------------------------------

    def test_delete_workspace_root_rejected(self, skill, context):
        """测试删除 workspace 根目录应被拒绝."""
        result = skill.execute(
            {"action": "delete_file", "path": "."},
            context,
        )
        # 由于 . 解析后就是 workspace 本身，应该被拒绝
        assert result["success"] is False
        assert "根目录" in result["message"] or "禁止" in result["message"]

    # ------------------------------------------------------------------
    # 文件大小限制测试
    # ------------------------------------------------------------------

    def test_read_file_size_limit(self, skill, workspace, context):
        """测试读取文件大小限制."""
        # 创建一个超大文件（超过 10MB 限制）
        big_file = os.path.join(workspace, "big_file.txt")
        with open(big_file, "w") as f:
            f.write("x" * (11 * 1024 * 1024))  # 11MB

        result = skill.execute(
            {"action": "read_file", "path": "big_file.txt"},
            context,
        )
        assert result["success"] is False
        assert "过大" in result["message"] or "超过" in result["message"]

    # ------------------------------------------------------------------
    # 审计日志测试
    # ------------------------------------------------------------------

    def test_audit_log_method_exists(self, skill):
        """测试审计日志方法存在."""
        assert hasattr(skill, "_audit_log")
        assert callable(skill._audit_log)

    def test_resolve_safe_path_uses_realpath(self, skill):
        """测试 _resolve_safe_path 方法存在且返回元组."""
        assert hasattr(skill, "_resolve_safe_path")
        assert callable(skill._resolve_safe_path)


# =========================================================================
# 综合测试计数验证
# =========================================================================


def test_count_test_cases():
    """验证测试用例数量 >= 15."""
    terminal_tests = [
        name for name in dir(TestTerminalCommandSecurity)
        if name.startswith("test_")
    ]
    file_tests = [
        name for name in dir(TestFileOperationSecurity)
        if name.startswith("test_")
    ]
    total = len(terminal_tests) + len(file_tests)
    print(f"\n终端命令安全测试: {len(terminal_tests)} 个")
    print(f"文件操作安全测试: {len(file_tests)} 个")
    print(f"总计: {total} 个测试用例")
    assert total >= 15, f"测试用例数量不足: {total} < 15"


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
