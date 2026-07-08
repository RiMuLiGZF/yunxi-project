"""
用户管理路由
"""

import sys
import json
from pathlib import Path
from datetime import datetime
from fastapi import APIRouter, Depends
from pydantic import BaseModel
from typing import List, Optional

project_root = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(project_root))

from ..schemas import ApiResponse
from ..auth import get_current_user, get_password_hash, verify_password

router = APIRouter()

# ==================== 数据存储路径 ====================

def _get_yunxi_dir() -> Path:
    """获取云汐数据目录 ~/.yunxi"""
    yunxi_dir = Path.home() / ".yunxi"
    yunxi_dir.mkdir(parents=True, exist_ok=True)
    return yunxi_dir


USERS_FILE = _get_yunxi_dir() / "users.json"

# ==================== 用户数据管理 ====================

_users_cache: Optional[List[dict]] = None


def _load_users() -> List[dict]:
    """从文件加载用户列表"""
    global _users_cache
    if USERS_FILE.exists():
        try:
            with open(USERS_FILE, "r", encoding="utf-8") as f:
                _users_cache = json.load(f)
            return _users_cache
        except Exception:
            pass

    # 首次运行：初始化 admin 用户
    default_users = [
        {
            "id": 1,
            "username": "admin",
            "password_hash": get_password_hash("admin123456"),
            "role": "admin",
            "nickname": "超级管理员",
            "email": "admin@yunxi.local",
            "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "last_login": None,
            "status": "active",
        }
    ]
    _save_users(default_users)
    _users_cache = default_users
    return _users_cache


def _save_users(users: List[dict]) -> None:
    """保存用户列表到文件"""
    global _users_cache
    with open(USERS_FILE, "w", encoding="utf-8") as f:
        json.dump(users, f, ensure_ascii=False, indent=2)
    _users_cache = users


def _get_users() -> List[dict]:
    """获取用户列表（带缓存）"""
    global _users_cache
    if _users_cache is None:
        return _load_users()
    return _users_cache


def _next_user_id(users: List[dict]) -> int:
    """生成下一个用户ID"""
    if not users:
        return 1
    return max(u["id"] for u in users) + 1


def _user_to_public(user: dict) -> dict:
    """转换为公开信息（去除密码哈希）"""
    return {
        "id": user["id"],
        "username": user["username"],
        "role": user.get("role", "viewer"),
        "nickname": user.get("nickname", user["username"]),
        "email": user.get("email", ""),
        "created_at": user.get("created_at", ""),
        "last_login": user.get("last_login"),
        "status": user.get("status", "active"),
    }


# ==================== Pydantic 模型 ====================

class UserCreate(BaseModel):
    username: str
    password: str
    role: str = "viewer"  # admin/operator/viewer
    nickname: Optional[str] = None
    email: Optional[str] = None


class UserUpdate(BaseModel):
    role: Optional[str] = None
    nickname: Optional[str] = None
    email: Optional[str] = None
    status: Optional[str] = None
    password: Optional[str] = None  # 可选：管理员重置密码


# ==================== 用户管理接口 ====================

@router.get("/users")
async def list_users(current_user: dict = Depends(get_current_user)):
    """获取用户列表"""
    users = _get_users()
    items = [_user_to_public(u) for u in users]
    return ApiResponse.success(data={"total": len(items), "items": items})


@router.post("/users")
async def create_user(
    req: UserCreate,
    current_user: dict = Depends(get_current_user),
):
    """新增用户"""
    # 仅管理员可创建用户
    if current_user.get("role") != "admin":
        return ApiResponse.error(code=403, message="无权限创建用户")

    users = _get_users()

    # 检查用户名是否已存在
    if any(u["username"] == req.username for u in users):
        return ApiResponse.error(code=400, message="用户名已存在")

    # 校验角色
    if req.role not in ("admin", "operator", "viewer"):
        return ApiResponse.error(code=400, message="角色值无效，仅支持 admin/operator/viewer")

    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    new_user = {
        "id": _next_user_id(users),
        "username": req.username,
        "password_hash": get_password_hash(req.password),
        "role": req.role,
        "nickname": req.nickname or req.username,
        "email": req.email or "",
        "created_at": now,
        "last_login": None,
        "status": "active",
    }
    users.append(new_user)
    _save_users(users)

    return ApiResponse.success(message="用户创建成功", data=_user_to_public(new_user))


@router.put("/users/{user_id}")
async def update_user(
    user_id: int,
    req: UserUpdate,
    current_user: dict = Depends(get_current_user),
):
    """更新用户"""
    # 仅管理员可修改用户
    if current_user.get("role") != "admin":
        return ApiResponse.error(code=403, message="无权限修改用户")

    users = _get_users()

    for user in users:
        if user["id"] == user_id:
            if req.role is not None:
                if req.role not in ("admin", "operator", "viewer"):
                    return ApiResponse.error(code=400, message="角色值无效")
                user["role"] = req.role
            if req.nickname is not None:
                user["nickname"] = req.nickname
            if req.email is not None:
                user["email"] = req.email
            if req.status is not None:
                if req.status not in ("active", "disabled"):
                    return ApiResponse.error(code=400, message="状态值无效")
                user["status"] = req.status
            if req.password is not None:
                if len(req.password) < 6:
                    return ApiResponse.error(code=400, message="密码长度不能少于6位")
                user["password_hash"] = get_password_hash(req.password)

            _save_users(users)
            return ApiResponse.success(message="用户更新成功", data=_user_to_public(user))

    return ApiResponse.error(code=404, message="用户不存在")


@router.delete("/users/{user_id}")
async def delete_user(
    user_id: int,
    current_user: dict = Depends(get_current_user),
):
    """删除用户"""
    # 仅管理员可删除用户
    if current_user.get("role") != "admin":
        return ApiResponse.error(code=403, message="无权限删除用户")

    users = _get_users()

    # 禁止删除自己
    if current_user.get("username") and any(
        u["id"] == user_id and u["username"] == current_user["username"]
        for u in users
    ):
        return ApiResponse.error(code=400, message="不能删除当前登录用户")

    for i, user in enumerate(users):
        if user["id"] == user_id:
            users.pop(i)
            _save_users(users)
            return ApiResponse.success(message="用户删除成功")

    return ApiResponse.error(code=404, message="用户不存在")
