from __future__ import annotations

"""Streaming 流式调用支持.

为 Skill 调用提供异步生成器（AsyncGenerator）模式，支持大模型生成、
长文本处理等场景的边生成边消费，避免阻塞整个 Pipeline。
"""

import asyncio
import time
from typing import Any, AsyncGenerator, Callable

import structlog
from pydantic import BaseModel, Field

from skill_cluster.interfaces import SkillInvokeRequest, SkillInvokeResult
from skill_cluster.skill_router import SkillRouter

logger = structlog.get_logger()


class StreamChunk(BaseModel):
    """流式数据块."""

    data: Any = Field(..., description="数据内容")
    is_done: bool = Field(default=False, description="是否为结束标记")
    metadata: dict[str, Any] = Field(
        default_factory=dict, description="元数据（如 token 用量、进度等）"
    )


class StreamInvokeResult(BaseModel):
    """流式调用聚合结果（消费完所有 chunk 后生成）."""

    skill_id: str = Field(..., description="技能 ID")
    action: str = Field(..., description="动作标识")
    status: str = Field(default="success", description="状态")
    data: Any = Field(default=None, description="完整聚合数据")
    error: str | None = Field(default=None, description="错误信息")
    latency_ms: float = Field(..., description="总耗时（毫秒）")
    trace_id: str = Field(..., description="追踪 ID")
    chunk_count: int = Field(default=0, description="数据块数量")


StreamHandler = Callable[[StreamChunk], None]


class StreamingInvoker:
    """流式调用器.

    包装 Skill 为异步生成器，支持逐块消费输出。
    """

    def __init__(self, router: SkillRouter | None = None) -> None:
        self._router = router

    async def invoke_stream(
        self,
        request: SkillInvokeRequest,
        agent_id: str,
        on_chunk: StreamHandler | None = None,
    ) -> AsyncGenerator[StreamChunk, None]:
        """流式调用技能.

        优先调用技能的 invoke_stream 方法；若技能未实现，
        则退化为 invoke + 单块 yield。

        Args:
            request: 调用请求.
            agent_id: Agent 标识.
            on_chunk: 可选的逐块回调.

        Yields:
            StreamChunk 数据块.
        """
        start = time.perf_counter()
        sid = request.skill_id
        router = self._router or SkillRouter()

        # 阶段1: 权限检查（复用 router 的权限检查逻辑）
        if hasattr(router, "_check_permission"):
            perm_result = router._check_permission(
                agent_id, sid, request.action, request.trace_id
            )
            if perm_result is not None:
                latency = (time.perf_counter() - start) * 1000
                yield StreamChunk(
                    data=None,
                    is_done=True,
                    metadata={
                        "error": perm_result.error,
                        "status": "unauthorized",
                        "latency_ms": latency,
                    },
                )
                return

        # 阶段2: 技能解析
        skill = None
        if hasattr(router, "_resolve_skill"):
            skill_or_error = router._resolve_skill(
                sid, request.action, request.trace_id
            )
            if isinstance(skill_or_error, SkillInvokeResult):
                latency = (time.perf_counter() - start) * 1000
                yield StreamChunk(
                    data=None,
                    is_done=True,
                    metadata={
                        "error": skill_or_error.error,
                        "status": skill_or_error.status,
                        "latency_ms": latency,
                    },
                )
                return
            skill = skill_or_error
        else:
            skill = router._registry.get_skill(sid)

        if skill is None:
            latency = (time.perf_counter() - start) * 1000
            yield StreamChunk(
                data=None,
                is_done=True,
                metadata={
                    "error": f"Skill {sid} not found",
                    "status": "not_found",
                    "latency_ms": latency,
                },
            )
            return

        # 阶段3: 执行（带整体超时保护）
        chunk_count = 0
        sub_stream = None
        try:
            if hasattr(skill, "invoke_stream") and callable(
                getattr(skill, "invoke_stream")
            ):
                sub_stream = skill.invoke_stream(request)
                try:
                    async for chunk in sub_stream:
                        chunk_count += 1
                        if on_chunk:
                            on_chunk(chunk)
                        yield chunk
                finally:
                    # 【第四轮优化 - P1】确保子生成器被关闭，防止资源泄漏
                    if sub_stream is not None:
                        await sub_stream.aclose()
            else:
                # 退化路径：同步 invoke 后拆分为单块
                result = await router.invoke(request, agent_id)
                chunk = StreamChunk(
                    data=result.data,
                    is_done=True,
                    metadata={
                        "status": result.status,
                        "latency_ms": result.latency_ms,
                        "error": result.error,
                    },
                )
                if on_chunk:
                    on_chunk(chunk)
                yield chunk
        except asyncio.TimeoutError:
            latency = (time.perf_counter() - start) * 1000
            yield StreamChunk(
                data=None,
                is_done=True,
                metadata={
                    "error": f"Stream timeout",
                    "status": "timeout",
                    "latency_ms": latency,
                    "chunk_count": chunk_count,
                },
            )
        except Exception as e:
            latency = (time.perf_counter() - start) * 1000
            logger.error(
                "stream_invoke_error",
                skill_id=sid,
                action=request.action,
                trace_id=request.trace_id,
                error=str(e),
            )
            yield StreamChunk(
                data=None,
                is_done=True,
                metadata={
                    "error": str(e),
                    "status": "failure",
                    "latency_ms": latency,
                    "chunk_count": chunk_count,
                },
            )
        finally:
            # 【第四轮优化 - P1】异常路径也确保子生成器关闭
            if sub_stream is not None:
                try:
                    await sub_stream.aclose()
                except Exception:
                    pass

    async def collect(
        self,
        request: SkillInvokeRequest,
        agent_id: str,
    ) -> StreamInvokeResult:
        """消费完整流并聚合为结果.

        Args:
            request: 调用请求.
            agent_id: Agent 标识.

        Returns:
            聚合后的流式调用结果.
        """
        start = time.perf_counter()
        chunks: list[Any] = []
        status = "success"
        error: str | None = None
        chunk_count = 0

        async for chunk in self.invoke_stream(request, agent_id):
            chunk_count += 1
            if not chunk.is_done:
                chunks.append(chunk.data)
            if chunk.metadata.get("status") in ("failure", "not_found", "timeout"):
                status = chunk.metadata["status"]
                error = chunk.metadata.get("error")

        latency = (time.perf_counter() - start) * 1000

        return StreamInvokeResult(
            skill_id=request.skill_id,
            action=request.action,
            status=status,
            data=chunks if len(chunks) > 1 else (chunks[0] if chunks else None),
            error=error,
            latency_ms=latency,
            trace_id=request.trace_id,
            chunk_count=chunk_count,
        )


class StreamableSkillMixin:
    """流式技能混入类.

    技能开发者继承此混入，只需实现 `stream` 生成器方法，
    即可自动获得 invoke_stream 能力。
    """

    async def stream(
        self, request: SkillInvokeRequest
    ) -> AsyncGenerator[StreamChunk, None]:
        """子类必须实现的流式生成器.

        Args:
            request: 调用请求.

        Yields:
            StreamChunk.
        """
        raise NotImplementedError

    async def invoke_stream(
        self, request: SkillInvokeRequest
    ) -> AsyncGenerator[StreamChunk, None]:
        """统一的流式调用入口（由 StreamingInvoker 调用）."""
        async for chunk in self.stream(request):
            yield chunk

    async def invoke(self, request: SkillInvokeRequest) -> SkillInvokeResult:
        """退化到流式聚合后的同步结果."""
        from skill_cluster.streaming import StreamingInvoker

        invoker = StreamingInvoker()
        result = await invoker.collect(request, agent_id="system")
        return SkillInvokeResult(
            skill_id=result.skill_id,
            action=result.action,
            status=result.status,  # type: ignore[arg-type]
            data=result.data if isinstance(result.data, dict) else {"data": result.data},
            error=result.error,
            latency_ms=result.latency_ms,
            trace_id=result.trace_id,
        )
