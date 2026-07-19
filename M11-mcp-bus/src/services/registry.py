"""M11 MCP Bus - 服务注册中心.

管理 MCP 服务器的注册、心跳、工具列表刷新等核心功能。
所有操作通过数据库持久化，支持多实例部署。

性能说明：
- 高频读接口接入三级缓存（L1内存 + L2文件 + L3 Redis预留）
- 服务器列表/工具列表使用短 TTL 缓存，心跳变化靠 TTL 自然过期
- 注册/注销/刷新操作后主动失效缓存
- 缓存 key 统一命名：m11:registry:*
"""

from __future__ import annotations

import hashlib
import secrets
import string
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import httpx
from sqlalchemy.orm import Session, joinedload

from ..config import get_settings
from ..db import get_session
from ..models_db import McpServer, McpTool

# ---------------------------------------------------------------------------
# 接入统一缓存框架 (shared.perf)
# ---------------------------------------------------------------------------
try:
    _project_root = Path(__file__).resolve()
    for _ in range(10):
        _project_root = _project_root.parent
        if (_project_root / "shared" / "perf" / "cache_manager.py").exists():
            if str(_project_root) not in sys.path:
                sys.path.insert(0, str(_project_root))
            break
except Exception:
    pass

try:
    from shared.perf.cache_manager import CacheManager
    _registry_cache = CacheManager.from_env(namespace="m11_registry")
    _HAS_UNIFIED_CACHE = True
except ImportError:
    _HAS_UNIFIED_CACHE = False
    _registry_cache = None  # type: ignore


# ============================================================
# 缓存 key 命名空间 (统一前缀：m11:registry:)
# ============================================================
# m11:registry:servers           - 服务器列表
# m11:registry:servers:{id}      - 服务器详情
# m11:registry:tools             - 工具列表（聚合）
# m11:registry:tools:{name}      - 工具详情


def _generate_api_key(length: int = 32) -> str:
    """生成随机 API Key.

    Args:
        length: 密钥长度

    Returns:
        随机生成的 API Key 字符串
    """
    alphabet = string.ascii_letters + string.digits
    return "mcp_" + "".join(secrets.choice(alphabet) for _ in range(length))


def _generate_server_id() -> str:
    """生成服务器 ID.

    Returns:
        服务器 ID 字符串
    """
    return "srv_" + secrets.token_hex(8)


class McpRegistry:
    """MCP 服务注册中心.

    负责管理 MCP 服务器的生命周期，包括注册、注销、心跳、
    工具列表刷新等功能。使用数据库作为持久化存储。
    """

    def __init__(self) -> None:
        """初始化注册中心."""
        self._settings = get_settings()

    # --------------------------------------------------------
    # 服务器管理
    # --------------------------------------------------------

    def register_server(
        self,
        name: str,
        transport_type: str = "http",
        endpoint: str = "",
        description: str = "",
        health_check_url: str = "",
    ) -> Tuple[McpServer, str]:
        """注册新的 MCP 服务器.

        自动生成 server_id 和 api_key，服务器初始状态为 offline。

        Args:
            name: 服务器名称（唯一）
            transport_type: 传输类型：http/sse/stdio
            endpoint: 服务端点地址
            description: 服务描述
            health_check_url: 健康检查地址

        Returns:
            (服务器对象, 明文 api_key) 元组

        Raises:
            ValueError: 服务器名称已存在
        """
        db = get_session()
        try:
            # 检查名称是否已存在
            existing = db.query(McpServer).filter(McpServer.name == name).first()
            if existing:
                raise ValueError(f"服务器名称已存在: {name}")

            api_key = _generate_api_key()

            server = McpServer(
                name=name,
                description=description,
                transport_type=transport_type,
                endpoint=endpoint,
                status="offline",
                api_key=api_key,
                health_check_url=health_check_url,
                last_heartbeat=None,
                created_at=datetime.utcnow(),
            )
            db.add(server)
            db.commit()
            db.refresh(server)

            # 失效服务器列表缓存
            if _HAS_UNIFIED_CACHE:
                _registry_cache.clear(pattern="m11:registry:servers:*")

            return server, api_key
        finally:
            db.close()

    def unregister_server(self, server_id: int) -> bool:
        """注销 MCP 服务器.

        Args:
            server_id: 服务器 ID

        Returns:
            是否成功删除
        """
        db = get_session()
        try:
            server = db.query(McpServer).filter(McpServer.id == server_id).first()
            if not server:
                return False
            db.delete(server)
            db.commit()

            # 失效相关缓存
            if _HAS_UNIFIED_CACHE:
                _registry_cache.clear(pattern="m11:registry:servers:*")
                _registry_cache.clear(pattern="m11:registry:tools:*")

            return True
        finally:
            db.close()

    def heartbeat(self, server_id: int, status: str = "online") -> Optional[McpServer]:
        """服务器心跳更新.

        更新最后心跳时间和状态。

        Args:
            server_id: 服务器 ID
            status: 服务器状态

        Returns:
            更新后的服务器对象，不存在则返回 None
        """
        db = get_session()
        try:
            server = db.query(McpServer).filter(McpServer.id == server_id).first()
            if not server:
                return None

            server.last_heartbeat = datetime.utcnow()
            server.status = status
            db.commit()
            db.refresh(server)
            return server
        finally:
            db.close()

    def list_servers(self, status: Optional[str] = None) -> List[McpServer]:
        """获取服务器列表（缓存 30 秒）.

        心跳状态变化通过短 TTL 自然过期，不主动失效，
        避免频繁心跳导致缓存抖动。

        Args:
            status: 可选，按状态过滤

        Returns:
            服务器列表
        """
        cache_key = f"m11:registry:servers:status={status or 'all'}"
        if _HAS_UNIFIED_CACHE and _registry_cache.exists(cache_key):
            return _registry_cache.get(cache_key)

        db = get_session()
        try:
            query = db.query(McpServer)
            if status:
                query = query.filter(McpServer.status == status)
            result = query.order_by(McpServer.created_at.desc()).all()

            if _HAS_UNIFIED_CACHE:
                _registry_cache.set(cache_key, result, ttl=30)  # 30 秒

            return result
        finally:
            db.close()

    def get_server(self, server_id: int) -> Optional[McpServer]:
        """获取服务器详情（缓存 30 秒）.

        Args:
            server_id: 服务器 ID

        Returns:
            服务器对象，不存在则返回 None
        """
        cache_key = f"m11:registry:servers:id:{server_id}"
        if _HAS_UNIFIED_CACHE and _registry_cache.exists(cache_key):
            return _registry_cache.get(cache_key)

        db = get_session()
        try:
            result = db.query(McpServer).filter(McpServer.id == server_id).first()

            if _HAS_UNIFIED_CACHE and result is not None:
                _registry_cache.set(cache_key, result, ttl=30)  # 30 秒

            return result
        finally:
            db.close()

    def get_server_by_name(self, name: str) -> Optional[McpServer]:
        """按名称获取服务器（缓存 30 秒）.

        Args:
            name: 服务器名称

        Returns:
            服务器对象，不存在则返回 None
        """
        cache_key = f"m11:registry:servers:name:{name}"
        if _HAS_UNIFIED_CACHE and _registry_cache.exists(cache_key):
            return _registry_cache.get(cache_key)

        db = get_session()
        try:
            result = db.query(McpServer).filter(McpServer.name == name).first()

            if _HAS_UNIFIED_CACHE and result is not None:
                _registry_cache.set(cache_key, result, ttl=30)  # 30 秒

            return result
        finally:
            db.close()

    def check_offline_servers(self) -> int:
        """检查超时服务器并标记为 offline.

        遍历所有 online 状态的服务器，如果最后心跳时间
        超过心跳超时阈值，则标记为 offline。

        Returns:
            被标记为 offline 的服务器数量
        """
        db = get_session()
        try:
            timeout = timedelta(seconds=self._settings.heartbeat_timeout)
            cutoff = datetime.utcnow() - timeout

            offline_servers = (
                db.query(McpServer)
                .filter(
                    McpServer.status == "online",
                    (McpServer.last_heartbeat.is_(None)) | (McpServer.last_heartbeat < cutoff),
                )
                .all()
            )

            count = 0
            for server in offline_servers:
                server.status = "offline"
                count += 1

            if count > 0:
                db.commit()

            return count
        finally:
            db.close()

    # --------------------------------------------------------
    # 工具管理
    # --------------------------------------------------------

    def refresh_all_tools(self, force: bool = False) -> Dict[str, Any]:
        """从所有 online 服务器刷新工具列表.

        遍历所有在线服务器，调用其 MCP tools/list 接口获取工具列表，
        然后更新本地缓存。

        Args:
            force: 是否强制刷新（忽略缓存间隔）

        Returns:
            刷新结果统计：{total_servers, refreshed, failed, total_tools}
        """
        db = get_session()
        try:
            online_servers = (
                db.query(McpServer).filter(McpServer.status == "online").all()
            )

            result = {
                "total_servers": len(online_servers),
                "refreshed": 0,
                "failed": 0,
                "total_tools": 0,
                "errors": [],
            }

            for server in online_servers:
                try:
                    tools = self._fetch_server_tools(server)
                    self._update_server_tools(db, server.id, server.name, tools)
                    result["refreshed"] += 1
                    result["total_tools"] += len(tools)
                except Exception as e:
                    result["failed"] += 1
                    result["errors"].append(f"{server.name}: {str(e)}")

            db.commit()

            # 失效工具列表缓存
            if _HAS_UNIFIED_CACHE:
                _registry_cache.clear(pattern="m11:registry:tools:*")

            return result
        finally:
            db.close()

    def _fetch_server_tools(self, server: McpServer) -> List[Dict[str, Any]]:
        """从远程服务器获取工具列表.

        支持 http 和 stdio 两种传输类型。

        Args:
            server: 服务器对象

        Returns:
            工具列表

        Raises:
            Exception: 请求失败时抛出
        """
        if server.transport_type == "http":
            return self._fetch_server_tools_http(server)
        elif server.transport_type == "stdio":
            return self._fetch_server_tools_stdio(server)
        else:
            raise ValueError(f"不支持的传输类型: {server.transport_type}")

    def _fetch_server_tools_http(self, server: McpServer) -> List[Dict[str, Any]]:
        """从 HTTP 服务器获取工具列表.

        Args:
            server: 服务器对象

        Returns:
            工具列表

        Raises:
            Exception: 请求失败时抛出
        """
        if not server.endpoint:
            raise ValueError("服务器未配置端点地址")

        # 发送 MCP JSON-RPC 请求
        payload = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/list",
            "params": {},
        }

        headers = {"Content-Type": "application/json"}
        if server.api_key:
            headers["Authorization"] = f"Bearer {server.api_key}"

        with httpx.Client(timeout=10.0) as client:
            response = client.post(server.endpoint, json=payload, headers=headers)
            response.raise_for_status()
            data = response.json()

        if "result" not in data:
            error = data.get("error", {})
            raise ValueError(f"工具列表获取失败: {error.get('message', '未知错误')}")

        return data.get("result", {}).get("tools", [])

    def _fetch_server_tools_stdio(self, server: McpServer) -> List[Dict[str, Any]]:
        """从 stdio 服务获取工具列表.

        通过 stdio_manager 向子进程发送 tools/list 请求。

        Args:
            server: 服务器对象

        Returns:
            工具列表

        Raises:
            Exception: 请求失败时抛出
        """
        from .stdio_manager import stdio_manager

        # 查找对应的 stdio 服务实例
        # stdio 服务通过名称与注册中心服务器关联
        stdio_service = None
        for svc in stdio_manager.list_services():
            if svc.name == server.name:
                stdio_service = svc
                break

        if not stdio_service:
            raise ValueError(f"stdio 服务未运行: {server.name}")

        # 使用 asyncio 运行时调用（同步方法内调用异步）
        # 注意：refresh_all_tools 是同步方法，这里需要在事件循环中运行
        import asyncio

        try:
            loop = asyncio.get_event_loop()
        except RuntimeError:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)

        if loop.is_running():
            # 如果已有运行中的事件循环（如在 FastAPI 中），返回空列表
            # 实际场景中 stdio 服务的工具刷新应该由异步任务处理
            raise RuntimeError("事件循环已在运行，无法同步获取 stdio 工具列表")

        result = loop.run_until_complete(
            stdio_manager.send_request(
                service_id=stdio_service.service_id,
                method="tools/list",
                params={},
                timeout=10.0,
            )
        )

        return result.get("tools", [])

    def _update_server_tools(
        self,
        db: Session,
        server_id: int,
        server_name: str,
        tools: List[Dict[str, Any]],
    ) -> None:
        """更新服务器的工具列表.

        删除旧工具，插入新工具，保持原子性。

        Args:
            db: 数据库 session
            server_id: 服务器 ID
            server_name: 服务器名称
            tools: 工具列表
        """
        # 删除该服务器的所有旧工具
        db.query(McpTool).filter(McpTool.server_id == server_id).delete()

        now = datetime.utcnow()
        for tool in tools:
            tool_name = tool.get("name", "")
            # 工具名格式：{server_name}.{tool_name}
            # 总是加服务器前缀，避免不同服务器的工具名冲突
            full_name = f"{server_name}.{tool_name}"

            db_tool = McpTool(
                server_id=server_id,
                name=full_name,
                description=tool.get("description", ""),
                category=tool.get("category", "general"),
                input_schema=tool.get("inputSchema", tool.get("input_schema", {})),
                cached_at=now,
            )
            db.add(db_tool)

    def get_all_tools(
        self,
        server_id: Optional[int] = None,
        category: Optional[str] = None,
        keyword: Optional[str] = None,
        page: int = 1,
        page_size: int = 50,
    ) -> Tuple[List[McpTool], int, List[str]]:
        """获取聚合工具列表（缓存 30 秒）.

        Args:
            server_id: 可选，按服务器过滤
            category: 可选，按分类过滤
            keyword: 可选，按关键词搜索（名称/描述）
            page: 页码，从 1 开始
            page_size: 每页数量

        Returns:
            (工具列表, 总数, 分类列表) 元组
        """
        cache_key = (
            f"m11:registry:tools:sid={server_id or 'all'}:"
            f"cat={category or 'all'}:kw={keyword or 'none'}:"
            f"p={page}:ps={page_size}"
        )
        if len(cache_key) > 200:
            h = hashlib.md5(cache_key.encode()).hexdigest()
            cache_key = f"m11:registry:tools:hash:{h}"

        if _HAS_UNIFIED_CACHE and _registry_cache.exists(cache_key):
            cached = _registry_cache.get(cache_key)
            if isinstance(cached, (list, tuple)) and len(cached) == 3:
                return cached[0], cached[1], cached[2]

        db = get_session()
        try:
            query = db.query(McpTool).options(joinedload(McpTool.server))

            if server_id:
                query = query.filter(McpTool.server_id == server_id)
            if category:
                query = query.filter(McpTool.category == category)
            if keyword:
                like = f"%{keyword}%"
                query = query.filter(
                    (McpTool.name.like(like)) | (McpTool.description.like(like))
                )

            total = query.count()

            # 获取所有分类
            categories = [
                row[0]
                for row in db.query(McpTool.category).distinct().all()
                if row[0]
            ]

            tools = (
                query.order_by(McpTool.name.asc())
                .offset((page - 1) * page_size)
                .limit(page_size)
                .all()
            )

            result = (tools, total, sorted(categories))

            if _HAS_UNIFIED_CACHE:
                _registry_cache.set(cache_key, result, ttl=30)  # 30 秒

            return result
        finally:
            db.close()

    def get_tool_by_name(self, tool_name: str) -> Optional[Tuple[McpTool, McpServer]]:
        """按工具名查找工具及其所属服务器.

        Args:
            tool_name: 工具全名（格式：{server_name}.{tool_name}）

        Returns:
            (工具对象, 服务器对象) 元组，未找到返回 None
        """
        db = get_session()
        try:
            tool = db.query(McpTool).filter(McpTool.name == tool_name).first()
            if not tool:
                return None

            server = db.query(McpServer).filter(McpServer.id == tool.server_id).first()
            if not server:
                return None

            return tool, server
        finally:
            db.close()

    def get_server_tool_count(self, server_id: int) -> int:
        """获取服务器的工具数量.

        Args:
            server_id: 服务器 ID

        Returns:
            工具数量
        """
        db = get_session()
        try:
            return db.query(McpTool).filter(McpTool.server_id == server_id).count()
        finally:
            db.close()

    # --------------------------------------------------------
    # stdio 服务集成
    # --------------------------------------------------------

    async def refresh_stdio_server_tools(self, server_id: int) -> int:
        """异步刷新 stdio 服务的工具列表.

        专门用于 stdio 传输类型的服务器，通过 stdio_manager 发送 tools/list 请求。

        Args:
            server_id: 服务器 ID

        Returns:
            刷新后的工具数量

        Raises:
            ValueError: 服务器不存在或不是 stdio 类型
        """
        from .stdio_manager import stdio_manager

        db = get_session()
        try:
            server = db.query(McpServer).filter(McpServer.id == server_id).first()
            if not server:
                raise ValueError(f"服务器不存在: {server_id}")

            if server.transport_type != "stdio":
                raise ValueError(f"服务器不是 stdio 类型: {server.transport_type}")

            # 查找对应的 stdio 服务实例
            stdio_service = None
            for svc in stdio_manager.list_services():
                if svc.name == server.name:
                    stdio_service = svc
                    break

            if not stdio_service:
                raise ValueError(f"stdio 服务未运行: {server.name}")

            # 发送 tools/list 请求
            result = await stdio_manager.send_request(
                service_id=stdio_service.service_id,
                method="tools/list",
                params={},
                timeout=10.0,
            )

            tools = result.get("tools", [])

            # 更新数据库
            self._update_server_tools(db, server.id, server.name, tools)
            db.commit()

            # 失效工具列表缓存
            if _HAS_UNIFIED_CACHE:
                _registry_cache.clear(pattern="m11:registry:tools:*")

            return len(tools)
        finally:
            db.close()

    def register_stdio_server(
        self,
        name: str,
        description: str = "",
    ) -> Tuple[McpServer, str]:
        """注册一个 stdio 类型的 MCP 服务器.

        便捷方法：创建 transport_type=stdio 的服务器记录。
        stdio 服务由 stdio_manager 管理，启动时会自动注册到服务列表。

        Args:
            name: 服务器名称（唯一）
            description: 服务描述

        Returns:
            (服务器对象, 明文 api_key) 元组
        """
        return self.register_server(
            name=name,
            transport_type="stdio",
            endpoint="stdio://local",
            description=description,
            health_check_url="",
        )


# ============================================================
# 单例实例
# ============================================================

mcp_registry = McpRegistry()
