"""M9 Programming Dev - 数据模型"""

from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Any
from enum import Enum


class VSCodeStatus(str, Enum):
    """VSCode状态"""
    STOPPED = "stopped"
    STARTING = "starting"
    RUNNING = "running"
    ERROR = "error"


class VSCodeInstance(BaseModel):
    """VSCode实例信息"""
    id: str
    name: str
    status: VSCodeStatus
    port: Optional[int] = None
    workspace: Optional[str] = None
    pid: Optional[int] = None
    created_at: str


class CodeExecutionRequest(BaseModel):
    """代码执行请求"""
    language: str = Field(..., description="编程语言")
    code: str = Field(..., description="要执行的代码")
    timeout: int = Field(30, description="超时时间(秒)")
    args: Optional[List[str]] = None
    env: Optional[Dict[str, str]] = None


class CodeExecutionResult(BaseModel):
    """代码执行结果"""
    success: bool
    stdout: str = ""
    stderr: str = ""
    exit_code: Optional[int] = None
    execution_time: float = 0.0


class ProjectInfo(BaseModel):
    """项目信息"""
    id: str
    name: str
    path: str
    description: Optional[str] = None
    language: Optional[str] = None
    created_at: str
    updated_at: str
