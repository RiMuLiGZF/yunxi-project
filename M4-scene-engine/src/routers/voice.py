"""语音服务 - FastAPI 路由.

提供语音服务的 REST API 接口，包括 TTS、ASR、VAD、唤醒词配置等。
"""

from __future__ import annotations

from typing import Optional, List

from fastapi import APIRouter, Depends, Query, UploadFile, File, Form, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from src.models.db import get_session
from src.models import make_response
from src.services.voice_service import VoiceService


router = APIRouter(prefix="/api/v1/voice", tags=["语音服务"])


# ---------------------------------------------------------------------------
# 请求模型
# ---------------------------------------------------------------------------


class TTSRequest(BaseModel):
    """文本转语音请求体."""

    text: str = Field(..., description="要合成的文本")
    voice_type: Optional[str] = Field(None, description="语音类型")
    speed: Optional[float] = Field(None, description="语速倍率 0.5-2.0", ge=0.5, le=2.0)
    pitch: Optional[float] = Field(None, description="音调倍率 0.5-2.0", ge=0.5, le=2.0)
    output_format: str = Field("mp3", description="输出格式 mp3/wav")


class VoiceConfigUpdate(BaseModel):
    """语音配置更新请求体."""

    voice_type: Optional[str] = Field(None, description="语音类型")
    voice_speed: Optional[float] = Field(None, description="语速倍率", ge=0.5, le=2.0)
    voice_pitch: Optional[float] = Field(None, description="音调倍率", ge=0.5, le=2.0)
    prefer_online: Optional[bool] = Field(None, description="是否优先使用在线服务")
    asr_model_size: Optional[str] = Field(None, description="ASR 模型大小")
    asr_language: Optional[str] = Field(None, description="ASR 默认语言")
    tts_output_format: Optional[str] = Field(None, description="TTS 输出格式")


class WakeWordConfigUpdate(BaseModel):
    """唤醒词配置更新请求体."""

    wake_words: List[str] = Field(..., description="唤醒词列表")


# ---------------------------------------------------------------------------
# 依赖注入
# ---------------------------------------------------------------------------


def get_voice_service(
    db: Session = Depends(get_session),
    user_id: str = Query("default", description="用户ID"),
) -> VoiceService:
    """获取语音服务实例.

    Args:
        db: 数据库会话
        user_id: 用户ID

    Returns:
        语音服务实例
    """
    return VoiceService(db, user_id=user_id)


# ---------------------------------------------------------------------------
# 语音状态
# ---------------------------------------------------------------------------


@router.get("/status", summary="获取语音服务状态")
async def voice_status(
    service: VoiceService = Depends(get_voice_service),
):
    """获取语音服务状态，包括 TTS/ASR 引擎可用性等."""
    result = service.get_status()
    return make_response(data=result, message="ok")


# ---------------------------------------------------------------------------
# TTS 文本转语音
# ---------------------------------------------------------------------------


@router.post("/tts/synthesize", summary="文本转语音")
async def tts_synthesize(
    req: TTSRequest,
    service: VoiceService = Depends(get_voice_service),
):
    """将文本合成为语音，返回音频文件 URL.

    简化版实现：返回 mock 音频 URL，预留真实 TTS 引擎接入点。
    """
    result = await service.tts_synthesize(
        text=req.text,
        voice_type=req.voice_type,
        speed=req.speed,
        pitch=req.pitch,
        output_format=req.output_format,
    )
    return make_response(data=result, message="ok")


# ---------------------------------------------------------------------------
# ASR 语音转文本
# ---------------------------------------------------------------------------


@router.post("/asr/transcribe", summary="语音转文本")
async def asr_transcribe(
    file: UploadFile = File(..., description="音频文件"),
    language: str = Form("zh", description="语言：zh/en/auto"),
    service: VoiceService = Depends(get_voice_service),
):
    """将上传的音频文件转写为文本.

    简化版实现：返回 mock 文本，预留真实 ASR 引擎接入点。
    """
    audio_data = await file.read()
    if not audio_data:
        return make_response(code=400, message="音频文件不能为空", data={})

    result = await service.asr_transcribe(
        audio_data=audio_data,
        filename=file.filename or "audio.webm",
        language=language,
    )
    return make_response(data=result, message="ok")


# ---------------------------------------------------------------------------
# VAD 语音活动检测
# ---------------------------------------------------------------------------


@router.post("/vad/detect", summary="语音活动检测")
async def vad_detect(
    file: UploadFile = File(..., description="音频文件"),
    threshold: float = Form(0.5, description="检测阈值"),
    min_speech_duration: float = Form(0.3, description="最小说话时长（秒）"),
    max_silence_duration: float = Form(0.5, description="最大静音时长（秒）"),
    service: VoiceService = Depends(get_voice_service),
):
    """检测音频文件中的语音活动片段.

    简化版实现：返回 mock 检测结果，预留真实 VAD 引擎接入点。
    """
    audio_data = await file.read()
    if not audio_data:
        return make_response(code=400, message="音频文件不能为空", data={})

    result = await service.vad_detect(
        audio_data=audio_data,
        threshold=threshold,
        min_speech_duration=min_speech_duration,
        max_silence_duration=max_silence_duration,
    )
    return make_response(data=result, message="ok")


# ---------------------------------------------------------------------------
# 唤醒词
# ---------------------------------------------------------------------------


@router.get("/wake-word/config", summary="获取唤醒词配置")
async def get_wake_word_config(
    service: VoiceService = Depends(get_voice_service),
):
    """获取当前唤醒词配置."""
    result = service.get_wake_word_config()
    return make_response(data=result, message="ok")


@router.put("/wake-word/config", summary="更新唤醒词配置")
async def update_wake_word_config(
    req: WakeWordConfigUpdate,
    service: VoiceService = Depends(get_voice_service),
):
    """更新唤醒词配置（支持设置多个唤醒词）."""
    try:
        result = service.update_wake_word_config(req.wake_words)
        return make_response(data=result, message="唤醒词配置已更新")
    except ValueError as e:
        return make_response(code=400, message=str(e), data={})


@router.post("/wake-word/add", summary="添加唤醒词")
async def add_wake_word(
    word: str = Query(..., description="要添加的唤醒词"),
    service: VoiceService = Depends(get_voice_service),
):
    """添加单个唤醒词."""
    try:
        result = service.add_wake_word(word)
        return make_response(data=result, message="唤醒词已添加")
    except ValueError as e:
        return make_response(code=400, message=str(e), data={})


@router.delete("/wake-word/remove", summary="移除唤醒词")
async def remove_wake_word(
    word: str = Query(..., description="要移除的唤醒词"),
    service: VoiceService = Depends(get_voice_service),
):
    """移除指定的唤醒词（至少保留一个）."""
    try:
        result = service.remove_wake_word(word)
        return make_response(data=result, message="唤醒词已移除")
    except ValueError as e:
        return make_response(code=400, message=str(e), data={})


@router.post("/wake-word/detect", summary="唤醒词检测")
async def wake_word_detect(
    file: UploadFile = File(..., description="音频文件"),
    language: str = Form("zh", description="语言"),
    service: VoiceService = Depends(get_voice_service),
):
    """检测音频文件中是否包含唤醒词.

    简化版实现：返回 mock 检测结果。
    """
    audio_data = await file.read()
    if not audio_data:
        return make_response(code=400, message="音频文件不能为空", data={})

    result = await service.wake_word_detect(
        audio_data=audio_data,
        language=language,
    )
    return make_response(data=result, message="ok")


# ---------------------------------------------------------------------------
# 语音配置
# ---------------------------------------------------------------------------


@router.get("/config", summary="获取语音配置")
async def get_voice_config(
    service: VoiceService = Depends(get_voice_service),
):
    """获取用户的语音配置."""
    result = service.get_config()
    return make_response(data=result, message="ok")


@router.put("/config", summary="更新语音配置")
async def update_voice_config(
    req: VoiceConfigUpdate,
    service: VoiceService = Depends(get_voice_service),
):
    """更新用户的语音配置."""
    update_data = req.dict(exclude_unset=True)
    result = service.update_config(update_data)
    return make_response(data=result, message="配置已更新")


# ---------------------------------------------------------------------------
# 语音选项
# ---------------------------------------------------------------------------


@router.get("/voices", summary="获取可用语音列表")
async def list_voices(
    service: VoiceService = Depends(get_voice_service),
):
    """获取所有可用的语音类型."""
    result = service.get_voice_options()
    return make_response(data=result, message="ok")


# ---------------------------------------------------------------------------
# 调用历史
# ---------------------------------------------------------------------------


@router.get("/history", summary="获取语音调用历史")
async def voice_history(
    operation_type: Optional[str] = Query(None, description="按操作类型过滤：tts/asr/vad/wake_word"),
    page: int = Query(1, ge=1, description="页码"),
    page_size: int = Query(20, ge=1, le=100, description="每页数量"),
    service: VoiceService = Depends(get_voice_service),
):
    """获取语音服务的调用历史记录."""
    result = service.get_history(
        operation_type=operation_type,
        page=page,
        page_size=page_size,
    )
    return make_response(data=result, message="ok")
