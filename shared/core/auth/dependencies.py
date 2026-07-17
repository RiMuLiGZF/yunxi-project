"""
统一认证体系 - FastAPI Depends 认证依赖

提供以 FastAPI Depends 方式使用的认证依赖函数，
适合在路由级别进行细粒度认证控制。

与中间件方式的区别：
- 中间件：全局拦截，适合所有接口都需要认证的场景
- Depends：路由级控制，适合部分接口需要认证的场景

用法：
    from fastapi import Depends, FastAPI
    from shared.core.auth.dependencies import create_auth_dependency
    from shared.core.auth.jwt import JWTHandler, JWTConfig

    jwt_handler = JWTHandler(JWTConfig(secret="your-secret"))
    get_current_user = create_auth_dependency(jwt_handler=jwt_handler)

    app = FastAPI()

    @app.get("/protected")
    async def protected(current_user: dict = Depends(get_current_user)):
        return {"user": current_user}
"""

from typing import Optional, Dict, Any, List, Callable

try:
    from fastapi import Depends, HTTPException, status, Request, Header
    from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
    _fastapi_available = True
except ImportError:  # pragma: no cover
    Depends = None
    HTTPException = None
    status = None
    Request = None
    Header = None
    HTTPBearer = None
    HTTPAuthorizationCredentials = None
    _fastapi_available = False


def is_fastapi_available() -> bool:
    """检查 FastAPI 是否可用"""
    return _fastapi_available


# ===========================================================================
# JWT 认证依赖
# ===========================================================================

def create_jwt_dependency(
    jwt_handler,
    token_blacklist_checker: Optional[Callable[[str], bool]] = None,
) -> Callable:
    """创建 JWT 认证依赖函数

    Args:
        jwt_handler: JWTHandler 实例
        token_blacklist_checker: Token 黑名单检查函数（可选）

    Returns:
        FastAPI 依赖函数，返回当前用户信息字典

    用法：
        get_current_user = create_jwt_dependency(jwt_handler)

        @app.get("/protected")
        async def protected(user=Depends(get_current_user)):
            return {"user": user}
    """
    if not _fastapi_available:
        raise RuntimeError("FastAPI 不可用，请先安装: pip install fastapi")

    security = HTTPBearer(auto_error=False)

    async def get_current_user(
        request: Request,
        credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
    ) -> Dict[str, Any]:
        """获取当前认证用户（JWT 方式）

        Raises:
            HTTPException: 401 认证失败
        """
        if credentials and credentials.scheme.lower() == "bearer":
            token = credentials.credentials
            payload = jwt_handler.decode_token(token, token_type="access")
            if payload:
                # 黑名单检查
                jti = payload.get("jti")
                if jti and token_blacklist_checker:
                    try:
                        if token_blacklist_checker(jti):
                            raise HTTPException(
                                status_code=status.HTTP_401_UNAUTHORIZED,
                                detail="Token 已失效",
                                headers={"WWW-Authenticate": "Bearer"},
                            )
                    except HTTPException:
                        raise
                    except Exception:
                        pass  # 黑名单检查异常不影响主流程

                return {
                    "auth_type": "jwt",
                    "user_id": payload.get("sub", ""),
                    "username": payload.get("username", ""),
                    "roles": payload.get("roles", []),
                    "scopes": payload.get("scopes", []),
                    "jti": jti,
                }

        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="未认证或认证已过期",
            headers={"WWW-Authenticate": "Bearer"},
        )

    return get_current_user


# ===========================================================================
# API Key 认证依赖
# ===========================================================================

def create_api_key_dependency(
    api_key_validator,
    header_names: Optional[List[str]] = None,
) -> Callable:
    """创建 API Key 认证依赖函数

    Args:
        api_key_validator: ApiKeyValidator 实例
        header_names: API Key Header 名称列表，默认 ["X-API-Key"]

    Returns:
        FastAPI 依赖函数，返回当前用户信息字典
    """
    if not _fastapi_available:
        raise RuntimeError("FastAPI 不可用，请先安装: pip install fastapi")

    if header_names is None:
        header_names = ["X-API-Key"]

    async def api_key_dependency(
        request: Request,
    ) -> Dict[str, Any]:
        """API Key 认证依赖

        Raises:
            HTTPException: 401 认证失败
        """
        # 从多个 Header 中提取
        api_key = None
        for header_name in header_names:
            key = request.headers.get(header_name.lower())
            if key:
                api_key = key
                break

        # 从 Query 参数提取
        if not api_key:
            api_key = request.query_params.get("api_key")

        if not api_key:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail=f"缺少 API Key，请在 {'/'.join(header_names)} 请求头中提供",
                headers={"WWW-Authenticate": "Bearer"},
            )

        key_info = api_key_validator.validate(api_key)
        if key_info is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="API Key 无效",
                headers={"WWW-Authenticate": "Bearer"},
            )

        return {
            "auth_type": "api_key",
            "user_id": f"api_{key_info.key_name}",
            "username": key_info.key_name,
            "roles": key_info.roles or [],
            "scopes": key_info.scopes or [],
            "api_key_name": key_info.key_name,
        }

    return api_key_dependency


# ===========================================================================
# 统一认证依赖（支持 JWT + API Key 双模式）
# ===========================================================================

def create_auth_dependency(
    jwt_handler=None,
    api_key_validator=None,
    api_key_header_names: Optional[List[str]] = None,
    token_blacklist_checker: Optional[Callable[[str], bool]] = None,
    required: bool = True,
) -> Callable:
    """创建统一认证依赖函数（支持 JWT + API Key 双模式）

    认证优先级：
    1. API Key（Header / Query）
    2. JWT Bearer Token

    Args:
        jwt_handler: JWTHandler 实例（可选）
        api_key_validator: ApiKeyValidator 实例（可选）
        api_key_header_names: API Key Header 名称列表
        token_blacklist_checker: Token 黑名单检查函数（可选）
        required: 是否强制要求认证，默认 True

    Returns:
        FastAPI 依赖函数，返回当前用户信息字典

    用法：
        get_current_user = create_auth_dependency(
            jwt_handler=jwt_handler,
            api_key_validator=api_key_validator,
        )

        @app.get("/protected")
        async def protected(user=Depends(get_current_user)):
            return {"user": user}
    """
    if not _fastapi_available:
        raise RuntimeError("FastAPI 不可用，请先安装: pip install fastapi")

    if api_key_header_names is None:
        api_key_header_names = ["X-API-Key"]

    security = HTTPBearer(auto_error=False)

    async def get_current_user(
        request: Request,
        credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
    ) -> Dict[str, Any]:
        """获取当前认证用户（支持 API Key 和 JWT）

        Raises:
            HTTPException: 401 认证失败（当 required=True 时）
        """
        # 方式 1: API Key 认证
        if api_key_validator is not None:
            api_key = None
            for header_name in api_key_header_names:
                key = request.headers.get(header_name.lower())
                if key:
                    api_key = key
                    break
            if not api_key:
                api_key = request.query_params.get("api_key")

            if api_key:
                key_info = api_key_validator.validate(api_key)
                if key_info:
                    return {
                        "auth_type": "api_key",
                        "user_id": f"api_{key_info.key_name}",
                        "username": key_info.key_name,
                        "roles": key_info.roles or [],
                        "scopes": key_info.scopes or [],
                        "api_key_name": key_info.key_name,
                    }

        # 方式 2: JWT Bearer Token 认证
        if jwt_handler is not None and credentials and credentials.scheme.lower() == "bearer":
            token = credentials.credentials
            payload = jwt_handler.decode_token(token, token_type="access")
            if payload:
                # 黑名单检查
                jti = payload.get("jti")
                if jti and token_blacklist_checker:
                    try:
                        if token_blacklist_checker(jti):
                            raise HTTPException(
                                status_code=status.HTTP_401_UNAUTHORIZED,
                                detail="Token 已失效",
                                headers={"WWW-Authenticate": "Bearer"},
                            )
                    except HTTPException:
                        raise
                    except Exception:
                        pass

                return {
                    "auth_type": "jwt",
                    "user_id": payload.get("sub", ""),
                    "username": payload.get("username", ""),
                    "roles": payload.get("roles", []),
                    "scopes": payload.get("scopes", []),
                    "jti": jti,
                }

        # 认证失败
        if required:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="未认证或认证已过期",
                headers={"WWW-Authenticate": "Bearer"},
            )

        # 可选认证模式下返回匿名用户
        return {
            "auth_type": "none",
            "user_id": "",
            "username": "anonymous",
            "roles": [],
            "scopes": [],
        }

    return get_current_user


# ===========================================================================
# 简单 Token 认证依赖（兼容 M9/M10 旧模块）
# ===========================================================================

def create_token_header_dependency(
    token_getter: Callable[[], str],
    header_names: Optional[List[str]] = None,
) -> Callable:
    """创建简单 Token Header 认证依赖

    适用于 M9/M10 等使用单一静态 Token 的旧模块，
    便于逐步迁移到统一认证体系。

    Args:
        token_getter: 获取预期 Token 的函数（无参，返回字符串）
        header_names: Token Header 名称列表

    Returns:
        FastAPI 依赖函数，认证成功返回 True
    """
    if not _fastapi_available:
        raise RuntimeError("FastAPI 不可用，请先安装: pip install fastapi")

    import hmac

    if header_names is None:
        header_names = ["X-API-Token"]

    async def token_dependency(request: Request) -> bool:
        """Token Header 认证依赖

        Raises:
            HTTPException: 401 认证失败
        """
        expected = token_getter()
        if not expected:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="认证 Token 未配置",
            )

        # 从多个 Header 中提取
        token = ""
        for header_name in header_names:
            t = request.headers.get(header_name.lower())
            if t:
                token = t
                break

        # 也支持 Authorization: Bearer
        if not token:
            auth_header = request.headers.get("authorization", "")
            if auth_header.lower().startswith("bearer "):
                token = auth_header[7:].strip()

        if not token:
            raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
                detail="未提供认证 Token",
            )

        if not hmac.compare_digest(token, expected):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Token 无效",
            )

        return True

    return token_dependency
