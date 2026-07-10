"""
M5 潮汐记忆系统 - P0问题修复验证脚本

验证内容：
1. 归档接口不再500（返回正确的 code/message/data 结构）
2. 私有域权限隔离（非所有者无法访问私有域）
3. L2层SQLite持久化（数据写入数据库，重启后可读取）
4. L1→L2迁移逻辑（满足条件的记忆从L1迁移到L2）
"""

from __future__ import annotations

import os
import sys
import tempfile
import shutil
from pathlib import Path

# 确保 src 目录在路径中
BASE_DIR = Path(__file__).resolve().parent
SRC_DIR = BASE_DIR / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))


def test_1_archive_no_500():
    """测试1：归档接口返回正确格式（不再500）"""
    print("\n" + "=" * 60)
    print("测试1：归档接口返回格式验证（修复500问题）")
    print("=" * 60)

    from main import create_app
    from tide_memory.api.routes import MemoryAPIRouter

    # 使用临时目录避免污染数据
    tmp_dir = tempfile.mkdtemp(prefix="m5_test_1_")
    os.environ["M5_STORAGE_PATH"] = tmp_dir
    try:
        app_ctx = create_app()
        router = MemoryAPIRouter(app_ctx)

        # 测试归档接口
        result = router.archive({
            "content": "测试记忆内容",
            "domain": "private:system",
            "agent_id": "system",
            "tags": ["测试", "验证"],
        })

        print(f"  归档返回: code={result.get('code')}, message={result.get('message')}")

        # 验证返回结构
        assert "code" in result, "返回结果缺少 code 字段"
        assert "message" in result, "返回结果缺少 message 字段"
        assert "data" in result, "返回结果缺少 data 字段"
        assert result["code"] == 0, f"归档失败，code={result['code']}"
        assert "archive_id" in result["data"], "data 中缺少 archive_id"
        print("  ✅ 归档接口返回格式正确，有 code/message/data 结构")

        # 测试检索接口
        result = router.recall({
            "query": "测试",
            "domain": "private:system",
            "agent_id": "system",
        })

        print(f"  检索返回: code={result.get('code')}, total={result.get('data', {}).get('total')}")

        assert "code" in result, "检索返回缺少 code 字段"
        assert result["code"] == 0, f"检索失败，code={result['code']}"
        assert "data" in result, "检索返回缺少 data 字段"
        print("  ✅ 检索接口返回格式正确")

        print("  ✅ 测试1通过：归档和检索接口都返回正确的 code/message/data 结构")
        return True
    except AssertionError as e:
        print(f"  ❌ 测试1失败：{e}")
        return False
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


def test_2_private_domain_isolation():
    """测试2：私有域权限隔离"""
    print("\n" + "=" * 60)
    print("测试2：私有域权限隔离验证")
    print("=" * 60)

    from tide_memory.security.domain_manager import DomainManager

    dm = DomainManager()

    # 注册两个Agent
    dm.register_agent("alice", role="normal")
    dm.register_agent("bob", role="normal")

    # Alice 应该能访问自己的私有域
    alice_read = dm.check_permission("alice", "private:alice", "read")
    alice_write = dm.check_permission("alice", "private:alice", "write")
    print(f"  Alice访问自己的私有域: read={alice_read}, write={alice_write}")
    assert alice_read == True, "Alice 应该能读自己的私有域"
    assert alice_write == True, "Alice 应该能写自己的私有域"
    print("  ✅ 所有者可以访问自己的私有域")

    # Bob 不应该能访问 Alice 的私有域（读权限
    bob_read_alice = dm.check_permission("bob", "private:alice", "read")
    bob_write_alice = dm.check_permission("bob", "private:alice", "write")
    print(f"  Bob访问Alice的私有域: read={bob_read_alice}, write={bob_write_alice}")
    assert bob_read_alice == False, "Bob 不应该能读 Alice 的私有域（Bug修复前为True！"
    assert bob_write_alice == False, "Bob 不应该能写 Alice 的私有域"
    print("  ✅ 非所有者无法访问他人的私有域（隔离生效）")

    # 系统管理员应有全部权限
    system_read = dm.check_permission("system", "private:alice", "read")
    print(f"  system访问Alice的私有域: read={system_read}")
    assert system_read == True, "系统管理员应有全部权限"
    print("  ✅ 系统管理员可以访问所有私有域")

    print("  ✅ 测试2通过：私有域权限隔离正常工作")
    return True


def test_3_l2_sqlite_persistence():
    """测试3：L2层SQLite持久化"""
    print("\n" + "=" * 60)
    print("测试3：L2层SQLite持久化验证")
    print("=" * 60)

    import sqlite3

    tmp_dir = tempfile.mkdtemp(prefix="m5_test_3_")
    db_path = os.path.join(tmp_dir, "l2_deep.db")

    try:
        from tide_memory.layers.l2_deep import DeepLayer
        from tide_memory.core.models import MemoryItem, MemoryLayer, MemoryDomain

        # 第一次创建并写入数据
        l2 = DeepLayer({"db_path": db_path, "max_items": 10000})

        item = MemoryItem(
            memory_id="mem_test_l2_001",
            content_hash="abc123",
            domain=MemoryDomain.PRIVATE,
            owner_agent="test_agent",
            tags=["重要", "测试"],
            quality_score=85.0,
        )
        l2.add(item)
        count_before = l2.count()
        print(f"  写入后L2数量: {count_before}")
        assert count_before == 1, f"写入后应该有1条记忆，实际{count_before}条"

        # 验证能读取
        retrieved = l2.get("mem_test_l2_001")
        assert retrieved is not None, "应该能读取到写入的记忆"
        assert retrieved.memory_id == "mem_test_l2_001", "memory_id 不匹配"
        assert retrieved.layer == MemoryLayer.L2_DEEP, "层级应该是 L2_DEEP"
        print(f"  读取验证: memory_id={retrieved.memory_id}, layer={retrieved.layer}")

        # 验证数据库文件存在
        assert os.path.exists(db_path), "数据库文件应该存在"
        print(f"  数据库文件存在: {db_path}")

        # 模拟重启：重新创建DeepLayer实例，验证数据还在
        del l2
        l2_new = DeepLayer({"db_path": db_path, "max_items": 10000})
        count_after = l2_new.count()
        print(f"  重启后L2数量: {count_after}")
        assert count_after == 1, f"重启后应该还有1条记忆，实际{count_after}条（持久化失败）"

        # 验证 items() 方法
        all_items = l2_new.items()
        assert len(all_items) == 1, "items() 应该返回1条记忆"
        print(f"  items() 返回: {len(all_items)} 条")

        # 验证 remove() 方法
        removed = l2_new.remove("mem_test_l2_001")
        assert removed == True, "remove() 应该返回 True"
        assert l2_new.count() == 0, "删除后应该为0条"
        print(f"  remove() 验证通过")

        # 验证 compress() 方法
        # 先加几条低质量记忆
        for i in range(5):
            low_item = MemoryItem(
                memory_id=f"mem_low_{i}",
                quality_score=20.0,
                domain=MemoryDomain.PRIVATE,
                owner_agent="test",
            )
            l2_new.add(low_item)
        for i in range(3):
            high_item = MemoryItem(
                memory_id=f"mem_high_{i}",
                quality_score=90.0,
                domain=MemoryDomain.PRIVATE,
                owner_agent="test",
            )
            l2_new.add(high_item)

        compress_result = l2_new.compress()
        print(f"  compress() 结果: compressed={compress_result['compressed_count']}, remaining={compress_result['remaining_count']}")
        assert compress_result["compressed_count"] == 5, f"应该压缩5条低质量记忆"
        assert compress_result["remaining_count"] == 3, f"应该剩余3条高质量记忆"

        print("  ✅ 测试3通过：L2层SQLite持久化正常工作")
        return True
    except AssertionError as e:
        print(f"  ❌ 测试3失败：{e}")
        return False
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


def test_4_l1_to_l2_migration():
    """测试4：L1→L2记忆迁移逻辑"""
    print("\n" + "=" * 60)
    print("测试4：L1→L2记忆迁移验证")
    print("=" * 60)

    tmp_dir = tempfile.mkdtemp(prefix="m5_test_4_")
    l1_db = os.path.join(tmp_dir, "l1_shallow.db")
    l2_db = os.path.join(tmp_dir, "l2_deep.db")

    try:
        from tide_memory.layers.l1_shallow import ShallowLayer
        from tide_memory.layers.l2_deep import DeepLayer
        from tide_memory.sleep.consolidation import ConsolidationEngine
        from tide_memory.core.models import MemoryItem, MemoryLayer, MemoryDomain, EmotionState

        l1 = ShallowLayer({"db_path": l1_db, "max_items": 1000})
        l2 = DeepLayer({"db_path": l2_db, "max_items": 10000})
        consolidation = ConsolidationEngine(l1=l1, l2=l2)

        # 添加不同条件的记忆
        # 1. 高访问次数（>=3）应该迁移
        high_access = MemoryItem(
            memory_id="mem_high_access",
            domain=MemoryDomain.PRIVATE,
            owner_agent="test",
            quality_score=50.0,
            access_count=5,
        )
        l1.add(high_access)

        # 2. 高质量分（>=70）应该迁移
        high_quality = MemoryItem(
            memory_id="mem_high_quality",
            domain=MemoryDomain.PRIVATE,
            owner_agent="test",
            quality_score=85.0,
            access_count=1,
        )
        l1.add(high_quality)

        # 3. 高EI值（>=0.6）应该迁移
        high_ei = MemoryItem(
            memory_id="mem_high_ei",
            domain=MemoryDomain.PRIVATE,
            owner_agent="test",
            quality_score=50.0,
            access_count=1,
            emotion=EmotionState(ei_score=0.8, dominant_emotion="joy"),
        )
        l1.add(high_ei)

        # 4. 不满足条件的不应该迁移
        low_all = MemoryItem(
            memory_id="mem_low_all",
            domain=MemoryDomain.PRIVATE,
            owner_agent="test",
            quality_score=40.0,
            access_count=1,
            emotion=EmotionState(ei_score=0.3),
        )
        l1.add(low_all)

        l1_count_before = l1.count()
        l2_count_before = l2.count()
        print(f"  迁移前: L1={l1_count_before}条, L2={l2_count_before}条")
        assert l1_count_before == 4, f"L1应该有4条记忆"
        assert l2_count_before == 0, f"L2应该有0条记忆"

        # 执行巩固
        stats = consolidation.run_consolidation(mode="normal")
        print(f"  巩固结果: promoted={stats['promoted']}")

        l1_count_after = l1.count()
        l2_count_after = l2.count()
        print(f"  迁移后: L1={l1_count_after}条, L2={l2_count_after}条")

        # 验证：3条应该迁移（高访问、高质量、高EI）
        assert stats["promoted"] >= 3, f"至少应该迁移3条记忆，实际迁移了{stats['promoted']}条"
        assert l1_count_after == 1, f"L1应该剩余1条记忆，实际{l1_count_after}条"
        assert l2_count_after >= 3, f"L2应该至少有3条记忆，实际{l2_count_after}条"

        # 验证留在L1的是不满足条件的
        remaining = l1.items()
        remaining_ids = [item.memory_id for item in remaining]
        assert "mem_low_all" in remaining_ids, "不满足条件的记忆应该留在L1"
        print(f"  留在L1的记忆: {remaining_ids}")

        # 验证迁移到L2的记忆
        migrated = l2.items()
        migrated_ids = [item.memory_id for item in migrated]
        assert "mem_high_access" in migrated_ids, "高访问记忆应该迁移到L2"
        assert "mem_high_quality" in migrated_ids, "高质量记忆应该迁移到L2"
        assert "mem_high_ei" in migrated_ids, "高EI记忆应该迁移到L2"
        print(f"  迁移到L2的记忆: {migrated_ids}")

        # 验证迁移后的记忆层级正确
        for item in migrated:
            assert item.layer == MemoryLayer.L2_DEEP, f"迁移后的记忆层级应该是L2_DEEP"
        print("  ✅ 迁移后记忆层级正确（L2_DEEP）")

        print("  ✅ 测试4通过：L1→L2记忆迁移逻辑正常工作")
        return True
    except AssertionError as e:
        print(f"  ❌ 测试4失败：{e}")
        import traceback
        traceback.print_exc()
        return False
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


def main():
    print("\n" + "#" * 60)
    print("#  M5 潮汐记忆系统 - P0问题修复验证")
    print("#" * 60)

    results = {}

    results["测试1_归档接口"] = test_1_archive_no_500()
    results["测试2_私有域隔离"] = test_2_private_domain_isolation()
    results["测试3_L2持久化"] = test_3_l2_sqlite_persistence()
    results["测试4_L1L2迁移"] = test_4_l1_to_l2_migration()

    print("\n" + "=" * 60)
    print("验证结果汇总")
    print("=" * 60)
    all_passed = True
    for name, passed in results.items():
        status = "✅ 通过" if passed else "❌ 失败"
        print(f"  {name}: {status}")
        if not passed:
            all_passed = False

    print("=" * 60)
    if all_passed:
        print("🎉 所有测试通过！P0问题全部修复完成。")
    else:
        print("⚠️  部分测试失败，请检查修复。")
    print("=" * 60 + "\n")

    return 0 if all_passed else 1


if __name__ == "__main__":
    sys.exit(main())
