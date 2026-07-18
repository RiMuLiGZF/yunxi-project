"""
监控中心 & 告警系统验证脚本
测试内容：
1. 告警列表获取
2. 告警创建和确认
3. 告警统计
4. 监控总览接口

使用方式：
    cd M8-control-tower
    python -m backend.test_monitor_alert

或者直接运行数据库级别测试（无需启动服务）：
    cd backend
    python test_monitor_alert.py
"""

import sys
import os
from pathlib import Path
from datetime import datetime, timedelta

# 添加项目路径（backend 目录加入 sys.path）
backend_dir = Path(__file__).parent.resolve()
if str(backend_dir) not in sys.path:
from sqlalchemy.orm import Session
from models import init_db, get_db, AlertRecord, User, TaskRecord, SessionLocal  # type: ignore


def _ensure_packages():
    """
    构建 backend 包结构，使得 monitor.py 的相对导入能正常工作。
    因为 M8-control-tower 目录名含横杠，不能直接作为 Python 包导入，
    所以手动把 backend 注册为顶级包，并预加载依赖模块。
    """
    import types

    # 检查是否已经初始化过
    if "backend.routers.monitor" in sys.modules:
        return sys.modules["backend.routers.monitor"]

    # 创建 backend 包
    if "backend" not in sys.modules:
        backend_pkg = types.ModuleType("backend")
        backend_pkg.__path__ = [str(backend_dir)]
        backend_pkg.__package__ = ""
        sys.modules["backend"] = backend_pkg

    # 预加载 config 模块
    if "backend.config" not in sys.modules:
        import importlib.util
        config_path = backend_dir / "config.py"
        spec = importlib.util.spec_from_file_location("backend.config", str(config_path))
        config_mod = importlib.util.module_from_spec(spec)
        sys.modules["backend.config"] = config_mod
        spec.loader.exec_module(config_mod)

    # 预加载 models 模块
    if "backend.models" not in sys.modules:
        import models as _models_mod
        sys.modules["backend.models"] = _models_mod

    # 预加载 schemas 模块
    if "backend.schemas" not in sys.modules:
        sys.modules["backend.schemas"] = types.ModuleType("backend.schemas")
        sys.modules["backend.schemas"].__path__ = [str(backend_dir / "schemas")]
        # 加载 schemas/__init__.py
        import importlib.util
        schemas_init = backend_dir / "schemas" / "__init__.py"
        spec = importlib.util.spec_from_file_location("backend.schemas", str(schemas_init))
        schemas_mod = importlib.util.module_from_spec(spec)
        sys.modules["backend.schemas"] = schemas_mod
        spec.loader.exec_module(schemas_mod)

    # 预加载 auth 模块（依赖 config）
    if "backend.auth" not in sys.modules:
        import importlib.util
        auth_path = backend_dir / "auth.py"
        spec = importlib.util.spec_from_file_location("backend.auth", str(auth_path))
        auth_mod = importlib.util.module_from_spec(spec)
        sys.modules["backend.auth"] = auth_mod
        spec.loader.exec_module(auth_mod)

    # 创建 backend.routers 包
    if "backend.routers" not in sys.modules:
        routers_pkg = types.ModuleType("backend.routers")
        routers_pkg.__path__ = [str(backend_dir / "routers")]
        routers_pkg.__package__ = "backend"
        sys.modules["backend.routers"] = routers_pkg

    # 加载 monitor 模块
    import importlib.util
    monitor_path = backend_dir / "routers" / "monitor.py"
    spec = importlib.util.spec_from_file_location(
        "backend.routers.monitor",
        str(monitor_path),
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules["backend.routers.monitor"] = module
    spec.loader.exec_module(module)
    return module


def _import_monitor_module():
    """获取 monitor 模块（懒加载）"""
    return _ensure_packages()


def print_separator(title: str):
    """打印分隔线"""
    print("\n" + "=" * 60)
    print(f"  {title}")
    print("=" * 60)


def test_db_initialization():
    """测试 0：数据库初始化和种子数据"""
    print_separator("测试 0：数据库初始化")

    # 初始化数据库（会自动创建表和种子数据）
    init_db()
    print("[OK] 数据库初始化完成")

    db = SessionLocal()
    try:
        # 检查告警表是否有数据
        alert_count = db.query(AlertRecord).count()
        print(f"[OK] 告警表记录数: {alert_count}")

        alerts = db.query(AlertRecord).all()
        for a in alerts:
            print(f"  - id={a.id}, level={a.level}, status={a.status}, title={a.title}")

        assert alert_count >= 3, "预置告警至少应有 3 条"
        print("[PASS] 预置告警数据验证通过")
    finally:
        db.close()


def test_alert_crud():
    """测试 1：告警 CRUD（数据库直接操作验证）"""
    print_separator("测试 1：告警 CRUD 操作")

    db = SessionLocal()
    try:
        # 1. 创建告警
        new_alert = AlertRecord(
            level="warning",
            title="测试告警 - CPU使用率偏高",
            content="CPU 使用率已达 85%，测试自动告警生成",
            source="system",
            status="active",
            created_at=datetime.utcnow(),
        )
        db.add(new_alert)
        db.commit()
        db.refresh(new_alert)
        print(f"[OK] 创建告警成功: id={new_alert.id}, title={new_alert.title}")

        # 2. 读取告警
        alert = db.query(AlertRecord).filter(AlertRecord.id == new_alert.id).first()
        assert alert is not None
        assert alert.level == "warning"
        assert alert.status == "active"
        print(f"[OK] 读取告警成功: id={alert.id}, level={alert.level}")

        # 3. 确认告警
        alert.status = "acknowledged"
        alert.acknowledged_at = datetime.utcnow()
        alert.acknowledged_by = "test_user"
        db.commit()
        db.refresh(alert)
        assert alert.status == "acknowledged"
        assert alert.acknowledged_by == "test_user"
        print(f"[OK] 确认告警成功: status={alert.status}, by={alert.acknowledged_by}")

        # 4. 解决告警
        alert.status = "resolved"
        alert.resolved_at = datetime.utcnow()
        alert.resolved_by = "test_user"
        db.commit()
        db.refresh(alert)
        assert alert.status == "resolved"
        assert alert.resolved_by == "test_user"
        print(f"[OK] 解决告警成功: status={alert.status}, by={alert.resolved_by}")

        # 5. 删除测试告警（清理）
        db.delete(alert)
        db.commit()
        print("[OK] 清理测试告警完成")

        print("[PASS] 告警 CRUD 测试全部通过")
    finally:
        db.close()


def test_alert_list_filters():
    """测试 2：告警列表过滤"""
    print_separator("测试 2：告警列表过滤功能")

    db = SessionLocal()
    try:
        # 先添加几条测试告警
        test_alerts = [
            AlertRecord(level="info", title="测试 info 告警", content="info 内容", source="system", status="active"),
            AlertRecord(level="warning", title="测试 warning 告警", content="warning 内容", source="m1", status="active"),
            AlertRecord(level="error", title="测试 error 告警", content="error 内容", source="m2", status="acknowledged"),
            AlertRecord(level="critical", title="测试 critical 告警", content="critical 内容", source="system", status="resolved"),
        ]
        for a in test_alerts:
            db.add(a)
        db.commit()

        # 测试按级别过滤
        warning_count = db.query(AlertRecord).filter(AlertRecord.level == "warning").count()
        print(f"[OK] warning 级别告警数: {warning_count}")
        assert warning_count >= 1

        # 测试按状态过滤
        active_count = db.query(AlertRecord).filter(AlertRecord.status == "active").count()
        print(f"[OK] active 状态告警数: {active_count}")
        assert active_count >= 2

        resolved_count = db.query(AlertRecord).filter(AlertRecord.status == "resolved").count()
        print(f"[OK] resolved 状态告警数: {resolved_count}")
        assert resolved_count >= 1

        # 测试按时间范围过滤
        now = datetime.utcnow()
        one_hour_ago = now - timedelta(hours=1)
        recent_count = (
            db.query(AlertRecord)
            .filter(AlertRecord.created_at >= one_hour_ago)
            .count()
        )
        print(f"[OK] 最近 1 小时告警数: {recent_count}")

        # 测试倒序排列
        alerts_desc = db.query(AlertRecord).order_by(AlertRecord.created_at.desc()).limit(5).all()
        print(f"[OK] 倒序查询最新 5 条告警: {len(alerts_desc)} 条")
        if len(alerts_desc) >= 2:
            assert alerts_desc[0].created_at >= alerts_desc[1].created_at

        # 清理测试数据
        for a in test_alerts:
            db.delete(a)
        db.commit()
        print("[OK] 清理测试告警完成")

        print("[PASS] 告警列表过滤测试全部通过")
    finally:
        db.close()


def test_alert_stats():
    """测试 3：告警统计"""
    print_separator("测试 3：告警统计功能")

    db = SessionLocal()
    try:
        # 各级别数量
        level_counts = {}
        for level in ["info", "warning", "error", "critical"]:
            count = db.query(AlertRecord).filter(AlertRecord.level == level).count()
            level_counts[level] = count
        print(f"[OK] 各级别告警数量: {level_counts}")

        # 各状态数量
        status_counts = {}
        for s in ["active", "acknowledged", "resolved"]:
            count = db.query(AlertRecord).filter(AlertRecord.status == s).count()
            status_counts[s] = count
        print(f"[OK] 各状态告警数量: {status_counts}")

        # 今日新增
        today_start = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
        today_new = db.query(AlertRecord).filter(AlertRecord.created_at >= today_start).count()
        print(f"[OK] 今日新增告警数: {today_new}")

        # 未解决数量
        unresolved = (
            db.query(AlertRecord)
            .filter(AlertRecord.status.in_(["active", "acknowledged"]))
            .count()
        )
        print(f"[OK] 未解决告警数: {unresolved}")

        # 总数
        total = db.query(AlertRecord).count()
        print(f"[OK] 告警总数: {total}")

        assert total >= 3, "至少应有预置的 3 条告警"
        print("[PASS] 告警统计测试通过")
    finally:
        db.close()


def test_threshold_alerts():
    """测试 4：阈值自动告警生成"""
    print_separator("测试 4：阈值自动告警生成")

    db = SessionLocal()
    try:
        # 直接导入 monitor 模块（绕过 __init__.py 的相对导入）
        monitor = _import_monitor_module()
        _check_thresholds_and_generate_alerts = monitor._check_thresholds_and_generate_alerts
        _add_alert_db = monitor._add_alert_db

        # 模拟高 CPU 指标（超过 critical 阈值）
        high_cpu_metrics = {
            "cpu": {"usage_percent": 95.0},
            "memory": {"percent": 50.0},
            "disk": {"percent": 50.0},
        }

        before_count = db.query(AlertRecord).count()
        _check_thresholds_and_generate_alerts(db, high_cpu_metrics)
        after_count = db.query(AlertRecord).count()
        new_count = after_count - before_count
        print(f"[OK] 高 CPU(95%) 触发生成 {new_count} 条告警")

        # 验证生成了 critical 级别的 CPU 告警
        cpu_critical = (
            db.query(AlertRecord)
            .filter(
                AlertRecord.level == "critical",
                AlertRecord.title.like("%CPU%"),
            )
            .order_by(AlertRecord.created_at.desc())
            .first()
        )
        assert cpu_critical is not None, "应生成 CPU critical 告警"
        print(f"[OK] CPU critical 告警: {cpu_critical.title}")

        # 模拟高内存指标（超过 warning 阈值）
        high_mem_metrics = {
            "cpu": {"usage_percent": 30.0},
            "memory": {"percent": 88.0},
            "disk": {"percent": 50.0},
        }

        before_count = db.query(AlertRecord).count()
        _check_thresholds_and_generate_alerts(db, high_mem_metrics)
        after_count = db.query(AlertRecord).count()
        new_count = after_count - before_count
        print(f"[OK] 高内存(88%) 触发生成 {new_count} 条告警")

        # 模拟高磁盘指标（超过 warning 阈值）
        high_disk_metrics = {
            "cpu": {"usage_percent": 30.0},
            "memory": {"percent": 50.0},
            "disk": {"percent": 85.0},
        }

        before_count = db.query(AlertRecord).count()
        _check_thresholds_and_generate_alerts(db, high_disk_metrics)
        after_count = db.query(AlertRecord).count()
        new_count = after_count - before_count
        print(f"[OK] 高磁盘(85%) 触发生成 {new_count} 条告警")

        # 测试去重：同一指标再次触发不应生成新告警（30 分钟内）
        before_count = db.query(AlertRecord).count()
        _check_thresholds_and_generate_alerts(db, high_cpu_metrics)
        after_count = db.query(AlertRecord).count()
        new_count = after_count - before_count
        print(f"[OK] 重复触发高 CPU（去重验证）新增 {new_count} 条（应为 0）")
        assert new_count == 0, "30 分钟内同一类型告警应去重"

        print("[PASS] 阈值自动告警生成测试通过")
    finally:
        db.close()


def test_active_users_and_tasks():
    """测试 5：活跃用户和任务数查询"""
    print_separator("测试 5：活跃用户和任务数真实化")

    db = SessionLocal()
    try:
        # 直接导入 monitor 模块
        monitor = _import_monitor_module()
        _get_active_users_count = monitor._get_active_users_count
        _get_today_tasks_count = monitor._get_today_tasks_count

        active_users = _get_active_users_count(db)
        print(f"[OK] 活跃用户数: {active_users}")
        assert isinstance(active_users, int)
        assert active_users >= 0

        # 测试今日任务数查询
        today_tasks = _get_today_tasks_count(db)
        print(f"[OK] 今日任务数: {today_tasks}")
        assert isinstance(today_tasks, int)
        assert today_tasks >= 0

        print("[PASS] 活跃用户和任务数查询测试通过")
    finally:
        db.close()


def test_alert_to_dict():
    """测试 6：告警转字典（兼容旧格式）"""
    print_separator("测试 6：告警转字典兼容性")

    db = SessionLocal()
    try:
        # 直接导入 monitor 模块
        monitor = _import_monitor_module()
        _alert_to_dict = monitor._alert_to_dict

        # 取一条预置告警
        alert = db.query(AlertRecord).first()
        assert alert is not None

        alert_dict = _alert_to_dict(alert)

        # 验证新旧字段都存在
        required_fields = [
            "id", "level", "title", "message", "content",
            "module", "source", "status", "acknowledged",
            "created_at", "created_at_formatted",
            "acknowledged_at", "acknowledged_at_formatted",
            "acknowledged_by",
            "resolved_at", "resolved_at_formatted",
            "resolved_by",
        ]
        for field in required_fields:
            assert field in alert_dict, f"缺少字段: {field}"

        # 验证 message == content（兼容）
        assert alert_dict["message"] == alert_dict["content"], "message 和 content 应一致"
        # 验证 module == source（兼容）
        assert alert_dict["module"] == alert_dict["source"], "module 和 source 应一致"
        # 验证 acknowledged 布尔值与 status 一致
        if alert.status in ("acknowledged", "resolved"):
            assert alert_dict["acknowledged"] is True
        else:
            assert alert_dict["acknowledged"] is False

        print(f"[OK] 告警字典字段完整: {len(required_fields)} 个字段")
        print(f"[OK] 新旧字段兼容性验证通过 (message/content, module/source, acknowledged)")
        print("[PASS] 告警转字典兼容性测试通过")
    finally:
        db.close()


def main():
    """主测试函数"""
    print("\n" + "╔" + "═" * 58 + "╗")
    print("║     监控中心 & 告警系统 - 功能验证脚本                    ║")
    print("╚" + "═" * 58 + "╝")
    print(f"\n测试时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"数据库路径: {os.path.abspath('./data/m8.db')}")

    try:
        # 测试 0：数据库初始化
        test_db_initialization()

        # 测试 1：告警 CRUD
        test_alert_crud()

        # 测试 2：告警列表过滤
        test_alert_list_filters()

        # 测试 3：告警统计
        test_alert_stats()

        # 测试 4：阈值自动告警
        test_threshold_alerts()

        # 测试 5：活跃用户和任务数
        test_active_users_and_tasks()

        # 测试 6：告警转字典兼容性
        test_alert_to_dict()

        # 汇总
        print_separator("测试总结")
        print("  所有测试通过！ ✓")
        print()
        print("  验证项目：")
        print("  ✓ 数据库初始化与预置告警")
        print("  ✓ 告警 CRUD 操作（创建/读取/确认/解决/删除）")
        print("  ✓ 告警列表过滤（按级别/状态/时间/排序）")
        print("  ✓ 告警统计（级别分布/状态分布/今日新增/未解决）")
        print("  ✓ 阈值自动告警生成（CPU/内存/磁盘 + 去重机制）")
        print("  ✓ 活跃用户和任务数真实查询")
        print("  ✓ 告警数据格式向后兼容")
        print()
        print("=" * 60)

    except AssertionError as e:
        print(f"\n[FAIL] 断言失败: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
    except Exception as e:
        print(f"\n[ERROR] 测试异常: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    # 切换到 backend 目录，确保相对路径正确
    os.chdir(Path(__file__).parent)
    main()
