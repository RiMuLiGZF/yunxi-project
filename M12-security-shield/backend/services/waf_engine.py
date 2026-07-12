"""
云汐 M12 安全盾 - WAF 检测引擎
实现 Web 应用防火墙核心检测逻辑，支持以下攻击类型检测：

1. SQL 注入检测 (SQL Injection)
2. 跨站脚本检测 (XSS - Cross-Site Scripting)
3. 跨站请求伪造检测 (CSRF)
4. 命令注入检测 (Command Injection)
5. 路径遍历检测 (Path Traversal)

使用正则表达式匹配和启发式规则进行检测，
支持自定义规则和动态规则加载。
"""

import re
import time
from typing import Dict, List, Optional, Any
from urllib.parse import unquote


# ===========================================================================
# 内置规则定义
# ===========================================================================

# SQL 注入检测规则
SQL_INJECTION_PATTERNS = [
    # 经典 SQL 注入
    (r"(?i)(\b(SELECT|INSERT|UPDATE|DELETE|DROP|CREATE|ALTER|TRUNCATE|EXEC|EXECUTE|UNION|GRANT|REVOKE)\b)", "sql_keyword"),
    # 注释符
    (r"(--|#|/\*|\*/)", "sql_comment"),
    # 单引号注入
    (r"('|%27).*(=|OR|AND|--)", "sql_quote_injection"),
    # 永真式
    (r"(?i)(\b1\s*=\s*1\b|\b'1'\s*=\s*'1'\b)", "sql_tautology"),
    # UNION 注入
    (r"(?i)\bUNION\b.*\bSELECT\b", "sql_union"),
    # 堆叠查询
    (r";\s*(SELECT|INSERT|UPDATE|DELETE|DROP|CREATE|EXEC)", "sql_stacked"),
]

# XSS 检测规则
XSS_PATTERNS = [
    # 脚本标签
    (r"(?i)<\s*script[^>]*>", "xss_script_tag"),
    # JavaScript 伪协议
    (r"(?i)javascript\s*:", "xss_javascript_protocol"),
    # 事件处理器
    (r"(?i)\bon\w+\s*=", "xss_event_handler"),
    # HTML 注入
    (r"(?i)<\s*(iframe|img|svg|body|input|form|a|div)[^>]*\bon\w+\s*=", "xss_html_event"),
    # eval 调用
    (r"(?i)eval\s*\(", "xss_eval"),
    # document.cookie / document.location
    (r"(?i)document\.(cookie|location|write)", "xss_document_access"),
    # 表达式注入
    (r"(?i)expression\s*\(", "xss_expression"),
    # VB Script
    (r"(?i)vbscript\s*:", "xss_vbscript"),
]

# 命令注入检测规则
COMMAND_INJECTION_PATTERNS = [
    # 管道符
    (r"[;&|`$]\s*(ls|cat|whoami|id|uname|ps|net|wget|curl|chmod|chown)", "cmd_pipe"),
    # 命令替换
    (r"\$\([^)]+\)|`[^`]+`", "cmd_substitution"),
    # Windows 命令
    (r"(?i)(\|\s*(dir|type|ipconfig|netstat|whoami|tasklist)|&\s*(dir|type|ipconfig))", "cmd_windows"),
    # 路径穿越执行
    (r"(?i)(/bin/|/sbin/|/usr/bin/|cmd\.exe|powershell)", "cmd_path_exec"),
    # 反引号执行
    (r"`[^`]+`", "cmd_backtick"),
]

# 路径遍历检测规则
PATH_TRAVERSAL_PATTERNS = [
    # 经典路径遍历
    (r"\.\./|\.\.\\", "path_traversal_dotdot"),
    # URL 编码的路径遍历
    (r"%2e%2e%2f|%2e%2e%5c", "path_traversal_encoded"),
    # 双写绕过
    (r"\.\.%2f|\.\.%5c", "path_traversal_double"),
    # 绝对路径访问
    (r"(?i)(/etc/passwd|/etc/shadow|/proc/|c:\\windows|c:\\winnt)", "path_traversal_absolute"),
]

# CSRF 检测规则（简化版）
CSRF_PATTERNS = [
    # 无 referer 的 POST 请求（在中间件层面检测）
    (r"(?i)(referer\s*:\s*none|origin\s*:\s*null)", "csrf_missing_origin"),
]


# ===========================================================================
# WAF 引擎类
# ===========================================================================

class WafEngine:
    """
    WAF 检测引擎

    提供 HTTP 请求的安全检测功能，支持多种攻击类型的检测和拦截。
    内置多种检测规则，同时支持自定义规则扩展。

    性能优化：
    - 预编译正则表达式，避免每次检测重新编译
    - 规则按类型分组，快速跳过不相关检测
    - 单次检测目标 < 1ms（正常请求路径）
    """

    def __init__(self):
        """初始化 WAF 引擎"""
        self.enabled = True
        self._rules: List[Dict[str, Any]] = []
        # 预编译正则缓存：rule_id -> compiled_pattern
        self._compiled_patterns: Dict[int, re.Pattern] = {}
        self._stats: Dict[str, Any] = {
            "total_checks": 0,
            "total_blocks": 0,
            "today_blocks": 0,
            "start_of_day": time.time(),
            "total_detection_time_ns": 0,
        }
        self._load_builtin_rules()

    def _load_builtin_rules(self) -> None:
        """加载内置规则并预编译正则表达式"""
        rule_id = 0

        all_patterns = [
            ("sql_injection", SQL_INJECTION_PATTERNS, "high", "block", "all"),
            ("xss", XSS_PATTERNS, "high", "block", "all"),
            ("command_injection", COMMAND_INJECTION_PATTERNS, "critical", "block", "all"),
            ("path_traversal", PATH_TRAVERSAL_PATTERNS, "high", "block", "all"),
            ("csrf", CSRF_PATTERNS, "medium", "log", "header"),
        ]

        for rule_type, patterns, severity, action, match_target in all_patterns:
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
                # 预编译正则表达式
                try:
                    self._compiled_patterns[rule_id] = re.compile(pattern, re.IGNORECASE)
                except re.error:
                    pass

    def enable(self) -> None:
        """启用 WAF"""
        self.enabled = True

    def disable(self) -> None:
        """禁用 WAF"""
        self.enabled = False

    def toggle(self) -> bool:
        """切换 WAF 开关状态

        Returns:
            切换后的状态
        """
        self.enabled = not self.enabled
        return self.enabled

    def get_rule_count(self) -> int:
        """获取规则总数

        Returns:
            规则总数
        """
        return len(self._rules)

    def get_active_rule_count(self) -> int:
        """获取启用的规则数

        Returns:
            启用的规则数
        """
        return sum(1 for r in self._rules if r["is_active"])

    def get_status(self) -> Dict[str, Any]:
        """获取 WAF 状态

        Returns:
            状态字典
        """
        rules_by_type: Dict[str, int] = {}
        for rule in self._rules:
            rtype = rule["type"]
            rules_by_type[rtype] = rules_by_type.get(rtype, 0) + 1

        return {
            "enabled": self.enabled,
            "total_rules": len(self._rules),
            "active_rules": self.get_active_rule_count(),
            "builtin_rules": sum(1 for r in self._rules if r["is_builtin"]),
            "custom_rules": sum(1 for r in self._rules if not r["is_builtin"]),
            "rules_by_type": rules_by_type,
            "today_blocks": self._stats["today_blocks"],
            "total_blocks": self._stats["total_blocks"],
            "total_checks": self._stats["total_checks"],
        }

    def get_rules(
        self,
        rule_type: Optional[str] = None,
        is_active: Optional[bool] = None,
    ) -> List[Dict[str, Any]]:
        """获取规则列表

        Args:
            rule_type: 按类型筛选
            is_active: 按启用状态筛选

        Returns:
            规则列表
        """
        rules = self._rules
        if rule_type:
            rules = [r for r in rules if r["type"] == rule_type]
        if is_active is not None:
            rules = [r for r in rules if r["is_active"] == is_active]
        return rules

    def add_rule(self, rule: Dict[str, Any]) -> Dict[str, Any]:
        """添加自定义规则

        Args:
            rule: 规则字典

        Returns:
            添加后的规则（含 ID）
        """
        new_id = max(r["id"] for r in self._rules) + 1 if self._rules else 1
        new_rule = {
            "id": new_id,
            "name": rule.get("name", f"custom_rule_{new_id}"),
            "type": rule.get("type", "custom"),
            "pattern": rule.get("pattern", ""),
            "severity": rule.get("severity", "medium"),
            "action": rule.get("action", "block"),
            "match_target": rule.get("match_target", "all"),
            "description": rule.get("description", ""),
            "is_builtin": False,
            "is_active": rule.get("is_active", True),
            "hit_count": 0,
        }
        self._rules.append(new_rule)
        # 预编译自定义规则的正则
        try:
            self._compiled_patterns[new_id] = re.compile(rule.get("pattern", ""), re.IGNORECASE)
        except re.error:
            pass
        return new_rule

    def update_rule(self, rule_id: int, updates: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """更新规则

        Args:
            rule_id: 规则 ID
            updates: 更新字段

        Returns:
            更新后的规则，不存在返回 None
        """
        for rule in self._rules:
            if rule["id"] == rule_id:
                for key, value in updates.items():
                    if key in rule and key not in ("id", "is_builtin"):
                        rule[key] = value
                # 如果 pattern 更新了，重新编译
                if "pattern" in updates:
                    try:
                        self._compiled_patterns[rule_id] = re.compile(updates["pattern"], re.IGNORECASE)
                    except re.error:
                        self._compiled_patterns.pop(rule_id, None)
                return rule
        return None

    def delete_rule(self, rule_id: int) -> bool:
        """删除规则（仅自定义规则可删除）

        Args:
            rule_id: 规则 ID

        Returns:
            是否删除成功
        """
        for i, rule in enumerate(self._rules):
            if rule["id"] == rule_id and not rule["is_builtin"]:
                self._rules.pop(i)
                self._compiled_patterns.pop(rule_id, None)
                return True
        return False

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

        性能优化：使用预编译正则表达式，正常请求检测 < 1ms

        Args:
            method: 请求方法
            path: 请求路径
            query: 查询字符串
            body: 请求体
            headers: 请求头字典
            client_ip: 客户端 IP

        Returns:
            检测结果字典
            {
                "passed": bool,       # 是否通过
                "rule_name": str,     # 触发的规则名称
                "rule_type": str,     # 规则类型
                "severity": str,      # 严重级别
                "action": str,        # 触发动作
                "matched_content": str,  # 匹配内容
                "match_target": str,  # 匹配位置
                "detection_time_ns": int,  # 检测耗时（纳秒）
            }
        """
        start_ns = time.perf_counter_ns()

        # 如果 WAF 未启用，直接通过
        if not self.enabled:
            elapsed = time.perf_counter_ns() - start_ns
            return {
                "passed": True, "rule_name": "", "rule_type": "",
                "severity": "", "action": "", "matched_content": "",
                "match_target": "", "detection_time_ns": elapsed,
            }

        self._stats["total_checks"] += 1
        self._check_day_reset()

        # URL 解码查询参数
        decoded_query = unquote(query) if query else ""
        decoded_path = unquote(path) if path else ""
        decoded_body = unquote(body) if body else ""

        # 拼接所有待检测内容
        check_targets = {
            "path": decoded_path,
            "query": decoded_query,
            "body": decoded_body,
            "header": " ".join(f"{k}:{v}" for k, v in (headers or {}).items()),
        }

        # 遍历规则进行检测（使用预编译正则）
        for rule in self._rules:
            if not rule["is_active"]:
                continue

            rule_id = rule["id"]
            match_target = rule["match_target"]
            compiled = self._compiled_patterns.get(rule_id)

            # 如果没有预编译的正则，跳过（规则无效）
            if compiled is None:
                continue

            # 确定需要检测的目标
            targets_to_check = []
            if match_target == "all":
                targets_to_check = list(check_targets.items())
            else:
                if match_target in check_targets:
                    targets_to_check = [(match_target, check_targets[match_target])]

            # 执行检测
            for target_name, target_content in targets_to_check:
                if not target_content:
                    continue

                match = compiled.search(target_content)
                if match:
                    # 命中规则
                    rule["hit_count"] += 1
                    self._stats["total_blocks"] += 1
                    self._stats["today_blocks"] += 1

                    elapsed = time.perf_counter_ns() - start_ns
                    self._stats["total_detection_time_ns"] += elapsed

                    matched_text = match.group(0)

                    return {
                        "passed": False,
                        "rule_name": rule["name"],
                        "rule_type": rule["type"],
                        "severity": rule["severity"],
                        "action": rule["action"],
                        "matched_content": matched_text[:200],
                        "match_target": target_name,
                        "detection_time_ns": elapsed,
                    }

        # 未命中任何规则，请求通过
        elapsed = time.perf_counter_ns() - start_ns
        self._stats["total_detection_time_ns"] += elapsed
        return {
            "passed": True,
            "rule_name": "",
            "rule_type": "",
            "severity": "",
            "action": "",
            "matched_content": "",
            "match_target": "",
            "detection_time_ns": elapsed,
        }

    def _check_day_reset(self) -> None:
        """检查并重置每日统计"""
        now = time.time()
        # 判断是否过了一天（86400秒）
        if now - self._stats["start_of_day"] >= 86400:
            self._stats["today_blocks"] = 0
            self._stats["start_of_day"] = now

    # -----------------------------------------------------------------------
    # 网关专用检测接口（高性能）
    # -----------------------------------------------------------------------

    def gateway_check(
        self,
        method: str = "GET",
        path: str = "",
        headers: Optional[Dict[str, str]] = None,
        body: str = "",
        client_ip: str = "",
        user_agent: str = "",
    ) -> Dict[str, Any]:
        """网关专用检测接口

        精简返回格式，方便网关快速判断是否拦截。
        使用预编译正则，性能 < 1ms。

        Args:
            method: HTTP 方法
            path: 请求路径
            headers: 请求头
            body: 请求体
            client_ip: 客户端 IP
            user_agent: 用户代理

        Returns:
            {
                "blocked": bool,       # 是否拦截
                "reason": str,         # 拦截原因
                "rule_id": str,        # 触发的规则名称
                "risk_level": str,     # 风险级别
                "detection_time_ms": float,  # 检测耗时（毫秒）
            }
        """
        result = self.check_request(
            method=method,
            path=path,
            query="",  # path 已包含完整路径信息
            body=body,
            headers=headers,
            client_ip=client_ip,
        )

        detection_time_ns = result.get("detection_time_ns", 0)
        detection_time_ms = detection_time_ns / 1_000_000.0

        if not result["passed"]:
            return {
                "blocked": True,
                "reason": f"{result['rule_type']} attack detected: {result['rule_name']}",
                "rule_id": result["rule_name"],
                "risk_level": result["severity"],
                "detection_time_ms": detection_time_ms,
            }

        return {
            "blocked": False,
            "reason": "",
            "rule_id": "",
            "risk_level": "low",
            "detection_time_ms": detection_time_ms,
        }

    def gateway_batch_check(
        self,
        requests: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        """批量检测接口

        Args:
            requests: 请求列表，每个元素包含 method/path/headers/body/client_ip/user_agent

        Returns:
            {
                "results": [...],      # 检测结果列表
                "total_count": int,    # 总检测数
                "blocked_count": int,  # 拦截数
                "total_time_ms": float, # 总耗时
            }
        """
        start_ns = time.perf_counter_ns()
        results = []
        blocked_count = 0

        for req in requests:
            result = self.gateway_check(
                method=req.get("method", "GET"),
                path=req.get("path", "/"),
                headers=req.get("headers", {}),
                body=req.get("body", ""),
                client_ip=req.get("client_ip", ""),
                user_agent=req.get("user_agent", ""),
            )
            if result["blocked"]:
                blocked_count += 1
            results.append(result)

        total_time_ms = (time.perf_counter_ns() - start_ns) / 1_000_000.0

        return {
            "results": results,
            "total_count": len(requests),
            "blocked_count": blocked_count,
            "total_time_ms": total_time_ms,
        }

    # -----------------------------------------------------------------------
    # 性能统计
    # -----------------------------------------------------------------------

    def get_performance_stats(self) -> Dict[str, Any]:
        """获取性能统计信息

        Returns:
            性能统计字典
        """
        total_checks = self._stats["total_checks"]
        total_time_ns = self._stats.get("total_detection_time_ns", 0)
        avg_time_ns = total_time_ns / total_checks if total_checks > 0 else 0

        return {
            "total_checks": total_checks,
            "total_detection_time_ms": total_time_ns / 1_000_000.0,
            "avg_detection_time_ms": avg_time_ns / 1_000_000.0,
            "avg_detection_time_us": avg_time_ns / 1_000.0,
        }


# ===========================================================================
# 单例管理
# ===========================================================================

_waf_engine: Optional[WafEngine] = None


def get_waf_engine() -> WafEngine:
    """获取 WAF 引擎单例

    Returns:
        WafEngine 实例
    """
    global _waf_engine
    if _waf_engine is None:
        _waf_engine = WafEngine()
    return _waf_engine


# 兼容直接运行测试
if __name__ == "__main__":
    engine = get_waf_engine()
    print(f"WAF 引擎已初始化")
    print(f"规则总数: {engine.get_rule_count()}")
    print(f"启用规则: {engine.get_active_rule_count()}")
    print()

    # 测试 SQL 注入检测
    result = engine.check_request(
        method="GET",
        path="/api/test",
        query="id=1' OR '1'='1",
    )
    print(f"SQL 注入测试: {'拦截' if not result['passed'] else '通过'}")
    if not result["passed"]:
        print(f"  规则: {result['rule_name']}")
        print(f"  类型: {result['rule_type']}")

    # 测试 XSS 检测
    result = engine.check_request(
        method="GET",
        path="/api/test",
        query="q=<script>alert(1)</script>",
    )
    print(f"XSS 测试: {'拦截' if not result['passed'] else '通过'}")
    if not result["passed"]:
        print(f"  规则: {result['rule_name']}")
        print(f"  类型: {result['rule_type']}")

    # 测试正常请求
    result = engine.check_request(
        method="GET",
        path="/api/test",
        query="page=1&size=10",
    )
    print(f"正常请求测试: {'拦截' if not result['passed'] else '通过'}")
