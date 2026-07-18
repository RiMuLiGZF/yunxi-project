#!/usr/bin/env python3
"""
云汐系统版本号一致性检查脚本

功能：
- 扫描所有模块目录的版本号
- 检查 __version__、config 配置、README 中的版本
- 与系统版本（shared.core.version.SYSTEM_VERSION）对比
- 输出不一致的报告
- 支持 --fix 参数自动修复简单的不一致

用法：
    python scripts/version_check.py
    python scripts/version_check.py --fix
    python scripts/version_check.py --module M2
"""

from __future__ import annotations

import argparse
import os
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional, Tuple

# ============================================================
# 路径配置
# ============================================================

SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent

# 将项目根目录加入 path，以便导入 shared
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


# ============================================================
# 数据结构
# ============================================================

@dataclass
class VersionMismatch:
    """版本不一致条目"""
    module: str
    location: str
    current_version: str
    expected_version: str
    fixable: bool = False

    def __str__(self) -> str:
        fixable_mark = " [可自动修复]" if self.fixable else ""
        return (
            f"  模块: {self.module}\n"
            f"  位置: {self.location}\n"
            f"  当前: {self.current_version}\n"
            f"  期望: {self.expected_version}{fixable_mark}"
        )


@dataclass
class ScanResult:
    """扫描结果"""
    total_checked: int = 0
    mismatches: List[VersionMismatch] = field(default_factory=list)
    fixed_count: int = 0

    @property
    def is_consistent(self) -> bool:
        return len(self.mismatches) == 0


# ============================================================
# 系统版本获取
# ============================================================

def get_system_version() -> str:
    """
    获取系统版本号（期望版本）

    优先从 shared.core.version 读取，
    失败则从 VERSION 根文件读取，
    最终回退到硬编码默认值。

    Returns:
        语义化版本号字符串（不带 v 前缀），如 "1.2.0"
    """
    # 1. 从 shared.core.version 读取
    try:
        from shared.core.version import SYSTEM_VERSION
        ver = SYSTEM_VERSION.lstrip("vV")
        return ver
    except Exception:
        pass

    # 2. 从 VERSION 根文件读取
    version_file = PROJECT_ROOT / "VERSION"
    if version_file.exists():
        try:
            content = version_file.read_text(encoding="utf-8")
            for line in content.splitlines():
                line = line.strip()
                if line.startswith("VERSION="):
                    return line.split("=", 1)[1].strip()
                if line.startswith("VERSION_TAG="):
                    tag = line.split("=", 1)[1].strip()
                    return tag.lstrip("vV")
        except Exception:
            pass

    # 3. 回退默认值
    return "1.2.0"


def normalize_version(version: str) -> str:
    """
    标准化版本号格式

    - 去除前后空白
    - 去除 v/V 前缀
    - 保留语义化版本号

    Args:
        version: 原始版本号

    Returns:
        标准化后的版本号
    """
    if not version:
        return ""
    ver = version.strip().lstrip("vV")
    return ver


# ============================================================
# 版本提取工具
# ============================================================

VERSION_PATTERNS = [
    # Python 模块 __version__ = "x.y.z"
    (re.compile(r'^__version__\s*=\s*[\'"]([^\'"]+)[\'"]', re.MULTILINE), "py_version"),
    # FastAPI version="x.y.z"
    (re.compile(r'version\s*=\s*[\'"]([^\'"]+)[\'"]', re.MULTILINE), "fastapi_version"),
    # Pydantic config version: str = "x.y.z"
    (re.compile(r'^\s+version\s*:\s*str\s*=\s*[\'"]([^\'"]+)[\'"]', re.MULTILINE), "config_version"),
    # version = "x.y.z"（赋值形式）
    (re.compile(r'^version\s*=\s*[\'"]([^\'"]+)[\'"]', re.MULTILINE), "simple_version"),
    # APP_VERSION = "x.y.z"
    (re.compile(r'APP_VERSION\s*=\s*[\'"]([^\'"]+)[\'"]', re.MULTILINE), "app_version"),
]

README_VERSION_PATTERN = re.compile(
    r'\*\*版本\*\*[：:]\s*v?([\d]+\.[\d]+\.[\d]+)',
    re.MULTILINE
)


def extract_versions_from_file(file_path: Path) -> List[Tuple[str, str, int]]:
    """
    从文件中提取版本号

    Args:
        file_path: 文件路径

    Returns:
        列表，每个元素为 (版本号, 匹配类型, 行号)
    """
    results = []
    try:
        content = file_path.read_text(encoding="utf-8")
    except Exception:
        return results

    lines = content.splitlines()

    for pattern, ptype in VERSION_PATTERNS:
        for match in pattern.finditer(content):
            version = match.group(1)
            # 计算行号
            line_num = content[:match.start(1)].count("\n") + 1
            results.append((version, ptype, line_num))

    return results


def extract_readme_version(file_path: Path) -> Optional[Tuple[str, int]]:
    """
    从 README 中提取版本号

    Args:
        file_path: README 文件路径

    Returns:
        (版本号, 行号) 或 None
    """
    try:
        content = file_path.read_text(encoding="utf-8")
    except Exception:
        return None

    match = README_VERSION_PATTERN.search(content)
    if match:
        version = match.group(1)
        line_num = content[:match.start(1)].count("\n") + 1
        return (version, line_num)
    return None


# ============================================================
# 模块扫描配置
# ============================================================

# 模块定义：模块名 -> 扫描路径列表
MODULE_SCAN_PATHS = {
    "shared": [
        ("shared/__init__.py", "py"),
        ("shared/core/__init__.py", "py"),
        ("shared/core/version.py", "py"),
    ],
    "M0": [
        ("M0-principal-console/src/__init__.py", "py"),
    ],
    "M1": [
        ("M1-agent-hub/src/__init__.py", "py"),
    ],
    "M2": [
        ("M2-skills-cluster/skill_cluster/version.py", "py"),
    ],
    "M5": [
        ("M5-tide-memory/src/tide_memory/__init__.py", "py"),
        ("M5-tide-memory/src/tide_memory/core/version.py", "py"),
    ],
    "M6": [
        ("M6-hardware-peripheral/m6_hardware/__init__.py", "py"),
        ("M6-hardware-peripheral/server.py", "py"),
    ],
    "M7": [
        ("M7-workflow-builder/src/__init__.py", "py"),
    ],
    "M8": [
        ("M8-control-tower/backend/__init__.py", "py"),
        ("M8-control-tower/backend/config.py", "py"),
    ],
    "M9": [
        ("M9-dev-workshop/backend/main.py", "py"),
    ],
    "M10": [
        ("M10-system-guard/m10_system_guard/__init__.py", "py"),
        ("M10-system-guard/m10_system_guard/config.py", "py"),
        ("M10-system-guard/server.py", "py"),
    ],
    "M11": [
        ("M11-mcp-bus/src/__init__.py", "py"),
        ("M11-mcp-bus/src/main.py", "py"),
        ("M11-mcp-bus/src/routers/health.py", "py"),
        ("M11-mcp-bus/README.md", "readme"),
    ],
    "M12": [
        ("M12-security-shield/backend/__init__.py", "py"),
        ("M12-security-shield/backend/config.py", "py"),
    ],
    "API-Gateway": [
        ("API-Gateway/src/main.py", "py"),
    ],
}


# ============================================================
# 扫描核心逻辑
# ============================================================

def scan_module_versions(
    expected_version: str,
    filter_module: Optional[str] = None,
) -> ScanResult:
    """
    扫描所有模块的版本号

    Args:
        expected_version: 期望的版本号
        filter_module: 如果指定，只扫描该模块

    Returns:
        扫描结果
    """
    result = ScanResult()

    for module_name, scan_paths in MODULE_SCAN_PATHS.items():
        if filter_module and module_name != filter_module:
            continue

        for rel_path, scan_type in scan_paths:
            file_path = PROJECT_ROOT / rel_path
            if not file_path.exists():
                continue

            result.total_checked += 1

            if scan_type == "readme":
                readme_info = extract_readme_version(file_path)
                if readme_info:
                    current_ver, line_num = readme_info
                    norm_current = normalize_version(current_ver)
                    if norm_current != expected_version:
                        result.mismatches.append(VersionMismatch(
                            module=module_name,
                            location=f"{rel_path}:{line_num} (README版本)",
                            current_version=current_ver,
                            expected_version=f"v{expected_version}",
                            fixable=True,
                        ))
            else:  # py 文件
                versions = extract_versions_from_file(file_path)
                for current_ver, vtype, line_num in versions:
                    norm_current = normalize_version(current_ver)
                    # 跳过明显不是模块版本的版本号（如固件版本、内部版本等）
                    if _should_skip_version(vtype, file_path, line_num, current_ver):
                        continue
                    if norm_current != expected_version:
                        result.mismatches.append(VersionMismatch(
                            module=module_name,
                            location=f"{rel_path}:{line_num} ({vtype})",
                            current_version=current_ver,
                            expected_version=expected_version,
                            fixable=_is_fixable(vtype),
                        ))

    # 检查 VERSION 根文件
    if not filter_module or filter_module == "ROOT":
        result.total_checked += 1
        version_file = PROJECT_ROOT / "VERSION"
        if version_file.exists():
            try:
                content = version_file.read_text(encoding="utf-8")
                # 检查 VERSION= 行
                ver_match = re.search(r'^VERSION=([\d.]+)', content, re.MULTILINE)
                if ver_match:
                    current = ver_match.group(1)
                    if current != expected_version:
                        result.mismatches.append(VersionMismatch(
                            module="ROOT",
                            location="VERSION (VERSION=)",
                            current_version=current,
                            expected_version=expected_version,
                            fixable=True,
                        ))
                # 检查 VERSION_TAG= 行
                tag_match = re.search(r'^VERSION_TAG=v([\d.]+)', content, re.MULTILINE)
                if tag_match:
                    current = tag_match.group(1)
                    if current != expected_version:
                        result.mismatches.append(VersionMismatch(
                            module="ROOT",
                            location="VERSION (VERSION_TAG=)",
                            current_version=f"v{current}",
                            expected_version=f"v{expected_version}",
                            fixable=True,
                        ))
            except Exception:
                pass

    return result


def _should_skip_version(vtype: str, file_path: Path, line_num: int, version: str) -> bool:
    """
    判断是否应该跳过某个版本号匹配（避免误报）

    跳过的情况：
    - 固件版本号（firmware_version）
    - 数据库迁移版本号
    - 乐观锁版本号
    - 模板项目的默认版本号（0.1.0）
    - API 版本号（v1, v2 等）
    """
    try:
        lines = file_path.read_text(encoding="utf-8").splitlines()
        if line_num <= len(lines):
            line = lines[line_num - 1]
            # 跳过固件版本
            if "firmware_version" in line.lower():
                return True
            # 跳过数据库版本/迁移版本
            if "db_version" in line.lower() or "schema_version" in line.lower():
                return True
            # 跳过乐观锁版本号（version = Column...）
            if "Column" in line and "version" in line.lower():
                return True
            # 跳过 API 版本（v1, v2 等）
            if re.search(r'/api/v\d+', line) or re.search(r'"v\d+"', line):
                return True
            # 跳过插件版本号（独立插件的版本）
            if "plugin" in line.lower() and "version" in line.lower():
                return True
            # 跳过模板代码中的版本（项目模板）
            if 'project_template' in str(file_path).lower() or '模板' in line:
                return True
            # 跳过格式版本号（如 Prometheus text/plain; version=0.0.4）
            if "text/plain" in line or "content_type" in line.lower():
                return True
    except Exception:
        pass

    return False


def _is_fixable(vtype: str) -> bool:
    """判断某种版本类型是否可自动修复"""
    fixable_types = {"py_version", "fastapi_version", "config_version", "simple_version", "app_version"}
    return vtype in fixable_types


# ============================================================
# 自动修复
# ============================================================

def fix_mismatches(mismatches: List[VersionMismatch], expected_version: str) -> int:
    """
    自动修复可修复的版本不一致

    Args:
        mismatches: 不一致列表
        expected_version: 期望的版本号

    Returns:
        修复的数量
    """
    fixed = 0

    for mismatch in mismatches:
        if not mismatch.fixable:
            continue

        file_path = PROJECT_ROOT / mismatch.location.split(":")[0]
        if not file_path.exists():
            continue

        try:
            content = file_path.read_text(encoding="utf-8")
            new_content = content

            if mismatch.location.endswith("(README版本)"):
                # README 修复：**版本**：vx.y.z
                new_content = README_VERSION_PATTERN.sub(
                    f"**版本**：v{expected_version}",
                    content,
                    count=1,
                )
            else:
                # Python 文件修复
                # 根据类型选择修复策略
                current_norm = normalize_version(mismatch.current_version)

                # __version__ = "x.y.z"
                if "(py_version)" in mismatch.location:
                    new_content = re.sub(
                        r'^__version__\s*=\s*[\'"]' + re.escape(mismatch.current_version) + r'[\'"]',
                        f'__version__ = "{expected_version}"',
                        content,
                        count=1,
                        flags=re.MULTILINE,
                    )
                # FastAPI version=
                elif "(fastapi_version)" in mismatch.location:
                    new_content = re.sub(
                        r'version\s*=\s*[\'"]' + re.escape(mismatch.current_version) + r'[\'"]',
                        f'version="{expected_version}"',
                        content,
                        count=1,
                    )
                # config version: str =
                elif "(config_version)" in mismatch.location:
                    new_content = re.sub(
                        r'(\n\s+version\s*:\s*str\s*=\s*[\'"])' + re.escape(mismatch.current_version) + r'([\'"])',
                        rf'\1{expected_version}\2',
                        content,
                        count=1,
                    )
                # APP_VERSION =
                elif "(app_version)" in mismatch.location:
                    new_content = re.sub(
                        r'APP_VERSION\s*=\s*[\'"]' + re.escape(mismatch.current_version) + r'[\'"]',
                        f'APP_VERSION = "{expected_version}"',
                        content,
                        count=1,
                    )

            if new_content != content:
                file_path.write_text(new_content, encoding="utf-8")
                fixed += 1
                print(f"  [已修复] {mismatch.module} - {mismatch.location}")
        except Exception as e:
            print(f"  [修复失败] {mismatch.module} - {mismatch.location}: {e}")

    return fixed


# ============================================================
# 输出报告
# ============================================================

def print_report(result: ScanResult, expected_version: str) -> None:
    """
    打印扫描报告

    Args:
        result: 扫描结果
        expected_version: 期望版本号
    """
    print("=" * 70)
    print("云汐系统版本号一致性检查报告")
    print("=" * 70)
    print(f"期望版本: {expected_version}")
    print(f"检查项数: {result.total_checked}")
    print(f"不一致数: {len(result.mismatches)}")
    print()

    if result.is_consistent:
        print("✅ 所有模块版本号一致！")
    else:
        print("❌ 发现版本不一致：")
        print("-" * 70)
        for i, mismatch in enumerate(result.mismatches, 1):
            print(f"\n[{i}]")
            print(str(mismatch))

    print()
    print("=" * 70)


# ============================================================
# 主入口
# ============================================================

def main() -> int:
    """主函数"""
    parser = argparse.ArgumentParser(
        description="云汐系统版本号一致性检查工具",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例：
  python scripts/version_check.py          # 检查所有模块
  python scripts/version_check.py --fix    # 检查并自动修复
  python scripts/version_check.py -m M11   # 只检查 M11 模块
        """,
    )
    parser.add_argument(
        "--fix",
        action="store_true",
        help="自动修复可修复的版本不一致",
    )
    parser.add_argument(
        "-m", "--module",
        type=str,
        default=None,
        help="只检查指定模块（如 M2、M11、shared 等）",
    )
    parser.add_argument(
        "-q", "--quiet",
        action="store_true",
        help="静默模式，只输出最终结果",
    )

    args = parser.parse_args()

    # 获取期望版本
    expected_version = get_system_version()

    if not args.quiet:
        print(f"系统版本（期望）: {expected_version}")
        print()

    # 执行扫描
    result = scan_module_versions(expected_version, filter_module=args.module)

    # 自动修复
    if args.fix and result.mismatches:
        print("执行自动修复...")
        fixable = [m for m in result.mismatches if m.fixable]
        if fixable:
            fixed = fix_mismatches(fixable, expected_version)
            result.fixed_count = fixed
            print(f"\n修复完成: {fixed}/{len(fixable)} 项已修复")
            print()
            # 修复后重新扫描确认
            if not args.quiet:
                print("重新扫描验证...")
                result = scan_module_versions(expected_version, filter_module=args.module)
        else:
            print("没有可自动修复的项")

    # 输出报告
    if not args.quiet:
        print_report(result, expected_version)
    else:
        if result.is_consistent:
            print(f"OK - 所有版本一致 (v{expected_version})")
        else:
            print(f"FAIL - {len(result.mismatches)} 处不一致")

    # 返回退出码
    return 0 if result.is_consistent else 1


if __name__ == "__main__":
    sys.exit(main())
