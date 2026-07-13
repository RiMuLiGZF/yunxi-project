"""代码执行技能基类.

【v3.10.0 新增】所有代码类技能的基础类，封装 M7 调用和结果渲染。
"""

from __future__ import annotations

from typing import Any

import structlog

from skill_cluster.interfaces import ISkill, SkillInvokeRequest, SkillInvokeResult, SkillManifest
from skill_cluster.security.code_exec.bridge import CodeExecutionBridge, ExecutionResult, ExecutionStatus
from skill_cluster.security.code_exec.renderer import ResultRenderer, RenderedOutput

logger = structlog.get_logger()


class CodeExecutionSkillBase(ISkill):
    """代码执行技能基类.

    封装了：
    - M7 代码执行调用
    - 结果渲染
    - 错误处理
    - 自动修复
    """

    def __init__(self, manifest: SkillManifest) -> None:
        super().__init__(manifest)
        self._config: dict[str, Any] = {}
        self._bridge: CodeExecutionBridge | None = None
        self._renderer = ResultRenderer()
        self._default_language = "python"

    def set_execution_bridge(self, bridge: CodeExecutionBridge) -> None:
        """注入代码执行桥梁."""
        self._bridge = bridge

    @property
    def bridge(self) -> CodeExecutionBridge:
        """获取执行桥梁（懒加载默认实例）."""
        if self._bridge is None:
            self._bridge = CodeExecutionBridge()
        return self._bridge

    async def _execute_code(
        self,
        code: str,
        language: str | None = None,
        files: dict[str, str] | None = None,
        stdin: str = "",
        timeout: int | None = None,
        auto_fix: bool = True,
        test_code: str | None = None,
    ) -> dict[str, Any]:
        """执行代码并返回结构化结果.

        Args:
            code: 核心代码
            language: 语言（默认python）
            files: 附加文件
            stdin: 标准输入
            timeout: 超时时间
            auto_fix: 是否自动修复
            test_code: 测试代码（追加到代码末尾执行验证）

        Returns:
            结构化结果字典
        """
        lang = language or self._default_language

        # 如果有测试代码，拼接到末尾
        full_code = code
        if test_code:
            full_code = code + "\n\n# === 测试验证 ===\n" + test_code

        # 执行
        result = await self.bridge.execute(
            code=full_code,
            language=lang,
            files=files,
            stdin=stdin,
            timeout=timeout,
            auto_fix=auto_fix,
        )

        # 渲染
        rendered = self._renderer.render(result)

        return self._build_result_dict(code, result, rendered)

    def _build_result_dict(
        self,
        code: str,
        exec_result: ExecutionResult,
        rendered: RenderedOutput,
    ) -> dict[str, Any]:
        """构建返回结果字典."""
        return {
            "code": code,
            "execution": {
                "status": exec_result.status.value,
                "exit_code": exec_result.exit_code,
                "execution_time_ms": round(exec_result.execution_time_ms, 2),
                "language": exec_result.language,
                "error_type": exec_result.error_type.value if exec_result.error_type else None,
                "retry_count": exec_result.retry_count,
            },
            "output": {
                "stdout": exec_result.stdout,
                "stderr": exec_result.stderr,
                "output_type": rendered.output_type,
            },
            "rendered": {
                "content": rendered.content,
                "summary": rendered.summary,
                "highlights": rendered.highlights,
                "has_more": rendered.has_more,
                "suggestion": rendered.suggestion,
            },
            "fix_history": exec_result.fix_history,
            "images": len(exec_result.images),
            "tables": exec_result.tables,
        }

    async def health(self) -> dict[str, Any]:
        return {
            "healthy": True,
            "skill_id": self.manifest.skill_id,
            "m7_connected": self.bridge.stats()["m7_connected"],
        }

    async def configure(self, config: dict[str, Any]) -> None:
        self._config.update(config)
