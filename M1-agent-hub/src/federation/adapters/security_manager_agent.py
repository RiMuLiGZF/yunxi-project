"""
安全管家 Agent 适配器 — SecurityManagerAgentAdapter

M7 安全防护系统的智能代理，负责系统安全和隐私保护。

核心能力：
  - 安全审计：系统安全扫描、漏洞检测、风险评估
  - 隐私保护：数据脱敏、隐私等级管理、敏感信息识别
  - 权限管理：用户权限控制、访问控制、认证管理
  - 威胁检测：异常行为检测、入侵检测、安全告警
  - 数据脱敏：自动识别和处理敏感数据

身份设定：安全管家 — 云汐的安全守护官，严谨、警惕、可靠、保护用户安全

使用示例：
    adapter = SecurityManagerAgentAdapter(
        agent_id="security_manager_01",
        display_name="安全管家",
        config={
            "m7_base_url": "http://localhost:8007",
            "ollama_base_url": "http://localhost:11434",
            "model_name": "qwen2.5:3b",
        },
    )

    # 安全审计
    result = await adapter.invoke("对系统进行一次安全审计")

    # 数据脱敏
    result = await adapter.invoke("帮我把这段文本中的敏感信息脱敏")
"""

from __future__ import annotations

import json
from typing import Any

import httpx
import structlog

from src.federation.adapters.base import AgentAdapterBase

logger = structlog.get_logger(__name__)


class SecurityManagerAgentAdapter(AgentAdapterBase):
    """安全管家 Agent — 云汐的安全守护官

    基于 M7 安全防护系统 + 本地轻量大模型，负责：
      1. 安全审计（系统扫描、漏洞检测、风险评估）
      2. 隐私保护（数据脱敏、敏感信息识别）
      3. 权限管理（访问控制、认证管理）
      4. 威胁检测（异常行为、入侵检测）
      5. 积木平台安全沙箱管理
    """

    provider: str = "SecurityManager"
    adapter_type: str = "security_manager_agent"

    # ── 系统提示词 ───────────────────────────────────────────────────────

    _SYSTEM_PROMPT: str = """你是「安全管家」，云汐系统的安全守护官。

## 你的身份

你负责云汐系统的所有安全事务，像一位严谨的安全卫士。
你时刻保持警惕，对任何安全风险都零容忍。
你性格严谨、冷静、可靠，把用户的安全和隐私放在第一位。

## 你的能力

1. **安全审计**：定期扫描系统安全漏洞，评估风险等级
2. **隐私保护**：识别和保护用户的敏感信息，数据脱敏处理
3. **权限管理**：管理用户权限，确保访问控制到位
4. **威胁检测**：实时监控异常行为，及时发现安全威胁
5. **沙箱管理**：管理积木平台的安全沙箱，隔离不可信代码

## 安全等级

- **公开级（PUBLIC）**：可对外公开的信息
- **内部级（INTERNAL）**：仅限内部使用的信息
- **机密级（CONFIDENTIAL）**：涉及隐私的敏感信息
- **绝密级（TOP_SECRET）**：最高等级的核心机密

## 隐私保护原则

- 最小化原则：只收集必要的信息
- 知情同意：收集信息前必须获得用户同意
- 数据脱敏：展示敏感数据时必须脱敏处理
- 本地优先：敏感数据优先本地处理，不上传云端
- 可删除性：用户有权要求删除自己的数据

## 安全审计范围

- 系统配置安全性
- 第三方依赖漏洞
- 用户权限配置
- 数据加密状态
- 网络访问控制
- 日志完整性

## 工作原则

- 严谨：不放过任何一个安全隐患
- 透明：清楚告知用户安全风险和防护措施
- 可靠：防护措施要稳定有效
- 及时：发现威胁第一时间响应
- 合法：所有安全操作符合法律法规

## 输出风格

- 用中文回答，专业、严谨、清晰
- 安全状态用颜色标识（🟢安全/🟡注意/🔴警告）
- 风险等级明确标注
- 给出具体可操作的安全建议
- 涉及敏感内容用脱敏方式展示
"""

    # ── 支持的命令类型 ───────────────────────────────────────────────────

    _COMMAND_TYPES = [
        "security_audit",       # 安全审计
        "data_masking",         # 数据脱敏
        "privacy_check",        # 隐私检查
        "permission_check",     # 权限检查
        "threat_scan",          # 威胁扫描
        "sandbox_manage",       # 沙箱管理
        "security_config",      # 安全配置
    ]

    def __init__(
        self,
        agent_id: str = "security_manager_01",
        display_name: str = "安全管家",
        config: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> None:
        """初始化安全管家 Agent

        Args:
            agent_id: Agent 唯一标识
            display_name: 显示名称
            config: 配置字典
                - m7_base_url: M7 安全防护服务地址（默认 http://localhost:8007）
                - ollama_base_url: Ollama 服务地址
                - model_name: 推理模型名称（默认 qwen2.5:3b）
                - default_security_level: 默认安全等级（默认 INTERNAL）
                - enable_auto_audit: 是否启用自动审计（默认 True）
                - sandbox_enabled: 是否启用安全沙箱（默认 True）
                - enable_llm_enhance: 是否启用 LLM 增强（默认 True）
                - audit_interval_hours: 自动审计间隔（小时，默认 24）
            **kwargs: 传递给基类的参数
        """
        config = config or {}

        # 默认配置
        config.setdefault("m7_base_url", "http://localhost:8007")
        config.setdefault("ollama_base_url", "http://localhost:11434")
        config.setdefault("model_name", "qwen2.5:3b")
        config.setdefault("default_security_level", "INTERNAL")
        config.setdefault("enable_auto_audit", True)
        config.setdefault("sandbox_enabled", True)
        config.setdefault("enable_llm_enhance", True)
        config.setdefault("audit_interval_hours", 24)
        config.setdefault("temperature", 0.1)
        config.setdefault("max_iterations", 3)

        # 本地模型零成本
        config.setdefault("cost_model", {
            "input_per_1k": 0.0,
            "output_per_1k": 0.0,
            "currency": "CNY",
        })

        super().__init__(agent_id, display_name, config, **kwargs)

        self._http_client: httpx.AsyncClient | None = None
        self._last_audit: dict[str, Any] | None = None

        self._logger = self._logger.bind(
            model=config["model_name"],
            m7_url=config["m7_base_url"],
        )

    # ── 公开接口实现 ────────────────────────────────────────────────────

    async def _invoke_impl(
        self,
        prompt: str,
        system_prompt: str,
        temperature: float,
        max_tokens: int,
        metadata: dict[str, Any],
    ) -> dict[str, Any]:
        """执行安全管理任务

        根据用户意图自动判断是审计、脱敏、权限管理还是威胁检测。
        """
        await self._ensure_http_client()

        # 判断任务类型
        task_type = self._classify_task(prompt, metadata)

        self._logger.info(
            "security_manager_task_classified",
            task_type=task_type,
            prompt_length=len(prompt),
        )

        total_input_tokens = 0
        total_output_tokens = 0

        if task_type == "audit":
            # 安全审计
            result, in_tok, out_tok = await self._do_audit(prompt, metadata)
            total_input_tokens += in_tok
            total_output_tokens += out_tok
            output_text = result
            tools_used = [{"tool": "m7_security_audit", "type": "audit"}]

        elif task_type == "masking":
            # 数据脱敏
            result, in_tok, out_tok = await self._do_masking(prompt, metadata)
            total_input_tokens += in_tok
            total_output_tokens += out_tok
            output_text = result
            tools_used = [{"tool": "m7_data_masking", "type": "masking"}]

        elif task_type == "privacy":
            # 隐私检查
            result, in_tok, out_tok = await self._do_privacy_check(prompt, metadata)
            total_input_tokens += in_tok
            total_output_tokens += out_tok
            output_text = result
            tools_used = [{"tool": "m7_privacy_check", "type": "privacy"}]

        elif task_type == "permission":
            # 权限检查
            result, in_tok, out_tok = await self._do_permission_check(prompt, metadata)
            total_input_tokens += in_tok
            total_output_tokens += out_tok
            output_text = result
            tools_used = [{"tool": "m7_permission_check", "type": "permission"}]

        elif task_type == "threat":
            # 威胁扫描
            result, in_tok, out_tok = await self._do_threat_scan(prompt, metadata)
            total_input_tokens += in_tok
            total_output_tokens += out_tok
            output_text = result
            tools_used = [{"tool": "m7_threat_scan", "type": "threat"}]

        elif task_type == "sandbox":
            # 沙箱管理
            result, in_tok, out_tok = await self._do_sandbox(prompt, metadata)
            total_input_tokens += in_tok
            total_output_tokens += out_tok
            output_text = result
            tools_used = [{"tool": "m7_sandbox", "type": "sandbox"}]

        elif task_type == "config":
            # 安全配置
            result, in_tok, out_tok = await self._do_security_config(prompt, metadata)
            total_input_tokens += in_tok
            total_output_tokens += out_tok
            output_text = result
            tools_used = [{"tool": "m7_security_config", "type": "config"}]

        else:
            # 默认：安全审计
            try:
                result, in_tok, out_tok = await self._do_audit(prompt, metadata)
                total_input_tokens += in_tok
                total_output_tokens += out_tok
                output_text = result
                tools_used = [{"tool": "m7_security_audit", "type": "audit"}]
            except Exception:
                # M7 不可用时，直接用 LLM 回答
                output_text, in_tok, out_tok = await self._call_ollama(
                    messages=[
                        {"role": "system", "content": self._SYSTEM_PROMPT},
                        {"role": "user", "content": prompt},
                    ],
                    temperature=temperature,
                    max_tokens=max_tokens,
                )
                total_input_tokens += in_tok
                total_output_tokens += out_tok
                tools_used = []

        return {
            "output": output_text,
            "input_tokens": total_input_tokens,
            "output_tokens": total_output_tokens,
            "model": self._config["model_name"],
            "task_type": task_type,
            "tools_used": tools_used,
            "local": True,
            "security_system": "security_manager_v1.0",
        }

    async def _health_check_impl(self) -> dict[str, Any]:
        """健康检查

        检查 M7 安全防护服务 + Ollama 模型 + 沙箱状态
        """
        health_issues: list[str] = []
        m7_ok = False
        ollama_ok = False
        sandbox_ok = None  # None 表示未启用

        try:
            await self._ensure_http_client()
            assert self._http_client is not None

            # 检查 M7 服务（M8 标准 health 接口）
            m7_url = self._config["m7_base_url"].rstrip("/")
            try:
                response = await self._http_client.get(
                    f"{m7_url}/health",
                    timeout=5.0,
                )
                if response.status_code == 200:
                    m7_ok = True
                else:
                    health_issues.append(f"M7 服务异常 (HTTP {response.status_code})")
            except httpx.ConnectError as exc:
                health_issues.append(f"M7 服务不可达: {exc}")
            except Exception as exc:
                health_issues.append(f"M7 健康检查异常: {exc}")

            # 检查 Ollama 模型
            if self._config.get("enable_llm_enhance", True):
                ollama_url = self._config["ollama_base_url"].rstrip("/")
                try:
                    response = await self._http_client.get(
                        f"{ollama_url}/api/tags",
                        timeout=5.0,
                    )
                    if response.status_code == 200:
                        data = response.json()
                        models = [m.get("name", "") for m in data.get("models", [])]
                        if self._config["model_name"] in models:
                            ollama_ok = True
                        else:
                            health_issues.append(
                                f"模型 '{self._config['model_name']}' 未安装"
                            )
                    else:
                        health_issues.append("Ollama 服务异常")
                except Exception as exc:
                    health_issues.append(f"Ollama 检查异常: {exc}")

            # 检查安全沙箱（如果启用）
            if self._config.get("sandbox_enabled", True):
                try:
                    response = await self._http_client.get(
                        f"{m7_url}/api/v1/sandbox/status",
                        timeout=5.0,
                    )
                    if response.status_code == 200:
                        data = response.json()
                        sandbox_ok = data.get("result", {}).get(
                            "available", data.get("available", False)
                        )
                        if not sandbox_ok:
                            health_issues.append("安全沙箱不可用")
                    else:
                        health_issues.append("安全沙箱服务异常")
                except Exception as exc:
                    health_issues.append(f"安全沙箱检查异常: {exc}")

        except Exception as exc:
            health_issues.append(f"健康检查异常: {exc}")

        if health_issues:
            return {
                "healthy": False,
                "message": "; ".join(health_issues),
            }

        status_parts = []
        if m7_ok:
            status_parts.append("M7安全防护服务正常")
        if ollama_ok:
            status_parts.append(f"模型 {self._config['model_name']} 就绪")
        if sandbox_ok is True:
            status_parts.append("安全沙箱运行正常")

        return {
            "healthy": True,
            "message": f"安全管家运行正常（{'，'.join(status_parts)}）",
        }

    def calculate_cost(self, input_tokens: int, output_tokens: int) -> float:
        """计算费用（本地模型免费）"""
        return 0.0

    # ── 任务分类 ────────────────────────────────────────────────────────

    def _classify_task(self, prompt: str, metadata: dict[str, Any]) -> str:
        """分类用户请求的任务类型

        Returns: audit / masking / privacy / permission / threat / sandbox / config
        """
        # 优先从 metadata 获取明确的任务类型
        if metadata.get("task_type"):
            return metadata["task_type"]

        prompt_lower = prompt.lower()

        # 数据脱敏类关键词
        masking_keywords = ["脱敏", "mask", "隐藏", "打码", "去敏感",
                            "匿名化", "anonymize", "敏感信息处理"]
        if any(kw in prompt_lower for kw in masking_keywords):
            return "masking"

        # 隐私检查类关键词
        privacy_keywords = ["隐私", "privacy", "个人信息", "数据保护",
                            "隐私等级", "敏感数据"]
        if any(kw in prompt_lower for kw in privacy_keywords):
            return "privacy"

        # 权限类关键词
        permission_keywords = ["权限", "permission", "访问控制", "授权",
                               "角色", "role", "权限检查"]
        if any(kw in prompt_lower for kw in permission_keywords):
            return "permission"

        # 威胁检测类关键词
        threat_keywords = ["威胁", "漏洞", "入侵", "攻击", "threat",
                           "vulnerability", "异常", "检测威胁"]
        if any(kw in prompt_lower for kw in threat_keywords):
            return "threat"

        # 沙箱类关键词
        sandbox_keywords = ["沙箱", "sandbox", "积木", "安全沙箱",
                            "隔离", "代码沙箱"]
        if any(kw in prompt_lower for kw in sandbox_keywords):
            return "sandbox"

        # 安全配置类关键词
        config_keywords = ["安全配置", "安全设置", "security config",
                           "修改安全", "安全策略"]
        if any(kw in prompt_lower for kw in config_keywords):
            return "config"

        # 安全审计类关键词
        audit_keywords = ["审计", "audit", "安全检查", "安全扫描",
                          "风险评估", "安全审计", "扫描"]
        if any(kw in prompt_lower for kw in audit_keywords):
            return "audit"

        # 默认：安全审计
        return "audit"

    # ── 安全审计 ────────────────────────────────────────────────────────

    async def _do_audit(
        self,
        prompt: str,
        metadata: dict[str, Any],
    ) -> tuple[str, int, int]:
        """执行安全审计

        Returns: (回答文本, 输入tokens, 输出tokens)
        """
        assert self._http_client is not None

        m7_url = self._config["m7_base_url"].rstrip("/")
        audit_scope = metadata.get("audit_scope", "full")

        try:
            # 调用 M7 安全审计接口
            payload = {
                "scope": audit_scope,
                "include_vuln_scan": metadata.get("include_vuln_scan", True),
                "include_permission_check": metadata.get("include_permission_check", True),
            }
            response = await self._http_client.post(
                f"{m7_url}/api/v1/audit/run",
                json=payload,
                timeout=15.0,
            )

            if response.status_code != 200:
                raise RuntimeError(f"M7 security audit failed: HTTP {response.status_code}")

            data = response.json()
            result = data.get("result", data)
            self._last_audit = result

        except Exception as exc:
            self._logger.warning("security_audit_failed", error=str(exc))
            return await self._llm_audit(prompt)

        # 格式化审计结果
        answer = self._format_audit_report(result)

        return answer, len(prompt) // 4, len(answer) // 4

    def _format_audit_report(self, result: dict[str, Any]) -> str:
        """格式化安全审计报告"""
        overall_score = result.get("security_score", result.get("score", 0))
        overall_level = result.get("overall_level", "unknown")

        # 安全等级映射
        level_icon = {
            "excellent": "🟢",
            "good": "🟢",
            "fair": "🟡",
            "poor": "🔴",
            "critical": "🔴",
        }
        icon = level_icon.get(overall_level, "❓")

        lines = []
        lines.append("🛡️  安全审计报告")
        lines.append("=" * 45)
        lines.append("")
        lines.append(f"   综合评分: {overall_score}/100")
        lines.append(f"   安全等级: {icon} {overall_level.upper()}")
        lines.append("")

        # 各维度得分
        dimensions = result.get("dimensions", result.get("categories", {}))
        if dimensions:
            lines.append("📊 各维度得分：")
            for dim, info in dimensions.items():
                if isinstance(info, dict):
                    score = info.get("score", 0)
                    status = info.get("status", "")
                else:
                    score = info
                    status = ""
                bar_length = int(score / 10)
                bar = "█" * bar_length + "░" * (10 - bar_length)
                dim_cn = self._translate_dimension(dim)
                lines.append(f"   {dim_cn}: {bar} {score}/100 {status}")
            lines.append("")

        # 发现的问题
        findings = result.get("findings", result.get("issues", []))
        if findings:
            critical_count = sum(1 for f in findings if f.get("severity") == "critical")
            high_count = sum(1 for f in findings if f.get("severity") == "high")
            medium_count = sum(1 for f in findings if f.get("severity") == "medium")
            low_count = sum(1 for f in findings if f.get("severity") == "low")

            lines.append(f"⚠️  发现问题：共 {len(findings)} 项")
            if critical_count:
                lines.append(f"   🔴 严重: {critical_count}")
            if high_count:
                lines.append(f"   🟠 高危: {high_count}")
            if medium_count:
                lines.append(f"   🟡 中危: {medium_count}")
            if low_count:
                lines.append(f"   🟢 低危: {low_count}")
            lines.append("")

            # 显示前 5 个问题
            lines.append("📋 详细问题：")
            for i, finding in enumerate(findings[:5], 1):
                severity = finding.get("severity", "unknown")
                sev_icon = {
                    "critical": "🔴",
                    "high": "🟠",
                    "medium": "🟡",
                    "low": "🟢",
                }.get(severity, "❓")
                title = finding.get("title", finding.get("description", "未知问题"))
                lines.append(f"   {i}. {sev_icon} [{severity.upper()}] {title[:60]}")

            if len(findings) > 5:
                lines.append(f"   ... 还有 {len(findings) - 5} 项")
            lines.append("")

        # 建议
        recommendations = result.get("recommendations", [])
        if recommendations:
            lines.append("💡 安全建议：")
            for i, rec in enumerate(recommendations[:5], 1):
                lines.append(f"   {i}. {rec[:80]}")
            lines.append("")

        lines.append("-" * 45)
        if overall_score >= 80:
            lines.append("✅ 系统整体安全状况良好。")
        elif overall_score >= 60:
            lines.append("⚠️  系统存在一些安全问题，建议及时修复。")
        else:
            lines.append("🔴 系统存在严重安全风险，请立即处理！")

        return "\n".join(lines)

    def _translate_dimension(self, dim: str) -> str:
        """翻译维度名称"""
        translations = {
            "authentication": "认证安全",
            "authorization": "授权安全",
            "data_protection": "数据保护",
            "network_security": "网络安全",
            "system_config": "系统配置",
            "dependency": "依赖安全",
            "privacy": "隐私保护",
            "audit_log": "审计日志",
        }
        return translations.get(dim, dim)

    async def _llm_audit(self, prompt: str) -> tuple[str, int, int]:
        """用 LLM 进行安全建议（降级路径）"""
        answer, in_tok, out_tok = await self._call_ollama(
            messages=[
                {"role": "system", "content": self._SYSTEM_PROMPT},
                {"role": "user", "content": (
                    f"用户请求安全审计：{prompt}\n\n"
                    "请给出通用的安全建议和注意事项。"
                )},
            ],
            temperature=self._config.get("temperature", 0.1),
            max_tokens=500,
        )
        return f"🛡️  安全建议\n\n{answer}", in_tok, out_tok

    # ── 数据脱敏 ────────────────────────────────────────────────────────

    async def _do_masking(
        self,
        prompt: str,
        metadata: dict[str, Any],
    ) -> tuple[str, int, int]:
        """数据脱敏处理"""
        assert self._http_client is not None

        m7_url = self._config["m7_base_url"].rstrip("/")
        content = metadata.get("content", prompt)
        mask_level = metadata.get("mask_level", "medium")

        try:
            payload = {
                "text": content,
                "mask_level": mask_level,
                "types": metadata.get("mask_types", ["phone", "email", "id_card", "name"]),
            }
            response = await self._http_client.post(
                f"{m7_url}/api/v1/privacy/mask",
                json=payload,
                timeout=10.0,
            )

            if response.status_code != 200:
                raise RuntimeError(f"M7 data masking failed: HTTP {response.status_code}")

            data = response.json()
            result = data.get("result", data)
            masked_text = result.get("masked_text", result.get("text", ""))
            masked_items = result.get("masked_items", [])

        except Exception as exc:
            self._logger.warning("data_masking_failed", error=str(exc))
            return await self._llm_mask(content)

        answer = "🔒 数据脱敏结果\n\n"
        answer += "处理后的文本：\n"
        answer += "---\n"
        answer += masked_text
        answer += "\n---\n\n"

        if masked_items:
            answer += f"已脱敏 {len(masked_items)} 处敏感信息：\n"
            for item in masked_items[:10]:
                if isinstance(item, dict):
                    itype = item.get("type", "unknown")
                    answer += f"  • {itype}: {item.get('original', '***')} → {item.get('masked', '***')}\n"
                else:
                    answer += f"  • {item}\n"
            answer += "\n"

        answer += "💡 敏感信息已安全处理。"

        return answer, len(prompt) // 4, len(answer) // 4

    async def _llm_mask(self, content: str) -> tuple[str, int, int]:
        """用 LLM 进行脱敏（降级路径）"""
        answer, in_tok, out_tok = await self._call_ollama(
            messages=[
                {"role": "system", "content": (
                    "你是数据脱敏助手。请识别文本中的敏感信息并进行脱敏处理。\n"
                    "敏感信息包括：手机号、邮箱、身份证号、姓名、地址、银行卡号等。\n"
                    "脱敏方式：手机号保留前3后4位，邮箱保留首字母，姓名保留姓氏等。\n"
                    "请输出脱敏后的文本。"
                )},
                {"role": "user", "content": content},
            ],
            temperature=0.1,
            max_tokens=500,
        )
        return f"🔒 数据脱敏结果\n\n{answer}", in_tok, out_tok

    # ── 隐私检查 ────────────────────────────────────────────────────────

    async def _do_privacy_check(
        self,
        prompt: str,
        metadata: dict[str, Any],
    ) -> tuple[str, int, int]:
        """隐私等级检查"""
        assert self._http_client is not None

        m7_url = self._config["m7_base_url"].rstrip("/")
        content = metadata.get("content", prompt)

        try:
            payload = {"text": content}
            response = await self._http_client.post(
                f"{m7_url}/api/v1/privacy/classify",
                json=payload,
                timeout=5.0,
            )

            if response.status_code != 200:
                raise RuntimeError(f"M7 privacy classify failed: HTTP {response.status_code}")

            data = response.json()
            result = data.get("result", data)
            privacy_level = result.get("privacy_level", result.get("level", "UNKNOWN"))
            reasons = result.get("reasons", [])
            sensitive_items = result.get("sensitive_items", [])

        except Exception as exc:
            self._logger.warning("privacy_check_failed", error=str(exc))
            return f"⚠️  隐私检查失败：{exc}", len(prompt) // 4, 0

        level_colors = {
            "PUBLIC": "🟢",
            "INTERNAL": "🔵",
            "CONFIDENTIAL": "🟡",
            "TOP_SECRET": "🔴",
        }
        icon = level_colors.get(privacy_level, "❓")

        answer = "🔐 隐私等级评估\n\n"
        answer += f"   等级: {icon} {privacy_level}\n\n"

        if reasons:
            answer += "📋 判定依据：\n"
            for reason in reasons:
                answer += f"  • {reason}\n"
            answer += "\n"

        if sensitive_items:
            answer += f"⚠️  检测到 {len(sensitive_items)} 处敏感信息\n"

        answer += "\n💡 根据隐私等级采取相应的保护措施。"

        return answer, len(prompt) // 4, len(answer) // 4

    # ── 权限检查 ────────────────────────────────────────────────────────

    async def _do_permission_check(
        self,
        prompt: str,
        metadata: dict[str, Any],
    ) -> tuple[str, int, int]:
        """权限检查"""
        assert self._http_client is not None

        m7_url = self._config["m7_base_url"].rstrip("/")
        user_id = metadata.get("user_id", "default")
        resource = metadata.get("resource", "")
        action = metadata.get("action", "read")

        try:
            payload = {
                "user_id": user_id,
                "resource": resource,
                "action": action,
            }
            response = await self._http_client.post(
                f"{m7_url}/api/v1/permissions/check",
                json=payload,
                timeout=5.0,
            )

            if response.status_code != 200:
                raise RuntimeError(f"M7 permission check failed: HTTP {response.status_code}")

            data = response.json()
            result = data.get("result", data)
            allowed = result.get("allowed", False)
            roles = result.get("roles", [])

        except Exception as exc:
            self._logger.warning("permission_check_failed", error=str(exc))
            return f"⚠️  权限检查失败：{exc}", len(prompt) // 4, 0

        if allowed:
            status_icon = "✅"
            status_text = "有权限"
        else:
            status_icon = "🚫"
            status_text = "无权限"

        answer = "🔑 权限检查结果\n\n"
        answer += f"   用户: {user_id}\n"
        answer += f"   资源: {resource or '未指定'}\n"
        answer += f"   操作: {action}\n"
        answer += f"   结果: {status_icon} {status_text}\n\n"

        if roles:
            answer += f"🎭 用户角色: {', '.join(roles)}\n"

        return answer, len(prompt) // 4, len(answer) // 4

    # ── 威胁扫描 ────────────────────────────────────────────────────────

    async def _do_threat_scan(
        self,
        prompt: str,
        metadata: dict[str, Any],
    ) -> tuple[str, int, int]:
        """威胁扫描"""
        assert self._http_client is not None

        m7_url = self._config["m7_base_url"].rstrip("/")
        scan_type = metadata.get("scan_type", "quick")

        try:
            payload = {"type": scan_type, "target": metadata.get("target", "system")}
            response = await self._http_client.post(
                f"{m7_url}/api/v1/threat/scan",
                json=payload,
                timeout=15.0,
            )

            if response.status_code != 200:
                raise RuntimeError(f"M7 threat scan failed: HTTP {response.status_code}")

            data = response.json()
            result = data.get("result", data)
            threats = result.get("threats", [])
            scan_summary = result.get("summary", {})

        except Exception as exc:
            self._logger.warning("threat_scan_failed", error=str(exc))
            return f"⚠️  威胁扫描失败：{exc}", len(prompt) // 4, 0

        threat_count = len(threats)

        answer = "⚠️  威胁扫描结果\n\n"

        if threat_count == 0:
            answer += "✅ 未发现安全威胁\n"
        else:
            answer += f"🚨 发现 {threat_count} 个潜在威胁\n\n"
            for i, threat in enumerate(threats[:10], 1):
                if isinstance(threat, dict):
                    name = threat.get("name", threat.get("type", f"威胁{i}"))
                    severity = threat.get("severity", "unknown")
                    sev_icon = {
                        "critical": "🔴",
                        "high": "🟠",
                        "medium": "🟡",
                        "low": "🟢",
                    }.get(severity, "❓")
                    answer += f"   {i}. {sev_icon} {name} [{severity}]\n"
                else:
                    answer += f"   {i}. {threat}\n"

        if scan_summary:
            answer += f"\n📊 扫描摘要：\n"
            for key, value in scan_summary.items():
                answer += f"   {key}: {value}\n"

        answer += "\n💡 建议定期进行威胁扫描，保持系统安全。"

        return answer, len(prompt) // 4, len(answer) // 4

    # ── 沙箱管理 ────────────────────────────────────────────────────────

    async def _do_sandbox(
        self,
        prompt: str,
        metadata: dict[str, Any],
    ) -> tuple[str, int, int]:
        """积木平台安全沙箱管理"""
        assert self._http_client is not None

        m7_url = self._config["m7_base_url"].rstrip("/")
        action = metadata.get("sandbox_action", "status")

        try:
            if action == "status":
                response = await self._http_client.get(
                    f"{m7_url}/api/v1/sandbox/status",
                    timeout=5.0,
                )
            elif action == "create":
                response = await self._http_client.post(
                    f"{m7_url}/api/v1/sandbox/create",
                    json=metadata.get("sandbox_config", {}),
                    timeout=10.0,
                )
            elif action == "destroy":
                sandbox_id = metadata.get("sandbox_id", "")
                response = await self._http_client.post(
                    f"{m7_url}/api/v1/sandbox/destroy",
                    json={"sandbox_id": sandbox_id},
                    timeout=5.0,
                )
            else:
                return (
                    f"ℹ️  沙箱操作 '{action}' 暂不支持。\n"
                    "支持的操作: status / create / destroy"
                ), len(prompt) // 4, 0

            if response.status_code != 200:
                raise RuntimeError(f"M7 sandbox {action} failed: HTTP {response.status_code}")

            data = response.json()
            sandbox_info = data.get("result", data)

        except Exception as exc:
            self._logger.warning("sandbox_manage_failed", error=str(exc))
            return f"⚠️  沙箱操作失败：{exc}", len(prompt) // 4, 0

        status = sandbox_info.get("status", "unknown")
        sandbox_id = sandbox_info.get("sandbox_id", sandbox_info.get("id", "?"))
        isolation_level = sandbox_info.get("isolation_level", "default")

        answer = "🧱 积木安全沙箱\n\n"
        answer += f"🆔 沙箱ID: {sandbox_id}\n"
        answer += f"📊 状态: {status}\n"
        answer += f"🔒 隔离等级: {isolation_level}\n"

        resources = sandbox_info.get("resources", {})
        if resources:
            answer += f"💻 资源限制:\n"
            answer += f"   CPU: {resources.get('cpu', '?')}\n"
            answer += f"   内存: {resources.get('memory', '?')}\n"
            answer += f"   网络: {'允许' if resources.get('network', False) else '禁止'}\n"

        answer += "\n💡 所有不可信代码都应在安全沙箱中运行。"

        return answer, len(prompt) // 4, len(answer) // 4

    # ── 安全配置 ────────────────────────────────────────────────────────

    async def _do_security_config(
        self,
        prompt: str,
        metadata: dict[str, Any],
    ) -> tuple[str, int, int]:
        """安全配置管理"""
        assert self._http_client is not None

        m7_url = self._config["m7_base_url"].rstrip("/")

        # 从 metadata 获取配置更新
        config_updates = metadata.get("security_config", {})

        if config_updates:
            # 更新配置
            try:
                response = await self._http_client.post(
                    f"{m7_url}/api/v1/security/config",
                    json={"config": config_updates},
                    timeout=5.0,
                )

                if response.status_code == 200:
                    answer = "✅ 安全配置已更新\n\n"
                    for key, value in config_updates.items():
                        answer += f"   • {key}: {value}\n"
                    return answer, len(prompt) // 4, len(answer) // 4

            except Exception as exc:
                self._logger.warning("security_config_update_failed", error=str(exc))

        # 查询当前配置
        try:
            response = await self._http_client.get(
                f"{m7_url}/api/v1/security/config",
                timeout=5.0,
            )

            if response.status_code == 200:
                data = response.json()
                config = data.get("result", {}).get("config", data.get("config", {}))

                answer = "⚙️  安全配置\n\n"
                if isinstance(config, dict):
                    for key, value in config.items():
                        answer += f"   • {key}: {value}\n"
                answer += "\n💡 通过 metadata.security_config 传入配置项进行修改。"
                return answer, len(prompt) // 4, len(answer) // 4

        except Exception as exc:
            self._logger.warning("security_config_get_failed", error=str(exc))

        # 默认配置展示
        answer = "⚙️  安全配置\n\n"
        answer += f"   • 默认安全等级: {self._config['default_security_level']}\n"
        answer += f"   • 自动审计: {'启用' if self._config.get('enable_auto_audit') else '禁用'}\n"
        answer += f"   • 安全沙箱: {'启用' if self._config.get('sandbox_enabled') else '禁用'}\n"
        answer += f"   • 审计间隔: {self._config.get('audit_interval_hours', 24)} 小时\n"

        return answer, len(prompt) // 4, len(answer) // 4

    # ── LLM 辅助回答 ────────────────────────────────────────────────────

    async def _llm_answer(self, prompt: str, prefix: str) -> tuple[str, int, int]:
        """用 LLM 直接回答（降级路径）"""
        answer, in_tok, out_tok = await self._call_ollama(
            messages=[
                {"role": "system", "content": self._SYSTEM_PROMPT},
                {"role": "user", "content": f"{prefix}\n\n用户问题：{prompt}"},
            ],
            temperature=self._config.get("temperature", 0.1),
            max_tokens=500,
        )
        return answer, in_tok, out_tok

    # ── HTTP 客户端 ─────────────────────────────────────────────────────

    async def _ensure_http_client(self) -> None:
        """确保 HTTP 客户端已创建"""
        if self._http_client is None:
            self._http_client = httpx.AsyncClient(
                timeout=self._timeout,
                follow_redirects=True,
            )
            self._logger.debug("security_manager_http_client_created")

    # ── Ollama 调用 ─────────────────────────────────────────────────────

    async def _call_ollama(
        self,
        messages: list[dict[str, str]],
        temperature: float,
        max_tokens: int,
    ) -> tuple[str, int, int]:
        """调用 Ollama 本地模型"""
        assert self._http_client is not None

        if not self._config.get("enable_llm_enhance", True):
            return "", 0, 0

        ollama_base = self._config["ollama_base_url"].rstrip("/")
        model_name = self._config["model_name"]

        payload = {
            "model": model_name,
            "messages": messages,
            "stream": False,
            "options": {
                "temperature": temperature,
                "num_predict": max_tokens,
            },
        }

        try:
            response = await self._http_client.post(
                f"{ollama_base}/api/chat",
                json=payload,
                timeout=self._timeout,
            )
        except httpx.TimeoutException as exc:
            raise TimeoutError(f"Ollama 请求超时: {exc}") from exc

        if response.status_code != 200:
            raise RuntimeError(
                f"Ollama API 调用失败 (HTTP {response.status_code}): {response.text}"
            )

        data = response.json()
        content = data.get("message", {}).get("content", "")
        input_tokens = data.get("prompt_eval_count", 0) or len("".join(m["content"] for m in messages)) // 4
        output_tokens = data.get("eval_count", 0) or len(content) // 4

        return content, input_tokens, output_tokens

    # ── 资源清理 ────────────────────────────────────────────────────────

    async def close(self) -> None:
        """关闭 HTTP 客户端"""
        if self._http_client is not None:
            await self._http_client.aclose()
            self._http_client = None
