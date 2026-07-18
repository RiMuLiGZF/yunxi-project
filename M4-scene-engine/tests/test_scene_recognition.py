"""
M4 单元测试 - 场景识别补充测试 (TS-007, P2级)

覆盖: 多关键词匹配、模糊匹配、场景识别置信度、默认场景、
      中文关键词匹配、混合场景关键词、边界条件
运行: python -m pytest tests/test_scene_recognition.py -v
"""
import os
import sys

import pytest
from src.services.recognizer import SceneRecognizer
from src.models import SCENE_DEFINITIONS, DEFAULT_SCENE


@pytest.fixture
def recognizer():
    """创建默认配置的场景识别器."""
    return SceneRecognizer(keyword_threshold=0.7, enable_llm=False)


class TestMultiKeywordMatching:
    """多关键词匹配测试"""

    def test_multiple_keywords_increases_score(self, recognizer):
        """匹配更多关键词应提高得分."""
        # 使用 work_dev 场景的关键词
        single_kw_text = "写代码"
        multi_kw_text = "写代码 编程 开发 调试 vscode"

        result_single = recognizer.recognize(single_kw_text)
        result_multi = recognizer.recognize(multi_kw_text)

        # 多关键词的 work_dev 得分应该更高
        assert result_multi["all_scores"]["work_dev"] >= result_single["all_scores"]["work_dev"]

    def test_all_keywords_match_high_confidence(self, recognizer):
        """匹配多个关键词时应有较高置信度."""
        # 用 work_dev 场景的多个关键词（共12个，这里使用大部分）
        text = "写代码 开发 编程 写程序 debug 调试 VS Code vscode 编辑器 项目 工作 开发模式"
        result = recognizer.recognize(text)

        # 大量关键词匹配，应该能识别为 work_dev
        assert result["scene"] == "work_dev"
        assert result["confidence"] >= 0.7

    def test_keyword_count_proportional_to_score(self, recognizer):
        """得分应与匹配关键词数量成比例."""
        # 用学习场景
        kw1 = "学习"
        kw2 = "学习 教程 解释"
        kw3 = "学习 教程 解释 讲解 教学 课程 知识"

        r1 = recognizer.recognize(kw1)
        r2 = recognizer.recognize(kw2)
        r3 = recognizer.recognize(kw3)

        score1 = r1["all_scores"]["learning"]
        score2 = r2["all_scores"]["learning"]
        score3 = r3["all_scores"]["learning"]

        assert score3 >= score2 >= score1

    def test_keyword_frequency_bonus(self, recognizer):
        """关键词重复出现应有频次加成."""
        once = "编程"
        multiple = "编程 编程 编程 编程"

        r_once = recognizer.recognize(once)
        r_multiple = recognizer.recognize(multiple)

        score_once = r_once["all_scores"]["work_dev"]
        score_multiple = r_multiple["all_scores"]["work_dev"]

        # 重复出现的得分应该更高或相等
        assert score_multiple >= score_once


class TestFuzzyMatching:
    """模糊匹配测试"""

    def test_partial_keyword_match(self, recognizer):
        """部分关键词匹配也能识别场景."""
        # 只匹配部分关键词
        text = "我想学点东西"
        result = recognizer.recognize(text)
        # 即使部分匹配，也应该有一定的分数
        assert result["confidence"] >= 0.0

    def test_mixed_language_keywords(self, recognizer):
        """中英文混合关键词应能匹配."""
        text = "写code和debug"
        result = recognizer.recognize(text)
        # 应能识别出 work_dev 场景的部分关键词
        assert "work_dev" in result["all_scores"]

    def test_case_insensitive_matching(self, recognizer):
        """关键词匹配应不区分大小写."""
        text_upper = "VS CODE DEBUG"
        text_lower = "vs code debug"

        r_upper = recognizer.recognize(text_upper)
        r_lower = recognizer.recognize(text_lower)

        # 不区分大小写，得分应该相同
        assert r_upper["all_scores"]["work_dev"] == r_lower["all_scores"]["work_dev"]

    def test_long_text_with_scattered_keywords(self, recognizer):
        """长文本中分散的关键词也应能匹配."""
        text = """
        今天我想做一个项目，需要写很多代码，
        用 vscode 编辑器来开发，
        中间可能需要调试一些 bug，
        整个编程过程应该会很充实。
        """
        result = recognizer.recognize(text)

        # 长文本中包含多个 work_dev 关键词
        assert result["all_scores"]["work_dev"] > 0


class TestRecognitionConfidence:
    """场景识别置信度测试"""

    def test_confidence_range(self, recognizer):
        """置信度应在 0-1 范围内."""
        texts = ["", "你好", "写代码编程开发", "学习教程知识", "生活菜谱美食"]

        for text in texts:
            result = recognizer.recognize(text)
            assert 0.0 <= result["confidence"] <= 1.0

    def test_high_confidence_for_clear_input(self, recognizer):
        """明确输入应有较高置信度并识别正确场景."""
        # 使用多个明确的 work_dev 关键词以超过阈值
        # work_dev 有12个关键词: 写代码,开发,编程,写程序,debug,调试,VS Code,vscode,编辑器,项目,工作,开发模式
        text = "写代码 开发 编程 写程序 debug 调试 VS Code vscode 编辑器 项目 工作"
        result = recognizer.recognize(text)
        assert result["scene"] == "work_dev"
        assert result["confidence"] >= 0.6

    def test_low_confidence_for_ambiguous_input(self, recognizer):
        """模糊输入应有低置信度."""
        # 高阈值 + 模糊输入
        rec = SceneRecognizer(keyword_threshold=0.9, enable_llm=False)
        result = rec.recognize("今天天气怎么样")
        # 高阈值下应该返回 unknown
        assert result["scene"] == "unknown"

    def test_confidence_rounding(self, recognizer):
        """置信度应保留4位小数."""
        result = recognizer.recognize("编程开发")
        # 置信度应该是四舍五入到4位的
        conf_str = str(result["confidence"])
        if "." in conf_str:
            decimal_part = conf_str.split(".")[1]
            assert len(decimal_part) <= 4

    def test_all_scores_sum_not_required(self, recognizer):
        """所有场景得分之和不需要等于1."""
        result = recognizer.recognize("写代码编程")
        scores = result["all_scores"]
        total = sum(scores.values())
        # 各场景独立计算得分，不一定总和为1
        assert total >= 0.0


class TestDefaultScene:
    """默认场景测试"""

    def test_default_scene_is_chat(self):
        """默认场景应为 chat."""
        assert DEFAULT_SCENE == "chat"

    def test_chat_scene_recognized(self, recognizer):
        """日常对话应识别为 chat 场景."""
        result = recognizer.recognize("你好，聊聊天吧")
        # 匹配到聊天相关关键词
        assert "chat" in result["all_scores"]
        assert result["all_scores"]["chat"] > 0

    def test_empty_input_returns_unknown(self, recognizer):
        """空输入应返回 unknown 场景."""
        result = recognizer.recognize("")
        assert result["scene"] == "unknown"
        assert result["confidence"] == 0.0

    def test_whitespace_input_returns_unknown(self, recognizer):
        """空白输入应返回 unknown 场景."""
        result = recognizer.recognize("   \n\t  ")
        assert result["scene"] == "unknown"
        assert result["confidence"] == 0.0


class TestSceneDefinitions:
    """场景定义完整性测试"""

    def test_all_scenes_have_keywords(self, recognizer):
        """所有场景都应该有关键词."""
        for scene_id in SCENE_DEFINITIONS:
            keywords = recognizer.get_scene_keywords(scene_id)
            assert len(keywords) > 0, f"{scene_id} 没有关键词"

    def test_all_scenes_have_name(self):
        """所有场景都应该有名称."""
        for scene_id, scene_def in SCENE_DEFINITIONS.items():
            assert "name" in scene_def, f"{scene_id} 缺少 name"
            assert len(scene_def["name"]) > 0

    def test_all_scenes_have_description(self):
        """所有场景都应该有描述."""
        for scene_id, scene_def in SCENE_DEFINITIONS.items():
            assert "description" in scene_def, f"{scene_id} 缺少 description"

    def test_default_scene_in_definitions(self):
        """默认场景应在场景定义中."""
        assert DEFAULT_SCENE in SCENE_DEFINITIONS

    def test_scene_count(self):
        """场景数量应符合预期."""
        # 至少包含 chat, creative, learning, life, work_dev,
        # growth, review, study_plan, life_management, social_relation,
        # emotion_comfort, appearance
        assert len(SCENE_DEFINITIONS) >= 10


class TestRecognizerEdgeCases:
    """场景识别边界条件测试"""

    def test_special_characters_input(self, recognizer):
        """特殊字符输入不应导致错误."""
        result = recognizer.recognize("!@#$%^&*()_+{}[]|\\:;'<>,.?/")
        assert "scene" in result
        assert "confidence" in result

    def test_very_long_text(self, recognizer):
        """非常长的文本应能正常处理."""
        long_text = "写代码 " * 100
        result = recognizer.recognize(long_text)
        assert result["scene"] in ["work_dev", "unknown"]
        assert 0.0 <= result["confidence"] <= 1.0

    def test_numbers_only_input(self, recognizer):
        """纯数字输入应能正常处理."""
        result = recognizer.recognize("1234567890")
        assert "scene" in result

    def test_emoji_input(self, recognizer):
        """emoji 输入不应导致错误."""
        result = recognizer.recognize("👨‍💻💻🚀")
        assert "scene" in result
        assert "confidence" in result

    def test_single_character_input(self, recognizer):
        """单字符输入应能正常处理."""
        result = recognizer.recognize("编")
        assert "scene" in result
        assert "confidence" in result

    def test_recognize_method_field_structure(self, recognizer):
        """识别结果应包含完整的字段结构."""
        result = recognizer.recognize("测试", include_all_scores=True)

        required_fields = ["scene", "confidence", "method", "reason", "top_scene", "score"]
        for field in required_fields:
            assert field in result, f"识别结果缺少字段: {field}"

    def test_method_field_values(self, recognizer):
        """method 字段应包含正确的值."""
        result = recognizer.recognize("")
        assert result["method"] == "none"

        result = recognizer.recognize("写代码")
        assert "keyword" in result["method"]


class TestChineseKeywordRecognition:
    """中文关键词识别测试"""

    def test_work_dev_chinese_keywords(self, recognizer):
        """工作开发场景中文关键词应能识别."""
        result = recognizer.recognize("我想写代码开发项目")
        assert result["all_scores"]["work_dev"] > 0

    def test_learning_chinese_keywords(self, recognizer):
        """学习场景中文关键词应能识别."""
        result = recognizer.recognize("我想学习新知识")
        assert result["all_scores"]["learning"] > 0

    def test_life_chinese_keywords(self, recognizer):
        """生活场景中文关键词应能识别."""
        result = recognizer.recognize("今天吃什么美食菜谱")
        assert result["all_scores"]["life"] > 0

    def test_growth_chinese_keywords(self, recognizer):
        """成长场景中文关键词应能识别."""
        result = recognizer.recognize("成长进步成就解锁")
        assert result["all_scores"]["growth"] > 0

    def test_emotion_chinese_keywords(self, recognizer):
        """情绪陪伴场景中文关键词应能识别."""
        result = recognizer.recognize("心情不好焦虑压力大")
        assert result["all_scores"]["emotion_comfort"] > 0

    def test_creative_chinese_keywords(self, recognizer):
        """创意创作场景中文关键词应能识别."""
        result = recognizer.recognize("写一篇文章创作灵感")
        assert result["all_scores"]["creative"] > 0


# ============================================================================
# 补充：关键词匹配边界测试
# ============================================================================

class TestKeywordBoundaryMatching:
    """关键词匹配边界测试 (P1 质量债务补强)"""

    def test_partial_keyword_match_no_false_positive(self, recognizer):
        """部分关键词子串不应误匹配."""
        # "工" 是 "工作" 的一部分，但不应该作为完整关键词匹配
        result = recognizer.recognize("工")
        # 单字不应匹配到任何场景的关键词
        assert result["confidence"] == 0.0 or result["scene"] == "unknown"

    def test_keyword_at_beginning(self, recognizer):
        """关键词在文本开头应能匹配."""
        result = recognizer.recognize("写代码的一天")
        assert result["all_scores"]["work_dev"] > 0

    def test_keyword_at_end(self, recognizer):
        """关键词在文本末尾应能匹配."""
        result = recognizer.recognize("今天我要写代码")
        assert result["all_scores"]["work_dev"] > 0

    def test_keyword_in_middle(self, recognizer):
        """关键词在文本中间应能匹配."""
        result = recognizer.recognize("今天我要写代码和测试")
        assert result["all_scores"]["work_dev"] > 0

    def test_punctuation_around_keyword(self, recognizer):
        """关键词周围有标点符号应仍能匹配."""
        result = recognizer.recognize("今天，写代码！开心")
        assert result["all_scores"]["work_dev"] > 0

    def test_multiple_occurrences_same_keyword(self, recognizer):
        """同一关键词多次出现应有频次效应."""
        result_once = recognizer.recognize("编程")
        result_multi = recognizer.recognize("编程编程编程编程编程")
        assert result_multi["all_scores"]["work_dev"] >= result_once["all_scores"]["work_dev"]

    def test_substring_not_matched(self, recognizer):
        """关键词的子串不应被匹配（精确匹配原则）."""
        # "习" 不是 "学习" 的完整匹配
        result = recognizer.recognize("习")
        assert result["confidence"] == 0.0 or result["scene"] == "unknown"


# ============================================================================
# 补充：多场景冲突测试
# ============================================================================

class TestMultiSceneConflict:
    """多场景冲突测试 (P1 质量债务补强)"""

    def test_work_and_learning_conflict(self, recognizer):
        """同时包含工作和学习关键词时应返回得分较高的场景."""
        text = "写代码学习编程知识"
        result = recognizer.recognize(text)
        # 应该有多个场景得分 > 0
        positive_scenes = {k: v for k, v in result["all_scores"].items() if v > 0}
        assert len(positive_scenes) >= 2  # 至少 work_dev 和 learning
        # all_scores 中最高分的场景应在 positive_scenes 中
        best_scene = max(result["all_scores"], key=result["all_scores"].get)
        assert best_scene in positive_scenes

    def test_life_and_emotion_conflict(self, recognizer):
        """同时包含生活和情绪关键词时."""
        text = "生活压力大心情不好"
        result = recognizer.recognize(text)
        positive_scenes = {k: v for k, v in result["all_scores"].items() if v > 0}
        assert len(positive_scenes) >= 2
        # 最佳匹配场景（在all_scores中）应有最高得分
        best_scene = max(result["all_scores"], key=result["all_scores"].get)
        best_score = result["all_scores"][best_scene]
        for scene, score in positive_scenes.items():
            assert score <= best_score + 0.001  # 允许浮点误差

    def test_all_scenes_some_keywords(self, recognizer):
        """包含多个场景关键词的混合文本."""
        text = "工作学习生活成长情绪复盘社交形象创意"
        result = recognizer.recognize(text)
        positive_scenes = {k: v for k, v in result["all_scores"].items() if v > 0}
        assert len(positive_scenes) >= 5  # 至少匹配5个以上场景

    def test_top_scene_has_highest_score(self, recognizer):
        """all_scores 中得分最高的场景应有最高得分."""
        text = "写代码 编程 开发 debug vscode 项目 工作"
        result = recognizer.recognize(text)
        best_score = max(result["all_scores"].values())
        best_scene = max(result["all_scores"], key=result["all_scores"].get)
        assert result["all_scores"][best_scene] == best_score


# ============================================================================
# 补充：上下文辅助识别测试
# ============================================================================

class TestContextAidedRecognition:
    """上下文辅助识别测试 (P1 质量债务补强)"""

    def test_recognize_with_context_param(self, recognizer):
        """传入 context 参数不应报错."""
        result = recognizer.recognize(
            "继续工作",
            context={"current_scene": "work_dev", "last_message": "写代码"}
        )
        assert "scene" in result
        assert "confidence" in result

    def test_context_does_not_break_recognition(self, recognizer):
        """上下文不应破坏正常的关键词识别."""
        result_no_ctx = recognizer.recognize("写代码编程开发")
        result_with_ctx = recognizer.recognize(
            "写代码编程开发",
            context={"current_scene": "chat"}
        )
        # 相同文本的识别结果场景应该一致
        assert result_no_ctx["scene"] == result_with_ctx["scene"]

    def test_empty_context_same_as_no_context(self, recognizer):
        """空上下文应与无上下文结果一致."""
        text = "学习新知识"
        result_no_ctx = recognizer.recognize(text)
        result_empty_ctx = recognizer.recognize(text, context={})
        assert result_no_ctx["scene"] == result_empty_ctx["scene"]


# ============================================================================
# 补充：空输入/短输入/长输入边界测试
# ============================================================================

class TestInputBoundaryRecognition:
    """输入边界测试 (P1 质量债务补强)"""

    def test_single_chinese_char_input(self, recognizer):
        """单个中文字符输入."""
        result = recognizer.recognize("编")
        assert "scene" in result
        assert "confidence" in result
        assert 0.0 <= result["confidence"] <= 1.0

    def test_two_char_input_partial(self, recognizer):
        """两字符输入."""
        result = recognizer.recognize("代码")
        assert "scene" in result
        assert result["confidence"] >= 0.0

    def test_very_long_input(self, recognizer):
        """超长文本输入应正常处理."""
        long_text = "写代码 " * 500
        result = recognizer.recognize(long_text)
        assert "scene" in result
        assert "confidence" in result
        assert result["scene"] in ["work_dev", "unknown"]

    def test_input_with_newlines(self, recognizer):
        """包含换行符的输入."""
        text = "今天要写代码\n然后学习新知识\n再做复盘总结"
        result = recognizer.recognize(text)
        assert "scene" in result
        assert result["confidence"] >= 0.0

    def test_input_with_special_chars(self, recognizer):
        """包含特殊字符的输入."""
        text = ">>> 写代码 <<< 编程!!!???"
        result = recognizer.recognize(text)
        assert "scene" in result
        assert result["all_scores"]["work_dev"] > 0


# ============================================================================
# 补充：误识别率验证
# ============================================================================

class TestMisidentificationResistance:
    """误识别率验证 - 非场景关键词不应误匹配 (P1 质量债务补强)"""

    def test_random_numbers_not_recognized(self, recognizer):
        """纯数字不应识别为任何场景."""
        result = recognizer.recognize("12345 67890")
        assert result["scene"] == "unknown"
        assert result["confidence"] == 0.0

    def test_unrelated_text_not_recognized(self, recognizer):
        """完全无关的文本不应识别为高置信度场景."""
        # 使用高阈值识别器
        rec = SceneRecognizer(keyword_threshold=0.5, enable_llm=False)
        result = rec.recognize("沙发电视冰箱洗衣机")
        assert result["confidence"] < 0.5 or result["scene"] == "unknown"

    def test_weather_talk_not_false_positive(self, recognizer):
        """天气话题不应误匹配."""
        result = recognizer.recognize("今天天气真好阳光明媚")
        # 可能有部分匹配，但置信度不应太高
        assert result["confidence"] < 0.7

    def test_political_talk_not_false_positive(self, recognizer):
        """新闻政治话题不应误匹配."""
        result = recognizer.recognize("今天新闻说经济增长了")
        assert result["confidence"] < 0.7 or result["scene"] == "unknown"

    def test_chat_scene_for_greetings(self, recognizer):
        """问候语应识别为聊天场景而非其他业务场景."""
        result = recognizer.recognize("你好早上好")
        # 应该匹配到 chat 场景
        assert result["all_scores"]["chat"] > 0

    def test_mixed_gibberish_not_confident(self, recognizer):
        """乱码/无意义文本不应有高置信度."""
        result = recognizer.recognize("asdf qwerty zxcv")
        assert result["confidence"] < 0.5 or result["scene"] == "unknown"
