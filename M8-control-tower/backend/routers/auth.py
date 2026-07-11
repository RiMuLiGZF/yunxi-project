"""
认证路由
"""

import sys
import json
from pathlib import Path
from datetime import timedelta, datetime
from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel

project_root = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(project_root))

from ..config import settings
from ..auth import verify_password, create_access_token, get_password_hash, get_current_user
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


def _ensure_default_user() -> None:
    """确保至少有一个 admin 用户

    密码优先级：
    1. M8_ADMIN_PASSWORD 环境变量
    2. 首次启动自动生成随机密码（输出到控制台和日志）
    """
    import secrets
    import string

    users = _load_users()
    if not users:
        # 获取管理员密码
        admin_password = settings.admin_password

        # 如果未配置，生成随机密码
        generated = False
        if not admin_password:
            alphabet = string.ascii_letters + string.digits + "!@#$%^&*"
            admin_password = "".join(secrets.choice(alphabet) for _ in range(16))
            generated = True

        default_user = {
            "id": 1,
            "username": "admin",
            "password_hash": get_password_hash(admin_password),
            "role": "admin",
            "nickname": "超级管理员",
            "email": "admin@yunxi.local",
            "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "last_login": None,
            "status": "active",
            "must_change_password": generated,  # 标记首次登录需改密码
        }
        _save_users([default_user])

        # 输出初始密码（仅首次生成时显示）
        if generated:
            print("\n" + "=" * 60)
            print("  ⚠️  首次启动：已生成默认管理员账户")
            print("=" * 60)
            print(f"  用户名: admin")
            print(f"  密  码: {admin_password}")
            print("-" * 60)
            print("  请妥善保存此密码，登录后立即修改！")
            print("=" * 60 + "\n")


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
async def logout(current_user: dict = Depends(get_current_user)):
    """用户登出"""
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
    """修改密码"""
    users = _load_users()
    username = current_user["username"]

    for user in users:
        if user["username"] == username:
            # 验证旧密码
            if not verify_password(req.old_password, user["password_hash"]):
                return ApiResponse.error(code=400, message="旧密码不正确")

            # 校验新密码长度
            if len(req.new_password) < 6:
                return ApiResponse.error(code=400, message="新密码长度不能少于6位")

            # 不能与旧密码相同
            if verify_password(req.new_password, user["password_hash"]):
                return ApiResponse.error(code=400, message="新密码不能与旧密码相同")

            # 更新密码
            user["password_hash"] = get_password_hash(req.new_password)
            _save_users(users)
            return ApiResponse.success(message="密码修改成功")

    return ApiResponse.error(code=404, message="用户不存在")
