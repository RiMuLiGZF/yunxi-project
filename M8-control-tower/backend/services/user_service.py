"""
M8 控制塔 - 用户服务 (UserService)

封装用户管理相关的业务逻辑，供 users.py router 和 auth_service 调用。
Router 只负责：参数校验 → 调用 service → 返回响应

职责：
1. 用户 CRUD（创建、查询、更新、删除）
2. 用户状态管理（启用/禁用/锁定）
3. 用户角色管理
4. 用户偏好设置
5. 个人资料管理
6. 密码更新

数据存储：
- 当前使用 JSON 文件存储（~/.yunxi/users.json）
- 后续可迁移到数据库，只需修改本文件的实现即可
- 上层调用方不受影响
"""

from __future__ import annotations

import sys
import json
import time
import threading
import logging
from pathlib import Path
from datetime import datetime
from typing import Optional, List, Dict, Any

# 将项目根目录加入 path，以便导入 shared 模块
_project_root = Path(__file__).parent.parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

from ..config import settings, generate_strong_password
from ..errors import M8ErrorCode, M8Exception

logger = logging.getLogger("m8.user_service")


# ===========================================================================
# 数据存储路径
# ===========================================================================

def _get_yunxi_dir() -> Path:
    """获取云汐数据目录 ~/.yunxi"""
    yunxi_dir = Path.home() / ".yunxi"
    yunxi_dir.mkdir(parents=True, exist_ok=True)
    return yunxi_dir


USERS_FILE = _get_yunxi_dir() / "users.json"


# ===========================================================================
# UserService - 用户服务主类
# ===========================================================================

class UserService:
    """用户服务

    封装所有用户管理相关的业务逻辑。
    数据持久层抽象在此类内部，上层（router/auth_service）不直接访问存储。
    """

    def __init__(self):
        self._users_cache: Optional[List[Dict]] = None
        self._cache_lock = threading.RLock()
        self._file_lock = threading.Lock()
        # 确保初始数据存在
        self._ensure_initialized()

    def _ensure_initialized(self) -> None:
        """确保用户数据已初始化"""
        if self._users_cache is None:
            self._load_users()

    # -----------------------------------------------------------------------
    # 数据持久化（内部方法）
    # -----------------------------------------------------------------------

    def _load_users(self) -> List[Dict]:
        """从文件加载用户列表"""
        with self._cache_lock:
            if self._users_cache is not None:
                return self._users_cache

            users_file = Path(USERS_FILE) if isinstance(USERS_FILE, str) else USERS_FILE
            if users_file.exists():
                try:
                    with open(users_file, "r", encoding="utf-8") as f:
                        self._users_cache = json.load(f)
                    return self._users_cache
                except Exception as e:
                    logger.warning(f"加载用户文件失败: {e}，将重新初始化")

            # 首次运行：初始化 admin 用户
            self._users_cache = self._create_default_users()
            self._save_users(self._users_cache)
            return self._users_cache

    def _save_users(self, users: List[Dict]) -> None:
        """保存用户列表到文件"""
        users_file = Path(USERS_FILE) if isinstance(USERS_FILE, str) else USERS_FILE
        with self._file_lock:
            with open(users_file, "w", encoding="utf-8") as f:
                json.dump(users, f, ensure_ascii=False, indent=2)
        # 更新缓存
        with self._cache_lock:
            self._users_cache = users

    def _create_default_users(self) -> List[Dict]:
        """创建默认用户（admin）"""
        from .auth_service import get_password_hash

        # 获取默认管理员密码
        admin_pwd = settings.admin_password
        if not admin_pwd or _is_weak_default(admin_pwd):
            if not settings.is_production:
                admin_pwd = generate_strong_password(16)
                logger.warning(
                    "[初始化] 开发环境：管理员密码未配置或为弱密码，已生成临时强密码\n"
                    f"       用户名: {settings.admin_username}\n"
                    f"       密码: {admin_pwd}\n"
                    "       生产环境请务必配置强密码"
                )
            else:
                admin_pwd = generate_strong_password(20)
                logger.critical(
                    "[初始化] 生产环境：管理员密码未配置或为弱密码，已自动生成随机密码！\n"
                    f"       用户名: {settings.admin_username}\n"
                    f"       密码: {admin_pwd}\n"
                    "       请立即修改配置并重启服务！"
                )

        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        default_users = [
            {
                "id": 1,
                "username": settings.admin_username,
                "password_hash": get_password_hash(admin_pwd),
                "role": "admin",
                "nickname": "超级管理员",
                "email": "admin@yunxi.local",
                "avatar": None,
                "phone": None,
                "bio": "",
                "status": "active",
                "created_at": now,
                "updated_at": now,
                "last_login": None,
                "last_login_ip": None,
                "failed_login_count": 0,
                "locked_until": None,
                "timezone": "Asia/Shanghai",
                "language": "zh-CN",
                "theme": "auto",
                "preferences": {},
            }
        ]
        return default_users

    # -----------------------------------------------------------------------
    # 用户查询
    # -----------------------------------------------------------------------

    def get_user_by_username(self, username: str) -> Optional[Dict[str, Any]]:
        """按用户名查找用户

        Args:
            username: 用户名

        Returns:
            用户 dict，不存在返回 None
        """
        users = self._load_users()
        for user in users:
            if user["username"] == username:
                return user
        return None

    def get_user_by_id(self, user_id: int) -> Optional[Dict[str, Any]]:
        """按 ID 查找用户

        Args:
            user_id: 用户 ID

        Returns:
            用户 dict，不存在返回 None
        """
        users = self._load_users()
        for user in users:
            if user["id"] == user_id:
                return user
        return None

    def get_user_by_email(self, email: str) -> Optional[Dict[str, Any]]:
        """按邮箱查找用户

        Args:
            email: 邮箱

        Returns:
            用户 dict，不存在返回 None
        """
        if not email:
            return None
        users = self._load_users()
        for user in users:
            if user.get("email") and user["email"].lower() == email.lower():
                return user
        return None

    def list_users(
        self,
        page: int = 1,
        page_size: int = 20,
        keyword: Optional[str] = None,
        status: Optional[str] = None,
        role: Optional[str] = None,
        sort_by: str = "created_at",
        sort_order: str = "desc",
    ) -> Dict[str, Any]:
        """获取用户列表（分页）

        Args:
            page: 页码
            page_size: 每页条数
            keyword: 关键词搜索（用户名/昵称/邮箱）
            status: 状态过滤
            role: 角色过滤
            sort_by: 排序字段
            sort_order: 排序方向

        Returns:
            {items, total, page, page_size, total_pages}
        """
        users = self._load_users()

        # 过滤
        filtered = users
        if keyword:
            kw = keyword.lower()
            filtered = [
                u for u in filtered
                if kw in u.get("username", "").lower()
                or kw in u.get("nickname", "").lower()
                or kw in (u.get("email") or "").lower()
            ]

        if status:
            filtered = [u for u in filtered if u.get("status") == status]

        if role:
            filtered = [u for u in filtered if u.get("role") == role]

        # 排序
        reverse = sort_order.lower() == "desc"
        filtered.sort(key=lambda u: u.get(sort_by, "") or "", reverse=reverse)

        # 分页
        total = len(filtered)
        start = (page - 1) * page_size
        end = start + page_size
        items = filtered[start:end]

        # 脱敏（移除密码哈希）
        safe_items = [self._sanitize_user(u) for u in items]

        total_pages = (total + page_size - 1) // page_size if page_size > 0 else 0

        return {
            "items": safe_items,
            "total": total,
            "page": page,
            "page_size": page_size,
            "total_pages": total_pages,
        }

    def get_user_count(self) -> int:
        """获取用户总数"""
        return len(self._load_users())

    # -----------------------------------------------------------------------
    # 用户创建/更新/删除
    # -----------------------------------------------------------------------

    def create_user(
        self,
        username: str,
        password: str,
        nickname: Optional[str] = None,
        email: Optional[str] = None,
        role: str = "user",
        **extra_fields,
    ) -> Dict[str, Any]:
        """创建新用户

        Args:
            username: 用户名
            password: 明文密码
            nickname: 昵称
            email: 邮箱
            role: 角色

        Returns:
            新用户 dict（已脱敏）

        Raises:
            M8Exception: 用户名已存在等错误
        """
        from .auth_service import get_password_hash

        users = self._load_users()

        # 检查用户名是否已存在
        if self.get_user_by_username(username):
            raise M8Exception(
                code=M8ErrorCode.USER_ALREADY_EXISTS,
                message=f"用户名 {username} 已存在",
            )

        # 检查邮箱是否已存在
        if email and self.get_user_by_email(email):
            raise M8Exception(
                code=M8ErrorCode.USER_EMAIL_EXISTS,
                message=f"邮箱 {email} 已被注册",
            )

        # 生成新 ID
        new_id = max((u["id"] for u in users), default=0) + 1

        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        new_user = {
            "id": new_id,
            "username": username,
            "password_hash": get_password_hash(password),
            "nickname": nickname or username,
            "email": email,
            "avatar": extra_fields.get("avatar"),
            "phone": extra_fields.get("phone"),
            "bio": extra_fields.get("bio", ""),
            "role": role,
            "status": "active",
            "created_at": now,
            "updated_at": now,
            "last_login": None,
            "last_login_ip": None,
            "failed_login_count": 0,
            "locked_until": None,
            "timezone": extra_fields.get("timezone", "Asia/Shanghai"),
            "language": extra_fields.get("language", "zh-CN"),
            "theme": extra_fields.get("theme", "auto"),
            "preferences": {},
        }

        users.append(new_user)
        self._save_users(users)

        logger.info(f"创建用户成功: {username} (id={new_id}, role={role})")
        return self._sanitize_user(new_user)

    def update_user(self, user_id: int, **fields) -> Optional[Dict[str, Any]]:
        """更新用户信息

        Args:
            user_id: 用户 ID
            **fields: 要更新的字段

        Returns:
            更新后的用户 dict（已脱敏），不存在返回 None
        """
        users = self._load_users()

        for i, user in enumerate(users):
            if user["id"] == user_id:
                # 不允许更新的字段
                protected = {"id", "username", "password_hash", "created_at"}
                update_fields = {k: v for k, v in fields.items() if k not in protected}

                if not update_fields:
                    return self._sanitize_user(user)

                update_fields["updated_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                users[i].update(update_fields)
                self._save_users(users)

                logger.info(f"更新用户信息: id={user_id}, fields={list(update_fields.keys())}")
                return self._sanitize_user(users[i])

        return None

    def delete_user(self, user_id: int) -> bool:
        """删除用户

        Args:
            user_id: 用户 ID

        Returns:
            是否成功删除
        """
        users = self._load_users()

        # 不允许删除最后一个 admin
        admin_count = sum(1 for u in users if u.get("role") == "admin")
        target = next((u for u in users if u["id"] == user_id), None)

        if target and target.get("role") == "admin" and admin_count <= 1:
            raise M8Exception(
                code=M8ErrorCode.USER_CANNOT_DELETE_LAST_ADMIN,
                message="不能删除最后一个管理员账户",
            )

        new_users = [u for u in users if u["id"] != user_id]
        if len(new_users) == len(users):
            return False

        self._save_users(new_users)
        logger.info(f"删除用户: id={user_id}, username={target.get('username') if target else 'unknown'}")
        return True

    # -----------------------------------------------------------------------
    # 密码管理
    # -----------------------------------------------------------------------

    def update_password(self, username: str, new_password_hash: str) -> bool:
        """更新用户密码（按用户名）

        Args:
            username: 用户名
            new_password_hash: 新的密码哈希

        Returns:
            是否成功
        """
        users = self._load_users()
        for i, user in enumerate(users):
            if user["username"] == username:
                users[i]["password_hash"] = new_password_hash
                users[i]["updated_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                self._save_users(users)
                return True
        return False

    def update_password_by_id(self, user_id: int, new_password_hash: str) -> bool:
        """更新用户密码（按 ID）

        Args:
            user_id: 用户 ID
            new_password_hash: 新的密码哈希

        Returns:
            是否成功
        """
        users = self._load_users()
        for i, user in enumerate(users):
            if user["id"] == user_id:
                users[i]["password_hash"] = new_password_hash
                users[i]["updated_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                self._save_users(users)
                return True
        return False

    # -----------------------------------------------------------------------
    # 状态管理
    # -----------------------------------------------------------------------

    def update_status(self, user_id: int, status: str, reason: str = "") -> bool:
        """更新用户状态

        Args:
            user_id: 用户 ID
            status: 目标状态 (active/disabled/locked)
            reason: 操作原因

        Returns:
            是否成功
        """
        valid_statuses = {"active", "disabled", "locked"}
        if status not in valid_statuses:
            raise ValueError(f"无效的用户状态: {status}")

        users = self._load_users()
        for i, user in enumerate(users):
            if user["id"] == user_id:
                # 不允许禁用最后一个 admin
                if status != "active" and user.get("role") == "admin":
                    admin_count = sum(1 for u in users if u.get("role") == "admin" and u.get("status") == "active")
                    if admin_count <= 1:
                        raise M8Exception(
                            code=M8ErrorCode.USER_CANNOT_DISABLE_LAST_ADMIN,
                            message="不能禁用最后一个管理员账户",
                        )

                users[i]["status"] = status
                users[i]["updated_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                if status == "locked":
                    # 锁定30分钟
                    users[i]["locked_until"] = datetime.fromtimestamp(
                        time.time() + 30 * 60
                    ).strftime("%Y-%m-%d %H:%M:%S")

                self._save_users(users)
                logger.info(f"用户状态更新: id={user_id}, status={status}, reason={reason}")
                return True
        return False

    def update_role(self, user_id: int, role: str) -> bool:
        """更新用户角色

        Args:
            user_id: 用户 ID
            role: 目标角色

        Returns:
            是否成功
        """
        valid_roles = {"admin", "user", "guest"}
        if role not in valid_roles:
            raise ValueError(f"无效的用户角色: {role}")

        users = self._load_users()
        for i, user in enumerate(users):
            if user["id"] == user_id:
                # 不允许把最后一个 admin 改成非 admin
                if role != "admin" and user.get("role") == "admin":
                    admin_count = sum(1 for u in users if u.get("role") == "admin")
                    if admin_count <= 1:
                        raise M8Exception(
                            code=M8ErrorCode.USER_CANNOT_CHANGE_LAST_ADMIN,
                            message="不能修改最后一个管理员的角色",
                        )

                users[i]["role"] = role
                users[i]["updated_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                self._save_users(users)
                logger.info(f"用户角色更新: id={user_id}, role={role}")
                return True
        return False

    # -----------------------------------------------------------------------
    # 登录相关
    # -----------------------------------------------------------------------

    def update_last_login(self, username: str, ip: str = "") -> bool:
        """更新最后登录时间

        Args:
            username: 用户名
            ip: 登录 IP

        Returns:
            是否成功
        """
        users = self._load_users()
        for i, user in enumerate(users):
            if user["username"] == username:
                now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                users[i]["last_login"] = now
                users[i]["last_login_ip"] = ip
                users[i]["failed_login_count"] = 0
                users[i]["locked_until"] = None
                self._save_users(users)
                return True
        return False

    # -----------------------------------------------------------------------
    # 偏好设置
    # -----------------------------------------------------------------------

    def get_preferences(self, user_id: int) -> Dict[str, Any]:
        """获取用户偏好设置

        Args:
            user_id: 用户 ID

        Returns:
            偏好设置 dict
        """
        user = self.get_user_by_id(user_id)
        if not user:
            return {}

        return {
            "theme": user.get("theme", "auto"),
            "language": user.get("language", "zh-CN"),
            "timezone": user.get("timezone", "Asia/Shanghai"),
            "notifications": user.get("preferences", {}).get("notifications", {}),
            "ui_settings": user.get("preferences", {}).get("ui_settings", {}),
        }

    def update_preferences(self, user_id: int, preferences: Dict[str, Any]) -> bool:
        """更新用户偏好设置

        Args:
            user_id: 用户 ID
            preferences: 偏好设置

        Returns:
            是否成功
        """
        users = self._load_users()
        for i, user in enumerate(users):
            if user["id"] == user_id:
                # 顶层字段
                if "theme" in preferences:
                    users[i]["theme"] = preferences["theme"]
                if "language" in preferences:
                    users[i]["language"] = preferences["language"]
                if "timezone" in preferences:
                    users[i]["timezone"] = preferences["timezone"]

                # 嵌套的 preferences
                if "preferences" not in users[i]:
                    users[i]["preferences"] = {}

                if "notifications" in preferences:
                    users[i]["preferences"]["notifications"] = preferences["notifications"]
                if "ui_settings" in preferences:
                    users[i]["preferences"]["ui_settings"] = preferences["ui_settings"]

                users[i]["updated_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                self._save_users(users)
                return True
        return False

    # -----------------------------------------------------------------------
    # 工具方法
    # -----------------------------------------------------------------------

    def _sanitize_user(self, user: Dict[str, Any]) -> Dict[str, Any]:
        """用户信息脱敏（移除敏感字段）

        Args:
            user: 用户 dict

        Returns:
            脱敏后的用户 dict
        """
        sensitive = {"password_hash"}
        return {k: v for k, v in user.items() if k not in sensitive}

    def get_user_permissions(self, user_id: int) -> List[str]:
        """获取用户权限列表（基于角色）

        Args:
            user_id: 用户 ID

        Returns:
            权限列表
        """
        user = self.get_user_by_id(user_id)
        if not user:
            return []

        role = user.get("role", "user")
        role_permissions = {
            "admin": [
                "user:read", "user:write", "user:delete",
                "module:read", "module:write", "module:operate",
                "system:read", "system:write",
                "compute:read", "compute:write",
                "monitor:read", "monitor:write",
                "security:read", "security:write",
                "backup:read", "backup:write",
                "evolution:read", "evolution:write",
            ],
            "user": [
                "user:read",
                "module:read",
                "system:read",
                "compute:read",
                "monitor:read",
            ],
            "guest": [
                "module:read",
                "monitor:read",
            ],
        }
        return role_permissions.get(role, [])


# 辅助函数：判断是否为弱默认密码
def _is_weak_default(password: str) -> bool:
    """判断是否为弱默认密码"""
    weak_passwords = {
        "admin", "admin123", "password", "123456", "12345678",
        "yunxi", "yunxi123", "m8admin", "default",
    }
    if not password or len(password) < 8:
        return True
    return password.lower() in weak_passwords


# 全局 UserService 单例
_user_service: Optional[UserService] = None
_user_service_lock = threading.Lock()


def get_user_service() -> UserService:
    """获取 UserService 单例"""
    global _user_service
    if _user_service is None:
        with _user_service_lock:
            if _user_service is None:
                _user_service = UserService()
    return _user_service
