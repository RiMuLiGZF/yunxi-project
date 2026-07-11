"""
云汐系统 - 语音引擎模块
- TTS: 文本转语音（edge-tts在线 + 浏览器SpeechSynthesis离线兜底）
- ASR: 语音转文本（faster-whisper本地离线 + vosk轻量备选）
- 统一接口，支持引擎切换和自动降级
"""

import os
import asyncio
import tempfile
from typing import Optional, Dict, Any, List
from pathlib import Path


class TTSEngine:
    """语音合成引擎（统一接口）

    优先级: edge-tts(在线) > pyttsx3(离线系统) > mock(文本返回)
    """

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        self.config = config or {}
        self._edge_tts = None
        self._pyttsx3_engine = None
        self._voice_type = self.config.get('voice_type', 'warm_female')
        self._voice_speed = self.config.get('voice_speed', 1.0)
        self._voice_pitch = self.config.get('voice_pitch', 1.0)
        self._prefer_online = self.config.get('prefer_online', True)

        # 语音类型映射
        self._voice_map = {
            'warm_female': {'edge_voice': 'zh-CN-XiaoxiaoNeural', 'label': '温暖女声'},
            'clear_female': {'edge_voice': 'zh-CN-XiaoyiNeural', 'label': '清澈女声'},
            'gentle_male': {'edge_voice': 'zh-CN-YunxiNeural', 'label': '温柔男声'},
            'cute_child': {'edge_voice': 'zh-CN-XiaoyouNeural', 'label': '可爱童声'},
            'robot': {'edge_voice': 'zh-CN-YunyangNeural', 'label': '机械音'},
        }

    @property
    def available_engines(self) -> List[str]:
        """可用引擎列表"""
        engines = []
        try:
            import edge_tts  # noqa
            engines.append('edge-tts')
        except ImportError:
            pass
        try:
            import pyttsx3  # noqa
            engines.append('pyttsx3')
        except ImportError:
            pass
        engines.append('mock')
        return engines

    @property
    def current_engine(self) -> str:
        """当前使用的引擎"""
        engines = self.available_engines
        if self._prefer_online and 'edge-tts' in engines:
            return 'edge-tts'
        if 'pyttsx3' in engines:
            return 'pyttsx3'
        return 'mock'

    def get_voice_options(self) -> List[Dict[str, str]]:
        """获取可用语音选项"""
        options = []
        for key, info in self._voice_map.items():
            options.append({
                'id': key,
                'name': info['label'],
                'engine': self.current_engine,
            })
        return options

    def _get_edge_voice(self) -> str:
        """获取 edge-tts 语音名称"""
        voice_info = self._voice_map.get(self._voice_type, self._voice_map['warm_female'])
        return voice_info['edge_voice']

    def _get_rate(self) -> str:
        """获取语速参数 (edge-tts格式: +20% / -10%)"""
        speed_percent = int((self._voice_speed - 1.0) * 100)
        if speed_percent >= 0:
            return f"+{speed_percent}%"
        return f"{speed_percent}%"

    async def synthesize(self, text: str, output_path: Optional[str] = None) -> Dict[str, Any]:
        """文本转语音

        Args:
            text: 要合成的文本
            output_path: 输出文件路径（可选，不指定则返回临时文件路径）

        Returns:
            {
                'success': bool,
                'engine': str,
                'audio_path': str,  # 音频文件路径
                'audio_format': str,  # mp3 / wav
                'duration': float,  # 预估时长（秒）
                'text': str,
            }
        """
        text = text.strip()
        if not text:
            return {'success': False, 'error': '文本不能为空', 'engine': self.current_engine}

        engine = self.current_engine

        # 尝试 edge-tts
        if engine == 'edge-tts':
            try:
                return await self._synthesize_edge_tts(text, output_path)
            except Exception as e:
                print(f"[TTS] edge-tts 失败，降级: {e}")
                engine = 'pyttsx3' if 'pyttsx3' in self.available_engines else 'mock'

        # 尝试 pyttsx3
        if engine == 'pyttsx3':
            try:
                return self._synthesize_pyttsx3(text, output_path)
            except Exception as e:
                print(f"[TTS] pyttsx3 失败，降级到mock: {e}")
                engine = 'mock'

        # Mock: 只返回文本信息
        return {
            'success': True,
            'engine': 'mock',
            'audio_path': None,
            'audio_format': None,
            'duration': len(text) * 0.2,  # 估算时长
            'text': text,
            'note': 'Mock模式：无音频输出，仅返回文本',
        }

    async def _synthesize_edge_tts(self, text: str, output_path: Optional[str] = None) -> Dict[str, Any]:
        """使用 edge-tts 合成语音"""
        import edge_tts

        if output_path is None:
            tmp_file = tempfile.NamedTemporaryFile(suffix='.mp3', delete=False)
            output_path = tmp_file.name
            tmp_file.close()

        voice = self._get_edge_voice()
        rate = self._get_rate()

        communicate = edge_tts.Communicate(text, voice, rate=rate)
        await communicate.save(output_path)

        # 估算时长（约每秒4-5个中文字）
        duration = len(text) / 4.5

        return {
            'success': True,
            'engine': 'edge-tts',
            'audio_path': output_path,
            'audio_format': 'mp3',
            'duration': duration,
            'text': text,
            'voice': voice,
        }

    def _synthesize_pyttsx3(self, text: str, output_path: Optional[str] = None) -> Dict[str, Any]:
        """使用 pyttsx3 合成语音（离线）"""
        import pyttsx3

        if self._pyttsx3_engine is None:
            self._pyttsx3_engine = pyttsx3.init()

        # 设置语速
        base_rate = self._pyttsx3_engine.getProperty('rate')
        self._pyttsx3_engine.setProperty('rate', int(base_rate * self._voice_speed))

        if output_path:
            # 保存到文件
            self._pyttsx3_engine.save_to_file(text, output_path)
            self._pyttsx3_engine.runAndWait()
            audio_format = Path(output_path).suffix.lstrip('.') or 'wav'
        else:
            # 直接播放（不保存文件）
            output_path = None
            audio_format = None
            self._pyttsx3_engine.say(text)
            self._pyttsx3_engine.runAndWait()

        return {
            'success': True,
            'engine': 'pyttsx3',
            'audio_path': output_path,
            'audio_format': audio_format,
            'duration': len(text) * 0.25,
            'text': text,
        }

    def speak(self, text: str) -> bool:
        """直接播放语音（不保存文件）"""
        engine = self.current_engine

        if engine == 'pyttsx3':
            try:
                import pyttsx3
                if self._pyttsx3_engine is None:
                    self._pyttsx3_engine = pyttsx3.init()
                base_rate = self._pyttsx3_engine.getProperty('rate')
                self._pyttsx3_engine.setProperty('rate', int(base_rate * self._voice_speed))
                self._pyttsx3_engine.say(text)
                self._pyttsx3_engine.runAndWait()
                return True
            except Exception as e:
                print(f"[TTS] pyttsx3播放失败: {e}")

        # edge-tts 需要生成文件后播放，这里暂不实现
        # 前端会通过音频元素播放
        return False

    def update_config(self, **kwargs):
        """更新配置"""
        if 'voice_type' in kwargs:
            self._voice_type = kwargs['voice_type']
        if 'voice_speed' in kwargs:
            self._voice_speed = kwargs['voice_speed']
        if 'voice_pitch' in kwargs:
            self._voice_pitch = kwargs['voice_pitch']
        if 'prefer_online' in kwargs:
            self._prefer_online = kwargs['prefer_online']


class ASREngine:
    """语音识别引擎（统一接口）

    优先级: faster-whisper(本地) > vosk(轻量) > mock
    """

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        self.config = config or {}
        self._whisper_model = None
        self._vosk_model = None
        self._model_size = self.config.get('model_size', 'small')  # tiny/base/small/medium
        self._language = self.config.get('language', 'zh')  # zh/en/auto
        self._device = self.config.get('device', 'auto')  # auto/cpu/cuda

    @property
    def available_engines(self) -> List[str]:
        """可用引擎列表"""
        engines = []
        try:
            from faster_whisper import WhisperModel  # noqa
            engines.append('faster-whisper')
        except ImportError:
            pass
        try:
            from vosk import Model  # noqa
            engines.append('vosk')
        except ImportError:
            pass
        engines.append('mock')
        return engines

    @property
    def current_engine(self) -> str:
        """当前使用的引擎"""
        engines = self.available_engines
        if 'faster-whisper' in engines:
            return 'faster-whisper'
        if 'vosk' in engines:
            return 'vosk'
        return 'mock'

    def _get_whisper_model(self):
        """获取faster-whisper模型（懒加载）"""
        if self._whisper_model is None:
            from faster_whisper import WhisperModel

            model_size = self._model_size
            device = self._device
            compute_type = 'int8'  # 默认用INT8量化，节省内存

            if device == 'auto':
                # 自动检测
                try:
                    import torch
                    if torch.cuda.is_available():
                        device = 'cuda'
                        compute_type = 'float16'
                    else:
                        device = 'cpu'
                except ImportError:
                    device = 'cpu'

            print(f"[ASR] 加载 faster-whisper 模型: {model_size} ({device}/{compute_type})")
            self._whisper_model = WhisperModel(
                model_size,
                device=device,
                compute_type=compute_type,
            )
        return self._whisper_model

    def transcribe(self, audio_path: str, language: Optional[str] = None) -> Dict[str, Any]:
        """语音转文本

        Args:
            audio_path: 音频文件路径
            language: 语言代码（zh/en/None=自动检测）

        Returns:
            {
                'success': bool,
                'engine': str,
                'text': str,
                'language': str,
                'duration': float,
                'segments': [...],
            }
        """
        if not os.path.exists(audio_path):
            return {'success': False, 'error': f'音频文件不存在: {audio_path}', 'engine': self.current_engine}

        lang = language or self._language
        engine = self.current_engine

        # 尝试 faster-whisper
        if engine == 'faster-whisper':
            try:
                return self._transcribe_whisper(audio_path, lang)
            except Exception as e:
                print(f"[ASR] faster-whisper 失败，降级: {e}")
                engine = 'vosk' if 'vosk' in self.available_engines else 'mock'

        # 尝试 vosk
        if engine == 'vosk':
            try:
                return self._transcribe_vosk(audio_path, lang)
            except Exception as e:
                print(f"[ASR] vosk 失败，降级到mock: {e}")
                engine = 'mock'

        # Mock: 返回模拟结果
        return {
            'success': True,
            'engine': 'mock',
            'text': '（语音识别功能需要安装 faster-whisper 或 vosk）',
            'language': lang or 'zh',
            'duration': 0,
            'segments': [],
            'note': 'Mock模式：请安装 faster-whisper 或 vosk 以启用语音识别',
        }

    def _transcribe_whisper(self, audio_path: str, language: Optional[str]) -> Dict[str, Any]:
        """使用 faster-whisper 识别"""
        model = self._get_whisper_model()

        # 如果language是auto或None，不传language参数让模型自动检测
        transcribe_kwargs = {}
        if language and language != 'auto':
            transcribe_kwargs['language'] = language

        segments, info = model.transcribe(audio_path, beam_size=5, **transcribe_kwargs)

        text_parts = []
        segment_list = []
        for segment in segments:
            text_parts.append(segment.text)
            segment_list.append({
                'start': segment.start,
                'end': segment.end,
                'text': segment.text,
                'confidence': segment.avg_logprob,
            })

        full_text = ''.join(text_parts).strip()

        return {
            'success': True,
            'engine': 'faster-whisper',
            'text': full_text,
            'language': info.language,
            'duration': info.duration,
            'segments': segment_list,
            'model': self._model_size,
        }

    def _transcribe_vosk(self, audio_path: str, language: Optional[str]) -> Dict[str, Any]:
        """使用 vosk 识别（轻量离线）"""
        import wave
        import json
        from vosk import Model, KaldiRecognizer

        # 检查模型路径
        model_path = self.config.get('vosk_model_path', '')
        if not model_path or not os.path.exists(model_path):
            raise ValueError(f'Vosk模型路径未配置或不存在: {model_path}')

        if self._vosk_model is None:
            self._vosk_model = Model(model_path)

        # 读取WAV文件（vosk需要16kHz单声道PCM）
        wf = wave.open(audio_path, "rb")
        if wf.getnchannels() != 1 or wf.getsampwidth() != 2 or wf.getcomptype() != "NONE":
            # 需要先转换格式
            raise ValueError("Vosk需要16kHz单声道16bit WAV格式音频，请先转换")

        rec = KaldiRecognizer(self._vosk_model, wf.getframerate())

        text_parts = []
        while True:
            data = wf.readframes(4000)
            if len(data) == 0:
                break
            if rec.AcceptWaveform(data):
                result = json.loads(rec.Result())
                if result.get('text'):
                    text_parts.append(result['text'])

        final_result = json.loads(rec.FinalResult())
        if final_result.get('text'):
            text_parts.append(final_result['text'])

        wf.close()

        full_text = ''.join(text_parts).strip()

        return {
            'success': True,
            'engine': 'vosk',
            'text': full_text,
            'language': language or 'zh',
            'duration': 0,
            'segments': [],
        }


class AudioUtils:
    """音频工具类"""

    @staticmethod
    def convert_format(input_path: str, output_path: str,
                       sample_rate: int = 16000, channels: int = 1) -> bool:
        """转换音频格式（需要ffmpeg）

        Args:
            input_path: 输入文件路径
            output_path: 输出文件路径
            sample_rate: 采样率（默认16kHz，适合ASR）
            channels: 声道数（默认单声道）

        Returns:
            是否成功
        """
        try:
            from pydub import AudioSegment
        except ImportError:
            print("[Audio] pydub 未安装，无法转换格式")
            return False

        try:
            audio = AudioSegment.from_file(input_path)
            audio = audio.set_frame_rate(sample_rate).set_channels(channels)
            audio.export(output_path, format='wav')
            return True
        except Exception as e:
            print(f"[Audio] 格式转换失败: {e}")
            return False

    @staticmethod
    def get_duration(audio_path: str) -> float:
        """获取音频时长（秒）"""
        try:
            from pydub import AudioSegment
            audio = AudioSegment.from_file(audio_path)
            return len(audio) / 1000.0
        except Exception:
            return 0.0

    @staticmethod
    def webm_to_wav(webm_path: str, wav_path: str) -> bool:
        """WebM转WAV（前端MediaRecorder常用格式转换）"""
        return AudioUtils.convert_format(webm_path, wav_path, 16000, 1)


# 全局单例
_tts_engine = None
_asr_engine = None


def get_tts_engine(config: Optional[Dict[str, Any]] = None) -> TTSEngine:
    """获取TTS引擎单例"""
    global _tts_engine
    if _tts_engine is None or config:
        _tts_engine = TTSEngine(config)
    return _tts_engine


def get_asr_engine(config: Optional[Dict[str, Any]] = None) -> ASREngine:
    """获取ASR引擎单例"""
    global _asr_engine
    if _asr_engine is None or config:
        _asr_engine = ASREngine(config)
    return _asr_engine
