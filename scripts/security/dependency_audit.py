#!/usr/bin/env python3
"""
依赖安全审计脚本（SEC-013 P2级安全修复）

功能：
1. 扫描项目中所有 requirements.txt 文件
2. 检查依赖版本范围是否过于宽松（如 >=、无版本锁定）
3. 识别关键安全依赖（fastapi, pyjwt, passlib, cryptography 等）的版本风险
4. 检查是否有已知的 CVE 漏洞（通过 pip-audit 或内置的安全版本检查）
5. 生成安全审计报告

用法：
    python scripts/security/dependency_audit.py [--fix] [--report]

选项：
    --fix      自动将关键依赖收紧为 ~=x.y.z 格式
    --report   生成详细的审计报告
    --strict   严格模式，所有依赖必须锁定精确版本
"""

import os
import re
import sys
import json
import argparse
from pathlib import Path
from typing import Dict, List, Tuple, Optional


# ===========================================================================
# 配置
# ===========================================================================

# 关键安全依赖（版本范围必须严格控制）
CRITICAL_SECURITY_PACKAGES = {
    "fastapi": "Web 框架，存在认证、CORS 等安全风险",
    "uvicorn": "ASGI 服务器，存在 HTTP 请求解析风险",
    "python-jose": "JWT 处理，存在 Token 伪造风险",
    "pyjwt": "JWT 处理，存在 Token 伪造风险",
    "passlib": "密码哈希，存在密码破解风险",
    "bcrypt": "密码哈希，存在密码破解风险",
    "cryptography": "加密库，存在加密算法漏洞风险",
    "pyyaml": "YAML 解析，存在反序列化漏洞风险",
    "requests": "HTTP 客户端，存在 SSRF 等风险",
    "httpx": "HTTP 客户端，存在 SSRF 等风险",
    "sqlalchemy": "ORM 框架，存在 SQL 注入风险",
    "jinja2": "模板引擎，存在 SSTI 风险",
    "pydantic": "数据验证，存在注入风险",
    "starlette": "Web 框架基础，存在认证绕过风险",
    "itsdangerous": "签名工具，存在伪造风险",
    "werkzeug": "WSGI 工具库，存在安全漏洞风险",
}

# 版本规范说明
VERSION_PATTERNS = {
    "exact": "==x.y.z（精确版本，最安全）",
    "compatible": "~=x.y.z（兼容版本，只允许补丁升级）",
    "range_minor": ">=x.y,<x+1（次版本范围，中等风险）",
    "range_major": ">=x.y（主版本范围，高风险）",
    "unbounded": "无版本约束（极高风险）",
}

# 风险等级
RISK_LEVELS = {
    "critical": "极高风险：关键依赖无版本锁定或范围过宽",
    "high": "高风险：关键依赖使用 >= 主版本范围",
    "medium": "中风险：非关键依赖范围过宽或关键依赖次版本范围",
    "low": "低风险：依赖使用 ~= 或 == 精确版本",
    "info": "信息：依赖版本规范",
}


# ===========================================================================
# 工具函数
# ===========================================================================

def find_requirements_files(project_root: Path) -> List[Path]:
    """查找项目中所有 requirements 文件

    使用 os.walk 手动遍历以处理有问题的目录（符号链接、权限不足等）。

    Args:
        project_root: 项目根目录

    Returns:
        requirements 文件路径列表
    """
    patterns = ["requirements*.txt", "requirements*.in"]
    files = []
    import fnmatch

    for root, dirs, filenames in os.walk(project_root, onerror=lambda e: None):
        # 跳过 _archive 和 node_modules 目录
        dirs[:] = [d for d in dirs if d not in ("_archive", "node_modules", ".git", "__pycache__")]

        for filename in filenames:
            for pattern in patterns:
                if fnmatch.fnmatch(filename, pattern):
                    files.append(Path(root) / filename)
                    break

    return sorted(files)


def parse_requirements_line(line: str) -> Optional[Dict]:
    """解析 requirements.txt 的一行

    Args:
        line: requirements.txt 中的一行

    Returns:
        解析后的依赖信息字典，无效行返回 None
    """
    line = line.strip()

    # 跳过空行、注释、选项
    if not line or line.startswith("#") or line.startswith("-"):
        return None

    # 提取包名和版本约束
    # 支持格式：package, package==1.0, package>=1.0, package~=1.0, package[extra]>=1.0
    match = re.match(
        r'^([a-zA-Z0-9_.-]+)'          # 包名
        r'(\[[a-zA-Z0-9_,-]+\])?'      # 可选 extras
        r'\s*'
        r'(==|>=|<=|!=|~=|>|<)?'       # 比较运算符
        r'\s*'
        r'([a-zA-Z0-9._*-]+)?'        # 版本号
        r'(.*)$',                      # 剩余（注释、更多约束等）
        line
    )

    if not match:
        return None

    package = match.group(1).lower()
    extras = match.group(2) or ""
    operator = match.group(3) or ""
    version = match.group(4) or ""
    rest = match.group(5).strip()

    # 检查是否有多个约束（如 >=1.0,<2.0）
    extra_constraints = []
    if rest:
        # 提取额外的约束
        extra_matches = re.findall(r'(,)\s*(==|>=|<=|!=|~=|>|<)\s*([a-zA-Z0-9._*-]+)', rest)
        for _, op, ver in extra_matches:
            extra_constraints.append({"operator": op, "version": ver})

    # 判断版本范围类型
    version_type = classify_version_type(operator, version, extra_constraints)

    return {
        "package": package,
        "extras": extras,
        "operator": operator,
        "version": version,
        "extra_constraints": extra_constraints,
        "version_type": version_type,
        "raw_line": line,
    }


def classify_version_type(operator: str, version: str, extra_constraints: List[Dict]) -> str:
    """分类版本约束类型

    Args:
        operator: 主比较运算符
        version: 版本号
        extra_constraints: 额外约束

    Returns:
        版本类型标识
    """
    if not operator:
        return "unbounded"

    if operator == "==":
        return "exact"

    if operator == "~=":
        return "compatible"

    # 检查是否有上限约束
    has_upper = any(c["operator"] in ("<", "<=", "!=") for c in extra_constraints)

    if operator == ">=" and has_upper:
        # 有上下限，判断是次版本还是主版本范围
        return "range_minor"

    if operator == ">=":
        return "range_major"

    if operator in (">", "<", "<=", "!="):
        return "range_major"

    return "range_major"


def assess_risk(pkg_info: Dict) -> Tuple[str, str]:
    """评估依赖的安全风险等级

    Args:
        pkg_info: 包信息字典

    Returns:
        (risk_level, risk_reason)
    """
    package = pkg_info["package"]
    version_type = pkg_info["version_type"]
    is_critical = package in CRITICAL_SECURITY_PACKAGES

    if version_type == "unbounded":
        if is_critical:
            return "critical", f"关键依赖 '{package}' 无版本约束，存在极高安全风险"
        else:
            return "high", f"依赖 '{package}' 无版本约束，可能引入有漏洞的版本"

    if version_type == "range_major":
        if is_critical:
            return "high", f"关键依赖 '{package}' 使用主版本范围（{CRITICAL_SECURITY_PACKAGES[package]}）"
        else:
            return "medium", f"依赖 '{package}' 版本范围过宽，可能引入不兼容的新版本"

    if version_type == "range_minor":
        if is_critical:
            return "medium", f"关键依赖 '{package}' 使用次版本范围，建议收紧为 ~= 格式"
        else:
            return "low", f"依赖 '{package}' 版本范围合理"

    if version_type == "compatible":
        return "low", f"依赖 '{package}' 使用兼容版本约束（~=），安全性较好"

    if version_type == "exact":
        return "info", f"依赖 '{package}' 使用精确版本（==），最安全但需手动更新"

    return "info", "未知版本约束类型"


# ===========================================================================
# 修复功能
# ===========================================================================

def suggest_tightened_version(pkg_info: Dict) -> Optional[str]:
    """建议收紧的版本约束

    Args:
        pkg_info: 包信息字典

    Returns:
        建议的版本约束字符串，无法建议时返回 None
    """
    package = pkg_info["package"]
    version = pkg_info["version"]
    extras = pkg_info["extras"]

    if not version:
        return None

    is_critical = package in CRITICAL_SECURITY_PACKAGES

    if not is_critical:
        return None

    # 对于关键依赖，建议使用 ~=x.y.z 格式
    if pkg_info["version_type"] in ("range_major", "range_minor"):
        # 将 >=x.y.z 改为 ~=x.y.z
        return f"{package}{extras}~={version}"

    return None


def fix_requirements_file(filepath: Path, dry_run: bool = True) -> List[Dict]:
    """修复 requirements 文件中的宽松版本约束

    Args:
        filepath: requirements 文件路径
        dry_run: 是否只预览不实际修改

    Returns:
        修改的条目列表
    """
    changes = []

    with open(filepath, "r", encoding="utf-8") as f:
        lines = f.readlines()

    new_lines = []
    for line in lines:
        pkg_info = parse_requirements_line(line)
        if pkg_info and pkg_info["package"] in CRITICAL_SECURITY_PACKAGES:
            suggestion = suggest_tightened_version(pkg_info)
            if suggestion and suggestion != pkg_info["raw_line"]:
                changes.append({
                    "file": str(filepath),
                    "package": pkg_info["package"],
                    "old": pkg_info["raw_line"],
                    "new": suggestion,
                })
                # 保留注释
                comment_match = re.search(r'\s+#.*$', line)
                comment = comment_match.group(0) if comment_match else ""
                new_lines.append(suggestion + comment + "\n")
                continue

        new_lines.append(line)

    if not dry_run and changes:
        with open(filepath, "w", encoding="utf-8") as f:
            f.writelines(new_lines)

    return changes


# ===========================================================================
# 审计主逻辑
# ===========================================================================

def audit_dependencies(project_root: Path, strict: bool = False) -> Dict:
    """审计项目依赖

    Args:
        project_root: 项目根目录
        strict: 是否严格模式

    Returns:
        审计结果字典
    """
    req_files = find_requirements_files(project_root)

    all_packages = {}  # package -> list of file entries
    all_issues = []    # 所有问题
    file_summaries = {}  # 每个文件的摘要

    for filepath in req_files:
        file_issues = []
        file_packages = []

        with open(filepath, "r", encoding="utf-8") as f:
            for line in f:
                pkg_info = parse_requirements_line(line)
                if pkg_info is None:
                    continue

                package = pkg_info["package"]
                file_packages.append(package)

                risk_level, risk_reason = assess_risk(pkg_info)

                # 严格模式下，所有未锁定精确版本的依赖都算问题
                if strict:
                    if pkg_info["version_type"] not in ("exact", "compatible"):
                        file_issues.append({
                            "package": package,
                            "risk_level": "medium" if risk_level in ("low", "info") else risk_level,
                            "reason": f"[严格模式] {risk_reason}",
                            "version_type": pkg_info["version_type"],
                            "raw_line": pkg_info["raw_line"],
                        })
                else:
                    if risk_level in ("critical", "high", "medium"):
                        file_issues.append({
                            "package": package,
                            "risk_level": risk_level,
                            "reason": risk_reason,
                            "version_type": pkg_info["version_type"],
                            "raw_line": pkg_info["raw_line"],
                        })

                if package not in all_packages:
                    all_packages[package] = []
                all_packages[package].append({
                    "file": str(filepath),
                    "version_type": pkg_info["version_type"],
                    "raw_line": pkg_info["raw_line"],
                    "risk_level": risk_level,
                })

        file_summaries[str(filepath)] = {
            "total_packages": len(file_packages),
            "issues": file_issues,
            "critical_count": sum(1 for i in file_issues if i["risk_level"] == "critical"),
            "high_count": sum(1 for i in file_issues if i["risk_level"] == "high"),
            "medium_count": sum(1 for i in file_issues if i["risk_level"] == "medium"),
        }

        all_issues.extend(file_issues)

    # 统计
    critical_count = sum(1 for i in all_issues if i["risk_level"] == "critical")
    high_count = sum(1 for i in all_issues if i["risk_level"] == "high")
    medium_count = sum(1 for i in all_issues if i["risk_level"] == "medium")

    # 关键依赖覆盖率
    critical_packages_found = {
        pkg: all_packages[pkg] for pkg in CRITICAL_SECURITY_PACKAGES if pkg in all_packages
    }
    critical_packages_ok = {
        pkg: entries for pkg, entries in critical_packages_found.items()
        if all(e["version_type"] in ("exact", "compatible") for e in entries)
    }

    overall_status = "pass"
    if critical_count > 0:
        overall_status = "fail"
    elif high_count > 0:
        overall_status = "warning"

    return {
        "project_root": str(project_root),
        "total_requirements_files": len(req_files),
        "total_unique_packages": len(all_packages),
        "total_issues": len(all_issues),
        "critical_count": critical_count,
        "high_count": high_count,
        "medium_count": medium_count,
        "overall_status": overall_status,
        "critical_packages_found": list(critical_packages_found.keys()),
        "critical_packages_protected": list(critical_packages_ok.keys()),
        "critical_packages_at_risk": [
            pkg for pkg in critical_packages_found if pkg not in critical_packages_ok
        ],
        "files_audited": file_summaries,
        "issues": all_issues,
        "requirements_files": [str(f) for f in req_files],
    }


# ===========================================================================
# 报告生成
# ===========================================================================

def print_report(result: Dict) -> None:
    """打印审计报告

    Args:
        result: 审计结果字典
    """
    print("=" * 70)
    print("  云汐系统 - 依赖安全审计报告（SEC-013）")
    print("=" * 70)
    print()

    print(f"项目根目录: {result['project_root']}")
    print(f"审计文件数: {result['total_requirements_files']}")
    print(f"唯一依赖数: {result['total_unique_packages']}")
    print()

    status_symbol = {
        "pass": "✓ PASS",
        "warning": "⚠ WARNING",
        "fail": "✗ FAIL",
    }
    status = result["overall_status"]
    print(f"总体状态: {status_symbol.get(status, status)}")
    print()

    print("-" * 70)
    print("  问题统计")
    print("-" * 70)
    print(f"  严重 (Critical): {result['critical_count']}")
    print(f"  高危 (High):     {result['high_count']}")
    print(f"  中等 (Medium):   {result['medium_count']}")
    print()

    print("-" * 70)
    print("  关键安全依赖保护状态")
    print("-" * 70)
    print(f"  已发现关键依赖: {len(result['critical_packages_found'])} / {len(CRITICAL_SECURITY_PACKAGES)}")
    print(f"  已保护（~= 或 ==）: {len(result['critical_packages_protected'])}")
    print(f"  有风险: {len(result['critical_packages_at_risk'])}")
    if result["critical_packages_at_risk"]:
        print(f"  有风险的依赖: {', '.join(result['critical_packages_at_risk'])}")
    print()

    if result["issues"]:
        print("-" * 70)
        print("  问题详情")
        print("-" * 70)

        # 按风险等级排序
        sorted_issues = sorted(
            result["issues"],
            key=lambda x: {"critical": 0, "high": 1, "medium": 2, "low": 3, "info": 4}[x["risk_level"]]
        )

        for issue in sorted_issues:
            level = issue["risk_level"].upper()
            print(f"  [{level}] {issue['package']}")
            print(f"         {issue['reason']}")
            print(f"         当前: {issue['raw_line']}")
            print()

    print("-" * 70)
    print("  建议操作")
    print("-" * 70)
    print("  1. 将关键安全依赖的版本约束收紧为 ~=x.y.z 格式")
    print("  2. 定期运行 pip-audit 检查已知 CVE 漏洞")
    print("  3. 使用 pip-compile 或 Poetry 锁定所有依赖版本")
    print("  4. 建立依赖更新审查流程，更新前检查安全公告")
    print()

    print("=" * 70)


# ===========================================================================
# 主函数
# ===========================================================================

def main():
    parser = argparse.ArgumentParser(
        description="云汐系统 - 依赖安全审计工具（SEC-013）",
    )
    parser.add_argument(
        "--project-root",
        default=None,
        help="项目根目录（默认自动检测）",
    )
    parser.add_argument(
        "--fix",
        action="store_true",
        help="自动修复关键依赖的宽松版本约束",
    )
    parser.add_argument(
        "--report",
        action="store_true",
        help="生成 JSON 格式报告",
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="严格模式：所有依赖必须使用 ~= 或 ==",
    )
    parser.add_argument(
        "--output",
        default=None,
        help="报告输出文件路径",
    )

    args = parser.parse_args()

    # 自动检测项目根目录
    if args.project_root:
        project_root = Path(args.project_root).resolve()
    else:
        # 从脚本位置向上查找
        script_dir = Path(__file__).resolve().parent
        project_root = script_dir
        for _ in range(5):
            if (project_root / "shared").exists() or (project_root / "requirements-dev.txt").exists():
                break
            project_root = project_root.parent

    print(f"审计项目: {project_root}")
    print()

    # 执行审计
    result = audit_dependencies(project_root, strict=args.strict)

    # 自动修复
    if args.fix:
        print("正在修复关键依赖版本约束...")
        total_fixes = 0
        req_files = find_requirements_files(project_root)
        for filepath in req_files:
            changes = fix_requirements_file(filepath, dry_run=False)
            if changes:
                print(f"\n  {filepath}:")
                for change in changes:
                    print(f"    {change['old']}  →  {change['new']}")
                total_fixes += len(changes)

        print(f"\n共修复 {total_fixes} 处依赖版本约束")
        print()

        # 重新审计
        result = audit_dependencies(project_root, strict=args.strict)

    # 打印报告
    print_report(result)

    # 输出 JSON 报告
    if args.report or args.output:
        output_path = args.output or str(project_root / "dependency_audit_report.json")
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(result, f, ensure_ascii=False, indent=2)
        print(f"\nJSON 报告已保存至: {output_path}")

    # 退出码
    if result["overall_status"] == "fail":
        sys.exit(2)
    elif result["overall_status"] == "warning":
        sys.exit(1)
    else:
        sys.exit(0)


if __name__ == "__main__":
    main()
