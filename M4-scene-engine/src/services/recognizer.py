"""场景识别引擎.

基于关键词匹配的场景识别，可配置 LLM 增强。
识别逻辑：
1. 关键词匹配（优先，速度快）
2. 关键词得分最高且 >= 阈值(0.7) -> 直接返回
3. 否则返回 unknown 场景
"""

from __future__ import annotations

import asyncio
import re
from typing import Any

import httpx
import structlog

from src.models import SCENE_DEFINITIONS

logger = structlog.get_logger(__name__)


class SceneRecognizer:
    """场景识别引擎.

    基于关键词匹配 + 规则的场景识别器。
    支持可插拔的 LLM 增强识别（可选）。
    """

    def __init__(
        self,
        keyword_threshold: float = 0.7,
        enable_llm: bool = False,
        llm_base_url: str = "",
        llm_model_name: str = "",
    ) -> None:
        """初始化场景识别器.

        Args:
            keyword_threshold: 关键词匹配阈值（0-1）
            enable_llm: 是否启用 LLM 增强识别
            llm_base_url: LLM 服务地址
            llm_model_name: LLM 模型名称
        """
        self.keyword_threshold = keyword_threshold
        self.enable_llm = enable_llm
        self.llm_base_url = llm_base_url
        self.llm_model_name = llm_model_name

        # 预构建场景关键词索引
        self._scene_keywords: dict[str, list[str]] = {}
        for scene_id, scene_def in SCENE_DEFINITIONS.items():
            self._scene_keywords[scene_id] = scene_def.get("keywords", [])

    def recognize(
        self,
        text: str = "",
        audio_data: bytes | None = None,
        image_data: bytes | None = None,
        context: dict[str, Any] | None = None,
        include_all_scores: bool = True,
    ) -> dict[str, Any]:
        """识别场景.

        Args:
            text: 用户输入文本
            audio_data: 音频二进制数据（可选，将自动 ASR 转文本）
            image_data: 图像二进制数据（可选，将自动 Vision/OCR 转文本）
            context: 上下文信息
            include_all_scores: 是否返回所有场景得分

        Returns:
            识别结果字典:
            {
                "scene": "work_dev",       # 最佳匹配场景
                "confidence": 0.85,        # 置信度
                "all_scores": {...},       # 所有场景得分
                "method": "keyword",       # 识别方法
                "reason": "匹配关键词..."  # 识别原因
            }
        """
        # 多模态预处理
        method_used = "keyword"  # 默认
        if audio_data and not text:
            # ASR 语音转文本
            text = self._asr_transcribe(audio_data)
            if text:
                method_used = "asr_"  # 前缀，后续拼接

        if image_data and not text:
            # OCR / Vision 图像转文本
            text = self._vision_extract(image_data)
            if text:
                method_used = "vision_"

        if not text or not text.strip():
            empty_result = {
                "scene": "unknown",
                "confidence": 0.0,
                "all_scores": {sid: 0.0 for sid in self._scene_keywords},
                "method": "none",
                "reason": "输入文本为空",
            }
            return empty_result

        text_lower = text.lower()
        scores: dict[str, float] = {}
        matched_keywords: dict[str, list[str]] = {}

        # 1. 关键词匹配
        for scene_id, keywords in self._scene_keywords.items():
            score, matched = self._calc_keyword_score(text_lower, keywords)
            scores[scene_id] = score
            if matched:
                matched_keywords[scene_id] = matched

        # 找出最高分场景
        best_scene = max(scores, key=scores.get)
        best_score = scores[best_scene]

        # 2. 关键词得分 >= 阈值 -> 直接返回
        if best_score >= self.keyword_threshold:
            self._schedule_store_to_m5(text, best_scene, best_score)
            result = {
                "scene": best_scene,
                "top_scene": best_scene,
                "confidence": round(best_score, 4),
                "score": round(best_score, 4),
                "method": method_used + "keyword",
                "reason": f"[{method_used.rstrip('_') or 'text'}] 匹配关键词: {', '.join(matched_keywords.get(best_scene, [])[:5])}",
            }
            if include_all_scores:
                result["all_scores"] = {k: round(v, 4) for k, v in scores.items()}
                result["scores"] = {k: round(v, 4) for k, v in scores.items()}
            return result

        # 3. 尝试 LLM 增强识别（可选）
        if self.enable_llm and self.llm_base_url:
            try:
                llm_result = self._llm_recognize(text, context or {})
                if llm_result.get("confidence", 0) >= self.keyword_threshold:
                    self._schedule_store_to_m5(text, llm_result["scene"], llm_result.get("confidence", 0))
                    if include_all_scores:
                        llm_result["all_scores"] = {k: round(v, 4) for k, v in scores.items()}
                        llm_result["scores"] = {k: round(v, 4) for k, v in scores.items()}
                    return llm_result
            except Exception as e:
                logger.warning("recognizer.llm_failed", error_type=type(e).__name__, error=str(e))
                pass  # LLM 失败时降级到关键词结果

        # 4. 返回 unknown
        self._schedule_store_to_m5(text, "unknown", best_score)
        result = {
            "scene": "unknown",
            "top_scene": "unknown",
            "confidence": round(best_score, 4),
            "score": round(best_score, 4),
            "method": method_used + "keyword",
            "reason": f"[{method_used.rstrip('_') or 'text'}] 最高关键词得分 {best_score:.2%} 低于阈值 {self.keyword_threshold:.0%}",
        }
        if include_all_scores:
            result["all_scores"] = {k: round(v, 4) for k, v in scores.items()}
            result["scores"] = {k: round(v, 4) for k, v in scores.items()}
        return result

    def _calc_keyword_score(
        self,
        text: str,
        keywords: list[str],
    ) -> tuple[float, list[str]]:
        """计算关键词匹配得分.

        得分计算：匹配关键词数 / 总关键词数，乘以匹配质量系数。
        同时考虑关键词出现的频次。

        Args:
            text: 输入文本（小写）
            keywords: 关键词列表

        Returns:
            (得分, 匹配到的关键词列表)
        """
        if not keywords:
            return 0.0, []

        matched: list[str] = []
        match_count = 0

        for kw in keywords:
            kw_lower = kw.lower()
            # 使用单词边界匹配，避免部分匹配
            if re.search(re.escape(kw_lower), text):
                matched.append(kw)
                # 统计出现次数
                count = len(re.findall(re.escape(kw_lower), text))
                match_count += min(count, 3)  # 最多计3次

        # 基础得分：匹配关键词数 / 总关键词数
        base_score = len(matched) / len(keywords) if keywords else 0.0

        # 频次加成
        freq_bonus = min(match_count / (len(keywords) * 2), 0.3) if keywords else 0.0

        # 长文本惩罚（避免长文本匹配更多关键词的偏差）
        text_len = len(text)
        len_factor = 1.0
        if text_len > 500:
            len_factor = 0.9
        elif text_len > 200:
            len_factor = 0.95

        score = min((base_score + freq_bonus) * len_factor, 1.0)
        return score, matched

    async def _llm_recognize(
        self,
        text: str,
        context: dict[str, Any],
    ) -> dict[str, Any]:
        """使用 LLM 进行场景识别（增强模式）.

        Args:
            text: 用户输入文本
            context: 上下文信息

        Returns:
            识别结果字典
        """
        try:
            import httpx

            scenes_desc = "\n".join(
                f"- {sid}: {sdef['name']} - {sdef['description']}"
                for sid, sdef in SCENE_DEFINITIONS.items()
            )

            system_prompt = f"""你是场景识别助手。请根据用户输入判断最适合的场景。
可选场景：
{scenes_desc}

请输出 JSON 格式：{{"scene": "场景ID", "confidence": 0.0-1.0, "reason": "判断理由"}}"""

            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.post(
                    f"{self.llm_base_url.rstrip('/')}/api/chat",
                    json={
                        "model": self.llm_model_name,
                        "messages": [
                            {"role": "system", "content": system_prompt},
                            {"role": "user", "content": text},
                        ],
                        "stream": False,
                        "options": {"temperature": 0.3, "num_predict": 200},
                    },
                )
                if response.status_code == 200:
                    data = response.json()
                    content = data.get("message", {}).get("content", "")
                    # 提取 JSON
                    import json as json_mod
                    start = content.find("{")
                    end = content.rfind("}")
                    if start >= 0 and end > start:
                        parsed = json_mod.loads(content[start:end + 1])
                        scene_id = parsed.get("scene", "unknown")
                        if scene_id not in SCENE_DEFINITIONS:
                            scene_id = "unknown"
                        return {
                            "scene": scene_id,
                            "top_scene": scene_id,
                            "confidence": float(parsed.get("confidence", 0.5)),
                            "score": float(parsed.get("confidence", 0.5)),
                            "method": "llm",
                            "reason": parsed.get("reason", ""),
                        }
        except Exception as e:
            logger.warning("recognizer.llm_recognize_failed", error_type=type(e).__name__, error=str(e))
            pass

        return {
            "scene": "unknown",
            "top_scene": "unknown",
            "confidence": 0.0,
            "score": 0.0,
            "method": "llm_failed",
            "reason": "LLM 识别失败",
        }

    def update_threshold(self, threshold: float) -> None:
        """更新关键词阈值."""
        self.keyword_threshold = max(0.0, min(1.0, threshold))

    # ------------------------------------------------------------------
    # M5 记忆写入（M4 -> M5 跨模块调用）
    # ------------------------------------------------------------------

    async def _store_to_m5(
        self,
        text: str,
        scene: str,
        confidence: float,
    ) -> None:
        """将场景识别结果异步写入 M5 记忆服务.

        Args:
            text: 用户输入文本（原始）
            scene: 识别到的场景ID
            confidence: 置信度
        """
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                await client.post(
                    "http://localhost:8005/api/v1/memory/store",
                    json={
                        "content": (
                            f"场景识别：用户输入 '{text[:100]}' "
                            f"被识别为 {scene} 场景"
                            f"（置信度 {confidence:.2f}）"
                        ),
                        "tags": ["scene_recognition", scene],
                        "source": "m4_recognizer",
                        "agent_id": "m4_scene_engine",
                    },
                )
        except Exception as e:
            logger.warning(
                "recognizer.store_to_m5_failed",
                scene=scene,
                error_type=type(e).__name__,
                error=str(e),
            )

    def _schedule_store_to_m5(
        self,
        text: str,
        scene: str,
        confidence: float,
    ) -> None:
        """安全地调度异步 M5 写入任务（不阻塞调用方）.

        尝试在已有事件循环中创建 task，若无可运行循环则静默跳过。

        Args:
            text: 用户输入文本
            scene: 识别到的场景ID
            confidence: 置信度
        """
        try:
            loop = asyncio.get_running_loop()
            loop.create_task(self._store_to_m5(text, scene, confidence))
        except RuntimeError:
            # 没有运行中的事件循环，静默跳过
            pass

    def update_scene_keywords(self, scene_id: str, keywords: list[str]) -> bool:
        """更新指定场景的关键词列表.

        Args:
            scene_id: 场景ID
            keywords: 新的关键词列表

        Returns:
            是否更新成功
        """
        if scene_id not in self._scene_keywords:
            return False
        self._scene_keywords[scene_id] = keywords
        return True

    def get_scene_keywords(self, scene_id: str) -> list[str]:
        """获取指定场景的关键词列表."""
        return self._scene_keywords.get(scene_id, [])

    # ------------------------------------------------------------------
    # 多模态预处理：ASR 语音转文本
    # ------------------------------------------------------------------

    def _asr_transcribe(self, audio_data: bytes) -> str:
        """将音频数据转为文本.

        按优先级尝试：
        1. faster_whisper 本地模型
        2. Ollama whisper 模型（HTTP 调用）
        3. mock 降级（返回模拟文本）

        Args:
            audio_data: 音频二进制数据

        Returns:
            转录文本；所有引擎不可用时返回空字符串
        """
        import tempfile
        import os

        # 1. 尝试 faster_whisper
        try:
            from faster_whisper import WhisperModel  # type: ignore[import-untyped]

            # 将音频写入临时文件
            suffix = ".wav"
            with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
                tmp.write(audio_data)
                tmp_path = tmp.name

            try:
                model = WhisperModel("small", device="cpu", compute_type="int8")
                segments, _ = model.transcribe(tmp_path)
                text = " ".join(seg.text for seg in segments).strip()
                if text:
                    logger.info("recognizer.asr_faster_whisper_ok", length=len(text))
                    return text
            finally:
                os.unlink(tmp_path)

        except ImportError:
            logger.debug("recognizer.asr_faster_whisper_not_installed")
        except Exception as e:
            logger.warning(
                "recognizer.asr_faster_whisper_failed",
                error_type=type(e).__name__,
                error=str(e),
            )

        # 2. 尝试 Ollama whisper 模型
        try:
            import base64 as b64mod

            b64 = b64mod.b64encode(audio_data).decode("utf-8")
            # Ollama whisper API 使用 /api/generate 或 /api/chat
            response = httpx.post(
                f"{self.llm_base_url.rstrip('/') or 'http://localhost:11434'}/api/generate",
                json={
                    "model": "whisper",
                    "prompt": "",
                    "images": [],  # whisper 通过 generate 直接处理音频
                    "stream": False,
                },
                timeout=30.0,
                files=None,
            )
            # 注意：Ollama 的 whisper 模型通常通过专门端点处理，
            # 此处为示意性实现，实际需根据 Ollama 版本调整
            if response.status_code == 200:
                data = response.json()
                text = data.get("response", "").strip()
                if text:
                    logger.info("recognizer.asr_ollama_ok", length=len(text))
                    return text
        except Exception as e:
            logger.debug(
                "recognizer.asr_ollama_failed",
                error_type=type(e).__name__,
                error=str(e),
            )

        # 3. Mock 降级
        mock_text = "这是一段语音输入的模拟文本，用于场景识别测试。"
        logger.info("recognizer.asr_mock_fallback")
        return mock_text

    # ------------------------------------------------------------------
    # 多模态预处理：Vision/OCR 图像转文本
    # ------------------------------------------------------------------

    def _vision_extract(self, image_data: bytes) -> str:
        """从图像数据中提取文字或描述.

        按优先级尝试：
        1. VisionService（Ollama vision 模型获取图像描述）
        2. OCRService（多引擎 OCR 提取文字）
        3. 返回空字符串

        Args:
            image_data: 图像二进制数据

        Returns:
            提取的文本；所有引擎不可用时返回空字符串
        """
        # 1. 尝试 VisionService 获取图像描述
        try:
            from src.services.vision_service import VisionService

            vision = VisionService(
                ollama_base_url=self.llm_base_url or "http://localhost:11434",
            )
            description = vision.describe_image(image_data)
            if description:
                logger.info("recognizer.vision_describe_ok", length=len(description))
                return description
        except Exception as e:
            logger.debug(
                "recognizer.vision_describe_failed",
                error_type=type(e).__name__,
                error=str(e),
            )

        # 2. 尝试 OCRService 提取文字
        try:
            from src.services.ocr_service import OCRService

            ocr = OCRService(
                ollama_base_url=self.llm_base_url or "http://localhost:11434",
            )
            text = ocr.extract_text(image_data)
            if text:
                logger.info("recognizer.vision_ocr_ok", length=len(text))
                return text
        except Exception as e:
            logger.debug(
                "recognizer.vision_ocr_failed",
                error_type=type(e).__name__,
                error=str(e),
            )

        logger.warning("recognizer.vision_all_failed")
        return ""
