"""
成长中心 - M5 代理路由
M8 作为代理，将成长相关请求转发到 M5 潮汐记忆的成长系统

说明：
- 原 growth.py 为 M8 本地实现，保留作为降级备用
- 本路由优先代理到 M5，M5 不可用时前端自动降级到 mock 数据
- 使用 httpx 直接发请求，不依赖 module_client（module_client 缺少 get_client 方法）
"""

import sys
from pathlib import Path
from typing import Optional, Dict, Any
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse
import json
import httpx

project_root = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(project_root))

from ..schemas import ApiResponse
from ..auth import get_current_user

router = APIRouter()

# M5 服务地址（从环境变量或默认值）
import os
M5_BASE_URL = os.getenv("M5_BASE_URL", "http://localhost:8005")
M5_ADMIN_TOKEN = os.getenv("M5_ADMIN_TOKEN", "yunxi-m5-admin-token-2026")

# HTTP 客户端
_client: Optional[httpx.AsyncClient] = None


def _get_client() -> httpx.AsyncClient:
    """获取 HTTP 客户端（懒加载）"""
    global _client
    if _client is None:
        _client = httpx.AsyncClient(
            base_url=M5_BASE_URL,
            timeout=30.0,
            headers={
                "Authorization": f"Bearer {M5_ADMIN_TOKEN}",
                "Content-Type": "application/json",
            },
        )
    return _client


async def _proxy(
    method: str,
    path: str,
    params: Optional[Dict] = None,
    json_data: Optional[Dict] = None,
) -> Any:
    """
    代理请求到 M5

    Args:
        method: HTTP 方法
        path: 路径（不含 /api/v1/growth 前缀）
        params: 查询参数
        json_data: 请求体

    Returns:
        M5 返回的 JSON 数据
    """
    client = _get_client()
    full_path = f"/api/v1/growth{path}"

    try:
        response = await client.request(
            method=method,
            url=full_path,
            params=params,
            json=json_data,
        )
        response.raise_for_status()
        result = response.json()
        # M5 可能返回 {code, data, message} 格式，也可能直接返回数据
        if isinstance(result, dict) and "data" in result:
            return result["data"]
        return result
    except httpx.HTTPStatusError as e:
        raise HTTPException(status_code=e.response.status_code, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"M5 代理失败: {str(e)}")


# ============================================================
# 成就勋章
# ============================================================

@router.get("/achievements")
async def get_achievements(
    category: Optional[str] = None,
    status: Optional[str] = None,
    current_user: dict = Depends(get_current_user)
):
    """获取成就列表"""
    try:
        params = {}
        if category:
            params["category"] = category
        if status:
            params["status"] = status
        result = await _proxy("GET", "/achievements", params=params if params else None)
        return ApiResponse.success(data=result)
    except HTTPException:
        raise
    except json.JSONDecodeError as e:
        return ApiResponse.error(message=f"获取成就列表失败: {str(e)}", code=502)


@router.get("/achievements/stats")
async def get_achievement_stats(current_user: dict = Depends(get_current_user)):
    """获取成就统计"""
    try:
        result = await _proxy("GET", "/achievements/stats")
        return ApiResponse.success(data=result)
    except HTTPException:
        raise
    except json.JSONDecodeError as e:
        return ApiResponse.error(message=f"获取成就统计失败: {str(e)}", code=502)


@router.post("/achievements/{achievement_id}/unlock")
async def unlock_achievement(
    achievement_id: str,
    current_user: dict = Depends(get_current_user)
):
    """解锁成就"""
    try:
        result = await _proxy("POST", f"/achievements/{achievement_id}/unlock")
        return ApiResponse.success(data=result)
    except HTTPException:
        raise
    except json.JSONDecodeError as e:
        return ApiResponse.error(message=f"解锁成就失败: {str(e)}", code=502)


# ============================================================
# 心智天赋树
# ============================================================

@router.get("/talents")
async def get_talent_tree(
    tree: Optional[str] = None,
    current_user: dict = Depends(get_current_user)
):
    """获取天赋树"""
    try:
        params = {"tree": tree} if tree else None
        result = await _proxy("GET", "/talents", params=params)
        return ApiResponse.success(data=result)
    except HTTPException:
        raise
    except json.JSONDecodeError as e:
        return ApiResponse.error(message=f"获取天赋树失败: {str(e)}", code=502)


@router.get("/talents/points")
async def get_talent_points(current_user: dict = Depends(get_current_user)):
    """获取可用天赋点"""
    try:
        result = await _proxy("GET", "/talents/points")
        return ApiResponse.success(data=result)
    except HTTPException:
        raise
    except json.JSONDecodeError as e:
        return ApiResponse.error(message=f"获取天赋点失败: {str(e)}", code=502)


@router.post("/talents/{node_id}/upgrade")
async def upgrade_talent(
    node_id: str,
    current_user: dict = Depends(get_current_user)
):
    """升级天赋节点"""
    try:
        result = await _proxy("POST", f"/talents/{node_id}/upgrade")
        return ApiResponse.success(data=result)
    except HTTPException:
        raise
    except json.JSONDecodeError as e:
        return ApiResponse.error(message=f"升级天赋失败: {str(e)}", code=502)


@router.post("/talents/reset")
async def reset_talents(current_user: dict = Depends(get_current_user)):
    """重置天赋树"""
    try:
        result = await _proxy("POST", "/talents/reset")
        return ApiResponse.success(data=result)
    except HTTPException:
        raise
    except json.JSONDecodeError as e:
        return ApiResponse.error(message=f"重置天赋失败: {str(e)}", code=502)


# ============================================================
# 潮汐历法
# ============================================================

@router.get("/calendar/{year}/{month}")
async def get_month_calendar(
    year: int,
    month: int,
    current_user: dict = Depends(get_current_user)
):
    """获取指定年月的日历数据"""
    try:
        result = await _proxy("GET", f"/calendar/{year}/{month}")
        return ApiResponse.success(data=result)
    except HTTPException:
        raise
    except json.JSONDecodeError as e:
        return ApiResponse.error(message=f"获取日历数据失败: {str(e)}", code=502)


@router.get("/calendar/stats")
async def get_calendar_stats(current_user: dict = Depends(get_current_user)):
    """获取日历统计"""
    try:
        result = await _proxy("GET", "/calendar/stats")
        return ApiResponse.success(data=result)
    except HTTPException:
        raise
    except json.JSONDecodeError as e:
        return ApiResponse.error(message=f"获取日历统计失败: {str(e)}", code=502)


@router.post("/calendar/checkin")
async def calendar_checkin(
    request: Request,
    current_user: dict = Depends(get_current_user)
):
    """打卡"""
    try:
        body = await request.json()
        result = await _proxy("POST", "/calendar/checkin", json_data=body)
        return ApiResponse.success(data=result)
    except HTTPException:
        raise
    except json.JSONDecodeError as e:
        return ApiResponse.error(message=f"打卡失败: {str(e)}", code=502)


# ============================================================
# 地球Online编年史
# ============================================================

@router.get("/chronicle")
async def get_chronicle_list(
    page: int = 1,
    size: int = 20,
    category: Optional[str] = None,
    year: Optional[int] = None,
    current_user: dict = Depends(get_current_user)
):
    """获取纪事列表"""
    try:
        params = {"page": page, "size": size}
        if category:
            params["category"] = category
        if year:
            params["year"] = year
        result = await _proxy("GET", "/chronicle", params=params)
        return ApiResponse.success(data=result)
    except HTTPException:
        raise
    except json.JSONDecodeError as e:
        return ApiResponse.error(message=f"获取纪事列表失败: {str(e)}", code=502)


@router.get("/chronicle/{item_id}")
async def get_chronicle_detail(
    item_id: str,
    current_user: dict = Depends(get_current_user)
):
    """获取纪事详情"""
    try:
        result = await _proxy("GET", f"/chronicle/{item_id}")
        return ApiResponse.success(data=result)
    except HTTPException:
        raise
    except json.JSONDecodeError as e:
        return ApiResponse.error(message=f"获取纪事详情失败: {str(e)}", code=502)


@router.post("/chronicle")
async def create_chronicle(
    request: Request,
    current_user: dict = Depends(get_current_user)
):
    """创建纪事"""
    try:
        body = await request.json()
        result = await _proxy("POST", "/chronicle", json_data=body)
        return ApiResponse.success(data=result)
    except HTTPException:
        raise
    except json.JSONDecodeError as e:
        return ApiResponse.error(message=f"创建纪事失败: {str(e)}", code=502)


@router.put("/chronicle/{item_id}")
async def update_chronicle(
    item_id: str,
    request: Request,
    current_user: dict = Depends(get_current_user)
):
    """更新纪事"""
    try:
        body = await request.json()
        result = await _proxy("PUT", f"/chronicle/{item_id}", json_data=body)
        return ApiResponse.success(data=result)
    except HTTPException:
        raise
    except json.JSONDecodeError as e:
        return ApiResponse.error(message=f"更新纪事失败: {str(e)}", code=502)


@router.delete("/chronicle/{item_id}")
async def delete_chronicle(
    item_id: str,
    current_user: dict = Depends(get_current_user)
):
    """删除纪事"""
    try:
        result = await _proxy("DELETE", f"/chronicle/{item_id}")
        return ApiResponse.success(data=result)
    except HTTPException:
        raise
    except json.JSONDecodeError as e:
        return ApiResponse.error(message=f"删除纪事失败: {str(e)}", code=502)


# ============================================================
# 记忆回响对比
# ============================================================

@router.get("/memories")
async def get_memory_echoes(
    page: int = 1,
    size: int = 20,
    category: Optional[str] = None,
    keyword: Optional[str] = None,
    current_user: dict = Depends(get_current_user)
):
    """获取记忆回响列表"""
    try:
        params = {"page": page, "size": size}
        if category:
            params["category"] = category
        if keyword:
            params["keyword"] = keyword
        result = await _proxy("GET", "/memories", params=params)
        return ApiResponse.success(data=result)
    except HTTPException:
        raise
    except json.JSONDecodeError as e:
        return ApiResponse.error(message=f"获取记忆回响失败: {str(e)}", code=502)


@router.get("/memories/{echo_id}")
async def get_memory_echo_detail(
    echo_id: str,
    current_user: dict = Depends(get_current_user)
):
    """获取记忆回响详情"""
    try:
        result = await _proxy("GET", f"/memories/{echo_id}")
        return ApiResponse.success(data=result)
    except HTTPException:
        raise
    except json.JSONDecodeError as e:
        return ApiResponse.error(message=f"获取记忆回响详情失败: {str(e)}", code=502)


@router.post("/memories/generate")
async def generate_memory_echo(
    request: Request,
    current_user: dict = Depends(get_current_user)
):
    """生成记忆回响"""
    try:
        body = await request.json()
        result = await _proxy("POST", "/memories/generate", json_data=body)
        return ApiResponse.success(data=result)
    except HTTPException:
        raise
    except json.JSONDecodeError as e:
        return ApiResponse.error(message=f"生成记忆回响失败: {str(e)}", code=502)


@router.delete("/memories/{echo_id}")
async def delete_memory_echo(
    echo_id: str,
    current_user: dict = Depends(get_current_user)
):
    """删除记忆回响"""
    try:
        result = await _proxy("DELETE", f"/memories/{echo_id}")
        return ApiResponse.success(data=result)
    except HTTPException:
        raise
    except json.JSONDecodeError as e:
        return ApiResponse.error(message=f"删除记忆回响失败: {str(e)}", code=502)


# ============================================================
# 赛季征程
# ============================================================

@router.get("/season/current")
async def get_current_season(current_user: dict = Depends(get_current_user)):
    """获取当前赛季"""
    try:
        result = await _proxy("GET", "/season/current")
        return ApiResponse.success(data=result)
    except HTTPException:
        raise
    except json.JSONDecodeError as e:
        return ApiResponse.error(message=f"获取当前赛季失败: {str(e)}", code=502)


@router.get("/season/history")
async def get_season_history(current_user: dict = Depends(get_current_user)):
    """获取历史赛季列表"""
    try:
        result = await _proxy("GET", "/season/history")
        return ApiResponse.success(data=result)
    except HTTPException:
        raise
    except json.JSONDecodeError as e:
        return ApiResponse.error(message=f"获取历史赛季失败: {str(e)}", code=502)


@router.get("/season/tasks")
async def get_season_tasks(
    type: Optional[str] = None,
    phase_id: Optional[str] = None,
    current_user: dict = Depends(get_current_user)
):
    """获取赛季任务列表"""
    try:
        params = {}
        if type:
            params["type"] = type
        if phase_id:
            params["phase_id"] = phase_id
        result = await _proxy("GET", "/season/tasks", params=params if params else None)
        return ApiResponse.success(data=result)
    except HTTPException:
        raise
    except json.JSONDecodeError as e:
        return ApiResponse.error(message=f"获取赛季任务失败: {str(e)}", code=502)


@router.post("/season/tasks/{task_id}/complete")
async def complete_season_task(
    task_id: str,
    current_user: dict = Depends(get_current_user)
):
    """完成赛季任务"""
    try:
        result = await _proxy("POST", f"/season/tasks/{task_id}/complete")
        return ApiResponse.success(data=result)
    except HTTPException:
        raise
    except json.JSONDecodeError as e:
        return ApiResponse.error(message=f"完成任务失败: {str(e)}", code=502)


@router.post("/season/tasks/{task_id}/claim")
async def claim_season_reward(
    task_id: str,
    current_user: dict = Depends(get_current_user)
):
    """领取赛季奖励"""
    try:
        result = await _proxy("POST", f"/season/tasks/{task_id}/claim")
        return ApiResponse.success(data=result)
    except HTTPException:
        raise
    except json.JSONDecodeError as e:
        return ApiResponse.error(message=f"领取奖励失败: {str(e)}", code=502)
