"""M11 MCP Bus - 语音模块 MCP 适配器.

将 M8 控制塔的语音能力封装为 MCP 工具，
包括文本转语音、语音转文本、唤醒词检测等功能。
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

import httpx

from .base import BaseMcpAdapter


class VoiceMcpAdapter(BaseMcpAdapter):
    """语音模块 MCP 适配器.

    封装 M8 控制塔的语音 API，提供以下 MCP 工具：
    - voice.tts_synthesize: 文本转语音
    - asr_transcribe: 语音转文本
    - wake_word_detect: 唤醒词检测
    - list_voices: 获取可用音色列表
    - get_status: 获取语音服务状态
    """

    adapter_name: str = "voice"
    adapter_description: str = "语音能力适配器 - 提供 TTS、ASR、唤醒词检测等语音工具"

    def __init__(
        self,
        m8_base_url: str = "http://localhost:8000",
        bus_url: str = "http://localhost:8011",
        server_endpoint: Optional[str] = None,
        m8_api_key: str = "",
    ) -> None:
        """初始化语音适配器.

        Args:
            m8_base_url: M8 控制塔基础地址
            bus_url: M11 总线地址
            server_endpoint: 本适配器的 MCP 端点地址
            m8_api_key: M8 API 鉴权密钥（可选）
        """
        super().__init__(
            bus_url=bus_url,
            server_name="voice",
            server_endpoint=server_endpoint,
        )

        self.m8_base_url = m8_base_url.rstrip("/")
        self.m8_api_key = m8_api_key

    # ============================================================
    # 工具定义
    # ============================================================

    def get_tools(self) -> List[Dict[str, Any]]:
        """获取语音模块的 MCP 工具列表.

        Returns:
            工具定义列表
        """
        return [
            {
                "name": "tts_synthesize",
                "description": "文本转语音，将输入文本合成为语音音频，返回音频文件地址或 base64 数据",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "text": {
                            "type": "string",
                            "description": "要合成的文本内容",
                        },
                        "voice": {
                            "type": "string",
                            "description": "音色名称，如不指定则使用默认音色",
                            "default": "default",
                        },
                        "rate": {
                            "type": "number",
                            "description": "语速倍率，范围 0.5-2.0，1.0 为正常速度",
                            "default": 1.0,
                            "minimum": 0.5,
                            "maximum": 2.0,
                        },
                    },
                    "required": ["text"],
                },
            },
            {
                "name": "asr_transcribe",
                "description": "语音转文本，将音频文件中的语音内容识别为文字",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "audio_url": {
                            "type": "string",
                            "description": "音频文件的 URL 地址（与 base64_audio 二选一）",
                        },
                        "base64_audio": {
                            "type": "string",
                            "description": "音频的 base64 编码数据（与 audio_url 二选一）",
                        },
                        "language": {
                            "type": "string",
                            "description": "语言代码，如 zh-CN、en-US，默认为自动检测",
                            "default": "auto",
                        },
                    },
                },
            },
            {
                "name": "wake_word_detect",
                "description": "唤醒词检测，在音频中检测指定的唤醒词是否出现",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "audio_url": {
                            "type": "string",
                            "description": "音频文件的 URL 地址",
                        },
                        "wake_words": {
                            "type": "array",
                            "items": {
                                "type": "string",
                            },
                            "description": "要检测的唤醒词列表",
                        },
                        "threshold": {
                            "type": "number",
                            "description": "检测阈值，范围 0.0-1.0，值越高越严格",
                            "default": 0.7,
                            "minimum": 0.0,
                            "maximum": 1.0,
                        },
                    },
                    "required": ["audio_url", "wake_words"],
                },
            },
            {
                "name": "list_voices",
                "description": "获取当前可用的音色列表，包括音色名称、语言、性别等信息",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "language": {
                            "type": "string",
                            "description": "按语言过滤音色，如 zh-CN、en-US，不填则返回全部",
                        },
                    },
                },
            },
            {
                "name": "get_status",
                "description": "获取语音服务的运行状态，包括服务可用性、已加载模型等信息",
                "inputSchema": {
                    "type": "object",
                    "properties": {},
                },
            },
        ]

    # ============================================================
    # 工具调用分发
    # ============================================================

    def call_tool(self, name: str, args: Dict[str, Any]) -> Dict[str, Any]:
        """调用语音工具.

        根据工具名分发到对应的 M8 语音 API。

        Args:
            name: 工具名称
            args: 工具参数

        Returns:
            工具执行结果

        Raises:
            ValueError: 工具不存在时抛出
            RuntimeError: 调用失败时抛出
        """
        tool_map = {
            "voice.tts_synthesize": self._call_tts_synthesize,
            "asr_transcribe": self._call_asr_transcribe,
            "wake_word_detect": self._call_wake_word_detect,
            "list_voices": self._call_list_voices,
            "get_status": self._call_get_status,
        }

        handler = tool_map.get(name)
        if not handler:
            raise ValueError(f"未知的语音工具: {name}")

        return handler(args)

    # ============================================================
    # 各工具的具体实现
    # ============================================================

    def _call_tts_synthesize(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """调用文本转语音接口.

        Args:
            args: 调用参数

        Returns:
            合成结果
        """
        text = args.get("text", "")
        if not text:
            raise ValueError("缺少必要参数: text")

        payload = {
            "text": text,
            "voice": args.get("voice", "default"),
            "rate": args.get("rate", 1.0),
        }

        return self._request_m8(
            method="POST",
            path="/api/voice/tts/synthesize",
            json=payload,
        )

    def _call_asr_transcribe(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """调用语音转文本接口.

        Args:
            args: 调用参数

        Returns:
            识别结果
        """
        audio_url = args.get("audio_url", "")
        base64_audio = args.get("base64_audio", "")

        if not audio_url and not base64_audio:
            raise ValueError("必须提供 audio_url 或 base64_audio 其中之一")

        payload: Dict[str, Any] = {}
        if audio_url:
            payload["audio_url"] = audio_url
        if base64_audio:
            payload["base64_audio"] = base64_audio

        language = args.get("language", "auto")
        if language:
            payload["language"] = language

        return self._request_m8(
            method="POST",
            path="/api/voice/asr/transcribe",
            json=payload,
        )

    def _call_wake_word_detect(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """调用唤醒词检测接口.

        Args:
            args: 调用参数

        Returns:
            检测结果
        """
        audio_url = args.get("audio_url", "")
        wake_words = args.get("wake_words", [])

        if not audio_url:
            raise ValueError("缺少必要参数: audio_url")
        if not wake_words:
            raise ValueError("缺少必要参数: wake_words")

        payload = {
            "audio_url": audio_url,
            "wake_words": wake_words,
            "threshold": args.get("threshold", 0.7),
        }

        return self._request_m8(
            method="POST",
            path="/api/voice/wake-word/detect",
            json=payload,
        )

    def _call_list_voices(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """调用获取音色列表接口.

        Args:
            args: 调用参数

        Returns:
            音色列表
        """
        params: Dict[str, Any] = {}
        language = args.get("language", "")
        if language:
            params["language"] = language

        return self._request_m8(
            method="GET",
            path="/api/voice/voices",
            params=params,
        )

    def _call_get_status(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """调用获取语音服务状态接口.

        Args:
            args: 调用参数

        Returns:
            服务状态
        """
        return self._request_m8(
            method="GET",
            path="/api/voice/status",
        )

    # ============================================================
    # M8 API 调用封装
    # ============================================================

    def _request_m8(
        self,
        method: str,
        path: str,
        json: Optional[Dict[str, Any]] = None,
        params: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """调用 M8 控制塔 API.

        Args:
            method: HTTP 方法（GET/POST 等）
            path: API 路径
            json: 请求体 JSON 数据
            params: URL 查询参数

        Returns:
            API 响应数据

        Raises:
            RuntimeError: 请求失败时抛出
        """
        url = f"{self.m8_base_url}{path}"

        headers = {"Content-Type": "application/json"}
        if self.m8_api_key:
            headers["Authorization"] = f"Bearer {self.m8_api_key}"

        try:
            with httpx.Client(timeout=30.0) as client:
                response = client.request(
                    method=method,
                    url=url,
                    json=json,
                    params=params,
                    headers=headers,
                )
                response.raise_for_status()
                return response.json()
        except httpx.HTTPStatusError as e:
            detail = ""
            try:
                error_data = e.response.json()
                detail = error_data.get("detail", error_data.get("message", str(e)))
            except Exception:
                detail = e.response.text or str(e)
            raise RuntimeError(f"M8 语音 API 调用失败（{e.response.status_code}）: {detail}") from e
        except httpx.HTTPError as e:
            raise RuntimeError(f"M8 语音 API 网络错误: {e}") from e
        except Exception as e:
            raise RuntimeError(f"M8 语音 API 调用异常: {e}") from e
