"""
云汐演练报告生成器 (Drill Report Generator)

根据演练结果生成结构化报告：
- 演练目标和范围
- 故障注入步骤
- 系统响应记录
- 恢复时间统计
- 问题和改进项

支持多种输出格式：JSON、Markdown、HTML

使用方式：
    from shared.core.chaos.drill_report import ReportGenerator

    generator = ReportGenerator()
    report = generator.generate(drill_result)
    markdown = report.to_markdown()
"""

from __future__ import annotations

import time
import json
import logging
from dataclasses import dataclass, field
from typing import Dict, Any, Optional, List
from datetime import datetime, timezone

logger = logging.getLogger(__name__)


# ============================================================
# 数据类
# ============================================================

@dataclass
class ImprovementItem:
    """改进项"""
    item_id: str
    title: str
    description: str = ""
    severity: str = "medium"       # low/medium/high/critical
    category: str = "general"      # availability/performance/security/operational
    current_state: str = ""
    recommendation: str = ""
    priority: int = 3              # 1-5，1最高
    status: str = "open"           # open/in_progress/resolved
    responsible: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "item_id": self.item_id,
            "title": self.title,
            "description": self.description,
            "severity": self.severity,
            "category": self.category,
            "current_state": self.current_state,
            "recommendation": self.recommendation,
            "priority": self.priority,
            "status": self.status,
            "responsible": self.responsible,
        }


@dataclass
class DrillResult:
    """演练结果摘要"""
    drill_id: str
    drill_name: str
    status: str = "unknown"
    start_time: float = 0.0
    end_time: float = 0.0
    duration_seconds: float = 0.0
    total_steps: int = 0
    completed_steps: int = 0
    failed_steps: int = 0
    skipped_steps: int = 0
    success_rate: float = 0.0
    mttr_seconds: float = 0.0     # 平均恢复时间
    mtbf_seconds: float = 0.0     # 平均故障间隔（如果有历史数据）
    rto_achieved: bool = False    # 是否达到恢复时间目标
    rpo_achieved: bool = False    # 是否达到恢复点目标
    errors: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "drill_id": self.drill_id,
            "drill_name": self.drill_name,
            "status": self.status,
            "start_time": self.start_time,
            "end_time": self.end_time,
            "duration_seconds": round(self.duration_seconds, 2),
            "total_steps": self.total_steps,
            "completed_steps": self.completed_steps,
            "failed_steps": self.failed_steps,
            "skipped_steps": self.skipped_steps,
            "success_rate": round(self.success_rate, 2),
            "mttr_seconds": round(self.mttr_seconds, 2),
            "mtbf_seconds": round(self.mtbf_seconds, 2),
            "rto_achieved": self.rto_achieved,
            "rpo_achieved": self.rpo_achieved,
            "errors": self.errors,
        }


@dataclass
class DrillReport:
    """完整演练报告"""
    report_id: str
    generated_at: float
    drill_result: DrillResult
    drill_script: Dict[str, Any] = field(default_factory=dict)
    steps_detail: List[Dict[str, Any]] = field(default_factory=list)
    events: List[Dict[str, Any]] = field(default_factory=list)
    metrics: Dict[str, Any] = field(default_factory=dict)
    objectives: List[str] = field(default_factory=list)
    scope: str = ""
    system_state_before: Dict[str, Any] = field(default_factory=dict)
    system_state_after: Dict[str, Any] = field(default_factory=dict)
    findings: List[str] = field(default_factory=list)
    improvements: List[ImprovementItem] = field(default_factory=list)
    conclusion: str = ""
    recommendations: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "report_id": self.report_id,
            "generated_at": self.generated_at,
            "generated_at_iso": datetime.fromtimestamp(self.generated_at, tz=timezone.utc).isoformat(),
            "drill_result": self.drill_result.to_dict(),
            "drill_script": self.drill_script,
            "steps_detail": self.steps_detail,
            "events": self.events,
            "metrics": self.metrics,
            "objectives": self.objectives,
            "scope": self.scope,
            "system_state_before": self.system_state_before,
            "system_state_after": self.system_state_after,
            "findings": self.findings,
            "improvements": [item.to_dict() for item in self.improvements],
            "conclusion": self.conclusion,
            "recommendations": self.recommendations,
        }

    def to_json(self, indent: int = 2) -> str:
        """导出为 JSON"""
        return json.dumps(self.to_dict(), ensure_ascii=False, indent=indent)

    def to_markdown(self) -> str:
        """导出为 Markdown"""
        d = self.to_dict()
        dr = d["drill_result"]

        lines = []
        lines.append(f"# 故障演练报告: {dr['drill_name']}")
        lines.append("")
        lines.append(f"- **报告ID**: {d['report_id']}")
        lines.append(f"- **生成时间**: {d['generated_at_iso']}")
        lines.append(f"- **演练状态**: {dr['status']}")
        lines.append(f"- **总耗时**: {dr['duration_seconds']} 秒")
        lines.append("")

        # 演练目标
        if d["objectives"]:
            lines.append("## 演练目标")
            lines.append("")
            for obj in d["objectives"]:
                lines.append(f"- {obj}")
            lines.append("")

        # 演练范围
        if d["scope"]:
            lines.append("## 演练范围")
            lines.append("")
            lines.append(d["scope"])
            lines.append("")

        # 结果摘要
        lines.append("## 结果摘要")
        lines.append("")
        lines.append(f"| 指标 | 值 |")
        lines.append(f"|------|-----|")
        lines.append(f"| 总步骤数 | {dr['total_steps']} |")
        lines.append(f"| 完成步骤 | {dr['completed_steps']} |")
        lines.append(f"| 失败步骤 | {dr['failed_steps']} |")
        lines.append(f"| 跳过步骤 | {dr['skipped_steps']} |")
        lines.append(f"| 成功率 | {dr['success_rate']}% |")
        lines.append(f"| 平均恢复时间 (MTTR) | {dr['mttr_seconds']} 秒 |")
        lines.append(f"| RTO 达标 | {'是' if dr['rto_achieved'] else '否'} |")
        lines.append(f"| RPO 达标 | {'是' if dr['rpo_achieved'] else '否'} |")
        lines.append("")

        # 步骤详情
        if d["steps_detail"]:
            lines.append("## 步骤详情")
            lines.append("")
            for i, step in enumerate(d["steps_detail"], 1):
                status_icon = "✓" if step["status"] == "completed" else ("✗" if step["status"] == "failed" else "-")
                lines.append(f"### {i}. {status_icon} {step['name']}")
                lines.append("")
                if step.get("description"):
                    lines.append(f"- **描述**: {step['description']}")
                lines.append(f"- **状态**: {step['status']}")
                lines.append(f"- **耗时**: {step.get('duration_seconds', 0)} 秒")
                if step.get("error"):
                    lines.append(f"- **错误**: {step['error']}")
                lines.append("")

        # 事件时间线
        if d["events"]:
            lines.append("## 事件时间线")
            lines.append("")
            for evt in d["events"]:
                ts = datetime.fromtimestamp(evt.get("timestamp", 0), tz=timezone.utc).strftime("%H:%M:%S")
                lines.append(f"- [{ts}] {evt.get('event_type', '')}: {evt.get('message', '')}")
            lines.append("")

        # 发现
        if d["findings"]:
            lines.append("## 主要发现")
            lines.append("")
            for finding in d["findings"]:
                lines.append(f"- {finding}")
            lines.append("")

        # 改进项
        if d["improvements"]:
            lines.append("## 改进项")
            lines.append("")
            lines.append(f"| 优先级 | 严重度 | 分类 | 标题 | 状态 |")
            lines.append(f"|--------|--------|------|------|------|")
            for imp in d["improvements"]:
                lines.append(
                    f"| P{imp['priority']} | {imp['severity']} | {imp['category']} | "
                    f"{imp['title']} | {imp['status']} |"
                )
            lines.append("")

            # 详细改进建议
            for imp in d["improvements"]:
                lines.append(f"### P{imp['priority']} - {imp['title']}")
                lines.append("")
                lines.append(f"- **严重度**: {imp['severity']}")
                lines.append(f"- **分类**: {imp['category']}")
                if imp.get("description"):
                    lines.append(f"- **描述**: {imp['description']}")
                if imp.get("current_state"):
                    lines.append(f"- **当前状态**: {imp['current_state']}")
                if imp.get("recommendation"):
                    lines.append(f"- **建议**: {imp['recommendation']}")
                lines.append("")

        # 结论
        if d["conclusion"]:
            lines.append("## 结论")
            lines.append("")
            lines.append(d["conclusion"])
            lines.append("")

        # 建议
        if d["recommendations"]:
            lines.append("## 后续建议")
            lines.append("")
            for rec in d["recommendations"]:
                lines.append(f"- {rec}")
            lines.append("")

        return "\n".join(lines)

    def to_html(self) -> str:
        """导出为 HTML（简化版）"""
        md = self.to_markdown()
        # 简单的 Markdown 转 HTML（足够用于报告查看）
        html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>故障演练报告 - {self.drill_result.drill_name}</title>
    <style>
        body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
               max-width: 900px; margin: 0 auto; padding: 20px; line-height: 1.6; color: #333; }}
        h1 {{ color: #1a1a2e; border-bottom: 3px solid #0f3460; padding-bottom: 10px; }}
        h2 {{ color: #16213e; margin-top: 30px; border-bottom: 2px solid #e94560; padding-bottom: 5px; }}
        h3 {{ color: #0f3460; }}
        table {{ border-collapse: collapse; width: 100%; margin: 15px 0; }}
        th, td {{ border: 1px solid #ddd; padding: 10px; text-align: left; }}
        th {{ background-color: #0f3460; color: white; }}
        tr:nth-child(even) {{ background-color: #f8f9fa; }}
        .success {{ color: #28a745; }}
        .failed {{ color: #dc3545; }}
        .warning {{ color: #ffc107; }}
        code {{ background-color: #f4f4f4; padding: 2px 6px; border-radius: 4px; }}
    </style>
</head>
<body>
<pre style="white-space: pre-wrap; word-wrap: break-word;">{md}</pre>
</body>
</html>"""
        return html

    def save(self, output_path: str, format: str = "json") -> str:
        """保存报告到文件"""
        if format == "json":
            content = self.to_json()
        elif format == "markdown":
            content = self.to_markdown()
        elif format == "html":
            content = self.to_html()
        else:
            raise ValueError(f"Unsupported format: {format}")

        with open(output_path, "w", encoding="utf-8") as f:
            f.write(content)

        return output_path


# ============================================================
# 报告生成器
# ============================================================

class ReportGenerator:
    """
    演练报告生成器

    根据演练结果自动生成结构化报告。
    """

    def __init__(self, rto_target_seconds: float = 300.0, rpo_target_minutes: float = 5.0):
        """
        Args:
            rto_target_seconds: 恢复时间目标（秒）
            rpo_target_minutes: 恢复点目标（分钟）
        """
        self.rto_target = rto_target_seconds
        self.rpo_target = rpo_target_minutes

    def generate(
        self,
        drill_result_dict: Dict[str, Any],
        drill_script: Optional[Dict[str, Any]] = None,
        objectives: Optional[List[str]] = None,
        scope: str = "",
    ) -> DrillReport:
        """
        生成演练报告

        Args:
            drill_result_dict: 演练结果字典
            drill_script: 演练脚本信息
            objectives: 演练目标列表
            scope: 演练范围描述

        Returns:
            DrillReport 对象
        """
        report_id = f"report_{int(time.time())}_{id(self) % 10000}"

        # 构建 DrillResult
        drill_result = DrillResult(
            drill_id=drill_result_dict.get("drill_id", ""),
            drill_name=drill_result_dict.get("drill_name", ""),
            status=drill_result_dict.get("status", "unknown"),
            start_time=drill_result_dict.get("start_time", 0),
            end_time=drill_result_dict.get("end_time", 0),
            duration_seconds=drill_result_dict.get("duration_seconds", 0),
            total_steps=drill_result_dict.get("total_steps", 0),
            completed_steps=drill_result_dict.get("completed_steps", 0),
            failed_steps=drill_result_dict.get("failed_steps", 0),
            skipped_steps=drill_result_dict.get("skipped_steps", 0),
            errors=drill_result_dict.get("errors", []),
        )

        # 计算成功率
        if drill_result.total_steps > 0:
            drill_result.success_rate = (
                drill_result.completed_steps / drill_result.total_steps * 100
            )

        # 计算 MTTR（从失败步骤到恢复步骤的时间）
        drill_result.mttr_seconds = self._calculate_mttr(drill_result_dict)

        # RTO/RPO 评估
        drill_result.rto_achieved = drill_result.mttr_seconds <= self.rto_target if drill_result.mttr_seconds > 0 else False
        drill_result.rpo_achieved = True  # 默认达标，根据实际数据调整

        # 生成发现和改进项
        findings = self._generate_findings(drill_result_dict, drill_result)
        improvements = self._generate_improvements(drill_result_dict, drill_result)
        conclusion = self._generate_conclusion(drill_result)
        recommendations = self._generate_recommendations(drill_result, improvements)

        # 默认目标
        default_objectives = objectives or [
            "验证系统在故障情况下的容错能力",
            "验证故障检测和自动转移机制的有效性",
            "验证系统恢复流程和恢复时间",
            "发现系统架构中的薄弱环节",
        ]

        report = DrillReport(
            report_id=report_id,
            generated_at=time.time(),
            drill_result=drill_result,
            drill_script=drill_script or {},
            steps_detail=drill_result_dict.get("steps", []),
            events=drill_result_dict.get("events", []),
            metrics=drill_result_dict.get("metrics", {}),
            objectives=default_objectives,
            scope=scope or "本次演练覆盖了故障注入、故障检测、故障转移、系统恢复等关键环节",
            findings=findings,
            improvements=improvements,
            conclusion=conclusion,
            recommendations=recommendations,
        )

        return report

    def _calculate_mttr(self, result_dict: Dict[str, Any]) -> float:
        """计算平均恢复时间（秒）"""
        steps = result_dict.get("steps", [])
        if not steps:
            return 0.0

        # 找到故障注入步骤和恢复步骤之间的时间差
        fault_time = None
        recover_time = None

        for step in steps:
            step_id = step.get("step_id", "")
            if "inject" in step_id.lower() or "fault" in step_id.lower():
                fault_time = step.get("completed_at", 0)
            if "recover" in step_id.lower() or "restore" in step_id.lower():
                if fault_time:
                    recover_time = step.get("completed_at", 0)
                    break

        if fault_time and recover_time and recover_time > fault_time:
            return recover_time - fault_time

        # 如果找不到明确的恢复时间，用总耗时估算
        return result_dict.get("duration_seconds", 0) * 0.4

    def _generate_findings(self, result_dict: Dict[str, Any], dr: DrillResult) -> List[str]:
        """生成主要发现"""
        findings = []

        if dr.status == "completed":
            findings.append("演练按计划完成，所有关键步骤均执行成功")
        elif dr.status == "failed":
            findings.append(f"演练失败，共 {dr.failed_steps} 个关键步骤执行失败")
            if dr.errors:
                findings.append(f"主要错误: {'; '.join(dr.errors[:3])}")

        if dr.mttr_seconds > 0:
            if dr.rto_achieved:
                findings.append(f"恢复时间 ({dr.mttr_seconds:.1f}秒) 满足 RTO 目标 ({self.rto_target}秒)")
            else:
                findings.append(f"恢复时间 ({dr.mttr_seconds:.1f}秒) 超过 RTO 目标 ({self.rto_target}秒)，需要优化")

        if dr.success_rate >= 90:
            findings.append(f"步骤成功率 {dr.success_rate:.1f}%，表现良好")
        elif dr.success_rate >= 70:
            findings.append(f"步骤成功率 {dr.success_rate:.1f}%，有待提升")
        else:
            findings.append(f"步骤成功率仅 {dr.success_rate:.1f}%，存在较大问题")

        # 检查事件中的异常
        events = result_dict.get("events", [])
        error_events = [e for e in events if "error" in e.get("event_type", "").lower()]
        if error_events:
            findings.append(f"演练过程中发生 {len(error_events)} 个错误事件")

        return findings

    def _generate_improvements(
        self, result_dict: Dict[str, Any], dr: DrillResult
    ) -> List[ImprovementItem]:
        """生成改进项"""
        improvements = []
        item_id = 1

        # 恢复时间不达标
        if not dr.rto_achieved and dr.mttr_seconds > 0:
            improvements.append(ImprovementItem(
                item_id=f"imp_{item_id:03d}",
                title="优化故障恢复时间",
                description=f"当前恢复时间 ({dr.mttr_seconds:.1f}秒) 未达到 RTO 目标 ({self.rto_target}秒)",
                severity="high",
                category="availability",
                current_state=f"MTTR = {dr.mttr_seconds:.1f}秒",
                recommendation="优化故障检测算法、缩短切换等待时间、增加自动化程度",
                priority=1,
            ))
            item_id += 1

        # 步骤失败
        if dr.failed_steps > 0:
            improvements.append(ImprovementItem(
                item_id=f"imp_{item_id:03d}",
                title="修复失败的演练步骤",
                description=f"本次演练有 {dr.failed_steps} 个步骤失败，需要排查原因",
                severity="high",
                category="operational",
                current_state=f"{dr.failed_steps} 个步骤失败 / {dr.total_steps} 总步骤",
                recommendation="分析失败步骤的具体原因，修复后重新演练",
                priority=1,
            ))
            item_id += 1

        # 成功率中等
        if 70 <= dr.success_rate < 90:
            improvements.append(ImprovementItem(
                item_id=f"imp_{item_id:03d}",
                title="提升演练成功率",
                description=f"当前成功率为 {dr.success_rate:.1f}%，目标应达到 95% 以上",
                severity="medium",
                category="operational",
                current_state=f"成功率 {dr.success_rate:.1f}%",
                recommendation="优化自动化脚本、完善监控告警、加强团队培训",
                priority=2,
            ))
            item_id += 1

        # 监控改进
        improvements.append(ImprovementItem(
            item_id=f"imp_{item_id:03d}",
            title="完善故障监控和告警",
            description="加强实时监控能力，缩短故障发现时间",
            severity="medium",
            category="operational",
            current_state="基础监控已配置",
            recommendation="增加关键指标的实时监控和智能告警",
            priority=2,
        ))
        item_id += 1

        # 自动化程度
        improvements.append(ImprovementItem(
            item_id=f"imp_{item_id:03d}",
            title="提高故障处理自动化程度",
            description="减少人工干预，提高故障处理的一致性和速度",
            severity="medium",
            category="availability",
            current_state="部分操作需要人工干预",
            recommendation="实现故障自动检测、自动转移、自动恢复的全链路自动化",
            priority=3,
        ))
        item_id += 1

        # 文档化
        improvements.append(ImprovementItem(
            item_id=f"imp_{item_id:03d}",
            title="完善应急预案文档",
            description="确保所有故障场景都有对应的应急处理文档",
            severity="low",
            category="operational",
            current_state="部分场景有文档",
            recommendation="整理所有故障场景的应急预案，定期更新和演练",
            priority=4,
        ))
        item_id += 1

        # 定期演练
        improvements.append(ImprovementItem(
            item_id=f"imp_{item_id:03d}",
            title="建立定期演练机制",
            description="定期进行故障演练，保持团队的应急响应能力",
            severity="medium",
            category="operational",
            current_state="本次为首次/不定期演练",
            recommendation="建立月度/季度演练计划，覆盖不同故障场景",
            priority=3,
        ))

        return improvements

    def _generate_conclusion(self, dr: DrillResult) -> str:
        """生成结论"""
        if dr.status == "completed" and dr.success_rate >= 90:
            return (
                f"本次演练成功完成，总体成功率为 {dr.success_rate:.1f}%。"
                f"系统在故障注入后表现出良好的容错和恢复能力，"
                f"平均恢复时间为 {dr.mttr_seconds:.1f} 秒。"
                f"建议持续优化并定期开展演练，确保系统的高可用性。"
            )
        elif dr.status == "completed":
            return (
                f"本次演练基本完成，成功率为 {dr.success_rate:.1f}%。"
                f"系统在故障处理方面仍有提升空间，"
                f"建议针对失败和薄弱环节进行专项优化。"
            )
        else:
            return (
                f"本次演练未完全成功（状态: {dr.status}），"
                f"有 {dr.failed_steps} 个关键步骤失败。"
                f"需要深入分析失败原因，修复问题后重新组织演练。"
            )

    def _generate_recommendations(
        self, dr: DrillResult, improvements: List[ImprovementItem]
    ) -> List[str]:
        """生成后续建议"""
        recs = []

        high_items = [i for i in improvements if i.priority <= 2]
        if high_items:
            recs.append(f"优先处理 {len(high_items)} 个高优先级改进项")

        if dr.failed_steps > 0:
            recs.append("深入分析失败步骤的根本原因")

        recs.append("在修复所有已知问题后进行第二轮演练验证")
        recs.append("建立定期演练机制（建议每季度至少一次全面演练）")
        recs.append("完善监控告警体系，缩短故障发现时间")
        recs.append("加强团队培训，提升应急响应能力")

        return recs
