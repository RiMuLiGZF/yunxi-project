"""
云汐内核 V10.0 — 枚举与常量定义

所有枚举类，包括 Agent 角色、安全分级、生命周期状态、
调度决策、仲裁级别、分身类型、M4 执行模式、用户场景、
调度策略、外部 Agent 类型、隐私等级、连接类型、许可证类型等。
"""

from __future__ import annotations

from enum import Enum, IntEnum


class AgentRole(str, Enum):
    """Agent角色模型（吸收CrewAI角色隔离）"""
    SUPERVISOR = "supervisor"    # 总管：编排全局任务
    EXECUTOR = "executor"        # 执行：承接子任务
    REVIEWER = "reviewer"        # 审查：审查执行结果
    EXTERNAL = "external"        # 外部：对接外部系统


class SecurityClassification(IntEnum):
    """涉密四级分级（吸收安全审计要求）"""
    PUBLIC = 0       # 公开
    INTERNAL = 1     # 内部
    CONFIDENTIAL = 2 # 机密
    TOP_SECRET = 3  # 绝密


class AgentLifeState(str, Enum):
    """Agent全生命周期状态（吸收LangGraph显式状态机）"""
    CREATED = "created"
    ACTIVATING = "activating"
    ACTIVE = "active"
    SUSPENDED = "suspended"
    DRAINING = "draining"       # 优雅终止中
    TERMINATED = "terminated"
    ARCHIVED = "archived"
    FAILED = "failed"


class SchedulingDecision(str, Enum):
    """端云调度决策"""
    LOCAL_FIRST = "local_first"
    AUTO = "auto"
    CLOUD_FIRST = "cloud_first"


class ArbitrationLevel(IntEnum):
    """三级仲裁（吸收AutoGen多Agent仲裁）"""
    AUTO_RESOLVE = 1   # 自动解决
    NEGOTIATE = 2       # 协商解决
    HUMAN_ESCALATE = 3  # 人工介入


class CloneType(str, Enum):
    """分身类型（吸收Claude Code委派分身）"""
    SCOUT = "scout"           # 勘探分身
    PLANNER = "planner"       # 规划分身
    WRITER = "writer"         # 撰写分身
    REVIEWER = "reviewer"     # 审查分身


class M4ExecutionMode(str, Enum):
    """M4 六大底层执行模式（全局标准命名）

    决定「做什么类型的事」，与 M1 调度策略（STRAT-A~F）属于不同层级。
    """
    DOCUMENT = "DOCUMENT"       # 文档写作/处理
    CODING = "CODING"           # 代码开发/评审
    REVIEW = "REVIEW"           # 评审/复盘
    DESIGN = "DESIGN"           # 设计/规划
    MENTAL = "MENTAL"           # 情绪陪伴/心理支持
    PLANNING = "PLANNING"       # 计划/任务管理


class UserScene(str, Enum):
    """上层用户可见场景（六场景）

    用户视角的场景分类，基于 M4 底层模式叠加业务语义。
    """
    WORK_DEV = "work_dev"               # 工作开发
    STUDY_PLAN = "study_plan"           # 学业规划
    REVIEW_SUMMARY = "review_summary"   # 复盘总结
    RELATIONSHIP = "relationship"       # 人际关系
    EMOTION_COMPANION = "emotion_companion"  # 情绪陪伴
    LIFE_MANAGEMENT = "life_management"     # 生活综合管理


class SchedulingStrategy(str, Enum):
    """M1 调度策略（STRAT-A~F）

    决定「用什么方式组队执行」，与 M4 底层模式正交。
    """
    STRAT_A = "STRAT_A"  # 简单任务直调
    STRAT_B = "STRAT_B"  # 复杂任务DAG编排
    STRAT_C = "STRAT_C"  # 端云协同计算
    STRAT_D = "STRAT_D"  # 涉密内容处理
    STRAT_E = "STRAT_E"  # 多Agent冲突仲裁
    STRAT_F = "STRAT_F"  # 断点续跑恢复


class ExternalAgentType(str, Enum):
    """外部 Agent 类型"""
    LLM = "llm"              # 通用大模型
    CODE = "code"            # 代码专用
    DESIGN = "design"        # 设计/创意
    SEARCH = "search"        # 搜索/研究
    TOOL = "tool"            # 工具调用
    CUSTOM = "custom"        # 自定义


class AgentPrivacyLevel(str, Enum):
    """外部 Agent 隐私等级"""
    STANDARD = "standard"    # 标准（数据可能经过服务商）
    ENHANCED = "enhanced"    # 增强（企业级隐私协议）
    LOCAL_ONLY = "local_only"  # 本地（数据不出境）


class ConnectionType(str, Enum):
    """连接类型"""
    API_KEY = "api_key"
    OAUTH = "oauth"
    LOCAL = "local"


class LicenseType(str, Enum):
    """Agent 许可证类型"""
    MIT = "MIT"                   # MIT 宽松协议
    APACHE = "Apache-2.0"         # Apache 2.0
    BSD = "BSD-3-Clause"          # BSD 3-Clause
    GPL_2 = "GPL-2.0"             # GPL v2（传染性）
    GPL_3 = "GPL-3.0"             # GPL v3（传染性）
    AGPL = "AGPL"                 # AGPL（强传染性）
    LGPL = "LGPL"                 # LGPL（弱传染性）
    PROPRIETARY = "Proprietary"   # 商业/专有
    OTHER = "Other"               # 其他


class UserPreferenceMode(str, Enum):
    """用户联邦调度偏好模式"""
    QUALITY_FIRST = "quality_first"    # 质量优先
    BALANCED = "balanced"              # 平衡模式
    COST_FIRST = "cost_first"          # 成本优先
    SPEED_FIRST = "speed_first"        # 速度优先


class ComparisonOutputMode(str, Enum):
    """多 Agent 对比输出模式"""
    BEST_ONLY = "best_only"      # 单优模式
    FUSION = "fusion"            # 融合模式
    SIDE_BY_SIDE = "side_by_side"  # 对比模式


# ══════════════════════════════════════════════════════════
# 命名映射表：底层模式 ↔ 上层场景 ↔ 调度策略
# ══════════════════════════════════════════════════════════

# M4 底层模式 → 上层用户场景（一对多，主映射为一对一）
MODE_TO_SCENE_PRIMARY: dict[M4ExecutionMode, UserScene] = {
    M4ExecutionMode.CODING: UserScene.WORK_DEV,
    M4ExecutionMode.DOCUMENT: UserScene.STUDY_PLAN,
    M4ExecutionMode.REVIEW: UserScene.REVIEW_SUMMARY,
    M4ExecutionMode.DESIGN: UserScene.RELATIONSHIP,
    M4ExecutionMode.MENTAL: UserScene.EMOTION_COMPANION,
    M4ExecutionMode.PLANNING: UserScene.LIFE_MANAGEMENT,
}

# 上层用户场景 → M4 底层模式（反向映射）
SCENE_TO_MODE: dict[UserScene, M4ExecutionMode] = {
    UserScene.WORK_DEV: M4ExecutionMode.CODING,
    UserScene.STUDY_PLAN: M4ExecutionMode.DOCUMENT,
    UserScene.REVIEW_SUMMARY: M4ExecutionMode.REVIEW,
    UserScene.RELATIONSHIP: M4ExecutionMode.DESIGN,
    UserScene.EMOTION_COMPANION: M4ExecutionMode.MENTAL,
    UserScene.LIFE_MANAGEMENT: M4ExecutionMode.PLANNING,
}

# 场景中文名称映射
SCENE_NAMES_ZH: dict[UserScene, str] = {
    UserScene.WORK_DEV: "工作开发",
    UserScene.STUDY_PLAN: "学业规划",
    UserScene.REVIEW_SUMMARY: "复盘总结",
    UserScene.RELATIONSHIP: "人际关系",
    UserScene.EMOTION_COMPANION: "情绪陪伴",
    UserScene.LIFE_MANAGEMENT: "生活综合管理",
}

# M4 模式中文名称映射
MODE_NAMES_ZH: dict[M4ExecutionMode, str] = {
    M4ExecutionMode.CODING: "代码开发",
    M4ExecutionMode.DOCUMENT: "文档写作",
    M4ExecutionMode.REVIEW: "评审复盘",
    M4ExecutionMode.DESIGN: "设计规划",
    M4ExecutionMode.MENTAL: "情绪支持",
    M4ExecutionMode.PLANNING: "计划管理",
}