"""
云汐 M9 数据水晶 - 连接器管理 API

P3 优化：数据采集管道 + 连接器生态
提供连接器的 CRUD、测试连接、健康检查、Schema 查询等接口
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import List, Dict, Any, Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

# 确保可以导入本地模块
_backend_dir = Path(__file__).resolve().parent.parent
if str(_backend_dir) not in sys.path:
    sys.path.insert(0, str(_backend_dir))

from connectors.manager import get_connector_manager

router = APIRouter(prefix="/api/v1/connectors", tags=["connectors"])


# ============================================================
# 请求/响应模型
# ============================================================

class ConnectorCreateRequest(BaseModel):
    name: str
    connector_type: str
    description: str = ""
    config: Dict[str, Any] = Field(default_factory=dict)


class ConnectorUpdateRequest(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    config: Optional[Dict[str, Any]] = None


class TestConnectionRequest(BaseModel):
    connector_type: str
    config: Dict[str, Any] = Field(default_factory=dict)


# ============================================================
# 连接器类型列表
# ============================================================

@router.get("/types", summary="获取可用连接器类型")
async def get_connector_types():
    """获取所有可用的连接器类型及其元数据"""
    try:
        mgr = get_connector_manager()
        types = mgr.list_connector_types()
        categories = mgr.get_connector_categories()
        return {
            "code": 0,
            "message": "ok",
            "data": {
                "types": types,
                "categories": categories,
                "total": len(types),
            }
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ============================================================
# 连接器 CRUD
# ============================================================

@router.get("", summary="连接器列表")
async def list_connectors():
    """获取所有连接器实例列表"""
    try:
        mgr = get_connector_manager()
        connectors = mgr.list_connectors()
        return {
            "code": 0,
            "message": "ok",
            "data": {
                "connectors": connectors,
                "total": len(connectors),
            }
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("", summary="创建连接器")
async def create_connector(request: ConnectorCreateRequest):
    """创建新的连接器实例"""
    try:
        mgr = get_connector_manager()
        connector_id = mgr.create_connector(
            connector_type=request.connector_type,
            config=request.config,
        )

        # 获取创建后的信息
        connector = mgr.get_connector(connector_id)
        config_info = mgr.get_connector_config(connector_id)

        return {
            "code": 0,
            "message": "ok",
            "data": {
                "id": connector_id,
                "name": request.name,
                "connector_type": request.connector_type,
                "description": request.description,
                "status": connector.status,
                "is_connected": connector.is_connected(),
                "config": connector.config,
                "created_at": config_info.get("created_at"),
            }
        }
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/{connector_id}", summary="连接器详情")
async def get_connector(connector_id: str):
    """获取连接器详细信息"""
    try:
        mgr = get_connector_manager()
        connector = mgr.get_connector(connector_id)
        config_info = mgr.get_connector_config(connector_id)

        return {
            "code": 0,
            "message": "ok",
            "data": {
                "id": connector_id,
                "name": connector.meta.name,
                "connector_type": config_info.get("connector_type", ""),
                "description": connector.meta.description,
                "status": connector.status,
                "is_connected": connector.is_connected(),
                "config": connector.config,
                "stats": connector.get_stats(),
                "version": connector.meta.version,
                "supported_operations": connector.meta.supported_operations,
                "created_at": config_info.get("created_at"),
                "updated_at": config_info.get("updated_at"),
            }
        }
    except KeyError:
        raise HTTPException(status_code=404, detail=f"连接器不存在: {connector_id}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.put("/{connector_id}", summary="更新连接器配置")
async def update_connector(connector_id: str, request: ConnectorUpdateRequest):
    """更新连接器配置"""
    try:
        mgr = get_connector_manager()
        updated = mgr.update_connector(
            connector_id,
            config=request.config or {},
        )

        connector = mgr.get_connector(connector_id)
        return {
            "code": 0,
            "message": "ok",
            "data": {
                "id": connector_id,
                "status": connector.status,
                "config": connector.config,
            }
        }
    except KeyError:
        raise HTTPException(status_code=404, detail=f"连接器不存在: {connector_id}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/{connector_id}", summary="删除连接器")
async def delete_connector(connector_id: str):
    """删除连接器实例"""
    try:
        mgr = get_connector_manager()
        deleted = mgr.delete_connector(connector_id)
        if not deleted:
            raise HTTPException(status_code=404, detail=f"连接器不存在: {connector_id}")

        return {
            "code": 0,
            "message": "ok",
            "data": {"deleted": True}
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ============================================================
# 连接操作
# ============================================================

@router.post("/{connector_id}/connect", summary="连接")
async def connect_connector(connector_id: str):
    """建立连接器连接"""
    try:
        mgr = get_connector_manager()
        result = mgr.connect_connector(connector_id)
        return {
            "code": 0,
            "message": "ok",
            "data": {"connected": result}
        }
    except KeyError:
        raise HTTPException(status_code=404, detail=f"连接器不存在: {connector_id}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/{connector_id}/disconnect", summary="断开连接")
async def disconnect_connector(connector_id: str):
    """断开连接器连接"""
    try:
        mgr = get_connector_manager()
        result = mgr.disconnect_connector(connector_id)
        return {
            "code": 0,
            "message": "ok",
            "data": {"disconnected": result}
        }
    except KeyError:
        raise HTTPException(status_code=404, detail=f"连接器不存在: {connector_id}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/test", summary="测试连接（不保存）")
async def test_connection(request: TestConnectionRequest):
    """测试连接器配置是否可用（不保存实例）"""
    try:
        mgr = get_connector_manager()
        result = mgr.test_connection(request.connector_type, request.config)
        return {
            "code": 0,
            "message": "ok",
            "data": result
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/{connector_id}/test", summary="测试已有连接器")
async def test_existing_connector(connector_id: str):
    """测试已有连接器的连接"""
    try:
        mgr = get_connector_manager()
        config_info = mgr.get_connector_config(connector_id)
        connector_type = config_info.get("connector_type", "")
        config = config_info.get("config", {})

        result = mgr.test_connection(connector_type, config)
        return {
            "code": 0,
            "message": "ok",
            "data": result
        }
    except KeyError:
        raise HTTPException(status_code=404, detail=f"连接器不存在: {connector_id}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ============================================================
# 健康检查
# ============================================================

@router.get("/{connector_id}/health", summary="健康状态")
async def get_connector_health(connector_id: str):
    """获取连接器健康状态"""
    try:
        mgr = get_connector_manager()
        health = mgr.get_health_status(connector_id)
        return {
            "code": 0,
            "message": "ok",
            "data": health
        }
    except KeyError:
        raise HTTPException(status_code=404, detail=f"连接器不存在: {connector_id}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ============================================================
# Schema 查询
# ============================================================

@router.get("/{connector_id}/schema", summary="获取 Schema")
async def get_connector_schema(connector_id: str, table: str = Query(..., description="表名/文件名")):
    """获取连接器指定表的 Schema"""
    try:
        mgr = get_connector_manager()
        schema = mgr.get_schema(connector_id, table)
        return {
            "code": 0,
            "message": "ok",
            "data": schema
        }
    except KeyError:
        raise HTTPException(status_code=404, detail=f"连接器不存在: {connector_id}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/{connector_id}/tables", summary="列出表/文件")
async def list_connector_tables(connector_id: str):
    """列出连接器中的所有表/文件/端点"""
    try:
        mgr = get_connector_manager()
        tables = mgr.list_tables(connector_id)
        return {
            "code": 0,
            "message": "ok",
            "data": {
                "tables": tables,
                "total": len(tables),
            }
        }
    except KeyError:
        raise HTTPException(status_code=404, detail=f"连接器不存在: {connector_id}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ============================================================
# 统计信息
# ============================================================

@router.get("/stats/summary", summary="连接器统计摘要")
async def get_connectors_stats():
    """获取连接器管理器统计信息"""
    try:
        mgr = get_connector_manager()
        stats = mgr.get_stats()
        return {
            "code": 0,
            "message": "ok",
            "data": stats
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
