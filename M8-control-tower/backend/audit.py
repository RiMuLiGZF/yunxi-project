"""
M8 管理工作台 - 审计日志模块（升级版）
=========================================
SC-007 P1级 - 审计日志全覆盖

已升级接入 shared.core.audit_framework 统一审计框架。

**向后兼容**：保留所有原有函数（add_audit_log, query_audit_logs, export_audit_logs_csv, audit_log 装饰器），
旧代码无需修改即可继续使用。

新增能力：
- 8大审计事件分类（authentication/authorization/configuration/data_management/user_management/security/system/api）
- 3级严重级别（info/warning/critical）
- 链式哈希防篡改
- 增强的查询能力（按分类、级别、操作者筛选）
- 支持 JSON/CSV 两种导出格式
- 审计统计仪表板数据
- 审计日志保留策略（默认180天）
- 审计完整性校验
"""

import json
import logging
import sys
from pathlib import Path
from typing import Optional, Any, Dict, List
from functools import wraps
from fastapi import Request

# 确保 shared 模块可导入
_project_root = Path(__file__).parent.parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

from shared.core.audit_framework import (
    AuditLogger as UnifiedAuditLogger,
    AuditEvent,
    AuditCategory,
    AuditLevel,
    AuditResult,
    JsonFileAuditStorage,
    MemoryAuditStorage,
    get_audit_logger,
    audit_log as unified_audit_decorator,
)

logger = logging.getLogger(__name__)


# ===========================================================================
# M8 专用审计日志器（基于统一框架）
# ===========================================================================

_m8_audit_logger: Optional[UnifiedAuditLogger] = None


def get_m8_audit_logger() -> UnifiedAuditLogger:
    """
    获取 M8 模块专用的审计日志器

    使用独立的存储目录，与业务数据分开存放。
    """
    global _m8_audit_logger
    if _m8_audit_logger is None:
        log_dir = Path.home() / ".yunxi" / "audit" / "m8"
        storage = JsonFileAuditStorage(
            log_dir=log_dir,
            retention_days=180,  # 默认保留 180 天
        )
        _m8_audit_logger = UnifiedAuditLogger(storage=storage)
    return _m8_audit_logger


# ===========================================================================
# 向后兼容：原有函数（内部委托给统一审计框架）
# ===========================================================================

def add_audit_log(
    action: str,
    module: str = "system",
    result: str = "success",
    username: str = "",
    user_id: Optional[int] = None,
    ip: str = "",
    user_agent: str = "",
    details: Optional[dict] = None,
) -> dict:
    """
    添加一条审计日志（向后兼容旧版API）

    内部委托给统一审计框架。

    Args:
        action: 操作类型
        module: 所属模块
        result: 结果（success/failed）
        username: 用户名
        user_id: 用户ID
        ip: 客户端IP
        user_agent: 用户代理
        details: 详细信息

    Returns:
        新增的日志记录字典（旧格式，兼容旧代码）
    """
    audit = get_m8_audit_logger()

    # 构造审计事件
    event = AuditEvent(
        category=_infer_category(module, action),
        level=_infer_level(result, action),
        actor=username or str(user_id or ""),
        module=module,
        action=action,
        result=result,
        ip_address=ip,
        user_agent=user_agent,
        metadata=details or {},
    )
    if user_id is not None:
        event.metadata["user_id"] = user_id

    audit.log(event)

    # 返回旧格式，保持向后兼容
    return {
        "id": int(event.timestamp.timestamp() * 1000000) if event.timestamp else 0,
        "user_id": user_id,
        "username": username,
        "action": action,
        "module": module,
        "result": result,
        "ip": ip,
        "user_agent": user_agent,
        "details": details or {},
        "created_at": event.timestamp.strftime("%Y-%m-%d %H:%M:%S") if event.timestamp else "",
        # 新增字段（新代码可以使用）
        "event_id": event.event_id,
        "category": event.category,
        "level": event.level,
    }


def _infer_category(module: str, action: str) -> str:
    """根据模块和操作推断审计分类"""
    action_lower = action.lower()

    # 认证相关
    if module == "auth" or action_lower in ("login", "logout", "token_refresh", "password_change"):
        return AuditCategory.AUTHENTICATION

    # 用户管理相关
    if module == "user" or action_lower.startswith(("create_user", "update_user", "delete_user", "role_")):
        return AuditCategory.USER_MANAGEMENT

    # 安全相关
    if module == "security" or "attack" in action_lower or "block" in action_lower or "waf" in action_lower:
        return AuditCategory.SECURITY

    # 配置相关
    if "config" in module.lower() or "setting" in action_lower or "setting" in module.lower():
        return AuditCategory.CONFIGURATION

    # 系统相关
    if module == "system" or "module_" in action_lower or "upgrade" in action_lower:
        return AuditCategory.SYSTEM

    # 默认
    return AuditCategory.SYSTEM


def _infer_level(result: str, action: str) -> str:
    """根据结果和操作推断严重级别"""
    action_lower = action.lower()

    if result == "failed" or result == "failure":
        # 登录失败等安全相关失败是警告级别
        if "login" in action_lower or "auth" in action_lower or "password" in action_lower:
            return AuditLevel.WARNING
        return AuditLevel.INFO

    # 关键操作即使成功也是 warning 级别
    critical_actions = ("delete_user", "reset_password", "key_rotate", "module_stop", "emergency")
    if any(ca in action_lower for ca in critical_actions):
        return AuditLevel.WARNING

    return AuditLevel.INFO


def query_audit_logs(
    username: Optional[str] = None,
    action: Optional[str] = None,
    module: Optional[str] = None,
    result: Optional[str] = None,
    start_time: Optional[str] = None,
    end_time: Optional[str] = None,
    page: int = 1,
    page_size: int = 20,
    # 新增筛选参数
    category: Optional[str] = None,
    level: Optional[str] = None,
    sort_by: str = "timestamp",
    sort_order: str = "desc",
) -> dict:
    """
    查询审计日志（增强版，向后兼容）

    支持原有筛选参数，新增按分类、级别筛选。

    Args:
        username: 按用户名筛选
        action: 按操作类型筛选
        module: 按模块筛选
        result: 按结果筛选
        start_time: 开始时间
        end_time: 结束时间
        page: 页码
        page_size: 每页数量
        category: 按事件分类筛选（新增）
        level: 按严重级别筛选（新增）
        sort_by: 排序字段（新增）
        sort_order: 排序方向（新增）

    Returns:
        {"total": 总数, "items": 日志列表, "page": page, "page_size": page_size}
    """
    audit = get_m8_audit_logger()

    # 旧版 result 值转换（success/failed -> success/failure）
    audit_result = result
    if result == "failed":
        audit_result = "failure"

    result_data = audit.query(
        category=category,
        level=level,
        actor=username,
        module=module,
        action=action,
        result=audit_result,
        start_time=start_time,
        end_time=end_time,
        page=page,
        page_size=page_size,
        sort_by=sort_by,
        sort_order=sort_order,
    )

    # 转换为旧格式，保持向后兼容
    old_format_items = []
    for item in result_data["items"]:
        details = item.get("metadata", {})
        user_id = details.pop("user_id", None) if isinstance(details, dict) else None

        old_format_items.append({
            "id": item.get("event_id", ""),
            "event_id": item.get("event_id", ""),
            "user_id": user_id,
            "username": item.get("actor", ""),
            "action": item.get("action", ""),
            "module": item.get("module", ""),
            "category": item.get("category", ""),
            "level": item.get("level", ""),
            "result": "failed" if item.get("result") == "failure" else item.get("result", ""),
            "ip": item.get("ip_address", ""),
            "user_agent": item.get("user_agent", ""),
            "details": details if isinstance(details, dict) else {},
            "created_at": item.get("timestamp", ""),
            "resource_type": item.get("resource_type", ""),
            "resource_id": item.get("resource_id", ""),
            "description": item.get("description", ""),
            "request_id": item.get("request_id", ""),
        })

    return {
        "total": result_data["total"],
        "items": old_format_items,
        "page": result_data["page"],
        "page_size": result_data["page_size"],
    }


def export_audit_logs_csv(
    username: Optional[str] = None,
    action: Optional[str] = None,
    module: Optional[str] = None,
    result: Optional[str] = None,
    start_time: Optional[str] = None,
    end_time: Optional[str] = None,
    category: Optional[str] = None,
    level: Optional[str] = None,
) -> str:
    """
    导出审计日志为 CSV 格式（增强版）

    Args:
        同 query_audit_logs 的筛选参数

    Returns:
        CSV 格式字符串
    """
    audit = get_m8_audit_logger()

    audit_result = result
    if result == "failed":
        audit_result = "failure"

    return audit.export(
        format="csv",
        category=category,
        level=level,
        actor=username,
        module=module,
        start_time=start_time,
        end_time=end_time,
    )


def export_audit_logs_json(
    username: Optional[str] = None,
    action: Optional[str] = None,
    module: Optional[str] = None,
    result: Optional[str] = None,
    start_time: Optional[str] = None,
    end_time: Optional[str] = None,
    category: Optional[str] = None,
    level: Optional[str] = None,
) -> str:
    """
    导出审计日志为 JSON 格式（新增）

    Returns:
        JSON 格式字符串
    """
    audit = get_m8_audit_logger()

    audit_result = result
    if result == "failed":
        audit_result = "failure"

    return audit.export(
        format="json",
        category=category,
        level=level,
        actor=username,
        module=module,
        start_time=start_time,
        end_time=end_time,
    )


def get_audit_stats(time_range: str = "24h") -> dict:
    """
    获取审计统计数据（新增）

    用于审计统计仪表板。

    Args:
        time_range: 时间范围（1h/24h/7d/30d/all）

    Returns:
        统计数据字典
    """
    audit = get_m8_audit_logger()
    return audit.get_stats(time_range=time_range)


def verify_audit_integrity() -> dict:
    """
    验证审计日志完整性（新增）

    基于链式哈希校验审计日志是否被篡改。

    Returns:
        {"valid": bool, "total_records": int, "error_index": int, "error_detail": str}
    """
    audit = get_m8_audit_logger()
    return audit.verify_integrity()


def clean_expired_audit_logs(retention_days: Optional[int] = None) -> int:
    """
    清理过期的审计日志（新增）

    Args:
        retention_days: 保留天数，None 时使用默认值（180天）

    Returns:
        清理的文件数量
    """
    audit = get_m8_audit_logger()
    return audit.clean_expired(retention_days)


# ===========================================================================
# 向后兼容：审计日志装饰器
# ===========================================================================

def audit_log(action: str, module: str = "system"):
    """
    审计日志装饰器（向后兼容旧版API）

    内部委托给统一审计框架的装饰器。

    用法：
        @audit_log("login", "auth")
        async def some_endpoint(...):
            ...

    注意：被装饰的函数需要有 current_user 参数（通过 Depends 注入）
    """
    return unified_audit_decorator(
        action=action,
        category=_infer_category(module, action),
        module=module,
        audit_logger=get_m8_audit_logger(),
    )


# ===========================================================================
# 新增：便捷审计函数
# ===========================================================================

def log_authentication(
    action: str = "login",
    username: str = "",
    result: str = "success",
    ip: str = "",
    user_agent: str = "",
    details: Optional[dict] = None,
) -> dict:
    """
    记录认证审计事件

    Args:
        action: 操作（login/logout/token_refresh/password_change/login_failed）
        username: 用户名
        result: 结果（success/failure）
        ip: IP地址
        user_agent: 用户代理
        details: 详细信息

    Returns:
        审计事件字典
    """
    audit = get_m8_audit_logger()
    level = AuditLevel.WARNING if result == "failure" else AuditLevel.INFO
    event = AuditEvent(
        category=AuditCategory.AUTHENTICATION,
        level=level,
        actor=username,
        module="auth",
        action=action,
        result=result,
        ip_address=ip,
        user_agent=user_agent,
        metadata=details or {},
    )
    audit.log(event)
    return event.to_dict()


def log_user_management(
    action: str = "create_user",
    username: str = "",
    operator: str = "",
    result: str = "success",
    ip: str = "",
    details: Optional[dict] = None,
) -> dict:
    """记录用户管理审计事件"""
    audit = get_m8_audit_logger()
    level = AuditLevel.WARNING if action in ("delete_user", "reset_password") else AuditLevel.INFO
    event = AuditEvent(
        category=AuditCategory.USER_MANAGEMENT,
        level=level,
        actor=operator,
        module="user",
        action=action,
        resource_type="user",
        resource_id=username,
        result=result,
        ip_address=ip,
        metadata=details or {},
    )
    audit.log(event)
    return event.to_dict()


def log_configuration_change(
    action: str = "update_config",
    config_key: str = "",
    operator: str = "",
    result: str = "success",
    ip: str = "",
    old_value: Any = None,
    new_value: Any = None,
) -> dict:
    """记录配置变更审计事件"""
    audit = get_m8_audit_logger()
    level = AuditLevel.WARNING if "key" in config_key.lower() or "secret" in config_key.lower() else AuditLevel.INFO
    event = AuditEvent(
        category=AuditCategory.CONFIGURATION,
        level=level,
        actor=operator,
        module="system",
        action=action,
        resource_type="config",
        resource_id=config_key,
        result=result,
        ip_address=ip,
        metadata={
            "config_key": config_key,
            # 不记录实际值，只记录是否变更
            "value_changed": old_value != new_value,
        },
    )
    audit.log(event)
    return event.to_dict()


def log_security_event(
    action: str = "attack_detected",
    source_ip: str = "",
    severity: str = "warning",
    description: str = "",
    details: Optional[dict] = None,
) -> dict:
    """记录安全审计事件"""
    audit = get_m8_audit_logger()
    level_map = {
        "info": AuditLevel.INFO,
        "warning": AuditLevel.WARNING,
        "critical": AuditLevel.CRITICAL,
    }
    level = level_map.get(severity.lower(), AuditLevel.WARNING)
    event = AuditEvent(
        category=AuditCategory.SECURITY,
        level=level,
        actor="system",
        module="security",
        action=action,
        description=description,
        result="success" if "detect" in action else "success",
        ip_address=source_ip,
        metadata=details or {},
    )
    audit.log(event)
    return event.to_dict()


def log_system_event(
    action: str = "module_start",
    module_name: str = "",
    operator: str = "system",
    result: str = "success",
    details: Optional[dict] = None,
) -> dict:
    """记录系统审计事件"""
    audit = get_m8_audit_logger()
    level = AuditLevel.WARNING if action in ("module_stop", "system_shutdown", "emergency_brake") else AuditLevel.INFO
    event = AuditEvent(
        category=AuditCategory.SYSTEM,
        level=level,
        actor=operator,
        module=module_name or "system",
        action=action,
        result=result,
        metadata=details or {},
    )
    audit.log(event)
    return event.to_dict()


# ===========================================================================
# 审计事件分类和级别列表（用于前端下拉框）
# ===========================================================================

def get_audit_categories() -> List[Dict[str, str]]:
    """获取所有审计事件分类列表"""
    return [
        {"value": "authentication", "label": "认证事件"},
        {"value": "authorization", "label": "授权事件"},
        {"value": "configuration", "label": "配置变更"},
        {"value": "data_management", "label": "数据管理"},
        {"value": "user_management", "label": "用户管理"},
        {"value": "security", "label": "安全事件"},
        {"value": "system", "label": "系统事件"},
        {"value": "api", "label": "API调用"},
    ]


def get_audit_levels() -> List[Dict[str, str]]:
    """获取所有审计级别列表"""
    return [
        {"value": "info", "label": "普通信息"},
        {"value": "warning", "label": "警告"},
        {"value": "critical", "label": "严重"},
    ]


def get_audit_actions() -> List[str]:
    """获取常见操作类型列表（用于筛选下拉框）"""
    return [
        # 认证
        "login", "logout", "login_failed", "token_refresh",
        "password_change", "password_reset",
        # 用户管理
        "create_user", "update_user", "delete_user",
        "assign_role", "revoke_role",
        # 配置
        "update_config", "key_rotate",
        # 安全
        "attack_detected", "ip_blocked", "waf_triggered",
        "policy_update",
        # 系统
        "module_start", "module_stop", "module_restart",
        "system_upgrade", "backup", "restore",
        "emergency_brake", "release_brake",
        # 数据管理
        "data_export", "data_import", "data_delete",
    ]
