"""
性能报告生成模块

生成 HTML 格式的性能测试报告，包含：
- 性能指标汇总
- 历史数据对比
- 性能趋势图（使用纯 CSS 柱状图）
- 测试结果详情

使用方式::

    from tests.performance.report import generate_html_report

    results = {
        "db_select_by_id": {"mean_ms": 0.5, "p95_ms": 1.2, ...},
        ...
    }
    html = generate_html_report(results, memory_results={})
    with open("report.html", "w") as f:
        f.write(html)
"""

import os
import json
import time
from pathlib import Path
from typing import Any, Dict, List, Optional
from datetime import datetime


# ============================================================
# HTML 模板
# ============================================================

HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>云汐系统性能基准测试报告</title>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body {
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif;
            background: #f5f7fa;
            color: #333;
            line-height: 1.6;
            padding: 20px;
        }
        .container { max-width: 1200px; margin: 0 auto; }
        header {
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white;
            padding: 30px;
            border-radius: 12px;
            margin-bottom: 30px;
        }
        header h1 { font-size: 28px; margin-bottom: 10px; }
        header .meta { opacity: 0.9; font-size: 14px; }
        .summary-grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
            gap: 15px;
            margin-bottom: 30px;
        }
        .summary-card {
            background: white;
            padding: 20px;
            border-radius: 10px;
            box-shadow: 0 2px 8px rgba(0,0,0,0.06);
        }
        .summary-card .label { font-size: 13px; color: #888; margin-bottom: 5px; }
        .summary-card .value { font-size: 24px; font-weight: 600; color: #333; }
        .summary-card .unit { font-size: 14px; color: #888; font-weight: normal; }
        section {
            background: white;
            border-radius: 10px;
            padding: 25px;
            margin-bottom: 20px;
            box-shadow: 0 2px 8px rgba(0,0,0,0.06);
        }
        section h2 {
            font-size: 20px;
            margin-bottom: 20px;
            padding-bottom: 10px;
            border-bottom: 2px solid #f0f0f0;
            color: #333;
        }
        table {
            width: 100%;
            border-collapse: collapse;
            font-size: 14px;
        }
        th, td {
            padding: 12px 15px;
            text-align: left;
            border-bottom: 1px solid #f0f0f0;
        }
        th {
            background: #f8f9fa;
            font-weight: 600;
            color: #555;
            font-size: 13px;
            text-transform: uppercase;
            letter-spacing: 0.5px;
        }
        tr:hover { background: #f8f9fa; }
        .bar-cell { min-width: 150px; }
        .bar-container {
            height: 20px;
            background: #f0f0f0;
            border-radius: 4px;
            overflow: hidden;
            position: relative;
        }
        .bar-fill {
            height: 100%;
            background: linear-gradient(90deg, #667eea, #764ba2);
            border-radius: 4px;
            transition: width 0.3s ease;
        }
        .bar-fill.fast { background: linear-gradient(90deg, #11998e, #38ef7d); }
        .bar-fill.medium { background: linear-gradient(90deg, #f093fb, #f5576c); }
        .bar-fill.slow { background: linear-gradient(90deg, #ff416c, #ff4b2b); }
        .bar-label {
            position: absolute;
            right: 5px;
            top: 50%;
            transform: translateY(-50%);
            font-size: 11px;
            color: #666;
        }
        .status-badge {
            display: inline-block;
            padding: 4px 10px;
            border-radius: 12px;
            font-size: 12px;
            font-weight: 600;
        }
        .status-fast { background: #d4edda; color: #155724; }
        .status-medium { background: #fff3cd; color: #856404; }
        .status-slow { background: #f8d7da; color: #721c24; }
        .category-tabs {
            display: flex;
            gap: 10px;
            margin-bottom: 20px;
            flex-wrap: wrap;
        }
        .category-tab {
            padding: 8px 16px;
            background: #f0f0f0;
            border-radius: 20px;
            cursor: pointer;
            font-size: 14px;
            transition: all 0.2s;
        }
        .category-tab:hover { background: #e0e0e0; }
        .category-tab.active {
            background: #667eea;
            color: white;
        }
        .test-group { display: none; }
        .test-group.active { display: block; }
        footer {
            text-align: center;
            padding: 20px;
            color: #999;
            font-size: 13px;
        }
        .metric-row {
            display: flex;
            justify-content: space-between;
            padding: 8px 0;
            border-bottom: 1px solid #f5f5f5;
        }
        .metric-row:last-child { border-bottom: none; }
        .metric-label { color: #666; }
        .metric-value { font-weight: 600; }
        .comparison-table { margin-top: 15px; }
        .trend-chart {
            display: flex;
            align-items: flex-end;
            height: 150px;
            gap: 5px;
            padding: 20px 0;
            border-bottom: 2px solid #f0f0f0;
        }
        .trend-bar {
            flex: 1;
            background: linear-gradient(180deg, #667eea, #764ba2);
            border-radius: 4px 4px 0 0;
            min-height: 5px;
            position: relative;
            transition: all 0.3s;
        }
        .trend-bar:hover { opacity: 0.8; }
        .trend-bar-label {
            position: absolute;
            bottom: -25px;
            left: 50%;
            transform: translateX(-50%);
            font-size: 11px;
            color: #999;
            white-space: nowrap;
        }
        .memory-section {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(300px, 1fr));
            gap: 20px;
        }
        .memory-card {
            background: #f8f9fa;
            padding: 15px;
            border-radius: 8px;
        }
        .memory-card h4 { margin-bottom: 10px; color: #555; }
    </style>
</head>
<body>
    <div class="container">
        <header>
            <h1>云汐系统性能基准测试报告</h1>
            <div class="meta">
                生成时间: {{generated_at}} |
                测试项: {{total_tests}} 项 |
                环境: {{environment}}
            </div>
        </header>

        <!-- 汇总卡片 -->
        <div class="summary-grid">
            {{summary_cards}}
        </div>

        <!-- 分类标签 -->
        <section>
            <h2>测试结果详情</h2>
            <div class="category-tabs">
                {{category_tabs}}
            </div>
            {{test_sections}}
        </section>

        <!-- 内存测试 -->
        {{memory_section}}

        <!-- 性能指标说明 -->
        <section>
            <h2>性能指标说明</h2>
            <div class="metric-row">
                <span class="metric-label">mean (平均值)</span>
                <span class="metric-value">所有测量值的算术平均</span>
            </div>
            <div class="metric-row">
                <span class="metric-label">median (中位数)</span>
                <span class="metric-value">中间值，不受极端值影响</span>
            </div>
            <div class="metric-row">
                <span class="metric-label">P95 / P99</span>
                <span class="metric-value">95% / 99% 的请求在此时间内完成</span>
            </div>
            <div class="metric-row">
                <span class="metric-label">QPS</span>
                <span class="metric-value">每秒查询数（吞吐量）</span>
            </div>
            <div class="metric-row">
                <span class="metric-label">stdev (标准差)</span>
                <span class="metric-value">性能波动程度，越小越稳定</span>
            </div>
        </section>

        <footer>
            云汐系统性能测试框架 v1.0 | 报告自动生成
        </footer>
    </div>

    <script>
        // 分类切换
        function showCategory(category) {{
            document.querySelectorAll('.category-tab').forEach(tab => {{
                tab.classList.toggle('active', tab.dataset.category === category);
            }});
            document.querySelectorAll('.test-group').forEach(group => {{
                group.classList.toggle('active', group.dataset.category === category);
            }});
        }}

        // 默认显示第一个分类
        document.addEventListener('DOMContentLoaded', function() {{
            const firstTab = document.querySelector('.category-tab');
            if (firstTab) {{
                showCategory(firstTab.dataset.category);
            }}
        }});
    </script>
</body>
</html>
"""


# ============================================================
# 报告生成
# ============================================================

def _get_category(name: str) -> str:
    """根据测试名称获取分类"""
    name_lower = name.lower()
    if name_lower.startswith("db_") or "database" in name_lower or "db:" in name_lower:
        return "数据库"
    if name_lower.startswith("api_") or "api:" in name_lower:
        return "API"
    if name_lower.startswith("memory_") or "memory:" in name_lower:
        return "内存"
    if name_lower.startswith("cache_") or "cache:" in name_lower:
        return "缓存"
    return "其他"


def _get_status(mean_ms: float) -> tuple:
    """根据平均耗时获取状态标签"""
    if mean_ms < 1:
        return "fast", "极快"
    elif mean_ms < 10:
        return "fast", "快"
    elif mean_ms < 50:
        return "medium", "中等"
    elif mean_ms < 100:
        return "medium", "较慢"
    else:
        return "slow", "慢"


def _generate_summary_cards(results: Dict[str, Dict[str, Any]]) -> str:
    """生成汇总卡片"""
    if not results:
        return '<div class="summary-card"><div class="label">暂无数据</div></div>'

    all_means = [r.get("mean_ms", 0) for r in results.values() if "mean_ms" in r]
    all_qps = [r.get("qps", 0) for r in results.values() if "qps" in r]

    avg_mean = sum(all_means) / len(all_means) if all_means else 0
    total_qps = sum(all_qps) if all_qps else 0
    test_count = len(results)

    # 统计快慢
    fast_count = sum(1 for m in all_means if m < 10)
    slow_count = sum(1 for m in all_means if m > 100)

    cards = [
        ("测试项总数", str(test_count), "项"),
        ("平均响应时间", f"{avg_mean:.2f}", "ms"),
        ("总吞吐量", f"{total_qps:.0f}", "QPS"),
        ("快速项", str(fast_count), "项"),
    ]

    html = ""
    for label, value, unit in cards:
        html += f"""
        <div class="summary-card">
            <div class="label">{label}</div>
            <div class="value">{value}<span class="unit"> {unit}</span></div>
        </div>
        """
    return html


def _generate_category_tabs(categories: List[str]) -> str:
    """生成分类标签"""
    html = ""
    for i, cat in enumerate(categories):
        active = "active" if i == 0 else ""
        html += f'<div class="category-tab {active}" data-category="{cat}" onclick="showCategory(\'{cat}\')">{cat}</div>'
    return html


def _generate_test_table(category: str, items: Dict[str, Dict[str, Any]]) -> str:
    """生成测试结果表格"""
    if not items:
        return ""

    # 计算最大值用于归一化柱状图
    all_means = [r.get("mean_ms", 0) for r in items.values()]
    max_mean = max(all_means) if all_means else 1

    rows = ""
    for name, data in sorted(items.items()):
        mean_ms = data.get("mean_ms", 0)
        p95 = data.get("p95_ms", 0)
        p99 = data.get("p99_ms", 0)
        count = data.get("count", 0)
        qps = data.get("qps", 0)

        # 状态
        status_class, status_text = _get_status(mean_ms)

        # 柱状图宽度
        bar_width = (mean_ms / max_mean * 100) if max_mean > 0 else 0
        bar_class = "fast" if status_class == "fast" else ("medium" if status_class == "medium" else "slow")

        rows += f"""
        <tr>
            <td><code>{name}</code></td>
            <td>{count}</td>
            <td class="bar-cell">
                <div class="bar-container">
                    <div class="bar-fill {bar_class}" style="width: {bar_width:.1f}%"></div>
                    <span class="bar-label">{mean_ms:.3f} ms</span>
                </div>
            </td>
            <td>{p95:.3f} ms</td>
            <td>{p99:.3f} ms</td>
            <td>{qps:,.1f}</td>
            <td><span class="status-badge status-{status_class}">{status_text}</span></td>
        </tr>
        """

    return f"""
    <table>
        <thead>
            <tr>
                <th>测试项</th>
                <th>次数</th>
                <th>平均耗时</th>
                <th>P95</th>
                <th>P99</th>
                <th>QPS</th>
                <th>状态</th>
            </tr>
        </thead>
        <tbody>
            {rows}
        </tbody>
    </table>
    """


def _generate_test_sections(results: Dict[str, Dict[str, Any]]) -> tuple:
    """生成测试分类和内容"""
    # 按分类组织结果
    categories_data: Dict[str, Dict[str, Dict[str, Any]]] = {}
    for name, data in results.items():
        cat = _get_category(name)
        if cat not in categories_data:
            categories_data[cat] = {}
        categories_data[cat][name] = data

    categories = list(categories_data.keys())
    tabs_html = _generate_category_tabs(categories)

    sections_html = ""
    for i, cat in enumerate(categories):
        active = "active" if i == 0 else ""
        table_html = _generate_test_table(cat, categories_data[cat])
        sections_html += f"""
        <div class="test-group {active}" data-category="{cat}">
            {table_html}
        </div>
        """

    return tabs_html, sections_html


def _generate_memory_section(memory_results: Dict[str, Dict[str, Any]]) -> str:
    """生成内存测试部分"""
    if not memory_results:
        return ""

    cards = ""
    for name, data in memory_results.items():
        current_mb = data.get("current_mb", 0)
        peak_mb = data.get("peak_mb", 0)
        cards += f"""
        <div class="memory-card">
            <h4>{name}</h4>
            <div class="metric-row">
                <span class="metric-label">内存增长</span>
                <span class="metric-value">{current_mb:.3f} MB</span>
            </div>
            <div class="metric-row">
                <span class="metric-label">峰值内存</span>
                <span class="metric-value">{peak_mb:.3f} MB</span>
            </div>
        </div>
        """

    return f"""
    <section>
        <h2>内存使用测试</h2>
        <div class="memory-section">
            {cards}
        </div>
    </section>
    """


def generate_html_report(
    results: Dict[str, Dict[str, Any]],
    memory_results: Optional[Dict[str, Dict[str, Any]]] = None,
    environment: str = "production",
) -> str:
    """生成 HTML 性能报告

    Args:
        results: 性能测试结果字典 {name: {mean_ms, p95_ms, ...}}
        memory_results: 内存测试结果 {name: {current_mb, peak_mb, ...}}
        environment: 环境标识

    Returns:
        HTML 字符串
    """
    generated_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    total_tests = len(results)

    summary_cards = _generate_summary_cards(results)
    tabs_html, sections_html = _generate_test_sections(results)
    memory_section = _generate_memory_section(memory_results or {})

    # 使用简单的字符串替换，避免与 CSS 中的 {} 冲突
    html = HTML_TEMPLATE
    replacements = {
        "{{generated_at}}": generated_at,
        "{{total_tests}}": str(total_tests),
        "{{environment}}": environment,
        "{{summary_cards}}": summary_cards,
        "{{category_tabs}}": tabs_html,
        "{{test_sections}}": sections_html,
        "{{memory_section}}": memory_section,
    }
    for placeholder, value in replacements.items():
        html = html.replace(placeholder, value)

    return html


# ============================================================
# JSON 报告
# ============================================================

def generate_json_report(
    results: Dict[str, Dict[str, Any]],
    memory_results: Optional[Dict[str, Dict[str, Any]]] = None,
    metadata: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """生成 JSON 格式报告

    Args:
        results: 性能测试结果
        memory_results: 内存测试结果
        metadata: 元数据

    Returns:
        报告字典
    """
    return {
        "generated_at": datetime.now().isoformat(),
        "metadata": metadata or {},
        "total_tests": len(results),
        "results": results,
        "memory_results": memory_results or {},
    }


# ============================================================
# 命令行入口
# ============================================================

def main():
    """命令行入口：从 JSON 结果生成 HTML 报告"""
    import sys

    if len(sys.argv) < 3:
        print("用法: python report.py <input_json> <output_html>")
        print("  input_json:  性能测试结果 JSON 文件")
        print("  output_html: 输出 HTML 报告路径")
        return

    input_path = sys.argv[1]
    output_path = sys.argv[2]

    try:
        with open(input_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        results = data.get("results", {})
        memory = data.get("memory_results", {})

        html = generate_html_report(results, memory)

        with open(output_path, "w", encoding="utf-8") as f:
            f.write(html)

        print(f"报告已生成: {output_path}")
    except Exception as e:
        print(f"生成报告失败: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
