"""
主理人专用调度Agent (Principal Scheduler Agent)

归属：主理人（用户）的专用调度Agent
核心能力：使用Claude Code风格，通过算力调度平台调用其他大模型API

功能：
1. 接收主理人指令，智能选择最合适的大模型（通过算力调度平台）
2. 支持多模型协作（复杂任务拆分给不同模型）
3. 任务调度与结果汇总
4. 支持代码生成、分析、对话等多种场景
"""

import time
import uuid
import asyncio
import re
from typing import Dict, Any, Optional, List, Tuple
from dataclasses import dataclass, field
from enum import Enum


class TaskType(str, Enum):
    """任务类型"""
    CHAT = "chat"                    # 普通对话
    CODE_GENERATION = "code"         # 代码生成
    CODE_ANALYSIS = "analysis"       # 代码分析
    REASONING = "reasoning"          # 深度推理
    TRANSLATION = "translation"      # 翻译
    SUMMARIZATION = "summarization"  # 摘要总结
    CREATIVE = "creative"            # 创意写作
    MULTI_MODEL = "multi_model"      # 多模型协作


class ModelPreference(str, Enum):
    """模型偏好"""
    SPEED = "speed"           # 速度优先
    QUALITY = "quality"       # 质量优先
    COST = "cost"             # 成本优先
    BALANCED = "balanced"     # 均衡


@dataclass
class ChatMessage:
    """聊天消息"""
    role: str  # user/assistant/system/tool
    content: str
    model_key: str = ""
    model_name: str = ""
    source_id: str = ""
    input_tokens: int = 0
    output_tokens: int = 0
    cost: float = 0.0
    latency_ms: int = 0
    route_id: str = ""
    tool_calls: List[Dict[str, Any]] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)
    message_id: str = ""
    created_at: float = 0.0

    def __post_init__(self):
        if not self.message_id:
            self.message_id = str(uuid.uuid4())
        if not self.created_at:
            self.created_at = time.time()


@dataclass
class RouteDecision:
    """路由决策结果"""
    model_key: str
    model_name: str
    source_id: str
    source_name: str
    task_type: str
    reason: str
    confidence: float
    route_id: str = ""
    estimated_cost: float = 0.0
    estimated_latency_ms: int = 0

    def __post_init__(self):
        if not self.route_id:
            self.route_id = str(uuid.uuid4())


@dataclass
class ChatResponse:
    """聊天响应"""
    response: str
    model_key: str
    model_name: str
    source_id: str
    input_tokens: int
    output_tokens: int
    cost: float
    latency_ms: int
    route_id: str
    task_type: str
    sub_tasks: List[Dict[str, Any]] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)


class PrincipalSchedulerAgent:
    """
    主理人专用调度Agent - 单例模式

    作为主理人的智能调度助手，能够：
    - 理解主理人指令意图
    - 智能选择最合适的大模型（通过算力调度平台）
    - 复杂任务自动拆分给不同模型协作
    - 汇总多模型结果并统一返回
    """

    _instance = None
    _instance_lock = None

    def __new__(cls):
        if cls._instance is None:
            import threading
            cls._instance_lock = threading.Lock()
            with cls._instance_lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return
        self._initialized = True

        # 会话缓存（内存中保留最近的会话）
        self._sessions: Dict[str, List[ChatMessage]] = {}

        # 算力路由引擎引用（懒加载）
        self._compute_router = None

        # 系统提示词
        self._system_prompt = """你是云汐系统的主理人调度Agent，采用Claude Code风格与主理人交流。

你的核心能力：
1. 理解主理人的需求，智能选择最合适的大模型来完成任务
2. 对于复杂任务，可以拆分为多个子任务，调用不同模型协作完成
3. 支持代码生成、代码分析、深度推理、创意写作、翻译摘要等多种场景

工作风格：
- 简洁高效，直击要点
- 主动思考，提前预判需求
- 遇到复杂问题时主动拆解
- 保持专业且友好的语气

你可以通过算力调度平台访问多种大模型，包括但不限于：
- 高质量推理模型（适合深度思考、复杂分析）
- 快速对话模型（适合日常对话、简单问题）
- 代码专用模型（适合代码生成、调试）
- 创意写作模型（适合文案、创作）
"""

    async def chat(
        self,
        message: str,
        session_id: Optional[str] = None,
        preference: str = "balanced",
        system_prompt: Optional[str] = None,
    ) -> ChatResponse:
        """
        与主理人调度Agent对话

        Args:
            message: 用户消息
            session_id: 会话ID（用于多轮对话）
            preference: 模型偏好 (speed/quality/cost/balanced)
            system_prompt: 自定义系统提示词

        Returns:
            ChatResponse: 响应结果
        """
        start_time = time.time()

        # 生成会话ID
        if not session_id:
            session_id = str(uuid.uuid4())

        # 获取或创建会话历史
        history = self._sessions.get(session_id, [])

        # 分析任务类型
        task_type = self._analyze_task_type(message)

        # 路由决策 - 选择最合适的模型
        route_decision = await self._route_model(message, task_type, preference)

        # 判断是否需要多模型协作
        is_complex = self._is_complex_task(message, task_type)

        if is_complex:
            # 多模型协作模式
            response = await self._multi_model_chat(
                message, history, task_type, route_decision, preference, system_prompt
            )
        else:
            # 单模型模式
            response = await self._single_model_chat(
                message, history, task_type, route_decision, system_prompt
            )

        # 保存消息到会话历史
        user_msg = ChatMessage(role="user", content=message)
        assistant_msg = ChatMessage(
            role="assistant",
            content=response.response,
            model_key=response.model_key,
            model_name=response.model_name,
            source_id=response.source_id,
            input_tokens=response.input_tokens,
            output_tokens=response.output_tokens,
            cost=response.cost,
            latency_ms=response.latency_ms,
            route_id=response.route_id,
            metadata=response.metadata,
        )

        history.append(user_msg)
        history.append(assistant_msg)
        self._sessions[session_id] = history

        # 限制历史长度
        if len(history) > 100:
            self._sessions[session_id] = history[-100:]

        # 保存到数据库
        self._save_chat_to_db(session_id, user_msg, assistant_msg, task_type)

        response.latency_ms = int((time.time() - start_time) * 1000)
        return response

    def _analyze_task_type(self, message: str) -> str:
        """
        分析消息，判断任务类型

        通过关键词和模式匹配来识别任务类型。
        """
        msg_lower = message.lower()

        # 代码相关检测
        code_patterns = [
            r'写.*代码', r'生成.*代码', r'code', r'编程', r'函数', r'脚本',
            r'写个.*程序', r'实现.*功能', r'debug', r'调试', r'修复.*bug',
            r'代码.*分析', r'审查.*代码', r'code review', r'优化.*代码',
        ]
        for pattern in code_patterns:
            if re.search(pattern, msg_lower):
                # 区分代码生成和代码分析
                if any(w in msg_lower for w in ['分析', '审查', 'review', '解释', '理解']):
                    return TaskType.CODE_ANALYSIS
                return TaskType.CODE_GENERATION

        # 深度推理/复杂思考
        reasoning_patterns = [
            r'分析.*问题', r'深度.*思考', r'帮我.*想想', r'推理', r'论证',
            r'比较.*优劣', r'方案', r'策略', r'建议', r'怎么.*办',
            r'为什么', r'原理', r'本质',
        ]
        for pattern in reasoning_patterns:
            if re.search(pattern, msg_lower):
                return TaskType.REASONING

        # 翻译
        translation_patterns = [
            r'翻译', r'translate', r'译成', r'翻成',
        ]
        for pattern in translation_patterns:
            if re.search(pattern, msg_lower):
                return TaskType.TRANSLATION

        # 摘要/总结
        summarization_patterns = [
            r'总结', r'摘要', r'概括', r'summarize', r'归纳',
            r'提炼', r'要点',
        ]
        for pattern in summarization_patterns:
            if re.search(pattern, msg_lower):
                return TaskType.SUMMARIZATION

        # 创意写作
        creative_patterns = [
            r'写.*文章', r'创作', r'写首诗', r'写个故事', r'文案',
            r'创意', r'策划', r'设计.*方案', r' brainstorm',
        ]
        for pattern in creative_patterns:
            if re.search(pattern, msg_lower):
                return TaskType.CREATIVE

        # 默认普通对话
        return TaskType.CHAT

    def _is_complex_task(self, message: str, task_type: str) -> bool:
        """判断是否为复杂任务，需要多模型协作"""
        # 消息长度判断
        if len(message) > 500:
            return True

        # 任务类型判断
        complex_types = [TaskType.REASONING, TaskType.CODE_ANALYSIS]
        if task_type in complex_types and len(message) > 200:
            return True

        # 多步骤关键词
        multi_step_patterns = [
            r'首先.*然后.*最后', r'分步骤', r'第一步.*第二步',
            r'从多个角度', r'综合分析', r'全面',
        ]
        msg_lower = message.lower()
        for pattern in multi_step_patterns:
            if re.search(pattern, msg_lower):
                return True

        return False

    async def _route_model(
        self,
        message: str,
        task_type: str,
        preference: str,
    ) -> RouteDecision:
        """
        路由决策 - 选择最合适的模型

        通过算力调度平台的路由引擎选择最优模型。
        """
        try:
            router = self._get_compute_router()

            # 构建路由请求参数
            purpose = self._task_type_to_purpose(task_type)

            # 调用算力路由引擎
            route_result = router.route_request(
                model_key=f"principal-{purpose}",
                purpose=purpose,
                caller_module="m8-inspection",
                caller_skill="principal_agent",
                input_tokens=len(message) // 4,  # 粗略估算
                priority="high" if preference == "quality" else "normal",
                privacy_level="enhanced",
            )

            if route_result.status.value == "success":
                return RouteDecision(
                    model_key=route_result.model_key,
                    model_name=route_result.model_key,
                    source_id=route_result.source_id or "",
                    source_name=route_result.source_name or "",
                    task_type=task_type,
                    reason=f"路由引擎选择: {route_result.model_key} (得分: {route_result.score:.2f})",
                    confidence=min(1.0, route_result.score),
                    route_id=route_result.route_id,
                    estimated_cost=route_result.cost_estimate,
                    estimated_latency_ms=int(route_result.latency_ms),
                )

        except Exception as e:
            # 路由失败时使用默认策略
            pass

        # 默认回退策略
        return self._fallback_route(task_type, preference)

    def _fallback_route(self, task_type: str, preference: str) -> RouteDecision:
        """回退路由策略（当算力调度平台不可用时）"""
        # 基于任务类型和偏好的启发式选择
        model_map = {
            TaskType.CODE_GENERATION: {
                "quality": ("deepseek-coder", "DeepSeek-Coder", "高质量代码模型"),
                "speed": ("qwen-code", "Qwen-Coder", "快速代码模型"),
                "balanced": ("default-code", "Default-Code", "均衡代码模型"),
                "cost": ("local-code", "Local-Code", "本地代码模型"),
            },
            TaskType.CODE_ANALYSIS: {
                "quality": ("claude-sonnet", "Claude-Sonnet", "深度分析模型"),
                "speed": ("gpt-4o-mini", "GPT-4o-Mini", "快速分析模型"),
                "balanced": ("default-analysis", "Default-Analysis", "均衡分析模型"),
                "cost": ("local-analysis", "Local-Analysis", "本地分析模型"),
            },
            TaskType.REASONING: {
                "quality": ("claude-opus", "Claude-Opus", "最强推理模型"),
                "speed": ("gpt-4o", "GPT-4o", "快速推理模型"),
                "balanced": ("default-reasoning", "Default-Reasoning", "均衡推理模型"),
                "cost": ("o3-mini", "O3-Mini", "低成本推理模型"),
            },
            TaskType.TRANSLATION: {
                "quality": ("gpt-4o", "GPT-4o", "高质量翻译"),
                "speed": ("qwen-plus", "Qwen-Plus", "快速翻译"),
                "balanced": ("default-translation", "Default-Translation", "均衡翻译"),
                "cost": ("local-translate", "Local-Translate", "本地翻译模型"),
            },
            TaskType.SUMMARIZATION: {
                "quality": ("claude-sonnet", "Claude-Sonnet", "高质量摘要"),
                "speed": ("gpt-4o-mini", "GPT-4o-Mini", "快速摘要"),
                "balanced": ("default-summary", "Default-Summary", "均衡摘要"),
                "cost": ("local-summary", "Local-Summary", "本地摘要模型"),
            },
            TaskType.CREATIVE: {
                "quality": ("claude-sonnet", "Claude-Sonnet", "创意写作模型"),
                "speed": ("qwen-plus", "Qwen-Plus", "快速创意模型"),
                "balanced": ("default-creative", "Default-Creative", "均衡创意模型"),
                "cost": ("local-creative", "Local-Creative", "本地创意模型"),
            },
            TaskType.CHAT: {
                "quality": ("gpt-4o", "GPT-4o", "高质量对话"),
                "speed": ("qwen-turbo", "Qwen-Turbo", "快速对话模型"),
                "balanced": ("default-chat", "Default-Chat", "均衡对话模型"),
                "cost": ("local-chat", "Local-Chat", "本地对话模型"),
            },
        }

        task_models = model_map.get(task_type, model_map[TaskType.CHAT])
        pref = preference if preference in task_models else "balanced"
        model_key, model_name, reason = task_models[pref]

        return RouteDecision(
            model_key=model_key,
            model_name=model_name,
            source_id="fallback-source",
            source_name="内置回退策略",
            task_type=task_type,
            reason=reason,
            confidence=0.5,
        )

    def _task_type_to_purpose(self, task_type: str) -> str:
        """将任务类型转换为算力路由的purpose参数"""
        purpose_map = {
            TaskType.CHAT: "chat",
            TaskType.CODE_GENERATION: "code",
            TaskType.CODE_ANALYSIS: "code",
            TaskType.REASONING: "chat",
            TaskType.TRANSLATION: "chat",
            TaskType.SUMMARIZATION: "chat",
            TaskType.CREATIVE: "chat",
        }
        return purpose_map.get(task_type, "chat")

    async def _single_model_chat(
        self,
        message: str,
        history: List[ChatMessage],
        task_type: str,
        route_decision: RouteDecision,
        system_prompt: Optional[str],
    ) -> ChatResponse:
        """单模型对话"""
        # 构建提示词
        effective_system = system_prompt or self._system_prompt

        # 模拟模型调用（实际项目中通过算力调度平台调用真实API）
        response_text = await self._mock_model_call(
            message=message,
            history=history,
            system_prompt=effective_system,
            model_key=route_decision.model_key,
            task_type=task_type,
        )

        # 估算 token
        input_tokens = len(message) // 4 + sum(len(m.content) // 4 for m in history[-10:])
        output_tokens = len(response_text) // 4

        return ChatResponse(
            response=response_text,
            model_key=route_decision.model_key,
            model_name=route_decision.model_name,
            source_id=route_decision.source_id,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cost=self._estimate_cost(input_tokens, output_tokens, route_decision.model_key),
            latency_ms=0,
            route_id=route_decision.route_id,
            task_type=task_type,
            metadata={
                "routing_reason": route_decision.reason,
                "confidence": route_decision.confidence,
                "mode": "single_model",
            },
        )

    async def _multi_model_chat(
        self,
        message: str,
        history: List[ChatMessage],
        task_type: str,
        primary_decision: RouteDecision,
        preference: str,
        system_prompt: Optional[str],
    ) -> ChatResponse:
        """多模型协作对话"""
        sub_tasks = self._decompose_task(message, task_type)

        results = []
        total_input_tokens = 0
        total_output_tokens = 0
        total_cost = 0.0

        effective_system = system_prompt or self._system_prompt

        for i, sub_task in enumerate(sub_tasks):
            # 为每个子任务选择合适的模型
            sub_route = await self._route_model(
                sub_task["prompt"],
                sub_task["task_type"],
                preference,
            )

            # 调用子模型
            sub_response = await self._mock_model_call(
                message=sub_task["prompt"],
                history=[],
                system_prompt=effective_system,
                model_key=sub_route.model_key,
                task_type=sub_task["task_type"],
            )

            sub_input = len(sub_task["prompt"]) // 4
            sub_output = len(sub_response) // 4
            sub_cost = self._estimate_cost(sub_input, sub_output, sub_route.model_key)

            total_input_tokens += sub_input
            total_output_tokens += sub_output
            total_cost += sub_cost

            results.append({
                "task_id": i + 1,
                "task_name": sub_task["name"],
                "task_type": sub_task["task_type"],
                "model_key": sub_route.model_key,
                "model_name": sub_route.model_name,
                "response": sub_response,
                "input_tokens": sub_input,
                "output_tokens": sub_output,
                "cost": sub_cost,
            })

        # 使用主模型汇总结果
        summary_prompt = self._build_summary_prompt(message, results)
        final_response = await self._mock_model_call(
            message=summary_prompt,
            history=[],
            system_prompt=effective_system,
            model_key=primary_decision.model_key,
            task_type=task_type,
        )

        summary_input = len(summary_prompt) // 4
        summary_output = len(final_response) // 4
        summary_cost = self._estimate_cost(summary_input, summary_output, primary_decision.model_key)

        total_input_tokens += summary_input
        total_output_tokens += summary_output
        total_cost += summary_cost

        return ChatResponse(
            response=final_response,
            model_key=primary_decision.model_key,
            model_name=primary_decision.model_name,
            source_id=primary_decision.source_id,
            input_tokens=total_input_tokens,
            output_tokens=total_output_tokens,
            cost=total_cost,
            latency_ms=0,
            route_id=primary_decision.route_id,
            task_type=TaskType.MULTI_MODEL,
            sub_tasks=results,
            metadata={
                "routing_reason": primary_decision.reason,
                "confidence": primary_decision.confidence,
                "mode": "multi_model",
                "sub_task_count": len(sub_tasks),
            },
        )

    def _decompose_task(self, message: str, task_type: str) -> List[Dict[str, Any]]:
        """将复杂任务拆分为子任务"""
        if task_type == TaskType.REASONING:
            return [
                {
                    "name": "问题分析",
                    "task_type": TaskType.CODE_ANALYSIS,
                    "prompt": f"请分析以下问题的核心要点和关键因素：\n\n{message}\n\n请从多个维度分析问题本质。",
                },
                {
                    "name": "方案构思",
                    "task_type": TaskType.CREATIVE,
                    "prompt": f"基于以下问题，构思3-5个可能的解决方案：\n\n{message}\n\n请提供多样化的思路。",
                },
                {
                    "name": "方案评估",
                    "task_type": TaskType.REASONING,
                    "prompt": f"针对以下问题的解决方案，请评估各方案的优劣：\n\n问题：{message}\n\n请从可行性、成本、效果等维度进行评估。",
                },
            ]
        elif task_type == TaskType.CODE_ANALYSIS:
            return [
                {
                    "name": "代码理解",
                    "task_type": TaskType.CODE_ANALYSIS,
                    "prompt": f"请仔细阅读并理解以下代码/问题，解释其核心逻辑：\n\n{message}",
                },
                {
                    "name": "问题诊断",
                    "task_type": TaskType.CODE_ANALYSIS,
                    "prompt": f"请诊断以下代码/问题中可能存在的问题或改进空间：\n\n{message}",
                },
                {
                    "name": "优化建议",
                    "task_type": TaskType.CODE_GENERATION,
                    "prompt": f"针对以下代码/问题，请提供具体的优化建议和修改方案：\n\n{message}",
                },
            ]
        else:
            # 默认拆分为两部分：分析 + 生成
            return [
                {
                    "name": "需求分析",
                    "task_type": TaskType.REASONING,
                    "prompt": f"请分析以下需求的关键点和约束条件：\n\n{message}",
                },
                {
                    "name": "内容生成",
                    "task_type": task_type,
                    "prompt": f"根据以下需求生成内容：\n\n{message}",
                },
            ]

    def _build_summary_prompt(self, original_message: str, sub_results: List[Dict[str, Any]]) -> str:
        """构建汇总提示词"""
        parts = [f"原始问题：{original_message}\n"]
        parts.append("各子任务结果：\n")

        for r in sub_results:
            parts.append(f"【{r['task_name']}】(模型: {r['model_name']})")
            parts.append(r["response"][:500])  # 限制长度
            parts.append("")

        parts.append("请综合以上各子任务的结果，给出最终的完整回答。")
        parts.append("要求：")
        parts.append("1. 整合各模型的洞察，形成统一的结论")
        parts.append("2. 保留关键信息，去除冗余")
        parts.append("3. 结构清晰，易于理解")

        return "\n".join(parts)

    async def _mock_model_call(
        self,
        message: str,
        history: List[ChatMessage],
        system_prompt: str,
        model_key: str,
        task_type: str,
    ) -> str:
        """
        模拟模型调用

        注意：实际项目中应通过算力调度平台调用真实的大模型API。
        这里提供模拟响应以便功能测试和开发调试。
        """
        await asyncio.sleep(0.1)  # 模拟网络延迟

        task_name = {
            TaskType.CHAT: "对话",
            TaskType.CODE_GENERATION: "代码生成",
            TaskType.CODE_ANALYSIS: "代码分析",
            TaskType.REASONING: "深度推理",
            TaskType.TRANSLATION: "翻译",
            TaskType.SUMMARIZATION: "摘要总结",
            TaskType.CREATIVE: "创意写作",
            TaskType.MULTI_MODEL: "多模型协作",
        }.get(task_type, "处理")

        # 基于任务类型生成不同的模拟响应
        responses = {
            TaskType.CODE_GENERATION: f"""好的，我将为您生成所需的代码。

**任务类型**：代码生成
**使用模型**：{model_key}

以下是根据您的需求生成的代码：

```python
# 自动生成的代码示例
def hello_world():
    \"\"\"示例函数\"\"\"
    print("Hello from Principal Scheduler Agent!")
    return "success"

if __name__ == "__main__":
    result = hello_world()
    print(f"Result: {{result}}")
```

**说明**：
- 这是通过主理人调度Agent路由到 `{model_key}` 模型生成的代码
- 实际部署时将调用真实的大模型API
- 支持代码生成、分析、调试等多种编程场景

您需要我对代码进行调整或解释吗？""",

            TaskType.REASONING: f"""让我来深入分析这个问题。

**任务类型**：深度推理
**使用模型**：{model_key}

经过分析，我认为：

1. **问题本质**：您提出的问题涉及多个层面的考量，需要从不同角度综合分析。

2. **关键因素**：
   - 技术可行性
   - 成本效益比
   - 实施复杂度
   - 长期维护性

3. **建议方案**：
   - 短期：采用快速验证方案，快速迭代
   - 中期：逐步优化架构，提升性能
   - 长期：构建完整的生态系统

4. **风险提示**：
   - 需要关注数据安全
   - 注意系统可扩展性
   - 保持团队协作效率

这是主理人调度Agent通过 `{model_key}` 模型进行的深度分析。
如需更详细的方案，请告诉我具体的约束条件。""",

            TaskType.CHAT: f"""您好！我是主理人调度Agent。

**任务类型**：对话
**使用模型**：{model_key}

收到您的消息：「{message[:100]}{'...' if len(message) > 100 else ''}」

我已通过算力调度平台为您选择了最合适的模型来回答您的问题。
这是一个模拟响应 - 在实际部署中，我会调用真实的大模型API来生成回答。

我可以帮助您：
- 编写和分析代码
- 进行深度思考和推理
- 翻译和摘要文本
- 创意写作和文案
- 以及更多...

有什么我可以帮您的吗？""",
        }

        return responses.get(
            task_type,
            f"""您好！我是主理人调度Agent。

**任务类型**：{task_name}
**使用模型**：{model_key}

这是通过算力调度平台路由到 `{model_key}` 模型的响应。
在实际部署中，这里将显示真实的大模型回答。

您的消息已收到，我会尽力为您提供帮助。"""
        )

    def _estimate_cost(self, input_tokens: int, output_tokens: int, model_key: str) -> float:
        """估算调用成本（元）"""
        # 简化的成本估算
        cost_map = {
            "claude-opus": (0.015, 0.075),
            "claude-sonnet": (0.003, 0.015),
            "gpt-4o": (0.005, 0.015),
            "gpt-4o-mini": (0.00015, 0.0006),
            "deepseek-coder": (0.001, 0.002),
            "qwen-plus": (0.0004, 0.0012),
            "qwen-turbo": (0.0002, 0.0006),
            "qwen-code": (0.0005, 0.001),
            "o3-mini": (0.001, 0.004),
        }

        input_rate, output_rate = cost_map.get(model_key, (0.001, 0.002))
        cost = (input_tokens / 1000) * input_rate + (output_tokens / 1000) * output_rate
        return round(cost, 6)

    def list_available_models(self) -> List[Dict[str, Any]]:
        """获取可用模型列表"""
        models = []

        try:
            router = self._get_compute_router()
            # 从算力调度平台获取模型列表
            if hasattr(router, '_model_bindings'):
                for key, binding in router._model_bindings.items():
                    models.append({
                        "model_key": key,
                        "model_name": binding.get("model_name", key),
                        "purpose": binding.get("purpose", "chat"),
                        "group_id": binding.get("group_id", ""),
                        "status": "available",
                    })
        except Exception:
            pass

        # 如果没有从算力平台获取到，返回默认模型列表
        if not models:
            default_models = [
                {"model_key": "default-chat", "model_name": "默认对话模型", "purpose": "chat", "status": "available"},
                {"model_key": "default-code", "model_name": "默认代码模型", "purpose": "code", "status": "available"},
                {"model_key": "default-reasoning", "model_name": "默认推理模型", "purpose": "chat", "status": "available"},
                {"model_key": "default-analysis", "model_name": "默认分析模型", "purpose": "chat", "status": "available"},
                {"model_key": "default-summary", "model_name": "默认摘要模型", "purpose": "chat", "status": "available"},
                {"model_key": "default-creative", "model_name": "默认创意模型", "purpose": "chat", "status": "available"},
                {"model_key": "default-translation", "model_name": "默认翻译模型", "purpose": "chat", "status": "available"},
            ]
            models = default_models

        return models

    def get_session_history(self, session_id: str, limit: int = 50) -> List[Dict[str, Any]]:
        """获取会话历史"""
        # 先从内存获取
        if session_id in self._sessions:
            history = self._sessions[session_id][-limit:]
            return [
                {
                    "message_id": m.message_id,
                    "role": m.role,
                    "content": m.content,
                    "model_key": m.model_key,
                    "model_name": m.model_name,
                    "created_at": m.created_at,
                }
                for m in history
            ]

        # 从数据库获取
        try:
            from ..models import SessionLocal, PrincipalChatMessage
            db = SessionLocal()
            messages = (
                db.query(PrincipalChatMessage)
                .filter(PrincipalChatMessage.session_id == session_id)
                .order_by(PrincipalChatMessage.id.desc())
                .limit(limit)
                .all()
            )
            db.close()

            # 反转顺序（最新的在后面）
            messages.reverse()
            return [m.to_dict() for m in messages]
        except Exception:
            pass

        return []

    def _get_compute_router(self):
        """获取算力路由引擎（懒加载）"""
        if self._compute_router is None:
            try:
                from ..compute_router import get_compute_router
                self._compute_router = get_compute_router()
            except Exception as e:
                print(f"[PrincipalSchedulerAgent] Failed to get compute router: {e}")
                self._compute_router = None
        return self._compute_router

    def _save_chat_to_db(
        self,
        session_id: str,
        user_msg: ChatMessage,
        assistant_msg: ChatMessage,
        task_type: str,
    ):
        """保存对话到数据库"""
        try:
            from ..models import (
                SessionLocal,
                PrincipalChatSession,
                PrincipalChatMessage,
            )

            db = SessionLocal()

            # 检查会话是否存在
            session = (
                db.query(PrincipalChatSession)
                .filter(PrincipalChatSession.session_id == session_id)
                .first()
            )

            if not session:
                # 创建新会话
                session = PrincipalChatSession(
                    session_id=session_id,
                    title=f"会话 - {time.strftime('%Y-%m-%d %H:%M')}",
                    status="active",
                    model_count=1,
                    total_tokens=0,
                    total_cost=0.0,
                    message_count=0,
                )
                db.add(session)

            # 更新会话统计
            session.message_count += 2  # user + assistant
            session.total_tokens += (
                user_msg.input_tokens + user_msg.output_tokens +
                assistant_msg.input_tokens + assistant_msg.output_tokens
            )
            session.total_cost += assistant_msg.cost

            # 保存用户消息
            db_user_msg = PrincipalChatMessage(
                message_id=user_msg.message_id,
                session_id=session_id,
                role="user",
                content=user_msg.content,
                input_tokens=user_msg.input_tokens,
                output_tokens=user_msg.output_tokens,
            )
            db.add(db_user_msg)

            # 保存助手消息
            db_assistant_msg = PrincipalChatMessage(
                message_id=assistant_msg.message_id,
                session_id=session_id,
                role="assistant",
                content=assistant_msg.content,
                model_key=assistant_msg.model_key,
                model_name=assistant_msg.model_name,
                source_id=assistant_msg.source_id,
                input_tokens=assistant_msg.input_tokens,
                output_tokens=assistant_msg.output_tokens,
                cost=assistant_msg.cost,
                latency_ms=assistant_msg.latency_ms,
                route_id=assistant_msg.route_id,
                extra_metadata=assistant_msg.metadata,
            )
            db.add(db_assistant_msg)

            db.commit()
            db.close()
        except Exception as e:
            print(f"[PrincipalSchedulerAgent] Failed to save chat to DB: {e}")

    async def manual_route_test(
        self,
        message: str,
        model_key: Optional[str] = None,
        preference: str = "balanced",
    ) -> Dict[str, Any]:
        """
        手动路由测试 - 测试路由决策结果

        Args:
            message: 测试消息
            model_key: 指定模型key（可选）
            preference: 模型偏好

        Returns:
            路由决策详情
        """
        task_type = self._analyze_task_type(message)
        is_complex = self._is_complex_task(message, task_type)

        if model_key:
            # 使用指定模型
            route_decision = RouteDecision(
                model_key=model_key,
                model_name=model_key,
                source_id="manual-test",
                source_name="手动指定",
                task_type=task_type,
                reason="手动指定模型",
                confidence=1.0,
            )
        else:
            # 正常路由
            route_decision = await self._route_model(message, task_type, preference)

        return {
            "task_type": task_type,
            "is_complex": is_complex,
            "preference": preference,
            "route_decision": {
                "model_key": route_decision.model_key,
                "model_name": route_decision.model_name,
                "source_id": route_decision.source_id,
                "source_name": route_decision.source_name,
                "reason": route_decision.reason,
                "confidence": route_decision.confidence,
                "route_id": route_decision.route_id,
                "estimated_cost": route_decision.estimated_cost,
            },
            "estimated_tokens": len(message) // 4,
            "mode": "multi_model" if is_complex else "single_model",
        }


def get_principal_scheduler_agent() -> PrincipalSchedulerAgent:
    """获取主理人调度Agent单例"""
    return PrincipalSchedulerAgent()
