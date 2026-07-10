"""
M8 管理工作台 - 认证模块
"""

"""
M8 Control Tower - Auth Module
"""

import os
import hmac
import secrets
import string
from pathlib import Path
from datetime import datetime, timedelta
from typing import Optional
from jose import JWTError, jwt
import bcrypt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

from .config import settings


def _ensure_jwt_secret() -> str:
    """Ensure JWT secret exists, auto-generate if not configured."""
    if settings.jwt_secret:
        return settings.jwt_secret

    alphabet = string.ascii_letters + string.digits + "!@#$%^&*-_=+"
    generated = "yunxi-jwt-" + "".join(secrets.choice(alphabet) for _ in range(48))

    try:
        secret_dir = Path.home() / ".yunxi"
        secret_dir.mkdir(parents=True, exist_ok=True)
        secret_file = secret_dir / "jwt_secret"
        if secret_file.exists():
            saved = secret_file.read_text(encoding="utf-8").strip()
            if saved:
                settings.jwt_secret = saved
                return saved
        secret_file.write_text(generated, encoding="utf-8")
        os.chmod(str(secret_file), 0o600)
    except Exception:
        pass

    settings.jwt_secret = generated
    return generated


_jwt_secret = _ensure_jwt_secret()

security = HTTPBearer(auto_error=False)



def verify_password(plain_password: str, hashed_password: str) -> bool:
    """验证密码（使用 bcrypt）"""
    try:
        return bcrypt.checkpw(plain_password.encode("utf-8"), hashed_password.encode("utf-8"))
    except Exception:
        return False


def get_password_hash(password: str) -> str:
    """生成密码哈希（使用 bcrypt）"""
    # bcrypt 限制密码长度 72 字节，过长则截断
    password_bytes = password.encode("utf-8")[:72]
    salt = bcrypt.gensalt()
    return bcrypt.hashpw(password_bytes, salt).decode("utf-8")


def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    """创建访问令牌"""
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.utcnow() + expires_delta
    else:
        expire = datetime.utcnow() + timedelta(minutes=settings.access_token_expire_minutes)
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, settings.jwt_secret, algorithm=settings.jwt_algorithm)
    return encoded_jwt


async def get_current_user(credentials: HTTPAuthorizationCredentials = Depends(security)) -> dict:
    """获取当前用户"""
    if credentials is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
            headers={"WWW-Authenticate": "Bearer"},
        )

    token = credentials.credentials
    try:
        payload = jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_algorithm])
        username: str = payload.get("sub")
        role: str = payload.get("role", "viewer")
        if username is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid token",
            )
    except JWTError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token",
        )

    return {"username": username, "role": role}



def has_role(user_role: str, required_role: str) -> bool:
    """检查用户是否拥有指定角色权限
    
    角色层级: owner > admin > editor > viewer
    """
    role_hierarchy = {
        "owner": 4,
        "admin": 3,
        "editor": 2,
        "viewer": 1,
    }
    user_level = role_hierarchy.get(user_role, 0)
    required_level = role_hierarchy.get(required_role, 0)
    return user_level >= required_level


def require_role(role: str):
    """角色权限校验装饰器
    
    用法: @router.post("/endpoint")
          @require_role("admin")
          async def endpoint(current_user: dict = Depends(get_current_user), ...):
    """
    from functools import wraps
    import inspect
    
    def decorator(func):
        @wraps(func)
        async def async_wrapper(*args, **kwargs):
            # Try to get current_user from kwargs first
            current_user = kwargs.get("current_user")
            if current_user is None:
                # Try to find it from args by inspecting the function signature
                sig = inspect.signature(func)
                params = list(sig.parameters.keys())
                if "current_user" in params:
                    idx = params.index("current_user")
                    if idx < len(args):
                        current_user = args[idx]
            
            if current_user is None or not isinstance(current_user, dict):
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Not authenticated",
                )
            
            if not has_role(current_user.get("role", ""), role):
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail=f"Insufficient permissions. Required role: {role}",
                )
            
            return await func(*args, **kwargs)
        
        @wraps(func)
        def sync_wrapper(*args, **kwargs):
            current_user = kwargs.get("current_user")
            if current_user is None:
                sig = inspect.signature(func)
                params = list(sig.parameters.keys())
                if "current_user" in params:
                    idx = params.index("current_user")
                    if idx < len(args):
                        current_user = args[idx]
            
            if current_user is None or not isinstance(current_user, dict):
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Not authenticated",
                )
            
            if not has_role(current_user.get("role", ""), role):
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail=f"Insufficient permissions. Required role: {role}",
                )
            
            return func(*args, **kwargs)
        
        # Check if the wrapped function is async
        import asyncio
        if asyncio.iscoroutinefunction(func):
            return async_wrapper
        else:
            return sync_wrapper
    
    return decorator


def verify_m8_token(token: str) -> bool:
    """Verify M8 internal token using hmac.compare_digest."""
    expected = settings.m8_admin_token
    if not expected:
        return False
    return hmac.compare_digest(token, expected)