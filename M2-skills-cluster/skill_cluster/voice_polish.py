"""VoicePolish 输出润色管道.

【v3.9.0 优化项2】Skill 输出与 YunxiVoice 联动。
所有面向用户的 Skill 输出统一经过 YunxiVoice-Agent 润色，保持全系统人格一致性。

核心设计：
- 5类技能润色程度分级（deep/medium/light/gentle/framework）
- 3级降级策略（快速模式/超时/错误）
- 技术术语保护机制（代码/数字/错误码不被篡改）
- 预算隔离：润色消耗单独计入 voice_polish 分类
- 与 M1 YunxiVoice-Agent 接口兼容（V10.1）
"""

from __future__ import annotations

import asyncio
import re
import time
from enum import Enum
from typing import Any, Callable

import structlog
from pydantic import BaseModel, Field

logger = structlog.get_logger()


class PolishLevel(str, Enum):
    """润色程度分级."""

    DEEP = "deep"           # 深度润色：创意/写作类
    MEDIUM = "medium"       # 中度润色：分析/建议类
    LIGHT = "light"         # 轻度润色：事实/数据类
    GENTLE = "gentle"       # 温和化润色：错误/告警类
    FRAMEWORK = "framework"  # 框架润色：代码/技术类


class SkillType(str, Enum):
    """技能类型分类."""

    CREATIVE = "creative"       # 创意/写作类
    ANALYSIS = "analysis"       # 分析/建议类
    FACTUAL = "factual"         # 事实/数据类
    ERROR = "error"             # 错误/告警类
    TECHNICAL = "technical"     # 代码/技术类


# 技能类型 → 润色级别 默认映射
SKILL_TYPE_POLISH_MAP: dict[SkillType, PolishLevel] = {
    SkillType.CREATIVE: PolishLevel.DEEP,
    SkillType.ANALYSIS: PolishLevel.MEDIUM,
    SkillType.FACTUAL: PolishLevel.LIGHT,
    SkillType.ERROR: PolishLevel.GENTLE,
    SkillType.TECHNICAL: PolishLevel.FRAMEWORK,
}


class VoicePolishConfig(BaseModel):
    """技能级润色配置."""

    voice_polish_level: PolishLevel = Field(default=PolishLevel.MEDIUM, description="润色级别")
    voice_polish_prompt_hint: str = Field(default="", description="润色提示词提示")
    preserve_technical_terms: bool = Field(default=True, description="是否保护技术术语")
    skill_type: SkillType = Field(default=SkillType.ANALYSIS, description="技能类型")
    timeout_ms: int = Field(default=300, description="润色超时（毫秒）")


class VoicePolishResult(BaseModel):
    """润色结果."""

    polished_content: str = Field(..., description="润色后的内容")
    original_content: str = Field(..., description="原始内容")
    voice_degraded: bool = Field(default=False, description="是否降级（跳过润色）")
    degrade_reason: str | None = Field(default=None, description="降级原因")
    polish_level: PolishLevel = Field(default=PolishLevel.MEDIUM, description="实际润色级别")
    latency_ms: float = Field(default=0.0, description="润色耗时（毫秒）")
    tokens_consumed: int = Field(default=0, description="润色消耗token数")
    technical_terms_preserved: bool = Field(default=True, description="技术术语是否完整保留")


class VoicePolishEngine:
    """Voice 润色引擎.

    负责将技能输出经过 YunxiVoice-Agent 润色后再返回给用户。
    支持分级润色、降级策略、技术术语保护、预算隔离。
    """

    def __init__(
        self,
        default_timeout_ms: int = 300,
        voice_budget_ratio: float = 0.1,
    ) -> None:
        self._default_timeout_ms = default_timeout_ms
        self._voice_budget_ratio = voice_budget_ratio

        # M1 YunxiVoice-Agent 回调（由M1注入）
        self._m1_voice_polish_callback: Callable | None = None
        # M1 Budget-Agent 回调（润色预算申请）
        self._m1_voice_budget_callback: Callable | None = None

        # 技能级润色配置缓存：skill_id -> VoicePolishConfig
        self._skill_configs: dict[str, VoicePolishConfig] = {}

        # 全局开关
        self._enabled: bool = True
        self._concise_mode: bool = False  # 简洁模式（快速模式）

    # ---- M1 回调注入 ----

    def set_m1_voice_callback(self, callback: Callable) -> None:
        """设置 M1 YunxiVoice-Agent 润色回调.

        回调签名: callback(raw_content, scene_type, skill_type, polish_level,
                          preserve_keywords, user_context) -> dict
        返回: {polished_content, tokens_consumed}
        """
        self._m1_voice_polish_callback = callback

    def set_m1_voice_budget_callback(self, callback: Callable) -> None:
        """设置 M1 Budget-Agent 润色预算申请回调.

        回调签名: callback(task_id, estimated_tokens, category='voice_polish') -> bool
        返回: True=配额批准, False=配额不足
        """
        self._m1_voice_budget_callback = callback

    # ---- 全局控制 ----

    def enable(self) -> None:
        """启用润色."""
        self._enabled = True

    def disable(self) -> None:
        """禁用润色（全局降级）."""
        self._enabled = False

    def set_concise_mode(self, concise: bool) -> None:
        """设置简洁模式（快速模式，跳过润色）."""
        self._concise_mode = concise

    # ---- 技能配置 ----

    def set_skill_config(self, skill_id: str, config: VoicePolishConfig) -> None:
        """设置技能级润色配置."""
        self._skill_configs[skill_id] = config

    def get_skill_config(self, skill_id: str) -> VoicePolishConfig:
        """获取技能级润色配置，不存在则返回默认."""
        return self._skill_configs.get(skill_id, VoicePolishConfig())

    def infer_skill_type(self, skill_id: str, description: str = "") -> SkillType:
        """根据技能ID和描述推断技能类型."""
        # 先看配置
        if skill_id in self._skill_configs:
            return self._skill_configs[skill_id].skill_type

        sid_lower = skill_id.lower()
        desc_lower = description.lower()

        # 代码/技术类
        if any(k in sid_lower for k in ["code", "dev", "bug", "test", "search", "debug"]):
            return SkillType.TECHNICAL
        if any(k in desc_lower for k in ["代码", "编程", "函数", "bug", "调试"]):
            return SkillType.TECHNICAL

        # 创意/写作类
        if any(k in sid_lower for k in ["write", "creative", "name", "copy", "translate", "doc"]):
            return SkillType.CREATIVE
        if any(k in desc_lower for k in ["写作", "创意", "文案", "翻译", "起名"]):
            return SkillType.CREATIVE

        # 分析/建议类
        if any(k in sid_lower for k in ["analysis", "analyze", "review", "suggest", "recommend"]):
            return SkillType.ANALYSIS
        if any(k in desc_lower for k in ["分析", "审查", "建议", "趋势", "统计"]):
            return SkillType.ANALYSIS

        # 事实/数据类
        if any(k in sid_lower for k in ["calendar", "weather", "query", "fetch", "data", "notify"]):
            return SkillType.FACTUAL
        if any(k in desc_lower for k in ["查询", "天气", "日程", "数据", "通知"]):
            return SkillType.FACTUAL

        # 默认分析类
        return SkillType.ANALYSIS

    # ---- 技术术语保护 ----

    def _extract_technical_terms(self, content: str) -> list[str]:
        """提取需要保护的技术术语.

        包括：代码块、错误码、数字、特定技术关键词。
        """
        terms: list[str] = []

        # 代码块（```...```）
        code_blocks = re.findall(r"```[\s\S]*?```", content)
        terms.extend(code_blocks)

        # 行内代码（`...`）
        inline_code = re.findall(r"`[^`]+`", content)
        terms.extend(inline_code)

        # 错误码（如 ErrorCode: 404, 错误码 500, ECONNREFUSED）
        error_codes = re.findall(
            r"(?:错误码|error[_\s]?code|status[_\s]?code)\s*[:：]?\s*[\w\-]+",
            content,
            re.IGNORECASE,
        )
        terms.extend(error_codes)

        # 纯数字序列（带单位的数值）
        numbers = re.findall(r"\b\d+(?:\.\d+)?(?:ms|s|%|KB|MB|GB|ms|次|个|条)?\b", content)
        terms.extend(numbers)

        return list(set(terms))

    def _verify_terms_preserved(self, original: str, polished: str) -> bool:
        """验证技术术语在润色后是否完整保留."""
        terms = self._extract_technical_terms(original)
        if not terms:
            return True  # 无术语需要保护

        # 检查每个术语是否都在润色结果中
        preserved_count = sum(1 for t in terms if t in polished)
        # 允许90%以上保留（考虑可能的格式调整）
        return preserved_count / len(terms) >= 0.9

    # ---- 主润色接口 ----

    async def polish(
        self,
        skill_id: str,
        raw_content: str,
        scene_type: str = "DEFAULT",
        user_context: dict[str, Any] | None = None,
        task_id: str = "",
        force_skip: bool = False,
    ) -> VoicePolishResult:
        """对技能输出进行润色.

        Args:
            skill_id: 技能ID
            raw_content: 原始输出内容
            scene_type: 场景类型（CODING/LEARNING/LIFE等）
            user_context: 用户上下文
            task_id: 任务ID（用于预算追踪）
            force_skip: 强制跳过润色

        Returns:
            VoicePolishResult 润色结果
        """
        start_time = time.time()
        config = self.get_skill_config(skill_id)
        skill_type = config.skill_type
        polish_level = config.voice_polish_level

        # --- 降级检查：快速模式 / 全局禁用 / 强制跳过 ---
        if not self._enabled or self._concise_mode or force_skip:
            return VoicePolishResult(
                polished_content=raw_content,
                original_content=raw_content,
                voice_degraded=True,
                degrade_reason="concise_mode" if self._concise_mode else "polish_disabled",
                polish_level=polish_level,
                latency_ms=(time.time() - start_time) * 1000,
                tokens_consumed=0,
            )

        # --- 预算检查：润色配额是否充足 ---
        estimated_tokens = max(50, len(raw_content) // 4)  # 估算润色token
        budget_ok = True
        if self._m1_voice_budget_callback and task_id:
            try:
                budget_ok = self._m1_voice_budget_callback(
                    task_id=task_id,
                    estimated_tokens=estimated_tokens,
                    category="voice_polish",
                )
            except Exception:
                budget_ok = True  # 预算回调异常时默认放行

        if not budget_ok:
            return VoicePolishResult(
                polished_content=raw_content,
                original_content=raw_content,
                voice_degraded=True,
                degrade_reason="voice_budget_exceeded",
                polish_level=polish_level,
                latency_ms=(time.time() - start_time) * 1000,
                tokens_consumed=0,
            )

        # --- 调用 M1 YunxiVoice-Agent ---
        if self._m1_voice_polish_callback is None:
            # 无M1回调，降级返回原始内容
            return VoicePolishResult(
                polished_content=raw_content,
                original_content=raw_content,
                voice_degraded=True,
                degrade_reason="voice_agent_not_connected",
                polish_level=polish_level,
                latency_ms=(time.time() - start_time) * 1000,
                tokens_consumed=0,
            )

        preserve_keywords = self._extract_technical_terms(raw_content) if config.preserve_technical_terms else []

        try:
            # 超时控制
            timeout_sec = config.timeout_ms / 1000.0
            result = await asyncio.wait_for(
                self._call_m1_voice_polish(
                    raw_content=raw_content,
                    scene_type=scene_type,
                    skill_type=skill_type.value,
                    polish_level=polish_level.value,
                    preserve_keywords=preserve_keywords,
                    user_context=user_context or {},
                    prompt_hint=config.voice_polish_prompt_hint,
                ),
                timeout=timeout_sec,
            )

            polished = result.get("polished_content", raw_content)
            tokens_used = result.get("tokens_consumed", 0)

            # 技术术语完整性校验
            terms_preserved = True
            if config.preserve_technical_terms:
                terms_preserved = self._verify_terms_preserved(raw_content, polished)
                if not terms_preserved:
                    # 术语被篡改，降级返回原始内容
                    logger.warning(
                        "voice_polish_terms_tampered",
                        skill_id=skill_id,
                        task_id=task_id,
                    )
                    return VoicePolishResult(
                        polished_content=raw_content,
                        original_content=raw_content,
                        voice_degraded=True,
                        degrade_reason="technical_terms_tampered",
                        polish_level=polish_level,
                        latency_ms=(time.time() - start_time) * 1000,
                        tokens_consumed=tokens_used,
                        technical_terms_preserved=False,
                    )

            return VoicePolishResult(
                polished_content=polished,
                original_content=raw_content,
                voice_degraded=False,
                polish_level=polish_level,
                latency_ms=(time.time() - start_time) * 1000,
                tokens_consumed=tokens_used,
                technical_terms_preserved=terms_preserved,
            )

        except asyncio.TimeoutError:
            # 超时降级
            return VoicePolishResult(
                polished_content=raw_content,
                original_content=raw_content,
                voice_degraded=True,
                degrade_reason="timeout",
                polish_level=polish_level,
                latency_ms=(time.time() - start_time) * 1000,
                tokens_consumed=0,
            )

        except Exception as e:
            # 错误降级
            logger.warning(
                "voice_polish_error",
                skill_id=skill_id,
                error=str(e),
            )
            return VoicePolishResult(
                polished_content=raw_content,
                original_content=raw_content,
                voice_degraded=True,
                degrade_reason=f"error: {str(e)}",
                polish_level=polish_level,
                latency_ms=(time.time() - start_time) * 1000,
                tokens_consumed=0,
            )

    async def _call_m1_voice_polish(
        self,
        raw_content: str,
        scene_type: str,
        skill_type: str,
        polish_level: str,
        preserve_keywords: list[str],
        user_context: dict[str, Any],
        prompt_hint: str,
    ) -> dict[str, Any]:
        """调用 M1 YunxiVoice-Agent 润色接口.

        接口协议（M1 V10.1 兼容）:
        intent: "voice.polish"
        payload: {raw_content, scene_type, skill_type, polish_level,
                  preserve_keywords, user_context}
        """
        if self._m1_voice_polish_callback is None:
            raise RuntimeError("M1 voice callback not set")

        # 支持异步和同步回调
        result = self._m1_voice_polish_callback(
            raw_content=raw_content,
            scene_type=scene_type,
            skill_type=skill_type,
            polish_level=polish_level,
            preserve_keywords=preserve_keywords,
            user_context=user_context,
            prompt_hint=prompt_hint,
        )

        # 如果是协程，await
        if asyncio.iscoroutine(result):
            result = await result

        return result

    # ---- 流式润色（预留接口） ----

    async def polish_stream(
        self,
        skill_id: str,
        raw_content: str,
        scene_type: str = "DEFAULT",
        mode: str = "fluent",  # fluent / speed
    ):
        """流式润色（预留接口，兼容 M1 V10.1 流式方案）.

        mode:
          - fluent: 流畅模式（整句输出）
          - speed: 极速模式（逐字输出，跳过深度润色）
        """
        # 极速模式直接返回原始内容流
        if mode == "speed":
            yield raw_content
            return

        # 流畅模式：先润色再流式输出
        result = await self.polish(skill_id, raw_content, scene_type)
        # 模拟流式输出（按字符）
        for char in result.polished_content:
            yield char

    # ---- 统计 ----

    @property
    def voice_budget_ratio(self) -> float:
        """润色预算占总预算比例."""
        return self._voice_budget_ratio

    def stats(self) -> dict[str, Any]:
        """润色引擎统计信息."""
        return {
            "enabled": self._enabled,
            "concise_mode": self._concise_mode,
            "configured_skills": len(self._skill_configs),
            "default_timeout_ms": self._default_timeout_ms,
            "voice_budget_ratio": self._voice_budget_ratio,
            "m1_voice_connected": self._m1_voice_polish_callback is not None,
            "m1_budget_connected": self._m1_voice_budget_callback is not None,
            "polish_levels": [l.value for l in PolishLevel],
            "skill_types": [t.value for t in SkillType],
        }
