"""
安全审计与涉密拦截子Agent — SecurityAgent

集成 GuardrailsV2 + SecurityClassifier + AuditLog，
提供输入安检、内容分级、权限预检、审计留痕等安全能力。

依赖：
- src.security.guardrails.GuardrailsV2：Prompt注入检测 + PII脱敏
- security.classifier.SecurityClassifier：涉密内容分级
- security.audit_log.AuditLog：操作日志留痕
- interfaces.IAgentPlugin / AgentTask / AgentResult：插件接口
- shared_models.SecurityClassification：涉密分级枚举
"""

from __future__ import annotations

import time
from typing import Any

import structlog

from src.tools.interfaces import (
    AgentTask,
    AgentResult,
    IAgentPlugin,
)
from shared_models import SecurityClassification
from src.security.guardrails import GuardrailsV2
from src.security.classifier import SecurityClassifier
from src.security.audit_log import AuditLog

logger = structlog.get_logger(__name__)


class SecurityAgent(IAgentPlugin):
    """安全审计与涉密拦截子Agent

    面向 Agent 集群提供统一的安全管控接口：
    - 输入安检：Prompt注入检测 + PII脱敏 + 涉密分级
    - 内容分级与审计留痕
    - 访问控制（基于涉密等级）
    - 审计日志查询
    """

    agent_id: str = "agent.security"
    version: str = "1.0.0"
    capabilities: list[str] = [
        "security.check_input",
        "security.classify",
        "security.classify_and_audit",
        "security.check_access",
        "security.audit_trail",
        "security.strip",
    ]

    def __init__(
        self,
        injection_threshold: float = 0.7,
        enable_pii_sanitize: bool = True,
    ) -> None:
        self._logger = logger.bind(agent_id=self.agent_id)
        # 初始化各安全组件
        self._guardrails = GuardrailsV2(
            injection_threshold=injection_threshold,
            enable_pii_sanitize=enable_pii_sanitize,
        )
        self._classifier = SecurityClassifier()
        self._audit_log = AuditLog()
        # Agent涉密等级缓存：agent_id -> SecurityClassification
        self._agent_clearances: dict[str, SecurityClassification] = {}

    # ── 生命周期 ──────────────────────────────────────────

    async def on_mount(self, registry: Any | None = None) -> None:
        """挂载时初始化安全组件"""
        self._logger.info(
            "security_agent_mounted",
            injection_threshold=self._guardrails.injection_detector.threshold,
            enable_pii=self._guardrails.enable_pii,
        )

    async def health(self) -> dict[str, Any]:
        """健康检查：包含审计日志统计"""
        base = await super().health()
        base["audit_stats"] = self._audit_log.stats()
        base["registered_agents"] = len(self._agent_clearances)
        return base

    # ── 核心任务处理 ─────────────────────────────────────

    async def handle_task(self, task: AgentTask) -> AgentResult:
        """处理安检/分级/审计请求

        支持的 intent：
        - security.check_input      ：输入安检（Prompt注入+PII+涉密分级）
        - security.classify         ：内容分级
        - security.classify_and_audit：分级+留痕
        - security.check_access     ：访问控制
        - security.audit_trail     ：审计日志查询
        - security.strip           ：内容脱敏
        """
        start_time = time.time()
        self._logger.info(
            "security_agent_handling_task",
            trace_id=task.trace_id,
            task_id=task.task_id,
            intent=task.intent,
        )

        try:
            intent = task.intent
            payload = task.payload

            if intent == "security.check_input":
                text: str = payload.get("text", "")
                output = self.check_input(text)
            elif intent == "security.classify":
                content: str = payload.get("content", "")
                level = self._classifier.classify_content(content)
                output = {
                    "classification": level.name,
                    "classification_value": level.value,
                }
            elif intent == "security.classify_and_audit":
                content: str = payload.get("content", "")
                agent_id: str = payload.get("agent_id", task.source)
                output = self.classify_and_audit(content, agent_id)
            elif intent == "security.check_access":
                agent_id: str = payload.get("agent_id", task.source)
                resource_level_str: str = payload.get("resource_level", "PUBLIC")
                resource_level = SecurityClassification[resource_level_str]
                allowed = self.check_access(agent_id, resource_level)
                output = {
                    "allowed": allowed,
                    "agent_id": agent_id,
                    "resource_level": resource_level_str,
                }
            elif intent == "security.audit_trail":
                agent_id: str = payload.get("agent_id", "")
                time_range: tuple[float, float] | None = None
                if "time_start" in payload and "time_end" in payload:
                    time_range = (payload["time_start"], payload["time_end"])
                entries = self.get_audit_trail(agent_id, time_range)
                output = {
                    "entries": [
                        {
                            "entry_id": e.entry_id,
                            "timestamp": e.timestamp,
                            "agent_id": e.agent_id,
                            "action": e.action,
                            "resource": e.resource,
                            "classification": e.classification,
                            "result": e.result,
                            "detail": e.detail,
                        }
                        for e in entries
                    ],
                    "count": len(entries),
                }
            elif intent == "security.strip":
                content: str = payload.get("content", "")
                target_level_str: str = payload.get("target_level", "PUBLIC")
                target_level = SecurityClassification[target_level_str]
                stripped = self._classifier.strip_for_level(content, target_level)
                output = {
                    "stripped_content": stripped,
                    "original_length": len(content),
                    "stripped_length": len(stripped),
                    "target_level": target_level_str,
                }
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
                "security_agent_task_failed",
                error=str(exc),
                exc_info=True,
                task_id=task.task_id,
            )
            return AgentResult(
                task_id=task.task_id,
                trace_id=task.trace_id,
                agent_id=self.agent_id,
                status="failure",
                error=f"SecurityAgent任务处理失败: {exc}",
                latency_ms=(time.time() - start_time) * 1000,
            )

    # ── 公开API ──────────────────────────────────────────

    def check_input(self, text: str) -> dict[str, Any]:
        """输入安检（Prompt注入 + PII + 涉密分级）

        执行完整的安全检查流程：
        1. Prompt Injection 检测（GuardrailsV2）
        2. PII 脱敏（GuardrailsV2）
        3. 涉密分级（SecurityClassifier）
        4. 审计留痕（AuditLog）

        Args:
            text: 待检查的输入文本

        Returns:
            包含安检结果的字典
        """
        # 步骤1+2：GuardrailsV2 安检（Prompt注入 + PII）
        guard_result = self._guardrails.check(text)

        # 步骤3：涉密分级（使用脱敏后的文本）
        classification = self._classifier.classify_content(guard_result.sanitized_text)

        # 步骤4：审计留痕
        self._audit_log.record(
            agent_id="system",
            action="check_input",
            resource="",
            classification=classification.name,
            result="deny" if guard_result.blocked else "allow",
            detail=f"risk_score={guard_result.risk_score:.2f}, "
                   f"blocked={guard_result.blocked}, "
                   f"classification={classification.name}",
        )

        self._logger.info(
            "input_check_completed",
            blocked=guard_result.blocked,
            risk_score=guard_result.risk_score,
            classification=classification.name,
            pii_count=len([d for d in guard_result.detections if d.get("type") == "pii_detected"]),
        )

        return {
            "blocked": guard_result.blocked,
            "block_reason": guard_result.block_reason,
            "risk_score": round(guard_result.risk_score, 4),
            "sanitized_text": guard_result.sanitized_text,
            "classification": classification.name,
            "classification_value": classification.value,
            "detections": guard_result.detections,
        }

    def classify_and_audit(self, content: str, agent_id: str) -> dict[str, Any]:
        """内容分级 + 审计留痕

        对内容进行涉密分级，并将结果记录到审计日志。

        Args:
            content: 待分级的内容
            agent_id: 请求分级的Agent ID

        Returns:
            包含分级结果和审计信息的字典
        """
        # 执行分级
        level = self._classifier.classify_content(content)

        # 审计留痕
        entry = self._audit_log.record(
            agent_id=agent_id,
            action="classify",
            resource="",
            classification=level.name,
            result="allow",
            detail=f"content_length={len(content)}, classification={level.name}",
        )

        self._logger.info(
            "classify_and_audit_completed",
            agent_id=agent_id,
            classification=level.name,
            entry_id=entry.entry_id,
        )

        return {
            "classification": level.name,
            "classification_value": level.value,
            "audit_entry_id": entry.entry_id,
            "audit_timestamp": entry.timestamp,
        }

    def check_access(
        self,
        agent_id: str,
        resource_level: SecurityClassification,
    ) -> bool:
        """访问控制

        检查 Agent 是否有权限访问指定涉密等级的资源。
        使用 SecurityClassifier 的 check_clearance 方法。

        Args:
            agent_id: Agent ID
            resource_level: 资源的涉密等级

        Returns:
            True 表示允许访问，False 表示拒绝
        """
        # 获取Agent的涉密等级，未注册则默认PUBLIC
        agent_clearance = self._agent_clearances.get(
            agent_id, SecurityClassification.PUBLIC
        )

        is_allowed = self._classifier.check_clearance(agent_clearance, resource_level)

        # 审计留痕
        self._audit_log.record(
            agent_id=agent_id,
            action="check_access",
            resource="",
            classification=resource_level.name,
            result="allow" if is_allowed else "deny",
            detail=f"agent_clearance={agent_clearance.name}, "
                   f"resource_level={resource_level.name}",
        )

        if not is_allowed:
            self._logger.warning(
                "access_denied",
                agent_id=agent_id,
                agent_clearance=agent_clearance.name,
                resource_level=resource_level.name,
            )

        return is_allowed

    def get_audit_trail(
        self,
        agent_id: str | None = None,
        time_range: tuple[float, float] | None = None,
    ) -> list[dict[str, Any]]:
        """查询审计日志

        Args:
            agent_id:   按Agent ID过滤（None表示全部）
            time_range: 时间范围 (start, end)，None表示不限

        Returns:
            审计条目字典列表
        """
        entries = self._audit_log.query(
            agent_id=agent_id,
            time_range=time_range,
        )
        return [
            {
                "entry_id": e.entry_id,
                "timestamp": e.timestamp,
                "agent_id": e.agent_id,
                "action": e.action,
                "resource": e.resource,
                "classification": e.classification,
                "result": e.result,
                "detail": e.detail,
            }
            for e in entries
        ]

    def register_agent_clearance(
        self,
        agent_id: str,
        clearance: SecurityClassification,
    ) -> None:
        """注册Agent的涉密等级

        Args:
            agent_id:  Agent ID
            clearance: 涉密等级
        """
        self._agent_clearances[agent_id] = clearance
        self._audit_log.record(
            agent_id="system",
            action="register_clearance",
            resource=agent_id,
            classification=clearance.name,
            result="allow",
            detail=f"注册Agent {agent_id} 的涉密等级为 {clearance.name}",
        )
        self._logger.info(
            "agent_clearance_registered",
            agent_id=agent_id,
            clearance=clearance.name,
        )
