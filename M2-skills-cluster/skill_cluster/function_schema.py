from __future__ import annotations

"""Function Schema Generator - LLM 函数调用模式自动生成.

自动从 Skill 的 action 描述和 Python 类型注解生成符合 OpenAI / Anthropic
function calling 规范的 JSON Schema，使大模型能够自动发现与调用 Skill。
"""

import inspect
from typing import Any, get_type_hints

from pydantic import BaseModel, Field, create_model

from skill_cluster.interfaces import ISkill, SkillInvokeRequest


class FunctionParameter(BaseModel):
    """函数参数定义."""

    name: str = Field(..., description="参数名")
    type: str = Field(..., description="JSON Schema 类型")
    description: str = Field(default="", description="参数描述")
    required: bool = Field(default=True, description="是否必填")
    default: Any = Field(default=None, description="默认值")
    enum: list[Any] | None = Field(default=None, description="枚举值")


class FunctionSchema(BaseModel):
    """符合 OpenAI function calling 规范的函数模式."""

    name: str = Field(..., description="函数名，格式: skill_id__action")
    description: str = Field(..., description="函数描述")
    parameters: dict[str, Any] = Field(
        default_factory=dict, description="JSON Schema 参数定义"
    )

    def to_openai_format(
        self, strict: bool = False, additional_properties: bool = True
    ) -> dict[str, Any]:
        """转换为 OpenAI tools 格式.

        Args:
            strict: 是否启用 OpenAI Structured Outputs 严格模式（2025+）.
            additional_properties: parameters 中是否允许额外属性.

        Returns:
            OpenAI tools 格式字典.
        """
        parameters = dict(self.parameters)
        if not additional_properties:
            parameters["additionalProperties"] = False
        if strict:
            parameters.setdefault("additionalProperties", False)

        result = {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": parameters,
            },
        }
        if strict:
            result["function"]["strict"] = True
        return result

    def to_anthropic_format(self) -> dict[str, Any]:
        """转换为 Anthropic tool_use 格式."""
        return {
            "name": self.name,
            "description": self.description,
            "input_schema": self.parameters,
        }


class ActionSignature(BaseModel):
    """Action 签名描述."""

    action: str = Field(..., description="动作标识")
    description: str = Field(..., description="动作描述")
    parameters: list[FunctionParameter] = Field(
        default_factory=list, description="参数列表"
    )
    returns: dict[str, Any] = Field(
        default_factory=dict, description="返回值 JSON Schema"
    )


class SkillSchemaRegistry:
    """Skill 模式注册中心.

    为每个 Skill 的每个 action 生成 LLM 可用的 function schema。
    """

    def __init__(self) -> None:
        self._schemas: dict[str, FunctionSchema] = {}
        self._action_signatures: dict[str, list[ActionSignature]] = {}

    def register_skill(
        self, skill: ISkill, action_signatures: list[ActionSignature] | None = None
    ) -> None:
        """注册 Skill 的模式.

        Args:
            skill: Skill 实例.
            action_signatures: Action 签名列表. 如果为 None，则尝试从 Skill 的
                `get_action_signatures` 方法获取。
        """
        sid = skill.manifest.skill_id
        desc = skill.manifest.description

        if action_signatures is None:
            action_signatures = getattr(skill, "get_action_signatures", lambda: [])()

        self._action_signatures[sid] = action_signatures

        for sig in action_signatures:
            schema = self._build_function_schema(sid, desc, sig)
            key = f"{sid.replace('.', '_')}__{sig.action}"
            self._schemas[key] = schema

    def _build_function_schema(
        self, skill_id: str, skill_desc: str, sig: ActionSignature
    ) -> FunctionSchema:
        """从 Action 签名构建 FunctionSchema."""
        properties: dict[str, Any] = {}
        required: list[str] = []

        for param in sig.parameters:
            prop: dict[str, Any] = {
                "type": param.type,
                "description": param.description,
            }
            if param.enum is not None:
                prop["enum"] = param.enum
            if param.default is not None:
                prop["default"] = param.default
            properties[param.name] = prop
            if param.required and param.default is None:
                required.append(param.name)

        parameters = {
            "type": "object",
            "properties": properties,
            "required": required,
        }

        description = f"[{skill_id}] {skill_desc} - Action: {sig.action}. {sig.description}"
        name = f"{skill_id.replace('.', '_')}__{sig.action}"

        return FunctionSchema(
            name=name,
            description=description,
            parameters=parameters,
        )

    def get_schema(self, function_name: str) -> FunctionSchema | None:
        """按函数名获取 Schema."""
        return self._schemas.get(function_name)

    def get_schemas_for_skill(self, skill_id: str) -> list[FunctionSchema]:
        """获取指定 Skill 的所有 Schema."""
        prefix = f"{skill_id.replace('.', '_')}__"
        return [
            schema for name, schema in self._schemas.items()
            if name.startswith(prefix)
        ]

    def list_all_schemas(self) -> list[FunctionSchema]:
        """列出所有 Schema."""
        return list(self._schemas.values())

    def list_all_openai_tools(self) -> list[dict[str, Any]]:
        """列出所有 OpenAI 格式的工具定义."""
        return [s.to_openai_format() for s in self._schemas.values()]

    def parse_llm_tool_call(self, function_name: str, arguments: dict[str, Any]) -> SkillInvokeRequest | None:
        """解析 LLM 的 tool call 为 SkillInvokeRequest.

        Args:
            function_name: LLM 调用的函数名，如 skill_doc_proc__parse_markdown
            arguments: 函数参数.

        Returns:
            SkillInvokeRequest 或 None.
        """
        schema = self._schemas.get(function_name)
        if schema is None:
            return None

        # 解析 function_name: skill_doc_proc__parse_markdown -> skill.doc_proc, parse_markdown
        # 由于 skill_id 中的点被替换为下划线，需要逆向还原
        # 策略：查找已注册 schema 的精确匹配
        for name, s in self._schemas.items():
            if name == function_name:
                # 从 action_signatures 中反推 skill_id 和 action
                for sid, sigs in self._action_signatures.items():
                    for sig in sigs:
                        expected = f"{sid.replace('.', '_')}__{sig.action}"
                        if expected == function_name:
                            return SkillInvokeRequest(
                                skill_id=sid,
                                action=sig.action,
                                params=arguments,
                                trace_id=f"llm_tool_{function_name}",
                            )
        return None


# ---------- 辅助工具：从类型注解生成参数 ----------

PYTHON_TYPE_TO_JSON: dict[type, str] = {
    str: "string",
    int: "integer",
    float: "number",
    bool: "boolean",
    list: "array",
    dict: "object",
    # 【第五轮优化】补全常见 Python 类型映射
    set: "array",
    frozenset: "array",
    tuple: "array",
    bytes: "string",
    bytearray: "string",
    type(None): "null",
}


def type_to_json_schema(t: type) -> str:
    """将 Python 类型映射为 JSON Schema 类型."""
    origin = getattr(t, "__origin__", None)
    if origin is list or origin is list:
        return "array"
    if origin is dict:
        return "object"
    return PYTHON_TYPE_TO_JSON.get(t, "string")


def build_signatures_from_function(
    action: str,
    func: Any,
    description: str = "",
) -> ActionSignature:
    """从 Python 函数签名自动构建 ActionSignature.

    Args:
        action: 动作标识.
        func: 函数对象.
        description: 动作描述.

    Returns:
        ActionSignature.
    """
    sig = inspect.signature(func)
    type_hints = get_type_hints(func)
    params: list[FunctionParameter] = []

    for name, param in sig.parameters.items():
        if name in ("self", "cls", "request"):
            continue

        param_type = type_hints.get(name, str)
        json_type = type_to_json_schema(param_type)

        default = param.default if param.default is not param.empty else None
        required = param.default is param.empty

        params.append(
            FunctionParameter(
                name=name,
                type=json_type,
                description="",
                required=required,
                default=default,
            )
        )

    return ActionSignature(
        action=action,
        description=description or (func.__doc__ or "").strip(),
        parameters=params,
    )
