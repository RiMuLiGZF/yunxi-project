#!/usr/bin/env python3
"""
测试环境配置安全检查脚本（SEC-008）

用于 CI/CD 流水线中，防止测试环境的弱密码、弱密钥泄露到生产环境。

检查内容：
1. 检测 .env.test 中是否使用了常见弱密码
2. 检测 JWT 密钥是否为弱密钥或默认值
3. 检测测试环境是否与生产环境使用相同的密钥
4. 验证 .env.test 是否在 .gitignore 中

用法：
    python scripts/test_env_security_check.py [--strict]

退出码：
    0 - 所有检查通过
    1 - 发现安全问题
"""

import re
import sys
import os
from pathlib import Path
from typing import List, Tuple


# 常见弱密码列表（黑名单）
WEAK_PASSWORDS = {
    "admin123456",
    "password",
    "123456",
    "12345678",
    "123456789",
    "admin",
    "changeme",
    "default",
    "qwerty",
    "abc123",
    "password123",
    "admin@123",
    "test123",
    "test123456",
    "yunxi123",
    "yunxi2026",
    "Test@123",
    "test@123",
}

# 常见弱密钥列表
WEAK_SECRETS = {
    "yunxi-test-jwt-secret-2026",
    "yunxi-jwt-secret",
    "your-secret-key",
    "secret",
    "changeme",
    "default-secret",
    "test-secret",
    "dev-secret",
}

# 弱密钥前缀模式
WEAK_SECRET_PATTERNS = [
    re.compile(r'^CHANGEME_', re.IGNORECASE),
    re.compile(r'^yunxi-', re.IGNORECASE),
    re.compile(r'^test-', re.IGNORECASE),
    re.compile(r'^dev-', re.IGNORECASE),
]


def load_env_file(filepath: Path) -> dict:
    """加载 .env 文件为字典"""
    env = {}
    if not filepath.exists():
        return env
    with open(filepath, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" in line:
                key, value = line.split("=", 1)
                env[key.strip()] = value.strip()
    return env


def check_weak_password(env: dict) -> List[Tuple[str, str]]:
    """检查测试环境密码是否为弱密码"""
    issues = []
    password_keys = [
        "TEST_ADMIN_PASSWORD",
        "TEST_PASSWORD",
        "M8_ADMIN_PASSWORD",
        "ADMIN_PASSWORD",
    ]
    for key in password_keys:
        value = env.get(key, "")
        if not value:
            continue
        if value.lower() in {p.lower() for p in WEAK_PASSWORDS}:
            issues.append((key, f"使用了常见弱密码: {value}"))
        elif len(value) < 12:
            issues.append((key, f"密码长度不足 12 位（当前 {len(value)} 位）"))
    return issues


def check_weak_jwt_secret(env: dict) -> List[Tuple[str, str]]:
    """检查 JWT 密钥是否为弱密钥"""
    issues = []
    secret_keys = [
        "JWT_SECRET",
        "TEST_JWT_SECRET",
        "M8_JWT_SECRET",
    ]
    for key in secret_keys:
        value = env.get(key, "")
        if not value:
            continue
        if value.lower() in {s.lower() for s in WEAK_SECRETS}:
            issues.append((key, f"使用了弱密钥: {value}"))
        elif any(pat.match(value) for pat in WEAK_SECRET_PATTERNS):
            issues.append((key, f"密钥使用了弱前缀模式: {value[:20]}..."))
        elif len(value) < 32:
            issues.append((key, f"密钥长度不足 32 字节（当前 {len(value)} 字符）"))
    return issues


def check_gitignore(project_root: Path) -> List[Tuple[str, str]]:
    """检查 .env.test 是否在 .gitignore 中"""
    issues = []
    gitignore_path = project_root / ".gitignore"
    if not gitignore_path.exists():
        issues.append((".gitignore", "文件不存在"))
        return issues

    with open(gitignore_path, "r", encoding="utf-8") as f:
        content = f.read()

    # 检查是否包含 .env.test
    if ".env.test" not in content and "*.env" not in content:
        issues.append((".env.test", "未在 .gitignore 中，可能被提交到仓库"))

    # 检查是否有例外规则覆盖了 .env.test
    if "!.env.test" in content:
        issues.append((".env.test", "存在 !.env.test 例外规则，会被提交到仓库"))

    return issues


def check_test_db_isolation(env: dict) -> List[Tuple[str, str]]:
    """检查测试数据库是否与生产环境隔离"""
    issues = []
    db_url = env.get("TEST_DATABASE_URL", "")
    if db_url and ("test" not in db_url.lower()):
        issues.append(("TEST_DATABASE_URL", "测试数据库名称不含 'test'，可能与开发/生产数据库混淆"))
    return issues


def check_env_separation(test_env: dict, prod_env_path: Path) -> List[Tuple[str, str]]:
    """检查测试环境与生产环境密钥是否分离"""
    issues = []
    if not prod_env_path.exists():
        return issues

    prod_env = load_env_file(prod_env_path)
    sensitive_keys = ["JWT_SECRET", "ADMIN_PASSWORD", "M8_ADMIN_PASSWORD"]
    for key in sensitive_keys:
        test_val = test_env.get(key, "")
        prod_val = prod_env.get(key, "")
        if test_val and prod_val and test_val == prod_val:
            issues.append((key, "测试环境与生产环境使用了相同的密钥/密码"))
    return issues


def run_checks(project_root: Path, strict: bool = False) -> int:
    """运行所有安全检查

    Args:
        project_root: 项目根目录
        strict: 是否启用严格模式

    Returns:
        问题数量（0 表示全部通过）
    """
    print("=" * 60)
    print("测试环境配置安全检查（SEC-008）")
    print("=" * 60)

    test_env_path = project_root / ".env.test"
    prod_env_path = project_root / "config" / "yunxi.env"

    all_issues: List[Tuple[str, str, str]] = []  # (check_name, key, message)

    # 加载测试环境配置
    test_env = load_env_file(test_env_path)
    if not test_env:
        print(f"\n[WARN] 未找到 .env.test 文件: {test_env_path}")
        print("       跳过测试环境配置检查")
    else:
        print(f"\n[INFO] 已加载测试环境配置: {test_env_path}")

        # 1. 弱密码检查
        print("\n--- 弱密码检查 ---")
        pwd_issues = check_weak_password(test_env)
        if pwd_issues:
            for key, msg in pwd_issues:
                print(f"  [FAIL] {key}: {msg}")
                all_issues.append(("weak_password", key, msg))
        else:
            print("  [PASS] 未发现弱密码")

        # 2. 弱 JWT 密钥检查
        print("\n--- 弱 JWT 密钥检查 ---")
        jwt_issues = check_weak_jwt_secret(test_env)
        if jwt_issues:
            for key, msg in jwt_issues:
                print(f"  [FAIL] {key}: {msg}")
                all_issues.append(("weak_jwt_secret", key, msg))
        else:
            print("  [PASS] JWT 密钥强度合格")

        # 3. 测试数据库隔离检查
        print("\n--- 测试数据库隔离检查 ---")
        db_issues = check_test_db_isolation(test_env)
        if db_issues:
            for key, msg in db_issues:
                print(f"  [WARN] {key}: {msg}")
                if strict:
                    all_issues.append(("db_isolation", key, msg))
        else:
            print("  [PASS] 测试数据库隔离正常")

        # 4. 测试与生产环境密钥分离检查
        print("\n--- 测试/生产环境密钥分离检查 ---")
        sep_issues = check_env_separation(test_env, prod_env_path)
        if sep_issues:
            for key, msg in sep_issues:
                print(f"  [FAIL] {key}: {msg}")
                all_issues.append(("env_separation", key, msg))
        else:
            print("  [PASS] 测试/生产环境密钥已分离（或生产环境配置不存在）")

    # 5. .gitignore 检查
    print("\n--- .gitignore 检查 ---")
    gi_issues = check_gitignore(project_root)
    if gi_issues:
        for key, msg in gi_issues:
            print(f"  [FAIL] {key}: {msg}")
            all_issues.append(("gitignore", key, msg))
    else:
        print("  [PASS] .env.test 已正确加入 .gitignore")

    # 总结
    print("\n" + "=" * 60)
    fail_count = len(all_issues)
    if fail_count == 0:
        print("[PASS] 所有安全检查通过！")
        print("=" * 60)
        return 0
    else:
        print(f"[FAIL] 发现 {fail_count} 个安全问题：")
        for i, (check_name, key, msg) in enumerate(all_issues, 1):
            print(f"  {i}. [{check_name}] {key}: {msg}")
        print("\n修复建议：")
        print("  1. 使用随机强密码替换弱密码（推荐 16+ 位，包含大小写字母、数字、特殊字符）")
        print("  2. 使用 openssl rand -hex 32 或 secrets.token_urlsafe(48) 生成强密钥")
        print("  3. 确保测试环境与生产环境使用完全不同的密钥")
        print("  4. 将 .env.test 加入 .gitignore")
        print("=" * 60)
        return fail_count


def main():
    import argparse
    parser = argparse.ArgumentParser(description="测试环境配置安全检查")
    parser.add_argument(
        "--strict",
        action="store_true",
        help="启用严格模式（包括警告级别的问题）",
    )
    parser.add_argument(
        "--project-root",
        type=str,
        default=None,
        help="项目根目录路径",
    )
    args = parser.parse_args()

    if args.project_root:
        project_root = Path(args.project_root)
    else:
        # 脚本位于 scripts/ 目录，项目根目录在上一级
        project_root = Path(__file__).resolve().parent.parent

    exit_code = run_checks(project_root, strict=args.strict)
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
