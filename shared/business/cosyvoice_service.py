"""
CosyVoice 语音合成服务（FastAPI）
================================

提供基于 CosyVoice 2.0/3.0 的高质量 TTS 服务，支持：
- 零样本语音克隆（Zero-shot Voice Cloning）
- 指令控制合成（Instruct-based TTS）
- 跨语言合成（Cross-lingual TTS）
- 说话人管理（预存声纹嵌入）
- 流式推理

部署方式：
    uvicorn cosyvoice_service:app --host 0.0.0.0 --port 50000

环境变量：
    COSYVOICE_MODEL_DIR - 模型目录路径（默认：./models/CosyVoice2-0.5B）
    COSYVOICE_DEVICE - 推理设备（cuda/cpu/auto，默认：auto）
    COSYVOICE_PORT - 服务端口（默认：50000）
"""

import os
import io
import sys
import time
import tempfile
import logging
from typing import Optional, Dict, Any, List
from pathlib import Path

logger = logging.getLogger(__name__)

from fastapi import FastAPI, UploadFile, File, Form, HTTPException
from fastapi.responses import Response, JSONResponse, StreamingResponse
import uvicorn


# ============================================================
# 配置
# ============================================================

MODEL_DIR = os.environ.get("COSYVOICE_MODEL_DIR", "./models/CosyVoice2-0.5B")
DEVICE = os.environ.get("COSYVOICE_DEVICE", "auto")
PORT = int(os.environ.get("COSYVOICE_PORT", "50000"))
SAMPLE_RATE = 22050

# 说话人嵌入缓存（内存中）
_speakers: Dict[str, Dict[str, Any]] = {}

# CosyVoice 模型实例（懒加载）
_cosyvoice_instance = None
_model_loaded = False
_load_error: Optional[str] = None


# ============================================================
# 模型加载
# ============================================================

def get_cosyvoice():
    """获取 CosyVoice 模型实例（懒加载）"""
    global _cosyvoice_instance, _model_loaded, _load_error
    
    if _model_loaded:
        if _cosyvoice_instance is None:
            raise RuntimeError(f"模型加载失败: {_load_error}")
        return _cosyvoice_instance
    
    try:
        print(f"[CosyVoice] 正在加载模型: {MODEL_DIR}")
        start_time = time.time()
        
        # 尝试导入 CosyVoice
        try:
            sys.path.append('third_party/Matcha-TTS')
        except Exception as e:
            # 路径添加失败不影响主流程，CosyVoice 可能通过其他方式导入
            logger.debug("添加 Matcha-TTS 路径失败: %s", e)
        
        from cosyvoice.cli.cosyvoice import AutoModel
        import torch
        
        # 自动检测设备
        device = DEVICE
        if device == "auto":
            if torch.cuda.is_available():
                device = "cuda"
            else:
                device = "cpu"
        
        print(f"[CosyVoice] 使用设备: {device}")
        
        # 加载模型
        model_path = Path(MODEL_DIR)
        if not model_path.exists():
            _load_error = f"模型目录不存在: {MODEL_DIR}"
            _model_loaded = True
            raise RuntimeError(_load_error)
        
        _cosyvoice_instance = AutoModel(model_dir=str(model_path))
        
        # 如果是 CUDA，将模型移到 GPU
        if device == "cuda" and hasattr(_cosyvoice_instance, 'to'):
            _cosyvoice_instance.to(device)
        
        load_time = time.time() - start_time
        print(f"[CosyVoice] 模型加载完成，耗时 {load_time:.1f}s")
        _model_loaded = True
        return _cosyvoice_instance
        
    except Exception as e:
        _load_error = str(e)
        _model_loaded = True
        print(f"[CosyVoice] 模型加载失败: {e}")
        raise RuntimeError(f"模型加载失败: {e}")


# ============================================================
# FastAPI 应用
# ============================================================

app = FastAPI(
    title="CosyVoice TTS Service",
    description="基于 CosyVoice 2.0/3.0 的高质量语音合成服务",
    version="1.0.0",
)


# ============================================================
# 健康检查
# ============================================================

@app.get("/health")
async def health_check():
    """健康检查"""
    global _model_loaded, _load_error
    return {
        "status": "ok" if _model_loaded and _cosyvoice_instance else "loading",
        "model_loaded": _model_loaded,
        "model_dir": MODEL_DIR,
        "device": DEVICE,
        "error": _load_error,
        "speakers": list(_speakers.keys()),
    }


@app.get("/ready")
async def ready_check():
    """服务就绪检查（模型加载完成）"""
    try:
        get_cosyvoice()
        return {"ready": True}
    except Exception as e:
        return {"ready": False, "error": str(e)}


# ============================================================
# 说话人管理
# ============================================================

@app.get("/speakers")
async def list_speakers():
    """获取已保存的说话人列表"""
    speakers_list = []
    for spk_id, spk_info in _speakers.items():
        speakers_list.append({
            'speaker_id': spk_id,
            'reference_text': spk_info.get('reference_text', ''),
            'created_at': spk_info.get('created_at', 0),
        })
    return {"speakers": speakers_list, "count": len(speakers_list)}


@app.post("/speakers/add")
async def add_speaker(
    speaker_id: str = Form(...),
    reference_text: str = Form(""),
    reference_audio: UploadFile = File(...),
):
    """添加说话人（保存声纹嵌入）
    
    仅 CosyVoice 2.0+ 支持预存说话人嵌入。
    对于 1.0 版本，返回成功但实际每次推理仍需传入参考音频。
    """
    try:
        # 保存参考音频到临时文件
        audio_data = await reference_audio.read()
        
        with tempfile.NamedTemporaryFile(suffix='.wav', delete=False) as tmp:
            tmp.write(audio_data)
            tmp_path = tmp.name
        
        try:
            cosyvoice = get_cosyvoice()
            
            # 尝试使用 add_zero_shot_spk 方法（v2+支持）
            if hasattr(cosyvoice, 'add_zero_shot_spk'):
                success = cosyvoice.add_zero_shot_spk(
                    reference_text,
                    tmp_path,
                    speaker_id,
                )
                if not success:
                    raise HTTPException(status_code=400, detail="添加说话人失败")
            else:
                # v1 版本不支持预存，保存参考音频路径供后续使用
                print(f"[CosyVoice] 当前版本不支持预存说话人，将保存参考音频路径")
            
            # 保存说话人信息
            _speakers[speaker_id] = {
                'reference_text': reference_text,
                'reference_audio_path': tmp_path,
                'reference_audio_data': audio_data,
                'created_at': time.time(),
            }
            
            return {
                "success": True,
                "speaker_id": speaker_id,
                "message": "说话人添加成功",
            }
            
        finally:
            # 注意：不要删除临时文件，后续推理可能需要
            # （实际生产环境应持久化存储）
            pass
            
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"添加说话人失败: {str(e)}")


@app.delete("/speakers/{speaker_id}")
async def delete_speaker(speaker_id: str):
    """删除说话人"""
    if speaker_id in _speakers:
        del _speakers[speaker_id]
        return {"success": True, "message": f"说话人 {speaker_id} 已删除"}
    raise HTTPException(status_code=404, detail=f"说话人 {speaker_id} 不存在")


# ============================================================
# 语音合成 - 零样本克隆
# ============================================================

@app.post("/tts/zero_shot")
async def tts_zero_shot(
    text: str = Form(...),
    reference_text: str = Form(""),
    speaker_id: Optional[str] = Form(None),
    reference_audio: Optional[UploadFile] = File(None),
):
    """零样本语音克隆
    
    使用方式二选一：
    1. 提供 speaker_id（已预存的说话人）
    2. 提供 reference_audio + reference_text（实时克隆）
    """
    try:
        cosyvoice = get_cosyvoice()
        
        # 确定参考音频
        ref_audio_path = None
        ref_text = reference_text
        
        if speaker_id and speaker_id in _speakers:
            # 使用已保存的说话人
            spk_info = _speakers[speaker_id]
            ref_audio_path = spk_info['reference_audio_path']
            if not ref_text:
                ref_text = spk_info.get('reference_text', '')
        elif reference_audio is not None:
            # 使用上传的参考音频
            audio_data = await reference_audio.read()
            with tempfile.NamedTemporaryFile(suffix='.wav', delete=False) as tmp:
                tmp.write(audio_data)
                ref_audio_path = tmp.name
        else:
            raise HTTPException(
                status_code=400, 
                detail="必须提供 speaker_id 或 reference_audio"
            )
        
        # 执行推理
        audio_chunks = []
        for i, chunk in enumerate(cosyvoice.inference_zero_shot(
            text,
            ref_text,
            ref_audio_path,
            stream=False,
        )):
            audio_chunks.append(chunk['tts_speech'])
        
        # 合并音频
        import torch
        if len(audio_chunks) == 1:
            audio_tensor = audio_chunks[0]
        else:
            audio_tensor = torch.cat(audio_chunks, dim=1)
        
        # 转换为 WAV 格式
        wav_data = _tensor_to_wav(audio_tensor, cosyvoice.sample_rate)
        
        return Response(
            content=wav_data,
            media_type="audio/wav",
            headers={
                "Content-Disposition": "attachment; filename=tts_output.wav",
                "X-Sample-Rate": str(cosyvoice.sample_rate),
                "X-Duration": str(audio_tensor.shape[1] / cosyvoice.sample_rate),
            }
        )
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"TTS 合成失败: {str(e)}")


# ============================================================
# 语音合成 - 指令控制
# ============================================================

@app.post("/tts/instruct")
async def tts_instruct(
    text: str = Form(...),
    instruction: str = Form(...),
    reference_text: str = Form(""),
    speaker_id: Optional[str] = Form(None),
    reference_audio: Optional[UploadFile] = File(None),
):
    """指令控制语音合成
    
    通过自然语言指令控制语音风格，如：
    - "用开心的语气说"
    - "用四川话说"
    - "语速快一点"
    """
    try:
        cosyvoice = get_cosyvoice()
        
        # 确定参考音频
        ref_audio_path = None
        ref_text = reference_text
        
        if speaker_id and speaker_id in _speakers:
            spk_info = _speakers[speaker_id]
            ref_audio_path = spk_info['reference_audio_path']
            if not ref_text:
                ref_text = spk_info.get('reference_text', '')
        elif reference_audio is not None:
            audio_data = await reference_audio.read()
            with tempfile.NamedTemporaryFile(suffix='.wav', delete=False) as tmp:
                tmp.write(audio_data)
                ref_audio_path = tmp.name
        else:
            raise HTTPException(
                status_code=400, 
                detail="必须提供 speaker_id 或 reference_audio"
            )
        
        # 执行推理
        audio_chunks = []
        for i, chunk in enumerate(cosyvoice.inference_instruct2(
            text,
            instruction,
            ref_text,
            ref_audio_path,
            stream=False,
        )):
            audio_chunks.append(chunk['tts_speech'])
        
        # 合并音频
        import torch
        if len(audio_chunks) == 1:
            audio_tensor = audio_chunks[0]
        else:
            audio_tensor = torch.cat(audio_chunks, dim=1)
        
        # 转换为 WAV
        wav_data = _tensor_to_wav(audio_tensor, cosyvoice.sample_rate)
        
        return Response(
            content=wav_data,
            media_type="audio/wav",
            headers={
                "Content-Disposition": "attachment; filename=tts_instruct.wav",
                "X-Sample-Rate": str(cosyvoice.sample_rate),
                "X-Duration": str(audio_tensor.shape[1] / cosyvoice.sample_rate),
                "X-Instruction": instruction,
            }
        )
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"TTS 合成失败: {str(e)}")


# ============================================================
# 语音合成 - 跨语言
# ============================================================

@app.post("/tts/cross_lingual")
async def tts_cross_lingual(
    text: str = Form(...),
    speaker_id: Optional[str] = Form(None),
    reference_audio: Optional[UploadFile] = File(None),
):
    """跨语言语音合成
    
    文本中使用 <|zh|><|en|><|jp|><|yue|><|ko|> 标签切换语言。
    """
    try:
        cosyvoice = get_cosyvoice()
        
        ref_audio_path = None
        
        if speaker_id and speaker_id in _speakers:
            spk_info = _speakers[speaker_id]
            ref_audio_path = spk_info['reference_audio_path']
        elif reference_audio is not None:
            audio_data = await reference_audio.read()
            with tempfile.NamedTemporaryFile(suffix='.wav', delete=False) as tmp:
                tmp.write(audio_data)
                ref_audio_path = tmp.name
        else:
            raise HTTPException(
                status_code=400, 
                detail="必须提供 speaker_id 或 reference_audio"
            )
        
        # 执行推理
        audio_chunks = []
        for i, chunk in enumerate(cosyvoice.inference_cross_lingual(
            text,
            ref_audio_path,
            stream=False,
        )):
            audio_chunks.append(chunk['tts_speech'])
        
        import torch
        if len(audio_chunks) == 1:
            audio_tensor = audio_chunks[0]
        else:
            audio_tensor = torch.cat(audio_chunks, dim=1)
        
        wav_data = _tensor_to_wav(audio_tensor, cosyvoice.sample_rate)
        
        return Response(
            content=wav_data,
            media_type="audio/wav",
            headers={
                "Content-Disposition": "attachment; filename=tts_cross_lingual.wav",
                "X-Sample-Rate": str(cosyvoice.sample_rate),
                "X-Duration": str(audio_tensor.shape[1] / cosyvoice.sample_rate),
            }
        )
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"TTS 合成失败: {str(e)}")


# ============================================================
# 语音合成 - 语音转换 (VC)
# ============================================================

@app.post("/tts/vc")
async def tts_vc(
    source_audio: UploadFile = File(...),
    target_audio: UploadFile = File(...),
):
    """语音转换（Voice Conversion）
    
    将源音频的内容转换为目标音频的音色。
    """
    try:
        cosyvoice = get_cosyvoice()
        
        # 保存上传的音频
        source_data = await source_audio.read()
        target_data = await target_audio.read()
        
        with tempfile.NamedTemporaryFile(suffix='.wav', delete=False) as tmp:
            tmp.write(source_data)
            source_path = tmp.name
        
        with tempfile.NamedTemporaryFile(suffix='.wav', delete=False) as tmp:
            tmp.write(target_data)
            target_path = tmp.name
        
        # 执行推理
        audio_chunks = []
        for i, chunk in enumerate(cosyvoice.inference_vc(
            source_path,
            target_path,
            stream=False,
        )):
            audio_chunks.append(chunk['tts_speech'])
        
        import torch
        if len(audio_chunks) == 1:
            audio_tensor = audio_chunks[0]
        else:
            audio_tensor = torch.cat(audio_chunks, dim=1)
        
        wav_data = _tensor_to_wav(audio_tensor, cosyvoice.sample_rate)
        
        return Response(
            content=wav_data,
            media_type="audio/wav",
            headers={
                "Content-Disposition": "attachment; filename=vc_output.wav",
                "X-Sample-Rate": str(cosyvoice.sample_rate),
            }
        )
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"语音转换失败: {str(e)}")


# ============================================================
# 辅助函数
# ============================================================

def _tensor_to_wav(audio_tensor, sample_rate: int) -> bytes:
    """将 PyTorch 张量转换为 WAV 字节数据"""
    import torchaudio
    import io
    
    # 确保是 2D 张量 [channels, samples]
    if audio_tensor.dim() == 1:
        audio_tensor = audio_tensor.unsqueeze(0)
    
    # 保存到内存缓冲区
    buffer = io.BytesIO()
    torchaudio.save(buffer, audio_tensor.cpu(), sample_rate, format='wav')
    buffer.seek(0)
    
    return buffer.read()


# ============================================================
# 启动入口
# ============================================================

if __name__ == "__main__":
    print("=" * 60)
    print("  CosyVoice TTS 服务")
    print("=" * 60)
    print(f"  模型目录: {MODEL_DIR}")
    print(f"  设备: {DEVICE}")
    print(f"  端口: {PORT}")
    print("=" * 60)
    print()
    print("API 文档: http://localhost:{}/docs".format(PORT))
    print("健康检查: http://localhost:{}/health".format(PORT))
    print()
    
    # 预加载模型（可选，注释掉则首次请求时加载）
    # try:
    #     get_cosyvoice()
    # except Exception as e:
    #     print(f"[警告] 预加载模型失败: {e}")
    #     print("       服务仍将启动，首次请求时将尝试加载。")
    
    uvicorn.run(app, host="0.0.0.0", port=PORT)
