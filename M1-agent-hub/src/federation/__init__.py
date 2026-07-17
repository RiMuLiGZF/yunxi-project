"""Agent 联邦调度系统（V11.0-FEDERATION）

支持外部主流 AI Agent 的统一调度、成本管控、隐私防护和结果对比。
"""

__version__ = "1.0.0"


from src.federation.registry import ExternalAgentRegistry
from src.federation.scheduler import FederatedScheduler
from src.federation.remote_discovery import RemoteAgentDiscovery, RemoteAgent
from src.federation.comparator import MultiAgentComparator
from src.federation.cost_controller import CostController
from src.federation.privacy_guard import PrivacyGuard, FederationPrivacyGuard
from src.federation.adapters.base import AgentAdapterBase
from src.federation.adapters.openai import OpenAIAdapter
from src.federation.adapters.anthropic import AnthropicAdapter
from src.federation.adapters.gemini import GeminiAdapter
from src.federation.adapters.local_model import LocalModelAdapter

__all__ = [
    "ExternalAgentRegistry",
    "FederatedScheduler",
    "RemoteAgentDiscovery",
    "RemoteAgent",
    "MultiAgentComparator",
    "CostController",
    "FederationPrivacyGuard",
    "AgentAdapterBase",
    "OpenAIAdapter",
    "AnthropicAdapter",
    "GeminiAdapter",
    "LocalModelAdapter",
]
