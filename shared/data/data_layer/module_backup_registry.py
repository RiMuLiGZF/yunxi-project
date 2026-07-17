"""
模块备份配置注册表（第二阶段统一治理）

集中管理所有模块的备份配置，
确保所有有独立数据库的模块都接入 M8 统一备份调度中心。

每个模块的配置包括：
- 模块ID和名称
- 数据库文件路径列表
- 备份策略（类型/压缩/加密/保留）
- 调度计划
- 备份端点（如果模块提供了API）

使用方式：
    from shared.data.data_layer.module_backup_registry import (
        get_all_module_configs,
        get_module_config,
        register_modules_with_orchestrator,
    )
"""
import sys
from pathlib import Path
from typing import Dict, List, Optional, Any

# 将项目根目录加入 path
_project_root = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(_project_root))

# 同时支持包内相对导入和脚本直接运行
try:
    from .backup_manager import (
        ModuleBackupConfig,
        BackupType,
        CompressionType,
        EncryptionType,
        RetentionPolicy,
        BackupOrchestrator,
    )
except ImportError:
    from backup_manager import (  # type: ignore
        ModuleBackupConfig,
        BackupType,
        CompressionType,
        EncryptionType,
        RetentionPolicy,
        BackupOrchestrator,
    )


# ============================================================
# 模块数据库路径发现
# ============================================================

def _find_db_files(base_dir: Path, pattern: str = "*.db",
                   exclude_backups: bool = True) -> List[str]:
    """在目录中查找数据库文件

    Args:
        base_dir: 基础目录
        pattern: 文件匹配模式
        exclude_backups: 是否排除备份目录中的数据库

    Returns:
        数据库文件绝对路径列表
    """
    db_files = []
    if not base_dir.exists():
        return db_files

    for db_file in base_dir.rglob(pattern):
        if not db_file.is_file():
            continue
        # 排除备份目录
        if exclude_backups and "backup" in str(db_file).lower():
            continue
        # 排除 WAL 和 SHM 文件
        if db_file.suffix not in (".db", ".sqlite"):
            continue
        db_files.append(str(db_file))

    return sorted(db_files)


def _find_module_dir(module_prefix: str) -> Optional[Path]:
    """查找模块目录

    Args:
        module_prefix: 模块前缀，如 "M4"、"m5"

    Returns:
        模块目录 Path，找不到返回 None
    """
    for item in _project_root.iterdir():
        if not item.is_dir():
            continue
        name_lower = item.name.lower()
        prefix_lower = module_prefix.lower()
        if name_lower.startswith(prefix_lower + "-") or name_lower == prefix_lower:
            return item
    return None


# ============================================================
# 各模块备份配置定义
# ============================================================

def _build_m4_config() -> ModuleBackupConfig:
    """M4 场景引擎 备份配置"""
    module_dir = _find_module_dir("M4")
    data_dir = module_dir / "data" if module_dir else _project_root / "M4-scene-engine" / "data"

    db_paths = _find_db_files(data_dir)

    backup_dir = str(_project_root / "backups" / "module_backups" / "m4")

    return ModuleBackupConfig(
        module_id="m4",
        db_paths=db_paths,
        backup_dir=backup_dir,
        max_backups=30,
        schedule={"type": "daily", "time": "03:00"},
        backup_type=BackupType.FULL,
        compression=CompressionType.GZIP,
        encryption=EncryptionType.NONE,
        retention=RetentionPolicy(
            strategy="hybrid",
            max_count=30,
            max_age_days=30,
            max_size_gb=5.0,
        ),
    )


def _build_m5_config() -> ModuleBackupConfig:
    """M5 潮汐记忆 备份配置

    M5 有多个数据库文件：
    - memory/l1_shallow.db (短期记忆)
    - memory/l2_deep.db (长期记忆)
    - memory/l3_abyss/index.db (深层记忆索引)
    - growth/growth.db (成长数据)
    """
    module_dir = _find_module_dir("M5")
    data_dir = module_dir / "data" if module_dir else _project_root / "M5-tide-memory" / "data"

    db_paths = _find_db_files(data_dir)

    backup_dir = str(_project_root / "backups" / "module_backups" / "m5")

    return ModuleBackupConfig(
        module_id="m5",
        db_paths=db_paths,
        backup_dir=backup_dir,
        max_backups=30,
        schedule={"type": "daily", "time": "03:30"},
        backup_type=BackupType.FULL,
        compression=CompressionType.GZIP,
        encryption=EncryptionType.NONE,
        retention=RetentionPolicy(
            strategy="hybrid",
            max_count=30,
            max_age_days=45,  # 记忆数据保留更久
            max_size_gb=10.0,
        ),
    )


def _build_m6_config() -> ModuleBackupConfig:
    """M6 硬件外设 备份配置"""
    module_dir = _find_module_dir("M6")
    data_dir = module_dir / "data" if module_dir else _project_root / "M6-hardware-peripheral" / "data"

    db_paths = _find_db_files(data_dir)

    backup_dir = str(_project_root / "backups" / "module_backups" / "m6")

    return ModuleBackupConfig(
        module_id="m6",
        db_paths=db_paths,
        backup_dir=backup_dir,
        max_backups=20,
        schedule={"type": "daily", "time": "04:00"},
        backup_type=BackupType.FULL,
        compression=CompressionType.GZIP,
        encryption=EncryptionType.NONE,
        retention=RetentionPolicy(
            strategy="count",
            max_count=20,
            max_age_days=20,
        ),
    )


def _build_m8_config() -> ModuleBackupConfig:
    """M8 控制塔 备份配置

    M8 自身也需要备份，作为调度中心，
    备份频率更高一些。
    """
    module_dir = _find_module_dir("M8")
    data_dir = module_dir / "backend" / "data" if module_dir else _project_root / "M8-control-tower" / "backend" / "data"

    db_paths = _find_db_files(data_dir)

    backup_dir = str(_project_root / "backups" / "module_backups" / "m8")

    return ModuleBackupConfig(
        module_id="m8",
        db_paths=db_paths,
        backup_dir=backup_dir,
        max_backups=50,  # 调度中心保留更多备份
        schedule={"type": "daily", "time": "02:00"},  # 最早备份，确保数据最新
        backup_type=BackupType.FULL,
        compression=CompressionType.GZIP,
        encryption=EncryptionType.NONE,
        retention=RetentionPolicy(
            strategy="hybrid",
            max_count=50,
            max_age_days=60,
            max_size_gb=5.0,
        ),
    )


def _build_m10_config() -> ModuleBackupConfig:
    """M10 系统卫士 备份配置"""
    module_dir = _find_module_dir("M10")
    data_dir = module_dir / "data" if module_dir else _project_root / "M10-system-guard" / "data"

    db_paths = _find_db_files(data_dir)

    backup_dir = str(_project_root / "backups" / "module_backups" / "m10")

    return ModuleBackupConfig(
        module_id="m10",
        db_paths=db_paths,
        backup_dir=backup_dir,
        max_backups=30,
        schedule={"type": "daily", "time": "04:30"},
        backup_type=BackupType.FULL,
        compression=CompressionType.GZIP,
        encryption=EncryptionType.NONE,
        retention=RetentionPolicy(
            strategy="hybrid",
            max_count=30,
            max_age_days=30,
            max_size_gb=3.0,
        ),
    )


def _build_m12_config() -> ModuleBackupConfig:
    """M12 安全盾 备份配置"""
    module_dir = _find_module_dir("M12")
    data_dir = module_dir / "data" if module_dir else _project_root / "M12-security-shield" / "data"

    db_paths = _find_db_files(data_dir)

    backup_dir = str(_project_root / "backups" / "module_backups" / "m12")

    return ModuleBackupConfig(
        module_id="m12",
        db_paths=db_paths,
        backup_dir=backup_dir,
        max_backups=30,
        schedule={"type": "daily", "time": "05:00"},
        backup_type=BackupType.FULL,
        compression=CompressionType.GZIP,
        encryption=EncryptionType.NONE,
        retention=RetentionPolicy(
            strategy="hybrid",
            max_count=30,
            max_age_days=90,  # 安全数据保留更久
            max_size_gb=2.0,
        ),
    )


def _build_m9_config() -> ModuleBackupConfig:
    """M9 开发工坊 备份配置"""
    module_dir = _find_module_dir("M9")
    data_dir = module_dir / "data" if module_dir else _project_root / "M9-dev-workshop" / "data"

    db_paths = _find_db_files(data_dir)

    backup_dir = str(_project_root / "backups" / "module_backups" / "m9")

    return ModuleBackupConfig(
        module_id="m9",
        db_paths=db_paths,
        backup_dir=backup_dir,
        max_backups=30,
        schedule={"type": "daily", "time": "03:00"},
        backup_type=BackupType.FULL,
        compression=CompressionType.GZIP,
        encryption=EncryptionType.NONE,
        retention=RetentionPolicy(
            strategy="hybrid",
            max_count=30,
            max_age_days=30,
            max_size_gb=5.0,
        ),
    )


# 模块配置构建函数映射
_MODULE_BUILDERS = {
    "m4": _build_m4_config,
    "m5": _build_m5_config,
    "m6": _build_m6_config,
    "m8": _build_m8_config,
    "m9": _build_m9_config,
    "m10": _build_m10_config,
    "m12": _build_m12_config,
}


# ============================================================
# 公共 API
# ============================================================

def get_module_config(module_id: str) -> Optional[ModuleBackupConfig]:
    """获取指定模块的备份配置

    Args:
        module_id: 模块ID，如 "m4"、"m5"

    Returns:
        模块备份配置，找不到返回 None
    """
    module_id = module_id.lower()
    builder = _MODULE_BUILDERS.get(module_id)
    if not builder:
        return None
    try:
        return builder()
    except Exception:
        return None


def get_all_module_configs() -> Dict[str, ModuleBackupConfig]:
    """获取所有已注册模块的备份配置

    Returns:
        {module_id: ModuleBackupConfig} 字典
    """
    configs = {}
    for module_id, builder in _MODULE_BUILDERS.items():
        try:
            config = builder()
            if config.db_paths:  # 只有找到数据库的模块才加入
                configs[module_id] = config
        except Exception:
            continue
    return configs


def register_modules_with_orchestrator(
    orchestrator: BackupOrchestrator,
    module_ids: Optional[List[str]] = None,
) -> Dict[str, bool]:
    """将模块备份配置注册到调度中心

    Args:
        orchestrator: BackupOrchestrator 实例
        module_ids: 要注册的模块ID列表，None 表示注册所有

    Returns:
        {module_id: 是否注册成功} 字典
    """
    results = {}

    if module_ids:
        builders = {mid: _MODULE_BUILDERS[mid] for mid in module_ids if mid in _MODULE_BUILDERS}
    else:
        builders = _MODULE_BUILDERS

    for module_id, builder in builders.items():
        try:
            config = builder()
            if not config.db_paths:
                results[module_id] = False
                continue
            success = orchestrator.register_module(config)
            results[module_id] = success
        except Exception:
            results[module_id] = False

    return results


def get_modules_with_db() -> List[str]:
    """获取所有有数据库文件的模块列表

    Returns:
        模块ID列表
    """
    modules = []
    for module_id, builder in _MODULE_BUILDERS.items():
        try:
            config = builder()
            if config.db_paths:
                modules.append(module_id)
        except Exception:
            continue
    return sorted(modules)


def get_module_backup_summary() -> Dict[str, Any]:
    """获取所有模块备份配置摘要

    Returns:
        模块备份配置摘要字典
    """
    summary = {}
    configs = get_all_module_configs()

    for module_id, config in configs.items():
        summary[module_id] = {
            "module_id": config.module_id,
            "db_count": len(config.db_paths),
            "db_paths": config.db_paths,
            "backup_dir": config.backup_dir,
            "backup_type": config.backup_type,
            "compression": config.compression,
            "encryption": config.encryption,
            "schedule": config.schedule,
            "max_backups": config.max_backups,
            "retention_strategy": config.retention.strategy,
        }

    return summary


# ============================================================
# 模块导出
# ============================================================

__all__ = [
    "get_module_config",
    "get_all_module_configs",
    "register_modules_with_orchestrator",
    "get_modules_with_db",
    "get_module_backup_summary",
]
