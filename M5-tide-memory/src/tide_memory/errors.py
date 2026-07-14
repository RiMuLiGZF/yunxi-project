"""
向后兼容模块

错误码定义已迁移至 tide_memory.common.errors
此文件提供向后兼容的导入路径
"""

from tide_memory.common.errors import (  # noqa: F401
    ErrorCode,
    TideMemoryError,
    MemoryNotFoundError,
    DomainPermissionError,
    InvalidMemoryError,
    ConsolidationError,
    VectorSearchError,
    error_response,
    success_response,
)
