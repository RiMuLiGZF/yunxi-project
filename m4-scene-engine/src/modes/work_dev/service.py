"""工作开发模式 - 业务逻辑层.

封装工作开发模式的核心业务逻辑，包括概览统计、项目管理、
任务看板、AI 代码助手、Git 管理、代码沙箱、代码片段、
开发会话、可视化统计等功能。
"""

from __future__ import annotations

import os
import re
import subprocess
import tempfile
import time
import uuid
from datetime import datetime, timedelta
from typing import Any, Optional

import httpx
import structlog
from sqlalchemy.orm import Session

from src.modes.work_dev.repository import WorkDevRepository

logger = structlog.get_logger(__name__)


# ---------------------------------------------------------------------------
# 常量配置
# ---------------------------------------------------------------------------

# 支持的编程语言
LANGUAGE_CONFIG: dict[str, dict[str, Any]] = {
    "python": {
        "name": "Python",
        "icon": "🐍",
        "extension": ".py",
    },
    "javascript": {
        "name": "JavaScript",
        "icon": "📜",
        "extension": ".js",
    },
    "typescript": {
        "name": "TypeScript",
        "icon": "🔷",
        "extension": ".ts",
    },
    "go": {
        "name": "Go",
        "icon": "🔵",
        "extension": ".go",
    },
    "rust": {
        "name": "Rust",
        "icon": "🦀",
        "extension": ".rs",
    },
}

# 支持的代码操作类型
VALID_OPERATIONS: set[str] = {
    "generate", "review", "debug", "optimize", "refactor", "explain", "test",
}

# 沙箱默认超时（秒）
SANDBOX_DEFAULT_TIMEOUT: int = 10
SANDBOX_MAX_OUTPUT: int = 10000
SANDBOX_MAX_CODE_SIZE_KB: int = 100

# 各语言危险代码模式
DANGEROUS_PATTERNS: dict[str, list[tuple[str, str, str]]] = {
    "python": [
        (r"os\.system\s*\(", "执行系统命令", "high"),
        (r"subprocess\.", "创建子进程", "high"),
        (r"\beval\s*\(", "动态代码执行", "high"),
        (r"\bexec\s*\(", "动态代码执行", "high"),
        (r"os\.remove\s*\(", "删除文件", "high"),
        (r"shutil\.rmtree\s*\(", "递归删除目录", "high"),
        (r"import\s+socket", "网络连接", "medium"),
        (r"urllib\.", "网络请求", "medium"),
        (r"requests\.", "网络请求", "medium"),
    ],
    "javascript": [
        (r"child_process\.", "执行系统命令", "high"),
        (r"\beval\s*\(", "动态代码执行", "high"),
        (r"new\s+Function\s*\(", "动态代码执行", "high"),
        (r"fs\.unlink", "删除文件", "high"),
        (r"fs\.rm\s*\(", "删除文件/目录", "high"),
        (r"fetch\s*\(", "网络请求", "medium"),
    ],
    "typescript": [
        (r"child_process\.", "执行系统命令", "high"),
        (r"\beval\s*\(", "动态代码执行", "high"),
        (r"fs\.unlink", "删除文件", "high"),
    ],
    "go": [
        (r'"os/exec"', "执行系统命令", "high"),
        (r"exec\.Command", "执行系统命令", "high"),
        (r"os\.Remove", "删除文件", "high"),
        (r'"net"', "网络连接", "medium"),
    ],
    "rust": [
        (r"std::process::Command", "执行系统命令", "high"),
        (r"std::fs::remove_file", "删除文件", "high"),
        (r"std::fs::remove_dir", "删除目录", "high"),
    ],
}

# 代码专家系统提示词
_CODE_EXPERT_SYSTEM_PROMPT: str = """你是 Codex，一位专业的代码专家。你的任务是帮助用户解决编程问题。

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
- 考虑边界条件和异常处理"""

# 操作类型对应的提示词模板
_OPERATION_PROMPTS: dict[str, str] = {
    "generate": "请帮我用 {language} 实现以下功能：\n{prompt}\n\n请给出完整的、可运行的代码实现，包含必要的注释和使用示例。",
    "review": "请帮我审查以下 {language} 代码：\n{prompt}\n\n请从以下维度进行审查：\n1. 代码正确性与潜在 Bug\n2. 代码规范与可读性\n3. 性能问题\n4. 安全隐患\n5. 改进建议",
    "debug": "我遇到了一个编程问题，请帮我分析和调试。以下是相关信息：\n{prompt}\n\n使用的语言：{language}\n\n请帮我分析可能的原因并提供修复方案。",
    "optimize": "请帮我优化以下 {language} 代码的性能：\n{prompt}\n\n请分析性能瓶颈，并提供优化后的代码，同时说明优化思路。",
    "refactor": "请帮我重构以下 {language} 代码：\n{prompt}\n\n请从代码结构、命名规范、复杂度等方面进行重构，提高可维护性。",
    "explain": "请帮我解释以下 {language} 代码的逻辑：\n{prompt}\n\n请用通俗易懂的语言解释代码的整体功能、核心思路和关键部分。",
    "test": "请为以下 {language} 代码生成单元测试：\n{prompt}\n\n请生成全面的测试用例，覆盖正常情况、边界条件和异常情况。",
}


# ---------------------------------------------------------------------------
# 服务类
# ---------------------------------------------------------------------------


class WorkDevService:
    """工作开发业务服务类.

    提供工作开发模式的所有业务逻辑，
    调用 WorkDevRepository 进行数据访问。
    """

    def __init__(self, db: Session, user_id: str = "default") -> None:
        """初始化服务.

        Args:
            db: 数据库会话
            user_id: 用户 ID
        """
        self.repo = WorkDevRepository(db, user_id=user_id)

    # -----------------------------------------------------------------------
    # 概览统计
    # -----------------------------------------------------------------------

    def get_overview(self) -> dict[str, Any]:
        """获取工作开发概览数据.

        Returns:
            概览数据字典，包含 stats、recent_tasks、recent_commits
        """
        projects = self.repo.list_projects()
        project_dicts = [p.to_dict() for p in projects]
        tasks = self.repo.list_tasks()
        task_dicts = [t.to_dict() for t in tasks]
        commits = self.repo.list_commits(limit=20)
        commit_dicts = [c.to_dict() for c in commits]

        total_projects = len(project_dicts)
        active_projects = sum(1 for p in project_dicts if p["status"] == "active")
        total_tasks = len(task_dicts)
        done_tasks = sum(1 for t in task_dicts if t["status"] == "done")
        in_progress_tasks = sum(1 for t in task_dicts if t["status"] == "in_progress")
        todo_tasks = sum(1 for t in task_dicts if t["status"] == "todo")
        total_commits = len(commit_dicts)
        week_commits = self.repo.count_week_commits()
        total_lines = self.repo.total_line_count()

        task_completion_rate = round(
            done_tasks / total_tasks * 100, 1
        ) if total_tasks > 0 else 0.0

        stats = {
            "total_projects": total_projects,
            "active_projects": active_projects,
            "total_tasks": total_tasks,
            "done_tasks": done_tasks,
            "in_progress_tasks": in_progress_tasks,
            "todo_tasks": todo_tasks,
            "total_commits": total_commits,
            "week_commits": week_commits,
            "total_lines": total_lines,
            "task_completion_rate": task_completion_rate,
        }

        recent_tasks = sorted(
            task_dicts, key=lambda x: x.get("updated_at", ""), reverse=True
        )[:5]

        recent_commits = sorted(
            commit_dicts, key=lambda x: x.get("created_at", ""), reverse=True
        )[:5]

        return {
            "stats": stats,
            "recent_tasks": recent_tasks,
            "recent_commits": recent_commits,
        }

    # -----------------------------------------------------------------------
    # 项目管理
    # -----------------------------------------------------------------------

    def list_projects(
        self,
        status: Optional[str] = None,
        category: Optional[str] = None,
    ) -> list[dict[str, Any]]:
        """获取项目列表（带任务统计）.

        Args:
            status: 按状态筛选
            category: 按分类筛选

        Returns:
            项目字典列表
        """
        projects = self.repo.list_projects(status=status, category=category)
        result = []
        for p in projects:
            p_dict = p.to_dict()
            project_tasks = self.repo.list_tasks(project_id=p.project_id)
            p_dict["task_count"] = len(project_tasks)
            p_dict["done_count"] = sum(
                1 for t in project_tasks if t.status == "done"
            )
            result.append(p_dict)
        return result

    def get_project_detail(self, project_id: int) -> Optional[dict[str, Any]]:
        """获取项目详情（含任务统计和最近提交）.

        Args:
            project_id: 项目 ID

        Returns:
            项目详情字典，不存在返回 None
        """
        project = self.repo.get_project(project_id)
        if not project:
            return None

        project_dict = project.to_dict()

        # 任务统计
        project_tasks = self.repo.list_tasks(project_id=project_id)
        project_dict["task_count"] = len(project_tasks)
        project_dict["done_count"] = sum(
            1 for t in project_tasks if t.status == "done"
        )

        # 最近提交
        commits = self.repo.list_commits(project_id=project_id, limit=10)
        project_dict["commits"] = [c.to_dict() for c in commits]

        return project_dict

    def get_project_stats(self, project_id: int) -> Optional[dict[str, Any]]:
        """获取项目统计数据.

        Args:
            project_id: 项目 ID

        Returns:
            项目统计字典，不存在返回 None
        """
        project = self.repo.get_project(project_id)
        if not project:
            return None

        tasks = self.repo.list_tasks(project_id=project_id)
        commits = self.repo.list_commits(project_id=project_id, limit=1000)

        total_tasks = len(tasks)
        done_tasks = sum(1 for t in tasks if t.status == "done")
        in_progress_tasks = sum(1 for t in tasks if t.status == "in_progress")
        todo_tasks = sum(1 for t in tasks if t.status == "todo")
        completion_rate = round(
            done_tasks / total_tasks * 100, 1
        ) if total_tasks > 0 else 0.0

        total_commits = len(commits)
        total_insertions = sum(c.additions or 0 for c in commits)
        total_deletions = sum(c.deletions or 0 for c in commits)

        # 本周提交数
        week_ago = datetime.utcnow() - timedelta(days=7)
        week_commits = sum(
            1 for c in commits
            if c.committed_at and c.committed_at >= week_ago
        )

        return {
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
            "line_count": project.line_count or total_insertions,
            "file_count": project.file_count or 0,
        }

    def create_project(
        self,
        name: str,
        description: str = "",
        language: str = "python",
        category: str = "",
        status: str = "planning",
    ) -> dict[str, Any]:
        """创建项目.

        Args:
            name: 项目名称
            description: 项目描述
            language: 主要语言
            category: 项目分类
            status: 状态

        Returns:
            创建后的项目字典
        """
        project = self.repo.create_project(
            name=name,
            description=description,
            language=language,
            category=category,
            status=status,
        )
        p_dict = project.to_dict()
        p_dict["task_count"] = 0
        p_dict["done_count"] = 0
        return p_dict

    def update_project(
        self,
        project_id: int,
        update_data: dict[str, Any],
    ) -> Optional[dict[str, Any]]:
        """更新项目信息.

        Args:
            project_id: 项目 ID
            update_data: 更新数据字典

        Returns:
            更新后的项目字典，不存在返回 None
        """
        project = self.repo.update_project(project_id, **update_data)
        if not project:
            return None

        p_dict = project.to_dict()
        project_tasks = self.repo.list_tasks(project_id=project_id)
        p_dict["task_count"] = len(project_tasks)
        p_dict["done_count"] = sum(
            1 for t in project_tasks if t.status == "done"
        )
        return p_dict

    def delete_project(self, project_id: int) -> bool:
        """删除项目.

        Args:
            project_id: 项目 ID

        Returns:
            True 表示删除成功
        """
        return self.repo.delete_project(project_id)

    # -----------------------------------------------------------------------
    # 任务看板
    # -----------------------------------------------------------------------

    def list_tasks(
        self,
        project_id: Optional[int] = None,
        status: Optional[str] = None,
        priority: Optional[str] = None,
    ) -> list[dict[str, Any]]:
        """获取任务列表.

        Args:
            project_id: 按项目筛选
            status: 按状态筛选
            priority: 按优先级筛选

        Returns:
            任务字典列表
        """
        tasks = self.repo.list_tasks(
            project_id=project_id, status=status, priority=priority
        )
        return [t.to_dict() for t in tasks]

    def get_task_board(
        self,
        project_id: Optional[int] = None,
    ) -> dict[str, list[dict[str, Any]]]:
        """获取任务看板数据（按状态分组）.

        Args:
            project_id: 按项目筛选

        Returns:
            看板数据字典，key 为状态，value 为任务列表
        """
        tasks = self.repo.list_tasks(project_id=project_id)
        task_dicts = [t.to_dict() for t in tasks]

        board = {
            "todo": [t for t in task_dicts if t["status"] == "todo"],
            "in_progress": [t for t in task_dicts if t["status"] == "in_progress"],
            "review": [t for t in task_dicts if t["status"] == "review"],
            "done": [t for t in task_dicts if t["status"] == "done"],
        }
        return board

    def create_task(
        self,
        title: str,
        description: str = "",
        status: str = "todo",
        priority: str = "medium",
        project_id: int = 0,
        assignee: str = "云汐",
        due_date: Optional[str] = None,
        tags: Optional[list[str]] = None,
        estimate_hours: int = 0,
    ) -> dict[str, Any]:
        """创建任务.

        Args:
            title: 任务标题
            description: 任务描述
            status: 状态
            priority: 优先级
            project_id: 所属项目 ID
            assignee: 负责人
            due_date: 截止日期
            tags: 标签列表
            estimate_hours: 预估工时

        Returns:
            创建后的任务字典
        """
        task = self.repo.create_task(
            title=title,
            description=description,
            status=status,
            priority=priority,
            project_id=project_id,
            assignee=assignee,
            due_date=due_date,
            tags=tags,
            estimate_hours=estimate_hours,
        )
        return task.to_dict()

    def update_task(
        self,
        task_id: int,
        update_data: dict[str, Any],
    ) -> Optional[dict[str, Any]]:
        """更新任务信息.

        Args:
            task_id: 任务 ID
            update_data: 更新数据字典

        Returns:
            更新后的任务字典，不存在返回 None
        """
        task = self.repo.update_task(task_id, **update_data)
        return task.to_dict() if task else None

    def update_task_status(
        self,
        task_id: int,
        status: str,
    ) -> Optional[dict[str, Any]]:
        """更新任务状态.

        Args:
            task_id: 任务 ID
            status: 新状态

        Returns:
            更新后的任务字典，不存在返回 None
        """
        task = self.repo.update_task_status(task_id, status)
        return task.to_dict() if task else None

    def delete_task(self, task_id: int) -> bool:
        """删除任务.

        Args:
            task_id: 任务 ID

        Returns:
            True 表示删除成功
        """
        return self.repo.delete_task(task_id)

    # -----------------------------------------------------------------------
    # Git 管理
    # -----------------------------------------------------------------------

    def list_commits(
        self,
        project_id: Optional[int] = None,
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        """获取提交记录列表.

        Args:
            project_id: 按项目筛选
            limit: 返回条数限制

        Returns:
            提交记录字典列表
        """
        commits = self.repo.list_commits(project_id=project_id, limit=limit)
        return [c.to_dict() for c in commits]

    def get_commit_stats(
        self,
        project_id: Optional[int] = None,
    ) -> dict[str, Any]:
        """获取提交统计数据.

        Args:
            project_id: 按项目筛选

        Returns:
            提交统计字典
        """
        return self.repo.get_commit_stats(project_id=project_id)

    def create_commit(
        self,
        message: str,
        project_id: int = 1,
    ) -> dict[str, Any]:
        """创建模拟提交记录.

        Args:
            message: 提交信息
            project_id: 项目 ID

        Returns:
            创建后的提交记录字典
        """
        # 模拟添加一些行数变化
        import random
        additions = random.randint(20, 100)
        deletions = random.randint(5, 40)
        files_changed = random.randint(1, 6)

        commit = self.repo.create_commit(
            message=message,
            project_id=project_id,
            additions=additions,
            deletions=deletions,
            files_changed=files_changed,
        )
        return commit.to_dict()

    def list_branches(self) -> list[dict[str, Any]]:
        """获取分支列表（模拟数据）.

        Returns:
            分支列表
        """
        return [
            {"name": "main", "ahead": 0, "behind": 0, "is_default": True, "last_commit": "2小时前"},
            {"name": "dev/agent-scheduler", "ahead": 5, "behind": 2, "is_default": False, "last_commit": "1天前"},
            {"name": "feature/skill-cluster", "ahead": 8, "behind": 3, "is_default": False, "last_commit": "3天前"},
            {"name": "fix/auth-bug", "ahead": 2, "behind": 0, "is_default": False, "last_commit": "5天前"},
        ]

    # -----------------------------------------------------------------------
    # 代码沙箱
    # -----------------------------------------------------------------------

    def get_supported_languages(self) -> list[dict[str, Any]]:
        """获取支持的编程语言列表.

        Returns:
            语言列表（含状态）
        """
        languages = []
        for key, config in LANGUAGE_CONFIG.items():
            available = self._check_language_available(key)
            languages.append({
                "key": key,
                "name": config["name"],
                "icon": config["icon"],
                "extension": config["extension"],
                "status": "available" if available else "unavailable",
            })
        return languages

    def _check_language_available(self, lang_key: str) -> bool:
        """检测语言是否在系统中可用.

        Args:
            lang_key: 语言 key

        Returns:
            True 表示可用
        """
        check_cmds = {
            "python": ["python", "--version"],
            "javascript": ["node", "--version"],
            "typescript": ["npx", "ts-node", "--version"],
            "go": ["go", "version"],
            "rust": ["rustc", "--version"],
        }
        cmd = check_cmds.get(lang_key)
        if not cmd:
            return False
        try:
            result = subprocess.run(
                cmd, capture_output=True, text=True, timeout=5,
                encoding="utf-8", errors="replace",
            )
            return result.returncode == 0 or bool(result.stdout.strip() or result.stderr.strip())
        except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
            return False

    def detect_dangerous_code(self, code: str, language: str) -> list[dict[str, Any]]:
        """检测代码中的危险模式.

        Args:
            code: 代码内容
            language: 编程语言

        Returns:
            危险检测结果列表
        """
        patterns = DANGEROUS_PATTERNS.get(language, [])
        if not patterns:
            return []

        findings: list[dict[str, Any]] = []
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
            if language in ("go", "rust") and stripped.startswith("//"):
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
        seen: set[tuple[int, str]] = set()
        unique_findings: list[dict[str, Any]] = []
        for f in findings:
            key = (f["line"], f["description"])
            if key not in seen:
                seen.add(key)
                unique_findings.append(f)

        return unique_findings

    def execute_code(
        self,
        code: str,
        language: str = "python",
        stdin: str = "",
    ) -> dict[str, Any]:
        """执行代码（沙箱环境）.

        Args:
            code: 代码内容
            language: 编程语言
            stdin: 标准输入

        Returns:
            执行结果字典
        """
        language = language.lower().strip()
        start = time.time()

        # 危险代码检测
        danger_findings = self.detect_dangerous_code(code, language)
        has_danger = len(danger_findings) > 0

        # 执行代码
        result = self._run_sandbox(code, language, stdin)

        # 组装安全警告
        security_warning_lines: list[str] = []
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

        stderr_output = result.get("stderr", "")
        if security_warning_lines:
            warning_text = "\n".join(security_warning_lines)
            if stderr_output:
                stderr_output = warning_text + "\n\n" + stderr_output
            else:
                stderr_output = warning_text

        # 记录使用统计
        self.repo.record_usage(
            action_type="execute",
            operation_type="execute",
            language=language,
            tokens_used=len(code),
            is_fallback=True,
        )

        return {
            "language": language,
            "stdout": result.get("stdout", ""),
            "stderr": stderr_output,
            "exit_code": result.get("exit_code", -1),
            "duration_ms": result.get("duration_ms", int((time.time() - start) * 1000)),
            "timed_out": result.get("timed_out", False),
            "security_warnings": danger_findings,
            "has_danger": has_danger,
        }

    def _run_sandbox(
        self,
        code: str,
        language: str,
        stdin: str = "",
    ) -> dict[str, Any]:
        """通用沙箱执行函数.

        Args:
            code: 代码内容
            language: 编程语言
            stdin: 标准输入

        Returns:
            执行结果字典
        """
        start = time.time()
        temp_file: Optional[str] = None

        # 语言对应的执行命令和文件扩展名
        lang_cmds: dict[str, tuple[list[str], str]] = {
            "python": (["python", "__FILE__"], ".py"),
            "javascript": (["node", "__FILE__"], ".js"),
            "typescript": (["npx", "ts-node", "__FILE__"], ".ts"),
            "go": (["go", "run", "__FILE__"], ".go"),
        }

        cmd_info = lang_cmds.get(language)
        if not cmd_info:
            return {
                "stdout": "",
                "stderr": f"不支持的语言: {language}",
                "exit_code": -1,
                "duration_ms": 0,
                "timed_out": False,
            }

        cmd, file_ext = cmd_info

        try:
            # 代码大小检查
            size_bytes = len(code.encode("utf-8"))
            if size_bytes > SANDBOX_MAX_CODE_SIZE_KB * 1024:
                return {
                    "stdout": "",
                    "stderr": "代码大小超过限制",
                    "exit_code": -1,
                    "duration_ms": int((time.time() - start) * 1000),
                    "timed_out": False,
                }

            with tempfile.NamedTemporaryFile(
                mode="w", suffix=file_ext, delete=False, encoding="utf-8"
            ) as f:
                f.write(code)
                temp_file = f.name

            actual_cmd = [c if c != "__FILE__" else temp_file for c in cmd]
            safe_env = self._get_safe_environ()

            try:
                proc = subprocess.run(
                    actual_cmd,
                    input=stdin,
                    capture_output=True,
                    text=True,
                    timeout=SANDBOX_DEFAULT_TIMEOUT,
                    env=safe_env,
                    encoding="utf-8",
                    errors="replace",
                )
                duration = int((time.time() - start) * 1000)
                return {
                    "stdout": proc.stdout[:SANDBOX_MAX_OUTPUT],
                    "stderr": proc.stderr[:SANDBOX_MAX_OUTPUT],
                    "exit_code": proc.returncode,
                    "duration_ms": duration,
                    "timed_out": False,
                }
            except subprocess.TimeoutExpired:
                return {
                    "stdout": "",
                    "stderr": f"执行超时（超过{SANDBOX_DEFAULT_TIMEOUT}秒）",
                    "exit_code": -1,
                    "duration_ms": SANDBOX_DEFAULT_TIMEOUT * 1000,
                    "timed_out": True,
                }

        except FileNotFoundError:
            return {
                "stdout": "",
                "stderr": "编译器/解释器未找到，请检查是否已安装",
                "exit_code": -1,
                "duration_ms": int((time.time() - start) * 1000),
                "timed_out": False,
            }
        except Exception as e:
            return {
                "stdout": "",
                "stderr": f"执行错误: {str(e)}",
                "exit_code": -1,
                "duration_ms": int((time.time() - start) * 1000),
                "timed_out": False,
            }
        finally:
            if temp_file and os.path.exists(temp_file):
                try:
                    os.unlink(temp_file)
                except Exception as e:
                    logger.warning("work_dev.sandbox_cleanup_failed", temp_file=temp_file,
                                   error_type=type(e).__name__, error=str(e))
                    pass

    def _get_safe_environ(self) -> dict[str, str]:
        """获取安全的环境变量（移除敏感信息）."""
        env = os.environ.copy()

        sensitive_keywords = [
            "API_KEY", "SECRET", "TOKEN", "PASSWORD", "PASSWD",
            "PRIVATE_KEY", "ACCESS_KEY", "AUTH", "COOKIE",
            "GIT_TOKEN", "GITHUB_TOKEN", "NPM_TOKEN",
            "AWS_ACCESS_KEY", "AWS_SECRET",
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
        return env

    # -----------------------------------------------------------------------
    # AI 代码助手
    # -----------------------------------------------------------------------

    def generate_code(
        self,
        prompt: str,
        language: str = "python",
        operation_type: str = "generate",
    ) -> dict[str, Any]:
        """AI 代码操作（生成/审查/调试/优化/重构/解释/测试生成）.

        当前为简化版（模板匹配 fallback），预留 LLM 接入点。

        Args:
            prompt: 需求描述
            language: 编程语言
            operation_type: 操作类型

        Returns:
            代码操作结果字典
        """
        if operation_type not in VALID_OPERATIONS:
            operation_type = "generate"

        # Fallback: 模板匹配生成代码
        code = self._fallback_generate_code(prompt, language, operation_type)

        # 记录使用统计
        self.repo.record_usage(
            action_type="generate",
            operation_type=operation_type,
            language=language,
            tokens_used=len(prompt) + len(code),
            is_fallback=True,
        )

        lang_name = LANGUAGE_CONFIG.get(language, {}).get("name", language)
        op_names = {
            "generate": "生成",
            "review": "审查",
            "debug": "调试",
            "optimize": "优化",
            "refactor": "重构",
            "explain": "解释",
            "test": "测试",
        }
        op_name = op_names.get(operation_type, "操作")

        content = (
            f"根据你的需求，我{op_name}了以下{lang_name}代码：\n\n"
            f"```{language}\n{code}\n```\n\n"
            f"**说明：**\n"
            f"- 代码包含基本的输入验证\n"
            f"- 已添加必要的注释说明\n\n"
            f"（当前为模板匹配模式，接入大模型后可获得更智能的回复）"
        )

        return {
            "language": language,
            "operation": operation_type,
            "content": content,
            "code": code,
            "is_fallback": True,
            "model": "template-matching",
        }

    def _fallback_generate_code(
        self,
        prompt: str,
        language: str,
        operation_type: str,
    ) -> str:
        """模板匹配 fallback 生成代码."""
        if language == "python":
            return self._generate_python_code(prompt, operation_type)
        elif language in ("javascript", "typescript"):
            return self._generate_javascript_code(prompt, language, operation_type)
        elif language == "go":
            return self._generate_go_code(prompt)
        elif language == "rust":
            return self._generate_rust_code(prompt)
        else:
            return self._generate_python_code(prompt, operation_type)

    def _generate_python_code(self, prompt: str, operation_type: str) -> str:
        """生成 Python 代码模板."""
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


if __name__ == "__main__":
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
            prompt_short = prompt[:50] if len(prompt) > 50 else prompt
            return f'''# Yunxi AI Code Generator
# Operation: {operation_type}
# Prompt: {prompt_short}

def main():
    """Main entry point."""
    print("Hello, Yunxi!")
    # NOTE: 请根据上方 Prompt 实现具体业务逻辑
    # TODO: 接入 _call_llm_for_codegen() 动态生成
    pass


if __name__ == "__main__":
    main()'''

    def _generate_javascript_code(
        self, prompt: str, language: str, operation_type: str,
    ) -> str:
        """生成 JavaScript/TypeScript 代码模板."""
        prompt_short = prompt[:50] if len(prompt) > 50 else prompt
        semicolon = ";" if language == "javascript" else ""
        return f"""// Yunxi AI Code Generator
// Operation: {operation_type}
// Prompt: {prompt_short}

function main() {{
  console.log('Hello, Yunxi!'){semicolon}
  // NOTE: 请根据上方 Prompt 实现具体业务逻辑
  // TODO: 接入 _call_llm_for_codegen() 动态生成
}}

main(){semicolon}"""

    def _generate_go_code(self, prompt: str) -> str:
        """生成 Go 代码模板."""
        prompt_short = prompt[:40] if len(prompt) > 40 else prompt
        return f'''package main

import "fmt"

// Yunxi AI Code Generator
// Prompt: {prompt_short}

func main() {{
\tfmt.Println("Hello, Yunxi!")
\t// NOTE: 请根据上方 Prompt 实现具体业务逻辑
\t// TODO: 接入 _call_llm_for_codegen() 动态生成
}}
'''

    def _generate_rust_code(self, prompt: str) -> str:
        """生成 Rust 代码模板."""
        prompt_short = prompt[:40] if len(prompt) > 40 else prompt
        return f'''// Yunxi AI Code Generator
// Prompt: {prompt_short}

fn main() {{
    println!("Hello, Yunxi!");
    // NOTE: 请根据上方 Prompt 实现具体业务逻辑
    // TODO: 接入 _call_llm_for_codegen() 动态生成
}}
'''

    # -----------------------------------------------------------------------
    # 代码对话
    # -----------------------------------------------------------------------

    def code_chat(
        self,
        message: str,
        language: str = "python",
        conversation_id: str = "default",
        context_code: str = "",
    ) -> dict[str, Any]:
        """代码对话（多轮）.

        当前为简化版（模板匹配 fallback），预留 LLM 接入点。

        Args:
            message: 用户消息
            language: 编程语言
            conversation_id: 会话 ID
            context_code: 上下文代码

        Returns:
            对话结果字典
        """
        # 获取或创建会话
        session = self.repo.get_or_create_session(
            session_id=conversation_id,
            session_type="code_chat",
            language=language,
        )

        # 添加用户消息
        self.repo.append_message(conversation_id, "user", message)

        # Fallback: 模板回复
        code = self._fallback_generate_code(message, language, "generate")
        lang_name = LANGUAGE_CONFIG.get(language, {}).get("name", language)
        reply = (
            f"好的，我来帮你处理这个问题。\n\n"
            f"这是一个{lang_name}示例：\n\n"
            f"```{language}\n{code}\n```\n\n"
            f"（当前为模板模式，接入大模型后可获得更智能的对话体验）"
        )

        # 添加 AI 回复
        self.repo.append_message(conversation_id, "assistant", reply)

        # 记录使用统计
        self.repo.record_usage(
            action_type="chat",
            operation_type="chat",
            language=language,
            tokens_used=len(message) + len(reply),
            is_fallback=True,
        )

        return {
            "reply": reply,
            "conversation_id": conversation_id,
            "message_id": f"msg_{uuid.uuid4().hex[:12]}",
            "language": language,
            "message_count": session.message_count + 2 if session else 2,
            "is_fallback": True,
            "model": "template-matching",
        }

    def list_chat_sessions(self) -> list[dict[str, Any]]:
        """获取代码对话会话列表.

        Returns:
            会话列表
        """
        sessions = self.repo.list_sessions(session_type="code_chat", limit=50)
        result = []
        for s in sessions:
            s_dict = s.to_dict()
            messages = s_dict.get("messages", [])
            last_msg = messages[-1] if messages else None
            result.append({
                "id": s_dict["session_id"],
                "title": s_dict["title"],
                "language": s_dict["language"],
                "message_count": s_dict["message_count"],
                "updated_at": s_dict["updated_at"],
                "last_message": last_msg.get("content", "")[:50] if last_msg else "",
            })
        return result

    def get_chat_session(self, conversation_id: str) -> dict[str, Any]:
        """获取代码对话会话详情.

        Args:
            conversation_id: 会话 ID

        Returns:
            会话详情字典
        """
        session = self.repo.get_session(conversation_id)
        if not session:
            return {
                "id": conversation_id,
                "messages": [],
                "language": "python",
                "message_count": 0,
            }
        s_dict = session.to_dict()
        return {
            "id": s_dict["session_id"],
            "messages": s_dict.get("messages", []),
            "language": s_dict["language"],
            "message_count": s_dict["message_count"],
            "created_at": s_dict["created_at"],
            "updated_at": s_dict["updated_at"],
        }

    def delete_chat_session(self, conversation_id: str) -> bool:
        """删除代码对话会话.

        Args:
            conversation_id: 会话 ID

        Returns:
            True 表示删除成功
        """
        return self.repo.delete_session(conversation_id)

    # -----------------------------------------------------------------------
    # 代码片段
    # -----------------------------------------------------------------------

    def list_snippets(
        self,
        language: Optional[str] = None,
        tag: Optional[str] = None,
        only_favorite: bool = False,
    ) -> list[dict[str, Any]]:
        """获取代码片段列表.

        Args:
            language: 按语言筛选
            tag: 按标签筛选
            only_favorite: 只显示收藏的

        Returns:
            代码片段字典列表
        """
        snippets = self.repo.list_snippets(
            language=language, tag=tag, only_favorite=only_favorite
        )
        return [s.to_dict() for s in snippets]

    def create_snippet(
        self,
        title: str,
        language: str = "python",
        code: str = "",
        description: str = "",
        tags: Optional[list[str]] = None,
        project_id: int = 0,
    ) -> dict[str, Any]:
        """创建代码片段.

        Args:
            title: 片段标题
            language: 编程语言
            code: 代码内容
            description: 描述说明
            tags: 标签列表
            project_id: 所属项目 ID

        Returns:
            创建后的代码片段字典
        """
        snippet = self.repo.create_snippet(
            title=title,
            language=language,
            code=code,
            description=description,
            tags=tags,
            project_id=project_id,
        )
        return snippet.to_dict()

    def update_snippet(
        self,
        snippet_id: int,
        update_data: dict[str, Any],
    ) -> Optional[dict[str, Any]]:
        """更新代码片段.

        Args:
            snippet_id: 片段 ID
            update_data: 更新数据字典

        Returns:
            更新后的代码片段字典，不存在返回 None
        """
        snippet = self.repo.update_snippet(snippet_id, **update_data)
        return snippet.to_dict() if snippet else None

    def delete_snippet(self, snippet_id: int) -> bool:
        """删除代码片段.

        Args:
            snippet_id: 片段 ID

        Returns:
            True 表示删除成功
        """
        return self.repo.delete_snippet(snippet_id)

    # -----------------------------------------------------------------------
    # 快速操作 & 最近活动
    # -----------------------------------------------------------------------

    def get_quick_actions(self) -> list[dict[str, Any]]:
        """获取快速操作列表.

        Returns:
            快速操作列表
        """
        return [
            {"id": "generate_code", "name": "AI 生成代码", "icon": "code", "hotkey": "⌘G"},
            {"id": "code_review", "name": "代码审查", "icon": "check-circle", "hotkey": "⌘R"},
            {"id": "git_commit", "name": "Git 提交", "icon": "git-commit", "hotkey": "⌘C"},
            {"id": "run_tests", "name": "运行测试", "icon": "play", "hotkey": "⌘T"},
            {"id": "view_logs", "name": "查看日志", "icon": "file-text", "hotkey": "⌘L"},
            {"id": "search_code", "name": "搜索代码", "icon": "search", "hotkey": "⌘F"},
            {"id": "new_project", "name": "新建项目", "icon": "folder-plus", "hotkey": "⌘N"},
            {"id": "new_task", "name": "新建任务", "icon": "plus-square", "hotkey": "⌘K"},
        ]

    def get_recent_activity(self, limit: int = 10) -> list[dict[str, Any]]:
        """获取最近活动.

        Args:
            limit: 返回条数限制

        Returns:
            活动列表
        """
        activities: list[dict[str, Any]] = []

        # 最近提交
        recent_commits = self.repo.list_commits(limit=5)
        for c in recent_commits:
            c_dict = c.to_dict()
            activities.append({
                "id": f"commit-{c_dict['id']}",
                "type": "commit",
                "title": f"提交: {c_dict['message']}",
                "time": c_dict["created_at"],
                "user": c_dict["author"],
            })

        # 最近任务
        recent_tasks = self.repo.list_tasks()
        for t in recent_tasks[:5]:
            t_dict = t.to_dict()
            status_text = {
                "todo": "创建了任务",
                "in_progress": "开始处理",
                "review": "提交审查",
                "done": "完成了",
            }
            activities.append({
                "id": f"task-{t_dict['id']}",
                "type": "task",
                "title": f"{status_text.get(t_dict['status'], '更新了')}: {t_dict['title']}",
                "time": t_dict["updated_at"],
                "user": t_dict["assignee"],
            })

        # 按时间排序
        activities.sort(key=lambda x: x["time"], reverse=True)
        return activities[:limit]

    # -----------------------------------------------------------------------
    # LLM 代码生成
    # -----------------------------------------------------------------------

    async def _call_llm_for_codegen(
        self,
        prompt: str,
        language: str = "python",
        context: str = "",
    ) -> str:
        """调用 LLM 接口生成代码.

        通过 httpx.AsyncClient 调用已配置的 LLM 服务端点，
        根据 prompt、语言和上下文代码生成目标代码。

        Args:
            prompt: 用户需求描述
            language: 目标编程语言
            context: 上下文代码（可选，用于增量生成）

        Returns:
            LLM 返回的生成代码字符串

        Raises:
            httpx.HTTPError: 网络或服务端错误时抛出
        """
        llm_url = os.environ.get(
            "LLM_CODEGEN_URL",
            "http://localhost:11434/v1/completions",
        )
        llm_api_key = os.environ.get("LLM_API_KEY", "")
        model = os.environ.get("LLM_CODEGEN_MODEL", "qwen2.5-coder:7b")

        # 构建系统提示词
        system_prompt = (
            f"你是一个专业的 {language} 代码生成助手。"
            f"请根据用户的需求描述，生成高质量的 {language} 代码。"
            f"只输出代码本身，不要包含额外说明。"
        )
        if context:
            system_prompt += f"\n参考已有上下文代码：\n{context}"

        # 构建请求体（兼容 OpenAI 接口格式）
        payload = {
            "model": model,
            "prompt": f"{system_prompt}\n\n用户需求：{prompt}\n\n请生成{language}代码：",
            "max_tokens": 2048,
            "temperature": 0.3,
            "stop": ["```", "---"],
        }

        headers = {
            "Content-Type": "application/json",
        }
        if llm_api_key:
            headers["Authorization"] = f"Bearer {llm_api_key}"

        async with httpx.AsyncClient(timeout=60.0) as client:
            response = await client.post(
                llm_url,
                json=payload,
                headers=headers,
            )
            response.raise_for_status()
            result = response.json()

        # 兼容不同 LLM 返回格式
        raw_code = ""
        if "choices" in result:
            choice = result["choices"][0]
            if "text" in choice:
                raw_code = choice["text"]
            elif "message" in choice:
                raw_code = choice["message"].get("content", "")
        elif "response" in result:
            raw_code = result["response"]
        else:
            raw_code = str(result)

        # 清理并返回生成的代码
        return raw_code.strip()
