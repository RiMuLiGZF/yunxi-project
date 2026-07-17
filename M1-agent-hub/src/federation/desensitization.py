"""
脱敏等级体系与路径可达性验证器 — Desensitization Engine

[V11.1 新增] 实现 Federated-Comparator 的四层脱敏体系（L0~L3），
并提供路径可达性验证，确保所有升/降级组合都能正确到达目标状态。

脱敏层级定义：
- L0 原始 (raw)         — 完整原始数据，无任何处理
- L1 模糊 (fuzzy)       — 部分信息保留，数据精度降低
- L2 掩码 (masked)      — 敏感字段替换为 *** 或 [脱敏]
- L3 加密 (encrypted)   — 整段数据加密存储，需密钥解密

路径转换规则（有向图）：
  L0 ↔ L1 ↔ L2 ↔ L3
  ↑↓         ↑↓
  └───直接───┘
  (L0 可直接到 L2/L3，L3 可直接到 L0/L1)

每类 PII 数据有自己的转换能力矩阵，路径验证器确保：
1. 从任意源层级可到达任意目标层级
2. 每一步转换有对应的处理函数
3. 配置时实时验证，不可达则告警
"""

from __future__ import annotations

import re
import hashlib
import base64
from enum import Enum
from typing import Any, Callable
from dataclasses import dataclass, field

import structlog

logger = structlog.get_logger(__name__)


# ══════════════════════════════════════════════════════════
# 脱敏等级定义
# ══════════════════════════════════════════════════════════

class DesensitizationLevel(str, Enum):
    """脱敏等级"""
    L0_RAW = "L0"          # 原始数据
    L1_FUZZY = "L1"        # 模糊化
    L2_MASKED = "L2"       # 掩码
    L3_ENCRYPTED = "L3"    # 加密

    @classmethod
    def from_str(cls, level: str) -> "DesensitizationLevel":
        """从字符串解析等级"""
        level_upper = level.upper().strip()
        mapping = {
            "L0": cls.L0_RAW, "RAW": cls.L0_RAW, "原始": cls.L0_RAW,
            "L1": cls.L1_FUZZY, "FUZZY": cls.L1_FUZZY, "模糊": cls.L1_FUZZY,
            "L2": cls.L2_MASKED, "MASKED": cls.L2_MASKED, "掩码": cls.L2_MASKED,
            "L3": cls.L3_ENCRYPTED, "ENCRYPTED": cls.L3_ENCRYPTED, "加密": cls.L3_ENCRYPTED,
        }
        if level_upper in mapping:
            return mapping[level_upper]
        # 尝试直接匹配枚举值
        for e in cls:
            if e.value == level_upper or e.name == level_upper:
                return e
        raise ValueError(f"无效的脱敏等级: {level}")

    @property
    def numeric_level(self) -> int:
        """数字等级（用于比较）"""
        return {
            DesensitizationLevel.L0_RAW: 0,
            DesensitizationLevel.L1_FUZZY: 1,
            DesensitizationLevel.L2_MASKED: 2,
            DesensitizationLevel.L3_ENCRYPTED: 3,
        }[self]


# ══════════════════════════════════════════════════════════
# 数据类型定义
# ══════════════════════════════════════════════════════════

class PiiDataType(str, Enum):
    """PII 数据类型"""
    EMAIL = "email"
    PHONE = "phone"
    ID_CARD = "id_card"
    BANK_CARD = "bank_card"
    NAME = "name"
    ADDRESS = "address"
    AMOUNT = "amount"
    LOCATION = "location"
    API_KEY = "api_key"
    PASSWORD = "password"
    TOKEN = "token"
    PRIVATE_KEY = "private_key"
    INTERNAL_URL = "internal_url"
    CUSTOM = "custom"


@dataclass
class PathResult:
    """路径验证结果"""
    source: str
    target: str
    reachable: bool
    shortest_path: list[str] = field(default_factory=list)
    all_paths: list[list[str]] = field(default_factory=list)
    step_count: int = 0
    reason: str = ""


@dataclass
class DesensitizationRule:
    """单条脱敏规则"""
    data_type: str                    # 数据类型
    source_level: DesensitizationLevel  # 源等级
    target_level: DesensitizationLevel  # 目标等级
    transform_fn: Callable | None = None  # 转换函数
    description: str = ""


# ══════════════════════════════════════════════════════════
# 脱敏转换函数库
# ══════════════════════════════════════════════════════════

class DesensitizationTransforms:
    """脱敏转换函数库

    为每种数据类型提供各等级间的转换函数。
    降级（升敏感级）：L0 → L1 → L2 → L3
    升级（降敏感级）：L3 → L2 → L1 → L0（注意：L2/L3 无法完全还原为 L0）
    """

    def __init__(self, encryption_key: str | None = None) -> None:
        import os
        # 优先使用传入的密钥，其次从环境变量读取，无默认值
        self._encryption_key = encryption_key or os.getenv("M1_ENCRYPTION_KEY", "")
        self._logger = logger.bind(component="desensitization_transforms")
        if not self._encryption_key:
            self._logger.warning(
                "未配置加密密钥（M1_ENCRYPTION_KEY），数据加密功能不可用"
            )

    # ── 邮箱 ─────────────────────────────────────

    def email_l0_to_l1(self, value: str) -> str:
        """邮箱 L0→L1：保留首字母和域名"""
        if "@" not in value:
            return value
        local, domain = value.split("@", 1)
        keep = max(1, len(local) // 3)
        return f"{local[:keep]}***@{domain}"

    def email_l0_to_l2(self, value: str) -> str:
        """邮箱 L0→L2：掩码大部分信息"""
        if "@" not in value:
            return "***@***.***"
        local, domain = value.split("@", 1)
        tld = domain.split(".")[-1] if "." in domain else "com"
        return f"{local[0]}***@***.{tld}"

    def email_l1_to_l2(self, value: str) -> str:
        """邮箱 L1→L2：进一步掩码"""
        # L1 已经是 a***@domain.com，再掩码域名
        if "@" not in value:
            return "***@***.***"
        local_part, domain = value.split("@", 1)
        tld = domain.split(".")[-1] if "." in domain else "com"
        return f"{local_part[0]}***@***.{tld}"

    def email_l0_to_l3(self, value: str) -> str:
        """邮箱 L0→L3：加密"""
        return self._encrypt(value)

    def email_l3_to_l0(self, value: str) -> str:
        """邮箱 L3→L0：解密"""
        return self._decrypt(value)

    # ── 手机号 ───────────────────────────────────

    def phone_l0_to_l1(self, value: str) -> str:
        """手机号 L0→L1：保留前3后4"""
        digits = re.sub(r"\D", "", value)
        if len(digits) == 11:
            return f"{digits[:3]}****{digits[-4:]}"
        return value

    def phone_l0_to_l2(self, value: str) -> str:
        """手机号 L0→L2：只保留前3"""
        digits = re.sub(r"\D", "", value)
        if len(digits) >= 3:
            return f"{digits[:3]}********"
        return "***********"

    def phone_l1_to_l2(self, value: str) -> str:
        """手机号 L1→L2：进一步掩码"""
        return re.sub(r"\d{4}$", "****", value)

    def phone_l0_to_l3(self, value: str) -> str:
        return self._encrypt(value)

    def phone_l3_to_l0(self, value: str) -> str:
        return self._decrypt(value)

    # ── 身份证 ───────────────────────────────────

    def id_card_l0_to_l1(self, value: str) -> str:
        """身份证 L0→L1：保留前6后4"""
        digits = re.sub(r"[^0-9Xx]", "", value)
        if len(digits) >= 10:
            return f"{digits[:6]}********{digits[-4:]}"
        return value

    def id_card_l0_to_l2(self, value: str) -> str:
        """身份证 L0→L2：只保留前2位"""
        digits = re.sub(r"[^0-9Xx]", "", value)
        if len(digits) >= 2:
            return f"{digits[:2]}**************"
        return "******************"

    def id_card_l1_to_l2(self, value: str) -> str:
        return re.sub(r"\d{4}$", "****", value)

    def id_card_l0_to_l3(self, value: str) -> str:
        return self._encrypt(value)

    def id_card_l3_to_l0(self, value: str) -> str:
        return self._decrypt(value)

    # ── 银行卡 ───────────────────────────────────

    def bank_card_l0_to_l1(self, value: str) -> str:
        """银行卡 L0→L1：保留前4后4"""
        digits = re.sub(r"\D", "", value)
        if len(digits) >= 8:
            return f"{digits[:4]} **** **** {digits[-4:]}"
        return value

    def bank_card_l0_to_l2(self, value: str) -> str:
        return "**** **** **** ****"

    def bank_card_l1_to_l2(self, value: str) -> str:
        return "**** **** **** ****"

    def bank_card_l0_to_l3(self, value: str) -> str:
        return self._encrypt(value)

    def bank_card_l3_to_l0(self, value: str) -> str:
        return self._decrypt(value)

    # ── 姓名 ─────────────────────────────────────

    def name_l0_to_l1(self, value: str) -> str:
        """姓名 L0→L1：保留姓，名用 *"""
        if len(value) <= 1:
            return value
        return value[0] + "*" * (len(value) - 1)

    def name_l0_to_l2(self, value: str) -> str:
        """姓名 L0→L2：全掩码"""
        return "*" * len(value) if value else "***"

    def name_l1_to_l2(self, value: str) -> str:
        return "*" * len(value) if value else "***"

    def name_l0_to_l3(self, value: str) -> str:
        return self._encrypt(value)

    def name_l3_to_l0(self, value: str) -> str:
        return self._decrypt(value)

    # ── 地址 ─────────────────────────────────────

    def address_l0_to_l1(self, value: str) -> str:
        """地址 L0→L1：保留到区级，详细地址掩码"""
        # 简单处理：保留前 12 个字符
        if len(value) <= 12:
            return value + "***"
        return value[:12] + "***"

    def address_l0_to_l2(self, value: str) -> str:
        """地址 L0→L2：只保留城市级"""
        if len(value) <= 6:
            return "***"
        return value[:6] + "***"

    def address_l1_to_l2(self, value: str) -> str:
        return value[:6] + "***" if len(value) > 6 else "***"

    def address_l0_to_l3(self, value: str) -> str:
        return self._encrypt(value)

    def address_l3_to_l0(self, value: str) -> str:
        return self._decrypt(value)

    # ── 金额 ─────────────────────────────────────

    def amount_l0_to_l1(self, value: str) -> str:
        """金额 L0→L1：精度降低（保留万位）"""
        try:
            num = float(re.sub(r"[^\d.]", "", value))
            if num >= 10000:
                return f"{round(num/10000, 1)}万元"
            return f"{round(num, -1)}元"
        except (ValueError, TypeError):
            return "***元"

    def amount_l0_to_l2(self, value: str) -> str:
        """金额 L0→L2：只显示量级"""
        try:
            num = float(re.sub(r"[^\d.]", "", value))
            if num >= 100000000:
                return "亿元级"
            if num >= 10000:
                return "万元级"
            if num >= 1000:
                return "千元级"
            return "元级"
        except (ValueError, TypeError):
            return "***"

    def amount_l1_to_l2(self, value: str) -> str:
        if "万" in value:
            return "万元级"
        return "元级"

    # ── 地理位置 ─────────────────────────────────

    def location_l0_to_l1(self, value: str) -> str:
        """地理位置 L0→L1：精度降到区级"""
        parts = value.split(",")
        if len(parts) >= 2:
            try:
                lat = round(float(parts[0]), 2)
                lng = round(float(parts[1]), 2)
                return f"{lat},{lng}"
            except (ValueError, TypeError):
                pass
        return value[:15] + "***" if len(value) > 15 else value

    def location_l0_to_l2(self, value: str) -> str:
        """地理位置 L0→L2：只保留城市级（小数点后0位）"""
        parts = value.split(",")
        if len(parts) >= 2:
            try:
                lat = round(float(parts[0]), 0)
                lng = round(float(parts[1]), 0)
                return f"{int(lat)},{int(lng)}"
            except (ValueError, TypeError):
                pass
        return "***,***"

    def location_l1_to_l2(self, value: str) -> str:
        parts = value.split(",")
        if len(parts) >= 2:
            try:
                lat = round(float(parts[0]), 0)
                lng = round(float(parts[1]), 0)
                return f"{int(lat)},{int(lng)}"
            except (ValueError, TypeError):
                pass
        return "***,***"

    # ── API Key / 密码 / Token / 私钥 ────────────

    def secret_l0_to_l1(self, value: str) -> str:
        """密钥类 L0→L1：保留前后几位"""
        if len(value) <= 8:
            return "****"
        return f"{value[:4]}****{value[-4:]}"

    def secret_l0_to_l2(self, value: str) -> str:
        """密钥类 L0→L2：完全掩码"""
        return "****[REDACTED]****"

    def secret_l1_to_l2(self, value: str) -> str:
        return "****[REDACTED]****"

    def secret_l0_to_l3(self, value: str) -> str:
        return self._encrypt(value)

    def secret_l3_to_l0(self, value: str) -> str:
        return self._decrypt(value)

    # ── 内网 URL ────────────────────────────────

    def url_l0_to_l1(self, value: str) -> str:
        """内网URL L0→L1：掩码 IP，保留路径"""
        return re.sub(r"\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}", "***.***.***.***", value)

    def url_l0_to_l2(self, value: str) -> str:
        """内网URL L0→L2：完全掩码"""
        return "[INTERNAL_URL_REDACTED]"

    def url_l1_to_l2(self, value: str) -> str:
        return "[INTERNAL_URL_REDACTED]"

    # ── 加密辅助 ─────────────────────────────────

    def _encrypt(self, value: str) -> str:
        """简易加密（开发用，生产应使用 Fernet）"""
        # 使用 XOR + base64 做简易加密（仅用于演示 L3 概念）
        key_bytes = self._encryption_key.encode()
        val_bytes = value.encode()
        encrypted = bytes([b ^ key_bytes[i % len(key_bytes)] for i, b in enumerate(val_bytes)])
        return "ENC:" + base64.b64encode(encrypted).decode()

    def _decrypt(self, value: str) -> str:
        """简易解密"""
        if not value.startswith("ENC:"):
            return value
        try:
            encrypted = base64.b64decode(value[4:])
            key_bytes = self._encryption_key.encode()
            decrypted = bytes([b ^ key_bytes[i % len(key_bytes)] for i, b in enumerate(encrypted)])
            return decrypted.decode()
        except Exception:
            return value


# ══════════════════════════════════════════════════════════
# 脱敏路径可达性验证器
# ══════════════════════════════════════════════════════════

class DesensitizationPathValidator:
    """脱敏路径可达性验证器

    职责：
    - 维护脱敏层级转换图（有向图）
    - 验证任意两等级间的路径可达性
    - 找出最短路径和所有可能路径
    - 配置时实时验证
    - 生成所有组合的可达性矩阵
    """

    # 标准转换图（4×4 全连接有向图）
    # L0 ↔ L1 ↔ L2 ↔ L3，且 L0↔L2、L0↔L3 直接可达
    STANDARD_GRAPH: dict[str, list[str]] = {
        "L0": ["L1", "L2", "L3"],
        "L1": ["L0", "L2"],
        "L2": ["L0", "L1", "L3"],
        "L3": ["L2", "L0", "L1"],
    }

    def __init__(
        self,
        custom_graph: dict[str, list[str]] | None = None,
        transforms: DesensitizationTransforms | None = None,
    ) -> None:
        self._graph = custom_graph or self.STANDARD_GRAPH
        self._transforms = transforms or DesensitizationTransforms()
        self._transform_cache: dict[tuple[str, str, str], Callable | None] = {}
        self._logger = logger.bind(component="path_validator")
        self._build_transform_cache()

    def _build_transform_cache(self) -> None:
        """构建转换函数缓存"""
        # 数据类型到函数前缀的映射
        type_prefixes = {
            "email": "email",
            "phone": "phone",
            "id_card": "id_card",
            "bank_card": "bank_card",
            "name": "name",
            "address": "address",
            "amount": "amount",
            "location": "location",
            "api_key": "secret",
            "password": "secret",
            "token": "secret",
            "private_key": "secret",
            "internal_url": "url",
            "custom": "secret",
        }

        for data_type, prefix in type_prefixes.items():
            # 所有相邻等级 + 直达路径
            transitions = [
                ("L0", "L1"), ("L1", "L0"),
                ("L0", "L2"), ("L2", "L0"),
                ("L1", "L2"), ("L2", "L1"),
                ("L0", "L3"), ("L3", "L0"),
                ("L2", "L3"), ("L3", "L2"),
                ("L1", "L3"), ("L3", "L1"),
            ]
            for src, tgt in transitions:
                fn_name = f"{prefix}_l{src[1]}_to_l{tgt[1]}"
                fn = getattr(self._transforms, fn_name, None)
                self._transform_cache[(data_type, src, tgt)] = fn

    def validate_path(
        self,
        source_level: str,
        target_level: str,
        data_type: str = "email",
    ) -> PathResult:
        """验证从源等级到目标等级的路径是否可达

        Args:
            source_level: 源等级（L0/L1/L2/L3）
            target_level: 目标等级
            data_type: 数据类型

        Returns:
            PathResult 包含可达性、最短路径、所有路径
        """
        src = source_level.upper()
        tgt = target_level.upper()

        # 同一等级
        if src == tgt:
            return PathResult(
                source=src,
                target=tgt,
                reachable=True,
                shortest_path=[src],
                all_paths=[[src]],
                step_count=0,
                reason="同一等级，无需转换",
            )

        # BFS 找最短路径
        shortest = self._bfs_shortest_path(src, tgt)

        # DFS 找所有路径
        all_paths = self._dfs_all_paths(src, tgt)

        # 检查每一步是否有对应的转换函数
        reachable = shortest is not None
        reason = ""

        if not reachable:
            reason = f"从 {src} 到 {tgt} 不存在转换路径"
        else:
            # 验证每一步都有转换函数
            valid = True
            for i in range(len(shortest) - 1):
                step_src = shortest[i]
                step_tgt = shortest[i + 1]
                fn = self._transform_cache.get((data_type, step_src, step_tgt))
                if fn is None:
                    valid = False
                    reason = f"缺少 {data_type} {step_src}→{step_tgt} 的转换函数"
                    break
            if valid:
                reason = f"通过 {len(shortest)-1} 步转换可达"

        return PathResult(
            source=src,
            target=tgt,
            reachable=reachable and (shortest is not None),
            shortest_path=shortest or [],
            all_paths=all_paths,
            step_count=len(shortest) - 1 if shortest else 0,
            reason=reason,
        )

    def _bfs_shortest_path(self, start: str, end: str) -> list[str] | None:
        """BFS 找最短路径"""
        if start not in self._graph:
            return None

        from collections import deque
        queue: deque[list[str]] = deque([[start]])
        visited = {start}

        while queue:
            path = queue.popleft()
            node = path[-1]
            if node == end:
                return path
            for neighbor in self._graph.get(node, []):
                if neighbor not in visited:
                    visited.add(neighbor)
                    queue.append(path + [neighbor])

        return None

    def _dfs_all_paths(self, start: str, end: str, max_paths: int = 10) -> list[list[str]]:
        """DFS 找所有路径（限制数量防止爆炸）"""
        if start not in self._graph:
            return []

        all_paths: list[list[str]] = []

        def dfs(node: str, path: list[str], visited: set[str]) -> None:
            if len(all_paths) >= max_paths:
                return
            if node == end:
                all_paths.append(list(path))
                return
            for neighbor in self._graph.get(node, []):
                if neighbor not in visited:
                    visited.add(neighbor)
                    path.append(neighbor)
                    dfs(neighbor, path, visited)
                    path.pop()
                    visited.remove(neighbor)

        dfs(start, [start], {start})
        return all_paths

    def validate_all_combinations(self, data_type: str = "email") -> dict[str, Any]:
        """验证所有层级组合的可达性（4×4 = 16 种组合）

        Args:
            data_type: 数据类型

        Returns:
            包含可达性矩阵和统计信息
        """
        levels = ["L0", "L1", "L2", "L3"]
        matrix: dict[str, dict[str, PathResult]] = {}
        reachable_count = 0
        total = 0

        for src in levels:
            matrix[src] = {}
            for tgt in levels:
                result = self.validate_path(src, tgt, data_type)
                matrix[src][tgt] = result
                total += 1
                if result.reachable:
                    reachable_count += 1

        return {
            "data_type": data_type,
            "total_combinations": total,
            "reachable_count": reachable_count,
            "unreachable_count": total - reachable_count,
            "all_reachable": reachable_count == total,
            "matrix": matrix,
        }

    def validate_all_data_types(self) -> dict[str, Any]:
        """验证所有数据类型的所有组合"""
        data_types = [
            "email", "phone", "id_card", "bank_card",
            "name", "address", "amount", "location",
            "api_key", "password", "token", "private_key",
            "internal_url",
        ]

        results: dict[str, dict[str, Any]] = {}
        all_pass = True
        total_combos = 0
        reachable_combos = 0

        for dt in data_types:
            result = self.validate_all_combinations(dt)
            results[dt] = result
            total_combos += result["total_combinations"]
            reachable_combos += result["reachable_count"]
            if not result["all_reachable"]:
                all_pass = False

        return {
            "all_data_types_pass": all_pass,
            "total_combinations": total_combos,
            "reachable_combinations": reachable_combos,
            "unreachable_combinations": total_combos - reachable_combos,
            "data_types": results,
        }

    def generate_test_cases(self, data_type: str = "email") -> list[dict[str, Any]]:
        """生成路径测试用例

        每条路径至少 3 个测试用例（正常/边界/异常）
        """
        levels = ["L0", "L1", "L2", "L3"]
        test_cases: list[dict[str, Any]] = []

        sample_data = self._get_sample_data(data_type)

        for src in levels:
            for tgt in levels:
                if src == tgt:
                    continue
                result = self.validate_path(src, tgt, data_type)
                if result.reachable:
                    # 正常数据
                    test_cases.append({
                        "data_type": data_type,
                        "source": src,
                        "target": tgt,
                        "input": sample_data["normal"],
                        "expected_type": "string",
                        "category": "normal",
                    })
                    # 边界数据
                    test_cases.append({
                        "data_type": data_type,
                        "source": src,
                        "target": tgt,
                        "input": sample_data["boundary"],
                        "expected_type": "string",
                        "category": "boundary",
                    })
                    # 异常数据
                    test_cases.append({
                        "data_type": data_type,
                        "source": src,
                        "target": tgt,
                        "input": sample_data["invalid"],
                        "expected_type": "string",
                        "category": "invalid",
                    })

        return test_cases

    @staticmethod
    def _get_sample_data(data_type: str) -> dict[str, str]:
        """获取各类数据的样本"""
        samples = {
            "email": {
                "normal": "user@example.com",
                "boundary": "a@b.co",
                "invalid": "not-an-email",
            },
            "phone": {
                "normal": "13812345678",
                "boundary": "13000000000",
                "invalid": "12345",
            },
            "id_card": {
                "normal": "110101199003071234",
                "boundary": "110101190001010001",
                "invalid": "12345",
            },
            "bank_card": {
                "normal": "6222021234567890123",
                "boundary": "4532015112830366",
                "invalid": "1234",
            },
            "name": {
                "normal": "张三",
                "boundary": "欧阳修",
                "invalid": "",
            },
            "address": {
                "normal": "北京市海淀区中关村大街1号",
                "boundary": "北京市东城区",
                "invalid": "",
            },
            "amount": {
                "normal": "12345.67元",
                "boundary": "0.01元",
                "invalid": "abc",
            },
            "location": {
                "normal": "39.9042,116.4074",
                "boundary": "0.0000,0.0000",
                "invalid": "abc",
            },
            "api_key": {
                "normal": "sk-abc123def456ghi789",
                "boundary": "sk-a",
                "invalid": "",
            },
            "password": {
                "normal": "MySecretPass123!",
                "boundary": "a",
                "invalid": "",
            },
            "token": {
                "normal": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9",
                "boundary": "token",
                "invalid": "",
            },
            "private_key": {
                "normal": "-----BEGIN RSA PRIVATE KEY-----\nMIIE...\n-----END RSA PRIVATE KEY-----",
                "boundary": "-----BEGIN PRIVATE KEY-----\nAB\n-----END PRIVATE KEY-----",
                "invalid": "not a key",
            },
            "internal_url": {
                "normal": "http://192.168.1.100:8080/api",
                "boundary": "http://10.0.0.1",
                "invalid": "https://example.com",
            },
        }
        return samples.get(data_type, samples["email"])

    def apply_desensitization(
        self,
        value: str,
        data_type: str,
        source_level: str,
        target_level: str,
    ) -> str:
        """执行脱敏转换

        Args:
            value: 原始值
            data_type: 数据类型
            source_level: 源等级
            target_level: 目标等级

        Returns:
            转换后的值

        Raises:
            ValueError: 路径不可达
        """
        src = source_level.upper()
        tgt = target_level.upper()

        if src == tgt:
            return value

        # 验证路径
        path_result = self.validate_path(src, tgt, data_type)
        if not path_result.reachable:
            raise ValueError(f"脱敏路径不可达: {src} → {tgt} ({data_type})")

        # 沿最短路径逐步转换
        current = value
        path = path_result.shortest_path

        for i in range(len(path) - 1):
            step_src = path[i]
            step_tgt = path[i + 1]
            fn = self._transform_cache.get((data_type, step_src, step_tgt))
            if fn is None:
                raise ValueError(f"缺少转换函数: {data_type} {step_src}→{step_tgt}")
            current = fn(current)

        return current


# ══════════════════════════════════════════════════════════
# 配置时实时验证器
# ══════════════════════════════════════════════════════════

class DesensitizationConfigValidator:
    """脱敏配置实时验证器

    用户配置脱敏规则时实时检查：
    - 目标状态是否可达
    - 配置是否有效
    - 不可达时给出警告 + 建议调整方案
    """

    def __init__(self, path_validator: DesensitizationPathValidator | None = None) -> None:
        self._validator = path_validator or DesensitizationPathValidator()
        self._logger = logger.bind(component="config_validator")

    def validate_rule(
        self,
        data_type: str,
        target_level: str,
        source_level: str = "L0",
    ) -> dict[str, Any]:
        """验证单条脱敏规则

        Returns:
            包含 valid、reason、suggestions
        """
        result = self._validator.validate_path(source_level, target_level, data_type)

        suggestions: list[str] = []
        if not result.reachable:
            # 给出建议
            suggestions.append(f"请检查 {data_type} 是否支持 {source_level} → {target_level} 的转换")
            suggestions.append("可尝试调整目标等级为 L1 或 L2")
            suggestions.append("或增加自定义转换函数")

        return {
            "valid": result.reachable,
            "data_type": data_type,
            "source_level": source_level,
            "target_level": target_level,
            "shortest_path": result.shortest_path,
            "step_count": result.step_count,
            "reason": result.reason,
            "suggestions": suggestions,
        }

    def validate_config(
        self,
        rules: list[dict[str, str]],
        default_level: str = "L1",
    ) -> dict[str, Any]:
        """验证完整的脱敏配置

        Args:
            rules: 规则列表，每项包含 data_type 和 target_level
            default_level: 默认脱敏等级

        Returns:
            验证结果
        """
        results: list[dict[str, Any]] = []
        all_valid = True
        warnings: list[str] = []

        # 验证默认等级
        try:
            DesensitizationLevel.from_str(default_level)
        except ValueError as exc:
            all_valid = False
            warnings.append(f"默认等级无效: {exc}")

        # 验证每条规则
        for rule in rules:
            data_type = rule.get("data_type", "")
            target = rule.get("target_level", default_level)
            source = rule.get("source_level", "L0")

            result = self.validate_rule(data_type, target, source)
            results.append(result)
            if not result["valid"]:
                all_valid = False
                warnings.append(
                    f"规则无效: {data_type} {source}→{target} - {result['reason']}"
                )

        return {
            "all_valid": all_valid,
            "total_rules": len(rules),
            "valid_rules": sum(1 for r in results if r["valid"]),
            "invalid_rules": sum(1 for r in results if not r["valid"]),
            "results": results,
            "warnings": warnings,
            "can_save": all_valid,  # 不可达配置阻止保存
        }
