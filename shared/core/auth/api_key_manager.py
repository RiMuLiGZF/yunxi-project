"""
API Key 统一管理中心 (SC-010)

提供 API Key 的完整生命周期管理，包括：
- Key 分级（admin/service/read/monitor）
- 创建、吊销、轮换、验证
- 配额管理（分钟/天/月限流）
- SQLite 持久化存储 + 内存缓存
- 默认 Key 初始化
- 使用统计

用法：
    from shared.core.auth.api_key_manager import (
        ApiKeyManager, ApiKeyLevel, get_api_key_manager,
    )

    manager = get_api_key_manager()
    api_key, key_info = manager.create_key(
        name="my-service",
        level=ApiKeyLevel.SERVICE,
        owner="team-a",
    )
    # api_key 只在创建时返回一次明文
    # 后续只能通过 key_prefix 识别

    # 验证
    result = manager.verify_key(api_key, required_level=ApiKeyLevel.SERVICE)
"""

import json
import time
import uuid
import logging
import threading
from enum import Enum
from datetime import datetime, timezone, timedelta
from typing import Optional, Dict, Any, List, Tuple
from dataclasses import dataclass, field

from .api_key import (
    generate_api_key,
    hash_api_key_sha256,
    verify_api_key_hash,
    mask_api_key,
    get_api_key_prefix,
    ApiKeyInfo,
    ApiKeyStore,
    ApiKeyValidator,
)

logger = logging.getLogger(__name__)


# ===========================================================================
# API Key 级别
# ===========================================================================

class ApiKeyLevel(str, Enum):
    """API Key 权限级别

    级别从高到低：
    - ADMIN:    管理级，完整权限，用于模块间管理调用
    - SERVICE:  服务级，正常业务调用权限
    - READ:     只读级，只能读取数据
    - MONITOR:  监控级，健康检查、指标采集
    """
    ADMIN = "admin"
    SERVICE = "service"
    READ = "read"
    MONITOR = "monitor"

    @classmethod
    def has_level(cls, required: "ApiKeyLevel", current: "ApiKeyLevel") -> bool:
        """检查 current 级别是否满足 required 级别要求

        高级别可以访问低级别资源（admin > service > read > monitor）。
        例如：required=SERVICE, current=ADMIN → True（admin 可以访问 service 资源）

        Args:
            required: 要求的最低级别
            current: 当前 Key 的级别

        Returns:
            True 表示满足要求
        """
        hierarchy = [cls.MONITOR, cls.READ, cls.SERVICE, cls.ADMIN]
        try:
            req_idx = hierarchy.index(required)
            cur_idx = hierarchy.index(current)
            return cur_idx >= req_idx
        except ValueError:
            return False

    @classmethod
    def default_scopes(cls, level: "ApiKeyLevel") -> List[str]:
        """获取各级别的默认权限范围"""
        return {
            cls.ADMIN: ["*"],
            cls.SERVICE: ["read", "write", "execute"],
            cls.READ: ["read"],
            cls.MONITOR: ["health", "metrics"],
        }.get(level, ["read"])

    @classmethod
    def default_rate_limit(cls, level: "ApiKeyLevel") -> Dict[str, int]:
        """获取各级别的默认限流配置"""
        return {
            cls.ADMIN: {"per_minute": 600, "per_hour": 10000, "per_day": 100000, "per_month": 2000000},
            cls.SERVICE: {"per_minute": 300, "per_hour": 5000, "per_day": 50000, "per_month": 1000000},
            cls.READ: {"per_minute": 120, "per_hour": 2000, "per_day": 20000, "per_month": 400000},
            cls.MONITOR: {"per_minute": 60, "per_hour": 500, "per_day": 5000, "per_month": 100000},
        }.get(level, {"per_minute": 60, "per_hour": 500, "per_day": 5000, "per_month": 100000})


# ===========================================================================
# 配额与限流管理
# ===========================================================================

@dataclass
class QuotaConfig:
    """配额配置"""
    per_minute: int = 0      # 每分钟请求数限制（0=不限制）
    per_hour: int = 0        # 每小时请求数限制（0=不限制）
    per_day: int = 0         # 每天请求数限制（0=不限制）
    per_month: int = 0       # 每月请求数限制（0=不限制）

    def to_dict(self) -> Dict[str, int]:
        return {
            "per_minute": self.per_minute,
            "per_hour": self.per_hour,
            "per_day": self.per_day,
            "per_month": self.per_month,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "QuotaConfig":
        return cls(
            per_minute=int(data.get("per_minute", 0)),
            per_hour=int(data.get("per_hour", 0)),
            per_day=int(data.get("per_day", 0)),
            per_month=int(data.get("per_month", 0)),
        )


@dataclass
class QuotaUsage:
    """配额使用情况"""
    minute_count: int = 0
    minute_window: float = 0.0   # 当前分钟窗口起始时间戳
    hour_count: int = 0
    hour_window: float = 0.0
    day_count: int = 0
    day_window: float = 0.0
    month_count: int = 0
    month_window: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "minute": {"count": self.minute_count, "window_start": self.minute_window},
            "hour": {"count": self.hour_count, "window_start": self.hour_window},
            "day": {"count": self.day_count, "window_start": self.day_window},
            "month": {"count": self.month_count, "window_start": self.month_window},
        }


class QuotaManager:
    """配额管理器

    基于滑动窗口的多维度限流：
    - 每分钟请求数
    - 每小时请求数
    - 每天请求数
    - 每月请求数

    使用内存计数器，适合单节点部署。
    多节点部署建议接入 Redis 等分布式限流方案。
    """

    def __init__(self):
        self._usage: Dict[str, QuotaUsage] = {}
        self._lock = threading.Lock()

    def _get_windows(self, now: Optional[float] = None) -> Tuple[float, float, float, float]:
        """计算各时间窗口的起始时间戳"""
        if now is None:
            now = time.time()
        dt = datetime.fromtimestamp(now, tz=timezone.utc)

        # 分钟窗口：当前分钟的 0 秒
        minute_start = dt.replace(second=0, microsecond=0).timestamp()
        # 小时窗口：当前小时的 0 分 0 秒
        hour_start = dt.replace(minute=0, second=0, microsecond=0).timestamp()
        # 天窗口：当天 00:00:00
        day_start = dt.replace(hour=0, minute=0, second=0, microsecond=0).timestamp()
        # 月窗口：当月 1 号 00:00:00
        month_start = dt.replace(day=1, hour=0, minute=0, second=0, microsecond=0).timestamp()

        return minute_start, hour_start, day_start, month_start

    def check_and_consume(
        self,
        key_id: str,
        quota: QuotaConfig,
    ) -> Tuple[bool, str, Dict[str, Any]]:
        """检查配额并消耗一次请求

        Args:
            key_id: Key 唯一标识
            quota: 配额配置

        Returns:
            (是否允许, 拒绝原因, 剩余配额详情)
        """
        now = time.time()
        min_win, hour_win, day_win, month_win = self._get_windows(now)

        with self._lock:
            usage = self._usage.get(key_id)
            if usage is None:
                usage = QuotaUsage()
                self._usage[key_id] = usage

            # 重置过期窗口
            if usage.minute_window != min_win:
                usage.minute_count = 0
                usage.minute_window = min_win
            if usage.hour_window != hour_win:
                usage.hour_count = 0
                usage.hour_window = hour_win
            if usage.day_window != day_win:
                usage.day_count = 0
                usage.day_window = day_win
            if usage.month_window != month_win:
                usage.month_count = 0
                usage.month_window = month_win

            # 检查各维度配额
            remaining = {}

            # 分钟
            if quota.per_minute > 0:
                if usage.minute_count >= quota.per_minute:
                    return False, "rate_limit_exceeded_minute", self._remaining_dict(usage, quota)
                remaining["per_minute"] = quota.per_minute - usage.minute_count - 1
            else:
                remaining["per_minute"] = -1  # 无限制

            # 小时
            if quota.per_hour > 0:
                if usage.hour_count >= quota.per_hour:
                    return False, "rate_limit_exceeded_hour", self._remaining_dict(usage, quota)
                remaining["per_hour"] = quota.per_hour - usage.hour_count - 1
            else:
                remaining["per_hour"] = -1

            # 天
            if quota.per_day > 0:
                if usage.day_count >= quota.per_day:
                    return False, "rate_limit_exceeded_day", self._remaining_dict(usage, quota)
                remaining["per_day"] = quota.per_day - usage.day_count - 1
            else:
                remaining["per_day"] = -1

            # 月
            if quota.per_month > 0:
                if usage.month_count >= quota.per_month:
                    return False, "rate_limit_exceeded_month", self._remaining_dict(usage, quota)
                remaining["per_month"] = quota.per_month - usage.month_count - 1
            else:
                remaining["per_month"] = -1

            # 消耗
            usage.minute_count += 1
            usage.hour_count += 1
            usage.day_count += 1
            usage.month_count += 1

            return True, "", remaining

    def _remaining_dict(self, usage: QuotaUsage, quota: QuotaConfig) -> Dict[str, int]:
        return {
            "per_minute": max(0, quota.per_minute - usage.minute_count),
            "per_hour": max(0, quota.per_hour - usage.hour_count),
            "per_day": max(0, quota.per_day - usage.day_count),
            "per_month": max(0, quota.per_month - usage.month_count),
        }

    def get_usage(self, key_id: str) -> Optional[Dict[str, Any]]:
        """获取指定 Key 的配额使用情况"""
        with self._lock:
            usage = self._usage.get(key_id)
            return usage.to_dict() if usage else None

    def reset_key(self, key_id: str) -> None:
        """重置指定 Key 的配额计数"""
        with self._lock:
            self._usage.pop(key_id, None)

    def cleanup_expired(self) -> int:
        """清理过期的配额记录（超过 2 天未访问的）"""
        now = time.time()
        cutoff = now - 2 * 24 * 3600  # 2 天前
        removed = 0
        with self._lock:
            expired_keys = [
                k for k, v in self._usage.items()
                if v.day_window < cutoff
            ]
            for k in expired_keys:
                del self._usage[k]
                removed += 1
        return removed


# ===========================================================================
# SQLite 持久化存储后端
# ===========================================================================

class SqliteApiKeyStore(ApiKeyStore):
    """基于 SQLite 的 API Key 持久化存储

    使用 shared.data.data_layer 的 DatabaseManager 进行数据库操作，
    支持线程安全的读写。

    表结构：
    - api_keys: 主表，存储 Key 基本信息
    - api_key_usage: 使用统计表（可选，用于持久化调用计数）
    """

    _TABLE_NAME = "api_keys"
    _TABLE_CREATED = False
    _table_lock = threading.Lock()

    def __init__(self, db_manager=None, db_name: str = "auth"):
        """
        Args:
            db_manager: DatabaseManager 实例，None 则使用默认单例
            db_name: 数据库名称
        """
        if db_manager is None:
            from shared.data.data_layer import get_db_manager
            db_manager = get_db_manager()
        self._db = db_manager
        self._db_name = db_name
        self._ensure_table()

    def _ensure_table(self) -> None:
        """确保表结构存在（幂等）"""
        with self._table_lock:
            if self._TABLE_CREATED:
                return

            # 检查表是否存在
            row = self._db.query_one(
                self._db_name,
                "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
                (self._TABLE_NAME,),
            )
            if row:
                self._TABLE_CREATED = True
                return

            # 创建表
            self._db.execute(
                self._db_name,
                f"""
                CREATE TABLE IF NOT EXISTS {self._TABLE_NAME} (
                    id TEXT PRIMARY KEY,
                    key_hash TEXT NOT NULL UNIQUE,
                    key_name TEXT NOT NULL,
                    key_prefix TEXT NOT NULL,
                    key_level TEXT NOT NULL DEFAULT 'service',
                    owner TEXT DEFAULT '',
                    scopes TEXT DEFAULT '[]',
                    quota_config TEXT DEFAULT '{{}}',
                    call_count INTEGER DEFAULT 0,
                    last_used_at TEXT,
                    expires_at TEXT,
                    status TEXT NOT NULL DEFAULT 'active',
                    rotation_of TEXT DEFAULT '',
                    created_by TEXT DEFAULT 'system',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    description TEXT DEFAULT '',
                    extra TEXT DEFAULT '{{}}'
                )
                """,
            )

            # 创建索引
            self._db.execute(
                self._db_name,
                f"CREATE INDEX IF NOT EXISTS idx_{self._TABLE_NAME}_owner ON {self._TABLE_NAME}(owner)",
            )
            self._db.execute(
                self._db_name,
                f"CREATE INDEX IF NOT EXISTS idx_{self._TABLE_NAME}_status ON {self._TABLE_NAME}(status)",
            )
            self._db.execute(
                self._db_name,
                f"CREATE INDEX IF NOT EXISTS idx_{self._TABLE_NAME}_level ON {self._TABLE_NAME}(key_level)",
            )
            self._db.execute(
                self._db_name,
                f"CREATE INDEX IF NOT EXISTS idx_{self._TABLE_NAME}_prefix ON {self._TABLE_NAME}(key_prefix)",
            )

            self._TABLE_CREATED = True
            logger.info("API Key 存储表已初始化: %s", self._TABLE_NAME)

    def _row_to_key_info(self, row: Dict[str, Any]) -> "ManagedApiKeyInfo":
        """将数据库行转换为 ManagedApiKeyInfo"""
        try:
            scopes = json.loads(row.get("scopes", "[]"))
        except (json.JSONDecodeError, TypeError):
            scopes = []
        try:
            quota_dict = json.loads(row.get("quota_config", "{}"))
        except (json.JSONDecodeError, TypeError):
            quota_dict = {}
        try:
            extra = json.loads(row.get("extra", "{}"))
        except (json.JSONDecodeError, TypeError):
            extra = {}

        def _parse_dt(val):
            if not val:
                return None
            try:
                return datetime.fromisoformat(val)
            except (ValueError, TypeError):
                return None

        return ManagedApiKeyInfo(
            key_id=row["id"],
            key_hash=row["key_hash"],
            key_name=row["key_name"],
            key_prefix=row["key_prefix"],
            level=ApiKeyLevel(row.get("key_level", "service")),
            owner=row.get("owner", ""),
            scopes=scopes,
            quota=QuotaConfig.from_dict(quota_dict),
            call_count=int(row.get("call_count", 0)),
            last_used_at=_parse_dt(row.get("last_used_at")),
            expires_at=_parse_dt(row.get("expires_at")),
            status=row.get("status", "active"),
            rotation_of=row.get("rotation_of", ""),
            created_by=row.get("created_by", "system"),
            created_at=_parse_dt(row.get("created_at")) or datetime.now(tz=timezone.utc),
            updated_at=_parse_dt(row.get("updated_at")) or datetime.now(tz=timezone.utc),
            description=row.get("description", ""),
            extra=extra,
        )

    def get_all_active(self) -> List[ApiKeyInfo]:
        """获取所有活跃的 Key（基类接口实现）

        包括 active 和 rotated 状态的 Key（rotated 在宽限期内仍可使用）。
        """
        rows = self._db.query_all(
            self._db_name,
            f"SELECT * FROM {self._TABLE_NAME} WHERE status IN ('active', 'rotated')",
        )
        result = []
        for row in rows:
            try:
                managed = self._row_to_key_info(row)
                result.append(managed.to_api_key_info())
            except Exception as e:
                logger.debug("解析 Key 信息失败: %s", e)
        return result

    def find_by_hash(self, key_hash: str) -> Optional[ApiKeyInfo]:
        """根据哈希查找（基类接口实现）"""
        managed = self.find_managed_by_hash(key_hash)
        return managed.to_api_key_info() if managed else None

    def find_managed_by_hash(self, key_hash: str) -> Optional["ManagedApiKeyInfo"]:
        """根据哈希查找完整的 ManagedApiKeyInfo"""
        row = self._db.query_one(
            self._db_name,
            f"SELECT * FROM {self._TABLE_NAME} WHERE key_hash = ?",
            (key_hash,),
        )
        return self._row_to_key_info(row) if row else None

    def find_by_id(self, key_id: str) -> Optional["ManagedApiKeyInfo"]:
        """根据 ID 查找"""
        row = self._db.query_one(
            self._db_name,
            f"SELECT * FROM {self._TABLE_NAME} WHERE id = ?",
            (key_id,),
        )
        return self._row_to_key_info(row) if row else None

    def list_keys(
        self,
        owner: Optional[str] = None,
        level: Optional[ApiKeyLevel] = None,
        status: Optional[str] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> List["ManagedApiKeyInfo"]:
        """列出 Key（支持筛选和分页）"""
        conditions = []
        params: List[Any] = []

        if owner:
            conditions.append("owner = ?")
            params.append(owner)
        if level:
            conditions.append("key_level = ?")
            params.append(level.value)
        if status:
            conditions.append("status = ?")
            params.append(status)

        where = ""
        if conditions:
            where = " WHERE " + " AND ".join(conditions)

        sql = f"SELECT * FROM {self._TABLE_NAME}{where} ORDER BY created_at DESC"
        rows = self._db.query_all(
            self._db_name, sql, tuple(params), limit=limit, offset=offset,
        )
        return [self._row_to_key_info(r) for r in rows]

    def count_keys(
        self,
        owner: Optional[str] = None,
        level: Optional[ApiKeyLevel] = None,
        status: Optional[str] = None,
    ) -> int:
        """统计 Key 数量"""
        conditions = []
        params: List[Any] = []

        if owner:
            conditions.append("owner = ?")
            params.append(owner)
        if level:
            conditions.append("key_level = ?")
            params.append(level.value)
        if status:
            conditions.append("status = ?")
            params.append(status)

        where = ""
        if conditions:
            where = " WHERE " + " AND ".join(conditions)

        row = self._db.query_one(
            self._db_name,
            f"SELECT COUNT(*) as cnt FROM {self._TABLE_NAME}{where}",
            tuple(params),
        )
        return int(row["cnt"]) if row else 0

    def add_managed_key(self, key_info: "ManagedApiKeyInfo") -> None:
        """新增一个 ManagedApiKeyInfo"""
        now = datetime.now(tz=timezone.utc).isoformat()
        self._db.insert(
            self._db_name,
            self._TABLE_NAME,
            {
                "id": key_info.key_id,
                "key_hash": key_info.key_hash,
                "key_name": key_info.key_name,
                "key_prefix": key_info.key_prefix,
                "key_level": key_info.level.value,
                "owner": key_info.owner,
                "scopes": json.dumps(key_info.scopes, ensure_ascii=False),
                "quota_config": json.dumps(key_info.quota.to_dict(), ensure_ascii=False),
                "call_count": key_info.call_count,
                "last_used_at": key_info.last_used_at.isoformat() if key_info.last_used_at else None,
                "expires_at": key_info.expires_at.isoformat() if key_info.expires_at else None,
                "status": key_info.status,
                "rotation_of": key_info.rotation_of,
                "created_by": key_info.created_by,
                "created_at": key_info.created_at.isoformat() if key_info.created_at else now,
                "updated_at": now,
                "description": key_info.description,
                "extra": json.dumps(key_info.extra, ensure_ascii=False),
            },
        )

    def update_key(self, key_id: str, updates: Dict[str, Any]) -> bool:
        """更新 Key 信息

        Args:
            key_id: Key ID
            updates: 要更新的字段字典（支持: key_name, owner, scopes, quota,
                     status, expires_at, description, extra, call_count, last_used_at）

        Returns:
            True 表示更新成功
        """
        if not updates:
            return False

        allowed_fields = {
            "key_name", "owner", "scopes", "quota_config", "status",
            "expires_at", "description", "extra", "call_count", "last_used_at",
            "key_level",
        }

        set_clauses = []
        params: List[Any] = []

        for field, value in updates.items():
            if field not in allowed_fields:
                continue
            if field in ("scopes", "extra"):
                value = json.dumps(value, ensure_ascii=False)
            elif field == "quota_config":
                value = json.dumps(value, ensure_ascii=False)
            elif isinstance(value, datetime):
                value = value.isoformat()
            set_clauses.append(f'"{field}" = ?')
            params.append(value)

        if not set_clauses:
            return False

        set_clauses.append('"updated_at" = ?')
        params.append(datetime.now(tz=timezone.utc).isoformat())
        params.append(key_id)

        sql = f'UPDATE {self._TABLE_NAME} SET {", ".join(set_clauses)} WHERE id = ?'
        affected = self._db.execute(self._db_name, sql, tuple(params))
        return affected > 0

    def increment_usage(self, key_info: ApiKeyInfo) -> None:
        """更新使用统计（基类接口实现）

        通过 key_hash 定位并增加调用计数。
        """
        now = datetime.now(tz=timezone.utc).isoformat()
        self._db.execute(
            self._db_name,
            f"""
            UPDATE {self._TABLE_NAME}
            SET call_count = call_count + 1, last_used_at = ?, updated_at = ?
            WHERE key_hash = ?
            """,
            (now, now, key_info.key_hash),
        )

    def increment_usage_by_id(self, key_id: str) -> None:
        """通过 ID 更新使用统计"""
        now = datetime.now(tz=timezone.utc).isoformat()
        self._db.execute(
            self._db_name,
            f"""
            UPDATE {self._TABLE_NAME}
            SET call_count = call_count + 1, last_used_at = ?, updated_at = ?
            WHERE id = ?
            """,
            (now, now, key_id),
        )

    def delete_expired(self) -> int:
        """清理已过期且超过保留期的 Key

        状态为 revoked 且更新时间超过 30 天的 Key 将被物理删除。
        """
        cutoff = (datetime.now(tz=timezone.utc) - timedelta(days=30)).isoformat()
        affected = self._db.execute(
            self._db_name,
            f"DELETE FROM {self._TABLE_NAME} WHERE status = 'revoked' AND updated_at < ?",
            (cutoff,),
        )
        return affected


# ===========================================================================
# 管理用的 Key 信息扩展类
# ===========================================================================

@dataclass
class ManagedApiKeyInfo:
    """管理用的 API Key 完整信息

    扩展自基础 ApiKeyInfo，增加了 ID、级别、状态、配额等管理字段。
    """
    key_id: str                              # 唯一 ID（UUID）
    key_hash: str                            # 密钥哈希
    key_name: str = ""                       # 名称
    key_prefix: str = ""                     # 前缀（展示用）
    level: ApiKeyLevel = ApiKeyLevel.SERVICE  # 权限级别
    owner: str = ""                          # 所有者
    scopes: List[str] = field(default_factory=list)  # 权限范围
    quota: QuotaConfig = field(default_factory=QuotaConfig)  # 配额配置
    call_count: int = 0                      # 累计调用次数
    last_used_at: Optional[datetime] = None  # 最后使用时间
    expires_at: Optional[datetime] = None    # 过期时间
    status: str = "active"                   # 状态: active/revoked/rotated/expired
    rotation_of: str = ""                    # 轮换自哪个 Key（旧 Key ID）
    created_by: str = "system"               # 创建人
    created_at: datetime = field(
        default_factory=lambda: datetime.now(tz=timezone.utc)
    )
    updated_at: datetime = field(
        default_factory=lambda: datetime.now(tz=timezone.utc)
    )
    description: str = ""                    # 描述
    extra: Dict[str, Any] = field(default_factory=dict)  # 扩展字段

    def to_api_key_info(self) -> ApiKeyInfo:
        """转换为基础 ApiKeyInfo（用于验证器兼容）"""
        return ApiKeyInfo(
            key_hash=self.key_hash,
            key_name=self.key_name,
            key_prefix=self.key_prefix,
            owner=self.owner,
            roles=[self.level.value],
            scopes=self.scopes,
            rate_limit=self.quota.per_minute,
            call_count=self.call_count,
            last_used_at=self.last_used_at,
            expires_at=self.expires_at,
            is_active=self.status == "active",
            created_by=self.created_by,
            created_at=self.created_at,
            description=self.description,
            extra=self.extra,
        )

    def to_dict(self, include_hash: bool = False) -> Dict[str, Any]:
        """转换为字典（用于 API 响应）"""
        result = {
            "key_id": self.key_id,
            "key_name": self.key_name,
            "key_prefix": self.key_prefix,
            "level": self.level.value,
            "owner": self.owner,
            "scopes": self.scopes,
            "quota": self.quota.to_dict(),
            "call_count": self.call_count,
            "last_used_at": self.last_used_at.isoformat() if self.last_used_at else None,
            "expires_at": self.expires_at.isoformat() if self.expires_at else None,
            "status": self.status,
            "rotation_of": self.rotation_of,
            "created_by": self.created_by,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
            "description": self.description,
            "extra": self.extra,
        }
        if include_hash:
            result["key_hash"] = self.key_hash
        return result

    def is_active_and_valid(self) -> bool:
        """检查是否为活跃且未过期

        以下状态视为有效（只要未过期）：
        - active: 正常活跃
        - rotated: 已轮换但仍在宽限期内
        """
        if self.status not in ("active", "rotated"):
            return False
        if self.expires_at and self.expires_at < datetime.now(tz=timezone.utc):
            return False
        return True


# ===========================================================================
# 内存缓存层
# ===========================================================================

class ApiKeyCache:
    """活跃 Key 内存缓存

    缓存最近使用的 Key 信息，减少数据库查询。
    使用简单的 LRU 策略（基于字典有序性）。
    """

    def __init__(self, max_size: int = 500, ttl_seconds: int = 300):
        """
        Args:
            max_size: 最大缓存条目数
            ttl_seconds: 缓存有效期（秒）
        """
        self.max_size = max_size
        self.ttl = ttl_seconds
        self._cache: Dict[str, Tuple[ManagedApiKeyInfo, float]] = {}
        self._lock = threading.Lock()

    def get(self, key_hash: str) -> Optional[ManagedApiKeyInfo]:
        """从缓存获取"""
        with self._lock:
            entry = self._cache.get(key_hash)
            if not entry:
                return None
            info, timestamp = entry
            # 检查是否过期
            if time.time() - timestamp > self.ttl:
                del self._cache[key_hash]
                return None
            # 移动到末尾（模拟 LRU）
            del self._cache[key_hash]
            self._cache[key_hash] = (info, time.time())
            return info

    def put(self, key_hash: str, info: ManagedApiKeyInfo) -> None:
        """写入缓存"""
        with self._lock:
            # 如果已存在，先删除旧条目
            if key_hash in self._cache:
                del self._cache[key_hash]
            # 超出容量，淘汰最旧的
            while len(self._cache) >= self.max_size:
                oldest_key = next(iter(self._cache))
                del self._cache[oldest_key]
            self._cache[key_hash] = (info, time.time())

    def invalidate(self, key_hash: str) -> None:
        """使缓存失效"""
        with self._lock:
            self._cache.pop(key_hash, None)

    def invalidate_by_prefix(self, key_prefix: str) -> int:
        """按前缀批量失效（用于轮换/吊销时清理）"""
        count = 0
        with self._lock:
            to_remove = [
                k for k, (v, _) in self._cache.items()
                if v.key_prefix == key_prefix
            ]
            for k in to_remove:
                del self._cache[k]
                count += 1
        return count

    def clear(self) -> None:
        """清空缓存"""
        with self._lock:
            self._cache.clear()

    def size(self) -> int:
        """当前缓存条目数"""
        with self._lock:
            return len(self._cache)


# ===========================================================================
# API Key 管理中心主类
# ===========================================================================

class ApiKeyManager:
    """API Key 统一管理中心

    提供完整的 API Key 生命周期管理能力：
    - 创建、吊销、轮换
    - 分级验证
    - 配额限流
    - 持久化存储 + 内存缓存
    - 统计信息

    Args:
        store: 存储后端，默认使用 SqliteApiKeyStore
        cache: 缓存层，默认使用 ApiKeyCache
        quota_manager: 配额管理器，默认使用 QuotaManager
        use_bcrypt: 是否使用 bcrypt 哈希，默认 False（用 SHA256 提升性能）
    """

    def __init__(
        self,
        store: Optional[SqliteApiKeyStore] = None,
        cache: Optional[ApiKeyCache] = None,
        quota_manager: Optional[QuotaManager] = None,
        use_bcrypt: bool = False,
    ):
        if store is None:
            store = SqliteApiKeyStore()
        if cache is None:
            cache = ApiKeyCache()
        if quota_manager is None:
            quota_manager = QuotaManager()

        self._store = store
        self._cache = cache
        self._quota = quota_manager
        self._use_bcrypt = use_bcrypt
        self._validator = ApiKeyValidator(store, use_bcrypt=use_bcrypt)
        self._lock = threading.Lock()

        # 默认 Key 初始化标记
        self._default_key_initialized = False

    # -----------------------------------------------------------------------
    # Key 创建
    # -----------------------------------------------------------------------

    def create_key(
        self,
        name: str,
        level: ApiKeyLevel = ApiKeyLevel.SERVICE,
        owner: str = "",
        expires_at: Optional[datetime] = None,
        scopes: Optional[List[str]] = None,
        rate_limit: Optional[Dict[str, int]] = None,
        description: str = "",
        created_by: str = "system",
        extra: Optional[Dict[str, Any]] = None,
        prefix: str = "yx-",
    ) -> Tuple[str, ManagedApiKeyInfo]:
        """创建新的 API Key

        Args:
            name: Key 名称
            level: 权限级别
            owner: 所有者
            expires_at: 过期时间（None=永不过期）
            scopes: 自定义权限范围（None=使用级别默认值）
            rate_limit: 自定义限流配置（None=使用级别默认值）
            description: 描述
            created_by: 创建人
            extra: 扩展字段
            prefix: Key 前缀

        Returns:
            (明文 API Key, ManagedApiKeyInfo)
            注意：明文 Key 只在创建时返回一次，之后无法再获取
        """
        # 兼容字符串级别输入
        if isinstance(level, str):
            level = ApiKeyLevel(level)

        # 生成明文 Key
        api_key = generate_api_key(prefix=prefix, length=32)

        # 计算哈希
        if self._use_bcrypt:
            from .api_key import hash_api_key
            key_hash = hash_api_key(api_key, use_bcrypt=True)
        else:
            key_hash = hash_api_key_sha256(api_key)

        # 确定权限范围
        if scopes is None:
            scopes = ApiKeyLevel.default_scopes(level)

        # 确定配额
        if rate_limit is not None:
            quota = QuotaConfig.from_dict(rate_limit)
        else:
            default_rl = ApiKeyLevel.default_rate_limit(level)
            quota = QuotaConfig.from_dict(default_rl)

        key_id = str(uuid.uuid4())
        key_prefix = get_api_key_prefix(api_key, prefix_len=8)
        now = datetime.now(tz=timezone.utc)

        key_info = ManagedApiKeyInfo(
            key_id=key_id,
            key_hash=key_hash,
            key_name=name,
            key_prefix=key_prefix,
            level=level,
            owner=owner,
            scopes=scopes,
            quota=quota,
            expires_at=expires_at,
            status="active",
            created_by=created_by,
            created_at=now,
            updated_at=now,
            description=description,
            extra=extra or {},
        )

        self._store.add_managed_key(key_info)
        logger.info(
            "API Key 创建成功: id=%s name=%s level=%s owner=%s prefix=%s",
            key_id, name, level.value, owner, key_prefix,
        )

        return api_key, key_info

    # -----------------------------------------------------------------------
    # Key 吊销
    # -----------------------------------------------------------------------

    def revoke_key(self, key_id: str, reason: str = "") -> bool:
        """吊销 Key

        Args:
            key_id: Key ID
            reason: 吊销原因（记录在 extra 中）

        Returns:
            True 表示成功吊销
        """
        key_info = self._store.find_by_id(key_id)
        if not key_info:
            return False

        extra = dict(key_info.extra)
        if reason:
            extra["revoke_reason"] = reason
        extra["revoked_at"] = datetime.now(tz=timezone.utc).isoformat()

        success = self._store.update_key(key_id, {
            "status": "revoked",
            "extra": extra,
        })

        if success:
            self._cache.invalidate(key_info.key_hash)
            self._quota.reset_key(key_id)
            logger.info("API Key 已吊销: id=%s name=%s reason=%s", key_id, key_info.key_name, reason)

        return success

    # -----------------------------------------------------------------------
    # Key 轮换
    # -----------------------------------------------------------------------

    def rotate_key(
        self,
        key_id: str,
        grace_days: int = 7,
    ) -> Tuple[str, ManagedApiKeyInfo]:
        """轮换 Key

        创建一个新 Key（与旧 Key 同级同配置），旧 Key 保留 grace_days 天后自动失效。

        Args:
            key_id: 要轮换的 Key ID
            grace_days: 旧 Key 宽限天数（默认 7 天）

        Returns:
            (新明文 API Key, 新 Key 信息)

        Raises:
            ValueError: Key 不存在或已被吊销
        """
        old_key = self._store.find_by_id(key_id)
        if not old_key:
            raise ValueError(f"Key 不存在: {key_id}")
        if old_key.status != "active":
            raise ValueError(f"Key 状态不是 active，无法轮换: {old_key.status}")

        # 创建新 Key（复制旧 Key 的配置）
        new_api_key, new_key_info = self.create_key(
            name=old_key.key_name,
            level=old_key.level,
            owner=old_key.owner,
            expires_at=old_key.expires_at,
            scopes=list(old_key.scopes),
            rate_limit=old_key.quota.to_dict(),
            description=f"{old_key.description} (rotated from {old_key.key_prefix})",
            created_by="rotation",
            extra={**old_key.extra, "rotated_from": key_id},
            prefix=old_key.key_prefix.split("-")[0] + "-" if "-" in old_key.key_prefix else "yx-",
        )
        # 设置 rotation_of
        new_key_info.rotation_of = key_id
        self._store.update_key(new_key_info.key_id, {
            "rotation_of": key_id,
        })

        # 设置旧 Key 的过期时间（宽限期后失效）
        grace_expiry = datetime.now(tz=timezone.utc) + timedelta(days=grace_days)
        # 如果旧 Key 原本的过期时间更早，保留原时间
        if old_key.expires_at and old_key.expires_at < grace_expiry:
            grace_expiry = old_key.expires_at

        old_extra = dict(old_key.extra)
        old_extra["rotated_to"] = new_key_info.key_id
        old_extra["rotation_grace_days"] = grace_days

        self._store.update_key(key_id, {
            "status": "rotated",
            "expires_at": grace_expiry,
            "extra": old_extra,
        })
        self._cache.invalidate(old_key.key_hash)

        logger.info(
            "API Key 轮换完成: old_id=%s new_id=%s grace_days=%d",
            key_id, new_key_info.key_id, grace_days,
        )

        return new_api_key, new_key_info

    # -----------------------------------------------------------------------
    # Key 验证
    # -----------------------------------------------------------------------

    def verify_key(
        self,
        api_key: str,
        required_level: Optional[ApiKeyLevel] = None,
        required_scopes: Optional[List[str]] = None,
    ) -> Optional[ManagedApiKeyInfo]:
        """验证 API Key

        验证步骤：
        1. 从缓存/存储中查找并验证哈希
        2. 检查状态和过期时间
        3. 检查权限级别
        4. 检查权限范围
        5. 检查配额
        6. 更新使用统计

        Args:
            api_key: 明文 API Key
            required_level: 要求的最低权限级别
            required_scopes: 要求的权限范围（需全部满足）

        Returns:
            验证通过返回 ManagedApiKeyInfo，失败返回 None
        """
        if not api_key:
            return None

        # 计算哈希
        key_hash = hash_api_key_sha256(api_key)

        # 先查缓存
        key_info = self._cache.get(key_hash)

        if not key_info:
            # 从存储查找
            if self._use_bcrypt:
                # bcrypt 必须遍历验证
                base_info = self._validator.validate(api_key)
                if not base_info:
                    return None
                key_info = self._store.find_managed_by_hash(base_info.key_hash)
            else:
                key_info = self._store.find_managed_by_hash(key_hash)
                # SHA256 快速验证
                if not key_info or not key_info.is_active_and_valid():
                    return None

            if key_info:
                self._cache.put(key_hash, key_info)

        # 状态检查
        if not key_info.is_active_and_valid():
            self._cache.invalidate(key_hash)
            return None

        # 级别检查
        if required_level and not ApiKeyLevel.has_level(required_level, key_info.level):
            logger.debug(
                "Key 级别不足: key_id=%s level=%s required=%s",
                key_info.key_id, key_info.level.value, required_level.value,
            )
            return None

        # 范围检查
        if required_scopes:
            if "*" not in key_info.scopes:
                missing = [s for s in required_scopes if s not in key_info.scopes]
                if missing:
                    logger.debug(
                        "Key 缺少权限范围: key_id=%s missing=%s",
                        key_info.key_id, missing,
                    )
                    return None

        # 配额检查
        allowed, reason, _ = self._quota.check_and_consume(key_info.key_id, key_info.quota)
        if not allowed:
            logger.warning(
                "Key 配额超限: key_id=%s reason=%s",
                key_info.key_id, reason,
            )
            return None

        # 更新使用统计（异步或延迟，这里直接更新）
        try:
            self._store.increment_usage_by_id(key_info.key_id)
            # 更新内存中的计数
            key_info.call_count += 1
            key_info.last_used_at = datetime.now(tz=timezone.utc)
        except Exception as e:
            logger.debug("使用统计更新失败: %s", e)

        return key_info

    def check_quota(self, api_key: str) -> Optional[Dict[str, Any]]:
        """检查配额使用情况（不消耗配额）

        Args:
            api_key: 明文 API Key

        Returns:
            配额使用详情，失败返回 None
        """
        if not api_key:
            return None

        key_hash = hash_api_key_sha256(api_key)
        key_info = self._cache.get(key_hash)
        if not key_info:
            key_info = self._store.find_managed_by_hash(key_hash)
            if key_info:
                self._cache.put(key_hash, key_info)

        if not key_info or not key_info.is_active_and_valid():
            return None

        usage = self._quota.get_usage(key_info.key_id) or {}
        return {
            "key_id": key_info.key_id,
            "key_prefix": key_info.key_prefix,
            "quota": key_info.quota.to_dict(),
            "usage": usage,
        }

    # -----------------------------------------------------------------------
    # Key 列表与查询
    # -----------------------------------------------------------------------

    def list_keys(
        self,
        owner: Optional[str] = None,
        level: Optional[ApiKeyLevel] = None,
        status: Optional[str] = None,
        page: int = 1,
        page_size: int = 50,
    ) -> Tuple[List[ManagedApiKeyInfo], int]:
        """列出 Key

        Args:
            owner: 按所有者筛选
            level: 按级别筛选
            status: 按状态筛选
            page: 页码（从 1 开始）
            page_size: 每页数量

        Returns:
            (Key 列表, 总数)
        """
        offset = max(0, (page - 1) * page_size)
        keys = self._store.list_keys(
            owner=owner, level=level, status=status,
            limit=page_size, offset=offset,
        )
        total = self._store.count_keys(owner=owner, level=level, status=status)
        return keys, total

    def get_key(self, key_id: str) -> Optional[ManagedApiKeyInfo]:
        """获取单个 Key 详情"""
        return self._store.find_by_id(key_id)

    # -----------------------------------------------------------------------
    # Key 更新
    # -----------------------------------------------------------------------

    def update_key(
        self,
        key_id: str,
        name: Optional[str] = None,
        owner: Optional[str] = None,
        scopes: Optional[List[str]] = None,
        level: Optional[ApiKeyLevel] = None,
        expires_at: Optional[datetime] = None,
        description: Optional[str] = None,
        extra: Optional[Dict[str, Any]] = None,
        rate_limit: Optional[Dict[str, int]] = None,
    ) -> Optional[ManagedApiKeyInfo]:
        """更新 Key 配置

        Args:
            key_id: Key ID
            name: 新名称
            owner: 新所有者
            scopes: 新权限范围
            level: 新级别
            expires_at: 新过期时间
            description: 新描述
            extra: 新扩展字段
            rate_limit: 新限流配置

        Returns:
            更新后的 Key 信息，找不到返回 None
        """
        key_info = self._store.find_by_id(key_id)
        if not key_info:
            return None

        updates: Dict[str, Any] = {}
        if name is not None:
            updates["key_name"] = name
        if owner is not None:
            updates["owner"] = owner
        if scopes is not None:
            updates["scopes"] = scopes
        if level is not None:
            updates["key_level"] = level.value
        if expires_at is not None:
            updates["expires_at"] = expires_at
        if description is not None:
            updates["description"] = description
        if extra is not None:
            updates["extra"] = extra
        if rate_limit is not None:
            updates["quota_config"] = rate_limit

        if not updates:
            return key_info

        success = self._store.update_key(key_id, updates)
        if success:
            self._cache.invalidate(key_info.key_hash)
            updated = self._store.find_by_id(key_id)
            if updated:
                logger.info("API Key 已更新: id=%s fields=%s", key_id, list(updates.keys()))
            return updated

        return key_info

    # -----------------------------------------------------------------------
    # 导入 Key
    # -----------------------------------------------------------------------

    def import_key(self, key_info_dict: Dict[str, Any]) -> ManagedApiKeyInfo:
        """导入已有 Key

        用于从其他系统迁移或恢复备份。

        Args:
            key_info_dict: Key 信息字典，必须包含 key_hash 和 key_name

        Returns:
            导入后的 ManagedApiKeyInfo

        Raises:
            ValueError: 缺少必要字段或哈希已存在
        """
        if not key_info_dict.get("key_hash"):
            raise ValueError("导入 Key 必须包含 key_hash")
        if not key_info_dict.get("key_name"):
            raise ValueError("导入 Key 必须包含 key_name")

        # 检查哈希是否已存在
        existing = self._store.find_managed_by_hash(key_info_dict["key_hash"])
        if existing:
            raise ValueError(f"Key 哈希已存在: {existing.key_id}")

        key_id = key_info_dict.get("key_id", str(uuid.uuid4()))
        level = ApiKeyLevel(key_info_dict.get("level", "service"))
        scopes = key_info_dict.get("scopes", ApiKeyLevel.default_scopes(level))

        quota_dict = key_info_dict.get("quota") or ApiKeyLevel.default_rate_limit(level)
        quota = QuotaConfig.from_dict(quota_dict)

        def _parse_dt(val):
            if not val:
                return None
            if isinstance(val, datetime):
                return val
            try:
                return datetime.fromisoformat(str(val))
            except (ValueError, TypeError):
                return None

        now = datetime.now(tz=timezone.utc)
        managed = ManagedApiKeyInfo(
            key_id=key_id,
            key_hash=key_info_dict["key_hash"],
            key_name=key_info_dict["key_name"],
            key_prefix=key_info_dict.get("key_prefix", key_info_dict["key_hash"][:8]),
            level=level,
            owner=key_info_dict.get("owner", ""),
            scopes=scopes,
            quota=quota,
            call_count=int(key_info_dict.get("call_count", 0)),
            last_used_at=_parse_dt(key_info_dict.get("last_used_at")),
            expires_at=_parse_dt(key_info_dict.get("expires_at")),
            status=key_info_dict.get("status", "active"),
            rotation_of=key_info_dict.get("rotation_of", ""),
            created_by=key_info_dict.get("created_by", "import"),
            created_at=_parse_dt(key_info_dict.get("created_at")) or now,
            updated_at=_parse_dt(key_info_dict.get("updated_at")) or now,
            description=key_info_dict.get("description", ""),
            extra=key_info_dict.get("extra", {}),
        )

        self._store.add_managed_key(managed)
        logger.info("API Key 导入成功: id=%s name=%s", key_id, managed.key_name)
        return managed

    # -----------------------------------------------------------------------
    # 统计信息
    # -----------------------------------------------------------------------

    def get_key_stats(self) -> Dict[str, Any]:
        """获取 Key 统计信息"""
        total = self._store.count_keys()
        active = self._store.count_keys(status="active")
        revoked = self._store.count_keys(status="revoked")
        rotated = self._store.count_keys(status="rotated")

        stats_by_level = {}
        for level in ApiKeyLevel:
            stats_by_level[level.value] = self._store.count_keys(level=level)

        return {
            "total": total,
            "active": active,
            "revoked": revoked,
            "rotated": rotated,
            "by_level": stats_by_level,
            "cache_size": self._cache.size(),
        }

    def get_usage_stats(
        self,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None,
    ) -> Dict[str, Any]:
        """获取使用量统计

        基于数据库中的 call_count 进行统计。
        """
        keys, _ = self.list_keys(page_size=1000)
        total_calls = sum(k.call_count for k in keys)
        active_keys = [k for k in keys if k.status == "active"]
        active_calls = sum(k.call_count for k in active_keys)

        # Top 10 调用最多的 Key
        top_keys = sorted(keys, key=lambda k: k.call_count, reverse=True)[:10]
        top_list = [
            {
                "key_id": k.key_id,
                "key_name": k.key_name,
                "key_prefix": k.key_prefix,
                "level": k.level.value,
                "call_count": k.call_count,
                "last_used_at": k.last_used_at.isoformat() if k.last_used_at else None,
            }
            for k in top_keys
        ]

        return {
            "total_keys": len(keys),
            "active_keys": len(active_keys),
            "total_calls": total_calls,
            "active_calls": active_calls,
            "top_keys": top_list,
            "period": {
                "start": start_date.isoformat() if start_date else None,
                "end": end_date.isoformat() if end_date else None,
            },
        }

    # -----------------------------------------------------------------------
    # 默认 Key 初始化
    # -----------------------------------------------------------------------

    def ensure_default_key(
        self,
        name: str = "default-admin-key",
        owner: str = "system",
        force_reset: bool = False,
    ) -> Optional[str]:
        """确保存在默认管理级 Key

        首次启动时自动生成默认的管理级 Key，用于内部服务间调用。
        Key 仅在首次生成时返回明文，之后无法再获取。

        Args:
            name: 默认 Key 名称
            owner: 所有者
            force_reset: 是否强制重置（删除旧的默认 Key 并生成新的）

        Returns:
            如果是新生成的 Key，返回明文；否则返回 None
        """
        with self._lock:
            # 检查是否已存在同名的 active Key
            existing = self._store.list_keys(owner=owner, status="active", limit=10)
            existing_default = [k for k in existing if k.key_name == name and k.level == ApiKeyLevel.ADMIN]

            if existing_default and not force_reset:
                self._default_key_initialized = True
                return None

            # 如果强制重置，先吊销所有同名 Key
            if force_reset:
                for k in existing_default:
                    self.revoke_key(k.key_id, reason="force_reset")

            # 创建新的默认 Key
            api_key, key_info = self.create_key(
                name=name,
                level=ApiKeyLevel.ADMIN,
                owner=owner,
                description="系统默认管理级 Key（用于内部服务间调用）",
                created_by="bootstrap",
                extra={"is_default": True},
            )

            self._default_key_initialized = True
            logger.info(
                "=" * 60 + "\n"
                "  默认 API Key 已生成（请妥善保存，仅显示一次）\n"
                "  Key Name: %s\n"
                "  Key ID:   %s\n"
                "  Level:    %s\n"
                "  API Key:  %s\n"
                "  提示：创建后无法再查看明文，请立即保存！\n"
                + "=" * 60,
                key_info.key_name, key_info.key_id, key_info.level.value, api_key,
            )

            return api_key

    # -----------------------------------------------------------------------
    # 清理维护
    # -----------------------------------------------------------------------

    def cleanup(self) -> Dict[str, int]:
        """执行清理维护

        - 清理过期的配额记录
        - 清理已吊销超过 30 天的 Key
        - 检查并标记已过期的 Key

        Returns:
            清理统计
        """
        quota_cleaned = self._quota.cleanup_expired()
        revoked_cleaned = self._store.delete_expired()

        # 标记已过期的 Key（仅 active 和 rotated 状态但已过期的）
        now = datetime.now(tz=timezone.utc).isoformat()
        expired_marked = self._store._db.execute(
            self._store._db_name,
            f"""
            UPDATE {self._store._TABLE_NAME}
            SET status = 'expired', updated_at = ?
            WHERE status IN ('active', 'rotated') AND expires_at IS NOT NULL AND expires_at < ?
            """,
            (now, now),
        )

        if expired_marked > 0:
            self._cache.clear()
            logger.info("已标记 %d 个过期 Key", expired_marked)

        return {
            "quota_cleaned": quota_cleaned,
            "revoked_cleaned": revoked_cleaned,
            "expired_marked": expired_marked,
        }

    @property
    def store(self) -> SqliteApiKeyStore:
        """获取存储后端"""
        return self._store

    @property
    def validator(self) -> ApiKeyValidator:
        """获取验证器（用于中间件/依赖兼容）"""
        return self._validator


# ===========================================================================
# 单例获取
# ===========================================================================

_manager_instance: Optional[ApiKeyManager] = None
_manager_lock = threading.Lock()


def get_api_key_manager(
    db_manager=None,
    db_name: str = "auth",
    use_bcrypt: bool = False,
) -> ApiKeyManager:
    """获取 API Key 管理器单例

    Args:
        db_manager: 数据库管理器（可选）
        db_name: 数据库名称
        use_bcrypt: 是否使用 bcrypt

    Returns:
        ApiKeyManager 单例
    """
    global _manager_instance
    if _manager_instance is None:
        with _manager_lock:
            if _manager_instance is None:
                store = SqliteApiKeyStore(db_manager=db_manager, db_name=db_name)
                cache = ApiKeyCache()
                quota_manager = QuotaManager()
                _manager_instance = ApiKeyManager(
                    store=store,
                    cache=cache,
                    quota_manager=quota_manager,
                    use_bcrypt=use_bcrypt,
                )
    return _manager_instance


def reset_api_key_manager() -> None:
    """重置单例（测试用）"""
    global _manager_instance
    with _manager_lock:
        _manager_instance = None
