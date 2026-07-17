"""
OpenAI 适配器 — OpenAI GPT 系列

概念级实现：模拟 OpenAI API 调用格式。
生产环境需替换为真实的 openai SDK 调用。
"""

from __future__ import annotations

import hashlib
from typing import Any

import structlog

from src.federation.adapters.base import AgentAdapterBase

logger = structlog.get_logger(__name__)


class OpenAIAdapter(AgentAdapterBase):
    """OpenAI GPT 系列适配器"""

    provider: str = "OpenAI"
    adapter_type: str = "openai"

    def __init__(
        self,
        agent_id: str = "ext_openai_gpt4",
        display_name: str = "GPT-4",
        model: str = "gpt-4",
        api_key: str = "",
        config: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> None:
        config = config or {}
        config.setdefault("model", model)
        config.setdefault("api_key", api_key)
        # 默认成本模型（GPT-4 参考价）
        config.setdefault("cost_model", {
            "input_per_1k": 0.03,
            "output_per_1k": 0.06,
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
        """模拟 OpenAI 调用

        开发环境下返回概念级响应，生产环境替换为真实 API 调用。
        """
        model = self._config.get("model", "gpt-4")
        api_key = self._config.get("api_key", "")

        # 概念级实现：生成模拟响应
        # 生产环境使用：
        # import openai
        # client = openai.AsyncOpenAI(api_key=api_key)
        # response = await client.chat.completions.create(...)

        if not api_key:
            # 无 API Key 时返回模拟响应
            simulated_output = self._simulate_response(prompt, model, temperature)
            input_tokens = len(prompt) // 4  # 粗略估算
            output_tokens = len(simulated_output) // 4
            return {
                "output": simulated_output,
                "input_tokens": input_tokens,
                "output_tokens": output_tokens,
                "model": model,
                "simulated": True,
            }

        # 有 API Key 的情况下，此处应调用真实 API
        # 为安全起见，开发环境仍返回模拟响应
        simulated_output = self._simulate_response(prompt, model, temperature)
        input_tokens = len(prompt) // 4
        output_tokens = len(simulated_output) // 4
        return {
            "output": simulated_output,
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "model": model,
            "simulated": True,
            "note": "开发环境模拟响应，生产环境调用真实API",
        }

    async def _health_check_impl(self) -> dict[str, Any]:
        """健康检查：检测 API Key 配置状态"""
        api_key = self._config.get("api_key", "")
        if not api_key:
            return {"healthy": False, "message": "未配置 API Key"}
        return {"healthy": True, "message": "API Key 已配置（开发环境模拟）"}

    def _simulate_response(self, prompt: str, model: str, temperature: float) -> str:
        """生成模拟响应（概念级）"""
        # 简单的模拟：基于输入生成一个确定性的简短回复
        h = hashlib.md5(prompt.encode()).hexdigest()[:8]
        return (
            f"[模拟响应 · {model}]\n"
            f"已收到您的请求（长度: {len(prompt)} 字符，温度: {temperature}）。\n\n"
            f"这是一个概念级的模拟响应。在生产环境中，这里会返回来自 {model} 的真实回答。\n"
            f"响应标识: {h}"
        )
