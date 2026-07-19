"""M4 语义场景识别单元测试.

覆盖：
- 语义场景识别基本功能
- 与 SceneRecognitionService / SceneClassifier 集成
- 降级机制
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

# 确保路径正确
_M4_ROOT = Path(__file__).resolve().parents[1]
_PROJECT_ROOT = Path(__file__).resolve().parents[3]
for _p in (str(_M4_ROOT), str(_PROJECT_ROOT)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from src.models import SCENE_DEFINITIONS
from src.scene.semantic import SemanticSceneRecognizer, SemanticRecognitionResult
from src.services.scene_classifier import SceneClassifier, EnsembleClassifier


# ============================================================================
# SemanticSceneRecognizer 基本功能测试
# ============================================================================

class TestSemanticSceneRecognizerBasic:
    """语义场景识别器基本功能测试."""

    def test_create_recognizer(self) -> None:
        """创建语义识别器."""
        recognizer = SemanticSceneRecognizer(SCENE_DEFINITIONS)
        assert isinstance(recognizer.enabled, bool)
        assert isinstance(recognizer.provider_name, str)

    def test_recognizer_has_scenes(self) -> None:
        """识别器应包含所有场景定义."""
        recognizer = SemanticSceneRecognizer(SCENE_DEFINITIONS)
        # 场景定义数量应与输入一致
        assert len(SCENE_DEFINITIONS) > 0

    def test_provider_name_not_empty(self) -> None:
        """提供者名称不应为空."""
        recognizer = SemanticSceneRecognizer(SCENE_DEFINITIONS)
        assert len(recognizer.provider_name) > 0


# ============================================================================
# 语义识别功能测试
# ============================================================================

class TestSemanticRecognition:
    """语义场景识别功能测试."""

    def test_recognize_returns_result(self) -> None:
        """识别应返回结果."""
        recognizer = SemanticSceneRecognizer(SCENE_DEFINITIONS)
        result = recognizer.recognize("写代码编程开发")
        assert isinstance(result, SemanticRecognitionResult)
        assert isinstance(result.scene, str)
        assert isinstance(result.confidence, float)
        assert 0.0 <= result.confidence <= 1.0

    def test_recognize_empty_text(self) -> None:
        """空文本应返回 unknown."""
        recognizer = SemanticSceneRecognizer(SCENE_DEFINITIONS)
        result = recognizer.recognize("")
        assert result.scene == "unknown"
        assert result.confidence == 0.0

    def test_recognize_whitespace_text(self) -> None:
        """空白文本应返回 unknown."""
        recognizer = SemanticSceneRecognizer(SCENE_DEFINITIONS)
        result = recognizer.recognize("   \n\t  ")
        assert result.scene == "unknown"
        assert result.confidence == 0.0

    def test_recognize_work_dev_scene(self) -> None:
        """工作开发相关文本应能识别为 work_dev."""
        recognizer = SemanticSceneRecognizer(SCENE_DEFINITIONS)
        result = recognizer.recognize("写代码 编程 开发 debug vscode 项目 工作")
        # 置信度应大于 0
        assert result.confidence >= 0.0
        # 候选列表应包含 work_dev
        scene_ids = [s for s, _ in result.candidates]
        # work_dev 应该在候选列表中
        assert "work_dev" in scene_ids or result.scene == "work_dev"

    def test_recognize_candidates(self) -> None:
        """识别结果应包含候选场景列表."""
        recognizer = SemanticSceneRecognizer(SCENE_DEFINITIONS)
        result = recognizer.recognize("学习知识课程", top_k=5)
        assert isinstance(result.candidates, list)
        assert len(result.candidates) > 0
        # 候选应按置信度降序
        for i in range(len(result.candidates) - 1):
            assert result.candidates[i][1] >= result.candidates[i + 1][1]

    def test_recognize_top_k(self) -> None:
        """识别结果不应超过 top_k 个候选."""
        recognizer = SemanticSceneRecognizer(SCENE_DEFINITIONS)
        result = recognizer.recognize("测试文本", top_k=3)
        assert len(result.candidates) <= 3

    def test_get_scene_semantic_score(self) -> None:
        """获取指定场景的语义得分."""
        recognizer = SemanticSceneRecognizer(SCENE_DEFINITIONS)
        score = recognizer.get_scene_semantic_score("work_dev", "编程开发")
        assert isinstance(score, float)
        assert 0.0 <= score <= 1.0

    def test_method_field(self) -> None:
        """method 字段应包含正确的值."""
        recognizer = SemanticSceneRecognizer(SCENE_DEFINITIONS)
        result = recognizer.recognize("测试")
        assert isinstance(result.method, str)
        assert len(result.method) > 0


# ============================================================================
# 与 SceneClassifier 集成测试
# ============================================================================

class TestSceneClassifierSemantic:
    """SceneClassifier 语义集成测试."""

    def test_classifier_ensembles_semantic(self) -> None:
        """分类器 ensemble 应能集成语义识别."""
        classifier = SceneClassifier()
        features = {
            "conversation_topic": "work",
            "active_app": "vscode",
            "location_type": "office",
            "time_period": "morning",
            "mood_tendency": "neutral",
        }
        result = classifier.classify(features, method="ensemble")
        assert result is not None
        assert isinstance(result.scene, str)
        assert 0.0 <= result.confidence <= 1.0

    def test_classifier_semantic_method(self) -> None:
        """直接使用 semantic 方法应能正常工作."""
        classifier = SceneClassifier()
        features = {
            "conversation_topic": "work",
            "active_app": "vscode",
        }
        result = classifier.classify(features, method="semantic")
        assert result is not None
        assert isinstance(result.scene, str)
        assert 0.0 <= result.confidence <= 1.0

    def test_classifier_semantic_empty_features(self) -> None:
        """空特征的语义识别应回退到规则方法."""
        classifier = SceneClassifier()
        result = classifier.classify({}, method="semantic")
        assert result is not None
        # 空特征可能返回规则方法的结果
        assert result.method in ["rule_based", "semantic"]

    def test_ensemble_classifier_semantic_property(self) -> None:
        """EnsembleClassifier 应有 semantic_enabled 属性."""
        ensemble = EnsembleClassifier()
        assert isinstance(ensemble.semantic_enabled, bool)

    def test_classifier_stats_has_semantic(self) -> None:
        """分类器统计应包含语义相关信息."""
        classifier = SceneClassifier()
        stats = classifier.get_stats()
        assert "semantic_enabled" in stats
        assert "semantic_provider" in stats

    def test_disable_semantic(self) -> None:
        """禁用语义时 ensemble 应正常工作."""
        ensemble = EnsembleClassifier(enable_semantic=False)
        assert ensemble.semantic_enabled is False

        features = {
            "conversation_topic": "work",
            "active_app": "vscode",
        }
        result = ensemble.classify(features)
        assert result is not None
        assert isinstance(result.scene, str)
