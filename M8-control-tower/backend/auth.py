"""
M8 管理工作台 - 认证模块
"""

from datetime import datetime, timedelta
from typing import Optional
from jose import JWTError, jwt
import bcrypt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

from .config import settings

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


def verify_m8_token(token: str) -> bool:
    """验证 M8 内部 Token"""
    return token == settings.m8_admin_token


def has_role(user_role: str, required_role: str) -> bool:
    """
    判断用户角色是否满足所需角色权限（角色层级向下兼容）。
    
    角色层级: owner > admin > auditor > user > viewer
    owner 拥有所有权限，admin 拥有除 owner 外的所有权限，依此类推。
    """
    role_hierarchy = {
        "owner": 100,
        "admin": 80,
        "auditor": 60,
        "user": 40,
        "viewer": 20,
    }
    user_level = role_hierarchy.get(user_role, 0)
    required_level = role_hierarchy.get(required_role, 0)
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
            # 如果没有，尝试从 args 中找（通常是关键字参数）
            if current_user is None:
                # 尝试从函数签名中找到 current_user 的位置
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
