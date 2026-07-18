"""
云汐共享业务层 (shared.business)
==================================

业务能力层，包含各业务引擎和模块客户端。

注意：本层模块后续可能逐步迁移到对应业务模块中，
此处为过渡期保留，方便统一管理和渐进式拆分。

子模块：
- agent_engine: Agent 引擎
- voice_engine: 语音引擎
- personality_engine: 人格引擎
- agent_team: Agent 团队
- multi_agent: 多 Agent 协作
- reasoning_engine: 推理引擎
- cosyvoice_*: CosyVoice 语音相关
- voice_preset_manager: 语音预设管理
- prosody_controller: 韵律控制器
- reminder_voice: 提醒语音
- user_profile: 用户画像
- roles: 角色系统
- context_aware: 上下文感知
- autonomous_learning: 自主学习
- skill_evolution: 技能进化
- rag_knowledge: RAG 知识
- long_term_memory: 长期记忆
- multimodal: 多模态
- a2a_client: A2A 客户端
- llm_client: LLM 客户端
- model_router: 模型路由
- builtin_tools: 内置工具
- tool_system: 工具系统
- module_client: 模块客户端
- process_manager: 进程管理器
- startup_orchestrator: 启动编排器
- distributed: 分布式基础设施
"""

# 模块客户端（基础设施类，使用频率最高）
from .module_client import (
    ModuleKey,
    ModuleCategory,
    ModuleInfo,
    ModuleClient,
    ModuleRegistry,
    ModuleStatus,
    get_registry,
    get_module_registry,
    DEFAULT_MODULE_CONFIGS,
)

# 进程管理
from .process_manager import (
    ProcessManager,
    ProcessInfo,
    ProcessStatus,
    MODULE_CONFIGS,
    get_process_manager,
)

# A2A 客户端
from .a2a_client import A2AClient, A2AError, A2AConnectionError, A2AResponseError

__version__ = "1.2.0"
"""shared.business 版本号"""

__all__ = [
    "__version__",
    # Module Client
    "ModuleKey", "ModuleCategory", "ModuleInfo", "ModuleClient",
    "ModuleRegistry", "ModuleStatus", "get_registry", "get_module_registry",
    "DEFAULT_MODULE_CONFIGS",
    # Process Manager
    "ProcessManager", "ProcessInfo", "ProcessStatus", "MODULE_CONFIGS",
    "get_process_manager",
    # A2A Client
    "A2AClient", "A2AError", "A2AConnectionError", "A2AResponseError",
]
