"""语义意图分类器 V2 单元测试"""
import sys
sys.path.insert(0, "/workspace/agent_cluster")
sys.path.insert(0, "/workspace")

import pytest

from agent_cluster.intent_classifier_v2 import SemanticIntentClassifier
from agent_cluster.intent_classifier import IntentRule


@pytest.fixture
def classifier():
    return SemanticIntentClassifier(semantic_weight=0.3)


def test_exact_match_still_works(classifier):
    result = classifier.classify("记笔记")
    assert result.target_agent == "agent.note"
    assert result.intent == "note.create"
    assert result.confidence == 1.0


def test_synonym_matching(classifier):
    """测试同义词扩展：'记下来' 是 '记笔记' 的同义词"""
    result = classifier.classify("帮我记下来")
    assert result.target_agent == "agent.note"
    assert result.confidence > 0


def test_semantic_similarity_boost(classifier):
    """语义相似度应提升无精确关键词匹配但语义相关的输入"""
    result = classifier.classify("记录一些内容")
    # "记录" 在 note.create 的关键词列表中，但属于包含匹配
    assert result.confidence > 0


def test_semantic_ngram_similarity(classifier):
    """测试内部 n-gram 相似度计算"""
    sim = classifier._calc_semantic_similarity("记笔记", "做个笔记")
    assert sim > 0
    assert sim <= 1.0


def test_fuse_confidence_keyword_dominant(classifier):
    """关键词置信度高时，融合结果以关键词为主"""
    fused = classifier._fuse_confidence(keyword_conf=0.9, semantic_conf=0.5)
    assert fused == 0.9


def test_fuse_confidence_semantic_compensation(classifier):
    """语义置信度高时给予补偿"""
    fused = classifier._fuse_confidence(keyword_conf=0.2, semantic_conf=0.8)
    assert fused > 0.2


def test_fuse_confidence_weighted_average(classifier):
    """一般情况使用加权平均"""
    fused = classifier._fuse_confidence(keyword_conf=0.5, semantic_conf=0.5)
    assert 0.4 <= fused <= 0.6


def test_empty_input(classifier):
    result = classifier.classify("")
    assert result.target_agent == "master_scheduler"
    assert result.confidence == 0.0


def test_fallback_for_unknown(classifier):
    result = classifier.classify("这是完全不相关的输入 xyz123")
    assert result.target_agent == "master_scheduler"
    assert result.intent == "general.fallback"
    assert result.confidence == 0.0


def test_confirm_threshold(classifier):
    result = classifier.classify("做个笔记吧")
    # 包含匹配 confidence=0.6，应触发 confirm
    assert result.requires_confirmation == (0.4 <= result.confidence < 0.7)


def test_synonym_list_not_empty(classifier):
    synonyms = classifier._get_synonyms("记笔记")
    assert len(synonyms) > 0
    assert "记下来" in synonyms


def test_add_custom_rule(classifier):
    classifier.add_rule(IntentRule(
        keywords=["自定义"],
        target_agent="agent.custom",
        intent="custom.action",
    ))
    result = classifier.classify("自定义")
    assert result.target_agent == "agent.custom"


def test_emotion_synonym(classifier):
    """测试情绪同义词：'低落' 是 '难过' 的同义词"""
    result = classifier.classify("我心情很低落")
    assert result.target_agent == "agent.emotion"
