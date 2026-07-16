"""
技能进化机制 - 云汐自我进化的能力层
能力评估 + 短板发现 + 改进计划 + 成长追踪

核心能力：
1. 能力雷达图 - 多维能力评估体系
2. 短板自动发现 - 从错误/失败/用户反馈中识别能力不足
3. 改进计划生成 - 针对短板生成可执行的提升方案
4. 成长追踪 - 记录能力变化曲线
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


class SkillCategory(str, Enum):
    """能力分类"""
    # 认知能力
    REASONING = "reasoning"        # 推理能力
    KNOWLEDGE = "knowledge"        # 知识广度
    CREATIVITY = "creativity"      # 创造力
    MEMORY = "memory"              # 记忆力
    
    # 沟通能力
    EMPATHY = "empathy"            # 共情能力
    EXPRESSION = "expression"      # 表达能力
    LISTENING = "listening"        # 倾听理解
    HUMOR = "humor"                # 幽默感
    
    # 执行能力
    PLANNING = "planning"          # 规划能力
    ORGANIZATION = "organization"  # 组织能力
    EFFICIENCY = "efficiency"      # 效率
    ACCURACY = "accuracy"          # 准确性
    
    # 人格特质相关
    PATIENCE = "patience"          # 耐心
    RESILIENCE = "resilience"      # 韧性
    CURIOSITY = "curiosity"        # 好奇心
    
    # 领域知识
    TECH = "tech"                  # 技术能力
    ART = "art"                    # 艺术人文
    LIFE = "life"                  # 生活经验
    LEARNING = "learning"          # 学习能力


@dataclass
class SkillScore:
    """单项能力得分"""
    category: str  # SkillCategory.value
    score: float = 0.5  # 0.0 - 1.0
    confidence: float = 0.3
    last_updated: float = field(default_factory=time.time)
    total_assessments: int = 0
    
    # 历史记录（最近的得分变化）
    history: List[Dict[str, float]] = field(default_factory=list)
    
    def update(self, new_score: float, weight: float = 0.1):
        """更新得分"""
        old_score = self.score
        effective_weight = weight * (0.5 + self.confidence * 0.5)
        self.score = self.score * (1 - effective_weight) + new_score * effective_weight
        self.score = max(0.0, min(1.0, self.score))
        
        self.total_assessments += 1
        self.confidence = min(0.95, 0.3 + self.total_assessments * 0.02)
        self.last_updated = time.time()
        
        # 记录历史（保留最近20条）
        self.history.append({
            "time": time.time(),
            "score": self.score,
            "delta": self.score - old_score,
        })
        if len(self.history) > 20:
            self.history = self.history[-20:]
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "category": self.category,
            "score": round(self.score, 3),
            "confidence": round(self.confidence, 3),
            "last_updated": self.last_updated,
            "total_assessments": self.total_assessments,
            "recent_trend": self._calc_trend(),
        }
    
    def _calc_trend(self) -> float:
        """计算最近趋势（正值=提升，负值=下降）"""
        if len(self.history) < 2:
            return 0.0
        return self.history[-1]["score"] - self.history[0]["score"]


@dataclass
class ImprovementPlan:
    """改进计划"""
    plan_id: str
    skill_category: str
    title: str
    description: str
    priority: str = "medium"  # high/medium/low
    
    steps: List[str] = field(default_factory=list)
    expected_outcome: str = ""
    deadline: Optional[float] = None
    
    created_at: float = field(default_factory=time.time)
    status: str = "active"  # active/completed/abandoned
    progress: float = 0.0  # 0-1
    
    related_feedbacks: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "plan_id": self.plan_id,
            "skill_category": self.skill_category,
            "title": self.title,
            "description": self.description,
            "priority": self.priority,
            "steps": self.steps,
            "expected_outcome": self.expected_outcome,
            "created_at": self.created_at,
            "status": self.status,
            "progress": round(self.progress, 2),
        }


@dataclass
class FeedbackRecord:
    """反馈记录（用于能力评估）"""
    feedback_id: str
    feedback_type: str  # positive/negative/correction/suggestion
    skill_category: str
    content: str
    source: str = "user"  # user/system/auto
    user_id: str = "default"
    
    created_at: float = field(default_factory=time.time)
    processed: bool = False
    impact_score: float = 0.0  # 对能力评分的影响程度
    
    metadata: Dict[str, Any] = field(default_factory=dict)


class SkillEvolutionEngine:
    """技能进化引擎 - 单例模式"""
    
    _instance: Optional["SkillEvolutionEngine"] = None
    
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
            self._data_dir = Path.home() / ".yunxi" / "skill_evolution"
        self._data_dir.mkdir(parents=True, exist_ok=True)
        
        # 能力评分（按用户）
        self._skills: Dict[str, Dict[str, SkillScore]] = {}  # user_id -> {category: SkillScore}
        # 改进计划
        self._plans: Dict[str, List[ImprovementPlan]] = {}  # user_id -> [ImprovementPlan]
        # 反馈记录
        self._feedbacks: Dict[str, List[FeedbackRecord]] = {}  # user_id -> [FeedbackRecord]
        
        self._lock = threading.RLock()
        
        # 能力分类名称映射
        self._category_names = {
            "reasoning": "推理能力",
            "knowledge": "知识广度",
            "creativity": "创造力",
            "memory": "记忆力",
            "empathy": "共情能力",
            "expression": "表达能力",
            "listening": "倾听理解",
            "humor": "幽默感",
            "planning": "规划能力",
            "organization": "组织能力",
            "efficiency": "效率",
            "accuracy": "准确性",
            "patience": "耐心",
            "resilience": "韧性",
            "curiosity": "好奇心",
            "tech": "技术能力",
            "art": "艺术人文",
            "life": "生活经验",
            "learning": "学习能力",
        }
        
        # 初始能力基准（云汐的初始水平）
        self._base_skills = {
            "empathy": 0.8,      # 共情 - 云汐的核心能力
            "expression": 0.7,   # 表达 - 良好
            "curiosity": 0.75,   # 好奇心 - 强
            "learning": 0.7,     # 学习能力 - 良好
            "creativity": 0.65,  # 创造力 - 中等偏上
            "reasoning": 0.6,    # 推理 - 中等
            "knowledge": 0.55,   # 知识广度 - 待提升
            "accuracy": 0.6,     # 准确性 - 中等
            "patience": 0.8,     # 耐心 - 高
            "planning": 0.6,     # 规划 - 中等
            "listening": 0.75,   # 倾听 - 良好
        }
        
        # 加载数据
        self._load_all()
    
    # ==================== 存储 ====================
    
    def _get_data_file(self, user_id: str, prefix: str) -> Path:
        return self._data_dir / f"{user_id}_{prefix}.json"
    
    def _load_all(self):
        """加载所有用户数据"""
        # 加载能力评分
        for f in self._data_dir.glob("*_skills.json"):
            user_id = f.stem.replace("_skills", "")
            try:
                with open(f, "r", encoding="utf-8") as fp:
                    data = json.load(fp)
                self._skills[user_id] = {
                    k: SkillScore(**v) for k, v in data.items()
                }
            except Exception:
                pass
        
        # 加载改进计划
        for f in self._data_dir.glob("*_plans.json"):
            user_id = f.stem.replace("_plans", "")
            try:
                with open(f, "r", encoding="utf-8") as fp:
                    data = json.load(fp)
                self._plans[user_id] = [ImprovementPlan(**p) for p in data]
            except Exception:
                pass
    
    def _save_skills(self, user_id: str):
        """保存能力评分"""
        data_file = self._get_data_file(user_id, "skills")
        with self._lock:
            skills = self._skills.get(user_id, {})
            data = {k: v.to_dict() for k, v in skills.items()}
            with open(data_file, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
    
    def _save_plans(self, user_id: str):
        """保存改进计划"""
        data_file = self._get_data_file(user_id, "plans")
        with self._lock:
            plans = self._plans.get(user_id, [])
            data = [p.to_dict() for p in plans]
            with open(data_file, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
    
    # ==================== 能力评估 ====================
    
    def get_skill_scores(self, user_id: str) -> Dict[str, SkillScore]:
        """获取用户的所有能力评分"""
        with self._lock:
            if user_id not in self._skills:
                # 初始化能力评分
                self._skills[user_id] = {}
                for category, base_score in self._base_skills.items():
                    self._skills[user_id][category] = SkillScore(
                        category=category,
                        score=base_score,
                        confidence=0.3,
                    )
                self._save_skills(user_id)
            return self._skills[user_id]
    
    def get_skill_radar(self, user_id: str) -> Dict[str, Any]:
        """获取能力雷达图数据"""
        skills = self.get_skill_scores(user_id)
        
        # 分类聚合
        groups = {
            "认知能力": ["reasoning", "knowledge", "creativity", "memory"],
            "沟通能力": ["empathy", "expression", "listening", "humor"],
            "执行能力": ["planning", "organization", "efficiency", "accuracy"],
            "人格特质": ["patience", "resilience", "curiosity"],
            "领域知识": ["tech", "art", "life", "learning"],
        }
        
        radar = {}
        for group_name, categories in groups.items():
            scores = []
            for cat in categories:
                if cat in skills:
                    scores.append(skills[cat].score)
            if scores:
                radar[group_name] = round(sum(scores) / len(scores), 3)
        
        # 总体评分
        all_scores = [s.score for s in skills.values()]
        overall = round(sum(all_scores) / len(all_scores), 3) if all_scores else 0.5
        
        # 找出最强和最弱的能力
        sorted_skills = sorted(skills.values(), key=lambda x: x.score, reverse=True)
        strengths = [s.category for s in sorted_skills[:3]]
        weaknesses = [s.category for s in sorted_skills[-3:]]
        
        return {
            "overall_score": overall,
            "groups": radar,
            "individual_skills": {k: v.to_dict() for k, v in skills.items()},
            "strengths": strengths,
            "weaknesses": weaknesses,
            "total_assessments": sum(s.total_assessments for s in skills.values()),
        }
    
    # ==================== 反馈处理 ====================
    
    def record_feedback(self, user_id: str,
                        feedback_type: str,
                        skill_category: str,
                        content: str,
                        impact: float = 0.05) -> FeedbackRecord:
        """记录反馈并更新能力评分
        
        Args:
            feedback_type: positive/negative/correction/suggestion
            skill_category: 影响的能力分类
            content: 反馈内容
            impact: 影响程度（0-1）
        
        Returns:
            FeedbackRecord对象
        """
        record = FeedbackRecord(
            feedback_id=f"fb_{uuid.uuid4().hex[:12]}",
            feedback_type=feedback_type,
            skill_category=skill_category,
            content=content,
            user_id=user_id,
            impact_score=impact,
        )
        
        with self._lock:
            if user_id not in self._feedbacks:
                self._feedbacks[user_id] = []
            self._feedbacks[user_id].append(record)
        
        # 更新能力评分
        skills = self.get_skill_scores(user_id)
        with self._lock:
            if skill_category in skills:
                if feedback_type == "positive":
                    # 正向反馈：提升评分
                    delta = impact * (1.0 - skills[skill_category].score) * 0.5
                    new_score = skills[skill_category].score + delta
                    skills[skill_category].update(new_score, weight=0.1)
                elif feedback_type in ["negative", "correction"]:
                    # 负向反馈/纠正：降低评分（但降低幅度小，因为要鼓励成长）
                    delta = impact * skills[skill_category].score * 0.3
                    new_score = skills[skill_category].score - delta
                    skills[skill_category].update(new_score, weight=0.15)
        
        self._save_skills(user_id)
        
        # 检查是否需要生成改进计划
        self._check_for_improvement_needs(user_id)
        
        return record
    
    def process_user_message_for_feedback(self, user_id: str,
                                            user_message: str,
                                            assistant_reply: str,
                                            conversation_id: str = ""):
        """从用户消息中自动检测反馈信号
        
        分析用户消息，检测是否包含正向/负向反馈
        """
        user_lower = user_message.lower()
        
        # 正向反馈关键词
        positive_patterns = [
            (r"(谢谢|感谢|你真好|太棒了|太赞了|真厉害|好棒|厉害)", "empathy", 0.08),
            (r"(说的对|有道理|我明白了|原来是这样|学到了|涨知识)", "knowledge", 0.05),
            (r"(你真懂我|你太了解我了|说到我心里了)", "listening", 0.08),
            (r"(太暖心了|好温暖|感动到了|哭了)", "empathy", 0.06),
            (r"(好有趣|哈哈|笑死了|太搞笑)", "humor", 0.07),
            (r"(安排得好|很清晰|有条理|很系统)", "planning", 0.06),
        ]
        
        # 负向反馈关键词
        negative_patterns = [
            (r"(不对|错了|你错了|不是这样|说的不对)", "accuracy", 0.06),
            (r"(不懂|没明白|没听懂|解释不清楚|太复杂)", "expression", 0.05),
            (r"(答非所问|不对题|跑题了|不相关)", "listening", 0.05),
            (r"(太慢了|等好久|能不能快点)", "efficiency", 0.04),
            (r"(太敷衍了|就这|没用|没意思)", "quality", 0.06),
        ]
        
        # 检测正向反馈
        for pattern, category, impact in positive_patterns:
            if re.search(pattern, user_lower):
                self.record_feedback(
                    user_id=user_id,
                    feedback_type="positive",
                    skill_category=category,
                    content=user_message[:100],
                    impact=impact,
                )
                break  # 一条消息只记录一次主要反馈
        
        # 检测负向反馈
        for pattern, category, impact in negative_patterns:
            if re.search(pattern, user_lower):
                self.record_feedback(
                    user_id=user_id,
                    feedback_type="correction",
                    skill_category=category,
                    content=user_message[:100],
                    impact=impact,
                )
                break
    
    # ==================== 改进计划 ====================
    
    def _check_for_improvement_needs(self, user_id: str):
        """检查是否需要生成新的改进计划"""
        skills = self.get_skill_scores(user_id)
        plans = self._plans.get(user_id, [])
        active_plans = [p for p in plans if p.status == "active"]
        
        # 找出评分最低且置信度足够高的能力
        low_skills = [
            (cat, s) for cat, s in skills.items()
            if s.score < 0.5 and s.confidence > 0.4 and s.total_assessments >= 3
        ]
        low_skills.sort(key=lambda x: x[1].score)
        
        # 最多同时有3个活跃的改进计划
        if len(active_plans) < 3 and low_skills:
            for cat, skill in low_skills[:3 - len(active_plans)]:
                # 检查是否已有该类别的活跃计划
                existing = any(p.skill_category == cat for p in active_plans)
                if not existing:
                    plan = self._generate_improvement_plan(cat, skill.score)
                    with self._lock:
                        if user_id not in self._plans:
                            self._plans[user_id] = []
                        self._plans[user_id].append(plan)
                    self._save_plans(user_id)
    
    def _generate_improvement_plan(self, skill_category: str,
                                    current_score: float) -> ImprovementPlan:
        """生成改进计划"""
        plan_templates = {
            "accuracy": {
                "title": "提升回答准确性",
                "description": "减少事实性错误，提升信息准确度",
                "priority": "high",
                "steps": [
                    "回答前先核实关键信息的准确性",
                    "对于不确定的内容明确说明，不编造",
                    "引用来源时确保可靠",
                    "用户纠正时认真记录并学习",
                    "定期回顾错误记录，总结规律",
                ],
                "expected_outcome": "准确性评分提升至0.6以上",
            },
            "expression": {
                "title": "提升表达清晰度",
                "description": "让回答更有条理、更容易理解",
                "priority": "medium",
                "steps": [
                    "复杂问题使用分点、分步骤的结构",
                    "先给出核心结论，再展开细节",
                    "用比喻和例子帮助理解抽象概念",
                    "根据用户调整表达深度",
                    "回答后检查是否清晰易懂",
                ],
                "expected_outcome": "表达能力评分提升至0.7以上",
            },
            "knowledge": {
                "title": "扩展知识广度",
                "description": "积累更多领域的知识，提升回答深度",
                "priority": "medium",
                "steps": [
                    "从用户提问中学习新知识",
                    "建立知识卡片系统，分类整理",
                    "定期复习已学知识，巩固记忆",
                    "关注新知识领域，保持好奇心",
                    "将不同领域的知识关联起来",
                ],
                "expected_outcome": "知识广度评分提升至0.6以上",
            },
            "efficiency": {
                "title": "提升响应效率",
                "description": "更快地给出高质量回答",
                "priority": "low",
                "steps": [
                    "快速抓住问题核心，避免冗余",
                    "常用问题建立快速回答模板",
                    "优化思考流程，减少不必要的步骤",
                    "平衡速度与质量，不因快而牺牲准确性",
                ],
                "expected_outcome": "效率评分提升至0.6以上",
            },
        }
        
        # 默认模板
        default_template = {
            "title": f"提升{self._category_names.get(skill_category, skill_category)}",
            "description": f"针对性提升{self._category_names.get(skill_category, skill_category)}",
            "priority": "medium",
            "steps": [
                "识别该能力的具体短板",
                "制定可执行的提升步骤",
                "在实践中刻意练习",
                "定期复盘和调整策略",
                "持续迭代改进",
            ],
            "expected_outcome": "能力评分有可观测的提升",
        }
        
        template = plan_templates.get(skill_category, default_template)
        
        return ImprovementPlan(
            plan_id=f"plan_{uuid.uuid4().hex[:12]}",
            skill_category=skill_category,
            title=template["title"],
            description=template["description"],
            priority=template["priority"],
            steps=template["steps"],
            expected_outcome=template["expected_outcome"],
        )
    
    def get_improvement_plans(self, user_id: str,
                               status: Optional[str] = None) -> List[ImprovementPlan]:
        """获取改进计划"""
        with self._lock:
            plans = self._plans.get(user_id, [])
            if status:
                plans = [p for p in plans if p.status == status]
            plans.sort(key=lambda p: p.created_at, reverse=True)
            return plans
    
    def update_plan_progress(self, user_id: str, plan_id: str,
                              progress: float) -> bool:
        """更新改进计划进度"""
        with self._lock:
            plans = self._plans.get(user_id, [])
            for plan in plans:
                if plan.plan_id == plan_id:
                    plan.progress = max(0.0, min(1.0, progress))
                    if plan.progress >= 1.0:
                        plan.status = "completed"
                    self._save_plans(user_id)
                    return True
        return False
    
    # ==================== 成长报告 ====================
    
    def get_growth_report(self, user_id: str) -> Dict[str, Any]:
        """生成成长报告"""
        radar = self.get_skill_radar(user_id)
        plans = self.get_improvement_plans(user_id)
        active_plans = [p for p in plans if p.status == "active"]
        completed_plans = [p for p in plans if p.status == "completed"]
        
        # 计算成长趋势
        skills = self.get_skill_scores(user_id)
        trends = {}
        for cat, skill in skills.items():
            trend = skill._calc_trend()
            if trend != 0:
                trends[cat] = trend
        
        improved = sum(1 for t in trends.values() if t > 0)
        declined = sum(1 for t in trends.values() if t < 0)
        
        return {
            "overall_score": radar["overall_score"],
            "strengths": radar["strengths"],
            "weaknesses": radar["weaknesses"],
            "active_improvement_plans": len(active_plans),
            "completed_plans": len(completed_plans),
            "growth_trend": {
                "improved_skills": improved,
                "declined_skills": declined,
                "trends": {k: round(v, 4) for k, v in trends.items()},
            },
            "total_feedbacks_processed": sum(
                s.total_assessments for s in skills.values()
            ),
        }


# 全局单例获取函数
_skill_evo_instance: Optional[SkillEvolutionEngine] = None


def get_skill_evolution_engine() -> SkillEvolutionEngine:
    """获取技能进化引擎单例"""
    global _skill_evo_instance
    if _skill_evo_instance is None:
        _skill_evo_instance = SkillEvolutionEngine()
    return _skill_evo_instance
