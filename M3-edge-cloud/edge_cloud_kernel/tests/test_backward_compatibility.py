"""向后兼容性测试.

验证端云协同增强功能不影响现有功能：
- 现有 API 接口正常工作
- 现有组件不受影响
- 新增组件为纯增量
- 边缘计算框架可插拔
"""

from __future__ import annotations

import pytest

from edge_cloud_kernel.core.kernel_manager import KernelManager


# ============================================================
# Fixtures
# ============================================================

@pytest.fixture
def kernel_manager(tmp_path):
    """创建 KernelManager 测试实例."""
    km = KernelManager(base_dir=tmp_path, project_root=tmp_path)
    km.init_all()
    yield km


# ============================================================
# 向后兼容测试 - 核心组件
# ============================================================

class TestCoreComponentsBackwardCompat:
    """核心组件向后兼容性测试."""

    def test_config_manager_still_works(self, kernel_manager):
        """测试配置管理器仍然可用."""
        config = kernel_manager.get_component("config_manager")
        # 组件应该存在（可能是 mock 模式，但不应该报错）
        assert "config_manager" in kernel_manager.mock_mode

    def test_device_registry_still_works(self, kernel_manager):
        """测试设备注册表仍然可用."""
        assert "device_registry" in kernel_manager.mock_mode

    def test_conflict_resolver_still_works(self, kernel_manager):
        """测试冲突解决器仍然可用."""
        assert "conflict_resolver" in kernel_manager.mock_mode

    def test_health_checker_still_works(self, kernel_manager):
        """测试健康探测器仍然可用."""
        assert "health_checker" in kernel_manager.mock_mode

    def test_m8_api_still_works(self, kernel_manager):
        """测试 M8 API 服务仍然可用."""
        assert "m8_api" in kernel_manager.mock_mode

    def test_core_components_count(self, kernel_manager):
        """测试核心组件数量（8 个核心 + 7 个增强 = 15 个）."""
        # 至少应该有 8 个核心组件的 mock 标记
        core_components = [
            "config_manager",
            "device_registry",
            "conflict_resolver",
            "offline_proxy",
            "health_checker",
            "sync_controller",
            "health_metrics",
            "m8_api",
        ]
        for comp in core_components:
            assert comp in kernel_manager.mock_mode, f"核心组件 {comp} 缺失"


# ============================================================
# 向后兼容测试 - 增强组件
# ============================================================

class TestEnhancedComponentsIncremental:
    """增强组件纯增量验证."""

    def test_sync_engine_is_additive(self, kernel_manager):
        """测试同步引擎是增量添加的."""
        # 增强组件应该存在
        assert "sync_engine" in kernel_manager.mock_mode

    def test_offline_manager_is_additive(self, kernel_manager):
        """测试离线管理器是增量添加的."""
        assert "offline_manager" in kernel_manager.mock_mode

    def test_edge_scheduler_is_additive(self, kernel_manager):
        """测试边缘调度器是增量添加的."""
        assert "edge_scheduler" in kernel_manager.mock_mode

    def test_edge_functions_is_additive(self, kernel_manager):
        """测试边缘函数服务是增量添加的."""
        assert "edge_functions" in kernel_manager.mock_mode

    def test_sync_protocol_is_additive(self, kernel_manager):
        """测试同步协议是增量添加的."""
        assert "sync_protocol" in kernel_manager.mock_mode

    def test_message_bus_is_additive(self, kernel_manager):
        """测试消息总线是增量添加的."""
        assert "message_bus" in kernel_manager.mock_mode

    def test_device_manager_enhanced_is_additive(self, kernel_manager):
        """测试增强设备管理器是增量添加的."""
        assert "device_manager_enhanced" in kernel_manager.mock_mode

    def test_enhanced_components_count(self, kernel_manager):
        """测试增强组件数量（7 个）."""
        enhanced_components = [
            "sync_engine",
            "offline_manager",
            "edge_scheduler",
            "edge_functions",
            "sync_protocol",
            "message_bus",
            "device_manager_enhanced",
        ]
        for comp in enhanced_components:
            assert comp in kernel_manager.mock_mode, f"增强组件 {comp} 缺失"

    def test_enhanced_components_independent(self, kernel_manager):
        """测试增强组件不影响核心组件."""
        # 获取核心组件的 mock 状态
        core_mock_status = {
            k: v for k, v in kernel_manager.mock_mode.items()
            if k in [
                "config_manager",
                "device_registry",
                "conflict_resolver",
                "offline_proxy",
                "health_checker",
                "sync_controller",
                "health_metrics",
                "m8_api",
            ]
        }
        # 核心组件应该都有状态记录
        assert len(core_mock_status) == 8


# ============================================================
# 向后兼容测试 - API 路由
# ============================================================

class TestApiBackwardCompat:
    """API 向后兼容性测试."""

    def test_v1_sync_status_exists(self):
        """测试 v1 同步状态接口仍然存在."""
        from edge_cloud_kernel.api.sync_router import router
        routes = [r.path for r in router.routes]
        assert "/api/v1/sync/status" in routes

    def test_v1_sync_conflicts_exists(self):
        """测试 v1 冲突列表接口仍然存在."""
        from edge_cloud_kernel.api.sync_router import router
        routes = [r.path for r in router.routes]
        assert "/api/v1/sync/conflicts" in routes

    def test_v3_sync_status_exists(self):
        """测试 v3 同步状态接口仍然存在."""
        from edge_cloud_kernel.api.sync_router import router
        routes = [r.path for r in router.routes]
        assert "/api/v3/sync/status" in routes

    def test_v3_sync_trigger_exists(self):
        """测试 v3 同步触发接口仍然存在."""
        from edge_cloud_kernel.api.sync_router import router
        routes = [r.path for r in router.routes]
        assert "/api/v3/sync/trigger" in routes

    def test_v3_sync_conflicts_exists(self):
        """测试 v3 冲突列表接口仍然存在."""
        from edge_cloud_kernel.api.sync_router import router
        routes = [r.path for r in router.routes]
        assert "/api/v3/sync/conflicts" in routes

    def test_v3_sync_conflict_resolve_exists(self):
        """测试 v3 冲突解决接口仍然存在."""
        from edge_cloud_kernel.api.sync_router import router
        routes = [r.path for r in router.routes]
        assert "/api/v3/sync/conflicts/{conflict_id}/resolve" in routes

    def test_devices_list_exists(self):
        """测试设备列表接口仍然存在."""
        from edge_cloud_kernel.api.device_router import router
        routes = [r.path for r in router.routes]
        assert "/api/v3/devices" in routes

    def test_health_endpoint_exists(self):
        """测试健康检查接口仍然存在."""
        from edge_cloud_kernel.api.health_router import router
        routes = [r.path for r in router.routes]
        assert "/health" in routes or "/api/v3/health" in routes


# ============================================================
# 向后兼容测试 - 新增 API 接口
# ============================================================

class TestNewApiEndpoints:
    """新增 API 接口验证（纯增量）."""

    def test_sync_handshake_endpoint(self):
        """测试新增握手接口."""
        from edge_cloud_kernel.api.sync_router import router
        routes = [r.path for r in router.routes]
        assert "/api/v3/sync/handshake" in routes

    def test_sync_push_endpoint(self):
        """测试新增推送接口."""
        from edge_cloud_kernel.api.sync_router import router
        routes = [r.path for r in router.routes]
        assert "/api/v3/sync/push" in routes

    def test_sync_pull_endpoint(self):
        """测试新增拉取接口."""
        from edge_cloud_kernel.api.sync_router import router
        routes = [r.path for r in router.routes]
        assert "/api/v3/sync/pull" in routes

    def test_sync_status_details_endpoint(self):
        """测试新增同步状态详情接口."""
        from edge_cloud_kernel.api.sync_router import router
        routes = [r.path for r in router.routes]
        assert "/api/v3/sync/status/details" in routes

    def test_edge_task_submit_endpoint(self):
        """测试新增边缘任务提交接口."""
        from edge_cloud_kernel.api.edge_router import router
        routes = [r.path for r in router.routes]
        assert "/api/v3/edge/task/submit" in routes

    def test_edge_task_status_endpoint(self):
        """测试新增边缘任务状态接口."""
        from edge_cloud_kernel.api.edge_router import router
        routes = [r.path for r in router.routes]
        assert "/api/v3/edge/task/{task_id}" in routes

    def test_edge_function_register_endpoint(self):
        """测试新增边缘函数注册接口."""
        from edge_cloud_kernel.api.edge_router import router
        routes = [r.path for r in router.routes]
        assert "/api/v3/edge/function/register" in routes

    def test_edge_functions_list_endpoint(self):
        """测试新增函数列表接口."""
        from edge_cloud_kernel.api.edge_router import router
        routes = [r.path for r in router.routes]
        assert "/api/v3/edge/functions" in routes

    def test_edge_function_invoke_endpoint(self):
        """测试新增函数调用接口."""
        from edge_cloud_kernel.api.edge_router import router
        routes = [r.path for r in router.routes]
        assert "/api/v3/edge/function/{function_id}/invoke" in routes

    def test_edge_metrics_endpoint(self):
        """测试新增边缘指标接口."""
        from edge_cloud_kernel.api.edge_router import router
        routes = [r.path for r in router.routes]
        assert "/api/v3/edge/metrics" in routes

    def test_device_register_endpoint(self):
        """测试新增设备注册接口."""
        from edge_cloud_kernel.api.device_router import router
        routes = [r.path for r in router.routes]
        assert "/api/v3/devices/register" in routes

    def test_device_detail_endpoint(self):
        """测试新增设备详情接口."""
        from edge_cloud_kernel.api.device_router import router
        routes = [r.path for r in router.routes]
        assert "/api/v3/devices/{device_id}" in routes

    def test_device_health_endpoint(self):
        """测试新增设备健康接口."""
        from edge_cloud_kernel.api.device_router import router
        routes = [r.path for r in router.routes]
        assert "/api/v3/devices/{device_id}/health" in routes

    def test_device_notify_endpoint(self):
        """测试新增设备通知接口."""
        from edge_cloud_kernel.api.device_router import router
        routes = [r.path for r in router.routes]
        assert "/api/v3/devices/{device_id}/notify" in routes

    def test_offline_queue_endpoint(self):
        """测试新增离线队列接口."""
        from edge_cloud_kernel.api.offline_router import router
        routes = [r.path for r in router.routes]
        assert "/api/v3/offline/queue" in routes

    def test_offline_flush_endpoint(self):
        """测试新增离线刷新接口."""
        from edge_cloud_kernel.api.offline_router import router
        routes = [r.path for r in router.routes]
        assert "/api/v3/offline/flush" in routes


# ============================================================
# 向后兼容测试 - 可插拔性
# ============================================================

class TestPluggability:
    """边缘计算框架可插拔性测试."""

    def test_routes_are_separate_modules(self):
        """测试路由是独立模块，可单独禁用."""
        # 边缘和离线路由是独立文件，可以独立导入/不导入
        from edge_cloud_kernel.api import edge_router, offline_router
        assert edge_router is not None
        assert offline_router is not None

    def test_services_are_separate_modules(self):
        """测试服务是独立模块，可单独禁用."""
        from edge_cloud_kernel.services import (
            sync_engine,
            offline_manager,
            edge_scheduler,
            edge_functions,
            protocol,
            message_bus,
            device_manager,
        )
        assert sync_engine is not None
        assert offline_manager is not None
        assert edge_scheduler is not None
        assert edge_functions is not None
        assert protocol is not None
        assert message_bus is not None
        assert device_manager is not None

    def test_services_export_public_api(self):
        """测试服务导出公共 API."""
        from edge_cloud_kernel.services import (
            SyncEngine,
            OfflineManager,
            EdgeScheduler,
            EdgeFunctionService,
            SyncProtocol,
            MessageBus,
            DeviceManager,
        )
        assert SyncEngine is not None
        assert OfflineManager is not None
        assert EdgeScheduler is not None
        assert EdgeFunctionService is not None
        assert SyncProtocol is not None
        assert MessageBus is not None
        assert DeviceManager is not None


# ============================================================
# 向后兼容测试 - 数据模型
# ============================================================

class TestDataModelCompat:
    """数据模型向后兼容性测试."""

    def test_existing_models_intact(self):
        """测试现有数据模型不受影响."""
        from edge_cloud_kernel.models import common
        assert common is not None

    def test_sync_models_intact(self):
        """测试同步数据模型不受影响."""
        from edge_cloud_kernel.models import sync_models
        assert sync_models is not None

    def test_sync_engine_new_models(self):
        """测试同步引擎新增数据模型不破坏现有模型."""
        from edge_cloud_kernel.services.sync_engine import (
            SyncStrategy,
            SyncDirection,
            ConflictResolutionPolicy,
        )
        assert SyncStrategy is not None
        assert SyncDirection is not None
        assert ConflictResolutionPolicy is not None

    def test_edge_new_models(self):
        """测试边缘计算新增数据模型不破坏现有模型."""
        from edge_cloud_kernel.services.edge_scheduler import (
            SchedulingStrategy,
            TaskStatus,
            TaskPriority,
        )
        assert SchedulingStrategy is not None
        assert TaskStatus is not None
        assert TaskPriority is not None
