"""
审计日志路由
"""

import sys
import json
from pathlib import Path
from datetime import datetime
from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from typing import Optional
import io

project_root = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(project_root))

from ..schemas import ApiResponse
from ..auth import get_current_user, has_role
from ..audit import query_audit_logs, export_audit_logs_csv

router = APIRouter()


@router.get("/logs")
async def get_audit_logs(
    username: Optional[str] = Query(None, description="按用户名筛选"),
    action: Optional[str] = Query(None, description="按操作类型筛选"),
    module: Optional[str] = Query(None, description="按模块筛选"),
    result: Optional[str] = Query(None, description="按结果筛选"),
    start_time: Optional[str] = Query(None, description="开始时间 YYYY-MM-DD HH:MM:SS"),
    end_time: Optional[str] = Query(None, description="结束时间 YYYY-MM-DD HH:MM:SS"),
    page: int = Query(1, ge=1, description="页码"),
    page_size: int = Query(20, ge=1, le=100, description="�