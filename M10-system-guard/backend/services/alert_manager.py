"""
云汐 M10 系统卫士 - A5 告警通知系统
负责告警生成、管理、确认和解决等功能
沙盒模式下使用模拟数据生成告警
"""

from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any

# 兼容相对导入和直接运行
try:
    from ..config import get_settings
    from ..mock_data_engine import get_mock_engine
    from ..database import get_session
    from ..models import Alert
except ImportError:
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from config import get_settings
    from mock_data_engine import get_mock_engine
    from database import get_session
    from models import Alert


class AlertManagerService:
    """
    告警通知系统
    提供告警查询、确认、解决和设置管理等功能
    """

    def __init__(self):
        """初始化告警管理服务"""
        self.settings = get_settings()
        self.mock_engine = get_mock_engine()
        # 告警设置
        self._alert_settings = {
            "enabled": True,
            "memory_warning_threshold": self.settings.memory_warning_threshold,
            "memory_danger_threshold": self.settings.memory_danger_threshold,
            "cpu_warning_threshold": self.settings.cpu_warning_threshold,
            "cpu_danger_threshold": self.settings.cpu_danger_threshold,
            "battery_warning_percent": self.settings.battery_warning_percent,
            "battery_critical_percent": self.settings.battery_critical_percent,
            "disk_warning_gb": self.settings.disk_warning_gb,
            "alert_suppression_minutes": self.settings.alert_suppression_minutes,
            "notification_channels": ["in_app", "desktop"],
            "quiet_hours_enabled": False,
            "quiet_hours_start": "23:00",
            "quiet_hours_end": "07:00",
        }
        # 初始化一些模拟告警
        self._init_mock_alerts()

    def _init_mock_alerts(self):
        """初始化模拟告警数据"""
        try:
            db = get_session()
            count = db.query(Alert).count()
            if count > 0:
                db.close()
                return

            # 插入一些历史告警
            now = datetime.now()
            mock_alerts = [
                {
                    "alert_type": "low_disk_space",
                    "level": "warning",
                    "title": "磁盘空间不足",
                    "message": "C盘剩余空间不足20GB，建议清理",
                    "metric_name": "disk_free_gb",
                    "metric_value": 18.5,
                    "threshold": 20.0,
                    "hours_ago": 12,
                    "acknowledged": True,
                    "resolved": False,
                },
                {
                    "alert_type": "high_cpu_temp",
                    "level": "warning",
                    "title": "CPU温度过高",
                    "message": "CPU温度达到88°C，已自动降频",
                    "metric_name": "cpu_temp",
                    "metric_value": 88.0,
                    "threshold": 85.0,
                    "hours_ago": 36,
                    "acknowledged": True,
                    "resolved": True,
                },
                {
                    "alert_type": "high_memory",
                    "level": "warning",
                    "title": "高内存使用率",
                    "message": "内存使用率达到82%，建议关闭部分程序",
                    "metric_name": "mem_percent",
                    "metric_value": 82.0,
                    "threshold": 80.0,
                    "hours_ago": 48,
                    "acknowledged": False,
                    "resolved": True,
                },
            ]

            for a in mock_alerts:
                alert_time = now - timedelta(hours=a["hours_ago"])
                alert = Alert(
                    alert_type=a["alert_type"],
                    level=a["level"],
                    title=a["title"],
                    message=a["message"],
                    metric_name=a["metric_name"],
                    metric_value=a["metric_value"],
                    threshold=a["threshold"],
                    created_at=alert_time,
                    acknowledged=a["acknowledged"],
                    acknowledged_at=alert_time + timedelta(minutes=5) if a["acknowledged"] else None,
                    resolved=a["resolved"],
                    resolved_at=alert_time + timedelta(hours=1) if a["resolved"] else None,
                    resolution_note="已自动恢复" if a["resolved"] else "",
                    source="system_monitor",
                )
                db.add(alert)
            db.commit()
            db.close()
        except Exception as e:
            print(f"[AlertManager] 初始化模拟告警失败: {e}")

    def get_alerts(self, level: Optional[str] = None,
                   resolved: Optional[bool] = None,
                   limit: int = 50,
                   offset: int = 0) -> Dict[str, Any]:
        """
        获取告警列表

        Args:
            level: 告警级别筛选（info/warning/critical/emergency）
            resolved: 是否已解决筛选
            limit: 返回数量限制
            offset: 偏移量

        Returns:
            告警列表和分页信息
        """
        try:
            db = get_session()
            query = db.query(Alert)

            if level:
                query = query.filter(Alert.level == level)
            if resolved is not None:
                query = query.filter(Alert.resolved == resolved)

            total = query.count()
            query = query.order_by(Alert.created_at.desc()).offset(offset).limit(limit)
            alerts = query.all()
            db.close()

            return {
                "total": total,
                "limit": limit,
                "offset": offset,
                "alerts": [a.to_dict() for a in alerts],
            }
        except Exception as e:
            print(f"[AlertManager] 获取告警列表失败: {e}")
            return {"total": 0, "limit": limit, "offset": offset, "alerts": []}

    def get_unresolved_count(self) -> Dict[str, Any]:
        """
        获取未解决告警数量

        Returns:
            各级别未解决告警数量统计
        """
        try:
            db = get_session()
            total = db.query(Alert).filter(Alert.resolved == False).count()
            info_count = db.query(Alert).filter(
                Alert.resolved == False, Alert.level == "info"
            ).count()
            warning_count = db.query(Alert).filter(
                Alert.resolved == False, Alert.level == "warning"
            ).count()
            critical_count = db.query(Alert).filter(
                Alert.resolved == False, Alert.level == "critical"
            ).count()
            emergency_count = db.query(Alert).filter(
                Alert.resolved == False, Alert.level == "emergency"
            ).count()
            unacknowledged = db.query(Alert).filter(
                Alert.resolved == False, Alert.acknowledged == False
            ).count()
            db.close()

            return {
                "total": total,
                "unacknowledged": unacknowledged,
                "by_level": {
                    "info": info_count,
                    "warning": warning_count,
                    "critical": critical_count,
                    "emergency": emergency_count,
                },
            }
        except Exception as e:
            print(f"[AlertManager] 获取未解决告警数失败: {e}")
            return {
                "total": 0,
                "unacknowledged": 0,
                "by_level": {"info": 0, "warning": 0, "critical": 0, "emergency": 0},
            }

    def acknowledge_alert(self, alert_id: int) -> bool:
        """
        确认告警

        Args:
            alert_id: 告警ID

        Returns:
            是否确认成功
        """
        try:
            db = get_session()
            alert = db.query(Alert).filter(Alert.id == alert_id).first()
            if not alert:
                db.close()
                return False

            alert.acknowledged = True
            alert.acknowledged_at = datetime.now()
            db.commit()
            db.close()
            return True
        except Exception as e:
            print(f"[AlertManager] 确认告警失败: {e}")
            return False

    def resolve_alert(self, alert_id: int, note: str = "") -> bool:
        """
        标记告警已解决

        Args:
            alert_id: 告警ID
            note: 解决说明

        Returns:
            是否解决成功
        """
        try:
            db = get_session()
            alert = db.query(Alert).filter(Alert.id == alert_id).first()
            if not alert:
                db.close()
                return False

            alert.resolved = True
            alert.resolved_at = datetime.now()
            alert.resolution_note = note or "已解决"
            if not alert.acknowledged:
                alert.acknowledged = True
                alert.acknowledged_at = datetime.now()
            db.commit()
            db.close()
            return True
        except Exception as e:
            print(f"[AlertManager] 解决告警失败: {e}")
            return False

    def get_alert_settings(self) -> Dict[str, Any]:
        """
        获取告警设置

        Returns:
            告警设置字典
        """
        return dict(self._alert_settings)

    def update_alert_settings(self, settings: Dict[str, Any]) -> Dict[str, Any]:
        """
        更新告警设置

        Args:
            settings: 新的设置项

        Returns:
            更新后的设置
        """
        for key, value in settings.items():
            if key in self._alert_settings:
                self._alert_settings[key] = value

        # 同步更新配置中的阈值
        if "memory_warning_threshold" in settings:
            self.settings.memory_warning_threshold = settings["memory_warning_threshold"]
        if "memory_danger_threshold" in settings:
            self.settings.memory_danger_threshold = settings["memory_danger_threshold"]
        if "cpu_warning_threshold" in settings:
            self.settings.cpu_warning_threshold = settings["cpu_warning_threshold"]
        if "cpu_danger_threshold" in settings:
            self.settings.cpu_danger_threshold = settings["cpu_danger_threshold"]

        return dict(self._alert_settings)

    def check_and_generate_alerts(self, metrics: Optional[dict] = None) -> List[dict]:
        """
        检查并生成告警（内部方法）

        Args:
            metrics: 系统指标数据

        Returns:
            新生成的告警列表
        """
        if metrics is None:
            metrics = self.mock_engine.generate_system_metrics()

        mock_alerts = self.mock_engine.generate_alerts(metrics)
        new_alerts = []

        try:
            db = get_session()
            for a in mock_alerts:
                # 检查抑制期内是否已有同类告警
                suppression_time = datetime.now() - timedelta(
                    minutes=self._alert_settings["alert_suppression_minutes"]
                )
                existing = db.query(Alert).filter(
                    Alert.alert_type == a["alert_type"],
                    Alert.created_at >= suppression_time,
                    Alert.resolved == False,
                ).first()

                if not existing:
                    alert = Alert(
                        alert_type=a["alert_type"],
                        level=a["level"],
                        title=a["title"],
                        message=a["message"],
                        metric_name=a.get("metric_name", ""),
                        metric_value=a.get("metric_value", 0),
                        threshold=a.get("threshold", 0),
                        source=a.get("source", "system_monitor"),
                        extra_data=a.get("extra_data", {}),
                    )
                    db.add(alert)
                    db.flush()
                    new_alerts.append(alert.to_dict())

            db.commit()
            db.close()
        except Exception as e:
            print(f"[AlertManager] 检查生成告警失败: {e}")

        return new_alerts

    def get_alert_statistics(self, days: int = 7) -> Dict[str, Any]:
        """
        获取告警统计数据

        Args:
            days: 统计天数

        Returns:
            统计数据字典
        """
        try:
            db = get_session()
            start_time = datetime.now() - timedelta(days=days)

            total = db.query(Alert).filter(Alert.created_at >= start_time).count()
            resolved = db.query(Alert).filter(
                Alert.created_at >= start_time, Alert.resolved == True
            ).count()

            # 按级别统计
            by_level = {}
            for level in ["info", "warning", "critical", "emergency"]:
                count = db.query(Alert).filter(
                    Alert.created_at >= start_time, Alert.level == level
                ).count()
                by_level[level] = count

            # 按类型统计
            by_type = {}
            alerts = db.query(Alert).filter(Alert.created_at >= start_time).all()
            for a in alerts:
                if a.alert_type not in by_type:
                    by_type[a.alert_type] = 0
                by_type[a.alert_type] += 1

            # 平均解决时间
            resolved_alerts = [a for a in alerts if a.resolved and a.created_at and a.resolved_at]
            if resolved_alerts:
                avg_resolve_minutes = sum(
                    (a.resolved_at - a.created_at).total_seconds() / 60
                    for a in resolved_alerts
                ) / len(resolved_alerts)
            else:
                avg_resolve_minutes = 0

            db.close()

            return {
                "period_days": days,
                "total_alerts": total,
                "resolved_count": resolved,
                "unresolved_count": total - resolved,
                "resolution_rate": round(resolved / total * 100, 1) if total > 0 else 0,
                "by_level": by_level,
                "by_type": by_type,
                "avg_resolution_minutes": round(avg_resolve_minutes, 1),
            }
        except Exception as e:
            print(f"[AlertManager] 获取告警统计失败: {e}")
            return {
                "period_days": days,
                "total_alerts": 0,
                "resolved_count": 0,
                "unresolved_count": 0,
                "resolution_rate": 0,
                "by_level": {},
                "by_type": {},
                "avg_resolution_minutes": 0,
            }


# 全局单例
_alert_manager: Optional[AlertManagerService] = None


def get_alert_manager() -> AlertManagerService:
    """获取告警管理服务单例"""
    global _alert_manager
    if _alert_manager is None:
        _alert_manager = AlertManagerService()
    return _alert_manager


# 兼容直接运行测试
if __name__ == "__main__":
    service = get_alert_manager()

    print("=== 告警统计 ===")
    stats = service.get_unresolved_count()
    print(f"未解决告警: {stats['total']}个")
    print(f"  信息: {stats['by_level']['info']}")
    print(f"  警告: {stats['by_level']['warning']}")
    print(f"  严重: {stats['by_level']['critical']}")

    print("\n=== 最近告警（前3个） ===")
    alerts = service.get_alerts(limit=3)
    for a in alerts["alerts"]:
        print(f"  [{a['level']}] {a['title']} - {a['message'][:50]}")

    print("\n=== 告警设置 ===")
    settings = service.get_alert_settings()
    print(f"告警启用: {settings['enabled']}")
    print(f"内存警告阈值: {settings['memory_warning_threshold']}%")
    print(f"抑制时间: {settings['alert_suppression_minutes']}分钟")
