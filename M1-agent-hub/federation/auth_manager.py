"""
联邦调度鉴权模块 — AuthManager

管理 API 访问权限，支持两种鉴权方式：
- Admin API Key 鉴权
- 内部调用 HMAC 签名鉴权
"""

from __future__ import annotations

import os
import hmac
import hashlib
import time
import uuid
from typing import Any

import structlog

logger = structlog.get_logger(__name__)


# 环境变量名
ADMIN_KEY_ENV = "FEDERATION_ADMIN_KEY"

# 权限级别
PERMISSION_READ = "read"
PERMISSION_WRITE = "write"
PERMISSION_ADMIN = "admin"

# 权限包含关系：admin > write > read
PERMISSION_HIERARCHY = {
    PERMISSION_ADMIN: {PERMISSION_ADMIN, PERMISSION_WRITE, PERMISSION_READ},
    PERMISSION_WRITE: {PERMISSION_WRITE, PERMISSION_READ},
    PERMISSION_READ: {PERMISSION_READ},
}

# 接口权限矩阵
ENDPOINT_PERMISSIONS = {
    # Agent 管理
    "POST /federation/agents/register": PERMISSION_ADMIN,
    "DELETE /federation/agents/{agent_id}": PERMISSION_ADMIN,
    "POST /federation/agents/{agent_id}/health-check": PERMISSION_READ,
    "GET /federation/agents": PERMISSION_READ,
    "GET /federation/agents/{agent_id}": PERMISSION_READ,

    # 调度决策
    "POST /federation/decide": PERMISSION_READ,

    # 调用
    "POST /federation/invoke": PERMISSION_WRITE,
    "POST /federation/compare": PERMISSION_WRITE,

    # 隐私
    "POST /federation/privacy/scan": PERMISSION_READ,
    "GET /federation/privacy/audit": PERMISSION_ADMIN,

    # 成本
    "GET /federation/cost/budget": PERMISSION_READ,
    "POST /federation/cost/budget": PERMISSION_ADMIN,
    "GET /federation/cost/records": PERMISSION_READ,
    "GET /federation/cost/daily": PERMISSION_READ,
}


class AuthManager:
    """鉴权管理器

    支持的鉴权方式：
    1. Admin API Key：Authorization: Bearer <admin-key>
    2. 内部调用：X-Internal-Call: true + X-Signature: <hmac-signature>
    """

    def __init__(self) -> None:
        self._admin_key: str = ""
        self._internal_secret: str = ""
        self._audit_log: list[dict[str, Any]] = []
        self._logger = logger.bind(component="auth_manager")
        self._init_keys()

    def _init_keys(self) -> None:
        """初始化密钥"""
        # Admin Key
        admin_key = os.environ.get(ADMIN_KEY_ENV, "")
        if admin_key:
            self._admin_key = admin_key
            self._logger.info("admin_key_loaded_from_env")
        else:
            # 开发模式：自动生成并打印
            self._admin_key = uuid.uuid4().hex + uuid.uuid4().hex
            self._logger.warning(
                "admin_key_auto_generated",
                key_preview=self._admin_key[:8] + "****",
                instruction=(
                    f"请设置环境变量 {ADMIN_KEY_ENV} 以确保安全性。"
                    f"当前生成的 Key 仅用于开发测试。"
                ),
            )

        # 内部调用密钥（用于 HMAC 签名）
        internal_secret = os.environ.get("FEDERATION_INTERNAL_SECRET", "")
        if internal_secret:
            self._internal_secret = internal_secret
        else:
            self._internal_secret = uuid.uuid4().hex + uuid.uuid4().hex
            self._logger.info("internal_secret_auto_generated")

    # ── 鉴权主入口 ────────────────────────────────────

    def authenticate(
        self,
        method: str,
        path: str,
        headers: dict[str, str],
    ) -> tuple[bool, str, str]:
        """鉴权请求

        Args:
            method: HTTP 方法
            path: 请求路径
            headers: 请求头

        Returns:
            (是否通过, 权限级别, 错误信息)
        """
        # 查找需要的权限
        required_perm = self._get_required_permission(method, path)

        # 公共接口（不需要权限）
        if required_perm is None:
            return True, PERMISSION_READ, ""

        # 尝试 Admin Key 鉴权
        auth_header = headers.get("authorization", "")
        if auth_header.startswith("Bearer "):
            token = auth_header[7:]
            if self._verify_admin_key(token):
                self._audit(method, path, "admin_key", True)
                return True, PERMISSION_ADMIN, ""
            else:
                self._audit(method, path, "admin_key", False, "invalid_admin_key")
                return False, "", "Invalid admin API key"

        # 尝试内部调用鉴权
        internal_call = headers.get("x-internal-call", "").lower() == "true"
        signature = headers.get("x-signature", "")
        timestamp = headers.get("x-timestamp", "")
        if internal_call and signature:
            if self._verify_internal_signature(method, path, signature, timestamp):
                self._audit(method, path, "internal_call", True)
                return True, PERMISSION_ADMIN, ""
            else:
                self._audit(method, path, "internal_call", False, "invalid_signature")
                return False, "", "Invalid internal call signature"

        # 没有鉴权信息
        self._audit(method, path, "none", False, "no_credentials")
        return False, "", "Authentication required"

    def check_permission(self, permission_level: str, required_perm: str) -> bool:
        """检查权限级别是否满足要求

        Args:
            permission_level: 当前权限级别
            required_perm: 需要的权限

        Returns:
            是否满足
        """
        if permission_level not in PERMISSION_HIERARCHY:
            return False
        return required_perm in PERMISSION_HIERARCHY[permission_level]

    def _get_required_permission(self, method: str, path: str) -> str | None:
        """获取接口需要的权限级别"""
        # 精确匹配
        key = f"{method.upper()} {path}"
        if key in ENDPOINT_PERMISSIONS:
            return ENDPOINT_PERMISSIONS[key]

        # 带路径参数的匹配（简化：替换 {xxx} 为通配）
        import re
        for endpoint_key, perm in ENDPOINT_PERMISSIONS.items():
            # 将 {param} 替换为正则匹配
            pattern = re.escape(endpoint_key).replace(r"\{", "(?P<").replace(r"\}", r">[^/]+)")
            if re.fullmatch(pattern, key):
                return perm

        # 默认：GET 类读权限，其他写权限（安全起见，未知接口给 admin）
        return PERMISSION_ADMIN

    # ── Admin Key 验证 ────────────────────────────────

    def _verify_admin_key(self, key: str) -> bool:
        """验证 Admin API Key"""
        if not self._admin_key or not key:
            return False
        # 用 hmac.compare_digest 防时序攻击
        return hmac.compare_digest(key, self._admin_key)

    # ── 内部调用签名验证 ──────────────────────────────

    def _verify_internal_signature(
        self,
        method: str,
        path: str,
        signature: str,
        timestamp: str,
    ) -> bool:
        """验证内部调用 HMAC 签名

        签名格式：HMAC-SHA256(secret, method + path + timestamp)
        """
        if not self._internal_secret or not signature or not timestamp:
            return False

        # 时间窗口检查（5 分钟内有效）
        try:
            ts = float(timestamp)
            if abs(time.time() - ts) > 300:  # 5 分钟
                return False
        except (ValueError, TypeError):
            return False

        # 计算签名
        message = f"{method.upper()}|{path}|{timestamp}"
        expected = hmac.new(
            self._internal_secret.encode(),
            message.encode(),
            hashlib.sha256,
        ).hexdigest()

        return hmac.compare_digest(signature, expected)

    def generate_internal_signature(
        self,
        method: str,
        path: str,
    ) -> tuple[str, str]:
        """生成内部调用签名（用于内部组件调用）

        Returns:
            (signature, timestamp)
        """
        ts = str(time.time())
        message = f"{method.upper()}|{path}|{ts}"
        signature = hmac.new(
            self._internal_secret.encode(),
            message.encode(),
            hashlib.sha256,
        ).hexdigest()
        return signature, ts

    # ── 审计日志 ──────────────────────────────────────

    def _audit(
        self,
        method: str,
        path: str,
        auth_type: str,
        success: bool,
        reason: str = "",
    ) -> None:
        """记录鉴权审计日志"""
        entry = {
            "timestamp": time.time(),
            "method": method,
            "path": path,
            "auth_type": auth_type,
            "success": success,
            "reason": reason,
        }
        self._audit_log.append(entry)

        if not success:
            self._logger.warning(
                "auth_failure",
                method=method,
                path=path,
                auth_type=auth_type,
                reason=reason,
            )

    def get_audit_log(self, limit: int = 100) -> list[dict[str, Any]]:
        """获取鉴权审计日志"""
        return list(reversed(self._audit_log[-limit:]))

    # ── 密钥管理 ──────────────────────────────────────

    def rotate_admin_key(self, new_key: str | None = None) -> dict[str, Any]:
        """轮换 Admin Key"""
        old_key = self._admin_key
        if new_key:
            self._admin_key = new_key
        else:
            self._admin_key = uuid.uuid4().hex + uuid.uuid4().hex

        self._logger.info(
            "admin_key_rotated",
            new_key_preview=self._admin_key[:8] + "****",
        )

        return {
            "success": True,
            "new_key_preview": self._admin_key[:8] + "****",
            "note": "请更新所有使用旧 Key 的客户端",
        }

    @property
    def admin_key_preview(self) -> str:
        """获取 Admin Key 的脱敏预览"""
        if not self._admin_key:
            return ""
        return self._admin_key[:8] + "****"


# 全局单例
_auth_manager: AuthManager | None = None


def get_auth_manager() -> AuthManager:
    """获取鉴权管理器单例"""
    global _auth_manager
    if _auth_manager is None:
        _auth_manager = AuthManager()
    return _auth_manager
