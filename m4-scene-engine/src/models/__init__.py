"""数据模型与场景定义.

包含场景定义、请求/响应模型、通用响应工具、数据库ORM模型等。

数据库模型请从 db 子包导入：
    from src.models.db import SceneContextDB, get_session
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from pydantic import BaseModel, Field

from . import db  # noqa: F401

# ---------------------------------------------------------------------------
# API 请求模型（从 api_requests 集中导入，保持向后兼容）
# ---------------------------------------------------------------------------

from .api_requests import (  # noqa: F401
    # 场景管理类
    SceneSwitchRequest,
    SceneRecognizeRequest,
    SceneConfigUpdateRequest,
    # 上下文类
    ContextSaveRequest,
    # 管理员类
    AdminConfigUpdateRequest,
    AdminSceneConfigRequest,
    AdminMcpConfigUpdateRequest,
    # MCP 工具类
    McpToolConfig,
    McpToolCallRequest,
    SceneMcpToolsUpdateRequest,
    # 技能类
    SkillBindingConfig,
    SkillExecuteRequest,
    SceneSkillsUpdateRequest,
    # 业务模式类
    ModeEnterRequest,
    ModeLeaveRequest,
    # 聊天类
    ChatSendRequest,
    ChatConversationCreateRequest,
    ChatNewConversationRequest,
    # 语音类
    VoiceSynthesizeRequest,
    VoiceConfigUpdateRequest,
    VoiceWakeWordConfigUpdateRequest,
    VoiceWakeWordAddRequest,
    VoiceWakeWordRemoveRequest,
    VoiceAsrTranscribeRequest,
    VoiceVadDetectRequest,
    # 手表类
    WatchDeviceRegisterRequest,
    WatchDeviceBindRequest,
    WatchDeviceUpdateRequest,
    WatchHealthDataSubmitRequest,
    WatchHealthSyncRequest,
    WatchNotificationSendRequest,
    WatchSettingsUpdateRequest,
    # 工作空间类
    WorkspaceVSCodeLaunchRequest,
    WorkspaceVSCodeOpenRequest,
    WorkspaceVSCodeExtensionRequest,
    WorkspaceVSCodeOpenFileRequest,
    WorkspaceVSCodeRunCommandRequest,
    # 兼容别名
    BindDeviceRequest,
    DeviceUpdateRequest,
    HealthSyncRequest,
    SendNotificationRequest,
    WatchSettingsUpdate,
    TTSRequest,
    VoiceConfigUpdate,
    WakeWordConfigUpdate,
    VSCodeLaunchRequest,
    VSCodeOpenRequest,
    VSCodeExtensionRequest,
    VSCodeOpenFileRequest,
    VSCodeRunCommandRequest,
)

# ---------------------------------------------------------------------------
# 场景定义（从 scene_definitions 导入，保持向后兼容）
# ---------------------------------------------------------------------------

from .scene_definitions import (  # noqa: F401
    DEFAULT_SCENE,
    ACTION_TYPES,
    SCENE_DEFINITIONS,
)

# ---------------------------------------------------------------------------
# 数据类
# ---------------------------------------------------------------------------

@dataclass
class SceneSwitchRecord:
    """场景切换记录."""
    id: str = ""
    from_scene: str = ""
    to_scene: str = ""
    trigger_type: str = "manual"  # manual/auto/recognize
    user_id: str = "default"
    timestamp: float = 0.0
    reason: str = ""


@dataclass
class SceneContext:
    """场景上下文数据."""
    scene_id: str = ""
    context_data: dict[str, Any] = field(default_factory=dict)
    last_updated: float = 0.0
    update_count: int = 0


# ---------------------------------------------------------------------------
# 通用响应工具（从 response_utils 导入，保持向后兼容）
# ---------------------------------------------------------------------------

from .response_utils import make_response  # noqa: F401, E402
