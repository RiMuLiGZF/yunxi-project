"""
云汐人格润色输出子Agent — YunxiVoiceAgent

将上游各Agent产出的结构化原始内容，润色成有云汐人格温度的自然语言。
负责「怎么说」，不负责「说什么」——事实性内容由上游专业Agent保证。

依赖：
- interfaces.IAgentPlugin / AgentTask / AgentResult：插件接口
- shared_models.SecurityClassification：涉密分级枚举
"""

from __future__ import annotations

import time
from typing import Any

import structlog

from interfaces import (
    AgentTask,
    AgentResult,
    IAgentPlugin,
)
from shared_models import (
    SecurityClassification,
    M4ExecutionMode,
    UserScene,
    MODE_TO_SCENE_PRIMARY,
    SCENE_TO_MODE,
    SCENE_NAMES_ZH,
    MODE_NAMES_ZH,
    PersonalityPreference,
)

logger = structlog.get_logger(__name__)


# ── 人格参数体系（两层：底层模式 + 上层场景） ──

DEFAULT_PERSONALITY = {
    "warmth": 8.5,
    "rationality": 7.5,
    "humor": 6.0,
    "empathy": 9.0,
    "reliability": 9.5,
}

# ── 第一层：M4 底层执行模式语气偏移（6 组）
# 定义每种底层模式的基础语气，决定「做什么事用什么基调」
MODE_TONE_OFFSETS: dict[str, dict[str, Any]] = {
    M4ExecutionMode.CODING.value: {
        "name": "代码开发（底层模式）",
        "level": "mode",
        "warmth": -1.0,
        "rationality": +1.0,
        "humor": -0.5,
        "empathy": -0.5,
        "reliability": +0.0,
        "keywords": ["嗯", "好的", "明白"],
    },
    M4ExecutionMode.DOCUMENT.value: {
        "name": "文档写作（底层模式）",
        "level": "mode",
        "warmth": -0.5,
        "rationality": +1.0,
        "humor": -0.5,
        "empathy": 0.0,
        "reliability": +0.5,
        "keywords": ["好的", "明白"],
    },
    M4ExecutionMode.REVIEW.value: {
        "name": "评审复盘（底层模式）",
        "level": "mode",
        "warmth": +0.5,
        "rationality": +0.5,
        "humor": 0.0,
        "empathy": +0.5,
        "reliability": +0.0,
        "keywords": ["嗯", "我在"],
    },
    M4ExecutionMode.DESIGN.value: {
        "name": "设计规划（底层模式）",
        "level": "mode",
        "warmth": +0.5,
        "rationality": 0.0,
        "humor": +0.5,
        "empathy": +0.5,
        "reliability": 0.0,
        "keywords": ["嗯", "好的"],
    },
    M4ExecutionMode.MENTAL.value: {
        "name": "情绪支持（底层模式）",
        "level": "mode",
        "warmth": +2.0,
        "rationality": -1.0,
        "humor": -1.0,
        "empathy": +2.0,
        "reliability": 0.0,
        "keywords": ["我在", "慢慢来"],
    },
    M4ExecutionMode.PLANNING.value: {
        "name": "计划管理（底层模式）",
        "level": "mode",
        "warmth": 0.0,
        "rationality": +1.0,
        "humor": 0.0,
        "empathy": 0.0,
        "reliability": +0.5,
        "keywords": ["好的", "明白"],
    },
}

# ── 第二层：上层用户场景语气微调（6 组）
# 在底层模式基础语气上叠加业务场景的细腻调整
SCENE_TONE_FINETUNE: dict[str, dict[str, Any]] = {
    UserScene.WORK_DEV.value: {
        "name": "工作开发（上层场景）",
        "base_mode": M4ExecutionMode.CODING.value,
        "warmth": 0.0,
        "rationality": 0.0,
        "humor": +0.5,
        "empathy": +0.5,
        "reliability": 0.0,
        "extra_keywords": [],
    },
    UserScene.STUDY_PLAN.value: {
        "name": "学业规划（上层场景）",
        "base_mode": M4ExecutionMode.DOCUMENT.value,
        "warmth": +1.0,
        "rationality": -0.5,
        "humor": 0.0,
        "empathy": +0.5,
        "reliability": 0.0,
        "extra_keywords": ["慢慢来"],
    },
    UserScene.REVIEW_SUMMARY.value: {
        "name": "复盘总结（上层场景）",
        "base_mode": M4ExecutionMode.REVIEW.value,
        "warmth": +0.5,
        "rationality": -0.5,
        "humor": 0.0,
        "empathy": +0.5,
        "reliability": 0.0,
        "extra_keywords": ["嗯"],
    },
    UserScene.RELATIONSHIP.value: {
        "name": "人际关系（上层场景）",
        "base_mode": M4ExecutionMode.DESIGN.value,
        "warmth": +1.0,
        "rationality": -0.5,
        "humor": 0.0,
        "empathy": +1.0,
        "reliability": 0.0,
        "extra_keywords": ["我在"],
    },
    UserScene.EMOTION_COMPANION.value: {
        "name": "情绪陪伴（上层场景）",
        "base_mode": M4ExecutionMode.MENTAL.value,
        "warmth": 0.0,
        "rationality": 0.0,
        "humor": 0.0,
        "empathy": 0.0,
        "reliability": 0.0,
        "extra_keywords": [],
    },
    UserScene.LIFE_MANAGEMENT.value: {
        "name": "生活综合管理（上层场景）",
        "base_mode": M4ExecutionMode.PLANNING.value,
        "warmth": +0.5,
        "rationality": -0.5,
        "humor": +0.5,
        "empathy": +0.5,
        "reliability": -0.5,
        "extra_keywords": ["嗯"],
    },
}

# 红线禁忌词（出现即触发自动替换/打回）
RED_LINE_PATTERNS = [
    "本AI",
    "作为人工智能",
    "作为AI",
    "我是一个AI",
    "我是一个人工智能",
    "我的模型",
    "我调用了",
    "Agent",
    "agent",
]


class YunxiVoiceAgent(IAgentPlugin):
    """云汐人格润色输出子Agent

    面向Agent集群提供统一的人格润色输出能力：
    - 人格润色：将结构化原始内容转换为有云汐温度的自然语言
    - 场景语气偏移：6种场景下的五维人格参数动态调整
    - 质量自检：事实完整性、语气一致性、红线违规检测
    - 涉密合规：MENTAL场景下确保不泄露原始情绪对话内容
    """

    agent_id: str = "agent.yunxi_voice"
    version: str = "1.0.0"
    capabilities: list[str] = [
        "voice.polish",
        "voice.polish_with_tone",
        "voice.quality_check",
        "voice.red_line_check",
        "voice.get_personality",
        "voice.update_preference",  # [V10.1] 偏好持久化
    ]

    def __init__(
        self,
        default_scene: str = "life_management",
        enable_quality_check: bool = True,
    ) -> None:
        self._logger = logger.bind(agent_id=self.agent_id)
        self._default_scene = default_scene  # 默认使用上层场景名
        self._enable_quality_check = enable_quality_check
        # 用户个性化偏好缓存（user_id -> PersonalityPreference dict）
        self._user_preferences: dict[str, dict[str, Any]] = {}

    # ── 生命周期 ──────────────────────────────────────────

    async def on_mount(self, registry: Any | None = None) -> None:
        """挂载时初始化"""
        self._logger.info(
            "yunxi_voice_agent_mounted",
            default_scene=self._default_scene,
            quality_check=self._enable_quality_check,
        )

    async def health(self) -> dict[str, Any]:
        """健康检查"""
        base = await super().health()
        base["supported_modes"] = list(MODE_TONE_OFFSETS.keys())
        base["supported_scenes"] = list(SCENE_TONE_FINETUNE.keys())
        base["user_preferences_cached"] = len(self._user_preferences)
        return base

    # ── 核心任务处理 ─────────────────────────────────────

    async def handle_task(self, task: AgentTask) -> AgentResult:
        """处理人格润色请求

        支持的 intent：
        - voice.polish              ：标准人格润色（自动识别场景）
        - voice.polish_with_tone    ：指定人格参数的润色
        - voice.quality_check       ：质量校验（事实完整性/语气一致性/红线检测）
        - voice.red_line_check      ：仅执行红线违规检测
        - voice.get_personality     ：获取指定场景的人格参数
        """
        start_time = time.time()
        self._logger.info(
            "yunxi_voice_handling_task",
            trace_id=task.trace_id,
            task_id=task.task_id,
            intent=task.intent,
        )

        try:
            intent = task.intent
            payload = task.payload

            if intent == "voice.polish":
                output = self.polish(
                    raw_content=payload.get("raw_content", ""),
                    scene_type=payload.get("scene_type", self._default_scene),
                    user_context=payload.get("user_context", {}),
                    output_format=payload.get("output_format", "text"),
                    length_hint=payload.get("length_hint", "medium"),
                )
            elif intent == "voice.polish_with_tone":
                personality = payload.get("personality_params", {})
                output = self.polish_with_custom_tone(
                    raw_content=payload.get("raw_content", ""),
                    personality=personality,
                    scene_type=payload.get("scene_type", self._default_scene),
                )
            elif intent == "voice.quality_check":
                output = self.quality_check(
                    raw_content=payload.get("raw_content", ""),
                    polished_content=payload.get("polished_content", ""),
                    scene_type=payload.get("scene_type", self._default_scene),
                )
            elif intent == "voice.red_line_check":
                output = self.red_line_check(
                    content=payload.get("content", ""),
                )
            elif intent == "voice.get_personality":
                output = self.get_personality_for_scene(
                    scene_type=payload.get("scene_type", self._default_scene),
                    user_context=payload.get("user_context", {}),
                )
            elif intent == "voice.update_preference":
                output = self.update_preference(
                    user_id=payload.get("user_id", ""),
                    preferences=payload.get("preferences", {}),
                    source=payload.get("source", "local"),
                )
            else:
                return AgentResult(
                    task_id=task.task_id,
                    trace_id=task.trace_id,
                    agent_id=self.agent_id,
                    status="failure",
                    error=f"不支持的intent: {intent}",
                    latency_ms=(time.time() - start_time) * 1000,
                )

            return AgentResult(
                task_id=task.task_id,
                trace_id=task.trace_id,
                agent_id=self.agent_id,
                status="success",
                output=output,
                latency_ms=(time.time() - start_time) * 1000,
            )
        except Exception as exc:
            self._logger.error(
                "yunxi_voice_task_failed",
                error=str(exc),
                exc_info=True,
                task_id=task.task_id,
            )
            return AgentResult(
                task_id=task.task_id,
                trace_id=task.trace_id,
                agent_id=self.agent_id,
                status="failure",
                error=f"YunxiVoiceAgent任务处理失败: {exc}",
                latency_ms=(time.time() - start_time) * 1000,
            )

    # ── 公开API ──────────────────────────────────────────

    def polish(
        self,
        raw_content: str,
        scene_type: str = "life_management",
        user_context: dict[str, Any] | None = None,
        output_format: str = "text",
        length_hint: str = "medium",
    ) -> dict[str, Any]:
        """标准人格润色

        将结构化原始内容润色为有云汐人格温度的自然语言。
        支持传入底层模式名（如 CODING）或上层场景名（如 work_dev），
        内部自动查表应用对应语气参数。

        Args:
            raw_content: 上游结构化原始内容
            scene_type: 场景/模式标识（支持 M4 底层模式名 或 上层场景名）
            user_context: 用户偏好上下文
            output_format: 输出格式（text/markdown/mixed）
            length_hint: 长度提示（short/medium/long）

        Returns:
            润色结果字典
        """
        user_context = user_context or {}

        # 解析输入：自动判断是底层模式还是上层场景
        resolved = self._resolve_identifier(scene_type)
        mode_key = resolved["mode_key"]
        scene_key = resolved["scene_key"]
        level = resolved["level"]  # "mode" 或 "scene"

        # 1. 计算最终人格参数（基础人格 + 模式偏移 + 场景微调 + 用户偏好）
        personality = self._calc_personality(scene_type, user_context)

        # 2. 执行红线检测
        red_line_result = self.red_line_check(raw_content)

        # 3. 概念级润色（骨架实现：保留原文 + 注入语气标识）
        #    实际生产环境应由LLM基于人格参数执行润色
        scene_config = MODE_TONE_OFFSETS[mode_key]
        if level == "scene" and scene_key in SCENE_TONE_FINETUNE:
            # 场景级：合并模式关键词 + 场景额外关键词
            finetune = SCENE_TONE_FINETUNE[scene_key]
            merged_keywords = scene_config["keywords"] + finetune.get("extra_keywords", [])
            scene_config = {**scene_config, "keywords": merged_keywords}
        polished = self._skeleton_polish(raw_content, scene_config, length_hint)

        # 4. MENTAL/EMOTION_COMPANION场景涉密自检
        privacy_check = "passed"
        if mode_key == M4ExecutionMode.MENTAL.value:
            privacy_check = self._mental_privacy_check(raw_content, polished)

        # 5. 质量校验（如启用）
        quality_ok = True
        if self._enable_quality_check:
            qc = self.quality_check(raw_content, polished, scene_type)
            quality_ok = qc["passed"]

        self._logger.info(
            "voice_polish_completed",
            scene_type=scene_type,
            resolved_level=level,
            mode_key=mode_key,
            scene_key=scene_key,
            output_format=output_format,
            length_hint=length_hint,
            quality_ok=quality_ok,
            red_line_violations=len(red_line_result["violations"]),
        )

        return {
            "result_type": "polished_output",
            "polished_content": polished,
            "tone_applied": f"{scene_type}_voice",
            "tone_level": level,  # "mode" 或 "scene"
            "resolved_mode": mode_key,
            "resolved_scene": scene_key,
            "personality_params": personality,
            "content_modified": raw_content != polished,
            "facts_preserved": quality_ok,
            "privacy_check": privacy_check,
            "red_line_violations": red_line_result["violations"],
            "scene_name": scene_config["name"],
        }

    def polish_with_custom_tone(
        self,
        raw_content: str,
        personality: dict[str, float],
        scene_type: str = "life_management",
    ) -> dict[str, Any]:
        """使用自定义人格参数润色

        Args:
            raw_content: 原始内容
            personality: 自定义五维人格参数
            scene_type: 场景/模式标识

        Returns:
            润色结果字典
        """
        resolved = self._resolve_identifier(scene_type)
        scene_config = MODE_TONE_OFFSETS[resolved["mode_key"]]
        polished = self._skeleton_polish(raw_content, scene_config, "medium")

        return {
            "result_type": "polished_output",
            "polished_content": polished,
            "tone_applied": "custom_tone",
            "personality_params": personality,
            "content_modified": raw_content != polished,
            "facts_preserved": True,
            "privacy_check": "passed",
            "scene_name": scene_config["name"],
        }

    def quality_check(
        self,
        raw_content: str,
        polished_content: str,
        scene_type: str = "life_management",
    ) -> dict[str, Any]:
        """质量校验

        校验维度：
        1. 事实完整性：关键数据点是否保留
        2. 语气一致性：人格参数是否在场景预期范围内
        3. 红线违规检测：禁忌词扫描

        Args:
            raw_content: 原始内容
            polished_content: 润色后内容
            scene_type: 场景类型

        Returns:
            校验结果字典
        """
        issues: list[str] = []

        # 事实完整性：检查关键数字/数据是否保留
        import re
        numbers_raw = re.findall(r'\d+', raw_content)
        numbers_polished = re.findall(r'\d+', polished_content)
        if len(numbers_raw) > 0 and len(numbers_polished) < len(numbers_raw):
            issues.append(f"事实完整性警告：原始{len(numbers_raw)}个数字，润色后{len(numbers_polished)}个")

        # 红线检测
        red_line = self.red_line_check(polished_content)
        if red_line["has_violation"]:
            issues.append(f"红线违规：{', '.join(red_line['violations'])}")

        # 场景语气一致性（概念级：检查是否包含场景关键词）
        resolved = self._resolve_identifier(scene_type)
        scene_config = MODE_TONE_OFFSETS[resolved["mode_key"]]
        keywords = scene_config.get("keywords", [])
        if resolved["level"] == "scene" and resolved["scene_key"] in SCENE_TONE_FINETUNE:
            finetune = SCENE_TONE_FINETUNE[resolved["scene_key"]]
            keywords = keywords + finetune.get("extra_keywords", [])
        has_tone_marker = any(kw in polished_content for kw in keywords)
        if not has_tone_marker and len(polished_content) > 20:
            issues.append(f"语气一致性提示：未检测到{scene_config['name']}场景典型语气词")

        passed = len([i for i in issues if "警告" in i or "违规" in i]) == 0

        return {
            "passed": passed,
            "issue_count": len(issues),
            "issues": issues,
            "fact_integrity": len(numbers_polished) >= len(numbers_raw) if numbers_raw else True,
            "tone_consistency": has_tone_marker,
            "red_line_clean": not red_line["has_violation"],
        }

    def red_line_check(self, content: str) -> dict[str, Any]:
        """红线违规检测

        扫描内容中是否包含禁忌词（机器化表述、内部架构泄露等）。

        Args:
            content: 待检测内容

        Returns:
            检测结果字典
        """
        violations: list[str] = []
        for pattern in RED_LINE_PATTERNS:
            if pattern in content:
                violations.append(pattern)

        return {
            "has_violation": len(violations) > 0,
            "violations": violations,
            "violation_count": len(violations),
        }

    def get_personality_for_scene(
        self,
        scene_type: str = "life_management",
        user_context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """获取指定场景/模式的人格参数

        支持传入底层模式名或上层场景名，自动解析。

        Args:
            scene_type: 场景/模式标识
            user_context: 用户偏好上下文

        Returns:
            人格参数字典
        """
        personality = self._calc_personality(scene_type, user_context or {})
        resolved = self._resolve_identifier(scene_type)
        scene_config = MODE_TONE_OFFSETS[resolved["mode_key"]]
        keywords = list(scene_config.get("keywords", []))
        if resolved["level"] == "scene" and resolved["scene_key"] in SCENE_TONE_FINETUNE:
            finetune = SCENE_TONE_FINETUNE[resolved["scene_key"]]
            keywords += finetune.get("extra_keywords", [])

        return {
            "scene_type": scene_type,
            "scene_name": scene_config["name"],
            "tone_level": resolved["level"],
            "resolved_mode": resolved["mode_key"],
            "resolved_scene": resolved["scene_key"],
            "personality_params": personality,
            "tone_keywords": keywords,
        }

    def set_user_preferences(
        self,
        user_id: str,
        preferences: dict[str, Any],
    ) -> None:
        """设置用户个性化偏好（本地缓存）

        Args:
            user_id: 用户ID
            preferences: 偏好字典（tone_temp/formality/verbosity/humor/nickname）
        """
        self._user_preferences[user_id] = preferences
        self._logger.info(
            "user_preferences_updated",
            user_id=user_id,
            preferences_keys=list(preferences.keys()),
        )

    def update_preference(
        self,
        user_id: str,
        preferences: dict[str, Any],
        source: str = "local",
    ) -> dict[str, Any]:
        """[V10.1] 更新用户人格偏好（支持本地缓存 + M5持久化）

        完整链路：M4 → M1 → YunxiVoice → M5 潮汐记忆（L2海湾层）
        本地缓存更新为同步操作，M5 持久化为异步委托（此处仅记录意图）。

        隐私规则：人格偏好数据标记为 CONFIDENTIAL 级，跨设备同步时
        须经 Security-Agent 脱敏检查。M5 不可用时回退默认值。

        Args:
            user_id: 用户ID
            preferences: 偏好字典，支持字段：
                - tone_temperature: colder / default / warmer
                - formality_level: casual / medium / formal
                - verbosity: concise / balanced / detailed
                - humor_level: low / medium / high
                - nickname: 用户自定义称呼
            source: 偏好来源（local / m5_sync / user_setting）

        Returns:
            更新结果字典
        """
        if not user_id:
            return {
                "success": False,
                "error": "user_id_required",
            }

        # 合并到现有偏好（增量更新，不覆盖未提供的字段）
        existing = self._user_preferences.get(user_id, {})
        merged = {**existing, **preferences}
        self._user_preferences[user_id] = merged

        self._logger.info(
            "voice_preference_updated",
            user_id=user_id,
            source=source,
            updated_keys=list(preferences.keys()),
            security_level="CONFIDENTIAL",
        )

        return {
            "success": True,
            "user_id": user_id,
            "preferences": merged,
            "security_level": "CONFIDENTIAL",
            "storage": {
                "local_cache": "updated",
                "m5_persistence": "delegated",  # 委托M5持久化，此处为概念级
            },
            "version": len(existing) + 1,
        }

    def get_user_preference(
        self,
        user_id: str,
    ) -> dict[str, Any]:
        """获取用户偏好（从本地缓存读取，M5读取由Orchestrator负责）

        Args:
            user_id: 用户ID

        Returns:
            用户偏好字典，不存在则返回空字典
        """
        return self._user_preferences.get(user_id, {})

    # ── 内部方法 ──────────────────────────────────────────

    def _resolve_identifier(self, identifier: str) -> dict[str, str]:
        """解析场景/模式标识符

        自动判断输入是底层模式名还是上层场景名，返回标准化的解析结果。

        Args:
            identifier: 模式名（如 CODING）或场景名（如 work_dev）

        Returns:
            包含 mode_key、scene_key、level 的字典
        """
        identifier_upper = identifier.upper()
        identifier_lower = identifier.lower()

        # 先尝试匹配底层模式（大写枚举）
        if identifier_upper in MODE_TONE_OFFSETS:
            mode_key = identifier_upper
            # 查找对应的主场景
            try:
                mode_enum = M4ExecutionMode(identifier_upper)
                scene_key = MODE_TO_SCENE_PRIMARY.get(mode_enum, UserScene.LIFE_MANAGEMENT).value
            except ValueError:
                scene_key = UserScene.LIFE_MANAGEMENT.value
            return {
                "mode_key": mode_key,
                "scene_key": scene_key,
                "level": "mode",
            }

        # 再尝试匹配上层场景
        if identifier_lower in SCENE_TONE_FINETUNE:
            scene_key = identifier_lower
            finetune = SCENE_TONE_FINETUNE[scene_key]
            mode_key = finetune["base_mode"]
            return {
                "mode_key": mode_key,
                "scene_key": scene_key,
                "level": "scene",
            }

        # 都不匹配：降级到默认场景
        self._logger.warning(
            "voice_identifier_not_found",
            identifier=identifier,
            fallback="life_management",
        )
        default_scene = UserScene.LIFE_MANAGEMENT.value
        return {
            "mode_key": SCENE_TONE_FINETUNE[default_scene]["base_mode"],
            "scene_key": default_scene,
            "level": "scene",
        }

    def _calc_personality(
        self,
        scene_type: str,
        user_context: dict[str, Any],
    ) -> dict[str, float]:
        """计算最终人格参数

        基础人格 + 底层模式偏移 + 上层场景微调 + 用户偏好微调。
        所有维度钳位到 0-10。

        Args:
            scene_type: 场景/模式标识
            user_context: 用户偏好上下文

        Returns:
            五维人格参数字典
        """
        base = dict(DEFAULT_PERSONALITY)
        resolved = self._resolve_identifier(scene_type)

        # 叠加底层模式偏移
        mode_offset = MODE_TONE_OFFSETS.get(resolved["mode_key"], {})
        for dim in base:
            if dim in mode_offset:
                base[dim] += mode_offset[dim]

        # 叠加上层场景微调（如果是场景级）
        if resolved["level"] == "scene" and resolved["scene_key"] in SCENE_TONE_FINETUNE:
            scene_finetune = SCENE_TONE_FINETUNE[resolved["scene_key"]]
            for dim in base:
                if dim in scene_finetune:
                    base[dim] += scene_finetune[dim]

        # 钳位到 0-10
        for dim in base:
            base[dim] = max(0.0, min(10.0, base[dim]))

        # 用户偏好微调（如提供）
        tone_temp = user_context.get("tone_preference", "default")
        if tone_temp == "warmer":
            base["warmth"] = min(10.0, base["warmth"] + 0.5)
        elif tone_temp == "colder":
            base["warmth"] = max(0.0, base["warmth"] - 0.5)

        formality = user_context.get("formality_level", "medium")
        if formality == "formal":
            base["rationality"] = min(10.0, base["rationality"] + 0.5)
            base["warmth"] = max(0.0, base["warmth"] - 0.5)
        elif formality == "casual":
            base["warmth"] = min(10.0, base["warmth"] + 0.5)
            base["rationality"] = max(0.0, base["rationality"] - 0.5)

        return base

    def _skeleton_polish(
        self,
        raw_content: str,
        scene: dict[str, Any],
        length_hint: str,
    ) -> str:
        """骨架级润色（概念实现）

        实际生产环境应由LLM基于人格参数执行润色。
        此处为骨架实现：添加场景语气标识 + 基本格式化。

        Args:
            raw_content: 原始内容
            scene: 场景配置
            length_hint: 长度提示

        Returns:
            润色后文本
        """
        if not raw_content:
            return ""

        # 骨架实现：保留原文，仅在开头注入场景语气词
        # 实际润色逻辑应由LLM完成
        keywords = scene.get("keywords", ["嗯"])
        opener = keywords[0] + "，"

        # 如果原文已经以语气词开头则不重复添加
        if any(raw_content.startswith(kw) for kw in keywords):
            return raw_content

        return opener + raw_content

    def _mental_privacy_check(
        self,
        raw_content: str,
        polished_content: str,
    ) -> str:
        """MENTAL场景隐私检查

        确保润色结果不包含原始情绪对话内容，仅基于结构化指标。

        Returns:
            "passed" / "failed"
        """
        # 概念级实现：检查是否包含对话标记（如"用户说："、"我问："等）
        dialog_markers = ["用户说：", "我说：", "他说：", "她说：", "对话内容", "原始对话"]
        for marker in dialog_markers:
            if marker in polished_content:
                self._logger.warning(
                    "mental_privacy_violation_detected",
                    marker=marker,
                )
                return "failed"
        return "passed"
