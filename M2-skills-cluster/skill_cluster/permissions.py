"""Permission 技能权限系统.

支持四级 ACL（none/read/write/admin）以及 action/params 级细粒度控制。

【模型迁移说明】
Pydantic 模型已迁移至 ``skill_cluster.models.security``，
本文件保留 import 别名以保持向后兼容。
"""

from __future__ import annotations

import os
from typing import Any

import structlog
import yaml

# ---- 从 models.security 导入 Pydantic 模型（向后兼容） ----
from skill_cluster.models.security import (
    PermissionMatrix,
    PermissionRule,
)

logger = structlog.get_logger()


# 补充 PermissionMatrix 的方法（原定义在 permissions.py 中，
# 迁移到 models 后需在此处通过 monkey-patch 补充业务方法）
# 注意：为保持代码清晰，我们在原文件中保留 PermissionMatrix 的业务方法，
# 但模型定义（字段、ConfigDict）在 models/security.py 中。
# 由于 PermissionMatrix 包含大量业务逻辑（set_base, check, load_yaml 等），
# 这些方法不属于纯数据模型，应保留在原文件中。
# 因此采用以下策略：
# - 数据字段定义在 models/security.py 的 PermissionMatrix 中
# - 业务方法通过子类扩展的方式在此处添加

class _PermissionMatrixWithMethods(PermissionMatrix):
    """带业务方法的权限矩阵.

    数据模型定义在 :class:`skill_cluster.models.security.PermissionMatrix`，
    业务方法（ACL 操作、规则匹配、持久化等）在此扩展。
    """

    _base_acl: dict[str, dict[str, str]] = {}  # agent_id -> skill_id -> level
    _rule_index: dict[str, list[PermissionRule]] = {}  # agent_id -> rules 二级索引

    def set_base(
        self, agent_id: str, skill_id: str, level: str
    ) -> None:
        """设置基础 ACL."""
        if agent_id not in self._base_acl:
            self._base_acl[agent_id] = {}
        self._base_acl[agent_id][skill_id] = level

    def get_base(self, agent_id: str, skill_id: str) -> str:
        """获取基础 ACL 级别（支持通配回退）."""
        # 1. 精确匹配
        level = self._base_acl.get(agent_id, {}).get(skill_id)
        if level is not None:
            return level
        # 2. agent 通配
        level = self._base_acl.get("*", {}).get(skill_id)
        if level is not None:
            return level
        # 3. skill 通配
        level = self._base_acl.get(agent_id, {}).get("*")
        if level is not None:
            return level
        # 4. 全通配
        level = self._base_acl.get("*", {}).get("*")
        if level is not None:
            return level
        return "none"

    def add_rule(self, rule: PermissionRule) -> None:
        """添加细粒度权限规则."""
        self.rules.append(rule)
        # 更新二级索引
        key = rule.agent_id if rule.agent_id != "*" else "*"
        self._rule_index.setdefault(key, []).append(rule)
        if rule.agent_id != "*":
            self._rule_index.setdefault("*", []).append(rule)
        # 将规则同步到基础 ACL
        if rule.agent_id != "*" and rule.skill_id != "*":
            self.set_base(rule.agent_id, rule.skill_id, rule.level)

    def check(
        self,
        agent_id: str,
        skill_id: str,
        required: str,
        action: str | None = None,
        params: dict[str, Any] | None = None,
    ) -> bool:
        """检查权限.

        优先匹配细粒度规则，无匹配时回退到基础 ACL。

        Args:
            agent_id: Agent ID.
            skill_id: 技能 ID.
            required: 需要的权限级别.
            action: 动作标识（可选）.
            params: 调用参数（可选）.

        Returns:
            是否有权限.
        """
        level_order = {"none": 0, "read": 1, "write": 2, "admin": 3}
        req_level = level_order.get(required, 0)

        # 1. 尝试细粒度规则匹配（按优先级排序）
        matched = self._match_rule(agent_id, skill_id, action, params)
        if matched is not None:
            granted = level_order.get(matched.level, 0)
            return granted >= req_level

        # 2. 回退到基础 ACL
        granted = level_order.get(
            self.get_base(agent_id, skill_id), 0
        )
        return granted >= req_level

    def _match_rule(
        self,
        agent_id: str,
        skill_id: str,
        action: str | None,
        params: dict[str, Any] | None,
    ) -> PermissionRule | None:
        """匹配最佳细粒度规则（使用二级索引减少扫描范围）."""
        import fnmatch

        # 通过二级索引获取候选规则（精确 agent + 通配），避免扫描全部规则
        candidates: list[PermissionRule] = []
        seen_ids: set[int] = set()
        for key in (agent_id, "*"):
            for rule in self._rule_index.get(key, []):
                if id(rule) not in seen_ids:
                    candidates.append(rule)
                    seen_ids.add(id(rule))

        best: PermissionRule | None = None
        best_score = -1

        for rule in candidates:
            score = 0
            # agent_id 匹配
            if rule.agent_id == agent_id:
                score += 4
            elif rule.agent_id != "*":
                continue
            # skill_id 匹配
            if rule.skill_id == skill_id:
                score += 4
            elif rule.skill_id != "*":
                continue
            # action 匹配
            if action is not None:
                if rule.action == action:
                    score += 2
                elif rule.action != "*":
                    continue
            # params_pattern 匹配
            if rule.params_pattern is not None and params is not None:
                param_str = str(sorted(params.items()))
                if not fnmatch.fnmatch(param_str, rule.params_pattern):
                    continue
                score += 1

            if score > best_score:
                best_score = score
                best = rule

        return best

    def load_yaml(self, path: str) -> None:
        """从 YAML 文件加载权限配置."""
        with open(path, "r") as f:
            data = yaml.safe_load(f)
        for item in data:
            rule = PermissionRule(**item)
            self.add_rule(rule)

    def save_yaml(self, path: str) -> None:
        """保存权限配置到 YAML 文件."""
        with open(path, "w") as f:
            yaml.dump(
                [r.model_dump() for r in self.rules],
                f,
                allow_unicode=True,
                default_flow_style=False,
            )


# 向后兼容：将带方法的子类作为 PermissionMatrix 导出
PermissionMatrix = _PermissionMatrixWithMethods  # type: ignore[assignment,misc]


class SkillPermissionManager:
    """技能权限管理器.

    管理全局权限矩阵，提供快速权限检查。
    兼容旧 API（config_dir、grant/revoke/list、持久化）。
    """

    _DEFAULT_CONFIG_FILE = "permissions.yaml"

    def __init__(self, config_dir: str | None = None) -> None:
        self._config_dir = config_dir
        self._matrix = PermissionMatrix()
        # 旧版默认策略：任意 agent 对任意 skill 默认 read，
        # 但 skill.tide_memory 默认 none
        self._matrix.set_base("*", "*", "read")
        self._matrix.set_base("*", "skill.tide_memory", "none")

        if config_dir is not None:
            os.makedirs(config_dir, exist_ok=True)
            config_path = os.path.join(config_dir, self._DEFAULT_CONFIG_FILE)
            if os.path.exists(config_path):
                self._matrix.load_yaml(config_path)

    # ---- 旧 API 兼容 ----

    def _sync_rule_from_base(
        self, agent_id: str, skill_id: str, level: str
    ) -> None:
        """将基础 ACL 同步为 PermissionRule（用于持久化）."""
        # 移除已有的同目标规则
        self._matrix.rules = [
            r
            for r in self._matrix.rules
            if not (r.agent_id == agent_id and r.skill_id == skill_id)
        ]
        if agent_id != "*" or skill_id != "*":
            self._matrix.rules.append(
                PermissionRule(
                    agent_id=agent_id, skill_id=skill_id, level=level
                )
            )

    def grant(
        self,
        agent_id: str,
        skill_id: str,
        level: str,
        scope: str | None = None,  # noqa: ARG002
    ) -> None:
        """授予权限（兼容旧 API，scope 参数保留但忽略）."""
        self._matrix.set_base(agent_id, skill_id, level)
        self._sync_rule_from_base(agent_id, skill_id, level)
        self._auto_persist()

    def revoke(self, agent_id: str, skill_id: str) -> None:
        """撤销权限，回退到 none（完全禁止访问）.

        【第五轮优化】修正 revoke 语义：原来回退到 "read" 导致撤销后仍可读取敏感数据。
        现在回退到 "none" 实现真正的权限撤销。
        """
        self._matrix.set_base(agent_id, skill_id, "none")
        self._sync_rule_from_base(agent_id, skill_id, "none")
        self._auto_persist()

    def list_for_agent(self, agent_id: str) -> list[dict[str, Any]]:
        """列出某 Agent 的所有显式权限配置."""
        perms: list[dict[str, Any]] = []
        for sid, level in self._matrix._base_acl.get(agent_id, {}).items():
            perms.append({"skill_id": sid, "level": level})
        return perms

    def _auto_persist(self) -> None:
        """若配置了 config_dir，自动持久化."""
        if self._config_dir is not None:
            config_path = os.path.join(
                self._config_dir, self._DEFAULT_CONFIG_FILE
            )
            self._matrix.save_yaml(config_path)

    # ---- 新 API ----

    def set_permission(
        self, agent_id: str, skill_id: str, level: str
    ) -> None:
        """设置基础权限."""
        self._matrix.set_base(agent_id, skill_id, level)

    def add_rule(self, rule: PermissionRule) -> None:
        """添加细粒度权限规则."""
        self._matrix.add_rule(rule)

    def check(
        self,
        agent_id: str,
        skill_id: str,
        required: str,
        action: str | None = None,
        params: dict[str, Any] | None = None,
    ) -> bool:
        """检查权限（支持 action/params 级细粒度控制）."""
        return self._matrix.check(
            agent_id, skill_id, required, action=action, params=params
        )

    def load(self, path: str) -> None:
        """从 YAML 加载权限配置."""
        self._matrix.load_yaml(path)

    def save(self, path: str) -> None:
        """保存权限配置到 YAML."""
        self._matrix.save_yaml(path)
