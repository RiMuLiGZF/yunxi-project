"""
M10 系统卫士 - 防护引擎模块 (A3)

负责阈值拦截与过载限流：
- CPU阈值拦截：超过阈值触发警告
- 内存阈值拦截：超过阈值触发限流
- 温度阈值拦截：超过阈值暂停重型任务
- 过载自动限流：动态调整并发数
- 分级拦截策略：提示/警告/严重/紧急 四级
"""

from __future__ import annotations

import time
import uuid
from collections import deque
from typing import Any, Callable

from .config import get_config
from .models import (
    GuardLevel, GuardPolicy, GuardAlert, MetricType,
)
from .system_monitor import get_system_monitor


class GuardEngine:
    """防护引擎.

    监控系统资源，当超过阈值时触发分级拦截和自动限流。
    支持四种指标类型的防护：CPU、内存、温度、磁盘。
    四级拦截策略：提示(info) / 警告(warning) / 严重(critical) / 紧急(emergency)
    """

    _instance = None
    _initialized = False

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self):
        if self._initialized:
            return
        self._initialized = True
        self._init_engine()

    def _init_engine(self):
        """初始化防护引擎."""
        config = get_config()
        self.config = config
        self.threshold_cfg = config.guard_threshold

        # 系统监控器
        self.system_monitor = get_system_monitor()

        # 防护策略
        self._policies: dict[MetricType, GuardPolicy] = {}
        self._init_policies()

        # 告警记录
        self._alerts: deque[GuardAlert] = deque(maxlen=500)

        # 当前状态
        self._current_levels: dict[MetricType, GuardLevel] = {
            MetricType.CPU: GuardLevel.INFO,
            MetricType.MEMORY: GuardLevel.INFO,
            MetricType.DISK: GuardLevel.INFO,
            MetricType.TEMPERATURE: GuardLevel.INFO,
        }

        # 过载限流状态
        self._current_concurrency_limit: int = 10  # 当前并发限制
        self._base_concurrency: int = 10  # 基础并发数
        self._throttling_active: bool = False
        self._heavy_tasks_paused: bool = False

        # 回调函数
        self._on_alert_callbacks: list[Callable] = []

    def _init_policies(self):
        """初始化防护策略."""
        cfg = self.threshold_cfg

        # CPU 防护策略
        self._policies[MetricType.CPU] = GuardPolicy(
            name="CPU防护",
            description="CPU使用率超过阈值时触发分级拦截",
            metric_type=MetricType.CPU,
            info_threshold=cfg.cpu_info,
            warning_threshold=cfg.cpu_warning,
            critical_threshold=cfg.cpu_critical,
            emergency_threshold=cfg.cpu_emergency,
            enabled=True,
            action_on_warning="日志记录，降低非核心任务优先级",
            action_on_critical="启动过载限流，减少并发数",
            action_on_emergency="暂停重型任务，仅保留核心服务",
        )

        # 内存防护策略
        self._policies[MetricType.MEMORY] = GuardPolicy(
            name="内存防护",
            description="内存使用率超过阈值时触发分级拦截",
            metric_type=MetricType.MEMORY,
            info_threshold=cfg.memory_info,
            warning_threshold=cfg.memory_warning,
            critical_threshold=cfg.memory_critical,
            emergency_threshold=cfg.memory_emergency,
            enabled=True,
            action_on_warning="日志记录，触发GC回收",
            action_on_critical="启动内存限流，限制新任务内存分配",
            action_on_emergency="暂停重型任务，释放缓存内存",
        )

        # 温度防护策略
        self._policies[MetricType.TEMPERATURE] = GuardPolicy(
            name="温度防护",
            description="系统温度超过阈值时触发硬件保护",
            metric_type=MetricType.TEMPERATURE,
            info_threshold=cfg.temp_info,
            warning_threshold=cfg.temp_warning,
            critical_threshold=cfg.temp_critical,
            emergency_threshold=cfg.temp_emergency,
            enabled=True,
            action_on_warning="日志记录，提高风扇转速（模拟）",
            action_on_critical="降低CPU频率，暂停重型计算",
            action_on_emergency="暂停所有重型任务，强制降温",
        )

        # 磁盘防护策略
        self._policies[MetricType.DISK] = GuardPolicy(
            name="磁盘防护",
            description="磁盘使用率超过阈值时触发告警",
            metric_type=MetricType.DISK,
            info_threshold=cfg.disk_info,
            warning_threshold=cfg.disk_warning,
            critical_threshold=cfg.disk_critical,
            emergency_threshold=cfg.disk_emergency,
            enabled=True,
            action_on_warning="日志记录，提醒清理磁盘",
            action_on_critical="暂停磁盘写入密集型任务",
            action_on_emergency="强制清理临时文件和缓存",
        )

    def check_all(self) -> dict[str, Any]:
        """检查所有防护策略.

        Returns:
            检查结果字典
        """
        results = {}
        overall_level = GuardLevel.INFO

        for metric_type in self._policies:
            result = self.check_metric(metric_type)
            results[metric_type.value] = result
            # result["level"] 是字符串，转回枚举比较
            result_level = GuardLevel(result["level"])
            if self._level_priority(result_level) > self._level_priority(overall_level):
                overall_level = result_level

        # 更新过载限流状态
        self._update_throttling(overall_level)

        return {
            "overall_level": overall_level.value,
            "metrics": results,
            "throttling_active": self._throttling_active,
            "heavy_tasks_paused": self._heavy_tasks_paused,
            "current_concurrency_limit": self._current_concurrency_limit,
        }

    def check_metric(self, metric_type: MetricType) -> dict[str, Any]:
        """检查单个指标的防护状态.

        Args:
            metric_type: 指标类型

        Returns:
            检查结果字典
        """
        policy = self._policies.get(metric_type)
        if not policy or not policy.enabled:
            return {
                "level": GuardLevel.INFO.value,
                "value": 0.0,
                "threshold": 0.0,
                "enabled": False,
                "message": "策略未启用",
            }

        # 获取当前指标值
        current_value = self.system_monitor.get_metric_value(metric_type)

        # 判断级别
        level = self._determine_level(current_value, policy)
        self._current_levels[metric_type] = level

        # 如果级别高于 INFO，生成告警
        if level != GuardLevel.INFO:
            self._create_alert(metric_type, level, current_value, policy)

        threshold_map = {
            GuardLevel.INFO: policy.info_threshold,
            GuardLevel.WARNING: policy.warning_threshold,
            GuardLevel.CRITICAL: policy.critical_threshold,
            GuardLevel.EMERGENCY: policy.emergency_threshold,
        }

        return {
            "level": level.value,
            "value": round(current_value, 2),
            "threshold": threshold_map.get(level, 0.0),
            "enabled": True,
            "message": self._get_level_message(metric_type, level, current_value),
        }

    def _determine_level(self, value: float, policy: GuardPolicy) -> GuardLevel:
        """根据值和策略确定防护级别.

        Args:
            value: 当前值
            policy: 防护策略

        Returns:
            防护级别
        """
        if value >= policy.emergency_threshold:
            return GuardLevel.EMERGENCY
        elif value >= policy.critical_threshold:
            return GuardLevel.CRITICAL
        elif value >= policy.warning_threshold:
            return GuardLevel.WARNING
        elif value >= policy.info_threshold:
            return GuardLevel.INFO
        else:
            return GuardLevel.INFO

    def _level_priority(self, level: GuardLevel) -> int:
        """获取级别优先级数值（用于比较）."""
        priorities = {
            GuardLevel.INFO: 0,
            GuardLevel.WARNING: 1,
            GuardLevel.CRITICAL: 2,
            GuardLevel.EMERGENCY: 3,
        }
        return priorities.get(level, 0)

    def _get_level_message(self, metric_type: MetricType, level: GuardLevel, value: float) -> str:
        """获取级别描述消息."""
        metric_names = {
            MetricType.CPU: "CPU使用率",
            MetricType.MEMORY: "内存使用率",
            MetricType.TEMPERATURE: "系统温度",
            MetricType.DISK: "磁盘使用率",
            MetricType.GPU: "GPU使用率",
            MetricType.NETWORK: "网络带宽",
            MetricType.BATTERY: "电池电量",
        }

        level_messages = {
            GuardLevel.INFO: "正常范围",
            GuardLevel.WARNING: "偏高，建议关注",
            GuardLevel.CRITICAL: "过高，已启动限流措施",
            GuardLevel.EMERGENCY: "危险！已暂停重型任务",
        }

        metric_name = metric_names.get(metric_type, metric_type.value)
        level_msg = level_messages.get(level, "")
        return f"{metric_name}: {value:.1f}% - {level_msg}"

    def _create_alert(self, metric_type: MetricType, level: GuardLevel, value: float, policy: GuardPolicy):
        """创建告警记录.

        为避免重复告警，同一级别在短时间内只记录一次。
        """
        # 检查是否有最近的同级别告警（60秒内）
        now = time.time()
        for alert in reversed(self._alerts):
            if (alert.metric_type == metric_type and
                    alert.level == level and
                    now - alert.timestamp < 60):
                return  # 跳过，避免重复告警

        # 确定触发的阈值
        threshold_map = {
            GuardLevel.WARNING: policy.warning_threshold,
            GuardLevel.CRITICAL: policy.critical_threshold,
            GuardLevel.EMERGENCY: policy.emergency_threshold,
        }
        threshold = threshold_map.get(level, policy.info_threshold)

        # 确定执行的动作
        action_map = {
            GuardLevel.WARNING: policy.action_on_warning,
            GuardLevel.CRITICAL: policy.action_on_critical,
            GuardLevel.EMERGENCY: policy.action_on_emergency,
        }
        action = action_map.get(level, "日志记录")

        alert = GuardAlert(
            alert_id=uuid.uuid4().hex[:16],
            timestamp=now,
            level=level,
            metric_type=metric_type,
            metric_value=round(value, 2),
            threshold=threshold,
            message=self._get_level_message(metric_type, level, value),
            action_taken=action,
            acknowledged=False,
        )

        self._alerts.append(alert)

        # 触发回调
        for callback in self._on_alert_callbacks:
            try:
                callback(alert)
            except Exception:
                pass

    def _update_throttling(self, overall_level: GuardLevel):
        """根据总体防护级别更新限流状态.

        过载自动限流：动态调整并发数
        - INFO: 正常，全并发
        - WARNING: 轻度限流，80% 并发
        - CRITICAL: 中度限流，50% 并发，暂停重型任务
        - EMERGENCY: 重度限流，20% 并发，暂停所有非核心任务
        """
        if overall_level == GuardLevel.INFO:
            self._current_concurrency_limit = self._base_concurrency
            self._throttling_active = False
            self._heavy_tasks_paused = False
        elif overall_level == GuardLevel.WARNING:
            self._current_concurrency_limit = int(self._base_concurrency * 0.8)
            self._throttling_active = True
            self._heavy_tasks_paused = False
        elif overall_level == GuardLevel.CRITICAL:
            self._current_concurrency_limit = int(self._base_concurrency * 0.5)
            self._throttling_active = True
            self._heavy_tasks_paused = True
        elif overall_level == GuardLevel.EMERGENCY:
            self._current_concurrency_limit = max(1, int(self._base_concurrency * 0.2))
            self._throttling_active = True
            self._heavy_tasks_paused = True

    def get_current_level(self, metric_type: MetricType) -> GuardLevel:
        """获取指定指标的当前防护级别.

        Args:
            metric_type: 指标类型

        Returns:
            当前防护级别
        """
        return self._current_levels.get(metric_type, GuardLevel.INFO)

    def get_overall_level(self) -> GuardLevel:
        """获取总体防护级别（最高级别）."""
        highest = GuardLevel.INFO
        for level in self._current_levels.values():
            if self._level_priority(level) > self._level_priority(highest):
                highest = level
        return highest

    def get_alerts(self, limit: int = 50, level: str | None = None) -> list[GuardAlert]:
        """获取告警记录.

        Args:
            limit: 返回数量限制
            level: 按级别过滤

        Returns:
            告警记录列表
        """
        alerts = list(self._alerts)
        if level:
            alerts = [a for a in alerts if a.level.value == level]
        return list(reversed(alerts))[:limit]

    def get_policy(self, metric_type: MetricType) -> GuardPolicy | None:
        """获取指定指标的防护策略.

        Args:
            metric_type: 指标类型

        Returns:
            防护策略
        """
        return self._policies.get(metric_type)

    def get_all_policies(self) -> dict[MetricType, GuardPolicy]:
        """获取所有防护策略."""
        return dict(self._policies)

    def update_policy(self, metric_type: MetricType, **kwargs) -> bool:
        """更新防护策略.

        Args:
            metric_type: 指标类型
            **kwargs: 策略参数

        Returns:
            是否更新成功
        """
        policy = self._policies.get(metric_type)
        if not policy:
            return False

        for key, value in kwargs.items():
            if hasattr(policy, key) and value is not None:
                setattr(policy, key, value)

        return True

    def can_run_heavy_task(self) -> bool:
        """检查是否可以运行重型任务.

        Returns:
            True 表示可以运行
        """
        if self._heavy_tasks_paused:
            return False

        # 检查关键指标
        cpu_level = self._current_levels.get(MetricType.CPU, GuardLevel.INFO)
        mem_level = self._current_levels.get(MetricType.MEMORY, GuardLevel.INFO)
        temp_level = self._current_levels.get(MetricType.TEMPERATURE, GuardLevel.INFO)

        # 任何指标达到 CRITICAL 或以上都不能运行重型任务
        if self._level_priority(cpu_level) >= self._level_priority(GuardLevel.CRITICAL):
            return False
        if self._level_priority(mem_level) >= self._level_priority(GuardLevel.CRITICAL):
            return False
        if self._level_priority(temp_level) >= self._level_priority(GuardLevel.CRITICAL):
            return False

        return True

    def get_concurrency_limit(self) -> int:
        """获取当前并发限制.

        Returns:
            允许的最大并发数
        """
        return self._current_concurrency_limit

    def set_base_concurrency(self, concurrency: int):
        """设置基础并发数.

        Args:
            concurrency: 基础并发数
        """
        self._base_concurrency = max(1, concurrency)
        # 重新计算当前限制
        self._update_throttling(self.get_overall_level())

    def acknowledge_alert(self, alert_id: str) -> bool:
        """确认告警.

        Args:
            alert_id: 告警 ID

        Returns:
            是否成功
        """
        for alert in self._alerts:
            if alert.alert_id == alert_id:
                alert.acknowledged = True
                return True
        return False

    def register_alert_callback(self, callback: Callable):
        """注册告警回调函数.

        Args:
            callback: 回调函数，接收 GuardAlert 参数
        """
        self._on_alert_callbacks.append(callback)

    def get_status_summary(self) -> dict[str, Any]:
        """获取防护引擎状态摘要.

        Returns:
            状态摘要字典
        """
        return {
            "overall_level": self.get_overall_level().value,
            "metric_levels": {k.value: v.value for k, v in self._current_levels.items()},
            "throttling_active": self._throttling_active,
            "heavy_tasks_paused": self._heavy_tasks_paused,
            "current_concurrency_limit": self._current_concurrency_limit,
            "base_concurrency": self._base_concurrency,
            "total_alerts": len(self._alerts),
            "unacknowledged_alerts": sum(1 for a in self._alerts if not a.acknowledged),
            "policies_count": len(self._policies),
        }


# 全局单例获取函数
_guard_engine_instance = None


def get_guard_engine() -> GuardEngine:
    """获取防护引擎单例."""
    global _guard_engine_instance
    if _guard_engine_instance is None:
        _guard_engine_instance = GuardEngine()
    return _guard_engine_instance
