"""
云汐内核 - 多 Agent 集群调度系统
复盘 Agent 模块

负责成长复盘、目标追踪、进度分析、周期性报告生成。
"""

from __future__ import annotations

import time
from typing import Any

import structlog
from src.tools.interfaces import AgentTask, AgentResult, IAgentPlugin

logger = structlog.get_logger(__name__)


class ReviewAgent(IAgentPlugin):
    """复盘 Agent

    基于时间范围汇总笔记、情绪、开发活动，生成成长复盘摘要，
    支持目标追踪与周期性报告生成。
    """

    agent_id: str = "agent.review"
    version: str = "1.0.0"
    capabilities: list[str] = [
        "review.summary",
        "review.goal",
        "review.report",
    ]

    def __init__(self) -> None:
        self._logger = logger.bind(agent_id=self.agent_id)
        self._goals: list[dict[str, Any]] = []
        self._reviews: list[dict[str, Any]] = []

    async def handle_task(self, task: AgentTask) -> AgentResult:
        """处理复盘相关任务"""
        start_time = time.time()
        intent = task.intent
        payload = task.payload

        self._logger.info(
            "handling_task",
            trace_id=task.trace_id,
            task_id=task.task_id,
            intent=intent,
        )

        try:
            if intent == "review.summary":
                result = await self._handle_summary(payload)
            elif intent == "review.goal":
                result = await self._handle_goal(payload)
            elif intent == "review.report":
                result = await self._handle_report(payload)
            else:
                return AgentResult(
                    task_id=task.task_id,
                    trace_id=task.trace_id,
                    agent_id=self.agent_id,
                    status="failure",
                    error=f"Unknown intent: {intent}",
                    latency_ms=(time.time() - start_time) * 1000,
                )

            latency_ms = (time.time() - start_time) * 1000
            return AgentResult(
                task_id=task.task_id,
                trace_id=task.trace_id,
                agent_id=self.agent_id,
                status="success",
                output=result,
                latency_ms=latency_ms,
            )

        except Exception as exc:
            latency_ms = (time.time() - start_time) * 1000
            self._logger.error(
                "task_error",
                trace_id=task.trace_id,
                intent=intent,
                error=str(exc),
            )
            return AgentResult(
                task_id=task.task_id,
                trace_id=task.trace_id,
                agent_id=self.agent_id,
                status="failure",
                error=str(exc),
                latency_ms=latency_ms,
            )

    async def _handle_summary(
        self, payload: dict[str, Any]
    ) -> dict[str, Any]:
        """生成复盘摘要

        基于时间范围汇总笔记、情绪、开发活动。
        """
        time_range = payload.get("time_range", "today")
        notes_data = payload.get("notes", [])
        emotions_data = payload.get("emotions", [])
        dev_data = payload.get("dev_activities", [])

        summary_lines: list[str] = [
            f"## 复盘摘要（{time_range}）\n"
        ]

        # 笔记总结
        if notes_data:
            notes_count = len(notes_data)
            summary_lines.append(
                f"### 📝 笔记\n"
                f"共记录了 {notes_count} 条笔记。"
            )

        # 情绪总结
        if emotions_data:
            emotion_tags = [
                e.get("emotion_tag", "neutral") for e in emotions_data
            ]
            positive_count = emotion_tags.count("positive")
            negative_count = emotion_tags.count("negative")
            summary_lines.append(
                f"### 💭 情绪\n"
                f"积极情绪 {positive_count} 次，"
                f"消极情绪 {negative_count} 次。"
            )

        # 开发活动总结
        if dev_data:
            dev_count = len(dev_data)
            summary_lines.append(
                f"### 💻 开发活动\n"
                f"共进行 {dev_count} 项开发相关活动。"
            )

        summary = "\n\n".join(summary_lines) if summary_lines else "暂无数据"

        review_record = {
            "time_range": time_range,
            "summary": summary,
            "generated_at": time.time(),
        }
        self._reviews.append(review_record)

        return {
            "action": "summarized",
            "report": summary,
            "goals": self._goals,
        }

    async def _handle_goal(
        self, payload: dict[str, Any]
    ) -> dict[str, Any]:
        """目标追踪

        支持目标的设定、进度更新、完成状态管理。
        """
        action = payload.get("action", "list")
        goal_data = payload.get("goal", {})

        if action == "create":
            goal = {
                "id": f"goal_{int(time.time())}",
                "title": goal_data.get("title", ""),
                "description": goal_data.get("description", ""),
                "progress": 0,
                "status": "active",
                "created_at": time.time(),
                "updated_at": time.time(),
            }
            self._goals.append(goal)
            return {
                "action": "created",
                "goal": goal,
            }

        elif action == "update":
            goal_id = goal_data.get("id", "")
            for goal in self._goals:
                if goal["id"] == goal_id:
                    if "progress" in goal_data:
                        goal["progress"] = goal_data["progress"]
                    if "status" in goal_data:
                        goal["status"] = goal_data["status"]
                    goal["updated_at"] = time.time()
                    return {
                        "action": "updated",
                        "goal": goal,
                    }
            raise ValueError(f"目标不存在: {goal_id}")

        elif action == "list":
            status_filter = payload.get("status")
            if status_filter:
                filtered = [
                    g for g in self._goals if g["status"] == status_filter
                ]
            else:
                filtered = list(self._goals)
            return {
                "action": "listed",
                "goals": filtered,
            }

        else:
            raise ValueError(f"Unknown goal action: {action}")

    async def _handle_report(
        self, payload: dict[str, Any]
    ) -> dict[str, Any]:
        """生成周期性报告

        支持周报/月报格式的复盘报告生成。
        实际生产环境会调用 skill.data_analysis 进行统计分析。
        """
        report_type = payload.get("type", "weekly")
        notes_data = payload.get("notes", [])
        emotions_data = payload.get("emotions", [])

        if report_type == "weekly":
            title = "周报"
        elif report_type == "monthly":
            title = "月报"
        else:
            title = f"{report_type}报告"

        report_lines: list[str] = [
            f"# {title}复盘报告\n",
        ]

        notes_count = len(notes_data)
        emotions_count = len(emotions_data)

        report_lines.append(f"## 数据概览\n")
        report_lines.append(f"- 笔记数量：{notes_count}")
        report_lines.append(f"- 情绪记录：{emotions_count}")

        # 目标进度
        active_goals = [g for g in self._goals if g["status"] == "active"]
        completed_goals = [g for g in self._goals if g["status"] == "completed"]

        report_lines.append(f"\n## 目标进度\n")
        report_lines.append(f"- 进行中：{len(active_goals)} 个")
        report_lines.append(f"- 已完成：{len(completed_goals)} 个")

        if active_goals:
            report_lines.append(f"\n### 进行中的目标")
            for g in active_goals:
                report_lines.append(
                    f"- {g['title']}（进度：{g['progress']}%）"
                )

        if completed_goals:
            report_lines.append(f"\n### 已完成的目标")
            for g in completed_goals:
                report_lines.append(f"- {g['title']}")

        report_text = "\n".join(report_lines)

        review_record = {
            "type": report_type,
            "report": report_text,
            "generated_at": time.time(),
        }
        self._reviews.append(review_record)

        return {
            "action": "reported",
            "report": report_text,
            "goals": self._goals,
        }

    async def health(self) -> dict[str, Any]:
        """返回健康状态"""
        return {
            "agent_id": self.agent_id,
            "status": "healthy",
            "version": self.version,
            "goals_count": len(self._goals),
            "reviews_count": len(self._reviews),
        }