#!/usr/bin/env python3
"""
硬编码密钥扫描工具（SEC-001 安全加固配套工具）

扫描代码库中可能存在的硬编码密钥/密码/Token，帮助开发者在提交代码前
发现并修复敏感信息泄露问题。

支持的检测模式：
- password = "xxx" / PASSWORD=xxx
- secret = "xxx" / SECRET_KEY=xxx
- api_key = "xxx" / API_KEY=xxx
- token = "xxx" / TOKEN=xxx
- jwt_secret / encryption_key / db_password / admin_token 等
- 常见的云服务密钥格式（AWS、GCP、Azure 等）

风险分级：
- HIGH（高危）: 疑似真实密钥，长度足够且符合密钥格式
- MEDIUM（中危）: 可能是默认值/测试值，建议改为环境变量
- LOW（低危）: 示例值/占位符，文档中的示例
- INFO（信息）: 变量名匹配但值为空或明显是变量引用

使用方法：
    python scripts/secret_scan.py                    # 扫描整个项目
    python scripts/secret_scan.py --path src/        # 扫描指定目录
    python scripts/secret_scan.py --high-only        # 只显示高危结果
    python scripts/secret_scan.py --exclude tests/   # 排除指定目录
    python scripts/secret_scan.py --json report.json # 输出 JSON 报告

退出码：
    0 - 未发现高危/中危问题
    1 - 发现高危或中危问题（用于 CI/CD 拦截）
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple


# ============================================================
# 扫描规则配置
# ============================================================

# 敏感字段名模式（不区分大小写）
SENSITIVE_FIELD_PATTERNS = [
    # 密码类
    (r'(password|passwd|pwd)\s*[=:]\s*["\']([^"\']{4,})["\']', "password"),
    # 密钥类
    (r'(secret|secret_key|jwt_secret|encryption_key)\s*[=:]\s*["\']([^"\']{4,})["\']', "secret"),
    # API Key 类
    (r'(api_key|apikey|api_secret)\s*[=:]\s*["\']([^"\']{4,})["\']', "api_key"),
    # Token 类
    (r'(token|auth_token|access_token|refresh_token|admin_token|bearer_token)\s*[=:]\s*["\']([^"\']{4,})["\']', "token"),
    # 数据库密码
    (r'(db_password|database_password|mysql_password|postgres_password)\s*[=:]\s*["\']([^"\']{4,})["\']', "db_password"),
    # 私钥
    (r'(private_key|rsa_key)\s*[=:]\s*["\']([^"\']{4,})["\']', "private_key"),
]

# 已知的高风险密钥前缀（强特征）
HIGH_RISK_PREFIXES = [
    # 云服务
    "AKIA",       # AWS Access Key ID
    "ASIA",       # AWS Temporary Access Key
    "AIza",       # Google API Key
    "sk-",        # OpenAI API Key
    "ghp_",       # GitHub Personal Access Token
    "gho_",       # GitHub OAuth Token
    "ghu_",       # GitHub User-to-Server Token
    "ghs_",       # GitHub Server-to-Server Token
    "ghr_",       # GitHub Refresh Token
    "xoxb-",      # Slack Bot Token
    "xoxp-",      # Slack User Token
    "xoxa-",      # Slack Workspace Token
    "eac_",       # Stripe API Key
    "rk_live_",   # Stripe Restricted Key
    "sk_live_",   # Stripe Secret Key (live)
    "pk_live_",   # Stripe Publishable Key (live)
    "sq0atp-",    # Square Access Token
    "sq0csp-",    # Square OAuth Secret
    # 通用强特征
    "-----BEGIN RSA PRIVATE KEY-----",
    "-----BEGIN PRIVATE KEY-----",
    "-----BEGIN EC PRIVATE KEY-----",
]

# 低风险/误报模式（值的内容匹配则降级）
LOW_RISK_VALUE_PATTERNS = [
    r'^\$\{.*\}$',           # 环境变量引用 ${VAR_NAME}
    r'^os\.environ',          # os.environ 调用
    r'^getenv\s*\(',          # getenv() 调用
    r'^your-',               # 示例占位符
    r'^example',             # 示例值
    r'^test-',               # 测试值（开头）
    r'^changeme',            # 占位符
    r'^change_me',           # 占位符
    r'^CHANGEME',            # 占位符
    r'^CHANGE_ME',           # 占位符
    r'^replace',             # 替换提示
    r'^xxx+$',               # xxx 占位符
    r'^\.\.\.$',             # ... 占位符
    r'^<.*>$',               # <placeholder> 格式
    r'^my-',                 # 示例值（my-secret 等）
    r'^dev-',                # 开发环境前缀
    r'^default',             # 默认值
    r'^sample',              # 示例值
    r'^demo',                # 演示值
    r'^fake',                # 假值
    r'^invalid',             # 无效值
    r'^wrong',               # 错误值
    r'^test\d*$',            # test / test123
    r'^password\d*$',        # password / password123（仅当字段就是 password 时）
    r'^admin\d*$',           # admin / admin123
    r'^123456',              # 弱密码
    r'^qwerty',              # 弱密码
]

# 误报的字段名上下文（变量定义但值是变量名/类型名）
FALSE_POSITIVE_FIELD_VALUES = {
    "password": {"password", "PASSWORD", "passwd"},
    "secret": {"secret", "SECRET", "top_secret"},
    "api_key": {"api_key", "API_KEY", "apikey"},
    "token": {"token", "TOKEN", "auth_token"},
}

# 要排除的文件类型
EXCLUDED_EXTENSIONS = {
    '.pyc', '.pyo', '.pyd',  # Python 编译文件
    '.so', '.dll', '.dylib',  # 动态库
    '.exe', '.bin',           # 二进制
    '.zip', '.tar', '.gz', '.tgz', '.rar', '.7z',  # 压缩包
    '.png', '.jpg', '.jpeg', '.gif', '.bmp', '.ico', '.webp',  # 图片
    '.mp3', '.mp4', '.avi', '.mov', '.wav',  # 音视频
    '.pdf', '.doc', '.docx', '.xls', '.xlsx', '.ppt', '.pptx',  # 文档
    '.woff', '.woff2', '.ttf', '.eot',  # 字体
}

# 要排除的目录
EXCLUDED_DIRS = {
    '__pycache__',
    '.git',
    '.svn',
    '.hg',
    'node_modules',
    '.venv',
    'venv',
    'env',
    '.env',
    'dist',
    'build',
    '.egg-info',
    '*.egg-info',
    '.pytest_cache',
    '.mypy_cache',
    '.ruff_cache',
    '.coverage',
    'htmlcov',
    '.tox',
}

# 测试文件目录模式（风险自动降级）
TEST_DIR_PATTERNS = [
    '/tests/',
    '/test/',
    '/__tests__/',
    '\\tests\\',
    '\\test\\',
    '/test_',
    '\\test_',
    '_test.py',
    'tests.py',
]


# ============================================================
# 数据结构
# ============================================================

class SecretFinding:
    """单个密钥发现结果"""

    def __init__(
        self,
        file_path: str,
        line_number: int,
        line_content: str,
        field_type: str,
        field_name: str,
        value: str,
        severity: str = "MEDIUM",
        reason: str = "",
    ):
        self.file_path = file_path
        self.line_number = line_number
        self.line_content = line_content.strip()
        self.field_type = field_type
        self.field_name = field_name
        self.value = value
        self.severity = severity
        self.reason = reason

    def to_dict(self) -> dict:
        return {
            "file_path": self.file_path,
            "line_number": self.line_number,
            "line_content": self._mask_value(),
            "field_type": self.field_type,
            "field_name": self.field_name,
            "value_preview": self._value_preview(),
            "severity": self.severity,
            "reason": self.reason,
        }

    def _value_preview(self) -> str:
        """值的预览（脱敏）"""
        if len(self.value) <= 8:
            return "***"
        return f"{self.value[:4]}...{self.value[-4:]}"

    def _mask_value(self) -> str:
        """在行内容中脱敏密钥值"""
        return self.line_content.replace(self.value, "***MASKED***")


# ============================================================
# 扫描逻辑
# ============================================================

def should_exclude_file(file_path: Path, exclude_patterns: List[str]) -> bool:
    """判断是否应该跳过该文件"""
    # 检查文件扩展名
    if file_path.suffix.lower() in EXCLUDED_EXTENSIONS:
        return True

    # 检查目录
    parts = set(file_path.parts)
    for excluded in EXCLUDED_DIRS:
        if excluded in parts:
            return True

    # 检查用户指定的排除模式
    path_str = str(file_path).replace('\\', '/')
    for pattern in exclude_patterns:
        if pattern in path_str:
            return True

    # 跳过 .env 文件（这些本身就是配置文件）
    if file_path.name.startswith('.env'):
        return True

    return False


def classify_severity(
    value: str,
    field_type: str,
    field_name: str,
    file_path: str,
) -> Tuple[str, str]:
    """
    对发现的硬编码值进行风险分级。

    Returns:
        (severity, reason): 风险等级和原因说明
    """
    value_lower = value.lower().strip()
    file_path_norm = file_path.replace('\\', '/')

    # 1. 检查是否为高风险前缀（强特征）
    for prefix in HIGH_RISK_PREFIXES:
        if value.startswith(prefix) or value_lower.startswith(prefix.lower()):
            return "HIGH", f"匹配高风险密钥前缀: {prefix}"

    # 2. 检查是否为误报（值就是变量名/类型名）
    fp_values = FALSE_POSITIVE_FIELD_VALUES.get(field_type, set())
    if value_lower in {v.lower() for v in fp_values}:
        return "INFO", "值与字段名相同，可能是类型/占位符定义"

    # 3. 检查低风险值模式
    for pattern in LOW_RISK_VALUE_PATTERNS:
        if re.match(pattern, value_lower, re.IGNORECASE):
            return "LOW", f"值匹配低风险模式: {pattern}"

    # 4. 检查是否在测试文件中
    is_test_file = False
    for test_pattern in TEST_DIR_PATTERNS:
        if test_pattern in file_path_norm or test_pattern.lower() in file_path_norm.lower():
            is_test_file = True
            break

    # 5. 根据值的长度和复杂度判断
    if len(value) >= 32:
        # 长度足够，可能是真实密钥
        if is_test_file:
            return "MEDIUM", f"测试文件中的长密钥（{len(value)} 字符），建议验证是否为测试专用"
        return "HIGH", f"长密钥（{len(value)} 字符），疑似真实密钥"

    if len(value) >= 16:
        # 中等长度
        if is_test_file:
            return "LOW", "测试文件中的中等长度密钥"
        return "MEDIUM", f"中等长度密钥（{len(value)} 字符）"

    # 短值（可能是弱密码或测试值）
    if is_test_file:
        return "LOW", "测试文件中的短密码/密钥"
    return "MEDIUM", f"短密码/密钥（{len(value)} 字符），可能是默认值或弱密码"


def scan_file(file_path: Path) -> List[SecretFinding]:
    """扫描单个文件中的硬编码密钥"""
    findings: List[SecretFinding] = []

    try:
        with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
            lines = f.readlines()
    except Exception:
        return findings

    for line_num, line in enumerate(lines, 1):
        # 跳过注释行（Python/JS/Java 风格注释）
        stripped = line.strip()
        if stripped.startswith('#') or stripped.startswith('//') or stripped.startswith('/*'):
            # 但 docstring 中的示例也要检查，所以不完全跳过
            pass

        for pattern, field_type in SENSITIVE_FIELD_PATTERNS:
            match = re.search(pattern, line, re.IGNORECASE)
            if match:
                field_name = match.group(1)
                value = match.group(2)

                # 跳过空值
                if not value or not value.strip():
                    continue

                # 跳过纯数字的短值（可能是配置编号等）
                if value.isdigit() and len(value) < 8:
                    continue

                severity, reason = classify_severity(
                    value, field_type, field_name, str(file_path)
                )

                findings.append(SecretFinding(
                    file_path=str(file_path),
                    line_number=line_num,
                    line_content=line,
                    field_type=field_type,
                    field_name=field_name,
                    value=value,
                    severity=severity,
                    reason=reason,
                ))

    return findings


def scan_directory(
    root_path: Path,
    exclude_patterns: List[str],
    extensions: Optional[List[str]] = None,
) -> List[SecretFinding]:
    """递归扫描目录"""
    all_findings: List[SecretFinding] = []
    root_str = str(root_path)

    for dirpath, dirnames, filenames in os.walk(root_str, topdown=True):
        # 过滤要排除的目录（修改 dirnames 会影响 os.walk 的递归）
        dirnames[:] = [
            d for d in dirnames
            if d not in EXCLUDED_DIRS
            and not any(pat in d for pat in exclude_patterns)
        ]

        for filename in filenames:
            try:
                file_path = Path(dirpath) / filename

                if should_exclude_file(file_path, exclude_patterns):
                    continue

                # 如果指定了扩展名，只扫描指定类型
                if extensions:
                    if file_path.suffix.lower() not in {e.lower() for e in extensions}:
                        continue

                findings = scan_file(file_path)
                all_findings.extend(findings)
            except (OSError, PermissionError, FileNotFoundError):
                # 跳过无法访问的文件
                continue

    return all_findings


# ============================================================
# 报告生成
# ============================================================

def print_report(findings: List[SecretFinding], high_only: bool = False) -> None:
    """打印人类可读的报告"""
    # 按严重程度分组
    by_severity: Dict[str, List[SecretFinding]] = {
        "HIGH": [],
        "MEDIUM": [],
        "LOW": [],
        "INFO": [],
    }

    for f in findings:
        by_severity[f.severity].append(f)

    # 按文件分组
    by_file: Dict[str, List[SecretFinding]] = {}
    for f in findings:
        if high_only and f.severity not in ("HIGH", "MEDIUM"):
            continue
        by_file.setdefault(f.file_path, []).append(f)

    # 统计
    total = len(findings)
    high_count = len(by_severity["HIGH"])
    medium_count = len(by_severity["MEDIUM"])
    low_count = len(by_severity["LOW"])
    info_count = len(by_severity["INFO"])

    print("=" * 70)
    print("硬编码密钥扫描报告")
    print("=" * 70)
    print(f"  总发现数: {total}")
    print(f"  高危 (HIGH):   {high_count}")
    print(f"  中危 (MEDIUM): {medium_count}")
    print(f"  低危 (LOW):    {low_count}")
    print(f"  信息 (INFO):   {info_count}")
    print("=" * 70)

    if high_only:
        display_findings = [f for f in findings if f.severity in ("HIGH", "MEDIUM")]
    else:
        display_findings = findings

    if not display_findings:
        print("\n✅ 未发现需要关注的硬编码密钥问题。")
        return

    # 按文件输出
    current_file = ""
    for f in sorted(display_findings, key=lambda x: (x.file_path, x.line_number)):
        if f.file_path != current_file:
            current_file = f.file_path
            print(f"\n📁 {f.file_path}")

        severity_icon = {
            "HIGH": "🔴",
            "MEDIUM": "🟡",
            "LOW": "🟢",
            "INFO": "🔵",
        }.get(f.severity, "⚪")

        print(f"   {severity_icon} 行 {f.line_number:4d} [{f.severity:6s}] "
              f"{f.field_name} = {f._value_preview()}")
        if f.reason:
            print(f"           原因: {f.reason}")
        # 打印脱敏后的行内容
        print(f"           代码: {f._mask_value()[:100]}")

    print("\n" + "=" * 70)
    print("建议:")
    if high_count > 0:
        print("  ⚠️  发现高危密钥！请立即将这些密钥移到环境变量或密钥管理系统。")
        print("     如果是已泄露的密钥，请立即吊销并重新生成。")
    if medium_count > 0:
        print("  ⚠️  发现中危问题。建议将这些配置改为从环境变量读取，")
        print("     并在开发环境自动生成随机默认值。")
    if low_count > 0:
        print("  ℹ️  发现低危问题（多为测试/示例值）。建议统一改为环境变量配置，")
        print("     避免测试值被误用到生产环境。")
    print("=" * 70)


def save_json_report(findings: List[SecretFinding], output_path: str) -> None:
    """保存 JSON 格式报告"""
    report = {
        "summary": {
            "total": len(findings),
            "high": sum(1 for f in findings if f.severity == "HIGH"),
            "medium": sum(1 for f in findings if f.severity == "MEDIUM"),
            "low": sum(1 for f in findings if f.severity == "LOW"),
            "info": sum(1 for f in findings if f.severity == "INFO"),
        },
        "findings": [f.to_dict() for f in findings],
    }

    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(report, f, ensure_ascii=False, indent=2)

    print(f"\n📄 JSON 报告已保存到: {output_path}")


# ============================================================
# 主入口
# ============================================================

def main() -> int:
    parser = argparse.ArgumentParser(
        description="硬编码密钥扫描工具 - 检测代码中的敏感信息泄露",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  %(prog)s                          扫描当前目录
  %(prog)s --path src/              扫描指定目录
  %(prog)s --high-only              只显示高危和中危结果
  %(prog)s --exclude tests/ --exclude .git/  排除目录
  %(prog)s --json report.json       输出 JSON 报告
  %(prog)s --ext .py --ext .js      只扫描 Python 和 JS 文件
        """,
    )

    parser.add_argument(
        "--path", "-p",
        default=".",
        help="要扫描的根目录（默认: 当前目录）",
    )
    parser.add_argument(
        "--exclude", "-e",
        action="append",
        default=[],
        help="排除的目录/文件模式（可多次指定）",
    )
    parser.add_argument(
        "--ext",
        action="append",
        default=None,
        help="只扫描指定扩展名的文件（可多次指定，如 --ext .py --ext .js）",
    )
    parser.add_argument(
        "--high-only",
        action="store_true",
        help="只显示高危和中危结果",
    )
    parser.add_argument(
        "--json", "-j",
        default=None,
        help="输出 JSON 报告到指定文件",
    )
    parser.add_argument(
        "--quiet", "-q",
        action="store_true",
        help="静默模式，只输出摘要",
    )

    args = parser.parse_args()

    root_path = Path(args.path).resolve()
    if not root_path.exists():
        print(f"❌ 错误：路径不存在: {root_path}", file=sys.stderr)
        return 2

    print(f"🔍 开始扫描: {root_path}")
    if args.exclude:
        print(f"   排除模式: {', '.join(args.exclude)}")
    if args.ext:
        print(f"   文件类型: {', '.join(args.ext)}")

    findings = scan_directory(
        root_path,
        exclude_patterns=args.exclude,
        extensions=args.ext,
    )

    if not args.quiet:
        print_report(findings, high_only=args.high_only)
    else:
        # 静默模式：只输出摘要
        high = sum(1 for f in findings if f.severity == "HIGH")
        medium = sum(1 for f in findings if f.severity == "MEDIUM")
        low = sum(1 for f in findings if f.severity == "LOW")
        print(f"扫描完成: HIGH={high}, MEDIUM={medium}, LOW={low}, TOTAL={len(findings)}")

    if args.json:
        save_json_report(findings, args.json)

    # 返回码：有高危或中危则返回 1
    has_high_or_medium = any(f.severity in ("HIGH", "MEDIUM") for f in findings)
    return 1 if has_high_or_medium else 0


if __name__ == "__main__":
    sys.exit(main())
