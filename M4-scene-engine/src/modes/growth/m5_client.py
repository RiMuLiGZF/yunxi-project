"""成长中心模式 - M5 成长系统客户端.

封装对 M5 潮汐记忆成长系统的 HTTP API 调用，
包括成就、天赋、历法、编年史、回响、赛季六大模块。
M5 不可用时自动返回 fallback mock 数据，确保业务不中断。
"""

from __future__ import annotations

import os
from typing import Any, Optional

import structlog

# ---------------------------------------------------------------------------
# 配置常量
# ---------------------------------------------------------------------------

#: M5 服务地址
M5_BASE_URL = os.environ.get("M5_BASE_URL", "http://localhost:8005")
#: 请求超时时间（秒）
M5_TIMEOUT = float(os.environ.get("M5_TIMEOUT", "5"))
#: 是否启用 fallback（开发环境默认开启）
M5_FALLBACK_ENABLED = os.environ.get("M5_FALLBACK", "true").lower() == "true"


# ---------------------------------------------------------------------------
# Mock 数据生成器
# ---------------------------------------------------------------------------


def _mock_achievement_list() -> dict[str, Any]:
    """Mock 成就列表数据."""
    return {
        "items": [
            {"id": "ach_first_step", "name": "初心萌动", "category": "growth",
             "rarity": "common", "rarity_text": "普通",
             "unlocked": True, "unlock_date": "2024-01-15",
             "condition": "完成第一次打卡",
             "description": "迈出成长的第一步，未来可期",
             "point_reward": 1},
            {"id": "ach_streak_7", "name": "七日之约", "category": "growth",
             "rarity": "rare", "rarity_text": "稀有",
             "unlocked": True, "unlock_date": "2024-02-01",
             "condition": "连续打卡7天",
             "description": "坚持一周，习惯初成",
             "point_reward": 2},
            {"id": "ach_streak_30", "name": "月度坚守", "category": "growth",
             "rarity": "epic", "rarity_text": "史诗",
             "unlocked": False, "unlock_date": "",
             "condition": "连续打卡30天",
             "description": "一个月的坚持，见证成长",
             "point_reward": 3},
            {"id": "ach_talent_master", "name": "天赋觉醒", "category": "skill",
             "rarity": "rare", "rarity_text": "稀有",
             "unlocked": True, "unlock_date": "2024-03-10",
             "condition": "解锁10个天赋节点",
             "description": "天赋之树初绽光芒",
             "point_reward": 2},
            {"id": "ach_social_first", "name": "社交达人", "category": "social",
             "rarity": "common", "rarity_text": "普通",
             "unlocked": False, "unlock_date": "",
             "condition": "首次进行社交互动",
             "description": "打开心扉，连接世界",
             "point_reward": 1},
            {"id": "ach_legendary_season", "name": "赛季传奇", "category": "special",
             "rarity": "legendary", "rarity_text": "传奇",
             "unlocked": False, "unlock_date": "",
             "condition": "完成一整个赛季全部任务",
             "description": "传奇之路，无人能及",
             "point_reward": 5},
        ],
        "total": 6,
    }


def _mock_achievement_stats() -> dict[str, Any]:
    """Mock 成就统计数据."""
    return {
        "total": 30,
        "unlocked": 12,
        "locked": 18,
        "by_category": {
            "growth": {"total": 10, "unlocked": 5},
            "skill": {"total": 8, "unlocked": 4},
            "social": {"total": 6, "unlocked": 2},
            "special": {"total": 6, "unlocked": 1},
        },
        "by_rarity": {
            "common": 8,
            "rare": 3,
            "epic": 1,
            "legendary": 0,
        },
        "unlock_rate": 40.0,
    }


def _mock_talent_tree() -> dict[str, Any]:
    """Mock 天赋树数据."""
    return {
        "nodes": [
            {"id": "mind_root", "name": "心智之根", "branch": "mind",
             "description": "心智分支的起点", "status": "unlocked",
             "level": 1, "max_level": 1, "parent_id": None,
             "children_ids": ["mind_focus", "mind_memory"],
             "tree": "mind", "point_cost": 0, "layer": 1},
            {"id": "mind_focus", "name": "专注之心", "branch": "mind",
             "description": "提升专注力与注意力", "status": "unlocked",
             "level": 2, "max_level": 3, "parent_id": "mind_root",
             "children_ids": ["mind_flow"],
             "tree": "mind", "point_cost": 1, "layer": 2},
            {"id": "mind_memory", "name": "记忆回廊", "branch": "mind",
             "description": "增强记忆与回忆能力", "status": "locked",
             "level": 0, "max_level": 3, "parent_id": "mind_root",
             "children_ids": [],
             "tree": "mind", "point_cost": 1, "layer": 2},
            {"id": "mind_flow", "name": "心流状态", "branch": "mind",
             "description": "进入深度心流状态", "status": "locked",
             "level": 0, "max_level": 1, "parent_id": "mind_focus",
             "children_ids": [],
             "tree": "mind", "point_cost": 2, "layer": 3},
            {"id": "emotion_root", "name": "稳态之核", "branch": "emotion",
             "description": "情绪稳态的根基", "status": "unlocked",
             "level": 1, "max_level": 1, "parent_id": None,
             "children_ids": ["emotion_calm", "emotion_resilience"],
             "tree": "emotion", "point_cost": 0, "layer": 1},
            {"id": "emotion_calm", "name": "平静之心", "branch": "emotion",
             "description": "保持内心平静", "status": "unlocked",
             "level": 1, "max_level": 3, "parent_id": "emotion_root",
             "children_ids": [],
             "tree": "emotion", "point_cost": 1, "layer": 2},
            {"id": "emotion_resilience", "name": "韧性之魂", "branch": "emotion",
             "description": "增强心理韧性", "status": "locked",
             "level": 0, "max_level": 3, "parent_id": "emotion_root",
             "children_ids": [],
             "tree": "emotion", "point_cost": 1, "layer": 2},
            {"id": "creativity_root", "name": "创造之源", "branch": "creativity",
             "description": "创造灵感的源泉", "status": "unlocked",
             "level": 1, "max_level": 1, "parent_id": None,
             "children_ids": ["creativity_idea", "creativity_express"],
             "tree": "creativity", "point_cost": 0, "layer": 1},
            {"id": "creativity_idea", "name": "灵感迸发", "branch": "creativity",
             "description": "激发创意灵感", "status": "locked",
             "level": 0, "max_level": 3, "parent_id": "creativity_root",
             "children_ids": [],
             "tree": "creativity", "point_cost": 1, "layer": 2},
            {"id": "creativity_express", "name": "表达之翼", "branch": "creativity",
             "description": "提升表达能力", "status": "locked",
             "level": 0, "max_level": 3, "parent_id": "creativity_root",
             "children_ids": [],
             "tree": "creativity", "point_cost": 1, "layer": 2},
            {"id": "experience_root", "name": "阅历之书", "branch": "experience",
             "description": "人生阅历的积累", "status": "unlocked",
             "level": 1, "max_level": 1, "parent_id": None,
             "children_ids": ["experience_adapt", "experience_wisdom"],
             "tree": "experience", "point_cost": 0, "layer": 1},
            {"id": "experience_adapt", "name": "适应之力", "branch": "experience",
             "description": "提升环境适应力", "status": "unlocked",
             "level": 1, "max_level": 3, "parent_id": "experience_root",
             "children_ids": [],
             "tree": "experience", "point_cost": 1, "layer": 2},
            {"id": "experience_wisdom", "name": "智慧之光", "branch": "experience",
             "description": "沉淀人生智慧", "status": "locked",
             "level": 0, "max_level": 3, "parent_id": "experience_root",
             "children_ids": [],
             "tree": "experience", "point_cost": 1, "layer": 2},
        ],
        "connections": [
            {"from": "mind_root", "to": "mind_focus"},
            {"from": "mind_root", "to": "mind_memory"},
            {"from": "mind_focus", "to": "mind_flow"},
            {"from": "emotion_root", "to": "emotion_calm"},
            {"from": "emotion_root", "to": "emotion_resilience"},
            {"from": "creativity_root", "to": "creativity_idea"},
            {"from": "creativity_root", "to": "creativity_express"},
            {"from": "experience_root", "to": "experience_adapt"},
            {"from": "experience_root", "to": "experience_wisdom"},
        ],
        "available_points": 5,
        "total_points": 15,
        "spent_points": 10,
        "stats": {
            "mind": {"unlocked": 2, "total": 5},
            "emotion": {"unlocked": 2, "total": 3},
            "creativity": {"unlocked": 1, "total": 3},
            "experience": {"unlocked": 2, "total": 3},
        },
    }


def _mock_talent_points() -> dict[str, Any]:
    """Mock 天赋点数数据."""
    return {
        "available_points": 5,
        "history": [
            {"date": "2024-03-15", "change": 2, "reason": "解锁成就：七日之约", "type": "earn"},
            {"date": "2024-03-10", "change": -1, "reason": "升级专注之心", "type": "spend"},
            {"date": "2024-03-01", "change": 2, "reason": "解锁成就：天赋觉醒", "type": "earn"},
            {"date": "2024-02-15", "change": 1, "reason": "解锁成就：初心萌动", "type": "earn"},
        ],
    }


def _mock_talent_stats() -> dict[str, Any]:
    """Mock 天赋统计数据."""
    return {
        "total_nodes": 14,
        "unlocked_nodes": 7,
        "max_level_nodes": 0,
        "available_points": 5,
        "total_points_earned": 15,
        "by_branch": {
            "mind": {"unlocked": 2, "total": 5, "spent_points": 3},
            "emotion": {"unlocked": 2, "total": 3, "spent_points": 2},
            "creativity": {"unlocked": 1, "total": 3, "spent_points": 0},
            "experience": {"unlocked": 2, "total": 3, "spent_points": 2},
        },
    }


def _mock_calendar_month(year: int, month: int) -> dict[str, Any]:
    """Mock 月历数据."""
    from calendar import monthrange
    _, days_in_month = monthrange(year, month)
    days = []
    for day in range(1, days_in_month + 1):
        date_str = f"{year}-{month:02d}-{day:02d}"
        is_checked = day <= 15  # 前半月已打卡
        mood = 7 if is_checked else 0
        energy = 8 if is_checked else 0
        tide_phase = "大潮" if day % 7 == 0 else "小潮"
        days.append({
            "date": date_str,
            "mood": mood,
            "energy": energy,
            "checked_in": is_checked,
            "summary": "今天学习了新的知识" if is_checked else "",
            "tags": ["学习", "成长"] if is_checked and day % 3 == 0 else [],
            "tide_phase": tide_phase,
        })
    return {
        "year": year,
        "month": month,
        "days": days,
        "stats": {
            "total_days": days_in_month,
            "checked_days": 15,
            "streak": 5,
            "avg_mood": 7.2,
            "avg_energy": 7.8,
            "checkin_rate": 15 / days_in_month * 100,
        },
    }


def _mock_calendar_stats() -> dict[str, Any]:
    """Mock 日历统计数据."""
    return {
        "total_days": 90,
        "checked_days": 62,
        "streak": 5,
        "avg_mood": 7.3,
        "avg_energy": 7.6,
        "checkin_rate": 68.9,
    }


def _mock_checkin() -> dict[str, Any]:
    """Mock 打卡返回."""
    return {
        "success": True,
        "date": "2024-03-15",
        "mood": 8,
        "energy": 7,
        "streak": 6,
        "message": "打卡成功！连续打卡第 6 天",
        "points_earned": 1,
    }


def _mock_chronicle_list() -> dict[str, Any]:
    """Mock 编年史列表."""
    return {
        "items": [
            {"id": "chr_001", "date": "2024.03.15", "title": "完成项目重构",
             "category": "main-quest", "category_text": "主线任务",
             "difficulty": "困难", "content": "历时两周完成了核心模块的重构工作",
             "tags": ["工作", "重构"], "has_git": True,
             "git_commits": [{"hash": "abc123", "message": "refactor: 重构核心模块"}],
             "created_at": "2024-03-15T10:00:00",
             "updated_at": "2024-03-15T10:00:00"},
            {"id": "chr_002", "date": "2024.03.10", "title": "解锁新技能",
             "category": "achievement", "category_text": "成就",
             "difficulty": "普通", "content": "学会了新的编程语言特性",
             "tags": ["学习", "技能"], "has_git": False,
             "git_commits": [],
             "created_at": "2024-03-10T14:30:00",
             "updated_at": "2024-03-10T14:30:00"},
            {"id": "chr_003", "date": "2024.03.01", "title": "人生重要决定",
             "category": "critical-decision", "category_text": "关键抉择",
             "difficulty": "史诗", "content": "做出了一个影响深远的决定",
             "tags": ["人生", "抉择"], "has_git": False,
             "git_commits": [],
             "created_at": "2024-03-01T09:00:00",
             "updated_at": "2024-03-01T09:00:00"},
            {"id": "chr_004", "date": "2024.02.28", "title": "支线任务完成",
             "category": "side-quest", "category_text": "支线任务",
             "difficulty": "入门", "content": "完成了一个有趣的小项目",
             "tags": ["兴趣", "项目"], "has_git": True,
             "git_commits": [{"hash": "def456", "message": "feat: 添加新功能"}],
             "created_at": "2024-02-28T16:00:00",
             "updated_at": "2024-02-28T16:00:00"},
        ],
        "total": 4,
        "page": 1,
        "size": 20,
        "total_pages": 1,
    }


def _mock_chronicle_detail(chronicle_id: str) -> dict[str, Any]:
    """Mock 编年史详情."""
    items = _mock_chronicle_list()["items"]
    for item in items:
        if item["id"] == chronicle_id:
            return item
    return {}


def _mock_echo_list() -> dict[str, Any]:
    """Mock 回响列表."""
    return {
        "items": [
            {"id": "echo_001", "title": "从焦虑到平静",
             "category": "emotion", "category_text": "情绪",
             "before": {"date": "2024-01-01", "title": "年初的迷茫",
                        "desc": "对未来感到焦虑不安", "emotion": "焦虑",
                        "pattern": "逃避问题", "tags": ["焦虑", "迷茫"]},
             "after": {"date": "2024-03-01", "title": "内心的笃定",
                       "desc": "学会与焦虑共处", "emotion": "平静",
                       "pattern": "积极面对", "tags": ["成长", "平静"]},
             "growth": "两个月的时间，学会了与焦虑共处的方法，内心更加笃定。",
             "content": "通过冥想、运动和写日记帮助我走出了困境。",
             "created_at": "2024-03-01T10:00:00"},
            {"id": "echo_002", "title": "编程能力提升",
             "category": "growth", "category_text": "成长",
             "before": {"date": "2024-01-15", "title": "入门阶段",
                        "desc": "只会基础语法", "emotion": "兴奋",
                        "pattern": "被动学习", "tags": ["编程", "入门"]},
             "after": {"date": "2024-03-15", "title": "独立开发",
                       "desc": "能独立完成项目", "emotion": "自豪",
                       "pattern": "主动探索", "tags": ["编程", "成长"]},
             "growth": "从入门到独立开发，代码量和思维都有了质的飞跃。",
             "content": "通过大量实践和项目经验的积累。",
             "created_at": "2024-03-15T14:00:00"},
        ],
        "total": 2,
        "page": 1,
        "size": 20,
        "total_pages": 1,
    }


def _mock_echo_detail(echo_id: str) -> dict[str, Any]:
    """Mock 回响详情."""
    items = _mock_echo_list()["items"]
    for item in items:
        if item["id"] == echo_id:
            return item
    return {}


def _mock_generate_echo() -> dict[str, Any]:
    """Mock 生成回响."""
    return {
        "id": "echo_new",
        "title": "新的成长回响",
        "category": "growth",
        "category_text": "成长",
        "before": {"date": "过去", "title": "过去的状态",
                   "desc": "过去的描述", "emotion": "",
                   "pattern": "", "tags": []},
        "after": {"date": "现在", "title": "现在的状态",
                  "desc": "现在的描述", "emotion": "",
                  "pattern": "", "tags": []},
        "growth": "在这段时间里，你经历了显著的成长。",
        "content": "每一步都是进步。",
        "created_at": "2024-03-15T10:00:00",
    }


def _mock_current_season() -> dict[str, Any]:
    """Mock 当前赛季."""
    return {
        "id": "season_2024_spring",
        "name": "春之觉醒赛季",
        "period": "2024年3月 - 2024年5月",
        "start_date": "2024-03-01",
        "end_date": "2024-05-31",
        "status": "active",
        "progress": 45,
        "days_left": 47,
        "phases": [
            {"id": "phase_1", "name": "萌芽阶段", "status": "completed",
             "tasks_total": 5, "tasks_completed": 5,
             "reward": "萌芽勋章", "reward_points": 3, "reward_claimed": True},
            {"id": "phase_2", "name": "生长阶段", "status": "active",
             "tasks_total": 7, "tasks_completed": 4,
             "reward": "生长勋章", "reward_points": 5, "reward_claimed": False},
            {"id": "phase_3", "name": "绽放阶段", "status": "locked",
             "tasks_total": 5, "tasks_completed": 0,
             "reward": "绽放勋章", "reward_points": 8, "reward_claimed": False},
        ],
    }


def _mock_season_history() -> dict[str, Any]:
    """Mock 赛季历史."""
    return {
        "items": [
            {"id": "season_2024_winter", "name": "冬之蛰伏赛季",
             "period": "2023年12月 - 2024年2月",
             "start_date": "2023-12-01", "end_date": "2024-02-29",
             "status": "completed", "progress": 100, "days_left": 0,
             "phases": []},
        ],
        "total": 1,
    }


def _mock_season_tasks() -> dict[str, Any]:
    """Mock 赛季任务列表."""
    return {
        "items": [
            {"id": "task_001", "phase_id": "phase_2",
             "title": "每日打卡", "description": "每天完成一次打卡",
             "type": "daily", "status": "completed", "points": 1,
             "completed_at": "2024-03-15T08:00:00"},
            {"id": "task_002", "phase_id": "phase_2",
             "title": "完成本周学习目标", "description": "本周学习满20小时",
             "type": "weekly", "status": "pending", "points": 3,
             "completed_at": None},
            {"id": "task_003", "phase_id": "phase_2",
             "title": "解锁5个成就", "description": "本赛季解锁5个新成就",
             "type": "seasonal", "status": "in-progress", "points": 5,
             "completed_at": None},
            {"id": "task_004", "phase_id": "phase_2",
             "title": "生成3篇编年史", "description": "记录3条重要纪事",
             "type": "seasonal", "status": "completed", "points": 3,
             "completed_at": "2024-03-10T12:00:00"},
            {"id": "task_005", "phase_id": "phase_2",
             "title": "连续打卡14天", "description": "连续14天不间断打卡",
             "type": "seasonal", "status": "pending", "points": 5,
             "completed_at": None},
        ],
        "total": 5,
    }


# ---------------------------------------------------------------------------
# M5 客户端类
# ---------------------------------------------------------------------------


class M5GrowthClient:
    """M5 成长系统 API 客户端.

    封装对 M5 潮汐记忆成长系统的 HTTP API 调用，
    涵盖成就、天赋、历法、编年史、回响、赛季六大模块。
    M5 不可用时自动返回 fallback mock 数据。
    """

    _logger = structlog.get_logger(__name__)

    def __init__(
        self,
        base_url: str = M5_BASE_URL,
        timeout: float = M5_TIMEOUT,
        fallback_enabled: bool = M5_FALLBACK_ENABLED,
    ) -> None:
        """初始化 M5 客户端.

        Args:
            base_url: M5 服务基础地址
            timeout: 请求超时时间（秒）
            fallback_enabled: 是否启用 fallback mock 数据
        """
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.fallback_enabled = fallback_enabled
        self._client = None  # httpx.AsyncClient 懒加载

    async def _get_client(self):
        """获取 httpx 异步客户端（懒加载）."""
        if self._client is None:
            try:
                import httpx
                self._client = httpx.AsyncClient(timeout=self.timeout)
            except ImportError:
                self._client = None
        return self._client

    async def _request(
        self,
        method: str,
        path: str,
        params: Optional[dict[str, Any]] = None,
        json: Optional[dict[str, Any]] = None,
        fallback_data: Optional[dict[str, Any]] = None,
    ) -> dict[str, Any]:
        """发送 HTTP 请求到 M5.

        Args:
            method: HTTP 方法（GET/POST/PUT/DELETE）
            path: API 路径
            params: 查询参数
            json: 请求体 JSON
            fallback_data: fallback 数据（M5 不可用时返回）

        Returns:
            M5 返回的数据或 fallback 数据
        """
        client = await self._get_client()

        if client is None:
            # httpx 不可用，直接返回 fallback
            if fallback_data is not None:
                return fallback_data
            return {}

        url = f"{self.base_url}{path}"
        try:
            response = await client.request(
                method=method,
                url=url,
                params=params,
                json=json,
            )
            if response.status_code == 200:
                result = response.json()
                # M5 返回格式: {code, message, data, ...}
                if isinstance(result, dict) and "data" in result:
                    return result["data"]
                return result
            # 非 200 状态码，fallback
            if self.fallback_enabled and fallback_data is not None:
                return fallback_data
            return {}
        except Exception as e:
            # 连接失败等异常，fallback
            self._logger.warning("m5_client.request_failed", endpoint=endpoint,
                                 error_type=type(e).__name__, error=str(e))
            if self.fallback_enabled and fallback_data is not None:
                return fallback_data
            return {}

    async def close(self) -> None:
        """关闭客户端连接."""
        if self._client is not None:
            try:
                await self._client.aclose()
            except Exception as e:
                self._logger.warning("m5_client.close_failed", error_type=type(e).__name__, error=str(e))
                pass
            self._client = None

    # -----------------------------------------------------------------------
    # 成就勋章 API
    # -----------------------------------------------------------------------

    async def list_achievements(
        self,
        category: Optional[str] = None,
        status: Optional[str] = None,
    ) -> dict[str, Any]:
        """获取成就列表.

        Args:
            category: 分类过滤（growth/skill/social/special）
            status: 状态过滤（unlocked/locked）

        Returns:
            成就列表数据
        """
        params = {}
        if category:
            params["category"] = category
        if status:
            params["status"] = status

        return await self._request(
            "GET",
            "/api/v1/growth/achievements",
            params=params if params else None,
            fallback_data=_mock_achievement_list(),
        )

    async def get_achievement_stats(self) -> dict[str, Any]:
        """获取成就统计.

        Returns:
            成就统计数据
        """
        return await self._request(
            "GET",
            "/api/v1/growth/achievements/stats",
            fallback_data=_mock_achievement_stats(),
        )

    async def unlock_achievement(self, achievement_id: str) -> dict[str, Any]:
        """解锁指定成就.

        Args:
            achievement_id: 成就 ID

        Returns:
            解锁结果
        """
        return await self._request(
            "POST",
            f"/api/v1/growth/achievements/{achievement_id}/unlock",
            fallback_data={"success": True, "achievement_id": achievement_id,
                            "message": "成就解锁成功", "points_earned": 1},
        )

    # -----------------------------------------------------------------------
    # 天赋树 API
    # -----------------------------------------------------------------------

    async def get_talent_tree(self, tree: Optional[str] = None) -> dict[str, Any]:
        """获取天赋树.

        Args:
            tree: 指定分支（mind/emotion/creativity/experience），可选

        Returns:
            天赋树数据
        """
        params = {"tree": tree} if tree else None
        return await self._request(
            "GET",
            "/api/v1/growth/talents",
            params=params,
            fallback_data=_mock_talent_tree(),
        )

    async def upgrade_talent(self, node_id: str) -> dict[str, Any]:
        """升级天赋节点.

        Args:
            node_id: 节点 ID

        Returns:
            升级结果
        """
        return await self._request(
            "POST",
            f"/api/v1/growth/talents/{node_id}/upgrade",
            fallback_data={"success": True, "node_id": node_id,
                            "new_level": 2, "points_spent": 1,
                            "message": "天赋升级成功"},
        )

    async def reset_talents(self) -> dict[str, Any]:
        """重置天赋树，返还点数.

        Returns:
            重置结果
        """
        return await self._request(
            "POST",
            "/api/v1/growth/talents/reset",
            fallback_data={"success": True, "refunded_points": 10,
                            "message": "天赋树已重置，点数已返还"},
        )

    async def get_talent_points(self) -> dict[str, Any]:
        """获取可用天赋点数.

        Returns:
            天赋点数数据
        """
        return await self._request(
            "GET",
            "/api/v1/growth/talents/points",
            fallback_data=_mock_talent_points(),
        )

    async def get_talent_stats(self) -> dict[str, Any]:
        """获取天赋统计.

        Returns:
            天赋统计数据
        """
        return await self._request(
            "GET",
            "/api/v1/growth/talents/stats",
            fallback_data=_mock_talent_stats(),
        )

    async def add_talent_points(
        self,
        amount: int = 1,
        source: str = "m4",
        source_id: str = "",
        reason: str = "",
    ) -> bool:
        """调用 M5 增加天赋点数.

        Args:
            amount: 增加的点数（正整数，>=1）
            source: 来源标识
            source_id: 来源ID
            reason: 原因说明

        Returns:
            是否成功
        """
        try:
            result = await self._request(
                "POST",
                "/api/v1/growth/talents/points/add",
                params={"amount": amount, "source": source, "source_id": source_id, "reason": reason},
                fallback_data={"available_points": amount, "added": amount},
            )
            return isinstance(result, dict) and result.get("added") == amount
        except Exception:
            return False

    # -----------------------------------------------------------------------
    # 潮汐历法 API
    # -----------------------------------------------------------------------

    async def get_month_calendar(self, year: int, month: int) -> dict[str, Any]:
        """获取指定年月的日历数据.

        Args:
            year: 年份
            month: 月份

        Returns:
            月历数据
        """
        return await self._request(
            "GET",
            f"/api/v1/growth/calendar/{year}/{month}",
            fallback_data=_mock_calendar_month(year, month),
        )

    async def checkin(
        self,
        mood: int = 7,
        energy: int = 7,
        date: Optional[str] = None,
        summary: str = "",
        tags: Optional[list[str]] = None,
    ) -> dict[str, Any]:
        """打卡.

        Args:
            mood: 心情值 1-10
            energy: 精力值 1-10
            date: 日期（YYYY-MM-DD），可选，默认今天
            summary: 当日总结
            tags: 标签列表

        Returns:
            打卡结果
        """
        body = {
            "mood": mood,
            "energy": energy,
        }
        if date:
            body["date"] = date
        if summary:
            body["summary"] = summary
        if tags:
            body["tags"] = tags

        return await self._request(
            "POST",
            "/api/v1/growth/calendar/checkin",
            json=body,
            fallback_data=_mock_checkin(),
        )

    async def get_calendar_stats(self) -> dict[str, Any]:
        """获取日历统计.

        Returns:
            日历统计数据
        """
        return await self._request(
            "GET",
            "/api/v1/growth/calendar/stats",
            fallback_data=_mock_calendar_stats(),
        )

    async def get_day_data(self, date: str) -> dict[str, Any]:
        """获取指定日期的数据.

        Args:
            date: 日期（YYYY-MM-DD）

        Returns:
            单日数据
        """
        return await self._request(
            "GET",
            f"/api/v1/growth/calendar/day/{date}",
            fallback_data={
                "date": date,
                "mood": 7,
                "energy": 8,
                "checked_in": True,
                "summary": "今天过得很充实",
                "tags": ["学习", "成长"],
                "tide_phase": "大潮",
            },
        )

    # -----------------------------------------------------------------------
    # 编年史 API
    # -----------------------------------------------------------------------

    async def list_chronicles(
        self,
        page: int = 1,
        size: int = 20,
        category: Optional[str] = None,
        year: Optional[int] = None,
    ) -> dict[str, Any]:
        """分页查询纪事列表.

        Args:
            page: 页码
            size: 每页数量
            category: 分类筛选
            year: 年份筛选

        Returns:
            编年史列表数据
        """
        params = {"page": page, "size": size}
        if category:
            params["category"] = category
        if year:
            params["year"] = year

        return await self._request(
            "GET",
            "/api/v1/growth/chronicle",
            params=params,
            fallback_data=_mock_chronicle_list(),
        )

    async def get_chronicle(self, chronicle_id: str) -> dict[str, Any]:
        """获取单条纪事详情.

        Args:
            chronicle_id: 纪事 ID

        Returns:
            纪事详情数据
        """
        return await self._request(
            "GET",
            f"/api/v1/growth/chronicle/{chronicle_id}",
            fallback_data=_mock_chronicle_detail(chronicle_id),
        )

    async def create_chronicle(self, data: dict[str, Any]) -> dict[str, Any]:
        """创建纪事.

        Args:
            data: 纪事数据

        Returns:
            创建后的纪事数据
        """
        return await self._request(
            "POST",
            "/api/v1/growth/chronicle",
            json=data,
            fallback_data={
                "id": "chr_new",
                **data,
                "created_at": "2024-03-15T10:00:00",
                "updated_at": "2024-03-15T10:00:00",
            },
        )

    async def update_chronicle(
        self,
        chronicle_id: str,
        data: dict[str, Any],
    ) -> dict[str, Any]:
        """更新纪事.

        Args:
            chronicle_id: 纪事 ID
            data: 更新数据

        Returns:
            更新后的纪事数据
        """
        return await self._request(
            "PUT",
            f"/api/v1/growth/chronicle/{chronicle_id}",
            json=data,
            fallback_data={
                "id": chronicle_id,
                **data,
                "updated_at": "2024-03-15T10:00:00",
            },
        )

    async def delete_chronicle(self, chronicle_id: str) -> dict[str, Any]:
        """删除纪事.

        Args:
            chronicle_id: 纪事 ID

        Returns:
            删除结果
        """
        return await self._request(
            "DELETE",
            f"/api/v1/growth/chronicle/{chronicle_id}",
            fallback_data={"deleted": True},
        )

    # -----------------------------------------------------------------------
    # 记忆回响 API
    # -----------------------------------------------------------------------

    async def list_echoes(
        self,
        page: int = 1,
        size: int = 20,
        category: Optional[str] = None,
        keyword: Optional[str] = None,
    ) -> dict[str, Any]:
        """分页查询记忆回响列表.

        Args:
            page: 页码
            size: 每页数量
            category: 分类筛选
            keyword: 关键词搜索

        Returns:
            回响列表数据
        """
        params = {"page": page, "size": size}
        if category:
            params["category"] = category
        if keyword:
            params["keyword"] = keyword

        return await self._request(
            "GET",
            "/api/v1/growth/memories",
            params=params,
            fallback_data=_mock_echo_list(),
        )

    async def get_echo(self, echo_id: str) -> dict[str, Any]:
        """获取单条回响详情.

        Args:
            echo_id: 回响 ID

        Returns:
            回响详情数据
        """
        return await self._request(
            "GET",
            f"/api/v1/growth/memories/{echo_id}",
            fallback_data=_mock_echo_detail(echo_id),
        )

    async def generate_echo(self, data: dict[str, Any]) -> dict[str, Any]:
        """生成记忆回响.

        Args:
            data: 生成参数（type, memory_id, before, after 等）

        Returns:
            生成的回响数据
        """
        return await self._request(
            "POST",
            "/api/v1/growth/memories/generate",
            json=data,
            fallback_data=_mock_generate_echo(),
        )

    async def delete_echo(self, echo_id: str) -> dict[str, Any]:
        """删除回响.

        Args:
            echo_id: 回响 ID

        Returns:
            删除结果
        """
        return await self._request(
            "DELETE",
            f"/api/v1/growth/memories/{echo_id}",
            fallback_data={"deleted": True},
        )

    # -----------------------------------------------------------------------
    # 赛季征程 API
    # -----------------------------------------------------------------------

    async def get_current_season(self) -> dict[str, Any]:
        """获取当前赛季详情.

        Returns:
            当前赛季数据
        """
        return await self._request(
            "GET",
            "/api/v1/growth/season/current",
            fallback_data=_mock_current_season(),
        )

    async def get_season_history(self) -> dict[str, Any]:
        """获取历史赛季列表.

        Returns:
            历史赛季数据
        """
        return await self._request(
            "GET",
            "/api/v1/growth/season/history",
            fallback_data=_mock_season_history(),
        )

    async def list_season_tasks(
        self,
        task_type: Optional[str] = None,
        phase_id: Optional[str] = None,
        season_id: Optional[str] = None,
        status: Optional[str] = None,
    ) -> dict[str, Any]:
        """获取赛季任务列表.

        Args:
            task_type: 类型筛选（daily/weekly/seasonal）
            phase_id: 阶段 ID 筛选
            season_id: 赛季 ID 筛选
            status: 状态筛选

        Returns:
            任务列表数据
        """
        params = {}
        if task_type:
            params["type"] = task_type
        if phase_id:
            params["phase_id"] = phase_id
        if season_id:
            params["season_id"] = season_id
        if status:
            params["status"] = status

        return await self._request(
            "GET",
            "/api/v1/growth/season/tasks",
            params=params if params else None,
            fallback_data=_mock_season_tasks(),
        )

    async def complete_season_task(self, task_id: str) -> dict[str, Any]:
        """完成赛季任务.

        Args:
            task_id: 任务 ID

        Returns:
            完成结果
        """
        return await self._request(
            "POST",
            f"/api/v1/growth/season/tasks/{task_id}/complete",
            fallback_data={"success": True, "task_id": task_id,
                            "points_earned": 3,
                            "message": "任务完成"},
        )

    async def claim_season_reward(self, task_id_or_phase_id: str) -> dict[str, Any]:
        """领取赛季奖励.

        Args:
            task_id_or_phase_id: 任务 ID 或阶段 ID

        Returns:
            领取结果
        """
        return await self._request(
            "POST",
            f"/api/v1/growth/season/tasks/{task_id_or_phase_id}/claim",
            fallback_data={"success": True, "id": task_id_or_phase_id,
                            "points_earned": 5,
                            "message": "奖励领取成功"},
        )


# ---------------------------------------------------------------------------
# 全局单例
# ---------------------------------------------------------------------------

#: 全局 M5 客户端实例
_growth_client: Optional[M5GrowthClient] = None


def get_m5_client() -> M5GrowthClient:
    """获取 M5 成长系统客户端单例.

    Returns:
        M5GrowthClient 实例
    """
    global _growth_client
    if _growth_client is None:
        _growth_client = M5GrowthClient()
    return _growth_client
