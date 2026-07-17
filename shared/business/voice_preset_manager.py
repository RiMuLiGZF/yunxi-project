"""
云汐音色管理 - 零样本语音克隆的参考音频管理
============================================

管理云汐的专属音色，支持：
1. 多套预设音色（温柔版、活泼版、沉稳版等）
2. 用户自定义音色上传
3. 音色质量评估
4. 与 CosyVoice 服务的自动注册
5. 音色切换与场景关联

音色是云汐"人机感"的关键——让AI拥有独一无二的声音。
"""

import os
import json
import time
import shutil
import logging
from typing import Optional, Dict, Any, List
from pathlib import Path
from dataclasses import dataclass, field, asdict

logger = logging.getLogger(__name__)


@dataclass
class VoicePreset:
    """音色预设"""
    preset_id: str                    # 音色ID
    name: str                         # 音色名称（如"温柔云汐"）
    description: str = ""             # 音色描述
    reference_audio_path: str = ""    # 参考音频路径
    reference_text: str = ""          # 参考音频文本
    style: str = "warm"               # 风格标签（warm/playful/calm/serious 等）
    gender: str = "female"            # 性别（female/male/other）
    age_range: str = "young_adult"    # 年龄段
    language: str = "zh-CN"           # 主要语言
    quality_score: float = 0.0        # 质量评分（0-100，自动评估）
    is_builtin: bool = False          # 是否内置预设
    is_active: bool = False           # 是否当前激活
    created_at: float = 0.0
    updated_at: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "VoicePreset":
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})


class VoicePresetManager:
    """云汐音色预设管理器
    
    管理所有音色预设，包括内置预设和用户自定义音色。
    """

    def __init__(self, storage_dir: Optional[str] = None):
        if storage_dir is None:
            storage_dir = os.environ.get(
                "YUNXI_VOICE_DIR",
                os.path.join(str(Path.home()), ".yunxi", "voices")
            )
        self.storage_dir = Path(storage_dir)
        self.audio_dir = self.storage_dir / "audio"
        self.presets_file = self.storage_dir / "presets.json"
        self._presets: Dict[str, VoicePreset] = {}
        self._active_preset_id: Optional[str] = None
        
        # 确保目录存在
        self.storage_dir.mkdir(parents=True, exist_ok=True)
        self.audio_dir.mkdir(parents=True, exist_ok=True)
        
        # 加载预设
        self._load_presets()
        
        # 初始化内置预设（首次运行）
        if not self._presets:
            self._init_builtin_presets()

    # ============================================================
    # 内置音色预设
    # ============================================================

    def _init_builtin_presets(self):
        """初始化内置音色预设
        
        这些是"虚拟"预设——用户需要提供参考音频才能真正使用。
        它们定义了云汐的几种典型声音风格。
        """
        builtin_presets = [
            VoicePreset(
                preset_id="yunxi_warm",
                name="温柔云汐",
                description="温暖柔和的女声，像知心姐姐一样温柔体贴，语速适中，语调平缓。最适合日常陪伴和情感支持场景。",
                style="warm",
                gender="female",
                age_range="young_adult",
                language="zh-CN",
                is_builtin=True,
                is_active=True,
                reference_text="希望你以后能够做的比我还好呦。无论遇到什么困难，我都会在这里陪着你。",
                created_at=time.time(),
                updated_at=time.time(),
            ),
            VoicePreset(
                preset_id="yunxi_playful",
                name="活泼云汐",
                description="元气满满的少女音，语速轻快，语调起伏大，充满活力。适合轻松聊天、讲笑话、玩游戏等场景。",
                style="playful",
                gender="female",
                age_range="teen",
                language="zh-CN",
                is_builtin=True,
                reference_text="哈哈哈哈太有意思了！快来跟我一起玩吧～今天也要元气满满哦！",
                created_at=time.time(),
                updated_at=time.time(),
            ),
            VoicePreset(
                preset_id="yunxi_calm",
                name="沉稳云汐",
                description="沉稳可靠的女声，语速稍慢，语调平稳，让人安心。适合工作讨论、学习辅导、深度思考场景。",
                style="calm",
                gender="female",
                age_range="young_adult",
                language="zh-CN",
                is_builtin=True,
                reference_text="让我们来认真分析一下这个问题。首先，我们需要了解事情的来龙去脉。",
                created_at=time.time(),
                updated_at=time.time(),
            ),
            VoicePreset(
                preset_id="yunxi_professional",
                name="专业云汐",
                description="专业干练的职场女声，语速适中偏快，语调清晰，逻辑感强。适合代码讲解、技术讨论、文档撰写场景。",
                style="professional",
                gender="female",
                age_range="young_adult",
                language="zh-CN",
                is_builtin=True,
                reference_text="这个问题的核心在于算法的时间复杂度。让我来解释一下具体的实现思路。",
                created_at=time.time(),
                updated_at=time.time(),
            ),
            VoicePreset(
                preset_id="yunxi_empathetic",
                name="共情云汐",
                description="温柔共情的女声，语速较慢，语调轻柔，充满理解和关怀。最适合情感陪伴、心理疏导场景。",
                style="empathetic",
                gender="female",
                age_range="young_adult",
                language="zh-CN",
                is_builtin=True,
                reference_text="我理解你的感受。遇到这样的事情确实很难过。没关系，哭出来也没关系，我会一直陪着你。",
                created_at=time.time(),
                updated_at=time.time(),
            ),
        ]
        
        for preset in builtin_presets:
            self._presets[preset.preset_id] = preset
        
        self._active_preset_id = "yunxi_warm"
        self._save_presets()

    # ============================================================
    # 预设管理
    # ============================================================

    def list_presets(self, include_unavailable: bool = True) -> List[VoicePreset]:
        """列出所有音色预设
        
        Args:
            include_unavailable: 是否包含未配置参考音频的预设
        """
        presets = list(self._presets.values())
        if not include_unavailable:
            presets = [p for p in presets if self.is_preset_ready(p.preset_id)]
        
        # 按创建时间排序
        presets.sort(key=lambda p: p.created_at)
        return presets

    def get_preset(self, preset_id: str) -> Optional[VoicePreset]:
        """获取指定音色预设"""
        return self._presets.get(preset_id)

    def get_active_preset(self) -> Optional[VoicePreset]:
        """获取当前激活的音色预设"""
        if self._active_preset_id:
            return self._presets.get(self._active_preset_id)
        return None

    def set_active_preset(self, preset_id: str) -> bool:
        """设置激活的音色预设
        
        Returns:
            是否成功
        """
        if preset_id not in self._presets:
            return False
        
        # 取消当前激活
        if self._active_preset_id and self._active_preset_id in self._presets:
            self._presets[self._active_preset_id].is_active = False
        
        # 设置新激活
        self._presets[preset_id].is_active = True
        self._active_preset_id = preset_id
        self._save_presets()
        return True

    def is_preset_ready(self, preset_id: str) -> bool:
        """检查预设是否已准备就绪（是否有参考音频）"""
        preset = self._presets.get(preset_id)
        if not preset:
            return False
        if preset.reference_audio_path and os.path.exists(preset.reference_audio_path):
            return True
        return False

    # ============================================================
    # 参考音频管理
    # ============================================================

    def set_reference_audio(
        self,
        preset_id: str,
        audio_path: str,
        reference_text: str = "",
    ) -> bool:
        """为预设设置参考音频
        
        Args:
            preset_id: 音色预设ID
            audio_path: 参考音频文件路径（WAV/MP3）
            reference_text: 参考音频对应的文本
        
        Returns:
            是否成功
        """
        preset = self._presets.get(preset_id)
        if not preset:
            return False
        
        if not os.path.exists(audio_path):
            return False
        
        # 复制音频到存储目录
        audio_filename = f"{preset_id}_reference{Path(audio_path).suffix}"
        dest_path = self.audio_dir / audio_filename
        
        try:
            shutil.copy2(audio_path, dest_path)
        except Exception:
            return False
        
        # 更新预设信息
        preset.reference_audio_path = str(dest_path)
        if reference_text:
            preset.reference_text = reference_text
        preset.updated_at = time.time()
        
        # 自动评估质量
        preset.quality_score = self._evaluate_audio_quality(dest_path)
        
        self._save_presets()
        return True

    def add_custom_preset(
        self,
        name: str,
        audio_path: str,
        reference_text: str = "",
        description: str = "",
        style: str = "custom",
    ) -> Optional[VoicePreset]:
        """添加自定义音色预设
        
        Args:
            name: 音色名称
            audio_path: 参考音频路径
            reference_text: 参考音频文本
            description: 音色描述
            style: 风格标签
        
        Returns:
            创建的预设（失败返回 None）
        """
        # 生成唯一ID
        preset_id = f"custom_{int(time.time())}"
        
        preset = VoicePreset(
            preset_id=preset_id,
            name=name,
            description=description,
            style=style,
            reference_text=reference_text,
            is_builtin=False,
            created_at=time.time(),
            updated_at=time.time(),
        )
        
        self._presets[preset_id] = preset
        
        # 设置参考音频
        if not self.set_reference_audio(preset_id, audio_path, reference_text):
            # 设置失败则删除预设
            del self._presets[preset_id]
            return None
        
        return preset

    def delete_preset(self, preset_id: str) -> bool:
        """删除音色预设
        
        内置预设不能删除，只能删除自定义预设。
        """
        preset = self._presets.get(preset_id)
        if not preset:
            return False
        
        if preset.is_builtin:
            return False
        
        # 删除音频文件
        if preset.reference_audio_path and os.path.exists(preset.reference_audio_path):
            try:
                os.unlink(preset.reference_audio_path)
            except Exception as e:
                # 参考音频文件删除失败不影响预设删除本身
                logger.debug("删除参考音频文件失败 %s: %s", preset.reference_audio_path, e)
        
        del self._presets[preset_id]
        
        # 如果删除的是当前激活的，激活第一个可用的
        if self._active_preset_id == preset_id:
            self._active_preset_id = None
            for p in self._presets.values():
                if self.is_preset_ready(p.preset_id):
                    self.set_active_preset(p.preset_id)
                    break
        
        self._save_presets()
        return True

    # ============================================================
    # CosyVoice 服务集成
    # ============================================================

    def register_with_cosyvoice(self, cosyvoice_client) -> Dict[str, bool]:
        """将所有可用预设注册到 CosyVoice 服务
        
        Args:
            cosyvoice_client: CosyVoiceClient 实例
        
        Returns:
            {preset_id: 是否注册成功}
        """
        results = {}
        
        for preset_id, preset in self._presets.items():
            if not self.is_preset_ready(preset_id):
                results[preset_id] = False
                continue
            
            try:
                success = cosyvoice_client.add_speaker(
                    speaker_id=preset_id,
                    reference_audio_path=preset.reference_audio_path,
                    reference_text=preset.reference_text,
                )
                results[preset_id] = success
            except Exception:
                results[preset_id] = False
        
        return results

    def get_synthesis_params(self, preset_id: Optional[str] = None) -> Dict[str, Any]:
        """获取语音合成参数（供 TTSEngine 使用）
        
        Args:
            preset_id: 音色预设ID（不指定则使用当前激活的）
        
        Returns:
            合成参数字典
        """
        if preset_id is None:
            preset = self.get_active_preset()
        else:
            preset = self.get_preset(preset_id)
        
        if preset is None:
            return {}
        
        return {
            'speaker_id': preset.preset_id if self.is_preset_ready(preset.preset_id) else None,
            'reference_audio': preset.reference_audio_path,
            'reference_text': preset.reference_text,
            'style': preset.style,
            'preset_name': preset.name,
        }

    # ============================================================
    # 音频质量评估
    # ============================================================

    def _evaluate_audio_quality(self, audio_path: str) -> float:
        """简单评估参考音频质量
        
        实际生产环境应使用更专业的音频质量评估模型。
        这里只做基础检查：文件大小、时长、格式等。
        """
        try:
            if not os.path.exists(audio_path):
                return 0.0
            
            file_size = os.path.getsize(audio_path)
            
            # 文件大小评分（100KB - 5MB 为最佳）
            size_kb = file_size / 1024
            if size_kb < 10:
                size_score = 20  # 太小可能质量差
            elif size_kb < 100:
                size_score = 60
            elif size_kb < 5120:  # 5MB
                size_score = 100
            elif size_kb < 20480:  # 20MB
                size_score = 80
            else:
                size_score = 60  # 太大可能加载慢
            
            # 文件格式评分
            ext = Path(audio_path).suffix.lower()
            format_scores = {'.wav': 100, '.flac': 100, '.mp3': 80, '.m4a': 70, '.ogg': 70}
            format_score = format_scores.get(ext, 50)
            
            # 综合评分
            total_score = size_score * 0.6 + format_score * 0.4
            return round(total_score, 1)
            
        except Exception:
            return 0.0

    # ============================================================
    # 持久化
    # ============================================================

    def _load_presets(self):
        """从文件加载预设"""
        if not self.presets_file.exists():
            return
        
        try:
            with open(self.presets_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
            
            for preset_data in data.get('presets', []):
                preset = VoicePreset.from_dict(preset_data)
                self._presets[preset.preset_id] = preset
            
            self._active_preset_id = data.get('active_preset_id')
            
        except Exception:
            # 加载失败则重新初始化
            self._presets = {}
            self._active_preset_id = None

    def _save_presets(self):
        """保存预设到文件"""
        data = {
            'version': '1.0',
            'active_preset_id': self._active_preset_id,
            'presets': [p.to_dict() for p in self._presets.values()],
        }
        
        try:
            with open(self.presets_file, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            # 预设持久化失败不影响运行时功能，但重启后配置会丢失
            logger.warning("保存音色预设失败 %s: %s", self.presets_file, e)

    # ============================================================
    # 场景-音色关联
    # ============================================================

    def get_preset_for_scene(self, scene: str) -> Optional[VoicePreset]:
        """根据场景推荐音色
        
        Args:
            scene: 场景类型（work_dev/emotion_companion 等）
        
        Returns:
            推荐的音色预设
        """
        # 场景到风格的映射
        scene_style_map = {
            'work_dev': 'professional',
            'study_plan': 'calm',
            'review_summary': 'calm',
            'relationship': 'empathetic',
            'emotion_companion': 'warm',
            'life_management': 'warm',
            'entertainment': 'playful',
        }
        
        target_style = scene_style_map.get(scene, 'warm')
        
        # 优先找匹配风格且已就绪的预设
        for preset in self._presets.values():
            if preset.style == target_style and self.is_preset_ready(preset.preset_id):
                return preset
        
        # 其次找当前激活的
        active = self.get_active_preset()
        if active and self.is_preset_ready(active.preset_id):
            return active
        
        # 最后找第一个已就绪的
        for preset in self._presets.values():
            if self.is_preset_ready(preset.preset_id):
                return preset
        
        return None


# ============================================================
# 便捷函数
# ============================================================

_default_manager: Optional[VoicePresetManager] = None


def get_voice_preset_manager(storage_dir: Optional[str] = None) -> VoicePresetManager:
    """获取全局音色预设管理器（单例）"""
    global _default_manager
    if _default_manager is None or storage_dir is not None:
        _default_manager = VoicePresetManager(storage_dir)
    return _default_manager
