"""工作开发模式 - 数据访问层.

封装项目、任务、提交记录、代码片段、开发会话、代码使用统计的
数据库 CRUD 操作。首次使用时自动初始化种子数据，确保开箱即用。
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta
from typing import Any, Optional

from sqlalchemy import desc, func
from sqlalchemy.orm import Session

from src.database import (
    WorkCodeSnippetDB,
    WorkCodeUsageDB,
    WorkCommitDB,
    WorkDevSessionDB,
    WorkProjectDB,
    WorkTaskDB,
)


# ---------------------------------------------------------------------------
# 种子数据
# ---------------------------------------------------------------------------


def _get_default_projects(user_id: str = "default") -> list[WorkProjectDB]:
    """获取默认项目种子数据.

    Args:
        user_id: 用户 ID

    Returns:
        默认项目列表
    """
    now = datetime.utcnow()
    return [
        WorkProjectDB(
            project_id=1,
            name="云汐系统",
            description="云汐AI助手核心系统，包含多模块协同架构",
            status="active",
            progress=65,
            language="python",
            category="后端开发",
            file_count=128,
            line_count=28500,
            commit_count=156,
            user_id=user_id,
            created_at=now - timedelta(days=60),
            updated_at=now - timedelta(hours=2),
        ),
        WorkProjectDB(
            project_id=2,
            name="前端门户",
            description="Web前端门户页面，响应式UI设计",
            status="active",
            progress=45,
            language="javascript",
            category="前端开发",
            file_count=86,
            line_count=15200,
            commit_count=98,
            user_id=user_id,
            created_at=now - timedelta(days=45),
            updated_at=now - timedelta(hours=5),
        ),
        WorkProjectDB(
            project_id=3,
            name="数据分析平台",
            description="数据可视化与分析平台",
            status="planning",
            progress=10,
            language="python",
            category="数据科学",
            file_count=12,
            line_count=2800,
            commit_count=15,
            user_id=user_id,
            created_at=now - timedelta(days=15),
            updated_at=now - timedelta(days=3),
        ),
    ]


def _get_default_tasks(user_id: str = "default") -> list[WorkTaskDB]:
    """获取默认任务种子数据.

    Args:
        user_id: 用户 ID

    Returns:
        默认任务列表
    """
    now = datetime.utcnow()
    return [
        WorkTaskDB(
            task_id=1, title="实现用户认证模块",
            description="完成登录、注册、权限校验功能",
            status="done", priority="high",
            project_id=1, assignee="云汐",
            tags=["后端", "安全"],
            estimate_hours=16, spent_hours=18,
            user_id=user_id,
            created_at=now - timedelta(days=20),
            updated_at=now - timedelta(days=10),
        ),
        WorkTaskDB(
            task_id=2, title="开发Agent调度系统",
            description="多Agent协同调度框架",
            status="in_progress", priority="high",
            project_id=1, assignee="云汐",
            tags=["架构", "核心"],
            estimate_hours=40, spent_hours=25,
            user_id=user_id,
            created_at=now - timedelta(days=12),
            updated_at=now - timedelta(hours=3),
        ),
        WorkTaskDB(
            task_id=3, title="编写API文档",
            description="Swagger自动生成文档",
            status="todo", priority="medium",
            project_id=1, assignee="云汐",
            tags=["文档"],
            estimate_hours=8, spent_hours=0,
            user_id=user_id,
            created_at=now - timedelta(days=8),
            updated_at=now - timedelta(days=8),
        ),
        WorkTaskDB(
            task_id=4, title="性能优化",
            description="接口响应时间优化到200ms以内",
            status="todo", priority="medium",
            project_id=1, assignee="云汐",
            tags=["性能", "优化"],
            estimate_hours=24, spent_hours=0,
            user_id=user_id,
            created_at=now - timedelta(days=6),
            updated_at=now - timedelta(days=6),
        ),
        WorkTaskDB(
            task_id=5, title="首页UI设计",
            description="系统门户首页设计与实现",
            status="done", priority="high",
            project_id=2, assignee="云汐",
            tags=["UI", "设计"],
            estimate_hours=12, spent_hours=14,
            user_id=user_id,
            created_at=now - timedelta(days=18),
            updated_at=now - timedelta(days=8),
        ),
        WorkTaskDB(
            task_id=6, title="响应式布局",
            description="移动端适配",
            status="in_progress", priority="medium",
            project_id=2, assignee="云汐",
            tags=["前端", "适配"],
            estimate_hours=20, spent_hours=12,
            user_id=user_id,
            created_at=now - timedelta(days=10),
            updated_at=now - timedelta(hours=6),
        ),
        WorkTaskDB(
            task_id=7, title="需求分析",
            description="平台功能需求调研",
            status="done", priority="high",
            project_id=3, assignee="云汐",
            tags=["需求"],
            estimate_hours=8, spent_hours=10,
            user_id=user_id,
            created_at=now - timedelta(days=14),
            updated_at=now - timedelta(days=10),
        ),
        WorkTaskDB(
            task_id=8, title="技术选型",
            description="确定技术栈和架构方案",
            status="in_progress", priority="high",
            project_id=3, assignee="云汐",
            tags=["架构", "技术"],
            estimate_hours=16, spent_hours=8,
            user_id=user_id,
            created_at=now - timedelta(days=7),
            updated_at=now - timedelta(days=1),
        ),
    ]


def _get_default_commits(user_id: str = "default") -> list[WorkCommitDB]:
    """获取默认提交记录种子数据.

    Args:
        user_id: 用户 ID

    Returns:
        默认提交记录列表
    """
    now = datetime.utcnow()
    commit_messages = [
        (1, "feat: 实现多Agent联邦调度系统", 120, 30, 5),
        (1, "fix: 修复首页API鉴权问题", 25, 8, 2),
        (1, "feat: 新增技能集群模块", 80, 15, 4),
        (1, "refactor: 重构配置管理系统", 60, 45, 3),
        (1, "docs: 更新API文档", 15, 5, 1),
        (1, "fix: 修复端口冲突问题", 10, 12, 2),
        (2, "feat: 新增成长中心模块", 90, 20, 6),
        (2, "style: 优化UI样式", 50, 30, 4),
    ]
    commits = []
    for i, (pid, msg, adds, dels, files) in enumerate(commit_messages):
        commits.append(WorkCommitDB(
            commit_id=i + 1,
            hash=uuid.uuid4().hex[:8],
            message=msg,
            author="云汐",
            project_id=pid,
            branch="main",
            additions=adds,
            deletions=dels,
            files_changed=files,
            committed_at=now - timedelta(hours=i * 6),
            user_id=user_id,
        ))
    return commits


def _get_default_snippets(user_id: str = "default") -> list[WorkCodeSnippetDB]:
    """获取默认代码片段种子数据.

    Args:
        user_id: 用户 ID

    Returns:
        默认代码片段列表
    """
    now = datetime.utcnow()
    return [
        WorkCodeSnippetDB(
            snippet_id=1,
            title="快速排序算法",
            language="python",
            code="def quick_sort(arr):\n    if len(arr) <= 1:\n        return arr\n    pivot = arr[len(arr) // 2]\n    left = [x for x in arr if x < pivot]\n    middle = [x for x in arr if x == pivot]\n    right = [x for x in arr if x > pivot]\n    return quick_sort(left) + middle + quick_sort(right)",
            description="经典快速排序实现，时间复杂度 O(n log n)",
            tags=["算法", "排序"],
            is_favorite=True,
            project_id=1,
            user_id=user_id,
            created_at=now - timedelta(days=25),
            updated_at=now - timedelta(days=20),
        ),
        WorkCodeSnippetDB(
            snippet_id=2,
            title="单例模式装饰器",
            language="python",
            code="def singleton(cls):\n    instances = {}\n    def wrapper(*args, **kwargs):\n        if cls not in instances:\n            instances[cls] = cls(*args, **kwargs)\n        return instances[cls]\n    return wrapper",
            description="线程安全的单例模式装饰器实现",
            tags=["设计模式", "工具"],
            is_favorite=False,
            project_id=1,
            user_id=user_id,
            created_at=now - timedelta(days=15),
            updated_at=now - timedelta(days=12),
        ),
    ]


def seed_work_dev_data(db: Session, user_id: str = "default") -> bool:
    """初始化工作开发模式的默认种子数据（幂等）.

    仅在项目表为空时执行初始化。

    Args:
        db: 数据库会话
        user_id: 用户 ID

    Returns:
        True 表示执行了初始化，False 表示已有数据跳过
    """
    project_count = (
        db.query(WorkProjectDB)
        .filter(WorkProjectDB.user_id == user_id)
        .count()
    )
    if project_count > 0:
        return False

    # 插入默认项目
    for project in _get_default_projects(user_id):
        db.add(project)
    db.flush()

    # 插入默认任务
    for task in _get_default_tasks(user_id):
        db.add(task)

    # 插入默认提交
    for commit in _get_default_commits(user_id):
        db.add(commit)

    # 插入默认代码片段
    for snippet in _get_default_snippets(user_id):
        db.add(snippet)

    db.commit()
    print(f"[Seed] 工作开发模式默认数据初始化完成 (user_id={user_id})")
    return True


# ---------------------------------------------------------------------------
# Repository 类
# ---------------------------------------------------------------------------


class WorkDevRepository:
    """工作开发数据仓库.

    提供项目、任务、提交记录、代码片段、开发会话、代码使用统计的
    数据库操作。首次实例化时自动初始化种子数据。
    """

    def __init__(self, db: Session, user_id: str = "default") -> None:
        """初始化数据仓库.

        Args:
            db: 数据库会话
            user_id: 用户 ID
        """
        self.db = db
        self.user_id = user_id
        self._ensure_seeded()

    def _ensure_seeded(self) -> None:
        """确保种子数据已初始化."""
        try:
            seed_work_dev_data(self.db, self.user_id)
        except Exception as e:
            print(f"[Seed] 工作开发数据初始化跳过: {e}")

    # -----------------------------------------------------------------------
    # 项目相关方法
    # -----------------------------------------------------------------------

    def list_projects(
        self,
        status: Optional[str] = None,
        category: Optional[str] = None,
    ) -> list[WorkProjectDB]:
        """获取项目列表（支持筛选）.

        Args:
            status: 按状态筛选
            category: 按分类筛选

        Returns:
            项目列表，按更新时间倒序排列
        """
        query = (
            self.db.query(WorkProjectDB)
            .filter(WorkProjectDB.user_id == self.user_id)
        )
        if status:
            query = query.filter(WorkProjectDB.status == status)
        if category:
            query = query.filter(WorkProjectDB.category == category)
        return query.order_by(desc(WorkProjectDB.updated_at)).all()

    def get_project(self, project_id: int) -> Optional[WorkProjectDB]:
        """按 ID 获取项目.

        Args:
            project_id: 项目业务 ID

        Returns:
            项目对象，不存在返回 None
        """
        return (
            self.db.query(WorkProjectDB)
            .filter(
                WorkProjectDB.project_id == project_id,
                WorkProjectDB.user_id == self.user_id,
            )
            .first()
        )

    def create_project(
        self,
        name: str,
        description: str = "",
        language: str = "python",
        category: str = "",
        status: str = "planning",
    ) -> WorkProjectDB:
        """创建项目.

        Args:
            name: 项目名称
            description: 项目描述
            language: 主要语言
            category: 项目分类
            status: 状态

        Returns:
            创建后的项目对象
        """
        # 计算下一个 project_id
        max_id = (
            self.db.query(func.max(WorkProjectDB.project_id))
            .filter(WorkProjectDB.user_id == self.user_id)
            .scalar()
        ) or 0

        now = datetime.utcnow()
        project = WorkProjectDB(
            project_id=max_id + 1,
            name=name,
            description=description,
            status=status,
            progress=0,
            language=language,
            category=category,
            file_count=0,
            line_count=0,
            commit_count=0,
            user_id=self.user_id,
            created_at=now,
            updated_at=now,
        )
        self.db.add(project)
        self.db.commit()
        self.db.refresh(project)
        return project

    def update_project(
        self,
        project_id: int,
        **kwargs: Any,
    ) -> Optional[WorkProjectDB]:
        """更新项目信息.

        Args:
            project_id: 项目 ID
            **kwargs: 待更新的字段

        Returns:
            更新后的项目对象，不存在返回 None
        """
        project = self.get_project(project_id)
        if not project:
            return None

        valid_fields = [
            "name", "description", "status", "progress",
            "language", "category", "repo_url",
            "file_count", "line_count", "commit_count",
        ]
        for key, value in kwargs.items():
            if value is None:
                continue
            if key in valid_fields and hasattr(project, key):
                setattr(project, key, value)

        project.updated_at = datetime.utcnow()
        self.db.commit()
        self.db.refresh(project)
        return project

    def delete_project(self, project_id: int) -> bool:
        """删除项目（同时删除关联的任务和提交）.

        Args:
            project_id: 项目 ID

        Returns:
            True 表示删除成功，False 表示不存在
        """
        project = self.get_project(project_id)
        if not project:
            return False

        # 删除关联任务
        self.db.query(WorkTaskDB).filter(
            WorkTaskDB.user_id == self.user_id,
            WorkTaskDB.project_id == project_id,
        ).delete(synchronize_session=False)

        # 删除关联提交
        self.db.query(WorkCommitDB).filter(
            WorkCommitDB.user_id == self.user_id,
            WorkCommitDB.project_id == project_id,
        ).delete(synchronize_session=False)

        # 删除关联代码片段
        self.db.query(WorkCodeSnippetDB).filter(
            WorkCodeSnippetDB.user_id == self.user_id,
            WorkCodeSnippetDB.project_id == project_id,
        ).delete(synchronize_session=False)

        self.db.delete(project)
        self.db.commit()
        return True

    def count_projects(self, status: Optional[str] = None) -> int:
        """统计项目数量.

        Args:
            status: 按状态筛选

        Returns:
            项目数量
        """
        query = self.db.query(WorkProjectDB).filter(
            WorkProjectDB.user_id == self.user_id
        )
        if status:
            query = query.filter(WorkProjectDB.status == status)
        return query.count()

    def total_line_count(self) -> int:
        """统计所有项目的代码总行数.

        Returns:
            代码总行数
        """
        result = (
            self.db.query(func.sum(WorkProjectDB.line_count))
            .filter(WorkProjectDB.user_id == self.user_id)
            .scalar()
        )
        return int(result or 0)

    # -----------------------------------------------------------------------
    # 任务相关方法
    # -----------------------------------------------------------------------

    def list_tasks(
        self,
        project_id: Optional[int] = None,
        status: Optional[str] = None,
        priority: Optional[str] = None,
    ) -> list[WorkTaskDB]:
        """获取任务列表（支持筛选）.

        Args:
            project_id: 按项目筛选
            status: 按状态筛选
            priority: 按优先级筛选

        Returns:
            任务列表，按更新时间倒序排列
        """
        query = (
            self.db.query(WorkTaskDB)
            .filter(WorkTaskDB.user_id == self.user_id)
        )
        if project_id:
            query = query.filter(WorkTaskDB.project_id == project_id)
        if status:
            query = query.filter(WorkTaskDB.status == status)
        if priority:
            query = query.filter(WorkTaskDB.priority == priority)
        return query.order_by(desc(WorkTaskDB.updated_at)).all()

    def get_task(self, task_id: int) -> Optional[WorkTaskDB]:
        """按 ID 获取任务.

        Args:
            task_id: 任务业务 ID

        Returns:
            任务对象，不存在返回 None
        """
        return (
            self.db.query(WorkTaskDB)
            .filter(
                WorkTaskDB.task_id == task_id,
                WorkTaskDB.user_id == self.user_id,
            )
            .first()
        )

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
    ) -> WorkTaskDB:
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
            创建后的任务对象
        """
        max_id = (
            self.db.query(func.max(WorkTaskDB.task_id))
            .filter(WorkTaskDB.user_id == self.user_id)
            .scalar()
        ) or 0

        now = datetime.utcnow()
        task = WorkTaskDB(
            task_id=max_id + 1,
            title=title,
            description=description,
            status=status,
            priority=priority,
            project_id=project_id,
            assignee=assignee,
            due_date=due_date,
            tags=tags or [],
            estimate_hours=estimate_hours,
            spent_hours=0,
            user_id=self.user_id,
            created_at=now,
            updated_at=now,
        )
        self.db.add(task)

        # 更新项目更新时间
        if project_id:
            project = self.get_project(project_id)
            if project:
                project.updated_at = now

        self.db.commit()
        self.db.refresh(task)
        return task

    def update_task(
        self,
        task_id: int,
        **kwargs: Any,
    ) -> Optional[WorkTaskDB]:
        """更新任务信息.

        Args:
            task_id: 任务 ID
            **kwargs: 待更新的字段

        Returns:
            更新后的任务对象，不存在返回 None
        """
        task = self.get_task(task_id)
        if not task:
            return None

        valid_fields = [
            "title", "description", "status", "priority",
            "project_id", "assignee", "due_date", "tags",
            "estimate_hours", "spent_hours",
        ]
        for key, value in kwargs.items():
            if value is None:
                continue
            if key in valid_fields and hasattr(task, key):
                setattr(task, key, value)

        task.updated_at = datetime.utcnow()

        # 更新项目更新时间
        if task.project_id:
            project = self.get_project(task.project_id)
            if project:
                project.updated_at = task.updated_at

        self.db.commit()
        self.db.refresh(task)
        return task

    def update_task_status(self, task_id: int, status: str) -> Optional[WorkTaskDB]:
        """更新任务状态.

        Args:
            task_id: 任务 ID
            status: 新状态

        Returns:
            更新后的任务对象，不存在返回 None
        """
        valid_statuses = {"todo", "in_progress", "review", "done"}
        if status not in valid_statuses:
            return self.get_task(task_id)
        return self.update_task(task_id, status=status)

    def delete_task(self, task_id: int) -> bool:
        """删除任务.

        Args:
            task_id: 任务 ID

        Returns:
            True 表示删除成功，False 表示不存在
        """
        task = self.get_task(task_id)
        if not task:
            return False
        self.db.delete(task)
        self.db.commit()
        return True

    def count_tasks(self, status: Optional[str] = None) -> int:
        """统计任务数量.

        Args:
            status: 按状态筛选

        Returns:
            任务数量
        """
        query = self.db.query(WorkTaskDB).filter(
            WorkTaskDB.user_id == self.user_id
        )
        if status:
            query = query.filter(WorkTaskDB.status == status)
        return query.count()

    # -----------------------------------------------------------------------
    # 提交记录相关方法
    # -----------------------------------------------------------------------

    def list_commits(
        self,
        project_id: Optional[int] = None,
        limit: int = 20,
    ) -> list[WorkCommitDB]:
        """获取提交记录列表.

        Args:
            project_id: 按项目筛选
            limit: 返回条数限制

        Returns:
            提交记录列表，按时间倒序
        """
        query = (
            self.db.query(WorkCommitDB)
            .filter(WorkCommitDB.user_id == self.user_id)
        )
        if project_id:
            query = query.filter(WorkCommitDB.project_id == project_id)
        return (
            query.order_by(desc(WorkCommitDB.committed_at))
            .limit(limit)
            .all()
        )

    def get_commit(self, commit_id: int) -> Optional[WorkCommitDB]:
        """按 ID 获取提交记录.

        Args:
            commit_id: 提交业务 ID

        Returns:
            提交记录对象，不存在返回 None
        """
        return (
            self.db.query(WorkCommitDB)
            .filter(
                WorkCommitDB.commit_id == commit_id,
                WorkCommitDB.user_id == self.user_id,
            )
            .first()
        )

    def create_commit(
        self,
        message: str,
        project_id: int = 1,
        branch: str = "main",
        author: str = "云汐",
        additions: int = 0,
        deletions: int = 0,
        files_changed: int = 0,
    ) -> WorkCommitDB:
        """创建提交记录（模拟提交）.

        Args:
            message: 提交信息
            project_id: 项目 ID
            branch: 分支
            author: 作者
            additions: 新增行数
            deletions: 删除行数
            files_changed: 变更文件数

        Returns:
            创建后的提交记录对象
        """
        max_id = (
            self.db.query(func.max(WorkCommitDB.commit_id))
            .filter(WorkCommitDB.user_id == self.user_id)
            .scalar()
        ) or 0

        now = datetime.utcnow()
        commit = WorkCommitDB(
            commit_id=max_id + 1,
            hash=uuid.uuid4().hex[:8],
            message=message,
            author=author,
            project_id=project_id,
            branch=branch,
            additions=additions,
            deletions=deletions,
            files_changed=files_changed,
            committed_at=now,
            user_id=self.user_id,
        )
        self.db.add(commit)

        # 更新项目统计
        project = self.get_project(project_id)
        if project:
            project.commit_count = (project.commit_count or 0) + 1
            project.line_count = (project.line_count or 0) + additions - deletions
            project.updated_at = now

        self.db.commit()
        self.db.refresh(commit)
        return commit

    def count_commits(self, project_id: Optional[int] = None) -> int:
        """统计提交数量.

        Args:
            project_id: 按项目筛选

        Returns:
            提交数量
        """
        query = self.db.query(WorkCommitDB).filter(
            WorkCommitDB.user_id == self.user_id
        )
        if project_id:
            query = query.filter(WorkCommitDB.project_id == project_id)
        return query.count()

    def count_week_commits(self) -> int:
        """统计本周提交次数.

        Returns:
            近 7 天的提交次数
        """
        week_ago = datetime.utcnow() - timedelta(days=7)
        return (
            self.db.query(WorkCommitDB)
            .filter(
                WorkCommitDB.user_id == self.user_id,
                WorkCommitDB.committed_at >= week_ago,
            )
            .count()
        )

    def get_commit_stats(self, project_id: Optional[int] = None) -> dict[str, Any]:
        """获取提交统计数据.

        Args:
            project_id: 按项目筛选

        Returns:
            提交统计字典
        """
        query = self.db.query(WorkCommitDB).filter(
            WorkCommitDB.user_id == self.user_id
        )
        if project_id:
            query = query.filter(WorkCommitDB.project_id == project_id)

        commits = query.all()

        total_insertions = sum(c.additions or 0 for c in commits)
        total_deletions = sum(c.deletions or 0 for c in commits)

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

        return {
            "total_commits": len(commits),
            "total_insertions": total_insertions,
            "total_deletions": total_deletions,
            "daily_commits": daily,
        }

    # -----------------------------------------------------------------------
    # 代码片段相关方法
    # -----------------------------------------------------------------------

    def list_snippets(
        self,
        language: Optional[str] = None,
        tag: Optional[str] = None,
        only_favorite: bool = False,
    ) -> list[WorkCodeSnippetDB]:
        """获取代码片段列表.

        Args:
            language: 按语言筛选
            tag: 按标签筛选
            only_favorite: 只显示收藏的

        Returns:
            代码片段列表，按更新时间倒序
        """
        query = (
            self.db.query(WorkCodeSnippetDB)
            .filter(WorkCodeSnippetDB.user_id == self.user_id)
        )
        if language:
            query = query.filter(WorkCodeSnippetDB.language == language)
        if only_favorite:
            query = query.filter(WorkCodeSnippetDB.is_favorite == True)  # noqa: E712

        snippets = query.order_by(desc(WorkCodeSnippetDB.updated_at)).all()
        if tag:
            snippets = [s for s in snippets if tag in (s.tags or [])]
        return snippets

    def get_snippet(self, snippet_id: int) -> Optional[WorkCodeSnippetDB]:
        """按 ID 获取代码片段.

        Args:
            snippet_id: 片段业务 ID

        Returns:
            代码片段对象，不存在返回 None
        """
        return (
            self.db.query(WorkCodeSnippetDB)
            .filter(
                WorkCodeSnippetDB.snippet_id == snippet_id,
                WorkCodeSnippetDB.user_id == self.user_id,
            )
            .first()
        )

    def create_snippet(
        self,
        title: str,
        language: str = "python",
        code: str = "",
        description: str = "",
        tags: Optional[list[str]] = None,
        project_id: int = 0,
    ) -> WorkCodeSnippetDB:
        """创建代码片段.

        Args:
            title: 片段标题
            language: 编程语言
            code: 代码内容
            description: 描述说明
            tags: 标签列表
            project_id: 所属项目 ID

        Returns:
            创建后的代码片段对象
        """
        max_id = (
            self.db.query(func.max(WorkCodeSnippetDB.snippet_id))
            .filter(WorkCodeSnippetDB.user_id == self.user_id)
            .scalar()
        ) or 0

        now = datetime.utcnow()
        snippet = WorkCodeSnippetDB(
            snippet_id=max_id + 1,
            title=title,
            language=language,
            code=code,
            description=description,
            tags=tags or [],
            is_favorite=False,
            project_id=project_id,
            user_id=self.user_id,
            created_at=now,
            updated_at=now,
        )
        self.db.add(snippet)
        self.db.commit()
        self.db.refresh(snippet)
        return snippet

    def update_snippet(
        self,
        snippet_id: int,
        **kwargs: Any,
    ) -> Optional[WorkCodeSnippetDB]:
        """更新代码片段.

        Args:
            snippet_id: 片段 ID
            **kwargs: 待更新的字段

        Returns:
            更新后的代码片段对象，不存在返回 None
        """
        snippet = self.get_snippet(snippet_id)
        if not snippet:
            return None

        valid_fields = [
            "title", "language", "code", "description",
            "tags", "is_favorite", "project_id",
        ]
        for key, value in kwargs.items():
            if value is None:
                continue
            if key in valid_fields and hasattr(snippet, key):
                setattr(snippet, key, value)

        snippet.updated_at = datetime.utcnow()
        self.db.commit()
        self.db.refresh(snippet)
        return snippet

    def delete_snippet(self, snippet_id: int) -> bool:
        """删除代码片段.

        Args:
            snippet_id: 片段 ID

        Returns:
            True 表示删除成功，False 表示不存在
        """
        snippet = self.get_snippet(snippet_id)
        if not snippet:
            return False
        self.db.delete(snippet)
        self.db.commit()
        return True

    # -----------------------------------------------------------------------
    # 开发会话相关方法
    # -----------------------------------------------------------------------

    def list_sessions(
        self,
        session_type: Optional[str] = None,
        limit: int = 20,
    ) -> list[WorkDevSessionDB]:
        """获取开发会话列表.

        Args:
            session_type: 按类型筛选
            limit: 返回条数限制

        Returns:
            会话列表，按更新时间倒序
        """
        query = (
            self.db.query(WorkDevSessionDB)
            .filter(WorkDevSessionDB.user_id == self.user_id)
        )
        if session_type:
            query = query.filter(WorkDevSessionDB.session_type == session_type)
        return (
            query.order_by(desc(WorkDevSessionDB.updated_at))
            .limit(limit)
            .all()
        )

    def get_session(self, session_id: str) -> Optional[WorkDevSessionDB]:
        """按 ID 获取开发会话.

        Args:
            session_id: 会话 ID

        Returns:
            会话对象，不存在返回 None
        """
        return (
            self.db.query(WorkDevSessionDB)
            .filter(
                WorkDevSessionDB.session_id == session_id,
                WorkDevSessionDB.user_id == self.user_id,
            )
            .first()
        )

    def get_or_create_session(
        self,
        session_id: str,
        session_type: str = "code_chat",
        language: str = "python",
        project_id: int = 0,
    ) -> WorkDevSessionDB:
        """获取或创建开发会话.

        Args:
            session_id: 会话 ID
            session_type: 会话类型
            language: 编程语言
            project_id: 关联项目 ID

        Returns:
            会话对象
        """
        session = self.get_session(session_id)
        if session:
            return session

        now = datetime.utcnow()
        session = WorkDevSessionDB(
            session_id=session_id,
            session_type=session_type,
            title="新对话",
            language=language,
            messages_json=[],
            project_id=project_id,
            message_count=0,
            user_id=self.user_id,
            created_at=now,
            updated_at=now,
        )
        self.db.add(session)
        self.db.commit()
        self.db.refresh(session)
        return session

    def append_message(
        self,
        session_id: str,
        role: str,
        content: str,
    ) -> Optional[WorkDevSessionDB]:
        """向会话追加消息.

        Args:
            session_id: 会话 ID
            role: 消息角色
            content: 消息内容

        Returns:
            更新后的会话对象，不存在返回 None
        """
        session = self.get_session(session_id)
        if not session:
            return None

        messages = session.messages_json or []
        messages.append({
            "role": role,
            "content": content,
            "timestamp": datetime.utcnow().isoformat(),
        })
        session.messages_json = messages
        session.message_count = len(messages)
        session.updated_at = datetime.utcnow()

        # 更新标题（取第一条用户消息）
        if session.title == "新对话" and role == "user":
            session.title = content[:30] + ("..." if len(content) > 30 else "")

        self.db.commit()
        self.db.refresh(session)
        return session

    def delete_session(self, session_id: str) -> bool:
        """删除开发会话.

        Args:
            session_id: 会话 ID

        Returns:
            True 表示删除成功，False 表示不存在
        """
        session = self.get_session(session_id)
        if not session:
            return False
        self.db.delete(session)
        self.db.commit()
        return True

    # -----------------------------------------------------------------------
    # 代码使用统计相关方法
    # -----------------------------------------------------------------------

    def record_usage(
        self,
        action_type: str,
        operation_type: str = "",
        language: str = "python",
        tokens_used: int = 0,
        project_id: int = 0,
        is_fallback: bool = False,
    ) -> WorkCodeUsageDB:
        """记录代码使用统计.

        Args:
            action_type: 操作类型
            operation_type: 操作子类型
            language: 编程语言
            tokens_used: 消耗 Token 数
            project_id: 所属项目 ID
            is_fallback: 是否为 fallback 模式

        Returns:
            创建后的使用记录对象
        """
        max_id = (
            self.db.query(func.max(WorkCodeUsageDB.usage_id))
            .filter(WorkCodeUsageDB.user_id == self.user_id)
            .scalar()
        ) or 0

        usage = WorkCodeUsageDB(
            usage_id=max_id + 1,
            action_type=action_type,
            operation_type=operation_type,
            language=language,
            tokens_used=tokens_used,
            project_id=project_id,
            is_fallback=is_fallback,
            user_id=self.user_id,
            created_at=datetime.utcnow(),
        )
        self.db.add(usage)
        self.db.commit()
        self.db.refresh(usage)
        return usage

    def get_today_token_usage(self) -> int:
        """获取今日 Token 消耗量.

        Returns:
            Token 数量
        """
        today_start = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
        result = (
            self.db.query(func.sum(WorkCodeUsageDB.tokens_used))
            .filter(
                WorkCodeUsageDB.user_id == self.user_id,
                WorkCodeUsageDB.created_at >= today_start,
            )
            .scalar()
        )
        return int(result or 0)
