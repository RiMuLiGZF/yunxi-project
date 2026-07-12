"""
M0 主理人管控台 - 认证模块

复用 M8 的 JWT 认证体系，增加 Owner 角色校验。
只有 Owner 角色才能访问 M0 的所有接口。
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Optional

import bcrypt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt

from .config import settings
from .errors import AuthenticationError, PermissionDeniedError

# ---------------------------------------------------------------------------
# 安全配置
# ---------------------------------------------------------------------------

security = HTTPBearer(auto_error=False)

# 角色层级定义（与 M8 保持一致）
ROLE_HIERARCHY = {
    "owner": 100,
    "admin": 80,
    "auditor": 60,
    "user": 40,
    "viewer": 20,
}


# ---------------------------------------------------------------------------
# 密码工具
# ---------------------------------------------------------------------------

def verify_password(plain_password: str, hashed_password: str) -> bool:
    """
    验证密码是否匹配

    Args:
        plain_password: 明文密码
        hashed_password: 哈希后的密码

    Returns:
        bool: 是否匹配
    """
    try:
        return bcrypt.checkpw(
            plain_password.encode("utf-8"),
            hashed_password.encode("utf-8"),
        )
    except Exception:
        return False


def get_password_hash(password: str) -> str:
    """
    生成密码哈希

    Args:
        password: 明文密码

    Returns:
        str: bcrypt 哈希后的密码
    """
    # bcrypt 限制密码长度 72 字节，过长则截断
    password_bytes = password.encode("utf-8")[:72]
    salt = bcrypt.gensalt()
    return bcrypt.hashpw(password_bytes, salt).decode("utf-8")


# ---------------------------------------------------------------------------
# Token 工具
# ---------------------------------------------------------------------------

def create_access_token(
    data: dict,
    expires_delta: Optional[timedelta] = None,
) -> str:
    """
    创建 JWT 访问令牌

    Args:
        data: 要编码到 Token 中的数据
        expires_delta: 过期时间增量，默认使用配置值

    Returns:
        str: JWT 令牌字符串
    """
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.utcnow() + expires_delta
    else:
        expire = datetime.utcnow() + timedelta(
            minutes=settings.access_token_expire_minutes
        )
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(
        to_encode,
        settings.jwt_secret,
        algorithm=settings.jwt_algorithm,
    )
    return encoded_jwt


def decode_token(token: str) -> dict:
    """
    解码并验证 JWT 令牌

    Args:
        token: JWT 令牌字符串

    Returns:
        dict: 解码后的 payload

    Raises:
        AuthenticationError: Token 无效或过期
    """
    try:
        payload = jwt.decode(
            token,
            settings.jwt_secret,
            algorithms=[settings.jwt_algorithm],
        )
        return payload
    except JWTError as e:
        raise AuthenticationError(message=f"Token 无效: {str(e)}")


# ---------------------------------------------------------------------------
# 角色权限
# ---------------------------------------------------------------------------

def has_role(user_role: str, required_role: str) -> bool:
    """
    判断用户角色是否满足所需角色权限（角色层级向下兼容）

    角色层级: owner > admin > auditor > user > viewer
    owner 拥有所有权限，admin 拥有除 owner 外的所有权限，依此类推。

    Args:
        user_role: 用户角色
        required_role: 所需角色

    Returns:
        bool: 是否满足权限要求
    """
    user_level = ROLE_HIERARCHY.get(user_role, 0)
    required_level = ROLE_HIERARCHY.get(required_role, 0)
    return user_level >= required_level


def require_role(required_role: str = "owner"):
    """
    生成角色权限校验依赖函数

    Args:
        required_role: 所需的最低角色

    Returns:
        Callable: FastAPI 依赖函数
    """

    async def role_checker(
        credentials: HTTPAuthorizationCredentials = Depends(security),
    ) -> dict:
        """
        验证 Token 并检查角色权限

        Args:
            credentials: HTTP Bearer Token 凭证

        Returns:
            dict: 用户信息（username, role）

        Raises:
            AuthenticationError: 认证失败
            PermissionDeniedError: 权限不足
        """
        if credentials is None:
            raise AuthenticationError(message="未提供认证令牌")

        token = credentials.credentials
        payload = decode_token(token)

        username: Optional[str] = payload.get("sub")
        role: str = payload.get("role", "viewer")

        if username is None:
            raise AuthenticationError(message="Token 中缺少用户信息")

        if not has_role(role, required_role):
            raise PermissionDeniedError(
                message=f"需要 {required_role} 角色权限，当前角色: {role}"
            )

        return {"username": username, "role": role}

    return role_checker


# ---------------------------------------------------------------------------
# 便捷依赖
# ---------------------------------------------------------------------------

async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security),
) -> dict:
    """
    获取当前认证用户（不做角色检查，仅验证 Token）

    Args:
        credentials: HTTP Bearer Token 凭证

    Returns:
        dict: 用户信息（username, role）

    Raises:
        AuthenticationError: 认证失败
    """
    if credentials is None:
        raise AuthenticationError(message="未提供认证令牌")

    token = credentials.credentials
    payload = decode_token(token)

    username: Optional[str] = payload.get("sub")
    role: str = payload.get("role", "viewer")

    if username is None:
        raise AuthenticationError(message="Token 中缺少用户信息")

    return {"username": username, "role": role}


async def get_principal_user(
    user: dict = Depends(require_role("owner")),
) -> dict:
    """
    获取当前主理人用户（Owner 角色）

    这是 M0 大部分接口使用的依赖，确保只有主理人才能访问。

    Args:
        user: 已通过 Owner 角色校验的用户

    Returns:
        dict: 用户信息
    """
    return user


# ---------------------------------------------------------------------------
# 主理人登录验证
# ---------------------------------------------------------------------------

def authenticate_principal(username: str, password: str) -> Optional[dict]:
    """
    验证主理人登录凭据

    MVP 版本：使用配置文件中预设的主理人账号。
    生产环境应改为从数据库或外部认证系统验证。

    Args:
        username: 用户名
        password: 密码

    Returns:
        Optional[dict]: 认证成功返回用户信息，失败返回 None
    """
    if username != settings.principal.username:
        return None

    # MVP 版本：直接比较明文密码（演示用途）
    # 生产环境应使用哈希密码 + bcrypt
    if password != settings.principal.password:
        return None

    return {
        "username": username,
        "role": "owner",
        "display_name": "主理人",
    }
