"""
运维体系单元测试 - 滚动升级、日志查询、指标定义、仪表盘

覆盖:
- RollingUpgradeManager (OP-003)
- LogQueryEngine & LogArchiver (OP-006)
- Metric Definitions (OB-002)
- Dashboard Generation (OB-004)

运行: python -m pytest shared/tests/test_ops_observability.py -v
"""
import os
import sys
import json
import time
import tempfile
import pytest
from unittest.mock import patch, MagicMock, mock_open
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import importlib.util
spec = importlib.util.spec_from_file_location(
    "yunxi_shared",
    os.path.join(os.path.dirname(__file__), "..", "__init__.py"),
)
if spec and spec.loader:
    import sys as _sys
    _shared_module = importlib.util.module_from_spec(spec)
    _sys.modules["yunxi_shared"] = _shared_module
    spec.loader.exec_module(_shared_module)


# ============================================================================
# 滚动升级测试
# ============================================================================

class TestRollingUpgradeManager:
    """滚动升级管理器测试 (OP-003)"""

    def _get_manager(self):
        from yunxi_shared.core.observability.rolling_upgrade import (
            RollingUpgradeManager,
            UpgradeConfig,
        )
        return RollingUpgradeManager(UpgradeConfig(backup_dir="./test_backups"))

    def test_manager_initialization(self):
        """升级管理器初始化"""
        manager = self._get_manager()
        status = manager.get_upgrade_status()
        assert status["phase"] == "idle"
        assert "current_upgrade" in status

    def test_register_module_operations(self):
        """注册模块操作函数"""
        manager = self._get_manager()
        manager.register_module_operations(
            module_id="test_mod",
            health_checker=lambda: True,
            starter=lambda: True,
            stopper=lambda: True,
        )
        assert "test_mod" in manager._health_checkers
        assert "test_mod" in manager._module_starters
        assert "test_mod" in manager._module_stoppers

    def test_check_for_upgrade_no_new_version(self):
        """检查升级 - 无新版本"""
        manager = self._get_manager()
        result = manager.check_for_upgrade()
        assert "has_new_version" in result
        assert "current_version" in result

    def test_check_for_upgrade_result_structure(self):
        """检查升级结果结构完整性"""
        manager = self._get_manager()
        result = manager.check_for_upgrade()
        assert isinstance(result, dict)
        required_keys = ["has_new_version", "current_version", "latest_version", "checked_at"]
        for key in required_keys:
            assert key in result, f"缺少字段: {key}"

    def test_get_upgrade_history_empty(self):
        """升级历史 - 空列表"""
        manager = self._get_manager()
        history = manager.get_upgrade_history()
        assert isinstance(history, list)

    def test_get_upgrade_history_with_limit(self):
        """升级历史 - limit 参数"""
        manager = self._get_manager()
        history = manager.get_upgrade_history(limit=5)
        assert isinstance(history, list)
        assert len(history) <= 5

    def test_upgrade_config_defaults(self):
        """升级配置默认值"""
        from yunxi_shared.core.observability.rolling_upgrade import UpgradeConfig
        config = UpgradeConfig()
        assert config.auto_check is True
        assert config.check_interval_seconds > 0
        assert config.auto_upgrade is False
        assert config.max_retry >= 1

    def test_upgrade_strategy_enum(self):
        """升级策略枚举值"""
        from yunxi_shared.core.observability.rolling_upgrade import UpgradeStrategy
        strategies = list(UpgradeStrategy)
        assert len(strategies) >= 3
        strategy_names = [s.value for s in strategies]
        assert "rolling" in strategy_names
        assert "blue_green" in strategy_names
        assert "canary" in strategy_names

    def test_upgrade_phase_enum(self):
        """升级阶段枚举"""
        from yunxi_shared.core.observability.rolling_upgrade import UpgradePhase
        phases = list(UpgradePhase)
        assert len(phases) >= 5
        phase_names = [p.value for p in phases]
        assert "idle" in phase_names
        assert "upgrading" in phase_names
        assert "completed" in phase_names

    def test_rollback_nonexistent_module(self):
        """回滚不存在的模块"""
        manager = self._get_manager()
        result = manager.rollback("nonexistent_module")
        assert result["success"] is False
        assert "error" in result

    def test_prepare_upgrade_empty_version(self):
        """准备升级 - 空版本号不报错但返回成功标记"""
        manager = self._get_manager()
        # 空版本号会被当作新版本号处理，不抛出异常
        result = manager.prepare_upgrade("")
        assert isinstance(result, dict)
        assert "success" in result

    def test_upgrade_status_enum(self):
        """升级状态枚举"""
        from yunxi_shared.core.observability.rolling_upgrade import UpgradeStatus
        statuses = list(UpgradeStatus)
        assert len(statuses) >= 4
        status_names = [s.value for s in statuses]
        assert "success" in status_names
        assert "failed" in status_names

    def test_version_info_structure(self):
        """版本信息数据类"""
        from yunxi_shared.core.observability.rolling_upgrade import VersionInfo
        vi = VersionInfo(version="v1.0.0", release_date="2026-01-01")
        assert vi.version == "v1.0.0"
        assert hasattr(vi, "release_notes")

    def test_module_upgrade_record(self):
        """模块升级记录数据类"""
        from yunxi_shared.core.observability.rolling_upgrade import (
            ModuleUpgradeRecord, UpgradeStatus
        )
        record = ModuleUpgradeRecord(module_id="m8", from_version="v1.0", to_version="v1.1")
        d = record.to_dict()
        assert d["module_id"] == "m8"
        assert d["status"] == UpgradeStatus.PENDING.value


# ============================================================================
# 日志查询引擎测试
# ============================================================================

class TestLogQueryEngine:
    """日志查询引擎测试 (OP-006)"""

    @pytest.fixture
    def temp_log_dir(self):
        """创建临时日志目录和测试日志文件（使用标准格式）"""
        with tempfile.TemporaryDirectory() as tmpdir:
            # 创建测试日志文件 - 使用格式: 时间 级别 模块: 消息
            log_file = os.path.join(tmpdir, "m8.log")
            now = datetime.now()
            log_lines = [
                f"{(now - timedelta(minutes=50)).strftime('%Y-%m-%d %H:%M:%S')} INFO m8: System started successfully",
                f"{(now - timedelta(minutes=45)).strftime('%Y-%m-%d %H:%M:%S')} INFO m8: Module registry initialized",
                f"{(now - timedelta(minutes=40)).strftime('%Y-%m-%d %H:%M:%S')} WARNING m8: High memory usage detected 85%",
                f"{(now - timedelta(minutes=35)).strftime('%Y-%m-%d %H:%M:%S')} ERROR m8: Database connection timeout",
                f"{(now - timedelta(minutes=30)).strftime('%Y-%m-%d %H:%M:%S')} ERROR m8: Failed to load config file",
                f"{(now - timedelta(minutes=25)).strftime('%Y-%m-%d %H:%M:%S')} INFO m8: User login user123",
                f"{(now - timedelta(minutes=20)).strftime('%Y-%m-%d %H:%M:%S')} CRITICAL m8: System crash detected",
                f"{(now - timedelta(minutes=15)).strftime('%Y-%m-%d %H:%M:%S')} DEBUG m8: Debug info trace id abc123",
                f"{(now - timedelta(minutes=10)).strftime('%Y-%m-%d %H:%M:%S')} INFO security: Login failed for user admin from 192.168.1.1",
                f"{(now - timedelta(minutes=5)).strftime('%Y-%m-%d %H:%M:%S')} INFO m8: Request processed in 150ms",
            ]
            with open(log_file, "w", encoding="utf-8") as f:
                f.write("\n".join(log_lines) + "\n")

            # 第二个日志文件
            log_file2 = os.path.join(tmpdir, "m1.log")
            log_lines2 = [
                f"{(now - timedelta(minutes=40)).strftime('%Y-%m-%d %H:%M:%S')} INFO m1: Agent hub started",
                f"{(now - timedelta(minutes=30)).strftime('%Y-%m-%d %H:%M:%S')} ERROR m1: Agent timeout error",
                f"{(now - timedelta(minutes=20)).strftime('%Y-%m-%d %H:%M:%S')} INFO m1: Task dispatched",
            ]
            with open(log_file2, "w", encoding="utf-8") as f:
                f.write("\n".join(log_lines2) + "\n")

            yield tmpdir

    def _get_engine(self, log_dir):
        from yunxi_shared.core.observability.log_query import LogQueryEngine
        return LogQueryEngine(log_dir=log_dir)

    def test_engine_initialization(self):
        """日志查询引擎初始化"""
        from yunxi_shared.core.observability.log_query import LogQueryEngine
        engine = LogQueryEngine()
        assert engine is not None

    def test_search_by_level_error(self, temp_log_dir):
        """按 ERROR 级别搜索（包含 CRITICAL）"""
        engine = self._get_engine(temp_log_dir)
        result = engine.search(level="ERROR")
        # ERROR 级别搜索会包含 CRITICAL
        assert result.total >= 3
        for entry in result.entries:
            assert entry.level in ("ERROR", "CRITICAL")

    def test_search_by_level_info(self, temp_log_dir):
        """按 INFO 级别搜索"""
        engine = self._get_engine(temp_log_dir)
        result = engine.search(level="INFO")
        assert result.total >= 3

    def test_search_by_module_m8(self, temp_log_dir):
        """按 m8 模块搜索"""
        engine = self._get_engine(temp_log_dir)
        result = engine.search(module="m8")
        assert result.total >= 5

    def test_search_by_module_m1(self, temp_log_dir):
        """按 m1 模块搜索"""
        engine = self._get_engine(temp_log_dir)
        result = engine.search(module="m1")
        assert result.total >= 2

    def test_search_by_keyword(self, temp_log_dir):
        """按关键字搜索"""
        engine = self._get_engine(temp_log_dir)
        result = engine.search(keyword="timeout")
        assert result.total >= 1
        for entry in result.entries:
            assert "timeout" in entry.raw_line.lower()

    def test_search_by_regex(self, temp_log_dir):
        """按正则表达式搜索（搜索 message 字段）"""
        engine = self._get_engine(temp_log_dir)
        # 搜索 message 中包含 timeout 的（不区分大小写）
        result = engine.search(regex=r"(?i)connection timeout")
        assert result.total >= 1

    def test_search_pagination(self, temp_log_dir):
        """日志搜索分页"""
        engine = self._get_engine(temp_log_dir)
        result = engine.search(level="INFO", page=1, page_size=2)
        assert len(result.entries) <= 2
        assert result.page == 1
        assert result.page_size == 2

    def test_search_case_sensitive(self, temp_log_dir):
        """大小写敏感搜索"""
        engine = self._get_engine(temp_log_dir)
        result_lower = engine.search(keyword="error", case_sensitive=False)
        result_upper = engine.search(keyword="ERROR", case_sensitive=True)
        # 不区分大小写应该找到更多（或相等）
        assert result_lower.total >= result_upper.total

    def test_get_stats(self, temp_log_dir):
        """日志统计"""
        engine = self._get_engine(temp_log_dir)
        stats = engine.get_stats(last_hours=24)
        assert stats.total_lines > 0
        assert stats.error_count >= 2
        assert stats.warning_count >= 1
        assert isinstance(stats.level_distribution, dict)

    def test_get_available_modules(self, temp_log_dir):
        """获取可用模块列表"""
        engine = self._get_engine(temp_log_dir)
        modules = engine.get_available_modules()
        assert isinstance(modules, list)
        assert "m8" in modules
        assert "m1" in modules

    def test_get_log_file_list(self, temp_log_dir):
        """获取日志文件列表"""
        engine = self._get_engine(temp_log_dir)
        files = engine.get_log_file_list()
        assert len(files) >= 2
        for f in files:
            assert "name" in f
            assert "size_kb" in f

    def test_log_category_enum(self):
        """日志分类枚举"""
        from yunxi_shared.core.observability.log_query import LogCategory
        categories = list(LogCategory)
        assert len(categories) >= 4
        cat_names = [c.value for c in categories]
        assert "system" in cat_names
        assert "security" in cat_names
        assert "business" in cat_names

    def test_search_by_category_security(self, temp_log_dir):
        """按安全分类搜索"""
        from yunxi_shared.core.observability.log_query import LogCategory
        engine = self._get_engine(temp_log_dir)
        result = engine.search(category=LogCategory.SECURITY)
        assert isinstance(result.total, int)

    def test_log_search_result_structure(self, temp_log_dir):
        """日志搜索结果结构"""
        engine = self._get_engine(temp_log_dir)
        result = engine.search(level="ERROR")
        assert hasattr(result, "total")
        assert hasattr(result, "entries")
        assert hasattr(result, "page")
        assert hasattr(result, "page_size")
        assert hasattr(result, "has_more")
        assert hasattr(result, "search_time_ms")


# ============================================================================
# 日志归档测试
# ============================================================================

class TestLogArchiver:
    """日志归档管理器测试 (OP-006)"""

    def test_archiver_initialization(self):
        """归档器初始化"""
        from yunxi_shared.core.observability.log_query import LogArchiver
        archiver = LogArchiver()
        assert archiver is not None

    def test_archive_config(self):
        """归档配置"""
        from yunxi_shared.core.observability.log_query import LogArchiver
        archiver = LogArchiver(log_dir="./logs", hot_days=7, warm_days=23)
        assert archiver._hot_days == 7
        assert archiver._warm_days == 23

    def test_archive_tier_enum(self):
        """归档层级枚举"""
        from yunxi_shared.core.observability.log_query import ArchiveTier
        tiers = list(ArchiveTier)
        assert len(tiers) == 3
        tier_names = [t.value for t in tiers]
        assert "hot" in tier_names
        assert "warm" in tier_names
        assert "cold" in tier_names

    def test_get_storage_stats_empty(self):
        """空目录存储统计"""
        from yunxi_shared.core.observability.log_query import LogArchiver
        with tempfile.TemporaryDirectory() as tmpdir:
            archiver = LogArchiver(log_dir=tmpdir)
            stats = archiver.get_storage_stats()
            assert isinstance(stats, dict)
            assert "hot" in stats
            assert "warm" in stats
            assert "cold" in stats

    def test_run_archive_dry_run(self):
        """归档试运行（不实际执行）"""
        from yunxi_shared.core.observability.log_query import LogArchiver
        with tempfile.TemporaryDirectory() as tmpdir:
            # 创建一些日志文件
            log_file = os.path.join(tmpdir, "m8.log")
            with open(log_file, "w") as f:
                f.write("test log data\n" * 100)
            archiver = LogArchiver(log_dir=tmpdir)
            result = archiver.run_archive(dry_run=True)
            assert result is not None
            assert hasattr(result, "files_archived")
            assert hasattr(result, "success")

    def test_archive_result_to_dict(self):
        """归档结果转字典"""
        from yunxi_shared.core.observability.log_query import ArchiveResult
        result = ArchiveResult(files_archived=5, bytes_freed=102400)
        d = result.to_dict()
        assert d["files_archived"] == 5
        assert "bytes_freed_mb" in d
        assert d["success"] is True

    def test_restore_from_cold_nonexistent(self):
        """从冷存储恢复不存在的文件"""
        from yunxi_shared.core.observability.log_query import LogArchiver
        with tempfile.TemporaryDirectory() as tmpdir:
            archiver = LogArchiver(log_dir=tmpdir)
            result = archiver.restore_from_cold("nonexistent_file.gz")
            assert result["success"] is False


# ============================================================================
# 指标定义测试
# ============================================================================

class TestMetricDefinitions:
    """监控指标定义测试 (OB-002)"""

    def test_system_metrics_exist(self):
        """系统指标存在"""
        from yunxi_shared.core.observability.metric_definitions import SYSTEM_METRICS
        assert len(SYSTEM_METRICS) >= 10

    def test_business_metrics_exist(self):
        """业务指标存在"""
        from yunxi_shared.core.observability.metric_definitions import BUSINESS_METRICS
        assert len(BUSINESS_METRICS) >= 10

    def test_module_metrics_exist(self):
        """模块指标存在"""
        from yunxi_shared.core.observability.metric_definitions import MODULE_METRICS
        assert len(MODULE_METRICS) >= 5

    def test_security_metrics_exist(self):
        """安全指标存在"""
        from yunxi_shared.core.observability.metric_definitions import SECURITY_METRICS
        assert len(SECURITY_METRICS) >= 5

    def test_metric_definition_structure(self):
        """指标定义结构完整性"""
        from yunxi_shared.core.observability.metric_definitions import SYSTEM_METRICS
        for metric in SYSTEM_METRICS[:5]:
            assert hasattr(metric, "name")
            assert hasattr(metric, "metric_type")
            assert hasattr(metric, "help")
            assert hasattr(metric, "category")

    def test_metric_naming_convention(self):
        """指标命名规范（全小写+下划线）"""
        from yunxi_shared.core.observability.metric_definitions import (
            SYSTEM_METRICS, BUSINESS_METRICS
        )
        all_metrics = SYSTEM_METRICS + BUSINESS_METRICS
        for metric in all_metrics[:10]:
            assert metric.name == metric.name.lower(), f"{metric.name} 不是全小写"
            assert " " not in metric.name, f"{metric.name} 包含空格"

    def test_get_all_metrics(self):
        """获取所有指标"""
        from yunxi_shared.core.observability.metric_definitions import get_all_metrics
        all_metrics = get_all_metrics()
        assert isinstance(all_metrics, list)
        assert len(all_metrics) >= 30

    def test_get_metrics_by_category(self):
        """按分类获取指标"""
        from yunxi_shared.core.observability.metric_definitions import get_metrics_by_category
        sys_metrics = get_metrics_by_category("system")
        assert len(sys_metrics) >= 10
        biz_metrics = get_metrics_by_category("business")
        assert len(biz_metrics) >= 10

    def test_get_metric_by_name(self):
        """按名称获取指标"""
        from yunxi_shared.core.observability.metric_definitions import get_metric_by_name
        metric = get_metric_by_name("system_cpu_usage_percent")
        assert metric is not None
        assert metric.name == "system_cpu_usage_percent"

    def test_get_metric_by_name_not_found(self):
        """获取不存在的指标"""
        from yunxi_shared.core.observability.metric_definitions import get_metric_by_name
        metric = get_metric_by_name("nonexistent_metric_xyz")
        assert metric is None

    def test_metric_type_enum(self):
        """指标类型枚举"""
        from yunxi_shared.core.observability.metric_definitions import MetricType
        types = list(MetricType)
        type_names = [t.value for t in types]
        assert "counter" in type_names
        assert "gauge" in type_names
        assert "histogram" in type_names

    def test_alert_thresholds_exist(self):
        """告警阈值配置存在"""
        from yunxi_shared.core.observability.metric_definitions import ALERT_THRESHOLDS
        assert len(ALERT_THRESHOLDS) >= 5
        for metric_name, thresholds in ALERT_THRESHOLDS.items():
            assert "warning" in thresholds
            assert "critical" in thresholds

    def test_metrics_to_dict(self):
        """指标转字典"""
        from yunxi_shared.core.observability.metric_definitions import (
            SYSTEM_METRICS, metrics_to_dict
        )
        result = metrics_to_dict(SYSTEM_METRICS[:3])
        assert isinstance(result, list)
        assert len(result) == 3
        assert isinstance(result[0], dict)
        assert "name" in result[0]
        assert "help" in result[0]
        assert "type" in result[0]

    def test_metric_labels(self):
        """指标标签定义"""
        from yunxi_shared.core.observability.metric_definitions import SYSTEM_METRICS
        cpu_metric = next((m for m in SYSTEM_METRICS if "cpu" in m.name), None)
        assert cpu_metric is not None
        assert isinstance(cpu_metric.labels, list)

    def test_register_standard_metrics(self):
        """注册标准指标"""
        from yunxi_shared.core.observability.metric_definitions import (
            register_standard_metrics
        )
        # 使用 mock 收集器
        mock_collector = MagicMock()
        mock_collector.counter = MagicMock()
        mock_collector.gauge = MagicMock()
        mock_collector.histogram = MagicMock()
        mock_collector.summary = MagicMock()

        result = register_standard_metrics(
            mock_collector, module_name="test_mod", categories=["system"]
        )
        assert isinstance(result, dict)
        assert "gauges" in result
        assert result["gauges"] > 0


# ============================================================================
# 仪表盘生成测试
# ============================================================================

class TestDashboards:
    """Grafana 仪表盘生成测试 (OB-004)"""

    def test_system_overview_dashboard(self):
        """系统总览仪表盘生成"""
        from yunxi_shared.core.observability.dashboards import (
            generate_system_overview_dashboard
        )
        dashboard = generate_system_overview_dashboard()
        assert isinstance(dashboard, dict)
        assert dashboard["title"] is not None
        assert "panels" in dashboard
        assert len(dashboard["panels"]) > 5

    def test_business_dashboard(self):
        """业务监控仪表盘生成"""
        from yunxi_shared.core.observability.dashboards import (
            generate_business_dashboard
        )
        dashboard = generate_business_dashboard()
        assert isinstance(dashboard, dict)
        assert "panels" in dashboard
        assert len(dashboard["panels"]) > 3

    def test_security_dashboard(self):
        """安全监控仪表盘生成"""
        from yunxi_shared.core.observability.dashboards import (
            generate_security_dashboard
        )
        dashboard = generate_security_dashboard()
        assert isinstance(dashboard, dict)
        assert "panels" in dashboard
        assert len(dashboard["panels"]) > 3

    def test_module_detail_dashboard(self):
        """模块详情仪表盘生成"""
        from yunxi_shared.core.observability.dashboards import (
            generate_module_detail_dashboard
        )
        dashboard = generate_module_detail_dashboard("m8")
        assert isinstance(dashboard, dict)
        title = dashboard.get("title", "")
        assert "m8" in title.lower() or "M8" in title or "模块" in title

    def test_dashboard_json_serializable(self):
        """仪表盘 JSON 可序列化"""
        from yunxi_shared.core.observability.dashboards import (
            generate_system_overview_dashboard
        )
        dashboard = generate_system_overview_dashboard()
        json_str = json.dumps(dashboard, ensure_ascii=False)
        assert len(json_str) > 100
        # 验证反序列化
        parsed = json.loads(json_str)
        assert parsed["title"] == dashboard["title"]

    def test_generate_all_dashboards(self):
        """生成所有仪表盘"""
        from yunxi_shared.core.observability.dashboards import generate_all_dashboards
        with tempfile.TemporaryDirectory() as tmpdir:
            result = generate_all_dashboards(tmpdir)
            assert isinstance(result, dict)
            assert len(result) >= 4
            for name, path in result.items():
                assert os.path.exists(path), f"文件未生成: {path}"

    def test_dashboard_registry(self):
        """仪表盘注册表"""
        from yunxi_shared.core.observability.dashboards import DASHBOARD_REGISTRY
        assert isinstance(DASHBOARD_REGISTRY, dict)
        assert len(DASHBOARD_REGISTRY) >= 4

    def test_panel_type_constants(self):
        """面板类型常量"""
        from yunxi_shared.core.observability.dashboards import PanelType
        assert PanelType.STAT == "stat"
        assert PanelType.TIMESERIES == "timeseries"
        assert PanelType.GAUGE == "gauge"

    def test_dashboard_variables(self):
        """仪表盘变量定义"""
        from yunxi_shared.core.observability.dashboards import (
            generate_system_overview_dashboard
        )
        dashboard = generate_system_overview_dashboard()
        assert "templating" in dashboard
        assert "list" in dashboard["templating"]
        assert len(dashboard["templating"]["list"]) >= 1

    def test_dashboard_time_range(self):
        """仪表盘时间范围配置"""
        from yunxi_shared.core.observability.dashboards import (
            generate_system_overview_dashboard
        )
        dashboard = generate_system_overview_dashboard()
        assert "time" in dashboard
        assert "from" in dashboard["time"]
        assert "to" in dashboard["time"]


# ============================================================================
# 可观测性模块导出测试
# ============================================================================

class TestObservabilityExports:
    """可观测性模块导出测试"""

    def test_rolling_upgrade_exports(self):
        """滚动升级模块导出"""
        from yunxi_shared.core.observability import (
            UpgradeStrategy,
            UpgradePhase,
            UpgradeStatus,
            UpgradeConfig,
            RollingUpgradeManager,
            get_upgrade_manager,
        )
        assert UpgradeStrategy is not None
        assert RollingUpgradeManager is not None
        assert callable(get_upgrade_manager)

    def test_log_query_exports(self):
        """日志查询模块导出"""
        from yunxi_shared.core.observability import (
            LogQueryEngine,
            LogSearchResult,
            LogArchiver,
            ArchiveTier,
            get_log_query_engine,
        )
        assert LogQueryEngine is not None
        assert LogArchiver is not None
        assert callable(get_log_query_engine)

    def test_metric_definitions_exports(self):
        """指标定义模块导出"""
        from yunxi_shared.core.observability import (
            MetricType,
            MetricDefinition,
            SYSTEM_METRICS,
            BUSINESS_METRICS,
            MODULE_METRICS,
            SECURITY_METRICS,
            ALERT_THRESHOLDS,
            get_all_metrics,
            get_metrics_by_category,
            get_metric_by_name,
            register_standard_metrics,
        )
        assert SYSTEM_METRICS is not None
        assert callable(get_all_metrics)

    def test_dashboard_exports(self):
        """仪表盘模块导出"""
        from yunxi_shared.core.observability import (
            generate_system_overview_dashboard,
            generate_business_dashboard,
            generate_security_dashboard,
            generate_module_detail_dashboard,
            generate_all_dashboards,
            DASHBOARD_REGISTRY,
            PanelType,
        )
        assert callable(generate_all_dashboards)
        assert DASHBOARD_REGISTRY is not None

    def test_get_upgrade_manager_singleton(self):
        """升级管理器单例"""
        from yunxi_shared.core.observability import (
            get_upgrade_manager, reset_upgrade_manager
        )
        reset_upgrade_manager()
        m1 = get_upgrade_manager()
        m2 = get_upgrade_manager()
        assert m1 is m2
        reset_upgrade_manager()
        m3 = get_upgrade_manager()
        assert m1 is not m3

    def test_get_log_query_engine_singleton(self):
        """日志查询引擎单例"""
        from yunxi_shared.core.observability import (
            get_log_query_engine, reset_log_query_engine
        )
        reset_log_query_engine()
        e1 = get_log_query_engine()
        e2 = get_log_query_engine()
        assert e1 is e2
        reset_log_query_engine()
        e3 = get_log_query_engine()
        assert e1 is not e3
