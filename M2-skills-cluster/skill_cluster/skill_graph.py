from __future__ import annotations

"""Skill Graph - 技能图谱.

参考 2025-2026 Skill Composition 与 DAG 任务分解最新研究，
实现技能间的语义依赖关系图，支持自动组合发现、环路检测、
可达性分析和拓扑排序执行。

【模型迁移说明】
Pydantic 模型已迁移至 ``skill_cluster.models.extension``，
本文件保留 import 别名以保持向后兼容。

所有 ``from skill_cluster.skill_graph import Xxx`` 的导入方式继续有效。
"""

import collections
from typing import Any

import structlog

from skill_cluster.interfaces import SkillManifest

# ---- 从 models.extension 导入 Pydantic 模型（向后兼容） ----
from skill_cluster.models.extension import (
    ComposableChain,
    GraphEdge,
)

logger = structlog.get_logger()


class SkillGraph:
    """技能图谱.

    构建技能之间的依赖关系图（有向无环图），
    支持环路检测、自动组合发现、拓扑排序和可达性分析。
    """

    def __init__(self) -> None:
        self._nodes: dict[str, SkillManifest] = {}
        self._edges: list[GraphEdge] = []
        self._adj: dict[str, list[str]] = collections.defaultdict(list)
        self._rev_adj: dict[str, list[str]] = collections.defaultdict(list)

    # ---- 图谱构建 ----

    def add_skill(self, manifest: SkillManifest) -> None:
        """添加技能节点."""
        self._nodes[manifest.skill_id] = manifest
        # 依赖关系：a 依赖 b，意味着 b 是 a 的前置条件
        # 边方向：b -> a（b 必须在 a 之前执行）
        for dep in manifest.dependencies:
            self._add_edge(dep, manifest.skill_id, "depends_on")

    def remove_skill(self, skill_id: str) -> None:
        """移除技能节点及其关联边."""
        self._nodes.pop(skill_id, None)
        self._adj.pop(skill_id, None)
        self._rev_adj.pop(skill_id, None)
        self._edges = [
            e
            for e in self._edges
            if e.source != skill_id and e.target != skill_id
        ]
        # 清理其他节点中对该节点的引用
        for sid in list(self._adj.keys()):
            self._adj[sid] = [n for n in self._adj[sid] if n != skill_id]
        for sid in list(self._rev_adj.keys()):
            self._rev_adj[sid] = [n for n in self._rev_adj[sid] if n != skill_id]

    def add_edge(
        self,
        source: str,
        target: str,
        edge_type: str = "depends_on",
        metadata: dict[str, Any] | None = None,
    ) -> None:
        """手动添加边."""
        self._add_edge(source, target, edge_type, metadata or {})

    def _add_edge(
        self,
        source: str,
        target: str,
        edge_type: str,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        edge = GraphEdge(
            source=source,
            target=target,
            edge_type=edge_type,
            metadata=metadata or {},
        )
        if edge not in self._edges:
            self._edges.append(edge)
            self._adj[source].append(target)
            self._rev_adj[target].append(source)

    # ---- 图谱分析 ----

    def detect_cycle(self) -> list[str] | None:
        """检测图中是否存在环路.

        Returns:
            环路中的节点列表，无环路返回 None.
        """
        WHITE, GRAY, BLACK = 0, 1, 2
        color = {node: WHITE for node in self._nodes}
        parent: dict[str, str | None] = {}

        def dfs(node: str) -> list[str] | None:
            color[node] = GRAY
            for neighbor in self._adj.get(node, []):
                if neighbor not in self._nodes:
                    continue
                if color[neighbor] == GRAY:
                    # 找到环路
                    cycle = [neighbor, node]
                    current = node
                    while parent.get(current) != neighbor:
                        current = parent.get(current, "")
                        if not current:
                            break
                        cycle.append(current)
                    cycle.reverse()
                    return cycle
                if color[neighbor] == WHITE:
                    parent[neighbor] = node
                    result = dfs(neighbor)
                    if result:
                        return result
            color[node] = BLACK
            return None

        for node in self._nodes:
            if color[node] == WHITE:
                result = dfs(node)
                if result:
                    return result
        return None

    def topological_sort(self) -> list[str]:
        """拓扑排序.

        Returns:
            技能 ID 的执行顺序列表.
        """
        in_degree: dict[str, int] = {node: 0 for node in self._nodes}
        for edge in self._edges:
            if edge.target in in_degree:
                in_degree[edge.target] += 1

        queue = collections.deque(
            node for node, deg in in_degree.items() if deg == 0
        )
        result: list[str] = []

        while queue:
            node = queue.popleft()
            result.append(node)
            for neighbor in self._adj.get(node, []):
                if neighbor in in_degree:
                    in_degree[neighbor] -= 1
                    if in_degree[neighbor] == 0:
                        queue.append(neighbor)

        return result

    def get_dependencies(
        self, skill_id: str, transitive: bool = False
    ) -> set[str]:
        """获取技能的依赖集合（该技能依赖了哪些技能）.

        Args:
            skill_id: 技能 ID.
            transitive: 是否递归获取传递依赖.

        Returns:
            依赖技能 ID 集合.
        """
        # 边方向：dep -> skill_id，所以依赖在 _adj 中是 skill_id 的出邻居
        # 但我们需要的是"skill_id 依赖了谁"，即原始 dependencies 字段
        # 由于边被构建为 dep -> skill_id，需要反向查 _rev_adj
        if not transitive:
            return set(self._rev_adj.get(skill_id, []))

        visited: set[str] = set()

        def dfs(node: str) -> None:
            for dep in self._rev_adj.get(node, []):
                if dep not in visited:
                    visited.add(dep)
                    dfs(dep)

        dfs(skill_id)
        return visited

    def get_dependents(
        self, skill_id: str, transitive: bool = False
    ) -> set[str]:
        """获取依赖该技能的上游技能集合（哪些技能依赖了该技能）.

        Args:
            skill_id: 技能 ID.
            transitive: 是否递归.

        Returns:
            上游技能 ID 集合.
        """
        # 边方向：skill_id -> dependent，所以上游在 _adj 的出邻居中
        if not transitive:
            return set(self._adj.get(skill_id, []))

        visited: set[str] = set()

        def dfs(node: str) -> None:
            for dep in self._adj.get(node, []):
                if dep not in visited:
                    visited.add(dep)
                    dfs(dep)

        dfs(skill_id)
        return visited

    def find_chains(
        self,
        start_id: str,
        end_id: str | None = None,
        max_depth: int = 10,
    ) -> list[ComposableChain]:
        """发现从起始技能出发的下游组合链.

        沿正向邻接表（dep -> dependent）搜索，找到所有依赖 start_id 的技能链。

        Args:
            start_id: 起始技能 ID.
            end_id: 终止技能 ID（None 表示搜索所有可达链）.
            max_depth: 最大搜索深度.

        Returns:
            可组合技能链列表.
        """
        chains: list[ComposableChain] = []
        path: list[str] = []

        def dfs(node: str, depth: int) -> None:
            if depth > max_depth:
                return
            path.append(node)

            # 沿正向边（node -> dependent）搜索
            neighbors = self._adj.get(node, [])
            if not neighbors:
                # 叶节点，记录链
                if len(path) > 1:
                    chains.append(
                        ComposableChain(
                            chain_id=f"chain_{len(chains)}",
                            skills=list(path),
                            total_steps=len(path),
                            description=" -> ".join(path),
                            confidence=1.0 / (depth + 1),
                        )
                    )
            else:
                for neighbor in neighbors:
                    if neighbor not in self._nodes:
                        continue
                    if neighbor in path:
                        continue
                    if end_id and neighbor == end_id:
                        new_path = path + [neighbor]
                        chains.append(
                            ComposableChain(
                                chain_id=f"chain_{len(chains)}",
                                skills=new_path,
                                total_steps=len(new_path),
                                description=" -> ".join(new_path),
                                confidence=1.0 / (depth + 2),
                            )
                        )
                        continue
                    dfs(neighbor, depth + 1)
                # 如果没有找到 end_id，也记录当前路径
                if not end_id and len(path) > 1:
                    chains.append(
                        ComposableChain(
                            chain_id=f"chain_{len(chains)}",
                            skills=list(path),
                            total_steps=len(path),
                            description=" -> ".join(path),
                            confidence=1.0 / (depth + 1),
                        )
                    )

            path.pop()

        dfs(start_id, 0)
        # 按置信度降序排列
        chains.sort(key=lambda c: c.confidence, reverse=True)
        return chains

    def validate_skill_ready(self, skill_id: str) -> tuple[bool, list[str]]:
        """验证技能是否就绪（所有依赖是否已注册）.

        Returns:
            (是否就绪, 缺失的依赖列表).
        """
        deps = self.get_dependencies(skill_id, transitive=True)
        missing = [d for d in deps if d not in self._nodes]
        return (len(missing) == 0, missing)

    def get_execution_order(self, skill_ids: list[str]) -> list[str]:
        """给定一组技能，返回满足依赖关系的执行顺序.

        Args:
            skill_ids: 需要执行的技能 ID 列表.

        Returns:
            满足依赖的执行顺序.
        """
        relevant_deps: set[str] = set(skill_ids)
        for sid in skill_ids:
            relevant_deps.update(self.get_dependencies(sid, transitive=True))

        # 子图拓扑排序
        in_degree: dict[str, int] = {node: 0 for node in relevant_deps}
        for edge in self._edges:
            if edge.source in relevant_deps and edge.target in relevant_deps:
                if edge.target in in_degree:
                    in_degree[edge.target] += 1

        queue = collections.deque(
            node for node, deg in in_degree.items() if deg == 0
        )
        result: list[str] = []

        while queue:
            node = queue.popleft()
            if node in {s for s in skill_ids}:
                result.append(node)
            for neighbor in self._adj.get(node, []):
                if neighbor in in_degree:
                    in_degree[neighbor] -= 1
                    if in_degree[neighbor] == 0:
                        queue.append(neighbor)

        return result

    # ---- 统计 ----

    def get_stats(self) -> dict[str, Any]:
        """获取图谱统计信息."""
        cycle = self.detect_cycle()
        return {
            "node_count": len(self._nodes),
            "edge_count": len(self._edges),
            "has_cycle": cycle is not None,
            "cycle_nodes": cycle or [],
            "isolated_nodes": [
                sid
                for sid in self._nodes
                if not self._adj.get(sid) and not self._rev_adj.get(sid)
            ],
        }
