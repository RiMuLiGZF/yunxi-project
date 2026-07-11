"""ResultRenderer 结果渲染器.

【v3.10.0 新增】将 M7 执行的原始输出转化为用户友好的展示格式。

支持4种输出类型的渲染：
1. 文本输出：格式化 + 关键字高亮 + 长输出折叠
2. 表格输出：自动检测表格 + 数据摘要 + 行列统计
3. 图表输出：图片展示 + 图表说明 + 下载支持
4. 错误输出：AI 人话翻译 + 修复建议 + 修复前后对比
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

import structlog
from pydantic import BaseModel, Field

from skill_cluster.code_execution_bridge import (
    ExecutionResult,
    ExecutionStatus,
    ErrorType,
)

logger = structlog.get_logger()


class RenderedOutput(BaseModel):
    """渲染后的输出."""

    output_type: str = Field(..., description="输出类型: text/table/image/error/mixed")
    content: str = Field(..., description="渲染后的内容（Markdown格式）")
    summary: str = Field(default="", description="一句话摘要")
    highlights: list[str] = Field(default_factory=list, description="高亮的关键信息")
    has_more: bool = Field(default=False, description="是否有折叠内容")
    suggestion: str | None = Field(default=None, description="下一步建议")


# ============================================================
# 文本渲染器
# ============================================================


class TextRenderer:
    """纯文本输出渲染器."""

    MAX_PREVIEW_LINES = 30
    MAX_PREVIEW_CHARS = 2000

    def render(self, stdout: str, stderr: str = "") -> RenderedOutput:
        """渲染文本输出."""
        lines = stdout.strip().splitlines()
        total_lines = len(lines)
        total_chars = len(stdout)

        # 判断是否需要折叠
        needs_fold = total_lines > self.MAX_PREVIEW_LINES or total_chars > self.MAX_PREVIEW_CHARS

        if needs_fold:
            preview_lines = lines[: self.MAX_PREVIEW_LINES]
            content = "\n".join(preview_lines)
            content += f"\n\n... (已折叠 {total_lines - self.MAX_PREVIEW_LINES} 行，共 {total_chars} 字符)"
            has_more = True
        else:
            content = stdout.strip()
            has_more = False

        # 提取关键信息（数字、百分比、关键结果）
        highlights = self._extract_highlights(stdout)

        # 生成摘要
        summary = self._generate_summary(stdout, total_lines)

        # 加上 stderr
        if stderr.strip():
            content += f"\n\n**警告输出：**\n```\n{stderr.strip()}\n```"

        return RenderedOutput(
            output_type="text",
            content=content,
            summary=summary,
            highlights=highlights,
            has_more=has_more,
        )

    def _extract_highlights(self, text: str) -> list[str]:
        """提取关键信息."""
        highlights: list[str] = []

        # 数字结果
        numbers = re.findall(r"(?:结果|答案|输出|result|answer|sum|total|count)\s*[:=]\s*[\d.]+", text, re.IGNORECASE)
        highlights.extend(numbers[:3])

        # 百分比
        percentages = re.findall(r"\d+(?:\.\d+)?%", text)
        if percentages:
            highlights.append(f"包含 {len(percentages)} 个百分比数据")

        # 成功/失败标记
        if re.search(r"(成功|success|passed|ok)\s*[:：]?\s*\d+", text, re.IGNORECASE):
            highlights.append("包含成功统计")
        if re.search(r"(失败|error|failed|fail)\s*[:：]?\s*\d+", text, re.IGNORECASE):
            highlights.append("包含失败统计")

        return highlights[:5]

    def _generate_summary(self, text: str, line_count: int) -> str:
        """生成一句话摘要."""
        if not text.strip():
            return "无输出"

        first_line = text.strip().splitlines()[0][:80]
        if line_count == 1:
            return f"1行输出: {first_line}"
        elif line_count <= 10:
            return f"{line_count}行输出，首行: {first_line}"
        else:
            return f"{line_count}行输出，共 {len(text)} 字符"


# ============================================================
# 表格渲染器
# ============================================================


class TableRenderer:
    """表格数据渲染器."""

    def render(self, stdout: str, tables: list[dict] | None = None) -> RenderedOutput:
        """渲染表格输出."""
        parsed_tables = tables or self._parse_tables(stdout)

        if not parsed_tables:
            # 不是表格，降级为文本
            return TextRenderer().render(stdout)

        content_parts = []
        all_highlights: list[str] = []

        for i, table in enumerate(parsed_tables):
            rendered = self._render_single_table(table, i)
            content_parts.append(rendered["content"])
            all_highlights.extend(rendered["highlights"])

        content = "\n\n".join(content_parts)
        summary = f"包含 {len(parsed_tables)} 个表格数据"

        return RenderedOutput(
            output_type="table",
            content=content,
            summary=summary,
            highlights=all_highlights[:5],
            has_more=False,
        )

    def _parse_tables(self, text: str) -> list[dict]:
        """从文本中解析表格."""
        tables: list[dict] = []

        # Markdown 表格
        md_table_pattern = r"\|.+\|\n\|[-:|]+\|\n(?:\|.+\|\n?)+"
        for match in re.finditer(md_table_pattern, text):
            table_text = match.group()
            table = self._parse_md_table(table_text)
            if table:
                tables.append(table)

        # CSV 格式
        lines = text.strip().splitlines()
        if len(lines) >= 2 and all("," in line for line in lines[:5]):
            csv_table = self._parse_csv_table(lines)
            if csv_table and csv_table["rows"] >= 2:
                tables.append(csv_table)

        return tables

    def _parse_md_table(self, text: str) -> dict | None:
        lines = text.strip().splitlines()
        if len(lines) < 2:
            return None

        headers = [c.strip() for c in lines[0].strip("|").split("|")]
        rows = []
        for line in lines[2:]:  # 跳过分隔线
            if line.strip():
                row = [c.strip() for c in line.strip("|").split("|")]
                rows.append(row)

        return {
            "headers": headers,
            "rows_data": rows,
            "rows": len(rows),
            "cols": len(headers),
        }

    def _parse_csv_table(self, lines: list[str]) -> dict | None:
        try:
            import csv
            import io
            reader = csv.reader(io.StringIO("\n".join(lines[:100])))
            all_rows = list(reader)
            if not all_rows:
                return None
            headers = all_rows[0]
            rows_data = all_rows[1:]
            return {
                "headers": headers,
                "rows_data": rows_data[:50],
                "rows": len(rows_data),
                "cols": len(headers),
            }
        except Exception:
            return None

    def _render_single_table(self, table: dict, index: int) -> dict:
        """渲染单个表格."""
        headers = table["headers"]
        rows = table["rows_data"]
        total_rows = table["rows"]
        cols = table["cols"]

        highlights: list[str] = [f"表格 {index+1}: {total_rows} 行 × {cols} 列"]

        # 限制展示行数
        max_display = 10
        display_rows = rows[:max_display]
        has_more = total_rows > max_display

        # 生成 Markdown 表格
        lines = []
        lines.append("| " + " | ".join(headers) + " |")
        lines.append("|" + "|".join(["---"] * len(headers)) + "|")
        for row in display_rows:
            # 补齐列数
            row_padded = row + [""] * (len(headers) - len(row))
            lines.append("| " + " | ".join(str(c) for c in row_padded[:len(headers)]) + " |")

        if has_more:
            lines.append(f"\n*... 还有 {total_rows - max_display} 行已折叠*")

        # 数据摘要
        summary_stats = self._calc_table_stats(rows, headers)
        if summary_stats:
            highlights.append(summary_stats)

        return {
            "content": "\n".join(lines),
            "highlights": highlights,
        }

    def _calc_table_stats(self, rows: list[list], headers: list[str]) -> str:
        """计算表格统计摘要."""
        if not rows:
            return ""

        # 尝试找数值列
        numeric_cols = []
        for col_idx in range(min(len(headers), len(rows[0]) if rows else 0)):
            values = []
            for row in rows[:20]:
                if col_idx < len(row):
                    try:
                        values.append(float(row[col_idx]))
                    except (ValueError, TypeError):
                        pass
            if len(values) >= 3:
                numeric_cols.append((col_idx, values))

        if not numeric_cols:
            return ""

        col_idx, values = numeric_cols[0]
        col_name = headers[col_idx] if col_idx < len(headers) else f"列{col_idx+1}"
        return f"{col_name}: 均值={sum(values)/len(values):.2f}, 最大={max(values):.2f}, 最小={min(values):.2f}"


# ============================================================
# 图表渲染器
# ============================================================


class ChartRenderer:
    """图表输出渲染器."""

    def render(self, images: list[bytes] | None = None, stdout: str = "") -> RenderedOutput:
        """渲染图表输出."""
        if not images and not stdout:
            return RenderedOutput(
                output_type="image",
                content="*(未生成图表)*",
                summary="图表生成失败",
            )

        image_count = len(images) if images else 0

        content_parts = []
        if image_count > 0:
            content_parts.append(f"**生成了 {image_count} 张图表：**")
            for i in range(image_count):
                content_parts.append(f"\n图表 {i+1}: (图片数据)")
            content_parts.append("\n*提示：可下载原始图片，或继续调整样式*")

        if stdout.strip():
            content_parts.append(f"\n**代码输出：**\n```\n{stdout[:500]}\n```")

        summary = f"生成 {image_count} 张图表" if image_count > 0 else "图表代码已执行"

        return RenderedOutput(
            output_type="image",
            content="\n".join(content_parts),
            summary=summary,
            highlights=[f"图表数量: {image_count}"],
            suggestion="可以调整颜色、标题、坐标轴等样式",
        )


# ============================================================
# 错误渲染器
# ============================================================


class ErrorRenderer:
    """错误输出渲染器.

    将技术错误信息转化为用户友好的解释。
    """

    # 常见错误的人话解释
    ERROR_EXPLANATIONS: dict[ErrorType, str] = {
        ErrorType.SYNTAX_ERROR: "代码有语法错误，可能是括号不匹配、缺少冒号或缩进不正确。",
        ErrorType.IMPORT_ERROR: "缺少需要的依赖库，需要先安装对应的软件包。",
        ErrorType.RUNTIME_ERROR: "代码运行时出错，可能是数据类型不对、变量不存在或索引越界。",
        ErrorType.TIMEOUT: "代码执行时间过长，可能有死循环或计算量太大。",
        ErrorType.MEMORY_ERROR: "内存不足，数据量太大了，需要优化算法或减少数据量。",
        ErrorType.SECURITY_ERROR: "代码包含不安全的操作，已被安全系统拦截。",
        ErrorType.UNKNOWN: "代码执行出错，具体原因需要查看错误信息。",
    }

    # 修复建议
    FIX_SUGGESTIONS: dict[ErrorType, list[str]] = {
        ErrorType.SYNTAX_ERROR: [
            "检查括号、引号是否配对",
            "检查缩进是否正确（Python用4个空格）",
            "检查每行末尾是否缺少冒号",
            "检查关键字拼写是否正确",
        ],
        ErrorType.IMPORT_ERROR: [
            "用 pip install 安装缺少的库",
            "检查 import 语句的拼写",
            "确认是否在正确的环境中运行",
        ],
        ErrorType.RUNTIME_ERROR: [
            "检查变量是否已定义",
            "检查数据类型是否匹配",
            "检查列表/字典的索引是否正确",
            "添加打印语句调试中间结果",
        ],
        ErrorType.TIMEOUT: [
            "检查是否有死循环",
            "减少数据量试试",
            "优化算法复杂度",
            "可以增加超时时间",
        ],
        ErrorType.MEMORY_ERROR: [
            "减少处理的数据量",
            "分批处理数据",
            "释放不需要的变量",
            "使用更节省内存的数据结构",
        ],
        ErrorType.SECURITY_ERROR: [
            "不要执行未知来源的代码",
            "检查代码是否包含危险操作",
            "确认需要哪些权限再运行",
        ],
        ErrorType.UNKNOWN: [
            "仔细阅读错误信息",
            "逐行检查代码逻辑",
            "用简单测试用例验证",
        ],
    }

    def render(
        self,
        error_type: ErrorType,
        stderr: str,
        fix_history: list[dict] | None = None,
        auto_fixed: bool = False,
    ) -> RenderedOutput:
        """渲染错误输出."""
        explanation = self.ERROR_EXPLANATIONS.get(error_type, "代码执行出错。")
        suggestions = self.FIX_SUGGESTIONS.get(error_type, [])

        content_parts = []

        if auto_fixed:
            content_parts.append("✅ **代码已自动修复并成功运行！**\n")
        else:
            content_parts.append("❌ **代码执行出错**\n")

        # 人话解释
        content_parts.append(f"**问题说明：** {explanation}\n")

        # 错误详情（折叠展示）
        if stderr.strip():
            error_preview = stderr.strip()[:800]
            content_parts.append(f"**错误详情：**\n```\n{error_preview}\n```\n")

        # 修复历史
        if fix_history:
            content_parts.append(f"**修复过程：** 自动尝试了 {len(fix_history)} 次修复\n")
            for i, fix in enumerate(fix_history):
                err = fix.get("error", "")[:100]
                content_parts.append(f"- 第 {i+1} 次: {fix.get('error_type', 'unknown')} - {err}")
            content_parts.append("")

        # 修复建议
        if suggestions and not auto_fixed:
            content_parts.append("**你可以尝试：**\n")
            for i, s in enumerate(suggestions[:4], 1):
                content_parts.append(f"{i}. {s}")
            content_parts.append("")

        content = "\n".join(content_parts)

        summary = f"{'已修复' if auto_fixed else '错误'}: {error_type.value}"
        highlights = [f"错误类型: {error_type.value}"]
        if fix_history:
            highlights.append(f"修复尝试: {len(fix_history)} 次")

        return RenderedOutput(
            output_type="error",
            content=content,
            summary=summary,
            highlights=highlights,
            has_more=len(stderr) > 800,
            suggestion=None if auto_fixed else "需要我帮你修复这段代码吗？",
        )


# ============================================================
# 统一结果渲染器
# ============================================================


class ResultRenderer:
    """统一结果渲染器.

    根据执行结果类型自动选择对应的渲染器。
    """

    def __init__(self) -> None:
        self._text_renderer = TextRenderer()
        self._table_renderer = TableRenderer()
        self._chart_renderer = ChartRenderer()
        self._error_renderer = ErrorRenderer()

    def render(self, result: ExecutionResult) -> RenderedOutput:
        """渲染执行结果."""
        # 错误结果
        if result.status in (ExecutionStatus.FAILED, ExecutionStatus.TIMEOUT, ExecutionStatus.MEMORY_LIMIT, ExecutionStatus.SECURITY_BLOCKED):
            return self._error_renderer.render(
                error_type=result.error_type or ErrorType.UNKNOWN,
                stderr=result.stderr,
                fix_history=result.fix_history,
                auto_fixed=False,
            )

        # 自动修复后成功
        if result.status == ExecutionStatus.FIXED:
            # 先渲染成功结果，再加上修复说明
            success_output = self._render_success(result)
            fix_note = f"\n\n---\n\n💡 **自动修复**：代码有 {len(result.fix_history)} 处问题已自动修复"
            success_output.content += fix_note
            success_output.summary += " (已自动修复)"
            return success_output

        # 成功结果
        return self._render_success(result)

    def _render_success(self, result: ExecutionResult) -> RenderedOutput:
        """渲染成功的执行结果."""
        # 有图片 → 图表
        if result.images:
            return self._chart_renderer.render(result.images, result.stdout)

        # 有表格数据 → 表格
        if result.tables:
            return self._table_renderer.render(result.stdout, result.tables)

        # 检测 stdout 是否包含表格
        if self._looks_like_table(result.stdout):
            return self._table_renderer.render(result.stdout)

        # 默认文本
        return self._text_renderer.render(result.stdout, result.stderr)

    def _looks_like_table(self, text: str) -> bool:
        """判断输出是否像表格."""
        lines = text.strip().splitlines()
        if len(lines) < 3:
            return False

        # Markdown 表格
        if re.match(r"\|.+\|", lines[0]) and re.match(r"\|[-:|]+\|", lines[1]):
            return True

        # CSV 风格
        first_commas = lines[0].count(",")
        if first_commas >= 2:
            comma_lines = sum(1 for line in lines[:5] if line.count(",") == first_commas)
            if comma_lines >= 3:
                return True

        return False
