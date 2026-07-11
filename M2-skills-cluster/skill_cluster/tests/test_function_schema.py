from __future__ import annotations

"""Function Schema Generator 单元测试."""

import pytest

from skill_cluster.function_schema import (
    ActionSignature,
    FunctionParameter,
    FunctionSchema,
    SkillSchemaRegistry,
    build_signatures_from_function,
)
from skill_cluster.interfaces import ISkill, SkillInvokeRequest, SkillInvokeResult, SkillManifest


class SchemaSkill(ISkill):
    """带有 Action 签名的测试 Skill."""

    def __init__(self) -> None:
        super().__init__(
            SkillManifest(
                skill_id="skill.schema_test",
                name="Schema Test",
                version="1.0.0",
                description="测试 Skill 模式生成",
                author="test",
                entrypoint="SchemaSkill",
            )
        )

    async def invoke(self, request: SkillInvokeRequest) -> SkillInvokeResult:
        return SkillInvokeResult(
            skill_id=self.manifest.skill_id,
            action=request.action,
            status="success",
            latency_ms=0.0,
            trace_id=request.trace_id,
        )

    async def health(self) -> dict:
        return {"healthy": True}

    async def configure(self, config: dict) -> None:
        pass

    def get_action_signatures(self) -> list[ActionSignature]:
        return [
            ActionSignature(
                action="analyze",
                description="分析文本内容",
                parameters=[
                    FunctionParameter(name="text", type="string", description="输入文本", required=True),
                    FunctionParameter(name="lang", type="string", description="语言", required=False, default="zh"),
                ],
            ),
            ActionSignature(
                action="summarize",
                description="生成摘要",
                parameters=[
                    FunctionParameter(name="content", type="string", description="内容", required=True),
                    FunctionParameter(name="max_length", type="integer", description="最大长度", required=False, default=200),
                ],
            ),
        ]


def test_register_skill_schema() -> None:
    registry = SkillSchemaRegistry()
    skill = SchemaSkill()
    registry.register_skill(skill)

    schemas = registry.list_all_schemas()
    assert len(schemas) == 2

    names = [s.name for s in schemas]
    assert "skill_schema_test__analyze" in names
    assert "skill_schema_test__summarize" in names


def test_openai_format() -> None:
    schema = FunctionSchema(
        name="skill_test__action",
        description="Test action",
        parameters={
            "type": "object",
            "properties": {"x": {"type": "string"}},
            "required": ["x"],
        },
    )
    fmt = schema.to_openai_format()
    assert fmt["type"] == "function"
    assert fmt["function"]["name"] == "skill_test__action"


def test_anthropic_format() -> None:
    schema = FunctionSchema(
        name="skill_test__action",
        description="Test action",
        parameters={
            "type": "object",
            "properties": {"x": {"type": "string"}},
            "required": ["x"],
        },
    )
    fmt = schema.to_anthropic_format()
    assert fmt["name"] == "skill_test__action"
    assert "input_schema" in fmt


def test_get_schemas_for_skill() -> None:
    registry = SkillSchemaRegistry()
    skill = SchemaSkill()
    registry.register_skill(skill)

    schemas = registry.get_schemas_for_skill("skill.schema_test")
    assert len(schemas) == 2


def test_parse_llm_tool_call() -> None:
    registry = SkillSchemaRegistry()
    skill = SchemaSkill()
    registry.register_skill(skill)

    request = registry.parse_llm_tool_call(
        "skill_schema_test__analyze",
        {"text": "hello", "lang": "en"},
    )
    assert request is not None
    assert request.skill_id == "skill.schema_test"
    assert request.action == "analyze"
    assert request.params["text"] == "hello"


def test_parse_unknown_tool_call() -> None:
    registry = SkillSchemaRegistry()
    request = registry.parse_llm_tool_call("unknown", {})
    assert request is None


def test_build_signatures_from_function() -> None:
    def sample_func(text: str, count: int = 10) -> str:
        """示例函数."""
        return text * count

    sig = build_signatures_from_function("sample", sample_func, "示例动作")
    assert sig.action == "sample"
    assert sig.description == "示例动作"
    assert len(sig.parameters) == 2
    assert sig.parameters[0].name == "text"
    assert sig.parameters[0].type == "string"
    assert sig.parameters[0].required is True
    assert sig.parameters[1].name == "count"
    assert sig.parameters[1].type == "integer"
    assert sig.parameters[1].required is False
    assert sig.parameters[1].default == 10
