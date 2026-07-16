#!/usr/bin/env python3
"""本地 CI 脚本 — 遍历所有模块运行测试并生成报告."""

import argparse
import os
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
MODULES = [
    "M0-principal-console",
    "M1-agent-hub",
    "M2-skills-cluster",
    "M3-edge-cloud",
    "M4-scene-engine",
    "M5-tide-memory",
    "M6-hardware-peripheral",
    "M7-workflow-builder",
    "M8-control-tower",
    "M9-dev-workshop",
    "M10-system-guard",
    "M11-mcp-bus",
    "M12-security-shield",
    "API-Gateway",
]

REPORT_PATH = PROJECT_ROOT / "reports" / "ci-report.md"


def has_tests(module_dir: Path) -> bool:
    return (module_dir / "tests").exists() or (module_dir / "pytest.ini").exists()


def run_module_tests(module_name: str) -> dict:
    module_dir = PROJECT_ROOT / module_name
    if not module_dir.exists():
        return {"status": "missing", "passed": 0, "failed": 0, "skipped": 0, "duration": 0}

    if not has_tests(module_dir):
        return {"status": "skipped", "passed": 0, "failed": 0, "skipped": 0, "duration": 0}

    start = time.time()
    result = subprocess.run(
        [sys.executable, "-m", "pytest", "--tb=short", "-q", "--timeout=60"],
        cwd=module_dir,
        capture_output=True,
        text=True,
    )
    duration = time.time() - start

    # Parse pytest summary line
    stdout = result.stdout + "\n" + result.stderr
    passed = failed = skipped = 0
    for line in stdout.splitlines():
        if "passed" in line or "failed" in line or "error" in line:
            # e.g. "10 passed, 2 failed, 1 skipped in 5.00s"
            parts = line.split()
            for i, part in enumerate(parts):
                if part == "passed":
                    passed = int(parts[i - 1])
                elif part == "failed":
                    failed = int(parts[i - 1])
                elif part == "skipped":
                    skipped = int(parts[i - 1])
            break

    if result.returncode == 0:
        status = "passed"
    elif passed > 0:
        status = "partial"
    else:
        status = "failed"

    return {"status": status, "passed": passed, "failed": failed, "skipped": skipped, "duration": duration}


def generate_report(results: list) -> str:
    total_passed = sum(r["passed"] for r in results)
    total_failed = sum(r["failed"] for r in results)
    total_skipped = sum(r["skipped"] for r in results)
    total_duration = sum(r["duration"] for r in results)

    lines = [
        "# 云汐本地 CI 报告",
        "",
        f"生成时间: {datetime.now().isoformat()}",
        "",
        "## 汇总",
        "",
        f"| 指标 | 数值 |",
        f"|------|------|",
        f"| 通过 | {total_passed} |",
        f"| 失败 | {total_failed} |",
        f"| 跳过 | {total_skipped} |",
        f"| 总耗时 | {total_duration:.2f}s |",
        "",
        "## 模块详情",
        "",
        "| 模块 | 状态 | 通过 | 失败 | 跳过 | 耗时 |",
        "|------|------|------|------|------|------|",
    ]

    for r in results:
        status_emoji = {"passed": "✅", "partial": "⚠️", "failed": "❌", "skipped": "⏭️", "missing": "❓"}.get(
            r["status"], "❓"
        )
        lines.append(
            f"| {r['module']} | {status_emoji} {r['status']} | {r['passed']} | {r['failed']} | {r['skipped']} | {r['duration']:.2f}s |"
        )

    lines.append("")
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="云汐本地 CI")
    parser.add_argument("--modules", type=str, help="逗号分隔的模块列表，如 M8,M11")
    parser.add_argument("--fail-fast", action="store_true", help="第一个失败即停止")
    args = parser.parse_args()

    modules = args.modules.split(",") if args.modules else MODULES
    print(f"将要测试 {len(modules)} 个模块: {', '.join(modules)}")
    print("=" * 60)

    results = []
    for module in modules:
        print(f"[{module}] 运行测试中...")
        result = run_module_tests(module)
        result["module"] = module
        results.append(result)
        print(f"[{module}] 状态: {result['status']} | 通过: {result['passed']} | 失败: {result['failed']} | 跳过: {result['skipped']} | 耗时: {result['duration']:.2f}s")

        if args.fail_fast and result["failed"] > 0:
            print("--fail-fast: 检测到失败，停止测试")
            break

    print("=" * 60)
    report = generate_report(results)
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(report, encoding="utf-8")
    print(f"报告已生成: {REPORT_PATH}")

    total_failed = sum(r["failed"] for r in results)
    sys.exit(0 if total_failed == 0 else 1)


if __name__ == "__main__":
    main()
