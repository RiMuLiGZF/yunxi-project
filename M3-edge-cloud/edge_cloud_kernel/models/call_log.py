"""调用日志模型.

定义推理调用日志记录，用于审计和回溯分析。
"""

from __future__ import annotations

import time
from typing import Any

from pydantic import BaseModel, Field


class CallLogRecord(BaseModel):
    """推理调用日志记录.

    每次推理调用生成一条日志，异步回写到本地存储。

    Attributes:
        log_id: 日志唯一标识.
        task_id: 关联的任务 ID.
        agent_name: 调用方 Agent 名称.
        target: 路由目标（local/cloud/hybrid）.
        provider_name: 使用的 Provider 名称.
        model: 实际使用的模型名称.
        prompt_tokens: 输入 token 数.
        completion_tokens: 输出 token 数.
        latency_ms: 端到端延迟（毫秒）.
        status: 调用状态（success/failed/timeout）.
        error_message: 错误信息（失败时）.
        vram_usage_before: 调用前显存使用率.
        vram_usage_after: 调用后显存使用率.
        timestamp: 调用时间戳.
    """

    log_id: str = Field(default="", description="日志 ID")
    task_id: str = Field(default="", description="关联任务 ID")
    agent_name: str = Field(default="", description="调用方 Agent")
    target: str = Field(default="local", description="路由目标")
    provider_name: str = Field(default="", description="Provider 名称")
    model: str = Field(default="", description="模型名称")
    prompt_tokens: int = Field(default=0, ge=0, description="输入 token 数")
    completion_tokens: int = Field(default=0, ge=0, description="输出 token 数")
    latency_ms: float = Field(default=0.0, ge=0.0, description="延迟毫秒")
    status: str = Field(default="success", description="调用状态")
    error_message: str | None = Field(default=None, description="错误信息")
    vram_usage_before: float | None = Field(default=None, description="调用前显存率")
    vram_usage_after: float | None = Field(default=None, description="调用后显存率")
    timestamp: float = Field(default_factory=time.time, description="调用时间戳")
