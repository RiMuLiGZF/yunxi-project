"""M9 Programming Dev - 项目管理器"""

import os
import json
import uuid
from typing import List, Optional, Dict
from datetime import datetime
from .config import settings
from .models import ProjectInfo
from .path_safety import safe_join, is_path_safe, PathSecurityError


class ProjectManager:
    """项目管理器"""
    
    def __init__(self):
        self._projects_dir = settings.projects_root_dir
        os.makedirs(self._projects_dir, exist_ok=True)
        self._cache: Dict[str, ProjectInfo] = {}
        self._load_all()
    
    def _project_meta_path(self, project_id: str) -> str:
        return os.path.join(self._projects_dir, project_id, ".project.json")
    
    def _load_all(self):
        """加载所有项目元数据"""
        if not os.path.exists(self._projects_dir):
            return
        for pid in os.listdir(self._projects_dir):
            meta_path = os.path.join(self._projects_dir, pid, ".project.json")
            if os.path.exists(meta_path):
                try:
                    with open(meta_path, 'r', encoding='utf-8') as f:
                        data = json.load(f)
                    self._cache[pid] = ProjectInfo(**data)
                except Exception:
                    pass
    
    def list_projects(self) -> List[ProjectInfo]:
        """列出所有项目"""
        return sorted(self._cache.values(), key=lambda p: p.updated_at, reverse=True)
    
    def get_project(self, project_id: str) -> Optional[ProjectInfo]:
        """获取项目信息"""
        return self._cache.get(project_id)
    
    def create_project(self, name: str, description: str = "", language: str = "") -> ProjectInfo:
        """创建新项目"""
        project_id = str(uuid.uuid4())[:8]
        project_path = os.path.join(self._projects_dir, project_id)
        os.makedirs(project_path, exist_ok=True)
        
        now = datetime.now().isoformat()
        project = ProjectInfo(
            id=project_id,
            name=name,
            path=project_path,
            description=description,
            language=language,
            created_at=now,
            updated_at=now
        )
        
        # 保存元数据
        with open(self._project_meta_path(project_id), 'w', encoding='utf-8') as f:
            f.write(project.model_dump_json(indent=2))
        
        self._cache[project_id] = project
        return project
    
    def delete_project(self, project_id: str) -> bool:
        """删除项目"""
        if project_id not in self._cache:
            return False

        project = self._cache[project_id]

        # P2-23: 路径安全检查，确保要删除的路径在项目根目录内
        if not is_path_safe(self._projects_dir, project.path):
            return False

        import shutil
        try:
            shutil.rmtree(project.path)
        except Exception:
            return False
        
        del self._cache[project_id]
        return True
    
    def get_project_files(self, project_id: str, path: str = "") -> List[Dict]:
        """获取项目文件列表"""
        project = self._cache.get(project_id)
        if not project:
            return []

        # P2-23: 路径安全检查，防止路径遍历
        full_path = safe_join(project.path, path) if path else project.path
        if not full_path or not os.path.exists(full_path):
            return []
        
        files = []
        for item in os.listdir(full_path):
            item_path = os.path.join(full_path, item)
            is_dir = os.path.isdir(item_path)
            files.append({
                "name": item,
                "is_dir": is_dir,
                "path": os.path.join(path, item) if path else item,
                "size": os.path.getsize(item_path) if not is_dir else 0
            })
        
        return sorted(files, key=lambda f: (not f["is_dir"], f["name"]))


# 全局单例
project_manager = ProjectManager()
