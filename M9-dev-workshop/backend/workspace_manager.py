"""
云汐 M9 开发者工坊 - 工作区/项目管理
负责项目的 CRUD、自动扫描、最近打开记录、标签分类、统计等功能
"""

import os
import json
from datetime import datetime, timedelta
from typing import Optional, List, Dict
from pathlib import Path

# 兼容相对导入和直接运行
try:
    from .config import get_settings
    from .models import SessionLocal, WorkspaceProject, DevActivity
except ImportError:
    from config import get_settings
    from models import SessionLocal, WorkspaceProject, DevActivity


class WorkspaceManager:
    """工作区管理器类"""

    # 项目标识文件（用于识别目录是否为项目）
    PROJECT_MARKERS = [
        ".git",
        ".vscode",
        "package.json",
        "requirements.txt",
        "pyproject.toml",
        "Cargo.toml",
        "go.mod",
        "pom.xml",
        "build.gradle",
        "CMakeLists.txt",
        "Makefile",
        ".project",
        ".idea",
    ]

    def __init__(self):
        """初始化工作区管理器"""
        self.settings = get_settings()
        self._db = SessionLocal()
        # 确保工作区根目录存在
        os.makedirs(self.settings.workspace_root, exist_ok=True)

    # ===== 项目 CRUD =====

    def create_project(
        self,
        name: str,
        path: str,
        description: str = "",
        icon: str = "folder",
        tags: Optional[List[str]] = None,
    ) -> Dict:
        """
        创建新项目记录
        :return: 创建结果
        """
        # 检查路径是否已存在
        existing = self._db.query(WorkspaceProject).filter(WorkspaceProject.path == path).first()
        if existing:
            return {"success": False, "message": f"项目路径已存在: {path}", "project": existing.to_dict()}

        # 确保目录存在
        os.makedirs(path, exist_ok=True)

        project = WorkspaceProject(
            name=name,
            path=path,
            description=description,
            icon=icon,
            tags=tags or [],
        )
        self._db.add(project)
        self._db.commit()
        self._db.refresh(project)

        return {"success": True, "message": "项目创建成功", "project": project.to_dict()}

    def get_project(self, project_id: int) -> Optional[Dict]:
        """根据 ID 获取项目"""
        project = self._db.query(WorkspaceProject).filter(WorkspaceProject.id == project_id).first()
        return project.to_dict() if project else None

    def get_project_by_path(self, path: str) -> Optional[Dict]:
        """根据路径获取项目"""
        project = self._db.query(WorkspaceProject).filter(WorkspaceProject.path == path).first()
        return project.to_dict() if project else None

    def list_projects(
        self,
        tag: Optional[str] = None,
        keyword: Optional[str] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> List[Dict]:
        """
        列出项目列表
        :param tag: 按标签过滤
        :param keyword: 关键词搜索（名称或描述）
        :param limit: 数量限制
        :param offset: 偏移量
        """
        query = self._db.query(WorkspaceProject)

        if keyword:
            query = query.filter(
                (WorkspaceProject.name.like(f"%{keyword}%")) |
                (WorkspaceProject.description.like(f"%{keyword}%"))
            )

        # 按更新时间倒序
        query = query.order_by(WorkspaceProject.updated_at.desc())
        projects = query.offset(offset).limit(limit).all()

        result = [p.to_dict() for p in projects]

        # 标签过滤（SQLite JSON 字段在 ORM 层面处理）
        if tag:
            result = [p for p in result if tag in p.get("tags", [])]

        return result

    def update_project(self, project_id: int, **kwargs) -> Dict:
        """更新项目信息"""
        project = self._db.query(WorkspaceProject).filter(WorkspaceProject.id == project_id).first()
        if not project:
            return {"success": False, "message": "项目不存在"}

        # 更新允许的字段
        allowed_fields = ["name", "description", "icon", "tags"]
        for field in allowed_fields:
            if field in kwargs and kwargs[field] is not None:
                setattr(project, field, kwargs[field])

        project.updated_at = datetime.now()
        self._db.commit()
        self._db.refresh(project)

        return {"success": True, "message": "更新成功", "project": project.to_dict()}

    def delete_project(self, project_id: int, delete_files: bool = False) -> Dict:
        """
        删除项目
        :param project_id: 项目 ID
        :param delete_files: 是否同时删除文件（默认只删除记录）
        """
        project = self._db.query(WorkspaceProject).filter(WorkspaceProject.id == project_id).first()
        if not project:
            return {"success": False, "message": "项目不存在"}

        project_path = project.path
        self._db.delete(project)
        self._db.commit()

        # 如果需要删除文件
        if delete_files and os.path.exists(project_path):
            import shutil
            try:
                shutil.rmtree(project_path)
            except Exception as e:
                return {"success": True, "message": f"记录已删除，但文件删除失败: {str(e)}"}

        return {"success": True, "message": "项目已删除"}

    # ===== 项目打开/最近项目 =====

    def open_project(self, project_id: int) -> Dict:
        """记录项目打开（更新最后打开时间、打开次数+1）"""
        project = self._db.query(WorkspaceProject).filter(WorkspaceProject.id == project_id).first()
        if not project:
            return {"success": False, "message": "项目不存在"}

        project.last_opened = datetime.now()
        project.open_count += 1
        project.updated_at = datetime.now()
        self._db.commit()
        self._db.refresh(project)

        return {"success": True, "project": project.to_dict()}

    def get_recent_projects(self, limit: int = 10) -> List[Dict]:
        """获取最近打开的项目"""
        projects = (
            self._db.query(WorkspaceProject)
            .filter(WorkspaceProject.last_opened.isnot(None))
            .order_by(WorkspaceProject.last_opened.desc())
            .limit(limit)
            .all()
        )
        return [p.to_dict() for p in projects]

    # ===== 自动扫描项目 =====

    def scan_projects(self, scan_dirs: Optional[List[str]] = None, max_depth: int = 3) -> Dict:
        """
        扫描目录中的项目
        :param scan_dirs: 要扫描的目录列表，为 None 则使用配置中的目录
        :param max_depth: 最大扫描深度
        :return: 扫描结果 {"found": int, "added": int, "projects": [...]}
        """
        dirs_to_scan = scan_dirs or self.settings.scan_dirs
        found_projects = []
        added_count = 0

        for scan_dir in dirs_to_scan:
            scan_dir = os.path.expandvars(scan_dir)
            if not os.path.isdir(scan_dir):
                continue

            for root, dirs, files in os.walk(scan_dir):
                # 控制扫描深度
                depth = root.replace(scan_dir, "").count(os.sep)
                if depth >= max_depth:
                    dirs[:] = []  # 清空 dirs 阻止继续深入
                    continue

                # 检查是否为项目目录
                if self._is_project_dir(root, files):
                    project_name = os.path.basename(root)
                    found_projects.append({
                        "name": project_name,
                        "path": root,
                    })

                    # 如果数据库中不存在，则添加
                    existing = self._db.query(WorkspaceProject).filter(
                        WorkspaceProject.path == root
                    ).first()
                    if not existing:
                        project = WorkspaceProject(
                            name=project_name,
                            path=root,
                            description=f"自动扫描发现的项目",
                            icon=self._detect_project_icon(files),
                            tags=self._detect_project_tags(files),
                        )
                        self._db.add(project)
                        added_count += 1

        self._db.commit()

        return {
            "found": len(found_projects),
            "added": added_count,
            "projects": found_projects,
        }

    def _is_project_dir(self, dir_path: str, files: List[str]) -> bool:
        """判断目录是否为项目目录"""
        # 检查是否有项目标识文件
        for marker in self.PROJECT_MARKERS:
            marker_path = os.path.join(dir_path, marker)
            if os.path.exists(marker_path):
                return True
        return False

    def _detect_project_icon(self, files: List[str]) -> str:
        """根据项目类型检测项目图标"""
        file_set = set(files)
        if "package.json" in file_set:
            return "nodejs"
        if "requirements.txt" in file_set or "pyproject.toml" in file_set:
            return "python"
        if "Cargo.toml" in file_set:
            return "rust"
        if "go.mod" in file_set:
            return "go"
        if "pom.xml" in file_set or "build.gradle" in file_set:
            return "java"
        if ".git" in file_set or os.path.exists(os.path.join(".", ".git")):
            return "git-folder"
        return "folder"

    def _detect_project_tags(self, files: List[str]) -> List[str]:
        """根据项目文件检测标签"""
        tags = []
        file_set = set(files)
        if "package.json" in file_set:
            tags.append("nodejs")
            # 进一步检测框架
            if os.path.exists("package.json"):
                try:
                    with open("package.json", "r", encoding="utf-8") as f:
                        pkg = json.load(f)
                        deps = pkg.get("dependencies", {})
                        if "react" in deps:
                            tags.append("react")
                        if "vue" in deps:
                            tags.append("vue")
                        if "next" in deps:
                            tags.append("nextjs")
                except Exception:
                    pass
        if "requirements.txt" in file_set or "pyproject.toml" in file_set:
            tags.append("python")
        if "Dockerfile" in file_set:
            tags.append("docker")
        if ".git" in file_set:
            tags.append("git")
        return tags

    # ===== 标签管理 =====

    def get_all_tags(self) -> List[str]:
        """获取所有项目标签"""
        projects = self._db.query(WorkspaceProject).all()
        all_tags = set()
        for p in projects:
            if p.tags:
                all_tags.update(p.tags)
        return sorted(list(all_tags))

    def add_tag(self, project_id: int, tag: str) -> Dict:
        """为项目添加标签"""
        project = self._db.query(WorkspaceProject).filter(WorkspaceProject.id == project_id).first()
        if not project:
            return {"success": False, "message": "项目不存在"}

        tags = list(project.tags or [])
        if tag not in tags:
            tags.append(tag)
            project.tags = tags
            project.updated_at = datetime.now()
            self._db.commit()

        return {"success": True, "tags": tags}

    def remove_tag(self, project_id: int, tag: str) -> Dict:
        """移除项目标签"""
        project = self._db.query(WorkspaceProject).filter(WorkspaceProject.id == project_id).first()
        if not project:
            return {"success": False, "message": "项目不存在"}

        tags = list(project.tags or [])
        if tag in tags:
            tags.remove(tag)
            project.tags = tags
            project.updated_at = datetime.now()
            self._db.commit()

        return {"success": True, "tags": tags}

    # ===== 项目统计 =====

    def get_statistics(self) -> Dict:
        """获取工作区统计信息"""
        total_projects = self._db.query(WorkspaceProject).count()
        projects = self._db.query(WorkspaceProject).all()

        # 总开发时长
        total_dev_time = sum(p.total_dev_time or 0 for p in projects)

        # 总打开次数
        total_opens = sum(p.open_count or 0 for p in projects)

        # 今日活动数
        today = datetime.now().date()
        today_activities = (
            self._db.query(DevActivity)
            .filter(DevActivity.timestamp >= datetime.combine(today, datetime.min.time()))
            .count()
        )

        # 按标签分类统计
        tag_stats = {}
        for p in projects:
            for tag in (p.tags or []):
                tag_stats[tag] = tag_stats.get(tag, 0) + 1

        return {
            "total_projects": total_projects,
            "total_dev_time_minutes": round(total_dev_time, 2),
            "total_opens": total_opens,
            "today_activities": today_activities,
            "tag_distribution": tag_stats,
        }

    def get_project_stats(self, project_id: int) -> Optional[Dict]:
        """获取单个项目的统计信息"""
        project = self._db.query(WorkspaceProject).filter(WorkspaceProject.id == project_id).first()
        if not project:
            return None

        # 获取项目相关的活动
        activities = (
            self._db.query(DevActivity)
            .filter(DevActivity.project == project.name)
            .order_by(DevActivity.timestamp.desc())
            .limit(20)
            .all()
        )

        return {
            "project": project.to_dict(),
            "recent_activities": [a.to_dict() for a in activities],
        }

    # ===== 开发活动记录 =====

    def log_activity(
        self,
        project: str,
        activity_type: str,
        duration: float = 0,
        description: str = "",
        meta_data: Optional[Dict] = None,
    ) -> Dict:
        """记录开发活动"""
        activity = DevActivity(
            project=project,
            activity_type=activity_type,
            duration=duration,
            description=description,
            meta_data=meta_data or {},
        )
        self._db.add(activity)
        self._db.commit()
        self._db.refresh(activity)
        return {"success": True, "activity": activity.to_dict()}

    def get_activities(
        self,
        project: Optional[str] = None,
        activity_type: Optional[str] = None,
        days: int = 7,
        limit: int = 50,
    ) -> List[Dict]:
        """获取开发活动记录"""
        query = self._db.query(DevActivity)

        if project:
            query = query.filter(DevActivity.project == project)
        if activity_type:
            query = query.filter(DevActivity.activity_type == activity_type)

        # 时间范围
        since = datetime.now() - timedelta(days=days)
        query = query.filter(DevActivity.timestamp >= since)

        activities = query.order_by(DevActivity.timestamp.desc()).limit(limit).all()
        return [a.to_dict() for a in activities]

    def close(self):
        """关闭数据库连接"""
        self._db.close()


# 全局单例
_workspace_manager: Optional[WorkspaceManager] = None


def get_workspace_manager() -> WorkspaceManager:
    """获取工作区管理器单例"""
    global _workspace_manager
    if _workspace_manager is None:
        _workspace_manager = WorkspaceManager()
    return _workspace_manager


# 兼容直接运行测试
if __name__ == "__main__":
    mgr = get_workspace_manager()
    stats = mgr.get_statistics()
    print("工作区统计:")
    for k, v in stats.items():
        print(f"  {k}: {v}")
    print(f"\n最近项目: {len(mgr.get_recent_projects())} 个")
    mgr.close()
