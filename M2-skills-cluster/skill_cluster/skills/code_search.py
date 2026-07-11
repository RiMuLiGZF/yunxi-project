from __future__ import annotations

"""代码搜索技能."""

import difflib
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


class CodeSearchSkill(ISkill):
    """代码搜索技能，支持索引、语义搜索、模糊搜索、代码片段获取."""

    def __init__(self) -> None:
        manifest = SkillManifest(
            skill_id="skill.code_search",
            name="代码搜索",
            version="1.0.0",
            description="索引代码库、语义/模糊搜索、获取代码片段",
            author="yunxi",
            tags=["code", "search"],
            capabilities=["index_repo", "semantic_search", "fuzzy_search", "get_snippet"],
            permissions=["read_file"],
            entrypoint="CodeSearchSkill",
        )
        super().__init__(manifest)
        self._config: dict[str, Any] = {}
        self._db_path = os.path.expanduser("~/.yunxi/cache/code_index/code_search.db")
        os.makedirs(os.path.dirname(self._db_path), exist_ok=True)
        self._init_db()

    def _init_db(self) -> None:
        with sqlite3.connect(self._db_path) as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS files (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    repo_path TEXT,
                    file_path TEXT UNIQUE,
                    language TEXT,
                    line_count INTEGER,
                    content TEXT
                )
                """
            )
            conn.commit()

    async def invoke(self, request: SkillInvokeRequest) -> SkillInvokeResult:
        action = request.action
        params = request.params
        start = __import__("time").perf_counter()

        try:
            if action == "index_repo":
                data = await self._index_repo(params)
            elif action == "semantic_search":
                data = self._semantic_search(params)
            elif action == "fuzzy_search":
                data = self._fuzzy_search(params)
            elif action == "get_snippet":
                data = self._get_snippet(params)
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

    async def _index_repo(self, params: dict[str, Any]) -> dict[str, Any]:
        """扫描本地代码库并建立索引."""
        repo_path = params.get("repo_path", "")
        file_patterns = params.get("file_patterns", ["*.py", "*.js", "*.ts", "*.java", "*.go", "*.rs"])
        # 路径校验
        base_dir = os.path.expanduser("~/.yunxi")
        abs_repo = os.path.abspath(repo_path)
        if not abs_repo.startswith(base_dir):
            raise PermissionError(f"Repo path {repo_path} is outside allowed directory")
        indexed = 0
        with sqlite3.connect(self._db_path) as conn:
            for root, _, files in os.walk(abs_repo):
                for fname in files:
                    if any(fname.endswith(p.lstrip("*")) for p in file_patterns):
                        fpath = os.path.join(root, fname)
                        rel_path = os.path.relpath(fpath, abs_repo)
                        try:
                            with open(fpath, encoding="utf-8", errors="replace") as f:
                                content = f.read()
                        except Exception:
                            continue
                        lines = content.splitlines()
                        lang = fname.split(".")[-1] if "." in fname else ""
                        conn.execute(
                            "INSERT OR REPLACE INTO files (repo_path, file_path, language, line_count, content) VALUES (?, ?, ?, ?, ?)",
                            (abs_repo, rel_path, lang, len(lines), content),
                        )
                        indexed += 1
            conn.commit()
        return {"indexed": indexed}

    def _semantic_search(self, params: dict[str, Any]) -> dict[str, Any]:
        """基于关键词的语义搜索（预留向量接口）."""
        query = params.get("query", "").lower()
        top_k = params.get("top_k", 5)
        keywords = query.split()
        results: list[dict[str, Any]] = []
        with sqlite3.connect(self._db_path) as conn:
            rows = conn.execute("SELECT file_path, content FROM files").fetchall()
        for file_path, content in rows:
            text = (file_path + " " + content).lower()
            score = sum(1 for kw in keywords if kw in text)
            if score > 0:
                results.append({"file_path": file_path, "score": score, "snippet": content[:200]})
        results.sort(key=lambda x: x["score"], reverse=True)
        return {"results": results[:top_k]}

    def _fuzzy_search(self, params: dict[str, Any]) -> dict[str, Any]:
        """模糊搜索."""
        query = params.get("query", "")
        top_k = params.get("top_k", 5)
        results: list[dict[str, Any]] = []
        with sqlite3.connect(self._db_path) as conn:
            rows = conn.execute("SELECT file_path, content FROM files").fetchall()
        for file_path, content in rows:
            score = difflib.SequenceMatcher(None, query, file_path).ratio()
            results.append({"file_path": file_path, "score": score, "snippet": content[:200]})
        results.sort(key=lambda x: x["score"], reverse=True)
        return {"results": results[:top_k]}

    def _get_snippet(self, params: dict[str, Any]) -> dict[str, Any]:
        """获取代码片段."""
        file_path = params.get("file_path", "")
        line_start = params.get("line_start", 1)
        line_end = params.get("line_end", line_start + 10)
        with sqlite3.connect(self._db_path) as conn:
            row = conn.execute(
                "SELECT content FROM files WHERE file_path = ?", (file_path,)
            ).fetchone()
        if not row:
            raise FileNotFoundError(f"File {file_path} not indexed")
        lines = row[0].splitlines()
        snippet = "\n".join(lines[line_start - 1 : line_end])
        return {"snippet": snippet, "lines": (line_start, line_end)}

    def _error(self, request: SkillInvokeRequest, error: str, start: float) -> SkillInvokeResult:
        latency = (__import__("time").perf_counter() - start) * 1000
        logger.error("code_search_error", action=request.action, error=error, trace_id=request.trace_id)
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
