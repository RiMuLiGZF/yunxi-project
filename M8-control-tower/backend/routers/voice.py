"""
语音服务路由
- TTS: 文本转语音
- ASR: 语音转文本
- VAD: 语音活动检测
- 唤醒词检测与配置
- 流式识别
- 语音配置
"""

import os
import sys
import uuid
import tempfile
from pathlib import Path
from typing import Optional, List

from fastapi import APIRouter, UploadFile, File, Form, HTTPException, WebSocket, WebSocketDisconnect
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
    emotion: Optional[str] = None  # 情感（warm/happy/sad/calm/excited 等，仅 CosyVoice 支持）
    instruction: Optional[str] = None  # 自定义指令（仅 CosyVoice 支持）
    scene: Optional[str] = None  # 场景上下文（用于韵律计算）
    voice_preset: Optional[str] = None  # 音色预设ID（CosyVoice 音色克隆用）


class ASRRequest(BaseModel):
    language: Optional[str] = "zh"  # zh/en/auto


class VoiceConfigUpdate(BaseModel):
    voice_type: Optional[str] = None
    voice_speed: Optional[float] = None
    voice_pitch: Optional[float] = None
    prefer_online: Optional[bool] = None
    asr_model_size: Optional[str] = None
    # CosyVoice 配置
    use_cosyvoice: Optional[bool] = None
    cosyvoice_api_url: Optional[str] = None
    cosyvoice_speaker_id: Optional[str] = None
    cosyvoice_emotion: Optional[str] = None
    cosyvoice_method: Optional[str] = None  # zero_shot / instruct / cross_lingual


class WakeWordConfig(BaseModel):
    """唤醒词配置请求"""
    wake_words: List[str]


class WakeWordDetectRequest(BaseModel):
    """唤醒词检测请求（文本模式，用于测试）"""
    text: str
    wake_words: Optional[List[str]] = None


class VADRequest(BaseModel):
    """VAD检测请求参数"""
    threshold: Optional[float] = 0.5
    min_speech_duration: Optional[float] = 0.3
    max_silence_duration: Optional[float] = 0.5


# ===== 工具函数 =====

def _get_config_from_db():
    """从数据库获取语音配置（如果M8的appearance模块可用）"""
    # 简化处理：使用环境变量或默认值
    wake_words_env = os.environ.get('WAKE_WORDS', '')
    wake_words = [w.strip() for w in wake_words_env.split(',') if w.strip()] if wake_words_env else ['云汐', '你好云汐']
    return {
        'voice_type': os.environ.get('VOICE_TYPE', 'warm_female'),
        'voice_speed': float(os.environ.get('VOICE_SPEED', '1.0')),
        'voice_pitch': float(os.environ.get('VOICE_PITCH', '1.0')),
        'prefer_online': os.environ.get('VOICE_PREFER_ONLINE', 'true').lower() == 'true',
        'model_size': os.environ.get('ASR_MODEL_SIZE', 'small'),
        'wake_words': wake_words,
        # CosyVoice 配置
        'use_cosyvoice': os.environ.get('USE_COSYVOICE', 'false').lower() == 'true',
        'cosyvoice_api_url': os.environ.get('COSYVOICE_API_URL', 'http://localhost:50000'),
        'cosyvoice_speaker_id': os.environ.get('COSYVOICE_SPEAKER_ID', 'yunxi_default'),
        'cosyvoice_emotion': os.environ.get('COSYVOICE_EMOTION', 'warm'),
        'cosyvoice_method': os.environ.get('COSYVOICE_METHOD', 'instruct'),
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
            "vad_engine": asr.current_vad_engine,
            "vad_engines": asr.available_vad_engines,
            "wake_words": asr.wake_words,
            "voice_options": tts.get_voice_options(),
        }
    }


# ===== TTS 语音合成 =====

@router.post("/tts/synthesize")
async def tts_synthesize(req: TTSRequest, user_id: Optional[str] = None):
    """文本转语音（返回音频文件URL）
    
    支持情感控制、场景韵律、CosyVoice 音色克隆等高级功能。
    如果提供了 user_id，会自动从用户画像中应用语音偏好。
    """
    if not _voice_available:
        raise HTTPException(status_code=500, detail="语音模块未安装")

    config = _get_config_from_db()
    
    # 从用户画像加载语音偏好（如果有user_id）
    if user_id:
        try:
            from shared.user_profile import get_user_profile_manager
            profile_mgr = get_user_profile_manager()
            voice_prefs = profile_mgr.get_voice_preferences(user_id)
            # 用户未显式指定时使用画像偏好
            if not req.voice_type and voice_prefs.get("voice") and voice_prefs["voice"] != "default":
                config['voice_type'] = voice_prefs["voice"]
            if not req.speed and voice_prefs.get("speed"):
                config['voice_speed'] = voice_prefs["speed"]
            if not req.pitch and voice_prefs.get("pitch"):
                config['voice_pitch'] = voice_prefs["pitch"]
        except Exception:
            pass  # 画像不可用时静默降级
    
    if req.voice_type:
        config['voice_type'] = req.voice_type
    if req.speed:
        config['voice_speed'] = req.speed
    if req.pitch:
        config['voice_pitch'] = req.pitch

    tts = get_tts_engine(config)

    # 生成输出文件名
    ext = req.output_format if req.output_format in ['mp3', 'wav'] else 'mp3'
    output_file = os.path.join(_temp_audio_dir, f"tts_{uuid.uuid4().hex[:12]}.{ext}")

    # 使用韵律控制器计算情感/场景相关的指令（如果有 CosyVoice）
    emotion = req.emotion
    instruction = req.instruction
    
    # 如果指定了场景但没有指定情感，尝试从场景推断
    if req.scene and not emotion and not instruction:
        try:
            from prosody_controller import get_prosody_controller
            prosody_ctrl = get_prosody_controller()
            instruction = prosody_ctrl.generate_cosyvoice_instruction(
                text=req.text,
                scene=req.scene,
            )
        except Exception:
            pass

    # 如果指定了音色预设，更新 TTS 引擎配置
    if req.voice_preset:
        try:
            from voice_preset_manager import get_voice_preset_manager
            preset_mgr = get_voice_preset_manager()
            preset_info = preset_mgr.get_synthesis_params(req.voice_preset)
            if preset_info.get('speaker_id'):
                tts.update_config(
                    cosyvoice_speaker_id=preset_info['speaker_id'],
                )
            if preset_info.get('reference_audio'):
                tts.update_config(
                    cosyvoice_reference_audio=preset_info['reference_audio'],
                    cosyvoice_reference_text=preset_info.get('reference_text', ''),
                )
        except Exception:
            pass

    result = await tts.synthesize(
        req.text, output_file,
        emotion=emotion,
        instruction=instruction,
    )

    if not result.get('success'):
        raise HTTPException(status_code=500, detail=result.get('error', '语音合成失败'))

    # 返回文件URL和元数据
    audio_id = Path(result['audio_path']).stem if result.get('audio_path') else None

    return {
        "code": 0,
        "message": "ok",
        "data": {
            "audio_id": audio_id,
            "audio_url": f"/api/voice/audio/{audio_id}.{ext}" if audio_id else None,
            "engine": result.get('engine'),
            "format": result.get('audio_format', ext),
            "duration": result.get('duration', 0),
            "text": req.text,
            "emotion": result.get('emotion', emotion),
            "voice_preset": req.voice_preset,
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
    
    # CosyVoice 配置
    if config.use_cosyvoice is not None:
        current['use_cosyvoice'] = config.use_cosyvoice
    if config.cosyvoice_api_url:
        current['cosyvoice_api_url'] = config.cosyvoice_api_url
    if config.cosyvoice_speaker_id:
        current['cosyvoice_speaker_id'] = config.cosyvoice_speaker_id
    if config.cosyvoice_emotion:
        current['cosyvoice_emotion'] = config.cosyvoice_emotion
    if config.cosyvoice_method:
        current['cosyvoice_method'] = config.cosyvoice_method

    # 更新引擎配置
    if _voice_available:
        tts = get_tts_engine()
        update_kwargs = dict(
            voice_type=current['voice_type'],
            voice_speed=current['voice_speed'],
            voice_pitch=current['voice_pitch'],
            prefer_online=current['prefer_online'],
        )
        # 添加 CosyVoice 配置
        if 'use_cosyvoice' in current:
            update_kwargs['use_cosyvoice'] = current['use_cosyvoice']
        if 'cosyvoice_api_url' in current:
            update_kwargs['cosyvoice_api_url'] = current['cosyvoice_api_url']
        if 'cosyvoice_speaker_id' in current:
            update_kwargs['cosyvoice_speaker_id'] = current['cosyvoice_speaker_id']
        if 'cosyvoice_emotion' in current:
            update_kwargs['cosyvoice_emotion'] = current['cosyvoice_emotion']
        if 'cosyvoice_method' in current:
            update_kwargs['cosyvoice_method'] = current['cosyvoice_method']
        
        tts.update_config(**update_kwargs)

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


# ===== VAD 语音活动检测 =====

@router.post("/vad/detect")
async def vad_detect(
    file: UploadFile = File(...),
    threshold: float = Form(0.5),
    min_speech_duration: float = Form(0.3),
    max_silence_duration: float = Form(0.5),
):
    """语音活动检测（VAD）

    上传音频文件，检测其中的语音片段起止时间。
    """
    if not _voice_available:
        raise HTTPException(status_code=500, detail="语音模块未安装")

    # 保存上传的文件
    suffix = Path(file.filename).suffix or '.wav'
    input_file = os.path.join(_temp_audio_dir, f"vad_input_{uuid.uuid4().hex[:12]}{suffix}")

    with open(input_file, 'wb') as f:
        content = await file.read()
        f.write(content)

    try:
        asr = get_asr_engine(_get_config_from_db())
        result = asr.vad_detect(
            input_file,
            threshold=threshold,
            min_speech_duration=min_speech_duration,
            max_silence_duration=max_silence_duration,
        )
    finally:
        # 清理临时文件
        try:
            if os.path.exists(input_file):
                os.remove(input_file)
        except Exception:
            pass

    if not result.get('success'):
        raise HTTPException(status_code=500, detail=result.get('error', 'VAD检测失败'))

    return {
        "code": 0,
        "message": "ok",
        "data": result,
    }


# ===== 唤醒词检测 =====

@router.post("/wake-word/detect")
async def wake_word_detect(
    file: UploadFile = File(...),
    language: str = Form("zh"),
):
    """唤醒词检测（上传音频文件）

    检测流程：VAD检测语音片段 → ASR识别 → 关键词匹配
    返回是否检测到唤醒词及匹配结果。
    """
    if not _voice_available:
        raise HTTPException(status_code=500, detail="语音模块未安装")

    # 保存上传的文件
    suffix = Path(file.filename).suffix or '.wav'
    input_file = os.path.join(_temp_audio_dir, f"wake_input_{uuid.uuid4().hex[:12]}{suffix}")

    with open(input_file, 'wb') as f:
        content = await file.read()
        f.write(content)

    try:
        asr = get_asr_engine(_get_config_from_db())
        result = asr.detect_wake_word(
            input_file,
            wake_words=None,  # 使用配置的默认唤醒词
            language=language if language != 'auto' else None,
        )
    finally:
        # 清理临时文件
        try:
            if os.path.exists(input_file):
                os.remove(input_file)
        except Exception:
            pass

    if not result.get('success'):
        raise HTTPException(status_code=500, detail=result.get('error', '唤醒词检测失败'))

    return {
        "code": 0,
        "message": "ok",
        "data": result,
    }


# ===== 唤醒词配置 =====

@router.get("/wake-word/config")
async def get_wake_word_config():
    """获取唤醒词配置"""
    if not _voice_available:
        return {
            "code": 0,
            "message": "ok",
            "data": {
                "wake_words": ['云汐', '你好云汐'],
                "default_words": ['云汐', '你好云汐'],
                "note": "语音模块未安装，返回默认配置",
            }
        }

    asr = get_asr_engine(_get_config_from_db())
    return {
        "code": 0,
        "message": "ok",
        "data": {
            "wake_words": asr.wake_words,
            "default_words": ['云汐', '你好云汐'],
            "vad_engine": asr.current_vad_engine,
            "asr_engine": asr.current_engine,
        }
    }


@router.put("/wake-word/config")
async def update_wake_word_config(config: WakeWordConfig):
    """更新唤醒词配置（运行时生效）

    设置多个唤醒词，至少需要保留一个。
    """
    if not config.wake_words or len(config.wake_words) == 0:
        raise HTTPException(status_code=400, detail="唤醒词列表不能为空")

    if not _voice_available:
        # mock模式：直接返回（不持久化）
        return {
            "code": 0,
            "message": "配置已更新（mock模式）",
            "data": {
                "wake_words": config.wake_words,
            }
        }

    asr = get_asr_engine(_get_config_from_db())
    success = asr.set_wake_words(config.wake_words)

    if not success:
        raise HTTPException(status_code=400, detail="唤醒词配置失败")

    return {
        "code": 0,
        "message": "唤醒词配置已更新",
        "data": {
            "wake_words": asr.wake_words,
        }
    }


@router.post("/wake-word/add")
async def add_wake_word(word: str):
    """添加单个唤醒词"""
    if not word or not word.strip():
        raise HTTPException(status_code=400, detail="唤醒词不能为空")

    if not _voice_available:
        return {
            "code": 0,
            "message": "已添加（mock模式）",
            "data": {"word": word.strip()}
        }

    asr = get_asr_engine(_get_config_from_db())
    success = asr.add_wake_word(word)

    if not success:
        raise HTTPException(status_code=400, detail="添加失败（唤醒词可能已存在）")

    return {
        "code": 0,
        "message": "唤醒词已添加",
        "data": {
            "wake_words": asr.wake_words,
        }
    }


@router.delete("/wake-word/remove")
async def remove_wake_word(word: str):
    """移除唤醒词"""
    if not word or not word.strip():
        raise HTTPException(status_code=400, detail="唤醒词不能为空")

    if not _voice_available:
        return {
            "code": 0,
            "message": "已移除（mock模式）",
            "data": {"word": word.strip()}
        }

    asr = get_asr_engine(_get_config_from_db())
    success = asr.remove_wake_word(word)

    if not success:
        raise HTTPException(status_code=400, detail="移除失败（唤醒词不存在或仅剩一个）")

    return {
        "code": 0,
        "message": "唤醒词已移除",
        "data": {
            "wake_words": asr.wake_words,
        }
    }


# ===== 流式语音识别（HTTP SSE） =====

@router.post("/asr/streaming")
async def asr_streaming(
    file: UploadFile = File(...),
    language: str = Form("zh"),
    chunk_duration: float = Form(5.0),
    vad_filter: bool = Form(True),
):
    """流式语音识别（基于上传文件的分块识别）

    将音频文件按chunk_duration分块识别，返回所有识别片段结果。
    适合较长音频的渐进式识别。
    """
    if not _voice_available:
        raise HTTPException(status_code=500, detail="语音模块未安装")

    # 保存上传的文件
    suffix = Path(file.filename).suffix or '.wav'
    input_file = os.path.join(_temp_audio_dir, f"stream_input_{uuid.uuid4().hex[:12]}{suffix}")

    with open(input_file, 'wb') as f:
        content = await file.read()
        f.write(content)

    # 转换为WAV格式（16kHz单声道16bit PCM）
    wav_file = input_file
    if suffix.lower() not in ['.wav']:
        wav_file = os.path.join(_temp_audio_dir, f"stream_wav_{uuid.uuid4().hex[:12]}.wav")
        if not AudioUtils.convert_format(input_file, wav_file, 16000, 1):
            wav_file = input_file

    try:
        # 读取WAV文件的PCM数据
        import wave
        wf = wave.open(wav_file, 'rb')
        sample_rate = wf.getframerate()
        sample_width = wf.getsampwidth()
        channels = wf.getnchannels()

        # 如果不是16kHz单声道16bit，需要重新采样
        if sample_rate != 16000 or channels != 1 or sample_width != 2:
            # 尝试使用pydub转换
            converted_file = os.path.join(_temp_audio_dir, f"stream_conv_{uuid.uuid4().hex[:12]}.wav")
            if AudioUtils.convert_format(wav_file, converted_file, 16000, 1):
                wf.close()
                wf = wave.open(converted_file, 'rb')
                wav_file = converted_file
                sample_rate = wf.getframerate()
                sample_width = wf.getsampwidth()
                channels = wf.getnchannels()

        n_frames = wf.getnframes()
        pcm_data = wf.readframes(n_frames)
        wf.close()

        # 构建生成器（模拟流式输入）
        chunk_size = int(16000 * 0.5 * 2)  # 0.5秒的PCM数据量

        def audio_gen():
            for i in range(0, len(pcm_data), chunk_size):
                yield pcm_data[i:i + chunk_size]

        asr = get_asr_engine(_get_config_from_db())
        config = _get_config_from_db()
        if language:
            config['language'] = language if language != 'auto' else None

        # 收集所有识别结果
        segments = []
        full_text_parts = []
        for result in asr.streaming_transcribe(
            audio_gen(),
            language=language if language != 'auto' else None,
            chunk_duration=chunk_duration,
            vad_filter=vad_filter,
        ):
            if result.get('success') and result.get('text'):
                segments.append(result)
                full_text_parts.append(result['text'])

        return {
            "code": 0,
            "message": "ok",
            "data": {
                "full_text": ''.join(full_text_parts),
                "segments": segments,
                "segment_count": len(segments),
                "engine": asr.current_engine,
                "vad_engine": asr.current_vad_engine,
            }
        }

    finally:
        # 清理临时文件
        try:
            if input_file != wav_file and os.path.exists(input_file):
                os.remove(input_file)
            if os.path.exists(wav_file):
                os.remove(wav_file)
        except Exception:
            pass


# ===== 流式语音识别（WebSocket） =====

@router.websocket("/ws/asr/streaming")
async def ws_asr_streaming(websocket: WebSocket, language: str = "zh"):
    """WebSocket流式语音识别

    客户端通过WebSocket持续发送PCM音频数据（16kHz单声道16bit小端），
    服务端实时识别并返回识别结果。

    消息格式：
    - 客户端: 发送二进制PCM音频数据
    - 服务端: 返回JSON识别结果
        {
            "type": "partial" | "final",
            "text": "识别文本",
            "segment_index": 1,
            "engine": "faster-whisper"
        }

    客户端发送 {"type": "stop"} 的文本消息来结束识别。
    """
    await websocket.accept()

    if not _voice_available:
        await websocket.send_json({
            "type": "error",
            "message": "语音模块未安装，使用mock模式"
        })
        # mock模式：返回模拟结果
        try:
            while True:
                data = await websocket.receive()
                if data.get('type') == 'websocket.disconnect':
                    break
                if 'text' in data and data['text']:
                    try:
                        import json
                        msg = json.loads(data['text'])
                        if msg.get('type') == 'stop':
                            break
                    except Exception:
                        pass
                if 'bytes' in data and data['bytes']:
                    # mock：收到音频就返回模拟文本
                    await websocket.send_json({
                        "type": "final",
                        "text": "（mock模式）语音识别结果",
                        "segment_index": 1,
                        "engine": "mock",
                    })
        except WebSocketDisconnect:
            pass
        return

    asr = get_asr_engine(_get_config_from_db())

    # 音频缓冲
    audio_buffer = bytearray()
    sample_rate = 16000
    bytes_per_second = sample_rate * 2  # 16bit
    chunk_duration = 5.0  # 每5秒识别一次
    chunk_bytes = int(chunk_duration * bytes_per_second)
    segment_index = 0

    try:
        while True:
            data = await websocket.receive()

            if data.get('type') == 'websocket.disconnect':
                break

            # 处理文本消息（控制指令）
            if 'text' in data and data['text']:
                try:
                    import json
                    msg = json.loads(data['text'])
                    if msg.get('type') == 'stop':
                        # 处理剩余音频
                        if len(audio_buffer) > int(0.5 * bytes_per_second):
                            chunk_data = bytes(audio_buffer)
                            tmp_path = os.path.join(_temp_audio_dir, f"ws_final_{uuid.uuid4().hex[:12]}.wav")
                            asr._write_pcm_wav(chunk_data, sample_rate, tmp_path)
                            result = asr.transcribe(tmp_path, language if language != 'auto' else None)
                            try:
                                os.unlink(tmp_path)
                            except Exception:
                                pass
                            if result.get('success') and result.get('text', '').strip():
                                segment_index += 1
                                await websocket.send_json({
                                    "type": "final",
                                    "text": result['text'].strip(),
                                    "segment_index": segment_index,
                                    "engine": result.get('engine', 'mock'),
                                })
                        await websocket.send_json({
                            "type": "complete",
                            "total_segments": segment_index,
                        })
                        break
                except json.JSONDecodeError:
                    pass

            # 处理二进制音频数据
            if 'bytes' in data and data['bytes']:
                audio_buffer.extend(data['bytes'])

                # 当缓冲足够一个chunk时进行识别
                while len(audio_buffer) >= chunk_bytes:
                    chunk_data = bytes(audio_buffer[:chunk_bytes])
                    audio_buffer = audio_buffer[chunk_bytes:]

                    # VAD快速过滤
                    vad_result = asr._vad_on_chunk(chunk_data, sample_rate)
                    if not vad_result.get('has_speech', False):
                        continue

                    # 写入临时文件并识别
                    tmp_path = os.path.join(_temp_audio_dir, f"ws_chunk_{uuid.uuid4().hex[:12]}.wav")
                    asr._write_pcm_wav(chunk_data, sample_rate, tmp_path)

                    try:
                        result = asr.transcribe(tmp_path, language if language != 'auto' else None)
                    finally:
                        try:
                            os.unlink(tmp_path)
                        except Exception:
                            pass

                    if result.get('success') and result.get('text', '').strip():
                        segment_index += 1
                        await websocket.send_json({
                            "type": "final",
                            "text": result['text'].strip(),
                            "segment_index": segment_index,
                            "engine": result.get('engine', 'mock'),
                            "language": result.get('language', language),
                        })

    except WebSocketDisconnect:
        pass
    except Exception as e:
        print(f"[WebSocket ASR] 错误: {e}")
        try:
            await websocket.send_json({
                "type": "error",
                "message": str(e),
            })
        except Exception:
            pass
    finally:
        try:
            await websocket.close()
        except Exception:
            pass
