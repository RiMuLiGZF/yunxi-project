from __future__ import annotations

"""技能市场 - 注册中心.

管理技能包的上架、下架、浏览、搜索、安装、卸载、评分等核心业务逻辑。
使用 SQLite 持久化元数据，文件系统存储技能包 zip 文件。

与现有系统的集成点：
- publish() 从 SkillRegistry 获取技能信息（try/except 降级）
- install() 调用 PluginLoader 加载已安装技能（try/except 降级）
"""

import inspect
import json
import os
import re
import sqlite3
import tempfile
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import structlog

from skill_cluster.market.models import (
    MarketListing,
    MarketStats,
    PublishRequest,
    SkillPackage,
)
from skill_cluster.market.store import SkillPackageStore

logger = structlog.get_logger()


# ===========================================================================
# SQL 安全校验（SEC-005 防 SQL 注入）
# ===========================================================================

# 安全的列名/表名正则
_SAFE_IDENTIFIER_RE = re.compile(r'^[a-zA-Z_][a-zA-Z0-9_]*$')

# skill_packages 表允许排序的列名白名单
_PACKAGE_SORT_COLUMNS = {
    "created_at",
    "updated_at",
    "download_count",
    "rating_avg",
    "rating_count",
    "name",
    "version",
    "author",
    "category",
    "package_id",
    "file_size",
}

# 允许的排序方式映射（sort 参数 -> ORDER BY 子句）
_SORT_OPTIONS: Dict[str, str] = {
    "newest": "created_at DESC",
    "popular": "download_count DESC, created_at DESC",
    "downloads": "download_count DESC, created_at DESC",
    "rating": "rating_avg DESC, rating_count DESC",
    "oldest": "created_at ASC",
    "name": "name ASC",
    "updated": "updated_at DESC",
}


def _validate_sort(sort: str) -> str:
    """校验排序参数并返回安全的 ORDER BY 子句.

    Args:
        sort: 排序方式名称

    Returns:
        安全的 ORDER BY 子句

    Raises:
        ValueError: 不支持的排序方式
    """
    if sort not in _SORT_OPTIONS:
        raise ValueError(
            f"Invalid sort option: {repr(sort)}. "
            f"Supported: {sorted(_SORT_OPTIONS.keys())}"
        )
    return _SORT_OPTIONS[sort]


def _validate_identifier(name: str, kind: str = "identifier") -> str:
    """校验 SQL 标识符是否安全.

    Args:
        name: 标识符名称
        kind: 标识符类型

    Returns:
        原始名称（如果安全）

    Raises:
        ValueError: 标识符不安全
    """
    if not name or not isinstance(name, str):
        raise ValueError(f"Invalid {kind}: empty or non-string")
    if not _SAFE_IDENTIFIER_RE.match(name):
        raise ValueError(
            f"Invalid {kind}: {repr(name)} - only alphanumeric and underscore allowed"
        )
    return name


def _safe_json_loads(value: str, default: Any) -> Any:
    """安全反序列化 JSON 字符串，失败返回默认值."""
    if not value:
        return default
    try:
        return json.loads(value)
    except (json.JSONDecodeError, TypeError):
        return default


def _safe_parse_dt(value: str) -> datetime:
    """安全解析 ISO 时间字符串，失败返回当前时间."""
    if not value:
        return datetime.now(tz=timezone.utc)
    try:
        return datetime.fromisoformat(value)
    except (ValueError, TypeError):
        return datetime.now(tz=timezone.utc)


class MarketRegistry:
    """技能市场注册中心.

    单例模式，通过 get_instance() 获取全局实例。
    管理 SQLite 数据库（skill_packages / ratings / download_logs 三张表）
    和文件存储（SkillPackageStore）。
    """

    _instance: Optional["MarketRegistry"] = None
    _lock = threading.Lock()
    # 全局 SkillRegistry 引用，由外部通过 set_skill_registry() 注入
    _skill_registry: Any = None

    def __init__(self, db_path: Optional[str] = None) -> None:
        if db_path is None:
            db_path = os.path.join(
                os.path.expanduser("~"), ".yunxi", "market", "market.db"
            )
        os.makedirs(os.path.dirname(db_path), exist_ok=True)
        self.db_path = db_path
        self.store = SkillPackageStore()
        self._init_db()

    # ------------------------------------------------------------------
    # 单例
    # ------------------------------------------------------------------

    @classmethod
    def get_instance(cls) -> "MarketRegistry":
        """获取单例实例."""
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = cls()
        return cls._instance

    @classmethod
    def set_skill_registry(cls, registry: Any) -> None:
        """注入全局 SkillRegistry 实例，供 publish() 使用."""
        cls._skill_registry = registry

    # ------------------------------------------------------------------
    # 数据库
    # ------------------------------------------------------------------

    def _init_db(self) -> None:
        """初始化 SQLite 数据库，创建 skill_packages / ratings / download_logs 表."""
        with self._get_conn() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS skill_packages (
                    package_id     TEXT PRIMARY KEY,
                    skill_id       TEXT NOT NULL,
                    name           TEXT NOT NULL,
                    version        TEXT NOT NULL,
                    description    TEXT,
                    author         TEXT,
                    tags           TEXT,
                    category       TEXT DEFAULT 'general',
                    capabilities   TEXT,
                    dependencies   TEXT,
                    permissions    TEXT,
                    checksum       TEXT,
                    file_size      INTEGER DEFAULT 0,
                    status         TEXT DEFAULT 'published',
                    download_count INTEGER DEFAULT 0,
                    rating_avg     REAL DEFAULT 0.0,
                    rating_count   INTEGER DEFAULT 0,
                    created_at     TEXT,
                    updated_at     TEXT,
                    entry_point    TEXT DEFAULT 'skill.py',
                    is_public      INTEGER DEFAULT 1
                );

                CREATE TABLE IF NOT EXISTS ratings (
                    id          INTEGER PRIMARY KEY AUTOINCREMENT,
                    package_id  TEXT NOT NULL,
                    user_id     TEXT NOT NULL,
                    rating      INTEGER NOT NULL,
                    comment     TEXT,
                    created_at  TEXT,
                    UNIQUE(package_id, user_id)
                );

                CREATE TABLE IF NOT EXISTS download_logs (
                    id          INTEGER PRIMARY KEY AUTOINCREMENT,
                    package_id  TEXT NOT NULL,
                    action      TEXT,
                    target_dir  TEXT,
                    status      TEXT,
                    created_at  TEXT
                );

                CREATE INDEX IF NOT EXISTS idx_packages_category
                    ON skill_packages(category);
                CREATE INDEX IF NOT EXISTS idx_packages_status
                    ON skill_packages(status);
                CREATE INDEX IF NOT EXISTS idx_packages_downloads
                    ON skill_packages(download_count);
                CREATE INDEX IF NOT EXISTS idx_ratings_package
                    ON ratings(package_id);
                """
            )

    def _get_conn(self) -> sqlite3.Connection:
        """获取 SQLite 连接（row_factory=Row）."""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    # ------------------------------------------------------------------
    # 行转换
    # ------------------------------------------------------------------

    @staticmethod
    def _row_to_package(row: sqlite3.Row) -> SkillPackage:
        """将数据库行转换为 SkillPackage."""
        return SkillPackage(
            package_id=row["package_id"],
            skill_id=row["skill_id"],
            name=row["name"],
            version=row["version"],
            description=row["description"] or "",
            author=row["author"] or "",
            tags=_safe_json_loads(row["tags"], []),
            category=row["category"] or "general",
            capabilities=_safe_json_loads(row["capabilities"], []),
            dependencies=_safe_json_loads(row["dependencies"], []),
            permissions=_safe_json_loads(row["permissions"], []),
            checksum=row["checksum"] or "",
            file_size=row["file_size"] or 0,
            status=row["status"] or "published",
            download_count=row["download_count"] or 0,
            rating_avg=row["rating_avg"] or 0.0,
            rating_count=row["rating_count"] or 0,
            created_at=_safe_parse_dt(row["created_at"]),
            updated_at=_safe_parse_dt(row["updated_at"]),
            entry_point=row["entry_point"] or "skill.py",
        )

    @staticmethod
    def _row_to_listing(row: sqlite3.Row) -> MarketListing:
        """将数据库行转换为 MarketListing."""
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

    # ------------------------------------------------------------------
    # SkillRegistry / PluginLoader 集成（try/except 降级）
    # ------------------------------------------------------------------

    def _get_skill_registry(self) -> Any:
        """获取全局 SkillRegistry 实例，失败返回 None."""
        if MarketRegistry._skill_registry is not None:
            return MarketRegistry._skill_registry
        try:
            from skill_cluster.core.registry import SkillRegistry

            return SkillRegistry()
        except Exception:
            return None

    def _find_skill_dir(self, skill_id: str) -> Optional[str]:
        """查找技能源文件目录.

        查找策略：
        1. 从 SkillRegistry 获取技能实例，用 inspect.getfile 定位源文件
        2. 从 skill_id 推导短名，在 skill_cluster/skills/ 目录下查找
        3. 均失败返回 None
        """
        # 策略 1：从 registry 获取技能实例
        registry = self._get_skill_registry()
        if registry is not None:
            try:
                skill = None
                if hasattr(registry, "get_skill"):
                    skill = registry.get_skill(skill_id)
                elif hasattr(registry, "get"):
                    wrapped = registry.get(skill_id)
                    skill = getattr(wrapped, "_skill", wrapped) if wrapped else None
                if skill is not None:
                    fpath = inspect.getfile(type(skill))
                    return str(Path(fpath).resolve().parent)
            except Exception as e:
                logger.debug(
                    "find_skill_dir_via_registry_failed",
                    skill_id=skill_id,
                    error=str(e),
                )

        # 策略 2：从 skill_id 推导文件名
        try:
            short_id = (
                skill_id.split(".")[-1] if "." in skill_id else skill_id
            )
            skills_dir = Path(__file__).resolve().parent.parent / "skills"
            candidate = skills_dir / f"{short_id}.py"
            if candidate.exists():
                return str(skills_dir)
        except Exception as e:
            logger.debug(
                "find_skill_dir_via_filename_failed",
                skill_id=skill_id,
                error=str(e),
            )

        return None

    def _build_manifest_json(
        self, pkg: SkillPackage
    ) -> Dict[str, Any]:
        """从 SkillPackage 构建 manifest.json 内容."""
        return {
            "package_id": pkg.package_id,
            "skill_id": pkg.skill_id,
            "name": pkg.name,
            "version": pkg.version,
            "description": pkg.description,
            "author": pkg.author,
            "tags": pkg.tags,
            "category": pkg.category,
            "capabilities": pkg.capabilities,
            "dependencies": pkg.dependencies,
            "permissions": pkg.permissions,
            "entry_point": pkg.entry_point,
            "created_at": pkg.created_at.isoformat(),
        }

    # ------------------------------------------------------------------
    # 上架 / 下架
    # ------------------------------------------------------------------

    def publish(
        self,
        skill_id: str,
        request: PublishRequest,
        author: str = "anonymous",
    ) -> SkillPackage:
        """上架技能到市场.

        流程：
        1. 尝试从 SkillRegistry 获取技能 manifest（失败则用 request 信息降级）
        2. 查找技能源文件目录
        3. 打包技能文件（临时目录 + manifest.json + .py 源文件）
        4. 保存到存储
        5. 写入数据库

        Args:
            skill_id: 技能 ID.
            request: 上架请求.
            author: 作者.

        Returns:
            SkillPackage 实例.

        Raises:
            RuntimeError: 无法找到技能源文件.
        """
        # 1. 获取技能信息
        name = skill_id
        version = "1.0.0"
        description = request.description
        capabilities: List[str] = []
        dependencies: List[str] = []
        permissions: List[str] = []
        entry_point = "skill.py"

        registry = self._get_skill_registry()
        if registry is not None:
            try:
                manifest = None
                if hasattr(registry, "get_manifest"):
                    manifest = registry.get_manifest(skill_id)
                if manifest is not None:
                    name = getattr(manifest, "name", name)
                    version = getattr(manifest, "version", version)
                    if not description:
                        description = getattr(manifest, "description", "")
                    capabilities = list(
                        getattr(manifest, "capabilities", []) or []
                    )
                    dependencies = list(
                        getattr(manifest, "dependencies", []) or []
                    )
                    permissions = list(
                        getattr(manifest, "permissions", []) or []
                    )
                    entry_point = getattr(
                        manifest, "entrypoint", entry_point
                    )
                    if not author or author == "anonymous":
                        author = getattr(manifest, "author", author)
            except Exception as e:
                logger.warning(
                    "publish_get_manifest_failed",
                    skill_id=skill_id,
                    error=str(e),
                )

        if not description:
            description = request.description or f"技能 {name}"

        # 2. 查找技能源文件目录
        skill_dir = self._find_skill_dir(skill_id)

        # 3. 打包
        checksum = ""
        file_size = 0
        now = datetime.now(tz=timezone.utc)
        package_id = f"pkg_{os.urandom(6).hex()}"

        pkg = SkillPackage(
            package_id=package_id,
            skill_id=skill_id,
            name=name,
            version=version,
            description=description,
            author=author,
            tags=request.tags,
            category=request.category,
            capabilities=capabilities,
            dependencies=dependencies,
            permissions=permissions,
            checksum=checksum,
            file_size=file_size,
            status="published",
            created_at=now,
            updated_at=now,
            entry_point=entry_point,
        )

        if skill_dir is not None:
            try:
                # 创建临时目录，复制源文件并写入 manifest.json
                with tempfile.TemporaryDirectory() as tmpdir:
                    tmp = Path(tmpdir)
                    # 写入 manifest.json
                    manifest_data = self._build_manifest_json(pkg)
                    (tmp / "manifest.json").write_text(
                        json.dumps(manifest_data, ensure_ascii=False, indent=2),
                        encoding="utf-8",
                    )
                    # 复制 .py 文件和 requirements.txt
                    src = Path(skill_dir)
                    short_id = (
                        skill_id.split(".")[-1]
                        if "." in skill_id
                        else skill_id
                    )
                    # 复制对应的 .py 文件
                    py_candidate = src / f"{short_id}.py"
                    if py_candidate.exists():
                        shutil_copy = False
                        try:
                            import shutil as _shutil

                            _shutil.copy2(str(py_candidate), str(tmp / py_candidate.name))
                            shutil_copy = True
                        except Exception:
                            pass
                        if not shutil_copy:
                            (tmp / py_candidate.name).write_text(
                                py_candidate.read_text(encoding="utf-8"),
                                encoding="utf-8",
                            )
                    # 复制 requirements.txt（若存在）
                    req_candidate = src / "requirements.txt"
                    if req_candidate.exists():
                        try:
                            import shutil as _shutil

                            _shutil.copy2(str(req_candidate), str(tmp / "requirements.txt"))
                        except Exception:
                            (tmp / "requirements.txt").write_text(
                                req_candidate.read_text(encoding="utf-8"),
                                encoding="utf-8",
                            )

                    data, checksum, file_size = self.store.pack_skill(
                        str(tmp), skill_id
                    )
                    self.store.save_package(package_id, data)
                    pkg.checksum = checksum
                    pkg.file_size = file_size
            except Exception as e:
                logger.warning(
                    "publish_pack_failed",
                    skill_id=skill_id,
                    error=str(e),
                )
        else:
            logger.warning(
                "publish_skill_dir_not_found",
                skill_id=skill_id,
                msg="技能源文件目录未找到，仅写入元数据",
            )

        # 4. 写入数据库
        is_public = 1 if request.is_public else 0
        with self._get_conn() as conn:
            conn.execute(
                """
                INSERT INTO skill_packages
                    (package_id, skill_id, name, version, description, author,
                     tags, category, capabilities, dependencies, permissions,
                     checksum, file_size, status, download_count, rating_avg,
                     rating_count, created_at, updated_at, entry_point, is_public)
                VALUES
                    (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    pkg.package_id,
                    pkg.skill_id,
                    pkg.name,
                    pkg.version,
                    pkg.description,
                    pkg.author,
                    json.dumps(pkg.tags, ensure_ascii=False),
                    pkg.category,
                    json.dumps(pkg.capabilities, ensure_ascii=False),
                    json.dumps(pkg.dependencies, ensure_ascii=False),
                    json.dumps(pkg.permissions, ensure_ascii=False),
                    pkg.checksum,
                    pkg.file_size,
                    pkg.status,
                    pkg.download_count,
                    pkg.rating_avg,
                    pkg.rating_count,
                    pkg.created_at.isoformat(),
                    pkg.updated_at.isoformat(),
                    pkg.entry_point,
                    is_public,
                ),
            )

        logger.info(
            "skill_published",
            package_id=pkg.package_id,
            skill_id=skill_id,
            name=name,
            version=version,
        )
        return pkg

    def unpublish(self, package_id: str) -> bool:
        """下架技能.

        将状态更新为 unpublished，并删除包文件。
        保留数据库记录用于历史追溯。
        """
        with self._get_conn() as conn:
            row = conn.execute(
                "SELECT package_id FROM skill_packages WHERE package_id = ?",
                (package_id,),
            ).fetchone()
            if row is None:
                return False
            conn.execute(
                """
                UPDATE skill_packages
                SET status = 'unpublished', updated_at = ?
                WHERE package_id = ?
                """,
                (datetime.now(tz=timezone.utc).isoformat(), package_id),
            )

        # 删除包文件
        try:
            self.store.delete_package(package_id)
        except Exception as e:
            logger.warning("unpublish_delete_file_failed", error=str(e))

        logger.info("skill_unpublished", package_id=package_id)
        return True

    # ------------------------------------------------------------------
    # 浏览 / 搜索
    # ------------------------------------------------------------------

    def list_packages(
        self,
        category: Optional[str] = None,
        tag: Optional[str] = None,
        page: int = 1,
        size: int = 20,
        sort: str = "newest",
    ) -> Tuple[List[MarketListing], int]:
        """浏览市场列表，返回 (items, total).

        安全特性（SEC-005）：
        - sort 参数使用白名单映射，防止 SQL 注入
        - 所有过滤条件使用参数化查询

        Args:
            category: 分类过滤.
            tag: 标签过滤.
            page: 页码（从 1 开始）.
            size: 每页数量.
            sort: 排序方式 - newest / popular / downloads / rating / oldest / name / updated.
        """
        where_clauses = ["status = 'published'", "is_public = 1"]
        params: List[Any] = []

        if category:
            where_clauses.append("category = ?")
            params.append(category)
        if tag:
            where_clauses.append("tags LIKE ?")
            params.append(f'%"{tag}"%')

        where_sql = " AND ".join(where_clauses)

        # SEC-005: 使用白名单映射获取安全的 ORDER BY 子句
        order_sql = _validate_sort(sort)

        page = max(1, page)
        size = max(1, min(size, 100))  # 限制每页最大 100 条
        offset = (page - 1) * size

        with self._get_conn() as conn:
            total_row = conn.execute(
                f"SELECT COUNT(*) AS cnt FROM skill_packages WHERE {where_sql}",
                params,
            ).fetchone()
            total = total_row["cnt"] if total_row else 0

            rows = conn.execute(
                f"""
                SELECT * FROM skill_packages
                WHERE {where_sql}
                ORDER BY {order_sql}
                LIMIT ? OFFSET ?
                """,
                params + [size, offset],
            ).fetchall()

        items = [self._row_to_listing(r) for r in rows]
        return items, total

    def search(
        self, query: str, page: int = 1, size: int = 20
    ) -> Tuple[List[MarketListing], int]:
        """搜索技能.

        在 name / description / tags / skill_id 中进行模糊匹配。
        """
        keyword = f"%{query}%"
        where_sql = (
            "status = 'published' AND is_public = 1 AND "
            "(name LIKE ? OR description LIKE ? OR tags LIKE ? OR skill_id LIKE ?)"
        )
        params = [keyword, keyword, keyword, keyword]
        offset = (page - 1) * size

        with self._get_conn() as conn:
            total_row = conn.execute(
                f"SELECT COUNT(*) AS cnt FROM skill_packages WHERE {where_sql}",
                params,
            ).fetchone()
            total = total_row["cnt"] if total_row else 0

            rows = conn.execute(
                f"""
                SELECT * FROM skill_packages
                WHERE {where_sql}
                ORDER BY download_count DESC, created_at DESC
                LIMIT ? OFFSET ?
                """,
                params + [size, offset],
            ).fetchall()

        items = [self._row_to_listing(r) for r in rows]
        return items, total

    def get_package(self, package_id: str) -> Optional[SkillPackage]:
        """获取技能包详情."""
        with self._get_conn() as conn:
            row = conn.execute(
                "SELECT * FROM skill_packages WHERE package_id = ?",
                (package_id,),
            ).fetchone()
        if row is None:
            return None
        return self._row_to_package(row)

    # ------------------------------------------------------------------
    # 安装 / 卸载
    # ------------------------------------------------------------------

    def install(
        self, package_id: str, target_dir: Optional[str] = None
    ) -> Dict[str, Any]:
        """安装技能包.

        流程：
        1. 获取包信息
        2. 读取包文件
        3. 解压到目标目录（默认 ~/.yunxi/skills/installed/{package_id}/）
        4. 尝试用 PluginLoader 加载
        5. 记录安装日志
        6. 增加下载计数

        Returns:
            安装信息字典.

        Raises:
            FileNotFoundError: 技能包不存在或文件缺失.
        """
        pkg = self.get_package(package_id)
        if pkg is None:
            raise FileNotFoundError(f"技能包不存在: {package_id}")

        # 确定安装目录
        if target_dir:
            install_path = target_dir
        else:
            install_path = str(self.store.get_installed_dir(package_id))

        # 读取包文件
        data = self.store.read_package(package_id)
        status = "success"
        error_msg = ""

        if data is not None:
            try:
                self.store.unpack_skill(data, install_path)
            except Exception as e:
                status = "failed"
                error_msg = str(e)
                logger.error(
                    "install_unpack_failed",
                    package_id=package_id,
                    error=str(e),
                )
                raise RuntimeError(f"解压失败: {e}") from e
        else:
            # 包文件不存在，仅记录元数据安装
            status = "metadata_only"
            logger.warning(
                "install_package_file_missing",
                package_id=package_id,
                msg="包文件不存在，仅记录安装元数据",
            )
            os.makedirs(install_path, exist_ok=True)

        # 尝试用 PluginLoader 加载（try/except 降级）
        plugin_loaded = False
        try:
            from skill_cluster.extensions.plugins.loader import PluginLoader

            loader = PluginLoader()
            loader.add_plugin_dir(install_path)
            infos = loader.scan()
            for info in infos:
                loaded = loader.load(info.plugin_id)
                if loaded is not None:
                    plugin_loaded = True
                    logger.info(
                        "install_plugin_loaded",
                        package_id=package_id,
                        plugin_id=info.plugin_id,
                    )
        except Exception as e:
            logger.warning(
                "install_plugin_load_failed",
                package_id=package_id,
                error=str(e),
            )

        # 记录安装日志
        try:
            with self._get_conn() as conn:
                conn.execute(
                    """
                    INSERT INTO download_logs
                        (package_id, action, target_dir, status, created_at)
                    VALUES (?, 'install', ?, ?, ?)
                    """,
                    (
                        package_id,
                        install_path,
                        status,
                        datetime.now(tz=timezone.utc).isoformat(),
                    ),
                )
                # 增加下载计数
                conn.execute(
                    """
                    UPDATE skill_packages
                    SET download_count = download_count + 1,
                        updated_at = ?
                    WHERE package_id = ?
                    """,
                    (datetime.now(tz=timezone.utc).isoformat(), package_id),
                )
        except Exception as e:
            logger.warning("install_log_failed", error=str(e))

        result: Dict[str, Any] = {
            "package_id": package_id,
            "skill_id": pkg.skill_id,
            "name": pkg.name,
            "version": pkg.version,
            "install_path": install_path,
            "status": status,
            "plugin_loaded": plugin_loaded,
        }
        if error_msg:
            result["error"] = error_msg

        logger.info(
            "skill_installed",
            package_id=package_id,
            install_path=install_path,
            plugin_loaded=plugin_loaded,
        )
        return result

    def uninstall(self, package_id: str) -> bool:
        """卸载已安装的技能.

        删除安装目录并记录日志。
        """
        installed_dir = self.store.get_installed_dir(package_id)
        if not installed_dir.exists():
            # 也检查是否有安装记录
            with self._get_conn() as conn:
                row = conn.execute(
                    """
                    SELECT id FROM download_logs
                    WHERE package_id = ? AND action = 'install' AND status = 'success'
                    LIMIT 1
                    """,
                    (package_id,),
                ).fetchone()
            if row is None:
                return False

        # 删除安装目录
        try:
            self.store.remove_installed(package_id)
        except Exception as e:
            logger.warning("uninstall_remove_dir_failed", error=str(e))

        # 尝试从 PluginLoader 卸载
        try:
            from skill_cluster.extensions.plugins.loader import PluginLoader

            loader = PluginLoader()
            for info in loader.list_loaded():
                if info.skill_id == package_id:
                    loader.unload(info.plugin_id)
        except Exception as e:
            logger.warning(
                "uninstall_plugin_unload_failed",
                error=str(e),
            )

        # 记录卸载日志
        try:
            with self._get_conn() as conn:
                conn.execute(
                    """
                    INSERT INTO download_logs
                        (package_id, action, target_dir, status, created_at)
                    VALUES (?, 'uninstall', ?, 'success', ?)
                    """,
                    (
                        package_id,
                        str(installed_dir),
                        datetime.now(tz=timezone.utc).isoformat(),
                    ),
                )
        except Exception as e:
            logger.warning("uninstall_log_failed", error=str(e))

        logger.info("skill_uninstalled", package_id=package_id)
        return True

    # ------------------------------------------------------------------
    # 评分
    # ------------------------------------------------------------------

    def rate(
        self,
        package_id: str,
        user_id: str,
        rating: int,
        comment: str = "",
    ) -> bool:
        """评分.

        每个用户对每个包只能评分一次（重复评分会更新）。
        评分后自动重新计算平均分和评分数。
        """
        with self._get_conn() as conn:
            row = conn.execute(
                "SELECT package_id FROM skill_packages WHERE package_id = ?",
                (package_id,),
            ).fetchone()
            if row is None:
                return False

            # 插入或更新评分
            conn.execute(
                """
                INSERT INTO ratings (package_id, user_id, rating, comment, created_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(package_id, user_id) DO UPDATE SET
                    rating = excluded.rating,
                    comment = excluded.comment,
                    created_at = excluded.created_at
                """,
                (
                    package_id,
                    user_id,
                    rating,
                    comment,
                    datetime.now(tz=timezone.utc).isoformat(),
                ),
            )

            # 重新计算平均分
            stats_row = conn.execute(
                """
                SELECT COUNT(*) AS cnt, AVG(rating) AS avg_rating
                FROM ratings WHERE package_id = ?
                """,
                (package_id,),
            ).fetchone()

            rating_count = stats_row["cnt"] if stats_row else 0
            rating_avg = round(stats_row["avg_rating"], 2) if stats_row and stats_row["avg_rating"] else 0.0

            conn.execute(
                """
                UPDATE skill_packages
                SET rating_avg = ?, rating_count = ?, updated_at = ?
                WHERE package_id = ?
                """,
                (rating_avg, rating_count, datetime.now(tz=timezone.utc).isoformat(), package_id),
            )

        logger.info(
            "skill_rated",
            package_id=package_id,
            user_id=user_id,
            rating=rating,
            rating_avg=rating_avg,
        )
        return True

    # ------------------------------------------------------------------
    # 统计 / 分类
    # ------------------------------------------------------------------

    def get_stats(self) -> MarketStats:
        """获取市场统计."""
        with self._get_conn() as conn:
            # 总包数
            total_row = conn.execute(
                "SELECT COUNT(*) AS cnt FROM skill_packages WHERE status = 'published'"
            ).fetchone()
            total_packages = total_row["cnt"] if total_row else 0

            # 总下载量
            dl_row = conn.execute(
                "SELECT COALESCE(SUM(download_count), 0) AS total FROM skill_packages"
            ).fetchone()
            total_downloads = dl_row["total"] if dl_row else 0

            # 总评分数
            rating_row = conn.execute(
                "SELECT COUNT(*) AS cnt FROM ratings"
            ).fetchone()
            total_ratings = rating_row["cnt"] if rating_row else 0

            # 平均评分
            avg_row = conn.execute(
                "SELECT AVG(rating) AS avg FROM ratings"
            ).fetchone()
            avg_rating = round(avg_row["avg"], 2) if avg_row and avg_row["avg"] else 0.0

            # 分类统计
            cat_rows = conn.execute(
                """
                SELECT category, COUNT(*) AS cnt
                FROM skill_packages
                WHERE status = 'published'
                GROUP BY category
                """
            ).fetchall()
            categories = {
                r["category"]: r["cnt"] for r in cat_rows
            }

            # 下载量 Top 5
            top_dl_rows = conn.execute(
                """
                SELECT * FROM skill_packages
                WHERE status = 'published' AND is_public = 1
                ORDER BY download_count DESC LIMIT 5
                """
            ).fetchall()
            top_downloaded = [self._row_to_listing(r) for r in top_dl_rows]

            # 评分 Top 5
            top_rated_rows = conn.execute(
                """
                SELECT * FROM skill_packages
                WHERE status = 'published' AND is_public = 1 AND rating_count > 0
                ORDER BY rating_avg DESC, rating_count DESC LIMIT 5
                """
            ).fetchall()
            top_rated = [self._row_to_listing(r) for r in top_rated_rows]

        return MarketStats(
            total_packages=total_packages,
            total_downloads=total_downloads,
            total_ratings=total_ratings,
            avg_rating=avg_rating,
            categories=categories,
            top_downloaded=top_downloaded,
            top_rated=top_rated,
        )

    def get_categories(self) -> List[Dict[str, Any]]:
        """获取分类列表（含每个分类的包数）."""
        with self._get_conn() as conn:
            rows = conn.execute(
                """
                SELECT category, COUNT(*) AS cnt
                FROM skill_packages
                WHERE status = 'published' AND is_public = 1
                GROUP BY category
                ORDER BY cnt DESC
                """
            ).fetchall()
        return [
            {"category": r["category"], "count": r["cnt"]}
            for r in rows
        ]
