"""Git 工具技能.

提供 Git 仓库操作功能，包括状态查看、提交、推送、拉取、分支管理、提交历史、差异对比等。
底层调用 git 命令行工具。
"""

from __future__ import annotations

import os
import subprocess
from typing import Any

import structlog

from src.services.skills.base import BaseSkill

logger = structlog.get_logger(__name__)


class GitToolSkill(BaseSkill):
    """Git 工具技能.

    支持的操作（通过 action 参数区分）:
        - status: 查看仓库状态
        - commit: 提交更改
        - push: 推送到远程
        - pull: 从远程拉取
        - branch: 分支管理（列出/创建/切换/删除）
        - log: 查看提交历史
        - diff: 查看差异对比

    所有操作都基于 git 命令行工具执行。
    """

    name = "git_tools"
    display_name = "Git 工具"
    description = "对 Git 仓库进行版本控制操作，包括状态查看、提交、推送、拉取、分支管理、历史查看、差异对比等"
    category = "development"
    icon = "📊"
    version = "1.0.0"

    parameters = {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "description": "操作类型：status(状态) / commit(提交) / push(推送) / pull(拉取) / branch(分支) / log(日志) / diff(差异)",
                "enum": ["status", "commit", "push", "pull", "branch", "log", "diff"],
            },
            "repo_path": {
                "type": "string",
                "description": "仓库路径（默认为工作目录）",
            },
            "message": {
                "type": "string",
                "description": "提交信息（用于 commit 操作）",
            },
            "files": {
                "type": "array",
                "items": {"type": "string"},
                "description": "要提交的文件列表（用于 commit 操作，为空则提交所有更改）",
            },
            "remote": {
                "type": "string",
                "description": "远程仓库名（用于 push/pull 操作，默认 origin）",
                "default": "origin",
            },
            "branch_name": {
                "type": "string",
                "description": "分支名（用于 branch 操作的创建/切换/删除）",
            },
            "branch_action": {
                "type": "string",
                "description": "分支操作类型：list(列出) / create(创建) / switch(切换) / delete(删除)，默认 list",
                "enum": ["list", "create", "switch", "delete"],
                "default": "list",
            },
            "limit": {
                "type": "integer",
                "description": "提交历史条数限制（用于 log 操作，默认 10）",
                "default": 10,
                "minimum": 1,
                "maximum": 100,
            },
            "target": {
                "type": "string",
                "description": "差异对比目标（用于 diff 操作，如分支名、commit hash，为空则对比工作区）",
            },
        },
        "required": ["action"],
    }

    # 支持的操作列表
    _SUPPORTED_ACTIONS = {"status", "commit", "push", "pull", "branch", "log", "diff"}

    def _run_git_command(
        self,
        args: list[str],
        repo_path: str,
        timeout: int = 60,
    ) -> dict[str, Any]:
        """执行 git 命令.

        Args:
            args: git 命令参数列表（不含 git 本身）
            repo_path: 仓库路径
            timeout: 超时时间（秒）

        Returns:
            执行结果字典
        """
        if not os.path.isdir(repo_path):
            return {
                "success": False,
                "message": f"目录不存在: {repo_path}",
                "data": {"repo_path": repo_path},
            }

        try:
            cmd = ["git"] + args
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                cwd=repo_path,
                timeout=timeout,
            )

            success = result.returncode == 0
            return {
                "success": success,
                "message": "命令执行成功" if success else f"git 命令失败: {result.stderr.strip()}",
                "data": {
                    "command": "git " + " ".join(args),
                    "stdout": result.stdout.strip(),
                    "stderr": result.stderr.strip(),
                    "returncode": result.returncode,
                    "repo_path": repo_path,
                },
            }

        except subprocess.TimeoutExpired:
            return {
                "success": False,
                "message": f"git 命令超时（{timeout}秒）",
                "data": {
                    "command": "git " + " ".join(args),
                    "repo_path": repo_path,
                },
            }
        except FileNotFoundError:
            return {
                "success": False,
                "message": "未找到 git 命令，请确认 Git 已安装并在 PATH 中",
                "data": {"repo_path": repo_path},
            }
        except Exception as e:
            return {
                "success": False,
                "message": f"执行 git 命令时发生异常: {e}",
                "data": {
                    "command": "git " + " ".join(args),
                    "repo_path": repo_path,
                    "error": str(e),
                },
            }

    def _get_repo_path(
        self,
        params: dict[str, Any],
        context: dict[str, Any],
    ) -> str:
        """获取仓库路径.

        Args:
            params: 参数字典
            context: 上下文字典

        Returns:
            仓库路径
        """
        repo_path = (
            params.get("repo_path")
            or context.get("project_path")
            or context.get("workspace")
            or os.getcwd()
        )
        return os.path.abspath(repo_path) if repo_path else os.getcwd()

    def execute(
        self,
        params: dict[str, Any],
        context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """执行 Git 操作.

        Args:
            params: 参数字典
            context: 执行上下文

        Returns:
            执行结果字典
        """
        ctx = context or {}
        action = params.get("action", "")

        if not action:
            return {
                "success": False,
                "message": "缺少 action 参数",
                "data": {"supported_actions": sorted(self._SUPPORTED_ACTIONS)},
            }

        if action not in self._SUPPORTED_ACTIONS:
            return {
                "success": False,
                "message": f"不支持的操作: {action}",
                "data": {"supported_actions": sorted(self._SUPPORTED_ACTIONS)},
            }

        repo_path = self._get_repo_path(params, ctx)

        # 根据 action 分发
        handler = getattr(self, f"_handle_{action}", None)
        if handler is None:
            return {
                "success": False,
                "message": f"操作 {action} 暂无处理方法",
                "data": {"action": action},
            }

        try:
            result = handler(repo_path, params, ctx)
            return result
        except Exception as e:
            return {
                "success": False,
                "message": f"执行 {action} 时发生异常: {e}",
                "data": {
                    "action": action,
                    "repo_path": repo_path,
                    "error": str(e),
                },
            }

    def _handle_status(
        self,
        repo_path: str,
        params: dict[str, Any],
        context: dict[str, Any],
    ) -> dict[str, Any]:
        """处理查看状态操作."""
        result = self._run_git_command(["status", "--short"], repo_path)
        if not result["success"]:
            return result

        stdout = result["data"]["stdout"]
        lines = stdout.splitlines() if stdout else []

        # 解析状态输出
        staged = []
        unstaged = []
        untracked = []

        for line in lines:
            if not line.strip():
                continue
            status_code = line[:2]
            file_path = line[3:].strip()

            if status_code[0] != " " and status_code[0] != "?":
                staged.append({"file": file_path, "status": status_code[0]})
            if status_code[1] != " " and status_code[1] != "?":
                unstaged.append({"file": file_path, "status": status_code[1]})
            if status_code[0] == "?" and status_code[1] == "?":
                untracked.append({"file": file_path})

        # 获取当前分支名
        branch_result = self._run_git_command(["branch", "--show-current"], repo_path)
        current_branch = branch_result["data"]["stdout"] if branch_result["success"] else ""

        return {
            "success": True,
            "message": f"状态获取成功，共 {len(lines)} 个变更文件",
            "data": {
                "repo_path": repo_path,
                "current_branch": current_branch,
                "staged": staged,
                "unstaged": unstaged,
                "untracked": untracked,
                "total_changes": len(lines),
                "raw_output": stdout,
            },
        }

    def _handle_commit(
        self,
        repo_path: str,
        params: dict[str, Any],
        context: dict[str, Any],
    ) -> dict[str, Any]:
        """处理提交操作."""
        message = params.get("message", "")
        if not message:
            return {
                "success": False,
                "message": "提交信息 (message) 不能为空",
                "data": {"repo_path": repo_path},
            }

        files = params.get("files", [])

        # 如果指定了文件，先 add 这些文件
        if files:
            add_result = self._run_git_command(["add"] + list(files), repo_path)
            if not add_result["success"]:
                return add_result
        else:
            # 否则 add 所有更改
            add_result = self._run_git_command(["add", "-A"], repo_path)
            if not add_result["success"]:
                return add_result

        # 执行 commit
        result = self._run_git_command(["commit", "-m", message], repo_path)
        if not result["success"]:
            # 可能是没有可提交的内容
            if "nothing to commit" in result["data"].get("stderr", ""):
                return {
                    "success": True,
                    "message": "没有可提交的更改",
                    "data": {
                        "repo_path": repo_path,
                        "committed": False,
                        "message": message,
                    },
                }
            return result

        # 获取 commit hash
        hash_result = self._run_git_command(["rev-parse", "HEAD"], repo_path)
        commit_hash = hash_result["data"]["stdout"] if hash_result["success"] else ""

        return {
            "success": True,
            "message": "提交成功",
            "data": {
                "repo_path": repo_path,
                "commit_hash": commit_hash,
                "message": message,
                "files": files,
                "output": result["data"]["stdout"],
            },
        }

    def _handle_push(
        self,
        repo_path: str,
        params: dict[str, Any],
        context: dict[str, Any],
    ) -> dict[str, Any]:
        """处理推送操作."""
        remote = params.get("remote", "origin")

        # 获取当前分支名
        branch_result = self._run_git_command(["branch", "--show-current"], repo_path)
        current_branch = branch_result["data"]["stdout"] if branch_result["success"] else ""

        if not current_branch:
            return {
                "success": False,
                "message": "无法获取当前分支名",
                "data": {"repo_path": repo_path},
            }

        result = self._run_git_command(
            ["push", remote, current_branch],
            repo_path,
            timeout=120,
        )

        if not result["success"]:
            return result

        return {
            "success": True,
            "message": f"已推送到 {remote}/{current_branch}",
            "data": {
                "repo_path": repo_path,
                "remote": remote,
                "branch": current_branch,
                "output": result["data"]["stdout"] or result["data"]["stderr"],
            },
        }

    def _handle_pull(
        self,
        repo_path: str,
        params: dict[str, Any],
        context: dict[str, Any],
    ) -> dict[str, Any]:
        """处理拉取操作."""
        remote = params.get("remote", "origin")

        result = self._run_git_command(
            ["pull", remote],
            repo_path,
            timeout=120,
        )

        if not result["success"]:
            return result

        return {
            "success": True,
            "message": "拉取成功",
            "data": {
                "repo_path": repo_path,
                "remote": remote,
                "output": result["data"]["stdout"] or result["data"]["stderr"],
            },
        }

    def _handle_branch(
        self,
        repo_path: str,
        params: dict[str, Any],
        context: dict[str, Any],
    ) -> dict[str, Any]:
        """处理分支管理操作."""
        branch_action = params.get("branch_action", "list")
        branch_name = params.get("branch_name", "")

        if branch_action == "list":
            return self._list_branches(repo_path)

        elif branch_action == "create":
            if not branch_name:
                return {
                    "success": False,
                    "message": "分支名 (branch_name) 不能为空",
                    "data": {"repo_path": repo_path},
                }
            result = self._run_git_command(["branch", branch_name], repo_path)
            if not result["success"]:
                return result
            return {
                "success": True,
                "message": f"分支 {branch_name} 创建成功",
                "data": {
                    "repo_path": repo_path,
                    "branch": branch_name,
                    "action": "create",
                },
            }

        elif branch_action == "switch":
            if not branch_name:
                return {
                    "success": False,
                    "message": "分支名 (branch_name) 不能为空",
                    "data": {"repo_path": repo_path},
                }
            result = self._run_git_command(["checkout", branch_name], repo_path)
            if not result["success"]:
                return result
            return {
                "success": True,
                "message": f"已切换到分支 {branch_name}",
                "data": {
                    "repo_path": repo_path,
                    "branch": branch_name,
                    "action": "switch",
                },
            }

        elif branch_action == "delete":
            if not branch_name:
                return {
                    "success": False,
                    "message": "分支名 (branch_name) 不能为空",
                    "data": {"repo_path": repo_path},
                }
            result = self._run_git_command(["branch", "-d", branch_name], repo_path)
            if not result["success"]:
                # 尝试强制删除
                result = self._run_git_command(["branch", "-D", branch_name], repo_path)
                if not result["success"]:
                    return result
            return {
                "success": True,
                "message": f"分支 {branch_name} 已删除",
                "data": {
                    "repo_path": repo_path,
                    "branch": branch_name,
                    "action": "delete",
                },
            }

        else:
            return {
                "success": False,
                "message": f"不支持的分支操作: {branch_action}",
                "data": {"supported": ["list", "create", "switch", "delete"]},
            }

    def _list_branches(self, repo_path: str) -> dict[str, Any]:
        """列出所有分支."""
        result = self._run_git_command(["branch", "-a"], repo_path)
        if not result["success"]:
            return result

        stdout = result["data"]["stdout"]
        lines = stdout.splitlines() if stdout else []

        local_branches = []
        remote_branches = []
        current_branch = ""

        for line in lines:
            line = line.strip()
            if not line:
                continue

            if line.startswith("*"):
                current_branch = line[1:].strip()
                local_branches.append(current_branch)
            elif line.startswith("remotes/"):
                remote_branches.append(line[len("remotes/"):])
            else:
                local_branches.append(line)

        return {
            "success": True,
            "message": f"共 {len(local_branches) + len(remote_branches)} 个分支",
            "data": {
                "repo_path": repo_path,
                "current_branch": current_branch,
                "local_branches": local_branches,
                "remote_branches": remote_branches,
                "total_local": len(local_branches),
                "total_remote": len(remote_branches),
            },
        }

    def _handle_log(
        self,
        repo_path: str,
        params: dict[str, Any],
        context: dict[str, Any],
    ) -> dict[str, Any]:
        """处理查看提交历史操作."""
        limit = params.get("limit", 10)
        limit = min(max(limit, 1), 100)  # 限制在 1-100 之间

        # 格式化输出：hash|author|date|message
        format_str = "%H|%an|%ai|%s"
        result = self._run_git_command(
            ["log", f"-{limit}", f"--pretty=format:{format_str}"],
            repo_path,
        )

        if not result["success"]:
            return result

        stdout = result["data"]["stdout"]
        lines = stdout.splitlines() if stdout else []

        commits = []
        for line in lines:
            parts = line.split("|", 3)
            if len(parts) == 4:
                commits.append({
                    "hash": parts[0],
                    "short_hash": parts[0][:7],
                    "author": parts[1],
                    "date": parts[2],
                    "message": parts[3],
                })

        return {
            "success": True,
            "message": f"获取到 {len(commits)} 条提交记录",
            "data": {
                "repo_path": repo_path,
                "commits": commits,
                "count": len(commits),
                "limit": limit,
            },
        }

    def _handle_diff(
        self,
        repo_path: str,
        params: dict[str, Any],
        context: dict[str, Any],
    ) -> dict[str, Any]:
        """处理差异对比操作."""
        target = params.get("target", "")

        if target:
            # 对比指定目标（分支、commit 等）
            result = self._run_git_command(["diff", target], repo_path)
        else:
            # 对比工作区与暂存区
            result = self._run_git_command(["diff"], repo_path)

        if not result["success"]:
            return result

        diff_output = result["data"]["stdout"]
        has_changes = bool(diff_output.strip())

        return {
            "success": True,
            "message": "差异获取成功" if has_changes else "没有差异",
            "data": {
                "repo_path": repo_path,
                "target": target,
                "has_changes": has_changes,
                "diff": diff_output,
            },
        }

    def health_check(self) -> bool:
        """检查 Git 是否可用."""
        try:
            result = subprocess.run(
                ["git", "--version"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            return result.returncode == 0
        except Exception as e:
            logger.warning("git_skill.health_check_failed", error_type=type(e).__name__, error=str(e))
            return False
