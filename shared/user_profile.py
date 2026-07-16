"""
用户画像与偏好学习引擎

功能：
1. 用户画像构建（基础属性 + 行为特征 + 偏好标签）
2. 交互记忆与偏好学习（基于历史对话自动学习用户习惯）
3. 个性化推荐（根据用户偏好调整回复风格、内容深度、TTS音色等）
4. 多用户支持（不同用户独立画像）
"""

import json
import time
import threading
from pathlib import Path
from typing import Dict, List, Optional, Any, Tuple
from dataclasses import dataclass, field, asdict
from collections import defaultdict
from enum import Enum


class PreferenceCategory(str, Enum):
    """偏好类别"""
    COMMUNICATION_STYLE = "communication_style"  # 沟通风格
    CONTENT_DEPTH = "content_depth"  # 内容深度
    VOICE = "voice"  # 语音偏好
    TOPIC_INTEREST = "topic_interest"  # 话题兴趣
    LANGUAGE = "language"  # 语言偏好
    VISUAL = "visual"  # 视觉偏好
    HABIT = "habit"  # 使用习惯


class InteractionType(str, Enum):
    """交互类型"""
    TEXT_CHAT = "text_chat"
    VOICE_CHAT = "voice_chat"
    COMMAND = "command"
    QUESTION = "question"
    FEEDBACK = "feedback"


@dataclass
class UserPreference:
    """用户偏好项"""
    category: str  # 偏好类别
    key: str  # 偏好键
    value: Any  # 偏好值
    confidence: float = 0.5  # 置信度 0-1
    count: int = 1  # 出现次数
    first_seen: float = field(default_factory=time.time)
    last_seen: float = field(default_factory=time.time)
    source: str = "inferred"  # explicit(用户明确设置) / inferred(系统推断)
    
    def update(self, value: Any, source: str = "inferred"):
        """更新偏好值"""
        self.value = value
        self.count += 1
        self.last_seen = time.time()
        self.source = source
        # 置信度随次数增加（上限0.95）
        self.confidence = min(0.95, 0.5 + 0.1 * (self.count - 1))


@dataclass
class UserProfile:
    """用户画像"""
    user_id: str
    nickname: str = "用户"
    avatar: str = ""
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    
    # 基础属性
    age: Optional[int] = None
    gender: Optional[str] = None
    location: Optional[str] = None
    language: str = "zh-CN"
    
    # 偏好存储（按类别分组）
    preferences: Dict[str, Dict[str, UserPreference]] = field(default_factory=dict)
    
    # 交互统计
    interaction_stats: Dict[str, Any] = field(default_factory=lambda: {
        "total_messages": 0,
        "voice_messages": 0,
        "text_messages": 0,
        "avg_response_length": 0,
        "active_hours": defaultdict(int),
        "common_topics": defaultdict(int),
        "command_usage": defaultdict(int),
    })
    
    # 最近交互记录（用于短期记忆）
    recent_interactions: List[Dict[str, Any]] = field(default_factory=list)
    max_recent: int = 50
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        # 手动构建字典，避免 asdict 处理 defaultdict 时出错
        data = {
            "user_id": self.user_id,
            "nickname": self.nickname,
            "avatar": self.avatar,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "age": self.age,
            "gender": self.gender,
            "location": self.location,
            "language": self.language,
            "max_recent": self.max_recent,
        }
        # 处理嵌套的 UserPreference
        prefs = {}
        for cat, items in self.preferences.items():
            prefs[cat] = {k: asdict(v) for k, v in items.items()}
        data["preferences"] = prefs
        # 处理 defaultdict
        stats = dict(self.interaction_stats)
        stats["active_hours"] = dict(stats.get("active_hours", {}))
        stats["common_topics"] = dict(stats.get("common_topics", {}))
        stats["command_usage"] = dict(stats.get("command_usage", {}))
        data["interaction_stats"] = stats
        # 最近交互记录
        data["recent_interactions"] = self.recent_interactions
        return data
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "UserProfile":
        """从字典创建"""
        profile = cls(user_id=data["user_id"])
        for key, value in data.items():
            if key == "preferences":
                profile.preferences = {}
                for cat, items in value.items():
                    profile.preferences[cat] = {
                        k: UserPreference(**v) for k, v in items.items()
                    }
            elif key == "interaction_stats":
                profile.interaction_stats = value
                # 恢复 defaultdict
                profile.interaction_stats["active_hours"] = defaultdict(int, value.get("active_hours", {}))
                profile.interaction_stats["common_topics"] = defaultdict(int, value.get("common_topics", {}))
                profile.interaction_stats["command_usage"] = defaultdict(int, value.get("command_usage", {}))
            elif key == "recent_interactions":
                profile.recent_interactions = value
            elif hasattr(profile, key):
                setattr(profile, key, value)
        return profile


class UserProfileManager:
    """用户画像管理器 - 单例模式"""
    
    _instance: Optional["UserProfileManager"] = None
    
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
            self._data_dir = Path.home() / ".yunxi" / "user_profiles"
        self._data_dir.mkdir(parents=True, exist_ok=True)
        
        # 用户画像缓存
        self._profiles: Dict[str, UserProfile] = {}
        self._lock = threading.RLock()
        
        # 偏好学习配置
        self._learning_config = {
            "min_occurrences": 3,  # 最少出现次数才形成偏好
            "confidence_decay_days": 30,  # 置信度衰减天数
            "max_preferences_per_category": 20,  # 每类最多偏好数
        }
        
        # 加载已有用户
        self._load_all_profiles()
        
        # 默认用户
        self._default_user_id = "default"
        if self._default_user_id not in self._profiles:
            self.create_profile(self._default_user_id, "默认用户")
    
    def _load_all_profiles(self):
        """加载所有用户画像"""
        try:
            for file in self._data_dir.glob("*.json"):
                try:
                    with open(file, "r", encoding="utf-8") as f:
                        data = json.load(f)
                    profile = UserProfile.from_dict(data)
                    self._profiles[profile.user_id] = profile
                except Exception:
                    continue
        except Exception:
            pass
    
    def _save_profile(self, profile: UserProfile):
        """保存用户画像到文件"""
        try:
            profile.updated_at = time.time()
            file_path = self._data_dir / f"{profile.user_id}.json"
            with open(file_path, "w", encoding="utf-8") as f:
                json.dump(profile.to_dict(), f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"保存用户画像失败: {e}")
    
    def create_profile(self, user_id: str, nickname: str = "", **kwargs) -> UserProfile:
        """创建用户画像"""
        with self._lock:
            if user_id in self._profiles:
                return self._profiles[user_id]
            
            profile = UserProfile(user_id=user_id, nickname=nickname or user_id)
            for key, value in kwargs.items():
                if hasattr(profile, key):
                    setattr(profile, key, value)
            
            self._profiles[user_id] = profile
            self._save_profile(profile)
            return profile
    
    def get_profile(self, user_id: Optional[str] = None) -> UserProfile:
        """获取用户画像"""
        user_id = user_id or self._default_user_id
        with self._lock:
            if user_id not in self._profiles:
                return self.create_profile(user_id)
            return self._profiles[user_id]
    
    def set_preference(self, user_id: str, category: str, key: str, value: Any, 
                       source: str = "explicit"):
        """设置用户偏好（显式设置）"""
        profile = self.get_profile(user_id)
        
        with self._lock:
            if category not in profile.preferences:
                profile.preferences[category] = {}
            
            if key in profile.preferences[category]:
                pref = profile.preferences[category][key]
                pref.value = value
                pref.source = source
                pref.confidence = 1.0 if source == "explicit" else pref.confidence
                pref.last_seen = time.time()
                pref.count += 1
            else:
                profile.preferences[category][key] = UserPreference(
                    category=category,
                    key=key,
                    value=value,
                    confidence=1.0 if source == "explicit" else 0.5,
                    source=source,
                )
            
            self._save_profile(profile)
    
    def get_preference(self, user_id: str, category: str, key: str, 
                       default: Any = None) -> Tuple[Any, float]:
        """获取用户偏好值和置信度"""
        profile = self.get_profile(user_id)
        
        with self._lock:
            cat_prefs = profile.preferences.get(category, {})
            if key in cat_prefs:
                pref = cat_prefs[key]
                return pref.value, pref.confidence
            return default, 0.0
    
    def get_all_preferences(self, user_id: str, category: Optional[str] = None) -> Dict[str, Any]:
        """获取所有偏好（可按类别筛选）"""
        profile = self.get_profile(user_id)
        
        with self._lock:
            result = {}
            if category:
                cat_prefs = profile.preferences.get(category, {})
                for k, v in cat_prefs.items():
                    result[k] = {"value": v.value, "confidence": v.confidence, "source": v.source}
            else:
                for cat, items in profile.preferences.items():
                    result[cat] = {}
                    for k, v in items.items():
                        result[cat][k] = {"value": v.value, "confidence": v.confidence, "source": v.source}
            return result
    
    def record_interaction(self, user_id: str, interaction_type: str, 
                           content: Optional[str] = None, metadata: Optional[Dict] = None):
        """记录用户交互（用于偏好学习）"""
        profile = self.get_profile(user_id)
        
        with self._lock:
            stats = profile.interaction_stats
            stats["total_messages"] += 1
            
            # 按类型统计
            if interaction_type == InteractionType.VOICE_CHAT:
                stats["voice_messages"] += 1
            else:
                stats["text_messages"] += 1
            
            # 活跃时段统计
            hour = time.localtime().tm_hour
            stats["active_hours"][hour] += 1
            
            # 命令使用统计
            if metadata and "command" in metadata:
                stats["command_usage"][metadata["command"]] += 1
            
            # 话题统计
            if metadata and "topics" in metadata:
                for topic in metadata["topics"]:
                    stats["common_topics"][topic] += 1
            
            # 最近交互记录
            profile.recent_interactions.append({
                "type": interaction_type,
                "content": content[:200] if content else "",
                "timestamp": time.time(),
                "metadata": metadata or {},
            })
            
            # 限制最近记录数量
            if len(profile.recent_interactions) > profile.max_recent:
                profile.recent_interactions = profile.recent_interactions[-profile.max_recent:]
            
            self._save_profile(profile)
    
    def learn_from_interaction(self, user_id: str, message: str, response: str,
                               feedback: Optional[str] = None):
        """从交互中学习用户偏好"""
        profile = self.get_profile(user_id)
        
        with self._lock:
            # 1. 学习沟通风格偏好
            self._learn_communication_style(profile, message, response, feedback)
            
            # 2. 学习内容深度偏好
            self._learn_content_depth(profile, message, response)
            
            # 3. 学习话题兴趣
            self._learn_topic_interest(profile, message)
            
            self._save_profile(profile)
    
    def _learn_communication_style(self, profile: UserProfile, message: str, 
                                    response: str, feedback: Optional[str]):
        """学习沟通风格偏好"""
        category = PreferenceCategory.COMMUNICATION_STYLE.value
        
        if category not in profile.preferences:
            profile.preferences[category] = {}
        
        # 分析用户消息的正式程度
        formality_score = self._analyze_formality(message)
        
        # 分析用户消息的长度偏好
        length_preference = "concise" if len(message) < 50 else "detailed"
        
        # 更新偏好
        prefs = profile.preferences[category]
        
        # 正式程度偏好
        if "formality" in prefs:
            prefs["formality"].update(formality_score)
        else:
            prefs["formality"] = UserPreference(
                category=category,
                key="formality",
                value=formality_score,
                confidence=0.3,
            )
        
        # 长度偏好
        if "length_preference" in prefs:
            prefs["length_preference"].update(length_preference)
        else:
            prefs["length_preference"] = UserPreference(
                category=category,
                key="length_preference",
                value=length_preference,
                confidence=0.3,
            )
    
    def _learn_content_depth(self, profile: UserProfile, message: str, response: str):
        """学习内容深度偏好"""
        category = PreferenceCategory.CONTENT_DEPTH.value
        
        if category not in profile.preferences:
            profile.preferences[category] = {}
        
        # 基于问题关键词推断深度偏好
        deep_keywords = ["为什么", "原理", "详细", "深入", "解释一下", "怎么实现", "底层"]
        shallow_keywords = ["简单说", "概括", "总结", "一句话", "大概"]
        
        message_lower = message.lower()
        deep_count = sum(1 for k in deep_keywords if k in message_lower)
        shallow_count = sum(1 for k in shallow_keywords if k in message_lower)
        
        if deep_count > shallow_count:
            depth = "deep"
        elif shallow_count > deep_count:
            depth = "shallow"
        else:
            return  # 没有明确偏好信号，不更新
        
        prefs = profile.preferences[category]
        if "depth" in prefs:
            prefs["depth"].update(depth)
        else:
            prefs["depth"] = UserPreference(
                category=category,
                key="depth",
                value=depth,
                confidence=0.3,
            )
    
    def _learn_topic_interest(self, profile: UserProfile, message: str):
        """学习话题兴趣（简化版，基于关键词匹配）"""
        category = PreferenceCategory.TOPIC_INTEREST.value
        
        if category not in profile.preferences:
            profile.preferences[category] = {}
        
        # 简化的话题关键词匹配
        topic_keywords = {
            "technology": ["编程", "代码", "技术", "软件", "硬件", "AI", "人工智能", "大模型"],
            "life": ["生活", "健康", "饮食", "运动", "旅游", "美食"],
            "work": ["工作", "效率", "管理", "项目", "会议", "报告"],
            "study": ["学习", "考试", "课程", "知识", "读书"],
            "entertainment": ["游戏", "电影", "音乐", "综艺", "小说"],
        }
        
        message_lower = message.lower()
        for topic, keywords in topic_keywords.items():
            count = sum(1 for k in keywords if k in message_lower)
            if count > 0:
                prefs = profile.preferences[category]
                if topic in prefs:
                    prefs[topic].count += count
                    prefs[topic].last_seen = time.time()
                    prefs[topic].confidence = min(0.95, 0.3 + 0.05 * prefs[topic].count)
                else:
                    prefs[topic] = UserPreference(
                        category=category,
                        key=topic,
                        value=count,
                        confidence=0.3,
                        count=count,
                    )
    
    def _analyze_formality(self, text: str) -> str:
        """分析文本正式程度"""
        formal_indicators = ["您好", "请问", "谢谢", "麻烦", "请教", "尊敬的"]
        casual_indicators = ["你好", "嘿", "嗨", "啊", "呢", "吧", "嘛"]
        
        formal_count = sum(1 for w in formal_indicators if w in text)
        casual_count = sum(1 for w in casual_indicators if w in text)
        
        if formal_count > casual_count:
            return "formal"
        elif casual_count > formal_count:
            return "casual"
        else:
            return "neutral"
    
    def get_personalized_prompt(self, user_id: str, base_prompt: str) -> str:
        """根据用户偏好生成个性化提示词"""
        profile = self.get_profile(user_id)
        enhancements = []
        
        with self._lock:
            # 沟通风格
            comm_prefs = profile.preferences.get(PreferenceCategory.COMMUNICATION_STYLE.value, {})
            if "formality" in comm_prefs and comm_prefs["formality"].confidence > 0.5:
                style = comm_prefs["formality"].value
                if style == "formal":
                    enhancements.append("使用正式、礼貌的语气回复")
                elif style == "casual":
                    enhancements.append("使用轻松、自然的语气回复")
            
            if "length_preference" in comm_prefs and comm_prefs["length_preference"].confidence > 0.5:
                length = comm_prefs["length_preference"].value
                if length == "concise":
                    enhancements.append("回复尽量简洁明了")
                elif length == "detailed":
                    enhancements.append("回复尽量详细全面")
            
            # 内容深度
            depth_prefs = profile.preferences.get(PreferenceCategory.CONTENT_DEPTH.value, {})
            if "depth" in depth_prefs and depth_prefs["depth"].confidence > 0.5:
                depth = depth_prefs["depth"].value
                if depth == "deep":
                    enhancements.append("深入分析，解释底层原理")
                elif depth == "shallow":
                    enhancements.append("浅显易懂，避免过多技术细节")
        
        if enhancements:
            return f"{base_prompt}\n\n【个性化要求】\n" + "\n".join(f"- {e}" for e in enhancements)
        
        return base_prompt
    
    def get_topics(self, user_id: str, top_n: int = 5) -> List[Tuple[str, float]]:
        """获取用户最感兴趣的话题"""
        profile = self.get_profile(user_id)
        
        with self._lock:
            topic_prefs = profile.preferences.get(PreferenceCategory.TOPIC_INTEREST.value, {})
            sorted_topics = sorted(
                topic_prefs.items(),
                key=lambda x: x[1].confidence * x[1].count,
                reverse=True
            )
            return [(k, v.confidence) for k, v in sorted_topics[:top_n]]
    
    def get_active_hours(self, user_id: str) -> List[int]:
        """获取用户活跃时段（按活跃度排序）"""
        profile = self.get_profile(user_id)
        
        with self._lock:
            hours = profile.interaction_stats.get("active_hours", {})
            sorted_hours = sorted(hours.items(), key=lambda x: x[1], reverse=True)
            return [h for h, _ in sorted_hours]
    
    def get_voice_preferences(self, user_id: str) -> Dict[str, Any]:
        """获取用户的语音偏好设置
        
        Returns:
            包含 voice, speed, emotion, pitch 等偏好的字典
        """
        profile = self.get_profile(user_id)
        defaults = {
            "voice": "default",
            "speed": 1.0,
            "emotion": "neutral",
            "pitch": 1.0,
            "volume": 1.0,
        }
        
        with self._lock:
            voice_prefs = profile.preferences.get(PreferenceCategory.VOICE.value, {})
            for key in defaults:
                if key in voice_prefs and voice_prefs[key].confidence > 0.3:
                    defaults[key] = voice_prefs[key].value
        
        return defaults
    
    def set_voice_preference(self, user_id: str, key: str, value: Any):
        """设置用户的语音偏好
        
        Args:
            user_id: 用户ID
            key: 偏好键（voice/speed/emotion/pitch/volume）
            value: 偏好值
        """
        self.set_preference(
            user_id,
            PreferenceCategory.VOICE.value,
            key,
            value,
            source="explicit",
        )
    
    def get_all_users(self) -> List[Dict[str, Any]]:
        """获取所有用户列表"""
        with self._lock:
            return [
                {
                    "user_id": p.user_id,
                    "nickname": p.nickname,
                    "avatar": p.avatar,
                    "created_at": p.created_at,
                    "updated_at": p.updated_at,
                    "total_messages": p.interaction_stats.get("total_messages", 0),
                }
                for p in self._profiles.values()
            ]
    
    def delete_profile(self, user_id: str) -> bool:
        """删除用户画像"""
        if user_id == self._default_user_id:
            return False  # 不允许删除默认用户
        
        with self._lock:
            if user_id not in self._profiles:
                return False
            
            del self._profiles[user_id]
            
            # 删除文件
            file_path = self._data_dir / f"{user_id}.json"
            if file_path.exists():
                file_path.unlink()
            
            return True


# 全局单例
_profile_manager: Optional[UserProfileManager] = None


def get_user_profile_manager() -> UserProfileManager:
    """获取用户画像管理器单例"""
    global _profile_manager
    if _profile_manager is None:
        _profile_manager = UserProfileManager()
    return _profile_manager
