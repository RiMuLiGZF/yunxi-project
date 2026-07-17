"""
多Agent协作系统 - 云汐智能体团队
专业Agent基类 + 团队管理 + 任务分发 + 结果整合

核心设计：
1. 专业Agent基类 - 统一接口，每个Agent有专长领域
2. Agent团队 - 多个专业Agent组成团队，由主控协调
3. 任务分发 - 根据任务类型自动分配给最合适的Agent
4. 并行协作 - 多个Agent并行处理不同子任务
5. 结果整合 - 将各Agent的输出整合为最终答案
"""

import re
import json
import time
import uuid
import asyncio
import threading
from abc import ABC, abstractmethod
from enum import Enum
from dataclasses import dataclass, field
from typing import Optional, List, Dict, Any, Tuple, Callable
from concurrent.futures import ThreadPoolExecutor, as_completed


class AgentSpecialty(str, Enum):
    """Agent专长领域"""
    GENERAL = "general"         # 通用
    RESEARCH = "research"       # 研究调研
    WRITING = "writing"         # 文案写作
    ANALYSIS = "analysis"       # 分析诊断
    CREATIVE = "creative"       # 创意构思
    EXECUTION = "execution"     # 执行操作
    CRITIQUE = "critique"       # 评审优化


class TaskType(str, Enum):
    """任务类型"""
    RESEARCH = "research"       # 调研查询
    WRITING = "writing"         # 写作创作
    ANALYSIS = "analysis"       # 分析诊断
    BRAINSTORM = "brainstorm"   # 头脑风暴
    EXECUTION = "execution"     # 执行操作
    REVIEW = "review"           # 评审优化
    COMPLEX = "complex"         # 复杂综合任务


@dataclass
class AgentTask:
    """Agent任务"""
    task_id: str
    task_type: str
    description: str
    context: Dict[str, Any] = field(default_factory=dict)
    priority: int = 5  # 1-10，越高越优先
    assigned_to: Optional[str] = None
    status: str = "pending"  # pending/running/completed/failed
    result: Optional[Any] = None
    error: Optional[str] = None
    start_time: Optional[float] = None
    end_time: Optional[float] = None
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "task_id": self.task_id,
            "task_type": self.task_type,
            "description": self.description,
            "priority": self.priority,
            "assigned_to": self.assigned_to,
            "status": self.status,
            "result": str(self.result)[:200] if self.result else None,
            "error": self.error,
            "execution_time": (
                round(self.end_time - self.start_time, 3)
                if self.start_time and self.end_time else None
            ),
        }


@dataclass
class AgentResult:
    """Agent执行结果"""
    agent_name: str
    success: bool
    output: str = ""
    data: Optional[Any] = None
    error: Optional[str] = None
    execution_time: float = 0.0
    confidence: float = 0.8  # 结果置信度
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "agent_name": self.agent_name,
            "success": self.success,
            "output": self.output,
            "data": self.data,
            "error": self.error,
            "execution_time": round(self.execution_time, 3),
            "confidence": self.confidence,
        }


@dataclass
class TeamResult:
    """团队协作结果"""
    success: bool
    final_answer: str = ""
    tasks: List[AgentTask] = field(default_factory=list)
    agent_results: List[AgentResult] = field(default_factory=list)
    total_time: float = 0.0
    agents_involved: List[str] = field(default_factory=list)
    error: Optional[str] = None
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "success": self.success,
            "final_answer": self.final_answer,
            "tasks": [t.to_dict() for t in self.tasks],
            "agent_results": [r.to_dict() for r in self.agent_results],
            "total_time": round(self.total_time, 3),
            "agents_involved": self.agents_involved,
            "error": self.error,
        }


class BaseAgent(ABC):
    """专业Agent基类
    
    所有专业Agent都继承自此类
    """
    
    name: str = ""
    description: str = ""
    specialty: str = AgentSpecialty.GENERAL.value
    
    # Agent特质
    strengths: List[str] = field(default_factory=list)  # 擅长什么
    limitations: List[str] = field(default_factory=list)  # 不擅长什么
    working_style: str = "严谨高效"  # 工作风格
    
    # 配置
    timeout: float = 60.0
    max_retries: int = 2
    
    def __init__(self):
        self._call_count = 0
        self._total_time = 0.0
        self._lock = threading.Lock()
    
    @abstractmethod
    def execute(self, task: AgentTask, context: Optional[Dict[str, Any]] = None) -> AgentResult:
        """执行任务
        
        子类必须实现此方法
        """
        pass
    
    def can_handle(self, task_type: str, description: str) -> float:
        """评估能否处理某任务，返回置信度 0-1
        
        默认基于专长匹配，子类可以重写
        """
        specialty_map = {
            AgentSpecialty.RESEARCH.value: [TaskType.RESEARCH.value],
            AgentSpecialty.WRITING.value: [TaskType.WRITING.value],
            AgentSpecialty.ANALYSIS.value: [TaskType.ANALYSIS.value, TaskType.REVIEW.value],
            AgentSpecialty.CREATIVE.value: [TaskType.BRAINSTORM.value, TaskType.WRITING.value],
            AgentSpecialty.EXECUTION.value: [TaskType.EXECUTION.value],
            AgentSpecialty.CRITIQUE.value: [TaskType.REVIEW.value],
            AgentSpecialty.GENERAL.value: [t.value for t in TaskType],
        }
        
        supported = specialty_map.get(self.specialty, [])
        if task_type in supported:
            return 0.7  # 基础匹配度
        return 0.2  # 不匹配但可以试试
    
    def get_profile(self) -> Dict[str, Any]:
        """获取Agent简介"""
        return {
            "name": self.name,
            "description": self.description,
            "specialty": self.specialty,
            "strengths": self.strengths,
            "limitations": self.limitations,
            "working_style": self.working_style,
            "timeout": self.timeout,
        }
    
    def _record_execution(self, execution_time: float):
        """记录执行统计"""
        with self._lock:
            self._call_count += 1
            self._total_time += execution_time
    
    def get_stats(self) -> Dict[str, Any]:
        """获取统计信息"""
        with self._lock:
            return {
                "name": self.name,
                "total_calls": self._call_count,
                "avg_execution_time": (
                    round(self._total_time / self._call_count, 3)
                    if self._call_count > 0 else 0
                ),
            }


class AgentTeam:
    """Agent团队 - 管理多个专业Agent
    
    负责Agent注册、任务分发、并行执行、结果整合
    """
    
    def __init__(self, team_name: str = "云汐团队"):
        self.team_name = team_name
        self._agents: Dict[str, BaseAgent] = {}
        self._lock = threading.RLock()
        
        # 任务历史
        self._task_history: List[AgentTask] = []
        self._max_history = 100
        
        # 线程池（用于并行执行）
        self._executor = ThreadPoolExecutor(max_workers=4)
    
    def register_agent(self, agent: BaseAgent) -> bool:
        """注册Agent"""
        with self._lock:
            if agent.name in self._agents:
                return False
            self._agents[agent.name] = agent
            return True
    
    def unregister_agent(self, agent_name: str) -> bool:
        """注销Agent"""
        with self._lock:
            if agent_name in self._agents:
                del self._agents[agent_name]
                return True
            return False
    
    def get_agent(self, agent_name: str) -> Optional[BaseAgent]:
        """获取指定Agent"""
        with self._lock:
            return self._agents.get(agent_name)
    
    def list_agents(self) -> List[BaseAgent]:
        """列出所有Agent"""
        with self._lock:
            return list(self._agents.values())
    
    def get_team_profile(self) -> Dict[str, Any]:
        """获取团队简介"""
        agents = self.list_agents()
        specialties = list(set(a.specialty for a in agents))
        return {
            "team_name": self.team_name,
            "total_agents": len(agents),
            "specialties": specialties,
            "agents": [a.get_profile() for a in agents],
        }
    
    def classify_task(self, description: str) -> Tuple[str, float]:
        """任务分类
        
        Returns:
            (任务类型, 置信度)
        """
        desc = description.lower()
        
        # 各类型的关键词
        type_keywords = {
            TaskType.RESEARCH.value: [
                "调研", "研究", "调查", "查询", "搜索", "查找", "了解",
                "什么是", "介绍一下", "资料", "信息", "分析一下",
                "research", "search", "find", "investigate",
            ],
            TaskType.WRITING.value: [
                "写", "撰写", "创作", "生成", "文案", "文章", "邮件",
                "报告", "总结", "写一个", "帮我写", "起草",
                "write", "generate", "create", "draft",
            ],
            TaskType.ANALYSIS.value: [
                "分析", "诊断", "评估", "判断", "原因", "为什么",
                "怎么回事", "问题", "数据", "统计",
                "analyze", "diagnose", "evaluate",
            ],
            TaskType.BRAINSTORM.value: [
                "创意", "想法", "点子", "构思", "头脑风暴", "策划",
                "方案", "设计", "灵感", "想几个",
                "brainstorm", "ideas", "creative",
            ],
            TaskType.EXECUTION.value: [
                "执行", "操作", "计算", "运行", "处理",
                "帮我做", "去做", "完成",
                "execute", "run", "do", "calculate",
            ],
            TaskType.REVIEW.value: [
                "评审", "优化", "改进", "修改", "润色",
                "检查", "审核", "反馈", "建议",
                "review", "optimize", "improve", "feedback",
            ],
        }
        
        scores = {}
        for task_type, keywords in type_keywords.items():
            score = sum(1 for kw in keywords if kw in desc)
            scores[task_type] = score
        
        # 找出最高分
        max_score = max(scores.values()) if scores else 0
        if max_score == 0:
            return TaskType.COMPLEX.value, 0.3
        
        best_types = [t for t, s in scores.items() if s == max_score]
        best_type = best_types[0]
        
        # 计算置信度
        confidence = min(max_score / 5.0, 1.0)
        
        return best_type, confidence
    
    def find_best_agent(self, task_type: str,
                        description: str) -> Optional[Tuple[str, float]]:
        """找到最适合的Agent
        
        Returns:
            (Agent名称, 匹配置信度)
        """
        agents = self.list_agents()
        if not agents:
            return None
        
        best_agent = None
        best_score = 0
        
        for agent in agents:
            score = agent.can_handle(task_type, description)
            if score > best_score:
                best_score = score
                best_agent = agent.name
        
        if best_agent:
            return best_agent, best_score
        return None
    
    def assign_task(self, task: AgentTask, context: Optional[Dict[str, Any]] = None) -> AgentResult:
        """分配并执行单个任务"""
        # 找最合适的Agent
        best = self.find_best_agent(task.task_type, task.description)
        if not best:
            return AgentResult(
                agent_name="unknown",
                success=False,
                error="没有找到合适的Agent来处理此任务",
            )
        
        agent_name, confidence = best
        agent = self.get_agent(agent_name)
        if not agent:
            return AgentResult(
                agent_name=agent_name,
                success=False,
                error=f"Agent {agent_name} 不存在",
            )
        
        task.assigned_to = agent_name
        task.status = "running"
        task.start_time = time.time()
        
        try:
            result = agent.execute(task, context)
            task.status = "completed" if result.success else "failed"
            task.result = result.output
            task.error = result.error
        except Exception as e:
            result = AgentResult(
                agent_name=agent_name,
                success=False,
                error=f"执行异常: {str(e)}",
            )
            task.status = "failed"
            task.error = str(e)
        
        task.end_time = time.time()
        
        # 记录历史
        with self._lock:
            self._task_history.append(task)
            if len(self._task_history) > self._max_history:
                self._task_history = self._task_history[-self._max_history:]
        
        return result
    
    def execute_parallel(self, tasks: List[AgentTask],
                         context: Optional[Dict[str, Any]] = None) -> List[AgentResult]:
        """并行执行多个任务"""
        results = []
        
        def run_task(task):
            return self.assign_task(task, context)
        
        futures = []
        for task in tasks:
            future = self._executor.submit(run_task, task)
            futures.append(future)
        
        for future in as_completed(futures):
            results.append(future.result())
        
        return results
    
    def handle_query(self, query: str,
                     context: Optional[Dict[str, Any]] = None) -> TeamResult:
        """处理用户查询（团队协作）
        
        1. 分析查询，确定任务类型
        2. 如果是简单任务，单个Agent处理
        3. 如果是复杂任务，分解为多个子任务，并行执行
        4. 整合结果，生成最终答案
        """
        start_time = time.time()
        context = context or {}
        tasks: List[AgentTask] = []
        agent_results: List[AgentResult] = []
        agents_involved: List[str] = []
        
        try:
            # 1. 任务分类
            task_type, confidence = self.classify_task(query)
            
            # 2. 判断任务复杂度
            is_complex = self._is_complex_task(query, task_type, confidence)
            
            if is_complex:
                # 复杂任务：分解为多个子任务
                subtasks = self._decompose_task(query, task_type)
                tasks = subtasks
                
                # 并行执行子任务
                results = self.execute_parallel(subtasks, context)
                agent_results = results
                agents_involved = list(set(r.agent_name for r in results))
                
                # 整合结果
                final_answer = self._synthesize_results(query, task_type, results)
            else:
                # 简单任务：单个Agent处理
                task = AgentTask(
                    task_id=str(uuid.uuid4())[:8],
                    task_type=task_type,
                    description=query,
                    priority=5,
                )
                tasks.append(task)
                
                result = self.assign_task(task, context)
                agent_results.append(result)
                agents_involved.append(result.agent_name)
                
                final_answer = self._format_single_result(query, result, task_type)
            
            total_time = time.time() - start_time
            
            return TeamResult(
                success=True,
                final_answer=final_answer,
                tasks=tasks,
                agent_results=agent_results,
                total_time=total_time,
                agents_involved=agents_involved,
            )
            
        except Exception as e:
            total_time = time.time() - start_time
            return TeamResult(
                success=False,
                error=str(e),
                tasks=tasks,
                agent_results=agent_results,
                total_time=total_time,
                agents_involved=agents_involved,
            )
    
    def _is_complex_task(self, query: str, task_type: str,
                         confidence: float) -> bool:
        """判断是否是复杂任务"""
        # 极短文本（<10字）通常是简单对话，直接返回False
        if len(query) < 10:
            return False
        
        # 长文本（>100字）通常是复杂任务
        if len(query) > 100:
            return True
        
        # 检查是否有多个任务信号（更精确的模式）
        multi_patterns = [
            r'既要.*又要',
            r'一方面.*另一方面',
            r'不仅.*还.*还',
            r'.*并且.*方案',
            r'先.*再.*然后',
            r'全面.*分析',
            r'综合.*分析',
            r'深度.*分析',
            r'调研.*并且',
            r'分析.*并且.*方案',
            r'团队.*一起',
            r'组织.*分析',
        ]
        for pattern in multi_patterns:
            if re.search(pattern, query):
                return True
        
        # 包含多个明确的任务动词
        task_verbs = ["分析", "调研", "写", "策划", "设计", "计算", "评估", "方案", "总结", "报告"]
        verb_count = sum(1 for v in task_verbs if v in query)
        if verb_count >= 3:
            return True
        
        # 置信度低且类型为complex（但文本长度中等）
        if confidence < 0.4 and task_type == TaskType.COMPLEX.value and len(query) > 30:
            return True
        
        return False
    
    def _decompose_task(self, query: str, task_type: str) -> List[AgentTask]:
        """将复杂任务分解为子任务
        
        简单实现：根据任务类型生成1-3个子任务
        """
        subtasks = []
        
        # 研究+分析+方案 的组合
        if task_type in [TaskType.COMPLEX.value, TaskType.ANALYSIS.value]:
            # 1. 调研任务
            subtasks.append(AgentTask(
                task_id=str(uuid.uuid4())[:8],
                task_type=TaskType.RESEARCH.value,
                description=f"调研以下问题的背景信息：{query}",
                priority=8,
            ))
            
            # 2. 分析任务
            subtasks.append(AgentTask(
                task_id=str(uuid.uuid4())[:8],
                task_type=TaskType.ANALYSIS.value,
                description=f"分析以下问题：{query}",
                priority=7,
            ))
            
            # 3. 如果是创意类，加头脑风暴
            if "创意" in query or "方案" in query or "设计" in query:
                subtasks.append(AgentTask(
                    task_id=str(uuid.uuid4())[:8],
                    task_type=TaskType.BRAINSTORM.value,
                    description=f"针对以下问题构思创意方案：{query}",
                    priority=6,
                ))
        
        elif task_type == TaskType.WRITING.value:
            # 写作：创意构思 + 文案撰写 + 评审优化
            subtasks.append(AgentTask(
                task_id=str(uuid.uuid4())[:8],
                task_type=TaskType.BRAINSTORM.value,
                description=f"为以下写作任务构思创意方向：{query}",
                priority=6,
            ))
            subtasks.append(AgentTask(
                task_id=str(uuid.uuid4())[:8],
                task_type=TaskType.WRITING.value,
                description=f"完成以下写作任务：{query}",
                priority=8,
            ))
        
        else:
            # 默认：单个任务
            subtasks.append(AgentTask(
                task_id=str(uuid.uuid4())[:8],
                task_type=task_type,
                description=query,
                priority=5,
            ))
        
        return subtasks
    
    def _synthesize_results(self, query: str, task_type: str,
                            results: List[AgentResult]) -> str:
        """整合多个Agent的结果"""
        successful = [r for r in results if r.success]
        failed = [r for r in results if not r.success]
        
        if not successful:
            return "抱歉，所有Agent都未能完成任务。"
        
        # 按Agent类型组织结果
        parts = []
        for i, result in enumerate(successful, 1):
            parts.append(f"【{result.agent_name}】\n{result.output}")
        
        combined = "\n\n".join(parts)
        
        if failed:
            failed_names = [f.agent_name for f in failed]
            combined += f"\n\n（注：{', '.join(failed_names)} 未能完成任务）"
        
        # 生成总结
        summary = f"针对你的问题「{query[:50]}...」，我组织了团队协作：\n\n{combined}\n\n以上是各专业Agent的分析结果，希望对你有帮助！"
        
        return summary
    
    def _format_single_result(self, query: str, result: AgentResult,
                              task_type: str) -> str:
        """格式化单个Agent的结果"""
        if result.success:
            return result.output
        else:
            return f"抱歉，任务未能完成：{result.error}"
    
    def get_stats(self) -> Dict[str, Any]:
        """获取团队统计"""
        agents = self.list_agents()
        
        with self._lock:
            total_tasks = len(self._task_history)
            completed = sum(1 for t in self._task_history if t.status == "completed")
            failed = sum(1 for t in self._task_history if t.status == "failed")
        
        agent_stats = [a.get_stats() for a in agents]
        
        return {
            "team_name": self.team_name,
            "total_agents": len(agents),
            "total_tasks": total_tasks,
            "completed_tasks": completed,
            "failed_tasks": failed,
            "success_rate": completed / total_tasks if total_tasks > 0 else 0,
            "agent_stats": agent_stats,
        }
    
    def get_task_history(self, limit: int = 20) -> List[Dict[str, Any]]:
        """获取任务历史"""
        with self._lock:
            return [t.to_dict() for t in reversed(self._task_history[-limit:])]


# 全局单例
_team_instance: Optional[AgentTeam] = None


def get_agent_team() -> AgentTeam:
    """获取Agent团队单例"""
    global _team_instance
    if _team_instance is None:
        _team_instance = AgentTeam()
    return _team_instance
