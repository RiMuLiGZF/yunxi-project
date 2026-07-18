"""
M8 控制塔 - 运维状态聚合器（Ops Status Aggregator）

聚合所有模块的健康状态，提供：
- 系统整体健康评分
- 模块状态汇总
- 服务依赖图
- 容量规划建议
- 故障预测（基于趋势）

设计原则：
- 纯增量，不影响现有功能
- 线程安全，支持并发访问
- 缓存机制，避免频繁调用各模块
- 与 shared.health 模块深度集成
"""

import os
import sys
import time
import threading
from pathlib import Path
from typing import Dict, Any, Optional, List, Tuple
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from collections import deque

# 项目根路径
project_root = Path(__file__).parent.parent.parent.parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

from shared.health.health_checker import HealthStatus


# ============================================================================
# 数据类
# ============================================================================

@dataclass
class ModuleHealthSnapshot:
    """模块健康快照"""
    module_name: str
    status: HealthStatus = HealthStatus.UNHEALTHY
    score: int = 0
    uptime_seconds: float = 0
    last_check: float = 0
    checks: Dict[str, Any] = field(default_factory=dict)
    error: Optional[str] = None


@dataclass
class SystemHealthSummary:
    """系统整体健康摘要"""
    overall_status: HealthStatus = HealthStatus.UNHEALTHY
    overall_score: int = 0
    total_modules: int = 0
    healthy_modules: int = 0
    degraded_modules: int = 0
    unhealthy_modules: int = 0
    timestamp: str = ""
    uptime_seconds: float = 0


@dataclass
class CapacityRecommendation:
    """容量规划建议"""
    resource: str
    current_usage: float
    threshold: float
    recommendation: str
    severity: str  # info / warning / critical


@dataclass
class FailurePrediction:
    """故障预测"""
    module: str
    metric: str
    trend: str  # rising / falling / stable
    risk_level: str  # low / medium / high
    predicted_time: Optional[str] = None
    description: str = ""


# ============================================================================
# 运维状态聚合器
# ============================================================================

class OpsStatusAggregator:
    """
    运维状态聚合器

    负责收集、聚合和分析所有模块的健康状态数据。
    使用缓存机制减少对各模块的频繁调用。
    """

    # 模块定义（名称 -> 显示名称 + 端口）
    MODULES = {
        "gateway": {"name": "API网关", "port": 8080, "critical": True},
        "m0": {"name": "主控台", "port": 8000, "critical": True},
        "m1": {"name": "对话核心", "port": 8001, "critical": True},
        "m2": {"name": "技能集群", "port": 8002, "critical": False},
        "m3": {"name": "端云协同", "port": 8003, "critical": False},
        "m4": {"name": "场景引擎", "port": 8004, "critical": False},
        "m5": {"name": "潮汐记忆", "port": 8005, "critical": False},
        "m6": {"name": "硬件外设", "port": 8006, "critical": False},
        "m7": {"name": "工作流", "port": 8007, "critical": False},
        "m8": {"name": "控制塔", "port": 8008, "critical": True},
        "m9": {"name": "数据水晶", "port": 8009, "critical": False},
        "m10": {"name": "系统卫士", "port": 8010, "critical": False},
        "m11": {"name": "MCP总线", "port": 8011, "critical": False},
        "m12": {"name": "安全盾", "port": 8012, "critical": False},
    }

    def __init__(
        self,
        cache_ttl: int = 15,  # 缓存过期时间（秒）
        history_size: int = 100,  # 历史记录大小
        base_url_template: str = "http://localhost:{port}",
    ):
        self._cache_ttl = cache_ttl
        self._base_url_template = base_url_template
        self._lock = threading.Lock()

        # 模块健康快照缓存
        self._snapshots: Dict[str, ModuleHealthSnapshot] = {
            name: ModuleHealthSnapshot(module_name=name)
            for name in self.MODULES
        }

        # 历史记录（用于趋势分析）
        self._score_history: Dict[str, deque] = {
            name: deque(maxlen=history_size)
            for name in self.MODULES
        }

        # 系统启动时间
        self._start_time = time.time()

        # 部署历史
        self._deployments: List[Dict[str, Any]] = []

        # 后台刷新线程
        self._refresh_thread: Optional[threading.Thread] = None
        self._running = False

    # ---- 公共 API ----

    def get_dashboard_overview(self) -> Dict[str, Any]:
        """获取运维仪表盘总览数据"""
        with self._lock:
            summary = self._compute_summary()
            resource_usage = self._get_resource_usage()
            recent_alerts = self._get_recent_alerts()

            return {
                "summary": {
                    "overall_status": summary.overall_status.value,
                    "overall_score": summary.overall_score,
                    "total_modules": summary.total_modules,
                    "healthy_modules": summary.healthy_modules,
                    "degraded_modules": summary.degraded_modules,
                    "unhealthy_modules": summary.unhealthy_modules,
                    "uptime_seconds": round(time.time() - self._start_time, 2),
                    "timestamp": datetime.now().isoformat(),
                },
                "resources": resource_usage,
                "recent_alerts": recent_alerts[:5],
                "deployments": len(self._deployments),
            }

    def get_module_list(self) -> List[Dict[str, Any]]:
        """获取模块状态列表"""
        with self._lock:
            result = []
            for name, info in self.MODULES.items():
                snap = self._snapshots.get(name)
                result.append({
                    "name": name,
                    "display_name": info["name"],
                    "port": info["port"],
                    "critical": info["critical"],
                    "status": snap.status.value if snap else "unknown",
                    "score": snap.score if snap else 0,
                    "uptime_seconds": round(snap.uptime_seconds, 2) if snap else 0,
                    "last_check": datetime.fromtimestamp(snap.last_check).isoformat() if snap and snap.last_check else None,
                })
            return result

    def get_module_detail(self, module_name: str) -> Optional[Dict[str, Any]]:
        """获取模块详情"""
        with self._lock:
            if module_name not in self.MODULES:
                return None

            info = self.MODULES[module_name]
            snap = self._snapshots.get(module_name)

            # 获取历史趋势
            history = list(self._score_history.get(module_name, []))

            return {
                "name": module_name,
                "display_name": info["name"],
                "port": info["port"],
                "critical": info["critical"],
                "status": snap.status.value if snap else "unknown",
                "score": snap.score if snap else 0,
                "uptime_seconds": round(snap.uptime_seconds, 2) if snap else 0,
                "last_check": datetime.fromtimestamp(snap.last_check).isoformat() if snap and snap.last_check else None,
                "checks": snap.checks if snap else {},
                "error": snap.error if snap else None,
                "score_history": history[-20:],  # 最近20条
            }

    def get_resource_usage(self) -> Dict[str, Any]:
        """获取资源使用情况"""
        return self._get_resource_usage()

    def get_capacity_recommendations(self) -> List[CapacityRecommendation]:
        """获取容量规划建议"""
        recommendations = []
        try:
            import psutil

            # CPU 建议
            cpu_percent = psutil.cpu_percent(interval=0.1)
            if cpu_percent > 80:
                recommendations.append(CapacityRecommendation(
                    resource="cpu",
                    current_usage=cpu_percent,
                    threshold=80.0,
                    recommendation="CPU使用率较高，建议扩容或优化高CPU消耗模块",
                    severity="warning" if cpu_percent < 90 else "critical",
                ))
            elif cpu_percent < 20:
                recommendations.append(CapacityRecommendation(
                    resource="cpu",
                    current_usage=cpu_percent,
                    threshold=20.0,
                    recommendation="CPU使用率较低，资源有富余",
                    severity="info",
                ))

            # 内存建议
            mem = psutil.virtual_memory()
            if mem.percent > 85:
                recommendations.append(CapacityRecommendation(
                    resource="memory",
                    current_usage=mem.percent,
                    threshold=85.0,
                    recommendation="内存使用率较高，建议增加内存或优化内存占用",
                    severity="warning" if mem.percent < 95 else "critical",
                ))

            # 磁盘建议
            import shutil
            usage = shutil.disk_usage(".")
            disk_percent = (usage.used / usage.total) * 100
            if disk_percent > 85:
                recommendations.append(CapacityRecommendation(
                    resource="disk",
                    current_usage=round(disk_percent, 2),
                    threshold=85.0,
                    recommendation="磁盘使用率较高，建议清理日志或扩容",
                    severity="warning" if disk_percent < 95 else "critical",
                ))

        except ImportError:
            pass

        return recommendations

    def get_failure_predictions(self) -> List[FailurePrediction]:
        """获取故障预测（基于趋势）"""
        predictions = []

        with self._lock:
            for module_name, history in self._score_history.items():
                if len(history) < 5:
                    continue

                # 简单趋势分析：最近分数持续下降
                recent = list(history)[-10:]
                if len(recent) < 5:
                    continue

                # 计算趋势
                first_half = sum(recent[:len(recent)//2]) / (len(recent)//2)
                second_half = sum(recent[len(recent)//2:]) / (len(recent) - len(recent)//2)
                diff = first_half - second_half

                if diff > 10:  # 下降超过10分
                    risk = "high" if diff > 25 else ("medium" if diff > 15 else "low")
                    predictions.append(FailurePrediction(
                        module=module_name,
                        metric="health_score",
                        trend="falling",
                        risk_level=risk,
                        description=f"{module_name} 健康评分呈下降趋势，近期下降约 {diff:.1f} 分",
                    ))

        return predictions

    def get_service_dependency_graph(self) -> Dict[str, Any]:
        """获取服务依赖图"""
        # 定义依赖关系
        dependencies = {
            "gateway": ["m0", "m1", "m2", "m3", "m4", "m5", "m6", "m7", "m8", "m9", "m10", "m11", "m12"],
            "m0": ["m1", "m8"],
            "m1": ["m2", "m4", "m5", "m8"],
            "m2": ["m8"],
            "m4": ["m5", "m8"],
            "m5": ["m8"],
            "m7": ["m1", "m2", "m8"],
            "m8": ["redis"],
            "m9": ["m8"],
            "m10": ["m8"],
            "m11": ["m8"],
            "m12": ["m8"],
        }

        nodes = []
        edges = []

        with self._lock:
            for name, info in self.MODULES.items():
                snap = self._snapshots.get(name)
                nodes.append({
                    "id": name,
                    "label": info["name"],
                    "status": snap.status.value if snap else "unknown",
                    "score": snap.score if snap else 0,
                    "critical": info["critical"],
                })

            # 添加基础设施节点
            nodes.append({"id": "redis", "label": "Redis", "status": "unknown", "score": 0, "critical": True})

            for source, targets in dependencies.items():
                for target in targets:
                    edges.append({"source": source, "target": target})

        return {"nodes": nodes, "edges": edges}

    # ---- 部署管理 ----

    def get_deployments(self, limit: int = 20) -> List[Dict[str, Any]]:
        """获取部署历史"""
        with self._lock:
            return list(reversed(self._deployments))[:limit]

    def record_deployment(self, module: str, version: str, status: str = "success") -> None:
        """记录部署事件"""
        with self._lock:
            self._deployments.append({
                "id": f"deploy-{int(time.time())}",
                "module": module,
                "version": version,
                "status": status,
                "timestamp": datetime.now().isoformat(),
            })
            # 限制历史记录数量
            if len(self._deployments) > 100:
                self._deployments = self._deployments[-100:]

    def trigger_deploy(self, module: str) -> Dict[str, Any]:
        """触发部署（预留接口）"""
        # 这是一个预留接口，实际部署逻辑需要根据具体部署方式实现
        return {
            "module": module,
            "status": "scheduled",
            "message": f"模块 {module} 的部署任务已排入队列（预留接口）",
            "deploy_id": f"deploy-{int(time.time())}",
        }

    # ---- 刷新机制 ----

    def refresh_all(self) -> None:
        """刷新所有模块的健康状态"""
        for module_name in self.MODULES:
            self._refresh_module(module_name)

    def start_background_refresh(self, interval: int = 30) -> None:
        """启动后台刷新线程"""
        if self._running:
            return
        self._running = True
        self._refresh_thread = threading.Thread(
            target=self._background_loop,
            args=(interval,),
            daemon=True,
        )
        self._refresh_thread.start()

    def stop_background_refresh(self) -> None:
        """停止后台刷新线程"""
        self._running = False
        if self._refresh_thread:
            self._refresh_thread.join(timeout=5)

    # ---- 内部方法 ----

    def _background_loop(self, interval: int) -> None:
        """后台刷新循环"""
        while self._running:
            try:
                self.refresh_all()
            except Exception:
                pass
            # 分段 sleep，便于快速停止
            for _ in range(interval):
                if not self._running:
                    break
                time.sleep(1)

    def _refresh_module(self, module_name: str) -> None:
        """刷新单个模块的健康状态"""
        info = self.MODULES.get(module_name)
        if not info:
            return

        port = info["port"]
        base_url = self._base_url_template.format(port=port)

        try:
            import httpx
            # 调用模块的健康端点
            with httpx.Client(timeout=3.0) as client:
                resp = client.get(f"{base_url}/health")
                if resp.status_code == 200:
                    data = resp.json()
                    # 兼容新旧两种格式
                    status_str = data.get("status", "unknown")
                    score = data.get("score", 0)
                    uptime = data.get("uptime_seconds", 0)
                    checks = data.get("checks", {})

                    try:
                        status = HealthStatus(status_str)
                    except ValueError:
                        status = HealthStatus.DEGRADED

                    with self._lock:
                        snap = self._snapshots.get(module_name)
                        if snap:
                            snap.status = status
                            snap.score = score
                            snap.uptime_seconds = uptime
                            snap.last_check = time.time()
                            snap.checks = checks
                            snap.error = None

                        # 记录历史
                        self._score_history[module_name].append(score)
                else:
                    self._mark_module_unhealthy(module_name, f"HTTP {resp.status_code}")
        except Exception as e:
            self._mark_module_unhealthy(module_name, str(e))

    def _mark_module_unhealthy(self, module_name: str, error: str) -> None:
        """标记模块为不健康"""
        with self._lock:
            snap = self._snapshots.get(module_name)
            if snap:
                snap.status = HealthStatus.UNHEALTHY
                snap.score = 0
                snap.last_check = time.time()
                snap.error = error
            self._score_history[module_name].append(0)

    def _compute_summary(self) -> SystemHealthSummary:
        """计算系统整体健康摘要"""
        healthy = 0
        degraded = 0
        unhealthy = 0
        total_score = 0
        count = 0

        for name, snap in self._snapshots.items():
            if snap.status == HealthStatus.HEALTHY:
                healthy += 1
            elif snap.status == HealthStatus.DEGRADED:
                degraded += 1
            else:
                unhealthy += 1
            total_score += snap.score
            count += 1

        # 计算整体状态
        critical_modules = [
            name for name, info in self.MODULES.items() if info["critical"]
        ]
        critical_unhealthy = any(
            self._snapshots[m].status == HealthStatus.UNHEALTHY
            for m in critical_modules
        )

        if critical_unhealthy or unhealthy > len(self.MODULES) * 0.3:
            overall_status = HealthStatus.UNHEALTHY
        elif degraded > 0 or unhealthy > 0:
            overall_status = HealthStatus.DEGRADED
        else:
            overall_status = HealthStatus.HEALTHY

        avg_score = total_score // count if count > 0 else 0

        return SystemHealthSummary(
            overall_status=overall_status,
            overall_score=avg_score,
            total_modules=count,
            healthy_modules=healthy,
            degraded_modules=degraded,
            unhealthy_modules=unhealthy,
            timestamp=datetime.now().isoformat(),
            uptime_seconds=time.time() - self._start_time,
        )

    def _get_resource_usage(self) -> Dict[str, Any]:
        """获取资源使用情况"""
        result = {
            "cpu": {"percent": 0, "cores": 0},
            "memory": {"total_mb": 0, "used_mb": 0, "percent": 0},
            "disk": {"total_gb": 0, "used_gb": 0, "percent": 0},
        }

        try:
            import psutil

            result["cpu"] = {
                "percent": psutil.cpu_percent(interval=0.1),
                "cores": psutil.cpu_count(),
                "load_avg": list(os.getloadavg()) if hasattr(os, 'getloadavg') else [0, 0, 0],
            }

            mem = psutil.virtual_memory()
            result["memory"] = {
                "total_mb": round(mem.total / (1024 * 1024), 2),
                "used_mb": round(mem.used / (1024 * 1024), 2),
                "available_mb": round(mem.available / (1024 * 1024), 2),
                "percent": mem.percent,
            }

            import shutil
            usage = shutil.disk_usage(".")
            result["disk"] = {
                "total_gb": round(usage.total / (1024 ** 3), 2),
                "used_gb": round(usage.used / (1024 ** 3), 2),
                "free_gb": round(usage.free / (1024 ** 3), 2),
                "percent": round((usage.used / usage.total) * 100, 2),
            }
        except ImportError:
            pass

        return result

    def _get_recent_alerts(self) -> List[Dict[str, Any]]:
        """获取最近告警（尝试从告警引擎获取）"""
        try:
            from shared.core.observability import get_alert_engine
            alert_engine = get_alert_engine()
            alerts = alert_engine.get_active_alerts()
            return [
                {
                    "id": a.get("id", ""),
                    "level": a.get("severity", "info"),
                    "title": a.get("name", ""),
                    "message": a.get("message", ""),
                    "source": a.get("source", ""),
                    "created_at": a.get("created_at", ""),
                }
                for a in alerts[:10]
            ]
        except Exception:
            return []

    # ---- 系统配置概览 ----

    def get_system_config_overview(self) -> Dict[str, Any]:
        """获取系统配置概览"""
        import os

        return {
            "system": {
                "version": _get_system_version(),
                "environment": os.environ.get("YUNXI_ENV", "development"),
                "modules": len(self.MODULES),
                "start_time": datetime.fromtimestamp(self._start_time).isoformat(),
            },
            "modules": {
                name: {
                    "name": info["name"],
                    "port": info["port"],
                    "critical": info["critical"],
                    "enabled": True,
                }
                for name, info in self.MODULES.items()
            },
            "features": {
                "docker_support": True,
                "health_check": True,
                "monitoring": True,
                "backup": True,
                "alerting": True,
                "logging": True,
            },
        }


def _get_system_version() -> str:
    """获取系统版本号"""
    try:
        from shared.core.version import SYSTEM_VERSION
        return SYSTEM_VERSION
    except ImportError:
        pass
    try:
        version_file = project_root / "VERSION"
        if version_file.exists():
            return version_file.read_text().strip()
    except Exception:
        pass
    return "unknown"


# ============================================================================
# 单例
# ============================================================================

_aggregator: Optional[OpsStatusAggregator] = None
_aggregator_lock = threading.Lock()


def get_ops_aggregator() -> OpsStatusAggregator:
    """获取运维状态聚合器单例"""
    global _aggregator
    if _aggregator is None:
        with _aggregator_lock:
            if _aggregator is None:
                _aggregator = OpsStatusAggregator()
    return _aggregator
