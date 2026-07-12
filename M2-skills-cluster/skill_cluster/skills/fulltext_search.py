from __future__ import annotations

"""全文检索技能."""

import os
import sqlite3
from typing import Any

import structlog

from skill_cluster.interfaces import (
    ISkill,
    SkillInvokeRequest,
    SkillInvokeResult,
    SkillManifest,
)

logger = structlog.get_logger()


class FulltextSearchSkill(ISkill):
    """全文检索技能，基于 SQLite FTS5."""

    def __init__(self) -> None:
        manifest = SkillManifest(
            skill_id="skill.fulltext_search",
            name="全文检索",
            version="1.0.0",
            description="索引文档、全文搜索、删除/更新索引",
            author="yunxi",
            tags=["search", "text"],
            capabilities=["index_document", "search", "delete_index", "update_index"],
            permissions=["read_file", "write"],
            entrypoint="FulltextSearchSkill",
        )
        super().__init__(manifest)
        self._config: dict[str, Any] = {}
        self._db_path = os.path.expanduser("~/.yunxi/cache/search_index/search.db")
        os.makedirs(os.path.dirname(self._db_path), exist_ok=True)
        self._init_db()

    def _init_db(self) -> None:
        with sqlite3.connect(self._db_path) as conn:
            conn.execute(
                """
                CREATE VIRTUAL TABLE IF NOT EXISTS documents USING fts5(
                    doc_id UNINDEXED,
                    title,
                    content,
                    metadata
                )
                """
            )
            conn.commit()

    async def invoke(self, request: SkillInvokeRequest) -> SkillInvokeResult:
        action = request.action
        params = request.params
        start = __import__("time").perf_counter()

        try:
            if action == "index_document":
                data = self._index_document(params)
            elif action == "search":
                data = self._search(params)
            elif action == "delete_index":
                data = self._delete_index(params)
            elif action == "update_index":
                data = self._update_index(params)
            else:
                return self._error(request, f"Unknown action: {action}", start)
            latency = (__import__("time").perf_counter() - start) * 1000
            return SkillInvokeResult(
                skill_id=self.manifest.skill_id,
                action=action,
                status="success",
                data=data,
                latency_ms=latency,
                trace_id=request.trace_id,
            )
        except Exception as e:
            return self._error(request, str(e), start)

    def _index_document(self, params: dict[str, Any]) -> dict[str, Any]:
        doc_id = params.get("doc_id", "")
        title = params.get("title", "")
        content = params.get("content", "")
        metadata = str(params.get("metadata", {}))
        with sqlite3.connect(self._db_path) as conn:
            conn.execute(
                "INSERT OR REPLACE INTO documents (doc_id, title, content, metadata) VALUES (?, ?, ?, ?)",
                (doc_id, title, content, metadata),
            )
            conn.commit()
        return {"indexed": True, "doc_id": doc_id}

    def _search(self, params: dict[str, Any]) -> dict[str, Any]:
        query = params.get("query", "")
        top_k = params.get("top_k", 10)
        with sqlite3.connect(self._db_path) as conn:
            rows = conn.execute(
                "SELECT doc_id, title, snippet(documents, 2, '<b>', '</b>', '...', 32) AS highlight FROM documents WHERE documents MATCH ? LIMIT ?",
                (query, top_k),
            ).fetchall()
        results = [
            {"doc_id": row[0], "title": row[1], "highlight": row[2]}
            for row in rows
        ]
        return {"results": results, "count": len(results)}

    def _delete_index(self, params: dict[str, Any]) -> dict[str, Any]:
        doc_id = params.get("doc_id", "")
        with sqlite3.connect(self._db_path) as conn:
            conn.execute("DELETE FROM documents WHERE doc_id = ?", (doc_id,))
            conn.commit()
        return {"deleted": True, "doc_id": doc_id}

    def _update_index(self, params: dict[str, Any]) -> dict[str, Any]:
        doc_id = params.get("doc_id", "")
        content = params.get("content", "")
        with sqlite3.connect(self._db_path) as conn:
            conn.execute(
                "UPDATE documents SET content = ? WHERE doc_id = ?",
                (content, doc_id),
            )
            conn.commit()
        return {"updated": True, "doc_id": doc_id}

    def _error(self, request: SkillInvokeRequest, error: str, start: float) -> SkillInvokeResult:
        latency = (__import__("time").perf_counter() - start) * 1000
        logger.error("fulltext_search_error", action=request.action, error=error, trace_id=request.trace_id)
        return SkillInvokeResult(
            skill_id=self.manifest.skill_id,
            action=request.action,
            status="failure",
            error=error,
            latency_ms=latency,
            trace_id=request.trace_id,
        )

    async def health(self) -> dict[str, Any]:
        return {"healthy": True, "skill_id": self.manifest.skill_id}

    async def configure(self, config: dict[str, Any]) -> None:
        self._config.update(config)
