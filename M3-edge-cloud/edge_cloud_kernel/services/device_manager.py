"""设备管理增强版.

在现有设备注册表基础上，提供增强的设备管理能力：
- 设备注册/注销（增强版，支持更多设备信息）
- 设备信息（型号/系统/版本/性能）
- 设备状态（在线/离线/忙碌）
- 设备分组
- 设备信任等级
- 设备健康监测（心跳检测、性能指标、异常检测、健康评分）

向后兼容：不修改现有 DeviceRegistry 接口，作为增强层使用。
可与现有 m8_api/device_registry.py 协同工作。
"""

from __future__ import annotations

import asyncio
import json
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

import structlog

logger = structlog.get_logger(__name__)

# ---------------------------------------------------------------------------
# 枚举类型
# ---------------------------------------------------------------------------


class DeviceTrustLevel(str, Enum):
    """设备信任等级枚举.

    Attributes:
        UNTRUSTED: 未信任（待验证）.
        LOW: 低信任度.
        MEDIUM: 中信任度.
        HIGH: 高信任度.
        TRUSTED: 完全信任.
    """

    UNTRUSTED = "untrusted"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    TRUSTED = "trusted"


class DeviceHealthStatus(str, Enum):
    """设备健康状态枚举.

    Attributes:
        HEALTHY: 健康.
        WARNING: 警告.
        DEGRADED: 性能下降.
        UNHEALTHY: 不健康.
        UNKNOWN: 未知.
    """

    HEALTHY = "healthy"
    WARNING = "warning"
    DEGRADED = "degraded"
    UNHEALTHY = "unhealthy"
    UNKNOWN = "unknown"


class DeviceOperationalStatus(str, Enum):
    """设备运行状态枚举.

    Attributes:
        ONLINE: 在线.
        OFFLINE: 离线.
        BUSY: 忙碌.
        IDLE: 空闲.
        ERROR: 错误.
        MAINTENANCE: 维护中.
    """

    ONLINE = "online"
    OFFLINE = "offline"
    BUSY = "busy"
    IDLE = "idle"
    ERROR = "error"
    MAINTENANCE = "maintenance"


# ---------------------------------------------------------------------------
# 数据结构
# ---------------------------------------------------------------------------


@dataclass
class HealthMetric:
    """健康指标.

    Attributes:
        metric_name: 指标名称.
        value: 指标值.
        unit: 单位.
        timestamp: 采样时间.
        threshold_warning: 警告阈值.
        threshold_critical: 严重阈值.
        status: 指标状态（normal/warning/critical）.
    """

    metric_name: str
    value: float
    unit: str = ""
    timestamp: float = field(default_factory=time.time)
    threshold_warning: float = 0.0
    threshold_critical: float = 0.0
    status: str = "normal"  # normal / warning / critical


@dataclass
class DeviceHealthScore:
    """设备健康评分.

    Attributes:
        overall_score: 综合评分（0-100）.
        cpu_score: CPU 健康分.
        memory_score: 内存健康分.
        network_score: 网络健康分.
        battery_score: 电池健康分.
        thermal_score: 温度健康分.
        stability_score: 稳定性评分.
        status: 健康状态.
        last_updated: 最后更新时间.
        recommendations: 优化建议列表.
    """

    overall_score: float = 100.0
    cpu_score: float = 100.0
    memory_score: float = 100.0
    network_score: float = 100.0
    battery_score: float = 100.0
    thermal_score: float = 100.0
    stability_score: float = 100.0
    status: DeviceHealthStatus = DeviceHealthStatus.HEALTHY
    last_updated: float = field(default_factory=time.time)
    recommendations: list[str] = field(default_factory=list)


@dataclass
class DeviceInfo:
    """增强版设备信息.

    Attributes:
        device_id: 设备唯一标识.
        name: 设备名称.
        device_type: 设备类型.
        model: 设备型号.
        manufacturer: 制造商.
        os_name: 操作系统名称.
        os_version: 操作系统版本.
        app_version: 应用版本.
        firmware_version: 固件版本.
        status: 运行状态.
        trust_level: 信任等级.
        last_seen: 最后活跃时间.
        registered_at: 注册时间.
        groups: 所属分组列表.
        metadata: 附加元数据.
        capabilities: 设备能力列表.
        cpu_cores: CPU 核心数.
        total_memory_gb: 总内存（GB）.
        total_storage_gb: 总存储（GB）.
        has_gpu: 是否有 GPU.
    """

    device_id: str
    name: str = ""
    device_type: str = "unknown"
    model: str = ""
    manufacturer: str = ""
    os_name: str = ""
    os_version: str = ""
    app_version: str = ""
    firmware_version: str = ""
    status: DeviceOperationalStatus = DeviceOperationalStatus.ONLINE
    trust_level: DeviceTrustLevel = DeviceTrustLevel.UNTRUSTED
    last_seen: float = field(default_factory=time.time)
    registered_at: float = field(default_factory=time.time)
    groups: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
    capabilities: list[str] = field(default_factory=list)
    cpu_cores: int = 0
    total_memory_gb: float = 0.0
    total_storage_gb: float = 0.0
    has_gpu: bool = False


@dataclass
class DeviceHealthRecord:
    """设备健康记录.

    Attributes:
        record_id: 记录 ID.
        device_id: 设备 ID.
        timestamp: 记录时间.
        cpu_usage: CPU 使用率.
        memory_usage: 内存使用率.
        battery_level: 电池电量.
        battery_temperature: 电池温度.
        network_latency_ms: 网络延迟.
        network_type: 网络类型.
        cpu_temperature: CPU 温度.
        active_tasks: 活跃任务数.
        error_count: 错误计数.
        health_score: 健康评分.
    """

    record_id: str
    device_id: str
    timestamp: float = field(default_factory=time.time)
    cpu_usage: float = 0.0
    memory_usage: float = 0.0
    battery_level: float = -1.0
    battery_temperature: float = 0.0
    network_latency_ms: float = 0.0
    network_type: str = "unknown"
    cpu_temperature: float = 0.0
    active_tasks: int = 0
    error_count: int = 0
    health_score: float = 100.0


# ---------------------------------------------------------------------------
# DeviceManager
# ---------------------------------------------------------------------------


class DeviceManager:
    """设备管理器增强版.

    提供完整的设备生命周期管理和健康监测能力：
    - 设备注册/注销/更新
    - 设备信息管理（硬件/软件/性能参数）
    - 设备状态管理（在线/离线/忙碌/空闲）
    - 设备分组
    - 设备信任等级
    - 心跳检测与健康监测
    - 性能指标上报
    - 异常检测与健康评分
    - 设备通知推送

    向后兼容：不修改现有 DeviceRegistry，作为增强层独立工作。

    Attributes:
        _devices: 设备字典 {device_id: DeviceInfo}.
        _health_records: 健康记录 {device_id: [records...]}.
        _health_scores: 健康评分 {device_id: DeviceHealthScore}.
        _groups: 设备分组 {group_name: [device_ids...]}.
        _heartbeat_timeout: 心跳超时时间（秒）.
        _health_record_limit: 每个设备保留的健康记录数.
    """

    def __init__(
        self,
        heartbeat_timeout: int = 120,
        health_record_limit: int = 100,
    ) -> None:
        """初始化设备管理器.

        Args:
            heartbeat_timeout: 心跳超时时间（秒），超时后标记为离线.
            health_record_limit: 每个设备保留的健康记录数.
        """
        self._devices: dict[str, DeviceInfo] = {}
        self._health_records: dict[str, list[DeviceHealthRecord]] = {}
        self._health_scores: dict[str, DeviceHealthScore] = {}
        self._groups: dict[str, set[str]] = {}
        self._heartbeat_timeout = heartbeat_timeout
        self._health_record_limit = health_record_limit
        self._anomaly_callbacks: list[Any] = []

        logger.info(
            "device_manager.init",
            heartbeat_timeout=heartbeat_timeout,
            health_record_limit=health_record_limit,
        )

    # ------------------------------------------------------------------
    # 设备注册与管理
    # ------------------------------------------------------------------

    def register_device(
        self,
        device_id: str,
        name: str = "",
        device_type: str = "unknown",
        model: str = "",
        manufacturer: str = "",
        os_name: str = "",
        os_version: str = "",
        app_version: str = "",
        firmware_version: str = "",
        capabilities: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
        cpu_cores: int = 0,
        total_memory_gb: float = 0.0,
        total_storage_gb: float = 0.0,
        has_gpu: bool = False,
    ) -> DeviceInfo:
        """注册设备.

        如果设备已存在，则更新设备信息。

        Args:
            device_id: 设备唯一标识.
            name: 设备名称.
            device_type: 设备类型.
            model: 设备型号.
            manufacturer: 制造商.
            os_name: 操作系统名称.
            os_version: 操作系统版本.
            app_version: 应用版本.
            firmware_version: 固件版本.
            capabilities: 设备能力列表.
            metadata: 附加元数据.
            cpu_cores: CPU 核心数.
            total_memory_gb: 总内存（GB）.
            total_storage_gb: 总存储（GB）.
            has_gpu: 是否有 GPU.

        Returns:
            设备信息对象.
        """
        existing = self._devices.get(device_id)

        if existing:
            # 更新已有设备
            existing.name = name or existing.name
            existing.model = model or existing.model
            existing.manufacturer = manufacturer or existing.manufacturer
            existing.os_name = os_name or existing.os_name
            existing.os_version = os_version or existing.os_version
            existing.app_version = app_version or existing.app_version
            existing.firmware_version = firmware_version or existing.firmware_version
            existing.status = DeviceOperationalStatus.ONLINE
            existing.last_seen = time.time()
            if capabilities:
                existing.capabilities = list(set(existing.capabilities + capabilities))
            if metadata:
                existing.metadata.update(metadata)
            if cpu_cores:
                existing.cpu_cores = cpu_cores
            if total_memory_gb:
                existing.total_memory_gb = total_memory_gb
            if total_storage_gb:
                existing.total_storage_gb = total_storage_gb
            if has_gpu:
                existing.has_gpu = has_gpu
            device = existing
        else:
            # 新设备
            device = DeviceInfo(
                device_id=device_id,
                name=name or f"device-{device_id[:8]}",
                device_type=device_type,
                model=model,
                manufacturer=manufacturer,
                os_name=os_name,
                os_version=os_version,
                app_version=app_version,
                firmware_version=firmware_version,
                status=DeviceOperationalStatus.ONLINE,
                trust_level=DeviceTrustLevel.UNTRUSTED,
                capabilities=capabilities or [],
                metadata=metadata or {},
                cpu_cores=cpu_cores,
                total_memory_gb=total_memory_gb,
                total_storage_gb=total_storage_gb,
                has_gpu=has_gpu,
            )
            self._devices[device_id] = device
            self._health_records[device_id] = []
            self._health_scores[device_id] = DeviceHealthScore()

        logger.info(
            "device_manager.registered",
            device_id=device_id,
            name=device.name,
            type=device_type,
            is_new=existing is None,
        )
        return device

    def unregister_device(self, device_id: str) -> bool:
        """注销设备.

        Args:
            device_id: 设备 ID.

        Returns:
            是否成功注销.
        """
        if device_id not in self._devices:
            return False

        # 从所有分组中移除
        for group_devices in self._groups.values():
            group_devices.discard(device_id)

        del self._devices[device_id]
        self._health_records.pop(device_id, None)
        self._health_scores.pop(device_id, None)

        logger.info("device_manager.unregistered", device_id=device_id)
        return True

    def get_device(self, device_id: str) -> DeviceInfo | None:
        """获取设备信息.

        Args:
            device_id: 设备 ID.

        Returns:
            设备信息，不存在返回 None.
        """
        return self._devices.get(device_id)

    def list_devices(
        self,
        status: DeviceOperationalStatus | None = None,
        device_type: str | None = None,
        group: str | None = None,
        trust_level: DeviceTrustLevel | None = None,
    ) -> list[DeviceInfo]:
        """列出设备.

        Args:
            status: 按状态过滤.
            device_type: 按类型过滤.
            group: 按分组过滤.
            trust_level: 按信任等级过滤.

        Returns:
            设备列表.
        """
        devices = list(self._devices.values())

        if status:
            devices = [d for d in devices if d.status == status]
        if device_type:
            devices = [d for d in devices if d.device_type == device_type]
        if trust_level:
            devices = [d for d in devices if d.trust_level == trust_level]
        if group and group in self._groups:
            group_ids = self._groups[group]
            devices = [d for d in devices if d.device_id in group_ids]

        # 按 last_seen 倒序
        devices.sort(key=lambda d: d.last_seen, reverse=True)
        return devices

    def update_device_status(
        self,
        device_id: str,
        status: DeviceOperationalStatus,
    ) -> bool:
        """更新设备状态.

        Args:
            device_id: 设备 ID.
            status: 新状态.

        Returns:
            是否成功.
        """
        device = self._devices.get(device_id)
        if not device:
            return False

        old_status = device.status
        device.status = status
        device.last_seen = time.time()

        if old_status != status:
            logger.info(
                "device_manager.status_changed",
                device_id=device_id,
                old=old_status.value,
                new=status.value,
            )

        return True

    # ------------------------------------------------------------------
    # 设备分组
    # ------------------------------------------------------------------

    def create_group(self, group_name: str) -> bool:
        """创建设备分组.

        Args:
            group_name: 分组名称.

        Returns:
            是否创建成功.
        """
        if group_name in self._groups:
            return False
        self._groups[group_name] = set()
        logger.info("device_manager.group_created", group=group_name)
        return True

    def delete_group(self, group_name: str) -> bool:
        """删除设备分组.

        Args:
            group_name: 分组名称.

        Returns:
            是否删除成功.
        """
        if group_name not in self._groups:
            return False
        del self._groups[group_name]
        logger.info("device_manager.group_deleted", group=group_name)
        return True

    def add_to_group(self, device_id: str, group_name: str) -> bool:
        """将设备加入分组.

        Args:
            device_id: 设备 ID.
            group_name: 分组名称.

        Returns:
            是否成功.
        """
        if device_id not in self._devices:
            return False

        if group_name not in self._groups:
            self.create_group(group_name)

        self._groups[group_name].add(device_id)
        device = self._devices[device_id]
        if group_name not in device.groups:
            device.groups.append(group_name)

        logger.debug(
            "device_manager.added_to_group",
            device_id=device_id,
            group=group_name,
        )
        return True

    def remove_from_group(self, device_id: str, group_name: str) -> bool:
        """将设备从分组移除.

        Args:
            device_id: 设备 ID.
            group_name: 分组名称.

        Returns:
            是否成功.
        """
        if group_name not in self._groups:
            return False
        if device_id not in self._groups[group_name]:
            return False

        self._groups[group_name].discard(device_id)
        device = self._devices.get(device_id)
        if device and group_name in device.groups:
            device.groups.remove(group_name)

        logger.debug(
            "device_manager.removed_from_group",
            device_id=device_id,
            group=group_name,
        )
        return True

    def list_groups(self) -> list[str]:
        """列出所有分组名称.

        Returns:
            分组名称列表.
        """
        return list(self._groups.keys())

    def get_group_devices(self, group_name: str) -> list[DeviceInfo]:
        """获取分组内的设备.

        Args:
            group_name: 分组名称.

        Returns:
            设备列表.
        """
        if group_name not in self._groups:
            return []
        device_ids = self._groups[group_name]
        return [
            self._devices[did] for did in device_ids if did in self._devices
        ]

    # ------------------------------------------------------------------
    # 信任等级管理
    # ------------------------------------------------------------------

    def set_trust_level(
        self,
        device_id: str,
        trust_level: DeviceTrustLevel,
    ) -> bool:
        """设置设备信任等级.

        Args:
            device_id: 设备 ID.
            trust_level: 信任等级.

        Returns:
            是否成功.
        """
        device = self._devices.get(device_id)
        if not device:
            return False

        old_level = device.trust_level
        device.trust_level = trust_level

        if old_level != trust_level:
            logger.info(
                "device_manager.trust_level_changed",
                device_id=device_id,
                old=old_level.value,
                new=trust_level.value,
            )

        return True

    def get_trust_level(self, device_id: str) -> DeviceTrustLevel | None:
        """获取设备信任等级.

        Args:
            device_id: 设备 ID.

        Returns:
            信任等级，设备不存在返回 None.
        """
        device = self._devices.get(device_id)
        return device.trust_level if device else None

    # ------------------------------------------------------------------
    # 设备健康监测
    # ------------------------------------------------------------------

    def record_heartbeat(
        self,
        device_id: str,
        cpu_usage: float = 0.0,
        memory_usage: float = 0.0,
        battery_level: float = -1.0,
        network_latency_ms: float = 0.0,
        network_type: str = "unknown",
        cpu_temperature: float = 0.0,
        battery_temperature: float = 0.0,
        active_tasks: int = 0,
        error_count: int = 0,
    ) -> DeviceHealthScore:
        """记录心跳和健康指标.

        Args:
            device_id: 设备 ID.
            cpu_usage: CPU 使用率（0-100）.
            memory_usage: 内存使用率（0-100）.
            battery_level: 电池电量（0-100，-1 表示无电池）.
            network_latency_ms: 网络延迟（毫秒）.
            network_type: 网络类型.
            cpu_temperature: CPU 温度（摄氏度）.
            battery_temperature: 电池温度（摄氏度）.
            active_tasks: 活跃任务数.
            error_count: 错误计数.

        Returns:
            计算后的健康评分.
        """
        if device_id not in self._devices:
            # 自动注册未知设备
            self.register_device(device_id=device_id)

        # 更新设备状态
        device = self._devices[device_id]
        device.last_seen = time.time()
        if device.status == DeviceOperationalStatus.OFFLINE:
            device.status = DeviceOperationalStatus.ONLINE

        # 记录健康数据
        record = DeviceHealthRecord(
            record_id=str(uuid.uuid4()),
            device_id=device_id,
            cpu_usage=cpu_usage,
            memory_usage=memory_usage,
            battery_level=battery_level,
            network_latency_ms=network_latency_ms,
            network_type=network_type,
            cpu_temperature=cpu_temperature,
            battery_temperature=battery_temperature,
            active_tasks=active_tasks,
            error_count=error_count,
        )

        if device_id not in self._health_records:
            self._health_records[device_id] = []

        self._health_records[device_id].append(record)

        # 限制记录数量
        if len(self._health_records[device_id]) > self._health_record_limit:
            self._health_records[device_id] = self._health_records[device_id][
                -self._health_record_limit:
            ]

        # 计算健康评分
        score = self._calculate_health_score(device_id, record)
        self._health_scores[device_id] = score
        record.health_score = score.overall_score

        # 异常检测
        self._detect_anomalies(device_id, score)

        return score

    def get_health_score(self, device_id: str) -> DeviceHealthScore | None:
        """获取设备健康评分.

        Args:
            device_id: 设备 ID.

        Returns:
            健康评分，设备不存在返回 None.
        """
        return self._health_scores.get(device_id)

    def get_health_records(
        self,
        device_id: str,
        limit: int = 20,
    ) -> list[DeviceHealthRecord]:
        """获取设备健康记录.

        Args:
            device_id: 设备 ID.
            limit: 返回条数.

        Returns:
            健康记录列表（按时间倒序）.
        """
        records = self._health_records.get(device_id, [])
        records_sorted = sorted(records, key=lambda r: r.timestamp, reverse=True)
        return records_sorted[:limit]

    def check_offline_devices(self) -> list[str]:
        """检查并标记超时离线的设备.

        Returns:
            新标记为离线的设备 ID 列表.
        """
        now = time.time()
        newly_offline: list[str] = []

        for device_id, device in self._devices.items():
            if device.status == DeviceOperationalStatus.OFFLINE:
                continue

            if now - device.last_seen > self._heartbeat_timeout:
                old_status = device.status
                device.status = DeviceOperationalStatus.OFFLINE
                newly_offline.append(device_id)

                logger.info(
                    "device_manager.device_offline",
                    device_id=device_id,
                    previous_status=old_status.value,
                    last_seen_ago=now - device.last_seen,
                )

        return newly_offline

    def _calculate_health_score(
        self,
        device_id: str,
        record: DeviceHealthRecord,
    ) -> DeviceHealthScore:
        """计算设备健康评分.

        综合 CPU、内存、网络、电池、温度、稳定性等多维度评分。
        """
        recommendations: list[str] = []

        # CPU 评分
        if record.cpu_usage < 50:
            cpu_score = 100.0
        elif record.cpu_usage < 80:
            cpu_score = 80.0
        elif record.cpu_usage < 95:
            cpu_score = 60.0
            recommendations.append("CPU 使用率较高，建议减少后台任务")
        else:
            cpu_score = 40.0
            recommendations.append("CPU 使用率过高，建议关闭部分应用")

        # 内存评分
        if record.memory_usage < 60:
            memory_score = 100.0
        elif record.memory_usage < 80:
            memory_score = 80.0
        elif record.memory_usage < 95:
            memory_score = 60.0
            recommendations.append("内存使用率较高，建议清理内存")
        else:
            memory_score = 40.0
            recommendations.append("内存使用率过高，存在 OOM 风险")

        # 网络评分
        if record.network_latency_ms < 50:
            network_score = 100.0
        elif record.network_latency_ms < 100:
            network_score = 85.0
        elif record.network_latency_ms < 300:
            network_score = 65.0
        elif record.network_latency_ms < 1000:
            network_score = 40.0
            recommendations.append("网络延迟较高，可能影响实时体验")
        else:
            network_score = 20.0
            recommendations.append("网络延迟过高，建议检查网络连接")

        # 电池评分
        if record.battery_level < 0:
            battery_score = 100.0  # 无电池（插电）满分
        elif record.battery_level > 50:
            battery_score = 100.0
        elif record.battery_level > 20:
            battery_score = 70.0
        elif record.battery_level > 10:
            battery_score = 40.0
            recommendations.append("电池电量较低，建议充电")
        else:
            battery_score = 20.0
            recommendations.append("电池电量过低，请尽快充电")

        # 温度评分
        max_temp = max(record.cpu_temperature, record.battery_temperature)
        if max_temp < 50:
            thermal_score = 100.0
        elif max_temp < 70:
            thermal_score = 80.0
        elif max_temp < 85:
            thermal_score = 50.0
            recommendations.append("设备温度较高，注意散热")
        else:
            thermal_score = 30.0
            recommendations.append("设备温度过高，可能触发降频")

        # 稳定性评分（基于错误计数）
        if record.error_count == 0:
            stability_score = 100.0
        elif record.error_count < 3:
            stability_score = 80.0
        elif record.error_count < 10:
            stability_score = 60.0
            recommendations.append("近期有较多错误，建议检查")
        else:
            stability_score = 40.0
            recommendations.append("错误数量过多，系统可能不稳定")

        # 综合评分（加权平均）
        weights = {
            "cpu": 0.20,
            "memory": 0.20,
            "network": 0.15,
            "battery": 0.15,
            "thermal": 0.15,
            "stability": 0.15,
        }

        overall_score = (
            cpu_score * weights["cpu"]
            + memory_score * weights["memory"]
            + network_score * weights["network"]
            + battery_score * weights["battery"]
            + thermal_score * weights["thermal"]
            + stability_score * weights["stability"]
        )

        # 确定健康状态
        if overall_score >= 85:
            status = DeviceHealthStatus.HEALTHY
        elif overall_score >= 70:
            status = DeviceHealthStatus.WARNING
        elif overall_score >= 50:
            status = DeviceHealthStatus.DEGRADED
        else:
            status = DeviceHealthStatus.UNHEALTHY

        return DeviceHealthScore(
            overall_score=round(overall_score, 1),
            cpu_score=round(cpu_score, 1),
            memory_score=round(memory_score, 1),
            network_score=round(network_score, 1),
            battery_score=round(battery_score, 1),
            thermal_score=round(thermal_score, 1),
            stability_score=round(stability_score, 1),
            status=status,
            recommendations=recommendations,
        )

    def _detect_anomalies(
        self,
        device_id: str,
        score: DeviceHealthScore,
    ) -> None:
        """检测设备异常并触发回调."""
        if score.status in (DeviceHealthStatus.DEGRADED, DeviceHealthStatus.UNHEALTHY):
            for callback in self._anomaly_callbacks:
                try:
                    result = callback(device_id, score)
                    if asyncio.iscoroutine(result):
                        asyncio.create_task(result)
                except Exception:
                    logger.exception("device_manager.anomaly_callback_error")

    def register_anomaly_callback(self, callback: Any) -> None:
        """注册异常检测回调.

        Args:
            callback: 接收 (device_id, health_score) 的回调函数.
        """
        self._anomaly_callbacks.append(callback)

    # ------------------------------------------------------------------
    # 设备通知
    # ------------------------------------------------------------------

    async def send_notification(
        self,
        device_id: str,
        title: str,
        body: str,
        notification_type: str = "info",
        priority: str = "normal",
        data: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """向设备推送通知.

        当前实现为模拟通知（记录到日志），实际集成时可对接
        推送服务或消息总线。

        Args:
            device_id: 目标设备 ID.
            title: 通知标题.
            body: 通知内容.
            notification_type: 通知类型（info/warning/error）.
            priority: 优先级（low/normal/high/critical）.
            data: 附加数据.

        Returns:
            通知结果 {success, notification_id}.
        """
        device = self._devices.get(device_id)
        if not device:
            return {
                "success": False,
                "error": "Device not found",
                "notification_id": "",
            }

        if device.status == DeviceOperationalStatus.OFFLINE:
            # 离线设备：存入待发送队列（模拟）
            logger.info(
                "device_manager.notification_queued",
                device_id=device_id,
                title=title,
                type=notification_type,
            )
            return {
                "success": True,
                "queued": True,
                "notification_id": str(uuid.uuid4()),
            }

        # 在线设备：模拟推送成功
        notification_id = str(uuid.uuid4())
        logger.info(
            "device_manager.notification_sent",
            device_id=device_id,
            title=title,
            type=notification_type,
            priority=priority,
            notification_id=notification_id,
        )

        return {
            "success": True,
            "queued": False,
            "notification_id": notification_id,
            "device_status": device.status.value,
        }

    # ------------------------------------------------------------------
    # 统计指标
    # ------------------------------------------------------------------

    def get_stats(self) -> dict[str, Any]:
        """获取设备管理统计.

        Returns:
            统计字典.
        """
        total = len(self._devices)
        online = sum(
            1 for d in self._devices.values()
            if d.status in (DeviceOperationalStatus.ONLINE, DeviceOperationalStatus.IDLE)
        )
        offline = sum(
            1 for d in self._devices.values()
            if d.status == DeviceOperationalStatus.OFFLINE
        )
        busy = sum(
            1 for d in self._devices.values()
            if d.status == DeviceOperationalStatus.BUSY
        )
        error_count = sum(
            1 for d in self._devices.values()
            if d.status == DeviceOperationalStatus.ERROR
        )

        # 健康分布
        healthy = sum(
            1 for s in self._health_scores.values()
            if s.status == DeviceHealthStatus.HEALTHY
        )
        warning = sum(
            1 for s in self._health_scores.values()
            if s.status == DeviceHealthStatus.WARNING
        )
        degraded = sum(
            1 for s in self._health_scores.values()
            if s.status == DeviceHealthStatus.DEGRADED
        )
        unhealthy = sum(
            1 for s in self._health_scores.values()
            if s.status == DeviceHealthStatus.UNHEALTHY
        )

        return {
            "total_devices": total,
            "online": online,
            "offline": offline,
            "busy": busy,
            "error": error_count,
            "groups": len(self._groups),
            "health": {
                "healthy": healthy,
                "warning": warning,
                "degraded": degraded,
                "unhealthy": unhealthy,
            },
            "trust_levels": {
                level.value: sum(
                    1 for d in self._devices.values() if d.trust_level == level
                )
                for level in DeviceTrustLevel
            },
        }
