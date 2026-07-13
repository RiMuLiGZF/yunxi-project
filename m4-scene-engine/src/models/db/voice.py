"""语音服务表模块.

包含配置、调用历史等 ORM 模型。
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Float,
    Index,
    Integer,
    JSON,
    String,
    Text,
)

from .base import Base


class VoiceConfigDB(Base):
    """语音服务 - 配置表."""

    __tablename__ = "voice_configs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(String(128), nullable=False, default="default", unique=True, index=True)
    voice_type = Column(String(50), default="warm_female")
    voice_speed = Column(Float, default=1.0)
    voice_pitch = Column(Float, default=1.0)
    prefer_online = Column(Boolean, default=True)
    asr_model_size = Column(String(20), default="small")
    asr_language = Column(String(10), default="zh")
    wake_words = Column(JSON, default=list)  # ["云汐", "你好云汐"]
    vad_threshold = Column(Float, default=0.5)
    vad_min_speech = Column(Float, default=0.3)
    vad_max_silence = Column(Float, default=0.5)
    tts_output_format = Column(String(10), default="mp3")
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    def to_dict(self) -> dict[str, Any]:
        """转换为字典."""
        return {
            "voice_type": self.voice_type,
            "voice_speed": self.voice_speed,
            "voice_pitch": self.voice_pitch,
            "prefer_online": self.prefer_online,
            "asr_model_size": self.asr_model_size,
            "asr_language": self.asr_language,
            "wake_words": self.wake_words or ["云汐", "你好云汐"],
            "vad_threshold": self.vad_threshold,
            "vad_min_speech_duration": self.vad_min_speech,
            "vad_max_silence_duration": self.vad_max_silence,
            "tts_output_format": self.tts_output_format,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


class VoiceHistoryDB(Base):
    """语音服务 - 调用历史表."""

    __tablename__ = "voice_history"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(String(128), nullable=False, default="default", index=True)
    operation_type = Column(String(20), nullable=False, index=True)  # tts/asr/vad/wake_word
    text = Column(Text, default="")  # TTS 输入文本 或 ASR 识别结果
    audio_id = Column(String(64), default="")
    duration = Column(Float, default=0.0)  # 音频时长（秒）
    engine = Column(String(50), default="mock")
    success = Column(Boolean, default=True)
    error_msg = Column(String(255), default="")
    extra = Column(JSON, default=dict)
    created_at = Column(DateTime, default=datetime.utcnow, index=True)

    __table_args__ = (
        Index("idx_voice_hist_user", "user_id", "created_at"),
        Index("idx_voice_hist_op", "operation_type", "created_at"),
    )

    def to_dict(self) -> dict[str, Any]:
        """转换为字典."""
        return {
            "id": self.id,
            "operation_type": self.operation_type,
            "text": self.text,
            "audio_id": self.audio_id,
            "duration": self.duration,
            "engine": self.engine,
            "success": self.success,
            "error_msg": self.error_msg,
            "extra": self.extra or {},
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }
