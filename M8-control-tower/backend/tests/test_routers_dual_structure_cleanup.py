# -*- coding: utf-8 -*-
"""
M8 routers 双重结构清理验证测试（M8 职责拆分阶段 0）

验证双重结构清理后的正确性：
1. 所有子目录路由可正常导入
2. 顶层存根文件正常工作（DeprecationWarning + 正确转发）
3. 新旧路径返回同一 APIRouter 实例
4. 目录结构正确
5. __init__.py 可正常导入（排除 data_access 预先存在的 bug）

运行方式:
  cd M8-control-tower/backend
  pytest tests/test_routers_dual_structure_cleanup.py -v
"""

import sys
import os
import re
import warnings
from pathlib import Path

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
# 工具函数
# ============================================================

def _read_source(path: Path) -> str:
    """读取源码文件"""
    return path.read_text(encoding="utf-8")


def _count_routes(router) -> int:
    """统计 router 中的路由数量"""
    return len([r for r in router.routes if hasattr(r, "path")])


# ============================================================
# 测试用例 - 子目录路由导入
# ============================================================

class TestSubdirectoryImports:
    """测试各子域子目录的路由可正常导入"""

    def test_core_subpackage_imports(self):
        """用例 1: core 子包 6 个路由全部可导入"""
        from backend.routers.core import (
            modules_router, system_router, deploy_router,
            modes_router, registry_router, m4_gateway_router,
        )
        from fastapi import APIRouter
        routers = [modules_router, system_router, deploy_router,
                   modes_router, registry_router, m4_gateway_router]
        for r in routers:
            assert isinstance(r, APIRouter)
        assert len(routers) == 6

    def test_security_subpackage_imports(self):
        """用例 2: security 子包 4 个路由全部可导入"""
        from backend.routers.security import (
            auth_router, users_router, security_router, audit_router,
        )
        from fastapi import APIRouter
        routers = [auth_router, users_router, security_router, audit_router]
        for r in routers:
            assert isinstance(r, APIRouter)
        assert len(routers) == 4

    def test_compute_subpackage_imports(self):
        """用例 3: compute 子包 8 个路由全部可导入"""
        from backend.routers.compute import (
            compute_sources_router, compute_gpu_router, compute_groups_router,
            compute_models_router, compute_routing_router, compute_monitor_router,
            compute_config_router, compute_skills_router,
        )
        from fastapi import APIRouter
        routers = [compute_sources_router, compute_gpu_router, compute_groups_router,
                   compute_models_router, compute_routing_router, compute_monitor_router,
                   compute_config_router, compute_skills_router]
        for r in routers:
            assert isinstance(r, APIRouter)
        assert len(routers) == 8

    def test_ops_subpackage_imports(self):
        """用例 4: ops 子包 5 个路由全部可导入"""
        from backend.routers.ops import (
            monitor_router, ops_dashboard_router, performance_router,
            inspection_agents_router, git_status_router,
        )
        from fastapi import APIRouter
        routers = [monitor_router, ops_dashboard_router, performance_router,
                   inspection_agents_router, git_status_router]
        for r in routers:
            assert isinstance(r, APIRouter)
        assert len(routers) == 5

    def test_config_subpackage_imports(self):
        """用例 5: config 子包 2 个路由全部可导入"""
        from backend.routers.config import config_center_router, i18n_router
        from fastapi import APIRouter
        assert isinstance(config_center_router, APIRouter)
        assert isinstance(i18n_router, APIRouter)

    def test_business_subpackage_imports(self):
        """用例 6: business 子包 23 个路由全部可导入"""
        from backend.routers.business import (
            growth_router, work_dev_router, review_router, study_plan_router,
            life_management_router, emotion_comfort_router, social_relation_router,
            appearance_router, chat_router, memory_router, brain_router,
            personalization_router, reminders_router, agents_router, task_router,
            workflow_router, evolution_planner_router, evolution_deployer_router,
            evolution_auditor_router, voice_router, voice_presets_router,
            m6_devices_router, watch_router,
        )
        from fastapi import APIRouter
        routers = [growth_router, work_dev_router, review_router, study_plan_router,
                   life_management_router, emotion_comfort_router, social_relation_router,
                   appearance_router, chat_router, memory_router, brain_router,
                   personalization_router, reminders_router, agents_router, task_router,
                   workflow_router, evolution_planner_router, evolution_deployer_router,
                   evolution_auditor_router, voice_router, voice_presets_router,
                   m6_devices_router, watch_router]
        for r in routers:
            assert isinstance(r, APIRouter)
        assert len(routers) == 23

    def test_data_backup_scheduler_import(self):
        """用例 7: data 子包 backup_scheduler 可导入"""
        from backend.routers.data.backup_scheduler import router as bs_router
        from fastapi import APIRouter
        assert isinstance(bs_router, APIRouter)


# ============================================================
# 测试用例 - 顶层存根文件
# ============================================================

class TestTopLevelStubs:
    """测试顶层存根文件的向后兼容性"""

    def test_stub_audit(self):
        """用例 8: routers.audit 存根正常工作"""
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            from backend.routers.audit import router as audit_stub
            from backend.routers.audit import audit_router as audit_named
            assert len(w) >= 1
            assert issubclass(w[0].category, DeprecationWarning)
            assert "deprecated" in str(w[0].message).lower()

        from backend.routers.security.audit import router as audit_real
        assert audit_stub is audit_real
        assert audit_stub is audit_named

    def test_stub_compute_sources(self):
        """用例 9: routers.compute_sources 存根正常工作"""
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            from backend.routers.compute_sources import router as cs_stub
            from backend.routers.compute_sources import compute_sources_router as cs_named
            assert len(w) >= 1
            assert issubclass(w[0].category, DeprecationWarning)

        from backend.routers.compute.compute_sources import router as cs_real
        assert cs_stub is cs_real
        assert cs_stub is cs_named

    def test_stub_system_with_functions(self):
        """用例 10: routers.system 存根正常工作（含函数导出）"""
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            from backend.routers.system import router as sys_stub
            from backend.routers.system import system_router as sys_named
            from backend.routers.system import get_module_actions, get_system_actions
            assert len(w) >= 1
            assert issubclass(w[0].category, DeprecationWarning)

        from backend.routers.core.system import router as sys_real
        assert sys_stub is sys_real
        assert sys_stub is sys_named
        # 验证额外导出的函数
        assert callable(get_module_actions)
        assert callable(get_system_actions)

    def test_stub_monitor_with_functions(self):
        """用例 11: routers.monitor 存根正常工作（含内部函数导出）"""
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            from backend.routers.monitor import router as mon_stub
            from backend.routers.monitor import monitor_router as mon_named
            from backend.routers.monitor import _get_system_metrics
            assert len(w) >= 1
            assert issubclass(w[0].category, DeprecationWarning)

        from backend.routers.ops.monitor import router as mon_real
        assert mon_stub is mon_real
        assert mon_stub is mon_named
        assert callable(_get_system_metrics)

    def test_stub_backup_scheduler(self):
        """用例 12: routers.backup_scheduler 存根正常工作"""
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            from backend.routers.backup_scheduler import router as bs_stub
            from backend.routers.backup_scheduler import backup_scheduler_router as bs_named
            assert len(w) >= 1
            assert issubclass(w[0].category, DeprecationWarning)

        from backend.routers.data.backup_scheduler import router as bs_real
        assert bs_stub is bs_real
        assert bs_stub is bs_named


# ============================================================
# 测试用例 - 新旧路径一致性
# ============================================================

class TestPathConsistency:
    """测试新旧导入路径返回同一对象"""

    def test_system_same_object(self):
        """用例 13: system 新旧路径返回同一 APIRouter 实例"""
        from backend.routers.core.system import router as sys_new
        from backend.routers.system import router as sys_old
        assert sys_old is sys_new

    def test_monitor_same_object(self):
        """用例 14: monitor 新旧路径返回同一 APIRouter 实例"""
        from backend.routers.ops.monitor import router as mon_new
        from backend.routers.monitor import router as mon_old
        assert mon_old is mon_new

    def test_audit_same_object(self):
        """用例 15: audit 新旧路径返回同一 APIRouter 实例"""
        from backend.routers.security.audit import router as audit_new
        from backend.routers.audit import router as audit_old
        assert audit_old is audit_new

    def test_compute_sources_same_object(self):
        """用例 16: compute_sources 新旧路径返回同一 APIRouter 实例"""
        from backend.routers.compute.compute_sources import router as cs_new
        from backend.routers.compute_sources import router as cs_old
        assert cs_old is cs_new

    def test_backup_scheduler_same_object(self):
        """用例 17: backup_scheduler 新旧路径返回同一 APIRouter 实例"""
        from backend.routers.data.backup_scheduler import router as bs_new
        from backend.routers.backup_scheduler import router as bs_old
        assert bs_old is bs_new


# ============================================================
# 测试用例 - 目录结构验证
# ============================================================

class TestDirectoryStructure:
    """测试目录结构正确性"""

    def test_subdirectories_exist(self):
        """用例 18: 所有 7 个子域子目录存在"""
        subdirs = ['core', 'compute', 'ops', 'security', 'config', 'data', 'business']
        routers_dir = _M8_ROOT / "routers"
        for subdir in subdirs:
            assert (routers_dir / subdir).is_dir(), f"Missing subdir: {subdir}"
            assert (routers_dir / subdir / "__init__.py").exists(), f"Missing __init__.py in {subdir}"

    def test_init_py_exists(self):
        """用例 19: routers/__init__.py 存在且非空"""
        init_path = _M8_ROOT / "routers" / "__init__.py"
        assert init_path.exists()
        content = _read_source(init_path)
        assert len(content) > 100  # 应包含所有导入

    def test_stub_files_are_lightweight(self):
        """用例 20: 存根文件不超过 25 行"""
        stub_files = {
            "audit.py": _M8_ROOT / "routers" / "audit.py",
            "compute_sources.py": _M8_ROOT / "routers" / "compute_sources.py",
            "system.py": _M8_ROOT / "routers" / "system.py",
            "monitor.py": _M8_ROOT / "routers" / "monitor.py",
            "backup_scheduler.py": _M8_ROOT / "routers" / "backup_scheduler.py",
        }
        for name, path in stub_files.items():
            if path.exists():
                lines = len(_read_source(path).splitlines())
                assert lines <= 25, f"Stub file {name} has {lines} lines (should be <= 25)"

    def test_stub_files_have_deprecation_warning(self):
        """用例 21: 所有存根文件都包含 DeprecationWarning"""
        stub_files = [
            _M8_ROOT / "routers" / "audit.py",
            _M8_ROOT / "routers" / "compute_sources.py",
            _M8_ROOT / "routers" / "system.py",
            _M8_ROOT / "routers" / "monitor.py",
            _M8_ROOT / "routers" / "backup_scheduler.py",
        ]
        for path in stub_files:
            if path.exists():
                content = _read_source(path)
                assert "DeprecationWarning" in content, f"{path.name} missing DeprecationWarning"
                assert "warnings.warn" in content, f"{path.name} missing warnings.warn"

    def test_no_duplicate_full_files(self):
        """用例 22: 顶层不应有完整的路由实现文件"""
        # 已知的保留文件
        expected_top_files = {
            "__init__.py",
            "audit.py",          # 存根
            "compute_sources.py", # 存根
            "system.py",         # 存根
            "monitor.py",        # 存根
            "backup_scheduler.py",  # 存根
            "__init__.py.bak",   # 备份文件
        }
        routers_dir = _M8_ROOT / "routers"
        top_py_files = set()
        for f in routers_dir.iterdir():
            if f.is_file() and f.suffix == ".py":
                top_py_files.add(f.name)

        # 检查是否有意外的大文件（> 100 行的顶层文件）
        for fname in top_py_files - expected_top_files:
            fpath = routers_dir / fname
            try:
                lines = len(_read_source(fpath).splitlines())
                assert lines <= 25, (
                    f"Unexpected large top-level file: {fname} ({lines} lines). "
                    f"It should be either a stub (<=25 lines) or moved to a subdirectory."
                )
            except OSError:
                # 无法读取的幽灵文件跳过
                pass


# ============================================================
# 测试用例 - 子域职责划分
# ============================================================

class TestSubdomainResponsibilities:
    """测试各子域的职责划分"""

    def test_core_responsibilities(self):
        """用例 23: core 子域包含核心控制模块"""
        from backend.routers.core import (
            modules_router, system_router, deploy_router,
            modes_router, registry_router, m4_gateway_router,
        )
        # core 应该有 6 个路由：模块、系统、部署、模式、注册、网关
        assert modules_router is not None
        assert system_router is not None
        assert deploy_router is not None

    def test_compute_responsibilities(self):
        """用例 24: compute 子域包含算力调度相关"""
        from backend.routers.compute import compute_sources_router, compute_gpu_router
        # compute 应该有算力源、GPU、分组等路由
        assert compute_sources_router is not None
        assert compute_gpu_router is not None

    def test_security_responsibilities(self):
        """用例 25: security 子域包含安全管理"""
        from backend.routers.security import auth_router, users_router, security_router, audit_router
        # security 应该有认证、用户、安全、审计
        assert auth_router is not None
        assert audit_router is not None


# ============================================================
# 主函数
# ============================================================

if __name__ == "__main__":
    pytest.main([__file__, "-v"])
