#!/usr/bin/env python3
"""
云汐系统 - 测试覆盖率运行脚本

提供多种覆盖率运行方式：
- 全量覆盖率
- 仅单元测试覆盖率
- 仅集成测试覆盖率
- 指定模块覆盖率

使用方法：
    python scripts/run_coverage.py              # 全量测试 + 覆盖率
    python scripts/run_coverage.py --unit       # 仅单元测试
    python scripts/run_coverage.py --integration # 仅集成测试
    python scripts/run_coverage.py --module m8  # 仅 M8 模块
    python scripts/run_coverage.py --html       # 生成 HTML 报告
    python scripts/run_coverage.py --xml        # 生成 XML 报告（CI 使用）
"""

import os
import sys
import subprocess
import argparse
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
REPORTS_DIR = PROJECT_ROOT / "tests" / "reports"


def run_pytest(args: list, with_coverage: bool = True) -> int:
    """运行 pytest 测试。

    Args:
        args: pytest 参数列表
        with_coverage: 是否启用覆盖率统计

    Returns:
        退出码
    """
    cmd = [sys.executable, "-m", "pytest"]

    if with_coverage:
        cmd = [
            sys.executable, "-m", "pytest",
            "--cov=shared/core",
            "--cov=shared/business",
            "--cov=M8-control-tower/backend",
            "--cov=M9-dev-workshop/backend",
            "--cov=M11-mcp-bus/src",
            "--cov-report=term-missing",
            "--cov-config=.coveragerc",
        ]

    cmd.extend(args)

    print(f"\n运行命令: {' '.join(cmd)}\n")
    print("=" * 70)

    result = subprocess.run(cmd, cwd=str(PROJECT_ROOT))
    return result.returncode


def generate_html_report() -> int:
    """生成 HTML 覆盖率报告。"""
    cmd = [
        sys.executable, "-m", "pytest",
        "--cov=shared/core",
        "--cov=shared/business",
        "--cov=M8-control-tower/backend",
        "--cov=M9-dev-workshop/backend",
        "--cov=M11-mcp-bus/src",
        "--cov-report=html",
        "--cov-report=term",
        "--cov-config=.coveragerc",
    ]

    print(f"\n生成 HTML 覆盖率报告...")
    print(f"运行命令: {' '.join(cmd)}\n")
    print("=" * 70)

    result = subprocess.run(cmd, cwd=str(PROJECT_ROOT))

    if result.returncode == 0:
        html_path = REPORTS_DIR / "coverage_html" / "index.html"
        print(f"\nHTML 报告已生成: {html_path}")

    return result.returncode


def generate_xml_report() -> int:
    """生成 XML 覆盖率报告（CI/CD 使用）。"""
    cmd = [
        sys.executable, "-m", "pytest",
        "--cov=shared/core",
        "--cov=shared/business",
        "--cov=M8-control-tower/backend",
        "--cov=M9-dev-workshop/backend",
        "--cov=M11-mcp-bus/src",
        "--cov-report=xml",
        "--cov-report=term",
        "--cov-config=.coveragerc",
    ]

    print(f"\n生成 XML 覆盖率报告...")
    print(f"运行命令: {' '.join(cmd)}\n")
    print("=" * 70)

    result = subprocess.run(cmd, cwd=str(PROJECT_ROOT))

    if result.returncode == 0:
        xml_path = REPORTS_DIR / "coverage.xml"
        print(f"\nXML 报告已生成: {xml_path}")

    return result.returncode


def main():
    parser = argparse.ArgumentParser(
        description="云汐系统测试覆盖率运行脚本",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    # 测试范围
    scope_group = parser.add_mutually_exclusive_group()
    scope_group.add_argument("--unit", action="store_true", help="仅运行单元测试")
    scope_group.add_argument("--integration", action="store_true", help="仅运行集成测试")
    scope_group.add_argument("--module", type=str, help="仅运行指定模块测试 (m8/m9/m11/shared)")

    # 报告格式
    report_group = parser.add_mutually_exclusive_group()
    report_group.add_argument("--html", action="store_true", help="生成 HTML 报告")
    report_group.add_argument("--xml", action="store_true", help="生成 XML 报告")
    report_group.add_argument("--json", action="store_true", help="生成 JSON 报告")

    # 其他选项
    parser.add_argument("--no-cov", action="store_true", help="不统计覆盖率")
    parser.add_argument("--verbose", "-v", action="store_true", help="详细输出")
    parser.add_argument("--failed", action="store_true", help="仅运行失败的测试")
    parser.add_argument("--mark", type=str, help="运行指定标记的测试")

    args = parser.parse_args()

    # 确保报告目录存在
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)

    # 构建 pytest 参数
    pytest_args = []

    if args.verbose:
        pytest_args.append("-v")

    if args.failed:
        pytest_args.append("--lf")

    # 测试范围过滤
    if args.unit:
        pytest_args.extend(["-m", "unit", "--ignore=tests/test_integration"])
    elif args.integration:
        pytest_args.extend(["-m", "integration", "tests/test_integration"])
    elif args.module:
        module = args.module.lower()
        module_map = {
            "m8": "tests/test_m8",
            "m9": "tests/test_m9",
            "m11": "tests/test_m11",
            "shared": "tests/test_shared",
            "m1": "tests/test_m1",
            "m2": "tests/test_m2",
            "m3": "tests/test_m3",
            "m4": "tests/test_m4",
            "m5": "tests/test_m5",
            "m6": "tests/test_m6",
            "m7": "tests/test_m7",
        }
        if module in module_map:
            pytest_args.append(module_map[module])
        else:
            print(f"未知模块: {module}")
            print(f"可用模块: {', '.join(module_map.keys())}")
            return 1

    if args.mark:
        pytest_args.extend(["-m", args.mark])

    # 运行测试
    if args.html:
        return generate_html_report()
    elif args.xml:
        return generate_xml_report()
    else:
        return run_pytest(pytest_args, with_coverage=not args.no_cov)


if __name__ == "__main__":
    sys.exit(main())
