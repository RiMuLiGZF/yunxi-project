"""
云汐系统 - 可复用 WAF 中间件（内嵌引擎模式）

基于 M12 安全盾的 WAF 检测引擎，封装为 FastAPI/Starlette 中间件，
可在任何模块中直接接入，无需依赖独立的 M12 服务。

特性：
1. 内嵌 WAF 引擎，零外部依赖，启动即可用
2. 支持两种模式：
   - monitor（检测模式）：只检测不拦截，记录日志，不影响性能
   - block（拦截模式）：检测到攻击立即返回 403
3. 可配置规则集：支持按类型启用/禁用规则
4. 自动降级：WAF 异常时自动放行，不影响主流程
5. 统计功能：拦截数、检测数、各类型攻击数
6. 高性能：预编译正则，正常请求检测 < 1ms

使用方式：
    from shared.waf_middleware import WafMiddleware, register_waf_middleware

    # 方式一：手动注册
    app.add_middleware(WafMiddleware, enabled=True, mode="monitor")

    # 方式二：使用注册函数
    register_waf_middleware(app)

配置项（环境变量）：
- WAF_ENABLED：是否启用 WAF（默认 true）
- WAF_MODE：monitor / block（默认 monitor）
- WAF_RULE_TYPES：启用的规则类型，逗号分隔，如 "sql_injection,xss"（默认全部启用）
- WAF_EXCLUDE_PATHS：排除的路径，逗号分隔
- WAF_BODY_LIMIT_KB：检测的请求体大小限制 KB（默认 10）
"""

import re
import time
import os
import logging
import threading
from typing import Dict, List, Optional, Set, Any
from urllib.parse import unquote

from fastapi import Request, status
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.types import ASGIApp

logger = logging.getLogger(__name__)

DAY_SECONDS = 86400

# ===========================================================================
# 内置规则定义
# ===========================================================================

# SQL 注入检测规则
SQL_INJECTION_PATTERNS = [
    (r"(?i)(\b(SELECT|INSERT|UPDATE|DELETE|DROP|CREATE|ALTER|TRUNCATE|EXEC|EXECUTE|UNION|GRANT|REVOKE)\b)", "sql_keyword"),
    (r"(--|#|/\*|\*/)", "sql_comment"),
    (r"('|%27).*(=|OR|AND|--)", "sql_quote_injection"),
    (r"(?i)(\b1\s*=\s*1\b|\b'1'\s*=\s*'1'\b)", "sql_tautology"),
    (r"(?i)\bUNION\b.*\bSELECT\b", "sql_union"),
    (r";\s*(SELECT|INSERT|UPDATE|DELETE|DROP|CREATE|EXEC)", "sql_stacked"),
]

# XSS 检测规则
XSS_PATTERNS = [
    (r"(?i)<\s*script[^>]*>", "xss_script_tag"),
    (r"(?i)javascript\s*:", "xss_javascript_protocol"),
    (r"(?i)\bon\w+\s*=", "xss_event_handler"),
    (r"(?i)<\s*(iframe|img|svg|body|input|form|a|div)[^>]*\bon\w+\s*=", "xss_html_event"),
    (r"(?i)eval\s*\(", "xss_eval"),
    (r"(?i)document\.(cookie|location|write)", "xss_document_access"),
    (r"(?i)expression\s*\(", "xss_expression"),
    (r"(?i)vbscript\s*:", "xss_vbscript"),
]

# 命令注入检测规则
COMMAND_INJECTION_PATTERNS = [
    (r"[;&|`$]\s*(ls|cat|whoami|id|uname|ps|net|wget|curl|chmod|chown)", "cmd_pipe"),
    (r"\$\([^)]+\)|`[^`]+`", "cmd_substitution"),
    (r"(?i)(\|\s*(dir|type|ipconfig|netstat|whoami|tasklist)|&\s*(dir|type|ipconfig))", "cmd_windows"),
    (r"(?i)(/bin/|/sbin/|/usr/bin/|cmd\.exe|powershell)", "cmd_path_exec"),
    (r"`[^`]+`", "cmd_backtick"),
]

# 路径遍历检测规则
PATH_TRAVERSAL_PATTERNS = [
    (r"\.\./|\.\.\\", "path_traversal_dotdot"),
    (r"%2e%2e%2f|%2e%2e%5c", "path_traversal_encoded"),
    (r"\.\.%2f|\.\.%5c", "path_traversal_double"),
    (r"(?i)(/etc/passwd|/etc/shadow|/proc/|c:\\windows|c:\\winnt)", "path_traversal_absolute"),
]

# CSRF 检测规则（简化版，主要检测 header）
CSRF_PATTERNS = [
    (r"(?i)(referer\s*:\s*none|origin\s*:\s*null)", "csrf_missing_origin"),
]

ALL_RULE_TYPES = {"sql_injection", "xss", "command_injection", "path_traversal", "csrf"}


# ===========================================================================
# WAF 引擎（轻量内嵌版）
# ===========================================================================

class WafEngineCore:
    """
    WAF 检测引擎核心（内嵌版）

    提供 HTTP 请求的安全检测功能，支持多种攻击类型的检测。
    使用预编译正则表达式，性能 < 1ms（正常请求）。
    """

    def __init__(self, enabled_rule_types: Optional[Set[str]] = None):
        """初始化 WAF 引擎

        Args:
            enabled_rule_types: 启用的规则类型集合，None 表示全部启用
        """
        self._lock = threading.RLock()
        self.enabled = True
        self._rules: List[Dict[str, Any]] = []
        self._compiled_patterns: Dict[int, re.Pattern] = {}
        self._stats: Dict[str, Any] = {
            "total_checks": 0,
            "total_blocks": 0,
            "today_blocks": 0,
            "start_of_day": time.time(),
            "total_detection_time_ns": 0,
            "blocks_by_type": {},
        }
        self._enabled_rule_types = enabled_rule_types or ALL_RULE_TYPES
        self._load_builtin_rules()

    def _load_builtin_rules(self) -> None:
        """加载内置规则并预编译正则表达式"""
        rule_id = 0

        all_patterns = [
            # request = path + query + body（最常见的攻击注入点）
            # header 检测容易误报（如 Accept: */* 会被误认为 SQL 注释）
            ("sql_injection", SQL_INJECTION_PATTERNS, "high", "block", "request"),
            ("xss", XSS_PATTERNS, "high", "block", "request"),
            ("command_injection", COMMAND_INJECTION_PATTERNS, "critical", "block", "request"),
            ("path_traversal", PATH_TRAVERSAL_PATTERNS, "high", "block", "path_query"),
            ("csrf", CSRF_PATTERNS, "medium", "log", "header"),
        ]

        for rule_type, patterns, severity, action, match_target in all_patterns:
            if rule_type not in self._enabled_rule_types:
                continue

            for pattern, name in patterns:
                rule_id += 1
                rule = {
                    "id": rule_id,
                    "name": f"{rule_type}_{name}",
                    "type": rule_type,
                    "pattern": pattern,
                    "severity": severity,
                    "action": action,
                    "match_target": match_target,
                    "is_builtin": True,
                    "is_active": True,
                    "hit_count": 0,
                }
                self._rules.append(rule)
                try:
                    self._compiled_patterns[rule_id] = re.compile(pattern, re.IGNORECASE)
                except re.error as e:
                    logger.warning("WAF rule %s has invalid regex: %s", rule.get("name", rule_id), e)

    def get_status(self) -> Dict[str, Any]:
        """获取 WAF 状态"""
        with self._lock:
            rules_by_type: Dict[str, int] = {}
            for rule in self._rules:
                rtype = rule["type"]
                rules_by_type[rtype] = rules_by_type.get(rtype, 0) + 1

            return {
                "enabled": self.enabled,
                "total_rules": len(self._rules),
                "active_rules": sum(1 for r in self._rules if r["is_active"]),
                "rules_by_type": rules_by_type,
                "today_blocks": self._stats["today_blocks"],
                "total_blocks": self._stats["total_blocks"],
                "total_checks": self._stats["total_checks"],
                "blocks_by_type": dict(self._stats.get("blocks_by_type", {})),
            }

    def get_performance_stats(self) -> Dict[str, Any]:
        """获取性能统计"""
        with self._lock:
            total_checks = self._stats["total_checks"]
            total_time_ns = self._stats.get("total_detection_time_ns", 0)
            avg_time_ns = total_time_ns / total_checks if total_checks > 0 else 0
            return {
                "total_checks": total_checks,
                "total_detection_time_ms": total_time_ns / 1_000_000.0,
                "avg_detection_time_ms": avg_time_ns / 1_000_000.0,
                "avg_detection_time_us": avg_time_ns / 1_000.0,
            }

    def check_request(
        self,
        method: str = "GET",
        path: str = "",
        query: str = "",
        body: str = "",
        headers: Optional[Dict[str, str]] = None,
        client_ip: str = "",
    ) -> Dict[str, Any]:
        """
        检测请求是否包含攻击特征

        Returns:
            {
                "passed": bool,
                "rule_name": str,
                "rule_type": str,
                "severity": str,
                "matched_content": str,
                "match_target": str,
                "detection_time_ns": int,
            }
        """
        start_ns = time.perf_counter_ns()

        if not self.enabled:
            elapsed = time.perf_counter_ns() - start_ns
            return {
                "passed": True, "rule_name": "", "rule_type": "",
                "severity": "", "matched_content": "",
                "match_target": "", "detection_time_ns": elapsed,
            }

        with self._lock:
            self._stats["total_checks"] += 1
            self._check_day_reset()

            decoded_query = unquote(query) if query else ""
            decoded_path = unquote(path) if path else ""
            decoded_body = unquote(body) if body else ""

            check_targets = {
                "path": decoded_path,
                "query": decoded_query,
                "body": decoded_body,
                "header": " ".join(f"{k}:{v}" for k, v in (headers or {}).items()),
            }

            for rule in self._rules:
                if not rule["is_active"]:
                    continue

                rule_id = rule["id"]
                match_target = rule["match_target"]
                compiled = self._compiled_patterns.get(rule_id)

                if compiled is None:
                    continue

                targets_to_check = []
                if match_target == "all":
                    targets_to_check = list(check_targets.items())
                elif match_target == "request":
                    # path + query + body（主要注入点，排除 header 减少误报）
                    targets_to_check = [
                        ("path", check_targets["path"]),
                        ("query", check_targets["query"]),
                        ("body", check_targets["body"]),
                    ]
                elif match_target == "path_query":
                    # path + query（路径遍历主要在路径和查询参数中）
                    targets_to_check = [
                        ("path", check_targets["path"]),
                        ("query", check_targets["query"]),
                    ]
                else:
                    if match_target in check_targets:
                        targets_to_check = [(match_target, check_targets[match_target])]

                for target_name, target_content in targets_to_check:
                    if not target_content:
                        continue

                    match = compiled.search(target_content)
                    if match:
                        rule["hit_count"] += 1
                        self._stats["total_blocks"] += 1
                        self._stats["today_blocks"] += 1

                        rtype = rule["type"]
                        blocks_by_type = self._stats.setdefault("blocks_by_type", {})
                        blocks_by_type[rtype] = blocks_by_type.get(rtype, 0) + 1

                        elapsed = time.perf_counter_ns() - start_ns
                        self._stats["total_detection_time_ns"] += elapsed

                        return {
                            "passed": False,
                            "rule_name": rule["name"],
                            "rule_type": rule["type"],
                            "severity": rule["severity"],
                            "matched_content": match.group(0)[:200],
                            "match_target": target_name,
                            "detection_time_ns": elapsed,
                        }

            elapsed = time.perf_counter_ns() - start_ns
            self._stats["total_detection_time_ns"] += elapsed
            return {
                "passed": True,
                "rule_name": "",
                "rule_type": "",
                "severity": "",
                "matched_content": "",
                "match_target": "",
                "detection_time_ns": elapsed,
            }

    def _check_day_reset(self) -> None:
        """检查并重置每日统计"""
        now = time.time()
        if now - self._stats["start_of_day"] >= DAY_SECONDS:
            self._stats["today_blocks"] = 0
            self._stats["start_of_day"] = now
            self._stats["blocks_by_type"] = {}


# ===========================================================================
# 配置辅助函数
# ===========================================================================

def _get_env_bool(name: str, default: bool = False) -> bool:
    """从环境变量读取布尔值"""
    val = os.environ.get(name, "")
    if val.lower() in ("true", "1", "yes", "on"):
        return True
    if val.lower() in ("false", "0", "no", "off"):
        return False
    return default


def _get_env_int(name: str, default: int) -> int:
    """从环境变量读取整数值"""
    try:
        return int(os.environ.get(name, default))
    except (ValueError, TypeError):
        return default


def _get_env_list(name: str, default: Optional[List[str]] = None) -> List[str]:
    """从环境变量读取逗号分隔的列表"""
    val = os.environ.get(name, "")
    if not val:
        return default or []
    return [item.strip() for item in val.split(",") if item.strip()]


# ===========================================================================
# 默认配置
# ===========================================================================

WAF_ENABLED = _get_env_bool("WAF_ENABLED", True)
WAF_MODE = os.environ.get("WAF_MODE", "block").lower()

# 验证模式
if WAF_MODE not in ("monitor", "block"):
    logger.warning("Invalid WAF_MODE: %s, using default 'block'", WAF_MODE)
    WAF_MODE = "block"

# 运行环境
_WAF_ENV = os.environ.get("YUNXI_ENV", os.environ.get("ENV", "development")).lower()
_WAF_IS_PRODUCTION = _WAF_ENV in ("production", "prod", "release")

# 生产环境 WAF 安全校验（SC-003 P1级）
if _WAF_IS_PRODUCTION:
    if not WAF_ENABLED:
        logger.critical(
            "[SC-003 P1] 生产环境安全告警：WAF 未启用（WAF_ENABLED=false）！\n"
            "生产环境必须启用 WAF 以提供 Web 应用防火墙防护。\n"
            "请设置 WAF_ENABLED=true。"
        )
    if WAF_MODE != "block":
        logger.critical(
            "[SC-003 P1] 生产环境安全告警：WAF 模式为 '%s'，攻击不会被拦截！\n"
            "生产环境 WAF 必须设为 block 模式才能真正拦截攻击。\n"
            "请设置 WAF_MODE=block。",
            WAF_MODE,
        )

# 启用的规则类型
WAF_RULE_TYPES = set(_get_env_list("WAF_RULE_TYPES")) or ALL_RULE_TYPES
# 过滤无效的规则类型
WAF_RULE_TYPES = WAF_RULE_TYPES & ALL_RULE_TYPES
if not WAF_RULE_TYPES:
    WAF_RULE_TYPES = ALL_RULE_TYPES

# 排除路径
WAF_EXCLUDE_PATHS: Set[str] = set(_get_env_list("WAF_EXCLUDE_PATHS"))
# 默认排除的路径
DEFAULT_EXCLUDE_PATHS: Set[str] = {
    "/health",
    "/m8/health",
    "/m8/metrics",
    "/m8/config",
    "/api/system/check",
    "/api/modules/status",
    "/api/waf/status",
    "/api/waf/stats",
    "/api/waf/health",
    "/docs",
    "/openapi.json",
    "/redoc",
    "/favicon.ico",
}
WAF_EXCLUDE_PATHS = WAF_EXCLUDE_PATHS | DEFAULT_EXCLUDE_PATHS

# 请求体检测限制（KB）
WAF_BODY_LIMIT_KB = _get_env_int("WAF_BODY_LIMIT_KB", 10)


# ===========================================================================
# WAF 中间件
# ===========================================================================

class WafMiddleware(BaseHTTPMiddleware):
    """
    WAF 中间件（内嵌引擎模式）

    直接集成 WAF 检测引擎，为 FastAPI 应用提供 Web 应用防火墙防护。
    零外部依赖，启动即可用，故障时自动降级。

    工作模式：
    - monitor：只检测不拦截，记录日志，不阻塞请求
    - block：同步检测，发现攻击立即返回 403

    降级策略：
    - WAF 引擎异常时自动降级，放行请求并记录告警
    """

    def __init__(
        self,
        app: ASGIApp,
        enabled: bool = None,
        mode: str = None,
        rule_types: Optional[Set[str]] = None,
        exclude_paths: Optional[Set[str]] = None,
        body_limit_kb: int = None,
    ):
        """初始化 WAF 中间件

        Args:
            app: ASGI 应用
            enabled: 是否启用 WAF
            mode: 工作模式（monitor/block）
            rule_types: 启用的规则类型集合
            exclude_paths: 排除的路径集合
            body_limit_kb: 请求体检测大小限制（KB）
        """
        super().__init__(app)
        self.enabled = enabled if enabled is not None else WAF_ENABLED
        self.mode = (mode or WAF_MODE).lower()
        self.rule_types = rule_types or WAF_RULE_TYPES
        self.exclude_paths = exclude_paths or WAF_EXCLUDE_PATHS
        self.body_limit_bytes = (body_limit_kb or WAF_BODY_LIMIT_KB) * 1024

        # 统计信息
        self._stats_lock = threading.Lock()
        self._stats = {
            "total_requests": 0,
            "checked_requests": 0,
            "blocked_requests": 0,
            "logged_attacks": 0,
            "degraded_count": 0,
            "error_count": 0,
        }

        # 初始化 WAF 引擎（故障降级：初始化失败也不影响启动）
        self._engine: Optional[WafEngineCore] = None
        self._engine_healthy = False
        try:
            self._engine = WafEngineCore(enabled_rule_types=self.rule_types)
            self._engine_healthy = True
            if self.enabled:
                logger.info(
                    "[WAF] 中间件已初始化 - 模式: %s, 规则: %d 条, 类型: %s",
                    self.mode,
                    self._engine.get_status()["total_rules"],
                    ", ".join(sorted(self.rule_types)),
                )
        except Exception as e:
            logger.error("[WAF] 引擎初始化失败，已降级（放行所有请求）: %s", e)
            self._engine_healthy = False

        if not self.enabled:
            logger.info("[WAF] 中间件已禁用")

        # 告警去重：同一 IP + 同一类型攻击，1 分钟内只触发一次告警
        self._alert_cooldown: Dict[str, float] = {}
        self._alert_cooldown_lock = threading.Lock()
        self._ALERT_COOLDOWN_SECONDS = 60  # 告警冷却时间（秒）

    def _trigger_waf_alert(self, client_ip: str, rule_type: str, rule_name: str, severity: str, path: str) -> None:
        """触发 WAF 攻击告警（带冷却去重）

        Args:
            client_ip: 客户端 IP
            rule_type: 攻击类型
            rule_name: 规则名称
            severity: 严重级别
            path: 请求路径
        """
        # 冷却去重键：IP + 攻击类型
        dedup_key = f"{client_ip}:{rule_type}"
        now = time.time()

        with self._alert_cooldown_lock:
            last_time = self._alert_cooldown.get(dedup_key, 0)
            if now - last_time < self._ALERT_COOLDOWN_SECONDS:
                return  # 冷却期内，不重复告警
            self._alert_cooldown[dedup_key] = now

            # 清理过期的冷却记录
            expired = [k for k, v in self._alert_cooldown.items() if now - v > self._ALERT_COOLDOWN_SECONDS * 10]
            for k in expired:
                del self._alert_cooldown[k]

        # 触发告警
        try:
            from .observability import get_alert_engine
            alert_engine = get_alert_engine()
            alert_engine.trigger_alert(
                rule_id="security_waf_attack_warning",
                value=None,
                labels={
                    "client_ip": client_ip,
                    "attack_type": rule_type,
                    "path": path[:100],
                },
                annotations={
                    "rule_name": rule_name,
                    "severity": severity,
                },
                summary=f"WAF检测到{rule_type}攻击",
                description=(
                    f"IP {client_ip} 在 {path[:100]} 路径触发 {rule_type} 攻击检测 "
                    f"(规则: {rule_name}, 级别: {severity})"
                ),
            )
        except Exception:
            # 告警失败不影响 WAF 功能
            pass

    async def dispatch(self, request: Request, call_next):
        """处理请求"""
        # WAF 未启用，直接放行
        if not self.enabled:
            return await call_next(request)

        # 引擎不健康，降级放行
        if not self._engine_healthy or self._engine is None:
            with self._stats_lock:
                self._stats["degraded_count"] += 1
            return await call_next(request)

        path = request.url.path
        with self._stats_lock:
            self._stats["total_requests"] += 1

        # 检查是否排除路径
        if self._is_excluded(path):
            return await call_next(request)

        # 提取请求信息
        try:
            request_info = await self._extract_request_info(request)
        except Exception as e:
            # 提取失败，降级放行
            with self._stats_lock:
                self._stats["error_count"] += 1
            logger.debug("[WAF] 请求信息提取失败，放行: %s", e)
            return await call_next(request)

        with self._stats_lock:
            self._stats["checked_requests"] += 1

        # 执行检测
        try:
            result = self._engine.check_request(
                method=request_info["method"],
                path=request_info["path"],
                query=request_info["query"],
                body=request_info["body"],
                headers=request_info["headers"],
                client_ip=request_info["client_ip"],
            )
        except Exception as e:
            # 检测异常，降级放行（安全优先：这里是故障降级，不是安全降级）
            with self._stats_lock:
                self._stats["degraded_count"] += 1
                self._stats["error_count"] += 1
            logger.warning("[WAF] 检测异常，降级放行: %s", e)
            return await call_next(request)

        # 根据检测结果和模式决定处理方式
        if not result["passed"]:
            if self.mode == "block":
                # 拦截模式：返回 403
                with self._stats_lock:
                    self._stats["blocked_requests"] += 1
                logger.warning(
                    "[WAF] 拦截攻击 - IP: %s, 路径: %s, 类型: %s, 规则: %s, 级别: %s, 位置: %s",
                    request_info["client_ip"],
                    path[:100],
                    result["rule_type"],
                    result["rule_name"],
                    result["severity"],
                    result["match_target"],
                )
                # 触发告警
                self._trigger_waf_alert(
                    client_ip=request_info["client_ip"],
                    rule_type=result["rule_type"],
                    rule_name=result["rule_name"],
                    severity=result["severity"],
                    path=path,
                )
                return JSONResponse(
                    status_code=status.HTTP_403_FORBIDDEN,
                    content={
                        "code": 403,
                        "message": "请求被安全防护系统拦截",
                        "data": {
                            "reason": f"{result['rule_type']} attack detected",
                            "rule_id": result["rule_name"],
                            "risk_level": result["severity"],
                            "match_target": result["match_target"],
                        },
                    },
                )
            else:
                # monitor 模式：只记录日志
                with self._stats_lock:
                    self._stats["logged_attacks"] += 1
                logger.info(
                    "[WAF] 检测到攻击（monitor 模式，未拦截）- IP: %s, 路径: %s, 类型: %s, 规则: %s",
                    request_info["client_ip"],
                    path[:100],
                    result["rule_type"],
                    result["rule_name"],
                )
                # monitor 模式也触发告警（INFO 级别）
                self._trigger_waf_alert(
                    client_ip=request_info["client_ip"],
                    rule_type=result["rule_type"],
                    rule_name=result["rule_name"],
                    severity=result["severity"],
                    path=path,
                )

        # 放行请求
        return await call_next(request)

    def _is_excluded(self, path: str) -> bool:
        """判断路径是否被排除"""
        # 精确匹配
        if path in self.exclude_paths:
            return True
        # 静态资源排除
        if path.endswith((".js", ".css", ".png", ".jpg", ".jpeg", ".gif", ".svg", ".ico", ".woff", ".woff2", ".ttf")):
            return True
        return False

    async def _extract_request_info(self, request: Request) -> dict:
        """提取请求信息用于 WAF 检测"""
        # 客户端 IP
        client_ip = self._get_client_ip(request)

        # 请求头
        headers = {}
        for key, value in request.headers.items():
            headers[key] = value

        # 查询字符串
        query = request.url.query or ""

        # 请求体（只检测有限大小）
        body = ""
        body_bytes = b""
        if request.method in ("POST", "PUT", "PATCH", "DELETE"):
            try:
                body_bytes = await request.body()
                if body_bytes and len(body_bytes) <= self.body_limit_bytes:
                    body = body_bytes.decode("utf-8", errors="ignore")
                # 重建请求体流，确保后续路由能正常读取
                if body_bytes:
                    await self._rebuild_request_body(request, body_bytes)
            except Exception as e:
                # 请求体读取/重建失败不阻断请求，WAF 降级为仅检测 header 和 query
                logger.debug("WAF 读取请求体失败: %s", e)
        return {
            "method": request.method,
            "path": request.url.path,
            "query": query,
            "headers": headers,
            "body": body,
            "client_ip": client_ip,
        }

    def _get_client_ip(self, request: Request) -> str:
        """获取客户端真实 IP"""
        forwarded_for = request.headers.get("x-forwarded-for")
        if forwarded_for:
            return forwarded_for.split(",")[0].strip()
        real_ip = request.headers.get("x-real-ip")
        if real_ip:
            return real_ip.strip()
        client = request.client
        if client:
            return client.host
        return "unknown"

    async def _rebuild_request_body(self, request: Request, body_bytes: bytes):
        """重建请求体流（Starlette 读取 body 后会消耗流）"""
        if not body_bytes:
            return
        try:
            original_receive = request._receive
            consumed = False

            async def receive():
                nonlocal consumed
                if not consumed:
                    consumed = True
                    return {
                        "type": "http.request",
                        "body": body_bytes,
                        "more_body": False,
                    }
                return await original_receive()

            request._receive = receive
        except Exception as e:
            # 请求体重建失败不影响主流程，WAF 降级即可
            logger.debug("WAF 重建请求体流失败: %s", e)

    def get_stats(self) -> dict:
        """获取中间件统计信息"""
        with self._stats_lock:
            stats = dict(self._stats)

        engine_status = {}
        engine_perf = {}
        if self._engine and self._engine_healthy:
            engine_status = self._engine.get_status()
            engine_perf = self._engine.get_performance_stats()

        return {
            "enabled": self.enabled,
            "mode": self.mode,
            "engine_healthy": self._engine_healthy,
            "rule_types": sorted(list(self.rule_types)),
            "middleware_stats": stats,
            "engine_status": engine_status,
            "performance": engine_perf,
        }

    def get_engine(self) -> Optional[WafEngineCore]:
        """获取 WAF 引擎实例"""
        return self._engine


# ===========================================================================
# 注册函数
# ===========================================================================

_waf_middleware_instance: Optional[WafMiddleware] = None
_waf_middleware_lock = threading.Lock()


def get_waf_middleware() -> Optional[WafMiddleware]:
    """获取 WAF 中间件单例（用于状态查询接口等）"""
    return _waf_middleware_instance


def register_waf_middleware(app, **kwargs) -> Optional[WafMiddleware]:
    """注册 WAF 中间件到 FastAPI 应用

    Args:
        app: FastAPI 应用实例
        **kwargs: 传递给 WafMiddleware 的参数

    Returns:
        WafMiddleware 实例，如果未启用返回 None
    """
    global _waf_middleware_instance

    enabled = kwargs.pop("enabled", None)
    if enabled is None:
        enabled = WAF_ENABLED

    if not enabled:
        logger.info("[WAF] WAF 中间件未启用（WAF_ENABLED=false）")
        return None

    with _waf_middleware_lock:
        middleware = WafMiddleware(app, enabled=enabled, **kwargs)
        app.add_middleware(WafMiddleware, enabled=enabled, **kwargs)
        _waf_middleware_instance = middleware

    return middleware


# ===========================================================================
# WAF 状态路由（可挂载到任何 FastAPI 应用）
# ===========================================================================

def create_waf_router(prefix: str = "/api/waf"):
    """创建 WAF 状态查询路由

    Args:
        prefix: 路由前缀

    Returns:
        FastAPI APIRouter 实例
    """
    from fastapi import APIRouter

    router = APIRouter(prefix=prefix, tags=["WAF-Web应用防火墙"])

    @router.get("/health", summary="WAF 健康检查")
    async def waf_health():
        """WAF 健康检查接口"""
        mw = get_waf_middleware()
        if mw is None:
            return {
                "code": 0,
                "message": "WAF not initialized",
                "data": {
                    "status": "not_initialized",
                    "enabled": False,
                },
            }

        stats = mw.get_stats()
        return {
            "code": 0,
            "message": "ok",
            "data": {
                "status": "healthy" if stats["engine_healthy"] else "degraded",
                "enabled": stats["enabled"],
                "mode": stats["mode"],
                "engine_healthy": stats["engine_healthy"],
            },
        }

    @router.get("/status", summary="WAF 状态查询")
    async def waf_status():
        """获取 WAF 当前运行状态"""
        mw = get_waf_middleware()
        if mw is None:
            return {
                "code": 0,
                "message": "WAF not initialized",
                "data": {"enabled": False},
            }

        return {
            "code": 0,
            "message": "ok",
            "data": mw.get_stats(),
        }

    @router.get("/stats", summary="WAF 统计信息")
    async def waf_stats():
        """获取 WAF 防护统计信息"""
        mw = get_waf_middleware()
        if mw is None:
            return {
                "code": 0,
                "message": "WAF not initialized",
                "data": {},
            }

        stats = mw.get_stats()
        return {
            "code": 0,
            "message": "ok",
            "data": {
                "enabled": stats["enabled"],
                "mode": stats["mode"],
                "engine_healthy": stats["engine_healthy"],
                "middleware": stats.get("middleware_stats", {}),
                "engine": stats.get("engine_status", {}),
                "performance": stats.get("performance", {}),
            },
        }

    return router
