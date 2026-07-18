"""
API Key 统一管理中心 - 单元测试 (SC-010)

测试内容：
- ApiKeyLevel 分级与权限检查
- QuotaManager 配额管理
- ApiKeyCache 内存缓存
- SqliteApiKeyStore 持久化存储
- ApiKeyManager 核心管理（创建/吊销/轮换/验证/列表/统计/导入）
- 默认 Key 初始化
- 过期清理
- ServiceCaller 服务调用 SDK
- FastAPI Router 管理接口
"""

import sys
import os
import time
import json
import tempfile
from pathlib import Path
from datetime import datetime, timezone, timedelta
from unittest.mock import patch, MagicMock

import pytest

# 确保可以导入 shared 模块
SHARED_DIR = Path(__file__).resolve().parent.parent
PROJECT_DIR = SHARED_DIR.parent
if str(PROJECT_DIR) not in sys.path:
# ===========================================================================
# 测试辅助函数
# ===========================================================================

def _create_temp_db_manager():
    """创建临时数据库管理器（用于测试隔离）"""
    from shared.data.data_layer.database_manager import DatabaseManager
    tmp_dir = tempfile.mkdtemp(prefix="api_key_test_")
    return DatabaseManager(data_root=tmp_dir), tmp_dir


def _create_test_manager():
    """创建测试用的 ApiKeyManager（使用临时数据库）"""
    from shared.core.auth.api_key_manager import (
        ApiKeyManager, SqliteApiKeyStore, ApiKeyCache, QuotaManager,
    )
    db_manager, tmp_dir = _create_temp_db_manager()
    store = SqliteApiKeyStore(db_manager=db_manager, db_name="test_auth")
    cache = ApiKeyCache(max_size=50, ttl_seconds=60)
    quota = QuotaManager()
    manager = ApiKeyManager(store=store, cache=cache, quota_manager=quota)
    return manager, tmp_dir


# ===========================================================================
# ApiKeyLevel 测试
# ===========================================================================

class TestApiKeyLevel:
    """API Key 级别测试"""

    def test_level_values(self):
        """级别枚举值正确"""
        from shared.core.auth.api_key_manager import ApiKeyLevel
        assert ApiKeyLevel.ADMIN.value == "admin"
        assert ApiKeyLevel.SERVICE.value == "service"
        assert ApiKeyLevel.READ.value == "read"
        assert ApiKeyLevel.MONITOR.value == "monitor"

    def test_level_hierarchy_admin(self):
        """admin 级别最高，可以访问所有级别资源"""
        from shared.core.auth.api_key_manager import ApiKeyLevel
        # admin 可以访问 admin 级资源
        assert ApiKeyLevel.has_level(ApiKeyLevel.ADMIN, ApiKeyLevel.ADMIN) is True
        # admin 可以访问 service 级资源
        assert ApiKeyLevel.has_level(ApiKeyLevel.SERVICE, ApiKeyLevel.ADMIN) is True
        # admin 可以访问 read 级资源
        assert ApiKeyLevel.has_level(ApiKeyLevel.READ, ApiKeyLevel.ADMIN) is True
        # admin 可以访问 monitor 级资源
        assert ApiKeyLevel.has_level(ApiKeyLevel.MONITOR, ApiKeyLevel.ADMIN) is True

    def test_level_hierarchy_service(self):
        """service 级别可以访问 service/read/monitor"""
        from shared.core.auth.api_key_manager import ApiKeyLevel
        assert ApiKeyLevel.has_level(ApiKeyLevel.SERVICE, ApiKeyLevel.SERVICE) is True
        assert ApiKeyLevel.has_level(ApiKeyLevel.READ, ApiKeyLevel.SERVICE) is True
        assert ApiKeyLevel.has_level(ApiKeyLevel.MONITOR, ApiKeyLevel.SERVICE) is True
        # service 不能访问 admin 级资源
        assert ApiKeyLevel.has_level(ApiKeyLevel.ADMIN, ApiKeyLevel.SERVICE) is False

    def test_level_hierarchy_read(self):
        """read 级别可以访问 read/monitor"""
        from shared.core.auth.api_key_manager import ApiKeyLevel
        assert ApiKeyLevel.has_level(ApiKeyLevel.READ, ApiKeyLevel.READ) is True
        assert ApiKeyLevel.has_level(ApiKeyLevel.MONITOR, ApiKeyLevel.READ) is True
        assert ApiKeyLevel.has_level(ApiKeyLevel.SERVICE, ApiKeyLevel.READ) is False
        assert ApiKeyLevel.has_level(ApiKeyLevel.ADMIN, ApiKeyLevel.READ) is False

    def test_level_hierarchy_monitor(self):
        """monitor 级别最低"""
        from shared.core.auth.api_key_manager import ApiKeyLevel
        assert ApiKeyLevel.has_level(ApiKeyLevel.MONITOR, ApiKeyLevel.MONITOR) is True
        assert ApiKeyLevel.has_level(ApiKeyLevel.READ, ApiKeyLevel.MONITOR) is False
        assert ApiKeyLevel.has_level(ApiKeyLevel.SERVICE, ApiKeyLevel.MONITOR) is False
        assert ApiKeyLevel.has_level(ApiKeyLevel.ADMIN, ApiKeyLevel.MONITOR) is False

    def test_default_scopes(self):
        """各级别默认权限范围正确"""
        from shared.core.auth.api_key_manager import ApiKeyLevel
        assert ApiKeyLevel.default_scopes(ApiKeyLevel.ADMIN) == ["*"]
        assert "read" in ApiKeyLevel.default_scopes(ApiKeyLevel.SERVICE)
        assert "write" in ApiKeyLevel.default_scopes(ApiKeyLevel.SERVICE)
        assert ApiKeyLevel.default_scopes(ApiKeyLevel.READ) == ["read"]
        assert "health" in ApiKeyLevel.default_scopes(ApiKeyLevel.MONITOR)

    def test_default_rate_limit(self):
        """各级别默认限流配置正确"""
        from shared.core.auth.api_key_manager import ApiKeyLevel
        admin_rl = ApiKeyLevel.default_rate_limit(ApiKeyLevel.ADMIN)
        service_rl = ApiKeyLevel.default_rate_limit(ApiKeyLevel.SERVICE)
        read_rl = ApiKeyLevel.default_rate_limit(ApiKeyLevel.READ)
        monitor_rl = ApiKeyLevel.default_rate_limit(ApiKeyLevel.MONITOR)

        # admin 配额最高
        assert admin_rl["per_minute"] >= service_rl["per_minute"]
        assert service_rl["per_minute"] >= read_rl["per_minute"]
        assert read_rl["per_minute"] >= monitor_rl["per_minute"]


# ===========================================================================
# QuotaManager 测试
# ===========================================================================

class TestQuotaManager:
    """配额管理器测试"""

    def test_basic_quota_check(self):
        """基础配额检查和消耗"""
        from shared.core.auth.api_key_manager import QuotaManager, QuotaConfig
        qm = QuotaManager()
        quota = QuotaConfig(per_minute=5, per_hour=0, per_day=0, per_month=0)

        # 连续 5 次应该都通过
        for i in range(5):
            allowed, reason, remaining = qm.check_and_consume("key1", quota)
            assert allowed is True, f"第 {i+1} 次应该通过"
            assert reason == ""

        # 第 6 次应该被拒绝
        allowed, reason, remaining = qm.check_and_consume("key1", quota)
        assert allowed is False
        assert "minute" in reason

    def test_multiple_keys_independent(self):
        """多个 Key 的配额相互独立"""
        from shared.core.auth.api_key_manager import QuotaManager, QuotaConfig
        qm = QuotaManager()
        quota = QuotaConfig(per_minute=3, per_hour=0, per_day=0, per_month=0)

        # key1 用满
        for _ in range(3):
            qm.check_and_consume("key1", quota)

        # key2 仍然有配额
        allowed, _, _ = qm.check_and_consume("key2", quota)
        assert allowed is True

    def test_no_limit_when_zero(self):
        """配额为 0 时表示不限制"""
        from shared.core.auth.api_key_manager import QuotaManager, QuotaConfig
        qm = QuotaManager()
        quota = QuotaConfig(per_minute=0, per_hour=0, per_day=0, per_month=0)

        # 多次调用都应通过
        for i in range(100):
            allowed, reason, remaining = qm.check_and_consume("key1", quota)
            assert allowed is True
            assert remaining["per_minute"] == -1  # -1 表示无限制

    def test_reset_key(self):
        """重置指定 Key 的配额"""
        from shared.core.auth.api_key_manager import QuotaManager, QuotaConfig
        qm = QuotaManager()
        quota = QuotaConfig(per_minute=2, per_hour=0, per_day=0, per_month=0)

        qm.check_and_consume("key1", quota)
        qm.check_and_consume("key1", quota)

        # 重置后应该恢复
        qm.reset_key("key1")
        allowed, _, _ = qm.check_and_consume("key1", quota)
        assert allowed is True

    def test_get_usage(self):
        """获取配额使用情况"""
        from shared.core.auth.api_key_manager import QuotaManager, QuotaConfig
        qm = QuotaManager()
        quota = QuotaConfig(per_minute=10, per_hour=100, per_day=0, per_month=0)

        for _ in range(3):
            qm.check_and_consume("key1", quota)

        usage = qm.get_usage("key1")
        assert usage is not None
        assert usage["minute"]["count"] == 3
        assert usage["hour"]["count"] == 3

    def test_cleanup_expired(self):
        """清理过期配额记录"""
        from shared.core.auth.api_key_manager import QuotaManager, QuotaConfig
        qm = QuotaManager()
        quota = QuotaConfig(per_minute=5, per_hour=0, per_day=0, per_month=0)

        # 创建一些使用记录
        for _ in range(3):
            qm.check_and_consume("active_key", quota)

        # 手动设置一个过期的记录（模拟）
        old_usage = qm._usage["active_key"]
        old_usage.day_window = time.time() - 3 * 24 * 3600  # 3 天前

        removed = qm.cleanup_expired()
        assert removed >= 1


# ===========================================================================
# ApiKeyCache 测试
# ===========================================================================

class TestApiKeyCache:
    """内存缓存测试"""

    def _make_info(self, key_hash="test_hash", prefix="yx-test"):
        from shared.core.auth.api_key_manager import ManagedApiKeyInfo, ApiKeyLevel, QuotaConfig
        return ManagedApiKeyInfo(
            key_id="test-id",
            key_hash=key_hash,
            key_name="test-key",
            key_prefix=prefix,
            level=ApiKeyLevel.SERVICE,
            quota=QuotaConfig(),
        )

    def test_put_and_get(self):
        """基本的写入和读取"""
        from shared.core.auth.api_key_manager import ApiKeyCache
        cache = ApiKeyCache(max_size=10, ttl_seconds=60)
        info = self._make_info("hash1")

        cache.put("hash1", info)
        result = cache.get("hash1")
        assert result is not None
        assert result.key_hash == "hash1"
        assert result.key_name == "test-key"

    def test_get_missing(self):
        """获取不存在的 Key 返回 None"""
        from shared.core.auth.api_key_manager import ApiKeyCache
        cache = ApiKeyCache(max_size=10, ttl_seconds=60)
        assert cache.get("nonexistent") is None

    def test_invalidate(self):
        """使缓存失效"""
        from shared.core.auth.api_key_manager import ApiKeyCache
        cache = ApiKeyCache(max_size=10, ttl_seconds=60)
        info = self._make_info("hash1")

        cache.put("hash1", info)
        assert cache.get("hash1") is not None

        cache.invalidate("hash1")
        assert cache.get("hash1") is None

    def test_lru_eviction(self):
        """LRU 淘汰策略"""
        from shared.core.auth.api_key_manager import ApiKeyCache
        cache = ApiKeyCache(max_size=3, ttl_seconds=60)

        for i in range(5):
            info = self._make_info(f"hash{i}")
            cache.put(f"hash{i}", info)

        assert cache.size() == 3
        # 最早的应该被淘汰
        assert cache.get("hash0") is None
        assert cache.get("hash1") is None
        # 最新的应该还在
        assert cache.get("hash4") is not None

    def test_ttl_expiry(self):
        """TTL 过期"""
        from shared.core.auth.api_key_manager import ApiKeyCache
        cache = ApiKeyCache(max_size=10, ttl_seconds=1)  # 1 秒过期
        info = self._make_info("hash1")

        cache.put("hash1", info)
        assert cache.get("hash1") is not None

        # 手动调整时间（模拟过期）
        cache._cache["hash1"] = (info, time.time() - 2)
        assert cache.get("hash1") is None

    def test_clear(self):
        """清空缓存"""
        from shared.core.auth.api_key_manager import ApiKeyCache
        cache = ApiKeyCache(max_size=10, ttl_seconds=60)

        for i in range(5):
            info = self._make_info(f"hash{i}")
            cache.put(f"hash{i}", info)

        assert cache.size() == 5
        cache.clear()
        assert cache.size() == 0


# ===========================================================================
# SqliteApiKeyStore 测试
# ===========================================================================

class TestSqliteApiKeyStore:
    """SQLite 持久化存储测试"""

    def test_table_creation(self):
        """表结构自动创建"""
        from shared.core.auth.api_key_manager import SqliteApiKeyStore
        db_manager, tmp_dir = _create_temp_db_manager()
        store = SqliteApiKeyStore(db_manager=db_manager, db_name="test_auth")

        # 检查表存在
        row = db_manager.query_one(
            "test_auth",
            "SELECT name FROM sqlite_master WHERE type='table' AND name='api_keys'",
        )
        assert row is not None
        assert row["name"] == "api_keys"

    def test_add_and_find_by_id(self):
        """添加和按 ID 查找"""
        from shared.core.auth.api_key_manager import (
            SqliteApiKeyStore, ManagedApiKeyInfo, ApiKeyLevel, QuotaConfig,
        )
        db_manager, tmp_dir = _create_temp_db_manager()
        store = SqliteApiKeyStore(db_manager=db_manager, db_name="test_auth")

        info = ManagedApiKeyInfo(
            key_id="test-001",
            key_hash="hash_test_001",
            key_name="测试 Key",
            key_prefix="yx-test-",
            level=ApiKeyLevel.SERVICE,
            owner="user1",
            scopes=["read", "write"],
            quota=QuotaConfig(per_minute=100, per_hour=1000, per_day=10000, per_month=0),
            description="测试用 Key",
        )

        store.add_managed_key(info)
        found = store.find_by_id("test-001")

        assert found is not None
        assert found.key_id == "test-001"
        assert found.key_name == "测试 Key"
        assert found.level == ApiKeyLevel.SERVICE
        assert found.owner == "user1"
        assert found.scopes == ["read", "write"]
        assert found.quota.per_minute == 100
        assert found.status == "active"

    def test_find_by_hash(self):
        """按哈希查找"""
        from shared.core.auth.api_key_manager import (
            SqliteApiKeyStore, ManagedApiKeyInfo, ApiKeyLevel, QuotaConfig,
        )
        db_manager, tmp_dir = _create_temp_db_manager()
        store = SqliteApiKeyStore(db_manager=db_manager, db_name="test_auth")

        info = ManagedApiKeyInfo(
            key_id="test-002",
            key_hash="unique_hash_002",
            key_name="hash-test",
            key_prefix="yx-hash",
            level=ApiKeyLevel.READ,
            quota=QuotaConfig(),
        )

        store.add_managed_key(info)
        found = store.find_managed_by_hash("unique_hash_002")

        assert found is not None
        assert found.key_id == "test-002"

    def test_list_keys_with_filters(self):
        """按条件筛选列表"""
        from shared.core.auth.api_key_manager import (
            SqliteApiKeyStore, ManagedApiKeyInfo, ApiKeyLevel, QuotaConfig,
        )
        db_manager, tmp_dir = _create_temp_db_manager()
        store = SqliteApiKeyStore(db_manager=db_manager, db_name="test_auth")

        # 创建多个不同级别的 Key
        for i, level in enumerate([ApiKeyLevel.ADMIN, ApiKeyLevel.SERVICE, ApiKeyLevel.READ]):
            info = ManagedApiKeyInfo(
                key_id=f"key-{i}",
                key_hash=f"hash-{i}",
                key_name=f"key-{level.value}",
                key_prefix=f"yx-{level.value}-",
                level=level,
                owner="team-a" if i < 2 else "team-b",
                quota=QuotaConfig(),
            )
            store.add_managed_key(info)

        # 按级别筛选
        service_keys = store.list_keys(level=ApiKeyLevel.SERVICE)
        assert len(service_keys) == 1
        assert service_keys[0].level == ApiKeyLevel.SERVICE

        # 按所有者筛选
        team_a_keys = store.list_keys(owner="team-a")
        assert len(team_a_keys) == 2

        # 计数
        total = store.count_keys()
        assert total == 3
        admin_count = store.count_keys(level=ApiKeyLevel.ADMIN)
        assert admin_count == 1

    def test_update_key(self):
        """更新 Key 信息"""
        from shared.core.auth.api_key_manager import (
            SqliteApiKeyStore, ManagedApiKeyInfo, ApiKeyLevel, QuotaConfig,
        )
        db_manager, tmp_dir = _create_temp_db_manager()
        store = SqliteApiKeyStore(db_manager=db_manager, db_name="test_auth")

        info = ManagedApiKeyInfo(
            key_id="update-test",
            key_hash="hash-update",
            key_name="原始名称",
            key_prefix="yx-upd-",
            level=ApiKeyLevel.SERVICE,
            quota=QuotaConfig(),
        )
        store.add_managed_key(info)

        # 更新名称和状态
        success = store.update_key("update-test", {
            "key_name": "更新后的名称",
            "status": "revoked",
        })
        assert success is True

        updated = store.find_by_id("update-test")
        assert updated.key_name == "更新后的名称"
        assert updated.status == "revoked"

    def test_increment_usage(self):
        """增加使用计数"""
        from shared.core.auth.api_key_manager import (
            SqliteApiKeyStore, ManagedApiKeyInfo, ApiKeyLevel, QuotaConfig,
        )
        from shared.core.auth.api_key import ApiKeyInfo
        db_manager, tmp_dir = _create_temp_db_manager()
        store = SqliteApiKeyStore(db_manager=db_manager, db_name="test_auth")

        info = ManagedApiKeyInfo(
            key_id="usage-test",
            key_hash="hash-usage",
            key_name="usage-test",
            key_prefix="yx-usa-",
            level=ApiKeyLevel.SERVICE,
            quota=QuotaConfig(),
        )
        store.add_managed_key(info)

        # 使用基类接口增加计数
        base_info = info.to_api_key_info()
        store.increment_usage(base_info)
        store.increment_usage(base_info)

        found = store.find_by_id("usage-test")
        assert found.call_count == 2
        assert found.last_used_at is not None


# ===========================================================================
# ApiKeyManager 核心功能测试
# ===========================================================================

class TestApiKeyManager:
    """API Key 管理中心核心测试"""

    # -------------------------------------------------------------------
    # 创建 Key
    # -------------------------------------------------------------------

    def test_create_key_basic(self):
        """基本创建 Key"""
        manager, tmp_dir = _create_test_manager()

        api_key, key_info = manager.create_key(
            name="test-service",
            level=manager._store and __import__('shared.core.auth.api_key_manager', fromlist=['ApiKeyLevel']).ApiKeyLevel.SERVICE,
            owner="team-a",
            description="测试服务 Key",
        )

        assert api_key is not None
        assert len(api_key) > 10
        assert api_key.startswith("yx-")
        assert key_info.key_name == "test-service"
        assert key_info.owner == "team-a"
        assert key_info.status == "active"
        assert key_info.key_prefix == api_key[:8]
        assert key_info.key_id is not None

    def test_create_key_different_levels(self):
        """创建不同级别的 Key"""
        from shared.core.auth.api_key_manager import ApiKeyLevel
        manager, tmp_dir = _create_test_manager()

        for level in [ApiKeyLevel.ADMIN, ApiKeyLevel.SERVICE, ApiKeyLevel.READ, ApiKeyLevel.MONITOR]:
            api_key, key_info = manager.create_key(
                name=f"key-{level.value}",
                level=level,
            )
            assert key_info.level == level
            assert len(key_info.scopes) > 0

    def test_create_key_custom_scopes(self):
        """自定义权限范围"""
        from shared.core.auth.api_key_manager import ApiKeyLevel
        manager, tmp_dir = _create_test_manager()

        api_key, key_info = manager.create_key(
            name="custom-scopes",
            level=ApiKeyLevel.SERVICE,
            scopes=["custom:read", "custom:write"],
        )
        assert key_info.scopes == ["custom:read", "custom:write"]

    def test_create_key_custom_rate_limit(self):
        """自定义限流配置"""
        from shared.core.auth.api_key_manager import ApiKeyLevel
        manager, tmp_dir = _create_test_manager()

        api_key, key_info = manager.create_key(
            name="custom-rl",
            level=ApiKeyLevel.SERVICE,
            rate_limit={"per_minute": 50, "per_hour": 500, "per_day": 5000, "per_month": 100000},
        )
        assert key_info.quota.per_minute == 50
        assert key_info.quota.per_hour == 500
        assert key_info.quota.per_day == 5000
        assert key_info.quota.per_month == 100000

    # -------------------------------------------------------------------
    # 验证 Key
    # -------------------------------------------------------------------

    def test_verify_key_success(self):
        """验证有效 Key"""
        from shared.core.auth.api_key_manager import ApiKeyLevel
        manager, tmp_dir = _create_test_manager()

        api_key, key_info = manager.create_key(
            name="verify-test",
            level=ApiKeyLevel.SERVICE,
        )

        result = manager.verify_key(api_key)
        assert result is not None
        assert result.key_id == key_info.key_id
        assert result.key_name == "verify-test"
        assert result.call_count == 1  # 验证成功后计数 +1

    def test_verify_key_invalid(self):
        """验证无效 Key"""
        manager, tmp_dir = _create_test_manager()

        result = manager.verify_key("invalid-key-xxxx")
        assert result is None

    def test_verify_key_with_level_check(self):
        """带级别检查的验证"""
        from shared.core.auth.api_key_manager import ApiKeyLevel
        manager, tmp_dir = _create_test_manager()

        # 创建 read 级 Key
        read_key, _ = manager.create_key(
            name="read-key",
            level=ApiKeyLevel.READ,
        )

        # read 级别可以访问 read 级资源
        result = manager.verify_key(read_key, required_level=ApiKeyLevel.READ)
        assert result is not None

        # read 级别不能访问 service 级资源
        result = manager.verify_key(read_key, required_level=ApiKeyLevel.SERVICE)
        assert result is None

        # 创建 admin 级 Key
        admin_key, _ = manager.create_key(
            name="admin-key",
            level=ApiKeyLevel.ADMIN,
        )

        # admin 级别可以访问 service 级资源
        result = manager.verify_key(admin_key, required_level=ApiKeyLevel.SERVICE)
        assert result is not None

    def test_verify_key_with_scope_check(self):
        """带权限范围检查的验证"""
        from shared.core.auth.api_key_manager import ApiKeyLevel
        manager, tmp_dir = _create_test_manager()

        api_key, _ = manager.create_key(
            name="scope-test",
            level=ApiKeyLevel.SERVICE,
            scopes=["data:read", "data:write"],
        )

        # 有 read 权限
        result = manager.verify_key(api_key, required_scopes=["data:read"])
        assert result is not None

        # 缺少 delete 权限
        result = manager.verify_key(api_key, required_scopes=["data:delete"])
        assert result is None

        # 通配符
        admin_key, _ = manager.create_key(
            name="admin-scope",
            level=ApiKeyLevel.ADMIN,
        )
        result = manager.verify_key(admin_key, required_scopes=["anything"])
        assert result is not None

    def test_verify_revoked_key(self):
        """验证已吊销的 Key"""
        from shared.core.auth.api_key_manager import ApiKeyLevel
        manager, tmp_dir = _create_test_manager()

        api_key, key_info = manager.create_key(
            name="revoke-test",
            level=ApiKeyLevel.SERVICE,
        )

        # 先验证通过
        assert manager.verify_key(api_key) is not None

        # 吊销
        manager.revoke_key(key_info.key_id, reason="测试吊销")

        # 再验证应该失败
        assert manager.verify_key(api_key) is None

    def test_verify_expired_key(self):
        """验证已过期的 Key"""
        from shared.core.auth.api_key_manager import ApiKeyLevel
        manager, tmp_dir = _create_test_manager()

        past_time = datetime.now(tz=timezone.utc) - timedelta(hours=1)
        api_key, _ = manager.create_key(
            name="expired-test",
            level=ApiKeyLevel.SERVICE,
            expires_at=past_time,
        )

        result = manager.verify_key(api_key)
        assert result is None

    # -------------------------------------------------------------------
    # 吊销 Key
    # -------------------------------------------------------------------

    def test_revoke_key(self):
        """吊销 Key"""
        from shared.core.auth.api_key_manager import ApiKeyLevel
        manager, tmp_dir = _create_test_manager()

        api_key, key_info = manager.create_key(
            name="revoke-test",
            level=ApiKeyLevel.SERVICE,
        )

        success = manager.revoke_key(key_info.key_id, reason="测试吊销")
        assert success is True

        revoked = manager.get_key(key_info.key_id)
        assert revoked.status == "revoked"
        assert revoked.extra.get("revoke_reason") == "测试吊销"

    def test_revoke_nonexistent_key(self):
        """吊销不存在的 Key"""
        manager, tmp_dir = _create_test_manager()
        success = manager.revoke_key("nonexistent-id")
        assert success is False

    # -------------------------------------------------------------------
    # 轮换 Key
    # -------------------------------------------------------------------

    def test_rotate_key(self):
        """轮换 Key"""
        from shared.core.auth.api_key_manager import ApiKeyLevel
        manager, tmp_dir = _create_test_manager()

        old_api_key, old_key_info = manager.create_key(
            name="rotate-test",
            level=ApiKeyLevel.SERVICE,
            owner="team-a",
            scopes=["read", "write"],
        )

        # 轮换
        new_api_key, new_key_info = manager.rotate_key(old_key_info.key_id, grace_days=3)

        assert new_api_key is not None
        assert new_api_key != old_api_key
        assert new_key_info.level == ApiKeyLevel.SERVICE
        assert new_key_info.owner == "team-a"
        assert new_key_info.rotation_of == old_key_info.key_id

        # 旧 Key 状态变为 rotated
        old_updated = manager.get_key(old_key_info.key_id)
        assert old_updated.status == "rotated"
        assert old_updated.expires_at is not None

        # 新 Key 可以验证通过
        assert manager.verify_key(new_api_key) is not None

        # 旧 Key 在宽限期内仍可使用
        assert manager.verify_key(old_api_key) is not None

    def test_rotate_revoked_key_fails(self):
        """轮换已吊销的 Key 应该失败"""
        from shared.core.auth.api_key_manager import ApiKeyLevel
        manager, tmp_dir = _create_test_manager()

        _, key_info = manager.create_key(
            name="rotate-fail",
            level=ApiKeyLevel.SERVICE,
        )
        manager.revoke_key(key_info.key_id)

        with pytest.raises(ValueError, match="无法轮换"):
            manager.rotate_key(key_info.key_id)

    # -------------------------------------------------------------------
    # 列表与查询
    # -------------------------------------------------------------------

    def test_list_keys_pagination(self):
        """Key 列表分页"""
        from shared.core.auth.api_key_manager import ApiKeyLevel
        manager, tmp_dir = _create_test_manager()

        # 创建 15 个 Key
        for i in range(15):
            manager.create_key(
                name=f"key-{i}",
                level=ApiKeyLevel.SERVICE,
            )

        # 第一页
        keys_page1, total = manager.list_keys(page=1, page_size=10)
        assert total == 15
        assert len(keys_page1) == 10

        # 第二页
        keys_page2, total = manager.list_keys(page=2, page_size=10)
        assert len(keys_page2) == 5

    def test_list_keys_filters(self):
        """Key 列表筛选"""
        from shared.core.auth.api_key_manager import ApiKeyLevel
        manager, tmp_dir = _create_test_manager()

        manager.create_key(name="admin1", level=ApiKeyLevel.ADMIN, owner="ops")
        manager.create_key(name="admin2", level=ApiKeyLevel.ADMIN, owner="ops")
        manager.create_key(name="svc1", level=ApiKeyLevel.SERVICE, owner="dev")
        manager.create_key(name="read1", level=ApiKeyLevel.READ, owner="dev")

        # 按级别筛选
        admin_keys, total = manager.list_keys(level=ApiKeyLevel.ADMIN)
        assert total == 2

        # 按所有者筛选
        dev_keys, total = manager.list_keys(owner="dev")
        assert total == 2

        # 组合筛选
        dev_read_keys, total = manager.list_keys(owner="dev", level=ApiKeyLevel.READ)
        assert total == 1

    # -------------------------------------------------------------------
    # 更新 Key
    # -------------------------------------------------------------------

    def test_update_key_config(self):
        """更新 Key 配置"""
        from shared.core.auth.api_key_manager import ApiKeyLevel
        manager, tmp_dir = _create_test_manager()

        _, key_info = manager.create_key(
            name="update-test",
            level=ApiKeyLevel.SERVICE,
            owner="old-owner",
        )

        updated = manager.update_key(
            key_info.key_id,
            name="new-name",
            owner="new-owner",
            description="新描述",
        )

        assert updated is not None
        assert updated.key_name == "new-name"
        assert updated.owner == "new-owner"
        assert updated.description == "新描述"

    # -------------------------------------------------------------------
    # 导入 Key
    # -------------------------------------------------------------------

    def test_import_key(self):
        """导入已有 Key"""
        from shared.core.auth.api_key_manager import ApiKeyLevel
        manager, tmp_dir = _create_test_manager()

        imported = manager.import_key({
            "key_hash": "imported_hash_123",
            "key_name": "imported-key",
            "level": "service",
            "owner": "import-team",
            "scopes": ["read"],
            "description": "导入的 Key",
        })

        assert imported.key_id is not None
        assert imported.key_name == "imported-key"
        assert imported.level == ApiKeyLevel.SERVICE
        assert imported.owner == "import-team"
        assert imported.status == "active"

        # 可以通过哈希找到
        found = manager._store.find_managed_by_hash("imported_hash_123")
        assert found is not None

    def test_import_duplicate_hash_fails(self):
        """导入重复哈希应该失败"""
        manager, tmp_dir = _create_test_manager()

        manager.import_key({
            "key_hash": "duplicate_hash",
            "key_name": "first",
        })

        with pytest.raises(ValueError, match="已存在"):
            manager.import_key({
                "key_hash": "duplicate_hash",
                "key_name": "second",
            })

    # -------------------------------------------------------------------
    # 统计信息
    # -------------------------------------------------------------------

    def test_get_key_stats(self):
        """获取统计信息"""
        from shared.core.auth.api_key_manager import ApiKeyLevel
        manager, tmp_dir = _create_test_manager()

        manager.create_key(name="k1", level=ApiKeyLevel.ADMIN)
        manager.create_key(name="k2", level=ApiKeyLevel.SERVICE)
        api_key3, info3 = manager.create_key(name="k3", level=ApiKeyLevel.READ)
        manager.revoke_key(info3.key_id)

        stats = manager.get_key_stats()
        assert stats["total"] == 3
        assert stats["active"] == 2
        assert stats["revoked"] == 1
        assert "by_level" in stats
        assert stats["by_level"]["admin"] == 1
        assert stats["by_level"]["service"] == 1

    def test_get_usage_stats(self):
        """获取使用量统计"""
        from shared.core.auth.api_key_manager import ApiKeyLevel
        manager, tmp_dir = _create_test_manager()

        api_key, _ = manager.create_key(name="usage-stats-test", level=ApiKeyLevel.SERVICE)

        # 调用几次
        for _ in range(5):
            manager.verify_key(api_key)

        usage_stats = manager.get_usage_stats()
        assert usage_stats["total_calls"] >= 5
        assert len(usage_stats["top_keys"]) > 0
        assert usage_stats["top_keys"][0]["call_count"] >= 5

    # -------------------------------------------------------------------
    # 默认 Key 初始化
    # -------------------------------------------------------------------

    def test_ensure_default_key_first_time(self):
        """首次初始化默认 Key"""
        manager, tmp_dir = _create_test_manager()

        default_key = manager.ensure_default_key(
            name="default-admin-key",
            owner="system",
        )

        assert default_key is not None
        assert len(default_key) > 10
        assert default_key.startswith("yx-")

    def test_ensure_default_key_second_time(self):
        """第二次调用不生成新 Key"""
        manager, tmp_dir = _create_test_manager()

        key1 = manager.ensure_default_key()
        key2 = manager.ensure_default_key()

        assert key1 is not None
        assert key2 is None  # 第二次返回 None

    def test_ensure_default_key_force_reset(self):
        """强制重置默认 Key"""
        manager, tmp_dir = _create_test_manager()

        key1 = manager.ensure_default_key()
        key2 = manager.ensure_default_key(force_reset=True)

        assert key1 is not None
        assert key2 is not None
        assert key1 != key2

    # -------------------------------------------------------------------
    # 配额限流
    # -------------------------------------------------------------------

    def test_rate_limit_minute(self):
        """分钟级限流"""
        from shared.core.auth.api_key_manager import ApiKeyLevel
        manager, tmp_dir = _create_test_manager()

        api_key, _ = manager.create_key(
            name="rate-limit-test",
            level=ApiKeyLevel.SERVICE,
            rate_limit={"per_minute": 3, "per_hour": 0, "per_day": 0, "per_month": 0},
        )

        # 前 3 次通过
        for i in range(3):
            result = manager.verify_key(api_key)
            assert result is not None, f"第 {i+1} 次应该通过"

        # 第 4 次被拒绝
        result = manager.verify_key(api_key)
        assert result is None

    def test_check_quota(self):
        """检查配额使用情况"""
        from shared.core.auth.api_key_manager import ApiKeyLevel
        manager, tmp_dir = _create_test_manager()

        api_key, key_info = manager.create_key(
            name="check-quota-test",
            level=ApiKeyLevel.SERVICE,
            rate_limit={"per_minute": 10, "per_hour": 100, "per_day": 0, "per_month": 0},
        )

        for _ in range(3):
            manager.verify_key(api_key)

        quota_info = manager.check_quota(api_key)
        assert quota_info is not None
        assert quota_info["key_id"] == key_info.key_id
        assert quota_info["quota"]["per_minute"] == 10

    # -------------------------------------------------------------------
    # 清理维护
    # -------------------------------------------------------------------

    def test_cleanup_marks_expired(self):
        """清理时标记已过期的 Key"""
        from shared.core.auth.api_key_manager import ApiKeyLevel
        manager, tmp_dir = _create_test_manager()

        # 创建一个已过期的 Key（通过直接操作数据库模拟）
        past = datetime.now(tz=timezone.utc) - timedelta(days=1)
        _, key_info = manager.create_key(
            name="expired-cleanup",
            level=ApiKeyLevel.SERVICE,
            expires_at=past,
        )

        # 执行清理
        result = manager.cleanup()
        assert result["expired_marked"] >= 1

        # Key 状态应为 expired
        updated = manager.get_key(key_info.key_id)
        assert updated.status == "expired"


# ===========================================================================
# ServiceCaller 测试
# ===========================================================================

class TestServiceCaller:
    """服务间调用 SDK 测试"""

    def test_create_caller(self):
        """创建 ServiceCaller 实例"""
        from shared.core.auth.service_caller import ServiceCaller, RetryConfig

        caller = ServiceCaller(
            api_key="yx-test-key-12345",
            base_url="http://localhost:8000",
            timeout=10.0,
        )

        assert caller._api_key == "yx-test-key-12345"
        assert caller._base_url == "http://localhost:8000"
        assert caller._timeout == 10.0

    def test_create_caller_empty_key_fails(self):
        """空 Key 创建失败"""
        from shared.core.auth.service_caller import ServiceCaller

        with pytest.raises(ValueError, match="不能为空"):
            ServiceCaller(api_key="")

    def test_build_url(self):
        """URL 构建"""
        from shared.core.auth.service_caller import ServiceCaller

        caller = ServiceCaller(
            api_key="yx-test",
            base_url="http://api.example.com/v1",
        )

        assert caller._build_url("/users") == "http://api.example.com/v1/users"
        assert caller._build_url("users") == "http://api.example.com/v1/users"
        assert caller._build_url("http://other.com/path") == "http://other.com/path"

    def test_retry_config_defaults(self):
        """重试配置默认值"""
        from shared.core.auth.service_caller import RetryConfig

        config = RetryConfig()
        assert config.max_retries == 3
        assert config.base_delay == 0.5
        assert 429 in config.retry_on_status
        assert 500 in config.retry_on_status

    def test_call_stats_initial(self):
        """初始统计状态"""
        from shared.core.auth.service_caller import ServiceCaller

        caller = ServiceCaller(api_key="yx-test")
        stats = caller.get_stats()
        assert stats["total_calls"] == 0
        assert stats["success_calls"] == 0
        assert stats["failed_calls"] == 0
        assert stats["success_rate"] == 0.0

    def test_create_service_caller_factory(self):
        """工厂函数创建"""
        from shared.core.auth.service_caller import create_service_caller

        caller = create_service_caller(
            api_key="yx-test",
            base_url="http://localhost:8000",
            max_retries=5,
            timeout=15.0,
        )

        assert caller is not None
        assert caller._retry_config.max_retries == 5
        assert caller._timeout == 15.0


# ===========================================================================
# FastAPI Router 测试
# ===========================================================================

class TestApiKeyRouter:
    """API Key 管理 Router 测试"""

    def test_router_creation(self):
        """创建 Router"""
        from shared.core.auth.api_key_router import is_fastapi_available
        if not is_fastapi_available():
            pytest.skip("FastAPI 不可用")

        from shared.core.auth.api_key_router import create_api_key_router
        from shared.core.auth.api_key_manager import ApiKeyLevel

        manager, tmp_dir = _create_test_manager()
        router = create_api_key_router(manager, require_admin=False)

        assert router is not None
        # 检查路由数量
        routes = [r.path for r in router.routes]
        assert any("api-keys" in r or r == "" for r in routes) or len(routes) > 0

    def test_router_with_admin_enabled(self):
        """启用管理员认证的 Router"""
        from shared.core.auth.api_key_router import is_fastapi_available
        if not is_fastapi_available():
            pytest.skip("FastAPI 不可用")

        from shared.core.auth.api_key_router import create_api_key_router

        manager, tmp_dir = _create_test_manager()
        router = create_api_key_router(manager, require_admin=True)

        assert router is not None

    def test_router_endpoint_count(self):
        """检查 Router 包含的端点数量"""
        from shared.core.auth.api_key_router import is_fastapi_available
        if not is_fastapi_available():
            pytest.skip("FastAPI 不可用")

        from shared.core.auth.api_key_router import create_api_key_router

        manager, tmp_dir = _create_test_manager()
        router = create_api_key_router(manager, require_admin=False)

        # 应该有多个路由端点
        route_paths = [r.path for r in router.routes if hasattr(r, 'path')]
        # 至少包含创建、列表、详情、更新、删除、轮换等端点
        assert len(route_paths) >= 8


# ===========================================================================
# 向后兼容测试
# ===========================================================================

class TestBackwardCompatibility:
    """向后兼容性测试"""

    def test_existing_api_key_module_unchanged(self):
        """现有 api_key 模块功能不受影响"""
        from shared.core.auth.api_key import (
            generate_api_key, hash_api_key_sha256, verify_api_key_hash,
            mask_api_key, ApiKeyInfo, InMemoryApiKeyStore, ApiKeyValidator,
        )

        # 生成和哈希
        key = generate_api_key()
        assert key.startswith("yx-")

        key_hash = hash_api_key_sha256(key)
        assert len(key_hash) == 64

        assert verify_api_key_hash(key, key_hash, use_bcrypt=False) is True
        assert verify_api_key_hash("wrong", key_hash, use_bcrypt=False) is False

        # 脱敏
        masked = mask_api_key(key)
        assert "*" in masked
        assert masked.startswith(key[:6])

        # 内存存储
        store = InMemoryApiKeyStore()
        info = ApiKeyInfo(key_hash=key_hash, key_name="test", roles=["admin"])
        store.add_key(info)
        assert len(store.get_all_active()) == 1

        # 验证器
        validator = ApiKeyValidator(store, use_bcrypt=False)
        result = validator.validate_sha256_fast(key)
        assert result is not None
        assert result.key_name == "test"

    def test_init_exports_all_old_apis(self):
        """__init__.py 仍然导出所有旧 API"""
        from shared.core.auth import (
            # 旧版 API
            hash_api_key, verify_api_key, is_public_path,
            generate_api_key, mask_api_key, DEFAULT_PUBLIC_PATHS,
            SimpleRateLimiter, create_api_key_dependency,
            # 新版 API
            ApiKeyInfo, ApiKeyStore, InMemoryApiKeyStore, ApiKeyValidator,
            # RBAC
            ROLE_ADMIN, has_role,
            # JWT
            JWTHandler, JWTConfig,
        )

        # 确保都可以调用
        assert callable(hash_api_key)
        assert callable(verify_api_key)
        assert callable(generate_api_key)
        assert callable(mask_api_key)
        assert len(DEFAULT_PUBLIC_PATHS) > 0
        assert SimpleRateLimiter is not None

    def test_new_manager_exports(self):
        """新模块导出正确"""
        from shared.core.auth import (
            ApiKeyLevel,
            ApiKeyManager,
            get_api_key_manager,
            ManagedApiKeyInfo,
            QuotaConfig,
            SqliteApiKeyStore,
        )

        assert ApiKeyLevel.ADMIN.value == "admin"
        assert ApiKeyManager is not None
        assert callable(get_api_key_manager)


# ===========================================================================
# 主入口
# ===========================================================================

if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
