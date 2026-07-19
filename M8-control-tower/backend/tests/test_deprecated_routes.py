# -*- coding: utf-8 -*-
"""
M8 已弃用路由测试（P2 级路由清理验证）

验证 P2 级路由清理后的行为：
1. OpsStatusAggregator 降级逻辑正常（/m8/health → /health）
2. MonitorService 标准功能正常
3. system.py / monitor.py 中废弃代码有弃用标记（源码检查）
4. health_service.py 中标准路径端点存在
5. ModuleClient 健康检查降级逻辑存在
6. 弃用路由文档完整

运行方式:
  cd M8-control-tower/backend
  pytest tests/test_deprecated_routes.py -v
"""

import sys
import os
import re
import warnings
import logging
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

# ============================================================
# 路径设置
# ============================================================

_M8_ROOT = Path(__file__).resolve().parent.parent
_PROJECT_ROOT = _M8_ROOT.parent.parent
for _p in (str(_M8_ROOT), str(_PROJECT_ROOT)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

# 设置环境
os.environ.setdefault("YUNXI_ENV", "testing")
os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")


# ============================================================
# 模块导入
# ============================================================

import importlib.util


def _load_module(name: str, file_path: Path):
    """使用 importlib.util 直接加载模块，绕过包级 __init__.py 的依赖问题"""
    spec = importlib.util.spec_from_file_location(name, str(file_path))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# 预加载无相对导入依赖的模块
_monitor_service_mod = _load_module(
    "monitor_service",
    _M8_ROOT / "services" / "monitor_service.py",
)

_ops_aggregator_mod = _load_module(
    "ops_status_aggregator",
    _M8_ROOT / "services" / "ops_status_aggregator.py",
)

# 源码文件路径（用于静态检查）
_SYSTEM_PY = _M8_ROOT / "routers" / "system.py"
_MONITOR_PY = _M8_ROOT / "routers" / "monitor.py"
_HEALTH_SERVICE_PY = _M8_ROOT / "services" / "health_service.py"
_MODULE_CLIENT_PY = _PROJECT_ROOT / "shared" / "business" / "module_client.py"
_DEPRECATED_DOC = _PROJECT_ROOT / "M8-control-tower" / "docs" / "deprecated_routes.md"


def _read_source(path: Path) -> str:
    """读取源码文件"""
    return path.read_text(encoding="utf-8")


def _find_route_handler(source: str, route_path: str, method: str = "get"):
    """
    找到指定路由路径的处理函数名和函数体。
    通过匹配 @router.{method}("{path}") 装饰器紧接的 def 行。
    返回 (func_name, func_body)
    """
    # 精确匹配：装饰器行后紧跟 def（可能中间有其他装饰器或空行）
    # 只匹配以 @router.{method} 开头，包含 "{path}" 的行
    # 然后找到紧随其后的第一个顶层 def（缩进4空格或更少）
    lines = source.split("\n")
    in_decorator = False
    func_name = ""

    for i, line in enumerate(lines):
        # 匹配装饰器行
        if not in_decorator:
            if re.match(rf'\s*@router\.{method}\(\s*"{re.escape(route_path)}"', line):
                in_decorator = True
            continue

        # 找到装饰器后的第一个 def 行（非内部函数，缩进应与装饰器同级或更少）
        # 注意：函数可能是 async def
        def_match = re.match(r'^(\s*)(?:async\s+)?def (\w+)\s*\(', line)
        if def_match:
            indent = def_match.group(1)
            # 只匹配顶层函数（缩进 <= 4 空格，即模块级函数）
            if len(indent) <= 4:
                func_name = def_match.group(2)
                break

    if not func_name:
        return "", ""

    # 提取函数体
    func_body = _find_function_body_by_name(source, func_name)
    return func_name, func_body


def _get_function_docstring(func_body: str) -> str:
    """从函数体中提取 docstring"""
    doc_match = re.search(r'^\s+"""(.*?)"""', func_body, re.DOTALL)
    if doc_match:
        return doc_match.group(1)
    return ""


def _find_function_body_by_name(source: str, func_name: str) -> str:
    """通过函数名查找函数体（支持 async def）"""
    pattern = rf'^(?:async\s+)?def {func_name}\(.*?\)(?:\s*->.*?)?:(.*?)(?=\n^(?:async\s+)?def |\n^class |\Z)'
    match = re.search(pattern, source, re.MULTILINE | re.DOTALL)
    if match:
        return match.group(1)
    return ""


# ============================================================
# 测试用例 - OpsStatusAggregator 降级逻辑
# ============================================================


class TestOpsAggregatorFallbackLogic:
    """测试 OpsStatusAggregator 的 /health 降级逻辑"""

    def test_standard_m8_health_success(self):
        """用例1：标准路径 /m8/health 调用成功，标记为标准接入"""
        OpsStatusAggregator = _ops_aggregator_mod.OpsStatusAggregator
        from shared.health.health_checker import HealthStatus

        agg = OpsStatusAggregator(cache_ttl=1, history_size=10)
        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "code": 0,
            "message": "ok",
            "data": {
                "status": "healthy",
                "score": 95,
                "uptime_seconds": 3600,
            },
        }
        mock_client.get.return_value = mock_resp

        with patch("httpx.Client", return_value=mock_client):
            agg._refresh_module("m7")

        snap = agg._snapshots["m7"]
        assert snap.status == HealthStatus.HEALTHY
        assert snap.score == 95
        assert snap.is_standard_m8 is True
        assert snap.used_fallback is False

    def test_fallback_on_404(self):
        """用例2：/m8/health 返回 404 时降级到 /health，标记非标准接入"""
        OpsStatusAggregator = _ops_aggregator_mod.OpsStatusAggregator
        from shared.health.health_checker import HealthStatus

        agg = OpsStatusAggregator(cache_ttl=1, history_size=10)
        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)

        call_order = []

        def mock_get(url, **kwargs):
            call_order.append(url)
            resp = MagicMock()
            if "/m8/health" in url:
                resp.status_code = 404
            elif "/health" in url and "/m8/" not in url:
                resp.status_code = 200
                resp.json.return_value = {"status": "healthy", "score": 80}
            else:
                resp.status_code = 404
            return resp

        mock_client.get.side_effect = mock_get

        with patch("httpx.Client", return_value=mock_client):
            agg._refresh_module("m6")

        snap = agg._snapshots["m6"]
        assert snap.status == HealthStatus.HEALTHY
        assert snap.is_standard_m8 is False
        assert snap.used_fallback is True
        assert len(call_order) == 2
        assert "/m8/health" in call_order[0]
        assert "/health" in call_order[1] and "/m8/" not in call_order[1]

    def test_fallback_on_connection_error(self):
        """用例3：/m8/health 连接失败时降级到 /health"""
        OpsStatusAggregator = _ops_aggregator_mod.OpsStatusAggregator
        import httpx

        agg = OpsStatusAggregator(cache_ttl=1, history_size=10)
        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)

        call_order = []

        def mock_get(url, **kwargs):
            call_order.append(url)
            if "/m8/health" in url:
                raise httpx.ConnectError("connection refused")
            resp = MagicMock()
            resp.status_code = 200
            resp.json.return_value = {"status": "healthy", "score": 70}
            return resp

        mock_client.get.side_effect = mock_get

        with patch("httpx.Client", return_value=mock_client):
            agg._refresh_module("m5")

        snap = agg._snapshots["m5"]
        assert snap.is_standard_m8 is False
        assert snap.used_fallback is True
        assert len(call_order) == 2

    def test_both_fail_returns_unhealthy(self):
        """用例4：/m8/health 和 /health 都连接失败时返回 UNHEALTHY"""
        OpsStatusAggregator = _ops_aggregator_mod.OpsStatusAggregator
        from shared.health.health_checker import HealthStatus
        import httpx

        agg = OpsStatusAggregator(cache_ttl=1, history_size=10)
        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)

        call_order = []

        def mock_get(url, **kwargs):
            call_order.append(url)
            raise httpx.ConnectError("connection refused")

        mock_client.get.side_effect = mock_get

        with patch("httpx.Client", return_value=mock_client):
            agg._refresh_module("m4")

        snap = agg._snapshots["m4"]
        # 连接失败时标记为不健康
        assert snap.status == HealthStatus.UNHEALTHY
        # 两个路径都连接失败，至少尝试了两个路径
        assert len(call_order) >= 2

    def test_fallback_logs_warning(self, caplog):
        """用例5：降级时记录 WARNING 日志"""
        OpsStatusAggregator = _ops_aggregator_mod.OpsStatusAggregator
        import httpx

        agg = OpsStatusAggregator(cache_ttl=1, history_size=10)
        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)

        call_order = []

        def mock_get(url, **kwargs):
            call_order.append(url)
            if "/m8/health" in url:
                raise httpx.ConnectError("connection refused")
            resp = MagicMock()
            resp.status_code = 200
            resp.json.return_value = {"status": "healthy", "score": 70}
            return resp

        mock_client.get.side_effect = mock_get

        with caplog.at_level(logging.WARNING):
            with patch("httpx.Client", return_value=mock_client):
                agg._refresh_module("m5")

        # 检查降级警告日志
        fallback_logs = [
            record for record in caplog.records
            if "降级" in record.message or "fallback" in record.message.lower()
        ]
        assert len(fallback_logs) > 0, "降级时应记录 WARNING 日志"


# ============================================================
# 测试用例 - MonitorService 标准功能
# ============================================================


class TestMonitorServiceStandard:
    """测试 MonitorService 标准功能（验证新路径依赖的服务正常）"""

    def test_get_system_metrics_returns_dict(self):
        """用例6：MonitorService.get_system_metrics() 返回正确结构"""
        MonitorService = _monitor_service_mod.MonitorService
        service = MonitorService()

        result = service.get_system_metrics()

        assert result is not None
        assert isinstance(result, dict)
        assert "cpu" in result
        assert "memory" in result
        assert isinstance(result["cpu"], dict)
        assert "usage_percent" in result["cpu"] or "usage" in result["cpu"]

    def test_get_history_data_returns_dict(self):
        """用例7：MonitorService.get_history_data() 返回正确结构"""
        MonitorService = _monitor_service_mod.MonitorService
        service = MonitorService()

        # 先收集一个数据点
        service.collect_history_point()

        result = service.get_history_data("1h")

        assert result is not None
        assert isinstance(result, dict)
        assert "period" in result
        assert result["period"] == "1h"
        # 历史数据可能是点列表或按指标分列的数组
        has_points = "points" in result
        has_timestamps = "timestamps" in result
        assert has_points or has_timestamps, "历史数据应包含 points 或 timestamps"


# ============================================================
# 测试用例 - monitor.py 向后兼容函数弃用标记（源码检查）
# ============================================================


class TestMonitorRouterDeprecationSource:
    """测试 monitor.py 中向后兼容函数的弃用标记（源码静态检查）"""

    def test_get_system_metrics_has_deprecation_warning(self):
        """用例8：_get_system_metrics() 函数中有 DeprecationWarning"""
        source = _read_source(_MONITOR_PY)

        assert "def _get_system_metrics" in source
        assert "DeprecationWarning" in source

        func_body = _find_function_body_by_name(source, "_get_system_metrics")
        assert func_body, "应找到 _get_system_metrics 函数体"
        assert "warnings.warn" in func_body, "_get_system_metrics 应调用 warnings.warn"
        assert "DeprecationWarning" in func_body, "_get_system_metrics 应使用 DeprecationWarning"

    def test_get_history_data_has_deprecation_warning(self):
        """用例9：_get_history_data() 函数中有 DeprecationWarning"""
        source = _read_source(_MONITOR_PY)

        assert "def _get_history_data" in source

        func_body = _find_function_body_by_name(source, "_get_history_data")
        assert func_body, "应找到 _get_history_data 函数体"
        assert "warnings.warn" in func_body, "_get_history_data 应调用 warnings.warn"
        assert "DeprecationWarning" in func_body, "_get_history_data 应使用 DeprecationWarning"

    def test_deprecated_functions_have_docstring_marker(self):
        """用例10：弃用函数的 docstring 中有 Deprecated 标记"""
        source = _read_source(_MONITOR_PY)

        # 检查 _get_system_metrics 的 docstring
        func_body = _find_function_body_by_name(source, "_get_system_metrics")
        doc = _get_function_docstring(func_body)
        assert doc, "_get_system_metrics 应有 docstring"
        assert "Deprecated" in doc or "弃用" in doc, \
            f"_get_system_metrics docstring 应包含弃用标记: {doc[:100]}"

        # 检查 _get_history_data 的 docstring
        func_body = _find_function_body_by_name(source, "_get_history_data")
        doc = _get_function_docstring(func_body)
        assert doc, "_get_history_data 应有 docstring"
        assert "Deprecated" in doc or "弃用" in doc, \
            f"_get_history_data docstring 应包含弃用标记: {doc[:100]}"


# ============================================================
# 测试用例 - system.py 废弃路由弃用标记（源码检查）
# ============================================================


class TestSystemRouterDeprecationSource:
    """测试 system.py 中废弃路由的弃用标记（源码静态检查）"""

    def test_system_health_has_deprecated_docstring(self):
        """用例11：/api/system/health 端点函数有弃用文档标记"""
        source = _read_source(_SYSTEM_PY)

        func_name, func_body = _find_route_handler(source, "/health", "get")
        assert func_name, f"应找到 /health 路由处理函数, 实际找到: {func_name}"

        doc = _get_function_docstring(func_body)
        assert doc, f"{func_name} 应有 docstring"
        assert "Deprecated" in doc or "弃用" in doc, \
            f"/health ({func_name}) 应有弃用标记: {doc[:100]}"
        assert "/m8/health" in doc or "/health" in doc, "应提到替代路径"

    def test_system_health_emits_deprecation_warning(self):
        """用例12：/api/system/health 函数中发出弃用警告"""
        source = _read_source(_SYSTEM_PY)

        func_name, func_body = _find_route_handler(source, "/health", "get")
        assert func_name, "应找到 /health 路由处理函数"
        assert func_body, f"应找到 {func_name} 函数体"

        assert "warnings.warn" in func_body or "logger.warning" in func_body, \
            "health 端点应发出弃用警告"
        assert "DEPRECATED" in func_body or "DeprecationWarning" in func_body, \
            "health 端点应标记为 DEPRECATED"

    def test_system_health_response_has_deprecated_flag(self):
        """用例13：system_health 响应中包含 _deprecated 标记"""
        source = _read_source(_SYSTEM_PY)

        assert "_deprecated" in source, "响应中应包含 _deprecated 字段"
        assert "_replacement" in source, "响应中应包含 _replacement 字段"

    def test_system_notices_has_deprecated_docstring(self):
        """用例14：/api/system/notices 端点有弃用文档标记"""
        source = _read_source(_SYSTEM_PY)

        func_name, func_body = _find_route_handler(source, "/notices", "get")
        assert func_name, f"应找到 /notices 路由处理函数, 实际: {func_name}"

        doc = _get_function_docstring(func_body)
        assert doc, f"{func_name} 应有 docstring"
        assert "Deprecated" in doc or "弃用" in doc, \
            f"/notices ({func_name}) 应有弃用标记: {doc[:100]}"

    def test_system_modules_list_has_deprecated_docstring(self):
        """用例15：/api/system/modules 列表端点有弃用文档标记"""
        source = _read_source(_SYSTEM_PY)

        func_name, func_body = _find_route_handler(source, "/modules", "get")
        assert func_name, f"应找到 /modules 路由处理函数, 实际: {func_name}"

        doc = _get_function_docstring(func_body)
        assert doc, f"{func_name} 应有 docstring"
        assert "Deprecated" in doc or "弃用" in doc, \
            f"/modules ({func_name}) 应有弃用标记: {doc[:100]}"

    def test_system_notices_emits_deprecation_warning(self):
        """用例16：/notices 端点发出弃用警告"""
        source = _read_source(_SYSTEM_PY)

        func_name, func_body = _find_route_handler(source, "/notices", "get")
        assert func_name, "应找到 /notices 路由处理函数"

        has_warn = "warnings.warn" in func_body or "logger.warning" in func_body
        has_deprecated = "DEPRECATED" in func_body or "DeprecationWarning" in func_body or "deprecated" in func_body.lower()
        assert has_warn and has_deprecated, \
            f"/notices ({func_name}) 应发出弃用警告"


# ============================================================
# 测试用例 - health_service.py 标准路径端点
# ============================================================


class TestHealthServiceStandardEndpoints:
    """测试 health_service.py 中标准路径端点存在"""

    def test_m8_health_endpoint_exists(self):
        """用例17：/m8/health 标准端点存在"""
        source = _read_source(_HEALTH_SERVICE_PY)
        assert '"/m8/health"' in source or "`/m8/health`" in source
        assert "register_m8_std_endpoints" in source

    def test_m8_metrics_endpoint_exists(self):
        """用例18：/m8/metrics 标准端点存在"""
        source = _read_source(_HEALTH_SERVICE_PY)
        assert '"/m8/metrics"' in source or "`/m8/metrics`" in source

    def test_m8_config_endpoint_exists(self):
        """用例19：/m8/config 标准端点存在"""
        source = _read_source(_HEALTH_SERVICE_PY)
        assert '"/m8/config"' in source or "`/m8/config`" in source

    def test_public_health_endpoint_exists(self):
        """用例20：公开 /health 端点存在（向后兼容）"""
        source = _read_source(_HEALTH_SERVICE_PY)
        assert "register_public_health_endpoint" in source
        assert '"/health"' in source or "`/health`" in source


# ============================================================
# 测试用例 - ModuleClient 健康检查降级
# ============================================================


class TestModuleClientHealthFallback:
    """测试 ModuleClient 健康检查降级逻辑"""

    def test_module_client_health_check_docstring_mentions_m8(self):
        """用例21：ModuleClient.health_check 文档提到 /m8/health 标准路径"""
        from shared.business.module_client import ModuleClient

        assert ModuleClient.health_check.__doc__ is not None
        doc = ModuleClient.health_check.__doc__
        assert "/m8/health" in doc
        assert "降级" in doc or "fallback" in doc.lower()

    def test_module_client_has_health_check_method(self):
        """用例22：ModuleClient 具有 health_check 异步方法"""
        from shared.business.module_client import ModuleClient
        import inspect

        assert hasattr(ModuleClient, "health_check")
        assert inspect.iscoroutinefunction(ModuleClient.health_check)


# ============================================================
# 测试用例 - 弃用路由文档
# ============================================================


class TestDeprecatedRoutesDocumentation:
    """测试弃用路由文档完整性"""

    def test_deprecated_routes_doc_exists(self):
        """用例23：弃用路由文档文件存在"""
        assert _DEPRECATED_DOC.exists(), f"文档文件应存在: {_DEPRECATED_DOC}"

    def test_deprecated_routes_doc_has_sections(self):
        """用例24：弃用路由文档包含必要章节"""
        content = _DEPRECATED_DOC.read_text(encoding="utf-8")

        assert "已弃用路由列表" in content
        assert "迁移指南" in content
        assert "兼容时间表" in content
        assert "保留不清理" in content  # 章节名可能是"保留不清理的项及原因"
        assert "/m8/health" in content
        assert "/api/system/health" in content

    def test_deprecated_routes_doc_has_system_health(self):
        """用例25：文档包含 /api/system/health 弃用记录"""
        content = _DEPRECATED_DOC.read_text(encoding="utf-8")

        assert "/api/system/health" in content
        assert "弃用版本" in content
        assert "替代路径" in content
        assert "计划删除版本" in content

    def test_deprecated_routes_doc_has_migration_guide(self):
        """用例26：文档包含迁移指南详细步骤"""
        content = _DEPRECATED_DOC.read_text(encoding="utf-8")

        # 迁移指南应包含具体场景
        assert "模块间调用" in content or "模块开发" in content
        assert "监控系统" in content or "运维" in content


# ============================================================
# 主函数
# ============================================================

if __name__ == "__main__":
    pytest.main([__file__, "-v"])
