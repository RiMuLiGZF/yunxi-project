"""多模态特征提取器.

从上下文中提取时间、位置、传感器、行为、用户状态等多维度特征，
为场景分类模型提供结构化输入。

特征类型：
1. 时间特征 - 小时、星期、节假日、时间段
2. 位置特征 - 位置类型、GPS、地理围栏
3. 传感器特征 - 心率、步数、环境数据（对接 M6）
4. 行为特征 - 活跃应用、操作序列、交互频率
5. 用户状态特征 - 忙碌/空闲、疲劳程度、情绪倾向
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


# ---------------------------------------------------------------------------
# 中国法定节假日（简化版，2024-2026 主要节假日）
# 格式: "MM-DD" 或特殊调休日
# ---------------------------------------------------------------------------
_CHINESE_HOLIDAYS_2024: set[str] = {
    "01-01",  # 元旦
    "02-10", "02-11", "02-12", "02-13", "02-14", "02-15", "02-16", "02-17",  # 春节
    "04-04", "04-05", "04-06",  # 清明
    "05-01", "05-02", "05-03", "05-04", "05-05",  # 劳动节
    "06-10",  # 端午
    "09-15", "09-16", "09-17",  # 中秋
    "10-01", "10-02", "10-03", "10-04", "10-05", "10-06", "10-07",  # 国庆
}

_CHINESE_HOLIDAYS_2025: set[str] = {
    "01-01",  # 元旦
    "01-28", "01-29", "01-30", "01-31", "02-01", "02-02", "02-03", "02-04",  # 春节
    "04-04", "04-05", "04-06",  # 清明
    "05-01", "05-02", "05-03", "05-04", "05-05",  # 劳动节
    "05-31", "06-01", "06-02",  # 端午
    "10-01", "10-02", "10-03", "10-04", "10-05", "10-06", "10-07", "10-08",  # 国庆中秋
}

_CHINESE_HOLIDAYS_2026: set[str] = {
    "01-01",  # 元旦
    "02-16", "02-17", "02-18", "02-19", "02-20", "02-21", "02-22", "02-23",  # 春节
    "04-04", "04-05", "04-06",  # 清明
    "05-01", "05-02", "05-03",  # 劳动节
    "06-19", "06-20", "06-21",  # 端午
    "09-25", "09-26", "09-27",  # 中秋
    "10-01", "10-02", "10-03", "10-04", "10-05", "10-06", "10-07",  # 国庆
}

_CHINESE_HOLIDAYS_BY_YEAR: dict[int, set[str]] = {
    2024: _CHINESE_HOLIDAYS_2024,
    2025: _CHINESE_HOLIDAYS_2025,
    2026: _CHINESE_HOLIDAYS_2026,
}

# 调休上班的周末（补班日）
_MAKEUP_WORKDAYS: set[str] = {
    # 2024
    "2024-02-04", "2024-02-18",  # 春节调休
    "2024-04-07",  # 清明调休
    "2024-04-28", "2024-05-11",  # 劳动节调休
    "2024-09-14", "2024-09-29", "2024-10-12",  # 中秋国庆调休
    # 2025
    "2025-01-26", "2025-02-08",  # 春节调休
    "2025-04-27",  # 劳动节调休
    "2025-09-28", "2025-10-11",  # 国庆调休
    # 2026
    "2026-02-14", "2026-02-27",  # 春节调休
    "2026-04-26",  # 劳动节调休
    "2026-09-20",  # 中秋调休
    "2026-10-10",  # 国庆调休
}


# ---------------------------------------------------------------------------
# 时间段定义
# ---------------------------------------------------------------------------
TIME_PERIODS = {
    "early_morning": (5, 8),    # 凌晨/早晨 5:00-8:00
    "morning": (8, 12),          # 上午 8:00-12:00
    "noon": (12, 14),            # 中午 12:00-14:00
    "afternoon": (14, 18),       # 下午 14:00-18:00
    "evening": (18, 22),         # 傍晚/晚上 18:00-22:00
    "late_night": (22, 5),       # 深夜 22:00-5:00
}


# ---------------------------------------------------------------------------
# 特征向量数据类
# ---------------------------------------------------------------------------

@dataclass
class FeatureVector:
    """多模态特征向量.

    包含从上下文中提取的所有特征，用于场景分类。
    """

    # 时间特征
    hour: int = 0
    weekday: int = 0           # 0=周一, 6=周日
    day_of_month: int = 1
    month: int = 1
    is_weekend: bool = False
    is_holiday: bool = False
    time_period: str = "morning"

    # 位置特征
    location_type: str = "unknown"   # home/office/outdoor/commuting/unknown
    gps_lat: float | None = None
    gps_lng: float | None = None
    geofence_match: str = ""

    # 传感器特征（对接 M6）
    heart_rate: int | None = None
    steps: int | None = None
    motion_state: str = "still"      # still/walking/running/driving
    ambient_noise: float | None = None
    ambient_light: float | None = None
    device_connections: list[str] = field(default_factory=list)

    # 行为特征
    active_app: str = ""
    recent_actions: list[str] = field(default_factory=list)
    interaction_frequency: float = 0.0  # 每分钟交互次数
    conversation_topic: str = ""

    # 用户状态特征
    busyness_level: float = 0.0   # 0.0-1.0 忙碌程度
    fatigue_level: float = 0.0    # 0.0-1.0 疲劳程度
    mood_tendency: str = "neutral"  # positive/neutral/negative

    # 原始上下文（用于调试和扩展）
    raw_context: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """转换为字典."""
        return {
            "time": {
                "hour": self.hour,
                "weekday": self.weekday,
                "day_of_month": self.day_of_month,
                "month": self.month,
                "is_weekend": self.is_weekend,
                "is_holiday": self.is_holiday,
                "time_period": self.time_period,
            },
            "location": {
                "location_type": self.location_type,
                "gps_lat": self.gps_lat,
                "gps_lng": self.gps_lng,
                "geofence_match": self.geofence_match,
            },
            "sensor": {
                "heart_rate": self.heart_rate,
                "steps": self.steps,
                "motion_state": self.motion_state,
                "ambient_noise": self.ambient_noise,
                "ambient_light": self.ambient_light,
                "device_connections": self.device_connections,
            },
            "behavior": {
                "active_app": self.active_app,
                "recent_actions": self.recent_actions,
                "interaction_frequency": self.interaction_frequency,
                "conversation_topic": self.conversation_topic,
            },
            "user_state": {
                "busyness_level": self.busyness_level,
                "fatigue_level": self.fatigue_level,
                "mood_tendency": self.mood_tendency,
            },
        }

    def to_flat_dict(self) -> dict[str, Any]:
        """转换为扁平化字典（用于分类器输入）."""
        return {
            # 时间特征
            "hour": self.hour,
            "weekday": self.weekday,
            "day_of_month": self.day_of_month,
            "month": self.month,
            "is_weekend": int(self.is_weekend),
            "is_holiday": int(self.is_holiday),
            "time_period": self.time_period,
            # 位置特征
            "location_type": self.location_type,
            "geofence_match": self.geofence_match,
            # 传感器特征
            "motion_state": self.motion_state,
            "has_heart_rate": int(self.heart_rate is not None),
            "has_steps": int(self.steps is not None),
            # 行为特征
            "active_app": self.active_app,
            "interaction_frequency": self.interaction_frequency,
            "conversation_topic": self.conversation_topic,
            # 用户状态
            "busyness_level": self.busyness_level,
            "fatigue_level": self.fatigue_level,
            "mood_tendency": self.mood_tendency,
        }


# ---------------------------------------------------------------------------
# 特征提取器
# ---------------------------------------------------------------------------

class FeatureExtractor:
    """多模态特征提取器.

    从上下文中提取时间、位置、传感器、行为、用户状态等多维度特征。

    使用方式::

        extractor = FeatureExtractor()
        features = extractor.extract(context)
        print(features.time_period, features.location_type)
    """

    def __init__(self) -> None:
        """初始化特征提取器."""
        self._holiday_cache: dict[str, bool] = {}

    # -------------------------------------------------------------------
    # 主提取方法
    # -------------------------------------------------------------------

    def extract(
        self,
        context: dict[str, Any] | None = None,
        timestamp: float | None = None,
    ) -> FeatureVector:
        """从上下文中提取特征向量.

        Args:
            context: 上下文数据字典
            timestamp: 时间戳（秒），None 则使用当前时间

        Returns:
            FeatureVector 特征向量
        """
        ctx = context or {}
        ts = timestamp if timestamp is not None else time.time()
        dt = datetime.fromtimestamp(ts)

        features = FeatureVector(raw_context=ctx)

        # 1. 时间特征
        self._extract_time_features(features, dt)

        # 2. 位置特征
        self._extract_location_features(features, ctx)

        # 3. 传感器特征
        self._extract_sensor_features(features, ctx)

        # 4. 行为特征
        self._extract_behavior_features(features, ctx)

        # 5. 用户状态特征
        self._extract_user_state_features(features, ctx, dt)

        return features

    # -------------------------------------------------------------------
    # 时间特征提取
    # -------------------------------------------------------------------

    def _extract_time_features(self, features: FeatureVector, dt: datetime) -> None:
        """提取时间特征.

        Args:
            features: 特征向量（原地修改）
            dt:  datetime 对象
        """
        features.hour = dt.hour
        features.weekday = dt.weekday()
        features.day_of_month = dt.day
        features.month = dt.month
        features.is_weekend = dt.weekday() >= 5
        features.is_holiday = self._is_holiday(dt)
        features.time_period = self._get_time_period(dt.hour)

    def _get_time_period(self, hour: int) -> str:
        """获取时间段名称.

        Args:
            hour: 小时（0-23）

        Returns:
            时间段 key
        """
        for period, (start, end) in TIME_PERIODS.items():
            if start < end:
                if start <= hour < end:
                    return period
            else:
                # 跨午夜的时段（如 late_night: 22-5）
                if hour >= start or hour < end:
                    return period
        return "morning"

    def _is_holiday(self, dt: datetime) -> bool:
        """判断是否为中国法定节假日.

        Args:
            dt: datetime 对象

        Returns:
            True 表示是节假日
        """
        date_key = dt.strftime("%Y-%m-%d")
        if date_key in self._holiday_cache:
            return self._holiday_cache[date_key]

        # 调休上班日，即使是周末也不算假期
        if date_key in _MAKEUP_WORKDAYS:
            self._holiday_cache[date_key] = False
            return False

        mmdd = dt.strftime("%m-%d")
        holidays = _CHINESE_HOLIDAYS_BY_YEAR.get(dt.year, set())
        is_holiday = mmdd in holidays

        # 周末也算休息日（除非是调休上班日）
        if not is_holiday and dt.weekday() >= 5:
            is_holiday = True

        self._holiday_cache[date_key] = is_holiday
        return is_holiday

    # -------------------------------------------------------------------
    # 位置特征提取
    # -------------------------------------------------------------------

    def _extract_location_features(
        self,
        features: FeatureVector,
        ctx: dict[str, Any],
    ) -> None:
        """提取位置特征.

        Args:
            features: 特征向量（原地修改）
            ctx: 上下文数据
        """
        # 位置类型（直接从上下文获取或推断）
        location = ctx.get("location", {})
        if isinstance(location, dict):
            features.location_type = location.get("type", "unknown")
            features.gps_lat = location.get("lat")
            features.gps_lng = location.get("lng")
            features.geofence_match = location.get("geofence", "")
        elif isinstance(location, str):
            features.location_type = location

        # 如果位置未知，根据时间和行为推断
        if features.location_type == "unknown":
            features.location_type = self._infer_location_type(ctx, features)

    def _infer_location_type(
        self,
        ctx: dict[str, Any],
        features: FeatureVector,
    ) -> str:
        """根据上下文推断位置类型.

        Args:
            ctx: 上下文数据
            features: 已提取的特征

        Returns:
            推断的位置类型
        """
        active_app = ctx.get("active_app", "")
        motion = ctx.get("motion_state", "")

        # 运动状态是 driving/walking 可能在通勤
        if motion in ("driving", "in_vehicle"):
            return "commuting"

        # 工作日工作时间，活跃应用是开发工具 -> 办公室
        if not features.is_weekend and 9 <= features.hour < 18:
            if any(app in active_app.lower() for app in
                   ["code", "vscode", "idea", "eclipse", "office", "excel", "word"]):
                return "office"

        # 深夜或清晨 -> 家
        if features.hour >= 22 or features.hour < 7:
            return "home"

        # 周末且有运动 -> 户外
        if features.is_weekend and motion in ("walking", "running"):
            return "outdoor"

        return "unknown"

    # -------------------------------------------------------------------
    # 传感器特征提取
    # -------------------------------------------------------------------

    def _extract_sensor_features(
        self,
        features: FeatureVector,
        ctx: dict[str, Any],
    ) -> None:
        """提取传感器特征（对接 M6 健康模块）.

        Args:
            features: 特征向量（原地修改）
            ctx: 上下文数据
        """
        sensor = ctx.get("sensor", {})
        if isinstance(sensor, dict):
            features.heart_rate = sensor.get("heart_rate")
            features.steps = sensor.get("steps")
            features.motion_state = sensor.get("motion_state", "still")
            features.ambient_noise = sensor.get("ambient_noise")
            features.ambient_light = sensor.get("ambient_light")
            features.device_connections = sensor.get("devices", [])

        # 兼容顶层字段
        if features.heart_rate is None and "heart_rate" in ctx:
            features.heart_rate = ctx["heart_rate"]
        if features.steps is None and "steps" in ctx:
            features.steps = ctx["steps"]
        if features.motion_state == "still" and "motion_state" in ctx:
            features.motion_state = ctx["motion_state"]

    # -------------------------------------------------------------------
    # 行为特征提取
    # -------------------------------------------------------------------

    def _extract_behavior_features(
        self,
        features: FeatureVector,
        ctx: dict[str, Any],
    ) -> None:
        """提取行为特征.

        Args:
            features: 特征向量（原地修改）
            ctx: 上下文数据
        """
        # 当前活跃应用
        features.active_app = ctx.get("active_app", "")

        # 最近操作序列
        recent = ctx.get("recent_actions", [])
        if isinstance(recent, list):
            features.recent_actions = recent[:20]  # 最多保留 20 条

        # 交互频率
        freq = ctx.get("interaction_frequency", 0.0)
        if isinstance(freq, (int, float)):
            features.interaction_frequency = float(freq)

        # 对话主题（从最近消息或用户输入推断）
        features.conversation_topic = ctx.get("conversation_topic", "")
        if not features.conversation_topic and "text" in ctx:
            features.conversation_topic = self._infer_topic(ctx["text"])

    def _infer_topic(self, text: str) -> str:
        """简单从文本推断对话主题.

        基于关键词的轻量级主题分类，作为更复杂 NLP 的降级方案。

        Args:
            text: 用户输入文本

        Returns:
            主题标签
        """
        text_lower = text.lower()

        topic_keywords = {
            "work": ["工作", "项目", "代码", "开发", "编程", "会议", "邮件", "report", "code", "bug"],
            "study": ["学习", "考试", "复习", "课程", "知识", "题目", "作业", "learn", "study"],
            "life": ["吃饭", "睡觉", "买菜", "做饭", "生活", "家务", "生活"],
            "entertainment": ["游戏", "电影", "音乐", "追剧", "综艺", "game", "movie", "music"],
            "health": ["运动", "健身", "跑步", "减肥", "健康", "身体", "exercise", "health"],
            "social": ["朋友", "聚会", "约会", "聊天", "社交", "social", "friend"],
            "travel": ["旅行", "出差", "机票", "酒店", "旅游", "travel", "trip"],
            "creative": ["写作", "创作", "画画", "设计", "灵感", "write", "create", "design"],
        }

        scores: dict[str, int] = {}
        for topic, keywords in topic_keywords.items():
            score = sum(1 for kw in keywords if kw in text_lower)
            if score > 0:
                scores[topic] = score

        if scores:
            return max(scores, key=scores.get)

        return "general"

    # -------------------------------------------------------------------
    # 用户状态特征提取
    # -------------------------------------------------------------------

    def _extract_user_state_features(
        self,
        features: FeatureVector,
        ctx: dict[str, Any],
        dt: datetime,
    ) -> None:
        """提取用户状态特征.

        Args:
            features: 特征向量（原地修改）
            ctx: 上下文数据
            dt: 当前时间
        """
        # 忙碌程度（直接或推断）
        if "busyness_level" in ctx:
            features.busyness_level = float(ctx["busyness_level"])
        else:
            features.busyness_level = self._infer_busyness(features, ctx)

        # 疲劳程度（基于使用时长和时段推断）
        if "fatigue_level" in ctx:
            features.fatigue_level = float(ctx["fatigue_level"])
        else:
            features.fatigue_level = self._infer_fatigue(features, ctx, dt)

        # 情绪倾向
        if "mood" in ctx:
            features.mood_tendency = ctx["mood"]
        elif "mood_tendency" in ctx:
            features.mood_tendency = ctx["mood_tendency"]
        else:
            features.mood_tendency = self._infer_mood(ctx)

    def _infer_busyness(
        self,
        features: FeatureVector,
        ctx: dict[str, Any],
    ) -> float:
        """推断用户忙碌程度（0.0-1.0）.

        Args:
            features: 特征向量
            ctx: 上下文数据

        Returns:
            忙碌程度 0.0-1.0
        """
        score = 0.0

        # 工作日工作时间基础分
        if not features.is_weekend and 9 <= features.hour < 18:
            score += 0.5

        # 高交互频率
        if features.interaction_frequency > 10:
            score += 0.3
        elif features.interaction_frequency > 5:
            score += 0.15

        # 工作相关应用
        work_apps = ["code", "vscode", "idea", "office", "excel", "word", "outlook"]
        if any(app in features.active_app.lower() for app in work_apps):
            score += 0.2

        # 运动状态下忙碌度降低
        if features.motion_state in ("walking", "running"):
            score -= 0.2

        return max(0.0, min(1.0, score))

    def _infer_fatigue(
        self,
        features: FeatureVector,
        ctx: dict[str, Any],
        dt: datetime,
    ) -> float:
        """推断用户疲劳程度（0.0-1.0）.

        基于使用时长、时段、步数等因素综合推断。

        Args:
            features: 特征向量
            ctx: 上下文数据
            dt: 当前时间

        Returns:
            疲劳程度 0.0-1.0
        """
        score = 0.0

        # 时间因素：深夜疲劳度高
        if features.hour >= 23 or features.hour < 6:
            score += 0.6
        elif features.hour >= 22:
            score += 0.4
        elif features.hour >= 20:
            score += 0.2

        # 下午 2-4 点容易犯困
        if 14 <= features.hour < 16:
            score += 0.2

        # 高步数（运动后疲劳）
        if features.steps is not None and features.steps > 10000:
            score += 0.3
        elif features.steps is not None and features.steps > 5000:
            score += 0.15

        # 高心率（可能疲劳）
        if features.heart_rate is not None and features.heart_rate > 100:
            score += 0.2

        # 低交互频率可能在休息
        if features.interaction_frequency < 1:
            score -= 0.2

        return max(0.0, min(1.0, score))

    def _infer_mood(self, ctx: dict[str, Any]) -> str:
        """推断用户情绪倾向.

        基于对话内容关键词的简单情感分析。

        Args:
            ctx: 上下文数据

        Returns:
            positive/neutral/negative
        """
        text = ctx.get("text", "")
        if not text:
            return "neutral"

        text_lower = text.lower()

        positive_words = [
            "开心", "高兴", "快乐", "棒", "好", "喜欢", "爱", "赞",
            "成功", "顺利", "满足", "幸福", "兴奋", "期待",
            "happy", "great", "good", "love", "nice", "excellent",
        ]
        negative_words = [
            "难过", "伤心", "生气", "烦", "累", "压力", "焦虑",
            "失望", "痛苦", "悲伤", "郁闷", "讨厌", "害怕",
            "sad", "angry", "tired", "bad", "worried", "stressed",
        ]

        pos_count = sum(1 for w in positive_words if w in text_lower)
        neg_count = sum(1 for w in negative_words if w in text_lower)

        if pos_count > neg_count:
            return "positive"
        elif neg_count > pos_count:
            return "negative"
        else:
            return "neutral"

    # -------------------------------------------------------------------
    # 工具方法
    # -------------------------------------------------------------------

    def get_feature_names(self) -> list[str]:
        """获取所有特征名称列表.

        Returns:
            特征名称列表
        """
        return [
            "hour", "weekday", "day_of_month", "month",
            "is_weekend", "is_holiday", "time_period",
            "location_type", "geofence_match",
            "motion_state", "has_heart_rate", "has_steps",
            "active_app", "interaction_frequency", "conversation_topic",
            "busyness_level", "fatigue_level", "mood_tendency",
        ]

    def get_feature_categories(self) -> dict[str, list[str]]:
        """获取按类别分组的特征名称.

        Returns:
            类别 -> 特征名称列表 的字典
        """
        return {
            "time": ["hour", "weekday", "day_of_month", "month",
                     "is_weekend", "is_holiday", "time_period"],
            "location": ["location_type", "geofence_match"],
            "sensor": ["motion_state", "has_heart_rate", "has_steps"],
            "behavior": ["active_app", "interaction_frequency", "conversation_topic"],
            "user_state": ["busyness_level", "fatigue_level", "mood_tendency"],
        }
