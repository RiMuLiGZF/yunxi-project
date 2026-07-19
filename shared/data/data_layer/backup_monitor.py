"""
云汐备份监控告警系统（第四阶段生产就绪）

提供备份系统的监控和告警能力：
- 备份失败告警
- 备份存储空间监控
- 备份过期提醒
- 恢复演练定期提醒
- 告警记录与查询

使用方式：
    from backup_monitor import BackupMonitor, AlertLevel, AlertType

    monitor = BackupMonitor()
    monitor.check_all()
    alerts = monitor.get_active_alerts()
"""

import sys
import json
import time
import shutil
import hashlib
import logging
from pathlib import Path
from datetime import datetime, timedelta
from dataclasses import dataclass, field, asdict
from typing import List, Dict, Any, Optional, Callable

logger = logging.getLogger(__name__)

# 导入备份管理器
_data_layer_dir = Path(__file__).parent
sys.path.insert(0, str(_data_layer_dir))

from backup_manager import (
    BackupManager,
    BackupReport,
    VerifyReport,
    StorageBackendType,
)
from module_backup_registry import (
    get_all_module_configs,
    get_module_backup_summary,
    get_modules_with_db,
)


# ============================================================
# 告警类型与级别
# ============================================================

class AlertType:
    """告警类型"""
    BACKUP_FAILURE = "backup_failure"           # 备份失败
    STORAGE_HIGH = "storage_high"               # 存储空间高
    STORAGE_CRITICAL = "storage_critical"       # 存储空间严重
    BACKUP_STALE = "backup_stale"               # 备份过期
    BACKUP_CORRUPTED = "backup_corrupted"       # 备份损坏
    DRILL_OVERDUE = "drill_overdue"             # 演练超期
    CONFIG_ERROR = "config_error"               # 配置错误


class AlertLevel:
    """告警级别"""
    INFO = "info"           # 通知
    WARNING = "warning"     # 警告
    CRITICAL = "critical"   # 严重


# ============================================================
# 告警数据类
# ============================================================

@dataclass
class Alert:
    """告警记录"""
    alert_id: str
    alert_type: str
    level: str
    module_id: str
    message: str
    details: Dict[str, Any] = field(default_factory=dict)
    created_at: float = 0.0
    resolved: bool = False
    resolved_at: float = 0.0
    resolution_note: str = ""

    def __post_init__(self):
        if not self.created_at:
            self.created_at = time.time()
        if not self.alert_id:
            self.alert_id = self._generate_id()

    def _generate_id(self) -> str:
        """生成告警ID"""
        raw = f"{self.alert_type}_{self.module_id}_{int(self.created_at)}"
        return hashlib.md5(raw.encode()).hexdigest()[:12]


@dataclass
class MonitorReport:
    """监控报告"""
    timestamp: float = 0.0
    total_modules: int = 0
    healthy_modules: int = 0
    problematic_modules: int = 0
    total_backups: int = 0
    total_size_bytes: int = 0
    storage_usage_percent: float = 0.0
    alerts: List[Alert] = field(default_factory=list)
    module_status: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        if not self.timestamp:
            self.timestamp = time.time()

    @property
    def critical_alerts(self) -> List[Alert]:
        return [a for a in self.alerts if a.level == AlertLevel.CRITICAL]

    @property
    def warning_alerts(self) -> List[Alert]:
        return [a for a in self.alerts if a.level == AlertLevel.WARNING]

    @property
    def overall_healthy(self) -> bool:
        return len(self.critical_alerts) == 0 and len(self.warning_alerts) == 0


# ============================================================
# 监控阈值配置
# ============================================================

@dataclass
class MonitorConfig:
    """监控配置"""
    # 存储阈值
    storage_warning_percent: float = 80.0      # 存储警告阈值（%）
    storage_critical_percent: float = 90.0     # 存储严重阈值（%）

    # 备份过期阈值（小时）
    backup_stale_hours: int = 28               # 备份过期时间（比每日多4小时缓冲）

    # 恢复演练提醒（天）
    drill_reminder_days: int = 30              # 月度演练提醒
    drill_quarterly_days: int = 90             # 季度演练提醒
    drill_yearly_days: int = 180               # 半年全系统演练提醒

    # 连续失败告警
    consecutive_failure_threshold: int = 1     # 连续失败几次告警

    # 告警文件路径
    alerts_file: str = ""                      # 告警记录文件

    def __post_init__(self):
        if not self.alerts_file:
            project_root = Path(__file__).parent.parent.parent.parent
            self.alerts_file = str(project_root / "backups" / "monitoring" / "alerts.json")


# ============================================================
# 备份监控器
# ============================================================

class BackupMonitor:
    """备份监控告警器

    第四阶段生产就绪增强：
    - 备份失败告警
    - 备份存储空间监控
    - 备份过期提醒
    - 恢复演练定期提醒
    - 告警持久化
    """

    def __init__(self, config: Optional[MonitorConfig] = None,
                 backup_manager: Optional[BackupManager] = None):
        """
        初始化备份监控器

        Args:
            config: 监控配置
            backup_manager: 备份管理器实例
        """
        self.config = config or MonitorConfig()
        self.bm = backup_manager or BackupManager()

        # 告警回调
        self._alert_callbacks: List[Callable[[Alert], None]] = []

        # 告警存储
        self._alerts: List[Alert] = []
        self._load_alerts()

    # --------------------------------------------------------
    # 告警回调管理
    # --------------------------------------------------------

    def add_alert_callback(self, callback: Callable[[Alert], None]) -> None:
        """添加告警回调函数"""
        self._alert_callbacks.append(callback)

    def add_webhook(self, url: str) -> None:
        """添加 Webhook 告警地址"""
        def webhook_callback(alert: Alert):
            try:
                import httpx
                payload = {
                    "alert_id": alert.alert_id,
                    "type": alert.alert_type,
                    "level": alert.level,
                    "module": alert.module_id,
                    "message": alert.message,
                    "details": alert.details,
                    "timestamp": alert.created_at,
                }
                httpx.post(url, json=payload, timeout=5.0)
            except Exception as e:
                # Webhook 告警推送失败不影响主流程，记录警告以便排查
                logger.warning("备份告警 Webhook 推送失败 %s: %s", url, e)

        self._alert_callbacks.append(webhook_callback)

    def _trigger_alert(self, alert: Alert) -> None:
        """触发告警"""
        # 检查是否已有未解决的同类告警（避免重复）
        existing = [
            a for a in self._alerts
            if not a.resolved
            and a.alert_type == alert.alert_type
            and a.module_id == alert.module_id
        ]
        if existing:
            return  # 已有未解决的同类告警，不重复触发

        self._alerts.append(alert)
        self._save_alerts()

        # 调用回调
        for callback in self._alert_callbacks:
            try:
                callback(alert)
            except Exception as e:
                # 单个告警回调失败不影响其他回调执行
                logger.warning("告警回调执行失败: %s", e, exc_info=True)

    # --------------------------------------------------------
    # 告警持久化
    # --------------------------------------------------------

    def _load_alerts(self) -> None:
        """加载告警记录"""
        try:
            alerts_path = Path(self.config.alerts_file)
            if not alerts_path.exists():
                return
            with open(alerts_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            self._alerts = [Alert(**item) for item in data.get("alerts", [])]
        except Exception:
            self._alerts = []

    def _save_alerts(self) -> None:
        """保存告警记录"""
        try:
            alerts_path = Path(self.config.alerts_file)
            alerts_path.parent.mkdir(parents=True, exist_ok=True)
            data = {
                "updated_at": time.time(),
                "total_alerts": len(self._alerts),
                "alerts": [asdict(a) for a in self._alerts[-500:]],  # 保留最近500条
            }
            with open(alerts_path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
        except Exception as e:
            # 告警持久化失败不影响监控逻辑，但需要记录以便排查
            logger.warning("保存告警记录失败: %s", e)

    # --------------------------------------------------------
    # 全面检查
    # --------------------------------------------------------

    def check_all(self) -> MonitorReport:
        """执行全面监控检查

        Returns:
            监控报告
        """
        report = MonitorReport()

        # 获取所有模块配置
        configs = get_all_module_configs()
        report.total_modules = len(configs)

        # 存储检查
        storage_check = self._check_storage()
        if not storage_check["ok"]:
            for alert in storage_check.get("alerts", []):
                report.alerts.append(alert)
                self._trigger_alert(alert)

        # 各模块检查
        for module_id in sorted(configs.keys()):
            status = self._check_module(module_id, configs[module_id])
            report.module_status[module_id] = status

            if status["healthy"]:
                report.healthy_modules += 1
            else:
                report.problematic_modules += 1
                for alert in status.get("alerts", []):
                    report.alerts.append(alert)
                    self._trigger_alert(alert)

        # 统计信息
        stats = self.bm.get_backup_stats()
        report.total_backups = stats.get("total_backups", 0)
        report.total_size_bytes = stats.get("total_size_bytes", 0)

        storage = self.bm.get_storage_usage()
        if "disk_free_percent" in storage:
            report.storage_usage_percent = round(
                100 - storage["disk_free_percent"], 2
            )

        # 演练提醒检查
        drill_alerts = self._check_drill_reminders()
        for alert in drill_alerts:
            report.alerts.append(alert)
            self._trigger_alert(alert)

        return report

    # --------------------------------------------------------
    # 存储检查
    # --------------------------------------------------------

    def _check_storage(self) -> Dict[str, Any]:
        """检查存储空间使用情况"""
        result = {"ok": True, "alerts": []}

        try:
            storage = self.bm.get_storage_usage()
            if "error" in storage:
                result["ok"] = False
                result["alerts"].append(Alert(
                    alert_id="",
                    alert_type=AlertType.CONFIG_ERROR,
                    level=AlertLevel.WARNING,
                    module_id="system",
                    message="无法获取存储使用信息",
                    details={"error": storage["error"]},
                ))
                return result

            used_percent = 100 - storage.get("disk_free_percent", 100)

            if used_percent >= self.config.storage_critical_percent:
                result["ok"] = False
                result["alerts"].append(Alert(
                    alert_id="",
                    alert_type=AlertType.STORAGE_CRITICAL,
                    level=AlertLevel.CRITICAL,
                    module_id="system",
                    message=f"备份存储空间严重不足: {used_percent:.1f}% 已使用",
                    details={
                        "used_percent": used_percent,
                        "free_bytes": storage.get("disk_free_bytes", 0),
                        "total_bytes": storage.get("disk_total_bytes", 0),
                    },
                ))
            elif used_percent >= self.config.storage_warning_percent:
                result["alerts"].append(Alert(
                    alert_id="",
                    alert_type=AlertType.STORAGE_HIGH,
                    level=AlertLevel.WARNING,
                    module_id="system",
                    message=f"备份存储空间使用率较高: {used_percent:.1f}%",
                    details={
                        "used_percent": used_percent,
                        "free_bytes": storage.get("disk_free_bytes", 0),
                        "total_bytes": storage.get("disk_total_bytes", 0),
                    },
                ))
        except Exception as e:
            result["alerts"].append(Alert(
                alert_id="",
                alert_type=AlertType.CONFIG_ERROR,
                level=AlertLevel.WARNING,
                module_id="system",
                message=f"存储检查异常: {e}",
            ))

        return result

    # --------------------------------------------------------
    # 模块检查
    # --------------------------------------------------------

    def _check_module(self, module_id: str, config) -> Dict[str, Any]:
        """检查单个模块的备份状态"""
        status = {
            "module_id": module_id,
            "healthy": True,
            "latest_backup": None,
            "backup_count": 0,
            "alerts": [],
        }

        try:
            # 获取该模块的备份列表
            backups = self.bm.list_backups(module_id=module_id)
            status["backup_count"] = len(backups)

            if not backups:
                status["healthy"] = False
                status["alerts"].append(Alert(
                    alert_id="",
                    alert_type=AlertType.BACKUP_STALE,
                    level=AlertLevel.CRITICAL,
                    module_id=module_id,
                    message=f"模块 {module_id} 没有任何备份",
                ))
                return status

            # 检查最新备份时间
            latest = backups[0]
            status["latest_backup"] = {
                "name": latest.get("name"),
                "created": latest.get("created"),
                "size_bytes": latest.get("size_bytes"),
            }

            backup_age_hours = (time.time() - latest.get("created", 0)) / 3600

            if backup_age_hours > self.config.backup_stale_hours:
                status["healthy"] = False
                status["alerts"].append(Alert(
                    alert_id="",
                    alert_type=AlertType.BACKUP_STALE,
                    level=AlertLevel.WARNING,
                    module_id=module_id,
                    message=f"模块 {module_id} 备份已过期: {backup_age_hours:.1f} 小时前",
                    details={
                        "latest_backup_time": latest.get("created"),
                        "age_hours": round(backup_age_hours, 1),
                        "threshold_hours": self.config.backup_stale_hours,
                    },
                ))

            # 验证最新备份完整性
            if latest.get("path"):
                backup_path = Path(latest["path"])
                try:
                    db_files = list(backup_path.glob("*.db")) + \
                               list(backup_path.glob("*.db.gz"))
                    if db_files:
                        verify_result = self.bm.verify_backup(str(db_files[0]))
                        if not verify_result.overall_valid:
                            status["healthy"] = False
                            status["alerts"].append(Alert(
                                alert_id="",
                                alert_type=AlertType.BACKUP_CORRUPTED,
                                level=AlertLevel.CRITICAL,
                                module_id=module_id,
                                message=f"模块 {module_id} 最新备份损坏",
                                details={
                                    "backup_name": latest.get("name"),
                                    "errors": verify_result.errors,
                                },
                            ))
                except Exception as e:
                    # 备份验证过程异常不中断整体监控流程
                    logger.warning("验证模块 %s 备份完整性失败: %s", module_id, e)

        except Exception as e:
            status["healthy"] = False
            status["alerts"].append(Alert(
                alert_id="",
                alert_type=AlertType.CONFIG_ERROR,
                level=AlertLevel.WARNING,
                module_id=module_id,
                message=f"模块 {module_id} 备份检查异常: {e}",
            ))

        return status

    # --------------------------------------------------------
    # 演练提醒检查
    # --------------------------------------------------------

    def _check_drill_reminders(self) -> List[Alert]:
        """检查恢复演练提醒"""
        alerts = []

        # 检查上次演练时间
        drill_log_path = Path(self.config.alerts_file).parent / "drill_log.json"
        last_drill = None

        try:
            if drill_log_path.exists():
                with open(drill_log_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                last_drill = data.get("last_drill_time", 0)
        except Exception as e:
            # 演练日志读取失败不影响提醒功能，按无历史记录处理
            logger.debug("读取恢复演练日志失败: %s", e)

        if not last_drill:
            # 没有演练记录，发出首次提醒
            alerts.append(Alert(
                alert_id="",
                alert_type=AlertType.DRILL_OVERDUE,
                level=AlertLevel.INFO,
                module_id="system",
                message="尚未执行过灾难恢复演练，建议尽快安排首次演练",
                details={"drill_type": "initial"},
            ))
            return alerts

        days_since_drill = (time.time() - last_drill) / 86400

        # 月度提醒
        if days_since_drill >= self.config.drill_reminder_days:
            alerts.append(Alert(
                alert_id="",
                alert_type=AlertType.DRILL_OVERDUE,
                level=AlertLevel.WARNING,
                module_id="system",
                message=f"距上次灾难恢复演练已 {days_since_drill:.0f} 天，请安排月度演练",
                details={
                    "last_drill_time": last_drill,
                    "days_since": round(days_since_drill, 1),
                    "drill_type": "monthly",
                },
            ))

        return alerts

    # --------------------------------------------------------
    # 告警查询
    # --------------------------------------------------------

    def get_active_alerts(self, level: Optional[str] = None) -> List[Alert]:
        """获取当前活跃告警

        Args:
            level: 按级别过滤

        Returns:
            告警列表
        """
        active = [a for a in self._alerts if not a.resolved]
        if level:
            active = [a for a in active if a.level == level]
        return sorted(active, key=lambda a: a.created_at, reverse=True)

    def get_all_alerts(self, limit: int = 100) -> List[Alert]:
        """获取所有告警记录（最近 N 条）"""
        return sorted(
            self._alerts, key=lambda a: a.created_at, reverse=True
        )[:limit]

    def resolve_alert(self, alert_id: str, note: str = "") -> bool:
        """标记告警已解决

        Args:
            alert_id: 告警ID
            note: 解决说明

        Returns:
            是否成功
        """
        for alert in self._alerts:
            if alert.alert_id == alert_id and not alert.resolved:
                alert.resolved = True
                alert.resolved_at = time.time()
                alert.resolution_note = note
                self._save_alerts()
                return True
        return False

    # --------------------------------------------------------
    # 记录演练
    # --------------------------------------------------------

    def record_drill(self, drill_type: str, results: Dict[str, Any]) -> bool:
        """记录恢复演练

        Args:
            drill_type: 演练类型
            results: 演练结果

        Returns:
            是否成功
        """
        try:
            drill_log_path = Path(self.config.alerts_file).parent / "drill_log.json"
            drill_log_path.parent.mkdir(parents=True, exist_ok=True)

            log = {
                "last_drill_time": time.time(),
                "last_drill_type": drill_type,
                "last_drill_results": results,
                "drill_history": [],
            }

            # 保留历史记录
            if drill_log_path.exists():
                try:
                    with open(drill_log_path, "r", encoding="utf-8") as f:
                        old_data = json.load(f)
                    history = old_data.get("drill_history", [])
                    history.append({
                        "time": old_data.get("last_drill_time", 0),
                        "type": old_data.get("last_drill_type", ""),
                        "results": old_data.get("last_drill_results", {}),
                    })
                    log["drill_history"] = history[-19:]  # 保留最近20次
                except Exception as e:
                    # 历史记录迁移失败不影响本次演练结果保存
                    logger.debug("迁移演练历史记录失败: %s", e)

            with open(drill_log_path, "w", encoding="utf-8") as f:
                json.dump(log, f, indent=2, ensure_ascii=False)

            return True
        except Exception:
            return False

    # --------------------------------------------------------
    # 状态摘要
    # --------------------------------------------------------

    def get_status_summary(self) -> Dict[str, Any]:
        """获取监控状态摘要"""
        active_alerts = self.get_active_alerts()
        storage = self.bm.get_storage_usage()

        return {
            "overall_healthy": len([a for a in active_alerts
                                    if a.level in (AlertLevel.WARNING, AlertLevel.CRITICAL)]) == 0,
            "active_alerts_count": len(active_alerts),
            "critical_alerts": len([a for a in active_alerts
                                    if a.level == AlertLevel.CRITICAL]),
            "warning_alerts": len([a for a in active_alerts
                                   if a.level == AlertLevel.WARNING]),
            "storage_used_percent": round(
                100 - storage.get("disk_free_percent", 100), 2
            ) if "disk_free_percent" in storage else None,
            "total_backups": self.bm.get_backup_stats().get("total_backups", 0),
            "monitored_modules": len(get_modules_with_db()),
        }


# ============================================================
# CLI 入口
# ============================================================

def main():
    """命令行入口"""
    import argparse

    parser = argparse.ArgumentParser(
        prog="backup_monitor.py",
        description="云汐备份监控告警工具（第四阶段生产就绪）",
    )

    subparsers = parser.add_subparsers(dest="command", help="可用命令")

    # check 命令
    check_parser = subparsers.add_parser("check", help="执行全面监控检查")
    check_parser.add_argument("--module", type=str, help="指定模块")
    check_parser.add_argument("--json", action="store_true", help="JSON 输出")

    # alerts 命令
    alerts_parser = subparsers.add_parser("alerts", help="查看告警")
    alerts_parser.add_argument("--active", action="store_true", help="仅活跃告警")
    alerts_parser.add_argument("--level", type=str, help="按级别过滤")
    alerts_parser.add_argument("--limit", type=int, default=20, help="显示数量")

    # resolve 命令
    resolve_parser = subparsers.add_parser("resolve", help="标记告警已解决")
    resolve_parser.add_argument("alert_id", type=str, help="告警ID")
    resolve_parser.add_argument("--note", type=str, default="", help="解决说明")

    # status 命令
    subparsers.add_parser("status", help="查看监控状态摘要")

    # record-drill 命令
    drill_parser = subparsers.add_parser("record-drill", help="记录演练")
    drill_parser.add_argument("--type", type=str, required=True, help="演练类型")

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        return 1

    monitor = BackupMonitor()

    if args.command == "check":
        report = monitor.check_all()

        if args.json:
            print(json.dumps({
                "timestamp": report.timestamp,
                "total_modules": report.total_modules,
                "healthy_modules": report.healthy_modules,
                "problematic_modules": report.problematic_modules,
                "total_backups": report.total_backups,
                "storage_usage_percent": report.storage_usage_percent,
                "overall_healthy": report.overall_healthy,
                "alerts": [asdict(a) for a in report.alerts],
            }, indent=2, ensure_ascii=False))
        else:
            print("=" * 60)
            print("  云汐备份监控报告")
            print("=" * 60)
            print(f"  检查时间: {datetime.fromtimestamp(report.timestamp).strftime('%Y-%m-%d %H:%M:%S')}")
            print(f"  模块总数: {report.total_modules}")
            print(f"  正常模块: {report.healthy_modules}")
            print(f"  异常模块: {report.problematic_modules}")
            print(f"  总备份数: {report.total_backups}")
            print(f"  存储使用率: {report.storage_usage_percent}%")
            print()

            if report.overall_healthy:
                print("  [OK] 所有检查通过")
            else:
                print(f"  [WARN] 发现 {len(report.alerts)} 个告警:")
                for alert in report.alerts:
                    level_icon = "!!" if alert.level == AlertLevel.CRITICAL else "! "
                    print(f"    [{level_icon}] {alert.module_id}: {alert.message}")

            print()

        return 0 if report.overall_healthy else 1

    elif args.command == "alerts":
        if args.active:
            alerts = monitor.get_active_alerts(level=args.level)
        else:
            alerts = monitor.get_all_alerts(limit=args.limit)
            if args.level:
                alerts = [a for a in alerts if a.level == args.level]
                alerts = alerts[:args.limit]

        print(f"共 {len(alerts)} 条告警:\n")
        print(f"{'ID':<14} {'级别':<8} {'类型':<20} {'模块':<8} {'消息'}")
        print("-" * 80)
        for a in alerts:
            status = "  " if a.resolved else "* "
            print(f"{status}{a.alert_id:<12} {a.level:<8} {a.alert_type:<20} {a.module_id:<8} {a.message[:40]}")

        return 0

    elif args.command == "resolve":
        success = monitor.resolve_alert(args.alert_id, args.note)
        if success:
            print(f"告警 {args.alert_id} 已标记为已解决")
            return 0
        else:
            print(f"未找到告警 {args.alert_id} 或告警已解决")
            return 1

    elif args.command == "status":
        status = monitor.get_status_summary()
        print("=" * 50)
        print("  备份监控状态摘要")
        print("=" * 50)
        print(f"  整体状态: {'正常' if status['overall_healthy'] else '异常'}")
        print(f"  活跃告警: {status['active_alerts_count']} (严重: {status['critical_alerts']}, 警告: {status['warning_alerts']})")
        print(f"  存储使用率: {status['storage_used_percent']}%")
        print(f"  监控模块数: {status['monitored_modules']}")
        print(f"  总备份数: {status['total_backups']}")
        print()
        return 0

    elif args.command == "record-drill":
        success = monitor.record_drill(args.type, {"recorded_by": "cli"})
        if success:
            print(f"演练已记录: {args.type}")
            return 0
        else:
            print("记录失败")
            return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
