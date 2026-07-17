"""
CosyVoice TTS 客户端
====================

通过 HTTP API 调用 CosyVoice 服务进行语音合成。
支持零样本语音克隆、指令控制、跨语言合成等高级功能。

服务部署方式：
- 本地部署：python -m cosyvoice_service
- 远程服务：配置 COSYVOICE_API_URL 环境变量

API 端点：
- POST /tts/zero_shot   - 零样本语音克隆
- POST /tts/instruct    - 指令控制合成
- POST /tts/cross_lingual - 跨语言合成
- POST /speakers/add    - 添加说话人（预存嵌入）
- GET  /speakers        - 获取已保存说话人列表
- GET  /health          - 健康检查
"""

import os
import io
import time
import base64
import tempfile
from typing import Optional, Dict, Any, List, Tuple
from pathlib import Path
from dataclasses import dataclass, field


@dataclass
class CosyVoiceConfig:
    """CosyVoice 配置"""
    # 服务地址
    api_url: str = "http://localhost:50000"
    
    # 默认说话人（零样本克隆用的参考音频）
    default_speaker_id: str = "yunxi_default"
    default_reference_audio: str = ""
    default_reference_text: str = ""
    
    # 合成参数
    stream: bool = False
    sample_rate: int = 22050
    
    # 指令控制默认值
    default_speed: str = "normal"  # slow / normal / fast
    default_emotion: str = "warm"  # warm / happy / sad / calm / excited
    
    # 超时设置（秒）
    timeout: int = 120
    
    # 重试设置
    max_retries: int = 2
    retry_delay: float = 1.0

    @classmethod
    def from_env(cls) -> "CosyVoiceConfig":
        """从环境变量加载配置"""
        return cls(
            api_url=os.environ.get("COSYVOICE_API_URL", "http://localhost:50000"),
            default_speaker_id=os.environ.get("COSYVOICE_SPEAKER_ID", "yunxi_default"),
            default_reference_audio=os.environ.get("COSYVOICE_REFERENCE_AUDIO", ""),
            default_reference_text=os.environ.get("COSYVOICE_REFERENCE_TEXT", 
                                                  "希望你以后能够做的比我还好呦。"),
            stream=os.environ.get("COSYVOICE_STREAM", "false").lower() == "true",
            sample_rate=int(os.environ.get("COSYVOICE_SAMPLE_RATE", "22050")),
            timeout=int(os.environ.get("COSYVOICE_TIMEOUT", "120")),
            max_retries=int(os.environ.get("COSYVOICE_MAX_RETRIES", "2")),
            retry_delay=float(os.environ.get("COSYVOICE_RETRY_DELAY", "1.0")),
        )

    @classmethod
    def from_dict(cls, config: Dict[str, Any]) -> "CosyVoiceConfig":
        """从字典加载配置"""
        cfg = cls()
        for key, value in config.items():
            if hasattr(cfg, key):
                setattr(cfg, key, value)
        return cfg


class CosyVoiceClient:
    """CosyVoice HTTP API 客户端
    
    支持同步和异步调用，自动重试和降级。
    """

    def __init__(self, config: Optional[CosyVoiceConfig] = None):
        self.config = config or CosyVoiceConfig.from_env()
        self._available = None  # None = 未检测, True/False = 已检测
        self._speakers_cache: Dict[str, Dict[str, Any]] = {}
        
    # ============================================================
    # 服务可用性检测
    # ============================================================

    @property
    def is_available(self) -> bool:
        """检查 CosyVoice 服务是否可用"""
        if self._available is not None:
            return self._available
        
        try:
            import requests
            resp = requests.get(
                f"{self.config.api_url}/health",
                timeout=5
            )
            self._available = resp.status_code == 200
        except Exception:
            self._available = False
        
        return self._available

    async def check_available_async(self) -> bool:
        """异步检查服务可用性"""
        if self._available is not None:
            return self._available
        
        try:
            import aiohttp
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    f"{self.config.api_url}/health",
                    timeout=aiohttp.ClientTimeout(total=5)
                ) as resp:
                    self._available = resp.status == 200
        except Exception:
            self._available = False
        
        return self._available

    def reset_availability(self) -> None:
        """重置可用性缓存（服务重启后调用）"""
        self._available = None

    # ============================================================
    # 说话人管理
    # ============================================================

    def add_speaker(
        self,
        speaker_id: str,
        reference_audio_path: str,
        reference_text: str = "",
    ) -> bool:
        """添加/注册说话人（保存声纹嵌入）
        
        Args:
            speaker_id: 说话人ID
            reference_audio_path: 参考音频路径 (WAV/MP3)
            reference_text: 参考音频对应的文本（可选，提升对齐精度）
        
        Returns:
            是否添加成功
        """
        if not os.path.exists(reference_audio_path):
            print(f"[CosyVoice] 参考音频不存在: {reference_audio_path}")
            return False
        
        try:
            import requests
            with open(reference_audio_path, 'rb') as f:
                files = {'reference_audio': f}
                data = {
                    'speaker_id': speaker_id,
                    'reference_text': reference_text,
                }
                resp = requests.post(
                    f"{self.config.api_url}/speakers/add",
                    files=files,
                    data=data,
                    timeout=self.config.timeout,
                )
            success = resp.status_code == 200
            if success:
                self._speakers_cache[speaker_id] = {
                    'reference_audio': reference_audio_path,
                    'reference_text': reference_text,
                }
            return success
        except Exception as e:
            print(f"[CosyVoice] 添加说话人失败: {e}")
            return False

    def list_speakers(self) -> List[Dict[str, Any]]:
        """获取已保存的说话人列表"""
        try:
            import requests
            resp = requests.get(
                f"{self.config.api_url}/speakers",
                timeout=10,
            )
            if resp.status_code == 200:
                data = resp.json()
                return data.get('speakers', [])
        except Exception:
            pass
        return []

    # ============================================================
    # 语音合成 - 零样本克隆
    # ============================================================

    def synthesize_zero_shot(
        self,
        text: str,
        reference_audio_path: Optional[str] = None,
        reference_text: Optional[str] = None,
        speaker_id: Optional[str] = None,
        output_path: Optional[str] = None,
    ) -> Dict[str, Any]:
        """零样本语音克隆合成（同步）
        
        Args:
            text: 要合成的文本
            reference_audio_path: 参考音频路径（与 speaker_id 二选一）
            reference_text: 参考音频对应的文本
            speaker_id: 已注册的说话人ID（与参考音频二选一，优先）
            output_path: 输出文件路径（可选）
        
        Returns:
            合成结果字典
        """
        import requests
        
        # 确定输出路径
        if output_path is None:
            tmp_file = tempfile.NamedTemporaryFile(suffix='.wav', delete=False)
            output_path = tmp_file.name
            tmp_file.close()
        
        # 构造请求数据
        data = {'text': text}
        files = {}
        
        if speaker_id:
            data['speaker_id'] = speaker_id
        elif reference_audio_path and os.path.exists(reference_audio_path):
            files['reference_audio'] = open(reference_audio_path, 'rb')
            if reference_text:
                data['reference_text'] = reference_text
        else:
            # 使用默认参考音频
            default_audio = self.config.default_reference_audio
            if default_audio and os.path.exists(default_audio):
                files['reference_audio'] = open(default_audio, 'rb')
                data['reference_text'] = self.config.default_reference_text
            else:
                # 关闭文件句柄
                for f in files.values():
                    f.close()
                return {
                    'success': False,
                    'error': '未提供参考音频且无默认配置',
                    'engine': 'cosyvoice',
                }
        
        try:
            # 重试逻辑
            last_error = None
            for attempt in range(self.config.max_retries + 1):
                try:
                    resp = requests.post(
                        f"{self.config.api_url}/tts/zero_shot",
                        data=data,
                        files=files if files else None,
                        timeout=self.config.timeout,
                    )
                    
                    if resp.status_code == 200:
                        # 保存音频
                        with open(output_path, 'wb') as f:
                            f.write(resp.content)
                        
                        duration = self._estimate_duration(text)
                        return {
                            'success': True,
                            'engine': 'cosyvoice',
                            'method': 'zero_shot',
                            'audio_path': output_path,
                            'audio_format': 'wav',
                            'sample_rate': self.config.sample_rate,
                            'duration': duration,
                            'text': text,
                            'speaker_id': speaker_id or 'reference_audio',
                        }
                    else:
                        last_error = f"HTTP {resp.status_code}: {resp.text[:200]}"
                except Exception as e:
                    last_error = str(e)
                
                if attempt < self.config.max_retries:
                    time.sleep(self.config.retry_delay)
            
            return {
                'success': False,
                'error': f"合成失败（重试{self.config.max_retries}次）: {last_error}",
                'engine': 'cosyvoice',
            }
        
        finally:
            # 关闭文件句柄
            for f in files.values():
                f.close()

    async def synthesize_zero_shot_async(
        self,
        text: str,
        reference_audio_path: Optional[str] = None,
        reference_text: Optional[str] = None,
        speaker_id: Optional[str] = None,
        output_path: Optional[str] = None,
    ) -> Dict[str, Any]:
        """零样本语音克隆合成（异步）"""
        import asyncio
        
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            None,
            lambda: self.synthesize_zero_shot(
                text, reference_audio_path, reference_text,
                speaker_id, output_path
            )
        )

    # ============================================================
    # 语音合成 - 指令控制
    # ============================================================

    def synthesize_instruct(
        self,
        text: str,
        instruction: str,
        reference_audio_path: Optional[str] = None,
        reference_text: Optional[str] = None,
        speaker_id: Optional[str] = None,
        output_path: Optional[str] = None,
    ) -> Dict[str, Any]:
        """指令控制语音合成（同步）
        
        通过自然语言指令控制语音风格，如：
        - "用开心的语气说"
        - "用四川话说"
        - "语速快一点"
        - "声音温柔一点"
        
        Args:
            text: 要合成的文本
            instruction: 控制指令（自然语言）
            reference_audio_path: 参考音频路径
            reference_text: 参考音频文本
            speaker_id: 已注册说话人ID
            output_path: 输出路径
        
        Returns:
            合成结果字典
        """
        import requests
        
        if output_path is None:
            tmp_file = tempfile.NamedTemporaryFile(suffix='.wav', delete=False)
            output_path = tmp_file.name
            tmp_file.close()
        
        data = {
            'text': text,
            'instruction': instruction,
        }
        files = {}
        
        if speaker_id:
            data['speaker_id'] = speaker_id
        elif reference_audio_path and os.path.exists(reference_audio_path):
            files['reference_audio'] = open(reference_audio_path, 'rb')
            if reference_text:
                data['reference_text'] = reference_text
        else:
            default_audio = self.config.default_reference_audio
            if default_audio and os.path.exists(default_audio):
                files['reference_audio'] = open(default_audio, 'rb')
                data['reference_text'] = self.config.default_reference_text
            else:
                for f in files.values():
                    f.close()
                return {
                    'success': False,
                    'error': '未提供参考音频且无默认配置',
                    'engine': 'cosyvoice',
                }
        
        try:
            last_error = None
            for attempt in range(self.config.max_retries + 1):
                try:
                    resp = requests.post(
                        f"{self.config.api_url}/tts/instruct",
                        data=data,
                        files=files if files else None,
                        timeout=self.config.timeout,
                    )
                    
                    if resp.status_code == 200:
                        with open(output_path, 'wb') as f:
                            f.write(resp.content)
                        
                        duration = self._estimate_duration(text)
                        return {
                            'success': True,
                            'engine': 'cosyvoice',
                            'method': 'instruct',
                            'audio_path': output_path,
                            'audio_format': 'wav',
                            'sample_rate': self.config.sample_rate,
                            'duration': duration,
                            'text': text,
                            'instruction': instruction,
                            'speaker_id': speaker_id or 'reference_audio',
                        }
                    else:
                        last_error = f"HTTP {resp.status_code}: {resp.text[:200]}"
                except Exception as e:
                    last_error = str(e)
                
                if attempt < self.config.max_retries:
                    time.sleep(self.config.retry_delay)
            
            return {
                'success': False,
                'error': f"合成失败（重试{self.config.max_retries}次）: {last_error}",
                'engine': 'cosyvoice',
            }
        
        finally:
            for f in files.values():
                f.close()

    async def synthesize_instruct_async(
        self,
        text: str,
        instruction: str,
        reference_audio_path: Optional[str] = None,
        reference_text: Optional[str] = None,
        speaker_id: Optional[str] = None,
        output_path: Optional[str] = None,
    ) -> Dict[str, Any]:
        """指令控制语音合成（异步）"""
        import asyncio
        
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            None,
            lambda: self.synthesize_instruct(
                text, instruction, reference_audio_path,
                reference_text, speaker_id, output_path
            )
        )

    # ============================================================
    # 语音合成 - 跨语言
    # ============================================================

    def synthesize_cross_lingual(
        self,
        text: str,
        reference_audio_path: Optional[str] = None,
        speaker_id: Optional[str] = None,
        output_path: Optional[str] = None,
    ) -> Dict[str, Any]:
        """跨语言语音合成（同步）
        
        用一种语言的参考音频合成另一种语言的语音。
        文本中使用 <|zh|><|en|><|jp|><|yue|><|ko|> 标签切换语言。
        """
        import requests
        
        if output_path is None:
            tmp_file = tempfile.NamedTemporaryFile(suffix='.wav', delete=False)
            output_path = tmp_file.name
            tmp_file.close()
        
        data = {'text': text}
        files = {}
        
        if speaker_id:
            data['speaker_id'] = speaker_id
        elif reference_audio_path and os.path.exists(reference_audio_path):
            files['reference_audio'] = open(reference_audio_path, 'rb')
        else:
            default_audio = self.config.default_reference_audio
            if default_audio and os.path.exists(default_audio):
                files['reference_audio'] = open(default_audio, 'rb')
            else:
                for f in files.values():
                    f.close()
                return {
                    'success': False,
                    'error': '未提供参考音频且无默认配置',
                    'engine': 'cosyvoice',
                }
        
        try:
            last_error = None
            for attempt in range(self.config.max_retries + 1):
                try:
                    resp = requests.post(
                        f"{self.config.api_url}/tts/cross_lingual",
                        data=data,
                        files=files if files else None,
                        timeout=self.config.timeout,
                    )
                    
                    if resp.status_code == 200:
                        with open(output_path, 'wb') as f:
                            f.write(resp.content)
                        
                        duration = self._estimate_duration(text)
                        return {
                            'success': True,
                            'engine': 'cosyvoice',
                            'method': 'cross_lingual',
                            'audio_path': output_path,
                            'audio_format': 'wav',
                            'sample_rate': self.config.sample_rate,
                            'duration': duration,
                            'text': text,
                            'speaker_id': speaker_id or 'reference_audio',
                        }
                    else:
                        last_error = f"HTTP {resp.status_code}: {resp.text[:200]}"
                except Exception as e:
                    last_error = str(e)
                
                if attempt < self.config.max_retries:
                    time.sleep(self.config.retry_delay)
            
            return {
                'success': False,
                'error': f"合成失败（重试{self.config.max_retries}次）: {last_error}",
                'engine': 'cosyvoice',
            }
        
        finally:
            for f in files.values():
                f.close()

    # ============================================================
    # 辅助方法
    # ============================================================

    def _estimate_duration(self, text: str) -> float:
        """估算音频时长（秒）
        
        CosyVoice 语速约每秒 4-5 个中文字
        """
        # 移除标签和控制符
        clean_text = text
        for tag in ['<|zh|>', '<|en|>', '<|jp|>', '<|yue|>', '<|ko|>',
                    '[laughter]', '[breath]', '<|endofprompt|>']:
            clean_text = clean_text.replace(tag, '')
        
        return len(clean_text) / 4.5

    def build_instruction(
        self,
        emotion: Optional[str] = None,
        speed: Optional[str] = None,
        dialect: Optional[str] = None,
        volume: Optional[str] = None,
        custom: Optional[str] = None,
    ) -> str:
        """构建指令控制文本
        
        Args:
            emotion: 情感（warm/happy/sad/calm/excited/gentle/serious）
            speed: 语速（slow/normal/fast）
            dialect: 方言（sichuan/dongbei/shaanxi/cantonese/minnan）
            volume: 音量（low/normal/high）
            custom: 自定义指令
        
        Returns:
            组合后的指令文本
        """
        instructions = []
        
        # 情感映射
        emotion_map = {
            'warm': '用温暖温柔的语气说',
            'happy': '用开心愉悦的语气说',
            'sad': '用略带忧伤的语气说',
            'calm': '用平静沉稳的语气说',
            'excited': '用兴奋激动的语气说',
            'gentle': '用轻柔温和的语气说',
            'serious': '用严肃认真的语气说',
            'playful': '用俏皮活泼的语气说',
        }
        if emotion and emotion in emotion_map:
            instructions.append(emotion_map[emotion])
        
        # 语速映射
        speed_map = {
            'slow': '语速慢一点',
            'normal': '语速适中',
            'fast': '语速快一点',
        }
        if speed and speed in speed_map and speed != 'normal':
            instructions.append(speed_map[speed])
        
        # 方言映射
        dialect_map = {
            'sichuan': '用四川话说',
            'dongbei': '用东北话说',
            'shaanxi': '用陕西话说',
            'cantonese': '用广东话说',
            'minnan': '用闽南话说',
            'shanghai': '用上海话说',
            'tianjin': '用天津话说',
        }
        if dialect and dialect in dialect_map:
            instructions.append(dialect_map[dialect])
        
        # 音量
        if volume and volume != 'normal':
            vol_map = {'low': '音量小一点', 'high': '音量大一点'}
            if volume in vol_map:
                instructions.append(vol_map[volume])
        
        # 自定义指令
        if custom:
            instructions.append(custom)
        
        if not instructions:
            return "用自然的语气说"
        
        return "，".join(instructions) + "<|endofprompt|>"


# ============================================================
# 便捷函数
# ============================================================

_default_client: Optional[CosyVoiceClient] = None


def get_cosyvoice_client(config: Optional[CosyVoiceConfig] = None) -> CosyVoiceClient:
    """获取全局 CosyVoice 客户端实例（单例）"""
    global _default_client
    if _default_client is None or config is not None:
        _default_client = CosyVoiceClient(config)
    return _default_client


def is_cosyvoice_available() -> bool:
    """检查 CosyVoice 服务是否可用（便捷函数）"""
    try:
        client = get_cosyvoice_client()
        return client.is_available
    except Exception:
        return False
