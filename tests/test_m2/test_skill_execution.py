"""
M2 技能集群 - 技能执行测试
"""
import sys
import pytest
from pathlib import Path
from typing import Dict, Any

PROJECT_ROOT = Path(__file__).parent.parent.parent
class MockSkillExecutor:
    SKILLS = {
        "add_numbers": {
            "input_schema": {"a": "int", "b": "int"},
            "output_schema": {"result": "int"},
            "handler": lambda p: {"result": p["a"] + p["b"]},
        },
        "greet": {
            "input_schema": {"name": "str", "greeting": "str?"},
            "output_schema": {"message": "str"},
            "handler": lambda p: {"message": f"{p.get('greeting', '你好')}, {p['name']}!"},
        },
        "calc_bmi": {
            "input_schema": {"height": "float", "weight": "float"},
            "output_schema": {"bmi": "float"},
            "handler": lambda p: {"bmi": round(p["weight"] / (p["height"]/100)**2, 1)},
        },
    }

    def validate(self, skill_id, params):
        if skill_id not in self.SKILLS:
            return {"valid": False, "errors": [f"技能不存在: {skill_id}"]}
        schema = self.SKILLS[skill_id]["input_schema"]
        errors = []
        for field, t in schema.items():
            optional = t.endswith("?")
            if field not in params:
                if not optional:
                    errors.append(f"缺少参数: {field}")
                continue
        return {"valid": len(errors) == 0, "errors": errors}

    def execute(self, skill_id, params):
        v = self.validate(skill_id, params)
        if not v["valid"]:
            return {"success": False, "error": "; ".join(v["errors"])}
        try:
            result = self.SKILLS[skill_id]["handler"](params)
            return {"success": True, "result": result}
        except Exception as e:
            return {"success": False, "error": str(e)}

class TestSkillExecution:
    @pytest.fixture
    def executor(self):
        return MockSkillExecutor()

    @pytest.mark.m2
    @pytest.mark.execution
    def test_valid_params(self, executor):
        r = executor.validate("add_numbers", {"a": 1, "b": 2})
        assert r["valid"] is True

    @pytest.mark.m2
    @pytest.mark.execution
    def test_missing_param(self, executor):
        r = executor.validate("add_numbers", {"a": 1})
        assert r["valid"] is False

    @pytest.mark.m2
    @pytest.mark.execution
    def test_optional_param(self, executor):
        r = executor.validate("greet", {"name": "云汐"})
        assert r["valid"] is True

    @pytest.mark.m2
    @pytest.mark.execution
    def test_nonexistent_skill(self, executor):
        r = executor.validate("bad_skill", {})
        assert r["valid"] is False

    @pytest.mark.m2
    @pytest.mark.execution
    def test_execute_add(self, executor):
        r = executor.execute("add_numbers", {"a": 3, "b": 5})
        assert r["success"] is True
        assert r["result"]["result"] == 8

    @pytest.mark.m2
    @pytest.mark.execution
    def test_execute_greet_default(self, executor):
        r = executor.execute("greet", {"name": "云汐"})
        assert "你好, 云汐!" in r["result"]["message"]

    @pytest.mark.m2
    @pytest.mark.execution
    def test_execute_greet_custom(self, executor):
        r = executor.execute("greet", {"name": "云汐", "greeting": "早上好"})
        assert "早上好" in r["result"]["message"]

    @pytest.mark.m2
    @pytest.mark.execution
    def test_execute_bmi(self, executor):
        r = executor.execute("calc_bmi", {"height": 170.0, "weight": 65.0})
        assert 22.0 <= r["result"]["bmi"] <= 23.0

    @pytest.mark.m2
    @pytest.mark.execution
    def test_execute_invalid_params_fails(self, executor):
        r = executor.execute("add_numbers", {"a": 1})
        assert r["success"] is False

    @pytest.mark.m2
    @pytest.mark.execution
    def test_execute_bad_skill_fails(self, executor):
        r = executor.execute("nonexistent", {})
        assert r["success"] is False

    @pytest.mark.m2
    @pytest.mark.execution
    def test_multiple_executions_independent(self, executor):
        r1 = executor.execute("add_numbers", {"a": 1, "b": 2})
        r2 = executor.execute("add_numbers", {"a": 10, "b": 20})
        assert r1["result"]["result"] == 3
        assert r2["result"]["result"] == 30
