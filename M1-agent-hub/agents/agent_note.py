"""
云汐内核 - 多 Agent 集群调度系统
笔记 Agent 模块

负责学习笔记的记录、整理、标签化、全文检索、知识图谱关联。
"""

from __future__ import annotations

import time
from typing import Any

import structlog
from interfaces import AgentTask, AgentResult, IAgentPlugin

logger = structlog.get_logger(__name__)


class NoteAgent(IAgentPlugin):
    """笔记 Agent

    处理笔记的创建、搜索、标签管理、知识图谱关联。
    """

    agent_id: str = "agent.note"
    version: str = "1.0.0"
    capabilities: list[str] = [
        "note.create",
        "note.search",
        "note.tag",
        "note.link",
    ]

    def __init__(self) -> None:
        self._logger = logger.bind(agent_id=self.agent_id)
        # 内存存储（生产环境使用 LocalDataManager）
        self._notes: dict[str, dict[str, Any]] = {}
        self._tags: dict[str, list[str]] = {}  # note_id -> tags
        self._links: list[dict[str, str]] = []  # [{source, target, relation}]

    async def handle_task(self, task: AgentTask) -> AgentResult:
        """处理笔记相关任务"""
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
            if intent == "note.create":
                result = await self._handle_create(payload)
            elif intent == "note.search":
                result = await self._handle_search(payload)
            elif intent == "note.tag":
                result = await self._handle_tag(payload)
            elif intent == "note.link":
                result = await self._handle_link(payload)
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

    async def _handle_create(
        self, payload: dict[str, Any]
    ) -> dict[str, Any]:
        """创建笔记

        接收 title、content、tags，通过 SkillRouter 调用
        skill.doc_proc 和 skill.fulltext_search 进行笔记处理和索引。
        """
        title = payload.get("title", "无标题笔记")
        content = payload.get("content", "")
        tags = payload.get("tags", [])

        note_id = f"note_{int(time.time())}"
        note = {
            "note_id": note_id,
            "title": title,
            "content": content,
            "tags": tags,
            "created_at": time.time(),
            "updated_at": time.time(),
        }

        self._notes[note_id] = note
        if tags:
            self._tags[note_id] = tags

        # 实际生产环境会通过 SkillRouter 调用：
        # await skill_router.invoke("skill.doc_proc", {"content": content})
        # await skill_router.invoke("skill.fulltext_search", {"index_note": note})

        self._logger.info("note_created", note_id=note_id, title=title)

        return {
            "action": "created",
            "notes": [note],
        }

    async def _handle_search(
        self, payload: dict[str, Any]
    ) -> dict[str, Any]:
        """搜索笔记

        接收 query、filters，返回匹配的笔记列表。
        实际生产环境会通过 skill.fulltext_search 执行全文检索。
        """
        query = payload.get("query", "").lower()
        filters = payload.get("filters", {})

        results = []
        for note_id, note in self._notes.items():
            # 简单关键词匹配
            if query:
                if (
                    query in note["title"].lower()
                    or query in note["content"].lower()
                ):
                    results.append(note)
            else:
                results.append(note)

        # 应用额外过滤
        tag_filter = filters.get("tags", [])
        if tag_filter:
            results = [
                n for n in results if any(t in self._tags.get(n["note_id"], []) for t in tag_filter)
            ]

        self._logger.info(
            "note_search_completed",
            query=query,
            results_count=len(results),
        )

        return {
            "action": "searched",
            "notes": results,
        }

    async def _handle_tag(
        self, payload: dict[str, Any]
    ) -> dict[str, Any]:
        """为笔记添加/修改标签"""
        note_id = payload.get("note_id", "")
        tags = payload.get("tags", [])

        if note_id not in self._notes:
            raise ValueError(f"笔记不存在: {note_id}")

        self._tags[note_id] = tags
        self._notes[note_id]["tags"] = tags
        self._notes[note_id]["updated_at"] = time.time()

        self._logger.info("note_tagged", note_id=note_id, tags=tags)

        return {
            "action": "tagged",
            "note_id": note_id,
            "tags": tags,
        }

    async def _handle_link(
        self, payload: dict[str, Any]
    ) -> dict[str, Any]:
        """建立笔记间的知识图谱关联"""
        source = payload.get("source_id", "")
        target = payload.get("target_id", "")
        relation = payload.get("relation", "related")

        if source not in self._notes:
            raise ValueError(f"源笔记不存在: {source}")
        if target not in self._notes:
            raise ValueError(f"目标笔记不存在: {target}")

        link = {
            "source": source,
            "target": target,
            "relation": relation,
            "created_at": time.time(),
        }
        self._links.append(link)

        self._logger.info(
            "note_linked",
            source=source,
            target=target,
            relation=relation,
        )

        return {
            "action": "linked",
            "link": link,
        }

    async def health(self) -> dict[str, Any]:
        """返回健康状态"""
        return {
            "agent_id": self.agent_id,
            "status": "healthy",
            "version": self.version,
            "notes_count": len(self._notes),
            "links_count": len(self._links),
        }