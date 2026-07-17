"""
云汐系统 - 语音引擎模块
- TTS: 文本转语音（edge-tts在线 + 浏览器SpeechSynthesis离线兜底）
- ASR: 语音转文本（faster-whisper本地离线 + vosk轻量备选）
- VAD: 语音活动检测（silero-vad + 能量阈值兜底）
- 唤醒词检测: VAD检测语音片段 → faster-whisper识别 → 关键词匹配
- 流式识别: 支持音频流分片识别
- 统一接口，支持引擎切换和自动降级
"""

import os
import io
import time
import asyncio
import tempfile
import logging
import numpy as np
from typing import Optional, Dict, Any, List, Tuple, Generator, AsyncGenerator
from pathlib import Path

logger = logging.getLogger(__name__)

class TTSEngine:
    """语音合成引擎（统一接口）

    优先级: fish-speech(本地高质量) > edge-tts(在线) > pyttsx3(离线系统) > mock(文本返回)
    """

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        self.config = config or {}
        self._edge_tts = None
        self._pyttsx3_engine = None
        self._fish_engine = None  # Fish Speech 引擎实例（懒加载）
        self._fish_available = None  # Fish Speech 可用性缓存（None=未检测, True/False=已检测）
        self._cosyvoice_client = None  # CosyVoice 客户端（懒加载）
        self._cosyvoice_available = None  # CosyVoice 可用性缓存

        # 基础语音参数
        self._voice_type = self.config.get('voice_type', 'warm_female')
        self._voice_speed = self.config.get('voice_speed', 1.0)
        self._voice_pitch = self.config.get('voice_pitch', 1.0)
        self._prefer_online = self.config.get('prefer_online', True)

        # CosyVoice 配置（最高优先级，需显式开启）
        self._use_cosyvoice = self.config.get('use_cosyvoice', False)
        self._cosyvoice_api_url = self.config.get('cosyvoice_api_url', 'http://localhost:50000')
        self._cosyvoice_speaker_id = self.config.get('cosyvoice_speaker_id', 'yunxi_default')
        self._cosyvoice_reference_audio = self.config.get('cosyvoice_reference_audio', '')
        self._cosyvoice_reference_text = self.config.get('cosyvoice_reference_text', 
                                                        '希望你以后能够做的比我还好呦。')
        self._cosyvoice_emotion = self.config.get('cosyvoice_emotion', 'warm')
        self._cosyvoice_method = self.config.get('cosyvoice_method', 'instruct')  # zero_shot / instruct / cross_lingual

        # Fish Speech 配置（懒加载，use_fish_speech=True 时才尝试加载）
        self._use_fish_speech = self.config.get('use_fish_speech', False)
        self._fish_device = self.config.get('fish_device', 'auto')  # cuda / cpu / auto
        self._fish_reference_audio = self.config.get('fish_reference_audio', '')  # 音色克隆参考音频
        self._fish_temperature = self.config.get('fish_temperature', 0.66)  # 温度参数，默认0.66
        self._fish_model_path = self.config.get('fish_model_path', '')  # Fish Speech 模型路径

        # 语音类型映射（14个中文音色 + 向后兼容的可爱童声）
        # 分类：普通话女声、普通话男声、方言、港澳台
        self._voice_map = {
            # ---------- 普通话女声 ----------
            'warm_female': {
                'edge_voice': 'zh-CN-XiaoxiaoNeural',
                'label': '温暖女声',
                'subtitle': '晓晓',
                'category': '普通话女声',
            },
            'clear_female': {
                'edge_voice': 'zh-CN-XiaoyiNeural',
                'label': '清澈女声',
                'subtitle': '晓伊',
                'category': '普通话女声',
            },
            # ---------- 普通话男声 ----------
            'gentle_male': {
                'edge_voice': 'zh-CN-YunxiNeural',
                'label': '温柔男声',
                'subtitle': '云希',
                'category': '普通话男声',
            },
            'steady_male': {
                'edge_voice': 'zh-CN-YunjianNeural',
                'label': '沉稳男声',
                'subtitle': '云健',
                'category': '普通话男声',
            },
            'young_male': {
                'edge_voice': 'zh-CN-YunxiaNeural',
                'label': '青年男声',
                'subtitle': '云夏',
                'category': '普通话男声',
            },
            'robot_male': {
                'edge_voice': 'zh-CN-YunyangNeural',
                'label': '机械男声',
                'subtitle': '云扬',
                'category': '普通话男声',
            },
            # ---------- 方言 ----------
            'northeast_female': {
                'edge_voice': 'zh-CN-liaoning-XiaobeiNeural',
                'label': '东北女声',
                'subtitle': '小北-东北话',
                'category': '方言',
            },
            'shaanxi_female': {
                'edge_voice': 'zh-CN-shaanxi-XiaoniNeural',
                'label': '陕西女声',
                'subtitle': '晓妮-陕西话',
                'category': '方言',
            },
            # ---------- 港澳台 - 粤语 ----------
            'hk_female1': {
                'edge_voice': 'zh-HK-HiuGaaiNeural',
                'label': '粤语女声1',
                'subtitle': '曉佳',
                'category': '港澳台-粤语',
            },
            'hk_female2': {
                'edge_voice': 'zh-HK-HiuMaanNeural',
                'label': '粤语女声2',
                'subtitle': '曉曼',
                'category': '港澳台-粤语',
            },
            'hk_male': {
                'edge_voice': 'zh-HK-WanLungNeural',
                'label': '粤语男声',
                'subtitle': '雲龍',
                'category': '港澳台-粤语',
            },
            # ---------- 港澳台 - 台湾 ----------
            'tw_female1': {
                'edge_voice': 'zh-TW-HsiaoChenNeural',
                'label': '台湾女声1',
                'subtitle': '曉臻',
                'category': '港澳台-台湾',
            },
            'tw_female2': {
                'edge_voice': 'zh-TW-HsiaoYuNeural',
                'label': '台湾女声2',
                'subtitle': '曉雨',
                'category': '港澳台-台湾',
            },
            'tw_male': {
                'edge_voice': 'zh-TW-YunJheNeural',
                'label': '台湾男声',
                'subtitle': '雲哲',
                'category': '港澳台-台湾',
            },
            # ---------- 向后兼容：可爱童声 ----------
            'cute_child': {
                'edge_voice': 'zh-CN-XiaoyouNeural',
                'label': '可爱童声',
                'subtitle': '晓悠',
                'category': '童声',
            },
        }

        # 向后兼容：robot 别名（映射到 robot_male）
        self._voice_map['robot'] = self._voice_map['robot_male']

    # ============================================================
    # 引擎可用性检测
    # ============================================================

    @property
    def available_engines(self) -> List[str]:
        """可用引擎列表

        按优先级从高到低排列：
        cosyvoice > fish-speech > edge-tts > pyttsx3 > mock

        cosyvoice 需显式配置 use_cosyvoice=True 且服务可用时出现
        fish-speech 仅在配置 use_fish_speech=True 且导入成功时出现
        """
        engines = []

        # CosyVoice（最高优先级，需显式开启且服务可用）
        if self._use_cosyvoice and self._check_cosyvoice_available():
            engines.append('cosyvoice')

        # Fish Speech（需显式开启）
        if self._use_fish_speech:
            try:
                from fish_speech.inference_engine import TTSInferenceEngine  # noqa
                engines.append('fish-speech')
            except ImportError:
                pass
            except Exception:
                # 其他错误（如依赖缺失）也视为不可用
                pass

        # edge-tts
        try:
            import edge_tts  # noqa
            engines.append('edge-tts')
        except ImportError:
            pass

        # pyttsx3
        try:
            import pyttsx3  # noqa
            engines.append('pyttsx3')
        except ImportError:
            pass

        # mock（始终可用）
        engines.append('mock')
        return engines

    @property
    def current_engine(self) -> str:
        """当前使用的引擎（按优先级自动选择）"""
        engines = self.available_engines

        # 最高优先级：CosyVoice（需配置启用且服务可用）
        if 'cosyvoice' in engines and self._cosyvoice_available is not False:
            # 检查是否配置了说话人或参考音频
            has_speaker = bool(self._cosyvoice_speaker_id)
            has_ref = bool(self._cosyvoice_reference_audio and 
                          os.path.exists(self._cosyvoice_reference_audio))
            if has_speaker or has_ref:
                return 'cosyvoice'

        # 第二优先级：fish-speech（需配置启用且可用）
        if 'fish-speech' in engines and self._fish_available is not False:
            # 需要检查参考音频是否配置
            if self._fish_reference_audio and os.path.exists(self._fish_reference_audio):
                return 'fish-speech'

        # 第三优先级：edge-tts（在线）
        if self._prefer_online and 'edge-tts' in engines:
            return 'edge-tts'

        # 第四优先级：pyttsx3（离线系统TTS）
        if 'pyttsx3' in engines:
            return 'pyttsx3'

        # 最低优先级：mock
        return 'mock'

    # ============================================================
    # 语音选项
    # ============================================================

    def get_voice_options(self) -> List[Dict[str, Any]]:
        """获取可用语音选项列表

        返回所有音色，包含分类信息，并标记哪些音色支持 fish-speech 克隆和 CosyVoice。

        Returns:
            列表项格式：
            {
                'id': str,           # 音色ID（用于 voice_type）
                'name': str,         # 音色名称（如 "温暖女声"）
                'subtitle': str,     # 副标题（如 "晓晓"）
                'category': str,     # 分类（普通话女声/普通话男声/方言/港澳台-粤语/...）
                'engine': str,       # 当前引擎
                'supports_fish_clone': bool,  # 是否支持 fish-speech 音色克隆
                'supports_cosyvoice': bool,   # 是否支持 CosyVoice 音色克隆
            }
        """
        fish_clone_available = (
            'fish-speech' in self.available_engines
            and self._fish_reference_audio
            and os.path.exists(self._fish_reference_audio)
        )
        cosyvoice_available = 'cosyvoice' in self.available_engines

        options = []
        for key, info in self._voice_map.items():
            # 跳过 robot 别名（避免重复，robot_male 已经在列表中）
            if key == 'robot':
                continue
            options.append({
                'id': key,
                'name': info['label'],
                'subtitle': info.get('subtitle', ''),
                'category': info.get('category', '其他'),
                'engine': self.current_engine,
                'supports_fish_clone': fish_clone_available,
                'supports_cosyvoice': cosyvoice_available,
            })
        return options

    def get_voice_categories(self) -> Dict[str, List[Dict[str, Any]]]:
        """按分类组织的语音选项（便于前端分组展示）

        Returns:
            {分类名: [语音选项列表]}
        """
        options = self.get_voice_options()
        categories: Dict[str, List[Dict[str, Any]]] = {}
        for opt in options:
            cat = opt['category']
            if cat not in categories:
                categories[cat] = []
            categories[cat].append(opt)
        return categories

    # ============================================================
    # 内部工具方法
    # ============================================================

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

    # ============================================================
    # Fish Speech 引擎（懒加载）
    # ============================================================

    def _get_fish_engine(self):
        """获取 Fish Speech 推理引擎（懒加载模式）

        首次调用时尝试加载模型，加载失败则标记为不可用并返回 None。
        后续调用直接返回缓存结果，避免重复尝试。

        Returns:
            TTSInferenceEngine 实例，不可用则返回 None
        """
        # 已有缓存结果
        if self._fish_engine is not None:
            return self._fish_engine
        if self._fish_available is False:
            return None

        # 未开启 fish-speech
        if not self._use_fish_speech:
            self._fish_available = False
            return None

        try:
            from fish_speech.inference_engine import TTSInferenceEngine
        except ImportError as e:
            print(f"[TTS] Fish Speech 未安装，跳过加载: {e}")
            self._fish_available = False
            return None
        except Exception as e:
            print(f"[TTS] Fish Speech 导入失败: {e}")
            self._fish_available = False
            return None

        # 检查参考音频（音色克隆必需）
        reference_audio = self._fish_reference_audio
        if not reference_audio:
            print("[TTS] Fish Speech 未配置参考音频 (fish_reference_audio)，无法使用音色克隆")
            self._fish_available = False
            return None
        if not os.path.exists(reference_audio):
            print(f"[TTS] Fish Speech 参考音频不存在: {reference_audio}")
            self._fish_available = False
            return None

        # 确定设备
        device = self._fish_device
        if device == 'auto':
            try:
                import torch
                if torch.cuda.is_available():
                    device = 'cuda'
                else:
                    device = 'cpu'
            except ImportError:
                device = 'cpu'

        try:
            print(f"[TTS] 正在加载 Fish Speech 模型 (device={device}) ...")

            # 构建推理引擎（fish-speech 0.1.0 API）
            # 注：fish-speech API 较底层，这里使用标准参数封装
            init_kwargs = {}
            if self._fish_model_path:
                init_kwargs['model_path'] = self._fish_model_path

            self._fish_engine = TTSInferenceEngine(
                device=device,
                **init_kwargs,
            )
            self._fish_available = True
            print(f"[TTS] Fish Speech 模型加载成功 (device={device})")
            return self._fish_engine

        except Exception as e:
            print(f"[TTS] Fish Speech 模型加载失败，将降级到 edge-tts: {e}")
            self._fish_engine = None
            self._fish_available = False
            return None

    async def _synthesize_fish_speech(self, text: str, output_path: Optional[str] = None) -> Dict[str, Any]:
        """使用 Fish Speech 合成语音（本地高质量TTS + 音色克隆）

        Fish Speech 为同步推理，内部放入线程池执行避免阻塞事件循环。

        Args:
            text: 要合成的文本
            output_path: 输出文件路径（可选）

        Returns:
            标准合成结果字典

        Raises:
            RuntimeError: 引擎不可用时抛出，触发降级逻辑
        """
        engine = self._get_fish_engine()
        if engine is None:
            raise RuntimeError("Fish Speech 引擎不可用")

        if output_path is None:
            tmp_file = tempfile.NamedTemporaryFile(suffix='.wav', delete=False)
            output_path = tmp_file.name
            tmp_file.close()

        reference_audio = self._fish_reference_audio

        def _do_inference():
            """在独立线程中执行推理"""
            # 注意：fish-speech 0.1.0 API 较底层，以下调用基于常见推理接口封装
            # 实际参数可能需要根据 fish-speech 版本调整
            inference_kwargs = {
                'text': text,
                'reference_audio': reference_audio,
                'temperature': self._fish_temperature,
                'output_path': output_path,
            }

            # 尝试调用 inference 方法（常见命名）
            if hasattr(engine, 'inference'):
                return engine.inference(**inference_kwargs)
            # 备选：synthesize 方法
            elif hasattr(engine, 'synthesize'):
                return engine.synthesize(**inference_kwargs)
            else:
                raise RuntimeError(
                    f"Fish Speech 引擎未找到 inference/synthesize 方法，"
                    f"可用方法: {[m for m in dir(engine) if not m.startswith('_')]}"
                )

        try:
            # 异步执行推理（避免阻塞事件循环）
            loop = asyncio.get_event_loop()
            result = await loop.run_in_executor(None, _do_inference)

            # 估算时长（约每秒4-5个中文字）
            duration = len(text) / 4.5

            return {
                'success': True,
                'engine': 'fish-speech',
                'audio_path': output_path,
                'audio_format': 'wav',
                'duration': duration,
                'text': text,
                'voice': self._voice_type,
                'reference_audio': reference_audio,
                'temperature': self._fish_temperature,
                'raw_result': result,
            }

        except Exception as e:
            print(f"[TTS] Fish Speech 推理失败: {e}")
            # 清理可能生成的不完整文件
            if output_path and os.path.exists(output_path):
                try:
                    os.unlink(output_path)
                except Exception as e:
                    # 清理失败不影响错误处理流程
                    logger.debug("清理 Fish Speech 输出文件失败: %s", e)
            raise

    # ============================================================
    # CosyVoice 引擎（HTTP 服务化调用）
    # ============================================================

    def _check_cosyvoice_available(self) -> bool:
        """检查 CosyVoice 服务是否可用（带缓存）"""
        if self._cosyvoice_available is not None:
            return self._cosyvoice_available
        
        try:
            from shared.cosyvoice_client import CosyVoiceClient, CosyVoiceConfig
            cfg = CosyVoiceConfig(
                api_url=self._cosyvoice_api_url,
                default_speaker_id=self._cosyvoice_speaker_id,
                default_reference_audio=self._cosyvoice_reference_audio,
                default_reference_text=self._cosyvoice_reference_text,
            )
            client = CosyVoiceClient(cfg)
            self._cosyvoice_available = client.is_available
            if self._cosyvoice_available:
                self._cosyvoice_client = client
        except Exception:
            self._cosyvoice_available = False
        
        return self._cosyvoice_available

    def _get_cosyvoice_client(self):
        """获取 CosyVoice 客户端（懒加载）"""
        if self._cosyvoice_client is None:
            if not self._check_cosyvoice_available():
                return None
        return self._cosyvoice_client

    async def _synthesize_cosyvoice(self, text: str, output_path: Optional[str] = None,
                                    emotion: Optional[str] = None,
                                    instruction: Optional[str] = None) -> Dict[str, Any]:
        """使用 CosyVoice 合成语音（零样本克隆 + 指令控制）

        CosyVoice 为 HTTP 服务调用，支持零样本语音克隆和自然语言指令控制。
        支持情感、语速、方言等细粒度控制。

        Args:
            text: 要合成的文本
            output_path: 输出文件路径（可选）
            emotion: 情感覆盖（warm/happy/sad/calm/excited 等）
            instruction: 自定义指令（优先于 emotion）

        Returns:
            标准合成结果字典

        Raises:
            RuntimeError: 引擎不可用时抛出，触发降级逻辑
        """
        client = self._get_cosyvoice_client()
        if client is None:
            raise RuntimeError("CosyVoice 服务不可用")

        if output_path is None:
            tmp_file = tempfile.NamedTemporaryFile(suffix='.wav', delete=False)
            output_path = tmp_file.name
            tmp_file.close()

        method = self._cosyvoice_method
        ref_audio = self._cosyvoice_reference_audio
        ref_text = self._cosyvoice_reference_text
        speaker_id = self._cosyvoice_speaker_id

        try:
            if method == 'instruct' or instruction or emotion:
                # 指令控制模式（支持情感/语速/方言等）
                if instruction is None:
                    # 根据配置构建指令
                    emotion_val = emotion or self._cosyvoice_emotion
                    # 语速映射
                    speed_val = 'normal'
                    if self._voice_speed < 0.8:
                        speed_val = 'slow'
                    elif self._voice_speed > 1.2:
                        speed_val = 'fast'
                    
                    instruction = client.build_instruction(
                        emotion=emotion_val,
                        speed=speed_val,
                    )
                
                result = await client.synthesize_instruct_async(
                    text=text,
                    instruction=instruction,
                    reference_audio_path=ref_audio if ref_audio and os.path.exists(ref_audio) else None,
                    reference_text=ref_text,
                    speaker_id=speaker_id,
                    output_path=output_path,
                )
            elif method == 'cross_lingual':
                # 跨语言模式
                result = await client.synthesize_cross_lingual_async(
                    text=text,
                    reference_audio_path=ref_audio if ref_audio and os.path.exists(ref_audio) else None,
                    speaker_id=speaker_id,
                    output_path=output_path,
                )
            else:
                # 零样本克隆模式（纯音色复刻，无风格控制）
                result = await client.synthesize_zero_shot_async(
                    text=text,
                    reference_audio_path=ref_audio if ref_audio and os.path.exists(ref_audio) else None,
                    reference_text=ref_text,
                    speaker_id=speaker_id,
                    output_path=output_path,
                )

            if not result.get('success'):
                raise RuntimeError(result.get('error', 'CosyVoice 合成失败'))

            # 补充返回字段
            result['voice'] = self._voice_type
            result['reference_audio'] = ref_audio
            result['speaker_id'] = speaker_id
            return result

        except Exception as e:
            print(f"[TTS] CosyVoice 推理失败: {e}")
            # 清理可能生成的不完整文件
            if output_path and os.path.exists(output_path):
                try:
                    os.unlink(output_path)
                except Exception as e:
                    # 清理失败不影响降级逻辑
                    logger.debug("清理 CosyVoice 输出文件失败: %s", e)
            # 标记为不可用，后续请求直接降级
            self._cosyvoice_available = False
            raise

    # ============================================================
    # 统一合成入口
    # ============================================================

    async def synthesize(self, text: str, output_path: Optional[str] = None,
                         emotion: Optional[str] = None,
                         instruction: Optional[str] = None) -> Dict[str, Any]:
        """文本转语音

        按优先级依次尝试各引擎，失败则自动降级。
        优先级: cosyvoice > fish-speech > edge-tts > pyttsx3 > mock

        Args:
            text: 要合成的文本
            output_path: 输出文件路径（可选，不指定则返回临时文件路径）
            emotion: 情感参数（仅 CosyVoice 支持，如 warm/happy/sad/calm 等）
            instruction: 自定义指令（仅 CosyVoice 支持，优先于 emotion）

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

        # 获取可用引擎列表（按优先级排序）
        engines = self.available_engines

        # ---------- 第一级：CosyVoice（本地高质量 + 音色克隆 + 情感控制） ----------
        if 'cosyvoice' in engines and self._use_cosyvoice:
            try:
                return await self._synthesize_cosyvoice(
                    text, output_path, 
                    emotion=emotion,
                    instruction=instruction,
                )
            except Exception as e:
                print(f"[TTS] CosyVoice 失败，降级到 fish-speech/edge-tts: {e}")
                # CosyVoice 失败后标记为不可用，避免后续重复尝试
                self._cosyvoice_available = False
                # 继续降级到下一级

        # ---------- 第二级：Fish Speech（本地高质量） ----------
        if 'fish-speech' in engines and self._use_fish_speech:
            try:
                return await self._synthesize_fish_speech(text, output_path)
            except Exception as e:
                print(f"[TTS] fish-speech 失败，降级到 edge-tts: {e}")
                # fish-speech 失败后标记为不可用，避免后续重复尝试
                self._fish_available = False
                # 继续降级到下一级

        # ---------- 第二级：edge-tts（在线） ----------
        if 'edge-tts' in engines:
            try:
                return await self._synthesize_edge_tts(text, output_path)
            except Exception as e:
                print(f"[TTS] edge-tts 失败，降级: {e}")
                # 继续降级

        # ---------- 第三级：pyttsx3（离线系统TTS） ----------
        if 'pyttsx3' in engines:
            try:
                return self._synthesize_pyttsx3(text, output_path)
            except Exception as e:
                print(f"[TTS] pyttsx3 失败，降级到mock: {e}")
                # 继续降级

        # ---------- 最低级：Mock（只返回文本信息） ----------
        return {
            'success': True,
            'engine': 'mock',
            'audio_path': None,
            'audio_format': None,
            'duration': len(text) * 0.2,  # 估算时长
            'text': text,
            'note': 'Mock模式：无音频输出，仅返回文本',
        }

    # ============================================================
    # edge-tts 引擎
    # ============================================================

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

    # ============================================================
    # pyttsx3 引擎（离线）
    # ============================================================

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

    # ============================================================
    # 直接播放
    # ============================================================

    def speak(self, text: str) -> bool:
        """直接播放语音（不保存文件）

        注意：fish-speech 和 edge-tts 需要先生成文件再播放，
        这里仅支持 pyttsx3 的直接播放。
        """
        engine = self.current_engine

        # fish-speech 和 edge-tts 需要生成文件后播放，这里不实现
        # 前端会通过音频元素播放

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

        return False

    # ============================================================
    # 配置更新
    # ============================================================

    def update_config(self, **kwargs):
        """更新配置

        支持的配置项：
        - voice_type: 音色ID
        - voice_speed: 语速倍率
        - voice_pitch: 音调倍率
        - prefer_online: 是否优先使用在线引擎
        - use_fish_speech: 是否启用 Fish Speech
        - fish_device: Fish Speech 设备 (cuda/cpu/auto)
        - fish_reference_audio: Fish Speech 参考音频路径
        - fish_temperature: Fish Speech 温度参数
        - fish_model_path: Fish Speech 模型路径
        - use_cosyvoice: 是否启用 CosyVoice
        - cosyvoice_api_url: CosyVoice 服务地址
        - cosyvoice_speaker_id: CosyVoice 默认说话人ID
        - cosyvoice_reference_audio: CosyVoice 参考音频路径
        - cosyvoice_reference_text: CosyVoice 参考音频文本
        - cosyvoice_emotion: CosyVoice 默认情感
        - cosyvoice_method: CosyVoice 合成方法 (zero_shot/instruct/cross_lingual)
        """
        # 基础语音参数
        if 'voice_type' in kwargs:
            self._voice_type = kwargs['voice_type']
        if 'voice_speed' in kwargs:
            self._voice_speed = kwargs['voice_speed']
        if 'voice_pitch' in kwargs:
            self._voice_pitch = kwargs['voice_pitch']
        if 'prefer_online' in kwargs:
            self._prefer_online = kwargs['prefer_online']

        # Fish Speech 参数
        fish_config_changed = False
        if 'use_fish_speech' in kwargs:
            self._use_fish_speech = kwargs['use_fish_speech']
            fish_config_changed = True
        if 'fish_device' in kwargs:
            self._fish_device = kwargs['fish_device']
            fish_config_changed = True
        if 'fish_reference_audio' in kwargs:
            self._fish_reference_audio = kwargs['fish_reference_audio']
            fish_config_changed = True
        if 'fish_temperature' in kwargs:
            self._fish_temperature = kwargs['fish_temperature']
        if 'fish_model_path' in kwargs:
            self._fish_model_path = kwargs['fish_model_path']
            fish_config_changed = True

        # Fish Speech 配置变更时重置缓存，下次调用重新检测
        if fish_config_changed:
            self._fish_engine = None
            self._fish_available = None

        # CosyVoice 参数
        cosyvoice_config_changed = False
        if 'use_cosyvoice' in kwargs:
            self._use_cosyvoice = kwargs['use_cosyvoice']
            cosyvoice_config_changed = True
        if 'cosyvoice_api_url' in kwargs:
            self._cosyvoice_api_url = kwargs['cosyvoice_api_url']
            cosyvoice_config_changed = True
        if 'cosyvoice_speaker_id' in kwargs:
            self._cosyvoice_speaker_id = kwargs['cosyvoice_speaker_id']
            cosyvoice_config_changed = True
        if 'cosyvoice_reference_audio' in kwargs:
            self._cosyvoice_reference_audio = kwargs['cosyvoice_reference_audio']
            cosyvoice_config_changed = True
        if 'cosyvoice_reference_text' in kwargs:
            self._cosyvoice_reference_text = kwargs['cosyvoice_reference_text']
            cosyvoice_config_changed = True
        if 'cosyvoice_emotion' in kwargs:
            self._cosyvoice_emotion = kwargs['cosyvoice_emotion']
        if 'cosyvoice_method' in kwargs:
            self._cosyvoice_method = kwargs['cosyvoice_method']
            cosyvoice_config_changed = True

        # CosyVoice 配置变更时重置缓存，下次调用重新检测
        if cosyvoice_config_changed:
            self._cosyvoice_client = None
            self._cosyvoice_available = None


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

    # ============================================================
    # VAD 语音活动检测
    # ============================================================

    @property
    def available_vad_engines(self) -> List[str]:
        """可用VAD引擎列表
        优先级: silero-vad > webrtcvad > mock(能量阈值)
        """
        engines = []
        try:
            import torch  # noqa
            import torchaudio  # noqa
            # silero-vad 依赖 torch 和 torchaudio
            engines.append('silero-vad')
        except ImportError:
            pass
        try:
            import webrtcvad  # noqa
            engines.append('webrtcvad')
        except ImportError:
            pass
        engines.append('mock')  # 能量阈值兜底
        return engines

    @property
    def current_vad_engine(self) -> str:
        """当前使用的VAD引擎"""
        engines = self.available_vad_engines
        if 'silero-vad' in engines:
            return 'silero-vad'
        if 'webrtcvad' in engines:
            return 'webrtcvad'
        return 'mock'

    def _get_silero_vad_model(self):
        """获取silero-vad模型（懒加载）"""
        if not hasattr(self, '_silero_model') or self._silero_model is None:
            import torch
            model, utils = torch.hub.load(
                repo_or_dir='snakers4/silero-vad',
                model='silero_vad',
                force_reload=False,
                onnx=False,
            )
            self._silero_model = model
            self._silero_utils = utils
        return self._silero_model

    def vad_detect(self, audio_path: str, threshold: float = 0.5,
                   min_speech_duration: float = 0.3,
                   max_silence_duration: float = 0.5) -> Dict[str, Any]:
        """VAD语音活动检测

        检测音频中的语音片段，返回语音起止时间和语音片段列表。

        Args:
            audio_path: 音频文件路径（支持WAV/MP3等常见格式）
            threshold: 语音置信度阈值（0-1，越高越严格）
            min_speech_duration: 最小语音时长（秒），短于此值的语音会被过滤
            max_silence_duration: 最大静音间隔（秒），间隔小于此值的相邻语音会被合并

        Returns:
            {
                'success': bool,
                'engine': str,
                'has_speech': bool,
                'speech_segments': [{'start': float, 'end': float, 'confidence': float}],
                'total_speech_duration': float,
                'sample_rate': int,
            }
        """
        if not os.path.exists(audio_path):
            return {
                'success': False,
                'error': f'音频文件不存在: {audio_path}',
                'engine': self.current_vad_engine,
                'has_speech': False,
                'speech_segments': [],
                'total_speech_duration': 0,
            }

        engine = self.current_vad_engine

        # 尝试 silero-vad
        if engine == 'silero-vad':
            try:
                return self._vad_silero(audio_path, threshold, min_speech_duration, max_silence_duration)
            except Exception as e:
                print(f"[VAD] silero-vad 失败，降级: {e}")
                engine = 'webrtcvad' if 'webrtcvad' in self.available_vad_engines else 'mock'

        # 尝试 webrtcvad
        if engine == 'webrtcvad':
            try:
                return self._vad_webrtc(audio_path, threshold, min_speech_duration, max_silence_duration)
            except Exception as e:
                print(f"[VAD] webrtcvad 失败，降级到mock: {e}")
                engine = 'mock'

        # Mock: 能量阈值法兜底
        return self._vad_mock(audio_path, min_speech_duration, max_silence_duration)

    def _vad_silero(self, audio_path: str, threshold: float,
                    min_speech_duration: float, max_silence_duration: float) -> Dict[str, Any]:
        """使用silero-vad进行语音活动检测"""
        import torch
        import torchaudio

        model = self._get_silero_vad_model()
        get_speech_timestamps = self._silero_utils[0]

        # 加载音频（silero-vad要求16kHz单声道）
        wav, sr = torchaudio.load(audio_path)
        if sr != 16000:
            resampler = torchaudio.transforms.Resample(sr, 16000)
            wav = resampler(wav)
            sr = 16000
        if wav.shape[0] > 1:
            wav = torch.mean(wav, dim=0, keepdim=True)

        # 获取语音时间戳
        speech_timestamps = get_speech_timestamps(
            wav.squeeze(),
            model,
            threshold=threshold,
            sampling_rate=sr,
            min_speech_duration_ms=int(min_speech_duration * 1000),
            max_speech_duration_s=30,
            min_silence_duration_ms=int(max_silence_duration * 1000),
            window_size_samples=512,
        )

        segments = []
        total_duration = 0.0
        for ts in speech_timestamps:
            start = ts['start'] / sr
            end = ts['end'] / sr
            segments.append({
                'start': round(start, 3),
                'end': round(end, 3),
                'confidence': 1.0,  # silero返回的是二值判断
            })
            total_duration += (end - start)

        return {
            'success': True,
            'engine': 'silero-vad',
            'has_speech': len(segments) > 0,
            'speech_segments': segments,
            'total_speech_duration': round(total_duration, 3),
            'sample_rate': sr,
        }

    def _vad_webrtcvad(self, audio_path: str, threshold: float,
                       min_speech_duration: float, max_silence_duration: float) -> Dict[str, Any]:
        """使用webrtcvad进行语音活动检测"""
        import webrtcvad
        import wave

        # 读取WAV文件（webrtcvad要求16kHz/8kHz/32kHz/48kHz单声道16bit PCM）
        wf = wave.open(audio_path, 'rb')
        sample_rate = wf.getframerate()
        channels = wf.getnchannels()
        sample_width = wf.getsampwidth()

        if channels != 1 or sample_width != 2:
            wf.close()
            raise ValueError("webrtcvad需要单声道16bit WAV格式音频")

        # webrtcvad支持的采样率
        if sample_rate not in [8000, 16000, 32000, 48000]:
            wf.close()
            raise ValueError(f"webrtcvad不支持采样率 {sample_rate}Hz")

        # 选择 aggressiveness 模式 (0-3, 3最严格)
        vad_level = min(3, max(0, int(threshold * 3)))
        vad = webrtcvad.Vad(vad_level)

        # 30ms帧
        frame_duration = 0.03  # 秒
        frame_size = int(sample_rate * frame_duration)
        frame_bytes = frame_size * 2  # 16bit

        segments = []
        in_speech = False
        speech_start = 0
        silence_frames = 0
        max_silence_frames = int(max_silence_duration / frame_duration)
        min_speech_frames = int(min_speech_duration / frame_duration)
        current_speech_frames = 0
        total_frames = 0

        while True:
            data = wf.readframes(frame_size)
            if len(data) < frame_bytes:
                break
            total_frames += 1

            is_speech = vad.is_speech(data, sample_rate)

            if is_speech:
                if not in_speech:
                    # 语音开始
                    in_speech = True
                    speech_start = total_frames * frame_duration
                    current_speech_frames = 0
                current_speech_frames += 1
                silence_frames = 0
            else:
                if in_speech:
                    silence_frames += 1
                    current_speech_frames += 1
                    if silence_frames >= max_silence_frames:
                        # 语音结束
                        speech_end = (total_frames - silence_frames) * frame_duration
                        if current_speech_frames >= min_speech_frames:
                            segments.append({
                                'start': round(speech_start, 3),
                                'end': round(speech_end, 3),
                                'confidence': 0.8,
                            })
                        in_speech = False

        # 处理末尾语音
        if in_speech and current_speech_frames >= min_speech_frames:
            speech_end = total_frames * frame_duration
            segments.append({
                'start': round(speech_start, 3),
                'end': round(speech_end, 3),
                'confidence': 0.8,
            })

        wf.close()

        total_duration = sum(s['end'] - s['start'] for s in segments)

        return {
            'success': True,
            'engine': 'webrtcvad',
            'has_speech': len(segments) > 0,
            'speech_segments': segments,
            'total_speech_duration': round(total_duration, 3),
            'sample_rate': sample_rate,
        }

    def _vad_mock(self, audio_path: str, min_speech_duration: float,
                  max_silence_duration: float) -> Dict[str, Any]:
        """VAD Mock实现：基于能量阈值的语音活动检测

        当silero-vad和webrtcvad都不可用时，使用简单的能量阈值法作为兜底。
        计算音频帧的RMS能量，超过阈值则判定为语音。
        """
        try:
            import wave

            wf = wave.open(audio_path, 'rb')
            sample_rate = wf.getframerate()
            channels = wf.getnchannels()
            sample_width = wf.getsampwidth()
            n_frames = wf.getnframes()

            if sample_width != 2:
                wf.close()
                # 非16bit WAV，直接返回整段作为一个语音片段
                duration = n_frames / sample_rate if sample_rate > 0 else 0
                return {
                    'success': True,
                    'engine': 'mock',
                    'has_speech': duration > 0,
                    'speech_segments': [{'start': 0, 'end': duration, 'confidence': 0.5}] if duration > 0 else [],
                    'total_speech_duration': duration,
                    'sample_rate': sample_rate,
                    'note': 'Mock模式：基于能量阈值的VAD（精度较低）',
                }

            raw_data = wf.readframes(n_frames)
            wf.close()

            # 转换为numpy数组
            audio_np = np.frombuffer(raw_data, dtype=np.int16).astype(np.float32)
            if channels > 1:
                audio_np = audio_np.reshape(-1, channels).mean(axis=1)

            # 归一化到 [-1, 1]
            audio_np /= 32768.0

            # 帧参数
            frame_duration = 0.03  # 30ms
            frame_size = int(sample_rate * frame_duration)
            n_total_frames = len(audio_np) // frame_size

            if n_total_frames == 0:
                return {
                    'success': True,
                    'engine': 'mock',
                    'has_speech': False,
                    'speech_segments': [],
                    'total_speech_duration': 0,
                    'sample_rate': sample_rate,
                    'note': 'Mock模式：音频太短',
                }

            # 计算每帧的RMS能量
            rms_values = []
            for i in range(n_total_frames):
                frame = audio_np[i * frame_size:(i + 1) * frame_size]
                rms = np.sqrt(np.mean(frame ** 2))
                rms_values.append(rms)

            # 自适应阈值：使用均值 + 0.5倍标准差作为阈值
            rms_array = np.array(rms_values)
            energy_threshold = np.mean(rms_array) + 0.5 * np.std(rms_array)
            # 确保最低阈值
            energy_threshold = max(energy_threshold, 0.01)

            # 检测语音段
            segments = []
            in_speech = False
            speech_start_frame = 0
            silence_frames = 0
            max_silence_frames = int(max_silence_duration / frame_duration)
            min_speech_frames = int(min_speech_duration / frame_duration)

            for i in range(n_total_frames):
                is_speech = rms_values[i] > energy_threshold

                if is_speech:
                    if not in_speech:
                        in_speech = True
                        speech_start_frame = i
                    silence_frames = 0
                else:
                    if in_speech:
                        silence_frames += 1
                        if silence_frames >= max_silence_frames:
                            # 语音结束
                            speech_frames = i - silence_frames - speech_start_frame
                            if speech_frames >= min_speech_frames:
                                segments.append({
                                    'start': round(speech_start_frame * frame_duration, 3),
                                    'end': round((i - silence_frames) * frame_duration, 3),
                                    'confidence': 0.5,
                                })
                            in_speech = False

            # 处理末尾语音
            if in_speech:
                speech_frames = n_total_frames - speech_start_frame
                if speech_frames >= min_speech_frames:
                    segments.append({
                        'start': round(speech_start_frame * frame_duration, 3),
                        'end': round(n_total_frames * frame_duration, 3),
                        'confidence': 0.5,
                    })

            total_duration = sum(s['end'] - s['start'] for s in segments)

            return {
                'success': True,
                'engine': 'mock',
                'has_speech': len(segments) > 0,
                'speech_segments': segments,
                'total_speech_duration': round(total_duration, 3),
                'sample_rate': sample_rate,
                'note': 'Mock模式：基于能量阈值的VAD（精度较低）',
            }

        except Exception as e:
            print(f"[VAD] mock模式失败: {e}")
            return {
                'success': True,
                'engine': 'mock',
                'has_speech': True,
                'speech_segments': [{'start': 0, 'end': 1.0, 'confidence': 0.3}],
                'total_speech_duration': 1.0,
                'sample_rate': 16000,
                'note': 'Mock模式：VAD不可用，默认整段为语音',
            }

    # ============================================================
    # 流式语音识别
    # ============================================================

    def streaming_transcribe(self, audio_generator: Generator[bytes, None, None],
                             language: Optional[str] = None,
                             chunk_duration: float = 5.0,
                             vad_filter: bool = True) -> Generator[Dict[str, Any], None, None]:
        """流式语音识别（生成器模式）

        逐段处理音频流，每识别出一段完整语音就yield结果。
        适用于WebSocket等长连接场景下的实时语音识别。

        Args:
            audio_generator: 音频数据生成器，每次yield一段PCM音频字节数据
            language: 语言代码（zh/en/None=自动检测）
            chunk_duration: 每个识别块的时长（秒），控制识别延迟
            vad_filter: 是否启用VAD过滤（只识别有语音的片段）

        Yields:
            {
                'success': bool,
                'engine': str,
                'text': str,
                'language': str,
                'is_final': bool,  # 是否是最终结果（语音段结束）
                'partial': bool,   # 是否是中间结果
                'segment_index': int,
            }
        """
        lang = language or self._language
        engine = self.current_engine

        # 收集音频数据
        audio_buffer = bytearray()
        sample_rate = 16000  # 假设16kHz单声道16bit PCM
        bytes_per_second = sample_rate * 2  # 16bit = 2 bytes
        chunk_bytes = int(chunk_duration * bytes_per_second)

        segment_index = 0
        pending_audio = bytearray()  # 待识别的累积音频

        for audio_chunk in audio_generator:
            if not audio_chunk:
                continue

            audio_buffer.extend(audio_chunk)

            # 当缓冲超过一个chunk时处理
            while len(audio_buffer) >= chunk_bytes:
                chunk_data = bytes(audio_buffer[:chunk_bytes])
                audio_buffer = audio_buffer[chunk_bytes:]

                # 可选：VAD过滤
                if vad_filter:
                    vad_result = self._vad_on_chunk(chunk_data, sample_rate)
                    if not vad_result.get('has_speech', False):
                        # 静音片段，跳过识别
                        continue

                # 将chunk写入临时文件进行识别
                with tempfile.NamedTemporaryFile(suffix='.wav', delete=False) as tmp:
                    tmp_path = tmp.name
                    self._write_pcm_wav(chunk_data, sample_rate, tmp_path)

                try:
                    result = self.transcribe(tmp_path, lang)
                    if result.get('success') and result.get('text', '').strip():
                        segment_index += 1
                        yield {
                            'success': True,
                            'engine': result.get('engine', engine),
                            'text': result['text'].strip(),
                            'language': result.get('language', lang or 'zh'),
                            'is_final': True,
                            'partial': False,
                            'segment_index': segment_index,
                            'duration': chunk_duration,
                        }
                finally:
                    try:
                        os.unlink(tmp_path)
                    except Exception as e:
                        # 临时文件清理失败不影响识别结果
                        logger.debug("清理 ASR 临时文件失败: %s", e)

        # 处理剩余音频
        if len(audio_buffer) > 0:
            remaining_data = bytes(audio_buffer)
            min_bytes = int(0.5 * bytes_per_second)  # 至少0.5秒才识别

            if len(remaining_data) >= min_bytes:
                with tempfile.NamedTemporaryFile(suffix='.wav', delete=False) as tmp:
                    tmp_path = tmp.name
                    self._write_pcm_wav(remaining_data, sample_rate, tmp_path)

                try:
                    result = self.transcribe(tmp_path, lang)
                    if result.get('success') and result.get('text', '').strip():
                        segment_index += 1
                        yield {
                            'success': True,
                            'engine': result.get('engine', engine),
                            'text': result['text'].strip(),
                            'language': result.get('language', lang or 'zh'),
                            'is_final': True,
                            'partial': False,
                            'segment_index': segment_index,
                            'duration': len(remaining_data) / bytes_per_second,
                        }
                finally:
                    try:
                        os.unlink(tmp_path)
                    except Exception as e:
                        # 临时文件清理失败不影响识别结果
                        logger.debug("清理 ASR 剩余音频临时文件失败: %s", e)

    def _vad_on_chunk(self, pcm_data: bytes, sample_rate: int) -> Dict[str, Any]:
        """对单chunk PCM数据进行VAD检测（内存中处理，不写文件）"""
        engine = self.current_vad_engine

        if engine == 'silero-vad':
            try:
                import torch
                model = self._get_silero_vad_model()

                # 转换为tensor
                audio_np = np.frombuffer(pcm_data, dtype=np.int16).astype(np.float32) / 32768.0
                audio_tensor = torch.from_numpy(audio_np)

                # 分帧检测
                window_size = 512
                speech_count = 0
                total_frames = 0

                for i in range(0, len(audio_tensor) - window_size, window_size):
                    frame = audio_tensor[i:i + window_size]
                    if len(frame) < window_size:
                        break
                    prob = model(frame, sample_rate).item()
                    if prob > 0.5:
                        speech_count += 1
                    total_frames += 1

                has_speech = total_frames > 0 and (speech_count / total_frames) > 0.3

                return {
                    'success': True,
                    'engine': 'silero-vad',
                    'has_speech': has_speech,
                    'speech_ratio': speech_count / max(total_frames, 1),
                }
            except Exception as e:
                print(f"[VAD] chunk级silero检测失败: {e}")
                # 降级到能量检测

        # 能量阈值法（快速检测）
        audio_np = np.frombuffer(pcm_data, dtype=np.int16).astype(np.float32) / 32768.0
        if len(audio_np) == 0:
            return {'success': True, 'engine': 'mock', 'has_speech': False}

        rms = np.sqrt(np.mean(audio_np ** 2))
        # 经验阈值：正常语音RMS大约在0.01-0.3之间
        has_speech = rms > 0.01

        return {
            'success': True,
            'engine': 'mock' if engine != 'silero-vad' else 'silero-vad-fallback',
            'has_speech': has_speech,
            'rms': float(rms),
        }

    @staticmethod
    def _write_pcm_wav(pcm_data: bytes, sample_rate: int, output_path: str):
        """将原始PCM数据写入WAV文件头"""
        import wave
        with wave.open(output_path, 'wb') as wf:
            wf.setnchannels(1)       # 单声道
            wf.setsampwidth(2)       # 16bit
            wf.setframerate(sample_rate)
            wf.writeframes(pcm_data)

    # ============================================================
    # 唤醒词检测
    # ============================================================

    def detect_wake_word(self, audio_path: str, wake_words: Optional[List[str]] = None,
                         language: Optional[str] = None) -> Dict[str, Any]:
        """唤醒词检测

        检测流程：
        1. VAD检测音频中的语音片段
        2. 对每个语音片段使用faster-whisper进行识别
        3. 将识别文本与唤醒词列表进行匹配
        4. 返回是否检测到唤醒词及匹配的唤醒词

        Args:
            audio_path: 音频文件路径
            wake_words: 唤醒词列表（如 ["云汐", "你好云汐"]），为None则使用默认配置
            language: 语言代码，默认中文

        Returns:
            {
                'success': bool,
                'engine': str,
                'wake_word_detected': bool,
                'matched_word': str | None,  # 匹配到的唤醒词
                'transcript': str,           # 完整识别文本
                'confidence': float,         # 匹配置信度 (0-1)
                'language': str,
            }
        """
        # 默认唤醒词
        if wake_words is None:
            wake_words = self.config.get('wake_words', ['云汐', '你好云汐'])

        if not wake_words:
            return {
                'success': False,
                'error': '唤醒词列表为空',
                'engine': self.current_engine,
                'wake_word_detected': False,
                'matched_word': None,
                'transcript': '',
                'confidence': 0.0,
                'language': language or self._language,
            }

        lang = language or self._language

        # 步骤1: VAD检测语音片段
        vad_result = self.vad_detect(audio_path)

        if not vad_result.get('success', False):
            # VAD失败，直接对整段音频进行识别
            return self._wake_word_from_file(audio_path, wake_words, lang)

        speech_segments = vad_result.get('speech_segments', [])

        if not speech_segments:
            # 没有检测到语音
            return {
                'success': True,
                'engine': self.current_engine,
                'wake_word_detected': False,
                'matched_word': None,
                'transcript': '',
                'confidence': 0.0,
                'language': lang or 'zh',
                'vad_engine': vad_result.get('engine', 'unknown'),
                'note': '未检测到语音活动',
            }

        # 步骤2: 提取语音片段并识别
        # 为了提高唤醒词检测效率，只识别第一个语音片段（唤醒词通常在开头）
        # 如果第一个片段没有匹配，再尝试第二个
        max_segments_to_check = min(3, len(speech_segments))

        for i in range(max_segments_to_check):
            segment = speech_segments[i]

            # 提取语音片段（使用ffmpeg或pydub，如果不可用则识别整段）
            segment_audio = self._extract_audio_segment(
                audio_path, segment['start'], segment['end']
            )

            if segment_audio is None:
                # 无法提取片段，识别整段
                return self._wake_word_from_file(audio_path, wake_words, lang)

            # 识别该片段
            result = self.transcribe(segment_audio, lang)

            # 清理临时文件
            try:
                os.unlink(segment_audio)
            except Exception as e:
                # 片段音频清理失败不影响唤醒词检测结果
                logger.debug("清理唤醒词检测片段音频失败: %s", e)

            if not result.get('success'):
                continue

            text = result.get('text', '').strip()
            if not text:
                continue

            # 步骤3: 关键词匹配
            match_result = self._match_wake_word(text, wake_words)
            if match_result['matched']:
                return {
                    'success': True,
                    'engine': result.get('engine', self.current_engine),
                    'wake_word_detected': True,
                    'matched_word': match_result['word'],
                    'transcript': text,
                    'confidence': match_result['confidence'],
                    'language': result.get('language', lang or 'zh'),
                    'vad_engine': vad_result.get('engine', 'unknown'),
                    'segment_index': i,
                    'segment_start': segment['start'],
                    'segment_end': segment['end'],
                }

        # 所有片段都没匹配到
        return {
            'success': True,
            'engine': self.current_engine,
            'wake_word_detected': False,
            'matched_word': None,
            'transcript': '',
            'confidence': 0.0,
            'language': lang or 'zh',
            'vad_engine': vad_result.get('engine', 'unknown'),
            'note': '语音中未检测到唤醒词',
        }

    def _wake_word_from_file(self, audio_path: str, wake_words: List[str],
                             language: Optional[str]) -> Dict[str, Any]:
        """直接从音频文件中检测唤醒词（不使用VAD分段）"""
        result = self.transcribe(audio_path, language)

        if not result.get('success'):
            return {
                'success': False,
                'error': result.get('error', '语音识别失败'),
                'engine': result.get('engine', self.current_engine),
                'wake_word_detected': False,
                'matched_word': None,
                'transcript': '',
                'confidence': 0.0,
                'language': result.get('language', language or 'zh'),
            }

        text = result.get('text', '').strip()
        match_result = self._match_wake_word(text, wake_words)

        return {
            'success': True,
            'engine': result.get('engine', self.current_engine),
            'wake_word_detected': match_result['matched'],
            'matched_word': match_result.get('word'),
            'transcript': text,
            'confidence': match_result.get('confidence', 0.0),
            'language': result.get('language', language or 'zh'),
            'note': '整段识别模式（VAD不可用）',
        }

    def _match_wake_word(self, text: str, wake_words: List[str]) -> Dict[str, Any]:
        """匹配唤醒词

        支持多种匹配策略（按优先级）：
        1. 精确匹配：文本中包含完整的唤醒词
        2. 前缀匹配：文本以唤醒词开头
        3. 同音字匹配：基于拼音的发音近似匹配
        4. 模糊匹配：基于字符相似度的近似匹配

        Args:
            text: 识别出的文本
            wake_words: 唤醒词列表

        Returns:
            {'matched': bool, 'word': str|None, 'confidence': float, 'match_type': str}
        """
        if not text or not wake_words:
            return {'matched': False, 'word': None, 'confidence': 0.0, 'match_type': 'none'}

        # 去除文本中的标点和空格，提高匹配率
        import re
        clean_text = re.sub(r'[^\w\u4e00-\u9fff]', '', text).lower()

        for word in wake_words:
            clean_word = re.sub(r'[^\w\u4e00-\u9fff]', '', word).lower()

            if not clean_word:
                continue

            # 1. 精确包含匹配
            if clean_word in clean_text:
                return {
                    'matched': True,
                    'word': word,
                    'confidence': 0.95,
                    'match_type': 'exact',
                }

            # 2. 前缀匹配（唤醒词通常在句首）
            if clean_text.startswith(clean_word):
                return {
                    'matched': True,
                    'word': word,
                    'confidence': 0.9,
                    'match_type': 'prefix',
                }

            # 3. 同音字匹配（基于拼音，处理ASR识别的同音字问题）
            # 例如："云汐" 可能被识别为 "元希/袁熙/营西"
            pinyin_match = self._pinyin_match(clean_text, clean_word)
            if pinyin_match > 0.55:
                return {
                    'matched': True,
                    'word': word,
                    'confidence': pinyin_match,
                    'match_type': 'pinyin',
                }

            # 4. 模糊匹配：计算字符相似度（句首窗口更宽松）
            # 取句首与唤醒词等长的窗口进行比较（唤醒词通常在开头）
            prefix_window = clean_text[:max(len(clean_word), 4)]
            prefix_sim = self._string_similarity(prefix_window, clean_word)
            if prefix_sim >= 0.55 and len(clean_word) <= len(prefix_window) + 1:
                return {
                    'matched': True,
                    'word': word,
                    'confidence': prefix_sim,
                    'match_type': 'prefix_fuzzy',
                }

            # 全文模糊匹配（较严格）
            similarity = self._string_similarity(clean_text, clean_word)
            if similarity >= 0.7:
                return {
                    'matched': True,
                    'word': word,
                    'confidence': similarity,
                    'match_type': 'fuzzy',
                }

        return {'matched': False, 'word': None, 'confidence': 0.0, 'match_type': 'none'}

    def _pinyin_match(self, text: str, word: str) -> float:
        """拼音相似度匹配（处理ASR同音字问题）

        尝试使用 pypinyin 库计算拼音相似度。
        支持三级匹配：
        1. 完整拼音相同（最高置信度）
        2. 声母相同（处理前后鼻音、平翘舌等ASR常见混淆）
        3. 声调外拼音相似度

        如果 pypinyin 未安装，返回 0（不影响原有逻辑）。

        Args:
            text: 识别文本
            word: 唤醒词

        Returns:
            拼音相似度 (0-1)
        """
        try:
            from pypinyin import lazy_pinyin, Style
        except ImportError:
            return 0.0

        try:
            # 取句首与唤醒词等长的窗口
            word_len = len(word)
            if word_len == 0 or len(text) < word_len:
                return 0.0

            # 取句首窗口比较
            text_prefix = text[:word_len]

            # 转拼音
            text_pinyin = lazy_pinyin(text_prefix, style=Style.NORMAL)
            word_pinyin = lazy_pinyin(word, style=Style.NORMAL)

            if len(text_pinyin) != len(word_pinyin) or len(text_pinyin) == 0:
                return 0.0

            # 计算完整拼音相同的比例
            exact_count = sum(1 for i in range(len(text_pinyin))
                            if text_pinyin[i] == word_pinyin[i])

            # 计算声母相同的比例（处理 yun/yuan、ying/yun 等混淆）
            def get_initial(py: str) -> str:
                """获取拼音声母（首字母，对于零声母取韵母首字母）"""
                if not py:
                    return ''
                # 常见声母列表
                initials = ['zh', 'ch', 'sh', 'b', 'p', 'm', 'f', 'd', 't', 'n', 'l',
                           'g', 'k', 'h', 'j', 'q', 'x', 'r', 'z', 'c', 's', 'y', 'w']
                for init in initials:
                    if py.startswith(init):
                        return init
                return py[0] if py else ''

            initial_count = sum(1 for i in range(len(text_pinyin))
                              if get_initial(text_pinyin[i]) == get_initial(word_pinyin[i]))

            # 综合评分：完整拼音权重高，声母匹配权重较低
            exact_score = exact_count / len(text_pinyin)
            initial_score = initial_count / len(text_pinyin)

            # 加权：完整拼音1.0，声母匹配0.5
            final_score = exact_score * 0.6 + initial_score * 0.4

            return final_score

        except Exception:
            return 0.0

    @staticmethod
    def _string_similarity(s1: str, s2: str) -> float:
        """计算两个字符串的相似度（基于编辑距离）

        对于唤醒词匹配场景，主要看s2（唤醒词）是否近似出现在s1中。
        使用滑动窗口计算最小编辑距离。
        """
        if not s1 or not s2:
            return 0.0

        len1, len2 = len(s1), len(s2)
        if len2 > len1:
            s1, s2 = s2, s1
            len1, len2 = len2, len1

        # 如果唤醒词比文本长很多，相似度低
        if len2 == 0:
            return 0.0

        # 在s1中滑动窗口，找与s2最相似的子串
        min_distance = float('inf')
        window_size = len2

        for i in range(len1 - window_size + 1):
            substring = s1[i:i + window_size]
            distance = 0
            for j in range(window_size):
                if substring[j] != s2[j]:
                    distance += 1
            min_distance = min(min_distance, distance)

        if min_distance == float('inf'):
            return 0.0

        similarity = 1.0 - (min_distance / len2)
        return max(0.0, min(1.0, similarity))

    def _extract_audio_segment(self, audio_path: str, start: float, end: float) -> Optional[str]:
        """提取音频片段

        使用pydub提取指定时间段的音频，保存为临时文件。
        如果pydub不可用，返回None。

        Args:
            audio_path: 原音频路径
            start: 开始时间（秒）
            end: 结束时间（秒）

        Returns:
            临时文件路径，失败返回None
        """
        try:
            from pydub import AudioSegment

            audio = AudioSegment.from_file(audio_path)
            segment = audio[start * 1000:end * 1000]

            tmp_file = tempfile.NamedTemporaryFile(suffix='.wav', delete=False)
            tmp_path = tmp_file.name
            tmp_file.close()

            segment.export(tmp_path, format='wav')
            return tmp_path
        except Exception as e:
            print(f"[ASR] 提取音频片段失败: {e}")
            return None

    # ============================================================
    # 唤醒词配置管理
    # ============================================================

    @property
    def wake_words(self) -> List[str]:
        """当前配置的唤醒词列表"""
        return self.config.get('wake_words', ['云汐', '你好云汐'])

    def set_wake_words(self, words: List[str]) -> bool:
        """设置唤醒词列表

        Args:
            words: 唤醒词列表，例如 ["云汐", "你好云汐", "小云"]

        Returns:
            是否设置成功
        """
        if not isinstance(words, list) or len(words) == 0:
            return False

        # 过滤空字符串
        filtered = [w.strip() for w in words if w and w.strip()]
        if not filtered:
            return False

        self.config['wake_words'] = filtered
        print(f"[ASR] 唤醒词已更新: {filtered}")
        return True

    def add_wake_word(self, word: str) -> bool:
        """添加单个唤醒词

        Args:
            word: 要添加的唤醒词

        Returns:
            是否添加成功（已存在则返回False）
        """
        if not word or not word.strip():
            return False

        word = word.strip()
        current = self.wake_words
        if word in current:
            return False

        current.append(word)
        self.config['wake_words'] = current
        print(f"[ASR] 唤醒词已添加: {word}")
        return True

    def remove_wake_word(self, word: str) -> bool:
        """移除唤醒词

        Args:
            word: 要移除的唤醒词

        Returns:
            是否移除成功
        """
        current = self.wake_words
        if word not in current:
            return False

        if len(current) <= 1:
            # 至少保留一个唤醒词
            return False

        current.remove(word)
        self.config['wake_words'] = current
        print(f"[ASR] 唤醒词已移除: {word}")
        return True


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
