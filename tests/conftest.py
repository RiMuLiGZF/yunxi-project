"""
云汐系统 - pytest 全局配置与 Fixtures

提供所有测试共享的 fixture 配置，包括：
- 测试环境配置加载
- 测试数据库（内存 SQLite）
- 各模块测试应用与客户端（M8/M9/M11）
- 测试用户与认证 Token
- 测试数据生成器
- 常用断言辅助工具
- Mock 外部依赖的工具
"""

import os
import sys
import json
import asyncio
import tempfile
from pathlib import Path
from datetime import datetime, timedelta
from typing import Dict, Any, Optional, Generator, AsyncGenerator, List

import pytest

# 将项目根目录加入 path
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

# 确保 shared 模块可以导入
sys.path.insert(0, str(PROJECT_ROOT / "shared"))


# ============================================================
# 配置加载
# ============================================================

def _load_env_test() -> Dict[str, str]:
    """加载 .env.test 配置文件"""
    env_file = PROJECT_ROOT / ".env.test"
    env_vars = {}
    if env_file.exists():
        with open(env_file, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, value = line.split("=", 1)
                key = key.strip()
                value = value.strip().strip('"').strip("'")
                env_vars[key] = value
                os.environ.setdefault(key, value)
    return env_vars


# 加载测试环境配置
_test_env = _load_env_test()

# 强制测试环境
os.environ["ENV"] = "testing"
os.environ["YUNXI_TEST_MODE"] = "1"


@pytest.fixture(scope="session")
def test_env() -> Dict[str, str]:
    """测试环境配置 fixture"""
    return _test_env


# ============================================================
# 事件循环配置（pytest-asyncio）
# ============================================================

@pytest.fixture(scope="session")
def event_loop() -> Generator:
    """会话级别的事件循环"""
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


# ============================================================
# 测试数据库 Fixtures
# ============================================================

@pytest.fixture(scope="function")
def test_db_path(tmp_path) -> str:
    """创建临时测试数据库路径（文件型 SQLite）"""
    db_path = tmp_path / "test.db"
    return str(db_path)


@pytest.fixture(scope="function")
def in_memory_db_url() -> str:
    """内存 SQLite 数据库 URL（速度最快，测试间完全隔离）"""
    return "sqlite:///:memory:"


@pytest.fixture(scope="function")
def test_data_dir(tmp_path) -> Path:
    """创建测试数据目录"""
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    return data_dir


@pytest.fixture(scope="function")
def test_workspace_dir(tmp_path) -> Path:
    """创建测试工作区目录"""
    workspace_dir = tmp_path / "workspace"
    workspace_dir.mkdir()
    # 创建一些测试项目
    (workspace_dir / "project-a").mkdir()
    (workspace_dir / "project-b").mkdir()
    (workspace_dir / "project-a" / "main.py").write_text("# test project a")
    return workspace_dir


# ============================================================
# 测试用户 Fixtures
# ============================================================

@pytest.fixture(scope="session")
def test_admin_user() -> Dict[str, Any]:
    """测试管理员用户信息"""
    return {
        "id": 1,
        "username": "admin",
        "password": "admin123456",
        "email": "admin@yunxi.local",
        "role": "admin",
        "is_active": True,
    }


@pytest.fixture(scope="session")
def test_normal_user() -> Dict[str, Any]:
    """测试普通用户信息"""
    return {
        "id": 2,
        "username": "testuser",
        "password": "testuser123",
        "email": "testuser@yunxi.local",
        "role": "user",
        "is_active": True,
    }


# ============================================================
# JWT 认证 Fixtures
# ============================================================

@pytest.fixture(scope="session")
def jwt_secret() -> str:
    """测试用 JWT 密钥（足够长度以通过安全检查）"""
    return "test-jwt-secret-key-for-unit-tests-only-1234567890"


@pytest.fixture(scope="session")
def jwt_handler(jwt_secret):
    """JWT 处理器 fixture"""
    try:
        from shared.core.auth.jwt import JWTHandler, JWTConfig
        config = JWTConfig(
            secret=jwt_secret,
            algorithm="HS256",
            access_token_expire_minutes=60,
            refresh_token_expire_days=7,
            require_secure_secret=False,
        )
        return JWTHandler(config)
    except ImportError:
        pytest.skip("JWT 模块不可用")


@pytest.fixture(scope="function")
def test_access_token(jwt_handler, test_admin_user) -> str:
    """生成测试用 Access Token"""
    return jwt_handler.create_access_token({
        "sub": str(test_admin_user["id"]),
        "username": test_admin_user["username"],
        "role": test_admin_user["role"],
    })


@pytest.fixture(scope="function")
def test_refresh_token(jwt_handler, test_admin_user) -> str:
    """生成测试用 Refresh Token"""
    return jwt_handler.create_refresh_token({
        "sub": str(test_admin_user["id"]),
        "username": test_admin_user["username"],
    })


# ============================================================
# API Key 认证 Fixtures
# ============================================================

@pytest.fixture(scope="function")
def test_api_key() -> str:
    """生成测试用 API Key"""
    try:
        from shared.core.auth.api_key import generate_api_key
        return generate_api_key(prefix="test-", length=32)
    except ImportError:
        return "test-api-key-for-unit-testing-purposes-only"


@pytest.fixture(scope="function")
def in_memory_api_key_store(test_api_key):
    """内存版 API Key 存储"""
    try:
        from shared.core.auth.api_key import InMemoryApiKeyStore, ApiKeyInfo, hash_api_key_sha256
        store = InMemoryApiKeyStore()
        key_hash = hash_api_key_sha256(test_api_key)
        store.add_key(ApiKeyInfo(
            key_hash=key_hash,
            key_name="test-key",
            key_prefix=test_api_key[:8],
            roles=["admin"],
            scopes=["*"],
            owner="test",
        ))
        return store
    except ImportError:
        pytest.skip("API Key 模块不可用")


# ============================================================
# M8 控制塔测试应用 Fixtures
# ============================================================

@pytest.fixture(scope="function")
def m8_app():
    """
    创建 M8 FastAPI 测试应用实例

    注意：如果 M8 后端模块无法导入（依赖缺失），
    则返回 None，相关测试会自动跳过。
    """
    try:
        # 设置测试环境
        os.environ["ENV"] = "testing"

        # 尝试导入 M8 应用
        m8_backend_path = PROJECT_ROOT / "M8-control-tower"
        if str(m8_backend_path) not in sys.path:
            sys.path.insert(0, str(m8_backend_path))

        from backend.main import create_app
        app = create_app()
        return app
    except Exception as e:
        pytest.skip(f"M8 应用无法初始化: {e}")


@pytest.fixture(scope="function")
def m8_client(m8_app):
    """
    M8 API 测试客户端（基于 TestClient）
    """
    from fastapi.testclient import TestClient
    return TestClient(m8_app)


# ============================================================
# M9 开发工坊测试应用 Fixtures
# ============================================================

@pytest.fixture(scope="function")
def m9_app(test_workspace_dir):
    """
    创建 M9 FastAPI 测试应用实例
    """
    try:
        os.environ["ENV"] = "testing"
        os.environ["M9_WORKSPACE_DIR"] = str(test_workspace_dir)

        m9_backend_path = PROJECT_ROOT / "M9-dev-workshop" / "backend"
        if str(m9_backend_path) not in sys.path:
            sys.path.insert(0, str(m9_backend_path))

        # 尝试从 main 模块创建应用
        try:
            from main import create_app
            app = create_app()
            return app
        except ImportError:
            # 如果没有 create_app，尝试直接导入 app
            try:
                from main import app
                return app
            except ImportError:
                pytest.skip("M9 应用无法导入")
    except Exception as e:
        pytest.skip(f"M9 应用无法初始化: {e}")


@pytest.fixture(scope="function")
def m9_client(m9_app):
    """
    M9 API 测试客户端（基于 TestClient）
    """
    from fastapi.testclient import TestClient
    return TestClient(m9_app)


# ============================================================
# M11 MCP 总线测试应用 Fixtures
# ============================================================

@pytest.fixture(scope="function")
def m11_app():
    """
    创建 M11 MCP Bus FastAPI 测试应用实例
    """
    try:
        os.environ["ENV"] = "testing"

        m11_src_path = PROJECT_ROOT / "M11-mcp-bus" / "src"
        if str(m11_src_path) not in sys.path:
            sys.path.insert(0, str(m11_src_path))

        try:
            from main import create_app
            app = create_app()
            return app
        except ImportError:
            try:
                from main import app
                return app
            except ImportError:
                pytest.skip("M11 应用无法导入")
    except Exception as e:
        pytest.skip(f"M11 应用无法初始化: {e}")


@pytest.fixture(scope="function")
def m11_client(m11_app):
    """
    M11 API 测试客户端（基于 TestClient）
    """
    from fastapi.testclient import TestClient
    return TestClient(m11_app)


# ============================================================
# 认证 Fixtures
# ============================================================

@pytest.fixture(scope="function")
def admin_token(m8_client) -> Optional[str]:
    """获取管理员 Token（通过登录接口）"""
    try:
        response = m8_client.post(
            "/api/auth/login",
            json={"username": "admin", "password": "admin123456"}
        )
        if response.status_code == 200:
            data = response.json()
            if data.get("code") == 0:
                return data.get("data", {}).get("access_token", "")
    except Exception:
        pass
    # 如果无法获取真实 token，返回测试用的占位 token
    return "test-admin-token-placeholder"


@pytest.fixture(scope="function")
def auth_headers(admin_token: str) -> Dict[str, str]:
    """带 Bearer 认证的请求头"""
    return {
        "Authorization": f"Bearer {admin_token}",
        "Content-Type": "application/json"
    }


@pytest.fixture(scope="function")
def api_key_headers(test_api_key: str) -> Dict[str, str]:
    """带 X-API-Key 认证的请求头"""
    return {
        "X-API-Key": test_api_key,
        "Content-Type": "application/json"
    }


# ============================================================
# API 客户端 Fixture
# ============================================================

@pytest.fixture(scope="function")
def api_client(test_env):
    """
    统一的 API 测试客户端

    提供便捷的 HTTP 请求方法，自动处理：
    - 基础 URL 拼接
    - Token 认证
    - 统一响应解析
    - 错误处理
    """
    from tests.utils.api_client import YunxiApiClient

    base_url = test_env.get("M8_BASE_URL", "http://127.0.0.1:18080")
    client = YunxiApiClient(base_url=base_url)
    yield client
    # 清理
    client.close()


# ============================================================
# 测试数据生成器 Fixture
# ============================================================

@pytest.fixture(scope="function")
def data_generator():
    """测试数据生成器"""
    from tests.utils.data_generator import TestDataGenerator
    return TestDataGenerator()


# ============================================================
# 常用断言辅助 Fixture
# ============================================================

@pytest.fixture(scope="session")
def assert_helper():
    """断言辅助工具"""
    class AssertHelper:
        @staticmethod
        def api_success(response_data: Dict[str, Any]):
            """验证 API 响应成功"""
            assert response_data.get("code") == 0, \
                f"API 返回错误: code={response_data.get('code')}, msg={response_data.get('message')}"
            assert "data" in response_data

        @staticmethod
        def api_error(response_data: Dict[str, Any], expected_code: int = None):
            """验证 API 响应错误"""
            assert response_data.get("code") != 0
            if expected_code is not None:
                assert response_data.get("code") == expected_code

        @staticmethod
        def has_keys(data: Dict[str, Any], keys: list):
            """验证字典包含指定 key"""
            for key in keys:
                assert key in data, f"缺少 key: {key}"

        @staticmethod
        def is_valid_datetime(date_str: str):
            """验证字符串是合法的日期时间格式"""
            try:
                datetime.fromisoformat(date_str.replace("Z", "+00:00"))
                return True
            except (ValueError, AttributeError):
                for fmt in ["%Y-%m-%d %H:%M:%S", "%Y-%m-%d", "%Y/%m/%d %H:%M:%S"]:
                    try:
                        datetime.strptime(date_str, fmt)
                        return True
                    except ValueError:
                        continue
                return False

        @staticmethod
        def is_valid_uuid(value: str) -> bool:
            """验证字符串是否为有效的 UUID"""
            import re
            uuid_pattern = r'^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'
            return bool(re.match(uuid_pattern, value, re.IGNORECASE))

        @staticmethod
        def is_paginated_response(data: Dict[str, Any]):
            """验证分页响应结构"""
            assert "items" in data
            assert "total" in data
            assert "page" in data
            assert "page_size" in data
            assert isinstance(data["items"], list)
            assert isinstance(data["total"], int)
            assert isinstance(data["page"], int)
            assert isinstance(data["page_size"], int)

    return AssertHelper()


# ============================================================
# Mock 工具 Fixtures
# ============================================================

@pytest.fixture(scope="function")
def mock_http_response():
    """创建 Mock HTTP 响应的辅助工具"""
    from unittest.mock import Mock

    def _make_response(status_code=200, json_data=None, text="", headers=None):
        mock_resp = Mock()
        mock_resp.status_code = status_code
        mock_resp.json.return_value = json_data or {}
        mock_resp.text = text
        mock_resp.headers = headers or {}
        mock_resp.ok = 200 <= status_code < 300
        return mock_resp

    return _make_response


@pytest.fixture(scope="function")
def mock_httpx_client():
    """Mock httpx.AsyncClient"""
    from unittest.mock import AsyncMock, MagicMock

    def _make_mock():
        mock_client = MagicMock()
        mock_client.get = AsyncMock()
        mock_client.post = AsyncMock()
        mock_client.put = AsyncMock()
        mock_client.delete = AsyncMock()
        mock_client.patch = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        return mock_client

    return _make_mock


# ============================================================
# Shared 核心模块 Fixtures
# ============================================================

@pytest.fixture(scope="session")
def sample_config():
    """示例配置（用于测试 BaseConfig）"""
    try:
        from shared.core.config import BaseConfig, EnvType
        from pydantic_settings import SettingsConfigDict

        class TestConfig(BaseConfig):
            module_name: str = "test"
            custom_setting: str = "default_value"
            timeout: int = 30

            model_config = SettingsConfigDict(
                env_prefix="TEST_",
                env_file=".env.test",
                extra="allow",
                validate_assignment=True,
            )

        return TestConfig
    except ImportError:
        pytest.skip("配置模块不可用")


# ============================================================
# 测试会话级钩子
# ============================================================

def pytest_configure(config):
    """pytest 配置钩子 - 会话开始前执行"""
    # 确保测试报告目录存在
    reports_dir = PROJECT_ROOT / "tests" / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)

    # 确保测试数据目录存在
    data_dir = PROJECT_ROOT / "tests" / "data"
    data_dir.mkdir(parents=True, exist_ok=True)

    # 确保覆盖率报告目录存在
    cov_dir = reports_dir / "coverage_html"
    cov_dir.mkdir(parents=True, exist_ok=True)

    # 设置测试环境标记
    os.environ["YUNXI_TEST_MODE"] = "1"
    os.environ["ENV"] = "testing"


def pytest_sessionstart(session):
    """测试会话开始"""
    print("\n" + "=" * 60)
    print("  云汐系统 - 自动化测试套件")
    print("  测试环境: testing")
    print(f"  开始时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 60)


def pytest_sessionfinish(session, exitstatus):
    """测试会话结束"""
    print("\n" + "=" * 60)
    print(f"  测试完成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"  退出状态: {exitstatus}")
    print("=" * 60 + "\n")


def pytest_collection_modifyitems(config, items):
    """测试用例收集后修改 - 添加默认标记"""
    for item in items:
        # 为集成测试目录下的测试自动添加 integration 标记
        if "test_integration" in str(item.fspath):
            item.add_marker(pytest.mark.integration)

        # 根据文件路径自动添加模块标记
        path_str = str(item.fspath)
        if "test_m8" in path_str:
            item.add_marker(pytest.mark.m8)
        elif "test_m9" in path_str:
            item.add_marker(pytest.mark.m9)
        elif "test_m11" in path_str:
            item.add_marker(pytest.mark.m11)
        elif "test_shared" in path_str:
            item.add_marker(pytest.mark.shared)
