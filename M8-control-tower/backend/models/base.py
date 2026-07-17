"""
M8 管理工作台 - 数据库基类与连接配置

包含 SQLAlchemy Base、engine、SessionLocal 以及数据库初始化函数。
"""

from sqlalchemy import create_engine, Column, Integer, String, DateTime, Text, Boolean, Float, JSON
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from datetime import datetime
import os

Base = declarative_base()

# 从 config 读取数据库 URL
from ..config import settings  # noqa: E402

SQLALCHEMY_DATABASE_URL = settings.database_url

# 确保 data 目录存在
_db_path = SQLALCHEMY_DATABASE_URL.replace("sqlite:///", "")
os.makedirs(os.path.dirname(_db_path) if os.path.dirname(_db_path) else "./data", exist_ok=True)

engine = create_engine(
    SQLALCHEMY_DATABASE_URL,
    connect_args={"check_same_thread": False},
)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def _get_alembic_config():
    """获取 Alembic 配置对象"""
    from alembic.config import Config
    from pathlib import Path

    backend_dir = Path(__file__).parent.parent
    alembic_ini = backend_dir / "alembic.ini"
    alembic_cfg = Config(str(alembic_ini))
    # 覆盖数据库 URL，使用 settings 中的配置
    alembic_cfg.set_main_option("sqlalchemy.url", SQLALCHEMY_DATABASE_URL)
    return alembic_cfg


def init_db():
    """初始化数据库（使用 Alembic 迁移，降级时使用 create_all）"""
    import structlog
    logger = structlog.get_logger("m8.backend.models")

    try:
        from alembic import command as alembic_command
        from sqlalchemy import inspect

        alembic_cfg = _get_alembic_config()

        # 检查数据库是否为空（没有 alembic_version 表且没有业务表）
        inspector = inspect(engine)
        existing_tables = inspector.get_table_names()

        if "alembic_version" not in existing_tables and len(existing_tables) == 0:
            # 全新数据库，直接执行 upgrade 到 head
            alembic_command.upgrade(alembic_cfg, "head")
        elif "alembic_version" not in existing_tables and len(existing_tables) > 0:
            # 已有业务表但没有 alembic_version，标记为初始基线
            alembic_command.stamp(alembic_cfg, "001_initial_baseline")
            # 然后尝试升级到最新版本
            alembic_command.upgrade(alembic_cfg, "head")
        else:
            # 已有 alembic_version，正常升级
            alembic_command.upgrade(alembic_cfg, "head")

    except ImportError:
        # alembic 不可用，降级使用 create_all
        Base.metadata.create_all(bind=engine)
    except Exception as e:
        # alembic 出错时也降级使用 create_all
        logger.warning("alembic_migration_failed", error=str(e))
        Base.metadata.create_all(bind=engine)

    _seed_initial_data()


def _seed_initial_data():
    """初始化种子数据（告警等）"""
    import structlog
    logger = structlog.get_logger("m8.backend.models")

    try:
        from .alert import AlertRecord  # noqa: E402
    except ImportError:
        logger.debug("alert model not available, skipping alert seed data")
        return

    db = SessionLocal()
    try:
        # 如果告警表为空，插入预置告警
        alert_count = db.query(AlertRecord).count()
        if alert_count == 0:
            from datetime import timedelta
            now = datetime.utcnow()
            seed_alerts = [
                AlertRecord(
                    level="warning",
                    title="内存使用率偏高",
                    content="系统内存使用率已达 75%，建议关注内存占用情况",
                    source="system",
                    status="active",
                    created_at=now - timedelta(hours=1),
                ),
                AlertRecord(
                    level="info",
                    title="M5 潮汐记忆系统连接正常",
                    content="M5 模块健康检查通过，响应时间 45ms",
                    source="m5",
                    status="active",
                    created_at=now - timedelta(minutes=30),
                ),
                AlertRecord(
                    level="critical",
                    title="磁盘空间不足",
                    content="C 盘剩余空间不足 10%，请及时清理",
                    source="system",
                    status="acknowledged",
                    created_at=now - timedelta(hours=2),
                    acknowledged_at=now - timedelta(hours=1),
                    acknowledged_by="admin",
                ),
            ]
            db.add_all(seed_alerts)
            db.commit()
    finally:
        db.close()

    _seed_backup_modules()


def _seed_backup_modules():
    """初始化备份调度中心的预置模块配置（第二阶段统一治理增强版）

    为所有有独立数据库的模块预置备份配置，
    包括 M4、M5、M6、M8、M9、M10、M12 等模块。
    """
    import structlog
    logger = structlog.get_logger("m8.backend.models")

    try:
        from .backup_scheduler import BackupModule  # noqa: E402
    except ImportError:
        logger.debug("backup_scheduler model not available, skipping backup module seed data")
        return

    db = SessionLocal()
    try:
        # 如果备份模块表为空，插入预置模块
        module_count = db.query(BackupModule).count()
        if module_count > 0:
            return

        # 第二阶段统一治理：预置所有有数据库的模块
        # 备份时间错开，避免同一时刻大量IO
        preset_modules = [
            {
                "module_id": "m4",
                "module_name": "场景引擎",
                "backup_endpoint": "",
                "auth_token": "",
                "schedule_type": "daily",
                "schedule_time": "03:00",
                "schedule_interval_minutes": 0,
                "enabled": True,
                "max_backups": 30,
                "description": "M4 场景引擎模块 - 场景数据与上下文备份",
                "extra_config": {
                    "module_port": 8004,
                    "backup_type": "full",
                    "compression": "gzip",
                    "encryption": "none",
                    "retention_strategy": "hybrid",
                    "retention_max_age_days": 30,
                    "retention_max_size_gb": 5.0,
                },
            },
            {
                "module_id": "m5",
                "module_name": "潮汐记忆",
                "backup_endpoint": "",
                "auth_token": "",
                "schedule_type": "daily",
                "schedule_time": "03:30",
                "schedule_interval_minutes": 0,
                "enabled": True,
                "max_backups": 30,
                "description": "M5 潮汐记忆系统 - 长期记忆与知识备份（L1/L2/L3 多级记忆）",
                "extra_config": {
                    "module_port": 8005,
                    "backup_type": "full",
                    "compression": "gzip",
                    "encryption": "none",
                    "retention_strategy": "hybrid",
                    "retention_max_age_days": 45,
                    "retention_max_size_gb": 10.0,
                },
            },
            {
                "module_id": "m6",
                "module_name": "硬件外设",
                "backup_endpoint": "",
                "auth_token": "",
                "schedule_type": "daily",
                "schedule_time": "04:00",
                "schedule_interval_minutes": 0,
                "enabled": True,
                "max_backups": 20,
                "description": "M6 硬件外设模块 - 设备配置与传感器数据备份",
                "extra_config": {
                    "module_port": 8006,
                    "backup_type": "full",
                    "compression": "gzip",
                    "encryption": "none",
                    "retention_strategy": "count",
                    "retention_max_age_days": 20,
                    "retention_max_size_gb": 3.0,
                },
            },
            {
                "module_id": "m8",
                "module_name": "控制塔",
                "backup_endpoint": "",
                "auth_token": "",
                "schedule_type": "daily",
                "schedule_time": "02:00",
                "schedule_interval_minutes": 0,
                "enabled": True,
                "max_backups": 50,
                "description": "M8 控制塔 - 调度中心自身数据备份（用户、配置、审计日志等）",
                "extra_config": {
                    "module_port": 8008,
                    "backup_type": "full",
                    "compression": "gzip",
                    "encryption": "none",
                    "retention_strategy": "hybrid",
                    "retention_max_age_days": 60,
                    "retention_max_size_gb": 5.0,
                    "data_dir": "M8-control-tower/backend/data",
                },
            },
            {
                "module_id": "m9",
                "module_name": "开发工坊",
                "backup_endpoint": "",
                "auth_token": "",
                "schedule_type": "daily",
                "schedule_time": "03:00",
                "schedule_interval_minutes": 0,
                "enabled": True,
                "max_backups": 30,
                "description": "M9 开发工坊 - 项目与代码备份",
                "extra_config": {
                    "module_port": 8009,
                    "backup_type": "full",
                    "compression": "gzip",
                    "encryption": "none",
                    "retention_strategy": "hybrid",
                    "retention_max_age_days": 30,
                    "retention_max_size_gb": 5.0,
                },
            },
            {
                "module_id": "m10",
                "module_name": "系统卫士",
                "backup_endpoint": "",
                "auth_token": "",
                "schedule_type": "daily",
                "schedule_time": "04:30",
                "schedule_interval_minutes": 0,
                "enabled": True,
                "max_backups": 30,
                "description": "M10 系统卫士 - 安全策略与系统监控数据备份",
                "extra_config": {
                    "module_port": 8010,
                    "backup_type": "full",
                    "compression": "gzip",
                    "encryption": "none",
                    "retention_strategy": "hybrid",
                    "retention_max_age_days": 30,
                    "retention_max_size_gb": 3.0,
                },
            },
            {
                "module_id": "m12",
                "module_name": "安全盾",
                "backup_endpoint": "",
                "auth_token": "",
                "schedule_type": "daily",
                "schedule_time": "05:00",
                "schedule_interval_minutes": 0,
                "enabled": True,
                "max_backups": 30,
                "description": "M12 安全盾 - 安全规则与审计数据备份",
                "extra_config": {
                    "module_port": 8012,
                    "backup_type": "full",
                    "compression": "gzip",
                    "encryption": "none",
                    "retention_strategy": "hybrid",
                    "retention_max_age_days": 90,
                    "retention_max_size_gb": 2.0,
                },
            },
        ]

        for config in preset_modules:
            module = BackupModule(**config)
            db.add(module)

        db.commit()
        logger.info(f"备份调度中心预置模块已初始化，共 {len(preset_modules)} 个模块（第二阶段统一治理）")
    except Exception as e:
        logger.warning(f"备份模块种子数据初始化失败: {e}")
        db.rollback()
    finally:
        db.close()


def get_db():
    """获取数据库会话"""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
