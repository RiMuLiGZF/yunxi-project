"""
云汐内核 V4 - LLM 提供商抽象层

⚠️ [V10.0-R03 DEPRECATED] 本模块中的推理执行逻辑（BaseLLMProvider子类）
属于模块3（端云协同）职责范围，将在模块3就绪后迁移。
当前保留作为向后兼容的临时实现。

M1仅保留"本地/云端路由决策"逻辑（InferenceRouter + LLMProviderFactory），
实际模型推理应通过 InferenceInterface 委托给模块3执行。

灵感来源：LiteLLM / LangChain 统一 LLM 接口

提供可插拔的 LLM 后端支持：
- OpenAI 兼容 API（GPT-4、Claude via 代理）
- 本地模型（Ollama、vLLM）
- 异步流式输出

所有 Provider 实现统一接口，支持：
- chat.completions
- chat.completions.stream
- embedding（可选）
"""

from __future__ import annotations

import asyncio
import os
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, AsyncIterator

import structlog

logger = structlog.get_logger(__name__)


@dataclass
class LLMMessage:
    """LLM 消息"""

    role: str = "user"  # system | user | assistant | tool
    content: str = ""
    name: str | None = None
    tool_calls: list[dict[str, Any]] | None = None


@dataclass
class LLMChoice:
    """LLM 生成选择"""

    index: int = 0
    message: LLMMessage = field(default_factory=lambda: LLMMessage())
    finish_reason: str | None = None
    delta: dict[str, Any] | None = None  # 流式输出时的增量


@dataclass
class LLMUsage:
    """Token 使用量"""

    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0


@dataclass
class LLMResponse:
    """LLM 响应"""

    id: str = ""
    model: str = ""
    choices: list[LLMChoice] = field(default_factory=list)
    usage: LLMUsage | None = None
    created_at: float = field(default_factory=time.time)


@dataclass
class LLMStreamChunk:
    """LLM 流式输出块"""

    id: str = ""
    model: str = ""
    index: int = 0
    delta_content: str = ""
    finish_reason: str | None = None
    usage: LLMUsage | None = None


# ── 抽象基类 ────────────────────────────────────────────────


class BaseLLMProvider(ABC):
    """LLM 提供商抽象基类"""

    def __init__(self, model: str, api_key: str | None = None, base_url: str | None = None) -> None:
        self.model = model
        self.api_key = api_key or os.getenv("LLM_API_KEY", "")
        self.base_url = base_url or os.getenv("LLM_BASE_URL", "")
        self._logger = logger.bind(service="llm_provider", model=model)

    @abstractmethod
    async def chat(
        self,
        messages: list[LLMMessage],
        temperature: float = 0.7,
        max_tokens: int | None = None,
        tools: list[dict[str, Any]] | None = None,
    ) -> LLMResponse:
        """非流式对话"""
        ...

    @abstractmethod
    async def chat_stream(
        self,
        messages: list[LLMMessage],
        temperature: float = 0.7,
        max_tokens: int | None = None,
        tools: list[dict[str, Any]] | None = None,
    ) -> AsyncIterator[LLMStreamChunk]:
        """流式对话（逐字输出）"""
        ...

    @abstractmethod
    async def embed(self, texts: list[str]) -> list[list[float]]:
        """文本嵌入"""
        ...


# ── OpenAI 兼容 Provider ────────────────────────────────────


class OpenAICompatibleProvider(BaseLLMProvider):
    """OpenAI 兼容 API Provider

    支持 OpenAI、Azure OpenAI、Claude（通过代理）、本地 vLLM 等
    任何兼容 OpenAI API 格式的后端。
    """

    def __init__(
        self,
        model: str = "gpt-4o-mini",
        api_key: str | None = None,
        base_url: str | None = None,
    ) -> None:
        super().__init__(model, api_key, base_url)
        self._client: Any = None  # 惰性初始化

    def _get_client(self) -> Any:
        """惰性初始化 OpenAI 客户端"""
        if self._client is None:
            try:
                from openai import AsyncOpenAI
            except ImportError:
                raise ImportError(
                    "openai package is required for OpenAICompatibleProvider. "
                    "Install it with: pip install openai"
                )
            self._client = AsyncOpenAI(
                api_key=self.api_key or "no-key",
                base_url=self.base_url or None,
            )
        return self._client

    def _messages_to_openai(self, messages: list[LLMMessage]) -> list[dict[str, Any]]:
        """转换为 OpenAI 格式"""
        result = []
        for msg in messages:
            d: dict[str, Any] = {"role": msg.role, "content": msg.content}
            if msg.name:
                d["name"] = msg.name
            if msg.tool_calls:
                d["tool_calls"] = msg.tool_calls
            result.append(d)
        return result

    async def chat(
        self,
        messages: list[LLMMessage],
        temperature: float = 0.7,
        max_tokens: int | None = None,
        tools: list[dict[str, Any]] | None = None,
    ) -> LLMResponse:
        """非流式对话"""
        start = time.time()
        client = self._get_client()
        params: dict[str, Any] = {
            "model": self.model,
            "messages": self._messages_to_openai(messages),
            "temperature": temperature,
        }
        if max_tokens:
            params["max_tokens"] = max_tokens
        if tools:
            params["tools"] = tools

        try:
            resp = await client.chat.completions.create(**params)
            latency_ms = (time.time() - start) * 1000

            choices = [
                LLMChoice(
                    index=c.index,
                    message=LLMMessage(
                        role=c.message.role,
                        content=c.message.content or "",
                        tool_calls=[
                            {
                                "id": tc.id,
                                "type": tc.type,
                                "function": {
                                    "name": tc.function.name,
                                    "arguments": tc.function.arguments,
                                },
                            }
                            for tc in (c.message.tool_calls or [])
                        ] or None,
                    ),
                    finish_reason=c.finish_reason,
                )
                for c in resp.choices
            ]

            usage = None
            if resp.usage:
                usage = LLMUsage(
                    prompt_tokens=resp.usage.prompt_tokens,
                    completion_tokens=resp.usage.completion_tokens,
                    total_tokens=resp.usage.total_tokens,
                )

            self._logger.debug(
                "llm_chat_complete",
                model=self.model,
                latency_ms=round(latency_ms, 2),
                tokens=usage.total_tokens if usage else 0,
            )

            return LLMResponse(
                id=resp.id,
                model=resp.model,
                choices=choices,
                usage=usage,
            )
        except Exception as exc:
            self._logger.error("llm_chat_error", error=str(exc))
            raise

    async def chat_stream(
        self,
        messages: list[LLMMessage],
        temperature: float = 0.7,
        max_tokens: int | None = None,
        tools: list[dict[str, Any]] | None = None,
    ) -> AsyncIterator[LLMStreamChunk]:
        """流式对话"""
        client = self._get_client()
        params: dict[str, Any] = {
            "model": self.model,
            "messages": self._messages_to_openai(messages),
            "temperature": temperature,
            "stream": True,
        }
        if max_tokens:
            params["max_tokens"] = max_tokens
        if tools:
            params["tools"] = tools

        try:
            stream = await client.chat.completions.create(**params)
            async for chunk in stream:
                delta = chunk.choices[0].delta if chunk.choices else None
                yield LLMStreamChunk(
                    id=chunk.id,
                    model=chunk.model,
                    index=chunk.choices[0].index if chunk.choices else 0,
                    delta_content=delta.content if delta else "",
                    finish_reason=chunk.choices[0].finish_reason if chunk.choices else None,
                )
        except Exception as exc:
            self._logger.error("llm_stream_error", error=str(exc))
            raise

    async def embed(self, texts: list[str]) -> list[list[float]]:
        """文本嵌入"""
        client = self._get_client()
        try:
            resp = await client.embeddings.create(
                model=self.model,
                input=texts,
            )
            return [item.embedding for item in resp.data]
        except Exception as exc:
            self._logger.error("llm_embed_error", error=str(exc))
            raise


# ── Mock Provider（用于测试/无 LLM 环境） ────────────────────


class MockLLMProvider(BaseLLMProvider):
    """Mock LLM Provider

    用于测试环境或未配置 LLM 的场景。
    模拟延迟和流式输出。
    """

    def __init__(self, model: str = "mock-model", response_template: str = "") -> None:
        super().__init__(model)
        self.response_template = response_template or "[Mock] 已收到消息：{content}"
        self.call_count = 0
        self.total_latency_ms = 0.0

    async def chat(
        self,
        messages: list[LLMMessage],
        temperature: float = 0.7,
        max_tokens: int | None = None,
        tools: list[dict[str, Any]] | None = None,
    ) -> LLMResponse:
        """模拟对话"""
        start = time.time()
        await asyncio.sleep(0.01)  # 模拟延迟

        user_content = ""
        if messages:
            user_content = messages[-1].content

        reply = self.response_template.format(content=user_content[:50])

        latency_ms = (time.time() - start) * 1000
        self.call_count += 1
        self.total_latency_ms += latency_ms

        return LLMResponse(
            id=f"mock_{self.call_count}",
            model=self.model,
            choices=[
                LLMChoice(
                    message=LLMMessage(role="assistant", content=reply),
                    finish_reason="stop",
                )
            ],
            usage=LLMUsage(prompt_tokens=len(user_content), completion_tokens=len(reply)),
        )

    async def chat_stream(
        self,
        messages: list[LLMMessage],
        temperature: float = 0.7,
        max_tokens: int | None = None,
        tools: list[dict[str, Any]] | None = None,
    ) -> AsyncIterator[LLMStreamChunk]:
        """模拟流式对话"""
        user_content = ""
        if messages:
            user_content = messages[-1].content

        reply = self.response_template.format(content=user_content[:50])

        # 模拟逐字输出
        chunk_size = 4
        for i in range(0, len(reply), chunk_size):
            await asyncio.sleep(0.005)
            yield LLMStreamChunk(
                id=f"mock_stream_{self.call_count}",
                model=self.model,
                delta_content=reply[i:i + chunk_size],
                finish_reason=None,
            )

        yield LLMStreamChunk(
            id=f"mock_stream_{self.call_count}",
            model=self.model,
            delta_content="",
            finish_reason="stop",
        )

    async def embed(self, texts: list[str]) -> list[list[float]]:
        """模拟嵌入（返回随机向量）"""
        import random
        return [[random.random() for _ in range(128)] for _ in texts]


# ── Provider 工厂 ───────────────────────────────────────────


class LLMProviderFactory:
    """LLM Provider 工厂

    [V10.0-R03] 本工厂保留在M1作为向后兼容，
    未来模块3应提供 InferenceInterface 的实现。
    """

    @staticmethod
    def create(
        provider_type: str = "mock",
        model: str | None = None,
        api_key: str | None = None,
        base_url: str | None = None,
    ) -> BaseLLMProvider:
        """创建 LLM Provider

        Args:
            provider_type: openai | mock
            model: 模型名称
            api_key: API 密钥
            base_url: 自定义 API 地址
        """
        if provider_type == "openai":
            return OpenAICompatibleProvider(
                model=model or "gpt-4o-mini",
                api_key=api_key,
                base_url=base_url,
            )
        elif provider_type == "mock":
            return MockLLMProvider(model=model or "mock-model")
        else:
            raise ValueError(f"Unknown provider type: {provider_type}")


# ── M1 路由决策层 ───────────────────────────────────────────

class InferenceRouter:
    """[V10.0-R03] 推理路由决策器（M1保留组件）

    负责"本地/云端路由决策"和"模型选择"，不执行实际推理。
    根据任务特征、网络状态、预算等因素选择最优推理路径。

    [V12.0] 新增三层模型架构支持：
    - 当 use_three_tier_router=True 时，启用 3B+7B+云端 的三层规则调度器
    - 由 shared.model_router.ThreeTierModelRouter 提供底层能力
    - 向后兼容：默认关闭，不影响现有逻辑
    """

    def __init__(
        self,
        inference_interface: Any | None = None,  # InferenceInterface 实例（模块3）
        model_rotation: Any | None = None,  # ModelRotationManager 实例
        default_local_model: str = "mock-model",
        default_cloud_model: str = "gpt-4o-mini",
        use_three_tier_router: bool = False,  # [V12.0] 是否启用三层模型架构
    ) -> None:
        self._inference = inference_interface
        self._rotation = model_rotation
        self._default_local = default_local_model
        self._default_cloud = default_cloud_model
        self._use_three_tier = use_three_tier_router
        self._three_tier_router: Any | None = None  # 惰性初始化
        self._logger = logger.bind(service="inference_router")

        if self._use_three_tier:
            self._logger.info("three_tier_router_enabled")

    def select_provider(
        self,
        task_complexity: str = "medium",
        network_available: bool = True,
        budget_remaining: float = 1.0,
    ) -> dict[str, str]:
        """选择推理提供商和模型

        Args:
            task_complexity: low | medium | high
            network_available: 是否有网络连接
            budget_remaining: 预算剩余比例（0.0 ~ 1.0）

        Returns:
            {"provider_type": "local|cloud", "model": "模型名称"}
        """
        # 无网络或低预算 -> 本地模型
        if not network_available or budget_remaining < 0.1:
            return {"provider_type": "local", "model": self._default_local}

        # 低复杂度 -> 本地轻量模型
        if task_complexity == "low":
            return {"provider_type": "local", "model": self._default_local}

        # 高复杂度且预算充足 -> 云端大模型
        if task_complexity == "high" and budget_remaining > 0.3:
            return {"provider_type": "cloud", "model": self._default_cloud}

        # 默认 -> 云端标准模型
        return {"provider_type": "cloud", "model": self._default_cloud}

    async def _get_three_tier_router(self):
        """获取三层路由调度器（惰性异步初始化）"""
        if self._three_tier_router is None:
            try:
                from shared.model_router import get_model_router_async
                self._three_tier_router = await get_model_router_async()
                self._logger.info("three_tier_router_initialized")
            except ImportError as exc:
                self._logger.warning("three_tier_router_import_failed", error=str(exc))
                raise
        return self._three_tier_router

    async def route_inference(
        self,
        messages: list[dict[str, Any]],
        task_complexity: str = "medium",
        network_available: bool = True,
        budget_remaining: float = 1.0,
    ) -> dict[str, Any]:
        """路由推理请求

        1. 决策：选择 provider_type 和 model
        2. 委托：通过 InferenceInterface 调用模块3执行推理

        [V12.0] 如果启用了三层路由模式，则使用 ThreeTierModelRouter 进行更精细的调度。
        """
        # [V12.0] 三层模型架构模式
        if self._use_three_tier:
            return await self._route_via_three_tier(messages, task_complexity)

        # 原有逻辑（向后兼容）
        decision = self.select_provider(
            task_complexity=task_complexity,
            network_available=network_available,
            budget_remaining=budget_remaining,
        )
        self._logger.info(
            "inference_routed",
            provider=decision["provider_type"],
            model=decision["model"],
        )

        # 如果模块3接口已接入，委托执行
        if self._inference is not None:
            return await self._inference.chat(
                model=decision["model"],
                messages=messages,
            )

        #  fallback：使用本地工厂创建临时provider（兼容模式）
        provider = LLMProviderFactory.create(
            provider_type="openai" if decision["provider_type"] == "cloud" else "mock",
            model=decision["model"],
        )
        llm_messages = [LLMMessage(role=m.get("role", "user"), content=m.get("content", "")) for m in messages]
        result = await provider.chat(llm_messages)
        return {
            "model": result.model,
            "content": result.choices[0].message.content if result.choices else "",
            "usage": {
                "prompt_tokens": result.usage.prompt_tokens if result.usage else 0,
                "completion_tokens": result.usage.completion_tokens if result.usage else 0,
            },
        }

    async def _route_via_three_tier(
        self,
        messages: list[dict[str, Any]],
        task_complexity_hint: str = "medium",
    ) -> dict[str, Any]:
        """通过三层模型架构调度器路由

        Args:
            messages: 消息列表
            task_complexity_hint: 复杂度提示（low/medium/high），
                                  用于在自动分类基础上做偏移

        Returns:
            标准推理结果字典
        """
        router = await self._get_three_tier_router()

        # 根据复杂度提示选择调用方式
        if task_complexity_hint == "low":
            content = await router.chat_simple(messages)
        elif task_complexity_hint == "high":
            content = await router.chat_cloud(messages)
        else:
            # medium 或其他：走自动分类路由
            content = await router.chat(messages)

        # 获取路由决策信息
        stats = router.stats()

        return {
            "model": stats.get("tier0_model", "unknown"),  # 简化：实际应该从响应中获取
            "content": content,
            "usage": {
                "prompt_tokens": 0,  # 规则版调度器暂不统计 token
                "completion_tokens": 0,
            },
            "router_info": {
                "mode": "three_tier",
                "total_requests": stats.get("total_requests", 0),
                "degradation_count": stats.get("degradation_count", 0),
            },
        }

    def stats(self) -> dict[str, Any]:
        base_stats = {
            "default_local": self._default_local,
            "default_cloud": self._default_cloud,
            "inference_interface_connected": self._inference is not None,
            "rotation_manager_connected": self._rotation is not None,
            "three_tier_router_enabled": self._use_three_tier,
        }
        if self._use_three_tier and self._three_tier_router is not None:
            base_stats["three_tier_router"] = self._three_tier_router.stats()
        return base_stats
