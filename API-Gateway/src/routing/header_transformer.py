"""
云汐 API 网关 - 请求/响应头转换器

功能：
1. 请求头添加/删除/修改
2. 响应头添加/删除/修改
3. 支持基于条件的头操作
"""
import re
import threading
from typing import List, Optional, Dict, Any
from dataclasses import dataclass, field


@dataclass
class HeaderCondition:
    """头操作条件

    Attributes:
        header: 要检查的头名称
        operator: 操作符：equals、contains、exists、not_exists、regex
        value: 比较值
    """
    header: str
    operator: str = "exists"  # equals, contains, exists, not_exists, regex
    value: str = ""


@dataclass
class HeaderRule:
    """头操作规则

    Attributes:
        action: 操作类型：add、remove、set、append
        header: 头名称
        value: 头值（add/set/append 时使用）
        direction: 方向：request、response、both
        conditions: 条件列表（所有条件满足才执行）
        order: 执行顺序
        enabled: 是否启用
    """
    action: str  # add, remove, set, append
    header: str
    value: str = ""
    direction: str = "both"  # request, response, both
    conditions: List[HeaderCondition] = field(default_factory=list)
    order: int = 100
    enabled: bool = True


class HeaderTransformer:
    """头转换器

    对请求头和响应头进行添加、删除、修改、追加等操作，
    支持条件判断。
    """

    def __init__(self, rules: Optional[List[HeaderRule]] = None):
        self._request_rules: List[HeaderRule] = []
        self._response_rules: List[HeaderRule] = []
        self._lock = threading.Lock()
        self._stats = {
            "request_transforms": 0,
            "response_transforms": 0,
            "add_ops": 0,
            "remove_ops": 0,
            "set_ops": 0,
            "append_ops": 0,
            "conditions_skipped": 0,
        }
        if rules:
            self.set_rules(rules)

    def set_rules(self, rules: List[HeaderRule]):
        """设置规则列表"""
        with self._lock:
            enabled_rules = [r for r in rules if r.enabled]
            self._request_rules = sorted(
                [r for r in enabled_rules if r.direction in ("request", "both")],
                key=lambda r: r.order
            )
            self._response_rules = sorted(
                [r for r in enabled_rules if r.direction in ("response", "both")],
                key=lambda r: r.order
            )

    def add_rule(self, rule: HeaderRule):
        """添加规则"""
        with self._lock:
            # 移除同类型同方向同头名的旧规则
            def _match(r: HeaderRule) -> bool:
                return (r.action == rule.action
                        and r.header.lower() == rule.header.lower()
                        and r.direction == rule.direction)

            self._request_rules = [r for r in self._request_rules if not _match(r)]
            self._response_rules = [r for r in self._response_rules if not _match(r)]

            if rule.direction in ("request", "both"):
                self._request_rules.append(rule)
                self._request_rules.sort(key=lambda r: r.order)
            if rule.direction in ("response", "both"):
                self._response_rules.append(rule)
                self._response_rules.sort(key=lambda r: r.order)

    def remove_rule(self, header: str, action: str, direction: str = "both") -> bool:
        """移除规则"""
        with self._lock:
            removed = False
            header_lower = header.lower()

            def _match(r: HeaderRule) -> bool:
                return r.action == action and r.header.lower() == header_lower

            if direction in ("request", "both"):
                orig = len(self._request_rules)
                self._request_rules = [r for r in self._request_rules if not _match(r)]
                removed = removed or len(self._request_rules) != orig

            if direction in ("response", "both"):
                orig = len(self._response_rules)
                self._response_rules = [r for r in self._response_rules if not _match(r)]
                removed = removed or len(self._response_rules) != orig

            return removed

    def transform_request(self, headers: Dict[str, str]) -> Dict[str, str]:
        """转换请求头

        Args:
            headers: 原始请求头字典

        Returns:
            转换后的请求头字典（新字典，不修改原字典）
        """
        with self._lock:
            result = dict(headers)
            self._stats["request_transforms"] += 1

            for rule in self._request_rules:
                if not rule.enabled:
                    continue
                if not self._check_conditions(rule.conditions, result):
                    self._stats["conditions_skipped"] += 1
                    continue
                self._apply_rule(rule, result)

            return result

    def transform_response(self, headers: Dict[str, str]) -> Dict[str, str]:
        """转换响应头

        Args:
            headers: 原始响应头字典

        Returns:
            转换后的响应头字典（新字典，不修改原字典）
        """
        with self._lock:
            result = dict(headers)
            self._stats["response_transforms"] += 1

            for rule in self._response_rules:
                if not rule.enabled:
                    continue
                if not self._check_conditions(rule.conditions, result):
                    self._stats["conditions_skipped"] += 1
                    continue
                self._apply_rule(rule, result)

            return result

    def _apply_rule(self, rule: HeaderRule, headers: Dict[str, str]):
        """应用单条规则"""
        header_lower = rule.header.lower()

        if rule.action == "add":
            # add: 只有不存在时才添加
            if not any(k.lower() == header_lower for k in headers):
                headers[rule.header] = rule.value
                self._stats["add_ops"] += 1

        elif rule.action == "set":
            # set: 存在则覆盖，不存在则添加
            # 移除所有大小写变体
            keys_to_remove = [k for k in headers if k.lower() == header_lower]
            for k in keys_to_remove:
                del headers[k]
            headers[rule.header] = rule.value
            self._stats["set_ops"] += 1

        elif rule.action == "remove":
            # remove: 删除头
            keys_to_remove = [k for k in headers if k.lower() == header_lower]
            for k in keys_to_remove:
                del headers[k]
                self._stats["remove_ops"] += 1

        elif rule.action == "append":
            # append: 追加到现有值（逗号分隔）
            existing_key = None
            for k in headers:
                if k.lower() == header_lower:
                    existing_key = k
                    break
            if existing_key:
                headers[existing_key] = headers[existing_key] + ", " + rule.value
            else:
                headers[rule.header] = rule.value
            self._stats["append_ops"] += 1

    def _check_conditions(self, conditions: List[HeaderCondition],
                          headers: Dict[str, str]) -> bool:
        """检查条件是否全部满足"""
        if not conditions:
            return True

        for cond in conditions:
            cond_header_lower = cond.header.lower()
            header_value = None
            for k, v in headers.items():
                if k.lower() == cond_header_lower:
                    header_value = v
                    break

            if cond.operator == "exists":
                if header_value is None:
                    return False
            elif cond.operator == "not_exists":
                if header_value is not None:
                    return False
            elif cond.operator == "equals":
                if header_value is None or header_value != cond.value:
                    return False
            elif cond.operator == "contains":
                if header_value is None or cond.value not in header_value:
                    return False
            elif cond.operator == "regex":
                if header_value is None:
                    return False
                try:
                    if not re.search(cond.value, header_value):
                        return False
                except re.error:
                    return False

        return True

    def get_rules(self) -> Dict[str, List[Dict[str, Any]]]:
        """获取所有规则"""
        with self._lock:
            return {
                "request": [
                    {
                        "action": r.action,
                        "header": r.header,
                        "value": r.value,
                        "order": r.order,
                        "conditions": [
                            {"header": c.header, "operator": c.operator, "value": c.value}
                            for c in r.conditions
                        ],
                    }
                    for r in self._request_rules
                ],
                "response": [
                    {
                        "action": r.action,
                        "header": r.header,
                        "value": r.value,
                        "order": r.order,
                        "conditions": [
                            {"header": c.header, "operator": c.operator, "value": c.value}
                            for c in r.conditions
                        ],
                    }
                    for r in self._response_rules
                ],
            }

    def get_stats(self) -> Dict[str, Any]:
        """获取统计信息"""
        with self._lock:
            return dict(self._stats)

    def reset_stats(self):
        """重置统计"""
        with self._lock:
            for key in self._stats:
                self._stats[key] = 0
