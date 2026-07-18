"""
云汐 M9 开发者工坊 - 项目管理服务

提供项目的完整生命周期管理：
- 项目 CRUD（创建、查询、更新、删除、归档）
- 从模板创建项目
- 项目文件管理
- 文件搜索与替换
"""

from __future__ import annotations

import os
import shutil
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

try:
    from .config import get_settings
except ImportError:
    try:
        from config import get_settings
    except ImportError:
        from ...config import get_settings


class ProjectService:
    """开发者工坊项目管理服务"""

    # 内置模板定义
    BUILTIN_TEMPLATES: List[Dict[str, Any]] = [
        {
            "id": "tpl_blank",
            "name": "空白项目",
            "description": "从零开始的空白项目",
            "category": "基础",
            "project_type": "web_app",
            "language": "",
            "framework": "",
            "icon": "📁",
            "files": {},
        },
        {
            "id": "tpl_python_package",
            "name": "Python 包",
            "description": "标准 Python 包项目结构，包含 setup.py 和测试目录",
            "category": "Python",
            "project_type": "python_module",
            "language": "python",
            "framework": "",
            "icon": "🐍",
            "files": {
                "src/__init__.py": '"""项目包入口."""\n\n__version__ = "0.1.0"\n',
                "src/main.py": '"""主入口模块."""\n\n\ndef main():\n    """主函数."""\n    print("Hello from 云汐开发者工坊!")\n    return 0\n\n\nif __name__ == "__main__":\n    exit(main())\n',
                "tests/__init__.py": '"""测试包."""\n',
                "tests/test_main.py": '"""主模块测试."""\n\nimport pytest\nfrom src.main import main\n\n\ndef test_main():\n    assert main() == 0\n',
                "setup.py": '''"""项目安装配置."""\n\nfrom setuptools import setup, find_packages\n\nsetup(\n    name="my-project",\n    version="0.1.0",\n    packages=find_packages(where="src"),\n    package_dir={"": "src"},\n    python_requires=">=3.8",\n)\n''',
                "requirements.txt": "# 项目依赖\n# 在此添加依赖包\n",
                "README.md": "# Python 包项目\n\n使用云汐 M9 开发者工坊创建的 Python 包项目。\n\n## 安装\n```bash\npip install -e .\n```\n\n## 测试\n```bash\npytest tests/\n```\n",
                ".gitignore": "__pycache__/\n*.py[cod]\n*$py.class\n*.egg-info/\ndist/\nbuild/\n.eggs/\n.pytest_cache/\n.venv/\nvenv/\nenv/\n",
            },
        },
        {
            "id": "tpl_skill_plugin",
            "name": "技能插件",
            "description": "云汐技能插件项目模板，用于创建自定义 AI 技能",
            "category": "云汐",
            "project_type": "skill",
            "language": "python",
            "framework": "yunxi-skill",
            "icon": "⚡",
            "files": {
                "skill.py": '''"""云汐技能插件主文件."""

from typing import Dict, Any


class MySkill:
    """自定义技能类."""

    name = "my-skill"
    description = "我的自定义技能"
    version = "0.1.0"

    def __init__(self, config: Dict[str, Any] = None):
        self.config = config or {}

    def execute(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """执行技能.

        Args:
            params: 输入参数

        Returns:
            执行结果
        """
        return {
            "success": True,
            "message": "技能执行成功",
            "data": params,
        }

    def get_tools(self) -> list:
        """获取技能提供的工具列表."""
        return [
            {
                "name": "my_tool",
                "description": "我的工具",
                "input_schema": {},
            }
        ]
''',
                "skill.json": '''{
    "name": "my-skill",
    "version": "0.1.0",
    "description": "我的自定义技能",
    "author": "",
    "entry_point": "skill.py:MySkill",
    "categories": ["general"],
    "permissions": []
}
''',
                "tests/test_skill.py": '''"""技能测试."""

import pytest
from skill import MySkill


def test_skill_init():
    skill = MySkill()
    assert skill.name == "my-skill"


def test_skill_execute():
    skill = MySkill()
    result = skill.execute({"test": "value"})
    assert result["success"] is True
''',
                "README.md": "# 云汐技能插件\n\n使用云汐 M9 开发者工坊创建的技能插件项目。\n\n## 功能\n- 自定义 AI 技能\n- 工具注册\n- 配置化管理\n",
                "requirements.txt": "# 技能依赖\n# 在此添加依赖包\n",
            },
        },
        {
            "id": "tpl_workflow",
            "name": "工作流",
            "description": "自动化工作流项目模板，支持多步骤编排",
            "category": "云汐",
            "project_type": "workflow",
            "language": "python",
            "framework": "yunxi-workflow",
            "icon": "🔄",
            "files": {
                "workflow.py": '''"""工作流定义."""

from typing import Dict, Any, List, Callable


class WorkflowStep:
    """工作流步骤."""

    def __init__(self, name: str, func: Callable):
        self.name = name
        self.func = func

    def execute(self, context: Dict[str, Any]) -> Dict[str, Any]:
        return self.func(context)


class Workflow:
    """工作流编排器."""

    def __init__(self, name: str):
        self.name = name
        self.steps: List[WorkflowStep] = []

    def add_step(self, step: WorkflowStep):
        self.steps.append(step)

    def run(self, initial_context: Dict[str, Any] = None) -> Dict[str, Any]:
        context = initial_context or {}
        for step in self.steps:
            context = step.execute(context)
        return context


# 示例工作流
def step_hello(context: Dict[str, Any]) -> Dict[str, Any]:
    print("Hello from workflow!")
    context["greeting"] = "hello"
    return context


def step_goodbye(context: Dict[str, Any]) -> Dict[str, Any]:
    print("Goodbye from workflow!")
    context["farewell"] = "goodbye"
    return context


def create_default_workflow() -> Workflow:
    wf = Workflow("default")
    wf.add_step(WorkflowStep("hello", step_hello))
    wf.add_step(WorkflowStep("goodbye", step_goodbye))
    return wf


if __name__ == "__main__":
    wf = create_default_workflow()
    result = wf.run()
    print(f"Workflow result: {result}")
''',
                "workflow.json": '''{
    "name": "default-workflow",
    "version": "0.1.0",
    "description": "默认工作流",
    "steps": [
        {"id": "hello", "name": "Hello Step", "type": "python"},
        {"id": "goodbye", "name": "Goodbye Step", "type": "python"}
    ]
}
''',
                "tests/test_workflow.py": '''"""工作流测试."""

import pytest
from workflow import Workflow, WorkflowStep, create_default_workflow


def test_workflow_creation():
    wf = create_default_workflow()
    assert len(wf.steps) == 2


def test_workflow_run():
    wf = create_default_workflow()
    result = wf.run({"input": "test"})
    assert result["greeting"] == "hello"
    assert result["farewell"] == "goodbye"
''',
                "README.md": "# 云汐工作流项目\n\n使用云汐 M9 开发者工坊创建的工作流项目。\n\n## 运行\n```bash\npython workflow.py\n```\n",
            },
        },
        {
            "id": "tpl_web_app",
            "name": "Web 应用",
            "description": "FastAPI Web 应用项目模板",
            "category": "Web",
            "project_type": "web_app",
            "language": "python",
            "framework": "fastapi",
            "icon": "🌐",
            "files": {
                "main.py": '''"""FastAPI Web 应用主入口."""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

app = FastAPI(
    title="云汐 Web 应用",
    description="使用 M9 开发者工坊创建的 Web 应用",
    version="0.1.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/")
async def root():
    return {"message": "Hello from 云汐开发者工坊!"}


@app.get("/health")
async def health():
    return {"status": "healthy"}


@app.get("/api/info")
async def api_info():
    return {
        "name": "云汐 Web 应用",
        "version": "0.1.0",
        "endpoints": ["/", "/health", "/api/info"],
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
''',
                "requirements.txt": "fastapi>=0.104.0\nuvicorn[standard]>=0.24.0\n",
                "README.md": "# Web 应用项目\n\n使用云汐 M9 开发者工坊创建的 FastAPI Web 应用。\n\n## 安装依赖\n```bash\npip install -r requirements.txt\n```\n\n## 运行\n```bash\npython main.py\n```\n\n## API 文档\n启动后访问 http://localhost:8000/docs\n",
                ".gitignore": "__pycache__/\n*.pyc\n.venv/\nvenv/\n.env\n*.log\n",
            },
        },
    ]

    def __init__(self):
        self.settings = get_settings()
        self._projects_dir = Path(self.settings.workspace_root) / "dev_projects"
        self._projects_dir.mkdir(parents=True, exist_ok=True)

    # ============================================================
    # 项目 CRUD
    # ============================================================

    def create_project(
        self,
        name: str,
        project_type: str = "web_app",
        template_id: str = "",
        owner_id: str = "default",
        description: str = "",
        language: str = "",
        framework: str = "",
        settings: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """创建新项目

        Args:
            name: 项目名称
            project_type: 项目类型
            template_id: 模板ID
            owner_id: 所有者ID
            description: 项目描述
            language: 编程语言
            framework: 框架
            settings: 项目设置

        Returns:
            创建的项目信息
        """
        from models import SessionLocal, Project

        db = SessionLocal()
        try:
            # 检查同名项目是否已存在（同一用户下）
            existing = (
                db.query(Project)
                .filter(
                    Project.name == name,
                    Project.owner_id == owner_id,
                    Project.status != "deleted",
                )
                .first()
            )
            if existing:
                return {"success": False, "error": f"项目 '{name}' 已存在"}

            # 创建项目记录
            project = Project(
                name=name,
                description=description,
                owner_id=owner_id,
                project_type=project_type,
                template_id=template_id,
                language=language,
                framework=framework,
                settings=settings or {},
                status="active",
            )
            db.add(project)
            db.flush()  # 获取 ID

            # 创建项目目录
            project_dir = self._get_project_dir(project.id)
            project_dir.mkdir(parents=True, exist_ok=True)

            # 如果有模板，从模板创建文件
            if template_id:
                self._apply_template(project.id, template_id)

            db.commit()
            db.refresh(project)
            return {"success": True, "project": project.to_dict()}
        except Exception as e:
            db.rollback()
            return {"success": False, "error": str(e)}
        finally:
            db.close()

    def get_project(self, project_id: int, owner_id: Optional[str] = None) -> Dict[str, Any]:
        """获取项目详情

        Args:
            project_id: 项目ID
            owner_id: 所有者ID（可选，用于权限校验）

        Returns:
            项目信息
        """
        from models import SessionLocal, Project

        db = SessionLocal()
        try:
            project = db.query(Project).filter(Project.id == project_id).first()
            if not project:
                return {"success": False, "error": "项目不存在"}
            if project.status == "deleted":
                return {"success": False, "error": "项目已删除"}
            if owner_id and project.owner_id != owner_id:
                return {"success": False, "error": "无权限访问"}

            # 更新最后打开时间
            project.last_opened_at = datetime.now()
            db.commit()
            db.refresh(project)

            return {"success": True, "project": project.to_dict()}
        except Exception as e:
            return {"success": False, "error": str(e)}
        finally:
            db.close()

    def list_projects(
        self,
        owner_id: str = "default",
        status: Optional[str] = None,
        project_type: Optional[str] = None,
        page: int = 1,
        page_size: int = 20,
        keyword: str = "",
    ) -> Dict[str, Any]:
        """获取项目列表

        Args:
            owner_id: 所有者ID
            status: 状态过滤
            project_type: 类型过滤
            page: 页码
            page_size: 每页数量
            keyword: 搜索关键词

        Returns:
            项目列表和分页信息
        """
        from models import SessionLocal, Project
        from sqlalchemy import and_

        db = SessionLocal()
        try:
            query = db.query(Project).filter(
                Project.owner_id == owner_id,
                Project.status != "deleted",
            )

            if status:
                query = query.filter(Project.status == status)
            if project_type:
                query = query.filter(Project.project_type == project_type)
            if keyword:
                query = query.filter(Project.name.like(f"%{keyword}%"))

            total = query.count()
            projects = (
                query.order_by(Project.updated_at.desc())
                .offset((page - 1) * page_size)
                .limit(page_size)
                .all()
            )

            return {
                "success": True,
                "projects": [p.to_dict() for p in projects],
                "total": total,
                "page": page,
                "page_size": page_size,
                "total_pages": (total + page_size - 1) // page_size,
            }
        except Exception as e:
            return {"success": False, "error": str(e), "projects": [], "total": 0}
        finally:
            db.close()

    def update_project(
        self, project_id: int, data: Dict[str, Any], owner_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """更新项目信息

        Args:
            project_id: 项目ID
            data: 更新数据
            owner_id: 所有者ID（权限校验）

        Returns:
            更新后的项目信息
        """
        from models import SessionLocal, Project

        db = SessionLocal()
        try:
            project = db.query(Project).filter(Project.id == project_id).first()
            if not project:
                return {"success": False, "error": "项目不存在"}
            if project.status == "deleted":
                return {"success": False, "error": "项目已删除"}
            if owner_id and project.owner_id != owner_id:
                return {"success": False, "error": "无权限修改"}

            # 更新字段
            allowed_fields = [
                "name", "description", "project_type",
                "language", "framework", "settings",
            ]
            for field in allowed_fields:
                if field in data and data[field] is not None:
                    setattr(project, field, data[field])

            project.updated_at = datetime.now()
            db.commit()
            db.refresh(project)
            return {"success": True, "project": project.to_dict()}
        except Exception as e:
            db.rollback()
            return {"success": False, "error": str(e)}
        finally:
            db.close()

    def delete_project(self, project_id: int, owner_id: Optional[str] = None) -> Dict[str, Any]:
        """软删除项目

        Args:
            project_id: 项目ID
            owner_id: 所有者ID

        Returns:
            操作结果
        """
        from models import SessionLocal, Project

        db = SessionLocal()
        try:
            project = db.query(Project).filter(Project.id == project_id).first()
            if not project:
                return {"success": False, "error": "项目不存在"}
            if owner_id and project.owner_id != owner_id:
                return {"success": False, "error": "无权限删除"}

            project.status = "deleted"
            project.updated_at = datetime.now()
            db.commit()
            return {"success": True, "message": "项目已删除"}
        except Exception as e:
            db.rollback()
            return {"success": False, "error": str(e)}
        finally:
            db.close()

    def archive_project(self, project_id: int, owner_id: Optional[str] = None) -> Dict[str, Any]:
        """归档项目

        Args:
            project_id: 项目ID
            owner_id: 所有者ID

        Returns:
            操作结果
        """
        from models import SessionLocal, Project

        db = SessionLocal()
        try:
            project = db.query(Project).filter(Project.id == project_id).first()
            if not project:
                return {"success": False, "error": "项目不存在"}
            if owner_id and project.owner_id != owner_id:
                return {"success": False, "error": "无权限操作"}
            if project.status == "deleted":
                return {"success": False, "error": "项目已删除"}

            project.status = "archived"
            project.updated_at = datetime.now()
            db.commit()
            return {"success": True, "message": "项目已归档"}
        except Exception as e:
            db.rollback()
            return {"success": False, "error": str(e)}
        finally:
            db.close()

    def unarchive_project(self, project_id: int, owner_id: Optional[str] = None) -> Dict[str, Any]:
        """取消归档项目

        Args:
            project_id: 项目ID
            owner_id: 所有者ID

        Returns:
            操作结果
        """
        from models import SessionLocal, Project

        db = SessionLocal()
        try:
            project = db.query(Project).filter(Project.id == project_id).first()
            if not project:
                return {"success": False, "error": "项目不存在"}
            if owner_id and project.owner_id != owner_id:
                return {"success": False, "error": "无权限操作"}
            if project.status != "archived":
                return {"success": False, "error": "项目未处于归档状态"}

            project.status = "active"
            project.updated_at = datetime.now()
            db.commit()
            return {"success": True, "message": "项目已取消归档"}
        except Exception as e:
            db.rollback()
            return {"success": False, "error": str(e)}
        finally:
            db.close()

    # ============================================================
    # 模板管理
    # ============================================================

    def list_templates(self, category: str = "") -> Dict[str, Any]:
        """获取模板列表

        Args:
            category: 分类过滤（可选）

        Returns:
            模板列表
        """
        templates = self.BUILTIN_TEMPLATES
        if category:
            templates = [t for t in templates if t["category"] == category]
        return {
            "success": True,
            "templates": [
                {k: v for k, v in t.items() if k != "files"}
                for t in templates
            ],
            "total": len(templates),
        }

    def get_template(self, template_id: str) -> Optional[Dict[str, Any]]:
        """获取模板详情"""
        for t in self.BUILTIN_TEMPLATES:
            if t["id"] == template_id:
                return t
        return None

    def create_from_template(
        self,
        template_id: str,
        name: str,
        owner_id: str = "default",
        description: str = "",
    ) -> Dict[str, Any]:
        """从模板创建项目

        Args:
            template_id: 模板ID
            name: 项目名称
            owner_id: 所有者ID
            description: 项目描述

        Returns:
            创建的项目信息
        """
        template = self.get_template(template_id)
        if not template:
            return {"success": False, "error": f"模板 '{template_id}' 不存在"}

        return self.create_project(
            name=name,
            project_type=template.get("project_type", "web_app"),
            template_id=template_id,
            owner_id=owner_id,
            description=description or template.get("description", ""),
            language=template.get("language", ""),
            framework=template.get("framework", ""),
            settings={"template_source": template_id},
        )

    def _apply_template(self, project_id: int, template_id: str) -> bool:
        """应用模板文件到项目目录

        Args:
            project_id: 项目ID
            template_id: 模板ID

        Returns:
            是否成功
        """
        template = self.get_template(template_id)
        if not template:
            return False

        project_dir = self._get_project_dir(project_id)
        files = template.get("files", {})

        for file_path, content in files.items():
            full_path = project_dir / file_path
            full_path.parent.mkdir(parents=True, exist_ok=True)
            try:
                full_path.write_text(content, encoding="utf-8")
            except Exception:
                pass

        return True

    # ============================================================
    # 项目文件管理
    # ============================================================

    def _get_project_dir(self, project_id: int) -> Path:
        """获取项目目录路径"""
        return self._projects_dir / str(project_id)

    def _resolve_project_path(
        self, project_id: int, file_path: str = ""
    ) -> Tuple[Optional[Path], Optional[str]]:
        """解析项目内文件路径，确保安全性

        Args:
            project_id: 项目ID
            file_path: 相对项目根的路径

        Returns:
            (绝对路径, 错误信息)
        """
        project_dir = self._get_project_dir(project_id)
        if not project_dir.exists():
            return None, "项目目录不存在"

        # 规范化路径，防止路径遍历攻击
        try:
            target = (project_dir / file_path).resolve()
            project_dir_resolved = project_dir.resolve()
            if not str(target).startswith(str(project_dir_resolved)):
                return None, "路径越界，访问被拒绝"
        except Exception as e:
            return None, f"路径解析失败: {str(e)}"

        return target, None

    def list_files(
        self,
        project_id: int,
        path: str = "",
        show_hidden: bool = False,
    ) -> Dict[str, Any]:
        """列出项目文件

        Args:
            project_id: 项目ID
            path: 目录路径
            show_hidden: 是否显示隐藏文件

        Returns:
            文件列表
        """
        target, error = self._resolve_project_path(project_id, path)
        if error:
            return {"success": False, "error": error}

        if not target.exists():
            return {"success": False, "error": "路径不存在"}
        if not target.is_dir():
            return {"success": False, "error": "路径不是目录"}

        try:
            items = []
            for entry in sorted(target.iterdir(), key=lambda x: (not x.is_dir(), x.name.lower())):
                if not show_hidden and entry.name.startswith("."):
                    continue
                stat = entry.stat()
                items.append({
                    "name": entry.name,
                    "path": str(entry.relative_to(self._get_project_dir(project_id))),
                    "is_dir": entry.is_dir(),
                    "size": stat.st_size if entry.is_file() else 0,
                    "modified": datetime.fromtimestamp(stat.st_mtime).isoformat(),
                })

            return {
                "success": True,
                "path": path,
                "items": items,
                "total": len(items),
            }
        except Exception as e:
            return {"success": False, "error": str(e)}

    def get_file(self, project_id: int, path: str) -> Dict[str, Any]:
        """获取文件内容

        Args:
            project_id: 项目ID
            path: 文件路径

        Returns:
            文件内容
        """
        target, error = self._resolve_project_path(project_id, path)
        if error:
            return {"success": False, "error": error}

        if not target.exists():
            return {"success": False, "error": "文件不存在"}
        if not target.is_file():
            return {"success": False, "error": "路径不是文件"}

        try:
            # 检查文件大小（限制 10MB）
            file_size = target.stat().st_size
            if file_size > 10 * 1024 * 1024:
                return {"success": False, "error": "文件过大，无法直接读取"}

            content = target.read_text(encoding="utf-8")
            return {
                "success": True,
                "path": path,
                "content": content,
                "size": file_size,
                "encoding": "utf-8",
            }
        except UnicodeDecodeError:
            # 二进制文件
            try:
                content = target.read_bytes()
                return {
                    "success": True,
                    "path": path,
                    "content": content.hex()[:100],  # 只返回前100字节的十六进制
                    "size": target.stat().st_size,
                    "encoding": "binary",
                    "is_binary": True,
                }
            except Exception as e:
                return {"success": False, "error": str(e)}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def save_file(
        self, project_id: int, path: str, content: str, encoding: str = "utf-8"
    ) -> Dict[str, Any]:
        """保存文件内容

        Args:
            project_id: 项目ID
            path: 文件路径
            content: 文件内容
            encoding: 编码

        Returns:
            保存结果
        """
        target, error = self._resolve_project_path(project_id, path)
        if error:
            return {"success": False, "error": error}

        if not target.exists():
            return {"success": False, "error": "文件不存在，请使用创建接口"}

        if target.is_dir():
            return {"success": False, "error": "路径是目录，不能保存"}

        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content, encoding=encoding)
            return {
                "success": True,
                "path": path,
                "size": len(content.encode(encoding)),
                "message": "文件已保存",
            }
        except Exception as e:
            return {"success": False, "error": str(e)}

    def create_file(
        self,
        project_id: int,
        path: str,
        content: str = "",
        is_directory: bool = False,
    ) -> Dict[str, Any]:
        """创建文件或目录

        Args:
            project_id: 项目ID
            path: 路径
            content: 文件内容（仅文件）
            is_directory: 是否为目录

        Returns:
            创建结果
        """
        target, error = self._resolve_project_path(project_id, path)
        if error:
            return {"success": False, "error": error}

        if target.exists():
            return {"success": False, "error": "路径已存在"}

        try:
            if is_directory:
                target.mkdir(parents=True, exist_ok=True)
                return {
                    "success": True,
                    "path": path,
                    "is_dir": True,
                    "message": "目录已创建",
                }
            else:
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(content, encoding="utf-8")
                return {
                    "success": True,
                    "path": path,
                    "is_dir": False,
                    "size": len(content.encode("utf-8")),
                    "message": "文件已创建",
                }
        except Exception as e:
            return {"success": False, "error": str(e)}

    def delete_file(self, project_id: int, path: str) -> Dict[str, Any]:
        """删除文件或目录

        Args:
            project_id: 项目ID
            path: 路径

        Returns:
            删除结果
        """
        if not path:
            return {"success": False, "error": "不能删除项目根目录"}

        target, error = self._resolve_project_path(project_id, path)
        if error:
            return {"success": False, "error": error}

        if not target.exists():
            return {"success": False, "error": "路径不存在"}

        try:
            if target.is_dir():
                shutil.rmtree(target)
            else:
                target.unlink()
            return {"success": True, "path": path, "message": "已删除"}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def rename_file(
        self, project_id: int, old_path: str, new_path: str
    ) -> Dict[str, Any]:
        """重命名文件或目录

        Args:
            project_id: 项目ID
            old_path: 原路径
            new_path: 新路径

        Returns:
            重命名结果
        """
        if not old_path or not new_path:
            return {"success": False, "error": "路径不能为空"}

        src, error = self._resolve_project_path(project_id, old_path)
        if error:
            return {"success": False, "error": f"原路径错误: {error}"}

        dst, error = self._resolve_project_path(project_id, new_path)
        if error:
            return {"success": False, "error": f"新路径错误: {error}"}

        if not src.exists():
            return {"success": False, "error": "原路径不存在"}
        if dst.exists():
            return {"success": False, "error": "新路径已存在"}

        try:
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(src), str(dst))
            return {
                "success": True,
                "old_path": old_path,
                "new_path": new_path,
                "message": "已重命名",
            }
        except Exception as e:
            return {"success": False, "error": str(e)}

    def create_directory(self, project_id: int, path: str) -> Dict[str, Any]:
        """创建目录

        Args:
            project_id: 项目ID
            path: 目录路径

        Returns:
            创建结果
        """
        return self.create_file(project_id, path, is_directory=True)

    # ============================================================
    # 搜索功能
    # ============================================================

    def search_files(
        self,
        project_id: int,
        query: str,
        path: str = "",
        case_sensitive: bool = False,
        file_pattern: str = "",
        max_results: int = 100,
    ) -> Dict[str, Any]:
        """在项目中搜索文件内容

        Args:
            project_id: 项目ID
            query: 搜索关键词
            path: 搜索起始路径
            case_sensitive: 是否区分大小写
            file_pattern: 文件过滤模式（如 *.py）
            max_results: 最大结果数

        Returns:
            搜索结果
        """
        target, error = self._resolve_project_path(project_id, path)
        if error:
            return {"success": False, "error": error}

        if not target.exists():
            return {"success": False, "error": "路径不存在"}

        try:
            results = []
            import fnmatch

            search_root = target if target.is_dir() else target.parent

            for root, dirs, files in os.walk(search_root):
                # 跳过隐藏目录和常见忽略目录
                dirs[:] = [d for d in dirs if not d.startswith(".") and d not in ("node_modules", "__pycache__", ".venv", "venv")]

                for filename in files:
                    if filename.startswith("."):
                        continue
                    if file_pattern and not fnmatch.fnmatch(filename, file_pattern):
                        continue

                    file_path = os.path.join(root, filename)
                    rel_path = os.path.relpath(file_path, self._get_project_dir(project_id))

                    try:
                        with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
                            for line_num, line in enumerate(f, 1):
                                line_for_check = line if case_sensitive else line.lower()
                                query_for_check = query if case_sensitive else query.lower()

                                if query_for_check in line_for_check:
                                    results.append({
                                        "file": rel_path,
                                        "line": line_num,
                                        "content": line.rstrip(),
                                        "match_start": line_for_check.find(query_for_check),
                                        "match_end": line_for_check.find(query_for_check) + len(query),
                                    })

                                    if len(results) >= max_results:
                                        return {
                                            "success": True,
                                            "query": query,
                                            "results": results,
                                            "total": len(results),
                                            "truncated": True,
                                        }
                    except (IOError, OSError):
                        continue

            return {
                "success": True,
                "query": query,
                "results": results,
                "total": len(results),
                "truncated": False,
            }
        except Exception as e:
            return {"success": False, "error": str(e)}

    def search_in_file(
        self,
        project_id: int,
        file_path: str,
        query: str,
        case_sensitive: bool = False,
    ) -> Dict[str, Any]:
        """在单个文件中搜索

        Args:
            project_id: 项目ID
            file_path: 文件路径
            query: 搜索关键词
            case_sensitive: 是否区分大小写

        Returns:
            搜索结果
        """
        target, error = self._resolve_project_path(project_id, file_path)
        if error:
            return {"success": False, "error": error}

        if not target.exists() or not target.is_file():
            return {"success": False, "error": "文件不存在"}

        try:
            results = []
            content = target.read_text(encoding="utf-8", errors="ignore")
            lines = content.split("\n")

            query_check = query if case_sensitive else query.lower()

            for line_num, line in enumerate(lines, 1):
                line_check = line if case_sensitive else line.lower()
                if query_check in line_check:
                    start = line_check.find(query_check)
                    results.append({
                        "line": line_num,
                        "content": line,
                        "match_start": start,
                        "match_end": start + len(query),
                    })

            return {
                "success": True,
                "file": file_path,
                "query": query,
                "matches": results,
                "total": len(results),
            }
        except Exception as e:
            return {"success": False, "error": str(e)}

    def replace_in_files(
        self,
        project_id: int,
        query: str,
        replacement: str,
        path: str = "",
        case_sensitive: bool = False,
        file_pattern: str = "",
    ) -> Dict[str, Any]:
        """在项目中替换文本

        Args:
            project_id: 项目ID
            query: 搜索关键词
            replacement: 替换文本
            path: 搜索起始路径
            case_sensitive: 是否区分大小写
            file_pattern: 文件过滤模式

        Returns:
            替换结果
        """
        target, error = self._resolve_project_path(project_id, path)
        if error:
            return {"success": False, "error": error}

        if not target.exists():
            return {"success": False, "error": "路径不存在"}

        try:
            import fnmatch
            replaced_files = []
            total_replacements = 0

            search_root = target if target.is_dir() else target.parent

            for root, dirs, files in os.walk(search_root):
                dirs[:] = [d for d in dirs if not d.startswith(".") and d not in ("node_modules", "__pycache__", ".venv", "venv")]

                for filename in files:
                    if filename.startswith("."):
                        continue
                    if file_pattern and not fnmatch.fnmatch(filename, file_pattern):
                        continue

                    file_path = os.path.join(root, filename)
                    rel_path = os.path.relpath(file_path, self._get_project_dir(project_id))

                    try:
                        content = ""
                        with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
                            content = f.read()

                        original_content = content
                        if case_sensitive:
                            new_content = content.replace(query, replacement)
                        else:
                            # 不区分大小写的替换
                            import re
                            pattern = re.compile(re.escape(query), re.IGNORECASE)
                            new_content = pattern.sub(replacement, content)

                        if new_content != original_content:
                            count = content.count(query) if case_sensitive else len(
                                re.findall(re.escape(query), content, re.IGNORECASE)
                            )
                            with open(file_path, "w", encoding="utf-8") as f:
                                f.write(new_content)
                            replaced_files.append({
                                "file": rel_path,
                                "replacements": count,
                            })
                            total_replacements += count
                    except (IOError, OSError):
                        continue

            return {
                "success": True,
                "query": query,
                "replacement": replacement,
                "files_modified": replaced_files,
                "total_replacements": total_replacements,
                "file_count": len(replaced_files),
            }
        except Exception as e:
            return {"success": False, "error": str(e)}

    def get_diff(
        self, project_id: int, path_a: str, path_b: str = ""
    ) -> Dict[str, Any]:
        """获取文件差异对比

        Args:
            project_id: 项目ID
            path_a: 文件A路径
            path_b: 文件B路径（为空则与当前内容对比，预留接口）

        Returns:
            差异结果
        """
        import difflib

        content_a_result = self.get_file(project_id, path_a)
        if not content_a_result.get("success"):
            return {"success": False, "error": f"文件A读取失败: {content_a_result.get('error')}"}

        content_a = content_a_result.get("content", "")

        if path_b:
            content_b_result = self.get_file(project_id, path_b)
            if not content_b_result.get("success"):
                return {"success": False, "error": f"文件B读取失败: {content_b_result.get('error')}"}
            content_b = content_b_result.get("content", "")
        else:
            # 没有第二个文件，返回空 diff
            content_b = content_a

        try:
            lines_a = content_a.splitlines(keepends=True)
            lines_b = content_b.splitlines(keepends=True)

            diff = list(difflib.unified_diff(
                lines_a,
                lines_b,
                fromfile=path_a,
                tofile=path_b or "current",
            ))

            return {
                "success": True,
                "path_a": path_a,
                "path_b": path_b,
                "diff": "".join(diff),
                "additions": sum(1 for line in diff if line.startswith("+") and not line.startswith("+++")),
                "deletions": sum(1 for line in diff if line.startswith("-") and not line.startswith("---")),
            }
        except Exception as e:
            return {"success": False, "error": str(e)}


# 全局单例
_project_service: Optional[ProjectService] = None


def get_project_service() -> ProjectService:
    """获取项目服务单例"""
    global _project_service
    if _project_service is None:
        _project_service = ProjectService()
    return _project_service
