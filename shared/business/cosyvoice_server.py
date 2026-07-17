#!/usr/bin/env python3
"""
CosyVoice 2.0 FastAPI 服务端
支持：文本转语音、零样本音色克隆、情感控制、语速控制

部署方式：
    python cosyvoice_server.py --model_dir ./models/CosyVoice2-0.5B --device cuda --port 50000
"""

import argparse
import base64
import io
import json
import os
import re
import sys
import time
from pathlib import Path
from typing import Optional, AsyncIterator

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
# 文本分割（流式合成辅助）
# ============================================================

# 句子结束标点符号（中英文混合）
_SENTENCE_END_PATTERN = re.compile(
    r'([。！？.!?；;])'
)
# 句子中间停顿标点（用于长句二次切分）
_CLAUSE_PAUSE_PATTERN = re.compile(
    r'([，,、])'
)


def split_sentences(text: str, min_len: int = 20, max_len: int = 50) -> list:
    """
    按句子分割文本，用于模拟流式 TTS。
    
    分割策略：
    1. 先按句末标点（。！？.!?；;）分割
    2. 句子太短（< min_len）则与下一句合并
    3. 句子太长（> max_len）则按停顿标点（，,、）二次切分
    4. 二次切分后仍过长，则按 max_len 硬切
    
    参数:
        text: 输入文本
        min_len: 每句最小字数
        max_len: 每句最大字数
    
    返回:
        句子列表
    """
    if not text or not text.strip():
        return []
    
    # 第一步：按句末标点分割（保留标点）
    parts = _SENTENCE_END_PATTERN.split(text)
    sentences = []
    current = ""
    
    for part in parts:
        if not part:
            continue
        if _SENTENCE_END_PATTERN.fullmatch(part):
            # 这是标点，追加到当前句子
            current += part
            sentences.append(current)
            current = ""
        else:
            current += part
    
    # 处理末尾没有标点的剩余文本
    if current.strip():
        sentences.append(current)
    
    # 第二步：合并过短的句子
    merged = []
    buffer = ""
    for sent in sentences:
        buffer += sent
        if len(buffer) >= min_len:
            merged.append(buffer)
            buffer = ""
    if buffer.strip():
        if merged:
            # 最后一句太短，合并到前一句
            merged[-1] += buffer
        else:
            merged.append(buffer)
    
    # 第三步：对过长的句子进行二次切分
    final_sentences = []
    for sent in merged:
        if len(sent) <= max_len:
            final_sentences.append(sent)
        else:
            # 按停顿标点二次切分
            sub_parts = _CLAUSE_PAUSE_PATTERN.split(sent)
            sub_buffer = ""
            for sub in sub_parts:
                if not sub:
                    continue
                if _CLAUSE_PAUSE_PATTERN.fullmatch(sub):
                    sub_buffer += sub
                    if len(sub_buffer) >= min_len:
                        final_sentences.append(sub_buffer)
                        sub_buffer = ""
                else:
                    # 检查加上这段后是否超上限
                    if len(sub_buffer) + len(sub) > max_len and sub_buffer:
                        final_sentences.append(sub_buffer)
                        sub_buffer = sub
                    else:
                        sub_buffer += sub
            if sub_buffer.strip():
                # 如果剩余部分太短，合并到上一句
                if len(sub_buffer) < min_len and final_sentences:
                    final_sentences[-1] += sub_buffer
                else:
                    # 仍过长则硬切
                    if len(sub_buffer) > max_len:
                        for i in range(0, len(sub_buffer), max_len):
                            chunk = sub_buffer[i:i + max_len]
                            if len(chunk) < min_len and final_sentences:
                                final_sentences[-1] += chunk
                            else:
                                final_sentences.append(chunk)
                    else:
                        final_sentences.append(sub_buffer)
    
    # 清理首尾空白并过滤空句子
    final_sentences = [s.strip() for s in final_sentences if s.strip()]
    
    return final_sentences


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


def _build_instruct_text(emotion: Optional[str], speed: float,
                         instruction: Optional[str]) -> str:
    """
    构建指令文本（复用 synthesize 中的逻辑，供流式合成使用）
    """
    if instruction:
        return instruction

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
        return "，".join(instruct_parts)
    return "用自然的语气说"


def _encode_audio_chunk(audio: np.ndarray, sample_rate: int,
                        fmt: str = "wav") -> bytes:
    """
    将音频 numpy 数组编码为指定格式的字节数据。

    参数:
        audio: 音频 numpy 数组 (float32, 单声道)
        sample_rate: 采样率
        fmt: 输出格式 - "wav" / "pcm" / "mp3"

    返回:
        编码后的字节数据
    """
    fmt = fmt.lower()

    if fmt == "pcm":
        # 16-bit PCM 原始数据
        pcm_data = (audio * 32767.0).astype(np.int16)
        return pcm_data.tobytes()

    elif fmt == "mp3":
        # 使用 lameenc 或 torchaudio 编码 MP3
        try:
            import lameenc
            encoder = lameenc.Encoder()
            encoder.set_bit_rate(128)
            encoder.set_in_sample_rate(sample_rate)
            encoder.set_channels(1)
            encoder.set_quality(2)
            pcm_data = (audio * 32767.0).astype(np.int16)
            mp3_data = encoder.encode(pcm_data.tobytes())
            mp3_data += encoder.flush()
            return mp3_data
        except ImportError:
            # 降级：返回 WAV
            print("[警告] 未安装 lameenc，MP3 格式降级为 WAV")
            buf = io.BytesIO()
            sf.write(buf, audio, sample_rate, format='WAV')
            return buf.getvalue()

    else:  # wav (默认)
        buf = io.BytesIO()
        sf.write(buf, audio, sample_rate, format='WAV')
        return buf.getvalue()


def _try_native_stream(text: str, instruct: str, ref_audio: torch.Tensor,
                       speed: float):
    """
    尝试使用 CosyVoice 原生流式合成（stream=True）。
    
    如果原生流式可用，返回生成器；不可用返回 None。
    """
    try:
        # 尝试调用 stream=True 模式
        stream_gen = _model.inference_instruct2(
            tts_text=text,
            instruct_text=instruct,
            prompt_speech_16k=ref_audio,
            stream=True,
            speed=speed,
        )
        # 尝试获取第一个 chunk 来验证流式是否真正生效
        # 如果模型不支持 stream，它可能仍然返回完整结果列表
        # 我们通过检查返回类型来判断
        import types
        if isinstance(stream_gen, types.GeneratorType):
            return stream_gen
        return None
    except (TypeError, ValueError, NotImplementedError):
        return None
    except Exception:
        return None


def synthesize_stream(
    text: str,
    speaker: str = "default",
    emotion: Optional[str] = None,
    speed: float = 1.0,
    instruction: Optional[str] = None,
    reference_audio: Optional[torch.Tensor] = None,
    audio_format: str = "wav",
):
    """
    流式语音合成生成器。
    
    优先尝试 CosyVoice 原生流式（stream=True），如果不支持则回退到
    按句子分割的模拟流式模式。每生成一个音频 chunk 就立刻 yield。

    Yields:
        dict: {
            "index": int,        # chunk 序号（从 0 开始）
            "audio": np.ndarray, # 音频数据 (float32)
            "sample_rate": int,  # 采样率
            "duration": float,   # 本 chunk 时长（秒）
            "text": str,         # 本 chunk 对应的文本（模拟流式时有效）
            "mode": str,         # "native" 原生流式 / "simulated" 模拟流式
        }
    
    最后 yield:
        dict: {"done": True, "total_duration": float, "total_chunks": int}
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

    instruct = _build_instruct_text(emotion, speed, instruction)

    # ---- 尝试原生流式 ----
    total_duration = 0.0
    chunk_index = 0

    native_stream = _try_native_stream(text, instruct, ref_audio, speed)
    if native_stream is not None:
        print(f"[流式TTS] 使用原生流式模式，文本长度: {len(text)} 字")
        t_start = time.time()
        try:
            for chunk_result in native_stream:
                # CosyVoice 原生流式通常返回 dict，含 'tts_speech'
                if isinstance(chunk_result, dict) and 'tts_speech' in chunk_result:
                    audio_tensor = chunk_result['tts_speech']
                    if isinstance(audio_tensor, torch.Tensor):
                        audio = audio_tensor.squeeze().cpu().numpy()
                    else:
                        audio = audio_tensor
                elif isinstance(chunk_result, torch.Tensor):
                    audio = chunk_result.squeeze().cpu().numpy()
                elif isinstance(chunk_result, np.ndarray):
                    audio = chunk_result.squeeze()
                else:
                    continue

                if len(audio) == 0:
                    continue

                duration = len(audio) / DEFAULT_SAMPLE_RATE
                total_duration += duration

                yield {
                    "index": chunk_index,
                    "audio": audio,
                    "sample_rate": DEFAULT_SAMPLE_RATE,
                    "duration": duration,
                    "text": "",
                    "mode": "native",
                }
                chunk_index += 1

            elapsed = time.time() - t_start
            print(f"[流式TTS] 原生流式完成: {chunk_index} chunks, "
                  f"总时长 {total_duration:.2f}s, 耗时 {elapsed:.2f}s")

            yield {
                "done": True,
                "total_duration": total_duration,
                "total_chunks": chunk_index,
            }
            return

        except Exception as e:
            print(f"[流式TTS] 原生流式失败，回退到模拟流式: {e}")
            # 回退到模拟流式

    # ---- 回退：模拟流式（按句子分割，逐句合成） ----
    print(f"[流式TTS] 使用模拟流式模式，文本长度: {len(text)} 字")
    sentences = split_sentences(text)
    print(f"[流式TTS] 分割为 {len(sentences)} 句")

    if not sentences:
        yield {"done": True, "total_duration": 0.0, "total_chunks": 0}
        return

    t_start = time.time()
    first_chunk_time = None

    for i, sentence in enumerate(sentences):
        t0 = time.time()
        try:
            audio_list = list(_model.inference_instruct2(
                tts_text=sentence,
                instruct_text=instruct,
                prompt_speech_16k=ref_audio,
                stream=False,
                speed=speed,
            ))

            if audio_list:
                audio_tensor = audio_list[-1]['tts_speech']
                if isinstance(audio_tensor, torch.Tensor):
                    audio = audio_tensor.squeeze().cpu().numpy()
                else:
                    audio = audio_tensor
            else:
                audio = None

            if audio is None or len(audio) == 0:
                continue

            duration = len(audio) / DEFAULT_SAMPLE_RATE
            total_duration += duration

            elapsed_chunk = time.time() - t0
            if first_chunk_time is None:
                first_chunk_time = time.time() - t_start
                print(f"[流式TTS] 首字延迟: {first_chunk_time:.3f}s")

            print(f"[流式TTS] chunk {i}: \"{sentence[:20]}...\" "
                  f"时长 {duration:.2f}s, 推理 {elapsed_chunk:.2f}s")

            yield {
                "index": chunk_index,
                "audio": audio,
                "sample_rate": DEFAULT_SAMPLE_RATE,
                "duration": duration,
                "text": sentence,
                "mode": "simulated",
            }
            chunk_index += 1

        except Exception as e:
            print(f"[流式TTS] 第 {i} 句合成失败: {e}")
            import traceback
            traceback.print_exc()
            # 单句失败不终止整体流式，继续下一句
            continue

    total_elapsed = time.time() - t_start
    print(f"[流式TTS] 模拟流式完成: {chunk_index} chunks, "
          f"总时长 {total_duration:.2f}s, 总耗时 {total_elapsed:.2f}s")

    yield {
        "done": True,
        "total_duration": total_duration,
        "total_chunks": chunk_index,
    }


# ============================================================
# SSE 辅助
# ============================================================

def _sse_audio_event(chunk_data: dict, audio_format: str) -> str:
    """
    构造 SSE audio_chunk 事件消息。

    参数:
        chunk_data: synthesize_stream yield 的 chunk 字典
        audio_format: 音频格式 (wav/pcm/mp3)

    返回:
        SSE 格式字符串
    """
    encoded = _encode_audio_chunk(
        chunk_data["audio"],
        chunk_data["sample_rate"],
        audio_format,
    )
    audio_b64 = base64.b64encode(encoded).decode('utf-8')

    payload = {
        "index": chunk_data["index"],
        "duration": round(chunk_data["duration"], 3),
        "sample_rate": chunk_data["sample_rate"],
        "format": audio_format,
        "mode": chunk_data.get("mode", "simulated"),
        "text": chunk_data.get("text", ""),
        "audio": audio_b64,
    }

    return f"event: audio_chunk\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"


def _sse_complete_event(total_duration: float, total_chunks: int) -> str:
    """构造 SSE complete 事件消息"""
    payload = {
        "total_duration": round(total_duration, 3),
        "total_chunks": total_chunks,
    }
    return f"event: complete\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"


def _sse_error_event(message: str) -> str:
    """构造 SSE error 事件消息"""
    payload = {"error": message}
    return f"event: error\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"


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


@app.get("/v1/tts/stream")
async def tts_stream(
    text: str,
    speaker: str = "default",
    emotion: Optional[str] = None,
    speed: float = 1.0,
    instruction: Optional[str] = None,
    format: str = "wav",
):
    """
    流式 TTS（Server-Sent Events）
    
    边生成边播放，降低首字延迟。优先使用 CosyVoice 原生流式，
    不支持时自动回退到按句子分割的模拟流式模式。

    参数:
        text: 待合成文本
        speaker: 音色名称
        emotion: 情感 (happy/sad/angry/gentle/...)
        speed: 语速 (0.5 ~ 2.0)
        instruction: 自然语言指令（可选，覆盖 emotion/speed）
        format: 音频格式 - wav / pcm / mp3

    SSE 事件:
        audio_chunk - 音频 chunk 数据
            data: {index, duration, sample_rate, format, mode, text, audio(base64)}
        complete - 合成完成
            data: {total_duration, total_chunks}
        error - 错误
            data: {error}
    """
    if _model is None:
        # 模型未加载时，先返回一个 error 事件再关闭
        async def _error_generator():
            yield _sse_error_event("模型未加载，请稍后重试")
        return StreamingResponse(
            _error_generator(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
            },
        )

    # 校验格式
    fmt = format.lower()
    if fmt not in ("wav", "pcm", "mp3"):
        async def _format_error():
            yield _sse_error_event(f"不支持的格式: {format}，请使用 wav/pcm/mp3")
        return StreamingResponse(
            _format_error(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
            },
        )

    # 校验文本
    if not text or not text.strip():
        async def _empty_error():
            yield _sse_error_event("文本不能为空")
        return StreamingResponse(
            _empty_error(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
            },
        )

    import asyncio

    def _stream_generator():
        """同步生成器：调用流式合成并输出 SSE 事件"""
        try:
            for chunk in synthesize_stream(
                text=text,
                speaker=speaker,
                emotion=emotion,
                speed=speed,
                instruction=instruction,
                audio_format=fmt,
            ):
                if chunk.get("done"):
                    # 完成事件
                    yield _sse_complete_event(
                        chunk["total_duration"],
                        chunk["total_chunks"],
                    )
                else:
                    # 音频 chunk 事件
                    yield _sse_audio_event(chunk, fmt)
        except Exception as e:
            import traceback
            traceback.print_exc()
            yield _sse_error_event(f"TTS 流式合成失败: {str(e)}")

    async def _async_stream():
        """
        将同步生成器包装为异步迭代器。
        
        使用 run_in_executor 避免阻塞事件循环，
        每次 yield 一个 SSE 事件字符串。
        """
        loop = asyncio.get_event_loop()
        gen = _stream_generator()
        
        while True:
            try:
                # 在线程池中执行 next(gen)，避免阻塞事件循环
                event = await loop.run_in_executor(None, next, gen)
                yield event
            except StopIteration:
                break

    return StreamingResponse(
        _async_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


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
