"""技能开发 SDK.

提供技能开发的基类、工具和脚手架。
"""

from __future__ import annotations

import json
import time
import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Optional


@dataclass
class SkillContext:
    """技能执行上下文."""
    skill_id: str
    user_id: str = ""
    session_id: str = ""
    trace_id: str = ""
    input_data: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)
    start_time: float = field(default_factory=time.time)

    def get(self, key: str, default: Any = None) -> Any:
        """获取输入数据."""
        return self.input_data.get(key, default)

    def set_metadata(self, key: str, value: Any) -> None:
        """设置元数据."""
        self.metadata[key] = value


@dataclass
class SkillResult:
    """技能执行结果."""
    success: bool
    data: Any = None
    error: str = ""
    output_type: str = "text"
    metadata: dict[str, Any] = field(default_factory=dict)
    duration: float = 0.0
    token_usage: dict[str, int] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "success": self.success,
            "data": self.data,
            "error": self.error,
            "output_type": self.output_type,
            "metadata": self.metadata,
            "duration": self.duration,
            "token_usage": self.token_usage,
        }


class BaseSkill(ABC):
    """技能基类.

    所有自定义技能都应继承此类，实现 execute 方法。
    """

    # 技能元数据（子类应覆盖）
    skill_id: str = ""
    skill_name: str = ""
    description: str = ""
    version: str = "1.0.0"
    author: str = ""
    category: str = "通用"
    tags: list[str] = []
    icon: str = "🔧"

    # 输入输出 Schema（可选）
    input_schema: dict[str, Any] = {}
    output_schema: dict[str, Any] = {}

    # 配置项
    timeout: int = 30
    max_retries: int = 0

    def __init__(self, config: Optional[dict[str, Any]] = None) -> None:
        self.config = config or {}
        self._initialized = False

    def initialize(self) -> bool:
        """初始化技能（加载模型、建立连接等）.

        子类可重写此方法。
        """
        self._initialized = True
        return True

    def cleanup(self) -> None:
        """清理资源."""
        self._initialized = False

    @abstractmethod
    def execute(self, context: SkillContext) -> SkillResult:
        """执行技能逻辑（子类必须实现）.

        Args:
            context: 技能执行上下文

        Returns:
            SkillResult 执行结果
        """
        ...

    def validate_input(self, input_data: dict[str, Any]) -> tuple[bool, str]:
        """验证输入数据.

        子类可重写此方法进行自定义验证。
        """
        return True, ""

    def run(self, input_data: dict[str, Any], **kwargs) -> SkillResult:
        """运行技能（带初始化、验证、计时）.

        这是外部调用的入口方法。
        """
        start_time = time.time()

        # 确保已初始化
        if not self._initialized:
            self.initialize()

        # 构建上下文
        context = SkillContext(
            skill_id=self.skill_id,
            user_id=kwargs.get("user_id", ""),
            session_id=kwargs.get("session_id", ""),
            trace_id=kwargs.get("trace_id", str(uuid.uuid4())),
            input_data=input_data,
        )

        # 验证输入
        valid, error_msg = self.validate_input(input_data)
        if not valid:
            return SkillResult(
                success=False,
                error=error_msg,
                duration=time.time() - start_time,
            )

        # 执行
        try:
            result = self.execute(context)
        except Exception as e:
            result = SkillResult(
                success=False,
                error=f"执行错误: {str(e)}",
                duration=time.time() - start_time,
            )

        result.duration = time.time() - start_time
        return result

    def get_info(self) -> dict[str, Any]:
        """获取技能信息."""
        return {
            "skill_id": self.skill_id,
            "name": self.skill_name,
            "description": self.description,
            "version": self.version,
            "author": self.author,
            "category": self.category,
            "tags": self.tags,
            "icon": self.icon,
            "input_schema": self.input_schema,
            "output_schema": self.output_schema,
            "timeout": self.timeout,
            "max_retries": self.max_retries,
        }


# ===========================================================================
# 工具函数
# ===========================================================================

def create_skill(
    skill_id: str,
    name: str,
    execute_func: Any,
    description: str = "",
    category: str = "通用",
    tags: Optional[list[str]] = None,
) -> BaseSkill:
    """从函数创建技能（快速开发工具）.

    Args:
        skill_id: 技能 ID
        name: 技能名称
        execute_func: 执行函数 (input_dict) -> result_dict
        description: 描述
        category: 分类
        tags: 标签

    Returns:
        BaseSkill 实例
    """

    class FunctionSkill(BaseSkill):
        def execute(self, context: SkillContext) -> SkillResult:
            result = execute_func(context.input_data)
            if isinstance(result, SkillResult):
                return result
            if isinstance(result, dict) and "success" in result:
                return SkillResult(
                    success=result["success"],
                    data=result.get("data"),
                    error=result.get("error", ""),
                )
            return SkillResult(success=True, data=result)

    FunctionSkill.skill_id = skill_id
    FunctionSkill.skill_name = name
    FunctionSkill.description = description
    FunctionSkill.category = category
    FunctionSkill.tags = tags or []

    return FunctionSkill()


def validate_skill_package(package_path: str) -> dict[str, Any]:
    """验证技能包.

    Args:
        package_path: 技能包路径

    Returns:
        验证结果
    """
    import os

    errors: list[str] = []
    warnings: list[str] = []

    # 检查目录存在
    if not os.path.isdir(package_path):
        return {"valid": False, "errors": ["技能包目录不存在"], "warnings": []}

    # 检查必要文件
    manifest_path = os.path.join(package_path, "skill.json")
    if not os.path.exists(manifest_path):
        errors.append("缺少 skill.json 清单文件")

    main_path = os.path.join(package_path, "main.py")
    if not os.path.exists(main_path):
        errors.append("缺少 main.py 主文件")

    # 解析清单
    info = {}
    if os.path.exists(manifest_path):
        try:
            with open(manifest_path, "r", encoding="utf-8") as f:
                info = json.load(f)
            if "skill_id" not in info:
                errors.append("skill.json 缺少 skill_id")
            if "name" not in info:
                warnings.append("skill.json 缺少 name")
        except json.JSONDecodeError:
            errors.append("skill.json 格式错误")

    if not info.get("version"):
        warnings.append("建议添加 version 字段")

    if not info.get("description"):
        warnings.append("建议添加 description 字段")

    return {
        "valid": len(errors) == 0,
        "errors": errors,
        "warnings": warnings,
        "info": info,
    }


def generate_skill_scaffold(
    skill_id: str,
    name: str,
    output_dir: str,
    description: str = "",
    author: str = "",
    category: str = "通用",
) -> dict[str, Any]:
    """生成技能脚手架.

    Args:
        skill_id: 技能 ID
        name: 技能名称
        output_dir: 输出目录
        description: 描述
        author: 作者
        category: 分类

    Returns:
        生成的文件列表
    """
    import os

    skill_dir = os.path.join(output_dir, skill_id)
    os.makedirs(skill_dir, exist_ok=True)

    files_created = []

    # skill.json
    manifest = {
        "skill_id": skill_id,
        "name": name,
        "description": description,
        "version": "1.0.0",
        "author": author,
        "category": category,
        "tags": [],
        "icon": "🔧",
        "entry": "main.py",
        "input_schema": {},
        "output_schema": {},
    }
    manifest_path = os.path.join(skill_dir, "skill.json")
    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)
    files_created.append(manifest_path)

    # main.py
    main_code = f'''"""
{name} 技能

{description}
"""

from skill_sdk import BaseSkill, SkillContext, SkillResult


class {''.join(w.capitalize() for w in skill_id.replace('-', '_').replace(' ', '_').split('_'))}Skill(BaseSkill):
    skill_id = "{skill_id}"
    skill_name = "{name}"
    description = "{description}"
    version = "1.0.0"
    author = "{author}"
    category = "{category}"
    tags = []
    icon = "🔧"

    def execute(self, context: SkillContext) -> SkillResult:
        """执行技能逻辑."""
        # TODO: 实现技能逻辑
        input_text = context.get("text", "")

        return SkillResult(
            success=True,
            data={{"message": f"收到: {{input_text}}"}},
        )


def create_skill(config=None):
    """技能工厂函数（必须）."""
    return {''.join(w.capitalize() for w in skill_id.replace('-', '_').replace(' ', '_').split('_'))}Skill(config)
'''
    main_path = os.path.join(skill_dir, "main.py")
    with open(main_path, "w", encoding="utf-8") as f:
        f.write(main_code)
    files_created.append(main_path)

    # README.md
    readme = f"""# {name}

{description}

## 安装

```bash
# 将此目录复制到技能目录
```

## 使用

```python
from main import create_skill

skill = create_skill()
result = skill.run({{"text": "hello"}})
```

## 配置

暂无特殊配置。
"""
    readme_path = os.path.join(skill_dir, "README.md")
    with open(readme_path, "w", encoding="utf-8") as f:
        f.write(readme)
    files_created.append(readme_path)

    return {
        "skill_dir": skill_dir,
        "files_created": files_created,
        "file_count": len(files_created),
    }
