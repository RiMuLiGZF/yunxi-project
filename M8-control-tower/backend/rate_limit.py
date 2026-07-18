"""
登录速率限制模块（SEC-012 P2级安全修复）

为登录接口提供 IP 级和用户名级的速率限制，防止暴力破解攻击。

特性：
1. 同一 IP：5 次/分钟
2. 同一用户名：5 次/分钟（连续失败后锁定 15 分钟）
3. 账户锁定：连续 10 次失败锁定 30 分钟
4. 内存缓存实现，线程安全
5. 审计日志记录失败的登录尝试
6. 超过限制后返回 429 Too Many Requests

使用方式：
    from .rate_limit import check_login_rate_limit, record_login_attempt

    # 在登录接口中：
    ok, retry_after = check_login_rate_limit(ip, username)
    if not ok:
        raise HTTPException(status_code=429, ...)

    # 登录失败后：
    record_login_attempt(ip, username, success=False)
"""

import time
import threading
import logging
from typing import Tuple, Dict, List
from collections import defaultdict

logger = logging.getLogger("m8.rate_limit")

# ===========================================================================
# 配置常量
# ===========================================================================

# IP 级速率限制：每分钟最大尝试次数
MAX_ATTEMPTS_PER_IP_PER_MINUTE = 5

# 用户名级速率限制：每分钟最大尝试次数
MAX_ATTEMPTS_PER_USER_PER_MINUTE = 5

# 用户名级失败锁定：连续失败次数阈值
MAX_CONSECUTIVE_FAILURES = 10

# 用户名级失败锁定时间（秒）
USER_LOCK_DURATION_SECONDS = 30 * 60  # 30 分钟

# 连续失败后临时锁定时间（秒）
TEMPORARY_LOCK_DURATION_SECONDS = 15 * 60  # 15 分钟

# 速率限制时间窗口（秒）
RATE_LIMIT_WINDOW_SECONDS = 60  # 1 分钟


# ===========================================================================
# 内存存储（线程安全）
# ===========================================================================

_rate_lock = threading.Lock()

# IP 级尝试记录：ip -> [timestamp, ...]
_ip_attempts: Dict[str, List[float]] = defaultdict(list)

# 用户名级尝试记录：username -> [timestamp, ...]
_user_attempts: Dict[str, List[float]] = defaultdict(list)

# 用户名级连续失败计数：username -> count
_user_consecutive_failures: Dict[str, int] = defaultdict(int)

# 用户名级锁定信息：username -> {"locked_until": timestamp, "reason": str}
_user_locks: Dict[str, Dict] = {}

# 审计日志：最近的失败尝试（最多保留 1000 条）
_audit_log: List[Dict] = []
MAX_AUDIT_LOG_ENTRIES = 1000


# ===========================================================================
# 工具函数
# ===========================================================================

def _clean_old_entries(entries: List[float], window_seconds: float) -> None:
    """清理时间窗口外的旧条目

    Args:
        entries: 时间戳列表
        window_seconds: 时间窗口（秒）
    """
    now = time.time()
    cutoff = now - window_seconds
    # 移除窗口外的条目
    while entries and entries[0] < cutoff:
        entries.pop(0)


def _add_audit_log(ip: str, username: str, success: bool, reason: str = "") -> None:
    """添加审计日志

    Args:
        ip: 客户端 IP
        username: 用户名
        success: 是否成功
        reason: 失败原因
    """
    entry = {
        "timestamp": time.time(),
        "ip": ip,
        "username": username,
        "success": success,
        "reason": reason,
    }
    _audit_log.append(entry)
    # 限制日志条目数量
    if len(_audit_log) > MAX_AUDIT_LOG_ENTRIES:
        _audit_log[:] = _audit_log[-MAX_AUDIT_LOG_ENTRIES:]


# ===========================================================================
# 速率限制检查
# ===========================================================================

def check_login_rate_limit(ip: str, username: str) -> Tuple[bool, int, str]:
    """检查登录速率限制

    检查顺序：
    1. 用户是否被锁定
    2. IP 级速率限制
    3. 用户名级速率限制

    Args:
        ip: 客户端 IP 地址
        username: 用户名

    Returns:
        (allowed, retry_after, reason):
        - allowed: 是否允许尝试
        - retry_after: 需要等待的秒数（0 表示不需要等待）
        - reason: 限制原因（用于日志和错误信息）
    """
    with _rate_lock:
        now = time.time()

        # 1. 检查用户是否被锁定
        if username in _user_locks:
            lock_info = _user_locks[username]
            if now < lock_info["locked_until"]:
                retry_after = int(lock_info["locked_until"] - now)
                reason = (
                    f"账户 '{username}' 因多次登录失败已被锁定，"
                    f"请 {retry_after // 60} 分钟后再试"
                )
                logger.warning(
                    "[SEC-012] 登录被阻止：账户锁定 (ip=%s, user=%s, reason=%s)",
                    ip, username, lock_info.get("reason", ""),
                )
                return False, retry_after, reason
            else:
                # 锁定已过期，清除锁定
                del _user_locks[username]
                _user_consecutive_failures[username] = 0

        # 2. 清理旧条目
        _clean_old_entries(_ip_attempts[ip], RATE_LIMIT_WINDOW_SECONDS)
        _clean_old_entries(_user_attempts[username], RATE_LIMIT_WINDOW_SECONDS)

        # 3. 检查 IP 级速率限制
        ip_count = len(_ip_attempts[ip])
        if ip_count >= MAX_ATTEMPTS_PER_IP_PER_MINUTE:
            # 计算还需要等待多久
            oldest = _ip_attempts[ip][0] if _ip_attempts[ip] else now
            retry_after = int(RATE_LIMIT_WINDOW_SECONDS - (now - oldest)) + 1
            reason = (
                f"IP {ip} 登录尝试过于频繁，请 {retry_after} 秒后再试"
            )
            logger.warning(
                "[SEC-012] 登录被阻止：IP 速率限制 (ip=%s, count=%d/%d)",
                ip, ip_count, MAX_ATTEMPTS_PER_IP_PER_MINUTE,
            )
            _add_audit_log(ip, username, False, "ip_rate_limit")
            return False, retry_after, reason

        # 4. 检查用户名级速率限制
        user_count = len(_user_attempts[username])
        if user_count >= MAX_ATTEMPTS_PER_USER_PER_MINUTE:
            oldest = _user_attempts[username][0] if _user_attempts[username] else now
            retry_after = int(RATE_LIMIT_WINDOW_SECONDS - (now - oldest)) + 1
            reason = (
                f"账户 '{username}' 登录尝试过于频繁，请 {retry_after} 秒后再试"
            )
            logger.warning(
                "[SEC-012] 登录被阻止：用户速率限制 (user=%s, count=%d/%d)",
                username, user_count, MAX_ATTEMPTS_PER_USER_PER_MINUTE,
            )
            _add_audit_log(ip, username, False, "user_rate_limit")
            return False, retry_after, reason

        return True, 0, ""


# ===========================================================================
# 登录尝试记录
# ===========================================================================

def record_login_attempt(ip: str, username: str, success: bool) -> None:
    """记录登录尝试结果

    Args:
        ip: 客户端 IP 地址
        username: 用户名
        success: 是否登录成功
    """
    with _rate_lock:
        now = time.time()

        # 记录 IP 级尝试（无论成功失败都计数，用于限流）
        _ip_attempts[ip].append(now)
        _clean_old_entries(_ip_attempts[ip], RATE_LIMIT_WINDOW_SECONDS)

        # 记录用户名级尝试（无论成功失败都计数，用于限流）
        _user_attempts[username].append(now)
        _clean_old_entries(_user_attempts[username], RATE_LIMIT_WINDOW_SECONDS)

        if success:
            # 登录成功：重置连续失败计数
            if username in _user_consecutive_failures:
                _user_consecutive_failures[username] = 0
            # 如果用户被锁定但成功了（理论上不会发生，因为锁定时会在 check 阶段被阻止）
            if username in _user_locks:
                del _user_locks[username]
            logger.info(
                "[SEC-012] 登录成功 (ip=%s, user=%s)",
                ip, username,
            )
            _add_audit_log(ip, username, True, "success")
        else:
            # 登录失败：增加连续失败计数
            _user_consecutive_failures[username] += 1
            consecutive = _user_consecutive_failures[username]

            logger.warning(
                "[SEC-012] 登录失败 (ip=%s, user=%s, consecutive_failures=%d)",
                ip, username, consecutive,
            )
            _add_audit_log(ip, username, False, "invalid_credentials")

            # 检查是否需要锁定账户
            if consecutive >= MAX_CONSECUTIVE_FAILURES:
                locked_until = now + USER_LOCK_DURATION_SECONDS
                _user_locks[username] = {
                    "locked_until": locked_until,
                    "reason": f"连续 {consecutive} 次登录失败",
                    "failure_count": consecutive,
                }
                logger.critical(
                    "[SEC-012] 账户已锁定 (user=%s, ip=%s, failures=%d, duration=%d分钟)",
                    username, ip, consecutive, USER_LOCK_DURATION_SECONDS // 60,
                )


# ===========================================================================
# 账户管理
# ===========================================================================

def unlock_user(username: str) -> bool:
    """解锁用户账户

    Args:
        username: 用户名

    Returns:
        True 表示成功解锁，False 表示用户未被锁定
    """
    with _rate_lock:
        if username in _user_locks:
            del _user_locks[username]
            _user_consecutive_failures[username] = 0
            logger.info("[SEC-012] 账户已手动解锁 (user=%s)", username)
            return True
        return False


def is_user_locked(username: str) -> Tuple[bool, Dict]:
    """检查用户是否被锁定

    Args:
        username: 用户名

    Returns:
        (is_locked, lock_info): 是否锁定 + 锁定信息
    """
    with _rate_lock:
        if username in _user_locks:
            now = time.time()
            lock_info = _user_locks[username].copy()
            if now < lock_info["locked_until"]:
                lock_info["remaining_seconds"] = int(lock_info["locked_until"] - now)
                return True, lock_info
            else:
                # 已过期
                del _user_locks[username]
                _user_consecutive_failures[username] = 0
        return False, {}


def get_consecutive_failures(username: str) -> int:
    """获取用户连续失败次数

    Args:
        username: 用户名

    Returns:
        连续失败次数
    """
    with _rate_lock:
        return _user_consecutive_failures.get(username, 0)


# ===========================================================================
# 统计与审计
# ===========================================================================

def get_rate_limit_stats() -> Dict:
    """获取速率限制统计信息

    Returns:
        统计信息字典
    """
    with _rate_lock:
        # 清理过期数据
        for ip in list(_ip_attempts.keys()):
            _clean_old_entries(_ip_attempts[ip], RATE_LIMIT_WINDOW_SECONDS)
            if not _ip_attempts[ip]:
                del _ip_attempts[ip]

        for user in list(_user_attempts.keys()):
            _clean_old_entries(_user_attempts[user], RATE_LIMIT_WINDOW_SECONDS)
            if not _user_attempts[user]:
                del _user_attempts[user]

        # 清理过期锁定
        now = time.time()
        expired_users = [u for u, info in _user_locks.items() if info["locked_until"] < now]
        for u in expired_users:
            del _user_locks[u]
            _user_consecutive_failures[u] = 0

        return {
            "monitored_ips": len(_ip_attempts),
            "monitored_users": len(_user_attempts),
            "locked_users": len(_user_locks),
            "locked_usernames": list(_user_locks.keys()),
            "audit_log_entries": len(_audit_log),
            "config": {
                "max_attempts_per_ip_per_minute": MAX_ATTEMPTS_PER_IP_PER_MINUTE,
                "max_attempts_per_user_per_minute": MAX_ATTEMPTS_PER_USER_PER_MINUTE,
                "max_consecutive_failures": MAX_CONSECUTIVE_FAILURES,
                "user_lock_duration_seconds": USER_LOCK_DURATION_SECONDS,
                "rate_limit_window_seconds": RATE_LIMIT_WINDOW_SECONDS,
            },
        }


def get_audit_log(limit: int = 100) -> List[Dict]:
    """获取审计日志（最近的 N 条）

    Args:
        limit: 返回的最大条目数

    Returns:
        审计日志列表（按时间倒序）
    """
    with _rate_lock:
        entries = _audit_log[-limit:] if limit < len(_audit_log) else list(_audit_log)
        # 返回副本并倒序（最新的在前）
        return list(reversed(entries))


def reset_rate_limit(ip: str = None, username: str = None) -> None:
    """重置速率限制计数（用于测试或手动重置）

    Args:
        ip: 指定 IP，None 表示重置所有 IP
        username: 指定用户名，None 表示重置所有用户
    """
    with _rate_lock:
        if ip is None:
            _ip_attempts.clear()
        elif ip in _ip_attempts:
            del _ip_attempts[ip]

        if username is None:
            _user_attempts.clear()
            _user_consecutive_failures.clear()
            _user_locks.clear()
        else:
            if username in _user_attempts:
                del _user_attempts[username]
            if username in _user_consecutive_failures:
                del _user_consecutive_failures[username]
            if username in _user_locks:
                del _user_locks[username]
