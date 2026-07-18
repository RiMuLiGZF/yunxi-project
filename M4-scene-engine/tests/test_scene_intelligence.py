"""场景引擎智能化测试.

测试场景预测引擎和场景模板市场。
"""

import sys
import time
from pathlib import Path

import pytest

# 确保可以导入 src 模块
SRC_DIR = Path(__file__).resolve().parent.parent / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))


# ===========================================================================
# 场景预测引擎测试
# ===========================================================================

class TestMarkovChainPredictor:
    """马尔可夫链预测器测试."""

    def test_initial_state(self):
        from src.services.scene_predictor import MarkovChainPredictor
        predictor = MarkovChainPredictor()
        assert predictor.predict("work") == []

    def test_single_transition(self):
        from src.services.scene_predictor import MarkovChainPredictor
        predictor = MarkovChainPredictor()
        predictor.record_transition("work", "rest")
        result = predictor.predict("work")
        assert len(result) == 1
        assert result[0][0] == "rest"
        assert result[0][1] == 1.0

    def test_multiple_transitions(self):
        from src.services.scene_predictor import MarkovChainPredictor
        predictor = MarkovChainPredictor()
        predictor.record_transition("work", "rest")
        predictor.record_transition("work", "rest")
        predictor.record_transition("work", "entertainment")
        result = predictor.predict("work")
        assert len(result) == 2
        assert result[0][0] == "rest"
        assert abs(result[0][1] - 2/3) < 0.01

    def test_top_n(self):
        from src.services.scene_predictor import MarkovChainPredictor
        predictor = MarkovChainPredictor()
        for i in range(5):
            predictor.record_transition("a", "b")
        for i in range(3):
            predictor.record_transition("a", "c")
        predictor.record_transition("a", "d")
        result = predictor.predict("a", top_n=2)
        assert len(result) == 2
        assert result[0][0] == "b"

    def test_transition_matrix(self):
        from src.services.scene_predictor import MarkovChainPredictor
        predictor = MarkovChainPredictor()
        predictor.record_transition("work", "rest")
        predictor.record_transition("rest", "sleep")
        matrix = predictor.get_transition_matrix()
        assert "work" in matrix
        assert "rest" in matrix
        assert matrix["work"]["rest"] == 1.0


class TestPatternMatcher:
    """模式匹配预测器测试."""

    def test_initial_state(self):
        from src.services.scene_predictor import PatternMatcher
        matcher = PatternMatcher()
        result = matcher.predict_at(time.time())
        assert result == []

    def test_record_and_predict(self):
        from src.services.scene_predictor import PatternMatcher
        matcher = PatternMatcher()
        now = time.time()
        matcher.record_scene_at("work", now)
        matcher.record_scene_at("work", now)
        matcher.record_scene_at("rest", now)
        result = matcher.predict_at(now)
        assert len(result) > 0
        assert result[0][0] == "work"

    def test_multiple_time_slots(self):
        from src.services.scene_predictor import PatternMatcher
        from datetime import datetime, timedelta
        matcher = PatternMatcher()

        # 模拟早晨工作
        morning = datetime.now().replace(hour=9, minute=0).timestamp()
        for _ in range(5):
            matcher.record_scene_at("work", morning)

        # 模拟晚上娱乐
        evening = datetime.now().replace(hour=20, minute=0).timestamp()
        for _ in range(5):
            matcher.record_scene_at("entertainment", evening)

        morning_result = matcher.predict_at(morning)
        evening_result = matcher.predict_at(evening)

        assert morning_result[0][0] == "work"
        assert evening_result[0][0] == "entertainment"


class TestContextPredictor:
    """上下文预测器测试."""

    def test_initial_state(self):
        from src.services.scene_predictor import ContextPredictor
        predictor = ContextPredictor()
        result = predictor.predict({})
        assert result == []

    def test_context_matching(self):
        from src.services.scene_predictor import ContextPredictor
        predictor = ContextPredictor()
        predictor.record({"time_of_day": "morning", "location_type": "office"}, "work")
        predictor.record({"time_of_day": "morning", "location_type": "office"}, "work")
        predictor.record({"time_of_day": "evening", "location_type": "home"}, "rest")

        result = predictor.predict({"time_of_day": "morning", "location_type": "office"})
        assert len(result) > 0
        assert result[0][0] == "work"

    def test_partial_match(self):
        from src.services.scene_predictor import ContextPredictor
        predictor = ContextPredictor()
        predictor.record({"time_of_day": "morning", "location_type": "office"}, "work")

        # 只匹配时间
        result = predictor.predict({"time_of_day": "morning"})
        assert len(result) > 0


class TestScenePredictor:
    """场景预测引擎集成测试."""

    def test_initial_state(self):
        from src.services.scene_predictor import ScenePredictor
        predictor = ScenePredictor()
        result = predictor.predict_next("work")
        assert result.confidence == 0.0

    def test_prediction_with_data(self):
        from src.services.scene_predictor import ScenePredictor
        predictor = ScenePredictor()

        for _ in range(10):
            predictor.record_transition("work", "rest")
        for _ in range(5):
            predictor.record_transition("work", "entertainment")

        result = predictor.predict_next("work")
        assert result.predicted_scene == "rest"
        assert result.confidence > 0
        assert len(result.candidates) > 0
        assert result.method == "ensemble"
        assert result.explanation != ""

    def test_predict_scene_at(self):
        from src.services.scene_predictor import ScenePredictor
        predictor = ScenePredictor()

        now = time.time()
        for _ in range(5):
            predictor.record_transition("a", "work", timestamp=now)

        result = predictor.predict_scene_at(now)
        assert isinstance(result.confidence, float)

    def test_prediction_history(self):
        from src.services.scene_predictor import ScenePredictor
        predictor = ScenePredictor()

        for _ in range(5):
            predictor.record_transition("work", "rest")

        predictor.predict_next("work")
        stats = predictor.get_prediction_stats()
        assert stats["total_predictions"] >= 1

    def test_accuracy_evaluation(self):
        from src.services.scene_predictor import ScenePredictor
        predictor = ScenePredictor()

        for _ in range(10):
            predictor.record_transition("work", "rest")

        predictor.predict_next("work")
        accuracy = predictor.evaluate_accuracy("rest")
        assert "accuracy" in accuracy
        assert 0 <= accuracy["accuracy"] <= 1

    def test_train_with_history(self):
        from src.services.scene_predictor import ScenePredictor
        predictor = ScenePredictor()

        sequence = ["work", "rest", "sleep", "work", "rest", "entertainment", "sleep"]
        result = predictor.train_with_history_data(sequence)

        assert result["sequence_length"] == 7
        assert result["transitions_recorded"] == 6
        assert result["unique_scenes"] == 4

        # 训练后应该能预测
        pred = predictor.predict_next("work")
        assert pred.confidence > 0

    def test_markov_only_mode(self):
        from src.services.scene_predictor import ScenePredictor
        predictor = ScenePredictor(enable_ensemble=False)

        for _ in range(5):
            predictor.record_transition("work", "rest")

        result = predictor.predict_next("work")
        assert result.method == "markov"


# ===========================================================================
# 场景模板市场测试
# ===========================================================================

class TestBuiltinTemplates:
    """内置模板测试."""

    def test_builtin_templates_exist(self):
        from src.services.scene_template_service import BUILTIN_TEMPLATES
        assert len(BUILTIN_TEMPLATES) > 10

    def test_template_structure(self):
        from src.services.scene_template_service import BUILTIN_TEMPLATES
        for tpl in BUILTIN_TEMPLATES:
            assert "id" in tpl
            assert "name" in tpl
            assert "description" in tpl
            assert "category" in tpl
            assert "settings" in tpl
            assert "icon" in tpl

    def test_categories_coverage(self):
        from src.services.scene_template_service import BUILTIN_TEMPLATES
        categories = set(tpl["category"] for tpl in BUILTIN_TEMPLATES)
        # 至少覆盖工作、学习、娱乐、运动、睡眠等大类
        assert len(categories) >= 5


class TestSceneTemplateService:
    """场景模板服务测试."""

    def test_list_templates(self):
        from src.services.scene_template_service import SceneTemplateService
        service = SceneTemplateService()
        result = service.list_templates()
        assert result["total"] > 0
        assert len(result["items"]) > 0
        assert result["page"] == 1

    def test_list_templates_pagination(self):
        from src.services.scene_template_service import SceneTemplateService
        service = SceneTemplateService()
        result = service.list_templates(page=1, page_size=5)
        assert len(result["items"]) <= 5
        assert result["page_size"] == 5

    def test_filter_by_category(self):
        from src.services.scene_template_service import SceneTemplateService
        service = SceneTemplateService()
        result = service.list_templates(category="工作")
        assert result["total"] > 0
        for tpl in result["items"]:
            assert tpl["category"] == "工作"

    def test_search_templates(self):
        from src.services.scene_template_service import SceneTemplateService
        service = SceneTemplateService()
        result = service.search_templates(keyword="工作")
        assert result["total"] > 0

    def test_search_no_match(self):
        from src.services.scene_template_service import SceneTemplateService
        service = SceneTemplateService()
        result = service.search_templates(keyword="不存在的关键词xyz")
        assert result["total"] == 0

    def test_get_template(self):
        from src.services.scene_template_service import SceneTemplateService
        service = SceneTemplateService()
        tpl = service.get_template("tpl_work_focus")
        assert tpl is not None
        assert tpl["id"] == "tpl_work_focus"
        assert tpl["name"] == "专注工作"

    def test_get_template_not_found(self):
        from src.services.scene_template_service import SceneTemplateService
        service = SceneTemplateService()
        tpl = service.get_template("nonexistent")
        assert tpl is None

    def test_get_categories(self):
        from src.services.scene_template_service import SceneTemplateService
        service = SceneTemplateService()
        categories = service.get_categories()
        assert len(categories) > 0
        for cat in categories:
            assert "name" in cat
            assert "count" in cat
            assert cat["count"] > 0

    def test_apply_template(self):
        from src.services.scene_template_service import SceneTemplateService
        service = SceneTemplateService()
        result = service.apply_template("tpl_work_focus", user_id="test_user")
        assert result["success"] is True
        assert "settings" in result
        assert result["template"]["id"] == "tpl_work_focus"

    def test_apply_template_not_found(self):
        from src.services.scene_template_service import SceneTemplateService
        service = SceneTemplateService()
        result = service.apply_template("nonexistent", user_id="test_user")
        assert result["success"] is False

    def test_apply_template_with_override(self):
        from src.services.scene_template_service import SceneTemplateService
        service = SceneTemplateService()
        result = service.apply_template(
            "tpl_work_focus",
            user_id="test_user",
            override_settings={"custom_setting": True},
        )
        assert result["success"] is True
        assert result["settings"]["custom_setting"] is True

    def test_get_applied_history(self):
        from src.services.scene_template_service import SceneTemplateService
        service = SceneTemplateService()
        service.apply_template("tpl_work_focus", user_id="test_user")
        service.apply_template("tpl_learn_reading", user_id="test_user")
        history = service.get_applied_templates("test_user")
        assert len(history) == 2

    def test_get_stats(self):
        from src.services.scene_template_service import SceneTemplateService
        service = SceneTemplateService()
        stats = service.get_stats()
        assert stats["total_templates"] > 0
        assert stats["builtin_templates"] > 0
        assert stats["custom_templates"] == 0


class TestCustomTemplates:
    """自定义模板测试."""

    def test_create_custom_template(self):
        from src.services.scene_template_service import SceneTemplateService
        service = SceneTemplateService()

        tpl = service.create_custom_template(
            name="我的自定义模板",
            description="测试用",
            category="其他",
            settings={"setting_a": 1},
            user_id="test_user",
            icon="🎯",
            tags=["测试"],
        )

        assert tpl["id"].startswith("tpl_custom_")
        assert tpl["name"] == "我的自定义模板"
        assert tpl["is_custom"] is True
        assert tpl["owner_id"] == "test_user"

    def test_list_my_templates(self):
        from src.services.scene_template_service import SceneTemplateService
        service = SceneTemplateService()

        service.create_custom_template(
            name="模板1", description="d", category="其他",
            settings={}, user_id="user1",
        )
        service.create_custom_template(
            name="模板2", description="d", category="其他",
            settings={}, user_id="user2",
        )

        mine = service.list_my_templates("user1")
        assert len(mine) == 1
        assert mine[0]["name"] == "模板1"

    def test_update_custom_template(self):
        from src.services.scene_template_service import SceneTemplateService
        service = SceneTemplateService()

        tpl = service.create_custom_template(
            name="原名", description="原描述", category="其他",
            settings={}, user_id="user1",
        )

        updated = service.update_custom_template(
            tpl["id"], user_id="user1",
            data={"name": "新名字", "description": "新描述"},
        )

        assert updated is not None
        assert updated["name"] == "新名字"
        assert updated["description"] == "新描述"

    def test_delete_custom_template(self):
        from src.services.scene_template_service import SceneTemplateService
        service = SceneTemplateService()

        tpl = service.create_custom_template(
            name="要删除的", description="d", category="其他",
            settings={}, user_id="user1",
        )

        result = service.delete_custom_template(tpl["id"], user_id="user1")
        assert result is True

        tpl_check = service.get_template(tpl["id"])
        assert tpl_check is None

    def test_delete_not_owner_fails(self):
        from src.services.scene_template_service import SceneTemplateService
        service = SceneTemplateService()

        tpl = service.create_custom_template(
            name="别人的", description="d", category="其他",
            settings={}, user_id="user1",
        )

        result = service.delete_custom_template(tpl["id"], user_id="user2")
        assert result is False


class TestTemplateImportExport:
    """模板导入导出测试."""

    def test_export_template(self):
        from src.services.scene_template_service import SceneTemplateService
        service = SceneTemplateService()

        data = service.export_template("tpl_work_focus")
        assert data is not None
        assert data["id"] == "tpl_work_focus"
        assert "export_version" in data
        assert "exported_at" in data

    def test_import_template(self):
        from src.services.scene_template_service import SceneTemplateService
        service = SceneTemplateService()

        template_data = {
            "name": "导入的模板",
            "description": "从外部导入",
            "category": "其他",
            "settings": {"imported": True},
            "icon": "📥",
        }

        result = service.import_template(template_data, user_id="test_user")
        assert result["success"] is True
        assert result["template"]["name"] == "导入的模板"
        assert result["template"]["is_custom"] is True

    def test_import_missing_fields(self):
        from src.services.scene_template_service import SceneTemplateService
        service = SceneTemplateService()

        result = service.import_template({"name": "缺字段"}, user_id="test")
        assert result["success"] is False


class TestSceneCombination:
    """场景组合测试."""

    def test_combine_scenes(self):
        from src.services.scene_template_service import SceneTemplateService
        service = SceneTemplateService()

        result = service.combine_scenes(
            primary_scene="work",
            secondary_scenes=["entertainment"],
            user_id="test_user",
        )

        assert result["success"] is True
        assert result["primary"] == "work"
        assert len(result["secondary"]) == 1
        assert "combined_settings" in result

    def test_combine_no_secondary(self):
        from src.services.scene_template_service import SceneTemplateService
        service = SceneTemplateService()

        result = service.combine_scenes(
            primary_scene="work",
            secondary_scenes=[],
            user_id="test_user",
        )

        assert result["success"] is True
        assert len(result["secondary"]) == 0


# ===========================================================================
# 智能识别服务集成测试（已有服务的扩展测试）
# ===========================================================================

class TestSceneRecognitionService:
    """场景识别服务扩展测试."""

    def test_service_init(self):
        from src.services.scene_recognition import SceneRecognitionService
        service = SceneRecognitionService()
        assert service is not None
        assert hasattr(service, "feature_extractor")
        assert hasattr(service, "classifier")

    def test_recognize_with_context(self):
        from src.services.scene_recognition import SceneRecognitionService
        service = SceneRecognitionService(max_history=50)

        result = service.recognize_scene(
            context={"text": "我要开始工作了", "time_of_day": "morning"},
        )

        assert "scene" in result
        assert "confidence" in result
        assert isinstance(result["confidence"], float)

    def test_candidates_list(self):
        from src.services.scene_recognition import SceneRecognitionService
        service = SceneRecognitionService()

        result = service.recognize_scene(context={"text": "工作"})

        assert "candidates" in result
        assert isinstance(result["candidates"], list)

    def test_recognition_with_features(self):
        from src.services.scene_recognition import SceneRecognitionService
        service = SceneRecognitionService()

        result = service.recognize_scene(
            context={
                "text": "学习",
                "time_of_day": "evening",
                "location_type": "home",
                "activity": "reading",
            },
        )

        assert "scene" in result
        assert "confidence" in result
