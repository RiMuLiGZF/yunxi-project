from __future__ import annotations

"""知识卡片/闪卡技能."""

import os
import sqlite3
import uuid
from datetime import datetime, timedelta
from typing import Any

import structlog

from skill_cluster.interfaces import (
    ISkill,
    SkillInvokeRequest,
    SkillInvokeResult,
    SkillManifest,
)

logger = structlog.get_logger()


class FlashcardSkill(ISkill):
    """知识卡片技能，支持闪卡创建、复习、卡组管理、学习统计."""

    def __init__(self) -> None:
        manifest = SkillManifest(
            skill_id="skill.flashcard",
            name="知识卡片",
            version="1.0.0",
            description="管理知识闪卡，支持间隔重复复习、卡组管理、学习统计",
            author="yunxi",
            tags=["flashcard", "learning", "memory"],
            capabilities=["create_card", "list_cards", "review", "stats", "decks", "search"],
            permissions=["read_file", "write"],
            entrypoint="FlashcardSkill",
        )
        super().__init__(manifest)
        self._config: dict[str, Any] = {}
        self._db_path = os.path.expanduser("~/.yunxi/data/flashcard.db")
        os.makedirs(os.path.dirname(self._db_path), exist_ok=True)
        self._init_db()

    def _init_db(self) -> None:
        """初始化数据库表结构."""
        with sqlite3.connect(self._db_path) as conn:
            # 卡组表
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS decks (
                    deck_id TEXT PRIMARY KEY,
                    name TEXT,
                    description TEXT,
                    card_count INTEGER DEFAULT 0,
                    created_at TEXT
                )
                """
            )
            # 卡片表
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS cards (
                    card_id TEXT PRIMARY KEY,
                    deck_id TEXT,
                    front TEXT,
                    back TEXT,
                    tags TEXT,
                    difficulty REAL DEFAULT 0.5,
                    review_count INTEGER DEFAULT 0,
                    last_reviewed TEXT,
                    next_review TEXT,
                    created_at TEXT
                )
                """
            )
            conn.commit()

    async def invoke(self, request: SkillInvokeRequest) -> SkillInvokeResult:
        """技能调用分发入口."""
        action = request.action
        params = request.params
        start = __import__("time").perf_counter()

        try:
            if action == "create_card":
                data = self._create_card(params)
            elif action == "list_cards":
                data = self._list_cards(params)
            elif action == "review":
                data = self._review(params)
            elif action == "stats":
                data = self._stats(params)
            elif action == "decks":
                data = self._decks(params)
            elif action == "search":
                data = self._search(params)
            else:
                return self._error(request, f"Unknown action: {action}", start)

            latency = (__import__("time").perf_counter() - start) * 1000
            return SkillInvokeResult(
                skill_id=self.manifest.skill_id,
                action=action,
                status="success",
                data=data,
                latency_ms=latency,
                trace_id=request.trace_id,
            )
        except Exception as e:
            return self._error(request, str(e), start)

    # ------------------------------ 动作：创建卡片 ------------------------------

    def _create_card(self, params: dict[str, Any]) -> dict[str, Any]:
        """创建一张新卡片.

        Args:
            params:
                - deck_id: 卡组 ID（可选，默认使用 default 卡组）
                - front: 卡片正面内容
                - back: 卡片背面内容
                - tags: 标签列表（可选）
                - difficulty: 初始难度 0-1（可选，默认 0.5）

        Returns:
            创建结果及卡片信息
        """
        card_id = str(uuid.uuid4())
        deck_id = params.get("deck_id", "default")
        front = params.get("front", "")
        back = params.get("back", "")
        tags_list = params.get("tags", [])
        tags = ",".join(tags_list) if isinstance(tags_list, list) else str(tags_list)
        difficulty = float(params.get("difficulty", 0.5))
        now = datetime.now().isoformat()

        # 如果卡组不存在则自动创建默认卡组
        self._ensure_deck_exists(deck_id)

        with sqlite3.connect(self._db_path) as conn:
            conn.execute(
                """
                INSERT INTO cards (card_id, deck_id, front, back, tags, difficulty,
                                   review_count, last_reviewed, next_review, created_at)
                VALUES (?, ?, ?, ?, ?, ?, 0, NULL, ?, ?)
                """,
                (card_id, deck_id, front, back, tags, difficulty, now, now),
            )
            # 更新卡组卡片计数
            conn.execute(
                "UPDATE decks SET card_count = card_count + 1 WHERE deck_id = ?",
                (deck_id,),
            )
            conn.commit()

        return {"card_id": card_id, "created": True, "deck_id": deck_id}

    # ------------------------------ 动作：卡片列表 ------------------------------

    def _list_cards(self, params: dict[str, Any]) -> dict[str, Any]:
        """获取卡片列表，支持按卡组和标签筛选.

        Args:
            params:
                - deck_id: 卡组 ID（可选）
                - tag: 标签筛选（可选）
                - limit: 返回数量限制（可选，默认 50）
                - offset: 偏移量（可选，默认 0）

        Returns:
            卡片列表及总数
        """
        deck_id = params.get("deck_id")
        tag = params.get("tag")
        limit = int(params.get("limit", 50))
        offset = int(params.get("offset", 0))

        query = "SELECT card_id, deck_id, front, back, tags, difficulty, review_count, last_reviewed, next_review, created_at FROM cards WHERE 1=1"
        count_query = "SELECT COUNT(*) FROM cards WHERE 1=1"
        args: list[Any] = []
        count_args: list[Any] = []

        if deck_id:
            query += " AND deck_id = ?"
            count_query += " AND deck_id = ?"
            args.append(deck_id)
            count_args.append(deck_id)

        if tag:
            query += " AND tags LIKE ?"
            count_query += " AND tags LIKE ?"
            like_tag = f"%{tag}%"
            args.append(like_tag)
            count_args.append(like_tag)

        query += " ORDER BY created_at DESC LIMIT ? OFFSET ?"
        args.extend([limit, offset])

        with sqlite3.connect(self._db_path) as conn:
            rows = conn.execute(query, args).fetchall()
            total = conn.execute(count_query, count_args).fetchone()[0]

        cards = [
            {
                "card_id": r[0],
                "deck_id": r[1],
                "front": r[2],
                "back": r[3],
                "tags": r[4].split(",") if r[4] else [],
                "difficulty": r[5],
                "review_count": r[6],
                "last_reviewed": r[7],
                "next_review": r[8],
                "created_at": r[9],
            }
            for r in rows
        ]

        return {"cards": cards, "total": total, "limit": limit, "offset": offset}

    # ------------------------------ 动作：复习 ------------------------------

    def _review(self, params: dict[str, Any]) -> dict[str, Any]:
        """获取待复习卡片（基于简化版间隔重复算法）.

        简化算法：按难度和上次复习时间排序，优先返回难度高、久未复习的卡片。
        同时支持提交复习结果，更新卡片难度和下次复习时间。

        Args:
            params:
                - mode: "fetch" 获取待复习卡片 / "submit" 提交复习结果
                - deck_id: 卡组 ID（可选）
                - limit: 获取数量（可选，默认 20）
                - card_id: 提交时的卡片 ID
                - quality: 复习质量 0-5（0=完全忘记，5=完美回忆）

        Returns:
            待复习卡片列表 或 更新后的卡片信息
        """
        mode = params.get("mode", "fetch")

        if mode == "submit":
            return self._submit_review(params)

        # fetch 模式：获取待复习卡片
        deck_id = params.get("deck_id")
        limit = int(params.get("limit", 20))
        now = datetime.now().isoformat()

        query = """
            SELECT card_id, deck_id, front, back, tags, difficulty, review_count,
                   last_reviewed, next_review, created_at
            FROM cards
            WHERE next_review <= ?
        """
        args: list[Any] = [now]

        if deck_id:
            query += " AND deck_id = ?"
            args.append(deck_id)

        # 简化版间隔重复排序：按难度降序 + 上次复习时间升序
        query += " ORDER BY difficulty DESC, last_reviewed ASC LIMIT ?"
        args.append(limit)

        with sqlite3.connect(self._db_path) as conn:
            rows = conn.execute(query, args).fetchall()

        cards = [
            {
                "card_id": r[0],
                "deck_id": r[1],
                "front": r[2],
                "back": r[3],
                "tags": r[4].split(",") if r[4] else [],
                "difficulty": r[5],
                "review_count": r[6],
                "last_reviewed": r[7],
                "next_review": r[8],
                "created_at": r[9],
            }
            for r in rows
        ]

        return {"cards": cards, "count": len(cards)}

    def _submit_review(self, params: dict[str, Any]) -> dict[str, Any]:
        """提交复习结果，更新卡片难度和下次复习时间.

        使用简化版 SM-2 算法：
        - 难度根据复习质量调整
        - 下次复习间隔基于难度计算
        """
        card_id = params.get("card_id", "")
        quality = int(params.get("quality", 3))  # 0-5
        quality = max(0, min(5, quality))
        now = datetime.now()

        with sqlite3.connect(self._db_path) as conn:
            row = conn.execute(
                "SELECT difficulty, review_count FROM cards WHERE card_id = ?",
                (card_id,),
            ).fetchone()

            if not row:
                raise ValueError(f"Card not found: {card_id}")

            old_difficulty = row[0]
            review_count = row[1] + 1

            # 简化版难度调整：质量越高难度越低
            # 难度范围 0-1，0=最简单，1=最难
            difficulty_delta = (2.5 - quality) * 0.1
            new_difficulty = max(0.0, min(1.0, old_difficulty + difficulty_delta))

            # 简化间隔计算：基于难度和复习次数
            # 难度越高，间隔越短；复习次数越多，间隔越长
            base_interval = 1 + review_count * 0.5
            interval_days = max(1, int(base_interval * (1 - new_difficulty * 0.7)))
            next_review = now + timedelta(days=interval_days)

            conn.execute(
                """
                UPDATE cards SET difficulty = ?, review_count = ?,
                       last_reviewed = ?, next_review = ?
                WHERE card_id = ?
                """,
                (new_difficulty, review_count, now.isoformat(), next_review.isoformat(), card_id),
            )
            conn.commit()

        return {
            "card_id": card_id,
            "reviewed": True,
            "new_difficulty": new_difficulty,
            "review_count": review_count,
            "next_review": next_review.isoformat(),
            "interval_days": interval_days,
        }

    # ------------------------------ 动作：学习统计 ------------------------------

    def _stats(self, params: dict[str, Any]) -> dict[str, Any]:
        """获取学习统计数据.

        Args:
            params:
                - deck_id: 卡组 ID（可选，不传则统计全部）

        Returns:
            结构化统计数据
        """
        deck_id = params.get("deck_id")
        now = datetime.now()
        today_start = now.replace(hour=0, minute=0, second=0, microsecond=0).isoformat()
        today_end = (now.replace(hour=23, minute=59, second=59) + timedelta(microseconds=999999)).isoformat()

        base_where = "WHERE 1=1"
        args: list[Any] = []
        if deck_id:
            base_where += " AND deck_id = ?"
            args.append(deck_id)

        with sqlite3.connect(self._db_path) as conn:
            # 总卡片数
            total_cards = conn.execute(
                f"SELECT COUNT(*) FROM cards {base_where}", args
            ).fetchone()[0]

            # 今日复习数
            reviewed_today = conn.execute(
                f"SELECT COUNT(*) FROM cards {base_where} AND last_reviewed >= ? AND last_reviewed <= ?",
                args + [today_start, today_end],
            ).fetchone()[0]

            # 待复习数量
            due_cards = conn.execute(
                f"SELECT COUNT(*) FROM cards {base_where} AND next_review <= ?",
                args + [now.isoformat()],
            ).fetchone()[0]

            # 平均难度
            avg_difficulty_row = conn.execute(
                f"SELECT AVG(difficulty) FROM cards {base_where}", args
            ).fetchone()
            avg_difficulty = round(avg_difficulty_row[0], 3) if avg_difficulty_row[0] is not None else 0.0

            # 掌握度 = 1 - 平均难度（越高越好）
            mastery_rate = round(1 - avg_difficulty, 3) if total_cards > 0 else 0.0

            # 掌握的卡片数（难度 < 0.3 视为掌握）
            mastered_cards = conn.execute(
                f"SELECT COUNT(*) FROM cards {base_where} AND difficulty < 0.3", args
            ).fetchone()[0]

            # 学习中的卡片数（难度 0.3-0.7）
            learning_cards = conn.execute(
                f"SELECT COUNT(*) FROM cards {base_where} AND difficulty >= 0.3 AND difficulty <= 0.7",
                args,
            ).fetchone()[0]

            # 困难的卡片数（难度 > 0.7）
            hard_cards = conn.execute(
                f"SELECT COUNT(*) FROM cards {base_where} AND difficulty > 0.7", args
            ).fetchone()[0]

            # 总复习次数
            total_reviews_row = conn.execute(
                f"SELECT SUM(review_count) FROM cards {base_where}", args
            ).fetchone()
            total_reviews = total_reviews_row[0] or 0

        return {
            "total_cards": total_cards,
            "reviewed_today": reviewed_today,
            "due_cards": due_cards,
            "avg_difficulty": avg_difficulty,
            "mastery_rate": mastery_rate,
            "mastered_cards": mastered_cards,
            "learning_cards": learning_cards,
            "hard_cards": hard_cards,
            "total_reviews": total_reviews,
            "deck_id": deck_id,
        }

    # ------------------------------ 动作：卡组管理 ------------------------------

    def _decks(self, params: dict[str, Any]) -> dict[str, Any]:
        """卡组管理：列表/创建/删除.

        Args:
            params:
                - action: "list" / "create" / "delete"
                - deck_id: 删除时的卡组 ID
                - name: 创建时的卡组名称
                - description: 创建时的卡组描述（可选）

        Returns:
            卡组列表或操作结果
        """
        sub_action = params.get("action", "list")

        if sub_action == "create":
            return self._create_deck(params)
        elif sub_action == "delete":
            return self._delete_deck(params)

        # list 模式
        with sqlite3.connect(self._db_path) as conn:
            rows = conn.execute(
                "SELECT deck_id, name, description, card_count, created_at FROM decks ORDER BY created_at DESC"
            ).fetchall()

        decks = [
            {
                "deck_id": r[0],
                "name": r[1],
                "description": r[2] or "",
                "card_count": r[3],
                "created_at": r[4],
            }
            for r in rows
        ]

        return {"decks": decks, "total": len(decks)}

    def _create_deck(self, params: dict[str, Any]) -> dict[str, Any]:
        """创建卡组."""
        deck_id = str(uuid.uuid4())
        name = params.get("name", "")
        description = params.get("description", "")
        now = datetime.now().isoformat()

        with sqlite3.connect(self._db_path) as conn:
            conn.execute(
                "INSERT INTO decks (deck_id, name, description, card_count, created_at) VALUES (?, ?, ?, 0, ?)",
                (deck_id, name, description, now),
            )
            conn.commit()

        return {"deck_id": deck_id, "name": name, "created": True}

    def _delete_deck(self, params: dict[str, Any]) -> dict[str, Any]:
        """删除卡组及其所有卡片."""
        deck_id = params.get("deck_id", "")

        if deck_id == "default":
            raise ValueError("不能删除默认卡组")

        with sqlite3.connect(self._db_path) as conn:
            conn.execute("DELETE FROM cards WHERE deck_id = ?", (deck_id,))
            conn.execute("DELETE FROM decks WHERE deck_id = ?", (deck_id,))
            conn.commit()

        return {"deleted": True, "deck_id": deck_id}

    # ------------------------------ 动作：搜索卡片 ------------------------------

    def _search(self, params: dict[str, Any]) -> dict[str, Any]:
        """搜索卡片（正面/背面/标签模糊匹配）.

        Args:
            params:
                - keyword: 搜索关键词
                - deck_id: 卡组 ID（可选）
                - limit: 返回数量限制（可选，默认 50）

        Returns:
            匹配的卡片列表
        """
        keyword = params.get("keyword", "")
        deck_id = params.get("deck_id")
        limit = int(params.get("limit", 50))

        if not keyword:
            return {"cards": [], "total": 0}

        like_keyword = f"%{keyword}%"
        query = """
            SELECT card_id, deck_id, front, back, tags, difficulty, review_count,
                   last_reviewed, next_review, created_at
            FROM cards
            WHERE (front LIKE ? OR back LIKE ? OR tags LIKE ?)
        """
        args: list[Any] = [like_keyword, like_keyword, like_keyword]

        if deck_id:
            query += " AND deck_id = ?"
            args.append(deck_id)

        query += " ORDER BY created_at DESC LIMIT ?"
        args.append(limit)

        with sqlite3.connect(self._db_path) as conn:
            rows = conn.execute(query, args).fetchall()

        cards = [
            {
                "card_id": r[0],
                "deck_id": r[1],
                "front": r[2],
                "back": r[3],
                "tags": r[4].split(",") if r[4] else [],
                "difficulty": r[5],
                "review_count": r[6],
                "last_reviewed": r[7],
                "next_review": r[8],
                "created_at": r[9],
            }
            for r in rows
        ]

        return {"cards": cards, "total": len(cards), "keyword": keyword}

    # ------------------------------ 工具方法 ------------------------------

    def _ensure_deck_exists(self, deck_id: str) -> None:
        """确保卡组存在，不存在则自动创建."""
        with sqlite3.connect(self._db_path) as conn:
            row = conn.execute(
                "SELECT deck_id FROM decks WHERE deck_id = ?", (deck_id,)
            ).fetchone()
            if not row:
                now = datetime.now().isoformat()
                name = "默认卡组" if deck_id == "default" else deck_id
                conn.execute(
                    "INSERT INTO decks (deck_id, name, description, card_count, created_at) VALUES (?, ?, '', 0, ?)",
                    (deck_id, name, now),
                )
                conn.commit()

    def _error(self, request: SkillInvokeRequest, error: str, start: float) -> SkillInvokeResult:
        """构造错误返回结果."""
        latency = (__import__("time").perf_counter() - start) * 1000
        logger.error("flashcard_error", action=request.action, error=error, trace_id=request.trace_id)
        return SkillInvokeResult(
            skill_id=self.manifest.skill_id,
            action=request.action,
            status="failure",
            error=error,
            latency_ms=latency,
            trace_id=request.trace_id,
        )

    async def health(self) -> dict[str, Any]:
        """健康检查."""
        return {"healthy": True, "skill_id": self.manifest.skill_id}

    async def configure(self, config: dict[str, Any]) -> None:
        """配置技能."""
        self._config.update(config)
