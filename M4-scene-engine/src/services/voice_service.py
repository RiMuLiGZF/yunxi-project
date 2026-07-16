"""语音服务 - 业务逻辑层.

封装语音服务的业务逻辑，包括 TTS（文本转语音）、ASR（语音转文本）、
VAD（语音活动检测）、唤醒词配置、语音配置管理等功能。

简化版实现：TTS/ASR 返回 mock 数据，预留真实引擎接入点。
"""

from __future__ import annotations

import uuid
from typing import Any, Optional
from datetime import datetime

from sqlalchemy.orm import Session

from src.models.db import VoiceConfigDB, VoiceHistoryDB


# ---------------------------------------------------------------------------
# 常量配置
# ---------------------------------------------------------------------------

#: 默认语音类型
DEFAULT_VOICE_TYPE = "warm_female"
#: 可用语音类型
AVAILABLE_VOICES: list[dict[str, Any]] = [
    {"id": "warm_female", "name": "温暖女声", "gender": "female", "description": "温柔温暖的女声，适合日常陪伴"},
    {"id": "clear_female", "name": "清澈女声", "gender": "female", "description": "清晰明亮的女声，适合信息播报"},
    {"id": "gentle_male", "name": "温润男声", "gender": "male", "description": "温和磁性的男声，适合专业场景"},
    {"id": "cute_child", "name": "可爱童声", "gender": "child", "description": "活泼可爱的童声，适合儿童模式"},
    {"id": "robot", "name": "机械音", "gender": "neutral", "description": "科技感机械音，适合开发者模式"},
]
#: 默认唤醒词
DEFAULT_WAKE_WORDS: list[str] = ["云汐", "你好云汐"]
#: 可用 TTS 引擎
TTS_ENGINES: list[str] = ["mock", "edge-tts", "azure", "local"]
#: 可用 ASR 引擎
ASR_ENGINES: list[str] = ["mock", "faster-whisper", "azure", "baidu"]


# ---------------------------------------------------------------------------
# VoiceService 主类
# ---------------------------------------------------------------------------


class VoiceService:
    """语音服务.

    封装语音相关的所有业务逻辑，包括 TTS、ASR、VAD、
    唤醒词管理、语音配置管理等。
    """

    def __init__(self, db: Session, user_id: str = "default") -> None:
        """初始化语音服务.

        Args:
            db: 数据库会话
            user_id: 用户ID
        """
        self.db = db
        self.user_id = user_id

    # ------------------------------------------------------------------
    # 配置管理
    # ------------------------------------------------------------------

    def get_config(self) -> dict[str, Any]:
        """获取用户语音配置.

        Returns:
            语音配置字典
        """
        config = (
            self.db.query(VoiceConfigDB)
            .filter(VoiceConfigDB.user_id == self.user_id)
            .first()
        )
        if config is None:
            # 创建默认配置
            config = VoiceConfigDB(
                user_id=self.user_id,
                voice_type=DEFAULT_VOICE_TYPE,
                voice_speed=1.0,
                voice_pitch=1.0,
                prefer_online=True,
                asr_model_size="small",
                asr_language="zh",
                wake_words=DEFAULT_WAKE_WORDS,
                vad_threshold=0.5,
                vad_min_speech=0.3,
                vad_max_silence=0.5,
                tts_output_format="mp3",
            )
            self.db.add(config)
            self.db.commit()
            self.db.refresh(config)

        return config.to_dict()

    def update_config(self, update_data: dict[str, Any]) -> dict[str, Any]:
        """更新用户语音配置.

        Args:
            update_data: 要更新的配置字段字典

        Returns:
            更新后的配置字典
        """
        config = (
            self.db.query(VoiceConfigDB)
            .filter(VoiceConfigDB.user_id == self.user_id)
            .first()
        )
        if config is None:
            # 先创建默认配置
            self.get_config()
            config = (
                self.db.query(VoiceConfigDB)
                .filter(VoiceConfigDB.user_id == self.user_id)
                .first()
            )

        # 更新允许的字段
        allowed_fields = [
            "voice_type", "voice_speed", "voice_pitch",
            "prefer_online", "asr_model_size", "asr_language",
            "wake_words", "vad_threshold", "vad_min_speech",
            "vad_max_silence", "tts_output_format",
        ]
        for field in allowed_fields:
            if field in update_data and update_data[field] is not None:
                setattr(config, field, update_data[field])

        config.updated_at = datetime.utcnow()
        self.db.commit()
        self.db.refresh(config)

        return config.to_dict()

    # ------------------------------------------------------------------
    # 语音状态
    # ------------------------------------------------------------------

    def get_status(self) -> dict[str, Any]:
        """获取语音服务状态.

        Returns:
            语音服务状态字典
        """
        config = self.get_config()
        return {
            "tts_available": True,  # mock 模式下始终可用
            "asr_available": True,
            "tts_engine": "mock",
            "asr_engine": "mock",
            "tts_engines": TTS_ENGINES,
            "asr_engines": ASR_ENGINES,
            "vad_engine": "mock",
            "vad_engines": ["mock", "silero", "webrtc"],
            "wake_words": config.get("wake_words", DEFAULT_WAKE_WORDS),
            "voice_options": AVAILABLE_VOICES,
            "note": "当前为 mock 模式，后续可接入真实语音引擎",
        }

    # ------------------------------------------------------------------
    # TTS 文本转语音
    # ------------------------------------------------------------------

    async def tts_synthesize(
        self,
        text: str,
        voice_type: Optional[str] = None,
        speed: Optional[float] = None,
        pitch: Optional[float] = None,
        output_format: str = "mp3",
    ) -> dict[str, Any]:
        """文本转语音（简化版 mock）.

        Args:
            text: 要合成的文本
            voice_type: 语音类型（可选，使用配置默认值）
            speed: 语速倍率（可选，0.5-2.0）
            pitch: 音调倍率（可选，0.5-2.0）
            output_format: 输出格式（mp3/wav）

        Returns:
            TTS 合成结果字典
        """
        config = self.get_config()
        actual_voice = voice_type or config["voice_type"]
        actual_speed = speed if speed is not None else config["voice_speed"]
        actual_pitch = pitch if pitch is not None else config["voice_pitch"]

        # 计算模拟音频时长（按中文字数估算）
        char_count = len(text)
        # 中文语速约 4-5 字/秒，乘以速度倍率
        estimated_duration = round(char_count / (4.5 * actual_speed), 2)

        audio_id = f"tts_{uuid.uuid4().hex[:12]}"
        audio_url = f"/api/v1/voice/audio/{audio_id}.{output_format}"

        # 记录历史
        history = VoiceHistoryDB(
            user_id=self.user_id,
            operation_type="tts",
            text=text,
            audio_id=audio_id,
            duration=estimated_duration,
            engine="mock",
            success=True,
            extra={
                "voice_type": actual_voice,
                "speed": actual_speed,
                "pitch": actual_pitch,
                "format": output_format,
            },
        )
        self.db.add(history)
        self.db.commit()

        return {
            "audio_id": audio_id,
            "audio_url": audio_url,
            "engine": "mock",
            "format": output_format,
            "duration": estimated_duration,
            "text": text,
            "voice_type": actual_voice,
            "speed": actual_speed,
            "pitch": actual_pitch,
            "is_mock": True,
        }

    # ------------------------------------------------------------------
    # ASR 语音转文本
    # ------------------------------------------------------------------

    async def asr_transcribe(
        self,
        audio_data: bytes,
        filename: str = "audio.webm",
        language: Optional[str] = None,
    ) -> dict[str, Any]:
        """语音转文本（简化版 mock）.

        Args:
            audio_data: 音频文件二进制数据
            filename: 文件名
            language: 语言（zh/en/auto）

        Returns:
            ASR 识别结果字典
        """
        config = self.get_config()
        actual_language = language or config["asr_language"]

        # mock 模式：返回模拟识别结果
        mock_texts = {
            "zh": "你好云汐，今天天气怎么样？",
            "en": "Hello Yunxi, what's the weather today?",
            "auto": "你好云汐，今天天气怎么样？",
        }
        text = mock_texts.get(actual_language, mock_texts["zh"])

        # 估算音频时长（按文件大小粗略估算）
        estimated_duration = round(len(audio_data) / (16000 * 2), 2)  # 假设 16kHz 16bit

        audio_id = f"asr_{uuid.uuid4().hex[:12]}"

        # 记录历史
        history = VoiceHistoryDB(
            user_id=self.user_id,
            operation_type="asr",
            text=text,
            audio_id=audio_id,
            duration=estimated_duration,
            engine="mock",
            success=True,
            extra={
                "language": actual_language,
                "filename": filename,
                "file_size": len(audio_data),
            },
        )
        self.db.add(history)
        self.db.commit()

        return {
            "text": text,
            "engine": "mock",
            "language": actual_language,
            "duration": estimated_duration,
            "segments": [
                {
                    "start": 0.0,
                    "end": estimated_duration,
                    "text": text,
                    "confidence": 0.95,
                }
            ],
            "is_mock": True,
        }

    # ------------------------------------------------------------------
    # VAD 语音活动检测
    # ------------------------------------------------------------------

    async def vad_detect(
        self,
        audio_data: bytes,
        threshold: float = 0.5,
        min_speech_duration: float = 0.3,
        max_silence_duration: float = 0.5,
    ) -> dict[str, Any]:
        """语音活动检测（简化版 mock）.

        Args:
            audio_data: 音频文件二进制数据
            threshold: 检测阈值
            min_speech_duration: 最小说话时长（秒）
            max_silence_duration: 最大静音时长（秒）

        Returns:
            VAD 检测结果字典
        """
        # 估算音频时长
        duration = round(len(audio_data) / (16000 * 2), 2)

        # mock 模式：假设检测到一段语音
        speech_segments = []
        if duration > 1.0:
            speech_segments = [
                {
                    "start": 0.5,
                    "end": duration - 0.5,
                    "duration": duration - 1.0,
                    "confidence": 0.85,
                }
            ]

        # 记录历史
        history = VoiceHistoryDB(
            user_id=self.user_id,
            operation_type="vad",
            text="",
            audio_id=f"vad_{uuid.uuid4().hex[:12]}",
            duration=duration,
            engine="mock",
            success=True,
            extra={
                "threshold": threshold,
                "min_speech_duration": min_speech_duration,
                "max_silence_duration": max_silence_duration,
                "speech_segments_count": len(speech_segments),
            },
        )
        self.db.add(history)
        self.db.commit()

        return {
            "has_speech": len(speech_segments) > 0,
            "speech_segments": speech_segments,
            "total_speech_duration": sum(s["duration"] for s in speech_segments),
            "total_duration": duration,
            "engine": "mock",
            "threshold": threshold,
            "is_mock": True,
        }

    # ------------------------------------------------------------------
    # 唤醒词
    # ------------------------------------------------------------------

    def get_wake_word_config(self) -> dict[str, Any]:
        """获取唤醒词配置.

        Returns:
            唤醒词配置字典
        """
        config = self.get_config()
        return {
            "wake_words": config.get("wake_words", DEFAULT_WAKE_WORDS),
            "default_words": DEFAULT_WAKE_WORDS,
            "vad_engine": "mock",
            "asr_engine": "mock",
            "note": "当前为 mock 模式",
        }

    def update_wake_word_config(self, wake_words: list[str]) -> dict[str, Any]:
        """更新唤醒词配置.

        Args:
            wake_words: 唤醒词列表

        Returns:
            更新后的唤醒词配置

        Raises:
            ValueError: 唤醒词列表为空
        """
        if not wake_words or len(wake_words) == 0:
            raise ValueError("唤醒词列表不能为空")

        config = self.update_config({"wake_words": wake_words})
        return {
            "wake_words": config.get("wake_words", wake_words),
        }

    def add_wake_word(self, word: str) -> dict[str, Any]:
        """添加单个唤醒词.

        Args:
            word: 要添加的唤醒词

        Returns:
            更新后的唤醒词列表
        """
        if not word or not word.strip():
            raise ValueError("唤醒词不能为空")

        config = self.get_config()
        wake_words = list(config.get("wake_words", DEFAULT_WAKE_WORDS))
        word = word.strip()

        if word in wake_words:
            raise ValueError("唤醒词已存在")

        wake_words.append(word)
        updated = self.update_config({"wake_words": wake_words})

        return {
            "wake_words": updated.get("wake_words", wake_words),
            "added": word,
        }

    def remove_wake_word(self, word: str) -> dict[str, Any]:
        """移除唤醒词.

        Args:
            word: 要移除的唤醒词

        Returns:
            更新后的唤醒词列表
        """
        if not word or not word.strip():
            raise ValueError("唤醒词不能为空")

        config = self.get_config()
        wake_words = list(config.get("wake_words", DEFAULT_WAKE_WORDS))
        word = word.strip()

        if word not in wake_words:
            raise ValueError("唤醒词不存在")

        if len(wake_words) <= 1:
            raise ValueError("至少需要保留一个唤醒词")

        wake_words.remove(word)
        updated = self.update_config({"wake_words": wake_words})

        return {
            "wake_words": updated.get("wake_words", wake_words),
            "removed": word,
        }

    async def wake_word_detect(
        self,
        audio_data: bytes,
        language: str = "zh",
    ) -> dict[str, Any]:
        """唤醒词检测（简化版 mock）.

        Args:
            audio_data: 音频文件二进制数据
            language: 语言

        Returns:
            唤醒词检测结果
        """
        config = self.get_config()
        wake_words = config.get("wake_words", DEFAULT_WAKE_WORDS)

        # mock 模式：随机检测到第一个唤醒词
        detected = len(audio_data) > 1000  # 音频足够大就认为检测到

        result = {
            "detected": detected,
            "wake_word": wake_words[0] if detected and wake_words else "",
            "confidence": 0.92 if detected else 0.0,
            "engine": "mock",
            "language": language,
            "is_mock": True,
        }

        # 记录历史
        history = VoiceHistoryDB(
            user_id=self.user_id,
            operation_type="wake_word",
            text=result["wake_word"],
            audio_id=f"wake_{uuid.uuid4().hex[:12]}",
            duration=round(len(audio_data) / (16000 * 2), 2),
            engine="mock",
            success=detected,
            extra={"confidence": result["confidence"]},
        )
        self.db.add(history)
        self.db.commit()

        return result

    # ------------------------------------------------------------------
    # 语音选项
    # ------------------------------------------------------------------

    def get_voice_options(self) -> dict[str, Any]:
        """获取可用语音列表.

        Returns:
            可用语音列表字典
        """
        return {
            "voices": AVAILABLE_VOICES,
            "engine": "mock",
            "current_voice": self.get_config().get("voice_type", DEFAULT_VOICE_TYPE),
        }

    # ------------------------------------------------------------------
    # 调用历史
    # ------------------------------------------------------------------

    def get_history(
        self,
        operation_type: Optional[str] = None,
        page: int = 1,
        page_size: int = 20,
    ) -> dict[str, Any]:
        """获取语音调用历史.

        Args:
            operation_type: 按操作类型过滤（tts/asr/vad/wake_word）
            page: 页码
            page_size: 每页数量

        Returns:
            分页历史记录
        """
        query = self.db.query(VoiceHistoryDB).filter(
            VoiceHistoryDB.user_id == self.user_id,
        )

        if operation_type:
            query = query.filter(VoiceHistoryDB.operation_type == operation_type)

        total = query.count()
        records = (
            query.order_by(VoiceHistoryDB.created_at.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
            .all()
        )

        return {
            "records": [r.to_dict() for r in records],
            "total": total,
            "page": page,
            "page_size": page_size,
        }
