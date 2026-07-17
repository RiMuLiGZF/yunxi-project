# -*- coding: utf-8 -*-
"""
SEC-008 测试：测试环境配置安全检查

验证测试环境配置的安全性：
1. 弱密码检测
2. 弱 JWT 密钥检测
3. .gitignore 检查
4. 测试/生产环境密钥分离
5. test_env_security_check.py 脚本功能验证
"""

import sys
import os
import pytest
import tempfile
import secrets
import importlib.util
from pathlib import Path

# 将项目根目录加入 path
_project_root = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(_project_root))

# 直接加载 test_env_security_check 模块
_check_script_path = _project_root / "scripts" / "test" / "test_env_security_check.py"
_spec = importlib.util.spec_from_file_location("test_env_security_check", _check_script_path)
_test_env_check = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_test_env_check)

check_weak_password = _test_env_check.check_weak_password
check_weak_jwt_secret = _test_env_check.check_weak_jwt_secret
check_gitignore = _test_env_check.check_gitignore
check_env_separation = _test_env_check.check_env_separation
check_test_db_isolation = _test_env_check.check_test_db_isolation
load_env_file = _test_env_check.load_env_file
run_checks = _test_env_check.run_checks


class TestEnvSecurityCheck:
    """测试环境配置安全检查"""

    def test_check_weak_password_detects_common_passwords(self):
        """测试弱密码检测函数能正确识别常见弱密码"""
        weak_env = {
            "TEST_ADMIN_PASSWORD": "admin123456",
        }
        issues = check_weak_password(weak_env)
        assert len(issues) >= 1
        assert any("admin123456" in msg for _, msg in issues)

    def test_check_weak_password_accepts_strong_passwords(self):
        """测试强密码能通过检测"""
        strong_env = {
            "TEST_ADMIN_PASSWORD": "X9#k2$Lm8!pQr4@nZ",
        }
        issues = check_weak_password(strong_env)
        assert len(issues) == 0

    def test_check_weak_password_min_length(self):
        """测试密码长度检查"""
        short_env = {
            "TEST_ADMIN_PASSWORD": "short",
        }
        issues = check_weak_password(short_env)
        assert len(issues) >= 1
        assert any("长度不足" in msg for _, msg in issues)

    def test_check_weak_jwt_secret_detects_weak_secrets(self):
        """测试弱 JWT 密钥检测"""
        weak_env = {
            "JWT_SECRET": "yunxi-test-jwt-secret-2026",
        }
        issues = check_weak_jwt_secret(weak_env)
        assert len(issues) >= 1

    def test_check_weak_jwt_secret_accepts_strong_secrets(self):
        """测试强 JWT 密钥能通过检测"""
        strong_secret = secrets.token_urlsafe(48)
        strong_env = {
            "JWT_SECRET": strong_secret,
        }
        issues = check_weak_jwt_secret(strong_env)
        assert len(issues) == 0

    def test_check_weak_jwt_secret_min_length(self):
        """测试 JWT 密钥长度检查"""
        short_env = {
            "JWT_SECRET": "short",
        }
        issues = check_weak_jwt_secret(short_env)
        assert len(issues) >= 1
        assert any("不足" in msg for _, msg in issues)

    def test_check_weak_jwt_secret_weak_prefix(self):
        """测试弱密钥前缀检测"""
        changeme_env = {
            "JWT_SECRET": "CHANGEME_test_secret",
        }
        issues = check_weak_jwt_secret(changeme_env)
        assert len(issues) >= 1
        assert any("弱前缀" in msg for _, msg in issues)

    def test_check_gitignore_with_env_test(self):
        """测试 .gitignore 检查"""
        with tempfile.TemporaryDirectory() as tmpdir:
            gitignore_path = Path(tmpdir) / ".gitignore"
            gitignore_path.write_text(
                "# 环境变量\n*.env\n!.env.example\n.env.test\n",
                encoding="utf-8",
            )
            issues = check_gitignore(Path(tmpdir))
            assert len(issues) == 0

    def test_check_gitignore_missing_env_test(self):
        """测试缺少 .env.test 的 .gitignore 会报警"""
        with tempfile.TemporaryDirectory() as tmpdir:
            gitignore_path = Path(tmpdir) / ".gitignore"
            gitignore_path.write_text(
                "*.log\n__pycache__/\n",
                encoding="utf-8",
            )
            issues = check_gitignore(Path(tmpdir))
            assert len(issues) >= 1
            assert any(".env.test" in key for key, _ in issues)

    def test_check_env_separation_different_keys(self):
        """测试测试/生产环境密钥分离检查（不同密钥应该通过）"""
        with tempfile.TemporaryDirectory() as tmpdir:
            prod_env_path = Path(tmpdir) / "config" / "yunxi.env"
            prod_env_path.parent.mkdir(parents=True, exist_ok=True)
            prod_env_path.write_text(
                "JWT_SECRET=prod-secret-key-very-long-and-secure-1234567890\n",
                encoding="utf-8",
            )

            test_env = {
                "JWT_SECRET": "test-secret-key-different-from-prod-0987654321",
            }

            issues = check_env_separation(test_env, prod_env_path)
            assert len(issues) == 0

    def test_check_env_separation_same_keys(self):
        """测试测试/生产环境使用相同密钥时应该报警"""
        with tempfile.TemporaryDirectory() as tmpdir:
            shared_secret = "shared-secret-key-very-long-1234567890"
            prod_env_path = Path(tmpdir) / "config" / "yunxi.env"
            prod_env_path.parent.mkdir(parents=True, exist_ok=True)
            prod_env_path.write_text(
                f"JWT_SECRET={shared_secret}\n",
                encoding="utf-8",
            )

            test_env = {
                "JWT_SECRET": shared_secret,
            }

            issues = check_env_separation(test_env, prod_env_path)
            assert len(issues) >= 1
            assert any("相同" in msg for _, msg in issues)

    def test_check_test_db_isolation(self):
        """测试测试数据库隔离检查"""
        test_env = {"TEST_DATABASE_URL": "sqlite:///./tests/data/test_m8.db"}
        issues = check_test_db_isolation(test_env)
        assert len(issues) == 0

        prod_like_env = {"TEST_DATABASE_URL": "sqlite:///./data/m8.db"}
        issues = check_test_db_isolation(prod_like_env)
        assert len(issues) >= 1
        assert any("test" in msg.lower() for _, msg in issues)

    def test_load_env_file(self):
        """测试 .env 文件加载函数"""
        with tempfile.TemporaryDirectory() as tmpdir:
            env_path = Path(tmpdir) / ".env.test"
            env_path.write_text(
                """# 测试配置
TEST_USER=admin
TEST_PASS=secret123
# 注释行
JWT_SECRET=test-jwt-key
""",
                encoding="utf-8",
            )

            env = load_env_file(env_path)
            assert env["TEST_USER"] == "admin"
            assert env["TEST_PASS"] == "secret123"
            assert env["JWT_SECRET"] == "test-jwt-key"
            assert len(env) == 3

    def test_run_checks_clean_env(self):
        """测试 run_checks 在干净环境中返回 0"""
        with tempfile.TemporaryDirectory() as tmpdir:
            gitignore = Path(tmpdir) / ".gitignore"
            gitignore.write_text("*.env\n.env.test\n", encoding="utf-8")

            env_test = Path(tmpdir) / ".env.test"
            env_test.write_text(
                f"TEST_ADMIN_PASSWORD={secrets.token_urlsafe(16)}\n"
                f"JWT_SECRET={secrets.token_urlsafe(48)}\n"
                f"TEST_DATABASE_URL=sqlite:///./tests/test.db\n",
                encoding="utf-8",
            )

            exit_code = run_checks(Path(tmpdir), strict=False)
            assert exit_code == 0

    def test_actual_env_test_passes(self):
        """测试实际项目中的 .env.test 能通过所有检查"""
        project_root = _project_root
        exit_code = run_checks(project_root, strict=False)
        assert exit_code == 0, "实际的 .env.test 应该通过所有安全检查"
