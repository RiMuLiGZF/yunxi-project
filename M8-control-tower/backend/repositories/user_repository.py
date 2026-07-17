"""
P2-21: 用户数据仓库（Database 版）

封装用户表的数据库 CRUD 操作。
迁移过渡期：优先读 DB，DB 为空时自动从 JSON 迁移。
"""

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import List, Optional, Dict, Any
from sqlalchemy.orm import Session

from ..models import User
from ..config import settings

logger = logging.getLogger(__name__)


def _get_users_json_path() -> Path:
    """获取 users.json 文件路径（兼容旧版）"""
    yunxi_dir = Path.home() / ".yunxi"
    yunxi_dir.mkdir(parents=True, exist_ok=True)
    return yunxi_dir / "users.json"


def _load_users_json() -> List[Dict[str, Any]]:
    """从 JSON 文件加载用户（降级兼容）"""
    json_path = _get_users_json_path()
    if json_path.exists():
        try:
            with open(json_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            # JSON 文件损坏时返回空列表，DB 为主数据源
            logger.warning("加载用户 JSON 文件失败: %s", e)
    return []


def _save_users_json(users: List[Dict[str, Any]]) -> None:
    """保存到 JSON 文件（双写兼容）"""
    json_path = _get_users_json_path()
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(users, f, ensure_ascii=False, indent=2)


def migrate_users_from_json(db: Session) -> int:
    """将 users.json 数据迁移到数据库.

    幂等操作：只在 users 表为空时执行迁移。
    迁移后 JSON 文件保留作为备份。

    Args:
        db: 数据库 session

    Returns:
        迁移的用户数量（0 表示不需要迁移）
    """
    # 检查是否已有数据
    count = db.query(User).count()
    if count > 0:
        return 0  # 已有数据，跳过

    # 从 JSON 加载
    users_json = _load_users_json()
    if not users_json:
        return 0

    migrated = 0
    for u in users_json:
        # 解析时间
        created_at = None
        if u.get("created_at"):
            try:
                created_at = datetime.strptime(u["created_at"], "%Y-%m-%d %H:%M:%S")
            except Exception:
                created_at = datetime.now()

        last_login = None
        if u.get("last_login"):
            try:
                last_login = datetime.strptime(u["last_login"], "%Y-%m-%d %H:%M:%S")
            except Exception as e:
                # 时间格式解析失败保持 None，不影响用户数据迁移
                logger.debug("解析用户 last_login 时间失败: %s", e)

        db_user = User(
            id=u.get("id"),
            username=u.get("username", ""),
            password_hash=u.get("password_hash", ""),
            role=u.get("role", "viewer"),
            nickname=u.get("nickname", ""),
            email=u.get("email", ""),
            status=u.get("status", "active"),
            created_at=created_at,
            last_login=last_login,
        )
        db.add(db_user)
        migrated += 1

    db.commit()
    print(f"[Migration] 用户表迁移完成: {migrated} 条记录")
    return migrated


class UserRepository:
    """用户数据仓库

    封装所有用户相关的数据库操作。
    自动处理 JSON→DB 迁移。
    """

    def __init__(self, db: Session):
        self.db = db
        # 首次访问时自动迁移
        self._ensure_migrated()

    def _ensure_migrated(self):
        """确保数据已迁移"""
        count = self.db.query(User).count()
        if count == 0:
            migrate_users_from_json(self.db)

    def get_all(self) -> List[User]:
        """获取所有用户"""
        return self.db.query(User).order_by(User.id).all()

    def get_by_id(self, user_id: int) -> Optional[User]:
        """按 ID 查找用户"""
        return self.db.query(User).filter(User.id == user_id).first()

    def get_by_username(self, username: str) -> Optional[User]:
        """按用户名查找用户"""
        return self.db.query(User).filter(User.username == username).first()

    def create(self, username: str, password_hash: str, role: str = "viewer",
               nickname: str = "", email: str = "", status: str = "active") -> User:
        """创建新用户"""
        user = User(
            username=username,
            password_hash=password_hash,
            role=role,
            nickname=nickname or username,
            email=email,
            status=status,
            created_at=datetime.utcnow(),
        )
        self.db.add(user)
        self.db.commit()
        self.db.refresh(user)

        # 双写 JSON（迁移过渡期）
        self._sync_to_json()

        return user

    def update(self, user_id: int, **kwargs) -> Optional[User]:
        """更新用户信息"""
        user = self.get_by_id(user_id)
        if not user:
            return None

        for key, value in kwargs.items():
            if hasattr(user, key) and value is not None:
                setattr(user, key, value)

        self.db.commit()
        self.db.refresh(user)

        # 双写 JSON
        self._sync_to_json()

        return user

    def delete(self, user_id: int) -> bool:
        """删除用户"""
        user = self.get_by_id(user_id)
        if not user:
            return False

        self.db.delete(user)
        self.db.commit()

        # 双写 JSON
        self._sync_to_json()

        return True

    def update_last_login(self, user_id: int) -> None:
        """更新最后登录时间"""
        user = self.get_by_id(user_id)
        if user:
            user.last_login = datetime.utcnow()
            self.db.commit()

    def count(self) -> int:
        """用户总数"""
        return self.db.query(User).count()

    def search(self, keyword: str = "", role: str = "", status: str = "",
               limit: int = 50, offset: int = 0) -> tuple[List[User], int]:
        """搜索用户（支持分页）

        Args:
            keyword: 用户名/昵称关键词
            role: 角色筛选
            status: 状态筛选
            limit: 每页数量
            offset: 偏移量

        Returns:
            (用户列表, 总数)
        """
        query = self.db.query(User)

        if keyword:
            query = query.filter(
                (User.username.contains(keyword)) |
                (User.nickname.contains(keyword)) |
                (User.email.contains(keyword))
            )

        if role:
            query = query.filter(User.role == role)

        if status:
            query = query.filter(User.status == status)

        total = query.count()
        users = query.order_by(User.id).offset(offset).limit(limit).all()

        return users, total

    def _sync_to_json(self):
        """同步到 JSON 文件（迁移过渡期双写）"""
        try:
            users = self.get_all()
            json_data = []
            for u in users:
                json_data.append({
                    "id": u.id,
                    "username": u.username,
                    "password_hash": u.password_hash,
                    "role": u.role,
                    "nickname": u.nickname,
                    "email": u.email,
                    "status": u.status,
                    "created_at": u.created_at.strftime("%Y-%m-%d %H:%M:%S") if u.created_at else None,
                    "last_login": u.last_login.strftime("%Y-%m-%d %H:%M:%S") if u.last_login else None,
                })
            _save_users_json(json_data)
        except Exception as e:
            print(f"[UserRepository] JSON 同步失败: {e}")
