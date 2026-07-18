"""
M10 系统卫士 - 配置管理模块

统一配置框架迁移版：
- 新接口：M10ModuleConfig（继承 BaseConfig，基于 pydantic-settings）
- 旧接口：M10Config + 子模型（保留，向后兼容）

统一管理所有配置，支持环境变量覆盖。
沙盒模式优先：默认使用模拟数据，不调用真实系统 API。
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field


# ============================================================
# 尝试从统一配置基类导入
# ============================================================

try:
    _current = Path(__file__).resolve()
    for _ in range(10):
        _current = _current.parent
        if (_current / "shared" / "core" / "config.py").exists():
            if str(_current) not in sys.path:
                sys.path.insert(0, str(_current))
            break
    from shared.core.config import BaseConfig, EnvType
    from pydantic_settings import SettingsConfigDict
    _USE_UNIFIED_CONFIG = True
except ImportError:
    _USE_UNIFIED_CONFIG = False


# ============================================================
# 配置子模型（保持不变，作为子配置使用）
# ============================================================

class BasicConfig(BaseModel):
    """基础配置."""
    name: str = "m10-system-guard"
    version: str = "1.2.0"
    port: int = 8010
    host: str = "0.0.0.0"
    log_level: str = "info"
    env: str = "development"


class SandboxConfig(BaseModel):
    """沙盒模式配置.

    沙盒模式下所有系统数据使用模拟生成，不调用真实系统 API，
    避免占用过多系统资源。
    """
    enabled: bool = False
    mock_cpu_range: tuple = (10.0, 60.0)
    mock_memory_range: tuple = (30.0, 70.0)
    mock_disk_range: tuple = (40.0, 80.0)
    mock_network_speed_range: tuple = (0.5, 50.0)
    mock_gpu_range: tuple = (5.0, 40.0)
    mock_temperature_range: tuple = (40.0, 75.0)
    mock_battery_range: tuple = (20.0, 100.0)
    mock_process_count: int = 120
    sample_interval_seconds: float = 1.0

    # 真实 GPU 采集（非沙盒模式）
    gpu_polling_interval_ms: int = 500
    gpu_monitor_processes: bool = True
    gpu_memory_warning_percent: float = 80.0
    gpu_temp_warning_celsius: float = 85.0
    gpu_power_warning_percent: float = 90.0


class GuardThresholdConfig(BaseModel):
    """防护阈值配置.

    分级拦截策略：提示/警告/严重/紧急 四级
    """
    cpu_info: float = 60.0
    cpu_warning: float = 75.0
    cpu_critical: float = 85.0
    cpu_emergency: float = 95.0

    memory_info: float = 65.0
    memory_warning: float = 80.0
    memory_critical: float = 90.0
    memory_emergency: float = 95.0

    temp_info: float = 60.0
    temp_warning: float = 70.0
    temp_critical: float = 80.0
    temp_emergency: float = 90.0

    disk_info: float = 70.0
    disk_warning: float = 85.0
    disk_critical: float = 92.0
    disk_emergency: float = 98.0


class ProcessConfig(BaseModel):
    """进程管理配置."""
    vscode_max_instances: int = 5
    top_n_default: int = 10
    yunxi_process_patterns: list = Field(default_factory=lambda: [
        "yunxi", "m1-", "m2-", "m3-", "m4-", "m5-",
        "m6-", "m7-", "m8-", "m9-", "m10-",
        "trae", "agent", "python.*yunxi",
    ])
    vscode_process_patterns: list = Field(default_factory=lambda: [
        "code", "vscode", "Code.exe", "code-insiders",
    ])


class StartupCheckConfig(BaseModel):
    """启动安全检查配置."""
    heavy_task_min_memory_free_percent: float = 20.0
    heavy_task_max_cpu_percent: float = 70.0
    heavy_task_max_temp: float = 75.0
    heavy_task_max_same_process: int = 3


class SandboxSchedulerConfig(BaseModel):
    """沙箱任务调度配置."""
    light_max_cpu: float = 80.0
    light_max_memory: float = 85.0

    normal_max_cpu: float = 70.0
    normal_max_memory: float = 75.0

    heavy_max_cpu: float = 60.0
    heavy_max_memory: float = 65.0

    super_heavy_max_cpu: float = 50.0
    super_heavy_max_memory: float = 55.0

    max_queue_size: int = 100
    queue_check_interval: float = 2.0


class AuditConfig(BaseModel):
    """审计日志配置."""
    log_dir: str = "./logs"
    max_file_size_mb: int = 50
    max_files: int = 10
    retention_days: int = 30


class ReportConfig(BaseModel):
    """报告生成配置."""
    report_dir: str = "./reports"
    daily_report_time: str = "23:59"
    weekly_report_day: int = 0


class DataAggregationConfig(BaseModel):
    """数据聚合配置."""
    raw_retention_minutes: int = 60
    minute_retention_hours: int = 24
    hour_retention_days: int = 7
    day_retention_days: int = 30


# ============================================================
# M10 模块统一配置类（新接口）
# ============================================================

if _USE_UNIFIED_CONFIG:

    class M10ModuleConfig(BaseConfig):
        """
        M10 系统卫士模块配置（统一配置框架版）

        继承自 BaseConfig，自动获得：
        - .env 文件加载
        - 环境变量覆盖
        - 生产环境敏感字段校验
        - 敏感字段脱敏
        - 配置热更新

        环境变量前缀：M10_
        """

        module_name: str = Field(default="m10-system-guard", description="模块名称")
        port: int = Field(default=8010, ge=1, le=65535, description="服务监听端口")

        # 子配置
        basic: BasicConfig = Field(default_factory=BasicConfig)
        sandbox: SandboxConfig = Field(default_factory=SandboxConfig)
        guard_threshold: GuardThresholdConfig = Field(default_factory=GuardThresholdConfig)
        process: ProcessConfig = Field(default_factory=ProcessConfig)
        startup_check: StartupCheckConfig = Field(default_factory=StartupCheckConfig)
        sandbox_scheduler: SandboxSchedulerConfig = Field(default_factory=SandboxSchedulerConfig)
        audit: AuditConfig = Field(default_factory=AuditConfig)
        report: ReportConfig = Field(default_factory=ReportConfig)
        data_aggregation: DataAggregationConfig = Field(default_factory=DataAggregationConfig)

        # CORS
        cors_origins: str = Field(
            default="http://localhost:3000,http://localhost:5173,http://127.0.0.1:3000,http://127.0.0.1:5173",
            description="CORS 允许的来源（逗号分隔）",
        )

        model_config = SettingsConfigDict(
            env_prefix="M10_",
            env_file=".env",
            env_file_encoding="utf-8",
            extra="allow",
            validate_assignment=True,
            nested_model_default_partial_update=True,
        )

        def reload_config(self) -> "M10ModuleConfig":
            """重新加载配置（兼容旧接口名）"""
            self.reload()
            return self


    # 全局配置单例（新接口）
    _m10_config: M10ModuleConfig | None = None

    def get_m10_config() -> M10ModuleConfig:
        """获取 M10 模块配置实例（单例模式，统一配置框架）"""
        global _m10_config
        if _m10_config is None:
            _m10_config = M10ModuleConfig()
        return _m10_config

else:
    M10ModuleConfig = None  # type: ignore
    get_m10_config = None  # type: ignore


# ============================================================
# 旧接口：M10Config（向后兼容）
# ============================================================

class M10Config(BaseModel):
    """
    M10 系统卫士全局配置（向后兼容层）

    .. deprecated:: 2.0.0
        请使用 M10ModuleConfig 替代。
    """
    basic: BasicConfig = Field(default_factory=BasicConfig)
    sandbox: SandboxConfig = Field(default_factory=SandboxConfig)
    guard_threshold: GuardThresholdConfig = Field(default_factory=GuardThresholdConfig)
    process: ProcessConfig = Field(default_factory=ProcessConfig)
    startup_check: StartupCheckConfig = Field(default_factory=StartupCheckConfig)
    sandbox_scheduler: SandboxSchedulerConfig = Field(default_factory=SandboxSchedulerConfig)
    audit: AuditConfig = Field(default_factory=AuditConfig)
    report: ReportConfig = Field(default_factory=ReportConfig)
    data_aggregation: DataAggregationConfig = Field(default_factory=DataAggregationConfig)
    cors_origins: str = "http://localhost:3000,http://localhost:5173,http://127.0.0.1:3000,http://127.0.0.1:5173"


# ============================================================
# 配置加载函数（向后兼容）
# ============================================================

_config_instance = None


def _apply_env_overrides(config):
    """应用环境变量覆盖配置（旧逻辑，保留以确保向后兼容）"""
    if os.getenv("M10_PORT"):
        config.basic.port = int(os.getenv("M10_PORT", "8010"))
    if os.getenv("M10_HOST"):
        config.basic.host = os.getenv("M10_HOST", "0.0.0.0")
    if os.getenv("M10_LOG_LEVEL"):
        config.basic.log_level = os.getenv("M10_LOG_LEVEL", "info")
    if os.getenv("M10_ENV"):
        config.basic.env = os.getenv("M10_ENV", "development")

    sandbox_enabled = os.getenv("M10_SANDBOX_ENABLED", "").lower()
    if sandbox_enabled in ("true", "1", "yes"):
        config.sandbox.enabled = True
    elif sandbox_enabled in ("false", "0", "no"):
        config.sandbox.enabled = False

    if os.getenv("M10_CORS_ORIGINS"):
        config.cors_origins = os.getenv("M10_CORS_ORIGINS", "")

    return config


def load_config(config_path=None):
    """加载配置（向后兼容旧接口）

    优先级：
    1. 指定的配置文件
    2. 环境变量覆盖
    3. 默认配置
    """
    global _config_instance

    config_dict = {}

    if config_path:
        path = Path(config_path)
        if path.exists():
            try:
                import yaml
                with open(path, "r", encoding="utf-8") as f:
                    config_dict = yaml.safe_load(f) or {}
            except ImportError:
                pass
            except Exception:
                pass

    config = M10Config(**config_dict)
    config = _apply_env_overrides(config)
    _config_instance = config
    return config


def get_config():
    """获取全局配置单例（向后兼容旧接口）"""
    global _config_instance
    if _config_instance is None:
        _config_instance = load_config()
    return _config_instance


def reload_config():
    """重新加载配置（向后兼容旧接口）"""
    global _config_instance
    _config_instance = None
    return get_config()


# ============================================================
# 系统版本号（统一从 shared.version 导入）
# ============================================================

def _load_system_version() -> str:
    """从 shared.version 导入系统版本号，导入失败则回退到默认值"""
    try:
        current = Path(__file__).resolve().parent
        for _ in range(10):
            if (current / "shared" / "version.py").exists():
                if str(current) not in sys.path:
                    sys.path.insert(0, str(current))
                break
            current = current.parent
        from shared.core.version import SYSTEM_VERSION
        return SYSTEM_VERSION
    except Exception:
        return "v1.0.0"


SYSTEM_VERSION = _load_system_version()
