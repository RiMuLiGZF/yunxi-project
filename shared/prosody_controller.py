"""
语音韵律控制器 - 人格润色与语音合成的桥梁
==========================================

解决"人机感"问题的核心模块：将人格参数、情感状态、场景上下文
转换为语音合成引擎可理解的韵律控制指令。

核心能力：
1. 人格五维参数 → 语音风格映射
2. 情感状态 → 韵律特征映射
3. 场景/模式 → 语速语调调整
4. 文本分析 → 停顿/重音/语气词注入
5. CosyVoice 指令生成器
6. SSML 生成器（edge-tts 等兼容）

这是"文本人格润色"和"语音合成"之间缺失的关键一层。
"""

import re
import math
from typing import Optional, Dict, Any, List, Tuple
from dataclasses import dataclass, field
from enum import Enum


class EmotionType(str, Enum):
    """情感类型"""
    WARM = "warm"           # 温暖温柔
    HAPPY = "happy"         # 开心愉悦
    SAD = "sad"             # 忧伤难过
    CALM = "calm"           # 平静沉稳
    EXCITED = "excited"     # 兴奋激动
    GENTLE = "gentle"       # 轻柔温和
    SERIOUS = "serious"     # 严肃认真
    PLAYFUL = "playful"     # 俏皮活泼
    THOUGHTFUL = "thoughtful"  # 若有所思
    ENCOURAGING = "encouraging"  # 鼓励支持
    EMPATHETIC = "empathetic"    # 共情理解


class SpeechRate(str, Enum):
    """语速级别"""
    VERY_SLOW = "very_slow"
    SLOW = "slow"
    NORMAL = "normal"
    FAST = "fast"
    VERY_FAST = "very_fast"


@dataclass
class PersonalityTraits:
    """五维人格参数（0-10 分制）"""
    warmth: float = 8.5        # 温暖度
    rationality: float = 7.5   # 理性度
    humor: float = 6.0         # 幽默度
    empathy: float = 9.0       # 共情感
    reliability: float = 9.5   # 可靠度


@dataclass
class SpeechProsody:
    """语音韵律特征
    
    描述一段语音的完整韵律特征，可映射到不同TTS引擎。
    """
    # 基础参数
    rate: float = 1.0          # 语速倍率 (0.5-2.0)
    pitch: float = 1.0         # 音调倍率 (0.5-2.0)
    volume: float = 1.0        # 音量倍率 (0.1-2.0)
    
    # 情感与风格
    emotion: str = "warm"      # 情感类型
    style: str = "natural"     # 说话风格
    
    # 细粒度控制
    pause_between_sentences: float = 0.4  # 句间停顿（秒）
    pause_between_paragraphs: float = 0.8  # 段间停顿（秒）
    emphasis_strength: float = 1.2        # 重音强度
    
    # 方言/语言
    dialect: Optional[str] = None  # 方言（sichuan/dongbei/cantonese 等）
    
    # 特殊效果
    breathiness: float = 0.0     # 气声程度（0-1）
    laughter: bool = False       # 是否带笑意
    
    def to_cosyvoice_instruction(self) -> str:
        """转换为 CosyVoice 指令控制文本
        
        Returns:
            自然语言指令（带 <|endofprompt|> 结束标记）
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
            'thoughtful': '用若有所思的语气说',
            'encouraging': '用鼓励支持的语气说',
            'empathetic': '用共情理解的语气说',
        }
        if self.emotion in emotion_map:
            instructions.append(emotion_map[self.emotion])
        
        # 语速
        if self.rate < 0.7:
            instructions.append('语速慢一点，再慢一点')
        elif self.rate < 0.85:
            instructions.append('语速慢一点')
        elif self.rate > 1.4:
            instructions.append('语速快一点，再快一点')
        elif self.rate > 1.2:
            instructions.append('语速快一点')
        
        # 音量
        if self.volume < 0.6:
            instructions.append('声音轻一点')
        elif self.volume > 1.4:
            instructions.append('声音大一点')
        
        # 方言
        dialect_map = {
            'sichuan': '用四川话说',
            'dongbei': '用东北话说',
            'shaanxi': '用陕西话说',
            'cantonese': '用广东话说',
            'minnan': '用闽南话说',
            'shanghai': '用上海话说',
            'tianjin': '用天津话说',
        }
        if self.dialect and self.dialect in dialect_map:
            instructions.append(dialect_map[self.dialect])
        
        # 气声/轻语
        if self.breathiness > 0.5:
            instructions.append('用气声轻声说')
        
        if not instructions:
            instructions.append('用自然的语气说')
        
        return "，".join(instructions) + "<|endofprompt|>"

    def to_ssml(self, text: str) -> str:
        """转换为 SSML 格式（适用于 edge-tts 等支持 SSML 的引擎）
        
        Args:
            text: 要合成的文本
        
        Returns:
            SSML 格式字符串
        """
        # 语速转换（百分比）
        rate_percent = int((self.rate - 1.0) * 100)
        rate_str = f"+{rate_percent}%" if rate_percent >= 0 else f"{rate_percent}%"
        
        # 音调转换（半音）
        pitch_st = int((self.pitch - 1.0) * 12)  # 1个八度=12半音
        pitch_str = f"+{pitch_st}st" if pitch_st >= 0 else f"{pitch_st}st"
        
        # 音量转换
        vol_percent = int(self.volume * 100)
        
        ssml = f'<speak version="1.0" xmlns="http://www.w3.org/2001/10/synthesis" xml:lang="zh-CN">'
        ssml += f'<voice name="zh-CN-XiaoxiaoNeural">'
        ssml += f'<prosody rate="{rate_str}" pitch="{pitch_str}" volume="{vol_percent}%">'
        ssml += text
        ssml += '</prosody></voice></speak>'
        
        return ssml

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            'rate': self.rate,
            'pitch': self.pitch,
            'volume': self.volume,
            'emotion': self.emotion,
            'style': self.style,
            'dialect': self.dialect,
            'pause_between_sentences': self.pause_between_sentences,
            'pause_between_paragraphs': self.pause_between_paragraphs,
        }


class ProsodyController:
    """语音韵律控制器
    
    根据人格参数、情感状态、场景上下文计算语音韵律特征。
    这是"人格润色"到"语音合成"的桥梁。
    """

    def __init__(self, personality: Optional[PersonalityTraits] = None):
        self.personality = personality or PersonalityTraits()
        
        # 场景配置
        self._scene_prosody_map = {
            'work_dev': SpeechProsody(rate=1.05, pitch=1.0, emotion='serious', 
                                      pause_between_sentences=0.35),
            'study_plan': SpeechProsody(rate=0.95, pitch=1.0, emotion='encouraging',
                                        pause_between_sentences=0.45),
            'review_summary': SpeechProsody(rate=0.9, pitch=0.95, emotion='calm',
                                            pause_between_sentences=0.5),
            'relationship': SpeechProsody(rate=0.9, pitch=1.05, emotion='empathetic',
                                          pause_between_sentences=0.5),
            'emotion_companion': SpeechProsody(rate=0.85, pitch=1.05, emotion='warm',
                                               pause_between_sentences=0.55),
            'life_management': SpeechProsody(rate=1.0, pitch=1.0, emotion='gentle',
                                             pause_between_sentences=0.4),
        }
        
        # 模式配置
        self._mode_prosody_map = {
            'CODING': SpeechProsody(rate=1.1, pitch=1.0, emotion='serious', style='precise'),
            'DOCUMENT': SpeechProsody(rate=0.95, pitch=1.0, emotion='calm', style='formal'),
            'REVIEW': SpeechProsody(rate=0.9, pitch=0.95, emotion='thoughtful', style='analytical'),
            'DESIGN': SpeechProsody(rate=1.0, pitch=1.05, emotion='playful', style='creative'),
            'MENTAL': SpeechProsody(rate=0.85, pitch=1.05, emotion='warm', style='supportive'),
            'PLANNING': SpeechProsody(rate=1.0, pitch=1.0, emotion='calm', style='organized'),
        }

    # ============================================================
    # 核心方法：计算韵律特征
    # ============================================================

    def compute_prosody(
        self,
        text: str,
        emotion: Optional[str] = None,
        scene: Optional[str] = None,
        mode: Optional[str] = None,
        user_preferences: Optional[Dict[str, Any]] = None,
    ) -> SpeechProsody:
        """计算语音韵律特征
        
        计算链路：基础人格 → 场景偏移 → 模式微调 → 情感强化 → 用户偏好 → 钳位
        
        Args:
            text: 要合成的文本（用于分析句子结构、标点等）
            emotion: 目标情感（可选，覆盖默认推断）
            scene: 场景上下文（可选）
            mode: 底层模式（可选）
            user_preferences: 用户偏好（可选）
        
        Returns:
            SpeechProsody 韵律特征对象
        """
        # 1. 基础韵律（由人格决定）
        prosody = self._base_prosody_from_personality()
        
        # 2. 场景偏移
        if scene and scene in self._scene_prosody_map:
            scene_prosody = self._scene_prosody_map[scene]
            prosody = self._blend_prosody(prosody, scene_prosody, weight=0.4)
        
        # 3. 模式微调
        if mode and mode in self._mode_prosody_map:
            mode_prosody = self._mode_prosody_map[mode]
            prosody = self._blend_prosody(prosody, mode_prosody, weight=0.3)
        
        # 4. 情感处理
        if emotion:
            # 显式指定的情感优先级最高
            prosody.emotion = emotion
            prosody = self._apply_emotion_tuning(prosody, emotion, weight=0.5)
        else:
            # 场景已提供基础情感，文本情感做微调（权重较低）
            inferred_emotion = self._infer_emotion_from_text(text)
            if inferred_emotion and inferred_emotion != prosody.emotion:
                # 文本情感与场景情感不同时，轻量混合
                prosody = self._apply_emotion_tuning(prosody, inferred_emotion, weight=0.2)
                # 情感标签仍以场景为主，但标注有文本情感微调
                prosody.emotion = prosody.emotion  # 保持场景情感标签
        
        # 5. 用户偏好
        if user_preferences:
            prosody = self._apply_user_preferences(prosody, user_preferences)
        
        # 6. 钳位（确保参数在合理范围内）
        prosody = self._clamp_prosody(prosody)
        
        return prosody

    # ============================================================
    # 人格 → 韵律 映射
    # ============================================================

    def _base_prosody_from_personality(self) -> SpeechProsody:
        """基于五维人格参数计算基础韵律特征"""
        p = self.personality
        
        # 温暖度高 → 语速稍慢、音调稍高、音量适中偏低
        # 理性度高 → 语速稳定、音调平稳、停顿稍长
        # 幽默度高 → 语速变化多、音调起伏大、重音明显
        # 共情感高 → 语速慢、音调柔和、停顿多
        # 可靠度高 → 语速稳定、音调偏低、音量适中
        
        base_rate = 1.0
        base_pitch = 1.0
        base_volume = 1.0
        
        # 温暖度影响
        base_pitch += (p.warmth - 5) * 0.02  # 温暖度越高音调略高
        base_volume -= (p.warmth - 5) * 0.01  # 温暖度越高音量略低
        
        # 理性度影响
        if p.rationality > 7:
            base_rate *= 0.98  # 理性的人说话稍慢，更稳重
        
        # 共情感影响
        base_rate -= (p.empathy - 5) * 0.02  # 共情度越高语速越慢
        
        # 幽默度影响（增加变化空间）
        # 幽默的人语调起伏更大，但平均语速差不多
        
        return SpeechProsody(
            rate=base_rate,
            pitch=base_pitch,
            volume=base_volume,
            emotion='warm' if p.warmth > 7 else 'calm',
            pause_between_sentences=0.35 + (p.empathy - 5) * 0.03,
            pause_between_paragraphs=0.7 + (p.empathy - 5) * 0.05,
        )

    # ============================================================
    # 情感 → 韵律 调优
    # ============================================================

    def _apply_emotion_tuning(self, prosody: SpeechProsody, emotion: str,
                              weight: float = 0.5) -> SpeechProsody:
        """根据情感类型调整韵律参数
        
        Args:
            prosody: 当前韵律特征
            emotion: 目标情感
            weight: 情感调整的权重（0-1），越大变化越明显
        """
        tuning = {
            'warm': {'rate': 0.95, 'pitch': 1.03, 'volume': 0.95},
            'happy': {'rate': 1.15, 'pitch': 1.1, 'volume': 1.1},
            'sad': {'rate': 0.8, 'pitch': 0.9, 'volume': 0.85},
            'calm': {'rate': 0.9, 'pitch': 0.95, 'volume': 0.9},
            'excited': {'rate': 1.25, 'pitch': 1.15, 'volume': 1.2},
            'gentle': {'rate': 0.85, 'pitch': 1.0, 'volume': 0.8},
            'serious': {'rate': 0.95, 'pitch': 0.95, 'volume': 1.0},
            'playful': {'rate': 1.1, 'pitch': 1.1, 'volume': 1.05},
            'thoughtful': {'rate': 0.85, 'pitch': 0.95, 'volume': 0.9},
            'encouraging': {'rate': 1.05, 'pitch': 1.05, 'volume': 1.1},
            'empathetic': {'rate': 0.85, 'pitch': 1.0, 'volume': 0.9},
        }
        
        if emotion in tuning:
            t = tuning[emotion]
            # 按权重混合（不是完全替换）
            prosody.rate = prosody.rate * (1 - weight) + t['rate'] * weight
            prosody.pitch = prosody.pitch * (1 - weight) + t['pitch'] * weight
            prosody.volume = prosody.volume * (1 - weight) + t['volume'] * weight
        
        return prosody

    # ============================================================
    # 文本情感推断
    # ============================================================

    def _infer_emotion_from_text(self, text: str) -> Optional[str]:
        """从文本内容简单推断情感
        
        基于关键词和标点的简单情感推断（实际生产环境应使用情感分析模型）。
        """
        text_lower = text.lower()
        
        # 开心/愉悦关键词
        happy_words = ['哈哈', '开心', '快乐', '高兴', '棒', '好耶', '太好了', '太棒了',
                       '恭喜', '庆祝', '!', '！', '嘻嘻', '嘿嘿']
        if any(w in text for w in happy_words):
            return 'happy'
        
        # 忧伤/难过关键词
        sad_words = ['难过', '伤心', '失望', '遗憾', '可惜', '唉', '哎', '...', '……']
        if any(w in text for w in sad_words):
            return 'sad'
        
        # 鼓励/支持关键词
        encouraging_words = ['加油', '相信你', '没问题', '一定可以', '坚持', '努力', '你可以的']
        if any(w in text for w in encouraging_words):
            return 'encouraging'
        
        # 共情关键词
        empathetic_words = ['我理解', '我懂', '确实', '不容易', '辛苦了', '抱抱', '别担心']
        if any(w in text for w in empathetic_words):
            return 'empathetic'
        
        # 严肃/认真关键词
        serious_words = ['重要', '注意', '必须', '需要注意', '关键', '核心', '本质']
        if any(w in text for w in serious_words):
            return 'serious'
        
        # 默认温暖
        return 'warm'

    # ============================================================
    # 辅助方法
    # ============================================================

    def _blend_prosody(self, base: SpeechProsody, overlay: SpeechProsody, 
                       weight: float = 0.5) -> SpeechProsody:
        """混合两个韵律特征
        
        Args:
            base: 基础韵律
            overlay: 叠加韵律
            weight: 叠加韵律的权重（0-1）
        
        Returns:
            混合后的韵律特征
        """
        return SpeechProsody(
            rate=base.rate * (1 - weight) + overlay.rate * weight,
            pitch=base.pitch * (1 - weight) + overlay.pitch * weight,
            volume=base.volume * (1 - weight) + overlay.volume * weight,
            emotion=overlay.emotion if weight > 0.5 else base.emotion,
            style=overlay.style if weight > 0.5 else base.style,
            pause_between_sentences=base.pause_between_sentences * (1 - weight) + overlay.pause_between_sentences * weight,
            pause_between_paragraphs=base.pause_between_paragraphs * (1 - weight) + overlay.pause_between_paragraphs * weight,
            dialect=overlay.dialect or base.dialect,
        )

    def _apply_user_preferences(self, prosody: SpeechProsody, 
                                prefs: Dict[str, Any]) -> SpeechProsody:
        """应用用户偏好"""
        # 语气温度（影响整体情感倾向）
        if 'warmth_level' in prefs:
            warmth = prefs['warmth_level']  # 0-10
            # 调整基础情感倾向
            prosody.pitch += (warmth - 5) * 0.01
        
        # 语速偏好
        if 'speech_speed' in prefs:
            speed = prefs['speech_speed']  # 0-10
            prosody.rate *= 0.7 + speed * 0.06  # 0.7-1.3 倍
        
        # 音量偏好
        if 'speech_volume' in prefs:
            vol = prefs['speech_volume']  # 0-10
            prosody.volume *= 0.5 + vol * 0.05  # 0.5-1.0 倍
        
        # 方言偏好
        if 'dialect' in prefs:
            prosody.dialect = prefs['dialect']
        
        return prosody

    def _clamp_prosody(self, prosody: SpeechProsody) -> SpeechProsody:
        """钳位韵律参数到合理范围"""
        prosody.rate = max(0.5, min(2.0, prosody.rate))
        prosody.pitch = max(0.5, min(2.0, prosody.pitch))
        prosody.volume = max(0.1, min(2.0, prosody.volume))
        prosody.pause_between_sentences = max(0.1, min(2.0, prosody.pause_between_sentences))
        prosody.pause_between_paragraphs = max(0.3, min(3.0, prosody.pause_between_paragraphs))
        return prosody

    # ============================================================
    # 便捷方法
    # ============================================================

    def generate_cosyvoice_instruction(
        self,
        text: str,
        emotion: Optional[str] = None,
        scene: Optional[str] = None,
        mode: Optional[str] = None,
        user_preferences: Optional[Dict[str, Any]] = None,
    ) -> str:
        """便捷方法：直接生成 CosyVoice 指令
        
        Returns:
            CosyVoice 指令控制文本（含 <|endofprompt|>）
        """
        prosody = self.compute_prosody(text, emotion, scene, mode, user_preferences)
        return prosody.to_cosyvoice_instruction()

    def generate_ssml(
        self,
        text: str,
        emotion: Optional[str] = None,
        scene: Optional[str] = None,
        mode: Optional[str] = None,
        user_preferences: Optional[Dict[str, Any]] = None,
    ) -> str:
        """便捷方法：直接生成 SSML"""
        prosody = self.compute_prosody(text, emotion, scene, mode, user_preferences)
        return prosody.to_ssml(text)


# ============================================================
# 便捷函数
# ============================================================

_default_controller: Optional[ProsodyController] = None


def get_prosody_controller(personality: Optional[PersonalityTraits] = None) -> ProsodyController:
    """获取全局韵律控制器实例（单例）"""
    global _default_controller
    if _default_controller is None or personality is not None:
        _default_controller = ProsodyController(personality)
    return _default_controller


def text_to_cosyvoice_instruction(
    text: str,
    emotion: Optional[str] = None,
    personality: Optional[PersonalityTraits] = None,
    scene: Optional[str] = None,
) -> str:
    """便捷函数：文本 → CosyVoice 指令"""
    controller = get_prosody_controller(personality)
    return controller.generate_cosyvoice_instruction(text, emotion, scene)
