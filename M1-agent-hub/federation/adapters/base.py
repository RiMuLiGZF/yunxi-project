"""
外部 Agent 适配器基类 — AgentAdapterBase

定义所有外部 Agent 适配器的统一接口。
"""

from __future__ import annotations

import time
from abc import ABC, abstractmethod
from typing import Any

import structlog

logger = structlog.get_logger(__name__)


class AgentAdapterBase(ABC):
    """外部 Agent 适配器基类

    所有外部 Agent 适配器必须继承此类，实现统一的调用接口。
    """

    provider: str = "base"
    adapter_type: str = "base"

    def __init__(
        self,
        agent_id: str,
        display_name: str,
        config: dict[str, Any] | None = None,
        timeout: float = 30.0,
        max_retries: int = 1,
    ) -> None:
        self.agent_id = agent_id
        self.display_name = display_name
        self._config = config or {}
        self._timeout = timeout
        self._max_retries = max_retries
        self._logger = logger.bind(
            adapter=self.adapter_type,
            agent_id=agent_id,
        )

    # ── 公开接口 ──────────────────────────────────────────

    async def invoke(
        self,
        prompt: str,
        system_prompt: str = "",
        temperature: float = 0.7,
        max_tokens: int = 2048,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """调用外部 Agent

        统一入口，内部处理重试、超时、错误处理。

        Args:
            prompt: 用户输入
            system_prompt: 系统提示词
            temperature: 温度参数
            max_tokens: 最大输出 token 数
            metadata: 元数据

        Returns:
            包含 output, input_tokens, output_tokens, latency_ms, success, error 的字典
        """
        start_time = time.time()
        metadata = metadata or {}
        last_error = ""

        for attempt in range(self._max_retries + 1):
            try:
                self._logger.debug(
                    "adapter_invoke_start",
                    attempt=attempt + 1,
                    prompt_length=len(prompt),
                )

                result = await self._invoke_impl(
                    prompt=prompt,
                    system_prompt=system_prompt,
                    temperature=temperature,
                    max_tokens=max_tokens,
                    metadata=metadata,
                )

                latency_ms = (time.time() - start_time) * 1000
                result["latency_ms"] = latency_ms
                result["success"] = True
                result["error"] = ""

                self._logger.info(
                    "adapter_invoke_success",
                    attempt=attempt + 1,
                    latency_ms=round(latency_ms, 2),
                    input_tokens=result.get("input_tokens", 0),
                    output_tokens=result.get("output_tokens", 0),
                )

                return result

            except TimeoutError as exc:
                last_error = f"超时: {exc}"
                self._logger.warning(
                    "adapter_invoke_timeout",
                    attempt=attempt + 1,
                    error=str(exc),
                )
                if attempt < self._max_retries:
                    continue

            except Exception as exc:
                last_error = str(exc)
                self._logger.error(
                    "adapter_invoke_failed",
                    attempt=attempt + 1,
                    error=str(exc),
                    exc_info=True,
                )
                if attempt < self._max_retries:
                    continue

        # 所有重试都失败
        latency_ms = (time.time() - start_time) * 1000
        return {
            "output": "",
            "input_tokens": 0,
            "output_tokens": 0,
            "latency_ms": latency_ms,
            "success": False,
            "error": last_error,
        }

    async def health_check(self) -> dict[str, Any]:
        """健康检查

        Returns:
            包含 healthy, latency_ms, message 的字典
        """
        try:
            start_time = time.time()
            result = await self._health_check_impl()
            latency_ms = (time.time() - start_time) * 1000
            return {
                "healthy": result.get("healthy", True),
                "latency_ms": latency_ms,
                "message": result.get("message", "ok"),
            }
        except Exception as exc:
            return {
                "healthy": False,
                "latency_ms": 0,
                "message": str(exc),
            }

    def calculate_cost(self, input_tokens: int, output_tokens: int) -> float:
        """计算调用费用

        Args:
            input_tokens: 输入 token 数
            output_tokens: 输出 token 数

        Returns:
            费用（美元）
        """
        cost_model = self._config.get("cost_model", {})
        input_per_1k = cost_model.get("input_per_1k", 0.0)
        output_per_1k = cost_model.get("output_per_1k", 0.0)
        per_request = cost_model.get("per_request", 0.0)
        return (
            input_tokens / 1000 * input_per_1k
            + output_tokens / 1000 * output_per_1k
            + per_request
        )

    # ── 子类实现 ──────────────────────────────────────────

    @abstractmethod
    async def _invoke_impl(
        self,
        prompt: str,
        system_prompt: str,
        temperature: float,
        max_tokens: int,
        metadata: dict[str, Any],
    ) -> dict[str, Any]:
        """实际调用实现，由子类重写

        返回: {"output": str, "input_tokens": int, "output_tokens": int}
        """
        ...

    async def _health_check_impl(self) -> dict[str, Any]:
        """健康检查实现，子类可重写

        默认返回 healthy=True，子类应实现实际的连接测试。
        """
        return {"healthy": True, "message": "ok"}
