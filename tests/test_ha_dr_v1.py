"""
云汐系统 V1.0 高可用与容灾综合测试
====================================

测试覆盖：
1. 高可用架构（健康检查、负载均衡、故障转移、服务注册）
2. 数据容灾（增强备份、恢复管理、数据库HA、备份调度）
3. 故障演练（故障注入、演练运行、报告生成）

总计: 40+ 测试用例
"""

from __future__ import annotations

import os
import sys
import time
import json
import tempfile
import shutil
import sqlite3
import pytest
from pathlib import Path

# 添加 shared 到路径
_project_root = Path(__file__).resolve().parent.parent
_shared_path = _project_root / "shared"
if str(_shared_path) not in sys.path:
from core.ha import (  # noqa: E402
    HealthCheckerPro,
    HealthCheckType,
    TcpHealthCheck,
    ResourceHealthCheck,
    create_load_balancer,
    LoadBalanceStrategy,
    ServiceInstance,
    FailoverManager,
    FailoverMode,
    FailoverState,
    ServiceRegistry,
    ServiceInstanceInfo,
    ServiceStatus,
)

from core.chaos import (  # noqa: E402
    FaultInjector,
    FaultType,
    FaultSeverity,
    DrillsRunner,
    module_outage_drill,
    database_failover_drill,
    network_partition_drill,
    full_system_recovery_drill,
    ReportGenerator,
)

from data.data_layer.disaster_recovery import (  # noqa: E402
    EnhancedBackupManager,
    BackupMode,
    ValidationLevel,
    RemoteBackupConfig,
    RecoveryManager,
    RecoveryMode,
    DatabaseHA,
    WALConfig,
    ConnectionPoolConfig,
    DBHealthStatus,
    BackupScheduler,
    ScheduleType,
)


# ============================================================
# Fixtures
# ============================================================

@pytest.fixture
def temp_dir():
    """临时目录 fixture"""
    d = tempfile.mkdtemp(prefix="yunxi_test_")
    yield Path(d)
    shutil.rmtree(d, ignore_errors=True)


@pytest.fixture
def test_db(temp_dir):
    """测试数据库 fixture"""
    db_path = temp_dir / "test.db"
    conn = sqlite3.connect(str(db_path))
    conn.execute("CREATE TABLE test_table (id INTEGER PRIMARY KEY, name TEXT)")
    conn.execute("INSERT INTO test_table (name) VALUES ('test1')")
    conn.execute("INSERT INTO test_table (name) VALUES ('test2')")
    conn.commit()
    conn.close()
    return db_path


@pytest.fixture
def backup_dir(temp_dir):
    """备份目录 fixture"""
    d = temp_dir / "backups"
    d.mkdir()
    return d


@pytest.fixture
def data_dir(temp_dir):
    """数据目录 fixture"""
    d = temp_dir / "data"
    d.mkdir()
    # 创建测试数据库
    db_path = d / "test.db"
    conn = sqlite3.connect(str(db_path))
    conn.execute("CREATE TABLE users (id INTEGER PRIMARY KEY, name TEXT)")
    conn.execute("INSERT INTO users (name) VALUES ('alice')")
    conn.execute("INSERT INTO users (name) VALUES ('bob')")
    conn.commit()
    conn.close()
    return d


# ============================================================
# 一、健康检查增强测试 (8 tests)
# ============================================================

class TestHealthCheckerPro:
    """健康检查增强测试"""

    def test_create_checker(self):
        """测试创建健康检查器"""
        checker = HealthCheckerPro(module_name="test", version="1.0.0")
        assert checker.module_name == "test"
        assert checker.version == "1.0.0"

    def test_register_tcp_check(self):
        """测试注册 TCP 检查"""
        checker = HealthCheckerPro(module_name="test")
        checker.register_tcp_check("db", "127.0.0.1", 65535)  # 不存在的端口
        assert "db" in checker.get_check_names()

    def test_register_resource_check(self):
        """测试注册资源检查"""
        checker = HealthCheckerPro(module_name="test")
        checker.register_resource_check("resource", cpu_threshold=100, memory_threshold=100)
        assert "resource" in checker.get_check_names()

    def test_check_all_returns_dict(self):
        """测试 check_all 返回结构"""
        checker = HealthCheckerPro(module_name="test")
        checker.register_resource_check("resource", cpu_threshold=100, memory_threshold=100)
        result = checker.check_all()
        assert "overall_status" in result
        assert "check_count" in result
        assert "checks" in result
        assert result["module"] == "test"

    def test_check_single(self):
        """测试单个检查"""
        checker = HealthCheckerPro(module_name="test")
        checker.register_resource_check("resource")
        result = checker.check_single("resource")
        assert result is not None
        assert result.check_name == "resource"

    def test_manual_remove_and_recover(self):
        """测试手动摘除和恢复"""
        checker = HealthCheckerPro(module_name="test")
        checker.register_resource_check("resource")
        checker.check_all()

        # 手动摘除
        result = checker.manual_remove("resource", "test")
        assert result is True
        assert "resource" in checker.get_removed_checks()

        # 手动恢复
        result = checker.manual_recover("resource", "test")
        assert result is True
        assert "resource" not in checker.get_removed_checks()

    def test_get_check_state(self):
        """测试获取检查状态"""
        checker = HealthCheckerPro(module_name="test")
        checker.register_resource_check("resource")
        state = checker.get_check_state("resource")
        assert state is not None
        assert state["name"] == "resource"

    def test_get_all_states(self):
        """测试获取所有状态"""
        checker = HealthCheckerPro(module_name="test")
        checker.register_resource_check("res1")
        checker.register_resource_check("res2")
        states = checker.get_all_states()
        assert len(states) == 2

    def test_get_trend_analysis(self):
        """测试趋势分析"""
        checker = HealthCheckerPro(module_name="test")
        checker.register_resource_check("resource")
        # 执行几次检查
        for _ in range(3):
            checker.check_all()
        trend = checker.get_trend_analysis("resource")
        assert "available" in trend


# ============================================================
# 二、TCP 健康检查测试 (3 tests)
# ============================================================

class TestTcpHealthCheck:
    """TCP 健康检查测试"""

    def test_tcp_check_unreachable_port(self):
        """测试不可达端口检查"""
        check = TcpHealthCheck(name="test", host="127.0.0.1", port=65535, timeout=1)
        result = check.check()
        assert result.check_name == "test"
        assert result.check_type == HealthCheckType.TCP
        # 不可达端口应该是不健康的
        assert result.status.value in ("unhealthy", "degraded")

    def test_tcp_check_localhost_known_port(self):
        """测试 localhost 上的已知服务"""
        # 80 端口通常没有服务，应该返回不健康
        check = TcpHealthCheck(name="test", host="127.0.0.1", port=80, timeout=1)
        result = check.check()
        assert result.check_type == HealthCheckType.TCP

    def test_tcp_check_to_dict(self):
        """TCP 检查结果序列化"""
        check = TcpHealthCheck(name="test", host="127.0.0.1", port=80, timeout=1)
        result = check.check()
        d = result.to_dict()
        assert d["check_name"] == "test"
        assert "response_time_ms" in d
        assert "details" in d


# ============================================================
# 三、资源健康检查测试 (3 tests)
# ============================================================

class TestResourceHealthCheck:
    """资源健康检查测试"""

    def test_resource_check_returns_result(self):
        """测试资源检查返回结果"""
        check = ResourceHealthCheck(name="resource")
        result = check.check()
        assert result.check_name == "resource"
        assert result.check_type == HealthCheckType.RESOURCE

    def test_resource_check_high_threshold(self):
        """测试高阈值下应该健康"""
        check = ResourceHealthCheck(
            name="resource",
            cpu_threshold=100,
            memory_threshold=100,
            disk_threshold=100,
        )
        result = check.check()
        # 正常情况下应该健康
        assert result.status.value in ("healthy", "degraded")

    def test_resource_check_details(self):
        """测试资源检查详情"""
        check = ResourceHealthCheck(name="resource")
        result = check.check()
        assert "cpu" in result.details or "memory" in result.details or "disk" in result.details


# ============================================================
# 四、负载均衡测试 (10 tests)
# ============================================================

class TestLoadBalancer:
    """负载均衡测试"""

    def _add_instances(self, lb, count=3):
        for i in range(count):
            lb.add_instance(f"node{i}", f"http://127.0.0.1:800{i}", weight=i + 1)

    def test_round_robin(self):
        """测试轮询负载均衡"""
        lb = create_load_balancer(LoadBalanceStrategy.ROUND_ROBIN, "test")
        self._add_instances(lb, 3)

        instances = []
        for _ in range(6):
            inst = lb.next_instance()
            assert inst is not None
            instances.append(inst.instance_id)

        # 应该轮询
        assert instances[0] != instances[1]
        assert instances[0] == instances[3]

    def test_weighted_round_robin(self):
        """测试加权轮询"""
        lb = create_load_balancer(LoadBalanceStrategy.WEIGHTED_ROUND_ROBIN, "test")
        lb.add_instance("heavy", "http://127.0.0.1:8001", weight=3)
        lb.add_instance("light", "http://127.0.0.1:8002", weight=1)

        counts = {"heavy": 0, "light": 0}
        for _ in range(40):  # 4 = 3 + 1，10轮
            inst = lb.next_instance()
            counts[inst.instance_id] += 1

        # 比例大约 3:1
        assert counts["heavy"] > counts["light"]

    def test_least_connections(self):
        """测试最少连接"""
        lb = create_load_balancer(LoadBalanceStrategy.LEAST_CONNECTIONS, "test")
        self._add_instances(lb, 3)

        # 给 node0 增加连接
        lb.increment_connection("node0")
        lb.increment_connection("node0")

        # 应该选连接最少的
        inst = lb.next_instance()
        assert inst.instance_id != "node0"

    def test_fastest_response(self):
        """测试最快响应"""
        lb = create_load_balancer(LoadBalanceStrategy.FASTEST_RESPONSE, "test")
        self._add_instances(lb, 3)

        # 记录不同响应时间
        lb.record_request("node0", 100, True)
        lb.record_request("node1", 50, True)
        lb.record_request("node2", 200, True)

        # 应该选最快的 (node1)
        inst = lb.next_instance()
        assert inst is not None

    def test_consistent_hash(self):
        """测试一致性哈希"""
        lb = create_load_balancer(LoadBalanceStrategy.CONSISTENT_HASH, "test")
        self._add_instances(lb, 3)

        # 相同 key 应该路由到相同实例
        inst1 = lb.next_instance("user123")
        inst2 = lb.next_instance("user123")
        assert inst1.instance_id == inst2.instance_id

        # 不同 key 可能路由到不同实例
        inst3 = lb.next_instance("user456")
        # 可能相同也可能不同，但应该都有效
        assert inst3 is not None

    def test_unhealthy_instance_skipped(self):
        """测试不健康实例被跳过"""
        from core.ha.load_balancer import InstanceStatus
        lb = create_load_balancer(LoadBalanceStrategy.ROUND_ROBIN, "test")
        lb.add_instance("healthy", "http://127.0.0.1:8001")
        lb.add_instance("unhealthy", "http://127.0.0.1:8002")
        lb.mark_unhealthy("unhealthy")

        # 应该总是选健康的
        for _ in range(10):
            inst = lb.next_instance()
            assert inst.instance_id == "healthy"

    def test_no_healthy_instance(self):
        """测试没有健康实例时返回 None"""
        from core.ha.load_balancer import InstanceStatus
        lb = create_load_balancer(LoadBalanceStrategy.ROUND_ROBIN, "test")
        lb.add_instance("bad", "http://127.0.0.1:8001")
        lb.mark_unhealthy("bad")

        inst = lb.next_instance()
        assert inst is None

    def test_add_remove_instance(self):
        """测试添加和移除实例"""
        lb = create_load_balancer(LoadBalanceStrategy.ROUND_ROBIN, "test")
        assert lb.add_instance("node1", "http://127.0.0.1:8001") is True
        assert lb.get_instance_count() == 1

        # 重复添加失败
        assert lb.add_instance("node1", "http://127.0.0.1:8001") is False

        # 移除
        assert lb.remove_instance("node1") is True
        assert lb.get_instance_count() == 0

    def test_get_stats(self):
        """测试统计信息"""
        lb = create_load_balancer(LoadBalanceStrategy.ROUND_ROBIN, "test")
        self._add_instances(lb, 2)
        stats = lb.get_stats()
        assert stats["service_name"] == "test"
        assert stats["instance_count"] == 2
        assert stats["healthy_count"] == 2

    def test_connection_tracking(self):
        """测试连接计数"""
        lb = create_load_balancer(LoadBalanceStrategy.LEAST_CONNECTIONS, "test")
        lb.add_instance("node1", "http://127.0.0.1:8001")

        lb.increment_connection("node1")
        lb.increment_connection("node1")

        inst = lb.get_instance("node1")
        assert inst.active_connections == 2

        lb.decrement_connection("node1")
        inst = lb.get_instance("node1")
        assert inst.active_connections == 1


# ============================================================
# 五、故障转移测试 (5 tests)
# ============================================================

class TestFailoverManager:
    """故障转移管理器测试"""

    def test_create_manager(self):
        """测试创建故障转移管理器"""
        fm = FailoverManager(service_name="test", mode=FailoverMode.ACTIVE_PASSIVE)
        assert fm.service_name == "test"
        assert fm.state == FailoverState.INITIALIZING

    def test_set_primary_and_standby(self):
        """测试设置主备节点"""
        fm = FailoverManager(service_name="test")
        fm.set_primary("node1", "http://127.0.0.1:8001")
        fm.set_standby("node2", "http://127.0.0.1:8002")

        primary = fm.get_primary()
        standby = fm.get_standby()
        assert primary is not None
        assert primary.node_id == "node1"
        assert standby is not None
        assert standby.node_id == "node2"

    def test_manual_failover(self):
        """测试手动故障转移"""
        fm = FailoverManager(service_name="test", switch_cooldown=0)
        fm.set_primary("node1", "http://127.0.0.1:8001")
        fm.set_standby("node2", "http://127.0.0.1:8002")

        event = fm.trigger_failover("test")
        assert event.event_type == "failover"
        assert event.from_node == "node1"
        assert event.to_node == "node2"

        # 切换后 node2 应该是主节点
        primary = fm.get_primary()
        assert primary.node_id == "node2"

    def test_manual_recovery(self):
        """测试手动恢复"""
        fm = FailoverManager(service_name="test", switch_cooldown=0)
        fm.set_primary("node1", "http://127.0.0.1:8001")
        fm.set_standby("node2", "http://127.0.0.1:8002")

        # 先故障转移
        fm.trigger_failover("test")

        # 再恢复
        event = fm.trigger_recovery("test")
        assert event.event_type == "recovery"

        # node1 应该恢复为主节点
        primary = fm.get_primary()
        assert primary.node_id == "node1"

    def test_get_stats(self):
        """测试统计信息"""
        fm = FailoverManager(service_name="test")
        fm.set_primary("node1", "http://127.0.0.1:8001")
        fm.set_standby("node2", "http://127.0.0.1:8002")

        stats = fm.get_stats()
        assert stats["service_name"] == "test"
        assert stats["node_count"] == 2
        assert "primary_node" in stats


# ============================================================
# 六、服务注册表测试 (5 tests)
# ============================================================

class TestServiceRegistry:
    """服务注册表测试"""

    def test_register_and_deregister(self):
        """测试注册和注销"""
        registry = ServiceRegistry()
        registry.clear()

        instance = ServiceInstanceInfo(
            service_name="test_service",
            instance_id="node1",
            host="127.0.0.1",
            port=8001,
        )

        assert registry.register_instance(instance) is True
        assert registry.get_service_count() == 1

        assert registry.deregister_instance("test_service", "node1") is True
        assert registry.get_service_count() == 0

    def test_heartbeat(self):
        """测试心跳"""
        registry = ServiceRegistry()
        registry.clear()

        instance = ServiceInstanceInfo(
            service_name="test",
            instance_id="node1",
            host="127.0.0.1",
            port=8001,
        )
        registry.register_instance(instance)

        assert registry.heartbeat("test", "node1") is True
        assert registry.heartbeat("nonexistent", "node1") is False

    def test_get_healthy_instances(self):
        """测试获取健康实例"""
        registry = ServiceRegistry()
        registry.clear()

        registry.register_instance(ServiceInstanceInfo(
            service_name="test", instance_id="h1", host="127.0.0.1", port=8001,
            status=ServiceStatus.HEALTHY,
        ))
        registry.register_instance(ServiceInstanceInfo(
            service_name="test", instance_id="u1", host="127.0.0.1", port=8002,
            status=ServiceStatus.UNHEALTHY,
        ))

        healthy = registry.get_healthy_instances("test")
        assert len(healthy) == 1
        assert healthy[0].instance_id == "h1"

    def test_mark_unhealthy(self):
        """测试标记不健康"""
        registry = ServiceRegistry()
        registry.clear()

        registry.register_instance(ServiceInstanceInfo(
            service_name="test", instance_id="node1", host="127.0.0.1", port=8001,
        ))

        assert registry.mark_unhealthy("test", "node1") is True
        healthy = registry.get_healthy_instances("test")
        assert len(healthy) == 0

    def test_get_stats(self):
        """测试统计"""
        registry = ServiceRegistry()
        registry.clear()

        registry.register_instance(ServiceInstanceInfo(
            service_name="svc1", instance_id="n1", host="127.0.0.1", port=8001,
        ))
        registry.register_instance(ServiceInstanceInfo(
            service_name="svc1", instance_id="n2", host="127.0.0.1", port=8002,
        ))

        stats = registry.get_stats()
        assert stats["service_count"] == 1
        assert stats["total_instances"] == 2


# ============================================================
# 七、增强备份测试 (5 tests)
# ============================================================

class TestEnhancedBackup:
    """增强备份测试"""

    def test_full_backup(self, data_dir, backup_dir):
        """测试全量备份"""
        ebm = EnhancedBackupManager(
            backup_root=str(backup_dir),
            data_root=str(data_dir),
        )

        result = ebm.full_backup("test.db")
        assert result["success"] is True
        assert result["backup_type"] == "full"
        assert "backup_id" in result
        assert result["size_bytes"] > 0

    def test_incremental_backup(self, data_dir, backup_dir):
        """测试增量备份"""
        ebm = EnhancedBackupManager(
            backup_root=str(backup_dir),
            data_root=str(data_dir),
        )

        # 先做一次全量
        ebm.full_backup("test.db")

        # 修改数据
        db_path = data_dir / "test.db"
        conn = sqlite3.connect(str(db_path))
        conn.execute("INSERT INTO users (name) VALUES ('charlie')")
        conn.commit()
        conn.close()

        # 增量备份
        result = ebm.incremental_backup("test.db")
        assert result["success"] is True
        assert result["backup_type"] == "incremental"

    def test_backup_validation(self, data_dir, backup_dir):
        """测试备份验证"""
        ebm = EnhancedBackupManager(
            backup_root=str(backup_dir),
            data_root=str(data_dir),
        )

        result = ebm.full_backup("test.db")
        backup_id = result["backup_id"]

        # 完整性验证
        validation = ebm.validate_backup(backup_id, ValidationLevel.INTEGRITY)
        assert validation.passed is True
        assert validation.integrity_passed is True
        assert validation.table_count >= 1

    def test_list_backups(self, data_dir, backup_dir):
        """测试列出备份"""
        ebm = EnhancedBackupManager(
            backup_root=str(backup_dir),
            data_root=str(data_dir),
        )

        ebm.full_backup("test.db", backup_name="backup_1")
        time.sleep(0.1)
        ebm.full_backup("test.db", backup_name="backup_2")

        backups = ebm.list_backups()
        assert len(backups) >= 2

    def test_delete_backup(self, data_dir, backup_dir):
        """测试删除备份"""
        ebm = EnhancedBackupManager(
            backup_root=str(backup_dir),
            data_root=str(data_dir),
        )

        result = ebm.full_backup("test.db")
        backup_id = result["backup_id"]

        assert ebm.delete_backup(backup_id) is True
        assert ebm.get_backup(backup_id) is None


# ============================================================
# 八、数据恢复测试 (3 tests)
# ============================================================

class TestRecoveryManager:
    """数据恢复测试"""

    def test_full_recovery(self, data_dir, backup_dir):
        """测试全量恢复"""
        # 创建备份
        ebm = EnhancedBackupManager(
            backup_root=str(backup_dir),
            data_root=str(data_dir),
        )
        result = ebm.full_backup("test.db")
        backup_id = result["backup_id"]

        # 删除原数据
        (data_dir / "test.db").unlink()

        # 恢复
        rm = RecoveryManager(
            backup_root=str(backup_dir),
            data_root=str(data_dir),
        )
        recovery = rm.full_recovery(backup_id, "test.db", create_safety_backup=False)
        assert recovery.success is True
        assert recovery.backup_id == backup_id

        # 验证数据
        db_path = data_dir / "test.db"
        assert db_path.exists()
        conn = sqlite3.connect(str(db_path))
        count = conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]
        conn.close()
        assert count == 2

    def test_recovery_progress(self, data_dir, backup_dir):
        """测试恢复进度跟踪"""
        ebm = EnhancedBackupManager(
            backup_root=str(backup_dir),
            data_root=str(data_dir),
        )
        result = ebm.full_backup("test.db")
        backup_id = result["backup_id"]

        (data_dir / "test.db").unlink()

        rm = RecoveryManager(
            backup_root=str(backup_dir),
            data_root=str(data_dir),
        )

        recovery = rm.full_recovery(backup_id, "test.db", create_safety_backup=False)
        progress = rm.get_progress(recovery.recovery_id)
        assert progress is not None
        assert progress.phase.value in ("completed", "failed")

    def test_recovery_validation(self, data_dir, backup_dir):
        """测试恢复验证"""
        ebm = EnhancedBackupManager(
            backup_root=str(backup_dir),
            data_root=str(data_dir),
        )
        result = ebm.full_backup("test.db")
        backup_id = result["backup_id"]

        (data_dir / "test.db").unlink()

        rm = RecoveryManager(
            backup_root=str(backup_dir),
            data_root=str(data_dir),
        )

        recovery = rm.full_recovery(backup_id, "test.db", create_safety_backup=False, validate_after=True)
        assert recovery.validation_passed is True


# ============================================================
# 九、数据库高可用测试 (3 tests)
# ============================================================

class TestDatabaseHA:
    """数据库高可用测试"""

    def test_wal_optimization(self, test_db):
        """测试 WAL 优化"""
        dha = DatabaseHA(str(test_db))
        result = dha.optimize_wal()
        assert result["success"] is True
        assert "journal_mode" in result

    def test_connection_pool(self, test_db):
        """测试连接池"""
        dha = DatabaseHA(
            str(test_db),
            pool_config=ConnectionPoolConfig(max_connections=5, min_connections=1),
        )
        dha.initialize()

        conn = dha.get_connection()
        assert conn is not None

        # 执行查询
        cursor = conn.cursor()
        cursor.execute("SELECT 1")
        assert cursor.fetchone()[0] == 1

        dha.release_connection(conn)

    def test_health_check(self, test_db):
        """测试健康检查"""
        dha = DatabaseHA(str(test_db))
        dha.initialize()

        stats = dha.get_stats()
        assert "health_status" in stats
        assert stats["health_status"] in ("healthy", "unknown")


# ============================================================
# 十、备份调度测试 (2 tests)
# ============================================================

class TestBackupScheduler:
    """备份调度器测试"""

    def test_add_schedule(self, data_dir, backup_dir):
        """测试添加调度任务"""
        scheduler = BackupScheduler(
            backup_root=str(backup_dir),
            data_root=str(data_dir),
        )

        result = scheduler.add_schedule(
            schedule_id="daily",
            name="每日备份",
            database="test.db",
            backup_mode="full",
            schedule_type=ScheduleType.DAILY,
            hour=2,
            minute=0,
        )
        assert result is True

        schedule = scheduler.get_schedule("daily")
        assert schedule is not None
        assert schedule.name == "每日备份"

    def test_trigger_now(self, data_dir, backup_dir):
        """测试立即触发"""
        scheduler = BackupScheduler(
            backup_root=str(backup_dir),
            data_root=str(data_dir),
        )

        scheduler.add_schedule(
            schedule_id="test",
            name="测试",
            database="test.db",
            backup_mode="full",
        )

        result = scheduler.trigger_now("test")
        assert result is not None
        assert result.get("success") is True


# ============================================================
# 十一、故障注入测试 (4 tests)
# ============================================================

class TestFaultInjector:
    """故障注入测试"""

    def test_inject_module_outage(self):
        """测试模块故障注入"""
        injector = FaultInjector()
        fault = injector.inject(
            target="m1",
            fault_type=FaultType.MODULE_OUTAGE,
            duration=10,
        )
        assert fault.fault_id is not None
        assert fault.fault_type == FaultType.MODULE_OUTAGE
        assert fault.target == "m1"

    def test_inject_network_latency(self):
        """测试网络延迟注入"""
        injector = FaultInjector()
        fault = injector.inject(
            target="m1",
            fault_type=FaultType.NETWORK_LATENCY,
            duration=5,
            parameters={"latency_ms": 500},
        )
        assert fault.fault_type == FaultType.NETWORK_LATENCY

    def test_recover_fault(self):
        """测试故障恢复"""
        injector = FaultInjector()
        fault = injector.inject(
            target="m1",
            fault_type=FaultType.MODULE_OUTAGE,
            duration=60,
        )

        recovered = injector.recover(fault.fault_id)
        assert recovered is not None
        assert recovered.state.value == "recovered"

    def test_recover_all(self):
        """测试全部恢复"""
        injector = FaultInjector()
        injector.inject(target="m1", fault_type=FaultType.MODULE_OUTAGE, duration=60)
        injector.inject(target="m2", fault_type=FaultType.ERROR_RESPONSE, duration=60)

        count = injector.recover_all()
        assert count >= 2
        assert len(injector.get_active_faults()) == 0


# ============================================================
# 十二、演练运行测试 (4 tests)
# ============================================================

class TestDrillsRunner:
    """演练运行测试"""

    def test_module_outage_drill(self):
        """测试模块宕机演练"""
        runner = DrillsRunner()
        script = module_outage_drill("m1")
        result = runner.run_drill(script)

        assert result is not None
        assert "drill_id" in result
        assert "status" in result
        assert result["total_steps"] > 0

    def test_database_failover_drill(self):
        """测试数据库切换演练"""
        runner = DrillsRunner()
        script = database_failover_drill("primary")
        result = runner.run_drill(script)

        assert result is not None
        assert result["total_steps"] > 0

    def test_network_partition_drill(self):
        """测试网络分区演练"""
        runner = DrillsRunner()
        script = network_partition_drill("m1")
        result = runner.run_drill(script)

        assert result is not None
        assert result["total_steps"] > 0

    def test_full_system_recovery_drill(self):
        """测试全系统恢复演练"""
        runner = DrillsRunner()
        script = full_system_recovery_drill()
        result = runner.run_drill(script)

        assert result is not None
        assert result["total_steps"] > 0


# ============================================================
# 十三、报告生成测试 (3 tests)
# ============================================================

class TestReportGenerator:
    """报告生成测试"""

    def test_generate_report(self):
        """测试生成报告"""
        generator = ReportGenerator()
        result = {
            "drill_id": "test_001",
            "drill_name": "测试演练",
            "status": "completed",
            "start_time": time.time() - 60,
            "end_time": time.time(),
            "duration_seconds": 60,
            "total_steps": 5,
            "completed_steps": 5,
            "failed_steps": 0,
            "skipped_steps": 0,
            "steps": [],
            "events": [],
            "metrics": {},
        }

        report = generator.generate(result)
        assert report.report_id is not None
        assert report.drill_result.drill_id == "test_001"
        assert len(report.findings) > 0
        assert len(report.improvements) > 0

    def test_report_to_json(self):
        """测试报告 JSON 导出"""
        generator = ReportGenerator()
        result = {
            "drill_id": "test_001",
            "drill_name": "测试演练",
            "status": "completed",
            "start_time": time.time(),
            "end_time": time.time() + 10,
            "duration_seconds": 10,
            "total_steps": 3,
            "completed_steps": 3,
            "failed_steps": 0,
            "skipped_steps": 0,
            "steps": [],
            "events": [],
            "metrics": {},
        }

        report = generator.generate(result)
        json_str = report.to_json()
        data = json.loads(json_str)
        assert data["drill_result"]["drill_id"] == "test_001"

    def test_report_to_markdown(self):
        """测试报告 Markdown 导出"""
        generator = ReportGenerator()
        result = {
            "drill_id": "test_001",
            "drill_name": "测试演练",
            "status": "completed",
            "start_time": time.time(),
            "end_time": time.time() + 10,
            "duration_seconds": 10,
            "total_steps": 3,
            "completed_steps": 3,
            "failed_steps": 0,
            "skipped_steps": 0,
            "steps": [],
            "events": [],
            "metrics": {},
        }

        report = generator.generate(result)
        md = report.to_markdown()
        assert "# 故障演练报告" in md
        assert "测试演练" in md


# ============================================================
# 十四、异地备份测试 (2 tests)
# ============================================================

class TestRemoteBackup:
    """异地备份测试"""

    def test_remote_backup_config(self, data_dir, backup_dir, temp_dir):
        """测试异地备份配置"""
        remote_path = temp_dir / "remote_backups"
        remote_config = RemoteBackupConfig(
            enabled=True,
            remote_path=str(remote_path),
            copy_full=True,
            max_remote_backups=5,
        )

        ebm = EnhancedBackupManager(
            backup_root=str(backup_dir),
            data_root=str(data_dir),
            remote_config=remote_config,
        )

        result = ebm.full_backup("test.db")
        assert result["success"] is True

        # 检查远程是否有备份
        remote_backups = list(remote_path.glob("*"))
        assert len(remote_backups) >= 1

    def test_sync_all_to_remote(self, data_dir, backup_dir, temp_dir):
        """测试全量同步到异地"""
        remote_path = temp_dir / "remote"
        remote_config = RemoteBackupConfig(
            enabled=True,
            remote_path=str(remote_path),
            copy_full=True,
            sync_on_create=False,  # 不自动同步
        )

        ebm = EnhancedBackupManager(
            backup_root=str(backup_dir),
            data_root=str(data_dir),
            remote_config=remote_config,
        )

        ebm.full_backup("test.db", backup_name="sync_test_1")
        time.sleep(0.1)
        ebm.full_backup("test.db", backup_name="sync_test_2")

        # 手动同步
        result = ebm.sync_all_to_remote()
        assert result["synced_count"] >= 2


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
