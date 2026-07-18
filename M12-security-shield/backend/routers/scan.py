"""
云汐 M12 安全盾 - 漏洞扫描器 API
提供静态扫描、依赖扫描、动态扫描、配置扫描等接口
"""

from fastapi import APIRouter, Query, Depends
from typing import Optional, List, Dict, Any
from pydantic import BaseModel, Field

# 兼容相对导入和直接运行
try:
    from ..schemas.common import make_response, make_error_response
    from ..services.vulnerability_scanner import get_vulnerability_scanner
    from ..auth import require_role, ROLE_ADMIN, ROLE_VIEWER
except ImportError:
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from schemas.common import make_response, make_error_response
    from services.vulnerability_scanner import get_vulnerability_scanner
    from auth import require_role, ROLE_ADMIN, ROLE_VIEWER

router = APIRouter(prefix="/api/m12/scan", tags=["M12-漏洞扫描"])


# ===========================================================================
# 请求/响应模型
# ===========================================================================

class StaticScanRequest(BaseModel):
    """静态扫描请求"""
    target_path: str = Field(..., description="扫描目标路径（目录或文件）")
    file_patterns: Optional[List[str]] = Field(default=None, description="文件模式列表")


class DependencyScanRequest(BaseModel):
    """依赖扫描请求"""
    project_path: str = Field(..., description="项目根目录路径（包含 requirements.txt 或 package.json）")


class DynamicScanRequest(BaseModel):
    """动态扫描请求"""
    base_url: str = Field(..., description="API 基础 URL")
    endpoints: List[Dict[str, Any]] = Field(..., description="端点列表")
    auth_token: Optional[str] = Field(default=None, description="认证 Token")


class ConfigScanRequest(BaseModel):
    """配置扫描请求"""
    config_data: Optional[Dict[str, Any]] = Field(default=None, description="配置数据")
    headers: Optional[Dict[str, str]] = Field(default=None, description="HTTP 响应头")


# ===========================================================================
# 静态扫描
# ===========================================================================

@router.post("/static", summary="静态代码扫描")
def scan_static(
    request: StaticScanRequest,
    current_user: dict = Depends(require_role(ROLE_ADMIN)),
):
    """
    执行静态代码扫描，检测代码中的安全漏洞：
    - 危险函数（eval/exec/os.system 等）
    - SQL 注入漏洞（字符串拼接 SQL）
    - XSS 漏洞（未转义输出）
    - 路径遍历漏洞
    - 硬编码密钥/密码
    - 不安全的随机数
    - 弱加密算法
    """
    try:
        scanner = get_vulnerability_scanner()
        result = scanner.scan_static(
            target_path=request.target_path,
            file_patterns=request.file_patterns,
        )
        return make_response(data=result.to_dict())
    except Exception as e:
        return make_error_response(f"静态扫描失败: {str(e)}")


# ===========================================================================
# 依赖扫描
# ===========================================================================

@router.post("/dependency", summary="依赖漏洞扫描")
def scan_dependency(
    request: DependencyScanRequest,
    current_user: dict = Depends(require_role(ROLE_ADMIN)),
):
    """
    扫描依赖包的已知漏洞：
    - 解析 requirements.txt / package.json
    - 检查已知漏洞版本
    - 版本比较和风险评估
    """
    try:
        scanner = get_vulnerability_scanner()
        result = scanner.scan_dependencies(
            project_path=request.project_path,
        )
        return make_response(data=result.to_dict())
    except Exception as e:
        return make_error_response(f"依赖扫描失败: {str(e)}")


# ===========================================================================
# 动态扫描
# ===========================================================================

@router.post("/dynamic", summary="动态 API 安全扫描")
def scan_dynamic(
    request: DynamicScanRequest,
    current_user: dict = Depends(require_role(ROLE_ADMIN)),
):
    """
    执行 API 动态安全测试：
    - 未认证访问测试
    - 越权访问测试
    - 输入验证测试
    - 错误信息泄露测试
    """
    try:
        scanner = get_vulnerability_scanner()
        result = scanner.scan_dynamic(
            base_url=request.base_url,
            endpoints=request.endpoints,
            auth_token=request.auth_token,
        )
        return make_response(data=result.to_dict())
    except Exception as e:
        return make_error_response(f"动态扫描失败: {str(e)}")


# ===========================================================================
# 配置扫描
# ===========================================================================

@router.post("/config", summary="安全配置扫描")
def scan_config(
    request: ConfigScanRequest,
    current_user: dict = Depends(require_role(ROLE_ADMIN)),
):
    """
    检查安全配置：
    - CORS 配置检查
    - 安全头检查
    - HTTPS 强制检查
    - Cookie 安全标志检查
    """
    try:
        scanner = get_vulnerability_scanner()
        result = scanner.scan_config(
            config_data=request.config_data or {},
            headers=request.headers or {},
        )
        return make_response(data=result.to_dict())
    except Exception as e:
        return make_error_response(f"配置扫描失败: {str(e)}")


# ===========================================================================
# 扫描历史
# ===========================================================================

@router.get("/history", summary="扫描历史记录")
def scan_history(
    scan_type: Optional[str] = Query(None, description="扫描类型：static/dependency/dynamic/config"),
    page: int = Query(1, ge=1, description="页码"),
    page_size: int = Query(20, ge=1, le=100, description="每页数量"),
    current_user: dict = Depends(require_role(ROLE_VIEWER)),
):
    """
    获取历史扫描记录列表
    """
    try:
        scanner = get_vulnerability_scanner()
        history = scanner.get_scan_history(scan_type=scan_type)
        total = len(history)
        start = (page - 1) * page_size
        end = start + page_size
        items = [h.to_dict() for h in history[start:end]]
        return make_response(data={
            "items": items,
            "total": total,
            "page": page,
            "page_size": page_size,
            "total_pages": (total + page_size - 1) // page_size if page_size > 0 else 0,
        })
    except Exception as e:
        return make_error_response(f"获取扫描历史失败: {str(e)}")


@router.get("/{scan_id}", summary="扫描详情")
def scan_detail(
    scan_id: str,
    current_user: dict = Depends(require_role(ROLE_VIEWER)),
):
    """
    获取单次扫描的详细结果
    """
    try:
        scanner = get_vulnerability_scanner()
        result = scanner.get_scan_by_id(scan_id)
        if result is None:
            return make_error_response(f"扫描记录不存在: {scan_id}", code=404)
        return make_response(data=result.to_dict())
    except Exception as e:
        return make_error_response(f"获取扫描详情失败: {str(e)}")


# ===========================================================================
# 扫描统计
# ===========================================================================

@router.get("/stats/summary", summary="扫描统计概览")
def scan_stats_summary(
    current_user: dict = Depends(require_role(ROLE_VIEWER)),
):
    """
    获取扫描统计概览数据：
    - 总扫描次数
    - 各严重级别漏洞数量
    - 趋势统计
    """
    try:
        scanner = get_vulnerability_scanner()
        stats = scanner.get_scan_stats()
        return make_response(data=stats)
    except Exception as e:
        return make_error_response(f"获取扫描统计失败: {str(e)}")
