"""M9 代码执行接口"""

from fastapi import APIRouter, HTTPException
from ..models import CodeExecutionRequest, CodeExecutionResult
from ..code_executor import code_executor

router = APIRouter()


@router.post("/execute", response_model=CodeExecutionResult)
async def execute_code(request: CodeExecutionRequest) -> CodeExecutionResult:
    """执行代码"""
    try:
        result = code_executor.execute(request)
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail="代码执行内部错误") from None


@router.get("/languages")
async def list_supported_languages() -> dict:
    """列出支持的编程语言"""
    return {
        "supported_languages": list(code_executor.LANGUAGE_COMMANDS.keys()),
        "all_languages": list(code_executor.LANGUAGE_EXTENSIONS.keys())
    }
