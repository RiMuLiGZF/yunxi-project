"""
版本一致性测试

测试云汐系统所有模块的版本号是否与系统版本保持一致。
测试版本检查脚本的基本功能。

测试项：
1. shared 版本号正确
2. SYSTEM_VERSION 格式正确（语义化版本）
3. 版本检查脚本能正确运行
4. 至少 5 个核心模块的版本号
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path

import pytest


# ============================================================
# 路径配置
# ============================================================

TEST_DIR = Path(__file__).resolve().parent
SHARED_DIR = TEST_DIR.parent
PROJECT_ROOT = SHARED_DIR.parent

# 将项目根目录加入 path，以便导入各模块
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


# ============================================================
# 工具函数
# ============================================================

SEMVER_PATTERN = re.compile(r'^\d+\.\d+\.\d+(-[a-zA-Z0-9.]+)?$')


def is_valid_semver(version: str) -> bool:
    """
    检查是否为有效的语义化版本号

    Args:
        version: 版本号字符串

    Returns:
        是否为有效语义化版本
    """
    return bool(SEMVER_PATTERN.match(version))


def get_system_version() -> str:
    """
    获取系统版本号（不带 v 前缀）

    Returns:
        语义化版本号
    """
    from shared.core.version import SYSTEM_VERSION
    return SYSTEM_VERSION.lstrip("vV")


def read_file_version(file_path: Path, pattern: re.Pattern) -> str | None:
    """
    从文件中读取版本号

    Args:
        file_path: 文件路径
        pattern: 匹配正则

    Returns:
        版本号或 None
    """
    if not file_path.exists():
        return None
    try:
        content = file_path.read_text(encoding="utf-8")
        match = pattern.search(content)
        if match:
            return match.group(1).lstrip("vV")
    except Exception:
        pass
    return None


# ============================================================
# 1. shared 版本号测试
# ============================================================

class TestSharedVersion:
    """shared 模块版本号测试"""

    def test_shared_init_version(self):
        """测试 shared/__init__.py 中的 __version__"""
        assert hasattr(__import__('shared'), '__version__')
        import shared
        assert shared.__version__ == "1.2.0"

    def test_shared_core_init_version(self):
        """测试 shared/core/__init__.py 中的 __version__"""
        from shared import core
        assert hasattr(core, '__version__')
        assert core.__version__ == "1.2.0"

    def test_system_version_exists(self):
        """测试 SYSTEM_VERSION 存在且格式正确"""
        from shared.core.version import SYSTEM_VERSION
        assert SYSTEM_VERSION is not None
        assert len(SYSTEM_VERSION) > 0

    def test_build_date_exists(self):
        """测试 BUILD_DATE 存在"""
        from shared.core.version import BUILD_DATE
        assert BUILD_DATE is not None
        # 格式应为 YYYY-MM-DD
        assert re.match(r'^\d{4}-\d{2}-\d{2}$', BUILD_DATE)

    def test_version_code_is_integer(self):
        """测试 VERSION_CODE 是整数"""
        from shared.core.version import VERSION_CODE
        assert isinstance(VERSION_CODE, int)
        assert VERSION_CODE > 0


# ============================================================
# 2. SYSTEM_VERSION 格式测试
# ============================================================

class TestSystemVersionFormat:
    """系统版本号格式测试"""

    def test_system_version_is_semver(self):
        """测试 SYSTEM_VERSION 是有效的语义化版本"""
        version = get_system_version()
        assert is_valid_semver(version), (
            f"SYSTEM_VERSION '{version}' 不是有效的语义化版本号"
        )

    def test_system_version_major_minor_patch(self):
        """测试 SYSTEM_VERSION 包含 major.minor.patch 三段"""
        version = get_system_version()
        parts = version.split('.')
        assert len(parts) >= 3, f"版本号应有至少三段，实际: {version}"
        # 每段都是数字
        for i, part in enumerate(parts[:3]):
            assert part.isdigit(), f"版本号第 {i+1} 段不是数字: {part}"

    def test_version_matches_1_2_0(self):
        """测试系统版本号为 1.2.0"""
        version = get_system_version()
        assert version == "1.2.0", f"期望版本 1.2.0，实际 {version}"

    def test_version_code_matches(self):
        """测试 VERSION_CODE 与版本号对应"""
        from shared.core.version import VERSION_CODE
        version = get_system_version()
        major, minor, patch = version.split('.')[:3]
        expected_code = int(major) * 100 + int(minor) * 10 + int(patch)
        # VERSION_CODE 为 120（v1.2.0）
        assert VERSION_CODE == expected_code, (
            f"VERSION_CODE {VERSION_CODE} 与版本 {version} 不匹配 "
            f"（期望 {expected_code}）"
        )


# ============================================================
# 3. 版本检查脚本测试
# ============================================================

class TestVersionCheckScript:
    """版本检查脚本功能测试"""

    SCRIPT_PATH = PROJECT_ROOT / "scripts" / "version_check.py"

    def test_script_exists(self):
        """测试版本检查脚本存在"""
        assert self.SCRIPT_PATH.exists(), (
            f"版本检查脚本不存在: {self.SCRIPT_PATH}"
        )

    def test_script_runs_successfully(self):
        """测试版本检查脚本能正常运行"""
        result = subprocess.run(
            [sys.executable, str(self.SCRIPT_PATH), "-q"],
            capture_output=True,
            text=True,
            cwd=str(PROJECT_ROOT),
            timeout=30,
        )
        # 脚本应能正常运行（退出码 0 或 1 都算运行成功）
        assert result.returncode in (0, 1), (
            f"脚本运行失败，退出码: {result.returncode}\n"
            f"stderr: {result.stderr}"
        )

    def test_script_reports_consistency(self):
        """测试脚本报告版本一致性（当前应为全部一致）"""
        result = subprocess.run(
            [sys.executable, str(self.SCRIPT_PATH), "-q"],
            capture_output=True,
            text=True,
            cwd=str(PROJECT_ROOT),
            timeout=30,
        )
        # 当前所有版本应一致，退出码应为 0
        assert result.returncode == 0, (
            f"版本不一致！退出码: {result.returncode}\n"
            f"stdout: {result.stdout}\n"
            f"stderr: {result.stderr[:500]}"
        )
        assert "OK" in result.stdout

    def test_script_module_filter(self):
        """测试 --module 参数能过滤模块"""
        result = subprocess.run(
            [sys.executable, str(self.SCRIPT_PATH), "-q", "-m", "M11"],
            capture_output=True,
            text=True,
            cwd=str(PROJECT_ROOT),
            timeout=30,
        )
        assert result.returncode == 0, (
            f"M11 模块版本检查失败: {result.stdout}"
        )

    def test_script_help(self):
        """测试 --help 参数"""
        result = subprocess.run(
            [sys.executable, str(self.SCRIPT_PATH), "--help"],
            capture_output=True,
            text=True,
            cwd=str(PROJECT_ROOT),
            timeout=10,
        )
        assert result.returncode == 0
        assert "version" in result.stdout.lower()
        assert "--fix" in result.stdout

    def test_script_full_report(self):
        """测试完整报告输出包含关键信息"""
        result = subprocess.run(
            [sys.executable, str(self.SCRIPT_PATH)],
            capture_output=True,
            text=True,
            cwd=str(PROJECT_ROOT),
            timeout=30,
        )
        output = result.stdout
        assert "云汐系统版本号一致性检查报告" in output
        assert "期望版本" in output
        assert "检查项数" in output
        assert "不一致数" in output


# ============================================================
# 4. 核心模块版本号测试（至少 5 个）
# ============================================================

class TestCoreModuleVersions:
    """核心模块版本号一致性测试"""

    EXPECTED_VERSION = "1.2.0"

    # 模块名 -> (文件路径, 版本号提取正则)
    MODULE_VERSION_SOURCES = {
        "M2-skill-cluster": (
            PROJECT_ROOT / "M2-skills-cluster" / "skill_cluster" / "version.py",
            re.compile(r'^__version__\s*=\s*[\'"]([^\'"]+)[\'"]', re.MULTILINE),
        ),
        "M5-tide-memory": (
            PROJECT_ROOT / "M5-tide-memory" / "src" / "tide_memory" / "__init__.py",
            re.compile(r'^__version__\s*=\s*_load_version\(\)', re.MULTILINE),
        ),
        "M6-hardware": (
            PROJECT_ROOT / "M6-hardware-peripheral" / "m6_hardware" / "__init__.py",
            re.compile(r'^__version__\s*=\s*[\'"]([^\'"]+)[\'"]', re.MULTILINE),
        ),
        "M7-workflow-builder": (
            PROJECT_ROOT / "M7-workflow-builder" / "src" / "__init__.py",
            re.compile(r'^__version__\s*=\s*[\'"]([^\'"]+)[\'"]', re.MULTILINE),
        ),
        "M8-control-tower": (
            PROJECT_ROOT / "M8-control-tower" / "backend" / "__init__.py",
            re.compile(r'^__version__\s*=\s*[\'"]([^\'"]+)[\'"]', re.MULTILINE),
        ),
        "M9-dev-workshop": (
            PROJECT_ROOT / "M9-dev-workshop" / "backend" / "main.py",
            re.compile(r'APP_VERSION\s*=\s*[\'"]([^\'"]+)[\'"]', re.MULTILINE),
        ),
        "M10-system-guard": (
            PROJECT_ROOT / "M10-system-guard" / "m10_system_guard" / "__init__.py",
            re.compile(r'^__version__\s*=\s*[\'"]([^\'"]+)[\'"]', re.MULTILINE),
        ),
        "M11-mcp-bus": (
            PROJECT_ROOT / "M11-mcp-bus" / "src" / "__init__.py",
            re.compile(r'^__version__\s*=\s*[\'"]([^\'"]+)[\'"]', re.MULTILINE),
        ),
        "M12-security-shield": (
            PROJECT_ROOT / "M12-security-shield" / "backend" / "__init__.py",
            re.compile(r'^__version__\s*=\s*[\'"]([^\'"]+)[\'"]', re.MULTILINE),
        ),
        "M0-principal-console": (
            PROJECT_ROOT / "M0-principal-console" / "src" / "__init__.py",
            re.compile(r'^__version__\s*=\s*[\'"]([^\'"]+)[\'"]', re.MULTILINE),
        ),
    }

    @pytest.mark.parametrize("module_name", [
        "M2-skill-cluster",
        "M6-hardware",
        "M7-workflow-builder",
        "M8-control-tower",
        "M11-mcp-bus",
        "M12-security-shield",
    ])
    def test_module_version_matches(self, module_name: str):
        """测试指定模块的版本号与系统版本一致"""
        file_path, pattern = self.MODULE_VERSION_SOURCES[module_name]
        assert file_path.exists(), f"模块文件不存在: {file_path}"

        version = read_file_version(file_path, pattern)
        assert version is not None, (
            f"无法从 {file_path} 提取版本号"
        )
        assert version == self.EXPECTED_VERSION, (
            f"模块 {module_name} 版本不一致: "
            f"期望 {self.EXPECTED_VERSION}，实际 {version}"
        )

    def test_m5_version_via_import(self):
        """测试 M5 潮汐记忆的版本号（通过动态加载）"""
        # M5 的 __version__ 是通过 _load_version() 动态加载的
        # 优先从 shared.version 读取，所以最终结果应为系统版本
        try:
            # 尝试直接导入
            m5_path = PROJECT_ROOT / "M5-tide-memory" / "src"
            if str(m5_path) not in sys.path:
                sys.path.insert(0, str(m5_path))
            import tide_memory
            version = tide_memory.__version__.lstrip("vV")
            assert version == self.EXPECTED_VERSION, (
                f"M5 版本不一致: 期望 {self.EXPECTED_VERSION}，实际 {version}"
            )
        except ImportError as e:
            pytest.skip(f"无法导入 tide_memory: {e}")

    def test_m9_app_version(self):
        """测试 M9 开发者工坊的 APP_VERSION"""
        file_path = PROJECT_ROOT / "M9-dev-workshop" / "backend" / "main.py"
        assert file_path.exists()

        pattern = re.compile(r'APP_VERSION\s*=\s*[\'"]([^\'"]+)[\'"]', re.MULTILINE)
        version = read_file_version(file_path, pattern)
        assert version is not None, "无法从 M9 main.py 提取 APP_VERSION"
        assert version == self.EXPECTED_VERSION, (
            f"M9 APP_VERSION 不一致: 期望 {self.EXPECTED_VERSION}，实际 {version}"
        )

    def test_m10_config_version(self):
        """测试 M10 系统卫士配置中的版本号"""
        file_path = PROJECT_ROOT / "M10-system-guard" / "m10_system_guard" / "config.py"
        assert file_path.exists()

        pattern = re.compile(
            r'^\s+version\s*:\s*str\s*=\s*[\'"]([^\'"]+)[\'"]',
            re.MULTILINE,
        )
        version = read_file_version(file_path, pattern)
        assert version is not None, "无法从 M10 config.py 提取版本号"
        assert version == self.EXPECTED_VERSION, (
            f"M10 配置版本不一致: 期望 {self.EXPECTED_VERSION}，实际 {version}"
        )

    def test_m12_config_version(self):
        """测试 M12 安全盾配置中的版本号"""
        file_path = PROJECT_ROOT / "M12-security-shield" / "backend" / "config.py"
        assert file_path.exists()

        pattern = re.compile(
            r'^\s+version\s*:\s*str\s*=\s*[\'"]([^\'"]+)[\'"]',
            re.MULTILINE,
        )
        version = read_file_version(file_path, pattern)
        assert version is not None, "无法从 M12 config.py 提取版本号"
        assert version == self.EXPECTED_VERSION, (
            f"M12 配置版本不一致: 期望 {self.EXPECTED_VERSION}，实际 {version}"
        )

    def test_version_root_file(self):
        """测试 VERSION 根文件版本号"""
        version_file = PROJECT_ROOT / "VERSION"
        assert version_file.exists(), "VERSION 根文件不存在"

        content = version_file.read_text(encoding="utf-8")

        # 检查 VERSION= 行
        ver_match = re.search(r'^VERSION=([\d.]+)', content, re.MULTILINE)
        assert ver_match, "VERSION 文件中未找到 VERSION= 行"
        assert ver_match.group(1) == self.EXPECTED_VERSION, (
            f"VERSION 文件 VERSION= 不一致: 期望 {self.EXPECTED_VERSION}，实际 {ver_match.group(1)}"
        )

        # 检查 VERSION_TAG= 行
        tag_match = re.search(r'^VERSION_TAG=v([\d.]+)', content, re.MULTILINE)
        assert tag_match, "VERSION 文件中未找到 VERSION_TAG= 行"
        assert tag_match.group(1) == self.EXPECTED_VERSION, (
            f"VERSION 文件 VERSION_TAG= 不一致: 期望 v{self.EXPECTED_VERSION}，实际 v{tag_match.group(1)}"
        )


# ============================================================
# 5. 向后兼容性测试
# ============================================================

class TestBackwardCompatibility:
    """版本号向后兼容性测试"""

    def test_m2_version_info_deprecated_alias(self):
        """测试 M2 的 __version_info__ 弃用别名仍可用"""
        try:
            m2_path = PROJECT_ROOT / "M2-skills-cluster"
            if str(m2_path) not in sys.path:
                sys.path.insert(0, str(m2_path))

            import importlib
            import warnings

            # 清除缓存确保重新加载
            if 'skill_cluster.version' in sys.modules:
                del sys.modules['skill_cluster.version']
            if 'skill_cluster' in sys.modules:
                del sys.modules['skill_cluster']

            from skill_cluster import version as m2_version

            # 测试 INTERNAL_VERSION_INFO 存在
            assert hasattr(m2_version, 'INTERNAL_VERSION_INFO')
            assert isinstance(m2_version.INTERNAL_VERSION_INFO, tuple)
            assert len(m2_version.INTERNAL_VERSION_INFO) == 3

            # 测试 __version_info__ 别名可用（有弃用警告）
            with warnings.catch_warnings(record=True) as w:
                warnings.simplefilter("always")
                version_info = m2_version.__version_info__
                assert isinstance(version_info, tuple)
                assert len(version_info) == 3
                # 应触发弃用警告
                deprecation_warnings = [
                    x for x in w if issubclass(x.category, DeprecationWarning)
                ]
                assert len(deprecation_warnings) > 0, (
                    "访问 __version_info__ 应触发 DeprecationWarning"
                )

            # 两者值应相同
            assert m2_version.INTERNAL_VERSION_INFO == version_info, (
                "INTERNAL_VERSION_INFO 与 __version_info__ 值应相同"
            )

        except ImportError as e:
            pytest.skip(f"无法导入 skill_cluster.version: {e}")

    def test_shared_version_deprecated_module(self):
        """测试 shared.version 弃用模块仍可用（向后兼容）"""
        import warnings

        # 清除已缓存的模块，确保重新导入触发警告
        modules_to_remove = [k for k in sys.modules if k == 'shared.version']
        for mod in modules_to_remove:
            del sys.modules[mod]

        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            from shared.version import SYSTEM_VERSION as sv_from_deprecated
            assert sv_from_deprecated is not None
            # 应触发弃用警告
            deprecation_warnings = [
                x for x in w
                if issubclass(x.category, DeprecationWarning)
                and 'shared.version' in str(x.message)
            ]
            assert len(deprecation_warnings) > 0, (
                "从 shared.version 导入应触发 DeprecationWarning，"
                f"实际警告: {[str(x.message) for x in w]}"
            )

        # 与新路径的值一致
        from shared.core.version import SYSTEM_VERSION as sv_from_core
        assert sv_from_deprecated == sv_from_core
