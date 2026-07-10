"""外部 Agent 适配器包"""

from federation.adapters.base import AgentAdapterBase
from federation.adapters.openai import OpenAIAdapter
from federation.adapters.anthropic import AnthropicAdapter
from federation.adapters.gemini import GeminiAdapter
from federation.adapters.local_model import LocalModelAdapter

__all__ = [
    "AgentAdapterBase",
    "OpenAIAdapter",
    "AnthropicAdapter",
    "GeminiAdapter",
    "LocalModelAdapter",
]
