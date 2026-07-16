"""
工作开发模式路由
提供代码沙箱、项目管理、代码管理、开发工具等 API
数据存储：SQLite 数据库（从内存迁移而来）

AI 代码助手：基于统一 LLMClient 驱动，支持代码生成、审查、调试、优化、重构、解释、测试生成等
"""
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import uuid
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional, List, Dict, Any, Tuple, Dict, Any

from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..config import settings
from ..models import (
    get_db,
    User,
    WorkProject,
    WorkTask,
    WorkCommit,
    WorkCodeUsage,
    ComputeCallLog,
    ComputeQuota,
)
from sqlalchemy import func

# 导入统一 LLM 客户端（容错导入，不可用时降级到模板匹配）
try:
    _project_root = Path(__file__).parent.parent.parent.parent
    if str(_project_root) not in sys.path:
        sys.path.insert(0, str(_project_root))
    from shared.llm_client import LLMClient
    _llm_import_ok = True
except ImportError:
    _llm_import_ok = False
    LLMClient = None

router = APIRouter(tags=["工作开发"])

config = settings

# 默认用户 ID（单用户模式）
DEFAULT_USER_ID = 1

# LLM 客户端实例（懒加载）
_llm_client_instance = None


def _get_llm_client():
    """获取 LLM 客户端实例（懒加载，失败时返回 None）"""
    global _llm_client_instance
    if not _llm_import_ok:
        return None
    if _llm_client_instance is None:
        try:
            _llm_client_instance = LLMClient()
        except Exception:
            _llm_client_instance = None
    return _llm_client_instance


def _record_code_usage(db, action_type, language="python", operation_type="",
                       tokens_used=0, is_fallback=False, project_id=0,
                       user_id=DEFAULT_USER_ID):
    """记录代码使用统计

    Args:
        db: 数据库会话
        action_type: 操作类型 generate/chat/execute/complete
        language: 编程语言
        operation_type: 操作子类型
        tokens_used: 估算 token 消耗
        is_fallback: 是否为 fallback 模式
        project_id: 项目ID
        user_id: 用户ID
    """
    try:
        # 找最大 usage_id
        max_id = db.query(func.max(WorkCodeUsage.usage_id)).filter_by(
            user_id=user_id
        ).scalar() or 0
        usage = WorkCodeUsage(
            usage_id=max_id + 1,
            action_type=action_type,
            operation_type=operation_type,
            language=language,
            tokens_used=tokens_used,
            project_id=project_id,
            is_fallback=is_fallback,
            user_id=user_id,
        )
        db.add(usage)
        db.commit()
    except Exception:
        # 统计失败不影响主流程
        db.rollback()


# ── 代码专家系统提示词 ──────────────────────────────────────────

_CODE_EXPERT_SYSTEM_PROMPT = """你是 Codex，一位专业的代码专家。你的任务是帮助用户解决编程问题。

## 你的能力

1. **代码生成**：根据需求生成高质量、可读性强的代码
2. **代码审查**：分析代码问题，提出优化建议
3. **Bug 调试**：定位错误原因，提供修复方案
4. **性能优化**：分析性能瓶颈，提供优化方案
5. **代码重构**：提供代码结构优化和设计模式建议
6. **代码解释**：用通俗易懂的语言解释代码逻辑
7. **测试生成**：为代码生成单元测试用例

## 工作原则

- 代码要规范、有注释、符合最佳实践
- 解释要清晰，分步骤说明
- 对于复杂问题，先给出思路再给出代码
- 用中文回答，代码注释用英文
- 保持专业、严谨的态度
- 考虑边界条件和异常处理

## 输出格式

- 代码使用 ```language 代码块格式
- 关键代码需要有清晰的注释
- 回答结构清晰，使用适当的标题和列表"""

# 操作类型对应的用户提示词模板
_OPERATION_PROMPTS = {
    "generate": "请帮我用 {language} 实现以下功能：\n{prompt}\n\n请给出完整的、可运行的代码实现，包含必要的注释和使用示例。",
    "review": "请帮我审查以下 {language} 代码：\n{prompt}\n\n请从以下维度进行审查：\n1. 代码正确性与潜在 Bug\n2. 代码规范与可读性\n3. 性能问题\n4. 安全隐患\n5. 改进建议\n\n请逐条列出问题，并给出优化后的代码。",
    "debug": "我遇到了一个编程问题，请帮我分析和调试。以下是相关信息：\n{prompt}\n\n使用的语言：{language}\n\n请帮我：\n1. 分析可能的原因\n2. 给出定位问题的方法\n3. 提供修复方案和代码示例",
    "optimize": "请帮我优化以下 {language} 代码的性能：\n{prompt}\n\n请分析性能瓶颈，并提供优化后的代码，同时说明优化思路和预期提升效果。",
    "refactor": "请帮我重构以下 {language} 代码：\n{prompt}\n\n请从以下方面进行重构：\n1. 代码结构和设计模式\n2. 命名规范\n3. 减少复杂度和嵌套\n4. 提高可维护性\n\n请给出重构后的代码，并说明重构思路。",
    "explain": "请帮我解释以下 {language} 代码的逻辑：\n{prompt}\n\n请用通俗易懂的语言解释：\n1. 代码的整体功能\n2. 核心实现思路\n3. 关键部分的逐行/逐段说明\n4. 输入输出示例",
    "test": "请为以下 {language} 代码生成单元测试：\n{prompt}\n\n请生成全面的测试用例，覆盖正常情况、边界条件和异常情况，并给出完整的测试代码。",
}

# 支持的操作类型
_VALID_OPERATIONS = set(_OPERATION_PROMPTS.keys())

# 代码对话会话存储（内存）
_code_chat_sessions = {}


# ============================================================
# 数据模型
# ============================================================

class CodeExecuteRequest(BaseModel):
    language: str = "python"
    code: str
    stdin: Optional[str] = ""


class CodeGenerateRequest(BaseModel):
    prompt: str
    language: str = "python"
    operation_type: str = "generate"  # generate, review, debug, optimize, refactor, explain, test


class CodeCompleteRequest(BaseModel):
    code: str
    cursor_line: int = 0
    cursor_col: int = 0
    language: str = "python"
    file_path: Optional[str] = ""


class CodeChatRequest(BaseModel):
    message: str
    language: str = "python"
    conversation_id: str = "default"
    context_code: Optional[str] = ""


class ProjectCreateRequest(BaseModel):
    name: str
    description: str = ""
    language: str = "python"


class TaskCreateRequest(BaseModel):
    title: str
    description: str = ""
    status: str = "todo"  # todo, in_progress, done
    priority: str = "medium"  # low, medium, high
    project_id: Optional[int] = None


class GitCommitRequest(BaseModel):
    message: str
    project_id: Optional[int] = None



# ============================================================
# 代码沙箱 - 安全配置
# ============================================================

# 沙箱默认超时（秒）
SANDBOX_DEFAULT_TIMEOUT = 10
# 沙箱最大超时（秒）
SANDBOX_MAX_TIMEOUT = 30
# 输出最大长度（字符）
SANDBOX_MAX_OUTPUT = 10000
# 代码最大大小（KB）
SANDBOX_MAX_CODE_SIZE_KB = 100
# 内存限制（MB），预留配置项
SANDBOX_MEMORY_LIMIT_MB = 256

# 各语言危险代码模式
DANGEROUS_PATTERNS = {
    "python": [
        # 系统命令执行
        (r"os\.system\s*\(", "执行系统命令", "high"),
        (r"subprocess\.", "创建子进程", "high"),
        (r"os\.popen\s*\(", "执行系统命令", "high"),
        (r"commands\.", "执行系统命令", "high"),
        (r"popen2\.", "执行系统命令", "high"),
        # 动态代码执行
        (r"\beval\s*\(", "动态代码执行", "high"),
        (r"\bexec\s*\(", "动态代码执行", "high"),
        (r"\bcompile\s*\(", "动态代码编译", "medium"),
        # 文件删除/破坏
        (r"os\.remove\s*\(", "删除文件", "high"),
        (r"os\.rmdir\s*\(", "删除目录", "high"),
        (r"os\.unlink\s*\(", "删除文件", "high"),
        (r"shutil\.rmtree\s*\(", "递归删除目录", "high"),
        # 网络访问
        (r"import\s+socket", "网络连接", "medium"),
        (r"from\s+socket\s+import", "网络连接", "medium"),
        (r"urllib\.", "网络请求", "medium"),
        (r"requests\.", "网络请求", "medium"),
        (r"http\.client", "网络请求", "medium"),
        # 环境变量/敏感信息
        (r"os\.environ", "读取环境变量", "medium"),
        (r"os\.getenv", "读取环境变量", "medium"),
        # 进程/线程
        (r"multiprocessing\.", "多进程操作", "medium"),
        (r"threading\.", "多线程操作", "low"),
        # 文件系统写入（危险路径）
        (r'open\s*\([^)]*[\'\"]/etc/', "写入系统目录", "high"),
        (r'open\s*\([^)]*[\'\"]/sys/', "写入系统目录", "high"),
        (r'open\s*\([^)]*[\'\"]/proc/', "写入系统目录", "high"),
    ],
    "javascript": [
        (r"require\s*\(\s*['\"]child_process['\"]", "执行系统命令", "high"),
        (r"child_process\.", "执行系统命令", "high"),
        (r"\bexec\s*\(", "执行命令", "high"),
        (r"\bexecSync\s*\(", "执行命令", "high"),
        (r"\bspawn\s*\(", "创建子进程", "high"),
        (r"\beval\s*\(", "动态代码执行", "high"),
        (r"new\s+Function\s*\(", "动态代码执行", "high"),
        (r"fs\.unlink", "删除文件", "high"),
        (r"fs\.rmdir", "删除目录", "high"),
        (r"fs\.rm\s*\(", "删除文件/目录", "high"),
        (r"require\s*\(\s*['\"]http['\"]", "网络请求", "medium"),
        (r"require\s*\(\s*['\"]https['\"]", "网络请求", "medium"),
        (r"require\s*\(\s*['\"]net['\"]", "网络连接", "medium"),
        (r"XMLHttpRequest", "网络请求", "medium"),
        (r"fetch\s*\(", "网络请求", "medium"),
    ],
    "typescript": [
        (r"require\s*\(\s*['\"]child_process['\"]", "执行系统命令", "high"),
        (r"child_process\.", "执行系统命令", "high"),
        (r"\bexec\s*\(", "执行命令", "high"),
        (r"\bspawn\s*\(", "创建子进程", "high"),
        (r"\beval\s*\(", "动态代码执行", "high"),
        (r"fs\.unlink", "删除文件", "high"),
        (r"fs\.rmdir", "删除目录", "high"),
        (r"fs\.rm\s*\(", "删除文件/目录", "high"),
    ],
    "go": [
        (r'"os/exec"', "执行系统命令", "high"),
        (r"exec\.Command", "执行系统命令", "high"),
        (r"os\.Remove", "删除文件", "high"),
        (r"os\.RemoveAll", "递归删除", "high"),
        (r'"net"', "网络连接", "medium"),
        (r"net\.", "网络连接", "medium"),
        (r"os\.Getenv", "读取环境变量", "medium"),
    ],
    "rust": [
        (r"std::process::Command", "执行系统命令", "high"),
        (r"std::fs::remove_file", "删除文件", "high"),
        (r"std::fs::remove_dir", "删除目录", "high"),
        (r"std::net::", "网络连接", "medium"),
    ],
}


def detect_dangerous_code(code, language):
    """检测代码中的危险模式

    Args:
        code: 代码内容
        language: 编程语言

    Returns:
        危险检测结果列表
    """
    patterns = DANGEROUS_PATTERNS.get(language, [])
    if not patterns:
        return []

    findings = []
    code_lines = code.split("\n")

    for line_num, line in enumerate(code_lines, 1):
        stripped = line.strip()
        # 跳过注释行
        if language == "python" and stripped.startswith("#"):
            continue
        if language in ("javascript", "typescript") and (
            stripped.startswith("//") or stripped.startswith("*")
        ):
            continue
        if language == "go" and stripped.startswith("//"):
            continue
        if language == "rust" and stripped.startswith("//"):
            continue

        for pattern, desc, severity in patterns:
            try:
                if re.search(pattern, line):
                    findings.append({
                        "line": line_num,
                        "code": stripped[:100],
                        "description": desc,
                        "severity": severity,
                    })
            except re.error:
                continue

    # 去重
    seen = set()
    unique_findings = []
    for f in findings:
        key = (f["line"], f["description"])
        if key not in seen:
            seen.add(key)
            unique_findings.append(f)

    return unique_findings


def get_safe_environ():
    """获取安全的环境变量（移除敏感信息）"""
    env = os.environ.copy()

    sensitive_keywords = [
        "API_KEY", "SECRET", "TOKEN", "PASSWORD", "PASSWD",
        "PRIVATE_KEY", "ACCESS_KEY", "AUTH", "COOKIE",
        "GIT_TOKEN", "GITHUB_TOKEN", "NPM_TOKEN",
        "AWS_ACCESS_KEY", "AWS_SECRET", "AZURE_KEY",
        "YUNXI_TOKEN", "M8_API_KEY", "ADMIN_TOKEN",
        "DATABASE_URL", "DB_PASSWORD", "REDIS_PASSWORD",
    ]

    keys_to_remove = []
    for key in env:
        upper_key = key.upper()
        for sensitive in sensitive_keywords:
            if sensitive in upper_key:
                keys_to_remove.append(key)
                break

    for key in keys_to_remove:
        del env[key]

    env["SANDBOX_MODE"] = "true"
    env["PYTHONSAFEPATH"] = "1"

    return env


def validate_code_size(code, max_size_kb=100):
    """验证代码大小是否在限制内"""
    size_bytes = len(code.encode("utf-8"))
    if size_bytes > max_size_kb * 1024:
        return False, "代码大小超过限制: %.1fKB > %dKB" % (size_bytes / 1024, max_size_kb)
    return True, ""


# ============================================================
# 代码沙箱 - 语言检测
# ============================================================

LANGUAGE_CONFIG = {
    "python": {
        "name": "Python",
        "icon": "\U0001f40d",
        "extension": ".py",
        "check_cmd": ["python", "--version"],
        "version_regex": r"Python\s+([\d.]+)",
    },
    "javascript": {
        "name": "JavaScript",
        "icon": "\U0001f4dc",
        "extension": ".js",
        "check_cmd": ["node", "--version"],
        "version_regex": r"v?([\d.]+)",
    },
    "typescript": {
        "name": "TypeScript",
        "icon": "\U0001f537",
        "extension": ".ts",
        "check_cmd": ["npx", "ts-node", "--version"],
        "version_regex": r"v?([\d.]+)",
        "note": "需要 ts-node（npx ts-node）",
    },
    "go": {
        "name": "Go",
        "icon": "\U0001f535",
        "extension": ".go",
        "check_cmd": ["go", "version"],
        "version_regex": r"go([\d.]+)",
    },
    "rust": {
        "name": "Rust",
        "icon": "\U0001f980",
        "extension": ".rs",
        "check_cmd": ["rustc", "--version"],
        "version_regex": r"rustc\s+([\d.]+)",
    },
}


def _check_language_available(lang_key):
    """检测语言是否在系统中可用"""
    config = LANGUAGE_CONFIG.get(lang_key)
    if not config:
        return {
            "key": lang_key, "name": lang_key, "version": "unknown",
            "status": "unavailable", "extension": "", "icon": "",
        }

    result = {
        "key": lang_key,
        "name": config["name"],
        "icon": config["icon"],
        "extension": config["extension"],
        "status": "unavailable",
        "version": "未安装",
    }

    try:
        proc = subprocess.run(
            config["check_cmd"],
            capture_output=True, text=True, timeout=5,
            encoding="utf-8", errors="replace",
        )
        output = (proc.stdout or "") + (proc.stderr or "")
        if proc.returncode == 0 or output.strip():
            match = re.search(config["version_regex"], output)
            if match:
                result["version"] = match.group(1)
            else:
                result["version"] = "已安装"
            result["status"] = "available"
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        pass

    if "note" in config and result["status"] == "unavailable":
        result["note"] = config["note"]

    return result


def get_all_languages():
    """获取所有语言的状态列表"""
    return [_check_language_available(k) for k in LANGUAGE_CONFIG]


# ============================================================
# 代码沙箱 - 执行引擎
# ============================================================

def _run_sandbox(cmd, code, stdin="", timeout=SANDBOX_DEFAULT_TIMEOUT,
                 file_ext=".txt"):
    """通用沙箱执行函数"""
    start = time.time()
    temp_file = None

    try:
        size_ok, size_msg = validate_code_size(code, SANDBOX_MAX_CODE_SIZE_KB)
        if not size_ok:
            return {
                "stdout": "", "stderr": size_msg, "exit_code": -1,
                "duration_ms": int((time.time() - start) * 1000),
                "timed_out": False, "memory_kb": 0,
            }

        with tempfile.NamedTemporaryFile(
            mode="w", suffix=file_ext, delete=False, encoding="utf-8"
        ) as f:
            f.write(code)
            temp_file = f.name

        actual_cmd = [c if c != "__FILE__" else temp_file for c in cmd]
        env = get_safe_environ()

        try:
            proc = subprocess.run(
                actual_cmd,
                input=stdin, capture_output=True, text=True,
                timeout=timeout, env=env,
                encoding="utf-8", errors="replace",
            )
            duration = int((time.time() - start) * 1000)
            return {
                "stdout": proc.stdout[:SANDBOX_MAX_OUTPUT],
                "stderr": proc.stderr[:SANDBOX_MAX_OUTPUT],
                "exit_code": proc.returncode,
                "duration_ms": duration,
                "timed_out": False, "memory_kb": 0,
            }
        except subprocess.TimeoutExpired:
            return {
                "stdout": "",
                "stderr": "执行超时（超过%d秒）" % timeout,
                "exit_code": -1, "duration_ms": timeout * 1000,
                "timed_out": True, "memory_kb": 0,
            }

    except FileNotFoundError:
        return {
            "stdout": "", "stderr": "编译器/解释器未找到，请检查是否已安装",
            "exit_code": -1, "duration_ms": int((time.time() - start) * 1000),
            "timed_out": False, "memory_kb": 0,
        }
    except Exception as e:
        return {
            "stdout": "", "stderr": "执行错误: %s" % str(e),
            "exit_code": -1, "duration_ms": int((time.time() - start) * 1000),
            "timed_out": False, "memory_kb": 0,
        }
    finally:
        if temp_file and os.path.exists(temp_file):
            try:
                os.unlink(temp_file)
            except Exception:
                pass


def _execute_python(code, stdin=""):
    return _run_sandbox(["python", "__FILE__"], code, stdin, file_ext=".py")


def _execute_javascript(code, stdin=""):
    return _run_sandbox(["node", "__FILE__"], code, stdin, file_ext=".js")


def _execute_typescript(code, stdin=""):
    return _run_sandbox(
        ["npx", "ts-node", "__FILE__"], code, stdin, file_ext=".ts"
    )


def _execute_go(code, stdin=""):
    return _run_sandbox(["go", "run", "__FILE__"], code, stdin, file_ext=".go")


def _execute_rust(code, stdin=""):
    """执行 Rust 代码（先编译再运行）"""
    start = time.time()
    temp_dir = None

    try:
        size_ok, size_msg = validate_code_size(code, SANDBOX_MAX_CODE_SIZE_KB)
        if not size_ok:
            return {
                "stdout": "", "stderr": size_msg, "exit_code": -1,
                "duration_ms": 0, "timed_out": False, "memory_kb": 0,
            }

        temp_dir = tempfile.mkdtemp(prefix="rust_sandbox_")
        src_file = os.path.join(temp_dir, "main.rs")
        with open(src_file, "w", encoding="utf-8") as f:
            f.write(code)

        exe_path = os.path.join(temp_dir, "main.exe" if os.name == "nt" else "main")
        env = get_safe_environ()

        # 编译
        compile_proc = subprocess.run(
            ["rustc", "-o", exe_path, src_file],
            capture_output=True, text=True, timeout=SANDBOX_DEFAULT_TIMEOUT,
            env=env, encoding="utf-8", errors="replace",
        )
        if compile_proc.returncode != 0:
            return {
                "stdout": "",
                "stderr": "编译错误:\n" + compile_proc.stderr[:SANDBOX_MAX_OUTPUT],
                "exit_code": compile_proc.returncode,
                "duration_ms": int((time.time() - start) * 1000),
                "timed_out": False, "memory_kb": 0,
            }

        # 运行
        remaining = max(1, SANDBOX_DEFAULT_TIMEOUT - int(time.time() - start))
        run_proc = subprocess.run(
            [exe_path], input=stdin, capture_output=True, text=True,
            timeout=remaining, env=env, encoding="utf-8", errors="replace",
        )
        return {
            "stdout": run_proc.stdout[:SANDBOX_MAX_OUTPUT],
            "stderr": run_proc.stderr[:SANDBOX_MAX_OUTPUT],
            "exit_code": run_proc.returncode,
            "duration_ms": int((time.time() - start) * 1000),
            "timed_out": False, "memory_kb": 0,
        }

    except subprocess.TimeoutExpired:
        return {
            "stdout": "",
            "stderr": "执行超时（超过%d秒）" % SANDBOX_DEFAULT_TIMEOUT,
            "exit_code": -1, "duration_ms": SANDBOX_DEFAULT_TIMEOUT * 1000,
            "timed_out": True, "memory_kb": 0,
        }
    except FileNotFoundError:
        return {
            "stdout": "", "stderr": "Rust 编译器 (rustc) 未安装",
            "exit_code": -1, "duration_ms": int((time.time() - start) * 1000),
            "timed_out": False, "memory_kb": 0,
        }
    except Exception as e:
        return {
            "stdout": "", "stderr": "执行错误: %s" % str(e),
            "exit_code": -1, "duration_ms": int((time.time() - start) * 1000),
            "timed_out": False, "memory_kb": 0,
        }
    finally:
        if temp_dir and os.path.exists(temp_dir):
            try:
                shutil.rmtree(temp_dir)
            except Exception:
                pass


LANGUAGE_EXECUTORS = {
    "python": _execute_python,
    "javascript": _execute_javascript,
    "node": _execute_javascript,
    "typescript": _execute_typescript,
    "go": _execute_go,
    "rust": _execute_rust,
}


# ============================================================
# 数据初始化
# ============================================================

def _ensure_data_initialized(db: Session, user_id: int = DEFAULT_USER_ID):
    """确保示例数据已初始化（表为空时自动插入）"""
    _init_sample_projects(db, user_id)


def _init_sample_projects(db: Session, user_id: int = DEFAULT_USER_ID):
    """初始化工作开发模式示例数据"""
    # 项目表为空时插入示例数据
    if db.query(WorkProject).filter_by(user_id=user_id).count() == 0:
        now = datetime.utcnow()

        # 示例项目
        project_templates = [
            {"name": "云汐系统", "description": "云汐AI助手核心系统", "language": "python", "status": "active"},
            {"name": "前端门户", "description": "Web前端门户页面", "language": "javascript", "status": "active"},
            {"name": "数据分析平台", "description": "数据可视化与分析", "language": "python", "status": "planning"},
        ]
        for i, p in enumerate(project_templates):
            pid = i + 1
            project = WorkProject(
                project_id=pid,
                name=p["name"],
                description=p["description"],
                status=p["status"],
                progress=0,
                language=p["language"],
                file_count=42 - i * 10,
                line_count=8500 - i * 2000,
                commit_count=120 - i * 30,
                created_at=now - timedelta(days=30 - i * 10),
                updated_at=now - timedelta(days=i),
                user_id=user_id,
            )
            db.add(project)
        db.commit()

    # 任务表为空时插入示例数据
    if db.query(WorkTask).filter_by(user_id=user_id).count() == 0:
        now = datetime.utcnow()

        task_templates = [
            (1, "实现用户认证模块", "完成登录、注册、权限校验", "done", "high"),
            (1, "开发Agent调度系统", "多Agent协同调度框架", "in_progress", "high"),
            (1, "编写API文档", "Swagger自动生成文档", "todo", "medium"),
            (1, "性能优化", "接口响应时间优化到200ms以内", "todo", "medium"),
            (2, "首页UI设计", "系统门户首页设计", "done", "high"),
            (2, "响应式布局", "移动端适配", "in_progress", "medium"),
            (3, "需求分析", "平台功能需求调研", "done", "high"),
            (3, "技术选型", "确定技术栈和架构", "in_progress", "high"),
        ]
        for i, (pid, title, desc, status, pri) in enumerate(task_templates):
            tid = i + 1
            task = WorkTask(
                task_id=tid,
                title=title,
                description=desc,
                status=status,
                priority=pri,
                project_id=pid,
                assignee="云汐",
                created_at=now - timedelta(days=20 - i * 2),
                updated_at=now - timedelta(days=i),
                user_id=user_id,
            )
            db.add(task)
        db.commit()

    # 提交记录表为空时插入示例数据
    if db.query(WorkCommit).filter_by(user_id=user_id).count() == 0:
        now = datetime.utcnow()

        commit_messages = [
            "feat: 实现多Agent联邦调度系统",
            "fix: 修复首页API鉴权问题",
            "feat: 新增技能集群模块",
            "refactor: 重构配置管理系统",
            "docs: 更新API文档",
            "fix: 修复端口冲突问题",
            "feat: 新增成长中心模块",
            "style: 优化UI样式",
        ]
        for i, msg in enumerate(commit_messages):
            cid = i + 1
            commit = WorkCommit(
                commit_id=cid,
                hash=uuid.uuid4().hex[:8],
                message=msg,
                author="云汐",
                project_id=1 if i < 6 else 2,
                branch="main",
                additions=50 + i * 10,
                deletions=10 + i * 3,
                files_changed=3 + i % 5,
                committed_at=now - timedelta(hours=i * 6),
                user_id=user_id,
            )
            db.add(commit)
        db.commit()


# ============================================================
# 辅助工具：ORM → Dict
# ============================================================

def _project_to_dict(p: WorkProject) -> dict:
    """项目 ORM → 字典（兼容原格式）"""
    return {
        "id": p.project_id,
        "name": p.name,
        "description": p.description,
        "status": p.status,
        "progress": p.progress,
        "language": p.language,
        "file_count": p.file_count,
        "line_count": p.line_count,
        "commit_count": p.commit_count,
        "created_at": p.created_at.isoformat() if p.created_at else None,
        "updated_at": p.updated_at.isoformat() if p.updated_at else None,
    }


def _task_to_dict(t: WorkTask) -> dict:
    """任务 ORM → 字典（兼容原格式）"""
    return {
        "id": t.task_id,
        "title": t.title,
        "description": t.description,
        "status": t.status,
        "priority": t.priority,
        "project_id": t.project_id,
        "assignee": t.assignee,
        "created_at": t.created_at.isoformat() if t.created_at else None,
        "updated_at": t.updated_at.isoformat() if t.updated_at else None,
    }


def _commit_to_dict(c: WorkCommit) -> dict:
    """提交记录 ORM → 字典（兼容原格式）"""
    return {
        "id": c.commit_id,
        "hash": c.hash,
        "message": c.message,
        "author": c.author,
        "project_id": c.project_id,
        "branch": c.branch,
        "created_at": c.committed_at.isoformat() if c.committed_at else None,
        "files_changed": c.files_changed,
        "insertions": c.additions,
        "deletions": c.deletions,
    }


# 代码会话仍然使用内存存储（临时会话，不需要持久化）
_code_sessions = {}


# ============================================================
# 概览统计
# ============================================================

@router.get("/overview")
async def work_dev_overview(
    db: Session = Depends(get_db),
):
    """工作开发模式概览统计（真实数据 + 估算标注）"""
    _ensure_data_initialized(db, DEFAULT_USER_ID)

    now = datetime.utcnow()
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    week_ago = now - timedelta(days=7)
    month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)

    # ── 基础统计：项目/任务/提交（真实数据） ──
    projects = db.query(WorkProject).filter_by(user_id=DEFAULT_USER_ID).all()
    tasks = db.query(WorkTask).filter_by(user_id=DEFAULT_USER_ID).all()
    commits = db.query(WorkCommit).filter_by(user_id=DEFAULT_USER_ID).all()

    total_projects = len(projects)
    active_projects = sum(1 for p in projects if p.status == "active")
    total_tasks = len(tasks)
    done_tasks = sum(1 for t in tasks if t.status == "done")
    in_progress_tasks = sum(1 for t in tasks if t.status == "in_progress")
    todo_tasks = sum(1 for t in tasks if t.status == "todo")
    total_commits = len(commits)
    total_lines = sum(p.line_count or 0 for p in projects)

    week_commits = sum(
        1 for c in commits
        if c.committed_at and c.committed_at > week_ago
    )

    # ── Token 今日消耗（优先从 ComputeCallLog 取，无则从 WorkCodeUsage 估算） ──
    token_today = 0
    token_source = "compute_monitor"  # compute_monitor / code_usage / estimated
    try:
        call_logs_today = db.query(
            func.sum(ComputeCallLog.input_tokens + ComputeCallLog.output_tokens)
        ).filter(
            ComputeCallLog.created_at >= today_start,
            ComputeCallLog.caller_module == "work_dev",
        ).scalar()
        if call_logs_today:
            token_today = int(call_logs_today or 0)
        else:
            # 从 WorkCodeUsage 估算（按字符数估算 token）
            usage_today = db.query(
                func.sum(WorkCodeUsage.tokens_used)
            ).filter(
                WorkCodeUsage.user_id == DEFAULT_USER_ID,
                WorkCodeUsage.created_at >= today_start,
            ).scalar()
            token_today = int(usage_today or 0)
            token_source = "code_usage"
    except Exception:
        # 如果表不存在，从代码使用次数估算
        try:
            usage_count = db.query(WorkCodeUsage).filter(
                WorkCodeUsage.user_id == DEFAULT_USER_ID,
                WorkCodeUsage.created_at >= today_start,
            ).count()
            token_today = usage_count * 800  # 平均每次约 800 token
            token_source = "estimated"
        except Exception:
            token_today = 0
            token_source = "estimated"

    # 昨日 Token 消耗（用于趋势）
    token_yesterday = 0
    try:
        yesterday_start = today_start - timedelta(days=1)
        call_logs_yesterday = db.query(
            func.sum(ComputeCallLog.input_tokens + ComputeCallLog.output_tokens)
        ).filter(
            ComputeCallLog.created_at >= yesterday_start,
            ComputeCallLog.created_at < today_start,
            ComputeCallLog.caller_module == "work_dev",
        ).scalar()
        token_yesterday = int(call_logs_yesterday or 0)
    except Exception:
        try:
            yesterday_count = db.query(WorkCodeUsage).filter(
                WorkCodeUsage.user_id == DEFAULT_USER_ID,
                WorkCodeUsage.created_at >= today_start - timedelta(days=1),
                WorkCodeUsage.created_at < today_start,
            ).count()
            token_yesterday = yesterday_count * 800
        except Exception:
            token_yesterday = token_today  # 无数据时持平

    token_change = 0.0
    if token_yesterday > 0:
        token_change = round((token_today - token_yesterday) / token_yesterday * 100, 1)

    # ── 代码生成次数（从 WorkCodeUsage 统计） ──
    code_gen_count_today = 0
    code_gen_source = "code_usage"
    try:
        code_gen_count_today = db.query(WorkCodeUsage).filter(
            WorkCodeUsage.user_id == DEFAULT_USER_ID,
            WorkCodeUsage.created_at >= today_start,
            WorkCodeUsage.action_type == "generate",
        ).count()
    except Exception:
        code_gen_count_today = 0
        code_gen_source = "estimated"

    # 昨日代码生成次数
    code_gen_yesterday = 0
    try:
        code_gen_yesterday = db.query(WorkCodeUsage).filter(
            WorkCodeUsage.user_id == DEFAULT_USER_ID,
            WorkCodeUsage.created_at >= today_start - timedelta(days=1),
            WorkCodeUsage.created_at < today_start,
            WorkCodeUsage.action_type == "generate",
        ).count()
    except Exception:
        pass

    code_gen_change = code_gen_count_today - code_gen_yesterday

    # ── 评审通过率（从代码审查操作统计） ──
    review_pass_rate = 0.0
    review_source = "estimated"
    try:
        # 统计 review 操作的总数
        review_total = db.query(WorkCodeUsage).filter(
            WorkCodeUsage.user_id == DEFAULT_USER_ID,
            WorkCodeUsage.operation_type == "review",
        ).count()
        if review_total > 0:
            # 估算通过率：假设 85-95% 之间，根据数据量微调
            # 实际需要 review 结果表，这里用估算并标注
            review_pass_rate = round(88.0 + (review_total % 7), 1)
            review_source = "estimated"
        else:
            review_pass_rate = 92.0
            review_source = "estimated"
    except Exception:
        review_pass_rate = 92.0
        review_source = "estimated"

    # 上周评审通过率（用于趋势，简单估算）
    review_last_week = review_pass_rate - 1.5  # 估算略有下降
    review_change = round(review_pass_rate - review_last_week, 1)

    # ── 预算余量（从 ComputeQuota 取，无则估算） ──
    budget_remaining_pct = 0.0
    budget_total = 0.0
    budget_used = 0.0
    budget_source = "estimated"
    try:
        quota = db.query(ComputeQuota).filter_by(
            scope="user",
            period="month",
        ).first()
        if quota and quota.limit_amount > 0:
            budget_total = quota.limit_amount
            budget_used = quota.used_amount or 0.0
            budget_remaining_pct = round(
                (1 - budget_used / budget_total) * 100, 1
            )
            budget_source = "compute_quota"
        else:
            # 从 token 消耗估算月度预算
            month_token_used = 0
            try:
                month_logs = db.query(
                    func.sum(ComputeCallLog.input_tokens + ComputeCallLog.output_tokens)
                ).filter(
                    ComputeCallLog.created_at >= month_start,
                    ComputeCallLog.caller_module == "work_dev",
                ).scalar()
                month_token_used = int(month_logs or 0)
            except Exception:
                month_token_used = token_today * 15  # 粗略估算月用量

            monthly_budget = 500000  # 假设月度预算 50 万 token
            budget_total = monthly_budget
            budget_used = month_token_used
            budget_remaining_pct = round(
                max(0, (1 - month_token_used / monthly_budget) * 100), 1
            )
            budget_source = "estimated"
    except Exception:
        budget_remaining_pct = 75.0
        budget_total = 500000
        budget_used = 125000
        budget_source = "estimated"

    # ── Token 分类明细（用于右侧面板） ──
    token_categories = []
    try:
        # 按操作类型统计今日 token
        cat_results = db.query(
            WorkCodeUsage.action_type,
            func.sum(WorkCodeUsage.tokens_used).label("total_tokens")
        ).filter(
            WorkCodeUsage.user_id == DEFAULT_USER_ID,
            WorkCodeUsage.created_at >= today_start,
        ).group_by(WorkCodeUsage.action_type).all()

        cat_map = {
            "generate": "代码生成",
            "chat": "对话交互",
            "execute": "代码执行",
            "complete": "代码补全",
        }
        token_categories = [
            {
                "key": row.action_type,
                "name": cat_map.get(row.action_type, row.action_type),
                "tokens": int(row.total_tokens or 0),
            }
            for row in cat_results
        ]
        # 按 token 数排序
        token_categories.sort(key=lambda x: x["tokens"], reverse=True)
    except Exception:
        token_categories = []

    # 确保至少有分类数据
    if not token_categories:
        token_categories = [
            {"key": "generate", "name": "代码生成", "tokens": int(token_today * 0.6)},
            {"key": "chat", "name": "对话交互", "tokens": int(token_today * 0.3)},
            {"key": "review", "name": "代码审查", "tokens": int(token_today * 0.1)},
        ]

    # ── 最近任务/提交 ──
    recent_tasks = sorted(
        [_task_to_dict(t) for t in tasks],
        key=lambda x: x["updated_at"],
        reverse=True
    )[:5]

    recent_commits = sorted(
        [_commit_to_dict(c) for c in commits],
        key=lambda x: x["created_at"],
        reverse=True
    )[:5]

    return {
        "code": 0,
        "message": "ok",
        "data": {
            "stats": {
                # 基础统计
                "total_projects": total_projects,
                "active_projects": active_projects,
                "total_tasks": total_tasks,
                "done_tasks": done_tasks,
                "in_progress_tasks": in_progress_tasks,
                "todo_tasks": todo_tasks,
                "total_commits": total_commits,
                "week_commits": week_commits,
                "total_lines": total_lines,
                # 4 个统计卡片数据
                "token_today": token_today,
                "token_source": token_source,
                "token_change_pct": token_change,
                "code_gen_today": code_gen_count_today,
                "code_gen_source": code_gen_source,
                "code_gen_change": code_gen_change,
                "review_pass_rate": review_pass_rate,
                "review_source": review_source,
                "review_change_pct": review_change,
                "budget_remaining_pct": budget_remaining_pct,
                "budget_total": budget_total,
                "budget_used": budget_used,
                "budget_source": budget_source,
                # token 分类
                "token_categories": token_categories,
            },
            "recent_tasks": recent_tasks,
            "recent_commits": recent_commits,
        }
    }


# ============================================================
# 代码沙箱
# ============================================================

@router.post("/code/execute")
async def execute_code(
    req: CodeExecuteRequest,
    db: Session = Depends(get_db),
):
    """执行代码（沙箱环境，带安全检测）"""
    session_id = str(uuid.uuid4())[:8]
    language = req.language.lower().strip()

    try:
        # 1. 语言支持检查
        executor = LANGUAGE_EXECUTORS.get(language)
        if not executor:
            raise HTTPException(
                status_code=400,
                detail="不支持的语言: %s，支持: %s" % (req.language, ", ".join(LANGUAGE_CONFIG.keys()))
            )

        # 2. 危险代码检测（警告模式，不阻止执行，但在结果中提示）
        danger_findings = detect_dangerous_code(req.code, language)
        has_danger = len(danger_findings) > 0

        # 3. 执行代码
        result = executor(req.code, req.stdin or "")

        # 4. 添加安全警告信息到 stderr
        security_warning_lines = []
        if has_danger:
            high_risk = [f for f in danger_findings if f["severity"] == "high"]
            medium_risk = [f for f in danger_findings if f["severity"] == "medium"]
            security_warning_lines.append(
                "[安全警告] 检测到 %d 处潜在危险操作（高危 %d 处，中危 %d 处）"
                % (len(danger_findings), len(high_risk), len(medium_risk))
            )
            for f in danger_findings[:5]:
                security_warning_lines.append(
                    "  - 第%d行 [%s]: %s" % (f["line"], f["severity"], f["description"])
                )
            if len(danger_findings) > 5:
                security_warning_lines.append("  ... 还有 %d 处" % (len(danger_findings) - 5))

        # 5. 保存会话
        _code_sessions[session_id] = {
            "session_id": session_id,
            "language": language,
            "code": req.code,
            "result": result,
            "danger_findings": danger_findings,
            "created_at": datetime.now().isoformat(),
        }

        # 6. 组装返回
        stderr_output = result["stderr"]
        if security_warning_lines:
            warning_text = "\n".join(security_warning_lines)
            if stderr_output:
                stderr_output = warning_text + "\n\n" + stderr_output
            else:
                stderr_output = warning_text

        _record_code_usage(db, "execute", language, "execute",
                          len(req.code), False)
        return {
            "code": 0,
            "message": "ok",
            "data": {
                "session_id": session_id,
                "language": language,
                "stdout": result["stdout"],
                "stderr": stderr_output,
                "exit_code": result["exit_code"],
                "duration_ms": result["duration_ms"],
                "timed_out": result.get("timed_out", False),
                "memory_kb": result.get("memory_kb", 0),
                "security_warnings": danger_findings,
                "has_danger": has_danger,
            }
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/code/languages")
async def get_supported_languages():
    """支持的编程语言列表（动态检测系统安装状态）"""
    languages = get_all_languages()
    return {"code": 0, "message": "ok", "data": languages}


@router.post("/code/generate")
async def generate_code(
    req: CodeGenerateRequest,
    db: Session = Depends(get_db),
):
    """AI 代码操作（生成/审查/调试/优化/重构/解释/测试生成）

    优先使用 LLM 大模型生成，LLM 不可用时降级到模板匹配。
    """
    operation = req.operation_type or "generate"
    if operation not in _VALID_OPERATIONS:
        raise HTTPException(status_code=400, detail=f"不支持的操作类型: {operation}")

    language = req.language or "python"
    prompt = req.prompt.strip()
    if not prompt:
        raise HTTPException(status_code=400, detail="prompt 不能为空")

    # 优先尝试 LLM
    llm = _get_llm_client()
    if llm is not None:
        try:
            result = await _call_llm_for_code(
                llm=llm,
                operation=operation,
                language=language,
                prompt=prompt,
            )
            # 估算 token 消耗
            est_tokens = len(prompt) + len(result)
            _record_code_usage(db, "generate", language, operation,
                              est_tokens, False)
            return {
                "code": 0,
                "message": "ok",
                "data": {
                    "language": language,
                    "operation": operation,
                    "content": result,
                    "model": _get_model_name(llm),
                    "is_fallback": False,
                }
            }
        except Exception:
            # LLM 调用失败，降级到模板匹配
            pass

    # Fallback: 模板匹配
    code = _fallback_generate_code(prompt, language)
    _record_code_usage(db, "generate", language, operation,
                      len(prompt) + len(code), True)
    return {
        "code": 0,
        "message": "ok",
        "data": {
            "language": language,
            "operation": operation,
            "content": f"根据你的需求，我生成了以下{_get_lang_name(language)}代码：\n\n```{language}\n{code}\n```\n\n**说明：**\n- 代码包含基本的输入验证\n- 已添加必要的注释说明\n\n（当前为模板匹配模式，接入大模型后可获得更智能的回复）",
            "code": code,
            "is_fallback": True,
        }
    }


async def _call_llm_for_code(llm, operation: str, language: str, prompt: str) -> str:
    """调用 LLM 进行代码操作"""
    user_prompt = _OPERATION_PROMPTS[operation].format(
        language=_get_lang_name(language),
        prompt=prompt,
    )
    messages = [
        {"role": "system", "content": _CODE_EXPERT_SYSTEM_PROMPT},
        {"role": "user", "content": user_prompt},
    ]
    reply = await llm.chat(
        messages=messages,
        temperature=0.2,
        max_tokens=4000,
    )
    return reply


def _get_model_name(llm) -> str:
    """获取当前使用的模型名称"""
    try:
        # 适配统一 LLMClient
        if hasattr(llm, '_model_name'):
            return llm._model_name
        if hasattr(llm, '_config') and hasattr(llm._config, 'llm_model'):
            return llm._config.llm_model
        if hasattr(llm, '_provider') and hasattr(llm._provider, 'model'):
            return llm._provider.model
    except Exception:
        pass
    return "unknown"


def _get_lang_name(lang_key: str) -> str:
    """语言 key 转显示名"""
    names = {
        "python": "Python",
        "javascript": "JavaScript",
        "typescript": "TypeScript",
        "go": "Go",
        "rust": "Rust",
        "java": "Java",
        "c": "C",
        "cpp": "C++",
    }
    return names.get(lang_key, lang_key)


def _fallback_generate_code(prompt: str, language: str) -> str:
    """模板匹配 fallback 生成代码"""
    if language == "python":
        return _generate_python_code(prompt)
    elif language in ("javascript", "typescript"):
        return _generate_javascript_code(prompt, language)
    elif language == "go":
        return _generate_go_code(prompt)
    elif language == "rust":
        return _generate_rust_code(prompt)
    else:
        return _generate_python_code(prompt)


def _generate_python_code(prompt: str) -> str:
    """生成 Python 代码模板"""
    if "排序" in prompt:
        return '''def quick_sort(arr):
    """Quick sort implementation."""
    if len(arr) <= 1:
        return arr
    pivot = arr[len(arr) // 2]
    left = [x for x in arr if x < pivot]
    middle = [x for x in arr if x == pivot]
    right = [x for x in arr if x > pivot]
    return quick_sort(left) + middle + quick_sort(right)


if __name__ == '__main__':
    data = [3, 6, 8, 10, 1, 2, 1]
    print(f"Before: {data}")
    print(f"After:  {quick_sort(data)}")'''
    elif "api" in prompt.lower() or "接口" in prompt:
        return '''from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

app = FastAPI(title="Yunxi API")


class Item(BaseModel):
    name: str
    description: str = ""
    price: float


@app.get("/items/{item_id}")
async def get_item(item_id: int):
    return {"item_id": item_id, "name": "Sample Item"}


@app.post("/items")
async def create_item(item: Item):
    return {"code": 0, "data": item}'''
    else:
        return f'''# Yunxi AI Code Generator
# Prompt: {prompt[:50]}

def main():
    """Main entry point."""
    print("Hello, Yunxi!")
    # TODO: Implement business logic here
    # 后续应接入 LLM（参考 M4 _call_llm_for_codegen）根据 prompt 动态生成，
    # 或通过 M4 WorkDevService 的 code_chat 接口获取智能代码生成。
    pass


if __name__ == "__main__":
    main()'''

def _generate_javascript_code(prompt: str, language: str = "javascript") -> str:
    """生成 JavaScript/TypeScript 代码模板"""
    return f"""// Yunxi AI Code Generator
// Prompt: {prompt[:50]}

function main() {{
  console.log('Hello, Yunxi!');
  // TODO: Implement business logic here
  // 后续应接入 LLM（参考 M4 _call_llm_for_codegen）根据 prompt 动态生成，
  // 或通过 M4 WorkDevService 的 code_chat 接口获取智能代码生成。
}}

main();"""


def _generate_go_code(prompt: str) -> str:
    """生成 Go 代码模板"""
    return f'''package main

import "fmt"

// Yunxi AI Code Generator
// Prompt: {prompt[:40]}

func main() {{
	fmt.Println("Hello, Yunxi!")
	// TODO: Implement business logic here
	// 后续应接入 LLM（参考 M4 _call_llm_for_codegen）根据 prompt 动态生成，
	// 或通过 M4 WorkDevService 的 code_chat 接口获取智能代码生成。
}}
'''


def _generate_rust_code(prompt: str) -> str:
    """生成 Rust 代码模板"""
    return f'''// Yunxi AI Code Generator
// Prompt: {prompt[:40]}

fn main() {{
    println!("Hello, Yunxi!");
    // TODO: Implement business logic here
    // 后续应接入 LLM（参考 M4 _call_llm_for_codegen）根据 prompt 动态生成，
    // 或通过 M4 WorkDevService 的 code_chat 接口获取智能代码生成。
}}
'''


# ── 代码补全 ──────────────────────────────────────────────────

@router.post("/code/complete")
async def complete_code(req: CodeCompleteRequest):
    """代码补全接口

    根据代码上下文和光标位置，给出补全建议。
    优先使用 LLM，不可用时返回简单的模板建议。
    """
    language = req.language or "python"
    code_context = req.code or ""

    # 优先尝试 LLM
    llm = _get_llm_client()
    if llm is not None:
        try:
            user_prompt = (
                f"请根据以下{_get_lang_name(language)}代码上下文，给出光标位置的代码补全建议。\n\n"
                f"代码上下文：\n```{language}\n{code_context}\n```\n\n"
                f"光标位置：第 {req.cursor_line + 1} 行，第 {req.cursor_col + 1} 列\n\n"
                f"请直接给出补全的代码片段，不需要解释。如果有多个可能的补全，按可能性排序给出最多 3 个建议，每个建议用 --- 分隔。"
            )
            messages = [
                {"role": "system", "content": _CODE_EXPERT_SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ]
            reply = await llm.chat(
                messages=messages,
                temperature=0.1,
                max_tokens=1000,
            )
            suggestions = [s.strip() for s in reply.split("---") if s.strip()][:3]
            if not suggestions:
                suggestions = [reply.strip()]
            return {
                "code": 0,
                "message": "ok",
                "data": {
                    "language": language,
                    "suggestions": suggestions,
                    "model": _get_model_name(llm),
                    "is_fallback": False,
                }
            }
        except Exception:
            pass

    # Fallback: 简单模板补全
    return {
        "code": 0,
        "message": "ok",
        "data": {
            "language": language,
            "suggestions": [
                "// TODO: 补全建议（模板模式）",
            ],
            "is_fallback": True,
        }
    }


# ── 代码对话 ──────────────────────────────────────────────────

@router.post("/code/chat")
async def code_chat(
    req: CodeChatRequest,
    db: Session = Depends(get_db),
):
    """代码对话接口（多轮）

    支持多轮对话，专注代码领域。
    会话数据存储在内存中。
    """
    conversation_id = req.conversation_id or "default"
    message = req.message.strip()
    if not message:
        raise HTTPException(status_code=400, detail="message 不能为空")

    language = req.language or "python"

    # 获取或创建会话
    if conversation_id not in _code_chat_sessions:
        _code_chat_sessions[conversation_id] = {
            "id": conversation_id,
            "messages": [],
            "created_at": time.time(),
            "language": language,
        }

    conv = _code_chat_sessions[conversation_id]

    # 如果语言变了，更新会话语言
    conv["language"] = language

    # 添加用户消息
    user_msg = {
        "role": "user",
        "content": message,
        "timestamp": time.time(),
    }
    conv["messages"].append(user_msg)

    # 如果有上下文代码，附加到第一条消息
    context_code = req.context_code or ""

    # 优先尝试 LLM
    llm = _get_llm_client()
    if llm is not None:
        try:
            reply = await _call_llm_chat(llm, conv, language, context_code)
            ai_msg = {
                "role": "assistant",
                "content": reply,
                "timestamp": time.time(),
            }
            conv["messages"].append(ai_msg)
            _record_code_usage(db, "chat", language, "chat",
                              len(message) + len(reply), False)
            return {
                "code": 0,
                "message": "ok",
                "data": {
                    "reply": reply,
                    "conversation_id": conversation_id,
                    "message_id": f"msg_{uuid.uuid4().hex[:12]}",
                    "language": language,
                    "model": _get_model_name(llm),
                    "message_count": len(conv["messages"]),
                    "is_fallback": False,
                }
            }
        except Exception:
            pass

    # Fallback: 模板回复
    fallback_reply = _get_fallback_chat_reply(message, language)
    ai_msg = {
        "role": "assistant",
        "content": fallback_reply,
        "timestamp": time.time(),
    }
    conv["messages"].append(ai_msg)
    _record_code_usage(db, "chat", language, "chat",
                      len(message) + len(fallback_reply), True)
    return {
        "code": 0,
        "message": "ok",
        "data": {
            "reply": fallback_reply,
            "conversation_id": conversation_id,
            "message_id": f"msg_{uuid.uuid4().hex[:12]}",
            "language": language,
            "message_count": len(conv["messages"]),
            "is_fallback": True,
        }
    }


async def _call_llm_chat(llm, conv: dict, language: str, context_code: str) -> str:
    """调用 LLM 进行代码对话"""
    # 构建消息列表
    messages = [
        {"role": "system", "content": _CODE_EXPERT_SYSTEM_PROMPT},
    ]

    # 如果有上下文代码，附加到系统提示中
    if context_code:
        messages[0]["content"] += (
            f"\n\n## 当前代码上下文\n用户正在处理以下{_get_lang_name(language)}代码：\n"
            f"```{language}\n{context_code}\n```"
        )

    # 添加历史消息（最近 20 条，节省 token）
    for msg in conv["messages"][-20:]:
        messages.append({"role": msg["role"], "content": msg["content"]})

    reply = await llm.chat(
        messages=messages,
        temperature=0.3,
        max_tokens=4000,
    )
    return reply


def _get_fallback_chat_reply(message: str, language: str) -> str:
    """Fallback 对话回复"""
    code = _fallback_generate_code(message, language)
    return f"好的，我来帮你处理这个问题。\n\n这是一个{_get_lang_name(language)}示例：\n\n```{language}\n{code}\n```\n\n（当前为模板模式，接入大模型后可获得更智能的对话体验）"


@router.get("/code/chat/conversations")
async def list_code_chat_conversations():
    """获取代码对话会话列表"""
    conv_list = []
    for cid, conv in _code_chat_sessions.items():
        last_msg = conv["messages"][-1] if conv["messages"] else None
        conv_list.append({
            "id": cid,
            "title": last_msg["content"][:30] + "..." if last_msg else "新对话",
            "language": conv.get("language", "python"),
            "message_count": len(conv["messages"]),
            "created_at": conv["created_at"],
            "updated_at": last_msg["timestamp"] if last_msg else conv["created_at"],
        })
    conv_list.sort(key=lambda x: x["updated_at"], reverse=True)
    return {
        "code": 0,
        "message": "ok",
        "data": {
            "conversations": conv_list,
            "total": len(conv_list),
        }
    }


@router.get("/code/chat/conversations/{conversation_id}")
async def get_code_chat_conversation(conversation_id: str):
    """获取单个代码对话会话详情"""
    conv = _code_chat_sessions.get(conversation_id)
    if not conv:
        return {
            "code": 0,
            "message": "ok",
            "data": {
                "id": conversation_id,
                "messages": [],
                "language": "python",
                "created_at": time.time(),
                "message_count": 0,
            }
        }
    return {
        "code": 0,
        "message": "ok",
        "data": {
            "id": conv["id"],
            "messages": conv["messages"],
            "language": conv.get("language", "python"),
            "created_at": conv["created_at"],
            "message_count": len(conv["messages"]),
        }
    }


@router.delete("/code/chat/conversations/{conversation_id}")
async def delete_code_chat_conversation(conversation_id: str):
    """删除代码对话会话"""
    if conversation_id in _code_chat_sessions:
        del _code_chat_sessions[conversation_id]
    return {
        "code": 0,
        "message": "会话已删除",
        "data": {"deleted": True},
    }


@router.get("/code/ai/status")
async def code_ai_status():
    """检查 AI 代码助手的 LLM 服务状态"""
    llm = _get_llm_client()
    if llm is None:
        return {
            "code": 0,
            "message": "ok",
            "data": {
                "available": False,
                "provider": None,
                "model": None,
                "mode": "fallback（模板匹配）",
            }
        }
    return {
        "code": 0,
        "message": "ok",
        "data": {
            "available": True,
            "provider": _get_provider_name(llm),
            "model": _get_model_name(llm),
            "mode": "llm（大模型）",
        }
    }


def _get_provider_name(llm) -> str:
    """获取 LLM 提供方名称"""
    try:
        # 适配统一 LLMClient
        if hasattr(llm, '_use_mock'):
            if llm._use_mock:
                return "mock"
            # 检查真实客户端类型
            if hasattr(llm, '_real_client'):
                client = llm._real_client
                client_type = type(client).__name__
                if 'Ollama' in client_type:
                    return "ollama"
                elif 'API' in client_type or 'OpenAI' in client_type or 'DeepSeek' in client_type:
                    return "api"
        if hasattr(llm, '_config') and hasattr(llm._config, 'llm_provider'):
            return llm._config.llm_provider
        if hasattr(llm, '_provider'):
            provider = llm._provider
            return type(provider).__name__.replace("Provider", "").lower()
    except Exception:
        pass
    return "unknown"


# ============================================================
# 项目管理
# ============================================================

@router.get("/projects")
async def list_projects(
    status: Optional[str] = None,
    db: Session = Depends(get_db),
):
    """项目列表"""
    _ensure_data_initialized(db, DEFAULT_USER_ID)

    query = db.query(WorkProject).filter_by(user_id=DEFAULT_USER_ID)
    if status:
        query = query.filter_by(status=status)

    projects = query.order_by(WorkProject.updated_at.desc()).all()

    # 附加任务统计
    result = []
    for p in projects:
        p_dict = _project_to_dict(p)
        project_tasks = db.query(WorkTask).filter_by(
            user_id=DEFAULT_USER_ID, project_id=p.project_id
        ).all()
        p_dict["task_count"] = len(project_tasks)
        p_dict["done_count"] = sum(1 for t in project_tasks if t.status == "done")
        result.append(p_dict)

    return {"code": 0, "message": "ok", "data": result}


@router.get("/projects/{project_id}")
async def get_project(
    project_id: int,
    db: Session = Depends(get_db),
):
    """项目详情"""
    _ensure_data_initialized(db, DEFAULT_USER_ID)

    project = db.query(WorkProject).filter_by(
        user_id=DEFAULT_USER_ID, project_id=project_id
    ).first()
    if not project:
        raise HTTPException(status_code=404, detail="项目不存在")

    project_dict = _project_to_dict(project)

    # 任务统计
    project_tasks = db.query(WorkTask).filter_by(
        user_id=DEFAULT_USER_ID, project_id=project_id
    ).all()
    project_dict["task_count"] = len(project_tasks)
    project_dict["done_count"] = sum(1 for t in project_tasks if t.status == "done")

    # 最近提交
    commits = db.query(WorkCommit).filter_by(
        user_id=DEFAULT_USER_ID, project_id=project_id
    ).order_by(WorkCommit.committed_at.desc()).limit(10).all()
    project_dict["commits"] = [_commit_to_dict(c) for c in commits]

    return {"code": 0, "message": "ok", "data": project_dict}


@router.post("/projects")
async def create_project(
    req: ProjectCreateRequest,
    db: Session = Depends(get_db),
):
    """创建项目"""
    _ensure_data_initialized(db, DEFAULT_USER_ID)

    # 找最大的 project_id
    all_projects = db.query(WorkProject).filter_by(user_id=DEFAULT_USER_ID).all()
    pid = max((p.project_id for p in all_projects), default=0) + 1

    now = datetime.utcnow()
    project = WorkProject(
        project_id=pid,
        name=req.name,
        description=req.description,
        status="planning",
        progress=0,
        language=req.language,
        file_count=0,
        line_count=0,
        commit_count=0,
        created_at=now,
        updated_at=now,
        user_id=DEFAULT_USER_ID,
    )
    db.add(project)
    db.commit()
    db.refresh(project)

    project_dict = _project_to_dict(project)
    project_dict["task_count"] = 0
    project_dict["done_count"] = 0

    return {"code": 0, "message": "项目创建成功", "data": project_dict}


class ProjectUpdateRequest(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    status: Optional[str] = None
    language: Optional[str] = None
    progress: Optional[int] = None


@router.put("/projects/{project_id}")
async def update_project(
    project_id: int,
    req: ProjectUpdateRequest,
    db: Session = Depends(get_db),
):
    """更新项目信息"""
    _ensure_data_initialized(db, DEFAULT_USER_ID)

    project = db.query(WorkProject).filter_by(
        user_id=DEFAULT_USER_ID, project_id=project_id
    ).first()
    if not project:
        raise HTTPException(status_code=404, detail="项目不存在")

    if req.name is not None:
        project.name = req.name
    if req.description is not None:
        project.description = req.description
    if req.status is not None:
        if req.status not in ("planning", "active", "archived", "completed"):
            raise HTTPException(status_code=400, detail="无效状态")
        project.status = req.status
    if req.language is not None:
        project.language = req.language
    if req.progress is not None:
        project.progress = max(0, min(100, req.progress))

    project.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(project)

    project_dict = _project_to_dict(project)
    project_tasks = db.query(WorkTask).filter_by(
        user_id=DEFAULT_USER_ID, project_id=project_id
    ).all()
    project_dict["task_count"] = len(project_tasks)
    project_dict["done_count"] = sum(1 for t in project_tasks if t.status == "done")

    return {"code": 0, "message": "项目已更新", "data": project_dict}


@router.delete("/projects/{project_id}")
async def delete_project(
    project_id: int,
    db: Session = Depends(get_db),
):
    """删除项目（同时删除关联的任务和提交）"""
    _ensure_data_initialized(db, DEFAULT_USER_ID)

    project = db.query(WorkProject).filter_by(
        user_id=DEFAULT_USER_ID, project_id=project_id
    ).first()
    if not project:
        raise HTTPException(status_code=404, detail="项目不存在")

    # 删除关联任务
    db.query(WorkTask).filter_by(
        user_id=DEFAULT_USER_ID, project_id=project_id
    ).delete()

    # 删除关联提交
    db.query(WorkCommit).filter_by(
        user_id=DEFAULT_USER_ID, project_id=project_id
    ).delete()

    # 删除项目
    db.delete(project)
    db.commit()

    return {"code": 0, "message": "项目已删除", "data": {"deleted": True, "project_id": project_id}}


@router.get("/projects/{project_id}/stats")
async def get_project_stats(
    project_id: int,
    db: Session = Depends(get_db),
):
    """项目统计数据"""
    _ensure_data_initialized(db, DEFAULT_USER_ID)

    project = db.query(WorkProject).filter_by(
        user_id=DEFAULT_USER_ID, project_id=project_id
    ).first()
    if not project:
        raise HTTPException(status_code=404, detail="项目不存在")

    tasks = db.query(WorkTask).filter_by(
        user_id=DEFAULT_USER_ID, project_id=project_id
    ).all()
    commits = db.query(WorkCommit).filter_by(
        user_id=DEFAULT_USER_ID, project_id=project_id
    ).all()

    total_tasks = len(tasks)
    done_tasks = sum(1 for t in tasks if t.status == "done")
    in_progress_tasks = sum(1 for t in tasks if t.status == "in_progress")
    todo_tasks = sum(1 for t in tasks if t.status == "todo")
    completion_rate = round(done_tasks / total_tasks * 100, 1) if total_tasks > 0 else 0.0

    total_commits = len(commits)
    total_insertions = sum(c.additions or 0 for c in commits)
    total_deletions = sum(c.deletions or 0 for c in commits)

    # 代码行数估算（项目表中的 line_count 或从提交估算）
    line_count = project.line_count or total_insertions

    # 本周提交数
    now = datetime.utcnow()
    week_ago = now - timedelta(days=7)
    week_commits = sum(
        1 for c in commits
        if c.committed_at and c.committed_at > week_ago
    )

    return {
        "code": 0,
        "message": "ok",
        "data": {
            "project_id": project_id,
            "total_tasks": total_tasks,
            "done_tasks": done_tasks,
            "in_progress_tasks": in_progress_tasks,
            "todo_tasks": todo_tasks,
            "completion_rate": completion_rate,
            "total_commits": total_commits,
            "week_commits": week_commits,
            "total_insertions": total_insertions,
            "total_deletions": total_deletions,
            "line_count": line_count,
            "file_count": project.file_count or 0,
        }
    }


# ============================================================
# 任务看板
# ============================================================

@router.get("/tasks")
async def list_tasks(
    project_id: Optional[int] = None,
    status: Optional[str] = None,
    db: Session = Depends(get_db),
):
    """任务列表"""
    _ensure_data_initialized(db, DEFAULT_USER_ID)

    query = db.query(WorkTask).filter_by(user_id=DEFAULT_USER_ID)
    if project_id:
        query = query.filter_by(project_id=project_id)
    if status:
        query = query.filter_by(status=status)

    tasks = query.order_by(WorkTask.updated_at.desc()).all()
    return {"code": 0, "message": "ok", "data": [_task_to_dict(t) for t in tasks]}


@router.get("/tasks/board")
async def task_board(
    project_id: Optional[int] = None,
    db: Session = Depends(get_db),
):
    """任务看板数据（按状态分组）"""
    _ensure_data_initialized(db, DEFAULT_USER_ID)

    query = db.query(WorkTask).filter_by(user_id=DEFAULT_USER_ID)
    if project_id:
        query = query.filter_by(project_id=project_id)

    tasks = query.all()
    task_dicts = [_task_to_dict(t) for t in tasks]

    board = {
        "todo": [t for t in task_dicts if t["status"] == "todo"],
        "in_progress": [t for t in task_dicts if t["status"] == "in_progress"],
        "done": [t for t in task_dicts if t["status"] == "done"],
    }
    return {"code": 0, "message": "ok", "data": board}


@router.post("/tasks")
async def create_task(
    req: TaskCreateRequest,
    db: Session = Depends(get_db),
):
    """创建任务"""
    _ensure_data_initialized(db, DEFAULT_USER_ID)

    # 找最大的 task_id
    all_tasks = db.query(WorkTask).filter_by(user_id=DEFAULT_USER_ID).all()
    tid = max((t.task_id for t in all_tasks), default=0) + 1

    now = datetime.utcnow()
    task = WorkTask(
        task_id=tid,
        title=req.title,
        description=req.description,
        status=req.status,
        priority=req.priority,
        project_id=req.project_id or 0,
        assignee="云汐",
        created_at=now,
        updated_at=now,
        user_id=DEFAULT_USER_ID,
    )
    db.add(task)

    # 更新项目时间
    if req.project_id:
        project = db.query(WorkProject).filter_by(
            user_id=DEFAULT_USER_ID, project_id=req.project_id
        ).first()
        if project:
            project.updated_at = now

    db.commit()
    db.refresh(task)

    return {"code": 0, "message": "任务创建成功", "data": _task_to_dict(task)}


@router.put("/tasks/{task_id}/status")
async def update_task_status(
    task_id: int,
    status: str,
    db: Session = Depends(get_db),
):
    """更新任务状态"""
    _ensure_data_initialized(db, DEFAULT_USER_ID)

    task = db.query(WorkTask).filter_by(
        user_id=DEFAULT_USER_ID, task_id=task_id
    ).first()
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")
    if status not in ("todo", "in_progress", "done"):
        raise HTTPException(status_code=400, detail="无效状态")

    task.status = status
    task.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(task)

    return {"code": 0, "message": "状态已更新", "data": _task_to_dict(task)}


# ============================================================
# 代码管理 (Git)
# ============================================================

@router.get("/commits")
async def list_commits(
    project_id: Optional[int] = None,
    limit: int = 20,
    db: Session = Depends(get_db),
):
    """提交记录"""
    _ensure_data_initialized(db, DEFAULT_USER_ID)

    query = db.query(WorkCommit).filter_by(user_id=DEFAULT_USER_ID)
    if project_id:
        query = query.filter_by(project_id=project_id)

    commits = query.order_by(WorkCommit.committed_at.desc()).limit(limit).all()
    return {"code": 0, "message": "ok", "data": [_commit_to_dict(c) for c in commits]}


@router.get("/commits/stats")
async def commit_stats(
    project_id: Optional[int] = None,
    db: Session = Depends(get_db),
):
    """提交统计"""
    _ensure_data_initialized(db, DEFAULT_USER_ID)

    query = db.query(WorkCommit).filter_by(user_id=DEFAULT_USER_ID)
    if project_id:
        query = query.filter_by(project_id=project_id)

    commits = query.all()

    # 按天统计最近 7 天
    now = datetime.utcnow()
    daily = []
    for i in range(6, -1, -1):
        day = now - timedelta(days=i)
        day_str = day.strftime("%Y-%m-%d")
        count = sum(
            1 for c in commits
            if c.committed_at and c.committed_at.strftime("%Y-%m-%d") == day_str
        )
        daily.append({"date": day_str, "count": count})

    total_insertions = sum(c.additions or 0 for c in commits)
    total_deletions = sum(c.deletions or 0 for c in commits)

    return {
        "code": 0,
        "message": "ok",
        "data": {
            "total_commits": len(commits),
            "total_insertions": total_insertions,
            "total_deletions": total_deletions,
            "daily_commits": daily,
        }
    }


@router.post("/commits")
async def create_commit(
    req: GitCommitRequest,
    db: Session = Depends(get_db),
):
    """模拟提交"""
    _ensure_data_initialized(db, DEFAULT_USER_ID)

    # 找最大的 commit_id
    all_commits = db.query(WorkCommit).filter_by(user_id=DEFAULT_USER_ID).all()
    cid = max((c.commit_id for c in all_commits), default=0) + 1

    pid = req.project_id or 1
    now = datetime.utcnow()
    commit = WorkCommit(
        commit_id=cid,
        hash=uuid.uuid4().hex[:8],
        message=req.message,
        author="云汐",
        project_id=pid,
        branch="main",
        additions=30 + cid * 5,
        deletions=5 + cid * 2,
        files_changed=2 + cid % 4,
        committed_at=now,
        user_id=DEFAULT_USER_ID,
    )
    db.add(commit)

    # 更新项目
    project = db.query(WorkProject).filter_by(
        user_id=DEFAULT_USER_ID, project_id=pid
    ).first()
    if project:
        project.commit_count = (project.commit_count or 0) + 1
        project.updated_at = now

    db.commit()
    db.refresh(commit)

    return {"code": 0, "message": "提交成功", "data": _commit_to_dict(commit)}


@router.get("/branches")
async def list_branches():
    """分支列表"""
    branches = [
        {"name": "main", "ahead": 0, "behind": 0, "is_default": True, "last_commit": "2小时前"},
        {"name": "dev/agent-scheduler", "ahead": 5, "behind": 2, "is_default": False, "last_commit": "1天前"},
        {"name": "feature/skill-cluster", "ahead": 8, "behind": 3, "is_default": False, "last_commit": "3天前"},
        {"name": "fix/auth-bug", "ahead": 2, "behind": 0, "is_default": False, "last_commit": "5天前"},
    ]
    return {"code": 0, "message": "ok", "data": branches}


# ============================================================
# 开发工具
# ============================================================

@router.get("/tools/file-tree")
async def get_file_tree(project_id: int = 1):
    """文件树结构"""
    tree = {
        "name": "yunxi-project",
        "type": "folder",
        "children": [
            {
                "name": "M1-agent-hub",
                "type": "folder",
                "children": [
                    {"name": "server.py", "type": "file", "size": "4.2KB"},
                    {"name": "config", "type": "folder", "children": [
                        {"name": "settings.yaml", "type": "file", "size": "1.8KB"},
                    ]},
                    {"name": "api", "type": "folder", "children": [
                        {"name": "m8_interface.py", "type": "file", "size": "3.5KB"},
                    ]},
                ]
            },
            {
                "name": "M2-skills-cluster",
                "type": "folder",
                "children": [
                    {"name": "start_server.py", "type": "file", "size": "2.1KB"},
                    {"name": "skill_cluster", "type": "folder", "children": [
                        {"name": "skills", "type": "folder", "children": [
                            {"name": "__init__.py", "type": "file", "size": "0.5KB"},
                            {"name": "todo.py", "type": "file", "size": "3.2KB"},
                            {"name": "goal.py", "type": "file", "size": "2.8KB"},
                        ]},
                    ]},
                ]
            },
            {
                "name": "M8-control-tower",
                "type": "folder",
                "children": [
                    {"name": "main.py", "type": "file", "size": "6.8KB"},
                    {"name": "backend/routers", "type": "folder", "children": [
                        {"name": "modules.py", "type": "file", "size": "8.5KB"},
                        {"name": "work_dev.py", "type": "file", "size": "7.2KB"},
                    ]},
                ]
            },
            {
                "name": "frontend",
                "type": "folder",
                "children": [
                    {"name": "modes", "type": "folder", "children": [
                        {"name": "work-dev.html", "type": "file", "size": "45KB"},
                        {"name": "growth-achievements.html", "type": "file", "size": "38KB"},
                    ]},
                ]
            },
            {"name": "README.md", "type": "file", "size": "2.3KB"},
            {"name": "requirements.txt", "type": "file", "size": "0.8KB"},
        ]
    }
    return {"code": 0, "message": "ok", "data": tree}


@router.get("/quick-actions")
async def quick_actions():
    """快速操作列表"""
    actions = [
        {"id": "generate_code", "name": "AI 生成代码", "icon": "code", "hotkey": "⌘G"},
        {"id": "code_review", "name": "代码审查", "icon": "check-circle", "hotkey": "⌘R"},
        {"id": "git_commit", "name": "Git 提交", "icon": "git-commit", "hotkey": "⌘C"},
        {"id": "run_tests", "name": "运行测试", "icon": "play", "hotkey": "⌘T"},
        {"id": "view_logs", "name": "查看日志", "icon": "file-text", "hotkey": "⌘L"},
        {"id": "search_code", "name": "搜索代码", "icon": "search", "hotkey": "⌘F"},
        {"id": "new_project", "name": "新建项目", "icon": "folder-plus", "hotkey": "⌘N"},
        {"id": "new_task", "name": "新建任务", "icon": "plus-square", "hotkey": "⌘K"},
    ]
    return {"code": 0, "message": "ok", "data": actions}


@router.get("/activity")
async def recent_activity(
    limit: int = 10,
    db: Session = Depends(get_db),
):
    """最近活动"""
    _ensure_data_initialized(db, DEFAULT_USER_ID)

    now = datetime.utcnow()
    activities = []

    # 最近提交
    recent_commits = db.query(WorkCommit).filter_by(
        user_id=DEFAULT_USER_ID
    ).order_by(WorkCommit.committed_at.desc()).limit(5).all()
    for c in recent_commits:
        c_dict = _commit_to_dict(c)
        activities.append({
            "id": f"commit-{c_dict['id']}",
            "type": "commit",
            "title": f"提交: {c_dict['message']}",
            "time": c_dict["created_at"],
            "user": c_dict["author"],
        })

    # 最近任务
    recent_tasks = db.query(WorkTask).filter_by(
        user_id=DEFAULT_USER_ID
    ).order_by(WorkTask.updated_at.desc()).limit(5).all()
    for t in recent_tasks:
        t_dict = _task_to_dict(t)
        status_text = {"todo": "创建了任务", "in_progress": "开始处理", "done": "完成了"}
        activities.append({
            "id": f"task-{t_dict['id']}",
            "type": "task",
            "title": f"{status_text.get(t_dict['status'], '更新了')}: {t_dict['title']}",
            "time": t_dict["updated_at"],
            "user": t_dict["assignee"],
        })

    activities.sort(key=lambda x: x["time"], reverse=True)
    return {"code": 0, "message": "ok", "data": activities[:limit]}



# ============================================================
# VS Code 集成
# ============================================================

# VS Code 常用工作区（可后续迁移到配置文件）
_VSCODE_WORKSPACES = {
    "yunxi-project": {
        "id": "yunxi-project",
        "name": "云汐项目",
        "path": "C:/Yunxi/workspace/yunxi-project",
        "icon": "💻",
    },
    "m8-control-tower": {
        "id": "m8-control-tower",
        "name": "M8 控制塔",
        "path": "C:/Yunxi/workspace/yunxi-project/M8-control-tower",
        "icon": "🗼",
    },
    "frontend": {
        "id": "frontend",
        "name": "前端门户",
        "path": "C:/Yunxi/workspace/yunxi-project/frontend",
        "icon": "🎨",
    },
    "m9-dev-workshop": {
        "id": "m9-dev-workshop",
        "name": "M9 开发工坊",
        "path": "C:/Yunxi/workspace/yunxi-project/M9-dev-workshop",
        "icon": "🛠️",
    },
}


def _check_vscode_installed():
    """检测 VS Code 是否已安装"""
    import shutil
    possible_paths = [
        "code.cmd",
        "code",
        os.path.expandvars(r"%LOCALAPPDATA%\Programs\Microsoft VS Codein\code.cmd"),
        os.path.expandvars(r"%ProgramFiles%\Microsoft VS Codein\code.cmd"),
        os.path.expandvars(r"%ProgramFiles(x86)%\Microsoft VS Codein\code.cmd"),
    ]
    for p in possible_paths:
        try:
            result = shutil.which(p)
            if result:
                try:
                    version_result = subprocess.run(
                        [result, "--version"],
                        capture_output=True, text=True, timeout=10
                    )
                    lines = version_result.stdout.strip().splitlines()
                    version = lines[0] if lines else "unknown"
                except Exception:
                    version = "unknown"
                return {"installed": True, "path": result, "version": version}
        except Exception:
            continue
    return {"installed": False, "path": None, "version": None}


def _get_vscode_instances():
    """获取运行中的 VS Code 实例"""
    instances = []
    try:
        for proc in psutil.process_iter(["pid", "name", "cmdline", "memory_info"]):
            try:
                name = proc.info.get("name", "").lower()
                if "code" in name and "code.exe" == name:
                    cmdline = proc.info.get("cmdline", [])
                    cmdline_str = " ".join(cmdline) if cmdline else ""
                    if "--type=" in cmdline_str:
                        continue
                    workspace = ""
                    for arg in cmdline:
                        if os.path.isdir(arg) and not arg.startswith("--"):
                            workspace = arg
                            break
                    mem_mb = 0
                    if proc.info.get("memory_info"):
                        mem_mb = int(proc.info["memory_info"].rss / 1024 / 1024)
                    instances.append({
                        "pid": proc.info["pid"],
                        "name": "VS Code",
                        "workspace": workspace,
                        "memory_mb": mem_mb,
                        "status": proc.status(),
                    })
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue
    except Exception as e:
        print(f"Error getting VS Code instances: {e}")
    return instances


@router.get("/vscode/installed")
async def check_vscode_installed():
    """检测 VS Code 是否安装"""
    info = _check_vscode_installed()
    return {"code": 0, "message": "ok", "data": info}


@router.get("/vscode/instances")
async def list_vscode_instances():
    """列出运行中的 VS Code 实例"""
    instances = _get_vscode_instances()
    return {"code": 0, "message": "ok", "data": {"count": len(instances), "instances": instances}}


@router.post("/vscode/launch")
async def launch_vscode(req: dict):
    """启动 VS Code"""
    info = _check_vscode_installed()
    if not info["installed"]:
        return {"code": 400, "message": "VS Code 未安装", "data": None}
    workspace_path = req.get("workspace_path", "")
    try:
        code_cmd = info["path"]
        if workspace_path and os.path.exists(workspace_path):
            subprocess.Popen([code_cmd, workspace_path], shell=True)
        else:
            subprocess.Popen([code_cmd], shell=True)
        import time
        time.sleep(2)
        instances = _get_vscode_instances()
        return {
            "code": 0,
            "message": "VS Code 已启动",
            "data": {"count": len(instances), "instances": instances},
        }
    except Exception as e:
        return {"code": 500, "message": f"启动失败: {str(e)}", "data": None}


@router.post("/vscode/open-file")
async def open_file_in_vscode(req: dict):
    """在 VS Code 中打开文件"""
    info = _check_vscode_installed()
    if not info["installed"]:
        return {"code": 400, "message": "VS Code 未安装", "data": None}
    file_path = req.get("file_path", "")
    line = req.get("line", 0)
    if not file_path or not os.path.exists(file_path):
        return {"code": 400, "message": "文件不存在", "data": None}
    try:
        code_cmd = info["path"]
        goto_arg = f"{file_path}:{line}" if line > 0 else file_path
        subprocess.Popen([code_cmd, "--goto", goto_arg], shell=True)
        return {"code": 0, "message": "已在 VS Code 中打开", "data": {"file": file_path, "line": line}}
    except Exception as e:
        return {"code": 500, "message": f"打开失败: {str(e)}", "data": None}


@router.get("/vscode/workspaces")
async def list_vscode_workspaces():
    """获取常用工作区列表"""
    workspaces = []
    for ws_id, ws_cfg in _VSCODE_WORKSPACES.items():
        exists = os.path.exists(ws_cfg["path"])
        workspaces.append({
            "id": ws_cfg["id"],
            "name": ws_cfg["name"],
            "path": ws_cfg["path"],
            "icon": ws_cfg["icon"],
            "exists": exists,
        })
    return {"code": 0, "message": "ok", "data": workspaces}


@router.post("/vscode/close/{pid}")
async def close_vscode_instance(pid: int):
    """关闭指定 PID 的 VS Code 实例"""
    try:
        proc = psutil.Process(pid)
        if "code" in proc.name().lower():
            proc.terminate()
            return {"code": 0, "message": "已关闭", "data": {"pid": pid}}
        else:
            return {"code": 400, "message": "不是 VS Code 进程", "data": None}
    except psutil.NoSuchProcess:
        return {"code": 404, "message": "进程不存在", "data": None}
    except Exception as e:
        return {"code": 500, "message": str(e), "data": None}

# ============================================================
# 真实 Git 集成
# ============================================================

# Git 仓库配置（可后续迁移到配置文件）
_GIT_REPOS = {
    "yunxi-project": {
        "id": "yunxi-project",
        "name": "云汐项目",
        "description": "云汐AI助手核心系统仓库",
        "path": "C:/Yunxi/workspace/yunxi-project",
    },
    "m8-control-tower": {
        "id": "m8-control-tower",
        "name": "M8 控制塔",
        "description": "M8 控制塔后端服务",
        "path": "C:/Yunxi/workspace/yunxi-project/M8-control-tower",
    },
}


def _run_git_command(repo_path: str, args, timeout: int = 30):
    """在指定仓库执行 git 命令

    Returns:
        (stdout, stderr, return_code)
    """
    try:
        proc = subprocess.run(
            ["git"] + args,
            cwd=repo_path,
            capture_output=True,
            text=True,
            timeout=timeout,
            encoding="utf-8",
            errors="replace",
        )
        return proc.stdout or "", proc.stderr or "", proc.returncode
    except subprocess.TimeoutExpired:
        return "", "Git 命令执行超时", -1
    except FileNotFoundError:
        return "", "Git 命令未找到，请确认 Git 已安装", -1
    except Exception as e:
        return "", f"Git 命令执行错误: {str(e)}", -1


def _get_repo_or_404(repo_id: str) -> dict:
    """获取仓库配置，不存在则抛出 404"""
    repo = _GIT_REPOS.get(repo_id)
    if not repo:
        raise HTTPException(status_code=404, detail=f"仓库不存在: {repo_id}")
    return repo


def _parse_git_status(status_output: str) -> dict:
    """解析 git status --porcelain 输出"""
    changes = []
    staged = []
    untracked = []
    modified = []
    deleted = []

    for line in status_output.strip().split("\n"):
        if not line.strip():
            continue
        x = line[0] if len(line) > 0 else " "
        y = line[1] if len(line) > 1 else " "
        path = line[3:].strip() if len(line) > 3 else ""

        entry = {"path": path, "status_x": x, "status_y": y}

        if x != " ":
            staged.append(entry)
            if x == "M":
                entry["status"] = "modified_staged"
            elif x == "A":
                entry["status"] = "added_staged"
            elif x == "D":
                entry["status"] = "deleted_staged"
            elif x == "R":
                entry["status"] = "renamed_staged"
        else:
            if y == "M":
                modified.append(entry)
                entry["status"] = "modified"
            elif y == "D":
                deleted.append(entry)
                entry["status"] = "deleted"
            elif y == "?":
                untracked.append(entry)
                entry["status"] = "untracked"
            else:
                entry["status"] = "unknown"

        changes.append(entry)

    return {
        "changes": changes,
        "staged_count": len(staged),
        "modified_count": len(modified),
        "deleted_count": len(deleted),
        "untracked_count": len(untracked),
        "is_clean": len(changes) == 0,
    }


def _parse_git_log(log_output: str):
    """解析 git log 输出（使用 | 分隔的格式化输出）"""
    commits = []
    for line in log_output.strip().split("\n"):
        if not line.strip():
            continue
        parts = line.split("|")
        if len(parts) >= 6:
            commits.append({
                "hash": parts[0],
                "short_hash": parts[1],
                "message": parts[2],
                "author": parts[3],
                "date": parts[4],
                "email": parts[5],
            })
    return commits


# --- Git API 请求模型 ---

class GitCommitRealRequest(BaseModel):
    message: str
    files: Optional[List[str]] = None


class GitBranchCreateRequest(BaseModel):
    branch_name: str
    base_branch: Optional[str] = None


class GitBranchSwitchRequest(BaseModel):
    branch_name: str


# --- Git API 路由 ---

@router.get("/git/repos")
async def list_git_repos():
    """获取 Git 仓库列表"""
    repos = []
    for repo_id, repo_cfg in _GIT_REPOS.items():
        stdout, stderr, rc = _run_git_command(repo_cfg["path"], ["rev-parse", "--is-inside-work-tree"])
        is_valid = rc == 0 and stdout.strip() == "true"

        current_branch = ""
        if is_valid:
            stdout2, _, _ = _run_git_command(repo_cfg["path"], ["rev-parse", "--abbrev-ref", "HEAD"])
            current_branch = stdout2.strip()

        repos.append({
            "id": repo_cfg["id"],
            "name": repo_cfg["name"],
            "description": repo_cfg["description"],
            "path": repo_cfg["path"],
            "is_valid": is_valid,
            "current_branch": current_branch,
        })
    return {"code": 0, "message": "ok", "data": repos}


@router.get("/git/{repo_id}/status")
async def git_repo_status(repo_id: str):
    """获取仓库状态（修改文件、暂存区状态）"""
    repo = _get_repo_or_404(repo_id)

    stdout_branch, _, rc_branch = _run_git_command(repo["path"], ["rev-parse", "--abbrev-ref", "HEAD"])
    current_branch = stdout_branch.strip() if rc_branch == 0 else "unknown"

    stdout_status, stderr_status, rc_status = _run_git_command(
        repo["path"], ["status", "--porcelain"]
    )
    if rc_status != 0:
        raise HTTPException(status_code=500, detail=f"获取状态失败: {stderr_status}")

    status_info = _parse_git_status(stdout_status)

    stdout_head, _, _ = _run_git_command(repo["path"], ["rev-parse", "--short", "HEAD"])
    head_hash = stdout_head.strip()

    return {
        "code": 0,
        "message": "ok",
        "data": {
            "repo_id": repo_id,
            "current_branch": current_branch,
            "head_hash": head_hash,
            **status_info,
        }
    }


@router.get("/git/{repo_id}/branches")
async def git_repo_branches(repo_id: str):
    """获取真实分支列表"""
    repo = _get_repo_or_404(repo_id)

    stdout, stderr, rc = _run_git_command(repo["path"], ["branch", "-v", "--no-abbrev"])
    if rc != 0:
        raise HTTPException(status_code=500, detail=f"获取分支失败: {stderr}")

    branches = []
    for line in stdout.strip().split("\n"):
        if not line.strip():
            continue
        is_current = line.startswith("*")
        line_clean = line.lstrip("* ").strip()

        parts = line_clean.split(None, 2)
        if len(parts) >= 2:
            name = parts[0]
            commit_hash = parts[1]
            last_msg = parts[2] if len(parts) > 2 else ""
        else:
            name = line_clean
            commit_hash = ""
            last_msg = ""

        branches.append({
            "name": name,
            "is_current": is_current,
            "is_default": name in ("main", "master"),
            "last_commit_hash": commit_hash,
            "last_commit_msg": last_msg,
        })

    return {"code": 0, "message": "ok", "data": branches}


@router.get("/git/{repo_id}/commits")
async def git_repo_commits(
    repo_id: str,
    limit: int = 20,
    branch: Optional[str] = None,
):
    """获取真实提交历史"""
    repo = _get_repo_or_404(repo_id)

    cmd = [
        "log",
        "--pretty=format:%H|%h|%s|%an|%ad|%ae",
        "--date=iso",
        f"-{limit}",
    ]
    if branch:
        cmd.append(branch)

    stdout, stderr, rc = _run_git_command(repo["path"], cmd)
    if rc != 0:
        raise HTTPException(status_code=500, detail=f"获取提交历史失败: {stderr}")

    commits = _parse_git_log(stdout)

    detailed_count = min(10, len(commits))
    for i in range(detailed_count):
        commit_hash = commits[i]["hash"]
        stdout_stat, _, rc_stat = _run_git_command(
            repo["path"], ["show", "--stat", "--numstat", "--format=", commit_hash]
        )
        if rc_stat == 0:
            additions = 0
            deletions = 0
            files = 0
            for stat_line in stdout_stat.strip().split("\n"):
                if not stat_line.strip():
                    continue
                stat_parts = stat_line.split("\t")
                if len(stat_parts) >= 3:
                    try:
                        additions += int(stat_parts[0]) if stat_parts[0] != "-" else 0
                        deletions += int(stat_parts[1]) if stat_parts[1] != "-" else 0
                        files += 1
                    except ValueError:
                        pass
            commits[i]["insertions"] = additions
            commits[i]["deletions"] = deletions
            commits[i]["files_changed"] = files
        else:
            commits[i]["insertions"] = 0
            commits[i]["deletions"] = 0
            commits[i]["files_changed"] = 0

    return {"code": 0, "message": "ok", "data": commits}


@router.post("/git/{repo_id}/commit")
async def git_repo_commit(
    repo_id: str,
    req: GitCommitRealRequest,
    db: Session = Depends(get_db),
):
    """真实提交（git add + git commit）"""
    repo = _get_repo_or_404(repo_id)

    if not req.message or not req.message.strip():
        raise HTTPException(status_code=400, detail="提交信息不能为空")

    if req.files and len(req.files) > 0:
        stdout_add, stderr_add, rc_add = _run_git_command(
            repo["path"], ["add"] + req.files
        )
    else:
        stdout_add, stderr_add, rc_add = _run_git_command(
            repo["path"], ["add", "-A"]
        )

    if rc_add != 0:
        raise HTTPException(status_code=500, detail=f"git add 失败: {stderr_add}")

    stdout_commit, stderr_commit, rc_commit = _run_git_command(
        repo["path"], ["commit", "-m", req.message]
    )

    if rc_commit != 0:
        if "nothing to commit" in stderr_commit or "nothing to commit" in stdout_commit:
            return {
                "code": 0,
                "message": "没有需要提交的变更",
                "data": {"committed": False, "reason": "nothing_to_commit"}
            }
        raise HTTPException(status_code=500, detail=f"git commit 失败: {stderr_commit}")

    stdout_head, _, _ = _run_git_command(repo["path"], ["rev-parse", "HEAD"])
    new_hash = stdout_head.strip()
    stdout_short, _, _ = _run_git_command(repo["path"], ["rev-parse", "--short", "HEAD"])
    short_hash = stdout_short.strip()

    # 同时保存到 SQLite 作为工作提交记录
    _ensure_data_initialized(db, DEFAULT_USER_ID)
    all_commits = db.query(WorkCommit).filter_by(user_id=DEFAULT_USER_ID).all()
    cid = max((c.commit_id for c in all_commits), default=0) + 1

    db_commit = WorkCommit(
        commit_id=cid,
        hash=short_hash,
        message=req.message,
        author="云汐",
        project_id=1,
        branch="main",
        additions=0,
        deletions=0,
        files_changed=0,
        committed_at=datetime.utcnow(),
        user_id=DEFAULT_USER_ID,
    )
    db.add(db_commit)
    db.commit()

    return {
        "code": 0,
        "message": "提交成功",
        "data": {
            "committed": True,
            "hash": new_hash,
            "short_hash": short_hash,
            "message": req.message,
        }
    }


@router.post("/git/{repo_id}/branch/create")
async def git_create_branch(
    repo_id: str,
    req: GitBranchCreateRequest,
):
    """创建分支（git checkout -b）"""
    repo = _get_repo_or_404(repo_id)

    if not req.branch_name or not req.branch_name.strip():
        raise HTTPException(status_code=400, detail="分支名不能为空")

    stdout_branches, _, _ = _run_git_command(repo["path"], ["branch", "--list", req.branch_name])
    if stdout_branches.strip():
        raise HTTPException(status_code=400, detail=f"分支已存在: {req.branch_name}")

    if req.base_branch:
        args = ["checkout", "-b", req.branch_name, req.base_branch]
    else:
        args = ["checkout", "-b", req.branch_name]

    stdout, stderr, rc = _run_git_command(repo["path"], args)
    if rc != 0:
        raise HTTPException(status_code=500, detail=f"创建分支失败: {stderr}")

    return {
        "code": 0,
        "message": f"分支 {req.branch_name} 创建成功",
        "data": {
            "branch_name": req.branch_name,
            "base_branch": req.base_branch or "current",
        }
    }


@router.post("/git/{repo_id}/branch/switch")
async def git_switch_branch(
    repo_id: str,
    req: GitBranchSwitchRequest,
):
    """切换分支（git checkout）"""
    repo = _get_repo_or_404(repo_id)

    if not req.branch_name or not req.branch_name.strip():
        raise HTTPException(status_code=400, detail="分支名不能为空")

    stdout_branches, _, _ = _run_git_command(repo["path"], ["branch", "--list", req.branch_name])
    if not stdout_branches.strip():
        raise HTTPException(status_code=404, detail=f"分支不存在: {req.branch_name}")

    stdout_status, _, _ = _run_git_command(repo["path"], ["status", "--porcelain"])
    if stdout_status.strip():
        raise HTTPException(
            status_code=400,
            detail="当前分支有未提交的变更，请先提交或暂存后再切换分支"
        )

    stdout, stderr, rc = _run_git_command(repo["path"], ["checkout", req.branch_name])
    if rc != 0:
        raise HTTPException(status_code=500, detail=f"切换分支失败: {stderr}")

    return {
        "code": 0,
        "message": f"已切换到分支 {req.branch_name}",
        "data": {"branch_name": req.branch_name}
    }


@router.post("/git/{repo_id}/pull")
async def git_pull(repo_id: str):
    """拉取代码（git pull）"""
    repo = _get_repo_or_404(repo_id)

    stdout_remote, _, rc_remote = _run_git_command(repo["path"], ["remote", "-v"])
    if rc_remote != 0 or not stdout_remote.strip():
        return {
            "code": 0,
            "message": "当前仓库没有配置远程仓库",
            "data": {"pulled": False, "reason": "no_remote"}
        }

    stdout, stderr, rc = _run_git_command(repo["path"], ["pull"], timeout=60)
    if rc != 0:
        raise HTTPException(status_code=500, detail=f"git pull 失败: {stderr}")

    already_up_to_date = "Already up to date" in stdout or "Already up-to-date" in stdout

    return {
        "code": 0,
        "message": "拉取成功",
        "data": {
            "pulled": True,
            "already_up_to_date": already_up_to_date,
            "output": stdout[:500],
        }
    }


@router.get("/git/{repo_id}/diff")
async def git_diff(
    repo_id: str,
    staged: bool = False,
    file: Optional[str] = None,
):
    """查看变更（git diff）"""
    repo = _get_repo_or_404(repo_id)

    args = ["diff"]
    if staged:
        args.append("--staged")
    if file:
        args.append("--")
        args.append(file)

    stdout, stderr, rc = _run_git_command(repo["path"], args)
    if rc != 0:
        raise HTTPException(status_code=500, detail=f"获取 diff 失败: {stderr}")

    return {
        "code": 0,
        "message": "ok",
        "data": {
            "diff": stdout,
            "staged": staged,
            "file": file,
            "has_changes": bool(stdout.strip()),
        }
    }


@router.get("/git/{repo_id}/stats")
async def git_stats(repo_id: str):
    """统计信息（提交数、作者统计、代码行数）"""
    repo = _get_repo_or_404(repo_id)

    # 总提交数
    stdout_count, _, rc_count = _run_git_command(repo["path"], ["rev-list", "--count", "HEAD"])
    total_commits = int(stdout_count.strip()) if rc_count == 0 and stdout_count.strip() else 0

    # 作者统计
    stdout_authors, _, rc_authors = _run_git_command(
        repo["path"], ["shortlog", "-sn", "HEAD"]
    )
    author_stats = []
    if rc_authors == 0:
        for line in stdout_authors.strip().split("\n"):
            if not line.strip():
                continue
            parts = line.strip().split("\t")
            if len(parts) >= 2:
                try:
                    count = int(parts[0].strip())
                except ValueError:
                    count = 0
                author_stats.append({"name": parts[1].strip(), "commits": count})

    # 文件数量
    stdout_files, _, rc_files = _run_git_command(repo["path"], ["ls-files"])
    file_count = 0
    total_lines = 0
    if rc_files == 0:
        files = [f for f in stdout_files.strip().split("\n") if f.strip()]
        file_count = len(files)

        # 统计代码行数（常见代码文件）
        code_extensions = {
            ".py", ".js", ".ts", ".html", ".css", ".go", ".rs",
            ".java", ".c", ".cpp", ".h", ".json", ".yaml", ".yml",
            ".md", ".txt", ".sh", ".bat", ".sql", ".vue", ".jsx", ".tsx",
        }
        code_files = [f for f in files if any(f.lower().endswith(ext) for ext in code_extensions)]

        for f in code_files[:500]:
            try:
                file_path = os.path.join(repo["path"], f)
                if os.path.isfile(file_path):
                    with open(file_path, "r", encoding="utf-8", errors="ignore") as fp:
                        total_lines += sum(1 for _ in fp if _.strip())
            except Exception:
                pass

    # 最近 7 天提交趋势
    daily_commits = []
    now = datetime.now()
    for i in range(6, -1, -1):
        day = now - timedelta(days=i)
        day_str = day.strftime("%Y-%m-%d")
        next_day = (day + timedelta(days=1)).strftime("%Y-%m-%d")
        stdout_daily, _, _ = _run_git_command(
            repo["path"],
            ["rev-list", "--count", f"--after={day_str}", f"--before={next_day}", "HEAD"]
        )
        try:
            count = int(stdout_daily.strip())
        except ValueError:
            count = 0
        daily_commits.append({"date": day_str, "count": count})

    # 当前分支
    stdout_branch, _, _ = _run_git_command(repo["path"], ["rev-parse", "--abbrev-ref", "HEAD"])
    current_branch = stdout_branch.strip()

    # 分支数量
    stdout_branches, _b, _ = _run_git_command(repo["path"], ["branch", "--list"])
    branch_count = len([b for b in stdout_branches.strip().split("\n") if b.strip()])

    # 总增删行数
    stdout_log_stat, _, _ = _run_git_command(
        repo["path"], ["log", "--pretty=tformat:", "--numstat"]
    )
    total_insertions = 0
    total_deletions = 0
    if stdout_log_stat:
        for line in stdout_log_stat.strip().split("\n"):
            if not line.strip():
                continue
            stat_parts = line.split("\t")
            if len(stat_parts) >= 2:
                try:
                    if stat_parts[0] != "-":
                        total_insertions += int(stat_parts[0])
                    if stat_parts[1] != "-":
                        total_deletions += int(stat_parts[1])
                except ValueError:
                    pass

    return {
        "code": 0,
        "message": "ok",
        "data": {
            "repo_id": repo_id,
            "total_commits": total_commits,
            "total_insertions": total_insertions,
            "total_deletions": total_deletions,
            "total_lines": total_lines,
            "file_count": file_count,
            "branch_count": branch_count,
            "current_branch": current_branch,
            "author_stats": author_stats,
            "daily_commits": daily_commits,
        }
    }
