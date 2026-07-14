"""
M8 标准接口适配层

M5 潮汐记忆系统对接 M8 标准接口规范
所有对外接口遵循 M8 统一错误码和响应格式

错误码统一说明：
    错误码唯一来源为 tide_memory.errors.ErrorCode，
    M8ErrorCode 作为向后兼容别名，映射到同一枚举。
"""

from __future__ import annotations

import os
from typing import Any, Dict, Optional
from datetime import datetime

import structlog

from ..core.version import get_module_version
from ..common.errors import ErrorCode

# 向后兼容别名：外部模块可继续通过 M8ErrorCode 引用错误码
M8ErrorCode = ErrorCode

logger = structlog.get_logger(__name__)


class M8Response:
    """M8 标准响应格式"""

    @staticmethod
    def success(data: Any = None, message: str = "success") -> Dict[str, Any]:
        return {
            "code": ErrorCode.SUCCESS,
            "message": message,
            "data": data,
            "request_id": M8Interface.generate_request_id(),
            "timestamp": datetime.now().isoformat(),
        }

    @staticmethod
    def error(code: ErrorCode, message: str = None, data: Any = None) -> Dict:
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
    - 标准错误码（统一来源：ErrorCode）
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

    def __init__(self, app_context: dict = None) -> None:
        self._app = app_context or {}
        self._router = None

    # === M8 标准接口 ===

    def m8_health_check(self) -> Dict:
        """M8标准：健康检查"""
        version = get_module_version()
        logger.debug("m8_health_check_executed", module="m5-memory", version=version)
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

    def m8_metrics(self, params: Dict[str, Any] = None) -> Dict[str, Any]:
        """
        M8标准：性能指标

        返回潮汐系统运行时的性能指标，包括记忆条数、各层数量、EI模型状态、潮汐相位等。
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

            # 通过 skill_interface 获取各层统计
            layer_counts = {}
            total_entries = 0
            keyword_index_stats = {}
            vector_index_stats = {}
            cache_stats = {}
            try:
                skill_if = self._app.get("skill_interface")
                if skill_if:
                    stats = skill_if.get_stats(domain="private")
                    total_entries = stats.get("total", 0)
                    layer_stats = stats.get("layers", {})
                    for layer_name, layer_data in layer_stats.items():
                        if isinstance(layer_data, dict):
                            layer_counts[layer_name] = layer_data.get("count", 0)
                        else:
                            layer_counts[layer_name] = layer_data
                    # 补充缺失的层级
                    for name in ["l0_beach", "l1_shallow", "l2_deep", "l3_abyss"]:
                        if name not in layer_counts:
                            layer_counts[name] = 0
                    keyword_index_stats = stats.get("keyword_index", {})
                    vector_index_stats = stats.get("vector_index", {})
                    cache_stats = stats.get("cache", {})
            except Exception as e:
                logger.warning("m8_metrics_layer_stats_failed", error=str(e))

            # 存储占用估算
            storage_used_mb = 0
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

                for layer_name, db_path in layers:
                    if os.path.exists(db_path):
                        try:
                            storage_used_mb += int(os.path.getsize(db_path) / 1024 / 1024)
                        except Exception:
                            pass
            except Exception as e:
                logger.warning("m8_metrics_storage_failed", error=str(e))

            # EI 模型状态
            ei_status = {"available": False, "history_samples": 0, "trend": "insufficient_data"}
            try:
                ei_engine = self._app.get("emotion")
                if ei_engine and hasattr(ei_engine, "get_history") and hasattr(ei_engine, "get_trend"):
                    history = ei_engine.get_history()
                    trend = ei_engine.get_trend()
                    ei_status = {
                        "available": True,
                        "history_samples": len(history),
                        "trend": trend.get("trend", "insufficient_data"),
                        "avg_ei": trend.get("avg_ei", 0.0),
                    }
            except Exception as e:
                logger.warning("m8_metrics_ei_status_failed", error=str(e))

            # 潮汐相位状态
            phase_status = {"current": "unknown", "auto_switch": False}
            try:
                phase_controller = self._app.get("phase_controller")
                if phase_controller and hasattr(phase_controller, "get_stats"):
                    pstats = phase_controller.get_stats()
                    phase_status = {
                        "current": pstats.get("current_phase", "unknown"),
                        "auto_switch": pstats.get("auto_switch", False),
                        "switch_count": pstats.get("switch_count", 0),
                        "current_duration_seconds": pstats.get("current_duration_seconds", 0),
                    }
            except Exception as e:
                logger.warning("m8_metrics_phase_status_failed", error=str(e))

            # 向量维度
            vector_dim = 1536
            try:
                config = self._app.get("config")
                if config:
                    vector_dim = config.get("vector.dimension", 1536)
            except Exception:
                pass

            return M8Response.success({
                "module": "m5-memory",
                "cpu_usage": round(cpu_usage, 1),
                "memory_mb": memory_mb,
                "total_entries": total_entries,
                "layer_counts": layer_counts,
                "vector_dim": vector_dim,
                "storage_used_mb": storage_used_mb,
                "ei_model": ei_status,
                "tide_phase": phase_status,
                "keyword_index": keyword_index_stats,
                "vector_index": vector_index_stats,
                "cache": cache_stats,
            })
        except Exception as e:
            logger.error("m8_metrics_failed", error=str(e))
            return M8Response.error(ErrorCode.INTERNAL_ERROR, str(e))

    def m8_config(self, params: Dict = None) -> Dict:
        """
        M8标准：配置查询

        返回潮汐系统的完整配置信息（已脱敏）。
        """
        try:
            version = get_module_version()
            config_dict = {}
            try:
                config = self._app.get("config")
                if config and hasattr(config, "to_dict"):
                    config_dict = config.to_dict()
                elif config and hasattr(config, "_config"):
                    # 兼容旧版直接访问内部字典
                    import copy
                    config_dict = copy.deepcopy(config._config)
            except Exception as e:
                logger.warning("m8_config_load_failed", error=str(e))

            return M8Response.success({
                "module": "m5-memory",
                "module_name": "潮汐记忆系统",
                "version": version,
                "levels": ["sensory", "short_term", "long_term"],
                "vector_enabled": True,
                "config": config_dict,
            })
        except Exception as e:
            logger.error("m8_config_failed", error=str(e))
            return M8Response.error(ErrorCode.INTERNAL_ERROR, str(e))

    def m8_recall(self, params: Dict[str, Any]) -> Dict[str, Any]:
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
                return M8Response.error(ErrorCode.INVALID_PARAMS, "query is required")

            top_k = params.get("top_k", 10)
            filters = params.get("filters", {})
            context = params.get("context", {})

            skill_if = self._app.get("skill_interface")
            if not skill_if:
                return M8Response.error(ErrorCode.INTERNAL_ERROR, "service not initialized")

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
                    return M8Response.error(ErrorCode.PERMISSION_DENIED)
                return M8Response.error(ErrorCode.UNKNOWN_ERROR, result.get("error", ""))

            return M8Response.success({
                "results": result.get("results", []),
                "total": result.get("total", 0),
                "query": query,
            })

        except Exception as e:
            logger.error("m8_recall_failed", error=str(e))
            return M8Response.error(ErrorCode.INTERNAL_ERROR, str(e))

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
                return M8Response.error(ErrorCode.INVALID_PARAMS, "content is required")

            metadata = params.get("metadata", {})
            context = params.get("context", {})

            skill_if = self._app.get("skill_interface")
            if not skill_if:
                return M8Response.error(ErrorCode.INTERNAL_ERROR, "service not initialized")

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
                    return M8Response.error(ErrorCode.PERMISSION_DENIED)
                return M8Response.error(ErrorCode.UNKNOWN_ERROR, result.get("error", ""))

            return M8Response.success({
                "memory_id": result.get("archive_id"),
                "layer": result.get("layer"),
                "content_hash": result.get("content_hash"),
                "created_at": result.get("created_at"),
            })

        except Exception as e:
            logger.error("m8_archive_failed", error=str(e))
            return M8Response.error(ErrorCode.INTERNAL_ERROR, str(e))

    def m8_get_stats(self, params: Dict = None) -> Dict:
        """M8标准：获取统计信息"""
        try:
            skill_if = self._app.get("skill_interface")
            if not skill_if:
                return M8Response.success({"total": 0, "layers": {}})

            stats = skill_if.get_stats(params.get("domain", "private") if params else "private")
            return M8Response.success(stats)
        except Exception as e:
            logger.error("m8_get_stats_failed", error=str(e))
            return M8Response.error(ErrorCode.INTERNAL_ERROR, str(e))

    def get_interface_spec(self) -> Dict[str, Any]:
        """获取M8接口规范定义"""
        version = get_module_version()
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
            "error_codes": {e.name: e.value for e in ErrorCode},
        }
# vim: set et ts=4 sw=4:
