#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
云汐系统 v1.1 - 测试报告生成器

功能：
- 读取 pytest JSON 输出
- 生成美观的 HTML 报告（带图表、统计、失败详情）
- 生成 Markdown 报告
- 包含概览统计、各模块通过率、失败用例详情、运行环境信息

使用：
    from generate_report import TestReportGenerator
    generator = TestReportGenerator()
    generator.generate(json_path, output_dir)
"""

import json
import os
import sys
import platform
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Any, Optional


# ============================================================
# 报告生成器
# ============================================================
class TestReportGenerator:
    """测试报告生成器 - 支持 HTML 和 Markdown 格式"""

    def __init__(self, project_name: str = "云汐系统"):
        self.project_name = project_name
        self.version = "v1.1"

    def generate(self, json_path: str, output_dir: str,
                 report_name: Optional[str] = None) -> Dict[str, str]:
        """
        生成测试报告

        Args:
            json_path: pytest-json 输出文件路径
            output_dir: 报告输出目录
            report_name: 报告名称（可选，默认按日期命名）

        Returns:
            生成的报告文件路径字典 {'html': ..., 'md': ...}
        """
        # 读取测试结果
        test_data = self._load_test_results(json_path)

        # 处理测试数据
        summary = self._process_summary(test_data)
        modules = self._process_by_module(test_data)
        failures = self._process_failures(test_data)
        env_info = self._get_env_info()

        # 生成报告名称
        if not report_name:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            report_name = f"test_report_{timestamp}"

        output_path = Path(output_dir)
        output_path.mkdir(parents=True, exist_ok=True)

        html_path = output_path / f"{report_name}.html"
        md_path = output_path / f"{report_name}.md"

        # 生成 HTML 报告
        html_content = self._generate_html(summary, modules, failures, env_info)
        with open(html_path, 'w', encoding='utf-8') as f:
            f.write(html_content)

        # 生成 Markdown 报告
        md_content = self._generate_markdown(summary, modules, failures, env_info)
        with open(md_path, 'w', encoding='utf-8') as f:
            f.write(md_content)

        return {
            'html': str(html_path),
            'md': str(md_path),
            'summary': summary
        }

    # ============================================================
    # 数据加载与处理
    # ============================================================
    def _load_test_results(self, json_path: str) -> Dict[str, Any]:
        """加载 pytest JSON 结果"""
        if not os.path.exists(json_path):
            raise FileNotFoundError(f"测试结果文件不存在: {json_path}")

        with open(json_path, 'r', encoding='utf-8') as f:
            data = json.load(f)

        return data

    def _process_summary(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """处理汇总统计"""
        # 兼容不同的 pytest-json 格式
        summary = data.get('summary', {})
        tests = data.get('tests', [])

        total = summary.get('total', len(tests))
        passed = summary.get('passed', 0)
        failed = summary.get('failed', 0)
        skipped = summary.get('skipped', 0)
        errors = summary.get('error', 0)
        xfailed = summary.get('xfailed', 0)
        xpassed = summary.get('xpassed', 0)

        # 如果 summary 中没有数据，从 tests 列表统计
        if total == 0 and tests:
            total = len(tests)
            outcome_counts = {}
            for t in tests:
                outcome = t.get('outcome', t.get('result', 'unknown'))
                outcome_counts[outcome] = outcome_counts.get(outcome, 0) + 1
            passed = outcome_counts.get('passed', 0)
            failed = outcome_counts.get('failed', 0)
            skipped = outcome_counts.get('skipped', 0)
            errors = outcome_counts.get('error', 0)

        duration = summary.get('duration', 0)
        if duration == 0 and tests:
            duration = sum(t.get('duration', 0) for t in tests)

        pass_rate = (passed / total * 100) if total > 0 else 0

        # 状态判断
        if failed > 0 or errors > 0:
            status = 'failed'
            status_text = '未通过'
        elif total == 0:
            status = 'empty'
            status_text = '无测试'
        else:
            status = 'passed'
            status_text = '全部通过'

        return {
            'total': total,
            'passed': passed,
            'failed': failed,
            'skipped': skipped,
            'errors': errors,
            'xfailed': xfailed,
            'xpassed': xpassed,
            'pass_rate': round(pass_rate, 2),
            'duration': round(duration, 2),
            'status': status,
            'status_text': status_text,
        }

    def _process_by_module(self, data: Dict[str, Any]) -> List[Dict[str, Any]]:
        """按模块统计测试结果"""
        tests = data.get('tests', [])
        module_stats = {}

        for test in tests:
            # 从 nodeid 提取模块名
            nodeid = test.get('nodeid', '')
            # 提取路径中的模块目录（如 test_m8/, test_m1/ 等）
            parts = nodeid.split('/')
            if len(parts) >= 2:
                module = parts[0]  # 第一级目录作为模块
            elif '::' in nodeid:
                module = nodeid.split('::')[0].split('/')[0]
            else:
                module = 'other'

            # 清理模块名
            module = module.replace('test_', '').replace('.py', '')
            if not module:
                module = 'other'

            if module not in module_stats:
                module_stats[module] = {
                    'name': module,
                    'total': 0,
                    'passed': 0,
                    'failed': 0,
                    'skipped': 0,
                    'errors': 0,
                    'duration': 0,
                }

            outcome = test.get('outcome', test.get('result', 'unknown'))
            module_stats[module]['total'] += 1
            module_stats[module]['duration'] += test.get('duration', 0)

            if outcome == 'passed':
                module_stats[module]['passed'] += 1
            elif outcome == 'failed':
                module_stats[module]['failed'] += 1
            elif outcome == 'skipped':
                module_stats[module]['skipped'] += 1
            elif outcome == 'error':
                module_stats[module]['errors'] += 1

        # 计算通过率
        result = []
        for mod in module_stats.values():
            total = mod['total']
            mod['pass_rate'] = round((mod['passed'] / total * 100), 1) if total > 0 else 0
            mod['duration'] = round(mod['duration'], 2)
            result.append(mod)

        # 按总数降序排列
        result.sort(key=lambda x: x['total'], reverse=True)
        return result

    def _process_failures(self, data: Dict[str, Any]) -> List[Dict[str, Any]]:
        """处理失败用例详情"""
        tests = data.get('tests', [])
        failures = []

        for test in tests:
            outcome = test.get('outcome', test.get('result', ''))
            if outcome in ('failed', 'error'):
                # 提取错误信息
                call = test.get('call', {})
                crash = test.get('crash', {})
                longrepr = call.get('longrepr', crash.get('message', ''))

                # 解析 longrepr 获取错误信息和堆栈
                error_msg = ''
                traceback = ''
                if isinstance(longrepr, str):
                    lines = longrepr.strip().split('\n')
                    if lines:
                        error_msg = lines[-1] if lines else longrepr[:200]
                        traceback = longrepr
                elif isinstance(longrepr, dict):
                    error_msg = longrepr.get('reprtext', str(longrepr))
                    traceback = error_msg

                failures.append({
                    'name': test.get('nodeid', 'unknown'),
                    'outcome': outcome,
                    'duration': round(test.get('duration', 0), 3),
                    'error_message': error_msg[:300],
                    'traceback': traceback,
                })

        return failures

    def _get_env_info(self) -> Dict[str, str]:
        """获取运行环境信息"""
        return {
            'python_version': platform.python_version(),
            'platform': platform.platform(),
            'system': platform.system(),
            'machine': platform.machine(),
            'run_time': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            'project': self.project_name,
            'version': self.version,
        }

    # ============================================================
    # HTML 报告生成
    # ============================================================
    def _generate_html(self, summary: Dict, modules: List[Dict],
                       failures: List[Dict], env: Dict) -> str:
        """生成 HTML 格式报告"""

        # 状态颜色
        status_colors = {
            'passed': '#10b981',
            'failed': '#ef4444',
            'empty': '#6b7280',
        }
        status_color = status_colors.get(summary['status'], '#6b7280')

        # 生成模块列表 HTML
        modules_html = ''
        for i, mod in enumerate(modules):
            status_class = 'pass' if mod['failed'] == 0 else 'fail'
            modules_html += f'''
                    <tr>
                        <td><span class="module-name">{mod['name']}</span></td>
                        <td class="num">{mod['total']}</td>
                        <td class="num pass">{mod['passed']}</td>
                        <td class="num fail">{mod['failed']}</td>
                        <td class="num skip">{mod['skipped']}</td>
                        <td>
                            <div class="progress-bar">
                                <div class="progress-fill {status_class}" style="width: {mod['pass_rate']}%"></div>
                            </div>
                            <span class="progress-text">{mod['pass_rate']}%</span>
                        </td>
                        <td class="num">{mod['duration']}s</td>
                    </tr>'''

        # 生成失败用例 HTML
        failures_html = ''
        if failures:
            for i, fail in enumerate(failures):
                # 转义 HTML
                tb_escaped = fail['traceback'].replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
                err_escaped = fail['error_message'].replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
                name_escaped = fail['name'].replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')

                failures_html += f'''
                    <div class="failure-item">
                        <div class="failure-header" onclick="toggleFailure({i})">
                            <span class="failure-icon">✕</span>
                            <span class="failure-name" title="{name_escaped}">{name_escaped}</span>
                            <span class="failure-toggle" id="toggle-{i}">▼</span>
                        </div>
                        <div class="failure-detail" id="detail-{i}" style="display: none;">
                            <div class="failure-error">{err_escaped}</div>
                            <pre class="failure-traceback">{tb_escaped}</pre>
                        </div>
                    </div>'''
        else:
            failures_html = '''
                    <div class="no-failures">
                        <span class="success-icon">✓</span>
                        <p>太棒了！所有测试均通过，没有失败用例。</p>
                    </div>'''

        # 饼图数据（用 CSS 实现的简易图表）
        pie_segments = []
        total = summary['total']
        colors = [
            ('--chart-pass', '#10b981', summary['passed']),
            ('--chart-fail', '#ef4444', summary['failed']),
            ('--chart-skip', '#f59e0b', summary['skipped']),
            ('--chart-error', '#8b5cf6', summary['errors']),
        ]
        cumulative = 0
        pie_css_vars = ''
        for name, color, count in colors:
            if total > 0:
                percent = (count / total) * 100
                start = cumulative
                end = cumulative + percent
                cumulative = end
                pie_css_vars += f'  {name}: {color};\n'
                pie_css_vars += f'  {name}-start: {start}%;\n'
                pie_css_vars += f'  {name}-end: {end}%;\n'

        html = f'''<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>测试报告 - {env['project']} {env['version']}</title>
    <style>
        /* ============================================================
           云汐系统测试报告 - 深色主题
           ============================================================ */
        :root {{
            --bg-primary: #0f172a;
            --bg-secondary: #1e293b;
            --bg-card: #1e293b;
            --bg-hover: #334155;
            --border: #334155;
            --text-primary: #f1f5f9;
            --text-secondary: #94a3b8;
            --text-tertiary: #64748b;
            --accent: #38bdf8;
            --accent-glow: rgba(56, 189, 248, 0.3);
            --success: #10b981;
            --success-bg: rgba(16, 185, 129, 0.1);
            --danger: #ef4444;
            --danger-bg: rgba(239, 68, 68, 0.1);
            --warning: #f59e0b;
            --warning-bg: rgba(245, 158, 11, 0.1);
            --info: #3b82f6;
            --radius: 12px;
            --radius-sm: 8px;
            --shadow: 0 4px 20px rgba(0, 0, 0, 0.3);
        }}

        * {{ margin: 0; padding: 0; box-sizing: border-box; }}

        body {{
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', 'PingFang SC',
                         'Microsoft YaHei', sans-serif;
            background: var(--bg-primary);
            color: var(--text-primary);
            line-height: 1.6;
            padding: 20px;
        }}

        .container {{
            max-width: 1100px;
            margin: 0 auto;
        }}

        /* 头部 */
        .header {{
            text-align: center;
            padding: 40px 20px;
            background: linear-gradient(135deg, #1e293b 0%, #0f172a 100%);
            border-radius: var(--radius);
            border: 1px solid var(--border);
            margin-bottom: 24px;
            position: relative;
            overflow: hidden;
        }}
        .header::before {{
            content: '';
            position: absolute;
            top: 0; left: 0; right: 0;
            height: 3px;
            background: linear-gradient(90deg, #38bdf8, #22d3ee, #10b981);
        }}
        .header h1 {{
            font-size: 28px;
            font-weight: 700;
            margin-bottom: 8px;
            background: linear-gradient(135deg, #38bdf8, #22d3ee);
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
            background-clip: text;
        }}
        .header .subtitle {{
            color: var(--text-secondary);
            font-size: 14px;
        }}

        /* 状态横幅 */
        .status-banner {{
            padding: 16px 24px;
            border-radius: var(--radius);
            margin-bottom: 24px;
            display: flex;
            align-items: center;
            justify-content: center;
            gap: 12px;
            font-size: 18px;
            font-weight: 600;
            border: 1px solid;
        }}
        .status-banner.passed {{
            background: var(--success-bg);
            border-color: var(--success);
            color: var(--success);
        }}
        .status-banner.failed {{
            background: var(--danger-bg);
            border-color: var(--danger);
            color: var(--danger);
        }}
        .status-banner.empty {{
            background: rgba(107, 114, 128, 0.1);
            border-color: var(--text-tertiary);
            color: var(--text-secondary);
        }}
        .status-banner .icon {{ font-size: 28px; }}

        /* 统计卡片网格 */
        .stats-grid {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(160px, 1fr));
            gap: 16px;
            margin-bottom: 24px;
        }}
        .stat-card {{
            background: var(--bg-card);
            border: 1px solid var(--border);
            border-radius: var(--radius);
            padding: 20px;
            text-align: center;
            transition: transform 0.2s, box-shadow 0.2s;
        }}
        .stat-card:hover {{
            transform: translateY(-2px);
            box-shadow: var(--shadow);
        }}
        .stat-card .value {{
            font-size: 32px;
            font-weight: 700;
            margin-bottom: 4px;
            font-variant-numeric: tabular-nums;
        }}
        .stat-card .label {{
            font-size: 13px;
            color: var(--text-secondary);
        }}
        .stat-card.pass .value {{ color: var(--success); }}
        .stat-card.fail .value {{ color: var(--danger); }}
        .stat-card.skip .value {{ color: var(--warning); }}
        .stat-card.rate .value {{ color: var(--accent); }}

        /* 图表区域 */
        .chart-section {{
            display: grid;
            grid-template-columns: 300px 1fr;
            gap: 24px;
            margin-bottom: 24px;
        }}
        @media (max-width: 768px) {{
            .chart-section {{ grid-template-columns: 1fr; }}
        }}

        .pie-chart-container {{
            background: var(--bg-card);
            border: 1px solid var(--border);
            border-radius: var(--radius);
            padding: 24px;
            display: flex;
            flex-direction: column;
            align-items: center;
        }}
        .pie-chart {{
            width: 180px;
            height: 180px;
            border-radius: 50%;
            background: conic-gradient(
                var(--success) 0% var(--chart-pass-end),
                var(--danger) var(--chart-pass-end) var(--chart-fail-end),
                var(--warning) var(--chart-fail-end) var(--chart-skip-end),
                var(--text-tertiary) var(--chart-skip-end) 100%
            );
            position: relative;
            margin-bottom: 16px;
        }}
        .pie-chart::after {{
            content: '';
            position: absolute;
            top: 20%; left: 20%;
            width: 60%; height: 60%;
            background: var(--bg-card);
            border-radius: 50%;
        }}
        .pie-center {{
            position: absolute;
            top: 50%; left: 50%;
            transform: translate(-50%, -50%);
            text-align: center;
            z-index: 1;
        }}
        .pie-center .rate {{
            font-size: 24px;
            font-weight: 700;
            color: var(--accent);
        }}
        .pie-center .label {{
            font-size: 11px;
            color: var(--text-secondary);
        }}

        .pie-legend {{
            display: flex;
            flex-direction: column;
            gap: 8px;
            width: 100%;
        }}
        .legend-item {{
            display: flex;
            align-items: center;
            gap: 8px;
            font-size: 13px;
        }}
        .legend-dot {{
            width: 10px;
            height: 10px;
            border-radius: 50%;
        }}
        .legend-dot.pass {{ background: var(--success); }}
        .legend-dot.fail {{ background: var(--danger); }}
        .legend-dot.skip {{ background: var(--warning); }}
        .legend-dot.error {{ background: #8b5cf6; }}
        .legend-value {{
            margin-left: auto;
            color: var(--text-secondary);
            font-variant-numeric: tabular-nums;
        }}

        /* 卡片通用样式 */
        .card {{
            background: var(--bg-card);
            border: 1px solid var(--border);
            border-radius: var(--radius);
            overflow: hidden;
        }}
        .card-header {{
            padding: 16px 20px;
            border-bottom: 1px solid var(--border);
            font-weight: 600;
            font-size: 16px;
            display: flex;
            align-items: center;
            gap: 8px;
        }}
        .card-body {{ padding: 20px; }}

        /* 模块表格 */
        .module-section {{ margin-bottom: 24px; }}
        table {{
            width: 100%;
            border-collapse: collapse;
        }}
        th, td {{
            padding: 12px 16px;
            text-align: left;
            border-bottom: 1px solid var(--border);
        }}
        th {{
            background: rgba(56, 189, 248, 0.05);
            font-weight: 600;
            font-size: 13px;
            color: var(--text-secondary);
            text-transform: uppercase;
            letter-spacing: 0.5px;
        }}
        tr:hover td {{ background: var(--bg-hover); }}
        td.num {{ text-align: right; font-variant-numeric: tabular-nums; }}
        td.pass {{ color: var(--success); }}
        td.fail {{ color: var(--danger); }}
        td.skip {{ color: var(--warning); }}
        .module-name {{
            font-weight: 500;
            font-family: 'JetBrains Mono', 'Fira Code', monospace;
            font-size: 13px;
        }}

        .progress-bar {{
            width: 100px;
            height: 6px;
            background: var(--bg-primary);
            border-radius: 3px;
            overflow: hidden;
            display: inline-block;
            vertical-align: middle;
        }}
        .progress-fill {{
            height: 100%;
            border-radius: 3px;
            transition: width 0.3s;
        }}
        .progress-fill.pass {{ background: var(--success); }}
        .progress-fill.fail {{ background: var(--danger); }}
        .progress-text {{
            margin-left: 8px;
            font-size: 12px;
            color: var(--text-secondary);
            font-variant-numeric: tabular-nums;
        }}

        /* 失败用例 */
        .failure-section {{ margin-bottom: 24px; }}
        .failure-item {{
            border: 1px solid var(--border);
            border-radius: var(--radius-sm);
            margin-bottom: 8px;
            overflow: hidden;
            transition: border-color 0.2s;
        }}
        .failure-item:hover {{ border-color: var(--danger); }}
        .failure-header {{
            padding: 12px 16px;
            background: var(--danger-bg);
            cursor: pointer;
            display: flex;
            align-items: center;
            gap: 10px;
            user-select: none;
        }}
        .failure-icon {{
            color: var(--danger);
            font-weight: bold;
            font-size: 14px;
        }}
        .failure-name {{
            flex: 1;
            font-family: 'JetBrains Mono', 'Fira Code', monospace;
            font-size: 13px;
            color: var(--text-primary);
            overflow: hidden;
            text-overflow: ellipsis;
            white-space: nowrap;
        }}
        .failure-toggle {{
            color: var(--text-tertiary);
            font-size: 10px;
            transition: transform 0.2s;
        }}
        .failure-detail {{
            padding: 16px;
            border-top: 1px solid var(--border);
            background: var(--bg-primary);
        }}
        .failure-error {{
            color: var(--danger);
            font-weight: 500;
            margin-bottom: 12px;
            padding: 10px 14px;
            background: var(--danger-bg);
            border-radius: var(--radius-sm);
            font-size: 13px;
        }}
        .failure-traceback {{
            background: #0a0f1a;
            padding: 14px;
            border-radius: var(--radius-sm);
            font-family: 'JetBrains Mono', 'Fira Code', monospace;
            font-size: 12px;
            line-height: 1.6;
            color: var(--text-secondary);
            overflow-x: auto;
            max-height: 300px;
            overflow-y: auto;
        }}

        .no-failures {{
            text-align: center;
            padding: 40px 20px;
            color: var(--success);
        }}
        .success-icon {{
            font-size: 48px;
            margin-bottom: 12px;
            display: block;
        }}

        /* 环境信息 */
        .env-section {{ margin-bottom: 24px; }}
        .env-grid {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
            gap: 12px;
        }}
        .env-item {{
            display: flex;
            justify-content: space-between;
            padding: 10px 14px;
            background: var(--bg-primary);
            border-radius: var(--radius-sm);
        }}
        .env-item .key {{
            color: var(--text-secondary);
            font-size: 13px;
        }}
        .env-item .value {{
            color: var(--text-primary);
            font-size: 13px;
            font-weight: 500;
        }}

        /* 页脚 */
        .footer {{
            text-align: center;
            padding: 20px;
            color: var(--text-tertiary);
            font-size: 12px;
        }}

        /* 滚动条 */
        ::-webkit-scrollbar {{ width: 8px; height: 8px; }}
        ::-webkit-scrollbar-track {{ background: var(--bg-primary); }}
        ::-webkit-scrollbar-thumb {{ background: var(--border); border-radius: 4px; }}
        ::-webkit-scrollbar-thumb:hover {{ background: var(--text-tertiary); }}
    </style>
</head>
<body>
    <div class="container">
        <!-- 头部 -->
        <div class="header">
            <h1>🌊 {env['project']} {env['version']} · 测试报告</h1>
            <div class="subtitle">自动化测试执行报告 · 生成时间: {env['run_time']}</div>
        </div>

        <!-- 状态横幅 -->
        <div class="status-banner {summary['status']}">
            <span class="icon">{'✓' if summary['status'] == 'passed' else '✕'}</span>
            <span>测试结果: {summary['status_text']}</span>
        </div>

        <!-- 统计卡片 -->
        <div class="stats-grid">
            <div class="stat-card">
                <div class="value">{summary['total']}</div>
                <div class="label">总用例数</div>
            </div>
            <div class="stat-card pass">
                <div class="value">{summary['passed']}</div>
                <div class="label">通过</div>
            </div>
            <div class="stat-card fail">
                <div class="value">{summary['failed']}</div>
                <div class="label">失败</div>
            </div>
            <div class="stat-card skip">
                <div class="value">{summary['skipped']}</div>
                <div class="label">跳过</div>
            </div>
            <div class="stat-card rate">
                <div class="value">{summary['pass_rate']}%</div>
                <div class="label">通过率</div>
            </div>
            <div class="stat-card">
                <div class="value">{summary['duration']}s</div>
                <div class="label">总耗时</div>
            </div>
        </div>

        <!-- 图表区 -->
        <div class="chart-section">
            <div class="pie-chart-container">
                <div class="pie-chart" style="{pie_css_vars}">
                    <div class="pie-center">
                        <div class="rate">{summary['pass_rate']}%</div>
                        <div class="label">通过率</div>
                    </div>
                </div>
                <div class="pie-legend">
                    <div class="legend-item">
                        <span class="legend-dot pass"></span>
                        <span>通过</span>
                        <span class="legend-value">{summary['passed']} ({round(summary['passed']/summary['total']*100, 1) if summary['total'] > 0 else 0}%)</span>
                    </div>
                    <div class="legend-item">
                        <span class="legend-dot fail"></span>
                        <span>失败</span>
                        <span class="legend-value">{summary['failed']} ({round(summary['failed']/summary['total']*100, 1) if summary['total'] > 0 else 0}%)</span>
                    </div>
                    <div class="legend-item">
                        <span class="legend-dot skip"></span>
                        <span>跳过</span>
                        <span class="legend-value">{summary['skipped']} ({round(summary['skipped']/summary['total']*100, 1) if summary['total'] > 0 else 0}%)</span>
                    </div>
                </div>
            </div>

            <!-- 模块统计 -->
            <div class="card module-section">
                <div class="card-header">📦 按模块统计</div>
                <div style="overflow-x: auto;">
                    <table>
                        <thead>
                            <tr>
                                <th>模块</th>
                                <th class="num">总数</th>
                                <th class="num">通过</th>
                                <th class="num">失败</th>
                                <th class="num">跳过</th>
                                <th>通过率</th>
                                <th class="num">耗时</th>
                            </tr>
                        </thead>
                        <tbody>
                            {modules_html}
                        </tbody>
                    </table>
                </div>
            </div>
        </div>

        <!-- 失败用例详情 -->
        <div class="card failure-section">
            <div class="card-header">❌ 失败用例详情 ({len(failures)})</div>
            <div class="card-body">
                {failures_html}
            </div>
        </div>

        <!-- 环境信息 -->
        <div class="card env-section">
            <div class="card-header">🖥️ 运行环境</div>
            <div class="card-body">
                <div class="env-grid">
                    <div class="env-item">
                        <span class="key">项目</span>
                        <span class="value">{env['project']} {env['version']}</span>
                    </div>
                    <div class="env-item">
                        <span class="key">Python 版本</span>
                        <span class="value">{env['python_version']}</span>
                    </div>
                    <div class="env-item">
                        <span class="key">操作系统</span>
                        <span class="value">{env['system']}</span>
                    </div>
                    <div class="env-item">
                        <span class="key">平台</span>
                        <span class="value">{env['platform']}</span>
                    </div>
                    <div class="env-item">
                        <span class="key">架构</span>
                        <span class="value">{env['machine']}</span>
                    </div>
                    <div class="env-item">
                        <span class="key">测试时间</span>
                        <span class="value">{env['run_time']}</span>
                    </div>
                </div>
            </div>
        </div>

        <!-- 页脚 -->
        <div class="footer">
            本报告由云汐系统自动化测试框架生成 · {env['run_time']}
        </div>
    </div>

    <script>
        // 折叠/展开失败用例详情
        function toggleFailure(index) {{
            const detail = document.getElementById('detail-' + index);
            const toggle = document.getElementById('toggle-' + index);
            if (detail.style.display === 'none') {{
                detail.style.display = 'block';
                toggle.textContent = '▲';
            }} else {{
                detail.style.display = 'none';
                toggle.textContent = '▼';
            }}
        }}
    </script>
</body>
</html>'''
        return html

    # ============================================================
    # Markdown 报告生成
    # ============================================================
    def _generate_markdown(self, summary: Dict, modules: List[Dict],
                           failures: List[Dict], env: Dict) -> str:
        """生成 Markdown 格式报告"""

        # 状态图标
        if summary['status'] == 'passed':
            status_icon = '✅'
        elif summary['status'] == 'failed':
            status_icon = '❌'
        else:
            status_icon = '⚪'

        # 模块统计表格
        modules_table = '''| 模块 | 总数 | 通过 | 失败 | 跳过 | 通过率 | 耗时 |
|------|------|------|------|------|--------|------|
'''
        for mod in modules:
            modules_table += f"| `{mod['name']}` | {mod['total']} | ✅ {mod['passed']} | ❌ {mod['failed']} | ⏭️ {mod['skipped']} | {mod['pass_rate']}% | {mod['duration']}s |\n"

        # 失败用例
        failures_section = ''
        if failures:
            failures_section = f'\n## ❌ 失败用例详情 ({len(failures)})\n\n'
            for i, fail in enumerate(failures, 1):
                failures_section += f'### {i}. `{fail["name"]}`\n\n'
                failures_section += f'- **结果**: {fail["outcome"]}\n'
                failures_section += f'- **耗时**: {fail["duration"]}s\n'
                failures_section += f'- **错误**: {fail["error_message"][:200]}\n\n'
                if fail['traceback']:
                    failures_section += '```\n' + fail['traceback'][:2000] + '\n```\n\n'
        else:
            failures_section = '\n## ✅ 所有测试通过\n\n没有失败的测试用例。\n'

        md = f"""# {env['project']} {env['version']} · 测试报告

> 自动化测试执行报告
> 生成时间: {env['run_time']}

## 📊 概览

{status_icon} **测试结果: {summary['status_text']}**

| 指标 | 数值 |
|------|------|
| 总用例数 | {summary['total']} |
| ✅ 通过 | {summary['passed']} |
| ❌ 失败 | {summary['failed']} |
| ⏭️ 跳过 | {summary['skipped']} |
| ⚠️ 错误 | {summary['errors']} |
| 📈 通过率 | **{summary['pass_rate']}%** |
| ⏱️ 总耗时 | {summary['duration']}s |

## 📦 按模块统计

{modules_table}
{failures_section}
## 🖥️ 运行环境

| 项目 | 信息 |
|------|------|
| 项目名称 | {env['project']} {env['version']} |
| Python 版本 | {env['python_version']} |
| 操作系统 | {env['system']} |
| 平台 | {env['platform']} |
| 架构 | {env['machine']} |
| 测试时间 | {env['run_time']} |

---

*本报告由云汐系统自动化测试框架自动生成*
"""
        return md


# ============================================================
# 命令行入口
# ============================================================
def main():
    """命令行入口"""
    import argparse

    parser = argparse.ArgumentParser(description='云汐系统 - 测试报告生成器')
    parser.add_argument('json_path', help='pytest JSON 结果文件路径')
    parser.add_argument('-o', '--output-dir', default='docs/test-reports',
                        help='报告输出目录 (默认: docs/test-reports)')
    parser.add_argument('-n', '--name', default=None,
                        help='报告名称 (默认: 按日期命名)')
    parser.add_argument('--project', default='云汐系统',
                        help='项目名称 (默认: 云汐系统)')

    args = parser.parse_args()

    try:
        generator = TestReportGenerator(project_name=args.project)
        result = generator.generate(
            json_path=args.json_path,
            output_dir=args.output_dir,
            report_name=args.name
        )

        print(f"\n{'='*60}")
        print(f"  📊 测试报告生成成功!")
        print(f"{'='*60}")
        print(f"  📄 HTML 报告: {result['html']}")
        print(f"  📝 Markdown:  {result['md']}")
        print(f"  {'-'*60}")
        s = result['summary']
        print(f"  总计: {s['total']} | 通过: {s['passed']} | "
              f"失败: {s['failed']} | 跳过: {s['skipped']}")
        print(f"  通过率: {s['pass_rate']}% | 耗时: {s['duration']}s")
        print(f"{'='*60}\n")

    except Exception as e:
        print(f"❌ 生成报告失败: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == '__main__':
    main()
