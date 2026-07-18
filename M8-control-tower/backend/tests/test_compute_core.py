"""
算力调度中台 - 核心功能验证脚本
验证内容：
1. 加密模块（encrypt/decrypt/mask_api_key）
2. 数据库模型（8 张表的创建和基础 CRUD）
3. 算力源 CRUD
4. 密钥分组 CRUD
5. 模型绑定 CRUD
6. 其他表基础写入测试

运行方式：
    cd M8-control-tower/backend
    python test_compute_core.py
"""

import sys
import os
from pathlib import Path

# 确保项目根目录在 path 中
# 脚本可以放在任意位置，自动定位到 M8-control-tower 目录
import os as _os
script_dir = Path(__file__).resolve().parent

# 尝试从脚本目录往上找 M8-control-tower
project_root = None
current = script_dir
while current != current.parent:
    if (current / "M8-control-tower").exists():
        project_root = current / "M8-control-tower"
        break
    if current.name == "M8-control-tower":
        project_root = current
        break
    current = current.parent

if project_root is None:
    # 硬编码备用
    project_root = Path("c:/Yunxi/workspace/yunxi-project/M8-control-tower")
# 设置测试用主密钥（避免影响生产环境）
os.environ.setdefault("COMPUTE_MASTER_KEY", "test-master-key-for-validation-1234567890")

# 使用独立的测试数据库
from backend.config import data_dir
test_db_path = data_dir / "test_compute_core.db"


def run_tests():
    """运行所有测试"""
    passed = 0
    failed = 0

    def test(name, func):
        nonlocal passed, failed
        try:
            func()
            passed += 1
            print(f"  [PASS] {name}")
        except Exception as e:
            failed += 1
            print(f"  [FAIL] {name}: {e}")
            import traceback
            traceback.print_exc()

    print("=" * 60)
    print("算力调度中台 - 核心功能验证")
    print("=" * 60)

    # ============================================================
    # 1. 加密模块测试
    # ============================================================
    print("\n1. 加密模块测试")
    print("-" * 40)

    from backend.crypto import encrypt, decrypt, mask_api_key, get_key_info

    def test_encrypt_decrypt():
        """测试加密解密"""
        original = "sk-test-api-key-1234567890abcdef"
        encrypted = encrypt(original)
        assert encrypted != original, "加密后不应等于原文"
        assert len(encrypted) > 0, "加密结果不应为空"

        decrypted = decrypt(encrypted)
        assert decrypted == original, f"解密后应等于原文: {decrypted} != {original}"

    test("加密/解密基本功能", test_encrypt_decrypt)

    def test_mask_api_key():
        """测试 API Key 掩码"""
        key = "sk-abcdefghijklmnopqrstuvwxyz123456"
        masked = mask_api_key(key)
        assert "****" in masked, "掩码应包含 ****"
        assert key not in masked, "掩码不应包含完整密钥"

    test("API Key 掩码", test_mask_api_key)

    def test_empty_key():
        """测试空密钥"""
        assert encrypt("") == "", "空字符串加密应返回空"
        assert decrypt("") == "", "空字符串解密应返回空"
        assert mask_api_key("") == "", "空字符串掩码应返回空"

    test("空密钥处理", test_empty_key)

    def test_key_info():
        """测试密钥信息获取"""
        info = get_key_info()
        assert "fingerprint" in info, "应包含密钥指纹"
        assert "algorithm" in info, "应包含算法信息"

    test("密钥信息获取", test_key_info)

    # ============================================================
    # 2. 数据库模型测试
    # ============================================================
    print("\n2. 数据库模型测试")
    print("-" * 40)

    # 使用测试数据库
    from sqlalchemy import create_engine, inspect
    from sqlalchemy.orm import sessionmaker
    from backend.models import Base

    test_db_url = f"sqlite:///{test_db_path}"
    test_engine = create_engine(
        test_db_url,
        connect_args={"check_same_thread": False},
    )
    TestSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=test_engine)

    # 创建所有表
    Base.metadata.create_all(bind=test_engine)

    def test_tables_exist():
        """验证所有 8 张表都已创建"""
        inspector = inspect(test_engine)
        tables = inspector.get_table_names()

        expected_tables = [
            "compute_sources",
            "compute_key_groups",
            "compute_model_bindings",
            "compute_skill_bindings",
            "compute_call_logs",
            "compute_quotas",
            "compute_routing_policies",
            "compute_alerts",
        ]

        for table_name in expected_tables:
            assert table_name in tables, f"表 {table_name} 不存在"

    test("8 张算力调度表创建", test_tables_exist)

    # ============================================================
    # 3. 算力源 CRUD 测试
    # ============================================================
    print("\n3. 算力源 CRUD 测试")
    print("-" * 40)

    from backend.models import ComputeSource

    db = TestSessionLocal()

    def test_source_create():
        """测试创建算力源"""
        api_key = "sk-test-1234567890"
        encrypted_key = encrypt(api_key)
        masked_key = mask_api_key(api_key)

        source = ComputeSource(
            source_id="test-source-01",
            name="测试算力源",
            type="cloud",
            provider="deepseek",
            base_url="https://api.deepseek.com/v1",
            api_key_encrypted=encrypted_key,
            api_key_masked=masked_key,
            status="active",
            priority=10,
            weight=100,
            max_concurrent=10,
            timeout=60,
            cost_per_1k_input=0.002,
            cost_per_1k_output=0.008,
            models=["deepseek-chat", "deepseek-coder"],
            capabilities=["chat", "code"],
            config={"test": True},
        )
        db.add(source)
        db.commit()
        db.refresh(source)

        assert source.id is not None, "ID 不应为空"
        assert source.source_id == "test-source-01"
        assert source.api_key_encrypted != api_key, "API Key 应已加密"
        assert source.api_key_masked == masked_key

        decrypted = decrypt(source.api_key_encrypted)
        assert decrypted == api_key, "解密后应等于原文"

    test("创建算力源", test_source_create)

    def test_source_query():
        """测试查询算力源"""
        source = db.query(ComputeSource).filter(
            ComputeSource.source_id == "test-source-01"
        ).first()
        assert source is not None, "应能查询到算力源"
        assert source.name == "测试算力源"
        assert source.type == "cloud"
        assert "chat" in source.capabilities
        assert len(source.models) == 2

    test("查询算力源", test_source_query)

    def test_source_update():
        """测试更新算力源"""
        source = db.query(ComputeSource).filter(
            ComputeSource.source_id == "test-source-01"
        ).first()
        source.name = "更新后的算力源"
        source.status = "inactive"
        source.priority = 5
        db.commit()
        db.refresh(source)

        assert source.name == "更新后的算力源"
        assert source.status == "inactive"
        assert source.priority == 5

    test("更新算力源", test_source_update)

    def test_source_list_filter():
        """测试列表筛选"""
        source2 = ComputeSource(
            source_id="test-local-01",
            name="本地测试源",
            type="local",
            provider="ollama",
            base_url="http://localhost:11434",
            status="active",
            models=["qwen2.5:7b"],
            capabilities=["chat"],
        )
        db.add(source2)
        db.commit()

        cloud_sources = db.query(ComputeSource).filter(
            ComputeSource.type == "cloud"
        ).all()
        assert len(cloud_sources) >= 1, "应至少有 1 个云端算力源"

        local_sources = db.query(ComputeSource).filter(
            ComputeSource.type == "local"
        ).all()
        assert len(local_sources) >= 1, "应至少有 1 个本地算力源"

    test("算力源列表筛选", test_source_list_filter)

    def test_source_delete():
        """测试删除算力源"""
        source = db.query(ComputeSource).filter(
            ComputeSource.source_id == "test-local-01"
        ).first()
        db.delete(source)
        db.commit()

        deleted = db.query(ComputeSource).filter(
            ComputeSource.source_id == "test-local-01"
        ).first()
        assert deleted is None, "删除后应查询不到"

    test("删除算力源", test_source_delete)

    # ============================================================
    # 4. 密钥分组 CRUD 测试
    # ============================================================
    print("\n4. 密钥分组 CRUD 测试")
    print("-" * 40)

    from backend.models import ComputeKeyGroup

    def test_group_create():
        """测试创建密钥分组"""
        group = ComputeKeyGroup(
            group_id="test-group-01",
            name="测试分组",
            description="这是一个测试分组",
            source_ids=["test-source-01"],
            default_source="test-source-01",
            routing_strategy="latency_first",
        )
        db.add(group)
        db.commit()
        db.refresh(group)

        assert group.id is not None
        assert group.group_id == "test-group-01"
        assert "test-source-01" in group.source_ids
        assert group.routing_strategy == "latency_first"

    test("创建密钥分组", test_group_create)

    def test_group_update():
        """测试更新密钥分组"""
        group = db.query(ComputeKeyGroup).filter(
            ComputeKeyGroup.group_id == "test-group-01"
        ).first()
        group.name = "更新后的测试分组"
        group.routing_strategy = "cost_first"
        db.commit()
        db.refresh(group)

        assert group.name == "更新后的测试分组"
        assert group.routing_strategy == "cost_first"

    test("更新密钥分组", test_group_update)

    def test_group_delete():
        """测试删除密钥分组"""
        group = db.query(ComputeKeyGroup).filter(
            ComputeKeyGroup.group_id == "test-group-01"
        ).first()
        db.delete(group)
        db.commit()

        deleted = db.query(ComputeKeyGroup).filter(
            ComputeKeyGroup.group_id == "test-group-01"
        ).first()
        assert deleted is None

    test("删除密钥分组", test_group_delete)

    # ============================================================
    # 5. 模型绑定 CRUD 测试
    # ============================================================
    print("\n5. 模型绑定 CRUD 测试")
    print("-" * 40)

    from backend.models import ComputeModelBinding

    test_group = ComputeKeyGroup(
        group_id="test-group-model",
        name="模型测试分组",
        source_ids=["test-source-01"],
    )
    db.add(test_group)
    db.commit()

    def test_model_create():
        """测试创建模型绑定"""
        model = ComputeModelBinding(
            model_key="test-chat-model",
            model_name="测试对话模型",
            purpose="chat",
            group_id="test-group-model",
            fallback_model_key="",
            max_tokens=4096,
            temperature_default=0.7,
        )
        db.add(model)
        db.commit()
        db.refresh(model)

        assert model.id is not None
        assert model.model_key == "test-chat-model"
        assert model.purpose == "chat"
        assert model.group_id == "test-group-model"

    test("创建模型绑定", test_model_create)

    def test_model_update():
        """测试更新模型绑定"""
        model = db.query(ComputeModelBinding).filter(
            ComputeModelBinding.model_key == "test-chat-model"
        ).first()
        model.max_tokens = 8192
        model.temperature_default = 0.5
        db.commit()
        db.refresh(model)

        assert model.max_tokens == 8192
        assert model.temperature_default == 0.5

    test("更新模型绑定", test_model_update)

    def test_model_delete():
        """测试删除模型绑定"""
        model = db.query(ComputeModelBinding).filter(
            ComputeModelBinding.model_key == "test-chat-model"
        ).first()
        db.delete(model)
        db.commit()

        deleted = db.query(ComputeModelBinding).filter(
            ComputeModelBinding.model_key == "test-chat-model"
        ).first()
        assert deleted is None

    test("删除模型绑定", test_model_delete)

    # ============================================================
    # 6. 其他表的基础写入测试
    # ============================================================
    print("\n6. 其他表基础功能测试")
    print("-" * 40)

    from backend.models import (
        ComputeSkillBinding,
        ComputeCallLog,
        ComputeQuota,
        ComputeRoutingPolicy,
        ComputeAlert,
    )
    import uuid

    def test_skill_binding():
        """测试技能权限表"""
        skill = ComputeSkillBinding(
            skill_id="test-skill-code",
            skill_name="代码生成技能",
            allowed_groups=["test-group-model"],
            allowed_sources=["test-source-01"],
            quota_daily=100.0,
            quota_monthly=2000.0,
            rate_limit_per_min=60,
            priority=50,
        )
        db.add(skill)
        db.commit()
        db.refresh(skill)
        assert skill.id is not None
        assert skill.skill_id == "test-skill-code"

    test("技能权限表写入", test_skill_binding)

    def test_call_log():
        """测试调用记录表"""
        log = ComputeCallLog(
            call_id=f"call-{uuid.uuid4().hex[:12]}",
            source_id="test-source-01",
            model_key="test-chat-model",
            caller_module="m8",
            caller_skill="chat",
            input_tokens=100,
            output_tokens=200,
            cost=0.005,
            latency_ms=500,
            status="success",
            error_code="",
            error_message="",
            request_hash="abc123",
        )
        db.add(log)
        db.commit()
        db.refresh(log)
        assert log.id is not None
        assert log.status == "success"
        assert log.cost == 0.005

    test("调用记录表写入", test_call_log)

    def test_quota():
        """测试额度配额表"""
        quota = ComputeQuota(
            scope="global",
            scope_key="all",
            period="daily",
            limit_amount=1000.0,
            used_amount=100.0,
            alert_threshold=80.0,
            action_on_exceed="alert_only",
        )
        db.add(quota)
        db.commit()
        db.refresh(quota)
        assert quota.id is not None
        assert quota.scope == "global"
        assert quota.used_amount == 100.0

    test("额度配额表写入", test_quota)

    def test_routing_policy():
        """测试路由策略表"""
        policy = ComputeRoutingPolicy(
            policy_id="test-policy",
            name="测试策略",
            mode="auto",
            default_strategy="latency_first",
            cost_weight=0.3,
            latency_weight=0.4,
            quality_weight=0.2,
            privacy_weight=0.1,
            auto_failover=True,
            circuit_breaker_enabled=True,
            rate_limit_enabled=True,
            offline_fallback_enabled=True,
        )
        db.add(policy)
        db.commit()
        db.refresh(policy)
        assert policy.id is not None
        assert policy.policy_id == "test-policy"
        assert policy.mode == "auto"

    test("路由策略表写入", test_routing_policy)

    def test_alert():
        """测试告警事件表"""
        alert = ComputeAlert(
            alert_id=f"alert-{uuid.uuid4().hex[:12]}",
            type="quota",
            severity="warning",
            source_id="test-source-01",
            message="日额度已使用 80%",
            details={"used": 80, "limit": 100},
            resolved=False,
        )
        db.add(alert)
        db.commit()
        db.refresh(alert)
        assert alert.id is not None
        assert alert.type == "quota"
        assert alert.severity == "warning"

    test("告警事件表写入", test_alert)

    # ============================================================
    # 清理
    # ============================================================
    db.close()
    test_engine.dispose()

    # 删除测试数据库
    try:
        if test_db_path.exists():
            test_db_path.unlink()
    except Exception:
        pass

    # ============================================================
    # 总结
    # ============================================================
    print("\n" + "=" * 60)
    print(f"测试完成: {passed} 通过, {failed} 失败")
    print("=" * 60)

    return failed == 0


if __name__ == "__main__":
    success = run_tests()
    sys.exit(0 if success else 1)
