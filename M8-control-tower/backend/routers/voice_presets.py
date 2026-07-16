"""
音色管理路由 - 云汐专属音色管理
================================

提供音色预设管理、参考音频上传、CosyVoice集成等API。

端点：
- GET /presets - 列出所有音色预设
- GET /presets/{preset_id} - 获取指定音色预设
- POST /presets - 添加自定义音色预设
- DELETE /presets/{preset_id} - 删除音色预设
- PUT /presets/{preset_id}/activate - 激活音色预设
- POST /presets/{preset_id}/audio - 上传参考音频
- GET /active - 获取当前激活的音色
- GET /cosyvoice/status - CosyVoice 服务状态
- POST /cosyvoice/register - 注册音色到 CosyVoice 服务
"""

import os
import sys
import uuid
from pathlib import Path
from typing import Optional, List

from fastapi import APIRouter, UploadFile, File, Form, HTTPException
from pydantic import BaseModel

# 确保 shared 目录在路径中
_current_dir = os.path.dirname(os.path.abspath(__file__))
_shared_dir = os.path.join(_current_dir, '..', '..', '..', 'shared')
if _shared_dir not in sys.path:
    sys.path.insert(0, _shared_dir)

try:
    from voice_preset_manager import get_voice_preset_manager, VoicePreset
    _preset_manager = get_voice_preset_manager()
    _presets_available = True
except ImportError as e:
    _presets_available = False
    _preset_error = str(e)

try:
    from cosyvoice_client import get_cosyvoice_client, CosyVoiceConfig
    _cosyvoice_available = True
except ImportError:
    _cosyvoice_available = False

router = APIRouter(tags=["音色管理"])


# ===== 请求模型 =====

class CreatePresetRequest(BaseModel):
    name: str
    description: str = ""
    style: str = "custom"
    reference_text: str = ""


class PresetActivateRequest(BaseModel):
    pass


# ===== 音色预设管理 =====

@router.get("/presets")
async def list_presets(include_unavailable: bool = True):
    """列出所有音色预设"""
    if not _presets_available:
        raise HTTPException(status_code=500, detail=f"音色管理模块不可用: {_preset_error}")
    
    presets = _preset_manager.list_presets(include_unavailable=include_unavailable)
    
    return {
        "code": 0,
        "message": "ok",
        "data": {
            "presets": [p.to_dict() for p in presets],
            "count": len(presets),
            "active_preset_id": _preset_manager._active_preset_id,
        }
    }


@router.get("/presets/{preset_id}")
async def get_preset(preset_id: str):
    """获取指定音色预设详情"""
    if not _presets_available:
        raise HTTPException(status_code=500, detail="音色管理模块不可用")
    
    preset = _preset_manager.get_preset(preset_id)
    if not preset:
        raise HTTPException(status_code=404, detail=f"音色预设 {preset_id} 不存在")
    
    return {
        "code": 0,
        "message": "ok",
        "data": {
            "preset": preset.to_dict(),
            "is_ready": _preset_manager.is_preset_ready(preset_id),
        }
    }


@router.post("/presets")
async def create_preset(
    name: str = Form(...),
    description: str = Form(""),
    style: str = Form("custom"),
    reference_text: str = Form(""),
    audio_file: UploadFile = File(...),
):
    """创建自定义音色预设（上传参考音频）"""
    if not _presets_available:
        raise HTTPException(status_code=500, detail="音色管理模块不可用")
    
    # 保存上传的音频
    import tempfile
    suffix = Path(audio_file.filename).suffix or '.wav'
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
        content = await audio_file.read()
        tmp.write(content)
        tmp_path = tmp.name
    
    try:
        preset = _preset_manager.add_custom_preset(
            name=name,
            audio_path=tmp_path,
            reference_text=reference_text,
            description=description,
            style=style,
        )
        
        if not preset:
            raise HTTPException(status_code=500, detail="创建音色预设失败")
        
        return {
            "code": 0,
            "message": "ok",
            "data": {
                "preset": preset.to_dict(),
                "is_ready": True,
            }
        }
    finally:
        # 清理临时文件（已被复制到存储目录）
        try:
            os.unlink(tmp_path)
        except Exception:
            pass


@router.delete("/presets/{preset_id}")
async def delete_preset(preset_id: str):
    """删除音色预设"""
    if not _presets_available:
        raise HTTPException(status_code=500, detail="音色管理模块不可用")
    
    success = _preset_manager.delete_preset(preset_id)
    if not success:
        raise HTTPException(status_code=400, detail="删除失败（内置预设不能删除或预设不存在）")
    
    return {
        "code": 0,
        "message": "ok",
        "data": {"deleted": preset_id}
    }


@router.put("/presets/{preset_id}/activate")
async def activate_preset(preset_id: str):
    """激活指定音色预设"""
    if not _presets_available:
        raise HTTPException(status_code=500, detail="音色管理模块不可用")
    
    if not _preset_manager.is_preset_ready(preset_id):
        raise HTTPException(status_code=400, detail="该音色尚未配置参考音频，无法激活")
    
    success = _preset_manager.set_active_preset(preset_id)
    if not success:
        raise HTTPException(status_code=404, detail=f"音色预设 {preset_id} 不存在")
    
    return {
        "code": 0,
        "message": "ok",
        "data": {"active_preset_id": preset_id}
    }


@router.post("/presets/{preset_id}/audio")
async def upload_reference_audio(
    preset_id: str,
    audio_file: UploadFile = File(...),
    reference_text: str = Form(""),
):
    """为音色预设上传/更新参考音频"""
    if not _presets_available:
        raise HTTPException(status_code=500, detail="音色管理模块不可用")
    
    preset = _preset_manager.get_preset(preset_id)
    if not preset:
        raise HTTPException(status_code=404, detail=f"音色预设 {preset_id} 不存在")
    
    # 保存上传的音频
    import tempfile
    suffix = Path(audio_file.filename).suffix or '.wav'
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
        content = await audio_file.read()
        tmp.write(content)
        tmp_path = tmp.name
    
    try:
        success = _preset_manager.set_reference_audio(
            preset_id=preset_id,
            audio_path=tmp_path,
            reference_text=reference_text,
        )
        
        if not success:
            raise HTTPException(status_code=500, detail="设置参考音频失败")
        
        updated_preset = _preset_manager.get_preset(preset_id)
        return {
            "code": 0,
            "message": "ok",
            "data": {
                "preset": updated_preset.to_dict() if updated_preset else None,
                "is_ready": True,
            }
        }
    finally:
        try:
            os.unlink(tmp_path)
        except Exception:
            pass


@router.get("/active")
async def get_active_preset():
    """获取当前激活的音色预设"""
    if not _presets_available:
        raise HTTPException(status_code=500, detail="音色管理模块不可用")
    
    preset = _preset_manager.get_active_preset()
    if not preset:
        return {
            "code": 0,
            "message": "ok",
            "data": {
                "active_preset": None,
                "is_ready": False,
                "note": "未配置任何可用音色",
            }
        }
    
    return {
        "code": 0,
        "message": "ok",
        "data": {
            "active_preset": preset.to_dict(),
            "is_ready": _preset_manager.is_preset_ready(preset.preset_id),
        }
    }


@router.get("/for-scene/{scene}")
async def get_preset_for_scene(scene: str):
    """根据场景获取推荐音色"""
    if not _presets_available:
        raise HTTPException(status_code=500, detail="音色管理模块不可用")
    
    preset = _preset_manager.get_preset_for_scene(scene)
    
    return {
        "code": 0,
        "message": "ok",
        "data": {
            "scene": scene,
            "recommended_preset": preset.to_dict() if preset else None,
            "is_ready": _preset_manager.is_preset_ready(preset.preset_id) if preset else False,
        }
    }


# ===== CosyVoice 服务管理 =====

@router.get("/cosyvoice/status")
async def cosyvoice_status():
    """获取 CosyVoice 服务状态"""
    if not _cosyvoice_available:
        return {
            "code": 0,
            "message": "ok",
            "data": {
                "available": False,
                "service_running": False,
                "note": "CosyVoice 客户端未安装",
            }
        }
    
    try:
        client = get_cosyvoice_client()
        available = client.is_available
        
        speakers = []
        if available:
            try:
                speakers = client.list_speakers()
            except Exception:
                pass
        
        return {
            "code": 0,
            "message": "ok",
            "data": {
                "available": True,
                "service_running": available,
                "api_url": client.config.api_url,
                "default_speaker_id": client.config.default_speaker_id,
                "registered_speakers": speakers,
                "sample_rate": client.config.sample_rate,
            }
        }
    except Exception as e:
        return {
            "code": 0,
            "message": "ok",
            "data": {
                "available": False,
                "service_running": False,
                "error": str(e),
            }
        }


@router.post("/cosyvoice/register")
async def register_presets_to_cosyvoice():
    """将所有可用音色预设注册到 CosyVoice 服务"""
    if not _cosyvoice_available or not _presets_available:
        raise HTTPException(status_code=500, detail="CosyVoice 客户端或音色管理模块不可用")
    
    try:
        client = get_cosyvoice_client()
        if not client.is_available:
            raise HTTPException(status_code=503, detail="CosyVoice 服务未运行")
        
        results = _preset_manager.register_with_cosyvoice(client)
        
        success_count = sum(1 for v in results.values() if v)
        
        return {
            "code": 0,
            "message": "ok",
            "data": {
                "results": results,
                "success_count": success_count,
                "total_count": len(results),
            }
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"注册失败: {str(e)}")
