"""
M8 配置中心服务 (ConfigCenterService)

配置中心核心服务，提供：
1. 配置 CRUD（带层级继承）
2. 配置版本管理（历史查询、回滚、对比）
3. 配置变更审计
4. 配置灰度发布
5. 配置校验（JSON Schema）
6. 配置模板导入导出

配置分层模型（优先级从高到低）：
    instance > env > module > global

即获取配置时，优先查找实例级配置，没有则查找环境级，
再没有查找模块级，最后使用全局配置。
"""

from __future__ import annotations

import sys
import json
import hashlib
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from datetime import datetime
from copy import deepcopy

# 将项目根目录加入 path
_project_root = Path(__file__).parent.parent.parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

from sqlalchemy.orm import Session
from sqlalchemy import and_, or_

from ..models.config_center import (
    ConfigItem, ConfigVersion, ConfigAuditLog, ConfigSchema,
)
from ..models.base import SessionLocal

# 加密支持（可选，基于 crypto 模块）
try:
    from ..crypto import encrypt_value, decrypt_value  # type: ignore
    _HAS_CRYPTO = True
except ImportError:
    try:
        from cryptography.fernet import Fernet
        import os
        _fernet_key = os.environ.get("CONFIG_CENTER_MASTER_KEY", "")
        if _fernet_key:
            _fernet = Fernet(_fernet_key.encode())
            _HAS_CRYPTO = True
        else:
            _HAS_CRYPTO = False
            _fernet = None

        def encrypt_value(value: str) -> str:
            if not _fernet:
                return value
            return _fernet.encrypt(value.encode()).decode()

        def decrypt_value(value: str) -> str:
            if not _fernet:
                return value
            return _fernet.decrypt(value.encode()).decode()
    except ImportError:
        _HAS_CRYPTO = False

        def encrypt_value(value: str) -> str:
            return value

        def decrypt_value(value: str) -> str:
            return value


logger = logging.getLogger("m8.config_center")

# 有效的作用域列表（优先级从低到高）
SCOPE_PRIORITY = ["global", "module", "env", "instance"]

# 有效的配置类型
VALID_CONFIG_TYPES = {"string", "int", "float", "bool", "json", "list"}


# ===========================================================================
# 辅助函数
# ===========================================================================

def _sanitize_value(value: Any, is_secret: bool) -> Any:
    """敏感配置值脱敏"""
    if is_secret and value is not None:
        return "***SECRET***"
    return value


def _infer_config_type(value: Any) -> str:
    """根据值推断配置类型"""
    if isinstance(value, bool):
        return "bool"
    elif isinstance(value, int):
        return "int"
    elif isinstance(value, float):
        return "float"
    elif isinstance(value, list):
        return "list"
    elif isinstance(value, dict):
        return "json"
    elif isinstance(value, str):
        return "string"
    return "json"


def _validate_type(value: Any, config_type: str) -> Tuple[bool, str]:
    """验证值是否符合配置类型"""
    if config_type == "string":
        if not isinstance(value, str):
            return False, f"值类型应为 string，实际为 {type(value).__name__}"
    elif config_type == "int":
        if not isinstance(value, int) or isinstance(value, bool):
            return False, f"值类型应为 int，实际为 {type(value).__name__}"
    elif config_type == "float":
        if not isinstance(value, (int, float)) or isinstance(value, bool):
            return False, f"值类型应为 float，实际为 {type(value).__name__}"
    elif config_type == "bool":
        if not isinstance(value, bool):
            return False, f"值类型应为 bool，实际为 {type(value).__name__}"
    elif config_type == "list":
        if not isinstance(value, list):
            return False, f"值类型应为 list，实际为 {type(value).__name__}"
    elif config_type == "json":
        if not isinstance(value, (dict, list, str, int, float, bool)):
            return False, f"值类型应为 json，实际为 {type(value).__name__}"
    else:
        return False, f"未知的配置类型: {config_type}"
    return True, ""


def _validate_scope(scope: str, module_name: str = None, env_name: str = None,
                    instance_id: str = None) -> Tuple[bool, str]:
    """验证作用域参数的合法性"""
    if scope not in SCOPE_PRIORITY:
        return False, f"无效的作用域: {scope}，有效值: {SCOPE_PRIORITY}"

    if scope == "global":
        if module_name or env_name or instance_id:
            return False, "global 作用域不需要 module_name/env_name/instance_id"
    elif scope == "module":
        if not module_name:
            return False, "module 作用域需要 module_name"
        if env_name or instance_id:
            return False, "module 作用域不需要 env_name/instance_id"
    elif scope == "env":
        if not module_name or not env_name:
            return False, "env 作用域需要 module_name 和 env_name"
        if instance_id:
            return False, "env 作用域不需要 instance_id"
    elif scope == "instance":
        if not module_name or not env_name or not instance_id:
            return False, "instance 作用域需要 module_name、env_name 和 instance_id"

    return True, ""


# ===========================================================================
# ConfigCenterService - 配置中心核心服务
# ===========================================================================

class ConfigCenterService:
    """配置中心服务

    提供配置的 CRUD、版本管理、审计、灰度发布、校验等功能。
    所有方法均接受一个 db session 参数，便于事务控制。
    """

    def __init__(self, db: Optional[Session] = None):
        self._db = db

    def _get_db(self) -> Session:
        """获取数据库会话"""
        if self._db:
            return self._db
        return SessionLocal()

    # ============================================================
    # 1. 配置 CRUD
    # ============================================================

    def get_config(
        self,
        key: str,
        scope: str = "global",
        module_name: Optional[str] = None,
        env_name: Optional[str] = None,
        instance_id: Optional[str] = None,
        resolve_inheritance: bool = True,
        include_secret: bool = False,
    ) -> Optional[Dict[str, Any]]:
        """获取配置

        Args:
            key: 配置键
            scope: 目标作用域
            module_name: 模块名
            env_name: 环境名
            instance_id: 实例ID
            resolve_inheritance: 是否解析层级继承（从高优先级到低优先级查找）
            include_secret: 是否返回敏感配置的明文值

        Returns:
            配置项字典，未找到返回 None
        """
        db = self._get_db()
        try:
            if not resolve_inheritance:
                # 直接查找指定作用域的配置
                item = self._find_item(db, key, scope, module_name, env_name, instance_id)
                if item:
                    return self._item_to_result(item, include_secret)
                return None

            # 层级继承：从高优先级到低优先级查找
            # instance > env > module > global
            search_scopes = []
            if scope == "instance" and instance_id:
                search_scopes.append(("instance", module_name, env_name, instance_id))
            if scope in ("instance", "env") and env_name:
                search_scopes.append(("env", module_name, env_name, None))
            if scope in ("instance", "env", "module") and module_name:
                search_scopes.append(("module", module_name, None, None))
            search_scopes.append(("global", None, None, None))

            for s_scope, s_mod, s_env, s_inst in search_scopes:
                item = self._find_item(db, key, s_scope, s_mod, s_env, s_inst)
                if item:
                    # 灰度判断：如果是灰度配置，检查是否应该返回灰度值
                    if item.is_canary and instance_id:
                        if self._should_use_canary(item, instance_id):
                            return self._item_to_result(item, include_secret)
                        # 不命中灰度，继续往下找非灰度版本
                        continue
                    return self._item_to_result(item, include_secret)

            return None
        finally:
            if not self._db:
                db.close()

    def set_config(
        self,
        key: str,
        value: Any,
        scope: str = "global",
        module_name: Optional[str] = None,
        env_name: Optional[str] = None,
        instance_id: Optional[str] = None,
        config_type: Optional[str] = None,
        description: str = "",
        is_secret: bool = False,
        operator: str = "system",
        reason: str = "",
        schema_name: Optional[str] = None,
    ) -> Dict[str, Any]:
        """设置配置（新增或更新）

        Args:
            key: 配置键
            value: 配置值
            scope: 作用域
            module_name: 模块名
            env_name: 环境名
            instance_id: 实例ID
            config_type: 配置类型，None 时自动推断
            description: 配置描述
            is_secret: 是否为敏感配置
            operator: 操作人
            reason: 变更原因
            schema_name: 关联的 Schema 名称（用于校验）

        Returns:
            设置后的配置项字典
        """
        db = self._get_db()
        try:
            # 验证作用域
            valid, msg = _validate_scope(scope, module_name, env_name, instance_id)
            if not valid:
                raise ValueError(msg)

            # 推断类型
            if config_type is None:
                config_type = _infer_config_type(value)

            if config_type not in VALID_CONFIG_TYPES:
                raise ValueError(f"无效的配置类型: {config_type}")

            # 类型校验
            type_valid, type_msg = _validate_type(value, config_type)
            if not type_valid:
                raise ValueError(type_msg)

            # Schema 校验
            if schema_name:
                schema_valid, schema_msg = self._validate_against_schema(
                    db, key, value, schema_name
                )
                if not schema_valid:
                    raise ValueError(f"Schema 校验失败: {schema_msg}")

            # 加密敏感配置
            stored_value = value
            if is_secret and _HAS_CRYPTO and value is not None:
                stored_value = encrypt_value(json.dumps(value) if isinstance(value, (dict, list)) else str(value))

            # 查找现有配置
            existing = self._find_item(db, key, scope, module_name, env_name, instance_id)

            if existing:
                # 更新
                old_value = existing.config_value
                old_version = existing.version

                existing.config_value = stored_value
                existing.config_type = config_type
                existing.description = description
                existing.is_secret = is_secret
                existing.version = existing.version + 1
                existing.updated_by = operator

                db.flush()

                # 记录版本
                self._create_version(db, existing, old_value, reason, operator)

                # 记录审计
                self._create_audit(
                    db, action="update",
                    key=key, scope=scope,
                    module_name=module_name, env_name=env_name, instance_id=instance_id,
                    old_value=_sanitize_value(old_value, is_secret),
                    new_value=_sanitize_value(stored_value, is_secret),
                    old_version=old_version,
                    new_version=existing.version,
                    operator=operator, reason=reason,
                )

                result = self._item_to_result(existing, include_secret=False)
            else:
                # 新建
                item = ConfigItem(
                    config_key=key,
                    config_value=stored_value,
                    config_type=config_type,
                    scope=scope,
                    module_name=module_name,
                    env_name=env_name,
                    instance_id=instance_id,
                    description=description,
                    is_secret=is_secret,
                    version=1,
                    updated_by=operator,
                )
                db.add(item)
                db.flush()

                # 记录版本
                self._create_version(db, item, None, reason, operator)

                # 记录审计
                self._create_audit(
                    db, action="create",
                    key=key, scope=scope,
                    module_name=module_name, env_name=env_name, instance_id=instance_id,
                    old_value=None,
                    new_value=_sanitize_value(stored_value, is_secret),
                    old_version=None,
                    new_version=1,
                    operator=operator, reason=reason,
                )

                result = self._item_to_result(item, include_secret=False)

            db.commit()
            return result
        except Exception:
            db.rollback()
            raise
        finally:
            if not self._db:
                db.close()

    def delete_config(
        self,
        key: str,
        scope: str = "global",
        module_name: Optional[str] = None,
        env_name: Optional[str] = None,
        instance_id: Optional[str] = None,
        operator: str = "system",
        reason: str = "",
    ) -> bool:
        """删除配置

        Args:
            key: 配置键
            scope: 作用域
            module_name: 模块名
            env_name: 环境名
            instance_id: 实例ID
            operator: 操作人
            reason: 删除原因

        Returns:
            是否删除成功
        """
        db = self._get_db()
        try:
            valid, msg = _validate_scope(scope, module_name, env_name, instance_id)
            if not valid:
                raise ValueError(msg)

            item = self._find_item(db, key, scope, module_name, env_name, instance_id)
            if not item:
                return False

            old_value = item.config_value
            old_version = item.version
            is_secret = item.is_secret

            db.delete(item)
            db.flush()

            # 记录审计
            self._create_audit(
                db, action="delete",
                key=key, scope=scope,
                module_name=module_name, env_name=env_name, instance_id=instance_id,
                old_value=_sanitize_value(old_value, is_secret),
                new_value=None,
                old_version=old_version,
                new_version=None,
                operator=operator, reason=reason,
            )

            db.commit()
            return True
        except Exception:
            db.rollback()
            raise
        finally:
            if not self._db:
                db.close()

    def list_configs(
        self,
        scope: Optional[str] = None,
        module_name: Optional[str] = None,
        env_name: Optional[str] = None,
        instance_id: Optional[str] = None,
        prefix: Optional[str] = None,
        include_secret: bool = False,
        page: int = 1,
        page_size: int = 50,
    ) -> Dict[str, Any]:
        """列出配置

        Args:
            scope: 作用域过滤
            module_name: 模块名过滤
            env_name: 环境名过滤
            instance_id: 实例ID过滤
            prefix: 配置键前缀过滤
            include_secret: 是否包含敏感配置明文
            page: 页码
            page_size: 每页条数

        Returns:
            分页结果 {items, total, page, page_size}
        """
        db = self._get_db()
        try:
            query = db.query(ConfigItem)

            if scope:
                query = query.filter(ConfigItem.scope == scope)
            if module_name:
                query = query.filter(
                    or_(ConfigItem.module_name == module_name,
                        ConfigItem.module_name.is_(None))
                )
            if env_name:
                query = query.filter(
                    or_(ConfigItem.env_name == env_name,
                        ConfigItem.env_name.is_(None))
                )
            if instance_id:
                query = query.filter(
                    or_(ConfigItem.instance_id == instance_id,
                        ConfigItem.instance_id.is_(None))
                )
            if prefix:
                query = query.filter(ConfigItem.config_key.like(f"{prefix}%"))

            total = query.count()
            items = (
                query.order_by(ConfigItem.config_key.asc(), ConfigItem.scope.asc())
                .offset((page - 1) * page_size)
                .limit(page_size)
                .all()
            )

            return {
                "items": [self._item_to_result(item, include_secret) for item in items],
                "total": total,
                "page": page,
                "page_size": page_size,
            }
        finally:
            if not self._db:
                db.close()

    def batch_get(
        self,
        keys: List[str],
        scope: str = "global",
        module_name: Optional[str] = None,
        env_name: Optional[str] = None,
        instance_id: Optional[str] = None,
        resolve_inheritance: bool = True,
    ) -> Dict[str, Any]:
        """批量获取配置

        Args:
            keys: 配置键列表
            scope: 作用域
            module_name: 模块名
            env_name: 环境名
            instance_id: 实例ID
            resolve_inheritance: 是否解析层级继承

        Returns:
            {key: value} 字典，未找到的 key 不包含在结果中
        """
        result = {}
        for key in keys:
            config = self.get_config(
                key, scope, module_name, env_name, instance_id,
                resolve_inheritance=resolve_inheritance, include_secret=True,
            )
            if config:
                result[key] = config["config_value"]
        return result

    def batch_set(
        self,
        items: List[Dict[str, Any]],
        scope: str = "global",
        module_name: Optional[str] = None,
        env_name: Optional[str] = None,
        instance_id: Optional[str] = None,
        operator: str = "system",
        reason: str = "",
    ) -> Dict[str, Any]:
        """批量设置配置

        Args:
            items: 配置项列表，每项包含 key, value, [config_type], [description], [is_secret]
            scope: 作用域
            module_name: 模块名
            env_name: 环境名
            instance_id: 实例ID
            operator: 操作人
            reason: 变更原因

        Returns:
            {success_count, failed_count, failed_items, results}
        """
        db = self._get_db()
        try:
            success_count = 0
            failed_count = 0
            failed_items = []
            results = []

            for item in items:
                try:
                    result = self.set_config(
                        key=item["key"],
                        value=item["value"],
                        scope=item.get("scope", scope),
                        module_name=item.get("module_name", module_name),
                        env_name=item.get("env_name", env_name),
                        instance_id=item.get("instance_id", instance_id),
                        config_type=item.get("config_type"),
                        description=item.get("description", ""),
                        is_secret=item.get("is_secret", False),
                        operator=operator,
                        reason=reason,
                    )
                    success_count += 1
                    results.append(result)
                except Exception as e:
                    failed_count += 1
                    failed_items.append({
                        "key": item.get("key", ""),
                        "error": str(e),
                    })

            return {
                "success_count": success_count,
                "failed_count": failed_count,
                "failed_items": failed_items,
                "results": results,
            }
        finally:
            if not self._db:
                db.close()

    # ============================================================
    # 2. 配置版本管理
    # ============================================================

    def list_versions(
        self,
        key: str,
        scope: str = "global",
        module_name: Optional[str] = None,
        env_name: Optional[str] = None,
        instance_id: Optional[str] = None,
        page: int = 1,
        page_size: int = 20,
    ) -> Dict[str, Any]:
        """查询配置版本历史

        Args:
            key: 配置键
            scope: 作用域
            module_name: 模块名
            env_name: 环境名
            instance_id: 实例ID
            page: 页码
            page_size: 每页条数

        Returns:
            分页版本列表
        """
        db = self._get_db()
        try:
            query = db.query(ConfigVersion).filter(
                ConfigVersion.config_key == key,
                ConfigVersion.scope == scope,
            )
            if module_name:
                query = query.filter(ConfigVersion.module_name == module_name)
            else:
                query = query.filter(ConfigVersion.module_name.is_(None))
            if env_name:
                query = query.filter(ConfigVersion.env_name == env_name)
            else:
                query = query.filter(ConfigVersion.env_name.is_(None))
            if instance_id:
                query = query.filter(ConfigVersion.instance_id == instance_id)
            else:
                query = query.filter(ConfigVersion.instance_id.is_(None))

            total = query.count()
            versions = (
                query.order_by(ConfigVersion.version.desc())
                .offset((page - 1) * page_size)
                .limit(page_size)
                .all()
            )

            return {
                "items": [v.to_dict() for v in versions],
                "total": total,
                "page": page,
                "page_size": page_size,
            }
        finally:
            if not self._db:
                db.close()

    def rollback_config(
        self,
        key: str,
        target_version: int,
        scope: str = "global",
        module_name: Optional[str] = None,
        env_name: Optional[str] = None,
        instance_id: Optional[str] = None,
        operator: str = "system",
        reason: str = "",
    ) -> Dict[str, Any]:
        """回滚配置到指定版本

        Args:
            key: 配置键
            target_version: 目标版本号
            scope: 作用域
            module_name: 模块名
            env_name: 环境名
            instance_id: 实例ID
            operator: 操作人
            reason: 回滚原因

        Returns:
            回滚后的配置项
        """
        db = self._get_db()
        try:
            # 查找目标版本
            version_record = (
                db.query(ConfigVersion)
                .filter(
                    ConfigVersion.config_key == key,
                    ConfigVersion.scope == scope,
                    ConfigVersion.version == target_version,
                )
                .first()
            )
            if not version_record:
                raise ValueError(f"版本 {target_version} 不存在")

            # 查找当前配置
            current = self._find_item(db, key, scope, module_name, env_name, instance_id)
            if not current:
                raise ValueError("当前配置不存在")

            old_value = current.config_value
            old_version = current.version

            # 回滚值
            current.config_value = version_record.config_value
            current.config_type = version_record.config_type
            current.description = version_record.description
            current.is_secret = version_record.is_secret
            current.version = current.version + 1
            current.updated_by = operator

            db.flush()

            # 创建新版本记录
            self._create_version(
                db, current, old_value,
                reason=f"rollback to v{target_version}: {reason}",
                operator=operator,
            )

            # 记录审计
            self._create_audit(
                db, action="rollback",
                key=key, scope=scope,
                module_name=module_name, env_name=env_name, instance_id=instance_id,
                old_value=_sanitize_value(old_value, current.is_secret),
                new_value=_sanitize_value(current.config_value, current.is_secret),
                old_version=old_version,
                new_version=current.version,
                operator=operator,
                reason=f"回滚到版本 {target_version}: {reason}",
                extra={"target_version": target_version},
            )

            db.commit()
            return self._item_to_result(current, include_secret=False)
        except Exception:
            db.rollback()
            raise
        finally:
            if not self._db:
                db.close()

    def diff_versions(
        self,
        key: str,
        version_a: int,
        version_b: int,
        scope: str = "global",
        module_name: Optional[str] = None,
        env_name: Optional[str] = None,
        instance_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """对比两个版本的差异

        Args:
            key: 配置键
            version_a: 版本 A
            version_b: 版本 B
            scope: 作用域
            module_name: 模块名
            env_name: 环境名
            instance_id: 实例ID

        Returns:
            差异信息
        """
        db = self._get_db()
        try:
            va = (
                db.query(ConfigVersion)
                .filter(
                    ConfigVersion.config_key == key,
                    ConfigVersion.scope == scope,
                    ConfigVersion.version == version_a,
                )
                .first()
            )
            vb = (
                db.query(ConfigVersion)
                .filter(
                    ConfigVersion.config_key == key,
                    ConfigVersion.scope == scope,
                    ConfigVersion.version == version_b,
                )
                .first()
            )

            if not va or not vb:
                raise ValueError("指定的版本不存在")

            is_secret = va.is_secret or vb.is_secret

            val_a = va.config_value if not is_secret else "***SECRET***"
            val_b = vb.config_value if not is_secret else "***SECRET***"

            changed = val_a != val_b

            return {
                "config_key": key,
                "scope": scope,
                "version_a": version_a,
                "version_b": version_b,
                "changed": changed,
                "value_a": val_a,
                "value_b": val_b,
                "type_a": va.config_type,
                "type_b": vb.config_type,
                "changed_at_a": va.changed_at.isoformat() if va.changed_at else None,
                "changed_at_b": vb.changed_at.isoformat() if vb.changed_at else None,
                "changed_by_a": va.changed_by,
                "changed_by_b": vb.changed_by,
            }
        finally:
            if not self._db:
                db.close()

    # ============================================================
    # 3. 配置变更审计
    # ============================================================

    def list_audit_logs(
        self,
        key: Optional[str] = None,
        scope: Optional[str] = None,
        module_name: Optional[str] = None,
        action: Optional[str] = None,
        operator: Optional[str] = None,
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None,
        page: int = 1,
        page_size: int = 50,
    ) -> Dict[str, Any]:
        """查询配置审计日志

        Args:
            key: 配置键过滤
            scope: 作用域过滤
            module_name: 模块名过滤
            action: 操作类型过滤
            operator: 操作人过滤
            start_time: 开始时间
            end_time: 结束时间
            page: 页码
            page_size: 每页条数

        Returns:
            分页审计日志
        """
        db = self._get_db()
        try:
            query = db.query(ConfigAuditLog)

            if key:
                query = query.filter(ConfigAuditLog.config_key == key)
            if scope:
                query = query.filter(ConfigAuditLog.scope == scope)
            if module_name:
                query = query.filter(ConfigAuditLog.module_name == module_name)
            if action:
                query = query.filter(ConfigAuditLog.action == action)
            if operator:
                query = query.filter(ConfigAuditLog.operator == operator)
            if start_time:
                query = query.filter(ConfigAuditLog.created_at >= start_time)
            if end_time:
                query = query.filter(ConfigAuditLog.created_at <= end_time)

            total = query.count()
            logs = (
                query.order_by(ConfigAuditLog.created_at.desc())
                .offset((page - 1) * page_size)
                .limit(page_size)
                .all()
            )

            return {
                "items": [log.to_dict() for log in logs],
                "total": total,
                "page": page,
                "page_size": page_size,
            }
        finally:
            if not self._db:
                db.close()

    # ============================================================
    # 4. 配置灰度发布
    # ============================================================

    def start_canary(
        self,
        key: str,
        canary_value: Any,
        scope: str = "module",
        module_name: Optional[str] = None,
        env_name: Optional[str] = None,
        canary_percent: Optional[int] = None,
        canary_instances: Optional[List[str]] = None,
        operator: str = "system",
        reason: str = "",
    ) -> Dict[str, Any]:
        """启动灰度发布

        在指定 scope 下创建灰度配置。
        支持两种灰度方式：按百分比、按实例列表。

        Args:
            key: 配置键
            canary_value: 灰度值
            scope: 灰度作用域（应为 env 或 module）
            module_name: 模块名
            env_name: 环境名
            canary_percent: 灰度百分比（0-100），与 canary_instances 二选一
            canary_instances: 灰度实例列表，与 canary_percent 二选一
            operator: 操作人
            reason: 灰度原因

        Returns:
            灰度配置项
        """
        if canary_percent is None and canary_instances is None:
            raise ValueError("canary_percent 和 canary_instances 必须指定一个")
        if canary_percent is not None and not (0 < canary_percent < 100):
            raise ValueError("canary_percent 必须在 1-99 之间")

        db = self._get_db()
        try:
            # 检查是否已有灰度配置
            existing_canary = (
                db.query(ConfigItem)
                .filter(
                    ConfigItem.config_key == key,
                    ConfigItem.scope == scope,
                    ConfigItem.is_canary == True,  # noqa: E712
                )
                .first()
            )
            if existing_canary:
                raise ValueError("该配置已有进行中的灰度发布")

            # 创建灰度配置项（在 instance 级别？不，在原 scope 下加 is_canary 标记）
            # 实际上，灰度是同一个 scope 下的特殊版本，通过 is_canary 标记
            config_type = _infer_config_type(canary_value)

            item = ConfigItem(
                config_key=key,
                config_value=canary_value,
                config_type=config_type,
                scope=scope,
                module_name=module_name,
                env_name=env_name,
                instance_id=None,
                description=f"[灰度] {reason}",
                is_secret=False,
                version=1,
                is_canary=True,
                canary_percent=canary_percent,
                canary_instances=canary_instances,
                updated_by=operator,
            )
            db.add(item)
            db.flush()

            # 记录版本
            self._create_version(db, item, None, reason, operator)

            # 记录审计
            self._create_audit(
                db, action="canary_start",
                key=key, scope=scope,
                module_name=module_name, env_name=env_name, instance_id=None,
                old_value=None,
                new_value=canary_value,
                operator=operator, reason=reason,
                extra={
                    "canary_percent": canary_percent,
                    "canary_instances": canary_instances,
                },
            )

            db.commit()
            return self._item_to_result(item, include_secret=False)
        except Exception:
            db.rollback()
            raise
        finally:
            if not self._db:
                db.close()

    def rollback_canary(
        self,
        key: str,
        scope: str = "module",
        module_name: Optional[str] = None,
        env_name: Optional[str] = None,
        operator: str = "system",
        reason: str = "",
    ) -> bool:
        """回滚灰度发布（取消灰度）

        Args:
            key: 配置键
            scope: 作用域
            module_name: 模块名
            env_name: 环境名
            operator: 操作人
            reason: 回滚原因

        Returns:
            是否成功
        """
        db = self._get_db()
        try:
            canary_item = (
                db.query(ConfigItem)
                .filter(
                    ConfigItem.config_key == key,
                    ConfigItem.scope == scope,
                    ConfigItem.is_canary == True,  # noqa: E712
                )
                .first()
            )
            if not canary_item:
                return False

            db.delete(canary_item)
            db.flush()

            self._create_audit(
                db, action="canary_rollback",
                key=key, scope=scope,
                module_name=module_name, env_name=env_name, instance_id=None,
                old_value=canary_item.config_value,
                new_value=None,
                operator=operator, reason=reason,
            )

            db.commit()
            return True
        except Exception:
            db.rollback()
            raise
        finally:
            if not self._db:
                db.close()

    def promote_canary(
        self,
        key: str,
        scope: str = "module",
        module_name: Optional[str] = None,
        env_name: Optional[str] = None,
        operator: str = "system",
        reason: str = "",
    ) -> Dict[str, Any]:
        """灰度转正（全量发布）

        将灰度值升级为正式值，取消灰度标记。

        Args:
            key: 配置键
            scope: 作用域
            module_name: 模块名
            env_name: 环境名
            operator: 操作人
            reason: 转正原因

        Returns:
            转正后的配置项
        """
        db = self._get_db()
        try:
            canary_item = (
                db.query(ConfigItem)
                .filter(
                    ConfigItem.config_key == key,
                    ConfigItem.scope == scope,
                    ConfigItem.is_canary == True,  # noqa: E712
                )
                .first()
            )
            if not canary_item:
                raise ValueError("没有进行中的灰度发布")

            # 找到或创建正式配置
            normal_item = self._find_item(
                db, key, scope, module_name, env_name, None
            )

            if normal_item:
                # 更新正式配置为灰度值
                old_value = normal_item.config_value
                old_version = normal_item.version
                normal_item.config_value = canary_item.config_value
                normal_item.config_type = canary_item.config_type
                normal_item.version = normal_item.version + 1
                normal_item.updated_by = operator
                db.flush()

                self._create_version(
                    db, normal_item, old_value,
                    reason=f"canary promote: {reason}",
                    operator=operator,
                )
            else:
                # 创建新的正式配置
                normal_item = ConfigItem(
                    config_key=key,
                    config_value=canary_item.config_value,
                    config_type=canary_item.config_type,
                    scope=scope,
                    module_name=module_name,
                    env_name=env_name,
                    instance_id=None,
                    description=canary_item.description.replace("[灰度] ", ""),
                    is_secret=canary_item.is_secret,
                    version=1,
                    updated_by=operator,
                )
                db.add(normal_item)
                db.flush()

                self._create_version(db, normal_item, None, reason, operator)

            # 删除灰度配置
            db.delete(canary_item)
            db.flush()

            self._create_audit(
                db, action="canary_promote",
                key=key, scope=scope,
                module_name=module_name, env_name=env_name, instance_id=None,
                old_value=None,
                new_value=canary_item.config_value,
                operator=operator,
                reason=f"灰度转正: {reason}",
            )

            db.commit()
            return self._item_to_result(normal_item, include_secret=False)
        except Exception:
            db.rollback()
            raise
        finally:
            if not self._db:
                db.close()

    # ============================================================
    # 5. 配置校验（Schema）
    # ============================================================

    def create_schema(
        self,
        schema_name: str,
        schema_json: Dict[str, Any],
        module_name: Optional[str] = None,
        description: str = "",
        operator: str = "system",
    ) -> Dict[str, Any]:
        """创建配置 Schema

        Args:
            schema_name: Schema 名称
            schema_json: JSON Schema 定义
            module_name: 所属模块
            description: 描述
            operator: 创建人

        Returns:
            创建的 Schema
        """
        db = self._get_db()
        try:
            existing = (
                db.query(ConfigSchema)
                .filter(ConfigSchema.schema_name == schema_name)
                .first()
            )
            if existing:
                raise ValueError(f"Schema '{schema_name}' 已存在")

            schema = ConfigSchema(
                schema_name=schema_name,
                schema_json=schema_json,
                module_name=module_name,
                description=description,
                created_by=operator,
            )
            db.add(schema)
            db.commit()
            db.refresh(schema)
            return schema.to_dict()
        except Exception:
            db.rollback()
            raise
        finally:
            if not self._db:
                db.close()

    def list_schemas(
        self,
        module_name: Optional[str] = None,
        is_active: Optional[bool] = None,
        page: int = 1,
        page_size: int = 50,
    ) -> Dict[str, Any]:
        """列出配置 Schema

        Args:
            module_name: 模块过滤
            is_active: 是否只列出激活的
            page: 页码
            page_size: 每页条数

        Returns:
            分页 Schema 列表
        """
        db = self._get_db()
        try:
            query = db.query(ConfigSchema)
            if module_name:
                query = query.filter(ConfigSchema.module_name == module_name)
            if is_active is not None:
                query = query.filter(ConfigSchema.is_active == is_active)

            total = query.count()
            schemas = (
                query.order_by(ConfigSchema.schema_name.asc())
                .offset((page - 1) * page_size)
                .limit(page_size)
                .all()
            )

            return {
                "items": [s.to_dict() for s in schemas],
                "total": total,
                "page": page,
                "page_size": page_size,
            }
        finally:
            if not self._db:
                db.close()

    def validate_config(
        self,
        key: str,
        value: Any,
        schema_name: str,
    ) -> Tuple[bool, str]:
        """校验配置值是否符合 Schema

        Args:
            key: 配置键
            value: 配置值
            schema_name: Schema 名称

        Returns:
            (是否通过, 错误信息)
        """
        db = self._get_db()
        try:
            return self._validate_against_schema(db, key, value, schema_name)
        finally:
            if not self._db:
                db.close()

    # ============================================================
    # 6. 配置模板（导入导出）
    # ============================================================

    def export_configs(
        self,
        scope: Optional[str] = None,
        module_name: Optional[str] = None,
        env_name: Optional[str] = None,
        prefix: Optional[str] = None,
        include_secret: bool = False,
    ) -> Dict[str, Any]:
        """导出配置为 JSON 格式

        Args:
            scope: 作用域过滤
            module_name: 模块名过滤
            env_name: 环境名过滤
            prefix: 键前缀过滤
            include_secret: 是否导出敏感配置明文

        Returns:
            导出数据
        """
        db = self._get_db()
        try:
            query = db.query(ConfigItem)
            if scope:
                query = query.filter(ConfigItem.scope == scope)
            if module_name:
                query = query.filter(ConfigItem.module_name == module_name)
            if env_name:
                query = query.filter(ConfigItem.env_name == env_name)
            if prefix:
                query = query.filter(ConfigItem.config_key.like(f"{prefix}%"))

            items = query.order_by(ConfigItem.config_key.asc()).all()

            configs = []
            for item in items:
                d = self._item_to_result(item, include_secret)
                configs.append({
                    "config_key": d["config_key"],
                    "config_value": d["config_value"],
                    "config_type": d["config_type"],
                    "scope": d["scope"],
                    "module_name": d["module_name"],
                    "env_name": d["env_name"],
                    "instance_id": d["instance_id"],
                    "description": d["description"],
                    "is_secret": d["is_secret"],
                })

            return {
                "version": "1.0",
                "exported_at": datetime.utcnow().isoformat(),
                "count": len(configs),
                "configs": configs,
            }
        finally:
            if not self._db:
                db.close()

    def import_configs(
        self,
        data: Dict[str, Any],
        operator: str = "system",
        overwrite: bool = True,
    ) -> Dict[str, Any]:
        """导入配置

        Args:
            data: 导出格式的配置数据
            operator: 操作人
            overwrite: 是否覆盖已有配置

        Returns:
            导入结果 {imported, skipped, failed}
        """
        db = self._get_db()
        try:
            imported = 0
            skipped = 0
            failed = 0
            failed_items = []

            configs = data.get("configs", [])
            for cfg in configs:
                try:
                    existing = self._find_item(
                        db,
                        cfg["config_key"],
                        cfg.get("scope", "global"),
                        cfg.get("module_name"),
                        cfg.get("env_name"),
                        cfg.get("instance_id"),
                    )
                    if existing and not overwrite:
                        skipped += 1
                        continue

                    self.set_config(
                        key=cfg["config_key"],
                        value=cfg["config_value"],
                        scope=cfg.get("scope", "global"),
                        module_name=cfg.get("module_name"),
                        env_name=cfg.get("env_name"),
                        instance_id=cfg.get("instance_id"),
                        config_type=cfg.get("config_type"),
                        description=cfg.get("description", ""),
                        is_secret=cfg.get("is_secret", False),
                        operator=operator,
                        reason="import",
                    )
                    imported += 1
                except Exception as e:
                    failed += 1
                    failed_items.append({
                        "key": cfg.get("config_key", ""),
                        "error": str(e),
                    })

            return {
                "imported": imported,
                "skipped": skipped,
                "failed": failed,
                "failed_items": failed_items,
            }
        finally:
            if not self._db:
                db.close()

    # ============================================================
    # 7. 健康检查
    # ============================================================

    def health_check(self) -> Dict[str, Any]:
        """配置中心健康检查"""
        db = self._get_db()
        try:
            # 简单查询测试
            count = db.query(ConfigItem).count()
            return {
                "status": "healthy",
                "config_count": count,
                "crypto_enabled": _HAS_CRYPTO,
            }
        except Exception as e:
            return {
                "status": "unhealthy",
                "error": str(e),
                "crypto_enabled": _HAS_CRYPTO,
            }
        finally:
            if not self._db:
                db.close()

    # ============================================================
    # 8. 变更监听（长轮询支持）
    # ============================================================

    def get_changes_since(
        self,
        since_version: int,
        scope: str = "module",
        module_name: Optional[str] = None,
        env_name: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """获取自指定版本以来的配置变更

        用于长轮询模式的配置监听。

        Args:
            since_version: 客户端已知的最新版本号（这里用审计日志 ID 代替）
            scope: 作用域
            module_name: 模块名
            env_name: 环境名

        Returns:
            变更列表
        """
        db = self._get_db()
        try:
            query = db.query(ConfigAuditLog).filter(
                ConfigAuditLog.id > since_version,
                ConfigAuditLog.scope == scope,
            )
            if module_name:
                query = query.filter(
                    or_(
                        ConfigAuditLog.module_name == module_name,
                        ConfigAuditLog.module_name.is_(None),
                    )
                )
            if env_name:
                query = query.filter(
                    or_(
                        ConfigAuditLog.env_name == env_name,
                        ConfigAuditLog.env_name.is_(None),
                    )
                )

            logs = query.order_by(ConfigAuditLog.id.asc()).limit(100).all()
            return [log.to_dict() for log in logs]
        finally:
            if not self._db:
                db.close()

    # ============================================================
    # 内部辅助方法
    # ============================================================

    def _find_item(
        self, db: Session, key: str, scope: str,
        module_name: Optional[str], env_name: Optional[str],
        instance_id: Optional[str],
    ) -> Optional[ConfigItem]:
        """查找配置项"""
        query = db.query(ConfigItem).filter(
            ConfigItem.config_key == key,
            ConfigItem.scope == scope,
        )
        if module_name:
            query = query.filter(ConfigItem.module_name == module_name)
        else:
            query = query.filter(ConfigItem.module_name.is_(None))
        if env_name:
            query = query.filter(ConfigItem.env_name == env_name)
        else:
            query = query.filter(ConfigItem.env_name.is_(None))
        if instance_id:
            query = query.filter(ConfigItem.instance_id == instance_id)
        else:
            query = query.filter(ConfigItem.instance_id.is_(None))

        return query.first()

    def _item_to_result(self, item: ConfigItem, include_secret: bool) -> Dict[str, Any]:
        """配置项转结果字典，处理敏感值和解密"""
        if include_secret and item.is_secret and _HAS_CRYPTO and item.config_value:
            try:
                decrypted = decrypt_value(item.config_value)
                # 尝试解析 JSON
                try:
                    value = json.loads(decrypted)
                except (json.JSONDecodeError, TypeError):
                    value = decrypted
                result = item.to_dict()
                result["config_value"] = value
                return result
            except Exception:
                return item.to_dict()
        return item.to_dict()

    def _create_version(
        self, db: Session, item: ConfigItem, old_value: Any,
        reason: str, operator: str,
    ) -> None:
        """创建版本记录"""
        version = ConfigVersion(
            config_key=item.config_key,
            scope=item.scope,
            module_name=item.module_name,
            env_name=item.env_name,
            instance_id=item.instance_id,
            version=item.version,
            config_value=item.config_value,
            config_type=item.config_type,
            description=item.description,
            is_secret=item.is_secret,
            change_reason=reason,
            changed_by=operator,
            is_canary=item.is_canary,
            canary_percent=item.canary_percent,
            canary_instances=item.canary_instances,
        )
        db.add(version)

    def _create_audit(
        self, db: Session, action: str, key: str, scope: str,
        module_name: Optional[str], env_name: Optional[str],
        instance_id: Optional[str],
        old_value: Any, new_value: Any,
        old_version: Optional[int], new_version: Optional[int],
        operator: str, reason: str, extra: Dict[str, Any] = None,
    ) -> None:
        """创建审计记录"""
        audit = ConfigAuditLog(
            action=action,
            config_key=key,
            scope=scope,
            module_name=module_name,
            env_name=env_name,
            instance_id=instance_id,
            old_value=old_value,
            new_value=new_value,
            old_version=old_version,
            new_version=new_version,
            operator=operator,
            reason=reason,
            extra=extra or {},
        )
        db.add(audit)

    def _should_use_canary(self, item: ConfigItem, instance_id: str) -> bool:
        """判断指定实例是否应该使用灰度配置"""
        if not item.is_canary:
            return False

        # 按实例列表灰度
        if item.canary_instances:
            return instance_id in item.canary_instances

        # 按百分比灰度（使用 instance_id 的哈希）
        if item.canary_percent is not None:
            hash_val = int(hashlib.md5(instance_id.encode()).hexdigest(), 16) % 100
            return hash_val < item.canary_percent

        return False

    def _validate_against_schema(
        self, db: Session, key: str, value: Any, schema_name: str,
    ) -> Tuple[bool, str]:
        """根据 Schema 校验配置值"""
        schema_record = (
            db.query(ConfigSchema)
            .filter(
                ConfigSchema.schema_name == schema_name,
                ConfigSchema.is_active == True,  # noqa: E712
            )
            .first()
        )
        if not schema_record:
            return False, f"Schema '{schema_name}' 不存在或未激活"

        schema = schema_record.schema_json

        # 简单的 Schema 校验（支持常见关键字）
        try:
            # 类型校验
            schema_type = schema.get("type")
            if schema_type:
                type_map = {
                    "string": str,
                    "integer": int,
                    "number": (int, float),
                    "boolean": bool,
                    "array": list,
                    "object": dict,
                }
                expected_type = type_map.get(schema_type)
                if expected_type:
                    if schema_type == "integer":
                        if isinstance(value, bool) or not isinstance(value, int):
                            return False, f"类型错误：应为 {schema_type}"
                    elif not isinstance(value, expected_type):
                        return False, f"类型错误：应为 {schema_type}"

            # 字符串长度校验
            if isinstance(value, str):
                if "minLength" in schema and len(value) < schema["minLength"]:
                    return False, f"字符串长度不足：最少 {schema['minLength']} 字符"
                if "maxLength" in schema and len(value) > schema["maxLength"]:
                    return False, f"字符串长度超限：最多 {schema['maxLength']} 字符"
                if "pattern" in schema:
                    import re
                    if not re.match(schema["pattern"], value):
                        return False, f"格式不匹配：{schema['pattern']}"

            # 数值范围校验
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                if "minimum" in schema and value < schema["minimum"]:
                    return False, f"数值过小：最小值为 {schema['minimum']}"
                if "maximum" in schema and value > schema["maximum"]:
                    return False, f"数值过大：最大值为 {schema['maximum']}"

            # 枚举校验
            if "enum" in schema:
                if value not in schema["enum"]:
                    return False, f"值不在允许范围内：{schema['enum']}"

            # 必填校验（通过 properties + required 在 object 类型中处理）
            if isinstance(value, dict) and "properties" in schema:
                required = schema.get("required", [])
                for req_key in required:
                    if req_key not in value:
                        return False, f"缺少必填字段：{req_key}"

            return True, ""
        except Exception as e:
            return False, f"Schema 校验异常: {str(e)}"


# 单例实例
_config_center_service: Optional[ConfigCenterService] = None


def get_config_center_service() -> ConfigCenterService:
    """获取配置中心服务单例"""
    global _config_center_service
    if _config_center_service is None:
        _config_center_service = ConfigCenterService()
    return _config_center_service
