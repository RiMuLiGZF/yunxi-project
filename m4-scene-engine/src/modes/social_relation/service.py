"""人际关系模式 - 业务逻辑层.

封装人际关系模式的核心业务逻辑，包括概览统计、关系图谱构建、
联系人管理、交往记录管理、社交提醒管理、情商课程等功能。
"""

from __future__ import annotations

import math
from typing import Any, Optional

from sqlalchemy.orm import Session

from src.modes.social_relation.repository import SocialRepository


# ---------------------------------------------------------------------------
# 颜色映射
# ---------------------------------------------------------------------------

_RELATION_COLOR_MAP: dict[str, str] = {
    "同事": "#52C41A",
    "同学": "#722ED1",
    "导师": "#FAAD14",
    "朋友": "#EB2F96",
    "家人": "#F5222D",
    "合作伙伴": "#FA8C16",
}


# ---------------------------------------------------------------------------
# 服务类
# ---------------------------------------------------------------------------


class SocialService:
    """人际关系业务服务类.

    提供人际关系模式的所有业务逻辑，
    调用 SocialRepository 进行数据访问。
    """

    def __init__(self, db: Session, user_id: str = "default") -> None:
        """初始化服务.

        Args:
            db: 数据库会话
            user_id: 用户 ID
        """
        self.repo = SocialRepository(db, user_id=user_id)

    # -----------------------------------------------------------------------
    # 概览统计
    # -----------------------------------------------------------------------

    def get_overview(self) -> dict[str, Any]:
        """获取人际关系概览数据.

        Returns:
            概览数据字典，包含 stats 和 top_contacts
        """
        contacts = self.repo.list_contacts()
        contact_dicts = [c.to_dict() for c in contacts]
        total_contacts = self.repo.count_contacts()
        total_interactions = self.repo.count_interactions()
        avg_closeness = int(self.repo.avg_importance())
        eq_data = self.repo.get_eq_score()
        week_interactions = self.repo.count_week_interactions()

        stats = {
            "total_contacts": total_contacts,
            "total_interactions": total_interactions,
            "avg_closeness": avg_closeness,
            "eq_score": eq_data["score"],
            "week_interactions": week_interactions,
            "streak_days": 15,  # 连续打卡天数（待实现）
        }
        top_contacts = sorted(
            contact_dicts, key=lambda x: x["closeness"], reverse=True
        )[:3]

        return {
            "stats": stats,
            "top_contacts": top_contacts,
        }

    # -----------------------------------------------------------------------
    # 关系图谱
    # -----------------------------------------------------------------------

    def build_relation_graph(self) -> dict[str, Any]:
        """根据联系人动态构建关系图谱.

        Returns:
            关系图谱数据，包含 nodes 和 links
        """
        contacts = self.repo.list_contacts()
        contact_dicts = [c.to_dict() for c in contacts]

        if not contact_dicts:
            return {"nodes": [], "links": []}

        # 中心节点（我）
        nodes: list[dict[str, Any]] = [
            {
                "id": 0,
                "name": "我",
                "x": 300,
                "y": 200,
                "level": 0,
                "color": "#1890FF",
            }
        ]
        links: list[dict[str, Any]] = []

        total = len(contact_dicts)
        radius_level1 = 120
        radius_level2 = 180

        for idx, c in enumerate(contact_dicts):
            # 按亲密度分级
            closeness = c.get("closeness", 50)
            level = 1 if closeness >= 75 else 2
            radius = radius_level1 if level == 1 else radius_level2

            # 均匀分布在圆周上
            angle = 2 * math.pi * idx / total - math.pi / 2
            x = int(300 + radius * math.cos(angle))
            y = int(200 + radius * math.sin(angle))

            color = _RELATION_COLOR_MAP.get(c.get("relationship_type", ""), "#13C2C2")
            relation_type = c.get("relationship_type", "其他")
            closeness = c.get("importance", c.get("closeness", 50))

            nodes.append({
                "id": c["id"],
                "name": c["name"],
                "x": x,
                "y": y,
                "level": level,
                "color": color,
                "closeness": closeness,
                "relation": relation_type,
                "avatar": c.get("avatar", ""),
            })
            links.append({
                "source": 0,
                "target": c["id"],
                "strength": round(closeness / 100, 2),
                "relation": relation_type,
            })

        return {"nodes": nodes, "links": links}

    # -----------------------------------------------------------------------
    # 联系人管理
    # -----------------------------------------------------------------------

    def list_contacts(
        self,
        relation: Optional[str] = None,
        tag: Optional[str] = None,
    ) -> list[dict[str, Any]]:
        """获取联系人列表.

        Args:
            relation: 按关系类型筛选
            tag: 按标签筛选

        Returns:
            联系人字典列表
        """
        contacts = self.repo.list_contacts(relation=relation, tag=tag)
        return [c.to_dict() for c in contacts]

    def get_contact_detail(self, contact_id: int) -> Optional[dict[str, Any]]:
        """获取联系人详情（含交往记录）.

        Args:
            contact_id: 联系人 ID

        Returns:
            联系人详情字典（含 contact 和 interactions），不存在返回 None
        """
        contact = self.repo.get_contact(contact_id)
        if not contact:
            return None

        interactions = self.repo.list_interactions(contact_id=contact_id)
        interaction_dicts = [i.to_dict() for i in interactions]

        return {
            "contact": contact.to_dict(),
            "interactions": interaction_dicts,
        }

    def create_contact(
        self,
        name: str,
        avatar: str = "👤",
        relation: str = "朋友",
        tags: Optional[list[str]] = None,
    ) -> dict[str, Any]:
        """创建联系人.

        Args:
            name: 姓名
            avatar: 头像 emoji
            relation: 关系类型
            tags: 标签列表

        Returns:
            创建后的联系人字典
        """
        contact = self.repo.create_contact(
            name=name, avatar=avatar, relation=relation, tags=tags,
        )
        return contact.to_dict()

    def update_contact(
        self,
        contact_id: int,
        update_data: dict[str, Any],
    ) -> Optional[dict[str, Any]]:
        """更新联系人信息.

        Args:
            contact_id: 联系人 ID
            update_data: 更新数据字典

        Returns:
            更新后的联系人字典，不存在返回 None
        """
        contact = self.repo.update_contact(contact_id, **update_data)
        return contact.to_dict() if contact else None

    def delete_contact(self, contact_id: int) -> bool:
        """删除联系人.

        Args:
            contact_id: 联系人 ID

        Returns:
            True 表示删除成功，False 表示不存在
        """
        return self.repo.delete_contact(contact_id)

    # -----------------------------------------------------------------------
    # 交往记录管理
    # -----------------------------------------------------------------------

    def list_interactions(
        self,
        contact_id: Optional[int] = None,
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        """获取交往记录列表.

        Args:
            contact_id: 按联系人筛选
            limit: 返回条数限制

        Returns:
            交往记录字典列表
        """
        interactions = self.repo.list_interactions(
            contact_id=contact_id, limit=limit,
        )
        return [i.to_dict() for i in interactions]

    def create_interaction(
        self,
        contact_id: int,
        contact_name: str,
        type: str,
        content: str,
        emotion: str = "neutral",
        duration_minutes: int = 0,
        location: str = "",
    ) -> dict[str, Any]:
        """创建交往记录（同时更新联系人统计）.

        Args:
            contact_id: 联系人 ID
            contact_name: 联系人姓名
            type: 交往类型
            content: 交往内容
            emotion: 心情
            duration_minutes: 时长（分钟）
            location: 地点

        Returns:
            创建后的交往记录字典
        """
        interaction = self.repo.create_interaction(
            contact_id=contact_id,
            contact_name=contact_name,
            type=type,
            content=content,
            emotion=emotion,
            duration_minutes=duration_minutes,
            location=location,
        )
        # 更新联系人统计
        self.repo.update_contact_stats(contact_id)
        return interaction.to_dict()

    # -----------------------------------------------------------------------
    # 社交提醒管理
    # -----------------------------------------------------------------------

    def list_reminders(self) -> list[dict[str, Any]]:
        """获取社交提醒列表.

        Returns:
            提醒字典列表
        """
        reminders = self.repo.list_reminders()
        return [r.to_dict() for r in reminders]

    def create_reminder(
        self,
        type: str,
        title: str,
        description: str = "",
        date: str = "",
        priority: str = "medium",
    ) -> dict[str, Any]:
        """创建社交提醒.

        Args:
            type: 提醒类型
            title: 提醒标题
            description: 提醒描述
            date: 日期字符串
            priority: 优先级

        Returns:
            创建后的提醒字典
        """
        reminder = self.repo.create_reminder(
            type=type, title=title, description=description,
            date=date, priority=priority,
        )
        return reminder.to_dict()

    def update_reminder_status(
        self,
        reminder_id: int,
        status: str,
    ) -> Optional[dict[str, Any]]:
        """更新提醒状态.

        Args:
            reminder_id: 提醒 ID
            status: 新状态

        Returns:
            更新后的提醒字典，不存在返回 None
        """
        reminder = self.repo.update_reminder_status(reminder_id, status)
        return reminder.to_dict() if reminder else None

    def delete_reminder(self, reminder_id: int) -> bool:
        """删除提醒.

        Args:
            reminder_id: 提醒 ID

        Returns:
            True 表示删除成功，False 表示不存在
        """
        return self.repo.delete_reminder(reminder_id)

    # -----------------------------------------------------------------------
    # 情商课程
    # -----------------------------------------------------------------------

    def list_eq_courses(self) -> list[dict[str, Any]]:
        """获取情商课程列表.

        Returns:
            情商课程字典列表
        """
        lessons = self.repo.list_eq_lessons()
        return [l.to_dict() for l in lessons]

    def get_eq_score(self) -> dict[str, Any]:
        """获取情商得分.

        Returns:
            情商评分字典
        """
        return self.repo.get_eq_score()
