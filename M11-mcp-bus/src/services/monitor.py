"""M11 MCP Bus - 监控统计服务.

记录工具调用、统计指标、服务器健康状态等监控信息。
使用数据库持久化 + 内存计数的混合模式。
"""

from __future__ import annotations

import json
import time
from collections import defaultdict
from datetime import datetime, timedelta
from threading import Lock
from typing import Any, Dict, List, Optional

from sqlalchemy import func

from ..db import get_session
from ..models_db import McpCall, McpServer, McpTool


class McpMonitor:
    """MCP 监控统计服务.

    负责记录调用日志、统计指标、服务器健康状态等。
    使用内存计数器 + 数据库持久化的混合模式，
    高频计数在内存中累加，定期写入数据库。
    """

    def __init__(self) -> None:
        """初始化监控服务."""
        # 内存计数器（启动以来的累计值）
        self._total_calls = 0
        self._success_calls = 0
        self._failed_calls = 0
        self._total_duration_ms = 0

        # 按工具统计
        self._tool_stats: Dict[str, Dict[str, Any]] = defaultdict(
            lambda: {"count": 0, "success": 0, "failed": 0, "total_duration": 0}
        )

        # 最近调用记录（内存环形缓冲区）
        self._recent_calls: List[Dict[str, Any]] = []
        self._recent_calls_max = 200

        # 锁
        self._lock = Lock()

    # --------------------------------------------------------
    # 调用记录
    # --------------------------------------------------------

    def record_call(
        self,
        tool_name: str,
        status: str,
        duration_ms: int,
        error: Optional[str] = None,
        server_id: Optional[int] = None,
        consumer: str = "",
        request_snippet: str = "",
        response_snippet: str = "",
    ) -> int:
        """记录一次工具调用.

        同时更新内存计数器并写入数据库。

        Args:
            tool_name: 工具名称
            status: 调用状态：success/failed
            duration_ms: 耗时（毫秒）
            error: 错误信息（失败时）
            server_id: 目标服务器 ID
            consumer: 调用方标识
            request_snippet: 请求摘要
            response_snippet: 响应摘要

        Returns:
            调用记录 ID
        """
        # 更新内存统计
        with self._lock:
            self._total_calls += 1
            self._total_duration_ms += duration_ms

            if status == "success":
                self._success_calls += 1
            else:
                self._failed_calls += 1

            tool_stat = self._tool_stats[tool_name]
            tool_stat["count"] += 1
            tool_stat["total_duration"] += duration_ms
            if status == "success":
                tool_stat["success"] += 1
            else:
                tool_stat["failed"] += 1

            # 添加到最近调用列表
            call_record = {
                "tool_name": tool_name,
                "status": status,
                "duration_ms": duration_ms,
                "error": error or "",
                "server_id": server_id,
                "consumer": consumer,
                "created_at": datetime.utcnow().isoformat(),
            }
            self._recent_calls.insert(0, call_record)
            if len(self._recent_calls) > self._recent_calls_max:
                self._recent_calls.pop()

        # 写入数据库
        db = get_session()
        try:
            call = McpCall(
                tool_name=tool_name,
                server_id=server_id,
                consumer=consumer,
                status=status,
                duration_ms=duration_ms,
                error_message=error or "",
                request_snippet=request_snippet[:500] if request_snippet else "",
                response_snippet=response_snippet[:1000] if response_snippet else "",
                created_at=datetime.utcnow(),
            )
            db.add(call)
            db.commit()
            db.refresh(call)
            return call.id
        finally:
            db.close()

    # --------------------------------------------------------
    # 统计数据
    # --------------------------------------------------------

    def get_stats(self) -> Dict[str, Any]:
        """获取整体统计数据.

        Returns:
            统计信息字典
        """
        with self._lock:
            total = self._total_calls
            success = self._success_calls
            avg_duration = (
                self._total_duration_ms / total if total > 0 else 0.0
            )
            success_rate = (success / total * 100) if total > 0 else 0.0

            # 热门工具 Top 10
            sorted_tools = sorted(
                self._tool_stats.items(),
                key=lambda x: x[1]["count"],
                reverse=True,
            )[:10]

            popular_tools = []
            for name, stat in sorted_tools:
                tool_avg = stat["total_duration"] / stat["count"] if stat["count"] > 0 else 0
                popular_tools.append({
                    "name": name,
                    "count": stat["count"],
                    "success": stat["success"],
                    "failed": stat["failed"],
                    "avg_duration_ms": round(tool_avg, 2),
                })

        return {
            "total_calls": total,
            "success_calls": success,
            "failed_calls": self._failed_calls,
            "success_rate": round(success_rate, 2),
            "avg_duration_ms": round(avg_duration, 2),
            "popular_tools": popular_tools,
            "tracked_tools": len(self._tool_stats),
        }

    def get_server_health(self) -> Dict[str, Any]:
        """获取服务器健康状态.

        Returns:
            服务器健康状态统计
        """
        db = get_session()
        try:
            total = db.query(McpServer).count()
            online = db.query(McpServer).filter(McpServer.status == "online").count()
            offline = total - online
            total_tools = db.query(McpTool).count()

            servers = db.query(McpServer).order_by(McpServer.name.asc()).all()
            server_list = []
            for s in servers:
                tool_count = (
                    db.query(McpTool).filter(McpTool.server_id == s.id).count()
                )
                server_list.append({
                    "id": s.id,
                    "name": s.name,
                    "status": s.status,
                    "transport_type": s.transport_type,
                    "tool_count": tool_count,
                    "last_heartbeat": (
                        s.last_heartbeat.isoformat() if s.last_heartbeat else None
                    ),
                })

            return {
                "total_servers": total,
                "online_servers": online,
                "offline_servers": offline,
                "total_tools": total_tools,
                "servers": server_list,
            }
        finally:
            db.close()

    def get_recent_calls(self, limit: int = 50) -> List[Dict[str, Any]]:
        """获取最近的调用记录.

        优先从内存环形缓冲区读取，速度快。

        Args:
            limit: 返回数量限制

        Returns:
            调用记录列表
        """
        with self._lock:
            return self._recent_calls[: min(limit, len(self._recent_calls))]

    # --------------------------------------------------------
    # 数据库查询（历史数据）
    # --------------------------------------------------------

    def get_call_history(
        self,
        tool_name: Optional[str] = None,
        status: Optional[str] = None,
        server_id: Optional[int] = None,
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None,
        page: int = 1,
        page_size: int = 20,
    ) -> tuple:
        """从数据库查询调用历史.

        Args:
            tool_name: 按工具名过滤
            status: 按状态过滤
            server_id: 按服务器过滤
            start_time: 开始时间
            end_time: 结束时间
            page: 页码
            page_size: 每页数量

        Returns:
            (调用列表, 总数) 元组
        """
        db = get_session()
        try:
            query = db.query(McpCall)

            if tool_name:
                query = query.filter(McpCall.tool_name.like(f"%{tool_name}%"))
            if status:
                query = query.filter(McpCall.status == status)
            if server_id:
                query = query.filter(McpCall.server_id == server_id)
            if start_time:
                query = query.filter(McpCall.created_at >= start_time)
            if end_time:
                query = query.filter(McpCall.created_at <= end_time)

            total = query.count()
            calls = (
                query.order_by(McpCall.created_at.desc())
                .offset((page - 1) * page_size)
                .limit(page_size)
                .all()
            )

            return calls, total
        finally:
            db.close()

    def get_call_by_id(self, call_id: int) -> Optional[McpCall]:
        """按 ID 获取调用详情.

        Args:
            call_id: 调用 ID

        Returns:
            调用记录对象
        """
        db = get_session()
        try:
            return db.query(McpCall).filter(McpCall.id == call_id).first()
        finally:
            db.close()

    def get_tool_stats_from_db(
        self, days: int = 7
    ) -> List[Dict[str, Any]]:
        """从数据库获取工具统计（按天聚合）.

        Args:
            days: 统计天数

        Returns:
            每日统计数据列表
        """
        db = get_session()
        try:
            start_date = datetime.utcnow() - timedelta(days=days)
            results = (
                db.query(
                    func.date(McpCall.created_at).label("date"),
                    func.count(McpCall.id).label("total"),
                    func.sum(
                        McpCall.status == "success"
                    ).label("success"),
                    func.avg(McpCall.duration_ms).label("avg_duration"),
                )
                .filter(McpCall.created_at >= start_date)
                .group_by(func.date(McpCall.created_at))
                .order_by(func.date(McpCall.created_at).desc())
                .all()
            )

            daily_stats = []
            for row in results:
                total = row.total or 0
                success = row.success or 0
                daily_stats.append({
                    "date": str(row.date),
                    "total_calls": total,
                    "success_calls": success,
                    "failed_calls": total - success,
                    "success_rate": round(success / total * 100, 2) if total > 0 else 0.0,
                    "avg_duration_ms": round(row.avg_duration or 0, 2),
                })

            return daily_stats
        finally:
            db.close()

    # --------------------------------------------------------
    # 系统指标
    # --------------------------------------------------------

    def get_system_metrics(self) -> Dict[str, Any]:
        """获取系统级指标（CPU、内存等）.

        Returns:
            系统指标字典
        """
        try:
            import psutil

            cpu_percent = psutil.cpu_percent(interval=0.1)
            memory = psutil.virtual_memory()
            memory_percent = memory.percent

            return {
                "cpu_percent": cpu_percent,
                "memory_percent": memory_percent,
                "memory_total_mb": round(memory.total / (1024 * 1024), 2),
                "memory_used_mb": round(memory.used / (1024 * 1024), 2),
                "memory_available_mb": round(memory.available / (1024 * 1024), 2),
            }
        except ImportError:
            return {
                "cpu_percent": 0.0,
                "memory_percent": 0.0,
                "memory_total_mb": 0.0,
                "memory_used_mb": 0.0,
                "memory_available_mb": 0.0,
            }

    def reset_memory_stats(self) -> None:
        """重置内存统计计数器.

        用于测试或手动重置，不影响数据库中的历史数据。
        """
        with self._lock:
            self._total_calls = 0
            self._success_calls = 0
            self._failed_calls = 0
            self._total_duration_ms = 0
            self._tool_stats.clear()
            self._recent_calls.clear()


# ============================================================
# 单例实例
# ============================================================

mcp_monitor = McpMonitor()
