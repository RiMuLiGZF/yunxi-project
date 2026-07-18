"""技能体系完善测试 - 演化/组合/SDK.

测试技能演化引擎、技能链、技能开发 SDK。
"""

import os
import sys
import tempfile
from pathlib import Path

import pytest

# 确保可以导入 skill_cluster 模块
CLUSTER_DIR = Path(__file__).resolve().parent.parent
if str(CLUSTER_DIR) not in sys.path:
    sys.path.insert(0, str(CLUSTER_DIR))


# ===========================================================================
# 技能演化引擎测试
# ===========================================================================

class TestSkillUsageRecord:
    """使用记录测试."""

    def test_record_creation(self):
        from skill_cluster.evolution import SkillUsageRecord
        record = SkillUsageRecord(
            skill_id="test_skill",
            user_id="user1",
            success=True,
            duration=1.5,
        )
        assert record.skill_id == "test_skill"
        assert record.success is True
        assert record.duration == 1.5


class TestEvolutionEngine:
    """技能演化引擎测试."""

    def test_initial_state(self):
        from skill_cluster.evolution import SkillEvolutionEngine
        engine = SkillEvolutionEngine()
        stats = engine.get_overall_stats()
        assert stats["total_skills_tracked"] == 0
        assert stats["total_usage_records"] == 0

    def test_record_usage(self):
        from skill_cluster.evolution import SkillEvolutionEngine
        engine = SkillEvolutionEngine()
        engine.record_usage(
            skill_id="skill_a",
            user_id="user1",
            success=True,
            duration=2.0,
        )
        stats = engine.get_overall_stats()
        assert stats["total_skills_tracked"] == 1
        assert stats["total_usage_records"] == 1

    def test_usage_stats(self):
        from skill_cluster.evolution import SkillEvolutionEngine
        engine = SkillEvolutionEngine()

        for _ in range(8):
            engine.record_usage("skill_a", "u1", True, 1.0)
        for _ in range(2):
            engine.record_usage("skill_a", "u1", False, 0.5, error_message="timeout")

        stats = engine.get_usage_stats("skill_a")
        assert stats["use_count"] == 10
        assert stats["success_count"] == 8
        assert stats["success_rate"] == 0.8
        assert stats["error_count"] == 2

    def test_usage_stats_empty(self):
        from skill_cluster.evolution import SkillEvolutionEngine
        engine = SkillEvolutionEngine()
        stats = engine.get_usage_stats("nonexistent")
        assert stats["use_count"] == 0
        assert stats["success_rate"] == 0.0

    def test_evaluate_skill(self):
        from skill_cluster.evolution import SkillEvolutionEngine
        engine = SkillEvolutionEngine()

        for _ in range(20):
            engine.record_usage("good_skill", "u1", True, 1.0, rating=5)

        evaluation = engine.evaluate_skill("good_skill")
        assert evaluation["evaluated"] is True
        assert evaluation["success_rate"] == 1.0
        assert 0 <= evaluation["overall_score"] <= 1.0

    def test_evaluate_skill_no_data(self):
        from skill_cluster.evolution import SkillEvolutionEngine
        engine = SkillEvolutionEngine()
        evaluation = engine.evaluate_skill("nonexistent")
        assert evaluation["evaluated"] is False

    def test_improvement_score(self):
        from skill_cluster.evolution import SkillEvolutionEngine
        engine = SkillEvolutionEngine()

        for _ in range(10):
            engine.record_usage("s1", "u1", True, 1.0, rating=4)

        score = engine.calculate_improvement_score("s1")
        assert 0 <= score <= 1.0

    def test_rankings(self):
        from skill_cluster.evolution import SkillEvolutionEngine
        engine = SkillEvolutionEngine()

        for _ in range(10):
            engine.record_usage("best", "u1", True, 0.5, rating=5)
        for _ in range(10):
            engine.record_usage("worst", "u1", False, 5.0, rating=1)

        rankings = engine.get_skill_rankings(sort_by="overall_score", top_n=10)
        assert len(rankings) == 2
        assert rankings[0]["skill_id"] == "best"

    def test_optimization_suggestions(self):
        from skill_cluster.evolution import SkillEvolutionEngine
        engine = SkillEvolutionEngine()

        for _ in range(10):
            engine.record_usage("low_success", "u1", False, 10.0)

        suggestions = engine.generate_optimization_suggestions("low_success")
        assert len(suggestions) > 0
        assert any(s["priority"] == "high" for s in suggestions)

    def test_suggestions_good_skill(self):
        from skill_cluster.evolution import SkillEvolutionEngine
        engine = SkillEvolutionEngine()

        for _ in range(20):
            engine.record_usage("perfect", "u1", True, 0.5, rating=5)

        suggestions = engine.generate_optimization_suggestions("perfect")
        assert len(suggestions) > 0
        # 表现良好的技能应该有 info 类型的建议
        assert any(s["type"] == "info" for s in suggestions)

    def test_auto_optimize_prompt(self):
        from skill_cluster.evolution import SkillEvolutionEngine
        engine = SkillEvolutionEngine()

        for _ in range(10):
            engine.record_usage("s1", "u1", True, 1.0, rating=4)

        result = engine.auto_optimize_prompt("s1", "简单的提示词")
        assert "optimizations" in result
        assert "suggestions" in result
        assert isinstance(result["optimizations"], list)

    def test_version_management(self):
        from skill_cluster.evolution import SkillEvolutionEngine
        engine = SkillEvolutionEngine()

        import time
        v1 = engine.create_version("s1", {"prompt": "v1"}, "初始版本")
        time.sleep(0.001)
        v2 = engine.create_version("s1", {"prompt": "v2"}, "优化版本")

        versions = engine.list_versions("s1")
        assert len(versions) == 2
        # 最新的在前
        assert versions[0]["version_id"] == v2["version_id"]

    def test_rollback_version(self):
        from skill_cluster.evolution import SkillEvolutionEngine
        engine = SkillEvolutionEngine()

        v1 = engine.create_version("s1", {"prompt": "v1"}, "v1")
        engine.create_version("s1", {"prompt": "v2"}, "v2")

        rollback = engine.rollback_version("s1", v1["version_id"])
        assert rollback is not None
        assert rollback["data"]["prompt"] == "v1"
        assert "rollback_from" in rollback

        versions = engine.list_versions("s1")
        assert len(versions) == 3  # 原2个 + 回滚版本


# ===========================================================================
# 技能链测试
# ===========================================================================

class TestSkillStep:
    """技能步骤测试."""

    def test_step_creation(self):
        from skill_cluster.composition import SkillStep
        step = SkillStep(step_id="s1", skill_id="echo", name="第一步")
        assert step.step_id == "s1"
        assert step.skill_id == "echo"
        assert step.enabled is True


class TestSkillChain:
    """技能链测试."""

    def test_chain_creation(self):
        from skill_cluster.composition import SkillChain
        chain = SkillChain(name="测试链", description="测试")
        assert chain.name == "测试链"
        assert len(chain.steps) == 0

    def test_add_step(self):
        from skill_cluster.composition import SkillChain
        chain = SkillChain()
        step_id = chain.add_step(skill_id="echo", name="步骤1")
        assert len(chain.steps) == 1
        assert chain.steps[0].step_id == step_id

    def test_remove_step(self):
        from skill_cluster.composition import SkillChain
        chain = SkillChain()
        step_id = chain.add_step("echo", "S1")
        assert len(chain.steps) == 1

        result = chain.remove_step(step_id)
        assert result is True
        assert len(chain.steps) == 0

    def test_remove_step_not_found(self):
        from skill_cluster.composition import SkillChain
        chain = SkillChain()
        assert chain.remove_step("nonexistent") is False

    def test_execute_chain(self):
        from skill_cluster.composition import SkillChain

        def mock_executor(skill_id, input_data):
            return {"skill": skill_id, "input": input_data, "output": f"result_{skill_id}"}

        chain = SkillChain()
        chain.add_step(skill_id="step_a", name="A")
        chain.add_step(skill_id="step_b", name="B")

        result = chain.execute({"initial": "data"}, executor=mock_executor)

        assert result.success is True
        assert result.total_steps == 2
        assert result.completed_steps == 2
        assert len(result.results) == 2

    def test_execute_with_mapping(self):
        from skill_cluster.composition import SkillChain

        def mock_executor(skill_id, input_data):
            return {"result": f"processed_{input_data.get('value', '')}"}

        chain = SkillChain()
        chain.add_step(
            skill_id="step1",
            output_mapping={"result": "step1_result"},
        )
        chain.add_step(
            skill_id="step2",
            input_mapping={"step1_result": "value"},
        )

        result = chain.execute({"value": "hello"}, executor=mock_executor)

        assert result.success is True
        assert result.completed_steps == 2

    def test_execute_error_stop(self):
        from skill_cluster.composition import SkillChain

        def failing_executor(skill_id, input_data):
            if skill_id == "fail_step":
                raise ValueError("执行失败")
            return {"ok": True}

        chain = SkillChain()
        chain.add_step(skill_id="ok_step", name="正常步骤")
        chain.add_step(skill_id="fail_step", name="失败步骤", error_handling="stop")
        chain.add_step(skill_id="after_step", name="后续步骤")

        result = chain.execute({}, executor=failing_executor)

        assert result.success is False
        assert result.completed_steps == 1
        assert len(result.errors) == 1

    def test_execute_error_continue(self):
        from skill_cluster.composition import SkillChain

        def failing_executor(skill_id, input_data):
            if skill_id == "fail_step":
                raise ValueError("执行失败")
            return {"ok": True}

        chain = SkillChain()
        chain.add_step(skill_id="ok_step")
        chain.add_step(skill_id="fail_step", error_handling="continue")
        chain.add_step(skill_id="after_step")

        result = chain.execute({}, executor=failing_executor)

        assert result.success is False  # 有错误
        assert result.completed_steps == 2  # 但完成了 2 步（ok + after）
        assert len(result.errors) == 1

    def test_condition_step(self):
        from skill_cluster.composition import SkillChain

        call_count = 0

        def mock_executor(skill_id, input_data):
            nonlocal call_count
            call_count += 1
            return {"count": call_count}

        chain = SkillChain()
        chain.add_step(skill_id="always", name="总是执行")
        chain.add_step(
            skill_id="conditional",
            name="条件执行",
            condition="count > 100",  # 不满足，跳过
        )

        result = chain.execute({"count": 1}, executor=mock_executor)

        assert result.completed_steps == 1  # 只执行了第一步

    def test_no_executor_raises(self):
        from skill_cluster.composition import SkillChain
        chain = SkillChain()
        chain.add_step("s1")
        with pytest.raises(ValueError):
            chain.execute({})


class TestSkillChainManager:
    """技能链管理器测试."""

    def test_create_chain(self):
        from skill_cluster.composition import SkillChainManager
        manager = SkillChainManager()

        chain = manager.create_chain(
            name="测试链",
            steps=[{"skill_id": "s1"}, {"skill_id": "s2"}],
            user_id="user1",
        )

        assert chain.chain_id is not None
        assert len(chain.steps) == 2

    def test_list_chains(self):
        from skill_cluster.composition import SkillChainManager
        manager = SkillChainManager()

        manager.create_chain("链1", [{"skill_id": "s1"}], user_id="u1")
        manager.create_chain("链2", [{"skill_id": "s2"}], user_id="u1")
        manager.create_chain("链3", [{"skill_id": "s3"}], user_id="u2")

        u1_chains = manager.list_chains("u1")
        assert len(u1_chains) == 2

        all_chains = manager.list_chains()
        assert len(all_chains) == 3

    def test_delete_chain(self):
        from skill_cluster.composition import SkillChainManager
        manager = SkillChainManager()

        chain = manager.create_chain("待删", [{"skill_id": "s1"}], user_id="u1")
        assert len(manager.list_chains("u1")) == 1

        result = manager.delete_chain(chain.chain_id, user_id="u1")
        assert result is True
        assert len(manager.list_chains("u1")) == 0

    def test_delete_wrong_user(self):
        from skill_cluster.composition import SkillChainManager
        manager = SkillChainManager()

        chain = manager.create_chain("别人的", [{"skill_id": "s1"}], user_id="u1")
        result = manager.delete_chain(chain.chain_id, user_id="u2")
        assert result is False

    def test_duplicate_chain(self):
        from skill_cluster.composition import SkillChainManager
        manager = SkillChainManager()

        original = manager.create_chain("原始", [{"skill_id": "s1"}], user_id="u1")
        copy = manager.duplicate_chain(original.chain_id, user_id="u1")

        assert copy is not None
        assert copy.chain_id != original.chain_id
        assert "副本" in copy.name
        assert len(copy.steps) == len(original.steps)

    def test_execute_chain(self):
        from skill_cluster.composition import SkillChainManager
        manager = SkillChainManager()

        def executor(sid, data):
            return {"result": sid}

        chain = manager.create_chain("执行测试", [{"skill_id": "s1"}], user_id="u1")
        result = manager.execute_chain(chain.chain_id, {"x": 1}, executor=executor)

        assert result is not None
        assert result.success is True


# ===========================================================================
# 技能开发 SDK 测试
# ===========================================================================

class TestSkillContext:
    """上下文测试."""

    def test_context_creation(self):
        from skill_cluster.sdk import SkillContext
        ctx = SkillContext(skill_id="test", input_data={"key": "value"})
        assert ctx.skill_id == "test"
        assert ctx.get("key") == "value"

    def test_context_default(self):
        from skill_cluster.sdk import SkillContext
        ctx = SkillContext(skill_id="test")
        assert ctx.get("nonexistent", "default") == "default"


class TestSkillResult:
    """结果测试."""

    def test_success_result(self):
        from skill_cluster.sdk import SkillResult
        result = SkillResult(success=True, data={"answer": 42})
        assert result.success is True
        assert result.data["answer"] == 42
        assert result.to_dict()["success"] is True

    def test_error_result(self):
        from skill_cluster.sdk import SkillResult
        result = SkillResult(success=False, error="出错了")
        assert result.success is False
        assert result.error == "出错了"


class TestBaseSkill:
    """基类测试."""

    def test_create_function_skill(self):
        from skill_cluster.sdk import create_skill

        def echo_skill(input_data):
            return {"echo": input_data.get("text", "")}

        skill = create_skill("echo", "回声技能", echo_skill)
        assert skill.skill_id == "echo"

        result = skill.run({"text": "hello"})
        assert result.success is True
        assert result.data["echo"] == "hello"

    def test_skill_info(self):
        from skill_cluster.sdk import BaseSkill, SkillContext, SkillResult

        class MySkill(BaseSkill):
            skill_id = "my_skill"
            skill_name = "我的技能"
            description = "测试技能"

            def execute(self, context):
                return SkillResult(success=True, data={"ok": True})

        skill = MySkill()
        info = skill.get_info()
        assert info["skill_id"] == "my_skill"
        assert info["name"] == "我的技能"

    def test_skill_run(self):
        from skill_cluster.sdk import BaseSkill, SkillContext, SkillResult

        class AddSkill(BaseSkill):
            skill_id = "add"
            skill_name = "加法"

            def execute(self, context):
                a = context.get("a", 0)
                b = context.get("b", 0)
                return SkillResult(success=True, data={"result": a + b})

        skill = AddSkill()
        result = skill.run({"a": 3, "b": 4})

        assert result.success is True
        assert result.data["result"] == 7
        assert result.duration >= 0

    def test_skill_error_handling(self):
        from skill_cluster.sdk import BaseSkill, SkillContext, SkillResult

        class BadSkill(BaseSkill):
            skill_id = "bad"
            skill_name = "坏技能"

            def execute(self, context):
                raise RuntimeError("boom")

        skill = BadSkill()
        result = skill.run({})

        assert result.success is False
        assert "boom" in result.error


class TestSkillValidation:
    """技能包验证测试."""

    def test_validate_missing_dir(self):
        from skill_cluster.sdk import validate_skill_package
        result = validate_skill_package("/nonexistent/path")
        assert result["valid"] is False

    def test_validate_valid_package(self):
        from skill_cluster.sdk import validate_skill_package, generate_skill_scaffold

        with tempfile.TemporaryDirectory() as tmpdir:
            generate_skill_scaffold("test_skill", "测试技能", tmpdir)
            result = validate_skill_package(os.path.join(tmpdir, "test_skill"))
            assert result["valid"] is True

    def test_validate_missing_manifest(self):
        from skill_cluster.sdk import validate_skill_package

        with tempfile.TemporaryDirectory() as tmpdir:
            skill_dir = os.path.join(tmpdir, "s1")
            os.makedirs(skill_dir)
            with open(os.path.join(skill_dir, "main.py"), "w") as f:
                f.write("# main")
            result = validate_skill_package(skill_dir)
            assert result["valid"] is False
            assert any("skill.json" in e for e in result["errors"])


class TestScaffoldGenerator:
    """脚手架生成测试."""

    def test_generate_scaffold(self):
        from skill_cluster.sdk import generate_skill_scaffold

        with tempfile.TemporaryDirectory() as tmpdir:
            result = generate_skill_scaffold(
                "my_skill", "我的技能", tmpdir,
                description="测试", author="tester", category="测试",
            )

            assert result["file_count"] == 3
            assert os.path.exists(os.path.join(tmpdir, "my_skill", "skill.json"))
            assert os.path.exists(os.path.join(tmpdir, "my_skill", "main.py"))
            assert os.path.exists(os.path.join(tmpdir, "my_skill", "README.md"))

    def test_scaffold_manifest(self):
        import json
        from skill_cluster.sdk import generate_skill_scaffold

        with tempfile.TemporaryDirectory() as tmpdir:
            generate_skill_scaffold("demo", "演示", tmpdir, category="工具")
            manifest_path = os.path.join(tmpdir, "demo", "skill.json")
            with open(manifest_path, "r", encoding="utf-8") as f:
                manifest = json.load(f)

            assert manifest["skill_id"] == "demo"
            assert manifest["name"] == "演示"
            assert manifest["category"] == "工具"
