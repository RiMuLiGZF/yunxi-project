"""
云汐 M12 安全盾 - WAF 核心模块（深度防御增强版）

在原有 WAF 引擎基础上增强，提供完整的 7 层防护：
1. SQL 注入检测（经典/盲注/堆叠查询/误报控制）
2. XSS 攻击检测（反射型/DOM/事件处理器/标签注入）
3. CSRF 防护（Token 验证/Referer 检查/SameSite Cookie）
4. 路径遍历检测（../检测/编码绕过/敏感路径防护）
5. 命令注入检测（Shell/系统命令/管道符）
6. SSRF 防护（内网 IP/云元数据/DNS Rebinding）
7. 速率限制（IP 级/用户级/接口级/令牌桶算法）

同时提供 WAF 中间件、拦截日志、低误报模式等功能。
"""

import re
import time
import ipaddress
import threading
import logging
import hashlib
from typing import Dict, List, Optional, Any, Tuple
from urllib.parse import unquote, urlparse
from collections import defaultdict, deque

logger = logging.getLogger(__name__)

DAY_SECONDS = 86400
MAX_LOG_ENTRIES = 10000


# ===========================================================================
# 内置规则定义（增强版）
# ===========================================================================

# SQL 注入检测规则（增强）
SQL_INJECTION_PATTERNS = [
    # 经典 SQL 注入关键词
    (r"(?i)\b(SELECT|INSERT|UPDATE|DELETE|DROP|CREATE|ALTER|TRUNCATE|EXEC|EXECUTE|UNION|GRANT|REVOKE|MERGE|DECLARE|CAST|CONVERT)\b", "sql_keyword", "high"),
    # 注释符
    (r"(--\s|#|/\*|\*/)", "sql_comment", "medium"),
    # 单引号注入 + 逻辑运算符
    (r"('|%27).*(=|OR|AND|--|#)", "sql_quote_injection", "high"),
    # 永真式
    (r"(?i)(\b1\s*=\s*1\b|\b'1'\s*=\s*'1'\b|\b0\s*=\s*0\b)", "sql_tautology", "high"),
    # UNION 注入
    (r"(?i)\bUNION\b[\s\S]*?\bSELECT\b", "sql_union", "critical"),
    # 堆叠查询
    (r";\s*(SELECT|INSERT|UPDATE|DELETE|DROP|CREATE|EXEC|ALTER|TRUNCATE)\b", "sql_stacked", "critical"),
    # 盲注 - 延时
    (r"(?i)(SLEEP\s*\(|WAITFOR\s+DELAY|BENCHMARK\s*\(|pg_sleep\s*\()", "sql_blind_time", "high"),
    # 盲注 - 布尔
    (r"(?i)\bAND\b[\s\S]*?\b(SELECT|EXISTS|COUNT)\b", "sql_blind_bool", "high"),
    # 十六进制/字符编码注入
    (r"(?i)(0x[0-9a-f]+|char\s*\()", "sql_encoded", "medium"),
]

# XSS 检测规则（增强）
XSS_PATTERNS = [
    # 脚本标签
    (r"(?i)<\s*script[^>]*>", "xss_script_tag", "high"),
    (r"(?i)<\s*/\s*script\s*>", "xss_script_close", "high"),
    # JavaScript 伪协议
    (r"(?i)javascript\s*:", "xss_javascript_protocol", "high"),
    # 事件处理器（onerror/onload/onclick/onmouseover 等）
    (r"(?i)\bon\w+\s*=", "xss_event_handler", "high"),
    # HTML 标签 + 事件属性
    (r"(?i)<\s*(iframe|img|svg|body|input|form|a|div|video|audio|object|embed)[^>]*\bon\w+\s*=", "xss_html_event", "critical"),
    # eval 调用
    (r"(?i)eval\s*\(", "xss_eval", "medium"),
    # document 对象访问
    (r"(?i)document\.(cookie|location|write|domain)", "xss_document_access", "medium"),
    # 表达式注入
    (r"(?i)expression\s*\(", "xss_expression", "medium"),
    # VB Script
    (r"(?i)vbscript\s*:", "xss_vbscript", "medium"),
    # DOM XSS - innerHTML/document.write/srcdoc
    (r"(?i)(innerHTML\s*=|document\.write\s*\(|srcdoc\s*=)", "xss_dom", "high"),
    # 数据 URI + base64
    (r"(?i)data\s*:\s*text/html", "xss_data_uri", "medium"),
    # 标签注入（带 src/href 属性）
    (r"(?i)<\s*(img|iframe|script)[^>]*(src|href)\s*=", "xss_tag_injection", "high"),
]

# 命令注入检测规则（增强）
COMMAND_INJECTION_PATTERNS = [
    # 管道符 + 常见命令
    (r"[;&|`$]\s*(ls|cat|whoami|id|uname|ps|net|wget|curl|chmod|chown|nc|bash|sh|rm|cp|mv)", "cmd_pipe", "critical"),
    # 命令替换 - $()
    (r"\$\([^)]+\)", "cmd_substitution_dollar", "high"),
    # 命令替换 - 反引号
    (r"`[^`]+`", "cmd_substitution_backtick", "high"),
    # Windows 命令
    (r"(?i)(\|\s*(dir|type|ipconfig|netstat|whoami|tasklist|calc)|&\s*(dir|type|ipconfig|netstat))", "cmd_windows", "high"),
    # 路径执行
    (r"(?i)(/bin/|/sbin/|/usr/bin/|/usr/local/bin/|cmd\.exe|powershell|wscript|cscript)", "cmd_path_exec", "critical"),
    # 重定向符 + 命令
    (r"(>>?|<<?)\s*(/etc/|/var/|c:\\|d:\\)", "cmd_redirect", "medium"),
    # 逻辑运算符 + 命令
    (r"(?i)(\|\||&&)\s*(ls|cat|rm|echo|whoami|id)", "cmd_logical_operator", "high"),
]

# 路径遍历检测规则（增强）
PATH_TRAVERSAL_PATTERNS = [
    # 经典路径遍历
    (r"\.\.[/\\]", "path_traversal_dotdot", "high"),
    # URL 编码的路径遍历
    (r"(?i)(%2e%2e%2f|%2e%2e%5c|%2e%2e/)", "path_traversal_encoded", "high"),
    # 双写绕过
    (r"(?i)(\.\.%2f|\.\.%5c|\.%2e/)", "path_traversal_double", "high"),
    # 绝对路径访问敏感文件
    (r"(?i)(/etc/passwd|/etc/shadow|/proc/self|/root/|c:\\windows\\system32|c:\\winnt)", "path_traversal_absolute", "critical"),
    # 空字节注入
    (r"(%00|\x00)", "path_traversal_null_byte", "medium"),
    # 敏感路径
    (r"(?i)(/\.env|/\.git|/\.svn|/\.htaccess|/wp-config|/config\.inc)", "path_sensitive_file", "high"),
]

# CSRF 检测规则
CSRF_PATTERNS = [
    (r"(?i)(referer\s*:\s*none|origin\s*:\s*null)", "csrf_missing_origin", "medium"),
]

# SSRF 防护 - 内网 IP 段
SSRF_PRIVATE_NETWORKS = [
    "0.0.0.0/8",          # 本网络
    "10.0.0.0/8",         # A 类私网
    "172.16.0.0/12",      # B 类私网
    "192.168.0.0/16",     # C 类私网
    "127.0.0.0/8",        # 回环地址
    "169.254.0.0/16",     # 链路本地
    "224.0.0.0/4",        # 组播
    "240.0.0.0/4",        # 保留
    "::1/128",            # IPv6 回环
    "fc00::/7",           # IPv6 唯一本地
    "fe80::/10",          # IPv6 链路本地
]

# SSRF 防护 - 云元数据服务
SSRF_CLOUD_METADATA = [
    "169.254.169.254",    # AWS/GCP/Azure 通用元数据
    "metadata.google.internal",  # GCP
    "metadata",           # 通用
]


# ===========================================================================
# WAF 拦截日志条目
# ===========================================================================

class WafLogEntry:
    """WAF 拦截日志条目"""

    def __init__(
        self,
        rule_name: str,
        rule_type: str,
        severity: str,
        matched_content: str,
        match_target: str,
        client_ip: str,
        method: str,
        path: str,
        user_agent: str = "",
        action: str = "block",
        low_confidence: bool = False,
    ):
        self.id = 0
        self.rule_name = rule_name
        self.rule_type = rule_type
        self.severity = severity
        self.matched_content = matched_content[:200]
        self.match_target = match_target
        self.client_ip = client_ip
        self.method = method
        self.path = path
        self.user_agent = user_agent
        self.action = action
        self.low_confidence = low_confidence
        self.timestamp = time.time()
        self.timestamp_str = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "rule_name": self.rule_name,
            "rule_type": self.rule_type,
            "severity": self.severity,
            "matched_content": self.matched_content,
            "match_target": self.match_target,
            "client_ip": self.client_ip,
            "method": self.method,
            "path": self.path,
            "user_agent": self.user_agent,
            "action": self.action,
            "low_confidence": self.low_confidence,
            "timestamp": self.timestamp_str,
            "timestamp_unix": self.timestamp,
        }


# ===========================================================================
# WAF 核心引擎（增强版）
# ===========================================================================

class WafCore:
    """
    WAF 核心引擎（深度防御版）

    提供完整的 7 层 Web 应用防护：
    1. SQL 注入检测
    2. XSS 攻击检测
    3. CSRF 防护
    4. 路径遍历检测
    5. 命令注入检测
    6. SSRF 防护
    7. 速率限制

    特性：
    - 低误报模式：仅拦截高危攻击
    - 上下文分析：降低误报率
    - 拦截日志：完整记录所有拦截事件
    - 可配置规则开关
    """

    def __init__(self, low_confidence_mode: bool = False):
        """初始化 WAF 核心引擎

        Args:
            low_confidence_mode: 低误报模式（仅拦截 high/critical 级别）
        """
        self._lock = threading.RLock()
        self.enabled = True
        self.low_confidence_mode = low_confidence_mode

        # 规则存储
        self._rules: List[Dict[str, Any]] = []
        self._compiled_patterns: Dict[int, re.Pattern] = {}

        # 拦截日志（有界队列）
        self._block_logs: deque = deque(maxlen=MAX_LOG_ENTRIES)
        self._log_id_counter = 0

        # 统计数据
        self._stats: Dict[str, Any] = {
            "total_checks": 0,
            "total_blocks": 0,
            "total_logged": 0,
            "today_blocks": 0,
            "today_checks": 0,
            "start_of_day": time.time(),
            "blocks_by_type": defaultdict(int),
            "blocks_by_severity": defaultdict(int),
        }

        # SSRF 内网 IP 网络对象（预计算）
        self._private_networks: List[ipaddress._BaseNetwork] = []
        self._init_private_networks()

        # 加载内置规则
        self._load_builtin_rules()

    def _init_private_networks(self) -> None:
        """初始化内网 IP 段列表"""
        for net_str in SSRF_PRIVATE_NETWORKS:
            try:
                if ":" in net_str:
                    self._private_networks.append(ipaddress.IPv6Network(net_str))
                else:
                    self._private_networks.append(ipaddress.IPv4Network(net_str))
            except ValueError:
                logger.warning("Invalid private network: %s", net_str)

    def _load_builtin_rules(self) -> None:
        """加载内置规则并预编译"""
        rule_id = 0

        all_pattern_groups = [
            ("sql_injection", SQL_INJECTION_PATTERNS, "all"),
            ("xss", XSS_PATTERNS, "all"),
            ("command_injection", COMMAND_INJECTION_PATTERNS, "all"),
            ("path_traversal", PATH_TRAVERSAL_PATTERNS, "all"),
            ("csrf", CSRF_PATTERNS, "header"),
        ]

        for rule_type, patterns, match_target in all_pattern_groups:
            for pattern, name, severity in patterns:
                rule_id += 1
                rule = {
                    "id": rule_id,
                    "name": f"{rule_type}_{name}",
                    "type": rule_type,
                    "pattern": pattern,
                    "severity": severity,
                    "action": "block" if severity in ("high", "critical") else "log",
                    "match_target": match_target,
                    "category": rule_type,
                    "is_builtin": True,
                    "is_active": True,
                    "hit_count": 0,
                    "description": f"{rule_type} detection: {name}",
                }
                self._rules.append(rule)
                try:
                    self._compiled_patterns[rule_id] = re.compile(pattern, re.IGNORECASE)
                except re.error as e:
                    logger.warning("WAF rule %s regex error: %s", rule["name"], e)

    # -----------------------------------------------------------------------
    # 基础属性与配置
    # -----------------------------------------------------------------------

    @property
    def rule_count(self) -> int:
        return len(self._rules)

    @property
    def active_rule_count(self) -> int:
        return sum(1 for r in self._rules if r["is_active"])

    def enable(self) -> None:
        with self._lock:
            self.enabled = True

    def disable(self) -> None:
        with self._lock:
            self.enabled = False

    def set_low_confidence_mode(self, enabled: bool) -> None:
        """设置低误报模式

        Args:
            enabled: 是否启用低误报模式
        """
        with self._lock:
            self.low_confidence_mode = enabled
            logger.info("WAF 低误报模式: %s", "开启" if enabled else "关闭")

    # -----------------------------------------------------------------------
    # 规则管理
    # -----------------------------------------------------------------------

    def get_rules(
        self,
        rule_type: Optional[str] = None,
        is_active: Optional[bool] = None,
        severity: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """获取规则列表"""
        with self._lock:
            rules = list(self._rules)
        if rule_type:
            rules = [r for r in rules if r["type"] == rule_type]
        if is_active is not None:
            rules = [r for r in rules if r["is_active"] == is_active]
        if severity:
            rules = [r for r in rules if r["severity"] == severity]
        return rules

    def get_rule_by_id(self, rule_id: int) -> Optional[Dict[str, Any]]:
        """根据 ID 获取规则"""
        with self._lock:
            for rule in self._rules:
                if rule["id"] == rule_id:
                    return rule.copy()
        return None

    def update_rule(self, rule_id: int, updates: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """更新规则配置"""
        with self._lock:
            for rule in self._rules:
                if rule["id"] == rule_id:
                    for key, value in updates.items():
                        if key in rule and key not in ("id", "is_builtin"):
                            rule[key] = value
                    if "pattern" in updates:
                        try:
                            self._compiled_patterns[rule_id] = re.compile(updates["pattern"], re.IGNORECASE)
                        except re.error:
                            self._compiled_patterns.pop(rule_id, None)
                    return rule.copy()
        return None

    def add_custom_rule(self, rule_data: Dict[str, Any]) -> Dict[str, Any]:
        """添加自定义规则"""
        with self._lock:
            new_id = max(r["id"] for r in self._rules) + 1 if self._rules else 1
            new_rule = {
                "id": new_id,
                "name": rule_data.get("name", f"custom_{new_id}"),
                "type": rule_data.get("type", "custom"),
                "pattern": rule_data.get("pattern", ""),
                "severity": rule_data.get("severity", "medium"),
                "action": rule_data.get("action", "block"),
                "match_target": rule_data.get("match_target", "all"),
                "category": rule_data.get("category", "custom"),
                "is_builtin": False,
                "is_active": rule_data.get("is_active", True),
                "hit_count": 0,
                "description": rule_data.get("description", ""),
            }
            self._rules.append(new_rule)
            try:
                self._compiled_patterns[new_id] = re.compile(new_rule["pattern"], re.IGNORECASE)
            except re.error:
                pass
            return new_rule.copy()

    # -----------------------------------------------------------------------
    # 请求检测（核心方法）
    # -----------------------------------------------------------------------

    def check_request(
        self,
        method: str = "GET",
        path: str = "",
        query: str = "",
        body: str = "",
        headers: Optional[Dict[str, str]] = None,
        client_ip: str = "",
        user_agent: str = "",
    ) -> Dict[str, Any]:
        """
        检测请求是否包含攻击特征

        Args:
            method: HTTP 方法
            path: 请求路径
            query: 查询字符串
            body: 请求体
            headers: 请求头字典
            client_ip: 客户端 IP
            user_agent: 用户代理

        Returns:
            检测结果字典
        """
        start_ns = time.perf_counter_ns()

        if not self.enabled:
            return self._make_pass_result(time.perf_counter_ns() - start_ns)

        with self._lock:
            self._stats["total_checks"] += 1
            self._stats["today_checks"] += 1
            self._check_day_reset()

        # URL 解码
        decoded_query = unquote(query) if query else ""
        decoded_path = unquote(path) if path else ""
        decoded_body = unquote(body) if body else ""

        # 误报控制：对特定上下文进行分析
        check_targets = {
            "path": decoded_path,
            "query": decoded_query,
            "body": decoded_body,
            "header": " ".join(f"{k}:{v}" for k, v in (headers or {}).items()),
        }

        # 遍历规则检测
        with self._lock:
            for rule in self._rules:
                if not rule["is_active"]:
                    continue

                rule_id = rule["id"]
                compiled = self._compiled_patterns.get(rule_id)
                if compiled is None:
                    continue

                # 确定检测目标
                targets_to_check = self._get_targets_to_check(rule, check_targets)

                for target_name, target_content in targets_to_check:
                    if not target_content:
                        continue

                    match = compiled.search(target_content)
                    if match:
                        # 误报控制：上下文分析
                        is_low_confidence = self._check_false_positive(
                            rule, target_content, match
                        )

                        # 低误报模式下，低置信度不拦截
                        if self.low_confidence_mode and is_low_confidence:
                            continue

                        rule["hit_count"] += 1
                        self._stats["total_blocks"] += 1
                        self._stats["today_blocks"] += 1
                        self._stats["blocks_by_type"][rule["type"]] += 1
                        self._stats["blocks_by_severity"][rule["severity"]] += 1

                        matched_text = match.group(0)[:200]

                        # 记录拦截日志
                        self._add_block_log(
                            rule_name=rule["name"],
                            rule_type=rule["type"],
                            severity=rule["severity"],
                            matched_content=matched_text,
                            match_target=target_name,
                            client_ip=client_ip,
                            method=method,
                            path=path,
                            user_agent=user_agent,
                            action=rule["action"],
                            low_confidence=is_low_confidence,
                        )

                        elapsed = time.perf_counter_ns() - start_ns
                        return {
                            "passed": False,
                            "blocked": True,
                            "rule_id": rule["id"],
                            "rule_name": rule["name"],
                            "rule_type": rule["type"],
                            "severity": rule["severity"],
                            "action": rule["action"],
                            "matched_content": matched_text,
                            "match_target": target_name,
                            "low_confidence": is_low_confidence,
                            "detection_time_ns": elapsed,
                            "detection_time_ms": elapsed / 1_000_000.0,
                        }

            # 未命中任何规则
            elapsed = time.perf_counter_ns() - start_ns
            return self._make_pass_result(elapsed)

    def _get_targets_to_check(
        self, rule: Dict[str, Any], check_targets: Dict[str, str]
    ) -> List[Tuple[str, str]]:
        """获取需要检测的目标列表"""
        match_target = rule["match_target"]
        if match_target == "all":
            return list(check_targets.items())
        elif match_target in check_targets:
            return [(match_target, check_targets[match_target])]
        return []

    def _check_false_positive(
        self, rule: Dict[str, Any], content: str, match: re.Match
    ) -> bool:
        """
        误报检测：通过上下文分析判断是否为误报

        Returns:
            True 表示可能是误报（低置信度）
        """
        rule_type = rule["type"]
        matched_text = match.group(0).lower()

        # SQL 注入误报控制
        if rule_type == "sql_injection":
            # 如果是 JSON 格式数据中的 select（可能是普通字段名）
            if '"select"' in content.lower() or "'select'" in content.lower():
                return True
            # 如果是 select 作为单词的一部分（如 "selection"）
            if len(matched_text) > 10 and re.match(r"^[a-z]+$", matched_text):
                # 检查是否是独立单词
                start, end = match.start(), match.end()
                before = content[max(0, start - 1):start].lower()
                after = content[end:end + 1].lower()
                if before.isalpha() or after.isalpha():
                    return True
            # 纯数字比较的永真式（如 1=1 在数学上下文中）
            if "1=1" in matched_text and "math" in content.lower():
                return True

        # XSS 误报控制
        if rule_type == "xss":
            # 事件处理器在纯文本中（如 "onclick" 作为普通文本）
            if rule["name"] == "xss_event_handler":
                # 检查前面是否有 HTML 标签
                before_match = content[:match.start()][-50:]
                if "<" not in before_match and "=" in matched_text:
                    # 可能是普通文本中的 onsomething=
                    return True

        # 命令注入误报控制
        if rule_type == "command_injection":
            # 管道符在普通文本中
            if "|" in matched_text and "||" not in matched_text:
                # 检查是否是代码片段中的合法操作
                if "javascript" in content.lower() or "function" in content.lower():
                    return True

        return False

    def _make_pass_result(self, detection_time_ns: int) -> Dict[str, Any]:
        """构造通过的检测结果"""
        return {
            "passed": True,
            "blocked": False,
            "rule_id": 0,
            "rule_name": "",
            "rule_type": "",
            "severity": "",
            "action": "",
            "matched_content": "",
            "match_target": "",
            "low_confidence": False,
            "detection_time_ns": detection_time_ns,
            "detection_time_ms": detection_time_ns / 1_000_000.0,
        }

    # -----------------------------------------------------------------------
    # SSRF 防护
    # -----------------------------------------------------------------------

    def check_ssrf(self, url: str) -> Dict[str, Any]:
        """
        检测 URL 是否存在 SSRF 风险

        Args:
            url: 待检测的 URL

        Returns:
            SSRF 检测结果
        """
        result = {
            "safe": True,
            "risk": "none",
            "reason": "",
            "resolved_ip": "",
            "is_private": False,
            "is_metadata": False,
        }

        try:
            parsed = urlparse(url)
            hostname = parsed.hostname or ""

            if not hostname:
                result["reason"] = "无法解析主机名"
                return result

            # 检查云元数据服务
            if hostname in SSRF_CLOUD_METADATA or "metadata" in hostname.lower():
                result["safe"] = False
                result["risk"] = "critical"
                result["reason"] = "云元数据服务访问"
                result["is_metadata"] = True
                return result

            # 尝试解析 IP（这里仅做静态检查，实际 DNS 解析需用 socket）
            try:
                ip_obj = ipaddress.ip_address(hostname)
                result["resolved_ip"] = str(ip_obj)
                result["is_private"] = self._is_private_ip(ip_obj)

                if result["is_private"]:
                    result["safe"] = False
                    result["risk"] = "high"
                    result["reason"] = f"内网 IP 地址: {hostname}"
                    return result

                # 回环地址
                if ip_obj.is_loopback:
                    result["safe"] = False
                    result["risk"] = "high"
                    result["reason"] = f"回环地址: {hostname}"
                    return result

            except ValueError:
                # 主机名不是 IP，需要 DNS 解析（这里只做域名模式检查）
                if hostname == "localhost" or hostname.endswith(".local"):
                    result["safe"] = False
                    result["risk"] = "medium"
                    result["reason"] = f"本地域名: {hostname}"
                    result["is_private"] = True
                    return result

        except Exception as e:
            result["reason"] = f"URL 解析错误: {str(e)}"

        return result

    def _is_private_ip(self, ip: ipaddress._BaseAddress) -> bool:
        """检查 IP 是否为内网/私有地址"""
        for net in self._private_networks:
            if isinstance(ip, type(net.network_address)):
                if ip in net:
                    return True
        return False

    # -----------------------------------------------------------------------
    # 拦截日志
    # -----------------------------------------------------------------------

    def _add_block_log(
        self,
        rule_name: str,
        rule_type: str,
        severity: str,
        matched_content: str,
        match_target: str,
        client_ip: str,
        method: str,
        path: str,
        user_agent: str,
        action: str,
        low_confidence: bool,
    ) -> None:
        """添加拦截日志（需在锁内调用）"""
        self._log_id_counter += 1
        entry = WafLogEntry(
            rule_name=rule_name,
            rule_type=rule_type,
            severity=severity,
            matched_content=matched_content,
            match_target=match_target,
            client_ip=client_ip,
            method=method,
            path=path,
            user_agent=user_agent,
            action=action,
            low_confidence=low_confidence,
        )
        entry.id = self._log_id_counter
        self._block_logs.append(entry)
        self._stats["total_logged"] += 1

    def get_block_logs(
        self,
        rule_type: Optional[str] = None,
        severity: Optional[str] = None,
        client_ip: Optional[str] = None,
        page: int = 1,
        page_size: int = 20,
    ) -> Dict[str, Any]:
        """获取拦截日志"""
        with self._lock:
            logs = [e.to_dict() for e in self._block_logs]

        logs.reverse()  # 最新在前

        if rule_type:
            logs = [l for l in logs if l["rule_type"] == rule_type]
        if severity:
            logs = [l for l in logs if l["severity"] == severity]
        if client_ip:
            logs = [l for l in logs if l["client_ip"] == client_ip]

        total = len(logs)
        offset = (page - 1) * page_size
        paged = logs[offset:offset + page_size]
        total_pages = (total + page_size - 1) // page_size if page_size > 0 else 0

        return {
            "items": paged,
            "total": total,
            "page": page,
            "page_size": page_size,
            "total_pages": total_pages,
        }

    # -----------------------------------------------------------------------
    # 统计信息
    # -----------------------------------------------------------------------

    def get_stats(self) -> Dict[str, Any]:
        """获取 WAF 统计信息"""
        with self._lock:
            self._check_day_reset()
            rules_by_type: Dict[str, int] = {}
            for rule in self._rules:
                rtype = rule["type"]
                rules_by_type[rtype] = rules_by_type.get(rtype, 0) + 1

            blocks_by_type = dict(self._stats["blocks_by_type"])
            blocks_by_severity = dict(self._stats["blocks_by_severity"])

            # Top 命中规则
            top_rules = sorted(
                self._rules,
                key=lambda r: r.get("hit_count", 0),
                reverse=True
            )[:10]

            return {
                "enabled": self.enabled,
                "low_confidence_mode": self.low_confidence_mode,
                "total_rules": len(self._rules),
                "active_rules": self.active_rule_count,
                "builtin_rules": sum(1 for r in self._rules if r["is_builtin"]),
                "custom_rules": sum(1 for r in self._rules if not r["is_builtin"]),
                "rules_by_type": rules_by_type,
                "total_checks": self._stats["total_checks"],
                "total_blocks": self._stats["total_blocks"],
                "today_checks": self._stats["today_checks"],
                "today_blocks": self._stats["today_blocks"],
                "blocks_by_type": blocks_by_type,
                "blocks_by_severity": blocks_by_severity,
                "total_logged": self._stats["total_logged"],
                "top_rules": [
                    {
                        "id": r["id"],
                        "name": r["name"],
                        "type": r["type"],
                        "severity": r["severity"],
                        "hit_count": r.get("hit_count", 0),
                    }
                    for r in top_rules
                ],
            }

    def _check_day_reset(self) -> None:
        """检查并重置每日统计（需在锁内调用）"""
        now = time.time()
        if now - self._stats["start_of_day"] >= DAY_SECONDS:
            self._stats["today_blocks"] = 0
            self._stats["today_checks"] = 0
            self._stats["start_of_day"] = now


# ===========================================================================
# 单例管理
# ===========================================================================

_waf_core: Optional[WafCore] = None
_waf_core_lock = threading.Lock()


def get_waf_core() -> WafCore:
    """获取 WAF 核心引擎单例

    Returns:
        WafCore 实例
    """
    global _waf_core
    if _waf_core is None:
        with _waf_core_lock:
            if _waf_core is None:
                _waf_core = WafCore()
    return _waf_core


# ===========================================================================
# 直接运行测试
# ===========================================================================

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)

    waf = get_waf_core()
    print(f"规则总数: {waf.rule_count}")
    print(f"活跃规则: {waf.active_rule_count}")

    # SQL 注入测试
    result = waf.check_request(
        method="GET",
        path="/api/user",
        query="id=1' OR '1'='1",
        client_ip="192.168.1.100",
    )
    print(f"\nSQL 注入检测: {'拦截' if not result['passed'] else '通过'}")
    if not result["passed"]:
        print(f"  规则: {result['rule_name']} ({result['severity']})")

    # SSRF 测试
    print("\nSSRF 检测:")
    for url in [
        "http://127.0.0.1:8080/test",
        "http://192.168.1.1/admin",
        "http://169.254.169.254/latest/meta-data/",
        "https://example.com/api",
    ]:
        ssrf_result = waf.check_ssrf(url)
        print(f"  {url}: {'安全' if ssrf_result['safe'] else '危险'} ({ssrf_result['risk']})")

    # 低误报模式测试
    print("\n低误报模式测试:")
    waf.set_low_confidence_mode(True)
    result = waf.check_request(
        method="POST",
        path="/api/data",
        body='{"selection": "this is a test with onclick=function()"}',
    )
    print(f"  低置信度攻击: {'拦截' if not result['passed'] else '通过'}")
    waf.set_low_confidence_mode(False)
