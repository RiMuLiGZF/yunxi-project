"""
隐私卫士 — PrivacyGuard 主入口

职责：协调 PII 检测、风险分类、内容脱敏、审计日志、外传检查。
"""

from __future__ import annotations

import hashlib
import time
from typing import Any

import structlog

from shared_models import SecurityClassification

from .detector import PIIDetector
from .sanitizer import Sanitizer
from .classifier import RiskClassifier

logger = structlog.get_logger(__name__)


class PrivacyGuard:
    """隐私卫士

    职责：
    - PII（个人可识别信息）检测
    - 风险等级评估
    - 内容脱敏/清洗
    - 审计日志
    - 内网 URL 识别与拦截
    """

    def __init__(self, custom_keywords: list[str] | None = None) -> None:
        self._custom_keywords: list[str] = custom_keywords or []
        self._detector = PIIDetector(self._custom_keywords[:])
        self._sanitizer = Sanitizer()
        self._classifier = RiskClassifier()
        self._audit_log: list[dict[str, Any]] = []
        self._scan_count: int = 0
        self._sanitize_count: int = 0
        self._block_count: int = 0
        self._logger = logger.bind(component="privacy_guard")

    # ════════════════════════════════════════════════════
    #  公共方法
    # ════════════════════════════════════════════════════

    def scan_content(
        self,
        content: str,
        security_level: SecurityClassification = SecurityClassification.INTERNAL,
        context: str = "",
    ) -> dict[str, Any]:
        """扫描内容中的 PII

        Args:
            content: 待扫描的内容
            security_level: 涉密等级
            context: 扫描上下文说明

        Returns:
            扫描结果字典
        """
        self._scan_count += 1

        # Step 1: 预处理归一化（防绕过）
        normalized = self._detector.normalize_content(content)

        # Step 2: 检测各类 PII
        detections = self._detector.detect_all_pii(normalized)

        # Step 3: 评估风险等级
        risk_level, risk_score = self._classifier.assess_risk_level(detections, security_level)

        # Step 4: 生成审计摘要
        audit_entry = self._build_audit_entry(
            content=content,
            detections=detections,
            risk_level=risk_level,
            risk_score=risk_score,
            security_level=security_level,
            context=context,
            action="scan",
        )
        self._audit_log.append(audit_entry)

        result = {
            "has_pii": len(detections) > 0,
            "detections": detections,
            "pii_types": list({d["pii_type"] for d in detections}),
            "pii_count": len(detections),
            "risk_level": risk_level,
            "risk_score": risk_score,
            "security_level": security_level.value,
            "audit_id": audit_entry["audit_id"],
            "content_hash": audit_entry["content_hash"],
            "content_length": audit_entry["content_length"],
        }

        if detections:
            self._logger.info(
                "pii_detected",
                pii_count=len(detections),
                pii_types=result["pii_types"],
                risk_level=risk_level,
                risk_score=round(risk_score, 2),
                context=context,
            )

        return result

    def sanitize_content(
        self,
        content: str,
        security_level: SecurityClassification = SecurityClassification.INTERNAL,
        target_risk: str = "low",
        context: str = "",
    ) -> dict[str, Any]:
        """对内容进行脱敏处理

        [V11.1 修复] 不再以 high 为唯一阈值，所有检测到 PII 的内容都进入脱敏分支。
        根据风险等级采用不同脱敏强度：
        - critical: 完全替换为 [已脱敏]
        - high: 强脱敏（只保留极少特征）
        - medium: 中等脱敏（保留部分特征）
        - low: 轻脱敏（保留大部分特征）

        Args:
            content: 待脱敏内容
            security_level: 涉密等级
            target_risk: 目标风险等级（low/medium/high）
            context: 上下文说明

        Returns:
            脱敏结果字典
        """
        self._sanitize_count += 1

        # Step 1: 扫描检测
        scan_result = self.scan_content(content, security_level, context)
        detections = scan_result["detections"]
        risk_level = scan_result["risk_level"]

        # Step 2: 执行脱敏（所有检测到 PII 的都执行，只是强度不同）
        sanitized = content
        if detections:
            sanitized = self._sanitizer.sanitize(
                content, detections, risk_level, target_risk,
                custom_keywords=self._custom_keywords,
            )

        # Step 3: 审计记录
        audit_entry = self._build_audit_entry(
            content=sanitized,
            detections=detections,
            risk_level=risk_level,
            risk_score=scan_result["risk_score"],
            security_level=security_level,
            context=context,
            action="sanitize",
            original_hash=scan_result["content_hash"],
        )
        self._audit_log.append(audit_entry)

        return {
            "original": content,
            "sanitized": sanitized,
            "sanitized_preview": self._make_preview(sanitized),
            "was_modified": content != sanitized,
            "pii_count": len(detections),
            "pii_types": scan_result["pii_types"],
            "risk_level": risk_level,
            "risk_score": scan_result["risk_score"],
            "audit_id": audit_entry["audit_id"],
            "content_hash": audit_entry["content_hash"],
            "content_length": audit_entry["content_length"],
            "sanitized_preview_length": len(audit_entry.get("sanitized_preview", "")),
        }

    def check_external_transfer(
        self,
        content: str,
        target_agent_id: str,
        agent_privacy_level: str = "standard",
        security_level: SecurityClassification = SecurityClassification.INTERNAL,
    ) -> dict[str, Any]:
        """检查内容是否可以传输给外部 Agent

        Args:
            content: 待传输内容
            target_agent_id: 目标 Agent ID
            agent_privacy_level: 目标 Agent 隐私等级
            security_level: 内容涉密等级

        Returns:
            检查结果
        """
        scan_result = self.scan_content(content, security_level, f"transfer:{target_agent_id}")
        risk_level = scan_result["risk_level"]

        can_transfer = True
        block_reason = ""

        # TOP_SECRET 涉密内容 + high/critical 风险 = 阻止
        if security_level >= SecurityClassification.TOP_SECRET and risk_level in ("high", "critical"):
            can_transfer = False
            block_reason = "最高涉密内容包含高风险 PII，禁止外传"
            self._block_count += 1

        # CONFIDENTIAL 涉密 + critical 风险 + 标准隐私 Agent = 阻止
        elif (
            security_level >= SecurityClassification.CONFIDENTIAL
            and risk_level == "critical"
            and agent_privacy_level == "standard"
        ):
            can_transfer = False
            block_reason = "涉密内容包含关键 PII，目标 Agent 隐私等级不足"
            self._block_count += 1

        # 含私钥内容一律阻止外传
        elif any(d["pii_type"] == "private_key" for d in scan_result["detections"]):
            can_transfer = False
            block_reason = "内容包含私钥，禁止外传"
            self._block_count += 1

        result = {
            "can_transfer": can_transfer,
            "block_reason": block_reason,
            "risk_level": risk_level,
            "pii_count": scan_result["pii_count"],
            "pii_types": scan_result["pii_types"],
            "recommendation": "sanitize_before_transfer" if (scan_result["pii_count"] > 0 and can_transfer) else "",
            "audit_id": scan_result["audit_id"],
        }

        if not can_transfer:
            self._logger.warning(
                "transfer_blocked",
                target_agent=target_agent_id,
                reason=block_reason,
                risk_level=risk_level,
            )

        return result

    # ════════════════════════════════════════════════════
    #  内部方法 — 审计与工具
    # ════════════════════════════════════════════════════

    def _build_audit_entry(
        self,
        content: str,
        detections: list[dict[str, Any]],
        risk_level: str,
        risk_score: float,
        security_level: SecurityClassification,
        context: str,
        action: str,
        original_hash: str = "",
    ) -> dict[str, Any]:
        """构建审计条目（V11.1 增加摘要字段）"""
        content_bytes = content.encode("utf-8")
        return {
            "audit_id": f"priv_{int(time.time()*1000)}_{abs(hash(context+action)) % 10000:04d}",
            "timestamp": time.time(),
            "action": action,
            "context": context,
            "risk_level": risk_level,
            "risk_score": round(risk_score, 2),
            "security_level": security_level.value,
            "pii_count": len(detections),
            "pii_types_detected": list({d["pii_type"] for d in detections}),
            "content_hash": hashlib.sha256(content_bytes).hexdigest(),
            "content_length": len(content_bytes),
            "sanitized_preview": self._make_preview(content),
            "original_hash": original_hash,
        }

    @staticmethod
    def _make_preview(content: str, max_len: int = 200) -> str:
        """生成内容预览（脱敏后安全的短文本）"""
        if not content:
            return ""
        if len(content) <= max_len:
            return content
        return content[:max_len] + "..."

    # ════════════════════════════════════════════════════
    #  配置与统计
    # ════════════════════════════════════════════════════

    def add_custom_keyword(self, keyword: str) -> None:
        """添加自定义敏感词"""
        if keyword and keyword not in self._custom_keywords:
            self._custom_keywords.append(keyword)
            self._detector.add_custom_keyword(keyword)

    def remove_custom_keyword(self, keyword: str) -> bool:
        """移除自定义敏感词"""
        if keyword in self._custom_keywords:
            self._custom_keywords.remove(keyword)
            return self._detector.remove_custom_keyword(keyword)
        return False

    def get_audit_log(self, limit: int = 100) -> list[dict[str, Any]]:
        """获取审计日志"""
        return list(reversed(self._audit_log[-limit:]))

    def stats(self) -> dict[str, Any]:
        """统计信息"""
        return {
            "total_scans": self._scan_count,
            "total_sanitizations": self._sanitize_count,
            "total_blocks": self._block_count,
            "custom_keywords_count": len(self._custom_keywords),
            "audit_log_size": len(self._audit_log),
        }


# 兼容别名（V11.0 命名）
FederationPrivacyGuard = PrivacyGuard


# ══════════════════════════════════════════════════════════
# V11.0 兼容层 — 适配旧 API 签名
# ══════════════════════════════════════════════════════════

class _LegacyScanResult:
    """V11.0 风格的扫描结果对象（带属性访问）"""

    def __init__(self, scan_result: dict[str, Any], auto_sanitize: bool = False, guard: Any = None, content: str = "", security_level: Any = None) -> None:
        self._raw = scan_result
        self.passed = not scan_result.get("has_pii", False)
        self.blocked = False
        self.risk_level = scan_result.get("risk_level", "none")
        self.risk_score = scan_result.get("risk_score", 0.0)
        self.sanitized_content = ""

        # 转换 detections 格式（兼容旧的多 type 体系）
        self.detections = []
        for d in scan_result.get("detections", []):
            pii_type = d.get("pii_type", "")
            if pii_type in ("api_key", "password", "token", "private_key"):
                # 代码密钥类
                det = dict(d)
                det["type"] = "code_secret"
                det["secret_type"] = pii_type
                self.detections.append(det)
            elif pii_type == "custom_keyword":
                det = dict(d)
                det["type"] = "custom_keyword"
                self.detections.append(det)
            else:
                # 普通 PII
                det = dict(d)
                det["type"] = "pii"
                self.detections.append(det)

        self.pii_count = scan_result.get("pii_count", 0)
        self.pii_types = scan_result.get("pii_types", [])
        self.content_hash = scan_result.get("content_hash", "")
        self.content_length = scan_result.get("content_length", 0)

        # V11.0 行为：TOP_SECRET 和 CONFIDENTIAL 级别即使无 PII 也拦截
        if security_level is not None:
            try:
                # 支持 enum 或 int 或 string
                if hasattr(security_level, 'value'):
                    sec_val = security_level.value
                else:
                    sec_val = security_level

                # TOP_SECRET = 3
                if sec_val == 3 or str(sec_val).lower() in ("top_secret", "topsecret"):
                    self.blocked = True
                    self.passed = False
                    if self.risk_level == "none":
                        self.risk_level = "high"
                # CONFIDENTIAL = 2
                elif sec_val == 2 or str(sec_val).lower() in ("confidential", "secret"):
                    self.blocked = True
                    if self.risk_level == "none":
                        self.risk_level = "medium"
            except Exception:
                pass

        # auto_sanitize 模式：自动脱敏
        if auto_sanitize and guard is not None and content:
            san_result = guard.sanitize_content(
                content,
                security_level if security_level is not None else SecurityClassification.INTERNAL,
            )
            self.sanitized_content = san_result["sanitized"]

    def __getattr__(self, name: str) -> Any:
        if name in self._raw:
            return self._raw[name]
        raise AttributeError(f"'{type(self).__name__}' object has no attribute '{name}'")

    def model_dump(self) -> dict[str, Any]:
        """兼容 Pydantic model_dump 方法"""
        return {
            "passed": self.passed,
            "blocked": self.blocked,
            "risk_level": self.risk_level,
            "risk_score": self.risk_score,
            "detections": self.detections,
            "pii_count": self.pii_count,
            "pii_types": self.pii_types,
            "sanitized_content": self.sanitized_content,
            "content_hash": self.content_hash,
            "content_length": self.content_length,
        }

    def dict(self) -> dict[str, Any]:
        """兼容 Pydantic dict 方法"""
        return self.model_dump()

    @property
    def summary(self) -> str:
        """结果摘要（兼容 V11.0）"""
        if self.blocked:
            return f"内容被拦截（风险等级：{self.risk_level}，检测到 {self.pii_count} 项敏感信息）"
        if self.pii_count > 0:
            return f"检测到 {self.pii_count} 项敏感信息（风险等级：{self.risk_level}）"
        return "内容安全，未检测到敏感信息"


def _patch_legacy_methods() -> None:
    """为 PrivacyGuard 打补丁，添加 V11.0 兼容方法"""

    def scan(self, content: str, security_level: Any = None, **kwargs: Any) -> _LegacyScanResult:
        """V11.0 兼容：scan 方法"""
        if security_level is None:
            security_level = SecurityClassification.INTERNAL
        result = self.scan_content(content, security_level, context=kwargs.get("context", ""))
        return _LegacyScanResult(
            result,
            auto_sanitize=getattr(self, 'auto_sanitize', False),
            guard=self,
            content=content,
            security_level=security_level,
        )

    def sanitize(self, content: str, security_level: Any = None, **kwargs: Any) -> dict[str, Any]:
        """V11.0 兼容：sanitize 方法"""
        if security_level is None:
            security_level = SecurityClassification.INTERNAL
        return self.sanitize_content(content, security_level, context=kwargs.get("context", ""))

    def add_blocked_keyword(self, keyword: str) -> bool:
        """V11.0 兼容：添加拦截关键词"""
        if keyword and keyword not in self._custom_keywords:
            self._custom_keywords.append(keyword)
            return True
        return False

    def remove_blocked_keyword(self, keyword: str) -> bool:
        """V11.0 兼容：移除拦截关键词"""
        return self.remove_custom_keyword(keyword)

    # 绑定方法
    PrivacyGuard.scan = scan
    PrivacyGuard.sanitize = sanitize
    PrivacyGuard.add_blocked_keyword = add_blocked_keyword
    PrivacyGuard.remove_blocked_keyword = remove_blocked_keyword

    # 处理 auto_sanitize 参数和默认关键词
    _orig_init = PrivacyGuard.__init__

    def _new_init(self, custom_keywords: list[str] | None = None, auto_sanitize: bool = False, blocked_keywords: list[str] | None = None) -> None:
        _orig_init(self, custom_keywords=custom_keywords)
        self.auto_sanitize = auto_sanitize
        # V11.0 兼容：默认内置关键词（当 custom_keywords 为 None 时添加）
        if custom_keywords is None and blocked_keywords is None:
            default_keywords = ["内部机密", "绝密", "机密文件", "请勿外传"]
            for kw in default_keywords:
                if kw not in self._custom_keywords:
                    self._custom_keywords.append(kw)
                    self._detector.add_custom_keyword(kw)
        if blocked_keywords:
            for kw in blocked_keywords:
                if kw not in self._custom_keywords:
                    self._custom_keywords.append(kw)
                    self._detector.add_custom_keyword(kw)

    PrivacyGuard.__init__ = _new_init


# 自动打补丁
_patch_legacy_methods()