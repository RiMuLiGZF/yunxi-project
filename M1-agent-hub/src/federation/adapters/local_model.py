"""
本地模型适配器 — LocalModelAdapter

复用现有 M3 端云协同的本地推理能力，作为联邦调度的本地备选。
隐私等级最高（LOCAL_ONLY），零成本。
"""

from __future__ import annotations

from typing import Any

import structlog

from src.federation.adapters.base import AgentAdapterBase

logger = structlog.get_logger(__name__)


class LocalModelAdapter(AgentAdapterBase):
    """本地模型适配器（复用 M3 端云协同的本地推理能力）"""

    provider: str = "Local"
    adapter_type: str = "local_model"

    def __init__(
        self,
        agent_id: str = "ext_local_7b",
        display_name: str = "本地模型 (7B)",
        model: str = "local-7b-instruct",
        config: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> None:
        config = config or {}
        config.setdefault("model", model)
        # 本地模型零成本
        config.setdefault("cost_model", {
            "input_per_1k": 0.0,
            "output_per_1k": 0.0,
            "currency": "USD",
        })
        super().__init__(agent_id, display_name, config, **kwargs)

    async def _invoke_impl(
        self,
        prompt: str,
        system_prompt: str,
        temperature: float,
        max_tokens: int,
        metadata: dict[str, Any],
    ) -> dict[str, Any]:
        """调用本地模型

        生产环境通过 M3 InferenceInterface 的本地推理路径执行。
        此处为概念级实现。
        """
        model = self._config.get("model", "local-7b-instruct")

        # 概念级实现：模拟本地模型响应
        # 生产环境调用：inference_interface.chat(prompt, model="local")
        simulated_output = (
            f"[本地模型 · {model}]\n"
            f"已在本地处理您的请求（{len(prompt)} 字符）。\n\n"
            f"这是本地模型的概念级响应。所有数据均在设备本地处理，"
            f"无需上传云端，隐私等级最高。\n\n"
            f"注：本地模型响应质量可能低于云端大模型，但具备完全的隐私保护和零成本优势。"
        )

        input_tokens = len(prompt) // 4
        output_tokens = len(simulated_output) // 4
        return {
            "output": simulated_output,
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "model": model,
            "local": True,
        }

    async def _health_check_impl(self) -> dict[str, Any]:
        """本地模型健康检查"""
        model = self._config.get("model", "local-7b-instruct")
        # 概念级：假设本地模型可用
        # 生产环境应实际检测模型加载状态
        return {
            "healthy": True,
            "message": f"本地模型 {model} 可用（概念级）",
        }

    def calculate_cost(self, input_tokens: int, output_tokens: int) -> float:
        """本地模型零成本"""
        return 0.0
