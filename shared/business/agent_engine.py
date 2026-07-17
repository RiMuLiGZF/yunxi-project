"""
Agent执行引擎 - 云汐智能体核心
ReAct模式：推理(Reasoning) + 行动(Action) + 观察(Observation)

核心能力：
1. 任务理解 - 解析用户需求，判断是否需要调用工具
2. 工具选择 - 智能选择合适的工具
3. 多步推理 - ReAct循环，逐步完成复杂任务
4. 结果整合 - 将工具结果整合为自然语言回复
5. 安全控制 - 最大步数、超时、工具白名单
"""

import re
import json
import time
import uuid
import asyncio
import threading
from enum import Enum
from dataclasses import dataclass, field
from typing import Optional, List, Dict, Any, Tuple, Callable
from datetime import datetime


class AgentStepType(str, Enum):
    """Agent步骤类型"""
    THOUGHT = "thought"       # 思考
    ACTION = "action"         # 行动（调用工具）
    OBSERVATION = "observation"  # 观察（工具结果）
    ANSWER = "answer"         # 最终答案


@dataclass
class AgentStep:
    """Agent执行步骤"""
    step_type: str
    content: str
    timestamp: float = field(default_factory=time.time)
    tool_name: Optional[str] = None
    tool_params: Optional[Dict[str, Any]] = None
    tool_result: Optional[Any] = None
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "step_type": self.step_type,
            "content": self.content,
            "timestamp": self.timestamp,
            "tool_name": self.tool_name,
            "tool_params": self.tool_params,
        }


@dataclass
class AgentResult:
    """Agent执行结果"""
    success: bool
    answer: str = ""
    steps: List[AgentStep] = field(default_factory=list)
    total_steps: int = 0
    execution_time: float = 0.0
    tools_used: List[str] = field(default_factory=list)
    error: Optional[str] = None
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "success": self.success,
            "answer": self.answer,
            "steps": [s.to_dict() for s in self.steps],
            "total_steps": self.total_steps,
            "execution_time": round(self.execution_time, 3),
            "tools_used": self.tools_used,
            "error": self.error,
        }


class AgentEngine:
    """Agent执行引擎
    
    实现ReAct模式的智能体执行引擎
    """
    
    def __init__(self, max_steps: int = 8, timeout: float = 120.0):
        self.max_steps = max_steps
        self.timeout = timeout
        
        # 工具选择策略
        self._tool_selection_enabled = True
        
        # 执行历史
        self._execution_history: Dict[str, AgentResult] = {}
        self._max_history = 50
        self._lock = threading.RLock()
    
    def run(self, query: str,
            context: Optional[Dict[str, Any]] = None,
            available_tools: Optional[List[str]] = None,
            system_prompt: Optional[str] = None) -> AgentResult:
        """执行Agent任务（同步）
        
        Args:
            query: 用户查询/任务
            context: 上下文信息（user_id, conversation_id等）
            available_tools: 可用工具名称列表，None表示全部可用
            system_prompt: 自定义系统提示词
        
        Returns:
            AgentResult
        """
        start_time = time.time()
        steps: List[AgentStep] = []
        tools_used: List[str] = []
        context = context or {}
        
        # 获取可用工具
        from .tool_system import get_tool_registry
        from .builtin_tools import _ensure_registered
        _ensure_registered()
        
        registry = get_tool_registry()
        all_tools = registry.list_tools()
        
        if available_tools:
            tools = [t for t in all_tools if t.name in available_tools]
        else:
            tools = all_tools
        
        # 生成工具描述
        tool_descriptions = [t.get_description_for_llm() for t in tools]
        tool_names = [t.name for t in tools]
        
        # 构建系统提示
        sys_prompt = system_prompt or self._build_system_prompt(tool_descriptions)
        
        # 初始化对话历史
        messages = [
            {"role": "system", "content": sys_prompt},
            {"role": "user", "content": query},
        ]
        
        # ReAct循环
        current_step = 0
        final_answer = ""
        error = None
        
        try:
            while current_step < self.max_steps:
                # 超时检查
                if time.time() - start_time > self.timeout:
                    error = "执行超时"
                    break
                
                # 生成下一步（思考或行动）
                step_content, action_tool, action_params = self._parse_next_step(
                    messages, tool_names
                )
                
                if not step_content:
                    step_content = "继续思考..."
                
                # 记录思考步骤
                thought_step = AgentStep(
                    step_type=AgentStepType.THOUGHT.value,
                    content=step_content,
                )
                steps.append(thought_step)
                current_step += 1
                
                # 检查是否是最终答案
                if self._is_final_answer(step_content):
                    final_answer = self._extract_final_answer(step_content)
                    steps.append(AgentStep(
                        step_type=AgentStepType.ANSWER.value,
                        content=final_answer,
                    ))
                    break
                
                # 如果没有工具调用，直接生成回答
                if not action_tool:
                    # 没有行动，直接返回思考内容作为回答
                    final_answer = step_content
                    steps.append(AgentStep(
                        step_type=AgentStepType.ANSWER.value,
                        content=final_answer,
                    ))
                    break
                
                # 执行工具
                action_step = AgentStep(
                    step_type=AgentStepType.ACTION.value,
                    content=f"调用工具: {action_tool}",
                    tool_name=action_tool,
                    tool_params=action_params,
                )
                steps.append(action_step)
                current_step += 1
                
                # 调用工具
                tool_result = registry.call_tool(action_tool, action_params, context)
                tools_used.append(action_tool)
                
                # 记录观察
                obs_content = tool_result.output if tool_result.success else f"错误: {tool_result.error}"
                obs_step = AgentStep(
                    step_type=AgentStepType.OBSERVATION.value,
                    content=obs_content,
                    tool_name=action_tool,
                    tool_result=tool_result,
                )
                steps.append(obs_step)
                current_step += 1
                
                # 将工具结果加入对话历史
                messages.append({
                    "role": "assistant",
                    "content": f"思考：{step_content}\n\n行动：{action_tool}({json.dumps(action_params, ensure_ascii=False)})",
                })
                messages.append({
                    "role": "user",
                    "content": f"观察结果：{obs_content}",
                })
                
                # 检查是否超出步数
                if current_step >= self.max_steps:
                    final_answer = self._synthesize_answer(steps, query)
                    steps.append(AgentStep(
                        step_type=AgentStepType.ANSWER.value,
                        content=final_answer,
                    ))
                    break
            
            # 如果循环结束还没有答案，综合生成
            if not final_answer and not error:
                final_answer = self._synthesize_answer(steps, query)
                steps.append(AgentStep(
                    step_type=AgentStepType.ANSWER.value,
                    content=final_answer,
                ))
        
        except Exception as e:
            error = f"执行异常: {str(e)}"
        
        # 构建结果
        result = AgentResult(
            success=error is None,
            answer=final_answer,
            steps=steps,
            total_steps=len(steps),
            execution_time=time.time() - start_time,
            tools_used=list(set(tools_used)),
            error=error,
        )
        
        # 记录历史
        exec_id = str(uuid.uuid4())[:8]
        with self._lock:
            self._execution_history[exec_id] = result
            if len(self._execution_history) > self._max_history:
                oldest = list(self._execution_history.keys())[0]
                del self._execution_history[oldest]
        
        return result
    
    def _build_system_prompt(self, tool_descriptions: List[Dict[str, Any]]) -> str:
        """构建系统提示词"""
        tools_json = json.dumps(tool_descriptions, ensure_ascii=False, indent=2)
        
        return f"""你是云汐，一个聪明能干的AI助手。你可以使用工具来帮助用户完成任务。

## 可用工具
以下是你可以使用的工具列表：

{tools_json}

## 工作方式
你采用"思考-行动-观察"的循环方式工作：
1. 思考(Thought)：分析用户问题，决定下一步做什么
2. 行动(Action)：如果需要，调用一个工具来获取信息
3. 观察(Observation)：查看工具返回的结果
4. 重复以上步骤，直到你有足够的信息来回答问题

## 输出格式
你的每一步思考都要遵循以下格式：

### 思考
<你的思考过程>

### 行动
工具名称：<工具名>
参数：
```json
<JSON格式的参数>
```

或者，如果不需要工具，直接给出最终答案：

### 最终答案
<你的完整回答>

## 重要规则
1. 每次只调用一个工具
2. 仔细阅读工具返回的结果
3. 如果工具结果不足以回答问题，继续调用其他工具
4. 确认信息充分后，给出最终答案
5. 不要编造工具中没有的信息
6. 用自然、友好的语气回答用户"""
    
    def _parse_next_step(self, messages: List[Dict[str, Any]],
                         tool_names: List[str]) -> Tuple[str, Optional[str], Optional[Dict[str, Any]]]:
        """解析下一步行动
        
        在没有LLM的情况下，使用规则引擎进行简单的工具选择和推理。
        这是一个轻量级实现，后续可以替换为真正的LLM调用。
        
        Returns:
            (思考内容, 工具名称, 工具参数)
        """
        # 获取最后一条用户消息
        last_user_msg = ""
        for msg in reversed(messages):
            if msg["role"] == "user":
                last_user_msg = msg["content"]
                break
        
        # 如果已经有观察结果，生成最终答案
        has_observation = any(
            "观察结果" in m.get("content", "")
            for m in messages
        )
        
        if has_observation:
            # 收集所有观察结果，综合回答
            observations = []
            for msg in messages:
                if "观察结果" in msg.get("content", ""):
                    observations.append(msg["content"].replace("观察结果：", ""))
            
            if observations:
                thought = f"我已经收集到了{len(observations)}条信息，现在可以回答用户的问题了。"
                answer = self._generate_answer_from_observations(last_user_msg, observations)
                return thought + f"\n\n### 最终答案\n{answer}", None, None
        
        # 简单的规则引擎：根据用户问题选择工具
        tool_name, tool_params, reason = self._select_tool(last_user_msg, tool_names)
        
        if tool_name:
            thought = f"{reason}我应该使用 {tool_name} 工具来获取相关信息。"
            return thought, tool_name, tool_params
        else:
            # 不需要工具，直接回答
            thought = "这个问题不需要调用工具，我可以直接回答。"
            answer = self._generate_direct_answer(last_user_msg)
            return thought + f"\n\n### 最终答案\n{answer}", None, None
    
    def _select_tool(self, query: str,
                     tool_names: List[str]) -> Tuple[Optional[str], Optional[Dict[str, Any]], str]:
        """根据查询选择合适的工具
        
        Returns:
            (工具名称, 参数, 选择理由)
        """
        q = query.lower()
        
        # 1. 计算器
        if ("calculator" in tool_names or "计算器" in tool_names) and self._is_math_query(query):
            expr = self._extract_math_expression(query)
            if expr:
                return "calculator", {"expression": expr}, "用户的问题涉及数学计算，"
        
        # 2. 当前时间
        if "get_current_time" in tool_names and self._is_time_query(query):
            return "get_current_time", {"format": "full"}, "用户想知道当前时间，"
        
        # 3. 记忆搜索
        if "search_memory" in tool_names and self._is_memory_query(query):
            memory_query = self._extract_memory_query(query)
            return "search_memory", {"query": memory_query, "limit": 5}, "用户在询问之前的事情，需要搜索记忆，"
        
        # 4. 知识库搜索
        if "search_knowledge" in tool_names and self._is_knowledge_query(query):
            return "search_knowledge", {"query": query, "limit": 3}, "用户在询问知识性问题，"
        
        # 5. 文本分析
        if "text_analysis" in tool_names and self._is_text_analysis_query(query):
            text = self._extract_text_for_analysis(query)
            if text:
                return "text_analysis", {"text": text, "top_keywords": 10}, "用户需要分析文本，"
        
        return None, None, ""
    
    def _is_math_query(self, query: str) -> bool:
        """判断是否是数学计算问题"""
        math_patterns = [
            r'计算.*[+\-*/^√]',
            r'[0-9]+\s*[+\-*/^]\s*[0-9]+',
            r'等于多少', r'结果是多少',
            r'平方|立方|根号|平方根',
            r'sin|cos|tan|log',
        ]
        q = query.lower()
        return any(re.search(p, q) for p in math_patterns)
    
    def _extract_math_expression(self, query: str) -> Optional[str]:
        """从查询中提取数学表达式"""
        # 尝试匹配常见的表达式模式
        patterns = [
            r'计算\s+(.+?)(?:\s*(?:等于多少|是多少|结果|等于))?\s*[?？]?$',
            r'(.+?)\s*(?:等于多少|是多少|结果是)\s*[?？]?$',
        ]
        for p in patterns:
            m = re.search(p, query.strip())
            if m:
                expr = m.group(1).strip()
                # 过滤掉看起来不像表达式的内容
                if len(expr) > 0 and len(expr) < 100:
                    # 简单清理
                    expr = expr.replace('×', '*').replace('÷', '/').replace('^', '**')
                    expr = expr.replace('的平方', '**2').replace('的立方', '**3')
                    expr = expr.replace('根号', 'sqrt(').replace('平方根', 'sqrt(')
                    # 确保括号配对
                    if expr.count('(') > expr.count(')'):
                        expr += ')' * (expr.count('(') - expr.count(')'))
                    return expr
        
        # 如果查询本身看起来像表达式
        if re.match(r'^[\d+\-*/.()sqrtpiexplogsincoatan ]+$', query.strip()):
            return query.strip()
        
        # 直接查找数字和运算符组合
        m = re.search(r'[\d.]+\s*[+\-*/]\s*[\d.]+(?:\s*[+\-*/]\s*[\d.]+)*', query)
        if m:
            return m.group(0).strip()
        
        return None
    
    def _is_time_query(self, query: str) -> bool:
        """判断是否是时间查询"""
        time_patterns = [
            r'现在几点', r'几点了', r'当前时间',
            r'今天几号', r'今天星期', r'什么日期',
            r'现在是什么时候',
        ]
        q = query.lower()
        return any(re.search(p, q) for p in time_patterns)
    
    def _is_memory_query(self, query: str) -> bool:
        """判断是否是记忆查询"""
        memory_patterns = [
            r'我之前说', r'我上次说', r'我曾经说',
            r'还记得', r'你记得', r'记不记得',
            r'我告诉过你', r'跟你说过',
            r'我的.*是什么', r'我喜欢',
            r'回忆一下', r'想想.*之前',
        ]
        q = query.lower()
        return any(re.search(p, q) for p in memory_patterns)
    
    def _extract_memory_query(self, query: str) -> str:
        """提取记忆搜索关键词"""
        # 简单地返回查询本身，记忆搜索会处理
        return query
    
    def _is_knowledge_query(self, query: str) -> bool:
        """判断是否是知识查询"""
        knowledge_patterns = [
            r'什么是', r'什么叫', r'解释一下',
            r'介绍.*[知识技巧方法]',
            r'查一下.*资料',
            r'告诉我.*原理',
        ]
        q = query.lower()
        return any(re.search(p, q) for p in knowledge_patterns)
    
    def _is_text_analysis_query(self, query: str) -> bool:
        """判断是否是文本分析查询"""
        patterns = [
            r'分析.*文本', r'统计.*字数', r'有多少字',
            r'关键词.*提取', r'关键词分析',
        ]
        q = query.lower()
        return any(re.search(p, q) for p in patterns)
    
    def _extract_text_for_analysis(self, query: str) -> Optional[str]:
        """提取待分析的文本"""
        # 简单实现：查找引号或冒号后的内容
        patterns = [
            r'[""](.+?)[""]',
            r'：\s*(.+)$',
            r':\s*(.+)$',
        ]
        for p in patterns:
            m = re.search(p, query)
            if m and len(m.group(1)) > 10:
                return m.group(1)
        return None
    
    def _is_final_answer(self, content: str) -> bool:
        """判断是否是最终答案"""
        return "### 最终答案" in content or "最终答案：" in content
    
    def _extract_final_answer(self, content: str) -> str:
        """提取最终答案"""
        patterns = [
            r'###\s*最终答案\s*\n(.+)',
            r'最终答案[：:]\s*(.+)',
        ]
        for p in patterns:
            m = re.search(p, content, re.DOTALL)
            if m:
                return m.group(1).strip()
        return content
    
    def _generate_answer_from_observations(self, query: str,
                                           observations: List[str]) -> str:
        """根据观察结果生成回答"""
        # 简单的模板回答
        if len(observations) == 1:
            obs = observations[0]
            return f"根据查询结果：\n\n{obs}\n\n希望这对你有帮助！"
        else:
            combined = "\n\n".join(f"[{i+1}] {obs}" for i, obs in enumerate(observations))
            return f"我为你找到了以下信息：\n\n{combined}\n\n综合以上信息，这就是你问题的答案。"
    
    def _generate_direct_answer(self, query: str) -> str:
        """直接生成回答（不需要工具）"""
        # 这是一个占位实现，实际应该调用LLM
        # 对于简单问题给出基本回答
        greetings = ["你好", "您好", "hi", "hello", "嗨"]
        q = query.lower().strip()
        if any(q.startswith(g) for g in greetings):
            return "你好呀！我是云汐，很高兴见到你。有什么我可以帮你的吗？"
        
        thanks = ["谢谢", "感谢", "thank you", "thanks"]
        if any(t in q for t in thanks):
            return "不客气！能帮到你我很开心。还有其他需要帮忙的吗？"
        
        # 默认回答
        return f"我理解你的问题是关于：{query[:50]}...\n\n不过目前我的能力还在成长中，对于一些复杂问题可能需要更多工具的帮助。你可以试试问我数学计算、时间查询，或者让我帮你搜索记忆和知识库哦！"
    
    def _synthesize_answer(self, steps: List[AgentStep], query: str) -> str:
        """综合所有步骤生成最终答案"""
        observations = [s for s in steps if s.step_type == AgentStepType.OBSERVATION.value]
        if observations:
            obs_texts = [s.content for s in observations]
            return self._generate_answer_from_observations(query, obs_texts)
        
        # 如果没有工具调用，返回最后一个思考
        thoughts = [s for s in steps if s.step_type == AgentStepType.THOUGHT.value]
        if thoughts:
            return thoughts[-1].content
        
        return "抱歉，我没能完成这个任务。"
    
    def get_execution_history(self, limit: int = 10) -> List[Dict[str, Any]]:
        """获取执行历史"""
        with self._lock:
            items = list(reversed(self._execution_history.items()))
            return [
                {"id": eid, **result.to_dict()}
                for eid, result in items[:limit]
            ]
    
    def get_stats(self) -> Dict[str, Any]:
        """获取统计信息"""
        with self._lock:
            total = len(self._execution_history)
            success = sum(1 for r in self._execution_history.values() if r.success)
            avg_steps = (
                sum(r.total_steps for r in self._execution_history.values()) / total
                if total > 0 else 0
            )
            avg_time = (
                sum(r.execution_time for r in self._execution_history.values()) / total
                if total > 0 else 0
            )
            
            # 工具使用统计
            tool_counts = {}
            for r in self._execution_history.values():
                for t in r.tools_used:
                    tool_counts[t] = tool_counts.get(t, 0) + 1
            
            return {
                "total_executions": total,
                "success_rate": success / total if total > 0 else 0,
                "avg_steps": round(avg_steps, 2),
                "avg_execution_time": round(avg_time, 3),
                "tool_usage": tool_counts,
            }


# 单例
_agent_engine_instance: Optional[AgentEngine] = None


def get_agent_engine() -> AgentEngine:
    """获取Agent引擎单例"""
    global _agent_engine_instance
    if _agent_engine_instance is None:
        _agent_engine_instance = AgentEngine()
    return _agent_engine_instance
