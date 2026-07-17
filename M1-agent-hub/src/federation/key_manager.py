"""
统一 API 密钥管理器 — APIKeyManager

提供多服务商 API 密钥的统一加密存储与管理，基于 CryptoManager (Fernet 加密)。
替代原有的分散式密钥存储（如 codex_keys.enc），统一存储在 ~/.yunxi/agent_keys.enc。

支持的服务商：openai, anthropic, deepseek, moonshot, qwen, custom
- 添加 / 删除 / 更新 / 查询（掩码显示）
- 密钥健康检查（测试连通性）
- 主密钥来源：FEDERATION_MASTER_KEY 环境变量
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

import structlog

from .crypto_utils import get_crypto_manager, mask_api_key

logger = structlog.get_logger(__name__)


# 统一密钥存储文件
KEYS_FILE = Path.home() / ".yunxi" / "agent_keys.enc"

# 受支持的服务商及其默认配置
SUPPORTED_PROVIDERS: dict[str, dict[str, Any]] = {
    "openai": {
        "display_name": "OpenAI",
        "default_base_url": "https://api.openai.com/v1",
        "default_model": "gpt-4o",
        "health_check_endpoint": "/models",
        "auth_header": "Authorization",
        "auth_prefix": "Bearer ",
    },
    "anthropic": {
        "display_name": "Anthropic",
        "default_base_url": "https://api.anthropic.com",
        "default_model": "claude-3-5-sonnet-20240620",
        "health_check_endpoint": "/v1/messages",
        "auth_header": "x-api-key",
        "auth_prefix": "",
    },
    "deepseek": {
        "display_name": "DeepSeek",
        "default_base_url": "https://api.deepseek.com/v1",
        "default_model": "deepseek-coder",
        "health_check_endpoint": "/models",
        "auth_header": "Authorization",
        "auth_prefix": "Bearer ",
    },
    "moonshot": {
        "display_name": "Moonshot (月之暗面)",
        "default_base_url": "https://api.moonshot.cn/v1",
        "default_model": "moonshot-v1-8k",
        "health_check_endpoint": "/models",
        "auth_header": "Authorization",
        "auth_prefix": "Bearer ",
    },
    "qwen": {
        "display_name": "Qwen (通义千问)",
        "default_base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "default_model": "qwen-plus",
        "health_check_endpoint": "/models",
        "auth_header": "Authorization",
        "auth_prefix": "Bearer ",
    },
    "custom": {
        "display_name": "自定义服务商",
        "default_base_url": "https://api.example.com/v1",
        "default_model": "gpt-4o",
        "health_check_endpoint": "/models",
        "auth_header": "Authorization",
        "auth_prefix": "Bearer ",
    },
}


class APIKeyManager:
    """统一 API 密钥管理器

    职责：
    - 多服务商 API 密钥的 CRUD 管理
    - Fernet 加密持久化存储
    - 密钥健康检查（测试 API 连通性）
    - 统一存储，替代分散的 codex_keys.enc 等
    """

    def __init__(self, keys_file: Path | None = None) -> None:
        self._crypto = get_crypto_manager()
        self._keys_file = keys_file or KEYS_FILE
        self._logger = logger.bind(component="api_key_manager")
        # 缓存：{provider: {key: encrypted_key, base_url: ..., model: ..., updated_at: ...}}
        self._cache: dict[str, dict[str, Any]] = {}
        self._load_keys()

    # ── 内部工具：持久化 ────────────────────────────────

    def _ensure_dir(self) -> None:
        """确保密钥存储目录存在"""
        self._keys_file.parent.mkdir(parents=True, exist_ok=True)

    def _load_keys(self) -> None:
        """从加密文件加载密钥到内存缓存"""
        if not self._keys_file.exists():
            self._cache = {}
            return

        try:
            encrypted_data = self._keys_file.read_text(encoding="utf-8")
            decrypted = self._crypto.decrypt(
                encrypted_data, caller_id="federation.key_manager"
            )
            data = json.loads(decrypted)
            # 兼容旧格式（纯 provider -> key 的映射）
            if isinstance(data, dict):
                normalized: dict[str, dict[str, Any]] = {}
                for provider, value in data.items():
                    if isinstance(value, str):
                        # 旧格式：provider -> encrypted_key_string
                        normalized[provider] = {
                            "api_key_encrypted": value,
                            "base_url": SUPPORTED_PROVIDERS.get(
                                provider, SUPPORTED_PROVIDERS["custom"]
                            )["default_base_url"],
                            "model": SUPPORTED_PROVIDERS.get(
                                provider, SUPPORTED_PROVIDERS["custom"]
                            )["default_model"],
                            "updated_at": time.time(),
                        }
                    elif isinstance(value, dict):
                        normalized[provider] = value
                self._cache = normalized
            else:
                self._cache = {}
            self._logger.info(
                "keys_loaded",
                count=len(self._cache),
                providers=list(self._cache.keys()),
            )
        except Exception as exc:
            self._logger.error("keys_load_failed", error=str(exc))
            self._cache = {}

    def _save_keys(self) -> None:
        """将内存缓存加密后持久化到文件"""
        self._ensure_dir()
        try:
            data_str = json.dumps(self._cache, ensure_ascii=False)
            encrypted = self._crypto.encrypt(data_str)
            self._keys_file.write_text(encrypted, encoding="utf-8")
            self._logger.debug(
                "keys_saved",
                count=len(self._cache),
                path=str(self._keys_file),
            )
        except Exception as exc:
            self._logger.error("keys_save_failed", error=str(exc))
            raise

    # ── CRUD 操作 ─────────────────────────────────────

    def add_key(
        self,
        provider: str,
        api_key: str,
        base_url: str = "",
        model: str = "",
    ) -> dict[str, Any]:
        """添加或更新一个服务商的 API 密钥

        Args:
            provider: 服务商名称（openai/anthropic/deepseek/moonshot/qwen/custom）
            api_key: 明文 API Key
            base_url: 自定义 API 基础 URL（可选，使用服务商默认值）
            model: 自定义默认模型（可选，使用服务商默认值）

        Returns:
            操作结果字典
        """
        provider = provider.lower().strip()
        if not api_key:
            return {"success": False, "error": "API Key 不能为空"}

        # 获取服务商配置
        provider_config = SUPPORTED_PROVIDERS.get(
            provider, SUPPORTED_PROVIDERS["custom"]
        )

        # 加密存储
        encrypted_key = self._crypto.encrypt(api_key)

        entry = {
            "api_key_encrypted": encrypted_key,
            "base_url": base_url or provider_config["default_base_url"],
            "model": model or provider_config["default_model"],
            "updated_at": time.time(),
        }

        is_update = provider in self._cache
        self._cache[provider] = entry
        self._save_keys()

        action = "updated" if is_update else "added"
        self._logger.info(
            f"key_{action}",
            provider=provider,
            key_preview=mask_api_key(api_key),
        )

        return {
            "success": True,
            "action": action,
            "provider": provider,
            "display_name": provider_config["display_name"],
            "key_preview": mask_api_key(api_key),
            "base_url": entry["base_url"],
            "model": entry["model"],
        }

    def remove_key(self, provider: str) -> dict[str, Any]:
        """删除指定服务商的 API 密钥

        Args:
            provider: 服务商名称

        Returns:
            操作结果字典
        """
        provider = provider.lower().strip()
        if provider not in self._cache:
            return {"success": False, "error": f"未找到 {provider} 的密钥"}

        del self._cache[provider]
        self._save_keys()

        self._logger.info("key_removed", provider=provider)
        return {"success": True, "provider": provider}

    def get_key(self, provider: str, caller_id: str = "") -> str:
        """获取指定服务商的明文 API Key（仅受信任调用者可读取）

        Args:
            provider: 服务商名称
            caller_id: 调用者标识（用于鉴权和审计）

        Returns:
            明文 API Key，未找到或无权限返回空字符串
        """
        provider = provider.lower().strip()
        entry = self._cache.get(provider)
        if not entry:
            return ""

        encrypted_key = entry.get("api_key_encrypted", "")
        if not encrypted_key:
            return ""

        # 受信任内部组件可以直接读取明文
        if caller_id and self._crypto.is_trusted_caller(caller_id):
            try:
                return self._crypto.decrypt(encrypted_key, caller_id=caller_id)
            except Exception as exc:
                self._logger.error(
                    "key_decrypt_failed",
                    provider=provider,
                    caller=caller_id,
                    error=str(exc),
                )
                return ""

        # 未鉴权调用：返回脱敏预览
        try:
            plaintext = self._crypto.decrypt(encrypted_key)
            self._logger.warning(
                "key_access_unauthorized",
                provider=provider,
                caller=caller_id or "unknown",
                returned_masked=True,
            )
            return mask_api_key(plaintext)
        except Exception:
            return "****"

    def get_key_masked(self, provider: str) -> str:
        """获取指定服务商的掩码密钥（安全的公开查询接口）

        Args:
            provider: 服务商名称

        Returns:
            掩码后的密钥字符串
        """
        provider = provider.lower().strip()
        entry = self._cache.get(provider)
        if not entry:
            return ""

        encrypted_key = entry.get("api_key_encrypted", "")
        if not encrypted_key:
            return ""

        try:
            plaintext = self._crypto.decrypt(encrypted_key)
            return mask_api_key(plaintext)
        except Exception:
            return "****"

    def list_keys(self) -> list[dict[str, Any]]:
        """列出所有已存储的密钥（掩码显示）

        Returns:
            密钥列表，每项包含 provider, display_name, key_preview, base_url, model, updated_at
        """
        result = []
        for provider, entry in sorted(self._cache.items()):
            provider_config = SUPPORTED_PROVIDERS.get(
                provider, SUPPORTED_PROVIDERS["custom"]
            )
            result.append(
                {
                    "provider": provider,
                    "display_name": provider_config["display_name"],
                    "key_preview": self.get_key_masked(provider),
                    "base_url": entry.get("base_url", ""),
                    "model": entry.get("model", ""),
                    "updated_at": entry.get("updated_at", 0),
                    "has_key": bool(entry.get("api_key_encrypted")),
                }
            )
        return result

    def update_key_config(
        self,
        provider: str,
        base_url: str = "",
        model: str = "",
    ) -> dict[str, Any]:
        """更新密钥的配置（base_url / model），不修改密钥本身

        Args:
            provider: 服务商名称
            base_url: 新的 API 基础 URL（可选）
            model: 新的默认模型（可选）

        Returns:
            操作结果字典
        """
        provider = provider.lower().strip()
        entry = self._cache.get(provider)
        if not entry:
            return {"success": False, "error": f"未找到 {provider} 的密钥"}

        if base_url:
            entry["base_url"] = base_url
        if model:
            entry["model"] = model
        entry["updated_at"] = time.time()

        self._cache[provider] = entry
        self._save_keys()

        self._logger.info("key_config_updated", provider=provider)
        return {
            "success": True,
            "provider": provider,
            "base_url": entry["base_url"],
            "model": entry["model"],
        }

    # ── 健康检查 ──────────────────────────────────────

    async def health_check(self, provider: str) -> dict[str, Any]:
        """测试指定服务商 API 密钥的连通性

        Args:
            provider: 服务商名称

        Returns:
            健康检查结果 {healthy, latency_ms, message, provider}
        """
        provider = provider.lower().strip()
        entry = self._cache.get(provider)
        if not entry:
            return {
                "healthy": False,
                "latency_ms": 0.0,
                "message": f"未找到 {provider} 的密钥配置",
                "provider": provider,
            }

        # 获取明文密钥（受信任的 key_manager 组件）
        api_key = self.get_key(provider, caller_id="federation.key_manager")
        if not api_key:
            return {
                "healthy": False,
                "latency_ms": 0.0,
                "message": "密钥解密失败或为空",
                "provider": provider,
            }

        provider_config = SUPPORTED_PROVIDERS.get(
            provider, SUPPORTED_PROVIDERS["custom"]
        )
        base_url = entry.get("base_url", provider_config["default_base_url"])
        endpoint = provider_config["health_check_endpoint"]
        auth_header = provider_config["auth_header"]
        auth_prefix = provider_config["auth_prefix"]

        import httpx

        url = base_url.rstrip("/") + endpoint
        headers = {
            auth_header: f"{auth_prefix}{api_key}",
            "Content-Type": "application/json",
        }

        # Anthropic 特殊处理
        if provider == "anthropic":
            headers["anthropic-version"] = "2023-06-01"

        start_time = time.time()
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                # Anthropic 没有简单的 list models 接口，发一个最小请求
                if provider == "anthropic":
                    response = await client.post(
                        url,
                        headers=headers,
                        json={
                            "model": entry.get("model", provider_config["default_model"]),
                            "max_tokens": 1,
                            "messages": [{"role": "user", "content": "hi"}],
                        },
                    )
                else:
                    response = await client.get(url, headers=headers)

                latency_ms = (time.time() - start_time) * 1000

                if response.status_code == 200:
                    result = {
                        "healthy": True,
                        "latency_ms": round(latency_ms, 2),
                        "message": "连接正常",
                        "provider": provider,
                        "status_code": response.status_code,
                    }
                else:
                    result = {
                        "healthy": False,
                        "latency_ms": round(latency_ms, 2),
                        "message": f"API 返回错误: HTTP {response.status_code}",
                        "provider": provider,
                        "status_code": response.status_code,
                    }
        except httpx.TimeoutException:
            latency_ms = (time.time() - start_time) * 1000
            result = {
                "healthy": False,
                "latency_ms": round(latency_ms, 2),
                "message": "请求超时",
                "provider": provider,
            }
        except Exception as exc:
            latency_ms = (time.time() - start_time) * 1000
            result = {
                "healthy": False,
                "latency_ms": round(latency_ms, 2),
                "message": f"连接失败: {exc}",
                "provider": provider,
            }

        self._logger.info(
            "key_health_check",
            provider=provider,
            healthy=result["healthy"],
            latency_ms=result["latency_ms"],
        )
        return result

    async def health_check_all(self) -> dict[str, Any]:
        """检查所有已配置密钥的健康状态

        Returns:
            汇总结果 {total, healthy, unhealthy, details}
        """
        details: dict[str, dict[str, Any]] = {}
        for provider in self._cache:
            result = await self.health_check(provider)
            details[provider] = result

        healthy_count = sum(1 for r in details.values() if r["healthy"])
        return {
            "total": len(details),
            "healthy": healthy_count,
            "unhealthy": len(details) - healthy_count,
            "details": details,
        }

    # ── 统计与元信息 ───────────────────────────────────

    def stats(self) -> dict[str, Any]:
        """获取密钥管理统计信息

        Returns:
            统计信息字典
        """
        return {
            "total_keys": len(self._cache),
            "providers": list(self._cache.keys()),
            "supported_providers": list(SUPPORTED_PROVIDERS.keys()),
            "crypto_available": self._crypto.is_crypto_available,
            "storage_path": str(self._keys_file),
            "storage_exists": self._keys_file.exists(),
        }

    def get_provider_info(self, provider: str) -> dict[str, Any] | None:
        """获取服务商的元信息（默认配置等）

        Args:
            provider: 服务商名称

        Returns:
            服务商信息字典，不支持的返回 None
        """
        provider = provider.lower().strip()
        config = SUPPORTED_PROVIDERS.get(provider)
        if not config:
            return None
        return {
            "provider": provider,
            "display_name": config["display_name"],
            "default_base_url": config["default_base_url"],
            "default_model": config["default_model"],
            "has_key": provider in self._cache,
        }

    def list_supported_providers(self) -> list[dict[str, Any]]:
        """列出所有支持的服务商及其配置

        Returns:
            服务商列表
        """
        result = []
        for provider, config in SUPPORTED_PROVIDERS.items():
            result.append(
                {
                    "provider": provider,
                    "display_name": config["display_name"],
                    "default_base_url": config["default_base_url"],
                    "default_model": config["default_model"],
                    "has_key": provider in self._cache,
                }
            )
        return result

    # ── 密钥轮换 ──────────────────────────────────────

    def rotate_master_key(self, new_key: str | None = None) -> dict[str, Any]:
        """轮换主密钥并重新加密所有存储的密钥

        Args:
            new_key: 新的主密钥（Fernet 格式），不提供则自动生成

        Returns:
            轮换结果
        """
        # 先解密所有现有密钥
        plain_keys: dict[str, dict[str, Any]] = {}
        for provider, entry in self._cache.items():
            encrypted_key = entry.get("api_key_encrypted", "")
            if encrypted_key:
                try:
                    plaintext = self._crypto.decrypt(encrypted_key)
                    plain_keys[provider] = {
                        "plaintext_key": plaintext,
                        "base_url": entry.get("base_url", ""),
                        "model": entry.get("model", ""),
                    }
                except Exception as exc:
                    self._logger.error(
                        "key_rotation_decrypt_failed",
                        provider=provider,
                        error=str(exc),
                    )

        # 轮换主密钥
        result = self._crypto.rotate_master_key(new_key)

        # 用新密钥重新加密
        success_count = 0
        for provider, data in plain_keys.items():
            try:
                new_encrypted = self._crypto.encrypt(data["plaintext_key"])
                self._cache[provider] = {
                    "api_key_encrypted": new_encrypted,
                    "base_url": data["base_url"],
                    "model": data["model"],
                    "updated_at": time.time(),
                }
                success_count += 1
            except Exception as exc:
                self._logger.error(
                    "key_rotation_encrypt_failed",
                    provider=provider,
                    error=str(exc),
                )

        # 持久化
        self._save_keys()

        result["rotated_keys_count"] = success_count
        result["total_keys"] = len(plain_keys)

        self._logger.info(
            "master_key_rotated",
            rotated=success_count,
            total=len(plain_keys),
        )

        return result


# ── 全局单例 ──────────────────────────────────────────

_key_manager: APIKeyManager | None = None


def get_key_manager() -> APIKeyManager:
    """获取统一密钥管理器单例"""
    global _key_manager
    if _key_manager is None:
        _key_manager = APIKeyManager()
    return _key_manager
