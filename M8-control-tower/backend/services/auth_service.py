"""
M8 控制塔 - 认证服务 (AuthService)

封装认证相关的业务逻辑，供 auth.py router 调用。
Router 只负责：参数校验 → 调用 service → 返回响应

职责：
1. 用户登录/登出/Token 刷新
2. 密码哈希与验证
3. Token 黑名单管理
4. 登录速率限制与账户锁定
5. 密码强度校验

注意：
- JWT 签发/验证统一使用 shared.core.auth.jwt.JWTHandler（如果可用）
- 密码哈希使用 bcrypt
- 用户数据持久化通过 UserService（不直接操作文件/数据库）
"""

from __future__ import annotations

import sys
import logging
import time
import threading
from pathlib import Path
from datetime import datetime, timedelta, timezone
from typing import Optional, Dict, Any, Tuple

# 将项目根目录加入 path，以便导入 shared 模块
_project_root = Path(__file__).parent.parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

import bcrypt

from ..config import settings, validate_password_strength
from ..errors import M8ErrorCode, M8Exception

logger = logging.getLogger("m8.auth_service")


# ===========================================================================
# 统一 JWTHandler 初始化（优先使用 shared 中的统一实现）
# ===========================================================================

try:
    from shared.core.auth.jwt import (
        JWTHandler,
        JWTConfig,
        InMemoryTokenBlacklist,
        is_jwt_available,
    )
    _HAS_UNIFIED_JWT = is_jwt_available()
except ImportError:
    _HAS_UNIFIED_JWT = False
    logger.warning("无法导入统一 JWTHandler，将使用本地 jose 实现作为回退方案。")

# jose 库（本地回退实现）
try:
    from jose import JWTError, jwt as _jose_jwt
    _HAS_JOSE = True
except ImportError:
    _jose_jwt = None
    _HAS_JOSE = False


# ===========================================================================
# 速率限制与账户锁定（内存版，生产环境建议用 Redis）
# ===========================================================================

_login_attempts: Dict[str, Dict[str, Any]] = {}  # key -> {count, first_attempt, locked_until}
_login_lock = threading.Lock()

# 配置
LOGIN_MAX_ATTEMPTS = 10          # 连续失败次数阈值
LOGIN_LOCK_DURATION_MIN = 30     # 锁定时长（分钟）
LOGIN_RATE_LIMIT_PER_MIN = 5     # 每分钟最多尝试次数


def _get_login_key(username: str, ip: str = "") -> str:
    """生成登录尝试的 key"""
    if ip:
        return f"ip:{ip}"
    return f"user:{username}"


def _check_rate_limit(username: str, ip: str = "") -> Tuple[bool, str]:
    """检查登录速率限制

    Returns:
        (是否允许, 错误消息)
    """
    now = time.time()
    with _login_lock:
        # 检查 IP 级别限流
        if ip:
            ip_key = _get_login_key("", ip)
            data = _login_attempts.get(ip_key, {"count": 0, "window_start": now})
            if now - data["window_start"] > 60:
                # 重置时间窗口
                data = {"count": 0, "window_start": now}
            if data["count"] >= LOGIN_RATE_LIMIT_PER_MIN:
                return False, f"登录过于频繁，请稍后再试（IP限流，{LOGIN_RATE_LIMIT_PER_MIN}次/分钟）"
            _login_attempts[ip_key] = data

        # 检查用户名级别限流
        user_key = _get_login_key(username, "")
        data = _login_attempts.get(user_key, {"count": 0, "window_start": now, "fail_count": 0, "locked_until": 0})
        if now - data["window_start"] > 60:
            data["count"] = 0
            data["window_start"] = now

        # 检查是否被锁定
        if data.get("locked_until", 0) > now:
            remain = int(data["locked_until"] - now)
            return False, f"账户已被临时锁定，请 {remain // 60} 分钟后再试"

        if data["count"] >= LOGIN_RATE_LIMIT_PER_MIN:
            return False, f"登录过于频繁，请稍后再试（用户限流，{LOGIN_RATE_LIMIT_PER_MIN}次/分钟）"

        _login_attempts[user_key] = data
        return True, ""


def _record_login_attempt(username: str, ip: str = "", success: bool = False) -> None:
    """记录登录尝试结果"""
    now = time.time()
    with _login_lock:
        user_key = _get_login_key(username, "")
        data = _login_attempts.get(user_key, {"count": 0, "window_start": now, "fail_count": 0, "locked_until": 0})

        data["count"] = data.get("count", 0) + 1

        if success:
            # 登录成功，重置失败计数
            data["fail_count"] = 0
            data["locked_until"] = 0
        else:
            data["fail_count"] = data.get("fail_count", 0) + 1
            if data["fail_count"] >= LOGIN_MAX_ATTEMPTS:
                data["locked_until"] = now + LOGIN_LOCK_DURATION_MIN * 60
                logger.warning(f"账户 {username} 连续失败 {LOGIN_MAX_ATTEMPTS} 次，已锁定 {LOGIN_LOCK_DURATION_MIN} 分钟")

        _login_attempts[user_key] = data

        # IP 级别也更新
        if ip:
            ip_key = _get_login_key("", ip)
            ip_data = _login_attempts.get(ip_key, {"count": 0, "window_start": now})
            ip_data["count"] = ip_data.get("count", 0) + 1
            _login_attempts[ip_key] = ip_data


# ===========================================================================
# 密码工具
# ===========================================================================

def get_password_hash(password: str) -> str:
    """生成密码哈希

    Args:
        password: 明文密码

    Returns:
        bcrypt 哈希后的密码字符串
    """
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """验证密码

    Args:
        plain_password: 明文密码
        hashed_password: 哈希后的密码

    Returns:
        是否匹配
    """
    try:
        return bcrypt.checkpw(plain_password.encode("utf-8"), hashed_password.encode("utf-8"))
    except Exception:
        return False


def check_password_strength(password: str) -> Dict[str, Any]:
    """检查密码强度

    Args:
        password: 待检查的密码

    Returns:
        {score, level, suggestions, is_strong}
    """
    score = 0
    suggestions = []

    if len(password) >= 8:
        score += 1
    else:
        suggestions.append("密码长度至少 8 位")

    if len(password) >= 12:
        score += 1

    if any(c.islower() for c in password):
        score += 1
    else:
        suggestions.append("包含小写字母")

    if any(c.isupper() for c in password):
        score += 1
    else:
        suggestions.append("包含大写字母")

    if any(c.isdigit() for c in password):
        score += 1
    else:
        suggestions.append("包含数字")

    if any(not c.isalnum() for c in password):
        score += 1
    else:
        suggestions.append("包含特殊字符")

    # 等级判定
    if score <= 2:
        level = "weak"
    elif score <= 3:
        level = "medium"
    elif score <= 4:
        level = "strong"
    else:
        level = "very_strong"

    return {
        "score": min(score, 4),
        "level": level,
        "suggestions": suggestions,
        "is_strong": score >= 4,
    }


# ===========================================================================
# JWT Token 管理
# ===========================================================================

class TokenManager:
    """Token 管理器

    统一封装 JWT 签发、验证、刷新、黑名单等操作。
    优先使用 shared.core.auth.jwt.JWTHandler，不可用时回退到本地 jose 实现。
    """

    def __init__(self):
        self._jwt_handler = None
        self._token_blacklist = None
        self._init_jwt()

        # Refresh Token 存储（内存版）
        self._refresh_tokens: Dict[str, Dict[str, Any]] = {}
        self._refresh_lock = threading.Lock()

    def _init_jwt(self) -> None:
        """初始化 JWT 处理器"""
        if _HAS_UNIFIED_JWT and settings.jwt_secret:
            try:
                config = JWTConfig(
                    secret=settings.jwt_secret,
                    algorithm=settings.jwt_algorithm,
                    access_token_expire_minutes=settings.access_token_expire_minutes,
                    refresh_token_expire_days=getattr(settings, "refresh_token_expire_days", 7),
                    require_secure_secret=False,
                )
                self._jwt_handler = JWTHandler(config)
                self._token_blacklist = InMemoryTokenBlacklist()
                # 验证 handler 确实可用（密钥非空）
                verify_key = self._jwt_handler._get_verification_key()
                if verify_key:
                    logger.info("统一 JWTHandler 初始化成功")
                    return
                else:
                    logger.warning("统一 JWTHandler 验证密钥为空，将使用本地 jose 实现")
            except Exception as e:
                logger.warning(f"统一 JWTHandler 初始化失败: {e}，将使用本地 jose 实现")

        # 本地 jose 回退实现
        self._jwt_handler = None
        self._token_blacklist = set()

    def create_access_token(self, subject: str, role: str = "user", extra: Optional[Dict] = None) -> Tuple[str, int]:
        """创建访问令牌

        Args:
            subject: 主体（用户名）
            role: 用户角色
            extra: 额外声明

        Returns:
            (token字符串, 有效期秒数)
        """
        expires_in = settings.access_token_expire_minutes * 60

        if self._jwt_handler:
            claims = {"sub": subject, "role": role}
            if extra:
                claims.update(extra)
            token = self._jwt_handler.create_access_token(data=claims)
            return token, expires_in

        # 本地 jose 回退实现
        if _jose_jwt is None:
            raise RuntimeError("JWT 功能不可用：缺少 jose 库")

        expire = datetime.now(tz=timezone.utc) + timedelta(seconds=expires_in)
        import uuid
        jti = str(uuid.uuid4())
        payload = {
            "sub": subject,
            "role": role,
            "exp": expire,
            "iat": datetime.now(tz=timezone.utc),
            "jti": jti,
            "type": "access",
        }
        if extra:
            payload.update(extra)
        token = _jose_jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)
        return token, expires_in

    def create_refresh_token(self, subject: str, role: str = "user") -> Tuple[str, int]:
        """创建刷新令牌

        Args:
            subject: 主体（用户名）
            role: 用户角色

        Returns:
            (token字符串, 有效期秒数)
        """
        expire_days = getattr(settings, "refresh_token_expire_days", 7)
        expires_in = expire_days * 24 * 3600

        if self._jwt_handler:
            data = {"sub": subject, "role": role}
            token = self._jwt_handler.create_refresh_token(data=data)
            return token, expires_in

        # 本地 jose 回退实现
        if _jose_jwt is None:
            raise RuntimeError("JWT 功能不可用：缺少 jose 库")

        import uuid
        jti = str(uuid.uuid4())
        expire = datetime.now(tz=timezone.utc) + timedelta(seconds=expires_in)
        payload = {
            "sub": subject,
            "role": role,
            "exp": expire,
            "iat": datetime.now(tz=timezone.utc),
            "jti": jti,
            "type": "refresh",
        }
        token = _jose_jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)

        # 存储 refresh token
        with self._refresh_lock:
            self._refresh_tokens[jti] = {
                "sub": subject,
                "role": role,
                "exp": expire.timestamp(),
                "created_at": time.time(),
                "revoked": False,
            }

        return token, expires_in

    def verify_token(self, token: str) -> Optional[Dict[str, Any]]:
        """验证访问令牌

        Args:
            token: JWT token 字符串

        Returns:
            解码后的 payload，失败返回 None
        """
        # 检查黑名单
        if self.is_token_blacklisted(token):
            return None

        if self._jwt_handler:
            try:
                payload = self._jwt_handler.decode_token(token)
                return payload
            except Exception:
                return None

        # 本地 jose 回退实现
        if _jose_jwt is None:
            return None

        try:
            payload = _jose_jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_algorithm])
            return payload
        except JWTError:
            return None

    def refresh_access_token(self, refresh_token: str) -> Optional[Tuple[str, str, int]]:
        """使用刷新令牌获取新的访问令牌

        Args:
            refresh_token: 刷新令牌

        Returns:
            (新access_token, 新refresh_token, 有效期秒数) 或 None
        """
        payload = self.verify_token(refresh_token)
        if not payload:
            return None

        # 检查是否是 refresh token
        if payload.get("type") != "refresh":
            return None

        # 检查是否被撤销
        jti = payload.get("jti", "")
        if self._is_refresh_token_revoked(jti):
            return None

        subject = payload.get("sub", "")
        role = payload.get("role", "user")

        # 签发新的 token 对
        new_access_token, expires_in = self.create_access_token(subject, role)
        new_refresh_token, _ = self.create_refresh_token(subject, role)

        # 撤销旧的 refresh token
        self._revoke_refresh_token(jti)

        return new_access_token, new_refresh_token, expires_in

    def blacklist_token(self, token: str) -> None:
        """将 token 加入黑名单

        Args:
            token: JWT token 字符串
        """
        if self._token_blacklist is not None:
            if hasattr(self._token_blacklist, "add"):
                self._token_blacklist.add(token)
        else:
            self._token_blacklist.add(token)

    def is_token_blacklisted(self, token: str) -> bool:
        """检查 token 是否在黑名单中"""
        if self._token_blacklist is not None:
            if hasattr(self._token_blacklist, "is_blacklisted"):
                return self._token_blacklist.is_blacklisted(token)
            return token in self._token_blacklist
        return False

    def _is_refresh_token_revoked(self, jti: str) -> bool:
        """检查 refresh token 是否已被撤销"""
        with self._refresh_lock:
            data = self._refresh_tokens.get(jti)
            if not data:
                # 没有记录（可能是统一 JWTHandler 管理的），假设未撤销
                return False
            return data.get("revoked", False)

    def _revoke_refresh_token(self, jti: str) -> None:
        """撤销 refresh token"""
        with self._refresh_lock:
            if jti in self._refresh_tokens:
                self._refresh_tokens[jti]["revoked"] = True

    def revoke_refresh_token(self, refresh_token: str) -> bool:
        """撤销刷新令牌

        Args:
            refresh_token: 刷新令牌

        Returns:
            是否成功
        """
        payload = self.verify_token(refresh_token)
        if not payload:
            return False
        jti = payload.get("jti", "")
        self._revoke_refresh_token(jti)
        return True


# 全局 TokenManager 单例
_token_manager: Optional[TokenManager] = None
_init_lock = threading.Lock()


def get_token_manager() -> TokenManager:
    """获取 TokenManager 单例"""
    global _token_manager
    if _token_manager is None:
        with _init_lock:
            if _token_manager is None:
                _token_manager = TokenManager()
    return _token_manager


# ===========================================================================
# AuthService - 认证服务主类
# ===========================================================================

class AuthService:
    """认证服务

    封装所有认证相关的业务逻辑。
    Router 层应直接调用此类的方法，不直接操作底层实现。
    """

    def __init__(self):
        self.token_manager = get_token_manager()

    def login(self, username: str, password: str, ip: str = "",
              remember_me: bool = False) -> Dict[str, Any]:
        """用户登录

        Args:
            username: 用户名
            password: 明文密码
            ip: 客户端 IP（用于限流）
            remember_me: 是否记住我（延长有效期）

        Returns:
            {
                "success": bool,
                "access_token": str,
                "refresh_token": str,
                "token_type": str,
                "expires_in": int,
                "user": {...},
                "message": str,
                "error_code": int,
            }

        Raises:
            M8Exception: 登录失败时抛出，由 router 捕获返回响应
        """
        # 1. 速率限制检查
        allowed, msg = _check_rate_limit(username, ip)
        if not allowed:
            raise M8Exception(
                code=M8ErrorCode.AUTH_RATE_LIMITED,
                message=msg,
            )

        # 2. 获取用户（通过 UserService）
        from .user_service import get_user_service
        user_service = get_user_service()
        user = user_service.get_user_by_username(username)

        if not user:
            _record_login_attempt(username, ip, success=False)
            raise M8Exception(
                code=M8ErrorCode.AUTH_INVALID_CREDENTIALS,
                message="用户名或密码错误",
            )

        # 3. 检查用户状态
        if user.get("status") != "active":
            if user.get("status") == "locked":
                raise M8Exception(
                    code=M8ErrorCode.AUTH_ACCOUNT_LOCKED,
                    message="账户已被锁定，请联系管理员",
                )
            raise M8Exception(
                code=M8ErrorCode.AUTH_ACCOUNT_DISABLED,
                message="账户已被禁用",
            )

        # 4. 验证密码
        password_hash = user.get("password_hash", "")
        if not verify_password(password, password_hash):
            _record_login_attempt(username, ip, success=False)
            raise M8Exception(
                code=M8ErrorCode.AUTH_INVALID_CREDENTIALS,
                message="用户名或密码错误",
            )

        # 5. 登录成功
        _record_login_attempt(username, ip, success=True)

        # 6. 生成 Token
        role = user.get("role", "user")
        access_token, expires_in = self.token_manager.create_access_token(
            subject=username,
            role=role,
            extra={"user_id": user.get("id")},
        )
        refresh_token, _ = self.token_manager.create_refresh_token(
            subject=username,
            role=role,
        )

        # 7. 更新最后登录时间
        user_service.update_last_login(username, ip)

        # 8. 返回结果（过滤敏感信息）
        user_info = {
            "id": user.get("id"),
            "username": user.get("username"),
            "nickname": user.get("nickname", user.get("username")),
            "role": role,
            "email": user.get("email"),
            "avatar": user.get("avatar"),
            "status": user.get("status"),
            "created_at": user.get("created_at"),
            "last_login": user.get("last_login"),
        }

        return {
            "success": True,
            "access_token": access_token,
            "refresh_token": refresh_token,
            "token_type": "bearer",
            "expires_in": expires_in,
            "user": user_info,
        }

    def logout(self, access_token: str, refresh_token: Optional[str] = None) -> bool:
        """用户登出

        Args:
            access_token: 访问令牌
            refresh_token: 刷新令牌（可选）

        Returns:
            是否成功
        """
        # 将 access token 加入黑名单
        if access_token:
            self.token_manager.blacklist_token(access_token)

        # 撤销 refresh token
        if refresh_token:
            self.token_manager.revoke_refresh_token(refresh_token)

        return True

    def refresh_token(self, refresh_token: str) -> Dict[str, Any]:
        """刷新访问令牌

        Args:
            refresh_token: 刷新令牌

        Returns:
            {access_token, refresh_token, token_type, expires_in}

        Raises:
            M8Exception: Token 无效时抛出
        """
        result = self.token_manager.refresh_access_token(refresh_token)
        if not result:
            raise M8Exception(
                code=M8ErrorCode.AUTH_TOKEN_INVALID,
                message="刷新令牌无效或已过期",
            )

        new_access_token, new_refresh_token, expires_in = result
        return {
            "access_token": new_access_token,
            "refresh_token": new_refresh_token,
            "token_type": "bearer",
            "expires_in": expires_in,
        }

    def get_current_user(self, token: str) -> Optional[Dict[str, Any]]:
        """从 token 获取当前用户信息

        Args:
            token: JWT token

        Returns:
            用户信息 dict，失败返回 None
        """
        payload = self.token_manager.verify_token(token)
        if not payload:
            return None

        username = payload.get("sub", "")
        if not username:
            return None

        # 获取用户详情
        from .user_service import get_user_service
        user_service = get_user_service()
        user = user_service.get_user_by_username(username)

        if not user or user.get("status") != "active":
            return None

        return {
            "id": user.get("id"),
            "username": user.get("username"),
            "nickname": user.get("nickname", user.get("username")),
            "role": user.get("role", "user"),
            "email": user.get("email"),
            "avatar": user.get("avatar"),
            "status": user.get("status"),
        }

    def change_password(self, username: str, old_password: str, new_password: str) -> bool:
        """修改密码

        Args:
            username: 用户名
            old_password: 原密码
            new_password: 新密码

        Returns:
            是否成功

        Raises:
            M8Exception: 验证失败时抛出
        """
        from .user_service import get_user_service
        user_service = get_user_service()

        user = user_service.get_user_by_username(username)
        if not user:
            raise M8Exception(
                code=M8ErrorCode.USER_NOT_FOUND,
                message="用户不存在",
            )

        # 验证原密码
        if not verify_password(old_password, user.get("password_hash", "")):
            raise M8Exception(
                code=M8ErrorCode.AUTH_INVALID_PASSWORD,
                message="原密码错误",
            )

        # 检查新密码强度
        strength = check_password_strength(new_password)
        if not strength["is_strong"]:
            raise M8Exception(
                code=M8ErrorCode.AUTH_WEAK_PASSWORD,
                message=f"新密码强度不足：{', '.join(strength['suggestions'])}",
            )

        # 更新密码
        new_hash = get_password_hash(new_password)
        success = user_service.update_password(username, new_hash)

        if success:
            logger.info(f"用户 {username} 修改密码成功")
        return success

    def reset_password(self, user_id: int, new_password: str) -> bool:
        """管理员重置用户密码

        Args:
            user_id: 用户 ID
            new_password: 新密码

        Returns:
            是否成功
        """
        from .user_service import get_user_service
        user_service = get_user_service()

        # 检查密码强度
        strength = check_password_strength(new_password)
        if not strength["is_strong"]:
            raise M8Exception(
                code=M8ErrorCode.AUTH_WEAK_PASSWORD,
                message=f"密码强度不足：{', '.join(strength['suggestions'])}",
            )

        new_hash = get_password_hash(new_password)
        return user_service.update_password_by_id(user_id, new_hash)


# 全局 AuthService 单例
_auth_service: Optional[AuthService] = None
_auth_service_lock = threading.Lock()


def get_auth_service() -> AuthService:
    """获取 AuthService 单例"""
    global _auth_service
    if _auth_service is None:
        with _auth_service_lock:
            if _auth_service is None:
                _auth_service = AuthService()
    return _auth_service
