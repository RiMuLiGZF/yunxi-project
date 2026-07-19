"""
Orchestrator 版本收敛测试

验证版本收敛后的行为：
1. v8 和 v9 可以正常导入（保留版本）
2. v2/v3/v4/v5/v7 仍可通过旧路径导入，但会触发 DeprecationWarning
3. v2/v3/v4/v5/v7 从 _deprecated/ 直接导入不触发警告（内部使用）
4. bootstrap 默认构建 v9
5. 版本选择机制（环境变量）正常工作
"""

from __future__ import annotations

import importlib
import sys
import warnings

import pytest


# 项目中已有的弃用警告（与 orchestrator 版本收敛无关），需要过滤
_KNOWN_DEPRECATIONS = {
    "shared_models 已迁移",  # shared_models -> models/ 迁移警告
}


def _is_orchestrator_deprecation(warning: warnings.WarningMessage) -> bool:
    """判断是否是 orchestrator 版本收敛相关的弃用警告"""
    if not issubclass(warning.category, DeprecationWarning):
        return False
    msg = str(warning.message)
    # 排除已知的其他弃用警告
    for known in _KNOWN_DEPRECATIONS:
        if known in msg:
            return False
    return True


class TestVersionRetention:
    """保留版本测试：v8 和 v9 应该可以正常导入且无 orchestrator 弃用警告"""

    def test_v9_import_without_orchestrator_deprecation(self) -> None:
        """v9 是保留版本，导入不应触发 orchestrator 相关的 DeprecationWarning"""
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            from src.orchestration.orchestrator_v9 import OrchestratorV9
            orch_deprecations = [x for x in w if _is_orchestrator_deprecation(x)]
            assert len(orch_deprecations) == 0, (
                f"v9 不应触发 orchestrator 弃用警告，但触发了 {len(orch_deprecations)} 个: "
                f"{[str(x.message) for x in orch_deprecations]}"
            )
            assert OrchestratorV9 is not None

    def test_v8_import_without_orchestrator_deprecation(self) -> None:
        """v8 是保留版本（稳定版），导入不应触发 orchestrator 相关的 DeprecationWarning"""
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            from src.orchestration.orchestrator_v8 import OrchestratorV8
            orch_deprecations = [x for x in w if _is_orchestrator_deprecation(x)]
            assert len(orch_deprecations) == 0, (
                f"v8 不应触发 orchestrator 弃用警告，但触发了 {len(orch_deprecations)} 个: "
                f"{[str(x.message) for x in orch_deprecations]}"
            )
            assert OrchestratorV8 is not None


def _reload_module_and_catch_warnings(module_name: str) -> list[warnings.WarningMessage]:
    """重新加载模块并捕获警告

    用于测试存根模块的 DeprecationWarning，因为模块可能已通过 _deprecated 路径被导入过，
    但存根本身（不同模块路径）应该是第一次加载。
    """
    # 如果模块已经加载过，先移除以便重新加载并捕获警告
    was_loaded = module_name in sys.modules
    if was_loaded:
        del sys.modules[module_name]

    try:
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            importlib.import_module(module_name)
            return w
    finally:
        # 不需要恢复，因为 importlib.import_module 会重新加载
        pass


class TestDeprecatedVersions:
    """废弃版本测试：v2/v3/v4/v5/v7 仍可导入但触发 DeprecationWarning"""

    def test_v2_import_triggers_deprecation_warning(self) -> None:
        """v2 已归档，从旧路径导入应触发 DeprecationWarning"""
        w = _reload_module_and_catch_warnings("src.orchestration.orchestrator_v2")
        orch_deprecations = [x for x in w if _is_orchestrator_deprecation(x)]
        assert len(orch_deprecations) >= 1, (
            f"v2 从旧路径导入应触发弃用警告，实际触发了 {len(orch_deprecations)} 个"
        )
        from src.orchestration.orchestrator_v2 import OrchestratorV2
        assert OrchestratorV2 is not None

    def test_v3_import_triggers_deprecation_warning(self) -> None:
        """v3 已归档，从旧路径导入应触发 DeprecationWarning"""
        w = _reload_module_and_catch_warnings("src.orchestration.orchestrator_v3")
        orch_deprecations = [x for x in w if _is_orchestrator_deprecation(x)]
        assert len(orch_deprecations) >= 1, (
            f"v3 从旧路径导入应触发弃用警告，实际触发了 {len(orch_deprecations)} 个"
        )
        from src.orchestration.orchestrator_v3 import OrchestratorV3
        assert OrchestratorV3 is not None

    def test_v4_import_triggers_deprecation_warning(self) -> None:
        """v4 已归档，从旧路径导入应触发 DeprecationWarning"""
        w = _reload_module_and_catch_warnings("src.orchestration.orchestrator_v4")
        orch_deprecations = [x for x in w if _is_orchestrator_deprecation(x)]
        assert len(orch_deprecations) >= 1, (
            f"v4 从旧路径导入应触发弃用警告，实际触发了 {len(orch_deprecations)} 个"
        )
        from src.orchestration.orchestrator_v4 import OrchestratorV4
        assert OrchestratorV4 is not None

    def test_v5_import_triggers_deprecation_warning(self) -> None:
        """v5 已归档，从旧路径导入应触发 DeprecationWarning"""
        w = _reload_module_and_catch_warnings("src.orchestration.orchestrator_v5")
        orch_deprecations = [x for x in w if _is_orchestrator_deprecation(x)]
        assert len(orch_deprecations) >= 1, (
            f"v5 从旧路径导入应触发弃用警告，实际触发了 {len(orch_deprecations)} 个"
        )
        from src.orchestration.orchestrator_v5 import OrchestratorV5
        assert OrchestratorV5 is not None

    def test_v7_import_triggers_deprecation_warning(self) -> None:
        """v7 已归档，从旧路径导入应触发 DeprecationWarning"""
        w = _reload_module_and_catch_warnings("src.orchestration.orchestrator_v7")
        orch_deprecations = [x for x in w if _is_orchestrator_deprecation(x)]
        assert len(orch_deprecations) >= 1, (
            f"v7 从旧路径导入应触发弃用警告，实际触发了 {len(orch_deprecations)} 个"
        )
        from src.orchestration.orchestrator_v7 import OrchestratorV7
        assert OrchestratorV7 is not None


class TestDeprecatedInternalImport:
    """内部导入测试：从 _deprecated/ 直接导入不应触发 orchestrator 弃用警告"""

    def test_v2_internal_import_no_orchestrator_deprecation(self) -> None:
        """从 _deprecated/ 直接导入 v2 不应触发 orchestrator 弃用警告（内部使用）"""
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            from src.orchestration._deprecated.orchestrator_v2 import OrchestratorV2
            orch_deprecations = [x for x in w if _is_orchestrator_deprecation(x)]
            assert len(orch_deprecations) == 0, (
                f"从 _deprecated/ 直接导入 v2 不应触发 orchestrator 弃用警告，"
                f"实际触发了 {len(orch_deprecations)} 个"
            )
            assert OrchestratorV2 is not None


class TestBootstrapVersionSelection:
    """bootstrap 版本选择测试"""

    def test_default_version_is_v9(self) -> None:
        """默认构建版本应为 v9"""
        from src.core.bootstrap import YunxiApplication
        app = YunxiApplication()
        version = app._resolve_version()
        assert version == "v9", f"默认版本应为 v9，实际为 {version}"

    def test_env_var_v8(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """设置环境变量 M1_ORCHESTRATOR_VERSION=v8 应返回 v8"""
        monkeypatch.setenv("M1_ORCHESTRATOR_VERSION", "v8")
        from src.core.bootstrap import YunxiApplication
        app = YunxiApplication()
        version = app._resolve_version()
        assert version == "v8", f"环境变量设置为 v8 时应返回 v8，实际为 {version}"

    def test_env_var_v9(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """设置环境变量 M1_ORCHESTRATOR_VERSION=v9 应返回 v9"""
        monkeypatch.setenv("M1_ORCHESTRATOR_VERSION", "v9")
        from src.core.bootstrap import YunxiApplication
        app = YunxiApplication()
        version = app._resolve_version()
        assert version == "v9", f"环境变量设置为 v9 时应返回 v9，实际为 {version}"

    def test_env_var_invalid_fallback_to_v9(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """设置无效环境变量应回退到 v9"""
        monkeypatch.setenv("M1_ORCHESTRATOR_VERSION", "v6")
        from src.core.bootstrap import YunxiApplication
        app = YunxiApplication()
        version = app._resolve_version()
        assert version == "v9", f"无效环境变量应回退到 v9，实际为 {version}"

    def test_config_version_v8(self) -> None:
        """配置文件中设置版本为 v8 时应返回 v8"""
        from src.core.bootstrap import YunxiApplication
        app = YunxiApplication()
        app.config.set("orchestration.version", "v8")
        version = app._resolve_version()
        assert version == "v8", f"配置文件设置为 v8 时应返回 v8，实际为 {version}"

    def test_env_var_overrides_config(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """环境变量优先级应高于配置文件"""
        monkeypatch.setenv("M1_ORCHESTRATOR_VERSION", "v9")
        from src.core.bootstrap import YunxiApplication
        app = YunxiApplication()
        app.config.set("orchestration.version", "v8")
        version = app._resolve_version()
        assert version == "v9", f"环境变量优先级应高于配置文件，实际为 {version}"


class TestBackwardCompatibility:
    """向后兼容性测试：旧 import 路径仍然可用"""

    def test_old_import_v2_class_is_same(self) -> None:
        """旧路径导入的 OrchestratorV2 应该和 _deprecated 中的是同一个类"""
        # 确保两个模块都已加载
        from src.orchestration.orchestrator_v2 import OrchestratorV2
        from src.orchestration._deprecated.orchestrator_v2 import OrchestratorV2 as DepV2
        # 应该是同一个类（存根 re-export）
        assert OrchestratorV2 is DepV2, (
            "旧路径导入的类应与 _deprecated 中的类是同一个对象"
        )

    def test_old_import_v7_class_is_same(self) -> None:
        """旧路径导入的 OrchestratorV7 应该和 _deprecated 中的是同一个类"""
        from src.orchestration.orchestrator_v7 import OrchestratorV7
        from src.orchestration._deprecated.orchestrator_v7 import OrchestratorV7 as DepV7
        assert OrchestratorV7 is DepV7, (
            "旧路径导入的类应与 _deprecated 中的类是同一个对象"
        )
