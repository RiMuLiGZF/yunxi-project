"""M2 语义路由单元测试.

覆盖：
- skill 语义匹配基本功能
- 降级机制（无 embedding 时正常工作）
- 与 SkillRecommender 集成
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

# 确保路径正确
_M2_ROOT = Path(__file__).resolve().parents[1]
_PROJECT_ROOT = Path(__file__).resolve().parents[3]
for _p in (str(_M2_ROOT), str(_PROJECT_ROOT)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from skill_cluster.interfaces import SkillManifest
from skill_cluster.semantic import SemanticSkillRouter, SemanticMatchResult
from skill_cluster.discovery.recommender import SkillRecommender, SkillRecommendation


def _make_manifest(
    skill_id: str,
    name: str,
    desc: str,
    tags: list[str] | None = None,
    caps: list[str] | None = None,
) -> SkillManifest:
    return SkillManifest(
        skill_id=skill_id,
        name=name,
        version="1.0.0",
        description=desc,
        author="test",
        entrypoint=skill_id,
        tags=tags or [],
        capabilities=caps or [],
    )


# ============================================================================
# SemanticSkillRouter 基本功能测试
# ============================================================================

class TestSemanticSkillRouterBasic:
    """语义路由器基本功能测试."""

    def test_create_router(self) -> None:
        """创建语义路由器."""
        router = SemanticSkillRouter()
        assert router.size == 0
        assert isinstance(router.provider_name, str)

    def test_register_skill(self) -> None:
        """注册技能."""
        router = SemanticSkillRouter()
        manifest = _make_manifest(
            "skill.test", "Test Skill", "A test skill for testing",
            tags=["test"], caps=["do_test"],
        )
        router.register_skill(manifest)
        assert router.size == 1

    def test_register_multiple_skills(self) -> None:
        """注册多个技能."""
        router = SemanticSkillRouter()
        for i in range(5):
            router.register_skill(_make_manifest(
                f"skill.{i}", f"Skill {i}", f"Description for skill {i}",
            ))
        assert router.size == 5

    def test_register_batch(self) -> None:
        """批量注册技能."""
        router = SemanticSkillRouter()
        manifests = [
            _make_manifest("skill.a", "Alpha", "Alpha skill"),
            _make_manifest("skill.b", "Beta", "Beta skill"),
            _make_manifest("skill.c", "Charlie", "Charlie skill"),
        ]
        router.register_skills(manifests)
        assert router.size == 3

    def test_unregister_skill(self) -> None:
        """注销技能."""
        router = SemanticSkillRouter()
        router.register_skill(_make_manifest(
            "skill.test", "Test", "Test skill",
        ))
        assert router.size == 1
        result = router.unregister_skill("skill.test")
        assert result is True
        assert router.size == 0

    def test_unregister_nonexistent(self) -> None:
        """注销不存在的技能."""
        router = SemanticSkillRouter()
        result = router.unregister_skill("skill.nonexistent")
        assert result is False

    def test_provider_name(self) -> None:
        """提供者名称应非空."""
        router = SemanticSkillRouter()
        assert len(router.provider_name) > 0


# ============================================================================
# 语义匹配测试
# ============================================================================

class TestSemanticMatch:
    """语义匹配功能测试."""

    def test_match_returns_results(self) -> None:
        """匹配应返回结果."""
        router = SemanticSkillRouter()
        router.register_skill(_make_manifest(
            "skill.search", "Web Search", "Search the web for information",
            tags=["search", "web"], caps=["search_web", "find_info"],
        ))
        results = router.match("find information online", top_k=5)
        assert isinstance(results, list)

    def test_match_empty_query(self) -> None:
        """空查询应返回空列表."""
        router = SemanticSkillRouter()
        router.register_skill(_make_manifest(
            "skill.test", "Test", "Test skill",
        ))
        results = router.match("", top_k=5)
        assert results == []

    def test_match_whitespace_query(self) -> None:
        """空白查询应返回空列表."""
        router = SemanticSkillRouter()
        router.register_skill(_make_manifest(
            "skill.test", "Test", "Test skill",
        ))
        results = router.match("   \n\t  ", top_k=5)
        assert results == []

    def test_match_result_type(self) -> None:
        """匹配结果应为 SemanticMatchResult 类型."""
        router = SemanticSkillRouter()
        router.register_skill(_make_manifest(
            "skill.translate", "Translator", "Translate text between languages",
            caps=["translate_en", "translate_zh"],
        ))
        results = router.match("translate text", top_k=1)
        if results:
            assert isinstance(results[0], SemanticMatchResult)
            assert isinstance(results[0].skill_id, str)
            assert isinstance(results[0].score, float)
            assert 0.0 <= results[0].score <= 1.0

    def test_match_top_k(self) -> None:
        """匹配应返回 top_k 个结果."""
        router = SemanticSkillRouter()
        for i in range(10):
            router.register_skill(_make_manifest(
                f"skill.{i}", f"Skill {i}", f"Description for skill {i}",
            ))
        results = router.match("test query", top_k=5)
        assert len(results) <= 5

    def test_match_sorted_by_score(self) -> None:
        """匹配结果应按得分降序排列."""
        router = SemanticSkillRouter()
        router.register_skill(_make_manifest(
            "skill.code", "Code Assistant", "Write and debug code programming development",
            tags=["code", "programming"],
            caps=["write_code", "debug_code"],
        ))
        router.register_skill(_make_manifest(
            "skill.cook", "Cooking Helper", "Cook recipes food meals kitchen",
            tags=["cooking", "food"],
            caps=["find_recipe", "cook_meal"],
        ))

        results = router.match("write code programming", top_k=2)
        if len(results) >= 2:
            assert results[0].score >= results[1].score

    def test_empty_router_match(self) -> None:
        """空路由器匹配应返回空列表."""
        router = SemanticSkillRouter()
        results = router.match("test query", top_k=5)
        assert results == []

    def test_get_skill_semantic_score(self) -> None:
        """获取指定技能的语义得分."""
        router = SemanticSkillRouter()
        router.register_skill(_make_manifest(
            "skill.test", "Test Skill", "Test skill for testing purposes",
        ))
        score = router.get_skill_semantic_score("skill.test", "test")
        assert isinstance(score, float)
        assert 0.0 <= score <= 1.0

    def test_get_nonexistent_skill_score(self) -> None:
        """获取不存在技能的得分应为 0."""
        router = SemanticSkillRouter()
        score = router.get_skill_semantic_score("skill.nonexistent", "test")
        assert score == 0.0


# ============================================================================
# 与 SkillRecommender 集成测试
# ============================================================================

class TestSkillRecommenderSemantic:
    """SkillRecommender 语义匹配集成测试."""

    def test_recommender_creates_with_semantic(self) -> None:
        """推荐器应能正常创建（含语义模块）."""
        rec = SkillRecommender()
        assert rec is not None
        # 语义模块可能启用也可能降级，但都不应报错
        assert hasattr(rec, '_semantic_enabled')

    def test_recommender_register_updates_semantic(self) -> None:
        """注册技能时应同步到语义路由器."""
        rec = SkillRecommender()
        rec.register_profile(_make_manifest(
            "skill.test", "Test Skill", "Test skill description",
            tags=["test"], caps=["do_test"],
        ))
        # 至少推荐功能应正常工作
        results = rec.recommend("test", top_k=5)
        assert len(results) == 1

    def test_recommender_match_dimensions_has_semantic(self) -> None:
        """匹配维度应包含 semantic（启用时）或不影响结果（禁用时）."""
        rec = SkillRecommender()
        rec.register_profile(_make_manifest(
            "skill.search", "Search", "Search for information",
            caps=["search_web"], tags=["search"],
        ))

        results = rec.recommend("search information", top_k=1)
        assert len(results) == 1
        dims = results[0].match_dimensions
        # 至少有基础维度
        assert "keyword" in dims
        assert "capability" in dims
        assert "experience" in dims
        # semantic 维度可能存在也可能不存在（取决于是否启用）
        # 但不应影响基本功能

    def test_recommender_disable_semantic(self) -> None:
        """禁用语义时推荐器应正常工作."""
        rec = SkillRecommender(enable_semantic=False)
        rec.register_profile(_make_manifest(
            "skill.test", "Test", "Test skill",
        ))
        results = rec.recommend("test", top_k=5)
        assert len(results) == 1
        # 禁用时不应有 semantic 维度
        assert "semantic" not in results[0].match_dimensions

    def test_recommender_score_range(self) -> None:
        """推荐得分应在合理范围内."""
        rec = SkillRecommender()
        rec.register_profile(_make_manifest(
            "skill.code", "Code Assistant", "Write code programming development",
            caps=["write_code", "debug"], tags=["programming"],
        ))
        rec.register_profile(_make_manifest(
            "skill.cook", "Cooking", "Cook food recipes",
            caps=["cook"], tags=["food"],
        ))

        results = rec.recommend("write code", top_k=2)
        assert len(results) == 2
        for r in results:
            assert 0.0 <= r.score <= 1.0

    def test_recommender_weights_include_semantic(self) -> None:
        """权重字典应包含 semantic 键."""
        rec = SkillRecommender()
        assert "semantic" in rec._weights

    def test_set_weights_semantic(self) -> None:
        """设置语义权重应正常工作."""
        rec = SkillRecommender()
        rec.set_weights({"semantic": 0.5, "keyword": 0.5})
        assert abs(sum(rec._weights.values()) - 1.0) < 0.01

    def test_recommender_reasons_include_semantic_when_high(self) -> None:
        """高语义匹配度时推荐理由可能包含语义信息."""
        rec = SkillRecommender()
        rec.register_profile(_make_manifest(
            "skill.programming", "Programming Assistant",
            "Help with programming code development debugging software engineering",
            caps=["write_code", "debug_code", "review_code"],
            tags=["programming", "code", "development"],
        ))

        results = rec.recommend(
            "programming software development code writing debugging",
            top_k=1,
        )
        assert len(results) == 1
        # 至少应有推荐理由
        assert len(results[0].reasons) > 0

    def test_recommender_multiple_skills_semantic_boost(self) -> None:
        """语义匹配应能作为补充提升相关技能排名."""
        rec = SkillRecommender()
        # 注册两个技能，关键词层面都不直接匹配，但语义层面有差异
        rec.register_profile(_make_manifest(
            "skill.recipe", "Recipe Finder",
            "Find cooking recipes food dishes meals ingredients kitchen",
            caps=["find_recipe", "suggest_meal"],
            tags=["cooking", "food", "recipe"],
        ))
        rec.register_profile(_make_manifest(
            "skill.finance", "Finance Tracker",
            "Track expenses budget money banking investment savings",
            caps=["track_expense", "manage_budget"],
            tags=["finance", "money", "budget"],
        ))

        # 查询与菜谱相关
        results = rec.recommend("cooking recipes food", top_k=2)
        assert len(results) == 2
        # 第一个应该是菜谱相关的
        assert results[0].skill_id == "skill.recipe"
