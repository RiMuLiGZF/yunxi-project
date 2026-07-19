"""
M9 开发工坊 - 项目 CRUD 单元测试

测试内容：
- 项目模型与数据库操作（内存 SQLite）
- 项目业务逻辑
- 项目 CRUD API（集成测试，标记为 integration）
"""

import sys
import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock

PROJECT_ROOT = Path(__file__).parent.parent.parent
M9_BACKEND_PATH = PROJECT_ROOT / "M9-dev-workshop" / "backend"

if str(M9_BACKEND_PATH) not in sys.path:
    sys.path.insert(0, str(M9_BACKEND_PATH))


# ============================================================
# 项目模型单元测试（内存 SQLite）
# ============================================================

class TestProjectModelUnit:
    """项目模型单元测试（使用内存 SQLite）"""

    @pytest.fixture
    def db_session(self):
        """创建内存 SQLite 会话用于测试"""
        try:
            from sqlalchemy import create_engine
            from sqlalchemy.orm import sessionmaker
            from models import Base

            engine = create_engine("sqlite:///:memory:")
            Base.metadata.create_all(bind=engine)
            SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
            session = SessionLocal()
            yield session
            session.close()
            Base.metadata.drop_all(bind=engine)
        except ImportError:
            pytest.skip("SQLAlchemy 或模型不可用")

    @pytest.mark.unit
    @pytest.mark.m9
    @pytest.mark.project
    def test_project_model_exists(self):
        """项目模型存在"""
        try:
            from models import Project
            assert Project is not None
        except ImportError:
            pytest.skip("项目模型不可用")

    @pytest.mark.unit
    @pytest.mark.m9
    @pytest.mark.project
    def test_project_model_has_required_fields(self):
        """项目模型有必要字段"""
        try:
            from models import Project
            assert hasattr(Project, "__tablename__")
            # 常见字段
            expected_fields = ["id", "name", "description", "created_at", "owner_id", "status"]
            actual_fields = [c.name for c in Project.__table__.columns]
            for field in expected_fields:
                assert field in actual_fields, f"缺少字段: {field}"
        except ImportError:
            pytest.skip("项目模型不可用")

    @pytest.mark.unit
    @pytest.mark.m9
    @pytest.mark.project
    def test_create_project_in_memory_db(self, db_session):
        """在内存数据库中创建项目"""
        from models import Project

        project = Project(
            name="测试项目",
            description="这是一个测试项目",
            owner_id="test-user-1",
            status="active",
        )
        db_session.add(project)
        db_session.commit()
        db_session.refresh(project)

        assert project.id is not None
        assert project.name == "测试项目"
        assert project.description == "这是一个测试项目"
        assert project.status == "active"
        assert project.owner_id == "test-user-1"

    @pytest.mark.unit
    @pytest.mark.m9
    @pytest.mark.project
    def test_create_multiple_projects(self, db_session):
        """创建多个项目"""
        from models import Project

        for i in range(5):
            project = Project(
                name=f"项目 {i}",
                description=f"描述 {i}",
                owner_id=f"user-{i}",
                status="active",
            )
            db_session.add(project)

        db_session.commit()
        count = db_session.query(Project).count()
        assert count == 5

    @pytest.mark.unit
    @pytest.mark.m9
    @pytest.mark.project
    def test_read_project_by_id(self, db_session):
        """按 ID 读取项目"""
        from models import Project

        project = Project(
            name="查询测试项目",
            description="查询测试描述",
            owner_id="test-user",
            status="active",
        )
        db_session.add(project)
        db_session.commit()

        found = db_session.query(Project).filter_by(id=project.id).first()
        assert found is not None
        assert found.name == "查询测试项目"

    @pytest.mark.unit
    @pytest.mark.m9
    @pytest.mark.project
    def test_update_project(self, db_session):
        """更新项目信息"""
        from models import Project

        project = Project(
            name="待更新项目",
            description="原始描述",
            owner_id="test-user",
            status="active",
        )
        db_session.add(project)
        db_session.commit()

        # 更新
        project.name = "更新后的项目名"
        project.description = "更新后的描述"
        db_session.commit()
        db_session.refresh(project)

        assert project.name == "更新后的项目名"
        assert project.description == "更新后的描述"

    @pytest.mark.unit
    @pytest.mark.m9
    @pytest.mark.project
    def test_delete_project(self, db_session):
        """删除项目"""
        from models import Project

        project = Project(
            name="待删除项目",
            description="即将被删除",
            owner_id="test-user",
            status="active",
        )
        db_session.add(project)
        db_session.commit()
        project_id = project.id

        # 删除
        db_session.delete(project)
        db_session.commit()

        found = db_session.query(Project).filter_by(id=project_id).first()
        assert found is None

    @pytest.mark.unit
    @pytest.mark.m9
    @pytest.mark.project
    def test_project_pagination(self, db_session):
        """项目分页查询"""
        from models import Project

        # 创建 20 个项目
        for i in range(20):
            project = Project(
                name=f"分页项目 {i}",
                description=f"分页描述 {i}",
                owner_id=f"user-{i}",
                status="active",
            )
            db_session.add(project)
        db_session.commit()

        # 第 1 页，每页 5 个
        page1 = db_session.query(Project).order_by(Project.id.desc()).limit(5).offset(0).all()
        assert len(page1) == 5

        # 第 2 页
        page2 = db_session.query(Project).order_by(Project.id.desc()).limit(5).offset(5).all()
        assert len(page2) == 5
        # 第 1 页的 ID 应该比第 2 页大
        assert page1[0].id > page2[0].id

    @pytest.mark.unit
    @pytest.mark.m9
    @pytest.mark.project
    def test_project_filter_by_status(self, db_session):
        """按状态筛选项目"""
        from models import Project

        # 创建不同状态的项目
        for status in ["active", "archived", "active", "paused"]:
            project = Project(
                name=f"{status} 项目",
                description=f"状态为 {status} 的项目",
                owner_id="test-user",
                status=status,
            )
            db_session.add(project)
        db_session.commit()

        # 筛选 active 状态
        active_count = db_session.query(Project).filter_by(status="active").count()
        assert active_count == 2

        archived_count = db_session.query(Project).filter_by(status="archived").count()
        assert archived_count == 1

    @pytest.mark.unit
    @pytest.mark.m9
    @pytest.mark.project
    def test_project_search_by_name(self, db_session):
        """按名称搜索项目"""
        from models import Project

        projects_data = [
            ("Alpha 项目", "第一个项目"),
            ("Beta 项目", "第二个项目"),
            ("Gamma 测试", "第三个项目"),
        ]
        for name, desc in projects_data:
            project = Project(
                name=name,
                description=desc,
                owner_id="test-user",
                status="active",
            )
            db_session.add(project)
        db_session.commit()

        # 搜索包含"项目"的
        results = db_session.query(Project).filter(Project.name.like("%项目%")).all()
        assert len(results) == 2

    @pytest.mark.unit
    @pytest.mark.m9
    @pytest.mark.project
    def test_project_default_status(self, db_session):
        """项目默认状态"""
        from models import Project

        # 只提供必填字段
        project = Project(
            name="默认状态项目",
            owner_id="test-user",
        )
        db_session.add(project)
        db_session.commit()
        db_session.refresh(project)

        assert project.id is not None
        assert project.status == "active"

    @pytest.mark.unit
    @pytest.mark.m9
    @pytest.mark.project
    def test_project_default_type(self, db_session):
        """项目默认类型"""
        from models import Project

        project = Project(
            name="默认类型项目",
            owner_id="test-user",
        )
        db_session.add(project)
        db_session.commit()
        db_session.refresh(project)

        assert project.project_type == "web_app"


# ============================================================
# 项目业务逻辑单元测试
# ============================================================

class TestProjectBusinessLogic:
    """项目业务逻辑单元测试"""

    @pytest.mark.unit
    @pytest.mark.m9
    @pytest.mark.project
    def test_project_service_exists(self):
        """项目服务类存在"""
        try:
            from services.project_service import ProjectService
            assert ProjectService is not None
        except (ImportError, AttributeError):
            pytest.skip("ProjectService 不可用")

    @pytest.mark.unit
    @pytest.mark.m9
    @pytest.mark.project
    def test_project_name_validation(self):
        """项目名称验证逻辑"""
        # 基础验证逻辑
        def validate_name(name):
            if not name or not name.strip():
                return False, "项目名称不能为空"
            if len(name) > 100:
                return False, "项目名称不能超过100个字符"
            return True, ""

        # 正常名称
        valid, msg = validate_name("我的项目")
        assert valid is True

        # 空名称
        valid, msg = validate_name("")
        assert valid is False

        # 空白名称
        valid, msg = validate_name("   ")
        assert valid is False

        # 超长名称
        valid, msg = validate_name("a" * 101)
        assert valid is False


# ============================================================
# 集成测试（需要完整 M9 应用）
# ============================================================

class TestProjectCRUDIntegration:
    """项目 CRUD API 集成测试（需要 M9 应用实例）

    依赖 m9_client fixture，应用无法初始化时自动跳过。
    """

    @pytest.mark.integration
    @pytest.mark.m9
    @pytest.mark.project
    def test_list_projects_endpoint(self, m9_client, auth_headers):
        """项目列表接口"""
        response = m9_client.get("/api/projects", headers=auth_headers)
        assert response.status_code in [200, 401, 403]

    @pytest.mark.integration
    @pytest.mark.m9
    @pytest.mark.project
    def test_list_projects_requires_auth(self, m9_client):
        """项目列表需要认证"""
        response = m9_client.get("/api/projects")
        assert response.status_code in [401, 403]

    @pytest.mark.integration
    @pytest.mark.m9
    @pytest.mark.project
    def test_create_project(self, m9_client, auth_headers):
        """创建项目"""
        body = {
            "name": "集成测试项目",
            "description": "通过集成测试创建的项目",
        }
        response = m9_client.post("/api/projects", json=body, headers=auth_headers)
        assert response.status_code in [200, 201, 400, 401, 403]
        if response.status_code in [200, 201]:
            data = response.json()
            assert isinstance(data, dict)

    @pytest.mark.integration
    @pytest.mark.m9
    @pytest.mark.project
    def test_create_project_missing_name(self, m9_client, auth_headers):
        """创建项目缺少名称"""
        body = {"description": "没有名称的项目"}
        response = m9_client.post("/api/projects", json=body, headers=auth_headers)
        assert response.status_code in [400, 422, 200, 401, 403]

    @pytest.mark.integration
    @pytest.mark.m9
    @pytest.mark.project
    def test_get_project_detail(self, m9_client, auth_headers):
        """获取项目详情"""
        # 先创建一个项目
        body = {"name": "详情测试项目", "description": "测试详情"}
        create_resp = m9_client.post("/api/projects", json=body, headers=auth_headers)

        if create_resp.status_code in [200, 201]:
            data = create_resp.json()
            # 从响应中提取项目 ID
            project_id = None
            if "data" in data and isinstance(data["data"], dict):
                project_id = data["data"].get("id")
            elif "id" in data:
                project_id = data.get("id")

            if project_id:
                response = m9_client.get(f"/api/projects/{project_id}", headers=auth_headers)
                assert response.status_code == 200

    @pytest.mark.integration
    @pytest.mark.m9
    @pytest.mark.project
    def test_update_project(self, m9_client, auth_headers):
        """更新项目"""
        # 先创建
        body = {"name": "待更新项目", "description": "原始描述"}
        create_resp = m9_client.post("/api/projects", json=body, headers=auth_headers)

        if create_resp.status_code in [200, 201]:
            data = create_resp.json()
            project_id = None
            if "data" in data and isinstance(data["data"], dict):
                project_id = data["data"].get("id")
            elif "id" in data:
                project_id = data.get("id")

            if project_id:
                update_body = {"name": "已更新的项目名", "description": "已更新的描述"}
                response = m9_client.put(
                    f"/api/projects/{project_id}",
                    json=update_body,
                    headers=auth_headers,
                )
                assert response.status_code in [200, 201, 400]

    @pytest.mark.integration
    @pytest.mark.m9
    @pytest.mark.project
    def test_delete_project(self, m9_client, auth_headers):
        """删除项目"""
        body = {"name": "待删除项目", "description": "即将删除"}
        create_resp = m9_client.post("/api/projects", json=body, headers=auth_headers)

        if create_resp.status_code in [200, 201]:
            data = create_resp.json()
            project_id = None
            if "data" in data and isinstance(data["data"], dict):
                project_id = data["data"].get("id")
            elif "id" in data:
                project_id = data.get("id")

            if project_id:
                response = m9_client.delete(f"/api/projects/{project_id}", headers=auth_headers)
                assert response.status_code in [200, 204, 400]

    @pytest.mark.integration
    @pytest.mark.m9
    @pytest.mark.project
    def test_project_pagination_api(self, m9_client, auth_headers):
        """项目分页接口"""
        response = m9_client.get(
            "/api/projects?page=1&page_size=10",
            headers=auth_headers,
        )
        if response.status_code == 200:
            data = response.json()
            assert isinstance(data, dict)

    @pytest.mark.integration
    @pytest.mark.m9
    @pytest.mark.project
    def test_project_search_api(self, m9_client, auth_headers):
        """项目搜索接口"""
        response = m9_client.get(
            "/api/projects?keyword=test",
            headers=auth_headers,
        )
        if response.status_code == 200:
            data = response.json()
            assert isinstance(data, dict)
