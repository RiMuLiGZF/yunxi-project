"""
云汐 M12 安全盾 - 鉴权管理 API
提供 API 密钥管理、登录认证、Token 刷新等接口
"""

from fastapi import APIRouter, Query, Depends
from fastapi.security import HTTPAuthorizationCredentials
from sqlalchemy.orm import Session
from typing import Optional

# 兼容相对导入和直接运行
try:
    from ..models import make_response, make_error_response
    from ..auth import (
        generate_api_key,
        hash_api_key,
        get_api_key_prefix,
        create_access_token,
        create_refresh_token,
        decode_token,
        verify_password,
        require_role,
        ROLE_ADMIN,
        security,
        blacklist_token,
        clean_expired_blacklist_tokens,
    )
    from ..database import get_db
    from ..config import get_settings
except ImportError:
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from models import make_response, make_error_response
    from auth import (
        generate_api_key,
        hash_api_key,
        get_api_key_prefix,
        create_access_token,
        create_refresh_token,
        decode_token,
        verify_password,
        require_role,
        ROLE_ADMIN,
        security,
        blacklist_token,
        clean_expired_blacklist_tokens,
    )
    from database import get_db
    from config import get_settings

router = APIRouter(prefix="/api/m12/auth", tags=["M12-鉴权管理"])


# 模拟 API Key 存储（实际应使用数据库）
_api_keys_storage = []
_api_key_id_counter = 0


# ===========================================================================
# 登录认证
# ===========================================================================

@router.post("/login", summary="登录获取 Token")
def login(
    username: str,
    password: str,
    remember_me: bool = False,
):
    """
    用户登录，获取访问令牌和刷新令牌

    当前通过环境变量配置的管理员账户进行认证。
    首次部署前请设置 M12_ADMIN_USERNAME 和 M12_ADMIN_PASSWORD_HASH。
    """
    try:
        settings = get_settings()

        if not username or not password:
            return make_error_response("用户名和密码不能为空", code=400)

        # 检查管理员账户是否已配置
        if not settings.admin_username or not settings.admin_password_hash:
            return make_error_response(
                "管理员账户未配置，请先设置 M12_ADMIN_USERNAME 和 M12_ADMIN_PASSWORD_HASH",
                code=503,
            )

        # 验证用户名和密码
        if username != settings.admin_username:
            return make_error_response("用户名或密码错误", code=401)

        if not verify_password(password, settings.admin_password_hash):
            return make_error_response("用户名或密码错误", code=401)

        # 构造用户信息（不再硬编码 admin 权限）
        user_info = {
            "user_id": f"user_{username}",
            "username": username,
            "roles": [ROLE_ADMIN],
            "scopes": ["*"],
        }

        # 生成 Token
        access_token = create_access_token(
            data={
                "sub": user_info["user_id"],
                "username": username,
                "roles": user_info["roles"],
                "scopes": user_info["scopes"],
            },
        )
        refresh_token = create_refresh_token(
            data={
                "sub": user_info["user_id"],
                "username": username,
            },
        )

        return make_response(data={
            "access_token": access_token,
            "refresh_token": refresh_token,
            "token_type": "bearer",
            "expires_in": settings.jwt_expire_minutes * 60,
            "user": user_info,
        }, message="登录成功")
    except Exception as e:
        return make_error_response(f"登录失败: {str(e)}")


@router.post("/refresh", summary="刷新 Token")
def refresh_token(refresh_token: str):
    """
    使用刷新令牌获取新的访问令牌
    """
    try:
        settings = get_settings()

        # 解码刷新令牌
        payload = decode_token(refresh_token)
        if not payload or payload.get("type") != "refresh":
            return make_error_response("无效的刷新令牌", code=401)

        user_id = payload.get("sub", "")
        username = payload.get("username", "")

        # 生成新的 Token
        new_access_token = create_access_token(
            data={
                "sub": user_id,
                "username": username,
                "roles": payload.get("roles", []),
                "scopes": payload.get("scopes", []),
            },
        )
        new_refresh_token = create_refresh_token(
            data={
                "sub": user_id,
                "username": username,
            },
        )

        return make_response(data={
            "access_token": new_access_token,
            "refresh_token": new_refresh_token,
            "token_type": "bearer",
            "expires_in": settings.jwt_expire_minutes * 60,
        }, message="Token 刷新成功")
    except Exception as e:
        return make_error_response(f"刷新 Token 失败: {str(e)}")


@router.post("/logout", summary="登出")
def logout(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
    db: Session = Depends(get_db),
):
    """
    用户登出，服务端将当前 Token 加入黑名单
    """
    try:
        if credentials and credentials.scheme.lower() == "bearer":
            token = credentials.credentials
            blacklist_token(db, token)
            # 登出时自动清理过期黑名单 Token
            clean_expired_blacklist_tokens(db)
        return make_response(data={"success": True}, message="登出成功")
    except Exception as e:
        return make_error_response(f"登出失败: {str(e)}")


# ===========================================================================
# API 密钥管理
# ===========================================================================

@router.get("/keys", summary="API 密钥列表")
def list_api_keys(
    owner: Optional[str] = Query(None, description="所有者筛选"),
    is_active: Optional[bool] = Query(None, description="是否启用筛选"),
    page: int = Query(1, ge=1, description="页码"),
    page_size: int = Query(20, ge=1, le=100, description="每页数量"),
    current_user: dict = Depends(require_role(ROLE_ADMIN)),
):
    """
    获取 API 密钥列表
    """
    try:
        global _api_keys_storage

        keys = list(_api_keys_storage)

        # 筛选
        if owner:
            keys = [k for k in keys if k.get("owner") == owner]
        if is_active is not None:
            keys = [k for k in keys if k.get("is_active") == is_active]

        # 倒序排列
        keys.reverse()

        # 分页
        total = len(keys)
        offset = (page - 1) * page_size
        paged_keys = keys[offset:offset + page_size]
        total_pages = (total + page_size - 1) // page_size if page_size > 0 else 0

        return make_response(data={
            "items": paged_keys,
            "total": total,
            "page": page,
            "page_size": page_size,
            "total_pages": total_pages,
        })
    except Exception as e:
        return make_error_response(f"获取密钥列表失败: {str(e)}")


@router.post("/keys", summary="创建 API 密钥")
def create_api_key(
    key_name: str,
    owner: str = "",
    roles: str = "",
    scopes: str = "",
    rate_limit: int = 0,
    description: str = "",
    current_user: dict = Depends(require_role(ROLE_ADMIN)),
):
    """
    创建新的 API 密钥

    注意：密钥只会在创建时返回一次，请妥善保存
    """
    try:
        global _api_keys_storage, _api_key_id_counter

        # 生成密钥
        api_key = generate_api_key(prefix=get_settings().api_key_prefix)
        key_hash = hash_api_key(api_key)
        key_prefix = get_api_key_prefix(api_key)

        _api_key_id_counter += 1
        key_record = {
            "id": _api_key_id_counter,
            "key_name": key_name,
            "key_hash": key_hash,
            "key_prefix": key_prefix,
            "owner": owner,
            "roles": roles.split(",") if roles else [],
            "scopes": scopes.split(",") if scopes else [],
            "rate_limit": rate_limit,
            "call_count": 0,
            "last_used_at": None,
            "expires_at": None,
            "is_active": True,
            "created_by": "system",
            "created_at": __import__("datetime").datetime.now().isoformat(),
            "description": description,
        }

        _api_keys_storage.append(key_record)

        # 返回时包含完整密钥（仅这一次）
        result = key_record.copy()
        result["api_key"] = api_key
        # 移除敏感字段的哈希值
        result.pop("key_hash", None)

        return make_response(data=result, message="API 密钥创建成功，请妥善保存")
    except Exception as e:
        return make_error_response(f"创建 API 密钥失败: {str(e)}")


@router.get("/keys/{key_id}", summary="获取密钥详情")
def get_api_key_detail(
    key_id: int,
    current_user: dict = Depends(require_role(ROLE_ADMIN)),
):
    """
    获取单个 API 密钥的详细信息（不含密钥本身）
    """
    try:
        global _api_keys_storage

        key_record = next((k for k in _api_keys_storage if k["id"] == key_id), None)
        if not key_record:
            return make_error_response(f"密钥不存在: {key_id}", code=404)

        # 不返回哈希值
        result = key_record.copy()
        result.pop("key_hash", None)

        return make_response(data=result)
    except Exception as e:
        return make_error_response(f"获取密钥详情失败: {str(e)}")


@router.put("/keys/{key_id}", summary="更新密钥")
def update_api_key(
    key_id: int,
    key_name: Optional[str] = None,
    owner: Optional[str] = None,
    roles: Optional[str] = None,
    scopes: Optional[str] = None,
    rate_limit: Optional[int] = None,
    description: Optional[str] = None,
    is_active: Optional[bool] = None,
    current_user: dict = Depends(require_role(ROLE_ADMIN)),
):
    """
    更新 API 密钥的配置信息
    """
    try:
        global _api_keys_storage

        key_record = next((k for k in _api_keys_storage if k["id"] == key_id), None)
        if not key_record:
            return make_error_response(f"密钥不存在: {key_id}", code=404)

        if key_name is not None:
            key_record["key_name"] = key_name
        if owner is not None:
            key_record["owner"] = owner
        if roles is not None:
            key_record["roles"] = roles.split(",") if roles else []
        if scopes is not None:
            key_record["scopes"] = scopes.split(",") if scopes else []
        if rate_limit is not None:
            key_record["rate_limit"] = rate_limit
        if description is not None:
            key_record["description"] = description
        if is_active is not None:
            key_record["is_active"] = is_active

        result = key_record.copy()
        result.pop("key_hash", None)

        return make_response(data=result, message="密钥更新成功")
    except Exception as e:
        return make_error_response(f"更新密钥失败: {str(e)}")


@router.delete("/keys/{key_id}", summary="吊销密钥")
def revoke_api_key(
    key_id: int,
    current_user: dict = Depends(require_role(ROLE_ADMIN)),
):
    """
    吊销（删除）指定的 API 密钥
    """
    try:
        global _api_keys_storage

        key_record = next((k for k in _api_keys_storage if k["id"] == key_id), None)
        if not key_record:
            return make_error_response(f"密钥不存在: {key_id}", code=404)

        _api_keys_storage = [k for k in _api_keys_storage if k["id"] != key_id]

        return make_response(data={"revoked": True, "key_id": key_id}, message="密钥已吊销")
    except Exception as e:
        return make_error_response(f"吊销密钥失败: {str(e)}")


@router.post("/keys/{key_id}/rotate", summary="轮换密钥")
def rotate_api_key(
    key_id: int,
    current_user: dict = Depends(require_role(ROLE_ADMIN)),
):
    """
    轮换 API 密钥（生成新密钥，旧密钥失效）

    注意：新密钥只会返回一次，请妥善保存
    """
    try:
        global _api_keys_storage

        key_record = next((k for k in _api_keys_storage if k["id"] == key_id), None)
        if not key_record:
            return make_error_response(f"密钥不存在: {key_id}", code=404)

        # 生成新密钥
        new_api_key = generate_api_key(prefix=get_settings().api_key_prefix)
        new_key_hash = hash_api_key(new_api_key)
        new_key_prefix = get_api_key_prefix(new_api_key)

        # 更新记录
        key_record["key_hash"] = new_key_hash
        key_record["key_prefix"] = new_key_prefix
        key_record["call_count"] = 0
        key_record["last_used_at"] = None

        result = key_record.copy()
        result["api_key"] = new_api_key
        result.pop("key_hash", None)

        return make_response(data=result, message="密钥轮换成功，请妥善保存新密钥")
    except Exception as e:
        return make_error_response(f"轮换密钥失败: {str(e)}")
