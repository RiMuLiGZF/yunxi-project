#!/usr/bin/env python3
"""
CosyVoice 2.0 FastAPI 服务端
支持：文本转语音、零样本音色克隆、情感控制、语速控制

部署方式：
    python cosyvoice_server.py --model_dir ./models/CosyVoice2-0.5B --device cuda --port 50000
"""

import argparse
import io
import os
import sys
import time
from pathlib import Path
from typing import Optional

import numpy as np
import soundfile as sf
import torch
import torchaudio
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import StreamingResponse, JSONResponse
from pydantic import BaseModel

# ============================================================
# 配置
# ============================================================

DEFAULT_SAMPLE_RATE = 22050

# ============================================================
# 全局变量
# ============================================================

app = FastAPI(
    title="CosyVoice TTS API",
    description="CosyVoice 2.0 语音合成服务 - 支持零样本音色克隆、情感控制",
    version="2.0.0",
)

_model = None
_model_dir = None
_device = "cpu"
_sample_cache = {}  # 音色缓存: name -> (audio_tensor, sr)
_default_voice = None  # 默认音色（启动时加载）


# ============================================================
# 数据模型
# ============================================================

class TTSRequest(BaseModel):
    text: str
    speaker: str = "default"
    emotion: Optional[str] = None  # happy, sad, angry, gentle, ...
    speed: float = 1.0  # 0.5 ~ 2.0
    instruction: Optional[str] = None  # 自然语言指令，如 "用温柔的声音说"
    reference_audio_path: Optional[str] = None  # 参考音频路径（服务端）


class VoicePreset(BaseModel):
    name: str
    description: str
    reference_audio: Optional[str] = None  # base64 或路径
    default_emotion: str = "neutral"


# ============================================================
# 模型加载
# ============================================================

def load_model(model_dir: str, device: str = "cuda"):
    """加载 CosyVoice 模型"""
    global _model, _model_dir, _device, _default_voice
    
    _model_dir = model_dir
    _device = device
    
    print(f"[加载模型] 目录: {model_dir}")
    print(f"[加载模型] 设备: {device}")
    
    try:
        from cosyvoice.cli.cosyvoice import CosyVoice2
        _model = CosyVoice2(model_dir, load_trt=False)
        print(f"[加载模型] ✓ CosyVoice2 加载成功")
        
        # 加载默认音色（使用 CosyVoice 自带的示例音频）
        default_audio_path = os.path.join(os.path.dirname(__file__), '..', 'CosyVoice', 'zero_shot_prompt.wav')
        if not os.path.exists(default_audio_path):
            # 尝试其他位置
            default_audio_path = '/root/cosyvoice/CosyVoice/zero_shot_prompt.wav'
        
        if os.path.exists(default_audio_path):
            audio, sr = sf.read(default_audio_path)
            audio = audio.astype(np.float32)
            if sr != 16000:
                audio = torchaudio.transforms.Resample(orig_freq=sr, new_freq=16000)(
                    torch.from_numpy(audio).unsqueeze(0)
                ).squeeze(0).numpy()
            audio_tensor = torch.from_numpy(audio).unsqueeze(0).float()
            _default_voice = audio_tensor
            _sample_cache['default'] = audio_tensor
            print(f"[加载模型] ✓ 默认音色加载成功")
        else:
            print(f"[加载模型] ⚠ 未找到默认音色音频")
        
        return True
    except Exception as e:
        print(f"[加载模型] ✗ 加载失败: {e}")
        import traceback
        traceback.print_exc()
        return False


def get_reference_audio(speaker: str) -> Optional[torch.Tensor]:
    """获取参考音频（音色）"""
    if speaker in _sample_cache:
        return _sample_cache[speaker]
    
    # 检查预定义音色目录
    preset_dir = Path(_model_dir) / "preset_voices"
    if preset_dir.exists():
        audio_path = preset_dir / f"{speaker}.wav"
        if audio_path.exists():
            audio, sr = sf.read(str(audio_path))
            audio = audio.astype(np.float32)
            if sr != 16000:
                audio = torchaudio.transforms.Resample(orig_freq=sr, new_freq=16000)(
                    torch.from_numpy(audio).unsqueeze(0)
                ).squeeze(0).numpy()
            audio_tensor = torch.from_numpy(audio).unsqueeze(0).float()
            _sample_cache[speaker] = audio_tensor
            return audio_tensor
    
    return None


# ============================================================
# TTS 核心函数
# ============================================================

def synthesize(
    text: str,
    speaker: str = "default",
    emotion: Optional[str] = None,
    speed: float = 1.0,
    instruction: Optional[str] = None,
    reference_audio: Optional[torch.Tensor] = None,
) -> tuple:
    """
    语音合成
    
    返回: (audio_data, sample_rate)
    """
    if _model is None:
        raise RuntimeError("模型未加载")
    
    # 获取参考音频
    ref_audio = reference_audio
    if ref_audio is None:
        ref_audio = get_reference_audio(speaker)
    if ref_audio is None:
        ref_audio = _default_voice
    if ref_audio is None:
        raise RuntimeError("没有可用的参考音频")
    
    # 构建指令
    if instruction:
        instruct = instruction
    else:
        instruct_parts = []
        if emotion:
            emotion_map = {
                "happy": "用开心愉悦的语气",
                "sad": "用悲伤低落的语气",
                "angry": "用生气的语气",
                "gentle": "用温柔的语气",
                "calm": "用平静沉稳的语气",
                "excited": "用兴奋激动的语气",
                "warm": "用温暖亲切的语气",
                "serious": "用严肃认真的语气",
                "playful": "用俏皮活泼的语气",
                "thoughtful": "用沉思的语气",
                "encouraging": "用鼓励的语气",
                "empathetic": "用共情安慰的语气",
            }
            if emotion in emotion_map:
                instruct_parts.append(emotion_map[emotion])
        
        if speed != 1.0:
            if speed < 0.8:
                instruct_parts.append("语速放慢")
            elif speed > 1.2:
                instruct_parts.append("语速加快")
        
        if instruct_parts:
            instruct = "，".join(instruct_parts)
        else:
            instruct = ""
    
    # 执行合成（始终使用 inference_instruct2，稳定性更好）
    # zero_shot 在文本太短时容易出现 LLM 采样失败
    t0 = time.time()
    
    try:
        # 如果没有指令，使用默认指令
        if not instruct:
            instruct = "用自然的语气说"
        
        # 使用 inference_instruct2（指令 + 参考音频）
        audio_list = list(_model.inference_instruct2(
            tts_text=text,
            instruct_text=instruct,
            prompt_speech_16k=ref_audio,
            stream=False,
            speed=speed,
        ))
        
        # 获取音频
        if audio_list:
            audio_tensor = audio_list[-1]['tts_speech']
            if isinstance(audio_tensor, torch.Tensor):
                audio = audio_tensor.squeeze().cpu().numpy()
            else:
                audio = audio_tensor
        else:
            audio = None
        
        elapsed = time.time() - t0
        duration = len(audio) / DEFAULT_SAMPLE_RATE if audio is not None else 0
        rtf = elapsed / duration if duration > 0 else 0
        
        print(f"[TTS] 文本长度: {len(text)} 字")
        print(f"[TTS] 音频时长: {duration:.2f} 秒")
        print(f"[TTS] 推理耗时: {elapsed:.2f} 秒")
        print(f"[TTS] RTF: {rtf:.3f}")
        
        return audio, DEFAULT_SAMPLE_RATE
        
    except Exception as e:
        print(f"[TTS] 合成失败: {e}")
        import traceback
        traceback.print_exc()
        raise


# ============================================================
# API 路由
# ============================================================

@app.get("/health")
async def health_check():
    """健康检查"""
    return {
        "status": "ok" if _model else "loading",
        "model_loaded": _model is not None,
        "device": _device,
        "model_dir": _model_dir,
    }


@app.get("/v1/voices")
async def list_voices():
    """列出可用音色"""
    voices = []
    
    # 默认音色
    voices.append({
        "name": "default",
        "type": "builtin",
        "description": "默认音色 - CosyVoice 示例女声",
    })
    
    # 预设音色
    preset_dir = Path(_model_dir) / "preset_voices" if _model_dir else None
    if preset_dir and preset_dir.exists():
        for f in preset_dir.glob("*.wav"):
            voices.append({
                "name": f.stem,
                "type": "preset",
                "description": f"预设音色 - {f.stem}",
            })
    
    return {"voices": voices, "count": len(voices)}


@app.get("/v1/emotions")
async def list_emotions():
    """列出支持的情感"""
    emotions = [
        {"name": "happy", "description": "开心愉悦"},
        {"name": "sad", "description": "悲伤低落"},
        {"name": "angry", "description": "生气"},
        {"name": "gentle", "description": "温柔"},
        {"name": "calm", "description": "平静沉稳"},
        {"name": "excited", "description": "兴奋激动"},
        {"name": "warm", "description": "温暖亲切"},
        {"name": "serious", "description": "严肃认真"},
        {"name": "playful", "description": "俏皮活泼"},
        {"name": "thoughtful", "description": "沉思"},
        {"name": "encouraging", "description": "鼓励"},
        {"name": "empathetic", "description": "共情安慰"},
    ]
    return {"emotions": emotions, "count": len(emotions)}


@app.post("/v1/tts")
async def tts_synthesize(request: TTSRequest):
    """文本转语音（返回 JSON 含 base64 音频）"""
    if _model is None:
        raise HTTPException(status_code=503, detail="模型未加载，请稍后重试")
    
    try:
        audio, sr = synthesize(
            text=request.text,
            speaker=request.speaker,
            emotion=request.emotion,
            speed=request.speed,
            instruction=request.instruction,
        )
        
        # 编码为 WAV
        buf = io.BytesIO()
        sf.write(buf, audio, sr, format='WAV')
        buf.seek(0)
        
        import base64
        audio_b64 = base64.b64encode(buf.read()).decode('utf-8')
        
        return {
            "success": True,
            "audio": audio_b64,
            "sample_rate": sr,
            "format": "wav",
            "duration": len(audio) / sr,
            "text_length": len(request.text),
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"TTS 合成失败: {str(e)}")


@app.post("/v1/tts/audio")
async def tts_audio(
    text: str = Form(...),
    speaker: str = Form("default"),
    emotion: Optional[str] = Form(None),
    speed: float = Form(1.0),
    instruction: Optional[str] = Form(None),
    format: str = Form("wav"),
):
    """文本转语音（直接返回音频文件）"""
    if _model is None:
        raise HTTPException(status_code=503, detail="模型未加载，请稍后重试")
    
    try:
        audio, sr = synthesize(
            text=text,
            speaker=speaker,
            emotion=emotion,
            speed=speed,
            instruction=instruction,
        )
        
        buf = io.BytesIO()
        sf.write(buf, audio, sr, format=format.upper())
        buf.seek(0)
        
        return StreamingResponse(
            buf,
            media_type=f"audio/{format}",
            headers={"Content-Disposition": f"attachment; filename=tts.{format}"},
        )
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"TTS 合成失败: {str(e)}")


@app.post("/v1/tts/clone")
async def tts_clone(
    text: str = Form(...),
    reference_audio: UploadFile = File(...),
    reference_text: Optional[str] = Form(""),
    emotion: Optional[str] = Form(None),
    speed: float = Form(1.0),
    instruction: Optional[str] = Form(None),
):
    """零样本音色克隆 - 上传参考音频进行音色克隆"""
    if _model is None:
        raise HTTPException(status_code=503, detail="模型未加载，请稍后重试")
    
    try:
        # 读取参考音频
        ref_content = await reference_audio.read()
        ref_buf = io.BytesIO(ref_content)
        ref_audio_np, ref_sr = sf.read(ref_buf)
        ref_audio_np = ref_audio_np.astype(np.float32)
        
        # 重采样到 16k（CosyVoice 需要 16k 参考音频）
        if ref_sr != 16000:
            ref_audio_tensor = torchaudio.transforms.Resample(orig_freq=ref_sr, new_freq=16000)(
                torch.from_numpy(ref_audio_np).unsqueeze(0)
            ).squeeze(0)
        else:
            ref_audio_tensor = torch.from_numpy(ref_audio_np)
        
        ref_audio_tensor = ref_audio_tensor.unsqueeze(0).float()
        
        audio, sr = synthesize(
            text=text,
            emotion=emotion,
            speed=speed,
            instruction=instruction,
            reference_audio=ref_audio_tensor,
        )
        
        buf = io.BytesIO()
        sf.write(buf, audio, sr, format='WAV')
        buf.seek(0)
        
        return StreamingResponse(
            buf,
            media_type="audio/wav",
            headers={"Content-Disposition": "attachment; filename=cloned_tts.wav"},
        )
        
    except Exception as e:
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"音色克隆失败: {str(e)}")


@app.post("/v1/voices/upload")
async def upload_voice(
    name: str = Form(...),
    description: str = Form(""),
    audio_file: UploadFile = File(...),
):
    """上传并保存自定义音色"""
    if not _model_dir:
        raise HTTPException(status_code=503, detail="模型目录未配置")
    
    try:
        preset_dir = Path(_model_dir) / "preset_voices"
        preset_dir.mkdir(exist_ok=True)
        
        content = await audio_file.read()
        save_path = preset_dir / f"{name}.wav"
        
        with open(save_path, "wb") as f:
            f.write(content)
        
        # 清除缓存
        _sample_cache.pop(name, None)
        
        return {
            "success": True,
            "name": name,
            "path": str(save_path),
            "description": description,
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"音色保存失败: {str(e)}")


@app.delete("/v1/voices/{name}")
async def delete_voice(name: str):
    """删除自定义音色"""
    if not _model_dir:
        raise HTTPException(status_code=503, detail="模型目录未配置")
    
    preset_dir = Path(_model_dir) / "preset_voices"
    audio_path = preset_dir / f"{name}.wav"
    
    if audio_path.exists():
        audio_path.unlink()
        _sample_cache.pop(name, None)
        return {"success": True, "name": name}
    else:
        raise HTTPException(status_code=404, detail=f"音色 '{name}' 不存在")


# ============================================================
# 兼容 API（供 cosyvoice_client.py 调用）
# ============================================================

@app.post("/tts/zero_shot")
async def tts_zero_shot_compat(
    text: str = Form(...),
    reference_audio: UploadFile = File(None),
    reference_text: Optional[str] = Form(""),
    speaker_id: Optional[str] = Form(None),
    speed: float = Form(1.0),
):
    """零样本语音克隆（兼容接口）"""
    if _model is None:
        raise HTTPException(status_code=503, detail="模型未加载，请稍后重试")
    
    try:
        ref_audio_tensor = None
        
        # 优先使用上传的参考音频
        if reference_audio is not None:
            ref_content = await reference_audio.read()
            ref_buf = io.BytesIO(ref_content)
            ref_audio_np, ref_sr = sf.read(ref_buf)
            ref_audio_np = ref_audio_np.astype(np.float32)
            
            if ref_sr != 16000:
                ref_audio_tensor = torchaudio.transforms.Resample(orig_freq=ref_sr, new_freq=16000)(
                    torch.from_numpy(ref_audio_np).unsqueeze(0)
                ).float()
            else:
                ref_audio_tensor = torch.from_numpy(ref_audio_np).unsqueeze(0).float()
        elif speaker_id:
            # 使用预设说话人
            ref_audio_tensor = get_reference_audio(speaker_id)
        
        if ref_audio_tensor is None:
            # 使用默认音色
            ref_audio_tensor = _default_voice
        
        if ref_audio_tensor is None:
            raise HTTPException(status_code=400, detail="未提供参考音频且无默认音色")
        
        audio, sr = synthesize(
            text=text,
            speed=speed,
            reference_audio=ref_audio_tensor,
        )
        
        buf = io.BytesIO()
        sf.write(buf, audio, sr, format='WAV')
        buf.seek(0)
        
        return StreamingResponse(
            buf,
            media_type="audio/wav",
            headers={"Content-Disposition": "attachment; filename=tts.wav"},
        )
        
    except Exception as e:
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"音色克隆失败: {str(e)}")


@app.post("/tts/instruct")
async def tts_instruct_compat(
    text: str = Form(...),
    instruction: str = Form(...),
    reference_audio: UploadFile = File(None),
    reference_text: Optional[str] = Form(""),
    speaker_id: Optional[str] = Form(None),
    speed: float = Form(1.0),
):
    """指令控制语音合成（兼容接口）"""
    if _model is None:
        raise HTTPException(status_code=503, detail="模型未加载，请稍后重试")
    
    try:
        ref_audio_tensor = None
        
        # 优先使用上传的参考音频
        if reference_audio is not None:
            ref_content = await reference_audio.read()
            ref_buf = io.BytesIO(ref_content)
            ref_audio_np, ref_sr = sf.read(ref_buf)
            ref_audio_np = ref_audio_np.astype(np.float32)
            
            if ref_sr != 16000:
                ref_audio_tensor = torchaudio.transforms.Resample(orig_freq=ref_sr, new_freq=16000)(
                    torch.from_numpy(ref_audio_np).unsqueeze(0)
                ).float()
            else:
                ref_audio_tensor = torch.from_numpy(ref_audio_np).unsqueeze(0).float()
        elif speaker_id:
            # 使用预设说话人
            ref_audio_tensor = get_reference_audio(speaker_id)
        
        if ref_audio_tensor is None:
            # 使用默认音色
            ref_audio_tensor = _default_voice
        
        if ref_audio_tensor is None:
            raise HTTPException(status_code=400, detail="未提供参考音频且无默认音色")
        
        audio, sr = synthesize(
            text=text,
            instruction=instruction,
            speed=speed,
            reference_audio=ref_audio_tensor,
        )
        
        buf = io.BytesIO()
        sf.write(buf, audio, sr, format='WAV')
        buf.seek(0)
        
        return StreamingResponse(
            buf,
            media_type="audio/wav",
            headers={"Content-Disposition": "attachment; filename=tts.wav"},
        )
        
    except Exception as e:
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"指令合成失败: {str(e)}")


# ============================================================
# 启动入口
# ============================================================

def main():
    parser = argparse.ArgumentParser(description="CosyVoice 2.0 TTS 服务")
    parser.add_argument("--model_dir", type=str, default=os.environ.get("COSYVOICE_MODEL_DIR", "./models/CosyVoice2-0.5B"))
    parser.add_argument("--device", type=str, default=os.environ.get("COSYVOICE_DEVICE", "cuda"))
    parser.add_argument("--host", type=str, default=os.environ.get("COSYVOICE_HOST", "0.0.0.0"))
    parser.add_argument("--port", type=int, default=int(os.environ.get("COSYVOICE_PORT", "50000")))
    args = parser.parse_args()
    
    # 加载模型
    print("=" * 60)
    print("  CosyVoice 2.0 TTS 服务启动中...")
    print("=" * 60)
    
    success = load_model(args.model_dir, args.device)
    
    if not success:
        print("\n⚠  模型加载失败，服务将以降级模式运行（返回 mock 数据）")
        print("   请检查模型目录和依赖是否正确安装")
    
    print(f"\n🚀 服务启动: http://{args.host}:{args.port}")
    print(f"📖 API 文档: http://{args.host}:{args.port}/docs")
    print()
    
    import uvicorn
    uvicorn.run(app, host=args.host, port=args.port)


if __name__ == "__main__":
    main()
