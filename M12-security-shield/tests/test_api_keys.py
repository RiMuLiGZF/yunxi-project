"""
M12 安全盾 - API Key 管理单元测试
覆盖：API Key 创建、验证、权限检查、吊销、列表查询
"""

import sys
import os
import re
import unittest
from datetime import datetime, timedelta
from unittest.mock import patch, MagicMock

# 将项目根目录加入路径
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

# 预先设置安全 JWT 密钥，避免默认空密钥触发启动失败
os.environ.setdefault("M12_JWT_SECRET", "test-jwt-secret-for-unit-tests-only-do-not-use-in-production")

from backend.auth import (
    generate_api_key,
    hash_api_key,
    get_api_key_prefix,
    validate_api_key,
    has_scope,
    has_role,
)
from backend.models import ApiKey
from backend.config import get_settings


class TestApiKeyGeneration(unittest.TestCase):
    """API Key 生成相关测试"""

    def test_generate_api_key_returns_string(self):
        """测试：生成的 Key 是非空字符串"""
        key = generate_api_key()
        self.assertIsInstance(key, str)
        self.assertTrue(len(key) > 0)

    def test_generate_api_key_has_correct_prefix(self):
        """测试：生成的 Key 格式正确（包含指定前缀）"""
        key = generate_api_key(prefix="m12-")
        self.assertTrue(key.startswith("m12-"))

    def test_generate_api_key_default_prefix(self):
        """测试：默认前缀为 m12-"""
        settings = get_settings()
        key = generate_api_key(prefix=settings.api_key_prefix)
        self.assertTrue(key.startswith(settings.api_key_prefix))

    def test_generate_api_key_length(self):
        """测试：生成的 Key 长度合理（前缀 + 32字节 URL-safe base64）"""
        key = generate_api_key(prefix="m12-")
        # 32 bytes -> base64 约 43 字符 + 前缀 4 字符
        self.assertGreater(len(key), 30)
        self.assertLess(len(key), 100)

    def test_generate_api_key_charset_urlsafe(self):
        """测试：生成的 Key 使用 URL-safe 字符集（字母、数字、-、_）"""
        key = generate_api_key(prefix="test-")
        # 去掉前缀后检查
        key_body = key[len("test-"):]
        # URL-safe base64 字符集: A-Z, a-z, 0-9, -, _
        pattern = r'^[A-Za-z0-9\-_]+=*$'
        self.assertTrue(re.match(pattern, key_body),
                        f"Key body '{key_body}' contains invalid characters")

    def test_generate_api_key_unique(self):
        """测试：多次生成的 Key 互不相同"""
        keys = set()
        for _ in range(20):
            keys.add(generate_api_key())
        self.assertEqual(len(keys), 20)

    def test_generate_api_key_custom_prefix(self):
        """测试：自定义前缀生效"""
        key = generate_api_key(prefix="custom-prefix-")
        self.assertTrue(key.startswith("custom-prefix-"))


class TestApiKeyHashing(unittest.TestCase):
    """API Key 哈希存储相关测试"""

    def test_hash_api_key_returns_hex_string(self):
        """测试：哈希函数返回十六进制字符串"""
        key = generate_api_key()
        hashed = hash_api_key(key)
        self.assertIsInstance(hashed, str)
        # SHA256 哈希是 64 个十六进制字符
        self.assertEqual(len(hashed), 64)
        # 全部是十六进制字符
        self.assertTrue(all(c in '0123456789abcdef' for c in hashed))

    def test_hash_api_key_stored_not_plaintext(self):
        """测试：存储的是哈希值而非明文"""
        key = "m12-testkey1234567890"
        hashed = hash_api_key(key)
        # 哈希值不应包含原始 key 的内容
        self.assertNotIn(key, hashed)
        self.assertNotEqual(key, hashed)

    def test_hash_api_key_consistent(self):
        """测试：相同输入得到相同哈希（确定性）"""
        key = generate_api_key()
        hash1 = hash_api_key(key)
        hash2 = hash_api_key(key)
        self.assertEqual(hash1, hash2)

    def test_hash_api_key_different_inputs_different_hashes(self):
        """测试：不同 Key 生成不同哈希值"""
        key1 = generate_api_key()
        key2 = generate_api_key()
        hash1 = hash_api_key(key1)
        hash2 = hash_api_key(key2)
        self.assertNotEqual(hash1, hash2)

    def test_get_api_key_prefix_format(self):
        """测试：Key 前缀展示格式正确（前8位 + ... + 后4位）"""
        key = "m12-abcdefghijklmnop1234"
        prefix = get_api_key_prefix(key)
        self.assertIn("...", prefix)
        # 以 key 的前 8 位开头
        self.assertTrue(prefix.startswith(key[:8]))
        # 以 key 的后 4 位结尾
        self.assertTrue(prefix.endswith(key[-4:]))

    def test_get_api_key_prefix_short_key(self):
        """测试：短 Key 的前缀展示"""
        short_key = "short"
        prefix = get_api_key_prefix(short_key)
        # 短 key 也应该返回带 ... 的格式
        self.assertIn("...", prefix)

    def test_get_api_key_prefix_empty(self):
        """测试：空 Key 的前缀展示"""
        prefix = get_api_key_prefix("")
        self.assertIsInstance(prefix, str)


class TestApiKeyValidation(unittest.TestCase):
    """API Key 验证功能测试（使用 mock 数据库）"""

    def setUp(self):
        """测试前准备：创建 mock 数据库会话"""
        self.mock_db = MagicMock()
        self.api_key = generate_api_key()
        self.key_hash = hash_api_key(self.api_key)

    def _create_mock_key_record(self, **kwargs):
        """创建一个 mock 的 ApiKey 对象"""
        defaults = {
            "id": 1,
            "key_name": "test-key",
            "key_hash": self.key_hash,
            "key_prefix": get_api_key_prefix(self.api_key),
            "owner": "test-owner",
            "roles": ["admin"],
            "scopes": ["waf:read", "waf:write"],
            "is_active": True,
            "expires_at": None,
        }
        defaults.update(kwargs)
        mock_key = MagicMock(spec=ApiKey)
        for k, v in defaults.items():
            setattr(mock_key, k, v)
        return mock_key

    def test_validate_valid_key_returns_record(self):
        """测试：有效 Key 验证通过，返回 Key 记录"""
        mock_key = self._create_mock_key_record()
        self.mock_db.query().filter().first.return_value = mock_key

        result = validate_api_key(self.mock_db, self.api_key)
        self.assertIsNotNone(result)
        self.assertEqual(result.key_name, "test-key")

    def test_validate_revoked_key_returns_none(self):
        """测试：已吊销（is_active=False）Key 验证失败"""
        mock_key = self._create_mock_key_record(is_active=False)
        # 因为 filter 条件里有 is_active==True，所以查询不到
        self.mock_db.query().filter().first.return_value = None

        result = validate_api_key(self.mock_db, self.api_key)
        self.assertIsNone(result)

    def test_validate_expired_key_returns_none(self):
        """测试：已过期 Key 验证失败"""
        # 过期时间设为昨天
        expired_time = datetime.now() - timedelta(days=1)
        mock_key = self._create_mock_key_record(
            is_active=True,
            expires_at=expired_time,
        )
        self.mock_db.query().filter().first.return_value = mock_key

        result = validate_api_key(self.mock_db, self.api_key)
        self.assertIsNone(result)

    def test_validate_nonexistent_key_returns_none(self):
        """测试：不存在的 Key 验证失败"""
        self.mock_db.query().filter().first.return_value = None

        result = validate_api_key(self.mock_db, "nonexistent-key-12345")
        self.assertIsNone(result)

    def test_validate_empty_key_returns_none(self):
        """测试：空 Key 验证失败"""
        self.mock_db.query().filter().first.return_value = None

        result = validate_api_key(self.mock_db, "")
        self.assertIsNone(result)

    def test_validate_key_not_expired_returns_record(self):
        """测试：未过期的 Key（有过期时间但未到）验证通过"""
        future_time = datetime.now() + timedelta(days=30)
        mock_key = self._create_mock_key_record(
            is_active=True,
            expires_at=future_time,
        )
        self.mock_db.query().filter().first.return_value = mock_key

        result = validate_api_key(self.mock_db, self.api_key)
        self.assertIsNotNone(result)


class TestApiKeyRBAC(unittest.TestCase):
    """API Key 权限验证（RBAC）测试"""

    def test_key_with_permission_passes_check(self):
        """测试：拥有权限的 Key 通过检查"""
        scopes = ["waf:read", "waf:write", "ip:read"]
        self.assertTrue(has_scope(scopes, "waf:read"))
        self.assertTrue(has_scope(scopes, "waf:write"))

    def test_key_without_permission_denied(self):
        """测试：缺少权限的 Key 被拒绝"""
        scopes = ["waf:read"]
        self.assertFalse(has_scope(scopes, "auth:write"))
        self.assertFalse(has_scope(scopes, "ip:write"))

    def test_wildcard_permission_matches_all(self):
        """测试：通配符权限（*）匹配所有"""
        scopes = ["*"]
        self.assertTrue(has_scope(scopes, "waf:read"))
        self.assertTrue(has_scope(scopes, "auth:write"))
        self.assertTrue(has_scope(scopes, "any:random:scope"))

    def test_empty_scopes_denied(self):
        """测试：空权限列表拒绝所有"""
        scopes = []
        self.assertFalse(has_scope(scopes, "waf:read"))
        self.assertFalse(has_scope(scopes, "*"))  # 注意：列表为空时没有 *

    def test_role_hierarchy_for_api_key(self):
        """测试：API Key 的角色层级判断"""
        # 拥有 admin 角色的 key
        roles = ["admin"]
        self.assertTrue(has_role(roles, "viewer"))  # admin > viewer
        self.assertTrue(has_role(roles, "admin"))   # admin == admin
        self.assertFalse(has_role(roles, "super_admin"))  # admin < super_admin


class TestApiKeyManagement(unittest.TestCase):
    """API Key 管理功能测试（创建、吊销、列表、查询）"""

    def setUp(self):
        """测试前准备：重置全局存储"""
        from backend.routers import auth_api
        auth_api._api_keys_storage = []
        auth_api._api_key_id_counter = 0
        self.auth_api = auth_api

    def test_create_api_key_success(self):
        """测试：创建 API Key 成功"""
        result = self.auth_api.create_api_key(
            key_name="test-key",
            owner="test-owner",
            roles="admin,operator",
            scopes="waf:read,waf:write",
            description="test description",
        )
        self.assertEqual(result["code"], 0)
        self.assertIn("api_key", result["data"])
        self.assertIn("id", result["data"])
        self.assertEqual(result["data"]["key_name"], "test-key")
        self.assertEqual(result["data"]["owner"], "test-owner")

    def test_create_api_key_metadata_correct(self):
        """测试：创建的 Key 元数据正确（名称、权限、过期时间）"""
        result = self.auth_api.create_api_key(
            key_name="my-service-key",
            owner="service-a",
            roles="api",
            scopes="waf:read",
            rate_limit=100,
            description="Service A API Key",
        )
        data = result["data"]
        self.assertEqual(data["key_name"], "my-service-key")
        self.assertEqual(data["owner"], "service-a")
        self.assertEqual(data["roles"], ["api"])
        self.assertEqual(data["scopes"], ["waf:read"])
        self.assertEqual(data["rate_limit"], 100)
        self.assertEqual(data["description"], "Service A API Key")
        self.assertTrue(data["is_active"])

    def test_create_api_key_returns_plaintext_once(self):
        """测试：创建时返回完整明文 Key，且不返回哈希值"""
        result = self.auth_api.create_api_key(key_name="once-key")
        data = result["data"]
        # 应该包含明文 api_key
        self.assertIn("api_key", data)
        self.assertTrue(data["api_key"].startswith("m12-"))
        # 不应该返回 key_hash
        self.assertNotIn("key_hash", data)

    def test_create_multiple_keys_unique_ids(self):
        """测试：多次创建 Key 具有唯一 ID"""
        ids = set()
        for i in range(5):
            result = self.auth_api.create_api_key(key_name=f"key-{i}")
            ids.add(result["data"]["id"])
        self.assertEqual(len(ids), 5)

    def _list_keys(self, **kwargs):
        """辅助方法：调用 list_api_keys，显式传递所有参数以避免 FastAPI Query 默认值问题"""
        defaults = {"owner": None, "is_active": None, "page": 1, "page_size": 20}
        defaults.update(kwargs)
        return self.auth_api.list_api_keys(**defaults)

    def test_list_api_keys_empty(self):
        """测试：列出所有 Key（空列表）"""
        result = self._list_keys(page=1, page_size=20)
        self.assertEqual(result["code"], 0)
        self.assertEqual(result["data"]["total"], 0)
        self.assertEqual(len(result["data"]["items"]), 0)

    def test_list_api_keys_with_data(self):
        """测试：列出所有 Key（有数据）"""
        for i in range(3):
            self.auth_api.create_api_key(key_name=f"list-key-{i}")

        result = self._list_keys(page=1, page_size=20)
        self.assertEqual(result["code"], 0)
        self.assertEqual(result["data"]["total"], 3)
        self.assertEqual(len(result["data"]["items"]), 3)

    def test_list_api_keys_pagination(self):
        """测试：Key 列表分页功能"""
        for i in range(10):
            self.auth_api.create_api_key(key_name=f"page-key-{i}")

        # 第 1 页，每页 3 条
        page1 = self._list_keys(page=1, page_size=3)
        self.assertEqual(page1["data"]["total"], 10)
        self.assertEqual(len(page1["data"]["items"]), 3)
        self.assertEqual(page1["data"]["page"], 1)

        # 第 2 页
        page2 = self._list_keys(page=2, page_size=3)
        self.assertEqual(len(page2["data"]["items"]), 3)
        self.assertEqual(page2["data"]["page"], 2)

        # 不同页的 ID 应该不同
        page1_ids = [k["id"] for k in page1["data"]["items"]]
        page2_ids = [k["id"] for k in page2["data"]["items"]]
        self.assertEqual(len(set(page1_ids) & set(page2_ids)), 0)

    def test_get_api_key_by_id(self):
        """测试：按 ID 查询 Key"""
        create_result = self.auth_api.create_api_key(key_name="get-by-id")
        key_id = create_result["data"]["id"]

        get_result = self.auth_api.get_api_key_detail(key_id)
        self.assertEqual(get_result["code"], 0)
        self.assertEqual(get_result["data"]["id"], key_id)
        self.assertEqual(get_result["data"]["key_name"], "get-by-id")
        # 详情不包含明文 key
        self.assertNotIn("api_key", get_result["data"])

    def test_get_nonexistent_key_returns_404(self):
        """测试：查询不存在的 Key 返回 404"""
        result = self.auth_api.get_api_key_detail(9999)
        self.assertNotEqual(result["code"], 0)

    def test_revoke_api_key(self):
        """测试：吊销 Key"""
        create_result = self.auth_api.create_api_key(key_name="to-revoke")
        key_id = create_result["data"]["id"]

        # 吊销
        revoke_result = self.auth_api.revoke_api_key(key_id)
        self.assertEqual(revoke_result["code"], 0)
        self.assertTrue(revoke_result["data"]["revoked"])

        # 吊销后查询不到
        get_result = self.auth_api.get_api_key_detail(key_id)
        self.assertNotEqual(get_result["code"], 0)

    def test_revoke_nonexistent_key_fails(self):
        """测试：吊销不存在的 Key 失败"""
        result = self.auth_api.revoke_api_key(9999)
        self.assertNotEqual(result["code"], 0)

    def test_update_api_key(self):
        """测试：更新 Key 配置"""
        create_result = self.auth_api.create_api_key(
            key_name="original-name",
            description="original desc",
        )
        key_id = create_result["data"]["id"]

        update_result = self.auth_api.update_api_key(
            key_id=key_id,
            key_name="updated-name",
            description="updated desc",
            is_active=False,
        )
        self.assertEqual(update_result["code"], 0)
        self.assertEqual(update_result["data"]["key_name"], "updated-name")
        self.assertEqual(update_result["data"]["description"], "updated desc")
        self.assertFalse(update_result["data"]["is_active"])

    def test_rotate_api_key(self):
        """测试：轮换 Key（生成新密钥，旧密钥失效）"""
        create_result = self.auth_api.create_api_key(key_name="rotate-key")
        key_id = create_result["data"]["id"]
        old_api_key = create_result["data"]["api_key"]
        old_prefix = create_result["data"]["key_prefix"]

        rotate_result = self.auth_api.rotate_api_key(key_id)
        self.assertEqual(rotate_result["code"], 0)
        new_api_key = rotate_result["data"]["api_key"]

        # 新 Key 和旧 Key 应该不同
        self.assertNotEqual(old_api_key, new_api_key)
        # 前缀也应该更新
        self.assertNotEqual(old_prefix, rotate_result["data"]["key_prefix"])
        # 调用计数重置
        self.assertEqual(rotate_result["data"]["call_count"], 0)

    def test_list_keys_filter_by_owner(self):
        """测试：按所有者筛选 Key 列表"""
        self.auth_api.create_api_key(key_name="k1", owner="team-a")
        self.auth_api.create_api_key(key_name="k2", owner="team-b")
        self.auth_api.create_api_key(key_name="k3", owner="team-a")

        result = self._list_keys(owner="team-a", page=1, page_size=20)
        self.assertEqual(result["data"]["total"], 2)


if __name__ == "__main__":
    unittest.main()
