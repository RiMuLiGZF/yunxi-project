"""
云汐 M10 系统卫士 - 配置管理模块
负责管理系统全局配置，包括沙盒模式开关、采样频率、数据保留策略等
"""

import os
import sys
from pathlib import Path
from dataclasses import dataclass, field
from typing import List, Optional


def _get_base_dir() -> Path:
    """获取项目基础目录（兼容直接运行和作为模块导入）"""
    if "__file__" in globals():
        return Path(__file__).resolve().parent.parent
    return Path.cwd()


@dataclass
class Settings:
    """系统配置类"""

    # ===== 基础路径配置 =====
    # 项目根目录
    base_dir: Path = field(default_factory=_get_base_dir)
    # 数据目录
    data_dir: Path = field(init=False)
    # 数据库路径（SQLite）
    db_path: Path = field(init=False)

    # ===== 沙盒模式配置 =====
    # 沙盒模式开关（True=使用模拟数据，False=调用真实系统API）
    sandbox_mode: bool = True
    # 采样间隔（秒）
    sampling_interval: int = 1
    # 数据保留天数
    data_retention_days: int = 7
    # 告警抑制时间（分钟）
    alert_suppression_minutes: int = 5

    # ===== 系统信息配置（模拟用） =====
    # 模拟的总内存（GB）
    mock_total_memory_gb: float = 32.0
    # 模拟的CPU核心数
    mock_cpu_cores: int = 8
    # 模拟的CPU逻辑核心数
    mock_cpu_logical: int = 16
    # 模拟的总磁盘空间（GB）
    mock_total_disk_gb: float = 1024.0
    # 模拟的GPU显存（GB）
    mock_gpu_memory_gb: float = 8.0

    # ===== 告警阈值配置 =====
    # 内存警告阈值（%）
    memory_warning_threshold: float = 80.0
    # 内存危险阈值（%）
    memory_danger_threshold: float = 90.0
    # CPU警告阈值（%）
    cpu_warning_threshold: float = 80.0
    # CPU危险阈值（%）
    cpu_danger_threshold: float = 90.0
    # 磁盘警告阈值（GB剩余）
    disk_warning_gb: float = 20.0
    # 低电量警告阈值（%）
    battery_warning_percent: float = 20.0
    # 极低电量阈值（%）
    battery_critical_percent: float = 10.0

    # ===== 服务配置 =====
    # 服务主机
    host: str = "0.0.0.0"
    # 服务端口
    port: int = 8010
    # 调试模式
    debug: bool = True
    # CORS 允许的源
    cors_origins: List[str] = field(default_factory=lambda: [
        "http://localhost:3000",
        "http://localhost:5173",
        "http://127.0.0.1:3000",
        "http://127.0.0.1:5173",
    ])

    def __post_init__(self):
        """初始化后处理：计算派生路径"""
        self.data_dir = self.base_dir / "data"
        self.db_path = self.data_dir / "yunxi_m10.db"
        # 确保数据目录存在
        self.data_dir.mkdir(parents=True, exist_ok=True)

    def get_db_url(self) -> str:
        """获取 SQLAlchemy 数据库连接 URL"""
        return f"sqlite:///{self.db_path.as_posix()}"


# 全局配置单例
_settings: Optional[Settings] = None


def get_settings() -> Settings:
    """获取全局配置实例（单例模式）"""
    global _settings
    if _settings is None:
        _settings = Settings()
    return _settings


# 兼容直接运行测试
if __name__ == "__main__":
    settings = get_settings()
    print(f"项目根目录: {settings.base_dir}")
    print(f"数据目录: {settings.data_dir}")
    print(f"数据库路径: {settings.db_path}")
    print(f"沙盒模式: {settings.sandbox_mode}")
    print(f"采样间隔: {settings.sampling_interval}秒")
    print(f"数据保留: {settings.data_retention_days}天")
    print(f"服务端口: {settings.port}")
