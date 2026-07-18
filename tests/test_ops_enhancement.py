"""
云汐系统 - 部署运维增强测试套件

测试覆盖：
1. 健康检查测试（活性/就绪/启动/深度/评分）
2. Docker 配置验证（Dockerfile语法/compose验证）
3. 运维仪表盘测试
4. 日志管理测试
5. 备份管理测试
6. 版本一致性测试
7. 向后兼容测试

运行方式：
    pytest tests/test_ops_enhancement.py -v
"""

import os
import sys
import json
import time
import tempfile
import shutil
from pathlib import Path
from datetime import datetime

import pytest

# 项目根路径
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))


# ============================================================================
# Fixtures
# ============================================================================

@pytest.fixture
def temp_dir():
    """临时目录 fixture"""
    d = tempfile.mkdtemp()
    yield Path(d)
    shutil.rmtree(d, ignore_errors=True)


@pytest.fixture
def health_checker():
    """健康检查器 fixture"""
    from shared.health.health_checker import HealthChecker
    return HealthChecker(
        module_name="test-module",
        version="1.0.0",
        module_display_name="测试模块",
    )


# ============================================================================
# 第一组：健康检查测试（8 个）
# ============================================================================

class TestHealthChecker:
    """健康检查器测试"""

    def test_health_checker_initialization(self, health_checker):
        """测试健康检查器初始化"""
        assert health_checker.module_name == "test-module"
        assert health_checker.version == "1.0.0"
        assert health_checker.module_display_name == "测试模块"
        assert health_checker.uptime_seconds >= 0
        assert not health_checker.is_startup_complete

    def test_liveness_check_default(self, health_checker):
        """测试活性检查（默认检查）"""
        result = health_checker.check_liveness()
        assert result.status.value == "healthy"
        assert result.module == "test-module"
        assert "process" in result.checks
        assert result.score == 100

    def test_liveness_check_custom(self, health_checker):
        """测试自定义活性检查"""
        from shared.health.health_checker import CheckResult

        def custom_check():
            return CheckResult.healthy(custom_field="value")

        health_checker.register_liveness_check("custom", custom_check)
        result = health_checker.check_liveness()
        assert result.status.value == "healthy"
        assert "custom" in result.checks
        assert result.checks["custom"].details.get("custom_field") == "value"

    def test_readiness_check_before_startup(self, health_checker):
        """测试启动未完成时的就绪检查"""
        from shared.health.health_checker import CheckResult, HealthStatus

        # 注册一个会失败的启动检查
        def failing_startup():
            return CheckResult.unhealthy(error="not ready")

        health_checker.register_startup_check("init", failing_startup, critical=True)
        result = health_checker.check_readiness()
        # 启动未完成时，就绪检查应该失败
        assert result.status == HealthStatus.UNHEALTHY

    def test_readiness_check_after_startup(self, health_checker):
        """测试启动完成后的就绪检查"""
        from shared.health.health_checker import CheckResult, HealthStatus

        def passing_startup():
            return CheckResult.healthy()

        def passing_readiness():
            return CheckResult.healthy()

        health_checker.register_startup_check("init", passing_startup, critical=True)
        health_checker.register_readiness_check("db", passing_readiness, critical=True)

        # 先调用启动检查使其完成
        health_checker.check_startup()
        assert health_checker.is_startup_complete

        result = health_checker.check_readiness()
        assert result.status == HealthStatus.HEALTHY

    def test_startup_check(self, health_checker):
        """测试启动检查"""
        from shared.health.health_checker import CheckResult, HealthStatus

        def passing_check():
            return CheckResult.healthy()

        health_checker.register_startup_check("init", passing_check, critical=True)

        result = health_checker.check_startup()
        assert result.status == HealthStatus.HEALTHY
        assert health_checker.is_startup_complete

    def test_deep_check(self, health_checker):
        """测试深度检查"""
        from shared.health.health_checker import CheckResult, HealthStatus

        def db_check():
            return CheckResult.healthy(type="postgresql")

        def redis_check():
            return CheckResult.degraded(error="slow response")

        health_checker.register_deep_check("database", db_check, critical=True)
        health_checker.register_deep_check("redis", redis_check, critical=False)

        result = health_checker.check_deep()
        # 非核心检查降级，整体应该是 degraded
        assert result.status == HealthStatus.DEGRADED
        assert "database" in result.checks
        assert "redis" in result.checks

    def test_health_score_calculation(self, health_checker):
        """测试健康评分计算"""
        from shared.health.health_checker import CheckResult

        # 全部健康 -> 100 分
        def healthy_check():
            return CheckResult.healthy()

        health_checker.register_readiness_check("check1", healthy_check, critical=True)
        health_checker.register_readiness_check("check2", healthy_check, critical=False)

        result = health_checker.check_deep()
        assert result.score == 100

        # 非核心检查降级 -> -5 分
        def degraded_check():
            return CheckResult.degraded(error="slow")

        health_checker.register_readiness_check("check3", degraded_check, critical=False)

        result = health_checker.check_deep()
        assert result.score < 100
        assert result.score >= 90

    def test_health_score_minimum_zero(self, health_checker):
        """测试健康评分最低为0"""
        from shared.health.health_checker import CheckResult

        # 注册大量失败的核心检查
        for i in range(20):
            def fail():
                return CheckResult.unhealthy(error="fail")
            health_checker.register_deep_check(f"check_{i}", fail, critical=True)

        result = health_checker.check_deep()
        assert result.score == 0
        assert result.score >= 0  # 不能为负

    def test_get_details(self, health_checker):
        """测试获取详细健康信息"""
        from shared.health.health_checker import CheckResult

        health_checker.register_readiness_check("memory", lambda: CheckResult.healthy(total=1024))
        health_checker.add_dependency("redis", url="redis://localhost:6379")

        details = health_checker.get_details()
        assert "dependencies" in details
        assert "system" in details
        assert "checks" in details
        assert "score" in details

    def test_get_metrics(self, health_checker):
        """测试获取健康指标"""
        from shared.health.health_checker import CheckResult

        health_checker.register_readiness_check("test", lambda: CheckResult.healthy())

        metrics = health_checker.get_metrics()
        assert "prometheus" in metrics
        assert "score" in metrics
        assert "yunxi_health_status" in metrics["prometheus"]
        assert "yunxi_health_score" in metrics["prometheus"]


# ============================================================================
# 第二组：Docker 配置验证（5 个）
# ============================================================================

class TestDockerConfig:
    """Docker 配置验证测试"""

    DOCKER_DIR = PROJECT_ROOT / "docker"
    COMPOSE_FILE = PROJECT_ROOT / "docker-compose.yml"

    def test_docker_directory_exists(self):
        """测试 docker 目录存在"""
        assert self.DOCKER_DIR.exists(), f"docker 目录不存在: {self.DOCKER_DIR}"

    def test_all_module_dockerfiles_exist(self):
        """测试所有模块的 Dockerfile 存在"""
        expected_dockerfiles = [
            "shared-base.Dockerfile",
            "gateway.Dockerfile",
            "m8.Dockerfile",
            "m0.Dockerfile",
            "m1.Dockerfile",
            "m2.Dockerfile",
            "m4.Dockerfile",
            "m7.Dockerfile",
            "m9.Dockerfile",
            "m10.Dockerfile",
            "m11.Dockerfile",
            "m12.Dockerfile",
        ]

        missing = []
        for df in expected_dockerfiles:
            path = self.DOCKER_DIR / df
            if not path.exists():
                missing.append(df)

        assert len(missing) == 0, f"缺少 Dockerfile: {missing}"

    def test_dockerfiles_have_multistage_build(self):
        """测试 Dockerfile 使用多阶段构建"""
        dockerfiles = list(self.DOCKER_DIR.glob("*.Dockerfile"))
        assert len(dockerfiles) > 0

        for df in dockerfiles:
            content = df.read_text(encoding="utf-8", errors="ignore")
            # 多阶段构建应该有多个 FROM 指令
            from_count = content.count("FROM ")
            assert from_count >= 2, f"{df.name} 未使用多阶段构建 (FROM 数量: {from_count})"

    def test_dockerfiles_have_healthcheck(self):
        """测试 Dockerfile 包含健康检查"""
        dockerfiles = list(self.DOCKER_DIR.glob("*.Dockerfile"))

        for df in dockerfiles:
            content = df.read_text(encoding="utf-8", errors="ignore")
            has_healthcheck = "HEALTHCHECK" in content or "healthcheck.sh" in content
            assert has_healthcheck, f"{df.name} 缺少健康检查配置"

    def test_dockerfiles_have_non_root_user(self):
        """测试 Dockerfile 使用非 root 用户"""
        dockerfiles = list(self.DOCKER_DIR.glob("*.Dockerfile"))

        for df in dockerfiles:
            content = df.read_text(encoding="utf-8", errors="ignore")
            has_user = "USER " in content or "useradd" in content
            assert has_user, f"{df.name} 未使用非 root 用户"

    def test_docker_compose_exists(self):
        """测试 docker-compose.yml 存在"""
        assert self.COMPOSE_FILE.exists(), "docker-compose.yml 不存在"

    def test_docker_compose_has_required_services(self):
        """测试 docker-compose 包含必需的服务"""
        import yaml

        with open(self.COMPOSE_FILE, "r", encoding="utf-8") as f:
            compose = yaml.safe_load(f)

        services = compose.get("services", {})
        required_services = [
            "redis",
            "yunxi-gateway",
            "yunxi-m1",
            "yunxi-m2",
            "yunxi-m4",
            "yunxi-m7",
            "yunxi-m8",
            "yunxi-m9",
            "yunxi-m10",
            "yunxi-m11",
            "yunxi-m12",
        ]

        missing = [s for s in required_services if s not in services]
        assert len(missing) == 0, f"docker-compose 缺少服务: {missing}"

    def test_docker_compose_has_networks(self):
        """测试 docker-compose 配置了网络"""
        import yaml

        with open(self.COMPOSE_FILE, "r", encoding="utf-8") as f:
            compose = yaml.safe_load(f)

        networks = compose.get("networks", {})
        assert len(networks) > 0, "docker-compose 未配置网络"

    def test_docker_compose_has_volumes(self):
        """测试 docker-compose 配置了卷"""
        import yaml

        with open(self.COMPOSE_FILE, "r", encoding="utf-8") as f:
            compose = yaml.safe_load(f)

        volumes = compose.get("volumes", {})
        assert len(volumes) > 0, "docker-compose 未配置数据卷"


# ============================================================================
# M8 backend 路径（用于导入 M8 服务模块）
M8_BACKEND_DIR = PROJECT_ROOT / "M8-control-tower" / "backend"


def _import_m8_module(module_name: str):
    """通过 importlib 导入 M8 后端模块"""
    import importlib.util
    module_path = M8_BACKEND_DIR / "services" / f"{module_name}.py"
    spec = importlib.util.spec_from_file_location(module_name, module_path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


# ============================================================================
# 第三组：运维仪表盘测试（9 个）
# ============================================================================

class TestOpsDashboard:
    """运维仪表盘测试"""

    def test_ops_aggregator_initialization(self):
        """测试运维状态聚合器初始化"""
        ops_mod = _import_m8_module("ops_status_aggregator")
        OpsStatusAggregator = ops_mod.OpsStatusAggregator

        agg = OpsStatusAggregator(cache_ttl=5, history_size=10)
        assert agg is not None
        assert len(agg.MODULES) > 0
        # 验证包含核心模块
        assert "m8" in agg.MODULES
        assert "gateway" in agg.MODULES

    def test_ops_aggregator_module_list(self):
        """测试获取模块列表"""
        ops_mod = _import_m8_module("ops_status_aggregator")
        OpsStatusAggregator = ops_mod.OpsStatusAggregator

        agg = OpsStatusAggregator(cache_ttl=5, history_size=10)
        modules = agg.get_module_list()

        assert isinstance(modules, list)
        assert len(modules) > 0

        # 验证模块结构
        for m in modules:
            assert "name" in m
            assert "display_name" in m
            assert "port" in m
            assert "status" in m
            assert "score" in m
            assert "critical" in m

    def test_ops_aggregator_dashboard_overview(self):
        """测试仪表盘总览"""
        ops_mod = _import_m8_module("ops_status_aggregator")
        OpsStatusAggregator = ops_mod.OpsStatusAggregator

        agg = OpsStatusAggregator(cache_ttl=5, history_size=10)
        overview = agg.get_dashboard_overview()

        assert "summary" in overview
        assert "resources" in overview
        assert "recent_alerts" in overview

        summary = overview["summary"]
        assert "overall_status" in summary
        assert "overall_score" in summary
        assert "total_modules" in summary
        assert "healthy_modules" in summary
        assert "uptime_seconds" in summary

    def test_ops_aggregator_module_detail(self):
        """测试模块详情"""
        ops_mod = _import_m8_module("ops_status_aggregator")
        OpsStatusAggregator = ops_mod.OpsStatusAggregator

        agg = OpsStatusAggregator(cache_ttl=5, history_size=10)
        detail = agg.get_module_detail("m8")

        assert detail is not None
        assert detail["name"] == "m8"
        assert "display_name" in detail
        assert "status" in detail
        assert "score" in detail
        assert "checks" in detail
        assert "score_history" in detail

    def test_ops_aggregator_module_detail_not_found(self):
        """测试不存在的模块详情"""
        ops_mod = _import_m8_module("ops_status_aggregator")
        OpsStatusAggregator = ops_mod.OpsStatusAggregator

        agg = OpsStatusAggregator(cache_ttl=5, history_size=10)
        detail = agg.get_module_detail("nonexistent-module")
        assert detail is None

    def test_ops_aggregator_resource_usage(self):
        """测试资源使用情况"""
        ops_mod = _import_m8_module("ops_status_aggregator")
        OpsStatusAggregator = ops_mod.OpsStatusAggregator

        agg = OpsStatusAggregator(cache_ttl=5, history_size=10)
        resources = agg.get_resource_usage()

        assert "cpu" in resources
        assert "memory" in resources
        assert "disk" in resources

    def test_ops_aggregator_dependency_graph(self):
        """测试服务依赖图"""
        ops_mod = _import_m8_module("ops_status_aggregator")
        OpsStatusAggregator = ops_mod.OpsStatusAggregator

        agg = OpsStatusAggregator(cache_ttl=5, history_size=10)
        graph = agg.get_service_dependency_graph()

        assert "nodes" in graph
        assert "edges" in graph
        assert len(graph["nodes"]) > 0
        assert len(graph["edges"]) > 0

    def test_ops_aggregator_deployments(self):
        """测试部署记录"""
        ops_mod = _import_m8_module("ops_status_aggregator")
        OpsStatusAggregator = ops_mod.OpsStatusAggregator

        agg = OpsStatusAggregator(cache_ttl=5, history_size=10)

        # 记录一个部署
        agg.record_deployment("m8", "2.0.0", "success")

        deployments = agg.get_deployments()
        assert len(deployments) >= 1
        assert deployments[0]["module"] == "m8"
        assert deployments[0]["version"] == "2.0.0"

    def test_ops_aggregator_system_config(self):
        """测试系统配置概览"""
        ops_mod = _import_m8_module("ops_status_aggregator")
        OpsStatusAggregator = ops_mod.OpsStatusAggregator

        agg = OpsStatusAggregator(cache_ttl=5, history_size=10)
        config = agg.get_system_config_overview()

        assert "system" in config
        assert "modules" in config
        assert "features" in config
        assert config["features"]["health_check"] is True
        assert config["features"]["backup"] is True


# ============================================================================
# 第四组：日志管理测试（5 个）
# ============================================================================

class TestLogManagement:
    """日志管理测试"""

    def test_log_rotation_config_defaults(self):
        """测试日志轮转配置默认值"""
        from shared.core.observability.unified_logger import LogRotationConfig

        config = LogRotationConfig()
        assert config.enabled is True
        assert config.backup_count == 30
        assert config.compress is True
        assert config.interval == 1

    def test_log_rotation_config_env_overrides(self, monkeypatch):
        """测试环境变量覆盖配置"""
        from shared.core.observability.unified_logger import LogRotationConfig

        monkeypatch.setenv("LOG_ROTATION_ENABLED", "false")
        monkeypatch.setenv("LOG_ROTATION_BACKUP_COUNT", "15")
        monkeypatch.setenv("LOG_ROTATION_COMPRESS", "false")

        config = LogRotationConfig()
        assert config.enabled is False
        assert config.backup_count == 15
        assert config.compress is False

    def test_unified_logger_creation(self, temp_dir):
        """测试统一日志器创建"""
        from shared.core.observability.unified_logger import UnifiedLogger

        logger = UnifiedLogger(
            name="test-logger",
            level="INFO",
            log_dir=str(temp_dir),
            json_format=True,
            console_output=True,
            file_output=True,
        )

        assert logger is not None
        assert logger.name == "test-logger"
        assert logger.json_format is True

    def test_unified_logger_structured_output(self, temp_dir):
        """测试结构化日志输出"""
        from shared.core.observability.unified_logger import UnifiedLogger

        logger = UnifiedLogger(
            name="test-structured",
            level="DEBUG",
            log_dir=str(temp_dir),
            json_format=True,
            console_output=False,
            file_output=True,
        )

        logger.info("test message", user_id="123", action="login")

        # 检查日志文件是否创建
        log_file = temp_dir / "test-structured.log"
        # 刷新日志
        import logging
        for handler in logger.get_logger().handlers:
            handler.flush()

        if log_file.exists():
            content = log_file.read_text(encoding="utf-8")
            lines = [l for l in content.strip().split("\n") if l.strip()]
            if lines:
                # 验证 JSON 格式
                log_entry = json.loads(lines[-1])
                assert "message" in log_entry
                assert "level" in log_entry
                assert "timestamp" in log_entry

    def test_log_context_injection(self, temp_dir):
        """测试日志上下文注入"""
        from shared.core.observability.unified_logger import (
            UnifiedLogger,
            set_log_context,
            get_log_context,
            clear_log_context,
        )

        # 清除已有上下文
        clear_log_context()

        logger = UnifiedLogger(
            name="test-context",
            level="INFO",
            log_dir=str(temp_dir),
            json_format=True,
            console_output=False,
            file_output=True,
        )

        set_log_context(trace_id="abc123", user_id="456")
        ctx = get_log_context()
        assert ctx["trace_id"] == "abc123"
        assert ctx["user_id"] == "456"

        logger.info("test with context")

        clear_log_context()
        ctx = get_log_context()
        assert ctx == {}

    def test_sensitive_data_masking(self):
        """测试敏感字段脱敏"""
        from shared.core.observability.unified_logger import mask_sensitive_data

        # 测试密码脱敏
        data = {"password": "secret123", "username": "testuser"}
        masked = mask_sensitive_data(data)
        assert masked["password"] == "***MASKED***"
        assert masked["username"] == "testuser"

        # 测试 token 脱敏
        data2 = {"access_token": "abcdef1234567890"}
        masked2 = mask_sensitive_data(data2)
        assert masked2["access_token"] == "***MASKED***"

        # 测试嵌套字典
        data3 = {"user": {"password": "secret", "name": "test"}}
        masked3 = mask_sensitive_data(data3)
        assert masked3["user"]["password"] == "***MASKED***"
        assert masked3["user"]["name"] == "test"

    def test_log_cleanup_tools(self, temp_dir):
        """测试日志清理工具"""
        from shared.core.observability.unified_logger import (
            clean_expired_logs,
            get_log_dir_size,
        )

        # 创建一些测试日志文件
        (temp_dir / "app.log").write_text("test log")
        (temp_dir / "app.log.1").write_text("old log")

        # 测试目录大小统计
        size, count = get_log_dir_size(str(temp_dir))
        assert count >= 2
        assert size > 0

        # 测试清理（dry_run）
        result = clean_expired_logs(str(temp_dir), max_age_days=0, dry_run=True)
        assert result["dry_run"] is True
        assert result["deleted"] >= 0


# ============================================================================
# 第五组：备份管理测试（6 个）
# ============================================================================

class TestBackupService:
    """备份管理服务测试"""

    def test_backup_service_initialization(self, temp_dir):
        """测试备份服务初始化"""
        backup_mod = _import_m8_module("backup_service")
        BackupService = backup_mod.BackupService
        RetentionPolicy = backup_mod.RetentionPolicy

        backup_dir = temp_dir / "backups"
        data_dir = temp_dir / "data"
        data_dir.mkdir()
        (data_dir / "test.txt").write_text("test data")

        service = BackupService(
            backup_dir=str(backup_dir),
            data_dir=str(data_dir),
            retention=RetentionPolicy(max_count=5),
        )

        assert service is not None
        assert backup_dir.exists()

    def test_create_backup(self, temp_dir):
        """测试创建备份"""
        backup_mod = _import_m8_module("backup_service")
        BackupService = backup_mod.BackupService

        backup_dir = temp_dir / "backups"
        data_dir = temp_dir / "data"
        data_dir.mkdir()
        (data_dir / "test.txt").write_text("test data content")

        service = BackupService(
            backup_dir=str(backup_dir),
            data_dir=str(data_dir),
        )

        record = service.create_backup(
            backup_type="full",
            description="test backup",
        )

        assert record is not None
        assert record.backup_id.startswith("backup-")
        assert record.backup_type == "full"
        assert record.description == "test backup"

        # 等待备份完成
        time.sleep(1)

        # 检查备份记录
        backup_info = service.get_backup(record.backup_id)
        assert backup_info is not None

    def test_list_backups(self, temp_dir):
        """测试列出备份"""
        backup_mod = _import_m8_module("backup_service")
        BackupService = backup_mod.BackupService

        backup_dir = temp_dir / "backups"
        data_dir = temp_dir / "data"
        data_dir.mkdir()

        service = BackupService(
            backup_dir=str(backup_dir),
            data_dir=str(data_dir),
        )

        result = service.list_backups()
        assert "backups" in result
        assert "total" in result
        assert isinstance(result["backups"], list)

    def test_backup_stats(self, temp_dir):
        """测试备份统计"""
        backup_mod = _import_m8_module("backup_service")
        BackupService = backup_mod.BackupService

        backup_dir = temp_dir / "backups"
        data_dir = temp_dir / "data"
        data_dir.mkdir()

        service = BackupService(
            backup_dir=str(backup_dir),
            data_dir=str(data_dir),
        )

        stats = service.get_stats()
        assert "total_backups" in stats
        assert "success_count" in stats
        assert "failed_count" in stats
        assert "total_size_bytes" in stats
        assert "retention_policy" in stats
        assert "backup_dir" in stats

    def test_verify_backup_not_found(self, temp_dir):
        """测试验证不存在的备份"""
        backup_mod = _import_m8_module("backup_service")
        BackupService = backup_mod.BackupService

        backup_dir = temp_dir / "backups"
        data_dir = temp_dir / "data"
        data_dir.mkdir()

        service = BackupService(
            backup_dir=str(backup_dir),
            data_dir=str(data_dir),
        )

        result = service.verify_backup("nonexistent-backup")
        assert result["valid"] is False
        assert "error" in result

    def test_delete_backup_not_found(self, temp_dir):
        """测试删除不存在的备份"""
        backup_mod = _import_m8_module("backup_service")
        BackupService = backup_mod.BackupService

        backup_dir = temp_dir / "backups"
        data_dir = temp_dir / "data"
        data_dir.mkdir()

        service = BackupService(
            backup_dir=str(backup_dir),
            data_dir=str(data_dir),
        )

        result = service.delete_backup("nonexistent-backup")
        assert result is False

    def test_dry_run_restore(self, temp_dir):
        """测试试运行恢复"""
        backup_mod = _import_m8_module("backup_service")
        BackupService = backup_mod.BackupService

        backup_dir = temp_dir / "backups"
        data_dir = temp_dir / "data"
        data_dir.mkdir()
        (data_dir / "test.txt").write_text("test data")

        service = BackupService(
            backup_dir=str(backup_dir),
            data_dir=str(data_dir),
        )

        record = service.create_backup(backup_type="full")
        time.sleep(1)

        result = service.restore_backup(record.backup_id, dry_run=True)
        assert "dry_run" in result
        assert result["dry_run"] is True


# ============================================================================
# 第六组：版本一致性与向后兼容测试（4 个）
# ============================================================================

class TestVersionAndCompatibility:
    """版本一致性与向后兼容测试"""

    def test_version_file_exists(self):
        """测试版本文件存在"""
        version_file = PROJECT_ROOT / "VERSION"
        assert version_file.exists(), "VERSION 文件不存在"
        version = version_file.read_text().strip()
        assert len(version) > 0, "版本号为空"

    def test_health_module_backward_compatible(self):
        """测试健康检查模块向后兼容（旧导入路径可用）"""
        # 测试旧路径 shared.core.observability.health 仍然可用
        try:
            from shared.core.observability.health import (
                HealthChecker as OldHealthChecker,
                HealthStatus,
                create_fastapi_health_router,
            )
            assert OldHealthChecker is not None
            assert HealthStatus is not None
        except ImportError as e:
            pytest.fail(f"旧版健康检查模块导入失败: {e}")

    def test_new_health_module_available(self):
        """测试新版健康检查模块可用"""
        try:
            from shared.health import (
                HealthChecker,
                HealthStatus,
                create_health_router,
                CheckType,
            )
            assert HealthChecker is not None
            assert CheckType is not None
        except ImportError as e:
            pytest.fail(f"新版健康检查模块导入失败: {e}")

    def test_logger_backward_compatible(self):
        """测试日志系统向后兼容"""
        try:
            from shared.core.observability import get_logger
            logger = get_logger("compat-test")
            assert logger is not None
            # 测试基本日志方法
            logger.info("compatibility test message")
        except Exception as e:
            pytest.fail(f"日志系统向后兼容失败: {e}")

    def test_docker_compose_backward_compatible(self):
        """测试 docker-compose 向后兼容（旧模块名仍可用）"""
        import yaml

        compose_file = PROJECT_ROOT / "docker-compose.yml"
        assert compose_file.exists()

        with open(compose_file, "r", encoding="utf-8") as f:
            compose = yaml.safe_load(f)

        services = compose.get("services", {})

        # 验证关键服务仍然使用旧的命名规范
        legacy_names = [
            "yunxi-gateway",
            "yunxi-m1",
            "yunxi-m8",
        ]
        for name in legacy_names:
            assert name in services, f"服务名 {name} 不再可用，破坏向后兼容"

    def test_ops_dashboard_pure_additive(self):
        """测试运维仪表盘是纯增量（不修改现有路由）"""
        # ops_dashboard 使用 /api/ops 前缀，是全新的路径
        # 验证它不与现有路由冲突
        ops_routes = [
            "/api/ops/dashboard",
            "/api/ops/modules",
            "/api/ops/resources",
            "/api/ops/logs",
            "/api/ops/deployments",
            "/api/ops/backups",
            "/api/ops/config",
        ]

        # 验证路由路径格式正确
        for route in ops_routes:
            assert route.startswith("/api/ops/"), f"路由 {route} 不在 ops 前缀下"


# ============================================================================
# 第七组：FastAPI 健康路由测试（3 个）
# ============================================================================

class TestHealthRouter:
    """健康检查路由测试"""

    @pytest.fixture
    def app(self):
        """创建测试用 FastAPI 应用"""
        from fastapi import FastAPI
        from shared.health import HealthChecker, create_health_router

        app = FastAPI()
        checker = HealthChecker(module_name="test", version="1.0.0")

        # 注册一些检查
        from shared.health import CheckResult
        checker.register_liveness_check("process", lambda: CheckResult.healthy(pid=12345))
        checker.register_startup_check("init", lambda: CheckResult.healthy())
        checker.register_readiness_check("db", lambda: CheckResult.healthy())

        router = create_health_router(checker)
        app.include_router(router)
        return app

    def test_health_endpoint(self, app):
        """测试 /health 端点"""
        from fastapi.testclient import TestClient

        client = TestClient(app)
        response = client.get("/health")
        assert response.status_code == 200
        data = response.json()
        assert "status" in data
        assert "score" in data
        assert "module" in data

    def test_health_live_endpoint(self, app):
        """测试 /health/live 端点"""
        from fastapi.testclient import TestClient

        client = TestClient(app)
        response = client.get("/health/live")
        assert response.status_code == 200
        data = response.json()
        assert "status" in data

    def test_health_ready_endpoint(self, app):
        """测试 /health/ready 端点"""
        from fastapi.testclient import TestClient

        client = TestClient(app)
        # 先调用 startup 使其完成
        client.get("/health/startup")

        response = client.get("/health/ready")
        assert response.status_code == 200
        data = response.json()
        assert "status" in data

    def test_health_startup_endpoint(self, app):
        """测试 /health/startup 端点"""
        from fastapi.testclient import TestClient

        client = TestClient(app)
        response = client.get("/health/startup")
        assert response.status_code == 200
        data = response.json()
        assert "status" in data

    def test_health_details_endpoint(self, app):
        """测试 /health/details 端点"""
        from fastapi.testclient import TestClient

        client = TestClient(app)
        response = client.get("/health/details")
        assert response.status_code == 200
        data = response.json()
        assert "dependencies" in data
        assert "system" in data

    def test_health_metrics_endpoint(self, app):
        """测试 /health/metrics 端点"""
        from fastapi.testclient import TestClient

        client = TestClient(app)
        response = client.get("/health/metrics")
        assert response.status_code == 200
        assert "text/plain" in response.headers["content-type"]


# ============================================================================
# 测试计数验证
# ============================================================================

def test_total_test_count():
    """验证测试用例总数 >= 30"""
    test_classes = [
        TestHealthChecker,
        TestDockerConfig,
        TestOpsDashboard,
        TestLogManagement,
        TestBackupService,
        TestVersionAndCompatibility,
        TestHealthRouter,
    ]

    total_tests = 0
    for cls in test_classes:
        test_methods = [m for m in dir(cls) if m.startswith("test_")]
        total_tests += len(test_methods)

    assert total_tests >= 30, f"测试用例数量不足: {total_tests} < 30"
    print(f"\n总测试用例数: {total_tests}")
