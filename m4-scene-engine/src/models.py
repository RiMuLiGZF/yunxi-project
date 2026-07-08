"""数据模型与场景定义.

包含场景定义、请求/响应模型、通用响应工具等。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# 场景定义
# ---------------------------------------------------------------------------

#: 默认场景
DEFAULT_SCENE = "chat"

#: 支持的场景动作类型
ACTION_TYPES: list[str] = [
    "launch_vscode",       # 启动 VS Code
    "open_project",        # 打开项目
    "open_file",           # 打开文件
    "install_extension",   # 安装扩展
    "run_command",         # 执行命令
]

#: 场景定义字典
SCENE_DEFINITIONS: dict[str, dict[str, Any]] = {
    "chat": {
        "id": "chat",
        "name": "日常对话",
        "icon": "💬",
        "description": "日常聊天、问答、闲聊场景",
        "tone": "friendly",
        "keywords": [
            "聊天", "闲聊", "说说", "聊聊", "问答", "提问",
            "你好", "hi", "hello", "在吗", "早上好",
        ],
        "mcp_tools": [],
        "actions": [],
        "skills": [],
    },
    "creative": {
        "id": "creative",
        "name": "创意创作",
        "icon": "🎨",
        "description": "文案写作、内容创作、灵感激发场景",
        "tone": "creative",
        "keywords": [
            "写一篇", "创作", "文案", "文章", "故事", "小说",
            "诗歌", "灵感", "创意", "写点", "写作",
        ],
        "mcp_tools": [],
        "actions": [],
        "skills": [],
    },
    "learning": {
        "id": "learning",
        "name": "学习教育",
        "icon": "📚",
        "description": "知识学习、技能提升、教育辅导场景",
        "tone": "educational",
        "keywords": [
            "学习", "教程", "解释", "讲解", "教学", "课程",
            "知识", "考试", "复习", "原理", "概念",
        ],
        "mcp_tools": [],
        "actions": [],
        "skills": [],
    },
    "life": {
        "id": "life",
        "name": "生活助手",
        "icon": "🏠",
        "description": "日常生活、出行、美食、健康等生活场景",
        "tone": "warm",
        "keywords": [
            "菜谱", "食谱", "做饭", "美食", "旅游", "出行",
            "健康", "运动", "减肥", "养生", "生活",
        ],
        "mcp_tools": [],
        "actions": [],
        "skills": [],
    },
    "work_dev": {
        "id": "work_dev",
        "name": "工作开发",
        "icon": "💻",
        "description": "编程开发、代码编写、项目调试场景",
        "tone": "professional",
        "keywords": [
            "写代码", "开发", "编程", "写程序", "debug", "调试",
            "VS Code", "vscode", "编辑器", "项目", "工作", "开发模式",
        ],
        "mcp_tools": [
            {
                "name": "yunxi_vscode_launch",
                "params": {},
                "trigger": "on_enter",
                "required": False,
            },
            {
                "name": "yunxi_compute_schedule",
                "params": {"action": "query_available"},
                "trigger": "on_enter",
                "required": False,
            },
        ],
        "actions": [
            {
                "type": "launch_vscode",
                "params": {
                    "new_window": True,
                },
                "condition": "not_running",
                "once": False,
            },
            {
                "type": "open_project",
                "params": {
                    "project_path": "",
                },
                "condition": "has_project_path",
                "once": False,
            },
            {
                "type": "install_extension",
                "params": {
                    "extensions": [
                        "ms-python.python",
                        "dbaeumer.vscode-eslint",
                        "esbenp.prettier-vscode",
                    ],
                },
                "condition": "first_enter",
                "once": True,
            },
        ],
        "skills": [
            {
                "name": "vscode_control",
                "auto_trigger": ["on_enter"],
                "default_params": {
                    "action": "launch",
                },
                "required": False,
            },
            {
                "name": "file_operation",
                "auto_trigger": [],
                "default_params": {},
                "required": False,
            },
            {
                "name": "terminal_command",
                "auto_trigger": [],
                "default_params": {},
                "required": False,
            },
            {
                "name": "git_tools",
                "auto_trigger": [],
                "default_params": {},
                "required": False,
            },
        ],
    },
}


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
# Pydantic 请求模型
# ---------------------------------------------------------------------------

class SceneSwitchRequest(BaseModel):
    """场景切换请求体."""
    to_scene: str = Field(..., description="目标场景ID")
    from_scene: str = Field("", description="源场景ID（可选）")
    trigger_type: str = Field("manual", description="触发类型 manual/auto/recognize")
    user_id: str = Field("default", description="用户ID")
    reason: str = Field("", description="切换原因")


class SceneRecognizeRequest(BaseModel):
    """场景识别请求体."""
    text: str = Field(..., description="用户输入文本")
    context: dict[str, Any] = Field(default_factory=dict, description="上下文信息")
    user_id: str = Field("default", description="用户ID")
    include_all_scores: bool = Field(True, description="是否返回所有场景得分")


class SceneConfigUpdateRequest(BaseModel):
    """场景配置更新请求体."""
    config: dict[str, Any] = Field(..., description="配置更新字典")


class AdminConfigUpdateRequest(BaseModel):
    """全局配置更新请求体."""
    config: dict[str, Any] = Field(..., description="配置更新字典")


class McpToolConfig(BaseModel):
    """MCP 工具配置项."""
    name: str = Field(..., description="MCP 工具名称")
    params: dict[str, Any] = Field(default_factory=dict, description="默认参数")
    trigger: str = Field("manual", description="触发时机: on_enter / on_leave / manual")
    required: bool = Field(False, description="是否必填（失败是否阻塞场景切换）")


class McpToolCallRequest(BaseModel):
    """MCP 工具调用请求体."""
    arguments: dict[str, Any] = Field(default_factory=dict, description="工具调用参数")


class SceneMcpToolsUpdateRequest(BaseModel):
    """场景 MCP 工具绑定更新请求体."""
    mcp_tools: list[McpToolConfig] = Field(..., description="MCP 工具配置列表")


# ---------------------------------------------------------------------------
# 技能绑定模型
# ---------------------------------------------------------------------------

class SkillBindingConfig(BaseModel):
    """场景技能绑定配置项."""
    name: str = Field(..., description="技能名称")
    auto_trigger: list[str] = Field(
        default_factory=list,
        description="自动触发时机: on_enter / on_leave，空列表表示手动触发",
    )
    default_params: dict[str, Any] = Field(
        default_factory=dict,
        description="技能默认参数",
    )
    required: bool = Field(False, description="是否必填（失败是否阻塞场景切换）")


class SceneSkillsUpdateRequest(BaseModel):
    """场景技能绑定更新请求体."""
    skills: list[SkillBindingConfig] = Field(..., description="技能绑定配置列表")


class SkillExecuteRequest(BaseModel):
    """技能执行请求体."""
    params: dict[str, Any] = Field(default_factory=dict, description="技能执行参数")
    context: dict[str, Any] = Field(default_factory=dict, description="执行上下文")


# ---------------------------------------------------------------------------
# 通用响应工具
# ---------------------------------------------------------------------------

def make_response(
    data: Any = None,
    code: int = 0,
    message: str = "success",
) -> dict[str, Any]:
    """构造统一响应格式.

    Args:
        data: 响应数据
        code: 状态码（0 表示成功）
        message: 状态消息

    Returns:
        统一格式的响应字典
    """
    return {
        "code": code,
        "message": message,
        "data": data if data is not None else {},
    }
