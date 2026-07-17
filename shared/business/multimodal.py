"""
多模态理解接口

功能：
1. 图像理解 - 图片描述、OCR、物体检测
2. 音频理解 - 语音识别、声纹识别、情感分析
3. 视频理解 - 关键帧提取、视频描述
4. 多模态融合 - 图文联合理解

设计原则：
- 统一接口，后端可插拔（本地模型/云端API）
- 异步处理，支持流式输入
- 结果缓存，减少重复计算
"""

import json
import time
import base64
import hashlib
import threading
import logging
from pathlib import Path
from typing import Dict, List, Optional, Any, Tuple, Union
from dataclasses import dataclass, field, asdict
from enum import Enum
from io import BytesIO

logger = logging.getLogger(__name__)


class ModalityType(str, Enum):
    """模态类型"""
    TEXT = "text"
    IMAGE = "image"
    AUDIO = "audio"
    VIDEO = "video"


class VisionTaskType(str, Enum):
    """视觉任务类型"""
    CAPTION = "caption"  # 图像描述
    OCR = "ocr"  # 文字识别
    OBJECT_DETECTION = "object_detection"  # 物体检测
    FACE_DETECTION = "face_detection"  # 人脸检测
    SCENE_CLASSIFICATION = "scene_classification"  # 场景分类
    QUALITY_ASSESSMENT = "quality_assessment"  # 图像质量评估
    GENERAL = "general"  # 通用理解


class AudioTaskType(str, Enum):
    """音频任务类型"""
    ASR = "asr"  # 语音识别
    SPEAKER_ID = "speaker_id"  # 说话人识别
    EMOTION = "emotion"  # 情感分析
    LANGUAGE_ID = "language_id"  # 语种识别
    GENERAL = "general"  # 通用理解


class ProviderType(str, Enum):
    """服务提供商类型"""
    LOCAL = "local"  # 本地模型
    OPENAI = "openai"  # OpenAI API
    DEEPSEEK = "deepseek"  # DeepSeek API
    QWEN = "qwen"  # 阿里通义
    OLLAMA = "ollama"  # Ollama 本地


@dataclass
class MultimodalResult:
    """多模态处理结果"""
    task_id: str
    task_type: str
    modality: str
    provider: str
    success: bool
    result: Optional[Dict[str, Any]] = None
    error: Optional[str] = None
    confidence: float = 0.0
    processing_time: float = 0.0
    created_at: float = field(default_factory=time.time)
    
    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class CacheEntry:
    """缓存条目"""
    key: str
    result: MultimodalResult
    created_at: float = field(default_factory=time.time)
    access_count: int = 0
    
    def is_expired(self, ttl: int = 3600) -> bool:
        return time.time() - self.created_at > ttl


class MultimodalCache:
    """多模态结果缓存（LRU + TTL）"""
    
    def __init__(self, max_size: int = 100, ttl: int = 3600):
        self._max_size = max_size
        self._ttl = ttl
        self._cache: Dict[str, CacheEntry] = {}
        self._lock = threading.RLock()
    
    def get(self, key: str) -> Optional[MultimodalResult]:
        """获取缓存"""
        with self._lock:
            entry = self._cache.get(key)
            if not entry:
                return None
            
            if entry.is_expired(self._ttl):
                del self._cache[key]
                return None
            
            entry.access_count += 1
            return entry.result
    
    def set(self, key: str, result: MultimodalResult):
        """设置缓存"""
        with self._lock:
            # 已满则清理最旧或访问最少的
            if len(self._cache) >= self._max_size:
                self._evict()
            
            self._cache[key] = CacheEntry(key=key, result=result)
    
    def _evict(self):
        """淘汰缓存条目"""
        if not self._cache:
            return
        
        # 优先淘汰过期的
        expired = [k for k, v in self._cache.items() if v.is_expired(self._ttl)]
        if expired:
            for k in expired[:5]:  # 一次最多清理5个
                del self._cache[k]
            return
        
        # 否则淘汰访问最少且最旧的
        sorted_keys = sorted(
            self._cache.keys(),
            key=lambda k: (self._cache[k].access_count, self._cache[k].created_at)
        )
        if sorted_keys:
            del self._cache[sorted_keys[0]]
    
    def clear(self):
        """清空缓存"""
        with self._lock:
            self._cache.clear()
    
    def size(self) -> int:
        """缓存大小"""
        with self._lock:
            return len(self._cache)


class MultimodalEngine:
    """多模态理解引擎 - 单例模式"""
    
    _instance: Optional["MultimodalEngine"] = None
    
    def __new__(cls, *args, **kwargs):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance
    
    def __init__(self, config: Optional[Dict] = None):
        if self._initialized:
            return
        self._initialized = True
        
        # 配置
        self._config = config or {}
        self._default_provider = self._config.get("default_provider", ProviderType.OLLAMA.value)
        
        # 缓存
        cache_size = self._config.get("cache_size", 100)
        cache_ttl = self._config.get("cache_ttl", 3600)
        self._cache = MultimodalCache(max_size=cache_size, ttl=cache_ttl)
        
        # 任务记录
        self._tasks: Dict[str, MultimodalResult] = {}
        self._lock = threading.RLock()
        
        # 提供商配置
        self._providers = self._init_providers()
    
    def _init_providers(self) -> Dict[str, Dict]:
        """初始化提供商配置"""
        providers = {}
        
        # Ollama 本地视觉模型
        providers[ProviderType.OLLAMA.value] = {
            "enabled": True,
            "base_url": "http://localhost:11434",
            "vision_model": "llava:7b",
            "text_model": "qwen2.5:7b",
        }
        
        # DeepSeek API
        providers[ProviderType.DEEPSEEK.value] = {
            "enabled": False,
            "api_key": "",
            "base_url": "https://api.deepseek.com",
            "vision_model": "deepseek-vl",
        }
        
        # OpenAI API
        providers[ProviderType.OPENAI.value] = {
            "enabled": False,
            "api_key": "",
            "base_url": "https://api.openai.com/v1",
            "vision_model": "gpt-4o",
        }
        
        return providers
    
    def _get_cache_key(self, modality: str, task_type: str, 
                       data_hash: str, params: Optional[Dict] = None) -> str:
        """生成缓存键"""
        params_str = json.dumps(params or {}, sort_keys=True)
        raw = f"{modality}:{task_type}:{data_hash}:{params_str}"
        return hashlib.md5(raw.encode()).hexdigest()
    
    def _hash_image(self, image_data: bytes) -> str:
        """计算图像哈希"""
        return hashlib.md5(image_data).hexdigest()
    
    def _hash_audio(self, audio_data: bytes) -> str:
        """计算音频哈希"""
        return hashlib.md5(audio_data).hexdigest()
    
    # ==================== 图像理解接口 ====================
    
    async def understand_image(self, 
                               image_input: Union[str, bytes, Path],
                               task_type: str = VisionTaskType.GENERAL.value,
                               prompt: Optional[str] = None,
                               provider: Optional[str] = None) -> MultimodalResult:
        """
        理解图像内容
        
        Args:
            image_input: 图像输入（路径/bytes/base64）
            task_type: 任务类型
            prompt: 自定义提示词
            provider: 服务提供商
        
        Returns:
            MultimodalResult
        """
        start_time = time.time()
        provider = provider or self._default_provider
        
        # 读取并解析图像
        image_data = self._load_image(image_input)
        image_hash = self._hash_image(image_data)
        
        # 检查缓存
        cache_key = self._get_cache_key("image", task_type, image_hash, {"prompt": prompt})
        cached = self._cache.get(cache_key)
        if cached:
            return cached
        
        # 生成任务ID
        task_id = f"img_{int(time.time())}_{image_hash[:8]}"
        
        try:
            # 调用对应提供商
            if provider == ProviderType.OLLAMA.value:
                result = await self._ollama_vision(image_data, task_type, prompt)
            elif provider == ProviderType.DEEPSEEK.value:
                result = await self._deepseek_vision(image_data, task_type, prompt)
            elif provider == ProviderType.OPENAI.value:
                result = await self._openai_vision(image_data, task_type, prompt)
            else:
                raise ValueError(f"不支持的提供商: {provider}")
            
            mm_result = MultimodalResult(
                task_id=task_id,
                task_type=task_type,
                modality=ModalityType.IMAGE.value,
                provider=provider,
                success=True,
                result=result,
                confidence=result.get("confidence", 0.8),
                processing_time=time.time() - start_time,
            )
            
        except Exception as e:
            mm_result = MultimodalResult(
                task_id=task_id,
                task_type=task_type,
                modality=ModalityType.IMAGE.value,
                provider=provider,
                success=False,
                error=str(e),
                processing_time=time.time() - start_time,
            )
        
        # 缓存结果
        if mm_result.success:
            self._cache.set(cache_key, mm_result)
        
        # 记录任务
        with self._lock:
            self._tasks[task_id] = mm_result
        
        return mm_result
    
    def _load_image(self, image_input: Union[str, bytes, Path]) -> bytes:
        """加载图像数据"""
        if isinstance(image_input, bytes):
            return image_input
        
        if isinstance(image_input, Path):
            with open(image_input, "rb") as f:
                return f.read()
        
        if isinstance(image_input, str):
            # 尝试作为文件路径
            path = Path(image_input)
            if path.exists():
                with open(path, "rb") as f:
                    return f.read()
            
            # 尝试作为 base64
            try:
                # 去掉 data:image/xxx;base64, 前缀
                if "," in image_input and image_input.startswith("data:image"):
                    image_input = image_input.split(",", 1)[1]
                return base64.b64decode(image_input)
            except Exception as e:
                # base64 解码失败是预期内的尝试，继续往下走抛出统一异常
                logger.debug("图像 base64 解码失败: %s", e)
            
            raise ValueError(f"无法解析图像输入: {image_input[:50]}...")
        
        raise TypeError(f"不支持的图像输入类型: {type(image_input)}")
    
    async def _ollama_vision(self, image_data: bytes, task_type: str, 
                             prompt: Optional[str] = None) -> Dict[str, Any]:
        """调用 Ollama 视觉模型"""
        import aiohttp
        
        provider_config = self._providers.get(ProviderType.OLLAMA.value, {})
        if not provider_config.get("enabled"):
            raise RuntimeError("Ollama 提供商未启用")
        
        base_url = provider_config.get("base_url", "http://localhost:11434")
        model = provider_config.get("vision_model", "llava:7b")
        
        # 根据任务类型构建提示词
        system_prompt = self._build_vision_prompt(task_type)
        user_prompt = prompt or "请描述这张图片的内容"
        
        # base64 编码
        image_b64 = base64.b64encode(image_data).decode()
        
        # 调用 Ollama API
        async with aiohttp.ClientSession() as session:
            url = f"{base_url}/api/generate"
            payload = {
                "model": model,
                "prompt": user_prompt,
                "system": system_prompt,
                "images": [image_b64],
                "stream": False,
            }
            
            async with session.post(url, json=payload, timeout=60) as resp:
                if resp.status != 200:
                    raise RuntimeError(f"Ollama API 返回错误: {resp.status}")
                data = await resp.json()
        
        return {
            "description": data.get("response", ""),
            "model": model,
            "confidence": 0.75,
        }
    
    async def _deepseek_vision(self, image_data: bytes, task_type: str,
                               prompt: Optional[str] = None) -> Dict[str, Any]:
        """调用 DeepSeek 视觉 API"""
        # 预留接口，待后续实现
        raise NotImplementedError("DeepSeek 视觉接口待实现")
    
    async def _openai_vision(self, image_data: bytes, task_type: str,
                             prompt: Optional[str] = None) -> Dict[str, Any]:
        """调用 OpenAI 视觉 API"""
        # 预留接口，待后续实现
        raise NotImplementedError("OpenAI 视觉接口待实现")
    
    def _build_vision_prompt(self, task_type: str) -> str:
        """构建视觉任务提示词"""
        prompts = {
            VisionTaskType.CAPTION.value: "你是一位图像描述专家。请用简洁的中文描述这张图片的主要内容。",
            VisionTaskType.OCR.value: "你是一位文字识别专家。请识别图片中的所有文字，按原文格式输出。",
            VisionTaskType.OBJECT_DETECTION.value: "你是一位物体检测专家。请列出图片中所有你能识别的物体，包括它们的大致位置。",
            VisionTaskType.FACE_DETECTION.value: "你是一位人脸检测专家。请描述图片中人脸的数量、位置、表情等特征。",
            VisionTaskType.SCENE_CLASSIFICATION.value: "你是一位场景分类专家。请判断这张图片属于什么场景类型。",
            VisionTaskType.QUALITY_ASSESSMENT.value: "你是一位图像质量评估专家。请评估这张图片的质量，包括清晰度、亮度、构图等方面。",
            VisionTaskType.GENERAL.value: "你是一位多模态理解助手。请全面理解这张图片，回答用户的问题。",
        }
        return prompts.get(task_type, prompts[VisionTaskType.GENERAL.value])
    
    # ==================== 音频理解接口 ====================
    
    async def understand_audio(self,
                               audio_input: Union[str, bytes, Path],
                               task_type: str = AudioTaskType.ASR.value,
                               language: Optional[str] = None,
                               provider: Optional[str] = None) -> MultimodalResult:
        """
        理解音频内容
        
        Args:
            audio_input: 音频输入（路径/bytes）
            task_type: 任务类型
            language: 语言
            provider: 服务提供商
        
        Returns:
            MultimodalResult
        """
        start_time = time.time()
        provider = provider or self._default_provider
        
        # 读取音频
        audio_data = self._load_audio(audio_input)
        audio_hash = self._hash_audio(audio_data)
        
        # 检查缓存
        cache_key = self._get_cache_key("audio", task_type, audio_hash, {"language": language})
        cached = self._cache.get(cache_key)
        if cached:
            return cached
        
        task_id = f"aud_{int(time.time())}_{audio_hash[:8]}"
        
        try:
            # 目前主要支持 ASR，使用本地 whisper 或 API
            result = await self._local_asr(audio_data, language)
            
            mm_result = MultimodalResult(
                task_id=task_id,
                task_type=task_type,
                modality=ModalityType.AUDIO.value,
                provider=provider,
                success=True,
                result=result,
                confidence=result.get("confidence", 0.8),
                processing_time=time.time() - start_time,
            )
            
        except Exception as e:
            mm_result = MultimodalResult(
                task_id=task_id,
                task_type=task_type,
                modality=ModalityType.AUDIO.value,
                provider=provider,
                success=False,
                error=str(e),
                processing_time=time.time() - start_time,
            )
        
        if mm_result.success:
            self._cache.set(cache_key, mm_result)
        
        with self._lock:
            self._tasks[task_id] = mm_result
        
        return mm_result
    
    def _load_audio(self, audio_input: Union[str, bytes, Path]) -> bytes:
        """加载音频数据"""
        if isinstance(audio_input, bytes):
            return audio_input
        
        if isinstance(audio_input, Path):
            with open(audio_input, "rb") as f:
                return f.read()
        
        if isinstance(audio_input, str):
            path = Path(audio_input)
            if path.exists():
                with open(path, "rb") as f:
                    return f.read()
            raise ValueError(f"音频文件不存在: {audio_input}")
        
        raise TypeError(f"不支持的音频输入类型: {type(audio_input)}")
    
    async def _local_asr(self, audio_data: bytes, language: Optional[str] = None) -> Dict[str, Any]:
        """本地语音识别（预留接口，可接入 faster-whisper 等）"""
        # 简化实现，实际应调用 whisper / faster-whisper
        return {
            "text": "[ASR 功能待接入本地 whisper 模型]",
            "language": language or "zh",
            "confidence": 0.0,
            "segments": [],
        }
    
    # ==================== 多模态融合接口 ====================
    
    async def multimodal_understand(self,
                                    text: Optional[str] = None,
                                    image: Optional[Union[str, bytes, Path]] = None,
                                    audio: Optional[Union[str, bytes, Path]] = None,
                                    prompt: Optional[str] = None,
                                    provider: Optional[str] = None) -> MultimodalResult:
        """
        多模态联合理解
        
        Args:
            text: 文本输入
            image: 图像输入
            audio: 音频输入
            prompt: 任务提示词
            provider: 服务提供商
        
        Returns:
            MultimodalResult
        """
        start_time = time.time()
        provider = provider or self._default_provider
        
        task_id = f"mm_{int(time.time())}_{hashlib.md5((text or '').encode()).hexdigest()[:8]}"
        
        # 收集各模态结果
        results = {}
        
        # 图像理解
        if image:
            img_result = await self.understand_image(
                image, 
                task_type=VisionTaskType.GENERAL.value,
                prompt=prompt,
                provider=provider
            )
            results["image"] = img_result.to_dict()
        
        # 音频理解
        if audio:
            aud_result = await self.understand_audio(
                audio,
                task_type=AudioTaskType.ASR.value,
                provider=provider
            )
            results["audio"] = aud_result.to_dict()
        
        # 文本是输入的一部分
        if text:
            results["text"] = {"content": text}
        
        # 融合结果（简化版：拼接各模态描述后调用 LLM 综合理解）
        fused_result = await self._fuse_results(results, prompt)
        
        mm_result = MultimodalResult(
            task_id=task_id,
            task_type="multimodal_fusion",
            modality="multimodal",
            provider=provider,
            success=True,
            result={
                "modalities": list(results.keys()),
                "fused_answer": fused_result,
                "individual_results": results,
            },
            confidence=0.75,
            processing_time=time.time() - start_time,
        )
        
        with self._lock:
            self._tasks[task_id] = mm_result
        
        return mm_result
    
    async def _fuse_results(self, results: Dict, prompt: Optional[str] = None) -> str:
        """融合多模态结果（简化版）"""
        # 实际应调用 LLM 进行融合推理
        parts = []
        if "image" in results and results["image"].get("success"):
            img_desc = results["image"]["result"].get("description", "")
            parts.append(f"图像内容: {img_desc}")
        
        if "audio" in results and results["audio"].get("success"):
            aud_text = results["audio"]["result"].get("text", "")
            parts.append(f"语音内容: {aud_text}")
        
        if "text" in results:
            parts.append(f"文本内容: {results['text']['content']}")
        
        combined = "\n".join(parts)
        
        if prompt:
            return f"基于以下多模态信息，回答用户问题：\n{combined}\n\n用户问题: {prompt}\n\n回答: "
        else:
            return f"多模态理解结果汇总：\n{combined}"
    
    # ==================== 管理接口 ====================
    
    def get_task(self, task_id: str) -> Optional[MultimodalResult]:
        """获取任务结果"""
        with self._lock:
            return self._tasks.get(task_id)
    
    def get_stats(self) -> Dict[str, Any]:
        """获取统计信息"""
        with self._lock:
            total = len(self._tasks)
            success = sum(1 for t in self._tasks.values() if t.success)
            failed = total - success
            
            by_modality = {}
            for t in self._tasks.values():
                m = t.modality
                by_modality[m] = by_modality.get(m, 0) + 1
            
            return {
                "total_tasks": total,
                "success": success,
                "failed": failed,
                "by_modality": by_modality,
                "cache_size": self._cache.size(),
                "default_provider": self._default_provider,
            }
    
    def clear_cache(self):
        """清空缓存"""
        self._cache.clear()
    
    def update_provider_config(self, provider: str, config: Dict):
        """更新提供商配置"""
        if provider in self._providers:
            self._providers[provider].update(config)
    
    def set_default_provider(self, provider: str):
        """设置默认提供商"""
        self._default_provider = provider
    
    def get_providers(self) -> Dict[str, Dict]:
        """获取所有提供商配置（脱敏）"""
        result = {}
        for name, config in self._providers.items():
            safe_config = {k: v for k, v in config.items() if k != "api_key"}
            if "api_key" in config:
                safe_config["api_key_configured"] = bool(config["api_key"])
            result[name] = safe_config
        return result


# 全局单例
_multimodal_engine: Optional[MultimodalEngine] = None


def get_multimodal_engine(config: Optional[Dict] = None) -> MultimodalEngine:
    """获取多模态引擎单例"""
    global _multimodal_engine
    if _multimodal_engine is None:
        _multimodal_engine = MultimodalEngine(config=config)
    return _multimodal_engine
