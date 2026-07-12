from __future__ import annotations

"""网页抓取技能."""

from typing import Any

import aiohttp
import structlog
from bs4 import BeautifulSoup

from skill_cluster.interfaces import (
    ISkill,
    SkillInvokeRequest,
    SkillInvokeResult,
    SkillManifest,
)

logger = structlog.get_logger()

MAX_RESPONSE_SIZE = 10 * 1024 * 1024  # 10MB


class WebFetchSkill(ISkill):
    """网页抓取技能，支持 URL 获取、HTML 解析、正文提取."""

    def __init__(self) -> None:
        manifest = SkillManifest(
            skill_id="skill.web_fetch",
            name="网页抓取",
            version="1.0.0",
            description="异步抓取网页、解析 HTML、提取正文",
            author="yunxi",
            tags=["network", "web"],
            capabilities=["fetch_url", "parse_html", "extract_article"],
            permissions=["network"],
            entrypoint="WebFetchSkill",
        )
        super().__init__(manifest)
        self._config: dict[str, Any] = {}

    async def invoke(self, request: SkillInvokeRequest) -> SkillInvokeResult:
        """执行网页抓取动作."""
        action = request.action
        params = request.params
        start = __import__("time").perf_counter()

        try:
            if action == "fetch_url":
                data = await self._fetch_url(params)
            elif action == "parse_html":
                data = self._parse_html(params)
            elif action == "extract_article":
                data = self._extract_article(params)
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

    async def _fetch_url(self, params: dict[str, Any]) -> dict[str, Any]:
        """异步 GET 请求."""
        url = params.get("url", "")
        if url.startswith("file://"):
            raise ValueError("file:// URLs are not allowed")
        headers = params.get("headers")
        timeout = aiohttp.ClientTimeout(total=params.get("timeout", 30))
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(url, headers=headers) as resp:
                content = await resp.read()
                if len(content) > MAX_RESPONSE_SIZE:
                    raise ValueError("Response size exceeds 10MB limit")
                text = content.decode("utf-8", errors="replace")
                return {
                    "status": resp.status,
                    "headers": dict(resp.headers),
                    "content": text,
                }

    def _parse_html(self, params: dict[str, Any]) -> dict[str, Any]:
        """解析 HTML."""
        html = params.get("html", "")
        selector = params.get("selector")
        soup = BeautifulSoup(html, "html.parser")
        if selector:
            elements = soup.select(selector)
            return {"texts": [el.get_text(strip=True) for el in elements]}
        return {"title": soup.title.string if soup.title else None, "text": soup.get_text(strip=True)}

    def _extract_article(self, params: dict[str, Any]) -> dict[str, Any]:
        """提取正文（启发式规则）."""
        html = params.get("html", "")
        soup = BeautifulSoup(html, "html.parser")
        # 优先 article 标签
        article = soup.find("article")
        if article:
            return {
                "title": soup.title.string if soup.title else "",
                "content": article.get_text(separator="\n", strip=True),
                "author": None,
            }
        # 最大文本块段落
        paragraphs = soup.find_all("p")
        best = ""
        for p in paragraphs:
            text = p.get_text(strip=True)
            if len(text) > len(best):
                best = text
        return {
            "title": soup.title.string if soup.title else "",
            "content": best,
            "author": None,
        }

    def _error(self, request: SkillInvokeRequest, error: str, start: float) -> SkillInvokeResult:
        latency = (__import__("time").perf_counter() - start) * 1000
        logger.error("web_fetch_error", action=request.action, error=error, trace_id=request.trace_id)
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
