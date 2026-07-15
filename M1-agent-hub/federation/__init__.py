"""Agent 联邦调度系统（V11.0-FEDERATION）

支持外部主流 AI Agent 的统一调度、成本管控、隐私防护和结果对比。
"""

__version__ = "1.0.0"


from federation.registry import ExternalAgentRegistry
from federation.scheduler import FederatedScheduler
from federation.remote_discovery import RemoteAgentDiscovery, RemoteAgent
from federation.comparator import MultiAgentComparator
from federation.cost_controller import CostController
from federation.privacy_guard import PrivacyGuard, FederationPrivacyGuard
from federation.adapters.base import AgentAdapterBase
from federation.adapters.openai import OpenAIAdapter
from federation.adapters.anthropic import AnthropicAdapter
from federation.adapters.gemini import GeminiAdapter
from federation.adapters.local_model import LocalModelAdapter

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
