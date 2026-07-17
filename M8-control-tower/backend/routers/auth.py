"""
认证路由
"""

import sys
import json
from pathlib import Path
from datetime import timedelta, datetime
from fastapi import APIRouter, HTTPException, Depends
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel

project_root = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(project_root))

from ..config import (
    settings,
    validate_password_strength,
    is_weak_default_password,
    generate_strong_password,
    PASSWORD_MIN_LENGTH,
)
from ..auth import (
    verify_password,
    create_access_token,
    get_password_hash,
    get_current_user,
    blacklist_token,
    security,
)
from ..schemas import ApiResponse

router = APIRouter()

# ==================== 用户数据存储路径 ====================

def _get_yunxi_dir() -> Path:
    """获取云汐数据目录 ~/.yunxi"""
    yunxi_dir = Path.home() / ".yunxi"
    yunxi_dir.mkdir(parents=True, exist_ok=True)
    return yunxi_dir


USERS_FILE = _get_yunxi_dir() / "users.json"


def _load_users() -> list:
    """加载用户列表"""
    if USERS_FILE.exists():
        try:
            with open(USERS_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return []


def _save_users(users: list) -> None:
    """保存用户列表"""
    with open(USERS_FILE, "w", encoding="utf-8") as f:
        json.dump(users, f, ensure_ascii=False, indent=2)


def _find_user_by_username(username: str) -> dict | None:
    """按用户名查找用户"""
    users = _load_users()
    for user in users:
        if user["username"] == username:
            return user
    return None


def _get_default_admin_password() -> str:
    """获取默认管理员密码（SC-004 P1级安全加固）

    优先级：
    1. 配置文件中的 M8_ADMIN_PASSWORD（如果是强密码）
    2. 开发环境：如果配置了弱默认密码，使用它但输出警告
    3. 开发环境：如果未配置，自动生成随机强密码并写入文件
    4. 生产环境：不允许使用默认弱密码

    Returns:
        str: 管理员密码（明文）
    """
    configured_pwd = settings.admin_password

    if configured_pwd and not is_weak_default_password(configured_pwd):
        # 配置了强密码，直接使用
        strong, _ = validate_password_strength(configured_pwd)
        if strong:
            return configured_pwd

    # 弱密码或未配置
    if settings.is_production:
        # 生产环境不允许使用弱密码，这里只在创建用户时被调用
        # 如果到了这里，说明配置校验没拦住，使用一个随机强密码
        import logging
        logger = logging.getLogger("m8.auth")
        random_pwd = generate_strong_password(16)
        logger.critical(
            "[SC-004 P1] 生产环境安全警告：M8_ADMIN_PASSWORD 未配置或为弱密码！\n"
            "       已自动生成随机管理员密码，请立即修改！\n"
            "       请配置 M8_ADMIN_PASSWORD 为符合强度要求的强密码。"
        )
        return random_pwd
    else:
        # 开发环境
        if configured_pwd and is_weak_default_password(configured_pwd):
            # 配置了默认弱密码，开发环境允许使用但警告
            import logging
            logger = logging.getLogger("m8.auth")
            logger.warning(
                "[SC-004 P1] 开发环境：当前使用默认弱密码 admin123456\n"
                "       生产环境请务必修改为强密码！\n"
                f"       密码强度要求：至少 {PASSWORD_MIN_LENGTH} 位，"
                "包含大小写字母、数字和特殊字符"
            )
            return configured_pwd
        elif configured_pwd:
            # 配置了但强度不够，开发环境允许
            return configured_pwd
        else:
            # 未配置，自动生成随机密码
            import logging
            logger = logging.getLogger("m8.auth")
            temp_pwd = generate_strong_password(16)
            # 将密码写入日志目录的文件
            try:
                logs_dir = Path(__file__).parent.parent / "data" / "logs"
                logs_dir.mkdir(parents=True, exist_ok=True)
                pwd_file = logs_dir / "temp_admin_password.txt"
                with open(pwd_file, "w", encoding="utf-8") as f:
                    f.write(f"# M8 管理员临时密码（开发环境自动生成）\n")
                    f.write(f"# 生成时间: {datetime.now().isoformat()}\n")
                    f.write(f"# 用户名: {settings.admin_username}\n")
                    f.write(f"# 密码: {temp_pwd}\n")
                    f.write(f"# 注意：仅开发环境使用，重启后重新生成\n")
                try:
                    pwd_file.chmod(0o600)
                except Exception:
                    pass
                logger.warning(
                    "[SC-004 P1] 开发环境：未配置 M8_ADMIN_PASSWORD，已自动生成临时强密码\n"
                    f"       用户名: {settings.admin_username}\n"
                    f"       临时密码已写入: {pwd_file}\n"
                    "       请通过 M8_ADMIN_PASSWORD 环境变量配置正式密码"
                )
            except Exception:
                logger.warning(
                    "[SC-004 P1] 开发环境：未配置 M8_ADMIN_PASSWORD，已自动生成临时强密码\n"
                    f"       用户名: {settings.admin_username}\n"
                    "       （无法写入密码文件，请通过日志查看）"
                )
            return temp_pwd


def _ensure_default_user() -> None:
    """确保至少有一个 admin 用户（SC-004 P1级安全加固）"""
    users = _load_users()
    if not users:
        # 获取安全的管理员密码
        admin_pwd = _get_default_admin_password()
        default_user = {
            "id": 1,
            "username": settings.admin_username,
            "password_hash": get_password_hash(admin_pwd),
            "role": "admin",
            "nickname": "超级管理员",
            "email": "admin@yunxi.local",
            "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "last_login": None,
            "status": "active",
        }
        _save_users([default_user])


# 启动时确保默认用户存在
_ensure_default_user()


# ==================== Pydantic 模型 ====================

class LoginRequest(BaseModel):
    username: str
    password: str


class ChangePasswordRequest(BaseModel):
    old_password: str
    new_password: str


# ==================== 认证接口 ====================

@router.post("/login")
async def login(req: LoginRequest):
    """用户登录"""
    user = _find_user_by_username(req.username)

    # 用户不存在
    if not user:
        raise HTTPException(status_code=401, detail="用户名或密码错误")

    # 检查用户状态
    if user.get("status") == "disabled":
        raise HTTPException(status_code=401, detail="账号已被禁用")

    # 验证密码（bcrypt 哈希）
    if not verify_password(req.password, user["password_hash"]):
        raise HTTPException(status_code=401, detail="用户名或密码错误")

    # 更新最后登录时间
    users = _load_users()
    for u in users:
        if u["username"] == req.username:
            u["last_login"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            break
    _save_users(users)

    access_token = create_access_token(
        data={"sub": req.username, "role": user.get("role", "viewer")},
        expires_delta=timedelta(minutes=settings.access_token_expire_minutes),
    )

    return ApiResponse.success(
        data={
            "access_token": access_token,
            "token_type": "bearer",
            "user": {
                "username": user["username"],
                "role": user.get("role", "viewer"),
                "nickname": user.get("nickname", user["username"]),
                "email": user.get("email", ""),
            },
        }
    )


@router.post("/logout")
async def logout(
    current_user: dict = Depends(get_current_user),
    credentials: HTTPAuthorizationCredentials = Depends(security),
):
    """用户登出（将 Token 加入黑名单）"""
    if credentials is not None:
        blacklist_token(credentials.credentials)
    return ApiResponse.success(message="登出成功")


@router.get("/userinfo")
async def get_userinfo(current_user: dict = Depends(get_current_user)):
    """获取当前用户信息"""
    user = _find_user_by_username(current_user["username"])
    user_info = {
        "username": current_user["username"],
        "role": current_user["role"],
        "nickname": user.get("nickname", current_user["username"]) if user else current_user["username"],
        "email": user.get("email", "") if user else "",
        "avatar": "",
    }
    return ApiResponse.success(data=user_info)


@router.get("/me")
async def get_me(current_user: dict = Depends(get_current_user)):
    """获取当前用户信息（别名）"""
    return await get_userinfo(current_user)


@router.post("/change-password")
async def change_password(
    req: ChangePasswordRequest,
    current_user: dict = Depends(get_current_user),
):
    """修改密码（SC-004 P1级：强制密码强度校验）"""
    users = _load_users()
    username = current_user["username"]

    for user in users:
        if user["username"] == username:
            # 验证旧密码
            if not verify_password(req.old_password, user["password_hash"]):
                return ApiResponse.error(code=400, message="旧密码不正确")

            # 校验新密码强度
            strong, msg = validate_password_strength(req.new_password)
            if not strong:
                return ApiResponse.error(
                    code=400,
                    message=f"新密码强度不足：{msg}"
                )

            # 不能与旧密码相同
            if verify_password(req.new_password, user["password_hash"]):
                return ApiResponse.error(code=400, message="新密码不能与旧密码相同")

            # 更新密码
            user["password_hash"] = get_password_hash(req.new_password)
            _save_users(users)
            return ApiResponse.success(message="密码修改成功")

    return ApiResponse.error(code=404, message="用户不存在")
