"""M2 技能集群 - 安全领域模型.

包含沙箱配置、权限规则、权限矩阵等安全相关的数据模型。
"""

from __future__ import annotations

from pydantic import ConfigDict, Field

from skill_cluster.models.base import M2BaseModel


# ---- 沙箱相关 ----

class SandboxConfig(M2BaseModel):
    """沙箱执行配置."""

    timeout_seconds: int = Field(default=30, description="执行超时（秒）")
    max_memory_mb: int = Field(default=256, description="内存限制（MB）")
    max_cpu_time_seconds: int = Field(default=10, description="CPU 时间限制（秒）")
    allowed_modules: list[str] | None = Field(
        default=None, description="允许导入的模块白名单（None 表示不限制）"
    )
    blocked_modules: list[str] = Field(
        default_factory=lambda: [
            "os",
            "subprocess",
            "sys",
            "socket",
            "urllib",
            "http",
            "ftplib",
            "pathlib",
        ],
        description="禁止导入的模块黑名单",
    )
    allow_file_write: bool = Field(default=False, description="是否允许文件写入")
    allow_network: bool = Field(default=False, description="是否允许网络访问")
    working_dir: str | None = Field(default=None, description="工作目录")


# ---- 权限相关 ----

class PermissionRule(M2BaseModel):
    """细粒度权限规则.

    支持 agent_id + skill_id + action + params_pattern 四元组控制。
    """

    agent_id: str = Field(default="*", description="Agent ID，* 表示通配")
    skill_id: str = Field(default="*", description="技能 ID，* 表示通配")
    action: str = Field(default="*", description="动作标识，* 表示通配")
    params_pattern: str | None = Field(
        default=None,
        description="参数模式（Python fnmatch 风格），None 表示不限制",
    )
    level: str = Field(default="none", description="权限级别")


class PermissionMatrix(M2BaseModel):
    """权限矩阵.

    基础 ACL: agent_id -> skill_id -> level.
    细粒度规则: 按 (agent_id, skill_id, action, params_pattern) 匹配。
    规则匹配优先级：精确匹配 > 部分通配 > 全通配。
    """

    model_config = ConfigDict(arbitrary_types_allowed=True)

    rules: list[PermissionRule] = Field(
        default_factory=list, description="细粒度权限规则列表"
    )
