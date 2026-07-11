from __future__ import annotations

"""情绪追踪技能."""

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

# 支持的情绪类型
VALID_MOODS = {"happy", "calm", "sad", "anxious", "angry", "tired", "neutral"}


class MoodSkill(ISkill):
    """情绪追踪技能，支持记录、列表、统计、趋势和洞察."""

    def __init__(self) -> None:
        manifest = SkillManifest(
            skill_id="skill.mood",
            name="情绪追踪",
            version="1.0.0",
            description="记录和分析情绪变化，发现情绪规律与触发因素",
            author="yunxi",
            tags=["mood", "emotion", "mental-health"],
            capabilities=["log", "list", "stats", "trend", "insights"],
            permissions=["read_file", "write"],
            entrypoint="MoodSkill",
        )
        super().__init__(manifest)
        self._config: dict[str, Any] = {}
        self._db_path = os.path.expanduser("~/.yunxi/data/mood.db")
        os.makedirs(os.path.dirname(self._db_path), exist_ok=True)
        self._init_db()

    def _init_db(self) -> None:
        """初始化数据库表结构."""
        with sqlite3.connect(self._db_path) as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS mood_logs (
                    log_id TEXT PRIMARY KEY,
                    mood TEXT,
                    valence REAL,
                    arousal REAL,
                    note TEXT,
                    triggers TEXT,
                    created_at TEXT,
                    date TEXT
                )
                """
            )
            # 创建索引加速日期查询
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_mood_date ON mood_logs(date)"
            )
            conn.commit()

    async def invoke(self, request: SkillInvokeRequest) -> SkillInvokeResult:
        """技能调用入口，根据 action 分发到对应处理方法."""
        action = request.action
        params = request.params
        start = __import__("time").perf_counter()

        try:
            if action == "log":
                data = self._log(params)
            elif action == "list":
                data = self._list(params)
            elif action == "stats":
                data = self._stats(params)
            elif action == "trend":
                data = self._trend(params)
            elif action == "insights":
                data = self._insights(params)
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

    def _log(self, params: dict[str, Any]) -> dict[str, Any]:
        """记录情绪."""
        log_id = str(uuid.uuid4())
        mood = params.get("mood", "neutral")
        valence = float(params.get("valence", 0.0))
        arousal = float(params.get("arousal", 0.5))
        note = params.get("note", "")
        triggers = params.get("triggers", [])
        triggers_str = ",".join(triggers) if isinstance(triggers, list) else triggers
        created_at = datetime.now().isoformat()
        date_str = datetime.now().strftime("%Y-%m-%d")

        # 验证情绪类型
        if mood not in VALID_MOODS:
            raise ValueError(f"无效的情绪类型: {mood}，支持的类型: {', '.join(sorted(VALID_MOODS))}")

        # 验证效价范围 -1 ~ 1
        if valence < -1 or valence > 1:
            raise ValueError("效价(valence)必须在 -1 到 1 之间")

        # 验证唤醒度范围 0 ~ 1
        if arousal < 0 or arousal > 1:
            raise ValueError("唤醒度(arousal)必须在 0 到 1 之间")

        with sqlite3.connect(self._db_path) as conn:
            conn.execute(
                """
                INSERT INTO mood_logs (log_id, mood, valence, arousal, note, triggers, created_at, date)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (log_id, mood, valence, arousal, note, triggers_str, created_at, date_str),
            )
            conn.commit()

        return {
            "log_id": log_id,
            "mood": mood,
            "valence": valence,
            "arousal": arousal,
            "created_at": created_at,
        }

    def _list(self, params: dict[str, Any]) -> dict[str, Any]:
        """情绪记录列表，按日期范围筛选."""
        start_date = params.get("start_date", "")
        end_date = params.get("end_date", "")
        mood = params.get("mood", "")
        page = int(params.get("page", 1))
        page_size = int(params.get("page_size", 30))
        offset = (page - 1) * page_size

        conditions: list[str] = []
        args: list[Any] = []

        if start_date:
            conditions.append("date >= ?")
            args.append(start_date)
        if end_date:
            conditions.append("date <= ?")
            args.append(end_date)
        if mood:
            conditions.append("mood = ?")
            args.append(mood)

        where_clause = " WHERE " + " AND ".join(conditions) if conditions else ""

        with sqlite3.connect(self._db_path) as conn:
            total = conn.execute(
                f"SELECT COUNT(*) FROM mood_logs{where_clause}", args
            ).fetchone()[0]

            rows = conn.execute(
                f"""
                SELECT log_id, mood, valence, arousal, note, triggers, created_at, date
                FROM mood_logs{where_clause}
                ORDER BY created_at DESC
                LIMIT ? OFFSET ?
                """,
                args + [page_size, offset],
            ).fetchall()

        logs = [
            {
                "log_id": r[0],
                "mood": r[1],
                "valence": r[2],
                "arousal": r[3],
                "note": r[4],
                "triggers": r[5].split(",") if r[5] else [],
                "created_at": r[6],
                "date": r[7],
            }
            for r in rows
        ]

        return {
            "logs": logs,
            "total": total,
            "page": page,
            "page_size": page_size,
            "total_pages": (total + page_size - 1) // page_size if page_size > 0 else 0,
        }

    def _stats(self, params: dict[str, Any]) -> dict[str, Any]:
        """统计信息：今日/本周/本月情绪分布."""
        period = params.get("period", "week")  # today, week, month, all
        now = datetime.now()
        today_str = now.strftime("%Y-%m-%d")

        # 计算各周期起始日期
        if period == "today":
            start_date = today_str
            end_date = today_str
        elif period == "week":
            week_start = now - timedelta(days=now.weekday())
            start_date = week_start.strftime("%Y-%m-%d")
            end_date = today_str
        elif period == "month":
            month_start = now.replace(day=1)
            start_date = month_start.strftime("%Y-%m-%d")
            end_date = today_str
        else:  # all
            start_date = ""
            end_date = ""

        conditions: list[str] = []
        args: list[Any] = []

        if start_date:
            conditions.append("date >= ?")
            args.append(start_date)
        if end_date:
            conditions.append("date <= ?")
            args.append(end_date)

        where_clause = " WHERE " + " AND ".join(conditions) if conditions else ""

        with sqlite3.connect(self._db_path) as conn:
            # 总记录数
            total = conn.execute(
                f"SELECT COUNT(*) FROM mood_logs{where_clause}", args
            ).fetchone()[0]

            # 情绪分布
            mood_rows = conn.execute(
                f"SELECT mood, COUNT(*) FROM mood_logs{where_clause} GROUP BY mood ORDER BY COUNT(*) DESC",
                args,
            ).fetchall()

            # 平均效价和唤醒度
            avg_rows = conn.execute(
                f"SELECT AVG(valence), AVG(arousal) FROM mood_logs{where_clause}",
                args,
            ).fetchone()

            # 记录天数
            days_count = conn.execute(
                f"SELECT COUNT(DISTINCT date) FROM mood_logs{where_clause}",
                args,
            ).fetchone()[0]

        mood_distribution = {r[0]: r[1] for r in mood_rows}
        avg_valence = round(avg_rows[0], 3) if avg_rows[0] is not None else 0
        avg_arousal = round(avg_rows[1], 3) if avg_rows[1] is not None else 0

        # 找出最常见情绪
        most_common_mood = mood_rows[0][0] if mood_rows else "neutral"

        return {
            "period": period,
            "start_date": start_date,
            "end_date": end_date,
            "total_records": total,
            "days_tracked": days_count,
            "mood_distribution": mood_distribution,
            "most_common_mood": most_common_mood,
            "avg_valence": avg_valence,
            "avg_arousal": avg_arousal,
        }

    def _trend(self, params: dict[str, Any]) -> dict[str, Any]:
        """趋势分析：最近 N 天的效价/唤醒度趋势."""
        days = int(params.get("days", 7))
        if days < 1:
            raise ValueError("天数必须大于 0")
        if days > 365:
            raise ValueError("天数不能超过 365 天")

        today = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
        start_date = today - timedelta(days=days - 1)
        start_date_str = start_date.strftime("%Y-%m-%d")
        end_date_str = today.strftime("%Y-%m-%d")

        with sqlite3.connect(self._db_path) as conn:
            # 按日期分组，计算每天的平均效价和唤醒度
            rows = conn.execute(
                """
                SELECT date, AVG(valence), AVG(arousal), COUNT(*)
                FROM mood_logs
                WHERE date >= ? AND date <= ?
                GROUP BY date
                ORDER BY date ASC
                """,
                (start_date_str, end_date_str),
            ).fetchall()

        # 构建完整的日期序列
        daily_data: list[dict[str, Any]] = []
        data_by_date = {r[0]: r for r in rows}

        for i in range(days):
            d = start_date + timedelta(days=i)
            d_str = d.strftime("%Y-%m-%d")
            if d_str in data_by_date:
                r = data_by_date[d_str]
                daily_data.append({
                    "date": d_str,
                    "avg_valence": round(r[1], 3),
                    "avg_arousal": round(r[2], 3),
                    "record_count": r[3],
                    "has_data": True,
                })
            else:
                daily_data.append({
                    "date": d_str,
                    "avg_valence": None,
                    "avg_arousal": None,
                    "record_count": 0,
                    "has_data": False,
                })

        # 计算整体趋势（有数据的天）
        valid_days = [d for d in daily_data if d["has_data"]]
        if len(valid_days) >= 2:
            # 简单趋势：比较前半段和后半段的平均效价
            mid = len(valid_days) // 2
            first_half = valid_days[:mid]
            second_half = valid_days[mid:]
            first_avg = sum(d["avg_valence"] for d in first_half) / len(first_half)
            second_avg = sum(d["avg_valence"] for d in second_half) / len(second_half)
            valence_trend = round(second_avg - first_avg, 3)
        else:
            valence_trend = 0

        return {
            "days": days,
            "start_date": start_date_str,
            "end_date": end_date_str,
            "daily_data": daily_data,
            "days_with_data": len(valid_days),
            "valence_trend": valence_trend,
            "trend_direction": "improving" if valence_trend > 0.1 else ("declining" if valence_trend < -0.1 else "stable"),
        }

    def _insights(self, params: dict[str, Any]) -> dict[str, Any]:
        """情绪洞察：常见触发因素、最佳/最差时段等."""
        days = int(params.get("days", 30))
        today = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
        start_date = today - timedelta(days=days - 1)
        start_date_str = start_date.strftime("%Y-%m-%d")

        with sqlite3.connect(self._db_path) as conn:
            # 获取时间范围内所有记录
            rows = conn.execute(
                """
                SELECT log_id, mood, valence, arousal, note, triggers, created_at, date
                FROM mood_logs
                WHERE date >= ?
                ORDER BY created_at ASC
                """,
                (start_date_str,),
            ).fetchall()

        if not rows:
            return {
                "period_days": days,
                "total_records": 0,
                "message": "暂无足够数据生成洞察",
            }

        total_records = len(rows)

        # 统计触发因素
        trigger_counts: dict[str, int] = {}
        positive_triggers: dict[str, int] = {}
        negative_triggers: dict[str, int] = {}

        # 按时段统计（早上/下午/晚上/深夜）
        time_period_counts: dict[str, dict[str, Any]] = {
            "morning": {"count": 0, "total_valence": 0.0, "moods": {}},
            "afternoon": {"count": 0, "total_valence": 0.0, "moods": {}},
            "evening": {"count": 0, "total_valence": 0.0, "moods": {}},
            "night": {"count": 0, "total_valence": 0.0, "moods": {}},
        }

        # 按星期统计
        weekday_data: dict[int, dict[str, Any]] = {
            i: {"count": 0, "total_valence": 0.0} for i in range(7)
        }

        for r in rows:
            mood = r[1]
            valence = r[2]
            triggers_str = r[5]
            created_at = r[6]

            # 触发因素统计
            if triggers_str:
                for trigger in triggers_str.split(","):
                    trigger = trigger.strip()
                    if trigger:
                        trigger_counts[trigger] = trigger_counts.get(trigger, 0) + 1
                        if valence > 0.3:
                            positive_triggers[trigger] = positive_triggers.get(trigger, 0) + 1
                        elif valence < -0.3:
                            negative_triggers[trigger] = negative_triggers.get(trigger, 0) + 1

            # 时段统计
            try:
                dt = datetime.fromisoformat(created_at)
                hour = dt.hour

                if 5 <= hour < 12:
                    period = "morning"
                elif 12 <= hour < 18:
                    period = "afternoon"
                elif 18 <= hour < 23:
                    period = "evening"
                else:
                    period = "night"

                time_period_counts[period]["count"] += 1
                time_period_counts[period]["total_valence"] += valence
                time_period_counts[period]["moods"][mood] = time_period_counts[period]["moods"].get(mood, 0) + 1

                # 星期统计
                weekday = dt.weekday()
                weekday_data[weekday]["count"] += 1
                weekday_data[weekday]["total_valence"] += valence
            except (ValueError, TypeError):
                pass

        # 整理触发因素
        top_triggers = sorted(
            [{"trigger": k, "count": v} for k, v in trigger_counts.items()],
            key=lambda x: x["count"],
            reverse=True,
        )[:10]

        top_positive_triggers = sorted(
            [{"trigger": k, "count": v} for k, v in positive_triggers.items()],
            key=lambda x: x["count"],
            reverse=True,
        )[:5]

        top_negative_triggers = sorted(
            [{"trigger": k, "count": v} for k, v in negative_triggers.items()],
            key=lambda x: x["count"],
            reverse=True,
        )[:5]

        # 最佳/最差时段
        period_avg_valence = []
        for period, data in time_period_counts.items():
            if data["count"] > 0:
                avg = data["total_valence"] / data["count"]
                period_avg_valence.append({"period": period, "avg_valence": round(avg, 3), "count": data["count"]})

        period_avg_valence.sort(key=lambda x: x["avg_valence"], reverse=True)
        best_period = period_avg_valence[0] if period_avg_valence else None
        worst_period = period_avg_valence[-1] if len(period_avg_valence) > 1 else None

        # 最佳/最差星期
        weekday_names = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]
        weekday_avg = []
        for wd, data in weekday_data.items():
            if data["count"] > 0:
                avg = data["total_valence"] / data["count"]
                weekday_avg.append({"weekday": weekday_names[wd], "weekday_num": wd, "avg_valence": round(avg, 3), "count": data["count"]})

        weekday_avg.sort(key=lambda x: x["avg_valence"], reverse=True)
        best_weekday = weekday_avg[0] if weekday_avg else None
        worst_weekday = weekday_avg[-1] if len(weekday_avg) > 1 else None

        return {
            "period_days": days,
            "start_date": start_date_str,
            "total_records": total_records,
            "top_triggers": top_triggers,
            "top_positive_triggers": top_positive_triggers,
            "top_negative_triggers": top_negative_triggers,
            "best_time_period": best_period,
            "worst_time_period": worst_period,
            "best_weekday": best_weekday,
            "worst_weekday": worst_weekday,
            "time_period_stats": {
                p: {
                    "count": d["count"],
                    "avg_valence": round(d["total_valence"] / d["count"], 3) if d["count"] > 0 else 0,
                }
                for p, d in time_period_counts.items()
            },
        }

    def _error(self, request: SkillInvokeRequest, error: str, start: float) -> SkillInvokeResult:
        """构造错误返回结果."""
        latency = (__import__("time").perf_counter() - start) * 1000
        logger.error("mood_error", action=request.action, error=error, trace_id=request.trace_id)
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
        """配置更新."""
        self._config.update(config)
