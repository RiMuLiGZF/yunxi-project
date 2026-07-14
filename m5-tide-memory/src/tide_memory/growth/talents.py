"""
心智天赋树模块

管理天赋树的定义、升级、重置、点数等功能。
四分支天赋树：心智、稳态、创造、阅历。
每个分支 8 个节点，3 层结构。
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any, Dict, List, Optional

from .database import GrowthDatabase
from .models import TalentNode


class TalentManager:
    """
    天赋树管理器

    负责天赋节点的查询、升级、重置，以及天赋点数的管理。
    """

    def __init__(self, db: GrowthDatabase = None) -> None:
        """
        初始化天赋管理器

        Args:
            db: 数据库实例，为 None 时使用默认单例
        """
        self._db = db or GrowthDatabase.get_instance()

    # ============================================================
    # 天赋树查询
    # ============================================================

    def get_talent_tree(self, tree: Optional[str] = None) -> Dict[str, Any]:
        """
        获取天赋树完整数据

        Args:
            tree: 指定天赋树分支（mind/emotion/creativity/experience），为 None 返回全部

        Returns:
            包含 nodes、connections、points、stats 的完整天赋树数据
        """
        # 查询天赋定义 + 用户状态
        sql = """
            SELECT t.*,
                   COALESCE(ut.level, 0) as user_level,
                   COALESCE(ut.status, 'locked') as user_status
            FROM growth_talents t
            LEFT JOIN growth_user_talents ut ON t.id = ut.talent_id
        """
        params: tuple = ()
        if tree:
            sql += " WHERE t.tree = ?"
            params = (tree,)
        sql += " ORDER BY t.tree, t.layer, t.sort_order, t.id"

        rows = self._db.query_all(sql, params)

        nodes = []
        connections = []
        spent_points = 0

        for row in rows:
            children_ids = json.loads(row["children_ids"]) if row["children_ids"] else []
            level = row["user_level"]
            max_level = row["max_level"]

            # 计算状态：如果有等级则为 unlocked
            status = "unlocked" if level > 0 else "locked"

            node = {
                "id": row["id"],
                "name": row["name"],
                "branch": row["branch"],
                "description": row["description"],
                "status": status,
                "level": level,
                "max_level": max_level,
                "parent_id": row["parent_id"] or None,
                "children_ids": children_ids,
                "tree": row["tree"],
                "point_cost": row["point_cost"],
                "layer": row["layer"],
            }
            nodes.append(node)

            # 累计已消耗点数
            spent_points += level * row["point_cost"]

            # 生成连接关系
            for child_id in children_ids:
                connections.append({
                    "from": row["id"],
                    "to": child_id,
                })

        # 获取点数信息
        available_points = self.get_available_points()
        total_points = available_points + spent_points

        # 统计
        total_nodes = len(nodes)
        unlocked_nodes = sum(1 for n in nodes if n["level"] > 0)
        max_level_nodes = sum(1 for n in nodes if n["level"] >= n["max_level"])

        # 按分支统计
        by_branch = {}
        for node in nodes:
            branch = node["branch"]
            if branch not in by_branch:
                by_branch[branch] = {"total": 0, "unlocked": 0, "max_level": 0, "spent_points": 0}
            by_branch[branch]["total"] += 1
            if node["level"] > 0:
                by_branch[branch]["unlocked"] += 1
                by_branch[branch]["spent_points"] += node["level"] * node["point_cost"]
            if node["level"] >= node["max_level"]:
                by_branch[branch]["max_level"] += 1

        return {
            "nodes": nodes,
            "connections": connections,
            "available_points": available_points,
            "total_points": total_points,
            "spent_points": spent_points,
            "stats": {
                "total_nodes": total_nodes,
                "unlocked_nodes": unlocked_nodes,
                "max_level_nodes": max_level_nodes,
                "by_branch": by_branch,
            },
        }

    def get_talent_node(self, node_id: str) -> Optional[Dict[str, Any]]:
        """
        获取单个天赋节点详情

        Args:
            node_id: 节点ID

        Returns:
            节点详情，不存在返回 None
        """
        sql = """
            SELECT t.*,
                   COALESCE(ut.level, 0) as user_level,
                   COALESCE(ut.status, 'locked') as user_status
            FROM growth_talents t
            LEFT JOIN growth_user_talents ut ON t.id = ut.talent_id
            WHERE t.id = ?
        """
        row = self._db.query_one(sql, (node_id,))
        if not row:
            return None

        children_ids = json.loads(row["children_ids"]) if row["children_ids"] else []
        level = row["user_level"]

        return {
            "id": row["id"],
            "name": row["name"],
            "branch": row["branch"],
            "description": row["description"],
            "status": "unlocked" if level > 0 else "locked",
            "level": level,
            "max_level": row["max_level"],
            "parent_id": row["parent_id"] or None,
            "children_ids": children_ids,
            "tree": row["tree"],
            "point_cost": row["point_cost"],
            "layer": row["layer"],
        }

    # ============================================================
    # 天赋升级
    # ============================================================

    def upgrade_node(self, node_id: str) -> Dict[str, Any]:
        """
        升级天赋节点

        升级条件：
        1. 节点存在
        2. 未达到最大等级
        3. 有足够的天赋点数
        4. 父节点已解锁（非第一层节点）

        Args:
            node_id: 节点ID

        Returns:
            升级结果
        """
        # 获取节点信息
        node = self.get_talent_node(node_id)
        if not node:
            return {"success": False, "error": "not_found", "message": "天赋节点不存在"}

        # 检查是否已满级
        if node["level"] >= node["max_level"]:
            return {"success": False, "error": "max_level", "message": "已达到最大等级"}

        # 检查点数
        cost = node["point_cost"]
        available = self.get_available_points()
        if available < cost:
            return {
                "success": False,
                "error": "insufficient_points",
                "message": f"天赋点数不足（需要 {cost}，可用 {available}）",
            }

        # 检查父节点是否已解锁
        parent_id = node.get("parent_id")
        if parent_id:
            parent = self.get_talent_node(parent_id)
            if not parent or parent["level"] == 0:
                return {
                    "success": False,
                    "error": "parent_locked",
                    "message": "前置天赋未解锁",
                }

        # 执行升级：扣除点数 + 更新等级
        new_level = node["level"] + 1

        # 更新用户天赋状态
        sql = """
            INSERT OR REPLACE INTO growth_user_talents
            (talent_id, level, status, updated_at)
            VALUES (?, ?, 'unlocked', datetime('now'))
        """
        self._db.execute(sql, (node_id, new_level))

        # 扣除点数
        self._deduct_points(
            amount=cost,
            source="talent_upgrade",
            source_id=node_id,
            reason=f"升级天赋：{node['name']} (等级 {node['level']} → {new_level})",
        )

        # 返回更新后的节点信息
        updated_node = self.get_talent_node(node_id)

        return {
            "success": True,
            "node": updated_node,
            "cost": cost,
            "new_level": new_level,
            "remaining_points": self.get_available_points(),
        }

    # ============================================================
    # 天赋重置
    # ============================================================

    def reset_talents(self) -> Dict[str, Any]:
        """
        重置天赋树，返还全部已消耗的点数

        Returns:
            重置结果
        """
        # 计算已消耗点数
        tree_data = self.get_talent_tree()
        spent_points = tree_data["spent_points"]

        if spent_points == 0:
            return {
                "success": True,
                "refunded_points": 0,
                "message": "没有已消耗的天赋点",
            }

        # 清空用户天赋状态
        self._db.execute("DELETE FROM growth_user_talents")

        # 返还点数
        self.add_points(
            amount=spent_points,
            source="reset",
            source_id="talent_reset",
            reason=f"天赋重置 - 返还 {spent_points} 点",
        )

        return {
            "success": True,
            "refunded_points": spent_points,
            "available_points": self.get_available_points(),
            "message": f"天赋已重置，返还 {spent_points} 天赋点",
        }

    # ============================================================
    # 天赋点数管理
    # ============================================================

    def get_available_points(self) -> int:
        """
        获取当前可用天赋点数

        Returns:
            可用点数
        """
        row = self._db.query_one("SELECT COALESCE(SUM(amount), 0) as total FROM growth_points")
        return row["total"] if row else 0

    def add_points(self, amount: int, source: str = "manual",
                   source_id: str = "", reason: str = "") -> int:
        """
        增加天赋点数

        Args:
            amount: 点数数量（正数）
            source: 来源类型（initial/achievement/season/manual/reset）
            source_id: 来源ID
            reason: 原因说明

        Returns:
            新增后的总可用点数
        """
        if amount <= 0:
            return self.get_available_points()

        sql = """
            INSERT INTO growth_points (amount, source, source_id, reason)
            VALUES (?, ?, ?, ?)
        """
        self._db.execute(sql, (amount, source, source_id, reason))

        return self.get_available_points()

    def _deduct_points(self, amount: int, source: str = "spend",
                       source_id: str = "", reason: str = "") -> bool:
        """
        扣除天赋点数（内部方法）

        Args:
            amount: 扣除数量（正数）
            source: 消耗类型
            source_id: 消耗ID
            reason: 原因说明

        Returns:
            是否成功
        """
        if amount <= 0:
            return True

        available = self.get_available_points()
        if available < amount:
            return False

        # 用负数值记录扣除
        sql = """
            INSERT INTO growth_points (amount, source, source_id, reason)
            VALUES (?, ?, ?, ?)
        """
        self._db.execute(sql, (-amount, source, source_id, reason))

        return True

    def get_points_history(self, limit: int = 20) -> List[Dict[str, Any]]:
        """
        获取点数变动历史

        Args:
            limit: 返回记录数

        Returns:
            点数变动记录列表
        """
        sql = """
            SELECT * FROM growth_points
            ORDER BY created_at DESC, id DESC
            LIMIT ?
        """
        rows = self._db.query_all(sql, (limit,))
        return [dict(row) for row in rows]

    # ============================================================
    # 天赋统计
    # ============================================================

    def get_stats(self) -> Dict[str, Any]:
        """
        获取天赋系统统计数据

        Returns:
            天赋统计信息
        """
        tree_data = self.get_talent_tree()
        stats = tree_data["stats"]

        return {
            "total_nodes": stats["total_nodes"],
            "unlocked_nodes": stats["unlocked_nodes"],
            "max_level_nodes": stats["max_level_nodes"],
            "available_points": tree_data["available_points"],
            "total_points_earned": tree_data["total_points"],
            "spent_points": tree_data["spent_points"],
            "by_branch": stats["by_branch"],
            "unlock_rate": round(
                stats["unlocked_nodes"] / stats["total_nodes"] * 100, 1
            ) if stats["total_nodes"] > 0 else 0.0,
        }


# vim: set et ts=4 sw=4:
