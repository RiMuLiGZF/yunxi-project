"""
算力调度中台 - 算力源管理路由
前缀：/api/compute/sources
"""

import uuid
import time
from datetime import datetime
from typing import List, Optional, Dict, Any
from fastapi import APIRouter, Depends, Query, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ..schemas import ApiResponse
from ..auth import get_current_user, require_role, has_role
from ..models import get_db, ComputeSource, AuditLog
from ..crypto import encrypt, decrypt, mask_api_key

router = APIRouter()


# ============================================================
# 请求体模型
# ============================================================

class ComputeSourceCreate(BaseModel):
    """新增算力源请求体"""
    source_id: str = Field(..., description="算力源唯一标识")
    name: str = Field(..., description="显示名称")
    type: str = Field("cloud", description="类型：local/cloud/private")
    provider: str = Field("custom", description="服务商")
    base_url: str = Field(..., description="API 地址")
    api_key: Optional[str] = Field("", description="API Key（明文，后端加密存储）")
    status: str = Field("inactive", description="状态：active/inactive/error")
    priority: int = Field(100, description="优先级，数字越小越优先")
    weight: int = Field(100, description="负载权重")
    max_concurrent: int = Field(10, description="最大并发数")
    timeout: int = Field(60, description="超时时间秒")
    cost_per_1k_input: float = Field(0.0, description="每千输入 token 成本")
    cost_per_1k_output: float = Field(0.0, description="每千输出 token 成本")
    models: List[str] = Field(default_factory=list, description="支持的模型列表")
    capabilities: List[str] = Field(default_factory=list, description="能力标签")
    config: Dict[str, Any] = Field(default_factory=dict, description="扩展配置")


class ComputeSourceUpdate(BaseModel):
    """更新算力源请求体"""
    name: Optional[str] = Field(None, description="显示名称")
    type: Optional[str] = Field(None, description="类型")
    provider: Optional[str] = Field(None, description="服务商")
    base_url: Optional[str] = Field(None, description="API 地址")
    api_key: Optional[str] = Field(None, description="API Key（提供则更新）")
    status: Optional[str] = Field(None, description="状态")
    priority: Optional[int] = Field(None, description="优先级")
    weight: Optional[int] = Field(None, description="负载权重")
    max_concurrent: Optional[int] = Field(None, description="最大并发数")
    timeout: Optional[int] = Field(None, description="超时时间秒")
    cost_per_1k_input: Optional[float] = Field(None, description="每千输入 token 成本")
    cost_per_1k_output: Optional[float] = Field(None, description="每千输出 token 成本")
    models: Optional[List[str]] = Field(None, description="支持的模型列表")
    capabilities: Optional[List[str]] = Field(None, description="能力标签")
    config: Option