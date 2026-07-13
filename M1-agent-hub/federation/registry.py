"""
外部 Agent 注册表 — ExternalAgentRegistry

管理所有外部 Agent 的注册、能力画像存储、健康检查和版本管理。

[V11.1 改进]
- API Key 使用 Fernet 对称加密存储，内存中无明文
- get_api_key 增加调用者鉴权，仅受信任组件可读取明文
- 日志中 API Key 自动脱敏
- 支持主密钥轮换
- 新增 license 字段与 GPL 协议风险提示
"""

from __future__ import annotations

import time
import uuid
from typing import Any

import structlog

from shared_models import (
    ExternalAgentProfile,
    ExternalAgentType,
    AgentPrivacyLevel,
    ConnectionType,
    CostModel,
    LicenseType,
)
from federation.crypto_utils import get_crypto_manager, mask_api_key

logger = structlog.get_logger(__name__)


# GPL 类传染性协议列表
GPL_LIKE_LICENSES = {"GPL-2.0", "GPL-3.0", "AGPL", "LGPL"}


class ExternalAgentRegistry:
    """外部 Agent 注册表

    职责：
    - 外部 Agent 的 CRUD 管理
    - 能力画像存储
    - 健康检查调度
    - API Key 加密存储（Fernet 对称加密）
    - 协议合规检查（GPL 风险提示）
    """

    def __init__(self) -> None:
        self._agents: dict[str, ExternalAgentProfile] = {}
        self._api_keys_encrypted: dict[str, str] = {}  # agent_id -> 加密后的 API Key
        self._adapters: dict[str, Any] = {}  # agent_id -> adapter 实例
        self._crypto = get_crypto_manager()
        self._logger = logger.bind(component="external_agent_registry")
        # 初始化时注册默认本地模型
        self._register_default_local()

    # ── CRUD ──────────────────────────────────────────────

    def register_agent(
        self,
        display_name: str,
        provider: str,
        agent_type: ExternalAgentType = ExternalAgentType.LLM,
        capabilities: list[str] | None = None,
        cost_model: dict[str, Any] | None = None,
        privacy_level: AgentPrivacyLevel = AgentPrivacyLevel.STANDARD,
        connection_type: ConnectionType = ConnectionType.API_KEY,
        config: dict[str, Any] | None = None,
        api_key: str = "",
        license: str | LicenseType = LicenseType.OTHER,
        confirm_license_risk: bool = False,
        agent_id: str | None = None,
    ) -> ExternalAgentProfile:
        """注册外部 Agent

        [V11.2] 支持幂等注册：如果指定 ``agent_id`` 且已存在，
        则执行更新操作而非创建新实例，保证重复注册无副作用。

        Args:
            display_name: 显示名称
            provider: 服务商
            agent_type: Agent 类型
            capabilities: 能力标签列表
            cost_model: 成本模型
            privacy_level: 隐私等级
            connection_type: 连接类型
            config: 连接配置（不含密钥）
            api_key: API Key（加密存储，不写入 profile）
            license: 协议许可证类型
            confirm_license_risk: 是否确认 GPL 等协议风险（GPL 类协议必须为 True 才能注册）
            agent_id: [V11.2] 可选的 Agent ID。若指定且已存在则执行更新（幂等），
                若未指定则自动生成。

        Returns:
            注册后的 AgentProfile

        Raises:
            ValueError: GPL 类协议未确认风险
        """
        # 协议类型处理
        if isinstance(license, str):
            try:
                license_enum = LicenseType(license)
            except ValueError:
                license_enum = LicenseType.OTHER
        else:
            license_enum = license

        # GPL 类协议风险检查
        license_warning = ""
        if license_enum.value in GPL_LIKE_LICENSES:
            license_warning = (
                f"警告：{license_enum.value} 协议具有传染性，"
                "接入后可能影响您的代码开源义务。"
            )
            if not confirm_license_risk:
                raise ValueError(
                    f"{license_warning} 注册 GPL 类协议的 Agent 必须设置 confirm_license_risk=True 确认风险。"
                )

        # [V11.2] 幂等注册：如果指定了 agent_id 且已存在，则执行更新
        if agent_id is not None and agent_id in self._agents:
            existing = self._agents[agent_id]
            # 更新已有 Agent 的字段
            existing.display_name = display_name
            existing.provider = provider
            existing.agent_type = agent_type
            existing.capabilities = capabilities or []
            if cost_model:
                existing.cost_model = CostModel(**cost_model)
            existing.privacy_level = privacy_level
            existing.connection_type = connection_type
            existing.config = config or {}
            existing.license = license_enum
            existing.updated_at = time.time()
            # API Key 如有更新则重新加密
            if api_key:
                encrypted = self._crypto.encrypt(api_key)
                self._api_keys_encrypted[agent_id] = encrypted

            self._logger.info(
                "agent_registered_idempotent",
                agent_id=agent_id,
                display_name=display_name,
                provider=provider,
                agent_type=agent_type.value,
                license=license_enum.value,
                has_api_key=bool(api_key or agent_id in self._api_keys_encrypted),
                license_warning=bool(license_warning),
            )
            return existing

        # 未指定 agent_id 或指定但不存在，走新建流程
        if agent_id is not None:
            final_agent_id = agent_id
        else:
            final_agent_id = f"ext_{provider.lower()}_{uuid.uuid4().hex[:8]}"

        profile = ExternalAgentProfile(
            agent_id=final_agent_id,
            display_name=display_name,
            provider=provider,
            agent_type=agent_type,
            capabilities=capabilities or [],
            cost_model=CostModel(**(cost_model or {})),
            privacy_level=privacy_level,
            connection_type=connection_type,
            config=config or {},
            status="active",
            license=license_enum,
        )

        self._agents[final_agent_id] = profile

        # API Key 加密存储
        if api_key:
            encrypted = self._crypto.encrypt(api_key)
            self._api_keys_encrypted[final_agent_id] = encrypted

        self._logger.info(
            "agent_registered",
            agent_id=final_agent_id,
            display_name=display_name,
            provider=provider,
            agent_type=agent_type.value,
            license=license_enum.value,
            has_api_key=bool(api_key),
            license_warning=bool(license_warning),
        )

        return profile

    def get_agent(self, agent_id: str) -> ExternalAgentProfile | None:
        """获取单个 Agent 详情"""
        return self._agents.get(agent_id)

    def list_agents(
        self,
        agent_type: ExternalAgentType | None = None,
        status: str | None = None,
    ) -> list[ExternalAgentProfile]:
        """列出所有外部 Agent，支持筛选"""
        result = list(self._agents.values())
        if agent_type:
            result = [a for a in result if a.agent_type == agent_type]
        if status:
            result = [a for a in result if a.status == status]
        return result

    def update_agent(
        self,
        agent_id: str,
        **kwargs: Any,
    ) -> ExternalAgentProfile | None:
        """更新 Agent 配置"""
        agent = self._agents.get(agent_id)
        if not agent:
            return None

        updated_fields = []
        for key, value in kwargs.items():
            if hasattr(agent, key) and key not in ("agent_id", "created_at"):
                setattr(agent, key, value)
                updated_fields.append(key)

        agent.updated_at = time.time()

        self._logger.info(
            "agent_updated",
            agent_id=agent_id,
            updated_fields=updated_fields,
        )

        return agent

    def delete_agent(self, agent_id: str) -> bool:
        """删除外部 Agent"""
        if agent_id not in self._agents:
            return False

        del self._agents[agent_id]
        self._api_keys_encrypted.pop(agent_id, None)
        self._adapters.pop(agent_id, None)

        self._logger.info("agent_deleted", agent_id=agent_id)
        return True

    # ── 别名方法（兼容 API 层命名） ────────────────────

    def unregister_agent(self, agent_id: str) -> bool:
        """注销外部 Agent（delete_agent 的别名）"""
        return self.delete_agent(agent_id)

    def update_status(self, agent_id: str, status: str) -> ExternalAgentProfile | None:
        """更新 Agent 状态（update_agent 的简化版）"""
        return self.update_agent(agent_id, status=status)

    async def check_health(self, agent_id: str) -> dict[str, Any]:
        """检查单个 Agent 健康状态

        Returns:
            包含 healthy, latency_ms, message 的字典
        """
        adapter = self.get_adapter(agent_id)
        if not adapter:
            return {"healthy": False, "latency_ms": 0.0, "message": "Agent not found"}
        result = await adapter.health_check()
        # 更新 profile
        if agent_id in self._agents:
            self._agents[agent_id].last_health_check = time.time()
            self._agents[agent_id].status = (
                "active" if result.get("healthy", False) else "unhealthy"
            )
        return result

    # ── API Key 管理（加密存储） ────────────────────────

    def set_api_key(self, agent_id: str, api_key: str) -> bool:
        """设置 API Key（加密存储，不写入 profile）

        Args:
            agent_id: Agent ID
            api_key: 明文 API Key

        Returns:
            是否设置成功
        """
        if agent_id not in self._agents:
            return False

        encrypted = self._crypto.encrypt(api_key)
        self._api_keys_encrypted[agent_id] = encrypted

        self._logger.info(
            "api_key_set",
            agent_id=agent_id,
            key_preview=mask_api_key(api_key),
        )
        return True

    def get_api_key(self, agent_id: str, caller_id: str = "") -> str:
        """获取 API Key（解密后返回，仅受信任调用者可读取）

        Args:
            agent_id: Agent ID
            caller_id: 调用者标识（用于鉴权和审计）

        Returns:
            解密后的明文 API Key

        Raises:
            PermissionError: 调用者不受信任
        """
        encrypted = self._api_keys_encrypted.get(agent_id, "")
        if not encrypted:
            return ""

        # 受信任内部组件可以直接读取
        if caller_id and self._crypto.is_trusted_caller(caller_id):
            plaintext = self._crypto.decrypt(encrypted, caller_id=caller_id)
            return plaintext

        # 未鉴权的调用：返回脱敏预览（不返回明文）
        # 先解密再脱敏，确保预览准确
        try:
            plaintext = self._crypto.decrypt(encrypted)
            self._logger.warning(
                "api_key_access_unauthorized",
                agent_id=agent_id,
                caller_id=caller_id or "unknown",
                returned_masked=True,
            )
            return mask_api_key(plaintext)
        except Exception:
            return "****"

    def rotate_all_keys(self, new_master_key: str | None = None) -> dict[str, Any]:
        """轮换主密钥并重新加密所有 API Key

        Args:
            new_master_key: 新的主密钥（Fernet 格式），不提供则自动生成

        Returns:
            轮换结果
        """
        # 先解密所有现有 Key
        plain_keys: dict[str, str] = {}
        for agent_id, encrypted in self._api_keys_encrypted.items():
            try:
                plain_keys[agent_id] = self._crypto.decrypt(encrypted)
            except Exception as exc:
                self._logger.error(
                    "key_rotation_decrypt_failed",
                    agent_id=agent_id,
                    error=str(exc),
                )

        # 轮换主密钥
        result = self._crypto.rotate_master_key(new_master_key)

        # 用新密钥重新加密
        success_count = 0
        for agent_id, plaintext in plain_keys.items():
            try:
                self._api_keys_encrypted[agent_id] = self._crypto.encrypt(plaintext)
                success_count += 1
            except Exception as exc:
                self._logger.error(
                    "key_rotation_encrypt_failed",
                    agent_id=agent_id,
                    error=str(exc),
                )

        result["rotated_keys_count"] = success_count
        result["total_keys"] = len(plain_keys)

        self._logger.info(
            "api_keys_rotated",
            rotated=success_count,
            total=len(plain_keys),
        )

        return result

    # ── 健康检查 ──────────────────────────────────────────

    async def test_connection(self, agent_id: str) -> dict[str, Any]:
        """测试 Agent 连接"""
        agent = self._agents.get(agent_id)
        if not agent:
            return {"success": False, "message": "Agent 不存在"}

        adapter = self._get_or_create_adapter(agent_id)
        if not adapter:
            return {"success": False, "message": "无法创建适配器"}

        result = await adapter.health_check()
        agent.last_health_check = time.time()
        agent.status = "active" if result["healthy"] else "error"

        return {
            "success": result["healthy"],
            "message": result["message"],
            "latency_ms": result.get("latency_ms", 0),
        }

    async def check_all_health(self) -> dict[str, Any]:
        """检查所有 Agent 健康状态"""
        results: dict[str, dict[str, Any]] = {}
        for agent_id in list(self._agents.keys()):
            result = await self.test_connection(agent_id)
            results[agent_id] = result

        healthy_count = sum(1 for r in results.values() if r["success"])
        return {
            "total": len(results),
            "healthy": healthy_count,
            "unhealthy": len(results) - healthy_count,
            "details": results,
        }

    # ── 适配器管理 ────────────────────────────────────────

    def _get_or_create_adapter(self, agent_id: str) -> Any | None:
        """获取或创建适配器实例"""
        if agent_id in self._adapters:
            return self._adapters[agent_id]

        agent = self._agents.get(agent_id)
        if not agent:
            return None

        # 解密 API Key（仅受信任的 registry 组件可读取）
        api_key = ""
        if agent_id in self._api_keys_encrypted:
            try:
                api_key = self._crypto.decrypt(
                    self._api_keys_encrypted[agent_id],
                    caller_id="federation.registry",
                )
            except Exception as exc:
                self._logger.error(
                    "api_key_decrypt_failed",
                    agent_id=agent_id,
                    error=str(exc),
                )

        provider_lower = agent.provider.lower()

        adapter = None
        try:
            if "openai" in provider_lower or "gpt" in provider_lower:
                from federation.adapters.openai import OpenAIAdapter
                adapter = OpenAIAdapter(
                    agent_id=agent.agent_id,
                    display_name=agent.display_name,
                    api_key=api_key,
                    config=agent.config,
                )
            elif "anthropic" in provider_lower or "claude" in provider_lower:
                from federation.adapters.anthropic import AnthropicAdapter
                adapter = AnthropicAdapter(
                    agent_id=agent.agent_id,
                    display_name=agent.display_name,
                    api_key=api_key,
                    config=agent.config,
                )
            elif "google" in provider_lower or "gemini" in provider_lower:
                from federation.adapters.gemini import GeminiAdapter
                adapter = GeminiAdapter(
                    agent_id=agent.agent_id,
                    display_name=agent.display_name,
                    api_key=api_key,
                    config=agent.config,
                )
            elif "local" in provider_lower:
                from federation.adapters.local_model import LocalModelAdapter
                adapter = LocalModelAdapter(
                    agent_id=agent.agent_id,
                    display_name=agent.display_name,
                    config=agent.config,
                )
        except Exception as exc:
            self._logger.error(
                "adapter_creation_failed",
                agent_id=agent_id,
                provider=agent.provider,
                error=str(exc),
            )
            return None

        if adapter:
            self._adapters[agent_id] = adapter

        return adapter

    def get_adapter(self, agent_id: str) -> Any | None:
        """公开的适配器获取方法"""
        return self._get_or_create_adapter(agent_id)

    # ── 统计 ──────────────────────────────────────────────

    def stats(self) -> dict[str, Any]:
        """注册表统计信息"""
        by_type: dict[str, int] = {}
        by_provider: dict[str, int] = {}
        by_status: dict[str, int] = {}
        by_license: dict[str, int] = {}

        for agent in self._agents.values():
            by_type[agent.agent_type.value] = by_type.get(agent.agent_type.value, 0) + 1
            by_provider[agent.provider] = by_provider.get(agent.provider, 0) + 1
            by_status[agent.status] = by_status.get(agent.status, 0) + 1
            by_license[agent.license.value] = by_license.get(agent.license.value, 0) + 1

        return {
            "total": len(self._agents),
            "by_type": by_type,
            "by_provider": by_provider,
            "by_status": by_status,
            "by_license": by_license,
            "encrypted_keys": len(self._api_keys_encrypted),
            "crypto_available": self._crypto.is_crypto_available,
        }

    # ── 默认本地模型 ──────────────────────────────────────

    def _register_default_local(self) -> None:
        """注册默认的本地模型 Agent（零成本、最高隐私等级）"""
        # 检查是否已注册
        for agent in self._agents.values():
            if agent.provider == "Local":
                return

        profile = ExternalAgentProfile(
            agent_id="ext_local_7b",
            display_name="本地模型 (7B)",
            provider="Local",
            agent_type=ExternalAgentType.LLM,
            capabilities=["text_generation", "local_only", "zero_cost"],
            response_speed="fast",
            quality_rating=3.5,
            cost_model=CostModel(input_per_1k=0.0, output_per_1k=0.0),
            privacy_level=AgentPrivacyLevel.LOCAL_ONLY,
            connection_type=ConnectionType.LOCAL,
            status="active",
            license=LicenseType.MIT,
        )
        self._agents[profile.agent_id] = profile
        self._logger.info("default_local_agent_registered")
