"""图像理解服务 — 通过多模态 LLM.

支持将图像发送给 Ollama vision 模型（如 llava）获取描述文本，
用于场景识别的多模态预处理。引擎不可用时静默降级。
"""

from __future__ import annotations

import base64
from typing import Any

import httpx
import structlog

logger = structlog.get_logger(__name__)

#: 默认 Ollama 地址
_DEFAULT_OLLAMA_BASE = "http://localhost:11434"
#: 默认 vision 模型
_DEFAULT_VISION_MODEL = "llava"


class VisionService:
    """图像理解服务 — 通过多模态 LLM.

    将 image_data 通过 Ollama vision 模型获取自然语言描述，
    供场景识别器消费。
    """

    def __init__(
        self,
        ollama_base_url: str = _DEFAULT_OLLAMA_BASE,
        vision_model: str = _DEFAULT_VISION_MODEL,
        timeout: float = 30.0,
    ) -> None:
        """初始化 Vision 服务.

        Args:
            ollama_base_url: Ollama 服务地址
            vision_model: vision 模型名称（如 llava, llava:13b 等）
            timeout: 请求超时（秒）
        """
        self.ollama_base_url = ollama_base_url.rstrip("/")
        self.vision_model = vision_model
        self.timeout = timeout

    def describe_image(
        self,
        image_data: bytes,
        prompt: str = "描述这张图片的内容",
    ) -> str:
        """通过 LLM 获取图像描述.

        将 image_data base64 编码后发送给 Ollama vision 模型，
        返回模型的文本描述。

        Args:
            image_data: 图像二进制数据
            prompt: 提示词

        Returns:
            图像描述文本；引擎不可用时返回空字符串
        """
        try:
            # 1. base64 编码
            b64 = base64.b64encode(image_data).decode("utf-8")
            data_url = f"data:image/png;base64,{b64}"

            # 2. 构造多模态消息
            messages = [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt},
                        {
                            "type": "image_url",
                            "image_url": {"url": data_url},
                        },
                    ],
                }
            ]

            # 3. 调用 Ollama /api/chat
            response = httpx.post(
                f"{self.ollama_base_url}/api/chat",
                json={
                    "model": self.vision_model,
                    "messages": messages,
                    "stream": False,
                    "options": {"temperature": 0.3, "num_predict": 300},
                },
                timeout=self.timeout,
            )
            response.raise_for_status()
            data = response.json()
            content = data.get("message", {}).get("content", "")
            if content:
                logger.info(
                    "vision.describe_ok",
                    model=self.vision_model,
                    length=len(content),
                )
                return content.strip()

        except httpx.ConnectError:
            logger.warning("vision.ollama_unreachable", url=self.ollama_base_url)
        except httpx.HTTPStatusError as e:
            logger.warning(
                "vision.ollama_http_error",
                status=e.response.status_code,
                model=self.vision_model,
            )
        except Exception as e:
            logger.warning(
                "vision.describe_failed",
                error_type=type(e).__name__,
                error=str(e),
            )

        return ""
