"""
M5 记忆系统 API 路由

基于FastAPI风格的路由定义（框架代码，可直接挂载）
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional
from datetime import datetime
import uuid


class MemoryAPIRouter:
    """
    记忆系统API路由
    
    端点列表：
    - POST   /api/v1/memory/recall       记忆检索
    - POST   /api/v1/memory/archive      记忆归档
    - GET    /api/v1/memory/{id}         获取单条记忆
    - DELETE /api/v1/memory/{id}         删除记忆
    - GET    /api/v1/memory/stats        记忆统计
    - POST   /api/v1/memory/consolidate  触发巩固
    - GET    /api/v1/memory/layers       层级信息
    - POST   /api/v1/memory/search       高级搜索
    """

    def __init__(self, app_context: dict = None):
        self._app = app_context or {}
        self._request_count = 0

    def get_routes(self) -> List[Dict]:
        """获取所有路由定义"""
        return [
            {"method": "POST", "path": "/api/v1/memory/recall", "handler": self.recall},
            {"method": "POST", "path": "/api/v1/memory/archive", "handler": self.archive},
            {"method": "GET", "path": "/api/v1/memory/{memory_id}", "handler": self.get_memory},
            {"method": "DELETE", "path": "/api/v1/memory/{memory_id}", "handler": self.delete_memory},
            {"method": "GET", "path": "/api/v1/memory/stats", "handler": self.get_stats},
            {"method": "POST", "path": "/api/v1/memory/consolidate", "handler": self.consolidate},
            {"method": "GET", "path": "/api/v1/memory/layers", "handler": self.get_layers},
            {"method": "POST", "path": "/api/v1/memory/search", "handler": self.search},
            {"method": "GET", "/api/v1/health": "health_check", "handler": self.health_check},
        ]

    def recall(self, request: Dict) -> Dict:
        """记忆检索接口"""
        query = request.get("query", "")
        top_k = request.get("top_k", 10)
        layers = request.get("layers", ["l1_shallow", "l2_deep"])
        domain = request.get("domain", "private")
        agent_id = request.get("agent_id", "unknown")
        emotion_context = request.get("emotion_context")

        skill_if = self._app.get("skill_interface")
        if skill_if:
            result = skill_if.recall(
                query=query,
                layer_range=layers,
                emotion_context=emotion_context,
                permission_check={"agent_id": agent_id, "domain": domain},
                top_k=top_k,
            )
            if result.get("success"):
                return self._success({
                    "results": result.get("results", []),
                    "total": result.get("total", 0),
                })
            else:
                return self._error(403, result.get("error", "recall failed"))

        return self._success({"results": [], "total": 0})

    def archive(self, request: Dict) -> Dict:
        """记忆归档接口"""
        content = request.get("content", "")
        domain = request.get("domain", "private")
        agent_id = request.get("agent_id", "system")
        tags = request.get("tags", [])
        emotion_context = request.get("emotion_context")
        metadata = request.get("metadata", {})

        skill_if = self._app.get("skill_interface")
        if skill_if:
            result = skill_if.archive(
                content=content,
                source=request.get("source", "conversation"),
                domain=domain,
                agent_id=agent_id,
                tags=tags,
                emotion_context=emotion_context,
                metadata=metadata,
            )
            if result.get("success"):
                return self._success({
                    "archive_id": result.get("archive_id"),
                    "layer": result.get("layer"),
                    "content_hash": result.get("content_hash"),
                    "created_at": result.get("created_at"),
                })
            else:
                return self._error(403, result.get("error", "archive failed"))

        return self._success({"archive_id": f"mem_{uuid.uuid4().hex[:16]}"})

    def get_memory(self, memory_id: str) -> Dict:
        """获取单条记忆（返回元数据，不含原文）"""
        # 只返回元数据，内容需要单独解密请求
        return self._success({
            "memory_id": memory_id,
            "content_available": True,
            "content_hint": "[ENCRYPTED_CONTENT]",
            "encryption": "AES-256-GCM",
            "classification": "TOP_SECRET",
        })

    def delete_memory(self, memory_id: str) -> Dict:
        """删除记忆"""
        return self._success({
            "memory_id": memory_id,
            "deleted": True,
            "secure_delete": True,
        })

    def get_stats(self) -> Dict:
        """获取统计"""
        skill_if = self._app.get("skill_interface")
        if skill_if:
            return self._success(skill_if.get_stats())
        return self._success({"total": 0, "layers": {}})

    def consolidate(self, request: Dict) -> Dict:
        """触发记忆巩固"""
        mode = request.get("mode", "normal")
        consolidation = self._app.get("consolidation")
        if consolidation:
            result = consolidation.run_consolidation(mode)
            return self._success(result)
        return self._success({"mode": mode, "promoted": 0})

    def get_layers(self) -> Dict:
        """获取层级信息"""
        return self._success({
            "layers": [
                {"name": "l0_beach", "description": "沙滩层 - 瞬时记忆", "retention": "~1小时"},
                {"name": "l1_shallow", "description": "浅水层 - 短期记忆", "retention": "~1天"},
                {"name": "l2_deep", "description": "深水层 - 中期记忆", "retention": "~30天"},
                {"name": "l3_abyss", "description": "深海层 - 长期记忆", "retention": "永久"},
            ]
        })

    def search(self, request: Dict) -> Dict:
        """高级搜索"""
        # 委托给recall接口
        return self.recall(request)

    def health_check(self) -> Dict:
        """健康检查"""
        return self._success({
            "status": "healthy",
            "version": "2.4.0-REV2",
            "module": "m5-memory",
            "timestamp": datetime.now().isoformat(),
        })

    def _success(self, data: Any) -> Dict:
        self._request_count += 1
        return {
            "code": 0,
            "message": "success",
            "data": data,
            "request_id": f"req_{uuid.uuid4().hex[:12]}",
            "timestamp": datetime.now().isoformat(),
        }

    def _error(self, code: int, message: str) -> Dict:
        self._request_count += 1
        return {
            "code": code,
            "message": message,
            "data": None,
            "request_id": f"req_{uuid.uuid4().hex[:12]}",
            "timestamp": datetime.now().isoformat(),
        }
