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


def get_db():
    """获取数据库会话"""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
