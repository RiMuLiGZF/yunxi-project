#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
云汐系统 v1.1 - 测试运行与报告生成脚本

功能：
- 运行 pytest 测试并收集结果
- 生成 HTML 格式报告（带样式）
- 生成 Markdown 格式报告
- 自动归档到 docs/test-reports/ 目录
- 支持按日期命名

使用：
    python scripts/test/run_tests.py                    # 运行全部测试
    python scripts/test/run_tests.py -m smoke           # 运行冒烟测试
    python scripts/test/run_tests.py tests/test_m8/     # 指定测试目录
    python scripts/test/run_tests.py --no-report        # 不生成报告
"""

import os
import sys
import json
import subprocess
import argparse
from datetime import datetime
from pathlib import Path

# 项目根目录
PROJECT_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

# 报告生成器
from generate_report import TestReportGenerator


# ============================================================
# 测试运行器
# ============================================================
class TestRunner:
    """测试运行器 - 执行 pytest 并生成报告"""

    def __init__(self, project_root: Path = None):
        self.project_root = project_root or PROJECT_ROOT
        self.reports_dir = self.project_root / "docs" / "test-reports"
        self.temp_json = self.project_root / "tests" / "reports" / "test_results.json"
        self.generator = TestReportGenerator(project_name="云汐系统")

    def run(self, test_path: str = "", markers: str = "",
            keywords: str = "", verbose: bool = True,
            generate_report: bool = True,
            report_name: str = None) -> dict:
        """
        运行测试并生成报告

        Args:
            test_path: 测试路径（文件或目录）
            markers: pytest marker 过滤
            keywords: pytest 关键字过滤
            verbose: 是否详细输出
            generate_report: 是否生成报告
            report_name: 报告名称

        Returns:
            运行结果字典
        """
        # 确保目录存在
        self.temp_json.parent.mkdir(parents=True, exist_ok=True)
        self.reports_dir.mkdir(parents=True, exist_ok=True)

        # 构建 pytest 命令
        cmd = [sys.executable, "-m", "pytest"]

        if test_path:
            cmd.append(str(self.project_root / test_path))
        else:
            # 默认使用 pytest.ini 配置的 testpaths
            pass

        # JSON 输出
        cmd.extend([
            "--json-report",
            f"--json-report-file={self.temp_json}",
            "--json-report-verbosity=2",
        ])

        # Marker 过滤
        if markers:
            cmd.extend(["-m", markers])

        # 关键字过滤
        if keywords:
            cmd.extend(["-k", keywords])

        # 详细程度
        if verbose:
            cmd.append("-v")
        else:
            cmd.append("-q")

        cmd.extend(["--tb=short"])

        # 运行测试
        print(f"\n{'='*60}")
        print(f"  🌊 云汐系统 v1.1 - 自动化测试")
        print(f"{'='*60}")
        print(f"  测试路径: {test_path or '全部测试'}")
        if markers:
            print(f"  标记过滤: {markers}")
        if keywords:
            print(f"  关键字: {keywords}")
        print(f"  开始时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        print(f"{'='*60}\n")

        result = subprocess.run(
            cmd,
            cwd=str(self.project_root),
            capture_output=False,
            text=True,
        )

        exit_code = result.returncode
        print(f"\n{'='*60}")
        print(f"  测试完成 (退出码: {exit_code})")
        print(f"{'='*60}\n")

        # 生成报告
        report_paths = {}
        if generate_report and self.temp_json.exists():
            try:
                report_paths = self._generate_report(report_name)
            except Exception as e:
                print(f"⚠️  报告生成失败: {e}")

        return {
            'exit_code': exit_code,
            'json_path': str(self.temp_json) if self.temp_json.exists() else None,
            'reports': report_paths,
            'success': exit_code in (0, 1)  # 0=全部通过, 1=有失败
        }

    def _generate_report(self, report_name: str = None) -> dict:
        """生成测试报告"""
        if not report_name:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            report_name = f"test_report_{timestamp}"

        print("📊 正在生成测试报告...")

        result = self.generator.generate(
            json_path=str(self.temp_json),
            output_dir=str(self.reports_dir),
            report_name=report_name,
        )

        # 同时生成一份 latest 报告（方便查看最新结果）
        try:
            latest_html = self.reports_dir / "latest.html"
            latest_md = self.reports_dir / "latest.md"

            # 复制最新报告
            import shutil
            shutil.copy2(result['html'], str(latest_html))
            shutil.copy2(result['md'], str(latest_md))

            result['latest_html'] = str(latest_html)
            result['latest_md'] = str(latest_md)
        except Exception:
            pass

        # 打印报告信息
        s = result['summary']
        print(f"\n{'='*60}")
        print(f"  📄 报告生成成功")
        print(f"{'='*60}")
        print(f"  📊 总用例: {s['total']} | 通过: {s['passed']} | "
              f"失败: {s['failed']} | 跳过: {s['skipped']}")
        print(f"  📈 通过率: {s['pass_rate']}% | ⏱️  耗时: {s['duration']}s")
        print(f"  {'-'*60}")
        print(f"  🌐 HTML 报告: {result['html']}")
        print(f"  📝 Markdown:  {result['md']}")
        if 'latest_html' in result:
            print(f"  📌 最新报告:  {result['latest_html']}")
        print(f"{'='*60}\n")

        return result


# ============================================================
# 命令行入口
# ============================================================
def main():
    """命令行入口"""
    parser = argparse.ArgumentParser(
        description='云汐系统 v1.1 - 测试运行与报告生成',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  %(prog)s                              # 运行全部测试并生成报告
  %(prog)s -m smoke                     # 运行冒烟测试
  %(prog)s tests/test_m8/               # 运行 M8 模块测试
  %(prog)s -k "auth and not slow"       # 按关键字过滤
  %(prog)s --no-report                  # 只运行测试，不生成报告
  %(prog)s --report-name my_report      # 指定报告名称
        """
    )

    parser.add_argument('test_path', nargs='?', default='',
                        help='测试路径（文件或目录，留空运行全部）')
    parser.add_argument('-m', '--markers', default='',
                        help='pytest marker 过滤表达式')
    parser.add_argument('-k', '--keywords', default='',
                        help='pytest 关键字过滤表达式')
    parser.add_argument('-q', '--quiet', action='store_true',
                        help='安静模式，减少输出')
    parser.add_argument('--no-report', action='store_true',
                        help='不生成测试报告')
    parser.add_argument('--report-name', default=None,
                        help='报告文件名称（不含扩展名）')
    parser.add_argument('--html-only', action='store_true',
                        help='只输出 HTML 报告路径（CI 用）')

    args = parser.parse_args()

    runner = TestRunner()

    try:
        result = runner.run(
            test_path=args.test_path,
            markers=args.markers,
            keywords=args.keywords,
            verbose=not args.quiet,
            generate_report=not args.no_report,
            report_name=args.report_name,
        )

        if args.html_only and result['reports']:
            print(result['reports'].get('html', ''))

        sys.exit(0 if result['exit_code'] == 0 else 1)

    except KeyboardInterrupt:
        print("\n⚠️  测试被用户中断")
        sys.exit(130)
    except Exception as e:
        print(f"❌ 运行出错: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(2)


if __name__ == '__main__':
    main()

