"""外部 Agent 适配器包"""

from src.federation.adapters.base import AgentAdapterBase
from src.federation.adapters.openai import OpenAIAdapter
from src.federation.adapters.anthropic import AnthropicAdapter
from src.federation.adapters.gemini import GeminiAdapter
from src.federation.adapters.local_model import LocalModelAdapter

__all__ = [
    "AgentAdapterBase",
    "OpenAIAdapter",
    "AnthropicAdapter",
    "GeminiAdapter",
    "LocalModelAdapter",
]
