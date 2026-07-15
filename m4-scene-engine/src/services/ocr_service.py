"""图像文字提取服务 — 多引擎降级.

支持 PaddleOCR、pytesseract、Ollama vision 等多种 OCR 引擎，
按优先级依次尝试，引擎不可用时静默降级。
"""

from __future__ import annotations

import base64
import io
from typing import Any

import httpx
import structlog

logger = structlog.get_logger(__name__)

#: 默认 Ollama 地址
_DEFAULT_OLLAMA_BASE = "http://localhost:11434"
#: OCR 用的 vision 模型
_DEFAULT_OCR_VISION_MODEL = "llava"


class OCRService:
    """图像文字提取服务 — 多引擎降级.

    按以下优先级尝试提取文字：
    1. PaddleOCR（如果已安装）
    2. pytesseract（如果已安装）
    3. Ollama vision 模型
    4. 返回空字符串
    """

    def __init__(
        self,
        ollama_base_url: str = _DEFAULT_OLLAMA_BASE,
        ocr_vision_model: str = _DEFAULT_OCR_VISION_MODEL,
        timeout: float = 30.0,
    ) -> None:
        """初始化 OCR 服务.

        Args:
            ollama_base_url: Ollama 服务地址
            ocr_vision_model: 用于 OCR 的 vision 模型
            timeout: 请求超时（秒）
        """
        self.ollama_base_url = ollama_base_url.rstrip("/")
        self.ocr_vision_model = ocr_vision_model
        self.timeout = timeout

    def extract_text(self, image_data: bytes) -> str:
        """从图像中提取文字.

        按优先级依次尝试各 OCR 引擎，首个成功即返回。

        Args:
            image_data: 图像二进制数据

        Returns:
            提取到的文字；所有引擎不可用时返回空字符串
        """
        # 1. 尝试 PaddleOCR
        text = self._try_paddleocr(image_data)
        if text:
            return text

        # 2. 尝试 pytesseract
        text = self._try_tesseract(image_data)
        if text:
            return text

        # 3. 尝试 Ollama vision 模型
        text = self._try_ollama_vision(image_data)
        if text:
            return text

        logger.warning("ocr.all_engines_failed")
        return ""

    # ------------------------------------------------------------------
    # 引擎实现
    # ------------------------------------------------------------------

    def _try_paddleocr(self, image_data: bytes) -> str:
        """尝试使用 PaddleOCR 提取文字."""
        try:
            from paddleocr import PaddleOCR  # type: ignore[import-untyped]

            import numpy as np
            from PIL import Image

            img = Image.open(io.BytesIO(image_data))
            img_array = np.array(img)

            engine = PaddleOCR(use_angle_cls=True, lang="ch", show_log=False)
            results = engine.ocr(img_array, cls=True)

            lines: list[str] = []
            for page in results:
                if page:
                    for line in page:
                        if line and len(line) >= 2:
                            lines.append(line[1][0])  # (text, confidence)

            text = "\n".join(lines).strip()
            if text:
                logger.info("ocr.paddleocr_ok", length=len(text))
                return text

        except ImportError:
            logger.debug("ocr.paddleocr_not_installed")
        except Exception as e:
            logger.warning(
                "ocr.paddleocr_failed",
                error_type=type(e).__name__,
                error=str(e),
            )

        return ""

    def _try_tesseract(self, image_data: bytes) -> str:
        """尝试使用 pytesseract 提取文字."""
        try:
            import pytesseract  # type: ignore[import-untyped]
            from PIL import Image

            img = Image.open(io.BytesIO(image_data))
            # 支持中文+英文
            text = pytesseract.image_to_string(img, lang="chi_sim+eng").strip()
            if text:
                logger.info("ocr.tesseract_ok", length=len(text))
                return text

        except ImportError:
            logger.debug("ocr.tesseract_not_installed")
        except Exception as e:
            logger.warning(
                "ocr.tesseract_failed",
                error_type=type(e).__name__,
                error=str(e),
            )

        return ""

    def _try_ollama_vision(self, image_data: bytes) -> str:
        """尝试使用 Ollama vision 模型提取文字."""
        try:
            b64 = base64.b64encode(image_data).decode("utf-8")
            data_url = f"data:image/png;base64,{b64}"

            messages = [
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "text",
                            "text": "请提取图片中的所有文字内容，只输出文字，不要添加任何解释。",
                        },
                        {
                            "type": "image_url",
                            "image_url": {"url": data_url},
                        },
                    ],
                }
            ]

            response = httpx.post(
                f"{self.ollama_base_url}/api/chat",
                json={
                    "model": self.ocr_vision_model,
                    "messages": messages,
                    "stream": False,
                    "options": {"temperature": 0.1, "num_predict": 500},
                },
                timeout=self.timeout,
            )
            response.raise_for_status()
            data = response.json()
            content = data.get("message", {}).get("content", "").strip()
            if content:
                logger.info("ocr.ollama_vision_ok", length=len(content))
                return content

        except httpx.ConnectError:
            logger.debug("ocr.ollama_unreachable", url=self.ollama_base_url)
        except Exception as e:
            logger.warning(
                "ocr.ollama_vision_failed",
                error_type=type(e).__name__,
                error=str(e),
            )

        return ""
