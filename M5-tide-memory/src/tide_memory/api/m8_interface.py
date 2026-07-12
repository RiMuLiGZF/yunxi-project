"""
M8 标准接口适配层

M5 潮汐记忆系统对接 M8 标准接口规范
所有对外接口遵循 M8 统一错误码和响应格式
"""

from __future__ import annotations

import os
from enum import IntEnum
from typing import Any, Dict, Optional
from datetime import datetime


class M8ErrorCode(IntEnum):
    """M8 统一错误码（M5分段 50000-59999）"""
    SUCCESS = 0
    
    # 通用错误
    UNKNOWN_ERROR = 50000
    INVALID_PARAMS = 50001
    UNAUTHORIZED = 50002
    FORBIDDEN = 50003
    NOT_FOUND = 50004
    RATE_LIMITED = 50005
    INTERNAL_ERROR = 50006
    
    # 记忆相关
    MEMORY_NOT_FOUND = 50101
    MEMORY_TOO_LARGE = 50102
    MEMORY_ENCRYPTION_FAILED = 50103
    MEMORY_DECRYPTION_FAILED = 50104
    
    # 权限相关
    PERMISSION_DENIED = 50201
    DOMAIN_NOT_ACCESSIBLE = 50202
    CLASSIFICATION_TOO_HIGH = 50203
    
    # 存储相关
    STORAGE_FULL = 50301
    STORAGE_ERROR = 50302
    SYNC_FAILED = 50303
    
    # 检索相关
    SEARCH_TIMEOUT = 50401
    VECTOR_INDEX_ERROR = 50402
    
    # 巩固相关
    CONSOLIDATION_RUNNING = 50501
    CONSOLIDATION_FAILED = 50502


# 延迟加载的版本号
_module_version: Optional[str] = None


def _get_module_version() -> str:
    """
    获取模块版本号

    优先从 shared.version 导入，导入失败则回退到 tide_memory.__version__
    """
    global _module_version
    if _module_version is not None:
        return _module_version

    try:
        # 查找项目根目录并从 shared.version 导入
        from pathlib import Path
        current = Path(__file__).resolve()
        for _ in range(10):
            current = current.parent
            if (current / "shared" / "version.py").exists():
                import sys
                if str(current) not in sys.path:
                    sys.path.insert(0, str(current))
                from shared.version import SYSTEM_VERSION
                _module_version = SYSTEM_VERSION
                return _module_version
    except Exception:
        pass

    # 回退到本模块的 __version__
    try:
        from tide_memory import __version__
        _module_version = __version__
    except Exception:
        _module_version = "2.4.0-REV2"

    return _module_version


class M8Response:
    """M8 标准响应格式"""

    @staticmethod
    def success(data: Any = None, message: str = "success") -> Dict:
        return {
            "code": M8ErrorCode.SUCCESS,
            "message": message,
            "data": data,
            "request_id": M8Interface.generate_request_id(),
            "timestamp": datetime.now().isoformat(),
        }

    @staticmethod
    def error(code: M8ErrorCode, message: str = None, data: Any = None) -> Dict:
        return {
            "code": code.value,
            "message": message or code.name,
            "data": data,
            "request_id": M8Interface.generate_request_id(),
            "timestamp": datetime.now().isoformat(),
        }


class M8Interface:
    """
    M8 标准接口适配层
    
    提供符合M8规范的统一接口：
    - 标准错误码
    - 标准响应格式
    - 标准请求ID
    - 统一鉴权入口
    """

    _request_counter = 0

    @staticmethod
    def generate_request_id() -> str:
        """生成标准请求ID"""
        import uuid
        M8Interface._request_counter += 1
        return f"m5-{uuid.uuid4().hex[:12]}"

    def __init__(self, app_context: dict = None):
        self._app = app_context or {}
        self._router = None

    # === M8 标准接口 ===

    def m8_health_check(self) -> Dict:
        """M8标准：健康检查"""
        version = _get_module_version()
        return M8Response.success({
            "module": "m5-memory",
            "version": version,
            "status": "healthy",
            "features": [
                "four_layer_tidal_memory",
                "emotion_inference",
                "domain_isolation",
                "classification_marking",
                "sleep_consolidation",
                "audit_logging",
                "m8_compatible",
            ]
        })

    def m8_metrics(self, params: Dict = None) -> Dict:
        """
        M8标准：性能指标

        返回模块运行时的性能指标，包括CPU、内存、存储、条目数等。
        """
        try:
            cpu_usage = 0.0
            memory_mb = 0
            try:
                import psutil
                cpu_usage = psutil.cpu_percent(interval=0.1)
                memory_mb = int(psutil.Process(os.getpid()).memory_info().rss / 1024 / 1024)
            except Exception:
                pass

            memory_entries = 0
            storage_used_mb = 0
            vector_dim = 1536
            cache_hit_rate = 0.0

            try:
                config = self._app.get("config")
                if config:
                    layers = [
                        ("l1_shallow", config.get("memory.layers.l1_shallow.db_path", "./data/memory/l1_shallow.db")),
                        ("l2_deep", config.get("memory.layers.l2_deep.db_path", "./data/memory/l2_deep.db")),
                        ("l3_abyss", os.path.join(config.get("storage.l3_path", "./data/memory/abyss"), "index.db")),
                    ]
                else:
                    layers = [
                        ("l1_shallow", "./data/memory/l1_shallow.db"),
                        ("l2_deep", "./data/memory/l2_deep.db"),
                    ]

                import sqlite3
                for layer_name, db_path in layers:
                    if os.path.exists(db_path):
                        try:
                            storage_used_mb += int(os.path.getsize(db_path) / 1024 / 1024)
                            conn = sqlite3.connect(db_path)
                            cur = conn.execute("SELECT COUNT(*) FROM memories")
                            memory_entries += cur.fetchone()[0]
                            conn.close()
                        except Exception:
                            pass

                if config:
                    vector_dim = config.get("vector.dimension", 1536)
            except Exception:
                pass

            return M8Response.success({
                "cpu_usage": round(cpu_usage, 1),
                "memory_mb": memory_mb,
                "memory_entries": memory_entries,
                "vector_dim": vector_dim,
                "cache_hit_rate": round(cache_hit_rate, 3),
                "storage_used_mb": storage_used_mb,
            })
        except Exception as e:
            return M8Response.error(M8ErrorCode.INTERNAL_ERROR, str(e))

    def m8_config(self, params: Dict = None) -> Dict:
        """M8标准：配置查询"""
        version = _get_module_version()
        return M8Response.success({
            "module": "m5",
            "module_name": "潮汐记忆系统",
            "version": version,
            "levels": ["sensory", "short_term", "long_term"],
            "vector_enabled": True,
        })

    def m8_recall(self, params: Dict) -> Dict:
        """
        M8标准：记忆检索
        
        请求格式：
        {
            "query": "检索文本",
            "top_k": 10,
            "filters": {"domain": "private", "layer": ["l1", "l2"]},
            "context": {"emotion": {...}, "agent_id": "xxx"}
        }
        """
        try:
            query = params.get("query", "")
            if not query:
                return M8Response.error(M8ErrorCode.INVALID_PARAMS, "query is required")

            top_k = params.get("top_k", 10)
            filters = params.get("filters", {})
            context = params.get("context", {})

            skill_if = self._app.get("skill_interface")
            if not skill_if:
                return M8Response.error(M8ErrorCode.INTERNAL_ERROR, "service not initialized")

            result = skill_if.recall(
                query=query,
                layer_range=filters.get("layers"),
                emotion_context=context.get("emotion"),
                permission_check={
                    "agent_id": context.get("agent_id", "unknown"),
                    "domain": filters.get("domain", "private"),
                },
                top_k=top_k,
            )

            if not result.get("success"):
                if result.get("error") == "permission_denied":
                    return M8Response.error(M8ErrorCode.PERMISSION_DENIED)
                return M8Response.error(M8ErrorCode.UNKNOWN_ERROR, result.get("error", ""))

            return M8Response.success({
                "results": result.get("results", []),
                "total": result.get("total", 0),
                "query": query,
            })

        except Exception as e:
            return M8Response.error(M8ErrorCode.INTERNAL_ERROR, str(e))

    def m8_archive(self, params: Dict) -> Dict:
        """
        M8标准：记忆归档
        
        请求格式：
        {
            "content": "记忆内容（已加密）",
            "source": "conversation",
            "metadata": {"tags": [], "emotion": {...}}
        }
        """
        try:
            content = params.get("content", "")
            if not content:
                return M8Response.error(M8ErrorCode.INVALID_PARAMS, "content is required")

            metadata = params.get("metadata", {})
            context = params.get("context", {})

            skill_if = self._app.get("skill_interface")
            if not skill_if:
                return M8Response.error(M8ErrorCode.INTERNAL_ERROR, "service not initialized")

            result = skill_if.archive(
                content=content,
                source=params.get("source", "conversation"),
                domain=metadata.get("domain", "private"),
                agent_id=context.get("agent_id", "system"),
                tags=metadata.get("tags", []),
                emotion_context=metadata.get("emotion"),
                metadata=metadata.get("extra", {}),
            )

            if not result.get("success"):
                if result.get("error") == "permission_denied":
                    return M8Response.error(M8ErrorCode.PERMISSION_DENIED)
                return M8Response.error(M8ErrorCode.UNKNOWN_ERROR, result.get("error", ""))

            return M8Response.success({
                "memory_id": result.get("archive_id"),
                "layer": result.get("layer"),
                "content_hash": result.get("content_hash"),
                "created_at": result.get("created_at"),
            })

        except Exception as e:
            return M8Response.error(M8ErrorCode.INTERNAL_ERROR, str(e))

    def m8_get_stats(self, params: Dict = None) -> Dict:
        """M8标准：获取统计信息"""
        try:
            skill_if = self._app.get("skill_interface")
            if not skill_if:
                return M8Response.success({"total": 0, "layers": {}})
            
            stats = skill_if.get_stats(params.get("domain", "private") if params else "private")
            return M8Response.success(stats)
        except Exception as e:
            return M8Response.error(M8ErrorCode.INTERNAL_ERROR, str(e))

    def get_interface_spec(self) -> Dict:
        """获取M8接口规范定义"""
        version = _get_module_version()
        return {
            "module": "m5-memory",
            "version": version,
            "m8_version": "1.0",
            "endpoints": [
                {"name": "health", "method": "GET", "path": "/m8/health"},
                {"name": "metrics", "method": "GET", "path": "/m8/metrics"},
                {"name": "config", "method": "GET", "path": "/m8/config"},
                {"name": "recall", "method": "POST", "path": "/m8/memory/recall"},
                {"name": "archive", "method": "POST", "path": "/m8/memory/archive"},
                {"name": "stats", "method": "GET", "path": "/m8/memory/stats"},
            ],
            "error_codes": {e.name: e.value for e in M8ErrorCode},
        }
# vim: set et ts=4 sw=4:
