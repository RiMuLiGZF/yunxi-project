"""
E2E 测试 - 共享 Fixtures

提供 E2E 测试所需的所有共享 fixtures：
- e2e_config: E2E 测试配置
- e2e_api_client: 配置好的 API 客户端
- auth_headers: 已认证的请求头
- admin_headers: 管理员权限的请求头
- test_user: 测试用户（自动创建和清理）
- test_data_factory: 测试数据工厂
- cleanup_test_data: 测试数据清理
"""

import os
import sys
import json
import time
from pathlib import Path
from typing import Dict, Any, Optional, Generator, List

import pytest

# 项目根目录
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

# 确保 tests 目录在 path 中
if str(PROJECT_ROOT / "tests") not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT / "tests"))

# 导入 E2E 配置和工具
from tests.e2e.config import E2ETestConfig, get_e2e_config
from tests.e2e.utils.api_client import E2EApiClient
from tests.e2e.utils.test_data import E2ETestDataFactory, TestUser
from tests.e2e.utils.helpers import (
    assert_api_success,
    assert_api_error,
    assert_has_keys,
    generate_test_id,
)


# ============================================================
# 配置 Fixtures
# ============================================================

@pytest.fixture(scope="session")
def e2e_config() -> E2ETestConfig:
    """
    E2E 测试配置 fixture（会话级）

    提供所有 E2E 测试共享的配置信息。
    """
    config = get_e2e_config()
    return config


@pytest.fixture(scope="session")
def use_mock(e2e_config: E2ETestConfig) -> bool:
    """是否使用 Mock 模式"""
    return e2e_config.use_mock


# ============================================================
# API 客户端 Fixtures
# ============================================================

@pytest.fixture(scope="function")
def e2e_api_client(e2e_config: E2ETestConfig) -> Generator[E2EApiClient, None, None]:
    """
    E2E API 客户端 fixture（函数级）

    每个测试函数独立的 API 客户端，确保测试隔离。
    测试结束后自动清理。
    """
    client = E2EApiClient(
        base_url=e2e_config.gateway_url,
        use_mock=e2e_config.use_mock,
        timeout=e2e_config.request_timeout,
        max_retries=e2e_config.max_retries,
        retry_interval=e2e_config.retry_interval,
    )
    yield client
    # 测试结束后清理
    client.cleanup_test_data(prefix=e2e_config.test_user_prefix)
    client.close()


@pytest.fixture(scope="function")
def admin_api_client(
    e2e_api_client: E2EApiClient,
    e2e_config: E2ETestConfig,
) -> E2EApiClient:
    """
    已登录管理员的 API 客户端

    自动以管理员身份登录。
    """
    result = e2e_api_client.login(
        username=e2e_config.admin_username,
        password=e2e_config.admin_password,
    )
    if result.get("code") != 0:
        pytest.skip(f"管理员登录失败: {result.get('message')}")
    return e2e_api_client


@pytest.fixture(scope="function")
def auth_headers(admin_api_client: E2EApiClient) -> Dict[str, str]:
    """
    已认证的请求头（管理员权限）

    Returns:
        包含 Authorization 的请求头字典
    """
    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json",
    }
    if admin_api_client.access_token:
        headers["Authorization"] = f"Bearer {admin_api_client.access_token}"
    return headers


@pytest.fixture(scope="function")
def admin_headers(auth_headers: Dict[str, str]) -> Dict[str, str]:
    """管理员权限的请求头（同 auth_headers，语义更明确）"""
    return auth_headers


# ============================================================
# 测试用户 Fixtures
# ============================================================

@pytest.fixture(scope="function")
def test_data_factory() -> Generator[E2ETestDataFactory, None, None]:
    """
    测试数据工厂 fixture

    提供测试数据生成能力，测试结束后自动清理。
    """
    factory = E2ETestDataFactory(prefix="e2e_test_")
    yield factory
    # 测试结束后清理
    factory.cleanup()


@pytest.fixture(scope="function")
def test_user(
    e2e_api_client: E2EApiClient,
    test_data_factory: E2ETestDataFactory,
) -> TestUser:
    """
    测试用户 fixture（自动创建和清理）

    创建一个普通测试用户，测试结束后自动清理。
    """
    user = test_data_factory.create_test_user(role="user")

    # 如果是 mock 模式，直接在客户端创建用户
    if e2e_api_client.use_mock:
        e2e_api_client._mock_users[user.username] = {
            "id": 100 + len(test_data_factory.get_created_users()),
            "username": user.username,
            "email": user.email,
            "password_hash": f"mock_hash_{user.password}",
            "_plain_password": user.password,
            "role": user.role,
            "is_active": True,
            "first_login": False,
            "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ"),
        }
        user.user_id = 100 + len(test_data_factory.get_created_users())

    return user


@pytest.fixture(scope="function")
def test_user_logged_in(
    e2e_api_client: E2EApiClient,
    test_user: TestUser,
) -> Dict[str, Any]:
    """
    已登录的测试用户

    Returns:
        登录结果 {token, user, ...}
    """
    result = e2e_api_client.login(
        username=test_user.username,
        password=test_user.password,
    )
    if result.get("code") != 0:
        pytest.skip(f"测试用户登录失败: {result.get('message')}")
    return result.get("data", {})


@pytest.fixture(scope="function")
def user_auth_headers(
    e2e_api_client: E2EApiClient,
    test_user_logged_in: Dict[str, Any],
) -> Dict[str, str]:
    """
    普通用户的认证请求头
    """
    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json",
    }
    token = test_user_logged_in.get("access_token", "")
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


# ============================================================
# 多设备/多用户 Fixtures
# ============================================================

@pytest.fixture(scope="function")
def multiple_test_users(
    test_data_factory: E2ETestDataFactory,
    e2e_api_client: E2EApiClient,
) -> List[TestUser]:
    """
    多个测试用户 fixture

    创建 5 个测试用户，用于多用户场景测试。
    """
    users = test_data_factory.create_multiple_users(count=5, role="user")

    if e2e_api_client.use_mock:
        for i, user in enumerate(users):
            e2e_api_client._mock_users[user.username] = {
                "id": 200 + i,
                "username": user.username,
                "email": user.email,
                "password_hash": f"mock_hash_{user.password}",
                "_plain_password": user.password,
                "role": user.role,
                "is_active": True,
                "first_login": False,
                "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ"),
            }
            user.user_id = 200 + i

    return users


# ============================================================
# 数据清理 Fixtures
# ============================================================

@pytest.fixture(scope="function")
def cleanup_test_data(
    e2e_api_client: E2EApiClient,
    e2e_config: E2ETestConfig,
) -> Generator[callable, None, None]:
    """
    测试数据清理 fixture

    提供一个清理函数，测试结束后自动执行清理。
    """
    cleanup_stats = {"cleaned": 0}

    def _cleanup(prefix: Optional[str] = None) -> int:
        prefix = prefix or e2e_config.test_user_prefix
        count = e2e_api_client.cleanup_test_data(prefix=prefix)
        cleanup_stats["cleaned"] += count
        return count

    yield _cleanup

    # 测试结束后自动清理
    if e2e_config.cleanup_strategy == "auto":
        try:
            _cleanup()
        except Exception:
            pass


# ============================================================
# 模块状态 Fixtures
# ============================================================

@pytest.fixture(scope="function")
def all_modules_healthy(
    admin_api_client: E2EApiClient,
    e2e_config: E2ETestConfig,
) -> bool:
    """
    确保所有模块健康（用于前置条件检查）

    如果模块不健康且非 mock 模式，跳过测试。
    """
    if e2e_config.use_mock:
        return True

    result = admin_api_client.get("/api/modules")
    if result.get("code") != 0:
        pytest.skip("无法获取模块状态")

    modules = result.get("data", {}).get("items", [])
    unhealthy = [m for m in modules if m.get("status") != "running"]
    if unhealthy:
        pytest.skip(f"以下模块不健康: {[m['key'] for m in unhealthy]}")

    return True


# ============================================================
# 测试数据快照 Fixtures
# ============================================================

@pytest.fixture(scope="function")
def data_snapshot(
    test_data_factory: E2ETestDataFactory,
) -> Generator[str, None, None]:
    """
    测试数据快照 fixture

    测试前创建数据快照，测试后可用于恢复。
    """
    snapshot_id = test_data_factory.create_snapshot("before_test")
    yield snapshot_id
    # 测试后恢复快照
    test_data_factory.restore_snapshot(snapshot_id)


# ============================================================
# 断言辅助 Fixtures
# ============================================================

@pytest.fixture(scope="session")
def e2e_assertions():
    """
    E2E 测试断言辅助工具
    """
    class E2EAssertions:
        @staticmethod
        def success(response: Dict[str, Any], msg: str = ""):
            assert_api_success(response, msg)

        @staticmethod
        def error(response: Dict[str, Any], code: Optional[int] = None, msg: str = ""):
            assert_api_error(response, code, msg)

        @staticmethod
        def has_keys(data: Dict[str, Any], keys: list, msg: str = ""):
            assert_has_keys(data, keys, msg)

        @staticmethod
        def paginated(data: Dict[str, Any], msg: str = ""):
            assert_has_keys(data, ["items", "total", "page", "page_size"], msg)
            assert isinstance(data["items"], list)
            assert isinstance(data["total"], int)

        @staticmethod
        def valid_id(value: str, msg: str = ""):
            assert value and len(value) > 0, f"ID 不能为空. {msg}"

        @staticmethod
        def response_time(
            client: E2EApiClient,
            threshold_ms: float = 3000,
            msg: str = "",
        ):
            avg = client.stats.avg_response_time_ms
            assert avg <= threshold_ms, \
                f"平均响应时间 {avg:.2f}ms 超过阈值 {threshold_ms}ms. {msg}"

    return E2EAssertions()


# ============================================================
# 会话级钩子
# ============================================================

def pytest_configure(config):
    """pytest 配置钩子"""
    # 注册 E2E 测试标记
    config.addinivalue_line(
        "markers",
        "e2e: 标记为端到端测试（运行时间较长，需要完整环境）",
    )
    config.addinivalue_line(
        "markers",
        "e2e_auth: 认证流程 E2E 测试",
    )
    config.addinivalue_line(
        "markers",
        "e2e_user_journey: 用户旅程 E2E 测试",
    )
    config.addinivalue_line(
        "markers",
        "e2e_module_integration: 模块集成 E2E 测试",
    )
    config.addinivalue_line(
        "markers",
        "e2e_gateway: 网关集成 E2E 测试",
    )
    config.addinivalue_line(
        "markers",
        "e2e_slow: 运行时间较长的 E2E 测试",
    )

    # 确保 E2E 报告目录存在
    reports_dir = PROJECT_ROOT / "tests" / "reports" / "e2e"
    reports_dir.mkdir(parents=True, exist_ok=True)


def pytest_collection_modifyitems(config, items):
    """测试用例收集后修改"""
    for item in items:
        # 为 E2E 目录下的测试自动添加 e2e 标记
        if "tests/e2e" in str(item.fspath).replace("\\", "/"):
            item.add_marker(pytest.mark.e2e)

        # 根据文件名添加更细粒度的标记
        path_str = str(item.fspath).lower()
        if "test_auth_flow" in path_str:
            item.add_marker(pytest.mark.e2e_auth)
        elif "test_user_journey" in path_str:
            item.add_marker(pytest.mark.e2e_user_journey)
        elif "test_module_integration" in path_str:
            item.add_marker(pytest.mark.e2e_module_integration)
        elif "test_api_gateway" in path_str:
            item.add_marker(pytest.mark.e2e_gateway)


def pytest_sessionstart(session):
    """测试会话开始"""
    print("\n" + "=" * 70)
    print("  云汐系统 - E2E 端到端测试套件")
    print("  测试环境: " + os.environ.get("E2E_ENV", "testing"))
    print("  Mock 模式: " + os.environ.get("E2E_USE_MOCK", "1"))
    print(f"  开始时间: {time.strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 70)


def pytest_sessionfinish(session, exitstatus):
    """测试会话结束"""
    print("\n" + "=" * 70)
    print(f"  E2E 测试完成时间: {time.strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"  退出状态: {exitstatus}")
    print("=" * 70 + "\n")
