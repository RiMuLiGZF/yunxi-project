"""分布式管理 API — 可挂载到任意模块的 FastAPI app

提供节点管理、心跳上报、消息中转和集群健康状态等 REST 接口。
"""

import time
import logging
from typing import Optional

from fastapi import APIRouter, HTTPException

logger = logging.getLogger("shared.distributed.api")

router = APIRouter(prefix="/api/v1/cluster", tags=["分布式集群管理"])

# -----------------------------------------------------------------------
# 全局单例（在应用启动时初始化，或通过依赖注入替换）
# -----------------------------------------------------------------------
_registry = None  # type: Optional["NodeRegistry"]
_bus = None  # type: Optional["MessageBus"]


def init_services(registry=None, bus=None):
    """初始化 API 服务（在应用启动时调用）

    Args:
        registry: NodeRegistry 实例（主节点必须提供）
        bus:      MessageBus 实例（可选）
    """
    global _registry, _bus
    _registry = registry
    _bus = bus
    if registry:
        logger.info("分布式 API 已绑定 NodeRegistry")
    if bus:
        logger.info("分布式 API 已绑定 MessageBus")


def _require_registry():
    """确保 NodeRegistry 已初始化"""
    if _registry is None:
        raise HTTPException(
            status_code=503,
            detail="NodeRegistry 未初始化（本节点可能非主节点）",
        )
    return _registry


# -----------------------------------------------------------------------
# 节点管理
# -----------------------------------------------------------------------


@router.get("/nodes", summary="列出所有节点")
async def list_nodes():
    """列出集群中所有已注册节点"""
    registry = _require_registry()
    nodes = registry.get_all_nodes()
    return {
        "code": 0,
        "message": "ok",
        "data": {
            "nodes": [n.to_dict() for n in nodes],
            "summary": registry.get_cluster_summary(),
        },
    }


@router.get("/nodes/{node_id}", summary="获取节点详情")
async def get_node(node_id: str):
    """获取指定节点的详细信息"""
    registry = _require_registry()
    node = registry.get_node(node_id)
    if not node:
        raise HTTPException(status_code=404, detail=f"节点 {node_id} 不存在")
    return {
        "code": 0,
        "message": "ok",
        "data": node.to_dict(),
    }


@router.post("/nodes/register", summary="注册节点")
async def register_node(payload: dict):
    """注册新节点（边缘节点调用）

    Request Body:
        node_id: 节点 ID
        node_role: 节点角色
        node_name: 节点名称
        host: 节点地址
        port: 节点端口
        modules: 节点运行的模块列表
    """
    registry = _require_registry()

    from .node_registry import NodeInfo

    required_fields = ["node_id", "host", "port"]
    for field_name in required_fields:
        if field_name not in payload:
            raise HTTPException(
                status_code=400,
                detail=f"缺少必填字段: {field_name}",
            )

    node = NodeInfo(
        node_id=payload["node_id"],
        node_role=payload.get("node_role", "edge"),
        node_name=payload.get("node_name", payload["node_id"]),
        host=payload["host"],
        port=payload["port"],
        modules=payload.get("modules", []),
    )
    registry.register(node)

    # 如果消息总线可用，通知所有节点有新节点加入
    if _bus:
        try:
            _bus.publish("cluster.node.joined", node.to_dict(), target_node="all")
        except Exception as e:
            logger.warning(f"广播节点加入事件失败: {e}")

    return {
        "code": 0,
        "message": "ok",
        "data": node.to_dict(),
    }


@router.post("/nodes/{node_id}/heartbeat", summary="节点心跳")
async def node_heartbeat(node_id: str, payload: dict = None):
    """节点心跳上报（边缘节点定期调用）

    Args:
        node_id: 节点 ID
        payload: 可选更新信息 {"status": "healthy", "modules": [...]}
    """
    registry = _require_registry()
    payload = payload or {}

    kwargs = {}
    if "status" in payload:
        kwargs["status"] = payload["status"]
    if "modules" in payload:
        kwargs["modules"] = payload["modules"]
    if "host" in payload:
        kwargs["host"] = payload["host"]
    if "port" in payload:
        kwargs["port"] = payload["port"]

    success = registry.heartbeat(node_id, **kwargs)
    if not success:
        raise HTTPException(
            status_code=404,
            detail=f"节点 {node_id} 未注册，请先调用 /nodes/register",
        )

    return {
        "code": 0,
        "message": "ok",
        "data": {"node_id": node_id, "heartbeat_time": time.time()},
    }


@router.delete("/nodes/{node_id}", summary="注销节点")
async def deregister_node(node_id: str):
    """注销指定节点"""
    registry = _require_registry()
    node = registry.get_node(node_id)
    if not node:
        raise HTTPException(status_code=404, detail=f"节点 {node_id} 不存在")

    registry.deregister(node_id)

    # 通知其他节点
    if _bus:
        try:
            _bus.publish(
                "cluster.node.left",
                {"node_id": node_id, "node_name": node.node_name},
                target_node="all",
            )
        except Exception as e:
            logger.warning(f"广播节点离开事件失败: {e}")

    return {"code": 0, "message": "ok"}


# -----------------------------------------------------------------------
# 消息中转
# -----------------------------------------------------------------------


@router.post("/message", summary="发送跨节点消息")
async def receive_message(payload: dict):
    """接收并处理跨节点消息

    边缘节点通过此接口接收广播消息或 RPC 请求。
    """
    topic = payload.get("topic", "")
    message_data = payload.get("payload", {})
    source_node = payload.get("source_node", "")
    message_type = payload.get("message_type", "broadcast")

    if not topic:
        raise HTTPException(status_code=400, detail="缺少 topic 字段")

    if _bus:
        # RPC 请求需要有处理器并返回结果
        if message_type == "request":
            handler = _bus._request_handlers.get(topic)
            if handler:
                try:
                    result = handler(topic, message_data)
                    return {"code": 0, "message": "ok", "data": result}
                except Exception as e:
                    logger.error(f"RPC 处理异常: {topic}: {e}")
                    return {"code": 500, "message": str(e), "data": None}
            return {"code": 404, "message": f"无处理器: {topic}", "data": None}
        else:
            # 普通广播/事件，在本地分发
            _bus._send_to_local(topic, message_data, source_node=source_node)
            return {"code": 0, "message": "ok"}
    else:
        return {"code": 503, "message": "MessageBus 未初始化", "data": None}


# -----------------------------------------------------------------------
# 集群健康状态
# -----------------------------------------------------------------------


@router.get("/health", summary="集群健康状态")
async def cluster_health():
    """获取集群整体健康状态"""
    if _registry is None:
        return {
            "code": 0,
            "message": "ok",
            "data": {
                "status": "standalone",
                "message": "本节点未运行注册中心（非主节点模式）",
            },
        }

    summary = _registry.get_cluster_summary()
    healthy_nodes = _registry.get_healthy_nodes()

    return {
        "code": 0,
        "message": "ok",
        "data": {
            **summary,
            "healthy_nodes": [n.to_dict() for n in healthy_nodes],
        },
    }
