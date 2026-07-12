"""
M10 系统卫士 - 启动安全检查模块 (A4)

供M1总控调用的API：重型任务执行前检查
检查项：内存/CPU/温度/同类进程数
返回：安全/警告/危险 三级评估
支持预期资源占用参数
"""

from __future__ import annotations

import time
import uuid
from typing import Any

from .config import get_config
from .models import (
    SecurityLevel, StartupCheckResult, TaskLevel,
)
from .system_monitor import get_system_monitor
from .process_manager import get_process_manager
from .guard_engine import get_guard_engine


class StartupChecker:
    """启动安全检查器.

    在重型任务执行前进行安全检查，评估当前系统状态是否适合启动新任务。
    返回三级评估结果：安全(safe) / 警告(warning) / 危险(danger)

    供 M1 总控模块调用，用于任务调度前的资源预检。
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
        self._init_checker()

    def _init_checker(self):
        """初始化启动检查器."""
        config = get_config()
        self.config = config
        self.check_cfg = config.startup_check

        # 依赖组件
        self.system_monitor = get_system_monitor()
        self.process_manager = get_process_manager()
        self.guard_engine = get_guard_engine()

        # 检查历史记录
        self._check_history: list[StartupCheckResult] = []

    def check_before_start(
        self,
        task_name: str,
        task_level: str = "normal",
        estimated_cpu_percent: float = 10.0,
        estimated_memory_mb: float = 100.0,
        same_process_name: str | None = None,
    ) -> StartupCheckResult:
        """执行启动前安全检查.

        Args:
            task_name: 任务名称
            task_level: 任务级别 (light/normal/heavy/super_heavy)
            estimated_cpu_percent: 预估 CPU 占用 (%)
            estimated_memory_mb: 预估内存占用 (MB)
            same_process_name: 同类进程名称（用于检查同类进程数）

        Returns:
            启动检查结果
        """
        result = StartupCheckResult(
            check_id=uuid.uuid4().hex[:16],
            timestamp=time.time(),
            task_name=task_name,
        )

        # 获取当前系统状态
        latest_metric = self.system_monitor.get_latest()

        # 1. 内存检查
        result.memory_ok, mem_details = self._check_memory(
            latest_metric.memory.usage_percent,
            estimated_memory_mb,
            latest_metric.memory.total_mb,
            task_level,
        )
        result.details["memory"] = mem_details

        # 2. CPU 检查
        result.cpu_ok, cpu_details = self._check_cpu(
            latest_metric.cpu.usage_percent,
            estimated_cpu_percent,
            task_level,
        )
        result.details["cpu"] = cpu_details

        # 3. 温度检查
        result.temperature_ok, temp_details = self._check_temperature(
            latest_metric.temperature.highest_temp_celsius,
            task_level,
        )
        result.details["temperature"] = temp_details

        # 4. 同类进程检查
        result.same_process_ok, proc_details = self._check_same_process(
            same_process_name or task_name,
            task_level,
        )
        result.details["same_process"] = proc_details

        # 计算总体级别
        result.overall_level = self._calculate_overall_level(result)

        # 确定是否允许启动
        result.allowed_to_start = result.overall_level != SecurityLevel.DANGER

        # 生成建议
        result.recommended_action = self._generate_recommendation(result, task_level)

        # 记录历史
        self._check_history.append(result)
        if len(self._check_history) > 200:
            self._check_history = self._check_history[-200:]

        return result

    def _check_memory(
        self,
        current_usage_percent: float,
        estimated_memory_mb: float,
        total_memory_mb: float,
        task_level: str,
    ) -> tuple[bool, dict[str, Any]]:
        """检查内存是否充足.

        Returns:
            (是否通过, 详细信息)
        """
        # 计算启动后的预估内存使用率
        estimated_percent = current_usage_percent + (estimated_memory_mb / total_memory_mb * 100)

        # 根据任务级别确定阈值
        thresholds = self._get_memory_thresholds(task_level)

        details = {
            "current_usage_percent": round(current_usage_percent, 1),
            "estimated_memory_mb": round(estimated_memory_mb, 1),
            "total_memory_mb": round(total_memory_mb, 1),
            "estimated_after_start_percent": round(estimated_percent, 1),
            "warning_threshold": thresholds["warning"],
            "danger_threshold": thresholds["danger"],
        }

        if estimated_percent >= thresholds["danger"]:
            details["status"] = "danger"
            details["message"] = f"预估内存使用率将达到 {estimated_percent:.1f}%，超过危险阈值"
            return False, details
        elif estimated_percent >= thresholds["warning"]:
            details["status"] = "warning"
            details["message"] = f"预估内存使用率将达到 {estimated_percent:.1f}%，偏高"
            return True, details
        else:
            details["status"] = "safe"
            details["message"] = "内存充足"
            return True, details

    def _check_cpu(
        self,
        current_usage_percent: float,
        estimated_cpu_percent: float,
        task_level: str,
    ) -> tuple[bool, dict[str, Any]]:
        """检查 CPU 是否充足.

        Returns:
            (是否通过, 详细信息)
        """
        estimated_percent = current_usage_percent + estimated_cpu_percent
        thresholds = self._get_cpu_thresholds(task_level)

        details = {
            "current_usage_percent": round(current_usage_percent, 1),
            "estimated_cpu_percent": round(estimated_cpu_percent, 1),
            "estimated_after_start_percent": round(min(estimated_percent, 100.0), 1),
            "warning_threshold": thresholds["warning"],
            "danger_threshold": thresholds["danger"],
        }

        estimated_percent = min(estimated_percent, 100.0)

        if estimated_percent >= thresholds["danger"]:
            details["status"] = "danger"
            details["message"] = f"预估CPU使用率将达到 {estimated_percent:.1f}%，超过危险阈值"
            return False, details
        elif estimated_percent >= thresholds["warning"]:
            details["status"] = "warning"
            details["message"] = f"预估CPU使用率将达到 {estimated_percent:.1f}%，偏高"
            return True, details
        else:
            details["status"] = "safe"
            details["message"] = "CPU资源充足"
            return True, details

    def _check_temperature(
        self,
        current_temp: float,
        task_level: str,
    ) -> tuple[bool, dict[str, Any]]:
        """检查温度是否安全.

        Returns:
            (是否通过, 详细信息)
        """
        thresholds = self._get_temperature_thresholds(task_level)

        # 预估温度上升（重型任务会使温度升高）
        temp_increase = {
            "light": 2.0,
            "normal": 5.0,
            "heavy": 10.0,
            "super_heavy": 15.0,
        }.get(task_level, 5.0)

        estimated_temp = current_temp + temp_increase

        details = {
            "current_temp_celsius": round(current_temp, 1),
            "estimated_increase": temp_increase,
            "estimated_after_start_celsius": round(estimated_temp, 1),
            "warning_threshold": thresholds["warning"],
            "danger_threshold": thresholds["danger"],
        }

        if estimated_temp >= thresholds["danger"]:
            details["status"] = "danger"
            details["message"] = f"预估温度将达到 {estimated_temp:.1f}°C，过热危险"
            return False, details
        elif estimated_temp >= thresholds["warning"]:
            details["status"] = "warning"
            details["message"] = f"预估温度将达到 {estimated_temp:.1f}°C，偏高"
            return True, details
        else:
            details["status"] = "safe"
            details["message"] = "温度正常"
            return True, details

    def _check_same_process(
        self,
        process_name: str,
        task_level: str,
    ) -> tuple[bool, dict[str, Any]]:
        """检查同类进程数量.

        Returns:
            (是否通过, 详细信息)
        """
        # 搜索同类进程
        similar_processes = self.process_manager.search_processes(process_name)
        count = len(similar_processes)

        # 根据任务级别确定最大同类进程数
        max_same = {
            "light": 10,
            "normal": 5,
            "heavy": 3,
            "super_heavy": 1,
        }.get(task_level, self.check_cfg.heavy_task_max_same_process)

        details = {
            "process_name": process_name,
            "similar_process_count": count,
            "max_allowed": max_same,
        }

        if count >= max_same * 2:
            details["status"] = "danger"
            details["message"] = f"同类进程数 ({count}) 过多，可能造成资源竞争"
            return False, details
        elif count >= max_same:
            details["status"] = "warning"
            details["message"] = f"同类进程数 ({count}) 已达上限，建议等待"
            return True, details
        else:
            details["status"] = "safe"
            details["message"] = f"同类进程数 ({count}) 在合理范围内"
            return True, details

    def _get_memory_thresholds(self, task_level: str) -> dict[str, float]:
        """获取内存检查阈值（根据任务级别）."""
        cfg = self.check_cfg
        base_warning = 80.0
        base_danger = 90.0

        # 任务越重，阈值越低（要求越严格）
        adjust = {
            "light": 10.0,
            "normal": 5.0,
            "heavy": 0.0,
            "super_heavy": -5.0,
        }.get(task_level, 0.0)

        return {
            "warning": base_warning + adjust,
            "danger": base_danger + adjust,
        }

    def _get_cpu_thresholds(self, task_level: str) -> dict[str, float]:
        """获取 CPU 检查阈值（根据任务级别）."""
        base_warning = 75.0
        base_danger = 90.0

        adjust = {
            "light": 10.0,
            "normal": 5.0,
            "heavy": 0.0,
            "super_heavy": -5.0,
        }.get(task_level, 0.0)

        return {
            "warning": base_warning + adjust,
            "danger": base_danger + adjust,
        }

    def _get_temperature_thresholds(self, task_level: str) -> dict[str, float]:
        """获取温度检查阈值（根据任务级别）."""
        base_warning = 70.0
        base_danger = 85.0

        # 任务越重，温度要求越严格
        adjust = {
            "light": 5.0,
            "normal": 0.0,
            "heavy": -5.0,
            "super_heavy": -10.0,
        }.get(task_level, 0.0)

        return {
            "warning": base_warning + adjust,
            "danger": base_danger + adjust,
        }

    def _calculate_overall_level(self, result: StartupCheckResult) -> SecurityLevel:
        """根据各项检查结果计算总体安全级别."""
        details = result.details

        # 统计各级别的数量
        danger_count = 0
        warning_count = 0

        for key in ["memory", "cpu", "temperature", "same_process"]:
            status = details.get(key, {}).get("status", "safe")
            if status == "danger":
                danger_count += 1
            elif status == "warning":
                warning_count += 1

        # 只要有一项危险，总体就是危险
        if danger_count > 0:
            return SecurityLevel.DANGER

        # 有两项及以上警告，总体为危险
        if warning_count >= 2:
            return SecurityLevel.DANGER

        # 有一项警告，总体为警告
        if warning_count == 1:
            return SecurityLevel.WARNING

        # 全部通过，安全
        return SecurityLevel.SAFE

    def _generate_recommendation(self, result: StartupCheckResult, task_level: str) -> str:
        """生成建议动作."""
        if result.overall_level == SecurityLevel.SAFE:
            return "系统状态良好，可以安全启动任务"

        if result.overall_level == SecurityLevel.WARNING:
            warnings = []
            for key in ["memory", "cpu", "temperature", "same_process"]:
                if result.details.get(key, {}).get("status") == "warning":
                    warnings.append(result.details[key].get("message", key))
            return "系统状态偏高，建议: " + "; ".join(warnings)

        if result.overall_level == SecurityLevel.DANGER:
            dangers = []
            for key in ["memory", "cpu", "temperature", "same_process"]:
                if result.details.get(key, {}).get("status") == "danger":
                    dangers.append(result.details[key].get("message", key))
            return "危险！不建议启动任务。原因: " + "; ".join(dangers)

        return ""

    def get_check_history(self, limit: int = 50) -> list[StartupCheckResult]:
        """获取检查历史记录.

        Args:
            limit: 返回数量限制

        Returns:
            检查结果列表
        """
        return list(reversed(self._check_history))[:limit]

    def get_stats(self) -> dict[str, Any]:
        """获取启动检查统计.

        Returns:
            统计信息字典
        """
        total = len(self._check_history)
        if total == 0:
            return {
                "total_checks": 0,
                "safe_count": 0,
                "warning_count": 0,
                "danger_count": 0,
                "allowed_rate": 0.0,
            }

        safe_count = sum(1 for r in self._check_history if r.overall_level == SecurityLevel.SAFE)
        warning_count = sum(1 for r in self._check_history if r.overall_level == SecurityLevel.WARNING)
        danger_count = sum(1 for r in self._check_history if r.overall_level == SecurityLevel.DANGER)
        allowed_count = sum(1 for r in self._check_history if r.allowed_to_start)

        return {
            "total_checks": total,
            "safe_count": safe_count,
            "warning_count": warning_count,
            "danger_count": danger_count,
            "allowed_rate": round(allowed_count / total * 100, 1),
        }


# 全局单例获取函数
_startup_checker_instance = None


def get_startup_checker() -> StartupChecker:
    """获取启动安全检查器单例."""
    global _startup_checker_instance
    if _startup_checker_instance is None:
        _startup_checker_instance = StartupChecker()
    return _startup_checker_instance
