"""M7 积木平台 - 工作流验证器.

工作流结构验证与 DAG 拓扑排序逻辑（Kahn 算法）。
从 engine.py 拆分而来，保持原有行为不变。
"""

from __future__ import annotations

import logging
from collections import deque
from typing import Any, Dict, List, Optional, Set, Tuple

logger = logging.getLogger("m7.engine")

# ============================================================
# DAG 拓扑排序
# ============================================================

def build_adjacency_list(blocks: List[Dict[str, Any]]) -> Tuple[Dict[str, List[str]], Dict[str, int]]:
    """从积木块构建邻接表和入度表.

    Args:
        blocks: 积木块列表，每个块包含 id 和 next 字段

    Returns:
        (adjacency, in_degree) 元组
        - adjacency: {block_id: [next_block_id, ...]}
        - in_degree: {block_id: 入度}
    """
    adjacency: Dict[str, List[str]] = {}
    in_degree: Dict[str, int] = {}

    # 初始化所有节点
    for block in blocks:
        block_id = block["id"]
        adjacency[block_id] = []
        in_degree[block_id] = 0

    # 构建邻接表和入度
    for block in blocks:
        block_id = block["id"]
        next_blocks = block.get("next", [])
        for next_id in next_blocks:
            if next_id in adjacency:
                adjacency[block_id].append(next_id)
                in_degree[next_id] += 1

    return adjacency, in_degree


def topological_sort(
    blocks: List[Dict[str, Any]],
    start_block: Optional[str] = None,
) -> List[str]:
    """对积木块进行拓扑排序（Kahn 算法）.

    Args:
        blocks: 积木块列表
        start_block: 可选的起始积木块 ID，指定后从该块开始执行

    Returns:
        按执行顺序排列的积木块 ID 列表

    Raises:
        ValueError: 如果检测到环
    """
    adjacency, in_degree = build_adjacency_list(blocks)

    # 如果指定了起始块，需要调整入度：起始块之前的所有依赖视为已满足
    if start_block and start_block in in_degree:
        # 找到从起始块可达的所有节点
        reachable: Set[str] = set()
        stack = [start_block]
        while stack:
            node = stack.pop()
            if node in reachable:
                continue
            reachable.add(node)
            for next_node in adjacency.get(node, []):
                stack.append(next_node)

        # 只保留可达节点
        adjacency = {k: [v for v in vs if v in reachable] for k, vs in adjacency.items() if k in reachable}
        # 重新计算入度（仅考虑可达节点之间的边）
        in_degree = {k: 0 for k in reachable}
        for node, next_nodes in adjacency.items():
            for next_node in next_nodes:
                in_degree[next_node] += 1

    # 找到所有入度为 0 的节点
    queue = deque()
    for node, degree in in_degree.items():
        if degree == 0:
            queue.append(node)

    result: List[str] = []
    while queue:
        node = queue.popleft()
        result.append(node)

        for neighbor in adjacency.get(node, []):
            in_degree[neighbor] -= 1
            if in_degree[neighbor] == 0:
                queue.append(neighbor)

    # 检测环
    if len(result) != len(in_degree):
        remaining = [n for n, d in in_degree.items() if d > 0]
        raise ValueError(f"工作流中存在循环依赖，涉及节点: {remaining}")

    return result


def is_linear_workflow(blocks: List[Dict[str, Any]]) -> bool:
    """判断工作流是否为线性（串行）结构.

    Args:
        blocks: 积木块列表

    Returns:
        True 表示线性结构
    """
    if len(blocks) <= 1:
        return True

    adjacency, in_degree = build_adjacency_list(blocks)

    # 线性结构：最多一个起点，最多一个终点，每个节点最多一个后继
    start_nodes = [n for n, d in in_degree.items() if d == 0]
    if len(start_nodes) != 1:
        return False

    for node, next_nodes in adjacency.items():
        if len(next_nodes) > 1:
            return False

    # 检查每个节点（除终点外）的入度都是 1
    for node, degree in in_degree.items():
        if degree > 1:
            return False
        # 终点（没有后继）的入度可以是 1 或 0（单节点）
        if len(adjacency.get(node, [])) == 0:
            continue

    return True



# ============================================================
# 工作流结构验证器
# ============================================================


class WorkflowValidator:
    """工作流结构验证器。

    对工作流定义进行结构性校验：积木块非空、id 存在且唯一、next 引用合法、
    起始块存在、是否存在循环依赖等。校验失败返回错误信息列表（空列表表示通过）。
    """

    def __init__(self, workflow: Optional[Dict[str, Any]] = None):
        self._workflow: Dict[str, Any] = workflow or {}

    def validate(self, start_block: Optional[str] = None) -> List[str]:
        """校验工作流结构，返回错误信息列表（空列表表示通过）。"""
        errors: List[str] = []
        blocks = self._workflow.get("blocks", []) or []
        if not blocks:
            errors.append("工作流中没有积木块")
            return errors

        seen: Set[str] = set()
        for block in blocks:
            bid = block.get("id") if isinstance(block, dict) else None
            if not bid:
                errors.append("存在缺少 id 的积木块")
                continue
            if bid in seen:
                errors.append(f"积木块 id 重复: {bid}")
                continue
            seen.add(bid)

        for block in blocks:
            if not isinstance(block, dict):
                continue
            bid = block.get("id")
            for nxt in block.get("next", []) or []:
                if nxt not in seen:
                    errors.append(f"积木块 {bid} 引用了不存在的 next: {nxt}")

        if start_block and start_block not in seen:
            errors.append(f"起始积木块不存在: {start_block}")

        try:
            topological_sort(blocks, start_block)
        except ValueError as exc:
            errors.append(str(exc))

        return errors

    def is_valid(self, start_block: Optional[str] = None) -> bool:
        return not self.validate(start_block)


__all__ = [
    "build_adjacency_list",
    "topological_sort",
    "is_linear_workflow",
    "WorkflowValidator",
]
