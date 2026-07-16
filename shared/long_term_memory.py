"""
长期记忆系统 - 云汐大脑核心组件
结构化记忆存储 + 智能检索 + 遗忘曲线 + 重要性评分

超越M5潮汐记忆的简单文本检索，提供：
- 结构化记忆（事实/事件/人物/知识/偏好）
- 重要性评分机制（自动+手动）
- 艾宾浩斯遗忘曲线模拟
- 多维度检索（时间/类型/重要性/关键词/语义）
- 记忆整合与摘要
- 记忆强化机制
"""

import os
import json
import time
import uuid
import math
import threading
from pathlib import Path
from enum import Enum
from dataclasses import dataclass, field, asdict
from typing import Optional, List, Dict, Any, Tuple
from datetime import datetime, timedelta


class MemoryType(str, Enum):
    """记忆类型"""
    FACT = "fact"              # 事实类记忆（用户说过的重要信息）
    EVENT = "event"            # 事件类记忆（发生过的事情）
    PERSON = "person"          # 人物类记忆（关于某个人的信息）
    KNOWLEDGE = "knowledge"    # 知识类记忆（学习到的知识）
    PREFERENCE = "preference"  # 偏好类记忆（用户喜好/习惯）
    CONVERSATION = "conversation"  # 对话摘要记忆
    GOAL = "goal"              # 目标/计划类记忆
    EMOTION = "emotion"        # 情感类记忆


class MemoryImportance(str, Enum):
    """记忆重要性等级"""
    TRIVIAL = "trivial"        # 不重要（很快遗忘）
    LOW = "low"                # 低重要性
    NORMAL = "normal"          # 普通
    IMPORTANT = "important"    # 重要
    CRITICAL = "critical"      # 关键（几乎不遗忘）


@dataclass
class Memory:
    """单条记忆"""
    memory_id: str
    memory_type: str  # MemoryType.value
    title: str
    content: str
    importance: str = MemoryImportance.NORMAL.value  # MemoryImportance.value
    importance_score: float = 0.5  # 0.0-1.0 数值化重要性
    
    # 时间相关
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    last_accessed: float = field(default_factory=time.time)
    access_count: int = 0
    
    # 遗忘曲线
    initial_strength: float = 1.0  # 初始记忆强度
    current_strength: float = 1.0  # 当前记忆强度（随时间衰减）
    review_count: int = 0  # 复习次数
    
    # 元数据
    tags: List[str] = field(default_factory=list)
    entities: List[str] = field(default_factory=list)  # 涉及的实体/人物
    source: str = "auto"  # 来源：auto/manual/conversation/import
    related_memories: List[str] = field(default_factory=list)  # 关联记忆ID
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Memory":
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})


class LongTermMemory:
    """长期记忆管理器 - 单例模式"""
    
    _instance: Optional["LongTermMemory"] = None
    
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
            self._data_dir = Path.home() / ".yunxi" / "long_term_memory"
        self._data_dir.mkdir(parents=True, exist_ok=True)
        
        # 记忆存储（按用户分文件）
        self._memories: Dict[str, List[Memory]] = {}  # user_id -> [Memory]
        self._lock = threading.RLock()
        
        # 遗忘曲线参数（艾宾浩斯）
        self._forgetting_params = {
            MemoryImportance.TRIVIAL.value:    {"half_life_days": 1,    "decay_rate": 0.5},
            MemoryImportance.LOW.value:        {"half_life_days": 3,    "decay_rate": 0.3},
            MemoryImportance.NORMAL.value:     {"half_life_days": 7,    "decay_rate": 0.2},
            MemoryImportance.IMPORTANT.value:  {"half_life_days": 30,   "decay_rate": 0.1},
            MemoryImportance.CRITICAL.value:   {"half_life_days": 365,  "decay_rate": 0.02},
        }
        
        # 加载已有记忆
        self._load_all_memories()
    
    # ==================== 存储 ====================
    
    def _get_memory_file(self, user_id: str) -> Path:
        """获取用户记忆文件路径"""
        return self._data_dir / f"{user_id}_memories.json"
    
    def _load_all_memories(self):
        """加载所有用户的记忆"""
        for json_file in self._data_dir.glob("*_memories.json"):
            user_id = json_file.stem.replace("_memories", "")
            try:
                with open(json_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                self._memories[user_id] = [Memory.from_dict(m) for m in data]
            except Exception:
                self._memories[user_id] = []
    
    def _save_memories(self, user_id: str):
        """保存用户记忆"""
        memory_file = self._get_memory_file(user_id)
        with self._lock:
            memories = self._memories.get(user_id, [])
            data = [m.to_dict() for m in memories]
            with open(memory_file, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
    
    # ==================== 添加记忆 ====================
    
    def add_memory(self, user_id: str,
                   memory_type: str,
                   title: str,
                   content: str,
                   importance: str = MemoryImportance.NORMAL.value,
                   tags: Optional[List[str]] = None,
                   entities: Optional[List[str]] = None,
                   source: str = "auto",
                   metadata: Optional[Dict[str, Any]] = None) -> Memory:
        """添加一条记忆
        
        Args:
            user_id: 用户ID
            memory_type: 记忆类型（MemoryType.value）
            title: 记忆标题（简短描述）
            content: 记忆内容（详细）
            importance: 重要性等级
            tags: 标签列表
            entities: 涉及的实体/人物
            source: 来源
            metadata: 额外元数据
        
        Returns:
            新建的Memory对象
        """
        memory_id = f"mem_{uuid.uuid4().hex[:12]}"
        
        # 计算重要性分数
        importance_score = self._calc_importance_score(importance, content, tags)
        
        # 初始强度与重要性正相关
        initial_strength = 0.5 + importance_score * 0.5
        
        memory = Memory(
            memory_id=memory_id,
            memory_type=memory_type,
            title=title,
            content=content,
            importance=importance,
            importance_score=importance_score,
            initial_strength=initial_strength,
            current_strength=initial_strength,
            tags=tags or [],
            entities=entities or [],
            source=source,
            metadata=metadata or {},
        )
        
        with self._lock:
            if user_id not in self._memories:
                self._memories[user_id] = []
            self._memories[user_id].append(memory)
        
        # 异步保存（这里同步保存，确保数据安全）
        self._save_memories(user_id)
        
        return memory
    
    def _calc_importance_score(self, importance: str, content: str, tags: Optional[List[str]]) -> float:
        """计算重要性分数（0.0-1.0）"""
        base_scores = {
            MemoryImportance.TRIVIAL.value:    0.1,
            MemoryImportance.LOW.value:        0.3,
            MemoryImportance.NORMAL.value:     0.5,
            MemoryImportance.IMPORTANT.value:  0.75,
            MemoryImportance.CRITICAL.value:   0.95,
        }
        score = base_scores.get(importance, 0.5)
        
        # 内容长度加成（信息量大的稍微重要一些）
        content_len = len(content)
        if content_len > 500:
            score = min(1.0, score + 0.05)
        
        # 关键标签加成
        important_tags = ["重要", "关键", "核心", "秘密", "密码", "生日", "纪念日"]
        if tags:
            for tag in tags:
                if tag in important_tags:
                    score = min(1.0, score + 0.1)
                    break
        
        return score
    
    # ==================== 检索记忆 ====================
    
    def search(self, user_id: str,
               query: str = "",
               memory_type: Optional[str] = None,
               min_importance: Optional[str] = None,
               min_strength: float = 0.0,
               tags: Optional[List[str]] = None,
               entity: Optional[str] = None,
               limit: int = 20,
               sort_by: str = "relevance") -> List[Memory]:
        """搜索记忆
        
        Args:
            user_id: 用户ID
            query: 搜索关键词
            memory_type: 按类型过滤
            min_importance: 最低重要性等级
            min_strength: 最低记忆强度
            tags: 按标签过滤（匹配任意一个）
            entity: 按实体过滤
            limit: 返回数量上限
            sort_by: 排序方式（relevance/recency/importance/strength）
        
        Returns:
            匹配的记忆列表
        """
        with self._lock:
            memories = self._memories.get(user_id, [])
            
            # 先更新所有记忆的当前强度（基于遗忘曲线）
            self._update_all_strengths(user_id)
            
            # 过滤
            filtered = []
            for mem in memories:
                # 强度过滤
                if mem.current_strength < min_strength:
                    continue
                
                # 类型过滤
                if memory_type and mem.memory_type != memory_type:
                    continue
                
                # 重要性过滤
                if min_importance:
                    if not self._importance_gte(mem.importance, min_importance):
                        continue
                
                # 标签过滤
                if tags:
                    if not any(t in mem.tags for t in tags):
                        continue
                
                # 实体过滤
                if entity and entity not in mem.entities:
                    continue
                
                # 关键词匹配（简单的文本包含，后续可升级为向量检索）
                if query:
                    query_lower = query.lower()
                    text = f"{mem.title} {mem.content}".lower()
                    if query_lower not in text:
                        # 部分匹配也算（关键词中有2个以上字出现在内容中）
                        if not self._partial_match(query_lower, text):
                            continue
                
                filtered.append(mem)
            
            # 排序
            if sort_by == "recency":
                filtered.sort(key=lambda m: m.created_at, reverse=True)
            elif sort_by == "importance":
                filtered.sort(key=lambda m: m.importance_score, reverse=True)
            elif sort_by == "strength":
                filtered.sort(key=lambda m: m.current_strength, reverse=True)
            else:  # relevance
                # 相关性 = 重要性 * 强度 * 关键词匹配度
                def calc_relevance(mem: Memory) -> float:
                    score = mem.importance_score * 0.3 + mem.current_strength * 0.2
                    if query:
                        # 简单的匹配度计算
                        text = f"{mem.title} {mem.content}".lower()
                        query_lower = query.lower()
                        if query_lower in text:
                            score += 0.5
                        else:
                            # 字符级匹配度
                            matches = sum(1 for c in query_lower if c in text)
                            score += 0.3 * (matches / max(len(query_lower), 1))
                    else:
                        score += 0.5  # 无查询词时默认中等相关
                    return score
                
                filtered.sort(key=calc_relevance, reverse=True)
            
            return filtered[:limit]
    
    def _partial_match(self, query: str, text: str) -> bool:
        """简单的部分匹配（超过50%的字符在文本中）"""
        if not query or not text:
            return False
        matches = sum(1 for c in set(query) if c in text)
        return matches / len(set(query)) > 0.5
    
    def _importance_gte(self, importance_a: str, importance_b: str) -> bool:
        """判断importance_a是否 >= importance_b"""
        order = [
            MemoryImportance.TRIVIAL.value,
            MemoryImportance.LOW.value,
            MemoryImportance.NORMAL.value,
            MemoryImportance.IMPORTANT.value,
            MemoryImportance.CRITICAL.value,
        ]
        return order.index(importance_a) >= order.index(importance_b)
    
    # ==================== 遗忘曲线 ====================
    
    def _update_all_strengths(self, user_id: str):
        """更新所有记忆的当前强度（基于遗忘曲线）"""
        now = time.time()
        memories = self._memories.get(user_id, [])
        
        needs_save = False
        for mem in memories:
            days_since_access = (now - mem.last_accessed) / (24 * 3600)
            if days_since_access < 0.01:  # 刚访问过，跳过
                continue
            
            # 获取遗忘参数
            params = self._forgetting_params.get(
                mem.importance,
                self._forgetting_params[MemoryImportance.NORMAL.value]
            )
            half_life = params["half_life_days"]
            decay_rate = params["decay_rate"]
            
            # 艾宾浩斯遗忘公式：R = e^(-t/S)
            # R: 记忆保持量，t: 时间，S: 记忆强度（由复习次数决定）
            # 简化版：基于半衰期的指数衰减
            decay_factor = math.exp(-days_since_access / half_life * decay_rate * 3)
            new_strength = mem.initial_strength * decay_factor
            
            # 复习过的记忆衰减更慢
            if mem.review_count > 0:
                review_bonus = 1 + mem.review_count * 0.3
                new_strength = mem.initial_strength * math.exp(-days_since_access / (half_life * review_bonus))
            
            new_strength = max(0.01, min(mem.initial_strength, new_strength))
            
            if abs(new_strength - mem.current_strength) > 0.001:
                mem.current_strength = new_strength
                needs_save = True
        
        if needs_save:
            self._save_memories(user_id)
    
    def reinforce_memory(self, user_id: str, memory_id: str) -> bool:
        """强化记忆（复习/重新激活）
        
        当用户再次接触到某条记忆时，调用此方法增强记忆强度
        """
        with self._lock:
            memories = self._memories.get(user_id, [])
            for mem in memories:
                if mem.memory_id == memory_id:
                    mem.last_accessed = time.time()
                    mem.access_count += 1
                    mem.review_count += 1
                    
                    # 每次复习提升初始强度（上限1.0）
                    boost = 0.1 * (1 - mem.initial_strength)
                    mem.initial_strength = min(1.0, mem.initial_strength + boost)
                    mem.current_strength = mem.initial_strength
                    
                    self._save_memories(user_id)
                    return True
            return False
    
    def set_importance(self, user_id: str, memory_id: str, importance: str) -> bool:
        """手动设置记忆重要性"""
        with self._lock:
            memories = self._memories.get(user_id, [])
            for mem in memories:
                if mem.memory_id == memory_id:
                    mem.importance = importance
                    mem.importance_score = self._calc_importance_score(importance, mem.content, mem.tags)
                    mem.initial_strength = 0.5 + mem.importance_score * 0.5
                    mem.current_strength = mem.initial_strength
                    mem.updated_at = time.time()
                    
                    self._save_memories(user_id)
                    return True
            return False
    
    # ==================== 记忆管理 ====================
    
    def get_memory(self, user_id: str, memory_id: str) -> Optional[Memory]:
        """获取单条记忆"""
        with self._lock:
            memories = self._memories.get(user_id, [])
            for mem in memories:
                if mem.memory_id == memory_id:
                    mem.last_accessed = time.time()
                    mem.access_count += 1
                    return mem
        return None
    
    def delete_memory(self, user_id: str, memory_id: str) -> bool:
        """删除记忆"""
        with self._lock:
            memories = self._memories.get(user_id, [])
            for i, mem in enumerate(memories):
                if mem.memory_id == memory_id:
                    memories.pop(i)
                    self._save_memories(user_id)
                    return True
        return False
    
    def get_stats(self, user_id: str) -> Dict[str, Any]:
        """获取记忆统计信息"""
        with self._lock:
            memories = self._memories.get(user_id, [])
            self._update_all_strengths(user_id)
            
            type_counts = {}
            importance_counts = {}
            total_strength = 0.0
            strong_count = 0
            
            for mem in memories:
                type_counts[mem.memory_type] = type_counts.get(mem.memory_type, 0) + 1
                importance_counts[mem.importance] = importance_counts.get(mem.importance, 0) + 1
                total_strength += mem.current_strength
                if mem.current_strength > 0.7:
                    strong_count += 1
            
            avg_strength = total_strength / len(memories) if memories else 0
            
            return {
                "total_memories": len(memories),
                "type_counts": type_counts,
                "importance_counts": importance_counts,
                "average_strength": round(avg_strength, 3),
                "strong_memories": strong_count,
                "weak_memories": len(memories) - strong_count,
            }
    
    def get_daily_forgetting(self, user_id: str) -> List[Memory]:
        """获取即将遗忘的记忆（用于复习提醒）"""
        with self._lock:
            memories = self._memories.get(user_id, [])
            self._update_all_strengths(user_id)
            
            # 强度在0.3-0.6之间的记忆（即将遗忘但还没完全忘记）
            fading = [m for m in memories if 0.3 < m.current_strength < 0.6
                     and m.importance != MemoryImportance.TRIVIAL.value]
            fading.sort(key=lambda m: m.current_strength)
            
            return fading[:10]  # 最多返回10条
    
    # ==================== 对话摘要记忆 ====================
    
    def save_conversation_summary(self, user_id: str,
                                   conversation_id: str,
                                   summary: str,
                                   key_points: List[str],
                                   emotions: Optional[List[str]] = None) -> Memory:
        """保存对话摘要记忆
        
        从对话中提取关键信息，形成长期记忆
        """
        title = key_points[0][:50] if key_points else summary[:50]
        
        content = f"摘要：{summary}\n\n要点：\n" + "\n".join(f"- {p}" for p in key_points)
        if emotions:
            content += f"\n\n情感：{', '.join(emotions)}"
        
        # 对话摘要默认为普通重要性
        return self.add_memory(
            user_id=user_id,
            memory_type=MemoryType.CONVERSATION.value,
            title=title,
            content=content,
            importance=MemoryImportance.NORMAL.value,
            tags=["conversation", "summary"],
            entities=[],
            source="conversation_summary",
            metadata={
                "conversation_id": conversation_id,
                "key_points": key_points,
                "emotions": emotions or [],
            }
        )
    
    def extract_and_save_facts(self, user_id: str,
                                conversation_id: str,
                                text: str,
                                facts: List[Dict[str, str]]) -> List[Memory]:
        """从对话中提取事实并保存为记忆
        
        Args:
            facts: [{"type": "fact/preference/person", "title": "...", "content": "...", "importance": "..."}]
        """
        saved = []
        for fact in facts:
            try:
                mem = self.add_memory(
                    user_id=user_id,
                    memory_type=fact.get("type", MemoryType.FACT.value),
                    title=fact.get("title", "未命名事实"),
                    content=fact.get("content", ""),
                    importance=fact.get("importance", MemoryImportance.NORMAL.value),
                    tags=fact.get("tags", []),
                    entities=fact.get("entities", []),
                    source="extracted",
                    metadata={
                        "conversation_id": conversation_id,
                        "source_text": text[:200],
                    }
                )
                saved.append(mem)
            except Exception:
                continue
        return saved


# 全局单例获取函数
_ltm_instance: Optional[LongTermMemory] = None


def get_long_term_memory() -> LongTermMemory:
    """获取长期记忆管理器单例"""
    global _ltm_instance
    if _ltm_instance is None:
        _ltm_instance = LongTermMemory()
    return _ltm_instance
