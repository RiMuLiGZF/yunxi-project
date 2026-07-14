"""
云汐 M12 安全盾 - 认证模块
提供 API Key 认证、JWT Token 认证、角色权限控制（RBAC）等功能。
支持多种认证方式：
  1. API Key - 服务间调用
  2. JWT Bearer Token - 用户登录认证
  3. 角色权限 - 基于角色的访问控制
"""

import hashlib
import secrets
import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional, List

# 兼容相对导入和直接运行
try:
    from .config import get_settings
    from .database import get_db
    from .models import ApiKey, TokenBlacklist
except ImportError:
    from config import get_settings
    from database import get_db
    from models import ApiKey, TokenBlacklist

from fastapi import Depends, HTTPException, status, Request
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.orm import Session

from jose import JWTError, jwt
from passlib.context import CryptContext


# ===========================================================================
# 常量定义
# ===========================================================================

# 角色定义
ROLE_SUPER_ADMIN = "super_admin"    # 超级管理员
ROLE_ADMIN = "admin"                # 管理员
ROLE_OPERATOR = "operator"          # 运维人员
ROLE_VIEWER = "viewer"              # 只读用户
ROLE_API = "api"                    # API 调用者

# 角色层级映射（高级别包含低级别权限）
ROLE_HIERARCHY = {
    ROLE_SUPER_ADMIN: 100,
    ROLE_ADMIN: 80,
    ROLE_OPERATOR: 60,
    ROLE_VIEWER: 40,
    ROLE_API: 20,
}

# 权限范围
SCOPE_WAF_READ = "waf:read"
SCOPE_WAF_WRITE = "waf:write"
SCOPE_AUTH_READ = "auth:read"
SCOPE_AUTH_WRITE = "auth:write"
SCOPE_IP_READ = "ip:read"
SCOPE_IP_WRITE = "ip:write"
SCOPE_AUDIT_READ = "audit:read"
SCOPE_DASHBOARD_READ = "dashboard:read"
SCOPE_AUTO_RESPONSE_READ = "auto_response:read"
SCOPE_AUTO_RESPONSE_WRITE = "auto_response:write"

ALL_SCOPES = [
    SCOPE_WAF_READ, SCOPE_WAF_WRITE,
    SCOPE_AUTH_READ, SCOPE_AUTH_WRITE,
    SCOPE_IP_READ, SCOPE_IP_WRITE,
    SCOPE_AUDIT_READ,
    SCOPE_DASHBOARD_READ,
    SCOPE_AUTO_RESPONSE_READ, SCOPE_AUTO_RESPONSE_WRITE,
]


# ===========================================================================
# 密码哈希
# ===========================================================================

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def hash_password(password: str) -> str:
    """哈希密码

    Args:
        password: 明文密码

    Returns:
        哈希后的密码
    """
    return pwd_context.hash(password)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """验证密码

    Args:
        plain_password: 明文密码
        hashed_password: 哈希后的密码

    Returns:
        是否匹配
    """
    return pwd_context.verify(plain_password, hashed_password)


# ===========================================================================
# API Key 管理
# ===========================================================================

def generate_api_key(prefix: str = "m12-") -> str:
    """生成 API Key

    Args:
        prefix: 密钥前缀

    Returns:
        生成的 API Key 字符串
    """
    key = secrets.token_urlsafe(32)
    return f"{prefix}{key}"


def hash_api_key(api_key: str) -> str:
    """哈希 API Key（用于存储，使用 bcrypt 慢哈希）
    
    Args:
        api_key: 明文 API Key
    
    Returns:
        bcrypt 哈希值
    """
    return pwd_context.hash(api_key)


def get_api_key_prefix(api_key: str) -> str:
    """获取 API Key 前缀（用于展示）

    Args:
        api_key: 完整 API Key

    Returns:
        前缀 + 末尾 4 位
    """
    if len(api_key) > 8:
        return f"{api_key[:8]}...{api_key[-4:]}"
    return api_key[:8] + "..." if api_key else ""


def validate_api_key(db: Session, api_key: str) -> Optional[ApiKey]:
    """验证 API Key 是否有效"""
    # 获取所有活跃的 API Key 记录
    active_keys = db.query(ApiKey).filter(ApiKey.is_active == True).all()
    
    for key_record in active_keys:
        try:
            if pwd_context.verify(api_key, key_record.key_hash):
                # 检查是否过期
                if key_record.expires_at and key_record.expires_at < datetime.now(tz=timezone.utc):
                    return None
                return key_record
        except Exception:
            continue
    
    return None


# ===========================================================================
# JWT Token 管理
# ===========================================================================

def create_access_token(
    data: dict,
    expires_delta: Optional[timedelta] = None,
) -> str:
    """创建访问令牌

    Args:
        data: 要编码到 Token 中的数据
        expires_delta: 过期时间增量

    Returns:
        JWT Token 字符串
    """
    settings = get_settings()
    to_encode = data.copy()

    if expires_delta:
        expire = datetime.now(tz=timezone.utc) + expires_delta
    else:
        expire = datetime.now(tz=timezone.utc) + timedelta(minutes=settings.jwt_expire_minutes)

    to_encode.update({
        "exp": expire,
        "iat": datetime.now(tz=timezone.utc),
        "type": "access",
        "jti": uuid.uuid4().hex,
    })

    encoded_jwt = jwt.encode(
        to_encode,
        settings.jwt_secret,
        algorithm=settings.jwt_algorithm,
    )
    return encoded_jwt


def create_refresh_token(data: dict) -> str:
    """创建刷新令牌

    Args:
        data: 要编码到 Token 中的数据

    Returns:
        JWT 刷新令牌字符串
    """
    settings = get_settings()
    to_encode = data.copy()
    expire = datetime.now(tz=timezone.utc) + timedelta(days=settings.jwt_refresh_expire_days)

    to_encode.update({
        "exp": expire,
        "iat": datetime.now(tz=timezone.utc),
        "type": "refresh",
        "jti": uuid.uuid4().hex,
    })

    encoded_jwt = jwt.encode(
        to_encode,
        settings.jwt_secret,
        algorithm=settings.jwt_algorithm,
    )
    return encoded_jwt


def decode_token(token: str) -> Optional[dict]:
    """解码 JWT Token

    Args:
        token: JWT Token 字符串

    Returns:
        解码后的数据，无效返回 None
    """
    settings = get_settings()
    try:
        payload = jwt.decode(
            token,
            settings.jwt_secret,
            algorithms=[settings.jwt_algorithm],
        )
        return payload
    except JWTError:
        return None


# ===========================================================================
# Token 黑名单管理
# ===========================================================================

def is_token_blacklisted(db: Session, token_jti: str) -> bool:
    """检查 Token JTI 是否在黑名单中

    Args:
        db: 数据库会话
        token_jti: Token 的 JTI 标识

    Returns:
        是否在黑名单中
    """
    if not token_jti:
        return False
    return db.query(TokenBlacklist).filter(
        TokenBlacklist.token_jti == token_jti,
    ).first() is not None


def add_token_to_blacklist(
    db: Session,
    token_jti: str,
    token_hash: str,
    expired_at: datetime,
) -> None:
    """将 Token 加入黑名单

    Args:
        db: 数据库会话
        token_jti: Token 的 JTI 标识
        token_hash: Token 的 SHA256 哈希
        expired_at: Token 过期时间
    """
    exists = db.query(TokenBlacklist).filter(
        TokenBlacklist.token_jti == token_jti,
    ).first()
    if exists:
        return
    record = TokenBlacklist(
        token_jti=token_jti,
        token_hash=token_hash,
        expired_at=expired_at,
    )
    db.add(record)
    db.commit()


def clean_expired_blacklist_tokens(db: Session) -> int:
    """清理已过期的黑名单 Token

    Args:
        db: 数据库会话

    Returns:
        清理的记录数量
    """
    now = datetime.now(tz=timezone.utc)
    result = db.query(TokenBlacklist).filter(
        TokenBlacklist.expired_at < now,
    ).delete(synchronize_session=False)
    db.commit()
    return result


def blacklist_token(db: Session, token: str) -> bool:
    """将指定 Token 加入黑名单（便捷函数）

    Args:
        db: 数据库会话
        token: JWT Token 字符串

    Returns:
        是否成功加入黑名单
    """
    payload = decode_token(token)
    if not payload or not payload.get("jti"):
        return False
    jti = payload.get("jti")
    exp_timestamp = payload.get("exp")
    expired_at = datetime.fromtimestamp(exp_timestamp) if exp_timestamp else datetime.now(tz=timezone.utc)
    token_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()
    add_token_to_blacklist(db, jti, token_hash, expired_at)
    return True


# ===========================================================================
# 角色权限控制
# ===========================================================================

def has_role(user_roles: List[str], required_role: str) -> bool:
    """检查用户是否拥有指定角色（按层级判断）

    Args:
        user_roles: 用户角色列表
        required_role: 需要的角色

    Returns:
        是否有权限
    """
    required_level = ROLE_HIERARCHY.get(required_role, 0)
    for role in user_roles:
        user_level = ROLE_HIERARCHY.get(role, 0)
        if user_level >= required_level:
            return True
    return False


def has_scope(user_scopes: List[str], required_scope: str) -> bool:
    """检查用户是否拥有指定权限范围

    Args:
        user_scopes: 用户权限范围列表
        required_scope: 需要的权限范围

    Returns:
        是否有权限
    """
    # 通配符支持
    if "*" in user_scopes:
        return True

    return required_scope in user_scopes


def has_any_scope(user_scopes: List[str], required_scopes: List[str]) -> bool:
    """检查用户是否拥有任意一个指定权限范围

    Args:
        user_scopes: 用户权限范围列表
        required_scopes: 需要的权限范围列表

    Returns:
        是否有任意一个权限
    """
    for scope in required_scopes:
        if has_scope(user_scopes, scope):
            return True
    return False


# ===========================================================================
# FastAPI 依赖
# ===========================================================================

security = HTTPBearer(auto_error=False)


async def get_current_user(
    request: Request,
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
    db: Session = Depends(get_db),
) -> dict:
    """获取当前认证用户（支持 API Key 和 JWT）

    认证优先级：
    1. X-API-Key 请求头（API Key 认证）
    2. Authorization: Bearer <token>（JWT 认证）

    Args:
        request: FastAPI 请求对象
        credentials: HTTP Bearer 认证凭据
        db: 数据库会话

    Returns:
        用户信息字典

    Raises:
        HTTPException: 认证失败时抛出 401
    """
    # 方式 1: API Key 认证
    api_key = request.headers.get("X-API-Key") or request.headers.get("x-api-key")
    if api_key:
        key_record = validate_api_key(db, api_key)
        if key_record:
            return {
                "auth_type": "api_key",
                "user_id": f"api_{key_record.id}",
                "username": key_record.key_name,
                "roles": key_record.roles or [],
                "scopes": key_record.scopes or [],
                "api_key_id": key_record.id,
            }

    # 方式 2: JWT Bearer Token 认证
    if credentials and credentials.scheme.lower() == "bearer":
        token = credentials.credentials
        payload = decode_token(token)
        if payload and payload.get("type") == "access":
            # 黑名单检查
            jti = payload.get("jti")
            if jti and is_token_blacklisted(db, jti):
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Token 已失效",
                    headers={"WWW-Authenticate": "Bearer"},
                )
            # 自动清理过期黑名单 Token（静默失败不影响主流程）
            try:
                clean_expired_blacklist_tokens(db)
            except Exception:
                pass
            return {
                "auth_type": "jwt",
                "user_id": payload.get("sub", ""),
                "username": payload.get("username", ""),
                "roles": payload.get("roles", []),
                "scopes": payload.get("scopes", []),
            }

    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="未认证或认证已过期",
        headers={"WWW-Authenticate": "Bearer"},
    )


def require_role(required_role: str):
    """角色权限检查装饰器（作为 FastAPI 依赖使用）

    Args:
        required_role: 需要的角色

    Returns:
        依赖函数
    """
    def role_checker(current_user: dict = Depends(get_current_user)) -> dict:
        if not has_role(current_user.get("roles", []), required_role):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"需要 {required_role} 角色权限",
            )
        return current_user
    return role_checker


def require_scope(required_scope: str):
    """权限范围检查装饰器（作为 FastAPI 依赖使用）

    Args:
        required_scope: 需要的权限范围

    Returns:
        依赖函数
    """
    def scope_checker(current_user: dict = Depends(get_current_user)) -> dict:
        if not has_scope(current_user.get("scopes", []), required_scope):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"需要 {required_scope} 权限",
            )
        return current_user
    return scope_checker
