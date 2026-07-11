"""
冒烟测试 - 仅用模拟数据，不包含任何真实用户数据

运行: python -m pytest tests/test_smoke.py -v
"""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import pytest


class TestConfig:
    """配置模块测试"""

    def test_default_config(self):
        from tide_memory.core.config import TideConfig
        config = TideConfig()
        assert config.get("basic.version") == "2.4.0"
        assert config.get("security.high_secret_local_only") is True

    def test_config_set_get(self):
        from tide_memory.core.config import TideConfig
        config = TideConfig()
        config.set("test.key", "value")
        assert config.get("test.key") == "value"


class TestModels:
    """数据模型测试"""

    def test_memory_item_defaults(self):
        from tide_memory.core.models import MemoryItem, MemoryLayer
        item = MemoryItem()
        assert item.memory_id.startswith("mem_")
        assert item.layer == MemoryLayer.L1_SHALLOW
        assert item.quality_score == 50.0

    def test_memory_touch(self):
        from tide_memory.core.models import MemoryItem
        item = MemoryItem()
        assert item.access_count == 0
        item.touch()
        assert item.access_count == 1
        assert item.last_accessed_at is not None

    def test_memory_promote(self):
        from tide_memory.core.models import MemoryItem, MemoryLayer
        item = MemoryItem(layer=MemoryLayer.L0_BEACH)
        item.promote()
        assert item.layer == MemoryLayer.L1_SHALLOW
        item.promote()
        assert item.layer == MemoryLayer.L2_DEEP


class TestLayers:
    """记忆层测试"""

    def test_beach_layer_add_get(self):
        from tide_memory.layers.l0_beach import BeachLayer
        from tide_memory.core.models import MemoryItem
        layer = BeachLayer({"max_items": 10})
        item = MemoryItem(tags=["测试", "记忆"])
        layer.add(item)
        assert layer.count() == 1
        retrieved = layer.get(item.memory_id)
        assert retrieved is not None
        assert retrieved.memory_id == item.memory_id

    def test_beach_layer_eviction(self):
        from tide_memory.layers.l0_beach import BeachLayer
        from tide_memory.core.models import MemoryItem
        layer = BeachLayer({"max_items": 3})
        ids = []
        for i in range(5):
            item = MemoryItem()
            layer.add(item)
            ids.append(item.memory_id)
        assert layer.count() == 3
        # 最旧的应该被淘汰
        assert layer.get(ids[0]) is None
        assert layer.get(ids[4]) is not None


class TestEmotion:
    """情绪推断测试（使用模拟数据）"""

    def test_valence_arousal_positive(self):
        from tide_memory.emotion.valence_arousal import ValenceArousalModel
        model = ValenceArousalModel()
        result = model.infer("今天非常开心，感觉很棒很快乐")
        assert result["valence"] > 0  # 正面效价
        assert result["arousal"] > 0.3  # 有唤醒度
        assert 0 <= result["confidence"] <= 1

    def test_valence_arousal_negative(self):
        from tide_memory.emotion.valence_arousal import ValenceArousalModel
        model = ValenceArousalModel()
        result = model.infer("很难过很伤心，感觉非常痛苦")
        assert result["valence"] < 0  # 负面效价

    def test_ei_engine_infer(self):
        from tide_memory.emotion.ei_model import EIEngine
        from tide_memory.emotion.valence_arousal import ValenceArousalModel
        ei = EIEngine(ValenceArousalModel())
        result = ei.infer_from_text("测试文本")
        assert "ei_score" in result
        assert "dominant_emotion" in result
        assert 0 <= result["ei_score"] <= 1


class TestSecurity:
    """安全模块测试"""

    def test_domain_manager_permission(self):
        from tide_memory.security.domain_manager import DomainManager
        dm = DomainManager()
        dm.register_agent("test_agent", role="normal")
        # 私有域自己有全部权限
        assert dm.check_permission("test_agent", "private:test_agent", "read") is True
        assert dm.check_permission("test_agent", "private:test_agent", "write") is True
        # 别人的私有域
        assert dm.check_permission("test_agent", "private:other", "read") is False

    def test_secret_marker_levels(self):
        from tide_memory.security.secret_marker import SecretMarker, ClassificationLevel
        sm = SecretMarker(default_level=ClassificationLevel.TOP_SECRET)
        result = sm.mark("test_mem_001", ClassificationLevel.CONFIDENTIAL, "测试标记")
        assert result["classification"] == "CONFIDENTIAL"
        assert result["encrypted"] is True
        assert sm.check_access("test_mem_001", "admin") is True
        assert sm.check_access("test_mem_001", "public") is False

    def test_desensitizer_phone(self):
        from tide_memory.security.desensitizer import DataDesensitizer
        ds = DataDesensitizer()
        text = "我的手机号是13812345678"
        result = ds.desensitize(text)
        assert "13812345678" not in result  # 手机号被脱敏

    def test_desensitizer_email(self):
        from tide_memory.security.desensitizer import DataDesensitizer
        ds = DataDesensitizer()
        text = "邮箱是test@example.com"
        result = ds.desensitize(text)
        assert "test@example.com" not in result


class TestAudit:
    """审计日志测试"""

    def test_audit_record(self, tmp_path):
        from tide_memory.audit.audit_logger import AuditLogger
        log_path = str(tmp_path / "test-audit.log")
        audit = AuditLogger(log_path=log_path, enabled=True)
        audit.record("mem_test", "read", "test_agent", "private", True)
        audit.flush()
        import os
        assert os.path.exists(log_path)
        results = audit.query(agent_id="test_agent")
        assert len(results) >= 1
        # 确认不包含记忆内容
        for entry in results:
            assert "content" not in entry


class TestM8Interface:
    """M8标准接口测试"""

    def test_health_check(self):
        from tide_memory.api.m8_interface import M8Interface
        m8 = M8Interface()
        result = m8.m8_health_check()
        assert result["code"] == 0
        assert result["data"]["module"] == "m5-memory"
        assert "four_layer_tidal_memory" in result["data"]["features"]

    def test_error_codes(self):
        from tide_memory.api.m8_interface import M8ErrorCode
        assert M8ErrorCode.SUCCESS == 0
        assert M8ErrorCode.PERMISSION_DENIED == 50201
        assert M8ErrorCode.INVALID_PARAMS == 50001


class TestUtils:
    """工具模块测试"""

    def test_hash_sha256(self):
        from tide_memory.utils.hash_utils import HashUtils
        h1 = HashUtils.sha256("测试文本")
        h2 = HashUtils.sha256("测试文本")
        assert h1 == h2
        assert len(h1) == 64

    def test_generate_id(self):
        from tide_memory.utils.hash_utils import HashUtils
        id1 = HashUtils.generate_id("mem")
        id2 = HashUtils.generate_id("mem")
        assert id1 != id2
        assert id1.startswith("mem_")

    def test_crypto_roundtrip(self):
        from tide_memory.utils.crypto import CryptoUtils
        key = CryptoUtils.generate_key()
        plaintext = "这是一条测试记忆内容（模拟数据，非真实用户数据）"
        encrypted = CryptoUtils.encrypt(plaintext, key)
        assert encrypted != plaintext
        decrypted = CryptoUtils.decrypt(encrypted, key)
        assert decrypted == plaintext


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
