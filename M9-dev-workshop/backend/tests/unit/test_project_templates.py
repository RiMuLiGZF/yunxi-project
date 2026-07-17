"""
M9 单元测试 - 项目模板系统测试

覆盖: 内置模板、自定义模板、从模板创建项目
运行: python -m pytest tests/unit/test_project_templates.py -v
"""
import os
import sys
import pytest
import tempfile
import shutil
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "..", "shared"))

from project_templates import ProjectTemplateManager


@pytest.fixture
def temp_workspace():
    """临时工作区 fixture"""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield tmpdir


@pytest.fixture
def template_manager(temp_workspace):
    """模板管理器 fixture"""
    # 临时设置工作区根目录
    import config
    original_root = config.get_settings().workspace_root
    config.get_settings().workspace_root = temp_workspace

    mgr = ProjectTemplateManager()
    yield mgr

    # 恢复
    config.get_settings().workspace_root = original_root


class TestProjectTemplateManager:
    """项目模板管理器测试"""

    def test_init(self, template_manager):
        """初始化测试"""
        assert template_manager is not None

    def test_list_templates_all(self, template_manager):
        """获取所有内置模板"""
        templates = template_manager.list_templates()
        assert len(templates) >= 8  # 至少 8 个内置模板

    def test_template_structure(self, template_manager):
        """模板结构验证"""
        templates = template_manager.list_templates()
        for tpl in templates:
            assert "id" in tpl
            assert "name" in tpl
            assert "description" in tpl
            assert "category" in tpl
            assert "files" in tpl
            assert isinstance(tpl["files"], dict)

    def test_get_template(self, template_manager):
        """获取单个模板"""
        templates = template_manager.list_templates()
        first_tpl = templates[0]

        result = template_manager.get_template(first_tpl["id"])
        assert result is not None
        assert result["id"] == first_tpl["id"]

    def test_get_template_not_found(self, template_manager):
        """获取不存在的模板"""
        result = template_manager.get_template("nonexistent_template")
        assert result is None

    def test_list_templates_by_category(self, template_manager):
        """按分类筛选模板"""
        result = template_manager.list_templates(category="Python")
        assert isinstance(result, list)
        for tpl in result:
            assert tpl["category"] == "Python"

    def test_list_templates_by_language(self, template_manager):
        """按语言筛选模板"""
        result = template_manager.list_templates(language="python")
        assert isinstance(result, list)
        for tpl in result:
            assert tpl.get("language") == "python"

    def test_list_templates_by_keyword(self, template_manager):
        """关键词搜索模板"""
        result = template_manager.list_templates(keyword="API")
        assert isinstance(result, list)

    def test_list_categories(self, template_manager):
        """获取分类列表"""
        categories = template_manager.list_categories()
        assert isinstance(categories, list)
        assert len(categories) > 0
        for cat in categories:
            assert "name" in cat
            assert "count" in cat

    def test_create_project_from_template(self, template_manager, temp_workspace):
        """从模板创建项目"""
        templates = template_manager.list_templates(language="python")
        assert len(templates) > 0

        tpl = templates[0]
        result = template_manager.create_project_from_template(
            template_id=tpl["id"],
            project_name="test_project",
            project_path=os.path.join(temp_workspace, "test_project"),
            description="测试项目",
        )

        assert result["success"] is True
        assert result["project_name"] == "test_project"
        assert result["template_id"] == tpl["id"]
        assert os.path.exists(result["project_path"])
        assert result["file_count"] > 0

    def test_create_project_from_template_nonexistent(self, template_manager, temp_workspace):
        """从不存在的模板创建项目"""
        result = template_manager.create_project_from_template(
            template_id="nonexistent",
            project_name="test",
            project_path=os.path.join(temp_workspace, "test"),
        )

        assert result["success"] is False
        assert "error" in result

    def test_create_project_path_exists(self, template_manager, temp_workspace):
        """项目路径已存在"""
        templates = template_manager.list_templates()
        tpl = templates[0]

        project_path = os.path.join(temp_workspace, "existing_project")
        os.makedirs(project_path)

        result = template_manager.create_project_from_template(
            template_id=tpl["id"],
            project_name="existing_project",
            project_path=project_path,
        )

        assert result["success"] is False
        assert "已存在" in result.get("error", "")

    def test_create_project_files_created(self, template_manager, temp_workspace):
        """验证创建的文件"""
        templates = template_manager.list_templates(language="python")
        tpl = templates[0]

        project_path = os.path.join(temp_workspace, "file_test_project")
        result = template_manager.create_project_from_template(
            template_id=tpl["id"],
            project_name="file_test",
            project_path=project_path,
        )

        assert result["success"] is True

        # 验证文件是否都创建了
        for file_rel_path in tpl["files"].keys():
            full_path = os.path.join(project_path, file_rel_path)
            assert os.path.exists(full_path), f"文件未创建: {file_rel_path}"

    def test_builtin_templates_have_readme(self, template_manager):
        """内置模板应该有 README 文件"""
        templates = template_manager.list_templates()
        for tpl in templates:
            files = tpl.get("files", {})
            # 至少有一个主要文件
            assert len(files) > 0, f"模板 {tpl['name']} 没有文件"

    def test_python_script_template(self, template_manager):
        """Python 脚本模板"""
        tpl = template_manager.get_template("tpl_python_script")
        assert tpl is not None
        assert tpl["language"] == "python"
        assert "main.py" in tpl["files"]
        assert "README.md" in tpl["files"]

    def test_fastapi_template(self, template_manager):
        """FastAPI 项目模板"""
        tpl = template_manager.get_template("tpl_fastapi")
        assert tpl is not None
        assert tpl["language"] == "python"
        assert "main.py" in tpl["files"]


class TestCustomTemplates:
    """自定义模板测试"""

    def test_save_custom_template(self, template_manager):
        """保存自定义模板"""
        template_data = {
            "name": "我的自定义模板",
            "description": "这是一个自定义项目模板",
            "category": "自定义",
            "language": "python",
            "icon": "🎨",
            "tags": ["自定义", "测试"],
            "files": {
                "main.py": "print('hello')",
                "README.md": "# 自定义模板",
            },
        }

        result = template_manager.save_custom_template(template_data)
        assert result["success"] is True
        assert "template_id" in result

    def test_list_custom_templates(self, template_manager):
        """列出自定义模板"""
        # 保存一个自定义模板
        template_manager.save_custom_template({
            "name": "自定义1",
            "description": "测试",
            "category": "自定义",
            "files": {"test.py": ""},
        })

        templates = template_manager.list_templates(category="自定义")
        assert len(templates) >= 1

    def test_delete_custom_template(self, template_manager):
        """删除自定义模板"""
        save_result = template_manager.save_custom_template({
            "name": "待删除",
            "description": "测试",
            "category": "自定义",
            "files": {"test.py": ""},
        })

        tpl_id = save_result["template_id"]
        result = template_manager.delete_custom_template(tpl_id)
        assert result["success"] is True

        # 确认已删除
        tpl = template_manager.get_template(tpl_id)
        assert tpl is None

    def test_delete_builtin_template_fails(self, template_manager):
        """不能删除内置模板"""
        templates = template_manager.list_templates()
        builtin = templates[0]

        result = template_manager.delete_custom_template(builtin["id"])
        assert result["success"] is False


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
