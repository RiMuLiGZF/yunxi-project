"""本地数据管理器单例.

管理 ~/.yunxi/ 下的所有本地数据。
"""

from __future__ import annotations

import asyncio
import json
import os
import sqlite3
import time
from pathlib import Path
from typing import Any

import aiosqlite
import structlog

from edge_cloud_kernel.migrations import create_migrator

logger = structlog.get_logger(__name__)

# 默认数据目录
DEFAULT_DATA_DIR: str = os.path.expanduser("~/.yunxi")

# 全局异步锁，保护单例创建和初始化
_init_lock: asyncio.Lock | None = None


def _get_init_lock() -> asyncio.Lock:
    """获取全局初始化锁（延迟创建，避免事件循环未启动时出错）."""
    global _init_lock
    if _init_lock is None:
        _init_lock = asyncio.Lock()
    return _init_lock


class LocalDataManager:
    """本地数据管理器（线程安全单例模式）.

    管理 ~/.yunxi/ 目录下的所有本地数据，包括：
    - 配置文件
    - 缓存数据
    - 调用日志
    - 审计记录
    - 会话状态

    线程安全:
        使用 asyncio.Lock 保护 __new__ 和 __init__ 中的竞争条件。
        推荐使用 async def initialize() 替代构造函数中的 IO 操作。

    Attributes:
        _data_dir: 数据根目录路径.
        _db_path: SQLite 数据库路径.
        _initialized: 是否已完成异步初始化.
        _data_dir_arg: 构造时传入的 data_dir 参数.
    """

    _instance: LocalDataManager | None = None

    def __new__(cls, data_dir: str | None = None) -> LocalDataManager:
        """单例模式实现.

        注意: 此方法仅分配实例，不执行 IO 操作。
        完整的初始化（目录创建、数据库初始化等）应通过
        async def initialize() 完成。

        Args:
            data_dir: 数据目录路径，仅首次创建时生效.

        Returns:
            LocalDataManager 单例实例.
        """
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
            cls._instance._data_dir_arg = data_dir
        return cls._instance

    def __init__(
        self,
        data_dir: str | None = None,
    ) -> None:
        """同步初始化 LocalDataManager（仅设置属性，不执行 IO）.

        Args:
            data_dir: 数据根目录，默认 ~/.yunxi/.
        """
        if self._initialized:
            return

        # 仅设置属性，不执行任何 IO 操作
        self._data_dir_arg = data_dir
        self._data_dir: Path = Path(data_dir or DEFAULT_DATA_DIR)

    async def initialize(self) -> None:
        """异步初始化，执行所有 IO 操作（线程安全）.

        创建目录结构、初始化数据库。应在应用启动时调用一次。
        使用 asyncio.Lock 保证并发安全。

        Returns:
            None.
        """
        if self._initialized:
            return

        lock = _get_init_lock()
        async with lock:
            # 双重检查锁定
            if self._initialized:
                return

            # 创建目录结构
            self._ensure_dirs()

            # 初始化数据库
            await self.initialize_db()

            self._initialized = True

            logger.info(
                "local_data_manager.initialized",
                data_dir=str(self._data_dir),
            )

    def _ensure_dirs(self) -> None:
        """确保所有必要的目录存在."""
        dirs = [
            "config",       # 配置文件
            "cache",        # 缓存数据
            "logs",         # 调用日志
            "audit",        # 审计记录
            "sessions",     # 会话状态
            "models",       # 模型缓存
        ]
        for d in dirs:
            (self._data_dir / d).mkdir(parents=True, exist_ok=True)

    @property
    def data_dir(self) -> Path:
        """获取数据根目录.

        Returns:
            Path: 数据根目录.
        """
        return self._data_dir

    @property
    def config_dir(self) -> Path:
        """获取配置文件目录.

        Returns:
            Path: 配置目录.
        """
        return self._data_dir / "config"

    @property
    def cache_dir(self) -> Path:
        """获取缓存目录.

        Returns:
            Path: 缓存目录.
        """
        return self._data_dir / "cache"

    @property
    def logs_dir(self) -> Path:
        """获取日志目录.

        Returns:
            Path: 日志目录.
        """
        return self._data_dir / "logs"

    @property
    def audit_dir(self) -> Path:
        """获取审计目录.

        Returns:
            Path: 审计目录.
        """
        return self._data_dir / "audit"

    @property
    def sessions_dir(self) -> Path:
        """获取会话目录.

        Returns:
            Path: 会话目录.
        """
        return self._data_dir / "sessions"

    @property
    def models_dir(self) -> Path:
        """获取模型缓存目录.

        Returns:
            Path: 模型缓存目录.
        """
        return self._data_dir / "models"

    @property
    def db_path(self) -> str:
        """获取 SQLite 数据库路径.

        Returns:
            数据库文件绝对路径.
        """
        return str(self._data_dir / "yunxi.db")

    def get_file_path(self, category: str, filename: str) -> str:
        """获取指定分类下的文件绝对路径.

        Args:
            category: 分类名称（config/cache/logs/audit/sessions/models）.
            filename: 文件名.

        Returns:
            文件绝对路径.
        """
        return str(self._data_dir / category / filename)

    def list_files(self, category: str) -> list[str]:
        """列出指定分类下的所有文件.

        Args:
            category: 分类名称.

        Returns:
            文件名列表.
        """
        dir_path = self._data_dir / category
        if not dir_path.exists():
            return []
        return [f.name for f in dir_path.iterdir() if f.is_file()]

    async def initialize_db(self) -> None:
        """初始化 SQLite 数据库及表结构（版本化迁移）.

        使用 DatabaseMigrator 进行版本化迁移管理，
        替代原有的 CREATE TABLE IF NOT EXISTS 模式。
        """
        db_path = self._data_dir / "yunxi.db"
        db_path.parent.mkdir(parents=True, exist_ok=True)

        # 使用版本化迁移管理器
        migrator = create_migrator(str(db_path))
        result = await migrator.migrate()

        logger.info(
            "local_data_manager.db_initialized",
            path=str(db_path),
            version=result["to_version"],
            applied_count=len(result["applied"]),
        )

    async def _get_conn(self) -> aiosqlite.Connection:
        """获取数据库连接（便捷方法）.

        Returns:
            aiosqlite 连接实例.
        """
        conn = await aiosqlite.connect(self.db_path)
        conn.row_factory = aiosqlite.Row
        return conn

    async def cleanup(self) -> None:
        """清理过期缓存和日志数据.

        清理内容：
        - 过期的 sessions（expires_at < now）
        - 过期的 cache_items（expires_at < now）
        - 30 天前的 call_logs
        - 90 天前的 audit_trail
        - 执行 VACUUM 优化
        """
        now = time.time()
        thirty_days_ago = now - 30 * 24 * 3600
        ninety_days_ago = now - 90 * 24 * 3600

        conn = await self._get_conn()
        try:
            # 删除过期会话
            cursor = await conn.execute(
                "DELETE FROM sessions WHERE expires_at < ?", (now,)
            )
            sessions_deleted = cursor.rowcount
            if sessions_deleted:
                logger.info(
                    "local_data_manager.cleanup_sessions", count=sessions_deleted
                )

            # 删除过期缓存
            cursor = await conn.execute(
                "DELETE FROM cache_items WHERE expires_at < ?", (now,)
            )
            cache_deleted = cursor.rowcount
            if cache_deleted:
                logger.info(
                    "local_data_manager.cleanup_cache", count=cache_deleted
                )

            # 删除 30 天前的调用日志
            cursor = await conn.execute(
                "DELETE FROM call_logs WHERE created_at < ?", (thirty_days_ago,)
            )
            logs_deleted = cursor.rowcount
            if logs_deleted:
                logger.info(
                    "local_data_manager.cleanup_call_logs", count=logs_deleted
                )

            # 删除 90 天前的审计记录
            cursor = await conn.execute(
                "DELETE FROM audit_trail WHERE created_at < ?", (ninety_days_ago,)
            )
            audit_deleted = cursor.rowcount
            if audit_deleted:
                logger.info(
                    "local_data_manager.cleanup_audit", count=audit_deleted
                )

            await conn.commit()

            # VACUUM 优化
            await conn.execute("VACUUM")

            logger.info(
                "local_data_manager.cleanup_done",
                sessions=sessions_deleted,
                cache=cache_deleted,
                call_logs=logs_deleted,
                audit=audit_deleted,
            )
        except Exception:
            await conn.rollback()
            logger.exception("local_data_manager.cleanup_failed")
            raise
        finally:
            await conn.close()

    # ------------------------------------------------------------------
    # 便捷方法：调用日志
    # ------------------------------------------------------------------

    async def save_call_log(self, record: dict) -> None:
        """保存一条调用日志.

        Args:
            record: 调用记录字典，可包含 agent_id, model, prompt_tokens,
                    completion_tokens, total_tokens, latency_ms, status,
                    error, route 等字段.
        """
        now = time.time()
        conn = await self._get_conn()
        try:
            await conn.execute(
                """
                INSERT INTO call_logs
                    (agent_id, model, prompt_tokens, completion_tokens,
                     total_tokens, latency_ms, status, error, route, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    record.get("agent_id"),
                    record.get("model"),
                    record.get("prompt_tokens", 0),
                    record.get("completion_tokens", 0),
                    record.get("total_tokens", 0),
                    record.get("latency_ms", 0),
                    record.get("status"),
                    record.get("error"),
                    record.get("route"),
                    now,
                ),
            )
            await conn.commit()
            logger.debug("local_data_manager.call_log_saved")
        except Exception:
            await conn.rollback()
            logger.exception("local_data_manager.save_call_log_failed")
            raise
        finally:
            await conn.close()

    async def get_call_logs(
        self,
        agent_id: str | None = None,
        limit: int = 100,
    ) -> list[dict]:
        """查询调用日志.

        Args:
            agent_id: 按 agent_id 过滤，None 表示不过滤.
            limit: 返回最大条数，默认 100.

        Returns:
            调用日志字典列表，按时间倒序.
        """
        conn = await self._get_conn()
        try:
            if agent_id:
                cursor = await conn.execute(
                    "SELECT * FROM call_logs WHERE agent_id = ? "
                    "ORDER BY created_at DESC LIMIT ?",
                    (agent_id, limit),
                )
            else:
                cursor = await conn.execute(
                    "SELECT * FROM call_logs ORDER BY created_at DESC LIMIT ?",
                    (limit,),
                )
            rows = await cursor.fetchall()
            return [dict(row) for row in rows]
        finally:
            await conn.close()

    # ------------------------------------------------------------------
    # 便捷方法：通用缓存
    # ------------------------------------------------------------------

    async def set_cache(
        self,
        key: str,
        value: Any,
        ttl_seconds: int = 3600,
    ) -> None:
        """设置缓存项.

        Args:
            key: 缓存键.
            value: 缓存值（支持任意可 JSON 序列化的类型）.
            ttl_seconds: 过期时间（秒），默认 1 小时.
        """
        now = time.time()
        expires_at = now + ttl_seconds
        value_json = json.dumps(value, ensure_ascii=False, default=str)
        conn = await self._get_conn()
        try:
            await conn.execute(
                """
                INSERT INTO cache_items (cache_key, value, expires_at, created_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(cache_key) DO UPDATE SET
                    value = excluded.value,
                    expires_at = excluded.expires_at
                """,
                (key, value_json, expires_at, now),
            )
            await conn.commit()
            logger.debug("local_data_manager.cache_set", key=key)
        except Exception:
            await conn.rollback()
            logger.exception("local_data_manager.set_cache_failed", key=key)
            raise
        finally:
            await conn.close()

    async def get_cache(self, key: str) -> Any | None:
        """获取缓存项.

        Args:
            key: 缓存键.

        Returns:
            缓存值，若不存在或已过期则返回 None.
        """
        now = time.time()
        conn = await self._get_conn()
        try:
            cursor = await conn.execute(
                "SELECT value FROM cache_items WHERE cache_key = ? AND expires_at > ?",
                (key, now),
            )
            row = await cursor.fetchone()
            if row is None:
                return None
            return json.loads(row["value"])
        finally:
            await conn.close()

    # ------------------------------------------------------------------
    # 便捷方法：配置键值
    # ------------------------------------------------------------------

    async def set_config(self, key: str, value: Any) -> None:
        """设置配置项.

        Args:
            key: 配置键.
            value: 配置值（支持任意可 JSON 序列化的类型）.
        """
        now = time.time()
        value_json = json.dumps(value, ensure_ascii=False, default=str)
        conn = await self._get_conn()
        try:
            await conn.execute(
                """
                INSERT INTO config_kv (key, value, updated_at)
                VALUES (?, ?, ?)
                ON CONFLICT(key) DO UPDATE SET
                    value = excluded.value,
                    updated_at = excluded.updated_at
                """,
                (key, value_json, now),
            )
            await conn.commit()
            logger.debug("local_data_manager.config_set", key=key)
        except Exception:
            await conn.rollback()
            logger.exception("local_data_manager.set_config_failed", key=key)
            raise
        finally:
            await conn.close()

    async def get_config(
        self,
        key: str,
        default: Any = None,
    ) -> Any | None:
        """获取配置项.

        Args:
            key: 配置键.
            default: 不存在时的默认值.

        Returns:
            配置值，若不存在则返回 default.
        """
        conn = await self._get_conn()
        try:
            cursor = await conn.execute(
                "SELECT value FROM config_kv WHERE key = ?", (key,)
            )
            row = await cursor.fetchone()
            if row is None:
                return default
            return json.loads(row["value"])
        finally:
            await conn.close()

    @classmethod
    def reset_instance(cls) -> None:
        """重置单例（仅用于测试）."""
        global _init_lock
        cls._instance = None
        _init_lock = None
