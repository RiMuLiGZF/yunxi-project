"""
云汐系统 - pytest 全局配置与 Fixtures

提供所有测试共享的 fixture 配置，包括：
- 测试环境配置加载
- M8 API 客户端
- 测试数据库
- 测试数据生成器
- 鉴权 Token fixture
"""

import os
import sys
import json
import asyncio
import tempfile
from pathlib import Path
from datetime import datetime, timedelta
from typing import Dict, Any, Optional, Generator, AsyncGenerator

import pytest

# 将项目根目录加入 path
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))


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
# 测试数据库 Fixture
# ============================================================

@pytest.fixture(scope="function")
def test_db_path(tmp_path) -> str:
    """创建临时测试数据库路径"""
    db_path = tmp_path / "test_m8.db"
    return str(db_path)


@pytest.fixture(scope="function")
def test_data_dir(tmp_path) -> Path:
    """创建测试数据目录"""
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    return data_dir


# ============================================================
# M8 测试应用 Fixture
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
        os.environ["ENV"] = "test"
        
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
# 认证 Fixtures
# ============================================================

@pytest.fixture(scope="function")
def admin_token(m8_client) -> Optional[str]:
    """获取管理员 Token"""
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
    """带认证的请求头"""
    return {
        "Authorization": f"Bearer {admin_token}",
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
                # 尝试其他格式
                for fmt in ["%Y-%m-%d %H:%M:%S", "%Y-%m-%d", "%Y/%m/%d %H:%M:%S"]:
                    try:
                        datetime.strptime(date_str, fmt)
                        return True
                    except ValueError:
                        continue
                return False
    
    return AssertHelper()


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
    
    # 设置测试环境标记
    os.environ["YUNXI_TEST_MODE"] = "1"


def pytest_sessionstart(session):
    """测试会话开始"""
    print("\n" + "=" * 60)
    print("  云汐系统 v1.1 - 自动化测试")
    print("  测试环境: test")
    print(f"  开始时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 60)


def pytest_sessionfinish(session, exitstatus):
    """测试会话结束"""
    print("\n" + "=" * 60)
    print(f"  测试完成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"  退出状态: {exitstatus}")
    print("=" * 60 + "\n")
