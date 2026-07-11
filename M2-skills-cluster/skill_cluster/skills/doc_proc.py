from __future__ import annotations

"""文档处理技能."""

import os
from typing import Any

import structlog

from skill_cluster.interfaces import (
    ISkill,
    SkillInvokeRequest,
    SkillInvokeResult,
    SkillManifest,
)

logger = structlog.get_logger()


class DocProcSkill(ISkill):
    """文档处理技能，支持 Markdown 解析、PDF 提取、文本分块、编码检测."""

    def __init__(self) -> None:
        manifest = SkillManifest(
            skill_id="skill.doc_proc",
            name="文档处理",
            version="1.0.0",
            description="解析 Markdown、提取 PDF、分块文本、检测编码",
            author="yunxi",
            tags=["document", "text"],
            capabilities=["parse_markdown", "extract_pdf", "chunk_text", "detect_encoding"],
            entrypoint="DocProcSkill",
        )
        super().__init__(manifest)
        self._config: dict[str, Any] = {}

    async def invoke(self, request: SkillInvokeRequest) -> SkillInvokeResult:
        """执行文档处理动作."""
        action = request.action
        params = request.params
        start = __import__("time").perf_counter()

        try:
            if action == "parse_markdown":
                data = self._parse_markdown(params)
            elif action == "extract_pdf":
                data = await self._extract_pdf(params)
            elif action == "chunk_text":
                data = self._chunk_text(params)
            elif action == "detect_encoding":
                data = self._detect_encoding(params)
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

    def _parse_markdown(self, params: dict[str, Any]) -> dict[str, Any]:
        """解析 Markdown 为结构化文本块."""
        import markdown

        content = params.get("content", "")
        html = markdown.markdown(content)
        # 简单结构化：按行提取标题和段落
        blocks: list[dict[str, Any]] = []
        for line in content.splitlines():
            stripped = line.strip()
            if not stripped:
                continue
            if stripped.startswith("#"):
                level = len(stripped) - len(stripped.lstrip("#"))
                blocks.append({"type": "heading", "level": level, "text": stripped.lstrip("# ").strip()})
            elif stripped.startswith(("- ", "* ", "1. ", "2. ")):
                blocks.append({"type": "list_item", "text": stripped.lstrip("- * 0123456789.").strip()})
            else:
                blocks.append({"type": "paragraph", "text": stripped})
        return {"html": html, "blocks": blocks}

    async def _extract_pdf(self, params: dict[str, Any]) -> dict[str, Any]:
        """提取 PDF 文本."""
        try:
            import fitz  # type: ignore[import-untyped]
        except Exception as exc:  # pragma: no cover
            raise RuntimeError("pymupdf (fitz) not installed") from exc
        file_path = params.get("file_path", "")
        # 路径合法性校验：禁止访问 ~/.yunxi/ 以外的目录（简化示例）
        base_dir = os.path.expanduser("~/.yunxi")
        abs_path = os.path.abspath(file_path)
        if not abs_path.startswith(base_dir):
            raise PermissionError(f"Path {file_path} is outside allowed directory")
        doc = fitz.open(abs_path)
        text = ""
        for page in doc:
            text += page.get_text()
        doc.close()
        return {"text": text, "pages": len(doc)}

    def _chunk_text(self, params: dict[str, Any]) -> dict[str, Any]:
        """按字符数分块."""
        text = params.get("text", "")
        chunk_size = params.get("chunk_size", 500)
        overlap = params.get("overlap", 50)
        chunks: list[str] = []
        start = 0
        while start < len(text):
            end = start + chunk_size
            chunks.append(text[start:end])
            start = end - overlap
            if start >= len(text):
                break
        return {"chunks": chunks}

    def _detect_encoding(self, params: dict[str, Any]) -> dict[str, Any]:
        """检测字节编码."""
        import chardet

        content_bytes = params.get("content_bytes", b"")
        result = chardet.detect(content_bytes)
        return {"encoding": result.get("encoding"), "confidence": result.get("confidence")}

    def _error(self, request: SkillInvokeRequest, error: str, start: float) -> SkillInvokeResult:
        latency = (__import__("time").perf_counter() - start) * 1000
        logger.error("doc_proc_error", action=request.action, error=error, trace_id=request.trace_id)
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
