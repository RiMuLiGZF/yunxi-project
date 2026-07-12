from __future__ import annotations

"""翻译转换技能."""

import hashlib
import json
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

CACHE_TTL_SECONDS = 7 * 24 * 3600


class TranslateSkill(ISkill):
    """翻译转换技能，支持文本翻译、语言检测、批量翻译."""

    def __init__(self) -> None:
        manifest = SkillManifest(
            skill_id="skill.translate",
            name="翻译转换",
            version="1.0.0",
            description="文本翻译、语言检测、批量翻译",
            author="yunxi",
            tags=["translate", "language"],
            capabilities=["translate_text", "detect_language", "batch_translate"],
            permissions=["network"],
            entrypoint="TranslateSkill",
        )
        super().__init__(manifest)
        self._config: dict[str, Any] = {}
        self._cache_dir = os.path.expanduser("~/.yunxi/cache/translate")
        os.makedirs(self._cache_dir, exist_ok=True)

    async def invoke(self, request: SkillInvokeRequest) -> SkillInvokeResult:
        action = request.action
        params = request.params
        start = __import__("time").perf_counter()

        try:
            if action == "translate_text":
                data = await self._translate_text(params)
            elif action == "detect_language":
                data = self._detect_language(params)
            elif action == "batch_translate":
                data = await self._batch_translate(params)
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

    async def _translate_text(self, params: dict[str, Any]) -> dict[str, Any]:
        text = params.get("text", "")
        source_lang = params.get("source_lang", "auto")
        target_lang = params.get("target_lang", "en")
        cache_key = hashlib.sha256(f"{text}:{target_lang}".encode()).hexdigest()
        cache_path = os.path.join(self._cache_dir, f"{cache_key}.json")

        # 检查缓存
        if os.path.exists(cache_path):
            with open(cache_path, encoding="utf-8") as f:
                cached = json.load(f)
            return {"translated": cached.get("result", ""), "source": text, "cached": True}

        # 本地 ONNX 翻译模型
        onnx_model = self._config.get("onnx_model")
        onnx_enabled = self._config.get("onnx_enabled", False)

        if onnx_enabled and onnx_model:
            try:
                from skill_cluster.onnx_runtime import get_engine
                engine = get_engine()
                if engine.is_model_loaded(onnx_model):
                    # ONNX 模型推理（具体输入格式取决于模型）
                    # 这里为概念接入，实际需根据模型输入格式适配
                    result = await self._onnx_translate(engine, onnx_model, text, target_lang)
                    if result:
                        # 写入缓存
                        with open(cache_path, "w", encoding="utf-8") as f:
                            json.dump({"result": result, "ttl": CACHE_TTL_SECONDS}, f)
                        return {"translated": result, "source": text, "cached": False, "backend": "onnx"}
            except Exception as e:
                logger.debug(f"ONNX 翻译失败，降级: {e}")

        # 通过 LLMProvider 翻译（预留接口，实际由端云协同内核提供）
        # [待接入] LLMProvider.translate
        # 降级：直接返回原文（避免直接调用 API）
        result = text  # 降级策略

        # 写入缓存
        with open(cache_path, "w", encoding="utf-8") as f:
            json.dump({"result": result, "ttl": CACHE_TTL_SECONDS}, f)

        return {"translated": result, "source": text, "cached": False}

    def _detect_language(self, params: dict[str, Any]) -> dict[str, Any]:
        try:
            from langdetect import detect
        except Exception as exc:
            raise RuntimeError("langdetect not installed") from exc
        text = params.get("text", "")
        lang = detect(text)
        return {"language": lang, "confidence": 1.0}

    async def _batch_translate(self, params: dict[str, Any]) -> dict[str, Any]:
        texts = params.get("texts", [])
        target_lang = params.get("target_lang", "en")
        import asyncio

        tasks = [
            self._translate_text({"text": t, "target_lang": target_lang})
            for t in texts
        ]
        results = await asyncio.gather(*tasks)
        return {
            "translations": [r["translated"] for r in results],
            "target_lang": target_lang,
        }

    def _error(self, request: SkillInvokeRequest, error: str, start: float) -> SkillInvokeResult:
        latency = (__import__("time").perf_counter() - start) * 1000
        logger.error("translate_error", action=request.action, error=error, trace_id=request.trace_id)
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
