from __future__ import annotations

"""Skill 技能注册中心.

支持多版本共存（skill_id -> {version: ISkill}），
get_skill 默认返回最新版本。
discover 支持 BM25 风格的 TF-IDF 语义检索。
"""

import math
import re
from typing import Any

import structlog

from skill_cluster.interfaces import ISkill, SkillManifest, SkillQuery

logger = structlog.get_logger()


class _SkillWrapper:
    """技能包装类，为 v2 API 提供统一的属性访问.

    包装 ISkill 实例，增加 enabled 和 usage_count 属性，
    并暴露原始 manifest。
    """

    def __init__(self, skill: ISkill) -> None:
        self._skill = skill
        self.manifest = skill.manifest
        self.enabled = True
        self.usage_count = 0
        self.created_at = 0.0
        self.last_used_at = 0.0


class SkillRegistryError(Exception):
    """注册中心异常."""

    pass


class SkillAlreadyExistsError(SkillRegistryError):
    """技能已存在异常."""

    pass


class DependencyNotFoundError(SkillRegistryError):
    """依赖未找到异常."""

    pass


class SkillDependencyOccupiedError(SkillRegistryError):
    """技能被依赖占用异常."""

    pass


def _version_key(v: str) -> tuple[int, int, int]:
    """将语义版本解析为可排序的元组."""
    parts = v.split("+")[0].split("-")[0].split(".")
    return tuple(int(p) for p in parts[:3])


class SkillRegistry:
    """技能注册中心，管理技能的注册、发现与版本管理.

    支持多版本共存：同一 skill_id 可注册多个版本，
    get_skill() 默认返回最新版本。
    discover() 支持 BM25 风格的 TF-IDF 语义检索。
    """

    def __init__(self) -> None:
        self._skills: dict[str, dict[str, ISkill]] = {}
        self._manifests: dict[str, dict[str, SkillManifest]] = {}
        self._versions: dict[str, list[str]] = {}
        # 倒排索引: term -> set(skill_id)，加速 BM25 的 DF 计算
        self._inverted_index: dict[str, set[str]] = {}
        # 最新版本缓存: skill_id -> version，避免每次 max() 排序
        self._latest_version: dict[str, str] = {}

    # ---- 注册管理 ----

    def register(
        self, skill: ISkill, trace_id: str = ""
    ) -> None:
        """注册技能.

        同名技能不同版本可共存；同一版本重复注册会报错。
        注册时会校验依赖是否已满足。

        Args:
            skill: 技能实例.
            trace_id: 调用链路追踪 ID.

        Raises:
            SkillAlreadyExistsError: 同一 skill_id + version 已存在.
            DependencyNotFoundError: 依赖的技能未注册.
        """
        manifest = skill.manifest
        sid = manifest.skill_id
        ver = manifest.version

        if sid not in self._skills:
            self._skills[sid] = {}
            self._manifests[sid] = {}
            self._versions[sid] = []

        if ver in self._skills[sid]:
            raise SkillAlreadyExistsError(
                f"Skill {sid}@{ver} 已存在"
            )

        for dep in manifest.dependencies:
            if self.get_skill(dep) is None:
                raise DependencyNotFoundError(
                    f"依赖技能 {dep} 未注册"
                )

        self._skills[sid][ver] = skill
        self._manifests[sid][ver] = manifest
        if ver not in self._versions[sid]:
            self._versions[sid].append(ver)

        # 更新倒排索引和最新版本缓存
        self._update_index(manifest, add=True)
        self._update_latest_version(sid)

        logger.info(
            "skill_registered",
            skill_id=sid,
            version=ver,
            trace_id=trace_id,
        )

    def _update_index(self, manifest: SkillManifest, add: bool = True) -> None:
        """更新倒排索引."""
        sid = manifest.skill_id
        text = (
            manifest.name
            + " "
            + manifest.description
            + " "
            + " ".join(manifest.tags)
            + " "
            + " ".join(manifest.capabilities)
        ).lower()
        terms = set(re.findall(r"\b\w+\b", text))
        for term in terms:
            if add:
                self._inverted_index.setdefault(term, set()).add(sid)
            else:
                self._inverted_index.get(term, set()).discard(sid)

    def _update_latest_version(self, sid: str) -> None:
        """更新最新版本缓存."""
        versions = self._versions.get(sid, [])
        if versions:
            self._latest_version[sid] = max(versions, key=_version_key)
        else:
            self._latest_version.pop(sid, None)

    def unregister(
        self,
        skill_id: str,
        force: bool = False,
        trace_id: str = "",
    ) -> bool:
        """注销技能（所有版本）.

        Args:
            skill_id: 技能 ID.
            force: 是否强制卸载（忽略依赖占用）.
            trace_id: 调用链路追踪 ID.

        Returns:
            是否成功注销.

        Raises:
            SkillDependencyOccupiedError: 有其他技能依赖该技能.
        """
        if skill_id not in self._skills:
            return False

        dependents = [
            sid
            for sid, versions in self._manifests.items()
            for m in versions.values()
            if skill_id in m.dependencies
        ]
        if dependents and not force:
            raise SkillDependencyOccupiedError(
                f"Skill {skill_id} 被 {dependents} 依赖，无法卸载"
            )

        # 清理倒排索引和最新版本缓存
        for manifest in self._manifests[skill_id].values():
            self._update_index(manifest, add=False)
        self._latest_version.pop(skill_id, None)

        del self._skills[skill_id]
        del self._manifests[skill_id]
        del self._versions[skill_id]

        logger.info(
            "skill_unregistered",
            skill_id=skill_id,
            trace_id=trace_id,
        )
        return True

    def unregister_version(
        self, skill_id: str, version: str, trace_id: str = ""
    ) -> bool:
        """注销指定版本技能."""
        if skill_id not in self._skills:
            return False
        if version not in self._skills[skill_id]:
            return False

        # 清理该版本的倒排索引
        manifest = self._manifests[skill_id].get(version)
        if manifest is not None:
            self._update_index(manifest, add=False)

        self._skills[skill_id].pop(version)
        self._manifests[skill_id].pop(version)
        self._versions[skill_id].remove(version)

        if not self._versions[skill_id]:
            del self._skills[skill_id]
            del self._manifests[skill_id]
            del self._versions[skill_id]
            self._latest_version.pop(skill_id, None)
        else:
            self._update_latest_version(skill_id)

        logger.info(
            "skill_version_unregistered",
            skill_id=skill_id,
            version=version,
            trace_id=trace_id,
        )
        return True

    # ---- 获取 ----

    def get_skill(
        self, skill_id: str, version: str | None = None
    ) -> ISkill | None:
        """按 ID 获取技能实例.

        若未指定 version，返回最新版本（使用缓存避免重复排序）.

        Args:
            skill_id: 技能 ID.
            version: 指定版本，None 表示最新版.

        Returns:
            技能实例，若不存在则返回 None.
        """
        versions = self._skills.get(skill_id)
        if versions is None:
            return None
        if version is not None:
            return versions.get(version)
        latest = self._latest_version.get(skill_id)
        if latest is not None:
            return versions.get(latest)
        latest = max(versions.keys(), key=_version_key)
        return versions[latest]

    def get_manifest(
        self, skill_id: str, version: str | None = None
    ) -> SkillManifest | None:
        """获取技能清单（最新版本）."""
        versions = self._manifests.get(skill_id)
        if versions is None:
            return None
        if version is not None:
            return versions.get(version)
        latest = self._latest_version.get(skill_id)
        if latest is not None:
            return versions.get(latest)
        latest = max(versions.keys(), key=_version_key)
        return versions[latest]

    def list_versions(self, skill_id: str) -> list[str]:
        """列出某技能的所有版本（降序）."""
        versions = self._versions.get(skill_id, [])
        return sorted(versions, key=_version_key, reverse=True)

    def list_skills(self) -> list[str]:
        """列出所有已注册技能 ID."""
        return list(self._skills.keys())

    def list_all(self) -> list[Any]:
        """列出所有已注册技能实例（每个 skill_id 取最新版本）.

        为 v2 API 提供兼容接口，返回的每个对象都有 manifest 属性。
        """
        result: list[Any] = []
        for sid in self._skills:
            skill = self.get_skill(sid)
            if skill is not None:
                result.append(_SkillWrapper(skill))
        return result

    def get(self, skill_id: str) -> Any | None:
        """获取技能实例包装（v2 API 兼容接口）.

        Returns:
            带有 manifest/enabled/usage_count 属性的包装对象，未找到返回 None
        """
        skill = self.get_skill(skill_id)
        if skill is None:
            return None
        return _SkillWrapper(skill)

    def all_manifests(self) -> list[SkillManifest]:
        """获取所有技能清单（每个 skill_id 取最新版本）."""
        result: list[SkillManifest] = []
        for sid in self._skills:
            manifest = self.get_manifest(sid)
            if manifest is not None:
                result.append(manifest)
        return result

    # ---- 发现 ----

    def discover(self, query: SkillQuery) -> list[SkillManifest]:
        """发现技能（BM25 语义检索）.

        Args:
            query: 查询条件.

        Returns:
            匹配的技能清单列表（按 BM25 评分降序）.
        """
        all_manifests = self.all_manifests()
        scored: list[tuple[SkillManifest, float]] = []

        for manifest in all_manifests:
            score = self._bm25_score(manifest, query, all_manifests)
            if score > 0:
                scored.append((manifest, score))

        scored.sort(key=lambda x: x[1], reverse=True)
        return [m for m, _ in scored]

    def _bm25_score(
        self,
        manifest: SkillManifest,
        query: SkillQuery,
        all_manifests: list[SkillManifest],
    ) -> float:
        """BM25 风格匹配评分."""
        text = (
            manifest.name
            + " "
            + manifest.description
            + " "
            + " ".join(manifest.tags)
            + " "
            + " ".join(manifest.capabilities)
        ).lower()

        # 基础过滤
        if query.name and not re.search(query.name, manifest.name, re.I):
            return 0.0
        if query.tags and not set(query.tags).issubset(
            set(manifest.tags)
        ):
            return 0.0
        if query.capability and query.capability not in manifest.capabilities:
            return 0.0

        query_text = (
            (query.semantic_query or "")
            + " "
            + (query.name or "")
            + " "
            + (query.capability or "")
        ).lower()
        if not query_text.strip():
            return 1.0

        terms = re.findall(r"\b\w+\b", query_text)
        if not terms:
            return 1.0

        # 标准 BM25 公式: IDF * (tf * (k1+1)) / (tf + k1 * (1 - b + b * dl/avgdl))
        k1 = 1.5
        b = 0.75
        doc_len = len(text.split())
        avg_dl = sum(
            len(
                (m.name + " " + m.description + " " + " ".join(m.tags) + " " + " ".join(m.capabilities)).split()
            )
            for m in all_manifests
        ) / max(len(all_manifests), 1)

        score = 0.0
        n = len(all_manifests)
        for term in terms:
            # 使用词边界匹配替代子串匹配
            tf = len(re.findall(r"\b" + re.escape(term) + r"\b", text))
            if tf == 0:
                continue
            # 使用倒排索引加速 DF 计算
            df = len(self._inverted_index.get(term, set()))
            idf = math.log((n - df + 0.5) / (df + 0.5) + 1)
            tf_norm = (tf * (k1 + 1)) / (tf + k1 * (1 - b + b * doc_len / max(avg_dl, 1)))
            score += idf * tf_norm

        return score

    # ---- 依赖管理 ----

    def get_dependencies(self, skill_id: str) -> list[str]:
        """获取技能的直接依赖列表（最新版本）."""
        manifest = self.get_manifest(skill_id)
        if manifest is None:
            return []
        return manifest.dependencies

    def get_dependents(self, skill_id: str) -> list[str]:
        """获取依赖此技能的其他技能列表."""
        return [
            sid
            for sid, versions in self._manifests.items()
            for m in versions.values()
            if skill_id in m.dependencies
        ]

    def validate_dependencies(
        self, skill_id: str, version: str | None = None
    ) -> tuple[bool, list[str]]:
        """验证技能的依赖是否全部满足."""
        deps = self.get_dependencies(skill_id)
        missing = [
            d for d in deps if self.get_skill(d) is None
        ]
        return (len(missing) == 0, missing)

    # ---- 统计 ----

    def get_versions(self, skill_id: str) -> list[str]:
        """获取技能历史版本（兼容旧接口，升序）."""
        versions = self._versions.get(skill_id, [])
        return sorted(versions, key=_version_key)

    def get_latest_version(self, skill_id: str) -> str | None:
        """获取技能最新版本."""
        versions = self.list_versions(skill_id)
        if not versions:
            return None
        return versions[0]

    def stats(self) -> dict[str, Any]:
        """注册中心统计信息."""
        total_versions = sum(
            len(vs) for vs in self._versions.values()
        )
        return {
            "total_skills": len(self._skills),
            "total_versions": total_versions,
            "skill_ids": self.list_skills(),
        }
