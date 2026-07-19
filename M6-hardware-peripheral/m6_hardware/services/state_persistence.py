"""
P2 半真实化改造：设备状态持久化服务

将设备的运行时状态（传感器读数、设备内部状态变量等）持久化到 JSON 文件，
服务重启后自动恢复，让模拟更接近真实硬件的记忆特性。

状态文件位置：data/device_states.json
"""

from __future__ import annotations

import json
import logging
import threading
import time
from pathlib import Path
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)


class StatePersistence:
    """设备状态持久化管理器

    负责将设备的运行时状态保存到本地 JSON 文件，以及从文件中恢复状态。
    使用简单的读写锁保证线程安全。

    状态结构：
    {
        "version": 1,
        "saved_at": "2024-01-01T00:00:00",
        "devices": {
            "device_id_1": {
                "state_vars": {...},   # 设备内部状态变量
                "sensor_readings": {...},  # 最新传感器读数
                "battery": 85.0,
                "status": "online",
                ...
            },
            ...
        }
    }
    """

    _VERSION = 1

    def __init__(self, state_file: str):
        """
        Args:
            state_file: 状态文件路径
        """
        self._state_file = Path(state_file)
        self._lock = threading.RLock()
        self._cache: Dict[str, Dict[str, Any]] = {}
        self._loaded = False

    def _ensure_dir(self) -> None:
        """确保状态文件所在目录存在"""
        self._state_file.parent.mkdir(parents=True, exist_ok=True)

    def load(self) -> Dict[str, Dict[str, Any]]:
        """从文件加载所有设备状态

        Returns:
            设备ID -> 状态字典 的映射
        """
        with self._lock:
            if self._loaded:
                return dict(self._cache)

            if not self._state_file.exists():
                logger.info("状态文件不存在，将创建新的状态文件: %s", self._state_file)
                self._loaded = True
                return {}

            try:
                with open(self._state_file, "r", encoding="utf-8") as f:
                    data = json.load(f)

                version = data.get("version", 1)
                devices = data.get("devices", {})
                self._cache = devices
                self._loaded = True
                logger.info(
                    "已从 %s 加载 %d 个设备的持久化状态 (版本 v%d)",
                    self._state_file, len(devices), version,
                )
                return dict(self._cache)
            except Exception as e:
                logger.warning(
                    "加载状态文件失败，将忽略已有状态: %s, error=%s",
                    self._state_file, e,
                )
                self._loaded = True
                return {}

    def save_device_state(self, device_id: str, state: Dict[str, Any]) -> None:
        """保存单个设备的状态

        Args:
            device_id: 设备ID
            state: 设备状态字典（应包含 state_vars、sensor_readings 等）
        """
        with self._lock:
            if not self._loaded:
                self.load()

            self._cache[device_id] = state
            self._flush()

    def save_all(self, devices: Dict[str, Dict[str, Any]]) -> None:
        """批量保存所有设备状态

        Args:
            devices: 设备ID -> 状态字典 的映射
        """
        with self._lock:
            self._cache = dict(devices)
            self._flush()

    def get_device_state(self, device_id: str) -> Optional[Dict[str, Any]]:
        """获取单个设备的持久化状态

        Args:
            device_id: 设备ID

        Returns:
            设备状态字典，不存在返回 None
        """
        with self._lock:
            if not self._loaded:
                self.load()
            state = self._cache.get(device_id)
            return dict(state) if state else None

    def remove_device_state(self, device_id: str) -> None:
        """移除设备的持久化状态

        Args:
            device_id: 设备ID
        """
        with self._lock:
            if not self._loaded:
                self.load()
            if device_id in self._cache:
                del self._cache[device_id]
                self._flush()

    def _flush(self) -> None:
        """将缓存写入文件（内部方法，调用者需持有锁）"""
        try:
            self._ensure_dir()
            data = {
                "version": self._VERSION,
                "saved_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
                "devices": self._cache,
            }
            # 先写入临时文件，再原子替换，避免写入中断导致文件损坏
            tmp_file = self._state_file.with_suffix(".tmp")
            with open(tmp_file, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2, default=str)
            tmp_file.replace(self._state_file)
        except Exception as e:
            logger.error("写入状态文件失败: %s, error=%s", self._state_file, e)

    def clear_all(self) -> None:
        """清空所有持久化状态"""
        with self._lock:
            self._cache.clear()
            if self._state_file.exists():
                try:
                    self._state_file.unlink()
                except Exception as e:
                    logger.warning("删除状态文件失败: %s", e)

    @property
    def state_file_path(self) -> str:
        """状态文件路径"""
        return str(self._state_file)
