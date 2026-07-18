"""技能市场 - 高级服务层.

在 MarketRegistry 基础上提供更丰富的市场功能：
- 增强的浏览与搜索（多标签过滤、价格类型、官方/认证筛选）
- 用户维度的安装管理
- 评论系统（分页、点赞）
- 技能上架更新管理
- 分类体系管理

与现有系统的关系：
- 复用 MarketRegistry 的 SQLite 存储和 SkillPackageStore 文件存储
- 新增表：reviews（带点赞）、installed_skills（用户维度安装记录）、categories（分类元数据）
- 所有新增功能为纯增量，不修改现有表结构和接口行为
"""

from __future__ import annotations

import json
import os
import re
import sqlite3
import threading
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

import structlog
from pydantic import BaseModel, Field

from skill_cluster.market.models import (
    MarketListing,
    MarketStats,
    PublishRequest,
    SkillPackage,
)
from skill_cluster.market.registry import MarketRegistry

logger = structlog.get_logger()


# ===========================================================================
# 数据模型
# ===========================================================================


class SkillListing(BaseModel):
    """技能上架信息（增强版）."""

    id: str
    skill_id: str
    name: str
    version: str
    author: str
    description: str
    category: str = "general"
    tags: List[str] = []
    icon_url: str = ""
    price_type: str = "free"  # free / paid / donation
    price_amount: float = 0.0
    rating: float = 0.0
    rating_count: int = 0
    install_count: int = 0
    download_count: int = 0
    is_official: bool = False
    is_verified: bool = False
    created_at: datetime = Field(default_factory=lambda: datetime.now(tz=timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(tz=timezone.utc))


class SkillReview(BaseModel):
    """技能评论."""

    id: int
    skill_id: str
    user_id: str
    user_name: str = ""
    rating: int
    comment: str = ""
    likes: int = 0
    created_at: datetime = Field(default_factory=lambda: datetime.now(tz=timezone.utc))


class SkillRatingStats(BaseModel):
    """技能评分统计."""

    skill_id: str
    avg_rating: float = 0.0
    total_count: int = 0
    distribution: Dict[int, int] = Field(default_factory=dict)  # 1-5 星分布


class InstalledSkill(BaseModel):
    """已安装技能记录."""

    user_id: str
    skill_id: str
    package_id: str
    installed_at: datetime
    version: str
    is_active: bool = True


class CategoryInfo(BaseModel):
    """分类信息."""

    category_id: str
    name: str
    description: str = ""
    icon: str = ""
    skill_count: int = 0
    parent_id: Optional[str] = None


class SearchFilters(BaseModel):
    """搜索过滤条件."""

    category: Optional[str] = None
    tags: List[str] = []
    price_type: Optional[str] = None  # free / paid / donation
    is_official: Optional[bool] = None
    is_verified: Optional[bool] = None
    min_rating: Optional[float] = None
    author: Optional[str] = None


# ===========================================================================
# SQL 安全校验（复用 registry 模式）
# ===========================================================================

_SAFE_IDENTIFIER_RE = re.compile(r'^[a-zA-Z_][a-zA-Z0-9_]*$')

_SORT_OPTIONS: Dict[str, str] = {
    "newest": "sp.created_at DESC",
    "popular": "sp.download_count DESC, sp.created_at DESC",
    "downloads": "sp.download_count DESC, sp.created_at DESC",
    "rating": "sp.rating_avg DESC, sp.rating_count DESC",
    "oldest": "sp.created_at ASC",
    "name": "sp.name ASC",
    "updated": "sp.updated_at DESC",
    "installs": "install_count DESC, sp.created_at DESC",
}

_PRICE_TYPES = {"free", "paid", "donation"}


def _validate_sort(sort: str) -> str:
    if sort not in _SORT_OPTIONS:
        raise ValueError(f"Invalid sort option: {sort}")
    return _SORT_OPTIONS[sort]


def _safe_json_loads(value: str, default: Any) -> Any:
    if not value:
        return default
    try:
        return json.loads(value)
    except (json.JSONDecodeError, TypeError):
        return default


def _safe_parse_dt(value: str) -> datetime:
    if not value:
        return datetime.now(tz=timezone.utc)
    try:
        return datetime.fromisoformat(value)
    except (ValueError, TypeError):
        return datetime.now(tz=timezone.utc)


# ===========================================================================
# SkillMarket 高级服务
# ===========================================================================


class SkillMarket:
    """技能市场高级服务.

    在 MarketRegistry 基础上提供增强功能：
    - 多维度搜索过滤
    - 用户维度安装管理
    - 评论点赞系统
    - 分类元数据管理
    - 技能上架更新

    单例模式，通过 get_instance() 获取。
    """

    _instance: Optional["SkillMarket"] = None
    _lock = threading.Lock()

    def __init__(self, db_path: Optional[str] = None) -> None:
        if db_path is None:
            db_path = os.path.join(
                os.path.expanduser("~"), ".yunxi", "market", "market.db"
            )
        self.db_path = db_path
        self._registry = MarketRegistry(db_path=db_path)
        self._init_tables()

    # ------------------------------------------------------------------
    # 单例
    # ------------------------------------------------------------------

    @classmethod
    def get_instance(cls) -> "SkillMarket":
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = cls()
        return cls._instance

    # ------------------------------------------------------------------
    # 数据库初始化（新增表，不修改现有表）
    # ------------------------------------------------------------------

    def _init_tables(self) -> None:
        """初始化新增的表结构.

        新增表：
        - skill_reviews: 评论表（带点赞、用户名）
        - installed_skills: 用户维度安装记录
        - categories: 分类元数据表
        - skill_extra: 技能扩展信息（价格、官方、认证、图标等）
        """
        with self._get_conn() as conn:
            conn.executescript(
                """
                -- 评论表（增强版，支持点赞和用户名）
                CREATE TABLE IF NOT EXISTS skill_reviews (
                    id          INTEGER PRIMARY KEY AUTOINCREMENT,
                    package_id  TEXT NOT NULL,
                    user_id     TEXT NOT NULL,
                    user_name   TEXT DEFAULT '',
                    rating      INTEGER NOT NULL,
                    comment     TEXT DEFAULT '',
                    likes       INTEGER DEFAULT 0,
                    created_at  TEXT,
                    UNIQUE(package_id, user_id)
                );
                CREATE INDEX IF NOT EXISTS idx_reviews_package
                    ON skill_reviews(package_id);
                CREATE INDEX IF NOT EXISTS idx_reviews_created
                    ON skill_reviews(created_at);

                -- 用户安装记录表
                CREATE TABLE IF NOT EXISTS installed_skills (
                    id            INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id       TEXT NOT NULL,
                    package_id    TEXT NOT NULL,
                    skill_id      TEXT NOT NULL,
                    version       TEXT,
                    installed_at  TEXT,
                    is_active     INTEGER DEFAULT 1,
                    UNIQUE(user_id, package_id)
                );
                CREATE INDEX IF NOT EXISTS idx_installed_user
                    ON installed_skills(user_id);
                CREATE INDEX IF NOT EXISTS idx_installed_package
                    ON installed_skills(package_id);

                -- 分类元数据表
                CREATE TABLE IF NOT EXISTS categories (
                    category_id  TEXT PRIMARY KEY,
                    name         TEXT NOT NULL,
                    description  TEXT DEFAULT '',
                    icon         TEXT DEFAULT '',
                    parent_id    TEXT,
                    sort_order   INTEGER DEFAULT 0
                );

                -- 技能扩展信息表（价格、官方、认证、图标等）
                CREATE TABLE IF NOT EXISTS skill_extra (
                    package_id    TEXT PRIMARY KEY,
                    price_type    TEXT DEFAULT 'free',
                    price_amount  REAL DEFAULT 0.0,
                    icon_url      TEXT DEFAULT '',
                    is_official   INTEGER DEFAULT 0,
                    is_verified   INTEGER DEFAULT 0,
                    install_count INTEGER DEFAULT 0,
                    updated_at    TEXT
                );
                """
            )
        # 初始化默认分类
        self._init_default_categories()

    def _init_default_categories(self) -> None:
        """初始化默认分类（如果不存在）."""
        defaults = [
            ("general", "综合", "通用技能分类", "", None, 0),
            ("productivity", "效率工具", "提升工作效率的技能", "", None, 1),
            ("creative", "创意创作", "写作、设计、绘画等创意类技能", "", None, 2),
            ("development", "开发工具", "编程、调试、代码分析等开发技能", "", None, 3),
            ("data", "数据分析", "数据处理、分析、可视化技能", "", None, 4),
            ("communication", "沟通翻译", "翻译、写作润色、沟通辅助技能", "", None, 5),
            ("learning", "学习教育", "学习辅助、知识管理技能", "", None, 6),
            ("lifestyle", "生活服务", "日常生活、健康管理技能", "", None, 7),
            ("entertainment", "娱乐休闲", "游戏、娱乐类技能", "", None, 8),
            ("business", "商业金融", "金融、商业分析技能", "", None, 9),
        ]
        with self._get_conn() as conn:
            for cat_id, name, desc, icon, parent, sort_order in defaults:
                conn.execute(
                    """
                    INSERT OR IGNORE INTO categories
                        (category_id, name, description, icon, parent_id, sort_order)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (cat_id, name, desc, icon, parent, sort_order),
                )

    def _get_conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    # ------------------------------------------------------------------
    # 行转换
    # ------------------------------------------------------------------

    @staticmethod
    def _row_to_listing(row: sqlite3.Row) -> MarketListing:
        return MarketListing(
            package_id=row["package_id"],
            name=row["name"],
            description=row["description"] or "",
            author=row["author"] or "",
            version=row["version"],
            tags=_safe_json_loads(row["tags"], []),
            category=row["category"] or "general",
            download_count=row["download_count"] or 0,
            rating_avg=row["rating_avg"] or 0.0,
            rating_count=row["rating_count"] or 0,
            created_at=_safe_parse_dt(row["created_at"]),
        )

    def _row_to_skill_listing(self, row: sqlite3.Row) -> SkillListing:
        """将数据库行转换为增强版 SkillListing."""
        return SkillListing(
            id=row["package_id"],
            skill_id=row["skill_id"],
            name=row["name"],
            version=row["version"],
            author=row["author"] or "",
            description=row["description"] or "",
            category=row["category"] or "general",
            tags=_safe_json_loads(row["tags"], []),
            icon_url=row["icon_url"] if "icon_url" in row.keys() else "",
            price_type=row["price_type"] if "price_type" in row.keys() else "free",
            price_amount=row["price_amount"] if "price_amount" in row.keys() else 0.0,
            rating=row["rating_avg"] or 0.0,
            rating_count=row["rating_count"] or 0,
            install_count=row["install_count"] if "install_count" in row.keys() else 0,
            download_count=row["download_count"] or 0,
            is_official=bool(row["is_official"]) if "is_official" in row.keys() else False,
            is_verified=bool(row["is_verified"]) if "is_verified" in row.keys() else False,
            created_at=_safe_parse_dt(row["created_at"]),
            updated_at=_safe_parse_dt(row["updated_at"]),
        )

    @staticmethod
    def _row_to_review(row: sqlite3.Row) -> SkillReview:
        return SkillReview(
            id=row["id"],
            skill_id=row["package_id"],
            user_id=row["user_id"],
            user_name=row["user_name"] or "",
            rating=row["rating"],
            comment=row["comment"] or "",
            likes=row["likes"] or 0,
            created_at=_safe_parse_dt(row["created_at"]),
        )

    @staticmethod
    def _row_to_category(row: sqlite3.Row) -> CategoryInfo:
        return CategoryInfo(
            category_id=row["category_id"],
            name=row["name"],
            description=row["description"] or "",
            icon=row["icon"] or "",
            skill_count=row["skill_count"] if "skill_count" in row.keys() else 0,
            parent_id=row["parent_id"] if "parent_id" in row.keys() else None,
        )

    # ------------------------------------------------------------------
    # 1. 浏览与搜索
    # ------------------------------------------------------------------

    def list_skills(
        self,
        category: Optional[str] = None,
        tags: Optional[List[str]] = None,
        sort: str = "newest",
        page: int = 1,
        page_size: int = 20,
        price_type: Optional[str] = None,
        is_official: Optional[bool] = None,
        is_verified: Optional[bool] = None,
        min_rating: Optional[float] = None,
    ) -> Tuple[List[SkillListing], int]:
        """技能列表（增强版，支持多维度过滤）.

        Args:
            category: 分类过滤
            tags: 多标签过滤（AND 关系）
            sort: 排序方式
            page: 页码
            page_size: 每页数量
            price_type: 价格类型过滤
            is_official: 是否官方
            is_verified: 是否认证
            min_rating: 最低评分

        Returns:
            (items, total)
        """
        where_clauses = ["sp.status = 'published'", "sp.is_public = 1"]
        params: List[Any] = []

        if category:
            where_clauses.append("sp.category = ?")
            params.append(category)

        if tags:
            for tag in tags:
                where_clauses.append("sp.tags LIKE ?")
                params.append(f'%"{tag}"%')

        if price_type and price_type in _PRICE_TYPES:
            where_clauses.append("se.price_type = ?")
            params.append(price_type)

        if is_official is not None:
            where_clauses.append("se.is_official = ?")
            params.append(1 if is_official else 0)

        if is_verified is not None:
            where_clauses.append("se.is_verified = ?")
            params.append(1 if is_verified else 0)

        if min_rating is not None:
            where_clauses.append("sp.rating_avg >= ?")
            params.append(min_rating)

        where_sql = " AND ".join(where_clauses)
        order_sql = _validate_sort(sort)

        page = max(1, page)
        page_size = max(1, min(page_size, 100))
        offset = (page - 1) * page_size

        with self._get_conn() as conn:
            total_row = conn.execute(
                f"""
                SELECT COUNT(*) AS cnt
                FROM skill_packages sp
                LEFT JOIN skill_extra se ON sp.package_id = se.package_id
                WHERE {where_sql}
                """,
                params,
            ).fetchone()
            total = total_row["cnt"] if total_row else 0

            rows = conn.execute(
                f"""
                SELECT sp.*,
                       COALESCE(se.price_type, 'free') AS price_type,
                       COALESCE(se.price_amount, 0.0) AS price_amount,
                       COALESCE(se.icon_url, '') AS icon_url,
                       COALESCE(se.is_official, 0) AS is_official,
                       COALESCE(se.is_verified, 0) AS is_verified,
                       COALESCE(se.install_count, 0) AS install_count
                FROM skill_packages sp
                LEFT JOIN skill_extra se ON sp.package_id = se.package_id
                WHERE {where_sql}
                ORDER BY {order_sql}
                LIMIT ? OFFSET ?
                """,
                params + [page_size, offset],
            ).fetchall()

        items = [self._row_to_skill_listing(r) for r in rows]
        return items, total

    def search_skills(
        self,
        keyword: str,
        filters: Optional[SearchFilters] = None,
        page: int = 1,
        page_size: int = 20,
    ) -> Tuple[List[SkillListing], int]:
        """搜索技能（增强版，支持多维度过滤）.

        在 name / description / tags / skill_id / author 中模糊匹配，
        并支持 filters 中的额外过滤条件。
        """
        where_clauses = ["sp.status = 'published'", "sp.is_public = 1"]
        params: List[Any] = []

        # 关键词搜索
        kw = f"%{keyword}%"
        where_clauses.append(
            "(sp.name LIKE ? OR sp.description LIKE ? OR sp.tags LIKE ? "
            "OR sp.skill_id LIKE ? OR sp.author LIKE ?)"
        )
        params.extend([kw, kw, kw, kw, kw])

        if filters:
            if filters.category:
                where_clauses.append("sp.category = ?")
                params.append(filters.category)
            if filters.tags:
                for tag in filters.tags:
                    where_clauses.append("sp.tags LIKE ?")
                    params.append(f'%"{tag}"%')
            if filters.price_type and filters.price_type in _PRICE_TYPES:
                where_clauses.append("se.price_type = ?")
                params.append(filters.price_type)
            if filters.is_official is not None:
                where_clauses.append("se.is_official = ?")
                params.append(1 if filters.is_official else 0)
            if filters.is_verified is not None:
                where_clauses.append("se.is_verified = ?")
                params.append(1 if filters.is_verified else 0)
            if filters.min_rating is not None:
                where_clauses.append("sp.rating_avg >= ?")
                params.append(filters.min_rating)
            if filters.author:
                where_clauses.append("sp.author LIKE ?")
                params.append(f"%{filters.author}%")

        where_sql = " AND ".join(where_clauses)
        page = max(1, page)
        page_size = max(1, min(page_size, 100))
        offset = (page - 1) * page_size

        with self._get_conn() as conn:
            total_row = conn.execute(
                f"""
                SELECT COUNT(*) AS cnt
                FROM skill_packages sp
                LEFT JOIN skill_extra se ON sp.package_id = se.package_id
                WHERE {where_sql}
                """,
                params,
            ).fetchone()
            total = total_row["cnt"] if total_row else 0

            rows = conn.execute(
                f"""
                SELECT sp.*,
                       COALESCE(se.price_type, 'free') AS price_type,
                       COALESCE(se.price_amount, 0.0) AS price_amount,
                       COALESCE(se.icon_url, '') AS icon_url,
                       COALESCE(se.is_official, 0) AS is_official,
                       COALESCE(se.is_verified, 0) AS is_verified,
                       COALESCE(se.install_count, 0) AS install_count
                FROM skill_packages sp
                LEFT JOIN skill_extra se ON sp.package_id = se.package_id
                WHERE {where_sql}
                ORDER BY sp.download_count DESC, sp.created_at DESC
                LIMIT ? OFFSET ?
                """,
                params + [page_size, offset],
            ).fetchall()

        items = [self._row_to_skill_listing(r) for r in rows]
        return items, total

    def get_skill_detail(self, skill_id: str) -> Optional[SkillListing]:
        """获取技能详情（增强版，含扩展信息）.

        Args:
            skill_id: 技能包 ID（即 package_id）

        Returns:
            SkillListing 或 None
        """
        with self._get_conn() as conn:
            row = conn.execute(
                """
                SELECT sp.*,
                       COALESCE(se.price_type, 'free') AS price_type,
                       COALESCE(se.price_amount, 0.0) AS price_amount,
                       COALESCE(se.icon_url, '') AS icon_url,
                       COALESCE(se.is_official, 0) AS is_official,
                       COALESCE(se.is_verified, 0) AS is_verified,
                       COALESCE(se.install_count, 0) AS install_count
                FROM skill_packages sp
                LEFT JOIN skill_extra se ON sp.package_id = se.package_id
                WHERE sp.package_id = ?
                """,
                (skill_id,),
            ).fetchone()

        if row is None:
            return None
        return self._row_to_skill_listing(row)

    def get_categories(self) -> List[CategoryInfo]:
        """获取分类列表（含技能数量统计）."""
        with self._get_conn() as conn:
            rows = conn.execute(
                """
                SELECT c.*,
                       COALESCE(pkg.cnt, 0) AS skill_count
                FROM categories c
                LEFT JOIN (
                    SELECT category, COUNT(*) AS cnt
                    FROM skill_packages
                    WHERE status = 'published' AND is_public = 1
                    GROUP BY category
                ) pkg ON c.category_id = pkg.category
                ORDER BY c.sort_order ASC, c.name ASC
                """
            ).fetchall()
        return [self._row_to_category(r) for r in rows]

    # ------------------------------------------------------------------
    # 2. 安装与卸载（用户维度）
    # ------------------------------------------------------------------

    def install_skill(self, skill_id: str, user_id: str) -> Dict[str, Any]:
        """用户安装技能.

        流程：
        1. 调用底层 MarketRegistry.install() 安装文件
        2. 记录用户安装记录
        3. 更新安装计数

        Args:
            skill_id: 技能包 ID（package_id）
            user_id: 用户 ID

        Returns:
            安装结果字典
        """
        # 调用底层安装
        result = self._registry.install(skill_id)

        # 记录用户安装记录
        now = datetime.now(tz=timezone.utc).isoformat()
        with self._get_conn() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO installed_skills
                    (user_id, package_id, skill_id, version, installed_at, is_active)
                VALUES (?, ?, ?, ?, ?, 1)
                """,
                (user_id, skill_id, result.get("skill_id", ""), result.get("version", ""), now),
            )
            # 更新安装计数
            conn.execute(
                """
                INSERT INTO skill_extra (package_id, install_count, updated_at)
                VALUES (?, 1, ?)
                ON CONFLICT(package_id) DO UPDATE SET
                    install_count = install_count + 1,
                    updated_at = excluded.updated_at
                """,
                (skill_id, now),
            )

        result["user_id"] = user_id
        result["installed_at"] = now
        logger.info("skill_installed_by_user", skill_id=skill_id, user_id=user_id)
        return result

    def uninstall_skill(self, skill_id: str, user_id: str) -> bool:
        """用户卸载技能.

        Args:
            skill_id: 技能包 ID
            user_id: 用户 ID

        Returns:
            是否成功
        """
        # 调用底层卸载
        success = self._registry.uninstall(skill_id)

        # 更新用户安装记录
        with self._get_conn() as conn:
            conn.execute(
                """
                UPDATE installed_skills
                SET is_active = 0
                WHERE user_id = ? AND package_id = ?
                """,
                (user_id, skill_id),
            )

        logger.info(
            "skill_uninstalled_by_user",
            skill_id=skill_id,
            user_id=user_id,
            success=success,
        )
        return True  # 即使底层卸载失败，也记录用户侧卸载

    def update_skill(self, skill_id: str, user_id: str) -> Dict[str, Any]:
        """更新技能到最新版本.

        检查是否有新版本可用，如有则重新安装。

        Args:
            skill_id: 技能包 ID
            user_id: 用户 ID

        Returns:
            更新结果字典
        """
        pkg = self._registry.get_package(skill_id)
        if pkg is None:
            raise FileNotFoundError(f"技能包不存在: {skill_id}")

        # 获取当前安装版本
        current_version = None
        with self._get_conn() as conn:
            row = conn.execute(
                """
                SELECT version FROM installed_skills
                WHERE user_id = ? AND package_id = ? AND is_active = 1
                """,
                (user_id, skill_id),
            ).fetchone()
            if row:
                current_version = row["version"]

        # 简单版本比较（实际场景应检查版本号大小）
        latest_version = pkg.version
        has_update = current_version != latest_version

        if has_update:
            # 重新安装（覆盖）
            result = self._registry.install(skill_id)
            now = datetime.now(tz=timezone.utc).isoformat()
            with self._get_conn() as conn:
                conn.execute(
                    """
                    UPDATE installed_skills
                    SET version = ?, installed_at = ?, is_active = 1
                    WHERE user_id = ? AND package_id = ?
                    """,
                    (latest_version, now, user_id, skill_id),
                )
            result["updated"] = True
            result["previous_version"] = current_version
            result["new_version"] = latest_version
        else:
            result = {
                "package_id": skill_id,
                "skill_id": pkg.skill_id,
                "name": pkg.name,
                "version": latest_version,
                "updated": False,
                "message": "已是最新版本",
            }

        return result

    def get_installed_skills(self, user_id: str) -> List[InstalledSkill]:
        """获取用户已安装的技能列表.

        Args:
            user_id: 用户 ID

        Returns:
            已安装技能列表
        """
        with self._get_conn() as conn:
            rows = conn.execute(
                """
                SELECT * FROM installed_skills
                WHERE user_id = ? AND is_active = 1
                ORDER BY installed_at DESC
                """,
                (user_id,),
            ).fetchall()

        return [
            InstalledSkill(
                user_id=row["user_id"],
                skill_id=row["skill_id"],
                package_id=row["package_id"],
                installed_at=_safe_parse_dt(row["installed_at"]),
                version=row["version"] or "",
                is_active=bool(row["is_active"]),
            )
            for row in rows
        ]

    # ------------------------------------------------------------------
    # 3. 评分与评论（增强版）
    # ------------------------------------------------------------------

    def rate_skill(
        self,
        skill_id: str,
        user_id: str,
        rating: int,
        comment: str = "",
        user_name: str = "",
    ) -> bool:
        """评分评论（增强版，支持用户名）.

        使用新增的 skill_reviews 表，保持与原有 ratings 表的数据同步。
        """
        if rating < 1 or rating > 5:
            raise ValueError("评分必须在 1-5 之间")

        now = datetime.now(tz=timezone.utc).isoformat()

        with self._get_conn() as conn:
            # 检查技能是否存在
            row = conn.execute(
                "SELECT package_id FROM skill_packages WHERE package_id = ?",
                (skill_id,),
            ).fetchone()
            if row is None:
                return False

            # 插入/更新评论
            conn.execute(
                """
                INSERT INTO skill_reviews
                    (package_id, user_id, user_name, rating, comment, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(package_id, user_id) DO UPDATE SET
                    rating = excluded.rating,
                    comment = excluded.comment,
                    user_name = excluded.user_name,
                    created_at = excluded.created_at
                """,
                (skill_id, user_id, user_name, rating, comment, now),
            )

            # 重新计算平均分和评分数
            stats_row = conn.execute(
                """
                SELECT COUNT(*) AS cnt, AVG(rating) AS avg_rating
                FROM skill_reviews WHERE package_id = ?
                """,
                (skill_id,),
            ).fetchone()

            rating_count = stats_row["cnt"] if stats_row else 0
            rating_avg = (
                round(stats_row["avg_rating"], 2)
                if stats_row and stats_row["avg_rating"]
                else 0.0
            )

            conn.execute(
                """
                UPDATE skill_packages
                SET rating_avg = ?, rating_count = ?, updated_at = ?
                WHERE package_id = ?
                """,
                (rating_avg, rating_count, now, skill_id),
            )

            # 同步更新原有 ratings 表（保持向后兼容）
            try:
                conn.execute(
                    """
                    INSERT INTO ratings (package_id, user_id, rating, comment, created_at)
                    VALUES (?, ?, ?, ?, ?)
                    ON CONFLICT(package_id, user_id) DO UPDATE SET
                        rating = excluded.rating,
                        comment = excluded.comment,
                        created_at = excluded.created_at
                    """,
                    (skill_id, user_id, rating, comment, now),
                )
            except Exception:
                pass  # 同步失败不影响主流程

        logger.info(
            "skill_rated_enhanced",
            skill_id=skill_id,
            user_id=user_id,
            rating=rating,
        )
        return True

    def get_reviews(
        self,
        skill_id: str,
        page: int = 1,
        page_size: int = 20,
        sort_by: str = "newest",  # newest / highest / lowest / most_liked
    ) -> Tuple[List[SkillReview], int]:
        """获取评论列表（分页）.

        Args:
            skill_id: 技能包 ID
            page: 页码
            page_size: 每页数量
            sort_by: 排序方式

        Returns:
            (reviews, total)
        """
        sort_map = {
            "newest": "created_at DESC",
            "highest": "rating DESC, created_at DESC",
            "lowest": "rating ASC, created_at DESC",
            "most_liked": "likes DESC, created_at DESC",
        }
        order_sql = sort_map.get(sort_by, sort_map["newest"])

        page = max(1, page)
        page_size = max(1, min(page_size, 100))
        offset = (page - 1) * page_size

        with self._get_conn() as conn:
            total_row = conn.execute(
                "SELECT COUNT(*) AS cnt FROM skill_reviews WHERE package_id = ?",
                (skill_id,),
            ).fetchone()
            total = total_row["cnt"] if total_row else 0

            rows = conn.execute(
                f"""
                SELECT * FROM skill_reviews
                WHERE package_id = ?
                ORDER BY {order_sql}
                LIMIT ? OFFSET ?
                """,
                (skill_id, page_size, offset),
            ).fetchall()

        reviews = [self._row_to_review(r) for r in rows]
        return reviews, total

    def get_skill_rating(self, skill_id: str) -> SkillRatingStats:
        """获取技能评分统计（含分布）.

        Args:
            skill_id: 技能包 ID

        Returns:
            评分统计
        """
        with self._get_conn() as conn:
            stats_row = conn.execute(
                """
                SELECT COUNT(*) AS cnt, AVG(rating) AS avg_rating
                FROM skill_reviews WHERE package_id = ?
                """,
                (skill_id,),
            ).fetchone()

            dist_rows = conn.execute(
                """
                SELECT rating, COUNT(*) AS cnt
                FROM skill_reviews WHERE package_id = ?
                GROUP BY rating
                ORDER BY rating DESC
                """,
                (skill_id,),
            ).fetchall()

        total_count = stats_row["cnt"] if stats_row else 0
        avg_rating = (
            round(stats_row["avg_rating"], 2)
            if stats_row and stats_row["avg_rating"]
            else 0.0
        )

        distribution = {r["rating"]: r["cnt"] for r in dist_rows}
        # 补全 1-5 星
        for i in range(1, 6):
            if i not in distribution:
                distribution[i] = 0

        return SkillRatingStats(
            skill_id=skill_id,
            avg_rating=avg_rating,
            total_count=total_count,
            distribution=distribution,
        )

    def like_review(self, review_id: int, user_id: str) -> bool:
        """点赞评论.

        简单实现：每次调用点赞数 +1（实际生产环境应防止重复点赞）。
        """
        with self._get_conn() as conn:
            conn.execute(
                "UPDATE skill_reviews SET likes = likes + 1 WHERE id = ?",
                (review_id,),
            )
            row = conn.execute(
                "SELECT changes() AS cnt"
            ).fetchone()
            return row["cnt"] > 0 if row else False

    # ------------------------------------------------------------------
    # 4. 技能上架管理
    # ------------------------------------------------------------------

    def publish_skill(
        self,
        skill_data: Dict[str, Any],
        author_id: str,
    ) -> SkillPackage:
        """发布技能到市场.

        在 MarketRegistry.publish() 基础上，支持更多元数据。

        Args:
            skill_data: 技能数据字典
            author_id: 作者 ID

        Returns:
            SkillPackage 实例
        """
        request = PublishRequest(
            skill_id=skill_data.get("skill_id", ""),
            description=skill_data.get("description", ""),
            category=skill_data.get("category", "general"),
            tags=skill_data.get("tags", []),
            is_public=skill_data.get("is_public", True),
        )

        pkg = self._registry.publish(
            skill_id=request.skill_id,
            request=request,
            author=skill_data.get("author", author_id),
        )

        # 写入扩展信息
        now = datetime.now(tz=timezone.utc).isoformat()
        price_type = skill_data.get("price_type", "free")
        if price_type not in _PRICE_TYPES:
            price_type = "free"

        with self._get_conn() as conn:
            conn.execute(
                """
                INSERT INTO skill_extra
                    (package_id, price_type, price_amount, icon_url,
                     is_official, is_verified, install_count, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, 0, ?)
                ON CONFLICT(package_id) DO UPDATE SET
                    price_type = excluded.price_type,
                    price_amount = excluded.price_amount,
                    icon_url = excluded.icon_url,
                    updated_at = excluded.updated_at
                """,
                (
                    pkg.package_id,
                    price_type,
                    skill_data.get("price_amount", 0.0),
                    skill_data.get("icon_url", ""),
                    1 if skill_data.get("is_official", False) else 0,
                    1 if skill_data.get("is_verified", False) else 0,
                    now,
                ),
            )

        return pkg

    def update_listing(self, skill_id: str, data: Dict[str, Any]) -> bool:
        """更新上架信息.

        支持更新：description, category, tags, icon_url, price_type, price_amount
        """
        now = datetime.now(tz=timezone.utc).isoformat()

        # 更新基本信息
        update_fields = []
        params: List[Any] = []

        if "description" in data:
            update_fields.append("description = ?")
            params.append(data["description"])
        if "category" in data:
            update_fields.append("category = ?")
            params.append(data["category"])
        if "tags" in data:
            update_fields.append("tags = ?")
            params.append(json.dumps(data["tags"], ensure_ascii=False))

        if update_fields:
            update_fields.append("updated_at = ?")
            params.append(now)
            params.append(skill_id)

            with self._get_conn() as conn:
                conn.execute(
                    f"""
                    UPDATE skill_packages
                    SET {', '.join(update_fields)}
                    WHERE package_id = ?
                    """,
                    params,
                )

        # 更新扩展信息
        extra_fields = []
        extra_params: List[Any] = []

        if "icon_url" in data:
            extra_fields.append("icon_url = ?")
            extra_params.append(data["icon_url"])
        if "price_type" in data and data["price_type"] in _PRICE_TYPES:
            extra_fields.append("price_type = ?")
            extra_params.append(data["price_type"])
        if "price_amount" in data:
            extra_fields.append("price_amount = ?")
            extra_params.append(data["price_amount"])
        if "is_official" in data:
            extra_fields.append("is_official = ?")
            extra_params.append(1 if data["is_official"] else 0)
        if "is_verified" in data:
            extra_fields.append("is_verified = ?")
            extra_params.append(1 if data["is_verified"] else 0)

        if extra_fields:
            extra_fields.append("updated_at = ?")
            extra_params.append(now)
            extra_params.append(skill_id)

            with self._get_conn() as conn:
                conn.execute(
                    f"""
                    INSERT INTO skill_extra (package_id, {', '.join(f.split(' = ')[0] for f in extra_fields)})
                    VALUES (?, {', '.join('?' for _ in extra_params[:-1])})
                    ON CONFLICT(package_id) DO UPDATE SET
                        {', '.join(extra_fields)}
                    WHERE package_id = ?
                    """,
                    [skill_id] + [p for i, p in enumerate(extra_params) if i < len(extra_params) - 1] + [skill_id],
                )

        return True

    def unpublish_skill(self, skill_id: str) -> bool:
        """下架技能."""
        return self._registry.unpublish(skill_id)

    # ------------------------------------------------------------------
    # 辅助方法
    # ------------------------------------------------------------------

    def get_registry(self) -> MarketRegistry:
        """获取底层 MarketRegistry 实例."""
        return self._registry
