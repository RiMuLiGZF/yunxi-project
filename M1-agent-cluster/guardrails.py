"""
云汐内核 V2 - Guardrails 护栏系统

灵感来源：OpenAI Agents SDK Guardrails
https://openai.com/zh-Hans-CN/index/new-tools-for-building-agents/

对 Agent 的输入/输出进行验证和过滤，
拦截越界请求、过滤敏感信息、检测误操作。
"""

from __future__ import annotations

import re
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable

import structlog

logger = structlog.get_logger(__name__)


@dataclass
class GuardrailResult:
    """护栏检查结果"""

    passed: bool = True
    violation_type: str = ""
    message: str = ""
    action: str = "allow"  # allow | block | warn | sanitize
    sanitized_value: Any = None


class Guardrail(ABC):
    """护栏基类

    所有护栏规则必须实现 check 方法。
    """

    def __init__(self, name: str, severity: str = "warn") -> None:
        self.name = name
        self.severity = severity  # allow | warn | block

    @abstractmethod
    async def check(self, value: Any, context: dict[str, Any] | None = None) -> GuardrailResult:
        """检查输入/输出值

        Args:
            value: 待检查的值
            context: 可选上下文信息

        Returns:
            GuardrailResult: 检查结果
        """
        ...


# ── 内置护栏实现 ────────────────────────────────────────────


class ContentLengthGuardrail(Guardrail):
    """内容长度护栏

    限制输入/输出的最大长度。
    """

    def __init__(self, max_length: int = 10000, **kwargs: Any) -> None:
        super().__init__("content_length", **kwargs)
        self.max_length = max_length

    async def check(self, value: Any, context: dict[str, Any] | None = None) -> GuardrailResult:
        text = str(value) if value is not None else ""
        if len(text) > self.max_length:
            return GuardrailResult(
                passed=False,
                violation_type="content_length_exceeded",
                message=f"内容长度 {len(text)} 超过限制 {self.max_length}",
                action="block",
            )
        return GuardrailResult(passed=True)


class SensitiveInfoGuardrail(Guardrail):
    """敏感信息护栏

    检测并过滤 PII（个人身份信息）等敏感数据。
    """

    PATTERNS: dict[str, str] = {
        "phone": r"1[3-9]\d{9}",
        "id_card": r"\d{17}[\dXx]|\d{15}",
        "email": r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}",
        "bank_card": r"\d{16,19}",
        "password": r"(?i)(password|密码|passwd|pwd)\s*[:=]\s*\S+",
    }

    def __init__(self, detect_only: bool = False, **kwargs: Any) -> None:
        super().__init__("sensitive_info", **kwargs)
        self.detect_only = detect_only
        self._compiled = {k: re.compile(v) for k, v in self.PATTERNS.items()}

    async def check(self, value: Any, context: dict[str, Any] | None = None) -> GuardrailResult:
        text = str(value) if value is not None else ""
        detections: list[str] = []
        sanitized = text

        for info_type, pattern in self._compiled.items():
            if pattern.search(text):
                detections.append(info_type)
                if not self.detect_only:
                    sanitized = pattern.sub(f"[{info_type}_REDACTED]", sanitized)

        if detections:
            action = "warn" if self.detect_only else "sanitize"
            return GuardrailResult(
                passed=self.detect_only,
                violation_type="sensitive_info_detected",
                message=f"检测到敏感信息: {', '.join(detections)}",
                action=action,
                sanitized_value=sanitized,
            )
        return GuardrailResult(passed=True)


class KeywordBlockGuardrail(Guardrail):
    """关键词拦截护栏

    拦截包含特定关键词的内容。
    """

    def __init__(self, blocklist: list[str] | None = None, **kwargs: Any) -> None:
        super().__init__("keyword_block", **kwargs)
        self.blocklist = blocklist or []

    async def check(self, value: Any, context: dict[str, Any] | None = None) -> GuardrailResult:
        text = str(value).lower() if value is not None else ""
        for keyword in self.blocklist:
            if keyword.lower() in text:
                return GuardrailResult(
                    passed=False,
                    violation_type="blocked_keyword",
                    message=f"内容包含禁用关键词: '{keyword}'",
                    action="block",
                )
        return GuardrailResult(passed=True)


class EmotionalRiskGuardrail(Guardrail):
    """情绪风险护栏

    检测严重负面情绪/危机信号，触发保护机制。
    """

    CRISIS_KEYWORDS: list[str] = [
        "自杀", "自残", "不想活", "结束生命", "跳楼",
        "上吊", "割腕", "吞药", "跳楼", "安眠药",
    ]

    def __init__(self, **kwargs: Any) -> None:
        super().__init__("emotional_risk", **kwargs)

    async def check(self, value: Any, context: dict[str, Any] | None = None) -> GuardrailResult:
        text = str(value) if value is not None else ""
        matches = [kw for kw in self.CRISIS_KEYWORDS if kw in text]
        if matches:
            return GuardrailResult(
                passed=False,
                violation_type="crisis_signal",
                message=f"检测到危机信号关键词: {', '.join(matches)}",
                action="block",
                sanitized_value=value,
            )
        return GuardrailResult(passed=True)


class RateLimitGuardrail(Guardrail):
    """频率限制护栏

    限制单位时间内的调用次数。
    """

    def __init__(self, max_calls: int = 100, window_seconds: int = 60, **kwargs: Any) -> None:
        super().__init__("rate_limit", **kwargs)
        self.max_calls = max_calls
        self.window_seconds = window_seconds
        self._calls: list[float] = []
        self._lock: Any = None  # 惰性初始化 asyncio.Lock

    def _get_lock(self):
        if self._lock is None:
            import asyncio
            self._lock = asyncio.Lock()
        return self._lock

    async def check(self, value: Any, context: dict[str, Any] | None = None) -> GuardrailResult:
        import time
        now = time.time()
        lock = self._get_lock()
        async with lock:
            # 清理过期记录
            self._calls = [t for t in self._calls if now - t < self.window_seconds]
            if len(self._calls) >= self.max_calls:
                return GuardrailResult(
                    passed=False,
                    violation_type="rate_limit_exceeded",
                    message=f"请求频率超限：{self.max_calls}/{self.window_seconds}s",
                    action="block",
                )
            self._calls.append(now)
        return GuardrailResult(passed=True)


# ── 护栏管线 ────────────────────────────────────────────────


class GuardrailPipeline:
    """护栏管线

    将多个护栏串联执行，支持输入/输出两端分别配置。
    """

    def __init__(self, name: str = "default") -> None:
        self.name = name
        self.input_guardrails: list[Guardrail] = []
        self.output_guardrails: list[Guardrail] = []
        self._logger = logger.bind(guardrail_pipeline=name)

    def add_input_guardrail(self, guardrail: Guardrail) -> GuardrailPipeline:
        """添加输入护栏"""
        self.input_guardrails.append(guardrail)
        return self

    def add_output_guardrail(self, guardrail: Guardrail) -> GuardrailPipeline:
        """添加输出护栏"""
        self.output_guardrails.append(guardrail)
        return self

    async def check_input(
        self, value: Any, context: dict[str, Any] | None = None
    ) -> tuple[bool, Any, list[GuardrailResult]]:
        """检查输入

        Returns:
            (是否通过, 处理后值, 所有检查结果)
        """
        return await self._run_guardrails(self.input_guardrails, value, context)

    async def check_output(
        self, value: Any, context: dict[str, Any] | None = None
    ) -> tuple[bool, Any, list[GuardrailResult]]:
        """检查输出

        Returns:
            (是否通过, 处理后值, 所有检查结果)
        """
        return await self._run_guardrails(self.output_guardrails, value, context)

    async def _run_guardrails(
        self,
        guardrails: list[Guardrail],
        value: Any,
        context: dict[str, Any] | None,
    ) -> tuple[bool, Any, list[GuardrailResult]]:
        """执行护栏链"""
        current_value = value
        results: list[GuardrailResult] = []

        for guardrail in guardrails:
            result = await guardrail.check(current_value, context)
            results.append(result)

            self._logger.debug(
                "guardrail_check",
                guardrail=guardrail.name,
                passed=result.passed,
                action=result.action,
            )

            if result.action == "sanitize" and result.sanitized_value is not None:
                current_value = result.sanitized_value

            if result.action == "block":
                self._logger.warning(
                    "guardrail_blocked",
                    guardrail=guardrail.name,
                    violation=result.violation_type,
                )
                return False, current_value, results

        passed = all(r.passed or r.action != "block" for r in results)
        return passed, current_value, results


# ── 预设管线配置 ────────────────────────────────────────────


def create_default_pipeline() -> GuardrailPipeline:
    """创建默认护栏管线

    适用于大多数 Agent 场景的标准配置。
    """
    pipeline = GuardrailPipeline("default")
    pipeline.add_input_guardrail(ContentLengthGuardrail(max_length=5000))
    pipeline.add_input_guardrail(EmotionalRiskGuardrail(severity="block"))
    pipeline.add_output_guardrail(ContentLengthGuardrail(max_length=10000))
    pipeline.add_output_guardrail(SensitiveInfoGuardrail(detect_only=True, severity="warn"))
    return pipeline
