"""
记忆回响对比模块

通过对比过去与现在的状态，生成成长洞察和感悟。
模拟"时空对话"效果，让用户看到自己的变化轨迹。

由于没有 LLM，采用模板化 + 随机化策略生成回响内容，
保证每次生成略有不同但主题一致。
"""

from __future__ import annotations

import random
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional

from .database import GrowthDatabase, dict_to_json, json_to_dict
from .models import MemoryEchoState

# 分类映射
CATEGORY_MAP: Dict[str, str] = {
    "emotion": "情绪",
    "decision": "决策",
    "social": "社交",
    "growth": "成长",
    "work": "工作",
    "life": "生活",
}

# 成长感悟模板库 - 按分类组织
GROWTH_TEMPLATES: Dict[str, List[str]] = {
    "emotion": [
        "曾经的你会因{trigger}而{past_emotion}，如今的你学会了用{present_pattern}去面对。情绪没有好坏，每一种感受都是成长的刻度。",
        "从{past_emotion}到{present_emotion}，你走过了一段不短的路。那些曾经让你辗转反侧的事，如今已能淡然处之——这就是时间给你的礼物。",
        "情绪的潮汐有起有落。回望过去，你会发现自己已经不再是那个会被{trigger}轻易左右的人了。内心的锚，越来越稳。",
        "你不再试图压抑{past_emotion}，而是学会了与它共处。这种从对抗到和解的转变，是情商提升最有力的证明。",
    ],
    "decision": [
        "过去面对{trigger}时，你倾向于{past_pattern}；而现在，你选择了{present_pattern}。决策方式的演变，映射着认知的升级。",
        "从犹豫到果断，从{past_pattern}到{present_pattern}——每一个决策风格的转变背后，都是无数次试错后的沉淀。",
        "你越来越清楚什么值得投入，什么应该放手。这种取舍的智慧，是过去的自己无法想象的成长。",
        "当初那个在十字路口徘徊的你，如今已能坚定地选择方向。不是因为答案变简单了，而是你变得更了解自己了。",
    ],
    "social": [
        "曾经在人群中你感到{past_emotion}，如今的你找到了属于自己的社交节奏。真正的成熟，是不再勉强自己融入不适合的圈子。",
        "从{past_pattern}到{present_pattern}，你对关系的理解越来越深刻。质量胜于数量，这句话你如今有了切身体会。",
        "你学会了设立边界，也学会了珍惜真正重要的人。这种在人际中保持自我的能力，是成长的重要里程碑。",
        "过去你可能会为了{trigger}而委屈自己，现在的你明白，健康的关系从不需要刻意讨好。",
    ],
    "growth": [
        "从{past_pattern}到{present_pattern}，你用行动证明了成长没有终点。每一步看似微小的改变，累积起来就是蜕变。",
        "回望这段路，你会惊讶于自己已经走了这么远。{trigger}曾是你的瓶颈，如今已成为你向上攀登的台阶。",
        "成长不是一蹴而就的爆发，而是日复一日的坚持。从{past_emotion}到{present_emotion}，你正在成为更好的自己。",
        "你不再害怕{trigger}，因为你知道每一次挑战都是成长的契机。这种心态的转变，比任何技能提升都更有价值。",
    ],
    "work": [
        "从{past_pattern}式的工作方式，到如今{present_pattern}的方法论，你对工作的理解已经上了一个台阶。",
        "曾经{trigger}让你感到{past_emotion}，现在的你更懂得如何在工作中找到节奏和意义。",
        "你不再是那个只会埋头苦干的人了。从执行者到思考者的转变，是职业生涯中最宝贵的跃迁。",
        "工作的意义，从{trigger}变成了更深层的价值实现。这种认知的升级，会带你走得更远。",
    ],
    "life": [
        "生活的节奏从{past_pattern}变成了{present_pattern}，你越来越懂得如何与自己相处，如何在平凡中找到意义。",
        "从对生活的{past_emotion}，到如今的{present_emotion}——你找到了属于自己的生活哲学。",
        "{trigger}曾让你迷茫，但走过那段路后你发现，生活没有标准答案，每个人都在用自己的方式定义幸福。",
        "你不再急于追赶什么，而是学会了享受当下。这种从容，是岁月给你最好的礼物。",
    ],
}

# 回响标题模板
TITLE_TEMPLATES: List[str] = [
    "时光回响：从{past}到{present}",
    "跨越时空的对话：{topic}",
    "成长的刻度：{topic}篇",
    "回响·{topic}：原来我已经走了这么远",
    "潮汐记忆·{topic}回响",
]

# 补充内容模板
CONTENT_TEMPLATES: List[str] = [
    "这是一段关于{topic}的记忆回响。过去的你和现在的你，在这一刻相遇。\n\n变化不一定总是显而易见的，但当你回头看时，会发现每一步都算数。",
    "你可能已经忘记了当初的自己是什么样子。让这段回响提醒你——你比自己想象的成长了更多。\n\n感谢那些{trigger}的时刻，它们塑造了今天的你。",
    "记忆的潮水涌来，带来了过去的碎片。将它们与当下对照，你会看到一条清晰的成长轨迹。\n\n{topic}只是其中一个侧面，但每个侧面都在诉说着同一个事实：你在变得更好。",
]


def _gen_id() -> str:
    """生成回响ID"""
    return f"echo_{uuid.uuid4().hex[:16]}"


def _row_to_echo(row: Dict[str, Any]) -> Dict[str, Any]:
    """将数据库行转为回响字典"""
    return {
        "id": row["id"],
        "title": row["title"],
        "category": row["category"],
        "category_text": row["category_text"],
        "before": json_to_dict(row["before_json"]),
        "after": json_to_dict(row["after_json"]),
        "growth": row["growth"],
        "content": row["content"],
        "created_at": row["created_at"],
    }


def _generate_growth_insight(
    category: str,
    before: MemoryEchoState,
    after: MemoryEchoState,
) -> str:
    """
    基于 before 和 after 的差异，生成成长感悟文本。

    使用模板 + 随机化策略，保证内容有差异但主题一致。
    """
    templates = GROWTH_TEMPLATES.get(category, GROWTH_TEMPLATES["growth"])
    template = random.choice(templates)

    past_emotion = before.emotion or "迷茫"
    present_emotion = after.emotion or "坚定"
    past_pattern = before.pattern or "被动应对"
    present_pattern = after.pattern or "主动把握"
    trigger = before.tags[0] if before.tags else "挑战"
    topic = CATEGORY_MAP.get(category, "成长")

    return template.format(
        past_emotion=past_emotion,
        present_emotion=present_emotion,
        past_pattern=past_pattern,
        present_pattern=present_pattern,
        trigger=trigger,
        topic=topic,
    )


def _generate_title(category: str, before: MemoryEchoState, after: MemoryEchoState) -> str:
    """生成回响标题"""
    template = random.choice(TITLE_TEMPLATES)
    past = before.title or "过去"
    present = after.title or "现在"
    topic = CATEGORY_MAP.get(category, "成长")
    return template.format(past=past, present=present, topic=topic)


def _generate_content(category: str, before: MemoryEchoState, after: MemoryEchoState) -> str:
    """生成补充内容"""
    template = random.choice(CONTENT_TEMPLATES)
    topic = CATEGORY_MAP.get(category, "成长")
    trigger = before.tags[0] if before.tags else "成长"
    return template.format(topic=topic, trigger=trigger)


class EchoManager:
    """
    记忆回响管理器

    负责回响的生成、查询、删除等功能。
    使用模板化 + 随机化策略生成成长感悟内容。
    """

    def __init__(self, db: GrowthDatabase = None):
        """
        初始化记忆回响管理器

        Args:
            db: 数据库实例，为 None 时使用默认单例
        """
        self._db = db or GrowthDatabase.get_instance()

    # ============================================================
    # 查询操作
    # ============================================================

    def list_echoes(
        self,
        page: int = 1,
        size: int = 20,
        category: Optional[str] = None,
        keyword: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        分页查询记忆回响列表。

        Args:
            page: 页码，从1开始
            size: 每页数量
            category: 分类筛选
            keyword: 关键词搜索（标题和内容）

        Returns:
            分页结果
        """
        conditions = []
        params: List[Any] = []

        if category:
            conditions.append("category = ?")
            params.append(category)

        if keyword:
            conditions.append("(title LIKE ? OR growth LIKE ? OR content LIKE ?)")
            like_pattern = f"%{keyword}%"
            params.extend([like_pattern, like_pattern, like_pattern])

        where_clause = ""
        if conditions:
            where_clause = "WHERE " + " AND ".join(conditions)

        # 总数
        count_sql = f"SELECT COUNT(*) as cnt FROM growth_memory_echoes {where_clause}"
        count_row = self._db.query_one(count_sql, tuple(params))
        total = count_row["cnt"] if count_row else 0

        # 分页数据
        offset = (page - 1) * size
        query_sql = f"""
            SELECT * FROM growth_memory_echoes
            {where_clause}
            ORDER BY created_at DESC
            LIMIT {size} OFFSET {offset}
        """
        rows = self._db.query_all(query_sql, tuple(params))

        items = [_row_to_echo(row) for row in rows]
        total_pages = (total + size - 1) // size if size > 0 else 0

        return {
            "items": items,
            "total": total,
            "page": page,
            "size": size,
            "total_pages": total_pages,
        }

    def get_echo(self, echo_id: str) -> Optional[Dict[str, Any]]:
        """
        获取单条回响详情。

        Args:
            echo_id: 回响ID

        Returns:
            回响数据，不存在返回 None
        """
        row = self._db.query_one(
            "SELECT * FROM growth_memory_echoes WHERE id = ?",
            (echo_id,),
        )
        if not row:
            return None
        return _row_to_echo(row)

    # ============================================================
    # 生成与删除
    # ============================================================

    def generate_echo(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """
        生成记忆回响。

        基于 before 和 after 状态的差异，使用模板生成成长感悟。

        Args:
            data: 生成参数，包含 type、before、after 等

        Returns:
            生成的回响数据
        """
        category = data.get("type", "growth")
        if category not in CATEGORY_MAP:
            category = "growth"

        category_text = CATEGORY_MAP.get(category, "成长")

        # 解析 before 和 after
        before_data = data.get("before") or {}
        after_data = data.get("after") or {}

        before = MemoryEchoState(**before_data) if isinstance(before_data, dict) else before_data
        after = MemoryEchoState(**after_data) if isinstance(after_data, dict) else after_data

        # 确保是 MemoryEchoState 对象
        if not isinstance(before, MemoryEchoState):
            before = MemoryEchoState()
        if not isinstance(after, MemoryEchoState):
            after = MemoryEchoState()

        # 生成内容
        title = _generate_title(category, before, after)
        growth_insight = _generate_growth_insight(category, before, after)
        content = _generate_content(category, before, after)

        # 存储到数据库
        echo_id = _gen_id()
        now = datetime.now().isoformat()

        self._db.execute(
            """
            INSERT INTO growth_memory_echoes
            (id, title, category, category_text, before_json, after_json, growth, content, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                echo_id,
                title,
                category,
                category_text,
                dict_to_json(before.model_dump()),
                dict_to_json(after.model_dump()),
                growth_insight,
                content,
                now,
            ),
        )

        return self.get_echo(echo_id) or {}

    def delete_echo(self, echo_id: str) -> bool:
        """
        删除回响。

        Args:
            echo_id: 回响ID

        Returns:
            是否删除成功
        """
        existing = self.get_echo(echo_id)
        if not existing:
            return False

        self._db.execute(
            "DELETE FROM growth_memory_echoes WHERE id = ?",
            (echo_id,),
        )
        return True


# vim: set et ts=4 sw=4:
