from __future__ import annotations

import pytest

from skill_cluster.interfaces import SkillManifest
from skill_cluster.skill_recommender import SkillRecommender, SkillRecommendation


def _make_manifest(
    skill_id: str, name: str, desc: str, tags: list[str] | None = None, caps: list[str] | None = None
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


def test_recommend_basic() -> None:
    rec = SkillRecommender()
    rec.register_profile(_make_manifest(
        "skill.doc_parse", "Document Parser", "Parse PDF and Word documents",
        tags=["document", "parser"],
        caps=["parse_pdf", "parse_docx"],
    ))
    rec.register_profile(_make_manifest(
        "skill.web_fetch", "Web Fetcher", "Fetch web pages and extract text",
        tags=["web", "fetch"],
        caps=["fetch_url", "extract_text"],
    ))

    results = rec.recommend("parse PDF document", top_k=2)
    assert len(results) == 2
    # doc_parse 应该排在前面
    assert results[0].skill_id == "skill.doc_parse"
    assert results[0].score > 0


def test_recommend_no_match() -> None:
    rec = SkillRecommender()
    rec.register_profile(_make_manifest(
        "skill.calc", "Calculator", "Math calculations",
    ))
    results = rec.recommend("fly to moon", top_k=5)
    # 无匹配时仍有结果（所有技能评分都很低）
    assert len(results) == 1


def test_recommend_exclude() -> None:
    rec = SkillRecommender()
    rec.register_profile(_make_manifest(
        "skill.a", "Alpha", "test skill a",
    ))
    rec.register_profile(_make_manifest(
        "skill.b", "Beta", "test skill b",
    ))

    results = rec.recommend("test", top_k=5, exclude_skills=["skill.a"])
    assert len(results) == 1
    assert results[0].skill_id == "skill.b"


def test_recommend_reasons() -> None:
    rec = SkillRecommender()
    rec.register_profile(_make_manifest(
        "skill.translate", "Translator", "Translate text between languages",
        caps=["translate_en", "translate_zh"],
    ))

    results = rec.recommend("translate English to Chinese", top_k=1)
    assert len(results[0].reasons) > 0


def test_recommend_with_memory() -> None:
    from skill_cluster.agent_memory import AgentMemory

    memory = AgentMemory("agent1")
    memory.add_long_term(
        "用户经常使用 skill.doc_parse 解析文档",
        tags=["skill:skill.doc_parse", "preference"],
        importance=8.0,
    )

    rec = SkillRecommender(memory=memory)
    rec.register_profile(_make_manifest(
        "skill.doc_parse", "Doc Parser", "Parse documents",
        tags=["doc"],
    ))
    rec.register_profile(_make_manifest(
        "skill.img_gen", "Image Gen", "Generate images",
        tags=["image"],
    ))

    results = rec.recommend("parse document", top_k=2, agent_id="agent1")
    # doc_parse 应因为记忆偏好而排在前面
    assert results[0].skill_id == "skill.doc_parse"


def test_set_weights() -> None:
    rec = SkillRecommender()
    rec.set_weights({"keyword": 0.8, "experience": 0.2})
    # 检查归一化后总和为 1
    total = sum(rec._weights.values())
    assert abs(total - 1.0) < 0.01


def test_recommend_match_dimensions() -> None:
    rec = SkillRecommender()
    rec.register_profile(_make_manifest(
        "skill.search", "Search", "Search for information",
        caps=["search_web"],
    ))

    results = rec.recommend("search information", top_k=1)
    dims = results[0].match_dimensions
    assert "keyword" in dims
    assert "capability" in dims
    assert "experience" in dims


def test_recommend_empty() -> None:
    rec = SkillRecommender()
    results = rec.recommend("do something", top_k=5)
    assert results == []
