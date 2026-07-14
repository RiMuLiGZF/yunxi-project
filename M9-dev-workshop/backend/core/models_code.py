"""
云汐 M9 开发者工坊 - 代码执行相关数据模型
"""

from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Any


class CodeExecutionRequest(BaseModel):
    """代码执行请求"""
    language: str = Field(..., min_length=1, max_length=50, description="编程语言")
    code: str = Field(..., min_length=1, max_length=102400, description="要执行的代码")
    timeout: int = Field(30, ge=1, le=300, description="超时时间(秒)")
    args: Optional[List[str]] = None
    env: Optional[Dict[str, str]] = None


class CodeExecutionResult(BaseModel):
    """代码执行结果"""
    success: bool
    stdout: str = ""
    stderr: str = ""
    exit_code: Optional[int] = None
    execution_time: float = 0.0
