"""
成长系统数据库管理

使用独立的 SQLite 数据库文件存储成长系统数据，
包含成就、天赋、日历三大模块的表结构和初始化逻辑。
"""

from __future__ import annotations

import json
import os
import sqlite3
import threading
from pathlib import Path
from typing import Any, Dict, List, Optional

from ..db import DatabaseMigrator


class GrowthDatabase:
    """
    成长系统 SQLite 数据库管理器

    负责数据库连接、表创建、预置数据初始化。
    使用独立数据库文件：data/growth/growth.db
    """

    _instance: Optional["GrowthDatabase"] = None
    _lock = threading.Lock()

    def __init__(self, db_path: str = None, use_migration: bool = True):
        """
        初始化数据库连接

        Args:
            db_path: 数据库文件路径，默认使用 data/growth/growth.db
            use_migration: 是否使用版本化迁移系统
        """
        if db_path is None:
            # 默认路径：模块根目录下的 data/growth/growth.db
            base_dir = Path(__file__).resolve().parent.parent.parent.parent
            db_path = str(base_dir / "data" / "growth" / "growth.db")

        self._db_path = db_path
        self._conn: Optional[sqlite3.Connection] = None
        self._thread_lock = threading.Lock()
        self._use_migration = use_migration

        # 确保目录存在
        os.makedirs(os.path.dirname(os.path.abspath(db_path)), exist_ok=True)

        # 初始化数据库
        self._init_database()

    @classmethod
    def get_instance(cls, db_path: str = None) -> "GrowthDatabase":
        """获取单例实例"""
        with cls._lock:
            if cls._instance is None:
                cls._instance = cls(db_path)
            return cls._instance

    def _get_connection(self) -> sqlite3.Connection:
        """获取数据库连接（线程安全，每次返回新连接以避免多线程问题）"""
        conn = sqlite3.connect(self._db_path, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        return conn

    def _init_database(self) -> None:
        """初始化数据库：建表 + 插入预置数据

        使用版本化迁移系统管理 schema，
        向后兼容：禁用迁移系统时回退到旧模式。
        """
        if self._use_migration:
            self._init_database_with_migration()
        else:
            self._init_database_legacy()

    def _get_migrator(self) -> DatabaseMigrator:
        """
        获取成长系统数据库的迁移器

        注册的迁移：
        - v1: 初始表结构 + 索引 + 预置数据

        Returns:
            DatabaseMigrator 实例
        """
        import structlog
        log = structlog.get_logger(__name__)
        migrator = DatabaseMigrator(self._db_path)

        def _init_seed_data(conn: sqlite3.Connection) -> None:
            """初始化预置数据（成就、天赋、点数、赛季）"""
            # 设置 row_factory 以兼容 GrowthDatabase 中的方法
            old_row_factory = conn.row_factory
            conn.row_factory = sqlite3.Row
            try:
                self._init_achievements(conn)
                self._init_talents(conn)
                self._init_points(conn)
                self._init_seasons(conn)
            finally:
                conn.row_factory = old_row_factory

        # v1: 初始 schema（所有表 + 索引 + 预置数据）
        migrator.register(
            version=1,
            name="initial_schema",
            up_sql=self._get_all_create_table_sql(),
            up_func=_init_seed_data,
        )

        return migrator

    def _get_all_create_table_sql(self) -> List[str]:
        """获取所有建表和建索引的 SQL 语句列表"""
        return [
            # 成就定义表
            """
            CREATE TABLE IF NOT EXISTS growth_achievements (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                category TEXT NOT NULL,
                rarity TEXT NOT NULL,
                rarity_text TEXT NOT NULL,
                condition TEXT NOT NULL,
                description TEXT NOT NULL,
                point_reward INTEGER DEFAULT 1,
                sort_order INTEGER DEFAULT 0,
                created_at TEXT DEFAULT (datetime('now'))
            )
            """,
            # 用户成就表
            """
            CREATE TABLE IF NOT EXISTS growth_user_achievements (
                achievement_id TEXT PRIMARY KEY,
                unlocked INTEGER DEFAULT 0,
                unlock_date TEXT DEFAULT '',
                unlocked_at TEXT DEFAULT '',
                FOREIGN KEY (achievement_id) REFERENCES growth_achievements(id)
            )
            """,
            # 天赋定义表
            """
            CREATE TABLE IF NOT EXISTS growth_talents (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                branch TEXT NOT NULL,
                tree TEXT NOT NULL,
                description TEXT NOT NULL,
                max_level INTEGER DEFAULT 1,
                parent_id TEXT DEFAULT '',
                children_ids TEXT DEFAULT '[]',
                point_cost INTEGER DEFAULT 1,
                layer INTEGER DEFAULT 1,
                sort_order INTEGER DEFAULT 0,
                created_at TEXT DEFAULT (datetime('now'))
            )
            """,
            # 用户天赋状态表
            """
            CREATE TABLE IF NOT EXISTS growth_user_talents (
                talent_id TEXT PRIMARY KEY,
                level INTEGER DEFAULT 0,
                status TEXT DEFAULT 'locked',
                updated_at TEXT DEFAULT (datetime('now')),
                FOREIGN KEY (talent_id) REFERENCES growth_talents(id)
            )
            """,
            # 天赋点数表
            """
            CREATE TABLE IF NOT EXISTS growth_points (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                amount INTEGER NOT NULL,
                source TEXT NOT NULL,
                source_id TEXT DEFAULT '',
                reason TEXT DEFAULT '',
                created_at TEXT DEFAULT (datetime('now'))
            )
            """,
            # 日历打卡表
            """
            CREATE TABLE IF NOT EXISTS growth_calendar (
                date TEXT PRIMARY KEY,
                mood INTEGER DEFAULT 0,
                energy INTEGER DEFAULT 0,
                checked_in INTEGER DEFAULT 0,
                summary TEXT DEFAULT '',
                tags TEXT DEFAULT '[]',
                tide_phase TEXT DEFAULT '小潮',
                created_at TEXT DEFAULT (datetime('now')),
                updated_at TEXT DEFAULT (datetime('now'))
            )
            """,
            # 索引
            "CREATE INDEX IF NOT EXISTS idx_ach_category ON growth_achievements(category)",
            "CREATE INDEX IF NOT EXISTS idx_ach_rarity ON growth_achievements(rarity)",
            "CREATE INDEX IF NOT EXISTS idx_user_ach_unlocked ON growth_user_achievements(unlocked)",
            "CREATE INDEX IF NOT EXISTS idx_talent_branch ON growth_talents(branch)",
            "CREATE INDEX IF NOT EXISTS idx_talent_tree ON growth_talents(tree)",
            "CREATE INDEX IF NOT EXISTS idx_calendar_checked ON growth_calendar(checked_in)",
            "CREATE INDEX IF NOT EXISTS idx_calendar_date ON growth_calendar(date)",
            # 编年史表
            """
            CREATE TABLE IF NOT EXISTS growth_chronicle (
                id TEXT PRIMARY KEY,
                date TEXT NOT NULL,
                title TEXT NOT NULL,
                category TEXT NOT NULL DEFAULT 'main-quest',
                category_text TEXT NOT NULL DEFAULT '主线任务',
                difficulty TEXT NOT NULL DEFAULT '普通',
                content TEXT NOT NULL DEFAULT '',
                tags TEXT NOT NULL DEFAULT '[]',
                has_git INTEGER NOT NULL DEFAULT 0,
                git_commits TEXT NOT NULL DEFAULT '[]',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """,
            "CREATE INDEX IF NOT EXISTS idx_chronicle_date ON growth_chronicle(date)",
            "CREATE INDEX IF NOT EXISTS idx_chronicle_category ON growth_chronicle(category)",
            # 记忆回响表
            """
            CREATE TABLE IF NOT EXISTS growth_memory_echoes (
                id TEXT PRIMARY KEY,
                title TEXT NOT NULL,
                category TEXT NOT NULL DEFAULT 'growth',
                category_text TEXT NOT NULL DEFAULT '成长',
                before_json TEXT NOT NULL DEFAULT '{}',
                after_json TEXT NOT NULL DEFAULT '{}',
                growth TEXT NOT NULL DEFAULT '',
                content TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL
            )
            """,
            "CREATE INDEX IF NOT EXISTS idx_echo_category ON growth_memory_echoes(category)",
            "CREATE INDEX IF NOT EXISTS idx_echo_created_at ON growth_memory_echoes(created_at)",
            # 赛季表
            """
            CREATE TABLE IF NOT EXISTS growth_seasons (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                period TEXT NOT NULL DEFAULT '',
                start_date TEXT NOT NULL,
                end_date TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'locked',
                created_at TEXT NOT NULL
            )
            """,
            # 赛季阶段表
            """
            CREATE TABLE IF NOT EXISTS growth_season_phases (
                id TEXT PRIMARY KEY,
                season_id TEXT NOT NULL,
                name TEXT NOT NULL,
                phase_index INTEGER NOT NULL DEFAULT 0,
                reward TEXT NOT NULL DEFAULT '',
                reward_points INTEGER NOT NULL DEFAULT 0,
                reward_claimed INTEGER NOT NULL DEFAULT 0,
                FOREIGN KEY (season_id) REFERENCES growth_seasons(id) ON DELETE CASCADE
            )
            """,
            "CREATE INDEX IF NOT EXISTS idx_phase_season ON growth_season_phases(season_id)",
            # 赛季任务表
            """
            CREATE TABLE IF NOT EXISTS growth_season_tasks (
                id TEXT PRIMARY KEY,
                season_id TEXT NOT NULL,
                phase_id TEXT NOT NULL,
                title TEXT NOT NULL,
                description TEXT NOT NULL DEFAULT '',
                type TEXT NOT NULL DEFAULT 'seasonal',
                status TEXT NOT NULL DEFAULT 'pending',
                points INTEGER NOT NULL DEFAULT 0,
                completed_at TEXT,
                FOREIGN KEY (season_id) REFERENCES growth_seasons(id) ON DELETE CASCADE,
                FOREIGN KEY (phase_id) REFERENCES growth_season_phases(id) ON DELETE CASCADE
            )
            """,
            "CREATE INDEX IF NOT EXISTS idx_task_season ON growth_season_tasks(season_id)",
            "CREATE INDEX IF NOT EXISTS idx_task_phase ON growth_season_tasks(phase_id)",
            "CREATE INDEX IF NOT EXISTS idx_task_type ON growth_season_tasks(type)",
            "CREATE INDEX IF NOT EXISTS idx_task_status ON growth_season_tasks(status)",
        ]

    def _bootstrap_growth_migration(self) -> bool:
        """
        引导成长系统迁移系统：检测现有数据库状态，初始化版本号

        Returns:
            是否成功引导
        """
        import structlog
        import time
        log = structlog.get_logger(__name__)
        try:
            conn = sqlite3.connect(self._db_path)
            try:
                # 检查核心表是否存在
                cursor = conn.execute(
                    "SELECT name FROM sqlite_master "
                    "WHERE type='table' AND name='growth_achievements'"
                )
                if not cursor.fetchone():
                    return False

                # 检测到已有数据，版本为 v1
                detected_version = 1

                # 初始化版本表和日志表
                migrator = self._get_migrator()
                migrator._ensure_version_table(conn)
                migrator._ensure_migration_log_table(conn)
                migrator._set_version(conn, detected_version)

                # 记录迁移日志
                for v in range(1, detected_version + 1):
                    if v in migrator._migrations:
                        m = migrator._migrations[v]
                        migrator._log_migration(conn, v, m.name, 0.0)

                conn.commit()
                log.info(
                    "migration.bootstrapped",
                    db="growth",
                    db_path=self._db_path,
                    detected_version=detected_version,
                )
                return True
            finally:
                conn.close()
        except Exception as e:
            log.warning("migration.bootstrap_failed", db="growth", error=str(e))
            return False

    def _init_database_with_migration(self) -> None:
        """使用版本化迁移系统初始化数据库"""
        import structlog
        log = structlog.get_logger(__name__)
        migrator = self._get_migrator()

        # 检查迁移系统是否已初始化
        if not migrator.is_initialized():
            # 尝试引导
            bootstrapped = self._bootstrap_growth_migration()
            if not bootstrapped:
                log.debug("migration.new_database", db="growth", db_path=self._db_path)

        # 执行迁移到最新版本
        try:
            result = migrator.migrate()
            if result["status"] == "success" and result["applied"]:
                log.info(
                    "migration.growth_applied",
                    from_version=result["from_version"],
                    to_version=result["to_version"],
                    applied_count=len(result["applied"]),
                )
        except Exception as e:
            log.error("migration.growth_failed", error=str(e))
            # 迁移失败时回退到旧模式
            self._init_database_legacy()

    def _init_database_legacy(self) -> None:
        """旧模式：直接建表 + 插入预置数据（向后兼容）"""
        conn = self._get_connection()
        try:
            self._create_tables(conn)
            self._init_achievements(conn)
            self._init_talents(conn)
            self._init_points(conn)
            self._init_seasons(conn)
            conn.commit()
        finally:
            conn.close()

    # ============================================================
    # 表结构定义
    # ============================================================

    def _create_tables(self, conn: sqlite3.Connection) -> None:
        """创建所有数据表"""
        cursor = conn.cursor()

        # 成就定义表
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS growth_achievements (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                category TEXT NOT NULL,
                rarity TEXT NOT NULL,
                rarity_text TEXT NOT NULL,
                condition TEXT NOT NULL,
                description TEXT NOT NULL,
                point_reward INTEGER DEFAULT 1,
                sort_order INTEGER DEFAULT 0,
                created_at TEXT DEFAULT (datetime('now'))
            )
        """)

        # 用户成就表（解锁状态）
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS growth_user_achievements (
                achievement_id TEXT PRIMARY KEY,
                unlocked INTEGER DEFAULT 0,
                unlock_date TEXT DEFAULT '',
                unlocked_at TEXT DEFAULT '',
                FOREIGN KEY (achievement_id) REFERENCES growth_achievements(id)
            )
        """)

        # 天赋定义表
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS growth_talents (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                branch TEXT NOT NULL,
                tree TEXT NOT NULL,
                description TEXT NOT NULL,
                max_level INTEGER DEFAULT 1,
                parent_id TEXT DEFAULT '',
                children_ids TEXT DEFAULT '[]',
                point_cost INTEGER DEFAULT 1,
                layer INTEGER DEFAULT 1,
                sort_order INTEGER DEFAULT 0,
                created_at TEXT DEFAULT (datetime('now'))
            )
        """)

        # 用户天赋状态表
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS growth_user_talents (
                talent_id TEXT PRIMARY KEY,
                level INTEGER DEFAULT 0,
                status TEXT DEFAULT 'locked',
                updated_at TEXT DEFAULT (datetime('now')),
                FOREIGN KEY (talent_id) REFERENCES growth_talents(id)
            )
        """)

        # 天赋点数表
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS growth_points (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                amount INTEGER NOT NULL,
                source TEXT NOT NULL,
                source_id TEXT DEFAULT '',
                reason TEXT DEFAULT '',
                created_at TEXT DEFAULT (datetime('now'))
            )
        """)

        # 日历打卡表
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS growth_calendar (
                date TEXT PRIMARY KEY,
                mood INTEGER DEFAULT 0,
                energy INTEGER DEFAULT 0,
                checked_in INTEGER DEFAULT 0,
                summary TEXT DEFAULT '',
                tags TEXT DEFAULT '[]',
                tide_phase TEXT DEFAULT '小潮',
                created_at TEXT DEFAULT (datetime('now')),
                updated_at TEXT DEFAULT (datetime('now'))
            )
        """)

        # 索引
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_ach_category ON growth_achievements(category)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_ach_rarity ON growth_achievements(rarity)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_user_ach_unlocked ON growth_user_achievements(unlocked)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_talent_branch ON growth_talents(branch)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_talent_tree ON growth_talents(tree)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_calendar_checked ON growth_calendar(checked_in)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_calendar_date ON growth_calendar(date)")

        # ========================================================
        # 编年史表
        # ========================================================
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS growth_chronicle (
                id TEXT PRIMARY KEY,
                date TEXT NOT NULL,
                title TEXT NOT NULL,
                category TEXT NOT NULL DEFAULT 'main-quest',
                category_text TEXT NOT NULL DEFAULT '主线任务',
                difficulty TEXT NOT NULL DEFAULT '普通',
                content TEXT NOT NULL DEFAULT '',
                tags TEXT NOT NULL DEFAULT '[]',
                has_git INTEGER NOT NULL DEFAULT 0,
                git_commits TEXT NOT NULL DEFAULT '[]',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
        """)
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_chronicle_date ON growth_chronicle(date)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_chronicle_category ON growth_chronicle(category)")

        # ========================================================
        # 记忆回响表
        # ========================================================
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS growth_memory_echoes (
                id TEXT PRIMARY KEY,
                title TEXT NOT NULL,
                category TEXT NOT NULL DEFAULT 'growth',
                category_text TEXT NOT NULL DEFAULT '成长',
                before_json TEXT NOT NULL DEFAULT '{}',
                after_json TEXT NOT NULL DEFAULT '{}',
                growth TEXT NOT NULL DEFAULT '',
                content TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL
            )
        """)
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_echo_category ON growth_memory_echoes(category)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_echo_created_at ON growth_memory_echoes(created_at)")

        # ========================================================
        # 赛季表
        # ========================================================
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS growth_seasons (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                period TEXT NOT NULL DEFAULT '',
                start_date TEXT NOT NULL,
                end_date TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'locked',
                created_at TEXT NOT NULL
            )
        """)

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS growth_season_phases (
                id TEXT PRIMARY KEY,
                season_id TEXT NOT NULL,
                name TEXT NOT NULL,
                phase_index INTEGER NOT NULL DEFAULT 0,
                reward TEXT NOT NULL DEFAULT '',
                reward_points INTEGER NOT NULL DEFAULT 0,
                reward_claimed INTEGER NOT NULL DEFAULT 0,
                FOREIGN KEY (season_id) REFERENCES growth_seasons(id) ON DELETE CASCADE
            )
        """)
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_phase_season ON growth_season_phases(season_id)")

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS growth_season_tasks (
                id TEXT PRIMARY KEY,
                season_id TEXT NOT NULL,
                phase_id TEXT NOT NULL,
                title TEXT NOT NULL,
                description TEXT NOT NULL DEFAULT '',
                type TEXT NOT NULL DEFAULT 'seasonal',
                status TEXT NOT NULL DEFAULT 'pending',
                points INTEGER NOT NULL DEFAULT 0,
                completed_at TEXT,
                FOREIGN KEY (season_id) REFERENCES growth_seasons(id) ON DELETE CASCADE,
                FOREIGN KEY (phase_id) REFERENCES growth_season_phases(id) ON DELETE CASCADE
            )
        """)
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_task_season ON growth_season_tasks(season_id)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_task_phase ON growth_season_tasks(phase_id)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_task_type ON growth_season_tasks(type)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_task_status ON growth_season_tasks(status)")

    # ============================================================
    # 预置数据初始化
    # ============================================================

    def _init_achievements(self, conn: sqlite3.Connection) -> None:
        """初始化预置成就数据（16个，4类 × 4级稀有度）"""
        cursor = conn.cursor()

        # 检查是否已有数据
        cursor.execute("SELECT COUNT(*) as cnt FROM growth_achievements")
        row = cursor.fetchone()
        if row["cnt"] > 0:
            return  # 已有数据，跳过初始化

        achievements = [
            # 成长类 (growth)
            ("ach_growth_1", "初识记忆", "growth", "common", "普通",
             "记录第一条记忆", "开启记忆之旅，种下第一颗时光的种子。", 1, 1),
            ("ach_growth_2", "时光旅人", "growth", "rare", "稀有",
             "累计记录 10 条记忆", "在时光中漫步，收藏十段珍贵回忆。", 2, 2),
            ("ach_growth_3", "深海探索者", "growth", "epic", "史诗",
             "累计记录 50 条记忆", "潜入记忆深海，发掘五十颗闪耀的珍珠。", 3, 3),
            ("ach_growth_4", "万象归一者", "growth", "legendary", "传奇",
             "累计记录 200 条记忆", "记忆如海纳百川，万物归一于心间。", 5, 4),

            # 技能类 (skill)
            ("ach_skill_1", "灵感火花", "skill", "common", "普通",
             "使用一次搜索功能", "点亮第一缕灵感的火花。", 1, 1),
            ("ach_skill_2", "织梦者", "skill", "rare", "稀有",
             "累计搜索 20 次", "在记忆之网中编织梦想的形状。", 2, 2),
            ("ach_skill_3", "炼金术士", "skill", "epic", "史诗",
             "累计搜索 100 次", "将碎片记忆炼化为智慧的黄金。", 3, 3),
            ("ach_skill_4", "创世之笔", "skill", "legendary", "传奇",
             "累计搜索 500 次", "以记忆为墨，书写属于你的创世篇章。", 5, 4),

            # 社交类 (social)
            ("ach_social_1", "初次相遇", "social", "common", "普通",
             "与第一位伙伴建立连接", "每段旅程都始于一次相遇。", 1, 1),
            ("ach_social_2", "温暖陪伴", "social", "rare", "稀有",
             "累计互动 30 次", "温暖的陪伴是最长情的告白。", 2, 2),
            ("ach_social_3", "心灵共鸣", "social", "epic", "史诗",
             "累计互动 100 次", "两颗心在记忆的回响中产生共鸣。", 3, 3),
            ("ach_social_4", "灵魂挚友", "social", "legendary", "传奇",
             "累计互动 365 次", "跨越时空的灵魂挚友，此生不渝。", 5, 4),

            # 特殊类 (special)
            ("ach_special_1", "第一天", "special", "common", "普通",
             "完成第一天打卡", "第一天，一切的开始。", 1, 1),
            ("ach_special_2", "连续七天", "special", "rare", "稀有",
             "连续打卡 7 天", "一周的坚持，习惯的力量。", 2, 2),
            ("ach_special_3", "赛季先锋", "special", "epic", "史诗",
             "连续打卡 30 天", "一个赛季的先锋，引领潮流。", 3, 3),
            ("ach_special_4", "传奇守护者", "special", "legendary", "传奇",
             "连续打卡 100 天", "百日守护，传奇之名当之无愧。", 5, 4),
        ]

        for ach in achievements:
            cursor.execute("""
                INSERT INTO growth_achievements
                (id, name, category, rarity, rarity_text, condition, description, point_reward, sort_order)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, ach)

    def _init_talents(self, conn: sqlite3.Connection) -> None:
        """初始化预置天赋树数据（4分支 × 8节点 = 32节点）"""
        cursor = conn.cursor()

        # 检查是否已有数据
        cursor.execute("SELECT COUNT(*) as cnt FROM growth_talents")
        row = cursor.fetchone()
        if row["cnt"] > 0:
            return  # 已有数据，跳过初始化

        # 定义四个分支的天赋树
        talent_trees = {
            # 心智分支 (mind)
            "mind": [
                # Layer 1 (4个)
                ("tal_mind_1_1", "逻辑萌芽", "mind", "mind",
                 "提升逻辑推理的基础能力，让思考更有条理。",
                 3, "", '["tal_mind_2_1"]', 1, 1, 1),
                ("tal_mind_1_2", "归纳直觉", "mind", "mind",
                 "从具体事例中提炼普遍规律的直觉能力。",
                 3, "", '["tal_mind_2_1"]', 1, 1, 2),
                ("tal_mind_1_3", "演绎锋芒", "mind", "mind",
                 "从一般原则推导具体结论的锐利思维。",
                 3, "", '["tal_mind_2_2"]', 1, 1, 3),
                ("tal_mind_1_4", "假设检验", "mind", "mind",
                 "提出假设并验证的科学思维方法。",
                 3, "", '["tal_mind_2_2"]', 1, 1, 4),
                # Layer 2 (3个)
                ("tal_mind_2_1", "因果透镜", "mind", "mind",
                 "看穿事物表象，洞察因果关系的透镜。",
                 3, "tal_mind_1_1", '["tal_mind_3_1"]', 2, 2, 1),
                ("tal_mind_2_2", "悖论耐受", "mind", "mind",
                 "在矛盾与悖论中保持思考的韧性。",
                 3, "tal_mind_1_3", '["tal_mind_3_1"]', 2, 2, 2),
                ("tal_mind_2_3", "系统思维", "mind", "mind",
                 "将事物视为整体系统的宏观视角。",
                 3, "tal_mind_1_2", '["tal_mind_3_1"]', 2, 2, 3),
                # Layer 3 (1个终极)
                ("tal_mind_3_1", "奥卡姆剃刀", "mind", "mind",
                 "如剃刀般锋利，剔除冗余，直指本质。",
                 5, "tal_mind_2_1", "[]", 3, 3, 1),
            ],
            # 稳态分支 (emotion)
            "emotion": [
                # Layer 1
                ("tal_emotion_1_1", "情绪感知", "emotion", "emotion",
                 "敏锐觉察自身情绪变化的能力。",
                 3, "", '["tal_emotion_2_1"]', 1, 1, 1),
                ("tal_emotion_1_2", "呼吸锚定", "emotion", "emotion",
                 "以呼吸为锚，在情绪风暴中保持稳定。",
                 3, "", '["tal_emotion_2_1"]', 1, 1, 2),
                ("tal_emotion_1_3", "认知重构", "emotion", "emotion",
                 "调整认知框架，转化情绪体验的技巧。",
                 3, "", '["tal_emotion_2_2"]', 1, 1, 3),
                ("tal_emotion_1_4", "边界守护", "emotion", "emotion",
                 "建立健康的情绪边界，保护内心安宁。",
                 3, "", '["tal_emotion_2_2"]', 1, 1, 4),
                # Layer 2
                ("tal_emotion_2_1", "压力转化", "emotion", "emotion",
                 "将压力转化为前进动力的炼金术。",
                 3, "tal_emotion_1_1", '["tal_emotion_3_1"]', 2, 2, 1),
                ("tal_emotion_2_2", "弹性心智", "emotion", "emotion",
                 "如弹簧般在挫折后迅速回弹的韧性。",
                 3, "tal_emotion_1_3", '["tal_emotion_3_1"]', 2, 2, 2),
                ("tal_emotion_2_3", "宁静致远", "emotion", "emotion",
                 "内心宁静方能行稳致远的智慧。",
                 3, "tal_emotion_1_2", '["tal_emotion_3_1"]', 2, 2, 3),
                # Layer 3
                ("tal_emotion_3_1", "不动明王", "emotion", "emotion",
                 "八风不动，心如磐石的终极境界。",
                 5, "tal_emotion_2_1", "[]", 3, 3, 1),
            ],
            # 创造分支 (creativity)
            "creativity": [
                # Layer 1
                ("tal_creativity_1_1", "灵感捕捉", "creativity", "creativity",
                 "在灵感闪现的瞬间将其捕获的技艺。",
                 3, "", '["tal_creativity_2_1"]', 1, 1, 1),
                ("tal_creativity_1_2", "联想编织", "creativity", "creativity",
                 "将看似无关的事物编织成新创意的能力。",
                 3, "", '["tal_creativity_2_1"]', 1, 1, 2),
                ("tal_creativity_1_3", "跨界杂交", "creativity", "creativity",
                 "跨越领域边界，孕育全新可能的方法。",
                 3, "", '["tal_creativity_2_2"]', 1, 1, 3),
                ("tal_creativity_1_4", "原型速构", "creativity", "creativity",
                 "快速构建原型验证想法的行动力。",
                 3, "", '["tal_creativity_2_2"]', 1, 1, 4),
                # Layer 2
                ("tal_creativity_2_1", "美学直觉", "creativity", "creativity",
                 "对美与和谐的敏锐直觉感知。",
                 3, "tal_creativity_1_1", '["tal_creativity_3_1"]', 2, 2, 1),
                ("tal_creativity_2_2", "逆向工程", "creativity", "creativity",
                 "从结果反推过程的逆向思维艺术。",
                 3, "tal_creativity_1_3", '["tal_creativity_3_1"]', 2, 2, 2),
                ("tal_creativity_2_3", "实验精神", "creativity", "creativity",
                 "不惧失败，勇于尝试的探索精神。",
                 3, "tal_creativity_1_2", '["tal_creativity_3_1"]', 2, 2, 3),
                # Layer 3
                ("tal_creativity_3_1", "造物主", "creativity", "creativity",
                 "从无到有创造万物的终极创造力。",
                 5, "tal_creativity_2_1", "[]", 3, 3, 1),
            ],
            # 阅历分支 (experience)
            "experience": [
                # Layer 1
                ("tal_experience_1_1", "时间沉淀", "experience", "experience",
                 "让经历在时间中沉淀为智慧。",
                 3, "", '["tal_experience_2_1"]', 1, 1, 1),
                ("tal_experience_1_2", "模式识别", "experience", "experience",
                 "从海量经验中识别重复模式的慧眼。",
                 3, "", '["tal_experience_2_1"]', 1, 1, 2),
                ("tal_experience_1_3", "教训萃取", "experience", "experience",
                 "从失败中萃取出珍贵教训的能力。",
                 3, "", '["tal_experience_2_2"]', 1, 1, 3),
                ("tal_experience_1_4", "情境复现", "experience", "experience",
                 "在记忆中精准复现过往情境的能力。",
                 3, "", '["tal_experience_2_2"]', 1, 1, 4),
                # Layer 2
                ("tal_experience_2_1", "历史透镜", "experience", "experience",
                 "以史为鉴，洞察当下的透镜。",
                 3, "tal_experience_1_1", '["tal_experience_3_1"]', 2, 2, 1),
                ("tal_experience_2_2", "相似联想", "experience", "experience",
                 "由相似经历触发洞见的联想能力。",
                 3, "tal_experience_1_3", '["tal_experience_3_1"]', 2, 2, 2),
                ("tal_experience_2_3", "预见微光", "experience", "experience",
                 "从经验中窥见未来趋势的微光。",
                 3, "tal_experience_1_2", '["tal_experience_3_1"]', 2, 2, 3),
                # Layer 3
                ("tal_experience_3_1", "万象归一", "experience", "experience",
                 "万般经历终归一，千江有水千江月。",
                 5, "tal_experience_2_1", "[]", 3, 3, 1),
            ],
        }

        for branch, talents in talent_trees.items():
            for tal in talents:
                cursor.execute("""
                    INSERT INTO growth_talents
                    (id, name, branch, tree, description, max_level, parent_id,
                     children_ids, point_cost, layer, sort_order)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, tal)

    def _init_points(self, conn: sqlite3.Connection) -> None:
        """初始化天赋点数（初始赠送 5 点作为新手礼包）"""
        cursor = conn.cursor()

        cursor.execute("SELECT COUNT(*) as cnt FROM growth_points")
        row = cursor.fetchone()
        if row["cnt"] > 0:
            return

        cursor.execute("""
            INSERT INTO growth_points (amount, source, source_id, reason)
            VALUES (?, ?, ?, ?)
        """, (5, "initial", "init_001", "新手礼包 - 初始天赋点数"))

    # ============================================================
    # 通用数据库操作
    # ============================================================

    def execute(self, sql: str, params: tuple = ()) -> int:
        """执行写操作，返回受影响行数"""
        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute(sql, params)
            conn.commit()
            return cursor.rowcount
        finally:
            conn.close()

    def query_one(self, sql: str, params: tuple = ()) -> Optional[Dict]:
        """查询单行数据"""
        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute(sql, params)
            row = cursor.fetchone()
            return dict(row) if row else None
        finally:
            conn.close()

    def query_all(self, sql: str, params: tuple = ()) -> List[Dict]:
        """查询多行数据"""
        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute(sql, params)
            rows = cursor.fetchall()
            return [dict(row) for row in rows]
        finally:
            conn.close()

    @property
    def db_path(self) -> str:
        """数据库文件路径"""
        return self._db_path

    # ============================================================
    # 赛季预置数据
    # ============================================================

    def _init_seasons(self, conn: sqlite3.Connection) -> None:
        """初始化预置赛季数据（S1 历史赛季 + S2 当前赛季）"""
        from datetime import datetime, timedelta

        cursor = conn.cursor()

        # 检查是否已有数据
        cursor.execute("SELECT COUNT(*) as cnt FROM growth_seasons")
        row = cursor.fetchone()
        if row["cnt"] > 0:
            return  # 已有数据，跳过初始化

        now = datetime.now()

        # ===== S1 启程之春（历史赛季，已完成） =====
        s1_start = (now - timedelta(days=180)).strftime("%Y-%m-%d")
        s1_end = (now - timedelta(days=90)).strftime("%Y-%m-%d")
        s1_id = "s1"

        cursor.execute(
            """
            INSERT INTO growth_seasons (id, name, period, start_date, end_date, status, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (s1_id, "S1 启程之春", "2026年Q1", s1_start, s1_end, "completed", now.isoformat()),
        )

        # S1 阶段
        s1_phases = self._build_season_phases_data(s1_id, completed=True)
        for phase in s1_phases:
            cursor.execute(
                """
                INSERT INTO growth_season_phases
                (id, season_id, name, phase_index, reward, reward_points, reward_claimed)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (phase["id"], phase["season_id"], phase["name"], phase["phase_index"],
                 phase["reward"], phase["reward_points"], phase["reward_claimed"]),
            )

        # S1 任务
        s1_tasks = self._build_season_tasks_data(s1_id, s1_phases, completed=True)
        completed_at = (now - timedelta(days=100)).isoformat()
        for task in s1_tasks:
            cursor.execute(
                """
                INSERT INTO growth_season_tasks
                (id, season_id, phase_id, title, description, type, status, points, completed_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (task["id"], task["season_id"], task["phase_id"], task["title"],
                 task["description"], task["type"], task["status"], task["points"], completed_at),
            )

        # ===== S2 觉醒之夏（当前进行中） =====
        s2_start = (now - timedelta(days=30)).strftime("%Y-%m-%d")
        s2_end = (now + timedelta(days=60)).strftime("%Y-%m-%d")
        s2_id = "s2"

        cursor.execute(
            """
            INSERT INTO growth_seasons (id, name, period, start_date, end_date, status, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (s2_id, "S2 觉醒之夏", "2026年Q2-Q3", s2_start, s2_end, "active", now.isoformat()),
        )

        # S2 阶段
        s2_phases = self._build_season_phases_data(s2_id, completed=False)
        for phase in s2_phases:
            cursor.execute(
                """
                INSERT INTO growth_season_phases
                (id, season_id, name, phase_index, reward, reward_points, reward_claimed)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (phase["id"], phase["season_id"], phase["name"], phase["phase_index"],
                 phase["reward"], phase["reward_points"], phase["reward_claimed"]),
            )

        # S2 任务
        s2_tasks = self._build_season_tasks_data(s2_id, s2_phases, completed=False)
        for task in s2_tasks:
            cursor.execute(
                """
                INSERT INTO growth_season_tasks
                (id, season_id, phase_id, title, description, type, status, points, completed_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (task["id"], task["season_id"], task["phase_id"], task["title"],
                 task["description"], task["type"], task["status"], task["points"], None),
            )

    def _build_season_phases_data(self, season_id: str, completed: bool = False) -> List[Dict[str, Any]]:
        """
        构建赛季的6个阶段数据。

        Args:
            season_id: 赛季ID
            completed: 是否已完成

        Returns:
            阶段数据列表
        """
        phase_defs = [
            {"name": "启程 · 建立基线", "reward": "启程徽章", "reward_points": 5},
            {"name": "深耕 · 聚焦主题", "reward": "深耕勋章", "reward_points": 10},
            {"name": "突破 · 技能习得", "reward": "突破之证", "reward_points": 15},
            {"name": "整合 · 体系构建", "reward": "整合桂冠", "reward_points": 20},
            {"name": "验证 · 实践检验", "reward": "验证印记", "reward_points": 25},
            {"name": "收官 · 沉淀归档", "reward": "赛季荣耀", "reward_points": 30},
        ]

        phases = []
        for i, pdef in enumerate(phase_defs):
            phase_id = f"{season_id}_phase_{i+1}"
            phases.append({
                "id": phase_id,
                "season_id": season_id,
                "name": pdef["name"],
                "phase_index": i + 1,
                "reward": pdef["reward"],
                "reward_points": pdef["reward_points"],
                "reward_claimed": 1 if completed else 0,
            })

        return phases

    def _build_season_tasks_data(self, season_id: str, phases: List[Dict], completed: bool = False) -> List[Dict[str, Any]]:
        """
        构建赛季任务数据，每个阶段 3-5 个任务。

        Args:
            season_id: 赛季ID
            phases: 阶段列表
            completed: 是否全部标记为已完成

        Returns:
            任务数据列表
        """
        task_templates = {
            1: [
                {"title": "完成个人基线测评", "desc": "梳理当前技能树与知识体系现状", "type": "seasonal", "points": 3},
                {"title": "设定赛季核心目标", "desc": "明确本赛季想要达成的3个核心目标", "type": "seasonal", "points": 3},
                {"title": "建立每日记录习惯", "desc": "开始使用潮汐记忆记录每日所思所得", "type": "daily", "points": 1},
                {"title": "完成首次记忆归档", "desc": "将第一条重要记忆存入深水层", "type": "seasonal", "points": 2},
            ],
            2: [
                {"title": "选定深耕主题", "desc": "从核心目标中拆解出本周聚焦主题", "type": "seasonal", "points": 3},
                {"title": "输入10份学习材料", "desc": "阅读/观看10份与主题相关的高质量内容", "type": "weekly", "points": 5},
                {"title": "输出3篇学习笔记", "desc": "将输入转化为自己的语言，沉淀为笔记", "type": "weekly", "points": 4},
                {"title": "建立主题知识图谱", "desc": "用可视化方式梳理主题知识点关联", "type": "seasonal", "points": 5},
            ],
            3: [
                {"title": "掌握核心技能点", "desc": "通过刻意练习掌握一项关键技能", "type": "seasonal", "points": 8},
                {"title": "完成第一个实践项目", "desc": "将所学应用到实际项目中，完成MVP", "type": "seasonal", "points": 10},
                {"title": "寻求外部反馈", "desc": "向他人展示成果并收集改进意见", "type": "weekly", "points": 3},
                {"title": "复盘技能习得路径", "desc": "总结自己是如何学会这项技能的", "type": "seasonal", "points": 4},
            ],
            4: [
                {"title": "构建知识体系框架", "desc": "将零散的知识点整合成体系化结构", "type": "seasonal", "points": 8},
                {"title": "输出一份完整教程", "desc": "用教别人的方式检验自己的理解深度", "type": "seasonal", "points": 10},
                {"title": "建立复用模板库", "desc": "将可复用的流程、方法整理成模板", "type": "weekly", "points": 5},
                {"title": "跨领域知识联结", "desc": "找到本主题与其他领域的关联点", "type": "seasonal", "points": 6},
                {"title": "中期赛季复盘", "desc": "回顾赛季过半的收获与不足", "type": "seasonal", "points": 3},
            ],
            5: [
                {"title": "接受真实场景挑战", "desc": "在真实项目/场景中应用所学体系", "type": "seasonal", "points": 12},
                {"title": "完成一次公开分享", "desc": "向团队或社区分享你的成果与方法", "type": "seasonal", "points": 8},
                {"title": "收集并处理反馈", "desc": "系统性收集反馈并迭代改进", "type": "weekly", "points": 5},
                {"title": "压力测试知识体系", "desc": "用难题检验体系的完备性", "type": "seasonal", "points": 6},
            ],
            6: [
                {"title": "赛季成果总览", "desc": "整理本赛季所有产出与成就", "type": "seasonal", "points": 5},
                {"title": "撰写赛季总结报告", "desc": "系统性复盘整个赛季的成长轨迹", "type": "seasonal", "points": 8},
                {"title": "知识沉淀归档", "desc": "将赛季核心成果存入长期记忆库", "type": "seasonal", "points": 5},
                {"title": "规划下一赛季", "desc": "基于本赛季经验制定下赛季目标", "type": "seasonal", "points": 3},
            ],
        }

        tasks = []
        for phase in phases:
            idx = phase["phase_index"]
            templates = task_templates.get(idx, [])
            for j, t in enumerate(templates):
                task_id = f"{phase['id']}_task_{j+1}"
                tasks.append({
                    "id": task_id,
                    "season_id": season_id,
                    "phase_id": phase["id"],
                    "title": t["title"],
                    "description": t["desc"],
                    "type": t["type"],
                    "status": "completed" if completed else "pending",
                    "points": t["points"],
                })

        return tasks


# ============================================================
# 模块级兼容函数（供 __init__.py 导出使用）
# ============================================================

def get_growth_db() -> GrowthDatabase:
    """
    获取成长模块数据库实例（单例）。

    兼容函数，内部委托给 GrowthDatabase.get_instance()。

    Returns:
        GrowthDatabase 实例
    """
    return GrowthDatabase.get_instance()


def init_growth_db() -> GrowthDatabase:
    """
    初始化成长模块数据库。

    触发数据库建表和预置数据插入。

    Returns:
        GrowthDatabase 实例
    """
    return GrowthDatabase.get_instance()


# ============================================================
# JSON 工具函数
# ============================================================

def json_to_list(value: str) -> List[Any]:
    """将 JSON 字符串转为列表，失败返回空列表"""
    try:
        result = json.loads(value)
        return result if isinstance(result, list) else []
    except (json.JSONDecodeError, TypeError):
        return []


def list_to_json(value: List[Any]) -> str:
    """将列表转为 JSON 字符串"""
    return json.dumps(value, ensure_ascii=False)


def json_to_dict(value: str) -> Dict[str, Any]:
    """将 JSON 字符串转为字典，失败返回空字典"""
    try:
        result = json.loads(value)
        return result if isinstance(result, dict) else {}
    except (json.JSONDecodeError, TypeError):
        return {}


def dict_to_json(value: Dict[str, Any]) -> str:
    """将字典转为 JSON 字符串"""
    return json.dumps(value, ensure_ascii=False)


# vim: set et ts=4 sw=4:
