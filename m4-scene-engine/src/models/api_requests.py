"""API 请求模型集中管理.

将分散在各路由文件中的 Pydantic 请求模型集中管理，
所有模型都带有严格的字段验证（min_length, max_length, pattern, ge, le 等）。

使用方式:
    from src.models.api_requests import SceneSwitchRequest, SceneRecognizeRequest
"""

from __future__ import annotations

from typing import Any, Optional, List, Dict

from pydantic import BaseModel, Field


# ===========================================================================
# 1. 场景管理类
# ===========================================================================

class SceneSwitchRequest(BaseModel):
    """场景切换请求体."""

    to_scene: str = Field(
        ...,
        min_length=1,
        max_length=64,
        pattern=r'^[a-z][a-z0-9_]*$',
        description="目标场景ID，小写字母开头，仅含小写字母、数字和下划线",
    )
    from_scene: str = Field(
        "",
        max_length=64,
        pattern=r'^[a-z][a-z0-9_]*$|^$',
        description="源场景ID（可选），小写字母开头，仅含小写字母、数字和下划线",
    )
    trigger_type: str = Field(
        "manual",
        pattern=r'^(manual|auto|recognize)$',
        description="触发类型: manual / auto / recognize",
    )
    user_id: str = Field(
        "default",
        min_length=1,
        max_length=128,
        description="用户ID",
    )
    reason: str = Field(
        "",
        max_length=500,
        description="切换原因",
    )


class SceneRecognizeRequest(BaseModel):
    """场景识别请求体."""

    text: str = Field(
        ...,
        min_length=1,
        max_length=2000,
        description="用户输入文本，1-2000字符",
    )
    context: dict[str, Any] = Field(
        default_factory=dict,
        description="上下文信息",
    )
    user_id: str = Field(
        "default",
        min_length=1,
        max_length=128,
        description="用户ID",
    )
    include_all_scores: bool = Field(
        True,
        description="是否返回所有场景得分",
    )


class SceneConfigUpdateRequest(BaseModel):
    """场景配置更新请求体."""

    config: dict[str, Any] = Field(
        ...,
        description="配置更新字典",
    )


# ===========================================================================
# 2. 上下文类
# ===========================================================================

class ContextSaveRequest(BaseModel):
    """上下文保存请求体."""

    context_json: dict[str, Any] = Field(
        default_factory=dict,
        description="上下文数据字典",
    )


# ===========================================================================
# 3. 管理员类
# ===========================================================================

class AdminConfigUpdateRequest(BaseModel):
    """全局配置更新请求体."""

    config: dict[str, Any] = Field(
        ...,
        description="配置更新字典",
    )


class AdminSceneConfigRequest(BaseModel):
    """管理员场景配置请求体."""

    scene_id: str = Field(
        ...,
        min_length=1,
        max_length=64,
        pattern=r'^[a-z][a-z0-9_]*$',
        description="场景ID，小写字母开头，仅含小写字母、数字和下划线",
    )
    enabled: Optional[bool] = Field(
        None,
        description="是否启用该场景",
    )
    priority: Optional[int] = Field(
        None,
        ge=0,
        le=100,
        description="场景优先级，0-100",
    )
    auto_switch_enabled: Optional[bool] = Field(
        None,
        description="是否允许自动切换到该场景",
    )
    custom_params: Optional[dict[str, Any]] = Field(
        None,
        description="自定义参数",
    )


class AdminMcpConfigUpdateRequest(BaseModel):
    """MCP 服务配置更新请求体."""

    mcp_enabled: Optional[bool] = Field(
        None,
        description="是否启用 MCP 服务",
    )
    mcp_base_url: Optional[str] = Field(
        None,
        max_length=512,
        description="MCP 服务地址",
    )
    mcp_api_key: Optional[str] = Field(
        None,
        max_length=256,
        description="MCP API 密钥",
    )
    mcp_timeout: Optional[float] = Field(
        None,
        ge=1.0,
        le=300.0,
        description="请求超时时间（秒），1-300",
    )


# ===========================================================================
# 4. MCP 工具类
# ===========================================================================

class McpToolConfig(BaseModel):
    """MCP 工具配置项."""

    name: str = Field(
        ...,
        min_length=1,
        max_length=128,
        pattern=r'^[a-z][a-z0-9_]*$',
        description="MCP 工具名称，小写字母开头，仅含小写字母、数字和下划线",
    )
    params: dict[str, Any] = Field(
        default_factory=dict,
        description="默认参数",
    )
    trigger: str = Field(
        "manual",
        pattern=r'^(on_enter|on_leave|manual)$',
        description="触发时机: on_enter / on_leave / manual",
    )
    required: bool = Field(
        False,
        description="是否必填（失败是否阻塞场景切换）",
    )


class McpToolCallRequest(BaseModel):
    """MCP 工具调用请求体."""

    arguments: dict[str, Any] = Field(
        default_factory=dict,
        description="工具调用参数",
    )


class SceneMcpToolsUpdateRequest(BaseModel):
    """场景 MCP 工具绑定更新请求体."""

    mcp_tools: list[McpToolConfig] = Field(
        ...,
        min_length=0,
        max_length=50,
        description="MCP 工具配置列表，最多 50 个",
    )


# ===========================================================================
# 5. 技能类
# ===========================================================================

class SkillBindingConfig(BaseModel):
    """场景技能绑定配置项."""

    name: str = Field(
        ...,
        min_length=1,
        max_length=128,
        pattern=r'^[a-z][a-z0-9_]*$',
        description="技能名称，小写字母开头，仅含小写字母、数字和下划线",
    )
    auto_trigger: list[str] = Field(
        default_factory=list,
        description="自动触发时机: on_enter / on_leave，空列表表示手动触发",
    )
    default_params: dict[str, Any] = Field(
        default_factory=dict,
        description="技能默认参数",
    )
    required: bool = Field(
        False,
        description="是否必填（失败是否阻塞场景切换）",
    )


class SkillExecuteRequest(BaseModel):
    """技能执行请求体."""

    params: dict[str, Any] = Field(
        default_factory=dict,
        description="技能执行参数",
    )
    context: dict[str, Any] = Field(
        default_factory=dict,
        description="执行上下文",
    )


class SceneSkillsUpdateRequest(BaseModel):
    """场景技能绑定更新请求体."""

    skills: list[SkillBindingConfig] = Field(
        ...,
        min_length=0,
        max_length=50,
        description="技能绑定配置列表，最多 50 个",
    )


# ===========================================================================
# 6. 业务模式类
# ===========================================================================

class ModeEnterRequest(BaseModel):
    """进入模式请求体."""

    user_id: str = Field(
        "default",
        min_length=1,
        max_length=128,
        description="用户ID",
    )
    context: dict[str, Any] = Field(
        default_factory=dict,
        description="进入模式时的上下文",
    )


class ModeLeaveRequest(BaseModel):
    """离开模式请求体."""

    user_id: str = Field(
        "default",
        min_length=1,
        max_length=128,
        description="用户ID",
    )
    context: dict[str, Any] = Field(
        default_factory=dict,
        description="离开模式时的上下文",
    )


# ===========================================================================
# 7. 聊天类
# ===========================================================================

class ChatSendRequest(BaseModel):
    """发送消息请求体."""

    message: str = Field(
        ...,
        min_length=1,
        max_length=4000,
        description="用户消息内容，1-4000字符",
    )
    conversation_id: Optional[str] = Field(
        None,
        min_length=1,
        max_length=64,
        description="会话ID，不传则新建会话",
    )
    mode: str = Field(
        "main-chat",
        min_length=1,
        max_length=64,
        description="聊天模式",
    )
    stream: bool = Field(
        False,
        description="是否流式输出",
    )
    system_prompt: Optional[str] = Field(
        None,
        max_length=2000,
        description="自定义系统提示词，最多2000字符",
    )


class ChatConversationCreateRequest(BaseModel):
    """新建会话请求体."""

    mode: str = Field(
        "main-chat",
        min_length=1,
        max_length=64,
        description="聊天模式",
    )
    title: Optional[str] = Field(
        None,
        max_length=200,
        description="会话标题，最多200字符",
    )


class ChatNewConversationRequest(ChatConversationCreateRequest):
    """新建会话请求体（兼容命名，与 ChatConversationCreateRequest 等价."""
    pass


# ===========================================================================
# 8. 语音类
# ===========================================================================

class VoiceSynthesizeRequest(BaseModel):
    """文本转语音请求体."""

    text: str = Field(
        ...,
        min_length=1,
        max_length=2000,
        description="要合成的文本，1-2000字符",
    )
    voice_type: Optional[str] = Field(
        None,
        max_length=64,
        description="语音类型",
    )
    speed: Optional[float] = Field(
        None,
        ge=0.5,
        le=2.0,
        description="语速倍率 0.5-2.0",
    )
    pitch: Optional[float] = Field(
        None,
        ge=0.5,
        le=2.0,
        description="音调倍率 0.5-2.0",
    )
    output_format: str = Field(
        "mp3",
        pattern=r'^(mp3|wav)$',
        description="输出格式 mp3/wav",
    )


class VoiceConfigUpdateRequest(BaseModel):
    """语音配置更新请求体."""

    voice_type: Optional[str] = Field(
        None,
        max_length=64,
        description="语音类型",
    )
    voice_speed: Optional[float] = Field(
        None,
        ge=0.5,
        le=2.0,
        description="语速倍率 0.5-2.0",
    )
    voice_pitch: Optional[float] = Field(
        None,
        ge=0.5,
        le=2.0,
        description="音调倍率 0.5-2.0",
    )
    prefer_online: Optional[bool] = Field(
        None,
        description="是否优先使用在线服务",
    )
    asr_model_size: Optional[str] = Field(
        None,
        max_length=32,
        description="ASR 模型大小",
    )
    asr_language: Optional[str] = Field(
        None,
        max_length=16,
        description="ASR 默认语言",
    )
    tts_output_format: Optional[str] = Field(
        None,
        pattern=r'^(mp3|wav)$',
        description="TTS 输出格式 mp3/wav",
    )


class VoiceWakeWordConfigUpdateRequest(BaseModel):
    """唤醒词配置更新请求体."""

    wake_words: list[str] = Field(
        ...,
        min_length=1,
        max_length=20,
        description="唤醒词列表，至少1个，最多20个",
    )


class VoiceWakeWordAddRequest(BaseModel):
    """添加唤醒词请求体."""

    word: str = Field(
        ...,
        min_length=1,
        max_length=32,
        description="要添加的唤醒词，1-32字符",
    )


class VoiceWakeWordRemoveRequest(BaseModel):
    """移除唤醒词请求体."""

    word: str = Field(
        ...,
        min_length=1,
        max_length=32,
        description="要移除的唤醒词，1-32字符",
    )


class VoiceAsrTranscribeRequest(BaseModel):
    """语音转文本请求体（用于描述 Form 参数的模型化参考）.

    注意：实际路由使用 UploadFile + Form，
    此模型用于文档和内部参数验证参考。
    """

    language: str = Field(
        "zh",
        pattern=r'^(zh|en|auto)$',
        description="语言：zh / en / auto",
    )


class VoiceVadDetectRequest(BaseModel):
    """语音活动检测请求体（用于描述 Form 参数的模型化参考）.

    注意：实际路由使用 UploadFile + Form，
    此模型用于文档和内部参数验证参考。
    """

    threshold: float = Field(
        0.5,
        ge=0.0,
        le=1.0,
        description="检测阈值，0.0-1.0",
    )
    min_speech_duration: float = Field(
        0.3,
        gt=0.0,
        le=10.0,
        description="最小说话时长（秒），0-10",
    )
    max_silence_duration: float = Field(
        0.5,
        gt=0.0,
        le=30.0,
        description="最大静音时长（秒），0-30",
    )


# ===========================================================================
# 9. 手表类
# ===========================================================================

class WatchDeviceRegisterRequest(BaseModel):
    """手表设备注册/绑定请求体."""

    device_id: str = Field(
        ...,
        min_length=1,
        max_length=128,
        description="设备ID",
    )
    name: str = Field(
        ...,
        min_length=1,
        max_length=64,
        description="设备名称，1-64字符",
    )
    device_type: str = Field(
        "watch",
        pattern=r'^(watch|ring|band)$',
        description="设备类型：watch / ring / band",
    )
    mac_address: Optional[str] = Field(
        "",
        max_length=32,
        description="MAC地址",
    )


class WatchDeviceBindRequest(WatchDeviceRegisterRequest):
    """绑定设备请求体（与 WatchDeviceRegisterRequest 等价，兼容命名）."""
    pass


class WatchDeviceUpdateRequest(BaseModel):
    """设备信息更新请求体."""

    name: Optional[str] = Field(
        None,
        min_length=1,
        max_length=64,
        description="设备名称，1-64字符",
    )
    status: Optional[str] = Field(
        None,
        pattern=r'^(online|offline)$',
        description="设备状态：online / offline",
    )
    battery: Optional[int] = Field(
        None,
        ge=0,
        le=100,
        description="电量百分比，0-100",
    )
    features: Optional[list[str]] = Field(
        None,
        max_length=50,
        description="支持的功能列表，最多50项",
    )
    settings: Optional[dict[str, Any]] = Field(
        None,
        description="设备配置",
    )


class WatchHealthDataSubmitRequest(BaseModel):
    """手表健康数据提交请求体."""

    device_id: str = Field(
        ...,
        min_length=1,
        max_length=128,
        description="设备ID",
    )
    data_type: str = Field(
        ...,
        pattern=r'^(heart_rate|steps|spo2|sleep)$',
        description="数据类型：heart_rate / steps / spo2 / sleep",
    )
    value: float = Field(
        ...,
        ge=0,
        le=100000,
        description="数据值",
    )
    timestamp: Optional[float] = Field(
        None,
        ge=0,
        description="数据时间戳（秒），不传则使用当前时间",
    )
    unit: Optional[str] = Field(
        None,
        max_length=16,
        description="数据单位",
    )
    extra: Optional[dict[str, Any]] = Field(
        None,
        description="扩展数据",
    )


class WatchHealthSyncRequest(BaseModel):
    """健康数据同步请求体."""

    device_id: str = Field(
        ...,
        min_length=1,
        max_length=128,
        description="设备ID",
    )
    data_type: Optional[str] = Field(
        None,
        pattern=r'^(heart_rate|steps|spo2|sleep)$',
        description="数据类型，不传则同步全部",
    )
    days: int = Field(
        7,
        ge=1,
        le=90,
        description="同步天数，1-90天",
    )


class WatchNotificationSendRequest(BaseModel):
    """发送通知请求体."""

    device_id: str = Field(
        ...,
        min_length=1,
        max_length=128,
        description="设备ID",
    )
    title: str = Field(
        ...,
        min_length=1,
        max_length=128,
        description="通知标题，1-128字符",
    )
    content: str = Field(
        ...,
        min_length=1,
        max_length=1000,
        description="通知内容，1-1000字符",
    )
    notification_type: str = Field(
        "info",
        pattern=r'^(info|warning|error|reminder)$',
        description="通知类型：info / warning / error / reminder",
    )
    action_type: Optional[str] = Field(
        "",
        max_length=64,
        description="动作类型",
    )
    action_data: Optional[dict[str, Any]] = Field(
        default_factory=dict,
        description="动作数据",
    )


class WatchSettingsUpdateRequest(BaseModel):
    """手表配置更新请求体."""

    settings: dict[str, Any] = Field(
        ...,
        description="配置项字典",
    )


# ===========================================================================
# 10. 工作空间类
# ===========================================================================

class WorkspaceVSCodeLaunchRequest(BaseModel):
    """VS Code 启动请求体."""

    project_path: str = Field(
        "",
        max_length=512,
        description="项目目录路径（可选）",
    )
    new_window: bool = Field(
        True,
        description="是否在新窗口打开",
    )


class WorkspaceVSCodeOpenRequest(BaseModel):
    """打开指定项目请求体."""

    project_path: str = Field(
        ...,
        min_length=1,
        max_length=512,
        description="项目目录路径",
    )
    new_window: bool = Field(
        True,
        description="是否在新窗口打开",
    )


class WorkspaceVSCodeExtensionRequest(BaseModel):
    """VS Code 扩展操作请求体."""

    extension_id: str = Field(
        ...,
        min_length=1,
        max_length=128,
        pattern=r'^[a-z0-9][a-z0-9._-]*$',
        description="扩展ID（如 ms-python.python）",
    )


class WorkspaceVSCodeOpenFileRequest(BaseModel):
    """打开文件请求体."""

    file_path: str = Field(
        ...,
        min_length=1,
        max_length=512,
        description="文件路径",
    )
    line: Optional[int] = Field(
        None,
        ge=1,
        description="行号（可选），从1开始",
    )


class WorkspaceVSCodeRunCommandRequest(BaseModel):
    """执行命令请求体."""

    command: str = Field(
        ...,
        min_length=1,
        max_length=2000,
        description="要执行的命令，1-2000字符",
    )
    cwd: str = Field(
        "",
        max_length=512,
        description="工作目录（可选）",
    )


# ===========================================================================
# 兼容别名（与各路由文件中本地定义的模型名保持一致）
# ===========================================================================

# 手表路由兼容别名
BindDeviceRequest = WatchDeviceBindRequest
DeviceUpdateRequest = WatchDeviceUpdateRequest
HealthSyncRequest = WatchHealthSyncRequest
SendNotificationRequest = WatchNotificationSendRequest
WatchSettingsUpdate = WatchSettingsUpdateRequest

# 语音路由兼容别名
TTSRequest = VoiceSynthesizeRequest
VoiceConfigUpdate = VoiceConfigUpdateRequest
WakeWordConfigUpdate = VoiceWakeWordConfigUpdateRequest

# 聊天路由兼容别名
ChatNewConversationRequest = ChatConversationCreateRequest

# 工作空间路由兼容别名
VSCodeLaunchRequest = WorkspaceVSCodeLaunchRequest
VSCodeOpenRequest = WorkspaceVSCodeOpenRequest
VSCodeExtensionRequest = WorkspaceVSCodeExtensionRequest
VSCodeOpenFileRequest = WorkspaceVSCodeOpenFileRequest
VSCodeRunCommandRequest = WorkspaceVSCodeRunCommandRequest


# ===========================================================================
# __all__ 导出列表
# ===========================================================================

__all__ = [
    # 1. 场景管理类
    "SceneSwitchRequest",
    "SceneRecognizeRequest",
    "SceneConfigUpdateRequest",
    # 2. 上下文类
    "ContextSaveRequest",
    # 3. 管理员类
    "AdminConfigUpdateRequest",
    "AdminSceneConfigRequest",
    "AdminMcpConfigUpdateRequest",
    # 4. MCP 工具类
    "McpToolConfig",
    "McpToolCallRequest",
    "SceneMcpToolsUpdateRequest",
    # 5. 技能类
    "SkillBindingConfig",
    "SkillExecuteRequest",
    "SceneSkillsUpdateRequest",
    # 6. 业务模式类
    "ModeEnterRequest",
    "ModeLeaveRequest",
    # 7. 聊天类
    "ChatSendRequest",
    "ChatConversationCreateRequest",
    "ChatNewConversationRequest",
    # 8. 语音类
    "VoiceSynthesizeRequest",
    "VoiceConfigUpdateRequest",
    "VoiceWakeWordConfigUpdateRequest",
    "VoiceWakeWordAddRequest",
    "VoiceWakeWordRemoveRequest",
    "VoiceAsrTranscribeRequest",
    "VoiceVadDetectRequest",
    # 9. 手表类
    "WatchDeviceRegisterRequest",
    "WatchDeviceBindRequest",
    "WatchDeviceUpdateRequest",
    "WatchHealthDataSubmitRequest",
    "WatchHealthSyncRequest",
    "WatchNotificationSendRequest",
    "WatchSettingsUpdateRequest",
    # 10. 工作空间类
    "WorkspaceVSCodeLaunchRequest",
    "WorkspaceVSCodeOpenRequest",
    "WorkspaceVSCodeExtensionRequest",
    "WorkspaceVSCodeOpenFileRequest",
    "WorkspaceVSCodeRunCommandRequest",
    # 兼容别名
    "BindDeviceRequest",
    "DeviceUpdateRequest",
    "HealthSyncRequest",
    "SendNotificationRequest",
    "WatchSettingsUpdate",
    "TTSRequest",
    "VoiceConfigUpdate",
    "WakeWordConfigUpdate",
    "VSCodeLaunchRequest",
    "VSCodeOpenRequest",
    "VSCodeExtensionRequest",
    "VSCodeOpenFileRequest",
    "VSCodeRunCommandRequest",
]
