"""M11 MCP Bus - 监控统计 API 路由.

提供总览统计、服务器/工具调用统计、最近调用记录、
健康状态等监控相关的 REST API 接口。
"""

from __future__ import annotations

import asyncio
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import func

from ..db import get_session
from ..models_db import McpCall, McpServer, McpTool
from ..services.health_checker import mcp_health_checker
from ..services.monitor import mcp_monitor
from ..services.registry import mcp_registry

router = APIRouter(prefix="/api/v1/monitor", tags=["monitor"])


# ============================================================
# 总览统计
# ============================================================

@router.get("/overview", summary="总览统计")
async def get_overview() -> Dict[str, Any]:
    """获取监控总览统计信息.

    返回总调用数、成功率、平均响应时间、服务器数、工具数等核心指标。
    """
    # 调用统计
    stats = mcp_monitor.get_stats()

    # 服务器和工具数量
    db = get_session()
    try:
        total_servers = db.query(McpServer).count()
        online_servers = db.query(McpServer).filter(McpServer.status == "online").count()
        total_tools = db.query(McpTool).count()
    finally:
        db.close()

    # 健康检查状态
    health_summary = mcp_health_checker.get_health_summary()

    return {
        "total_calls": stats["total_calls"],
        "success_calls": stats["success_calls"],
        "failed_calls": stats["failed_calls"],
        "success_rate": stats["success_rate"],
        "avg_duration_ms": stats["avg_duration_ms"],
        "total_servers": total_servers,
        "online_servers": online_servers,
        "offline_servers": total_servers - online_servers,
        "total_tools": total_tools,
        "tracked_tools": stats["tracked_tools"],
        "health_check_running": mcp_health_checker.is_running,
        "health_summary": health_summary,
    }


# ============================================================
# 服务器调用统计
# ============================================================

@router.get("/server-stats", summary="各服务器调用统计")
async def get_server_stats(
    limit: int = Query(20, ge=1, le=100, description="返回数量"),
) -> Dict[str, Any]:
    """获取各服务器的调用统计.

    按调用次数降序排列，返回每台服务器的调用数、成功率、平均耗时等。
    """
    db = get_session()
    try:
        # 从数据库按服务器分组统计
        results = (
            db.query(
                McpCall.server_id,
                func.count(McpCall.id).label("total_calls"),
                func.sum(McpCall.status == "success").label("success_calls"),
                func.avg(McpCall.duration_ms).label("avg_duration"),
            )
            .filter(McpCall.server_id.isnot(None))
            .group_by(McpCall.server_id)
            .order_by(func.count(McpCall.id).desc())
            .limit(limit)
            .all()
        )

        items = []
        for row in results:
            server = mcp_registry.get_server(row.server_id)
            total = row.total_calls or 0
            success = row.success_calls or 0
            items.append({
                "server_id": row.server_id,
                "server_name": server.name if server else f"server_{row.server_id}",
                "total_calls": total,
                "success_calls": success,
                "failed_calls": total - success,
                "success_rate": round(success / total * 100, 2) if total > 0 else 0.0,
                "avg_duration_ms": round(row.avg_duration or 0, 2),
                "status": server.status if server else "unknown",
            })

        # 补充没有调用记录的服务器
        if len(items) < limit:
            all_servers = mcp_registry.list_servers()
            existing_ids = {item["server_id"] for item in items}
            for server in all_servers:
                if server.id not in existing_ids and len(items) < limit:
                    items.append({
                        "server_id": server.id,
                        "server_name": server.name,
                        "total_calls": 0,
                        "success_calls": 0,
                        "failed_calls": 0,
                        "success_rate": 0.0,
                        "avg_duration_ms": 0.0,
                        "status": server.status,
                    })

        return {
            "total": len(items),
            "items": items,
        }
    finally:
        db.close()


# ============================================================
# 工具调用统计
# ============================================================

@router.get("/tool-stats", summary="各工具调用统计 Top 20")
async def get_tool_stats(
    limit: int = Query(20, ge=1, le=100, description="返回数量"),
) -> Dict[str, Any]:
    """获取各工具的调用统计 Top N.

    按调用次数降序排列，返回每个工具的调用数、成功率、平均耗时等。
    """
    stats = mcp_monitor.get_stats()
    popular_tools = stats.get("popular_tools", [])

    # 如果内存中的数据不够，从数据库补充
    if len(popular_tools) < limit:
        db = get_session()
        try:
            results = (
                db.query(
                    McpCall.tool_name,
                    func.count(McpCall.id).label("total_calls"),
                    func.sum(McpCall.status == "success").label("success_calls"),
                    func.avg(McpCall.duration_ms).label("avg_duration"),
                )
                .group_by(McpCall.tool_name)
                .order_by(func.count(McpCall.id).desc())
                .limit(limit)
                .all()
            )

            db_tools = []
            for row in results:
                total = row.total_calls or 0
                success = row.success_calls or 0
                db_tools.append({
                    "name": row.tool_name,
                    "count": total,
                    "success": success,
                    "failed": total - success,
                    "avg_duration_ms": round(row.avg_duration or 0, 2),
                })

            # 合并内存和数据库数据，以数据库为准（更全面）
            if db_tools:
                popular_tools = db_tools
        finally:
            db.close()

    # 限制返回数量
    items = popular_tools[:limit]

    return {
        "total": len(items),
        "items": items,
    }


# ============================================================
# 最近调用记录
# ============================================================

@router.get("/recent-calls", summary="最近调用记录")
async def get_recent_calls(
    limit: int = Query(50, ge=1, le=200, description="返回数量"),
) -> Dict[str, Any]:
    """获取最近的调用记录.

    优先从内存环形缓冲区读取，响应速度快。
    支持 limit 参数控制返回数量。
    """
    calls = mcp_monitor.get_recent_calls(limit=limit)

    return {
        "total": len(calls),
        "items": calls,
    }


# ============================================================
# 健康状态
# ============================================================

@router.get("/health-status", summary="所有服务器健康状态")
async def get_health_status() -> Dict[str, Any]:
    """获取所有服务器的健康检查状态.

    返回健康检查汇总和各服务器的详细健康状态。
    """
    summary = mcp_health_checker.get_health_summary()
    health_list = mcp_health_checker.get_all_health()

    # 如果健康检查缓存为空，返回数据库中的服务器状态作为兜底
    if not health_list:
        servers = mcp_registry.list_servers()
        health_list = []
        for server in servers:
            health_list.append({
                "server_id": server.id,
                "server_name": server.name,
                "status": server.status,
                "latency_ms": 0,
                "last_check": server.last_heartbeat.isoformat() if server.last_heartbeat else None,
                "consecutive_failures": 0,
            })

    return {
        "summary": summary,
        "servers": health_list,
    }


@router.post("/health-check/{server_id}", summary="手动触发健康检查")
async def trigger_health_check(server_id: int) -> Dict[str, Any]:
    """手动触发单个服务器的健康检查.

    Args:
        server_id: 服务器 ID

    Returns:
        健康检查结果
    """
    # 验证服务器是否存在
    server = mcp_registry.get_server(server_id)
    if not server:
        raise HTTPException(status_code=404, detail=f"服务器不存在: {server_id}")

    # 获取健康检查器的事件循环，如果后台线程在运行则使用它
    if mcp_health_checker._loop and mcp_health_checker._loop.is_running():
        # 在后台事件循环中执行检查
        future = asyncio.run_coroutine_threadsafe(
            mcp_health_checker.check_server(server_id),
            mcp_health_checker._loop,
        )
        try:
            result = future.result(timeout=10)
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"健康检查执行失败: {e}")
    else:
        # 没有后台线程，在当前线程中同步执行
        try:
            result = await mcp_health_checker.check_server(server_id)
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"健康检查执行失败: {e}")

    return {
        "message": "健康检查完成",
        "result": result,
    }


@router.post("/health-check-all", summary="手动触发全部健康检查")
async def trigger_health_check_all() -> Dict[str, Any]:
    """手动触发所有服务器的健康检查.

    Returns:
        健康检查统计结果
    """
    if mcp_health_checker._loop and mcp_health_checker._loop.is_running():
        future = asyncio.run_coroutine_threadsafe(
            mcp_health_checker.check_all(),
            mcp_health_checker._loop,
        )
        try:
            result = future.result(timeout=30)
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"健康检查执行失败: {e}")
    else:
        try:
            result = await mcp_health_checker.check_all()
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"健康检查执行失败: {e}")

    return {
        "message": "全部健康检查完成",
        "result": result,
    }
