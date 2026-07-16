"""
自主学习引擎 - 云汐自我进化核心
从对话和交互中自动学习、提取知识、发现规律、沉淀成长

核心能力：
1. 知识抽取 - 从对话中自动提取事实、概念、规律
2. 模式发现 - 发现用户行为模式、语言习惯、情感规律
3. 错误学习 - 从错误回答和用户纠正中学习改进
4. 反馈学习 - 从用户反馈（点赞/点踩/纠正）中学习
5. 知识整合 - 将新知识与已有知识关联、去重、验证
"""

import re
import json
import time
import uuid
import threading
from pathlib import Path
from enum import Enum
from dataclasses import dataclass, field, asdict
from typing import Optional, List, Dict, Any, Tuple


class LearningType(str, Enum):
    """学习类型"""
    FACT = "fact"                    # 事实知识
    PREFERENCE = "preference"        # 用户偏好
    PATTERN = "pattern"              # 行为模式
    KNOWLEDGE = "knowledge"          # 通用知识
    MISTAKE = "mistake"              # 错误教训
    FEEDBACK = "feedback"            # 用户反馈
    SKILL_GAP = "skill_gap"          # 能力短板
    INSIGHT = "insight"              # 洞察感悟


class LearningStatus(str, Enum):
    """学习条目状态"""
    PENDING = "pending"          # 待验证
    VERIFIED = "verified"        # 已验证
    INTEGRATED = "integrated"    # 已整合入知识库
    REJECTED = "rejected"        # 被否决/错误


@dataclass
class LearningItem:
    """单条学习记录"""
    item_id: str
    learning_type: str  # LearningType.value
    title: str
    content: str
    confidence: float = 0.5  # 0-1 置信度
    status: str = LearningStatus.PENDING.value
    
    source: str = "conversation"  # 来源
    source_id: str = ""  # 来源ID（对话ID等）
    user_id: str = "default"
    
    created_at: float = field(default_factory=time.time)
    verified_at: Optional[float] = None
    integrated_at: Optional[float] = None
    
    tags: List[str] = field(default_factory=list)
    related_items: List[str] = field(default_factory=list)  # 关联的学习条目
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    # 强化次数（被验证/使用的次数）
    reinforcement_count: int = 0
    
    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "LearningItem":
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})


class AutonomousLearningEngine:
    """自主学习引擎 - 单例模式"""
    
    _instance: Optional["AutonomousLearningEngine"] = None
    
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
            self._data_dir = Path.home() / ".yunxi" / "learning"
        self._data_dir.mkdir(parents=True, exist_ok=True)
        
        # 学习记录存储
        self._items: Dict[str, List[LearningItem]] = {}  # user_id -> [LearningItem]
        self._lock = threading.RLock()
        
        # 学习统计
        self._stats: Dict[str, Dict[str, Any]] = {}
        
        # 自动学习开关（可配置）
        self._auto_learn = True
        self._extract_facts = True
        self._extract_preferences = True
        self._learn_from_mistakes = True
        
        # 模式匹配规则（用于从对话中自动提取）
        self._extraction_patterns = {
            # 用户明确陈述的偏好
            "preference_explicit": [
                r"我(喜欢|爱|最爱|偏好|倾向于|更爱|特别喜欢)(.+?)[。！？\.]",
                r"我(不喜欢|讨厌|反感|受不了|排斥)(.+?)[。！？\.]",
                r"我的(爱好|兴趣|特长|擅长)是(.+?)[。！？\.]",
                r"我(觉得|认为|感觉)(.+?)(比较|很|非常|特别)?(好|棒|不错|差|不好|讨厌)[。！？\.]",
            ],
            # 用户明确陈述的事实
            "fact_explicit": [
                r"我(叫|是|名字叫)(.+?)[。！？\s]",
                r"我(今年|现在)(\d+)岁",
                r"我(住在|在)(.+?)(工作|上学|生活)",
                r"我的(职业|工作|专业)是(.+?)[。！？\.]",
                r"我(有|养)(一只|一条|一只)(猫|狗|宠物)",
            ],
            # 用户纠正/反馈
            "correction": [
                r"(不对|错了|不是|你错了|你说的不对)",
                r"(应该是|实际上是|其实是|正确的是)",
                r"(下次别|不要再说|以后不要)",
            ],
            # 用户情绪/情感表达
            "emotion": [
                r"我(今天|最近)(很|非常|特别|有点)?(开心|高兴|难过|伤心|焦虑|烦躁|疲惫|累|压力大)",
                r"(气死我了|烦死了|好郁闷|好开心|太棒了|太难受了)",
            ],
        }
        
        # 加载已有数据
        self._load_all()
    
    # ==================== 存储 ====================
    
    def _get_data_file(self, user_id: str) -> Path:
        return self._data_dir / f"{user_id}_learning.json"
    
    def _load_all(self):
        """加载所有用户的学习记录"""
        for json_file in self._data_dir.glob("*_learning.json"):
            user_id = json_file.stem.replace("_learning", "")
            try:
                with open(json_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                self._items[user_id] = [LearningItem.from_dict(item) for item in data]
            except Exception:
                self._items[user_id] = []
    
    def _save(self, user_id: str):
        """保存用户学习记录"""
        data_file = self._get_data_file(user_id)
        with self._lock:
            items = self._items.get(user_id, [])
            data = [item.to_dict() for item in items]
            with open(data_file, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
    
    # ==================== 知识抽取 ====================
    
    def extract_from_conversation(self, user_id: str,
                                   conversation_id: str,
                                   user_message: str,
                                   assistant_reply: str,
                                   mode: str = "main-chat") -> List[LearningItem]:
        """从一轮对话中提取可学习的内容
        
        Args:
            user_id: 用户ID
            conversation_id: 对话ID
            user_message: 用户消息
            assistant_reply: 助手回复
            mode: 对话模式
        
        Returns:
            新提取的学习条目列表
        """
        if not self._auto_learn:
            return []
        
        new_items = []
        
        # 1. 提取用户偏好
        if self._extract_preferences:
            pref_items = self._extract_preferences_from_text(user_id, conversation_id, user_message)
            new_items.extend(pref_items)
        
        # 2. 提取事实信息
        if self._extract_facts:
            fact_items = self._extract_facts_from_text(user_id, conversation_id, user_message)
            new_items.extend(fact_items)
        
        # 3. 检测用户纠正（错误学习）
        if self._learn_from_mistakes:
            mistake_items = self._detect_correction(user_id, conversation_id, user_message, assistant_reply)
            new_items.extend(mistake_items)
        
        # 4. 检测情感模式
        emotion_items = self._detect_emotion_pattern(user_id, conversation_id, user_message)
        new_items.extend(emotion_items)
        
        # 保存新条目
        if new_items:
            with self._lock:
                if user_id not in self._items:
                    self._items[user_id] = []
                self._items[user_id].extend(new_items)
            self._save(user_id)
            
            # 尝试自动整合到长期记忆和知识库
            self._try_integrate_new_items(user_id, new_items)
        
        return new_items
    
    def _extract_preferences_from_text(self, user_id: str, conversation_id: str, text: str) -> List[LearningItem]:
        """从文本中提取用户偏好"""
        items = []
        
        for pattern in self._extraction_patterns["preference_explicit"]:
            matches = re.findall(pattern, text)
            for match in matches:
                if isinstance(match, tuple):
                    verb = match[0] if len(match) > 0 else ""
                    content = match[1] if len(match) > 1 else str(match)
                else:
                    verb = ""
                    content = str(match)
                
                if not content or len(content) < 2:
                    continue
                
                # 判断是正向还是负向偏好
                is_negative = any(w in verb for w in ["不", "讨厌", "反感", "受不了", "排斥"])
                
                item_title = f"用户{'不' if is_negative else ''}喜欢：{content[:30]}"
                item_content = f"用户{'不' if is_negative else ''}喜欢{content}"
                
                item = LearningItem(
                    item_id=f"learn_{uuid.uuid4().hex[:12]}",
                    learning_type=LearningType.PREFERENCE.value,
                    title=item_title,
                    content=item_content,
                    confidence=0.7 if verb else 0.5,  # 明确表达的偏好置信度更高
                    status=LearningStatus.PENDING.value,
                    source="conversation",
                    source_id=conversation_id,
                    user_id=user_id,
                    tags=["preference", "auto_extracted", "negative" if is_negative else "positive"],
                    metadata={
                        "verb": verb,
                        "extraction_method": "pattern_match",
                    }
                )
                items.append(item)
        
        return items
    
    def _extract_facts_from_text(self, user_id: str, conversation_id: str, text: str) -> List[LearningItem]:
        """从文本中提取事实信息"""
        items = []
        
        for pattern in self._extraction_patterns["fact_explicit"]:
            matches = re.findall(pattern, text)
            for match in matches:
                if isinstance(match, tuple):
                    content = " ".join(str(m) for m in match if m)
                else:
                    content = str(match)
                
                if not content or len(content) < 2:
                    continue
                
                item = LearningItem(
                    item_id=f"learn_{uuid.uuid4().hex[:12]}",
                    learning_type=LearningType.FACT.value,
                    title=f"用户事实：{content[:30]}",
                    content=content,
                    confidence=0.8,  # 用户主动陈述的事实置信度高
                    status=LearningStatus.PENDING.value,
                    source="conversation",
                    source_id=conversation_id,
                    user_id=user_id,
                    tags=["fact", "auto_extracted", "user_info"],
                    metadata={
                        "extraction_method": "pattern_match",
                    }
                )
                items.append(item)
        
        return items
    
    def _detect_correction(self, user_id: str, conversation_id: str,
                            user_message: str, assistant_reply: str) -> List[LearningItem]:
        """检测用户纠正，从中学习"""
        items = []
        
        for pattern in self._extraction_patterns["correction"]:
            if re.search(pattern, user_message):
                item = LearningItem(
                    item_id=f"learn_{uuid.uuid4().hex[:12]}",
                    learning_type=LearningType.MISTAKE.value,
                    title=f"用户纠正：{user_message[:40]}",
                    content=f"用户指出了错误：{user_message}\n\n之前的回复：{assistant_reply[:200]}",
                    confidence=0.9,  # 用户明确纠正的置信度很高
                    status=LearningStatus.PENDING.value,
                    source="conversation",
                    source_id=conversation_id,
                    user_id=user_id,
                    tags=["mistake", "correction", "needs_review"],
                    metadata={
                        "user_message": user_message,
                        "assistant_reply": assistant_reply[:300],
                    }
                )
                items.append(item)
                break  # 一条消息只记录一次纠正
        
        return items
    
    def _detect_emotion_pattern(self, user_id: str, conversation_id: str, text: str) -> List[LearningItem]:
        """检测情感表达，积累情感模式数据"""
        items = []
        
        for pattern in self._extraction_patterns["emotion"]:
            matches = re.findall(pattern, text)
            if matches:
                for match in matches:
                    emotion = ""
                    intensity = "normal"
                    
                    if isinstance(match, tuple):
                        # 提取情绪词
                        for m in match:
                            if m in ["开心", "高兴", "难过", "伤心", "焦虑", "烦躁", "疲惫", "累", "压力大"]:
                                emotion = m
                            elif m in ["很", "非常", "特别", "有点"]:
                                intensity = m
                    
                    if emotion:
                        item = LearningItem(
                            item_id=f"learn_{uuid.uuid4().hex[:12]}",
                            learning_type=LearningType.PATTERN.value,
                            title=f"情感记录：{emotion}({intensity})",
                            content=f"用户表达了{intensity}的{emotion}情绪",
                            confidence=0.6,
                            status=LearningStatus.PENDING.value,
                            source="conversation",
                            source_id=conversation_id,
                            user_id=user_id,
                            tags=["emotion", "pattern", emotion],
                            metadata={
                                "emotion": emotion,
                                "intensity": intensity,
                                "time": time.strftime("%Y-%m-%d %H:%M:%S"),
                            }
                        )
                        items.append(item)
                
                if items:
                    break
        
        return items
    
    # ==================== 知识整合 ====================
    
    def _try_integrate_new_items(self, user_id: str, new_items: List[LearningItem]):
        """尝试将新学习的条目整合到长期记忆和知识库中
        
        高置信度的条目自动整合，低置信度的待人工验证
        """
        try:
            from shared.long_term_memory import get_long_term_memory, MemoryType, MemoryImportance
            ltm = get_long_term_memory()
            
            for item in new_items:
                # 高置信度（>0.7）的自动整合
                if item.confidence >= 0.7 and item.status == LearningStatus.PENDING.value:
                    
                    # 映射到长期记忆类型
                    mem_type = self._map_learning_to_memory_type(item.learning_type)
                    importance = self._confidence_to_importance(item.confidence)
                    
                    ltm.add_memory(
                        user_id=user_id,
                        memory_type=mem_type,
                        title=item.title,
                        content=item.content,
                        importance=importance,
                        tags=item.tags,
                        source="auto_learning",
                        metadata={"learning_item_id": item.item_id},
                    )
                    
                    # 标记为已整合
                    item.status = LearningStatus.INTEGRATED.value
                    item.integrated_at = time.time()
                    item.reinforcement_count += 1
            
            self._save(user_id)
        except Exception:
            # 整合失败不影响学习记录本身
            pass
    
    def _map_learning_type_to_memory_type(self, learning_type: str) -> str:
        """将学习类型映射为长期记忆类型"""
        mapping = {
            LearningType.FACT.value: "fact",
            LearningType.PREFERENCE.value: "preference",
            LearningType.PATTERN.value: "fact",
            LearningType.KNOWLEDGE.value: "knowledge",
            LearningType.MISTAKE.value: "fact",
            LearningType.FEEDBACK.value: "preference",
            LearningType.INSIGHT.value: "knowledge",
        }
        return mapping.get(learning_type, "fact")
    
    def _confidence_to_importance(self, confidence: float) -> str:
        """将置信度映射到重要性等级"""
        if confidence >= 0.9:
            return "important"
        elif confidence >= 0.7:
            return "normal"
        elif confidence >= 0.5:
            return "low"
        else:
            return "trivial"
    
    # ==================== 验证与强化 ====================
    
    def verify_item(self, user_id: str, item_id: str,
                    is_correct: bool, feedback: str = "") -> bool:
        """验证一条学习记录（人工确认）
        
        Args:
            user_id: 用户ID
            item_id: 学习条目ID
            is_correct: 是否正确
            feedback: 反馈说明
        
        Returns:
            是否成功
        """
        with self._lock:
            items = self._items.get(user_id, [])
            for item in items:
                if item.item_id == item_id:
                    if is_correct:
                        item.status = LearningStatus.VERIFIED.value
                        item.verified_at = time.time()
                        item.confidence = min(1.0, item.confidence + 0.2)
                        item.reinforcement_count += 1
                        
                        # 验证后自动整合
                        if item.status != LearningStatus.INTEGRATED.value:
                            self._try_integrate_new_items(user_id, [item])
                    else:
                        item.status = LearningStatus.REJECTED.value
                        item.confidence = max(0.0, item.confidence - 0.3)
                        if feedback:
                            item.metadata["reject_reason"] = feedback
                    
                    self._save(user_id)
                    return True
        return False
    
    def reinforce_item(self, user_id: str, item_id: str) -> bool:
        """强化一条学习记录（被使用/验证时调用）"""
        with self._lock:
            items = self._items.get(user_id, [])
            for item in items:
                if item.item_id == item_id:
                    item.reinforcement_count += 1
                    item.confidence = min(1.0, item.confidence + 0.05)
                    self._save(user_id)
                    return True
        return False
    
    # ==================== 查询 ====================
    
    def get_items(self, user_id: str,
                  learning_type: Optional[str] = None,
                  status: Optional[str] = None,
                  min_confidence: float = 0.0,
                  limit: int = 50) -> List[LearningItem]:
        """查询学习记录"""
        with self._lock:
            items = self._items.get(user_id, [])
            
            filtered = []
            for item in items:
                if learning_type and item.learning_type != learning_type:
                    continue
                if status and item.status != status:
                    continue
                if item.confidence < min_confidence:
                    continue
                filtered.append(item)
            
            # 按时间倒序
            filtered.sort(key=lambda x: x.created_at, reverse=True)
            
            return filtered[:limit]
    
    def get_stats(self, user_id: str) -> Dict[str, Any]:
        """获取学习统计"""
        with self._lock:
            items = self._items.get(user_id, [])
            
            type_counts = {}
            status_counts = {}
            total_confidence = 0.0
            verified_count = 0
            integrated_count = 0
            
            for item in items:
                type_counts[item.learning_type] = type_counts.get(item.learning_type, 0) + 1
                status_counts[item.status] = status_counts.get(item.status, 0) + 1
                total_confidence += item.confidence
                if item.status == LearningStatus.VERIFIED.value:
                    verified_count += 1
                if item.status == LearningStatus.INTEGRATED.value:
                    integrated_count += 1
            
            avg_confidence = total_confidence / len(items) if items else 0
            
            return {
                "total_learned": len(items),
                "type_counts": type_counts,
                "status_counts": status_counts,
                "average_confidence": round(avg_confidence, 3),
                "verified_count": verified_count,
                "integrated_count": integrated_count,
                "auto_learn_enabled": self._auto_learn,
            }
    
    def get_pending_review(self, user_id: str, limit: int = 20) -> List[LearningItem]:
        """获取待审核的学习条目"""
        return self.get_items(
            user_id=user_id,
            status=LearningStatus.PENDING.value,
            min_confidence=0.3,
            limit=limit,
        )
    
    # ==================== 设置 ====================
    
    def set_auto_learn(self, enabled: bool):
        """设置自动学习开关"""
        self._auto_learn = enabled
    
    def get_auto_learn(self) -> bool:
        """获取自动学习开关状态"""
        return self._auto_learn


# 全局单例获取函数
_ale_instance: Optional[AutonomousLearningEngine] = None


def get_autonomous_learning_engine() -> AutonomousLearningEngine:
    """获取自主学习引擎单例"""
    global _ale_instance
    if _ale_instance is None:
        _ale_instance = AutonomousLearningEngine()
    return _ale_instance
