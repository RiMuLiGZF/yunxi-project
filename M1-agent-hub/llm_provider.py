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

    [V12.1] 增强调度能力：
    - 显存感知调度（VRAM-aware scheduling）
    - 模型优先级队列（P0-P3 四级）
    - 低显存自动降级（auto_degrade）
    - 动态上下文调整（dynamic context window）
    - 预测性预热（predictive preloading）
    """

    def __init__(
        self,
        inference_interface: Any | None = None,  # InferenceInterface 实例（模块3）
        model_rotation: Any | None = None,  # ModelRotationManager 实例
        default_local_model: str = "mock-model",
        default_cloud_model: str = "gpt-4o-mini",
        use_three_tier_router: bool = False,  # [V12.0] 是否启用三层模型架构
        enable_vram_awareness: bool = True,   # [V12.1] 启用显存感知
        enable_priority_queue: bool = True,   # [V12.1] 启用优先级队列
        enable_auto_degrade: bool = True,     # [V12.1] 启用自动降级
        enable_dynamic_ctx: bool = True,      # [V12.1] 启用动态上下文
        enable_preload: bool = False,         # [V12.1] 启用预测性预热（默认关闭）
    ) -> None:
        self._inference = inference_interface
        self._rotation = model_rotation
        self._default_local = default_local_model
        self._default_cloud = default_cloud_model
        self._use_three_tier = use_three_tier_router
        self._three_tier_router: Any | None = None  # 惰性初始化
        self._logger = logger.bind(service="inference_router")

        # [V12.1] 增强功能开关（通过环境变量也可控制）
        self._enable_vram = enable_vram_awareness
        self._enable_pq = enable_priority_queue
        self._enable_degrade = enable_auto_degrade
        self._enable_dctx = enable_dynamic_ctx
        self._enable_preload = enable_preload

        # [V12.1] 调度统计
        self._scheduling_stats: dict[str, Any] = {
            "total_routed": 0,
            "vram_triggered_degrade": 0,
            "ctx_adjustments": 0,
            "preload_hits": 0,
            "preload_misses": 0,
        }

        if self._use_three_tier:
            self._logger.info(
                "three_tier_router_enabled",
                vram_awareness=self._enable_vram,
                priority_queue=self._enable_pq,
                auto_degrade=self._enable_degrade,
                dynamic_ctx=self._enable_dctx,
                preload=self._enable_preload,
            )

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
        """通过三层模型架构调度器路由（V12.1 增强版）

        Args:
            messages: 消息列表
            task_complexity_hint: 复杂度提示（low/medium/high），
                                  用于在自动分类基础上做偏移

        Returns:
            标准推理结果字典，包含增强的调度信息
        """
        router = await self._get_three_tier_router()
        self._scheduling_stats["total_routed"] += 1

        # 记录调用前的降级计数，用于计算本次是否发生降级
        pre_degrade_count = router.stats().get("degradation_count", 0)

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

        # 统计本次请求是否触发了降级
        post_degrade_count = stats.get("degradation_count", 0)
        degraded_this_request = post_degrade_count > pre_degrade_count

        # 同步调度统计
        if stats.get("vram_triggered_degradations", 0):
            self._scheduling_stats["vram_triggered_degrade"] = stats["vram_triggered_degradations"]
        if stats.get("ctx_shrink_count", 0):
            self._scheduling_stats["ctx_adjustments"] = stats["ctx_shrink_count"]
        if stats.get("preload_hit_count", 0):
            self._scheduling_stats["preload_hits"] = stats["preload_hit_count"]
        if stats.get("preload_miss_count", 0):
            self._scheduling_stats["preload_misses"] = stats["preload_miss_count"]

        # 确定实际使用的模型
        actual_model = stats.get("tier0_model", "unknown")
        actual_tier = 0
        if stats.get("tier1_loaded") and not stats.get("tier0_loaded"):
            actual_model = stats.get("tier1_model", "unknown")
            actual_tier = 1
        if degraded_this_request and stats.get("degradation_stats", {}).get("reason_breakdown"):
            # 如果发生了降级，尝试从最近的降级记录推断
            pass

        return {
            "model": actual_model,
            "tier": actual_tier,
            "content": content,
            "usage": {
                "prompt_tokens": 0,  # 规则版调度器暂不统计 token
                "completion_tokens": 0,
            },
            "router_info": {
                "mode": "three_tier_v12",
                "total_requests": stats.get("total_requests", 0),
                "degradation_count": stats.get("degradation_count", 0),
                "degraded_this_request": degraded_this_request,
                # V12.1 增强信息
                "vram_status": stats.get("vram_status"),
                "degradation_stats": stats.get("degradation_stats"),
                "context_window_k": stats.get("context_window_k"),
                "priority_queue_enabled": stats.get("priority_queue_enabled", False),
            },
        }

    def stats(self) -> dict[str, Any]:
        """获取调度器统计信息（V12.1 增强版）"""
        base_stats = {
            "default_local": self._default_local,
            "default_cloud": self._default_cloud,
            "inference_interface_connected": self._inference is not None,
            "rotation_manager_connected": self._rotation is not None,
            "three_tier_router_enabled": self._use_three_tier,
            # V12.1 增强功能开关
            "features": {
                "vram_awareness": self._enable_vram,
                "priority_queue": self._enable_pq,
                "auto_degrade": self._enable_degrade,
                "dynamic_ctx": self._enable_dctx,
                "preload": self._enable_preload,
            },
            # V12.1 调度统计
            "scheduling_stats": dict(self._scheduling_stats),
        }
        if self._use_three_tier and self._three_tier_router is not None:
            base_stats["three_tier_router"] = self._three_tier_router.stats()
        return base_stats

    # ── [V12.1] 增强调度能力接口 ───────────────────────

    async def get_vram_status(self) -> dict[str, Any] | None:
        """获取当前显存状态

        Returns:
            显存状态字典，包含 total_gb / used_gb / free_gb / usage_ratio / source
            未启用三层路由时返回 None
        """
        if not self._use_three_tier or not self._enable_vram:
            return None
        router = await self._get_three_tier_router()
        try:
            vram = await router.get_vram_usage()
            return vram.to_dict()
        except Exception as exc:
            self._logger.warning("get_vram_status_failed", error=str(exc))
            return None

    async def preload_for_task(self, task_type: str) -> bool:
        """预测性预热：根据任务类型提前预热对应模型

        Args:
            task_type: 任务类型（simple/medium/complex）

        Returns:
            True 表示预热已启动或已预热
        """
        if not self._use_three_tier or not self._enable_preload:
            return False
        router = await self._get_three_tier_router()
        return await router.preload_for_task(task_type)

    async def get_degradation_stats(self) -> dict[str, Any] | None:
        """获取降级统计信息"""
        if not self._use_three_tier:
            return None
        router = await self._get_three_tier_router()
        return router.get_degradation_stats()

    async def get_unload_candidates(self) -> list[int]:
        """获取当前可卸载的模型列表（按优先级从低到高）"""
        if not self._use_three_tier:
            return []
        router = await self._get_three_tier_router()
        return router.get_unload_candidates()

    async def evict_low_priority(self, needed_gb: float) -> int:
        """卸载低优先级模型以释放显存

        Args:
            needed_gb: 需要释放的显存（GB）

        Returns:
            实际卸载的模型数量
        """
        if not self._use_three_tier or not self._enable_vram:
            return 0
        router = await self._get_three_tier_router()
        return await router.evict_low_priority_models(needed_gb)

    async def get_context_window(self, task_type: str, tier: int) -> int | None:
        """获取指定任务和层级的 context window 大小"""
        if not self._use_three_tier or not self._enable_dctx:
            return None
        router = await self._get_three_tier_router()
        return router.get_context_window_for_task(task_type, tier)
