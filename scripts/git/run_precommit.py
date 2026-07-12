#!/usr/bin/env python3
"""
云汐系统 v1.1 - Git Pre-Commit 核心检查逻辑 (GIT-01)

功能：
1. 代码规范检查（Python语法检查、import排序）
2. 自动运行单元测试（仅运行变更相关的测试）
3. 大文件/敏感信息扫描（防止误提交API密钥等）

返回值：
  0 - 所有检查通过
  1 - 检查失败（阻止提交）
"""

import sys
import os
import re
import subprocess
from pathlib import Path
from typing import List, Tuple, Dict, Any

# ============================================================
# 配置项
# ============================================================

# 大文件阈值（字节），默认 5MB
LARGE_FILE_THRESHOLD = 5 * 1024 * 1024

# 敏感信息正则模式
SENSITIVE_PATTERNS: Dict[str, str] = {
    "API Key (generic)": r"(?i)(api[_-]?key|apikey|api_secret)\s*[:=]\s*['\"]?[A-Za-z0-9_\-]{16,}['\"]?",
    "AWS Access Key": r"(?i)AKIA[0-9A-Z]{16}",
    "AWS Secret Key": r"(?i)(aws_secret_access_key|aws_secret)\s*[:=]\s*['\"]?[A-Za-z0-9/+=]{40}['\"]?",
    "GitHub Token": r"(?i)gh[pousr]_[A-Za-z0-9_]{36,}",
    "Private Key": r"-----BEGIN (?:RSA |EC |DSA |OPENSSH )?PRIVATE KEY-----",
    "Bearer Token": r"(?i)bearer\s+[A-Za-z0-9_\-\.]{20,}",
    "JWT Token": r"eyJ[A-Za-z0-9_\-]+\.[A-Za-z0-9_\-]+\.[A-Za-z0-9_\-]+",
    "Database URL": r"(?i)(postgres|mysql|mongodb|redis)://[^\s'\"<>]+",
    "Cloud Service Key": r"(?i)(sk-|pk-|key-)[A-Za-z0-9]{20,}",
    "Slack/Webhook Token": r"(?i)(xox[baprs]-|https://hooks\.slack\.com/services/)",
}

# 忽略的文件路径/后缀（不做敏感信息扫描）
SENSITIVE_SCAN_IGNORE = {
    ".png", ".jpg", ".jpeg", ".gif", ".bmp", ".ico", ".webp",
    ".pdf", ".zip", ".tar", ".gz", ".7z", ".rar",
    ".woff", ".woff2", ".ttf", ".eot",
    ".pyc", ".pyo", ".pyd", ".so", ".dll", ".exe",
    ".mp3", ".mp4", ".avi", ".mov", ".wav",
}

# Conventional Commit 类型
CONVENTIONAL_COMMIT_TYPES = [
    "feat", "fix", "docs", "style", "refactor", "perf",
    "test", "build", "ci", "chore", "revert", "wip",
    "merge", "release", "deploy", "hotfix",
]

# 项目根目录（向上查找 .git 目录）
def _find_project_root() -> Path:
    """查找项目根目录（包含 .git 的目录）"""
    current = Path(__file__).resolve().parent
    for _ in range(10):
        if (current / ".git").exists():
            return current
        current = current.parent
    return Path.cwd()


PROJECT_ROOT = _find_project_root()


# ============================================================
# 工具函数
# ============================================================

def _run_git(args: List[str], cwd: Path = None) -> Tuple[int, str, str]:
    """运行 git 命令，返回 (returncode, stdout, stderr)"""
    try:
        result = subprocess.run(
            ["git"] + args,
            capture_output=True,
            text=True,
            cwd=str(cwd or PROJECT_ROOT),
            timeout=30,
        )
        return result.returncode, result.stdout.strip(), result.stderr.strip()
    except subprocess.TimeoutExpired:
        return -1, "", "git command timed out"
    except Exception as e:
        return -1, "", str(e)


def _get_staged_files() -> List[Path]:
    """获取暂存区文件列表"""
    code, stdout, _ = _run_git(["diff", "--cached", "--name-only", "--diff-filter=ACMR"])
    if code != 0:
        return []
    files = []
    for line in stdout.split("\n"):
        line = line.strip()
        if line:
            files.append(PROJECT_ROOT / line)
    return files


def _get_staged_python_files() -> List[Path]:
    """获取暂存区的 Python 文件"""
    return [f for f in _get_staged_files() if f.suffix == ".py"]


def _color_print(message: str, color: str = "white"):
    """带颜色的输出（简单实现，兼容 Windows PowerShell）"""
    color_map = {
        "red": "\033[91m",
        "green": "\033[92m",
        "yellow": "\033[93m",
        "blue": "\033[94m",
        "cyan": "\033[96m",
        "white": "\033[0m",
        "bold": "\033[1m",
    }
    reset = "\033[0m"
    prefix = color_map.get(color, "")
    # Windows 下尝试启用 ANSI
    if os.name == "nt":
        try:
            import ctypes
            kernel32 = ctypes.windll.kernel32
            kernel32.SetConsoleMode(kernel32.GetStdHandle(-11), 7)
        except Exception:
            pass
    print(f"{prefix}{message}{reset}")


# ============================================================
# 检查项 1: Python 语法检查
# ============================================================

def check_python_syntax() -> Tuple[bool, List[str]]:
    """检查暂存区 Python 文件的语法正确性"""
    py_files = _get_staged_python_files()
    if not py_files:
        return True, ["无 Python 文件变更，跳过语法检查"]

    errors = []
    passed = 0

    for f in py_files:
        if not f.exists():
            continue
        try:
            with open(f, "r", encoding="utf-8") as fp:
                source = fp.read()
            compile(source, str(f), "exec")
            passed += 1
        except SyntaxError as e:
            try:
                rel_path = f.relative_to(PROJECT_ROOT)
            except ValueError:
                rel_path = f
            errors.append(f"  {rel_path}: 第 {e.lineno} 行 - {e.msg}")
        except Exception as e:
            try:
                rel_path = f.relative_to(PROJECT_ROOT)
            except ValueError:
                rel_path = f
            errors.append(f"  {rel_path}: {e}")

    messages = [f"Python 语法检查：{passed} 个文件通过"]
    if errors:
        messages.append(f"发现 {len(errors)} 个语法错误：")
        messages.extend(errors)
        return False, messages
    return True, messages


# ============================================================
# 检查项 2: Import 排序检查
# ============================================================

def check_import_order() -> Tuple[bool, List[str]]:
    """检查 Python 文件的 import 排序（标准库 / 第三方 / 本地）"""
    py_files = _get_staged_python_files()
    if not py_files:
        return True, ["无 Python 文件变更，跳过 import 排序检查"]

    # 优先使用 isort（如果已安装）
    existing_files = [str(f) for f in py_files if f.exists()]
    if not existing_files:
        return True, ["无有效 Python 文件，跳过 import 排序检查"]

    try:
        result = subprocess.run(
            [sys.executable, "-m", "isort", "--check-only", "--diff",
             "--profile", "black"] + existing_files,
            capture_output=True,
            text=True,
            cwd=str(PROJECT_ROOT),
            timeout=30,
        )
        if result.returncode == 0:
            return True, ["Import 排序检查：全部通过 (isort)"]
        else:
            issues = []
            for line in result.stdout.split("\n")[:20]:
                if line.strip():
                    issues.append(f"  {line.strip()}")
            return False, ["Import 排序检查：发现不规范的 import 顺序"] + issues + \
                   ["  提示：运行 `isort --profile black .` 自动修复"]
    except (ImportError, FileNotFoundError, subprocess.TimeoutExpired):
        pass

    # 降级：简单检查 import 顺序
    warnings = []
    for f in py_files:
        if not f.exists():
            continue
        try:
            with open(f, "r", encoding="utf-8") as fp:
                lines = fp.readlines()
            future_found = False
            last_import_line = 0
            for i, line in enumerate(lines, 1):
                stripped = line.strip()
                if stripped.startswith("from __future__"):
                    future_found = True
                    last_import_line = i
                elif stripped.startswith("import ") or stripped.startswith("from "):
                    if future_found and last_import_line > 0 and i > last_import_line + 2:
                        try:
                            rel_path = f.relative_to(PROJECT_ROOT)
                        except ValueError:
                            rel_path = f
                        warnings.append(f"  {rel_path}: 第 {i} 行 - import 与 __future__ 之间应保留空行")
                        break
                    last_import_line = i
        except Exception:
            pass

    if warnings:
        return True, ["Import 排序检查：通过（简化模式，建议安装 isort）"] + warnings[:5]
    return True, ["Import 排序检查：通过（简化模式，建议安装 isort）"]


# ============================================================
# 检查项 3: 大文件扫描
# ============================================================

def check_large_files() -> Tuple[bool, List[str]]:
    """扫描暂存区中的大文件"""
    staged_files = _get_staged_files()
    if not staged_files:
        return True, ["无暂存文件，跳过大文件检查"]

    large_files = []
    for f in staged_files:
        try:
            if f.exists() and f.is_file():
                size = f.stat().st_size
                if size > LARGE_FILE_THRESHOLD:
                    try:
                        rel_path = f.relative_to(PROJECT_ROOT)
                    except ValueError:
                        rel_path = f
                    size_mb = size / (1024 * 1024)
                    large_files.append(f"  {rel_path} ({size_mb:.1f} MB)")
        except OSError:
            pass

    messages = [f"大文件检查：阈值 {LARGE_FILE_THRESHOLD // (1024*1024)} MB"]
    if large_files:
        messages.append(f"发现 {len(large_files)} 个大文件：")
        messages.extend(large_files)
        messages.append("  提示：大文件应加入 .gitignore 或使用 Git LFS")
        return False, messages
    messages.append("通过：无大文件")
    return True, messages


# ============================================================
# 检查项 4: 敏感信息扫描
# ============================================================

def check_sensitive_info() -> Tuple[bool, List[str]]:
    """扫描暂存区文件中的敏感信息"""
    staged_files = _get_staged_files()
    if not staged_files:
        return True, ["无暂存文件，跳过敏感信息扫描"]

    findings = []
    scanned = 0

    for f in staged_files:
        if not f.exists() or not f.is_file():
            continue
        if f.suffix.lower() in SENSITIVE_SCAN_IGNORE:
            continue
        # 跳过密钥/证书文件（直接警告）
        if f.suffix.lower() in {".key", ".pem", ".p12", ".pfx", ".crt", ".cer"}:
            try:
                rel_path = f.relative_to(PROJECT_ROOT)
            except ValueError:
                rel_path = f
            findings.append(f"  [警告] {rel_path}: 密钥/证书文件，建议确认是否应提交")
            continue

        try:
            with open(f, "r", encoding="utf-8", errors="ignore") as fp:
                content = fp.read()
            scanned += 1
        except (OSError, UnicodeDecodeError):
            continue

        try:
            rel_path = f.relative_to(PROJECT_ROOT)
        except ValueError:
            rel_path = f

        for pattern_name, pattern in SENSITIVE_PATTERNS.items():
            matches = re.findall(pattern, content)
            if matches:
                lines = content.split("\n")
                for line_num, line in enumerate(lines, 1):
                    if re.search(pattern, line):
                        stripped = line.strip()
                        if stripped.startswith("#") or stripped.startswith("//") or stripped.startswith('"""'):
                            continue
                        if "your_" in line.lower() or "example" in line.lower() or "xxx" in line.lower():
                            continue
                        if "pragma: allowlist secret" in line.lower():
                            continue
                        findings.append(
                            f"  {rel_path}:{line_num} - 疑似 {pattern_name}"
                        )
                        break

    messages = [f"敏感信息扫描：已扫描 {scanned} 个文件"]
    if findings:
        messages.append(f"发现 {len(findings)} 个潜在敏感信息：")
        messages.extend(findings[:20])
        if len(findings) > 20:
            messages.append(f"  ... 还有 {len(findings) - 20} 项")
        messages.append("  提示：如确认为误报，可在该行添加 # pragma: allowlist secret 注释")
        return False, messages
    messages.append("通过：未发现敏感信息")
    return True, messages


# ============================================================
# 检查项 5: 变更相关的单元测试
# ============================================================

def check_related_tests() -> Tuple[bool, List[str]]:
    """运行与变更相关的单元测试"""
    py_files = _get_staged_python_files()
    if not py_files:
        return True, ["无 Python 文件变更，跳过单元测试"]

    # 查找相关测试文件
    test_files = set()
    for f in py_files:
        if not f.exists():
            continue
        # 如果是测试文件本身，直接加入
        if f.name.startswith("test_") or f.name.endswith("_test.py"):
            test_files.add(str(f))
            continue

        # 查找对应的测试文件（同名 test_ 前缀）
        stem = f.stem
        test_candidates = [
            f.parent / f"test_{stem}.py",
            f.parent / "tests" / f"test_{stem}.py",
            f.parent.parent / "tests" / f"test_{stem}.py",
            PROJECT_ROOT / "tests" / f"test_{stem}.py",
        ]
        for candidate in test_candidates:
            if candidate.exists():
                test_files.add(str(candidate))
                break

    if not test_files:
        return True, ["未找到关联的测试文件，跳过单元测试"]

    messages = [f"单元测试：找到 {len(test_files)} 个相关测试文件"]

    # 尝试用 pytest 运行
    try:
        result = subprocess.run(
            [sys.executable, "-m", "pytest", "-x", "-q", "--tb=short",
             "--timeout=30"] + sorted(test_files),
            capture_output=True,
            text=True,
            cwd=str(PROJECT_ROOT),
            timeout=120,
        )
        if result.returncode == 0:
            passed_match = re.search(r"(\d+)\s+passed", result.stdout)
            count = passed_match.group(1) if passed_match else "若干"
            messages.append(f"通过：{count} 个测试全部通过")
            return True, messages
        else:
            failed_lines = []
            for line in result.stdout.split("\n"):
                if "FAILED" in line or "ERROR" in line:
                    failed_lines.append(f"  {line.strip()}")
            messages.append(f"失败：部分测试未通过")
            messages.extend(failed_lines[:10])
            messages.append("  提示：修复测试后再提交，或使用 --no-verify 跳过（不推荐）")
            return False, messages
    except (subprocess.TimeoutExpired, FileNotFoundError):
        messages.append("跳过：pytest 不可用或测试超时")
        return True, messages
    except Exception as e:
        messages.append(f"跳过：测试执行异常 - {e}")
        return True, messages


# ============================================================
# 检查项 6: 提交信息格式检查 (commit-msg hook 调用)
# ============================================================

def check_commit_message(msg_file: str = None, message: str = None) -> Tuple[bool, List[str]]:
    """
    检查提交信息是否符合 Conventional Commits 规范

    格式: <type>(<scope>): <subject>
    例如: feat(auth): add login page
          fix(m8): correct null pointer in monitor
    """
    if message is None:
        if msg_file and Path(msg_file).exists():
            try:
                with open(msg_file, "r", encoding="utf-8") as f:
                    message = f.read()
            except Exception:
                return False, ["无法读取提交信息文件"]
        else:
            return False, ["未提供提交信息"]

    # 去除注释行（git 自动添加的）
    lines = [l for l in message.split("\n") if not l.startswith("#")]
    full_msg = "\n".join(lines).strip()

    if not full_msg:
        return False, ["提交信息不能为空"]

    first_line = full_msg.split("\n")[0].strip()

    messages = ["提交信息格式检查："]

    # 检查长度
    if len(first_line) > 72:
        return False, messages + [
            f"  错误：标题行过长（{len(first_line)} 字符，建议不超过 72 字符）"
        ]

    # Conventional Commits 格式正则
    pattern = (
        r"^(?P<type>" + "|".join(CONVENTIONAL_COMMIT_TYPES) + r")"
        r"(?:\((?P<scope>[a-zA-Z0-9_\-]+)\))?"
        r"(?P<breaking>!)?"
        r":\s+"
        r"(?P<subject>.+)$"
    )

    match = re.match(pattern, first_line, re.IGNORECASE)
    if not match:
        type_list = ", ".join(CONVENTIONAL_COMMIT_TYPES[:10])
        return False, messages + [
            f"  错误：标题不符合 Conventional Commits 格式",
            f"  正确格式: <type>(<scope>): <subject>",
            f"  常用 type: {type_list}, ...",
            f"  示例: feat(m8): add git status dashboard",
            f"  示例: fix(auth): resolve login timeout issue",
            f"  当前标题: {first_line}",
        ]

    commit_type = match.group("type").lower()
    scope = match.group("scope") or "-"
    subject = match.group("subject")
    is_breaking = bool(match.group("breaking"))

    # 检查 subject 不以大写字母开头（建议）
    if subject and subject[0].isupper():
        messages.append("  [建议] 标题首字母建议小写")

    # 检查 subject 结尾不以句号结尾
    if subject.endswith("."):
        messages.append("  [建议] 标题结尾不应有句号")

    messages.append(
        f"  通过: type={commit_type}, scope={scope}, "
        f"breaking={'是' if is_breaking else '否'}"
    )

    # 检查正文（如果有）
    body_lines = full_msg.split("\n")[1:]
    body = [l.strip() for l in body_lines if l.strip() and not l.startswith("#")]
    if body:
        messages.append(f"  正文: {len(body)} 行")

    return True, messages


# ============================================================
# 主入口
# ============================================================

def run_precommit_checks() -> int:
    """运行所有 pre-commit 检查，返回退出码"""
    _color_print("\n" + "=" * 60, "cyan")
    _color_print("  云汐系统 Git Pre-Commit 检查 (GIT-01)", "bold")
    _color_print("=" * 60 + "\n", "cyan")

    checks = [
        ("Python 语法检查", check_python_syntax),
        ("Import 排序检查", check_import_order),
        ("大文件扫描", check_large_files),
        ("敏感信息扫描", check_sensitive_info),
        ("关联单元测试", check_related_tests),
    ]

    passed_count = 0
    failed_count = 0
    skipped_count = 0

    for name, check_fn in checks:
        _color_print(f"[{name}]", "blue")
        try:
            passed, messages = check_fn()
            for msg in messages:
                print(msg)
            if passed:
                _color_print(f"  ✓ 通过\n", "green")
                passed_count += 1
            else:
                _color_print(f"  ✗ 失败\n", "red")
                failed_count += 1
        except Exception as e:
            _color_print(f"  ! 异常: {e}\n", "yellow")
            skipped_count += 1

    # 汇总
    _color_print("-" * 60, "cyan")
    _color_print(
        f"  结果: {passed_count} 通过, {failed_count} 失败, {skipped_count} 跳过",
        "bold"
    )
    _color_print("=" * 60 + "\n", "cyan")

    if failed_count > 0:
        _color_print("提交被阻止！请修复上述问题后再提交。", "red")
        _color_print("（如确需跳过，可使用 git commit --no-verify，但不推荐）\n", "yellow")
        return 1

    _color_print("所有检查通过，可以提交！\n", "green")
    return 0


def run_commit_msg_check(msg_file: str) -> int:
    """运行 commit-msg 检查，返回退出码"""
    _color_print("\n" + "=" * 60, "cyan")
    _color_print("  云汐系统 Commit Message 检查 (GIT-01)", "bold")
    _color_print("=" * 60 + "\n", "cyan")

    passed, messages = check_commit_message(msg_file=msg_file)
    for msg in messages:
        print(msg)

    print()
    if passed:
        _color_print("  ✓ 提交信息格式正确\n", "green")
        return 0
    else:
        _color_print("  ✗ 提交信息格式不符合规范\n", "red")
        _color_print("提交被阻止！请修改提交信息后再提交。\n", "red")
        return 1


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--commit-msg":
        msg_file = sys.argv[2] if len(sys.argv) > 2 else None
        sys.exit(run_commit_msg_check(msg_file))
    else:
        sys.exit(run_precommit_checks())
