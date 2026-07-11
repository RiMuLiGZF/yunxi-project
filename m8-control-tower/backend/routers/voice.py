"""
语音服务路由
- TTS: 文本转语音
- ASR: 语音转文本
- 语音配置
"""

import os
import sys
import uuid
import tempfile
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, UploadFile, File, Form, HTTPException
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel

# 确保 shared 目录在路径中
_current_dir = os.path.dirname(os.path.abspath(__file__))
_shared_dir = os.path.join(_current_dir, '..', '..', '..', 'shared')
if _shared_dir not in sys.path:
    sys.path.insert(0, _shared_dir)

try:
    from voice_engine import get_tts_engine, get_asr_engine, AudioUtils
    _voice_available = True
except ImportError:
    _voice_available = False

router = APIRouter(tags=["语音服务"])

# 临时音频文件目录
_temp_audio_dir = os.path.join(tempfile.gettempdir(), 'yunxi_voice')
os.makedirs(_temp_audio_dir, exist_ok=True)


# ===== 请求模型 =====

class TTSRequest(BaseModel):
    text: str
    voice_type: Optional[str] = None  # warm_female/clear_female/gentle_male/cute_child/robot
    speed: Optional[float] = None  # 语速倍率 0.5-2.0
    pitch: Optional[float] = None  # 音调倍率 0.5-2.0
    output_format: Optional[str] = "mp3"  # mp3/wav


class ASRRequest(BaseModel):
    language: Optional[str] = "zh"  # zh/en/auto


class VoiceConfigUpdate(BaseModel):
    voice_type: Optional[str] = None
    voice_speed: Optional[float] = None
    voice_pitch: Optional[float] = None
    prefer_online: Optional[bool] = None
    asr_model_size: Optional[str] = None


# ===== 工具函数 =====

def _get_config_from_db():
    """从数据库获取语音配置（如果M8的appearance模块可用）"""
    # 简化处理：使用环境变量或默认值
    return {
        'voice_type': os.environ.get('VOICE_TYPE', 'warm_female'),
        'voice_speed': float(os.environ.get('VOICE_SPEED', '1.0')),
        'voice_pitch': float(os.environ.get('VOICE_PITCH', '1.0')),
        'prefer_online': os.environ.get('VOICE_PREFER_ONLINE', 'true').lower() == 'true',
        'model_size': os.environ.get('ASR_MODEL_SIZE', 'small'),
    }


# ===== 语音状态 =====

@router.get("/status")
async def voice_status():
    """获取语音服务状态"""
    if not _voice_available:
        return {
            "code": 0,
            "message": "ok",
            "data": {
                "tts_available": False,
                "asr_available": False,
                "tts_engine": "none",
                "asr_engine": "none",
                "note": "语音模块未安装",
            }
        }

    tts = get_tts_engine(_get_config_from_db())
    asr = get_asr_engine(_get_config_from_db())

    return {
        "code": 0,
        "message": "ok",
        "data": {
            "tts_available": tts.current_engine != 'mock',
            "asr_available": asr.current_engine != 'mock',
            "tts_engine": tts.current_engine,
            "asr_engine": asr.current_engine,
            "tts_engines": tts.available_engines,
            "asr_engines": asr.available_engines,
            "voice_options": tts.get_voice_options(),
        }
    }


# ===== TTS 语音合成 =====

@router.post("/tts/synthesize")
async def tts_synthesize(req: TTSRequest):
    """文本转语音（返回音频文件URL）"""
    if not _voice_available:
        raise HTTPException(status_code=500, detail="语音模块未安装")

    config = _get_config_from_db()
    if req.voice_type:
        config['voice_type'] = req.voice_type
    if req.speed:
        config['voice_speed'] = req.speed
    if req.pitch:
        config['voice_pitch'] = req.pitch

    tts = get_tts_engine(config)

    # 生成输出文件名
    output_file = os.path.join(_temp_audio_dir, f"tts_{uuid.uuid4().hex[:12]}.mp3")

    result = await tts.synthesize(req.text, output_file)

    if not result.get('success'):
        raise HTTPException(status_code=500, detail=result.get('error', '语音合成失败'))

    # 返回文件URL和元数据
    audio_id = Path(result['audio_path']).stem if result.get('audio_path') else None

    return {
        "code": 0,
        "message": "ok",
        "data": {
            "audio_id": audio_id,
            "audio_url": f"/api/voice/audio/{audio_id}.mp3" if audio_id else None,
            "engine": result.get('engine'),
            "format": result.get('audio_format', 'mp3'),
            "duration": result.get('duration', 0),
            "text": req.text,
        }
    }


@router.get("/tts/stream")
async def tts_stream(text: str, voice_type: Optional[str] = None):
    """文本转语音（直接返回音频文件流）"""
    if not _voice_available:
        raise HTTPException(status_code=500, detail="语音模块未安装")

    config = _get_config_from_db()
    if voice_type:
        config['voice_type'] = voice_type

    tts = get_tts_engine(config)

    output_file = os.path.join(_temp_audio_dir, f"tts_{uuid.uuid4().hex[:12]}.mp3")
    result = await tts.synthesize(text, output_file)

    if not result.get('success') or not result.get('audio_path'):
        raise HTTPException(status_code=500, detail=result.get('error', '语音合成失败'))

    return FileResponse(
        result['audio_path'],
        media_type="audio/mpeg",
        filename="speech.mp3"
    )


# ===== ASR 语音识别 =====

@router.post("/asr/transcribe")
async def asr_transcribe(
    file: UploadFile = File(...),
    language: str = Form("zh"),
):
    """语音转文本（上传音频文件）"""
    if not _voice_available:
        raise HTTPException(status_code=500, detail="语音模块未安装")

    # 保存上传的文件
    suffix = Path(file.filename).suffix or '.webm'
    input_file = os.path.join(_temp_audio_dir, f"asr_input_{uuid.uuid4().hex[:12]}{suffix}")

    with open(input_file, 'wb') as f:
        content = await file.read()
        f.write(content)

    # 如果不是WAV格式，先转换
    wav_file = input_file
    if suffix.lower() not in ['.wav']:
        wav_file = os.path.join(_temp_audio_dir, f"asr_wav_{uuid.uuid4().hex[:12]}.wav")
        if not AudioUtils.convert_format(input_file, wav_file, 16000, 1):
            # 转换失败，尝试直接识别（faster-whisper支持多种格式）
            wav_file = input_file

    config = _get_config_from_db()
    if language:
        config['language'] = language if language != 'auto' else None

    asr = get_asr_engine(config)
    result = asr.transcribe(wav_file, language if language != 'auto' else None)

    # 清理临时文件
    try:
        if input_file != wav_file and os.path.exists(input_file):
            os.remove(input_file)
        # 不立即删除wav文件，可能被缓存使用
    except Exception:
        pass

    if not result.get('success'):
        raise HTTPException(status_code=500, detail=result.get('error', '语音识别失败'))

    return {
        "code": 0,
        "message": "ok",
        "data": {
            "text": result.get('text', ''),
            "engine": result.get('engine'),
            "language": result.get('language', language),
            "duration": result.get('duration', 0),
            "segments": result.get('segments', []),
        }
    }


# ===== 音频文件访问 =====

@router.get("/audio/{filename}")
async def get_audio_file(filename: str):
    """获取临时音频文件"""
    # 安全检查：防止路径遍历
    if '..' in filename or '/' in filename or '\\' in filename:
        raise HTTPException(status_code=400, detail="无效的文件名")

    filepath = os.path.join(_temp_audio_dir, filename)
    if not os.path.exists(filepath):
        raise HTTPException(status_code=404, detail="音频文件不存在")

    # 根据扩展名设置MIME类型
    ext = Path(filename).suffix.lower()
    mime_types = {
        '.mp3': 'audio/mpeg',
        '.wav': 'audio/wav',
        '.ogg': 'audio/ogg',
        '.webm': 'audio/webm',
    }
    media_type = mime_types.get(ext, 'audio/mpeg')

    return FileResponse(filepath, media_type=media_type)


# ===== 语音配置 =====

@router.get("/config")
async def get_voice_config():
    """获取语音配置"""
    config = _get_config_from_db()
    return {
        "code": 0,
        "message": "ok",
        "data": config,
    }


@router.put("/config")
async def update_voice_config(config: VoiceConfigUpdate):
    """更新语音配置（运行时生效，不持久化）"""
    current = _get_config_from_db()

    if config.voice_type:
        current['voice_type'] = config.voice_type
    if config.voice_speed is not None:
        current['voice_speed'] = config.voice_speed
    if config.voice_pitch is not None:
        current['voice_pitch'] = config.voice_pitch
    if config.prefer_online is not None:
        current['prefer_online'] = config.prefer_online

    # 更新引擎配置
    if _voice_available:
        tts = get_tts_engine()
        tts.update_config(
            voice_type=current['voice_type'],
            voice_speed=current['voice_speed'],
            voice_pitch=current['voice_pitch'],
            prefer_online=current['prefer_online'],
        )

    return {
        "code": 0,
        "message": "配置已更新",
        "data": current,
    }


# ===== 语音选项 =====

@router.get("/voices")
async def list_voices():
    """获取可用语音列表"""
    if not _voice_available:
        return {
            "code": 0,
            "message": "ok",
            "data": {
                "voices": [],
                "engine": "none",
            }
        }

    tts = get_tts_engine(_get_config_from_db())
    return {
        "code": 0,
        "message": "ok",
        "data": {
            "voices": tts.get_voice_options(),
            "engine": tts.current_engine,
        }
    }
