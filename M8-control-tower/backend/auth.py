"""
M8 管理工作台 - 认证模块（SEC-004 修复：迁移到统一认证体系）

本模块已迁移到使用 shared.core.auth.jwt 中的统一 JWTHandler，
保留 M8 特有的功能（密码哈希、角色权限、内部 Token 验证等），
JWT 签发/验证统一走 JWTHandler，确保：
- Token 黑名单检查
- 密钥轮换接口
- JTI 唯一标识
- 向后兼容：旧的 Token 格式仍然能验证通过（平滑过渡）
"""

import sys
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

import bcrypt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

from .config import settings

logger = logging.getLogger("m8.auth")

# 将项目根目录加入 path，以便导入 shared 模块
_project_root = Path(__file__).parent.parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

# 尝试导入统一的 JWTHandler
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
    logger.warning(
        "[SEC-004] 无法导入统一 JWTHandler，将使用 jose 直接实现作为回退方案。"
    )
    try:
        from jose import JWTError, jwt as _jose_jwt
    except ImportError:
        _jose_jwt = None

security = HTTPBearer(auto_error=False)


# ===========================================================================
# 统一 JWTHandler 初始化 + Token 黑名单
# ===========================================================================

_jwt_handler: Optional["JWTHandler"] = None
_token_blacklist: Optional["InMemoryTokenBlacklist"] = None
_jwt_init_failed = False


def _get_jwt_handler() -> Optional["JWTHandler"]:
    """获取或初始化统一 JWTHandler（懒加载）

    Returns:
        JWTHandler 实例，不可用时返回 None
    """
    global _jwt_handler, _jwt_init_failed

    if _jwt_handler is not None:
        return _jwt_handler

    if _jwt_init_failed or not _HAS_UNIFIED_JWT:
        return None

    # 向后兼容：如果密钥为空或太短，不使用统一 JWTHandler，
    # 回退到直接使用 jose 的方式（保持旧行为）
    # JWTHandler 内部会检查 if not verify_key: return None，空密钥会导致验证失败
    if not settings.jwt_secret or len(settings.jwt_secret) < 1:
        logger.debug(
            "[SEC-004] JWT 密钥为空，跳过统一 JWTHandler 初始化，使用回退方案"
        )
        _jwt_init_failed = True
        return None

    try:
        config = JWTConfig(
            secret=settings.jwt_secret,
            algorithm=settings.jwt_algorithm,
            access_token_expire_minutes=settings.access_token_expire_minutes,
            issuer="m8-control-tower",
            require_secure_secret=settings.is_production,
        )
        _jwt_handler = JWTHandler(config)
        logger.info("[SEC-004] 已初始化统一 JWTHandler（M8 控制塔）")
        return _jwt_handler
    except Exception as e:
        _jwt_init_failed = True
        logger.warning("[SEC-004] JWTHandler 初始化失败，将使用回退方案: %s", e)
        return None


def _get_token_blacklist() -> Optional["InMemoryTokenBlacklist"]:
    """获取或初始化内存 Token 黑名单

    Returns:
        InMemoryTokenBlacklist 实例
    """
    global _token_blacklist

    if _token_blacklist is not None:
        return _token_blacklist

    if not _HAS_UNIFIED_JWT:
        return None

    try:
        _token_blacklist = InMemoryTokenBlacklist()
        return _token_blacklist
    except Exception:
        return None


def _jti_is_blacklisted(jti: Optional[str]) -> bool:
    """检查 JTI 是否在黑名单中

    Args:
        jti: Token 的 JTI 标识

    Returns:
        True 表示在黑名单中
    """
    if not jti:
        return False
    bl = _get_token_blacklist()
    if bl is None:
        return False
    return bl.is_blacklisted(jti)


def blacklist_token(token: str) -> bool:
    """将 Token 加入黑名单（用于登出）

    Args:
        token: JWT Token 字符串

    Returns:
        True 表示成功加入黑名单
    """
    if not _HAS_UNIFIED_JWT:
        return False

    handler = _get_jwt_handler()
    bl = _get_token_blacklist()
    if handler is None or bl is None:
        return False

    try:
        # 先验证 Token 有效性
        payload = handler.decode_token(token, token_type="access")
        if payload is None:
            return False

        jti = payload.get("jti")
        if not jti:
            return False

        # 计算过期时间
        exp_timestamp = payload.get("exp")
        if exp_timestamp:
            expired_at = datetime.fromtimestamp(exp_timestamp, tz=timezone.utc)
        else:
            expired_at = datetime.now(tz=timezone.utc) + timedelta(
                minutes=settings.access_token_expire_minutes
            )

        token_hash = handler.hash_token(token)
        bl.add(jti, token_hash, expired_at)
        return True
    except Exception as e:
        logger.warning("加入 Token 黑名单失败: %s", e)
        return False


def clean_expired_blacklist() -> int:
    """清理已过期的黑名单 Token

    Returns:
        清理的记录数量
    """
    bl = _get_token_blacklist()
    if bl is None:
        return 0
    return bl.clean_expired()


def rotate_jwt_secret(new_secret: str) -> bool:
    """密钥轮换接口 - 用新密钥重新初始化 JWTHandler

    注意：旧密钥签发的 Token 在密钥轮换后暂时无法验证，
    如需支持平滑过渡，请使用 RS256 + verification_keys 机制。

    Args:
        new_secret: 新的 JWT 密钥

    Returns:
        True 表示轮换成功
    """
    global _jwt_handler

    if not _HAS_UNIFIED_JWT:
        return False

    try:
        config = JWTConfig(
            secret=new_secret,
            algorithm=settings.jwt_algorithm,
            access_token_expire_minutes=settings.access_token_expire_minutes,
            issuer="m8-control-tower",
            require_secure_secret=settings.is_production,
        )
        _jwt_handler = JWTHandler(config)
        logger.info("[SEC-004] JWT 密钥已轮换")
        return True
    except Exception as e:
        logger.warning("[SEC-004] JWT 密钥轮换失败: %s", e)
        return False


# ===========================================================================
# 密码相关（M8 特有，保留）
# ===========================================================================

def verify_password(plain_password: str, hashed_password: str) -> bool:
    """验证密码（使用 bcrypt）"""
    try:
        return bcrypt.checkpw(
            plain_password.encode("utf-8"), hashed_password.encode("utf-8")
        )
    except Exception:
        return False


def get_password_hash(password: str) -> str:
    """生成密码哈希（使用 bcrypt）"""
    # bcrypt 限制密码长度 72 字节，过长则截断
    password_bytes = password.encode("utf-8")[:72]
    salt = bcrypt.gensalt()
    return bcrypt.hashpw(password_bytes, salt).decode("utf-8")


# ===========================================================================
# JWT Token 签发/验证（统一走 JWTHandler，保留向后兼容）
# ===========================================================================

def create_access_token(
    data: dict, expires_delta: Optional[timedelta] = None
) -> str:
    """创建访问令牌

    优先使用统一 JWTHandler，不可用时回退到直接使用 jose。
    新签发的 Token 包含 JTI、type 等标准字段。

    Args:
        data: 要编码到 Token 中的数据
        expires_delta: 过期时间增量，不传则使用默认配置

    Returns:
        JWT Token 字符串
    """
    handler = _get_jwt_handler()
    if handler is not None:
        return handler.create_access_token(data, expires_delta)

    # 回退方案：直接使用 jose（保持旧格式兼容）
    if not _HAS_UNIFIED_JWT and _jose_jwt is not None:
        to_encode = data.copy()
        if expires_delta:
            expire = datetime.now(tz=timezone.utc) + expires_delta
        else:
            expire = datetime.now(tz=timezone.utc) + timedelta(
                minutes=settings.access_token_expire_minutes
            )
        to_encode.update({"exp": expire})
        return _jose_jwt.encode(
            to_encode, settings.jwt_secret, algorithm=settings.jwt_algorithm
        )

    raise RuntimeError("JWT 功能不可用，请安装 python-jose")


def _decode_token_legacy(token: str) -> Optional[dict]:
    """旧格式 Token 解码（向后兼容）

    用于验证不含 type、jti、iss 字段的旧 Token。
    这是为了平滑过渡，确保升级前签发的 Token 仍然有效。

    注意：旧格式 Token 不验证 issuer，因为旧 Token 可能没有 iss 字段。

    Args:
        token: JWT Token 字符串

    Returns:
        payload 字典，无效返回 None
    """
    try:
        # 旧格式 Token 直接用 jose 解码，不验证 issuer 和 type
        # 因为旧 Token 可能没有这些字段
        if _HAS_UNIFIED_JWT:
            from jose import jwt as _jose_jwt
            payload = _jose_jwt.decode(
                token,
                settings.jwt_secret,
                algorithms=[settings.jwt_algorithm],
                options={"verify_aud": False},
            )
            return payload
        else:
            # 回退到 jose
            if _jose_jwt is not None:
                return _jose_jwt.decode(
                    token, settings.jwt_secret, algorithms=[settings.jwt_algorithm]
                )
    except Exception:
        pass
    return None


async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security),
) -> dict:
    """获取当前用户

    验证流程：
    1. 检查 Authorization header
    2. 使用统一 JWTHandler 验证 Token
    3. 检查 Token 是否在黑名单中
    4. 向后兼容：如果新格式验证失败，尝试旧格式

    Args:
        credentials: HTTP Bearer Token 凭证

    Returns:
        用户信息字典 {"username": ..., "role": ...}

    Raises:
        HTTPException: 401 未授权
    """
    if credentials is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
            headers={"WWW-Authenticate": "Bearer"},
        )

    token = credentials.credentials
    payload = None

    handler = _get_jwt_handler()
    if handler is not None:
        # 优先使用统一 JWTHandler 验证（新格式，带 type=access）
        payload = handler.decode_token(token, token_type="access")

        if payload is None:
            # 向后兼容：尝试旧格式（没有 type 字段的 Token）
            payload = _decode_token_legacy(token)
            if payload is not None:
                logger.debug(
                    "[SEC-004] 检测到旧格式 Token，已兼容验证通过，"
                    "建议用户重新登录获取新格式 Token"
                )

        # 检查 Token 黑名单
        if payload is not None:
            jti = payload.get("jti")
            if _jti_is_blacklisted(jti):
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Token has been revoked",
                    headers={"WWW-Authenticate": "Bearer"},
                )
    else:
        # 回退方案：直接使用 jose
        try:
            if _jose_jwt is not None:
                payload = _jose_jwt.decode(
                    token, settings.jwt_secret, algorithms=[settings.jwt_algorithm]
                )
        except Exception:
            payload = None

    if payload is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token",
            headers={"WWW-Authenticate": "Bearer"},
        )

    username: str = payload.get("sub", "")
    role: str = payload.get("role", "viewer")

    if not username:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token",
            headers={"WWW-Authenticate": "Bearer"},
        )

    return {"username": username, "role": role}


def verify_m8_token(token: str) -> bool:
    """验证 M8 内部 Token（模块间调用）"""
    return token == settings.m8_admin_token


# ===========================================================================
# 角色权限（M8 特有，保留）
# ===========================================================================

# 角色层级定义（供外部引用）
ROLE_LEVELS = {
    "owner": 100,
    "admin": 80,
    "auditor": 60,
    "user": 40,
    "viewer": 20,
}

# 合法角色列表
VALID_ROLES = set(ROLE_LEVELS.keys())


def has_role(user_role: str, required_role: str) -> bool:
    """
    判断用户角色是否满足所需角色权限（角色层级向下兼容）。

    角色层级: owner > admin > auditor > user > viewer
    owner 拥有所有权限，admin 拥有除 owner 外的所有权限，依此类推。
    """
    user_level = ROLE_LEVELS.get(user_role, 0)
    required_level = ROLE_LEVELS.get(required_role, 0)
    return user_level >= required_level


def require_role(required_role: str):
    """
    角色权限校验装饰器。

    用法（装饰器模式）:
        @router.post("/admin-only")
        @require_role("admin")
        async def admin_endpoint(data: dict, current_user: dict = Depends(get_current_user)):
            ...

    注意：被装饰的函数必须已经通过 get_current_user 获取了 current_user，
    装饰器会从函数的 kwargs 或返回前的上下文中检查角色。
    为简化实现，装饰器模式下依赖函数参数中的 current_user。
    """

    def decorator(func):
        import functools

        @functools.wraps(func)
        async def wrapper(*args, **kwargs):
            # 尝试从 kwargs 中获取 current_user
            current_user = kwargs.get("current_user")
            # 如果没有，尝试从函数签名中找到 current_user 的位置
            if current_user is None:
                import inspect

                sig = inspect.signature(func)
                bound = sig.bind_partial(*args, **kwargs)
                current_user = bound.arguments.get("current_user")

            if current_user is None:
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Not authenticated",
                )

            user_role = current_user.get("role", "viewer")
            if not has_role(user_role, required_role):
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail=f"Insufficient permissions. Required role: {required_role}",
                )

            return await func(*args, **kwargs)

        return wrapper

    return decorator
