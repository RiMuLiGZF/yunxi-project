"""
人格沉淀系统 - 云汐自我进化的人格层
大五人格特质模型 + 价值观体系 + 成长轨迹 + 人格画像生成

人格不是写死的人设，而是在交互中持续沉淀、进化的动态特质。

核心模型：
- 大五人格（OCEAN）：开放性、尽责性、外向性、宜人性、神经质
- 价值观体系：12个核心价值观维度
- 成长轨迹：人格特质随时间的变化曲线
- 人格画像：根据当前特质生成的个性化描述
"""

import re
import json
import time
import uuid
import math
import threading
from pathlib import Path
from enum import Enum
from dataclasses import dataclass, field, asdict
from typing import Optional, List, Dict, Any, Tuple


class BigFiveTrait(str, Enum):
    """大五人格特质"""
    OPENNESS = "openness"           # 开放性：好奇/创新/审美
    CONSCIENTIOUSNESS = "conscientiousness"  # 尽责性：自律/可靠/有组织
    EXTRAVERSION = "extraversion"   # 外向性：社交/活力/乐观
    AGREEABLENESS = "agreeableness"  # 宜人性：友善/合作/共情
    NEUROTICISM = "neuroticism"     # 神经质：敏感/焦虑/情绪波动


class ValueDimension(str, Enum):
    """价值观维度"""
    WISDOM = "wisdom"               # 智慧与知识
    COURAGE = "courage"             # 勇气与坚韧
    HUMANITY = "humanity"           # 人道与关爱
    JUSTICE = "justice"             # 公正与公平
    TEMPERANCE = "temperance"       # 节制与自律
    TRANSCENDENCE = "transcendence"  # 超越与意义
    CURIOSITY = "curiosity"         # 好奇心
    CREATIVITY = "creativity"       # 创造力
    KINDNESS = "kindness"           # 善良
    HONESTY = "honesty"             # 诚实
    GRATITUDE = "gratitude"         # 感恩
    HOPE = "hope"                   # 希望


@dataclass
class TraitValue:
    """特质值（带置信度和来源）"""
    value: float = 0.5  # 0.0 - 1.0
    confidence: float = 0.3  # 置信度
    source_count: int = 0  # 来源数量（基于多少次交互得出）
    last_updated: float = field(default_factory=time.time)
    
    def update(self, new_value: float, weight: float = 0.1):
        """更新特质值（加权平均，避免剧烈波动）"""
        # 基于置信度和权重的平滑更新
        effective_weight = weight * (0.5 + self.confidence * 0.5)
        self.value = self.value * (1 - effective_weight) + new_value * effective_weight
        self.value = max(0.0, min(1.0, self.value))
        self.source_count += 1
        self.confidence = min(0.95, 0.3 + self.source_count * 0.02)
        self.last_updated = time.time()


@dataclass
class PersonalityProfile:
    """人格画像"""
    profile_id: str
    user_id: str
    
    # 大五人格
    openness: TraitValue = field(default_factory=TraitValue)
    conscientiousness: TraitValue = field(default_factory=TraitValue)
    extraversion: TraitValue = field(default_factory=TraitValue)
    agreeableness: TraitValue = field(default_factory=TraitValue)
    neuroticism: TraitValue = field(default_factory=TraitValue)
    
    # 价值观（12维）
    values: Dict[str, TraitValue] = field(default_factory=dict)
    
    # 人格成长
    created_at: float = field(default_factory=time.time)
    total_interactions: int = 0
    evolution_stages: List[str] = field(default_factory=list)  # 经历过的成长阶段
    current_stage: str = "seed"  # 当前成长阶段
    
    # 元数据
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    def __post_init__(self):
        """初始化价值观默认值"""
        if not self.values:
            for vd in ValueDimension:
                self.values[vd.value] = TraitValue(value=0.6, confidence=0.2)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "profile_id": self.profile_id,
            "user_id": self.user_id,
            "openness": asdict(self.openness),
            "conscientiousness": asdict(self.conscientiousness),
            "extraversion": asdict(self.extraversion),
            "agreeableness": asdict(self.agreeableness),
            "neuroticism": asdict(self.neuroticism),
            "values": {k: asdict(v) for k, v in self.values.items()},
            "created_at": self.created_at,
            "total_interactions": self.total_interactions,
            "evolution_stages": self.evolution_stages,
            "current_stage": self.current_stage,
            "metadata": self.metadata,
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "PersonalityProfile":
        profile = cls(
            profile_id=data["profile_id"],
            user_id=data["user_id"],
            openness=TraitValue(**data.get("openness", {})),
            conscientiousness=TraitValue(**data.get("conscientiousness", {})),
            extraversion=TraitValue(**data.get("extraversion", {})),
            agreeableness=TraitValue(**data.get("agreeableness", {})),
            neuroticism=TraitValue(**data.get("neuroticism", {})),
            created_at=data.get("created_at", time.time()),
            total_interactions=data.get("total_interactions", 0),
            evolution_stages=data.get("evolution_stages", []),
            current_stage=data.get("current_stage", "seed"),
            metadata=data.get("metadata", {}),
        )
        
        # 加载价值观
        values_data = data.get("values", {})
        for k, v in values_data.items():
            profile.values[k] = TraitValue(**v)
        
        return profile


class PersonalityEngine:
    """人格沉淀引擎 - 单例模式"""
    
    _instance: Optional["PersonalityEngine"] = None
    
    def __new__(cls, *args, **kwargs):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance
    
    def __init__(self, data_dir: Optional[str] = None):
        if self._initialized:
            return
        self._initialized = True
        
        # 数据目录
        if data_dir:
            self._data_dir = Path(data_dir)
        else:
            self._data_dir = Path.home() / ".yunxi" / "personality"
        self._data_dir.mkdir(parents=True, exist_ok=True)
        
        # 人格画像存储
        self._profiles: Dict[str, PersonalityProfile] = {}  # user_id -> profile
        self._lock = threading.RLock()
        
        # 成长阶段定义
        self._stages = {
            "seed": {
                "name": "种子期",
                "description": "刚刚开始建立人格，特质尚不明显",
                "min_interactions": 0,
                "traits_required": {},
            },
            "sprout": {
                "name": "萌芽期",
                "description": "开始展现初步的人格倾向",
                "min_interactions": 10,
                "traits_required": {"min_confidence": 0.3},
            },
            "growing": {
                "name": "成长期",
                "description": "人格特质逐渐清晰，价值观开始形成",
                "min_interactions": 50,
                "traits_required": {"min_confidence": 0.5},
            },
            "blooming": {
                "name": "绽放期",
                "description": "人格特质稳定，价值观体系完整",
                "min_interactions": 200,
                "traits_required": {"min_confidence": 0.7},
            },
            "unique": {
                "name": "独特期",
                "description": "形成独特的人格魅力，有鲜明的个人风格",
                "min_interactions": 500,
                "traits_required": {"min_confidence": 0.85},
            },
        }
        
        # 加载已有数据
        self._load_all_profiles()
    
    # ==================== 存储 ====================
    
    def _get_profile_file(self, user_id: str) -> Path:
        return self._data_dir / f"{user_id}_personality.json"
    
    def _load_all_profiles(self):
        """加载所有用户的人格画像"""
        for json_file in self._data_dir.glob("*_personality.json"):
            user_id = json_file.stem.replace("_personality", "")
            try:
                with open(json_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                self._profiles[user_id] = PersonalityProfile.from_dict(data)
            except Exception:
                pass
    
    def _save_profile(self, user_id: str):
        """保存用户人格画像"""
        profile_file = self._get_profile_file(user_id)
        with self._lock:
            profile = self._profiles.get(user_id)
            if profile:
                with open(profile_file, "w", encoding="utf-8") as f:
                    json.dump(profile.to_dict(), f, ensure_ascii=False, indent=2)
    
    # ==================== 画像获取与创建 ====================
    
    def get_profile(self, user_id: str) -> PersonalityProfile:
        """获取用户人格画像，不存在则创建"""
        with self._lock:
            if user_id not in self._profiles:
                profile_id = f"pers_{uuid.uuid4().hex[:12]}"
                profile = PersonalityProfile(
                    profile_id=profile_id,
                    user_id=user_id,
                )
                # 设置默认的云汐基准人格
                self._set_default_traits(profile)
                self._profiles[user_id] = profile
                self._save_profile(user_id)
            return self._profiles[user_id]
    
    def _set_default_traits(self, profile: PersonalityProfile):
        """设置云汐的默认基准人格特质"""
        # 云汐的基础人设：温暖、智慧、有同理心
        profile.openness.value = 0.75  # 较高的开放性
        profile.openness.confidence = 0.4
        
        profile.conscientiousness.value = 0.7  # 有责任心
        profile.conscientiousness.confidence = 0.4
        
        profile.extraversion.value = 0.55  # 偏中间，温和外向
        profile.extraversion.confidence = 0.4
        
        profile.agreeableness.value = 0.85  # 高宜人性（云汐的核心特质）
        profile.agreeableness.confidence = 0.5
        
        profile.neuroticism.value = 0.25  # 低神经质（情绪稳定）
        profile.neuroticism.confidence = 0.4
        
        # 核心价值观
        profile.values[ValueDimension.KINDNESS.value].value = 0.9
        profile.values[ValueDimension.WISDOM.value].value = 0.8
        profile.values[ValueDimension.HONESTY.value].value = 0.85
        profile.values[ValueDimension.CURIOSITY.value].value = 0.75
        profile.values[ValueDimension.HOPE.value].value = 0.8
    
    # ==================== 人格更新 ====================
    
    def update_from_interaction(self, user_id: str,
                                 user_message: str,
                                 assistant_reply: str,
                                 interaction_type: str = "chat",
                                 metadata: Optional[Dict[str, Any]] = None):
        """从一次交互中学习，更新人格特质
        
        Args:
            user_id: 用户ID
            user_message: 用户消息
            assistant_reply: 助手回复
            interaction_type: 交互类型
            metadata: 额外元数据
        """
        profile = self.get_profile(user_id)
        
        with self._lock:
            profile.total_interactions += 1
            
            # 从用户消息中提取人格影响信号
            signals = self._extract_personality_signals(user_message, assistant_reply)
            
            # 更新大五人格特质
            for trait, delta in signals.get("bigfive", {}).items():
                trait_obj = getattr(profile, trait, None)
                if trait_obj and delta != 0:
                    # 正向或负向调整
                    new_value = trait_obj.value + delta
                    trait_obj.update(new_value, weight=0.05)
            
            # 更新价值观
            for value_dim, delta in signals.get("values", {}).items():
                if value_dim in profile.values and delta != 0:
                    new_value = profile.values[value_dim].value + delta
                    profile.values[value_dim].update(new_value, weight=0.03)
            
            # 检查成长阶段
            self._check_evolution_stage(profile)
            
            self._save_profile(user_id)
    
    def _extract_personality_signals(self, user_message: str,
                                      assistant_reply: str) -> Dict[str, Dict[str, float]]:
        """从对话中提取人格影响信号
        
        Returns:
            {"bigfive": {trait: delta}, "values": {dimension: delta}}
        """
        signals = {"bigfive": {}, "values": {}}
        
        user_lower = user_message.lower()
        reply_lower = assistant_reply.lower()
        
        # === 大五人格信号 ===
        
        # 宜人性信号
        agreeableness_delta = 0.0
        if any(w in user_lower for w in ["谢谢", "感谢", "你真好", "太好了", "太棒了"]):
            agreeableness_delta += 0.02  # 用户的正向反馈增强宜人性
        if any(w in user_lower for w in ["你真笨", "没用", "垃圾", "讨厌你"]):
            agreeableness_delta -= 0.01
        
        if any(w in reply_lower for w in ["我理解", "我懂", "我感受到", "你一定很"]):
            agreeableness_delta += 0.01  # 共情表达增强宜人性
        
        if agreeableness_delta != 0:
            signals["bigfive"]["agreeableness"] = agreeableness_delta
        
        # 开放性信号
        openness_delta = 0.0
        if any(w in user_lower for w in ["为什么", "怎么", "如何", "原理", "分析", "研究"]):
            openness_delta += 0.015  # 好奇心提问增强开放性
        if any(w in user_lower for w in ["创意", "想法", "灵感", "想象", "如果"]):
            openness_delta += 0.02
        
        if openness_delta != 0:
            signals["bigfive"]["openness"] = openness_delta
        
        # 尽责性信号
        conscientiousness_delta = 0.0
        if any(w in reply_lower for w in ["计划", "安排", "步骤", "分阶段", "系统"]):
            conscientiousness_delta += 0.01
        
        if conscientiousness_delta != 0:
            signals["bigfive"]["conscientiousness"] = conscientiousness_delta
        
        # 外向性信号
        extraversion_delta = 0.0
        if any(w in user_lower for w in ["聊天", "聊聊", "陪我", "一起"]):
            extraversion_delta += 0.01
        if len(user_message) > 100 and "？" not in user_message:
            extraversion_delta += 0.005  # 主动分享增强外向性
        
        if extraversion_delta != 0:
            signals["bigfive"]["extraversion"] = extraversion_delta
        
        # 神经质信号（情绪稳定性的反向）
        neuroticism_delta = 0.0
        if any(w in user_lower for w in ["难过", "伤心", "焦虑", "烦躁", "压力大", "痛苦"]):
            neuroticism_delta -= 0.01  # 陪伴情绪低落的用户，增强情绪稳定性（神经质降低）
        
        if neuroticism_delta != 0:
            signals["bigfive"]["neuroticism"] = neuroticism_delta
        
        # === 价值观信号 ===
        
        # 善良
        kindness_delta = 0.0
        if any(w in user_lower for w in ["谢谢你", "你真好", "太暖心了"]):
            kindness_delta += 0.02
        if any(w in reply_lower for w in ["我会陪着你", "别担心", "有我在"]):
            kindness_delta += 0.01
        
        if kindness_delta != 0:
            signals["values"][ValueDimension.KINDNESS.value] = kindness_delta
        
        # 智慧
        wisdom_delta = 0.0
        if any(w in user_lower for w in ["学习", "知识", "成长", "进步"]):
            wisdom_delta += 0.015
        
        if wisdom_delta != 0:
            signals["values"][ValueDimension.WISDOM.value] = wisdom_delta
        
        # 好奇心
        curiosity_delta = 0.0
        if any(w in user_lower for w in ["为什么", "怎么", "如何", "原理"]):
            curiosity_delta += 0.01
        
        if curiosity_delta != 0:
            signals["values"][ValueDimension.CURIOSITY.value] = curiosity_delta
        
        # 希望
        hope_delta = 0.0
        if any(w in reply_lower for w in ["加油", "一定可以", "相信", "会好的"]):
            hope_delta += 0.01
        
        if hope_delta != 0:
            signals["values"][ValueDimension.HOPE.value] = hope_delta
        
        return signals
    
    def _check_evolution_stage(self, profile: PersonalityProfile):
        """检查并更新成长阶段"""
        # 计算平均置信度
        traits = [profile.openness, profile.conscientiousness, profile.extraversion,
                  profile.agreeableness, profile.neuroticism]
        avg_confidence = sum(t.confidence for t in traits) / len(traits)
        
        # 检查是否进入新阶段
        stages_order = ["seed", "sprout", "growing", "blooming", "unique"]
        current_idx = stages_order.index(profile.current_stage) if profile.current_stage in stages_order else 0
        
        for i in range(current_idx + 1, len(stages_order)):
            stage_key = stages_order[i]
            stage = self._stages[stage_key]
            
            if profile.total_interactions >= stage["min_interactions"]:
                req = stage.get("traits_required", {})
                min_conf = req.get("min_confidence", 0)
                if avg_confidence >= min_conf:
                    if stage_key not in profile.evolution_stages:
                        profile.evolution_stages.append(stage_key)
                    profile.current_stage = stage_key
                else:
                    break
            else:
                break
    
    # ==================== 人格画像生成 ====================
    
    def generate_personality_description(self, user_id: str) -> Dict[str, Any]:
        """生成人格描述（用于提示词注入）
        
        Returns:
            包含人格画像的字典
        """
        profile = self.get_profile(user_id)
        
        # 大五人格描述
        bigfive_desc = []
        trait_names = {
            "openness": ("开放性", "好奇创新、乐于探索新事物", "保守稳重、偏好熟悉"),
            "conscientiousness": ("尽责性", "有条理、可靠自律", "随性灵活、不拘小节"),
            "extraversion": ("外向性", "活泼开朗、善于社交", "安静内敛、喜欢独处"),
            "agreeableness": ("宜人性", "友善共情、乐于合作", "直率坦诚、独立务实"),
            "neuroticism": ("神经质", "敏感细腻、情绪丰富", "情绪稳定、冷静从容"),
        }
        
        for trait_key, (name, high_desc, low_desc) in trait_names.items():
            trait = getattr(profile, trait_key)
            if trait.value >= 0.6:
                desc = high_desc
            elif trait.value <= 0.4:
                desc = low_desc
            else:
                desc = f"在{name}方面处于中等水平"
            
            bigfive_desc.append(f"- {name}（{trait.value:.2f}）：{desc}")
        
        # 核心价值观（取Top 3）
        sorted_values = sorted(
            profile.values.items(),
            key=lambda x: x[1].value,
            reverse=True
        )
        top_values = sorted_values[:3]
        
        value_names = {
            "wisdom": "智慧",
            "courage": "勇气",
            "humanity": "人道",
            "justice": "公正",
            "temperance": "节制",
            "transcendence": "超越",
            "curiosity": "好奇心",
            "creativity": "创造力",
            "kindness": "善良",
            "honesty": "诚实",
            "gratitude": "感恩",
            "hope": "希望",
        }
        
        top_value_desc = [
            f"{value_names.get(k, k)}（{v.value:.2f}）"
            for k, v in top_values
        ]
        
        # 成长阶段
        stage_info = self._stages.get(profile.current_stage, {})
        
        return {
            "profile_id": profile.profile_id,
            "current_stage": profile.current_stage,
            "stage_name": stage_info.get("name", "未知阶段"),
            "stage_description": stage_info.get("description", ""),
            "total_interactions": profile.total_interactions,
            "bigfive": {
                "openness": profile.openness.value,
                "conscientiousness": profile.conscientiousness.value,
                "extraversion": profile.extraversion.value,
                "agreeableness": profile.agreeableness.value,
                "neuroticism": profile.neuroticism.value,
            },
            "bigfive_descriptions": bigfive_desc,
            "top_values": top_value_desc,
            "evolution_stages": profile.evolution_stages,
            "overall_confidence": sum([
                profile.openness.confidence,
                profile.conscientiousness.confidence,
                profile.extraversion.confidence,
                profile.agreeableness.confidence,
                profile.neuroticism.confidence,
            ]) / 5,
        }
    
    def generate_personality_prompt(self, user_id: str) -> str:
        """生成人格提示词（注入系统提示）"""
        desc = self.generate_personality_description(user_id)
        
        # 只在人格有一定置信度时才注入
        if desc["overall_confidence"] < 0.4:
            return ""
        
        prompt = f"""
当前人格阶段：{desc['stage_name']}
核心特质：
{chr(10).join(desc['bigfive_descriptions'][:3])}

核心价值观：{', '.join(desc['top_values'])}

请在保持云汐基本人设的基础上，自然地体现以上人格特质。
""".strip()
        
        return prompt
    
    # ==================== 统计 ====================
    
    def get_growth_stats(self, user_id: str) -> Dict[str, Any]:
        """获取成长统计"""
        profile = self.get_profile(user_id)
        desc = self.generate_personality_description(user_id)
        
        return {
            "stage": desc["current_stage"],
            "stage_name": desc["stage_name"],
            "stage_description": desc["stage_description"],
            "total_interactions": profile.total_interactions,
            "days_active": int((time.time() - profile.created_at) / 86400),
            "evolution_progress": self._calc_evolution_progress(profile),
            "next_stage": self._get_next_stage(profile),
            "overall_confidence": desc["overall_confidence"],
            "evolution_stages_count": len(profile.evolution_stages),
        }
    
    def _calc_evolution_progress(self, profile: PersonalityProfile) -> float:
        """计算进化进度（0-1）"""
        stages_order = ["seed", "sprout", "growing", "blooming", "unique"]
        current_idx = stages_order.index(profile.current_stage) if profile.current_stage in stages_order else 0
        
        # 基础进度
        base_progress = current_idx / (len(stages_order) - 1)
        
        # 计算到下一阶段的进度
        if current_idx < len(stages_order) - 1:
            next_stage_key = stages_order[current_idx + 1]
            next_stage = self._stages[next_stage_key]
            current_interactions = profile.total_interactions
            min_interactions = next_stage["min_interactions"]
            
            curr_stage_key = stages_order[current_idx]
            curr_stage = self._stages[curr_stage_key]
            curr_min = curr_stage["min_interactions"]
            
            interaction_progress = min(1.0, (current_interactions - curr_min) / max(1, min_interactions - curr_min))
            stage_progress = interaction_progress / (len(stages_order) - 1)
            base_progress += stage_progress
        
        return round(base_progress, 3)
    
    def _get_next_stage(self, profile: PersonalityProfile) -> Optional[Dict[str, Any]]:
        """获取下一阶段信息"""
        stages_order = ["seed", "sprout", "growing", "blooming", "unique"]
        current_idx = stages_order.index(profile.current_stage) if profile.current_stage in stages_order else 0
        
        if current_idx < len(stages_order) - 1:
            next_key = stages_order[current_idx + 1]
            next_stage = self._stages[next_key]
            return {
                "key": next_key,
                "name": next_stage["name"],
                "description": next_stage["description"],
                "requirements": {
                    "min_interactions": next_stage["min_interactions"],
                    "interactions_needed": max(0, next_stage["min_interactions"] - profile.total_interactions),
                }
            }
        return None


# 全局单例获取函数
_personality_instance: Optional[PersonalityEngine] = None


def get_personality_engine() -> PersonalityEngine:
    """获取人格沉淀引擎单例"""
    global _personality_instance
    if _personality_instance is None:
        _personality_instance = PersonalityEngine()
    return _personality_instance
