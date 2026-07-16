#!/usr/bin/env python3
"""
快速验证脚本 - 快速检查系统核心功能

使用方法:
    python tools/ci/quick-check.py
    python tools/ci/quick-check.py --full
"""
import sys
import os
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))


def check_imports():
    """检查核心模块导入"""
    print("=== 1. 核心模块导入检查 ===")
    checks = [
        ("shared.observability", "可观测性模块"),
        ("shared.data_layer", "数据层模块"),
        ("shared.middleware.tracing", "链路追踪中间件"),
        ("shared.config", "配置模块"),
        ("shared.llm_client", "LLM客户端"),
        ("shared.module_client", "模块调用客户端"),
    ]
    
    passed = 0
    failed = 0
    for module_name, desc in checks:
        try:
            __import__(module_name)
            print(f"  ✓ {desc} ({module_name})")
            passed += 1
        except Exception as e:
            print(f"  ✗ {desc} ({module_name}): {e}")
            failed += 1
    
    print(f"  结果: {passed} 通过, {failed} 失败")
    return failed == 0


def check_file_structure():
    """检查目录结构"""
    print("\n=== 2. 目录结构检查 ===")
    
    required_dirs = [
        "M0-principal-console",
        "M1-agent-hub",
        "M2-skills-cluster",
        "M3-edge-cloud",
        "M4-scene-engine",
        "M5-tide-memory",
        "M6-hardware-peripheral",
        "M7-workflow-builder",
        "M8-control-tower",
        "M9-dev-workshop",
        "M10-system-guard",
        "M11-mcp-bus",
        "M12-security-shield",
        "API-Gateway",
        "shared",
        "config",
    ]
    
    required_files = [
        "start-all.ps1",
        "stop-all.ps1",
        "README.md",
    ]
    
    passed = 0
    failed = 0
    
    for d in required_dirs:
        if (PROJECT_ROOT / d).exists():
            print(f"  ✓ {d}/")
            passed += 1
        else:
            print(f"  ✗ {d}/ 缺失")
            failed += 1
    
    for f in required_files:
        if (PROJECT_ROOT / f).exists():
            print(f"  ✓ {f}")
            passed += 1
        else:
            print(f"  ✗ {f} 缺失")
            failed += 1
    
    print(f"  结果: {passed} 通过, {failed} 失败")
    return failed == 0


def check_shared_modules():
    """检查shared子模块"""
    print("\n=== 3. Shared 子模块检查 ===")
    
    shared_dirs = [
        "observability",
        "data_layer",
        "middleware",
        "distributed",
    ]
    
    passed = 0
    failed = 0
    
    shared_path = PROJECT_ROOT / "shared"
    for d in shared_dirs:
        if (shared_path / d).exists():
            py_files = list((shared_path / d).glob("*.py"))
            print(f"  ✓ {d}/ ({len(py_files)} py files)")
            passed += 1
        else:
            print(f"  ✗ {d}/ 缺失")
            failed += 1
    
    print(f"  结果: {passed} 通过, {failed} 失败")
    return failed == 0


def check_observability():
    """测试可观测性功能"""
    print("\n=== 4. 可观测性功能测试 ===")
    
    try:
        from shared.observability import get_logger, get_metrics, start_trace, end_trace
        
        # 测试日志
        logger = get_logger("test-observability")
        logger.info("测试日志 - 可观测性模块正常")
        print("  ✓ 日志系统")
        
        # 测试指标
        metrics = get_metrics()
        metrics.inc("test_counter_total", labels={"test": "true"})
        m = metrics.get_all()
        print(f"  ✓ 指标系统 ({m['total_metrics']} 个指标)")
        
        # 测试追踪
        trace = start_trace("test-trace-id-123")
        span = trace.start_span("test_operation")
        span.end()
        summary = trace.get_trace_summary()
        print(f"  ✓ 追踪系统 (trace_id={summary['trace_id'][:8]}..., spans={summary['span_count']})")
        
        return True
    except Exception as e:
        print(f"  ✗ 失败: {e}")
        import traceback
        traceback.print_exc()
        return False


def check_data_layer():
    """测试数据层功能"""
    print("\n=== 5. 数据层功能测试 ===")
    
    try:
        from shared.data_layer import DatabaseManager, BackupManager, MigrationEngine
        
        # 测试 DatabaseManager
        db = DatabaseManager(data_root=str(PROJECT_ROOT / "data" / "ci_test"))
        db.execute("test", "CREATE TABLE IF NOT EXISTS test (id INTEGER PRIMARY KEY, name TEXT)")
        db.execute("test", "INSERT INTO test (name) VALUES (?)", ("hello",))
        result = db.query_one("test", "SELECT * FROM test WHERE id=?", (1,))
        assert result["name"] == "hello"
        health = db.health_check("test")
        assert health["status"] == "healthy"
        print(f"  ✓ DatabaseManager (status={health['status']})")
        
        # 测试 BackupManager
        bm = BackupManager(
            backup_root=str(PROJECT_ROOT / "data" / "ci_backups"),
            data_root=str(PROJECT_ROOT / "data" / "ci_test"),
        )
        backup_result = bm.backup_database(
            str(PROJECT_ROOT / "data" / "ci_test" / "test.db"),
            "ci_test_backup.db"
        )
        assert backup_result["success"]
        print(f"  ✓ BackupManager (size={backup_result['size_mb']} MB)")
        
        # 测试 MigrationEngine
        me = MigrationEngine(db)
        migrations = [
            {"version": 1, "name": "add_email", "up": "ALTER TABLE test ADD COLUMN email TEXT"}
        ]
        result = me.migrate("test", migrations)
        assert result["success"]
        ver = me.get_current_version("test")
        assert ver == 1
        print(f"  ✓ MigrationEngine (version={ver})")
        
        # 清理
        db.close()
        
        return True
    except Exception as e:
        print(f"  ✗ 失败: {e}")
        import traceback
        traceback.print_exc()
        return False


def main():
    import argparse
    parser = argparse.ArgumentParser(description="云汐系统快速验证")
    parser.add_argument("--full", action="store_true", help="完整检查（含功能测试）")
    args = parser.parse_args()
    
    print("=" * 60)
    print("云汐系统 - 快速验证")
    print("=" * 60)
    
    all_passed = True
    
    # 基础检查（总是执行）
    all_passed &= check_file_structure()
    all_passed &= check_imports()
    all_passed &= check_shared_modules()
    
    # 完整检查
    if args.full:
        all_passed &= check_observability()
        all_passed &= check_data_layer()
    
    print("\n" + "=" * 60)
    if all_passed:
        print("✓ 所有检查通过！")
        return 0
    else:
        print("✗ 部分检查失败")
        return 1


if __name__ == "__main__":
    sys.exit(main())
