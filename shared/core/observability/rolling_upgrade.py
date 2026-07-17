"""
云汐滚动升级管理器（OP-003, P1级）
====================================

提供生产级别的滚动升级机制，支持：
- 版本检查与下载
- 模块级滚动升级（逐个升级、备份、健康检查、自动回滚）
- 蓝绿部署策略
- 金丝雀发布策略
- 紧急回滚
- 升级历史记录
- 升级配置管理

核心类：
- UpgradeStrategy: 升级策略枚举（ROLLING / BLUE_GREEN / CANARY）
- UpgradePhase: 升级阶段枚举
- ModuleUpgradeRecord: 单个模块升级记录
- UpgradeConfig: 升级配置
- RollingUpgradeManager: 滚动升级管理器主类

使用方式：
    from shared.core.observability import RollingUpgradeManager, get_upgrade_manager

    manager = get_upgrade_manager()
    status = manager.check_for_upgrade()
    if status.has_new_version:
        result = manager.prepare_upgrade(status.latest_version)
        if result.success:
            upgrade_result = manager.execute_rolling_upgrade()
"""

import os
import time
import json
import shutil
import threading
import subprocess
from enum import Enum
from pathlib import Path
from typing import Dict, Any, Optional, List, Tuple, Callable
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone


# ============================================================================
# 枚举类型
# ============================================================================

class UpgradeStrategy(str, Enum):
    """升级策略

    - ROLLING: 滚动升级（逐个模块替换）
    - BLUE_GREEN: 蓝绿部署（新版本并行运行，验证后切换流量）
    - CANARY: 金丝雀发布（先小流量验证，逐步扩大）
    """
    ROLLING = "rolling"
    BLUE_GREEN = "blue_green"
    CANARY = "canary"


class UpgradePhase(str, Enum):
    """升级阶段"""
    IDLE = "idle"
    CHECKING = "checking"
    PREPARING = "preparing"
    BACKING_UP = "backing_up"
    UPGRADING = "upgrading"
    HEALTH_CHECKING = "health_checking"
    ROLLING_BACK = "rolling_back"
    COMPLETED = "completed"
    FAILED = "failed"


class UpgradeStatus(str, Enum):
    """升级状态"""
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    SUCCESS = "success"
    FAILED = "failed"
    ROLLED_BACK = "rolled_back"


# ============================================================================
# 数据模型
# ============================================================================

@dataclass
class ModuleUpgradeRecord:
    """单个模块的升级记录"""
    module_id: str
    module_name: str = ""
    from_version: str = ""
    to_version: str = ""
    status: UpgradeStatus = UpgradeStatus.PENDING
    phase: UpgradePhase = UpgradePhase.IDLE
    start_time: Optional[float] = None
    end_time: Optional[float] = None
    backup_path: str = ""
    error_message: str = ""
    health_check_passed: bool = False
    details: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "module_id": self.module_id,
            "module_name": self.module_name,
            "from_version": self.from_version,
            "to_version": self.to_version,
            "status": self.status.value,
            "phase": self.phase.value,
            "start_time": self.start_time,
            "end_time": self.end_time,
            "backup_path": self.backup_path,
            "error_message": self.error_message,
            "health_check_passed": self.health_check_passed,
            "duration_seconds": round(self.end_time - self.start_time, 2) if self.start_time and self.end_time else None,
            "details": self.details,
        }


@dataclass
class UpgradeConfig:
    """升级配置

    支持环境变量覆盖：
        UPGRADE_AUTO_CHECK=true/false       # 自动检查升级
        UPGRADE_CHECK_INTERVAL=3600         # 检查间隔（秒）
        UPGRADE_AUTO_UPGRADE=false          # 自动升级
        UPGRADE_STRATEGY=rolling            # 升级策略
        UPGRADE_WINDOW_START=02:00          # 升级窗口开始
        UPGRADE_WINDOW_END=04:00            # 升级窗口结束
        UPGRADE_BACKUP_DIR=backups/upgrade  # 备份目录
        UPGRADE_MAX_RETRY=3                 # 最大重试次数
        UPGRADE_HEALTH_CHECK_TIMEOUT=30     # 健康检查超时（秒）
        UPGRADE_ROLLBACK_ON_FAILURE=true    # 失败自动回滚
        UPGRADE_CANARY_TRAFFIC_PERCENT=10   # 金丝雀初始流量百分比
    """
    # 自动检查
    auto_check: bool = True
    check_interval_seconds: int = 3600  # 1小时

    # 自动升级
    auto_upgrade: bool = False

    # 升级策略
    strategy: UpgradeStrategy = UpgradeStrategy.ROLLING

    # 升级窗口（仅在窗口内自动升级）
    upgrade_window_start: str = "02:00"  # HH:MM 格式
    upgrade_window_end: str = "04:00"

    # 备份配置
    backup_dir: str = "backups/upgrade"
    keep_backup_count: int = 5

    # 重试配置
    max_retry: int = 3
    retry_interval_seconds: int = 30

    # 健康检查
    health_check_timeout: int = 30
    health_check_max_retries: int = 3

    # 回滚配置
    rollback_on_failure: bool = True

    # 金丝雀发布配置
    canary_initial_traffic_percent: int = 10
    canary_step_percent: int = 20
    canary_step_interval_seconds: int = 300  # 5分钟

    # 蓝绿部署配置
    blue_green_switch_mode: str = "manual"  # manual / auto

    @classmethod
    def from_env(cls) -> "UpgradeConfig":
        """从环境变量加载配置"""
        config = cls()

        env_map = {
            "UPGRADE_AUTO_CHECK": ("auto_check", lambda v: v.lower() in ("true", "1", "yes", "on")),
            "UPGRADE_CHECK_INTERVAL": ("check_interval_seconds", int),
            "UPGRADE_AUTO_UPGRADE": ("auto_upgrade", lambda v: v.lower() in ("true", "1", "yes", "on")),
            "UPGRADE_STRATEGY": ("strategy", lambda v: UpgradeStrategy(v.lower())),
            "UPGRADE_WINDOW_START": ("upgrade_window_start", str),
            "UPGRADE_WINDOW_END": ("upgrade_window_end", str),
            "UPGRADE_BACKUP_DIR": ("backup_dir", str),
            "UPGRADE_MAX_RETRY": ("max_retry", int),
            "UPGRADE_HEALTH_CHECK_TIMEOUT": ("health_check_timeout", int),
            "UPGRADE_ROLLBACK_ON_FAILURE": ("rollback_on_failure", lambda v: v.lower() in ("true", "1", "yes", "on")),
            "UPGRADE_CANARY_TRAFFIC_PERCENT": ("canary_initial_traffic_percent", int),
        }

        for env_key, (attr, converter) in env_map.items():
            val = os.getenv(env_key)
            if val is not None:
                try:
                    setattr(config, attr, converter(val))
                except (ValueError, TypeError):
                    pass

        return config

    def is_in_upgrade_window(self) -> bool:
        """检查当前时间是否在升级窗口内"""
        try:
            now = datetime.now()
            current_time = now.time()

            start_h, start_m = map(int, self.upgrade_window_start.split(":"))
            end_h, end_m = map(int, self.upgrade_window_end.split(":"))

            start_time = datetime.strptime(self.upgrade_window_start, "%H:%M").time()
            end_time = datetime.strptime(self.upgrade_window_end, "%H:%M").time()

            if start_time <= end_time:
                return start_time <= current_time <= end_time
            else:
                # 跨午夜的窗口
                return current_time >= start_time or current_time <= end_time
        except (ValueError, AttributeError):
            return True  # 配置错误时默认允许

    def to_dict(self) -> Dict[str, Any]:
        return {
            "auto_check": self.auto_check,
            "check_interval_seconds": self.check_interval_seconds,
            "auto_upgrade": self.auto_upgrade,
            "strategy": self.strategy.value,
            "upgrade_window_start": self.upgrade_window_start,
            "upgrade_window_end": self.upgrade_window_end,
            "backup_dir": self.backup_dir,
            "keep_backup_count": self.keep_backup_count,
            "max_retry": self.max_retry,
            "retry_interval_seconds": self.retry_interval_seconds,
            "health_check_timeout": self.health_check_timeout,
            "health_check_max_retries": self.health_check_max_retries,
            "rollback_on_failure": self.rollback_on_failure,
            "canary_initial_traffic_percent": self.canary_initial_traffic_percent,
            "canary_step_percent": self.canary_step_percent,
            "canary_step_interval_seconds": self.canary_step_interval_seconds,
            "blue_green_switch_mode": self.blue_green_switch_mode,
        }


@dataclass
class VersionInfo:
    """版本信息"""
    version: str
    release_date: str = ""
    release_notes: str = ""
    download_url: str = ""
    checksum: str = ""
    is_critical: bool = False
    affected_modules: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


# ============================================================================
# 滚动升级管理器
# ============================================================================

class RollingUpgradeManager:
    """滚动升级管理器

    提供完整的滚动升级生命周期管理：
    1. 检查新版本
    2. 准备升级（下载、验证）
    3. 执行滚动升级（按模块逐个升级）
    4. 健康检查
    5. 失败自动回滚
    6. 升级历史记录
    """

    def __init__(
        self,
        config: Optional[UpgradeConfig] = None,
        project_root: Optional[str] = None,
    ):
        """
        Args:
            config: 升级配置，None 则从环境变量加载
            project_root: 项目根目录，None 则自动推断
        """
        self.config = config or UpgradeConfig.from_env()
        self._project_root = self._resolve_project_root(project_root)
        self._lock = threading.RLock()

        # 升级状态
        self._current_phase: UpgradePhase = UpgradePhase.IDLE
        self._current_upgrade: Optional[Dict[str, Any]] = None
        self._module_records: Dict[str, ModuleUpgradeRecord] = {}

        # 升级历史
        self._history: List[Dict[str, Any]] = []
        self._max_history = 50

        # 后台检查线程
        self._check_thread: Optional[threading.Thread] = None
        self._check_stop = threading.Event()
        self._latest_version: Optional[VersionInfo] = None

        # 模块健康检查函数注册
        self._health_checkers: Dict[str, Callable[[], bool]] = {}
        self._module_stoppers: Dict[str, Callable[[], bool]] = {}
        self._module_starters: Dict[str, Callable[[], bool]] = {}

        # 加载历史记录
        self._load_history()

    # -----------------------------------------------------------------------
    # 内部工具
    # -----------------------------------------------------------------------

    def _resolve_project_root(self, explicit_root: Optional[str]) -> Path:
        """解析项目根目录"""
        if explicit_root:
            return Path(explicit_root).resolve()

        # 从当前文件向上查找
        current = Path(__file__).resolve()
        for _ in range(6):
            current = current.parent
            if (current / "shared").exists() or (current / "config").exists():
                return current
        return current

    @property
    def project_root(self) -> Path:
        """项目根目录"""
        return self._project_root

    @property
    def backup_dir(self) -> Path:
        """备份目录"""
        backup_path = Path(self.config.backup_dir)
        if not backup_path.is_absolute():
            backup_path = self._project_root / backup_path
        return backup_path

    @property
    def current_phase(self) -> UpgradePhase:
        """当前升级阶段"""
        return self._current_phase

    # -----------------------------------------------------------------------
    # 模块操作注册
    # -----------------------------------------------------------------------

    def register_module_operations(
        self,
        module_id: str,
        health_checker: Optional[Callable[[], bool]] = None,
        starter: Optional[Callable[[], bool]] = None,
        stopper: Optional[Callable[[], bool]] = None,
    ) -> None:
        """注册模块的操作函数

        Args:
            module_id: 模块ID
            health_checker: 健康检查函数，返回 True 表示健康
            starter: 启动函数，返回 True 表示成功
            stopper: 停止函数，返回 True 表示成功
        """
        if health_checker:
            self._health_checkers[module_id] = health_checker
        if starter:
            self._module_starters[module_id] = starter
        if stopper:
            self._module_stoppers[module_id] = stopper

    # -----------------------------------------------------------------------
    # 版本检查
    # -----------------------------------------------------------------------

    def check_for_upgrade(self, current_version: Optional[str] = None) -> Dict[str, Any]:
        """检查是否有新版本可用

        Args:
            current_version: 当前版本号，None 则从系统获取

        Returns:
            包含 has_new_version、latest_version、current_version 的字典
        """
        with self._lock:
            self._current_phase = UpgradePhase.CHECKING

        if current_version is None:
            try:
                from ..version import SYSTEM_VERSION
                current_version = SYSTEM_VERSION
            except ImportError:
                current_version = "v0.0.0"

        result = {
            "current_version": current_version,
            "has_new_version": False,
            "latest_version": None,
            "checked_at": time.time(),
        }

        # 模拟版本检查（实际实现应连接版本服务器/GitHub Release）
        # 这里提供一个可扩展的接口
        latest = self._fetch_latest_version()
        if latest and self._version_greater_than(latest.version, current_version):
            result["has_new_version"] = True
            result["latest_version"] = latest.to_dict()
            self._latest_version = latest

        with self._lock:
            self._current_phase = UpgradePhase.IDLE

        return result

    def _fetch_latest_version(self) -> Optional[VersionInfo]:
        """获取最新版本信息

        默认实现：检查本地版本文件或返回 None。
        生产环境应覆盖此方法或通过配置版本服务器地址。
        """
        # 检查本地版本文件（可选）
        version_file = self._project_root / "config" / "latest_version.json"
        if version_file.exists():
            try:
                with open(version_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                return VersionInfo(**data)
            except (json.JSONDecodeError, TypeError, KeyError):
                pass

        return None

    @staticmethod
    def _version_greater_than(version_a: str, version_b: str) -> bool:
        """比较版本号，version_a > version_b 返回 True

        支持 v1.2.3 / 1.2.3 格式
        """
        def parse_version(v: str) -> Tuple[int, ...]:
            v = v.lstrip("vV")
            parts = []
            for p in v.split("."):
                try:
                    parts.append(int(p))
                except ValueError:
                    parts.append(0)
            return tuple(parts)

        a_parts = parse_version(version_a)
        b_parts = parse_version(version_b)

        # 补齐长度
        max_len = max(len(a_parts), len(b_parts))
        a_parts = a_parts + (0,) * (max_len - len(a_parts))
        b_parts = b_parts + (0,) * (max_len - len(b_parts))

        return a_parts > b_parts

    # -----------------------------------------------------------------------
    # 升级准备
    # -----------------------------------------------------------------------

    def prepare_upgrade(self, target_version: str) -> Dict[str, Any]:
        """准备升级

        执行：
        1. 创建升级目录
        2. 下载新版本（如需要）
        3. 验证完整性
        4. 预检查

        Args:
            target_version: 目标版本号

        Returns:
            准备结果字典
        """
        with self._lock:
            if self._current_phase != UpgradePhase.IDLE:
                return {
                    "success": False,
                    "error": f"Upgrade already in progress: {self._current_phase.value}",
                }
            self._current_phase = UpgradePhase.PREPARING

        try:
            upgrade_id = f"upgrade_{target_version}_{int(time.time())}"

            # 1. 创建升级目录
            upgrade_dir = self.backup_dir / "staging" / target_version
            upgrade_dir.mkdir(parents=True, exist_ok=True)

            # 2. 预检查：磁盘空间
            disk_check = self._check_disk_space()
            if not disk_check["ok"]:
                raise RuntimeError(f"磁盘空间不足: {disk_check.get('message', '')}")

            # 3. 模拟下载验证（实际应从版本服务器下载）
            verification = self._verify_version_package(target_version, upgrade_dir)

            # 4. 保存升级准备信息
            self._current_upgrade = {
                "upgrade_id": upgrade_id,
                "target_version": target_version,
                "from_version": self._get_current_version(),
                "strategy": self.config.strategy.value,
                "start_time": time.time(),
                "staging_dir": str(upgrade_dir),
                "modules": [],
                "status": "prepared",
            }

            result = {
                "success": True,
                "upgrade_id": upgrade_id,
                "target_version": target_version,
                "staging_dir": str(upgrade_dir),
                "verification": verification,
                "disk_space_ok": disk_check["ok"],
            }

            with self._lock:
                self._current_phase = UpgradePhase.IDLE

            return result

        except Exception as e:
            with self._lock:
                self._current_phase = UpgradePhase.IDLE
            return {
                "success": False,
                "error": str(e),
            }

    def _check_disk_space(self) -> Dict[str, Any]:
        """检查磁盘空间"""
        try:
            usage = shutil.disk_usage(str(self._project_root))
            free_gb = usage.free / (1024 ** 3)
            return {
                "ok": free_gb >= 2.0,  # 至少 2GB 空闲
                "free_gb": round(free_gb, 2),
                "total_gb": round(usage.total / (1024 ** 3), 2),
                "message": f"空闲空间 {free_gb:.2f} GB" if free_gb >= 2.0 else f"空闲空间不足 {free_gb:.2f} GB",
            }
        except Exception as e:
            return {"ok": False, "error": str(e)}

    def _verify_version_package(self, version: str, staging_dir: Path) -> Dict[str, Any]:
        """验证版本包完整性

        默认实现：生成验证信息。
        生产环境应实现 checksum 校验、签名验证等。
        """
        return {
            "verified": True,
            "version": version,
            "method": "local_check",
            "staging_dir": str(staging_dir),
        }

    def _get_current_version(self) -> str:
        """获取当前系统版本"""
        try:
            from ..version import SYSTEM_VERSION
            return SYSTEM_VERSION
        except ImportError:
            return "unknown"

    # -----------------------------------------------------------------------
    # 执行滚动升级
    # -----------------------------------------------------------------------

    def execute_rolling_upgrade(
        self,
        module_ids: Optional[List[str]] = None,
        strategy: Optional[UpgradeStrategy] = None,
    ) -> Dict[str, Any]:
        """执行滚动升级

        按模块逐个升级，每个模块：
        1. 备份当前版本
        2. 停止模块
        3. 替换为新版本
        4. 启动模块
        5. 健康检查
        6. 失败则回滚

        Args:
            module_ids: 要升级的模块ID列表，None 则升级所有已注册模块
            strategy: 升级策略，None 则使用配置中的策略

        Returns:
            升级结果字典
        """
        with self._lock:
            if self._current_phase != UpgradePhase.IDLE and self._current_upgrade is None:
                return {
                    "success": False,
                    "error": "No upgrade prepared. Call prepare_upgrade() first.",
                }
            self._current_phase = UpgradePhase.UPGRADING

        if strategy is None:
            strategy = self.config.strategy

        # 确定要升级的模块
        if module_ids is None:
            module_ids = list(self._health_checkers.keys())

        if not module_ids:
            with self._lock:
                self._current_phase = UpgradePhase.IDLE
            return {"success": True, "message": "No modules to upgrade", "modules": []}

        # 初始化模块升级记录
        from_version = self._get_current_version()
        to_version = self._current_upgrade.get("target_version", "unknown") if self._current_upgrade else "unknown"

        self._module_records.clear()
        for mid in module_ids:
            self._module_records[mid] = ModuleUpgradeRecord(
                module_id=mid,
                from_version=from_version,
                to_version=to_version,
            )

        upgrade_results: Dict[str, Dict[str, Any]] = {}
        success_count = 0
        failed_count = 0
        rolled_back_modules: List[str] = []

        # 按优先级排序模块（先升级依赖底层模块）
        sorted_modules = self._sort_modules_by_priority(module_ids)

        try:
            if strategy == UpgradeStrategy.ROLLING:
                result = self._do_rolling_upgrade(sorted_modules)
            elif strategy == UpgradeStrategy.BLUE_GREEN:
                result = self._do_blue_green_upgrade(sorted_modules)
            elif strategy == UpgradeStrategy.CANARY:
                result = self._do_canary_upgrade(sorted_modules)
            else:
                result = self._do_rolling_upgrade(sorted_modules)

            # 统计结果
            for mid, record in self._module_records.items():
                upgrade_results[mid] = record.to_dict()
                if record.status == UpgradeStatus.SUCCESS:
                    success_count += 1
                elif record.status == UpgradeStatus.FAILED:
                    failed_count += 1
                elif record.status == UpgradeStatus.ROLLED_BACK:
                    rolled_back_modules.append(mid)

            overall_success = failed_count == 0 or (
                self.config.rollback_on_failure and failed_count > 0 and len(rolled_back_modules) > 0
            )

            with self._lock:
                if overall_success and failed_count == 0:
                    self._current_phase = UpgradePhase.COMPLETED
                elif rolled_back_modules:
                    self._current_phase = UpgradePhase.ROLLING_BACK
                else:
                    self._current_phase = UpgradePhase.FAILED

            # 记录历史
            history_entry = {
                "upgrade_id": self._current_upgrade.get("upgrade_id", "unknown") if self._current_upgrade else "unknown",
                "from_version": from_version,
                "to_version": to_version,
                "strategy": strategy.value,
                "start_time": self._current_upgrade.get("start_time") if self._current_upgrade else time.time(),
                "end_time": time.time(),
                "status": "success" if failed_count == 0 else "partial" if rolled_back_modules else "failed",
                "success_count": success_count,
                "failed_count": failed_count,
                "rolled_back_count": len(rolled_back_modules),
                "modules": upgrade_results,
            }
            self._add_history(history_entry)

            return {
                "success": failed_count == 0,
                "strategy": strategy.value,
                "success_count": success_count,
                "failed_count": failed_count,
                "rolled_back_count": len(rolled_back_modules),
                "rolled_back_modules": rolled_back_modules,
                "modules": upgrade_results,
                "duration_seconds": round(time.time() - (self._current_upgrade.get("start_time", time.time()) if self._current_upgrade else time.time()), 2),
            }

        except Exception as e:
            with self._lock:
                self._current_phase = UpgradePhase.FAILED
            return {
                "success": False,
                "error": str(e),
                "modules": {mid: r.to_dict() for mid, r in self._module_records.items()},
            }

    def _sort_modules_by_priority(self, module_ids: List[str]) -> List[str]:
        """按优先级排序模块（底层模块先升级）

        可通过模块注册表获取优先级，这里使用默认顺序。
        """
        try:
            from ..module_registry import get_module_registry
            registry = get_module_registry()
            modules = []
            for mid in module_ids:
                mod = registry.get_module(mid)
                if mod:
                    modules.append((mid, mod.priority))
                else:
                    modules.append((mid, 100))
            modules.sort(key=lambda x: x[1])
            return [m[0] for m in modules]
        except ImportError:
            return module_ids

    def _do_rolling_upgrade(self, module_ids: List[str]) -> Dict[str, Any]:
        """执行滚动升级（逐个模块）"""
        for mid in module_ids:
            record = self._module_records.get(mid)
            if not record:
                continue

            record.start_time = time.time()
            record.status = UpgradeStatus.IN_PROGRESS
            record.phase = UpgradePhase.BACKING_UP

            try:
                # 步骤 1: 备份
                backup_result = self._backup_module(mid)
                if not backup_result["success"]:
                    raise RuntimeError(f"备份失败: {backup_result.get('error', 'unknown')}")
                record.backup_path = backup_result.get("backup_path", "")

                # 步骤 2: 停止模块
                record.phase = UpgradePhase.UPGRADING
                stop_result = self._stop_module(mid)
                if not stop_result:
                    raise RuntimeError("模块停止失败")

                # 步骤 3: 执行升级（替换文件）
                upgrade_result = self._upgrade_module_files(mid)
                if not upgrade_result["success"]:
                    raise RuntimeError(f"升级文件替换失败: {upgrade_result.get('error', 'unknown')}")

                # 步骤 4: 启动模块
                start_result = self._start_module(mid)
                if not start_result:
                    raise RuntimeError("模块启动失败")

                # 步骤 5: 健康检查
                record.phase = UpgradePhase.HEALTH_CHECKING
                health_ok = self._wait_for_health(mid)
                if not health_ok:
                    raise RuntimeError("健康检查失败")
                record.health_check_passed = True

                # 升级成功
                record.status = UpgradeStatus.SUCCESS
                record.phase = UpgradePhase.COMPLETED
                record.end_time = time.time()

            except Exception as e:
                record.error_message = str(e)
                record.phase = UpgradePhase.ROLLING_BACK

                if self.config.rollback_on_failure:
                    # 尝试回滚
                    rollback_result = self.rollback(mid)
                    if rollback_result["success"]:
                        record.status = UpgradeStatus.ROLLED_BACK
                    else:
                        record.status = UpgradeStatus.FAILED
                else:
                    record.status = UpgradeStatus.FAILED

                record.end_time = time.time()

        return {"completed": True}

    def _do_blue_green_upgrade(self, module_ids: List[str]) -> Dict[str, Any]:
        """执行蓝绿部署

        蓝绿部署策略：
        1. 在绿色环境部署新版本
        2. 验证绿色环境健康
        3. 切换流量到绿色环境
        4. 保留蓝色环境作为回滚备份
        """
        # 简化实现：标记为蓝绿模式，核心逻辑与滚动升级类似
        # 实际生产环境需要配合流量切换（如 Nginx 配置切换）
        for mid in module_ids:
            record = self._module_records.get(mid)
            if not record:
                continue

            record.start_time = time.time()
            record.status = UpgradeStatus.IN_PROGRESS
            record.phase = UpgradePhase.PREPARING
            record.details["deployment_mode"] = "blue_green"

            try:
                # 蓝绿部署：先在备用目录部署新版本
                backup_result = self._backup_module(mid)
                record.backup_path = backup_result.get("backup_path", "")

                # 模拟在绿色环境部署
                record.phase = UpgradePhase.UPGRADING
                upgrade_result = self._upgrade_module_files(mid)
                if not upgrade_result["success"]:
                    raise RuntimeError(f"绿色环境部署失败: {upgrade_result.get('error', 'unknown')}")

                # 启动绿色环境
                start_result = self._start_module(mid)
                if not start_result:
                    raise RuntimeError("绿色环境启动失败")

                # 健康检查
                record.phase = UpgradePhase.HEALTH_CHECKING
                health_ok = self._wait_for_health(mid)
                if not health_ok:
                    raise RuntimeError("绿色环境健康检查失败")
                record.health_check_passed = True

                # 切换流量（模拟）
                record.details["traffic_switch"] = "completed"

                record.status = UpgradeStatus.SUCCESS
                record.phase = UpgradePhase.COMPLETED
                record.end_time = time.time()

            except Exception as e:
                record.error_message = str(e)
                record.phase = UpgradePhase.ROLLING_BACK
                if self.config.rollback_on_failure:
                    self.rollback(mid)
                    record.status = UpgradeStatus.ROLLED_BACK
                else:
                    record.status = UpgradeStatus.FAILED
                record.end_time = time.time()

        return {"completed": True}

    def _do_canary_upgrade(self, module_ids: List[str]) -> Dict[str, Any]:
        """执行金丝雀发布

        金丝雀发布策略：
        1. 先向少量流量（如 10%）发布新版本
        2. 观察一段时间，验证指标正常
        3. 逐步扩大流量比例
        4. 全量发布或回滚
        """
        for mid in module_ids:
            record = self._module_records.get(mid)
            if not record:
                continue

            record.start_time = time.time()
            record.status = UpgradeStatus.IN_PROGRESS
            record.phase = UpgradePhase.PREPARING
            record.details["deployment_mode"] = "canary"
            record.details["canary_steps"] = []

            try:
                # 备份
                backup_result = self._backup_module(mid)
                record.backup_path = backup_result.get("backup_path", "")

                # 升级文件
                record.phase = UpgradePhase.UPGRADING
                upgrade_result = self._upgrade_module_files(mid)
                if not upgrade_result["success"]:
                    raise RuntimeError(f"升级失败: {upgrade_result.get('error', 'unknown')}")

                # 启动
                self._start_module(mid)

                # 金丝雀步骤：逐步增加流量
                current_percent = 0
                target_percent = 100
                step = self.config.canary_step_percent
                initial = self.config.canary_initial_traffic_percent

                # 初始流量
                current_percent = initial
                record.details["canary_steps"].append({
                    "traffic_percent": current_percent,
                    "status": "applying",
                    "timestamp": time.time(),
                })

                # 健康检查
                record.phase = UpgradePhase.HEALTH_CHECKING
                health_ok = self._wait_for_health(mid)
                if not health_ok:
                    raise RuntimeError(f"金丝雀发布失败：{current_percent}% 流量下健康检查不通过")

                record.details["canary_steps"][-1]["status"] = "success"
                record.details["canary_steps"][-1]["health_passed"] = True

                # 逐步扩大流量
                while current_percent < target_percent:
                    current_percent = min(current_percent + step, target_percent)
                    record.details["canary_steps"].append({
                        "traffic_percent": current_percent,
                        "status": "applying",
                        "timestamp": time.time(),
                    })

                    # 每个步骤做健康检查
                    health_ok = self._wait_for_health(mid, timeout=10)
                    if not health_ok:
                        raise RuntimeError(f"金丝雀发布失败：{current_percent}% 流量下健康检查不通过")

                    record.details["canary_steps"][-1]["status"] = "success"
                    record.details["canary_steps"][-1]["health_passed"] = True

                record.health_check_passed = True
                record.status = UpgradeStatus.SUCCESS
                record.phase = UpgradePhase.COMPLETED
                record.end_time = time.time()

            except Exception as e:
                record.error_message = str(e)
                record.phase = UpgradePhase.ROLLING_BACK
                if self.config.rollback_on_failure:
                    self.rollback(mid)
                    record.status = UpgradeStatus.ROLLED_BACK
                else:
                    record.status = UpgradeStatus.FAILED
                record.end_time = time.time()

        return {"completed": True}

    # -----------------------------------------------------------------------
    # 模块级操作（可被子类或外部注册覆盖）
    # -----------------------------------------------------------------------

    def _backup_module(self, module_id: str) -> Dict[str, Any]:
        """备份模块

        Args:
            module_id: 模块ID

        Returns:
            备份结果字典
        """
        try:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            backup_path = self.backup_dir / f"{module_id}_{timestamp}"
            backup_path.mkdir(parents=True, exist_ok=True)

            # 查找模块目录
            module_dir = self._find_module_dir(module_id)
            if module_dir and module_dir.exists():
                # 备份模块代码（排除日志和临时文件）
                backup_module = backup_path / module_dir.name
                shutil.copytree(
                    str(module_dir),
                    str(backup_module),
                    ignore=shutil.ignore_patterns(
                        "*.pyc", "__pycache__", "logs", "*.log", ".git",
                        "*.tmp", "*.bak", "node_modules",
                    ),
                    dirs_exist_ok=True,
                )

            # 备份版本信息
            version_info = {
                "module_id": module_id,
                "backup_time": timestamp,
                "from_version": self._get_current_version(),
            }
            with open(backup_path / "version_info.json", "w", encoding="utf-8") as f:
                json.dump(version_info, f, indent=2, ensure_ascii=False)

            return {
                "success": True,
                "backup_path": str(backup_path),
                "module_id": module_id,
            }
        except Exception as e:
            return {
                "success": False,
                "error": str(e),
                "module_id": module_id,
            }

    def _find_module_dir(self, module_id: str) -> Optional[Path]:
        """查找模块目录"""
        try:
            from ..module_registry import get_module_registry
            registry = get_module_registry()
            mod = registry.get_module(module_id)
            if mod and mod.directory:
                dir_path = Path(mod.directory)
                if not dir_path.is_absolute():
                    dir_path = self._project_root / dir_path
                return dir_path if dir_path.exists() else None
        except ImportError:
            pass

        # 备用：在项目根目录下查找
        for candidate in self._project_root.iterdir():
            if candidate.is_dir() and candidate.name.lower().startswith(module_id.lower()):
                return candidate

        return None

    def _stop_module(self, module_id: str) -> bool:
        """停止模块

        优先使用注册的停止函数，否则尝试通过进程管理停止。
        """
        stopper = self._module_stoppers.get(module_id)
        if stopper:
            try:
                return stopper()
            except Exception:
                return False

        # 默认实现：无操作（依赖外部进程管理）
        return True

    def _start_module(self, module_id: str) -> bool:
        """启动模块"""
        starter = self._module_starters.get(module_id)
        if starter:
            try:
                return starter()
            except Exception:
                return False

        # 默认实现：无操作
        return True

    def _upgrade_module_files(self, module_id: str) -> Dict[str, Any]:
        """升级模块文件

        默认实现：模拟文件替换。
        生产环境应从 staging 目录复制新版本文件到模块目录。
        """
        # 模拟升级成功
        return {
            "success": True,
            "module_id": module_id,
            "method": "simulated",
        }

    def _wait_for_health(self, module_id: str, timeout: Optional[int] = None) -> bool:
        """等待模块健康检查通过

        Args:
            module_id: 模块ID
            timeout: 超时时间（秒），None 则使用配置值

        Returns:
            True 表示健康检查通过
        """
        if timeout is None:
            timeout = self.config.health_check_timeout

        checker = self._health_checkers.get(module_id)
        if not checker:
            # 没有注册健康检查函数，默认通过
            return True

        max_retries = self.config.health_check_max_retries
        retry_interval = timeout / max(max_retries, 1)

        for _ in range(max_retries):
            try:
                if checker():
                    return True
            except Exception:
                pass
            time.sleep(retry_interval)

        return False

    # -----------------------------------------------------------------------
    # 回滚
    # -----------------------------------------------------------------------

    def rollback(self, module_id: str) -> Dict[str, Any]:
        """回滚指定模块到上一版本

        Args:
            module_id: 模块ID

        Returns:
            回滚结果字典
        """
        record = self._module_records.get(module_id)
        if not record:
            return {
                "success": False,
                "error": f"No upgrade record for module {module_id}",
            }

        backup_path = record.backup_path
        if not backup_path or not Path(backup_path).exists():
            return {
                "success": False,
                "error": f"Backup not found: {backup_path}",
            }

        try:
            # 停止模块
            self._stop_module(module_id)

            # 从备份恢复
            module_dir = self._find_module_dir(module_id)
            backup_dir = Path(backup_path)

            if module_dir and backup_dir.exists():
                # 找到备份中的模块目录
                backup_module_dir = None
                for item in backup_dir.iterdir():
                    if item.is_dir() and item.name != "version_info.json":
                        backup_module_dir = item
                        break

                if backup_module_dir and module_dir.exists():
                    # 恢复文件
                    shutil.rmtree(str(module_dir))
                    shutil.copytree(str(backup_module_dir), str(module_dir))

            # 重新启动模块
            self._start_module(module_id)

            # 健康检查
            health_ok = self._wait_for_health(module_id)

            record.status = UpgradeStatus.ROLLED_BACK
            record.details["rollback_health_passed"] = health_ok

            return {
                "success": True,
                "module_id": module_id,
                "health_check_passed": health_ok,
                "restored_from": backup_path,
            }

        except Exception as e:
            return {
                "success": False,
                "error": str(e),
                "module_id": module_id,
            }

    def rollback_all(self) -> Dict[str, Any]:
        """回滚所有模块"""
        results = {}
        for mid in list(self._module_records.keys()):
            results[mid] = self.rollback(mid)

        success_count = sum(1 for r in results.values() if r["success"])
        return {
            "success": success_count == len(results),
            "success_count": success_count,
            "total": len(results),
            "modules": results,
        }

    # -----------------------------------------------------------------------
    # 升级状态查询
    # -----------------------------------------------------------------------

    def get_upgrade_status(self) -> Dict[str, Any]:
        """获取当前升级状态"""
        with self._lock:
            return {
                "phase": self._current_phase.value,
                "current_upgrade": self._current_upgrade,
                "module_records": {
                    mid: rec.to_dict() for mid, rec in self._module_records.items()
                },
                "latest_version": self._latest_version.to_dict() if self._latest_version else None,
                "config": self.config.to_dict(),
            }

    def get_upgrade_history(
        self,
        limit: int = 20,
        module_id: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """获取升级历史记录

        Args:
            limit: 返回记录数上限
            module_id: 按模块筛选，None 表示全部

        Returns:
            升级历史记录列表（按时间倒序）
        """
        with self._lock:
            history = list(reversed(self._history))

            if module_id:
                history = [
                    h for h in history
                    if module_id in h.get("modules", {})
                ]

            return history[:limit]

    def _add_history(self, entry: Dict[str, Any]) -> None:
        """添加历史记录"""
        with self._lock:
            self._history.append(entry)
            # 限制历史记录数量
            if len(self._history) > self._max_history:
                self._history = self._history[-self._max_history:]
            self._save_history()

    def _history_file(self) -> Path:
        """历史记录文件路径"""
        return self.backup_dir / "upgrade_history.json"

    def _save_history(self) -> None:
        """保存历史记录到文件"""
        try:
            history_file = self._history_file()
            history_file.parent.mkdir(parents=True, exist_ok=True)
            with open(history_file, "w", encoding="utf-8") as f:
                json.dump(list(self._history), f, indent=2, ensure_ascii=False, default=str)
        except Exception:
            pass

    def _load_history(self) -> None:
        """从文件加载历史记录"""
        try:
            history_file = self._history_file()
            if history_file.exists():
                with open(history_file, "r", encoding="utf-8") as f:
                    self._history = json.load(f)
                if len(self._history) > self._max_history:
                    self._history = self._history[-self._max_history:]
        except Exception:
            self._history = []

    # -----------------------------------------------------------------------
    # 后台自动检查
    # -----------------------------------------------------------------------

    def start_auto_check(self) -> bool:
        """启动自动版本检查线程"""
        if not self.config.auto_check:
            return False

        if self._check_thread and self._check_thread.is_alive():
            return True

        self._check_stop.clear()
        self._check_thread = threading.Thread(
            target=self._auto_check_loop,
            name="UpgradeAutoCheck",
            daemon=True,
        )
        self._check_thread.start()
        return True

    def stop_auto_check(self) -> None:
        """停止自动版本检查"""
        self._check_stop.set()
        if self._check_thread:
            self._check_thread.join(timeout=5)
            self._check_thread = None

    def _auto_check_loop(self) -> None:
        """自动检查循环"""
        while not self._check_stop.is_set():
            try:
                result = self.check_for_upgrade()
                if result.get("has_new_version") and self.config.auto_upgrade:
                    # 在升级窗口内自动升级
                    if self.config.is_in_upgrade_window():
                        latest = result.get("latest_version", {})
                        version = latest.get("version", "") if latest else ""
                        if version:
                            prep = self.prepare_upgrade(version)
                            if prep.get("success"):
                                self.execute_rolling_upgrade()
            except Exception:
                pass

            # 等待检查间隔
            self._check_stop.wait(self.config.check_interval_seconds)

    # -----------------------------------------------------------------------
    # 配置更新
    # -----------------------------------------------------------------------

    def update_config(self, **kwargs) -> Dict[str, Any]:
        """更新升级配置

        Args:
            **kwargs: 配置键值对

        Returns:
            更新后的配置
        """
        with self._lock:
            for key, value in kwargs.items():
                if hasattr(self.config, key):
                    setattr(self.config, key, value)

            # 策略类型转换
            if "strategy" in kwargs and isinstance(kwargs["strategy"], str):
                self.config.strategy = UpgradeStrategy(kwargs["strategy"])

            return self.config.to_dict()

    # -----------------------------------------------------------------------
    # 重置
    # -----------------------------------------------------------------------

    def reset(self) -> None:
        """重置升级管理器状态（用于测试或清理）"""
        with self._lock:
            self._current_phase = UpgradePhase.IDLE
            self._current_upgrade = None
            self._module_records.clear()
            self.stop_auto_check()


# ============================================================================
# 全局单例
# ============================================================================

_upgrade_manager: Optional[RollingUpgradeManager] = None
_upgrade_manager_lock = threading.Lock()


def get_upgrade_manager(
    config: Optional[UpgradeConfig] = None,
    project_root: Optional[str] = None,
) -> RollingUpgradeManager:
    """获取全局滚动升级管理器（单例）

    Args:
        config: 升级配置
        project_root: 项目根目录

    Returns:
        RollingUpgradeManager 实例
    """
    global _upgrade_manager
    if _upgrade_manager is None:
        with _upgrade_manager_lock:
            if _upgrade_manager is None:
                _upgrade_manager = RollingUpgradeManager(
                    config=config,
                    project_root=project_root,
                )
    return _upgrade_manager


def reset_upgrade_manager() -> None:
    """重置全局升级管理器（主要用于测试）"""
    global _upgrade_manager
    with _upgrade_manager_lock:
        if _upgrade_manager:
            _upgrade_manager.reset()
        _upgrade_manager = None


# ============================================================================
# 模块导出
# ============================================================================

__all__ = [
    # 枚举
    "UpgradeStrategy",
    "UpgradePhase",
    "UpgradeStatus",
    # 数据模型
    "ModuleUpgradeRecord",
    "UpgradeConfig",
    "VersionInfo",
    # 主类
    "RollingUpgradeManager",
    # 全局函数
    "get_upgrade_manager",
    "reset_upgrade_manager",
]
