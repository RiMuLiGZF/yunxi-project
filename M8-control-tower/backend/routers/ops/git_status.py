"""
Git 状态看板路由 (GIT-05)
- 获取当前仓库状态（分支、变更文件数、最近提交）
- 获取最近提交记录
- 获取分支列表
- 触发提交（需要 owner 权限）
- 获取指定文件的 diff
"""

import sys
import os
import subprocess
import re
from pathlib import Path
from datetime import datetime
from typing import List, Dict, Any, Optional
from fastapi import APIRouter, Depends, Query, HTTPException
from pydantic import BaseModel, Field

project_root = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(project_root))

from ...schemas import ApiResponse
from ...auth import get_current_user, has_role

router = APIRouter()

# Git 仓库路径（项目根目录）
REPO_PATH = project_root


# ============================================================
# 工具函数
# ============================================================

def _run_git(args: List[str], cwd: Path = REPO_PATH, timeout: int = 30) -> tuple:
    """运行 git 命令，返回 (returncode, stdout, stderr)"""
    try:
        result = subprocess.run(
            ["git"] + args,
            capture_output=True,
            text=True,
            cwd=str(cwd),
            timeout=timeout,
            encoding="utf-8",
            errors="replace",
        )
        return result.returncode, result.stdout.strip(), result.stderr.strip()
    except subprocess.TimeoutExpired:
        return -1, "", "Git 命令执行超时"
    except FileNotFoundError:
        return -1, "", "Git 未安装或不在 PATH 中"
    except Exception as e:
        return -1, "", str(e)


def _is_git_repo() -> bool:
    """检查是否为 Git 仓库"""
    code, _, _ = _run_git(["rev-parse", "--is-inside-work-tree"])
    return code == 0


def _parse_git_date(date_str: str) -> Optional[float]:
    """解析 git 日期格式为时间戳"""
    if not date_str:
        return None
    try:
        # git --format=%ai 输出格式: 2024-01-15 10:30:00 +0800
        dt = datetime.strptime(date_str[:19], "%Y-%m-%d %H:%M:%S")
        return dt.timestamp()
    except (ValueError, IndexError):
        return None


# ============================================================
# Pydantic 模型
# ============================================================

class GitCommitRequest(BaseModel):
    """提交请求体"""
    message: str = Field(..., description="提交信息（需符合 Conventional Commits 规范）")
    add_all: bool = Field(False, description="是否自动添加所有变更文件")
    files: Optional[List[str]] = Field(None, description="指定要提交的文件列表")


# ============================================================
# 接口实现
# ============================================================

@router.get("/status")
async def get_git_status(current_user: dict = Depends(get_current_user)):
    """获取当前仓库状态（分支、变更文件数、最近提交）"""
    if not _is_git_repo():
        return ApiResponse.error(code=503, message="Git 仓库未初始化")

    # 当前分支
    code, branch, _ = _run_git(["rev-parse", "--abbrev-ref", "HEAD"])
    if code != 0:
        branch = "unknown"

    # 最近一次提交的 hash
    code, last_commit_hash, _ = _run_git(["rev-parse", "HEAD"])
    if code != 0:
        last_commit_hash = ""

    # 最近一次提交信息
    code, last_commit_info, _ = _run_git([
        "log", "-1",
        "--format=%H%n%an%n%ae%n%ai%n%s"
    ])
    last_commit = None
    if code == 0 and last_commit_info:
        lines = last_commit_info.split("\n")
        if len(lines) >= 5:
            last_commit = {
                "hash": lines[0],
                "author": lines[1],
                "email": lines[2],
                "date": lines[3],
                "timestamp": _parse_git_date(lines[3]),
                "message": lines[4],
            }

    # 变更文件统计
    code, status_output, _ = _run_git(["status", "--porcelain"])
    changed_files = []
    staged_count = 0
    unstaged_count = 0
    untracked_count = 0

    if code == 0 and status_output:
        for line in status_output.split("\n"):
            if not line.strip():
                continue
            status_code = line[:2]
            file_path = line[3:].strip()
            changed_files.append({
                "status": status_code.strip(),
                "file": file_path,
                "staged": status_code[0] != " " and status_code[0] != "?",
                "unstaged": status_code[1] != " " and status_code[1] != "?",
            })
            if status_code[0] not in (" ", "?"):
                staged_count += 1
            if status_code[1] not in (" ", "?"):
                unstaged_count += 1
            if status_code == "??":
                untracked_count += 1

    # 远程信息
    code, remote_output, _ = _run_git(["remote", "-v"])
    remotes = []
    if code == 0 and remote_output:
        seen = set()
        for line in remote_output.split("\n"):
            if not line.strip():
                continue
            parts = line.split()
            if len(parts) >= 2:
                name = parts[0]
                url = parts[1]
                if name not in seen:
                    remotes.append({"name": name, "url": url})
                    seen.add(name)

    # 是否有未推送的提交
    code, ahead_behind, _ = _run_git(["rev-list", "--left-right", "--count", "HEAD...@{u}"])
    ahead = 0
    behind = 0
    if code == 0 and ahead_behind:
        parts = ahead_behind.split()
        if len(parts) == 2:
            ahead = int(parts[0])
            behind = int(parts[1])

    status = {
        "branch": branch,
        "last_commit": last_commit,
        "last_commit_hash": last_commit_hash[:7] if last_commit_hash else "",
        "changed_files": {
            "total": len(changed_files),
            "staged": staged_count,
            "unstaged": unstaged_count,
            "untracked": untracked_count,
            "files": changed_files[:50],  # 最多返回 50 个文件
        },
        "remotes": remotes,
        "ahead": ahead,
        "behind": behind,
        "is_repo": True,
        "repo_path": str(REPO_PATH),
    }

    return ApiResponse.success(data=status)


@router.get("/commits")
async def get_git_commits(
    limit: int = Query(20, description="返回条数，默认 20，最大 100"),
    branch: Optional[str] = Query(None, description="分支名，默认当前分支"),
    current_user: dict = Depends(get_current_user),
):
    """获取最近提交记录"""
    if not _is_git_repo():
        return ApiResponse.error(code=503, message="Git 仓库未初始化")

    limit = min(max(1, limit), 100)

    args = ["log", f"-{limit}", "--format=%H%n%an%n%ae%n%ai%n%s%n%b---END---"]
    if branch:
        args.append(branch)

    code, output, _ = _run_git(args)
    if code != 0:
        return ApiResponse.error(code=500, message=f"获取提交记录失败: {_}")

    commits = []
    if output:
        # 按分隔符拆分每个提交
        blocks = output.split("---END---")
        for block in blocks:
            block = block.strip()
            if not block:
                continue
            lines = block.strip().split("\n")
            if len(lines) < 5:
                continue
            # 第5行之后是 body
            body = "\n".join(lines[5:]).strip() if len(lines) > 5 else ""
            commit = {
                "hash": lines[0],
                "short_hash": lines[0][:7],
                "author": lines[1],
                "email": lines[2],
                "date": lines[3],
                "timestamp": _parse_git_date(lines[3]),
                "message": lines[4],
                "body": body,
            }
            commits.append(commit)

    return ApiResponse.success(data={
        "total": len(commits),
        "items": commits,
        "branch": branch or "HEAD",
    })


@router.get("/branches")
async def get_git_branches(current_user: dict = Depends(get_current_user)):
    """获取分支列表"""
    if not _is_git_repo():
        return ApiResponse.error(code=503, message="Git 仓库未初始化")

    # 本地分支
    code, local_output, _ = _run_git(["branch", "--format=%(refname:short)%09%(objectname:short)%09%(committerdate:iso8601)"])
    local_branches = []
    current_branch = ""
    if code == 0 and local_output:
        for line in local_output.split("\n"):
            if not line.strip():
                continue
            parts = line.split("\t")
            name = parts[0].lstrip("*").strip()
            if line.startswith("*"):
                current_branch = name
            local_branches.append({
                "name": name,
                "hash": parts[1] if len(parts) > 1 else "",
                "last_commit_date": parts[2] if len(parts) > 2 else "",
                "is_current": name == current_branch,
                "type": "local",
            })

    # 远程分支
    code, remote_output, _ = _run_git(["branch", "-r", "--format=%(refname:short)%09%(objectname:short)%09%(committerdate:iso8601)"])
    remote_branches = []
    if code == 0 and remote_output:
        for line in remote_output.split("\n"):
            if not line.strip():
                continue
            parts = line.split("\t")
            name = parts[0].strip()
            # 跳过 HEAD 指针
            if "HEAD" in name:
                continue
            remote_branches.append({
                "name": name,
                "hash": parts[1] if len(parts) > 1 else "",
                "last_commit_date": parts[2] if len(parts) > 2 else "",
                "is_current": False,
                "type": "remote",
            })

    return ApiResponse.success(data={
        "current_branch": current_branch,
        "local": {
            "total": len(local_branches),
            "items": local_branches,
        },
        "remote": {
            "total": len(remote_branches),
            "items": remote_branches,
        },
    })


@router.post("/commit")
async def create_commit(
    req: GitCommitRequest,
    current_user: dict = Depends(get_current_user),
):
    """触发提交（需要 owner 或 admin 权限）"""
    # 权限检查
    if not has_role(current_user.get("role", ""), "admin"):
        return ApiResponse.error(
            code=403,
            message="权限不足：需要 owner 或 admin 角色才能触发提交"
        )

    if not _is_git_repo():
        return ApiResponse.error(code=503, message="Git 仓库未初始化")

    if not req.message or not req.message.strip():
        return ApiResponse.error(code=400, message="提交信息不能为空")

    # 提交信息格式检查（Conventional Commits）
    commit_types = ["feat", "fix", "docs", "style", "refactor", "perf", "test",
                    "build", "ci", "chore", "revert", "wip", "merge", "release", "deploy", "hotfix"]
    pattern = r"^(?P<type>" + "|".join(commit_types) + r")(?:\([a-zA-Z0-9_\-]+\))?!?:\s+.+$"
    if not re.match(pattern, req.message.strip(), re.IGNORECASE):
        return ApiResponse.error(
            code=400,
            message="提交信息不符合 Conventional Commits 格式，应为: <type>(<scope>): <subject>"
        )

    # 添加文件
    if req.add_all:
        code, _, err = _run_git(["add", "-A"])
        if code != 0:
            return ApiResponse.error(code=500, message=f"添加文件失败: {err}")
    elif req.files:
        # 安全检查：防止路径遍历
        for f in req.files:
            if ".." in f or f.startswith("/") or f.startswith("\\"):
                return ApiResponse.error(code=400, message=f"非法文件路径: {f}")
        code, _, err = _run_git(["add"] + req.files)
        if code != 0:
            return ApiResponse.error(code=500, message=f"添加文件失败: {err}")
    else:
        # 检查是否有暂存内容
        code, diff_output, _ = _run_git(["diff", "--cached", "--name-only"])
        if code != 0 or not diff_output.strip():
            return ApiResponse.error(code=400, message="没有暂存的文件，请先 add 文件或设置 add_all=true")

    # 执行提交
    code, _, err = _run_git(["commit", "-m", req.message.strip()])
    if code != 0:
        return ApiResponse.error(code=500, message=f"提交失败: {err}")

    # 获取新提交的 hash
    code, commit_hash, _ = _run_git(["rev-parse", "HEAD"])
    short_hash = commit_hash[:7] if code == 0 else ""

    return ApiResponse.success(
        data={
            "commit_hash": commit_hash,
            "short_hash": short_hash,
            "message": req.message.strip(),
        },
        message="提交成功"
    )


@router.get("/diff")
async def get_git_diff(
    file: str = Query(..., description="文件路径（相对仓库根目录）"),
    staged: bool = Query(False, description="是否比较暂存区（否则比较工作区）"),
    current_user: dict = Depends(get_current_user),
):
    """获取指定文件的 diff"""
    if not _is_git_repo():
        return ApiResponse.error(code=503, message="Git 仓库未初始化")

    if not file or not file.strip():
        return ApiResponse.error(code=400, message="文件路径不能为空")

    # 安全检查：防止路径遍历
    if ".." in file or file.startswith("/") or file.startswith("\\"):
        return ApiResponse.error(code=400, message="非法文件路径")

    # 检查文件是否存在
    file_path = REPO_PATH / file
    if not file_path.exists():
        return ApiResponse.error(code=404, message=f"文件不存在: {file}")

    # 获取 diff
    args = ["diff", "--no-color"]
    if staged:
        args.append("--cached")
    args.append(file)

    code, diff_output, err = _run_git(args)
    if code != 0:
        return ApiResponse.error(code=500, message=f"获取 diff 失败: {err}")

    # 如果没有 diff 输出，可能是未跟踪文件，返回文件内容
    if not diff_output.strip():
        code, status_out, _ = _run_git(["status", "--porcelain", file])
        if code == 0 and status_out.strip().startswith("??"):
            # 未跟踪文件，返回全部内容
            try:
                with open(file_path, "r", encoding="utf-8", errors="replace") as f:
                    content = f.read()
                diff_output = f"新增文件: {file}\n\n" + content
            except Exception as e:
                diff_output = f"无法读取文件: {e}"

    # 统计变更行数
    added = 0
    removed = 0
    for line in diff_output.split("\n"):
        if line.startswith("+") and not line.startswith("+++"):
            added += 1
        elif line.startswith("-") and not line.startswith("---"):
            removed += 1

    return ApiResponse.success(data={
        "file": file,
        "staged": staged,
        "diff": diff_output,
        "stats": {
            "additions": added,
            "deletions": removed,
            "total": added + removed,
        },
    })


@router.get("/health")
async def git_health():
    """Git 健康检查（无需鉴权，供系统检查调用）"""
    try:
        code, version_out, _ = _run_git(["--version"])
        git_available = code == 0
        is_repo = _is_git_repo()

        return ApiResponse.success(data={
            "git_installed": git_available,
            "git_version": version_out if git_available else "",
            "is_repo": is_repo,
            "repo_path": str(REPO_PATH),
        })
    except Exception as e:
        return ApiResponse.error(code=500, message=str(e))
