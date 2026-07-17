"""
云汐 API 网关 - 路径重写模块

功能：
1. 正则表达式路径重写
2. 前缀剥离（strip_prefix）
3. 路径添加前缀
"""
import re
import threading
from typing import List, Optional, Dict, Any
from dataclasses import dataclass, field


@dataclass
class RewriteRule:
    """路径重写规则

    Attributes:
        pattern: 匹配模式（正则表达式或路径前缀）
        replacement: 替换后的路径（正则替换时可使用分组引用 \\1, \\2 等）
        type: 重写类型：regex（正则）、strip_prefix（剥离前缀）、add_prefix（添加前缀）
        order: 执行顺序（越小越先执行）
        enabled: 是否启用
    """
    pattern: str
    replacement: str = ""
    type: str = "regex"  # regex, strip_prefix, add_prefix
    order: int = 100
    enabled: bool = True

    def __post_init__(self):
        # 预编译正则表达式
        if self.type == "regex":
            try:
                self._compiled = re.compile(self.pattern)
            except re.error:
                self._compiled = None
        else:
            self._compiled = None


class PathRewriter:
    """路径重写器

    支持多种路径重写方式，按顺序执行。
    """

    def __init__(self, rules: Optional[List[RewriteRule]] = None):
        """
        Args:
            rules: 重写规则列表
        """
        self._rules: List[RewriteRule] = []
        self._lock = threading.Lock()
        self._stats = {
            "total_rewrites": 0,
            "regex_rewrites": 0,
            "strip_prefix_rewrites": 0,
            "add_prefix_rewrites": 0,
            "no_match": 0,
        }
        if rules:
            self.set_rules(rules)

    def set_rules(self, rules: List[RewriteRule]):
        """设置重写规则列表（按 order 排序）"""
        with self._lock:
            self._rules = sorted(
                [r for r in rules if r.enabled],
                key=lambda r: r.order
            )

    def add_rule(self, rule: RewriteRule):
        """添加重写规则"""
        with self._lock:
            self._rules = [r for r in self._rules if r.pattern != rule.pattern or r.type != rule.type]
            self._rules.append(rule)
            self._rules = sorted(
                [r for r in self._rules if r.enabled],
                key=lambda r: r.order
            )

    def remove_rule(self, pattern: str, rule_type: str = "regex") -> bool:
        """移除重写规则"""
        with self._lock:
            original_len = len(self._rules)
            self._rules = [
                r for r in self._rules
                if not (r.pattern == pattern and r.type == rule_type)
            ]
            return len(self._rules) != original_len

    def rewrite(self, path: str) -> str:
        """对路径执行所有重写规则

        Args:
            path: 原始路径

        Returns:
            重写后的路径
        """
        with self._lock:
            self._stats["total_rewrites"] += 1
            current_path = path
            matched = False

            for rule in self._rules:
                if not rule.enabled:
                    continue

                if rule.type == "regex":
                    result = self._apply_regex_rewrite(current_path, rule)
                    if result != current_path:
                        self._stats["regex_rewrites"] += 1
                        matched = True
                        current_path = result

                elif rule.type == "strip_prefix":
                    result = self._apply_strip_prefix(current_path, rule)
                    if result != current_path:
                        self._stats["strip_prefix_rewrites"] += 1
                        matched = True
                        current_path = result

                elif rule.type == "add_prefix":
                    result = self._apply_add_prefix(current_path, rule)
                    if result != current_path:
                        self._stats["add_prefix_rewrites"] += 1
                        matched = True
                        current_path = result

            if not matched:
                self._stats["no_match"] += 1

            return current_path

    def _apply_regex_rewrite(self, path: str, rule: RewriteRule) -> str:
        """应用正则表达式重写"""
        if rule._compiled is None:
            try:
                rule._compiled = re.compile(rule.pattern)
            except re.error:
                return path

        match = rule._compiled.search(path)
        if match:
            return rule._compiled.sub(rule.replacement, path)
        return path

    def _apply_strip_prefix(self, path: str, rule: RewriteRule) -> str:
        """应用前缀剥离"""
        prefix = rule.pattern
        if path.startswith(prefix):
            remaining = path[len(prefix):]
            if not remaining.startswith("/"):
                remaining = "/" + remaining
            return remaining
        return path

    def _apply_add_prefix(self, path: str, rule: RewriteRule) -> str:
        """应用添加前缀"""
        prefix = rule.replacement
        if not path.startswith(prefix):
            if prefix.endswith("/") and path.startswith("/"):
                return prefix + path[1:]
            elif not prefix.endswith("/") and not path.startswith("/"):
                return prefix + "/" + path
            else:
                return prefix + path
        return path

    def get_rules(self) -> List[Dict[str, Any]]:
        """获取所有规则"""
        with self._lock:
            return [
                {
                    "pattern": r.pattern,
                    "replacement": r.replacement,
                    "type": r.type,
                    "order": r.order,
                    "enabled": r.enabled,
                }
                for r in self._rules
            ]

    def get_stats(self) -> Dict[str, Any]:
        """获取统计信息"""
        with self._lock:
            return dict(self._stats)

    def reset_stats(self):
        """重置统计"""
        with self._lock:
            for key in self._stats:
                self._stats[key] = 0
