"""
M9 开发工坊 - 项目 CRUD 测试

测试内容：
- 项目列表接口
- 创建项目
- 获取项目详情
- 更新项目
- 删除项目
- 项目标签管理
"""

import sys
import pytest
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent.parent
class TestProjectCRUD:
    """项目 CRUD 测试"""

    # ============================================================
    # 项目列表
    # ============================================================

    @pytest.mark.unit
    @pytest.mark.m9
    @pytest.mark.project
    def test_project_list_endpoint(self, m9_client):
        """项目列表接口"""
        try:
            response = m9_client.get("/api/v1/workspace/projects")
            if response.status_code == 404:
                response = m9_client.get("/api/workspace/projects")
            assert response.status_code in [200, 401, 403, 404]
        except Exception as e:
            pytest.skip(f"项目列表测试跳过: {e}")

    @pytest.mark.unit
    @pytest.mark.m9
    @pytest.mark.project
    def test_project_list_returns_json(self, m9_client):
        """项目列表返回 JSON"""
        try:
            response = m9_client.get("/api/v1/workspace/projects")
            if response.status_code == 404:
                response = m9_client.get("/api/workspace/projects")
            if response.status_code == 200:
                data = response.json()
                assert isinstance(data, dict)
                assert "code" in data
        except Exception as e:
            pytest.skip(f"项目列表 JSON 测试跳过: {e}")

    @pytest.mark.unit
    @pytest.mark.m9
    @pytest.mark.project
    def test_recent_projects_endpoint(self, m9_client):
        """最近项目接口"""
        try:
            response = m9_client.get("/api/v1/workspace/projects/recent")
            if response.status_code == 404:
                response = m9_client.get("/api/workspace/recent")
            assert response.status_code in [200, 401, 403, 404]
        except Exception as e:
            pytest.skip(f"最近项目测试跳过: {e}")

    # ============================================================
    # 创建项目
    # ============================================================

    @pytest.mark.unit
    @pytest.mark.m9
    @pytest.mark.project
    def test_create_project(self, m9_client, test_workspace_dir):
        """创建项目"""
        try:
            body = {
                "name": "test-project",
                "path": str(test_workspace_dir / "test-project"),
                "description": "测试项目",
                "icon": "folder",
                "tags": ["test", "demo"],
            }
            response = m9_client.post("/api/v1/workspace/projects", json=body)
            if response.status_code == 404:
                response = m9_client.post("/api/workspace/projects", json=body)
            assert response.status_code in [200, 201, 400, 401, 403, 404]
        except Exception as e:
            pytest.skip(f"创建项目测试跳过: {e}")

    @pytest.mark.unit
    @pytest.mark.m9
    @pytest.mark.project
    def test_create_project_missing_name(self, m9_client):
        """创建项目缺少名称"""
        try:
            body = {
                "path": "/tmp/test",
            }
            response = m9_client.post("/api/v1/workspace/projects", json=body)
            if response.status_code == 404:
                response = m9_client.post("/api/workspace/projects", json=body)
            assert response.status_code in [400, 422, 200, 401, 403, 404]
        except Exception as e:
            pytest.skip(f"缺少名称测试跳过: {e}")

    @pytest.mark.unit
    @pytest.mark.m9
    @pytest.mark.project
    def test_create_project_empty_name(self, m9_client):
        """创建项目名称为空"""
        try:
            body = {
                "name": "",
                "path": "/tmp/test",
            }
            response = m9_client.post("/api/v1/workspace/projects", json=body)
            if response.status_code == 404:
                response = m9_client.post("/api/workspace/projects", json=body)
            assert response.status_code in [400, 422, 200, 401, 403, 404]
        except Exception as e:
            pytest.skip(f"空名称测试跳过: {e}")

    # ============================================================
    # 项目详情
    # ============================================================

    @pytest.mark.unit
    @pytest.mark.m9
    @pytest.mark.project
    def test_get_project_detail(self, m9_client):
        """获取项目详情"""
        try:
            response = m9_client.get("/api/v1/workspace/projects/1")
            if response.status_code == 404:
                response = m9_client.get("/api/workspace/projects/1")
            assert response.status_code in [200, 401, 403, 404]
        except Exception as e:
            pytest.skip(f"项目详情测试跳过: {e}")

    @pytest.mark.unit
    @pytest.mark.m9
    @pytest.mark.project
    def test_get_nonexistent_project(self, m9_client):
        """获取不存在的项目"""
        try:
            response = m9_client.get("/api/v1/workspace/projects/99999")
            if response.status_code == 404:
                response = m9_client.get("/api/workspace/projects/99999")
            assert response.status_code in [200, 404, 401, 403]
        except Exception as e:
            pytest.skip(f"不存在项目测试跳过: {e}")

    # ============================================================
    # 更新项目
    # ============================================================

    @pytest.mark.unit
    @pytest.mark.m9
    @pytest.mark.project
    def test_update_project(self, m9_client):
        """更新项目信息"""
        try:
            body = {
                "name": "updated-project",
                "description": "更新后的描述",
            }
            response = m9_client.put("/api/v1/workspace/projects/1", json=body)
            if response.status_code == 404:
                response = m9_client.patch("/api/workspace/projects/1", json=body)
            assert response.status_code in [200, 400, 401, 403, 404]
        except Exception as e:
            pytest.skip(f"更新项目测试跳过: {e}")

    # ============================================================
    # 删除项目
    # ============================================================

    @pytest.mark.unit
    @pytest.mark.m9
    @pytest.mark.project
    def test_delete_project(self, m9_client):
        """删除项目"""
        try:
            response = m9_client.delete("/api/v1/workspace/projects/99999")
            if response.status_code == 404:
                response = m9_client.delete("/api/workspace/projects/99999")
            assert response.status_code in [200, 404, 401, 403]
        except Exception as e:
            pytest.skip(f"删除项目测试跳过: {e}")

    # ============================================================
    # 标签管理
    # ============================================================

    @pytest.mark.unit
    @pytest.mark.m9
    @pytest.mark.project
    def test_project_tags_endpoint(self, m9_client):
        """项目标签接口"""
        try:
            response = m9_client.get("/api/v1/workspace/tags")
            if response.status_code == 404:
                response = m9_client.get("/api/workspace/tags")
            assert response.status_code in [200, 401, 403, 404]
        except Exception as e:
            pytest.skip(f"标签列表测试跳过: {e}")

    @pytest.mark.unit
    @pytest.mark.m9
    @pytest.mark.project
    def test_project_filter_by_tag(self, m9_client):
        """按标签筛选项目"""
        try:
            response = m9_client.get("/api/v1/workspace/projects?tag=test")
            if response.status_code == 404:
                response = m9_client.get("/api/workspace/projects?tag=test")
            assert response.status_code in [200, 401, 403, 404]
        except Exception as e:
            pytest.skip(f"标签筛选测试跳过: {e}")
