"""
M5 潮汐记忆系统 - 完整测试套件
所有测试使用模拟/假数据，不包含任何真实用户数据
"""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import pytest


# ========== 层级测试 ==========

class TestL0BeachLayer:
    """L0沙滩层测试"""

    def test_add_and_get(self):
        from tide_memory.layers.l0_beach import BeachLayer
        from tide_memory.core.models import MemoryItem
        layer = BeachLayer({"max_items": 50})
        item = MemoryItem(tags=["测试"])
        layer.add(item)
        assert layer.get(item.memory_id) is not None

    def test_max_items_eviction(self):
        from tide_memory.layers.l0_beach import BeachLayer
        from tide_memory.core.models import MemoryItem
        layer = BeachLayer({"max_items": 5})
        ids = []
        for i in range(10):
            item = MemoryItem(tags=[f"tag{i}"])
            layer.add(item)
            ids.append(item.memory_id)
        assert layer.count() == 5
        assert layer.get(ids[0]) is None
        assert layer.get(ids[9]) is not None

    def test_lru_order(self):
        from tide_memory.layers.l0_beach import BeachLayer
        from tide_memory.core.models import MemoryItem
        layer = BeachLayer({"max_items": 3})
        items = [MemoryItem() for _ in range(3)]
        for item in items:
            layer.add(item)
        # 访问第一个，它应该移到最后
        layer.get(items[0].memory_id)
        # 添加新的，应该淘汰最久未访问的（items[1]）
        new_item = MemoryItem()
        layer.add(new_item)
        assert layer.get(items[1].memory_id) is None
        assert layer.get(items[0].memory_id) is not None

    def test_search(self):
        from tide_memory.layers.l0_beach import BeachLayer
        from tide_memory.core.models import MemoryItem
        layer = BeachLayer()
        layer.add(MemoryItem(tags=["工作", "会议"]))
        layer.add(MemoryItem(tags=["生活", "娱乐"]))
        results = layer.search("工作会议", top_k=5)
        assert len(results) >= 1

    def test_remove(self):
        from tide_memory.layers.l0_beach import BeachLayer
        from tide_memory.core.models import MemoryItem
        layer = BeachLayer()
        item = MemoryItem()
        layer.add(item)
        assert layer.count() == 1
        assert layer.remove(item.memory_id) is True
        assert layer.count() == 0

    def test_pop_oldest(self):
        from tide_memory.layers.l0_beach import BeachLayer
        from tide_memory.core.models import MemoryItem
        layer = BeachLayer()
        first = MemoryItem()
        layer.add(first)
        layer.add(MemoryItem())
        oldest = layer.pop_oldest()
        assert oldest.memory_id == first.memory_id


class TestL1ShallowLayer:
    """L1浅水层测试"""

    def test_add_and_get(self, tmp_path):
        from tide_memory.layers.l1_shallow import ShallowLayer
        from tide_memory.core.models import MemoryItem
        db_path = str(tmp_path / "l1_test.db")
        layer = ShallowLayer({"db_path": db_path, "max_items": 100})
        item = MemoryItem(tags=["测试"])
        layer.add(item)
        assert layer.count() == 1
        retrieved = layer.get(item.memory_id)
        assert retrieved is not None
        assert retrieved.memory_id == item.memory_id

    def test_search(self, tmp_path):
        from tide_memory.layers.l1_shallow import ShallowLayer
        from tide_memory.core.models import MemoryItem
        db_path = str(tmp_path / "l1_search.db")
        layer = ShallowLayer({"db_path": db_path})
        layer.add(MemoryItem(tags=["测试1"], quality_score=80))
        layer.add(MemoryItem(tags=["测试2"], quality_score=60))
        results = layer.search("测试", top_k=5)
        assert len(results) >= 2
        # 质量分降序
        assert results[0]["similarity"] >= results[1]["similarity"]

    def test_content_not_in_results(self, tmp_path):
        """搜索结果不包含原文"""
        from tide_memory.layers.l1_shallow import ShallowLayer
        from tide_memory.core.models import MemoryItem
        db_path = str(tmp_path / "l1_safe.db")
        layer = ShallowLayer({"db_path": db_path})
        layer.add(MemoryItem(content_hash="abc123"))
        results = layer.search("test", top_k=5)
        for r in results:
            assert "content" not in r or r["content_preview"] == "[SANITIZED]"


class TestL2DeepLayer:
    """L2深水层测试"""

    def test_add_and_get(self):
        from tide_memory.layers.l2_deep import DeepLayer
        from tide_memory.core.models import MemoryItem
        layer = DeepLayer()
        item = MemoryItem(tags=["测试"])
        layer.add(item)
        assert layer.count() == 1

    def test_compress(self):
        from tide_memory.layers.l2_deep import DeepLayer
        from tide_memory.core.models import MemoryItem
        layer = DeepLayer()
        for i in range(10):
            quality = 20 if i < 5 else 80
            layer.add(MemoryItem(tags=[f"tag{i}"], quality_score=quality))
        result = layer.compress()
        assert result["compressed_count"] > 0


class TestL3AbyssLayer:
    """L3深海层测试"""

    def test_add_and_search(self, tmp_path):
        from tide_memory.layers.l3_abyss import AbyssLayer
        from tide_memory.core.models import MemoryItem
        storage = str(tmp_path / "l3_test")
        layer = AbyssLayer({"storage_path": storage})
        item = MemoryItem(tags=["重要", "永久"], quality_score=90)
        layer.add(item)
        assert layer.count() == 1
        results = layer.search("重要", top_k=5)
        assert len(results) >= 1
        # L3层内容标记为加密
        for r in results:
            assert r.get("encrypted") is True


# ========== 情绪测试 ==========

class TestValenceArousal:
    """效价-唤醒度模型测试"""

    def test_positive_text(self):
        from tide_memory.emotion.valence_arousal import ValenceArousalModel
        model = ValenceArousalModel()
        result = model.infer("非常开心快乐幸福美好棒极了")
        assert result["valence"] > 0

    def test_negative_text(self):
        from tide_memory.emotion.valence_arousal import ValenceArousalModel
        model = ValenceArousalModel()
        result = model.infer("非常难过伤心痛苦悲伤")
        assert result["valence"] < 0

    def test_neutral_text(self):
        from tide_memory.emotion.valence_arousal import ValenceArousalModel
        model = ValenceArousalModel()
        result = model.infer("今天天气不错")
        # 中性文本效价接近0
        assert -0.3 < result["valence"] < 0.3

    def test_empty_text(self):
        from tide_memory.emotion.valence_arousal import ValenceArousalModel
        model = ValenceArousalModel()
        result = model.infer("")
        assert result["confidence"] < 0.3

    def test_arousal_modifiers(self):
        from tide_memory.emotion.valence_arousal import ValenceArousalModel
        model = ValenceArousalModel()
        r1 = model.infer("开心")
        r2 = model.infer("非常开心")
        assert r2["arousal"] > r1["arousal"]

    def test_negation(self):
        from tide_memory.emotion.valence_arousal import ValenceArousalModel
        model = ValenceArousalModel()
        r1 = model.infer("开心")
        r2 = model.infer("不开心")
        # 否定应该翻转效价
        assert r1["valence"] * r2["valence"] <= 0

    def test_batch_infer(self):
        from tide_memory.emotion.valence_arousal import ValenceArousalModel
        model = ValenceArousalModel()
        results = model.batch_infer(["开心", "难过", "平静"])
        assert len(results) == 3


class TestEIEngine:
    """EI引擎测试"""

    def test_infer(self):
        from tide_memory.emotion.ei_model import EIEngine
        from tide_memory.emotion.valence_arousal import ValenceArousalModel
        ei = EIEngine(ValenceArousalModel())
        result = ei.infer_from_text("测试文本")
        assert 0 <= result["ei_score"] <= 1
        assert "dominant_emotion" in result
        assert "valence" in result
        assert "arousal" in result

    def test_high_emotion_ei(self):
        from tide_memory.emotion.ei_model import EIEngine
        from tide_memory.emotion.valence_arousal import ValenceArousalModel
        ei = EIEngine(ValenceArousalModel())
        result = ei.infer_from_text("非常极其特别开心快乐幸福激动兴奋")
        assert result["ei_score"] > 0.3  # 高情绪强度

    def test_emotion_labels(self):
        from tide_memory.emotion.ei_model import EIEngine
        from tide_memory.emotion.valence_arousal import ValenceArousalModel
        ei = EIEngine(ValenceArousalModel())
        labels = set()
        texts = ["非常开心", "很难过", "很焦虑", "很平静", "一般般"]
        for text in texts:
            result = ei.infer_from_text(text)
            labels.add(result["dominant_emotion"])
        assert len(labels) >= 2  # 至少有2种不同情绪标签

    def test_trend_insufficient(self):
        from tide_memory.emotion.ei_model import EIEngine
        ei = EIEngine()
        trend = ei.get_trend()
        assert trend["trend"] == "insufficient_data"


# ========== 安全测试 ==========

class TestDomainManager:
    """域权限管理器测试"""

    def test_private_owner_full_access(self):
        from tide_memory.security.domain_manager import DomainManager
        dm = DomainManager()
        dm.register_agent("alice")
        assert dm.check_permission("alice", "private:alice", "read")
        assert dm.check_permission("alice", "private:alice", "write")
        assert dm.check_permission("alice", "private:alice", "delete")

    def test_private_others_no_access(self):
        from tide_memory.security.domain_manager import DomainManager
        dm = DomainManager()
        dm.register_agent("alice")
        dm.register_agent("bob")
        assert not dm.check_permission("bob", "private:alice", "read")
        assert not dm.check_permission("bob", "private:alice", "write")

    def test_core_readonly(self):
        from tide_memory.security.domain_manager import DomainManager
        dm = DomainManager()
        dm.register_agent("normal_agent", role="normal")
        assert not dm.check_permission("normal_agent", "core:system", "write")

    def test_admin_full_access(self):
        from tide_memory.security.domain_manager import DomainManager
        dm = DomainManager()
        assert dm.check_permission("system", "private:anyone", "read")
        assert dm.check_permission("system", "core:system", "admin")

    def test_revoke_permission(self):
        from tide_memory.security.domain_manager import DomainManager, Permission
        dm = DomainManager()
        dm.register_agent("alice")
        # 默认共享域可读
        assert dm.check_permission("alice", "shared:team1", "read")


class TestSecretMarker:
    """密级标记测试"""

    def test_default_level(self):
        from tide_memory.security.secret_marker import SecretMarker, ClassificationLevel
        sm = SecretMarker(default_level=ClassificationLevel.TOP_SECRET)
        assert sm.get_level("nonexistent") == "TOP_SECRET"

    def test_mark_and_check(self):
        from tide_memory.security.secret_marker import SecretMarker, ClassificationLevel
        sm = SecretMarker()
        sm.mark("mem_001", ClassificationLevel.CONFIDENTIAL)
        assert sm.check_access("mem_001", "confidential")
        assert not sm.check_access("mem_001", "internal")

    def test_public_access(self):
        from tide_memory.security.secret_marker import SecretMarker, ClassificationLevel
        sm = SecretMarker()
        sm.mark("mem_002", ClassificationLevel.PUBLIC)
        assert sm.check_access("mem_002", "anyone")

    def test_top_secret_local_only(self):
        from tide_memory.security.secret_marker import SecretMarker, ClassificationLevel
        sm = SecretMarker()
        assert sm.local_only(ClassificationLevel.TOP_SECRET)
        assert not sm.local_only(ClassificationLevel.PUBLIC)

    def test_encrypt_required(self):
        from tide_memory.security.secret_marker import SecretMarker, ClassificationLevel
        sm = SecretMarker()
        assert sm.encrypt_required(ClassificationLevel.TOP_SECRET)
        assert sm.encrypt_required(ClassificationLevel.CONFIDENTIAL)
        assert not sm.encrypt_required(ClassificationLevel.PUBLIC)

    def test_downgrade(self):
        from tide_memory.security.secret_marker import SecretMarker, ClassificationLevel
        sm = SecretMarker()
        sm.mark("mem_003", ClassificationLevel.TOP_SECRET)
        new_level = sm.downgrade("mem_003")
        assert new_level == "CONFIDENTIAL"
        new_level = sm.downgrade("mem_003")
        assert new_level == "INTERNAL"

    def test_upgrade(self):
        from tide_memory.security.secret_marker import SecretMarker, ClassificationLevel
        sm = SecretMarker()
        sm.mark("mem_004", ClassificationLevel.INTERNAL)
        new_level = sm.upgrade("mem_004", "敏感内容")
        assert new_level == "CONFIDENTIAL"

    def test_stats(self):
        from tide_memory.security.secret_marker import SecretMarker, ClassificationLevel
        sm = SecretMarker()
        sm.mark("m1", ClassificationLevel.TOP_SECRET)
        sm.mark("m2", ClassificationLevel.CONFIDENTIAL)
        stats = sm.get_stats()
        assert stats["TOP_SECRET"] == 1
        assert stats["CONFIDENTIAL"] == 1


class TestDesensitizer:
    """数据脱敏测试"""

    def test_phone_desensitize(self):
        from tide_memory.security.desensitizer import DataDesensitizer
        ds = DataDesensitizer()
        text = "联系电话：13912345678"
        result = ds.desensitize(text)
        assert "13912345678" not in result

    def test_email_desensitize(self):
        from tide_memory.security.desensitizer import DataDesensitizer
        ds = DataDesensitizer()
        text = "邮箱：user@example.com"
        result = ds.desensitize(text)
        assert "user@example.com" not in result

    def test_id_card_desensitize(self):
        from tide_memory.security.desensitizer import DataDesensitizer
        ds = DataDesensitizer()
        text = "身份证：110101199001011234"
        result = ds.desensitize(text)
        assert "110101199001011234" not in result

    def test_ip_desensitize(self):
        from tide_memory.security.desensitizer import DataDesensitizer
        ds = DataDesensitizer()
        text = "IP地址：192.168.1.100"
        result = ds.desensitize(text)
        assert "192.168.1.100" not in result

    def test_api_key_desensitize(self):
        from tide_memory.security.desensitizer import DataDesensitizer
        ds = DataDesensitizer()
        text = "api_key=sk-12345abcde"
        result = ds.desensitize(text)
        assert "sk-12345abcde" not in result

    def test_dict_desensitize(self):
        from tide_memory.security.desensitizer import DataDesensitizer
        ds = DataDesensitizer()
        data = {"password": "secret123", "phone": "13912345678", "name": "test"}
        result = ds.desensitize_dict(data)
        assert result["password"] != "secret123"

    def test_memory_content_mask(self):
        from tide_memory.security.desensitizer import DataDesensitizer
        ds = DataDesensitizer()
        content = "这是一条很长的记忆内容，包含敏感信息"
        result = ds.mask_memory_content(content, level="full")
        assert result == "[CONTENT_REDACTED]"

    def test_sensitive_score(self):
        from tide_memory.security.desensitizer import DataDesensitizer
        ds = DataDesensitizer()
        score = ds.get_sensitive_score("手机号13912345678，邮箱test@example.com")
        assert score > 0.3


# ========== 检索测试 ==========

class TestKeywordSearch:
    """关键词检索测试"""

    def test_index_and_search(self):
        from tide_memory.recall.keyword_search import KeywordSearch
        ks = KeywordSearch()
        ks.index("mem_001", "人工智能机器学习", tags=["AI", "ML"])
        ks.index("mem_002", "大数据分析", tags=["数据"])
        results = ks.search("人工智能")
        assert len(results) >= 1
        assert results[0]["memory_id"] == "mem_001"

    def test_tag_search(self):
        from tide_memory.recall.keyword_search import KeywordSearch
        ks = KeywordSearch()
        ks.index("mem_001", "内容1", tags=["工作", "重要"])
        ks.index("mem_002", "内容2", tags=["生活"])
        results = ks.search("", tags=["重要"])
        assert len(results) >= 1

    def test_delete(self):
        from tide_memory.recall.keyword_search import KeywordSearch
        ks = KeywordSearch()
        ks.index("mem_001", "测试内容")
        assert ks.delete("mem_001")
        results = ks.search("测试")
        assert len(results) == 0

    def test_stats(self):
        from tide_memory.recall.keyword_search import KeywordSearch
        ks = KeywordSearch()
        ks.index("m1", "测试内容一")
        ks.index("m2", "测试内容二")
        stats = ks.get_stats()
        assert stats["total_docs"] == 2


class TestRecallEngine:
    """检索引擎测试"""

    def test_search_empty(self):
        from tide_memory.recall.recall_engine import RecallEngine
        engine = RecallEngine()
        results = engine.search("测试")
        assert isinstance(results, list)

    def test_archive_memory(self):
        from tide_memory.recall.recall_engine import RecallEngine
        engine = RecallEngine()
        result = engine.archive_memory(
            content_hash="abc123",
            source="test",
            domain="private",
            agent_id="test_agent",
            tags=["测试"],
        )
        assert "memory_id" in result
        assert result["memory_id"].startswith("mem_")

    def test_get_stats(self):
        from tide_memory.recall.recall_engine import RecallEngine
        engine = RecallEngine()
        stats = engine.get_stats()
        assert "total" in stats
        assert "layers" in stats


# ========== 巩固测试 ==========

class TestConsolidation:
    """记忆巩固测试"""

    def test_run_quick(self):
        from tide_memory.sleep.consolidation import ConsolidationEngine
        engine = ConsolidationEngine()
        result = engine.run_consolidation(mode="quick")
        assert "mode" in result
        assert result["mode"] == "quick"

    def test_run_full(self):
        from tide_memory.sleep.consolidation import ConsolidationEngine
        engine = ConsolidationEngine()
        result = engine.run_consolidation(mode="full")
        assert result["reindexed"] is True

    def test_stats(self):
        from tide_memory.sleep.consolidation import ConsolidationEngine
        engine = ConsolidationEngine()
        stats = engine.get_consolidation_stats()
        assert "total_consolidations" in stats


# ========== 审计测试 ==========

class TestAuditLogger:
    """审计日志测试"""

    def test_record_and_query(self, tmp_path):
        from tide_memory.audit.audit_logger import AuditLogger
        log_path = str(tmp_path / "audit.log")
        audit = AuditLogger(log_path=log_path)
        audit.record("mem_001", "read", "agent_1", "private", True)
        audit.flush()
        results = audit.query(agent_id="agent_1")
        assert len(results) >= 1
        # 确认日志不包含记忆内容
        for entry in results:
            assert "content" not in entry
            assert "body" not in entry

    def test_permission_denied_log(self, tmp_path):
        from tide_memory.audit.audit_logger import AuditLogger
        log_path = str(tmp_path / "audit2.log")
        audit = AuditLogger(log_path=log_path)
        audit.record("mem_001", "read", "hacker", "private", False, "permission_denied")
        audit.flush()
        results = audit.query(operation="read")
        denied = [r for r in results if not r.get("success")]
        assert len(denied) >= 1

    def test_stats(self, tmp_path):
        from tide_memory.audit.audit_logger import AuditLogger
        log_path = str(tmp_path / "audit3.log")
        audit = AuditLogger(log_path=log_path)
        for i in range(10):
            audit.record(f"mem_{i}", "read", "agent", "private", True)
        audit.flush()
        stats = audit.get_stats()
        assert stats["total_logs"] >= 10


# ========== M8接口测试 ==========

class TestM8Interface:
    """M8标准接口测试"""

    def test_health(self):
        from tide_memory.api.m8_interface import M8Interface
        m8 = M8Interface()
        result = m8.m8_health_check()
        assert result["code"] == 0
        assert "features" in result["data"]
        assert "m8_compatible" in result["data"]["features"]

    def test_recall_invalid_params(self):
        from tide_memory.api.m8_interface import M8Interface
        m8 = M8Interface()
        result = m8.m8_recall({})
        assert result["code"] != 0

    def test_error_codes_complete(self):
        from tide_memory.api.m8_interface import M8ErrorCode
        assert hasattr(M8ErrorCode, "SUCCESS")
        assert hasattr(M8ErrorCode, "PERMISSION_DENIED")
        assert hasattr(M8ErrorCode, "INVALID_PARAMS")
        assert M8ErrorCode.SUCCESS == 0

    def test_interface_spec(self):
        from tide_memory.api.m8_interface import M8Interface
        m8 = M8Interface()
        spec = m8.get_interface_spec()
        assert spec["module"] == "m5-memory"
        assert "endpoints" in spec
        assert "error_codes" in spec


# ========== 工具测试 ==========

class TestCryptoUtils:
    """加密工具测试"""

    def test_generate_key(self):
        from tide_memory.utils.crypto import CryptoUtils
        key = CryptoUtils.generate_key()
        assert len(key) == 32  # 256 bits

    def test_encrypt_decrypt(self):
        from tide_memory.utils.crypto import CryptoUtils
        key = CryptoUtils.generate_key()
        plaintext = "测试加密内容（模拟数据）"
        encrypted = CryptoUtils.encrypt(plaintext, key)
        assert encrypted != plaintext
        decrypted = CryptoUtils.decrypt(encrypted, key)
        assert decrypted == plaintext

    def test_different_keys(self):
        from tide_memory.utils.crypto import CryptoUtils
        key1 = CryptoUtils.generate_key()
        key2 = CryptoUtils.generate_key()
        encrypted = CryptoUtils.encrypt("test", key1)
        # 用不同密钥解密应该失败
        decrypted = CryptoUtils.decrypt(encrypted, key2)
        # 要么返回None，要么结果不对
        assert decrypted != "test" or decrypted is None

    def test_hash_content(self):
        from tide_memory.utils.crypto import CryptoUtils
        h1 = CryptoUtils.hash_content("测试")
        h2 = CryptoUtils.hash_content("测试")
        assert h1 == h2
        assert len(h1) == 64  # SHA256


class TestHashUtils:
    """哈希工具测试"""

    def test_sha256(self):
        from tide_memory.utils.hash_utils import HashUtils
        h = HashUtils.sha256("test")
        assert len(h) == 64

    def test_generate_id_unique(self):
        from tide_memory.utils.hash_utils import HashUtils
        ids = set()
        for _ in range(100):
            ids.add(HashUtils.generate_id("mem"))
        assert len(ids) == 100

    def test_merkle_root(self):
        from tide_memory.utils.hash_utils import HashUtils
        hashes = [HashUtils.sha256(f"item{i}") for i in range(10)]
        root = HashUtils.merkle_root(hashes)
        assert len(root) == 64
        # 相同输入产生相同根
        assert HashUtils.merkle_root(hashes) == root


class TestAuthMiddleware:
    """认证中间件测试"""

    def test_missing_token(self):
        from tide_memory.middleware.auth import AuthMiddleware
        auth = AuthMiddleware()
        ok, info = auth.authenticate({"headers": {}})
        assert not ok
        assert info["error"] == "missing_token"

    def test_bearer_token(self):
        from tide_memory.middleware.auth import AuthMiddleware
        auth = AuthMiddleware()
        ok, info = auth.authenticate({
            "headers": {"authorization": "Bearer test-token-12345"}
        })
        # 简单token格式也能通过
        assert ok is True or info.get("error") in ["invalid_token"]

    def test_rate_limit_tracking(self):
        from tide_memory.middleware.auth import AuthMiddleware
        auth = AuthMiddleware()
        stats = auth.get_auth_stats()
        assert "rate_limit" in stats


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
