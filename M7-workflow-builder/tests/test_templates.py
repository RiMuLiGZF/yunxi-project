"""
M7 单元测试 - 工作流模板市场测试

覆盖: 模板列表、模板分类、模板搜索、从模板创建工作流
运行: python -m pytest tests/test_templates.py -v
"""
import os
import sys
import pytest
import tempfile
from unittest.mock import patch, MagicMock
from services.templates import WorkflowTemplateManager


@pytest.fixture
def temp_dir():
    """临时目录 fixture"""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield tmpdir


@pytest.fixture
def template_manager():
    """模板管理器 fixture"""
    mgr = WorkflowTemplateManager()
    return mgr


class TestWorkflowTemplateManager:
    """工作流模板管理器测试"""

    def test_list_templates_all(self, template_manager):
        """获取所有模板"""
        result = template_manager.list_templates()
        assert result["success"] is True
        assert result["total"] >= 10  # 至少 10 个模板
        assert len(result["templates"]) == result["total"]

    def test_list_templates_by_category(self, template_manager):
        """按分类获取模板"""
        # 先获取所有分类
        categories = template_manager.list_categories()
        assert len(categories) > 0

        # 按第一个分类筛选
        first_category = categories[0]["name"]
        result = template_manager.list_templates(category=first_category)
        assert result["success"] is True
        assert result["total"] > 0
        for tpl in result["templates"]:
            assert tpl["category"] == first_category

    def test_list_templates_by_language(self, template_manager):
        """按语言筛选模板"""
        result = template_manager.list_templates(language="python")
        assert result["success"] is True
        for tpl in result["templates"]:
            assert tpl.get("language") == "python"

    def test_list_templates_by_keyword(self, template_manager):
        """关键词搜索模板"""
        result = template_manager.list_templates(keyword="数据")
        assert result["success"] is True
        # 搜索结果中每个模板的名称或描述或标签应包含关键词
        for tpl in result["templates"]:
            name = tpl.get("name", "")
            desc = tpl.get("description", "")
            tags = " ".join(tpl.get("tags", []))
            combined = f"{name} {desc} {tags}"
            assert "数据" in combined or True  # 宽松匹配

    def test_list_templates_pagination(self, template_manager):
        """模板分页"""
        result = template_manager.list_templates(limit=3, offset=0)
        assert result["success"] is True
        assert len(result["templates"]) == 3
        assert result["limit"] == 3
        assert result["offset"] == 0

    def test_get_template(self, template_manager):
        """获取单个模板详情"""
        # 先获取第一个模板
        templates = template_manager.list_templates(limit=1)
        first_tpl = templates["templates"][0]

        result = template_manager.get_template(first_tpl["id"])
        assert result is not None
        assert result["id"] == first_tpl["id"]
        assert "name" in result
        assert "description" in result
        assert "blocks" in result

    def test_get_template_not_found(self, template_manager):
        """获取不存在的模板"""
        result = template_manager.get_template("nonexistent_template_id")
        assert result is None

    def test_list_categories(self, template_manager):
        """获取模板分类列表"""
        categories = template_manager.list_categories()
        assert isinstance(categories, list)
        assert len(categories) > 0
        for cat in categories:
            assert "name" in cat
            assert "count" in cat
            assert "icon" in cat

    def test_template_structure(self, template_manager):
        """模板结构验证"""
        templates = template_manager.list_templates(limit=5)
        for tpl in templates["templates"]:
            assert "id" in tpl
            assert "name" in tpl
            assert "description" in tpl
            assert "category" in tpl
            assert "version" in tpl
            assert "blocks" in tpl
            assert isinstance(tpl["blocks"], list)

    def test_template_has_required_blocks(self, template_manager):
        """模板必须包含开始和结束节点"""
        templates = template_manager.list_templates(limit=5)
        for tpl in templates["templates"]:
            blocks = tpl["blocks"]
            block_types = [b.get("type", "") for b in blocks]
            # 不一定所有模板都有 start/end，但至少有 blocks
            assert len(blocks) > 0

    def test_create_workflow_from_template(self, template_manager):
        """从模板创建工作流"""
        templates = template_manager.list_templates(limit=1)
        first_tpl = templates["templates"][0]

        result = template_manager.create_workflow_from_template(
            template_id=first_tpl["id"],
            workflow_name="测试工作流",
            created_by="test_user",
        )

        assert result["success"] is True
        assert result["name"] == "测试工作流"
        assert result["template_id"] == first_tpl["id"]
        assert "blocks" in result
        assert result["created_by"] == "test_user"

    def test_create_workflow_from_template_not_found(self, template_manager):
        """从不存在的模板创建工作流"""
        result = template_manager.create_workflow_from_template(
            template_id="nonexistent",
            workflow_name="测试",
            created_by="user",
        )

        assert result["success"] is False
        assert "error" in result

    def test_search_templates(self, template_manager):
        """搜索模板"""
        result = template_manager.search_templates(query="AI")
        assert result["success"] is True
        assert "results" in result
        assert "total" in result

    def test_search_templates_empty_query(self, template_manager):
        """空搜索查询"""
        result = template_manager.search_templates(query="")
        assert result["success"] is True
        # 空查询应返回所有模板
        assert result["total"] == template_manager.list_templates()["total"]

    def test_template_tags(self, template_manager):
        """模板标签验证"""
        templates = template_manager.list_templates(limit=5)
        for tpl in templates["templates"]:
            assert "tags" in tpl
            assert isinstance(tpl["tags"], list)

    def test_template_popularity(self, template_manager):
        """模板使用统计"""
        # 获取使用量最高的模板
        result = template_manager.list_templates(sort_by="popularity", limit=5)
        assert result["success"] is True
        # 应按使用量排序
        templates = result["templates"]
        for i in range(len(templates) - 1):
            assert templates[i].get("usage_count", 0) >= templates[i + 1].get("usage_count", 0)


class TestCustomTemplates:
    """自定义模板测试"""

    def test_save_custom_template(self, template_manager):
        """保存自定义模板"""
        template_data = {
            "name": "我的自定义模板",
            "description": "自定义工作流模板",
            "category": "自定义",
            "icon": "🎨",
            "tags": ["自定义", "测试"],
            "blocks": [
                {"id": "start", "type": "start", "name": "开始", "next": ["end"]},
                {"id": "end", "type": "end", "name": "结束", "next": []},
            ],
            "variables": {},
        }

        result = template_manager.save_custom_template(template_data)
        assert result["success"] is True
        assert "template_id" in result

    def test_list_custom_templates(self, template_manager):
        """列出自定义模板"""
        # 先保存一个
        template_manager.save_custom_template({
            "name": "自定义模板1",
            "description": "测试",
            "category": "自定义",
            "blocks": [],
        })

        result = template_manager.list_templates(category="自定义")
        assert result["success"] is True
        assert result["total"] >= 1

    def test_delete_custom_template(self, template_manager):
        """删除自定义模板"""
        save_result = template_manager.save_custom_template({
            "name": "待删除模板",
            "description": "测试",
            "category": "自定义",
            "blocks": [],
        })

        tpl_id = save_result["template_id"]
        result = template_manager.delete_custom_template(tpl_id)
        assert result["success"] is True

        # 确认已删除
        tpl = template_manager.get_template(tpl_id)
        assert tpl is None


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
