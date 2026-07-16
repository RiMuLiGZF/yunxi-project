"""
思维链推理引擎 - 云汐大脑推理层
CoT推理 + 任务分解 + 反思校验 + 多步规划

支持能力：
- 自动任务分解（复杂问题拆成子问题）
- 思维链引导（让模型逐步推理）
- 自我反思与校验（检查答案合理性）
- 多方案比较（生成多个方案择优）
- 推理过程可视化
"""

import re
import json
import time
import asyncio
import threading
from enum import Enum
from dataclasses import dataclass, field
from typing import Optional, List, Dict, Any, Tuple, Callable
from abc import ABC, abstractmethod


class ReasoningMode(str, Enum):
    """推理模式"""
    DIRECT = "direct"          # 直接回答（简单问题）
    COT = "cot"                # 思维链（需要推理的问题）
    TREE = "tree"              # 思维树（多路径探索）
    PLAN = "plan"              # 规划式（复杂任务分解）
    REFLECT = "reflect"        # 反思式（自我校验改进）


class TaskComplexity(str, Enum):
    """任务复杂度"""
    SIMPLE = "simple"          # 简单：直接回答
    MEDIUM = "medium"          # 中等：需要几步推理
    COMPLEX = "complex"        # 复杂：需要分解和规划
    RESEARCH = "research"      # 研究级：需要多轮探索


@dataclass
class ReasoningStep:
    """推理步骤"""
    step_id: int
    title: str
    thought: str = ""          # 思考内容
    action: str = ""           # 行动/操作
    observation: str = ""      # 观察/结果
    confidence: float = 0.5    # 置信度
    timestamp: float = field(default_factory=time.time)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "step_id": self.step_id,
            "title": self.title,
            "thought": self.thought,
            "action": self.action,
            "observation": self.observation,
            "confidence": self.confidence,
        }


@dataclass
class ReasoningResult:
    """推理结果"""
    mode: str
    final_answer: str
    steps: List[ReasoningStep]
    total_time: float = 0.0
    confidence: float = 0.0
    reflections: List[str] = field(default_factory=list)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "mode": self.mode,
            "final_answer": self.final_answer,
            "steps": [s.to_dict() for s in self.steps],
            "total_time": round(self.total_time, 3),
            "confidence": self.confidence,
            "reflections": self.reflections,
            "step_count": len(self.steps),
        }


class ChainOfThoughtEngine:
    """思维链推理引擎"""
    
    def __init__(self):
        # 复杂度分类阈值（基于问题特征）
        self._complexity_rules = [
            # 简单问题模式
            {
                "complexity": TaskComplexity.SIMPLE.value,
                "patterns": [
                    r"^(你好|您好|hi|hello|嗨|在吗)",
                    r"^.{0,20}$",  # 非常短的问题
                    r"^(几点|今天|星期|天气|时间)",
                    r"^(谢谢|感谢|拜拜|再见)",
                ],
            },
            # 研究级问题
            {
                "complexity": TaskComplexity.RESEARCH.value,
                "patterns": [
                    r"(分析|研究|调查|对比|评估|方案|设计)",
                    r"(为什么|原因|原理|机制)",
                    r"怎么.*做|如何.*实现|步骤.*流程",
                    r"(计划|规划|策略|战略)",
                ],
            },
        ]
        
        # CoT 提示词模板
        self._cot_prompt_templates = {
            "general": (
                "让我们一步步来思考这个问题。\n\n"
                "问题：{question}\n\n"
                "请按以下格式回答：\n"
                "【步骤1：理解问题】\n"
                "（这里写你对问题的理解）\n\n"
                "【步骤2：分析思路】\n"
                "（这里写你的分析过程）\n\n"
                "【步骤3：逐步推导】\n"
                "（这里写具体的推导过程）\n\n"
                "【最终答案】\n"
                "（这里给出最终答案）"
            ),
            "math": (
                "这是一道需要仔细计算的问题。让我们一步步来：\n\n"
                "问题：{question}\n\n"
                "请展示完整的计算过程，每一步都写清楚。"
            ),
            "coding": (
                "让我们分析这个编程问题，然后给出解决方案。\n\n"
                "问题：{question}\n\n"
                "请按以下步骤思考：\n"
                "1. 理解需求\n"
                "2. 设计思路\n"
                "3. 实现代码\n"
                "4. 边界情况处理"
            ),
        }
    
    def classify_complexity(self, question: str) -> str:
        """判断问题复杂度
        
        Returns:
            TaskComplexity value
        """
        q = question.strip()
        
        # 先检查简单问题
        simple_patterns = self._complexity_rules[0]["patterns"]
        for pattern in simple_patterns:
            if re.search(pattern, q, re.IGNORECASE):
                return TaskComplexity.SIMPLE.value
        
        # 再检查复杂/研究级
        research_patterns = self._complexity_rules[1]["patterns"]
        match_count = 0
        for pattern in research_patterns:
            if re.search(pattern, q):
                match_count += 1
        
        if match_count >= 2 or len(q) > 100:
            return TaskComplexity.COMPLEX.value
        elif match_count == 1:
            return TaskComplexity.MEDIUM.value
        else:
            return TaskComplexity.MEDIUM.value  # 默认中等
    
    def determine_reasoning_mode(self, question: str,
                                  preference: str = "auto") -> str:
        """确定使用的推理模式
        
        Args:
            question: 用户问题
            preference: 用户偏好（auto/cot/plan/reflect/direct）
        
        Returns:
            ReasoningMode value
        """
        if preference != "auto":
            return preference
        
        complexity = self.classify_complexity(question)
        
        if complexity == TaskComplexity.SIMPLE.value:
            return ReasoningMode.DIRECT.value
        elif complexity == TaskComplexity.MEDIUM.value:
            return ReasoningMode.COT.value
        elif complexity == TaskComplexity.COMPLEX.value:
            return ReasoningMode.PLAN.value
        else:  # research
            return ReasoningMode.REFLECT.value
    
    # ==================== CoT 提示词构建 ====================
    
    def build_cot_prompt(self, question: str,
                         mode: str = "auto",
                         domain: str = "general") -> str:
        """构建思维链增强的prompt
        
        Args:
            question: 用户问题
            mode: 推理模式
            domain: 领域（general/math/coding/...）
        
        Returns:
            增强后的prompt
        """
        if mode == ReasoningMode.DIRECT.value:
            return question
        
        # 选择模板
        template = self._cot_prompt_templates.get(
            domain, self._cot_prompt_templates["general"]
        )
        
        base_prompt = template.format(question=question)
        
        # 根据模式追加额外要求
        if mode == ReasoningMode.REFLECT.value:
            base_prompt += (
                "\n\n在给出最终答案后，请再反思一下："
                "\n1. 答案是否完整？"
                "\n2. 有没有遗漏的角度？"
                "\n3. 如何可以更好？"
            )
        elif mode == ReasoningMode.PLAN.value:
            base_prompt += (
                "\n\n请先制定详细的执行计划，列出所有子任务，"
                "然后逐步完成每个子任务，最后汇总结果。"
            )
        
        return base_prompt
    
    def build_decomposition_prompt(self, question: str) -> str:
        """构建任务分解prompt
        
        将复杂问题拆分为多个子问题
        """
        prompt = f"""
你是一个任务分解专家。请将以下复杂问题拆分为3-5个子问题，
每个子问题都是可以独立回答的小问题。

原问题：{question}

请按以下格式输出子问题列表：
子问题1：xxx
子问题2：xxx
子问题3：xxx
...

要求：
1. 子问题之间有逻辑递进关系
2. 每个子问题都有明确的答案
3. 回答完所有子问题就能完整回答原问题
""".strip()
        return prompt
    
    def build_reflection_prompt(self, question: str, answer: str) -> str:
        """构建反思prompt
        
        让模型检查自己的答案并改进
        """
        prompt = f"""
请反思你对以下问题的回答，看看有没有可以改进的地方。

问题：{question}

你的回答：
{answer}

请从以下角度反思：
1. 准确性：回答是否正确？有没有事实错误？
2. 完整性：是否遗漏了重要信息？
3. 清晰度：表达是否清楚？
4. 深度：分析是否足够深入？

如果需要改进，请给出改进后的回答。如果回答已经很好，直接说"回答良好"。
""".strip()
        return prompt
    
    # ==================== 推理结果解析 ====================
    
    def parse_cot_response(self, response: str) -> Tuple[str, List[ReasoningStep]]:
        """解析CoT响应，提取步骤和最终答案
        
        Returns:
            (最终答案, 推理步骤列表)
        """
        steps = []
        
        # 尝试提取步骤
        step_patterns = [
            r"【步骤(\d+)[:：](.*?)】\s*\n?(.*?)(?=\n【步骤\d+|\n【最终答案】|$)",
            r"步骤(\d+)[:：](.*?)\n(.*?)(?=\n步骤\d+|\n最终答案|$)",
            r"第(\d+)步[:：](.*?)\n(.*?)(?=\n第\d+步|\n最终答案|$)",
        ]
        
        for pattern in step_patterns:
            matches = re.findall(pattern, response, re.DOTALL)
            if matches:
                for step_num, title, content in matches:
                    step = ReasoningStep(
                        step_id=int(step_num),
                        title=title.strip() if title.strip() else f"步骤{step_num}",
                        thought=content.strip(),
                    )
                    steps.append(step)
                break
        
        # 如果没找到结构化步骤，尝试按段落分割
        if not steps:
            paragraphs = [p.strip() for p in re.split(r'\n\s*\n', response) if p.strip()]
            for i, para in enumerate(paragraphs[:-1], 1):
                # 跳过太短的段落
                if len(para) < 10:
                    continue
                step = ReasoningStep(
                    step_id=i,
                    title=f"思考{i}",
                    thought=para[:500],
                )
                steps.append(step)
        
        # 提取最终答案
        final_answer = response
        answer_patterns = [
            r"【最终答案】\s*\n?(.*?)$",
            r"最终答案[:：]\s*\n?(.*?)$",
            r"结论[:：]\s*\n?(.*?)$",
            r"总结[:：]\s*\n?(.*?)$",
        ]
        
        for pattern in answer_patterns:
            match = re.search(pattern, response, re.DOTALL)
            if match:
                final_answer = match.group(1).strip()
                break
        
        # 如果没找到明确的最终答案，用最后一段
        if final_answer == response and len(response) > 200:
            # 取最后200字作为"答案"部分
            final_answer = response[-200:].strip()
        
        return final_answer, steps
    
    def parse_decomposition(self, response: str) -> List[str]:
        """解析任务分解结果，提取子问题列表"""
        sub_questions = []
        
        # 匹配各种子问题格式
        patterns = [
            r"子问题\d+[:：](.*?)(?=\n子问题\d+|\n\d+\.|\Z)",
            r"\d+[.、])(.*?)(?=\n\d+[.、]|\Z)",
            r"[-*]\s+(.*?)(?=\n[-*]\s+|\Z)",
        ]
        
        for pattern in patterns:
            matches = re.findall(pattern, response, re.DOTALL)
            if matches:
                for m in matches:
                    q = m.strip()
                    if q and len(q) > 5:
                        sub_questions.append(q)
                if sub_questions:
                    break
        
        # 如果没找到结构化的，按行分割
        if not sub_questions:
            lines = [l.strip() for l in response.split('\n') if l.strip()]
            for line in lines:
                # 跳过标题行
                if re.match(r'^(子问题|问题|任务)', line) and len(line) < 15:
                    continue
                if len(line) > 10:
                    sub_questions.append(line)
        
        return sub_questions[:5]  # 最多5个子问题
    
    # ==================== 综合推理 ====================
    
    def plan_reasoning(self, question: str,
                       domain: str = "general",
                       user_preference: str = "auto") -> Dict[str, Any]:
        """规划推理方案
        
        给定一个问题，规划如何回答它（不实际执行）
        
        Returns:
            推理方案字典
        """
        complexity = self.classify_complexity(question)
        mode = self.determine_reasoning_mode(question, user_preference)
        
        plan = {
            "question": question,
            "complexity": complexity,
            "mode": mode,
            "domain": domain,
            "estimated_steps": 1,
            "estimated_time": "快速",
            "strategy": "",
        }
        
        if mode == ReasoningMode.DIRECT.value:
            plan["strategy"] = "直接回答，无需复杂推理"
            plan["estimated_steps"] = 1
            plan["estimated_time"] = "即时"
        
        elif mode == ReasoningMode.COT.value:
            plan["strategy"] = "思维链推理，逐步分析问题"
            plan["estimated_steps"] = 3
            plan["estimated_time"] = "快速"
        
        elif mode == ReasoningMode.PLAN.value:
            plan["strategy"] = "任务分解后逐一回答，最后汇总"
            plan["estimated_steps"] = 5
            plan["estimated_time"] = "中等"
        
        elif mode == ReasoningMode.REFLECT.value:
            plan["strategy"] = "先给出回答，再自我反思和改进"
            plan["estimated_steps"] = 4
            plan["estimated_time"] = "较长"
        
        elif mode == ReasoningMode.TREE.value:
            plan["strategy"] = "多路径探索，择优选择"
            plan["estimated_steps"] = 6
            plan["estimated_time"] = "较长"
        
        return plan
    
    def estimate_confidence(self, question: str,
                             answer: str,
                             steps: List[ReasoningStep]) -> float:
        """估算答案的置信度
        
        基于多个因素综合评估
        """
        score = 0.5  # 基础分
        
        # 步骤数量（有推理过程更可信）
        if len(steps) >= 3:
            score += 0.1
        elif len(steps) >= 1:
            score += 0.05
        
        # 答案长度（适中的长度更可信）
        ans_len = len(answer)
        if 100 < ans_len < 2000:
            score += 0.1
        elif ans_len < 20:
            score -= 0.1
        
        # 步骤置信度
        if steps:
            avg_conf = sum(s.confidence for s in steps) / len(steps)
            score += avg_conf * 0.2
        
        # 问题类型加成
        simple_keywords = ["你好", "谢谢", "在吗", "hi", "hello"]
        if any(kw in question.lower() for kw in simple_keywords):
            score = 0.95  # 简单问题高置信
        
        return min(1.0, max(0.0, score))


# 全局引擎实例
_cot_engine: Optional[ChainOfThoughtEngine] = None


def get_cot_engine() -> ChainOfThoughtEngine:
    """获取思维链推理引擎单例"""
    global _cot_engine
    if _cot_engine is None:
        _cot_engine = ChainOfThoughtEngine()
    return _cot_engine
