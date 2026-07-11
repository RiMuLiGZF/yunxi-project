"""
统一数据库配置

约定各模块数据库文件路径规范，提供统一的数据库 URL 生成工具。
路径规范：~/.yunxi/db/{module_name}.db
"""

import os
from pathlib import Path
from typing import Optional


def get_yunxi_data_dir() -> Path:
    """获取云汐系统数据根目录.

    优先级：
    1. 环境变量 YUNXI_DATA_DIR
    2. ~/.yunxi/

    Returns:
        数据根目录路径
    """
    env_dir = os.environ.get("YUNXI_DATA_DIR", "")
    if env_dir:
        return Path(env_dir).expanduser()
    return Path.home() / ".yunxi"


def get_db_dir() -> Path:
    """获取数据库文件目录.

    Returns:
        数据库目录路径（不存在则创建）
    """
    db_dir = get_yunxi_data_dir() / "db"
    db_dir.mkdir(parents=True, exist_ok=True)
    return db_dir


def get_db_url(module_name: str, db_name: Optional[str] = None) -> str:
    """获取指定模块的 SQLite 数据库 URL.

    Args:
        module_name: 模块名称（如 m7, m8, m9）
        db_name: 数据库名（可选，默认等于 module_name）

    Returns:
        SQLAlchemy 数据库 URL（sqlite:/// 格式）

    示例:
        >>> get_db_url("m8")
        "sqlite:////home/user/.yunxi/db/m8.db"
    """
    name = db_name or module_name
    db_path = get_db_dir() / f"{name}.db"
    # SQLite URL 格式: sqlite:///absolute_path
    return f"sqlite:///{db_path}"


def get_db_path(module_name: str, db_name: Optional[str] = None) -> Path:
    """获取数据库文件的本地路径.

    Args:
        module_name: 模块名称
        db_name: 数据库名（可选）

    Returns:
        数据库文件路径
    """
    name = db_name or module_name
    return get_db_dir() / f"{name}.db"


# 各模块数据库标识常量
MODULE_DB = {
    "m1": "m1",           # M1 系统编排
    "m2": "m2",           # M2 任务中枢
    "m3": "m3",           # M3 边端云
    "m4": "m4",           # M4 场景引擎
    "m5": "m5",           # M5 潮汐记忆
    "m6": "m6",           # M6 硬件外设
    "m7": "m7",           # M7 工作流积木
    "m8": "m8",           # M8 管理控制塔
    "m9": "m9",           # M9 开发者工坊
    "m10": "m10",         # M10 系统卫士
}
