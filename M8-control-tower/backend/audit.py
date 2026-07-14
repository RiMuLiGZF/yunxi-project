"""
M8 管理工作台 - 审计日志模块
"""

import json
import os
from pathlib import Path
from datetime import datetime
from typing import Optional
from functools import wraps
from fastapi import Request

# 审计日志使用 JSON 文件存储（只追加模式）
# 同时也支持 SQLAlchemy 模型（如果数据库可用）

def _get_yunxi_dir() -> Path:
    """获取云汐数据目录 ~/.yunxi"""
    yunxi_dir = Path.home() / ".yunxi"
    yunxi_dir.mkdir(parents=True, exist_ok=True)
    return yunxi_dir


AUDIT_LOG_FILE = _get_yunxi_dir() / "audit_logs.json"
AUDIT_LOG_LOCK_FILE = _get_yunxi_dir() / "audit_logs.lock"


def _load_all_logs() -> list:
    """加载所有审计日志"""
    if AUDIT_LOG_FILE.exists():
        try:
            with open(AUDIT_LOG_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return []


def _save_logs(logs: list) -> None:
    """保存审计日志（只追加时不使用此方法，使用 append）"""
    with open(AUDIT_LOG_FILE, "w", encoding="utf-8") as f:
        json.dump(logs, f, ensure_ascii=False, indent=2)


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
    添加一条审计日志（只追加）

    Args:
        action: 操作类型（login/logout/create/update/delete/enable/disable 等）
        module: 所属模块（auth/user/system/module/security 等）
        result: 结果（success/failed）
        username: 用户名
        user_id: 用户ID
        ip: 客户端IP
        user_agent: 用户代理
        details: 详细信息（字典）

    Returns:
        新增的日志记录
    """
    # 确保所有字段都是可序列化的类型
    safe_username = str(username) if username else ""
    safe_action = str(action) if action else ""
    safe_module = str(module) if module else ""
    safe_result = str(result) if result else "success"
    safe_ip = str(ip) if ip else ""
    safe_user_agent = str(user_agent)[:500] if user_agent else ""
    safe_details = details or {}

    # 确保 details 可以 JSON 序列化
    try:
        json.dumps(safe_details)
    except (TypeError, ValueError):
        safe_details = {"raw": str(safe_details)}

    log_entry = {
        "id": int(datetime.utcnow().timestamp() * 1000000),  # 微秒时间戳作为ID
        "user_id": user_id,
        "username": safe_username,
        "action": safe_action,
        "module": safe_module,
        "result": safe_result,
        "ip": safe_ip,
        "user_agent": safe_user_agent,
        "details": safe_details,
        "created_at": datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S"),
    }

    # 以追加模式写入文件
    logs = _load_all_logs()
    logs.append(log_entry)
    _save_logs(logs)

    # 尝试写入数据库（如果可用）
    try:
        from .models import SessionLocal, AuditLog as DBAuditLog
        db = SessionLocal()
        try:
            db_log = DBAuditLog(
                user_id=user_id,
                username=safe_username,
                action=safe_action,
                module=safe_module,
                result=safe_result,
                ip=safe_ip,
                user_agent=safe_user_agent,
                details=safe_details,
            )
            db.add(db_log)
            db.commit()
        except Exception:
            db.rollback()
        finally:
            db.close()
    except Exception:
        pass

    return log_entry


def query_audit_logs(
    username: Optional[str] = None,
    action: Optional[str] = None,
    module: Optional[str] = None,
    result: Optional[str] = None,
    start_time: Optional[str] = None,
    end_time: Optional[str] = None,
    page: int = 1,
    page_size: int = 20,
) -> dict:
    """
    P2-22: 查询审计日志（支持分页和筛选）
    
    优先从数据库查询，数据库不可用时降级到 JSON 文件。

    Args:
        username: 按用户名筛选
        action: 按操作类型筛选
        module: 按模块筛选
        result: 按结果筛选
        start_time: 开始时间（YYYY-MM-DD HH:MM:SS）
        end_time: 结束时间（YYYY-MM-DD HH:MM:SS）
        page: 页码
        page_size: 每页数量

    Returns:
        {"total": 总数, "items": 日志列表, "page": page, "page_size": page_size}
    """
    # 优先从数据库查询
    try:
        from .models import SessionLocal
        from .repositories.audit_repository import AuditRepository
        db = SessionLocal()
        try:
            repo = AuditRepository(db)
            logs, total = repo.query(
                username=username,
                action=action,
                module=module,
                result=result,
                start_time=start_time,
                end_time=end_time,
                page=page,
                page_size=page_size,
            )
            items = [log.to_dict() for log in logs]
            return {"total": total, "items": items, "page": page, "page_size": page_size}
        finally:
            db.close()
    except Exception:
        # 降级：使用 JSON 文件
        pass

    # JSON 降级方案
    logs = _load_all_logs()

    # 筛选
    filtered = logs
    if username:
        filtered = [log for log in filtered if username.lower() in log.get("username", "").lower()]
    if action:
        filtered = [log for log in filtered if log.get("action") == action]
    if module:
        filtered = [log for log in filtered if log.get("module") == module]
    if result:
        filtered = [log for log in filtered if log.get("result") == result]
    if start_time:
        filtered = [log for log in filtered if log.get("created_at", "") >= start_time]
    if end_time:
        filtered = [log for log in filtered if log.get("created_at", "") <= end_time]

    # 按时间倒序
    filtered.sort(key=lambda x: x.get("created_at", ""), reverse=True)

    total = len(filtered)

    # 分页
    start = (page - 1) * page_size
    end = start + page_size
    items = filtered[start:end]

    return {"total": total, "items": items, "page": page, "page_size": page_size}


def export_audit_logs_csv(
    username: Optional[str] = None,
    action: Optional[str] = None,
    module: Optional[str] = None,
    result: Optional[str] = None,
    start_time: Optional[str] = None,
    end_time: Optional[str] = None,
) -> str:
    """
    导出审计日志为 CSV 格式

    Returns:
        CSV 格式字符串
    """
    result_data = query_audit_logs(
        username=username,
        action=action,
        module=module,
        result=result,
        start_time=start_time,
        end_time=end_time,
        page=1,
        page_size=100000,  # 导出全部
    )

    logs = result_data["items"]

    # CSV 表头
    headers = ["ID", "用户名", "操作", "模块", "结果", "IP", "User-Agent", "详情", "创建时间"]

    import csv
    import io

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(headers)

    for log in logs:
        details_str = json.dumps(log.get("details", {}), ensure_ascii=False)
        writer.writerow([
            log.get("id", ""),
            log.get("username", ""),
            log.get("action", ""),
            log.get("module", ""),
            log.get("result", ""),
            log.get("ip", ""),
            log.get("user_agent", ""),
            details_str,
            log.get("created_at", ""),
        ])

    return output.getvalue()


def audit_log(action: str, module: str = "system"):
    """
    审计日志装饰器

    用法：
        @audit_log("login", "auth")
        async def some_endpoint(...):
            ...

    注意：被装饰的函数需要有 current_user 参数（通过 Depends 注入）
    """
    def decorator(func):
        @wraps(func)
        async def wrapper(*args, **kwargs):
            # 获取 request 对象
            request = kwargs.get("request")
            ip = ""
            user_agent = ""
            if request and isinstance(request, Request):
                forwarded = request.headers.get("X-Forwarded-For", "")
                if forwarded:
                    ip = forwarded.split(",")[0].strip()
                elif request.client:
                    ip = request.client.host
                user_agent = request.headers.get("User-Agent", "")

            # 获取当前用户
            current_user = kwargs.get("current_user", {})
            username = current_user.get("username", "") if current_user else ""
            user_id = current_user.get("id") if current_user else None

            result_status = "success"
            details = {}

            try:
                result = await func(*args, **kwargs)

                # 如果返回的是 ApiResponse，检查 code
                if hasattr(result, 'code'):
                    if result.code != 0:
                        result_status = "failed"
                        details["error_message"] = result.message
                elif isinstance(result, dict) and result.get("code", 0) != 0:
                    result_status = "failed"
                    details["error_message"] = result.get("message", "")

                return result
            except Exception as e:
                result_status = "failed"
                details["error"] = str(e)
                raise
            finally:
                try:
                    add_audit_log(
                        action=action,
                        module=module,
                        result=result_status,
                        username=username,
                        user_id=user_id,
                        ip=ip,
                        user_agent=user_agent,
                        details=details,
                    )
                except Exception:
                    # 审计日志写入失败不影响主流程
                    pass

        return wrapper
    return decorator
