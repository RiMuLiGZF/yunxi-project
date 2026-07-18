"""SceneRecognizer 单元测试.

测试 SceneRecognizer 的核心功能：
- 关键词匹配得分计算
- 场景识别基本逻辑
- 阈值控制
- 关键词动态更新
- 长文本惩罚/频次加成
- 空输入处理
"""

import os
import sys

import pytest
from src.services.recognizer import SceneRecognizer
from src.models import SCENE_DEFINITIONS


@pytest.fixture
def recognizer():
    """创建默认配置的场景识别器."""
    return SceneRecognizer(keyword_threshold=0.7, enable_llm=False)


class TestSceneRecognizer:
    """SceneRecognizer 测试类."""

    # ------------------------------------------------------------------
    # 基础识别测试
    # ------------------------------------------------------------------

    def test_recognize_empty_text(self, recognizer):
        """空文本应返回 unknown."""
        result = recognizer.recognize("")
        assert result["scene"] == "unknown"
        assert result["confidence"] == 0.0
        assert result["method"] == "none"

    def test_recognize_whitespace_text(self, recognizer):
        """纯空白文本应返回 unknown."""
        result = recognizer.recognize("   \n\t  ")
        assert result["scene"] == "unknown"
        assert result["confidence"] == 0.0

    def test_recognize_returns_all_scores(self, recognizer):
        """include_all_scores=True 时应返回 all_scores 字段."""
        result = recognizer.recognize("写代码编程开发", include_all_scores=True)
        assert "all_scores" in result
        assert "scores" in result
        assert isinstance(result["all_scores"], dict)
        # 所有场景都应该有得分
        for scene_id in SCENE_DEFINITIONS:
            assert scene_id in result["all_scores"]

    def test_recognize_without_all_scores(self, recognizer):
        """include_all_scores=False 时不应返回 all_scores 字段."""
        result = recognizer.recognize("写代码", include_all_scores=False)
        assert "all_scores" not in result
        assert "scores" not in result

    def test_recognize_returns_reason(self, recognizer):
        """识别结果应包含 reason 字段."""
        result = recognizer.recognize("编程开发")
        assert "reason" in result
        assert isinstance(result["reason"], str)
        assert len(result["reason"]) > 0

    def test_recognize_top_scene_field(self, recognizer):
        """识别结果应包含 top_scene 字段."""
        result = recognizer.recognize("编程开发")
        assert "top_scene" in result
        assert result["top_scene"] == result["scene"]

    # ------------------------------------------------------------------
    # 关键词得分计算测试
    # ------------------------------------------------------------------

    def test_calc_keyword_score_no_match(self, recognizer):
        """完全不匹配时得分为 0."""
        score, matched = recognizer._calc_keyword_score(
            "hello world", ["编程", "开发", "代码"]
        )
        assert score == 0.0
        assert matched == []

    def test_calc_keyword_score_full_match(self, recognizer):
        """全部匹配时得分应较高."""
        score, matched = recognizer._calc_keyword_score(
            "编程 开发 代码", ["编程", "开发", "代码"]
        )
        assert score > 0.5
        assert len(matched) == 3

    def test_calc_keyword_score_partial_match(self, recognizer):
        """部分匹配时得分按比例计算."""
        score, matched = recognizer._calc_keyword_score(
            "编程开发", ["编程", "开发", "代码", "调试", "部署"]
        )
        assert 0 < score < 1.0
        assert len(matched) == 2

    def test_calc_keyword_score_empty_keywords(self, recognizer):
        """空关键词列表得分为 0."""
        score, matched = recognizer._calc_keyword_score("test text", [])
        assert score == 0.0
        assert matched == []

    def test_calc_keyword_score_frequency_bonus(self, recognizer):
        """关键词多次出现应有频次加成（不超过上限）."""
        # 同一关键词出现多次
        text = "编程 编程 编程 编程 编程"
        score, matched = recognizer._calc_keyword_score(text, ["编程"])
        assert score > 0.0
        assert len(matched) == 1  # matched 列表只去重记录

    def test_calc_keyword_score_long_text_penalty(self, recognizer):
        """长文本应有惩罚因子."""
        short_text = "编程开发"
        long_text = "编程开发" + "啊" * 600  # 超过 500 字符

        score_short, _ = recognizer._calc_keyword_score(short_text, ["编程", "开发"])
        score_long, _ = recognizer._calc_keyword_score(long_text, ["编程", "开发"])

        # 长文本得分应该更低或相等（因为惩罚因子）
        assert score_long <= score_short

    # ------------------------------------------------------------------
    # 阈值控制测试
    # ------------------------------------------------------------------

    def test_threshold_blocks_low_score(self):
        """设置高阈值时低置信度应返回 unknown."""
        # 设置非常高的阈值
        rec = SceneRecognizer(keyword_threshold=0.99, enable_llm=False)
        result = rec.recognize("今天天气真不错呢")
        # 阈值很高时应该返回 unknown
        assert result["scene"] == "unknown"
        assert "confidence" in result
        assert 0 <= result["confidence"] <= 1.0

    def test_update_threshold_clamped(self, recognizer):
        """更新阈值应被限制在 0-1 范围."""
        recognizer.update_threshold(1.5)
        assert recognizer.keyword_threshold == 1.0

        recognizer.update_threshold(-0.5)
        assert recognizer.keyword_threshold == 0.0

        recognizer.update_threshold(0.5)
        assert recognizer.keyword_threshold == 0.5

    def test_threshold_zero_always_matches(self):
        """阈值为 0 时任何输入都会返回最佳匹配场景."""
        rec = SceneRecognizer(keyword_threshold=0.0)
        result = rec.recognize("随便写点什么")
        # 阈值为 0 时，最高分场景应该被选中（不是 unknown）
        # 除非所有场景得分都是 0
        if result["confidence"] > 0:
            assert result["scene"] != "unknown"

    # ------------------------------------------------------------------
    # 关键词动态更新测试
    # ------------------------------------------------------------------

    def test_update_scene_keywords_success(self, recognizer):
        """更新存在场景的关键词应成功."""
        result = recognizer.update_scene_keywords("work_dev", ["新关键词1", "新关键词2"])
        assert result is True
        assert recognizer.get_scene_keywords("work_dev") == ["新关键词1", "新关键词2"]

    def test_update_scene_keywords_invalid_scene(self, recognizer):
        """更新不存在场景的关键词应返回 False."""
        result = recognizer.update_scene_keywords("nonexistent", ["test"])
        assert result is False

    def test_get_scene_keywords_default(self, recognizer):
        """获取默认场景关键词."""
        keywords = recognizer.get_scene_keywords("work_dev")
        assert isinstance(keywords, list)
        assert len(keywords) > 0  # 预定义场景应该有关键词

    def test_get_scene_keywords_not_exists(self, recognizer):
        """获取不存在场景的关键词应返回空列表."""
        keywords = recognizer.get_scene_keywords("nonexistent")
        assert keywords == []

    def test_update_keywords_affects_recognition(self, recognizer):
        """更新关键词应影响识别结果."""
        # 先确保 "测试场景" 这个关键词不在任何场景中
        test_kw = "超级独特测试关键词xyz123"

        # 更新 work_dev 的关键词
        recognizer.update_scene_keywords("work_dev", [test_kw])

        # 用该关键词测试
        result = recognizer.recognize(test_kw)
        assert result["scene"] == "work_dev"
        assert result["confidence"] > 0.7

    # ------------------------------------------------------------------
    # LLM 配置测试
    # ------------------------------------------------------------------

    def test_llm_disabled_by_default(self, recognizer):
        """默认不启用 LLM."""
        assert recognizer.enable_llm is False
        assert recognizer.llm_base_url == ""

    def test_llm_config_direct_set(self):
        """直接设置 LLM 配置."""
        rec = SceneRecognizer(
            keyword_threshold=0.5,
            enable_llm=True,
            llm_base_url="http://localhost:11434",
            llm_model_name="test-model",
        )
        assert rec.enable_llm is True
        assert rec.llm_base_url == "http://localhost:11434"
        assert rec.llm_model_name == "test-model"

    def test_llm_disabled_skips_enhancement(self):
        """LLM 未启用时即使低于阈值也不调用 LLM."""
        rec = SceneRecognizer(keyword_threshold=0.99, enable_llm=False)
        result = rec.recognize("模糊输入测试")
        # 不应该有 method=llm 的结果
        assert result["method"] in ("keyword", "none")
        # 因为阈值很高，应该返回 unknown
        assert result["scene"] == "unknown"

    # ------------------------------------------------------------------
    # 场景定义测试
    # ------------------------------------------------------------------

    def test_all_scenes_have_keywords(self, recognizer):
        """所有预定义场景都应该有关键词."""
        for scene_id in SCENE_DEFINITIONS:
            keywords = recognizer.get_scene_keywords(scene_id)
            assert isinstance(keywords, list), f"{scene_id} 关键词不是列表"
            # 至少有一个关键词
            assert len(keywords) > 0, f"{scene_id} 没有关键词"

    def test_scene_definitions_structure(self):
        """SCENE_DEFINITIONS 结构应正确."""
        assert isinstance(SCENE_DEFINITIONS, dict)
        assert len(SCENE_DEFINITIONS) > 0

        for scene_id, scene_def in SCENE_DEFINITIONS.items():
            assert "name" in scene_def, f"{scene_id} 缺少 name"
            assert "description" in scene_def, f"{scene_id} 缺少 description"
            assert "keywords" in scene_def, f"{scene_id} 缺少 keywords"
            assert isinstance(scene_def["keywords"], list)
